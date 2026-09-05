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


def _cross_entity_match_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.cross_entity_match import cross_entity_match
        names = args.get("names")
        if isinstance(names, str):
            names = [n.strip() for n in names.replace(";", ",").split(",") if n.strip()]
        modules = args.get("modules")
        if isinstance(modules, str):
            modules = [m.strip() for m in modules.replace(";", ",").split(",") if m.strip()]
        return cross_entity_match(
            db,
            names=names if isinstance(names, list) else None,
            modules=modules if isinstance(modules, list) else None,
            limit=int(args.get("limit") or 50),
        )
    except Exception as e:
        logger.error("[Tool] cross_entity_match hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _vcenter_snapshot_summary_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Fleet-wide snapshot özeti — vCenter SOAP canlı (snapshot_count / en eski)."""
    try:
        from app.services import vcenter_vm_performance as perf
        r = perf.fetch_live_vm_stats(db)
        vms = r.get("vms") or []
        host_filter = (args.get("host_name") or args.get("esxi_host") or "").strip().lower()
        ds_filter = (args.get("datastore") or "").strip().lower()
        if host_filter:
            vms = [v for v in vms if host_filter in (v.get("name") or "").lower()
                   or host_filter in str(v.get("hypervisor") or "").lower()]
        with_snap = [v for v in vms if (v.get("snapshot_count") or 0) > 0]
        with_snap.sort(key=lambda x: -(x.get("snapshot_count") or 0))
        note = None
        if with_snap and all(v.get("snapshot_space_gb") is None for v in with_snap):
            note = (
                "Bu vCenter/ESXi sürümü summary.storage'ı desteklemiyor — TOPLAM "
                "yaklaşık alan bu fleet özetinde mevcut değil. Belirli bir VM'in "
                "GERÇEK snapshot boyutunu öğrenmek için vcenter_list_vm_snapshots "
                "(vm_name ile) çağır — orada per-snapshot gerçek byte boyutu döner."
            )
        return {
            "ok": True,
            "source": "vcenter_live",
            "count": len(with_snap),
            "total_vms_scanned": len(vms),
            "errors": r.get("errors") or [],
            "vms": with_snap[: int(args.get("limit") or 100)],
            **({"note": note} if note else {}),
        }
    except Exception as e:
        logger.error("[Tool] vcenter_snapshot_summary hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _vcenter_list_vm_snapshots_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Tek VM snapshot ağacı — vCenter SOAP list_snapshots."""
    from app.models.server import Server
    from app.services.snapshot_service import list_external_snapshots
    from app.services.platform_scope import vm_filter_condition

    name = (args.get("vm_name") or args.get("name") or "").strip()
    server_id = args.get("server_id")
    srv = None
    if server_id:
        srv = db.query(Server).filter(Server.id == int(server_id)).first()
    elif name:
        srv = db.query(Server).filter(
            vm_filter_condition(),
            Server.name.ilike(name),
        ).first()
        if not srv:
            srv = db.query(Server).filter(
                vm_filter_condition(),
                Server.name.ilike(f"%{name}%"),
            ).first()
    if not srv:
        return {"ok": False, "error": "VM bulunamadı — vm_name veya server_id verin"}
    # Tek VM sorgusu — her snapshot için GERÇEK boyutu da çek (layout + datastore
    # browser üzerinden; tahmin/reçete değil, gerçek dosya sistemi boyutu).
    result = list_external_snapshots(srv, db, include_size=True)
    return {
        "ok": bool(result.get("success")),
        "vm": srv.name,
        "server_id": srv.id,
        "platform": result.get("platform"),
        "snapshots": result.get("snapshots") or [],
        "size_note": result.get("size_note"),
        "message": result.get("message"),
        "source": "vcenter_soap",
    }


def _vcenter_ask_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Canlı READ-ONLY yönlendirme — tam envanter dump yerine atomik araçlar."""
    question = (args.get("question") or "").strip()
    if not question:
        return {"ok": False, "error": "question zorunlu"}
    q = question.lower()
    try:
        from app.services.chat_intent import classify_chat_intent, ChatIntentKind
        intent = classify_chat_intent(question)
        if intent.kind == ChatIntentKind.CONCEPTUAL:
            from app.services.hypervisor_intelligence import answer_hypervisor_question
            result = answer_hypervisor_question(db, question)
            return {"ok": not bool(result.get("error")), "answer": result.get("answer"), "source": "conceptual"}
        if "snapshot" in q:
            vm_hint = args.get("vm_name") or ""
            size_asked = any(k in q for k in (
                "boyut", "büyüklük", "buyukluk", "kaç gb", "kac gb", "ne kadar", "yer kaplı",
            ))
            if vm_hint and (
                size_asked
                or any(k in q for k in ("listele", "göster", "goster", "ağaç", "agac", "hangi", "soap"))
            ):
                # Belirli bir VM + boyut/liste isteği → gerçek per-snapshot boyutu
                # dönen atomik araca git (tahmin/reçete değil, gerçek SOAP sorgusu).
                return _vcenter_list_vm_snapshots_handler(db, {"vm_name": vm_hint}, ctx)
            return _vcenter_snapshot_summary_handler(db, {"limit": 200}, ctx)
        from app.services import vcenter_vm_performance as perf
        if any(k in q for k in ("canlı", "canli", "anlık", "anlik", "perf", "cpu", "ram")):
            r = perf.fetch_live_vm_stats(db)
            return {"ok": True, "source": "vcenter_live", "vms": (r.get("vms") or [])[:50], "errors": r.get("errors")}
        from app.services.hypervisor_intelligence import answer_hypervisor_question
        result = answer_hypervisor_question(db, question)
        if result.get("error"):
            return {"ok": False, "error": result["error"]}
        return {"ok": True, "answer": result.get("answer"), "source": "hypervisor_intelligence"}
    except Exception as e:
        logger.error(f"[Tool] vcenter_ask hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _db_list_vms_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.virt_db_query import list_vms_db
        from app.services.virt_inventory_policy import (
            effective_vm_list_limit,
            is_full_scan_request,
        )
        default_lim = effective_vm_list_limit()
        lim = int(args.get("limit") or default_lim)
        if is_full_scan_request():
            lim = max(lim, default_lim)
        fields = args.get("fields")
        if isinstance(fields, str):
            fields = [f.strip() for f in fields.split(",") if f.strip()]
        include_disks = args.get("include_disks")
        if include_disks is None:
            include_disks = True
        return list_vms_db(
            db,
            hypervisor=args.get("hypervisor"),
            power_state=args.get("power_state"),
            host_name=args.get("host_name"),
            cluster=args.get("cluster"),
            datastore=args.get("datastore"),
            name_filter=args.get("name_filter"),
            limit=lim,
            fields=fields if isinstance(fields, list) else None,
            include_disks=bool(include_disks),
        )
    except Exception as e:
        logger.error("[Tool] db_list_vms hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _db_vm_detail_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.virt_db_query import vm_detail_db
        return vm_detail_db(db, name=args.get("name"), server_id=args.get("server_id"))
    except Exception as e:
        logger.error("[Tool] db_vm_detail hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _db_list_datastores_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.virt_db_query import list_datastores_db
        fields = args.get("fields")
        if isinstance(fields, str):
            fields = [f.strip() for f in fields.split(",") if f.strip()]
        return list_datastores_db(
            db,
            hypervisor=args.get("hypervisor"),
            name_filter=args.get("name_filter"),
            fields=fields if isinstance(fields, list) else None,
        )
    except Exception as e:
        logger.error("[Tool] db_list_datastores hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _db_list_esx_hosts_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.virt_db_query import list_esx_hosts_db
        fields = args.get("fields")
        if isinstance(fields, str):
            fields = [f.strip() for f in fields.split(",") if f.strip()]
        return list_esx_hosts_db(
            db,
            hypervisor=args.get("hypervisor"),
            name_filter=args.get("name_filter"),
            fields=fields if isinstance(fields, list) else None,
        )
    except Exception as e:
        logger.error("[Tool] db_list_esx_hosts hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _db_list_clusters_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.virt_db_query import list_clusters_db
        return list_clusters_db(
            db,
            hypervisor=args.get("hypervisor"),
            name_filter=args.get("name_filter") or args.get("cluster"),
        )
    except Exception as e:
        logger.error("[Tool] db_list_clusters hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _db_metric_trend_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Host/VM/datastore zaman serisinden trend + tükenme tahmini (deterministik).

    vCenter'ın tarihsel rollup'ı her ortamda yok (doğrudan ESXi bağlantısında
    yalnız realtime vardır); bu araç kalıcı hypertable'lardan hesapladığı için
    o ortamlarda da trend sorularını yanıtlar.
    """
    try:
        from app.services.virt_trend_query import run_metric_trend
        return run_metric_trend(
            db,
            entity_type=args.get("entity_type") or args.get("entity") or "host",
            metric=args.get("metric"),
            name_filter=args.get("name_filter") or args.get("name") or args.get("target"),
            hypervisor=args.get("hypervisor"),
            days=args.get("days") or args.get("lookback_days") or 7,
            top_n=args.get("top_n") or args.get("limit") or 10,
            order=args.get("order") or "worsening",
            threshold=args.get("threshold"),
        )
    except Exception as e:
        logger.error("[Tool] db_metric_trend hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _virt_health_overview_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Sanallaştırma ortamının sağlık skoru + kritik/uyarı bulguları.

    Bu veriyi üreten motor (`virt_ops_center`) daha önce yalnızca UI'a REST
    üzerinden servis ediliyordu; "vCenter sağlıklı mı / ortamda problem var mı"
    sorularında ajanın çağırabileceği bir araç yoktu.
    """
    try:
        from app.services.virt_ops_center import build_virt_command_center
        data = build_virt_command_center(db)

        def _slim_host(card: Dict[str, Any]) -> Dict[str, Any]:
            return {
                "host": card.get("host_name") or card.get("hypervisor_name"),
                "platform": card.get("platform"),
                "severity": card.get("max_severity"),
                "cpu_pct": card.get("cpu_usage_pct"),
                "mem_pct": card.get("mem_usage_pct"),
                "ds_pct": card.get("ds_usage_pct"),
                "vms_running": card.get("vms_running"),
                "connection_state": card.get("connection_state"),
                "maintenance": card.get("maintenance_mode"),
                "issues": [
                    {
                        "severity": i.get("severity"),
                        "category": i.get("category"),
                        "title": i.get("title"),
                        "detail": i.get("detail"),
                    }
                    for i in (card.get("issues") or [])
                ],
                "suggested_actions": card.get("suggested_actions") or [],
            }

        limit = max(1, min(int(args.get("limit") or 20), 60))
        logs = data.get("platform_logs") or []
        if bool(args.get("include_logs", True)):
            log_out = [
                {
                    "severity": l.get("severity"),
                    "category": l.get("category"),
                    "title": l.get("title"),
                    "host": l.get("host_name"),
                    "timestamp": l.get("timestamp"),
                }
                for l in logs
                if (l.get("severity") in ("critical", "emergency", "warning"))
            ][:limit]
        else:
            log_out = []

        # Donanım sensörü özetini buraya da koyuyoruz: model genel sağlık
        # sorusunda bu aracı seçtiğinde "hangi hostta sensör alarmı var"
        # sorusunu ikinci bir tur olmadan yanıtlayabilsin.
        hardware_health: List[Dict[str, Any]] = []
        try:
            from app.services.virt_db_query import list_esx_hosts_db
            hosts = list_esx_hosts_db(
                db,
                fields=["name", "cluster", "overall_status", "sensor_bad_count",
                        "bad_sensors", "config_issues"],
            )
            hardware_health = [
                h for h in (hosts.get("hosts") or [])
                if (h.get("overall_status") not in (None, "green"))
                or (h.get("sensor_bad_count") or 0) > 0
                or (h.get("config_issues") or [])
            ][:limit]
        except Exception as hh_e:
            logger.debug("virt_health_overview donanım sağlığı eki atlandı: %s", hh_e)

        # Küçük modeller skor/kart yapısını yorumlarken "sorun yok" diyebiliyor;
        # tek cümlelik hazır hüküm bu hatayı büyük ölçüde kapatıyor.
        _health = data.get("health") or {}
        _crit = int(data.get("critical_count") or 0)
        _warn = int(data.get("warning_count") or 0)
        _worst = ", ".join(
            f"{c.get('host_name') or c.get('hypervisor_name')}: "
            + "; ".join((i.get("title") or "") for i in (c.get("issues") or [])[:2])
            for c in (data.get("critical_hosts") or [])[:3]
        )
        if _crit or _warn:
            verdict = (
                f"ORTAM SORUNLU — skor {_health.get('score')}/100 "
                f"({_health.get('label')}), {_crit} kritik / {_warn} uyarı bulgu."
                + (f" Öne çıkanlar → {_worst}." if _worst else "")
            )
        else:
            verdict = (
                f"Kritik/uyarı bulgu yok — skor {_health.get('score')}/100 "
                f"({_health.get('label')})."
            )
        if hardware_health:
            verdict += (
                " Donanım: "
                + ", ".join(
                    f"{h.get('name')} ({h.get('overall_status')}, "
                    f"{h.get('sensor_bad_count') or 0} sensör)"
                    for h in hardware_health[:3]
                )
                + "."
            )

        return {
            "ok": True,
            "source": "virt_ops_center (hypervisor_host_metrics + system_events)",
            "verdict": verdict,
            "verdict_note": "Bu cümle hazır hükümdür; cevabında bunu esas al, tersini iddia etme.",
            "health": data.get("health"),
            "hardware_health": hardware_health,
            "hardware_health_note": (
                "Yalnız sorunlu host'lar listelenir (overall_status green değil veya "
                "sensör/yapılandırma uyarısı var). Boşsa donanım sağlığı temizdir."
            ),
            "totals": data.get("totals"),
            "critical_count": data.get("critical_count"),
            "warning_count": data.get("warning_count"),
            "critical_hosts": [_slim_host(c) for c in (data.get("critical_hosts") or [])[:limit]],
            "warning_hosts": [_slim_host(c) for c in (data.get("warning_hosts") or [])[:limit]],
            "recent_issues": log_out,
            "window_hours": data.get("window_hours"),
            "generated_at": data.get("generated_at"),
            "coverage_note": (
                "Sağlık skoru host CPU/RAM/datastore eşikleri + son 24 saatlik "
                "event/alarm kayıtlarından hesaplanır. Donanım sensörü verisi "
                "db_list_esx_hosts (fields=[name,overall_status,sensor_bad_count]) "
                "ile, HA/failover durumu db_list_clusters ile sorgulanır."
            ),
        }
    except Exception as e:
        logger.error("[Tool] virt_health_overview hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


# Jenerik property okuyucu için kürasyonlu path kataloğu — model bu menüden
# seçer, serbest path de kabul edilir (doğrulama retrieve_properties'te).
_VC_PROPERTY_CATALOG: Dict[str, Dict[str, str]] = {
    "HostSystem": {
        "name": "ESXi host adı",
        "parent": "Cluster/ComputeResource MOR",
        "summary.overallStatus": "green/yellow/red",
        "summary.rebootRequired": "Yeniden başlatma gerekli mi",
        "config.product.fullName": "ESXi sürüm adı",
        "hardware.biosInfo.biosVersion": "BIOS sürümü",
        "runtime.inMaintenanceMode": "Bakım modu",
        "runtime.bootTime": "Son açılış zamanı",
        "runtime.healthSystemRuntime.systemHealthInfo.numericSensorInfo": "Donanım sensörleri",
        "config.storageDevice.multipathInfo": "Multipath/LUN path durumu",
        "config.dateTimeInfo.ntpConfig.server": "NTP sunucuları",
        "configIssue": "Yapılandırma uyarıları",
    },
    "ClusterComputeResource": {
        "name": "Cluster adı",
        "host": "Üye host MOR listesi",
        "summary.effectiveCpu": "Kullanılabilir CPU (MHz)",
        "summary.effectiveMemory": "Kullanılabilir RAM (MB)",
        "configuration.dasConfig.admissionControlPolicy": "HA admission control politikası",
        "configuration.drsConfig.vmotionRate": "DRS migration eşiği (1-5)",
        "configurationEx.drsConfig.option": "DRS gelişmiş ayarlar",
    },
    "Datastore": {
        "name": "Datastore adı",
        "summary.capacity": "Toplam kapasite (byte)",
        "summary.freeSpace": "Boş alan (byte)",
        "summary.uncommitted": "Thin provisioning taahhüt edilmemiş alan",
        "summary.maintenanceMode": "Bakım modu",
        "summary.accessible": "Erişilebilir mi",
        "host": "Mount eden host'lar ve mount durumu",
        "iormConfiguration.enabled": "Storage IO Control açık mı",
        "info.vmfs.ssd": "SSD mi",
    },
    "VirtualMachine": {
        "name": "VM adı",
        "runtime.host": "Çalıştığı host MOR",
        "runtime.powerState": "Güç durumu",
        "summary.storage.committed": "Kullanılan disk (byte)",
        "summary.storage.uncommitted": "Taahhüt edilmemiş (snapshot/thin)",
        "config.version": "Hardware sürümü",
        "guest.toolsRunningStatus": "VMware Tools durumu",
        "config.hardware.numCPU": "vCPU",
        "config.hardware.memoryMB": "RAM (MB)",
        "snapshot.rootSnapshotList": "Snapshot ağacı",
    },
}


def _vcenter_property_read_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Jenerik READ-ONLY vSphere property okuyucu.

    Sabit pathSet'lerin kapsamadığı bir alan sorulduğunda kod değişikliği
    beklemeden yanıt üretir. Yalnız RetrieveProperties + ContainerView; mutate
    method yüzeyi yok (bkz. perf_catalog.SOAP_MUTATE_DENY).
    """
    try:
        from app.models.hypervisor import Hypervisor, HypervisorType
        from app.services.hypervisor_credentials import hv_password
        from app.services.vmware.perf_catalog import is_mutate_method
        from app.services.vmware.vcenter_client import VCenterClient

        if bool(args.get("list_catalog")):
            return {
                "ok": True,
                "read_only": True,
                "catalog": _VC_PROPERTY_CATALOG,
                "hint": (
                    "object_type + path_set ile çağır. Katalogdaki path'ler "
                    "önerilerdir; vSphere API'sindeki başka bir path de verilebilir."
                ),
            }

        object_type = (args.get("object_type") or "").strip()
        if not object_type:
            return {
                "ok": False,
                "error": "object_type zorunlu (HostSystem, ClusterComputeResource, Datastore, VirtualMachine …)",
                "hint": "list_catalog=true ile kullanılabilir tip/path listesine bak",
            }

        path_set = (
            args.get("path_set") or args.get("paths")
            or args.get("properties") or args.get("property_set")
        )
        if isinstance(path_set, str):
            path_set = [p.strip() for p in path_set.replace(";", ",").split(",") if p.strip()]
        if not isinstance(path_set, list) or not path_set:
            return {"ok": False, "error": "path_set zorunlu (en az bir property path)"}

        # Savunma: mutate method adı property gibi geçirilmiş olabilir
        for p in path_set:
            if is_mutate_method(str(p)):
                return {"ok": False, "error": f"Mutate method yasak: {p}"}
        if not any(str(p).strip().lower() == "name" for p in path_set):
            path_set = ["name"] + list(path_set)

        q = db.query(Hypervisor).filter(Hypervisor.hypervisor_type == HypervisorType.VMWARE)
        hv_name = (args.get("hypervisor") or "").strip().lower()
        hv = None
        if hv_name:
            for cand in q.all():
                if (cand.name or "").lower() == hv_name or (cand.ip_address or "") == hv_name:
                    hv = cand
                    break
        hv = hv or q.first()
        if not hv:
            return {"ok": False, "error": "Tanımlı VMware vCenter bulunamadı"}

        client = VCenterClient(
            host=hv.ip_address or hv.hostname,
            username=hv.username or (hv.connection_config or {}).get("username", ""),
            password=hv_password(hv),
            port=hv.port or 443,
            verify_ssl=False,
        )
        rows = client.retrieve_properties(
            object_type,
            path_set,
            name_filter=args.get("name_filter") or args.get("target"),
            limit=max(1, min(int(args.get("limit") or 50), 300)),
        )
        return {
            "ok": True,
            "read_only": True,
            "mutate": False,
            "source": "vcenter_soap_retrieve_properties",
            "hypervisor": hv.name,
            "object_type": object_type,
            "path_set": path_set,
            "count": len(rows),
            "objects": rows,
            "note": (
                "Boş sonuç: path yanlış olabilir veya bu ortamda o özellik "
                "yapılandırılmamıştır. Kullanılabilir path önerileri için "
                "list_catalog=true."
            ) if not rows else None,
        }
    except Exception as e:
        logger.error("[Tool] vcenter_property_read hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _infra_report_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Hazır rapor motoru (kapasite/forecast/risk/anomali…) — hesabı motor yapar.

    Trend/forecast aritmetiğini modele bıraktığımızda uydurma sayı riski var;
    burada `report_engine` deterministik üretir, model yalnız yorumlar.
    """
    try:
        from app.services.report_engine import (
            REPORT_REGISTRY, format_report_as_markdown,
        )
        rtype = (
            args.get("report_type") or args.get("type") or args.get("report") or ""
        ).strip().lower()
        available = sorted(REPORT_REGISTRY.keys())
        if not rtype or rtype not in REPORT_REGISTRY:
            return {
                "ok": False,
                "error": f"Geçersiz report_type: {rtype or '(boş)'}",
                "available_types": available,
            }
        data = REPORT_REGISTRY[rtype](db) or {}
        out: Dict[str, Any] = {
            "ok": True,
            "source": "report_engine",
            "report_type": rtype,
            "available_types": available,
        }
        if bool(args.get("markdown", True)):
            try:
                out["markdown"] = format_report_as_markdown(rtype, data)
            except Exception as fe:
                logger.debug("format_report_as_markdown(%s): %s", rtype, fe)
        if bool(args.get("include_raw", False)):
            out["data"] = data
        else:
            # Ham veri bağlamı şişirebilir; yalnız üst düzey özet alanları
            out["summary"] = {
                k: v for k, v in data.items()
                if not isinstance(v, (list, dict))
            }
        return out
    except Exception as e:
        logger.error("[Tool] infra_report hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _knowledge_search_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Bilgi bankası / runbook / incident geçmişi semantik arama (pgvector).

    RAG şu ana kadar yalnızca endpoint içinde PASİF olarak enjekte ediliyordu:
    model kendi kararıyla arama yapamıyor, ilk retrieval ıskalarsa ikinci şansı
    olmuyordu. Bu araç aynı motoru ajanın erişimine açar.
    """
    query = (args.get("query") or args.get("question") or "").strip()
    if not query:
        return {"ok": False, "error": "query zorunlu"}
    try:
        import asyncio
        from app.services.rag_service import get_rag_context_for_message

        collections = args.get("collections")
        if isinstance(collections, str):
            collections = [c.strip() for c in collections.replace(";", ",").split(",") if c.strip()]
        if not isinstance(collections, list) or not collections:
            collections = None

        async def _run():
            return await get_rag_context_for_message(query, collections=collections)

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            ctx_out = asyncio.run(_run())
        else:
            # Zaten bir event loop içindeyiz (async endpoint) → ayrı thread
            import concurrent.futures as _cf
            with _cf.ThreadPoolExecutor(max_workers=1) as ex:
                ctx_out = ex.submit(lambda: asyncio.run(_run())).result(timeout=120)

        found = {k: v for k, v in (ctx_out or {}).items() if (v or "").strip()}
        return {
            "ok": True,
            "source": "rag_pgvector",
            "query": query,
            "collections_searched": collections or ["runbook", "incidents", "metrics", "knowledge"],
            "hits": found,
            "empty": not found,
            "note": None if found else (
                "Bilgi bankasında bu sorguya yakın kayıt bulunamadı. "
                "Farklı/daha kısa anahtar kelimelerle tekrar denenebilir."
            ),
        }
    except Exception as e:
        logger.error("[Tool] knowledge_search hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _prometheus_query_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Prometheus/envanter doğal dil sorgusu (NLQ hattı → PromQL + DB).

    `services/nlq` hattı yalnızca kendi sayfasından erişilebiliyordu; hiçbir
    sohbet yüzeyi bir soruyu buraya yönlendiremiyordu.
    """
    question = (args.get("question") or args.get("query") or "").strip()
    if not question:
        return {"ok": False, "error": "question zorunlu"}
    try:
        from app.services.nlq.pipeline import run_nlq
        result = run_nlq(
            db, question,
            user=(ctx or {}).get("user"),
            live_check=args.get("live_check"),
        )
        status = result.get("status")
        return {
            "ok": status == "success",
            "source": "nlq_prometheus",
            "status": status,
            "question": question,
            "summary": result.get("summary"),
            "results": (result.get("results") or [])[:100],
            "answer_markdown": result.get("answer_markdown"),
            "interpreted_query": result.get("interpreted_query"),
            "reason": result.get("reason"),
            "missing_fields": result.get("missing_fields"),
            "note": (
                "Bu araç guest OS / envanter metriklerini (node_exporter, "
                "windows_exporter) sorgular. ESXi/hipervizör seviyesi metrikler "
                "için db_list_esx_hosts veya vcenter_perf_query kullan."
            ),
        }
    except Exception as e:
        logger.error("[Tool] prometheus_query hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _db_virt_alarms_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.virt_db_query import list_virt_alarms_db
        return list_virt_alarms_db(
            db,
            hours=int(args.get("hours") or 48),
            unresolved_only=bool(args.get("unresolved_only", True)),
            limit=int(args.get("limit") or 50),
        )
    except Exception as e:
        logger.error("[Tool] db_virt_alarms hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _db_virt_cross_match_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """READ-ONLY: host/VM/datastore/alarm SoT'larını ortak anahtarla birleştir."""
    try:
        from app.services.virt_db_query import cross_match_virt_db
        fields = args.get("fields")
        if isinstance(fields, str):
            fields = [f.strip() for f in fields.split(",") if f.strip()]
        include = args.get("include")
        if isinstance(include, str):
            include = [x.strip() for x in include.split(",") if x.strip()]
        return cross_match_virt_db(
            db,
            join_on=str(args.get("join_on") or "host"),
            include=include if isinstance(include, list) else None,
            hypervisor=args.get("hypervisor"),
            host_name=args.get("host_name"),
            fields=fields if isinstance(fields, list) else None,
            hours=int(args.get("hours") or 48),
            limit=int(args.get("limit") or 100),
        )
    except Exception as e:
        logger.error("[Tool] db_virt_cross_match hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _db_list_critical_events_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """READ-ONLY: system_events tablosundan kritik/hata seviyeli olayları listeler.

    'Sunucularda/VM'lerde kritik event var mı?' tarzı sorularda gerçek veriye
    dayanmayı garanti eder — bu tool eklenmeden önce bu tür sorular hiçbir araç
    çağırmadan LLM tarafından tamamen uydurma (yanlış tarih/kaynak) cevaplanıyordu.
    """
    try:
        from datetime import datetime, timedelta, timezone
        from app.models.event import SystemEvent

        hours = max(1, min(int(args.get("hours") or 24), 24 * 30))
        since = datetime.now(timezone.utc) - timedelta(hours=hours)

        sev_arg = (args.get("severity") or "critical").strip().lower()
        if sev_arg in ("all", "hepsi", "*"):
            severities = None
        else:
            severities = [s.strip() for s in sev_arg.split(",") if s.strip()]

        limit = max(1, min(int(args.get("limit") or 50), 200))
        server_filter = (args.get("server_name") or "").strip()

        q = db.query(SystemEvent, Server.name).outerjoin(
            Server, Server.id == SystemEvent.server_id
        ).filter(SystemEvent.created_at >= since)
        if severities:
            q = q.filter(SystemEvent.severity.in_(severities))
        if server_filter:
            q = q.filter(Server.name.ilike(f"%{server_filter}%"))
        q = q.order_by(SystemEvent.created_at.desc()).limit(limit)
        rows = q.all()

        total_q = db.query(SystemEvent).filter(SystemEvent.created_at >= since)
        if severities:
            total_q = total_q.filter(SystemEvent.severity.in_(severities))
        total_count = total_q.count()

        events = [
            {
                "server": server_name or (f"server_id={ev.server_id}" if ev.server_id else None),
                "severity": ev.severity,
                "event_type": ev.event_type,
                "source": ev.source,
                "title": ev.title,
                "description": (ev.description or "")[:300],
                "occurrence_count": ev.occurrence_count,
                "created_at": ev.created_at.isoformat() if ev.created_at else None,
                "last_seen": ev.last_seen.isoformat() if ev.last_seen else None,
                "resolved": ev.resolved,
                "acknowledged": ev.is_acknowledged,
            }
            for ev, server_name in rows
        ]
        return {
            "ok": True,
            "source": "db",
            "hours": hours,
            "severity_filter": severities or "all",
            "count": len(events),
            "total_count_in_window": total_count,
            "events": events,
            "hint": (
                "Bu liste system_events tablosundandır (gerçek, SoT). count=0 ise "
                "gerçekten belirtilen pencerede/severity'de olay yok demektir — "
                "uydurma olay/tarih ÜRETME."
            ),
        }
    except Exception as e:
        logger.error("[Tool] db_list_critical_events hata: %s", e, exc_info=True)
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


def _vcenter_perf_query_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """READ-ONLY dinamik QueryPerf — katalogdan yalnız istenen metrikler; mutate yok."""
    try:
        from app.services.virt_perf_query import run_virt_perf_query
        from app.services.vmware.perf_catalog import is_mutate_method

        # Savunma: args içine sızmış mutate method adı varsa reddet
        for k in ("method", "soap_method", "operation"):
            if is_mutate_method(str(args.get(k) or "")):
                return {"ok": False, "error": f"Mutate method yasak: {args.get(k)}"}

        metrics = args.get("metrics")
        if isinstance(metrics, str):
            metrics = [m.strip() for m in metrics.replace(";", ",").split(",") if m.strip()]
        return run_virt_perf_query(
            db,
            entity=str(args.get("entity") or "host"),
            target=args.get("target") or args.get("host") or args.get("vm"),
            metrics=metrics if isinstance(metrics, list) else None,
            hypervisor=args.get("hypervisor"),
            top_n=int(args.get("top_n") or 10),
            max_sample=int(args.get("max_sample") or 1),
            interval_id=int(args.get("interval_id") or 20),
            lookback_hours=(
                float(args["lookback_hours"])
                if args.get("lookback_hours") not in (None, "", 0)
                else None
            ),
            list_catalog=bool(args.get("list_catalog")),
        )
    except Exception as e:
        logger.error("[Tool] vcenter_perf_query hata: %s", e, exc_info=True)
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
        node_err = client.last_error
        projects = client.list_projects()
        proj_err = client.last_error
        pods = client.list_pods()
        pod_err = client.last_error
        live_errors = [e for e in (node_err, proj_err, pod_err) if e]

        # KRİTİK: canlı API 401/403/bağlantı hatası verdiğinde list_* metodları
        # sessizce [] döner — bunu "gerçekten 0 kayıt var" ile ASLA karıştırma.
        # Böyle bir durumda açık hata + (varsa) DB'den son senkron veriyle
        # fallback döndür ki model "0 node/pod bulunamadı" diye yanlış cevap
        # üretmesin (bkz. gözlemlenen regresyon: 401 → "cluster boş" hallüsinasyonu).
        if live_errors and not nodes and not projects and not pods:
            fallback: Dict[str, Any] = {}
            try:
                from app.services.ocp_db_query import list_ocp_nodes_db, list_ocp_projects_db
                fallback["db_nodes"] = list_ocp_nodes_db(db, cluster=cluster.name)
                fallback["db_projects"] = list_ocp_projects_db(db, cluster=cluster.name)
            except Exception:
                pass
            return {
                "ok": False,
                "live_connection_failed": True,
                "error": f"Canlı OpenShift API hatası: {live_errors[0]}",
                "hint": (
                    "BU BİR '0 NODE/POD' DURUMU DEĞİL — canlı API'ye erişilemedi "
                    "(token süresi dolmuş/bağlantı hatası olabilir). Cluster'ın boş "
                    "olduğunu SÖYLEME. Aşağıdaki db_nodes/db_projects varsa (son "
                    "senkron), onu 'as_of' notuyla birlikte kullan; yoksa kullanıcıya "
                    "canlı bağlantının başarısız olduğunu açıkça belirt."
                ),
                **fallback,
            }

        by_status = dict(Counter((p.get("status") or "Unknown") for p in pods))
        problems = [
            p for p in pods
            if (p.get("status") or "").lower() not in ("running", "succeeded")
            or int(p.get("restart_count") or 0) >= 5
            or p.get("reason")
        ]
        # Canlı sürüm — DB'deki cluster.version periyodik sync ile stale kalabilir;
        # `version` sorulduğunda güncel değeri gösterebilmek için canlı API'den de dene.
        live_version = client.get_version() or cluster.version

        summary = {
            "cluster": cluster.name,
            "api_url": cluster.api_url,
            "version": live_version,
            "version_db_cached": cluster.version,
            "node_count": len(nodes),
            "nodes": [{"name": n.get("name"), "role": n.get("role"), "status": n.get("status")} for n in nodes[:50]],
            "project_count": len(projects),
            "pod_count": len(pods),
            "pods_by_status": by_status,
            "problem_pod_count": len(problems),
            "problem_pods_sample": problems[:30],
            "question_hint": question or None,
            "hint": (
                "Detaylı pod listesi için list_ocp_pods; Cluster Operator/sağlık/ClusterVersion "
                "için ocp_cluster_status; storage (PV/PVC/StorageClass) için ocp_storage_overview; "
                "network (NAD/CNI) için ocp_network_overview; namespace ResourceQuota/LimitRange "
                "için ocp_resource_quota; VM tam detayı için kubevirt_vm_detail; snapshot/restore "
                "için kubevirt_snapshots; DataVolume için list_datavolumes; canlı migrasyon için "
                "list_ocp_migrations aracını çağır."
            ),
        }
        if live_errors:
            summary["live_connection_warning"] = (
                f"UYARI: bazı canlı sorgularda hata oluştu ({'; '.join(live_errors)}). "
                "Yukarıdaki sayılar kısmi/eksik olabilir — 0 ise gerçek boşluk mu "
                "yoksa erişim hatası mı olduğunu belirt."
            )
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
        if client.last_error and not pods:
            # 401/403/bağlantı hatası → "0 pod" ile karıştırma (bkz. openshift_ask).
            return {
                "ok": False,
                "live_connection_failed": True,
                "error": f"Canlı OpenShift API hatası: {client.last_error}",
                "hint": (
                    "BU '0 POD' DEMEK DEĞİL — canlı bağlantı başarısız oldu. "
                    "Namespace'in gerçekten boş olduğunu SÖYLEME; kullanıcıya "
                    "canlı API erişim hatası olduğunu açıkça belirt."
                ),
            }
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


def _db_list_ocp_nodes_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.ocp_db_query import list_ocp_nodes_db
        return list_ocp_nodes_db(
            db,
            cluster=args.get("cluster"),
            role=args.get("role"),
            status=args.get("status"),
            limit=int(args.get("limit") or 200),
        )
    except Exception as e:
        logger.error("[Tool] db_list_ocp_nodes hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _db_list_ocp_projects_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.ocp_db_query import list_ocp_projects_db
        return list_ocp_projects_db(
            db,
            cluster=args.get("cluster"),
            name_filter=args.get("name_filter"),
            limit=int(args.get("limit") or 200),
        )
    except Exception as e:
        logger.error("[Tool] db_list_ocp_projects hata: %s", e, exc_info=True)
        return {"ok": False, "error": str(e)}


def _list_ocp_events_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    cluster = resolve_openshift_cluster(db, args)
    if not cluster:
        return {"ok": False, "error": "Tanımlı OpenShift cluster bulunamadı"}
    hours = max(1, min(int(args.get("hours") or 48), 168))
    try:
        client = _build_ocp_client(cluster)
        events = client.list_events(hours=hours)
        if client.last_error and not events:
            return {
                "ok": False,
                "live_connection_failed": True,
                "error": f"Canlı OpenShift API hatası: {client.last_error}",
                "hint": "BU '0 OLAY' DEMEK DEĞİL — canlı bağlantı başarısız oldu, olay olmadığını SÖYLEME.",
            }
        # KubeVirt VM/VMI/DataVolume/Node ile ilişkili olayları da ekle — ayrı istemci
        # (aynı bearer token/cluster; VM/VMI/DataVolume kind filtresiyle).
        try:
            from app.services.openshift.cluster_ops import kubevirt_client_from_cluster
            kv_client = kubevirt_client_from_cluster(cluster)
            kv_events = kv_client.list_events(hours=hours)
            existing_keys = {(e.get("source_object"), e.get("reason"), e.get("timestamp")) for e in events}
            for ev in kv_events:
                key = (ev.get("source_object"), ev.get("reason"), ev.get("timestamp"))
                if key not in existing_keys:
                    events.append(ev)
                    existing_keys.add(key)
        except Exception as exc:
            logger.debug("KubeVirt events merge skipped: %s", exc)
        return {"ok": True, "cluster": cluster.name, "hours": hours,
                "count": len(events), "events": events[:100]}
    except Exception as e:
        logger.error(f"[Tool] list_ocp_events hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _ocp_cluster_status_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Cluster adı/sürüm/API server + Cluster Operator durumu + ClusterVersion + MachineConfigPool + genel sağlık."""
    cluster = resolve_openshift_cluster(db, args)
    if not cluster:
        return {"ok": False, "error": "Tanımlı OpenShift cluster bulunamadı"}
    try:
        from app.services.openshift.cluster_ops import cluster_overview, cluster_health
        client = _build_ocp_client(cluster)
        overview = cluster_overview(client, cluster)
        health = cluster_health(client)
        return {
            "ok": True,
            "cluster": cluster.name,
            "api_url": cluster.api_url,
            "version": overview.get("version") or cluster.version,
            "overall_health": health.get("overall"),
            "cluster_version_update": {
                "updating": health.get("updating"),
                "message": health.get("update_message"),
            },
            "operators": {
                "total": health.get("operators", {}).get("total"),
                "degraded": health.get("operators", {}).get("degraded"),
                "progressing": health.get("operators", {}).get("progressing"),
                "unavailable": health.get("operators", {}).get("unavailable"),
            },
            "operator_install_status": overview.get("operators"),
            "nodes_not_ready": health.get("nodes_not_ready"),
            "nodes_pressured": health.get("nodes_pressured"),
            "machine_config_pools": health.get("machine_config_pools"),
            "capacity": overview.get("capacity"),
            "namespaces": overview.get("namespaces"),
            "kubevirt_vms": overview.get("kubevirt_vms"),
            "migration_ready": overview.get("migration_ready"),
            "migration_missing": overview.get("migration_missing"),
        }
    except Exception as e:
        logger.error(f"[Tool] ocp_cluster_status hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _ocp_storage_overview_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """StorageClass / PersistentVolume / PersistentVolumeClaim canlı envanteri."""
    cluster = resolve_openshift_cluster(db, args)
    if not cluster:
        return {"ok": False, "error": "Tanımlı OpenShift cluster bulunamadı"}
    try:
        from app.services.openshift.cluster_ops import storage_overview
        client = _build_ocp_client(cluster)
        result = storage_overview(client)
        namespace = (args.get("namespace") or "").strip()
        if namespace:
            result["persistent_volume_claims"] = [
                p for p in result.get("persistent_volume_claims", [])
                if p.get("namespace") == namespace
            ]
        return {"ok": True, "cluster": cluster.name, **result}
    except Exception as e:
        logger.error(f"[Tool] ocp_storage_overview hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _ocp_network_overview_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """NetworkAttachmentDefinition (Multus CNI/bridge/SR-IOV/MACVLAN) envanteri."""
    cluster = resolve_openshift_cluster(db, args)
    if not cluster:
        return {"ok": False, "error": "Tanımlı OpenShift cluster bulunamadı"}
    try:
        from app.services.openshift.cluster_ops import network_overview
        client = _build_ocp_client(cluster)
        result = network_overview(client)
        return {"ok": True, "cluster": cluster.name, **result}
    except Exception as e:
        logger.error(f"[Tool] ocp_network_overview hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _list_datavolumes_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """CDI DataVolume listesi — VM disk import/clone durumu, progress, kaynak (http/registry/pvc)."""
    cluster = resolve_openshift_cluster(db, args)
    if not cluster:
        return {"ok": False, "error": "Tanımlı OpenShift cluster bulunamadı"}
    namespace = (args.get("namespace") or "").strip() or None
    try:
        from app.services.openshift.cluster_ops import list_datavolumes
        client = _build_ocp_client(cluster)
        result = list_datavolumes(client, namespace=namespace)
        return {"ok": True, "cluster": cluster.name, "namespace": namespace, **result}
    except Exception as e:
        logger.error(f"[Tool] list_datavolumes hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _list_ocp_migrations_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """KubeVirt Live Migration (VirtualMachineInstanceMigration) durumu — kaynak/hedef node, transfer hızı, ilerleme."""
    cluster = resolve_openshift_cluster(db, args)
    if not cluster:
        return {"ok": False, "error": "Tanımlı OpenShift cluster bulunamadı"}
    namespace = (args.get("namespace") or "").strip() or None
    try:
        from app.services.openshift.cluster_ops import list_migrations
        client = _build_ocp_client(cluster)
        result = list_migrations(client, namespace=namespace)
        return {"ok": True, "cluster": cluster.name, "namespace": namespace, **result}
    except Exception as e:
        logger.error(f"[Tool] list_ocp_migrations hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _ocp_resource_quota_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """Namespace ResourceQuota (CPU/bellek limit+used, obje sayısı) + LimitRange."""
    cluster = resolve_openshift_cluster(db, args)
    if not cluster:
        return {"ok": False, "error": "Tanımlı OpenShift cluster bulunamadı"}
    namespace = (args.get("namespace") or "").strip()
    if not namespace:
        return {"ok": False, "error": "namespace gerekli (hangi proje için quota sorgulanacak?)"}
    try:
        from app.services.openshift.cluster_ops import resource_quota_overview
        client = _build_ocp_client(cluster)
        result = resource_quota_overview(client, namespace)
        return {"ok": True, "cluster": cluster.name, **result}
    except Exception as e:
        logger.error(f"[Tool] ocp_resource_quota hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _resolve_kubevirt_client(db: Session, args: Dict[str, Any]):
    """KubeVirt istemcisi — ÖNCE ayrı tanımlı 'openshift_virt' Hypervisor kaydını dener
    (list_kubevirt_vms ile aynı yol); yoksa OpenShiftCluster bağlantı bilgisiyle (aynı
    cluster, aynı token) bir KubeVirtClient kurar. Böylece ayrı bir hypervisor kaydı
    OLMASA BİLE (yalnızca OpenShiftCluster tanımlıysa) VM detay/snapshot sorguları çalışır.

    Returns: (client, label) veya (None, error_message)
    """
    hv = resolve_hypervisor(db, args, type_filter=HypervisorType.OPENSHIFT_VIRT)
    if hv:
        try:
            return _build_kubevirt_client(hv), hv.name
        except Exception as e:
            return None, f"KubeVirt hypervisor bağlantı hatası: {e}"
    cluster = resolve_openshift_cluster(db, args)
    if cluster:
        try:
            from app.services.openshift.cluster_ops import kubevirt_client_from_cluster
            return kubevirt_client_from_cluster(cluster), cluster.name
        except Exception as e:
            return None, f"OpenShift cluster üzerinden KubeVirt bağlantı hatası: {e}"
    return None, "Tanımlı OpenShift Virtualization (KubeVirt) hypervisor veya OpenShift cluster bulunamadı"


def _kubevirt_vm_detail_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """KubeVirt VM detayı — fields/question ile YALNIZ istenen alanlar (dump yok).

    Canlı API'den tam spec çekilir ama LLM'e yalnızca kullanıcının sorduğu
    (veya belirsizse kısa özet) alanlar projekte edilir.
    """
    from app.services.ocp_field_projection import (
        detect_requested_kubevirt_fields,
        normalize_fields,
        project_kubevirt_vm,
    )

    client, label = _resolve_kubevirt_client(db, args)
    if not client:
        return {"ok": False, "error": label}
    vm_name = (args.get("vm_name") or args.get("name") or "").strip()
    namespace = (args.get("namespace") or "").strip()
    if not vm_name:
        return {"ok": False, "error": "vm_name gerekli"}
    try:
        if not namespace:
            for v in client.list_vms():
                if (v.get("name") or "").strip().lower() == vm_name.lower():
                    namespace = v.get("namespace") or ""
                    break
        if not namespace:
            return {"ok": False, "error": f"VM '{vm_name}' bulunamadı veya namespace belirlenemedi; namespace parametresini verin"}
        detail = client.get_vm_full_details(f"{namespace}/{vm_name}", name=vm_name)
        if not detail:
            return {"ok": False, "error": f"VM bulunamadı: {namespace}/{vm_name}"}

        raw_fields = args.get("fields")
        if isinstance(raw_fields, str):
            raw_fields = [f.strip() for f in raw_fields.split(",") if f.strip()]
        question = (args.get("question") or "").strip()
        if isinstance(raw_fields, list) and raw_fields:
            fields = normalize_fields(raw_fields)
        elif question:
            fields = detect_requested_kubevirt_fields(question)
        else:
            # ctx'teki orijinal kullanıcı mesajı (agentic loop geçiriyorsa)
            fields = detect_requested_kubevirt_fields(
                (ctx or {}).get("user_message") or (ctx or {}).get("message") or ""
            )

        projected = project_kubevirt_vm(detail, fields)
        return {
            "ok": True,
            "source": label,
            "vm": projected,
            "hint": (
                "Yalnız istenen/özet alanlar döndü — tüm özellikleri kullanıcıya sayma. "
                "Eksik alan için fields=[...] ile tekrar çağır."
            ),
        }
    except Exception as e:
        logger.error(f"[Tool] kubevirt_vm_detail hata: {e}", exc_info=True)
        return {"ok": False, "error": str(e)}


def _kubevirt_snapshots_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    """KubeVirt VM Snapshot + Restore listesi (snapshot.kubevirt.io) — ready/phase/failure_reason/volume snapshots."""
    client, label = _resolve_kubevirt_client(db, args)
    if not client:
        return {"ok": False, "error": label}
    vm_name = (args.get("vm_name") or args.get("name") or "").strip()
    namespace = (args.get("namespace") or "").strip()
    if not vm_name:
        return {"ok": False, "error": "vm_name gerekli"}
    try:
        from app.services.openshift.kubevirt_ops import list_snapshots, list_restores
        if not namespace:
            for v in client.list_vms():
                if (v.get("name") or "").strip().lower() == vm_name.lower():
                    namespace = v.get("namespace") or ""
                    break
        if not namespace:
            return {"ok": False, "error": f"VM '{vm_name}' bulunamadı veya namespace belirlenemedi; namespace parametresini verin"}
        snaps = list_snapshots(client, namespace, vm_name)
        restores = list_restores(client, namespace, vm_name)
        return {
            "ok": True, "source": label, "namespace": namespace, "vm": vm_name,
            "snapshot_count": len(snaps), "snapshots": snaps,
            "restore_count": len(restores), "restores": restores,
        }
    except Exception as e:
        logger.error(f"[Tool] kubevirt_snapshots hata: {e}", exc_info=True)
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
    "cross_entity_match": Tool(
        name="cross_entity_match",
        description=(
            "Modüller arası READ-ONLY envanter JOIN: hostname / vm_name / IP ile "
            "Linux, Windows, vCenter VM/ESXi host kayıtlarını tek satırda eşleştirir. "
            "Unified'de linux+virt, ocp+virt vb. çapraz sorularda önce anahtar doğrula; "
            "sonra ilgili canlı tool'larla alanları doldur. Uydurma eşleştirme yapma."
        ),
        parameters={
            "type": "object",
            "properties": {
                "names": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Eşleştirilecek ad/IP listesi",
                },
                "modules": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "linux, windows, virt, openshift (opsiyonel filtre)",
                },
                "limit": {"type": "integer"},
            },
            "required": ["names"],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_cross_entity_match_handler,
        direct_label="Modüller arası envanter join",
    ),
    "db_list_vms": Tool(
        name="db_list_vms",
        description=(
            "VMware/hypervisor VM envanterini DATABASE'den listeler (READ-ONLY, canlı API yok). "
            "Kaç VM, poweredOn/Off, host/cluster/datastore, vCPU/RAM, disk_gb, disk_count, disks[]. "
            "VM disk adet/boyut sorularında TEK çağrı yeter — her VM için db_vm_detail döngüsü yapma. "
            "disk_gb doluysa 'toplanmadı' deme. fields ile kolon seç; disk_gb/disk_count her zaman korunur. "
            "Kullanıcı belirli bir datastore/host/cluster/VM adı verdiyse datastore/host_name/cluster/"
            "name_filter ile daralt — filtresiz çağırma (gereksiz tüm filo dökümü = bilgi kirliliği). "
            "Önce bunu kullan; stale=true veya eksik alan varsa vcenter_ask / canlı tool'a düş."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hypervisor": {"type": "string", "description": "vCenter kaydı adı/label filtresi (ESXi değil; örn. Office)"},
                "power_state": {"type": "string", "description": "örn. poweredOn / poweredOff"},
                "host_name": {"type": "string", "description": "ESXi host adı/IP (vm_host_name; vCenter adı değil)"},
                "cluster": {"type": "string", "description": "Cluster adı"},
                "datastore": {
                    "type": "string",
                    "description": (
                        "Yalnızca bu datastore'daki VM'leri döndür (substring, case-insensitive). "
                        "'X datastore'unda hangi VM'ler var' gibi sorularda MUTLAKA kullan — "
                        "filtresiz çağrı TÜM VM'leri döner (istenmeyen bilgi kirliliği)."
                    ),
                },
                "name_filter": {
                    "type": "string",
                    "description": (
                        "VM adında arama (substring). Kullanıcı belirli BİR VM adını verdiyse "
                        "bunu kullan (veya doğrudan db_vm_detail çağır) — tüm filoyu döndürme."
                    ),
                },
                "limit": {
                    "type": "integer",
                    "description": (
                        "Max satır. Varsayılan: Gelişmiş Ayarlar virt_chat_vm_list_limit "
                        "(onaylı tam taramada hard_max)."
                    ),
                },
                "include_disks": {
                    "type": "boolean",
                    "description": "true (varsayılan): her VM için disks[{label,capacity_gb,...}] dahil",
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "İstenen alanlar. Örn: name, ip, power_state, host (ESXi), "
                        "esxi_host, cluster, datastore, vcpu, memory_mb, disk_gb, "
                        "disk_count, disks, guest_os, hypervisor/vcenter (vCenter label). "
                        "disk_gb/disk_count her zaman eklenir. host ≠ hypervisor."
                    ),
                },
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_db_list_vms_handler,
        direct_label="DB VM listesi",
    ),
    "db_vm_detail": Tool(
        name="db_vm_detail",
        description=(
            "Tek VM detayını DATABASE'den getirir (disk listesi, NIC/portgroup, "
            "ESXi host, vCenter label, guest OS, QuickStats). "
            "host/esxi_host=ESXi; hypervisor/vcenter=vCenter kaydı — karıştırma. "
            "Canlı API yok — önce bunu dene."
        ),
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "VM adı / guest hostname"},
                "server_id": {"type": "integer", "description": "servers.id"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_db_vm_detail_handler,
        direct_label="DB VM detay",
    ),
    "db_list_datastores": Tool(
        name="db_list_datastores",
        description=(
            "Datastore kapasite/free/accessible bilgisini DATABASE'den (virt_datastores) getirir "
            "(READ-ONLY). 'Yer var mı', 'datastore doluluk' sorularında ÖNCE bunu kullan. "
            "fields=[...] ile kolon seç. stale=true veya boşsa canlı vcenter_ask / sync."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hypervisor": {"type": "string", "description": "vCenter adı (opsiyonel)"},
                "name_filter": {
                    "type": "string",
                    "description": (
                        "Belirli bir datastore adında arama (substring). Kullanıcı tek bir "
                        "datastore adı verdiyse bunu kullan — filtresiz çağrı TÜM datastore'ları döner."
                    ),
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "İstenen alanlar. Örn: name, usage_pct, free_gb, capacity_gb, "
                        "accessible, hypervisor"
                    ),
                },
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_db_list_datastores_handler,
        direct_label="DB datastore listesi",
    ),
    "db_list_esx_hosts": Tool(
        name="db_list_esx_hosts",
        description=(
            "ESXi host bilgisini DATABASE'den listeler. "
            "metrics (CPU/RAM/state) ile inventory (IP, version, vendor) JOIN edilir — "
            "tek satırda birleşik sonuç. "
            "Kullanıcının istediği alanları fields ile geç (örn. name,ip,version). "
            "fields yoksa kısa özet: name,ip,version,connection_state,hypervisor. "
            "Canlı API yok; stale/eksik alan için sync veya vcenter_ask."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hypervisor": {"type": "string", "description": "vCenter adı (opsiyonel)"},
                "name_filter": {
                    "type": "string",
                    "description": (
                        "Belirli bir ESXi host adında arama (substring). Kullanıcı tek bir "
                        "host adı verdiyse bunu kullan — filtresiz çağrı TÜM host'ları döner."
                    ),
                },
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "İstenen alanlar (dinamik). Örn: name, ip, version, vendor, model, "
                        "cpu_pct, mem_pct, connection_state, vms_total, hypervisor, "
                        "cluster (host'un cluster'ı), overall_status (green/yellow/red), "
                        "sensor_bad_count (donanım sensör alarmı sayısı), bad_sensors "
                        "(arızalı sensör detayı), config_issues"
                    ),
                },
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_db_list_esx_hosts_handler,
        direct_label="DB ESXi host (join+fields)",
    ),
    "db_list_clusters": Tool(
        name="db_list_clusters",
        description=(
            "vCenter CLUSTER durumu DATABASE'den (READ-ONLY): HA açık mı, admission control "
            "politikası, failover slot durumu (total/used/unreserved), DRS otomasyon seviyesi "
            "ve migration eşiği, effective CPU/RAM kapasitesi, cluster host'larının CPU/RAM "
            "ortalaması. "
            "'HA yapılandırması riskli mi', 'bir host arızalanırsa VM'ler ayağa kalkar mı', "
            "'DRS dengeli mi', 'cluster kapasitesi ne durumda', 'en riskli cluster hangisi' "
            "sorularında BUNU ÇAĞIR. Her satırda `ha_verdict` alanı hazır deterministik "
            "değerlendirme içerir — kendi başına failover hesabı YAPMA, bu alanı kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hypervisor": {"type": "string", "description": "vCenter adı (opsiyonel)"},
                "name_filter": {"type": "string", "description": "Cluster adı filtresi (substring)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_db_list_clusters_handler,
        direct_label="DB cluster HA/DRS durumu",
    ),
    "db_metric_trend": Tool(
        name="db_metric_trend",
        description=(
            "TREND ve KAPASİTE TÜKENME TAHMİNİ (READ-ONLY, DB zaman serisi). Host / VM / "
            "datastore için seçilen metriğin geçmiş penceredeki ilk-son değeri, ortalama, "
            "p95, günlük eğimi (slope_per_day) ve eşiğe kalan gün (days_to_threshold) "
            "deterministik hesaplanır. "
            "'son 7 günde kötüleşen VM'ler', 'datastore ne zaman dolar', '30 günlük trend', "
            "'kapasite problemi yaşayacak host/cluster', 'uzun süredir düşük kullanan VM'ler "
            "(right-sizing)', 'performansı bozulan' sorularında BUNU ÇAĞIR — trend/tahmin "
            "aritmetiğini KENDİN YAPMA. insufficient_history=true olan satırlarda trend "
            "yorumu yapma, yalnız mevcut değeri bildir."
        ),
        parameters={
            "type": "object",
            "properties": {
                "entity_type": {
                    "type": "string",
                    "enum": ["host", "vm", "datastore"],
                    "description": "Varlık tipi (varsayılan host)",
                },
                "metric": {
                    "type": "string",
                    "description": (
                        "host: cpu_pct|mem_pct|ds_pct|vms_running · "
                        "vm: cpu_pct|mem_pct|cpu_ready_pct|disk_latency_ms|balloon_mb|"
                        "swapped_mb|net_dropped_rx|guest_disk_pct|snapshot_count · "
                        "datastore: usage_pct|free_gb|used_gb|uncommitted_gb"
                    ),
                },
                "days": {"type": "number", "description": "Geriye dönük pencere (gün, varsayılan 7)"},
                "top_n": {"type": "integer", "description": "Kaç satır (varsayılan 10)"},
                "order": {
                    "type": "string",
                    "enum": ["worsening", "improving", "highest", "lowest"],
                    "description": "Sıralama; worsening = en hızlı artan eğim",
                },
                "name_filter": {"type": "string", "description": "Ad filtresi (substring)"},
                "hypervisor": {"type": "string", "description": "vCenter adı (opsiyonel)"},
                "threshold": {
                    "type": "number",
                    "description": "Tükenme eşiği (varsayılan doluluk %90 / free_gb 0)",
                },
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_db_metric_trend_handler,
        direct_label="Trend / kapasite tahmini",
    ),
    "virt_health_overview": Tool(
        name="virt_health_overview",
        description=(
            "SANALLAŞTIRMA ORTAMININ GENEL SAĞLIK DEĞERLENDİRMESİ (READ-ONLY, DB). "
            "Sağlık skoru + seviyesi, kritik/uyarı host kartları (hangi host, hangi metrik, "
            "hangi eşik), önerilen aksiyonlar ve son 24 saatin kritik event/alarm başlıkları. "
            "'vCenter sağlıklı mı', 'ortamda problem var mı', 'sağlık durumu nedir', "
            "'yönetici olarak bilmem gereken bir şey var mı', 'bir sorun görüyor musun', "
            "'genel durum nasıl', 'risk seviyesi nedir' gibi GENEL/BELİRSİZ sağlık "
            "sorularında İLK BUNU ÇAĞIR. Detay gerekirse ardından db_list_esx_hosts "
            "(sensör), db_list_clusters (HA), db_virt_alarms (alarm) ile derinleş."
        ),
        parameters={
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max host/olay satırı (varsayılan 20)"},
                "include_logs": {
                    "type": "boolean",
                    "description": "Son 24 saatin kritik event başlıklarını ekle (varsayılan true)",
                },
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_virt_health_overview_handler,
        direct_label="Sanallaştırma sağlık özeti",
    ),
    "vcenter_property_read": Tool(
        name="vcenter_property_read",
        description=(
            "JENERİK vSphere property okuyucu (canlı SOAP, READ-ONLY, mutate YOK). "
            "Diğer araçların kapsamadığı bir vCenter özelliği sorulduğunda bunu kullan: "
            "object_type (HostSystem | ClusterComputeResource | Datastore | VirtualMachine | "
            "Datacenter | DistributedVirtualSwitch …) + path_set (vSphere property path listesi). "
            "Örnekler: multipath/LUN path durumu → HostSystem + config.storageDevice.multipathInfo; "
            "NTP → HostSystem + config.dateTimeInfo.ntpConfig.server; "
            "datastore mount durumu → Datastore + host; "
            "thin provisioning taahhüdü → Datastore + summary.uncommitted; "
            "VM snapshot ağacı → VirtualMachine + snapshot.rootSnapshotList. "
            "Hangi path'lerin olduğunu bilmiyorsan önce list_catalog=true ile katalogu al. "
            "ÖNCE özel araçları dene (db_* / vcenter_perf_query); bu araç son çare esnek yoldur."
        ),
        parameters={
            "type": "object",
            "properties": {
                "object_type": {
                    "type": "string",
                    "description": "vSphere managed object tipi (ör. HostSystem)",
                },
                "path_set": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Okunacak property path listesi (name otomatik eklenir)",
                },
                "name_filter": {"type": "string", "description": "Nesne adına göre süzme (substring)"},
                "hypervisor": {"type": "string", "description": "vCenter adı (opsiyonel)"},
                "limit": {"type": "integer", "description": "Max nesne (varsayılan 50)"},
                "list_catalog": {
                    "type": "boolean",
                    "description": "true → tip/path önerileri kataloğunu döner, sorgu yapmaz",
                },
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_vcenter_property_read_handler,
        direct_label="vCenter jenerik property okuma",
    ),
    "infra_report": Tool(
        name="infra_report",
        description=(
            "HAZIR RAPOR MOTORU (READ-ONLY, DB). Trend/forecast/risk aritmetiğini motor "
            "deterministik hesaplar; sen yalnızca yorumlarsın — sayıları KENDİN TÜRETME. "
            "report_type: capacity (kapasite + datastore doluluk), forecast (30 gün büyüme "
            "tahmini / kapasite tükenme), risk, anomaly, performance_bottleneck, vm_health, "
            "consolidation (right-sizing), lifecycle, resource_usage, riskiest_assets, "
            "operations, sla, business_impact, finance, security_compliance, executive_summary. "
            "'Önümüzdeki 30 günde kapasite problemi olacak mı', 'yönetici raporu hazırla', "
            "'right-sizing önerisi', 'en riskli varlıklar' gibi sorularda BUNU ÇAĞIR."
        ),
        parameters={
            "type": "object",
            "properties": {
                "report_type": {"type": "string", "description": "Rapor tipi (yukarıdaki listeden)"},
                "markdown": {
                    "type": "boolean",
                    "description": "Hazır Markdown tablo üret (varsayılan true)",
                },
                "include_raw": {
                    "type": "boolean",
                    "description": "Ham JSON veriyi de ekle (bağlamı büyütür, varsayılan false)",
                },
            },
            "required": ["report_type"],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_infra_report_handler,
        direct_label="Altyapı raporu (motor)",
    ),
    "knowledge_search": Tool(
        name="knowledge_search",
        description=(
            "BİLGİ BANKASI / RUNBOOK / GEÇMİŞ OLAY semantik arama (pgvector, READ-ONLY). "
            "Kurum içi doküman, prosedür, daha önce çözülmüş benzer arıza kaydı veya "
            "yüklenmiş PDF/runbook içeriği gerektiğinde çağır: 'bu hatayı daha önce nasıl "
            "çözdük', 'prosedür ne diyor', 'runbook var mı', 'benzer incident'. "
            "Canlı metrik/envanter için kullanma — onlar db_* ve vcenter_* araçlarında."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Arama sorgusu (doğal dil)"},
                "collections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "runbook | incidents | metrics | knowledge (boş = hepsi)",
                },
            },
            "required": ["query"],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_knowledge_search_handler,
        direct_label="Bilgi bankası arama (RAG)",
    ),
    "prometheus_query": Tool(
        name="prometheus_query",
        description=(
            "GUEST OS metrik/envanter doğal dil sorgusu (NLQ → PromQL + DB, READ-ONLY). "
            "node_exporter / windows_exporter verisi üzerinden: 'CPU'su %80 üstünde olan "
            "sunucular', 'disk doluluğu %90'ı geçen makineler', 'RAM kullanımı en yüksek 10 "
            "sunucu', 'servisi düşmüş olanlar'. "
            "DİKKAT: Bu araç işletim sistemi içi metrikleri sorgular. ESXi/hipervizör "
            "seviyesindeki CPU/RAM/datastore için db_list_esx_hosts veya vcenter_perf_query kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "question": {"type": "string", "description": "Doğal dil sorgu"},
                "live_check": {
                    "type": "boolean",
                    "description": "Sonuçları canlı SSH/agent ile doğrula (yavaş)",
                },
            },
            "required": ["question"],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_prometheus_query_handler,
        direct_label="Prometheus NLQ sorgusu",
    ),
    "db_virt_alarms": Tool(
        name="db_virt_alarms",
        description=(
            "vCenter alarmlarını DATABASE'den (system_events, sync edilmiş) listeler (READ-ONLY). "
            "Önce bunu kullan; boş/stale ise vcenter_live_alarms. "
            "Host/VM/datastore ile birlikte çapraz tablo için db_virt_cross_match tercih et."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "Kaç saat (varsayılan 48)"},
                "unresolved_only": {"type": "boolean", "description": "Sadece çözülmemiş (varsayılan true)"},
                "limit": {"type": "integer"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_db_virt_alarms_handler,
        direct_label="DB virt alarmları",
    ),
    "db_list_critical_events": Tool(
        name="db_list_critical_events",
        description=(
            "Sunucu/VM sistem olaylarını (system_events tablosu — SSH log toplayıcı, "
            "disk/servis hataları, anomali tespiti) DATABASE'den listeler (READ-ONLY). "
            "'Kritik event/alarm/olay var mı', 'son N saatte hata var mı' tarzı HER "
            "soruda ÖNCE bunu çağır — bu tool çağrılmadan böyle bir soruya ASLA "
            "cevap verme (uydurma olay/tarih üretmiş olursun)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hours": {"type": "integer", "description": "Kaç saat geriye bakılacak (varsayılan 24)"},
                "severity": {
                    "type": "string",
                    "description": "critical | critical,error | warning | all (varsayılan critical)",
                },
                "server_name": {"type": "string", "description": "Belirli bir sunucu/VM adı filtresi (opsiyonel)"},
                "limit": {"type": "integer", "description": "Max satır (varsayılan 50)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_db_list_critical_events_handler,
        direct_label="DB kritik sistem olayları (system_events)",
    ),
    "db_virt_cross_match": Tool(
        name="db_virt_cross_match",
        description=(
            "READ-ONLY çapraz eşleştirme: ESXi host ⋈ VM ⋈ datastore ⋈ alarm SoT'larını "
            "ortak anahtarla tek satırda birleştirir. "
            "Örn. 'hangi host'ta alarm var ve disk dolu', 'datastore X'teki VM'ler + host IP'. "
            "join_on=host|datastore|entity. fields ile çıktı kolonları seç. "
            "Write/power/destroy YOK — yalnızca DB join."
        ),
        parameters={
            "type": "object",
            "properties": {
                "join_on": {
                    "type": "string",
                    "description": "Eşleştirme ekseni: host (varsayılan) | datastore | entity",
                },
                "include": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Kaynaklar: hosts, vms, datastores, alarms (varsayılan hepsi)",
                },
                "hypervisor": {"type": "string", "description": "vCenter adı filtresi"},
                "host_name": {"type": "string", "description": "Tek ESXi host filtresi"},
                "hours": {"type": "integer", "description": "Alarm penceresi (saat)"},
                "limit": {"type": "integer", "description": "Max satır (varsayılan 100)"},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Çıktı alanları. Örn: match_key, host, host_ip, vm_count, vms, "
                        "datastore, ds_usage_pct, alarm_count, alarms, hypervisor"
                    ),
                },
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_db_virt_cross_match_handler,
        direct_label="DB virt çapraz eşleştirme",
    ),
    "vcenter_ask": Tool(
        name="vcenter_ask",
        description=(
            "vCenter/hypervisor ile ilgili doğal dil sorusunu CANLI READ-ONLY veriyle yanıtlar "
            "(VM listesi, host/VM durumu, kaynak kullanımı, snapshot, event/alarm). "
            "Write/power/destroy/reconfig YAPMAZ. "
            "DB yetersiz/stale ise kullan; çapraz tablo için önce db_virt_cross_match dene."
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
    "vcenter_perf_query": Tool(
        name="vcenter_perf_query",
        description=(
            "vCenter Monitor tarzı performans (READ-ONLY QueryPerf) — anlık VEYA geçmiş. "
            "Geniş counter kataloğundan YALNIZ kullanıcının istediği metrikleri çeker "
            "(disk_rate, disk_requests, cpu, mem, net, vdisk, overview, mem_pressure, "
            "contention, latency_breakdown, ds_iops veya kanonik key). "
            "GEÇMİŞ/TREND soruları için lookback_hours ver (ör. 24, 168) — avg/min/max/p95 döner. "
            "Storage latency'nin kaynağını ayırmak için entity=host + metrics=[latency_breakdown]: "
            "device yüksek→array, queue yüksek→host HBA, kernel yüksek→VMkernel. "
            "Memory pressure için metrics=[mem_pressure] (balloon/swap), CPU contention için [contention]. "
            "Host Disk Rate/Requests Top-N (naa.*/NVMe) için entity=host, "
            "metrics=[disk_rate] veya [disk_requests], target=ESXi adı, top_n=10. "
            "VM için entity=vm + target=VM adı. Envanter ile join (IP, version…). "
            "Power/destroy/reconfig/mutate YOK. Kataloğu görmek için list_catalog=true."
        ),
        parameters={
            "type": "object",
            "properties": {
                "entity": {
                    "type": "string",
                    "description": "host (ESXi) veya vm — varsayılan host",
                },
                "target": {
                    "type": "string",
                    "description": "ESXi host adı veya VM adı",
                },
                "metrics": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "İstenen metrikler/bundle: disk_rate, disk_requests, disk, cpu, mem, "
                        "net, vdisk, overview veya disk_read_kbps, cpu_usage_pct, …"
                    ),
                },
                "hypervisor": {"type": "string", "description": "vCenter adı (opsiyonel)"},
                "top_n": {
                    "type": "integer",
                    "description": "Disk instance Top-N (varsayılan 10)",
                },
                "max_sample": {
                    "type": "integer",
                    "description": "Realtime sample sayısı (1–180, varsayılan 1)",
                },
                "interval_id": {
                    "type": "integer",
                    "description": "Perf interval saniye (realtime=20)",
                },
                "lookback_hours": {
                    "type": "number",
                    "description": (
                        "GEÇMİŞE dönük sorgu penceresi (saat). Verilirse vCenter'ın "
                        "kendi rollup'ından avg/min/max/p95 döner — 'son 24 saat', "
                        "'son 7 gün', 'trend', 'kötüleşti mi' sorularında kullan. "
                        "Boş bırakılırsa anlık (realtime) değer döner."
                    ),
                },
                "list_catalog": {
                    "type": "boolean",
                    "description": "true ise QueryPerf atmadan katalog listeler",
                },
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_vcenter_perf_query_handler,
        direct_label="vCenter dinamik perf (QueryPerf)",
    ),
    "vcenter_snapshot_summary": Tool(
        name="vcenter_snapshot_summary",
        description=(
            "vCenter SOAP canlı — snapshot'ı olan VM'lerin özeti: snapshot_count, en eski tarih VE "
            "snapshot_space_gb (summary.storage.uncommitted — VM'in TOPLAM yaklaşık snapshot alanı, GB; "
            "bazı ESXi/vCenter sürümlerinde desteklenmez, o durumda null döner ama diğer alanlar gelir). "
            "'Snapshot boyutu/büyüklüğü ne kadar?' gibi sorularda tarif VERME, bu aracı ÇAĞIR. "
            "Fleet veya host filtresi. Snapshot ağacı/isim için vcenter_list_vm_snapshots kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "host_name": {"type": "string", "description": "ESXi host filtresi (opsiyonel)"},
                "datastore": {"type": "string", "description": "Datastore filtresi (opsiyonel)"},
                "limit": {"type": "integer", "description": "Max VM satırı (varsayılan 100)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_vcenter_snapshot_summary_handler,
        direct_label="vCenter canlı snapshot özeti",
    ),
    "vcenter_list_vm_snapshots": Tool(
        name="vcenter_list_vm_snapshots",
        description=(
            "Tek VM için vCenter SOAP snapshot ağacı: isim, tarih, hiyerarşi VE her "
            "snapshot için size_gb/size_bytes (GERÇEK dosya boyutu — layout + datastore "
            "browser üzerinden hesaplanır, tahmin değil; disk zinciri düzensizse "
            "size_note ile açıklanır). 'Snapshot boyutu ne kadar?' sorularında tarif "
            "VERME, bu aracı ÇAĞIR. vm_name veya server_id zorunlu."
        ),
        parameters={
            "type": "object",
            "properties": {
                "vm_name": {"type": "string", "description": "VM adı"},
                "server_id": {"type": "integer", "description": "ainew server id"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_vcenter_list_vm_snapshots_handler,
        direct_label="vCenter VM snapshot ağacı",
    ),
    "db_list_ocp_nodes": Tool(
        name="db_list_ocp_nodes",
        description=(
            "OpenShift node envanterini DATABASE'den (periyodik sync, ~10dk) listeler "
            "(READ-ONLY). Node adı/rol(master|worker|infra)/durum/CPU-RAM kapasitesi için "
            "ÖNCE bunu dene; canlı/anlık pod detayı veya stale=true ise openshift_ask / "
            "list_ocp_pods ile canlıya geç."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "OpenShift cluster adı (opsiyonel)"},
                "role": {"type": "string", "description": "master | worker | infra (opsiyonel)"},
                "status": {"type": "string", "description": "Durum filtresi, örn. Ready/NotReady (opsiyonel)"},
                "limit": {"type": "integer", "description": "Max satır (varsayılan 200)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_db_list_ocp_nodes_handler,
        direct_label="DB OpenShift node envanteri",
    ),
    "db_list_ocp_projects": Tool(
        name="db_list_ocp_projects",
        description=(
            "OpenShift proje/namespace envanterini DATABASE'den (periyodik sync, ~10dk) "
            "listeler (READ-ONLY): pod/deployment/route sayıları. ÖNCE bunu dene; "
            "canlı pod detayı veya stale=true ise openshift_ask / list_ocp_pods kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "OpenShift cluster adı (opsiyonel)"},
                "name_filter": {"type": "string", "description": "Proje adında arama (opsiyonel)"},
                "limit": {"type": "integer", "description": "Max satır (varsayılan 200)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_db_list_ocp_projects_handler,
        direct_label="DB OpenShift proje/namespace envanteri",
    ),
    "openshift_ask": Tool(
        name="openshift_ask",
        description=(
            "OpenShift/Kubernetes cluster CANLI genel durumu (node, namespace/proje, sürüm). "
            "YALNIZCA OpenShift/OCP/pod/namespace sorularında kullan — Linux sunucu SSH/"
            "systemd durumuna bakmak için KULLANMA. Detay için list_ocp_pods/list_ocp_events. "
            "DB stale/boş ise veya canlı doğrulama gerekiyorsa kullan."
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
            "Deployment) + KubeVirt VM/VMI/DataVolume olayları birleşik. Linux journalctl/syslog "
            "DEĞİL — yalnızca OCP/K8s olay sorularında."
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
    "ocp_cluster_status": Tool(
        name="ocp_cluster_status",
        description=(
            "OpenShift Cluster CANLI durumu: cluster adı/API server URL/sürüm (ClusterVersion), "
            "Cluster Operator listesi + degraded/progressing/unavailable durumu, genel sağlık "
            "(healthy/warning/critical), MachineConfigPool durumu, node/pod kapasite özeti, "
            "namespace sayısı, KubeVirt/CDI/MTV operatör kurulum durumu. 'Cluster sağlıklı mı', "
            "'hangi operatörler bozuk', 'cluster versiyonu ne', 'API server adresi ne' sorularında kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "OpenShift cluster adı (opsiyonel)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_ocp_cluster_status_handler,
        direct_label="OpenShift cluster sağlık/operatör durumu",
    ),
    "ocp_storage_overview": Tool(
        name="ocp_storage_overview",
        description=(
            "StorageClass (provisioner, default, reclaim policy, binding mode) + "
            "PersistentVolume (kapasite, phase, claim, reclaim, access mode) + "
            "PersistentVolumeClaim (kapasite, phase, storage class, bağlı PV) CANLI envanteri. "
            "'PVC'ler ne durumda', 'kaç PV var', 'hangi storage class default' sorularında kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "OpenShift cluster adı (opsiyonel)"},
                "namespace": {"type": "string", "description": "PVC'leri belirli bir namespace'e filtrele (opsiyonel)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_ocp_storage_overview_handler,
        direct_label="OpenShift storage (PV/PVC/StorageClass) envanteri",
    ),
    "ocp_network_overview": Tool(
        name="ocp_network_overview",
        description=(
            "NetworkAttachmentDefinition (Multus CNI) envanteri — hangi ek ağlar tanımlı, "
            "hangi namespace'lerde kullanılıyor. Bridge/SR-IOV/MACVLAN gibi CNI tipi sorularında "
            "ve 'ek network/VLAN tanımlı mı' sorularında kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "OpenShift cluster adı (opsiyonel)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_ocp_network_overview_handler,
        direct_label="OpenShift network (NAD/Multus) envanteri",
    ),
    "list_datavolumes": Tool(
        name="list_datavolumes",
        description=(
            "CDI DataVolume (cdi.kubevirt.io) CANLI listesi — VM disk import/clone durumu, "
            "progress (%), boyut, kaynak (HTTP URL/Registry image/kaynak PVC), storage class. "
            "'DataVolume import durumu ne', 'disk kopyalama ne kadar ilerledi' sorularında kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "OpenShift cluster adı (opsiyonel)"},
                "namespace": {"type": "string", "description": "Belirli namespace (opsiyonel, yoksa tüm cluster)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_list_datavolumes_handler,
        direct_label="OpenShift DataVolume listesi",
    ),
    "list_ocp_migrations": Tool(
        name="list_ocp_migrations",
        description=(
            "KubeVirt Live Migration (VirtualMachineInstanceMigration) CANLI listesi — hangi VM, "
            "kaynak/hedef node, phase (Pending/Scheduling/Running/Succeeded/Failed), veri "
            "işlenen/kalan/toplam byte, transfer hızı, başlangıç/bitiş zamanı. 'Canlı migrasyon "
            "var mı', 'VM hangi node'a taşınıyor', 'migration ilerlemesi ne' sorularında kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "OpenShift cluster adı (opsiyonel)"},
                "namespace": {"type": "string", "description": "Belirli namespace (opsiyonel, yoksa tüm cluster)"},
            },
            "required": [],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_list_ocp_migrations_handler,
        direct_label="OpenShift/KubeVirt canlı migrasyon listesi",
    ),
    "ocp_resource_quota": Tool(
        name="ocp_resource_quota",
        description=(
            "Namespace ResourceQuota (CPU/bellek limit ve kullanım, obje sayısı sınırları — "
            "VM/pod adedi dahil) + LimitRange CANLI sorgusu. 'Bu projenin CPU/bellek kotası ne', "
            "'kota doldu mu' sorularında kullan. namespace ZORUNLU."
        ),
        parameters={
            "type": "object",
            "properties": {
                "cluster": {"type": "string", "description": "OpenShift cluster adı (opsiyonel)"},
                "namespace": {"type": "string", "description": "Proje/namespace adı (ZORUNLU)"},
            },
            "required": ["namespace"],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_ocp_resource_quota_handler,
        direct_label="OpenShift namespace ResourceQuota/LimitRange",
    ),
    "kubevirt_vm_detail": Tool(
        name="kubevirt_vm_detail",
        description=(
            "KubeVirt VM CANLI detayı — BİLGİ KİRLİLİĞİ YOK: fields veya question ile "
            "YALNIZ istenen alanları döner (varsayılan kısa özet: name/namespace/phase/"
            "cpu/memory/ip/node/guest_os). Tam dump istemiyorsan fields geç. "
            "Örn. fields=[run_strategy,firmware,dedicated_cpu_placement,cpu_numa] veya "
            "question='runStrategy ve firmware nedir'. list_kubevirt_vms yalnız liste özeti."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hypervisor": {"type": "string", "description": "KubeVirt hypervisor adı (opsiyonel)"},
                "vm_name": {"type": "string", "description": "VM adı (ZORUNLU)"},
                "namespace": {"type": "string", "description": "VM'in namespace'i (opsiyonel — verilmezse otomatik bulunur)"},
                "fields": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "İstenen alanlar. Örn: run_strategy, firmware, cpu_cores, memory_gb, "
                        "ip_address, disks, nics, dedicated_cpu_placement, cpu_numa, hugepages, "
                        "affinity, labels, annotations, vmi_conditions. Boşsa kısa özet."
                    ),
                },
                "question": {
                    "type": "string",
                    "description": "Kullanıcı sorusu — fields yoksa bundan alan çıkarılır",
                },
            },
            "required": ["vm_name"],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_kubevirt_vm_detail_handler,
        direct_label="KubeVirt VM detay (alan seçimli)",
    ),
    "kubevirt_snapshots": Tool(
        name="kubevirt_snapshots",
        description=(
            "KubeVirt VM Snapshot + Restore CANLI listesi: snapshot adı, ready/phase, oluşturma "
            "zamanı, kaynak, volume snapshot'lar, failure_reason; restore adı/kaynak "
            "snapshot/hedef VM/tamamlanma durumu. 'Bu VM'in snapshotları neler', 'snapshot hazır "
            "mı', 'restore işlemi tamamlandı mı' sorularında kullan."
        ),
        parameters={
            "type": "object",
            "properties": {
                "hypervisor": {"type": "string", "description": "KubeVirt hypervisor adı (opsiyonel)"},
                "vm_name": {"type": "string", "description": "VM adı (ZORUNLU)"},
                "namespace": {"type": "string", "description": "VM'in namespace'i (opsiyonel — verilmezse otomatik bulunur)"},
            },
            "required": ["vm_name"],
        },
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_kubevirt_snapshots_handler,
        direct_label="KubeVirt VM snapshot/restore listesi",
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
    # "infra" her platformda ortak olduğu için bu üç araç TÜM sohbet
    # yüzeylerinde (Linux / Windows / Sanallaştırma / OpenShift / Unified)
    # görünür — bilgi bankası, rapor motoru ve NLQ hattı platforma özel değil.
    "infra_report": frozenset({"infra"}),
    "knowledge_search": frozenset({"infra"}),
    "prometheus_query": frozenset({"infra"}),
    "cross_entity_match": frozenset({"infra", "linux", "windows", "vcenter", "openshift"}),
    "db_list_vms": frozenset({"vcenter", "infra"}),
    "db_vm_detail": frozenset({"vcenter", "infra"}),
    "db_list_datastores": frozenset({"vcenter", "infra"}),
    "db_list_esx_hosts": frozenset({"vcenter", "infra"}),
    "db_list_clusters": frozenset({"vcenter", "infra"}),
    "virt_health_overview": frozenset({"vcenter", "infra"}),
    "db_metric_trend": frozenset({"vcenter", "infra"}),
    "vcenter_property_read": frozenset({"vcenter"}),
    "db_virt_alarms": frozenset({"vcenter", "infra"}),
    "db_list_critical_events": frozenset({"infra"}),
    "db_virt_cross_match": frozenset({"vcenter", "infra"}),
    "vcenter_ask": frozenset({"vcenter"}),
    "vcenter_live_alarms": frozenset({"vcenter"}),
    "vcenter_live_tasks": frozenset({"vcenter"}),
    "vcenter_perf_query": frozenset({"vcenter"}),
    "vcenter_snapshot_summary": frozenset({"vcenter"}),
    "vcenter_list_vm_snapshots": frozenset({"vcenter"}),
    "openshift_ask": frozenset({"openshift"}),
    "list_kubevirt_vms": frozenset({"openshift", "vcenter"}),
    "list_ocp_pods": frozenset({"openshift"}),
    "list_ocp_events": frozenset({"openshift"}),
    # NOT: "infra" EKLENMEDİ (db_list_vms/db_list_esx_hosts gibi virt DB tool'larından
    # farklı olarak) — "infra" PLATFORM_TOOL_DOMAINS'te HER platformda ortak olduğu için
    # o etiket, kesişim testini (tool.domains & domains) her zaman doğru yapıp bu tool'un
    # Linux/Windows/virt sohbetlerine de sızmasına yol açardı. openshift_ask/list_ocp_pods
    # ile aynı dar izolasyonu koru: yalnızca "openshift" (+ Unified'da domains=None zaten
    # tam erişim veriyor, bu tool'lara ayrıca ihtiyaç yok).
    "db_list_ocp_nodes": frozenset({"openshift"}),
    "db_list_ocp_projects": frozenset({"openshift"}),
    "ocp_cluster_status": frozenset({"openshift"}),
    "ocp_storage_overview": frozenset({"openshift"}),
    "ocp_network_overview": frozenset({"openshift"}),
    "list_datavolumes": frozenset({"openshift"}),
    "list_ocp_migrations": frozenset({"openshift"}),
    "ocp_resource_quota": frozenset({"openshift"}),
    "kubevirt_vm_detail": frozenset({"openshift", "vcenter"}),
    "kubevirt_snapshots": frozenset({"openshift", "vcenter"}),
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


# UI / rapor tanımları platform adını farklı yazabiliyor — tek noktada çöz.
_PLATFORM_ALIASES: Dict[str, str] = {
    "virtualization": "virt", "vcenter": "virt", "vmware": "virt",
    "hypervisor": "virt", "sanallastirma": "virt", "sanallaştırma": "virt",
    "ocp": "openshift", "kubernetes": "openshift", "k8s": "openshift",
    "rhel": "linux", "all": "unified", "admin": "unified", "executive": "unified",
}


def domains_for_platform(platform: Optional[str]) -> Optional[frozenset]:
    """Sohbet platformuna göre tool domain filtresi; bilinmeyen → linux.

    Eşanlamlılar burada çözülür: "virtualization"/"vcenter" gibi bir değer
    tanınmazsa Linux'a düşüyordu ve o sohbette TÜM vCenter araçları sessizce
    kayboluyordu — model de "canlı veri mevcut değil" diyordu.
    """
    if not platform:
        return PLATFORM_TOOL_DOMAINS["linux"]
    key = platform.strip().lower()
    key = _PLATFORM_ALIASES.get(key, key)
    if key in PLATFORM_TOOL_DOMAINS:
        return PLATFORM_TOOL_DOMAINS[key]
    logger.warning(
        "domains_for_platform: bilinmeyen platform %r → linux araç setine düşüldü",
        platform,
    )
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
