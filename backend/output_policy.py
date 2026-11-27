"""
Intelligent output selection: choose processing settings per file (type, size, dimensions)
instead of one fixed setting for everything. Pure functions, no I/O, so they are easy to test.
Every decision returns the numbers plus a one-line reason that is stored and shown to the user.

Hard limits that never change (project spec): images max 1920 px and never upscaled,
videos max 720p and first 60 s, outputs stay WebP / H.264 MP4.
"""
import os

KB, MB = 1024, 1024 * 1024
DEFAULT_WEBP_QUALITY = int(os.environ.get("WEBP_QUALITY", "82"))
MAX_DIMENSION = int(os.environ.get("MAX_DIMENSION", "1920"))
MAX_VIDEO_HEIGHT = int(os.environ.get("MAX_VIDEO_HEIGHT", "720"))
DEFAULT_CRF = int(os.environ.get("VIDEO_CRF", "28"))


def choose_image_settings(width: int, height: int, size_bytes: int, has_alpha: bool = False) -> dict:
    mp = width * height / 1_000_000
    if has_alpha:
        q, why = 90, "transparent image: higher quality so edges stay clean (alpha kept)"
    elif size_bytes < 100 * KB and mp < 1:
        q, why = 90, "small image: higher quality so the file does not grow"
    elif mp >= 12 or size_bytes >= 5 * MB:
        q, why = 78, "very large photo: stronger compression"
    elif mp >= 2:
        q, why = DEFAULT_WEBP_QUALITY, "standard photo: balanced quality"
    else:
        q, why = 85, "low-resolution image: slightly higher quality"
    return {"kind": "image", "max_dimension": MAX_DIMENSION, "webp_quality": q, "reason": why}


def choose_video_settings(width: int, height: int, duration_s: float, size_bytes: int) -> dict:
    if size_bytes < 2 * MB or height <= 480:
        crf, why = 26, "small or low-resolution video: higher quality so it does not grow"
    elif height >= 1080:
        crf, why = 30, "Full HD or larger: stronger compression while scaling down to 720p"
    else:
        crf, why = DEFAULT_CRF, "standard video: balanced quality"
    if duration_s and duration_s > 60:
        why += "; only the first 60 s are kept"
    return {"kind": "video", "max_height": MAX_VIDEO_HEIGHT, "crf": crf, "reason": why}


class DefaultPolicy:
    """Object handed to the processors. Swap in another object to change the rules."""
    image = staticmethod(choose_image_settings)
    video = staticmethod(choose_video_settings)
