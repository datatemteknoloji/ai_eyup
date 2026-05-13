"""
Sistem Güncelleme Servisi - SSH tabanlı check/apply
"""
import io, time, logging, paramiko
from typing import Optional, List, Dict, Any
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


def _resolve_creds(server, global_cred=None,
                   override_username=None, override_password=None,
                   override_sudo_password=None) -> dict:
    """
    Kimlik bilgisi önceliği:
    1. Plan'daki override (yetkili kullanıcı adımında girildi)
    2. Server'ın connection_config
    3. Global credential
    """
    cfg = server.connection_config or {}
    base_username = cfg.get("username") or (global_cred.username if global_cred else "root") or "root"
    base_password = cfg.get("password") or (global_cred.password if global_cred else None)
    base_key      = cfg.get("private_key") or (global_cred.private_key if global_cred else None)
    base_sudo     = cfg.get("sudo_password") or (global_cred.sudo_password if global_cred else None)

    # Override geçerliyse kullan
    username = override_username or base_username
    password = override_password or base_password
    # sudo password: override varsa onu kullan, yoksa override_password (kullanıcı şifresiyle sudo olabilir)
    sudo_pw  = override_sudo_password or (override_password if override_username else base_sudo) or base_password

    return {
        "host":          server.ip_address,
        "port":          int(cfg.get("port") or (global_cred.port if global_cred else 22) or 22),
        "username":      username,
        "password":      password,
        "private_key":   None if override_username else base_key,  # override varsa key kullanma
        "sudo_password": sudo_pw,
    }


def _make_client(creds: dict) -> paramiko.SSHClient:
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    pkey = None
    if creds.get("private_key"):
        for cls in (paramiko.RSAKey, paramiko.Ed25519Key, paramiko.ECDSAKey):
            try:
                pkey = cls.from_private_key(io.StringIO(creds["private_key"])); break
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
    return client


def _run(client, cmd, sudo_pass=None, timeout=600, priv_method="sudo"):
    """
    Komutu yetki yükseltme yöntemiyle çalıştırır.
    priv_method: sudo | dzdo | su | pbrun | direct
    """
    safe_cmd = cmd.replace("'", "'\\''")
    if priv_method == "dzdo":
        # Centrify DirectControl — dzdo genellikle AD şifresiyle veya şifresiz çalışır
        if sudo_pass:
            cmd = f"echo '{sudo_pass}' | dzdo -S sh -c '{safe_cmd}'"
        else:
            cmd = f"dzdo sh -c '{safe_cmd}'"
    elif priv_method == "su":
        if sudo_pass:
            cmd = f"echo '{sudo_pass}' | su -c '{safe_cmd}' root"
        else:
            cmd = f"su -c '{safe_cmd}' root"
    elif priv_method == "pbrun":
        # Powerbroker / BeyondTrust
        cmd = f"pbrun sh -c '{safe_cmd}'"
    elif priv_method == "sudo":
        if sudo_pass:
            cmd = f"echo '{sudo_pass}' | sudo -S sh -c '{safe_cmd}'"
        elif cmd not in ("whoami", "uname -r") and not cmd.startswith("command"):
            cmd = f"sudo sh -c '{safe_cmd}'"
    # direct: komut olduğu gibi çalışır (root kullanıcı)

    _, stdout, stderr = client.exec_command(cmd, timeout=timeout, get_pty=False)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def _detect_pkg_manager(client) -> str:
    for mgr in ("dnf", "apt-get", "yum"):
        code, _, _ = _run(client, f"command -v {mgr}", timeout=5)
        if code == 0:
            return "apt" if mgr == "apt-get" else mgr
    return "unknown"


def check_available_updates(server, update_type: str, global_cred=None) -> List[Dict]:
    creds = _resolve_creds(server, global_cred)
    sudo  = creds.get("sudo_password")
    try:
        client = _make_client(creds)
        mgr    = _detect_pkg_manager(client)
        result = []
        if mgr in ("dnf", "yum"):
            _run(client, f"{mgr} makecache -q 2>/dev/null || true", sudo_pass=sudo, timeout=60)
            if update_type == "security":
                _, out, _ = _run(client, f"{mgr} check-update --security 2>/dev/null; true", sudo_pass=sudo, timeout=60)
                result = _parse_dnf_check_update(out, is_security=True)
            elif update_type == "kernel":
                _, out, _ = _run(client, f"{mgr} check-update kernel* 2>/dev/null; true", sudo_pass=sudo, timeout=60)
                result = _parse_dnf_check_update(out, kernel_only=True)
            else:
                _, out, _ = _run(client, f"{mgr} check-update 2>/dev/null; true", sudo_pass=sudo, timeout=90)
                result = _parse_dnf_check_update(out)
        elif mgr == "apt":
            _run(client, "apt-get update -qq 2>/dev/null", sudo_pass=sudo, timeout=60)
            _, out, _ = _run(client, "apt list --upgradable 2>/dev/null | tail -n +2", timeout=30)
            result = _parse_apt_upgradable(out, update_type)
        client.close()
        return result
    except Exception as exc:
        return [{"name": "ERROR", "error": str(exc), "is_security": False, "is_kernel": False}]


