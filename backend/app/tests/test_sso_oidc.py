"""OIDC SSO: id_token doğrulama, katı grup eşleme, PKCE/state, tek kullanımlık kod, JIT kullanıcı, uçtan uca HTTP."""
import base64
import hashlib
import json
import time
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core.database import get_db
from app.core.encryption import encrypt_secret
from app.models.identity import IdentityConfig
from app.models.user import User
from app.services import sso_oidc
from app.services.sso_oidc import SsoError

ISS = "https://idp.example.com/realms/corp"
CID = "ainew"
JWKS = "https://idp.example.com/jwks"


class FakeRedis:
    def __init__(self):
        self.d = {}

    def set(self, k, v, ex=None):
        self.d[k] = v

    def getdel(self, k):
        return self.d.pop(k, None)


class FakeJwkClient:
    def __init__(self, key):
        self._key = key

    def get_signing_key_from_jwt(self, _tok):
        class K:
            pass

        k = K()
        k.key = self._key.public_key()
        return k


@pytest.fixture()
def rsa_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture()
def fake_redis(monkeypatch):
    r = FakeRedis()
    monkeypatch.setattr(sso_oidc, "get_redis", lambda: r)
    return r


def _cfg(**kw):
    base = dict(
        sso_enabled=True, sso_mode="oidc", sso_issuer=ISS, sso_client_id=CID,
        sso_client_secret_enc=encrypt_secret("s3cret"),
        sso_redirect_uri="https://ainew.example.com/api/v1/auth/sso/callback",
        sso_scopes="profile email", sso_admin_group="ainew-admins",
        sso_operator_group="ainew-ops", sso_viewer_group="ainew-view",
        sso_frontend_redirect="/",
    )
    base.update(kw)
    return IdentityConfig(id=1, **base)


def _token(key, **over):
    now = int(time.time())
    claims = {"iss": ISS, "aud": CID, "sub": "u1", "iat": now, "exp": now + 300, "nonce": "N1"}
    claims.update(over)
    return jwt.encode(claims, key, algorithm="RS256")


# ── grup / kullanıcı adı ───────────────────────────────────────────────────

def test_group_match_is_strict_not_substring():
    assert sso_oidc.group_matches(["ainew-admins"], "ainew-admins")
    assert sso_oidc.group_matches(["AINEW-Admins"], "ainew-admins")
    assert sso_oidc.group_matches(["CN=ainew-admins,OU=g,DC=x"], "ainew-admins")
    assert sso_oidc.group_matches(["/corp/ainew-admins"], "ainew-admins")
    assert not sso_oidc.group_matches(["ainew-admins-requests"], "ainew-admins")
    assert not sso_oidc.group_matches(["not-ainew-admins"], "ainew-admins")
    assert not sso_oidc.group_matches(["anything"], "")


def test_resolve_role_priority_and_none():
    cfg = _cfg()
    assert sso_oidc.resolve_role(cfg, ["ainew-view", "ainew-admins"]) == "admin"
    assert sso_oidc.resolve_role(cfg, ["ainew-ops"]) == "operator"
    assert sso_oidc.resolve_role(cfg, ["ainew-view"]) == "viewer"
    assert sso_oidc.resolve_role(cfg, ["x"]) is None


def test_derive_username():
    assert sso_oidc.derive_username({"preferred_username": "Ali.Veli@corp.local"}) == "ali.veli"
    assert sso_oidc.derive_username({"email": "a@b.c"}) == "a"
    with pytest.raises(SsoError):
        sso_oidc.derive_username({"preferred_username": "a b;drop"})
    with pytest.raises(SsoError):
        sso_oidc.derive_username({})


def test_is_configured_requires_everything():
    assert sso_oidc.is_configured(_cfg())
    assert not sso_oidc.is_configured(_cfg(sso_enabled=False))
    assert not sso_oidc.is_configured(_cfg(sso_client_secret_enc=""))
    assert not sso_oidc.is_configured(_cfg(sso_issuer=""))
    assert not sso_oidc.is_configured(_cfg(sso_mode="kerberos"))


