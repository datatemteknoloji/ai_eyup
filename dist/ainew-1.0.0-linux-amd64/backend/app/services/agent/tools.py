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
        return {"ok": True, "summary": build_infra_overview_text(db)}
    except Exception as e:
        return {"ok": False, "error": str(e)}


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
            "TÜM ALTYAPININ genel envanter özetini döndürür: toplam sunucu sayısı, "
            "Linux/Windows dağılımı, AI Ready sunucu sayısı, sanal makine (VM) sayısı, "
            "fiziksel host sayısı ve hypervisor listesi. 'Kaç sunucumuz/VM'imiz var', "
            "'altyapıda kaç makine var' gibi TEK BİR sunucuyla ilgili OLMAYAN, genel/toplam "
            "sayı sorularında bu aracı kullan — sunucu sunucu run_diagnostic/df ÇALIŞTIRMA, "
            "tek çağrı yeterlidir ve parametre gerektirmez."
        ),
        parameters={"type": "object", "properties": {}},
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda args: "",
        direct_handler=_infra_overview_handler,
        direct_label="Altyapı genel envanter özeti",
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
