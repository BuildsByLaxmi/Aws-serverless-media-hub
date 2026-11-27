"""
Python processing worker (replaces the S3-triggered processor Lambda).
Reuses image_processor / video_processor / media_common unchanged.

Run:  python backend/supabase_worker.py            # polls for UPLOADED rows forever
      python backend/supabase_worker.py --once     # drain the queue and exit
"""
import json
import os
import sys
import tempfile
import time

from image_processor import InvalidMediaError
from media_common import media_type, output_keys, reduction_percent, run_processor
from supabase_config import INPUT_BUCKET, MAX_INPUT_MB, OUTPUT_BUCKET

CONTENT_TYPES = {".webp": "image/webp", ".jpg": "image/jpeg", ".mp4": "video/mp4"}


def _log(**kw):
    print(json.dumps(kw), flush=True)


def process_media(store, media_id):
    """Process one media item. Returns 'COMPLETED', 'FAILED' or 'SKIPPED' (duplicate/not ready)."""
    rec = store.get_record(media_id)
    if not rec:
        _log(mediaId=media_id, skipped="unknown media id")
        return "SKIPPED"
    if not store.claim_for_processing(media_id):       # duplicate trigger or already done
        _log(mediaId=media_id, skipped=f"not claimable (status={rec['status']})")
        return "SKIPPED"

    name = os.path.basename(rec["original_path"])
    if media_type(name) == "unsupported":
        store.update_record(media_id, {"status": "FAILED", "error_message": "Unsupported file type"})
        return "FAILED"
    started = time.time()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, name)
            store.download_to(INPUT_BUCKET, rec["original_path"], src)
            size = os.path.getsize(src)
            if size > MAX_INPUT_MB * 1024 * 1024:
                raise InvalidMediaError(f"File larger than {MAX_INPUT_MB} MB")

            result = run_processor(src, os.path.join(tmp, "out"), media_id)
            keys = output_keys(media_id, result["outputExt"])
            for path, key in ((result["optimizedPath"], keys["outputKey"]),
                              (result["thumbnailPath"], keys["thumbnailKey"])):
                store.upload_file(OUTPUT_BUCKET, key, path,
                                  CONTENT_TYPES.get(os.path.splitext(key)[1], "application/octet-stream"))
            optimized = os.path.getsize(result["optimizedPath"])
            store.update_record(media_id, {
                "status": "COMPLETED", "media_type": result["mediaType"],
                "original_size": size, "optimized_size": optimized,
                "compression_percentage": reduction_percent(size, optimized),
                "processed_path": keys["outputKey"], "thumbnail_path": keys["thumbnailKey"],
                "processing_time": round(time.time() - started, 2), "error_message": None})
            _log(mediaId=media_id, status="COMPLETED")
            return "COMPLETED"
    except Exception as e:      # invalid media and unexpected errors both end as FAILED (retry via re-upload)
        store.update_record(media_id, {"status": "FAILED", "error_message": str(e)[:500],
                                      "processing_time": round(time.time() - started, 2)})
        _log(mediaId=media_id, status="FAILED", reason=str(e)[:200])
        return "FAILED"


def run_loop(store, once=False, interval=3):
    while True:
        ids = store.pending_ids()
        for mid in ids:
            process_media(store, mid)
        if once and not ids:
            return
        if not ids:
            time.sleep(interval)


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    from supabase_config import get_client
    from supabase_store import SupabaseStore
    run_loop(SupabaseStore(get_client()), once="--once" in sys.argv)
