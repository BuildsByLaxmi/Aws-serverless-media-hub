"""In-memory stand-in for SupabaseStore with the same interface and atomic-claim semantics."""
import datetime as dt
import os


class FakeStore:
    def __init__(self):
        self.rows, self.objects = {}, {}

    def _now(self): return dt.datetime.now(dt.timezone.utc).isoformat()

    def create_record(self, media_id, filename, media_type, size, input_path):
        if media_id in self.rows: raise ValueError("duplicate key")
        self.rows[media_id] = {"media_id": media_id, "original_filename": filename, "media_type": media_type,
            "original_size": size, "optimized_size": None, "compression_percentage": None,
            "original_path": input_path, "processed_path": None, "thumbnail_path": None,
            "status": "UPLOADING", "processing_time": None, "error_message": None,
            "created_at": self._now(), "updated_at": self._now()}
        return self.rows[media_id]

    def get_record(self, mid): return dict(self.rows[mid]) if mid in self.rows else None
    def list_records(self, limit=20): return [dict(r) for r in self.rows.values()][:limit]
    def update_record(self, mid, fields): self.rows[mid].update({**fields, "updated_at": self._now()})

    def mark_uploaded(self, mid):
        if self.rows[mid]["status"] != "UPLOADING": return False
        self.update_record(mid, {"status": "UPLOADED"}); return True

    def claim_for_processing(self, mid):
        if self.rows[mid]["status"] != "UPLOADED": return False
        self.update_record(mid, {"status": "PROCESSING", "error_message": None}); return True

    def count_pending(self):
        return sum(r["status"] in ("UPLOADING", "UPLOADED", "PROCESSING") for r in self.rows.values())

    def stats_rows(self, limit=10000):
        return [dict(r) for r in self.rows.values()]

    def get_many(self, ids):
        return [dict(self.rows[i]) for i in ids if i in self.rows]

    def pending_ids(self, limit=10):
        return [m for m, r in self.rows.items() if r["status"] == "UPLOADED"][:limit]

    def object_size(self, bucket, path):
        d = self.objects.get((bucket, path)); return len(d) if d is not None else None
    def signed_upload(self, path): return {"signed_url": f"fake://upload/{path}", "token": "t", "path": path}
    def upload_bytes(self, bucket, path, data, ct): self.objects[(bucket, path)] = data
    def upload_file(self, bucket, path, src, ct):
        with open(src, "rb") as f: self.objects[(bucket, path)] = f.read()
    def download_to(self, bucket, path, dest):
        with open(dest, "wb") as f: f.write(self.objects[(bucket, path)])
    def signed_url(self, bucket, path, seconds=3600):
        assert (bucket, path) in self.objects
        return f"fake://signed/{bucket}/{path}?exp={seconds}"
