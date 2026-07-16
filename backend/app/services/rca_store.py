"""Incident RCA sonuçlarını geçmiş koruyarak saklar."""
from __future__ import annotations

from typing import Any, Dict, List


MAX_RCA_HISTORY = 10


def store_incident_rca(incident, new_result: Dict[str, Any]) -> None:
    """
    Yeni RCA sonucunu yazar; önceki analiz varsa history listesine ekler.
    history en fazla MAX_RCA_HISTORY kayıt tutar (eski → yeni).
    """
    prev = incident.rca_result if isinstance(incident.rca_result, dict) else {}
    history: List[Dict[str, Any]] = list(prev.get("history") or [])
    if prev.get("analysis"):
        history.append(
            {
                "analysis": prev.get("analysis"),
                "model": prev.get("model"),
                "analyzed_at": prev.get("analyzed_at"),
                "auto": prev.get("auto", False),
            }
        )
        if len(history) > MAX_RCA_HISTORY:
            history = history[-MAX_RCA_HISTORY:]
    payload = dict(new_result)
    payload["history"] = history
    incident.rca_result = payload
