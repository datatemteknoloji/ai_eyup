"""Referans paketleri için resmi kaynak bağlantıları ve URL güvenliği (G.3).

- `backend/app/data/reference_sources.json`: izinli alan adları + doğrulanmış resmi bağlantılar.
- Arayüz yalnız `verified: true` bağlantıları gösterir; doğrulanamayanlar dosyada kalır ama gizlenir.
- Paket içindeki kayıt başına `source_url` (eski paketlerde `url`) yalnız https + izinli alan adı ise kabul edilir.
  Hiçbir bağlantı uydurulmaz: URL yoksa alan boş kalır.
"""
from __future__ import annotations

import json
import os
from functools import lru_cache
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlsplit

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "reference_sources.json")


@lru_cache(maxsize=1)
def _load() -> Dict[str, Any]:
    with open(_PATH, encoding="utf-8") as f:
        return json.load(f)


def allowed_domains() -> List[str]:
    return [d.lower() for d in _load().get("allowed_domains", [])]


def host_allowed(host: str) -> bool:
    h = (host or "").lower().rstrip(".")
    return any(h == d or h.endswith("." + d) for d in allowed_domains())


def check_source_url(url: Any) -> Tuple[bool, str]:
    """(geçerli, neden). Boş/None geçerlidir (bağlantı yok)."""
    if url is None or url == "":
        return True, ""
    if not isinstance(url, str):
        return False, "metin değil"
    try:
        u = urlsplit(url.strip())
    except ValueError:
        return False, "ayrıştırılamadı"
    if u.scheme != "https":
        return False, "https değil"
    if u.username or u.password:
        return False, "kimlik bilgisi içeriyor"
    if not u.hostname or not host_allowed(u.hostname):
        return False, "izinli resmi alan adı değil"
    if "..." in u.path or "…" in url:
        return False, "yer tutucu/eksik bağlantı"
    return True, ""


def safe_source_url(url: Any) -> Optional[str]:
    """Gösterim için: yalnız geçerli ve izinli bağlantı; aksi halde None."""
    if not url:
        return None
    ok, _ = check_source_url(url)
    return url.strip() if ok else None


def record_url(rec: Dict[str, Any]) -> Any:
    """Kayıttaki bağlantı: `source_url`, yoksa eski `url`."""
    return rec.get("source_url") if rec.get("source_url") not in (None, "") else rec.get("url")


def offenders(records: Iterable[Any], id_key: str = "id") -> List[str]:
    """İzinsiz bağlantı taşıyan kayıtlar: ["VMSA-1: <neden> (<url>)", ...]."""
    out: List[str] = []
    for r in records:
        if not isinstance(r, dict):
            continue
        for key in ("source_url", "url"):
            v = r.get(key)
            ok, why = check_source_url(v)
            if not ok:
                out.append(f"{r.get(id_key) or '?'}: {key} {why} ({str(v)[:80]})")
    return out


def verified_sources(pack_kind: Optional[str] = None) -> List[Dict[str, Any]]:
    out = []
    for s in _load().get("sources", []):
        if not s.get("verified"):
            continue
        if pack_kind and pack_kind not in (s.get("packs") or []):
            continue
        out.append({k: s.get(k) for k in ("id", "vendor", "title_tr", "title_en", "url", "verified_on")})
    return out


def unverified_sources() -> List[Dict[str, Any]]:
    """Denetim/rapor için: gizlenen bağlantılar ve nedenleri (arayüzde gösterilmez)."""
    return [{k: s.get(k) for k in ("id", "url", "reason", "verified_on")}
            for s in _load().get("sources", []) if not s.get("verified")]
