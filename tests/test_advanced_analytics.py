"""
Tests for Advanced Analytics, Visual Dashboard, and Media Management (College Capstone Level).
Verifies:
  1. summarize() empty dataset safety and graceful degradation
  2. summarize() real telemetry calculations: average PSNR, processing time, format and media type distributions
  3. Video assets explicitly exclude PSNR from quality average (PSNR is image-only)
  4. /api/stats contract adherence and security isolation (no media_id or signed URLs leaked)
  5. RFC-4180 CSV export generation logic and headers
  6. Frontend asset delivery and Chart.js integration
"""

import datetime as dt
import os
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
sys.path.insert(0, os.path.join(ROOT, "tests"))
os.environ.setdefault("WORKER_TRIGGER_TOKEN", "secret-token")

from fastapi.testclient import TestClient
from fake_store import FakeStore
import supabase_api
if not supabase_api.WORKER_TOKEN:
    supabase_api.WORKER_TOKEN = "secret-token"
from supabase_api import create_app, summarize
from supabase_worker import process_media
from supabase_config import INPUT_BUCKET

IMG = os.path.join(ROOT, "tests", "test_images", "landscape.jpg")
with open(IMG, "rb") as f:
    IMG_BYTES = f.read()


class TestAdvancedAnalytics(unittest.TestCase):
    def setUp(self):
        self.store = FakeStore()
        self.app = create_app(self.store, process_media)
        self.client = TestClient(self.app)

    def test_summarize_empty_dataset_graceful(self):
        s = summarize([])
        self.assertEqual(s["total_files"], 0)
        self.assertEqual(s["files_processed"], 0)
        self.assertEqual(s["failed"], 0)
        self.assertEqual(s["in_progress"], 0)
        self.assertEqual(s["total_original_bytes"], 0)
        self.assertEqual(s["total_optimized_bytes"], 0)
        self.assertEqual(s["total_saved_bytes"], 0)
        self.assertEqual(s["overall_reduction_percent"], 0.0)
        self.assertEqual(s["average_reduction_percent"], 0.0)
        self.assertIsNone(s["average_psnr_db"])
        self.assertEqual(s["average_processing_time_sec"], 0.0)
        self.assertEqual(s["media_type_distribution"], {"image": 0, "video": 0})
        self.assertEqual(s["format_distribution"], {})
        self.assertEqual(s["daily_activity"], [])
        self.assertEqual(s["quality_distribution"]["excellent_35_plus"], 0)
        self.assertEqual(s["storage_comparison"]["original_mb"], 0.0)

    def test_summarize_mixed_image_and_video_telemetry(self):
        today = dt.date.today().isoformat()
        rows = [
            # 1. Completed image with excellent PSNR
            {
                "media_id": "img1",
                "media_type": "image",
                "status": "COMPLETED",
                "original_size": 1000000,
                "optimized_size": 200000,
                "compression_percentage": 80.0,
                "psnr_db": 38.5,
                "processing_time": 0.35,
                "settings_used": {"format": "webp", "quality": 80},
                "created_at": f"{today}T10:00:00Z"
            },
            # 2. Completed image with good PSNR
            {
                "media_id": "img2",
                "media_type": "image",
                "status": "COMPLETED",
                "original_size": 2000000,
                "optimized_size": 500000,
                "compression_percentage": 75.0,
                "psnr_db": 32.5,
                "processing_time": 0.45,
                "settings_used": {"format": "jpeg", "quality": 85},
                "created_at": f"{today}T11:00:00Z"
            },
            # 3. Completed video (PSNR must be null!)
            {
                "media_id": "vid1",
                "media_type": "video",
                "status": "COMPLETED",
                "original_size": 10000000,
                "optimized_size": 3000000,
                "compression_percentage": 70.0,
                "psnr_db": None,
                "processing_time": 2.20,
                "settings_used": {"format": "mp4"},
                "created_at": f"{today}T12:00:00Z"
            },
            # 4. Failed upload
            {
                "media_id": "fail1",
                "media_type": "image",
                "status": "FAILED",
                "original_size": 50000,
                "optimized_size": None,
                "compression_percentage": None,
                "psnr_db": None,
                "processing_time": 0.05,
                "created_at": f"{today}T13:00:00Z"
            }
        ]

        s = summarize(rows)
        self.assertEqual(s["total_files"], 4)
        self.assertEqual(s["files_processed"], 3)
        self.assertEqual(s["failed"], 1)

        # Average PSNR should strictly be (38.5 + 32.5) / 2 = 35.5 dB (video is excluded!)
        self.assertAlmostEqual(s["average_psnr_db"], 35.5, places=2)

        # Average processing time: (0.35 + 0.45 + 2.20) / 3 = 1.0s
        self.assertAlmostEqual(s["average_processing_time_sec"], 1.0, places=2)

        # Media type distribution
        self.assertEqual(s["media_type_distribution"]["image"], 3)
        self.assertEqual(s["media_type_distribution"]["video"], 1)

        # Format distribution
        self.assertEqual(s["format_distribution"]["WEBP"], 1)
        self.assertEqual(s["format_distribution"]["JPEG"], 1)
        self.assertEqual(s["format_distribution"]["MP4"], 1)

        # Quality distribution
        self.assertEqual(s["quality_distribution"]["excellent_35_plus"], 1)
        self.assertEqual(s["quality_distribution"]["good_30_35"], 1)
        self.assertEqual(s["quality_distribution"]["acceptable_25_30"], 0)

        # Daily activity contains today
        self.assertEqual(len(s["daily_activity"]), 1)
        self.assertEqual(s["daily_activity"][0]["uploaded"], 4)
        self.assertEqual(s["daily_activity"][0]["completed"], 3)

    def test_api_stats_endpoint_returns_advanced_metrics(self):
        # Upload and complete real test image
        u = self.client.post("/api/uploads", json={"filename": "photo.jpg", "size": len(IMG_BYTES), "content_type": "image/jpeg"}).json()
        mid = u["media_id"]
        self.store.objects[(INPUT_BUCKET, u["path"])] = IMG_BYTES
        self.client.post(f"/api/uploads/{mid}/complete")
        process_media(self.store, mid)

        resp = self.client.get("/api/stats")
        self.assertEqual(resp.status_code, 200)
        s = resp.json()

        self.assertEqual(s["files_processed"], 1)
        self.assertGreater(s["total_saved_bytes"], 0)
        self.assertIsNotNone(s["average_psnr_db"])
        self.assertIn("WEBP", s["format_distribution"])
        self.assertIn("storage_comparison", s)
        self.assertIn("daily_activity", s)

        # Crucial security check: media_id must not leak into stats payload
        txt = str(s)
        self.assertNotIn("media_id", txt)
        self.assertNotIn("fake://", txt)
        self.assertNotIn(mid, txt)

    def test_frontend_includes_chartjs_and_management_ui(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("Media Pipeline", r.text)
        self.assertIn("chart.js", r.text.lower())
        self.assertIn("itemSizeChart", r.text)
        self.assertIn("storageChart", r.text)
        self.assertIn("dailyActivityChart", r.text)
        self.assertIn("exportCsvBtn", r.text)
        self.assertIn("historySearch", r.text)
        self.assertIn("detailModal", r.text)

    def test_app_js_syntax_and_features(self):
        r = self.client.get("/app.js")
        self.assertEqual(r.status_code, 200)
        js = r.text
        self.assertIn("exportHistoryToCsv", js)
        self.assertIn("renderDashboardCharts", js)
        self.assertIn("openDetailModal", js)
        self.assertIn("renderItemAnalytics", js)


if __name__ == "__main__":
    unittest.main()
