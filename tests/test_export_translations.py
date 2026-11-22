"""scripts/export_translations.py: one CSV row per user-facing key in en, hi, mr and kok, for native-speaker review.
It reads the translation files and never writes them. Expected values come from the files as they are (113 keys)."""
import csv
import hashlib
import json
from pathlib import Path

from scripts import export_translations as ex

I18N = Path(__file__).resolve().parent.parent / "web" / "src" / "i18n"
LANGS = ("en", "hi", "mr", "kok")
COLUMNS = ["key", "English", "Hindi", "Marathi", "Konkani", "reviewer", "status", "corrected text", "comment"]


def _dicts():
    return {lang: json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8")) for lang in LANGS}


def _digest():
    return {lang: hashlib.sha256((I18N / f"{lang}.json").read_bytes()).hexdigest() for lang in LANGS}


def _read(path):
    with open(path, encoding="utf-8-sig", newline="") as fh:
        return list(csv.reader(fh))


def test_every_key_once_with_the_four_texts(tmp_path):
    out = tmp_path / "review.csv"
    ex.export(out)
    rows = _read(out)
    assert rows[0] == COLUMNS
    d = _dicts()
    assert [r[0] for r in rows[1:]] == list(d["en"])                 # every key, in the English file's order
    assert len(rows) - 1 == 113
    for key, en, hi, mr, kok, reviewer, status, corrected, comment in rows[1:]:
        assert (en, hi, mr, kok) == (d["en"][key], d["hi"][key], d["mr"][key], d["kok"][key])
        assert (reviewer, corrected, comment) == ("", "", "")


def test_status_carries_the_review_marker(tmp_path):
    out = tmp_path / "review.csv"
    ex.export(out)
    statuses = {r[6] for r in _read(out)[1:]}
    assert statuses == {"needs native-speaker review"}
    for lang in ("hi", "mr", "kok"):
        assert _dicts()[lang]["_meta.review"] == "needs native-speaker review"   # marker kept in the files


def test_translation_files_are_not_changed(tmp_path):
    before = _digest()
    ex.export(tmp_path / "review.csv")
    assert _digest() == before


def test_devanagari_survives_a_spreadsheet_round_trip(tmp_path):
    out = tmp_path / "review.csv"
    ex.export(out)
    assert out.read_bytes().startswith(b"\xef\xbb\xbf")             # UTF-8 with BOM: Excel shows Devanagari
    row = next(r for r in _read(out) if r[0] == "_meta.language")
    assert row[1:5] == ["English", "हिंदी", _dicts()["mr"]["_meta.language"], _dicts()["kok"]["_meta.language"]]
