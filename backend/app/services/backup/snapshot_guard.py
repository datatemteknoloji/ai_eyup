"""vmw.snapshot_remove ön kontrolü (Madde 14 / Dilim C).

- backup capability varsa: ilgili VM'de aktif bk_sessions → blokla.
- Veeam yoksa: yedek isim kalıbına uyan snapshot'lar ve yapılandırılabilir
  yedek penceresi içindeki işlemler bloklanır.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence

from sqlalchemy.orm import Session

from app.services.capabilities import get_capabilities

# Yaygın Veeam / yedek snapshot ad kalıpları (Veeam'siz ortamda "inceleme" koruması)
_BACKUP_NAME_RX = re.compile(
    r"(veeam|vbr|backup|vbr-|replica|_replica|VEEAM|Veeam|VeeamONE|Veeam.Guest)",
    re.I,
)


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def backup_window_active(db: Session, *, now: Optional[datetime] = None) -> bool:
    """Ayarlar: backup_window_hours = \"22-06\" (yerel sunucu saati, 24h). Boşsa kapalı."""
    try:
        from app.models.app_settings import AppSettings
        row = db.query(AppSettings).filter(AppSettings.key == "backup_window_hours").first()
        raw = (row.value if row else "") or ""
    except Exception:  # noqa: BLE001
        raw = ""
    raw = str(raw).strip()
    if not raw or "-" not in raw:
        return False
    try:
        a, b = raw.split("-", 1)
        start, end = int(a.strip()), int(b.strip())
    except ValueError:
        return False
    hour = (now or _utcnow()).astimezone().hour
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def snapshot_looks_like_backup(name: Any) -> bool:
    return bool(_BACKUP_NAME_RX.search(str(name or "")))


def _active_backup_sessions_for_vm(db: Session, *, vm_name: str, matched_vm_id: Optional[int]) -> int:
    """VM'i koruyan işlerin bitmemiş (son 24 saatte başlamış) oturum sayısı — capability varken.

    İş↔VM bağı: BkProtectedObject.job_provider_id (restorePoint.backupId → backups.jobId).
    Bağ kurulamayan VM için 0 döner (yanlış engel yerine isim kalıbı koruması devrede kalır).
    """
    try:
        from datetime import timedelta
        from app.models.backup import BkJob, BkProtectedObject, BkSession
        from app.services.backup.demo_gate import active_instances
        # yalnız gerçek sağlayıcılar: DB'de kalmış demo/devre dışı satırlar gerçek snapshot kararını etkilemez (F.0)
        real_ids = [i.id for i in active_instances(db)]
        objs = db.query(BkProtectedObject).filter(BkProtectedObject.instance_id.in_(real_ids or [-1]))
        if matched_vm_id:
            objs = objs.filter(BkProtectedObject.matched_vm_id == matched_vm_id)
        else:
            objs = objs.filter(BkProtectedObject.name.ilike(vm_name))
        pairs = {(o.instance_id, o.job_provider_id) for o in objs.limit(50).all() if o.job_provider_id}
        if not pairs:
            return 0
        since = _utcnow() - timedelta(hours=24)
        n = 0
        for iid, pjid in pairs:
            job = db.query(BkJob).filter(BkJob.instance_id == iid, BkJob.provider_job_id == pjid).first()
            if job is None:
                continue
            n += (db.query(BkSession)
                  .filter(BkSession.job_id == job.id, BkSession.ended_at.is_(None), BkSession.started_at >= since)
                  .count())
        return n
    except Exception:  # noqa: BLE001
        return 0


def check_snapshot_remove(
    db: Session,
    *,
    snapshots: Sequence[Dict[str, Any]],
    vm_name: str,
    matched_vm_id: Optional[int] = None,
) -> Dict[str, Any]:
    """Bloklanacaksa ok=False ve neden; aksi halde ok=True."""
    caps = get_capabilities()
    has_backup = "backup" in caps
    blocked: List[str] = []

    if has_backup:
        n = _active_backup_sessions_for_vm(db, vm_name=vm_name, matched_vm_id=matched_vm_id)
        if n:
            return {
                "ok": False,
                "error": f"Aktif yedek oturumu varken snapshot silinemez ({n} session).",
                "reason": "active_backup_session",
            }

    for s in snapshots:
        name = s.get("name")
        if snapshot_looks_like_backup(name):
            if has_backup:
                blocked.append(str(name))
            else:
                blocked.append(str(name))

    if blocked:
        return {
            "ok": False,
            "error": (
                "Yedek/replica görünümlü snapshot silinemez: "
                + ", ".join(blocked[:5])
                + ("; yedek sağlayıcısı bağlı değil — isim kalıbı koruması." if not has_backup else ".")
            ),
            "reason": "backup_named_snapshot",
            "snapshots": blocked,
        }

    if backup_window_active(db):
        return {
            "ok": False,
            "error": "Yedek penceresi içinde snapshot silme engellendi (Ayarlar: backup_window_hours).",
            "reason": "backup_window",
        }

    return {"ok": True}
