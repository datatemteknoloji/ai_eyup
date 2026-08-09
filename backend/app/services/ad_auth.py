"""Active Directory / LDAP authentication helpers."""
from __future__ import annotations

import ssl
from dataclasses import dataclass, field

from app.models.identity import IdentityConfig
from app.services.host_resolve import resolve_connect_host
from app.services.identity_store import build_ldap_url, decrypt_ad_bind_password


@dataclass
class AdAuthResult:
    ok: bool
    message: str
    username: str = ""
    role: str | None = None
    groups: list[str] = field(default_factory=list)
    email: str = ""
    full_name: str = ""
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
    viewer_group: str = "",
) -> str | None:
    if _group_match(groups, admin_group):
        return "admin"
    if _group_match(groups, operator_group):
        return "operator"
    if _group_match(groups, viewer_group):
        return "viewer"
    return None


def resolve_ad_connect_host(hostname: str) -> tuple[str, str]:
    """AD host çözümleme — DNS sonra host /etc/hosts (host_resolve)."""
    return resolve_connect_host(hostname)

def make_ldap_server(cfg: IdentityConfig):
    from ldap3 import ALL, Server, Tls

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
        validate = ssl.CERT_REQUIRED if verify else ssl.CERT_NONE
        tls_kwargs: dict = {
            "validate": validate,
            "version": ssl.PROTOCOL_TLS_CLIENT,
        }
        if ca:
            tls_kwargs["ca_certs_data"] = ca
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


def authenticate_ad(cfg: IdentityConfig, username: str, password: str) -> AdAuthResult:
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
    user_filter = filt_tpl.replace(
        "{username}", user.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    )

    candidates: list[str] = []
    if "@" in user:
        candidates.append(user)
    elif domain:
        candidates.append(f"{user}@{domain}")
        candidates.append(f"{domain}\\{user}")
    else:
        candidates.append(user)

    try:
        server, connect_host, resolve_note, ldap_url = make_ldap_server(cfg)
    except Exception as exc:  # noqa: BLE001
        return AdAuthResult(ok=False, message=f"LDAP sunucu hatası: {exc}")

    bind_dn = (cfg.ad_bind_dn or "").strip()
    bind_pw = decrypt_ad_bind_password(cfg)
    groups: list[str] = []
    email = ""
    full_name = ""

    try:
        if bind_dn and bind_pw and base_dn:
            svc = Connection(server, user=bind_dn, password=bind_pw, auto_bind=True, receive_timeout=10)
            svc.search(
                search_base=base_dn,
                search_filter=user_filter,
                search_scope=SUBTREE,
                attributes=[
                    "distinguishedName", "sAMAccountName", "memberOf",
                    "userPrincipalName", "mail", "displayName",
                ],
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
            entry_dn = (
                str(entry.distinguishedName)
                if hasattr(entry, "distinguishedName")
                else str(entry.entry_dn)
            )
            if hasattr(entry, "memberOf") and entry.memberOf:
                groups = [str(x) for x in entry.memberOf.values]
            if hasattr(entry, "mail") and entry.mail:
                email = str(entry.mail)
            if hasattr(entry, "displayName") and entry.displayName:
                full_name = str(entry.displayName)
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
                        attributes=["memberOf", "sAMAccountName", "mail", "displayName"],
                        size_limit=1,
                    )
                    if conn.entries:
                        e0 = conn.entries[0]
                        if hasattr(e0, "memberOf") and e0.memberOf:
                            groups = [str(x) for x in e0.memberOf.values]
                        if hasattr(e0, "mail") and e0.mail:
                            email = str(e0.mail)
                        if hasattr(e0, "displayName") and e0.displayName:
                            full_name = str(e0.displayName)
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
            viewer_group=cfg.ad_viewer_group,
        )
        # Grup eşlemesi opsiyonel — şifre doğrulandıysa giriş OK; rol ainew'de yönetilir
        return AdAuthResult(
            ok=True,
            message=f"AD kimlik doğrulama başarılı ({resolve_note})",
            username=user.split("@")[0].split("\\")[-1],
            role=role,  # None olabilir
            groups=groups,
            email=email,
            full_name=full_name,
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
    bind_dn = (cfg.ad_bind_dn or "").strip()
    bind_pw = decrypt_ad_bind_password(cfg)
    if not bind_dn or not bind_pw:
        return AdAuthResult(ok=False, message="Service account DN / şifre gerekli")
    try:
        from ldap3 import Connection
    except ImportError:
        return AdAuthResult(ok=False, message="ldap3 kurulu değil")
    try:
        server, connect_host, resolve_note, ldap_url = make_ldap_server(cfg)
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
