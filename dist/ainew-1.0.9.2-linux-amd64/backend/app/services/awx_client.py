"""
AWX REST API Client - Job Template çalıştırma, durum takibi
"""
import logging
import requests
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class AWXClient:
    """AWX REST API wrapper"""
    
    def __init__(self, base_url: str, username: str, password: str, verify_ssl: bool = True):
        """
        base_url: https://awx.example.com
        username: AWX kullanıcı adı
        password: AWX şifresi veya token
        """
        self.base_url = base_url.rstrip("/")
        self.auth = (username, password)
        self.verify_ssl = verify_ssl
        self.session = requests.Session()
        self.session.auth = self.auth
        self.session.verify = self.verify_ssl
    
    def _get(self, endpoint: str) -> Dict[str, Any]:
        """GET request"""
        url = f"{self.base_url}/api/v2{endpoint}"
        response = self.session.get(url, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def _post(self, endpoint: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """POST request"""
        url = f"{self.base_url}/api/v2{endpoint}"
        response = self.session.post(url, json=data, timeout=30)
        response.raise_for_status()
        return response.json()
    
    def list_job_templates(self) -> List[Dict[str, Any]]:
        """Job template listesi"""
        try:
            result = self._get("/job_templates/")
            return result.get("results", [])
        except Exception as e:
            logger.error(f"AWX list job templates error: {e}")
            return []
    
    def launch_job_template(
        self,
        template_id: int,
        inventory_id: Optional[int] = None,
        extra_vars: Optional[Dict[str, Any]] = None,
        limit: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Job template başlat.
        template_id: AWX'teki job template ID
        inventory_id: Farklı inventory kullanmak için
        extra_vars: Playbook'a extra değişkenler (JSON)
        limit: Belirli hostlara sınırla (örn: "server1,server2")
        
        Dönüş: {"id": job_id, "status": "pending", "url": "/api/v2/jobs/123/"}
        """
        try:
            data = {}
            if inventory_id:
                data["inventory"] = inventory_id
            if extra_vars:
                data["extra_vars"] = extra_vars
            if limit:
                data["limit"] = limit
            
            result = self._post(f"/job_templates/{template_id}/launch/", data)
            return {
                "success": True,
                "job_id": result.get("id"),
                "status": result.get("status"),
                "url": result.get("url"),
                "name": result.get("name")
            }
        except Exception as e:
            logger.error(f"AWX launch job error: {e}")
            return {"success": False, "error": str(e)}
    
    def get_job_status(self, job_id: int) -> Dict[str, Any]:
        """
        Job durumu sorgula.
        Dönüş: {"id": int, "status": "pending|running|successful|failed", "stdout": str, ...}
        """
        try:
            result = self._get(f"/jobs/{job_id}/")
            return {
                "id": result.get("id"),
                "name": result.get("name"),
                "status": result.get("status"),
                "started": result.get("started"),
                "finished": result.get("finished"),
                "elapsed": result.get("elapsed"),
                "failed": result.get("failed"),
                "summary_fields": result.get("summary_fields", {})
            }
        except Exception as e:
            logger.error(f"AWX get job status error: {e}")
            return {"id": job_id, "status": "error", "error": str(e)}
    
    def get_job_stdout(self, job_id: int) -> str:
        """Job çıktısı (stdout) al"""
        try:
            result = self._get(f"/jobs/{job_id}/stdout/?format=txt")
            # format=txt olduğunda response plaintext
            return result if isinstance(result, str) else result.get("content", "")
        except Exception as e:
            logger.error(f"AWX get job stdout error: {e}")
            return f"Hata: {e}"
    
    def cancel_job(self, job_id: int) -> Dict[str, Any]:
        """Çalışan job'ı iptal et"""
        try:
            result = self._post(f"/jobs/{job_id}/cancel/", {})
            return {"success": True, "status": result.get("status")}
        except Exception as e:
            logger.error(f"AWX cancel job error: {e}")
            return {"success": False, "error": str(e)}
    
    def list_inventories(self) -> List[Dict[str, Any]]:
        """AWX inventory listesi"""
        try:
            result = self._get("/inventories/")
            return result.get("results", [])
        except Exception as e:
            logger.error(f"AWX list inventories error: {e}")
            return []
    
    def create_inventory(self, name: str, organization_id: int = 1) -> Dict[str, Any]:
        """Yeni inventory oluştur"""
        try:
            data = {"name": name, "organization": organization_id}
            result = self._post("/inventories/", data)
            return {"success": True, "id": result.get("id"), "name": result.get("name")}
        except Exception as e:
            logger.error(f"AWX create inventory error: {e}")
            return {"success": False, "error": str(e)}
    
    def add_host_to_inventory(self, inventory_id: int, hostname: str, variables: Optional[Dict] = None) -> Dict[str, Any]:
        """Inventory'ye host ekle"""
        try:
            data = {"name": hostname, "inventory": inventory_id}
            if variables:
                data["variables"] = variables
            result = self._post("/hosts/", data)
            return {"success": True, "id": result.get("id"), "name": result.get("name")}
        except Exception as e:
            logger.error(f"AWX add host error: {e}")
            return {"success": False, "error": str(e)}
