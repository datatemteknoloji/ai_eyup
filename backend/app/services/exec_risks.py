"""Öncelikli riskler açık bulgulardan gelir. Ham olay başlığı kullanılmaz."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

from sqlalchemy.orm import Session

from app.models.infra_finding import InfraFinding

_AREAS = {
    "vmware": "Sanallaştırma",
    "olvm": "Sanallaştırma",
    "ocp_virt": "Sanallaştırma",
    "ocp": "OpenShift",
    "linux": "Linux",
    "windows": "Windows",
}
_SEV = {"critical": 5, "high": 4, "medium": 2, "low": 1, "info": 0}
_IMPACT = {"critical": 3, "high": 3, "medium": 2, "low": 1, "info": 0}
_ACTION = {
    "critical": "Önce bu varlığı inceleyin.",
    "high": "Bu hafta içinde giderin.",
    "medium": "Planlı bakımda giderin.",
    "low": "İzlemeye devam edin.",
}
_IP = re.compile(r"\d{1,3}(?:\.\d{1,3}){3}")
_LOG = re.compile(r"logged in|user-agent|python-requests", re.I)

RULE_TR = "Sıra = şiddet × açık kalma günü × etki. Etki: kritik ve yüksek 3, orta 2, düşük 1."


def _plain(text: Optional[str]) -> Optional[str]:
    raw = (text or "").strip()
    if not raw or _IP.search(raw) or _LOG.search(raw):
        return None
    return raw


def _age_days(first_seen: Optional[datetime], now: datetime) -> int:
    if first_seen is None:
        return 1
    if first_seen.tzinfo is None:
        first_seen = first_seen.replace(tzinfo=timezone.utc)
    return max(1, (now - first_seen).days)


def rank_findings(
    db: Session,
    *,
    now: Optional[datetime] = None,
    synthetic_source_ids: Optional[Set[int]] = None,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    hidden = synthetic_source_ids or set()
    rows = (
        db.query(InfraFinding)
        .filter(InfraFinding.active == True, InfraFinding.result == "fail")  # noqa: E712
        .all()
    )
    ranked: List[Dict[str, Any]] = []
    for row in rows:
        area = _AREAS.get(row.platform or "")
        if area is None:
            continue
        if row.source_id is not None and int(row.source_id) in hidden:
            continue
        if (row.entity_name or "").startswith("ZZ-FAKE"):
            continue
        evidence = row.evidence or {}
        if evidence.get("demo") or "demo" in (row.source_name or "").lower():
            continue
        sev = (row.severity or "medium").lower()
        if _SEV.get(sev, 0) <= 0:
            continue
        age = _age_days(row.first_seen, now)
        impact = _IMPACT.get(sev, 1)
        title = _plain(row.title) or "Açık bulgu"
        action = _plain(row.recommendation) or _ACTION.get(sev, _ACTION["medium"])
        ranked.append({
            "area": area,
            "sentence": title,
            "impact": impact,
            "age_days": age,
            "action": action,
            "entity_name": _plain(row.entity_name),
            "first_seen": row.first_seen.isoformat() if row.first_seen else None,
            "rank": _SEV[sev] * age * impact,
            "severity": sev,
        })
    ranked.sort(key=lambda item: (-item["rank"], item["sentence"]))
    return ranked[:limit]
