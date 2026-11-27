"""
Upload + status API (replaces the upload Lambda). FastAPI; run:
    uvicorn supabase_api:app --app-dir backend --port 8000
Browser never sees the service-role key; it gets short-lived signed upload/download URLs.
"""
import hmac
import os
import re
import uuid

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from media_common import media_type, new_media_id
from supabase_config import ALLOWED_MIME_PREFIXES, INPUT_BUCKET, MAX_INPUT_MB, OUTPUT_BUCKET

WORKER_TOKEN = os.environ.get("WORKER_TRIGGER_TOKEN", "")
PROCESS_INLINE = os.environ.get("PROCESS_INLINE", "false").lower() == "true"
ID_RE = re.compile(r"^[a-z0-9-]{1,40}$")


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
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_methods=["GET", "POST"], allow_headers=["*"])

    def trigger(bg: BackgroundTasks, media_id: str):
        if PROCESS_INLINE and process_fn:      # demo convenience; the default is the separate worker
            bg.add_task(process_fn, store, media_id)

    @app.post("/api/uploads")
    def create_upload(req: UploadRequest):
        name = validate_upload(req)
        media_id = new_media_id(name, uuid.uuid4().hex)
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

    def view(rec):
        out = dict(rec)
        if rec["status"] == "COMPLETED":
            out["processed_url"] = store.signed_url(OUTPUT_BUCKET, rec["processed_path"])
            out["thumbnail_url"] = store.signed_url(OUTPUT_BUCKET, rec["thumbnail_path"])
        return out

    @app.get("/api/media/{media_id}")
    def status(media_id: str):
        if not ID_RE.match(media_id):
            raise HTTPException(400, "Bad media id")
        rec = store.get_record(media_id)
        if not rec:
            raise HTTPException(404, "Unknown media id")
        return view(rec)

    @app.get("/api/media")
    def history():
        return [view(r) for r in store.list_records(20)]

    @app.post("/internal/process/{media_id}")
    def internal_process(media_id: str, bg: BackgroundTasks, x_worker_token: str = Header("")):
        """Secured processing trigger (e.g. for a Supabase Database Webhook)."""
        if not WORKER_TOKEN or not hmac.compare_digest(x_worker_token, WORKER_TOKEN):
            raise HTTPException(401, "Unauthorized")
        if process_fn:
            bg.add_task(process_fn, store, media_id)
        return {"queued": media_id}

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
