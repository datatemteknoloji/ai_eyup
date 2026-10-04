"""Centrify Senkronizasyon Servisi — WinRM → DB.

Kapsam: zone, rol (+login bayrakları), komut, rol↔komut üyeliği,
assignment, computer, unix profil, computer role.

WinRM yoğunluğu:
- Tercihen zone başına tek `list_zone_inventory` çağrısı
- Global throttle (`sync_throttle`) + zone arası bekleme
- Inventory başarısızsa parçalı fallback (yine throttle'lı)
"""
from __future__ import annotations

import hashlib
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)


def _hash(data: dict) -> str:
    canonical = json.dumps(data, sort_keys=True, default=str)
    return hashlib.sha256(canonical.encode()).hexdigest()[:16]


def _parse_uuid(guid_str: str) -> Optional[uuid.UUID]:
    if not guid_str:
        return None
    try:
        return uuid.UUID(str(guid_str).strip("{}"))
    except (ValueError, AttributeError):
        return None


def _as_bool(val: Any, default: bool = False) -> bool:
    if val is None or val == "":
        return default
    if isinstance(val, bool):
        return val
    s = str(val).strip().lower()
    if s in ("1", "true", "yes", "y", "on"):
        return True
    if s in ("0", "false", "no", "n", "off"):
        return False
    return default


def _parse_rights(raw: Any) -> list[str]:
    if raw is None:
        return []
    if isinstance(raw, list):
        return [str(x).strip() for x in raw if str(x).strip()]
    s = str(raw).strip()
    if not s:
        return []
    if "||" in s:
        return [p.strip() for p in s.split("||") if p.strip()]
    if "|" in s:
        return [p.strip() for p in s.split("|") if p.strip()]
    return [s]


def _parse_dt(val: Any) -> Optional[datetime]:
    if val is None or val == "":
        return None
    if isinstance(val, datetime):
        return val if val.tzinfo else val.replace(tzinfo=timezone.utc)
    s = str(val).strip()
    if not s or s.lower() in ("none", "null"):
        return None
    try:
        # ISO / ADEdit varyasyonları
        s2 = s.replace("Z", "+00:00")
        dt = datetime.fromisoformat(s2)
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def _norm_scope(scope: str) -> str:
    s = (scope or "zone").strip().lower()
    if s in ("computer", "host", "machine"):
        return "computer"
    return "zone"


def _norm_assignee_type(t: str) -> str:
    s = (t or "user").strip().lower()
    if "group" in s:
        return "group"
    if "computer" in s:
        return "computer_role"
    return "user"


