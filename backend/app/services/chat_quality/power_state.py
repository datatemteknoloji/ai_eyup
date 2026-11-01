"""Kanonik VM güç durumu sınıflandırması (Adım 5a).

Tek doğruluk kaynağı: ham `vm_power_state` değerini (VMware `poweredOn`, `POWERED_OFF`,
KubeVirt `Running`/`Stopped`, oVirt `up`/`down`, Proxmox `running`/`stopped`, Hyper-V `Running`/`Off`…)
beş sınıftan birine çevirir:

  on            çalışıyor
  off           kapalı
  suspended     askıya alınmış (VMware suspended, oVirt suspended, Hyper-V saved)
  transitional  geçiş/duraklama/hata (Starting, Migrating, Paused, CrashLoopBackOff, …) — açık/kapalı SAYILMAZ
  unknown       boş / tanınmayan değer — açık/kapalı SAYILMAZ

Kurallar: büyük/küçük harf, boşluk, `_` ve `-` yok sayılır (`POWERED_ON` = `poweredOn` = `powered on`).
Tanınmayan değer sessizce kapalı/açık yapılmaz; `summarize()` ham değerlerini adetleriyle döndürür
(cevapta "Diğer: 3 — X:2, Y:1").

Bu modül yalnız saf fonksiyonlar içerir (DB/ağ yok).
"""
from __future__ import annotations

import logging
import re
import threading
from collections import Counter
from typing import Any, Dict, Iterable, Optional

ON = "on"
OFF = "off"
SUSPENDED = "suspended"
TRANSITIONAL = "transitional"
UNKNOWN = "unknown"

CLASSES = (ON, OFF, SUSPENDED, TRANSITIONAL, UNKNOWN)

logger = logging.getLogger(__name__)

# Tanınmayan ham değer başına SÜREÇ BAŞINA bir kez WARNING (log seli olmasın).
_WARNED: set = set()
_WARNED_LOCK = threading.Lock()
_WARNED_MAX = 200  # bellek sınırı (sınırsız farklı değer gelirse)


def reset_warned() -> None:
    """Yalnız testler için: uyarılmış değer kümesini sıfırlar."""
    with _WARNED_LOCK:
        _WARNED.clear()


def _warn_unrecognized(raw: Any, key: str) -> None:
    with _WARNED_LOCK:
        if key in _WARNED or len(_WARNED) >= _WARNED_MAX:
            return
        _WARNED.add(key)
    logger.warning(
        "power_state: tanınmayan ham güç durumu değeri %r (normalize=%r) -> 'unknown' "
        "(açık/kapalı sayılmaz); gerekiyorsa chat_quality/power_state.py kümelerine ekleyin",
        str(raw)[:80], key[:80],
    )

_SEP_RE = re.compile(r"[\s_\-.]+")

# Anahtarlar normalize edilmiş biçimdedir (küçük harf, ayırıcısız).
_ON = frozenset({
    "poweredon", "on", "running", "up", "active",
})
_OFF = frozenset({
    "poweredoff", "off", "stopped", "down", "shutoff", "shutdown", "halted",
})
_SUSPENDED = frozenset({
    "suspended", "suspend", "standby", "saved", "hibernated",
})
_TRANSITIONAL = frozenset({
    # KubeVirt / Kubernetes
    "starting", "stopping", "migrating", "provisioning", "terminating", "paused", "pending",
    "scheduling", "scheduled", "waitingforvolumebinding", "errorunschedulable", "unschedulable",
    "crashloopbackoff", "errimagepull", "imagepullbackoff", "datavolumeerror",
    # VMware / oVirt / Hyper-V
    "poweringon", "poweringoff", "poweringup", "poweringdown", "rebootinprogress", "rebooting",
    "waitforlaunch", "imagelocked", "savingstate", "restoringstate", "notresponding",
    "preparingformaintenance", "resetting", "pausing", "resuming", "saving",
})
# Açıkça "durum yok" anlamına gelenler
_UNKNOWN = frozenset({"", "unknown", "none", "null", "n/a", "na", "unassigned", "-"})


def normalize_key(raw: Any) -> str:
    """`POWERED_ON`, `powered on`, `Powered-On` → `poweredon`."""
    if raw is None:
        return ""
    return _SEP_RE.sub("", str(raw).strip().lower())


