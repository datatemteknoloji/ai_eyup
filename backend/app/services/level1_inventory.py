"""Level 1 / Ops envanter: ainew servers SoT + Dropt ensure (credential ayrımı).

- ainew connection_config → GlobalCredential / form (örn. datatem)
- Dropt TargetServer cred → Level 1 otomasyon (örn. root) — ensure-host
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import httpx
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.core.encryption import encrypt_secret
from app.models.credential import GlobalCredential
from app.models.server import Server

logger = logging.getLogger(__name__)


def _apply_global_connection_config(
    db: Session,
    server: Server,
    *,
    override: Optional[dict] = None,
) -> None:
    """Ainew yönetim SSH — Level 1 otomasyon user'dan bağımsız."""
    cfg: dict[str, Any] = dict(server.connection_config or {})
    if override:
        for k, v in override.items():
            if v is None or v == "":
                continue
            if k in ("password", "private_key", "sudo_password") and isinstance(v, str):
                cfg[k] = encrypt_secret(v) or v
            else:
                cfg[k] = v
    if not cfg.get("username"):
        global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()  # noqa: E712
        if not global_cred:
            global_cred = db.query(GlobalCredential).first()
        if global_cred:
            cfg.setdefault("username", global_cred.username)
            if global_cred.password:
                cfg.setdefault("password", global_cred.password)
            if global_cred.private_key:
                cfg.setdefault("private_key", global_cred.private_key)
            if global_cred.sudo_password or global_cred.password:
                cfg.setdefault(
                    "sudo_password",
                    global_cred.sudo_password or global_cred.password,
                )
            cfg.setdefault("port", global_cred.port or 22)
    server.connection_config = cfg
    flag_modified(server, "connection_config")


def find_server_by_ip_or_hostname(db: Session, *, ip: str, hostname: str) -> Optional[Server]:
    ip = (ip or "").strip()
    hostname = (hostname or "").strip()
    if ip:
        row = db.query(Server).filter(Server.ip_address == ip).first()
        if row:
            return row
    if hostname:
        row = (
            db.query(Server)
            .filter(Server.hostname == hostname)
            .first()
        )
        if row:
            return row
        return db.query(Server).filter(Server.name == hostname).first()
    return None


def create_or_get_ainew_server(
    db: Session,
    *,
    hostname: str,
    ip: str,
    server_type: str = "UNKNOWN",
    os_type: str = "linux",
    name: Optional[str] = None,
    connection_override: Optional[dict] = None,
    source: str = "level1-ops",
) -> tuple[Server, bool]:
    """
    Returns (server, created).
    server_type: PHYSICAL | VIRTUAL | UNKNOWN — genelde detect sonrası set edilir.
    """
    hostname = hostname.strip()
    ip = ip.strip()
    st = (server_type or "UNKNOWN").upper()
    if st not in ("PHYSICAL", "VIRTUAL", "UNKNOWN"):
        st = "UNKNOWN"
    existing = find_server_by_ip_or_hostname(db, ip=ip, hostname=hostname)
    if existing:
        if connection_override:
            _apply_global_connection_config(db, existing, override=connection_override)
        if not existing.os_type and os_type:
            existing.os_type = os_type
        db.commit()
        db.refresh(existing)
        return existing, False

    display = (name or hostname).strip()
    if db.query(Server).filter(Server.name == display).first():
        display = f"{display}-{ip.replace('.', '-')}"

    server = Server(
        name=display,
        hostname=hostname,
        ip_address=ip,
        status="OFFLINE",
        os_type=os_type or "linux",
        server_type=st,
        connection_config={},
    )
    _apply_global_connection_config(db, server, override=connection_override)
    meta = dict(server.connection_config or {})
    meta["_inventory_source"] = source
    server.connection_config = meta
    flag_modified(server, "connection_config")
    db.add(server)
    db.commit()
    db.refresh(server)
    return server, True


def ensure_and_detect(
    db: Session,
    server: Server,
    *,
    dropt_base: str,
    dropt_token: str,
) -> tuple[Optional[int], dict[str, Any]]:
    """Dropt ensure + virt detect (önce otomasyon facts, yoksa ainew SSH)."""
    from app.services.virt_detect import probe_and_apply

    dropt_id: Optional[int] = None
    try:
        result = ensure_dropt_for_server(
            dropt_base=dropt_base,
            dropt_token=dropt_token,
            server=server,
            skip_connection_test=False,
        )
        dropt_id = int(result["id"]) if result.get("id") is not None else None
        if (result.get("status") or "").lower() == "unreachable" and dropt_id:
            try:
                with httpx.Client(timeout=20.0) as client:
                    client.delete(
                        f"{dropt_base.rstrip('/')}/api/servers/{dropt_id}",
                        headers={"Authorization": f"Bearer {dropt_token}"},
                    )
            except Exception as del_exc:  # noqa: BLE001
                logger.warning("Dropt unreachable silinemedi id=%s: %s", dropt_id, del_exc)
            detect = probe_and_apply(db, server, prefer_dropt=False)
            return None, {
                "ensure_error": "otomasyon SSH unreachable — Level 1'e eklenmedi",
                **detect,
            }
    except Exception as exc:  # noqa: BLE001
        logger.warning("ensure failed: %s", exc)
        detect = probe_and_apply(db, server, prefer_dropt=False)
        return None, {"ensure_error": str(exc), **detect}

    detect = probe_and_apply(
        db,
        server,
        dropt_base=dropt_base,
        dropt_token=dropt_token,
        dropt_server_id=dropt_id,
        prefer_dropt=True,
    )
    return dropt_id, detect


