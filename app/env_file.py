"""Minimal .env loader (standard library only). Real environment variables always win."""

import os
from pathlib import Path


def load_env_file(path: Path) -> list[str]:
    """Set KEY=VALUE lines from `path` that are not already set. Returns the names loaded."""
    if not path.is_file():
        return []
    loaded: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
