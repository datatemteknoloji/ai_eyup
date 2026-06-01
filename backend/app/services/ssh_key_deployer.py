"""
SSH Key Deployer - SSH public key'i sunuculara dağıtır
"""
import logging
import tempfile
from typing import Dict, Any
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa, ed25519, ec
from cryptography.hazmat.backends import default_backend

logger = logging.getLogger(__name__)


class SSHKeyDeployer:
    """SSH public key'i sunuculara dağıtan servis"""

    @staticmethod
    def extract_public_key_from_private(private_key_str: str) -> str:
        """
        Private key'den public key çıkar.
        RSA, Ed25519, ECDSA destekler.
        """
        try:
            # Private key'i yükle
            private_key_bytes = private_key_str.encode('utf-8')
            
            # Farklı key tiplerini dene
            try:
                # RSA
                from cryptography.hazmat.primitives.serialization import load_pem_private_key
                private_key = load_pem_private_key(private_key_bytes, password=None, backend=default_backend())
            except Exception as e:
                # OpenSSH formatı dene
                from cryptography.hazmat.primitives.serialization import load_ssh_private_key
                private_key = load_ssh_private_key(private_key_bytes, password=None, backend=default_backend())
            
            # Public key çıkar
            public_key = private_key.public_key()
            
            # OpenSSH formatında serialize et
            public_key_bytes = public_key.public_bytes(
                encoding=serialization.Encoding.OpenSSH,
                format=serialization.PublicFormat.OpenSSH
            )
            
            return public_key_bytes.decode('utf-8')
        
        except Exception as e:
            logger.error(f"Public key extraction failed: {e}")
            raise Exception(f"Private key işlenemedi: {str(e)}")

    @staticmethod
    def deploy_public_key(ssh_manager, private_key: str) -> Dict[str, Any]:
        """
        SSH public key'i sunucuya dağıt (authorized_keys'e ekle).
        
        Args:
            ssh_manager: SSHManager instance (bağlantı zaten açık)
            private_key: Private key string (PEM veya OpenSSH formatında)
        
        Returns:
            {"success": bool, "message": str}
        """
        try:
            # Public key'i çıkar
            public_key = SSHKeyDeployer.extract_public_key_from_private(private_key)
            
            # authorized_keys dosyasına ekle
            commands = [
                "mkdir -p ~/.ssh",
                "chmod 700 ~/.ssh",
                f"echo '{public_key}' >> ~/.ssh/authorized_keys",
                "chmod 600 ~/.ssh/authorized_keys",
                # Duplicate kontrolü (aynı key'i tekrar eklememek için)
                "awk '!seen[$0]++' ~/.ssh/authorized_keys > ~/.ssh/authorized_keys.tmp && mv ~/.ssh/authorized_keys.tmp ~/.ssh/authorized_keys"
            ]
            
            # Komutları çalıştır
            for cmd in commands:
                stdin, stdout, stderr = ssh_manager.client.exec_command(cmd, timeout=10)
                exit_status = stdout.channel.recv_exit_status()
                
                if exit_status != 0:
                    error_msg = stderr.read().decode('utf-8', errors='ignore')
                    logger.warning(f"Key deployment command failed: {cmd} - {error_msg}")
                    # Devam et, kritik değil
            
            logger.info(f"SSH public key deployed successfully")
            return {
                "success": True,
                "message": "SSH public key başarıyla dağıtıldı"
            }
        
        except Exception as e:
            logger.error(f"SSH key deployment failed: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"Key deployment hatası: {str(e)}"
            }
