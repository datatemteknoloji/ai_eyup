"""Ekip eşleme — sıralı kurallar (ilk eşleşen geçerli).

1 object_exact  2 folder_prefix  3 name_pattern  4 archive_key
5 user_department (kullanıcı adından türetilen; resmi alan değil)  6 client
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import csv
import fnmatch
import io
import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.automic import AutomicObjectHeader, AutomicTeamRule, AutomicUser

logger = logging.getLogger(__name__)

RULE_ORDER = (
    "object_exact",
    "folder_prefix",
    "name_pattern",
    "archive_key",
    "user_department",
    "client",
)

RULE_LABEL_TR = {
    "object_exact": "Nesne bazında elle atama",
    "folder_prefix": "Klasör yolu öneki",
    "name_pattern": "Nesne adı deseni",
    "archive_key": "Archive key",
    "user_department": "Kullanıcı adından türetilen departman (resmi alan değil)",
    "client": "Client",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def list_rules(db: Session, system_id: int) -> List[AutomicTeamRule]:
    return (
        db.query(AutomicTeamRule)
        .filter(AutomicTeamRule.system_id == int(system_id))
        .order_by(AutomicTeamRule.priority.asc(), AutomicTeamRule.id.asc())
        .all()
    )


def _match_pattern(pattern: str, value: str) -> bool:
    p = (pattern or "").strip()
    v = value or ""
    if not p:
        return False
    if p.startswith("re:"):
        try:
            return bool(re.search(p[3:], v))
        except re.error:
            return False
    return fnmatch.fnmatch(v.upper(), p.upper())


def resolve_team(
    db: Session, system_id: int, *,
    object_name: Optional[str] = None,
    folder: Optional[str] = None,
    archive1: Optional[str] = None,
    archive2: Optional[str] = None,
    client: Optional[int] = None,
    creator_department: Optional[str] = None,
    rules: Optional[List[AutomicTeamRule]] = None,
) -> Dict[str, Any]:
    """{team, rule_type, rule_label, match_value, rule_id} veya team=None."""
    ordered = rules if rules is not None else list_rules(db, system_id)
    by_type: Dict[str, List[AutomicTeamRule]] = {t: [] for t in RULE_ORDER}
    for r in ordered:
        if not r.enabled:
            continue
        if r.rule_type in by_type:
            by_type[r.rule_type].append(r)

    def hit(r: AutomicTeamRule) -> Dict[str, Any]:
        return {
            "team": r.team,
            "rule_type": r.rule_type,
            "rule_label": RULE_LABEL_TR.get(r.rule_type, r.rule_type),
            "match_value": r.match_value,
            "rule_id": r.id,
        }

    name = (object_name or "").strip()
    for r in by_type["object_exact"]:
        if name and name.upper() == (r.match_value or "").strip().upper():
            return hit(r)

    fold = folder or ""
    for r in by_type["folder_prefix"]:
        pref = (r.match_value or "").strip()
        if pref and fold.upper().startswith(pref.upper()):
            return hit(r)

    for r in by_type["name_pattern"]:
        if name and _match_pattern(r.match_value, name):
            return hit(r)

    for r in by_type["archive_key"]:
        mv = (r.match_value or "").strip()
        if not mv:
            continue
        # "1:VALUE" / "2:VALUE" veya düz değer (her iki archive)
        if mv.upper().startswith("1:"):
            if (archive1 or "").strip().upper() == mv[2:].strip().upper():
                return hit(r)
        elif mv.upper().startswith("2:"):
            if (archive2 or "").strip().upper() == mv[2:].strip().upper():
                return hit(r)
        elif (archive1 or "").strip().upper() == mv.upper() or (archive2 or "").strip().upper() == mv.upper():
            return hit(r)

    dept = (creator_department or "").strip()
    for r in by_type["user_department"]:
        if dept and dept.upper() == (r.match_value or "").strip().upper():
            return hit(r)

    if client is not None:
        for r in by_type["client"]:
            try:
                if int(r.match_value) == int(client):
                    return hit(r)
            except (TypeError, ValueError) as _e:
                note_error("teams.resolve_team", _e)
                continue

    return {
        "team": None,
        "rule_type": None,
        "rule_label": "ekip atanmamış",
        "match_value": None,
        "rule_id": None,
    }


def resolve_team_for_object(
    db: Session, system_id: int, client: int, object_name: str,
) -> Dict[str, Any]:
    oh = db.get(AutomicObjectHeader, {
        "system_id": int(system_id), "client": int(client), "object_name": object_name,
    })
    folder = oh.folder if oh else None
    archive1 = oh.archive1 if oh else None
    archive2 = oh.archive2 if oh else None
    creator_dept = None
    if oh and oh.created_by and "/" in oh.created_by:
        creator_dept = oh.created_by.split("/", 1)[1]
    elif oh and oh.created_by:
        # created_by bazen yalnız ad — USER tablosundan dene
        u = (
            db.query(AutomicUser)
            .filter(
                AutomicUser.system_id == int(system_id),
                AutomicUser.client == int(client),
                AutomicUser.name == oh.created_by.split("/")[0],
            )
            .first()
        )
        if u:
            creator_dept = u.department
    return resolve_team(
        db, system_id,
        object_name=object_name, folder=folder,
        archive1=archive1, archive2=archive2,
        client=client, creator_department=creator_dept,
    )


def upsert_rule(
    db: Session, system_id: int, *,
    rule_type: str, match_value: str, team: str,
    priority: Optional[int] = None, enabled: bool = True,
    rule_id: Optional[int] = None, updated_by: Optional[str] = None,
) -> AutomicTeamRule:
    if rule_type not in RULE_ORDER:
        raise ValueError(f"Geçersiz kural tipi: {rule_type}")
    if rule_id:
        row = db.get(AutomicTeamRule, int(rule_id))
        if not row or row.system_id != int(system_id):
            raise ValueError("Kural bulunamadı")
    else:
        row = AutomicTeamRule(system_id=int(system_id))
        db.add(row)
    row.rule_type = rule_type
    row.match_value = (match_value or "")[:512]
    row.team = (team or "")[:200]
    row.priority = int(priority if priority is not None else _default_priority(rule_type))
    row.enabled = bool(enabled)
    row.updated_at = _now()
    row.updated_by = updated_by
    return row


def _default_priority(rule_type: str) -> int:
    try:
        return (RULE_ORDER.index(rule_type) + 1) * 10
    except ValueError:
        return 100


def delete_rule(db: Session, system_id: int, rule_id: int) -> bool:
    row = db.get(AutomicTeamRule, int(rule_id))
    if not row or row.system_id != int(system_id):
        return False
    db.delete(row)
    return True


def import_csv(
    db: Session, system_id: int, content: str, *,
    updated_by: Optional[str] = None,
) -> Dict[str, Any]:
    """CSV: object_name|folder,team  veya rule_type,match_value,team[,priority]."""
    reader = csv.DictReader(io.StringIO(content))
    if not reader.fieldnames:
        return {"ok": False, "error": "Boş CSV", "imported": 0}
    fields = {f.strip().lower() for f in reader.fieldnames}
    n = 0
    for row in reader:
        norm = {((k or "").strip().lower()): (v or "").strip() for k, v in row.items()}
        if "rule_type" in fields and "match_value" in fields:
            rt = norm.get("rule_type") or "object_exact"
            mv = norm.get("match_value") or ""
            team = norm.get("team") or ""
            pr = norm.get("priority")
        elif "object_name" in fields or "folder" in fields:
            if norm.get("object_name"):
                rt, mv = "object_exact", norm["object_name"]
            else:
                rt, mv = "folder_prefix", norm.get("folder") or ""
            team = norm.get("team") or ""
            pr = None
        else:
            continue
        if not mv or not team:
            continue
        upsert_rule(
            db, system_id, rule_type=rt, match_value=mv, team=team,
            priority=int(pr) if pr else None, updated_by=updated_by,
        )
        n += 1
    db.commit()
    return {"ok": True, "imported": n}


def seed_demo_rules(db: Session, system_id: int) -> int:
    """Fake/demo ortam için örnek kurallar."""
    existing = list_rules(db, system_id)
    if existing:
        return 0
    samples = [
        ("folder_prefix", "FIN/", "Finans", 20),
        ("folder_prefix", "HR/", "IK", 20),
        ("name_pattern", "JOBS.FIN.*", "Finans", 30),
        ("name_pattern", "JOBS.SAP.*", "SAP", 30),
        ("archive_key", "1:FINANCE", "Finans", 40),
        ("user_department", "OPS", "Operasyon", 50),
        ("client", "100", "Client-100", 60),
    ]
    for rt, mv, team, pr in samples:
        upsert_rule(db, system_id, rule_type=rt, match_value=mv, team=team, priority=pr,
                    updated_by="system")
    db.commit()
    return len(samples)
