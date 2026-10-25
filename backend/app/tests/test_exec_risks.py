"""Risk sırası bulgu şiddeti, yaşı ve etkisindendir. Oturum satırı risk olmaz."""
from datetime import datetime, timedelta, timezone

from app.models.infra_finding import InfraFinding
from app.services.exec_risks import rank_findings


def _add(db, **kw):
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    row = InfraFinding(
        platform=kw.get("platform", "vmware"),
        source_id=kw.get("source_id", 1),
        source_name=kw.get("source_name", "office"),
        category="health",
        check_id=kw.get("check_id", "health.host"),
        entity_kind="host",
        entity_ref=kw.get("entity_ref", "host-1"),
        entity_name=kw.get("entity_name", "esx01"),
        result=kw.get("result", "fail"),
        severity=kw.get("severity", "critical"),
        title=kw.get("title", "Bellek eşiği aşıldı"),
        recommendation=kw.get("recommendation"),
        evidence=kw.get("evidence") or {},
        active=kw.get("active", True),
        first_seen=kw.get("first_seen", now - timedelta(days=kw.get("age", 10))),
    )
    db.add(row)
    db.commit()
    return row


def test_order_is_severity_times_age_times_impact(isolated_db):
    _add(isolated_db, entity_ref="old", title="Eski uyarı", severity="medium", age=40)
    _add(isolated_db, entity_ref="new", title="Yeni kritik", severity="critical", age=2)
    now = datetime(2026, 10, 25, tzinfo=timezone.utc)
    rows = rank_findings(isolated_db, now=now)
    assert [r["sentence"] for r in rows] == ["Eski uyarı", "Yeni kritik"]
    assert rows[0]["rank"] == 2 * 40 * 2
    assert rows[1]["rank"] == 5 * 2 * 3


def test_log_line_is_not_a_risk_sentence(isolated_db):
    _add(
        isolated_db,
        title="User DATATEM.LOCAL\\Administrator@192.168.1.129 logged in as python-requests/2.31.0",
        entity_name="192.168.1.129",
    )
    rows = rank_findings(isolated_db, now=datetime(2026, 10, 25, tzinfo=timezone.utc))
    assert rows[0]["sentence"] == "Açık bulgu"
    assert rows[0]["entity_name"] is None


def test_demo_and_synthetic_and_inactive_are_out(isolated_db):
    _add(isolated_db, entity_ref="demo", source_name="veeam demo", title="Demo bulgu")
    _add(isolated_db, entity_ref="fake", entity_name="ZZ-FAKE-host", title="Sahte")
    _add(isolated_db, entity_ref="hid", source_id=9, title="Sentetik kaynak")
    _add(isolated_db, entity_ref="off", active=False, title="Kapalı")
    _add(isolated_db, entity_ref="pass", result="pass", title="Geçen")
    _add(isolated_db, entity_ref="ok", title="Gerçek bulgu", source_id=2)
    rows = rank_findings(isolated_db, now=datetime(2026, 10, 25, tzinfo=timezone.utc), synthetic_source_ids={9})
    assert [r["sentence"] for r in rows] == ["Gerçek bulgu"]
