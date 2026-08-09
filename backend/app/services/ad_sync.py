"""AD dizin kullanıcılarını ainew users tablosuna senkronize et.

Yetkilendirme ainew Kullanıcı Yönetimi'ndedir — AD grupları zorunlu değildir.
Opsiyonel Admin/Operator/Viewer grupları yalnızca *yeni* kullanıcıya varsayılan rol önerir.
"""
from __future__ import annotations

from sqlalchemy.orm import Session

from app.models.identity import IdentityConfig
from app.models.user import User
from app.services.ad_auth import make_ldap_server, resolve_role_from_groups
from app.services.identity_store import decrypt_ad_bind_password


def list_ad_directory_users(cfg: IdentityConfig, *, limit: int = 500) -> list[dict]:
    from ldap3 import SUBTREE, Connection

    bind_dn = (cfg.ad_bind_dn or "").strip()
    bind_pw = decrypt_ad_bind_password(cfg)
    base_dn = (cfg.ad_base_dn or "").strip()
    if not bind_dn or not bind_pw or not base_dn:
        raise ValueError("AD bind DN / şifre / Base DN gerekli")

    server, _host, _note, _url = make_ldap_server(cfg)
    conn = Connection(server, user=bind_dn, password=bind_pw, auto_bind=True, receive_timeout=30)
    try:
        search_filter = (
            "(&(objectCategory=person)(objectClass=user)"
            "(!(userAccountControl:1.2.840.113556.1.4.803:=2)))"
        )
        conn.search(
            search_base=base_dn,
            search_filter=search_filter,
            search_scope=SUBTREE,
            attributes=["sAMAccountName", "memberOf", "mail", "displayName"],
            size_limit=limit,
        )
        out: list[dict] = []
        for entry in conn.entries:
            sam = ""
            if hasattr(entry, "sAMAccountName") and entry.sAMAccountName:
                sam = str(entry.sAMAccountName)
            if not sam or sam.endswith("$"):
                continue
            groups: list[str] = []
            if hasattr(entry, "memberOf") and entry.memberOf:
                groups = [str(x) for x in entry.memberOf.values]
            mail = ""
            if hasattr(entry, "mail") and entry.mail:
                mail = str(entry.mail)
            display = ""
            if hasattr(entry, "displayName") and entry.displayName:
                display = str(entry.displayName)
            out.append({
                "username": sam,
                "groups": groups,
                "mail": mail,
                "full_name": display,
            })
        out.sort(key=lambda x: x["username"].lower())
        return out
    finally:
        conn.unbind()


def _suggested_role(cfg: IdentityConfig, groups: list[str]) -> str:
    """Opsiyonel AD grup eşlemesi; yoksa viewer."""
    role = resolve_role_from_groups(
        groups,
        admin_group=cfg.ad_admin_group or "",
        operator_group=cfg.ad_operator_group or "",
        viewer_group=cfg.ad_viewer_group or "",
    )
    return role or "viewer"


def sync_ad_users(db: Session, cfg: IdentityConfig) -> dict:
    """
    Base DN altındaki etkin AD kullanıcılarını Kullanıcı Yönetimi'ne getir.

    - Local + parola kullanıcıları asla üzerine yazılmaz
    - Yeni AD kullanıcıları: auth_source=ad, varsayılan rol viewer
      (opsiyonel grup alanları doluysa önerilen rol)
    - Mevcut AD kullanıcıları: profil (mail/ad) güncellenir; **rol/modül ezilmez**
    - Dizinde artık olmayan AD kullanıcıları pasifleştirilir
    """
    if not cfg.ad_enabled:
        raise ValueError("Active Directory kapalı")

    directory = list_ad_directory_users(cfg)
    created = 0
    updated = 0
    skipped_local = 0
    deactivated = 0
    synced_usernames: set[str] = set()

    for item in directory:
        username = item["username"]
        synced_usernames.add(username.lower())

        existing = db.query(User).filter(User.username == username).first()
        if existing and (existing.auth_source or "local") == "local" and existing.hashed_password:
            skipped_local += 1
            continue

        suggested = _suggested_role(cfg, item.get("groups") or [])

        if existing is None:
            u = User(
                username=username,
                email=item.get("mail") or None,
                full_name=item.get("full_name") or None,
                hashed_password=None,
                role=suggested,
                auth_source="ad",
                is_active=True,
            )
            db.add(u)
            created += 1
        else:
            existing.auth_source = "ad"
            existing.hashed_password = None
            # Rolü koru — yetki Kullanıcı Yönetimi'nde
            if not existing.is_active:
                # Dizinde yeniden görüneni aç (admin pasife almış olabilir; sync aktif eder)
                # Kullanıcı bilerek pasife aldıysa tekrar sync açar — tercih: aktif tut
                existing.is_active = True
            if item.get("mail"):
                existing.email = item["mail"]
            if item.get("full_name"):
                existing.full_name = item["full_name"]
            updated += 1

    # Dizinde kalmayan AD kullanıcılarını pasifleştir
    ad_users = db.query(User).filter(User.auth_source == "ad").all()
    for u in ad_users:
        if u.username.lower() not in synced_usernames and u.is_active:
            u.is_active = False
            deactivated += 1

    db.commit()
    return {
        "ok": True,
        "scanned": len(directory),
        "matched": len(synced_usernames),
        "created": created,
        "updated": updated,
        "skipped_local": skipped_local,
        "deactivated": deactivated,
    }


def upsert_ad_user_jit(
    db: Session,
    *,
    username: str,
    role: str,
    email: str = "",
    full_name: str = "",
) -> User:
    """İlk başarılı AD login'de kullanıcı oluştur / güncelle (JIT)."""
    existing = db.query(User).filter(User.username == username).first()
    if existing and (existing.auth_source or "local") == "local" and existing.hashed_password:
        raise ValueError("Bu kullanıcı adı local hesapla çakışıyor")
    if existing is None:
        existing = User(
            username=username,
            email=email or None,
            full_name=full_name or None,
            hashed_password=None,
            role=role or "viewer",
            auth_source="ad",
            is_active=True,
        )
        db.add(existing)
    else:
        existing.auth_source = "ad"
        existing.hashed_password = None
        # Mevcut rolü koru
        if email:
            existing.email = email
        if full_name:
            existing.full_name = full_name
        existing.is_active = True
    db.commit()
    db.refresh(existing)
    return existing
