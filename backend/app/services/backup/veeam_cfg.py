"""Veeam yanıt ayrıştırıcıları (F.1): iş yapılandırması, proxy, nesne yolu.

Alan adları YALNIZ resmi dokümandan (VBR 13 REST 1.3-rev1; ``veeam_api_ref.ENDPOINTS``):
  * Jobs → "Get All Jobs" yanıt modeli
    https://helpcenter.veeam.com/references/vbr/13/rest/1.3-rev1/tag/Jobs/index.html
  * Proxies → "Get All Proxies" / "Get All Proxy States"
    https://helpcenter.veeam.com/references/vbr/13/rest/1.3-rev1/tag/Proxies/index.html
  * Repositories → "Get All Repositories" (immutability alanı YOK → not_measurable)
    https://helpcenter.veeam.com/references/vbr/13/rest/1.3-rev1/tag/Repositories/index.html

Üçlü durum: alan yanıtta yoksa ya da bool değilse ``None`` (= ölçülemedi). ``False`` yalnız
yanıt açıkça ``false`` dediğinde döner — eksik alan asla "kapalı" sayılmaz.
"""
from __future__ import annotations

import ipaddress
import re
from typing import Any, Dict, List, Optional

_MISSING = object()
_DAYS_TR = {"sunday": "Paz", "monday": "Pzt", "tuesday": "Sal", "wednesday": "Çar",
            "thursday": "Per", "friday": "Cum", "saturday": "Cmt"}


def _g(d: Any, *path: str) -> Any:
    cur = d
    for k in path:
        if not isinstance(cur, dict) or k not in cur:
            return _MISSING
        cur = cur[k]
    return cur


def tri(v: Any) -> Optional[bool]:
    """Yalnız gerçek bool → bool; aksi halde None (ölçülemedi)."""
    return v if isinstance(v, bool) else None


def _tri_at(d: Any, *path: str) -> Optional[bool]:
    v = _g(d, *path)
    return None if v is _MISSING else tri(v)


def _int_at(d: Any, *path: str) -> Optional[int]:
    v = _g(d, *path)
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _str_at(d: Any, *path: str) -> Optional[str]:
    v = _g(d, *path)
    return v if isinstance(v, str) and v else None


# ── host adı normalizasyonu (vCenter eşleşmesi) ──────────────────────────────

def normalize_host(h: Any) -> Optional[str]:
    """``https://VC01.Tech.Local:443/`` → ``vc01.tech.local``. IP aynen (küçük harf)."""
    if not isinstance(h, str):
        return None
    s = h.strip().lower()
    if not s:
        return None
    s = re.sub(r"^[a-z][a-z0-9+.-]*://", "", s).split("/")[0]
    if s.count(":") == 1:          # host:port (IPv6 değil)
        s = s.split(":")[0]
    return s.rstrip(".") or None


def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s.strip("[]"))
        return True
    except ValueError:
        return False


