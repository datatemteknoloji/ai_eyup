"""
Envanter tekilleştirme — UCMDB, hypervisor, Exadata, manuel kayıtları birleştirir.

Eşleştirme önceliği: IP → hostname → name (case-insensitive)
Kaynak bilgisi connection_config.inventory_sources içinde tutulur.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.server import Server

logger = logging.getLogger(__name__)


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def find_existing_server(
    db: Session,
    *,
    ip: Optional[str] = None,
    hostname: Optional[str] = None,
    name: Optional[str] = None,
    exclude_id: Optional[int] = None,
) -> Optional[Server]:
    """Tekil envanter kaydı bul — IP, hostname veya name ile."""
    ip_n = _norm(ip)
    host_n = _norm(hostname)
    name_n = _norm(name)

    if ip_n:
        q = db.query(Server).filter(Server.ip_address.isnot(None))
        for s in q.all():
            if s.id == exclude_id:
                continue
            if _norm(s.ip_address) == ip_n:
                return s

    if host_n:
        for s in db.query(Server).filter(Server.hostname.isnot(None)).all():
            if s.id == exclude_id:
                continue
            if _norm(s.hostname) == host_n:
                return s

    if name_n:
        for s in db.query(Server).all():
            if s.id == exclude_id:
                continue
            if _norm(s.name) == name_n:
                return s

    return None


def tag_inventory_source(server: Server, source: str, extra: Optional[Dict[str, Any]] = None) -> None:
    """connection_config.inventory_sources listesine kaynak etiketi ekle."""
    cfg = dict(server.connection_config or {})
    sources: List[Dict[str, Any]] = list(cfg.get("inventory_sources") or [])
    entry = {"source": source, "updated_at": datetime.utcnow().isoformat()}
    if extra:
        entry.update(extra)
    # Aynı kaynak varsa güncelle
    replaced = False
    for i, s in enumerate(sources):
        if s.get("source") == source:
            sources[i] = {**s, **entry}
            replaced = True
            break
    if not replaced:
        sources.append(entry)
    cfg["inventory_sources"] = sources
    cfg["primary_inventory_source"] = cfg.get("primary_inventory_source") or source
    server.connection_config = cfg


def detect_duplicate_groups(db: Session) -> List[Dict[str, Any]]:
    """Potansiyel mükerrer grupları döner (aynı IP veya hostname)."""
    servers = db.query(Server).all()
    by_ip: Dict[str, List[Server]] = {}
    by_host: Dict[str, List[Server]] = {}

    for s in servers:
        ip = _norm(s.ip_address)
        host = _norm(s.hostname)
        if ip:
            by_ip.setdefault(ip, []).append(s)
        if host and host != ip:
            by_host.setdefault(host, []).append(s)

    groups: List[Dict[str, Any]] = []
    seen_ids: set = set()

    def _group(key: str, match_type: str, items: List[Server]) -> None:
        if len(items) < 2:
            return
        ids = {s.id for s in items}
        if ids & seen_ids:
            return
        seen_ids.update(ids)
        groups.append({
            "match_key": key,
            "match_type": match_type,
            "count": len(items),
            "servers": [
                {
                    "id": s.id,
                    "name": s.name,
                    "hostname": s.hostname,
                    "ip_address": s.ip_address,
                    "server_type": s.server_type,
                    "hypervisor_id": s.hypervisor_id,
                    "sources": (s.connection_config or {}).get("inventory_sources", []),
                }
                for s in items
            ],
        })

    for ip, items in by_ip.items():
        _group(ip, "ip", items)
    for host, items in by_host.items():
        _group(host, "hostname", items)

    return sorted(groups, key=lambda g: -g["count"])


def merge_servers(db: Session, keep_id: int, merge_ids: List[int], dry_run: bool = True) -> Dict[str, Any]:
    """merge_ids kayıtlarını keep_id altında birleştirir."""
    keep = db.query(Server).filter(Server.id == keep_id).first()
    if not keep:
        raise ValueError(f"keep_id={keep_id} bulunamadı")

    to_merge = db.query(Server).filter(Server.id.in_(merge_ids), Server.id != keep_id).all()
    if not to_merge:
        return {"merged": 0, "dry_run": dry_run}

    actions = []
    for s in to_merge:
        actions.append({"from_id": s.id, "from_name": s.name, "into_id": keep_id})
        if dry_run:
            continue
        # Kaynak etiketlerini taşı
        for src in (s.connection_config or {}).get("inventory_sources") or []:
            tag_inventory_source(keep, src.get("source", "merged"), src)
        tag_inventory_source(keep, "dedup_merge", {"merged_from_id": s.id, "merged_from_name": s.name})
        # Boş alanları doldur
        for field in ("ip_address", "hostname", "os_type", "os_version", "cpu_cores", "memory_gb", "tier"):
            if not getattr(keep, field) and getattr(s, field):
                setattr(keep, field, getattr(s, field))
        if not keep.hypervisor_id and s.hypervisor_id:
            keep.hypervisor_id = s.hypervisor_id
            keep.hypervisor_vm_id = s.hypervisor_vm_id
        db.delete(s)

    if not dry_run:
        db.commit()

    return {"merged": len(to_merge), "dry_run": dry_run, "keep_id": keep_id, "actions": actions}


def auto_deduplicate(db: Session, dry_run: bool = True) -> Dict[str, Any]:
    """Tüm mükerrer gruplarda en eski kaydı tut, diğerlerini birleştir."""
    groups = detect_duplicate_groups(db)
    total_merged = 0
    results = []

    for g in groups:
        servers = g["servers"]
        # En çok bilgi taşıyan veya en düşük id (eski kayıt) kalsın
        keep = min(servers, key=lambda x: (0 if x.get("hypervisor_id") else 1, x["id"]))
        merge_ids = [s["id"] for s in servers if s["id"] != keep["id"]]
        if not merge_ids:
            continue
        r = merge_servers(db, keep["id"], merge_ids, dry_run=dry_run)
        total_merged += r["merged"]
        results.append({"group": g["match_key"], "match_type": g["match_type"], **r})

    return {"groups_processed": len(results), "total_merged": total_merged, "dry_run": dry_run, "details": results}
