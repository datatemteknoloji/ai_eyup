from __future__ import annotations

import re
import shlex
from typing import Any

from sqlmodel import Session

from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.modules import pkg_common
from app.services import package_repo_store as store

ACTION_TITLES = {
    "install": "Paket kur",
}

_PKG_RE = re.compile(r"^[A-Za-z0-9._+-]+$")
_MOUNT_RE = re.compile(r"^/[A-Za-z0-9._/-]+$")


def job_summary(action: str, payload: dict[str, Any]) -> str:
    kw = (payload.get("keyword") or "").strip()
    if kw:
        return f"{ACTION_TITLES.get(action, action)}: [{kw}]"
    pkgs = payload.get("packages") or []
    if isinstance(pkgs, list):
        label = ", ".join(str(p) for p in pkgs[:5])
        if len(pkgs) > 5:
            label += f" (+{len(pkgs) - 5})"
    else:
        label = str(pkgs)
    return f"{ACTION_TITLES.get(action, action)}: {label}"


def _normalize_packages(payload: dict[str, Any], *, allow_empty: bool = False) -> list[str]:
    raw = payload.get("packages") or []
    if isinstance(raw, str):
        raw = [x.strip() for x in raw.replace(",", " ").split() if x.strip()]
    if not isinstance(raw, list):
        raw = []
    out: list[str] = []
    for p in raw:
        name = str(p).strip()
        if not name:
            continue
        if not _PKG_RE.match(name):
            raise ValueError(f"Geçersiz paket adı: {name}")
        out.append(name)
    if not out and not allow_empty:
        raise ValueError("En az bir paket adı gerekli")
    return out


def list_data_mount_candidates(session: Session, server: TargetServer) -> list[dict[str, Any]]:
    """Yalnızca kullanıcı datası için uygun FS: xfs/ext4 disk, root VG / tmpfs /run/shm hariç."""
    from app.modules import filesystem

    skip_prefixes = ("/run", "/dev", "/proc", "/sys", "/tmp", "/var/tmp", "/boot")
    skip_exact = {"/", "/home", "/var", "/usr", "/opt", "/root"}
    ok_fstypes = {"xfs", "ext4", "ext3"}

    rows = filesystem.list_filesystems(session, server)
    out: list[dict[str, Any]] = []
    for row in rows:
        mount_raw = str(row.get("mount") or "")
        mount = mount_raw.rstrip("/") or "/"
        fstype = str(row.get("fstype") or "").lower()
        src = str(row.get("source") or "")
        if mount in skip_exact or mount in filesystem.MOUNT_BLACKLIST:
            continue
        if any(mount == p or mount.startswith(p + "/") for p in skip_prefixes):
            continue
        if fstype not in ok_fstypes:
            continue
        if "overlay" in fstype or "tmpfs" in fstype or "ramfs" in fstype:
            continue
        if not src.startswith("/dev/"):
            continue
        if row.get("on_root_vg") or row.get("blacklisted"):
            continue
        out.append(
            {
                "mount": mount_raw,
                "fstype": row.get("fstype"),
                "size": row.get("size"),
                "avail": row.get("avail"),
                "use_pct": row.get("use_pct"),
            }
        )
    return out


