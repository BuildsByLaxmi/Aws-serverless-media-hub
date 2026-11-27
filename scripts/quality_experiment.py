"""Quality vs compression experiment: encode one image at several WebP qualities and print size and PSNR.
Run by hand, no Supabase needed:   python scripts/quality_experiment.py tests/test_images/landscape.jpg
Results are measurements for THAT image only; do not generalize them to all images."""
import io, os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))
from PIL import Image
from image_processor import load_image, resize_image
from quality_metrics import psnr, psnr_label

QUALITIES = [95, 82, 80, 60]


def run(path):
    src = os.path.getsize(path)
    img = resize_image(load_image(path))
    rows = []
    for q in QUALITIES:
        buf = io.BytesIO(); img.save(buf, "WEBP", quality=q, method=4)
        buf.seek(0); dec = Image.open(buf); dec.load()
        rows.append((q, buf.getbuffer().nbytes, psnr(img, dec)))
    return src, rows


if __name__ == "__main__":
    path = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), "..", "tests", "test_images", "landscape.jpg")
    src, rows = run(path)
    print(f"{path}  (original {src/1024:.0f} KB)")
    print(f"{'quality':>8} {'size KB':>9} {'saved %':>8} {'PSNR dB':>8}  verdict")
    for q, size, db in rows:
        print(f"{q:>8} {size/1024:>9.1f} {(src-size)/src*100:>8.1f} {db:>8.2f}  {psnr_label(db)}")
