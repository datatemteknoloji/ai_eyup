"""Gerçek VBR yanıtlarını fixture'a çevirirken maskeleme (F.4).

Maskelenenler: host adları (FQDN), IP adresleri, kullanıcı adları (``DOMAIN\\user``, ``user@domain``,
``Created by …``, ``initiatedBy``, ``userName``) ve yollar (Windows/UNC/Unix). Maskeleme DETERMİNİSTİKTİR
(aynı değer her yerde aynı takma ada gider) — bu sayede ``jobs[].virtualMachines.includes[].hostName`` ile
``backupObjects[].path`` içindeki host eşleşmesi korunur.

Maskelenmeyenler: UUID'ler, VM/iş/depo adları (eşleştirme mantığı için). Bunlar hassassa ``--mask-names``.
Maskeleme bir garanti değildir: dosyaları paylaşmadan önce gözle kontrol edin (script bunu da yazdırır).
"""
from __future__ import annotations

import ipaddress
import re
from typing import Any, Dict, Optional

_UUID_RX = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
_IPV4_RX = re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")
# FQDN: en az iki etiket + alfabetik TLD (sürüm numaralarını — 13.0.1.180 — yakalamaz)
_FQDN_RX = re.compile(r"\b(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,24}\b")
_DOMAIN_USER_RX = re.compile(r"\b([A-Za-z0-9_.-]+)\\([A-Za-z0-9_.$-]+)\b")
_EMAIL_RX = re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b")
_WIN_PATH_RX = re.compile(r"^(?:[A-Za-z]:\\|\\\\)")
_UNIX_PATH_RX = re.compile(r"^/\S+$")
_MASKED_SEG_RX = re.compile(r"^(?:MASKED|seg\d+|host-\d+\.example\.invalid)$")
_USER_KEYS = {"initiatedby", "username", "user", "owner", "createdby", "accountname"}
_HOST_KEYS = {"hostname", "dnsname", "servername", "host"}
_PATH_KEYS = {"path", "folder", "directory", "mountpath"}
_TLD_KEEP = {"json", "yaml", "yml"}


def _is_ip(s: str) -> bool:
    try:
        ipaddress.ip_address(s)
        return True
    except ValueError:
        return False


class Masker:
    def __init__(self, *, mask_names: bool = False):
        self.mask_names = mask_names
        self._maps: Dict[str, Dict[str, str]] = {k: {} for k in ("host", "ip", "user", "path", "name")}

    def _alias(self, kind: str, raw: str, fmt: str) -> str:
        m = self._maps[kind]
        if raw not in m:
            m[raw] = fmt.format(len(m) + 1)
        return m[raw]

    # ── tekil değerler ──────────────────────────────────────────────────────
    def host(self, v: str) -> str:
        v0 = v.strip()
        if _is_ip(v0):
            return self.ip(v0)
        return self._alias("host", v0.lower(), "host-{}.example.invalid")

    def ip(self, v: str) -> str:
        return self._alias("ip", v, "192.0.2.{}")      # RFC 5737 TEST-NET-1

    def user(self, v: str) -> str:
        return self._alias("user", v, "user{}")

    def path(self, v: str) -> str:
        if "\\" in v and not _WIN_PATH_RX.match(v):
            # backupObjects path: "<vcenter>\\<datacenter>\\...\\<vm>" — ilk bölüm host (tutarlı alias), son bölüm korunur
            parts = v.split("\\")
            head = self.host(parts[0]) if parts[0] else parts[0]
            mid = [self._alias("path", p, "seg{}") for p in parts[1:-1]]
            return "\\".join([head, *mid, parts[-1]]) if len(parts) > 1 else head
        return self._alias("path", v, "/masked/path{}")

    # ── serbest metin ───────────────────────────────────────────────────────
    def text(self, s: str) -> str:
        if _UUID_RX.match(s):
            return s
        out = _EMAIL_RX.sub(lambda m: self.user(m.group(0)) + "@example.invalid", s)
        out = _DOMAIN_USER_RX.sub(lambda m: f"MASKED\\{self.user(m.group(0))}", out)
        out = _IPV4_RX.sub(lambda m: self.ip(m.group(0)), out)

        def _fq(m: "re.Match[str]") -> str:
            tok = m.group(0)
            if tok.lower().endswith(".invalid") or tok.split(".")[-1].lower() in _TLD_KEEP:
                return tok
            return self.host(tok)
        return _FQDN_RX.sub(_fq, out)

    # ── ağaç ────────────────────────────────────────────────────────────────
    def mask(self, obj: Any, key: Optional[str] = None) -> Any:
        if isinstance(obj, dict):
            return {k: self.mask(v, k) for k, v in obj.items()}
        if isinstance(obj, list):
            return [self.mask(v, key) for v in obj]
        if not isinstance(obj, str) or not obj:
            return obj
        kl = (key or "").lower()
        if _UUID_RX.match(obj) or "version" in kl or kl in ("build", "revision"):
            return obj          # sürüm/derleme numaraları (ör. 13.0.1.180) IP gibi görünür ama hassas değildir
        if kl in _HOST_KEYS:
            return self.host(obj)
        if kl in _USER_KEYS:
            return self.user(obj)
        if kl in _PATH_KEYS or _WIN_PATH_RX.match(obj) or (_UNIX_PATH_RX.match(obj) and obj.count("/") >= 2):
            return self.path(obj)
        if self.mask_names and kl == "name":
            return self._alias("name", obj, "name{}")
        return self.text(obj)

    def mapping_sizes(self) -> Dict[str, int]:
        return {k: len(v) for k, v in self._maps.items()}


def leaks(masked: Any) -> list[str]:
    """Maskelenmiş JSON'da kalan olası sızıntılar (IP ≠ 192.0.2.x, FQDN ≠ *.invalid, DOMAIN\\user, e-posta)."""
    found: list[str] = []

    def walk(o: Any, key: str = "") -> None:
        if isinstance(o, dict):
            for k, v in o.items():
                walk(v, str(k))
        elif isinstance(o, list):
            for v in o:
                walk(v, key)
        elif isinstance(o, str):
            if "version" in key.lower() or key.lower() in ("build", "revision"):
                return
            for m in _IPV4_RX.findall(o):
                if not m.startswith("192.0.2."):
                    found.append(f"ip:{m}")
            for m in _FQDN_RX.findall(o):
                if not m.lower().endswith(".invalid") and m.split(".")[-1].lower() not in _TLD_KEEP:
                    found.append(f"fqdn:{m}")
            for m in _EMAIL_RX.findall(o):
                if not m.endswith("@example.invalid") and "example.invalid" not in m:
                    found.append(f"email:{m}")
            for m in _DOMAIN_USER_RX.finditer(o):
                if not _MASKED_SEG_RX.match(m.group(1)):    # maskeli yol parçaları (host-N…\segN) kullanıcı sayılmaz
                    found.append(f"user:{m.group(0)}")
    walk(masked)
    return sorted(set(found))
