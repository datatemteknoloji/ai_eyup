"""OpenShift cluster → openshift_virt hypervisor + Server envanter köprüsü.

OCP kümesi `/openshift/vms` üzerinden canlı KubeVirt listesi verir; Linux/Virt
modülleri ise `servers` tablosundan beslenir. Bu servis cluster kimliğiyle
yönetilen bir `openshift_virt` hypervisor kaydı oluşturur/günceller ve mevcut
`sync_hypervisor_vms` yolunu kullanarak VM'leri `servers`'a yazar.

Manuel ayrı hypervisor kaydı gerekmez — cluster sync yeterlidir.
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional
from urllib.parse import urlparse

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.openshift import OpenShiftCluster
from app.services.hypervisor_credentials import plain, seal_connection_secrets, sealed

logger = logging.getLogger(__name__)

META_CLUSTER_ID = "openshift_cluster_id"
META_MANAGED = "managed_by"
MANAGED_BY = "openshift_cluster_sync"


def _api_url(cluster: OpenShiftCluster) -> str:
    cc = cluster.connection_config or {}
    return (cc.get("api_url") or cluster.api_url or "").strip()


def _hostname_and_ip(api_url: str) -> tuple[str, str]:
    host = api_url
    try:
        parsed = urlparse(api_url if "://" in api_url else f"https://{api_url}")
        host = parsed.hostname or api_url
    except Exception:
        host = api_url
    # ip_address kolonu 45 karakter; URL tamamını hostname'de tut
    return (api_url or host or "openshift")[:255], (host or api_url or "openshift")[:45]


def _hv_name(cluster: OpenShiftCluster) -> str:
    base = (cluster.name or "OpenShift").strip() or "OpenShift"
    return f"{base} (OpenShift Virt)"[:255]


def find_managed_virt_hypervisor(db: Session, cluster: OpenShiftCluster) -> Optional[Hypervisor]:
    """Cluster'a bağlı yönetilen openshift_virt kaydını bul."""
    hvs = (
        db.query(Hypervisor)
        .filter(Hypervisor.hypervisor_type == HypervisorType.OPENSHIFT_VIRT)
        .all()
    )
    for hv in hvs:
        meta = hv.meta_data or {}
        if meta.get(META_CLUSTER_ID) == cluster.id:
            return hv
    # Eski / elle eklenmiş kayıt: aynı API URL
    api = _api_url(cluster).rstrip("/")
    if not api:
        return None
    for hv in hvs:
        cc = hv.connection_config or {}
        hv_api = (cc.get("api_url") or hv.hostname or "").rstrip("/")
        if hv_api and hv_api == api:
            return hv
    return None