def _fetch_zone_inventory(adapter, zone_dn: str) -> dict:
    """Inventory tek çağrı; yoksa / hata olursa parçalı fallback."""
    if hasattr(adapter, "list_zone_inventory"):
        try:
            inv = adapter.list_zone_inventory(zone_dn)
            if isinstance(inv, dict) and not inv.get("error"):
                # En azından roller veya komutlar geldiyse kabul et
                if any(inv.get(k) for k in ("roles", "commands", "assignments", "computers")):
                    return {
                        "roles": inv.get("roles") or [],
                        "commands": inv.get("commands") or [],
                        "assignments": inv.get("assignments") or [],
                        "computers": inv.get("computers") or [],
                        "unix_profiles": inv.get("unix_profiles") or [],
                        "computer_roles": inv.get("computer_roles") or [],
                        "mode": "inventory",
                    }
        except Exception as exc:
            logger.warning("list_zone_inventory başarısız (%s): %s — fallback", zone_dn, exc)

    roles = []
    commands = []
    assignments = []
    computers = []
    unix_profiles = []
    computer_roles = []
    errors = []

    buckets: dict[str, list] = {
        "roles": roles,
        "commands": commands,
        "assignments": assignments,
        "computers": computers,
        "unix_profiles": unix_profiles,
        "computer_roles": computer_roles,
    }
    fetchers = [
        ("roles", lambda: adapter.list_roles(zone_dn)),
        ("commands", lambda: adapter.list_commands(zone_dn)),
        ("assignments", lambda: adapter.list_role_assignments(zone_dn)),
        ("computers", lambda: getattr(adapter, "list_computers", lambda _z: [])(zone_dn)),
        ("unix_profiles", lambda: getattr(adapter, "list_unix_profiles", lambda _z: [])(zone_dn)),
        ("computer_roles", lambda: adapter.list_computer_roles(zone_dn)),
    ]
    for label, fn in fetchers:
        try:
            data = fn()
            if isinstance(data, dict):
                data = [data]
            buckets[label] = list(data or [])
        except Exception as exc:
            errors.append(f"{label}: {exc}")
            logger.warning("Zone %s %s fallback hata: %s", zone_dn, label, exc)
    roles = buckets["roles"]
    commands = buckets["commands"]
    assignments = buckets["assignments"]
    computers = buckets["computers"]
    unix_profiles = buckets["unix_profiles"]
    computer_roles = buckets["computer_roles"]

    # Rights eksik roller için get_role_detail (seyrek; throttle zaten adapter'da)
    if hasattr(adapter, "get_role_detail"):
        for r in roles:
            rights = _parse_rights(r.get("rights"))
            if rights:
                continue
            name = r.get("name")
            if not name:
                continue
            try:
                detail = adapter.get_role_detail(zone_dn, name) or {}
                r["rights"] = detail.get("rights") or []
                for k in (
                    "password_login_allowed", "sso_login_allowed", "require_mfa",
                    "description", "ad_guid", "ad_dn", "is_system_role",
                ):
                    if detail.get(k) not in (None, "") and not r.get(k):
                        r[k] = detail.get(k)
            except Exception as exc:
                errors.append(f"role_detail {name}: {exc}")

    return {
        "roles": roles,
        "commands": commands,
        "assignments": assignments,
        "computers": computers,
        "unix_profiles": unix_profiles,
        "computer_roles": computer_roles,
        "mode": "fallback",
        "errors": errors,
    }


def _apply_role_login_flags(role_obj, rdata: dict) -> None:
    role_obj.password_login_allowed = _as_bool(rdata.get("password_login_allowed"), role_obj.password_login_allowed or False)
    role_obj.sso_login_allowed = _as_bool(rdata.get("sso_login_allowed"), role_obj.sso_login_allowed or False)
    role_obj.require_mfa = _as_bool(rdata.get("require_mfa"), role_obj.require_mfa or False)
    if rdata.get("allow_local_accounts") not in (None, ""):
        role_obj.allow_local_accounts = _as_bool(rdata.get("allow_local_accounts"))
    if rdata.get("non_restricted_shell") not in (None, ""):
        role_obj.non_restricted_shell = _as_bool(rdata.get("non_restricted_shell"))
    if rdata.get("user_visible") not in (None, ""):
        role_obj.user_visible = _as_bool(rdata.get("user_visible"), True)
    if rdata.get("console_login_allowed") not in (None, ""):
        role_obj.console_login_allowed = _as_bool(rdata.get("console_login_allowed"))
    if rdata.get("remote_login_allowed") not in (None, ""):
        role_obj.remote_login_allowed = _as_bool(rdata.get("remote_login_allowed"))
    if rdata.get("powershell_remote_allowed") not in (None, ""):
        role_obj.powershell_remote_allowed = _as_bool(rdata.get("powershell_remote_allowed"))
    if rdata.get("rescue_login_allowed") not in (None, ""):
        role_obj.rescue_login_allowed = _as_bool(rdata.get("rescue_login_allowed"))
    audit = rdata.get("audit_level")
    if audit:
        role_obj.audit_level = str(audit)[:30]


def _parent_zone_chain(db, zone_id: int) -> list[int]:
    """Child → parent zinciri (önce kendi zone). Tepeden tanımlı komut eşlemesi için."""
    from app.models.centrify_zone import CentrifyZone
    chain = [zone_id]
    seen = {zone_id}
    current = db.query(CentrifyZone).filter_by(id=zone_id).first()
    while current and current.parent_zone_id and current.parent_zone_id not in seen:
        chain.append(current.parent_zone_id)
        seen.add(current.parent_zone_id)
        current = db.query(CentrifyZone).filter_by(id=current.parent_zone_id).first()
    return chain