def classify(raw: Any) -> str:
    """Ham güç durumu → `on|off|suspended|transitional|unknown`."""
    k = normalize_key(raw)
    if k in _ON:
        return ON
    if k in _OFF:
        return OFF
    if k in _SUSPENDED:
        return SUSPENDED
    if k in _TRANSITIONAL:
        return TRANSITIONAL
    if k in _UNKNOWN:
        return UNKNOWN
    # "suspend…" ile başlayan (suspendedByUser vb.) → askıda
    if k.startswith("suspend"):
        return SUSPENDED
    _warn_unrecognized(raw, k)
    return UNKNOWN


def is_on(raw: Any) -> bool:
    return classify(raw) == ON


def is_off(raw: Any) -> bool:
    return classify(raw) == OFF


def is_suspended(raw: Any) -> bool:
    return classify(raw) == SUSPENDED


def is_recognized(raw: Any) -> bool:
    """`unknown` sınıfı yalnız boş/'unknown' değerlerde değil, tanınmayan değerlerde de döner;
    bu fonksiyon tanınmayanı (ne bilinen sınıf ne açık 'durum yok') ayırt eder."""
    k = normalize_key(raw)
    if k in _UNKNOWN:
        return True
    return k in _ON or k in _OFF or k in _SUSPENDED or k in _TRANSITIONAL or k.startswith("suspend")


def summarize(raws: Iterable[Any]) -> Dict[str, Any]:
    """Adetler + ham değer kırılımı.

    Dönüş: `{"total", "on", "off", "suspended", "transitional", "unknown",
             "other_raw": {ham_değer: adet}}` — `other_raw` transitional + unknown ham değerleridir
    (boş değer `(boş)` olarak yazılır).
    """
    counts = {c: 0 for c in CLASSES}
    other: Counter = Counter()
    total = 0
    for raw in raws:
        total += 1
        c = classify(raw)
        counts[c] += 1
        if c in (TRANSITIONAL, UNKNOWN):
            label = str(raw).strip() if raw is not None and str(raw).strip() else "(boş)"
            other[label] += 1
    return {"total": total, **counts, "other_raw": dict(other)}


def other_note(other_raw: Dict[str, int], *, max_items: int = 6) -> str:
    """`{"Paused": 2, "X": 1}` → `Paused:2, X:1` (en sık değerler önce)."""
    items = sorted(other_raw.items(), key=lambda kv: (-kv[1], kv[0]))
    shown = [f"{k}:{n}" for k, n in items[:max_items]]
    rest = len(items) - len(shown)
    if rest > 0:
        shown.append(f"+{rest} değer daha")
    return ", ".join(shown)


def label_tr(cls: str) -> str:
    return {
        ON: "çalışıyor",
        OFF: "kapalı",
        SUSPENDED: "askıda",
        TRANSITIONAL: "geçiş/diğer durum",
        UNKNOWN: "bilinmiyor",
    }.get(cls, cls)


def pstate_label(raw: Optional[Any]) -> str:
    """Kullanıcıya gösterim: ham değer korunur."""
    s = "" if raw is None else str(raw).strip()
    return s or "-"


# ── SQL bağlama (Adım 5d) ───────────────────────────────────────────────────────────────
# Sohbet dışı sorgular (rapor/KPI/virt_reclaim) ham değer listelerini kendileri yazmasın: aşağıdaki ifadeler
# `_ON` kümesinden ÜRETİLİR ve `normalize_key` ile aynı normalizasyonu uygular (küçük harf, boşluk/_/-/. yok).
_SQL_SEP = r"[\s_.-]+"


def on_keys() -> tuple:
    return tuple(sorted(_ON))


def sql_is_on(col: str) -> str:
    """Ham SQL parçası: `<col>` kanonik olarak ON sınıfında mı. `col` güvenilir sabit ad olmalı (kullanıcı girdisi değil)."""
    keys = ", ".join("'" + k.replace("'", "''") + "'" for k in on_keys())
    return f"lower(regexp_replace(btrim({col}), '{_SQL_SEP}', '', 'g')) IN ({keys})"


def sqla_is_on(column):
    """SQLAlchemy ifadesi: `column` kanonik olarak ON sınıfında mı."""
    from sqlalchemy import func

    return func.lower(func.regexp_replace(func.btrim(column), _SQL_SEP, "", "g")).in_(list(on_keys()))
