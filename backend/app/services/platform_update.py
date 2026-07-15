"""
Platform self-update: paket tarama/upload/prepare + docker.sock ile ayrık updater.
"""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import socket
import tarfile
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

SAFE_NAME_RE = re.compile(r"^[A-Za-z0-9._+-]+$")


class UnixHTTPConnection(HTTPConnection):
    def __init__(self, unix_path: str, timeout: float = 60.0):
        super().__init__("localhost", timeout=timeout)
        self.unix_path = unix_path

    def connect(self) -> None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        sock.settimeout(self.timeout)
        sock.connect(self.unix_path)
        self.sock = sock


class UnixHTTPHandler(urllib.request.HTTPHandler):
    def __init__(self, unix_path: str):
        super().__init__()
        self.unix_path = unix_path

    def http_open(self, req):
        return self.do_open(lambda *a, **k: UnixHTTPConnection(self.unix_path, timeout=120.0), req)


def _env_bool(name: str, default: bool = False) -> bool:
    raw = (os.getenv(name) or "").strip().lower()
    if not raw:
        return default
    return raw in ("1", "true", "yes", "on")


def install_dir() -> Path:
    return Path(os.getenv("AINEW_INSTALL_DIR", "/data")).resolve()


def data_dir() -> Path:
    return Path(os.getenv("AINEW_DATA_DIR", "/data/data")).resolve()


def updates_dir() -> Path:
    override = (os.getenv("AINEW_UPDATES_DIR") or "").strip()
    if override:
        p = Path(override)
    else:
        p = Path("/app/updates")
    p.mkdir(parents=True, exist_ok=True)
    (p / "incoming").mkdir(exist_ok=True)
    (p / "prepared").mkdir(exist_ok=True)
    (p / "bin").mkdir(exist_ok=True)
    return p


def status_path() -> Path:
    return updates_dir() / "status.json"


def log_path() -> Path:
    return updates_dir() / "apply.log"


def docker_sock() -> str:
    return os.getenv("DOCKER_SOCK", "/var/run/docker.sock")


def platform_update_enabled() -> bool:
    return _env_bool("PLATFORM_UPDATE_ENABLED", False)


def max_upload_bytes() -> int:
    # varsayılan 8 GiB
    return int(os.getenv("PLATFORM_UPDATE_MAX_UPLOAD_BYTES", str(8 * 1024 ** 3)))


def updater_image() -> str:
    return os.getenv("PLATFORM_UPDATER_IMAGE", "alpine:3.20")


def parse_version(v: str) -> Tuple[int, ...]:
    v = (v or "").strip().lstrip("vV")
    parts: List[int] = []
    for p in re.split(r"[.-]", v):
        if p.isdigit():
            parts.append(int(p))
        else:
            m = re.match(r"^(\d+)", p)
            parts.append(int(m.group(1)) if m else 0)
    return tuple(parts) if parts else (0,)


def version_gt(a: str, b: str) -> bool:
    return parse_version(a) > parse_version(b)


def version_gte(a: str, b: str) -> bool:
    return parse_version(a) >= parse_version(b)


def current_version() -> str:
    from app.core.version import get_app_version
    return get_app_version()


def write_status(payload: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(payload)
    payload["updated_at"] = datetime.now(timezone.utc).isoformat()
    path = status_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    return payload


def read_status() -> Dict[str, Any]:
    path = status_path()
    if not path.is_file():
        return {"state": "idle", "message": ""}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"state": "idle", "message": ""}
        # log_tail ekle
        lp = log_path()
        if lp.is_file():
            try:
                text = lp.read_text(encoding="utf-8", errors="replace")
                data["log_tail"] = "\n".join(text.splitlines()[-40:])
            except OSError:
                pass
        return data
    except Exception as e:
        logger.warning("status.json okunamadı: %s", e)
        return {"state": "unknown", "message": str(e)}


