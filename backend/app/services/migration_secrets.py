"""
Tam DB taşıma için secret özeti + export.

Ainew container env + (mümkünse) Dropt container env'den okur.
UI'da plaintext göstermeyin — sadece fingerprint + indirme.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, unquote

from app.services.secret_policy import secret_key_fingerprint

logger = logging.getLogger(__name__)

EXPORT_CONFIRM = "TASIMA SIRLARINI INDIR"
DROPT_API_CONTAINER = "dropt_api"


def _fp(value: Optional[str]) -> str:
    if not (value or "").strip():
        return "none"
    return secret_key_fingerprint(value.strip())


def _postgres_password_from_database_url() -> str:
    url = (os.getenv("DATABASE_URL") or "").strip()
    if not url:
        return (os.getenv("POSTGRES_PASSWORD") or "").strip()
    try:
        raw = url
        if raw.startswith("postgresql+psycopg2"):
            raw = "postgresql" + raw[len("postgresql+psycopg2") :]
        elif raw.startswith("postgresql+psycopg"):
            raw = "postgresql" + raw[len("postgresql+psycopg") :]
        u = urlparse(raw)
        return unquote(u.password or "") if u.password else ""
    except Exception:
        return (os.getenv("POSTGRES_PASSWORD") or "").strip()


def _parse_env_file(path: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                if not k:
                    continue
                out[k] = v.strip().strip("'").strip('"')
    except OSError:
        pass
    return out


def _read_install_env_files() -> Tuple[Dict[str, str], Dict[str, str], List[str]]:
    """AINEW_INSTALL_DIR altında .env / dropt/.env (container'da mount varsa)."""
    notes: List[str] = []
    install = (os.getenv("AINEW_INSTALL_DIR") or "").strip().rstrip("/")
    main: Dict[str, str] = {}
    dropt: Dict[str, str] = {}
    if not install:
        notes.append("AINEW_INSTALL_DIR tanımlı değil — dosyadan okuma yok")
        return main, dropt, notes
    main_path = f"{install}/.env"
    dropt_path = f"{install}/dropt/.env"
    if os.path.isfile(main_path):
        main = _parse_env_file(main_path)
        notes.append(f"Okundu: {main_path}")
    else:
        notes.append(f"Dosya yok (container içi): {main_path}")
    if os.path.isfile(dropt_path):
        dropt = _parse_env_file(dropt_path)
        notes.append(f"Okundu: {dropt_path}")
    else:
        notes.append(f"Dosya yok (container içi): {dropt_path}")
    return main, dropt, notes


def _dropt_env_via_docker() -> Tuple[Dict[str, str], Optional[str]]:
    """dropt_api container printenv → FERNET_KEY / JWT / bridge."""
    try:
        from app.services import docker_engine as docker

        c = docker.find_container_by_name(DROPT_API_CONTAINER)
        if not c:
            return {}, f"{DROPT_API_CONTAINER} container bulunamadı"
        cid = c.get("Id") or ""
        code, out = docker.exec_in_container(
            cid,
            [
                "sh",
                "-c",
                "printf 'FERNET_KEY=%s\\n' \"$FERNET_KEY\"; "
                "printf 'JWT_SECRET=%s\\n' \"$JWT_SECRET\"; "
                "printf 'AINEW_BRIDGE_SECRET=%s\\n' \"$AINEW_BRIDGE_SECRET\"; "
                "printf 'POSTGRES_PASSWORD=%s\\n' \"$POSTGRES_PASSWORD\"",
            ],
            timeout=20.0,
        )
        text = (out or b"").decode("utf-8", errors="replace")
        if code != 0 and not text.strip():
            return {}, f"dropt env exit={code}"
        keys = {"FERNET_KEY", "JWT_SECRET", "AINEW_BRIDGE_SECRET", "POSTGRES_PASSWORD"}
        result: Dict[str, str] = {}
        for ln in text.splitlines():
            if "=" not in ln:
                continue
            k, _, v = ln.partition("=")
            if k in keys and v.strip():
                result[k] = v
        return result, None
    except Exception as e:
        logger.info("Dropt env docker okunamadı: %s", e)
        return {}, str(e)[:200]


def collect_migration_secrets() -> Dict[str, Any]:
    """Kaynak değerleri birleştir (env → dosya → dropt docker)."""
    file_main, file_dropt, file_notes = _read_install_env_files()
    dropt_docker, dropt_err = _dropt_env_via_docker()

    secret_key = (os.getenv("SECRET_KEY") or file_main.get("SECRET_KEY") or "").strip()
    bridge = (
        os.getenv("AINEW_BRIDGE_SECRET")
        or file_main.get("AINEW_BRIDGE_SECRET")
        or dropt_docker.get("AINEW_BRIDGE_SECRET")
        or file_dropt.get("AINEW_BRIDGE_SECRET")
        or ""
    ).strip()
    postgres = _postgres_password_from_database_url() or (file_main.get("POSTGRES_PASSWORD") or "").strip()
    dropt_pg = (
        os.getenv("DROPT_POSTGRES_PASSWORD")
        or file_main.get("DROPT_POSTGRES_PASSWORD")
        or dropt_docker.get("POSTGRES_PASSWORD")
        or ""
    ).strip()
    fernet = (dropt_docker.get("FERNET_KEY") or file_dropt.get("FERNET_KEY") or "").strip()
    jwt = (dropt_docker.get("JWT_SECRET") or file_dropt.get("JWT_SECRET") or "").strip()

    bridge_dropt = (dropt_docker.get("AINEW_BRIDGE_SECRET") or file_dropt.get("AINEW_BRIDGE_SECRET") or bridge).strip()
    bridge_match = bool(bridge and bridge_dropt and bridge == bridge_dropt)

    values = {
        "SECRET_KEY": secret_key,
        "AINEW_BRIDGE_SECRET": bridge,
        "POSTGRES_PASSWORD": postgres,
        "DROPT_POSTGRES_PASSWORD": dropt_pg,
        "FERNET_KEY": fernet,
        "JWT_SECRET": jwt,
        "DROPT_AINEW_BRIDGE_SECRET": bridge_dropt,
    }

    install_hint = (os.getenv("AINEW_INSTALL_DIR") or "/data").strip().rstrip("/") or "/data"

    keys_meta = [
        {
            "key": "SECRET_KEY",
            "target_file": f"{install_hint}/.env",
            "required": True,
            "present": bool(secret_key),
            "fingerprint": _fp(secret_key),
            "note": "ainew şifreli alanlar + DB zip fingerprint",
        },
        {
            "key": "AINEW_BRIDGE_SECRET",
            "target_file": f"{install_hint}/.env",
            "required": True,
            "present": bool(bridge),
            "fingerprint": _fp(bridge),
            "note": "ainew ↔ Dropt köprü (ana .env)",
        },
        {
            "key": "POSTGRES_PASSWORD",
            "target_file": f"{install_hint}/.env",
            "required": False,
            "present": bool(postgres),
            "fingerprint": _fp(postgres),
            "note": "ainew TimescaleDB — compose için önerilir",
        },
        {
            "key": "DROPT_POSTGRES_PASSWORD",
            "target_file": f"{install_hint}/.env",
            "required": False,
            "present": bool(dropt_pg),
            "fingerprint": _fp(dropt_pg),
            "note": "Dropt Postgres (ana .env)",
        },
        {
            "key": "FERNET_KEY",
            "target_file": f"{install_hint}/dropt/.env",
            "required": True,
            "present": bool(fernet),
            "fingerprint": _fp(fernet),
            "note": "Dropt şifreli sırlar",
        },
        {
            "key": "AINEW_BRIDGE_SECRET",
            "target_file": f"{install_hint}/dropt/.env",
            "required": True,
            "present": bool(bridge_dropt),
            "fingerprint": _fp(bridge_dropt),
            "note": "Dropt köprü — ana .env ile aynı olmalı",
            "bridge_match": bridge_match,
        },
        {
            "key": "JWT_SECRET",
            "target_file": f"{install_hint}/dropt/.env",
            "required": False,
            "present": bool(jwt),
            "fingerprint": _fp(jwt),
            "note": "Dropt oturumları",
        },
        {
            "key": "POSTGRES_PASSWORD",
            "target_file": f"{install_hint}/dropt/.env",
            "required": False,
            "present": bool(dropt_pg),
            "fingerprint": _fp(dropt_pg),
            "note": "Dropt DB — DROPT_POSTGRES_PASSWORD ile aynı",
        },
    ]

    missing_required = [
        f"{m['key']} → {m['target_file']}"
        for m in keys_meta
        if m.get("required") and not m.get("present")
    ]

    return {
        "install_dir_hint": install_hint,
        "export_confirm_phrase": EXPORT_CONFIRM,
        "secret_key_fingerprint": _fp(secret_key),
        "bridge_fingerprint": _fp(bridge),
        "fernet_fingerprint": _fp(fernet),
        "bridge_match": bridge_match,
        "keys": keys_meta,
        "missing_required": missing_required,
        "ready_for_full_migrate": len(missing_required) == 0 and (not bridge or bridge_match),
        "notes": file_notes + ([f"Dropt docker: {dropt_err}"] if dropt_err else ["Dropt docker: ok"]),
        "do_not_copy": [
            "AINEW_INSTALL_DIR",
            "DATA_DIR",
            "CORS_ORIGINS",
            "BACKEND_IMAGE",
            "FRONTEND_IMAGE",
            "yönetim IP / sertifika yolları",
        ],
        "_values": values,  # yalnızca export için; API status'tan düşülecek
    }


def build_export_env_text(*, include_db_passwords: bool = True) -> Tuple[str, Dict[str, Any]]:
    """Hedefe yapıştırılacak .env metni + meta (değerler loglanmaz)."""
    packed = collect_migration_secrets()
    vals: Dict[str, str] = packed.pop("_values", {})
    install = packed.get("install_dir_hint") or "/data"
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    lines: List[str] = [
        f"# ainew migration secrets — {ts}",
        f"# Kaynak install hint: {install}",
        f"# Fingerprint SECRET_KEY: {packed.get('secret_key_fingerprint')}",
        f"# Fingerprint AINEW_BRIDGE_SECRET: {packed.get('bridge_fingerprint')}",
        f"# Fingerprint FERNET_KEY: {packed.get('fernet_fingerprint')}",
        "#",
        "# Hedefte:",
        f"#   1) BLOK A →  <INSTALL>/.env     (örn. /data/app/.env)",
        f"#   2) BLOK B →  <INSTALL>/dropt/.env",
        "#   3) docker compose up -d --force-recreate backend worker",
        "#      (+ dropt stack recreate)",
        "#   AINEW_INSTALL_DIR / DATA_DIR / CORS kopyalamayın.",
        "#",
        "# === BLOK A: ana .env ===",
        f"SECRET_KEY={vals.get('SECRET_KEY') or ''}",
        f"AINEW_BRIDGE_SECRET={vals.get('AINEW_BRIDGE_SECRET') or ''}",
    ]
    if include_db_passwords:
        lines.append(f"POSTGRES_PASSWORD={vals.get('POSTGRES_PASSWORD') or ''}")
        lines.append(f"DROPT_POSTGRES_PASSWORD={vals.get('DROPT_POSTGRES_PASSWORD') or ''}")
    lines += [
        "#",
        "# === BLOK B: dropt/.env ===",
        f"FERNET_KEY={vals.get('FERNET_KEY') or ''}",
        f"AINEW_BRIDGE_SECRET={vals.get('AINEW_BRIDGE_SECRET') or vals.get('DROPT_AINEW_BRIDGE_SECRET') or ''}",
        f"JWT_SECRET={vals.get('JWT_SECRET') or ''}",
    ]
    if include_db_passwords:
        lines.append(f"POSTGRES_PASSWORD={vals.get('DROPT_POSTGRES_PASSWORD') or ''}")
    lines.append("")
    meta = {k: v for k, v in packed.items() if k != "_values"}
    return "\n".join(lines), meta


def public_status() -> Dict[str, Any]:
    """API için — plaintext yok."""
    packed = collect_migration_secrets()
    packed.pop("_values", None)
    return packed


def parse_migration_env_blocks(text: str) -> Tuple[Dict[str, str], Dict[str, str]]:
    """BLOK A / BLOK B ayır; yoksa tüm KEY= satırları A'ya gider, B için bilinen dropt anahtarları kopyalanır."""
    main: Dict[str, str] = {}
    dropt: Dict[str, str] = {}
    section = "A"
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            upper = line.upper()
            if "BLOK B" in upper or "DROPT/.ENV" in upper:
                section = "B"
            elif "BLOK A" in upper or "ANA .ENV" in upper:
                section = "A"
            continue
        if "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if not k or k.startswith("#"):
            continue
        if section == "B":
            dropt[k] = v
        else:
            main[k] = v
    # Eski format: tek blok — Dropt anahtarlarını B'ye de taşı
    if not dropt and main:
        for k in ("FERNET_KEY", "JWT_SECRET"):
            if k in main:
                dropt[k] = main[k]
        if "AINEW_BRIDGE_SECRET" in main:
            dropt["AINEW_BRIDGE_SECRET"] = main["AINEW_BRIDGE_SECRET"]
        if "DROPT_POSTGRES_PASSWORD" in main:
            dropt["POSTGRES_PASSWORD"] = main["DROPT_POSTGRES_PASSWORD"]
        elif "POSTGRES_PASSWORD" in main and "FERNET_KEY" in main:
            # belirsiz — B için ayrı POSTGRES yoksa dokunma
            pass
    return main, dropt


def merge_env_file(path: Path, updates: Dict[str, str]) -> Dict[str, Any]:
    """Mevcut .env satırlarını koruyarak verilen anahtarları güncelle/ekle."""
    path = Path(path)
    updates = {k: v for k, v in (updates or {}).items() if k and v is not None and str(v) != ""}
    if not updates:
        return {"path": str(path), "updated": [], "skipped": True}

    path.parent.mkdir(parents=True, exist_ok=True)
    existing_lines: List[str] = []
    if path.is_file():
        existing_lines = path.read_text(encoding="utf-8", errors="replace").splitlines()

    seen: set = set()
    out_lines: List[str] = []
    changed: List[str] = []
    for line in existing_lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in updates:
                out_lines.append(f"{k}={updates[k]}")
                seen.add(k)
                changed.append(k)
                continue
        out_lines.append(line)

    for k, v in updates.items():
        if k not in seen:
            out_lines.append(f"{k}={v}")
            changed.append(k)

    # yedek
    if path.is_file():
        bak = path.with_suffix(path.suffix + f".bak-migrate-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}")
        try:
            bak.write_bytes(path.read_bytes())
        except OSError:
            pass

    path.write_text("\n".join(out_lines) + "\n", encoding="utf-8")
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return {"path": str(path), "updated": changed, "backup": True}


def resolve_install_dir_for_write() -> Optional[str]:
    """Yazılabilir kurulum kökü (.env bulunan). Önce /ainew-install mount."""
    candidates: List[str] = []
    mount = (os.getenv("AINEW_INSTALL_MOUNT") or "/ainew-install").strip().rstrip("/")
    if mount:
        candidates.append(mount)
    env_install = (os.getenv("AINEW_INSTALL_DIR") or "").strip().rstrip("/")
    if env_install:
        candidates.append(env_install)
    try:
        from app.services import docker_engine as docker

        c = docker.find_container_by_name("server_management_backend")
        if c and c.get("Id"):
            insp = docker.inspect_container(c["Id"])
            labels = (insp.get("Config") or {}).get("Labels") or {}
            wd = (labels.get("com.docker.compose.project.working_dir") or "").strip().rstrip("/")
            if wd:
                candidates.append(wd)
    except Exception:
        pass
    for p in ("/data/app", "/data", "/opt/ainew"):
        if p not in candidates:
            candidates.append(p)

    seen = set()
    for d in candidates:
        if not d or d in seen:
            continue
        seen.add(d)
        env_path = Path(d) / ".env"
        try:
            if env_path.is_file() and os.access(str(env_path), os.W_OK):
                return d
            parent = env_path.parent
            if parent.is_dir() and os.access(str(parent), os.W_OK):
                return d
        except OSError:
            continue
    return None


def apply_migration_secrets_text(
    text: str,
    *,
    install_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    migration-secrets.env içeriğini hedef .env dosyalarına yazar.
    Dönüş: yazılan yollar / hatalar (değerler yok).
    """
    install = (install_dir or resolve_install_dir_for_write() or "").strip().rstrip("/")
    data_dir = (os.getenv("AINEW_DATA_DIR") or os.getenv("DATA_DIR") or "").strip().rstrip("/")

    main_keys, dropt_keys = parse_migration_env_blocks(text)
    result: Dict[str, Any] = {
        "applied": False,
        "install_dir": install or None,
        "main": None,
        "dropt": None,
        "artifact": None,
        "errors": [],
        "recreate_required": True,
        "secret_key_fingerprint": _fp(main_keys.get("SECRET_KEY")),
    }

    # Her zaman DATA_DIR altına artefakt bırak (container recreate sonrası operatör için)
    if data_dir:
        try:
            art_dir = Path(data_dir) / "backups"
            art_dir.mkdir(parents=True, exist_ok=True)
            art = art_dir / "last-restore-migration-secrets.env"
            art.write_text(text if text.endswith("\n") else text + "\n", encoding="utf-8")
            os.chmod(art, 0o600)
            result["artifact"] = str(art)
        except OSError as e:
            result["errors"].append(f"artifact yazılamadı: {e}")

    if not install:
        result["errors"].append(
            "Kurulum dizini bulunamadı / yazılamıyor — .env otomatik güncellenemedi. "
            "Artefakt dosyasındaki BLOK A/B satırlarını elle uygulayın."
        )
        return result

    main_path = Path(install) / ".env"
    dropt_path = Path(install) / "dropt" / ".env"

    try:
        if main_keys:
            result["main"] = merge_env_file(main_path, main_keys)
            result["applied"] = True
    except OSError as e:
        result["errors"].append(f"ana .env yazılamadı ({main_path}): {e}")

    try:
        if dropt_keys:
            result["dropt"] = merge_env_file(dropt_path, dropt_keys)
            result["applied"] = True
    except OSError as e:
        result["errors"].append(f"dropt/.env yazılamadı ({dropt_path}): {e}")

    if result["applied"] and not result["errors"]:
        result["message"] = (
            f"Secret'lar diske yazıldı ({install}). "
            "Çalışan container env'si değişmez — "
            "docker compose up -d --force-recreate backend worker (+ dropt) çalıştırın."
        )
    elif result["artifact"] and not result["applied"]:
        result["message"] = (
            f"Otomatik .env yazımı olmadı. Secret dosyası: {result['artifact']}"
        )
    return result


def fingerprint_from_migration_env_text(text: str) -> str:
    main, _ = parse_migration_env_blocks(text)
    return _fp(main.get("SECRET_KEY"))
