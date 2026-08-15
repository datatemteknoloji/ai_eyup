"""
AI Ready toplu tarama — önce ucuz TCP, sonra SSH.

Pubkey atlanmaz: SSH aşaması mevcut connect_ssh sırasını kullanır
(key varsa önce key, olmazsa şifre / KI). Global SSH timeout'larına dokunulmaz.
Ölçek: TCP fazı bulk_tcp_workers (varsayılan 100), SSH yalnız açık portlara
bulk_ssh_workers (varsayılan 25).
"""
from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable, Dict, List, Optional

from app.services.bulk_concurrency import bulk_ssh_workers, bulk_tcp_workers
from app.services.monitoring.server_health_checker import ServerHealthChecker

logger = logging.getLogger(__name__)

ProgressCb = Optional[Callable[[int, int, bool, str], None]]


def tcp_open(host: str, port: int = 22, timeout: Optional[float] = None) -> bool:
    ok, _reason = ServerHealthChecker.ping_server(host, port, timeout)
    return bool(ok)


def _ssh_one(snap: dict) -> bool:
    from app.services.ssh_manager import SSHManager

    ssh = SSHManager(
        host=snap["ip"],
        username=snap["username"],
        password=snap.get("password"),
        private_key=snap.get("private_key"),
        port=int(snap.get("port") or 22),
        sudo_password=snap.get("sudo_password"),
    )
    try:
        # Key varsa connect_ssh önce pubkey dener; şifre ikinci.
        return bool(ssh.connect())
    except Exception:
        return False
    finally:
        try:
            ssh.close()
        except Exception:
            pass


def probe_linux_snapshots(
    snapshots: List[dict],
    *,
    on_progress: ProgressCb = None,
) -> Dict[int, bool]:
    """
    snapshots: id, ip, username, password?, private_key?, port?
    Dönüş: {server_id: ssh_ok}
    """
    total = len(snapshots)
    results: Dict[int, bool] = {}
    if not total:
        return results

    tcp_n = bulk_tcp_workers()
    ssh_n = bulk_ssh_workers()
    reachable: List[dict] = []
    done = 0

    def _tcp(snap: dict):
        port = int(snap.get("port") or 22)
        return snap, tcp_open(snap["ip"], port)

    logger.info(
        "AI Ready TCP ön tarama: %s sunucu, tcp_workers=%s ssh_workers=%s",
        total, tcp_n, ssh_n,
    )
    with ThreadPoolExecutor(max_workers=tcp_n, thread_name_prefix="ai-ready-tcp") as pool:
        futs = [pool.submit(_tcp, s) for s in snapshots]
        for fut in as_completed(futs):
            snap, opened = fut.result()
            sid = snap["id"]
            if opened:
                reachable.append(snap)
            else:
                results[sid] = False
                done += 1
                if on_progress:
                    on_progress(done, total, False, f"TCP: {done}/{total}")

    logger.info(
        "AI Ready TCP bitti: %s/%s port açık, SSH deneniyor",
        len(reachable), total,
    )
    if not reachable:
        return results

    with ThreadPoolExecutor(max_workers=ssh_n, thread_name_prefix="ai-ready-ssh") as pool:
        futs = {pool.submit(_ssh_one, s): s["id"] for s in reachable}
        for fut in as_completed(futs):
            sid = futs[fut]
            try:
                ok = bool(fut.result())
            except Exception:
                ok = False
            results[sid] = ok
            done += 1
            if on_progress:
                on_progress(done, total, ok, f"SSH: {done}/{total}")

    logger.info(
        "AI Ready SSH bitti: %s denendi, %s başarılı",
        len(reachable),
        sum(1 for v in results.values() if v),
    )
    return results
