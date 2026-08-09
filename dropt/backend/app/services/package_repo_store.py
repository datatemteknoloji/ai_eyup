from __future__ import annotations

import re
from typing import Any

from sqlmodel import Session, select

from app.models.package_repos import PkgLocalRepo, PkgSubscription
from app.models.server import TargetServer
from app.services.credential_manager import CredentialManager
from app.services.target_ssh import run_ssh

_OS_ID_ALIASES = {
    "rhel": ("rhel", "red hat", "redhat"),
    "centos": ("centos",),
    "rocky": ("rocky",),
    "almalinux": ("almalinux", "alma"),
    "ol": ("ol", "oracle"),
}


def encrypt_activation_key(plain: str) -> str:
    return CredentialManager().encrypt(plain.strip())


def decrypt_activation_key(token: str) -> str:
    return CredentialManager().decrypt(token)


def _parse_os_release(stdout: str) -> tuple[str, str, str]:
    data: dict[str, str] = {}
    for line in stdout.splitlines():
        if "=" not in line:
            continue
        k, v = line.split("=", 1)
        data[k.strip()] = v.strip().strip('"')
    os_id = (data.get("ID") or "").lower()
    ver = data.get("VERSION_ID") or ""
    major = ver.split(".")[0] if ver else ""
    pretty = data.get("PRETTY_NAME") or f"{os_id} {ver}".strip()
    return os_id, major, pretty


def parse_os_pretty(text: str) -> tuple[str, str]:
    t = (text or "").lower()
    os_id = ""
    for canon, aliases in _OS_ID_ALIASES.items():
        if any(a in t for a in aliases):
            os_id = canon
            break
    m = re.search(r"\b([0-9]{1,2})(?:\.\d+)?\b", text or "")
    major = m.group(1) if m else ""
    return os_id, major


def read_target_os(session: Session, server: TargetServer) -> dict[str, str]:
    r = run_ssh(session, server, "cat /etc/os-release 2>/dev/null || true", timeout=15)
    os_id, major, pretty = _parse_os_release(r.stdout or "")
    if not os_id and server.os_pretty:
        os_id, major = parse_os_pretty(server.os_pretty)
        pretty = server.os_pretty
    return {"os_id": os_id, "version_major": major, "pretty": pretty}


def os_matches(configured: str, target: str) -> bool:
    p = (configured or "").strip().lower()
    t = (target or "").strip().lower()
    if not p or not t:
        return False
    if p == t:
        return True
    aliases = _OS_ID_ALIASES.get(p, (p,))
    return any(a in t or t == a for a in aliases)


def os_key(os_id: str, major: str) -> str:
    return f"{(os_id or '').lower()}:{(major or '').strip()}"


def inventory_os_options(session: Session) -> list[dict[str, Any]]:
    """Envanterdeki sunuculardan distinct OS major listesi (+ bilinen rhel 8/9)."""
    rows = list(session.exec(select(TargetServer)).all())
    counts: dict[tuple[str, str], dict[str, Any]] = {}
    for s in rows:
        os_id, major = parse_os_pretty(s.os_pretty or "")
        if not os_id or not major:
            continue
        k = (os_id, major)
        if k not in counts:
            label = {
                "rhel": "Red Hat Enterprise Linux",
                "centos": "CentOS",
                "rocky": "Rocky Linux",
                "almalinux": "AlmaLinux",
                "ol": "Oracle Linux",
            }.get(os_id, os_id)
            counts[k] = {
                "os_id": os_id,
                "os_major": major,
                "label": f"{label} {major}",
                "value": os_key(os_id, major),
                "count": 0,
            }
        counts[k]["count"] += 1
    # Bilinen majörler envanter boş olsa bile seçilebilir
    for major in ("8", "9", "10"):
        k = ("rhel", major)
        if k not in counts:
            counts[k] = {
                "os_id": "rhel",
                "os_major": major,
                "label": f"Red Hat Enterprise Linux {major}",
                "value": os_key("rhel", major),
                "count": 0,
            }
    return sorted(counts.values(), key=lambda x: (x["os_id"], int(x["os_major"] or 0)))


def list_subscriptions(session: Session) -> list[PkgSubscription]:
    return list(session.exec(select(PkgSubscription).order_by(PkgSubscription.os_id, PkgSubscription.os_major)).all())


def list_local_repos(session: Session) -> list[PkgLocalRepo]:
    return list(
        session.exec(
            select(PkgLocalRepo).order_by(PkgLocalRepo.keyword, PkgLocalRepo.os_id, PkgLocalRepo.os_major)
        ).all()
    )


