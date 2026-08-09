"""
Platform kapsamı — Linux / Windows / Sanallaştırma AIOps filtreleme yardımcıları.
"""
from __future__ import annotations

import re
import time
from typing import List, Optional, Set

from sqlalchemy import func as sa_func, or_, and_
from sqlalchemy.orm import Query, Session

from app.models.event import SystemEvent
from app.models.server import Server

from app.models.exadata import ExadataNode

VALID_PLATFORMS = frozenset({"linux", "windows", "virt", "exadata", "openshift"})

# Kısa TTL önbellek — Layout her 30-60 sn'de ops/summary çağırır; her çağrıda
# Server tablosunun tamamını Python'da taramak gereksiz. Process-içi, thread-safe
# olmak zorunda değil (uvicorn tek worker varsayılanı); en kötü stale = TTL.
_ID_CACHE: dict = {}  # key -> (expires_monotonic, value)
_ID_CACHE_TTL = 45.0


def _cached(key: str, factory):
    now = time.monotonic()
    hit = _ID_CACHE.get(key)
    if hit and hit[0] > now:
        return hit[1]
    val = factory()
    _ID_CACHE[key] = (now + _ID_CACHE_TTL, val)
    return val


def invalidate_platform_id_cache() -> None:
    _ID_CACHE.clear()

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
    `UNKNOWN` (henüz detect edilmemiş) VM sayılmaz.
    """
    st = (server.server_type or "").upper()
    if st == "UNKNOWN":
        return False
    return bool(server.hypervisor_id) or st == "VIRTUAL"


def vm_filter_condition():
    """SQLAlchemy filtre koşulu — `is_vm()` ile aynı mantığı DB sorgusunda uygular."""
    return or_(Server.hypervisor_id.isnot(None), Server.server_type == "VIRTUAL")


def get_linux_server_ids(db: Session) -> List[int]:
    return [s.id for s in db.query(Server).all() if is_linux_server(s)]


def get_windows_server_ids(db: Session) -> List[int]:
    return _cached("windows_ids", lambda: [s.id for s in db.query(Server).all() if is_windows_server(s)])


def get_vm_server_ids(db: Session) -> List[int]:
    return [s.id for s in db.query(Server).filter(vm_filter_condition()).all()]


def is_linux_module_server(server: Server, exadata_ids: Optional[Set[int]] = None) -> bool:
    """Linux modülü envanteri — Windows ve Exadata hariç tüm Linux sunucular.

    Windows modülü (`/windows/servers`) hem fiziksel hem sanal Windows
    sunucularını gösterdiği için, tutarlılık adına Linux modülü de hem
    fiziksel Linux host'ları hem de Linux guest OS'li VM'leri gösterir.
    Sanallaştırma modülü (platform=virt) zaten TÜM VM'leri (OS fark etmeksizin)
    ayrıca gösterir — bu iki görünüm birbirini dışlamaz, farklı amaçlara hizmet eder
    (Sanallaştırma = altyapı/hypervisor görünümü, Linux/Windows = OS izleme görünümü).
    """
    if is_windows_server(server):
        return False
    ids = exadata_ids if exadata_ids is not None else None
    if ids is not None and server.id in ids:
        return False
    return True


def get_linux_module_server_ids(db: Session) -> List[int]:
    def _build():
        exadata_ids = get_exadata_server_id_set(db)
        return [s.id for s in db.query(Server).all() if is_linux_module_server(s, exadata_ids)]
    return _cached("linux_module_ids", _build)


def get_linux_module_server_id_set(db: Session) -> Set[int]:
    return set(get_linux_module_server_ids(db))


def is_physical_host(server: Server, exadata_ids: Optional[Set[int]] = None) -> bool:
    """Gerçek fiziksel host — VM, Windows, Exadata ve UNKNOWN hariç.

    `is_linux_module_server` (OS izleme görünümü) artık Linux guest OS'li
    VM'leri de içerdiği için, "Entegrasyonlar → Fiziksel Hostlar" gibi
    yalnızca donanım envanterini gösteren yerler bu daha katı filtreyi kullanır.
    """
    if (server.server_type or "").upper() == "UNKNOWN":
        return False
    return is_linux_module_server(server, exadata_ids) and not is_vm(server)


def get_physical_host_ids(db: Session) -> List[int]:
    exadata_ids = get_exadata_server_id_set(db)
    return [s.id for s in db.query(Server).all() if is_physical_host(s, exadata_ids)]


def server_ids_for_platform(db: Session, platform: str) -> List[int]:
    if platform == "linux":
        return get_linux_module_server_ids(db)
    if platform == "windows":
        return get_windows_server_ids(db)
    if platform == "virt":
        return get_vm_server_ids(db)
    if platform == "exadata":
        return get_exadata_server_ids(db)
    if platform == "openshift":
        return []  # Server tablosuna bağlı değil — kendi cluster/node/proje envanteri var
    return []


def apply_server_platform_filter(q: Query, platform: Optional[str], db: Session) -> Query:
    """Server sorgusuna modül envanter filtresi uygular."""
    if not platform or platform not in VALID_PLATFORMS:
        return q
    if platform == "virt":
        return q.filter(vm_filter_condition())
    ids = server_ids_for_platform(db, platform)
    if ids:
        return q.filter(Server.id.in_(ids))
    return q.filter(False)


def get_exadata_server_ids(db: Session) -> List[int]:
    """Exadata node'larına bağlı Linux sunucu ID'leri (AIOps filtreleme için)."""
    rows = db.query(ExadataNode.server_id).filter(ExadataNode.server_id.isnot(None)).all()
    return [r[0] for r in rows if r[0]]


def get_exadata_server_id_set(db: Session) -> Set[int]:
    return set(get_exadata_server_ids(db))


def platform_for_server(db: Session, server: Server, exadata_ids: Optional[Set[int]] = None) -> str:
    """Olay etiketleme — Exadata node'una bağlı sunucular 'exadata', diğerleri OS'a göre."""
    ids = exadata_ids if exadata_ids is not None else get_exadata_server_id_set(db)
    if server.id in ids:
        return "exadata"
    if is_windows_server(server):
        return "windows"
    return "linux"


def _platform_json(platform: str):
    # raw_data sütunu PostgreSQL'de "json" tipinde (jsonb değil) — .astext comparator'ı
    # desteklemiyor. json_extract_path_text hem json hem jsonb ile çalışır.
    return sa_func.json_extract_path_text(SystemEvent.raw_data, "platform") == platform


# Kaynak (source) bazlı platform eşlemesi — raw_data.platform etiketi eksik olan
# eski/legacy kayıtlarda bile bir modülün diğerine ait log kaynağını göstermemesi
# için ek bir güvenlik katmanı (server_id eşleşmesine tek başına güvenilmiyor).
_VIRT_SOURCES = ("vcenter_event", "vcenter_alarm", "vcenter_task", "virt_collector", "virt_resource", "openshift_virt_event")
_WINDOWS_SOURCES = ("windows_collector",)
_LINUX_SOURCES = ("log_collector",)
_EXADATA_SOURCES = ("exadata_collector",)
_OPENSHIFT_SOURCES = ("openshift_collector",)


def apply_platform_filter(q: Query, platform: Optional[str], db: Session) -> Query:
    """SystemEvent sorgusuna platform filtresi uygular. platform=None → değişiklik yok."""
    if not platform or platform not in VALID_PLATFORMS:
        return q

    if platform == "virt":
        return q.filter(or_(
            _platform_json("virt"),
            SystemEvent.source.in_(_VIRT_SOURCES),
        ))

    if platform == "exadata":
        exadata_ids = get_exadata_server_ids(db)
        explicit = or_(_platform_json("exadata"), SystemEvent.source.in_(_EXADATA_SOURCES))
        if exadata_ids:
            return q.filter(and_(SystemEvent.server_id.in_(exadata_ids), explicit))
        return q.filter(explicit)

    if platform == "openshift":
        # Server tablosuna bağlı değil — sadece kaynak/raw_data.platform eşleşmesiyle filtrelenir.
        return q.filter(or_(_platform_json("openshift"), SystemEvent.source.in_(_OPENSHIFT_SOURCES)))

    windows_ids = get_windows_server_ids(db)
    linux_module_ids = get_linux_module_server_ids(db)

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

    # linux modülü — VM, Windows, Exadata sunucularının log/olayları hariç
    conds: list = []
    if linux_module_ids:
        conds.append(
            and_(
                SystemEvent.server_id.in_(linux_module_ids),
                SystemEvent.source.notin_(_VIRT_SOURCES + _WINDOWS_SOURCES),
                or_(
                    SystemEvent.raw_data.is_(None),
                    SystemEvent.raw_data["platform"].is_(None),
                    _platform_json("linux"),
                ),
            )
        )
        conds.append(
            and_(
                _platform_json("linux"),
                or_(
                    SystemEvent.server_id.is_(None),
                    SystemEvent.server_id.in_(linux_module_ids),
                ),
            )
        )
    return q.filter(or_(*conds)) if conds else q.filter(False)


def filter_incidents_for_platform(incidents: list, platform: Optional[str], db: Session) -> list:
    """Incident listesini modüle göre ayırır.

    Kural (Events filtresiyle uyumlu):
    - İlgili event'lerin platform'u birincil kaynaktır.
    - `auto_vcenter_*` / `auto_virt_*` kaynaklı incident'lar yalnızca Sanallaştırma'da görünür;
      Linux guest `affected_servers` kesişimiyle Linux'a sızmaz.
    - OS modülleri (linux/windows) hypervisor kaynaklı incident'ları göstermez.
    """
    if not platform or platform not in VALID_PLATFORMS:
        return incidents

    linux_module_ids: Set[int] = set(get_linux_module_server_ids(db))
    windows_ids: Set[int] = set(get_windows_server_ids(db))
    exadata_ids: Set[int] = get_exadata_server_id_set(db)

    all_event_ids: Set[int] = set()
    for inc in incidents:
        all_event_ids.update(inc.related_events or [])

    event_platform: dict = {}
    if all_event_ids:
        for ev in db.query(SystemEvent).filter(SystemEvent.id.in_(list(all_event_ids))).all():
            event_platform[ev.id] = infer_event_platform(ev, linux_module_ids, windows_ids, exadata_ids)

    def _src_flags(src: str) -> tuple:
        s = (src or "").lower()
        virt = any(k in s for k in ("virt", "hypervisor", "vcenter")) and "openshift" not in s
        exa = "exadata" in s
        win = "windows" in s
        ocp = "openshift" in s and "virt" not in s
        return virt, exa, win, ocp

    def matches(inc) -> bool:
        src = inc.source or ""
        is_virt_src, is_exa_src, is_win_src, is_ocp_src = _src_flags(src)
        related_plats = {
            event_platform[eid]
            for eid in (inc.related_events or [])
            if eid in event_platform
        }

        if platform == "virt":
            if is_virt_src:
                return True
            return "virt" in related_plats

        if platform == "exadata":
            if is_exa_src:
                return True
            return "exadata" in related_plats

        if platform == "openshift":
            if is_ocp_src:
                return True
            return "openshift" in related_plats

        # OS görünümleri: hypervisor / diğer platform kaynaklarını gösterme
        if is_virt_src or is_ocp_src:
            return False
        if platform == "linux" and (is_win_src or is_exa_src):
            return False
        if platform == "windows" and is_exa_src:
            return False

        if related_plats:
            # İlişkili event'ler varsa yalnızca onların platform'una göre eşle
            # (ör. vCenter olayı Linux guest'e bağlı olsa bile Linux'a düşmez)
            return platform in related_plats

        aff = set(inc.affected_servers or [])
        src_l = (src or "").lower()
        if platform == "linux":
            if aff & linux_module_ids:
                return True
            # Event/server bağı kopmuş Linux AIOps/log incident'ları kaybolmasın
            if not aff and any(
                k in src_l for k in ("log_collector", "aiops", "storm_detector", "manual", "metric_anomaly")
            ):
                return not is_virt_src and not is_win_src and not is_exa_src
            return False
        if platform == "windows":
            if aff & windows_ids:
                return True
            if not aff and "windows" in src_l:
                return True
            return False
        return False

    return [inc for inc in incidents if matches(inc)]


def infer_event_platform(
    ev: SystemEvent,
    linux_ids: Optional[Set[int]] = None,
    windows_ids: Optional[Set[int]] = None,
    exadata_ids: Optional[Set[int]] = None,
) -> str:
    raw = ev.raw_data or {}
    p = raw.get("platform")
    if p in VALID_PLATFORMS:
        return p
    src = (ev.source or "").lower()
    if (
        src.startswith("vcenter_")
        or src in _VIRT_SOURCES
        or src.startswith("virt_")
        or "vcenter" in src
        or src.startswith("auto_virt")
        or src.startswith("auto_vcenter")
    ):
        return "virt"
    if src in _EXADATA_SOURCES or "exadata" in src:
        return "exadata"
    if src in _OPENSHIFT_SOURCES or src.startswith("openshift_") and "virt" not in src:
        return "openshift"
    if src in _WINDOWS_SOURCES or src.startswith("windows_") or src.startswith("auto_windows"):
        return "windows"
    if src in _LINUX_SOURCES or src.startswith("auto_log") or src == "prometheus":
        # prometheus anomalileri server_id üzerinden OS'a düşer; aşağıda devam
        pass
    if ev.server_id:
        if exadata_ids is not None and ev.server_id in exadata_ids:
            return "exadata"
        if windows_ids is not None and ev.server_id in windows_ids:
            return "windows"
        if linux_ids is not None and ev.server_id in linux_ids:
            return "linux"
    if src in _LINUX_SOURCES or src.startswith("auto_log"):
        return "linux"
    return "linux"
