"""
Monitoring API endpoints
"""
import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from app.core.database import get_db
from app.core.config import settings
from app.models.server import Server
from app.services.monitoring.node_exporter_installer import NodeExporterInstaller
from app.services.monitoring.prometheus_target_manager import PrometheusTargetManager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/metrics/servers")
async def list_metric_servers(db: Session = Depends(get_db)):
    """
    Metrik kurulu sunucuların özeti — DB + Prometheus senkron.
    Canlı Metrikler ekranı bu listeyi kullanır.
    """
    from app.services.monitoring.prometheus_metrics import (
        get_node_exporter_up_map,
        sync_node_exporter_running_from_prometheus,
    )

    sync_stats = sync_node_exporter_running_from_prometheus(db)
    up_map = get_node_exporter_up_map()

    servers = db.query(Server).filter(
        Server.ip_address.isnot(None),
        Server.ip_address != "",
        Server.node_exporter_installed == True,  # noqa: E712
    ).order_by(Server.name).all()

    rows = []
    scrape_error_count = 0

    for s in servers:
        instance = f"{s.ip_address.strip()}:9100"
        live = up_map.get(instance) == "1"
        if (s.status or "").upper() == "ONLINE" and s.node_exporter_installed and not live:
            scrape_error_count += 1

        rows.append({
            "id": s.id,
            "name": s.name,
            "ip_address": s.ip_address,
            "status": s.status,
            "instance": instance,
            "live": live,
            "installed": bool(s.node_exporter_installed),
            "running_db": bool(s.node_exporter_running),
        })

    online_installed = [r for r in rows if (r["status"] or "").upper() == "ONLINE"]

    return {
        "total_installed": len(rows),
        "total_online_installed": len(online_installed),
        "total_live": sync_stats.get("live", 0),
        "total_live_servers": sum(1 for r in rows if r["live"] and (r["status"] or "").upper() == "ONLINE"),
        "scrape_errors": scrape_error_count,
        "sync": sync_stats,
        "servers": rows,
    }


@router.post("/node-exporter/bulk-install")
async def bulk_install_node_exporter(
    server_ids: Optional[List[int]] = None,
    db: Session = Depends(get_db),
):
    """
    Birden fazla sunucuya paralel Node Exporter kurulumu.
    server_ids boşsa: node_exporter_running=False olan tüm ONLINE AI-Ready sunucular.
    """
    import asyncio
    from concurrent.futures import ThreadPoolExecutor

    if server_ids:
        servers = db.query(Server).filter(Server.id.in_(server_ids)).all()
    else:
        # node exporter çalışmayan, ONLINE, AI-Ready sunucular
        servers = db.query(Server).filter(
            Server.status == "ONLINE",
            Server.ai_ready == True,
            Server.node_exporter_running == False,
        ).all()

    if not servers:
        return {"queued": 0, "message": "Uygun sunucu bulunamadı"}

    results = {}

    def _install_one(srv):
        try:
            installer = NodeExporterInstaller(srv, db)
            res = installer.install()
            # DB'yi güncelle
            srv.node_exporter_installed = res.get("success", False)
            srv.node_exporter_running   = res.get("success", False)
            db.commit()
            return srv.id, {"success": res.get("success", False), "message": res.get("message", "")}
        except Exception as e:
            return srv.id, {"success": False, "message": str(e)}

    with ThreadPoolExecutor(max_workers=8, thread_name_prefix="bulk-ne") as pool:
        from concurrent.futures import as_completed
        futures = {pool.submit(_install_one, s): s for s in servers}
        for f in as_completed(futures):
            srv_id, result = f.result()
            results[str(srv_id)] = result

    success = sum(1 for r in results.values() if r["success"])
    failed  = len(results) - success
    logger.info(f"Bulk Node Exporter: {success} başarılı, {failed} başarısız")
    return {
        "queued":   len(servers),
        "success":  success,
        "failed":   failed,
        "results":  results,
    }


