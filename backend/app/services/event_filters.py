"""
Paylaşılan SystemEvent filtreleri — Komuta Merkezi, rozetler ve KPI sayaçları
aynı 'actionable' tanımını kullanır (gürültü azaltma, salt okuma).
"""
from __future__ import annotations

from sqlalchemy import or_, and_
from sqlalchemy.orm import Query

from app.models.event import SystemEvent

# log_entry: müşteri adm/journal ile gelen warning/error/critical görünür olsun.
# (Eski eşikler occurrence≥2/3 + error hariç → Ops boş görünüyordu.)
LOG_ENTRY_ACTIONABLE = or_(
    SystemEvent.event_type != "log_entry",
    and_(
        SystemEvent.event_type == "log_entry",
        SystemEvent.severity.in_(["critical", "emergency"]),
        SystemEvent.occurrence_count >= 1,
    ),
    and_(
        SystemEvent.event_type == "log_entry",
        SystemEvent.severity == "warning",
        SystemEvent.occurrence_count >= 1,
    ),
    and_(
        SystemEvent.event_type == "log_entry",
        SystemEvent.severity == "error",
        SystemEvent.occurrence_count >= 1,
    ),
)

# Sanallaştırma: rutin vCenter task (info) ve oturum olayları
ROUTINE_VIRT_EXCLUDE = or_(
    and_(
        SystemEvent.event_type == "vcenter_task",
        SystemEvent.severity.in_(["info"]),
    ),
    SystemEvent.title.ilike("%UserLoginSession%"),
    SystemEvent.title.ilike("%UserLogoutSession%"),
    SystemEvent.title.ilike("%logged in%"),
    SystemEvent.title.ilike("%logged out%"),
    SystemEvent.title.ilike("%User logged%"),
    SystemEvent.title.ilike("%session %"),
)


def apply_actionable_event_filters(q: Query) -> Query:
    """Komuta Merkezi ile aynı: çözülmemiş, bilinmeyen, onaysız, actionable log_entry."""
    return q.filter(
        SystemEvent.resolved == False,  # noqa: E712
        SystemEvent.is_known == False,  # noqa: E712
        SystemEvent.is_acknowledged == False,  # noqa: E712
        LOG_ENTRY_ACTIONABLE,
    )


def apply_hide_routine_virt(q: Query, show_routine: bool = False) -> Query:
    """show_routine=False iken rutin sanallaştırma olaylarını gizle (veri silinmez)."""
    if show_routine:
        return q
    return q.filter(~ROUTINE_VIRT_EXCLUDE)
