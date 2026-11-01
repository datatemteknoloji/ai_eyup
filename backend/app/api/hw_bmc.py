"""Faz 3b — BMC (iLO/iDRAC) uç noktaları + kimlik profilleri. Okuma: `hardware` modülü; YAZMA: yalnız admin (module_policy ROLE_RULES).

* Parola hiçbir yanıtta dönmez (`has_password`).
* Çözümleme önceliği: host > portal > üretici > global (bmc_creds); başarısızlıkta zincirleme YOK.
* «Bağlantıyı test et» TEK deneme + bekleme süresi; yalnız başarılıysa `auth_halted` kalkar. Kaydetmek tek başına kaldırmaz.
* Toplama bayrakları Gelişmiş Ayarlar'dadır (`hw_ipmi_inband_enabled`, `hw_bmc_logs_enabled`; varsayılan KAPALI).
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.core.auth import get_current_user, require_role
from app.core.database import get_db
from app.models.hw import HwBmcEndpoint, HwBmcProfile, HwHostLink, HwServer
from app.models.integration_instance import IntegrationInstance
from app.models.server import Server
from app.models.user import User
from app.services.hw import auth_guard, bmc_creds as BC, bmc_endpoints as EP, bmc_logs, ipmi_inband
from app.services.hw.constants import CATEGORY

router = APIRouter()
_admin = require_role("admin")

_HOST_RE = re.compile(r"^[A-Za-z0-9_.:\-\[\]]{1,253}$")


def _valid_host(v: str) -> str:
    h = (v or "").strip()
    if not h or not _HOST_RE.match(h) or "://" in h:
        raise HTTPException(422, "Geçersiz BMC adresi (IP veya ana makine adı; protokol/yol olmadan).")
    return h


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _profiles(db: Session) -> List[HwBmcProfile]:
    return db.query(HwBmcProfile).order_by(HwBmcProfile.id).all()


# ── Okuma ─────────────────────────────────────────────────────────────────────────────────────────────────────────
@router.get("/overview")
def overview(db: Session = Depends(get_db), _u: User = Depends(get_current_user)):
    from app.api.hw import _classify_all, _scope
    from app.core.auth import user_has_module
    if not user_has_module(_u, "hardware", db):
        raise HTTPException(403, "BMC bilgileri için `hardware` modülü yetkisi gerekir.")
    EP.sync_endpoints(db)
    db.commit()
    mode, scope_ids, _ = _scope(db)
    profiles = _profiles(db)
    insts = {r.id: (r.label or r.endpoint) for r in db.query(IntegrationInstance).filter(
        IntegrationInstance.category == CATEGORY).all()}
    hws = {h.id: h for h in db.query(HwServer).all()}
    servers = {s.id: s for s in db.query(Server).all()}
    links = {l.hw_server_id: l for l in db.query(HwHostLink).all()}
    classes = _classify_all(db, [i for i in scope_ids]) if scope_ids else {}
    eps = db.query(HwBmcEndpoint).order_by(HwBmcEndpoint.id).all()
    srv_ep = {e.target_id: e for e in eps if e.target_kind == "server"}
    rows: List[Dict[str, Any]] = []
    for ep in eps:
        hs = hws.get(ep.target_id) if ep.target_kind == "hw" else None
        if ep.target_kind == "hw" and hs is None:
            continue
        if ep.target_kind == "server" and servers.get(ep.target_id) is None:
            continue
        if ep.target_kind == "server" and any(l.target_kind == "server" and l.target_id == ep.target_id for l in links.values()):
            continue                      # portal kaydına bağlı Linux sunucu: satır portal kaydında
        res = BC.resolve(ep, vendor=(ep.vendor or (hs.vendor if hs else None)),
                         instance_id=(hs.instance_id if hs else None), profiles=profiles)
        name = hs.name if hs else servers[ep.target_id].name
        ipmi_ep = ep
        if hs is not None:
            lk = links.get(hs.id)
            if lk is not None and lk.target_kind == "server":
                ipmi_ep = srv_ep.get(lk.target_id) or ep
        rows.append({
            "id": ep.id, "target": {"kind": ep.target_kind, "id": ep.target_id, "name": name},
            "host_class": (classes.get(ep.target_id, "physical") if hs is not None else "physical"),
            "vendor": ep.vendor or (hs.vendor if hs else None), "model": (hs.model if hs else None),
            "bmc_ip": ep.bmc_ip, "ip_source": ep.ip_source, "enabled": bool(ep.enabled),
            "profile_id": ep.profile_id,
            "resolved": ({"id": res.profile.id, "name": res.profile.name, "level": res.level,
                          "private": EP.is_private(res.profile),
                          "username": BC.username_of(res.profile)} if res.profile is not None else None),
            # Bu makineye ÖZEL hesap (varsa) — parola yok
            "account": ({"username": BC.username_of(res.profile), "has_password": bool(BC.load(res.profile)[1]),
                         "verify_tls": bool(res.profile.verify_tls)}
                        if (res.profile is not None and EP.is_private(res.profile)) else None),
            "status": ep.status, "last_error": ep.last_error, "auth_halted": bool(ep.auth_halted),
            "last_run_at": _iso(ep.last_run_at), "last_ok_at": _iso(ep.last_ok_at),
            "ipmi_status": ipmi_ep.ipmi_status, "ipmi_run_at": _iso(ipmi_ep.ipmi_run_at),
            "instance": insts.get(hs.instance_id) if hs else None,
        })
    by_status: Dict[str, int] = {}
    for r in rows:
        key = "auth_halted" if r["auth_halted"] else (r["status"] or "never")
        by_status[key] = by_status.get(key, 0) + 1
    return {
        "ok": True, "demo": mode == "demo",
        "flags": {"ipmi_inband": ipmi_inband.enabled(), "bmc_redfish": bmc_logs.enabled()},
        "profiles": [BC.public_dict(p) | {"instance_label": insts.get(p.instance_id)} for p in profiles
                     if not EP.is_private(p)],       # makineye özel hesaplar listede/atama menüsünde görünmez
        "endpoints": rows, "counts": {"total": len(rows), "by_status": by_status,
                                      "no_ip": sum(1 for r in rows if not r["bmc_ip"])},
        "instances": [{"id": i, "label": l} for i, l in sorted(insts.items())],
        "test_cooldown_sec": auth_guard.TEST_COOLDOWN_SEC,
        "note": "BMC'ye doğrudan bağlantı için ainew sunucusundan her iLO/iDRAC adresine TCP 443 erişimi ve salt-okunur bir "
                "BMC hesabı gerekir. Kimlik reddedilirse o BMC durur (hesap kilitlenmesin); «Bağlantıyı test et» sürdürür.",
    }


# ── Profil yazma (admin) ──────────────────────────────────────────────────────────────────────────────────────────
class ProfileBody(BaseModel):
    name: str = Field("", max_length=128)
    scope: str = Field("global", pattern="^(global|vendor|instance|host)$")
    vendor: Optional[str] = Field(None, pattern="^(dell|hpe)$")
    instance_id: Optional[int] = None
    username: str = Field("", max_length=255)
    password: Optional[str] = None            # boş → mevcut korunur
    verify_tls: bool = False


def _find_existing(db: Session, b: ProfileBody) -> Optional[HwBmcProfile]:
    q = db.query(HwBmcProfile).filter(HwBmcProfile.scope == b.scope)
    if b.scope == "vendor":
        return q.filter(HwBmcProfile.vendor == b.vendor).first()
    if b.scope == "instance":
        return q.filter(HwBmcProfile.instance_id == b.instance_id).first()
    if b.scope == "global":
        return q.first()
    return None


@router.post("/profiles")
def save_profile(body: ProfileBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    """global / vendor / instance profili UPSERT'tir (kapsam başına tek); `host` profilleri adlandırılmış ve çoktur."""
    if body.scope == "vendor" and not body.vendor:
        raise HTTPException(422, "Üretici profili için vendor (dell|hpe) gerekli.")
    if body.scope == "instance":
        if body.instance_id is None or not db.query(IntegrationInstance).filter(
                IntegrationInstance.id == body.instance_id, IntegrationInstance.category == CATEGORY).first():
            raise HTTPException(422, "Portal entegrasyonu bulunamadı.")
    if body.scope == "host" and not body.name.strip():
        raise HTTPException(422, "Host profili için ad gerekli.")
    if body.name.strip().startswith(EP.PRIVATE_PREFIX):
        raise HTTPException(422, f"«{EP.PRIVATE_PREFIX}» öneki sistem tarafından kullanılır; başka bir ad seçin.")
    p = _find_existing(db, body)
    if p is None:
        if not body.username.strip() or not body.password:
            raise HTTPException(422, "Yeni profil için kullanıcı adı ve parola gerekli.")
        p = HwBmcProfile(scope=body.scope, vendor=body.vendor if body.scope == "vendor" else None,
                         instance_id=body.instance_id if body.scope == "instance" else None)
        db.add(p)
    p.name = (body.name or {"global": "Global BMC hesabı", "vendor": f"{(body.vendor or '').upper()} BMC hesabı",
                            "instance": "Portal BMC hesabı"}.get(body.scope, "")).strip()[:128]
    BC.store(p, body.username, body.password)
    p.verify_tls = bool(body.verify_tls)
    p.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(p)
    return {"ok": True, "profile": BC.public_dict(p)}


