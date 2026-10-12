"""Ortak kapasite senaryo motoru (H Faz 1): tek model + vCenter / OLVM / OpenShift adaptörleri.

Düğüm kapasitesi, HA rezervi, N+1, yerleşim (what-if) ve drene senaryosu TEK yerde hesaplanır.
Eski motorlar (`virt_capacity_planner` iç hesapları, `ocp_capacity_sim.simulate_legacy`) bir sürüm
boyunca `CAPACITY_ENGINE=legacy` ile korunur; varsayılan `unified`. Eşdeğerlik testleri her iki motoru
aynı girdilerde karşılaştırır (`tests/test_capacity_engine.py`).
"""
from __future__ import annotations

import os

ENGINE_ENV = "CAPACITY_ENGINE"


def engine_mode() -> str:
    """`unified` (varsayılan) | `legacy`. Bilinmeyen değer → legacy (temkinli)."""
    v = (os.getenv(ENGINE_ENV) or "unified").strip().lower()
    return v if v in ("unified", "legacy") else "legacy"
