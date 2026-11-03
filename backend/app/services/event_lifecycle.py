"""Event / Incident yaşam döngüsü — «sorun giderilince sayı kendiliğinden düşsün».

Olay türüne göre iyileşme modeli (kim, nasıl çözer):

| Sınıf   | Türler                                   | Çözen                                                    |
|---------|------------------------------------------|----------------------------------------------------------|
| managed | `metric_anomaly`                         | `aiops_engine._auto_resolve_recovered` + `storm_detector` |
| managed | `hw_*` (Dell OME / HPE OneView)          | `services/hw/events.sync_hw_events` (koşul kalkınca çöz)  |
| state   | `vcenter_alarm`                          | collector alarm sürdükçe `last_seen` yeniler → bu modül `STATE_QUIET_HOURS` sessizlikte çözer |
| point   | log_entry, vcenter_event/task, ovirt/openshift/openshift_virt/virt olayları… | bu modül: son tekrardan beri önem derecesine göre sessizlik süresi dolunca çözer |
| manual  | `source == manual`                       | dokunulmaz (kullanıcı kaydı)                              |

«Point» olayın iyileşmesi = yeni tekrarın GELMEMESİ; süre `last_seen`'den ölçülür. Collector'lar aynı olayı yeniden
görünce `last_seen`'i yenilediği için süren sorun açık kalır, kesilen sorun sessizlik süresi sonunda kapanır.
Üst sınır 24 saattir — `/events/stats` penceresi (24 saat) ile liste/KPI tutarlı kalır.

Incident tarafı (`reconcile_incidents`): otomatik açılmış (`auto_*` / `storm_detector`), sahiplenilmemiş, `open`
incident'ın TÜM bağlı olayları çözülmüşse (kısa bekleme `INCIDENT_GRACE_MINUTES` sonrası) incident kapanır.
Bağlı olaylardan biri hâlâ açıksa incident kapanmaz (sorun sürüyor). Elle açılan / sahiplenilen / `investigating`
incident'a dokunulmaz. Hiçbir şey silinmez — yalnız `resolved` durumuna geçer.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Set

from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from app.core.timeutil import ensure_utc, utc_now
from app.models.event import Incident, SystemEvent

logger = logging.getLogger(__name__)

# Kendi iyileşme mantığı olan türler — bu modül dokunmaz.
MANAGED_TYPES = frozenset({"metric_anomaly"})
MANAGED_PREFIXES = ("hw_",)
# Koşul-tabanlı (alarm): collector alarm sürdükçe last_seen'i yeniler.
STATE_TYPES = frozenset({"vcenter_alarm"})
# Kullanıcı kayıtları otomatik çözülmez.
SKIP_SOURCES = frozenset({"manual"})

# Collector aralıkları 10-15 dk; geçici sync hatası alarmı yanlışlıkla çözmesin diye cömert.
STATE_QUIET_HOURS = 4
# Son tekrardan beri sessizlik süresi (saat) — önem derecesine göre. Hiçbiri 24 saati aşmaz.
POINT_QUIET_HOURS: Dict[str, int] = {
    "info": 2,
    "warning": 12,
    "error": 24,
    "critical": 24,
    "emergency": 24,
}
DEFAULT_POINT_QUIET_HOURS = 24
# Bağlı tüm olaylar çözüldükten sonra incident'ı kapatmadan önceki kısa bekleme (titreşimi önler).
INCIDENT_GRACE_MINUTES = 15
# Incident aranırken tek turda işlenecek en çok kayıt.
_MAX_INCIDENTS = 2000


def parse_event_timestamp(value: Any) -> Optional[datetime]:
    """Collector'ın ISO-8601 zaman damgasını (Z / ofsetli / naive) UTC-aware datetime'a çevirir; hatalıysa None."""
    if not value:
        return None
    if isinstance(value, datetime):
        return ensure_utc(value)
    try:
        return ensure_utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def _is_incident_auto(inc: Incident) -> bool:
    src = (inc.source or "")
    return src.startswith("auto_") or src == "storm_detector"


def _last_activity():
    return func.coalesce(SystemEvent.last_seen, SystemEvent.created_at)


def sweep_stale_events(db: Session, now: Optional[datetime] = None) -> Dict[str, int]:
    """Sessizliği dolan point/state olayları çöz (toplu UPDATE; satır silinmez)."""
    now = now or utc_now()
    base = db.query(SystemEvent.id).filter(
        SystemEvent.resolved == False,  # noqa: E712
        ~SystemEvent.event_type.in_(list(MANAGED_TYPES)),
        or_(SystemEvent.source.is_(None), ~SystemEvent.source.in_(list(SKIP_SOURCES))),
    )
    for prefix in MANAGED_PREFIXES:
        base = base.filter(~SystemEvent.event_type.like(f"{prefix}%"))

    def _resolve(q) -> int:
        ids = [i for (i,) in q.all()]
        if not ids:
            return 0
        n = (
            db.query(SystemEvent)
            .filter(SystemEvent.id.in_(ids), SystemEvent.resolved == False)  # noqa: E712
            .update({SystemEvent.resolved: True, SystemEvent.resolved_at: now}, synchronize_session=False)
        )
        return int(n or 0)

    stats = {"state": 0, "point": 0}
    # state (alarm)
    stats["state"] = _resolve(
        base.filter(
            SystemEvent.event_type.in_(list(STATE_TYPES)),
            _last_activity() < now - timedelta(hours=STATE_QUIET_HOURS),
        )
    )
    # point — önem derecesine göre
    point = base.filter(~SystemEvent.event_type.in_(list(STATE_TYPES)))
    for sev, hours in POINT_QUIET_HOURS.items():
        stats["point"] += _resolve(
            point.filter(SystemEvent.severity == sev, _last_activity() < now - timedelta(hours=hours))
        )
    # bilinmeyen / boş önem dereceleri → varsayılan süre
    stats["point"] += _resolve(
        point.filter(
            or_(SystemEvent.severity.is_(None), ~SystemEvent.severity.in_(list(POINT_QUIET_HOURS))),
            _last_activity() < now - timedelta(hours=DEFAULT_POINT_QUIET_HOURS),
        )
    )
    if stats["state"] or stats["point"]:
        db.commit()
        logger.info("[EventLifecycle] %d state + %d point olay sessizlikten çözüldü", stats["state"], stats["point"])
    return stats


def unresolved_linked_event_ids(db: Session, event_ids: Iterable[int]) -> Set[int]:
    """Verilen id'ler arasında hâlâ ÇÖZÜLMEMİŞ olanlar (sorun sürüyor göstergesi)."""
    ids = [int(i) for i in dict.fromkeys(event_ids) if i is not None]
    if not ids:
        return set()
    rows = db.query(SystemEvent.id).filter(
        SystemEvent.id.in_(ids), SystemEvent.resolved == False,  # noqa: E712
    ).all()
    return {i for (i,) in rows}