@router.post("/node-exporter/install/{server_id}")
async def install_node_exporter(server_id: int, db: Session = Depends(get_db)):
    """SSH erişimi olan sunucuya Node Exporter kur - ai_ready zorunlu degil"""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # Global default credential'i al
    from app.models.credential import GlobalCredential
    global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
    if not global_cred:
        global_cred = db.query(GlobalCredential).first()

    # Kullanilacak credential: global varsa global, yoksa sunucunun kendi'si
    if global_cred:
        original_config = server.connection_config or {}
        server.connection_config = {
            "username": global_cred.username,
            "password": global_cred.password,
            "private_key": global_cred.private_key,
            "sudo_password": global_cred.sudo_password or global_cred.password,
            "port": global_cred.port or 22,
        }
    elif not server.connection_config or not server.connection_config.get("username"):
        raise HTTPException(status_code=400, detail="Global credential veya sunucu SSH bilgisi gerekli")
    
    try:
        installer = NodeExporterInstaller(server)
        result = installer.install()
        
        # Kurulum başarılıysa Prometheus'a target ekle
        if result.get("success"):
            server.node_exporter_installed = True
            server.node_exporter_running = result.get("running", True)
            db.commit()

            from app.services.monitoring.prometheus_metrics import sync_node_exporter_targets_from_db
            prom_stats = sync_node_exporter_targets_from_db(db)
            instance = f"{server.ip_address}:9100"
            result["prometheus_target_added"] = prom_stats.get("targets_after", 0) >= prom_stats.get("targets_before", 0)
            result["prometheus_instance"] = instance
            result["prometheus_sync"] = prom_stats
            steps = result.get("steps", [])
            steps.append({
                "id": "prometheus",
                "label": "Prometheus hedefi senkron",
                "status": "success",
                "message": f"{prom_stats.get('targets_after')} hedef ({instance})",
            })
            result["steps"] = steps
        
        # Bağlantıyı kapat
        installer.connector.close()
        
        return result
        
    except Exception as e:
        logger.error(f"Node Exporter kurulum hatası (Server ID: {server_id}): {e}", exc_info=True)
        # Frontend'de adımların görünmesi için steps varsa 200 ile dön (success: false)
        if isinstance(e, HTTPException):
            raise
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/node-exporter/start/{server_id}")
async def start_node_exporter(server_id: int, db: Session = Depends(get_db)):
    """Kurulu ama durmus Node Exporter'i basla - server veya global credential kullanir"""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    # Credential: once server'in kendisi, yoksa/basarisizsa global default
    from app.services.ssh_manager import SSHManager
    from app.models.credential import GlobalCredential
    from datetime import datetime
    
    def try_start(username, password, private_key=None, port=22, sudo_password=None):
        ssh = SSHManager(
            host=server.ip_address or server.hostname,
            username=username, password=password,
            private_key=private_key, port=port,
            sudo_password=sudo_password or password
        )
        if not ssh.connect():
            return False, "SSH baglantisi kurulamadi"
        try:
            # Zaten çalışıyor mu kontrol et
            _, pgrep_out, _ = ssh.execute_command("pgrep -f node_exporter 2>/dev/null | head -1")
            if pgrep_out.strip():
                # Çalışıyor - crontab ile kalıcı yap (yoksa)
                _, which_out2, _ = ssh.execute_command(
                    "which node_exporter 2>/dev/null || find $HOME -name node_exporter 2>/dev/null | head -1"
                )
                bin_path = which_out2.strip() or f"/home/{username}/bin/node_exporter"
                nohup_entry = f"nohup {bin_path} --web.listen-address=0.0.0.0:9100 > /tmp/node_exporter.log 2>&1 &"
                _, cron_out, _ = ssh.execute_command("crontab -l 2>/dev/null")
                if "node_exporter" not in cron_out:
                    ssh.execute_command(
                        f"(crontab -l 2>/dev/null | grep -v node_exporter; "
                        f"echo '@reboot sleep 10 && {nohup_entry}') | crontab -"
                    )
                return True, "already_running"

            # Binary yolunu bul
            _, which_out, _ = ssh.execute_command(
                "which node_exporter 2>/dev/null || find $HOME -name node_exporter 2>/dev/null | head -1"
            )
            install_path = which_out.strip() or f"/home/{username}/bin/node_exporter"

            # 1. Systemd user service (sudo gerektirmez) - D-Bus varsa
            success, stdout, stderr = ssh.execute_command(
                f"loginctl enable-linger {username} 2>/dev/null; "
                "systemctl --user daemon-reload 2>/dev/null; "
                "systemctl --user start node_exporter 2>/dev/null"
            )
            combined = (stdout + stderr).lower()
            if success or ("active" in combined and "d-bus" not in combined and "no such file" not in combined):
                return True, ""

            # 2. Sudosuz sistem servisi
            success, stdout, stderr = ssh.execute_command("systemctl start node_exporter")
            if success or "already active" in (stdout + stderr).lower():
                return True, ""

            # 3. Sudo ile
            success, stdout, stderr = ssh.execute_command("systemctl start node_exporter", use_sudo=True)
            if success or "already active" in (stdout + stderr).lower():
                return True, ""

            # 4. Nohup + crontab (sudo yok, kalici)
            nohup_cmd = f"nohup {install_path} --web.listen-address=0.0.0.0:9100 > /tmp/node_exporter.log 2>&1 &"
            _, p_out, _ = ssh.execute_command(
                f"pkill -f node_exporter 2>/dev/null; sleep 1; {nohup_cmd}; sleep 2; pgrep -f node_exporter && echo started"
            )
            if "started" in p_out.lower():
                # Crontab ile kalici yap
                ssh.execute_command(
                    f"(crontab -l 2>/dev/null | grep -v node_exporter; "
                    f"echo '@reboot {nohup_cmd}') | crontab -"
                )
                return True, "nohup+crontab"

            return False, (stderr or stdout).strip()
        finally:
            ssh.close()
    
    last_error = "Bilinmeyen hata"
    
    # 1. Global default credential'i once dene (en yetkili kullanici)
    global_cred = db.query(GlobalCredential).filter(GlobalCredential.is_default == True).first()
    if not global_cred:
        global_cred = db.query(GlobalCredential).first()
    if global_cred:
        ok, last_error = try_start(
            username=global_cred.username,
            password=global_cred.password,
            private_key=global_cred.private_key,
            port=global_cred.port or 22,
            sudo_password=global_cred.sudo_password or global_cred.password
        )
        if ok:
            server.node_exporter_running = True
            server.node_exporter_last_check = datetime.utcnow()
            db.commit()
            return {"success": True, "message": "Node Exporter baslatildi", "server": server.name}
    
    # 2. Fallback: server'in kendi credential'i
    conn = server.connection_config or {}
    if conn.get("username"):
        ok, last_error = try_start(
            username=conn.get("username"),
            password=conn.get("password"),
            private_key=conn.get("private_key"),
            port=conn.get("port", 22),
            sudo_password=conn.get("sudo_password") or conn.get("password")
        )
        if ok:
            server.node_exporter_running = True
            server.node_exporter_last_check = datetime.utcnow()
            db.commit()
            return {"success": True, "message": "Node Exporter baslatildi", "server": server.name}
    
    raise HTTPException(status_code=500, detail=f"Baslatma basarisiz: {last_error}")

