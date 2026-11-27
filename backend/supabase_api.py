"""
Upload + status API (replaces the upload Lambda). FastAPI; run:
    uvicorn supabase_api:app --app-dir backend --port 8000
Browser never sees the service-role key; it gets short-lived signed upload/download URLs.
"""
import datetime as dt
import hmac
import os
import re
import time
import uuid
from collections import defaultdict, deque

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from media_common import media_type, slugify
from quality_metrics import psnr_label
from supabase_config import ALLOWED_MIME_PREFIXES, INPUT_BUCKET, MAX_INPUT_MB, OUTPUT_BUCKET, load_env_config

load_env_config()

WORKER_TOKEN = os.environ.get("WORKER_TRIGGER_TOKEN", "")
PROCESS_INLINE = os.environ.get("PROCESS_INLINE", "false").lower() == "true"
ID_RE = re.compile(r"^[a-z0-9-]{1,64}$")
UPLOADS_PER_HOUR = int(os.environ.get("UPLOADS_PER_HOUR", "30"))   # per client IP
MAX_PENDING = int(os.environ.get("MAX_PENDING_UPLOADS", "200"))     # rows stuck in UPLOADING/UPLOADED
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
CODESPACES_ORIGIN_REGEX = r"https://.*\.(app\.github\.dev|githubpreview\.dev)"


def new_media_id(filename: str) -> str:
    """readable slug + 80 random bits (the id is the only thing protecting a status page)."""
    return f"{slugify(filename)}-{uuid.uuid4().hex[:20]}"


class RateLimiter:
    def __init__(self, limit, window=3600):
        self.limit, self.window, self.hits = limit, window, defaultdict(deque)

    def allow(self, key):
        now, q = time.time(), self.hits[key]
        while q and now - q[0] > self.window:
            q.popleft()
        if len(q) >= self.limit:
            return False
        q.append(now)
        return True


MAX_BATCH_IDS = 20


def summarize(rows):
    if not rows:
        rows = []
    done = [r for r in rows if r.get("status") == "COMPLETED"]
    orig = sum(int(r.get("original_size") or 0) for r in done)
    opt = sum(int(r.get("optimized_size") or 0) for r in done)
    pcts = []
    for r in done:
        val = r.get("compression_percentage")
        if val is not None and val != "":
            try:
                pcts.append(float(val))
            except (ValueError, TypeError):
                pass

    psnrs = []
    for r in done:
        val = r.get("psnr_db")
        if val is not None and val != "":
            try:
                psnrs.append(float(val))
            except (ValueError, TypeError):
                pass

    proc_times = []
    for r in done:
        val = r.get("processing_time")
        if val is not None and val != "":
            try:
                proc_times.append(float(val))
            except (ValueError, TypeError):
                pass

    # Media type distribution
    type_counts = {"image": 0, "video": 0}
    for r in rows:
        mt = (r.get("media_type") or "").lower()
        if mt == "image" or "image" in mt:
            type_counts["image"] += 1
        elif mt == "video" or "video" in mt:
            type_counts["video"] += 1

    # Output format distribution
    format_counts = {}
    for r in done:
        settings = r.get("settings_used")
        fmt_name = ""
        if isinstance(settings, dict):
            fmt_name = settings.get("format") or settings.get("output_format") or ""
        if not fmt_name and (r.get("media_type") == "video" or "video" in (r.get("media_type") or "")):
            fmt_name = "mp4"
        elif not fmt_name:
            fmt_name = "webp"
        fmt_name = str(fmt_name).upper()
        format_counts[fmt_name] = format_counts.get(fmt_name, 0) + 1

    # Daily activity (grouped by YYYY-MM-DD)
    daily = {}
    for r in rows:
        created = r.get("created_at")
        if created:
            date_str = str(created)[:10]
        else:
            date_str = dt.date.today().isoformat()
        if date_str not in daily:
            daily[date_str] = {"date": date_str, "uploaded": 0, "completed": 0, "bytes_saved": 0}
        daily[date_str]["uploaded"] += 1
        if r.get("status") == "COMPLETED":
            daily[date_str]["completed"] += 1
            o = int(r.get("original_size") or 0)
            n = int(r.get("optimized_size") or 0)
            if o > n:
                daily[date_str]["bytes_saved"] += (o - n)
    daily_list = sorted(daily.values(), key=lambda d: d["date"])[-14:]

    # Quality distribution buckets (PSNR tiers)
    quality_buckets = {
        "excellent_35_plus": sum(1 for p in psnrs if p >= 35.0),
        "good_30_35": sum(1 for p in psnrs if 30.0 <= p < 35.0),
        "acceptable_25_30": sum(1 for p in psnrs if 25.0 <= p < 30.0),
        "low_under_25": sum(1 for p in psnrs if p < 25.0),
    }

    return {
        "total_files": len(rows),
        "files_processed": len(done),
        "failed": sum(r.get("status") == "FAILED" for r in rows),
        "in_progress": sum(r.get("status") in ("UPLOADING", "UPLOADED", "PROCESSING") for r in rows),
        "total_original_bytes": orig,
        "total_optimized_bytes": opt,
        "total_saved_bytes": orig - opt,
        "overall_reduction_percent": round((orig - opt) / orig * 100, 2) if orig else 0.0,
        "average_reduction_percent": round(sum(pcts) / len(pcts), 2) if pcts else 0.0,
        "average_psnr_db": round(sum(psnrs) / len(psnrs), 2) if psnrs else None,
        "average_processing_time_sec": round(sum(proc_times) / len(proc_times), 2) if proc_times else 0.0,
        "media_type_distribution": type_counts,
        "format_distribution": format_counts,
        "daily_activity": daily_list,
        "quality_distribution": quality_buckets,
        "storage_comparison": {
            "original_mb": round(orig / 1048576, 2),
            "optimized_mb": round(opt / 1048576, 2),
            "saved_mb": round((orig - opt) / 1048576, 2),
        },
    }


