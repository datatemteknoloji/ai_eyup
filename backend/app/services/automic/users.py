"""Automic kullanıcı tablosu — OH (OType=USER) senkronu, client zorunlu join, arama.

AH_USR_Idnr ↔ OH_Idnr eşlemesi resmi 24.4 şemasında açıkça kanıtlanmaz; kod/yaml
varsayımıdır ve gerçek veriyle doğrulanacaktır. USR tablosu okunmaz (şifre riski).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.models.automic import AutomicSystem, AutomicUser

from .defaults import effective_settings
from .source.base import SourceError

logger = logging.getLogger(__name__)

# Eşleşmeme oranı bu eşiği aşarsa collector uyarır (gerçek veriyle doğrulama sinyali).
DEFAULT_MISMATCH_WARN_RATIO = 0.05


def _now() -> datetime:
    return datetime.now(timezone.utc)


def split_oh_user_name(full: str) -> Tuple[str, Optional[str]]:
    """OH_Name → (name, department). Automic'te genelde NAME/DEPARTMENT."""
    s = (full or "").strip()
    if not s:
        return "", None
    if "/" in s:
        name, dept = s.split("/", 1)
        return name.strip(), (dept.strip() or None)
    return s, None


def full_user_name(name: Optional[str], department: Optional[str] = None) -> str:
    n = (name or "").strip()
    d = (department or "").strip() if department else ""
    if n and d:
        return f"{n}/{d}"
    return n or d


def is_deleted_flag(delete_flag: Optional[int]) -> bool:
    """OH_DeleteFlag: 0=not deleted; 1/2/5 silinmiş/sürümlü/arşiv."""
    if delete_flag is None:
        return False
    try:
        return int(delete_flag) != 0
    except (TypeError, ValueError):
        return False


LEGACY_USER_TAG = "eski kayıt — kullanıcı ID'si yok"


def format_user_display(
    *,
    user_idnr: Optional[int] = None,
    name: Optional[str] = None,
    department: Optional[str] = None,
    delete_flag: Optional[int] = None,
    user_name_at_run: Optional[str] = None,
    found: bool = False,
) -> Optional[str]:
    """Görüntüleme adı: güncel join, silinmiş etiketi, bilinmeyen ID, eski kayıt."""
    if found:
        label = full_user_name(name, department) or (user_name_at_run or "").strip() or f"ID:{user_idnr}"
        if is_deleted_flag(delete_flag):
            return f"{label} (silinmiş)"
        return label
    if user_idnr is not None:
        return f"bilinmeyen kullanıcı (ID: {int(user_idnr)})"
    legacy = (user_name_at_run or "").strip()
    if legacy:
        return f"{legacy} ({LEGACY_USER_TAG})"
    return None


def require_client_pairs(pairs: Sequence[Tuple[Optional[int], Any]]) -> List[Tuple[int, int]]:
    """Kullanıcı join'lerinde client zorunlu — client'sız (ama id'li) çağrı ValueError."""
    out: List[Tuple[int, int]] = []
    for client, uid in pairs:
        if uid is None:
            continue
        if client is None:
            raise ValueError("kullanıcı join için client zorunlu")
        out.append((int(client), int(uid)))
    return out


def lookup_users(
    db: Session, system_id: int, pairs: Sequence[Tuple[Optional[int], Any]],
) -> Dict[Tuple[int, int], AutomicUser]:
    """(client, user_idnr) → AutomicUser. Client'sız pair reddedilir."""
    clean = require_client_pairs(pairs)
    if not clean:
        return {}
    clients = sorted({c for c, _ in clean})
    ids = sorted({u for _, u in clean})
    rows = (
        db.query(AutomicUser)
        .filter(
            AutomicUser.system_id == int(system_id),
            AutomicUser.client.in_(clients),
            AutomicUser.user_idnr.in_(ids),
        )
        .all()
    )
    wanted = set(clean)
    return {(r.client, r.user_idnr): r for r in rows if (r.client, r.user_idnr) in wanted}


