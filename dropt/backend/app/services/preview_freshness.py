"""
Preview tazeliği — apply öncesi ortamın hâlâ preview anındaki gibi olduğunu doğrular.

Başka bir kullanıcı (veya aynı kullanıcı) arada apply ettiyse planned_commands /
before_state kaymış olabilir; kör apply yerine yeniden önizleme istenir.
Terminal bu kontrolden etkilenmez (yalnızca job apply yolu).
"""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from sqlmodel import Session, col, select

from app.models.job import Job, JobRun, JobRunStatus, JobStatus
from app.modules.base import HostPlan
from app.modules.registry import get_module

logger = logging.getLogger(__name__)

# before_state içinde karşılaştırılmayan (zaman/önbellek) alanlar
_VOLATILE_KEYS = frozenset(
    {
        "collected_at",
        "timestamp",
        "ts",
        "now",
        "cached",
        "cache_hit",
        "as_of",
        "checked_at",
        "inventory_at",
    }
)


class StalePreviewError(ValueError):
    """Önizleme bayat — yeniden preview gerekir."""


def normalize_commands(cmds: list[str] | None) -> list[str]:
    out: list[str] = []
    for c in cmds or []:
        s = str(c).strip()
        if not s or s.startswith("#"):
            continue
        out.append(s)
    return out


def fingerprint_state(state: dict[str, Any] | None) -> str:
    """Kararlı JSON parmak izi (volatile alanlar hariç)."""
    cleaned = _strip_volatile(state or {})
    return json.dumps(cleaned, sort_keys=True, ensure_ascii=False, default=str)


def _strip_volatile(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {
            k: _strip_volatile(v)
            for k, v in obj.items()
            if k not in _VOLATILE_KEYS and not str(k).startswith("_")
        }
    if isinstance(obj, list):
        return [_strip_volatile(x) for x in obj]
    return obj


def revalidate_job_preview(session: Session, job: Job) -> dict[int, HostPlan]:
    """
    Canlı build_plans ile preview JobRun kayıtlarını karşılaştırır.
    Uyuşmazlıkta StalePreviewError.
    Dönüş: server_id → taze HostPlan (apply tarafı isterse kullanır).
    """
    if job.id is None:
        raise StalePreviewError("İş kimliği yok")

    mod = get_module(job.module)
    from app.models.server import TargetServer

    sids = [int(s) for s in (job.server_ids or []) if s is not None]
    if not sids:
        raise StalePreviewError("Sunucu listesi boş")
    servers = list(session.exec(select(TargetServer).where(col(TargetServer.id).in_(sids))).all())
    found = {int(s.id) for s in servers if s.id is not None}  # type: ignore[arg-type]
    missing = [i for i in sids if i not in found]
    if missing:
        raise StalePreviewError(f"Sunucu bulunamadı: {missing}")
    by_id = {int(s.id): s for s in servers if s.id is not None}  # type: ignore[misc]
    ordered = [by_id[i] for i in sids]

    try:
        fresh_plans = mod.build_plans(session, job.action, ordered, dict(job.payload or {}))
    except Exception as e:
        raise StalePreviewError(
            f"Önizleme yenilenemedi (ortam okunamadı): {e}. Lütfen yeniden önizleyin."
        ) from e

    by_sid: dict[int, HostPlan] = {int(p.server_id): p for p in fresh_plans}

    runs = session.exec(select(JobRun).where(JobRun.job_id == job.id)).all()
    # Uygulanacak adaylar: komutu olan ve skip edilmemiş run'lar
    ok_runs = [
        r
        for r in runs
        if (r.planned_commands or []) and r.status != JobRunStatus.skipped
    ]
    if not ok_runs:
        ok_runs = [r for r in runs if r.status == JobRunStatus.pending]

    mismatches: list[str] = []
    for run in ok_runs:
        sid = int(run.target_server_id)
        host = run.hostname or str(sid)
        fresh = by_sid.get(sid)
        if fresh is None:
            mismatches.append(f"{host}: canlı planda sunucu yok")
            continue
        if not fresh.ok:
            err = (fresh.error or "plan geçersiz").strip()
            mismatches.append(f"{host}: {err}")
            continue

        old_cmds = normalize_commands(list(run.planned_commands or []))
        new_cmds = normalize_commands(list(fresh.planned_commands or []))
        if old_cmds != new_cmds:
            mismatches.append(
                f"{host}: planlanan komutlar değişmiş "
                f"(önizleme {len(old_cmds)} adım → şimdi {len(new_cmds)} adım)"
            )
            continue

        old_fp = fingerprint_state(dict(run.before_state or {}))
        new_fp = fingerprint_state(dict(fresh.before_state or {}))
        if old_fp != new_fp:
            mismatches.append(f"{host}: sunucu durumu önizlemeden bu yana değişmiş")

    if mismatches:
        detail = "; ".join(mismatches[:5])
        extra = f" (+{len(mismatches) - 5} daha)" if len(mismatches) > 5 else ""
        raise StalePreviewError(
            "Önizleme güncelliğini yitirdi — ortam değişmiş. "
            "Lütfen yeniden önizleyip sonra uygulayın. "
            f"Ayrıntı: {detail}{extra}"
        )

    return by_sid


def mark_overlapping_previews_stale(session: Session, finished_job: Job) -> int:
    """
    Başarılı/partial apply sonrası aynı sunuculardaki diğer previewed işlere
    payload._stale işaretler (UI uyarı / apply'de ek sinyal).
    """
    if finished_job.id is None:
        return 0
    if finished_job.status not in {JobStatus.success, JobStatus.partial}:
        return 0

    wanted = {int(s) for s in (finished_job.server_ids or []) if s is not None}
    if not wanted:
        return 0

    others = session.exec(
        select(Job).where(
            Job.status == JobStatus.previewed,
            Job.id != finished_job.id,
        )
    ).all()

    n = 0
    reason = (
        f"Sunucu durumu iş #{finished_job.id} "
        f"({finished_job.created_by_username}/{finished_job.module}.{finished_job.action}) "
        f"uygulamasından sonra değişmiş olabilir — yeniden önizleyin."
    )
    for other in others:
        overlap = wanted & {int(s) for s in (other.server_ids or []) if s is not None}
        if not overlap:
            continue
        payload = dict(other.payload or {})
        payload["_stale"] = True
        payload["_stale_by_job_id"] = int(finished_job.id)
        payload["_stale_reason"] = reason
        other.payload = payload
        if not (other.error_message or "").strip():
            other.error_message = reason[:1024]
        session.add(other)
        n += 1
    if n:
        session.commit()
        logger.info(
            "preview stale işaretlendi: %s iş (tetikleyen job=%s)",
            n,
            finished_job.id,
        )
    return n
