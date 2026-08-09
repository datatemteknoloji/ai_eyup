from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlmodel import Session, select

from app.models.job import (
    AuditStatus,
    Job,
    JobRun,
    JobRunStatus,
    JobStatus,
    PreviewArtifact,
)
from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.modules.registry import get_module, supported_modules
from app.services.audit import write_audit
from app.services.privilege import elevate_commands


def normalize_talep_id(raw: str) -> str:
    value = (raw or "").strip()
    if not value:
        raise ValueError("Talep ID zorunludur")
    if len(value) > 255:
        raise ValueError("Talep ID çok uzun")
    return value


def _load_servers(session: Session, server_ids: list[int]) -> list[TargetServer]:
    if not server_ids:
        raise ValueError("En az bir sunucu seçilmelidir")
    from sqlmodel import col

    servers = session.exec(select(TargetServer).where(col(TargetServer.id).in_(server_ids))).all()
    found = {s.id for s in servers}
    missing = [i for i in server_ids if i not in found]
    if missing:
        raise ValueError(f"Sunucu bulunamadı: {missing}")
    by_id = {s.id: s for s in servers}
    return [by_id[i] for i in server_ids]


def create_job(
    session: Session,
    *,
    module: str,
    action: str,
    talep_id: str,
    server_ids: list[int],
    payload: dict[str, Any],
    user_id: int,
    username: str,
    role: str,
    client_ip: str = "",
) -> Job:
    if module not in supported_modules():
        raise ValueError(f"Desteklenmeyen modül: {module}")
    mod = get_module(module)
    talep = normalize_talep_id(talep_id)
    servers = _load_servers(session, server_ids)
    title = mod.ACTION_TITLES.get(action, f"{module}.{action}")
    summary = mod.job_summary(action, payload)

    job = Job(
        module=module,
        action=action,
        status=JobStatus.draft,
        talep_id=talep,
        title=title,
        summary_tr=summary,
        created_by_user_id=user_id,
        created_by_username=username,
        created_by_role=role,
        client_ip=client_ip,
        payload=payload,
        server_ids=server_ids,
        dry_run=True,
        progress_done=0,
        progress_total=len(servers),
    )
    session.add(job)
    session.commit()
    session.refresh(job)

    write_audit(
        session,
        action=f"job.create.{module}.{action}",
        status=AuditStatus.info,
        message=f"İş oluşturuldu: {title}",
        user_id=user_id,
        username=username,
        role=role,
        client_ip=client_ip,
        talep_id=talep,
        job_id=job.id,
    )
    return job


