"""Guards: tests cannot reach the network; no keys or real-model output are committed."""

import re
import subprocess
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
SECRET_PATTERNS = [
    re.compile(r"AIza[0-9A-Za-z_\-]{35}"),          # Google API key
    re.compile(r"sk-ant-[0-9A-Za-z_\-]{20,}"),      # Anthropic API key
    re.compile(r"\bAQ\.[0-9A-Za-z_\-]{30,}"),        # Google API key (newer AQ. format)
    re.compile(r"GEMINI_API_KEY\s*=\s*['\"]?[A-Za-z0-9_.\-]{20,}"),
]


def test_dotenv_is_never_committable():
    assert ".env" in (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert not [p for p in _tracked_files() if p.name == ".env"]


def _tracked_files() -> list[Path]:
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                         cwd=ROOT, capture_output=True, text=True, check=True).stdout
    return [ROOT / line for line in out.splitlines() if line]


def test_network_is_blocked_during_tests():
    with pytest.raises(OSError, match="network disabled"):
        urllib.request.urlopen("https://example.com", timeout=2)


def test_no_api_keys_in_committable_files():
    hits = []
    for path in _tracked_files():
        if path.suffix in {".png", ".jpg", ".pdf", ".pyc"} or not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        hits += [f"{path.relative_to(ROOT)}: {p.pattern}" for p in SECRET_PATTERNS if p.search(text)]
    assert hits == []


def test_real_eval_results_are_not_committable():
    assert not [p for p in _tracked_files() if "eval_results" in p.parts]
    assert "eval_results/" in (ROOT / ".gitignore").read_text(encoding="utf-8")
