"""Platform sağlık notu.

Pencere, çağıranın verdiği olay listesidir (yönetici özeti: son 24 saat).
Aynı varlık ve aynı olay türü (varsa reason ile) bu listede bir kez sayılır;
grupta en yüksek şiddet tutulur.

Ceza = (30×kritik + 12×uyarı) / popülasyon, tavan 100.
Skor = max(0, yuvarla(100 − ceza)).
Bilgi olayı cezaya girmez.
Popülasyon: Linux/Windows sunucu, sanallaştırma host, OpenShift node.
Popülasyon 0 veya izleme yoksa skor üretilmez.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

WEIGHT_CRITICAL = 30
WEIGHT_WARNING = 12

# Yayındaki önceki olay formülü. Karşılaştırma içindir; nota yazılmaz.
LEGACY_EVENT_WEIGHTS = {"emergency": 25, "critical": 15, "warning": 5, "info": 1}

_RANK = {"emergency": 4, "critical": 3, "warning": 2, "info": 1}

FORMULA_TR = (
    "24 saatlik pencerede aynı varlık ve aynı olay türü bir kez sayılır. "
    "Ceza = (30×kritik + 12×uyarı) / popülasyon, tavan 100. "
    "Skor = 100 − ceza. Bilgi olayı cezaya girmez. "
    "Popülasyon: Linux ve Windows sunucu, sanallaştırma host, OpenShift node."
)
FORMULA_EN = (
    "Within the 24-hour window the same asset and the same event type count once. "
    "Penalty = (30×critical + 12×warning) / population, capped at 100. "
    "Score = 100 − penalty. Info events add no penalty. "
    "Population: Linux and Windows servers, virtualization hosts, OpenShift nodes."
)


def _grade(score: Optional[int]) -> Dict[str, Optional[str]]:
    if score is None:
        return {"grade": None, "label": "Ölçülemedi", "color": "slate"}
    if score >= 90:
        return {"grade": "A", "label": "Sağlıklı", "color": "green"}
    if score >= 75:
        return {"grade": "B", "label": "İyi", "color": "blue"}
    if score >= 55:
        return {"grade": "C", "label": "Dikkat", "color": "yellow"}
    if score >= 35:
        return {"grade": "D", "label": "Sorunlu", "color": "orange"}
    return {"grade": "F", "label": "Kritik", "color": "red"}


def _unmeasured(population: int = 0) -> Dict[str, Any]:
    return {
        "score": None, "grade": None, "label": "Ölçülemedi", "color": "slate",
        "measurable": False, "penalty": None, "severity_breakdown": {},
        "event_count": 0, "raw_event_count": 0, "server_count": population,
        "legacy_score": None,
    }


def event_identity(ev: Any) -> Tuple[Any, ...]:
    """Varlık + olay türü. Aynı anahtar pencerede bir kez sayılır."""
    raw = getattr(ev, "raw_data", None) or {}
    if not isinstance(raw, dict):
        raw = {}
    server_id = getattr(ev, "server_id", None)
    if server_id:
        asset: Tuple[Any, ...] = ("server", server_id)
    elif raw.get("source_object"):
        asset = ("object", raw.get("cluster_id"), raw.get("namespace"), raw.get("source_object"))
    elif raw.get("host_name"):
        asset = ("host", raw.get("hypervisor_id"), raw.get("host_name"))
    else:
        asset = ("title", getattr(ev, "title", None) or "")
    kind = (getattr(ev, "event_type", None) or "", raw.get("reason") or "")
    return (asset, kind)


def dedupe_events(events: Sequence[Any]) -> List[Any]:
    best: Dict[Tuple[Any, ...], Any] = {}
    for ev in events:
        key = event_identity(ev)
        cur = best.get(key)
        if cur is None or _RANK.get(getattr(ev, "severity", None), 0) >= _RANK.get(getattr(cur, "severity", None), 0):
            best[key] = ev
    return list(best.values())


def score_from_counts(critical: int, warning: int, population: int, *, monitored: bool = True) -> Dict[str, Any]:
    if population <= 0 or monitored is False:
        return _unmeasured(population)
    penalty = min((critical * WEIGHT_CRITICAL + warning * WEIGHT_WARNING) / population, 100.0)
    score = max(0, round(100 - penalty))
    graded = _grade(score)
    return {
        "score": score,
        "measurable": True,
        "penalty": round(penalty, 1),
        "server_count": population,
        "critical": critical,
        "warning": warning,
        **graded,
    }


def score_events(events: Iterable[Any], population: int, *, monitored: Optional[bool] = None) -> Dict[str, Any]:
    raw = list(events)
    if population <= 0 or monitored is False:
        out = _unmeasured(population)
        out["raw_event_count"] = len(raw)
        return out
    unique = dedupe_events(raw)
    critical = warning = 0
    by_sev: Dict[str, int] = {}
    for ev in unique:
        sev = getattr(ev, "severity", None) or "info"
        by_sev[sev] = by_sev.get(sev, 0) + 1
        if sev in ("critical", "emergency"):
            critical += 1
        elif sev == "warning":
            warning += 1
    out = score_from_counts(critical, warning, population, monitored=True)
    out["severity_breakdown"] = by_sev
    out["event_count"] = len(unique)
    out["raw_event_count"] = len(raw)
    return out


def legacy_event_score(events: Iterable[Any], population: int) -> Optional[int]:
    """Önceki formül: tekilleştirme yok, ağırlık 25/15/5/1, popülasyona böl, tavan 100."""
    if population <= 0:
        return None
    penalty = 0
    for ev in events:
        penalty += LEGACY_EVENT_WEIGHTS.get(getattr(ev, "severity", None), 1)
    return max(0, round(100 - min(penalty / population, 100)))


def legacy_virt_score(critical: int, warning: int, host_count: int, manager_count: int) -> Optional[int]:
    """Önceki sanallaştırma formülü: yayılım + sabit varlık cezası."""
    if host_count <= 0 and manager_count <= 0:
        return None
    denom = max(host_count + manager_count, 1)
    spread = (critical / denom) * 60 + (warning / denom) * 20
    presence = 20 if critical else (8 if warning else 0)
    return max(0, min(100, round(100 - spread - presence)))
