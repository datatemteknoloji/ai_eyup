"""Uygulama sürümü — kök VERSION dosyası / APP_VERSION env."""
from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path


def _candidates() -> list[Path]:
    here = Path(__file__).resolve()
    # app/core/version.py → /app veya backend/
    app_root = here.parents[2]  # .../app
    backend_root = here.parents[3] if len(here.parents) > 3 else app_root.parent
    return [
        Path("/app/VERSION"),
        app_root.parent / "VERSION",       # /app/VERSION when cwd layout
        backend_root / "VERSION",
        backend_root.parent / "VERSION",   # repo kökü (dev)
        Path.cwd() / "VERSION",
    ]


@lru_cache(maxsize=1)
def get_app_version() -> str:
    env = (os.environ.get("APP_VERSION") or os.environ.get("VERSION") or "").strip()
    if env:
        return env.lstrip("vV")
    for path in _candidates():
        try:
            if path.is_file():
                val = path.read_text(encoding="utf-8").strip()
                if val:
                    return val.lstrip("vV")
        except OSError:
            continue
    return "0.0.0"
