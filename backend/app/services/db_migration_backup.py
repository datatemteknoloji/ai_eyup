"""
Tam veritabanı yedek / geri yükleme (ainew + opsiyonel Dropt).

pg_dump / psql, ilgili DB container içinde Docker exec ile çalışır.
Disk artefaktları (chroma, rpm mirror, uploads) dahil değildir.
"""
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import tarfile
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

from app.services import docker_engine as docker

logger = logging.getLogger(__name__)

FORMAT_NAME = "ainew-db-backup"
FORMAT_VERSION = "1.0"
RESTORE_CONFIRM = "VERITABANI GERI YUKLE"

AINEW_DB_CONTAINER = "server_management_db"
DROPT_DB_CONTAINER = "dropt_db"


def _secret_key_fingerprint() -> str:
    key = (os.getenv("SECRET_KEY") or "").encode("utf-8")
    if not key:
        return "none"
    return f"sha256:{hashlib.sha256(key).hexdigest()[:16]}"


def _app_version() -> str:
    try:
        from app.core.version import get_app_version
        return get_app_version()
    except Exception:
        return os.getenv("APP_VERSION") or "unknown"


def _parse_database_url(url: str) -> Dict[str, str]:
    """postgresql://user:pass@host:port/db → components."""
    raw = (url or "").strip()
    if raw.startswith("postgresql+psycopg"):
        raw = "postgresql" + raw[len("postgresql+psycopg"):]
    if raw.startswith("postgresql+psycopg2"):
        raw = "postgresql" + raw[len("postgresql+psycopg2"):]
    u = urlparse(raw)
    db = (u.path or "/").lstrip("/").split("?")[0] or "postgres"
    return {
        "user": u.username or "postgres",
        "password": u.password or "",
        "host": u.hostname or "localhost",
        "port": str(u.port or 5432),
        "database": db,
    }


def ainew_db_creds() -> Dict[str, str]:
    url = os.getenv("DATABASE_URL") or "postgresql://postgres:postgres@localhost:5432/server_management"
    return _parse_database_url(url)


def dropt_db_creds() -> Dict[str, str]:
    user = os.getenv("DROPT_POSTGRES_USER") or "dtt"
    password = os.getenv("DROPT_POSTGRES_PASSWORD") or ""
    db = os.getenv("DROPT_POSTGRES_DB") or "dttportal"
    # Host network backend → published 5433; container-internal dump uses local socket/user
    return {
        "user": user,
        "password": password,
        "host": "localhost",
        "port": "5433",
        "database": db,
    }


def capability() -> Dict[str, Any]:
    readable = docker.docker_sock_readable()
    writable = docker.docker_sock_writable()
    reasons: List[str] = []
    if not readable:
        reasons.append(f"Docker soketi okunamıyor: {docker.docker_sock()}")
    if not writable:
        reasons.append("Docker soketi yazılamıyor — dump/restore için RW mount gerekli")

    ainew_ok = False
    dropt_ok = False
    try:
        if readable:
            ainew_ok = docker.find_container_by_name(AINEW_DB_CONTAINER) is not None
            dropt_ok = docker.find_container_by_name(DROPT_DB_CONTAINER) is not None
    except Exception as e:
        reasons.append(str(e)[:200])

    if readable and not ainew_ok:
        reasons.append(f"{AINEW_DB_CONTAINER} bulunamadı")

    return {
        "available": readable and writable and ainew_ok,
        "docker_sock_ok": readable and writable,
        "ainew_db_present": ainew_ok,
        "dropt_db_present": dropt_ok,
        "restore_confirm_phrase": RESTORE_CONFIRM,
        "format": FORMAT_NAME,
        "format_version": FORMAT_VERSION,
        "secret_key_fingerprint": _secret_key_fingerprint(),
        "app_version": _app_version(),
        "reasons": reasons,
        "includes": {
            "ainew_postgres": True,
            "dropt_postgres": True,
            "disk_artifacts": False,
            "note": (
                "PostgreSQL şeması + veri (sunucular, vCenter, OCP, audit, ayarlar, …). "
                "Chroma, RPM mirror dosyaları, uploads ve Redis AOF dahil değildir."
            ),
        },
    }


def _dump_via_exec(container_name: str, user: str, database: str, password: str) -> bytes:
    found = docker.find_container_by_name(container_name)
    if not found or not found.get("Id"):
        raise RuntimeError(f"DB container yok: {container_name}")
    cid = found["Id"]

    # Shell ile PGPASSWORD — şifrede tek tırnak kaçışı
    pw = (password or "").replace("'", "'\"'\"'")
    # --clean --if-exists restore'ta nesneleri düşürür; dump tarafında da üretilebilir
    script = (
        f"export PGPASSWORD='{pw}'; "
        f"pg_dump -U '{user}' -d '{database}' "
        f"--no-owner --no-acl --clean --if-exists --encoding=UTF8"
    )
    code, out = docker.exec_in_container(cid, ["bash", "-lc", script], timeout=900.0)
    if code != 0:
        err = out.decode("utf-8", errors="replace")[:800]
        raise RuntimeError(f"pg_dump başarısız ({container_name}): exit={code} {err}")
    if not out or len(out) < 40:
        raise RuntimeError(f"pg_dump boş çıktı ({container_name})")
    return out


