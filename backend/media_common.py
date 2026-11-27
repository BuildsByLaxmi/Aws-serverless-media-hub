"""
Shared helpers used by BOTH Lambda functions and the local simulator,
so that mediaId, S3 keys and the metadata record are always identical.
This file is the "interface contract" from Section 5 of the plan.
"""
import hashlib
import os
import re
import time

# Kept here (not imported from the processors) so the upload API Lambda
# does not need Pillow/FFmpeg just to validate a filename.
IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".gif", ".tiff", ".tif", ".webp"}
VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}

# ---- Agreed S3 key layout ----------------------------------------------
#   INPUT  bucket: uploads/{mediaId}/{originalName}
#   OUTPUT bucket: processed/{mediaId}.webp | processed/{mediaId}.mp4
#                  thumbnails/{mediaId}.jpg
# -----------------------------------------------------------------------

def media_type(filename: str) -> str:
    ext = os.path.splitext(filename)[1].lower()
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in VIDEO_EXTENSIONS:
        return "video"
    return "unsupported"


def slugify(name: str) -> str:
    stem = os.path.splitext(os.path.basename(name))[0].lower()
    return (re.sub(r"[^a-z0-9]+", "-", stem).strip("-") or "media")[:24]


def new_media_id(filename: str, unique: str) -> str:
    """e.g. 'photo-3f9a2c' — readable + unique."""
    return f"{slugify(filename)}-{hashlib.md5(unique.encode()).hexdigest()[:6]}"


def media_id_from_key(key: str) -> str:
    """uploads/{mediaId}/{file} -> mediaId.  Any other key (e.g. a manual console
    upload) gets a deterministic id, so a repeated S3 event maps to the same record."""
    parts = key.split("/")
    if len(parts) >= 3 and parts[0] == "uploads":
        return parts[1]
    return new_media_id(key, key)


def output_keys(media_id: str, output_ext: str) -> dict:
    return {
        "outputKey": f"processed/{media_id}{output_ext}",
        "thumbnailKey": f"thumbnails/{media_id}.jpg",
    }


def reduction_percent(original: int, optimized: int) -> float:
    """Reduction % = (Original - Optimized) / Original x 100"""
    if not original:
        return 0.0
    return round((original - optimized) / original * 100, 2)


def run_processor(src_path: str, out_dir: str, media_id: str, policy=None) -> dict:
    from image_processor import InvalidMediaError, process_image
    kind = media_type(src_path)
    if kind == "image":
        return process_image(src_path, out_dir, media_id, policy)
    if kind == "video":
        from video_processor import process_video
        return process_video(src_path, out_dir, media_id, policy)
    raise InvalidMediaError(f"Unsupported file type: {os.path.basename(src_path)}")


def build_record(media_id, original_name, original_size, result, keys, processing_ms, cdn_domain=""):
    optimized_size = os.path.getsize(result["optimizedPath"])
    thumb_size = os.path.getsize(result["thumbnailPath"])
    rec = {
        "mediaId": media_id,
        "originalName": original_name,
        "mediaType": result["mediaType"],
        "originalSizeBytes": original_size,
        "optimizedSizeBytes": optimized_size,
        "thumbnailSizeBytes": thumb_size,
        "reductionPercent": reduction_percent(original_size, optimized_size),
        "status": "COMPLETED",
        "outputKey": keys["outputKey"],
        "thumbnailKey": keys["thumbnailKey"],
        "originalWidth": result["originalWidth"],
        "originalHeight": result["originalHeight"],
        "optimizedWidth": result["optimizedWidth"],
        "optimizedHeight": result["optimizedHeight"],
        "processingMs": processing_ms,
        "completedAt": int(time.time()),
    }
    if cdn_domain:
        rec["outputUrl"] = f"https://{cdn_domain}/{keys['outputKey']}"
        rec["thumbnailUrl"] = f"https://{cdn_domain}/{keys['thumbnailKey']}"
    return rec
