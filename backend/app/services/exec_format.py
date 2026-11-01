"""Yönetici sayfası ortak biçimleyiciler (Türkçe sayı/yüzde/GB). exec_view ve exec_inventory kullanır."""
from __future__ import annotations

import re
from typing import Optional

_IP = re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")


def _tr_int(value: int) -> str:
    return f"{int(value):,}".replace(",", ".")


def _tr_pct(value: Optional[float]) -> str:
    if value is None:
        return "—"
    text_value = f"{float(value):.0f}"
    return f"%{text_value}"


def _tr_gb(value: float) -> str:
    if value >= 1024:
        text = f"{value / 1024:.1f}".replace(".", ",")
        if text.endswith(",0"):
            text = text[:-2]
        return f"{text} TB"
    text = f"{value:.1f}".replace(".", ",")
    if text.endswith(",0"):
        text = text[:-2]
    return f"{text} GB"


def _safe_name(value: Optional[str]) -> Optional[str]:
    if not value:
        return None
    if value.startswith("ZZ-FAKE") or _IP.search(value):
        return None
    return value
