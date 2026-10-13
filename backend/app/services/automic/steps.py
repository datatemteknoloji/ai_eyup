"""Collector adım bütçeleri: her adımın kendi zaman payı var; aşan adım kesilir, imleçten sonraki turda devam eder.

Hiçbir adım diğerlerini aç bırakamaz: adım son tarihi = min(tur son tarihi, adım başlangıcı + pay × toplam bütçe).
Adımlar kendi `deadline` parametresini kontrol eder (zaten öyleydi); imleçler kalıcıdır (watermark, backfill/jpp/script/users
imleçleri, rapor kuyruğu tablosu, `AutomicCollectorState.step_state` içindeki refresh/resync imleçleri).
Süre ve "bütçe aşımı" `AutomicCollectorRun.step_metrics` + `step_state` (toplam sayaç) üzerinden health'e gider.
"""
from __future__ import annotations

import copy
import logging
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Dict, Iterator, Optional

from .errors import note_error

logger = logging.getLogger(__name__)

DEFAULT_SHARES: Dict[str, float] = {
    "ingest": 0.30, "active": 0.04, "reports": 0.22, "refresh": 0.12, "users": 0.03, "infra": 0.04,
    "gap": 0.02, "jpp": 0.05, "script": 0.05, "reconcile": 0.04, "backfill": 0.05, "resync": 0.04,
}
# Bu hata kodları tüm turu bozar (bağlantı/yetki); adım içinde yutulmaz → üst katman devre kesici
FATAL_CODES = ("circuit_open", "connection_lost", "auth_failed", "no_listener", "connect_failed", "busy")


class StepClock:
    def __init__(self, total_sec: float, shares: Optional[Dict[str, float]], run_deadline: float,
                 on_error: Optional[Any] = None):
        merged = dict(DEFAULT_SHARES)
        for k, v in (shares or {}).items():
            try:
                merged[k] = max(0.01, min(1.0, float(v)))
            except (TypeError, ValueError) as exc:
                note_error("collector.step_shares", exc, detail=f"{k}={v!r}")
                continue
        self.total = float(total_sec)
        self.shares = merged
        self.run_deadline = run_deadline
        self.on_error = on_error  # ör. db.rollback — hatalı adım oturumu bozmasın
        self.metrics: Dict[str, Dict[str, Any]] = {}

    @contextmanager
    def step(self, name: str) -> Iterator[SimpleNamespace]:
        """`with clock.step("reports") as st:` → st.deadline (monotonic), st.items (adım doldurur), st.cut."""
        budget = self.total * self.shares.get(name, 0.03)
        start = time.monotonic()
        st = SimpleNamespace(deadline=min(self.run_deadline, start + budget), items=0, cut=False, error=None,
                             budget=budget, name=name)
        try:
            yield st
        except Exception as exc:  # noqa: BLE001
            code = getattr(exc, "code", None)
            if code in FATAL_CODES:
                self._record(name, st, start, fatal=True)
                raise
            # Bir adımın hatası diğer adımları aç bırakmaz: kaydet, devam et
            note_error(f"collector.step.{name}", exc)
            if self.on_error is not None:
                try:
                    self.on_error()
                except Exception as rexc:  # noqa: BLE001
                    note_error(f"collector.step.{name}.rollback", rexc)
            st.error = f"{type(exc).__name__}: {exc}"[:200]
        finally:
            if name not in self.metrics:
                self._record(name, st, start)

    def _record(self, name: str, st: SimpleNamespace, start: float, fatal: bool = False) -> None:
        elapsed = time.monotonic() - start
        overrun = bool(st.cut) or (time.monotonic() >= st.deadline - 0.25 and elapsed >= st.budget * 0.9)
        self.metrics[name] = {
            "duration_sec": round(elapsed, 2), "budget_sec": round(st.budget, 1), "overrun": bool(overrun),
            "items": int(st.items or 0), "error": st.error or ("fatal" if fatal else None),
        }

    def snapshot(self) -> Dict[str, Dict[str, Any]]:
        return dict(self.metrics)


def get_step_state(state: Any) -> Dict[str, Any]:
    # Derin kopya: JSONB kolonu değişiklik izlemez — yerinde değiştirilen iç sözlük "değişmedi" sanılıp yazılmazdı
    ss = copy.deepcopy(dict(getattr(state, "step_state", None) or {}))
    ss.setdefault("cursors", {})
    ss.setdefault("last", {})
    ss.setdefault("overruns", {})
    ss.setdefault("runs", 0)
    return ss


def save_step_metrics(state: Any, metrics: Dict[str, Dict[str, Any]], cursors: Optional[Dict[str, Any]] = None) -> None:
    ss = get_step_state(state)
    if cursors is not None:
        ss["cursors"] = cursors
    ss["last"] = metrics
    ss["runs"] = int(ss.get("runs") or 0) + 1
    ov = dict(ss.get("overruns") or {})
    for name, m in metrics.items():
        if m.get("overrun"):
            ov[name] = int(ov.get(name) or 0) + 1
    ss["overruns"] = ov
    ss["last_at"] = datetime.now(timezone.utc).isoformat()
    state.step_state = ss
