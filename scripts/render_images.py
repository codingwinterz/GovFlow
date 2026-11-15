"""Render each messy synthetic document to a clean and a degraded PNG (deterministic).

Source text: documents/<doc_type>.print.txt if present (what is printed on the paper),
otherwise documents/<doc_type>.txt. Truth labels stay in messy_labels.json, untouched.

Run: python -m scripts.render_images
"""

import json
import random
from pathlib import Path
from typing import Literal

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

SET_DIR = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "land_acquisition"
Variant = Literal["clean", "degraded"]
WIDTH, MARGIN, LINE_HEIGHT, FONT_SIZE = 1200, 60, 56, 34
FONT_CANDIDATES = ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]

# Degradation settings (one fixed seed, so images are reproducible)
ROTATE_DEGREES, BLUR_RADIUS, CONTRAST, SPECKLES, SEED = 1.8, 1.3, 0.45, 6000, 1234


def _font() -> ImageFont.ImageFont:
    for path in FONT_CANDIDATES:
        if Path(path).exists():
            return ImageFont.truetype(path, FONT_SIZE)
    return ImageFont.load_default(size=FONT_SIZE)


def _clean(text: str) -> Image.Image:
    lines = text.rstrip("\n").split("\n")
    img = Image.new("L", (WIDTH, 2 * MARGIN + LINE_HEIGHT * len(lines)), 255)
    draw = ImageDraw.Draw(img)
    font = _font()
    for i, line in enumerate(lines):
        draw.text((MARGIN, MARGIN + i * LINE_HEIGHT), line, fill=0, font=font)
    return img


def _degrade(img: Image.Image) -> Image.Image:
    rng = random.Random(SEED)
    out = img.rotate(ROTATE_DEGREES, resample=Image.Resampling.BICUBIC, expand=False, fillcolor=255)
    out = out.filter(ImageFilter.GaussianBlur(BLUR_RADIUS))
    out = ImageEnhance.Contrast(out).enhance(CONTRAST)
    pixels = out.load()
    w, h = out.size
    for _ in range(SPECKLES):
        pixels[rng.randrange(w), rng.randrange(h)] = rng.randint(90, 170)
    return out


def render_document(text: str, variant: Variant) -> Image.Image:
    clean = _clean(text)
    return clean if variant == "clean" else _degrade(clean)


def _source_text(folder: Path, doc_type: str) -> str:
    printed = folder / "documents" / f"{doc_type}.print.txt"
    path = printed if printed.exists() else folder / "documents" / f"{doc_type}.txt"
    return path.read_text(encoding="utf-8")


def main() -> None:
    labels = json.loads((SET_DIR / "messy_labels.json").read_text(encoding="utf-8"))
    count = 0
    for item in labels["documents"]:
        folder = SET_DIR / item["case"]
        (folder / "images").mkdir(exist_ok=True)
        for variant in ("clean", "degraded"):
            render_document(_source_text(folder, item["doc_type"]), variant).save(
                folder / "images" / f"{item['doc_type']}_{variant}.png", optimize=True)
            count += 1
    print(f"Wrote {count} images")


if __name__ == "__main__":
    main()
