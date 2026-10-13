"""SQL şablonları: mantıksal alan → sütun eşlemesi + sorgu iskeletleri."""
from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .sql_guard import assert_read_only

_SQL_DIR = Path(__file__).parent / "sql"
_IDENT = re.compile(r"^[A-Za-z][A-Za-z0-9_$#]{0,127}$")


def safe_ident(name: str) -> str:
    if not name or not _IDENT.match(name):
        raise ValueError(f"Geçersiz tanımlayıcı: {name!r}")
    return name.upper()


def list_profiles(engine: str) -> List[str]:
    d = _SQL_DIR / engine
    if not d.is_dir():
        return []
    return sorted(p.stem for p in d.glob("*.yaml"))


@lru_cache(maxsize=16)
def load_profile(engine: str, profile: str) -> Dict[str, Any]:
    path = _SQL_DIR / engine / f"{profile}.yaml"
    if not path.is_file():
        raise FileNotFoundError(f"SQL şablonu bulunamadı: {engine}/{profile}")
    with path.open(encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def resolve_mapping(profile: Dict[str, Any], columns_by_table: Dict[str, set]) -> Dict[str, Any]:
    """Keşfedilen sütunlarla şablonu eşleştirir.

    Dönen: {logical_table: {"table": T|None, "columns": {field: col}, "missing_required": [...],
            "missing_optional": [...], "available": bool}}
    """
    out: Dict[str, Any] = {}
    for lname, spec in (profile.get("tables") or {}).items():
        table = next((t.upper() for t in spec.get("table") or [] if t.upper() in columns_by_table), None)
        cols = columns_by_table.get(table or "", set())
        mapped: Dict[str, str] = {}
        miss_req: List[str] = []
        miss_opt: List[str] = []
        for kind, target in (("required", miss_req), ("optional", miss_opt)):
            for field, cands in (spec.get(kind) or {}).items():
                col = next((c.upper() for c in cands or [] if c.upper() in cols), None)
                if col:
                    mapped[field] = col
                else:
                    target.append(field)
        out[lname] = {
            "table": table,
            "columns": mapped,
            "missing_required": miss_req if table else list((spec.get("required") or {}).keys()),
            "missing_optional": miss_opt,
            "available": bool(table) and not miss_req,
        }
    return out


_PLACEHOLDER = re.compile(r"\{f:([a-z_]+)\}")


# FETCH FIRST zorunlu üst sınır (çağıran limit vermezse)
_DEFAULT_FETCH_CAP = 500
# Aggregate / tek satır şablonları — yine de FETCH 1
_SINGLE_ROW = frozenset({
    "latest_run_id", "min_run_id", "execution_by_id", "report_count", "object_header_by_name",
    "user_object_id_bounds", "count_ended_by_id_range", "table_row_count",
})


def render(profile: Dict[str, Any], query: str, *, schema: str, table_map: Dict[str, Any],
           fields: Optional[List[str]] = None, clients_bind: Optional[str] = None,
           ids_bind: Optional[str] = None, limit: Optional[int] = None,
           default_limit: Optional[int] = None) -> str:
    """Sorgu iskeletini eşlemeyle doldurur; guard'dan geçirir. Her zaman FETCH FIRST ekler."""
    tpl = (profile.get("queries") or {}).get(query)
    if not tpl:
        raise KeyError(f"Şablonda sorgu yok: {query}")
    cols: Dict[str, str] = table_map.get("columns") or {}
    table = safe_ident(table_map.get("table") or "")
    qualified = f"{safe_ident(schema)}.{table}" if schema else table

    def _col(field: str) -> str:
        c = cols.get(field)
        if not c:
            raise KeyError(f"Alan eşlenmemiş: {field}")
        return safe_ident(c)

    sql = _PLACEHOLDER.sub(lambda m: _col(m.group(1)), " ".join(tpl.split()))
    if "{sel}" in sql:
        sel_parts = []
        for i, f in enumerate(fields or []):
            c = cols.get(f)
            sel_parts.append(f"{safe_ident(c)} AS F{i}" if c else f"NULL AS F{i}")
        sql = sql.replace("{sel}", ", ".join(sel_parts) or "1")
    sql = sql.replace("{t}", qualified)
    if "{clients}" in sql:
        sql = sql.replace("{clients}", clients_bind or "NULL")
    if "{ids}" in sql:
        sql = sql.replace("{ids}", ids_bind or "NULL")
    if "{live}" in sql:
        # OH_DeleteFlag (24.4 OH.md): 0=not deleted, 1=deleted, 2=versioned, 5=archived/reorganized.
        df = cols.get("delete_flag")
        live = f"AND ({safe_ident(df)} = 0 OR {safe_ident(df)} IS NULL)" if df else ""
        sql = sql.replace("{live}", live)
    if "FETCH FIRST" not in sql.upper():
        if query in _SINGLE_ROW:
            n = 1 if limit is None else max(1, int(limit))
        else:
            n = int(limit if limit is not None else (default_limit or _DEFAULT_FETCH_CAP))
            n = max(1, n)
        sql = f"{sql} FETCH FIRST {n} ROWS ONLY"
    return assert_read_only(sql)