def run_preview(session: Session, job: Job) -> PreviewArtifact:
    if job.status not in {JobStatus.draft, JobStatus.previewed, JobStatus.failed, JobStatus.partial}:
        raise ValueError(f"Bu durumda önizleme yapılamaz: {job.status}")

    mod = get_module(job.module)
    servers = _load_servers(session, list(job.server_ids))
    plans = mod.build_plans(session, job.action, servers, dict(job.payload or {}))

    existing = session.exec(select(JobRun).where(JobRun.job_id == job.id)).all()
    for row in existing:
        session.delete(row)
    session.commit()

    host_summaries: list[dict[str, Any]] = []
    all_cmds: list[str] = []
    risks: list[str] = []
    for plan in plans:
        planned = elevate_commands(session, list(plan.planned_commands or []))
        run = JobRun(
            job_id=job.id,  # type: ignore[arg-type]
            target_server_id=plan.server_id,
            hostname=plan.hostname,
            ip=plan.ip,
            status=JobRunStatus.pending if plan.ok else JobRunStatus.failed,
            dry_run=True,
            summary_tr=plan.summary_tr,
            planned_commands=planned,
            before_state=plan.before_state,
            error_message=plan.error,
        )
        session.add(run)
        host_summaries.append(
            {
                "server_id": plan.server_id,
                "hostname": plan.hostname,
                "ip": plan.ip,
                "ok": plan.ok,
                "summary_tr": plan.summary_tr,
                "planned_commands": planned,
                "error": plan.error,
            }
        )
        all_cmds.extend(planned)
        if plan.risk_notes:
            risks.append(f"{plan.hostname}: {plan.risk_notes}")

    ok_count = sum(1 for p in plans if p.ok)
    summary_tr = (
        f"{ok_count}/{len(plans)} sunucuda işlem yapılabilir. "
        + " · ".join(p.summary_tr for p in plans[:5])
        + (" …" if len(plans) > 5 else "")
    )
    technical = "\n".join(all_cmds) if all_cmds else "Komut yok"

    prev = session.exec(select(PreviewArtifact).where(PreviewArtifact.job_id == job.id)).first()
    if prev:
        prev.summary_tr = summary_tr
        prev.risk_notes = "\n".join(risks)
        prev.planned_commands = all_cmds
        prev.host_summaries = host_summaries
        prev.technical_detail = technical
        prev.created_at = datetime.now(UTC)
        artifact = prev
    else:
        artifact = PreviewArtifact(
            job_id=job.id,  # type: ignore[arg-type]
            summary_tr=summary_tr,
            risk_notes="\n".join(risks),
            planned_commands=all_cmds,
            host_summaries=host_summaries,
            technical_detail=technical,
        )
        session.add(artifact)

    job.status = JobStatus.previewed
    job.dry_run = True
    job.summary_tr = summary_tr[:1024]
    job.previewed_at = datetime.now(UTC)
    job.updated_at = datetime.now(UTC)
    job.error_message = "" if ok_count else "Önizleme: uygulanabilir hedef yok"
    session.add(job)
    session.commit()
    session.refresh(artifact)

    write_audit(
        session,
        action=f"job.preview.{job.module}.{job.action}",
        status=AuditStatus.info if ok_count else AuditStatus.failed,
        message=summary_tr[:2000],
        user_id=job.created_by_user_id,
        username=job.created_by_username,
        role=job.created_by_role,
        client_ip=job.client_ip,
        talep_id=job.talep_id,
        job_id=job.id,
        output=technical[:5000],
    )
    return artifact


