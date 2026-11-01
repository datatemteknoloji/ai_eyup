"""Adım 5 kapanış / Aşama 2a — pencere verilmeyen (varsayılan) handler yolunda tz-aware «şimdi».

Eski hata: `since = datetime.utcnow() - timedelta(days=N)` NAİF UTC değeri timestamptz sütununa bağlanınca,
oturum saat diliminde (Europe/Istanbul) yerel sayılıyor → pencere 3 saat fazla geniş. Düzeltme:
`clock.default_since(days)` (tz-aware; `now_override` ve `chat_timezone` destekli).
"""
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services import hypervisor_intelligence as hi
from app.services.chat_quality import clock, time_window as tw

IST = tw._tz("Europe/Istanbul")[0]
NOW = datetime(2026, 10, 15, 14, 30, tzinfo=IST)           # 11:30 UTC


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: NOW)
    from app.services import runtime_settings as rs
    real_str = rs.get_str
    monkeypatch.setattr(rs, "get_str", lambda k: "Europe/Istanbul" if k == "chat_timezone" else real_str(k))


def test_now_aware_is_tz_aware_and_same_instant():
    n = clock.now_aware()
    assert n.tzinfo is not None
    assert n.utcoffset() == timedelta(hours=3)
    assert n == NOW


def test_now_aware_naive_override_assumed_local(monkeypatch):
    # now_override naif (sistem yerel saati) → ayarlı dilime çevrilir; anı değişmez
    naive_local = datetime(2026, 10, 15, 14, 30)
    monkeypatch.setattr(clock, "now", lambda: naive_local)
    n = clock.now_aware("Europe/Istanbul")
    assert n.tzinfo is not None
    assert n.astimezone(timezone.utc) == naive_local.astimezone().astimezone(timezone.utc)


def test_default_since_window_boundary_istanbul():
    s = clock.default_since(1)
    assert s.tzinfo is not None
    # 24 saat önce: 14 Ekim 14:30 İstanbul = 11:30 UTC. Eski kod naif UTC (11:30) → İstanbul yerel 11:30 → 3 sa fazla.
    assert s.astimezone(timezone.utc) == datetime(2026, 10, 14, 11, 30, tzinfo=timezone.utc)
    legacy_naive_utc = datetime(2026, 10, 14, 11, 30)       # eski `utcnow() - 1g` değeri
    legacy_as_local = legacy_naive_utc.replace(tzinfo=IST)   # Postgres bunu İstanbul yerel sayardı
    assert (s - legacy_as_local) == timedelta(hours=3)       # 3 saat fark = düzeltilen hata


def test_default_since_days_arithmetic():
    assert clock.default_since(7) == NOW - timedelta(days=7)
    assert clock.default_since(30) == NOW - timedelta(days=30)


def _since_param(db):
    for c in db.execute.call_args_list:
        if len(c.args) > 1 and isinstance(c.args[1], dict) and "since" in c.args[1]:
            return c.args[1]["since"]
    return None


@pytest.mark.parametrize("handler,question,days", [
    ("h_critical_alarms_24h", "Kritik alarmlar neler?", 1),
    ("h_storage_alarms_30d", "Storage alarmları neler?", 30),
    ("h_vm_most_alarms_7d", "En çok alarm üreten VM'ler?", 7),
    ("h_alarm_trend", "Alarm trendi nedir?", 30),
    ("h_network_errors", "Network hataları var mı?", 7),
])
def test_default_path_binds_tz_aware_since(handler, question, days):
    db = MagicMock()
    getattr(hi, handler)(db, question)
    since = _since_param(db)
    assert since is not None, f"{handler}: since parametresi bağlanmadı"
    assert since.tzinfo is not None, f"{handler}: naif since (utcnow) — 3 saat kayma"
    assert since.astimezone(timezone.utc) == (NOW - timedelta(days=days)).astimezone(timezone.utc)


def test_events_keyword_search_default_path_aware(monkeypatch):
    from app.services import vcenter_vm_lifecycle as lc
    monkeypatch.setattr(lc, "_vmware_hypervisors", lambda db: [])
    db = MagicMock()
    hi.h_events_keyword_search(db, "backup olayları")
    since = _since_param(db)
    assert since is None or since.tzinfo is not None


def test_no_naive_utcnow_since_left_in_handlers():
    src = Path(hi.__file__).read_text(encoding="utf-8")
    bad = re.findall(r"^\s*since\s*=\s*datetime\.utcnow\(\)", src, flags=re.M)
    assert bad == []


def test_windowed_path_unchanged():
    db = MagicMock()
    db.execute.return_value.scalar.return_value = datetime(2026, 8, 1, tzinfo=IST)   # en eski system_events kaydı
    hi.h_critical_alarms_24h(db, "Dün oluşan kritik alarmlar")
    since = _since_param(db)
    # pencere: dün 00:00 – bugün 00:00 (İstanbul)
    assert since == datetime(2026, 10, 14, 0, 0, tzinfo=IST)
