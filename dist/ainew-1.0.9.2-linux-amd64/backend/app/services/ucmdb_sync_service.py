"""
uCMDB → ainew envanter senkronu.

- Fiziksel sunucular → Server (hypervisor_id yok, VIRTUAL değil)
- Exadata rack/node → ExadataRack / ExadataNode (+ isteğe bağlı Server link)
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.app_settings import AppSettings
from app.models.exadata import ExadataNode, ExadataNodeRole, ExadataRack
from app.models.server import Server
from app.services.inventory_dedup import find_existing_server, tag_inventory_source
from app.services.ucmdb_client import UcmdbClient, UcmdbClientError

logger = logging.getLogger(__name__)

SETTINGS_KEY = "ucmdb_connection"

DEFAULT_CONNECTION: Dict[str, Any] = {
    "enabled": False,
    "base_url": "",
    "username": "",
    "password": "",
    "verify_ssl": False,
    "sync_physical": True,
    "sync_exadata": True,
    "sync_virtual": False,
    "physical_ci_types": ["unix", "nt", "node", "host_node", "aix_server"],
    "physical_tql": "",
    "exadata_ci_types": [
        "oracle_exadata",
        "exadata",
        "oracle_db_machine",
        "oracle_exadata_storage_server",
    ],
    "exadata_tql": "",
    "exadata_node_name_patterns": ["db0", "cel", "exadata", "-db", "-cel"],
}

_CI_TYPE_MAP: List[Tuple[str, str, bool]] = [
    ("windows", "windows", False),
    ("nt", "windows", False),
    ("unix", "linux", False),
    ("linux", "linux", False),
    ("red hat", "rhel", False),
    ("rhel", "rhel", False),
    ("suse", "sles", False),
    ("ubuntu", "ubuntu", False),
    ("vmware virtual machine", "", True),
    ("virtual machine", "", True),
    ("hyper-v", "windows", True),
    ("ibm aix", "aix", False),
    ("aix", "aix", False),
    ("exadata", "linux", False),
    ("oracle", "linux", False),
]


def _get_row(db: Session) -> Optional[AppSettings]:
    return db.query(AppSettings).filter(AppSettings.key == SETTINGS_KEY).first()


def load_connection(db: Session) -> Dict[str, Any]:
    cfg = dict(DEFAULT_CONNECTION)
    row = _get_row(db)
    if row and row.value:
        try:
            saved = json.loads(row.value)
            if isinstance(saved, dict):
                cfg.update(saved)
        except Exception:
            logger.warning("ucmdb_connection JSON okunamadı")
    return cfg


def save_connection(db: Session, data: Dict[str, Any], *, keep_password: bool = True) -> Dict[str, Any]:
    cfg = load_connection(db)
    for k, v in data.items():
        if k == "password" and (v is None or v == "" or v == "********"):
            continue
        cfg[k] = v
    row = _get_row(db)
    payload = json.dumps(cfg)
    if row:
        row.value = payload
    else:
        db.add(AppSettings(key=SETTINGS_KEY, value=payload))
    db.commit()
    return public_connection(cfg)


def public_connection(cfg: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(cfg)
    if out.get("password"):
        out["password"] = "********"
        out["password_set"] = True
    else:
        out["password_set"] = False
    return out


def _client_from_cfg(cfg: Dict[str, Any]) -> UcmdbClient:
    return UcmdbClient(
        base_url=str(cfg.get("base_url") or ""),
        username=str(cfg.get("username") or ""),
        password=str(cfg.get("password") or ""),
        verify_ssl=bool(cfg.get("verify_ssl", False)),
    )


def test_connection(db: Session) -> Dict[str, Any]:
    cfg = load_connection(db)
    client = _client_from_cfg(cfg)
    client.authenticate()
    return {"ok": True, "message": "uCMDB kimlik doğrulama başarılı", "base_url": cfg.get("base_url")}


def _prop(ci: Dict[str, Any], *keys: str, default: str = "") -> str:
    lower_map = {str(ck).lower(): cv for ck, cv in ci.items()}
    for k in keys:
        v = ci.get(k)
        if v in (None, ""):
            v = lower_map.get(k.lower())
        if v not in (None, ""):
            return str(v).strip()
    return default


def _ci_to_server_fields(ci: Dict[str, Any]) -> Dict[str, Any]:
    name = _prop(ci, "name", "display_label", "Name")
    host = _prop(ci, "primary_dns_name", "host_name", "hostname", "dns_name")
    ip = _prop(ci, "primary_ip_address", "ip_address", "ip", "management_ip")
    os_raw = _prop(ci, "discovered_os_name", "os_description", "os_family", "os_name", "os_type")
    os_ver = _prop(ci, "os_version", "os_software_version")
    ci_type = _prop(ci, "ci_type", "type", "typeName", "ciType")
    env = _prop(ci, "environment", "tier", "business_criticality")
    notes = _prop(ci, "description", "note")
    ucmdb_id = _prop(ci, "ucmdb_id", "ucmdbId", "global_id", "root_id", "id")

    mem_gb = None
    mem_raw = _prop(ci, "memory_size", "memory_size_mb", "physical_memory_mb")
    if mem_raw:
        try:
            mv = float(mem_raw)
            if mv > 500000:
                mem_gb = max(1, round(mv / (1024 * 1024)))
            elif mv > 1024:
                mem_gb = max(1, round(mv / 1024))
            else:
                mem_gb = max(1, round(mv))
        except (TypeError, ValueError):
            pass

    cpu = None
    cpu_raw = _prop(ci, "cpu_number", "number_of_processors", "cpu_count", "cpus")
    if cpu_raw:
        try:
            cpu = int(float(cpu_raw))
        except (TypeError, ValueError):
            pass

    is_virtual = None
    os_type = ""
    blob = f"{ci_type} {os_raw}".lower()
    for kw, osname, is_virt in _CI_TYPE_MAP:
        if kw in blob:
            if osname:
                os_type = osname
            is_virtual = is_virt
            break
    if not os_type and os_raw:
        os_type = os_raw[:64]

    tier = "unknown"
    if env:
        t = env.lower()
        tier = {
            "production": "critical", "prod": "critical", "staging": "high",
            "test": "medium", "qa": "medium", "development": "low", "dev": "low",
        }.get(t, t[:20])

    server_type = "physical"
    if is_virtual is True:
        server_type = "VIRTUAL"
    elif ci_type:
        server_type = ci_type[:64]

    return {
        "name": name or host or ip or "unknown",
        "hostname": host or name or "",
        "ip_address": ip or None,
        "os_type": os_type,
        "os_version": os_ver,
        "cpu_cores": cpu,
        "memory_gb": mem_gb,
        "server_type": server_type,
        "tier": tier,
        "_is_virtual": is_virtual,
        "_notes": notes,
        "_ucmdb_id": ucmdb_id,
        "_ci_type": ci_type,
        "_vendor": _prop(ci, "vendor"),
        "_model": _prop(ci, "model_name", "model"),
        "_datacenter": _prop(ci, "data_center", "location", "datacenter"),
    }


def _is_exadata_ci(ci: Dict[str, Any], patterns: List[str], exadata_types: List[str]) -> bool:
    ci_type = _prop(ci, "ci_type", "type", "typeName").lower()
    name = _prop(ci, "name", "display_label").lower()
    for t in exadata_types:
        if t.lower() in ci_type or ci_type == t.lower():
            return True
    for p in patterns:
        if p.lower() in name:
            return True
    return False


def _guess_node_role(name: str, ci_type: str) -> ExadataNodeRole:
    blob = f"{name} {ci_type}".lower()
    if "cel" in blob or "storage" in blob or "cell" in blob:
        return ExadataNodeRole.STORAGE_CELL
    if "ib" in blob or "infiniband" in blob or "switch" in blob:
        return ExadataNodeRole.IB_SWITCH
    if "pdu" in blob:
        return ExadataNodeRole.PDU
    if "db" in blob or "compute" in blob or "unix" in blob or "linux" in blob:
        return ExadataNodeRole.COMPUTE_NODE
    return ExadataNodeRole.OTHER


def _find_by_ucmdb_id(db: Session, ucmdb_id: str) -> Optional[Server]:
    if not ucmdb_id:
        return None
    for s in db.query(Server).filter(Server.connection_config.isnot(None)).limit(8000).all():
        cfg = s.connection_config or {}
        if cfg.get("ucmdb_id") == ucmdb_id or cfg.get("ucmdb_global_id") == ucmdb_id:
            return s
    return None


def _upsert_physical(db: Session, fields: Dict[str, Any], *, skip_virtual: bool) -> str:
    if skip_virtual and fields.get("_is_virtual") is True:
        return "skipped_virtual"
    if fields.get("server_type") == "VIRTUAL" and skip_virtual:
        return "skipped_virtual"

    name = fields["name"]
    ip = fields.get("ip_address")
    host = fields.get("hostname")
    ucmdb_id = fields.get("_ucmdb_id")

    existing = _find_by_ucmdb_id(db, ucmdb_id or "")
    if not existing:
        existing = find_existing_server(db, ip=ip, hostname=host or None, name=name)

    meta = {
        "ucmdb_import": True,
        "ucmdb_api_sync": True,
        "ucmdb_id": ucmdb_id or None,
        "ucmdb_ci_type": fields.get("_ci_type") or None,
        "ucmdb_is_virtual": fields.get("_is_virtual"),
    }
    if fields.get("_notes"):
        meta["ucmdb_notes"] = fields["_notes"]
    if fields.get("_vendor"):
        meta["ucmdb_vendor"] = fields["_vendor"]
    if fields.get("_model"):
        meta["ucmdb_model"] = fields["_model"]

    if existing:
        for field in ("ip_address", "hostname", "os_type", "os_version", "cpu_cores", "memory_gb", "server_type", "tier"):
            v = fields.get(field)
            if v is not None and v != "":
                setattr(existing, field, v)
        cfg = dict(existing.connection_config or {})
        cfg.update({k: v for k, v in meta.items() if v is not None})
        existing.connection_config = cfg
        tag_inventory_source(existing, "ucmdb", {"via": "api"})
        return "updated"

    cfg = {k: v for k, v in meta.items() if v is not None}
    cfg["inventory_sources"] = [{"source": "ucmdb", "via": "api"}]
    srv = Server(
        name=name,
        hostname=host or name,
        ip_address=ip,
        os_type=fields.get("os_type") or "",
        os_version=fields.get("os_version") or "",
        cpu_cores=fields.get("cpu_cores"),
        memory_gb=fields.get("memory_gb"),
        server_type="VIRTUAL" if fields.get("_is_virtual") else (fields.get("server_type") or "physical"),
        tier=fields.get("tier") or "unknown",
        status="OFFLINE",
        connection_config=cfg,
    )
    db.add(srv)
    db.flush()
    return "created"


def _upsert_exadata_from_ci(db: Session, fields: Dict[str, Any], cfg: Dict[str, Any]) -> str:
    name = fields["name"]
    ip = fields.get("ip_address")
    host = fields.get("hostname") or name
    ci_type = (fields.get("_ci_type") or "").lower()
    ucmdb_id = fields.get("_ucmdb_id")
    patterns = [p.lower() for p in (cfg.get("exadata_node_name_patterns") or [])]
    is_node_like = any(p in name.lower() for p in patterns) or any(
        x in ci_type for x in ("cell", "storage", "compute", "unix", "node")
    )
    is_rack_like = any(x in ci_type for x in ("exadata", "db_machine", "rack")) and not is_node_like
    now = datetime.now(timezone.utc)

    if is_rack_like or not is_node_like:
        rack = None
        if ucmdb_id:
            for r in db.query(ExadataRack).all():
                md = r.meta_data or {}
                if md.get("ucmdb_id") == ucmdb_id:
                    rack = r
                    break
        if not rack:
            rack = db.query(ExadataRack).filter(
                (ExadataRack.name == name) | (ExadataRack.hostname == host)
            ).first()
        if rack:
            rack.hostname = host or rack.hostname
            if ip:
                rack.ip_address = ip
            rack.model = fields.get("_model") or rack.model
            rack.datacenter = fields.get("_datacenter") or rack.datacenter
            md = dict(rack.meta_data or {})
            md.update({"ucmdb_id": ucmdb_id, "ucmdb_ci_type": fields.get("_ci_type"), "source": "ucmdb"})
            rack.meta_data = md
            rack.last_sync = now
            return "exadata_rack_updated"
        rack = ExadataRack(
            name=name, rack_name=name, hostname=host, ip_address=ip,
            model=fields.get("_model") or None, datacenter=fields.get("_datacenter") or None,
            status="unknown", connection_config={},
            meta_data={"ucmdb_id": ucmdb_id, "ucmdb_ci_type": fields.get("_ci_type"), "source": "ucmdb"},
            last_sync=now,
        )
        db.add(rack)
        db.flush()
        return "exadata_rack_created"

    rack_guess = re.sub(r"(db|cel|cell| Dom)\d+.*$", "", name, flags=re.I).rstrip("-_")
    if not rack_guess or rack_guess == name:
        rack_guess = name.rsplit("-", 1)[0] if "-" in name else f"{name}-rack"
    rack = db.query(ExadataRack).filter(ExadataRack.name == rack_guess).first()
    if not rack:
        rack = ExadataRack(
            name=rack_guess, rack_name=rack_guess, status="unknown", connection_config={},
            meta_data={"source": "ucmdb", "auto_created": True}, last_sync=now,
        )
        db.add(rack)
        db.flush()

    role = _guess_node_role(name, ci_type)
    node = None
    for n in list(rack.nodes or []):
        md = n.meta_data or {}
        if (ucmdb_id and md.get("ucmdb_id") == ucmdb_id) or n.name == name or (ip and n.ip_address == ip):
            node = n
            break
    if not node:
        node = db.query(ExadataNode).filter(ExadataNode.rack_id == rack.id, ExadataNode.name == name).first()

    server_id = None
    if role == ExadataNodeRole.COMPUTE_NODE:
        _upsert_physical(db, {**fields, "_is_virtual": False, "server_type": "physical"}, skip_virtual=False)
        srv = find_existing_server(db, ip=ip, hostname=host, name=name)
        if srv:
            server_id = srv.id

    if node:
        node.hostname = host
        if ip:
            node.ip_address = ip
        node.role = role
        node.cpu_cores = fields.get("cpu_cores") or node.cpu_cores
        node.memory_gb = fields.get("memory_gb") or node.memory_gb
        if server_id:
            node.server_id = server_id
        md = dict(node.meta_data or {})
        md.update({"ucmdb_id": ucmdb_id, "ucmdb_ci_type": fields.get("_ci_type"), "source": "ucmdb"})
        node.meta_data = md
        return "exadata_node_updated"

    node = ExadataNode(
        rack_id=rack.id, role=role, name=name, hostname=host, ip_address=ip,
        cpu_cores=fields.get("cpu_cores"), memory_gb=fields.get("memory_gb"),
        server_id=server_id, status="unknown",
        meta_data={"ucmdb_id": ucmdb_id, "ucmdb_ci_type": fields.get("_ci_type"), "source": "ucmdb"},
    )
    db.add(node)
    return "exadata_node_created"


def sync_from_ucmdb(db: Session, *, dry_run: bool = False) -> Dict[str, Any]:
    cfg = load_connection(db)
    if not cfg.get("base_url") or not cfg.get("username") or not cfg.get("password"):
        raise UcmdbClientError("uCMDB bağlantı ayarları eksik (URL / kullanıcı / parola)")

    client = _client_from_cfg(cfg)
    client.authenticate()

    stats: Dict[str, Any] = {
        "physical_fetched": 0, "exadata_fetched": 0,
        "created": 0, "updated": 0, "skipped": 0,
        "exadata_rack_created": 0, "exadata_rack_updated": 0,
        "exadata_node_created": 0, "exadata_node_updated": 0,
        "errors": [], "dry_run": dry_run,
    }
    skip_virtual = not bool(cfg.get("sync_virtual"))

    physical_cis: List[Dict[str, Any]] = []
    if cfg.get("sync_physical", True):
        try:
            physical_cis = client.fetch_cis(
                ci_types=list(cfg.get("physical_ci_types") or ["node"]),
                tql_name=(cfg.get("physical_tql") or None),
            )
            stats["physical_fetched"] = len(physical_cis)
        except Exception as e:
            logger.exception("physical fetch failed")
            stats["errors"].append(f"Fiziksel CI çekilemedi: {e}")

    exadata_cis: List[Dict[str, Any]] = []
    if cfg.get("sync_exadata", True):
        try:
            tql = cfg.get("exadata_tql") or None
            types = list(cfg.get("exadata_ci_types") or [])
            if tql or types:
                exadata_cis = client.fetch_cis(ci_types=types or ["node"], tql_name=tql)
            patterns = list(cfg.get("exadata_node_name_patterns") or [])
            for ci in physical_cis:
                if _is_exadata_ci(ci, patterns, types):
                    exadata_cis.append(ci)
            seen = set()
            uniq = []
            for ci in exadata_cis:
                key = _prop(ci, "ucmdb_id", "ucmdbId", "global_id", "name", "primary_ip_address")
                if key in seen:
                    continue
                seen.add(key)
                uniq.append(ci)
            exadata_cis = uniq
            stats["exadata_fetched"] = len(exadata_cis)
        except Exception as e:
            logger.exception("exadata fetch failed")
            stats["errors"].append(f"Exadata CI çekilemedi: {e}")

    if dry_run:
        stats["preview_physical"] = [
            {"name": _ci_to_server_fields(ci)["name"], "ip": _ci_to_server_fields(ci).get("ip_address"),
             "os": _ci_to_server_fields(ci).get("os_type"), "ci_type": _ci_to_server_fields(ci).get("_ci_type")}
            for ci in physical_cis[:30]
        ]
        stats["preview_exadata"] = [
            {"name": _ci_to_server_fields(ci)["name"], "ip": _ci_to_server_fields(ci).get("ip_address"),
             "ci_type": _ci_to_server_fields(ci).get("_ci_type")}
            for ci in exadata_cis[:30]
        ]
        return stats

    exadata_ids = set()
    for ci in exadata_cis:
        fields = _ci_to_server_fields(ci)
        exadata_ids.add(fields.get("_ucmdb_id") or fields["name"])
        try:
            action = _upsert_exadata_from_ci(db, fields, cfg)
            stats[action] = stats.get(action, 0) + 1
        except Exception as e:
            stats["errors"].append(f"Exadata {fields.get('name')}: {e}")

    for ci in physical_cis:
        fields = _ci_to_server_fields(ci)
        key = fields.get("_ucmdb_id") or fields["name"]
        if key in exadata_ids and _is_exadata_ci(
            ci, list(cfg.get("exadata_node_name_patterns") or []), list(cfg.get("exadata_ci_types") or [])
        ):
            stats["skipped"] += 1
            continue
        try:
            action = _upsert_physical(db, fields, skip_virtual=skip_virtual)
            if action == "created":
                stats["created"] += 1
            elif action == "updated":
                stats["updated"] += 1
            else:
                stats["skipped"] += 1
        except Exception as e:
            stats["errors"].append(f"Fiziksel {fields.get('name')}: {e}")

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise UcmdbClientError(f"DB commit hatası: {e}") from e
    return stats
