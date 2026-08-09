from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from app.api.deps import get_current_user
from app.core.database import get_session
from app.models.server import TargetServer
from app.models.user import User
import shlex

from app.modules import asm, filesystem, limits, packages, path_perms, services, sudoers, sysctl, vlan
from app.modules import pkg_common
from app.services import package_repo_store as pkg_store

router = APIRouter(prefix="/ops", tags=["ops"])


@router.get("/sudo-templates")
def sudo_templates(_user: User = Depends(get_current_user)) -> list:
    return sudoers.list_templates()


@router.get("/servers/{server_id}/sudo-rules")
def server_sudo_rules(
    server_id: int,
    who: str = Query("", description="opsiyonel: user veya %group filtre"),
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Custom sudoers kuralları (Defaults / root / %wheel hariç)."""
    server = _server_or_404(session, server_id)
    try:
        if who.strip():
            rules = sudoers.list_rules_for_who(session, server, who.strip())
        else:
            rules = sudoers.list_custom_rules(session, server)
        return {"server_id": server.id, "hostname": server.hostname, "rules": rules}
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/sudo-lookup")
def sudo_lookup(
    hostname: str = Query(..., min_length=1, max_length=255),
    who: str = Query(..., min_length=1, max_length=128, description="user veya %group"),
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Benzer sunucudan yetki kopyası: envanter hostname + user/group → kurallar."""
    server = sudoers.find_server_by_hostname(session, hostname)
    if server is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Envanterde sunucu yok: {hostname}",
        )
    try:
        rules = sudoers.list_rules_for_who(session, server, who.strip())
        return {
            "server_id": server.id,
            "hostname": server.hostname,
            "who": who.strip(),
            "rules": rules,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/servers/{server_id}/sudo-which")
def server_sudo_which(
    server_id: int,
    q: str = Query(..., min_length=1, max_length=128, description="kısa komut adı"),
    as_user: str = Query("", max_length=128, description="opsiyonel: login user (yoksa/empty→root)"),
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Kısa komutu user PATH'inde ara; yoksa root fallback."""
    server = _server_or_404(session, server_id)
    try:
        result = sudoers.resolve_command_path(session, server, q, as_user=as_user)
        return {"server_id": server.id, "hostname": server.hostname, **result}
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/path-whitelist")
def path_whitelist(_user: User = Depends(get_current_user)) -> list:
    return path_perms.list_whitelist()


@router.get("/path-modes")
def path_modes(_user: User = Depends(get_current_user)) -> list:
    return path_perms.list_mode_templates()


@router.get("/sysctl-templates")
def sysctl_templates(_user: User = Depends(get_current_user)) -> list:
    return sysctl.list_templates()


@router.get("/sysctl-allowed")
def sysctl_allowed(_user: User = Depends(get_current_user)) -> list:
    return sysctl.list_allowed_params()


@router.get("/limits-items")
def limits_items(_user: User = Depends(get_current_user)) -> list:
    return limits.list_allowed_items()


@router.get("/limits-types")
def limits_types(_user: User = Depends(get_current_user)) -> list:
    return limits.list_limit_types()


@router.get("/vlan-pools")
def vlan_pools(_user: User = Depends(get_current_user)) -> list:
    return vlan.list_pools()


@router.get("/servers/{server_id}/filesystems")
def server_filesystems(
    server_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list:
    server = session.get(TargetServer, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sunucu bulunamadı")
    try:
        return filesystem.list_filesystems(session, server)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/servers/{server_id}/services")
def server_services(
    server_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Custom systemd unit'leri (/etc/systemd/system/*.service)."""
    server = _server_or_404(session, server_id)
    try:
        rows = services.list_services(session, server)
        return {
            "server_id": server.id,
            "hostname": server.hostname,
            "services": rows,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/servers/{server_id}/interfaces")
def server_interfaces(
    server_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list:
    server = session.get(TargetServer, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sunucu bulunamadı")
    try:
        return vlan.list_interfaces(session, server)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/servers/{server_id}/network-interfaces")
def server_network_interfaces(
    server_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Add Network: UP + usable NICs (docker/ilo/idrac/mgmt hariç)."""
    from app.modules import network as network_mod

    server = _server_or_404(session, server_id)
    try:
        rows = network_mod.list_usable_interfaces(session, server)
        visible = [r for r in rows if not r.get("hidden")]
        bond = network_mod.next_bond_name(session, server)
        return {
            "server_id": server.id,
            "hostname": server.hostname,
            "interfaces": visible,
            "next_bond_name": bond,
            "bond_modes": [
                {"value": "1", "label": "mode=1 active-backup"},
                {"value": "4", "label": "mode=4 802.3ad (LACP)"},
                {"value": "6", "label": "mode=6 balance-alb"},
            ],
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/servers/{server_id}/ip-change")
def server_ip_change_inventory(
    server_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """IP Değişikliği: IP taşıyan iface listesi + ana IP (default route + nslookup) + resolv."""
    from app.modules import network as network_mod

    server = _server_or_404(session, server_id)
    try:
        return network_mod.list_ip_change_inventory(session, server)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/servers/{server_id}/sysctl")
def server_sysctl(
    server_id: int,
    keys: str = Query("", description="comma-separated keys"),
    refresh: bool = Query(False, description="true = cache atla, SSH ile yeniden oku"),
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    server = session.get(TargetServer, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sunucu bulunamadı")
    key_list = [k.strip() for k in keys.split(",") if k.strip()] or None
    try:
        return sysctl.get_current_values(session, server, key_list, refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/servers/{server_id}/limits")
def server_limits(
    server_id: int,
    refresh: bool = Query(False, description="true = cache atla, SSH ile yeniden oku"),
    user: str = Query("", description="opsiyonel: su - user ile ulimit doğrula"),
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    server = session.get(TargetServer, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sunucu bulunamadı")
    try:
        return limits.get_current_limits(
            session,
            server,
            refresh=refresh,
            verify_user=(user.strip() or None),
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/servers/{server_id}/volume-groups")
def server_volume_groups(
    server_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> list:
    server = session.get(TargetServer, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sunucu bulunamadı")
    try:
        return filesystem.list_volume_groups(session, server)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/servers/{server_id}/filesystem-inventory")
def server_filesystem_inventory(
    server_id: int,
    refresh: bool = Query(False, description="true = Redis cache atla, SSH ile yeniden oku"),
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """FileSystem Management: VG + FS + partitionsuz diskler + root VG kilidi."""
    server = session.get(TargetServer, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sunucu bulunamadı")
    try:
        return filesystem.list_inventory(session, server, refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/servers/{server_id}/asm-disks")
def server_asm_disks(
    server_id: int,
    refresh: bool = Query(False, description="true = SCSI rescan + multipath yeniden oku"),
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    server = session.get(TargetServer, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sunucu bulunamadı")
    try:
        return asm.scan_disks(session, server, refresh=refresh)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/asm-seq-next")
def asm_seq_next(
    prefix: str = Query(..., min_length=1, max_length=17, description="Alias öneki (örn. DATA)"),
    server_ids: str = Query(..., description="Virgülle sunucu id'leri"),
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Mevcut ASM_/mapper adlarından max indeks + 1 (gap doldurulmaz)."""
    prefix = prefix.strip()
    if not asm.ALIAS_PREFIX_RE.match(prefix):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Alias öneki geçersiz (örn. DATA; en fazla 17 karakter)",
        )
    ids: list[int] = []
    for part in server_ids.split(","):
        part = part.strip()
        if not part:
            continue
        try:
            ids.append(int(part))
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Geçersiz server_id: {part}",
            ) from exc
    ids = ids[:2]
    if not ids:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="server_ids zorunlu")
    servers: list[TargetServer] = []
    for sid in ids:
        server = session.get(TargetServer, sid)
        if server is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Sunucu bulunamadı: {sid}")
        servers.append(server)
    try:
        used_max = asm.max_seq_index_for_servers(session, servers, prefix)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    next_index = used_max + 1
    sample_alias, sample_asm = asm.sequential_aliases(prefix, next_index)
    return {
        "prefix": prefix,
        "used_max": used_max,
        "next_index": next_index,
        "sample_alias": sample_alias,
        "sample_asm_name": sample_asm,
    }


def _server_or_404(session: Session, server_id: int) -> TargetServer:
    server = session.get(TargetServer, server_id)
    if server is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Sunucu bulunamadı")
    return server


@router.get("/servers/{server_id}/package-context")
def server_package_context(
    server_id: int,
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Hedef OS + bu OS için keyword chip'leri + subscription var mı."""
    server = _server_or_404(session, server_id)
    try:
        osinfo = pkg_store.read_target_os(session, server)
        os_id, major = osinfo.get("os_id") or "", osinfo.get("version_major") or ""
        creds = pkg_store.get_subscription_creds_optional(session, os_id, major)
        keywords = []
        for row in pkg_store.list_local_repos(session):
            if not row.enabled:
                continue
            if not pkg_store.os_matches(row.os_id, os_id):
                continue
            if (row.os_major or "") != (major or ""):
                continue
            keywords.append(pkg_store.local_repo_public(row))
        return {
            "os": osinfo,
            "subscription_key_set": bool(creds),
            "keywords": keywords,
            "data_mounts": packages.list_data_mount_candidates(session, server),
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/servers/{server_id}/dnf-search")
def server_dnf_search(
    server_id: int,
    q: str = Query(..., min_length=1, max_length=128),
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """dnf search — key varsa geçici register; yoksa mevcut subscription ile ara."""
    server = _server_or_404(session, server_id)
    query = q.strip()
    if "*" not in query and "?" not in query:
        query = f"{query}*"
    from app.services.target_ssh import run_ssh

    osinfo = pkg_store.read_target_os(session, server)
    os_id, major = osinfo.get("os_id") or "", osinfo.get("version_major") or ""
    creds = pkg_store.get_subscription_creds_optional(session, os_id, major)
    did_register = False
    try:
        if creds:
            for c in (
                pkg_common.subscription_wipe_script(),
                pkg_common.subscription_register_script(creds[0], creds[1]),
            ):
                r = run_ssh(session, server, c, timeout=120)
                if not r.ok and "register" in c:
                    raise ValueError((r.stderr or r.stdout or "register failed")[:400])
            did_register = True
        search = run_ssh(
            session,
            server,
            f"dnf search -q {shlex.quote(query)} 2>/dev/null | head -n 80\n",
            timeout=120,
        )
        results: list[dict[str, str]] = []
        for line in (search.stdout or "").splitlines():
            line = line.strip()
            if not line or line.endswith(":") or "Matched" in line:
                continue
            if " : " in line:
                left, summary = line.split(" : ", 1)
                name = left.split(".")[0].strip()
            else:
                name, summary = line.split()[0], ""
            if name and name not in {x["name"] for x in results}:
                results.append({"name": name, "summary": summary.strip()[:200]})
        return {
            "query": query,
            "os": osinfo,
            "subscription_used": did_register,
            "results": results,
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    finally:
        if did_register:
            try:
                run_ssh(session, server, pkg_common.subscription_wipe_script(), timeout=60)
            except Exception:
                pass


@router.get("/servers/{server_id}/package-versions")
def server_package_versions(
    server_id: int,
    keyword: str = Query("docker", min_length=1, max_length=64),
    package: str = Query("docker-ce", min_length=1, max_length=64),
    _user: User = Depends(get_current_user),
    session: Session = Depends(get_session),
) -> dict:
    """Geçici local repo (+ opsiyonel sub) ile paket sürüm listesi; afterward cleanup."""
    import re

    from app.services.target_ssh import run_ssh

    server = _server_or_404(session, server_id)
    osinfo = pkg_store.read_target_os(session, server)
    os_id, major = osinfo.get("os_id") or "", osinfo.get("version_major") or ""
    local = pkg_store.find_local_repo(session, keyword.strip().lower(), os_id, major)
    if local is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND,
            f"OS {os_id}:{major} için keyword={keyword} local repo yok",
        )
    creds = pkg_store.get_subscription_creds_optional(session, os_id, major)
    did_register = False
    try:
        if creds:
            for c in (
                pkg_common.subscription_wipe_script(),
                pkg_common.subscription_register_script(creds[0], creds[1]),
            ):
                r = run_ssh(session, server, c, timeout=120)
                if not r.ok and "register" in c:
                    raise ValueError((r.stderr or r.stdout or "register failed")[:400])
            did_register = True
        mr = run_ssh(session, server, pkg_common.local_repo_mount_script(local), timeout=120)
        if not mr.ok:
            raise ValueError((mr.stderr or mr.stdout or "NFS mount fail")[:400])
        listed = run_ssh(
            session,
            server,
            (
                f"dnf list --showduplicates {shlex.quote(package)} 2>/dev/null "
                f"| sed -n '/^{re.escape(package)}\\./p' | awk '{{print $2}}' | sort -V | uniq\n"
                "echo VERSIONS_END\n"
            ),
            timeout=180,
        )
        versions: list[str] = []
        for line in (listed.stdout or "").splitlines():
            if line.strip() == "VERSIONS_END":
                break
            v = line.strip()
            if not v:
                continue
            m = re.search(r"(?:^|:)(\d+\.\d+\.\d+(?:-\d+)?)(?:\.|$)", v)
            if m:
                ver = m.group(1).split("-")[0]
                if ver not in versions:
                    versions.append(ver)
        return {
            "keyword": keyword,
            "package": package,
            "os": osinfo,
            "versions": versions,
            "latest": versions[-1] if versions else "",
        }
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    finally:
        try:
            run_ssh(session, server, pkg_common.local_repo_cleanup_script(local), timeout=60)
        except Exception:
            pass
        if did_register:
            try:
                run_ssh(session, server, pkg_common.subscription_wipe_script(), timeout=60)
            except Exception:
                pass
