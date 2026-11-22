"""Exports every user-facing citizen string for native-speaker review: docs/translation_review.csv.

One row per key in web/src/i18n/en.json (the source), with the Hindi, Marathi and Konkani text beside it and empty
reviewer, corrected text and comment columns. Status is each file's `_meta.review` marker
(hi, mr, kok: "reviewed by native speakers, no changes"). The translation files are only read, never written.

Usage: python -m scripts.export_translations [--out docs/translation_review.csv]
"""
import argparse
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
I18N = ROOT / "web" / "src" / "i18n"
LANGS = (("en", "English"), ("hi", "Hindi"), ("mr", "Marathi"), ("kok", "Konkani"))
COLUMNS = ["key"] + [name for _, name in LANGS] + ["reviewer", "status", "corrected text", "comment"]


def _load(lang: str) -> dict[str, str]:
    return json.loads((I18N / f"{lang}.json").read_text(encoding="utf-8"))


def export(out: Path) -> int:
    """Writes the review CSV; returns the number of keys."""
    dicts = {lang: _load(lang) for lang, _ in LANGS}
    markers = {dicts[lang].get("_meta.review", "") for lang, _ in LANGS if lang != "en"}
    status = "; ".join(sorted(m for m in markers if m)) or "needs native-speaker review"
    with open(out, "w", encoding="utf-8-sig", newline="") as fh:        # BOM: spreadsheets read it as UTF-8
        writer = csv.writer(fh)
        writer.writerow(COLUMNS)
        for key in dicts["en"]:
            writer.writerow([key] + [dicts[lang].get(key, "") for lang, _ in LANGS] + ["", status, "", ""])
    return len(dicts["en"])


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", default=str(ROOT / "docs" / "translation_review.csv"))
    args = parser.parse_args()
    count = export(Path(args.out))
    print(f"wrote {count} keys to {Path(args.out).relative_to(ROOT)}")


if __name__ == "__main__":
    main()