def resolve_user_display(
    db: Session, system_id: int, client: Optional[int], user_idnr: Optional[int],
    user_name_at_run: Optional[str] = None,
) -> Optional[str]:
    if client is None and user_idnr is not None:
        raise ValueError("kullanıcı join için client zorunlu")
    if user_idnr is None:
        return format_user_display(user_name_at_run=user_name_at_run, found=False)
    found = lookup_users(db, system_id, [(client, user_idnr)])
    u = found.get((int(client), int(user_idnr)))
    if u is None:
        return format_user_display(
            user_idnr=int(user_idnr), user_name_at_run=user_name_at_run, found=False)
    return format_user_display(
        user_idnr=u.user_idnr, name=u.name, department=u.department,
        delete_flag=u.delete_flag, user_name_at_run=user_name_at_run, found=True,
    )


def attach_user_displays(
    db: Session, system_id: int, items: List[Dict[str, Any]],
    *, client_key: str = "client", id_key: str = "user_idnr",
    at_run_key: str = "user_name_at_run", out_key: str = "user",
) -> List[Dict[str, Any]]:
    """Satırlara güncel kullanıcı görüntü adını yazar (client zorunlu join)."""
    # client'sız ama id'li satırlar: bilinmeyen; join'e dahil edilmez
    pairs = []
    for it in items:
        uid, cl = it.get(id_key), it.get(client_key)
        if uid is None:
            continue
        if cl is None:
            it[out_key] = format_user_display(
                user_idnr=int(uid), user_name_at_run=it.get(at_run_key), found=False)
            continue
        pairs.append((cl, uid))
    found = lookup_users(db, system_id, pairs) if pairs else {}
    for it in items:
        uid = it.get(id_key)
        cl = it.get(client_key)
        at_run = it.get(at_run_key)
        if uid is None:
            it[out_key] = format_user_display(
                user_name_at_run=at_run or it.get(out_key), found=False)
            continue
        if cl is None:
            continue  # yukarıda set edildi
        urow = found.get((int(cl), int(uid)))
        if urow is None:
            it[out_key] = format_user_display(
                user_idnr=int(uid), user_name_at_run=at_run, found=False)
        else:
            it[out_key] = format_user_display(
                user_idnr=urow.user_idnr, name=urow.name, department=urow.department,
                delete_flag=urow.delete_flag, user_name_at_run=at_run, found=True,
            )
    return items


def _wildcard_sql(pattern: str) -> str:
    """* ? → SQL ILIKE; joker yoksa kısmi eşleşme."""
    p = (pattern or "").strip().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    p = p.replace("*", "%").replace("?", "_")
    if "%" not in p and "_" not in p.replace("\\_", ""):
        p = f"%{p}%"
    return p


def parse_user_search_pattern(pattern: str) -> Tuple[Optional[str], Optional[str]]:
    """'name/dept' → (name_pat|None, dept_pat|None). '*' = filtre yok. '/' yoksa (pat, None)."""
    raw = (pattern or "").strip()
    if not raw:
        return None, None
    if "/" in raw:
        name_p, dept_p = raw.split("/", 1)
        name_f = None if not name_p.strip() or name_p.strip() == "*" else name_p.strip()
        dept_f = None if not dept_p.strip() or dept_p.strip() == "*" else dept_p.strip()
        return name_f, dept_f
    return raw, None


