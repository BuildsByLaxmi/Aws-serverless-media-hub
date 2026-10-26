# Team Interface & Integration Contract
**AWS Serverless Media Transcoder and Thumbnail Pipeline**  
**Lead Owner**: Person 1 (Infrastructure & Delivery Lead)  
**Collaborators**: Person 2 (Media Processing Lead), Person 3 (Website & Database Lead)

---

## 1. Purpose of this Document
To ensure each team member can work independently without resource clashes, blocking dependencies, or naming discrepancies. **All three team members must adhere strictly to these conventions.**

---

## 2. Team Member Ownership & Git Branches

| Member | Role | Folder Ownership | Git Branch | Key Deliverable |
| :--- | :--- | :--- | :--- | :--- |
| **Person 1** | **Infrastructure & Delivery** | `infrastructure/` | `feature/aws-setup` | S3 buckets, IAM, CloudFront OAC, triggers, CloudFormation |
| **Person 2** | **Media Processing & Lambda** | `backend/` | `feature/media-processing` | Python handler, Pillow resizing/WebP, FFmpeg, tests |
| **Person 3** | **Website & Metadata** | `frontend/` | `feature/frontend` | Upload UI, Presigned URL client, metrics display |

> **Rule**: Never push directly to `main`. Create pull requests from feature branches into `main`. Person 1 reviews and merges once individual modules are verified.

---

## 3. Global AWS Configuration
- **AWS Region**: `us-east-1` (Default) or `ap-south-1` *(must be the same for all resources)*
- **Input S3 Bucket**: `media-hub-input-<UNIQUE_SUFFIX>` (e.g., `media-hub-input-group07`)
- **Output S3 Bucket**: `media-hub-output-<UNIQUE_SUFFIX>` (e.g., `media-hub-output-group07`)
- **DynamoDB Table Name**: `MediaMetadata`
- **Lambda Function Name**: `MediaPipelineProcessor`
- **CloudFront CDN Distribution**: `https://<DISTRIBUTION_ID>.cloudfront.net`

---

## 4. S3 Key Hierarchy (Storage Layout)

### A. Input S3 Bucket (`media-hub-input-<ID>`)
Uploads must be placed under the `raw/` prefix:
```text
raw/
└── {mediaId}-{originalFilename}
```
*Example*: `raw/img_a1b2c3d4-photo.jpg` or `raw/vid_e5f6g7h8-clip.mp4`

### B. Output S3 Bucket (`media-hub-output-<ID>`)
Lambda (Person 2) writes processed assets into two dedicated folders:
```text
output-bucket/
├── processed/
│   ├── {mediaId}.webp      # Optimized image (WebP, max width 1920px)
│   └── {mediaId}.mp4       # Transcoded video (H.264/AAC, optimized bitrate)
└── thumbnails/
    ├── {mediaId}.jpg       # Image thumbnail (200x200 JPEG, aspect ratio preserved)
    └── {mediaId}.jpg       # Video thumbnail (320x180 JPEG, frame at 00:00:01)
```

---

## 5. Lambda Environment Variables (Configured by Person 1 for Person 2)

Person 2's Python code must read configuration dynamically using `os.environ.get()`:

| Environment Variable | Description | Example Value |
| :--- | :--- | :--- |
| `OUTPUT_BUCKET` | Target bucket for processed media | `media-hub-output-group07` |
| `DYNAMODB_TABLE` | Metadata tracking table | `MediaMetadata` |
| `CLOUDFRONT_DOMAIN` | CDN domain serving outputs | `d123456abcdef.cloudfront.net` |
| `IMAGE_MAX_WIDTH` | Maximum width for resized images | `1920` |
| `IMAGE_QUALITY` | WebP compression quality (1-100) | `82` |
| `THUMBNAIL_WIDTH` | Image thumbnail width in px | `200` |
| `THUMBNAIL_HEIGHT` | Image thumbnail height in px | `200` |
| `VIDEO_MAX_HEIGHT` | Target height for 720p transcoding| `720` |

---

## 6. DynamoDB Table Schema (`MediaMetadata`)

- **Table Name**: `MediaMetadata`
- **Partition Key (Hash Key)**: `mediaId` (Type: `String`)
- **Sort Key**: None (single-item lookup)

### Record Schema & Data Types:
```json
{
  "mediaId": "img_a1b2c3d4",
  "originalName": "family_vacation.jpg",
  "mediaType": "IMAGE",
  "mimeType": "image/jpeg",
  "originalSizeBytes": 4194304,
  "optimizedSizeBytes": 943718,
  "reductionPercent": 77.5,
  "originalDimensions": "4032x3024",
  "optimizedDimensions": "1920x1440",
  "status": "COMPLETED",
  "uploadedAt": "2026-10-26T10:00:00Z",
  "processedAt": "2026-10-26T10:00:03Z",
  "processingDurationMs": 2840,
  "outputKey": "processed/img_a1b2c3d4.webp",
  "thumbnailKey": "thumbnails/img_a1b2c3d4.jpg",
  "outputUrl": "https://d123456abcdef.cloudfront.net/processed/img_a1b2c3d4.webp",
  "thumbnailUrl": "https://d123456abcdef.cloudfront.net/thumbnails/img_a1b2c3d4.jpg",
  "errorMessage": null
}
```

### Allowed Status Values:
1. `PROCESSING` — File received by Lambda, processing in progress.
2. `COMPLETED` — Optimized file and thumbnail saved, metadata populated.
3. `FAILED` — Processing failed (corrupt file, unsupported codec, out-of-memory). `errorMessage` contains the error.

---

## 7. Metrics & Formula Specification
The reduction percentage calculation must be consistent across Person 2 (calculation) and Person 3 (display):

$$\text{reductionPercent} = \frac{\text{originalSizeBytes} - \text{optimizedSizeBytes}}{\text{originalSizeBytes}} \times 100$$

- Rounded to **2 decimal places** (e.g. `77.50%`).
- For videos where optimization is applied, the same formula applies.
- Space saved in bytes: `originalSizeBytes - optimizedSizeBytes`.

---

## 8. Frontend Upload Flow (Person 3 Integration)

To eliminate the need for exposing AWS IAM credentials in frontend JavaScript:
1. **Presigned Upload Method**:
   - The user selects a file on `frontend/index.html`.
   - `app.js` generates a unique `mediaId` (e.g., `img_` + random 8-character hex string).
   - `app.js` obtains a presigned S3 upload URL (generated via Person 1's helper script/Lambda or AWS SDK).
   - `app.js` performs an HTTP `PUT` request with the binary file directly to S3.
2. **Status Polling**:
   - `app.js` polls DynamoDB every 2 seconds using the `mediaId` until `status === "COMPLETED"`.
   - Once completed, `app.js` renders the before/after preview, file sizes, savings percentage, and clickable CloudFront URLs.

---

## 9. CloudFront Delivery Rules
- All media assets delivered to the client **MUST** use the CloudFront HTTPS URL:  
  `https://<CLOUDFRONT_DOMAIN>/processed/{mediaId}.webp`  
  `https://<CLOUDFRONT_DOMAIN>/thumbnails/{mediaId}.jpg`
- Direct S3 `s3.amazonaws.com` URLs must **never** be used on the frontend. The S3 output bucket has **Block Public Access enabled**, and requests directly to S3 will return `403 Access Denied`.
