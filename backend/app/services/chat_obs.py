"""Chat soğuk yol gözlemlenebilirliği (Plan 2 Dalga 3 — TTFT).

perf_counter ile cache/collect/agentic/ttft süreleri; isteğe bağlı Prometheus histogram.
"""
from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional, Sequence, Tuple

logger = logging.getLogger(__name__)

# RAG: canlı collect bittikten sonra en fazla bu kadar ek bekle (sn)
RAG_AFTER_COLLECT_BUDGET_SEC = 2.5

_HIST: Dict[str, Any] = {}


def _histogram(name: str, documentation: str):
    if name in _HIST:
        return _HIST[name]
    try:
        from prometheus_client import Histogram

        h = Histogram(
            name,
            documentation,
            labelnames=("platform",),
            buckets=(0.05, 0.1, 0.25, 0.5, 1, 2, 5, 10, 20, 45, 90, 180),
        )
        _HIST[name] = h
        return h
    except Exception as e:
        logger.debug("prometheus histogram yok (%s): %s", name, e)
        _HIST[name] = None
        return None


def observe_seconds(metric: str, seconds: float, *, platform: str = "linux") -> None:
    if seconds < 0:
        return
    h = _histogram(
        f"ainew_chat_{metric}_seconds",
        f"Chat cold-path {metric} duration in seconds",
    )
    if h is not None:
        try:
            h.labels(platform=platform or "linux").observe(seconds)
        except Exception:
            pass


class ChatTiming:
    """Bir stream turu için zaman damgaları."""

    def __init__(self, platform: str = "linux"):
        self.platform = platform or "linux"
        self.t0 = time.perf_counter()
        self._marks: Dict[str, float] = {"start": self.t0}
        self._ttft_logged = False

    def mark(self, name: str) -> None:
        self._marks[name] = time.perf_counter()

    def elapsed_ms(self, since: str = "start", until: Optional[str] = None) -> float:
        t_a = self._marks.get(since, self.t0)
        t_b = self._marks[until] if until and until in self._marks else time.perf_counter()
        return max(0.0, (t_b - t_a) * 1000.0)

    def note_ttft(self) -> None:
        if self._ttft_logged:
            return
        self._ttft_logged = True
        self.mark("ttft")
        sec = (self._marks["ttft"] - self.t0)
        observe_seconds("ttft", sec, platform=self.platform)

    def finish(
        self,
        *,
        cache_hit: bool = False,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, float]:
        """Log + histogram; ms cinsinden özet döner."""
        now = time.perf_counter()
        self._marks.setdefault("end", now)

        def _ms(a: str, b: str) -> float:
            if a not in self._marks or b not in self._marks:
                return -1.0
            return max(0.0, (self._marks[b] - self._marks[a]) * 1000.0)

        cache_ms = _ms("start", "cache") if "cache" in self._marks else -1.0
        collect_ms = _ms("collect_start", "collect_end")
        agentic_ms = _ms("agentic_start", "agentic_end")
        ttft_ms = _ms("start", "ttft") if "ttft" in self._marks else -1.0
        total_ms = (self._marks["end"] - self.t0) * 1000.0

        if collect_ms >= 0:
            observe_seconds("collect", collect_ms / 1000.0, platform=self.platform)
        if agentic_ms >= 0:
            observe_seconds("agentic", agentic_ms / 1000.0, platform=self.platform)
        if cache_hit and cache_ms >= 0:
            observe_seconds("cache", cache_ms / 1000.0, platform=self.platform)

        summary = {
            "cache_ms": round(cache_ms, 1) if cache_ms >= 0 else -1,
            "collect_ms": round(collect_ms, 1) if collect_ms >= 0 else -1,
            "agentic_ms": round(agentic_ms, 1) if agentic_ms >= 0 else -1,
            "ttft_ms": round(ttft_ms, 1) if ttft_ms >= 0 else -1,
            "total_ms": round(total_ms, 1),
        }
        extra_s = ""
        if extra:
            extra_s = " " + " ".join(f"{k}={v}" for k, v in extra.items())
        logger.info(
            "[ChatTTFT] platform=%s cache_hit=%s cache_ms=%s collect_ms=%s "
            "agentic_ms=%s ttft_ms=%s total_ms=%s%s",
            self.platform,
            cache_hit,
            summary["cache_ms"],
            summary["collect_ms"],
            summary["agentic_ms"],
            summary["ttft_ms"],
            summary["total_ms"],
            extra_s,
        )
        return summary


def safe_task_result(task, default):
    try:
        if task.done() and not task.cancelled():
            return task.result()
    except Exception:
        return default
    return default


async def await_live_then_rag(
    live_tasks: Sequence[asyncio.Future],
    rag_task: asyncio.Future,
    *,
    live_timeout: float,
    rag_budget: float = RAG_AFTER_COLLECT_BUDGET_SEC,
) -> Tuple[List[Any], Any]:
    """Canlı collect bitince ilerle; RAG best-effort (kısa ek bütçe).

    Returns:
        live_results: live_tasks sırasıyla sonuçlar (timeout/cancel → default benzeri None)
        rag_result: dict veya {}
    """
    live_list = list(live_tasks)
    if live_list:
        done, pending = await asyncio.wait(live_list, timeout=max(0.1, float(live_timeout)))
        for t in pending:
            t.cancel()
    else:
        done = set()

    live_results = []
    for t in live_list:
        if t in done:
            live_results.append(safe_task_result(t, None))
        else:
            live_results.append(None)

    if rag_task.done():
        rag = safe_task_result(rag_task, {})
        return live_results, rag if isinstance(rag, dict) else {}

    done_r, pend_r = await asyncio.wait([rag_task], timeout=max(0.0, float(rag_budget)))
    for t in pend_r:
        t.cancel()
    if rag_task in done_r:
        rag = safe_task_result(rag_task, {})
        return live_results, rag if isinstance(rag, dict) else {}
    return live_results, {}
