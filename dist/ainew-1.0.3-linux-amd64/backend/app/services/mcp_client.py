"""
Linux MCP client + fallback built-in diagnostics tools.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

from app.services.ssh_manager import SSHManager


@dataclass
class McpCredential:
    username: str
    password: Optional[str]
    private_key: Optional[str]
    port: int = 22


BUILTIN_LINUX_TOOLS: List[Dict] = [
    {"name": "builtin.uptime",       "description": "Sunucu uptime & yük ortalaması",        "category": "system",  "icon": "⏱"},
    {"name": "builtin.memory",       "description": "RAM / Swap kullanım özeti",              "category": "system",  "icon": "🧠"},
    {"name": "builtin.disk",         "description": "Disk kullanımı (df -h)",                 "category": "storage", "icon": "💾"},
    {"name": "builtin.cpu_top",      "description": "CPU'yu en çok kullanan süreçler",        "category": "process", "icon": "⚡"},
    {"name": "builtin.processes",    "description": "Tüm süreçler (CPU/MEM sırası)",          "category": "process", "icon": "🔄"},
    {"name": "builtin.network_ports","description": "Dinleyen portlar",                       "category": "network", "icon": "🌐"},
    {"name": "builtin.os_info",      "description": "İşletim sistemi & kernel bilgisi",       "category": "system",  "icon": "🐧"},
    {"name": "builtin.services",     "description": "Çalışan systemd servisleri",             "category": "system",  "icon": "⚙️"},
    {"name": "builtin.last_logins",  "description": "Son kullanıcı giriş geçmişi",            "category": "security","icon": "🔐"},
    {"name": "builtin.dmesg_errors", "description": "Kernel hata / uyarı mesajları",          "category": "security","icon": "⚠️"},
    {"name": "builtin.network_io",   "description": "Ağ arayüzü istatistikleri",              "category": "network", "icon": "📡"},
    {"name": "builtin.open_files",   "description": "En fazla dosya açan süreçler (lsof)",    "category": "process", "icon": "📂"},
]


def _builtin_command(tool_name: str) -> Optional[str]:
    commands = {
        "builtin.uptime":        "uptime && echo '---LOAD---' && cat /proc/loadavg",
        "builtin.cpu_top":       "COLUMNS=220 top -bn1 | head -n 25",
        "builtin.memory":        "free -h && echo '---VMSTAT---' && vmstat -s | head -15",
        "builtin.disk":          "df -h -x tmpfs -x devtmpfs -x squashfs 2>/dev/null || df -h",
        "builtin.network_ports": "ss -tulpen 2>/dev/null || netstat -tulpen 2>/dev/null",
        "builtin.dmesg_errors":  "dmesg --level=err,warn --time-format=reltime 2>/dev/null | tail -n 60 || dmesg | grep -iE 'error|warn|fail|critical' | tail -60",
        "builtin.os_info":       "cat /etc/os-release 2>/dev/null; echo '---KERNEL---'; uname -r; echo '---HOSTNAME---'; hostname -f 2>/dev/null || hostname; echo '---UPTIME---'; uptime; echo '---CPU---'; lscpu 2>/dev/null | grep -E 'Architecture|CPU.s.|Thread|Core|Socket|Model name|MHz' || grep 'model name' /proc/cpuinfo | head -1",
        "builtin.services":      "systemctl list-units --type=service --state=running --no-pager --plain 2>/dev/null | head -50 || service --status-all 2>&1 | head -50",
        "builtin.last_logins":   "last -n 25 -F 2>/dev/null || last -n 25",
        "builtin.processes":     "ps aux --sort=-%cpu 2>/dev/null | head -35 || ps aux | head -35",
        "builtin.network_io":    "cat /proc/net/dev && echo '---IP---' && ip -s link 2>/dev/null | head -60 || ifconfig 2>/dev/null | head -60",
        "builtin.open_files":    "lsof -n 2>/dev/null | awk '{print $1}' | sort | uniq -c | sort -rn | head -20 || echo 'lsof kullanılamıyor'",
    }
    return commands.get(tool_name)


def run_builtin_tool(host: str, credential: McpCredential, tool_name: str) -> Dict[str, Any]:
    command = _builtin_command(tool_name)
    if not command:
        raise ValueError(f"Desteklenmeyen built-in tool: {tool_name}")

    manager = SSHManager(
        host=host,
        username=credential.username,
        password=credential.password,
        private_key=credential.private_key,
        port=credential.port or 22,
    )

    if not manager.connect():
        raise RuntimeError(f"SSH baglantisi kurulamadi: {credential.username}@{host}")

    try:
        success, stdout, stderr = manager.execute_command(command)
        return {
            "tool_name": tool_name,
            "host": host,
            "success": bool(success),
            "command": command,
            "stdout": stdout,
            "stderr": stderr,
        }
    finally:
        manager.close()


async def list_linux_mcp_tools(host: str, credential: McpCredential) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except Exception:
        return [], "Python 'mcp' veya 'linux-mcp-server' paketi yuklu degil"

    env = {
        "LINUX_MCP_HOST": host,
        "LINUX_MCP_USER": credential.username,
        "LINUX_MCP_PORT": str(credential.port or 22),
        "LINUX_MCP_VERIFY_HOST_KEYS": "false",
        "LINUX_MCP_COMMAND_TIMEOUT": "20",
    }
    if credential.private_key:
        env["LINUX_MCP_SEARCH_FOR_SSH_KEY"] = "false"
        env["LINUX_MCP_SSH_KEY"] = credential.private_key
    elif credential.password:
        env["LINUX_MCP_SEARCH_FOR_SSH_KEY"] = "false"
        env["LINUX_MCP_PASSWORD"] = credential.password

    try:
        server_params = StdioServerParameters(
            command="python3",
            args=["-m", "linux_mcp_server"],
            env=env,
        )
        async with stdio_client(server_params) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                tools_resp = await session.list_tools()
                tools = []
                for t in tools_resp.tools:
                    tools.append(
                        t.model_dump() if hasattr(t, "model_dump") else {"name": str(getattr(t, "name", ""))}
                    )
                return tools, None
    except Exception as exc:
        return [], str(exc)


async def call_linux_mcp_tool(
    host: str,
    credential: McpCredential,
    tool_name: str,
    arguments: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    env = {
        "LINUX_MCP_HOST": host,
        "LINUX_MCP_USER": credential.username,
        "LINUX_MCP_PORT": str(credential.port or 22),
        "LINUX_MCP_VERIFY_HOST_KEYS": "false",
        "LINUX_MCP_COMMAND_TIMEOUT": "25",
    }
    if credential.private_key:
        env["LINUX_MCP_SEARCH_FOR_SSH_KEY"] = "false"
        env["LINUX_MCP_SSH_KEY"] = credential.private_key
    elif credential.password:
        env["LINUX_MCP_SEARCH_FOR_SSH_KEY"] = "false"
        env["LINUX_MCP_PASSWORD"] = credential.password

    server_params = StdioServerParameters(
        command="python3",
        args=["-m", "linux_mcp_server"],
        env=env,
    )

    async with stdio_client(server_params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            call_result = await session.call_tool(tool_name, arguments or {})
            return call_result.model_dump() if hasattr(call_result, "model_dump") else {"result": str(call_result)}
