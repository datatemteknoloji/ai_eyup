"""Değişiklikler ekranı: ardışık geçmiş ↔ baseline sapması ayrımı, baseline görünürlüğü, ack, retention."""
from datetime import datetime, timedelta, timezone

from app.models.infra_finding import VirtConfigSnapshot
from app.services import virt_config_drift as d
from app.services.findings import store
from app.tests.isolated_db import _isolated_engine, isolated_db  # noqa: F401

NOW = datetime.now(timezone.utc)


def _save(db, ref, cfg, hours_ago, *, kind="host", plat="vmware", src=1):
    return store.save_config_snapshot(
        db, platform=plat, source_id=src, entity_kind=kind, entity_ref=ref, entity_name=ref,
        cluster_name="C1", config=cfg, now=NOW - timedelta(hours=hours_ago))


def test_zero_drift_when_baseline_marked_after_last_change(isolated_db):
    """Kullanıcının gördüğü durum: değişiklikler baseline'dan ÖNCE olduysa sapma 0'dır (beklenen)."""
    db = isolated_db
    _save(db, "h1", {"ntp": "a"}, 30)
    _save(db, "h1", {"ntp": "b"}, 20)                       # değişiklik
    db.commit()
    d.set_baseline(db, platform="vmware", source_id=1, user="ayse")
    db.commit()
    p = d.changes_payload(db, platforms=["vmware"], days=30)
    assert p["count"] == 1 and p["baseline_count"] == 1
    assert p["drifted_count"] == 0                          # son hal = baseline
    assert p["baseline_marked_by"] == "ayse" and p["baseline_marked_at"]
    assert p["changes"][0]["has_baseline"] is True and p["changes"][0]["baseline_by"] == "ayse"


def test_drift_is_live_and_separate_from_history(isolated_db):
    db = isolated_db
    _save(db, "h1", {"ntp": "a", "dns": "1"}, 30)
    db.commit()
    d.set_baseline(db, platform="vmware", source_id=1, user="ayse")
    db.commit()
    _save(db, "h1", {"ntp": "b", "dns": "1"}, 5)            # baseline SONRASI değişiklik
    db.commit()
    ov = d.baseline_overview(db, platforms=["vmware"], with_diff=True)
    assert ov["count"] == 1 and ov["drifted"] == 1 and ov["drifted_by_kind"] == {"host": 1}
    it = ov["items"][0]
    assert it["status"] == "drift" and it["drift_count"] == 1 and it["baseline_by"] == "ayse"
    assert it["changes"][0]["path"] == "ntp" and it["changes"][0]["old"] == "a" and it["changes"][0]["new"] == "b"
    cmp = d.baseline_compare(db, platform="vmware", source_id=1, entity_kind="host", entity_ref="h1")
    assert cmp["change_count"] == 1 and cmp["same"] is False and cmp["baseline"]["baseline_by"] == "ayse"
    assert d.baseline_compare(db, platform="vmware", source_id=1, entity_kind="host", entity_ref="nope") is None


def test_changes_to_unbaselined_entities_are_explained(isolated_db):
    """Değişen ama baseline'ı olmayan varlık sapma sayısına girmez; payload bunu açıkça bildirir."""
    db = isolated_db
    _save(db, "h1", {"a": 1}, 30)
    _save(db, "vm1", {"cpu": 2}, 30, kind="vm")
    db.commit()
    d.set_baseline(db, platform="vmware", source_id=1, entity_kind="host", user="u")
    db.commit()
    _save(db, "vm1", {"cpu": 4}, 5, kind="vm")               # vm baseline'sız değişti
    db.commit()
    p = d.changes_payload(db, platforms=["vmware"], days=30)
    assert p["drifted_count"] == 0
    assert p["changed_entities"] == 1 and p["changed_unbaselined"] == 1
    assert p["changed_unbaselined_kinds"] == {"vm": 1}


def test_ack_hides_without_deleting_and_does_not_affect_drift(isolated_db):
    db = isolated_db
    _save(db, "h1", {"a": 1}, 30)
    db.commit()
    d.set_baseline(db, platform="vmware", source_id=1, user="u")
    db.commit()
    _save(db, "h1", {"a": 2}, 5)
    db.commit()
    row = d.list_changes(db, platforms=["vmware"])[0]
    assert d.ack_changes(db, [row["id"]], "ayse", platforms=["vmware"]) == 1
    db.commit()
    assert d.list_changes(db, platforms=["vmware"]) == []                         # varsayılan: gizli
    shown = d.list_changes(db, platforms=["vmware"], ack="all")
    assert len(shown) == 1 and shown[0]["acked"] and shown[0]["ack_by"] == "ayse"
    assert len(d.list_changes(db, platforms=["vmware"], ack="only")) == 1
    assert d.baseline_overview(db, platforms=["vmware"])["drifted"] == 1          # sapma etkilenmez
    assert db.query(VirtConfigSnapshot).count() == 2                              # hiçbir şey silinmedi
    p = d.changes_payload(db, platforms=["vmware"])
    assert p["count"] == 0 and p["acked_total"] == 1
    assert d.ack_changes(db, [row["id"]], "x", undo=True) == 1
    db.commit()
    assert len(d.list_changes(db, platforms=["vmware"])) == 1


def test_platform_scoping_and_limit_not_consumed_by_other_platform(isolated_db):
    db = isolated_db
    for i in range(3):
        _save(db, "n1", {"v": i}, 10 - i, kind="node", plat="ocp", src=9)
    _save(db, "h1", {"v": 0}, 20)
    _save(db, "h1", {"v": 1}, 1)
    db.commit()
    rows = d.list_changes(db, platforms=["vmware", "olvm", "ocp_virt"], limit=1)
    assert len(rows) == 1 and rows[0]["platform"] == "vmware"                    # ocp satırları limiti yemez


def test_prune_dry_run_and_protections(isolated_db):
    db = isolated_db
    for i in range(6):
        _save(db, "h1", {"v": i}, 24 * 400 - i * 24)         # hepsi 365 günden eski
    db.commit()
    first = db.query(VirtConfigSnapshot).order_by(VirtConfigSnapshot.captured_at).first()
    first.is_baseline = True                                  # baseline korunur
    db.commit()
    r = d.prune_snapshots(db, retention_days=365, keep_last=2, platforms=["vmware"], dry_run=True)
    assert r["dry_run"] and r["candidates"] == 3 and r["deleted"] == 0           # 6 - latest(1) - baseline(1) - keep_last(2 içinde latest)
    assert db.query(VirtConfigSnapshot).count() == 6
    r2 = d.prune_snapshots(db, retention_days=365, keep_last=2, platforms=["vmware"], dry_run=False)
    db.commit()
    assert r2["deleted"] == 3 and db.query(VirtConfigSnapshot).count() == 3
    assert db.query(VirtConfigSnapshot).filter(VirtConfigSnapshot.is_baseline.is_(True)).count() == 1
    assert db.query(VirtConfigSnapshot).filter(VirtConfigSnapshot.is_latest.is_(True)).count() == 1
