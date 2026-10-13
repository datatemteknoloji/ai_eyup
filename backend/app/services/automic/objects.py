"""Nesne başlığı (OH) ve script sürümleri (OT) — modül DB önbelleği + kaynak okuma."""
from __future__ import annotations
from app.services.automic.errors import note_error

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.automic import (
    AutomicCollectorState,
    AutomicObjectHeader,
    AutomicObjectScriptVersion,
    AutomicObjectUsage,
    AutomicSystem,
)

from .defaults import effective_settings
from .masking import mask_text
from .source.base import SourceError
from .source.factory import build_source

logger = logging.getLogger(__name__)


def _iso(v: Optional[datetime]) -> Optional[str]:
    return v.isoformat() if v else None


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _header_dict(h: AutomicObjectHeader) -> Dict[str, Any]:
    return {
        "client": h.client, "object_name": h.object_name, "object_id": h.object_id,
        "object_type": h.object_type, "title": h.title, "folder": h.folder,
        "created_at": _iso(h.created_at), "created_by": h.created_by,
        "modified_at": _iso(h.modified_at), "modified_by": h.modified_by, "ert_sec": h.ert_sec,
        "seen_at": _iso(h.seen_at), "deleted_at": _iso(h.deleted_at),
    }


def upsert_header(db: Session, system_id: int, row: Dict[str, Any]) -> AutomicObjectHeader:
    client = int(row["client"])
    name = (row.get("object_name") or "").strip()
    h = db.get(AutomicObjectHeader, {"system_id": system_id, "client": client, "object_name": name})
    if h is None:
        h = AutomicObjectHeader(system_id=system_id, client=client, object_name=name)
        db.add(h)
    h.object_id = row.get("object_id")
    h.object_type = row.get("object_type")
    h.title = row.get("title")
    h.folder = row.get("folder")
    h.archive1 = (row.get("archive1") or None)
    h.archive2 = (row.get("archive2") or None)
    h.created_at = row.get("created_at")
    h.created_by = row.get("created_by")
    h.modified_at = row.get("modified_at")
    h.modified_by = row.get("modified_by")
    h.ert_sec = row.get("ert_sec")
    h.seen_at = _now()
    h.deleted_at = None
    return h


def sync_object_headers(db: Session, system: AutomicSystem, *, since: Optional[datetime] = None,
                        limit: int = 500, id_min: Optional[int] = None,
                        id_max: Optional[int] = None) -> Dict[str, Any]:
    """Kaynaktan OH başlıklarını OH_Idnr PK aralığıyla çeker (zaman taraması yok).

    id_min/id_max yoksa temkinli modda toplu senkron atlanır; tekil istek
    `ensure_header` / `fetch_object_header` (client+name) kullanır.
    """
    from .defaults import effective_settings

    g = effective_settings(system.settings).get("source_guard") or {}
    if id_min is None or id_max is None:
        if g.get("cautious_mode", True):
            return {"ok": True, "upserted": 0, "skipped": "cautious_mode_no_oh_scan",
                    "note": "OH toplu senkron için OH_Idnr aralığı gerekir; istek üzerine tekil çekilir."}
        return {"ok": True, "upserted": 0, "skipped": "oh_id_range_required"}
    with build_source(system) as src:
        if not src.supports("objects"):
            return {"ok": False, "capability": "unavailable", "upserted": 0}
        rows = src.fetch_object_headers(
            list(system.clients or []), limit=limit, id_min=int(id_min), id_max=int(id_max))
    n = 0
    for r in rows:
        if not r.get("object_name"):
            continue
        upsert_header(db, system.id, r)
        n += 1
    db.commit()
    return {"ok": True, "upserted": n}


def ensure_header(db: Session, system: AutomicSystem, client: int, name: str,
                  *, force: bool = False) -> Optional[Dict[str, Any]]:
    """OH başlığı — yalnız modül DB (object_header_by_name orta risk; canlı yasak)."""
    h = db.get(AutomicObjectHeader, {"system_id": system.id, "client": int(client), "object_name": name})
    return _header_dict(h) if h else None


def _content_hash(text_body: str) -> str:
    return hashlib.sha256(text_body.encode("utf-8", errors="replace")).hexdigest()


def _mask_script(system: AutomicSystem, text_body: str) -> str:
    settings = effective_settings(system.settings)
    return mask_text(text_body, settings.get("masking"))


