"""Event döngüsü tıkanma gözcüsü (tanı aracı; Adım 11).

Neden: SSE teslimi event döngüsünde çalışır; bir hat senkron iş yapıp döngüyü
bloklarsa progress/token olayları geç ulaşır. Gözcü ayrı bir iş parçacığında
döngünün «nabzını» izler; tıkanma eşiği aşılırsa döngü iş parçacığının yığınını
log'a yazar (kim tıkıyor görülsün). Yük: 0,5 sn'de bir uyanan iş parçacığı + 0,25 sn'de
bir çalışan küçük async görev. Kapatma: LOOP_WATCHDOG=0.
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
import threading
import time
import traceback
from typing import Optional

logger = logging.getLogger(__name__)

BEAT_S = 0.25
CHECK_S = 0.5
STALL_WARN_S = 1.5

_state = {"beat": 0.0, "loop_tid": 0, "max_stall": 0.0, "stalls": 0}
_started = False


def enabled() -> bool:
    return (os.getenv("LOOP_WATCHDOG", "1") or "1").strip().lower() not in ("0", "false", "no", "off")


def stats() -> dict:
    return {"max_stall_s": round(_state["max_stall"], 2), "stalls": _state["stalls"]}


async def _beat_task() -> None:
    _state["loop_tid"] = threading.get_ident()
    while True:
        _state["beat"] = time.monotonic()
        await asyncio.sleep(BEAT_S)


def _stack_of_loop() -> str:
    fr = sys._current_frames().get(_state["loop_tid"])
    if fr is None:
        return ""
    frames = traceback.extract_stack(fr)
    app = [x for x in frames if "/app/app/" in x.filename][-10:]  # çağıran uygulama kodu (kütüphane gürültüsü değil)
    tail = frames[-3:]
    keep = app + [x for x in tail if x not in app]
    return "".join(traceback.format_list(keep))


def _thread_summary(top: int = 8) -> str:
    """Diğer iş parçacıklarının en üst çerçeveleri (GIL çekişmesi / CPU tüketen iş tanısı)."""
    me = threading.get_ident()
    counts: dict = {}
    for tid, fr in sys._current_frames().items():
        if tid in (me, _state["loop_tid"]):
            continue
        key = f"{fr.f_code.co_filename.split('site-packages/')[-1]}:{fr.f_lineno} {fr.f_code.co_name}"
        counts[key] = counts.get(key, 0) + 1
    rows = sorted(counts.items(), key=lambda kv: -kv[1])[:top]
    return f"{sum(counts.values())} iş parçacığı; " + " | ".join(f"{n}× {k}" for k, n in rows)


_cpu_prev: dict = {}
_cpu_delta: dict = {}


def _sample_thread_cpu() -> None:
    """Python iş parçacıklarının CPU tikleri (/proc/self/task/<tid>/stat; Linux). Hata sessiz."""
    try:
        cur = {}
        for t in threading.enumerate():
            nid = getattr(t, "native_id", None)
            if not nid:
                continue
            try:
                with open(f"/proc/self/task/{nid}/stat", "rb") as fh:
                    parts = fh.read().rsplit(b")", 1)[-1].split()
                cur[t.ident] = (int(parts[11]) + int(parts[12]), t.name)
            except Exception:
                continue
        _cpu_delta.clear()
        for ident, (ticks, name) in cur.items():
            prev = _cpu_prev.get(ident)
            if prev is not None:
                _cpu_delta[ident] = (ticks - prev[0], name)
        _cpu_prev.clear()
        _cpu_prev.update(cur)
    except Exception:
        pass


def _hot_threads(top: int = 2) -> str:
    """Son örnekleme penceresinde en çok CPU tüketen iş parçacıklarının yığını (GIL tutan iş tanısı)."""
    rows = sorted(_cpu_delta.items(), key=lambda kv: -kv[1][0])[:top]
    frames = sys._current_frames()
    out = []
    for ident, (d, name) in rows:
        if d <= 0:
            continue
        fr = frames.get(ident)
        st = "".join(traceback.format_stack(fr, limit=8)) if fr is not None else "?"
        out.append(f"[{name}] +{d} tik/{CHECK_S}sn\n{st}")
    return "\n".join(out) or "(CPU tüketen iş parçacığı yok)"


def _watch() -> None:
    reported_for = 0.0
    in_stall_beat = 0.0
    while True:
        time.sleep(CHECK_S)
        _sample_thread_cpu()
        beat = _state["beat"]
        if not beat:
            continue
        stall = time.monotonic() - beat - BEAT_S
        if stall > _state["max_stall"]:
            _state["max_stall"] = stall
        if in_stall_beat and beat != in_stall_beat:
            # tıkanma bitti (nabız ilerledi): toplam süreyi bildir
            total = max(0.0, beat - in_stall_beat)
            if total >= STALL_WARN_S + 1.0:
                logger.warning("[LoopWatchdog] tıkanma bitti: yaklaşık %.1f sn", total)
            in_stall_beat = 0.0
        if stall >= STALL_WARN_S and beat != reported_for:
            reported_for = beat
            in_stall_beat = beat
            _state["stalls"] += 1
            try:
                logger.warning(
                    "[LoopWatchdog] event döngüsü %.1f sn tıkalı; yığın:\n%s\nDiğer iş parçacıkları: %s\nEn çok CPU tüketenler:\n%s",
                    stall, _stack_of_loop(), _thread_summary(), _hot_threads(),
                )
            except Exception:
                pass


def start(loop: Optional[asyncio.AbstractEventLoop] = None) -> None:
    """Startup'ta çağrılır (idempotent)."""
    global _started
    if _started or not enabled():
        return
    _started = True
    lp = loop or asyncio.get_event_loop()
    lp.create_task(_beat_task())
    threading.Thread(target=_watch, name="loop_watchdog", daemon=True).start()
    logger.info("Event döngüsü gözcüsü başladı (eşik %.1f sn)", STALL_WARN_S)