@router.put("/profiles/{pid}")
def update_profile(pid: int, body: ProfileBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    p = db.query(HwBmcProfile).filter(HwBmcProfile.id == pid).first()
    if p is None:
        raise HTTPException(404, "Profil bulunamadı")
    if body.name.strip() and not EP.is_private(p):
        if body.name.strip().startswith(EP.PRIVATE_PREFIX):
            raise HTTPException(422, f"«{EP.PRIVATE_PREFIX}» öneki sistem tarafından kullanılır; başka bir ad seçin.")
        p.name = body.name.strip()[:128]
    if body.username.strip() or body.password:
        BC.store(p, body.username, body.password)
    p.verify_tls = bool(body.verify_tls)
    p.updated_at = datetime.now(timezone.utc)
    db.commit()
    return {"ok": True, "profile": BC.public_dict(p)}


@router.delete("/profiles/{pid}")
def delete_profile(pid: int, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    n = db.query(HwBmcProfile).filter(HwBmcProfile.id == pid).delete(synchronize_session=False)
    db.commit()
    return {"ok": True, "removed": n}


# ── Uç nokta yazma (admin) ────────────────────────────────────────────────────────────────────────────────────────
class EndpointBody(BaseModel):
    target_kind: str = Field(..., pattern="^(server|hw)$")
    target_id: int
    bmc_ip: str
    profile_id: Optional[int] = None
    enabled: bool = True


@router.post("/endpoints")
def create_endpoint(body: EndpointBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    """Elle BMC adresi (ip_source=manual). Hedef mevcut olmalı."""
    ip = _valid_host(body.bmc_ip)
    exists = (db.query(Server.id).filter(Server.id == body.target_id).first() if body.target_kind == "server"
              else db.query(HwServer.id).filter(HwServer.id == body.target_id).first())
    if not exists:
        raise HTTPException(404, "Hedef bulunamadı")
    if body.profile_id is not None and not db.query(HwBmcProfile.id).filter(HwBmcProfile.id == body.profile_id).first():
        raise HTTPException(422, "Profil bulunamadı")
    ep = EP.ensure_endpoint(db, body.target_kind, body.target_id)
    ep.bmc_ip, ep.ip_source, ep.enabled = ip, "manual", bool(body.enabled)
    ep.profile_id = body.profile_id
    db.commit()
    return {"ok": True, "id": ep.id}


class EndpointPatch(BaseModel):
    bmc_ip: Optional[str] = None
    profile_id: Optional[int] = None
    enabled: Optional[bool] = None


@router.put("/endpoints/{eid}")
def update_endpoint(eid: int, body: EndpointPatch, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    ep = db.query(HwBmcEndpoint).filter(HwBmcEndpoint.id == eid).first()
    if ep is None:
        raise HTTPException(404, "Uç nokta bulunamadı")
    sent = body.model_fields_set
    if "bmc_ip" in sent:
        if (body.bmc_ip or "").strip():
            ep.bmc_ip, ep.ip_source = _valid_host(body.bmc_ip or ""), "manual"
        else:                               # elle girişi kaldır → portal/keşif değerine dön
            ep.bmc_ip, ep.ip_source = None, ("portal" if ep.target_kind == "hw" else "discovered")
            EP.sync_endpoints(db)
    if "profile_id" in sent:
        if body.profile_id is not None and not db.query(HwBmcProfile.id).filter(HwBmcProfile.id == body.profile_id).first():
            raise HTTPException(422, "Profil bulunamadı")
        EP.drop_private_if_replaced(db, ep, body.profile_id)     # eski ÖZEL hesap yetim kalmasın
        ep.profile_id = body.profile_id
    if "enabled" in sent and body.enabled is not None:
        ep.enabled = bool(body.enabled)
    db.commit()
    return {"ok": True}


class AccountBody(BaseModel):
    username: str = Field("", max_length=255)
    password: Optional[str] = None            # boş → mevcut özel hesabın parolası korunur
    verify_tls: bool = False
    clear: bool = False                       # True → bu makineye özel hesabı sil


@router.put("/endpoints/{eid}/account")
def set_endpoint_account(eid: int, body: AccountBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    """Bu makineye ÖZEL BMC kullanıcı/parola (öncelik sırasında en üstte). Arkada 1:1 host profili tutulur.
    Kimlik DOĞRULANMAZ (BMC'ye bağlanılmaz); `auth_halted` yalnız başarılı «Bağlantıyı test et» ile kalkar."""
    ep = db.query(HwBmcEndpoint).filter(HwBmcEndpoint.id == eid).first()
    if ep is None:
        raise HTTPException(404, "Uç nokta bulunamadı")
    if body.clear:
        EP.clear_account(db, ep)
    else:
        try:
            EP.set_account(db, ep, body.username, body.password, body.verify_tls)
        except ValueError as e:
            raise HTTPException(422, str(e))
    db.commit()
    return {"ok": True}


class ServerAccountBody(BaseModel):
    server_id: int
    bmc_ip: Optional[str] = None
    username: str = Field("", max_length=255)
    password: Optional[str] = None
    verify_tls: bool = False


@router.post("/server-account")
def set_server_account(body: ServerAccountBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    """Fiziksel sunucu eklerken/düzenlerken isteğe bağlı BMC IP + özel hesap (hepsi boşsa hiçbir şey yazılmaz).
    Sunucu bir portal kaydına bağlıysa uç nokta o portal kaydında tutulur."""
    if not db.query(Server.id).filter(Server.id == body.server_id).first():
        raise HTTPException(404, "Sunucu bulunamadı")
    ip = _valid_host(body.bmc_ip) if (body.bmc_ip or "").strip() else None
    has_acct = bool(body.username.strip() or body.password)
    if ip is None and not has_acct:
        return {"ok": True, "changed": False}
    link = db.query(HwHostLink).filter(HwHostLink.target_kind == "server", HwHostLink.target_id == body.server_id).first()
    ep = EP.ensure_endpoint(db, "hw", link.hw_server_id) if link else EP.ensure_endpoint(db, "server", body.server_id)
    if ip is not None:
        ep.bmc_ip, ep.ip_source = ip, "manual"
    if has_acct:
        try:
            EP.set_account(db, ep, body.username, body.password, body.verify_tls)
        except ValueError as e:
            raise HTTPException(422, str(e))
    db.commit()
    return {"ok": True, "changed": True, "id": ep.id}


@router.get("/server-account/{server_id}")
def get_server_account(server_id: int, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    """Linux sunucu düzenleme paneli için TEK sunucunun BMC durumu (parola YOK; uç nokta yoksa oluşturulmaz).
    `/overview` tüm filoyu döndüğü için çekmecede kullanılmaz."""
    if not db.query(Server.id).filter(Server.id == server_id).first():
        raise HTTPException(404, "Sunucu bulunamadı")
    link = db.query(HwHostLink).filter(HwHostLink.target_kind == "server", HwHostLink.target_id == server_id).first()
    kind, tid = ("hw", link.hw_server_id) if link else ("server", server_id)
    ep = db.query(HwBmcEndpoint).filter(HwBmcEndpoint.target_kind == kind, HwBmcEndpoint.target_id == tid).first()
    if ep is None:
        return {"ok": True, "exists": False, "endpoint_id": None, "bmc_ip": None, "ip_source": None,
                "account": None, "resolved": None, "status": None, "auth_halted": False, "last_error": None}
    hs = db.query(HwServer).filter(HwServer.id == tid).first() if kind == "hw" else None
    res = BC.resolve(ep, vendor=(ep.vendor or (hs.vendor if hs else None)),
                     instance_id=(hs.instance_id if hs else None), profiles=_profiles(db))
    private = res.profile is not None and EP.is_private(res.profile)
    return {
        "ok": True, "exists": True, "endpoint_id": ep.id, "bmc_ip": ep.bmc_ip, "ip_source": ep.ip_source,
        "account": ({"username": BC.username_of(res.profile), "has_password": bool(BC.load(res.profile)[1]),
                     "verify_tls": bool(res.profile.verify_tls)} if private else None),
        "resolved": ({"username": BC.username_of(res.profile), "level": res.level, "private": private}
                     if res.profile is not None else None),
        "status": ep.status, "auth_halted": bool(ep.auth_halted), "last_error": ep.last_error,
    }


class BulkBody(BaseModel):
    ids: List[int] = Field(..., min_length=1, max_length=2000)
    profile_id: Optional[int] = None
    enabled: Optional[bool] = None


@router.post("/endpoints/bulk")
def bulk_endpoints(body: BulkBody, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    """Toplu atama: `profile_id` gönderilirse (null = temizle) tüm seçili uç noktalara uygulanır."""
    sent = body.model_fields_set
    if "profile_id" in sent and body.profile_id is not None and not db.query(HwBmcProfile.id).filter(
            HwBmcProfile.id == body.profile_id).first():
        raise HTTPException(422, "Profil bulunamadı")
    rows = db.query(HwBmcEndpoint).filter(HwBmcEndpoint.id.in_(body.ids)).all()
    for ep in rows:
        if "profile_id" in sent:
            EP.drop_private_if_replaced(db, ep, body.profile_id)
            ep.profile_id = body.profile_id
        if body.enabled is not None:
            ep.enabled = bool(body.enabled)
    db.commit()
    return {"ok": True, "updated": len(rows)}


@router.post("/endpoints/{eid}/test")
def test_endpoint(eid: int, db: Session = Depends(get_db), _u: User = Depends(_admin)):
    """TEK deneme (Redfish kök + Managers). Bekleme süresi + aynı BMC'ye aynı anda tek deneme. Başarılıysa durdurma kalkar."""
    ep = db.query(HwBmcEndpoint).filter(HwBmcEndpoint.id == eid).first()
    if ep is None:
        raise HTTPException(404, "Uç nokta bulunamadı")
    wait = auth_guard.acquire_test_slot(f"bmc:{eid}")
    if wait:
        raise HTTPException(429, f"Hesap kilitlenmesin diye bekleyin: {wait} sn sonra yeniden deneyin.")
    with auth_guard.attempt_lock(f"bmc{eid}") as got:
        if not got:
            raise HTTPException(409, "Bu BMC'ye başka bir deneme sürüyor.")
        return bmc_logs.test_endpoint(db, ep)


@router.post("/sync")
def sync_now(db: Session = Depends(get_db), _u: User = Depends(_admin)):
    """Uç nokta satırlarını portal kayıtları + fiziksel sunucularla eşitler (ağa çıkmaz)."""
    r = EP.sync_endpoints(db)
    db.commit()
    return {"ok": True, **r}