def subscription_public(row: PkgSubscription) -> dict[str, Any]:
    return {
        "id": row.id,
        "label": row.label or f"{row.os_id}-{row.os_major}",
        "os_id": row.os_id,
        "os_major": row.os_major,
        "os_value": os_key(row.os_id, row.os_major),
        "org": row.org,
        "activation_key_set": bool(row.activation_key_enc),
        "enabled": row.enabled,
    }


def local_repo_public(row: PkgLocalRepo) -> dict[str, Any]:
    st = (row.source_type or "nfs").strip().lower() or "nfs"
    return {
        "id": row.id,
        "keyword": row.keyword,
        "label": row.label or row.keyword,
        "os_id": row.os_id,
        "os_major": row.os_major,
        "os_value": os_key(row.os_id, row.os_major),
        "source_type": st,
        "nfs_path": row.nfs_path or "",
        "mount_point": row.mount_point or "",
        "repo_id": row.repo_id or "",
        "baseurl_suffix": row.baseurl_suffix or "",
        "portal_path": getattr(row, "portal_path", None) or "",
        "file_glob": getattr(row, "file_glob", None) or "*.rpm",
        "needs_data_mount": bool(row.needs_data_mount),
        "post_commands": row.post_commands or "",
        "enabled": row.enabled,
    }


def is_portal_repo(row: PkgLocalRepo) -> bool:
    return (row.source_type or "nfs").strip().lower() == "portal_files"


def is_nfs_repo(row: PkgLocalRepo) -> bool:
    return (row.source_type or "nfs").strip().lower() == "nfs"


def is_subscription_repo(row: PkgLocalRepo) -> bool:
    return (row.source_type or "").strip().lower() == "subscription"


def source_label(row: PkgLocalRepo | None) -> str:
    if row is None:
        return "dnf"
    st = (row.source_type or "nfs").strip().lower() or "nfs"
    if st == "portal_files":
        return "portal"
    if st == "subscription":
        return "subscription"
    return "nfs"


# Portal RPM kökü — path bu dizin altında olmalı
PORTAL_RPM_ROOT = "/var/lib/dropt/rpms"


def validate_portal_path(portal_path: str) -> str:
    from pathlib import Path

    raw = (portal_path or "").strip()
    if not raw:
        raise ValueError("Portal path zorunlu")
    if ".." in raw or not raw.startswith("/"):
        raise ValueError("Portal path mutlak olmalı ve .. içermemeli")
    root = Path(PORTAL_RPM_ROOT).resolve()
    try:
        resolved = Path(raw).resolve()
    except Exception as exc:
        raise ValueError(f"Portal path çözülemedi: {exc}") from exc
    try:
        resolved.relative_to(root)
    except ValueError as exc:
        raise ValueError(
            f"Portal path yalnızca {PORTAL_RPM_ROOT}/ altında olabilir"
        ) from exc
    if not resolved.is_dir():
        raise ValueError(f"Portal path dizin değil veya yok: {resolved}")
    return str(resolved)


def resolve_portal_rpm_files(portal_path: str, file_glob: str) -> list[str]:
    """portal_path altındaki glob eşleşen .rpm dosyaları (mutlak path)."""
    from pathlib import Path

    base = Path(validate_portal_path(portal_path))
    pattern = (file_glob or "*.rpm").strip() or "*.rpm"
    if "/" in pattern or ".." in pattern:
        raise ValueError("file_glob yalnızca dosya kalıbı olmalı (örn. snowlinux*.rpm)")
    files = sorted(p for p in base.glob(pattern) if p.is_file() and p.suffix.lower() == ".rpm")
    if not files:
        # glob *rpm değilse yine de eşleşen dosyaları al
        files = sorted(p for p in base.glob(pattern) if p.is_file())
    if not files:
        raise ValueError(f"Portal path'te eşleşen dosya yok: {base}/{pattern}")
    return [str(p) for p in files]


def list_keywords(session: Session) -> list[dict[str, Any]]:
    """UI chip'leri: unique keyword + needs_data_mount + source_type özeti."""
    by_kw: dict[str, dict[str, Any]] = {}
    for row in list_local_repos(session):
        if not row.enabled:
            continue
        kw = row.keyword.strip().lower()
        st = (row.source_type or "nfs").strip().lower() or "nfs"
        if kw not in by_kw:
            by_kw[kw] = {
                "keyword": kw,
                "label": row.label or kw,
                "needs_data_mount": bool(row.needs_data_mount),
                "source_type": st,
            }
        else:
            by_kw[kw]["needs_data_mount"] = by_kw[kw]["needs_data_mount"] or bool(
                row.needs_data_mount
            )
            # karışık tip varsa işaretle
            if by_kw[kw]["source_type"] != st:
                by_kw[kw]["source_type"] = "mixed"
    return sorted(by_kw.values(), key=lambda x: x["keyword"])



