"""
OpenText / Micro Focus uCMDB REST API istemcisi.

Base URL örnekleri:
  https://ucmdb.example.com:8443/rest-api
  https://ucmdb.example.com:8443/ucmdb-server/rest-api  (container)

Akış:
  POST /authenticate  → JWT
  Authorization: Bearer <token>
  POST /topologyQuery  → CI + ilişkiler
  POST /topology       → kayıtlı TQL adı ile sonuç (veya job id + chunk)
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

DEFAULT_LAYOUT = [
    "name",
    "display_label",
    "primary_ip_address",
    "primary_dns_name",
    "discovered_os_name",
    "os_description",
    "os_family",
    "os_version",
    "memory_size",
    "cpu_number",
    "number_of_processors",
    "node_role",
    "serial_number",
    "data_center",
    "location",
    "environment",
    "vendor",
    "model_name",
    "description",
    "global_id",
    "root_id",
]


class UcmdbClientError(Exception):
    pass


class UcmdbClient:
    def __init__(
        self,
        base_url: str,
        username: str,
        password: str,
        *,
        verify_ssl: bool = True,
        timeout: float = 120.0,
    ):
        self.base_url = (base_url or "").rstrip("/")
        self.username = username or ""
        self.password = password or ""
        self.verify_ssl = bool(verify_ssl)
        self.timeout = timeout
        self._token: Optional[str] = None
        if not self.base_url:
            raise UcmdbClientError("uCMDB base_url gerekli")
        if not self.username or not self.password:
            raise UcmdbClientError("uCMDB kullanıcı adı ve parola gerekli")

    def _headers(self) -> Dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        if self._token:
            h["Authorization"] = f"Bearer {self._token}"
        return h

    def authenticate(self) -> str:
        url = f"{self.base_url}/authenticate"
        payload = {
            "username": self.username,
            "password": self.password,
            "clientContext": 1,
        }
        try:
            with httpx.Client(verify=self.verify_ssl, timeout=self.timeout) as client:
                r = client.post(url, json=payload, headers={"Content-Type": "application/json"})
        except httpx.HTTPError as e:
            raise UcmdbClientError(f"uCMDB bağlantı hatası: {e}") from e

        if r.status_code >= 400:
            detail = r.text[:400]
            raise UcmdbClientError(f"Kimlik doğrulama başarısız ({r.status_code}): {detail}")

        data = r.json() if r.content else {}
        token = data.get("token") or data.get("Token")
        if not token:
            raise UcmdbClientError("uCMDB token dönmedi — kullanıcı SDK yetkisini kontrol edin")
        self._token = token
        return token

    def ensure_auth(self) -> None:
        if not self._token:
            self.authenticate()

    def topology_query(
        self,
        *,
        ci_types: List[str],
        layout: Optional[List[str]] = None,
        include_subtypes: bool = True,
        relations: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """CI tip(ler)i için topologyQuery çalıştırır."""
        self.ensure_auth()
        layout = layout or DEFAULT_LAYOUT
        nodes = []
        for i, ci_type in enumerate(ci_types):
            ct = (ci_type or "").strip()
            if not ct:
                continue
            nodes.append(
                {
                    "type": ct,
                    "queryIdentifier": f"n{i}",
                    "visible": True,
                    "includeSubtypes": include_subtypes,
                    "layout": layout,
                    "attributeConditions": [],
                    "linkConditions": [],
                }
            )
        if not nodes:
            raise UcmdbClientError("En az bir CI tipi gerekli")

        body: Dict[str, Any] = {"nodes": nodes, "relations": relations or []}
        url = f"{self.base_url}/topologyQuery"
        with httpx.Client(verify=self.verify_ssl, timeout=self.timeout) as client:
            r = client.post(url, json=body, headers=self._headers())
            if r.status_code == 401:
                self.authenticate()
                r = client.post(url, json=body, headers=self._headers())
        if r.status_code >= 400:
            raise UcmdbClientError(f"topologyQuery hatası ({r.status_code}): {r.text[:500]}")
        return r.json() if r.content else {}

    def topology_named(self, tql_name: str) -> Dict[str, Any]:
        """Kayıtlı TQL adıyla sonuç al (POST /topology)."""
        self.ensure_auth()
        name = (tql_name or "").strip()
        if not name:
            raise UcmdbClientError("TQL adı boş")
        url = f"{self.base_url}/topology"
        with httpx.Client(verify=self.verify_ssl, timeout=self.timeout) as client:
            r = client.post(url, content=name, headers={**self._headers(), "Content-Type": "text/plain"})
            if r.status_code == 401:
                self.authenticate()
                r = client.post(url, content=name, headers={**self._headers(), "Content-Type": "text/plain"})
            if r.status_code >= 400:
                r = client.post(url, json={"name": name}, headers=self._headers())
                if r.status_code >= 400:
                    raise UcmdbClientError(f"topology (TQL) hatası ({r.status_code}): {r.text[:500]}")
            data = r.json() if r.content else {}

            job_id = data.get("id") or data.get("queryResultId")
            if job_id and "cis" not in data and "CIs" not in data:
                chunk_url = f"{self.base_url}/topology/result/{job_id}/1"
                cr = client.get(chunk_url, headers=self._headers())
                if cr.status_code >= 400:
                    raise UcmdbClientError(f"topology result hatası ({cr.status_code}): {cr.text[:500]}")
                return cr.json() if cr.content else {}
            return data

    def fetch_cis(
        self,
        *,
        ci_types: Optional[List[str]] = None,
        tql_name: Optional[str] = None,
        layout: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """CI listesini düzleştirilmiş dict listesi olarak döner."""
        if tql_name and tql_name.strip():
            raw = self.topology_named(tql_name.strip())
        else:
            raw = self.topology_query(ci_types=ci_types or ["node"], layout=layout)
        return flatten_cis(raw)


def flatten_cis(payload: Any) -> List[Dict[str, Any]]:
    """uCMDB JSON yanıtından CI listesi çıkarır (sürüm farklarına toleranslı)."""
    if not payload:
        return []
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = (
            payload.get("cis")
            or payload.get("CIs")
            or payload.get("cisWithProperties")
            or (payload.get("data") or {}).get("cis")
            or (payload.get("queryResult") or {}).get("cis")
            or []
        )
    else:
        return []

    out: List[Dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        props = item.get("properties") or item.get("Properties") or {}
        if not isinstance(props, dict):
            props = {}
        flat = {**props}
        for k in ("ucmdbId", "ucmdb_id", "id", "type", "typeName", "ciType"):
            if k in item and k not in flat:
                flat[k] = item[k]
        if item.get("type"):
            flat.setdefault("ci_type", item["type"])
        if item.get("ucmdbId"):
            flat.setdefault("ucmdb_id", item["ucmdbId"])
        out.append(flat)
    return out
