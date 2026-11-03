"""Event / Incident yaşam döngüsü: sorun giderilince sayılar kendiliğinden düşer (event_lifecycle.py)."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

from app.models.event import Incident, SystemEvent
from app.services import event_lifecycle as lc
from app.tests.isolated_db import _isolated_engine, isolated_db  # noqa: F401

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


def _ev(db, hours_ago: float, *, etype="log_entry", sev="warning", source="log_collector", resolved=False, **kw):
    ls = NOW - timedelta(hours=hours_ago)
    e = SystemEvent(event_type=etype, severity=sev, source=source, title=f"{etype}-{sev}-{hours_ago}",
                    resolved=resolved, last_seen=ls, raw_data=kw.pop("raw_data", {}), **kw)
    db.add(e)
    db.commit()
    db.query(SystemEvent).filter(SystemEvent.id == e.id).update({"created_at": ls})
    db.commit()
    return e


def _inc(db, related, *, source="auto_log_entry", status="open", updated_hours_ago=30, title="t", **kw):
    ts = NOW - timedelta(hours=updated_hours_ago)
    i = Incident(title=title, severity="critical", status=status, source=source, affected_servers=[],
                 related_events=list(related), **kw)
    db.add(i)
    db.commit()
    db.query(Incident).filter(Incident.id == i.id).update({"created_at": ts, "updated_at": ts})
    db.commit()
    return i


def _state(db, e):
    db.expire_all()
    return db.query(SystemEvent).get(e.id).resolved


# ── olay süpürme ─────────────────────────────────────────────────────────────

def test_point_events_resolve_by_severity_quiet_time(isolated_db):
    db = isolated_db
    info_old, info_new = _ev(db, 3, sev="info"), _ev(db, 1, sev="info")
    warn_old, warn_new = _ev(db, 13, sev="warning"), _ev(db, 11, sev="warning")
    crit_old, crit_new = _ev(db, 25, sev="critical", etype="vcenter_event"), _ev(db, 23, sev="critical", etype="vcenter_event")
    unknown_sev = _ev(db, 25, sev="weird")
    stats = lc.sweep_stale_events(db, NOW)
    assert stats["point"] == 4
    assert [_state(db, e) for e in (info_old, warn_old, crit_old, unknown_sev)] == [True] * 4
    assert [_state(db, e) for e in (info_new, warn_new, crit_new)] == [False] * 3
    r = db.query(SystemEvent).get(info_old.id)
    assert r.resolved_at is not None            # silinmez, çözüldü olarak işaretlenir


def test_state_alarm_uses_state_window_and_managed_or_manual_untouched(isolated_db):
    db = isolated_db
    alarm_stale, alarm_live = _ev(db, 5, etype="vcenter_alarm", sev="critical"), _ev(db, 2, etype="vcenter_alarm", sev="critical")
    metric = _ev(db, 40, etype="metric_anomaly", sev="warning", source="prometheus")
    hw = _ev(db, 100, etype="hw_alert", sev="critical", source="hw_sync")
    manual = _ev(db, 100, sev="critical", source="manual")
    already = _ev(db, 100, sev="warning", resolved=True)
    stats = lc.sweep_stale_events(db, NOW)
    assert stats["state"] == 1 and stats["point"] == 0
    assert _state(db, alarm_stale) is True and _state(db, alarm_live) is False
    assert _state(db, metric) is False and _state(db, hw) is False and _state(db, manual) is False
    assert _state(db, already) is True


def test_recurring_event_stays_open(isolated_db):
    db = isolated_db
    e = _ev(db, 40, sev="warning")                                 # eski ama collector last_seen'i yeniledi
    db.query(SystemEvent).filter(SystemEvent.id == e.id).update({"last_seen": NOW - timedelta(minutes=10)})
    db.commit()
    assert lc.sweep_stale_events(db, NOW) == {"state": 0, "point": 0}
    assert _state(db, e) is False


# ── incident uzlaştırma ──────────────────────────────────────────────────────

def test_incident_closes_only_when_all_linked_events_resolved(isolated_db):
    db = isolated_db
    ok1 = _ev(db, 30, resolved=True)
    ok2 = _ev(db, 30, resolved=True)
    still = _ev(db, 1, resolved=False)
    for e in (ok1, ok2):
        db.query(SystemEvent).filter(SystemEvent.id == e.id).update({"resolved_at": NOW - timedelta(hours=2)})
    db.commit()
    done = _inc(db, [ok1.id, ok2.id])
    persists = _inc(db, [ok1.id, still.id])
    assert lc.reconcile_incidents(db, NOW) == 1
    db.expire_all()
    d, p = db.query(Incident).get(done.id), db.query(Incident).get(persists.id)
    assert d.status == "resolved" and d.resolved_at and "bağlı tüm olaylar düzeldi" in d.resolution
    assert p.status == "open"                                        # sorun sürüyor


def test_incident_grace_and_protection_rules(isolated_db):
    db = isolated_db
    fresh_res = _ev(db, 1, resolved=True)
    db.query(SystemEvent).filter(SystemEvent.id == fresh_res.id).update({"resolved_at": NOW - timedelta(minutes=3)})
    old_res = _ev(db, 30, resolved=True)
    db.query(SystemEvent).filter(SystemEvent.id == old_res.id).update({"resolved_at": NOW - timedelta(hours=3)})
    db.commit()
    in_grace = _inc(db, [fresh_res.id])
    manual = _inc(db, [old_res.id], source="manual")
    owned = _inc(db, [old_res.id], assigned_to="ayse")
    investigating = _inc(db, [old_res.id], status="investigating")
    no_events = _inc(db, [])
    storm = _inc(db, [old_res.id], source="storm_detector")
    assert lc.reconcile_incidents(db, NOW) == 1                       # yalnız storm kapanır
    db.expire_all()
    by = {i.id: i.status for i in db.query(Incident).all()}
    assert by[storm.id] == "resolved"
    assert by[in_grace.id] == "open" and by[manual.id] == "open" and by[owned.id] == "open"
    assert by[investigating.id] == "investigating" and by[no_events.id] == "open"


def test_auto_close_quiet_does_not_close_while_problem_persists(isolated_db):
    db = isolated_db
    from app.services.aiops_engine import auto_close_quiet_incidents
    live = _ev(db, 0.1, resolved=False)
    dead = _ev(db, 30, resolved=True)
    persisting = _inc(db, [live.id], title="persisting")
    quiet = _inc(db, [dead.id])
    storm_quiet = _inc(db, [], source="storm_detector")
    assert auto_close_quiet_incidents(db, NOW) == 2
    db.expire_all()
    assert db.query(Incident).get(persisting.id).status == "open"
    assert db.query(Incident).get(quiet.id).status == "resolved"
    assert db.query(Incident).get(storm_quiet.id).status == "resolved"   # storm da sessiz kalınca kapanır


# ── persist: süren kritik anomali incident'a yeniden bağlanır ───────────────────

def test_persisting_critical_anomaly_relinks_incident_after_close(isolated_db):
    db = isolated_db
    from app.services import aiops_engine as eng
    ev = _ev(db, 0.2, etype="metric_anomaly", sev="critical", source="prometheus",
             raw_data={"metric": "cpu_usage"})
    closed = _inc(db, [ev.id], source="auto_metric_anomaly", status="resolved")   # incident kapanmış, anomali sürüyor
    anomaly = {"server_id": None, "metric_name": "cpu_usage", "severity": "critical", "current_value": 99,
               "message": "cpu yüksek", "detected_at": NOW.isoformat()}
    sup = {"suppress": False, "effective_severity": "critical", "downgrade_reason": None, "recurrence": {}}
    with patch.object(eng, "apply_baseline_filter", return_value=sup), \
         patch.object(eng, "run_lifecycle", return_value={"events_swept": 0, "incidents_closed": 0}):
        r = eng.persist_anomalies_as_events(db, [anomaly])
    assert r["updated"] == 1 and r["incidents"] == 1
    db.expire_all()
    open_incs = db.query(Incident).filter(Incident.status == "open").all()
    assert len(open_incs) == 1 and ev.id in open_incs[0].related_events
    assert db.query(Incident).get(closed.id).status == "resolved"             # eski kayıt yeniden açılmaz
    # ikinci tur: zaten bağlı → yeni incident açılmaz
    with patch.object(eng, "apply_baseline_filter", return_value=sup), \
         patch.object(eng, "run_lifecycle", return_value={"events_swept": 0, "incidents_closed": 0}):
        r2 = eng.persist_anomalies_as_events(db, [anomaly])
    assert r2["incidents"] == 0 and db.query(Incident).filter(Incident.status == "open").count() == 1


# ── storm: kapalı incident yeniden canlanmaz ──────────────────────────────────

def test_storm_does_not_revive_closed_incident(isolated_db):
    db = isolated_db
    from app.services.storm_detector import get_or_create_storm_incident
    closed = Incident(title="⚡ ALARM FIRTINASI: cpu — 6 sunucu", severity="critical", status="closed",
                      source="storm_detector", affected_servers=[], related_events=[])
    db.add(closed)
    db.commit()
    storm = {"metric": "cpu", "server_count": 6, "event_count": 6, "max_severity": "critical",
             "server_ids": [1, 2, 3, 4, 5, 6], "event_ids": [1, 2, 3, 4, 5, 6]}
    new_id = get_or_create_storm_incident(db, storm)
    assert new_id != closed.id
    db.expire_all()
    assert db.query(Incident).get(closed.id).status == "closed"


# ── collector'lar: yeniden dökümde şişme / yeniden açma yok ─────────────────────

def test_vcenter_replay_does_not_inflate_or_reopen(isolated_db):
    db = isolated_db
    from app.services import vcenter_event_collector as vc
    manual = _ev(db, 5, etype="vcenter_event", sev="critical", source="vcenter_event", resolved=True, occurrence_count=1)
    alarm = _ev(db, 5, etype="vcenter_alarm", sev="critical", source="vcenter_alarm", occurrence_count=1)
    hv = SimpleNamespace(id=1, name="vc", ip_address="1.1.1.1", hostname="vc")
    item = {"severity": "critical", "entity_name": "esx1"}
    with patch.object(vc, "_resolve_server_id", return_value=None):
        vc._backfill_existing_event(manual, db, hv, item, NOW)
        vc._backfill_existing_event(alarm, db, hv, item, NOW)
    assert manual.resolved is True and manual.occurrence_count == 1
    assert manual.last_seen == NOW - timedelta(hours=5)                       # replay last_seen'i yenilemez
    assert alarm.last_seen == NOW and alarm.occurrence_count == 1             # alarm: «hâlâ tetikte»


def test_openshift_recurrence_reopens_but_replay_does_not(isolated_db):
    db = isolated_db
    from app.models.openshift import OpenShiftCluster
    from app.services import openshift_event_collector as oc
    c = OpenShiftCluster(name="ocp", api_url="https://x:6443", connection_config={})
    db.add(c)
    db.flush()
    key = f"ocp{c.id}-Pod/a-BackOff"
    old_ts = NOW - timedelta(hours=30)
    ev = _ev(db, 30, etype="openshift_event", sev="warning", source=oc.OPENSHIFT_SOURCE, resolved=True,
             raw_data={"external_key": key})
    db.query(SystemEvent).filter(SystemEvent.id == ev.id).update({"resolved_at": NOW - timedelta(hours=6)})
    db.commit()
    item = {"source_object": "Pod/a", "reason": "BackOff", "severity": "warning", "timestamp": old_ts.isoformat()}
    with patch.object(oc, "utc_now", return_value=NOW):
        assert oc._upsert_openshift_event(db, c, item, NOW) is False          # aynı zaman damgası = replay
    db.expire_all()
    assert db.query(SystemEvent).get(ev.id).resolved is True
    item["timestamp"] = (NOW - timedelta(minutes=5)).isoformat()                # gerçek tekrar
    with patch.object(oc, "utc_now", return_value=NOW):
        assert oc._upsert_openshift_event(db, c, item, NOW) is False
    db.commit()
    db.expire_all()
    r = db.query(SystemEvent).get(ev.id)
    assert r.resolved is False and r.resolved_at is None and r.occurrence_count == 2