def find_subscription_for_os(
    session: Session, os_id: str, major: str
) -> PkgSubscription | None:
    for row in list_subscriptions(session):
        if not row.enabled:
            continue
        if os_matches(row.os_id, os_id) and (row.os_major or "") == (major or ""):
            return row
    return None


def find_local_repo(
    session: Session, keyword: str, os_id: str, major: str
) -> PkgLocalRepo | None:
    kw = (keyword or "").strip().lower()
    for row in list_local_repos(session):
        if not row.enabled:
            continue
        if row.keyword.strip().lower() != kw:
            continue
        if os_matches(row.os_id, os_id) and (row.os_major or "") == (major or ""):
            return row
    return None


def get_subscription_creds_optional(
    session: Session, os_id: str, major: str
) -> tuple[str, str] | None:
    """Key yoksa None → wipe/register atlanır."""
    sub = find_subscription_for_os(session, os_id, major)
    if sub is None or not sub.enabled:
        return None
    if not (sub.activation_key_enc or "").strip():
        return None
    if not (sub.org or "").strip():
        return None
    key = decrypt_activation_key(sub.activation_key_enc)
    if not key.strip():
        return None
    return sub.org.strip(), key.strip()


def docker_pkgs_line(version: str = "") -> str:
    """Latest = sürümsüz metapaket; pin = docker-ce-X + docker-ce-cli-X."""
    ver = (version or "").strip()
    if not ver or ver.lower() in {"latest", "last"}:
        return (
            "docker-ce docker-ce-cli containerd.io "
            "docker-buildx-plugin docker-compose-plugin"
        )
    # basit semver / rpm sürüm
    import re

    if not re.match(r"^[0-9]+(\.[0-9]+){1,3}(-[0-9]+)?$", ver):
        raise ValueError(f"Geçersiz docker sürümü: {ver}")
    return (
        f"docker-ce-{ver} docker-ce-cli-{ver} containerd.io "
        "docker-buildx-plugin docker-compose-plugin"
    )


def _pin_hardcoded_docker_pkgs(text: str, version: str) -> str:
    """Eski şablonlarda sabit 'docker-ce …' varsa seçilen sürüme çevir.

    {{docker_pkgs}} yoksa bile UI'daki version seçimi etkili olsun.
    docker-ce-cli önce pinlenir (docker-ce prefix çakışmasın).
    """
    import re

    ver = (version or "").strip()
    if not ver or ver.lower() in {"latest", "last"}:
        return text
    pinned = docker_pkgs_line(ver)
    # Tam metapaket satırı (boşluk varyasyonları)
    text = re.sub(
        r"docker-ce\s+docker-ce-cli\s+containerd\.io\s+"
        r"docker-buildx-plugin\s+docker-compose-plugin",
        pinned,
        text,
    )
    # Tek tek sürümsüz paket adları (zaten docker-ce-28.x ise dokunma)
    text = re.sub(r"(?<![\w.-])docker-ce-cli(?![\w.-])", f"docker-ce-cli-{ver}", text)
    text = re.sub(r"(?<![\w.-])docker-ce(?![\w.-])", f"docker-ce-{ver}", text)
    return text


def render_post_commands(
    template: str,
    *,
    data_mount: str = "",
    package_version: str = "",
) -> str:
    dm = (data_mount or "").rstrip("/")
    text = template or ""
    try:
        docker_pkgs = docker_pkgs_line(package_version)
    except ValueError:
        docker_pkgs = docker_pkgs_line("")
    ver = (package_version or "").strip()
    ver_suffix = "" if not ver or ver.lower() in {"latest", "last"} else f"-{ver}"
    repl = {
        "{{data_mount}}": dm,
        "{{docker_dir}}": f"{dm}/docker" if dm else "",
        "{{containerd_dir}}": f"{dm}/containerd" if dm else "",
        "{{docker_pkgs}}": docker_pkgs,
        "{{pkg_ver}}": ver if ver and ver.lower() not in {"latest", "last"} else "",
        "{{pkg_ver_suffix}}": ver_suffix,
    }
    for k, v in repl.items():
        text = text.replace(k, v)
    # Placeholder kullanılmayan eski local-repo şablonları için
    if ver and ver.lower() not in {"latest", "last"}:
        try:
            text = _pin_hardcoded_docker_pkgs(text, ver)
        except ValueError:
            pass
    return text
