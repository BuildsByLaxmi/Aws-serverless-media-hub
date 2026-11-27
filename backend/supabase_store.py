"""
Supabase Storage + PostgreSQL operations (replaces boto3 S3 + DynamoDB calls).
Everything the API and worker need goes through SupabaseStore, so tests can swap in a fake.
"""
import datetime as dt
import os

from supabase_config import INPUT_BUCKET, OUTPUT_BUCKET, SIGNED_URL_SECONDS, STALE_PROCESSING_SECONDS, TABLE


def _now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


class SupabaseStore:
    def __init__(self, client):
        self.c = client

    # ---------- database ----------
    def create_record(self, media_id, filename, media_type, size, input_path):
        row = {"media_id": media_id, "original_filename": filename, "media_type": media_type,
               "original_size": size, "original_path": input_path, "status": "UPLOADING"}
        self.c.table(TABLE).insert(row).execute()
        return row

    def get_record(self, media_id):
        r = self.c.table(TABLE).select("*").eq("media_id", media_id).limit(1).execute()
        return r.data[0] if r.data else None

    def list_records(self, limit=20):
        r = self.c.table(TABLE).select("*").order("created_at", desc=True).limit(limit).execute()
        return r.data

    def update_record(self, media_id, fields):
        fields = {**fields, "updated_at": _now()}
        self.c.table(TABLE).update(fields).eq("media_id", media_id).execute()

    def mark_uploaded(self, media_id):
        """UPLOADING -> UPLOADED, atomic. Returns True if this call made the change."""
        r = (self.c.table(TABLE).update({"status": "UPLOADED", "updated_at": _now()})
             .eq("media_id", media_id).eq("status", "UPLOADING").execute())
        return bool(r.data)

    def claim_for_processing(self, media_id):
        """Atomic UPLOADED -> PROCESSING. Only one caller can win, so duplicate triggers are
        harmless. A row stuck in PROCESSING longer than STALE_PROCESSING_SECONDS (crashed
        worker) can be reclaimed."""
        r = (self.c.table(TABLE).update({"status": "PROCESSING", "error_message": None, "updated_at": _now()})
             .eq("media_id", media_id).eq("status", "UPLOADED").execute())
        if r.data:
            return True
        cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(seconds=STALE_PROCESSING_SECONDS)).isoformat()
        r = (self.c.table(TABLE).update({"status": "PROCESSING", "updated_at": _now()})
             .eq("media_id", media_id).eq("status", "PROCESSING").lt("updated_at", cutoff).execute())
        return bool(r.data)

    def count_pending(self):
        r = (self.c.table(TABLE).select("media_id", count="exact")
             .in_("status", ["UPLOADING", "UPLOADED", "PROCESSING"]).limit(1).execute())
        return r.count or 0

    def pending_ids(self, limit=10):
        r = (self.c.table(TABLE).select("media_id").eq("status", "UPLOADED")
             .order("created_at").limit(limit).execute())
        return [x["media_id"] for x in r.data]

    # ---------- storage ----------
    def object_size(self, bucket, path):
        folder, name = os.path.split(path)
        for item in self.c.storage.from_(bucket).list(folder):
            if item.get("name") == name:
                return (item.get("metadata") or {}).get("size")
        return None

    def signed_upload(self, path):
        r = self.c.storage.from_(INPUT_BUCKET).create_signed_upload_url(path)
        return {"signed_url": r["signed_url"], "token": r["token"], "path": path}

    def upload_bytes(self, bucket, path, data, content_type):
        self.c.storage.from_(bucket).upload(path, data, {"content-type": content_type, "upsert": "true"})

    def download_to(self, bucket, path, dest):
        data = self.c.storage.from_(bucket).download(path)
        with open(dest, "wb") as f:
            f.write(data)

    def upload_file(self, bucket, path, src, content_type):
        with open(src, "rb") as f:
            self.upload_bytes(bucket, path, f.read(), content_type)

    def signed_url(self, bucket, path, seconds=SIGNED_URL_SECONDS):
        return self.c.storage.from_(bucket).create_signed_url(path, seconds)["signedURL"]
