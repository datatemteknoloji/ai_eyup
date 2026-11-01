"""Unified sohbette Automic iş sinyali (Adım 6c-2).

«Şu an kaç iş çalışıyor?», «Hangi job'lar hata verdi?» gibi platform adı
geçmeyen iş sorularını Automic modülüne yönlendirir. OpenShift Job/CronJob,
Linux cron, «iş yükü», «işlemci», «işletim sistemi», «iş sahibi» gibi
kullanımlar Automic sayılmaz.
"""
from __future__ import annotations

import re
from typing import Optional

_OBJECT_RE = re.compile(
    r"(?<![a-z0-9_])(?:jobs|jobp|jobf|jobg|jsch|evnt|scri|cale|prpt)\.[a-z0-9_.$#@\-]+",
    re.IGNORECASE,
)

_JOB_RE = re.compile(
    r"(?<![a-z0-9_])job(?:s|lar|ler|ları|leri|ların|lerin|lardan|lerden|larda|lerde|un|u)?(?![a-z0-9_])"
    r"|(?<![a-z0-9_])job['’](?:lar|ler|ları|leri|ların|lerin|un|u|ı|i)",
    re.IGNORECASE,
)

_IS_RE = re.compile(
    r"(?<![a-zçğıöşü0-9_])iş(?:ler|leri|lerin|lerden|lerde|in|i)?(?![a-zçğıöşü0-9_])",
    re.IGNORECASE,
)

_IS_NOT_JOB = (
    "iş yük", "iş sahib", "iş gün", "iş birim", "iş ortağ", "iş sürekliliğ",
    "iş kritik", "iş birliğ", "iş zekâ", "iş zeka", "iş analiz",
)

_EXEC_HINT = (
    "çalış", "calis", "hata", "başarısız", "basarisiz", "fail", "abend", "aktif",
    "bekle", "bekli", "bitti", "bitmedi", "tamamlan", "koştu", "kostu", "iptal", "takıl",
    "gecik", "sürdü", "süre", "uzun sür", "kaç kez", "en son", "son çalış",
    "iş akış", "workflow",
)

_OTHER_PLATFORM = (
    "openshift", "ocp", "kubernetes", "k8s", "kube", "pod", "namespace", "cronjob",
    "cron", "crontab", "linux", "windows", "sunucu", "server", "vcenter", "esxi",
    "vmware", "systemd", "systemctl", "zamanlanmış görev", "task scheduler",
    "scheduled task", "exadata", "veeam", "yedekleme", "backup",
)

_VM_RE = re.compile(r"(?<![a-z0-9_])vm(?:s|ler|leri|lerin|lerde|in)?(?![a-z0-9_])|sanal makine", re.I)


def _lower_tr(text: str) -> str:
    return (text or "").replace("I", "ı").replace("İ", "i").lower()


def automic_signal(message: str) -> Optional[str]:
    """Automic sinyali varsa nedenini döndür (`object`, `job_word`, `is_word`), yoksa None."""
    ml = _lower_tr(message)
    if not ml.strip():
        return None
    if _OBJECT_RE.search(ml):
        return "object"
    if any(p in ml for p in _OTHER_PLATFORM) or _VM_RE.search(ml):
        return None
    if not any(h in ml for h in _EXEC_HINT):
        return None
    if _JOB_RE.search(ml):
        return "job_word"
    if "iş akış" in ml or "workflow" in ml:
        return "is_word"
    stripped = ml
    for p in _IS_NOT_JOB:
        stripped = stripped.replace(p, " ")
    if _IS_RE.search(stripped):
        return "is_word"
    return None
