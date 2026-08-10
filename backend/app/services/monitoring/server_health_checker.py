"""
Server Health Checker - Sunucu durumlarını otomatik kontrol eder.
3000–4000 sunucu ölçeği için paralel TCP/SSH/WinRM kontrolü kullanır.
"""
import asyncio
import logging
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.server import Server
from app.services.bulk_concurrency import bulk_tcp_workers

logger = logging.getLogger(__name__)


class ServerHealthChecker:
    """Sunucu sağlık durumunu kontrol eden servis"""

    @staticmethod
    def ping_server(ip_address: str, port: int = 22, timeout: float = None) -> Tuple[bool, str]:
        """TCP bağlantı dener; (başarılı_mı, hata_açıklaması) döner."""
        if timeout is None:
            try:
                from app.services.runtime_settings import get_float
                timeout = float(get_float("health_tcp_timeout_sec"))
            except Exception:
                timeout = 2.0
        try:
            with socket.create_connection((ip_address, port), timeout=timeout):
                return True, ""
        except socket.timeout:
            return False, "timeout"
        except ConnectionRefusedError:
            return False, "connection_refused"
        except OSError as e:
            err = "no_route" if getattr(e, "errno", None) in (113, 101, 111) else str(e)
            return False, err
        except Exception as e:
            return False, str(e)[:80]

    @staticmethod
    def check_server_status(
        server: Any,
        db: Session = None,
        winrm_global: Optional[dict] = None,
        *,
        deep: bool = False,
    ) -> Tuple[str, str]:
        """(status, sebep) döner. Sebep sadece OFFLINE/WARNING için dolu.

        deep=False (varsayılan, periyodik tarama): yalnızca TCP port kontrolü.
        Credential'lı tam SSH/WinRM her 5 dk'da yüzlerce sunucuya auth denemesi
        yapıyordu — ağ gürültüsü ve log spam üretir. Tam auth yalnızca deep=True
        (manuel tek sunucu kontrolü) veya AI Ready güncellemede yapılır.
        """
        if not (getattr(server, "ip_address", None) or "").strip():
            current = (getattr(server, "status", None) or "UNKNOWN").upper()
            return current, "ip_yok"

        from app.services.platform_scope import is_windows_server
        if is_windows_server(server):
            return ServerHealthChecker._check_windows_status(
                server, db, winrm_global=winrm_global, deep=deep
            )

        port = 22
        try:
            cfg = getattr(server, "connection_config", None)
            if cfg and isinstance(cfg, dict):
                port = int(cfg.get("port", 22) or 22)
        except Exception:
            port = 22

        is_reachable, ping_reason = ServerHealthChecker.ping_server(server.ip_address, port=port)

        if not is_reachable:
            return "OFFLINE", f"tcp_{port}_ulasilamiyor:{ping_reason}"

        if not deep:
            return "ONLINE", ""

        cfg = getattr(server, "connection_config", None) or {}
        if cfg.get("username"):
            try:
                from app.services.monitoring.server_connector import ServerConnector
                connector = ServerConnector(server)
                test_result = connector.test_connection()
                connector.close()
                if test_result.get("success"):
                    return "ONLINE", ""
                return "WARNING", "ssh_baglanamadi"
            except Exception as e:
                return "WARNING", f"ssh_hata:{str(e)[:50]}"

        return "ONLINE", ""

    @staticmethod
    def _has_windows_cred(server: Any, winrm_global: Optional[dict] = None) -> bool:
        """Per-server veya global WinRM credential var mı?"""
        cfg = getattr(server, "connection_config", None) or {}
        if cfg.get("username") and (cfg.get("password") or cfg.get("winrm")):
            # Kendi credential'ı tanımlanmış (apply sonrası winrm=True + username)
            if cfg.get("winrm") or cfg.get("protocol") == "winrm" or cfg.get("winrm_port"):
                return True
            # Windows olarak işaretli ve username+password varsa WinRM say
            if cfg.get("password") and cfg.get("username"):
                return True
        if winrm_global and winrm_global.get("username") and winrm_global.get("password"):
            return True
        return False

    @staticmethod
    def _check_windows_status(
        server: Any,
        db: Session = None,
        winrm_global: Optional[dict] = None,
        *,
        deep: bool = False,
    ) -> Tuple[str, str]:
        """Windows sağlık kontrolü.

        Global/per-server WinRM credential yoksa hiçbir bağlantı denemesi yapılmaz
        (TCP 5985 dahil) — envanterdeki Windows VM'ler boşa taranmaz.
        """
        if not ServerHealthChecker._has_windows_cred(server, winrm_global):
            # Credential yok → dokunma, mevcut durumu koru
            current = (getattr(server, "status", None) or "UNKNOWN").upper()
            if current in ("", "UNKNOWN"):
                return "UNKNOWN", "winrm_cred_yok"
            return current, "winrm_cred_yok"

        cfg = getattr(server, "connection_config", None) or {}
        try:
            port = int(cfg.get("winrm_port") or (winrm_global or {}).get("port") or 5985)
        except Exception:
            port = 5985

        is_reachable, ping_reason = ServerHealthChecker.ping_server(server.ip_address, port=port)
        if not is_reachable:
            return "OFFLINE", f"tcp_{port}_ulasilamiyor:{ping_reason}"

        if not deep:
            return "ONLINE", ""

        try:
            from app.services.windows.winrm_client import WinRMClient
            client = WinRMClient.from_server(server)
            if client is None:
                gcred = winrm_global
                if gcred is None and db is not None:
                    from app.api.windows import _get_global_winrm
                    gcred = _get_global_winrm(db)
                if gcred:
                    host = (server.ip_address or getattr(server, "hostname", None) or "").strip()
                    client = WinRMClient(
                        host=host,
                        username=gcred.get("username"),
                        password=gcred.get("password"),
                        port=int(gcred.get("port") or 5985),
                        use_https=bool(gcred.get("use_https")),
                    )
            if client is None:
                return "UNKNOWN", "winrm_cred_yok"

            result = client.test_connection()
            if result.get("connected"):
                return "ONLINE", ""
            return "WARNING", "winrm_baglanamadi"
        except Exception as e:
            return "WARNING", f"winrm_hata:{str(e)[:50]}"

    @staticmethod
    def _sync_ai_ready(server: Server, status: str, reason: str) -> bool:
        """SSH/WinRM erişilemeyen sunucularda ai_ready bayrağını temizle.
        Credential tanımlı değilse (henüz yapılandırılmamış) bayrağa dokunma.
        """
        if reason in ("winrm_cred_yok", "ip_yok"):
            return False
        if not server.ai_ready:
            return False
        if status == "OFFLINE":
            server.ai_ready = False
            return True
        if status == "WARNING" and reason.startswith(("ssh_", "winrm_")):
            server.ai_ready = False
            return True
        return False

    @staticmethod
    def update_server_statuses(
        db: Session,
        on_progress=None,
        cancel_check=None,
    ) -> Dict[str, int]:
        """Tüm sunucuların durumlarını paralel kontrol et ve güncelle.

        on_progress(done, total) — opsiyonel UI ilerleme callback'i.
        cancel_check() — True dönerse kalan işler iptal edilir (partial stats döner).
        """
        try:
            servers = db.query(Server).all()
            stats = {
                "checked": 0,
                "updated": 0,
                "online": 0,
                "offline": 0,
                "warning": 0,
                "ai_ready_cleared": 0,
                "workers": 0,
                "cancelled": False,
                "total": 0,
            }
            if not servers:
                return stats

            winrm_global = None
            try:
                from app.api.windows import _get_global_winrm
                winrm_global = _get_global_winrm(db)
            except Exception:
                winrm_global = None

            snapshots = []
            from app.core.encryption import decrypt_secret
            from app.services.platform_scope import is_windows_server
            skipped_win_no_cred = 0
            for s in servers:
                # Windows + hiç WinRM credential yok → hiçbir TCP denemesi yapma
                if is_windows_server(s) and not ServerHealthChecker._has_windows_cred(s, winrm_global):
                    skipped_win_no_cred += 1
                    continue
                cfg = dict(s.connection_config or {})
                # Worker thread'lerde SSH için düz metin kimlik bilgisi
                if cfg.get("password"):
                    try:
                        cfg["password"] = decrypt_secret(cfg.get("password"))
                    except Exception:
                        pass
                if cfg.get("private_key"):
                    try:
                        cfg["private_key"] = decrypt_secret(cfg.get("private_key"))
                    except Exception:
                        pass
                if cfg.get("sudo_password"):
                    try:
                        cfg["sudo_password"] = decrypt_secret(cfg.get("sudo_password"))
                    except Exception:
                        pass
                snapshots.append({
                    "id": s.id,
                    "name": s.name,
                    "hostname": s.hostname,
                    "ip_address": s.ip_address,
                    "status": s.status,
                    "os_type": s.os_type,
                    "connection_config": cfg,
                    "ai_ready": bool(s.ai_ready),
                })

            workers = bulk_tcp_workers()
            stats["workers"] = workers
            stats["total"] = len(snapshots)
            if skipped_win_no_cred:
                logger.info(
                    "Health check: %s Windows atlandı (WinRM credential yok)",
                    skipped_win_no_cred,
                )
            logger.info("Health check: %s sunucu, workers=%s", len(snapshots), workers)
            if on_progress:
                try:
                    on_progress(0, len(snapshots))
                except Exception:
                    pass

            def _one(snap: dict) -> Tuple[int, str, str, str, bool]:
                ns = SimpleNamespace(**snap)
                new_status, reason = ServerHealthChecker.check_server_status(
                    ns, db=None, winrm_global=winrm_global
                )
                return snap["id"], snap["status"] or "", new_status, reason, snap["ai_ready"]

            results: List[Tuple[int, str, str, str, bool]] = []
            done = 0
            cancelled = False
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="health-check") as pool:
                futures = [pool.submit(_one, snap) for snap in snapshots]
                pending = set(futures)
                for fut in as_completed(futures):
                    pending.discard(fut)
                    try:
                        results.append(fut.result())
                    except Exception as exc:
                        logger.debug("Health check future error: %s", exc)
                        continue
                    done += 1
                    # Erken ve sık tick — UI 0/N'de uzun süre kalmasın
                    if on_progress and (
                        done <= 3 or done % 5 == 0 or done == len(snapshots)
                    ):
                        try:
                            on_progress(done, len(snapshots))
                        except Exception:
                            pass
                    if done % 200 == 0 or done == len(snapshots):
                        logger.info("Health check ilerlemesi %s/%s", done, len(snapshots))
                    if cancel_check and cancel_check():
                        cancelled = True
                        stats["cancelled"] = True
                        for p in pending:
                            p.cancel()
                        logger.info(
                            "Health check iptal edildi (%s/%s tamamlandı)",
                            done,
                            len(snapshots),
                        )
                        break

            by_id = {s.id: s for s in servers}
            for srv_id, old_status, new_status, reason, _prev_ai in results:
                stats["checked"] += 1
                server = by_id.get(srv_id)
                if not server:
                    continue

                if ServerHealthChecker._sync_ai_ready(server, new_status, reason):
                    stats["ai_ready_cleared"] += 1
                    stats["updated"] += 1
                    logger.info(
                        "Server %s: ai_ready cleared (%s, %s)",
                        server.name, new_status, reason,
                    )

                old_u = (old_status or "").upper()
                new_u = (new_status or "").upper()
                status_changed = old_u != new_u

                if status_changed:
                    server.status = new_status
                    stats["updated"] += 1
                    logger.info(
                        "Server %s (%s) status: %s -> %s",
                        server.name, server.ip_address, old_status, new_status,
                    )

                if new_status == "ONLINE":
                    stats["online"] += 1
                elif new_status == "OFFLINE":
                    stats["offline"] += 1
                    # Zaten OFFLINE olanları her turda WARNING spam'leme
                    if status_changed or not old_u:
                        logger.warning(
                            "OFFLINE: %s (%s) sebep: %s",
                            server.name, server.ip_address or "—", reason or "bilinmiyor",
                        )
                    else:
                        logger.debug(
                            "OFFLINE (devam): %s (%s) sebep: %s",
                            server.name, server.ip_address or "—", reason,
                        )
                elif new_status == "WARNING":
                    stats["warning"] += 1
                    if status_changed:
                        logger.warning(
                            "WARNING: %s (%s) sebep: %s",
                            server.name, server.ip_address, reason,
                        )

            db.commit()
            return stats

        except Exception as e:
            logger.error("Server status update failed: %s", e, exc_info=True)
            db.rollback()
            return {"error": str(e)}

    @staticmethod
    async def update_server_statuses_async(db: Session, on_progress=None) -> Dict[str, int]:
        """Async wrapper for status update"""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(
            None,
            lambda: ServerHealthChecker.update_server_statuses(db, on_progress=on_progress),
        )
