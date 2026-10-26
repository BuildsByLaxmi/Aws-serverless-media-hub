# Backend Module: Media Processing & Lambda
**Lead Owner**: Person 2 (Processing Lead)  
**Assisting / Integration**: Person 1 & Person 3

---

## 1. Responsibilities
- Write the Python Lambda handler (`lambda_function.py`).
- Use **Pillow** to resize images, compress, and convert to WebP format (`image_processor.py`).
- Generate thumbnails (e.g., 200x200 JPEG preserving aspect ratio).
- Add **FFmpeg**-based video transcoding to 720p H.264 and extract a video frame thumbnail (`video_processor.py`).
- Compute file size reduction percentages and store results in DynamoDB (`MediaMetadata`).
- Handle errors gracefully (corrupt media, unsupported formats, timeouts).

---

## 2. Interface Contract (Read from Environment Variables)
Your code should retrieve configuration from environment variables configured by Person 1:
```python
import os

OUTPUT_BUCKET = os.environ.get("OUTPUT_BUCKET")
DYNAMODB_TABLE = os.environ.get("DYNAMODB_TABLE", "MediaMetadata")
CLOUDFRONT_DOMAIN = os.environ.get("CLOUDFRONT_DOMAIN")
IMAGE_MAX_WIDTH = int(os.environ.get("IMAGE_MAX_WIDTH", "1920"))
IMAGE_QUALITY = int(os.environ.get("IMAGE_QUALITY", "82"))
```

---

## 3. Storage Hierarchy
When saving to the output bucket:
- **Optimized Image**: `processed/{mediaId}.webp`
- **Optimized Video**: `processed/{mediaId}.mp4`
- **Image Thumbnail**: `thumbnails/{mediaId}.jpg` (200x200)
- **Video Thumbnail**: `thumbnails/{mediaId}.jpg` (320x180)

---

## 4. Local Testing
Before deploying to AWS Lambda, test your functions locally using:
```bash
pip install -r requirements.txt
python -m unittest discover tests/
```