def ensure_wrapper_script() -> Path:
    """Wrapper'ı updates/bin altına koy (deploy kopyası veya gömülü)."""
    dest = updates_dir() / "bin" / "ainew-apply-update.sh"
    candidates = [
        Path("/app/scripts/ainew-apply-update.sh"),
        Path("/app/deploy/ainew-apply-update.sh"),
        Path(__file__).resolve().parents[2] / "scripts" / "ainew-apply-update.sh",
        Path(__file__).resolve().parents[3] / "deploy" / "ainew-apply-update.sh",
        install_dir() / "ainew-apply-update.sh",
    ]
    src = next((c for c in candidates if c.is_file()), None)
    if src:
        try:
            if (not dest.is_file()) or (src.stat().st_mtime > dest.stat().st_mtime):
                shutil.copy2(src, dest)
        except OSError as e:
            logger.warning("wrapper kopyalanamadı: %s", e)
    if not dest.is_file():
        # Minimal gömülü fallback (apply/rollback)
        dest.write_text(
            "#!/usr/bin/env bash\n"
            "set -euo pipefail\n"
            'INSTALL_DIR="${AINEW_INSTALL_DIR:-/data}"\n'
            'DATA_DIR="${AINEW_DATA_DIR:-/data/data}"\n'
            'ACTION="$1"; shift\n'
            'case "$ACTION" in\n'
            "  apply) cd \"$1\"; exec ./update-rhel.sh --install-dir \"$INSTALL_DIR\" ;;\n"
            "  rollback) cd \"$INSTALL_DIR\"; exec ./rollback-rhel.sh ;;\n"
            "  *) echo bad action; exit 2 ;;\n"
            "esac\n",
            encoding="utf-8",
        )
    try:
        dest.chmod(0o755)
    except OSError:
        pass
    return dest


def docker_sock_available() -> bool:
    sock = docker_sock()
    return os.path.exists(sock) and os.access(sock, os.R_OK | os.W_OK)


def is_packaged_install() -> bool:
    d = install_dir()
    return (d / "docker-compose.prod.yml").is_file() and (d / ".env").is_file()


def capability() -> Dict[str, Any]:
    enabled_flag = platform_update_enabled()
    sock_ok = docker_sock_available()
    packaged = is_packaged_install()
    reasons: List[str] = []
    if not enabled_flag:
        reasons.append("PLATFORM_UPDATE_ENABLED kapalı (yalnızca dağıtım/prod kurulumunda açılır)")
    if not sock_ok:
        reasons.append(f"Docker soketi yok veya yazılamıyor: {docker_sock()}")
    if not packaged:
        reasons.append(
            f"Paket kurulumu algılanamadı ({install_dir()}/docker-compose.prod.yml + .env gerekli)"
        )
    ok = enabled_flag and sock_ok and packaged
    return {
        "enabled": ok,
        "feature_flag": enabled_flag,
        "docker_sock_ok": sock_ok,
        "packaged_install": packaged,
        "install_dir": str(install_dir()),
        "data_dir": str(data_dir()),
        "updates_dir": str(updates_dir()),
        "current_version": current_version(),
        "max_upload_bytes": max_upload_bytes(),
        "reasons": reasons,
        "job": read_status(),
        "has_backup": _latest_backup() is not None,
    }


