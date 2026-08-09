"""Async SIEM webhook forward for audit events."""

from __future__ import annotations

from typing import Any

from app.core.config import get_settings


def forward_audit_payload(payload: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    if not settings.siem_enabled or not (settings.siem_webhook_url or "").strip():
        return {"ok": False, "skipped": True, "reason": "siem disabled"}
    try:
        import httpx
    except ImportError:
        return {"ok": False, "error": "httpx missing"}
    try:
        with httpx.Client(timeout=settings.siem_timeout_sec) as client:
            res = client.post(settings.siem_webhook_url.strip(), json=payload)
            return {"ok": res.is_success, "status_code": res.status_code}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc)[:500]}