def host_matches(a: Any, b: Any) -> bool:
    """Tam eşit veya (ikisi de IP değilse) kısa ad (ilk etiket) eşit."""
    na, nb = normalize_host(a), normalize_host(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    if _is_ip(na) or _is_ip(nb):
        return False
    return na.split(".")[0] == nb.split(".")[0]


def host_from_backup_object_path(path: Any) -> Optional[str]:
    """``backupObjects[].path`` ilk bölümü vCenter hostName'idir (doküman örneği:
    ``vcenter01.tech.local\\Prague\\Templates\\Manual\\win10_pro``). Sahada doğrulanmadı (api_ref #8)."""
    if not isinstance(path, str) or "\\" not in path:
        return None
    return normalize_host(path.split("\\", 1)[0])


# ── iş yapılandırması ────────────────────────────────────────────────────────

def _schedule_summary(sch: Any) -> Optional[str]:
    if _g(sch, "runAutomatically") is _MISSING:
        return None
    if _g(sch, "runAutomatically") is False:
        return "Elle"
    parts: List[str] = []
    if _tri_at(sch, "daily", "isEnabled"):
        t = _str_at(sch, "daily", "localTime") or "?"
        kind = _str_at(sch, "daily", "dailyKind")
        days = _g(sch, "daily", "days")
        if kind == "SelectedDays" and isinstance(days, list):
            parts.append("Günlük %s (%s)" % (t, ",".join(_DAYS_TR.get(str(x).lower(), str(x)) for x in days)))
        else:
            parts.append(f"Günlük {t}")
    if _tri_at(sch, "monthly", "isEnabled"):
        parts.append("Aylık %s" % (_str_at(sch, "monthly", "localTime") or "?"))
    if _tri_at(sch, "periodically", "isEnabled"):
        n = _int_at(sch, "periodically", "frequency")
        unit = {"Hours": "saat", "Minutes": "dk", "Days": "gün"}.get(_str_at(sch, "periodically", "periodicallyKind") or "", "")
        parts.append(f"Her {n} {unit}".strip() if n else "Periyodik")
    if _tri_at(sch, "continuously", "isEnabled"):
        parts.append("Sürekli")
    if _tri_at(sch, "afterThisJob", "isEnabled"):
        parts.append("Şu işten sonra: %s" % (_str_at(sch, "afterThisJob", "jobName") or "?"))
    return "; ".join(parts) if parts else "Tanımsız"


def parse_job_config(j: Dict[str, Any]) -> Dict[str, Any]:
    """``GET /api/v1/jobs`` bir öğesi → normalize yapılandırma. Eksik alan = ``None`` (ölçülemedi)."""
    st = _g(j, "storage")
    adv = _g(j, "storage", "advancedSettings")
    gfs: Dict[str, Optional[int]] = {}
    for k, cnt in (("weekly", "keepForNumberOfWeeks"), ("monthly", "keepForNumberOfMonths"),
                   ("yearly", "keepForNumberOfYears")):
        if _tri_at(j, "storage", "gfsPolicy", k, "isEnabled"):
            gfs[k] = _int_at(j, "storage", "gfsPolicy", k, cnt)
    vms: List[Dict[str, Any]] = []
    for v in (_g(j, "virtualMachines", "includes") if _g(j, "virtualMachines", "includes") is not _MISSING else []) or []:
        if isinstance(v, dict):
            vms.append({"host": normalize_host(v.get("hostName")), "name": v.get("name"),
                        "object_id": v.get("objectId") if isinstance(v.get("objectId"), str) else None,
                        "type": v.get("type")})
    proxy_ids = _g(j, "storage", "backupProxies", "proxyIds")
    return {
        "id": str(j.get("id")),
        "disabled": tri(j.get("isDisabled")),
        "vbr_type": j.get("type"),
        # şifreleme: storage.advancedSettings.storageData.encryption.isEnabled (Jobs → Get All Jobs)
        "encryption": _tri_at(adv, "storageData", "encryption", "isEnabled") if adv is not _MISSING else None,
        # CBT: storage.advancedSettings.vSphere.changedBlockTracking.isEnabled (yalnız VMware işleri)
        "cbt": _tri_at(adv, "vSphere", "changedBlockTracking", "isEnabled") if adv is not _MISSING else None,
        "backup_health": _tri_at(adv, "backupHealth", "isEnabled") if adv is not _MISSING else None,
        "backup_mode": _str_at(adv, "backupModeType") if adv is not _MISSING else None,
        "retention_type": _str_at(st, "retentionPolicy", "type") if st is not _MISSING else None,
        "retention_quantity": _int_at(st, "retentionPolicy", "quantity") if st is not _MISSING else None,
        "gfs_enabled": _tri_at(st, "gfsPolicy", "isEnabled") if st is not _MISSING else None,
        "gfs": gfs,
        "app_aware": _tri_at(j, "guestProcessing", "appAwareProcessing", "isEnabled"),
        "retry_enabled": _tri_at(j, "schedule", "retry", "isEnabled"),
        "retry_count": _int_at(j, "schedule", "retry", "retryCount"),
        "retry_wait_min": _int_at(j, "schedule", "retry", "awaitMinutes"),
        "window_enabled": _tri_at(j, "schedule", "backupWindow", "isEnabled"),
        "schedule_summary": _schedule_summary(_g(j, "schedule")),
        "proxy_auto": _tri_at(st, "backupProxies", "autoSelectEnabled") if st is not _MISSING else None,
        "proxy_ids": [str(x) for x in proxy_ids] if isinstance(proxy_ids, list) else None,
        "repository_id": _str_at(st, "backupRepositoryId") if st is not _MISSING else None,
        "vms": vms,
    }


# ── proxy ────────────────────────────────────────────────────────────────────

def parse_proxy_state(p: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": str(p.get("id")), "name": p.get("name") or "", "type": p.get("type"),
            "host_name": p.get("hostName") if isinstance(p.get("hostName"), str) else None,
            "is_disabled": tri(p.get("isDisabled")), "is_online": tri(p.get("isOnline")),
            "is_out_of_date": tri(p.get("isOutOfDate"))}


def parse_proxy_config(p: Dict[str, Any]) -> Dict[str, Any]:
    return {"id": str(p.get("id")), "transport_mode": _str_at(p, "server", "transportMode"),
            "max_tasks": _int_at(p, "server", "maxTaskCount")}
