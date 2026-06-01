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

    def preview(self, db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> str:
        server = resolve_server(db, args, ctx)
        sname = server.name if server else "(sunucu bulunamadı)"
        try:
            cmd = self.build_command(args)
        except Exception as e:
            cmd = f"(komut oluşturulamadı: {e})"
        return f"{sname}: {cmd}"

    def execute(self, db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
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
        allow_sudo=False,
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
        allow_sudo=False,
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
}


def get_tool(name: str) -> Optional[Tool]:
    return TOOLS.get(name)


def tool_specs() -> List[Dict[str, Any]]:
    """LLM'e gönderilecek tool şemaları (Ollama/OpenAI function-calling formatı)."""
    return [
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
