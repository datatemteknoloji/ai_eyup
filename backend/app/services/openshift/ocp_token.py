"""OpenShift Thanos / Prometheus için otomatik OAuth token yenileme.

Ayarlar > Monitoring'deki OpenShift kaynağında saklı ``sha256~…`` token'ı bir OpenShift
OAuth kullanıcı token'ıdır ve varsayılan olarak ~24 saat sonra dolar (Thanos 401 döner).
Kaynağın token'ı geçersizse, OpenShift modülünde kayıtlı küme girişiyle (kullanıcı/şifre)
yeni bir token alınır ve **yalnızca bellekte** tutulur; DB'ye yazılmaz.

Davranış:
  - Yalnızca ``sha256~`` ile başlayan (süresi dolabilen) token'lar yoklanır; ServiceAccount
    JWT'leri ve diğer token'lar olduğu gibi kullanılır.
  - Geçerlilik, küme API'sinde ``users/~`` ile yoklanır ve kısa süre önbelleğe alınır.
  - Yoklama / yenileme başarısız olursa (ağ hatası, giriş yok) saklı token kullanılır.
"""
from __future__ import annotations

import base64
import hashlib
import logging
import re
import threading
import time
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

_LOCK = threading.Lock()
_VALID_TTL = 300.0       # geçerlilik yoklaması önbelleği (sn)
_MINT_TTL = 6 * 3600.0   # üretilen token bellekte bu kadar tutulur
_PROBE_TIMEOUT = 6.0
_MINT_FAIL_TTL = 120.0   # başarısız yenilemeyi bu süre tekrar deneme

_valid_cache: Dict[str, Tuple[float, bool]] = {}
_minted: Dict[int, Tuple[float, str]] = {}      # cluster_id → (ts, token)
_mint_failed: Dict[int, float] = {}


def _tok_key(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()[:24]


def is_expirable(token: str) -> bool:
    return bool(token) and token.startswith("sha256~")


def _load_clusters() -> list:
    """(id, api_url, connection_config) — salt okunur."""
    from sqlalchemy import text
    from app.core.database import SessionLocal

    db = SessionLocal()
    try:
        rows = db.execute(
            text("select id, api_url, connection_config from openshift_clusters order by id")
        ).all()
        return [(r.id, str(r.api_url or ""), dict(r.connection_config or {})) for r in rows]
    finally:
        db.close()


def _cluster_verify(cfg: Dict[str, Any]) -> bool:
    v = cfg.get("verify_ssl")
    return bool(v) if v is not None else False


def _probe(api_url: str, token: str, verify: bool) -> Optional[bool]:
    """True/False: token geçerli mi; None: belirlenemedi (ağ hatası)."""
    try:
        r = httpx.get(
            f"{api_url.rstrip('/')}/apis/user.openshift.io/v1/users/~",
            headers={"Authorization": f"Bearer {token}"},
            verify=verify,
            timeout=_PROBE_TIMEOUT,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("ocp token probe failed: %s", e)
        return None
    if r.status_code == 401:
        return False
    if r.status_code in (200, 403, 404):
        # 403/404: token geçerli ama user API'si yetkisiz — yine de kimliği doğrulanmış.
        return True
    return None


def _mint(api_url: str, cfg: Dict[str, Any]) -> Optional[str]:
    """Kayıtlı kullanıcı/şifre ile OAuth (challenging client) token al."""
    from app.core.encryption import decrypt_secret

    user = str(cfg.get("username") or "").strip()
    raw_pw = cfg.get("password") or ""
    if not user or not raw_pw:
        return None
    try:
        pw = decrypt_secret(raw_pw)
    except Exception:  # noqa: BLE001
        pw = raw_pw
    verify = _cluster_verify(cfg)
    try:
        with httpx.Client(verify=verify, timeout=15.0) as c:
            meta = c.get(f"{api_url.rstrip('/')}/.well-known/oauth-authorization-server").json()
            auth = meta["authorization_endpoint"]
            basic = base64.b64encode(f"{user}:{pw}".encode()).decode()
            resp = c.get(
                auth,
                params={"client_id": "openshift-challenging-client", "response_type": "token"},
                headers={"X-CSRF-Token": "ainew", "Authorization": f"Basic {basic}"},
                follow_redirects=False,
            )
        m = re.search(r"access_token=([^&]+)", resp.headers.get("location", ""))
        return m.group(1) if m else None
    except Exception as e:  # noqa: BLE001
        logger.warning("OpenShift OAuth token yenilenemedi: %s", e)
        return None


def _pick_cluster(clusters: list, source_url: str):
    """Kaynak URL'sinin ait olduğu kümeyi seç (tek küme varsa o)."""
    if not clusters:
        return None
    if len(clusters) == 1:
        return clusters[0]
    host = (urlparse(source_url).hostname or "").lower()
    for cid, api, cfg in clusters:
        # api.ocp.example.local → apps.ocp.example.local
        ah = (urlparse(api).hostname or "").lower()
        if ah.startswith("api."):
            if host.endswith("apps." + ah[4:]):
                return (cid, api, cfg)
    return clusters[0]


def resolve_token(stored_token: str, source_url: str) -> str:
    """Saklı token geçerliyse onu, süresi dolmuşsa bellekteki yenisini döndür."""
    if not is_expirable(stored_token):
        return stored_token
    now = time.time()
    key = _tok_key(stored_token)
    with _LOCK:
        hit = _valid_cache.get(key)
    if hit and now - hit[0] < _VALID_TTL and hit[1]:
        return stored_token

    try:
        picked = _pick_cluster(_load_clusters(), source_url)
    except Exception as e:  # noqa: BLE001
        logger.debug("ocp token: cluster okunamadı: %s", e)
        return stored_token
    if not picked:
        return stored_token
    cid, api, cfg = picked
    verify = _cluster_verify(cfg)

    # Daha önce üretilmiş token hâlâ taze mi?
    with _LOCK:
        m = _minted.get(cid)
    if m and now - m[0] < _MINT_TTL:
        if hit and now - hit[0] < _VALID_TTL and not hit[1]:
            return m[1]
    if not (hit and now - hit[0] < _VALID_TTL):
        ok = _probe(api, stored_token, verify)
        if ok is None:
            return stored_token
        with _LOCK:
            _valid_cache[key] = (now, bool(ok))
        if ok:
            return stored_token
        hit = (now, False)

    # Saklı token geçersiz → üretilmiş token kullan / yenile
    with _LOCK:
        m = _minted.get(cid)
        failed_at = _mint_failed.get(cid, 0.0)
    if m and now - m[0] < _MINT_TTL:
        return m[1]
    if now - failed_at < _MINT_FAIL_TTL:
        return stored_token
    new = _mint(api, cfg)
    with _LOCK:
        if new:
            _minted[cid] = (now, new)
            _mint_failed.pop(cid, None)
        else:
            _mint_failed[cid] = now
    if new:
        logger.info("OpenShift Thanos token otomatik yenilendi (cluster_id=%s)", cid)
        return new
    return stored_token


def invalidate_cache() -> None:
    with _LOCK:
        _valid_cache.clear()
        _minted.clear()
        _mint_failed.clear()
