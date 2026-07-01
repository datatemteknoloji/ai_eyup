"""
OpenText UCMDB Integration API
Static import: CSV / Excel export from UCMDB → Server inventory
"""
from __future__ import annotations

import io
import json
import logging
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.models.server import Server

logger = logging.getLogger(__name__)
router = APIRouter()

# ── UCMDB field → our Server field mapping suggestions ───────────────────────
# Keys: common UCMDB column names (lowercase, stripped).
# Values: our Server model attribute names.
FIELD_SUGGESTIONS: Dict[str, str] = {
    # Name / identity
    "name":                    "name",
    "ci name":                 "name",
    "display label":           "name",
    "hostname":                "hostname",
    "primary hostname":        "hostname",
    "dns name":                "hostname",
    "host name":               "hostname",
    # IP
    "primary ip address":      "ip_address",
    "ip address":              "ip_address",
    "ip":                      "ip_address",
    "management ip":           "ip_address",
    # OS
    "os name":                 "os_type",
    "operating system":        "os_type",
    "os type":                 "os_type",
    "discovered os name":      "os_type",
    "os version":              "os_version",
    "os software version":     "os_version",
    # Hardware
    "cpu count":               "cpu_cores",
    "number of cpus":          "cpu_cores",
    "cpu":                     "cpu_cores",
    "memory size (mb)":        "memory_mb_raw",
    "memory size":             "memory_mb_raw",
    "physical memory (mb)":    "memory_mb_raw",
    "memory (gb)":             "memory_gb",
    # Type / environment
    "ci type":                 "server_type",
    "environment":             "tier",
    "tier":                    "tier",
    "business criticality":    "tier",
    # Description / notes
    "description":             "notes",
    "note":                    "notes",
}

# CI Type → os_type  (substring match, lowercase)
# Also determines is_virtual flag
CI_TYPE_MAP: List[tuple] = [
    # Windows physical/virtual
    ("windows",                 "windows",  False),
    # Linux / Unix physical/virtual
    ("unix",                    "linux",    False),
    ("linux",                   "linux",    False),
    ("red hat",                 "rhel",     False),
    ("rhel",                    "rhel",     False),
    ("suse",                    "sles",     False),
    ("ubuntu",                  "ubuntu",   False),
    # VMware virtual
    ("vmware virtual machine",  "",         True),
    ("vmware vm",               "",         True),
    ("virtual machine",         "",         True),
    # Hyper-V
    ("hyper-v",                 "windows",  True),
    # IBM physical
    ("ibm aix",                 "aix",      False),
    ("aix",                     "aix",      False),
    ("ibm server",              "",         False),
    ("ibm blade",               "",         False),
    # HP physical
    ("hp server",               "",         False),
    ("hp proliant",             "",         False),
    ("hp blade",                "",         False),
    # Dell physical
    ("dell",                    "",         False),
    # Physical generic
    ("physical server",         "",         False),
    ("bare metal",              "",         False),
    # Generic
    ("host",                    "",         False),
    ("node",                    "",         False),
    ("server",                  "",         False),
]

TIER_MAP: Dict[str, str] = {
    "production":    "critical",
    "prod":          "critical",
    "staging":       "high",
    "pre-prod":      "high",
    "test":          "medium",
    "qa":            "medium",
    "development":   "low",
    "dev":           "low",
}


# ── Helpers ───────────────────────────────────────────────────────────────────

def _parse_file(content: bytes, filename: str) -> List[Dict[str, str]]:
    """Parse CSV or Excel file into list of dicts."""
    import pandas as pd

    name_lower = filename.lower()
    try:
        if name_lower.endswith((".xlsx", ".xls")):
            df = pd.read_excel(io.BytesIO(content), dtype=str)
        else:
            # Try common CSV encodings
            for enc in ("utf-8-sig", "utf-8", "latin-1", "cp1252"):
                try:
                    df = pd.read_csv(io.BytesIO(content), dtype=str, encoding=enc)
                    break
                except UnicodeDecodeError:
                    continue
            else:
                raise ValueError("Dosya kodlaması tanınamadı")

        df = df.where(df.notna(), other="")
        return df.to_dict(orient="records")
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"Dosya okunamadı: {exc}")


