"""Hypervisor silindiğinde ilişkili VM envanterinin de temizlenmesi.

`servers.hypervisor_id` FK'si ON DELETE SET NULL olduğu için, bir hypervisor
silindiğinde ondan senkronize edilmiş VM kayıtları veritabanında "yetim"
(orphan) olarak kalır — ne hypervisor'a bağlıdır ne de gerçek bir envanter
kaydı olarak anlamlıdır. Kullanıcı "entegrasyon silinince ortam temizlensin"
istediği için, hypervisor silme işlemiyle birlikte bu VM'ler de kaldırılır.
Level 1 (Dropt) kopyası da aynı IP / ainew:{id} iziyle silinir.
"""
from __future__ import annotations

import logging
from typing import List

from sqlalchemy.orm import Session

from app.models.server import Server
from app.models.infrastructure_report import BusinessServiceMap

logger = logging.getLogger(__name__)


def delete_servers_cascade(db: Session, server_ids: List[int]) -> int:
    """Verilen sunucu ID'lerini, FK kısıtlaması olan (cascade tanımlı olmayan)
    ilişkili kayıtları önce temizleyerek siler. Diğer tablolar (events, alerts,
    baseline_metrics, metrics, vm_snapshots vb.) DB seviyesinde ON DELETE CASCADE
    ile otomatik temizlenir; exadata_nodes ve agent_actions SET NULL ile korunur.
    """
    if not server_ids:
        return 0

    rows = db.query(Server.id, Server.ip_address).filter(Server.id.in_(server_ids)).all()
    ainew_ids = [int(r[0]) for r in rows]
    ips = [(r[1] or "").strip() for r in rows if (r[1] or "").strip()]

    db.query(BusinessServiceMap).filter(BusinessServiceMap.server_id.in_(server_ids)).delete(
        synchronize_session=False
    )

    deleted = db.query(Server).filter(Server.id.in_(server_ids)).delete(synchronize_session=False)
    db.commit()

    try:
        from app.services.level1_inventory import best_effort_delete_dropt_hosts

        pruned = best_effort_delete_dropt_hosts(
            ainew_server_ids=ainew_ids,
            ips=ips,
            actor_username="hypervisor-delete",
        )
        if pruned:
            logger.info("Level 1 Dropt prune after ainew cascade: %s", pruned)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Level 1 Dropt prune skipped: %s", exc)

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
