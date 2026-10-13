"""Araç argümanı temizliği — model yer tutucuları (*, %, 0) filtreye dönüşmesin."""
from __future__ import annotations

from typing import Any, Dict, Optional


def clean_str_filter(v: Any) -> Optional[str]:
    """Modelin 'tümünü seç' yer tutucuları (*, %, boş) → filtre YOK."""
    if v is None:
        return None
    s = str(v).strip()
    if not s or s in ("*", "%", "?", ".*", "any", "ALL", "all"):
        return None
    return s


def _int(v: Any) -> Optional[int]:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def sanitize_search_args(args: Dict[str, Any]) -> Dict[str, Any]:
    """object_type='*' exact-match tuzağı ve user='*' username sapması engellenir."""
    out = dict(args or {})
    for k in ("object_name", "object_type", "agent", "folder", "user", "system"):
        if k in out:
            cleaned = clean_str_filter(out.get(k))
            if cleaned is None:
                out.pop(k, None)
            else:
                out[k] = cleaned
    sc = _int(out.get("status_code"))
    if sc is None or sc == 0:
        out.pop("status_code", None)
    cl = _int(out.get("client"))
    if cl is None or cl == 0:
        out.pop("client", None)
    return out
