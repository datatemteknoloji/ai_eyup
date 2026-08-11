"""
Otomatik onboarding — Entegrasyonlar'dan eklenen sunucuların Canlı Metrikler'de
manuel müdahale gerekmeden görünmesi için arka planda çalışan işlevler:

  1) AI Ready testi     — SSH (Linux) / WinRM (Windows) ile erişim doğrulanır
  2) OS/Kernel bilgisi   — AI Ready olan, os_version/kernel_version bilgisi eksik
                           Linux sunuculardan SSH ile /etc/os-release + uname -r toplanır
  3) Exporter kurulumu  — AI Ready olan, henüz kurulu olmayan sunuculara
                          Node Exporter (Linux) / Windows Exporter (Windows) kurulur
  4) Windows Update/Defender — AI Ready Windows sunuculardan WinRM ile bekleyen
                          güncelleme sayısı, reboot durumu ve Defender durumu toplanır
  5) Linux güvenlik denetimi — AI Ready Linux sunuculardan SSH ile firewall/SELinux
                          durumu ve son 24 saatteki başarısız giriş sayısı toplanır

Tüm fonksiyonlar senkron (blocking) — background_tasks.py bunları
run_in_executor ile thread pool'da çağırır. Raporlar bu şekilde toplanan
cache alanlarını okur; rapor üretimi sırasında canlı SSH/WinRM sorgusu YAPILMAZ
(hızlı ve senkron çalışması için)."""
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional

from sqlalchemy import or_
from app.services.bulk_concurrency import bulk_ssh_workers
from sqlalchemy.orm import Session

from app.models.server import Server
from app.services.monitoring.node_exporter_installer import NodeExporterInstaller
from app.services.platform_scope import is_windows_server
from app.services.ssh_manager import SSHManager

logger = logging.getLogger(__name__)

# Windows Update/Defender ve Linux güvenlik denetimi ağır/yavaş işlemler olduğundan
# (COM update search, SSH turu) her onboarding döngüsünde (10dk) değil, bu aralıktan
# daha eski kontrolü olan sunucular için tekrar çalıştırılır.
_RECHECK_INTERVAL = timedelta(hours=6)


def _parse_os_release(text: str) -> Dict[str, str]:
    pretty_name = ""
    version_id = ""
    release_id = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("PRETTY_NAME="):
            pretty_name = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("VERSION_ID="):
            version_id = line.split("=", 1)[1].strip().strip('"')
        elif line.startswith("ID=") and not line.startswith("ID_LIKE="):
            release_id = line.split("=", 1)[1].strip().strip('"')
    return {
        "pretty_name": pretty_name,
        "version_id": version_id,
        "release_id": release_id,
    }


