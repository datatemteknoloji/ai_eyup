"""OpenShift pod durum sınıflandırması — sayım kuralı ve `list_ocp_pods` aracı aynı tanımı kullanır."""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, Optional

PROBLEM_RESTART_MIN = 5

PROBLEM_DEFINITION_TR = (
    "Hatalı pod tanımı: durumu Running/Succeeded dışında olan, ya da nedeni (reason) Completed dışında dolu olan, "
    f"ya da {PROBLEM_RESTART_MIN}+ kez yeniden başlamış pod."
)


# «Hatalı (Error/CrashLoopBackOff/RunContainerError)» sorusu bu DAR kümeyi sorar; `problem_count` (restart ≥5 vb. dahil)
# bu soruya cevap DEĞİLDİR — ikisi karıştırılırsa sayı ~10 kat şişer (bench o09).
ERROR_STATES = ("Error", "CrashLoopBackOff", "RunContainerError")
ERROR_STATE_DEFINITION_TR = (
    "error_state_count: durumu/nedeni Error, CrashLoopBackOff veya RunContainerError olan pod sayısı. "
    "«Error/CrashLoopBackOff/RunContainerError durumundaki pod sayısı» sorusunda BU alanı kullan; "
    "problem_count daha geniştir (restart ≥5, Pending, Completed dışı reason dahil) — onunla karıştırma."
)


def error_state_of(status: Optional[str], reason: Optional[str]) -> Optional[str]:
    """Pod `ERROR_STATES` kümesindeyse durum adı (status veya reason eşleşmesi), değilse None."""
    for st in ERROR_STATES:
        if matches_state(status, reason, st):
            return st
    return None


def is_problem(status: Optional[str], reason: Optional[str], restarts: Any = 0) -> bool:
    st = (status or "").strip().lower()
    rs = (reason or "").strip().lower()
    if st not in ("running", "succeeded"):
        return True
    if rs and rs != "completed":
        return True
    try:
        return int(restarts or 0) >= PROBLEM_RESTART_MIN
    except (TypeError, ValueError):
        return False


def problem_key(status: Optional[str], reason: Optional[str], restarts: Any = 0) -> str:
    """Hatalı pod kırılım anahtarı: neden (varsa) > durum > «yüksek restart»."""
    rs = (reason or "").strip()
    if rs and rs.lower() != "completed":
        return rs
    st = (status or "").strip()
    if st.lower() not in ("running", "succeeded", ""):
        return st
    if st == "":
        return "Unknown"
    return f"{PROBLEM_RESTART_MIN}+ restart ({st})"


def matches_state(status: Optional[str], reason: Optional[str], want: str) -> bool:
    """`want` bir durum/neden adı (küçük harf): status veya reason eşitse True."""
    w = (want or "").lower()
    return (status or "").strip().lower() == w or (reason or "").strip().lower() == w


def summarize(pods: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    """Pod sözlükleri (status/reason/restart_count) → by_status, by_reason, problem_count."""
    by_status: Counter = Counter()
    by_reason: Counter = Counter()
    problems = 0
    total = 0
    err_by: Counter = Counter()
    for p in pods:
        total += 1
        st, rs, rc = p.get("status"), p.get("reason"), p.get("restart_count")
        by_status[st or "Unknown"] += 1
        es = error_state_of(st, rs)
        if es:
            err_by[es] += 1
        if is_problem(st, rs, rc):
            problems += 1
            by_reason[problem_key(st, rs, rc)] += 1
    return {
        "total": total,
        "by_status": dict(by_status.most_common()),
        "by_reason": dict(by_reason.most_common()),
        "problem_count": problems,
        "problem_definition": PROBLEM_DEFINITION_TR,
        "error_state_count": sum(err_by.values()),
        "error_state_breakdown": dict(err_by.most_common()),
        "error_state_definition": ERROR_STATE_DEFINITION_TR,
    }
