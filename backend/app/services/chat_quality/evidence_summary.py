"""Adım 8d — «model özetleyemedi» fallback'i için okunur özet (ham JSON YOK).

``render(evidence)``: araç kanıt metnini (``[Etiket]\\n{json}`` blokları) kullanıcıya okunur biçimde sunar:
  * bilinen şekil (kayıt listesi içeren sonuç) → kısa tablo (ilk 10 satır, «N kayıttan 10'u»),
  * düz sayaç/özet alanları → kısa madde listesi,
  * tanınmayan / bozuk / kesik JSON → «Cevap özetlenemedi; <kaynak türü> verisi alındı (N kayıt).»
  * düz metin (SSH/WinRM komut çıktısı) → olduğu gibi (kırpılmış kod bloğu; JSON değil).
Hiçbir koşulda ham JSON, araç adı veya snake_case alan adı basmaz. Saf fonksiyonlar; DB/ağ yok.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

MAX_ROWS = 10
MAX_BLOCKS = 3
MAX_CELL = 80
MAX_TEXT = 1500

_BLOCK_RE = re.compile(r"(?m)^\[([^\]\n]{2,120})\]\s*\n")

_LABELS = {
    "name": "Ad", "vm": "VM", "vm_name": "VM", "host": "Host", "esxi_host": "Host", "cluster": "Cluster",
    "hypervisor": "Hypervisor", "title": "Başlık", "severity": "Önem", "event_type": "Tür", "source": "Kaynak",
    "created_at": "Zaman", "last_seen": "Son görülme", "power_state": "Güç durumu", "status": "Durum",
    "state": "Durum", "namespace": "Namespace", "project": "Proje", "pod": "Pod", "node": "Node", "ip": "IP",
    "count": "Adet", "occurrence_count": "Tekrar", "description": "Açıklama", "message": "Mesaj", "server": "Sunucu",
    "reason": "Neden", "restarts": "Restart", "role": "Rol", "datastore": "Datastore", "capacity_gb": "Kapasite (GB)",
    "free_gb": "Boş (GB)", "type": "Tür", "kind": "Tür", "resolved": "Çözüldü",
}
_PRIORITY = [
    "name", "vm", "vm_name", "pod", "node", "host", "esxi_host", "server", "title", "namespace", "project",
    "cluster", "hypervisor", "severity", "event_type", "status", "state", "power_state", "reason", "role",
    "restarts", "count", "occurrence_count", "ip", "datastore", "capacity_gb", "free_gb", "created_at", "last_seen",
    "source", "description", "message",
]
_LIST_KEYS = ("events", "vms", "pods", "items", "rows", "hosts", "datastores", "nodes", "projects", "alarms",
              "results", "data", "runs", "executions", "snapshots", "clusters", "servers", "records")
_TOTAL_KEYS = ("total_count_in_window", "total_count", "total", "count")
_SKIP_SCALAR = {"ok", "read_only", "source", "stale", "hint", "note", "error", "hours", "limit", "severity_filter"}
_SNAKE = re.compile(r"[a-z][a-z0-9]*(?:_[a-z0-9]+)+")


def _clean_label(label: str) -> str:
    """Kaynak türü: parantez içi tablo/araç adını ve snake_case adı at; boşsa «araç»."""
    t = re.sub(r"\s*\([^)]*\)", "", label or "").strip()
    if not t or "_" in t:
        return "araç"
    return t


def _cell(v: Any) -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return "evet" if v else "hayır"
    if isinstance(v, (dict, list)):
        return "—"
    s = str(v).replace("\n", " ").replace("|", "/").strip()
    return s if len(s) <= MAX_CELL else s[: MAX_CELL - 1] + "…"


def _human_key(k: str) -> str:
    return _LABELS.get(k) or k.replace("_", " ")


def _find_list(data: Dict[str, Any]) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
    best: Optional[Tuple[str, List[Dict[str, Any]]]] = None
    for k in list(_LIST_KEYS) + [x for x in data if x not in _LIST_KEYS]:
        v = data.get(k)
        if isinstance(v, list) and v and all(isinstance(r, dict) for r in v):
            if best is None or len(v) > len(best[1]):
                best = (k, v)
                if k in _LIST_KEYS:
                    break
    return best


def _table(rows: List[Dict[str, Any]]) -> str:
    first = rows[0]
    shown = rows[:MAX_ROWS]
    cols = [k for k in _PRIORITY if k in first and not isinstance(first.get(k), (dict, list))
            and any(r.get(k) not in (None, "") for r in shown)][:5]
    if not cols:
        cols = [k for k, v in first.items() if not isinstance(v, (dict, list))][:4]
    if not cols:
        return ""
    head = "| " + " | ".join(_human_key(c) for c in cols) + " |"
    sep = "|" + "|".join("---" for _ in cols) + "|"
    body = ["| " + " | ".join(_cell(r.get(c)) for c in cols) + " |" for r in rows[:MAX_ROWS]]
    return "\n".join([head, sep] + body)


def _total(data: Dict[str, Any], n_rows: int) -> int:
    for k in _TOTAL_KEYS:
        v = data.get(k)
        if isinstance(v, int) and not isinstance(v, bool) and v >= n_rows:
            return v
    return n_rows


def _scalars(data: Dict[str, Any]) -> List[str]:
    out = []
    for k, v in data.items():
        if k in _SKIP_SCALAR or isinstance(v, (dict, list)) or v in (None, ""):
            continue
        out.append(f"- {_human_key(k).capitalize()}: {_cell(v)}")
        if len(out) >= 8:
            break
    return out


def _num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _counters(data: Dict[str, Any]) -> List[str]:
    """Sayaç sözlükleri (`by_object: {ad: sayı}` ya da `{ad: {adet: n}}`) → sıralı «ilk N» tablosu (Adım 15)."""
    out: List[str] = []
    for k, v in data.items():
        if k in _SKIP_SCALAR or not isinstance(v, dict) or len(v) < 2:
            continue
        pairs: List[Tuple[str, float]] = []
        if all(_num(x) for x in v.values()):
            pairs = [(str(a), float(b)) for a, b in v.items()]
        else:
            # {ad: {count|total|n|runs|errors: sayı}} → ilk sayısal alan
            for a, b in v.items():
                if isinstance(b, dict):
                    nums = [x for x in b.values() if _num(x)]
                    if nums:
                        pairs.append((str(a), float(nums[0])))
        if len(pairs) < 2:
            continue
        pairs.sort(key=lambda p: -p[1])
        shown = pairs[:MAX_ROWS]
        fmt = lambda n: str(int(n)) if float(n).is_integer() else f"{n:.1f}"
        rows = ["| Ad | Değer |", "|---|---|"] + [f"| {_cell(a)} | {fmt(n)} |" for a, n in shown]
        note = f"{_human_key(k).capitalize()} — {len(pairs)} kalem" + (f", ilk {len(shown)} gösteriliyor" if len(pairs) > len(shown) else "")
        out.append(f"**{note}**\n\n" + "\n".join(rows))
        if len(out) >= 2:
            break
    return out


def _parse_json(text: str) -> Any:
    t = (text or "").strip()
    if not t or t[0] not in "{[":
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(t)
        return obj
    except Exception:
        return None


def _block_text(label: str, body: str) -> str:
    kind = _clean_label(label)
    data = _parse_json(body)
    if isinstance(data, list) and data and all(isinstance(r, dict) for r in data):
        data = {"items": data}
    if isinstance(data, dict):
        found = _find_list(data)
        if found:
            _, rows = found
            total = _total(data, len(rows))
            tbl = _table(rows)
            if tbl:
                shown = min(len(rows), MAX_ROWS)
                note = f"{kind} verisi — {total} kayıt" + (f", ilk {shown} gösteriliyor" if total > shown else "")
                return f"**{note}**\n\n{tbl}"
        sc = _scalars(data)
        ct = _counters(data)
        if sc or ct:
            parts = []
            if sc:
                parts.append(f"**{kind} verisi (özet)**\n\n" + "\n".join(sc))
            parts.extend(ct)
            return "\n\n".join(parts)
        n = len(found[1]) if found else None
        return f"Cevap özetlenemedi; **{kind}** verisi alındı" + (f" ({n} kayıt)." if n else ".")
    if (body or "").lstrip()[:1] in "{[":
        return f"Cevap özetlenemedi; **{kind}** verisi alındı (kısaltılmış/okunamayan biçim)."
    txt = (body or "").strip()
    if not txt:
        return ""
    clip = txt if len(txt) <= MAX_TEXT else txt[:MAX_TEXT] + "\n… (kısaltıldı)"
    return f"**{kind} çıktısı**\n\n```\n{clip}\n```"


def render(evidence: str) -> str:
    """Okunur özet (asla ham JSON değil). Kanıt boşsa kısa not."""
    ev = (evidence or "").strip()
    if not ev:
        return "Araç çıktısı bu turda boş döndü."
    parts = _BLOCK_RE.split(ev)
    blocks: List[str] = []
    if len(parts) >= 3:
        # parts: [önsöz, etiket1, gövde1, etiket2, gövde2, …]
        for i in range(1, len(parts) - 1, 2):
            t = _block_text(parts[i], parts[i + 1])
            if t:
                blocks.append(t)
            if len(blocks) >= MAX_BLOCKS:
                break
    else:
        t = _block_text("araç", ev)
        if t:
            blocks.append(t)
    if not blocks:
        return "Cevap özetlenemedi; araç verisi alındı."
    more = ""
    n_blocks = (len(parts) - 1) // 2 if len(parts) >= 3 else 1
    if n_blocks > MAX_BLOCKS:
        more = f"\n\n_(+{n_blocks - MAX_BLOCKS} kaynak daha alındı; kısalık için gösterilmedi.)_"
    body = "\n\n".join(blocks) + more
    if all(b.startswith("Cevap özetlenemedi") for b in blocks):
        return body
    return "Model bu turda cevabı yazamadı; toplanan verinin kısa dökümü aşağıda:\n\n" + body
