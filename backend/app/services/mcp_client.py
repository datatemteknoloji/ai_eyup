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


BUILTIN_LINUX_TOOLS: List[Dict[str, str]] = [
    {"name": "builtin.uptime", "description": "Sunucu uptime bilgisini getirir"},
    {"name": "builtin.cpu_top", "description": "CPU kullanan ilk surecleri getirir"},
    {"name": "builtin.memory", "description": "RAM kullanim ozetini getirir"},
    {"name": "builtin.disk", "description": "Disk kullanim ozetini getirir"},
    {"name": "builtin.network_ports", "description": "Dinlenen portlari listeler"},
    {"name": "builtin.dmesg_errors", "description": "Son kernel hata satirlarini getirir"},
]


def _builtin_command(tool_name: str) -> Optional[str]:
    commands = {
        "builtin.uptime": "uptime",
        "builtin.cpu_top": "COLUMNS=200 top -bn1 | head -n 20",
        "builtin.memory": "free -h",
        "builtin.disk": "df -h",
        "builtin.network_ports": "ss -tulpen || netstat -tulpen",
        "builtin.dmesg_errors": "dmesg --level=err,warn | tail -n 80",
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
