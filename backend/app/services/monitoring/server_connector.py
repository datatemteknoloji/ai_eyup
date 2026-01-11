"""
Server Connector - SSH/WinRM bağlantı servisi
"""
import logging
import paramiko
from typing import Dict, Optional, Any

logger = logging.getLogger(__name__)

class ServerConnector:
    """Sunucu bağlantı servisi (SSH/WinRM)"""
    
    def __init__(self, server):
        """
        Args:
            server: Server model instance with connection_config
        """
        self.server = server
        self.connection_config = server.connection_config or {}
        self.os_type = server.os_type.lower() if server.os_type else "linux"
        self.ip_address = server.ip_address
        self.port = self.connection_config.get("port") or (22 if self.os_type == "linux" else 5985)
        self._username = self.connection_config.get("username")
        self._password = self.connection_config.get("password")
        self.private_key = self.connection_config.get("private_key")
        self.sudo_password = self.connection_config.get("sudo_password") or self._password  # Sudo şifresi (varsa)
        self.ssh_client: Optional[paramiko.SSHClient] = None
    
    def _get_ssh_client(self) -> paramiko.SSHClient:
        """SSH client oluştur ve bağlan"""
        if self.ssh_client:
            try:
                # Bağlantıyı test et
                self.ssh_client.get_transport().send_ignore()
                return self.ssh_client
            except:
                pass
        
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        
        try:
            # Private key varsa kullan
            if self.private_key:
                import io
                key_file = io.StringIO(self.private_key)
                try:
                    pkey = paramiko.RSAKey.from_private_key(key_file)
                except:
                    key_file.seek(0)
                    try:
                        pkey = paramiko.Ed25519Key.from_private_key(key_file)
                    except:
                        key_file.seek(0)
                        pkey = paramiko.ECDSAKey.from_private_key(key_file)
                
                ssh.connect(
                    hostname=self.ip_address,
                    port=self.port,
                    username=self._username,
                    pkey=pkey,
                    timeout=10,
                    look_for_keys=False,
                    allow_agent=False
                )
            else:
                # Password ile bağlan
                ssh.connect(
                    hostname=self.ip_address,
                    port=self.port,
                    username=self._username,
                    password=self._password,
                    timeout=10,
                    look_for_keys=False,
                    allow_agent=False
                )
            
            self.ssh_client = ssh
            return ssh
            
        except Exception as e:
            logger.error(f"SSH bağlantı hatası: {e}")
            raise
    
    def test_connection(self) -> Dict[str, Any]:
        """Bağlantı testi"""
        try:
            ssh = self._get_ssh_client()
            stdin, stdout, stderr = ssh.exec_command("echo 'OK'", timeout=5)
            exit_status = stdout.channel.recv_exit_status()
            
            if exit_status == 0:
                return {"success": True, "message": "Bağlantı başarılı"}
            else:
                error_msg = stderr.read().decode('utf-8', errors='ignore')
                return {"success": False, "error": f"Komut hatası: {error_msg}"}
                
        except paramiko.AuthenticationException:
            return {"success": False, "error": "Kimlik doğrulama hatası: Kullanıcı adı veya şifre yanlış"}
        except paramiko.SSHException as e:
            return {"success": False, "error": f"SSH hatası: {str(e)}"}
        except Exception as e:
            return {"success": False, "error": f"Bağlantı hatası: {str(e)}"}
    
    def execute_command(self, command: str, timeout: int = 30) -> Dict[str, Any]:
        """Komut çalıştır"""
        try:
            ssh = self._get_ssh_client()
            stdin, stdout, stderr = ssh.exec_command(command, timeout=timeout)
            exit_status = stdout.channel.recv_exit_status()
            
            stdout_text = stdout.read().decode('utf-8', errors='ignore')
            stderr_text = stderr.read().decode('utf-8', errors='ignore')
            
            return {
                "success": exit_status == 0,
                "stdout": stdout_text,
                "stderr": stderr_text,
                "exit_code": exit_status,
                "command": command
            }
            
        except Exception as e:
            logger.error(f"Komut çalıştırma hatası: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "stdout": "",
                "stderr": str(e),
                "exit_code": -1,
                "command": command
            }
    
    def close(self):
        """Bağlantıyı kapat"""
        if self.ssh_client:
            try:
                self.ssh_client.close()
            except:
                pass
            self.ssh_client = None
    
    def __del__(self):
        """Destructor - bağlantıyı kapat"""
        self.close()
    
    @property
    def password(self) -> Optional[str]:
        """Password property"""
        return self._password
    
    @property
    def username(self) -> str:
        """Username property"""
        return self._username or ""