def search_users(
    db: Session, system_id: int, clients: List[int], pattern: str, *, limit: int = 50,
) -> List[Dict[str, Any]]:
    """Modül DB kullanıcı araması — ILIKE, wildcard, ad ve/veya departman."""
    name_f, dept_f = parse_user_search_pattern(pattern)
    if name_f is None and dept_f is None and "/" not in (pattern or ""):
        return []
    where = ["system_id = :sid", "client = ANY(:cl)"]
    p: Dict[str, Any] = {"sid": int(system_id), "cl": list(clients), "lim": max(1, min(int(limit), 200))}
    if "/" in (pattern or ""):
        if name_f is not None:
            where.append("name ILIKE :np ESCAPE '\\'")
            p["np"] = _wildcard_sql(name_f)
        if dept_f is not None:
            where.append("department ILIKE :dp ESCAPE '\\'")
            p["dp"] = _wildcard_sql(dept_f)
    else:
        where.append(
            "(name ILIKE :np ESCAPE '\\' OR department ILIKE :np ESCAPE '\\' "
            "OR (name || '/' || COALESCE(department, '')) ILIKE :np ESCAPE '\\')"
        )
        p["np"] = _wildcard_sql(name_f or pattern)
    rows = db.execute(text(
        f"SELECT client, user_idnr, name, department, delete_flag FROM automic_users "
        f"WHERE {' AND '.join(where)} ORDER BY name, department LIMIT :lim"
    ), p).all()
    return [{
        "client": int(c), "user_idnr": int(uid), "name": n, "department": d,
        "delete_flag": df, "full_name": full_user_name(n, d),
        "display": format_user_display(
            user_idnr=int(uid), name=n, department=d, delete_flag=df, found=True),
    } for c, uid, n, d, df in rows]


def suggest_users(
    db: Session, system_id: int, clients: List[int], pattern: str, *, limit: int = 15,
) -> List[Dict[str, Any]]:
    """Bilinmeyen ad için en yakın eşleşmeler (kısmi / prefix)."""
    raw = (pattern or "").strip().strip("*/")
    if not raw:
        return []
    # önce normal arama
    hits = search_users(db, system_id, clients, raw, limit=limit)
    if hits:
        return hits
    # prefix / içerir gevşek
    token = raw.split("/")[0][:40]
    if len(token) < 2:
        return []
    rows = db.execute(text(
        "SELECT client, user_idnr, name, department, delete_flag FROM automic_users "
        "WHERE system_id = :sid AND client = ANY(:cl) AND ("
        " name ILIKE :p ESCAPE '\\' OR department ILIKE :p ESCAPE '\\')"
        " ORDER BY name LIMIT :lim"
    ), {"sid": int(system_id), "cl": list(clients), "p": _wildcard_sql(token), "lim": limit}).all()
    return [{
        "client": int(c), "user_idnr": int(uid), "name": n, "department": d,
        "full_name": full_user_name(n, d),
        "display": format_user_display(
            user_idnr=int(uid), name=n, department=d, delete_flag=df, found=True),
        "runs": 0,
    } for c, uid, n, d, df in rows]


def upsert_user(db: Session, system_id: int, row: Dict[str, Any]) -> Optional[AutomicUser]:
    """OH USER satırını yazar; içerik aynıysa yalnız last_seen/synced_at güncellenir."""
    client = row.get("client")
    oid = row.get("object_id") or row.get("user_idnr")
    if client is None or oid is None:
        return None
    full = (row.get("object_name") or row.get("name") or "").strip()
    if not full:
        return None
    name, dept = split_oh_user_name(full)
    if not name and dept:
        name, dept = dept, None
    if not name:
        return None
    df = row.get("delete_flag")
    try:
        df_i = int(df) if df is not None else 0
    except (TypeError, ValueError):
        df_i = 0
    now = _now()
    u = db.get(AutomicUser, {
        "system_id": int(system_id), "client": int(client), "user_idnr": int(oid),
    })
    if u is None:
        u = AutomicUser(
            system_id=int(system_id), client=int(client), user_idnr=int(oid),
            name=name[:200], department=(dept[:200] if dept else None),
            delete_flag=df_i, first_seen=now, last_seen=now, synced_at=now,
        )
        db.add(u)
        return u
    changed = (u.name != name[:200] or (u.department or None) != (dept[:200] if dept else None)
               or (u.delete_flag or 0) != df_i)
    u.name = name[:200]
    u.department = dept[:200] if dept else None
    u.delete_flag = df_i
    u.last_seen = now
    if changed or True:
        u.synced_at = now
    return u


