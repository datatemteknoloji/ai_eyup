"""
NLQ query validator — allowlist, types, RBAC tier merge, injection checks.
"""
from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.nlq.schema import (
    ALLOWED_FIELDS,
    ALLOWED_INTENTS,
    ALLOWED_OPERATORS,
    DEFAULT_COLUMNS,
    DEFAULT_LIMIT,
    FIELD_TYPES,
    HARD_MAX_LIMIT,
    INJECTION_PATTERNS,
    operators_for_type,
)


class QueryValidationError(Exception):
    def __init__(self, message: str, invalid_field: Optional[str] = None, details: Optional[dict] = None):
        super().__init__(message)
        self.message = message
        self.invalid_field = invalid_field
        self.details = details or {}

    def as_dict(self) -> dict:
        d = {"status": "invalid_query", "message": self.message}
        if self.invalid_field:
            d["invalid_field"] = self.invalid_field
        d.update(self.details)
        return d


def _check_injection(value: Any) -> None:
    if value is None:
        return
    if isinstance(value, (list, tuple)):
        for v in value:
            _check_injection(v)
        return
    if not isinstance(value, str):
        return
    low = value.lower()
    for pat in INJECTION_PATTERNS:
        if pat in low:
            raise QueryValidationError(
                "Sorguda zararlı veya desteklenmeyen içerik tespit edildi.",
                details={"pattern": pat},
            )


def _coerce_number(value: Any, field: str) -> Any:
    if isinstance(value, bool):
        raise QueryValidationError(f"'{field}' için sayısal değer bekleniyor.")
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str) and value.strip():
        try:
            if "." in value:
                return float(value)
            return int(value)
        except ValueError:
            pass
    raise QueryValidationError(f"'{field}' için sayısal değer bekleniyor.", invalid_field=field)


def _normalize_filter(f: dict) -> dict:
    field = (f.get("field") or "").strip()
    op = (f.get("operator") or "").strip()
    value = f.get("value")

    if field not in ALLOWED_FIELDS:
        raise QueryValidationError(
            "Sorguda desteklenmeyen bir alan kullanıldı.",
            invalid_field=field or None,
        )
    if op not in ALLOWED_OPERATORS:
        raise QueryValidationError(
            f"Desteklenmeyen operatör: {op}",
            invalid_field=field,
        )
    ftype = FIELD_TYPES[field]
    allowed_ops = operators_for_type(ftype)
    if op not in allowed_ops:
        raise QueryValidationError(
            f"'{field}' alanı için '{op}' operatörü geçersiz.",
            invalid_field=field,
        )

    _check_injection(value)
    _check_injection(field)

    if op in ("is_null", "is_not_null"):
        return {"field": field, "operator": op, "value": None}

    if op == "between":
        if not isinstance(value, (list, tuple)) or len(value) != 2:
            raise QueryValidationError("'between' için [min, max] değeri gerekir.", invalid_field=field)
        if ftype == "number":
            value = [_coerce_number(value[0], field), _coerce_number(value[1], field)]
        return {"field": field, "operator": op, "value": list(value)}

    if op in ("in", "not_in"):
        if not isinstance(value, (list, tuple)) or len(value) == 0:
            raise QueryValidationError(f"'{op}' için boş olmayan liste gerekir.", invalid_field=field)
        if ftype == "number":
            value = [_coerce_number(v, field) for v in value]
        elif ftype == "string":
            value = [str(v) for v in value]
        return {"field": field, "operator": op, "value": list(value)}

    if ftype == "number":
        value = _coerce_number(value, field)
        # uptime_days filter → keep as days; builder converts to seconds
    elif ftype == "boolean":
        if isinstance(value, str):
            value = value.strip().lower() in ("1", "true", "yes", "evet", "on")
        else:
            value = bool(value)
    elif ftype == "string":
        if value is None:
            raise QueryValidationError(f"'{field}' için değer gerekir.", invalid_field=field)
        value = str(value)
        # environment aliases
        if field == "environment":
            aliases = {
                "prod": "production", "production": "production",
                "prd": "production", "üretilmiş": "production",
                "stage": "staging", "staging": "staging", "test": "staging",
                "dev": "development", "development": "development",
            }
            value = aliases.get(value.lower(), value.lower())
    elif ftype == "datetime":
        if isinstance(value, (int, float)):
            # relative days ago handled by builder when operator suggests
            pass
        elif isinstance(value, str):
            value = value.strip()

    return {"field": field, "operator": op, "value": value}


