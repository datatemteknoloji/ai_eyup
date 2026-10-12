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

from app.services.backup.veeam_cfg import host_matches

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


def _narrow(cands: List[Dict[str, Any]], obj_host: Optional[str]) -> Tuple[List[Dict[str, Any]], bool]:
    """F.1: yedek nesnesinin vCenter hostName'i bilinen vCenter anahtarlarından biriyle eşleşen adaylara
    DARALTIR; asla eler-bırakmaz (hostName alanı sahada doğrulanmadı — tek adayı host yüzünden reddetmek
    yanlış 'korunmasız' üretirdi). Daraltma yalnız çok adaylı (ör. iki vCenter'da aynı moref/ad) durumda etkilidir."""
    if not obj_host or len(cands) < 2:
        return cands, False
    n = [v for v in cands if any(host_matches(obj_host, k) for k in (v.get("vcenter_keys") or ()))]
    if n and len(n) < len(cands):
        return n, True
    return cands, False


def match_object(obj: Dict[str, Any], idx: VmIndex) -> Tuple[Optional[int], str, str]:
    """→ (server_id | None, method, confidence). method '+host' son eki: vCenter hostName ile desteklendi."""
    name = str(obj.get("name") or "")
    ref = obj.get("object_ref")
    obj_host = obj.get("host_name")
    by_ref, n1 = _narrow(idx.by_ref.get(str(ref), []) if ref else [], obj_host)
    by_name, n2 = _narrow(idx.by_name.get(name, []), obj_host)
    sfx = "+host" if (n1 or n2) else ""
    if len(by_ref) == 1 and len(by_name) == 1 and by_ref[0]["id"] == by_name[0]["id"]:
        return by_ref[0]["id"], "moref+name" + sfx, CONF_EXACT
    if len(by_name) == 1:
        return by_name[0]["id"], "name" + sfx, CONF_HIGH
    if len(by_ref) == 1 and len(by_name) == 0:
        return by_ref[0]["id"], "moref" + sfx, CONF_HIGH
    if len(by_name) > 1:
        return None, "ambiguous_name", CONF_NONE
    low = idx.by_lower.get(name.lower(), [])
    if len(low) == 1:
        return low[0]["id"], "name_ci", CONF_LOW
    sh = idx.by_short.get(_short(name), [])
    if len(sh) == 1:
        return sh[0]["id"], "short_name", CONF_LOW
    return None, "none", CONF_NONE


def inventory_vms(db: Any) -> List[Dict[str, Any]]:
    """Eşleştirme için ainew VMware VM listesi + vCenter anahtarları (hostname / IP / ad; yalnız okuma)."""
    from app.services import virt_insights_data as vd
    from app.services.backup.veeam_cfg import normalize_host
    hvs = vd.virt_hypervisors(db, platform="vmware")
    keys = {h.id: tuple(k for k in (normalize_host(h.hostname), normalize_host(h.ip_address), normalize_host(h.name)) if k)
            for h in hvs}
    out = vd.vm_allocations(db, [h.id for h in hvs])
    for v in out:
        v["vcenter_keys"] = keys.get(v.get("hypervisor_id"), ())
    return out


def match_all(objects: List[Dict[str, Any]], vms: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], Optional[int], str, str]]:
    idx = VmIndex(vms)
    return [(o, *match_object(o, idx)) for o in objects]
