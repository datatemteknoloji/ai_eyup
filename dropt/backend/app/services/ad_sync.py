"""Sync AD directory users into portal users table."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlmodel import Session, select

from app.models.identity import IdentityConfig
from app.models.user import AuthSource, User, UserRole
from app.services.ad_auth import _make_ldap_server, resolve_role_from_groups
from app.services.identity_store import decrypt_ad_bind_password
from app.services.user_ids import next_directory_id


def list_ad_directory_users(cfg: IdentityConfig, *, limit: int = 500) -> list[dict]:
    """Return raw AD users (sAMAccountName + groups)."""
    from ldap3 import Connection, SUBTREE

    bind_dn = (cfg.ad_bind_dn or "").strip()
    bind_pw = decrypt_ad_bind_password(cfg)
    base_dn = (cfg.ad_base_dn or "").strip()
    if not bind_dn or not bind_pw or not base_dn:
        raise ValueError("AD bind DN / şifre / Base DN gerekli")

    server, _host, _note, _url = _make_ldap_server(cfg)
    conn = Connection(server, user=bind_dn, password=bind_pw, auto_bind=True, receive_timeout=30)
    try:
        # Enabled users only (not ACCOUNTDISABLE bit)
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
            out.append({"username": sam, "groups": groups, "mail": mail})
        out.sort(key=lambda x: x["username"].lower())
        return out
    finally:
        conn.unbind()


def sync_ad_users(session: Session, cfg: IdentityConfig) -> dict:
    """
    Upsert AD users into portal DB.
    - ID range: 10000+
    - Role from Admin/Operator group mapping; else role=none (unauthorized)
    - Existing local usernames are skipped (no overwrite)
    """
    if not cfg.ad_enabled:
        raise ValueError("Active Directory kapalı")

    directory = list_ad_directory_users(cfg)
    created = 0
    updated = 0
    skipped_local = 0

    for item in directory:
        username = item["username"]
        existing = session.exec(select(User).where(User.username == username)).first()
        if existing and existing.auth_source == AuthSource.local and existing.password_hash:
            skipped_local += 1
            continue

        role = resolve_role_from_groups(
            item["groups"],
            admin_group=cfg.ad_admin_group,
            operator_group=cfg.ad_operator_group,
        )
        if role is None:
            role = UserRole.none

        if existing is None:
            user = User(
                id=next_directory_id(session),
                username=username,
                password_hash=None,
                role=role,
                auth_source=AuthSource.ad,
                is_active=role != UserRole.none,
                created_at=datetime.now(UTC),
            )
            session.add(user)
            session.commit()
            created += 1
        else:
            # Keep admin-assigned role if already set and not none? Prefer group mapping on sync.
            existing.auth_source = AuthSource.ad
            existing.password_hash = None
            existing.role = role
            if role == UserRole.none:
                existing.is_active = False
            else:
                existing.is_active = True
            session.add(existing)
            session.commit()
            updated += 1

    return {
        "ok": True,
        "scanned": len(directory),
        "created": created,
        "updated": updated,
        "skipped_local": skipped_local,
    }