def _suggest_mapping(columns: List[str]) -> Dict[str, Optional[str]]:
    """Auto-suggest field mapping from column names."""
    mapping: Dict[str, Optional[str]] = {}
    for col in columns:
        key = col.strip().lower()
        mapping[col] = FIELD_SUGGESTIONS.get(key)
    return mapping


def _row_to_server_data(row: Dict[str, str], mapping: Dict[str, str]) -> Dict[str, Any]:
    """Apply mapping to a single row, returning a clean server dict."""
    data: Dict[str, Any] = {"source": "ucmdb"}
    for col, field in mapping.items():
        if not field or field == "__skip__":
            continue
        val = (row.get(col) or "").strip()
        if not val:
            continue
        data[field] = val

    # Normalise memory: if memory_mb_raw given → convert to memory_gb
    if "memory_mb_raw" in data:
        try:
            data["memory_gb"] = max(1, round(float(data.pop("memory_mb_raw")) / 1024))
        except (ValueError, TypeError):
            data.pop("memory_mb_raw", None)

    # Normalise cpu_cores to int
    if "cpu_cores" in data:
        try:
            data["cpu_cores"] = int(float(data["cpu_cores"]))
        except (ValueError, TypeError):
            data.pop("cpu_cores", None)

    # Derive os_type and is_virtual from server_type (CI Type)
    if "server_type" in data:
        ct = data["server_type"].lower()
        for kw, osname, is_virt in CI_TYPE_MAP:
            if kw in ct:
                if osname and "os_type" not in data:
                    data["os_type"] = osname
                data["_is_virtual"] = is_virt
                break

    # Normalise tier
    if "tier" in data:
        t = data["tier"].lower()
        data["tier"] = TIER_MAP.get(t, t[:20] if t else "unknown")

    # notes → store as JSON meta (we'll stash in connection_config)
    if "notes" in data:
        data["_notes"] = data.pop("notes")

    return data


# ── Schemas ───────────────────────────────────────────────────────────────────

class MappingConfirm(BaseModel):
    upload_id: str
    # column_name → server_field  (or "__skip__" to ignore)
    mapping: Dict[str, str]
    update_existing: bool = True    # update if hostname/IP already exists
    dry_run: bool = False           # preview only, don't write


# ── Endpoints ─────────────────────────────────────────────────────────────────

import secrets as _secrets
import time as _time

# Per-upload session cache: upload_id → {rows, filename, ts}
# TTL of 30 minutes; each authenticated user gets a unique upload_id so
# concurrent uploads from different users don't overwrite each other.
_upload_sessions: Dict[str, Dict[str, Any]] = {}
_UPLOAD_TTL = 1800  # 30 minutes


def _purge_expired_uploads() -> None:
    now = _time.time()
    expired = [k for k, v in _upload_sessions.items() if now - v["ts"] > _UPLOAD_TTL]
    for k in expired:
        del _upload_sessions[k]


@router.post("/preview")
async def preview_upload(file: UploadFile = File(...)):
    """
    Upload a UCMDB CSV/Excel export.
    Returns: upload_id (use in /import), columns, suggested field mapping, sample rows.
    """
    content = await file.read()
    if len(content) > 20 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Dosya 20 MB'dan büyük olamaz")

    rows = _parse_file(content, file.filename or "upload.csv")
    if not rows:
        raise HTTPException(status_code=422, detail="Dosyada veri bulunamadı")

    columns = list(rows[0].keys())
    mapping = _suggest_mapping(columns)

    # Store with a unique token — avoids cross-user data leakage
    _purge_expired_uploads()
    upload_id = _secrets.token_hex(16)
    _upload_sessions[upload_id] = {"rows": rows, "filename": file.filename, "ts": _time.time()}

    return {
        "upload_id": upload_id,
        "filename": file.filename,
        "total_rows": len(rows),
        "columns": columns,
        "suggested_mapping": mapping,
        "sample_rows": rows[:10],
    }


