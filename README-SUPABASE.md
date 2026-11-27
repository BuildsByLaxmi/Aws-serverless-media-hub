# Supabase version (branch `feature/supabase-integration`)

The original AWS implementation (Lambda, S3, DynamoDB, CloudFront) is untouched and kept as the reference. This branch adds a Supabase version beside it.

| AWS | Supabase version |
|---|---|
| S3 input / output buckets | Storage `media-input` / `media-output` (private) |
| DynamoDB `MediaMetadata` | Postgres `public.media_metadata` |
| Upload Lambda | FastAPI app `backend/supabase_api.py` (signed upload URLs) |
| Processor Lambda + S3 event | Python worker `backend/supabase_worker.py` (polls for `UPLOADED` rows; also `POST /internal/process/{id}` with a secret token) |
| CloudFront | Short-lived signed URLs |

Pillow and FFmpeg code (`image_processor.py`, `video_processor.py`, `media_common.py`) is reused unchanged except WebP quality default 80 -> 82 (per project spec).

**Honest deployment note:** the API and worker run on your own machine (`localhost`). That is not a cloud-hosted serverless deployment. No free FFmpeg worker host has been verified yet.

## Flow
`POST /api/uploads` (validates, creates row `UPLOADING`, returns signed upload URL) -> browser PUTs file to `media-input` -> `POST /api/uploads/{id}/complete` (checks object exists, row `UPLOADED`) -> worker claims row atomically (`PROCESSING`), processes, uploads `processed/{id}.webp|mp4` and `thumbnails/{id}.jpg` to `media-output`, row `COMPLETED` or `FAILED` -> `GET /api/media/{id}` returns status plus signed URLs.

## Setup
1. Supabase Dashboard > SQL Editor: paste and run `supabase/migrations/0001_security.sql` (RLS deny-by-default, status constraint, keeps buckets private).
2. Dashboard > Project Settings > API: copy Project URL and the `service_role` key into `backend/.env` (copy from `backend/.env.example`). Never commit it or put it in the frontend.
3. `pip install -r backend/requirements-supabase.txt` and install FFmpeg.

## Demo
```bash
uvicorn supabase_api:app --app-dir backend --port 8000     # terminal 1 (API)
python backend/supabase_worker.py                           # terminal 2 (worker)
python -m http.server 5500 -d frontend                      # terminal 3 (UI at http://localhost:5500)
```
Or set `PROCESS_INLINE=true` to skip the separate worker.

## Tests
```bash
python -m pytest tests -q
```
Supabase calls are replaced by an in-memory fake (`tests/fake_store.py`); Pillow/FFmpeg run for real. Live Supabase calls are not covered by tests.

## Notes
- Spec check: images max 1920 px, WebP q82, 200x200 JPEG thumbnail, video H.264 720p max. Video over 60 s is truncated to 60 s (original behaviour), not rejected.
- Free tier: Supabase Free caps uploads at 50 MB per file, so `MAX_INPUT_MB` defaults to 50 (AWS version used 200).
- The demo has no user login: anyone who can reach the API can upload. Do not expose it publicly without adding auth.

## Live smoke test (real Supabase project)
```bash
export SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=...   # or put them in backend/.env and `set -a; . backend/.env`
python scripts/live_smoke_test.py
```
Uploads a real image and video through the API with signed upload URLs, runs the worker, fetches the signed output URLs, checks the duplicate run is skipped, then deletes its own test rows and files. Passed on 2026-11-27 against the `media-pipeline` project.
