"""
Aynı hedef sunucuda eşzamanlı Level-1 (Dropt) operasyonlarını engeller.

- Redis SET NX + TTL: hızlı, worker'lar arası güvenli kilit
- DB yedek kontrolü: status=running (veya run=running) job'lar
Redis yoksa yalnız DB kontrolü uygulanır (best-effort).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Optional

from sqlmodel import Session, col, select

from app.core.config import get_settings
from app.models.job import Job, JobRun, JobRunStatus, JobStatus

logger = logging.getLogger(__name__)

_LOCK_PREFIX = "dropt:host_op_lock:"
_LOCK_TTL_SEC = 7200  # güvenlik: stuck worker → otomatik düşer


class HostLockError(ValueError):
    """Sunucu başka bir işlem tarafından kilitli."""


@dataclass
class BlockingJobInfo:
    job_id: int
    username: str
    module: str
    action: str
    status: str
    server_ids: list[int]


def _redis():
    import redis

    return redis.from_url(get_settings().redis_url, decode_responses=True)


def _lock_key(server_id: int) -> str:
    return f"{_LOCK_PREFIX}{int(server_id)}"


def _lock_token(job: Job) -> str:
    return f"{int(job.id)}|{job.created_by_username or '?'}"


def find_blocking_jobs(session: Session, job: Job) -> list[BlockingJobInfo]:
    """Aynı sunucu(lar) üzerinde running (veya run running) başka işler."""
    wanted = {int(s) for s in (job.server_ids or []) if s is not None}
    if not wanted:
        return []

    active = session.exec(
        select(Job).where(
            col(Job.status).in_([JobStatus.running, JobStatus.approved]),
            Job.id != job.id,
        )
    ).all()

    out: list[BlockingJobInfo] = []
    seen: set[int] = set()
    for other in active:
        oid = int(other.id) if other.id is not None else 0
        if oid in seen:
            continue
        overlap = wanted & {int(s) for s in (other.server_ids or []) if s is not None}
        if not overlap:
            continue
        seen.add(oid)
        out.append(
            BlockingJobInfo(
                job_id=oid,
                username=other.created_by_username or "?",
                module=other.module,
                action=other.action,
                status=other.status.value if hasattr(other.status, "value") else str(other.status),
                server_ids=sorted(overlap),
            )
        )

    # JobRun.running — job status gecikmeli kalmış olabilir
    run_rows = session.exec(
        select(JobRun).where(
            col(JobRun.target_server_id).in_(list(wanted)),
            JobRun.status == JobRunStatus.running,
            JobRun.job_id != job.id,
        )
    ).all()
    for run in run_rows:
        if int(run.job_id) in seen:
            continue
        other = session.get(Job, run.job_id)
        if other is None:
            continue
        seen.add(int(run.job_id))
        out.append(
            BlockingJobInfo(
                job_id=int(run.job_id),
                username=other.created_by_username or "?",
                module=other.module,
                action=other.action,
                status="run_running",
                server_ids=[int(run.target_server_id)],
            )
        )
    return out


def _format_blockers(blockers: list[BlockingJobInfo], server_labels: dict[int, str] | None = None) -> str:
    parts = []
    for b in blockers[:3]:
        names = []
        for sid in b.server_ids:
            names.append((server_labels or {}).get(sid) or f"id={sid}")
        host = ", ".join(names)
        parts.append(
            f"iş #{b.job_id} ({b.username}, {b.module}.{b.action}, {host})"
        )
    extra = f" (+{len(blockers) - 3} daha)" if len(blockers) > 3 else ""
    return (
        "Bu sunucuda şu an başka bir operasyon devam ediyor. "
        "Bitmesini bekleyip tekrar deneyin. "
        f"Engelleyen: {'; '.join(parts)}{extra}"
    )


def _server_labels(session: Session, server_ids: list[int]) -> dict[int, str]:
    from app.models.server import TargetServer

    if not server_ids:
        return {}
    rows = session.exec(select(TargetServer).where(col(TargetServer.id).in_(server_ids))).all()
    out: dict[int, str] = {}
    for s in rows:
        label = (s.hostname or s.ip or str(s.id)).strip()
        out[int(s.id)] = label  # type: ignore[arg-type]
    return out


def assert_servers_free(session: Session, job: Job) -> None:
    """Apply öncesi hızlı kontrol — kilit almadan 409 üretmek için."""
    blockers = find_blocking_jobs(session, job)
    if not blockers:
        # Redis'te yabancı kilit var mı?
        try:
            r = _redis()
            token_prefix = f"{int(job.id)}|"
            for sid in sorted({int(s) for s in (job.server_ids or []) if s is not None}):
                cur = r.get(_lock_key(sid))
                if cur and not str(cur).startswith(token_prefix):
                    raise HostLockError(
                        f"Bu sunucuda (id={sid}) başka bir işlem kilidi var ({cur}). "
                        "Bitmesini bekleyip tekrar deneyin."
                    )
        except HostLockError:
            raise
        except Exception as e:
            logger.debug("host lock redis probe skip: %s", e)
        return

    labels = _server_labels(session, [sid for b in blockers for sid in b.server_ids])
    raise HostLockError(_format_blockers(blockers, labels))


def acquire_server_locks(session: Session, job: Job) -> list[int]:
    """
    Job'un tüm server_ids için kilit alır.
    Başarısızsa kısmi kilitleri geri bırakır ve HostLockError fırlatır.
    """
    if job.id is None:
        raise HostLockError("İş kimliği yok — kilit alınamaz")

    blockers = find_blocking_jobs(session, job)
    if blockers:
        labels = _server_labels(session, [sid for b in blockers for sid in b.server_ids])
        raise HostLockError(_format_blockers(blockers, labels))

    sids = sorted({int(s) for s in (job.server_ids or []) if s is not None})
    if not sids:
        return []

    token = _lock_token(job)
    held: list[int] = []
    try:
        r = _redis()
    except Exception as e:
        logger.warning("host lock: Redis yok, yalnız DB kontrolü ile devam (%s)", e)
        return []

    try:
        for sid in sids:
            key = _lock_key(sid)
            ok = r.set(key, token, nx=True, ex=_LOCK_TTL_SEC)
            if ok:
                held.append(sid)
                continue
            cur = r.get(key)
            # Aynı job yeniden deniyorsa (retry) — sahipliği koru / TTL yenile
            if cur and str(cur).startswith(f"{int(job.id)}|"):
                r.set(key, token, xx=True, ex=_LOCK_TTL_SEC)
                held.append(sid)
                continue
            raise HostLockError(
                f"Bu sunucuda (id={sid}) başka bir işlem kilidi var "
                f"({cur or 'bilinmiyor'}). Bitmesini bekleyip tekrar deneyin."
            )
        return held
    except Exception:
        _release_keys(r, held, token)
        raise


def release_server_locks(job: Job, held_server_ids: Optional[list[int]] = None) -> None:
    """Sahibi bu job olan kilitleri bırakır."""
    if job.id is None:
        return
    sids = held_server_ids
    if sids is None:
        sids = sorted({int(s) for s in (job.server_ids or []) if s is not None})
    if not sids:
        return
    token = _lock_token(job)
    try:
        r = _redis()
    except Exception as e:
        logger.debug("host lock release redis skip: %s", e)
        return
    _release_keys(r, list(sids), token)


def _release_keys(r: Any, server_ids: list[int], token: str) -> None:
    prefix = token.split("|", 1)[0] + "|"
    for sid in server_ids:
        key = _lock_key(sid)
        try:
            cur = r.get(key)
            if cur and str(cur).startswith(prefix):
                r.delete(key)
        except Exception as e:
            logger.warning("host lock release failed sid=%s: %s", sid, e)
