"""Lightweight .env loader used when start.sh isn't sourcing environment variables."""

from __future__ import annotations

import os
from pathlib import Path


def load_dotenv(path: Path | None = None) -> None:
    """
    Populate os.environ with variables from a .env file if it exists.

    Existing environment variables are left untouched to allow overrides.
    """
    env_path = path or Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return

    try:
        content = env_path.read_text(encoding="utf-8")
    except OSError:
        return

    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value