def test_http_issuer_only_for_loopback():
    with pytest.raises(SsoError):
        sso_oidc._check_url("http://idp.corp.local", "Issuer")
    assert sso_oidc._check_url("http://localhost:9000", "Issuer")
    assert sso_oidc._check_url("https://idp.corp.local", "Issuer")


# ── id_token doğrulama ─────────────────────────────────────────────────────

@pytest.fixture()
def verify(monkeypatch, rsa_key):
    monkeypatch.setattr(sso_oidc, "_get_jwk_client", lambda uri: FakeJwkClient(rsa_key))

    def run(tok, nonce="N1"):
        return sso_oidc.verify_id_token(tok, jwks_uri=JWKS, issuer=ISS, client_id=CID, nonce=nonce)

    return run


def test_verify_ok(verify, rsa_key):
    assert verify(_token(rsa_key))["sub"] == "u1"


@pytest.mark.parametrize("over", [{"aud": "other"}, {"iss": "https://evil"}, {"exp": 1}, {"nonce": "BAD"}])
def test_verify_rejects_bad_claims(verify, rsa_key, over):
    with pytest.raises(SsoError):
        verify(_token(rsa_key, **over))


def test_verify_rejects_wrong_signature(verify):
    other = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(SsoError):
        verify(_token(other))


def test_verify_rejects_hs256_and_none(verify):
    now = int(time.time())
    claims = {"iss": ISS, "aud": CID, "sub": "u", "iat": now, "exp": now + 60, "nonce": "N1"}
    with pytest.raises(SsoError):
        verify(jwt.encode(claims, "x" * 40, algorithm="HS256"))
    with pytest.raises(SsoError):
        verify(jwt.encode(claims, None, algorithm="none"))


def test_verify_requires_nonce(verify, rsa_key):
    now = int(time.time())
    tok = jwt.encode({"iss": ISS, "aud": CID, "sub": "u", "iat": now, "exp": now + 60}, rsa_key, algorithm="RS256")
    with pytest.raises(SsoError):
        verify(tok)


# ── state / PKCE / tek kullanımlık kod ─────────────────────────────────────

