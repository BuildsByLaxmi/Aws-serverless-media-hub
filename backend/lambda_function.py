"""
lambda_function.py — PROCESSOR Lambda  (Person 2 writes it, Person 1 deploys/triggers it)

Trigger : S3 ObjectCreated on the INPUT bucket
Handler : lambda_function.lambda_handler
Env vars: OUTPUT_BUCKET, TABLE_NAME (=MediaMetadata), CLOUDFRONT_DOMAIN, MAX_INPUT_MB
Layer   : FFmpeg (only needed for videos)

Flow: read event -> download to /tmp -> Pillow/FFmpeg -> upload to OUTPUT bucket
      -> write metadata to DynamoDB -> logs in CloudWatch
Safe to retry: same input key -> same mediaId -> same output keys (overwrite, no duplicates),
and an already COMPLETED record for the same object version is skipped.
"""
import json
import os
import tempfile
import time
import urllib.parse
from decimal import Decimal

import boto3

from image_processor import InvalidMediaError
from media_common import build_record, media_id_from_key, media_type, output_keys, run_processor

s3 = boto3.client("s3")
table = boto3.resource("dynamodb").Table(os.environ.get("TABLE_NAME", "MediaMetadata"))

OUTPUT_BUCKET = os.environ["OUTPUT_BUCKET"]
CLOUDFRONT_DOMAIN = os.environ.get("CLOUDFRONT_DOMAIN", "")
MAX_INPUT_MB = int(os.environ.get("MAX_INPUT_MB", "200"))

CONTENT_TYPES = {".webp": "image/webp", ".jpg": "image/jpeg", ".mp4": "video/mp4"}


def to_dynamo(value):
    """DynamoDB does not accept Python floats -> convert to Decimal."""
    if isinstance(value, float):
        return Decimal(str(value))
    if isinstance(value, dict):
        return {k: to_dynamo(v) for k, v in value.items()}
    return value


def update_record(media_id, fields: dict):
    fields = to_dynamo(fields)
    table.update_item(
        Key={"mediaId": media_id},
        UpdateExpression="SET " + ", ".join(f"#{k} = :{k}" for k in fields),
        ExpressionAttributeNames={f"#{k}": k for k in fields},
        ExpressionAttributeValues={f":{k}": v for k, v in fields.items()},
    )


def process_one(bucket: str, key: str, etag: str):
    original_name = os.path.basename(key)
    media_id = media_id_from_key(key)
    log = {"mediaId": media_id, "key": key}

    # --- idempotency: skip duplicate S3 events for the same object version
    existing = table.get_item(Key={"mediaId": media_id}).get("Item")
    if existing and existing.get("status") == "COMPLETED" and existing.get("inputETag") == etag:
        print(json.dumps({**log, "skipped": "already processed"}))
        return

    if media_type(original_name) == "unsupported":
        update_record(media_id, {"status": "FAILED", "originalName": original_name,
                                 "errorMessage": "Unsupported file type", "inputKey": key})
        print(json.dumps({**log, "status": "FAILED", "reason": "unsupported type"}))
        return

    size = s3.head_object(Bucket=bucket, Key=key)["ContentLength"]
    if size > MAX_INPUT_MB * 1024 * 1024:
        update_record(media_id, {"status": "FAILED", "originalName": original_name,
                                 "originalSizeBytes": size, "inputKey": key,
                                 "errorMessage": f"File larger than {MAX_INPUT_MB} MB"})
        return

    update_record(media_id, {"status": "PROCESSING", "originalName": original_name,
                             "inputKey": key, "inputETag": etag})
    started = time.time()
    try:
        with tempfile.TemporaryDirectory(dir="/tmp") as tmp:
            src = os.path.join(tmp, original_name)
            s3.download_file(bucket, key, src)

            result = run_processor(src, os.path.join(tmp, "out"), media_id)
            keys = output_keys(media_id, result["outputExt"])

            for path, out_key in ((result["optimizedPath"], keys["outputKey"]),
                                  (result["thumbnailPath"], keys["thumbnailKey"])):
                ext = os.path.splitext(out_key)[1]
                s3.upload_file(path, OUTPUT_BUCKET, out_key, ExtraArgs={
                    "ContentType": CONTENT_TYPES.get(ext, "application/octet-stream"),
                    "CacheControl": "public, max-age=31536000",
                })

            record = build_record(media_id, original_name, size, result, keys,
                                  int((time.time() - started) * 1000), CLOUDFRONT_DOMAIN)
            record.pop("mediaId")
            record["errorMessage"] = ""
            update_record(media_id, record)
            print(json.dumps({**log, "status": "COMPLETED",
                              "reductionPercent": record["reductionPercent"],
                              "processingMs": record["processingMs"]}))
    except InvalidMediaError as e:
        update_record(media_id, {"status": "FAILED", "errorMessage": str(e)[:500]})
        print(json.dumps({**log, "status": "FAILED", "reason": str(e)}))
    except Exception as e:
        update_record(media_id, {"status": "FAILED", "errorMessage": str(e)[:500]})
        print(json.dumps({**log, "status": "FAILED", "reason": str(e)}))
        raise  # unexpected error -> let Lambda retry


def lambda_handler(event, context):
    for record in event.get("Records", []):
        bucket = record["s3"]["bucket"]["name"]
        key = urllib.parse.unquote_plus(record["s3"]["object"]["key"])
        etag = record["s3"]["object"].get("eTag", "")
        if bucket == OUTPUT_BUCKET:          # safety net against self-triggering loops
            print("Ignoring event from output bucket")
            continue
        process_one(bucket, key, etag)
    return {"statusCode": 200}
