"""Supabase settings, read from environment variables only (never hard-code keys)."""
import os

INPUT_BUCKET = os.environ.get("SUPABASE_INPUT_BUCKET", "media-input")
OUTPUT_BUCKET = os.environ.get("SUPABASE_OUTPUT_BUCKET", "media-output")
TABLE = "media_metadata"
MAX_INPUT_MB = int(os.environ.get("MAX_INPUT_MB", "50"))   # Supabase Free: 50 MB per-file upload cap
SIGNED_URL_SECONDS = int(os.environ.get("SIGNED_URL_SECONDS", "3600"))
STALE_PROCESSING_SECONDS = int(os.environ.get("STALE_PROCESSING_SECONDS", "900"))

ALLOWED_MIME_PREFIXES = ("image/", "video/")


def get_client():
    """Server-side client using the service-role key. Backend/worker only, never the browser."""
    from supabase import create_client
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env (see .env.example)")
    return create_client(url, key)
