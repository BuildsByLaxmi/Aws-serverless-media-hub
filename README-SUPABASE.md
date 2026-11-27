# Supabase version of the Media Pipeline

The original AWS version (S3, Lambda, DynamoDB, CloudFront) is still in this repo and untouched. This version does the same job with free-tier friendly services. Use whichever fits: AWS needs an AWS account, this one needs a free Supabase project.

## What it does
Upload an image or video. A Python worker makes an optimized copy plus a thumbnail, and the page shows status, size saved, a preview and a download link.

| | Output |
|---|---|
| Image | `processed/{id}.webp` (max 1920 px, WebP quality 82) + `thumbnails/{id}.jpg` (200x200) |
| Video | `processed/{id}.mp4` (H.264, max 720p, first 60 s only) + `thumbnails/{id}.jpg` (200x200 frame) |

## AWS vs Supabase
| AWS | Supabase version |
|---|---|
| S3 input / output buckets | Storage `media-input` / `media-output` (private) |
| DynamoDB `MediaMetadata` | Postgres table `public.media_metadata` |
| Upload API Lambda | FastAPI app `backend/supabase_api.py` |
| S3 event -> processor Lambda | Python worker `backend/supabase_worker.py` (polls the table) |
| CloudFront | Short-lived signed URLs (1 hour) |
| Pillow / FFmpeg code | The same files, reused unchanged |

```
Browser --1 POST /api/uploads--> FastAPI --creates row (UPLOADING)--> Postgres
Browser --2 PUT file (signed URL, raw body)--------------------------> Storage media-input (private)
Browser --3 POST /api/uploads/{id}/complete--> FastAPI (checks file, row -> UPLOADED)
Worker  --4 claims row (PROCESSING), downloads, Pillow/FFmpeg--------> Storage media-output
Worker  --5 row -> COMPLETED + sizes + paths                         Postgres
Browser --6 GET /api/media/{id}--> status + signed preview/download URLs
```
Statuses: `UPLOADING -> UPLOADED -> PROCESSING -> COMPLETED | FAILED`. Two workers can never process the same file: the claim is one atomic database update.

## Prerequisites
Python 3.10+, FFmpeg, a free Supabase project with two **private** buckets `media-input` and `media-output` and the table `public.media_metadata` (SQL in the Supabase project notes / your original setup).

## Setup
1. **Database + security SQL.** Supabase Dashboard > your project > SQL Editor > New query > paste `supabase/migrations/0001_security.sql` > Run. It is safe to run again. It turns on Row Level Security with no public access, gives the backend's `service_role` the table permissions, and keeps the buckets private.
2. **Keys.** Dashboard > Project Settings > API: copy the Project URL and the secret / `service_role` key. Copy `backend/.env.example` to `backend/.env` and fill them in. `.env` is git-ignored. Never put the key in `frontend/`, in chat, or on GitHub.
3. **Install.** `pip install -r backend/requirements-supabase.txt` and install FFmpeg (`sudo apt-get install ffmpeg`, `brew install ffmpeg`, or `choco install ffmpeg`).

## Run the demo (one command)
```bash
./scripts/run_demo.sh
```
This starts the worker and the API, and the API also serves the web page. Open http://localhost:8000. Prefer separate terminals?
```bash
python backend/supabase_worker.py                              # terminal 1: worker
uvicorn supabase_api:app --app-dir backend --port 8000         # terminal 2: API + UI
```
(Or set `PROCESS_INLINE=true` and skip the worker; the API then processes uploads itself.)

### GitHub Codespaces
1. Repo page > Code > Codespaces > Create codespace on the branch. FFmpeg and Python packages install automatically (`.devcontainer/`).
2. Keep keys out of git: repo Settings > Secrets and variables > Codespaces > New repository secret, add `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` (rebuild or restart the codespace afterwards), or create `backend/.env` inside the codespace.
3. In the terminal run `./scripts/run_demo.sh`. Open the **Ports** tab, find port 8000, click the globe icon. The page and the API share one address, so there is no `localhost` or CORS problem. Port 8000 stays private (only you) which is what you want.

## API
| Endpoint | Purpose |
|---|---|
| `POST /api/uploads` `{filename,size,content_type}` | Validates, creates the row, returns `media_id` and a signed upload URL (rate limited per IP) |
| `POST /api/uploads/{id}/complete` | Checks the file arrived, marks `UPLOADED` (safe to call twice) |
| `GET /api/media/{id}` | Status, sizes, and signed URLs once `COMPLETED` |
| `GET /api/stats` | Dashboard totals for ALL uploads (counts, bytes, average reduction). Aggregates only |
| `GET /api/batch?ids=a,b,c` | Cumulative summary for up to 20 ids you supply. Unknown ids are only counted |
| `GET /api/admin/media` | Admin list. Needs header `X-Worker-Token` |
| `POST /internal/process/{id}` | Trigger processing. Needs header `X-Worker-Token` |

Example with curl (the file upload itself goes straight to Supabase with the returned URL):
```bash
curl -s localhost:8000/api/uploads -H 'content-type: application/json' -d '{"filename":"cat.jpg","size":123456,"content_type":"image/jpeg"}'
curl -X PUT "<signed_url from above>" -H 'content-type: image/jpeg' --data-binary @cat.jpg
curl -X POST localhost:8000/api/uploads/<media_id>/complete
curl localhost:8000/api/media/<media_id>
```

