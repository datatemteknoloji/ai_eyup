"""Subscription + geçici NFS local repo komut yardımcıları (packages / docker)."""

from __future__ import annotations

import shlex
from typing import Any

def subscription_wipe_script() -> str:
    return (
        "set +e\n"
        "subscription-manager unregister 2>/dev/null || true\n"
        "subscription-manager remove --all 2>/dev/null || true\n"
        "subscription-manager clean 2>/dev/null || true\n"
        "echo SUB_WIPE_OK\n"
    )


def subscription_register_script(org: str, activation_key: str) -> str:
    # activation_key yalnızca SSH komutunda; job payload/log'a yazılmamalı
    return (
        "set -e\n"
        f"subscription-manager register --org={shlex.quote(org)} "
        f"--activationkey={shlex.quote(activation_key)} --force\n"
        "echo SUB_REGISTER_OK\n"
    )


def local_repo_file_path(repo_id: str) -> str:
    safe = re_repo_id(repo_id)
    return f"/etc/yum.repos.d/dropt-{safe}.repo"


def re_repo_id(repo_id: str) -> str:
    import re

    s = re.sub(r"[^A-Za-z0-9_-]+", "-", (repo_id or "local").strip()) or "local"
    return s[:64]


def local_repo_mount_script(repo: Any) -> str:
    mp = (repo.mount_point or "").strip() or f"/mnt/dropt-repo-{repo.keyword}"
    nfs = (repo.nfs_path or "").strip()
    rid = re_repo_id(repo.repo_id or f"dropt-{repo.keyword}")
    suffix = (repo.baseurl_suffix or "").strip().lstrip("/")
    base = f"file://{mp}" + (f"/{suffix}" if suffix else "")
    repo_file = local_repo_file_path(rid)
    return (
        "set -e\n"
        f"mkdir -p {shlex.quote(mp)}\n"
        f"if mountpoint -q {shlex.quote(mp)}; then umount -l {shlex.quote(mp)} 2>/dev/null || true; fi\n"
        f"mount -t nfs -o ro,soft,timeo=30 {shlex.quote(nfs)} {shlex.quote(mp)}\n"
        f"cat > {shlex.quote(repo_file)} <<'EOF'\n"
        f"[{rid}]\n"
        f"name=Dropt local {repo.keyword}\n"
        f"baseurl={base}\n"
        "enabled=1\n"
        "gpgcheck=0\n"
        "EOF\n"
        f"echo LOCAL_REPO_MOUNTED:{shlex.quote(mp)}\n"
    )


def local_repo_cleanup_script(repo: Any) -> str:
    mp = (repo.mount_point or "").strip() or f"/mnt/dropt-repo-{repo.keyword}"
    rid = re_repo_id(repo.repo_id or f"dropt-{repo.keyword}")
    repo_file = local_repo_file_path(rid)
    return (
        "set +e\n"
        f"rm -f {shlex.quote(repo_file)}\n"
        f"if mountpoint -q {shlex.quote(mp)}; then umount {shlex.quote(mp)} || umount -l {shlex.quote(mp)}; fi\n"
        "echo LOCAL_REPO_CLEANED\n"
    )


def run_steps(
    session: Any,
    server: Any,
    cmds: list[str],
    *,
    redact_substrings: list[str] | None = None,
    on_step: Any | None = None,
    timeout: int = 300,
) -> tuple[bool, str, str]:
    """Komutları sırayla çalıştır; on_step(i, total, label, ok, stdout_chunk) opsiyonel."""
    from app.services.target_ssh import run_ssh

    # Yorum satırlarını sayma — gerçek çalışacak adımlar
    runnable = [str(c) for c in cmds if str(c).strip() and not str(c).strip().startswith("#")]
    total = max(1, len(runnable))
    out: list[str] = []
    err: list[str] = []
    step = 0
    redacts = [x for x in (redact_substrings or []) if x]

    def mask(text: str) -> str:
        t = text
        for s in redacts:
            if s:
                t = t.replace(s, "***")
        return t

    for cmd in cmds:
        raw = str(cmd)
        if not raw.strip() or raw.strip().startswith("#"):
            out.append(mask(raw.strip()))
            continue
        step += 1
        preview = mask(raw.strip().splitlines()[0][:160])
        out.append(f"\n--- step {step}/{total}: {preview} ---")
        if on_step:
            try:
                on_step(step - 1, total, preview, True, "", phase="start")
            except Exception:
                pass
        # dnf / post uzun sürebilir
        cmd_timeout = timeout
        low = raw.lower()
        if "dnf " in low or "yum " in low:
            cmd_timeout = max(timeout, 900)
        r = run_ssh(session, server, raw, timeout=cmd_timeout)
        chunk = ""
        if r.stdout:
            chunk = mask(r.stdout.rstrip())
            out.append(chunk)
        if r.stderr:
            serr = mask(r.stderr.rstrip())
            out.append(serr)
            err.append(serr)
            chunk = (chunk + "\n" + serr).strip()
        ok = bool(r.ok)
        if on_step:
            try:
                on_step(step, total, preview, ok, chunk, phase="end")
            except Exception:
                pass
        if not ok:
            fail = (
                f"[FAILED] step {step}/{total} exit={r.exit_code}: {preview}\n"
                f"{mask((r.stderr or r.stdout or '').strip()) or '(stderr/stdout boş)'}"
            )
            out.append(fail)
            err.append(fail)
            return False, "\n".join(out), "\n".join(err)
    if on_step:
        try:
            on_step(total, total, "done", True, "", phase="done")
        except Exception:
            pass
    return True, "\n".join(out), "\n".join(err)