def validate_query(
    raw: dict,
    *,
    allowed_tiers: Optional[List[str]] = None,
    force_live_check: Optional[bool] = None,
) -> dict:
    """
    Returns normalized query dict.
    allowed_tiers: None = no restriction; else list of permitted environments/tiers.
    """
    if not isinstance(raw, dict):
        raise QueryValidationError("Sorgu JSON nesne olmalıdır.")

    intent = (raw.get("intent") or "").strip()
    if intent == "unsupported":
        return {
            "intent": "unsupported",
            "reason": raw.get("reason") or "Bu soru mevcut veri modeliyle cevaplanamıyor.",
            "missing_fields": raw.get("missing_fields") or [],
        }
    if intent not in ALLOWED_INTENTS:
        raise QueryValidationError(f"Desteklenmeyen intent: {intent}")

    filters_in = raw.get("filters") or []
    if not isinstance(filters_in, list):
        raise QueryValidationError("'filters' bir dizi olmalıdır.")

    filters: List[dict] = []
    for f in filters_in:
        if not isinstance(f, dict):
            raise QueryValidationError("Her filtre bir nesne olmalıdır.")
        filters.append(_normalize_filter(f))

    # RBAC: restrict environment to allowed_tiers
    if allowed_tiers is not None:
        allowed = {t.lower() for t in allowed_tiers if t}
        env_filters = [f for f in filters if f["field"] == "environment"]
        for ef in env_filters:
            if ef["operator"] == "=" and str(ef["value"]).lower() not in allowed:
                raise QueryValidationError(
                    "Bu ortama erişim yetkiniz yok.",
                    invalid_field="environment",
                )
            if ef["operator"] == "in":
                narrowed = [v for v in ef["value"] if str(v).lower() in allowed]
                if not narrowed:
                    raise QueryValidationError(
                        "Bu ortam listesine erişim yetkiniz yok.",
                        invalid_field="environment",
                    )
                ef["value"] = narrowed
        if not any(f["field"] == "environment" for f in filters) and allowed:
            filters.append({
                "field": "environment",
                "operator": "in",
                "value": sorted(allowed),
            })

    sort = raw.get("sort")
    if sort is not None:
        if not isinstance(sort, dict):
            raise QueryValidationError("'sort' bir nesne olmalıdır.")
        sf = (sort.get("field") or "").strip()
        direction = (sort.get("direction") or "desc").strip().lower()
        if sf not in ALLOWED_FIELDS:
            raise QueryValidationError("Sort için desteklenmeyen alan.", invalid_field=sf)
        if direction not in ("asc", "desc"):
            raise QueryValidationError("Sort direction 'asc' veya 'desc' olmalıdır.")
        sort = {"field": sf, "direction": direction}

    limit = raw.get("limit", DEFAULT_LIMIT)
    try:
        limit = int(limit)
    except (TypeError, ValueError):
        raise QueryValidationError("'limit' sayı olmalıdır.")
    if limit < 1:
        limit = 1
    if limit > HARD_MAX_LIMIT:
        limit = HARD_MAX_LIMIT

    cols = raw.get("requested_columns") or list(DEFAULT_COLUMNS)
    if not isinstance(cols, list):
        cols = list(DEFAULT_COLUMNS)
    cols = [c for c in cols if c in ALLOWED_FIELDS]
    if not cols:
        cols = list(DEFAULT_COLUMNS)

    live_check = bool(raw.get("live_check", False))
    if force_live_check is not None:
        live_check = bool(force_live_check)

    return {
        "intent": "search_servers",
        "filters": filters,
        "sort": sort,
        "limit": limit,
        "live_check": live_check,
        "requested_columns": cols,
    }
