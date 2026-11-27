# AWS Serverless Media Transcoder & Thumbnail Pipeline

**Cloud Computing Project** · Amazon S3 · AWS Lambda · Amazon DynamoDB · Amazon CloudFront

Upload a photo or video and AWS processes it automatically:

| You upload | The pipeline creates |
|---|---|
| `photo.jpg` (6.4 MB, 4000×3000) | `processed/<id>.webp` (108 KB, 1920×1440, **−98 %**) + `thumbnails/<id>.jpg` (200×200) |
| `video.mp4` (1080p) | `processed/<id>.mp4` (720p H.264) + `thumbnails/<id>.jpg` (a video frame) |

DynamoDB stores the original size, optimized size, % saved, dimensions, processing time and status. CloudFront serves the files.

```
Website ─► S3 Input ─► S3 Event ─► Lambda (Pillow / FFmpeg) ─► S3 Output ─► CloudFront ─► Website
                                         └──────────► DynamoDB (MediaMetadata) ◄── status API
```
For the full diagram, the interface contract and the design decisions, see [`infrastructure/architecture.md`](infrastructure/architecture.md).

> **Free alternative:** a Supabase version of this pipeline (no AWS account needed) is described in [`README-SUPABASE.md`](README-SUPABASE.md).

---

## Project structure
```
aws-media-pipeline/
├── frontend/                     ← Person 3
│   ├── index.html                upload page · status · before/after · history
│   ├── style.css
│   ├── app.js                    presigned upload, status polling, results (+ demo mode)
│   └── config.js                 API_URL goes here
├── backend/
│   ├── lambda_function.py        ← Person 2: processor Lambda (S3-triggered)
│   ├── image_processor.py        ← Person 2: Pillow resize / WebP / 200×200 thumbnail
│   ├── video_processor.py        ← Person 2: FFmpeg compress + frame thumbnail
│   ├── upload_api.py             ← Person 3: presigned URL + status API Lambda
│   ├── media_common.py           shared contract: mediaId, S3 keys, record format
│   └── requirements.txt
├── infrastructure/               ← Person 1
│   ├── architecture.md
│   ├── deployment-notes.md       console steps 01–08
│   ├── iam-processor-policy.json, iam-upload-api-policy.json
│   ├── s3-input-cors.json, s3-output-bucket-policy.json
│   └── template.yaml             optional one-command deploy (AWS SAM)
├── scripts/
│   ├── package_lambda.py         builds dist/processor.zip + dist/upload_api.zip
│   ├── build_ffmpeg_layer.py     builds dist/ffmpeg-layer.zip
│   └── local_pipeline.py         runs the whole pipeline offline
├── tests/
│   ├── test_processor.py         11 unit tests
│   ├── test_images/              landscape, portrait, large, transparent PNG, invalid file
│   └── test_videos/              sample_video.mp4
├── docs/
│   ├── team-plan.md              roles, branches, timeline, demo script
│   ├── test-cases.md             measured results + AWS test table
│   └── report-and-viva.md        report chapters + 19 viva Q&A
└── .github/workflows/pages.yml   auto-deploys frontend/ to GitHub Pages
```

## Quick start

**1. Without AWS (try it in 2 minutes)**
```bash
pip install Pillow                                   # FFmpeg is needed only for the video test
python -m unittest discover -s tests -v              # 11 tests
python scripts/local_pipeline.py tests/test_images   # full pipeline offline → local_cloud/
```
Open `frontend/index.html` in Chrome. With `API_URL` empty, it runs in **demo mode** and simulates processing in the browser.

**2. On AWS:** follow [`infrastructure/deployment-notes.md`](infrastructure/deployment-notes.md) step by step (Steps 01–08). It works with a normal AWS account or a college AWS Academy lab (use `LabRole`).

## Team
| Person | Name | GitHub | Role | Branch |
|---|---|---|---|---|
| Person 1 | Hiral Gupta (`1024030818`) | [@Hiral07-og](https://github.com/Hiral07-og) | Infrastructure & delivery (S3, IAM, trigger, CloudFront, integration) | `feature/aws-setup` |
| Person 2 | Laxmi Singla (`1024030834`) | [@BuildsByLaxmi](https://github.com/BuildsByLaxmi) | Media processing & Lambda (Pillow, FFmpeg, tests) | `feature/media-processing` |
| Person 3 | Riddhi Dhawan (`1024030943`) | [@riddhidhawan19](https://github.com/riddhidhawan19) | Website & metadata (UI, upload API, DynamoDB) | `feature/frontend` |

The full task list, two-week timeline and demo script are in [`docs/team-plan.md`](docs/team-plan.md).

## Build order (the important rule)
**Get images working end to end first, then add video.** Steps 01 to 07 give you a complete project, and Step 08 (FFmpeg) is the extra feature on top.

## Cost & safety
Everything fits in the AWS Free Tier for a college demo. Set a budget alert first, keep both buckets private, never put AWS keys in `app.js`, and delete the resources after the evaluation (see the clean-up section of the deployment notes).
