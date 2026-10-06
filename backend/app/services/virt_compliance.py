"""Denetim kanıtı — bulguların kontrol (ISO 27001:2022 Ek A) bazında gruplanması.

Bu bir sertifikasyon aracı değildir: otomatik ölçülebilen teknik kontrollerin
güncel durumunu (pass / fail / ölçülemedi / istisna) zaman damgasıyla verir;
ölçülemeyen maddeler "manuel inceleme" listesinde ayrıca gösterilir.
"""
from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Sequence

from sqlalchemy.orm import Session

from app.services.findings.registry import CONTROL_TITLES, MANUAL_REVIEW_ITEMS
from app.services.findings.store import query_findings


def compliance_report(db: Session, *, platforms: Sequence[str]) -> Dict[str, Any]:
    rows = query_findings(db, platforms=platforms, result="all", include_excepted=True, limit=5000)
    controls: Dict[str, Dict[str, Any]] = {}
    by_ctrl: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for f in rows:
        for ref in f.get("refs") or []:
            by_ctrl[ref].append(f)
    for ctrl, items in sorted(by_ctrl.items()):
        c = {"pass": 0, "fail": 0, "not_measurable": 0, "excepted": 0}
        for f in items:
            if f.get("exception"):
                c["excepted"] += 1
            else:
                c[f["result"]] = c.get(f["result"], 0) + 1
        measured = c["pass"] + c["fail"]
        controls[ctrl] = {
            "control": ctrl, "title": CONTROL_TITLES.get(ctrl, ctrl), "counts": c,
            "score_pct": round(100.0 * c["pass"] / measured, 1) if measured else None,
            "findings": items,
        }
    return {
        "ok": True,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "platforms": list(platforms),
        "controls": list(controls.values()),
        "manual_review": MANUAL_REVIEW_ITEMS,
        "disclaimer": ("Otomatik teknik kanıt eşlemesidir; sertifikasyon beyanı değildir. "
                       "Ölçülemeyen maddeler manuel kanıt gerektirir."),
    }


def compliance_rows(rep: Dict[str, Any]) -> Iterable[List[Any]]:
    for c in rep.get("controls") or []:
        for f in c["findings"]:
            ex = f.get("exception") or {}
            yield [
                c["control"], c["title"], f["platform"], f.get("source_name"), f.get("cluster_name") or "",
                f.get("entity_name"), f["check_id"], f["title"], f["result"], f["severity"],
                (f.get("detail") or "")[:500], json.dumps(f.get("evidence") or {}, ensure_ascii=False)[:2000],
                f.get("last_seen"), (f"{ex.get('reason')} ({ex.get('created_by')})" if ex else ""),
            ]
    for m in rep.get("manual_review") or []:
        yield [m["control"], CONTROL_TITLES.get(m["control"], m["control"]), "", "", "", "", "manual",
               m["title"], "manual_review", "", m["note"], "", rep.get("generated_at"), ""]
