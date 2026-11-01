"""Tur izi için sır maskeleme (rolden bağımsız; kırpmadan ÖNCE uygulanır).

Kapsam: parola/token/api-key benzeri anahtarlar, Kubernetes Secret `data`/`stringData`,
`*-data` (kubeconfig), `.dockerconfigjson`, secret-benzeri env adları, JWT, Bearer,
PEM özel anahtar, URL içi kimlik bilgisi, satır içi `parola=...`. `managedFields` ve
`last-applied-configuration` gürültüsü düşürülür.
"""
from __future__ import annotations

import re
from typing import Any

MASK = "***"
_MAX_DEPTH = 14

_SECRET_KEY_RE = re.compile(
    r"(pass(word|wd)?|pwd|secret|token|api[_-]?key|private[_-]?key|authorization|"
    r"credential|ssh[_-]?key|client[_-]?key|cookie|dockerconfigjson|bearer)",
    re.IGNORECASE,
)
# Anahtar adında secret geçse de değer sır olmayan alanlar (ad/sayaç/tip/referans)
_SAFE_SUFFIX_RE = re.compile(
    r"(_?name|_?names|_?count|_?type|_?ref|_?refs|_?id|_?age|_?expiry|_?expires?(_at)?|"
    r"_?ttl|_?enabled|_?policy|_?namespace|_?kind)$",
    re.IGNORECASE,
)
_DATA_SUFFIX_RE = re.compile(r"-data$", re.IGNORECASE)
_DROP_KEYS = {"managedFields"}
_DROP_ANNOTATIONS = {"kubectl.kubernetes.io/last-applied-configuration"}

_JWT_RE = re.compile(r"eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]*")
_BEARER_RE = re.compile(r"(?i)\bbearer\s+[A-Za-z0-9._~+/=-]{12,}")
_PEM_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*(?:PRIVATE KEY|CERTIFICATE|ENCRYPTED)[A-Z0-9 ]*-----"
    r"(?:.*?-----END [A-Z0-9 ]*-----|.*\Z)",
    re.DOTALL,
)
_URL_CRED_RE = re.compile(r"(?i)\b([a-z][a-z0-9+.-]*://[^\s/:@]+):([^\s/@]+)@")
_INLINE_RE = re.compile(
    r"(?i)\b(pass(?:word|wd)?|pwd|secret|token|api[_-]?key|client[_-]?secret)\b(\s*[=:]\s*)(?!\*{3})([^\s,;\"']+)"
)
_SK_RE = re.compile(r"\b(?:sk|pk|ghp|gho|xox[abp])[-_][A-Za-z0-9_-]{16,}\b")
_AWS_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")


def mask_text(s: str) -> str:
    if not isinstance(s, str) or not s:
        return s
    out = _PEM_RE.sub(MASK, s)
    out = _JWT_RE.sub(MASK, out)
    out = _BEARER_RE.sub("Bearer " + MASK, out)
    out = _URL_CRED_RE.sub(lambda m: f"{m.group(1)}:{MASK}@", out)
    out = _INLINE_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{MASK}", out)
    out = _SK_RE.sub(MASK, out)
    out = _AWS_RE.sub(MASK, out)
    return out


def _is_secret_key(key: str) -> bool:
    k = str(key)
    if _DATA_SUFFIX_RE.search(k):
        return True
    if not _SECRET_KEY_RE.search(k):
        return False
    return not _SAFE_SUFFIX_RE.search(k)


def _mask_env_list(items: list) -> bool:
    """[{"name": "DB_PASSWORD", "value": "x"}] biçimini tanır."""
    return bool(items) and all(
        isinstance(i, dict) and "name" in i and ("value" in i) for i in items
    )


def mask_obj(obj: Any, _depth: int = 0, _in_secret: bool = False) -> Any:
    """JSON-benzeri nesneyi maskeler (yeni nesne döner; girdiyi değiştirmez)."""
    if _depth > _MAX_DEPTH:
        return MASK
    if isinstance(obj, str):
        return mask_text(obj)
    if isinstance(obj, (int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, dict):
        kind_secret = str(obj.get("kind", "")).lower() == "secret"
        out: dict = {}
        for k, v in obj.items():
            if k in _DROP_KEYS:
                continue
            if k == "annotations" and isinstance(v, dict):
                v = {a: b for a, b in v.items() if a not in _DROP_ANNOTATIONS}
            if _in_secret or (kind_secret and k in ("data", "stringData")):
                out[k] = _mask_values(v)
                continue
            if _is_secret_key(k) and not isinstance(v, (dict, list)):
                out[k] = MASK if v not in (None, "") else v
                continue
            out[k] = mask_obj(v, _depth + 1)
        return out
    if isinstance(obj, (list, tuple)):
        items = list(obj)
        if _mask_env_list(items):
            res = []
            for i in items:
                d = dict(i)
                if _is_secret_key(str(d.get("name", ""))) and d.get("value") not in (None, ""):
                    d["value"] = MASK
                res.append(mask_obj(d, _depth + 1))
            return res
        return [mask_obj(i, _depth + 1) for i in items]
    return mask_text(str(obj))


def _mask_values(v: Any) -> Any:
    """Secret data bloğu: anahtarlar kalır, tüm değerler maskelenir."""
    if isinstance(v, dict):
        return {k: (MASK if not isinstance(x, (dict, list)) else _mask_values(x)) for k, x in v.items()}
    if isinstance(v, list):
        return [_mask_values(x) for x in v]
    return MASK if v not in (None, "") else v
