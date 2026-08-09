"""Active Directory / LDAP authentication helpers."""

from __future__ import annotations

import os
import socket
import ssl
from dataclasses import dataclass, field
from pathlib import Path

from app.models.identity import IdentityConfig
from app.models.user import UserRole
from app.services.identity_store import build_ldap_url, decrypt_ad_bind_password, sync_ldap_url_from_parts

HOST_ETC_HOSTS = Path(os.environ.get("HOST_ETC_HOSTS", "/host-etc-hosts"))


@dataclass
class AdAuthResult:
    ok: bool
    message: str
    username: str = ""
    role: UserRole | None = None
    groups: list[str] = field(default_factory=list)
    resolved_host: str = ""
    ldap_url: str = ""


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def _group_match(member_of: list[str], needle: str) -> bool:
    n = _norm(needle)
    if not n:
        return False
    for g in member_of:
        gl = _norm(g)
        if gl == n or n in gl or gl.endswith(f"cn={n},") or f"cn={n}," in gl:
            return True
        if gl.startswith("cn="):
            cn = gl.split(",", 1)[0][3:]
            if cn == n:
                return True
    return False


def resolve_role_from_groups(
    groups: list[str],
    *,
    admin_group: str,
    operator_group: str,
) -> UserRole | None:
    if _group_match(groups, admin_group):
        return UserRole.admin
    if _group_match(groups, operator_group):
        return UserRole.operator
    return None


def _lookup_host_etc_hosts(hostname: str) -> str | None:
    """Resolve name via mounted host /etc/hosts (dynamic — no compose edits per AD)."""
    if not HOST_ETC_HOSTS.is_file():
        return None
    target = _norm(hostname)
    try:
        text = HOST_ETC_HOSTS.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        ip, *names = parts
        if any(_norm(n) == target for n in names):
            return ip
    return None


def resolve_ad_connect_host(hostname: str) -> tuple[str, str]:
    """
    Returns (connect_target, note).
    Prefer normal DNS; fall back to host OS /etc/hosts mount.
    """
    host = (hostname or "").strip()
    if not host:
        return "", "AD host boş"
    try:
        socket.getaddrinfo(host, None)
        return host, f"DNS OK: {host}"
    except OSError:
        pass
    mapped = _lookup_host_etc_hosts(host)
    if mapped:
        return mapped, f"Host /etc/hosts: {host} → {mapped}"
    return host, f"Uyarı: {host} çözülemedi (DNS + host /etc/hosts)"


def _make_ldap_server(cfg: IdentityConfig):
    from ldap3 import ALL, Server, Tls

    sync_ldap_url_from_parts(cfg)
    host = (cfg.ad_host or "").strip()
    if not host and cfg.ad_ldap_url:
        # last resort parse
        sync_ldap_url_from_parts(cfg)
        host = (cfg.ad_host or "").strip()
    if not host:
        raise ValueError("AD sunucu adresi (host) tanımlı değil")

    use_ssl = bool(cfg.ad_use_ssl)
    port = int(cfg.ad_port or (636 if use_ssl else 389))
    connect_host, resolve_note = resolve_ad_connect_host(host)
    ldap_url = build_ldap_url(host=host, port=port, use_ssl=use_ssl)

    tls = None
    if use_ssl:
        ca = (cfg.ad_ca_cert_pem or "").strip() or None
        verify = bool(cfg.ad_tls_verify) and bool(ca)
        # Without CA: never hard-fail on cert (lab-friendly, like other app)
        validate = ssl.CERT_REQUIRED if verify else ssl.CERT_NONE
        tls_kwargs: dict = {
            "validate": validate,
            "version": ssl.PROTOCOL_TLS_CLIENT,
        }
        if ca:
            tls_kwargs["ca_certs_data"] = ca
        # When connecting via IP from hosts file, still accept original hostname on cert
        if connect_host != host:
            tls_kwargs["valid_names"] = [host, connect_host]
        tls = Tls(**tls_kwargs)

    server = Server(
        connect_host,
        port=port,
        use_ssl=use_ssl,
        tls=tls,
        get_info=ALL,
        connect_timeout=8,
    )
    return server, connect_host, resolve_note, ldap_url


