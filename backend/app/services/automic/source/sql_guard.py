"""Kaynak DB'ye (automic_source) giden her SQL için salt okunur doğrulama.

Kaynak türünden bağımsızdır: yalnızca tek bir SELECT / WITH … SELECT ifadesine izin verir.
"""
from __future__ import annotations

import re

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|merge|drop|create|alter|truncate|grant|revoke|rename|"
    r"comment|lock|call|execute|exec|begin|declare|commit|rollback|savepoint|"
    r"purge|analyze|associate|disassociate|flashback|explain|"
    r"dbms_\w+|utl_\w+|sys\.\w+)\b",
    re.IGNORECASE,
)
_FOR_UPDATE = re.compile(r"\bfor\s+update\b", re.IGNORECASE)
_INTO = re.compile(r"\binto\s+\w+", re.IGNORECASE)  # SELECT … INTO
_STRING_LIT = re.compile(r"'(?:[^']|'')*'")


class UnsafeSqlError(ValueError):
    pass


def assert_read_only(sql: str) -> str:
    """Yalnızca tek bir SELECT/WITH ifadesine izin verir; aksi halde UnsafeSqlError."""
    if not sql or not sql.strip():
        raise UnsafeSqlError("Boş SQL")
    body = _STRING_LIT.sub("''", sql).strip().rstrip(";").strip()
    # Çoklu ifade: kalan ';'
    if ";" in body:
        raise UnsafeSqlError("Birden fazla ifade / ';' yasak")
    if "--" in body or "/*" in body:
        raise UnsafeSqlError("SQL yorumu yasak")
    first = body.split(None, 1)[0].lower()
    if first not in ("select", "with"):
        raise UnsafeSqlError("Yalnızca SELECT/WITH çalıştırılabilir")
    if _FOR_UPDATE.search(body):
        raise UnsafeSqlError("FOR UPDATE yasak")
    # SELECT INTO (PL/SQL) — SELECT ile başlayıp FROM öncesi INTO
    if first == "select":
        head = re.split(r"\bfrom\b", body, maxsplit=1, flags=re.I)[0]
        if re.search(r"\binto\b", head, re.I):
            raise UnsafeSqlError("SELECT INTO yasak")
    m = _FORBIDDEN.search(body)
    if m:
        raise UnsafeSqlError(f"Yasaklı anahtar kelime: {m.group(1)}")
    return sql
