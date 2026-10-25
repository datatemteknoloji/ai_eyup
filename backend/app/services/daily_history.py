"""Ham saklama penceresinden uzun geçmiş günlük özetten okunur.

Ham süreler değişmez. Günlük continuous aggregate 400 gün tutulur.
Aynı güne düşen ham tick'ler bir örnek sayılmaz; örnek = bir gün.
"""
from __future__ import annotations

RAW_RETENTION_DAYS = {
    "metric_data": 30,
    "hypervisor_host_metrics": 90,
    "virt_datastore_metrics": 180,
    "ocp_resource_metrics": 30,
}

DAILY_KEEP_DAYS = 400


def reads_daily_summary(source: str, days: int) -> bool:
    """İstenen pencere ham saklamadan uzunsa günlük özet kullanılır."""
    limit = RAW_RETENTION_DAYS[source]
    return int(days) > limit
