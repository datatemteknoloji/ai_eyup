"""Opsiyonel yedekleme/DR sağlayıcıları — yapılandırma (Entegrasyonlar modülü, yalnız admin).

Kimlik bilgisi `encrypt_secret` ile `integration_instances.credential_ref` içinde saklanır
(`write_credential` DEĞİL); hiçbir yanıtta / log'da parola dönmez.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import require_role
from app.core.database import get_db
from app.core.encryption import decrypt_secret, encrypt_secret
from app.models.integration_instance import IntegrationInstance
from app.models.user import User
from app.services.backup import registry as breg
from app.services.backup.veeam_api_ref import DEFAULT_PORT, DEFAULT_REVISION, REVISIONS
from app.services.backup.demo_gate import DISABLED_MSG_TR, demo_enabled
from app.services.backup.veeam_provider import KIND_DEMO, KIND_REAL

router = APIRouter()
CATEGORY = "backup"
_admin = require_role("admin")


class InstanceBody(BaseModel):
    kind: str = Field(KIND_REAL, description="veeam_vbr | veeam_demo")
    label: str = ""
    endpoint: str = ""
    port: int = DEFAULT_PORT
    username: str = ""
    password: Optional[str] = None            # boş → mevcut parola korunur
    verify_ssl: bool = True
    ca_bundle_path: Optional[str] = None
    api_revision: str = DEFAULT_REVISION
    sync_interval_sec: int = Field(3600, ge=300, le=86400)
    lookback_days: int = Field(30, ge=1, le=365)


class TestBody(InstanceBody):
    instance_id: Optional[int] = None


def _meta(row: IntegrationInstance) -> Dict[str, Any]:
    return breg.parse_meta(row)


def _user(row: IntegrationInstance) -> str:
    try:
        return str(json.loads(decrypt_secret(row.credential_ref) or "{}").get("username") or "")
    except Exception:  # noqa: BLE001
        return ""


def _dict(row: IntegrationInstance) -> Dict[str, Any]:
    m = _meta(row)
    return {
        "id": row.id, "kind": row.kind, "demo": row.kind == KIND_DEMO,
        "demo_inactive": row.kind == KIND_DEMO and not demo_enabled(), "label": row.label, "endpoint": row.endpoint,
        "port": m.get("port") or DEFAULT_PORT, "username": _user(row), "has_credentials": bool(row.credential_ref),
        "verify_ssl": row.verify_ssl, "ca_bundle_path": m.get("ca_bundle_path"),
        "api_revision": m.get("api_revision") or DEFAULT_REVISION, "lookback_days": m.get("lookback_days") or 30,
        "enabled": row.enabled, "sync_interval_sec": row.sync_interval_sec,
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        "last_status": row.last_status, "last_error": row.last_error,
        "server": m.get("server"), "warnings": m.get("warnings") or [], "counts": m.get("last_counts"),
        "consecutive_failures": m.get("consecutive_failures") or 0, "breaker_until": m.get("breaker_until"),
    }


def _apply(row: IntegrationInstance, b: InstanceBody) -> None:
    if b.kind not in (KIND_REAL, KIND_DEMO):
        raise HTTPException(400, f"Desteklenmeyen sağlayıcı: {b.kind}")
    if b.kind == KIND_DEMO and not demo_enabled():
        raise HTTPException(403, DISABLED_MSG_TR)
    if b.api_revision not in REVISIONS:
        raise HTTPException(400, f"Desteklenmeyen API revizyonu: {b.api_revision}")
    if b.kind == KIND_REAL and not (b.endpoint or "").strip():
        raise HTTPException(400, "Sunucu adresi zorunlu")
    row.category, row.kind = CATEGORY, b.kind
    row.label = (b.label or ("DEMO Veeam (fixture)" if b.kind == KIND_DEMO else b.endpoint))[:255]
    row.endpoint = (b.endpoint or "").strip()[:512]
    row.verify_ssl = bool(b.verify_ssl)
    row.sync_interval_sec = b.sync_interval_sec
    m = _meta(row)
    m.update(port=b.port, ca_bundle_path=(b.ca_bundle_path or None), api_revision=b.api_revision,
             lookback_days=b.lookback_days)
    row.meta_json = json.dumps(m)
    if b.kind == KIND_REAL:
        prev = {}
        try:
            prev = json.loads(decrypt_secret(row.credential_ref) or "{}") if row.credential_ref else {}
        except Exception:  # noqa: BLE001
            prev = {}
        user = b.username or prev.get("username") or ""
        pw = b.password if b.password else prev.get("password") or ""
        row.credential_ref = encrypt_secret(json.dumps({"username": user, "password": pw}))


def _get(db: Session, iid: int) -> IntegrationInstance:
    row = db.query(IntegrationInstance).filter(IntegrationInstance.id == iid,
                                               IntegrationInstance.category == CATEGORY).first()
    if row is None:
        raise HTTPException(404, "Sağlayıcı bulunamadı")
    return row


def _after_change() -> None:
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()


@router.get("/instances")
def list_instances(db: Session = Depends(get_db), _u: User = Depends(_admin)):
    rows = db.query(IntegrationInstance).filter(IntegrationInstance.category == CATEGORY).order_by(
        IntegrationInstance.id).all()
    return {"instances": [_dict(r) for r in rows],
            "kinds": [{"kind": KIND_REAL, "label": "Veeam Backup & Replication (REST API)"}]
                     + ([{"kind": KIND_DEMO, "label": "DEMO / fixture (gerçek Veeam değil)"}] if demo_enabled() else []),
            "demo_enabled": demo_enabled(),
            "revisions": [{"revision": k, "status": v[0], "build": v[1]} for k, v in REVISIONS.items()],
            "note": "Önerilen VBR rolü: Veeam Backup Viewer (salt okunur). serverInfo yalnız Backup Administrator "
                    "rolüne açıktır; Viewer ile VBR sürümü görüntülenemez."}


@router.post("/instances")
def create_instance(body: InstanceBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    row = IntegrationInstance(category=CATEGORY, kind=body.kind, enabled=False, last_status="never")
    _apply(row, body)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _dict(row)


@router.put("/instances/{iid}")
def update_instance(iid: int, body: InstanceBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    row = _get(db, iid)
    _apply(row, body)
    db.commit()
    _after_change()
    return _dict(row)


@router.delete("/instances/{iid}")
def delete_instance(iid: int, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    row = _get(db, iid)
    db.delete(row)
    db.commit()
    _after_change()
    _resolve_findings(db)
    return {"ok": True}


def _resolve_findings(db: Session) -> None:
    try:
        from app.services.backup.rpo_engine import persist_backup_findings
        persist_backup_findings(db)
    except Exception:  # noqa: BLE001
        db.rollback()


@router.post("/test")
def test_connection(body: TestBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    """Kaydetmeden bağlantı testi. Parola boşsa kayıtlı parola kullanılır (instance_id ile)."""
    tmp = IntegrationInstance(category=CATEGORY, kind=body.kind, enabled=False)
    stored: Optional[IntegrationInstance] = _get(db, body.instance_id) if body.instance_id else None
    if stored is not None:
        tmp.credential_ref = stored.credential_ref
    if body.kind == KIND_REAL and not body.password and stored is None:
        raise HTTPException(400, "Parola gerekli")
    _apply(tmp, body)
    from app.services.backup.registry import get_provider_factory
    f = get_provider_factory(body.kind)
    if f is None:
        raise HTTPException(400, "Sağlayıcı kayıtlı değil")
    res = f(tmp).test_connection()
    return {"ok": res.ok, "message": res.message, "api_revision": res.api_version, "details": res.details,
            "demo": body.kind == KIND_DEMO}


class EnableBody(BaseModel):
    enabled: bool


@router.post("/instances/{iid}/enable")
def enable_instance(iid: int, body: EnableBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    from app.services.backup.sync import sync_instance
    row = _get(db, iid)
    if body.enabled and row.kind == KIND_DEMO and not demo_enabled():
        raise HTTPException(403, DISABLED_MSG_TR)
    row.enabled = body.enabled
    db.commit()
    sync: Optional[Dict[str, Any]] = None
    if body.enabled:
        sync = sync_instance(db, row, force=True)
        _after_change()
        if sync.get("ok"):
            _resolve_findings(db)   # ilk bulguları hemen üret
    else:
        _after_change()
        _resolve_findings(db)       # capability düştü → backup bulguları çözülür
    db.refresh(row)
    return {"instance": _dict(row), "sync": sync}


@router.post("/instances/{iid}/sync")
def sync_now(iid: int, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    from app.services.backup.sync import sync_instance
    row = _get(db, iid)
    if not row.enabled:
        raise HTTPException(400, "Önce sağlayıcıyı etkinleştirin")
    res = sync_instance(db, row, force=True)
    _after_change()
    if res.get("ok"):
        _resolve_findings(db)
    db.refresh(row)
    return {"instance": _dict(row), "sync": res}
