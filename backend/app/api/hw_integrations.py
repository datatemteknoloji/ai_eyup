"""Opsiyonel donanım yönetimi sağlayıcıları (Dell OME / HPE OneView–OVGD) — yapılandırma (Entegrasyonlar, yalnız admin).

Kimlik bilgisi `encrypt_secret` ile `integration_instances.credential_ref` içinde saklanır; hiçbir yanıtta/log'da parola dönmez.

Hesap kilitlenmesin diye (docs/plans/hw-providers.md §12):
  * Kimlik bilgisi/adres DEĞİŞİNCE otomatik senkron durur (`auth_halted`, kind=changed); yalnız başarılı “Bağlantıyı test et” sürdürür.
  * 401/403 → yeniden deneme yok, senkron durur; kaydetmek tek başına sürdürmez.
  * Test düğmesinde bekleme süresi + aynı entegrasyona aynı anda tek deneme (Redis kilidi).
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import require_role
from app.core.config import remote_llm_enabled
from app.core.database import get_db
from app.core.encryption import decrypt_secret, encrypt_secret
from app.models.hw import HwManager
from app.models.integration_instance import IntegrationInstance
from app.models.user import User
from app.services.hw import auth_guard
from app.services.hw.constants import (
    CATEGORY, DEFAULT_ALARM_SEC, DEFAULT_INVENTORY_SEC, DEFAULT_WARRANTY_SEC, KIND_DELL, KIND_DEMO, KIND_HPE,
    MIN_ALARM_SEC, MODE_ONEVIEW, MODE_OVGD, SUPPORT_LABEL_TR, TEST_COOLDOWN_SEC,
)
from app.services.hw.creds import load_meta
from app.services.hw.demo_gate import DISABLED_MSG_TR, demo_enabled
from app.services.integrations.registry import get_provider_factory

router = APIRouter()
_admin = require_role("admin")
_KINDS = (KIND_DELL, KIND_HPE, KIND_DEMO)


class InstanceBody(BaseModel):
    kind: str = Field(KIND_DELL, description="dell_ome | hpe_oneview | hw_demo")
    label: str = ""
    endpoint: str = ""
    port: int = Field(443, ge=1, le=65535)
    username: str = ""
    password: Optional[str] = None            # boş → mevcut parola korunur
    verify_ssl: bool = True
    ca_bundle_path: Optional[str] = None
    mode: str = MODE_OVGD                     # yalnız hpe_oneview: ovgd | oneview
    appliances: List[str] = Field(default_factory=list)   # mode=oneview: ek appliance adresleri (paylaşılan hesap)
    login_domain: str = "Local"
    alarm_interval_sec: int = Field(DEFAULT_ALARM_SEC, ge=MIN_ALARM_SEC, le=86400)
    inventory_interval_sec: int = Field(DEFAULT_INVENTORY_SEC, ge=3600, le=7 * 86400)
    warranty_interval_sec: int = Field(DEFAULT_WARRANTY_SEC, ge=3600, le=7 * 86400)
    fetch_firmware: bool = False              # yalnız dell_ome: cihaz başına firmware envanteri (yavaş, kısıtlı)
    throttle_sec: float = Field(0.0, ge=0.0, le=5.0)


class TestBody(InstanceBody):
    instance_id: Optional[int] = None


def _creds(row: IntegrationInstance) -> Dict[str, str]:
    try:
        return json.loads(decrypt_secret(row.credential_ref) or "{}") if row.credential_ref else {}
    except Exception:  # noqa: BLE001
        return {}


def _fingerprint(row: IntegrationInstance) -> str:
    """Bağlantı kimliği: adres + hesap + parola + mod/appliance/TLS. Değişirse yeniden test gerekir."""
    c = _creds(row)
    m = load_meta(row)
    raw = json.dumps([row.kind, row.endpoint, c.get("username"), c.get("password"), m.get("port"), m.get("mode"),
                      sorted(m.get("appliances") or []), m.get("login_domain"), row.verify_ssl, m.get("ca_bundle_path")],
                     sort_keys=True, default=str)
    return hashlib.sha256(raw.encode()).hexdigest()


def _dict(db: Session, row: IntegrationInstance) -> Dict[str, Any]:
    m = load_meta(row)
    c = _creds(row)
    halt = auth_guard.halt_info(row)
    iv = m.get("intervals") or {}
    mgrs = db.query(HwManager).filter(HwManager.instance_id == row.id).order_by(HwManager.id).all()
    return {
        "id": row.id, "kind": row.kind, "demo": row.kind == KIND_DEMO,
        "demo_inactive": row.kind == KIND_DEMO and not demo_enabled(),
        "label": row.label, "endpoint": row.endpoint, "port": m.get("port") or 443,
        "username": c.get("username") or "", "has_credentials": bool(row.credential_ref),
        "verify_ssl": row.verify_ssl, "ca_bundle_path": m.get("ca_bundle_path"),
        "mode": m.get("mode") or MODE_OVGD, "appliances": m.get("appliances") or [],
        "login_domain": m.get("login_domain") or "Local",
        "alarm_interval_sec": iv.get("alarm") or row.sync_interval_sec or DEFAULT_ALARM_SEC,
        "inventory_interval_sec": iv.get("inventory") or DEFAULT_INVENTORY_SEC,
        "warranty_interval_sec": iv.get("warranty") or DEFAULT_WARRANTY_SEC,
        "fetch_firmware": bool(m.get("fetch_firmware")), "throttle_sec": m.get("throttle_sec") or 0.0,
        "enabled": row.enabled,
        "last_sync_at": row.last_sync_at.isoformat() if row.last_sync_at else None,
        "last_status": row.last_status, "last_error": row.last_error,
        "auth_halted": bool(halt), "auth_halt": halt,
        "warnings": m.get("warnings") or [], "not_measurable": m.get("not_measurable") or [],
        "counts": m.get("last_counts"), "parts_at": m.get("parts_at") or {},
        "consecutive_failures": m.get("consecutive_failures") or 0, "breaker_until": m.get("breaker_until"),
        "managers": [{"id": g.id, "key": g.provider_key, "kind": g.manager_kind, "name": g.name, "address": g.address,
                      "version": g.version, "api_version": g.api_version, "support_level": g.support_level,
                      "support_label": SUPPORT_LABEL_TR.get(g.support_level, g.support_level), "status": g.status,
                      "error": g.last_error, "server_count": g.server_count,
                      "last_sync_at": g.last_sync_at.isoformat() if g.last_sync_at else None} for g in mgrs],
    }


def _apply(row: IntegrationInstance, b: InstanceBody) -> bool:
    """Gövdeyi satıra uygular. Dönüş: bağlantı kimliği (adres/hesap/parola/mod) DEĞİŞTİ mi."""
    if b.kind not in _KINDS:
        raise HTTPException(400, f"Desteklenmeyen sağlayıcı: {b.kind}")
    if b.kind == KIND_DEMO and not demo_enabled():
        raise HTTPException(403, DISABLED_MSG_TR)
    if b.mode not in (MODE_OVGD, MODE_ONEVIEW):
        raise HTTPException(400, f"Desteklenmeyen mod: {b.mode}")
    if b.kind != KIND_DEMO and not (b.endpoint or "").strip():
        raise HTTPException(400, "Sunucu adresi zorunlu")
    before = _fingerprint(row) if row.credential_ref or row.endpoint else None
    row.category, row.kind = CATEGORY, b.kind
    row.label = (b.label or ("DEMO donanım (fixture)" if b.kind == KIND_DEMO else b.endpoint))[:255]
    row.endpoint = (b.endpoint or "").strip()[:512]
    row.verify_ssl = bool(b.verify_ssl)
    row.sync_interval_sec = b.alarm_interval_sec
    m = load_meta(row)
    m.update(port=b.port, ca_bundle_path=(b.ca_bundle_path or None),
             intervals={"alarm": b.alarm_interval_sec, "inventory": b.inventory_interval_sec,
                        "warranty": b.warranty_interval_sec},
             throttle_sec=b.throttle_sec, fetch_firmware=bool(b.fetch_firmware and b.kind == KIND_DELL))
    if b.kind == KIND_HPE:
        m.update(mode=b.mode, appliances=[a.strip() for a in b.appliances if a and a.strip()],
                 login_domain=(b.login_domain or "Local").strip())
    row.meta_json = json.dumps(m)
    if b.kind != KIND_DEMO:
        prev = _creds(row)
        user = b.username or prev.get("username") or ""
        pw = b.password if b.password else prev.get("password") or ""
        row.credential_ref = encrypt_secret(json.dumps({"username": user, "password": pw}))
    return before is not None and before != _fingerprint(row)


def _get(db: Session, iid: int) -> IntegrationInstance:
    row = db.query(IntegrationInstance).filter(IntegrationInstance.id == iid,
                                               IntegrationInstance.category == CATEGORY).first()
    if row is None:
        raise HTTPException(404, "Sağlayıcı bulunamadı")
    return row


def _after_change() -> None:
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()


def _refresh_findings(db: Session) -> None:
    try:
        from app.services.hw.findings_engine import persist_hw_findings
        persist_hw_findings(db)
    except Exception:  # noqa: BLE001
        db.rollback()


@router.get("/instances")
def list_instances(db: Session = Depends(get_db), _u: User = Depends(_admin)):
    rows = db.query(IntegrationInstance).filter(IntegrationInstance.category == CATEGORY).order_by(
        IntegrationInstance.id).all()
    kinds = [{"kind": KIND_DELL, "label": "Dell OpenManage Enterprise (OME 4.x)"},
             {"kind": KIND_HPE, "label": "HPE OneView / OneView Global Dashboard"}]
    if demo_enabled():
        kinds.append({"kind": KIND_DEMO, "label": "DEMO / fixture (gerçek sağlayıcı değil)"})
    return {
        "instances": [_dict(db, r) for r in rows], "kinds": kinds, "demo_enabled": demo_enabled(),
        "llm_remote": remote_llm_enabled(), "test_cooldown_sec": TEST_COOLDOWN_SEC,
        "notes": {
            "account": "Salt-okunur hesap kullanın (OME: Viewer/VIEW yetkisi; OneView/OVGD: salt-okunur rol). "
                       "RSA SecurID etkin OME hesapları REST API'yi kullanamaz.",
            "auth_protection": "Kimlik doğrulama bir kez denenir; reddedilirse otomatik senkron durur (hesap kilitlenmesin). "
                               "Bilgileri düzeltip “Bağlantıyı test et” ile sürdürün; yalnız kaydetmek sürdürmez.",
            "support": "Doğrulanmış / Uyumlu / Desteklenmeyen seviyeleri sürüm okunarak belirlenir; bilinmeyen alanlar “ölçülemedi” gösterilir.",
        },
    }


@router.post("/instances")
def create_instance(body: InstanceBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    row = IntegrationInstance(category=CATEGORY, kind=body.kind, enabled=False, last_status="never")
    _apply(row, body)
    db.add(row)
    db.commit()
    db.refresh(row)
    return _dict(db, row)


@router.put("/instances/{iid}")
def update_instance(iid: int, body: InstanceBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    row = _get(db, iid)
    changed = _apply(row, body)
    if changed and row.kind != KIND_DEMO and not auth_guard.is_halted(row):
        # Yeni bilgiler TEST EDİLMEDEN otomatik denenmez (yazım hatası → hesap kilidi riski)
        m = load_meta(row)
        m[auth_guard.HALT_KEY] = True
        m["auth_halted_kind"] = "changed"
        m["auth_halted_msg"] = ("Bağlantı bilgileri değişti; otomatik senkron durduruldu. "
                                "“Bağlantıyı test et” ile doğrulayın.")
        from datetime import datetime, timezone
        m["auth_halted_at"] = datetime.now(timezone.utc).isoformat()
        row.meta_json = json.dumps(m)
    db.commit()
    _after_change()
    return _dict(db, row)


@router.delete("/instances/{iid}")
def delete_instance(iid: int, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    row = _get(db, iid)
    db.delete(row)
    db.commit()
    _after_change()
    _refresh_findings(db)
    return {"ok": True}


@router.post("/test")
def test_connection(body: TestBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    """Bağlantı testi (kaydetmeden de çalışır). Kayıtlı + değişmemiş bilgilerle başarılı test, durdurulmuş senkronu sürdürür."""
    stored: Optional[IntegrationInstance] = _get(db, body.instance_id) if body.instance_id else None
    tmp = IntegrationInstance(category=CATEGORY, kind=body.kind, enabled=False)
    if stored is not None:
        tmp.credential_ref = stored.credential_ref
        tmp.meta_json = stored.meta_json
    if body.kind != KIND_DEMO and not body.password and stored is None:
        raise HTTPException(400, "Parola gerekli")
    _apply(tmp, body)
    factory = get_provider_factory(body.kind)
    if factory is None:
        raise HTTPException(400, "Sağlayıcı kayıtlı değil")

    same = stored is not None and _fingerprint(tmp) == _fingerprint(stored)
    key = f"i{stored.id}" if stored is not None else hashlib.sha1(
        f"{tmp.kind}|{tmp.endpoint}|{_creds(tmp).get('username')}".encode()).hexdigest()[:20]
    wait = auth_guard.acquire_test_slot(key)
    if wait:
        raise HTTPException(429, f"Hesap kilidini önlemek için test düğmesi {wait} sn sonra yeniden kullanılabilir.")

    with auth_guard.attempt_lock(stored.id if stored is not None else None) as got:
        if not got:
            raise HTTPException(409, "Bu entegrasyona karşı başka bir bağlantı denemesi sürüyor; birazdan tekrar deneyin.")
        res = factory(tmp).test_connection()

    out: Dict[str, Any] = {"ok": res.ok, "message": res.message, "api_version": res.api_version,
                           "details": res.details, "demo": body.kind == KIND_DEMO, "resumed": False,
                           "needs_save": bool(stored is not None and not same)}
    if stored is not None and same:
        if res.ok:
            was = auth_guard.is_halted(stored)
            auth_guard.clear(db, stored)
            out["resumed"] = was
            _after_change()
        elif (res.details or {}).get("auth_halt"):
            d = res.details or {}
            auth_guard.halt(db, stored, kind=str(d.get("kind") or "auth"), message=res.message, where="test")
            out["auth_halted"] = True
    if not res.ok and (res.details or {}).get("auth_halt"):
        out["hint"] = ("Kimlik doğrulama reddedildi. Hesap kilitlenmesin diye tekrar denemeyin; kullanıcı adı/parolayı "
                       "doğrulayıp kaydedin, sonra tek bir test yapın.")
    return out


class EnableBody(BaseModel):
    enabled: bool


@router.post("/instances/{iid}/enable")
def enable_instance(iid: int, body: EnableBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    from app.services.hw.sync import sync_instance
    row = _get(db, iid)
    if body.enabled and row.kind == KIND_DEMO and not demo_enabled():
        raise HTTPException(403, DISABLED_MSG_TR)
    if body.enabled and auth_guard.is_halted(row):
        raise HTTPException(409, "Kimlik doğrulama koruması: önce “Bağlantıyı test et” ile bilgileri doğrulayın.")
    row.enabled = body.enabled
    db.commit()
    sync: Optional[Dict[str, Any]] = None
    if body.enabled:
        sync = sync_instance(db, row, force=True)
        _after_change()
        if sync.get("ok"):
            _refresh_findings(db)
    else:
        _after_change()
        _refresh_findings(db)
    db.refresh(row)
    return {"instance": _dict(db, row), "sync": sync}


@router.post("/instances/{iid}/sync")
def sync_now(iid: int, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    from app.services.hw.sync import sync_instance
    row = _get(db, iid)
    if not row.enabled:
        raise HTTPException(400, "Önce sağlayıcıyı etkinleştirin")
    if auth_guard.is_halted(row):
        raise HTTPException(409, "Kimlik doğrulama koruması: önce “Bağlantıyı test et” ile bilgileri doğrulayın.")
    res = sync_instance(db, row, force=True)
    _after_change()
    if res.get("ok"):
        _refresh_findings(db)
    db.refresh(row)
    return {"instance": _dict(db, row), "sync": res}
