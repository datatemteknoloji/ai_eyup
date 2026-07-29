"""
OpenShift OAuth yardımcı modülü — kullanıcı adı + şifreyi bearer token'a çevirir.

`oc login -u <user> -p <password>` komutunun kullandığı akışla aynıdır:
1. API sunucusundan OAuth metadata'sı alınır (/.well-known/oauth-authorization-server).
2. "openshift-challenging-client" client_id'siyle implicit grant (response_type=token)
   akışı, HTTP Basic Auth (kullanıcı adı/şifre) ile tetiklenir.
3. Sunucu 302 ile yönlendirir; Location header'ının fragment kısmında
   `access_token=...` bulunur.

Bu, servis hesabı token'ı olmayan ama kullanıcı adı/şifresi olan ortamlar için
API URL + Token alanının yanına ikinci bir kimlik doğrulama seçeneği sağlar.
"""
import logging
from typing import Optional, Tuple
from urllib.parse import parse_qs

import requests
from urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)
logger = logging.getLogger(__name__)

CHALLENGING_CLIENT_ID = "openshift-challenging-client"
_MAX_REDIRECTS = 8


def _normalize_api_url(api_url: str) -> str:
    url = (api_url or "").strip().rstrip("/")
    if url and not url.startswith("http"):
        url = f"https://{url}"
    return url


def _extract_token_from_location(location: str) -> Optional[str]:
    if not location:
        return None
    # access_token fragment'ı '#' sonrasında query-string formatında gelir
    fragment = location.split("#", 1)[1] if "#" in location else ""
    if not fragment:
        return None
    params = parse_qs(fragment)
    token = params.get("access_token")
    return token[0] if token else None


def obtain_oauth_token(
    api_url: str,
    username: str,
    password: str,
    verify_ssl: bool = False,
    timeout: int = 20,
) -> Tuple[Optional[str], str]:
    """Kullanıcı adı/şifre ile OpenShift OAuth sunucusundan bearer token alır.

    Returns (token, error_message). Başarılı olursa error_message boş string olur.
    """
    base = _normalize_api_url(api_url)
    if not base:
        return None, "API Server URL gerekli"
    if not username or not password:
        return None, "Kullanıcı adı ve şifre gerekli"

    session = requests.Session()
    session.verify = verify_ssl

    try:
        meta_r = session.get(f"{base}/.well-known/oauth-authorization-server", timeout=timeout)
        if meta_r.status_code != 200:
            return None, (
                f"OAuth metadata alınamadı (HTTP {meta_r.status_code}) — "
                "cluster bir OAuth sunucusuna sahip mi kontrol edin"
            )
        meta = meta_r.json() or {}
        authorize_endpoint = meta.get("authorization_endpoint")
        if not authorize_endpoint:
            return None, "OAuth authorization_endpoint bulunamadı"
    except requests.exceptions.SSLError:
        return None, "SSL hatası — Sertifika doğrulanamadı"
    except requests.exceptions.ConnectTimeout:
        return None, "Bağlantı zaman aşımı — API URL ve port erişilebilir mi?"
    except requests.exceptions.ConnectionError as e:
        logger.error(f"OpenShift OAuth metadata connection error: {e}")
        return None, "Bağlantı kurulamadı — API URL kontrol edin"
    except Exception as e:
        logger.error(f"OpenShift OAuth metadata error: {e}")
        return None, str(e)

    try:
        url = authorize_endpoint
        params = {"client_id": CHALLENGING_CLIENT_ID, "response_type": "token"}
        headers = {"X-Csrf-Token": "1"}
        for _ in range(_MAX_REDIRECTS):
            r = session.get(
                url,
                params=params,
                headers=headers,
                auth=(username, password),
                allow_redirects=False,
                timeout=timeout,
            )
            params = None  # yönlendirmelerde query zaten Location içinde taşınır

            if r.status_code == 401:
                return None, "Kullanıcı adı veya şifre hatalı"

            location = r.headers.get("Location", "")
            token = _extract_token_from_location(location)
            if token:
                return token, ""

            if r.status_code in (301, 302, 303, 307, 308) and location:
                url = location if location.startswith("http") else f"{base}{location}"
                continue

            if r.status_code == 200:
                return None, "OAuth sunucusu beklenmeyen bir sayfa döndürdü (login formu?) — kimlik sağlayıcı basic auth'u desteklemiyor olabilir"

            return None, f"OAuth akışı başarısız (HTTP {r.status_code})"

        return None, "OAuth yönlendirme zinciri çok uzun — token alınamadı"
    except requests.exceptions.SSLError:
        return None, "SSL hatası — Sertifika doğrulanamadı"
    except requests.exceptions.ConnectTimeout:
        return None, "Bağlantı zaman aşımı — API URL ve port erişilebilir mi?"
    except requests.exceptions.ConnectionError as e:
        logger.error(f"OpenShift OAuth connection error: {e}")
        return None, "Bağlantı kurulamadı — API URL kontrol edin"
    except Exception as e:
        logger.error(f"OpenShift OAuth flow error: {e}")
        return None, str(e)
