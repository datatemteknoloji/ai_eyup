"""Platform hiyerarşileri ve tam yol gösterimi (H.0).

  vCenter  : instance → Datacenter → Cluster → (Resource Pool) → Host;   datastore ↔ host erişimi
  OLVM     : Manager (instance) → Data Center → Cluster → Host;           Storage Domain data center seviyesinde
  OpenShift: Cluster (instance) → node rolü / MachineConfigPool → Node;   StorageClass / PV

Hesap birimi CLUSTER'dır (HA, N+1, overcommit, eşikler, tükenme). Datacenter / instance / platform seviyeleri
yalnız raporlama için toplanır; boş kapasite bu seviyelerde HAVUZLANMAZ. Tüm kimlikler instance kimliğini içerir:
farklı instance'lardaki aynı isimli cluster'lar karışmaz.
"""
from __future__ import annotations

from typing import Any, Optional, Tuple

UNKNOWN_LEVEL = "?"


def cluster_key(instance_id: Any, cluster: Optional[str]) -> Tuple[Any, str]:
    """Cluster kimliği: (instance_id, cluster adı). Yalnız ad kullanmak iki vCenter'da çakışır."""
    return (instance_id, cluster or "(cluster yok)")


def path_str(instance: Optional[str], level2: Optional[str], cluster: Optional[str], host: Optional[str] = None) -> str:
    """`vc01 / DC-IST / CL-PROD-01 / esx03`, `olvm01 / DC1 / Cluster-A / host05`, `ocp-prod / worker / node-07`.

    `level2`: vCenter/OLVM'de datacenter, OpenShift'te node rolü. Okunamadıysa "?" (uydurma ad yazılmaz).
    OpenShift'te cluster = instance olduğundan `cluster=None` verilirse o seviye atlanır.
    """
    parts = [instance or UNKNOWN_LEVEL, level2 or UNKNOWN_LEVEL]
    if cluster is not None:
        parts.append(cluster)
    if host:
        parts.append(host)
    return " / ".join(parts)
