"""
Paket Yönetimi Servisi
SSH üzerinden:
  - .deb / .rpm dosyası dağıtımı (SFTP + dpkg/rpm)
  - apt / yum / dnf sistem güncellemesi
  - Mevcut güncellemeleri listeleme
"""
import logging
import time
import os
import io
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

import paramiko
from sqlalchemy.orm import Session

from app.models.server import Server
from app.models.credential import GlobalCredential
from app.models.package_job import PackageJob

logger = logging.getLogger(__name__)

UPLOADS_DIR = "/app/uploads/packages"


# ─── Credential helpers ─────────────────────────────────────────────────────

def _resolve_creds(server: Server, global_cred: Optional[GlobalCredential] = None) -> dict:
    cfg = server.connection_config or {}
    return {
        "host":         server.ip_address,
        "port":         int(cfg.get("port") or (global_cred.port if global_cred else 22) or 22),
        "username":     cfg.get("username") or (global_cred.username if global_cred else "root") or "root",
        "password":     cfg.get("password") or (global_cred.password if global_cred else None),
        "private_key":  cfg.get("private_key") or (global_cred.private_key if global_cred else None),
        "sudo_password": cfg.get("sudo_password") or (global_cred.sudo_password if global_cred else None),
    }


def _make_client(creds: dict) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    pkey = None
    if creds.get("private_key"):
        for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                pkey = cls.from_private_key(io.StringIO(creds["private_key"]))
                break
            except Exception:
                pass

    connected = False
    if pkey:
        try:
            client.connect(creds["host"], port=creds["port"], username=creds["username"],
                           pkey=pkey, timeout=10, allow_agent=False, look_for_keys=False)
            connected = True
        except Exception:
            pass

    if not connected and creds.get("password"):
        client.connect(creds["host"], port=creds["port"], username=creds["username"],
                       password=creds["password"], timeout=10, allow_agent=False, look_for_keys=False)
        connected = True

    if not connected:
        raise Exception("SSH bağlantısı kurulamadı")

    return client


def _run_cmd(client: paramiko.SSHClient, cmd: str, sudo_pass: Optional[str] = None,
             timeout: int = 300) -> tuple[int, str, str]:
    """Komut çalıştırır. (exit_code, stdout, stderr) döner."""
    if sudo_pass and not cmd.startswith("echo"):
        cmd = f"echo '{sudo_pass}' | sudo -S sh -c {_shell_quote(cmd)}"
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=False)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def _shell_quote(s: str) -> str:
    return "'" + s.replace("'", "'\\''") + "'"


def _detect_pkg_manager(client: paramiko.SSHClient) -> str:
    """'apt' | 'yum' | 'dnf' | 'unknown'"""
    for mgr in ("dnf", "apt-get", "yum"):
        code, _, _ = _run_cmd(client, f"command -v {mgr}", timeout=5)
        if code == 0:
            return "apt" if mgr == "apt-get" else mgr
    return "unknown"


# ─── Tek sunucu operasyonları (sync, thread'de çalışır) ─────────────────────

def _deploy_to_one(server: Server, file_path: str, original_name: str,
                   global_cred: Optional[GlobalCredential]) -> Dict[str, Any]:
    """Tek sunucuya paket dağıt. Sonuç dict'i döner."""
    t0 = time.time()
    creds = _resolve_creds(server, global_cred)
    remote_path = f"/tmp/{original_name}"

    try:
        client = _make_client(creds)

        # SFTP ile dosyayı gönder
        sftp = client.open_sftp()
        sftp.put(file_path, remote_path)
        sftp.close()

        # Paket tipine göre kur
        ext = original_name.rsplit(".", 1)[-1].lower()
        sudo = creds.get("sudo_password")

        if ext == "deb":
            code, out, err = _run_cmd(
                client,
                f"DEBIAN_FRONTEND=noninteractive dpkg -i {remote_path} 2>&1 || "
                f"DEBIAN_FRONTEND=noninteractive apt-get install -f -y 2>&1",
                sudo_pass=sudo, timeout=300,
            )
        elif ext == "rpm":
            code, out, err = _run_cmd(
                client,
                f"rpm -Uvh --force {remote_path} 2>&1",
                sudo_pass=sudo, timeout=300,
            )
        else:
            code, out, err = 1, "", "Desteklenmeyen paket türü (deb/rpm gerekli)"

        # Temp dosyayı temizle
        _run_cmd(client, f"rm -f {remote_path}", sudo_pass=sudo, timeout=10)
        client.close()

        return {
            "status":   "success" if code == 0 else "failed",
            "output":   out[:4000],
            "error":    err[:2000],
            "duration": round(time.time() - t0, 1),
        }

    except Exception as exc:
        logger.warning(f"deploy_to_one({server.name}): {exc}")
        return {"status": "failed", "output": "", "error": str(exc),
                "duration": round(time.time() - t0, 1)}