def ensure_dropt_for_server(
    *,
    dropt_base: str,
    dropt_token: str,
    server: Server,
    skip_connection_test: bool = False,
) -> dict[str, Any]:
    """Dropt ensure-host — otomasyon credential; ainew SSH'ı değiştirmez.

    skip_connection_test=False: otomasyon user ile dener (ready/unreachable).
    Unreachable yeni kayıtlar çağıran tarafta silinebilir.
    """
    hostname = (server.hostname or server.vm_guest_hostname or server.name or server.ip_address or "").strip()
    ip = (server.ip_address or "").strip()
    if not ip:
        raise ValueError("IP yok")
    with httpx.Client(timeout=60.0) as client:
        cr = client.post(
            f"{dropt_base.rstrip('/')}/api/servers/ensure-host",
            headers={
                "Authorization": f"Bearer {dropt_token}",
                "Content-Type": "application/json",
            },
            json={
                "hostname": hostname,
                "ip": ip,
                "port": 22,
                "description": f"ainew:{server.id} {(server.name or '').strip()}".strip()[:512],
                "skip_connection_test": skip_connection_test,
            },
        )
    if cr.status_code >= 400:
        raise RuntimeError(f"Dropt ensure-host: {cr.text[:400]}")
    return cr.json()


def bridge_dropt_token(*, dropt_base: str, bridge_secret: str, username: str = "ainew-sync", role: str = "admin") -> str:
    with httpx.Client(timeout=20.0) as client:
        r = client.post(
            f"{dropt_base.rstrip('/')}/api/auth/bridge",
            headers={"X-Ainew-Bridge-Secret": bridge_secret, "Content-Type": "application/json"},
            json={"username": username, "role": role, "full_name": "ainew inventory sync"},
        )
    if r.status_code >= 400:
        raise RuntimeError(f"Dropt bridge: {r.text[:300]}")
    token = (r.json().get("token") or {}).get("access_token")
    if not token:
        raise RuntimeError("Dropt bridge token yok")
    return str(token)


def best_effort_ensure_after_ainew_create(server: Server, *, actor_username: str = "ainew") -> None:
    """Fiziksel Host / entegrasyon create sonrası Dropt projeksiyon + tip detect."""
    import os

    from app.core.database import SessionLocal
    from app.services.virt_detect import probe_and_apply

    secret = (os.getenv("AINEW_BRIDGE_SECRET") or "").strip()
    base = (os.getenv("DROPT_API_URL") or "http://127.0.0.1:8001").rstrip("/")
    if not server.ip_address:
        return

    db = SessionLocal()
    try:
        # Yeniden yükle (aynı session dışında çağrılabilir)
        row = db.query(Server).filter(Server.id == server.id).first()
        if not row:
            return
        dropt_id = None
        token = None
        if secret:
            try:
                token = bridge_dropt_token(
                    dropt_base=base,
                    bridge_secret=secret,
                    username=f"sync-{actor_username}"[:64],
                )
                result = ensure_dropt_for_server(
                    dropt_base=base, dropt_token=token, server=row, skip_connection_test=False,
                )
                dropt_id = int(result["id"]) if result.get("id") is not None else None
                if (result.get("status") or "").lower() == "unreachable" and dropt_id:
                    with httpx.Client(timeout=20.0) as client:
                        client.delete(
                            f"{base}/api/servers/{dropt_id}",
                            headers={"Authorization": f"Bearer {token}"},
                        )
                    dropt_id = None
            except Exception as exc:  # noqa: BLE001
                logger.warning("best_effort Dropt ensure failed for server %s: %s", server.id, exc)
        # Tip: önce Dropt facts (otomasyon), yoksa ainew SSH
        if (row.server_type or "").upper() in ("", "UNKNOWN", "PHYSICAL", "VIRTUAL") and not row.hypervisor_id:
            probe_and_apply(
                db,
                row,
                dropt_base=base if token else "",
                dropt_token=token or "",
                dropt_server_id=dropt_id,
                prefer_dropt=bool(token and dropt_id),
            )
    finally:
        db.close()