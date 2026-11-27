"""Tests for the Supabase workflow, run against FakeStore (no network, no credentials).
Real Pillow/FFmpeg processing is exercised; only Supabase I/O is faked."""
import io, os, subprocess, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend")); sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("WORKER_TRIGGER_TOKEN", "secret-token")

from fastapi.testclient import TestClient
from PIL import Image
from fake_store import FakeStore
import supabase_api
from supabase_worker import process_media
from supabase_config import INPUT_BUCKET, OUTPUT_BUCKET

IMG = os.path.join(ROOT, "tests", "test_images")
VID = os.path.join(ROOT, "tests", "test_videos", "sample_video.mp4")


def read(p):
    with open(p, "rb") as f: return f.read()


class Base(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.client = TestClient(supabase_api.create_app(self.store, process_media))

    def upload(self, name, data, ctype=""):
        r = self.client.post("/api/uploads", json={"filename": name, "size": len(data), "content_type": ctype})
        self.assertEqual(r.status_code, 200, r.text)
        j = r.json()
        self.store.objects[(INPUT_BUCKET, j["path"])] = data       # simulates the browser's signed-URL upload
        c = self.client.post(f"/api/uploads/{j['media_id']}/complete")
        self.assertEqual(c.status_code, 200, c.text)
        return j["media_id"]


class TestUploadApi(Base):
    def test_rejects_invalid_type(self):
        r = self.client.post("/api/uploads", json={"filename": "notes.txt", "size": 10})
        self.assertEqual(r.status_code, 400)
        r = self.client.post("/api/uploads", json={"filename": "a.jpg", "size": 10, "content_type": "text/html"})
        self.assertEqual(r.status_code, 400)

    def test_rejects_too_big_and_empty(self):
        for size in (0, 10**9):
            self.assertEqual(self.client.post("/api/uploads", json={"filename": "a.jpg", "size": size}).status_code, 400)

    def test_filename_sanitised(self):
        r = self.client.post("/api/uploads", json={"filename": "../../etc/pa ss.jpg", "size": 5}).json()
        self.assertTrue(r["path"].startswith("uploads/") and ".." not in r["path"] and " " not in r["path"])

    def test_metadata_created_as_uploading_then_uploaded(self):
        r = self.client.post("/api/uploads", json={"filename": "a.jpg", "size": 5}).json()
        self.assertEqual(self.store.get_record(r["media_id"])["status"], "UPLOADING")
        self.assertEqual(self.client.post(f"/api/uploads/{r['media_id']}/complete").status_code, 409)  # nothing in storage
        self.store.objects[(INPUT_BUCKET, r["path"])] = b"12345"
        self.client.post(f"/api/uploads/{r['media_id']}/complete")
        self.assertEqual(self.store.get_record(r["media_id"])["status"], "UPLOADED")

    def test_unknown_and_bad_ids(self):
        self.assertEqual(self.client.get("/api/media/nope").status_code, 404)
        self.assertEqual(self.client.get("/api/media/BAD..ID").status_code, 400)

    def test_internal_endpoint_requires_token(self):
        self.assertEqual(self.client.post("/internal/process/x").status_code, 401)
        self.assertEqual(self.client.post("/internal/process/x", headers={"x-worker-token": "wrong"}).status_code, 401)
        self.assertEqual(self.client.post("/internal/process/x", headers={"x-worker-token": "secret-token"}).status_code, 200)


class TestAbuseProtection(Base):
    def test_media_ids_unguessable(self):
        ids = {self.client.post("/api/uploads", json={"filename": "a.jpg", "size": 5}).json()["media_id"] for _ in range(5)}
        self.assertEqual(len(ids), 5)
        for i in ids: self.assertGreaterEqual(len(i.split("-")[-1]), 20)

    def test_public_listing_removed_admin_requires_token(self):
        self.assertIn(self.client.get("/api/media").status_code, (404, 405))
        self.assertEqual(self.client.get("/api/admin/media").status_code, 401)
        self.assertEqual(self.client.get("/api/admin/media", headers={"x-worker-token": "secret-token"}).status_code, 200)

    def test_rate_limit(self):
        app = supabase_api.create_app(self.store, process_media)
        supabase_api.UPLOADS_PER_HOUR = 3
        try:
            c = TestClient(supabase_api.create_app(self.store, process_media))
        finally:
            supabase_api.UPLOADS_PER_HOUR = 30
        codes = [c.post("/api/uploads", json={"filename": "a.jpg", "size": 5}).status_code for _ in range(5)]
        self.assertEqual(codes, [200, 200, 200, 429, 429])

    def test_pending_cap(self):
        supabase_api.MAX_PENDING = 2
        try:
            codes = [self.client.post("/api/uploads", json={"filename": "a.jpg", "size": 5}).status_code for _ in range(3)]
        finally:
            supabase_api.MAX_PENDING = 200
        self.assertEqual(codes, [200, 200, 503])

    def test_ui_served_same_origin(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200); self.assertIn("Media Pipeline", r.text)
        self.assertEqual(self.client.get("/app.js").status_code, 200)

    def test_cors_allows_codespaces_origin_only(self):
        h = {"Origin": "https://abc-8000.app.github.dev", "Access-Control-Request-Method": "POST"}
        self.assertEqual(self.client.options("/api/uploads", headers=h).headers.get("access-control-allow-origin"), h["Origin"])
        h["Origin"] = "https://evil.example.com"
        self.assertIsNone(self.client.options("/api/uploads", headers=h).headers.get("access-control-allow-origin"))


class TestImageFlow(Base):
    def test_valid_image_end_to_end(self):
        data = read(os.path.join(IMG, "large_photo.jpg"))
        mid = self.upload("large_photo.jpg", data, "image/jpeg")
        self.assertEqual(process_media(self.store, mid), "COMPLETED")
        api_view = self.client.get(f"/api/media/{mid}").json()
        self.assertNotIn("processed_path", api_view)            # internal paths are not exposed
        rec = {**self.store.get_record(mid), **api_view}
        self.assertEqual(rec["status"], "COMPLETED")
        self.assertEqual(rec["processed_path"], f"processed/{mid}.webp")
        self.assertEqual(rec["thumbnail_path"], f"thumbnails/{mid}.jpg")
        self.assertIn("signed", rec["processed_url"]); self.assertIn("signed", rec["thumbnail_url"])
        self.assertLess(rec["optimized_size"], rec["original_size"])
        expect = round((rec["original_size"] - rec["optimized_size"]) / rec["original_size"] * 100, 2)
        self.assertEqual(float(rec["compression_percentage"]), expect)
        self.assertGreaterEqual(rec["processing_time"], 0)
        out = Image.open(io.BytesIO(self.store.objects[(OUTPUT_BUCKET, rec["processed_path"])]))
        self.assertEqual(out.format, "WEBP"); self.assertLessEqual(max(out.size), 1920)
        th = Image.open(io.BytesIO(self.store.objects[(OUTPUT_BUCKET, rec["thumbnail_path"])]))
        self.assertEqual((th.format, th.size), ("JPEG", (200, 200)))

    def test_status_transitions(self):
        seen = []
        orig = self.store.update_record
        self.store.update_record = lambda m, f: (seen.append(f.get("status")), orig(m, f))
        mid = self.upload("landscape.jpg", read(os.path.join(IMG, "landscape.jpg")))
        process_media(self.store, mid)
        self.assertEqual([x for x in seen if x][-2:], ["PROCESSING", "COMPLETED"])
        self.assertEqual(self.store.get_record(mid)["status"], "COMPLETED")
        self.assertIn("UPLOADED", seen); self.assertLess(seen.index("UPLOADED"), seen.index("COMPLETED"))

    def test_duplicate_processing_is_skipped(self):
        mid = self.upload("landscape.jpg", read(os.path.join(IMG, "landscape.jpg")))
        self.assertEqual(process_media(self.store, mid), "COMPLETED")
        before = self.store.get_record(mid)
        self.assertEqual(process_media(self.store, mid), "SKIPPED")
        self.assertEqual(self.store.get_record(mid)["processing_time"], before["processing_time"])

    def test_duplicate_complete_call_triggers_once(self):
        calls = []
        app = supabase_api.create_app(self.store, lambda s, m: calls.append(m))
        supabase_api.PROCESS_INLINE = True
        try:
            c = TestClient(app)
            j = c.post("/api/uploads", json={"filename": "a.jpg", "size": 3}).json()
            self.store.objects[(INPUT_BUCKET, j["path"])] = b"abc"
            c.post(f"/api/uploads/{j['media_id']}/complete"); c.post(f"/api/uploads/{j['media_id']}/complete")
        finally:
            supabase_api.PROCESS_INLINE = False
        self.assertEqual(calls, [j["media_id"]])

    def test_corrupt_image_marked_failed(self):
        mid = self.upload("invalid_file.jpg", read(os.path.join(IMG, "invalid_file.jpg")))
        self.assertEqual(process_media(self.store, mid), "FAILED")
        rec = self.store.get_record(mid)
        self.assertEqual(rec["status"], "FAILED"); self.assertIn("valid image", rec["error_message"])
        self.assertNotIn((OUTPUT_BUCKET, f"processed/{mid}.webp"), self.store.objects)

    def test_unknown_media_id_skipped(self):
        self.assertEqual(process_media(self.store, "ghost"), "SKIPPED")

    def test_transparent_png(self):
        mid = self.upload("logo.png", read(os.path.join(IMG, "logo_transparent.png")))
        self.assertEqual(process_media(self.store, mid), "COMPLETED")


class TestSpec(unittest.TestCase):
    def test_webp_quality_default_is_82(self):
        import image_processor
        self.assertEqual(image_processor.WEBP_QUALITY, 82)


class TestVideoFlow(Base):
    def test_video_end_to_end(self):
        mid = self.upload("sample_video.mp4", read(VID), "video/mp4")
        self.assertEqual(process_media(self.store, mid), "COMPLETED")
        rec = self.store.get_record(mid)
        self.assertEqual(rec["processed_path"], f"processed/{mid}.mp4")
        self.assertEqual(rec["thumbnail_path"], f"thumbnails/{mid}.jpg")
        th = Image.open(io.BytesIO(self.store.objects[(OUTPUT_BUCKET, rec["thumbnail_path"])]))
        self.assertEqual((th.format, th.size), ("JPEG", (200, 200)))
        tmp = "/tmp/_out_test.mp4"
        with open(tmp, "wb") as f: f.write(self.store.objects[(OUTPUT_BUCKET, rec["processed_path"])])
        info = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries",
                               "stream=codec_name,height", "-of", "csv=p=0", tmp], capture_output=True, text=True).stdout.strip()
        codec, height = info.split(",")
        self.assertEqual(codec, "h264"); self.assertLessEqual(int(height), 720)

    def test_corrupt_video_marked_failed(self):
        mid = self.upload("broken.mp4", b"this is not a video at all" * 50)
        self.assertEqual(process_media(self.store, mid), "FAILED")
        self.assertTrue(self.store.get_record(mid)["error_message"])


if __name__ == "__main__":
    unittest.main()
