"""Tests for the five features: before/after data, dashboard stats, PSNR, batch summary, output selection."""
import io, os, shutil, sys, unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend")); sys.path.insert(0, os.path.join(ROOT, "tests"))
sys.path.insert(0, os.path.join(ROOT, "scripts"))
from PIL import Image
import output_policy as op
import quality_metrics as qm
from image_processor import process_image
from video_processor import process_video
from supabase_store import SupabaseStore, NEW_COLUMNS
from supabase_config import INPUT_BUCKET
from test_supabase_pipeline import Base as _Base, read, IMG, VID
from supabase_worker import process_media
import tempfile


def _has_ffmpeg():
    try:
        from video_processor import ffmpeg_path
        return bool(ffmpeg_path())
    except Exception:
        return False


class TestOutputSelection(unittest.TestCase):
    def test_image_tiers_have_reasons_and_hard_limits(self):
        cases = [(800, 600, 50_000, False), (4000, 3000, 6_000_000, False), (1920, 1080, 800_000, False),
                 (640, 480, 300_000, False), (500, 500, 900_000, True)]
        for c in cases:
            s = op.choose_image_settings(*c)
            self.assertTrue(s["reason"])
            self.assertEqual(s["max_dimension"], 1920)
            self.assertTrue(50 <= s["webp_quality"] <= 95)
        self.assertEqual(op.choose_image_settings(500, 500, 900_000, True)["webp_quality"], 90)
        self.assertLess(op.choose_image_settings(4000, 3000, 6_000_000)["webp_quality"],
                        op.choose_image_settings(1920, 1080, 800_000)["webp_quality"])

    def test_video_never_exceeds_720p(self):
        for w, h, d, sz in [(1920, 1080, 30, 9_000_000), (640, 360, 10, 500_000), (3840, 2160, 120, 40_000_000)]:
            s = op.choose_video_settings(w, h, d, sz)
            self.assertLessEqual(s["max_height"], 720)
            self.assertTrue(s["reason"])

    def test_process_image_with_policy_reports_settings_and_psnr(self):
        with tempfile.TemporaryDirectory() as t:
            r = process_image(os.path.join(IMG, "landscape.jpg"), t, "x1", policy=op.DefaultPolicy)
            self.assertIn("reason", r["settings"])
            self.assertGreater(r["psnr"], 20)
            self.assertLessEqual(max(r["optimizedWidth"], r["optimizedHeight"]), 1920)

    def test_process_image_without_policy_unchanged(self):
        with tempfile.TemporaryDirectory() as t:
            r = process_image(os.path.join(IMG, "landscape.jpg"), t, "x2")
            self.assertTrue(os.path.exists(r["optimizedPath"]))

    def test_transparent_png_keeps_alpha(self):
        with tempfile.TemporaryDirectory() as t:
            r = process_image(os.path.join(IMG, "logo_transparent.png"), t, "x3", policy=op.DefaultPolicy)
            self.assertEqual(Image.open(r["optimizedPath"]).mode, "RGBA")

    @unittest.skipUnless(_has_ffmpeg(), "ffmpeg not installed")
    def test_video_policy_settings(self):
        with tempfile.TemporaryDirectory() as t:
            r = process_video(VID, t, "v1", policy=op.DefaultPolicy)
            self.assertIn("reason", r["settings"])
            self.assertLessEqual(r["optimizedHeight"], 720)


class TestPsnr(unittest.TestCase):
    def test_identical_is_capped_and_excellent(self):
        a = Image.new("RGB", (32, 32), (10, 20, 30))
        self.assertEqual(qm.psnr(a, a), 99.0)
        self.assertIn("excellent", qm.psnr_label(99.0).lower())

    def test_known_value(self):
        a = Image.new("RGB", (16, 16), (100, 100, 100)); b = Image.new("RGB", (16, 16), (110, 110, 110))
        self.assertAlmostEqual(qm.psnr(a, b), 20 * __import__("math").log10(255 / 10), places=1)

    def test_labels_ordered(self):
        self.assertNotEqual(qm.psnr_label(25), qm.psnr_label(45))

    def test_size_mismatch_rejected(self):
        with self.assertRaises(ValueError):
            qm.psnr(Image.new("RGB", (20, 20)), Image.new("RGB", (10, 10)))


class Base(_Base):
    def upload(self, *a):
        mid = super().upload(*a)
        process_media(self.store, mid)
        return mid


