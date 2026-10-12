"""Veeam VBR REST istemcisi — SALT-OKUNUR (token/logout dışında yalnız GET).

Auth akışı, header'lar ve sayfalama: veeam_api_ref.py başlığındaki doküman
bağlantıları (Overview → Authorization / Request Headers / Query Parameters).
Parola yalnız bellekte; log/hata mesajlarına yazılmaz.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Iterator, List, Optional, Protocol

import requests

from app.services.backup.veeam_api_ref import (
    AUTH_WRITE_PATHS, DEFAULT_REVISION, ENDPOINTS, REVISIONS, doc_url,
)

logger = logging.getLogger(__name__)

PAGE_LIMIT = 200  # doküman: limit varsayılanı 200


class VeeamApiError(Exception):
    """kind: auth | forbidden | network | tls | server | parse | readonly."""

    def __init__(self, kind: str, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.kind = kind
        self.status = status


class VeeamTransport(Protocol):
    def get_json(self, key: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]: ...


def paged(transport: VeeamTransport, key: str, params: Optional[Dict[str, Any]] = None,
          *, max_items: int = 5000) -> Iterator[Dict[str, Any]]:
    """skip/limit sayfalama (Overview → Query Parameters). Yanıt: {"data": [...], "pagination": {...}}."""
    skip = 0
    got = 0
    while got < max_items:
        q = dict(params or {})
        q.update({"skip": skip, "limit": PAGE_LIMIT})
        body = transport.get_json(key, q)
        rows = body.get("data") if isinstance(body, dict) else None
        if not isinstance(rows, list):
            raise VeeamApiError("parse", f"{key}: 'data' listesi yok")
        for r in rows:
            if isinstance(r, dict):
                yield r
                got += 1
                if got >= max_items:
                    return
        total = (body.get("pagination") or {}).get("total")
        skip += len(rows)
        if not rows or len(rows) < PAGE_LIMIT or (isinstance(total, int) and skip >= total):
            return


class VeeamRestClient:
    def __init__(self, host: str, username: str, password: str, *, port: int = 9419, verify: Any = True,
                 revision: str = DEFAULT_REVISION, timeout: float = 20.0, retries: int = 2,
                 session: Optional[requests.Session] = None):
        if revision not in REVISIONS:
            raise VeeamApiError("parse", f"Desteklenmeyen API revizyonu: {revision}")
        host = host.strip().rstrip("/")
        for pfx in ("https://", "http://"):
            if host.lower().startswith(pfx):
                host = host[len(pfx):]
        if ":" in host.split("/")[0]:
            host, _, p = host.partition(":")
            port = int(p.split("/")[0] or port)
        self.base = f"https://{host}:{int(port)}"
        self._user, self._pw = username, password
        self.verify = verify
        self.revision = revision
        self.timeout = timeout
        self.retries = max(0, retries)
        self._s = session or requests.Session()
        self._access: Optional[str] = None
        self._refresh: Optional[str] = None
        self._exp = 0.0

    # ── auth ────────────────────────────────────────────────────────────────
    def _headers(self, token: bool = True) -> Dict[str, str]:
        h = {"x-api-version": self.revision, "Accept": "application/json"}
        if token and self._access:
            h["Authorization"] = f"Bearer {self._access}"
        return h

    def _token_request(self, form: Dict[str, str]) -> None:
        # Doc: Overview → Requesting Authorization / Using Refresh Token
        # https://helpcenter.veeam.com/references/vbr/13/rest/1.3-rev1/tag/SectionOverview/index.html  (doğrulama: 1.3-rev1 doküman)
        try:
            r = self._s.post(self.base + "/api/oauth2/token", data=form, headers=self._headers(False),
                             verify=self.verify, timeout=self.timeout)
        except requests.exceptions.SSLError as e:
            raise VeeamApiError("tls", f"TLS doğrulama hatası: {_short(e)}") from None
        except requests.exceptions.RequestException as e:
            raise VeeamApiError("network", f"Bağlantı hatası: {_short(e)}") from None
        if r.status_code in (400, 401, 403):
            raise VeeamApiError("auth", f"Kimlik doğrulama reddedildi (HTTP {r.status_code})", r.status_code)
        if r.status_code != 200:
            raise VeeamApiError("server", f"Token isteği HTTP {r.status_code}", r.status_code)
        try:
            j = r.json()
            self._access = j["access_token"]
            self._refresh = j.get("refresh_token")
            self._exp = time.monotonic() + max(30, int(j.get("expires_in") or 900) - 60)
        except Exception:
            raise VeeamApiError("parse", "Token yanıtı çözümlenemedi") from None

    def login(self) -> None:
        self._token_request({"grant_type": "password", "username": self._user, "password": self._pw})

    def _ensure_token(self) -> None:
        if self._access and time.monotonic() < self._exp:
            return
        if self._refresh:
            try:
                self._token_request({"grant_type": "refresh_token", "refresh_token": self._refresh})
                return
            except VeeamApiError:
                pass
        self.login()

    def logout(self) -> None:
        # Doc: Overview → Performing Logout (POST /api/oauth2/logout; Bearer)
        if not self._access:
            return
        try:
            self._s.post(self.base + "/api/oauth2/logout", headers=self._headers(), verify=self.verify,
                         timeout=self.timeout)
        except Exception:  # noqa: BLE001
            pass
        self._access = self._refresh = None

    # ── salt-okunur GET ─────────────────────────────────────────────────────
    def get_json(self, key: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        ep = ENDPOINTS.get(key)
        if ep is None or ep.method != "GET":
            raise VeeamApiError("readonly", f"İzin verilmeyen endpoint: {key}")
        self._ensure_token()
        last: Optional[VeeamApiError] = None
        for attempt in range(self.retries + 1):
            try:
                r = self._s.get(self.base + ep.path, params=params or None, headers=self._headers(),
                                verify=self.verify, timeout=self.timeout)
            except requests.exceptions.SSLError as e:
                raise VeeamApiError("tls", f"TLS doğrulama hatası: {_short(e)}") from None
            except requests.exceptions.RequestException as e:
                last = VeeamApiError("network", f"Bağlantı hatası: {_short(e)}")
                time.sleep(0.5 * (attempt + 1))
                continue
            if r.status_code == 401 and attempt == 0:
                self._access = None
                self._ensure_token()
                continue
            if r.status_code == 401:
                raise VeeamApiError("auth", "Oturum reddedildi (HTTP 401)", 401)
            if r.status_code == 403:
                raise VeeamApiError("forbidden", f"Yetki yok (HTTP 403) — {ep.path} ({doc_url(key)})", 403)
            if r.status_code >= 500:
                last = VeeamApiError("server", f"VBR hata (HTTP {r.status_code})", r.status_code)
                time.sleep(0.5 * (attempt + 1))
                continue
            if r.status_code != 200:
                raise VeeamApiError("server", f"{ep.path} HTTP {r.status_code}", r.status_code)
            try:
                return r.json()
            except Exception:
                raise VeeamApiError("parse", f"{ep.path} yanıtı JSON değil") from None
        raise last or VeeamApiError("network", "Bilinmeyen bağlantı hatası")


def _short(e: Exception) -> str:
    return str(e).replace("\n", " ")[:200]


assert set(AUTH_WRITE_PATHS) == {"/api/oauth2/token", "/api/oauth2/logout"}