def create_backup_zip(include_dropt: bool = True) -> Tuple[Path, Dict[str, Any]]:
    """Zip dosyası oluştur; (path, manifest) döner. Caller silmeli."""
    cap = capability()
    if not cap["available"]:
        raise RuntimeError("; ".join(cap["reasons"]) or "Yedek alınamıyor")

    ainew = ainew_db_creds()
    dropt = dropt_db_creds()

    tmpdir = Path(tempfile.mkdtemp(prefix="ainew-db-backup-"))
    try:
        ainew_sql = _dump_via_exec(
            AINEW_DB_CONTAINER, ainew["user"], ainew["database"], ainew["password"]
        )
        (tmpdir / "ainew.sql").write_bytes(ainew_sql)

        dropt_included = False
        dropt_size = 0
        if include_dropt and cap.get("dropt_db_present"):
            if not dropt["password"]:
                logger.warning("DROPT_POSTGRES_PASSWORD yok — Dropt dump atlandı")
            else:
                dropt_sql = _dump_via_exec(
                    DROPT_DB_CONTAINER, dropt["user"], dropt["database"], dropt["password"]
                )
                (tmpdir / "dropt.sql").write_bytes(dropt_sql)
                dropt_included = True
                dropt_size = len(dropt_sql)

        manifest = {
            "format": FORMAT_NAME,
            "format_version": FORMAT_VERSION,
            "app_version": _app_version(),
            "exported_at": datetime.now(timezone.utc).isoformat(),
            "secret_key_fingerprint": _secret_key_fingerprint(),
            "databases": {
                "ainew": {
                    "file": "ainew.sql",
                    "container": AINEW_DB_CONTAINER,
                    "database": ainew["database"],
                    "user": ainew["user"],
                    "size_bytes": len(ainew_sql),
                    "sha256": hashlib.sha256(ainew_sql).hexdigest(),
                },
                "dropt": {
                    "included": dropt_included,
                    "file": "dropt.sql" if dropt_included else None,
                    "container": DROPT_DB_CONTAINER,
                    "database": dropt["database"],
                    "user": dropt["user"],
                    "size_bytes": dropt_size,
                    "sha256": (
                        hashlib.sha256((tmpdir / "dropt.sql").read_bytes()).hexdigest()
                        if dropt_included else None
                    ),
                },
            },
            "warnings": [
                "Geri yükleme hedef veritabanındaki mevcut verinin üzerine yazar (--clean).",
                "Şifreli alanlar için hedef SECRET_KEY, kaynak ile aynı olmalıdır.",
                "Chroma / RPM mirror / uploads disk dosyaları bu yedekte yoktur.",
            ],
        }
        (tmpdir / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )

        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        zip_path = tmpdir / f"ainew-db-backup-{stamp}.zip"
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            zf.write(tmpdir / "manifest.json", "manifest.json")
            zf.write(tmpdir / "ainew.sql", "ainew.sql")
            if dropt_included:
                zf.write(tmpdir / "dropt.sql", "dropt.sql")

        return zip_path, manifest
    except Exception:
        # partial cleanup
        try:
            import shutil
            shutil.rmtree(tmpdir, ignore_errors=True)
        except Exception:
            pass
        raise


def _tar_single_file(filename: str, content: bytes) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo(name=filename)
        info.size = len(content)
        tf.addfile(info, io.BytesIO(content))
    return buf.getvalue()


def _restore_sql(container_name: str, user: str, database: str, password: str, sql: bytes) -> None:
    from app.services import docker_engine as de

    found = de.find_container_by_name(container_name)
    if not found:
        raise RuntimeError(f"DB container yok: {container_name}")
    cid = found["Id"]

    # SQL'i container /tmp altına koy
    remote_name = "ainew_restore.sql"
    tar_bytes = _tar_single_file(remote_name, sql)
    docker.put_archive(cid, "/tmp", tar_bytes)

    pw = (password or "").replace("'", "'\"'\"'")
    # TimescaleDB: mümkünse pre/post restore
    script = (
        f"export PGPASSWORD='{pw}'; "
        f"psql -U '{user}' -d '{database}' -v ON_ERROR_STOP=1 "
        f"-c \"SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_extension WHERE extname='timescaledb') "
        f"THEN timescaledb_pre_restore() ELSE true END;\" || true; "
        f"psql -U '{user}' -d '{database}' -v ON_ERROR_STOP=1 -f /tmp/{remote_name}; "
        f"rc=$?; "
        f"psql -U '{user}' -d '{database}' -v ON_ERROR_STOP=0 "
        f"-c \"SELECT CASE WHEN EXISTS (SELECT 1 FROM pg_extension WHERE extname='timescaledb') "
        f"THEN timescaledb_post_restore() ELSE true END;\" || true; "
        f"rm -f /tmp/{remote_name}; "
        f"exit $rc"
    )
    code, out = docker.exec_in_container(cid, ["bash", "-lc", script], timeout=1800.0)
    if code != 0:
        err = out.decode("utf-8", errors="replace")[-1200:]
        raise RuntimeError(f"Restore başarısız ({container_name}): exit={code}\n{err}")


