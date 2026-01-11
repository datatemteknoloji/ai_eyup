"""
Node Exporter Installer - SSH ile Node Exporter kurulumu
"""
import os
import json
import logging
import subprocess
import platform
import paramiko
from pathlib import Path
from typing import Dict, Optional, Any
from app.services.monitoring.server_connector import ServerConnector
from app.core.config import settings

logger = logging.getLogger(__name__)

class NodeExporterInstaller:
    """Node Exporter kurulum servisi"""
    
    NODE_EXPORTER_VERSION = "1.7.0"
    NODE_EXPORTER_PORT = 9100
    
    def __init__(self, server):
        """
        Args:
            server: Server model instance with connection_config
        """
        self.server = server
        self.connector = ServerConnector(server)
        self.os_type = server.os_type.lower() if server.os_type else "linux"
        self.arch = self._detect_architecture()
    
    def _detect_architecture(self) -> str:
        """Sunucu mimarisini tespit et"""
        try:
            result = self.connector.execute_command("uname -m")
            if result.get("success"):
                arch = result.get("stdout", "").strip()
                # Mapping
                arch_map = {
                    "x86_64": "amd64",
                    "amd64": "amd64",
                    "aarch64": "arm64",
                    "arm64": "arm64",
                    "armv7l": "armv7",
                    "armv6l": "armv6"
                }
                return arch_map.get(arch, "amd64")
        except Exception as e:
            logger.warning(f"Architecture detection failed: {e}")
        return "amd64"  # Default
    
    def install(self) -> Dict[str, Any]:
        """Node Exporter kurulumu"""
        try:
            if self.os_type == "windows":
                return {"success": False, "error": "Windows için Node Exporter kurulumu henüz desteklenmiyor"}
            
            # 1. Bağlantı testi
            connection_test = self.connector.test_connection()
            if not connection_test.get("success"):
                return {"success": False, "error": f"SSH bağlantı hatası: {connection_test.get('error')}"}
            
            # 2. Node Exporter zaten kurulu mu kontrol et
            status_check = self.check_status()
            if status_check.get("installed") and status_check.get("running"):
                return {"success": True, "message": "Node Exporter zaten kurulu ve çalışıyor", "installed": True, "running": True}
            
            # 3. Node Exporter'ı indir
            download_result = self._download_node_exporter()
            if not download_result.get("success"):
                return download_result
            
            # 4. Node Exporter'ı kur
            install_result = self._install_node_exporter(download_result.get("path"))
            if not install_result.get("success"):
                return install_result
            
            # 5. Systemd servisi oluştur
            service_result = self._create_systemd_service()
            if not service_result.get("success"):
                return service_result
            
            # 6. Servisi başlat
            start_result = self._start_service()
            if not start_result.get("success"):
                return start_result
            
            # 7. Durumu kontrol et
            final_check = self.check_status()
            
            return {
                "success": True,
                "message": "Node Exporter başarıyla kuruldu ve başlatıldı",
                "installed": True,
                "running": final_check.get("running", False),
                "port": self.NODE_EXPORTER_PORT,
                "version": self.NODE_EXPORTER_VERSION
            }
            
        except Exception as e:
            logger.error(f"Node Exporter kurulum hatası: {e}", exc_info=True)
            return {"success": False, "error": f"Kurulum hatası: {str(e)}"}
    
    def _get_local_binary_path(self) -> Optional[str]:
        """Backend sunucusundaki binary dosya yolunu al"""
        try:
            storage_path = Path(settings.NODE_EXPORTER_STORAGE_PATH)
            arch_dir = storage_path / self.arch
            binary_file = arch_dir / "node_exporter"
            
            # Binary var mı kontrol et
            if binary_file.exists() and binary_file.is_file():
                return str(binary_file.absolute())
            
            # Veya genel binary (tüm mimariler için)
            general_binary = storage_path / "node_exporter"
            if general_binary.exists() and general_binary.is_file():
                return str(general_binary.absolute())
            
            logger.warning(f"Local binary bulunamadı: {binary_file} veya {general_binary}")
            return None
            
        except Exception as e:
            logger.error(f"Local binary path hatası: {e}", exc_info=True)
            return None
    
    def _download_node_exporter(self) -> Dict[str, Any]:
        """Node Exporter binary'sini backend sunucusundan dağıt veya GitHub'dan indir"""
        try:
            # Önce backend sunucusundan dağıtmayı dene
            local_binary = self._get_local_binary_path()
            
            if local_binary and settings.NODE_EXPORTER_DISTRIBUTION_METHOD == "scp":
                # SCP ile kopyala
                return self._distribute_via_scp(local_binary)
            elif local_binary and settings.NODE_EXPORTER_DISTRIBUTION_METHOD == "http":
                # HTTP ile indir
                return self._distribute_via_http(local_binary)
            else:
                # Fallback: GitHub'dan indir
                logger.info(f"Local binary bulunamadı, GitHub'dan indiriliyor (arch: {self.arch})")
                return self._download_from_github()
                
        except Exception as e:
            logger.error(f"Download hatası: {e}", exc_info=True)
            return {"success": False, "error": f"İndirme hatası: {str(e)}"}
    
    def _distribute_via_scp(self, local_binary_path: str) -> Dict[str, Any]:
        """SCP ile binary'yi remote sunucuya kopyala (paramiko SFTP kullanarak)"""
        try:
            ssh = self.connector._get_ssh_client()
            sftp = ssh.open_sftp()
            
            # Remote temp dizini
            remote_temp_dir = "/tmp"
            remote_binary_path = f"{remote_temp_dir}/node_exporter"
            
            try:
                # Binary'yi oku
                with open(local_binary_path, 'rb') as local_file:
                    binary_data = local_file.read()
                
                # Remote sunucuya yaz
                remote_file = sftp.file(remote_binary_path, 'wb')
                remote_file.write(binary_data)
                remote_file.close()
                
                # Remote dosya izinlerini ayarla (chmod yapmak için komut çalıştır)
                self.connector.execute_command(f"chmod +x {remote_binary_path}")
                
                # Binary'yi test et
                test_result = self.connector.execute_command(f"{remote_binary_path} --version")
                if test_result.get("success") or "version" in test_result.get("stdout", "").lower():
                    return {"success": True, "path": remote_binary_path, "method": "scp", "source": "backend_server"}
                else:
                    return {"success": False, "error": f"Binary test hatası: {test_result.get('stderr', 'Bilinmeyen hata')}"}
                    
            finally:
                sftp.close()
                
        except Exception as e:
            logger.error(f"SCP/SFTP dağıtım hatası: {e}", exc_info=True)
            # Fallback: Base64 ile dağıt
            logger.info("SCP başarısız, Base64 metodunu deniyoruz")
            return self._distribute_via_base64(local_binary_path)
    
    def _distribute_via_base64(self, local_binary_path: str) -> Dict[str, Any]:
        """Base64 encoding ile binary'yi remote sunucuya aktar (fallback metod)"""
        try:
            import base64
            
            # Binary'yi oku
            with open(local_binary_path, 'rb') as f:
                binary_data = f.read()
            
            # Binary boyutunu kontrol et (20MB limit)
            binary_size_mb = len(binary_data) / 1024 / 1024
            if binary_size_mb > 20:
                logger.warning(f"Binary çok büyük ({binary_size_mb:.2f} MB), SFTP metodunu kullanın")
                return {"success": False, "error": f"Binary çok büyük ({binary_size_mb:.2f} MB), SFTP veya HTTP metodu kullanın"}
            
            # Base64 encode et
            encoded_data = base64.b64encode(binary_data).decode('utf-8')
            
            # Remote sunucuya base64 decode ederek yaz (Python script ile)
            remote_temp_dir = "/tmp"
            remote_binary_path = f"{remote_temp_dir}/node_exporter"
            
            # Python ile decode ve yazma (daha güvenilir)
            python_script = f"""
import base64
import os

encoded_data = '''{encoded_data}'''

binary_data = base64.b64decode(encoded_data)
with open('{remote_binary_path}', 'wb') as f:
    f.write(binary_data)

os.chmod('{remote_binary_path}', 0o755)
print('OK')
"""
            
            # Python script'i çalıştır
            result = self.connector.execute_command(f"python3 << 'EOFPYTHON'\n{python_script}\nEOFPYTHON\n")
            
            if result.get("success") and "OK" in result.get("stdout", ""):
                # Binary'yi test et
                test_result = self.connector.execute_command(f"{remote_binary_path} --version")
                if test_result.get("success") or "version" in test_result.get("stdout", "").lower():
                    return {"success": True, "path": remote_binary_path, "method": "base64", "source": "backend_server"}
                else:
                    return {"success": False, "error": f"Binary test hatası: {test_result.get('stderr', 'Bilinmeyen hata')}"}
            else:
                error_msg = result.get('stderr', result.get('stdout', 'Bilinmeyen hata'))
                return {"success": False, "error": f"Binary yazma hatası: {error_msg[:300]}"}
                
        except Exception as e:
            logger.error(f"Base64 dağıtım hatası: {e}", exc_info=True)
            return {"success": False, "error": f"Base64 dağıtım hatası: {str(e)}"}
    
    def _distribute_via_http(self, local_binary_path: str) -> Dict[str, Any]:
        """HTTP endpoint üzerinden binary'yi indir (backend HTTP server gerekli)"""
        try:
            # Backend host IP'sini bul (sunucunun erişebileceği IP)
            # Önce sunucunun backend'e erişip erişemediğini test et
            # Genelde backend container'ının IP'si veya host IP'si kullanılır
            
            # Environment variable'dan veya config'den al
            backend_host = settings.BACKEND_HOST
            if backend_host == "localhost":
                # Localhost yerine gerçek IP kullan (sunucudan erişilebilir olmalı)
                # Sunucunun backend'e erişimi için backend container'ının IP'sini kullan
                # Veya Docker network'ündeki hostname'i kullan
                backend_host = os.getenv("BACKEND_SERVICE_HOST", "backend")  # Docker compose service name
            
            backend_port = settings.BACKEND_PORT
            download_url = f"http://{backend_host}:{backend_port}/api/v1/monitoring/node-exporter/download/{self.arch}"
            remote_temp_dir = "/tmp"
            remote_binary_path = f"{remote_temp_dir}/node_exporter"
            
            # curl veya wget ile indir
            download_cmd = f"""
                curl -s -f {download_url} -o {remote_binary_path} 2>&1 || \
                wget -q {download_url} -O {remote_binary_path} 2>&1
            """
            
            result = self.connector.execute_command(download_cmd)
            if result.get("success"):
                # Dosyanın indirildiğini kontrol et
                file_check = self.connector.execute_command(f"test -f {remote_binary_path} && echo 'exists' || echo 'not found'")
                if "exists" in file_check.get("stdout", "").lower():
                    # Binary'yi executable yap ve test et
                    chmod_result = self.connector.execute_command(f"chmod +x {remote_binary_path}")
                    if chmod_result.get("success"):
                        test_result = self.connector.execute_command(f"{remote_binary_path} --version")
                        if test_result.get("success") or "version" in test_result.get("stdout", "").lower():
                            return {"success": True, "path": remote_binary_path, "method": "http", "source": "backend_server", "url": download_url}
                        else:
                            return {"success": False, "error": f"Binary test hatası: {test_result.get('stderr', 'Bilinmeyen hata')}"}
                    else:
                        return {"success": False, "error": f"chmod hatası: {chmod_result.get('stderr', 'Bilinmeyen hata')}"}
                else:
                    error_msg = result.get('stdout', '') + result.get('stderr', '')
                    return {"success": False, "error": f"Dosya indirilemedi: {error_msg[:200]}"}
            else:
                error_msg = result.get('stdout', '') + result.get('stderr', '')
                return {"success": False, "error": f"HTTP indirme hatası: {error_msg[:200]}"}
                
        except Exception as e:
            logger.error(f"HTTP dağıtım hatası: {e}", exc_info=True)
            return {"success": False, "error": f"HTTP dağıtım hatası: {str(e)}"}
    
    def _download_from_github(self) -> Dict[str, Any]:
        """GitHub'dan Node Exporter binary'sini indir (fallback)"""
        try:
            download_url = f"https://github.com/prometheus/node_exporter/releases/download/v{self.NODE_EXPORTER_VERSION}/node_exporter-{self.NODE_EXPORTER_VERSION}.linux-{self.arch}.tar.gz"
            download_dir = "/tmp"
            tar_filename = f"node_exporter-{self.NODE_EXPORTER_VERSION}.linux-{self.arch}.tar.gz"
            extract_dir = f"/tmp/node_exporter-{self.NODE_EXPORTER_VERSION}.linux-{self.arch}"
            binary_path = f"{extract_dir}/node_exporter"
            
            # Download komutu
            download_cmd = f"""
                cd {download_dir} && \
                wget -q {download_url} -O {tar_filename} && \
                tar -xzf {tar_filename} && \
                echo {binary_path}
            """
            
            result = self.connector.execute_command(download_cmd)
            if result.get("success"):
                return {"success": True, "path": binary_path, "method": "github", "source": "github", "download_url": download_url}
            else:
                # Son çare: Base64 ile dağıt
                logger.warning("GitHub indirme başarısız, Base64 ile dağıtım deneniyor")
                local_binary = self._get_local_binary_path()
                if local_binary:
                    return self._distribute_via_base64(local_binary)
                return {"success": False, "error": f"GitHub indirme hatası: {result.get('stderr', 'Bilinmeyen hata')}"}
                
        except Exception as e:
            logger.error(f"GitHub download hatası: {e}", exc_info=True)
            return {"success": False, "error": f"GitHub indirme hatası: {str(e)}"}
    
    def _install_node_exporter(self, binary_path: str) -> Dict[str, Any]:
        """Node Exporter binary'sini /usr/local/bin'e kopyala (sudo olmadan deneyelim)"""
        try:
            # Önce sudo olmadan deneyelim (root kullanıcı ise)
            is_root = self.connector.username == "root"
            
            if is_root:
                # Root kullanıcı - sudo gerekmez
                install_cmd = f"""
                    mkdir -p /usr/local/bin && \
                    cp {binary_path} /usr/local/bin/node_exporter && \
                    chmod +x /usr/local/bin/node_exporter && \
                    chown root:root /usr/local/bin/node_exporter && \
                    /usr/local/bin/node_exporter --version
                """
            else:
                # Kullanıcı dizinine kur (sudo gerekmez)
                user_home = f"/home/{self.connector.username}"
                # Kullanıcı home dizinini tespit et
                home_check = self.connector.execute_command("echo $HOME")
                user_home = home_check.get("stdout", f"/home/{self.connector.username}").strip() or f"/home/{self.connector.username}"
                
                install_cmd = f"""
                    mkdir -p {user_home}/bin && \
                    cp {binary_path} {user_home}/bin/node_exporter && \
                    chmod +x {user_home}/bin/node_exporter && \
                    {user_home}/bin/node_exporter --version
                """
            
            result = self.connector.execute_command(install_cmd)
            if result.get("success") or "version" in result.get("stdout", "").lower():
                if is_root:
                    install_path = "/usr/local/bin/node_exporter"
                else:
                    install_path = f"/home/{self.connector.username}/bin/node_exporter"
                return {"success": True, "message": "Node Exporter binary kopyalandı", "install_path": install_path}
            else:
                error_msg = result.get('stderr', result.get('stdout', 'Bilinmeyen hata'))
                # Sudo gerekirse deneyelim
                if not is_root:
                    password = self.connector.sudo_password or ""
                    sudo_prefix = f"echo '{password}' | sudo -S" if password else "sudo"
                    sudo_cmd = f"""
                        {sudo_prefix} mkdir -p /usr/local/bin && \
                        {sudo_prefix} cp {binary_path} /usr/local/bin/node_exporter && \
                        {sudo_prefix} chmod +x /usr/local/bin/node_exporter && \
                        {sudo_prefix} chown root:root /usr/local/bin/node_exporter && \
                        /usr/local/bin/node_exporter --version
                    """
                    sudo_result = self.connector.execute_command(sudo_cmd)
                    if sudo_result.get("success") or "version" in sudo_result.get("stdout", "").lower():
                        return {"success": True, "message": "Node Exporter binary kopyalandı (sudo ile)", "install_path": "/usr/local/bin/node_exporter"}
                    else:
                        sudo_error = sudo_result.get('stderr', sudo_result.get('stdout', 'Bilinmeyen hata'))
                        if "password is required" in sudo_error or "sudo: a password is required" in sudo_error or "not in the sudoers" in sudo_error:
                            return {"success": False, "error": f"Kullanıcı '{self.connector.username}' sudo yetkisine sahip değil. Root kullanıcı veya sudo yetkisi olan kullanıcı kullanın. Hata: {sudo_error}"}
                        return {"success": False, "error": f"Kurulum hatası: {sudo_error}"}
                return {"success": False, "error": f"Kurulum hatası: {error_msg}"}
                
        except Exception as e:
            logger.error(f"Install hatası: {e}", exc_info=True)
            return {"success": False, "error": f"Kurulum hatası: {str(e)}"}
    
    def _create_systemd_service(self) -> Dict[str, Any]:
        """Systemd servisi oluştur (root veya user service)"""
        try:
            is_root = self.connector.username == "root"
            
            # Install path'i belirle
            install_path_check = self.connector.execute_command("which node_exporter 2>/dev/null || echo '/usr/local/bin/node_exporter'")
            install_path = install_path_check.get("stdout", "/usr/local/bin/node_exporter").strip()
            
            # Install path yoksa kullanıcı dizinini kontrol et
            if not install_path or install_path == "/usr/local/bin/node_exporter":
                home_check = self.connector.execute_command("echo $HOME")
                user_home = home_check.get("stdout", f"/home/{self.connector.username}").strip() or f"/home/{self.connector.username}"
                install_path = f"{user_home}/bin/node_exporter"
                # Binary var mı kontrol et
                bin_check = self.connector.execute_command(f"test -f {install_path} && echo 'exists' || echo 'not found'")
                if "not found" in bin_check.get("stdout", "").lower():
                    install_path = "/usr/local/bin/node_exporter"  # Fallback
            
            if is_root:
                # Root kullanıcı - systemd service
                service_content = f"""[Unit]
Description=Node Exporter
After=network.target

[Service]
Type=simple
User=root
ExecStart={install_path}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
"""
                service_file = "/etc/systemd/system/node_exporter.service"
                create_cmd = f"""
                    tee {service_file} > /dev/null << 'EOFSERVICE'
{service_content}
EOFSERVICE
                    systemctl daemon-reload
                """
            else:
                # Kullanıcı service (systemd user service)
                service_content = f"""[Unit]
Description=Node Exporter
After=network.target

[Service]
Type=simple
ExecStart={install_path}
Restart=always
RestartSec=5

[Install]
WantedBy=default.target
"""
                home_check = self.connector.execute_command("echo $HOME")
                user_home = home_check.get("stdout", f"/home/{self.connector.username}").strip() or f"/home/{self.connector.username}"
                systemd_user_dir = f"{user_home}/.config/systemd/user"
                service_file = f"{systemd_user_dir}/node_exporter.service"
                
                create_cmd = f"""
                    mkdir -p {systemd_user_dir} && \
                    tee {service_file} > /dev/null << 'EOFSERVICE'
{service_content}
EOFSERVICE
                    systemctl --user daemon-reload
                """
            
            result = self.connector.execute_command(create_cmd)
            if result.get("success"):
                return {"success": True, "message": f"Systemd servisi oluşturuldu ({'root' if is_root else 'user'})", "service_file": service_file, "install_path": install_path}
            else:
                error_msg = result.get('stderr', result.get('stdout', 'Bilinmeyen hata'))
                # Sudo denemesi
                if not is_root:
                    password = self.connector.sudo_password or ""
                    sudo_prefix = f"echo '{password}' | sudo -S" if password else "sudo"
                    sudo_cmd = f"""
                        {sudo_prefix} tee /etc/systemd/system/node_exporter.service > /dev/null << 'EOFSERVICE'
[Unit]
Description=Node Exporter
After=network.target

[Service]
Type=simple
User=root
ExecStart={install_path}
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOFSERVICE
                        {sudo_prefix} systemctl daemon-reload
                    """
                    sudo_result = self.connector.execute_command(sudo_cmd)
                    if sudo_result.get("success"):
                        return {"success": True, "message": "Systemd servisi oluşturuldu (sudo ile)", "service_file": "/etc/systemd/system/node_exporter.service", "install_path": install_path}
                    else:
                        sudo_error = sudo_result.get('stderr', sudo_result.get('stdout', 'Bilinmeyen hata'))
                        if "password is required" in sudo_error or "sudo: a password is required" in sudo_error or "not in the sudoers" in sudo_error:
                            return {"success": False, "error": f"Kullanıcı '{self.connector.username}' sudo yetkisine sahip değil. Root kullanıcı veya sudo yetkisi olan kullanıcı kullanın. Hata: {sudo_error}"}
                        return {"success": False, "error": f"Servis oluşturma hatası: {sudo_error}"}
                return {"success": False, "error": f"Servis oluşturma hatası: {error_msg}"}
                
        except Exception as e:
            logger.error(f"Service creation hatası: {e}", exc_info=True)
            return {"success": False, "error": f"Servis oluşturma hatası: {str(e)}"}
    
    def _start_service(self) -> Dict[str, Any]:
        """Servisi başlat ve enable et (root veya user service)"""
        try:
            is_root = self.connector.username == "root"
            
            if is_root:
                # Root kullanıcı - systemd service
                start_cmd = """
                    systemctl enable node_exporter && \
                    systemctl start node_exporter && \
                    systemctl status node_exporter --no-pager | head -5
                """
            else:
                # Kullanıcı service - önce systemctl --user dene
                start_cmd = """
                    systemctl --user enable node_exporter && \
                    systemctl --user start node_exporter && \
                    systemctl --user status node_exporter --no-pager | head -5
                """
            
            result = self.connector.execute_command(start_cmd)
            stdout_text = result.get("stdout", "").lower()
            if result.get("success") or "active (running)" in stdout_text or "enabled" in stdout_text:
                return {"success": True, "message": f"Servis başlatıldı ({'root' if is_root else 'user'})"}
            else:
                error_msg = result.get('stderr', result.get('stdout', 'Bilinmeyen hata'))
                # Sudo denemesi
                if not is_root:
                    password = self.connector.sudo_password or ""
                    sudo_prefix = f"echo '{password}' | sudo -S" if password else "sudo"
                    sudo_cmd = f"""
                        {sudo_prefix} systemctl enable node_exporter && \
                        {sudo_prefix} systemctl start node_exporter && \
                        {sudo_prefix} systemctl status node_exporter --no-pager | head -5
                    """
                    sudo_result = self.connector.execute_command(sudo_cmd)
                    if sudo_result.get("success") or "active (running)" in sudo_result.get("stdout", "").lower():
                        return {"success": True, "message": "Servis başlatıldı (sudo ile)"}
                    else:
                        sudo_error = sudo_result.get('stderr', sudo_result.get('stdout', 'Bilinmeyen hata'))
                        if "password is required" in sudo_error or "sudo: a password is required" in sudo_error or "not in the sudoers" in sudo_error:
                            # Son çare: nohup ile manuel başlat
                            return self._start_manual()
                        return {"success": False, "error": f"Servis başlatma hatası: {sudo_error}"}
                return {"success": False, "error": f"Servis başlatma hatası: {error_msg}"}
                
        except Exception as e:
            logger.error(f"Service start hatası: {e}", exc_info=True)
            return {"success": False, "error": f"Servis başlatma hatası: {str(e)}"}
    
    def _start_manual(self) -> Dict[str, Any]:
        """Node Exporter'ı manuel olarak başlat (nohup ile)"""
        try:
            # Install path'i bul
            which_result = self.connector.execute_command("which node_exporter 2>/dev/null || echo ''")
            install_path = which_result.get("stdout", "").strip()
            if not install_path:
                home_check = self.connector.execute_command("echo $HOME")
                user_home = home_check.get("stdout", f"/home/{self.connector.username}").strip() or f"/home/{self.connector.username}"
                install_path = f"{user_home}/bin/node_exporter"
            
            # Mevcut process'i durdur (varsa)
            self.connector.execute_command("pkill -f node_exporter || true")
            
            # nohup ile başlat
            start_cmd = f"""
                nohup {install_path} --web.listen-address=:{self.NODE_EXPORTER_PORT} > /tmp/node_exporter.log 2>&1 &
                sleep 2
                pgrep -f node_exporter && echo "started" || echo "failed"
            """
            
            result = self.connector.execute_command(start_cmd)
            if result.get("success") and "started" in result.get("stdout", "").lower():
                return {"success": True, "message": "Node Exporter manuel olarak başlatıldı (nohup)", "manual": True}
            else:
                return {"success": False, "error": f"Manuel başlatma hatası: {result.get('stderr', 'Bilinmeyen hata')}"}
                
        except Exception as e:
            logger.error(f"Manual start hatası: {e}", exc_info=True)
            return {"success": False, "error": f"Manuel başlatma hatası: {str(e)}"}
    
    def check_status(self) -> Dict[str, Any]:
        """Node Exporter durumunu kontrol et"""
        try:
            # Sudo şifresini al (varsa)
            password = self.connector.password or ""
            sudo_prefix = f"echo '{password}' | sudo -S" if password else "sudo"
            
            # Service durumu (sudo olmadan da deneyelim)
            status_cmd = f"{sudo_prefix} systemctl is-active node_exporter 2>/dev/null || systemctl is-active node_exporter 2>/dev/null || echo 'inactive'"
            status_result = self.connector.execute_command(status_cmd)
            
            is_running = status_result.get("success") and "active" in status_result.get("stdout", "").lower()
            
            # Binary varlığı (farklı konumları kontrol et)
            binary_check = self.connector.execute_command("which node_exporter 2>/dev/null || test -f /usr/local/bin/node_exporter && echo 'exists' || test -f ~/bin/node_exporter && echo 'exists' || echo 'not found'")
            is_installed = binary_check.get("success") and "exists" in binary_check.get("stdout", "").lower()
            
            # Port kontrolü (sudo olmadan da deneyelim)
            port_check = self.connector.execute_command(f"{sudo_prefix} netstat -tlnp 2>/dev/null | grep {self.NODE_EXPORTER_PORT} || netstat -tln 2>/dev/null | grep {self.NODE_EXPORTER_PORT} || ss -tln 2>/dev/null | grep {self.NODE_EXPORTER_PORT} || echo 'not listening'")
            is_listening = port_check.get("success") and "not listening" not in port_check.get("stdout", "").lower() and f":{self.NODE_EXPORTER_PORT}" in port_check.get("stdout", "")
            
            return {
                "installed": is_installed,
                "running": is_running and is_listening,
                "service_active": is_running,
                "port_listening": is_listening,
                "port": self.NODE_EXPORTER_PORT
            }
            
        except Exception as e:
            logger.error(f"Status check hatası: {e}", exc_info=True)
            return {"installed": False, "running": False, "error": str(e)}
    
    def uninstall(self) -> Dict[str, Any]:
        """Node Exporter'ı kaldır"""
        try:
            # Servisi durdur ve kaldır
            uninstall_cmd = """
                sudo systemctl stop node_exporter 2>/dev/null || true && \
                sudo systemctl disable node_exporter 2>/dev/null || true && \
                sudo rm -f /etc/systemd/system/node_exporter.service && \
                sudo systemctl daemon-reload && \
                sudo rm -f /usr/local/bin/node_exporter && \
                echo "Node Exporter kaldırıldı"
            """
            
            result = self.connector.execute_command(uninstall_cmd)
            if result.get("success"):
                return {"success": True, "message": "Node Exporter başarıyla kaldırıldı"}
            else:
                return {"success": False, "error": f"Kaldırma hatası: {result.get('stderr', 'Bilinmeyen hata')}"}
                
        except Exception as e:
            logger.error(f"Uninstall hatası: {e}", exc_info=True)
            return {"success": False, "error": f"Kaldırma hatası: {str(e)}"}
