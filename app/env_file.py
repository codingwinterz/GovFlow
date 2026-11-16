"""Minimal .env loader (standard library only). Real environment variables always win."""

import os
from pathlib import Path
from typing import Optional


def read_env_file(path: Path) -> dict[str, str]:
    """KEY=VALUE lines of `path` (quotes stripped). Reads only: the process environment is not changed."""
    if not path.is_file():
        return {}
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = (part.strip() for part in line.split("=", 1))
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if key:
            out[key] = value
    return out


def env_value(name: str, path: Optional[Path] = None) -> Optional[str]:
    """A setting from the real environment, else from the .env file at `path`; None when blank or absent."""
    value = os.environ.get(name) or (read_env_file(path).get(name) if path else None)
    return value.strip() or None if value else None


def load_env_file(path: Path) -> list[str]:
    """Set KEY=VALUE lines from `path` that are not already set. Returns the names loaded."""
    loaded: list[str] = []
    for key, value in read_env_file(path).items():
        if key not in os.environ:
            os.environ[key] = value
            loaded.append(key)
    return loaded