def collect_os_release_info(db: Session) -> Dict:
    """AI Ready olup os_version / os_version_id / kernel eksik olan Linux
    sunuculara SSH ile bağlanıp /etc/os-release ve `uname -r` bilgisini toplar.

    vCenter guest_OS yalnızca major verir (RHEL_9_64 → RHEL 9); minor (9.7 / 9.8)
    yalnızca guest içinden VERSION_ID ile gelir.
    """
    from app.models.credential import GlobalCredential
    from app.services.ssh_credentials import resolve_ssh_creds

    servers = (
        db.query(Server)
        .filter(
            Server.ai_ready == True,  # noqa: E712
            Server.ip_address.isnot(None),
            Server.ip_address != "",
        )
        .filter(
            or_(
                Server.os_version.is_(None), Server.os_version == "",
                Server.os_version_id.is_(None), Server.os_version_id == "",
                Server.kernel_version.is_(None), Server.kernel_version == "",
            )
        )
        .all()
    )
    servers = [s for s in servers if not is_windows_server(s)]

    if not servers:
        return {"checked": 0, "updated": 0}

    global_cred = (
        db.query(GlobalCredential).filter_by(is_default=True).first()
        or db.query(GlobalCredential).first()
    )

    # Thread pool'a ORM nesnesi değil, çözülmüş snapshot ver.
    snapshots = []
    for srv in servers:
        creds = resolve_ssh_creds(srv, global_cred=global_cred)
        if not creds.get("has_secret"):
            continue
        snapshots.append({
            "id": srv.id,
            "host": creds["host"],
            "username": creds["username"] or "root",
            "password": creds["password"],
            "private_key": creds["private_key"],
            "port": creds["port"],
        })

    def _collect_one(snap: Dict) -> Optional[Dict[str, str]]:
        ssh = SSHManager(
            host=snap["host"],
            username=snap["username"],
            password=snap["password"],
            private_key=snap["private_key"],
            port=snap["port"],
        )
        try:
            if not ssh.connect():
                return None
            _, os_out, _ = ssh.execute_command("cat /etc/os-release 2>/dev/null")
            parsed = _parse_os_release(os_out)
            _, kernel_out, _ = ssh.execute_command("uname -r")
            parsed["kernel"] = kernel_out.strip()
            return parsed
        except Exception as e:
            logger.debug("OS release toplama hatası (id=%s): %s", snap["id"], e)
            return None
        finally:
            ssh.close()

    results: Dict[int, Optional[Dict[str, str]]] = {}
    with ThreadPoolExecutor(max_workers=bulk_ssh_workers(), thread_name_prefix="auto-osinfo") as pool:
        futures = {pool.submit(_collect_one, snap): snap["id"] for snap in snapshots}
        for fut in as_completed(futures):
            sid = futures[fut]
            results[sid] = fut.result()

    updated = 0
    for srv in servers:
        info = results.get(srv.id)
        if not info:
            continue
        changed = False
        if info.get("pretty_name") and (
            not srv.os_version or len(info["pretty_name"]) > len(srv.os_version or "")
        ):
            srv.os_version = info["pretty_name"]
            changed = True
        if info.get("version_id"):
            # Hypervisor major (9) yerine SSH minor (9.8) her zaman yazılsın
            if not srv.os_version_id or len(info["version_id"]) >= len(srv.os_version_id or ""):
                if info["version_id"] != (srv.os_version_id or ""):
                    srv.os_version_id = info["version_id"]
                    changed = True
        if info.get("release_id") and not srv.os_release_id:
            srv.os_release_id = info["release_id"]
            changed = True
        if info.get("kernel") and not srv.kernel_version:
            srv.kernel_version = info["kernel"]
            changed = True
        if info.get("release_id") and (
            not srv.os_type or str(srv.os_type).lower() in ("linux", "linuxguest", "")
        ):
            srv.os_type = info["release_id"]
            changed = True
        elif not srv.os_type:
            srv.os_type = "linux"
            changed = True
        if changed:
            updated += 1
    db.commit()

    if updated:
        logger.info("Auto-onboarding: %s Linux sunucunun OS/kernel bilgisi güncellendi", updated)

    return {"checked": len(snapshots), "updated": updated}


def auto_install_node_exporter(db: Session) -> Dict:
    """AI Ready + ONLINE + node_exporter kurulu olmayan Linux sunuculara otomatik kurulum."""
    servers = db.query(Server).filter(
        Server.status == "ONLINE",
        Server.ai_ready == True,  # noqa: E712
        Server.node_exporter_installed == False,  # noqa: E712
    ).all()
    servers = [s for s in servers if not is_windows_server(s)]

    if not servers:
        return {"queued": 0, "success": 0, "failed": 0}

    def _install_one(srv):
        # Thread pool içinde çalışır — SQLAlchemy session thread-safe olmadığından
        # burada DB'ye dokunulmaz, sadece SSH/paramiko işlemleri yapılır.
        try:
            installer = NodeExporterInstaller(srv)
            res = installer.install()
            return srv.id, srv.name, bool(res.get("success")), res.get("message", "")
        except Exception as e:
            return srv.id, srv.name, False, str(e)

    results = []
    with ThreadPoolExecutor(max_workers=bulk_ssh_workers(), thread_name_prefix="auto-ne") as pool:
        futures = {pool.submit(_install_one, s): s for s in servers}
        for f in as_completed(futures):
            results.append(f.result())

    by_id = {r[0]: r for r in results}
    for srv in servers:
        r = by_id.get(srv.id)
        if r:
            srv.node_exporter_installed = r[2]
            srv.node_exporter_running = r[2]
    db.commit()

    success = sum(1 for r in results if r[2])
    failed = len(results) - success
    if success:
        logger.info(
            "Auto onboarding — Node Exporter kuruldu: %s",
            ", ".join(r[1] for r in results if r[2]),
        )
    if failed:
        for _id, name, ok, msg in results:
            if not ok:
                logger.debug("Auto onboarding — Node Exporter kurulamadı (%s): %s", name, msg)

    try:
        from app.services.monitoring.prometheus_metrics import sync_node_exporter_targets_from_db
        sync_node_exporter_targets_from_db(db)
    except Exception:
        logger.debug("Prometheus target sync (auto onboarding) atlandı", exc_info=True)

    return {"queued": len(servers), "success": success, "failed": failed}


