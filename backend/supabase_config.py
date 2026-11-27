"""Supabase settings, read from environment variables only (never hard-code keys)."""
import base64
import json
import os
import sys


def load_env_config():
    """Load environment variables from backend/.env or root .env if present."""
    try:
        from dotenv import load_dotenv
        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.path.join(base_dir, ".env"),
            os.path.join(base_dir, "..", ".env"),
            os.path.join(os.getcwd(), "backend", ".env"),
            os.path.join(os.getcwd(), ".env"),
        ]
        for p in candidates:
            if os.path.isfile(p):
                load_dotenv(p, override=False)
    except ImportError:
        pass


load_env_config()

INPUT_BUCKET = os.environ.get("SUPABASE_INPUT_BUCKET", "media-input")
OUTPUT_BUCKET = os.environ.get("SUPABASE_OUTPUT_BUCKET", "media-output")
TABLE = "media_metadata"
MAX_INPUT_MB = int(os.environ.get("MAX_INPUT_MB", "50"))   # Supabase Free: 50 MB per-file upload cap
SIGNED_URL_SECONDS = int(os.environ.get("SIGNED_URL_SECONDS", "3600"))
STALE_PROCESSING_SECONDS = int(os.environ.get("STALE_PROCESSING_SECONDS", "900"))

ALLOWED_MIME_PREFIXES = ("image/", "video/")


def get_supabase_credentials():
    """Extract and sanitize SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY."""
    load_env_config()
    url = (os.environ.get("SUPABASE_URL") or "").strip().strip("\"'").rstrip("/")
    key = (
        os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        or os.environ.get("SUPABASE_SERVICE_KEY")
        or os.environ.get("SUPABASE_KEY")
        or ""
    ).strip().strip("\"'")

    # Strip Windows CR if present
    url = url.replace("\r", "")
    key = key.replace("\r", "")

    if key.startswith("Bearer "):
        key = key[7:].strip()

    return url, key


def inspect_key_role(key: str) -> str:
    """Safely check the JWT role without exposing credentials or requiring secret verification."""
    try:
        parts = key.split(".")
        if len(parts) >= 2:
            padded = parts[1] + "=" * ((4 - len(parts[1]) % 4) % 4)
            payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
            return payload.get("role", "unknown")
    except Exception:
        pass
    return "unknown"


def get_client():
    """Server-side client using the service-role key. Backend/worker only, never the browser."""
    from supabase import create_client
    url, key = get_supabase_credentials()
    if not url or not key:
        raise RuntimeError("Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY in backend/.env (see .env.example)")

    role = inspect_key_role(key)
    if role == "anon":
        print(
            "WARNING: SUPABASE_SERVICE_ROLE_KEY is set to an 'anon' public key ('role': 'anon'). "
            "Row Level Security (RLS) denies database access to the anon key. "
            "Please use the 'service_role' secret key from Supabase Dashboard > Project Settings > API.",
            file=sys.stderr,
            flush=True,
        )

    return create_client(url, key)


def diagnose_supabase():
    """Diagnose Supabase connection, credentials, tables and buckets independently."""
    print("=== Supabase Connection Diagnostic ===")
    url, key = get_supabase_credentials()
    if not url:
        print("[FAIL] SUPABASE_URL is missing or empty.")
        print("       Set SUPABASE_URL in backend/.env or Codespaces secrets.")
        return False
    print(f"[OK] SUPABASE_URL format: {url}")

    if not key:
        print("[FAIL] SUPABASE_SERVICE_ROLE_KEY is missing or empty.")
        print("       Set SUPABASE_SERVICE_ROLE_KEY in backend/.env or Codespaces secrets.")
        return False

    role = inspect_key_role(key)
    masked = key[:6] + "..." + key[-4:] if len(key) > 10 else "***"
    print(f"[INFO] API Key format: JWT (length={len(key)}, masked={masked}, detected_role='{role}')")
    if role == "anon":
        print("[FAIL] Key has role='anon'! Supabase requires the 'service_role' secret key for the backend and worker.")
        print("       Go to Supabase Dashboard > Project Settings > API and copy 'service_role'.")

    try:
        client = get_client()
    except Exception as e:
        print(f"[FAIL] Could not instantiate Supabase client: {e}")
        return False

    # Test PostgREST API
    print(f"[INFO] Testing database table '{TABLE}' access...")
    try:
        r = client.table(TABLE).select("media_id").limit(1).execute()
        print(f"[OK] Database query succeeded (status 200). Table '{TABLE}' is accessible.")
    except Exception as e:
        err_msg = str(e)
        if "Invalid API key" in err_msg:
            print("[FAIL] PostgREST returned 'Invalid API key'!")
            print("       Reasons: 1) The key does not match this project URL, 2) Secret was rotated, or 3) Key has extra whitespace/quotes.")
        elif "PGRST204" in err_msg or "does not exist" in err_msg.lower():
            print(f"[FAIL] Table '{TABLE}' does not exist! Run supabase/migrations/0001_security.sql in Supabase SQL Editor.")
        else:
            print(f"[FAIL] Database query failed: {err_msg}")

    # Test Storage Buckets
    print(f"[INFO] Testing storage buckets ('{INPUT_BUCKET}', '{OUTPUT_BUCKET}')...")
    try:
        buckets = client.storage.list_buckets()
        bucket_names = [b.name for b in buckets] if buckets else []
        print(f"[INFO] Discovered buckets: {bucket_names}")
        for b in (INPUT_BUCKET, OUTPUT_BUCKET):
            if b in bucket_names:
                print(f"[OK] Bucket '{b}' exists.")
            else:
                print(f"[WARN] Bucket '{b}' not found in bucket list. Verify private bucket '{b}' exists in Storage.")
    except Exception as e:
        print(f"[WARN] Storage bucket check error: {e}")

    return True


if __name__ == "__main__":
    diagnose_supabase()