def _persist_script_lines(
    db: Session, system: AutomicSystem, client: int, name: str, oid: int,
    lines: List[str], *, header: Optional[Dict[str, Any]] = None, keep: int = 10,
) -> AutomicObjectScriptVersion:
    """Maskele + hash ile sürüm yaz (collector veya canlı yolu)."""
    raw = "\n".join(lines)
    masked = _mask_script(system, raw)
    hsh = _content_hash(masked)
    latest = get_version(db, system, client, name)
    if latest and latest.content_hash == hsh:
        return latest
    ver_no = (latest.version_no + 1) if latest else 1
    mod = None
    if header and header.get("modified_at"):
        try:
            mod = datetime.fromisoformat(str(header["modified_at"]).replace("Z", "+00:00"))
        except Exception:
            mod = None
    row = AutomicObjectScriptVersion(
        system_id=system.id, client=int(client), object_name=name, object_id=int(oid),
        version_no=ver_no, content_hash=hsh, content=masked,
        line_count=masked.count("\n") + (1 if masked else 0),
        size_bytes=len(masked.encode("utf-8", errors="replace")),
        fetched_at=_now(), source_modified_at=mod,
    )
    db.add(row)
    db.flush()
    old = (db.query(AutomicObjectScriptVersion)
           .filter_by(system_id=system.id, client=int(client), object_name=name)
           .order_by(AutomicObjectScriptVersion.version_no.desc()).offset(keep).all())
    for o in old:
        db.delete(o)
    return row


def sync_scripts_chunk(db: Session, system: AutomicSystem, src, *,
                       id_min: int, id_max: int, max_objects: int = 20) -> Dict[str, Any]:
    """OH_Idnr aralığındaki değişen nesnelerin OT script'lerini modül DB'ye yazar (collector)."""
    if not src.supports("versions"):
        return {"ok": False, "upserted": 0, "skipped": "versions_unavailable"}
    keep = int((effective_settings(system.settings).get("retention") or {}).get("object_script_versions") or 10)
    rows = db.execute(text(
        "SELECT client, object_name, object_id, modified_at FROM automic_object_headers "
        "WHERE system_id = :sid AND object_id >= :lo AND object_id < :hi "
        "AND object_id IS NOT NULL AND deleted_at IS NULL "
        "ORDER BY object_id LIMIT 500"
    ), {"sid": system.id, "lo": int(id_min), "hi": int(id_max)}).all()
    n = 0
    for client, name, oid, mod in rows:
        if n >= max(1, int(max_objects)):
            break
        latest = get_version(db, system, int(client), name)
        needs = latest is None
        if latest and mod is not None:
            ref = latest.source_modified_at or latest.fetched_at
            m = mod if getattr(mod, "tzinfo", None) else (
                mod.replace(tzinfo=timezone.utc) if mod else None)
            if ref is None or (m and m > ref):
                needs = True
        if not needs:
            continue
        try:
            lines = src.fetch_object_script(int(oid))
        except SourceError as exc:
            note_error("objects.sync_scripts_chunk", exc)
            continue
        header = {"modified_at": mod.isoformat() if mod else None}
        _persist_script_lines(
            db, system, int(client), name, int(oid), lines, header=header, keep=keep)
        n += 1
    if n:
        db.commit()
    return {"ok": True, "upserted": n}


def list_versions(db: Session, system: AutomicSystem, client: int, name: str) -> List[Dict[str, Any]]:
    rows = (db.query(AutomicObjectScriptVersion)
            .filter_by(system_id=system.id, client=int(client), object_name=name)
            .order_by(AutomicObjectScriptVersion.version_no.desc()).all())
    return [{
        "version_no": r.version_no, "content_hash": r.content_hash, "line_count": r.line_count,
        "size_bytes": r.size_bytes, "fetched_at": _iso(r.fetched_at),
        "source_modified_at": _iso(r.source_modified_at),
    } for r in rows]


def get_version(db: Session, system: AutomicSystem, client: int, name: str,
                version_no: Optional[int] = None) -> Optional[AutomicObjectScriptVersion]:
    q = db.query(AutomicObjectScriptVersion).filter_by(
        system_id=system.id, client=int(client), object_name=name)
    if version_no is not None:
        return q.filter_by(version_no=int(version_no)).first()
    return q.order_by(AutomicObjectScriptVersion.version_no.desc()).first()