@router.post("/node-exporter/uninstall/{server_id}")
async def uninstall_node_exporter(server_id: int, db: Session = Depends(get_db)):
    """Sunucudan Node Exporter kaldır ve Prometheus'tan çıkar"""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")
    
    if not server.connection_config or not server.connection_config.get("username"):
        raise HTTPException(status_code=400, detail="Server must have SSH credentials to uninstall Node Exporter")
    
    try:
        installer = NodeExporterInstaller(server)
        result = installer.uninstall()
        
        # Prometheus hedeflerini DB ile senkronize et
        if result.get("success"):
            server.node_exporter_installed = False
            server.node_exporter_running = False
            db.commit()

            from app.services.monitoring.prometheus_metrics import sync_node_exporter_targets_from_db
            prom_stats = sync_node_exporter_targets_from_db(db)
            result["prometheus_target_removed"] = prom_stats.get("removed_orphans", 0) > 0 or prom_stats.get("targets_after", 0) < prom_stats.get("targets_before", 0)
            result["prometheus_sync"] = prom_stats
        
        # Bağlantıyı kapat
        installer.connector.close()
        
        return result
        
    except Exception as e:
        logger.error(f"Node Exporter kaldırma hatası (Server ID: {server_id}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Kaldırma hatası: {str(e)}")