def _upgrade_one(server: Server, security_only: bool,
                 global_cred: Optional[GlobalCredential]) -> Dict[str, Any]:
    """Tek sunucuda sistem güncellemesi yap."""
    t0 = time.time()
    creds = _resolve_creds(server, global_cred)

    try:
        client = _make_client(creds)
        mgr    = _detect_pkg_manager(client)
        sudo   = creds.get("sudo_password")
        output_parts: list[str] = []

        if mgr == "apt":
            code, out, _ = _run_cmd(
                client, "DEBIAN_FRONTEND=noninteractive apt-get update -y 2>&1",
                sudo_pass=sudo, timeout=120,
            )
            output_parts.append(f"[apt update]\n{out}")

            if security_only:
                upgrade_cmd = (
                    "DEBIAN_FRONTEND=noninteractive apt-get install -y "
                    "$(apt-get -s upgrade 2>/dev/null | grep -i 'Inst.*security' | awk '{print $2}') 2>&1"
                )
            else:
                upgrade_cmd = "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y 2>&1"

            code, out, err = _run_cmd(client, upgrade_cmd, sudo_pass=sudo, timeout=600)
            output_parts.append(f"[apt upgrade]\n{out}")

        elif mgr in ("yum", "dnf"):
            if security_only:
                cmd = f"{mgr} update --security -y 2>&1"
            else:
                cmd = f"{mgr} update -y 2>&1"
            code, out, err = _run_cmd(client, cmd, sudo_pass=sudo, timeout=600)
            output_parts.append(f"[{mgr} update]\n{out}")
        else:
            code, out, err = 1, "", "Paket yöneticisi tespit edilemedi (apt/yum/dnf bulunamadı)"

        client.close()
        return {
            "status":   "success" if code == 0 else "failed",
            "output":   "\n".join(output_parts)[:6000],
            "error":    err[:2000] if "err" in dir() else "",
            "duration": round(time.time() - t0, 1),
        }

    except Exception as exc:
        logger.warning(f"upgrade_one({server.name}): {exc}")
        return {"status": "failed", "output": "", "error": str(exc),
                "duration": round(time.time() - t0, 1)}


def _check_updates_one(server: Server,
                       global_cred: Optional[GlobalCredential]) -> Dict[str, Any]:
    """Tek sunucuda mevcut güncellemeleri listele."""
    t0 = time.time()
    creds = _resolve_creds(server, global_cred)

    try:
        client = _make_client(creds)
        mgr    = _detect_pkg_manager(client)
        sudo   = creds.get("sudo_password")

        if mgr == "apt":
            _run_cmd(client, "apt-get update -qq 2>/dev/null", sudo_pass=sudo, timeout=60)
            code, out, err = _run_cmd(
                client, "apt list --upgradable 2>/dev/null | tail -n +2",
                timeout=30,
            )
        elif mgr in ("yum", "dnf"):
            code, out, err = _run_cmd(
                client, f"{mgr} check-update 2>/dev/null || true",
                sudo_pass=sudo, timeout=120,
            )
        else:
            code, out, err = 1, "", "Paket yöneticisi tespit edilemedi"

        client.close()

        lines = [l for l in out.strip().splitlines() if l.strip()]
        return {
            "status":        "success",
            "update_count":  len(lines),
            "output":        out[:4000],
            "error":         err[:500],
            "duration":      round(time.time() - t0, 1),
        }

    except Exception as exc:
        logger.warning(f"check_updates_one({server.name}): {exc}")
        return {"status": "failed", "output": "", "error": str(exc),
                "update_count": 0, "duration": round(time.time() - t0, 1)}


# ─── Job runner (arka planda çalışır) ────────────────────────────────────────

def run_package_job(job_id: int, servers: List[Server],
                    global_cred: Optional[GlobalCredential],
                    operation: str,                    # deploy | upgrade | check_updates
                    file_path: str = "",
                    original_name: str = "",
                    security_only: bool = False) -> None:
    """
    Blocking — ThreadPoolExecutor'dan çağrılır.
    Her sunucu için operasyonu çalıştırır ve job kaydını günceller.
    """
    from app.core.database import SessionLocal
    db: Session = SessionLocal()

    try:
        job: PackageJob = db.query(PackageJob).filter_by(id=job_id).first()
        if not job:
            return

        job.status = "running"
        db.commit()

        results: dict = {}
        success_count = 0
        fail_count    = 0

        for srv in servers:
            sid = str(srv.id)
            logger.info(f"PackageJob #{job_id} [{operation}] → {srv.name} ({srv.ip_address})")

            if operation == "deploy":
                res = _deploy_to_one(srv, file_path, original_name, global_cred)
            elif operation == "upgrade":
                res = _upgrade_one(srv, security_only, global_cred)
            else:
                res = _check_updates_one(srv, global_cred)

            res["server_name"] = srv.name
            res["server_ip"]   = srv.ip_address
            results[sid]       = res

            if res["status"] == "success":
                success_count += 1
            else:
                fail_count += 1

            # Her sunucu bittikçe DB'yi güncelle (canlı ilerleme)
            job.results           = dict(results)
            job.completed_servers = success_count + fail_count
            db.commit()

        # Son durum
        if fail_count == 0:
            job.status = "completed"
        elif success_count == 0:
            job.status = "failed"
        else:
            job.status = "partial"

        job.completed_at = datetime.now(timezone.utc)
        db.commit()

    except Exception as exc:
        logger.error(f"run_package_job #{job_id}: {exc}", exc_info=True)
        try:
            job = db.query(PackageJob).filter_by(id=job_id).first()
            if job:
                job.status = "failed"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()