def _parse_dnf_check_update(output, is_security=False, kernel_only=False):
    pkgs = []
    for line in output.splitlines():
        line = line.strip()
        if not line or any(x in line for x in ["Last metadata", "Loading", "Loaded", "Obsoleting"]):
            continue
        parts = line.split()
        if len(parts) >= 2 and "." in parts[0]:
            name = parts[0].rsplit(".", 1)[0]
            is_kern = "kernel" in name.lower()
            if kernel_only and not is_kern:
                continue
            pkgs.append({"name": name, "new_version": parts[1] if len(parts) > 1 else "",
                         "repo": parts[2] if len(parts) > 2 else "",
                         "is_security": is_security, "is_kernel": is_kern})
    return pkgs


def _parse_apt_upgradable(output, update_type):
    pkgs = []
    for line in output.splitlines():
        parts = line.strip().split()
        if parts and "/" in parts[0]:
            name = parts[0].split("/")[0]
            is_kern = "linux-image" in name
            pkgs.append({"name": name, "new_version": parts[1] if len(parts) > 1 else "",
                         "is_security": "security" in line.lower(), "is_kernel": is_kern})
    return pkgs


def check_reboot_required(client, mgr) -> bool:
    code, out, _ = _run(client, "needs-restarting -r 2>/dev/null; echo RC:$?", timeout=10)
    if "RC:1" in out:
        return True
    code2, _, _ = _run(client, "test -f /var/run/reboot-required", timeout=5)
    return code2 == 0


def apply_updates_to_server(server, update_type, global_cred=None,
                             repo_file_content=None, repo_name=None,
                             override_username=None, override_password=None,
                             override_sudo_password=None, priv_method="sudo"):
    t0 = time.time()
    creds = _resolve_creds(server, global_cred,
                           override_username, override_password, override_sudo_password)
    sudo = creds.get("sudo_password")
    pm   = priv_method or "sudo"
    log_lines = []

    def log(msg):
        log_lines.append(f"[{datetime.now(timezone.utc).strftime('%H:%M:%S')}] {msg}")

    try:
        client = _make_client(creds); mgr = _detect_pkg_manager(client)
        log(f"Bağlantı: {server.ip_address} ({mgr})")

        tmp_repo_file = None
        if repo_file_content and repo_name:
            tmp_repo_file = f"/etc/yum.repos.d/{repo_name}-update.repo" if mgr != "apt" \
                           else f"/etc/apt/sources.list.d/{repo_name}-update.list"
            escaped = repo_file_content.replace("'", "'\\''")
            _run(client, f"echo '{escaped}' | tee {tmp_repo_file} > /dev/null", sudo_pass=sudo, timeout=10)
            log(f"Geçici repo eklendi: {tmp_repo_file}")
            if mgr in ("dnf", "yum"):
                _run(client, f"{mgr} makecache -q 2>/dev/null || true", sudo_pass=sudo, timeout=60)
            elif mgr == "apt":
                _run(client, "apt-get update -qq 2>/dev/null", sudo_pass=sudo, timeout=60)

        if mgr in ("dnf", "yum"):
            if update_type == "security":
                cmd = f"{mgr} update --security -y 2>&1"
            elif update_type == "kernel":
                cmd = f"{mgr} update kernel* -y 2>&1"
            else:
                cmd = f"{mgr} update -y 2>&1"
        elif mgr == "apt":
            if update_type == "security":
                cmd = "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y $(apt-get -s upgrade 2>/dev/null | grep security | awk '{print $2}') 2>&1"
            elif update_type == "kernel":
                cmd = "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get install -y linux-image-generic 2>&1"
            else:
                cmd = "apt-get update -qq && DEBIAN_FRONTEND=noninteractive apt-get upgrade -y 2>&1"
        else:
            raise RuntimeError("Paket yöneticisi bulunamadı")

        log(f"Güncelleme başlatılıyor ({update_type})...")
        code, out, err = _run(client, cmd, sudo_pass=sudo, timeout=1800, priv_method=pm)
        log(f"exit={code}")
        log_lines.append(out[-3000:])

        pkgs_updated = []
        in_upd = False
        for line in out.splitlines():
            if "Upgraded:" in line or "Updated:" in line:
                in_upd = True; continue
            if in_upd:
                if not line.strip() or (line[0].isalpha() and ":" in line):
                    in_upd = False; continue
                parts = line.strip().split()
                if parts:
                    pkgs_updated.append({"name": parts[0], "version": parts[1] if len(parts) > 1 else ""})

        reboot_req = check_reboot_required(client, mgr)
        if reboot_req:
            log("⚠️ Reboot gerekiyor")
        if tmp_repo_file:
            _run(client, f"rm -f {tmp_repo_file}", sudo_pass=sudo, timeout=10)
        client.close()
        return {"status": "success" if code == 0 else "failed", "log": "\n".join(log_lines),
                "packages_updated": pkgs_updated, "reboot_required": reboot_req,
                "duration": round(time.time() - t0, 1)}
    except Exception as exc:
        log(f"HATA: {exc}")
        return {"status": "failed", "log": "\n".join(log_lines), "packages_updated": [],
                "reboot_required": False, "duration": round(time.time() - t0, 1), "error": str(exc)}