def fetch_and_store_script(db: Session, system: AutomicSystem, client: int, name: str,
                           *, force: bool = False, allow_live: Optional[bool] = None,
                           user_id: Optional[int] = None) -> Dict[str, Any]:
    """Script'i (politika izinliyse) kaynaktan alır, maskeler, hash ile sürümler."""
    from . import live_read

    header = ensure_header(db, system, client, name, force=force)
    oid = (header or {}).get("object_id")
    if not oid:
        for c in (system.clients or [client]):
            header = ensure_header(db, system, int(c), name, force=force)
            if header and header.get("object_id"):
                client = int(c)
                oid = header["object_id"]
                break
    if not oid:
        as_of = live_read.data_as_of(db, system.id)
        return {
            "ok": False,
            "error": "Nesne object_id modül DB'de yok (OH canlı okuma yasak — orta risk). "
                     "Collector OH senkronu veya nesne adı ile bekleyin.",
            "capability": "objects" if header is None else "partial",
            "data_source": "module_db", "as_of": as_of,
        }

    # Önbellekte varsa ve force değilse canlıya gitme
    latest = get_version(db, system, client, name)
    if latest and not force:
        as_of = live_read.data_as_of(db, system.id)
        return {
            "ok": True, "cached": True, "client": client, "object_name": name,
            "header": header, "version": {
                "version_no": latest.version_no, "content_hash": latest.content_hash,
                "line_count": latest.line_count, "size_bytes": latest.size_bytes,
                "fetched_at": _iso(latest.fetched_at),
            },
            "content": latest.content, "data_source": "module_db", "as_of": as_of,
            "freshness_note": f"Script modül DB sürümü; veriler {as_of or 'son senkron'} itibarıyla.",
        }

    keep = 10
    for s in [system]:
        r = (effective_settings(s.settings).get("retention") or {})
        keep = int(r.get("object_script_versions") or keep)

    # force = kaynaktan yenile talebi → allow_live=True (yine politika kapısından geçer)
    lr = live_read.call(
        db, system, "fetch_object_script", int(oid),
        allow_live=True if (force or allow_live is True) else allow_live,
        user_id=user_id, tool="automic_object",
    )
    if not lr.ok or lr.data is None:
        as_of = live_read.data_as_of(db, system.id)
        if latest:
            return {
                "ok": True, "cached": True, "client": client, "object_name": name,
                "header": header,
                "version": {
                    "version_no": latest.version_no, "content_hash": latest.content_hash,
                    "line_count": latest.line_count, "size_bytes": latest.size_bytes,
                    "fetched_at": _iso(latest.fetched_at),
                },
                "content": latest.content, "data_source": "module_db", "as_of": as_of,
                "freshness_note": lr.error or f"Canlı okuma yok; veriler {as_of} itibarıyla.",
            }
        return {
            "ok": False,
            "error": (
                lr.error
                or "Script modül DB'de yok. Canlı okuma kapalı/izinsiz; collector ağır pencerede "
                "OH_ModDate değişen nesnelerin OT metnini senkronlar."
            ),
            "code": lr.code, "data_source": "module_db", "as_of": as_of,
            "freshness_note": (
                f"Canlı okuma kapalı olduğu için script kaynaktan alınamadı; "
                f"son toplama {as_of or '—'}."
            ),
        }
    row = _persist_script_lines(
        db, system, client, name, int(oid), lr.data, header=header, keep=keep)
    db.commit()
    as_of = live_read.data_as_of(db, system.id)
    return {
        "ok": True, "cached": False, "client": client, "object_name": name,
        "header": header,
        "version": {
            "version_no": row.version_no, "content_hash": row.content_hash,
            "line_count": row.line_count, "size_bytes": row.size_bytes,
            "fetched_at": _iso(row.fetched_at),
        },
        "content": row.content, "data_source": "source_live", "as_of": as_of,
    }


