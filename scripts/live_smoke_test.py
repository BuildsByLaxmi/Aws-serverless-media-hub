"""Live end-to-end smoke test against the real Supabase project. Creates then deletes its own test rows/objects.
Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in the environment."""
import os, sys, time
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
import httpx
from fastapi.testclient import TestClient
from supabase_config import get_client, INPUT_BUCKET, OUTPUT_BUCKET, TABLE
from supabase_store import SupabaseStore
from supabase_worker import process_media
import supabase_api

ROOT = os.path.join(os.path.dirname(__file__), "..")
store = SupabaseStore(get_client()); api = TestClient(supabase_api.create_app(store, process_media))
made = []
def step(msg): print("STEP:", msg, flush=True)
try:
    for fname, ctype in (("tests/test_images/large_photo.jpg", "image/jpeg"), ("tests/test_videos/sample_video.mp4", "video/mp4")):
        data = open(os.path.join(ROOT, fname), "rb").read(); name = os.path.basename(fname)
        r = api.post("/api/uploads", json={"filename": name, "size": len(data), "content_type": ctype}); step(f"create upload {name}: {r.status_code}")
        r.raise_for_status(); j = r.json(); made.append(j["media_id"])
        fd = {"cacheControl": (None, "3600"), "": (name, data, ctype)}
        p = httpx.put(j["signed_url"], files=fd, timeout=120); step(f"signed PUT: {p.status_code} {p.text[:120]}")
        p.raise_for_status()
        c = api.post(f"/api/uploads/{j['media_id']}/complete"); step(f"complete: {c.status_code} {c.text[:120]}"); c.raise_for_status()
        step(f"process: {process_media(store, j['media_id'])}")
        st = api.get(f"/api/media/{j['media_id']}").json()
        print({k: st.get(k) for k in ("status","media_type","original_size","optimized_size","compression_percentage","processing_time","processed_path","thumbnail_path","error_message")})
        for k in ("processed_url", "thumbnail_url"):
            u = st.get(k); 
            if u:
                full = u if u.startswith("http") else os.environ["SUPABASE_URL"] + "/storage/v1" + u
                g = httpx.get(full, timeout=60); step(f"signed GET {k}: {g.status_code} {g.headers.get('content-type')} {len(g.content)}B")
        pub = httpx.get(f"{os.environ['SUPABASE_URL']}/storage/v1/object/public/{INPUT_BUCKET}/uploads/{j['media_id']}/{name}"); step(f"public access to private input (expect 4xx): {pub.status_code}")
        step(f"re-process duplicate: {process_media(store, j['media_id'])}")
finally:
    for m in made:
        rec = store.get_record(m)
        if rec:
            store.c.storage.from_(INPUT_BUCKET).remove([rec["original_path"]])
            outs = [x for x in (rec.get("processed_path"), rec.get("thumbnail_path")) if x]
            if outs: store.c.storage.from_(OUTPUT_BUCKET).remove(outs)
            store.c.table(TABLE).delete().eq("media_id", m).execute()
    step("cleanup done")