def _due_for_recheck(last_checked) -> bool:
    if not last_checked:
        return True
    now = datetime.now(timezone.utc) if last_checked.tzinfo else datetime.utcnow()
    return (now - last_checked) >= _RECHECK_INTERVAL


def collect_windows_update_status(db: Session) -> Dict:
    """AI Ready Windows sunuculardan WinRM ile bekleyen güncelleme sayısı, reboot
    gerekliliği ve Windows Defender durumunu toplar. Yama & Güvenlik raporları bu
    cache'i okur (rapor üretimi sırasında canlı WinRM sorgusu yapılmaz)."""
    from app.services.windows.winrm_client import WinRMClient

    candidates = db.query(Server).filter(Server.ai_ready == True).all()  # noqa: E712
    candidates = [s for s in candidates if is_windows_server(s)]
    servers = [s for s in candidates if _due_for_recheck(s.win_updates_last_checked)]
    if not servers:
        return {"checked": 0, "updated": 0}

    gcred: Optional[Dict] = None
    try:
        from app.api.windows import _get_global_winrm
        gcred = _get_global_winrm(db)
    except Exception:
        gcred = None

    script = """
$r = @{}
try {
    $session = New-Object -ComObject Microsoft.Update.Session
    $searcher = $session.CreateUpdateSearcher()
    $search = $searcher.Search("IsInstalled=0 and Type='Software'")
    $r.PendingCount = $search.Updates.Count
    $r.CriticalCount = ($search.Updates | Where-Object { $_.MsrcSeverity -eq 'Critical' }).Count
} catch {
    $r.PendingCount = -1
    $r.CriticalCount = -1
}
try {
    $r.RebootRequired = [bool](Test-Path 'HKLM:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\WindowsUpdate\\Auto Update\\RebootRequired')
} catch { $r.RebootRequired = $false }
try {
    $mp = Get-MpComputerStatus -ErrorAction Stop
    $r.DefenderEnabled = [bool]$mp.AntivirusEnabled
    $r.DefenderUpToDate = [bool]($mp.AntivirusSignatureAge -le 2)
} catch {
    $r.DefenderEnabled = $null
    $r.DefenderUpToDate = $null
}
$r | ConvertTo-Json -Compress
"""

    def _check_one(srv: Server) -> Optional[Dict]:
        # Thread pool içinde çalışır — SQLAlchemy session'a burada dokunulmaz.
        client = WinRMClient.from_server(srv)
        if not client and gcred and (srv.ip_address or srv.hostname):
            client = WinRMClient(
                host=srv.ip_address or srv.hostname,
                username=gcred["username"],
                password=gcred["password"],
                port=gcred.get("port", 5985),
                use_https=gcred.get("use_https", False),
            )
        if not client:
            return None
        try:
            r = client.run_ps(script)
            if not r.get("success") or not r.get("stdout", "").strip():
                return None
            return json.loads(r["stdout"].strip())
        except Exception as e:
            logger.debug("Windows update/defender toplama hatası (%s): %s", srv.name, e)
            return None

    results: Dict[int, Optional[Dict]] = {}
    with ThreadPoolExecutor(max_workers=bulk_ssh_workers(), thread_name_prefix="auto-winupd") as pool:
        futures = {pool.submit(_check_one, s): s for s in servers}
        for fut in as_completed(futures):
            srv = futures[fut]
            results[srv.id] = fut.result()

    updated = 0
    now = datetime.utcnow()
    for srv in servers:
        info = results.get(srv.id)
        srv.win_updates_last_checked = now  # başarısız denemeleri de işaretle — sürekli tekrar denemeyi önler
        if info:
            pending = info.get("PendingCount")
            if isinstance(pending, (int, float)) and pending >= 0:
                srv.win_updates_pending = int(pending)
            crit = info.get("CriticalCount")
            if isinstance(crit, (int, float)) and crit >= 0:
                srv.win_updates_critical = int(crit)
            srv.win_reboot_pending = bool(info.get("RebootRequired"))
            if info.get("DefenderEnabled") is not None:
                srv.win_defender_enabled = bool(info.get("DefenderEnabled"))
            if info.get("DefenderUpToDate") is not None:
                srv.win_defender_up_to_date = bool(info.get("DefenderUpToDate"))
            updated += 1
    db.commit()

    if updated:
        logger.info("Auto-onboarding: %s Windows sunucunun update/Defender durumu güncellendi", updated)

    return {"checked": len(servers), "updated": updated}


