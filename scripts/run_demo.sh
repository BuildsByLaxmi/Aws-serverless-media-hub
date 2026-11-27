#!/usr/bin/env bash
# One command demo (local machine or GitHub Codespaces): API + UI on port 8000 and the worker.
# Needs SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY, either exported (Codespaces secrets) or in backend/.env
set -euo pipefail
cd "$(dirname "$0")/.."
command -v ffmpeg >/dev/null || { echo "ffmpeg not found. Install it first (see README-SUPABASE.md)"; exit 1; }
[ -f backend/.env ] && { set -a; . backend/.env; set +a; }
[ -f .env ] && { set -a; . .env; set +a; }
: "${SUPABASE_URL:?Set SUPABASE_URL (backend/.env or Codespaces secret)}"
: "${SUPABASE_SERVICE_ROLE_KEY:?Set SUPABASE_SERVICE_ROLE_KEY (backend/.env or Codespaces secret)}"
python backend/supabase_worker.py &
WORKER=$!
trap 'kill $WORKER 2>/dev/null' EXIT
echo "Open the forwarded port 8000 (Codespaces: Ports tab > globe icon) or http://localhost:8000"
uvicorn supabase_api:app --app-dir backend --host 0.0.0.0 --port 8000