class UploadRequest(BaseModel):
    filename: str
    size: int
    content_type: str = ""


def safe_name(filename: str) -> str:
    name = os.path.basename(filename).replace("\\", "/").split("/")[-1]
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._")
    return name[:100]


def validate_upload(req: UploadRequest):
    name = safe_name(req.filename)
    if not name or media_type(name) == "unsupported":
        raise HTTPException(400, "Unsupported file type. Upload an image or video.")
    if req.content_type and not req.content_type.startswith(ALLOWED_MIME_PREFIXES):
        raise HTTPException(400, "Content type must be image/* or video/*.")
    if req.size <= 0 or req.size > MAX_INPUT_MB * 1024 * 1024:
        raise HTTPException(400, f"File must be between 1 byte and {MAX_INPUT_MB} MB.")
    return name


def create_app(store, process_fn=None):
    app = FastAPI(title="Supabase media pipeline API")
    origins = [o for o in os.environ.get("ALLOWED_ORIGINS", "http://localhost:5500,http://127.0.0.1:5500,http://localhost:8000").split(",") if o]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_origin_regex=CODESPACES_ORIGIN_REGEX,
                       allow_methods=["GET", "POST"], allow_headers=["*"])
    limiter = RateLimiter(UPLOADS_PER_HOUR)

    def trigger(bg: BackgroundTasks, media_id: str):
        if PROCESS_INLINE and process_fn:      # demo convenience; the default is the separate worker
            bg.add_task(process_fn, store, media_id)

    @app.post("/api/uploads")
    def create_upload(req: UploadRequest, request: Request):
        name = validate_upload(req)
        ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
              or (request.client.host if request.client else "?"))
        if not limiter.allow(ip):
            raise HTTPException(429, "Too many uploads from your address. Try again later.")
        if store.count_pending() >= MAX_PENDING:
            raise HTTPException(503, "Upload queue is full. Try again later.")
        media_id = new_media_id(name)
        path = f"uploads/{media_id}/{name}"
        store.create_record(media_id, name, media_type(name), req.size, path)
        return {"media_id": media_id, **store.signed_upload(path)}

    @app.post("/api/uploads/{media_id}/complete")
    def complete_upload(media_id: str, bg: BackgroundTasks):
        if not ID_RE.match(media_id):
            raise HTTPException(400, "Bad media id")
        rec = store.get_record(media_id)
        if not rec:
            raise HTTPException(404, "Unknown media id")
        actual = store.object_size(INPUT_BUCKET, rec["original_path"])
        if actual is None:
            raise HTTPException(409, "File not found in storage yet")
        if actual > MAX_INPUT_MB * 1024 * 1024:
            store.update_record(media_id, {"status": "FAILED", "error_message": f"File larger than {MAX_INPUT_MB} MB"})
            raise HTTPException(400, "File too large")
        store.update_record(media_id, {"original_size": actual})
        changed = store.mark_uploaded(media_id)     # duplicate /complete calls are no-ops
        if changed:
            trigger(bg, media_id)
        return {"media_id": media_id, "status": store.get_record(media_id)["status"]}

    PUBLIC_FIELDS = ("media_id", "original_filename", "media_type", "original_size", "optimized_size",
                     "compression_percentage", "status", "processing_time", "error_message", "created_at", "updated_at",
                     "original_width", "original_height", "optimized_width", "optimized_height", "psnr_db", "settings_used")

    def view(rec):
        """Only fields the UI needs: internal storage paths are never returned."""
        out = {k: rec.get(k) for k in PUBLIC_FIELDS}
        if rec["status"] == "COMPLETED":
            out["processed_url"] = store.signed_url(OUTPUT_BUCKET, rec["processed_path"])
            out["thumbnail_url"] = store.signed_url(OUTPUT_BUCKET, rec["thumbnail_path"])
            out["original_url"] = store.signed_url(INPUT_BUCKET, rec["original_path"])   # for before/after
            o, n = rec.get("original_size") or 0, rec.get("optimized_size") or 0
            out["space_saved_bytes"] = o - n
            out["psnr_label"] = psnr_label(rec.get("psnr_db")) if rec.get("psnr_db") is not None else None
        return out

    @app.get("/api/media/{media_id}")
    def status(media_id: str):
        if not ID_RE.match(media_id):
            raise HTTPException(400, "Bad media id")
        rec = store.get_record(media_id)
        if not rec:
            raise HTTPException(404, "Unknown media id")
        return view(rec)

    @app.get("/api/stats")
    def stats():
        """Aggregates only (no file names, ids, paths or URLs). Counts every upload: there are no accounts."""
        try:
            return summarize(store.stats_rows())
        except Exception as e:
            print(f"Error generating stats: {e}", flush=True)
            return summarize([])

    @app.get("/api/batch")
    def batch(ids: str = ""):
        """Cumulative summary for the ids the caller supplies (max 20). Unknown ids are counted, not revealed."""
        wanted = [i for i in ids.split(",") if i]
        if not wanted or len(wanted) > MAX_BATCH_IDS or not all(ID_RE.match(i) for i in wanted):
            raise HTTPException(400, f"Provide 1 to {MAX_BATCH_IDS} valid ids")
        try:
            rows = store.get_many(wanted)
        except Exception as e:
            print(f"Error fetching batch: {e}", flush=True)
            rows = []
        out = summarize(rows)
        out["requested"] = len(wanted)
        out["unknown"] = len(wanted) - len(rows)
        out["items"] = [{"media_id": r.get("media_id"), "status": r.get("status")} for r in rows if r.get("media_id")]
        return out

    @app.get("/api/admin/media")
    def history(x_worker_token: str = Header("")):
        """Admin-only listing. Public users only ever see their own item by its unguessable id."""
        if not WORKER_TOKEN or not hmac.compare_digest(x_worker_token, WORKER_TOKEN):
            raise HTTPException(401, "Unauthorized")
        return [view(r) for r in store.list_records(50)]

    @app.post("/internal/process/{media_id}")
    def internal_process(media_id: str, bg: BackgroundTasks, x_worker_token: str = Header("")):
        """Secured processing trigger (e.g. for a Supabase Database Webhook)."""
        if not WORKER_TOKEN or not hmac.compare_digest(x_worker_token, WORKER_TOKEN):
            raise HTTPException(401, "Unauthorized")
        if process_fn:
            bg.add_task(process_fn, store, media_id)
        return {"queued": media_id}

    if os.path.isdir(FRONTEND_DIR):      # same-origin UI: one port, no CORS, works in Codespaces
        app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="ui")
    return app


def _load_env():
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:      # python-dotenv is optional when variables are already exported
        pass


def _default_app():
    _load_env()
    from supabase_config import get_client
    from supabase_store import SupabaseStore
    from supabase_worker import process_media
    return create_app(SupabaseStore(get_client()), process_media)


# Importing this module without credentials (e.g. in unit tests) must not crash, but a misconfigured
# server must fail loudly: `uvicorn supabase_api:app` will raise the clear error from get_client().
_load_env()
app = _default_app() if os.environ.get("SUPABASE_URL") else None