class TestWorkerAndApi(Base):
    def test_completed_record_has_feature_fields(self):
        mid = self.upload("p.jpg", read(os.path.join(IMG, "large_photo.jpg")), "image/jpeg")
        rec = self.store.get_record(mid)
        self.assertEqual(rec["status"], "COMPLETED")
        for k in ("original_width", "original_height", "optimized_width", "optimized_height", "psnr_db", "settings_used"):
            self.assertIsNotNone(rec[k], k)
        j = self.client.get(f"/api/media/{mid}").json()
        self.assertGreater(j["space_saved_bytes"], 0)
        self.assertTrue(j["psnr_label"])
        self.assertTrue(j["original_url"].startswith("fake://"))
        self.assertIn("reason", j["settings_used"])
        self.assertNotIn("original_path", j); self.assertNotIn("processed_path", j)

    @unittest.skipUnless(_has_ffmpeg(), "ffmpeg not installed")
    def test_video_has_no_psnr(self):
        mid = self.upload("v.mp4", read(VID), "video/mp4")
        j = self.client.get(f"/api/media/{mid}").json()
        self.assertEqual(j["status"], "COMPLETED")
        self.assertIsNone(j["psnr_db"])

    def test_original_url_only_when_completed(self):
        r = self.client.post("/api/uploads", json={"filename": "a.jpg", "size": 5}).json()
        j = self.client.get(f"/api/media/{r['media_id']}").json()
        self.assertNotIn("original_url", j)

    def test_stats_aggregate_only(self):
        self.upload("a.jpg", read(os.path.join(IMG, "landscape.jpg")), "image/jpeg")
        self.upload("b.txt.jpg", b"not an image at all", "image/jpeg")
        s = self.client.get("/api/stats").json()
        self.assertEqual(s["files_processed"], 1); self.assertEqual(s["failed"], 1)
        self.assertEqual(s["total_files"], 2)
        self.assertGreater(s["total_saved_bytes"], 0)
        self.assertGreater(s["average_reduction_percent"], 0)
        txt = str(s)
        self.assertNotIn("uploads/", txt); self.assertNotIn("fake://", txt); self.assertNotIn("media_id", txt)

    def test_stats_empty(self):
        s = self.client.get("/api/stats").json()
        self.assertEqual((s["total_files"], s["overall_reduction_percent"]), (0, 0.0))

    def test_batch_summary(self):
        a = self.upload("a.jpg", read(os.path.join(IMG, "landscape.jpg")), "image/jpeg")
        b = self.upload("b.jpg", read(os.path.join(IMG, "large_photo.jpg")), "image/jpeg")
        j = self.client.get(f"/api/batch?ids={a},{b},zzzzzzzz").json()
        self.assertEqual((j["requested"], j["files_processed"], j["unknown"]), (3, 2, 1))
        ra, rb = self.store.get_record(a), self.store.get_record(b)
        self.assertEqual(j["total_original_bytes"], ra["original_size"] + rb["original_size"])
        self.assertEqual(j["total_saved_bytes"], j["total_original_bytes"] - j["total_optimized_bytes"])
        self.assertNotIn("fake://", str(j))

    def test_batch_validation(self):
        for q in ("", "ids=", "ids=../etc", "ids=" + ",".join(["a"] * 21), "ids=A B"):
            self.assertEqual(self.client.get("/api/batch?" + q).status_code, 400, q)


class _Err(Exception):
    def __init__(self, code): super().__init__("column missing"); self.code = code


class _Q:
    def __init__(self, c): self.c = c
    def update(self, f): self.c.calls.append(dict(f)); self.f = f; return self
    def eq(self, *a): return self
    def execute(self):
        if any(k in self.f for k in NEW_COLUMNS) and self.c.fail: raise _Err("PGRST204")
        return None


class _Client:
    def __init__(self, fail): self.calls = []; self.fail = fail
    def table(self, n): return _Q(self)


class TestStoreFallback(unittest.TestCase):
    def test_retries_without_new_columns(self):
        c = _Client(True); SupabaseStore(c).update_record("m", {"status": "COMPLETED", "psnr_db": 40.0})
        self.assertEqual(len(c.calls), 2); self.assertNotIn("psnr_db", c.calls[1]); self.assertEqual(c.calls[1]["status"], "COMPLETED")

    def test_no_retry_when_columns_exist(self):
        c = _Client(False); SupabaseStore(c).update_record("m", {"status": "COMPLETED", "psnr_db": 40.0})
        self.assertEqual(len(c.calls), 1); self.assertIn("psnr_db", c.calls[0])

    def test_other_errors_still_raise(self):
        class Boom(_Client):
            def table(self, n):
                q = _Q(self); q.execute = lambda: (_ for _ in ()).throw(RuntimeError("network down")); return q
        with self.assertRaises(RuntimeError): SupabaseStore(Boom(False)).update_record("m", {"psnr_db": 1})


class TestExperimentScript(unittest.TestCase):
    def test_runs(self):
        import quality_experiment
        src, rows = quality_experiment.run(os.path.join(IMG, "landscape.jpg"))
        self.assertEqual([r[0] for r in rows], [95, 82, 80, 60])
        self.assertGreater(rows[0][1], rows[3][1])


if __name__ == "__main__":
    unittest.main()
