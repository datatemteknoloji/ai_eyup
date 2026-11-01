"""MTV taşıma geçmişi toplayıcısı — Plan/Migration CR'lerini `mtv_plan_snapshots` tablosuna yazar.

- Salt-okunur: kümede yalnız GET yapılır (mevcut `mtv_service` yardımcıları).
- Plan başına tek satır (cluster_id + plan_uid); her turda güncellenir. CR kümeden silinirse satır
  kalır, `removed_at` dolar → geçmiş/trend raporu kaybolmaz.
- Küme erişilemezse veya MTV kurulu değilse (Forklift API cevap vermez) HİÇBİR satır silinmez/kapanmaz
  ("erişilemedi" ≠ "plan yok").
- Sahte (`fake_seed`) ve sentetik cluster atlanır.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.mtv import MtvPlanSnapshot
from app.models.openshift import OpenShiftCluster

logger = logging.getLogger(__name__)


def _ts(value: Any) -> Optional[datetime]:
    if not value or not isinstance(value, str):
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        return None


def _cond(obj: Dict[str, Any], ctype: str) -> bool:
    for c in ((obj.get("status") or {}).get("conditions") or []):
        if c.get("type") == ctype:
            return c.get("status") == "True"
    return False


def _vm_cond(vm: Dict[str, Any], ctype: str) -> bool:
    for c in (vm.get("conditions") or []):
        if c.get("type") == ctype:
            return c.get("status") == "True"
    return False


def _vm_result(vm: Dict[str, Any]) -> str:
    if _vm_cond(vm, "Succeeded"):
        return "succeeded"
    if _vm_cond(vm, "Failed") or vm.get("error"):
        return "failed"
    if _vm_cond(vm, "Canceled"):
        return "canceled"
    if vm.get("started") and not vm.get("completed"):
        return "running"
    return "pending"


def parse_plan(plan: Dict[str, Any], migrations: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Tek Plan CR'ini snapshot sözlüğüne çevirir (saf fonksiyon — testlenebilir)."""
    meta = plan.get("metadata") or {}
    spec = plan.get("spec") or {}
    status = plan.get("status") or {}
    mig = status.get("migration") or {}
    vms_raw = mig.get("vms") or []
    vms: List[Dict[str, Any]] = []
    for vm in vms_raw:
        err = vm.get("error") or {}
        vms.append({
            "name": vm.get("name") or vm.get("id"),
            "phase": vm.get("phase"),
            "result": _vm_result(vm),
            "started": vm.get("started"),
            "completed": vm.get("completed"),
            "error": "; ".join(err.get("reasons") or []) if err else None,
        })
    spec_vm_n = len(spec.get("vms") or [])
    total = max(spec_vm_n, len(vms))
    ok = sum(1 for v in vms if v["result"] == "succeeded")
    bad = sum(1 for v in vms if v["result"] == "failed")
    run = sum(1 for v in vms if v["result"] == "running")

    crit = next((c for c in (status.get("conditions") or []) if c.get("category") == "Critical"), None)
    if spec.get("archived") or _cond(plan, "Archived"):
        state = "archived"
    elif _cond(plan, "Succeeded"):
        state = "succeeded"
    elif _cond(plan, "Failed"):
        state = "failed"
    elif _cond(plan, "Executing"):
        state = "running"
    elif _cond(plan, "Ready"):
        state = "ready"
    else:
        state = "validating"
    # Plan koşulu henüz yazılmadıysa VM sonuçlarından türet
    if state in ("ready", "validating") and vms:
        if bad and not run:
            state = "failed"
        elif ok and ok == total:
            state = "succeeded"
        elif run:
            state = "running"

    plan_name = meta.get("name") or ""
    started = _ts(mig.get("started"))
    completed = _ts(mig.get("completed"))
    if started is None:
        for m in migrations or []:
            if (m.get("spec") or {}).get("plan", {}).get("name") == plan_name:
                t = _ts((m.get("metadata") or {}).get("creationTimestamp"))
                if t and (started is None or t < started):
                    started = t
    if completed is None and state in ("succeeded", "failed"):
        done = [_ts(v["completed"]) for v in vms if v.get("completed")]
        completed = max([d for d in done if d], default=None)

    prov = spec.get("provider") or {}
    src = prov.get("source") if isinstance(prov.get("source"), dict) else None
    return {
        "plan_uid": meta.get("uid") or f"name:{plan_name}",
        "plan_name": plan_name,
        "namespace": meta.get("namespace"),
        "source_provider": (src or {}).get("name"),
        "target_namespace": spec.get("targetNamespace"),
        "warm": bool(spec.get("warm")),
        "state": state,
        "vm_total": total,
        "vm_succeeded": ok,
        "vm_failed": bad,
        "vm_running": run,
        "error": (crit.get("message") if crit else None),
        "started_at": started,
        "completed_at": completed,
        "vms": vms,
    }


