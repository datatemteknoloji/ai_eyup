"""Çok parçalı soru — hangi alt-konular tool ile karşılandı?

LLM yargıç yok. Soru kalıbı × çalıştırılan tool adı.
"""
from __future__ import annotations

import re
from typing import Iterable, List, Sequence, Tuple

# (soru regex, tool adı alt-dizgileri, etiket)
_CLAUSES: Tuple[Tuple[str, Tuple[str, ...], str], ...] = (
    (r"snapshot", ("snapshot",), "snapshot"),
    (r"openshift|ocp|\bpod\b|kubevirt|crashloop", ("ocp", "openshift", "kubevirt", "datavolume"), "openshift"),
    (r"\bwindows\b|winrm|event.?log|powershell", ("win_", "windows"), "windows"),
    (r"yavaş|yavas|bottleneck|cpu\s*ready|contention", ("bottleneck", "perf", "metric", "prometheus", "linux_virt_io"), "perf"),
    (r"datastore|disk\s*(rate|latency|iops)", ("datastore", "disk", "perf"), "storage"),
    (r"iowait|guest.?io", ("linux_virt_io", "iowait"), "guest_io"),
    (r"exadata|asm\b|storage cell|cell server|db node", ("exadata", "asm"), "exadata"),
)


def clause_tags_in_message(message: str) -> List[str]:
    m = message or ""
    tags: List[str] = []
    for pat, _needles, label in _CLAUSES:
        if re.search(pat, m, re.I) and label not in tags:
            tags.append(label)
    return tags


def tool_covers(label: str, tools_used: Iterable[str]) -> bool:
    needles = next((n for _p, n, lab in _CLAUSES if lab == label), ())
    blob = " ".join(tools_used or []).lower()
    return any(n.lower() in blob for n in needles)


def uncovered_clause_labels(message: str, tools_used: Sequence[str]) -> List[str]:
    tags = clause_tags_in_message(message)
    if len(tags) < 2:
        return []
    return [t for t in tags if not tool_covers(t, tools_used)]


def sufficiency_nudge(missing: Sequence[str]) -> str:
    joined = ", ".join(missing)
    return (
        f"Sorunun şu kısımları henüz araçla karşılanmadı: {joined}. "
        "Uygun READ_ONLY aracı çağır; bu kısımları atlayıp bitirme."
    )
