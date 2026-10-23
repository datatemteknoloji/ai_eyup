"""Donanım kaydı ↔ ainew hedefi (fiziksel Linux/Windows sunucu, ESXi host) eşleştirmesi.

Sıra: seri/service tag (exact) → UUID (exact; SMBIOS karışık-endian varyantı dahil) → HPE sanal seri / sanal UUID
(profil atanmış sunucu; exact) → kısa hostname (YALNIZ iki tarafta da tekil ise; confidence=low, UI'da işaretli).
Bir hedefe en çok bir donanım kaydı eşlenir. Eşleşmeyenler iki yönde listelenir (üçüncü liste: belirsiz/çakışan).
Saf çekirdek `match_core` I/O yapmaz (test edilebilir); `run_matching` DB'yi okur/yazar.
"""
from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.services.hw.identity import normalize_serial, short_host, uuid_variants

logger = logging.getLogger(__name__)

CONF_EXACT = "exact"
CONF_LOW = "low"


@dataclass
class HwItem:
    id: int
    serial: Optional[str] = None
    uuid: Optional[str] = None
    virtual_serial: Optional[str] = None
    virtual_uuid: Optional[str] = None
    names: List[str] = field(default_factory=list)      # os_hostname, name


@dataclass
class Target:
    kind: str                                            # server | esxi
    id: int
    serial: Optional[str] = None
    uuid: Optional[str] = None
    names: List[str] = field(default_factory=list)


@dataclass
class MatchResult:
    links: List[Tuple[int, str, int, str, str]] = field(default_factory=list)   # (hw_id, kind, target_id, method, conf)
    hw_unmatched: List[int] = field(default_factory=list)
    target_unmatched: List[Tuple[str, int]] = field(default_factory=list)
    ambiguous: List[Dict[str, Any]] = field(default_factory=list)


def _uuid_keys(u: Optional[str]) -> List[str]:
    return uuid_variants(u)


def match_core(hw: List[HwItem], targets: List[Target]) -> MatchResult:
    res = MatchResult()
    used_hw: set = set()
    used_t: set = set()

    def tkey(t: Target) -> Tuple[str, int]:
        return (t.kind, t.id)

    def _try(method: str, hw_keys, tgt_keys, conf: str) -> None:
        """hw_keys: Callable[HwItem]→List[str]; tgt_keys: Callable[Target]→List[str]. Her iki taraf tekil ise eşler."""
        index: Dict[str, List[Target]] = defaultdict(list)
        for t in targets:
            if tkey(t) in used_t:
                continue
            for k in tgt_keys(t):
                index[k].append(t)
        hw_by_key: Dict[str, List[HwItem]] = defaultdict(list)
        for h in hw:
            if h.id in used_hw:
                continue
            for k in hw_keys(h):
                hw_by_key[k].append(h)
        for h in hw:
            if h.id in used_hw:
                continue
            cands: Dict[Tuple[str, int], Target] = {}
            for k in hw_keys(h):
                for t in index.get(k, []):
                    cands[tkey(t)] = t
            if not cands:
                continue
            # belirsizlik: birden çok hedef VEYA aynı anahtarı paylaşan birden çok donanım kaydı
            sharing = {x.id for k in hw_keys(h) for x in hw_by_key.get(k, [])}
            if len(cands) > 1 or len(sharing) > 1:
                res.ambiguous.append({"hw_id": h.id, "method": method,
                                      "targets": [list(k) for k in cands], "hw_ids": sorted(sharing)})
                continue
            (k, t), = cands.items()
            used_hw.add(h.id)
            used_t.add(k)
            res.links.append((h.id, t.kind, t.id, method, conf))

    _try("serial", lambda h: [h.serial] if h.serial else [], lambda t: [t.serial] if t.serial else [], CONF_EXACT)
    _try("uuid", lambda h: _uuid_keys(h.uuid), lambda t: _uuid_keys(t.uuid), CONF_EXACT)
    _try("virtual_serial", lambda h: [h.virtual_serial] if h.virtual_serial else [],
         lambda t: [t.serial] if t.serial else [], CONF_EXACT)
    _try("virtual_uuid", lambda h: _uuid_keys(h.virtual_uuid), lambda t: _uuid_keys(t.uuid), CONF_EXACT)

    def _hosts(names: List[str]) -> List[str]:
        out = []
        for n in names:
            s = short_host(n)
            if s and s not in out:
                out.append(s)
        return out

    _try("hostname", lambda h: _hosts(h.names), lambda t: _hosts(t.names), CONF_LOW)

    res.hw_unmatched = [h.id for h in hw if h.id not in used_hw]
    res.target_unmatched = [tkey(t) for t in targets if tkey(t) not in used_t]
    return res


def load_hw_items(db: Session) -> List[HwItem]:
    from app.models.hw import HwServer
    from app.services.hw.demo_gate import demo_enabled
    from app.models.integration_instance import IntegrationInstance
    # DEMO kayıtları gerçek eşleştirmeye KARIŞMAZ (gerçek sağlayıcı varsa zaten demo etkisiz)
    demo_ids = [i for (i,) in db.query(IntegrationInstance.id).filter(IntegrationInstance.kind == "hw_demo").all()]
    q = db.query(HwServer)
    if demo_ids:
        q = q.filter(~HwServer.instance_id.in_(demo_ids))
    return [HwItem(id=s.id, serial=normalize_serial(s.serial), uuid=s.uuid, virtual_serial=normalize_serial(s.virtual_serial),
                   virtual_uuid=s.virtual_uuid, names=[n for n in (s.os_hostname, s.name) if n])
            for s in q.all()]


def load_targets(db: Session) -> List[Target]:
    from app.models.hypervisor_inventory import HypervisorHostInventory
    from app.models.server import Server
    out: List[Target] = []
    for s in db.query(Server).filter((Server.server_type.is_(None)) | (Server.server_type.in_(("PHYSICAL", "physical", "UNKNOWN")))).all():
        out.append(Target("server", s.id, serial=normalize_serial(s.hw_serial), uuid=s.hw_uuid,
                          names=[n for n in (s.hostname, s.name) if n]))
    for h in db.query(HypervisorHostInventory).all():
        out.append(Target("esxi", h.id, serial=normalize_serial(h.serial_number), uuid=h.uuid,
                          names=[h.host_name] if h.host_name else []))
    return out


def run_matching(db: Session) -> Dict[str, Any]:
    """Eşleşmeleri yeniden hesaplar ve `hw_host_links`'e yazar (idempotent)."""
    from app.models.hw import HwHostLink
    hw = load_hw_items(db)
    if not hw:
        db.query(HwHostLink).delete(synchronize_session=False)
        db.commit()
        return {"links": 0, "hw_unmatched": 0}
    res = match_core(hw, load_targets(db))
    want = {h: (k, t, m, c) for (h, k, t, m, c) in res.links}
    have = {l.hw_server_id: l for l in db.query(HwHostLink).all()}
    for hid, l in list(have.items()):
        w = want.get(hid)
        if w is None or (l.target_kind, l.target_id) != (w[0], w[1]):
            db.delete(l)
            have.pop(hid)
    db.flush()
    for hid, (k, t, m, c) in want.items():
        l = have.get(hid)
        if l is None:
            db.add(HwHostLink(hw_server_id=hid, target_kind=k, target_id=t, method=m, confidence=c))
        else:
            l.method, l.confidence = m, c
    db.commit()
    return {"links": len(want), "hw_unmatched": len(res.hw_unmatched), "ambiguous": len(res.ambiguous),
            "target_unmatched": len(res.target_unmatched)}
