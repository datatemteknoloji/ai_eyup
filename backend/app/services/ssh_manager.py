"""
SSH Connection Manager - Sunuculara SSH ile bağlanma ve komut çalıştırma
"""
import paramiko
import logging
from typing import Optional, Dict, Tuple
from io import StringIO

logger = logging.getLogger(__name__)


class SSHManager:
    """SSH bağlantı yöneticisi"""
    
    def __init__(self, host: str, username: str, password: Optional[str] = None, 
                 private_key: Optional[str] = None, port: int = 22, 
                 sudo_password: Optional[str] = None):
        self.host = host
        self.username = username
        self.password = password
        self.private_key_str = private_key
        self.port = port
        self.sudo_password = sudo_password or password
        self.client = None
    
    def connect(self) -> bool:
        """SSH bağlantısı kur"""
        try:
            self.client = paramiko.SSHClient()
            self.client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
            
            # Private key varsa kullan
            pkey = None
            if self.private_key_str:
                try:
                    key_file = StringIO(self.private_key_str)
                    pkey = paramiko.RSAKey.from_private_key(key_file)
                except Exception:
                    try:
                        key_file = StringIO(self.private_key_str)
                        pkey = paramiko.Ed25519Key.from_private_key(key_file)
                    except Exception as e:
                        logger.warning(f"Private key parse failed: {e}")
            
            # Bağlan (Önce key ile dene, başarısız olursa password ile dene)
            connected = False
            
            if pkey:
                try:
                    self.client.connect(
                        self.host,
                        port=self.port,
                        username=self.username,
                        pkey=pkey,
                        timeout=10,
                        allow_agent=False,
                        look_for_keys=False
                    )
                    connected = True
                except Exception as key_err:
                    logger.warning(f"Key auth failed for {self.host}, trying password... ({key_err})")
                    
            if not connected and self.password:
                self.client.connect(
                    self.host,
                    port=self.port,
                    username=self.username,
                    password=self.password,
                    timeout=10,
                    allow_agent=False,
                    look_for_keys=False
                )
                connected = True
                
            if not connected:
                raise Exception("Hem key hem de password ile bağlantı başarısız.")
            
            logger.info(f"✅ SSH bağlantısı başarılı: {self.username}@{self.host}")
            return True
            
        except Exception as e:
            logger.error(f"❌ SSH bağlantı hatası ({self.host}): {e}")
            return False
    
    def execute_command(self, command: str, use_sudo: bool = False) -> Tuple[bool, str, str]:
        """
        Komut çalıştır
        Returns: (success, stdout, stderr)
        """
        if not self.client:
            return False, "", "SSH bağlantısı yok"
        
        try:
            if use_sudo and self.sudo_password:
                command = f"echo '{self.sudo_password}' | sudo -S {command}"
            
            stdin, stdout, stderr = self.client.exec_command(command, timeout=30)
            
            stdout_text = stdout.read().decode('utf-8', errors='ignore')
            stderr_text = stderr.read().decode('utf-8', errors='ignore')
            exit_code = stdout.channel.recv_exit_status()
            
            success = exit_code == 0
            
            if success:
                logger.info(f"✅ Komut başarılı ({self.host}): {command[:50]}")
            else:
                logger.warning(f"⚠️ Komut hata döndü ({self.host}, exit={exit_code}): {command[:50]}")
            
            return success, stdout_text, stderr_text
            
        except Exception as e:
            logger.error(f"❌ Komut çalıştırma hatası ({self.host}): {e}")
            return False, "", str(e)
    
    def test_connection(self) -> Dict:
        """Bağlantıyı test et ve sistem bilgisi al"""
        if not self.connect():
            return {
                "success": False,
                "message": "SSH bağlantısı kurulamadı",
                "details": {}
            }
        
        try:
            # Sistem bilgisi topla
            success, hostname, _ = self.execute_command("hostname")
            _, os_info, _ = self.execute_command("cat /etc/os-release | grep PRETTY_NAME | cut -d= -f2 | tr -d '\"'")
            _, uptime, _ = self.execute_command("uptime -p")
            _, kernel, _ = self.execute_command("uname -r")
            
            details = {
                "hostname": hostname.strip() if success else "Unknown",
                "os": os_info.strip() if os_info else "Unknown",
                "uptime": uptime.strip() if uptime else "Unknown",
                "kernel": kernel.strip() if kernel else "Unknown"
            }
            
            return {
                "success": True,
                "message": f"✅ SSH bağlantısı başarılı: {self.username}@{self.host}",
                "details": details
            }
            
        except Exception as e:
            return {
                "success": False,
                "message": f"Bağlantı kuruldu ama bilgi alınamadı: {e}",
                "details": {}
            }
    
    def install_node_exporter(self, version: str = "1.7.0") -> Tuple[bool, str]:
        """Node Exporter kur"""
        try:
            # İndirme ve kurulum komutları
            install_script = f"""
# Node Exporter kontrol et
if systemctl is-active --quiet node_exporter; then
    echo "Node Exporter zaten çalışıyor"
    exit 0
fi

# İndir ve kur
cd /tmp
wget -q https://github.com/prometheus/node_exporter/releases/download/v{version}/node_exporter-{version}.linux-amd64.tar.gz
tar xzf node_exporter-{version}.linux-amd64.tar.gz
sudo mv node_exporter-{version}.linux-amd64/node_exporter /usr/local/bin/
sudo rm -rf node_exporter-{version}*

# Systemd service oluştur
sudo tee /etc/systemd/system/node_exporter.service > /dev/null <<EOF
[Unit]
Description=Node Exporter
After=network.target

[Service]
User=nobody
ExecStart=/usr/local/bin/node_exporter
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# Başlat
sudo systemctl daemon-reload
sudo systemctl enable node_exporter
sudo systemctl start node_exporter

echo "Node Exporter kuruldu ve başlatıldı"
"""
            
            success, stdout, stderr = self.execute_command(install_script)
            
            if success or "zaten çalışıyor" in stdout:
                logger.info(f"✅ Node Exporter kuruldu: {self.host}")
                return True, stdout
            else:
                logger.error(f"❌ Node Exporter kurulum hatası ({self.host}): {stderr}")
                return False, stderr
                
        except Exception as e:
            logger.error(f"❌ Node Exporter kurulum exception ({self.host}): {e}")
            return False, str(e)
    
    def close(self):
        """Bağlantıyı kapat"""
        if self.client:
            try:
                self.client.close()
                logger.info(f"SSH bağlantısı kapatıldı: {self.host}")
            except Exception as e:
                logger.warning(f"Operation failed: {e}")
    
    def __enter__(self):
        self.connect()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()