def _build_install(session: Session, server: TargetServer, payload: dict[str, Any]) -> HostPlan:
    keyword = (payload.get("keyword") or "").strip().lower()
    osinfo = store.read_target_os(session, server)
    os_id, major = osinfo.get("os_id") or "", osinfo.get("version_major") or ""
    if not os_id or not major:
        raise ValueError(f"Hedef OS okunamadı ({osinfo.get('pretty')})")

    creds = store.get_subscription_creds_optional(session, os_id, major)
    local = None
    data_mount = (payload.get("data_mount") or "").strip().rstrip("/")
    package_version = (payload.get("package_version") or "").strip() or "latest"

    if keyword:
        local = store.find_local_repo(session, keyword, os_id, major)
        if local is None:
            raise ValueError(
                f"OS {os_id}:{major} için keyword reçetesi yok (keyword={keyword}). Settings → Repolar."
            )
        is_portal = store.is_portal_repo(local)
        is_nfs = store.is_nfs_repo(local)
        is_sub_src = store.is_subscription_repo(local)
        if local.needs_data_mount and not is_portal:
            if not data_mount or not _MOUNT_RE.match(data_mount) or ".." in data_mount:
                raise ValueError("Bu keyword için data mount seçimi zorunlu")
            allowed = {c["mount"] for c in list_data_mount_candidates(session, server)}
            if data_mount not in allowed:
                raise ValueError(f"Mount aday listesinde değil: {data_mount}")
        if is_portal:
            files = store.resolve_portal_rpm_files(local.portal_path, local.file_glob or "*.rpm")
            packages = _normalize_packages(payload, allow_empty=True)
        else:
            files = []
            packages = _normalize_packages(
                payload, allow_empty=bool((local.post_commands or "").strip())
            )
        if "{{docker_pkgs}}" in (local.post_commands or "") or keyword == "docker":
            store.docker_pkgs_line(package_version)
        if is_sub_src and not packages and not (local.post_commands or "").strip():
            raise ValueError(
                "Subscription keyword: paket listesi veya post_commands gerekli"
            )
    else:
        local = None
        is_portal = False
        is_nfs = False
        is_sub_src = False
        files = []
        packages = _normalize_packages(payload, allow_empty=False)

    cmds: list[str] = []
    if creds:
        cmds.append("# subscription wipe + register (activation key set)")
    else:
        cmds.append("# subscription atlandı (key yok — mevcut kayıt kullanılır)")
        if local and store.is_subscription_repo(local):
            cmds.append(
                "# uyarı: keyword kaynağı subscription; OS activation key yoksa "
                "hedefte zaten kayıtlı Satellite beklenir"
            )
    if local and is_portal:
        cmds.append(
            f"# portal RPM [{keyword}] {local.portal_path}/{local.file_glob or '*.rpm'} "
            f"({len(files)} dosya) → /tmp + dnf localinstall"
        )
        for f in files[:8]:
            cmds.append(f"#   · {f.rsplit('/', 1)[-1]}")
        if len(files) > 8:
            cmds.append(f"#   · … +{len(files) - 8}")
    elif local and is_nfs:
        cmds.append(f"# NFS local repo [{keyword}] {local.nfs_path}")
    elif local and is_sub_src:
        cmds.append(f"# subscription keyword [{keyword}] — dnf (Satellite) + post_commands")
    if packages and not (local and is_portal):
        cmds.append(f"dnf install -y {' '.join(packages)}")
    elif local and is_portal:
        cmds.append(f"dnf localinstall -y {local.file_glob or '*.rpm'}")
    if local and (local.post_commands or "").strip():
        cmds.append("# post_commands (keyword recipe)")
        preview = store.render_post_commands(
            local.post_commands,
            data_mount=data_mount,
            package_version=package_version,
        )
        for line in preview.splitlines()[:12]:
            if line.strip():
                cmds.append(line.strip()[:120])
    if local and is_portal:
        cmds.append("# cleanup /tmp portal RPM dir")
    elif local and is_nfs:
        cmds.append("# cleanup local NFS repo")
    if creds:
        cmds.append("# subscription wipe (after)")

    mode = f"[{keyword}]" if keyword else "general"
    ver_lbl = package_version if keyword else ""
    sub_lbl = "key" if creds else "no-key"
    src_lbl = store.source_label(local) if local else "dnf"
    return HostPlan(
        server_id=server.id,  # type: ignore[arg-type]
        hostname=server.hostname,
        ip=server.ip,
        ok=True,
        summary_tr=(
            f"{server.hostname}: {mode} install/{src_lbl} ({osinfo.get('pretty')}, sub={sub_lbl}"
            + (f", ver={ver_lbl}" if ver_lbl else "")
            + (f", data={data_mount}" if data_mount else "")
            + (f", rpms={len(files)}" if files else "")
            + ")"
        ),
        planned_commands=cmds,
        before_state={
            "action": "install",
            "keyword": keyword,
            "packages": packages,
            "data_mount": data_mount,
            "package_version": package_version,
            "os": osinfo,
            "use_subscription": bool(creds),
            "org": creds[0] if creds else "",
            "local_repo_id": local.id if local else None,
            "needs_data_mount": bool(local.needs_data_mount) if local else False,
            "source_type": (local.source_type if local else "") or "",
            "portal_files": [f.rsplit("/", 1)[-1] for f in files] if files else [],
        },
        risk_notes=(
            "Activation key yoksa subscription register atlanır (mevcut kayıt). "
            "NFS local repo finally umount edilir. "
            "Portal RPM: /tmp'ye kopyalanır, localinstall, sonra silinir. "
            "Subscription keyword: Satellite/dnf + aynı post_commands/path şablonları. "
            "Docker sürümü boş/latest → {{docker_pkgs}} latest."
        ),
    )


