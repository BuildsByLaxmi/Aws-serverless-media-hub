"""
Tests for Person 2's processing code — the cases listed in the plan:
landscape, portrait, large image, invalid file, video, reduction formula, retry-safe ids.

Run:  python -m unittest discover -s tests -v
"""
import os
import shutil
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "backend"))

from PIL import Image  # noqa: E402

from image_processor import InvalidMediaError, process_image  # noqa: E402
from media_common import (media_id_from_key, media_type, output_keys,  # noqa: E402
                          reduction_percent, run_processor)

IMAGES = os.path.join(HERE, "test_images")
VIDEOS = os.path.join(HERE, "test_videos")


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.out = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.out)

    def _check(self, name, expect_landscape):
        r = process_image(os.path.join(IMAGES, name), self.out, "t")
        self.assertTrue(r["optimizedPath"].endswith(".webp"))
        with Image.open(r["optimizedPath"]) as im:
            self.assertEqual(im.format, "WEBP")
            self.assertLessEqual(max(im.size), 1920)
            self.assertEqual(im.width > im.height, expect_landscape)
            # aspect ratio preserved (within rounding)
            self.assertAlmostEqual(im.width / im.height,
                                   r["originalWidth"] / r["originalHeight"], places=2)
        with Image.open(r["thumbnailPath"]) as th:
            self.assertEqual(th.size, (200, 200))
            self.assertEqual(th.format, "JPEG")
        return r

    def test_landscape(self):
        self._check("landscape.jpg", True)

    def test_portrait(self):
        self._check("portrait.jpg", False)

    def test_large_image_is_resized_and_smaller(self):
        src = os.path.join(IMAGES, "large_photo.jpg")
        r = self._check("large_photo.jpg", True)
        self.assertEqual(r["optimizedWidth"], 1920)
        self.assertLess(os.path.getsize(r["optimizedPath"]), os.path.getsize(src))

    def test_png_with_transparency(self):
        self._check("logo_transparent.png", True)

    def test_invalid_file_raises(self):
        with self.assertRaises(InvalidMediaError):
            process_image(os.path.join(IMAGES, "invalid_file.jpg"), self.out, "bad")

    def test_unsupported_extension(self):
        self.assertEqual(media_type("notes.txt"), "unsupported")
        with self.assertRaises(InvalidMediaError):
            run_processor(os.path.join(IMAGES, "not_media.txt"), self.out, "x")


@unittest.skipUnless(shutil.which("ffmpeg"), "ffmpeg not installed")
class VideoTests(unittest.TestCase):
    def test_video_compress_and_thumbnail(self):
        out = tempfile.mkdtemp()
        try:
            r = run_processor(os.path.join(VIDEOS, "sample_video.mp4"), out, "vid")
            self.assertTrue(os.path.getsize(r["optimizedPath"]) > 0)
            self.assertLessEqual(r["optimizedHeight"], 720)
            with Image.open(r["thumbnailPath"]) as th:
                self.assertEqual(th.size, (200, 200))
        finally:
            shutil.rmtree(out)


class ContractTests(unittest.TestCase):
    def test_reduction_formula(self):            # example from the plan: 4 MB -> 1 MB = 75 %
        self.assertEqual(reduction_percent(4_000_000, 1_000_000), 75.0)
        self.assertEqual(reduction_percent(0, 10), 0.0)

    def test_media_id_from_upload_key(self):
        self.assertEqual(media_id_from_key("uploads/photo-3f9a2c/photo.jpg"), "photo-3f9a2c")

    def test_manual_upload_id_is_stable_for_retries(self):
        self.assertEqual(media_id_from_key("photo.jpg"), media_id_from_key("photo.jpg"))

    def test_output_key_layout(self):
        self.assertEqual(output_keys("photo-001", ".webp"),
                         {"outputKey": "processed/photo-001.webp",
                          "thumbnailKey": "thumbnails/photo-001.jpg"})


if __name__ == "__main__":
    unittest.main(verbosity=2)
