from __future__ import annotations

import re
import shlex
from typing import Any

from sqlmodel import Session

from app.models.server import TargetServer
from app.modules.base import HostPlan
from app.services.target_ssh import run_ssh

ACTION_TITLES = {
    "set": "Hostname değiştir",
}

_SHORT_RE = re.compile(r"^[a-zA-Z0-9]([a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$")
_DOMAIN_RE = re.compile(r"^[a-zA-Z0-9.-]+$")

# Centrify adjoin computer container (sabit)
_CENTRIFY_CONTAINER = "kfs.local/Centrify/Unix Servers/Redhat"


def job_summary(action: str, payload: dict[str, Any]) -> str:
    title = ACTION_TITLES.get(action, action)
    short = (payload.get("short_name") or "").strip()
    domain = (payload.get("domain") or "").strip()
    fqdn = f"{short}.{domain}" if domain else short
    return f"{title}: → {fqdn}" if short else title


def _run(session: Session, server: TargetServer, command: str, *, timeout: float = 30.0):
    return run_ssh(session, server, command, timeout=timeout)


def split_fqdn(fqdn: str) -> tuple[str, str]:
    """
    FQDN → (short, domain). Domain = ilk '.' sonrası tüm kısım.
    örn. test.datatem.local → (test, datatem.local)
    """
    name = (fqdn or "").strip().lower().rstrip(".")
    if not name:
        return "", ""
    if "." not in name:
        return name, ""
    short, domain = name.split(".", 1)
    return short, domain


def read_hostname_state(session: Session, server: TargetServer) -> dict[str, Any]:
    script = r"""
set +e
echo "SHORT=$(hostname -s 2>/dev/null)"
echo "FQDN=$(hostname -f 2>/dev/null)"
echo "HOSTS_BEGIN"
grep -E "[[:space:]]" /etc/hosts 2>/dev/null | head -n 40
echo "HOSTS_END"
echo "WARN_BEGIN"
ps -eo comm= 2>/dev/null | grep -Eiq 'oracle|sap|hana|pacemaker|corosync|db2' && echo CLUSTER_HINT=1 || echo CLUSTER_HINT=0
echo "WARN_END"
"""
    result = _run(session, server, script, timeout=20)
    if not result.ok and not result.stdout.strip():
        raise RuntimeError(result.stderr.strip() or "Hostname bilgisi alınamadı")

    short_raw = fqdn = ""
    hosts_lines: list[str] = []
    in_hosts = False
    cluster_hint = False
    for line in result.stdout.splitlines():
        if line.startswith("SHORT="):
            short_raw = line.split("=", 1)[1].strip()
        elif line.startswith("FQDN="):
            fqdn = line.split("=", 1)[1].strip()
        elif line == "HOSTS_BEGIN":
            in_hosts = True
        elif line == "HOSTS_END":
            in_hosts = False
        elif in_hosts:
            hosts_lines.append(line)
        elif line.startswith("CLUSTER_HINT="):
            cluster_hint = line.split("=", 1)[1].strip() == "1"

    # Envanter hostname yedek FQDN (hostname -f boş/kısa dönerse)
    inv = (server.hostname or "").strip()
    if not fqdn or ("." not in fqdn and inv and "." in inv):
        fqdn = inv or fqdn or short_raw
    if not fqdn and short_raw:
        fqdn = short_raw

    short, domain = split_fqdn(fqdn)
    if not short and short_raw:
        short = short_raw.strip().lower()

    warnings: list[str] = []
    if cluster_hint:
        warnings.append(
            "Sunucuda Oracle/SAP/cluster benzeri süreç izi görüldü. Hostname değişikliği uygulamaları etkileyebilir."
        )

    return {
        "short_name": short,
        "domain": domain,
        "fqdn": fqdn.strip().lower().rstrip(".") if fqdn else short,
        "hosts_preview": "\n".join(hosts_lines[:40]),
        "warnings": warnings,
        "ip": server.ip,
    }


