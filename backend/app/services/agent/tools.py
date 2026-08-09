"""
Agent Tool Registry.

Her tool:
  - name, description: LLM'e sunulan tanım
  - parameters:        JSON şeması (OpenAI/Ollama tool-calling formatı)
  - risk_level:        READ_ONLY (otomatik) | MUTATING (onay gerekir)
  - preview(args,ctx): onay kartında gösterilecek komut önizlemesi
  - execute(db,args,ctx): gerçek çalıştırma (read-only anında; mutating onay sonrası)

Tasarım: tool'lar ham shell komutuna indirgenip executor.run_ssh_command'dan geçer,
böylece policy engine (sandbox) her durumda devrededir.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.server import Server
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.openshift import OpenShiftCluster
from app.services.agent.policy import RiskLevel
from app.services.agent.executor import run_ssh_command

logger = logging.getLogger(__name__)


# ── Sunucu çözümleme ─────────────────────────────────────────────────────────
def resolve_server(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Optional[Server]:
    """args['server'] (ad/ip) veya args['server_id'] ya da ctx['server_ids'][0] ile sunucu bulur."""
    q = db.query(Server).filter(Server.ai_ready == True)  # noqa: E712
    sid = args.get("server_id")
    if sid:
        return q.filter(Server.id == sid).first()
    name = (args.get("server") or "").strip().lower()
    if name:
        for s in q.all():
            if (s.name and s.name.lower() == name) or (s.ip_address and s.ip_address == name):
                return s
    ctx_ids = ctx.get("server_ids") or []
    if ctx_ids:
        return q.filter(Server.id == ctx_ids[0]).first()
    return None


def resolve_hypervisor(
    db: Session, args: Dict[str, Any], type_filter: Optional[HypervisorType] = None,
) -> Optional[Hypervisor]:
    """args['hypervisor'] (ad/ip) ile bir Hypervisor bulur; verilmezse (type_filter'a uyan) ilkini döner."""
    q = db.query(Hypervisor)
    if type_filter:
        q = q.filter(Hypervisor.hypervisor_type == type_filter)
    name = (args.get("hypervisor") or args.get("server") or "").strip().lower()
    if name:
        for hv in q.all():
            if (hv.name and hv.name.lower() == name) or (hv.ip_address and hv.ip_address == name):
                return hv
    return q.first()


def resolve_openshift_cluster(db: Session, args: Dict[str, Any]) -> Optional[OpenShiftCluster]:
    """args['cluster']/args['hypervisor'] (ad) ile bir OpenShiftCluster bulur; yoksa ilkini döner."""
    q = db.query(OpenShiftCluster)
    name = (args.get("cluster") or args.get("hypervisor") or "").strip().lower()
    if name:
        for c in q.all():
            if c.name and c.name.lower() == name:
                return c
    return q.first()


def _build_vcenter_client(hv: Hypervisor):
    from app.services.vmware.vcenter_client import VCenterClient
    from app.services.hypervisor_credentials import hv_password, plain
    cc = hv.connection_config or {}
    return VCenterClient(
        host=hv.ip_address or hv.hostname,
        username=hv.username or cc.get("username", ""),
        password=hv_password(hv),
        port=hv.port or 443,
    )


def _build_kubevirt_client(hv: Hypervisor):
    from app.services.openshift.kubevirt_client import KubeVirtClient
    from app.services.hypervisor_credentials import hv_password, hv_token, plain
    cc = hv.connection_config or {}
    use_creds = bool(cc.get("username")) and bool(cc.get("password") or hv.password)
    return KubeVirtClient(
        api_url=cc.get("api_url") or hv.hostname or hv.ip_address,
        token="" if use_creds else hv_token(hv),
        username=cc.get("username") or "",
        password=plain(cc.get("password")) or hv_password(hv),
        verify_ssl=bool(cc.get("verify_ssl", False)),
    )


def _build_ocp_client(cluster: OpenShiftCluster):
    from app.services.openshift.cluster_ops import client_from_cluster
    return client_from_cluster(cluster)


def _service_arg_ok(service: str) -> bool:
    """Servis adı basit doğrulama (enjeksiyon önleme)."""
    import re
    return bool(service) and bool(re.fullmatch(r"[A-Za-z0-9._@\-]+", service))


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]
    risk_level: RiskLevel
    build_command: Callable[[Dict[str, Any]], str]
    timeout: int = 30
    allow_sudo: bool = False
    # Belirli bir sunucuya SSH ile bağlanmadan çalışan araçlar için (ör. DB'den
    # toplu envanter özeti). Set edilirse preview/execute SSH akışını atlar.
    direct_handler: Optional[Callable[[Session, Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = None
    direct_label: str = ""
    # Platform kapsamı — Linux sohbetinde OpenShift araçları (ve tersi) karışmasın.
    # Örn. {"linux"}, {"openshift"}, {"vcenter"}, {"infra"}
    domains: frozenset = frozenset({"linux"})

    def preview(self, db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> str:
        if self.direct_handler:
            return self.direct_label or self.name
        server = resolve_server(db, args, ctx)
        sname = server.name if server else "(sunucu bulunamadı)"
        try:
            cmd = self.build_command(args)
        except Exception as e:
            cmd = f"(komut oluşturulamadı: {e})"
        return f"{sname}: {cmd}"

    def execute(self, db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
        if self.direct_handler:
            return self.direct_handler(db, args, ctx)
        server = resolve_server(db, args, ctx)
        if not server:
            return {"ok": False, "error": "Hedef sunucu bulunamadı (ai_ready olmalı)."}
        try:
            command = self.build_command(args)
        except Exception as e:
            return {"ok": False, "error": f"Geçersiz argüman: {e}"}
        return run_ssh_command(
            db, server, command,
            allow_sudo=self.allow_sudo,
            timeout=self.timeout,
            session_id=ctx.get("session_id"),
            sudo_password_override=ctx.get("sudo_password_override"),
            actor_name=ctx.get("actor_name"),
        )


# ── Komut üreticiler ─────────────────────────────────────────────────────────
def _diag_cmd(args: Dict[str, Any]) -> str:
    cmd = (args.get("command") or "").strip()
    if not cmd:
        raise ValueError("command zorunlu")
    return cmd


def _logs_cmd(args: Dict[str, Any]) -> str:
    service = (args.get("service") or "").strip()
    lines = int(args.get("lines") or 100)
    lines = max(1, min(lines, 1000))
    if service:
        if not _service_arg_ok(service):
            raise ValueError("geçersiz servis adı")
        return f"journalctl -u {service} -n {lines} --no-pager"
    return f"journalctl -n {lines} --no-pager"


def _clean_logs_cmd(args: Dict[str, Any]) -> str:
    # Güvenli log temizleme: journald vacuum (yıkıcı değil, sadece eski log rotasyonu)
    days = int(args.get("keep_days") or 3)
    days = max(1, min(days, 90))
    return f"sudo journalctl --vacuum-time={days}d"


def _restart_service_cmd(args: Dict[str, Any]) -> str:
    service = (args.get("service") or "").strip()
    if not _service_arg_ok(service):
        raise ValueError("geçersiz servis adı")
    return f"sudo systemctl restart {service}"


def _lvm_info_cmd(args: Dict[str, Any]) -> str:
    scope = (args.get("scope") or "all").strip().lower()
    cmds = {
        "pv": "sudo pvs",
        "vg": "sudo vgs",
        "lv": "sudo lvs",
        "all": "sudo pvs; sudo vgs; sudo lvs",
    }
    return cmds.get(scope, cmds["all"])


_LVM_NAME = re.compile(r"[A-Za-z0-9._+\-]+")
_LVM_DEVICE = re.compile(r"/dev/[A-Za-z0-9/_\-]+")
_LVM_SIZE = re.compile(r"\+?(?:\d+(?:\.\d+)?[KMGTPE]?B?|\d+%(?:FREE|VG|PVS|ORIGIN))", re.I)


def _check(pattern: re.Pattern, value: str, label: str) -> str:
    value = (value or "").strip()
    if not value or not pattern.fullmatch(value):
        raise ValueError(f"geçersiz {label}: {value!r}")
    return value


def _lvm_manage_cmd(args: Dict[str, Any]) -> str:
    op = (args.get("operation") or "").strip().lower()
    if op == "create_pv":
        dev = _check(_LVM_DEVICE, args.get("device"), "device")
        return f"sudo pvcreate {dev}"
    if op == "create_vg":
        vg = _check(_LVM_NAME, args.get("vg_name"), "vg_name")
        devices = args.get("devices") or ([args["device"]] if args.get("device") else [])
        if isinstance(devices, str):
            devices = [devices]
        if not devices:
            raise ValueError("create_vg için en az bir device gerekli")
        devs = " ".join(_check(_LVM_DEVICE, d, "device") for d in devices)
        return f"sudo vgcreate {vg} {devs}"
    if op == "extend_vg":
        vg = _check(_LVM_NAME, args.get("vg_name"), "vg_name")
        dev = _check(_LVM_DEVICE, args.get("device"), "device")
        return f"sudo vgextend {vg} {dev}"
    if op == "create_lv":
        vg = _check(_LVM_NAME, args.get("vg_name"), "vg_name")
        lv = _check(_LVM_NAME, args.get("lv_name"), "lv_name")
        size = _check(_LVM_SIZE, args.get("size"), "size")
        flag = "-l" if size.endswith(("FREE", "VG", "PVS", "ORIGIN", "free", "vg", "pvs", "origin")) else "-L"
        return f"sudo lvcreate {flag} {size} -n {lv} {vg}"
    if op == "extend_lv":
        vg = _check(_LVM_NAME, args.get("vg_name"), "vg_name")
        lv = _check(_LVM_NAME, args.get("lv_name"), "lv_name")
        size = _check(_LVM_SIZE, args.get("size"), "size")
        if size.startswith("-"):
            raise ValueError("küçültme (negatif boyut) desteklenmez")
        flag = "-l" if size.endswith(("FREE", "VG", "PVS", "ORIGIN", "free", "vg", "pvs", "origin")) else "-L"
        resize = " -r" if args.get("resize_fs") else ""
        return f"sudo lvextend{resize} {flag} {size} /dev/{vg}/{lv}"
    raise ValueError(f"desteklenmeyen operation: {op!r}")


def _free_disks_cmd(args: Dict[str, Any]) -> str:
    # Tüm blok aygıtları + hangilerinin PV olduğu → LLM boş olanları ayıklar.
    return (
        "echo '=== BLOK AYGITLAR (lsblk) ==='; "
        "lsblk -o NAME,SIZE,TYPE,FSTYPE,MOUNTPOINT,MODEL; "
        "echo '=== MEVCUT PV (pvs) ==='; "
        "sudo pvs --noheadings -o pv_name,vg_name 2>/dev/null || echo 'PV yok'"
    )


def _infra_overview_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.infra_summary import build_infra_overview_text
    try:
        platform = (ctx or {}).get("platform") or (args or {}).get("platform")
        return {
            "ok": True,
            "platform_scope": (platform or "unified"),
            "summary": build_infra_overview_text(db, platform=platform),
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _vcenter_ask_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    question = (args.get("question") or "").strip()
    if not question:
        return {"ok": False, "error": "question zorunlu"}
    try:
        from app.services.hypervisor_intelligence import answer_hypervisor_question
        result = answer_hypervisor_question(db, question)
        if result.get("error"):
            return {"ok": False, "error": result["error"]}
        return {"ok": True, "answer": result.get("answer"), "source": "hypervisor_intelligence"}
    except Exception as e:
        logger.error(f"[Tool] vcenter_ask hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _vcenter_live_alarms_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    hv = resolve_hypervisor(db, args, type_filter=HypervisorType.VMWARE)
    if not hv:
        return {"ok": False, "error": "Tanımlı VMware vCenter bulunamadı"}
    hours = max(1, min(int(args.get("hours") or 48), 168))
    try:
        client = _build_vcenter_client(hv)
        data = client.collect_platform_logs(hours=hours, max_events=300)
        return {
            "ok": True,
            "hypervisor": hv.name,
            "hours": hours,
            "alarms": (data.get("alarms") or [])[:50],
            "errors": data.get("errors") or [],
            "collected_at": data.get("collected_at"),
        }
    except Exception as e:
        logger.error(f"[Tool] vcenter_live_alarms hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _vcenter_live_tasks_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    hv = resolve_hypervisor(db, args, type_filter=HypervisorType.VMWARE)
    if not hv:
        return {"ok": False, "error": "Tanımlı VMware vCenter bulunamadı"}
    hours = max(1, min(int(args.get("hours") or 48), 168))
    try:
        client = _build_vcenter_client(hv)
        data = client.collect_platform_logs(hours=hours, max_events=500)
        return {
            "ok": True,
            "hypervisor": hv.name,
            "hours": hours,
            "task_events": (data.get("task_events") or [])[:80],
            "errors": data.get("errors") or [],
            "collected_at": data.get("collected_at"),
        }
    except Exception as e:
        logger.error(f"[Tool] vcenter_live_tasks hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _openshift_ask_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    question = (args.get("question") or "").strip()
    cluster = resolve_openshift_cluster(db, args)
    if not cluster:
        return {"ok": False, "error": "Tanımlı OpenShift cluster bulunamadı"}
    try:
        from collections import Counter
        client = _build_ocp_client(cluster)
        nodes = client.list_nodes()
        projects = client.list_projects()
        pods = client.list_pods()
        by_status = dict(Counter((p.get("status") or "Unknown") for p in pods))
        problems = [
            p for p in pods
            if (p.get("status") or "").lower() not in ("running", "succeeded")
            or int(p.get("restart_count") or 0) >= 5
            or p.get("reason")
        ]
        summary = {
            "cluster": cluster.name,
            "version": cluster.version,
            "node_count": len(nodes),
            "nodes": [{"name": n.get("name"), "role": n.get("role"), "status": n.get("status")} for n in nodes[:50]],
            "project_count": len(projects),
            "pod_count": len(pods),
            "pods_by_status": by_status,
            "problem_pod_count": len(problems),
            "problem_pods_sample": problems[:30],
            "question_hint": question or None,
            "hint": "Detaylı pod listesi için list_ocp_pods aracını çağır (namespace filtreli veya tümü).",
        }
        return {"ok": True, **summary}
    except Exception as e:
        logger.error(f"[Tool] openshift_ask hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _list_kubevirt_vms_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    hv = resolve_hypervisor(db, args, type_filter=HypervisorType.OPENSHIFT_VIRT)
    if not hv:
        return {"ok": False, "error": "Tanımlı OpenShift Virtualization (KubeVirt) hypervisor bulunamadı"}
    try:
        client = _build_kubevirt_client(hv)
        vms = client.list_vms()
        return {"ok": True, "hypervisor": hv.name, "count": len(vms), "vms": vms[:100]}
    except Exception as e:
        logger.error(f"[Tool] list_kubevirt_vms hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _list_ocp_pods_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    cluster = resolve_openshift_cluster(db, args)
    if not cluster:
        return {"ok": False, "error": "Tanımlı OpenShift cluster bulunamadı"}
    namespace = (args.get("namespace") or "").strip() or None
    try:
        from collections import Counter
        client = _build_ocp_client(cluster)
        pods = client.list_pods(namespace=namespace)
        by_status = dict(Counter((p.get("status") or "Unknown") for p in pods))
        by_ns = Counter((p.get("namespace") or "") for p in pods)

        def _is_problem(p: Dict[str, Any]) -> bool:
            st = (p.get("status") or "").lower()
            reason = (p.get("reason") or "").lower()
            if st not in ("running", "succeeded"):
                return True
            if reason and reason not in ("completed",):
                return True
            if int(p.get("restart_count") or 0) >= 5:
                return True
            return False

        problems = [p for p in pods if _is_problem(p)]
        problems.sort(key=lambda p: (-int(p.get("restart_count") or 0), p.get("namespace") or "", p.get("name") or ""))
        # Kompakt tek satır — JSON object şişmesini önler
        problem_lines = [
            f"{p.get('namespace')}/{p.get('name')} status={p.get('status')} "
            f"reason={p.get('reason') or '-'} restarts={p.get('restart_count', 0)} "
            f"ready={p.get('ready')} node={p.get('node_name') or '-'}"
            for p in problems[:50]
        ]

        _FULL_LIMIT = 120
        result: Dict[str, Any] = {
            "ok": True,
            "cluster": cluster.name,
            "namespace": namespace,
            "count": len(pods),
            "by_status": by_status,
            "by_namespace": [
                {"namespace": ns, "count": n}
                for ns, n in by_ns.most_common(60)
            ],
            "problem_count": len(problems),
            "problem_pods": problem_lines,
        }

        if namespace or len(pods) <= _FULL_LIMIT:
            result["pods"] = pods
            result["list_complete"] = True
        else:
            lines = ["namespace\tname\tstatus\treason\tnode\trestarts\tready"]
            for p in pods:
                lines.append(
                    f"{p.get('namespace','')}\t{p.get('name','')}\t{p.get('status','')}\t"
                    f"{p.get('reason') or ''}\t{p.get('node_name') or ''}\t"
                    f"{p.get('restart_count', 0)}\t{p.get('ready') or ''}"
                )
            result["pods_tsv"] = "\n".join(lines)
            result["pods_listed"] = len(pods)
            result["list_complete"] = True
            result["hint"] = (
                "Tüm pod'lar pods_tsv içinde (TSV, satır başına 1 pod). "
                "Belirli proje için list_ocp_pods(namespace=...) çağır."
            )
        return result
    except Exception as e:
        logger.error(f"[Tool] list_ocp_pods hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _list_ocp_events_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    cluster = resolve_openshift_cluster(db, args)
    if not cluster:
        return {"ok": False, "error": "Tanımlı OpenShift cluster bulunamadı"}
    hours = max(1, min(int(args.get("hours") or 48), 168))
    try:
        client = _build_ocp_client(cluster)
        events = client.list_events(hours=hours)
        return {"ok": True, "cluster": cluster.name, "hours": hours,
                "count": len(events), "events": events[:100]}
    except Exception as e:
        logger.error(f"[Tool] list_ocp_events hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _sys_summary_cmd(args: Dict[str, Any]) -> str:
    return (
        "echo '=== UPTIME / LOAD ==='; uptime; "
        "echo; echo '=== CPU ==='; "
        "lscpu 2>/dev/null | grep -E 'Model name|Socket|Core|Thread|CPU\\(s\\)|MHz'; "
        "echo; echo '=== BELLEK ==='; free -h"
    )


_PATH_RE = re.compile(r"/[\w./\-]*")


def _disk_usage_cmd(args: Dict[str, Any]) -> str:
    mount = (args.get("mount") or "").strip()
    if mount:
        mount = _check(_PATH_RE, mount, "mount")
        return f"df -h {mount}; echo; echo '=== INODE KULLANIMI ==='; df -i {mount}"
    return "df -h; echo; echo '=== INODE KULLANIMI ==='; df -i"


def _large_dirs_cmd(args: Dict[str, Any]) -> str:
    path = (args.get("path") or "/").strip()
    path = _check(_PATH_RE, path, "path")
    depth = max(1, min(int(args.get("depth") or 1), 3))
    count = max(1, min(int(args.get("count") or 15), 30))
    return f"du -xh {path} --max-depth={depth} 2>/dev/null | sort -rh | head -{count}"


def _processes_cmd(args: Dict[str, Any]) -> str:
    sort_by = (args.get("sort_by") or "cpu").strip().lower()
    key = "-%mem" if sort_by == "mem" else "-%cpu"
    count = max(1, min(int(args.get("count") or 15), 50))
    # +1: ps aux başlık satırını da sayar, head bunu düşürmesin
    return f"ps aux --sort={key} | head -{count + 1}"


def _service_status_cmd(args: Dict[str, Any]) -> str:
    service = (args.get("service") or "").strip()
    if not _service_arg_ok(service):
        raise ValueError("geçersiz servis adı")
    return f"systemctl status {service} --no-pager -l"


def _service_logs_cmd(args: Dict[str, Any]) -> str:
    service = (args.get("service") or "").strip()
    if not _service_arg_ok(service):
        raise ValueError("geçersiz servis adı")
    lines = max(1, min(int(args.get("lines") or 100), 1000))
    return f"journalctl -u {service} -n {lines} --no-pager"


def _network_status_cmd(args: Dict[str, Any]) -> str:
    return (
        "echo '=== IP ADRESLERI ==='; ip -brief addr 2>/dev/null || ifconfig; "
        "echo; echo '=== ROUTING ==='; ip route 2>/dev/null || route -n; "
        "echo; echo '=== DINLEYEN PORTLAR ==='; ss -tulpn 2>/dev/null || netstat -tulpn 2>/dev/null; "
        "echo; echo '=== AKTIF BAGLANTILAR (ilk 30) ==='; "
        "(ss -tunp 2>/dev/null | head -30) || (netstat -tunp 2>/dev/null | head -30)"
    )


_PKG_NAME_RE = re.compile(r"[A-Za-z0-9._+\-]+")


def _package_status_cmd(args: Dict[str, Any]) -> str:
    package = (args.get("package") or "").strip()
    if package:
        pkg = _check(_PKG_NAME_RE, package, "package")
        return (
            f"rpm -q {pkg} 2>/dev/null || dpkg -s {pkg} 2>/dev/null "
            f"|| echo 'Paket bulunamadi: {pkg}'"
        )
    # NOT: dnf/apt repo'ya erişemezse (air-gapped/kapalı ağ) uzun süre asılı kalabilir;
    # 'timeout N' ile üst sınır koyuyoruz ki tüm komut zinciri kilitlenmesin.
    return (
        "if command -v dnf >/dev/null 2>&1; then "
        "echo '=== GUNCELLENEBILIR PAKETLER (dnf) ==='; "
        "timeout 10 dnf check-update 2>/dev/null | head -40; "
        "echo; echo '=== KURULU PAKET SAYISI ==='; rpm -qa | wc -l; "
        "elif command -v apt >/dev/null 2>&1; then "
        "echo '=== GUNCELLENEBILIR PAKETLER (apt) ==='; "
        "timeout 10 apt list --upgradable 2>/dev/null | head -40; "
        "echo; echo '=== KURULU PAKET SAYISI ==='; dpkg -l | wc -l; "
        "else echo 'Desteklenen paket yoneticisi bulunamadi'; fi"
    )


def _security_events_cmd(args: Dict[str, Any]) -> str:
    hours = max(1, min(int(args.get("hours") or 24), 168))
    return (
        "echo '=== SON GIRISLER (last) ==='; last -n 20; "
        f"echo; echo '=== BASARISIZ SSH GIRISLERI (son {hours}s) ==='; "
        f"(journalctl -u sshd --since '{hours} hours ago' --no-pager 2>/dev/null "
        "| grep -iE 'failed|invalid|authentication failure' | tail -30) "
        "|| (grep -iE 'failed|invalid' /var/log/secure /var/log/auth.log 2>/dev/null | tail -30) "
        "|| echo 'Log kaynagi bulunamadi'; "
        "echo; echo '=== SELINUX ==='; sestatus 2>/dev/null || getenforce 2>/dev/null || echo 'SELinux yok'; "
        "echo; echo '=== FIREWALL ==='; "
        "firewall-cmd --state 2>/dev/null || systemctl is-active firewalld 2>/dev/null || echo 'bilinmiyor'"
    )


# Sabit, elle onaylanmış komut menüsü — execute_approved_command SADECE buradaki
# key'lerden birini kabul eder, LLM'in serbest metin komut göndermesi mümkün değildir
# (run_diagnostic'in aksine, burada args'tan hiçbir şey shell'e enterpole edilmez).
APPROVED_COMMANDS: Dict[str, str] = {
    "whoami": "whoami",
    "hostname": "hostname -f 2>/dev/null || hostname",
    "os_release": "cat /etc/os-release",
    "kernel_version": "uname -a",
    "who_logged_in": "who",
    "current_user_id": "id",
    "date_time": "date",
    "timezone": "timedatectl 2>/dev/null || cat /etc/timezone 2>/dev/null",
    "sudo_permissions": "sudo -l",
    "mounted_filesystems": "mount | column -t",
    "resource_limits": "ulimit -a",
    "docker_containers": "docker ps -a 2>/dev/null || echo 'docker kurulu değil'",
}


def _approved_command_cmd(args: Dict[str, Any]) -> str:
    cmd_id = (args.get("command_id") or "").strip()
    if cmd_id not in APPROVED_COMMANDS:
        raise ValueError(
            f"onaylanmamış command_id: {cmd_id!r} (izinli: {', '.join(APPROVED_COMMANDS)})"
        )
    return APPROVED_COMMANDS[cmd_id]


def _failed_services_cmd(args: Dict[str, Any]) -> str:
    return (
        "echo '=== FAILED SERVISLER ==='; systemctl --failed --no-pager --plain 2>/dev/null; "
        "echo; echo '=== TAKILI KALMIŞ (activating/deactivating) SERVISLER ==='; "
        "systemctl list-units --state=activating,deactivating --no-pager --plain 2>/dev/null"
    )


def _stuck_processes_cmd(args: Dict[str, Any]) -> str:
    return (
        "echo '=== ZOMBIE PROCESSLER ==='; echo 'PID PPID STAT ETIME CMD'; "
        "ps -eo pid,ppid,stat,etime,cmd --no-headers 2>/dev/null | awk '$3 ~ /Z/ {print}'; "
        "echo; echo '=== D-STATE (disk/IO bekleyen) PROCESSLER ==='; echo 'PID PPID STAT ETIME CMD'; "
        "ps -eo pid,ppid,stat,etime,cmd --no-headers 2>/dev/null | awk '$3 ~ /^D/ {print}'"
    )


def _reboot_info_cmd(args: Dict[str, Any]) -> str:
    # NOT: policy.py DESTRUCTIVE_PATTERNS "reboot/shutdown/halt" kelimelerini
    # komut metninde ararsa yıkıcı sayıp reddeder — bu yüzden bilinçli olarak
    # 'last -x' / 'journalctl --list-boots' gibi bu kelimeleri İÇERMEYEN
    # salt-okunur komutlar kullanılıyor (fonksiyonel olarak eşdeğer bilgiyi verir).
    return (
        "echo '=== AÇIK KALMA SÜRESİ ==='; uptime -p 2>/dev/null || uptime; "
        "echo; echo '=== SON BOOT ZAMANI ==='; who -b 2>/dev/null; "
        "echo; echo '=== BOOT/KAPANMA GEÇMİŞİ (son 10) ==='; last -x -n 10 2>/dev/null; "
        "echo; echo '=== SYSTEMD BOOT GEÇMİŞİ ==='; journalctl --list-boots --no-pager 2>/dev/null | tail -5"
    )


def _kernel_errors_cmd(args: Dict[str, Any]) -> str:
    hours = max(1, min(int(args.get("hours") or 24), 168))
    return (
        f"echo '=== KERNEL HATALARI (son {hours}s) ==='; "
        f"(journalctl -k --since '{hours} hours ago' -p err --no-pager 2>/dev/null | tail -50) "
        "|| (dmesg -T 2>/dev/null | tail -100) || echo 'Kernel logu okunamadı'; "
        "echo; echo '=== PANIC / OOPS / SEGFAULT / OOM ARAMA ==='; "
        f"(journalctl -k --since '{hours} hours ago' --no-pager 2>/dev/null "
        "| grep -iE 'panic|oops|segfault|out of memory|oom.?kill' | tail -30) "
        "|| (dmesg 2>/dev/null | grep -iE 'panic|oops|segfault|out of memory|oom.?kill' | tail -30) "
        "|| echo 'Bulunamadı/erişilemedi'"
    )


def _admin_diag_snapshot_cmd(args: Dict[str, Any]) -> str:
    """Kıdemli sysadmin log+config checklist (salt okunur, sırlar süzülmüş)."""
    hours = max(1, min(int(args.get("hours") or 24), 168))
    return (
        f"echo '=== JOURNAL ERR+ (son {hours}s) ==='; "
        f"journalctl -p err..emerg --since '{hours} hours ago' --no-pager 2>/dev/null | tail -60; "
        "echo; echo '=== DMESG SORUN ==='; "
        "(dmesg -T 2>/dev/null || dmesg 2>/dev/null) | "
        "grep -iE 'error|fail|panic|oops|oom|blocked|I/O error|reset|timeout|segfault' | tail -40; "
        "echo; echo '=== FAILED UNITS ==='; systemctl --failed --no-pager --plain 2>/dev/null; "
        "echo; echo '=== AUTH/SECURE (son 40) ==='; "
        "tail -n 40 /var/log/secure 2>/dev/null || tail -n 40 /var/log/auth.log 2>/dev/null; "
        "echo; echo '=== FSTAB ==='; cat /etc/fstab 2>/dev/null | grep -v '^#' | grep -v '^$'; "
        "echo; echo '=== SYSCTL (conf) ==='; "
        "(cat /etc/sysctl.conf 2>/dev/null; for f in /etc/sysctl.d/*.conf; do "
        "[ -f \"$f\" ] && echo \"# $f\" && grep -v '^#' \"$f\" | grep -v '^$'; done) 2>/dev/null | head -50; "
        "echo; echo '=== SSHD ÖZET ==='; "
        "grep -E '^(Port|PermitRootLogin|PasswordAuthentication|PubkeyAuthentication|MaxAuthTries|MaxStartups|ClientAlive)' "
        "/etc/ssh/sshd_config /etc/ssh/sshd_config.d/* 2>/dev/null | grep -v '^#' | head -30; "
        "echo; echo '=== SELINUX ==='; getenforce 2>/dev/null; cat /etc/selinux/config 2>/dev/null | grep -v '^#' | grep -v '^$'; "
        "echo; echo '=== DNS ==='; cat /etc/resolv.conf 2>/dev/null; "
        "echo; echo '=== FIREWALL ==='; "
        "(firewall-cmd --list-all 2>/dev/null | head -25) || (iptables -L -n 2>/dev/null | head -25); "
        "echo; echo '=== NEEDS-RESTART ==='; needs-restarting -r 2>/dev/null || echo 'needs-restarting yok'"
    )


def _security_patch_status_cmd(args: Dict[str, Any]) -> str:
    # NOT: /var/run/reboot-required gibi yollar 'reboot' kelimesini içerdiği için
    # policy engine tarafından yıkıcı sayılıp reddedilir — bu yüzden RHEL/CentOS'ta
    # standart olan 'needs-restarting -r' (dnf-utils) tercih edildi.
    return (
        "echo '=== ÇALIŞAN KERNEL ==='; uname -r; "
        "echo; echo '=== KURULU KERNEL PAKETLERİ ==='; "
        "(rpm -q kernel 2>/dev/null) || (dpkg -l 'linux-image*' 2>/dev/null | grep '^ii'); "
        "echo; echo '=== YENİDEN BAŞLATMA GEREKİYOR MU ==='; "
        "needs-restarting -r 2>/dev/null || echo 'needs-restarting aracı yok (dnf-utils kurulu değil)'; "
        "echo; echo '=== GÜVENLİK GÜNCELLEMELERİ ==='; "
        "(timeout 10 dnf updateinfo list security 2>/dev/null | head -40) "
        "|| (timeout 10 yum updateinfo list security 2>/dev/null | head -40) "
        "|| (timeout 10 apt list --upgradable 2>/dev/null | grep -i security | head -40) "
        "|| echo 'Güvenlik güncelleme bilgisi alınamadı (repo erişilemedi/zaman aşımı)'"
    )


def _mount_health_cmd(args: Dict[str, Any]) -> str:
    return (
        "echo '=== MOUNT LİSTESİ ==='; (mount | column -t 2>/dev/null) || mount; "
        "echo; echo '=== READ-ONLY MOUNTLAR ==='; "
        "(mount | grep -E '\\(ro[,)]') || echo 'Read-only mount yok'; "
        "echo; echo '=== NFS/CIFS MOUNTLAR ==='; "
        "(findmnt -t nfs,nfs4,cifs 2>/dev/null) || (mount | grep -iE 'nfs|cifs') || echo 'NFS/CIFS mount yok'; "
        "echo; echo '=== MULTIPATH DURUMU ==='; "
        "(multipath -ll 2>/dev/null | head -30) || echo 'multipath kurulu değil/kullanılmıyor'"
    )


def _update_packages_cmd(args: Dict[str, Any]) -> str:
    mgr = (args.get("manager") or "dnf").strip().lower()
    packages = args.get("packages") or []
    if isinstance(packages, str):
        packages = [packages]
    import re
    safe_pkgs = [p for p in packages if re.fullmatch(r"[A-Za-z0-9._+\-]+", str(p))]
    pkg_str = " ".join(safe_pkgs)
    if mgr in ("apt", "apt-get"):
        base = "sudo apt-get install -y" if safe_pkgs else "sudo apt-get upgrade -y"
        return f"{base} {pkg_str}".strip()
    # dnf/yum
    base = f"sudo {mgr} install -y" if safe_pkgs else f"sudo {mgr} update -y"
    return f"{base} {pkg_str}".strip()


# ── Tool tanımları ──────────────────────────────────────────────────────────
TOOLS: Dict[str, Tool] = {
    "infra_overview": Tool(
        name="infra_overview",
        description=(
            "Aktif sohbet platformunun envanter özetini döndürür (ucuz DB sorgusu, parametre yok). "
            "Linux sohbetinde YALNIZCA Linux sayıları; Windows'ta Windows; OpenShift'te cluster; "
            "Virt'te hypervisor/VM; Unified'da TÜM altyapı. "
            "'Kaç sunucu var', 'envanter durumu', 'AI Ready kaç tane' gibi genel sayı/özet "
            "sorularında bunu kullan — sunucu sunucu SSH/df ÇALIŞTIRMA."
        ),
        parameters={"type": "object", "properties": {}},
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_infra_overview_handler,
        direct_label="Platform envanter özeti",
    ),
    "vcenter_ask": Tool(
        name="vcenter_ask",
        description=(
            "vCenter/hypervisor ile ilgili doğal dil sorusunu CANLI veriyle yanıtlar (VM listesi, "
            "host/VM durumu, kaynak kullanımı, snapshot, event/alarm vb.) — mevcut hypervisor "
            "zeka katmanını (deterministik + gerekirse canlı vCenter sorgusu) kullanır. "
            "Sanallaştırma/hypervisor/VM ile ilgili SPESİFİK bir soru geldiğinde önce bunu dene."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Sorulacak doğal dil sorusu"},
            },
            "required": ["question"],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_vcenter_ask_handler,
        direct_label="vCenter/Hypervisor canlı soru-cevap",
    ),
    "vcenter_live_alarms": Tool(
        name="vcenter_live_alarms",
        description=(
            "vCenter'dan TETİKLENMİŞ (aktif) alarmları CANLI olarak (DB'yi atlayıp doğrudan "
            "vCenter SOAP API'sinden) çeker. 'Şu an aktif alarm var mı', 'kırmızı/sarı alarm var mı' "
            "gibi güncel durum sorularında DB özetine değil bu araca güven."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hypervisor": {"type": "string", "description": "vCenter/hypervisor adı (opsiyonel, tek tanımlıysa gerekmez)"},
                "hours": {"type": "integer", "description": "Kaç saat geriye bakılsın (varsayılan 48)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_vcenter_live_alarms_handler,
        direct_label="vCenter canlı alarm sorgusu",
    ),
    "vcenter_live_tasks": Tool(
        name="vcenter_live_tasks",
        description=(
            "vCenter'daki son görev (task) olaylarını CANLI olarak (DB'yi atlayıp doğrudan vCenter "
            "SOAP API'sinden) çeker — VM oluşturma/silme/migrate/snapshot gibi işlemler ve hataları. "
            "'Son ne işlemler yapıldı', 'hangi görev başarısız oldu' gibi sorularda kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hypervisor": {"type": "string", "description": "vCenter/hypervisor adı (opsiyonel)"},
                "hours": {"type": "integer", "description": "Kaç saat geriye bakılsın (varsayılan 48)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_vcenter_live_tasks_handler,
        direct_label="vCenter canlı task sorgusu",
    ),
    "openshift_ask": Tool(
        name="openshift_ask",
        description=(
            "OpenShift/Kubernetes cluster CANLI genel durumu (node, namespace/proje, sürüm). "
            "YALNIZCA OpenShift/OCP/pod/namespace sorularında kullan — Linux sunucu SSH/"
            "systemd durumuna bakmak için KULLANMA. Detay için list_ocp_pods/list_ocp_events."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "OpenShift cluster adı (opsiyonel)"},
                "question": {"type": "string", "description": "Sorulan soru (bağlam için, opsiyonel)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_openshift_ask_handler,
        direct_label="OpenShift canlı genel durum",
    ),
    "list_kubevirt_vms": Tool(
        name="list_kubevirt_vms",
        description=(
            "OpenShift Virtualization (KubeVirt) üzerindeki VM'leri CANLI olarak listeler "
            "(DB senkronizasyonunu beklemeden anlık durum)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hypervisor": {"type": "string", "description": "KubeVirt hypervisor adı (opsiyonel)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_list_kubevirt_vms_handler,
        direct_label="KubeVirt canlı VM listesi",
    ),
    "list_ocp_pods": Tool(
        name="list_ocp_pods",
        description=(
            "OpenShift/Kubernetes POD listesi (durum, restart, node). "
            "Linux systemd servisi / process listesi DEĞİL — pod/namespace/CrashLoop sorularında kullan. "
            "namespace verilirse yalnızca o proje."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "OpenShift cluster adı (opsiyonel)"},
                "namespace": {"type": "string", "description": "Belirli bir namespace/proje (opsiyonel)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_list_ocp_pods_handler,
        direct_label="OpenShift canlı pod listesi",
    ),
    "list_ocp_events": Tool(
        name="list_ocp_events",
        description=(
            "OpenShift cluster olayları (Node NotReady, CrashLoopBackOff, OOMKilled, PVC, "
            "Deployment). Linux journalctl/syslog DEĞİL — yalnızca OCP/K8s olay sorularında."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "OpenShift cluster adı (opsiyonel)"},
                "hours": {"type": "integer", "description": "Kaç saat geriye bakılsın (varsayılan 48)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_list_ocp_events_handler,
        direct_label="OpenShift canlı olay listesi",
    ),
    "run_diagnostic": Tool(
        name="run_diagnostic",
        description=(
            "Sunucuda SALT-OKUNUR bir teşhis komutu çalıştırır (df, free, top, ps, ss, "
            "vmstat, iostat, systemctl status, journalctl vb.). Yıkıcı komutlar reddedilir."
        ),
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "command": {"type": "string", "description": "Çalıştırılacak salt-okunur komut"},
            },
            "required": ["command"],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_diag_cmd,
        timeout=60,
        # allow_sudo=True → permission denied gelirse stored sudo_password ile otomatik retry yapılır.
        # Risk seviyesi READ_ONLY kalmaya devam eder; onay akışı tetiklenmez.
        allow_sudo=True,
    ),
    "read_service_logs": Tool(
        name="read_service_logs",
        description="Bir servisin (veya sistemin) son loglarını okur (journalctl, salt-okunur).",
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "service": {"type": "string", "description": "systemd servis adı (opsiyonel)"},
                "lines": {"type": "integer", "description": "Satır sayısı (1-1000)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_logs_cmd,
        timeout=30,
        allow_sudo=True,
    ),
    "clean_logs": Tool(
        name="clean_logs",
        description=(
            "Disk açmak için eski journald loglarını temizler (journalctl --vacuum-time). "
            "MUTATING — insan onayı gerekir."
        ),
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "keep_days": {"type": "integer", "description": "Kaç günlük log tutulsun (varsayılan 3)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.MUTATING,
        build_command=_clean_logs_cmd,
        timeout=120,
        allow_sudo=True,
    ),
    "restart_service": Tool(
        name="restart_service",
        description="Bir systemd servisini yeniden başlatır. MUTATING — insan onayı gerekir.",
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "service": {"type": "string", "description": "Yeniden başlatılacak systemd servisi"},
            },
            "required": ["service"],
        },
        risk_level=RiskLevel.MUTATING,
        build_command=_restart_service_cmd,
        timeout=60,
        allow_sudo=True,
    ),
    "update_packages": Tool(
        name="update_packages",
        description=(
            "Paket günceller/kurar (dnf/yum/apt). packages boşsa tüm sistemi günceller. "
            "MUTATING — insan onayı gerekir."
        ),
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "manager": {"type": "string", "enum": ["dnf", "yum", "apt", "apt-get"]},
                "packages": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Kurulacak/güncellenecek paketler (boşsa tüm sistem)",
                },
            },
            "required": [],
        },
        risk_level=RiskLevel.MUTATING,
        build_command=_update_packages_cmd,
        timeout=600,
        allow_sudo=True,
    ),
    "list_free_disks": Tool(
        name="list_free_disks",
        description=(
            "Sunucudaki tüm blok aygıtları ve mevcut PV'leri SALT-OKUNUR listeler. "
            "Boş/kullanılmayan diskleri (filesystem'i ve mount'u olmayan, PV olmayan) "
            "kullanıcıya seçenek olarak sunmadan önce bunu çağır."
        ),
        parameters={
            "type": "object",
            "properties": {"server": {"type": "string", "description": "Sunucu adı veya IP"}},
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_free_disks_cmd,
        timeout=30,
        allow_sudo=True,
    ),
    "lvm_info": Tool(
        name="lvm_info",
        description=(
            "LVM durumunu SALT-OKUNUR listeler (pvs/vgs/lvs): fiziksel volume, "
            "volume group ve logical volume'lar."
        ),
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "scope": {"type": "string", "enum": ["pv", "vg", "lv", "all"],
                          "description": "Hangi LVM katmanı (varsayılan all)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_lvm_info_cmd,
        timeout=30,
        allow_sudo=True,
    ),
    "get_system_summary": Tool(
        name="get_system_summary",
        description="CPU, RAM, uptime ve load bilgisini SALT-OKUNUR özetler (uptime, lscpu, free).",
        parameters={
            "type": "object",
            "properties": {"server": {"type": "string", "description": "Sunucu adı veya IP"}},
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_sys_summary_cmd,
        timeout=30,
    ),
    "get_disk_usage": Tool(
        name="get_disk_usage",
        description="Disk ve dosya sistemi dolulukları ile inode kullanımını SALT-OKUNUR gösterir (df -h / df -i).",
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "mount": {"type": "string", "description": "Belirli bir mount noktası (opsiyonel, örn. /var)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_disk_usage_cmd,
        timeout=30,
    ),
    "get_large_directories": Tool(
        name="get_large_directories",
        description=(
            "Belirtilen dizin altında en fazla alan kullanan alt dizinleri SALT-OKUNUR listeler "
            "(du + sort). Disk doluluğu araştırırken hangi dizinin şiştiğini bulmak için kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "path": {"type": "string", "description": "Taranacak kök dizin (varsayılan /)"},
                "depth": {"type": "integer", "description": "Alt dizin derinliği (1-3, varsayılan 1)"},
                "count": {"type": "integer", "description": "Kaç sonuç gösterilsin (1-30, varsayılan 15)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_large_dirs_cmd,
        timeout=60,
        allow_sudo=True,
    ),
    "get_processes": Tool(
        name="get_processes",
        description="CPU veya RAM tüketimine göre sıralı süreç listesini SALT-OKUNUR döner (ps aux).",
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "sort_by": {"type": "string", "enum": ["cpu", "mem"], "description": "Sıralama kriteri (varsayılan cpu)"},
                "count": {"type": "integer", "description": "Kaç süreç gösterilsin (1-50, varsayılan 15)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_processes_cmd,
        timeout=30,
    ),
    "get_service_status": Tool(
        name="get_service_status",
        description="Bir systemd servisinin durumunu SALT-OKUNUR sorgular (systemctl status).",
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "service": {"type": "string", "description": "systemd servis adı"},
            },
            "required": ["service"],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_service_status_cmd,
        timeout=30,
        allow_sudo=True,
    ),
    "get_service_logs": Tool(
        name="get_service_logs",
        description="Belirlenen systemd servisinin son loglarını SALT-OKUNUR getirir (journalctl -u).",
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "service": {"type": "string", "description": "systemd servis adı"},
                "lines": {"type": "integer", "description": "Satır sayısı (1-1000, varsayılan 100)"},
            },
            "required": ["service"],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_service_logs_cmd,
        timeout=30,
        allow_sudo=True,
    ),
    "get_network_status": Tool(
        name="get_network_status",
        description=(
            "IP adresleri, routing tablosu, dinleyen portlar ve aktif bağlantıları SALT-OKUNUR "
            "kontrol eder (ip addr/route, ss -tulpn)."
        ),
        parameters={
            "type": "object",
            "properties": {"server": {"type": "string", "description": "Sunucu adı veya IP"}},
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_network_status_cmd,
        timeout=30,
        allow_sudo=True,
    ),
    "get_package_status": Tool(
        name="get_package_status",
        description=(
            "Paket ve güncelleme durumunu SALT-OKUNUR sorgular (dnf/apt check-update, rpm/dpkg). "
            "package verilirse yalnızca o paketin kurulu sürümünü gösterir."
        ),
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "package": {"type": "string", "description": "Belirli bir paket adı (opsiyonel)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_package_status_cmd,
        timeout=45,
    ),
    "get_security_events": Tool(
        name="get_security_events",
        description=(
            "SSH giriş denemelerini, başarısız kimlik doğrulamaları, SELinux ve firewall durumunu "
            "SALT-OKUNUR inceler (last, journalctl -u sshd / /var/log/secure, sestatus, firewall-cmd)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "hours": {"type": "integer", "description": "Kaç saat geriye bakılsın (1-168, varsayılan 24)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_security_events_cmd,
        timeout=30,
        allow_sudo=True,
    ),
    "execute_approved_command": Tool(
        name="execute_approved_command",
        description=(
            "Yalnızca ÖNCEDEN ONAYLANMIŞ sabit bir komut listesinden (command_id ile seçilir) "
            "komut çalıştırır — serbest metin komut kabul edilmez. İzinli command_id'ler: "
            + ", ".join(APPROVED_COMMANDS)
            + ". Diğer/keyfi salt-okunur komutlar için run_diagnostic'i kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "command_id": {
                    "type": "string",
                    "enum": sorted(APPROVED_COMMANDS.keys()),
                    "description": "Çalıştırılacak onaylı komutun kimliği",
                },
            },
            "required": ["command_id"],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_approved_command_cmd,
        timeout=30,
        allow_sudo=True,
    ),
    "get_failed_services": Tool(
        name="get_failed_services",
        description=(
            "Linux sunucuda başarısız systemd unit'leri (systemctl --failed). "
            "OpenShift/Kubernetes pod durumu DEĞİL — pod/CrashLoop için list_ocp_pods kullan. "
            "'Hangi servis durmuş', 'systemd failed' gibi Linux sorularında kullan."
        ),
        parameters={
            "type": "object",
            "properties": {"server": {"type": "string", "description": "Sunucu adı veya IP"}},
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_failed_services_cmd,
        timeout=30,
    ),
    "get_stuck_processes": Tool(
        name="get_stuck_processes",
        description=(
            "Zombie (Z) ve D-state (disk/IO bekleyen) süreçleri SALT-OKUNUR listeler. "
            "'Zombie process var mı', 'D state process var mı' gibi sorularda kullan."
        ),
        parameters={
            "type": "object",
            "properties": {"server": {"type": "string", "description": "Sunucu adı veya IP"}},
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_stuck_processes_cmd,
        timeout=30,
    ),
    "get_reboot_info": Tool(
        name="get_reboot_info",
        description=(
            "Sunucunun ne zamandır açık olduğunu, son açılış zamanını ve son "
            "açılış/kapanış geçmişini SALT-OKUNUR gösterir. "
            "'Sunucu ne zamandır açık', 'son reboot ne zaman/neden oldu' gibi sorularda kullan."
        ),
        parameters={
            "type": "object",
            "properties": {"server": {"type": "string", "description": "Sunucu adı veya IP"}},
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_reboot_info_cmd,
        timeout=30,
    ),
    "get_kernel_errors": Tool(
        name="get_kernel_errors",
        description=(
            "Kernel loglarında hata, panic, oops, segfault ve OOM (out-of-memory) izlerini "
            "SALT-OKUNUR tarar. 'Kernel loglarında hata var mı', 'panic oluşmuş mu', "
            "'OOM logları var mı', 'segmentation fault oluşmuş mu' gibi sorularda kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "hours": {"type": "integer", "description": "Kaç saat geriye bakılsın (1-168, varsayılan 24)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_kernel_errors_cmd,
        timeout=30,
        allow_sudo=True,
    ),
    "get_admin_diag_snapshot": Tool(
        name="get_admin_diag_snapshot",
        description=(
            "Kıdemli Linux sysadmin checklist'ini tek turda SALT-OKUNUR toplar: journal err+, "
            "dmesg sorun satırları, failed units, auth/secure, fstab, sysctl conf, sshd_config özeti, "
            "SELinux, DNS, firewall, needs-restarting. 'Analiz et', 'kök neden', 'loglara bak', "
            "'configleri kontrol et', 'sorun teşhisi', 'dmesg + journal' gibi derin tanı sorularında kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "hours": {"type": "integer", "description": "Journal için saat (1-168, varsayılan 24)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_admin_diag_snapshot_cmd,
        timeout=60,
        allow_sudo=True,
    ),
    "get_security_patch_status": Tool(
        name="get_security_patch_status",
        description=(
            "Çalışan/kurulu kernel sürümlerini, yeniden başlatma gerekip gerekmediğini ve "
            "bekleyen güvenlik güncellemelerini (CVE/security patch) SALT-OKUNUR sorgular. "
            "'Güvenlik güncellemesi gerekiyor mu', 'kernel güncel mi', 'reboot gerekli mi', "
            "'güvenlik patchleri eksik mi' gibi sorularda kullan."
        ),
        parameters={
            "type": "object",
            "properties": {"server": {"type": "string", "description": "Sunucu adı veya IP"}},
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_security_patch_status_cmd,
        timeout=45,
    ),
    "get_mount_health": Tool(
        name="get_mount_health",
        description=(
            "Mount edilmiş dosya sistemlerini, read-only mount'ları, NFS/CIFS bağlantılarının "
            "durumunu ve multipath yapılandırmasını SALT-OKUNUR kontrol eder. "
            "'Mount durumları', 'NFS/CIFS mount sağlıklı mı', 'read-only mount olmuş mu', "
            "'multipath durumu' gibi sorularda kullan."
        ),
        parameters={
            "type": "object",
            "properties": {"server": {"type": "string", "description": "Sunucu adı veya IP"}},
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=_mount_health_cmd,
        timeout=30,
        allow_sudo=True,
    ),
    "manage_lvm": Tool(
        name="manage_lvm",
        description=(
            "LVM hacim BÜYÜTME/oluşturma işlemleri (MUTATING — insan onayı gerekir). "
            "Operasyonlar: create_pv (pvcreate), create_vg (vgcreate, bir/birden çok diskten "
            "yeni volume group), extend_vg (vgextend), create_lv (lvcreate), "
            "extend_lv (lvextend, opsiyonel resize_fs ile FS de büyür). "
            "Küçültme/silme (lvreduce/lvremove/vgremove) GÜVENLİK NEDENİYLE DESTEKLENMEZ."
        ),
        parameters={
            "type": "object",
            "properties": {
                "server": {"type": "string", "description": "Sunucu adı veya IP"},
                "operation": {"type": "string",
                              "enum": ["create_pv", "create_vg", "extend_vg", "create_lv", "extend_lv"]},
                "vg_name": {"type": "string", "description": "Volume group adı"},
                "lv_name": {"type": "string", "description": "Logical volume adı"},
                "size": {"type": "string",
                         "description": "Boyut: '10G', '+5G' (büyütme) veya '100%FREE'"},
                "device": {"type": "string", "description": "Tek fiziksel aygıt, örn. /dev/sdb"},
                "devices": {"type": "array", "items": {"type": "string"},
                            "description": "create_vg için bir/birden çok aygıt, örn. ['/dev/sdb','/dev/sdc']"},
                "resize_fs": {"type": "boolean",
                              "description": "extend_lv için dosya sistemini de büyüt (-r)"},
            },
            "required": ["operation"],
        },
        risk_level=RiskLevel.MUTATING,
        build_command=_lvm_manage_cmd,
        timeout=300,
        allow_sudo=True,
    ),
}


# Platform domain etiketleri — sohbet kapsamına göre tool filtresi için.
_TOOL_DOMAIN_OVERRIDE = {
    "infra_overview": frozenset({"infra"}),
    "vcenter_ask": frozenset({"vcenter"}),
    "vcenter_live_alarms": frozenset({"vcenter"}),
    "vcenter_live_tasks": frozenset({"vcenter"}),
    "openshift_ask": frozenset({"openshift"}),
    "list_kubevirt_vms": frozenset({"openshift", "vcenter"}),
    "list_ocp_pods": frozenset({"openshift"}),
    "list_ocp_events": frozenset({"openshift"}),
}
for _tool_name, _tool in TOOLS.items():
    if _tool_name in _TOOL_DOMAIN_OVERRIDE:
        _tool.domains = _TOOL_DOMAIN_OVERRIDE[_tool_name]


# Platform sohbeti → izinli tool domain setleri (None = tümü).
PLATFORM_TOOL_DOMAINS = {
    "linux": frozenset({"linux", "infra"}),
    "openshift": frozenset({"openshift", "infra"}),
    "windows": frozenset({"windows", "infra"}),
    "virt": frozenset({"vcenter", "infra"}),
    "exadata": frozenset({"linux", "infra"}),
    "unified": None,
}


def domains_for_platform(platform: Optional[str]) -> Optional[frozenset]:
    """Sohbet platformuna göre tool domain filtresi; bilinmeyen → linux."""
    if not platform:
        return PLATFORM_TOOL_DOMAINS["linux"]
    key = platform.strip().lower()
    if key in PLATFORM_TOOL_DOMAINS:
        return PLATFORM_TOOL_DOMAINS[key]
    return PLATFORM_TOOL_DOMAINS["linux"]


def get_tool(name: str) -> Optional[Tool]:
    return TOOLS.get(name)


# ask_user: gerçek bir shell tool değil — orchestrator tarafından özel işlenir.
# Agent, kullanıcının somut seçenekler arasından seçim yapmasını istediğinde çağırır.
ASK_USER_SPEC: Dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "ask_user",
        "description": (
            "Kullanıcıya somut seçenekler sunup seçim yaptırır ve yanıtı bekler. "
            "Argümanları (hangi disk, hangi boyut vb.) TAHMİN ETME; bunun yerine önce "
            "list_free_disks/lvm_info gibi salt-okunur tool'larla adayları topla, sonra "
            "ask_user ile net seçenekler sun. Akış, kullanıcı seçene kadar duraklar."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Kullanıcıya sorulan soru"},
                "options": {
                    "type": "array", "items": {"type": "string"},
                    "description": "Seçenekler (insan-okur metin), örn. '/dev/sdb (500G, boş)'",
                },
                "allow_multiple": {"type": "boolean",
                                   "description": "Birden çok seçim yapılabilir mi"},
            },
            "required": ["question", "options"],
        },
    },
}


def tool_specs() -> List[Dict[str, Any]]:
    """LLM'e gönderilecek tool şemaları — Linux + Windows araçları."""
    specs = [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": t.parameters,
            },
        }
        for t in TOOLS.values()
    ]
    # Windows tools
    try:
        from app.services.agent.tools_windows import WINDOWS_TOOLS
        for wt in WINDOWS_TOOLS:
            specs.append({"type": "function", "function": wt})
    except Exception:
        pass
    specs.append(ASK_USER_SPEC)
    return specs


def tool_specs_read_only(domains: Optional[frozenset] = None) -> List[Dict[str, Any]]:
    """Yalnızca READ_ONLY araçların şemalarını döner (mutating araçlar ve ask_user HARİÇ).

    Onay akışı barındırmayan salt-okunur sohbet döngüleri (örn. Unified Chat'in
    agentic modu) için kullanılır — LLM burada asla bir değişiklik yapan aracı
    çağıramaz, sadece bilgi toplayabilir.

    domains verilirse yalnızca o platform kümesiyle kesişen araçlar döner
    (Linux sohbetinde OpenShift araçlarının karışmasını önlemek için).
    """
    specs = [
        {
            "type": "function",
            "function": {"name": t.name, "description": t.description, "parameters": t.parameters},
        }
        for t in TOOLS.values()
        if t.risk_level == RiskLevel.READ_ONLY
        and (domains is None or (t.domains & domains))
    ]
    try:
        from app.services.agent.tools_windows import WINDOWS_TOOLS, MUTATING_WIN_TOOLS
        if domains is None or ("windows" in domains):
            for wt in WINDOWS_TOOLS:
                if wt["name"] not in MUTATING_WIN_TOOLS:
                    specs.append({"type": "function", "function": wt})
    except Exception:
        pass
    return specs