def validate_backup_zip(zip_path: Path) -> Dict[str, Any]:
    with zipfile.ZipFile(zip_path, "r") as zf:
        names = set(zf.namelist())
        if "manifest.json" not in names or "ainew.sql" not in names:
            raise ValueError("Geçersiz yedek: manifest.json ve ainew.sql gerekli")
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if manifest.get("format") != FORMAT_NAME:
            raise ValueError(f"Beklenmeyen format: {manifest.get('format')}")
        ainew_sql = zf.read("ainew.sql")
        expected = ((manifest.get("databases") or {}).get("ainew") or {}).get("sha256")
        if expected:
            got = hashlib.sha256(ainew_sql).hexdigest()
            if got != expected:
                raise ValueError("ainew.sql bütünlük kontrolü başarısız (sha256)")
        dropt_meta = (manifest.get("databases") or {}).get("dropt") or {}
        dropt_sql = None
        if dropt_meta.get("included") and dropt_meta.get("file") in names:
            dropt_sql = zf.read(dropt_meta["file"])
            expected_d = dropt_meta.get("sha256")
            if expected_d:
                if hashlib.sha256(dropt_sql).hexdigest() != expected_d:
                    raise ValueError("dropt.sql bütünlük kontrolü başarısız (sha256)")
        return {
            "manifest": manifest,
            "ainew_sql": ainew_sql,
            "dropt_sql": dropt_sql,
            "current_fingerprint": _secret_key_fingerprint(),
            "fingerprint_match": manifest.get("secret_key_fingerprint") == _secret_key_fingerprint(),
        }


def restore_backup_zip(
    zip_path: Path,
    *,
    confirm: str,
    restore_ainew: bool = True,
    restore_dropt: bool = True,
    require_fingerprint_match: bool = True,
) -> Dict[str, Any]:
    if (confirm or "").strip() != RESTORE_CONFIRM:
        raise ValueError(f"Onay metni hatalı — tam olarak yazın: {RESTORE_CONFIRM}")

    cap = capability()
    if not cap["available"]:
        raise RuntimeError("; ".join(cap["reasons"]) or "Restore yapılamıyor")

    parsed = validate_backup_zip(zip_path)
    manifest = parsed["manifest"]
    if require_fingerprint_match and not parsed["fingerprint_match"]:
        raise ValueError(
            "SECRET_KEY parmak izi eşleşmiyor. Şifreli alanlar bozulur. "
            "Aynı SECRET_KEY ile devam edin veya require_fingerprint_match=false "
            "(bilinçli risk) kullanın."
        )

    results: Dict[str, Any] = {
        "ainew": None,
        "dropt": None,
        "warnings": list(manifest.get("warnings") or []),
        "fingerprint_match": parsed["fingerprint_match"],
        "source_version": manifest.get("app_version"),
        "source_exported_at": manifest.get("exported_at"),
    }

    if restore_ainew and parsed["ainew_sql"]:
        ainew = ainew_db_creds()
        _restore_sql(
            AINEW_DB_CONTAINER,
            ainew["user"],
            ainew["database"],
            ainew["password"],
            parsed["ainew_sql"],
        )
        results["ainew"] = {"ok": True, "size_bytes": len(parsed["ainew_sql"])}

    if restore_dropt and parsed["dropt_sql"]:
        if not cap.get("dropt_db_present"):
            results["warnings"].append("Dropt DB container yok — Dropt restore atlandı")
            results["dropt"] = {"ok": False, "skipped": True}
        else:
            dropt = dropt_db_creds()
            if not dropt["password"]:
                raise RuntimeError("DROPT_POSTGRES_PASSWORD tanımlı değil")
            _restore_sql(
                DROPT_DB_CONTAINER,
                dropt["user"],
                dropt["database"],
                dropt["password"],
                parsed["dropt_sql"],
            )
            results["dropt"] = {"ok": True, "size_bytes": len(parsed["dropt_sql"])}
    elif restore_dropt and not parsed["dropt_sql"]:
        results["dropt"] = {"ok": False, "skipped": True, "reason": "Yedekte Dropt yok"}

    return results
