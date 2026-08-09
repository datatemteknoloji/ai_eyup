"""OIDC Authorization Code helpers for portal SSO."""

from __future__ import annotations

import secrets
import time
from typing import Any
from urllib.parse import urlencode

import httpx
from jose import jwt

from app.core.config import get_settings
from app.models.identity import IdentityConfig
from app.models.user import UserRole
from app.services.ad_auth import resolve_role_from_groups
from app.services.identity_store import decrypt_sso_client_secret

# in-memory state store (single API process; Redis optional later)
_SSO_STATES: dict[str, float] = {}
_STATE_TTL_SEC = 600


def _prune_states() -> None:
    now = time.time()
    dead = [k for k, exp in _SSO_STATES.items() if exp < now]
    for k in dead:
        _SSO_STATES.pop(k, None)


def create_sso_state() -> str:
    _prune_states()
    state = secrets.token_urlsafe(24)
    _SSO_STATES[state] = time.time() + _STATE_TTL_SEC
    return state


def consume_sso_state(state: str) -> bool:
    _prune_states()
    exp = _SSO_STATES.pop(state, None)
    return exp is not None and exp >= time.time()


def fetch_oidc_discovery(issuer: str) -> dict[str, Any]:
    base = issuer.rstrip("/")
    url = f"{base}/.well-known/openid-configuration"
    with httpx.Client(timeout=10.0) as client:
        res = client.get(url)
        res.raise_for_status()
        return res.json()


def build_authorize_url(cfg: IdentityConfig) -> tuple[str, str]:
    if not cfg.sso_enabled:
        raise ValueError("SSO kapalı")
    if not cfg.sso_issuer.strip() or not cfg.sso_client_id.strip() or not cfg.sso_redirect_uri.strip():
        raise ValueError("SSO issuer / client_id / redirect_uri gerekli")
    discovery = fetch_oidc_discovery(cfg.sso_issuer.strip())
    auth_ep = discovery.get("authorization_endpoint")
    if not auth_ep:
        raise ValueError("OIDC authorization_endpoint yok")
    state = create_sso_state()
    scopes = (cfg.sso_scopes or "openid profile email").strip()
    qs = urlencode(
        {
            "response_type": "code",
            "client_id": cfg.sso_client_id.strip(),
            "redirect_uri": cfg.sso_redirect_uri.strip(),
            "scope": scopes,
            "state": state,
        }
    )
    return f"{auth_ep}?{qs}", state


def exchange_code_and_resolve(
    cfg: IdentityConfig,
    *,
    code: str,
    state: str,
) -> tuple[str, UserRole, dict[str, Any]]:
    if not consume_sso_state(state):
        raise ValueError("Geçersiz veya süresi dolmuş SSO state")
    secret = decrypt_sso_client_secret(cfg)
    if not secret:
        raise ValueError("SSO client secret tanımlı değil")

    discovery = fetch_oidc_discovery(cfg.sso_issuer.strip())
    token_ep = discovery.get("token_endpoint")
    if not token_ep:
        raise ValueError("OIDC token_endpoint yok")

    with httpx.Client(timeout=15.0) as client:
        res = client.post(
            token_ep,
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": cfg.sso_redirect_uri.strip(),
                "client_id": cfg.sso_client_id.strip(),
                "client_secret": secret,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if res.status_code >= 400:
            raise ValueError(f"Token exchange başarısız: {res.text[:300]}")
        tokens = res.json()

    id_token = tokens.get("id_token") or ""
    access_token = tokens.get("access_token") or ""
    claims: dict[str, Any] = {}
    if id_token:
        # Signature verification against JWKS would be ideal; decode without verify for MVP
        # but still require issuer match when present.
        claims = jwt.get_unverified_claims(id_token)
        iss = (claims.get("iss") or "").rstrip("/")
        expected = cfg.sso_issuer.strip().rstrip("/")
        if iss and expected and iss != expected:
            raise ValueError("id_token issuer uyuşmuyor")

    # Optional userinfo for groups
    userinfo_ep = discovery.get("userinfo_endpoint")
    if userinfo_ep and access_token:
        try:
            with httpx.Client(timeout=10.0) as client:
                ui = client.get(userinfo_ep, headers={"Authorization": f"Bearer {access_token}"})
                if ui.status_code < 400:
                    claims = {**claims, **ui.json()}
        except Exception:
            pass

    username = (
        str(claims.get("preferred_username") or claims.get("upn") or claims.get("email") or claims.get("sub") or "")
        .strip()
        .split("@")[0]
    )
    if not username:
        raise ValueError("SSO token'dan kullanıcı adı alınamadı")

    groups_raw = claims.get("groups") or claims.get("roles") or []
    if isinstance(groups_raw, str):
        groups = [groups_raw]
    elif isinstance(groups_raw, list):
        groups = [str(g) for g in groups_raw]
    else:
        groups = []

    role = resolve_role_from_groups(
        groups,
        admin_group=cfg.sso_admin_group or cfg.ad_admin_group,
        operator_group=cfg.sso_operator_group or cfg.ad_operator_group,
    )
    # If no group claim, allow default operator when SSO is trusted (optional)
    if role is None:
        # Still require group mapping for safety
        raise ValueError("SSO kullanıcısı Admin/Operator grubunda değil")

    return username, role, claims


def frontend_sso_success_url(cfg: IdentityConfig, access_token: str) -> str:
    base = (cfg.sso_frontend_redirect or get_settings().cors_origin_list[0] or "http://localhost:3000").rstrip("/")
    # SPA login page picks up ?sso_token=
    return f"{base}/?sso_token={access_token}"


def frontend_sso_error_url(cfg: IdentityConfig, message: str) -> str:
    from urllib.parse import quote

    base = (cfg.sso_frontend_redirect or get_settings().cors_origin_list[0] or "http://localhost:3000").rstrip("/")
    return f"{base}/?sso_error={quote(message[:200])}"
