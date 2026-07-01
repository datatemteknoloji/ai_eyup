"""
Paket Yönetimi Servisi
SSH üzerinden:
  - .deb / .rpm dosyası dağıtımı (SFTP + dpkg/rpm)
  - apt / yum / dnf sistem güncellemesi
  - Mevcut güncellemeleri listeleme
"""
import logging
import socket
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

def _resolve_creds(server: Server, global_cred: Optional[GlobalCredential] = None,
                   override_user: Optional[str] = None,
                   override_password: Optional[str] = None,
                   override_sudo_password: Optional[str] = None) -> dict:
    from app.core.encryption import decrypt_secret
    cfg = server.connection_config or {}
    base_user  = cfg.get("username") or (global_cred.username if global_cred else "root") or "root"
    _rp  = cfg.get("password") or (global_cred.password if global_cred else None)
    _rs  = cfg.get("sudo_password") or (global_cred.sudo_password if global_cred else None)
    _rk  = cfg.get("private_key") or (global_cred.private_key if global_cred else None)
    base_pass  = decrypt_secret(_rp) if _rp else None
    base_sudo  = decrypt_secret(_rs) if _rs else None
    base_key   = decrypt_secret(_rk) if _rk else None
    base_port  = int(cfg.get("port") or (global_cred.port if global_cred else 22) or 22)

    return {
        "host":         server.ip_address,
        "port":         base_port,
        "username":     override_user or base_user,
        "password":     override_password or base_pass,
        "private_key":  base_key if not override_user else None,
        "sudo_password": override_sudo_password or (override_password if override_user else base_sudo),
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
             timeout: int = 300,
             log_callback=None) -> tuple[int, str, str]:
    """Komut çalıştırır. (exit_code, stdout, stderr) döner.
    log_callback(line) varsa her satır için çağrılır (canlı log akışı).
    Şifre komut dizisine gömülmez; PTY channel stdin'e gönderilir.
    """
    actual_cmd = f"sudo -S sh -c {_shell_quote(cmd)}" if sudo_pass else cmd

    transport = client.get_transport()
    channel = transport.open_session()
    channel.settimeout(timeout)
    channel.get_pty()
    channel.exec_command(actual_cmd)

    if sudo_pass:
        time.sleep(0.3)          # sudo şifre prompt'unu bekle
        channel.sendall((sudo_pass + "\n").encode())

    out_lines: list[str] = []
    buf = ""
    timed_out = False
    while True:
        try:
            data = channel.recv(4096)
        except socket.timeout:
            timed_out = True
            break
        except Exception:
            break
        if not data:
            break
        chunk = data.decode("utf-8", errors="replace")
        buf += chunk
        while "\n" in buf:
            line, buf = buf.split("\n", 1)
            line += "\n"
            out_lines.append(line)
            if log_callback:
                try:
                    log_callback(line)
                except Exception:
                    pass
    if buf:
        out_lines.append(buf)
        if log_callback:
            try:
                log_callback(buf)
            except Exception:
                pass

    out  = "".join(out_lines)
    err  = ""   # get_pty=True ile stderr stdout'a karışır
    if timed_out:
        channel.close()
        return 1, out, f"Komut zaman aşımına uğradı ({timeout}s)"
    code = channel.recv_exit_status()
    channel.close()
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
                   global_cred: Optional[GlobalCredential],
                   override_user: Optional[str] = None,
                   override_password: Optional[str] = None,
                   override_sudo_password: Optional[str] = None,
                   log_callback=None) -> Dict[str, Any]:
    """Tek sunucuya paket dağıt. Sonuç dict'i döner."""
    t0 = time.time()
    creds = _resolve_creds(server, global_cred, override_user, override_password, override_sudo_password)
    remote_path = f"/tmp/{original_name}"

    def _log(msg: str):
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass

    try:
        client = _make_client(creds)
        _log(f"[SSH] {server.ip_address} bağlantısı kuruldu\n")

        # SFTP ile dosyayı /tmp'ye gönder
        sftp = client.open_sftp()
        _log(f"[SFTP] {original_name} → /tmp/ kopyalanıyor...\n")
        sftp.put(file_path, remote_path)
        sftp.close()
        _log(f"[SFTP] Dosya kopyalandı: {remote_path}\n")

        # Paket tipine göre kur
        ext  = original_name.rsplit(".", 1)[-1].lower()
        sudo = creds.get("sudo_password")

        if ext == "deb":
            code, out, err = _run_cmd(
                client,
                f"DEBIAN_FRONTEND=noninteractive dpkg -i {remote_path} || "
                f"DEBIAN_FRONTEND=noninteractive apt-get install -f -y",
                sudo_pass=sudo, timeout=300, log_callback=_log,
            )
        elif ext == "rpm":
            code, out, err = _run_cmd(
                client,
                f"rpm -Uvh --force {remote_path}",
                sudo_pass=sudo, timeout=300, log_callback=_log,
            )
        else:
            code, out, err = 1, "", "Desteklenmeyen paket türü (deb/rpm gerekli)"

        _run_cmd(client, f"rm -f {remote_path}", sudo_pass=sudo, timeout=10)
        client.close()

        return {
            "status":   "success" if code == 0 else "failed",
            "output":   out[:8000],
            "error":    err[:2000],
            "duration": round(time.time() - t0, 1),
        }

    except Exception as exc:
        logger.warning(f"deploy_to_one({server.name}): {exc}")
        return {"status": "failed", "output": "", "error": str(exc),
                "duration": round(time.time() - t0, 1)}