@router.get("/node-exporter/download/{arch}")
async def download_node_exporter_binary(arch: str):
    """Node Exporter binary'sini backend sunucusundan indir"""
    from fastapi.responses import FileResponse
    from pathlib import Path
    from app.core.config import settings
    
    try:
        # Binary dosya yolu
        storage_path = Path(settings.NODE_EXPORTER_STORAGE_PATH)
        arch_dir = storage_path / arch
        binary_file = arch_dir / "node_exporter"
        
        # Binary var mı kontrol et
        if not binary_file.exists():
            # Genel binary'yi dene
            general_binary = storage_path / "node_exporter"
            if general_binary.exists():
                binary_file = general_binary
            else:
                raise HTTPException(status_code=404, detail=f"Node Exporter binary bulunamadı (arch: {arch})")
        
        # Binary'yi servis et
        return FileResponse(
            path=str(binary_file.absolute()),
            filename=f"node_exporter-{arch}",
            media_type="application/octet-stream"
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Binary download hatası (arch: {arch}): {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Binary indirme hatası: {str(e)}")

@router.get("/node-exporter/list-ai-ready")
async def list_ai_ready_servers(db: Session = Depends(get_db)):
    """AI Ready sunucuları listele - DB cache okur, SSH yapmaz"""
    try:
        servers = db.query(Server).filter(
            Server.ai_ready == True,
            Server.connection_config.isnot(None)
        ).all()
        
        result = []
        for server in servers:
            conn_config = server.connection_config or {}
            username = conn_config.get("username", "")
            
            if username and server.ip_address:
                # SSH yapmak yerine DB cache oku (background task günceller)
                installed = bool(getattr(server, "node_exporter_installed", False))
                running = bool(getattr(server, "node_exporter_running", False))
                
                # Cache yoksa Prometheus'tan hızlı kontrol (SSH yok)
                if not installed:
                    from app.services.monitoring.prometheus_metrics import node_exporter_up_for_server
                    try:
                        if node_exporter_up_for_server(server.ip_address, server.hostname):
                            installed = True
                            running = True
                    except Exception as e:
                        logger.warning(f"Operation failed: {e}")
                
                result.append({
                    "id": server.id,
                    "name": server.name,
                    "ip_address": server.ip_address,
                    "hostname": server.hostname,
                    "os_type": server.os_type,
                    "username": username,
                    "port": conn_config.get("port", 22),
                    "node_exporter": {
                        "installed": installed,
                        "running": running
                    }
                })
        
        return {
            "total": len(result),
            "servers": result
        }
        
    except Exception as e:
        logger.error(f"AI Ready sunucular listesi hatası: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Liste hatası: {str(e)}")

def _prometheus_node_exporter_up(server_ip: Optional[str], hostname: Optional[str]) -> bool:
    """Prometheus'tan bu sunucuda node-exporter'ın up olup olmadığını kontrol et"""
    if not server_ip and not hostname:
        return False
    try:
        with httpx.Client(timeout=5.0) as client:
            resp = client.get(
                f"{settings.PROMETHEUS_URL}/api/v1/query",
                params={"query": 'up{job="node-exporter"}'}
            )
            if resp.status_code != 200:
                return False
            data = resp.json()
            if data.get("status") != "success":
                return False
            for r in data.get("data", {}).get("result", []):
                instance = (r.get("metric") or {}).get("instance", "")
                value = r.get("value")
                if value is None or len(value) < 2:
                    continue
                if str(value[1]) != "1":
                    continue
                if server_ip and (instance == f"{server_ip}:9100" or instance.startswith(server_ip + ":")):
                    return True
                if hostname and (instance.startswith(hostname) or hostname in instance):
                    return True
    except Exception as e:
        logger.debug(f"Prometheus fallback hatası: {e}")
    return False


@router.get("/node-exporter/status/{server_id}")
async def check_node_exporter_status(server_id: int, db: Session = Depends(get_db)):
    """Node Exporter durumunu kontrol et - DB cache + Prometheus, SSH yapmaz"""
    server = db.query(Server).filter(Server.id == server_id).first()
    if not server:
        raise HTTPException(status_code=404, detail="Server not found")

    # DB'den taze oku (cache bypass)
    db.expire(server)
    db.refresh(server)

    installed = bool(server.node_exporter_installed) if server.node_exporter_installed is not None else False
    running = bool(server.node_exporter_running) if server.node_exporter_running is not None else False

    # DB'de kayıt yoksa Prometheus'tan kontrol et ve DB'ye yaz
    if not installed and (server.ip_address or server.hostname):
        if _prometheus_node_exporter_up(server.ip_address, server.hostname):
            installed = True
            running = True
            from datetime import datetime
            server.node_exporter_installed = True
            server.node_exporter_running = True
            server.node_exporter_last_check = datetime.utcnow()
            try:
                db.commit()
            except Exception:
                db.rollback()

    return {
        "server_id": server_id,
        "server_name": server.name,
        "server_ip": server.ip_address,
        "installed": installed,
        "running": running
    }

@router.post("/prometheus/sync-targets")
async def sync_prometheus_targets(db: Session = Depends(get_db)):
    """DB'deki kurulu sunuculara göre Prometheus hedef dosyasını yeniden oluşturur."""
    from app.services.monitoring.prometheus_metrics import sync_node_exporter_targets_from_db
    try:
        stats = sync_node_exporter_targets_from_db(db)
        return {"success": True, **stats}
    except Exception as e:
        logger.error(f"Prometheus target sync hatası: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/prometheus/sync-ai-ready-targets")
async def sync_ai_ready_targets(db: Session = Depends(get_db)):
    """AI Ready sunucuları Prometheus target dosyasına ekle/güncelle"""
    try:
        # AI Ready ve ONLINE sunucuları bul
        servers = db.query(Server).filter(
            Server.ai_ready == True,
            Server.status == "ONLINE",
            Server.ip_address.isnot(None),
            Server.connection_config.isnot(None)
        ).all()
        
        target_manager = PrometheusTargetManager()
        
        # Mevcut target'ları yükle
        all_targets = target_manager.load_targets()
        existing_instances = {t.get("targets", [])[0]: t for t in all_targets if t.get("targets")}
        
        added_count = 0
        updated_count = 0
        skipped_count = 0
        errors = []
        
        # AI Ready sunucular için target'ları oluştur
        new_targets = []
        for server in servers:
            if not server.ip_address:
                skipped_count += 1
                continue
            
            instance = f"{server.ip_address}:9100"
            
            # Node Exporter kurulu mu kontrol et (ZORUNLU - sadece kurulu olanlar eklenir)
            try:
                installer = NodeExporterInstaller(server)
                status = installer.check_status()
                installer.connector.close()
                
                # Node Exporter kurulu değilse kesinlikle atla
                if not status.get("installed", False):
                    skipped_count += 1
                    logger.info(f"Server {server.name} ({server.ip_address}) Node Exporter kurulu değil, atlanıyor (AI Ready ama Node Exporter yok)")
                    continue
            except Exception as e:
                # Hata durumunda da ekleme (Node Exporter kurulu değil demektir)
                skipped_count += 1
                logger.warning(f"Server {server.name} ({server.ip_address}) Node Exporter durum kontrolü hatası: {e} - Atlanıyor")
                continue
            
            # Target oluştur
            labels = {
                "server_id": str(server.id),
                "server_name": server.name,
                "job": "node-exporter"
            }
            
            if instance in existing_instances:
                # Mevcut target'ı güncelle
                existing_instances[instance]["labels"] = labels
                updated_count += 1
            else:
                # Yeni target ekle
                new_target = {
                    "targets": [instance],
                    "labels": labels
                }
                new_targets.append(new_target)
                added_count += 1
        
        # Tüm target'ları birleştir ve kaydet
        if added_count > 0 or updated_count > 0:
            # Mevcut target'ları güncelle
            final_targets = list(existing_instances.values()) + new_targets
            target_manager.save_targets(final_targets)
            
            # Prometheus'u reload et
            try:
                await target_manager.reload_prometheus_async()
            except Exception as e:
                try:
                    target_manager.reload_prometheus_sync()
                except Exception as e:
                    logger.warning(f"Operation failed: {e}")
        
        return {
            "success": True,
            "message": "AI Ready sunucular Prometheus target dosyasına eklendi",
            "added": added_count,
            "updated": updated_count,
            "skipped": skipped_count,
            "total_ai_ready": len(servers),
            "errors": errors if errors else None
        }
        
    except Exception as e:
        logger.error(f"AI Ready target sync hatası: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Sync hatası: {str(e)}")
