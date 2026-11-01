"""Faz 3b — BMC uç noktası kayıtları (hw_bmc_endpoints): oluşturma/eşitleme + log hedefi çözümü.

IP önceliği: manual > portal (hw_servers.bmc_ip) > discovered (ipmitool lan print). Hedef türleri:
  `hw`     portal kaydı (hw_servers.id)           — Dell/HPE portalından gelen tekil/şasi sunucu
  `server` Linux sayfasındaki fiziksel sunucu      — portal kaydı yok (veya bağlı değil)
Log hedefi: portal kaydı bir Linux sunucuya/hypervisor host'una BAĞLIysa log o hedefe, değilse `hw` hedefine yazılır.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.hw import HwBmcEndpoint, HwBmcProfile, HwHostLink, HwServer

logger = logging.getLogger(__name__)

IP_SOURCES = ("manual", "portal", "discovered")

# «Bu makineye özel hesap»: arkada 1:1 bir host profili (scope=host) tutulur; kullanıcı «profil» kavramını görmez.
# Ad kuralı (şema değişikliği gerektirmez): `endpoint:<uç nokta id>`. Paylaşılan (adlandırılmış) host profillerinden ayrılır.
PRIVATE_PREFIX = "endpoint:"


def private_name(ep_id: int) -> str:
    return f"{PRIVATE_PREFIX}{ep_id}"


def is_private(profile: Any) -> bool:
    return bool(profile is not None and (getattr(profile, "name", "") or "").startswith(PRIVATE_PREFIX))


def private_profile(db: Session, ep: HwBmcEndpoint) -> Optional[HwBmcProfile]:
    """Uç noktaya şu an bağlı profil ÖZEL ise onu döner (paylaşılan profil → None)."""
    if ep.profile_id is None:
        return None
    p = db.query(HwBmcProfile).filter(HwBmcProfile.id == ep.profile_id).first()
    return p if (p is not None and p.name == private_name(ep.id)) else None


def set_account(db: Session, ep: HwBmcEndpoint, username: str, password: Optional[str], verify_tls: bool) -> HwBmcProfile:
    """Bu uç noktaya özel kullanıcı/parola. Parola boşsa mevcut özel hesapta korunur; YENİ hesapta ikisi de gerekir.
    Paylaşılan bir profil atanmışsa onun yerine özel hesap atanır (paylaşılan profile dokunulmaz). Çağıran commit eder."""
    from app.services.hw import bmc_creds as BC

    p = private_profile(db, ep)
    user = (username or "").strip()
    if p is None:
        if not user or not password:
            raise ValueError("BMC hesabı için kullanıcı adı ve parola birlikte girilmeli.")
        p = HwBmcProfile(scope="host", name=private_name(ep.id))
        db.add(p)
        db.flush()
    BC.store(p, user, password)
    p.verify_tls = bool(verify_tls)
    ep.profile_id = p.id
    return p


def clear_account(db: Session, ep: HwBmcEndpoint) -> bool:
    p = private_profile(db, ep)
    if p is None:
        return False
    ep.profile_id = None
    db.flush()
    db.delete(p)
    return True


def drop_private_if_replaced(db: Session, ep: HwBmcEndpoint, new_profile_id: Optional[int]) -> None:
    """Uç noktaya BAŞKA bir profil atanırken (veya temizlenirken) eski özel hesap yetim kalmasın."""
    p = private_profile(db, ep)
    if p is not None and p.id != new_profile_id:
        ep.profile_id = new_profile_id
        db.flush()
        db.delete(p)


def ensure_endpoint(db: Session, kind: str, tid: int) -> HwBmcEndpoint:
    ep = db.query(HwBmcEndpoint).filter(HwBmcEndpoint.target_kind == kind, HwBmcEndpoint.target_id == tid).first()
    if ep is None:
        ep = HwBmcEndpoint(target_kind=kind, target_id=tid, ip_source=("portal" if kind == "hw" else "discovered"),
                           enabled=True, status="never", auth_halted=False)
        db.add(ep)
        db.flush()
    return ep


def sync_endpoints(db: Session) -> Dict[str, int]:
    """Gerçek portal kayıtları (DEMO değil) ve fiziksel Linux/Windows sunucular için uç nokta satırı garanti eder;
    portal IP'sini (manuel değilse) uygular. Bağlı bir hw kaydı varsa o sunucu için ayrı `server` satırı AÇILMAZ."""
    from app.models.server import Server
    from app.services.hw.demo_gate import active_instances

    created = updated = 0
    ids = [r.id for r in active_instances(db, include_demo=False)]
    existing = {(e.target_kind, e.target_id): e for e in db.query(HwBmcEndpoint).all()}
    linked_servers = {l.target_id for l in db.query(HwHostLink).filter(HwHostLink.target_kind == "server").all()}
    if ids:
        for hs in db.query(HwServer).filter(HwServer.instance_id.in_(ids)).all():
            ep = existing.get(("hw", hs.id))
            if ep is None:
                ep = HwBmcEndpoint(target_kind="hw", target_id=hs.id, ip_source="portal", enabled=True, status="never",
                                   auth_halted=False)
                db.add(ep)
                existing[("hw", hs.id)] = ep
                created += 1
            if ep.ip_source != "manual":
                if (hs.bmc_ip or None) != (ep.bmc_ip or None) or ep.ip_source != "portal":
                    ep.bmc_ip, ep.ip_source = (hs.bmc_ip or None), "portal"
                    updated += 1
            if hs.vendor and not ep.vendor:
                ep.vendor = hs.vendor
    for s in db.query(Server).all():
        if (s.server_type or "").upper() != "PHYSICAL" or s.id in linked_servers:
            continue
        if ("server", s.id) not in existing:
            ep = HwBmcEndpoint(target_kind="server", target_id=s.id, ip_source="discovered", enabled=True,
                               status="never", auth_halted=False)
            db.add(ep)
            existing[("server", s.id)] = ep
            created += 1
    db.flush()
    # Kaynağı silinmiş (portal kaydı / sunucu) uç noktalar yetim kalmasın
    hw_ids = {i for (i,) in db.query(HwServer.id).all()}
    srv_ids = {i for (i,) in db.query(Server.id).all()}
    removed = 0
    for (k, i), ep in list(existing.items()):
        if (k == "hw" and i not in hw_ids) or (k == "server" and i not in srv_ids):
            db.delete(ep)
            removed += 1
    db.flush()
    # Uç noktası kalmayan özel hesaplar da silinir (parola artığı kalmasın)
    live = {private_name(i) for (i,) in db.query(HwBmcEndpoint.id).all()}
    for p in db.query(HwBmcProfile).filter(HwBmcProfile.name.like(f"{PRIVATE_PREFIX}%")).all():
        if p.name not in live:
            db.delete(p)
    db.flush()
    return {"created": created, "updated": updated, "removed": removed}


def log_target(db: Session, ep: HwBmcEndpoint) -> Tuple[str, int]:
    """Bu uç noktanın log kayıtlarının yazılacağı hedef (target_kind, target_id)."""
    if ep.target_kind == "server":
        return "server", ep.target_id
    link = db.query(HwHostLink).filter(HwHostLink.hw_server_id == ep.target_id).first()
    if link is not None:
        return link.target_kind, link.target_id
    return "hw", ep.target_id