def _upgrade_one(server: Server, security_only: bool,
                 global_cred: Optional[GlobalCredential],
                 log_callback=None) -> Dict[str, Any]:
    """Tek sunucuda sistem güncellemesi yap."""
    t0 = time.time()
    creds = _resolve_creds(server, global_cred)

    def _log(msg: str):
        if log_callback:
            try:
                log_callback(msg)
            except Exception:
                pass

    try:
        client = _make_client(creds)
        _log(f"[SSH] {server.ip_address} bağlantısı kuruldu\n")
        mgr    = _detect_pkg_manager(client)
        sudo   = creds.get("sudo_password")
        output_parts: list[str] = []

        if mgr == "apt":
            _log("[apt] Paket listesi güncelleniyor...\n")
            code, out, _ = _run_cmd(
                client, "DEBIAN_FRONTEND=noninteractive apt-get update -y",
                sudo_pass=sudo, timeout=120, log_callback=_log,
            )
            output_parts.append(f"[apt update]\n{out}")

            if security_only:
                upgrade_cmd = (
                    "DEBIAN_FRONTEND=noninteractive apt-get install -y "
                    "$(apt-get -s upgrade 2>/dev/null | grep -i 'Inst.*security' | awk '{print $2}')"
                )
            else:
                upgrade_cmd = "DEBIAN_FRONTEND=noninteractive apt-get upgrade -y"

            _log(f"[apt] {'Güvenlik' if security_only else 'Tam'} güncelleme başlıyor...\n")
            code, out, err = _run_cmd(client, upgrade_cmd, sudo_pass=sudo, timeout=600,
                                      log_callback=_log)
            output_parts.append(f"[apt upgrade]\n{out}")

        elif mgr in ("yum", "dnf"):
            cmd = f"{mgr} update {'--security' if security_only else ''} -y"
            _log(f"[{mgr}] {'Güvenlik' if security_only else 'Tam'} güncelleme başlıyor...\n")
            code, out, err = _run_cmd(client, cmd, sudo_pass=sudo, timeout=600,
                                      log_callback=_log)
            output_parts.append(f"[{mgr} update]\n{out}")
        else:
            code, out, err = 1, "", "Paket yöneticisi tespit edilemedi (apt/yum/dnf bulunamadı)"

        client.close()
        return {
            "status":   "success" if code == 0 else "failed",
            "output":   "\n".join(output_parts)[:12000],
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

def run_package_job(job_id: int, server_ids: List[int],
                    operation: str,                    # deploy | upgrade | check_updates
                    file_path: str = "",
                    original_name: str = "",
                    security_only: bool = False,
                    override_user: Optional[str] = None,
                    override_password: Optional[str] = None,
                    override_sudo_password: Optional[str] = None) -> None:
    """
    Blocking — ThreadPoolExecutor'dan çağrılır.
    Server nesnelerini kendi session'ından yükler (detached object sorunu olmaz).
    """
    from app.core.database import ThreadSessionLocal as SessionLocal
    db: Session = SessionLocal()

    try:
        job: PackageJob = db.query(PackageJob).filter_by(id=job_id).first()
        if not job:
            return

        # Sunucuları ve global credential'ı thread'in kendi session'ından yükle
        servers     = db.query(Server).filter(Server.id.in_(server_ids)).all()
        global_cred = db.query(GlobalCredential).filter_by(is_default=True).first() \
                      or db.query(GlobalCredential).first()

        job.status = "running"
        db.commit()

        results: dict = {}
        success_count = 0
        fail_count    = 0

        for srv in servers:
            sid = str(srv.id)
            logger.info(f"PackageJob #{job_id} [{operation}] → {srv.name} ({srv.ip_address})")

            # Canlı log tampon — periyodik DB yazımı
            _live_buf: list[str] = []
            _last_flush = [time.time()]

            def _make_log_cb(job_ref, srv_id: str, buf: list, last_flush: list):
                def _cb(line: str):
                    buf.append(line)
                    now = time.time()
                    if now - last_flush[0] >= 0.8:   # 800ms'de bir flush
                        last_flush[0] = now
                        try:
                            cur_log = dict(job_ref.live_log or {})
                            cur_log[srv_id] = "".join(buf)[-6000:]
                            job_ref.live_log = cur_log
                            db.commit()
                        except Exception:
                            pass
                return _cb

            log_cb = _make_log_cb(job, sid, _live_buf, _last_flush)

            if operation == "deploy":
                res = _deploy_to_one(srv, file_path, original_name, global_cred,
                                     override_user, override_password, override_sudo_password,
                                     log_callback=log_cb)
            elif operation == "upgrade":
                res = _upgrade_one(srv, security_only, global_cred, log_callback=log_cb)
            else:
                res = _check_updates_one(srv, global_cred)

            res["server_name"] = srv.name
            res["server_ip"]   = srv.ip_address
            results[sid]       = res

            if res["status"] == "success":
                success_count += 1
            else:
                fail_count += 1

            # Sunucu bittikçe live_log'u da final output ile güncelle
            cur_log = dict(job.live_log or {})
            cur_log[sid] = "".join(_live_buf)[-6000:]
            job.live_log = cur_log

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
