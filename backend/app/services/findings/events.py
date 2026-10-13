"""Bulgu → OLAY eşlemesi (deterministik, kodda tanımlı).

Aynı host'taki açık bulgular iki gruba ayrılır:
  (a) aynı olay (aynı kök): aynı `check_id` ailesindeki bulgular — tek olay gibi anlatılır, tek AI yorumu paylaşır;
  (b) aynı host'taki DİĞER açık bulgular: "bu olayla doğrudan ilişkili değil" — olayın nedeni/parçası gibi anlatılmaz.

Aileler elle tanımlıdır (tahmin yok). Tanımsız kontrol kendi başına tek üyeli bir olaydır.
Olay anahtarı: `platform|source_id|entity_ref|aile`.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.infra_finding import InfraFinding

# aile → (check_id önekleri ya da tam kimlikler). Yalnız host varlıklarında gruplanır.
EVENT_FAMILIES: Dict[str, Tuple[str, ...]] = {
    # Donanım: sensör alarmı + genel durum + tekrar + olay örüntüsü + yapılandırma sorunu (aynı fiziksel kök)
    "hardware": ("hw.host.",),
    # Zaman eşitleme (NTP yapılandırılmamış / çalışmıyor)
    "time_sync": ("vmw.host.ntp_configured", "vmw.host.ntp_running", "olvm.host.ntp"),
    # Yol/uplink yedekliliği
    "path_redundancy": ("vmw.host.uplink_redundancy", "vmw.host.storage_path_redundancy", "olvm.host.multipath"),
    # Host durumu (bağlantı / uzun bakım / OLVM durumu)
    "host_state": ("vmw.host.connection", "vmw.host.long_maintenance", "olvm.host.status", "olvm.host.long_maintenance"),
}

FAMILY_LABEL_TR = {"hardware": "Donanım", "time_sync": "Zaman eşitleme", "path_redundancy": "Yol yedekliliği",
                   "host_state": "Host durumu"}


def family_of(check_id: str, entity_kind: str) -> str:
    """check_id → olay ailesi; tanımsızsa check_id'nin kendisi (tek üyeli olay)."""
    if entity_kind == "host":
        for fam, pats in EVENT_FAMILIES.items():
            if any(check_id == p or (p.endswith(".") and check_id.startswith(p)) for p in pats):
                return fam
    return check_id


def event_key(row: InfraFinding) -> str:
    return f"{row.platform}|{row.source_id}|{row.entity_ref}|{family_of(row.check_id, row.entity_kind)}"


_SEV = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _open_fails(db: Session, row: InfraFinding) -> List[InfraFinding]:
    q = (db.query(InfraFinding)
         .filter(InfraFinding.platform == row.platform, InfraFinding.source_id == row.source_id,
                 InfraFinding.entity_ref == row.entity_ref, InfraFinding.active.is_(True),
                 InfraFinding.result == "fail"))
    return sorted(q.all(), key=lambda r: (_SEV.get(r.severity, 9), r.check_id, r.id))


def event_split(db: Session, row: InfraFinding) -> Dict[str, Any]:
    """{"key","family","members":[row...] (a, kendisi dahil), "others":[row...] (b), "representative_id"}.

    Kendisi açık/başarısız değilse bile (ör. çözülmüş) üye olarak eklenir; böylece olay anahtarı tutarlı kalır."""
    fam = family_of(row.check_id, row.entity_kind)
    rows = _open_fails(db, row)
    if row.entity_kind != "host":
        members = [row]
        others: List[InfraFinding] = []
    else:
        members = [r for r in rows if family_of(r.check_id, r.entity_kind) == fam]
        others = [r for r in rows if family_of(r.check_id, r.entity_kind) != fam]
        if row.id not in {m.id for m in members}:
            members.append(row)
    members = sorted(members, key=lambda r: (_SEV.get(r.severity, 9), r.check_id, r.id))
    return {"key": event_key(row), "family": fam, "members": members, "others": others,
            "representative_id": min(m.id for m in members)}


def brief(r: InfraFinding) -> Dict[str, Any]:
    return {"id": r.id, "check_id": r.check_id, "category": r.category, "severity": r.severity,
            "title": r.title, "detail": r.detail}