def authenticate_ad(
    cfg: IdentityConfig,
    username: str,
    password: str,
) -> AdAuthResult:
    if not cfg.ad_enabled:
        return AdAuthResult(ok=False, message="Active Directory kapalı")
    if not username.strip() or not password:
        return AdAuthResult(ok=False, message="Kullanıcı adı / şifre gerekli")

    try:
        from ldap3 import Connection, SUBTREE
        from ldap3.core.exceptions import LDAPException
    except ImportError:
        return AdAuthResult(ok=False, message="ldap3 kurulu değil")

    user = username.strip()
    domain = (cfg.ad_domain or "").strip()
    base_dn = (cfg.ad_base_dn or "").strip()
    filt_tpl = cfg.ad_user_filter or "(|(sAMAccountName={username})(userPrincipalName={username}))"
    user_filter = filt_tpl.replace("{username}", user.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)"))

    candidates: list[str] = []
    if "@" in user:
        candidates.append(user)
    elif domain:
        candidates.append(f"{user}@{domain}")
        candidates.append(f"{domain}\\{user}")
    else:
        candidates.append(user)

    try:
        server, connect_host, resolve_note, ldap_url = _make_ldap_server(cfg)
    except Exception as exc:  # noqa: BLE001
        return AdAuthResult(ok=False, message=f"LDAP sunucu hatası: {exc}")

    bind_dn = (cfg.ad_bind_dn or "").strip()
    bind_pw = decrypt_ad_bind_password(cfg)
    groups: list[str] = []

    try:
        if bind_dn and bind_pw and base_dn:
            svc = Connection(server, user=bind_dn, password=bind_pw, auto_bind=True, receive_timeout=10)
            svc.search(
                search_base=base_dn,
                search_filter=user_filter,
                search_scope=SUBTREE,
                attributes=["distinguishedName", "sAMAccountName", "memberOf", "userPrincipalName"],
                size_limit=1,
            )
            if not svc.entries:
                svc.unbind()
                return AdAuthResult(
                    ok=False,
                    message="AD kullanıcısı bulunamadı",
                    resolved_host=connect_host,
                    ldap_url=ldap_url,
                )
            entry = svc.entries[0]
            entry_dn = str(entry.distinguishedName) if hasattr(entry, "distinguishedName") else str(entry.entry_dn)
            if hasattr(entry, "memberOf") and entry.memberOf:
                groups = [str(x) for x in entry.memberOf.values]
            svc.unbind()
            candidates.insert(0, entry_dn)

        authed = False
        last_err = ""
        for cand in candidates:
            try:
                conn = Connection(server, user=cand, password=password, auto_bind=True, receive_timeout=10)
                authed = True
                if not groups and base_dn:
                    conn.search(
                        search_base=base_dn,
                        search_filter=user_filter,
                        search_scope=SUBTREE,
                        attributes=["memberOf", "sAMAccountName"],
                        size_limit=1,
                    )
                    if conn.entries and hasattr(conn.entries[0], "memberOf") and conn.entries[0].memberOf:
                        groups = [str(x) for x in conn.entries[0].memberOf.values]
                conn.unbind()
                break
            except LDAPException as exc:
                last_err = str(exc)
                continue
            except Exception as exc:  # noqa: BLE001
                last_err = str(exc)
                continue

        if not authed:
            return AdAuthResult(
                ok=False,
                message=f"AD kimlik doğrulama başarısız: {last_err or 'invalid credentials'} ({resolve_note})",
                resolved_host=connect_host,
                ldap_url=ldap_url,
            )

        role = resolve_role_from_groups(
            groups,
            admin_group=cfg.ad_admin_group,
            operator_group=cfg.ad_operator_group,
        )
        if role is None:
            return AdAuthResult(
                ok=False,
                message="AD girişi başarılı ama Admin/Operator grubunda değil",
                username=user,
                groups=groups,
                resolved_host=connect_host,
                ldap_url=ldap_url,
            )
        return AdAuthResult(
            ok=True,
            message=f"AD kimlik doğrulama başarılı ({resolve_note})",
            username=user.split("@")[0].split("\\")[-1],
            role=role,
            groups=groups,
            resolved_host=connect_host,
            ldap_url=ldap_url,
        )
    except Exception as exc:  # noqa: BLE001
        return AdAuthResult(
            ok=False,
            message=f"AD hatası: {exc} ({resolve_note})",
            resolved_host=connect_host,
            ldap_url=ldap_url,
        )


def test_ad_bind(cfg: IdentityConfig) -> AdAuthResult:
    """Test service-account bind only."""
    bind_dn = (cfg.ad_bind_dn or "").strip()
    bind_pw = decrypt_ad_bind_password(cfg)
    if not bind_dn or not bind_pw:
        return AdAuthResult(ok=False, message="Service account DN / şifre gerekli")
    try:
        from ldap3 import Connection
    except ImportError:
        return AdAuthResult(ok=False, message="ldap3 kurulu değil")
    try:
        server, connect_host, resolve_note, ldap_url = _make_ldap_server(cfg)
        conn = Connection(server, user=bind_dn, password=bind_pw, auto_bind=True, receive_timeout=10)
        conn.unbind()
        return AdAuthResult(
            ok=True,
            message=f"Service account bağlantısı başarılı ({resolve_note})",
            resolved_host=connect_host,
            ldap_url=ldap_url,
        )
    except Exception as exc:  # noqa: BLE001
        return AdAuthResult(ok=False, message=f"Bağlantı başarısız: {exc}")
