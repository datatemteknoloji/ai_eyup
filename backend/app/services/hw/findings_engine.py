"""Donanım bulguları — deterministik; yalnız `hw` capability + gerçek (demo olmayan) sağlayıcı varken üretilir.

Yalnız FAIL taslakları yazılır (pass satırı yok): koşul düzelince bulgu otomatik çözülür. DEMO veri bulgu üretmez.
Bulgu metni/kanıtı BMC IP veya seri İÇERMEZ (bulgular herkese görünür; ayrıntı `hardware` yetkisiyle Donanım ekranında).
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.hw import HwAlert, HwHostLink, HwServer, HwWarranty
from app.models.integration_instance import IntegrationInstance
from app.services.findings.registry import RESULT_FAIL
from app.services.findings.store import FindingDraft
from app.services.hw.constants import AUTH_FAILED, HEALTH_CRITICAL
from app.services.hw.demo_gate import active_instances, hw_mode
from app.services.hw.sync import data_age_sec, provider_stale

RECUR_THRESHOLD = 3
RECUR_WINDOW_H = 24


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def hw_findings(db: Session, *, now: Optional[datetime] = None) -> List[FindingDraft]:
    now = now or datetime.now(timezone.utc)
    out: List[FindingDraft] = []
    insts = active_instances(db)
    stale_by: Dict[int, bool] = {i.id: provider_stale(i, now) for i in insts}
    age_by: Dict[int, Optional[float]] = {i.id: data_age_sec(i, now) for i in insts}
    ids = [i.id for i in insts] or [-1]

    # ── sağlayıcı ──────────────────────────────────────────────────────────────────────────────────────────────
    for i in insts:
        ref = f"provider:{i.id}"
        if (i.last_status or "") in ("error", AUTH_FAILED):
            out.append(FindingDraft("hw.provider.sync_failed", "provider", ref, i.label or f"hw-{i.id}", RESULT_FAIL,
                                    evidence={"status": i.last_status, "error": (i.last_error or "")[:300]},
                                    detail=(i.last_error or "")[:300]))
        elif i.last_sync_at is not None and stale_by[i.id]:
            out.append(FindingDraft("hw.provider.stale", "provider", ref, i.label or f"hw-{i.id}", RESULT_FAIL,
                                    evidence={"data_age_sec": age_by[i.id]}, data_age_sec=age_by[i.id]))

    servers = db.query(HwServer).filter(HwServer.instance_id.in_(ids)).all()
    by_ref = {(s.instance_id, s.provider_ref): s for s in servers}
    links = {l.hw_server_id: l for l in db.query(HwHostLink).filter(HwHostLink.hw_server_id.in_([s.id for s in servers] or [-1])).all()}

    # ── sağlık kritik / bağlantısız ─────────────────────────────────────────────────────────────────────────────
    for s in servers:
        ref = f"hw:{s.instance_id}:{s.provider_ref}"
        stale = stale_by.get(s.instance_id, False)
        age = age_by.get(s.instance_id)
        if s.health == HEALTH_CRITICAL:
            out.append(FindingDraft("hw.server.health_critical", "server", ref, s.name or s.provider_ref, RESULT_FAIL,
                                    evidence={"vendor": s.vendor, "model": s.model, "raw_status": s.raw_status},
                                    detail=f"{s.vendor.upper()} sağlayıcısı sunucuyu Kritik bildiriyor.",
                                    stale=stale, data_age_sec=age))
        if s.connected is False:
            out.append(FindingDraft("hw.server.unreachable", "server", ref, s.name or s.provider_ref, RESULT_FAIL,
                                    evidence={"vendor": s.vendor}, stale=stale, data_age_sec=age))

    # ── firmware: referans sunucudan düşük (kabul edilmemiş) ────────────────────────────────────────────────────
    try:
        from app.services.hw.firmware_compare import compare_all
        for r in compare_all(db, [s for s in servers]).values():
            if r["status"] != "outdated":
                continue
            s = r["_server"]
            names = [c["name"] for c in r["components"] if c["state"] == "outdated"]
            out.append(FindingDraft("hw.firmware.outdated", "server", f"hw:{s.instance_id}:{s.provider_ref}", s.name or s.provider_ref,
                                    RESULT_FAIL, evidence={"outdated_components": len(names), "model": s.model, "vendor": s.vendor},
                                    detail=f"{len(names)} bileşen referans sunucudan düşük sürümde: " + ", ".join(names[:5]),
                                    stale=stale_by.get(s.instance_id, False), data_age_sec=age_by.get(s.instance_id)))
    except Exception:  # noqa: BLE001 — firmware karşılaştırması diğer donanım bulgularını engellemez
        import logging
        logging.getLogger(__name__).exception("hw firmware karşılaştırması başarısız")

    # ── tekrar eden alarm ───────────────────────────────────────────────────────────────────────────────────────
    cutoff = now - timedelta(hours=RECUR_WINDOW_H)
    cnt: Dict[tuple, int] = defaultdict(int)
    sample: Dict[tuple, str] = {}
    for a in db.query(HwAlert).filter(HwAlert.instance_id.in_(ids), HwAlert.server_ref.isnot(None)).all():
        occ = _aware(a.occurred_at)
        if occ is None or occ < cutoff or a.state == "cleared":
            continue
        k = (a.instance_id, a.server_ref, a.fingerprint)
        cnt[k] += 1
        sample.setdefault(k, (a.message or "")[:200])
    for (iid, sref, fp), n in cnt.items():
        if n < RECUR_THRESHOLD:
            continue
        s = by_ref.get((iid, sref))
        if s is None:
            continue
        out.append(FindingDraft("hw.alert.recurring", "server", f"hw:{iid}:{sref}:{fp[:12]}", s.name or sref, RESULT_FAIL,
                                evidence={"count_24h": n, "threshold": RECUR_THRESHOLD, "message": sample[(iid, sref, fp)]},
                                detail=f"Son {RECUR_WINDOW_H} saatte {n} kez: {sample[(iid, sref, fp)]}",
                                stale=stale_by.get(iid, False), data_age_sec=age_by.get(iid)))

    # ── garanti (üretim katmanı + eşleşmiş sunucu) ──────────────────────────────────────────────────────────────
    from app.models.server import Server
    max_end: Dict[tuple, datetime] = {}
    for w in db.query(HwWarranty).filter(HwWarranty.instance_id.in_(ids)).all():
        e = _aware(w.end_date)
        if e is None:
            continue
        k = (w.instance_id, w.server_ref)
        if k not in max_end or e > max_end[k]:
            max_end[k] = e
    for (iid, sref), end in max_end.items():
        s = by_ref.get((iid, sref))
        if s is None or end >= now:
            continue
        l = links.get(s.id)
        if l is None or l.target_kind != "server":
            continue
        srv = db.query(Server).filter(Server.id == l.target_id).first()
        if srv is None or (srv.tier or "").lower() != "production":
            continue
        out.append(FindingDraft("hw.warranty.expired_prod", "server", f"hw:{iid}:{sref}", srv.name, RESULT_FAIL,
                                evidence={"warranty_end": end.date().isoformat(), "tier": "production"},
                                detail=f"Garanti {end.date().isoformat()} tarihinde bitti.",
                                stale=stale_by.get(iid, False), data_age_sec=age_by.get(iid)))

    # ── eşleşmeyen kayıtlar (sağlayıcı başına tek toplu bilgi bulgusu) ───────────────────────────────────────────
    for i in insts:
        mine = [s for s in servers if s.instance_id == i.id]
        un = [s for s in mine if s.id not in links]
        if un:
            out.append(FindingDraft("hw.server.unmatched", "provider", f"provider:{i.id}", i.label or f"hw-{i.id}", RESULT_FAIL,
                                    evidence={"unmatched": len(un), "total": len(mine),
                                              "examples": [s.name for s in un[:10]]},
                                    detail=f"{len(un)}/{len(mine)} donanım kaydı ainew sunucusuyla eşleşmedi."))
    return out


def persist_hw_findings(db: Session, *, now: Optional[datetime] = None) -> Dict[str, Any]:
    from app.services.capabilities import get_capabilities
    from app.services.findings import store
    from app.services.findings.registry import RESOLVED_FIXED, RESOLVED_PROVIDER_DISABLED
    caps = get_capabilities(force_refresh=True)
    have = "hw" in caps and hw_mode(db) == "real"
    drafts = hw_findings(db, now=now) if have else []
    r = store.persist_findings(db, platform="hw", source_id=None, source_name="hardware", categories=("hardware",),
                               drafts=drafts, now=now,
                               resolve_reason=RESOLVED_FIXED if have else RESOLVED_PROVIDER_DISABLED)
    db.commit()
    return {"capability": have, **r}