def apply_job(session: Session, job: Job, *, only_failed: bool = False) -> Job:
    # previewed = sync path; approved = Celery kuyruğa alındıktan sonra
    if job.status not in {
        JobStatus.previewed,
        JobStatus.approved,
        JobStatus.partial,
        JobStatus.failed,
    }:
        raise ValueError("Önce önizleme yapılmalı (veya kısmi/başarısız iş yeniden denenmeli)")

    artifact = session.exec(select(PreviewArtifact).where(PreviewArtifact.job_id == job.id)).first()
    if artifact is None:
        raise ValueError("Önizleme kaydı yok")

    ok_hosts = [h for h in (artifact.host_summaries or []) if h.get("ok")]
    if not ok_hosts and not only_failed:
        raise ValueError("Uygulanabilir sunucu yok")

    mod = get_module(job.module)
    job.status = JobStatus.running
    job.dry_run = False
    job.applied_at = datetime.now(UTC)
    job.updated_at = datetime.now(UTC)
    session.add(job)
    session.commit()

    from app.services.job_events import publish_job_event

    publish_job_event(
        int(job.id),  # type: ignore[arg-type]
        {
            "type": "job_start",
            "job_id": job.id,
            "module": job.module,
            "action": job.action,
            "title": job.title,
            "talep_id": job.talep_id,
        },
    )

    write_audit(
        session,
        action=f"job.apply.start.{job.module}.{job.action}",
        status=AuditStatus.info,
        message="Uygulama başladı",
        user_id=job.created_by_user_id,
        username=job.created_by_username,
        role=job.created_by_role,
        client_ip=job.client_ip,
        talep_id=job.talep_id,
        job_id=job.id,
    )

    runs = session.exec(select(JobRun).where(JobRun.job_id == job.id)).all()
    sid_order = {sid: i for i, sid in enumerate(list(job.server_ids))}

    def _run_sort_key(r: JobRun) -> tuple:
        role = (r.before_state or {}).get("role")
        role_rank = 0 if role in {"primary", "single"} else 1 if role == "peer" else 2
        return (role_rank, sid_order.get(r.target_server_id, 999), r.id or 0)

    ordered_runs = sorted(runs, key=_run_sort_key)
    servers = {s.id: s for s in _load_servers(session, list(job.server_ids))}

    success = 0
    failed = 0
    skipped = 0
    primary_failed = False

    from app.services.job_events import publish_job_progress

    publish_job_progress(
        int(job.id),  # type: ignore[arg-type]
        done=0,
        total=max(1, len(ordered_runs)),
        label="uygulama başlıyor…",
        session=session,
    )

    for run in ordered_runs:
        if only_failed and run.status == JobRunStatus.success:
            skipped += 1
            continue
        plan_ok = any(
            h.get("server_id") == run.target_server_id and h.get("ok") for h in (artifact.host_summaries or [])
        )
        if not plan_ok and run.status == JobRunStatus.failed and run.error_message and not only_failed:
            skipped += 1
            continue
        if not plan_ok:
            run.status = JobRunStatus.skipped
            run.finished_at = datetime.now(UTC)
            session.add(run)
            skipped += 1
            continue

        server = servers.get(run.target_server_id)
        if server is None:
            run.status = JobRunStatus.failed
            run.error_message = "Sunucu kaydı yok"
            failed += 1
            session.add(run)
            continue

        run.status = JobRunStatus.running
        run.dry_run = False
        run.started_at = datetime.now(UTC)
        session.add(run)
        session.commit()

        plan = HostPlan(
            server_id=run.target_server_id,
            hostname=run.hostname,
            ip=run.ip,
            ok=True,
            summary_tr=run.summary_tr,
            planned_commands=list(run.planned_commands or []),
            before_state=dict(run.before_state or {}),
        )
        try:
            from app.services.job_events import publish_job_event

            planned = list(run.planned_commands or [])
            runnable_n = sum(
                1 for c in planned if str(c).strip() and not str(c).strip().startswith("#")
            )
            publish_job_event(
                int(job.id),  # type: ignore[arg-type]
                {
                    "type": "run_start",
                    "hostname": run.hostname,
                    "server_id": run.target_server_id,
                    "summary": run.summary_tr,
                    "commands": planned,
                },
            )
            # Adım progress’i modül apply içinde de gelebilir; başlangıçta 0/N
            if runnable_n:
                publish_job_progress(
                    int(job.id),  # type: ignore[arg-type]
                    done=0,
                    total=runnable_n,
                    label=f"{run.hostname}: 0/{runnable_n} adım",
                    hostname=run.hostname,
                    session=session,
                )
            # Tam script’i peşinen basma (organize/create uzun); kısa özet + ilk satırlar
            publish_job_event(
                int(job.id),  # type: ignore[arg-type]
                {
                    "type": "command",
                    "hostname": run.hostname,
                    "line": f"# {runnable_n} adım uygulanacak",
                },
            )
            for cmd in planned[:12]:
                preview = str(cmd).strip().splitlines()[0][:160] if str(cmd).strip() else ""
                if not preview:
                    continue
                prefix = "# " if preview.startswith("#") else "$ "
                publish_job_event(
                    int(job.id),  # type: ignore[arg-type]
                    {
                        "type": "command",
                        "hostname": run.hostname,
                        "line": f"{prefix}{preview.lstrip('# ').lstrip('$ ')}",
                    },
                )
            if len(planned) > 12:
                publish_job_event(
                    int(job.id),  # type: ignore[arg-type]
                    {
                        "type": "command",
                        "hostname": run.hostname,
                        "line": f"# … +{len(planned) - 12} satır daha (canlı çıktıda)",
                    },
                )

            # ASM cluster: stop peers if primary already failed
            if job.module == "asm" and (run.before_state or {}).get("role") == "peer" and primary_failed:
                run.status = JobRunStatus.skipped
                run.error_message = "Ana sunucu başarısız — peer atlandı"
                run.finished_at = datetime.now(UTC)
                session.add(run)
                skipped += 1
                session.commit()
                publish_job_event(
                    int(job.id),  # type: ignore[arg-type]
                    {"type": "run_skip", "hostname": run.hostname, "message": run.error_message},
                )
                continue

            ok, after, stdout, stderr = mod.apply_plan(
                session,
                server,
                job.action,
                dict(job.payload or {}),
                plan,
                job_id=job.id,  # type: ignore[arg-type]
            )
            run.after_state = after
            run.stdout = (stdout or "")[:5000]
            run.stderr = (stderr or "")[:5000]
            run.status = JobRunStatus.success if ok else JobRunStatus.failed
            run.error_message = "" if ok else (stderr.strip() or "Doğrulama başarısız")
            if stdout:
                publish_job_event(
                    int(job.id),  # type: ignore[arg-type]
                    {"type": "stdout", "hostname": run.hostname, "text": stdout[:4000]},
                )
            if stderr:
                publish_job_event(
                    int(job.id),  # type: ignore[arg-type]
                    {"type": "stderr", "hostname": run.hostname, "text": stderr[:2000]},
                )
            publish_job_event(
                int(job.id),  # type: ignore[arg-type]
                {
                    "type": "run_end",
                    "hostname": run.hostname,
                    "ok": ok,
                    "message": run.error_message or run.summary_tr,
                },
            )
            if ok:
                success += 1
            else:
                failed += 1
                if (run.before_state or {}).get("role") in {"primary", "single"}:
                    primary_failed = True
        except Exception as exc:  # noqa: BLE001
            run.status = JobRunStatus.failed
            run.error_message = str(exc)[:1024]
            failed += 1
            if (run.before_state or {}).get("role") in {"primary", "single"}:
                primary_failed = True
            try:
                from app.services.job_events import publish_job_event

                publish_job_event(
                    int(job.id),  # type: ignore[arg-type]
                    {"type": "error", "hostname": run.hostname, "message": str(exc)[:500]},
                )
            except Exception:
                pass

        run.finished_at = datetime.now(UTC)
        session.add(run)
        session.commit()

        write_audit(
            session,
            action=f"job.run.{job.module}.{job.action}",
            status=AuditStatus.success if run.status == JobRunStatus.success else AuditStatus.failed,
            message=run.summary_tr or run.error_message,
            user_id=job.created_by_user_id,
            username=job.created_by_username,
            role=job.created_by_role,
            client_ip=job.client_ip,
            target_server_id=run.target_server_id,
            hostname=run.hostname,
            ip=run.ip,
            talep_id=job.talep_id,
            job_id=job.id,
            before_state=run.before_state,
            after_state={
                k: v
                for k, v in (run.after_state or {}).items()
                if k != "artifact_path"  # don't put absolute path noise in audit much
            },
            output=(
                f"size={run.after_state.get('artifact_size_bytes') if run.after_state else None}\n"
                f"{run.error_message}"
            )[:4000],
        )

        job.progress_done = success + failed + skipped
        job.progress_total = max(1, len(ordered_runs))
        job.updated_at = datetime.now(UTC)
        session.add(job)
        session.commit()
        publish_job_progress(
            int(job.id),  # type: ignore[arg-type]
            done=job.progress_done,
            total=job.progress_total,
            label=f"sunucu bitti ({run.hostname})",
            hostname=run.hostname,
            session=None,  # zaten commit edildi
        )

    if failed == 0 and success > 0:
        final = JobStatus.success
    elif success == 0 and failed > 0:
        final = JobStatus.failed
    elif success > 0 and failed > 0:
        final = JobStatus.partial
    else:
        final = JobStatus.failed

    job.status = final
    job.finished_at = datetime.now(UTC)
    job.updated_at = datetime.now(UTC)
    job.progress_done = job.progress_total
    if isinstance(job.payload, dict) and "password" in job.payload:
        payload = dict(job.payload)
        payload["password"] = "***"
        job.payload = payload
    session.add(job)
    session.commit()
    session.refresh(job)

    publish_job_event(
        int(job.id),  # type: ignore[arg-type]
        {
            "type": "job_end",
            "job_id": job.id,
            "status": final.value,
            "success": success,
            "failed": failed,
            "skipped": skipped,
        },
    )

    write_audit(
        session,
        action=f"job.apply.finish.{job.module}.{job.action}",
        status=AuditStatus.success if final == JobStatus.success else AuditStatus.failed,
        message=f"İş bitti: {final.value} (ok={success}, fail={failed}, skip={skipped})",
        user_id=job.created_by_user_id,
        username=job.created_by_username,
        role=job.created_by_role,
        client_ip=job.client_ip,
        talep_id=job.talep_id,
        job_id=job.id,
    )
    return job
