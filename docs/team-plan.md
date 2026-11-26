# Team Plan: Who Does What

## Roles
| | **Person 1: Infrastructure lead** | **Person 2: Processing lead** | **Person 3: Application lead** |
|---|---|---|---|
| **Member** | Hiral Gupta (`1024030818`) | Laxmi Singla (`1024030834`) | Riddhi Dhawan (`1024030943`) |
| **GitHub** | [@Hiral07-og](https://github.com/Hiral07-og) | [@BuildsByLaxmi](https://github.com/BuildsByLaxmi) | [@riddhidhawan19](https://github.com/riddhidhawan19) |
| **Owns folders** | `infrastructure/` | `backend/image_processor.py`, `video_processor.py`, `lambda_function.py`, `tests/`, `scripts/build_ffmpeg_layer.py` | `frontend/`, `backend/upload_api.py`, `.github/workflows/` |
| **AWS services** | S3 (2 buckets), IAM, S3 trigger, CloudFront + OAC | Lambda, Lambda layer (FFmpeg), CloudWatch Logs | DynamoDB `MediaMetadata`, Lambda Function URL, GitHub Pages |
| **Responsibilities** | Buckets, permissions, CORS, trigger, CloudFront, **final integration** | Pillow resize / WebP / thumbnail, FFmpeg video, error handling, unit tests | Upload page, presigned-URL API, status polling, results page, metadata schema |
| **Deliverables** | Working buckets, IAM policies, trigger, CloudFront URL, `deployment-notes.md` | Tested processing code, test results, `processor.zip`, FFmpeg layer | Working website, DynamoDB schema, screenshots |
| **Git branch** | `feature/aws-setup` | `feature/media-processing` | `feature/frontend` |
| **Viva topics** | IAM least privilege, why two buckets, OAC vs public bucket, CDN caching, S3 events | Event-driven / FaaS, cold start, Lambda limits (15 min, /tmp, memory), WebP vs JPEG, FFmpeg flags | Presigned URLs, CORS, NoSQL design, polling, static hosting |

`backend/media_common.py` is **shared**. It holds the agreed keys and record format, so changes to it need agreement from Person 2 and Person 3.

## Git workflow
```bash
git clone https://github.com/BuildsByLaxmi/Aws-serverless-media-hub.git
git checkout -b feature/media-processing      # your own branch
# …work, test…
git add . && git commit -m "Add WebP compression"
git push origin feature/media-processing      # open a Pull Request into main
```
Person 1 reviews and merges the pull requests into `main`, because Person 1 owns integration.

## Two-week timeline (progress tracker)
| Days | Who | Milestone | Done? |
|---|---|---|---|
| 1–2 | All | GitHub repo, buckets, IAM roles, DynamoDB table (Steps 01, 03) | ☐ |
| 3–4 | P2, P3 (P1 prepares AWS) | Local image processing passes tests; upload UI runs in demo mode (Step 02) | ☐ |
| 5–7 | P1 + P2 | S3 → Lambda trigger; outputs + metadata appear automatically (Step 04) | ☐ |
| 8–9 | P1 + P3 | Upload API + website connected; CloudFront URLs (Steps 05, 06) | ☐ |
| 10–11 | P2 | FFmpeg layer + video processing (Step 08) | ☐ |
| 12–13 | All | Test cases, measurements, screenshots, report (Step 07) | ☐ |
| 14 | All | Final demo rehearsal: each member explains their part | ☐ |

## Demo script (about 5 minutes)
1. **P1:** show the architecture diagram, then the 2 private buckets, the trigger and CloudFront in the console
2. **P3:** open the website and upload a large photo while the status steps animate live
3. **P2:** open CloudWatch logs for that upload and explain the processing code
4. **P3:** show the before/after view, the reduction %, and the DynamoDB item
5. **P1:** open the CloudFront URL (it works), then the direct S3 URL (AccessDenied), to show security
6. **P2:** upload a video and show the 720p output and its thumbnail
