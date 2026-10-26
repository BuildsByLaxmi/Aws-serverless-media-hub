# Frontend Module: Website & Application Interface
**Lead Owner**: Person 3 (Application Lead)  
**Collaborators**: Person 1 & Person 2

---

## 1. Responsibilities
- Build the web interface (`index.html`, `style.css`, `app.js`).
- Implement the file upload workflow (direct upload to S3 using Presigned URLs to prevent exposing AWS keys).
- Query DynamoDB (`MediaMetadata`) for processing status (`PROCESSING` -> `COMPLETED`).
- Display comparison metrics:
  - Original file size vs Optimized file size.
  - Storage reduction percentage saved.
  - Before-and-after image/video preview.
  - Links to CloudFront-delivered assets.

---

## 2. Configuration Parameters
`app.js` will interact with the following resources provisioned by Person 1:
- **Input S3 Bucket**: Provided by Person 1 via `infrastructure/interface-contract.md`.
- **CloudFront Domain**: `https://<DISTRIBUTION_ID>.cloudfront.net` (Used to display processed files and thumbnails).
- **DynamoDB Table**: `MediaMetadata`.

---

## 3. Recommended Frontend Flow
1. User selects a local image or video file.
2. Web app displays an immediate local preview and original file size.
3. Web app obtains an S3 Presigned URL (using Person 1's generator or backend endpoint).
4. Web app uploads file directly to S3 via HTTP `PUT`.
5. Web app polls DynamoDB using the unique `mediaId` until `status === "COMPLETED"`.
6. Web app displays:
   - Optimized media via CloudFront CDN.
   - Generated thumbnail.
   - Exact savings percentage: `((original - optimized) / original) * 100`.