def script_diff(db: Session, system: AutomicSystem, client: int, name: str,
                a: Optional[int] = None, b: Optional[int] = None) -> Dict[str, Any]:
    """İki sürüm arası satır farkı (unified benzeri, sınırlı)."""
    versions = list_versions(db, system, client, name)
    if len(versions) < 1:
        fetched = fetch_and_store_script(db, system, client, name)
        if not fetched.get("ok"):
            return fetched
        versions = list_versions(db, system, client, name)
    if len(versions) < 2 and a is None and b is None:
        ver = get_version(db, system, client, name)
        return {"ok": True, "object_name": name, "client": client,
                "a": None, "b": versions[0] if versions else None,
                "hunks": [], "note": "Karşılaştırılacak ikinci sürüm yok.",
                "content_b": ver.content if ver else ""}
    vb_no = b if b is not None else versions[0]["version_no"]
    va_no = a if a is not None else (versions[1]["version_no"] if len(versions) > 1 else None)
    vb = get_version(db, system, client, name, vb_no)
    va = get_version(db, system, client, name, va_no) if va_no is not None else None
    if not vb:
        return {"ok": False, "error": f"Sürüm {vb_no} bulunamadı."}
    lines_a = (va.content if va else "").splitlines()
    lines_b = vb.content.splitlines()
    import difflib
    diff = list(difflib.unified_diff(lines_a, lines_b, fromfile=f"v{va_no or 0}", tofile=f"v{vb_no}", lineterm=""))
    if len(diff) > 400:
        diff = diff[:400] + ["… (kırpıldı)"]
    return {
        "ok": True, "client": client, "object_name": name,
        "a": {"version_no": va.version_no, "content_hash": va.content_hash} if va else None,
        "b": {"version_no": vb.version_no, "content_hash": vb.content_hash},
        "diff": diff,
    }


def _jpp_synced_at(db: Session, system_id: int) -> Optional[datetime]:
    st = db.get(AutomicCollectorState, system_id)
    if st and st.jpp_synced_at:
        return st.jpp_synced_at
    row = db.execute(text(
        "SELECT MAX(seen_at) FROM automic_object_usage WHERE system_id = :sid"
    ), {"sid": system_id}).scalar()
    return row


def object_usage(db: Session, system: AutomicSystem, client: int, name: str,
                 *, depth: int = 1) -> Dict[str, Any]:
    """Usage/bağımlılık — yalnız modül DB (JPP senkron); kaynak isim taraması yok."""
    name = (name or "").strip()
    if not name:
        return {"ok": False, "error": "object_name gerekli"}
    synced = _jpp_synced_at(db, system.id)
    if synced is None:
        return {
            "ok": False, "error": "JPP kullanım verisi henüz senkron edilmedi "
            "(ağır iş penceresinde collector çeker).",
            "code": "jpp_not_synced", "synced_at": None,
        }
    nodes: List[Dict[str, Any]] = [{"id": name, "label": name, "kind": "object"}]
    edges: List[Dict[str, Any]] = []
    # çocuklar (bu nesne ebeveyn)
    children = db.execute(text(
        "SELECT child_name, child_type, line_no FROM automic_object_usage "
        "WHERE system_id = :sid AND client = :c AND parent_object_name = :n "
        "ORDER BY line_no LIMIT 200"
    ), {"sid": system.id, "c": int(client), "n": name}).all()
    for child, ctype, lnr in children:
        nodes.append({"id": child, "label": child, "kind": "child",
                      "object_type": ctype, "line_no": lnr})
        edges.append({"from": name, "to": child, "relation": "contains", "line_no": lnr})
    # ebeveynler (bu nesneyi çağıran)
    parents = db.execute(text(
        "SELECT DISTINCT parent_object_name, parent_object_id FROM automic_object_usage "
        "WHERE system_id = :sid AND client = :c AND child_name = :n "
        "AND parent_object_name IS NOT NULL LIMIT 100"
    ), {"sid": system.id, "c": int(client), "n": name}).all()
    for pname, pid in parents:
        nodes.append({"id": pname, "label": pname, "kind": "parent", "object_id": pid,
                      "object_type": "JOBP"})
        edges.append({"from": pname, "to": name, "relation": "calls"})
    seen: set = set()
    uniq = []
    for n in nodes:
        if n["id"] in seen:
            continue
        seen.add(n["id"])
        uniq.append(n)
    header = db.get(AutomicObjectHeader, {
        "system_id": system.id, "client": int(client), "object_name": name})
    if header and header.object_type:
        uniq[0]["object_type"] = header.object_type
    return {
        "ok": True, "system": system.name, "system_id": system.id,
        "object_name": name, "client": int(client), "depth": depth,
        "nodes": uniq, "edges": edges,
        "data_source": "module_db",
        "synced_at": synced.isoformat() if synced else None,
    }


