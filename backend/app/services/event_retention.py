"""
Event Retention — system_events tablosu için otomatik temizlik.

system_events sürekli büyüyen bir tablo (log_entry, metric_anomaly, vcenter_event vb.
periyodik olarak arka plan görevlerince ekleniyor) ama hiçbir otomatik retention
mekanizması yoktu. Zamanla milyonlarca satıra ulaşırsa index bakımı, VACUUM ve genel
sorgu performansı kademeli olarak bozulur (dolaylı "hang" riski). Bu modül, ayarlanabilir
bir saklama süresinden (varsayılan 180 gün) eski kayıtları periyodik olarak siler.
"""
import logging
from datetime import datetime, timezone, timedelta

from sqlalchemy.orm import Session

from app.models.event import SystemEvent

logger = logging.getLogger(__name__)


def cleanup_old_events(db: Session, retention_days: int = 180, batch_size: int = 5000) -> dict:
    """retention_days'den eski system_events kayıtlarını siler (last_seen baz alınır).

    Büyük silme işlemlerinin tek bir uzun transaction'da kilit tutmaması için
    parça parça (batch) silinir.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(days=max(30, retention_days))
    total_deleted = 0
    try:
        while True:
            ids = [
                r[0] for r in (
                    db.query(SystemEvent.id)
                    .filter(SystemEvent.last_seen < cutoff)
                    .limit(batch_size)
                    .all()
                )
            ]
            if not ids:
                break
            deleted = (
                db.query(SystemEvent)
                .filter(SystemEvent.id.in_(ids))
                .delete(synchronize_session=False)
            )
            db.commit()
            total_deleted += deleted
            if deleted < batch_size:
                break
    except Exception:
        db.rollback()
        raise
    if total_deleted:
        logger.info(f"Event retention: {total_deleted} eski kayıt silindi (>{retention_days} gün)")
    return {"deleted": total_deleted, "retention_days": retention_days}