def _validate_names(short_name: str, domain: str) -> tuple[str, str, str]:
    short = short_name.strip().lower()
    dom = domain.strip().lower().strip(".")
    if not short or not _SHORT_RE.match(short):
        raise ValueError("Kısa ad geçersiz (harf/rakam/-, 1–63 karakter)")
    if dom and not _DOMAIN_RE.match(dom):
        raise ValueError("Domain geçersiz")
    fqdn = f"{short}.{dom}" if dom else short
    if len(fqdn) > 253:
        raise ValueError("FQDN çok uzun")
    return short, dom, fqdn


def build_success_checklist(
    *,
    old_fqdn: str,
    new_fqdn: str,
    ip: str,
    lang: str = "tr",
) -> list[str]:
    """Başarı sonrası kontrol listesi (dinamik FQDN / IP; tr|en)."""
    old = (old_fqdn or "").strip() or "—"
    new = (new_fqdn or "").strip() or "—"
    addr = (ip or "").strip() or "—"
    if (lang or "tr").lower().startswith("en"):
        return [
            (
                "The requester must open a ticket to update DNS records using the format below.\n\n"
                "Request path: DNS Definition / Change DNS Record\n"
                "Sample request:\n"
                f'"{old} {addr}" record should be updated so that it becomes "{new} {addr}".'
            ),
            (
                "Relevant teams must be informed so monitoring and Datastore entries can be updated.\n\n"
                "Sample mail:\n"
                "To: Sanallaştırma ve Bulut Platformları Yönetimi, Sistem İzleme ve Hizmet Analiz "
                "İşletimi, Sistem İşletim ve İzleme, Altyapı İzleme\n"
                "CC: Unix Linux Sistem Tasarım ve Planlama\n\n"
                f'Hostname of server "{old}" has been updated to "{new}".\n'
                "Please update the required Datastore and monitoring records."
            ),
        ]
    return [
        (
            "Talep sahibinin belirtilen formatı kullanarak dns bilgilerinin güncellenmesi "
            "için talep oluşturması gerekmektedir.\n\n"
            "Talep Kırılım: DNS Tanımı / DNS Kayıt Değiştirme\n"
            "Örnek Talep:\n"
            f'"{old} {addr}" kaydının "{new} {addr}" olacak şekilde DNS kaydının '
            "güncellenmesini rica ederiz."
        ),
        (
            "İzleme ve Datastore alanlarının güncellenmesi üzere ilgili ekipler "
            "bilgilendirilmelidir.\n\n"
            "Örnek Mail:\n"
            "To: Sanallaştırma ve Bulut Platformları Yönetimi, Sistem İzleme ve Hizmet Analiz "
            "İşletimi, Sistem İşletim ve İzleme, Altyapı İzleme\n"
            "CC: Unix Linux Sistem Tasarım ve Planlama\n\n"
            f'"{old}" isimli sunucunun hostname bilgisi "{new}" olarak güncellenmiştir.\n'
            "Gerekli Datastore ve izleme kayıtları düzenlemesinin yapılmasını rica ederiz."
        ),
    ]


def parse_adinfo(stdout: str) -> dict[str, str]:
    """adinfo -a → zone + domain (Current DC ilk '.' sonrası)."""
    zone = ""
    current_dc = ""
    joined_domain = ""
    for line in (stdout or "").splitlines():
        low = line.strip()
        if low.lower().startswith("zone:"):
            zone = line.split(":", 1)[1].strip()
        elif low.lower().startswith("current dc:"):
            current_dc = line.split(":", 1)[1].strip()
        elif low.lower().startswith("joined to domain:"):
            joined_domain = line.split(":", 1)[1].strip()
    domain = ""
    if current_dc and "." in current_dc:
        domain = current_dc.split(".", 1)[1].strip().lower()
    elif joined_domain:
        domain = joined_domain.strip().lower()
    return {"zone": zone, "domain": domain, "current_dc": current_dc}