def run_system_update_plan(plan_id: int) -> None:
    from app.core.database import SessionLocal
    from app.models.system_update import SystemUpdatePlan, SystemUpdateJob
    from app.models.server import Server
    from app.models.credential import GlobalCredential
    from app.models.repository import RepoSource
    from app.services.repo_sync_service import generate_repo_file
    import socket

    db = SessionLocal()
    try:
        plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
        if not plan:
            return
        plan.status = "running"
        plan.started_at = datetime.now(timezone.utc)
        db.commit()

        global_cred = db.query(GlobalCredential).filter_by(is_default=True).first() \
                      or db.query(GlobalCredential).first()

        repo_file_content = repo_name = None
        if plan.repo_id:
            repo = db.query(RepoSource).filter_by(id=plan.repo_id).first()
            if repo:
                try:
                    server_ip = socket.gethostbyname(socket.gethostname())
                except Exception:
                    server_ip = "127.0.0.1"
                repo_file_content = generate_repo_file(repo, server_ip, 8000)
                repo_name = repo.name

        jobs = db.query(SystemUpdateJob).filter_by(plan_id=plan_id).all()
        success_count = fail_count = 0

        for job in jobs:
            server = db.query(Server).filter_by(id=job.server_id).first()
            if not server:
                job.status = "skipped"; db.commit(); continue

            job.status = "running"
            job.started_at = datetime.now(timezone.utc)
            db.commit()

            result = apply_updates_to_server(
                server, plan.update_type, global_cred,
                repo_file_content, repo_name,
                override_username=plan.override_username,
                override_password=plan.override_password,
                override_sudo_password=plan.override_sudo_password,
                priv_method=plan.priv_method or "sudo",
            )
            job.status           = result["status"]
            job.log              = result.get("log", "")
            job.packages_updated = result.get("packages_updated", [])
            job.reboot_required  = result.get("reboot_required", False)
            job.completed_at     = datetime.now(timezone.utc)
            db.commit()

            if result["status"] == "success":
                success_count += 1
            else:
                fail_count += 1
            plan.completed_servers = success_count + fail_count
            db.commit()

        plan.status = "completed" if fail_count == 0 else ("failed" if success_count == 0 else "partial")
        plan.completed_at = datetime.now(timezone.utc)
        db.commit()

        try:
            _generate_ai_summary(plan_id, db)
        except Exception:
            pass
    except Exception as exc:
        logger.error(f"run_system_update_plan #{plan_id}: {exc}", exc_info=True)
        try:
            plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
            if plan:
                plan.status = "failed"; db.commit()
        except Exception:
            pass
    finally:
        db.close()


def _generate_ai_summary(plan_id, db):
    from app.models.system_update import SystemUpdatePlan, SystemUpdateJob
    import requests, json
    plan = db.query(SystemUpdatePlan).filter_by(id=plan_id).first()
    jobs = db.query(SystemUpdateJob).filter_by(plan_id=plan_id).all()
    total_pkgs = sum(len(j.packages_updated or []) for j in jobs)
    reboot_count = sum(1 for j in jobs if j.reboot_required)
    fail_count   = sum(1 for j in jobs if j.status == "failed")
    prompt = f"""Sistem güncelleme tamamlandı. Türkçe özet (3-4 cümle):
Plan: {plan.name} | Tip: {plan.update_type} | Toplam sunucu: {plan.total_servers}
Başarılı: {plan.completed_servers - fail_count} | Başarısız: {fail_count}
Toplam güncellenen paket: {total_pkgs} | Reboot gereken: {reboot_count}"""
    try:
        from app.core.config import settings
        r = requests.post(f"{settings.OLLAMA_URL}/api/generate",
                          json={"model": "qwen2.5:latest", "prompt": prompt, "stream": False}, timeout=60)
        if r.status_code == 200:
            plan.ai_summary = r.json().get("response", "")
            db.commit()
    except Exception:
        pass
