"""
video_processor.py — Owner: Person 2 (Processing lead)

Needs an FFmpeg binary. On Lambda it comes from the FFmpeg layer at /opt/bin/ffmpeg
(see scripts/build_ffmpeg_layer.sh). Locally it uses the ffmpeg on your PATH.

    extract_thumbnail() -> frame at 1s, centre-cropped to 200x200 JPG
    compress_video()    -> H.264 MP4, max 720p, CRF 28, faststart
    process_video()     -> runs both, returns dimensions
"""
import os
import re
import shutil
import subprocess

from image_processor import InvalidMediaError

MAX_VIDEO_HEIGHT = int(os.environ.get("MAX_VIDEO_HEIGHT", "720"))
MAX_VIDEO_SECONDS = int(os.environ.get("MAX_VIDEO_SECONDS", "60"))   # keeps Lambda inside its timeout
VIDEO_CRF = os.environ.get("VIDEO_CRF", "28")


def ffmpeg_path() -> str:
    for p in ("/opt/bin/ffmpeg", shutil.which("ffmpeg") or ""):
        if p and os.path.exists(p):
            return p
    # Check standard Windows paths if not yet in system PATH
    win_candidates = [
        os.path.expandvars(r"%LOCALAPPDATA%\Microsoft\WinGet\Packages\Gyan.FFmpeg_Microsoft.Winget.Source_8wekyb3d8bbwe\ffmpeg-9.1-full_build\bin\ffmpeg.exe"),
        r"C:\ProgramData\chocolatey\bin\ffmpeg.exe",
        r"C:\ffmpeg\bin\ffmpeg.exe",
    ]
    for p in win_candidates:
        if os.path.exists(p):
            return p
    raise RuntimeError("FFmpeg not found. Attach the FFmpeg Lambda layer (/opt/bin/ffmpeg).")


def _run(args):
    r = subprocess.run(args, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if r.returncode != 0:
        raise InvalidMediaError("FFmpeg could not process this video: " + r.stderr.strip()[-300:])
    return r


def probe_dimensions(src_path: str):
    """Reads width/height from ffmpeg's stream info (no ffprobe needed)."""
    r = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", src_path],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    m = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", r.stderr)
    if not m:
        raise InvalidMediaError(f"Not a valid video file: {os.path.basename(src_path)}")
    return int(m.group(1)), int(m.group(2))


def extract_thumbnail(src_path: str, out_path: str, size=(200, 200)) -> str:
    w, h = size
    vf = f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h}"
    _run([ffmpeg_path(), "-y", "-ss", "1", "-i", src_path, "-frames:v", "1", "-vf", vf, out_path])
    if not os.path.exists(out_path):                      # clip shorter than 1 s
        _run([ffmpeg_path(), "-y", "-i", src_path, "-frames:v", "1", "-vf", vf, out_path])
    return out_path


def probe_duration(src_path: str) -> float:
    r = subprocess.run([ffmpeg_path(), "-hide_banner", "-i", src_path],
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", r.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def compress_video(src_path: str, out_path: str, crf=None, max_height=None) -> str:
    crf = str(crf if crf is not None else VIDEO_CRF)
    max_height = max_height or MAX_VIDEO_HEIGHT
    _run([ffmpeg_path(), "-y", "-i", src_path,
          "-t", str(MAX_VIDEO_SECONDS),
          "-vf", f"scale=-2:'min({max_height},ih)'",
          "-c:v", "libx264", "-preset", "veryfast", "-crf", crf,
          "-c:a", "aac", "-b:a", "96k",
          "-movflags", "+faststart", out_path])
    return out_path


def process_video(src_path: str, out_dir: str, media_id: str, policy=None) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    width, height = probe_dimensions(src_path)
    extra, crf, max_h = {}, None, None
    if policy is not None:
        settings = policy.video(width, height, probe_duration(src_path), os.path.getsize(src_path))
        crf, max_h = settings["crf"], settings["max_height"]
        extra["settings"] = settings
    optimized_path = compress_video(src_path, os.path.join(out_dir, f"{media_id}.mp4"), crf, max_h)
    thumbnail_path = extract_thumbnail(src_path, os.path.join(out_dir, f"{media_id}_thumb.jpg"))
    out_w, out_h = probe_dimensions(optimized_path)
    return {
        "mediaType": "video",
        "optimizedPath": optimized_path,
        "thumbnailPath": thumbnail_path,
        "outputExt": ".mp4",
        "originalWidth": width,
        "originalHeight": height,
        "optimizedWidth": out_w,
        "optimizedHeight": out_h,
        **extra,
    }