## Tests
```bash
python -m pytest tests -q                 # 33 tests: original AWS processor tests + Supabase workflow
python scripts/live_smoke_test.py         # LIVE: needs real keys, uploads and then deletes its own test data
```
- Unit tests use an in-memory fake instead of Supabase (`tests/fake_store.py`); Pillow and FFmpeg run for real.
- The live smoke test talks to your real Supabase project.
- The browser flow was tested by hand-scripted Chrome against the real project.

## Security notes
- Buckets are private; files are only reachable through signed URLs. Service key lives only in backend environment variables.
- Server-side checks: allowed file extensions and MIME types, size limit (default 50 MB, the Supabase Free cap), sanitized filenames, atomic duplicate-processing guard, worker endpoint needs a secret token (constant-time compare).
- Media ids contain 80 random bits and the public listing is removed, so a status page can only be opened by someone who has its id.
- Limits per IP (30 uploads/hour) and a cap on queued uploads protect your free storage.
- **There is no user login.** Anyone who can reach the API can upload (within the limits). That is fine for a demo on a private Codespaces port. Do not publish it widely without adding authentication.
- `X-Forwarded-For` is trusted for the rate limit; behind a proxy that's correct, but exposed directly it can be spoofed.

## Hosting for free (prepared, not deployed)
`Dockerfile` and `render.yaml` are ready, so the API + UI + worker run as one Render web service on the free plan. Limits from Render's pages (https://render.com/docs/free, https://render.com/pricing): sleeps after 15 min idle (about 1 min to wake), 512 MB RAM, 750 free hours/month, files are lost on restart (fine: files live in Supabase), outbound bandwidth beyond the free amount is billed unless no card is on file, in which case it suspends. Large videos may not fit in 512 MB; not tested. Nothing has been deployed. Supabase Free: 1 GB storage, 500 MB database, 5 GB egress, 50 MB per file, project pauses after 1 week of inactivity (resume it from the dashboard).

## Common errors
| Message | Fix |
|---|---|
| `permission denied for table media_metadata` | Run `0001_security.sql` (it grants `service_role`). |
| `Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY` | Fill `backend/.env` or export the variables. |
| `FFmpeg not found` | Install FFmpeg and restart the worker. |
| Page says `Failed to fetch` | Open the page from the API's own address (port 8000), not a different server. |
| Upload works but status stays `UPLOADED` | The worker isn't running (or set `PROCESS_INLINE=true`). |
| `Too many uploads` (429) | Wait, or raise `UPLOADS_PER_HOUR`. |
| Supabase calls fail after a quiet week | Free projects pause; click Restore in the dashboard. |

## Spec notes and known behavior
Images: max 1920 px, WebP q82 (changed from 80 in the original code to match the spec). Videos longer than 60 s are cut to the first 60 s, not rejected (original behavior). Tiny PNGs can get slightly bigger as WebP, so the reduction percentage can be negative. Input limit is 50 MB here (200 MB on AWS).


## Five added features (branch `feature/five-features`)
1. **Before/after comparison**: each finished card shows the original and the optimized file side by side (images or videos) with sizes, space saved, reduction %, original/optimized dimensions and the measured processing time. The original is shown through a short-lived signed URL (only for COMPLETED items; storage paths are never returned).
2. **Optimization dashboard** (`GET /api/stats`): files processed, failed, in progress, total storage saved, average reduction. There are no user accounts, so it counts every upload to the deployment.
3. **Quality evaluation**: PSNR (dB) between the resized original and the decoded WebP, computed with Pillow only (no new packages). Images only, not videos. Labels: >=40 excellent, >=35 very good, >=30 good, >=25 fair, below low. PSNR is a rough number, not a replacement for looking at the picture.
4. **Batch processing**: choose up to 10 files; they upload one after another, each processed independently, then "Last batch" shows cumulative savings (`GET /api/batch`).
5. **Intelligent output selection** (`backend/output_policy.py`): settings chosen per file and the reason is saved in `settings_used` and shown.
   - Images (max 1920 px, never upscaled, WebP): transparent -> q90; small (<100 KB and <1 MP) -> q90; very large (>=12 MP or >=5 MB) -> q78; standard (>=2 MP) -> q82 (spec default); low resolution -> q85.
   - Videos (H.264, max 720p, first 60 s): small or <=480p -> CRF 26; >=1080p -> CRF 30; otherwise CRF 28.

### Database step (once): run `supabase/migrations/0002_features.sql`
Supabase Dashboard > SQL Editor > New query > paste the file > Run. It only adds optional columns and is safe to re-run. Until it is run, everything still works: the worker prints a warning and skips the new columns (dimensions, PSNR and settings show as "-" or are hidden).

### Quality experiment (hand-run, not part of the app)
`python scripts/quality_experiment.py path/to/image.jpg` prints size and PSNR for WebP quality 95/82/80/60. Results apply to that one image only.

### Limitations
- Dashboard and batch counts are global/per-id; no per-user history without accounts.
- PSNR is images only. Sequential uploads, max 10 per batch. Free-tier limits still apply (50 MB per file, 1 GB storage).
- The processed result uses the policy only in the Supabase worker; the AWS code path is unchanged.
