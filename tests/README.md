# Test Assets & Validation Suite
**Owner**: All Team Members  
**Coordinator**: Person 1 (Integration Lead)

---

## 1. Directory Structure
```text
tests/
├── test_images/
│   └── (Sample JPEG/PNG files: landscape, portrait, high-res 4MB+)
├── test_videos/
│   └── (Sample MP4/MOV clips: 10s-30s short test clips)
└── README.md
```

---

## 2. Recommended Test Cases

| Test Case | Input Asset | Expected Outcome | Verification Metric |
| :--- | :--- | :--- | :--- |
| **TC-01: High-Res Photo** | 4-8 MB JPEG (Landscape) | Resized to max 1920px, WebP format, 200x200 thumb | >70% size reduction |
| **TC-02: Portrait Photo** | 3 MB PNG (Portrait) | Aspect ratio preserved, WebP format, 200x200 thumb | >65% size reduction |
| **TC-03: Small Image** | <500 KB JPEG | Valid WebP + thumbnail generated without distortion | Correct dimensions |
| **TC-04: Short Video Clip** | 10-30 MB MP4 (1080p) | Transcoded to 720p H.264, frame extracted at 00:00:01 | >60% video size reduction |
| **TC-05: Corrupt File** | Corrupt .bin disguised as .jpg | Lambda handles exception gracefully; DynamoDB status = `FAILED` | Error logged, no crash |
| **TC-06: Direct S3 Access** | Access output S3 URL directly | Returns `403 Access Denied` (Bucket is strictly private) | OAC security verified |
| **TC-07: CloudFront Delivery** | Access CloudFront HTTPS URL | Returns `200 OK` with fast response time | CDN delivery verified |
