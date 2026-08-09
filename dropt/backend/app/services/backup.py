"""Admin backup helpers: app_settings export/import + Postgres dump/restore."""

from __future__ import annotations

import gzip
import os
import subprocess
import tempfile
from datetime import datetime, timezone
from typing import Any

from sqlmodel import Session, select

from app.core.config import get_settings
from app.models.settings import AppSetting

# Never export unless include_secrets=true
_SECRET_KEYS = frozenset(
    {
        "automation_password",
        "assistant_gateway_api_key",
    }
)


def _pg_url() -> str:
    raw = (os.environ.get("DATABASE_URL") or "").strip()
    if not raw:
        raise RuntimeError("DATABASE_URL tanımlı değil")
    return raw.replace("postgresql+psycopg://", "postgresql://", 1)


def export_settings_payload(session: Session, *, include_secrets: bool = False) -> dict[str, Any]:
    rows = session.exec(select(AppSetting)).all()
    settings: dict[str, str] = {}
    redacted: list[str] = []
    for row in rows:
        if row.key in _SECRET_KEYS and not include_secrets:
            redacted.append(row.key)
            continue
        settings[row.key] = row.value or ""
    return {
        "format": "dropt-settings-v1",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "app_version": get_settings().app_version,
        "include_secrets": include_secrets,
        "redacted_keys": sorted(redacted),
        "settings": settings,
    }


def import_settings_payload(session: Session, payload: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Geçersiz JSON")
    fmt = payload.get("format")
    if fmt not in {"dropt-settings-v1", None}:
        raise ValueError(f"Bilinmeyen format: {fmt}")
    data = payload.get("settings")
    if not isinstance(data, dict) or not data:
        raise ValueError("settings objesi gerekli")
    updated = 0
    created = 0
    for key, value in data.items():
        k = str(key).strip()
        if not k or len(k) > 128:
            continue
        v = "" if value is None else str(value)
        if len(v) > 2048:
            raise ValueError(f"Değer çok uzun: {k}")
        row = session.get(AppSetting, k)
        if row is None:
            session.add(AppSetting(key=k, value=v))
            created += 1
        else:
            row.value = v
            session.add(row)
            updated += 1
    session.commit()
    return {"created": created, "updated": updated, "total": created + updated}


def dump_database_sql_gz() -> bytes:
    url = _pg_url()
    proc = subprocess.run(
        ["pg_dump", "--dbname", url, "--no-owner", "--no-acl", "--clean", "--if-exists"],
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or b"").decode("utf-8", errors="replace")[:500]
        raise RuntimeError(f"pg_dump başarısız: {err}")
    return gzip.compress(proc.stdout)


def restore_database_sql_gz(blob: bytes) -> str:
    """Apply dump. Prefer dumps without DROP of active connections issues."""
    url = _pg_url()
    try:
        sql = gzip.decompress(blob)
    except OSError:
        sql = blob  # plain sql
    with tempfile.NamedTemporaryFile(prefix="dropt-restore-", suffix=".sql", delete=False) as tmp:
        tmp.write(sql)
        path = tmp.name
    try:
        proc = subprocess.run(
            ["psql", "--dbname", url, "-v", "ON_ERROR_STOP=1", "-f", path],
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            err = (proc.stderr or b"").decode("utf-8", errors="replace")[:800]
            raise RuntimeError(f"psql restore başarısız: {err}")
        return (proc.stdout or b"").decode("utf-8", errors="replace")[-2000:]
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def dump_filename() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"dttportal-{stamp}.sql.gz"
