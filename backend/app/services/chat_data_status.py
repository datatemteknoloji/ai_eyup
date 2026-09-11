"""Canlı veri durumu — 'yok' / 'alınamadı' / 'sorgulanmadı' ayrımı.

Tool ve collect sonuçlarına tek bir status eklenir. LLM bunu 'veri yok'
ile karıştırmamalı. Mevcut tool handler'ları değiştirilmez; sonuç
serileştirilirken çıkarılır.
"""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

SUCCESS = "SUCCESS"
SUCCESS_EMPTY = "SUCCESS_EMPTY"
FAILED = "FAILED"
NOT_QUERIED = "NOT_QUERIED"
STALE = "STALE"
TIMEOUT = "TIMEOUT"
PARTIAL = "PARTIAL"

_EMPTY_KEYS = (
    "vms", "hosts", "items", "results", "data", "rows", "pods",
        "events", "datastores", "clusters", "servers", "list",
        "racks", "nodes", "cells",
)


def infer_tool_status(payload: Any, *, forced: Optional[str] = None) -> str:
    if forced:
        return forced
    if payload is None:
        return SUCCESS_EMPTY
    if isinstance(payload, str):
        raw = payload.strip()
        if not raw:
            return SUCCESS_EMPTY
        low = raw.lower()
        if "timeout" in low or "zaman aşımı" in low or "zaman asimi" in low:
            return TIMEOUT
        try:
            payload = json.loads(raw)
        except Exception:
            return SUCCESS
    if not isinstance(payload, dict):
        return SUCCESS
    if payload.get("data_status"):
        return str(payload["data_status"])
    err = str(payload.get("error") or "")
    err_l = err.lower()
    if "timeout" in err_l or "zaman aşımı" in err_l:
        return TIMEOUT
    if payload.get("ok") is False or err:
        return FAILED
    if payload.get("stale") is True:
        return STALE
    if payload.get("partial") is True:
        return PARTIAL
    for key in _EMPTY_KEYS:
        val = payload.get(key)
        if isinstance(val, list) and len(val) == 0:
            return SUCCESS_EMPTY
    return SUCCESS


def annotate_payload(payload: Any, *, forced: Optional[str] = None) -> Any:
    """Dict ise data_status ekler; değilse olduğu gibi bırakır (status ayrıca)."""
    status = infer_tool_status(payload, forced=forced)
    if isinstance(payload, dict):
        if payload.get("data_status"):
            return payload
        out = dict(payload)
        out["data_status"] = status
        return out
    return payload


def format_collect_line(source: str, status: str, detail: str = "") -> str:
    extra = f" {detail}".rstrip()
    return f"{source}: STATUS={status}{extra}"


def status_prompt_rule() -> str:
    return (
        "7. TOPLAMA DURUMU / tool JSON içindeki data_status alanını oku: "
        "SUCCESS=alındı, SUCCESS_EMPTY=sorgu başarılı ama kayıt yok, "
        "FAILED=hata, TIMEOUT=zaman aşımı, NOT_QUERIED=bu turda hiç sorulmadı, "
        "STALE=eski cache. NOT_QUERIED veya TIMEOUT için 'ortamda veri yok' DEME; "
        "kaynağın alınamadığını veya sorulmadığını söyle."
    )
