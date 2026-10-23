"""Donanım sağlayıcıları için ortak, GÜVENLİ HTTP istemcisi.

* Salt-okunur: `endpoints.allowed` dışındaki her istek `HwApiError(kind="readonly")` ile reddedilir (ağa çıkmadan).
* Kimlik doğrulama: 401/oturum reddi → HEMEN `HwApiError(kind="auth")`, yeniden DENEME YOK (hesap kilitlenmesin).
  403 → `forbidden` (yeniden deneme yok). Oturum açma (POST) hiçbir koşulda yeniden denenmez.
* Yalnız ağ/zaman aşımı ve 5xx hataları GET'te sınırlı üstel bekleme ile yeniden denenir.
* Parola/token hiçbir log/hata mesajına yazılmaz.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

import requests
from requests.exceptions import ConnectionError as ReqConnError, SSLError, Timeout

from app.services.hw import endpoints as ep

logger = logging.getLogger(__name__)

RETRY_MAX = 2
RETRY_BASE_SEC = 1.0


class HwApiError(Exception):
    """kind: auth | forbidden | network | tls | server | parse | readonly | unsupported | client"""

    def __init__(self, kind: str, message: str, status: Optional[int] = None):
        super().__init__(message)
        self.kind = kind
        self.status = status
        self.message = message


_MSG_TR = {
    "auth": "Kimlik doğrulama reddedildi (kullanıcı adı/parola). Hesap kilitlenmesin diye otomatik senkron durduruldu.",
    "forbidden": "Yetki yetersiz (HTTP 403). Hesabın salt-okunur ama gerekli görüntüleme yetkisine sahip olduğundan emin olun.",
    "network": "Sunucuya ulaşılamadı (ağ / zaman aşımı).",
    "tls": "TLS sertifikası doğrulanamadı. Sertifika zincirini (CA paketi) ekleyin veya doğrulamayı kapatın.",
    "server": "Sunucu hata döndürdü (5xx).",
    "parse": "Yanıt beklenen biçimde değil.",
}


def msg_tr(kind: str) -> str:
    return _MSG_TR.get(kind, kind)


class HwHttp:
    def __init__(self, base_url: str, product: str, *, verify: Any = True, timeout=(5, 30),
                 session: Optional[requests.Session] = None, sleep=time.sleep):
        self.base = base_url.rstrip("/")
        self.product = product
        self.verify = verify
        self.timeout = timeout
        self.s = session or requests.Session()
        self._sleep = sleep
        self.requests_made = 0          # test/gözlem: toplam ağ isteği sayısı
        self.login_attempts = 0

    # ── düşük seviye ────────────────────────────────────────────────────────────────────────────────────────────
    def _send(self, method: str, path: str, *, params=None, json_body=None, headers=None) -> requests.Response:
        if not ep.allowed(self.product, method, path):
            raise HwApiError("readonly", f"İzin verilmeyen istek engellendi: {method} {path}")
        url = self.base + path
        self.requests_made += 1
        try:
            return self.s.request(method, url, params=params, json=json_body, headers=headers or {},
                                  verify=self.verify, timeout=self.timeout, allow_redirects=False)
        except SSLError as e:
            raise HwApiError("tls", msg_tr("tls")) from e
        except Timeout as e:
            raise HwApiError("network", msg_tr("network")) from e
        except ReqConnError as e:
            raise HwApiError("network", msg_tr("network")) from e
        except requests.RequestException as e:  # noqa: BLE001
            raise HwApiError("network", msg_tr("network")) from e

    @staticmethod
    def _raise_for(resp: requests.Response) -> None:
        sc = resp.status_code
        if sc in (401,):
            raise HwApiError("auth", msg_tr("auth"), sc)
        if sc == 403:
            raise HwApiError("forbidden", msg_tr("forbidden"), sc)
        if 500 <= sc <= 599:
            raise HwApiError("server", f"{msg_tr('server')} (HTTP {sc})", sc)
        if sc >= 400:
            raise HwApiError("client", f"İstek reddedildi (HTTP {sc})", sc)

    # ── herkese açık ────────────────────────────────────────────────────────────────────────────────────────────
    def get(self, path: str, *, params: Optional[Dict[str, Any]] = None,
            headers: Optional[Dict[str, str]] = None, retry: bool = True) -> Any:
        """GET + JSON. Yalnız network/5xx yeniden denenir (üstel bekleme)."""
        attempts = (RETRY_MAX + 1) if retry else 1
        last: Optional[HwApiError] = None
        for i in range(attempts):
            try:
                resp = self._send("GET", path, params=params, headers=headers)
                self._raise_for(resp)
                try:
                    return resp.json()
                except ValueError as e:
                    raise HwApiError("parse", msg_tr("parse")) from e
            except HwApiError as e:
                last = e
                if e.kind in ("network", "server") and i < attempts - 1:
                    self._sleep(RETRY_BASE_SEC * (2 ** i))
                    continue
                raise
        assert last is not None
        raise last

    def login(self, body: Dict[str, Any], *, headers: Optional[Dict[str, str]] = None) -> requests.Response:
        """Oturum açma: TEK deneme, yeniden deneme YOK. Çağıran 401/403'te durmalıdır."""
        self.login_attempts += 1
        method, path = ep.LOGIN[self.product]
        resp = self._send(method, path, json_body=body, headers=headers)
        self._raise_for(resp)
        return resp

    def logout(self, path: Optional[str] = None, *, headers: Optional[Dict[str, str]] = None) -> None:
        """En iyi çaba; hata yutulur."""
        try:
            method, pat = ep.LOGOUT[self.product]
            p = path or (pat if isinstance(pat, str) else None)
            if not p:
                return
            self._send(method, p, headers=headers)
        except Exception as e:  # noqa: BLE001
            logger.debug("hw logout (%s) yoksayıldı: %s", self.product, type(e).__name__)

    def close(self) -> None:
        try:
            self.s.close()
        except Exception:  # noqa: BLE001
            pass
