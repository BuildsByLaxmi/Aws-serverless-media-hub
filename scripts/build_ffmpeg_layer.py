"""
Builds an FFmpeg Lambda layer ZIP (needed only for VIDEO processing — Step 08).
Works on Windows/macOS/Linux/Colab, no AWS CLI needed.

    python scripts/build_ffmpeg_layer.py

Creates dist/ffmpeg-layer.zip containing bin/ffmpeg -> on Lambda it appears at /opt/bin/ffmpeg.

Then: Lambda console -> Layers -> Create layer -> upload the ZIP
      (if it is above 50 MB, upload it to S3 first and give the S3 URL),
      compatible runtime Python 3.12, architecture x86_64
      -> open the processor function -> Layers -> Add a layer -> Custom layers.
"""
import io
import os
import tarfile
import urllib.request
import zipfile

URL = "https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-amd64-static.tar.xz"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "dist", "ffmpeg-layer.zip")

if __name__ == "__main__":
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    print("Downloading static FFmpeg for Linux x86_64 (~40 MB)...")
    data = urllib.request.urlopen(URL).read()
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:xz") as tar:
        member = next(m for m in tar.getmembers() if m.name.endswith("/ffmpeg") and m.isfile())
        binary = tar.extractfile(member).read()
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        info = zipfile.ZipInfo("bin/ffmpeg")
        info.external_attr = 0o755 << 16          # keep it executable on Lambda
        info.compress_type = zipfile.ZIP_DEFLATED
        z.writestr(info, binary)
    print(f"Built {OUT} ({os.path.getsize(OUT)/1048576:.1f} MB)")
    print("Upload it as a Lambda layer (see the docstring at the top of this file).")