def _probe_centrify(session: Session, server: TargetServer) -> dict[str, str] | None:
    r = _run(
        session,
        server,
        "set +e\n"
        "if command -v adinfo >/dev/null 2>&1; then adinfo -a; else echo CENTRIFY_ABSENT; fi\n",
        timeout=45,
    )
    text = r.stdout or ""
    if "CENTRIFY_ABSENT" in text:
        return None
    info = parse_adinfo(text)
    if not info.get("zone") or not info.get("domain"):
        return None
    return info


def _redact(text: str, secrets: list[str]) -> str:
    out = text or ""
    for s in secrets:
        if s:
            out = out.replace(s, "***")
    return out


def _best_effort_centrify_leave(
    session: Session,
    server: TargetServer,
    username: str,
) -> tuple[bool, str]:
    cmd = f"set +e\nadleave -f {shlex.quote(username)}\necho ADLEAVE_EXIT:$?\n"
    r = _run(session, server, cmd, timeout=120)
    ok = bool(r.ok) or "ADLEAVE_EXIT:0" in (r.stdout or "")
    return ok, (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")


def _best_effort_centrify_join(
    session: Session,
    server: TargetServer,
    *,
    zone: str,
    username: str,
    password: str,
    domain: str,
) -> tuple[bool, str]:
    # leave -f şifresiz; join için echo | adjoin
    script = (
        "set +e\n"
        f"echo {shlex.quote(password)} | adjoin "
        f"-z {shlex.quote(zone)} "
        f"-c {shlex.quote(_CENTRIFY_CONTAINER)} "
        f"-f -u {shlex.quote(username)} {shlex.quote(domain)}\n"
        "echo ADJOIN_EXIT:$?\n"
    )
    r = _run(session, server, script, timeout=180)
    out = _redact((r.stdout or "") + (("\n" + r.stderr) if r.stderr else ""), [password])
    ok = "ADJOIN_EXIT:0" in out or (
        r.ok and "successfully joined" in out.lower()
    )
    return ok, out


def _best_effort_hpsa(session: Session, server: TargetServer) -> tuple[bool, str]:
    script = (
        "set +e\n"
        "sw=0; hw=0; miss=0\n"
        "if [ -x /opt/opsware/agent/pylibs3/cog/bs_software ]; then\n"
        "  /opt/opsware/agent/pylibs3/cog/bs_software --debug && sw=1 || sw=0\n"
        "else\n"
        "  echo HPSA_SOFTWARE_MISSING; miss=1\n"
        "fi\n"
        "if [ -x /opt/opsware/agent/pylibs3/cog/bs_hardware ]; then\n"
        "  /opt/opsware/agent/pylibs3/cog/bs_hardware --debug && hw=1 || hw=0\n"
        "else\n"
        "  echo HPSA_HARDWARE_MISSING; miss=1\n"
        "fi\n"
        "echo HPSA_SW:$sw HPSA_HW:$hw HPSA_MISS:$miss\n"
    )
    r = _run(session, server, script, timeout=300)
    text = (r.stdout or "") + (("\n" + r.stderr) if r.stderr else "")
    ok = "HPSA_SW:1" in text and "HPSA_HW:1" in text and "HPSA_MISS:0" in text
    return ok, text


def build_plans(
    session: Session, action: str, servers: list[TargetServer], payload: dict[str, Any]
) -> list[HostPlan]:
    if action != "set":
        return [
            HostPlan(
                server_id=s.id,  # type: ignore[arg-type]
                hostname=s.hostname,
                ip=s.ip,
                ok=False,
                summary_tr=f"Bilinmeyen aksiyon: {action}",
                error="Bilinmeyen aksiyon",
            )
            for s in servers
        ]

    plans: list[HostPlan] = []
    for server in servers:
        try:
            short, domain, new_fqdn = _validate_names(
                str(payload.get("short_name") or ""),
                str(payload.get("domain") or ""),
            )
            state = read_hostname_state(session, server)
            old_fqdn = state.get("fqdn") or server.hostname
            old_short = state.get("short_name") or ""
            if new_fqdn == old_fqdn:
                plans.append(
                    HostPlan(
                        server_id=server.id,  # type: ignore[arg-type]
                        hostname=server.hostname,
                        ip=server.ip,
                        ok=False,
                        summary_tr=f"{server.hostname}: zaten {new_fqdn}",
                        before_state=state,
                        error="Değişiklik yok",
                    )
                )
                continue

            cmds = [
                f"cp /etc/hosts /etc/hosts.bak.$(date +%s)",
                f"hostnamectl set-hostname {shlex.quote(new_fqdn)}",
                f"# /etc/hosts: {old_short}/{old_fqdn} → {short}/{new_fqdn} ({server.ip})",
                "hostname -f && hostname -s",
            ]
            risk = "Hostname ve /etc/hosts değişecek. DNS/izleme envanteri ayrıca güncellenmeli."
            if state.get("warnings"):
                risk = " · ".join(state["warnings"]) + " · " + risk

            plans.append(
                HostPlan(
                    server_id=server.id,  # type: ignore[arg-type]
                    hostname=server.hostname,
                    ip=server.ip,
                    ok=True,
                    summary_tr=f"{server.hostname}: {old_fqdn} → {new_fqdn}",
                    planned_commands=cmds,
                    before_state={
                        **state,
                        "old_fqdn": old_fqdn,
                        "old_short": old_short,
                        "new_short": short,
                        "new_domain": domain,
                        "new_fqdn": new_fqdn,
                    },
                    risk_notes=risk,
                )
            )
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
    _ = job_id
    if action != "set" or not plan.ok:
        return False, plan.before_state, "", plan.error or "Plan uygulanamaz"

    from app.services import centrify_store as cstore

    short, domain, new_fqdn = _validate_names(
        str(payload.get("short_name") or ""),
        str(payload.get("domain") or ""),
    )
    old_fqdn = str((plan.before_state or {}).get("old_fqdn") or "")
    old_short = str((plan.before_state or {}).get("old_short") or "")
    ip = server.ip

    log_chunks: list[str] = []
    post_notes: list[str] = []
    secrets_to_redact: list[str] = []

    # --- Centrify probe + leave (best-effort; hostname sonucunu etkilemez) ---
    centrify_info: dict[str, str] | None = None
    centrify_creds: tuple[str, str, str] | None = None
    try:
        centrify_info = _probe_centrify(session, server)
        if centrify_info:
            log_chunks.append(
                f"CENTRIFY_ZONE={centrify_info.get('zone')}\n"
                f"CENTRIFY_DOMAIN={centrify_info.get('domain')}\n"
                f"CENTRIFY_DC={centrify_info.get('current_dc')}"
            )
            centrify_creds = cstore.get_plain_creds(session, centrify_info["domain"])
            if centrify_creds:
                user, password, _dom = centrify_creds
                secrets_to_redact.append(password)
                leave_ok, leave_out = _best_effort_centrify_leave(session, server, user)
                log_chunks.append("--- centrify adleave ---\n" + leave_out)
                if not leave_ok:
                    log_chunks.append("CENTRIFY_LEAVE_SKIP_OR_FAIL")
            else:
                log_chunks.append(
                    f"CENTRIFY_NO_CREDS domain={centrify_info.get('domain')} — leave/join atlandı"
                )
                centrify_info = None  # join da yapma
    except Exception as exc:  # noqa: BLE001
        log_chunks.append(f"CENTRIFY_PRE_ERROR: {exc}")
        centrify_info = None
        centrify_creds = None

    # Remote apply with rollback of hosts on verify fail
    script = f"""
set -e
TS=$(date +%s)
cp /etc/hosts /etc/hosts.bak.$TS
hostnamectl set-hostname {shlex.quote(new_fqdn)}

python3 - <<'PY'
from pathlib import Path
ip = {ip!r}
old_short = {old_short!r}
old_fqdn = {old_fqdn!r}
new_short = {short!r}
new_fqdn = {new_fqdn!r}
path = Path("/etc/hosts")
lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
out = []
for line in lines:
    stripped = line.strip()
    if not stripped or stripped.startswith("#"):
        out.append(line)
        continue
    parts = stripped.split()
    if not parts:
        out.append(line)
        continue
    addrs, names = parts[0], parts[1:]
    if addrs == ip or (old_short and old_short in names) or (old_fqdn and old_fqdn in names):
        # drop old mapping for this host identity; rewrite at end
        continue
    out.append(line)
out.append(f"{{ip}}\\t{{new_fqdn}} {{new_short}}")
path.write_text("\\n".join(out) + "\\n", encoding="utf-8")
print("HOSTS_UPDATED")
PY

NEW_F=$(hostname -f 2>/dev/null || true)
NEW_S=$(hostname -s 2>/dev/null || true)
echo "VERIFY_FQDN=$NEW_F"
echo "VERIFY_SHORT=$NEW_S"
if [ "$NEW_F" != {shlex.quote(new_fqdn)} ] && [ "$NEW_S" != {shlex.quote(short)} ]; then
  cp /etc/hosts.bak.$TS /etc/hosts
  echo "ROLLBACK_HOSTS=1"
  exit 2
fi
echo "BACKUP=/etc/hosts.bak.$TS"
"""

    result = _run(session, server, script, timeout=60)
    out = result.stdout
    err = result.stderr
    verify_fqdn = ""
    verify_short = ""
    backup = ""
    for line in out.splitlines():
        if line.startswith("VERIFY_FQDN="):
            verify_fqdn = line.split("=", 1)[1].strip()
        elif line.startswith("VERIFY_SHORT="):
            verify_short = line.split("=", 1)[1].strip()
        elif line.startswith("BACKUP="):
            backup = line.split("=", 1)[1].strip()

    ok = result.ok and (verify_fqdn == new_fqdn or verify_short == short)
    log_chunks.append("--- hostname ---\n" + (out or ""))

    # --- Centrify join + HPSA (yalnızca hostname başarılıysa; yine best-effort) ---
    if ok and centrify_info and centrify_creds:
        try:
            user, password, dom = centrify_creds
            secrets_to_redact.append(password)
            join_ok, join_out = _best_effort_centrify_join(
                session,
                server,
                zone=centrify_info["zone"],
                username=user,
                password=password,
                domain=dom,
            )
            log_chunks.append("--- centrify adjoin ---\n" + join_out)
            if join_ok:
                post_notes.append("Centrify bilgileri güncellendi")
        except Exception as exc:  # noqa: BLE001
            log_chunks.append(f"CENTRIFY_JOIN_ERROR: {exc}")

    if ok:
        try:
            hpsa_ok, hpsa_out = _best_effort_hpsa(session, server)
            log_chunks.append("--- hpsa ---\n" + hpsa_out)
            if hpsa_ok:
                post_notes.append("HPSA bilgileri güncellendi")
        except Exception as exc:  # noqa: BLE001
            log_chunks.append(f"HPSA_ERROR: {exc}")

    combined_out = _redact("\n".join(log_chunks), secrets_to_redact)
    combined_err = _redact(err or "", secrets_to_redact)

    after = {
        **(plan.before_state or {}),
        "new_fqdn": new_fqdn,
        "new_short": short,
        "new_domain": domain,
        "verify_fqdn": verify_fqdn,
        "verify_short": verify_short,
        "hosts_backup": backup,
        "inventory_updated": False,
        "post_notes": post_notes,
        "checklist": build_success_checklist(
            old_fqdn=old_fqdn,
            new_fqdn=new_fqdn,
            ip=ip,
            lang="tr",
        ),
        "checklist_en": build_success_checklist(
            old_fqdn=old_fqdn,
            new_fqdn=new_fqdn,
            ip=ip,
            lang="en",
        ),
    }

    if ok:
        server.hostname = new_fqdn
        session.add(server)
        session.commit()
        after["inventory_updated"] = True

    return (
        ok,
        after,
        combined_out,
        combined_err if ok else (combined_err or "Hostname doğrulaması başarısız; hosts yedeği geri yüklendi olabilir"),
    )
