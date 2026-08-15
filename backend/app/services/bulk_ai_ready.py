"""
Bulk AI Ready Service - Tüm sunucuları tarayıp SSH bağlantısı yapılabilenleri AI Ready yapar.
3000–4000 sunucu ölçeği için paralel SSH testi kullanır.
"""
import logging
from typing import Dict, List, Optional

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.server import Server
from app.models.credential import GlobalCredential
from app.services.platform_scope import is_linux_server
from app.services.ssh_credentials import resolve_ssh_creds
from app.services.bulk_concurrency import bulk_ssh_workers

logger = logging.getLogger(__name__)


class BulkAIReadyService:
    """Toplu AI Ready işlemleri"""

    @staticmethod
    def scan_and_mark_ai_ready(db: Session, credential_id: Optional[int] = None) -> Dict:
        """
        Tüm sunucuları tara ve SSH bağlantısı yapılabilenleri AI Ready yap.
        SSH testleri BULK_SSH_WORKERS (varsayılan 25) paralel worker ile yapılır.
        Kimlik: sunucu connection_config → yoksa seçilen/global credential (SSH butonu ile aynı).
        """
        if credential_id:
            credential = db.query(GlobalCredential).filter(
                GlobalCredential.id == credential_id
            ).first()
        else:
            credential = db.query(GlobalCredential).filter(
                GlobalCredential.is_default == True  # noqa: E712
            ).first()

        if not credential:
            return {
                "total_servers": 0,
                "scanned": 0,
                "ai_ready_marked": 0,
                "failed": 0,
                "error": "Global credential bulunamadı. Lütfen önce Settings'ten credential tanımlayın.",
            }

        # SSH / AI Ready yalnızca Linux — Windows WinRM ile ayrı test edilir
        servers = [
            s for s in db.query(Server).filter(
                Server.ip_address != None,  # noqa: E711
                Server.ip_address != "",
            ).all()
            if is_linux_server(s)
        ]

        snapshots = []
        for s in servers:
            ip = (s.ip_address or "").strip()
            if not ip:
                continue
            creds = resolve_ssh_creds(s, global_cred=credential, ip=ip, name=s.name)
            if not creds.get("has_secret"):
                continue
            snapshots.append({
                "id": s.id,
                "name": s.name,
                "ip": ip,
                "username": creds["username"],
                "password": creds["password"],
                "private_key": creds["private_key"],
                "port": creds["port"],
                "sudo_password": creds["sudo_password"],
            })

        from app.services.ai_ready_probe import probe_linux_snapshots

        logger.info(
            "🔍 %s sunucu taranacak (credential: %s, TCP ön tarama + SSH)",
            len(snapshots),
            credential.name,
        )

        by_ok = probe_linux_snapshots(snapshots)
        test_rows: List[dict] = []
        for snap in snapshots:
            ok = bool(by_ok.get(snap["id"]))
            test_rows.append({
                "server_id": snap["id"],
                "server_name": snap["name"],
                "ip_address": snap["ip"],
                "ok": ok,
                "message": "SSH bağlantısı başarılı" if ok else "SSH bağlantısı başarısız",
                "details": {},
            })

        by_id = {s.id: s for s in servers}
        marked = failed = 0
        detail_results = []

        for row in test_rows:
            server = by_id.get(row["server_id"])
            if not server:
                continue
            if row["ok"]:
                if not server.connection_config:
                    server.connection_config = {}
                # Başarılı olanlara global credential yaz (SSH butonu aynı kaynağı görsün)
                server.connection_config.update({
                    "username": credential.username,
                    "password": credential.password,
                    "private_key": credential.private_key,
                    "port": credential.port or 22,
                    "sudo_password": credential.sudo_password,
                })
                flag_modified(server, "connection_config")
                server.ai_ready = True
                marked += 1
                detail_results.append({
                    "server_id": row["server_id"],
                    "server_name": row["server_name"],
                    "ip_address": row["ip_address"],
                    "status": "success",
                    "message": f"✅ {row['message']}",
                    "details": row.get("details", {}),
                })
            else:
                failed += 1
                detail_results.append({
                    "server_id": row["server_id"],
                    "server_name": row["server_name"],
                    "ip_address": row["ip_address"],
                    "status": "failed",
                    "message": f"❌ {row['message']}",
                    "details": row.get("details", ""),
                })

        db.commit()
        logger.info("🎉 Tarama tamamlandı: %s/%s sunucu AI Ready", marked, len(snapshots))

        return {
            "total_servers": len(servers),
            "scanned": len(snapshots),
            "ai_ready_marked": marked,
            "failed": failed,
            "workers": bulk_ssh_workers(),
            "results": detail_results,
        }
