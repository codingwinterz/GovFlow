"""Render each messy synthetic document as clean, degraded and hard images (deterministic). ALL SYNTHETIC.

Variants:
  clean     black computer-font text on white (PNG)
  degraded  slight tilt, blur, faded ink and speckle noise (PNG)
  hard      a phone photo of a stamped form (JPEG): one field filled in by hand (handwriting-style font, blue ink),
            a red rubber stamp over part of the text, the page photographed at an angle (perspective), a shadow
            across it, and JPEG compression artefacts. A footer says it is a synthetic test document.

Source text: documents/<doc_type>.print.txt if present (what is printed on the paper),
otherwise documents/<doc_type>.txt. Truth labels stay in messy_labels.json, untouched.
Both schemes: data/synthetic/land_acquisition and data/synthetic/disaster_relief.

Run: python -m scripts.render_images
"""

import io
import json
import random
from pathlib import Path
from typing import Literal, Optional

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

DATA = Path(__file__).resolve().parent.parent / "data" / "synthetic"
SET_DIR = DATA / "land_acquisition"
SETS = {"land_acquisition": DATA / "land_acquisition", "disaster_relief": DATA / "disaster_relief"}
Variant = Literal["clean", "degraded", "hard"]
SUFFIX = {"clean": "png", "degraded": "png", "hard": "jpg"}
WIDTH, MARGIN, LINE_HEIGHT, FONT_SIZE = 1200, 60, 56, 34
FONT_CANDIDATES = ["C:/Windows/Fonts/arial.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"]
HAND_FONT_CANDIDATES = ["C:/Windows/Fonts/Inkfree.ttf", "C:/Windows/Fonts/segoepr.ttf", "C:/Windows/Fonts/LHANDW.TTF",
                        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Oblique.ttf"]
FOOTER = "SYNTHETIC TEST DOCUMENT - NOT A REAL RECORD"

# The field filled in by hand on the hard variant, by the label printed before it.
HANDWRITTEN = {"identity_proof": "name", "residence_proof": "name", "ownership_record": "area",
               "survey_sheet": "total area", "damage_assessment": "damage"}

# Degradation settings (one fixed seed, so images are reproducible)
ROTATE_DEGREES, BLUR_RADIUS, CONTRAST, SPECKLES, SEED = 1.8, 1.3, 0.45, 6000, 1234
PAPER, INK, BLUE_INK, TABLE = (244, 239, 226), (38, 36, 42), (28, 48, 140), (74, 64, 56)
JPEG_QUALITY = 38


def _first_font(candidates: list[str], size: int) -> ImageFont.ImageFont:
    for path in candidates:
        if Path(path).exists():
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _font() -> ImageFont.ImageFont:
    return _first_font(FONT_CANDIDATES, FONT_SIZE)


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


# --- hard: handwritten field, stamp, phone photo -----------------------------------------------------------------

def _form(text: str, handwritten: Optional[str]) -> Image.Image:
    """The paper: printed lines, one value written by hand in blue, and the synthetic footer."""
    lines = text.rstrip("\n").split("\n")
    height = 2 * MARGIN + LINE_HEIGHT * (len(lines) + 1)
    img = Image.new("RGB", (WIDTH, height), PAPER)
    draw = ImageDraw.Draw(img)
    font, hand = _font(), _first_font(HAND_FONT_CANDIDATES, FONT_SIZE + 8)
    for i, line in enumerate(lines):
        y = MARGIN + i * LINE_HEIGHT
        label, sep, value = line.partition(":")
        if handwritten and sep and label.strip().lower() == handwritten:
            printed = f"{label}{sep} "
            draw.text((MARGIN, y), printed, fill=INK, font=font)
            draw.text((MARGIN + draw.textlength(printed, font=font) + 6, y - 6), value.strip(), fill=BLUE_INK, font=hand)
        else:
            draw.text((MARGIN, y), line, fill=INK, font=font)
    small = _first_font(FONT_CANDIDATES, 20)
    draw.text((MARGIN, height - MARGIN + 6), FOOTER, fill=(120, 116, 108), font=small)
    return img


def _stamp(img: Image.Image) -> Image.Image:
    """A red rubber stamp, partly over the printed values, slightly rotated and see-through."""
    w, h = img.size
    size = 300
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    red = (185, 32, 40, 150)
    draw.ellipse((10, 10, size - 10, size - 10), outline=red, width=7)
    draw.ellipse((34, 34, size - 34, size - 34), outline=red, width=3)
    font = _first_font(FONT_CANDIDATES, 30)
    for text, y in (("REVENUE OFFICE", 100), ("SYNTHETIC", 140), ("VERIFIED", 180)):
        draw.text(((size - draw.textlength(text, font=font)) / 2, y), text, fill=red, font=font)
    layer = layer.rotate(-17, resample=Image.Resampling.BICUBIC, expand=False)
    out = img.convert("RGBA")
    out.alpha_composite(layer, (int(w * 0.17), max(0, int(h * 0.52) - size // 2)))   # over the values
    return out.convert("RGB")


def _solve(a: list[list[float]], b: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting (8 x 8 here; no numpy needed)."""
    n = len(b)
    m = [row[:] + [b[i]] for i, row in enumerate(a)]
    for col in range(n):
        pivot = max(range(col, n), key=lambda r: abs(m[r][col]))
        m[col], m[pivot] = m[pivot], m[col]
        for r in range(col + 1, n):
            factor = m[r][col] / m[col][col]
            for c in range(col, n + 1):
                m[r][c] -= factor * m[col][c]
    x = [0.0] * n
    for r in range(n - 1, -1, -1):
        x[r] = (m[r][n] - sum(m[r][c] * x[c] for c in range(r + 1, n))) / m[r][r]
    return x


def _perspective_coeffs(output: list[tuple[float, float]], source: list[tuple[float, float]]) -> list[float]:
    """PIL PERSPECTIVE data mapping each output point back to its source point."""
    rows, rhs = [], []
    for (x, y), (u, v) in zip(output, source):
        rows.append([x, y, 1, 0, 0, 0, -u * x, -u * y])
        rhs.append(u)
        rows.append([0, 0, 0, x, y, 1, -v * x, -v * y])
        rhs.append(v)
    return _solve(rows, rhs)


def _photograph(img: Image.Image) -> Image.Image:
    """The page on a table, photographed at an angle, with a shadow across it and phone-camera noise."""
    w, h = img.size
    pad = 90
    canvas = Image.new("RGB", (w + 2 * pad, h + 2 * pad), TABLE)
    canvas.paste(img, (pad, pad))
    cw, ch = canvas.size
    page = [(pad, pad), (pad + w, pad), (pad + w, pad + h), (pad, pad + h)]            # page corners on the canvas
    seen = [(pad + 0.07 * w, pad + 0.05 * h), (pad + 0.95 * w, pad - 0.02 * h),      # where the camera sees them
            (pad + 1.02 * w, pad + 0.98 * h), (pad - 0.03 * w, pad + 1.04 * h)]
    out = canvas.transform((cw, ch), Image.Transform.PERSPECTIVE, _perspective_coeffs(seen, page),
                           resample=Image.Resampling.BICUBIC, fillcolor=TABLE)
    shade = Image.new("L", (cw, ch))
    shade.putdata([int(255 * (1.0 - 0.45 * min(1.0, (x / cw * 0.6 + y / ch * 0.4) ** 1.4)))
                   for y in range(ch) for x in range(cw)])
    out = Image.composite(out, Image.new("RGB", (cw, ch), (0, 0, 0)), shade)
    out = out.filter(ImageFilter.GaussianBlur(0.9))
    rng = random.Random(SEED + 1)
    pixels = out.load()
    for _ in range(25000):
        x, y = rng.randrange(cw), rng.randrange(ch)
        r, g, b = pixels[x, y]
        d = rng.randint(-28, 28)
        pixels[x, y] = (max(0, min(255, r + d)), max(0, min(255, g + d)), max(0, min(255, b + d)))
    out = out.resize((cw * 4 // 5, ch * 4 // 5), Image.Resampling.BILINEAR)
    buffer = io.BytesIO()
    out.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return Image.open(io.BytesIO(buffer.getvalue())).convert("RGB")


def render_document(text: str, variant: Variant, handwritten: Optional[str] = None) -> Image.Image:
    if variant == "hard":
        return _photograph(_stamp(_form(text, handwritten)))
    clean = _clean(text)
    return clean if variant == "clean" else _degrade(clean)


def _source_text(folder: Path, doc_type: str) -> str:
    printed = folder / "documents" / f"{doc_type}.print.txt"
    path = printed if printed.exists() else folder / "documents" / f"{doc_type}.txt"
    return path.read_text(encoding="utf-8")


def main() -> None:
    count = 0
    for set_dir in SETS.values():
        labels = json.loads((set_dir / "messy_labels.json").read_text(encoding="utf-8"))
        for item in labels["documents"]:
            folder = set_dir / item["case"]
            (folder / "images").mkdir(exist_ok=True)
            text = _source_text(folder, item["doc_type"])
            for variant in ("clean", "degraded", "hard"):
                image = render_document(text, variant, HANDWRITTEN.get(item["doc_type"]))
                path = folder / "images" / f"{item['doc_type']}_{variant}.{SUFFIX[variant]}"
                if variant == "hard":
                    image.save(path, format="JPEG", quality=JPEG_QUALITY)
                else:
                    image.save(path, optimize=True)
                count += 1
    print(f"Wrote {count} images")


if __name__ == "__main__":
    main()
