"""
Run the whole pipeline on your laptop / Google Colab — no AWS needed.
(Step 02 of the plan: "build image processing locally first")

Folders stand in for the cloud:
    local_cloud/input-bucket/     = S3 input bucket
    local_cloud/output-bucket/    = S3 output bucket (processed/, thumbnails/)
    local_cloud/MediaMetadata.json = DynamoDB table

Usage:
    python scripts/local_pipeline.py tests/test_images      # process a folder
    python scripts/local_pipeline.py photo.jpg              # one file
    python scripts/local_pipeline.py --watch                # acts like the S3 trigger
"""
import json
import os
import shutil
import sys
import tempfile
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "backend"))
from media_common import (build_record, media_id_from_key, media_type,  # noqa: E402
                          output_keys, run_processor)

CLOUD = os.path.join(ROOT, "local_cloud")
INPUT = os.path.join(CLOUD, "input-bucket")
OUTPUT = os.path.join(CLOUD, "output-bucket")
TABLE = os.path.join(CLOUD, "MediaMetadata.json")


def load_table():
    return json.load(open(TABLE)) if os.path.exists(TABLE) else {}


def save_table(t):
    json.dump(t, open(TABLE, "w"), indent=2)


def simulate_lambda(key: str):
    """Same steps as backend/lambda_function.py, with folders instead of boto3."""
    src = os.path.join(INPUT, key)
    name = os.path.basename(key)
    media_id = media_id_from_key(key)
    table = load_table()
    table[media_id] = {"mediaId": media_id, "originalName": name, "status": "PROCESSING"}
    save_table(table)
    t0 = time.time()
    try:
        with tempfile.TemporaryDirectory() as tmp:
            result = run_processor(src, tmp, media_id)
            keys = output_keys(media_id, result["outputExt"])
            for path, out_key in ((result["optimizedPath"], keys["outputKey"]),
                                  (result["thumbnailPath"], keys["thumbnailKey"])):
                dst = os.path.join(OUTPUT, out_key)
                os.makedirs(os.path.dirname(dst), exist_ok=True)
                shutil.copy(path, dst)
            rec = build_record(media_id, name, os.path.getsize(src), result, keys,
                               int((time.time() - t0) * 1000))
    except Exception as e:
        rec = {"mediaId": media_id, "originalName": name, "status": "FAILED", "errorMessage": str(e)}
    table[media_id] = rec
    save_table(table)
    return rec


def human(n):
    return f"{n/1048576:.2f} MB" if n >= 1048576 else f"{n/1024:.1f} KB"


def print_record(r):
    if r["status"] != "COMPLETED":
        print(f"  ✗ {r['originalName']:<28} FAILED  -> {r.get('errorMessage')}")
        return
    print(f"  ✓ {r['originalName']:<28} {human(r['originalSizeBytes']):>10} -> "
          f"{human(r['optimizedSizeBytes']):>10}  ({r['reductionPercent']:>6.2f}% saved)  "
          f"{r['originalWidth']}x{r['originalHeight']} -> {r['optimizedWidth']}x{r['optimizedHeight']}  "
          f"{r['processingMs']} ms")


def upload(path):
    key = os.path.basename(path)
    os.makedirs(INPUT, exist_ok=True)
    shutil.copy(path, os.path.join(INPUT, key))
    return key


def main():
    os.makedirs(INPUT, exist_ok=True)
    os.makedirs(OUTPUT, exist_ok=True)
    if len(sys.argv) > 1 and sys.argv[1] == "--watch":
        print(f"Watching {INPUT} — drop files in (Ctrl+C to stop)")
        seen = set(os.listdir(INPUT))
        while True:
            for f in sorted(set(os.listdir(INPUT)) - seen):
                seen.add(f)
                print(f"S3 event: ObjectCreated -> {f}")
                print_record(simulate_lambda(f))
            time.sleep(1)

    target = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "tests", "test_images")
    files = ([os.path.join(target, f) for f in sorted(os.listdir(target))]
             if os.path.isdir(target) else [target])
    print("Processing (upload -> S3 event -> Lambda -> output bucket -> MediaMetadata):")
    for f in files:
        if os.path.isfile(f):
            print_record(simulate_lambda(upload(f)))
    print(f"\nOutputs:  {OUTPUT}\nMetadata: {TABLE}")


if __name__ == "__main__":
    main()
