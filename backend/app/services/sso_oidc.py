"""
ainew girişi için OIDC (Authorization Code + PKCE) tek oturum açma.

Güvenlik özellikleri (Dropt'taki MVP'den bilinçli olarak farklı):
- id_token imzası JWKS ile DOĞRULANIR (iss, aud, exp, iat, sub zorunlu; nonce eşleşmeli; alg beyaz liste).
- state/nonce/PKCE verifier Redis'te tutulur (çok işçili çalışmada güvenli), tek kullanımlık, 10 dk TTL.
  Redis yoksa SSO KAPALI davranır (fail-closed) — süreç belleğine düşülmez.
- Oturum token'ı URL'de taşınmaz: callback yalnızca 60 sn ömürlü, tek kullanımlık bir `sso_code`
  döndürür; arayüz bunu `POST /auth/sso/exchange` ile gerçek token'a çevirir.
- Rol eşleme KATI: grup adı tam eşleşmeli (alt dizge değil); hiçbir gruba uymayan kullanıcı reddedilir.
- Aynı adlı yerel (parolalı) hesap varsa SSO reddedilir (hesap devralma yok).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import re
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Optional
from urllib.parse import urlencode, urlparse

import httpx
import jwt
from jwt import PyJWKClient
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.core.redis_client import get_redis
from app.models.identity import IdentityConfig
from app.models.user import User
from app.services.identity_store import decrypt_sso_client_secret

logger = logging.getLogger(__name__)

STATE_TTL_SEC = 600
LOGIN_CODE_TTL_SEC = 60
DISCOVERY_TTL_SEC = 600
HTTP_TIMEOUT = 10.0

# HS* (paylaşılan anahtar) ve "none" bilinçli olarak YOK.
ALLOWED_ID_TOKEN_ALGS = ("RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512")

_STATE_PREFIX = "ainew:sso:state:"
_CODE_PREFIX = "ainew:sso:code:"
_USERNAME_RE = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
_ERROR_CODE_RE = re.compile(r"[^a-z_]")


class SsoError(Exception):
    """Kullanıcıya gösterilebilir (güvenli) SSO hatası."""


@dataclass
class SsoIdentity:
    username: str
    role: str
    subject: str
    email: str = ""
    full_name: str = ""
    groups: list[str] = field(default_factory=list)


# ── Yapılandırma ───────────────────────────────────────────────────────────

def is_configured(cfg: IdentityConfig) -> bool:
    """SSO düğmesi yalnızca eksiksiz yapılandırılmışsa gösterilir."""
    return bool(
        cfg.sso_enabled
        and (cfg.sso_mode or "oidc").lower() == "oidc"
        and (cfg.sso_issuer or "").strip()
        and (cfg.sso_client_id or "").strip()
        and (cfg.sso_redirect_uri or "").strip()
        and (cfg.sso_client_secret_enc or "").strip()
    )


def _check_url(url: str, what: str) -> str:
    u = urlparse((url or "").strip())
    if u.scheme not in ("http", "https") or not u.netloc:
        raise SsoError(f"{what} geçerli bir URL değil")
    # Düz http yalnızca loopback için (geliştirme/test); kurumsal IdP https olmalı.
    if u.scheme == "http" and (u.hostname or "") not in ("localhost", "127.0.0.1", "::1"):
        raise SsoError(f"{what} https olmalı")
    return url.strip()


def _scopes(cfg: IdentityConfig) -> str:
    parts = (cfg.sso_scopes or "openid profile email").split()
    if "openid" not in parts:
        parts.insert(0, "openid")
    return " ".join(parts)


# ── Discovery (önbellekli) ─────────────────────────────────────────────────

_disc_lock = threading.Lock()
_disc_cache: dict[str, tuple[float, dict[str, Any]]] = {}


def _http_get_json(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
        res = client.get(url, headers={"Accept": "application/json"})
        res.raise_for_status()
        return res.json()


def fetch_discovery(issuer: str, *, use_cache: bool = True) -> dict[str, Any]:
    base = _check_url(issuer, "Issuer").rstrip("/")
    now = time.time()
    if use_cache:
        with _disc_lock:
            hit = _disc_cache.get(base)
            if hit and hit[0] > now:
                return hit[1]
    try:
        doc = _http_get_json(f"{base}/.well-known/openid-configuration")
    except Exception as exc:  # noqa: BLE001
        logger.warning("OIDC discovery başarısız (%s): %s", base, exc)
        raise SsoError("SSO sağlayıcısına ulaşılamadı (discovery)") from exc
    if (doc.get("issuer") or "").rstrip("/") != base:
        raise SsoError("Discovery issuer değeri yapılandırılan Issuer ile uyuşmuyor")
    for key in ("authorization_endpoint", "token_endpoint", "jwks_uri"):
        _check_url(str(doc.get(key) or ""), f"Discovery {key}")
    with _disc_lock:
        _disc_cache[base] = (now + DISCOVERY_TTL_SEC, doc)
    return doc


def clear_discovery_cache() -> None:
    with _disc_lock:
        _disc_cache.clear()


# ── Redis tabanlı tek kullanımlık kayıtlar ─────────────────────────────────

def _redis():
    r = get_redis()
    if r is None:
        raise SsoError("SSO için Redis gerekli ve şu an erişilemiyor")
    return r


def _store(prefix: str, key: str, value: str, ttl: int) -> None:
    _redis().set(f"{prefix}{key}", value, ex=ttl)


def _take(prefix: str, key: str) -> Optional[str]:
    """Oku + sil (tek kullanımlık)."""
    if not key or len(key) > 200:
        return None
    return _redis().getdel(f"{prefix}{key}")


def create_login_code(user_id: int) -> str:
    code = secrets.token_urlsafe(32)
    _store(_CODE_PREFIX, code, str(int(user_id)), LOGIN_CODE_TTL_SEC)
    return code


def consume_login_code(code: str) -> Optional[int]:
    raw = _take(_CODE_PREFIX, (code or "").strip())
    try:
        return int(raw) if raw else None
    except ValueError:
        return None


# ── Yetkilendirme isteği ───────────────────────────────────────────────────

def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def build_authorize_url(cfg: IdentityConfig) -> str:
    if not is_configured(cfg):
        raise SsoError("SSO etkin değil veya yapılandırma eksik")
    redirect_uri = _check_url(cfg.sso_redirect_uri, "Redirect URI")
    disc = fetch_discovery(cfg.sso_issuer)
    state = secrets.token_urlsafe(24)
    nonce = secrets.token_urlsafe(24)
    verifier = secrets.token_urlsafe(48)
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    _store(_STATE_PREFIX, state, json.dumps({"nonce": nonce, "verifier": verifier}), STATE_TTL_SEC)
    qs = urlencode(
        {
            "response_type": "code",
            "client_id": cfg.sso_client_id.strip(),
            "redirect_uri": redirect_uri,
            "scope": _scopes(cfg),
            "state": state,
            "nonce": nonce,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        }
    )
    sep = "&" if "?" in disc["authorization_endpoint"] else "?"
    return f"{disc['authorization_endpoint']}{sep}{qs}"


# ── Grup / kullanıcı adı çözümleme ─────────────────────────────────────────

def _norm(s: str) -> str:
    return (s or "").strip().lower()


def group_matches(groups: list[str], needle: str) -> bool:
    """KATI eşleşme: tam ad, DN'nin CN'i veya yol (/a/b) son segmenti. Alt dizge DEĞİL."""
    n = _norm(needle)
    if not n:
        return False
    for g in groups:
        gl = _norm(g)
        if not gl:
            continue
        if gl == n:
            return True
        if gl.startswith("cn="):
            if gl.split(",", 1)[0][3:] == n:
                return True
        if "/" in gl and gl.rstrip("/").rsplit("/", 1)[-1] == n:
            return True
    return False


def resolve_role(cfg: IdentityConfig, groups: list[str]) -> Optional[str]:
    if group_matches(groups, cfg.sso_admin_group):
        return "admin"
    if group_matches(groups, cfg.sso_operator_group):
        return "operator"
    if group_matches(groups, cfg.sso_viewer_group):
        return "viewer"
    return None


def _groups_from_claims(claims: dict[str, Any]) -> list[str]:
    raw = claims.get("groups")
    if raw is None:
        raw = claims.get("roles")
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [str(g) for g in raw if isinstance(g, (str, int))]
    return []


def derive_username(claims: dict[str, Any]) -> str:
    raw = ""
    for key in ("preferred_username", "upn", "email", "sub"):
        v = claims.get(key)
        if isinstance(v, str) and v.strip():
            raw = v.strip()
            break
    name = raw.split("@", 1)[0].strip().lower()
    if not _USERNAME_RE.match(name):
        raise SsoError("SSO kullanıcı adı geçersiz veya alınamadı")
    return name


# ── Token değişimi ve id_token doğrulama ───────────────────────────────────

_jwk_clients: dict[str, PyJWKClient] = {}
_jwk_lock = threading.Lock()


def _get_jwk_client(jwks_uri: str) -> PyJWKClient:
    with _jwk_lock:
        c = _jwk_clients.get(jwks_uri)
        if c is None:
            c = PyJWKClient(jwks_uri, cache_keys=True, lifespan=600, timeout=HTTP_TIMEOUT)
            _jwk_clients[jwks_uri] = c
        return c


def verify_id_token(id_token: str, *, jwks_uri: str, issuer: str, client_id: str, nonce: str) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as exc:
        raise SsoError("id_token okunamadı") from exc
    alg = header.get("alg")
    if alg not in ALLOWED_ID_TOKEN_ALGS:
        raise SsoError("id_token imza algoritması desteklenmiyor")
    try:
        key = _get_jwk_client(jwks_uri).get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token,
            key,
            algorithms=[alg],
            audience=client_id,
            issuer=issuer,
            leeway=60,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        logger.warning("id_token doğrulanamadı: %s", exc)
        raise SsoError("id_token doğrulanamadı (imza, süre, issuer veya audience)") from exc
    except Exception as exc:  # noqa: BLE001 — JWKS ağ hatası vb.
        logger.warning("JWKS alınamadı: %s", exc)
        raise SsoError("SSO sağlayıcısının imza anahtarları alınamadı") from exc
    aud = claims.get("aud")
    if isinstance(aud, list) and len(aud) > 1 and claims.get("azp") != client_id:
        raise SsoError("id_token azp değeri geçersiz")
    token_nonce = claims.get("nonce")
    if not isinstance(token_nonce, str) or not hmac.compare_digest(token_nonce, nonce):
        raise SsoError("id_token nonce doğrulaması başarısız")
    return claims


def _exchange_code(cfg: IdentityConfig, disc: dict[str, Any], code: str, verifier: str) -> dict[str, Any]:
    secret = decrypt_sso_client_secret(cfg)
    if not secret:
        raise SsoError("SSO client secret tanımlı değil")
    data = {
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": cfg.sso_redirect_uri.strip(),
        "code_verifier": verifier,
    }
    methods = disc.get("token_endpoint_auth_methods_supported") or []
    auth = None
    if methods and "client_secret_post" not in methods and "client_secret_basic" in methods:
        auth = (cfg.sso_client_id.strip(), secret)
    else:
        data["client_id"] = cfg.sso_client_id.strip()
        data["client_secret"] = secret
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
            res = client.post(
                disc["token_endpoint"],
                data=data,
                auth=auth,
                headers={"Accept": "application/json"},
            )
    except Exception as exc:  # noqa: BLE001
        logger.warning("SSO token isteği başarısız: %s", exc)
        raise SsoError("SSO token uç noktasına ulaşılamadı") from exc
    if res.status_code >= 400:
        logger.warning("SSO token değişimi reddedildi: HTTP %s %s", res.status_code, res.text[:200])
        raise SsoError("SSO token değişimi reddedildi (kod geçersiz veya client bilgileri hatalı)")
    try:
        return res.json()
    except ValueError as exc:
        raise SsoError("SSO token yanıtı geçersiz") from exc


def _userinfo(disc: dict[str, Any], access_token: str) -> dict[str, Any]:
    ep = disc.get("userinfo_endpoint")
    if not ep or not access_token:
        return {}
    try:
        with httpx.Client(timeout=HTTP_TIMEOUT, follow_redirects=False) as client:
            res = client.get(ep, headers={"Authorization": f"Bearer {access_token}"})
        if res.status_code < 400:
            body = res.json()
            return body if isinstance(body, dict) else {}
    except Exception as exc:  # noqa: BLE001
        logger.info("SSO userinfo alınamadı (yok sayıldı): %s", exc)
    return {}


def handle_callback(cfg: IdentityConfig, *, code: str, state: str) -> SsoIdentity:
    if not is_configured(cfg):
        raise SsoError("SSO etkin değil veya yapılandırma eksik")
    raw = _take(_STATE_PREFIX, state)
    if not raw:
        raise SsoError("SSO oturumu geçersiz veya süresi dolmuş; tekrar deneyin")
    try:
        saved = json.loads(raw)
        nonce, verifier = str(saved["nonce"]), str(saved["verifier"])
    except (ValueError, KeyError) as exc:
        raise SsoError("SSO oturumu bozuk") from exc

    disc = fetch_discovery(cfg.sso_issuer)
    tokens = _exchange_code(cfg, disc, code, verifier)
    id_token = tokens.get("id_token") or ""
    if not id_token:
        raise SsoError("SSO sağlayıcısı id_token döndürmedi (scope 'openid' gerekli)")
    claims = verify_id_token(
        id_token,
        jwks_uri=disc["jwks_uri"],
        issuer=str(disc["issuer"]),
        client_id=cfg.sso_client_id.strip(),
        nonce=nonce,
    )

    groups = _groups_from_claims(claims)
    email = claims.get("email") if isinstance(claims.get("email"), str) else ""
    name = claims.get("name") if isinstance(claims.get("name"), str) else ""
    if not groups:
        info = _userinfo(disc, tokens.get("access_token") or "")
        # OIDC: userinfo.sub id_token.sub ile aynı olmalı; değilse yok say.
        if info and info.get("sub") == claims.get("sub"):
            groups = _groups_from_claims(info)
            email = email or (info.get("email") if isinstance(info.get("email"), str) else "")
            name = name or (info.get("name") if isinstance(info.get("name"), str) else "")

    role = resolve_role(cfg, groups)
    if role is None:
        raise SsoError("Hesabınız ainew için yetkili bir gruba üye değil")
    return SsoIdentity(
        username=derive_username(claims),
        role=role,
        subject=str(claims.get("sub")),
        email=email[:255],
        full_name=name[:255],
        groups=groups,
    )


# ── Kullanıcı oluşturma (JIT) ──────────────────────────────────────────────

def provision_user(db: Session, ident: SsoIdentity) -> User:
    existing = db.query(User).filter(func.lower(User.username) == ident.username.lower()).first()
    if existing is not None:
        if (existing.auth_source or "local") == "local" and existing.hashed_password:
            raise SsoError("Bu kullanıcı adı yerel bir hesapla çakışıyor; SSO ile giriş yapılamaz")
        if not existing.is_active:
            raise SsoError("Hesap pasif; yöneticinizle iletişime geçin")
        # Mevcut rol ve kaynak korunur (Kullanıcı Yönetimi'ndeki yetki geçerli; AD ile aynı).
        if ident.email:
            existing.email = ident.email
        if ident.full_name:
            existing.full_name = ident.full_name
        db.commit()
        db.refresh(existing)
        return existing
    user = User(
        username=ident.username,
        email=ident.email or None,
        full_name=ident.full_name or None,
        hashed_password=None,
        role=ident.role,
        auth_source="sso",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── Yönetici testi ─────────────────────────────────────────────────────────

def check_configuration(cfg: IdentityConfig) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, ok: bool, message: str) -> None:
        checks.append({"name": name, "ok": ok, "message": message})

    add("Etkin", bool(cfg.sso_enabled), "SSO etkin" if cfg.sso_enabled else "SSO etkin değil (kutuyu işaretleyip kaydedin)")
    add("Mod", (cfg.sso_mode or "oidc").lower() == "oidc", "OIDC" if (cfg.sso_mode or "oidc").lower() == "oidc" else "Yalnızca OIDC desteklenir")
    for label, val in (("Issuer", cfg.sso_issuer), ("Client ID", cfg.sso_client_id), ("Redirect URI", cfg.sso_redirect_uri)):
        add(label, bool((val or "").strip()), "Tanımlı" if (val or "").strip() else "Boş")
    add("Client Secret", bool((cfg.sso_client_secret_enc or "").strip()), "Tanımlı" if (cfg.sso_client_secret_enc or "").strip() else "Boş")
    has_groups = any((cfg.sso_admin_group, cfg.sso_operator_group, cfg.sso_viewer_group))
    add("Grup eşleme", bool(has_groups), "En az bir rol grubu tanımlı" if has_groups else "Hiç grup tanımlı değil — kimse giriş yapamaz")
    if (cfg.sso_redirect_uri or "").strip():
        try:
            _check_url(cfg.sso_redirect_uri, "Redirect URI")
            add("Redirect URI biçimi", True, "Geçerli")
        except SsoError as exc:
            add("Redirect URI biçimi", False, str(exc))
    if (cfg.sso_issuer or "").strip():
        try:
            disc = fetch_discovery(cfg.sso_issuer, use_cache=False)
            add("Discovery", True, "Issuer ve uç noktalar doğrulandı")
            try:
                jwks = _http_get_json(disc["jwks_uri"])
                n = len(jwks.get("keys") or [])
                add("JWKS", n > 0, f"{n} imza anahtarı" if n else "İmza anahtarı bulunamadı")
            except Exception as exc:  # noqa: BLE001
                add("JWKS", False, f"Alınamadı: {type(exc).__name__}")
        except SsoError as exc:
            add("Discovery", False, str(exc))
    return {"ok": all(c["ok"] for c in checks), "checks": checks}
