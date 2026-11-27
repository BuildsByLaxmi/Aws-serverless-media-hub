"""Image quality metrics using Pillow only (no numpy). PSNR = how close the optimized image is to the original."""
import math

from PIL import Image, ImageChops


def _rgb(img: Image.Image) -> Image.Image:
    if img.mode in ("RGBA", "LA") or "transparency" in img.info:
        base = Image.new("RGB", img.size, (255, 255, 255))     # same white background for both images
        base.paste(img.convert("RGBA"), mask=img.convert("RGBA").split()[-1])
        return base
    return img.convert("RGB")


def psnr(a: Image.Image, b: Image.Image, cap: float = 99.0) -> float:
    """PSNR in dB over RGB. Identical images return `cap`. Sizes must match."""
    if a.size != b.size:
        raise ValueError("images must have the same size")
    a, b = _rgb(a), _rgb(b)
    hist = ImageChops.difference(a, b).histogram()               # 3 x 256 bins
    n = a.width * a.height * 3
    mse = sum(count * (i % 256) ** 2 for i, count in enumerate(hist)) / n
    if mse == 0:
        return cap
    return round(min(cap, 10 * math.log10(255 ** 2 / mse)), 2)


def psnr_label(db):
    if db is None:
        return None
    if db >= 40: return "excellent (differences are practically invisible)"
    if db >= 35: return "very good"
    if db >= 30: return "good (small differences on close inspection)"
    if db >= 25: return "fair (visible differences)"
    return "low (clearly visible quality loss)"