def test_authorize_url_has_pkce_state_nonce(monkeypatch, fake_redis):
    monkeypatch.setattr(sso_oidc, "fetch_discovery", lambda iss, **k: {"authorization_endpoint": "https://idp.example.com/auth"})
    url = sso_oidc.build_authorize_url(_cfg())
    q = {k: v[0] for k, v in parse_qs(urlparse(url).query).items()}
    assert q["response_type"] == "code" and q["code_challenge_method"] == "S256"
    assert "openid" in q["scope"].split()
    saved = json.loads(fake_redis.d[f"ainew:sso:state:{q['state']}"])
    expect = base64.urlsafe_b64encode(hashlib.sha256(saved["verifier"].encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == expect and q["nonce"] == saved["nonce"]


def test_login_code_single_use(fake_redis):
    c = sso_oidc.create_login_code(7)
    assert sso_oidc.consume_login_code(c) == 7
    assert sso_oidc.consume_login_code(c) is None
    assert sso_oidc.consume_login_code("") is None


def test_no_redis_fails_closed(monkeypatch):
    monkeypatch.setattr(sso_oidc, "get_redis", lambda: None)
    with pytest.raises(SsoError):
        sso_oidc.create_login_code(1)


# ── kullanıcı oluşturma ────────────────────────────────────────────────────

def _ident(**kw):
    d = dict(username="ali", role="operator", subject="s", email="a@x.y", full_name="Ali")
    d.update(kw)
    return sso_oidc.SsoIdentity(**d)


def test_provision_creates_sso_user(isolated_db):
    u = sso_oidc.provision_user(isolated_db, _ident())
    assert u.auth_source == "sso" and u.role == "operator" and u.hashed_password is None


def test_provision_blocks_local_collision(isolated_db):
    isolated_db.add(User(username="ali", hashed_password="x", role="admin", auth_source="local", is_active=True))
    isolated_db.commit()
    with pytest.raises(SsoError):
        sso_oidc.provision_user(isolated_db, _ident())


def test_provision_inactive_and_case_insensitive_and_role_kept(isolated_db):
    isolated_db.add(User(username="Ali", role="viewer", auth_source="ad", is_active=False))
    isolated_db.commit()
    with pytest.raises(SsoError):
        sso_oidc.provision_user(isolated_db, _ident(role="admin"))
    u = isolated_db.query(User).first()
    u.is_active = True
    isolated_db.commit()
    got = sso_oidc.provision_user(isolated_db, _ident(role="admin"))
    assert got.id == u.id and got.role == "viewer" and got.auth_source == "ad"
    assert isolated_db.query(User).count() == 1


# ── Uçtan uca HTTP (IdP çağrıları taklit) ──────────────────────────────────

@pytest.fixture()
def api(isolated_db, fake_redis, monkeypatch, rsa_key):
    from app.api import auth, public

    isolated_db.add(_cfg())
    isolated_db.commit()
    app = FastAPI()
    app.include_router(auth.router, prefix="/auth")
    app.include_router(public.router, prefix="/public")
    app.dependency_overrides[get_db] = lambda: isolated_db
    disc = {
        "issuer": ISS, "authorization_endpoint": "https://idp.example.com/auth",
        "token_endpoint": "https://idp.example.com/token", "jwks_uri": JWKS,
    }
    monkeypatch.setattr(sso_oidc, "fetch_discovery", lambda iss, **k: disc)
    monkeypatch.setattr(sso_oidc, "_get_jwk_client", lambda uri: FakeJwkClient(rsa_key))
    return TestClient(app, follow_redirects=False), rsa_key


def _start(client):
    r = client.get("/auth/sso/start")
    assert r.status_code == 302
    q = parse_qs(urlparse(r.headers["location"]).query)
    return q["state"][0], q["nonce"][0]


def _patch_token(monkeypatch, key, nonce, **claims):
    tok = _token(key, nonce=nonce, **claims)
    monkeypatch.setattr(sso_oidc, "_exchange_code", lambda cfg, disc, code, verifier: {"id_token": tok})


def test_login_options(api):
    client, _ = api
    assert client.get("/public/login-options").json() == {"ad_enabled": False, "sso_enabled": True}


def test_full_sso_flow_and_code_is_single_use(api, monkeypatch):
    client, key = api
    state, nonce = _start(client)
    _patch_token(monkeypatch, key, nonce, preferred_username="Ayse@corp", groups=["ainew-admins"])
    r = client.get("/auth/sso/callback", params={"code": "c", "state": state})
    assert r.status_code == 302
    loc = r.headers["location"]
    assert loc.startswith("/login?sso_code=") and "access_token" not in loc and "sso_token" not in loc
    code = parse_qs(urlparse(loc).query)["sso_code"][0]
    ok = client.post("/auth/sso/exchange", json={"code": code})
    assert ok.status_code == 200
    body = ok.json()
    assert body["user"]["username"] == "ayse" and body["user"]["role"] == "admin" and body["access_token"]
    assert client.post("/auth/sso/exchange", json={"code": code}).status_code == 401


def test_callback_replayed_state_rejected(api, monkeypatch):
    client, key = api
    state, nonce = _start(client)
    _patch_token(monkeypatch, key, nonce, preferred_username="bob", groups=["ainew-ops"])
    assert "sso_code=" in client.get("/auth/sso/callback", params={"code": "c", "state": state}).headers["location"]
    again = client.get("/auth/sso/callback", params={"code": "c", "state": state}).headers["location"]
    assert "sso_error=" in again


def test_user_without_group_denied(api, monkeypatch, isolated_db):
    client, key = api
    state, nonce = _start(client)
    _patch_token(monkeypatch, key, nonce, preferred_username="eve", groups=["other"])
    loc = client.get("/auth/sso/callback", params={"code": "c", "state": state}).headers["location"]
    assert "sso_error=" in loc and "sso_code" not in loc
    assert isolated_db.query(User).filter(User.username == "eve").count() == 0


def test_idp_error_does_not_echo_description(api):
    client, _ = api
    loc = client.get(
        "/auth/sso/callback",
        params={"error": "access_denied", "error_description": "<script>x</script>"},
    ).headers["location"]
    assert "script" not in loc and "access_denied" in loc


def test_exchange_garbage_code(api):
    client, _ = api
    assert client.post("/auth/sso/exchange", json={"code": "nope"}).status_code == 401
