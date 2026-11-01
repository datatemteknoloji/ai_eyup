"""Olay zaman damgaları: `last_seen` UTC-aware yazılmalı (Postgres oturumu Europe/Istanbul iken naive `utcnow()`
yazmak timestamptz'yi 3 saat geriye kaydırıyordu → `last_seen < created_at`)."""
from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

import pytest
from sqlalchemy import text

import app.models.infrastructure_report  # noqa: F401
from app.models.event import SystemEvent
from app.models.server import Server

SVC = Path(__file__).resolve().parents[1] / "services"


def _srv(db):
    s = Server(name="lin-tz-01", hostname="lin-tz-01", ip_address="10.0.0.9", server_type="PHYSICAL", os_type="linux")
    db.add(s)
    db.commit()
    return s


def test_log_collector_last_seen_is_not_shifted_by_session_timezone(isolated_db):
    from app.services import log_collector
    db = isolated_db
    db.execute(text("SET TIME ZONE 'Europe/Istanbul'"))
    srv = _srv(db)
    logs = [{"line": "kernel: EDAC MC0: 1 CE memory read error", "severity": "warning", "category": "hardware"}]
    assert log_collector.save_logs_to_db(db, srv, logs) == 1
    ev = db.query(SystemEvent).filter(SystemEvent.server_id == srv.id).one()
    assert abs((ev.created_at - ev.last_seen).total_seconds()) < 60            # önceden ~10800 sn (3 saat)
    # ikinci tur: mevcut kaydın last_seen güncellemesi de kaymamalı
    assert log_collector.save_logs_to_db(db, srv, logs) == 0
    db.refresh(ev)
    assert ev.last_seen >= ev.created_at - timedelta(seconds=5)
    assert abs((ev.last_seen - ev.created_at).total_seconds()) < 60


# Olay yazan toplayıcılar `last_seen = now` için naive `datetime.utcnow()` kullanmamalı.
WRITERS = ["log_collector.py", "windows_log_collector.py", "vcenter_event_collector.py", "virt_log_collector.py",
           "openshift_event_collector.py", "openshift_virt_event_collector.py", "ovirt_event_collector.py",
           "syslog_receiver.py", "aiops_engine.py", "event_dedupe.py"]
# virt_log_collector: yaşam döngüsü durum damgası (AppSettings metni) kendi içinde tutarlı naive UTC'dir → izinli.
ALLOWED = {"virt_log_collector.py": 2}


@pytest.mark.parametrize("fname", WRITERS)
def test_event_writers_do_not_use_naive_utcnow_for_db_timestamps(fname):
    src = (SVC / fname).read_text()
    n = len(re.findall(r"datetime\.utcnow\(\)", src))
    allowed = ALLOWED.get(fname, 0)
    extra = {"aiops_engine.py": 1}.get(fname, 0)          # aiops: `analyzed_at` yalnız JSON metni
    assert n <= allowed + extra, f"{fname}: {n} adet naive datetime.utcnow() (izinli {allowed + extra})"
