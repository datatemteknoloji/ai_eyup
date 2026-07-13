"""
Proxmox VE REST API client.
Uses `proxmoxer` library to manage VMs and containers on Proxmox nodes.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ProxmoxClient:
    """Proxmox VE client using proxmoxer."""

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 8006,
        verify_ssl: bool = False,
        realm: str = "pam",
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.verify_ssl = verify_ssl
        self.realm = realm
        self._prx = None

    def _connect(self):
        if self._prx is None:
            from proxmoxer import ProxmoxAPI
            user = f"{self.username}@{self.realm}"
            self._prx = ProxmoxAPI(
                self.host,
                user=user,
                password=self.password,
                verify_ssl=self.verify_ssl,
                port=self.port,
            )
        return self._prx

    def test_connection(self) -> Dict[str, Any]:
        try:
            prx = self._connect()
            version = prx.version.get()
            return {
                "connected": True,
                "version": version.get("version", ""),
                "release": version.get("release", ""),
                "message": "Proxmox bağlantısı başarılı",
            }
        except Exception as exc:
            return {"connected": False, "message": str(exc)}

    def list_nodes(self) -> List[Dict]:
        """List all Proxmox cluster nodes."""
        try:
            prx = self._connect()
            return [
                {
                    "name": n["node"],
                    "status": n.get("status", "unknown"),
                    "cpu_usage": round(n.get("cpu", 0) * 100, 1),
                    "mem_total_gb": round(n.get("maxmem", 0) / (1024 ** 3), 2),
                    "mem_used_gb": round(n.get("mem", 0) / (1024 ** 3), 2),
                    "uptime": n.get("uptime", 0),
                }
                for n in prx.nodes.get()
            ]
        except Exception as exc:
            logger.error("Proxmox list_nodes error: %s", exc)
            return []

    def list_vms(self) -> List[Dict]:
        """List all VMs (qemu) and containers (lxc) across all nodes."""
        vms = []
        try:
            prx = self._connect()
            for node in prx.nodes.get():
                node_name = node["node"]
                # QEMU VMs
                for vm in prx.nodes(node_name).qemu.get():
                    vms.append(self._map_vm(vm, node_name, "qemu"))
                # LXC containers
                for ct in prx.nodes(node_name).lxc.get():
                    vms.append(self._map_vm(ct, node_name, "lxc"))
        except Exception as exc:
            logger.error("Proxmox list_vms error: %s", exc)
        return vms

    def _map_vm(self, raw: Dict, node: str, vm_type: str) -> Dict:
        status = raw.get("status", "stopped")
        return {
            "vm_id": str(raw.get("vmid", "")),
            "name": raw.get("name", f"vm-{raw.get('vmid')}"),
            "status": "ONLINE" if status == "running" else "OFFLINE",
            "power_state": status,
            "cpu_cores": raw.get("cpus") or raw.get("cpu", 0),
            "memory_gb": round((raw.get("maxmem") or raw.get("mem", 0)) / (1024 ** 3), 1),
            "disk_gb": round((raw.get("maxdisk", 0)) / (1024 ** 3), 1),
            "os_type": "lxc" if vm_type == "lxc" else "",
            "ip_address": "",
            "node": node,
            "vm_type": vm_type,
            "uptime": raw.get("uptime", 0),
        }

    def get_vm_detail(self, node: str, vmid: int) -> Dict:
        """Get detailed configuration for a VM."""
        try:
            prx = self._connect()
            config = prx.nodes(node).qemu(vmid).config.get()
            status = prx.nodes(node).qemu(vmid).status.current.get()
            return {
                "config": config,
                "status": status,
                "vmid": vmid,
                "node": node,
            }
        except Exception as exc:
            return {"error": str(exc)}

    def start_vm(self, node: str, vmid: int) -> Dict:
        try:
            prx = self._connect()
            task = prx.nodes(node).qemu(vmid).status.start.post()
            return {"success": True, "task": task}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def stop_vm(self, node: str, vmid: int) -> Dict:
        try:
            prx = self._connect()
            task = prx.nodes(node).qemu(vmid).status.stop.post()
            return {"success": True, "task": task}
        except Exception as exc:
            return {"success": False, "error": str(exc)}

    def list_storages(self) -> List[Dict]:
        """List all storage backends across nodes."""
        storages = []
        try:
            prx = self._connect()
            for node in prx.nodes.get():
                node_name = node["node"]
                for st in prx.nodes(node_name).storage.get():
                    storages.append({
                        "node": node_name,
                        "storage": st.get("storage"),
                        "type": st.get("type"),
                        "total_gb": round((st.get("total", 0)) / (1024 ** 3), 1),
                        "avail_gb": round((st.get("avail", 0)) / (1024 ** 3), 1),
                        "used_gb": round((st.get("used", 0)) / (1024 ** 3), 1),
                        "active": st.get("active", 0) == 1,
                    })
        except Exception as exc:
            logger.error("Proxmox list_storages error: %s", exc)
        return storages

    @classmethod
    def from_hypervisor(cls, hv) -> "ProxmoxClient":
        """Build client from Hypervisor ORM object."""
        return cls(
            host=hv.host,
            username=hv.username,
            password=hv.password,
            port=hv.port or 8006,
            verify_ssl=hv.verify_ssl if hasattr(hv, "verify_ssl") else False,
        )