def _latest_backup() -> Optional[Path]:
    base = data_dir() / "backups"
    latest = base / "latest"
    try:
        if latest.exists():
            return latest.resolve()
    except OSError:
        pass
    if not base.is_dir():
        return None
    cands = sorted(base.glob("pre-update-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return cands[0] if cands else None


def _safe_under(root: Path, path: Path) -> Path:
    root_r = root.resolve()
    path_r = path.resolve()
    if root_r != path_r and root_r not in path_r.parents:
        raise ValueError("Geçersiz yol (path traversal)")
    return path_r


def _inspect_package_dir(pkg: Path) -> Optional[Dict[str, Any]]:
    if not pkg.is_dir():
        return None
    ver_f = pkg / "VERSION"
    upd = pkg / "update-rhel.sh"
    if not ver_f.is_file() or not upd.is_file():
        return None
    ver = ver_f.read_text(encoding="utf-8").strip().lstrip("vV")
    has_images = any((pkg / "images").glob("*.tar*")) if (pkg / "images").is_dir() else False
    return {
        "path": str(pkg),
        "name": pkg.name,
        "version": ver,
        "has_update_script": True,
        "has_images": has_images,
        "kind": "directory",
        "newer_than_current": version_gt(ver, current_version()),
    }


def _inspect_tarball(archive: Path) -> Optional[Dict[str, Any]]:
    if not archive.is_file():
        return None
    name = archive.name.lower()
    if not (name.endswith(".tar.gz") or name.endswith(".tgz") or name.endswith(".tar")):
        return None
    ver = None
    has_script = False
    has_images = False
    try:
        mode = "r:gz" if name.endswith((".tar.gz", ".tgz")) else "r:"
        with tarfile.open(archive, mode) as tf:
            for m in tf.getmembers()[:4000]:
                n = m.name.replace("\\", "/")
                base = n.split("/")[-1]
                if base == "VERSION" and m.isfile():
                    f = tf.extractfile(m)
                    if f:
                        ver = f.read(64).decode("utf-8", errors="replace").strip().lstrip("vV")
                if base == "update-rhel.sh":
                    has_script = True
                if "/images/" in f"/{n}" and (
                    n.endswith(".tar.gz") or n.endswith(".tar") or ".tar.gz.part" in n
                ):
                    has_images = True
                if ver and has_script and has_images:
                    break
    except Exception as e:
        logger.warning("tar incelemesi başarısız %s: %s", archive, e)
        return None
    if not ver or not has_script:
        return None
    return {
        "path": str(archive),
        "name": archive.name,
        "version": ver,
        "has_update_script": has_script,
        "has_images": has_images,
        "kind": "archive",
        "size_bytes": archive.stat().st_size,
        "newer_than_current": version_gt(ver, current_version()),
    }


def list_packages() -> List[Dict[str, Any]]:
    root = updates_dir()
    found: List[Dict[str, Any]] = []
    seen_versions = set()

    prepared = root / "prepared"
    if prepared.is_dir():
        for child in sorted(prepared.iterdir()):
            info = _inspect_package_dir(child)
            if info:
                found.append(info)
                seen_versions.add(info["version"])

    # Doğrudan updates/ altına bırakılmış dizinler
    for child in sorted(root.iterdir()):
        if child.name in ("incoming", "prepared", "bin") or not child.is_dir():
            continue
        info = _inspect_package_dir(child)
        if info and info["version"] not in seen_versions:
            found.append(info)
            seen_versions.add(info["version"])

    incoming = root / "incoming"
    scan_dirs = [incoming, root]
    for d in scan_dirs:
        if not d.is_dir():
            continue
        for f in sorted(d.iterdir()):
            if not f.is_file():
                continue
            info = _inspect_tarball(f)
            if info:
                found.append(info)

    return found


def save_upload(filename: str, file_obj, *, max_bytes: Optional[int] = None) -> Dict[str, Any]:
    max_b = max_bytes if max_bytes is not None else max_upload_bytes()
    base = Path(filename or "package.tar.gz").name
    if not SAFE_NAME_RE.match(base):
        raise ValueError("Geçersiz dosya adı")
    if not (
        base.lower().endswith(".tar.gz")
        or base.lower().endswith(".tgz")
        or base.lower().endswith(".tar")
    ):
        raise ValueError("Yalnızca .tar.gz / .tgz / .tar kabul edilir")

    dest_dir = updates_dir() / "incoming"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = _safe_under(dest_dir, dest_dir / base)

    written = 0
    with open(dest, "wb") as out:
        while True:
            chunk = file_obj.read(1024 * 1024)
            if not chunk:
                break
            written += len(chunk)
            if written > max_b:
                out.close()
                try:
                    dest.unlink(missing_ok=True)
                except TypeError:
                    if dest.exists():
                        dest.unlink()
                raise ValueError(f"Dosya limiti aşıldı ({max_b} byte)")
            out.write(chunk)

    info = _inspect_tarball(dest)
    if not info:
        try:
            dest.unlink()
        except OSError:
            pass
        raise ValueError("Geçersiz paket (VERSION / update-rhel.sh yok)")
    info["uploaded"] = True
    return info


def _safe_extract(tf: tarfile.TarFile, dest: Path) -> None:
    dest_r = dest.resolve()
    for member in tf.getmembers():
        target = (dest / member.name).resolve()
        if dest_r != target and dest_r not in target.parents:
            raise ValueError(f"Güvenli olmayan tar üyesi: {member.name}")
    tf.extractall(dest)


def prepare_package(source_path: str, *, allow_downgrade: bool = False) -> Dict[str, Any]:
    src = Path(source_path)
    root = updates_dir()
    # Kaynak updates altında olmalı
    _safe_under(root, src)

    if src.is_dir():
        info = _inspect_package_dir(src)
        if not info:
            raise ValueError("Geçersiz paket dizini")
        prepared_path = src
        ver = info["version"]
    elif src.is_file():
        info = _inspect_tarball(src)
        if not info:
            raise ValueError("Geçersiz paket arşivi")
        ver = info["version"]
        prepared_path = root / "prepared" / ver
        if prepared_path.exists():
            shutil.rmtree(prepared_path)
        prepared_path.mkdir(parents=True)
        mode = "r:gz" if src.name.lower().endswith((".tar.gz", ".tgz")) else "r:"
        with tarfile.open(src, mode) as tf:
            # tek üst dizin varsa içeriği düzleştir
            members = tf.getmembers()
            top_dirs = {m.name.split("/")[0] for m in members if m.name}
            with tempfile.TemporaryDirectory(prefix="ainew-prep-") as tmp:
                tmp_p = Path(tmp)
                _safe_extract(tf, tmp_p)
                if len(top_dirs) == 1:
                    inner = tmp_p / next(iter(top_dirs))
                    if inner.is_dir() and (inner / "update-rhel.sh").is_file():
                        for child in inner.iterdir():
                            shutil.move(str(child), str(prepared_path / child.name))
                    else:
                        for child in tmp_p.iterdir():
                            shutil.move(str(child), str(prepared_path / child.name))
                else:
                    for child in tmp_p.iterdir():
                        shutil.move(str(child), str(prepared_path / child.name))
        info = _inspect_package_dir(prepared_path)
        if not info:
            raise ValueError("Çıkarma sonrası paket geçersiz")
    else:
        raise ValueError("Kaynak bulunamadı")

    cur = current_version()
    if not allow_downgrade and not version_gt(ver, cur):
        raise ValueError(
            f"Hedef sürüm ({ver}) mevcut sürümden ({cur}) yeni olmalı "
            f"(düşürme için allow_downgrade=true)"
        )

    ensure_wrapper_script()
    return {
        "ok": True,
        "current_version": cur,
        "target_version": ver,
        "prepared_path": str(prepared_path),
        "has_images": bool(info.get("has_images")),
        "newer_than_current": version_gt(ver, cur),
    }


def _docker_request(method: str, path: str, body: Optional[dict] = None) -> Tuple[int, Any]:
    sock = docker_sock()
    data = None
    headers = {"Content-Type": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
    opener = urllib.request.build_opener(UnixHTTPHandler(sock))
    req = urllib.request.Request(
        f"http://localhost{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with opener.open(req, timeout=120) as resp:
            raw = resp.read()
            code = getattr(resp, "status", 200)
            if not raw:
                return code, None
            try:
                return code, json.loads(raw.decode("utf-8"))
            except Exception:
                return code, raw.decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        raw = e.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"message": raw}
        return e.code, payload


def _host_updates_dir() -> str:
    """Host'taki updates yolu (nsenter için). Container /app/updates ise DATA_DIR/updates."""
    return str(data_dir() / "updates")


def _start_updater_container(host_cmd: str) -> str:
    """
    Host PID namespace + nsenter ile wrapper çalıştır.
    host_cmd: bash script'e verilecek argümanlar (apply path / rollback).
    """
    if not docker_sock_available():
        raise RuntimeError("Docker soketi kullanılamıyor")

    # Eski updater varsa kaldır
    _docker_request("DELETE", "/containers/ainew-updater?force=true")

    host_updates = _host_updates_dir()
    host_wrapper = f"{host_updates}/bin/ainew-apply-update.sh"
    host_data = str(data_dir())
    host_install = str(install_dir())
    image = updater_image()

    # Image pull offline ortamda başarısız olabilir; varsa local kullan.
    # create fails with 404 if missing — caller should have image preloaded on prod hosts.
    cfg = {
        "Image": image,
        "Cmd": [
            "sh",
            "-c",
            (
                "apk add --no-cache util-linux bash >/dev/null 2>&1 || true; "
                f"exec nsenter --target 1 --mount --uts --ipc --net -- "
                f"/bin/bash {host_wrapper} {host_cmd}"
            ),
        ],
        "HostConfig": {
            "Privileged": True,
            "PidMode": "host",
            "AutoRemove": True,
            "NetworkMode": "host",
        },
        "Env": [
            f"AINEW_INSTALL_DIR={host_install}",
            f"AINEW_DATA_DIR={host_data}",
        ],
        "Labels": {"ainew.updater": "1"},
    }

    code, created = _docker_request("POST", "/containers/create?name=ainew-updater", cfg)
    if code == 404:
        # image yok — dene docker hub (online) veya hata
        pull_code, _ = _docker_request(
            "POST",
            f"/images/create?fromImage={urllib.parse.quote(image.split(':')[0])}"
            f"&tag={urllib.parse.quote(image.split(':')[1] if ':' in image else 'latest')}",
        )
        if pull_code not in (200, 201):
            raise RuntimeError(
                f"Updater imajı yok ({image}). Air-gap: alpine:3.20 yükleyin "
                f"veya PLATFORM_UPDATER_IMAGE ayarlayın."
            )
        code, created = _docker_request("POST", "/containers/create?name=ainew-updater", cfg)

    if code not in (200, 201) or not isinstance(created, dict) or not created.get("Id"):
        raise RuntimeError(f"Updater container oluşturulamadı: {created}")

    cid = created["Id"]
    scode, sbody = _docker_request("POST", f"/containers/{cid}/start")
    if scode not in (204, 200, 304):
        raise RuntimeError(f"Updater başlatılamadı: {sbody}")
    return cid


def apply_update(prepared_path: str, *, actor_name: str = "admin") -> Dict[str, Any]:
    prep = Path(prepared_path)
    _safe_under(updates_dir(), prep)
    info = _inspect_package_dir(prep)
    if not info:
        raise ValueError("Hazır paket geçersiz")

    ensure_wrapper_script()
    # Host yolu: prepared container'da /app/updates/prepared/X → host DATA_DIR/updates/prepared/X
    host_prepared = str(data_dir() / "updates" / "prepared" / prep.name)
    # Eğer prepared updates kökünde farklı yerdeyse
    try:
        rel = prep.resolve().relative_to(updates_dir().resolve())
        host_prepared = str(data_dir() / "updates" / rel)
    except Exception:
        pass

    cur = current_version()
    target = info["version"]
    write_status(
        {
            "state": "running",
            "action": "apply",
            "old_version": cur,
            "new_version": target,
            "message": f"Güncelleme başlatıldı ({actor_name})",
            "prepared_path": host_prepared,
        }
    )
    # apply.log temizle
    try:
        log_path().write_text("", encoding="utf-8")
    except OSError:
        pass

    cid = _start_updater_container(f"apply {host_prepared}")
    return {
        "ok": True,
        "container_id": cid[:12],
        "old_version": cur,
        "new_version": target,
        "status": read_status(),
    }


def rollback_update(*, actor_name: str = "admin") -> Dict[str, Any]:
    if _latest_backup() is None:
        raise ValueError("Geri alınacak yedek yok")
    ensure_wrapper_script()
    cur = current_version()
    write_status(
        {
            "state": "running",
            "action": "rollback",
            "old_version": cur,
            "new_version": "",
            "message": f"Geri alma başlatıldı ({actor_name})",
        }
    )
    try:
        log_path().write_text("", encoding="utf-8")
    except OSError:
        pass
    cid = _start_updater_container("rollback")
    return {"ok": True, "container_id": cid[:12], "status": read_status()}