def fetch_cluster_plans(cluster: OpenShiftCluster) -> Optional[List[Dict[str, Any]]]:
    """Kümedeki Plan'ları okur. None = Forklift API'sine erişilemedi (MTV yok / yetki / ağ)."""
    from app.services.openshift import mtv_service as mtv

    client = mtv._client(cluster)
    try:
        plans = mtv._get(client, f"{mtv.FORKLIFT}/namespaces/{mtv.NS}/plans")
        if plans is None:
            return None
        migs = (mtv._get(client, f"{mtv.FORKLIFT}/namespaces/{mtv.NS}/migrations") or {}).get("items") or []
        return [parse_plan(p, migs) for p in plans.get("items") or []]
    finally:
        try:
            client.logout()
        except Exception:  # noqa: BLE001
            pass


def upsert_snapshots(db: Session, cluster: OpenShiftCluster, parsed: List[Dict[str, Any]], now: datetime) -> Dict[str, int]:
    existing = {r.plan_uid: r for r in db.query(MtvPlanSnapshot).filter(MtvPlanSnapshot.cluster_id == cluster.id).all()}
    seen = set()
    added = updated = 0
    for p in parsed:
        uid = p["plan_uid"]
        seen.add(uid)
        row = existing.get(uid)
        if row is None:
            row = MtvPlanSnapshot(cluster_id=cluster.id, first_seen=now, **p)
            db.add(row)
            added += 1
        else:
            for k, v in p.items():
                setattr(row, k, v)
            updated += 1
        row.cluster_name = cluster.name
        row.last_seen = now
        row.removed_at = None
    removed = 0
    for uid, row in existing.items():
        if uid not in seen and row.removed_at is None:
            row.removed_at = now
            removed += 1
    db.commit()
    return {"added": added, "updated": updated, "removed": removed}


def sync_all_mtv_history(db: Session) -> Dict[str, Any]:
    """Tüm gerçek cluster'lar için anlık görüntü. Hata bir cluster'ı atlatır, diğerlerini durdurmaz."""
    from app.services.openshift.fake_cluster import is_fake
    from app.services.synthetic_scope import cluster_is_synthetic

    now = datetime.now(timezone.utc)
    out: Dict[str, Any] = {"clusters": 0, "unavailable": 0, "added": 0, "updated": 0, "removed": 0}
    for cluster in db.query(OpenShiftCluster).order_by(OpenShiftCluster.id).all():
        if is_fake(cluster) or cluster_is_synthetic(cluster):
            continue
        out["clusters"] += 1
        try:
            parsed = fetch_cluster_plans(cluster)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MTV geçmişi (%s) okunamadı: %s", cluster.name, exc)
            out["unavailable"] += 1
            continue
        if parsed is None:
            out["unavailable"] += 1
            continue
        try:
            res = upsert_snapshots(db, cluster, parsed, now)
        except Exception as exc:  # noqa: BLE001
            db.rollback()
            logger.warning("MTV geçmişi (%s) yazılamadı: %s", cluster.name, exc)
            continue
        for k, v in res.items():
            out[k] += v
    return out
