"""Rapor alıntısı: baş + hata desenleri (bağlamlı) + son satırlar, boyut sınırlı."""
from __future__ import annotations

import hashlib
import re
from typing import Any, Dict, List, Optional, Tuple

_NUM = re.compile(r"\d+")
_HEX = re.compile(r"\b[0-9a-fA-F]{8,}\b")
_QUOTED = re.compile(r"'[^']*'|\"[^\"]*\"")
_PATH = re.compile(r"(/[\w.-]+){2,}")


def build_excerpt(lines: List[str], cfg: Dict[str, Any]) -> Tuple[str, bool]:
    head = int(cfg.get("head_lines") or 50)
    tail = int(cfg.get("tail_lines") or 200)
    ctx = int(cfg.get("context_lines") or 5)
    max_bytes = int(cfg.get("max_kb") or 64) * 1024
    pats = [p for p in cfg.get("patterns") or [] if p]
    rx = re.compile("|".join(re.escape(p) for p in pats), re.IGNORECASE) if pats else None
    n = len(lines)
    keep = set(range(min(head, n))) | set(range(max(0, n - tail), n))
    if rx:
        for i, ln in enumerate(lines):
            if rx.search(ln):
                keep.update(range(max(0, i - ctx), min(n, i + ctx + 1)))
    out: List[str] = []
    prev = -1
    truncated = len(keep) < n
    for i in sorted(keep):
        if prev >= 0 and i != prev + 1:
            out.append(f"… ({i - prev - 1} satır atlandı) …")
        out.append(lines[i])
        prev = i
    text = "\n".join(out)
    raw = text.encode("utf-8")
    if len(raw) > max_bytes:
        half = max_bytes // 2
        text = raw[:half].decode("utf-8", "ignore") + "\n… (boyut sınırı) …\n" + raw[-half:].decode("utf-8", "ignore")
        truncated = True
    return text, truncated


def error_signature(lines: List[str], patterns: List[str]) -> Optional[str]:
    """İlk anlamlı hata satırından normalleştirilmiş imza (sayılar/yollar/tırnaklar silinir)."""
    priority = [re.compile(p, re.IGNORECASE) for p in (r"ORA-\d{5}", r"Exception|Error:", r"\bERROR\b", r"\bFATAL\b")]
    generic = re.compile("|".join(re.escape(p) for p in patterns), re.IGNORECASE) if patterns else None
    cand = None
    for rx in priority:
        cand = next((ln for ln in lines if rx.search(ln)), None)
        if cand:
            break
    if cand is None and generic:
        cand = next((ln for ln in lines if generic.search(ln)), None)
    if not cand:
        return None
    m = re.search(r"ORA-\d{5}[^\n]{0,80}", cand)
    s = m.group(0) if m else cand
    s = _QUOTED.sub("'…'", s)
    s = _PATH.sub("/…", s)
    s = _HEX.sub("#", s)
    s = re.sub(r"(?<!ORA-)\b\d+\b", "N", s)
    s = re.sub(r"\s+", " ", s).strip()[:200]
    return s or None


def signature_hash(sig: Optional[str]) -> Optional[str]:
    return hashlib.sha1(sig.encode()).hexdigest()[:16] if sig else None