def sync_jpp_chunk(db: Session, system: AutomicSystem, src, *,
                   id_min: int, id_max: int, limit: int = 500) -> Dict[str, Any]:
    """Kaynaktan JPP satırlarını OH_Idnr PK aralığıyla çekip modül DB'ye yazar."""
    from sqlalchemy import bindparam
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    if not src.supports("usage_graph"):
        return {"ok": False, "upserted": 0, "skipped": "usage_unavailable"}
    rows = src.fetch_jpp_by_parent_range(int(id_min), int(id_max), limit=limit)
    if not rows:
        return {"ok": True, "upserted": 0}
    parent_ids = sorted({int(r["parent_object_id"]) for r in rows})
    id_map: Dict[int, Dict[str, Any]] = {}
    if parent_ids:
        q = db.execute(
            text(
                "SELECT object_id, client, object_name FROM automic_object_headers "
                "WHERE system_id = :sid AND object_id IN :ids"
            ).bindparams(bindparam("ids", expanding=True)),
            {"sid": system.id, "ids": parent_ids},
        ).all()
        for oid, cl, oname in q:
            id_map[int(oid)] = {"client": int(cl), "name": oname}
        missing = [i for i in parent_ids if i not in id_map]
        if missing and hasattr(src, "_lookup_names"):
            try:
                looked = src._lookup_names(missing, kind="collector")
                for oid, info in (looked or {}).items():
                    if info and info.get("name"):
                        id_map[int(oid)] = {
                            "client": int(info["client"]) if info.get("client") is not None else None,
                            "name": info["name"],
                        }
            except Exception as exc:
                note_error("objects.sync_jpp_chunk", exc)
    now = _now()
    clients = set(int(c) for c in (system.clients or []) if c is not None)
    payload = []
    for r in rows:
        pid = int(r["parent_object_id"])
        info = id_map.get(pid) or {}
        cl = info.get("client")
        if cl is None and r.get("client") is not None:
            cl = int(r["client"])
        if cl is None and len(clients) == 1:
            cl = next(iter(clients))
        if cl is None or (clients and cl not in clients):
            continue
        child = (r.get("child_name") or "").strip()
        if not child:
            continue
        payload.append({
            "system_id": system.id, "client": int(cl), "parent_object_id": pid,
            "line_no": int(r.get("line_no") or 0),
            "parent_object_name": info.get("name") or r.get("parent_object_name"),
            "child_name": child, "child_type": r.get("child_type"), "seen_at": now,
        })
    if not payload:
        return {"ok": True, "upserted": 0}
    stmt = pg_insert(AutomicObjectUsage.__table__).values(payload)
    stmt = stmt.on_conflict_do_update(
        index_elements=["system_id", "client", "parent_object_id", "line_no"],
        set_={
            "parent_object_name": stmt.excluded.parent_object_name,
            "child_name": stmt.excluded.child_name,
            "child_type": stmt.excluded.child_type,
            "seen_at": stmt.excluded.seen_at,
        },
    )
    db.execute(stmt)
    return {"ok": True, "upserted": len(payload)}


def prune_script_versions(db: Session, system: AutomicSystem) -> int:
    from datetime import timedelta
    r = effective_settings(system.settings).get("retention") or {}
    keep = int(r.get("object_script_versions") or 10)
    max_age = int(r.get("object_script_version_days") or 90)
    deleted = 0
    res = db.execute(text(
        "DELETE FROM automic_object_script_versions WHERE system_id = :sid AND fetched_at < :c"
    ), {"sid": system.id, "c": _now() - timedelta(days=max_age)})
    deleted += int(res.rowcount or 0)
    # nesne başına keep
    rows = db.execute(text("""
        SELECT client, object_name FROM automic_object_script_versions
        WHERE system_id = :sid GROUP BY 1, 2 HAVING count(*) > :k
    """), {"sid": system.id, "k": keep}).all()
    for client, name in rows:
        old = (db.query(AutomicObjectScriptVersion)
               .filter_by(system_id=system.id, client=client, object_name=name)
               .order_by(AutomicObjectScriptVersion.version_no.desc()).offset(keep).all())
        for o in old:
            db.delete(o)
            deleted += 1
    db.commit()
    return deleted
