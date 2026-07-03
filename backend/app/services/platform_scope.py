"""
Platform kapsamı — Linux / Windows / Sanallaştırma AIOps filtreleme yardımcıları.
"""
from __future__ import annotations

import re
from typing import List, Optional, Set

from sqlalchemy import func as sa_func, or_, and_
from sqlalchemy.orm import Query, Session

from app.models.event import SystemEvent
from app.models.server import Server

VALID_PLATFORMS = frozenset({"linux", "windows", "virt"})

# `os_type` henüz toplanmamış (ör. VMware Tools kurulu değil, sync hiç
# çalışmamış) VM'ler için isim tabanlı son çare tahmini — sadece os_type
# BOŞ olduğunda devreye girer, bilinen bir Linux/other değeri asla ezilmez.
_WINDOWS_NAME_RE = re.compile(r"windows|winserver|win[-_]?server|win\d{2}", re.IGNORECASE)


def is_windows_server(server: Server) -> bool:
    os_type = (server.os_type or "").lower()
    if "windows" in os_type:
        return True
    conn = server.connection_config or {}
    if conn.get("winrm") or conn.get("protocol") == "winrm":
        return True
    if not os_type and _WINDOWS_NAME_RE.search(server.name or ""):
        return True
    return False


def is_linux_server(server: Server) -> bool:
    return not is_windows_server(server)


def is_vm(server: Server) -> bool:
    """Bir sunucunun sanal makine sayılıp sayılmayacağını belirler.

    Sanallaştırma modülü "bütün VM'leri" göstermeli — bu yüzden hem
    hypervisor sync ile gelen VM'ler (`hypervisor_id` dolu) hem de
    UCMDB/CMDB gibi başka kaynaklardan `server_type=VIRTUAL` olarak
    işaretlenmiş sunucular VM sayılır.
    """
    return bool(server.hypervisor_id) or (server.server_type or "").upper() == "VIRTUAL"


def vm_filter_condition():
    """SQLAlchemy filtre koşulu — `is_vm()` ile aynı mantığı DB sorgusunda uygular."""
    return or_(Server.hypervisor_id.isnot(None), Server.server_type == "VIRTUAL")


def get_linux_server_ids(db: Session) -> List[int]:
    return [s.id for s in db.query(Server).all() if is_linux_server(s)]


def get_windows_server_ids(db: Session) -> List[int]:
    return [s.id for s in db.query(Server).all() if is_windows_server(s)]


def get_vm_server_ids(db: Session) -> List[int]:
    return [s.id for s in db.query(Server).filter(vm_filter_condition()).all()]


def _platform_json(platform: str):
    # raw_data sütunu PostgreSQL'de "json" tipinde (jsonb değil) — .astext comparator'ı
    # desteklemiyor. json_extract_path_text hem json hem jsonb ile çalışır.
    return sa_func.json_extract_path_text(SystemEvent.raw_data, "platform") == platform


# Kaynak (source) bazlı platform eşlemesi — raw_data.platform etiketi eksik olan
# eski/legacy kayıtlarda bile bir modülün diğerine ait log kaynağını göstermemesi
# için ek bir güvenlik katmanı (server_id eşleşmesine tek başına güvenilmiyor).
_VIRT_SOURCES = ("vcenter_event", "vcenter_alarm", "vcenter_task", "virt_collector", "virt_resource")
_WINDOWS_SOURCES = ("windows_collector",)
_LINUX_SOURCES = ("log_collector",)


def apply_platform_filter(q: Query, platform: Optional[str], db: Session) -> Query:
    """SystemEvent sorgusuna platform filtresi uygular. platform=None → değişiklik yok."""
    if not platform or platform not in VALID_PLATFORMS:
        return q

    if platform == "virt":
        return q.filter(or_(
            _platform_json("virt"),
            SystemEvent.source.in_(_VIRT_SOURCES),
        ))

    windows_ids = get_windows_server_ids(db)
    linux_ids = get_linux_server_ids(db)

    if platform == "windows":
        # Windows modülü sadece OS üzerinden (WinRM/Event Log) toplanan kayıtları
        # göstermeli — bir Windows VM'e ait vCenter olayı (raw_data.platform="virt")
        # veya başka bir platformun log kaynağı (ör. log_collector) server_id
        # eşleşmesiyle buraya sızmamalı.
        conds = [_platform_json("windows")]
        if windows_ids:
            conds.append(
                and_(
                    SystemEvent.server_id.in_(windows_ids),
                    SystemEvent.source.notin_(_VIRT_SOURCES + _LINUX_SOURCES),
                    or_(
                        SystemEvent.raw_data.is_(None),
                        SystemEvent.raw_data["platform"].is_(None),
                        _platform_json("windows"),
                    ),
                )
            )
        return q.filter(or_(*conds)) if conds else q.filter(False)

    # linux — mevcut kayıtlar platform etiketi olmadan da linux sunucularına bağlı
    conds = [_platform_json("linux")]
    if linux_ids:
        conds.append(
            and_(
                SystemEvent.server_id.in_(linux_ids),
                SystemEvent.source.notin_(_VIRT_SOURCES + _WINDOWS_SOURCES),
                or_(
                    SystemEvent.raw_data.is_(None),
                    SystemEvent.raw_data["platform"].is_(None),
                    _platform_json("linux"),
                ),
            )
        )
    return q.filter(or_(*conds)) if conds else q.filter(False)


def filter_incidents_for_platform(incidents: list, platform: Optional[str], db: Session) -> list:
    if not platform or platform not in VALID_PLATFORMS:
        return incidents

    linux_ids: Set[int] = set(get_linux_server_ids(db))
    windows_ids: Set[int] = set(get_windows_server_ids(db))

    all_event_ids: Set[int] = set()
    for inc in incidents:
        all_event_ids.update(inc.related_events or [])

    event_platform: dict = {}
    if all_event_ids:
        for ev in db.query(SystemEvent).filter(SystemEvent.id.in_(list(all_event_ids))).all():
            event_platform[ev.id] = infer_event_platform(ev, linux_ids, windows_ids)

    def matches(inc) -> bool:
        for eid in inc.related_events or []:
            if event_platform.get(eid) == platform:
                return True
        aff = set(inc.affected_servers or [])
        if platform == "linux" and aff & linux_ids:
            return True
        if platform == "windows" and aff & windows_ids:
            return True
        if platform == "virt":
            src = (inc.source or "").lower()
            if "virt" in src or "hypervisor" in src or "vcenter" in src:
                return True
        return False

    return [inc for inc in incidents if matches(inc)]


def infer_event_platform(ev: SystemEvent, linux_ids: Optional[Set[int]] = None, windows_ids: Optional[Set[int]] = None) -> str:
    raw = ev.raw_data or {}
    p = raw.get("platform")
    if p in VALID_PLATFORMS:
        return p
    src = (ev.source or "").lower()
    if src.startswith("vcenter_") or src in ("virt_collector", "virt_resource"):
        return "virt"
    if ev.server_id:
        if windows_ids is not None and ev.server_id in windows_ids:
            return "windows"
        if linux_ids is not None and ev.server_id in linux_ids:
            return "linux"
    return "linux"
