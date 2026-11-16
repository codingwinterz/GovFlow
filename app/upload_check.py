"""Uploaded bytes must be what the file name says: a .png must be a PNG, a .txt must be text, and so on."""

from typing import Optional

SIGNATURES = {
    ".png": b"\x89PNG\r\n\x1a\n",
    ".jpg": b"\xff\xd8\xff",
    ".jpeg": b"\xff\xd8\xff",
    ".pdf": b"%PDF-",
}


def content_problem(suffix: str, content: bytes) -> Optional[str]:
    """Why `content` is not a valid file of type `suffix`, or None when it is."""
    if suffix == ".txt":
        if b"\x00" in content:
            return "The .txt file contains binary data, not text."
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return "The .txt file is not UTF-8 text."
        return None
    signature = SIGNATURES.get(suffix)
    if signature is None:
        return f"Unsupported file type {suffix}"
    if not content.startswith(signature):
        return f"The file content is not a {suffix} file (its first bytes do not match)."
    return None
