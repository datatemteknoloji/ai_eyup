"""Zabbix JSON-RPC client (READ-ONLY).

Auth: API token (Authorization Bearer) veya user.login (username/password).
Zabbix 5.x–7.x uyumu: login params hem username hem user dener.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

import httpx

from app.services.monitoring_sources import MonitoringSource, zabbix_api_url

logger = logging.getLogger(__name__)

_SESSION_TTL_SEC = 800  # Zabbix default ~15m; yenilemeden önce
_session_cache: Dict[str, Dict[str, Any]] = {}


class ZabbixError(Exception):
    def __init__(self, message: str, *, code: Optional[int] = None, data: Any = None):
        super().__init__(message)
        self.code = code
        self.data = data


class ZabbixClient:
    def __init__(self, source: MonitoringSource):
        self.source = source
        self.api = zabbix_api_url(source)
        self.verify = bool(source.verify_ssl)
        self._auth: Optional[str] = None
        self._auth_kind: str = ""  # token|session

    def _cache_key(self) -> str:
        return f"{self.source.id}|{self.api}"

    def _load_cached_session(self) -> Optional[str]:
        row = _session_cache.get(self._cache_key())
        if not row:
            return None
        if float(row.get("exp") or 0) < time.time():
            _session_cache.pop(self._cache_key(), None)
            return None
        return str(row.get("auth") or "") or None

    def _store_session(self, auth: str) -> None:
        _session_cache[self._cache_key()] = {
            "auth": auth,
            "exp": time.time() + _SESSION_TTL_SEC,
        }

    def clear_session(self) -> None:
        _session_cache.pop(self._cache_key(), None)
        self._auth = None

    def _post(self, method: str, params: Any = None, *, auth: Optional[str] = None) -> Any:
        body: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params if params is not None else [],
            "id": 1,
        }
        headers = {"Content-Type": "application/json"}
        # API token (Zabbix 5.4+): Authorization Bearer — body auth yok
        token = (self.source.token or "").strip()
        if token and method != "apiinfo.version":
            headers["Authorization"] = f"Bearer {token}"
            self._auth_kind = "token"
        elif auth:
            body["auth"] = auth
            self._auth_kind = "session"

        try:
            with httpx.Client(timeout=25.0, verify=self.verify) as client:
                resp = client.post(self.api, json=body, headers=headers)
        except httpx.HTTPError as e:
            raise ZabbixError(f"Zabbix bağlantı hatası: {e}") from e

        try:
            data = resp.json()
        except Exception as e:
            raise ZabbixError(f"Zabbix yanıtı JSON değil (HTTP {resp.status_code})") from e

        if not isinstance(data, dict):
            raise ZabbixError(f"Zabbix beklenmeyen yanıt (HTTP {resp.status_code})")

        err = data.get("error")
        if err:
            msg = err.get("data") or err.get("message") or str(err)
            raise ZabbixError(str(msg), code=err.get("code"), data=err)
        if resp.status_code >= 400:
            raise ZabbixError(f"Zabbix HTTP {resp.status_code}")
        return data.get("result")

    def version(self) -> str:
        result = self._post("apiinfo.version", [])
        return str(result or "")

    def login(self) -> str:
        token = (self.source.token or "").strip()
        if token:
            self._auth = token
            self._auth_kind = "token"
            return token

        cached = self._load_cached_session()
        if cached:
            self._auth = cached
            self._auth_kind = "session"
            return cached

        user = (self.source.username or "").strip()
        password = self.source.password or ""
        if not user or not password:
            raise ZabbixError(
                "Zabbix kimlik bilgisi yok: API token veya kullanıcı+şifre gerekli"
            )

        last_err: Optional[Exception] = None
        # Sürüme göre doğru login alanı (7.x = username; eski = user)
        ver = ""
        try:
            ver = self.version()
        except Exception:
            pass
        major = 0
        try:
            major = int(str(ver).split(".")[0])
        except Exception:
            major = 0

        attempts: List[Dict[str, str]] = []
        if major >= 6:
            attempts = [{"username": user, "password": password}]
        elif major > 0:
            attempts = [{"user": user, "password": password}]
        else:
            # sürüm alınamadı — önce yeni, sonra eski
            attempts = [
                {"username": user, "password": password},
                {"user": user, "password": password},
            ]

        for params in attempts:
            try:
                result = self._post("user.login", params)
                auth = str(result or "")
                if not auth:
                    raise ZabbixError("user.login boş auth döndü")
                self._auth = auth
                self._auth_kind = "session"
                self._store_session(auth)
                return auth
            except ZabbixError as e:
                last_err = e
                # Yanlış şifre / kilit — diğer param formatını deneme
                msg = str(e).lower()
                if "password" in msg or "blocked" in msg or "incorrect" in msg:
                    break
                # "unexpected parameter username" → eski API; user dene
                if "unexpected parameter" in msg and "username" in msg and major == 0:
                    continue
                if "unexpected parameter" in msg and "user" in msg:
                    break
                continue
        raise ZabbixError(str(last_err) if last_err else "Zabbix login başarısız")

    def ensure_auth(self) -> None:
        if self._auth:
            return
        self.login()

    def call(self, method: str, params: Any = None) -> Any:
        if method == "apiinfo.version":
            return self._post(method, params)
        self.ensure_auth()
        try:
            return self._post(
                method,
                params,
                auth=None if self._auth_kind == "token" else self._auth,
            )
        except ZabbixError as e:
            # Session expired → bir kez yenile
            if self._auth_kind == "session" and e.code in (-32602, -32500, -32600):
                self.clear_session()
                self.login()
                return self._post(method, params, auth=self._auth)
            raise

    def hostgroups(self, search: str = "", limit: int = 200) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "output": ["groupid", "name"],
            "sortfield": "name",
            "limit": limit,
        }
        if search.strip():
            params["search"] = {"name": search.strip()}
            params["searchWildcardsEnabled"] = True
        rows = self.call("hostgroup.get", params) or []
        return rows if isinstance(rows, list) else []

    def hosts(
        self,
        *,
        groupids: Optional[List[str]] = None,
        search: str = "",
        limit: int = 200,
        monitored_only: bool = True,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "output": ["hostid", "host", "name", "status", "available", "description"],
            "selectGroups": ["groupid", "name"],
            "selectInterfaces": ["ip", "dns", "port", "type", "main"],
            "sortfield": "name",
            "limit": limit,
        }
        if monitored_only:
            params["filter"] = {"status": 0}  # enabled
        if groupids:
            params["groupids"] = groupids
        if search.strip():
            params["search"] = {"name": search.strip(), "host": search.strip()}
            params["searchWildcardsEnabled"] = True
            params["searchByAny"] = True
        rows = self.call("host.get", params) or []
        return rows if isinstance(rows, list) else []

    def items_for_hosts(
        self,
        hostids: List[str],
        *,
        search_keys: Optional[List[str]] = None,
        search: str = "",
        limit: int = 500,
    ) -> List[Dict[str, Any]]:
        if not hostids:
            return []
        params: Dict[str, Any] = {
            "output": [
                "itemid", "hostid", "name", "key_", "value_type",
                "units", "lastvalue", "lastclock", "status", "state",
            ],
            "hostids": hostids,
            "filter": {"status": 0},
            "sortfield": "name",
            "limit": limit,
        }
        if search.strip():
            params["search"] = {"name": search.strip(), "key_": search.strip()}
            params["searchWildcardsEnabled"] = True
            params["searchByAny"] = True
        if search_keys:
            # Exact key filter when possible
            params["filter"] = {**(params.get("filter") or {}), "key_": search_keys}
        rows = self.call("item.get", params) or []
        return rows if isinstance(rows, list) else []

    def history(
        self,
        itemids: List[str],
        *,
        value_type: int = 0,
        time_from: int,
        time_till: int,
        limit: int = 5000,
    ) -> List[Dict[str, Any]]:
        if not itemids:
            return []
        # uint → history=3; float → 0
        hist = 3 if int(value_type) == 3 else 0
        params = {
            "output": "extend",
            "history": hist,
            "itemids": itemids,
            "time_from": int(time_from),
            "time_till": int(time_till),
            "sortfield": "clock",
            "sortorder": "ASC",
            "limit": limit,
        }
        rows = self.call("history.get", params) or []
        return rows if isinstance(rows, list) else []

    def problems(
        self,
        *,
        hostids: Optional[List[str]] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        params: Dict[str, Any] = {
            "output": "extend",
            "recent": True,
            "sortfield": ["eventid"],
            "sortorder": "DESC",
            "limit": limit,
        }
        if hostids:
            params["hostids"] = hostids
        # Zabbix 7 bazı kurulumlarda selectHosts reddeder — denemeli al
        for extra in (
            {"selectHosts": ["hostid", "host", "name"]},
            {},
        ):
            try:
                rows = self.call("problem.get", {**params, **extra}) or []
                return rows if isinstance(rows, list) else []
            except ZabbixError as e:
                if "selectHosts" in str(e) and extra:
                    continue
                raise
        return []


def client_from_source(source: MonitoringSource) -> ZabbixClient:
    return ZabbixClient(source)