def build_plans(
    session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]
) -> list[HostPlan]:
    plans: list[HostPlan] = []
    if len(servers) > 1:
        for server in servers:
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=False,
                    summary_tr=f"{server.hostname}: Paket kur tek sunucuda çalışır",
                    error="Tek sunucu seçin",
                )
            )
        return plans
    for server in servers:
        try:
            if action != "install":
                raise ValueError(f"Bilinmeyen aksiyon: {action}")
            plans.append(_build_install(session, server, payload))
        except Exception as exc:  # noqa: BLE001
            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=False,
                    summary_tr=f"{server.hostname}: önizleme hatası",
                    error=str(exc),
                )
            )
    return plans


def apply_plan(
    session: Session,
    server: TargetServer,
    action: str,
    payload: dict[str, Any],
    plan: HostPlan,
    *,
    job_id: int = 0,
) -> tuple[bool, dict[str, Any], str, str]:
    _ = action
    if not plan.ok:
        return False, plan.before_state, "", plan.error

    from app.services.target_ssh import upload_files

    osinfo = store.read_target_os(session, server)
    os_id, major = osinfo.get("os_id") or "", osinfo.get("version_major") or ""
    keyword = str(plan.before_state.get("keyword") or "")
    packages = list(plan.before_state.get("packages") or [])
    data_mount = str(plan.before_state.get("data_mount") or "")
    package_version = str(plan.before_state.get("package_version") or "latest")

    creds = store.get_subscription_creds_optional(session, os_id, major)
    local = store.find_local_repo(session, keyword, os_id, major) if keyword else None
    is_portal = bool(local and store.is_portal_repo(local))
    is_nfs = bool(local and store.is_nfs_repo(local))
    redacts: list[str] = []
    if creds:
        redacts.append(creds[1])

    remote_rpm_dir = ""
    portal_files: list[str] = []
    if is_portal and local is not None:
        portal_files = store.resolve_portal_rpm_files(
            local.portal_path, local.file_glob or "*.rpm"
        )
        safe_kw = re.sub(r"[^a-zA-Z0-9_-]+", "-", keyword or "rpm")[:40]
        remote_rpm_dir = f"/tmp/dropt-rpm-{job_id or 0}-{safe_kw}"

    cmds: list[str] = []
    if creds:
        cmds.append(pkg_common.subscription_wipe_script())
        cmds.append(pkg_common.subscription_register_script(creds[0], creds[1]))

    if local and is_nfs:
        cmds.append(pkg_common.local_repo_mount_script(local))

    if is_portal and remote_rpm_dir:
        glob_pat = (local.file_glob if local else None) or "*.rpm"
        cmds.append(
            "set -e\n"
            f"cd {shlex.quote(remote_rpm_dir)}\n"
            f"ls -la\n"
            f"dnf localinstall -y {shlex.quote(glob_pat)}\n"
            "echo DNF_LOCALINSTALL_OK\n"
        )
    elif packages:
        pkg_line = " ".join(shlex.quote(str(p)) for p in packages)
        cmds.append(f"set -e\ndnf install -y {pkg_line}\necho DNF_INSTALL_OK\n")

    if local and (local.post_commands or "").strip():
        body = store.render_post_commands(
            local.post_commands,
            data_mount=data_mount,
            package_version=package_version,
        )
        cmds.append("set -e\n" + body + "\necho POST_COMMANDS_OK\n")

    cleanup_cmds: list[str] = []
    if is_portal and remote_rpm_dir:
        cleanup_cmds.append(
            f"set +e\nrm -rf {shlex.quote(remote_rpm_dir)}\necho PORTAL_RPM_CLEANED\n"
        )
    elif local and is_nfs:
        cleanup_cmds.append(pkg_common.local_repo_cleanup_script(local))
    if creds:
        cleanup_cmds.append(pkg_common.subscription_wipe_script())

    all_cmds = list(cmds) + cleanup_cmds
    runnable_n = sum(1 for c in all_cmds if str(c).strip() and not str(c).strip().startswith("#"))
    # portal upload = ekstra adım
    upload_steps = 1 if (is_portal and portal_files) else 0
    total_steps = runnable_n + upload_steps

    def _publish_progress(done: int, total: int, label: str) -> None:
        if not job_id:
            return
        from app.models.job import Job
        from app.services.job_events import publish_job_event

        pct = int(round(100.0 * done / total)) if total else 0
        try:
            job = session.get(Job, job_id)
            if job is not None:
                job.progress_done = done
                job.progress_total = total
                session.add(job)
                session.commit()
        except Exception:
            try:
                session.rollback()
            except Exception:
                pass
        publish_job_event(
            int(job_id),
            {
                "type": "progress",
                "hostname": server.hostname,
                "done": done,
                "total": total,
                "percent": min(100, pct),
                "label": label[:200],
            },
        )

    def on_step(done: int, total: int, label: str, ok: bool, chunk: str, phase: str = "") -> None:
        _ = (ok, chunk, total)
        abs_done = upload_steps + done
        if phase == "start":
            _publish_progress(abs_done, total_steps, f"çalışıyor: {label}")
        elif phase in {"end", "done"}:
            _publish_progress(abs_done, total_steps, label if phase == "done" else f"bitti: {label}")

    logs_pre = ""
    if is_portal and portal_files and remote_rpm_dir:
        if job_id:
            _publish_progress(0, total_steps, "RPM dosyaları yükleniyor…")
        try:
            uploaded = upload_files(session, server, portal_files, remote_rpm_dir, timeout=600)
            logs_pre = (
                f"--- portal upload → {remote_rpm_dir} ---\n"
                + "\n".join(uploaded)
                + f"\nUPLOADED {len(uploaded)} file(s)\n"
            )
            if job_id:
                _publish_progress(upload_steps, total_steps, f"{len(uploaded)} RPM yüklendi")
        except Exception as exc:  # noqa: BLE001
            return (
                False,
                {**plan.before_state, "phase": "upload"},
                logs_pre,
                f"Portal RPM yükleme başarısız: {exc}",
            )

    if job_id and runnable_n:
        _publish_progress(upload_steps, total_steps, "başlıyor")

    ok, out, err = pkg_common.run_steps(
        session,
        server,
        cmds,
        redact_substrings=redacts,
        on_step=on_step,
        timeout=300,
    )
    out = (logs_pre + "\n" + out).strip() if logs_pre else out

    cleanup_ok = True
    if cleanup_cmds:
        main_n = sum(1 for c in cmds if str(c).strip() and not str(c).strip().startswith("#"))

        def on_cleanup(done: int, total: int, label: str, ok_s: bool, chunk: str, phase: str = "") -> None:
            _ = (ok_s, total)
            abs_done = upload_steps + main_n + done
            on_step(abs_done - upload_steps, runnable_n, label, ok_s, chunk, phase=phase)

        c_ok, c_out, c_err = pkg_common.run_steps(
            session,
            server,
            cleanup_cmds,
            redact_substrings=redacts,
            on_step=on_cleanup,
            timeout=120,
        )
        cleanup_ok = c_ok
        out = out + "\n" + c_out
        if c_err:
            err = (err + "\n" + c_err).strip()

    if job_id:
        _publish_progress(
            total_steps if ok else max(0, total_steps - 1),
            total_steps,
            "tamam" if ok else "hata",
        )

    after = {
        **plan.before_state,
        "applied_ok": ok,
        "cleanup_ok": cleanup_ok,
        "remote_rpm_dir": remote_rpm_dir or None,
    }
    return ok, after, out, err