def incident_problem_persists(db: Session, inc: Incident) -> bool:
    """Bağlı olaylardan en az biri hâlâ açıksa True."""
    return bool(unresolved_linked_event_ids(db, inc.related_events or []))


def reconcile_incidents(db: Session, now: Optional[datetime] = None) -> int:
    """Bağlı TÜM olayları çözülmüş otomatik incident'ları kapat. Dönen: kapatılan sayı."""
    now = now or utc_now()
    cutoff = now - timedelta(minutes=INCIDENT_GRACE_MINUTES)
    candidates: List[Incident] = [
        i for i in (
            db.query(Incident)
            .filter(
                Incident.status == "open",
                or_(Incident.assigned_to.is_(None), Incident.assigned_to == ""),
                or_(Incident.source.ilike("auto_%"), Incident.source == "storm_detector"),
            )
            .limit(_MAX_INCIDENTS)
            .all()
        )
        if _is_incident_auto(i) and (i.related_events or [])
    ]
    if not candidates:
        return 0

    all_ids = {int(e) for i in candidates for e in (i.related_events or []) if e is not None}
    state: Dict[int, Any] = {}
    # 5000'lik parçalar: IN listesi şişmesin
    id_list = sorted(all_ids)
    for k in range(0, len(id_list), 5000):
        chunk = id_list[k:k + 5000]
        for eid, resolved, resolved_at in db.query(
            SystemEvent.id, SystemEvent.resolved, SystemEvent.resolved_at,
        ).filter(SystemEvent.id.in_(chunk)).all():
            state[eid] = (bool(resolved), ensure_utc(resolved_at))

    closed = 0
    for inc in candidates:
        found = [state[int(e)] for e in (inc.related_events or []) if e is not None and int(e) in state]
        if not found:
            continue  # bağlı olaylar silinmiş: sessiz-kapanma kuralı (auto_close_quiet_incidents) karar verir
        if any(not r for r, _ in found):
            continue  # sorun sürüyor
        last = max((ra for _, ra in found if ra is not None), default=None)
        if last is not None and last > cutoff:
            continue  # titreşim payı
        inc.status = "resolved"
        inc.resolved_at = now
        inc.resolution = (inc.resolution or "") or "Otomatik çözüldü: bağlı tüm olaylar düzeldi."
        closed += 1
    if closed:
        db.commit()
        logger.info("[EventLifecycle] %d incident, bağlı olayların tümü çözüldüğü için kapatıldı", closed)
    return closed


def run_lifecycle(db: Session, now: Optional[datetime] = None) -> Dict[str, int]:
    """Tam tur: olay süpürme + incident uzlaştırma + dashboard sayaç önbelleğini geçersiz kıl."""
    now = now or utc_now()
    out = {"events_swept": 0, "incidents_closed": 0}
    try:
        s = sweep_stale_events(db, now)
        out["events_swept"] = s["state"] + s["point"]
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("[EventLifecycle] olay süpürme başarısız: %s", exc)
    try:
        out["incidents_closed"] = reconcile_incidents(db, now)
    except Exception as exc:  # noqa: BLE001
        db.rollback()
        logger.warning("[EventLifecycle] incident uzlaştırma başarısız: %s", exc)
    if out["events_swept"] or out["incidents_closed"]:
        try:
            from app.services.dashboard_stats_cache import invalidate_dashboard_stats
            invalidate_dashboard_stats()
        except Exception:  # noqa: BLE001
            pass
    return out
