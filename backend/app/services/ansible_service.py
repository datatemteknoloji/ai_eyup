"""
Ansible Service - Inventory oluşturma, ad-hoc komut, SSH check
"""
import os
import json
import logging
import tempfile
import subprocess
from typing import List, Dict, Any, Optional, Tuple
from sqlalchemy.orm import Session
from app.models.server import Server
from app.models.credential import GlobalCredential

logger = logging.getLogger(__name__)


class AnsibleService:
    """Ansible ad-hoc komut + inventory yönetimi"""

    @staticmethod
    def generate_inventory(servers: List[Server], db: Optional[Session] = None) -> str:
        """
        Sunuculardan Ansible inventory (INI) oluştur.
        Önce sunucunun kendi connection_config'ine bakar,
        yoksa Global Credential'dan alır.
        """
        lines = ["[all]"]
        
        # Global Credential'ı al (yoksa None)
        global_cred = None
        if db:
            global_cred = db.query(GlobalCredential).first()
        
        for s in servers:
            # SADECE IP adresi olanları ekle, hostname ile bağlanma YOK
            if not s.ip_address or not s.ip_address.strip():
                logger.warning(f"Sunucu '{s.name}' atlandı: IP adresi yok")
                continue
            
            host = s.ip_address.strip()
            
            # Önce sunucunun kendi config'i, yoksa global credential
            cfg = s.connection_config or {}
            user = cfg.get("username")
            password = cfg.get("password")
            private_key = cfg.get("private_key")
            port = cfg.get("port")
            sudo_password = cfg.get("sudo_password")
            
            # Global credential'dan fallback
            if not user and global_cred:
                user = global_cred.username
            if not password and global_cred:
                password = global_cred.password
            if not private_key and global_cred:
                private_key = global_cred.private_key
            if not port and global_cred:
                port = global_cred.port
            if not sudo_password and global_cred:
                sudo_password = global_cred.sudo_password
            
            # Varsayılanlar
            user = user or "root"
            port = port or 22
            
            # ansible_host, ansible_user, ansible_port, ansible_ssh_pass (veya key)
            inv_line = f"{s.name} ansible_host={host} ansible_user={user} ansible_port={port}"
            inv_line += " ansible_ssh_common_args='-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null'"
            
            if password:
                inv_line += f" ansible_ssh_pass={password}"
            if private_key:
                # Private key dosyaya yazılmalı (geçici)
                inv_line += f" ansible_ssh_private_key_file=/tmp/ansible_key_{s.id}"
            if sudo_password:
                inv_line += f" ansible_become_pass={sudo_password}"
            
            lines.append(inv_line)
        
        return "\n".join(lines)

    @staticmethod
    def ping_servers(servers: List[Server], db: Optional[Session] = None) -> Dict[str, bool]:
        """Ansible ping modülü ile SSH check. {server_name: reachable}"""
        if not servers:
            return {}
        
        inventory_content = AnsibleService.generate_inventory(servers, db)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as inv_file:
            inv_file.write(inventory_content)
            inv_path = inv_file.name
        
        try:
            # ansible all -i <inventory> -m ping --one-line
            result = subprocess.run(
                ["ansible", "all", "-i", inv_path, "-m", "ping", "--one-line"],
                capture_output=True,
                text=True,
                timeout=60
            )
            
            # Çıktı: "host1 | SUCCESS => {...}" veya "host2 | UNREACHABLE! => {...}"
            reachable = {}
            for line in result.stdout.splitlines():
                if " | " in line:
                    parts = line.split(" | ", 1)
                    host_name = parts[0].strip()
                    status = parts[1]
                    reachable[host_name] = "SUCCESS" in status
            
            return reachable
        except subprocess.TimeoutExpired:
            logger.error("Ansible ping timeout")
            return {s.name: False for s in servers}
        except Exception as e:
            logger.error(f"Ansible ping error: {e}")
            return {s.name: False for s in servers}
        finally:
            os.remove(inv_path)

    @staticmethod
    def run_ad_hoc_command(
        servers: List[Server],
        module: str = "shell",
        args: str = "",
        become: bool = False,
        db: Optional[Session] = None
    ) -> Dict[str, Any]:
        """
        Ansible ad-hoc komut çalıştır.
        module: shell, command, yum, apt, copy, vb.
        args: modül argümanları (örn: "uptime" veya "name=vim state=present")
        become: sudo ile çalıştır mı
        
        Dönüş: {
            "success": bool,
            "results": {server_name: {"rc": int, "stdout": str, "stderr": str}},
            "failed": [server_name, ...]
        }
        """
        if not servers:
            return {"success": False, "error": "Hiç sunucu seçilmedi", "results": {}, "failed": []}
        
        inventory_content = AnsibleService.generate_inventory(servers, db)
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as inv_file:
            inv_file.write(inventory_content)
            inv_path = inv_file.name
        
        try:
            cmd = ["ansible", "all", "-i", inv_path, "-m", module, "-a", args, "-T", "30", "-f", "10"]
            if become:
                cmd.append("--become")
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 dakika (çok sunucu için)
            )
            
            # Ansible çıktısını parse et (stdout + stderr)
            results = {}
            failed = []
            
            # Önce stdout'u satır satır işle
            for line in result.stdout.splitlines():
                if " | " not in line:
                    continue
                    
                parts = line.split(" | ", 1)
                if len(parts) < 2:
                    continue
                    
                host_name = parts[0].strip()
                status_and_output = parts[1].strip()
                
                if "SUCCESS" in status_and_output or "CHANGED" in status_and_output:
                    # Çıktıyı => işaretinden sonra al
                    if " >> " in status_and_output:
                        output = status_and_output.split(" >> ", 1)[1] if len(status_and_output.split(" >> ", 1)) > 1 else ""
                    else:
                        output = status_and_output
                    results[host_name] = {"rc": 0, "stdout": output, "stderr": ""}
                elif "FAILED" in status_and_output or "UNREACHABLE" in status_and_output:
                    results[host_name] = {"rc": 1, "stdout": "", "stderr": status_and_output}
                    failed.append(host_name)
            
            # stderr'de başarısız olanları ekle
            for line in result.stderr.splitlines():
                if " | " not in line:
                    continue
                parts = line.split(" | ", 1)
                if len(parts) < 2:
                    continue
                host_name = parts[0].strip()
                if host_name not in results:
                    results[host_name] = {"rc": 1, "stdout": "", "stderr": parts[1].strip()}
                    failed.append(host_name)
            
            return {
                "success": result.returncode == 0,
                "results": results,
                "failed": failed,
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timeout (10 dk)", "results": {}, "failed": [s.name for s in servers]}
        except Exception as e:
            logger.error(f"Ansible ad-hoc error: {e}", exc_info=True)
            return {"success": False, "error": str(e), "results": {}, "failed": []}
        finally:
            os.remove(inv_path)

    @staticmethod
    def run_playbook(servers: List[Server], playbook_content: str, db: Optional[Session] = None) -> Dict[str, Any]:
        """
        Seçili sunucularda Ansible playbook (YAML) çalıştır.
        Playbook içeriği geçici dosyaya yazılır, ansible-playbook komutu çalıştırılır.
        """
        # Inventory oluştur
        inventory_content = AnsibleService.generate_inventory(servers, db)
        
        # Geçici dosyalar: inventory ve playbook
        with tempfile.NamedTemporaryFile(mode='w', suffix='.ini', delete=False) as inv_file:
            inv_file.write(inventory_content)
            inv_path = inv_file.name
        
        with tempfile.NamedTemporaryFile(mode='w', suffix='.yml', delete=False) as pb_file:
            pb_file.write(playbook_content)
            pb_path = pb_file.name
        
        try:
            logger.info(f"Ansible playbook çalıştırılıyor: {len(servers)} sunucu")
            
            cmd = [
                "ansible-playbook",
                "-i", inv_path,
                pb_path,
                "-T", "30",  # SSH timeout 30sn
                "-f", "10"   # 10 paralel fork
            ]
            
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=600  # 10 dakika timeout
            )
            
            logger.info(f"Playbook tamamlandı: returncode={result.returncode}")
            
            # Çıktıyı parse et
            results = {}
            failed = []
            
            # Basit parsing: Her satırda "host_name | SUCCESS/FAILED" ara
            for line in result.stdout.splitlines():
                if " | " not in line:
                    continue
                    
                parts = line.split(" | ", 1)
                if len(parts) < 2:
                    continue
                    
                host_name = parts[0].strip()
                status_and_output = parts[1].strip()
                
                if "ok=" in status_and_output or "changed=" in status_and_output:
                    # PLAY RECAP satırı
                    results[host_name] = {"rc": 0, "stdout": status_and_output, "stderr": ""}
                    if "failed=" in status_and_output and "failed=0" not in status_and_output:
                        failed.append(host_name)
            
            # stderr'de hata kontrolü
            if result.stderr:
                for line in result.stderr.splitlines():
                    if "UNREACHABLE" in line or "FAILED" in line:
                        # Host ismini çıkar
                        for server in servers:
                            if server.name in line or server.ip_address in line:
                                failed.append(server.name)
            
            return {
                "success": result.returncode == 0,
                "results": results,
                "failed": list(set(failed)),
                "stdout": result.stdout,
                "stderr": result.stderr
            }
        except subprocess.TimeoutExpired:
            return {"success": False, "error": "Timeout (10 dk)", "results": {}, "failed": [s.name for s in servers]}
        except Exception as e:
            logger.error(f"Ansible playbook error: {e}", exc_info=True)
            return {"success": False, "error": str(e), "results": {}, "failed": []}
        finally:
            os.remove(inv_path)
            os.remove(pb_path)
