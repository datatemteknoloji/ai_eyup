"""Yedek nesnesi ↔ ainew VM eşleştirme (deterministik).

Güven düzeyleri (``BkProtectedObject.match_confidence``):
  exact — moref VE ad birlikte eşleşir (ikisi de tekil)
  high  — ad birebir (büyük/küçük harf duyarlı) tekil eşleşir, veya moref tekil eşleşir
  low   — ad büyük/küçük harf farkıyla veya kısa ad (FQDN öneki) ile eşleşir
  none  — eşleşme yok veya belirsiz (aynı ad birden fazla VM'de)

RPO / "korumasız" kararında yalnız exact/high kullanılır; low yalnız inceleme
listesindedir (ölçülemedi) — yanlış eşleşme ile yanlış bulgu üretilmez.
moref eşleşmesi "doğrulanmadı" (veeam_api_ref #1): backupObjects.objectId alanının
her zaman VMware moref olduğu dokümanda net değil.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

CONF_EXACT, CONF_HIGH, CONF_LOW, CONF_NONE = "exact", "high", "low", "none"
TRUSTED = (CONF_EXACT, CONF_HIGH)


def _short(name: str) -> str:
    return (name or "").split(".")[0].lower()


class VmIndex:
    def __init__(self, vms: List[Dict[str, Any]]):
        self.by_name: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.by_lower: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.by_short: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        self.by_ref: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for v in vms:
            n = str(v.get("name") or "")
            if not n:
                continue
            self.by_name[n].append(v)
            self.by_lower[n.lower()].append(v)
            self.by_short[_short(n)].append(v)
            if v.get("ref"):
                self.by_ref[str(v["ref"])].append(v)


def match_object(obj: Dict[str, Any], idx: VmIndex) -> Tuple[Optional[int], str, str]:
    """→ (server_id | None, method, confidence)."""
    name = str(obj.get("name") or "")
    ref = obj.get("object_ref")
    by_ref = idx.by_ref.get(str(ref), []) if ref else []
    by_name = idx.by_name.get(name, [])
    if len(by_ref) == 1 and len(by_name) == 1 and by_ref[0]["id"] == by_name[0]["id"]:
        return by_ref[0]["id"], "moref+name", CONF_EXACT
    if len(by_name) == 1:
        return by_name[0]["id"], "name", CONF_HIGH
    if len(by_ref) == 1 and len(by_name) == 0:
        return by_ref[0]["id"], "moref", CONF_HIGH
    if len(by_name) > 1:
        return None, "ambiguous_name", CONF_NONE
    low = idx.by_lower.get(name.lower(), [])
    if len(low) == 1:
        return low[0]["id"], "name_ci", CONF_LOW
    sh = idx.by_short.get(_short(name), [])
    if len(sh) == 1:
        return sh[0]["id"], "short_name", CONF_LOW
    return None, "none", CONF_NONE


def match_all(objects: List[Dict[str, Any]], vms: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], Optional[int], str, str]]:
    idx = VmIndex(vms)
    return [(o, *match_object(o, idx)) for o in objects]