def sync_users_chunk(
    db: Session, system: AutomicSystem, src, *,
    id_min: int, id_max: int, limit: int = 500,
) -> Dict[str, Any]:
    """OH OType=USER — OH_Idnr PK aralığı; ModDate'e göre değişmeyenlerde gereksiz yazım yok."""
    if not getattr(src, "supports", lambda *_: False)("objects"):
        return {"ok": False, "upserted": 0, "skipped": "objects_unavailable"}
    fn = getattr(src, "fetch_users_by_id_range", None)
    if not callable(fn):
        return {"ok": False, "upserted": 0, "skipped": "users_fetch_missing"}
    clients = [int(c) for c in (system.clients or [])]
    try:
        rows = fn(clients, id_min=int(id_min), id_max=int(id_max), limit=max(1, int(limit)))
    except SourceError as exc:
        return {"ok": False, "upserted": 0, "error": str(exc), "code": exc.code}
    n = 0
    skipped_unchanged = 0
    for r in rows:
        if (r.get("object_type") or "USER").upper() != "USER":
            continue
        client = r.get("client")
        oid = r.get("object_id")
        if client is None or oid is None:
            continue
        existing = db.get(AutomicUser, {
            "system_id": system.id, "client": int(client), "user_idnr": int(oid),
        })
        full = (r.get("object_name") or "").strip()
        name, dept = split_oh_user_name(full)
        df = r.get("delete_flag")
        try:
            df_i = int(df) if df is not None else 0
        except (TypeError, ValueError):
            df_i = 0
        src_mod = r.get("modified_at")
        if existing and src_mod and existing.synced_at:
            mod = src_mod if getattr(src_mod, "tzinfo", None) else (
                src_mod.replace(tzinfo=timezone.utc) if isinstance(src_mod, datetime) else None)
            if (mod and mod <= existing.synced_at
                    and existing.name == (name[:200] if name else existing.name)
                    and (existing.department or None) == (dept[:200] if dept else None)
                    and (existing.delete_flag or 0) == df_i):
                existing.last_seen = _now()
                skipped_unchanged += 1
                continue
        if upsert_user(db, system.id, r):
            n += 1
    if n or skipped_unchanged:
        db.commit()
    return {"ok": True, "upserted": n, "unchanged": skipped_unchanged, "fetched": len(rows)}


def mismatch_ratio(recs: Iterable[Dict[str, Any]]) -> Tuple[float, int, int]:
    """(_user_id_matched bayraklı) kayıtlar için eşleşmeme oranı → (ratio, bad, total)."""
    with_id = [r for r in recs if r.get("user_idnr") or r.get("user_id")]
    if not with_id:
        return 0.0, 0, 0
    bad = sum(1 for r in with_id if not r.get("_user_id_matched", False))
    return bad / len(with_id), bad, len(with_id)


def mismatch_warning(
    recs: Iterable[Dict[str, Any]], *, threshold: float = DEFAULT_MISMATCH_WARN_RATIO,
) -> Optional[str]:
    """AH_USR_Idnr↔OH_Idnr eşleşmeme oranı eşiği aşarsa uyarı metni.

    Not: eşleme resmi şemada kanıtlanmaz — gerçek veriyle doğrulanacak.
    """
    ratio, bad, total = mismatch_ratio(recs)
    if total <= 0 or ratio < float(threshold):
        return None
    pct = ratio * 100
    thr = float(threshold) * 100
    return (
        f"AH_USR_Idnr↔OH_Idnr eşleşmeme oranı %{pct:.1f} "
        f"({bad}/{total}; eşik %{thr:.0f}) — gerçek veriyle doğrulanacak"
    )


def effective_mismatch_threshold(system: AutomicSystem) -> float:
    g = effective_settings(system.settings).get("source_guard") or {}
    try:
        return float(g.get("user_id_mismatch_warn_ratio") or DEFAULT_MISMATCH_WARN_RATIO)
    except (TypeError, ValueError):
        return DEFAULT_MISMATCH_WARN_RATIO
