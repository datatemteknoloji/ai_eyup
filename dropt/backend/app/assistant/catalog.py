from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any


_CATALOG_PATH = Path(__file__).resolve().parent / "capabilities.json"


@lru_cache(maxsize=1)
def load_catalog() -> dict[str, Any]:
    raw = _CATALOG_PATH.read_text(encoding="utf-8")
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("capabilities"), list):
        raise RuntimeError("capabilities.json geçersiz")
    return data


def reload_catalog() -> dict[str, Any]:
    load_catalog.cache_clear()
    return load_catalog()


def list_capabilities() -> list[dict[str, Any]]:
    return list(load_catalog().get("capabilities") or [])


def get_capability(cap_id: str) -> dict[str, Any] | None:
    for c in list_capabilities():
        if c.get("id") == cap_id:
            return c
    return None


def catalog_for_prompt() -> str:
    lines = []
    for c in list_capabilities():
        lines.append(
            f"- id={c.get('id')} | {c.get('title_tr')} | route={c.get('route')} | "
            f"keywords={', '.join(c.get('keywords') or [])}"
        )
    return "\n".join(lines)
