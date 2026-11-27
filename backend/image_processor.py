"""
image_processor.py — Owner: Person 2 (Processing lead)

Separate small functions (as per plan) so each can be tested on its own:
    load_image()        -> open + fix phone rotation (EXIF)
    resize_image()      -> shrink keeping aspect ratio (never upscale)
    compress_to_webp()  -> save optimized WebP
    make_thumbnail()    -> exact 200x200 centre-cropped JPG
    process_image()     -> runs all of the above, returns sizes/dimensions
"""
import os

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_DIMENSION = int(os.environ.get("MAX_DIMENSION", "1920"))   # longest side of optimized image
WEBP_QUALITY = int(os.environ.get("WEBP_QUALITY", "82"))
THUMBNAIL_SIZE = (200, 200)


class InvalidMediaError(Exception):
    """Raised when the uploaded file is not a readable image/video."""


def load_image(path: str) -> Image.Image:
    try:
        img = Image.open(path)
        img.load()
    except (UnidentifiedImageError, OSError) as e:
        raise InvalidMediaError(f"Not a valid image file: {os.path.basename(path)}") from e
    img = ImageOps.exif_transpose(img)          # portrait photos from phones stay upright
    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "transparency" in img.info else "RGB")
    return img


def resize_image(img: Image.Image, max_dimension: int = MAX_DIMENSION) -> Image.Image:
    out = img.copy()
    out.thumbnail((max_dimension, max_dimension), Image.LANCZOS)   # keeps aspect ratio
    return out


def compress_to_webp(img: Image.Image, out_path: str, quality: int = WEBP_QUALITY) -> str:
    img.save(out_path, "WEBP", quality=quality, method=4)
    return out_path


def make_thumbnail(img: Image.Image, out_path: str, size=THUMBNAIL_SIZE) -> str:
    thumb = ImageOps.fit(img.convert("RGB"), size, Image.LANCZOS)   # centre crop to exact size
    thumb.save(out_path, "JPEG", quality=85)
    return out_path


def process_image(src_path: str, out_dir: str, media_id: str) -> dict:
    os.makedirs(out_dir, exist_ok=True)
    img = load_image(src_path)
    optimized = resize_image(img)

    optimized_path = compress_to_webp(optimized, os.path.join(out_dir, f"{media_id}.webp"))
    thumbnail_path = make_thumbnail(img, os.path.join(out_dir, f"{media_id}_thumb.jpg"))

    return {
        "mediaType": "image",
        "optimizedPath": optimized_path,
        "thumbnailPath": thumbnail_path,
        "outputExt": ".webp",
        "originalWidth": img.width,
        "originalHeight": img.height,
        "optimizedWidth": optimized.width,
        "optimizedHeight": optimized.height,
    }
