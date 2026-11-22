"""Tesseract OCR: the fallback OCR engine, plus a no-LLM baseline extractor for evaluation.

The baseline's label parser knows the synthetic document layouts ("Occupant:", "Survey No.:").
It exists to measure what OCR alone achieves; it is not part of the production pipeline.
Requires the Tesseract binary (set TESSERACT_CMD if it is not on PATH).
"""

import io
import os
import re
import shutil
from datetime import date
from pathlib import Path
from typing import Any, Callable, Optional

from app.extraction import ExtractionRequest, OcrResult, Page, ProviderField

DEFAULT_WINDOWS_PATH = Path("C:/Program Files/Tesseract-OCR/tesseract.exe")


def tesseract_cmd() -> Optional[str]:
    env = os.environ.get("TESSERACT_CMD")
    if env and Path(env).exists():
        return env
    if DEFAULT_WINDOWS_PATH.exists():
        return str(DEFAULT_WINDOWS_PATH)
    return shutil.which("tesseract")


def tesseract_available() -> bool:
    return tesseract_cmd() is not None


def _default_image_to_data(image: Any) -> dict:
    import pytesseract
    pytesseract.pytesseract.tesseract_cmd = tesseract_cmd() or "tesseract"
    return pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)


def _default_open_image(data: bytes) -> Any:
    from PIL import Image
    return Image.open(io.BytesIO(data))


def lines_from_data(data: dict) -> list[tuple[str, float]]:
    """Group Tesseract words into lines: (text, mean word confidence 0..1)."""
    lines: dict[tuple, list[tuple[str, float]]] = {}
    for i, text in enumerate(data["text"]):
        conf = float(data["conf"][i])
        if not str(text).strip() or conf < 0:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        lines.setdefault(key, []).append((str(text), conf))
    return [(" ".join(w for w, _ in words), sum(c for _, c in words) / len(words) / 100)
            for words in lines.values()]


class TesseractOcr:
    name = "tesseract"

    def __init__(self, image_to_data: Callable[[Any], dict] = _default_image_to_data,
                 open_image: Callable[[bytes], Any] = _default_open_image):
        self._image_to_data = image_to_data
        self._open_image = open_image

    def read_lines(self, page: Page) -> list[tuple[str, float]]:
        if page.image_bytes is None:
            return [(line, 1.0) for line in (page.text or "").splitlines() if line.strip()]
        return lines_from_data(self._image_to_data(self._open_image(page.image_bytes)))

    def ocr(self, document_id: str, page: Page) -> OcrResult:
        if page.image_bytes is None:
            return OcrResult(text=page.text or "", confidence=1.0)
        data = self._image_to_data(self._open_image(page.image_bytes))
        confs = [float(c) for t, c in zip(data["text"], data["conf"]) if str(t).strip() and float(c) >= 0]
        text = "\n".join(line for line, _ in lines_from_data(data))
        return OcrResult(text=text, confidence=(sum(confs) / len(confs) / 100) if confs else 0.0)


# --- baseline label parser ------------------------------------------------------------

_SEP = r"\s*[:.;]?\s*"
_LABELS = [
    # "Name of holder:" / "Name of the occupant:" (Form I & XIV). On a two-column card Tesseract gives the label line
    # alone: read nothing then (the cross-check is skipped), never the label words "of holder:" as the name.
    ("name", re.compile(rf"^(?:name(?:\s+of\s+(?:the\s+)?(?:holder|occupant|owner))?|occupant){_SEP}(?!of\b)([^\s:.;].*)$",
                        re.I)),
    ("survey_number", re.compile(rf"^survey\s*no\.?{_SEP}(.+)$", re.I)),
    ("area", re.compile(rf"^(?:total\s+)?area{_SEP}([\d.,]+)\s*(.*)$", re.I)),
    ("issue_date", re.compile(rf"^issued{_SEP}(.+)$", re.I)),
    ("expiry_date", re.compile(rf"^valid\s*up\s*to{_SEP}(.+)$", re.I)),
    ("id_number", re.compile(rf"^id\s*no\.?{_SEP}(.+)$", re.I)),
    # disaster relief layouts
    ("house_number", re.compile(rf"^house\s*no\.?{_SEP}(.+)$", re.I)),
    ("house_type", re.compile(rf"^house\s*type{_SEP}(.+)$", re.I)),
    ("area_type", re.compile(rf"^area\s*type{_SEP}(.+)$", re.I)),
    ("notified_area", re.compile(rf"^notified\s*area{_SEP}(.+)$", re.I)),
    ("village", re.compile(rf"^village{_SEP}(.+)$", re.I)),
    ("damage_percent", re.compile(rf"^damage{_SEP}([\d.]+)\s*%?", re.I)),
    ("assessment_date", re.compile(rf"^assessed{_SEP}(.+)$", re.I)),
]


def _iso_date(text: str) -> Optional[str]:
    match = re.fullmatch(r"(\d{2})/(\d{2})/(\d{4})", text.strip())
    if not match:
        return None
    try:
        return date(int(match.group(3)), int(match.group(2)), int(match.group(1))).isoformat()
    except ValueError:
        return None


def _parse_line(label: str, match: re.Match, conf: float) -> list[ProviderField]:
    if label == "area":
        try:
            area = float(match.group(1).replace(",", ""))
        except ValueError:
            return []
        out = [ProviderField(name="area", value=area, confidence=conf)]
        if match.group(2).strip():
            out.append(ProviderField(name="area_unit", value=match.group(2).strip(), confidence=conf))
        return out
    value = match.group(1).strip()
    if label in ("issue_date", "expiry_date", "assessment_date"):
        value = _iso_date(value)
        if value is None:
            return []   # unreadable date: omit rather than guess
    return [ProviderField(name=label, value=value, confidence=conf)]


def parse_labelled_lines(lines: list[tuple[str, float]], fields: list[str]) -> list[ProviderField]:
    found: list[ProviderField] = []
    for text, conf in lines:
        for label, pattern in _LABELS:
            match = pattern.match(text.strip())
            if match:
                found += [f for f in _parse_line(label, match, conf) if f.name in fields]
                break
    return found


class TesseractBaselineProvider:
    """Tesseract alone, no LLM: OCR each page and parse labelled lines."""
    name = "tesseract_only"

    def __init__(self, ocr: Optional[TesseractOcr] = None):
        self.ocr = ocr or TesseractOcr()

    def extract(self, request: ExtractionRequest) -> list[ProviderField]:
        out: list[ProviderField] = []
        for page in request.pages:
            fields = parse_labelled_lines(self.ocr.read_lines(page), request.fields)
            out += [f.model_copy(update={"page": page.number}) for f in fields]
        return out