def collect_linux_security_audit(db: Session) -> Dict:
    """AI Ready Linux sunuculardan SSH ile firewall/SELinux durumu ve son 24 saatteki
    başarısız SSH giriş sayısını toplar. Linux güvenlik raporu bu cache'i okur."""
    candidates = (
        db.query(Server)
        .filter(
            Server.ai_ready == True,  # noqa: E712
            Server.ip_address.isnot(None),
            Server.ip_address != "",
        )
        .all()
    )
    candidates = [s for s in candidates if not is_windows_server(s)]
    servers = [s for s in candidates if _due_for_recheck(s.linux_security_last_check)]
    if not servers:
        return {"checked": 0, "updated": 0}

    def _audit_one(srv: Server) -> Optional[Dict]:
        # Thread pool içinde çalışır — SQLAlchemy session'a burada dokunulmaz.
        cfg = srv.connection_config or {}
        if not cfg.get("username"):
            return None
        ssh = SSHManager(
            host=srv.ip_address,
            username=cfg.get("username"),
            password=cfg.get("password"),
            private_key=cfg.get("private_key"),
            port=cfg.get("port", 22),
        )
        try:
            if not ssh.connect():
                return None
            _, fw_out, _ = ssh.execute_command(
                "systemctl is-active firewalld 2>/dev/null || systemctl is-active ufw 2>/dev/null || echo unknown"
            )
            _, se_out, _ = ssh.execute_command("getenforce 2>/dev/null || echo N/A")
            _, fail_out, _ = ssh.execute_command(
                "journalctl -u sshd --since '-24 hours' 2>/dev/null | grep -c 'Failed password'"
            )
            try:
                failed_logins = int((fail_out or "0").strip().splitlines()[0])
            except Exception:
                failed_logins = 0
            return {
                "firewall_active": (fw_out or "").strip() == "active",
                "selinux": (se_out or "N/A").strip() or "N/A",
                "failed_logins": failed_logins,
            }
        except Exception as e:
            logger.debug("Linux güvenlik denetimi hatası (%s): %s", srv.name, e)
            return None
        finally:
            ssh.close()

    results: Dict[int, Optional[Dict]] = {}
    with ThreadPoolExecutor(max_workers=bulk_ssh_workers(), thread_name_prefix="auto-secaudit") as pool:
        futures = {pool.submit(_audit_one, s): s for s in servers}
        for fut in as_completed(futures):
            srv = futures[fut]
            results[srv.id] = fut.result()

    updated = 0
    now = datetime.utcnow()
    for srv in servers:
        info = results.get(srv.id)
        if not info:
            continue
        srv.linux_firewall_active = info["firewall_active"]
        srv.linux_selinux_status = info["selinux"]
        srv.linux_failed_logins_24h = info["failed_logins"]
        srv.linux_security_last_check = now
        updated += 1
    db.commit()

    if updated:
        logger.info("Auto-onboarding: %s Linux sunucunun güvenlik denetimi güncellendi", updated)

    return {"checked": len(servers), "updated": updated}