def _resolve_command_id(db, zone_id: int, right_name: str, cmd_cache: dict) -> Optional[int]:
    """Right adını komut id'sine çevir — önce zone, sonra parent zinciri."""
    key = (zone_id, right_name.lower())
    if key in cmd_cache:
        return cmd_cache[key]
    from app.models.centrify_zone import CentrifyCommand
    for zid in _parent_zone_chain(db, zone_id):
        cmd = (
            db.query(CentrifyCommand)
            .filter(
                CentrifyCommand.zone_id == zid,
                CentrifyCommand.deleted_in_ad.is_(False),
                CentrifyCommand.name.ilike(right_name),
            )
            .first()
        )
        if cmd:
            cmd_cache[key] = cmd.id
            return cmd.id
    cmd_cache[key] = None
    return None


def run_full_sync(adapter) -> dict:
    """Tam senkronizasyon — tüm zone nesneleri + üyelikler."""
    from app.services.centrify.database import get_centrify_thread_session, create_centrify_tables
    from app.services.centrify.sync_throttle import pause_between_zones
    from app.models.centrify_zone import (
        CentrifyZone,
        CentrifyRole,
        CentrifyCommand,
        CentrifyRoleCommand,
        CentrifyRoleAssignment,
        CentrifyComputer,
        CentrifyUnixProfile,
        CentrifyComputerRole,
    )

    create_centrify_tables()
    db = get_centrify_thread_session()
    if db is None:
        return {"ok": False, "errors": ["Centrify DB erişilemiyor"]}

    errors: list[str] = []
    stats = {
        "zones_synced": 0,
        "roles_synced": 0,
        "commands_synced": 0,
        "role_command_links": 0,
        "assignments_synced": 0,
        "computers_synced": 0,
        "unix_profiles_synced": 0,
        "computer_roles_synced": 0,
        "inventory_mode_zones": 0,
        "fallback_mode_zones": 0,
    }
    now = datetime.now(timezone.utc)

    try:
        try:
            raw_zones = adapter.list_zones()
        except Exception as exc:
            return {"ok": False, "errors": [f"Zone listesi alınamadı: {exc}"]}

        zone_map: dict[str, int] = {}  # ad_dn → id
        zone_id_by_name: dict[str, int] = {}

        for zdata in raw_zones or []:
            ad_guid = _parse_uuid(zdata.get("ad_guid", ""))
            if ad_guid is None:
                errors.append(f"Zone GUID parse edilemedi: {zdata.get('name', '?')}")
                continue
            existing = db.query(CentrifyZone).filter_by(ad_guid=ad_guid).first()
            new_hash = _hash(zdata)
            if existing:
                if existing.source_hash != new_hash:
                    existing.name = zdata.get("name", existing.name)
                    existing.ad_dn = zdata.get("ad_dn", existing.ad_dn)
                    existing.zone_type = zdata.get("zone_type", existing.zone_type)
                    existing.description = zdata.get("description")
                    existing.source_hash = new_hash
                    existing.updated_at = now
                existing.last_synced_at = now
                existing.last_seen_in_ad = now
                existing.deleted_in_ad = False
                zone_map[existing.ad_dn] = existing.id
                zone_id_by_name[existing.name.lower()] = existing.id
            else:
                zone = CentrifyZone(
                    ad_guid=ad_guid,
                    ad_dn=zdata.get("ad_dn", ""),
                    name=zdata.get("name", ""),
                    zone_type=zdata.get("zone_type", "hierarchical"),
                    description=zdata.get("description"),
                    management_state="imported_readonly",
                    source_hash=new_hash,
                    last_synced_at=now,
                    last_seen_in_ad=now,
                )
                db.add(zone)
                db.flush()
                zone_map[zone.ad_dn] = zone.id
                zone_id_by_name[zone.name.lower()] = zone.id
            stats["zones_synced"] += 1

        for zdata in raw_zones or []:
            parent_dn = zdata.get("parent_zone_dn", "")
            ad_dn = zdata.get("ad_dn", "")
            if parent_dn and ad_dn in zone_map and parent_dn in zone_map:
                zone = db.query(CentrifyZone).filter_by(id=zone_map[ad_dn]).first()
                if zone:
                    zone.parent_zone_id = zone_map[parent_dn]

        db.commit()

        # Parent-first sıralama: tepeden tanımlı komutlar önce gelsin
        depth_cache: dict[int, int] = {}

        def _zone_depth(zid: int) -> int:
            if zid in depth_cache:
                return depth_cache[zid]
            z = db.query(CentrifyZone).filter_by(id=zid).first()
            if not z or not z.parent_zone_id:
                depth_cache[zid] = 0
            else:
                depth_cache[zid] = 1 + _zone_depth(z.parent_zone_id)
            return depth_cache[zid]

        zones_ordered = sorted(zone_map.items(), key=lambda kv: (_zone_depth(kv[1]), kv[0]))

        computer_by_dn: dict[str, int] = {}
        computer_by_name: dict[str, int] = {}
        cmd_cache: dict = {}

        first_zone = True
        for zone_dn, zone_id in zones_ordered:
            if not first_zone:
                pause_between_zones()
            first_zone = False

            inv = _fetch_zone_inventory(adapter, zone_dn)
            if inv.get("mode") == "inventory":
                stats["inventory_mode_zones"] += 1
            else:
                stats["fallback_mode_zones"] += 1
            for e in inv.get("errors") or []:
                errors.append(f"{zone_dn}: {e}")

            seen_cmd_guids: set[uuid.UUID] = set()
            seen_role_guids: set[uuid.UUID] = set()
            seen_assign_guids: set[uuid.UUID] = set()
            seen_comp_guids: set[uuid.UUID] = set()
            seen_unix_keys: set[str] = set()
            seen_cr_guids: set[uuid.UUID] = set()

            # ── Commands ──
            for cdata in inv.get("commands") or []:
                ad_guid = _parse_uuid(cdata.get("ad_guid", ""))
                if ad_guid is None:
                    # GUID yoksa name+zone ile sözde GUID
                    name = cdata.get("name") or ""
                    if not name:
                        continue
                    ad_guid = uuid.uuid5(uuid.NAMESPACE_DNS, f"centrify-cmd:{zone_id}:{name}")
                seen_cmd_guids.add(ad_guid)
                existing = db.query(CentrifyCommand).filter_by(ad_guid=ad_guid).first()
                new_hash = _hash(cdata)
                if existing:
                    existing.name = cdata.get("name", existing.name)
                    existing.ad_dn = cdata.get("ad_dn") or existing.ad_dn
                    existing.command_path = cdata.get("command_path")
                    existing.match_type = cdata.get("match_type")
                    existing.run_as_user = cdata.get("run_as_user") or "root"
                    existing.run_as_group = cdata.get("run_as_group")
                    existing.auth_type = cdata.get("auth_type") or "password"
                    existing.description = cdata.get("description")
                    existing.source_hash = new_hash
                    existing.updated_at = now
                    existing.last_synced_at = now
                    existing.last_seen_in_ad = now
                    existing.deleted_in_ad = False
                    existing.zone_id = zone_id
                else:
                    db.add(CentrifyCommand(
                        zone_id=zone_id,
                        ad_guid=ad_guid,
                        ad_dn=cdata.get("ad_dn") or "",
                        name=cdata.get("name") or "",
                        command_path=cdata.get("command_path"),
                        match_type=cdata.get("match_type"),
                        run_as_user=cdata.get("run_as_user") or "root",
                        run_as_group=cdata.get("run_as_group"),
                        auth_type=cdata.get("auth_type") or "password",
                        description=cdata.get("description"),
                        management_state="imported_readonly",
                        source_hash=new_hash,
                        last_synced_at=now,
                        last_seen_in_ad=now,
                    ))
                stats["commands_synced"] += 1

            db.flush()

            # ── Computers (assignment scope için önce) ──
            for cdata in inv.get("computers") or []:
                ad_guid = _parse_uuid(cdata.get("ad_guid", ""))
                name = cdata.get("name") or ""
                if ad_guid is None:
                    if not name:
                        continue
                    ad_guid = uuid.uuid5(uuid.NAMESPACE_DNS, f"centrify-comp:{zone_id}:{name}")
                seen_comp_guids.add(ad_guid)
                existing = db.query(CentrifyComputer).filter_by(ad_guid=ad_guid).first()
                new_hash = _hash(cdata)
                if existing:
                    existing.name = name or existing.name
                    existing.fqdn = cdata.get("fqdn") or existing.fqdn
                    existing.os_type = cdata.get("os_type") or existing.os_type
                    existing.agent_version = cdata.get("agent_version") or existing.agent_version
                    existing.ad_dn = cdata.get("ad_dn") or existing.ad_dn
                    existing.source_hash = new_hash
                    existing.updated_at = now
                    existing.last_synced_at = now
                    existing.last_seen_in_ad = now
                    existing.deleted_in_ad = False
                    existing.zone_id = zone_id
                    comp = existing
                else:
                    comp = CentrifyComputer(
                        zone_id=zone_id,
                        ad_guid=ad_guid,
                        ad_dn=cdata.get("ad_dn") or "",
                        name=name,
                        fqdn=cdata.get("fqdn"),
                        os_type=cdata.get("os_type"),
                        agent_version=cdata.get("agent_version"),
                        management_state="imported_readonly",
                        source_hash=new_hash,
                        last_synced_at=now,
                        last_seen_in_ad=now,
                    )
                    db.add(comp)
                    db.flush()
                if comp.ad_dn:
                    computer_by_dn[comp.ad_dn.lower()] = comp.id
                if comp.name:
                    computer_by_name[comp.name.lower()] = comp.id
                if comp.fqdn:
                    computer_by_name[comp.fqdn.lower()] = comp.id
                stats["computers_synced"] += 1

            db.flush()

            # ── Roles + rights links ──
            for rdata in inv.get("roles") or []:
                ad_guid = _parse_uuid(rdata.get("ad_guid", ""))
                name = rdata.get("name") or ""
                if ad_guid is None:
                    if not name:
                        continue
                    ad_guid = uuid.uuid5(uuid.NAMESPACE_DNS, f"centrify-role:{zone_id}:{name}")
                seen_role_guids.add(ad_guid)
                existing = db.query(CentrifyRole).filter_by(ad_guid=ad_guid).first()
                new_hash = _hash({k: v for k, v in rdata.items() if k != "rights"})
                if existing:
                    existing.name = name or existing.name
                    existing.ad_dn = rdata.get("ad_dn") or existing.ad_dn
                    existing.description = rdata.get("description")
                    existing.is_system_role = _as_bool(rdata.get("is_system_role"))
                    _apply_role_login_flags(existing, rdata)
                    existing.source_hash = new_hash
                    existing.updated_at = now
                    existing.last_synced_at = now
                    existing.last_seen_in_ad = now
                    existing.deleted_in_ad = False
                    existing.zone_id = zone_id
                    role = existing
                else:
                    role = CentrifyRole(
                        zone_id=zone_id,
                        ad_guid=ad_guid,
                        ad_dn=rdata.get("ad_dn") or "",
                        name=name,
                        description=rdata.get("description"),
                        is_system_role=_as_bool(rdata.get("is_system_role")),
                        management_state="imported_readonly",
                        source_hash=new_hash,
                        last_synced_at=now,
                        last_seen_in_ad=now,
                    )
                    _apply_role_login_flags(role, rdata)
                    db.add(role)
                    db.flush()
                stats["roles_synced"] += 1

                # Role ↔ command membership (replace set)
                rights = _parse_rights(rdata.get("rights"))
                desired_cmd_ids: set[int] = set()
                for right in rights:
                    cid = _resolve_command_id(db, zone_id, right, cmd_cache)
                    if cid:
                        desired_cmd_ids.add(cid)
                    else:
                        errors.append(f"Right eşleşmedi: zone={zone_id} role={name} right={right}")

                existing_links = (
                    db.query(CentrifyRoleCommand).filter_by(role_id=role.id).all()
                )
                existing_ids = {l.command_id for l in existing_links}
                for lid in existing_ids - desired_cmd_ids:
                    link = next(l for l in existing_links if l.command_id == lid)
                    db.delete(link)
                for cid in desired_cmd_ids - existing_ids:
                    db.add(CentrifyRoleCommand(role_id=role.id, command_id=cid))
                    stats["role_command_links"] += 1
                stats["role_command_links"] += len(desired_cmd_ids & existing_ids)

            db.flush()

            # ── Assignments ──
            role_by_name = {
                r.name.lower(): r.id
                for r in db.query(CentrifyRole).filter_by(zone_id=zone_id, deleted_in_ad=False).all()
            }
            # Parent zone rollerine de atama olabilir
            for zid in _parent_zone_chain(db, zone_id)[1:]:
                for r in db.query(CentrifyRole).filter_by(zone_id=zid, deleted_in_ad=False).all():
                    role_by_name.setdefault(r.name.lower(), r.id)

            for adata in inv.get("assignments") or []:
                role_name = (adata.get("role_name") or "").strip()
                role_id = role_by_name.get(role_name.lower())
                if not role_id:
                    errors.append(f"Assignment rol bulunamadı: {role_name} @ {zone_dn}")
                    continue
                ad_guid = _parse_uuid(adata.get("ad_guid", ""))
                if ad_guid is None:
                    key = f"{zone_id}:{role_name}:{adata.get('assignee_dn')}:{adata.get('scope_dn')}"
                    ad_guid = uuid.uuid5(uuid.NAMESPACE_DNS, f"centrify-ra:{key}")
                seen_assign_guids.add(ad_guid)
                scope_type = _norm_scope(adata.get("scope_type", "zone"))
                scope_dn = (adata.get("scope_dn") or "").strip()
                computer_id = None
                if scope_type == "computer":
                    computer_id = computer_by_dn.get(scope_dn.lower()) if scope_dn else None
                    if computer_id is None and scope_dn:
                        # CN=host,... veya kısa ad
                        short = scope_dn.split(",")[0].replace("CN=", "").strip()
                        computer_id = computer_by_name.get(short.lower())
                existing = db.query(CentrifyRoleAssignment).filter_by(ad_guid=ad_guid).first()
                new_hash = _hash(adata)
                payload = dict(
                    zone_id=zone_id,
                    computer_id=computer_id,
                    role_id=role_id,
                    assignee_type=_norm_assignee_type(adata.get("assignee_type", "user")),
                    assignee_dn=adata.get("assignee_dn") or "",
                    assignee_name=adata.get("assignee_name") or "",
                    scope_type=scope_type,
                    scope_dn=scope_dn or None,
                    start_time=_parse_dt(adata.get("start_time")),
                    end_time=_parse_dt(adata.get("end_time")),
                    source_hash=new_hash,
                    last_synced_at=now,
                    last_seen_in_ad=now,
                    deleted_in_ad=False,
                    management_state="imported_readonly",
                )
                if existing:
                    for k, v in payload.items():
                        setattr(existing, k, v)
                    existing.updated_at = now
                    existing.ad_dn = adata.get("ad_dn") or existing.ad_dn
                else:
                    db.add(CentrifyRoleAssignment(
                        ad_guid=ad_guid,
                        ad_dn=adata.get("ad_dn"),
                        **payload,
                    ))
                stats["assignments_synced"] += 1

            # ── UNIX profiles ──
            for udata in inv.get("unix_profiles") or []:
                uname = (udata.get("user_name") or "").strip()
                udn = (udata.get("user_dn") or "").strip() or uname
                if not uname:
                    continue
                key = f"{zone_id}:{udn.lower()}"
                seen_unix_keys.add(key)
                existing = (
                    db.query(CentrifyUnixProfile)
                    .filter_by(zone_id=zone_id, user_dn=udn)
                    .first()
                )
                if existing is None:
                    existing = (
                        db.query(CentrifyUnixProfile)
                        .filter_by(zone_id=zone_id, user_name=uname)
                        .first()
                    )
                new_hash = _hash(udata)
                uid = udata.get("uid")
                gid = udata.get("gid")
                try:
                    uid_i = int(uid) if uid not in (None, "") else None
                except ValueError:
                    uid_i = None
                try:
                    gid_i = int(gid) if gid not in (None, "") else None
                except ValueError:
                    gid_i = None
                if existing:
                    existing.user_name = uname
                    existing.user_dn = udn
                    existing.uid = uid_i
                    existing.gid = gid_i
                    existing.home_dir = udata.get("home_dir")
                    existing.shell = udata.get("shell")
                    existing.gecos = udata.get("gecos")
                    existing.enabled = _as_bool(udata.get("enabled"), True)
                    existing.source_hash = new_hash
                    existing.last_synced_at = now
                    existing.updated_at = now
                else:
                    db.add(CentrifyUnixProfile(
                        zone_id=zone_id,
                        user_dn=udn,
                        user_name=uname,
                        uid=uid_i,
                        gid=gid_i,
                        home_dir=udata.get("home_dir"),
                        shell=udata.get("shell"),
                        gecos=udata.get("gecos"),
                        enabled=_as_bool(udata.get("enabled"), True),
                        source_hash=new_hash,
                        last_synced_at=now,
                    ))
                stats["unix_profiles_synced"] += 1

            # ── Computer roles ──
            for crdata in inv.get("computer_roles") or []:
                ad_guid = _parse_uuid(crdata.get("ad_guid", ""))
                name = crdata.get("name") or ""
                if ad_guid is None:
                    if not name:
                        continue
                    ad_guid = uuid.uuid5(uuid.NAMESPACE_DNS, f"centrify-cr:{zone_id}:{name}")
                seen_cr_guids.add(ad_guid)
                existing = db.query(CentrifyComputerRole).filter_by(ad_guid=ad_guid).first()
                new_hash = _hash(crdata)
                if existing:
                    existing.name = name or existing.name
                    existing.description = crdata.get("description")
                    existing.ad_dn = crdata.get("ad_dn") or existing.ad_dn
                    existing.source_hash = new_hash
                    existing.last_synced_at = now
                    existing.last_seen_in_ad = now
                    existing.deleted_in_ad = False
                    existing.zone_id = zone_id
                    existing.updated_at = now
                else:
                    db.add(CentrifyComputerRole(
                        zone_id=zone_id,
                        ad_guid=ad_guid,
                        ad_dn=crdata.get("ad_dn") or "",
                        name=name,
                        description=crdata.get("description"),
                        management_state="imported_readonly",
                        source_hash=new_hash,
                        last_synced_at=now,
                        last_seen_in_ad=now,
                    ))
                stats["computer_roles_synced"] += 1

            # Soft-delete: bu sync'te görülmeyen zone nesneleri
            if seen_cmd_guids:
                for row in db.query(CentrifyCommand).filter_by(zone_id=zone_id, deleted_in_ad=False).all():
                    if row.ad_guid not in seen_cmd_guids:
                        row.deleted_in_ad = True
                        row.updated_at = now
            if seen_role_guids:
                for row in db.query(CentrifyRole).filter_by(zone_id=zone_id, deleted_in_ad=False).all():
                    if row.ad_guid not in seen_role_guids:
                        row.deleted_in_ad = True
                        row.updated_at = now
            if seen_assign_guids:
                for row in db.query(CentrifyRoleAssignment).filter_by(zone_id=zone_id, deleted_in_ad=False).all():
                    if row.ad_guid and row.ad_guid not in seen_assign_guids:
                        row.deleted_in_ad = True
                        row.updated_at = now
            if seen_comp_guids:
                for row in db.query(CentrifyComputer).filter_by(zone_id=zone_id, deleted_in_ad=False).all():
                    if row.ad_guid not in seen_comp_guids:
                        row.deleted_in_ad = True
                        row.updated_at = now
            if seen_cr_guids:
                for row in db.query(CentrifyComputerRole).filter_by(zone_id=zone_id, deleted_in_ad=False).all():
                    if row.ad_guid not in seen_cr_guids:
                        row.deleted_in_ad = True
                        row.updated_at = now

            db.commit()
            logger.info(
                "Centrify zone sync OK zone_id=%s mode=%s roles=%s cmds=%s assigns=%s hosts=%s",
                zone_id, inv.get("mode"),
                len(inv.get("roles") or []),
                len(inv.get("commands") or []),
                len(inv.get("assignments") or []),
                len(inv.get("computers") or []),
            )

        return {"ok": len(errors) == 0, **stats, "errors": errors[:200]}

    except Exception as exc:
        db.rollback()
        logger.exception("Centrify sync hatası")
        return {"ok": False, "errors": [str(exc)], **stats}
    finally:
        db.close()