@router.post("/import")
def import_ucmdb(body: MappingConfirm, db: Session = Depends(get_db)):
    """
    Import UCMDB data using the upload_id returned by /preview.
    """
    session = _upload_sessions.get(body.upload_id)
    if not session:
        raise HTTPException(status_code=400, detail="Geçersiz veya süresi dolmuş upload_id — önce /preview endpoint'ine dosya yükleyin")
    rows = session["rows"]
    if not rows:
        raise HTTPException(status_code=400, detail="Önce /preview endpoint'ine dosya yükleyin")

    created = updated = skipped = 0
    errors: List[str] = []
    preview_list: List[Dict] = []

    for i, row in enumerate(rows):
        try:
            data = _row_to_server_data(row, body.mapping)
        except Exception as exc:
            errors.append(f"Satır {i+1}: {exc}")
            continue

        name = data.get("name", "").strip()
        ip   = data.get("ip_address", "").strip()
        host = data.get("hostname", "").strip()

        if not name and not ip and not host:
            skipped += 1
            continue

        # Use name as hostname fallback
        if not name:
            name = host or ip

        is_virt_preview = data.get("_is_virtual")
        ci_label = data.get("server_type", "")
        if is_virt_preview is True:
            category = "Sanal"
        elif is_virt_preview is False:
            category = "Fiziksel"
        else:
            category = ci_label or "?"

        preview_list.append({
            "name": name,
            "ip_address": ip,
            "hostname": host,
            "os_type": data.get("os_type", ""),
            "tier": data.get("tier", ""),
            "cpu_cores": data.get("cpu_cores"),
            "memory_gb": data.get("memory_gb"),
            "category": category,
            "server_type": ci_label,
        })

        if body.dry_run:
            continue

        # Find existing server by IP or hostname
        existing: Optional[Server] = None
        if ip:
            existing = db.query(Server).filter(Server.ip_address == ip).first()
        if not existing and host:
            existing = db.query(Server).filter(Server.hostname == host).first()
        if not existing and name:
            existing = db.query(Server).filter(Server.name == name).first()

        notes = data.pop("_notes", None)
        is_virtual = data.pop("_is_virtual", None)  # True/False/None

        meta: Dict[str, Any] = {"ucmdb_import": True}
        if notes:
            meta["ucmdb_notes"] = notes
        if is_virtual is not None:
            meta["ucmdb_is_virtual"] = is_virtual

        # Resolved server_type label
        raw_ci_type = data.get("server_type", "")
        if is_virtual is True and not raw_ci_type:
            data["server_type"] = "virtual"
        elif is_virtual is False and not raw_ci_type:
            data["server_type"] = "physical"

        if existing and body.update_existing:
            for field in ("ip_address", "hostname", "os_type", "os_version",
                          "cpu_cores", "memory_gb", "server_type", "tier"):
                v = data.get(field)
                if v is not None and v != "":
                    setattr(existing, field, v)
            cfg = dict(existing.connection_config or {})
            cfg.update(meta)
            existing.connection_config = cfg
            updated += 1
        elif existing:
            skipped += 1
        else:
            cfg = meta.copy()
            new_srv = Server(
                name=name,
                hostname=host or name,
                ip_address=ip or None,
                os_type=data.get("os_type", ""),
                os_version=data.get("os_version", ""),
                cpu_cores=data.get("cpu_cores"),
                memory_gb=data.get("memory_gb"),
                server_type=data.get("server_type", ""),
                tier=data.get("tier", "unknown"),
                status="OFFLINE",
                connection_config=cfg,
            )
            db.add(new_srv)
            created += 1

    if not body.dry_run:
        try:
            db.commit()
        except Exception as exc:
            db.rollback()
            raise HTTPException(status_code=500, detail=f"Veritabanı hatası: {exc}")

    return {
        "dry_run": body.dry_run,
        "total_rows": len(rows),
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "errors": errors[:20],
        "preview": preview_list if body.dry_run else preview_list[:5],
    }


@router.get("/field-options")
def list_field_options():
    """Return available Server fields for mapping UI."""
    return {
        "fields": [
            {"value": "__skip__",    "label": "— Atla —"},
            {"value": "name",        "label": "Sunucu Adı"},
            {"value": "hostname",    "label": "Hostname"},
            {"value": "ip_address",  "label": "IP Adresi"},
            {"value": "os_type",     "label": "OS Tipi"},
            {"value": "os_version",  "label": "OS Versiyonu"},
            {"value": "cpu_cores",   "label": "CPU Çekirdek"},
            {"value": "memory_gb",   "label": "RAM (GB)"},
            {"value": "memory_mb_raw","label": "RAM (MB → GB çevrilir)"},
            {"value": "server_type", "label": "CI Tipi / Sunucu Tipi"},
            {"value": "tier",        "label": "Ortam / Tier"},
            {"value": "notes",       "label": "Notlar (meta olarak saklanır)"},
        ]
    }
