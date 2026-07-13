"""Hypervisor silindiğinde ilişkili VM envanterinin de temizlenmesi.

`servers.hypervisor_id` FK'si ON DELETE SET NULL olduğu için, bir hypervisor
silindiğinde ondan senkronize edilmiş VM kayıtları veritabanında "yetim"
(orphan) olarak kalır — ne hypervisor'a bağlıdır ne de gerçek bir envanter
kaydı olarak anlamlıdır. Kullanıcı "entegrasyon silinince ortam temizlensin"
istediği için, hypervisor silme işlemiyle birlikte bu VM'ler de kaldırılır.
"""
from __future__ import annotations

from typing import List

from sqlalchemy.orm import Session

from app.models.server import Server
from app.models.infrastructure_report import BusinessServiceMap


def delete_servers_cascade(db: Session, server_ids: List[int]) -> int:
    """Verilen sunucu ID'lerini, FK kısıtlaması olan (cascade tanımlı olmayan)
    ilişkili kayıtları önce temizleyerek siler. Diğer tablolar (events, alerts,
    baseline_metrics, metrics, vm_snapshots vb.) DB seviyesinde ON DELETE CASCADE
    ile otomatik temizlenir; exadata_nodes ve agent_actions SET NULL ile korunur.
    """
    if not server_ids:
        return 0

    db.query(BusinessServiceMap).filter(BusinessServiceMap.server_id.in_(server_ids)).delete(
        synchronize_session=False
    )

    deleted = db.query(Server).filter(Server.id.in_(server_ids)).delete(synchronize_session=False)
    db.commit()
    return deleted


def delete_orphaned_hypervisor_vms(db: Session) -> int:
    """Daha önce silinmiş hypervisor'lardan kalan, hypervisor_id'si NULL olan
    ama hâlâ hypervisor senkron izleri taşıyan (hypervisor_vm_id dolu) VM
    kayıtlarını temizler — geçmişte yapılan hypervisor silmelerinin bakiyesi."""
    orphan_ids = [
        r[0]
        for r in db.query(Server.id)
        .filter(Server.hypervisor_id.is_(None), Server.hypervisor_vm_id.isnot(None))
        .all()
    ]
    return delete_servers_cascade(db, orphan_ids)