def ensure_virt_hypervisor_from_cluster(db: Session, cluster: OpenShiftCluster) -> Hypervisor:
    """Cluster kimliğiyle openshift_virt Hypervisor oluştur veya kimliği güncelle."""
    api_url = _api_url(cluster)
    if not api_url:
        raise ValueError(f"OpenShift cluster {cluster.id} için api_url yok")

    cc_src = dict(cluster.connection_config or {})
    token = plain(cc_src.get("token") or "")
    username = (cc_src.get("username") or "").strip()
    password = plain(cc_src.get("password") or "")
    verify_ssl = bool(cc_src.get("verify_ssl", False))

    # Düz metin sırlarla connection_config kur; seal_connection_secrets tek sefer şifreler.
    # (Cluster'dan plain() sonrası tekrar sealed() + seal_connection_secrets çift şifreleme yapmaz.)
    hv_cc: Dict[str, Any] = {
        "api_url": api_url,
        "verify_ssl": verify_ssl,
    }
    username_val = "token"
    password_val = ""
    if token:
        hv_cc["token"] = token
        password_val = token
        username_val = "token"
    elif username and password:
        hv_cc["username"] = username
        hv_cc["password"] = password
        username_val = username
        password_val = password
    else:
        raise ValueError(
            f"OpenShift cluster '{cluster.name}' için token veya kullanıcı/şifre yok; "
            "KubeVirt VM envanteri atlandı"
        )

    hv_cc = seal_connection_secrets(hv_cc)
    password_val = sealed(password_val) or password_val
    hostname_val, ip_val = _hostname_and_ip(api_url)
    name = _hv_name(cluster)

    hv = find_managed_virt_hypervisor(db, cluster)
    if hv is None:
        # İsim çakışması — benzersizleştir
        existing_name = db.query(Hypervisor).filter(Hypervisor.name == name).first()
        if existing_name:
            name = f"{name} #{cluster.id}"[:255]
        hv = Hypervisor(
            name=name,
            hypervisor_type=HypervisorType.OPENSHIFT_VIRT,
            hostname=hostname_val,
            ip_address=ip_val,
            port=443,
            username=username_val,
            password=password_val,
            connection_config=hv_cc,
            status="ONLINE",
            meta_data={META_CLUSTER_ID: cluster.id, META_MANAGED: MANAGED_BY},
        )
        db.add(hv)
        db.flush()
        logger.info(
            "openshift_virt hypervisor oluşturuldu: id=%s cluster=%s (%s)",
            hv.id, cluster.id, cluster.name,
        )
    else:
        hv.hostname = hostname_val
        hv.ip_address = ip_val
        hv.username = username_val
        hv.password = password_val
        hv.connection_config = hv_cc
        meta = dict(hv.meta_data or {})
        meta[META_CLUSTER_ID] = cluster.id
        meta[META_MANAGED] = MANAGED_BY
        hv.meta_data = meta
        flag_modified(hv, "meta_data")
        flag_modified(hv, "connection_config")
        if not hv.name:
            hv.name = name
        db.flush()

    return hv


def sync_kubevirt_vms_into_servers(db: Session, cluster: OpenShiftCluster) -> Dict[str, Any]:
    """Cluster'daki KubeVirt VM'leri Server envanterine senkronize et.

    KubeVirt yoksa veya auth eksikse soft-fail (errors listesi); OCP sync'i bozmaz.
    """
    try:
        hv = ensure_virt_hypervisor_from_cluster(db, cluster)
    except ValueError as exc:
        logger.info("KubeVirt Server sync atlandı (cluster=%s): %s", cluster.name, exc)
        return {"skipped": True, "reason": str(exc), "synced_count": 0, "total_vms": 0, "errors": []}
    except Exception as exc:
        logger.exception("openshift_virt hypervisor ensure failed (cluster=%s)", cluster.name)
        return {
            "skipped": True,
            "reason": str(exc),
            "synced_count": 0,
            "total_vms": 0,
            "errors": [str(exc)],
        }

    from app.services.inventory_sync_service import sync_hypervisor_vms
    from app.services.platform_scope import invalidate_platform_id_cache

    try:
        result = sync_hypervisor_vms(db, hv, track_progress=False)
    except Exception as exc:
        logger.exception("KubeVirt VM sync failed (cluster=%s hv=%s)", cluster.name, hv.id)
        return {
            "skipped": False,
            "hypervisor_id": hv.id,
            "synced_count": 0,
            "total_vms": 0,
            "errors": [str(exc)],
        }

    try:
        invalidate_platform_id_cache()
    except Exception:
        pass

    out = {
        "skipped": False,
        "hypervisor_id": hv.id,
        "synced_count": result.get("synced_count", 0),
        "total_vms": result.get("total_vms", 0),
        "enriched_count": result.get("enriched_count", 0),
        "errors": result.get("errors") or [],
    }
    logger.info(
        "KubeVirt→servers sync cluster=%s hv=%s total=%s new=%s errors=%s",
        cluster.name, hv.id, out["total_vms"], out["synced_count"], out["errors"],
    )
    return out
