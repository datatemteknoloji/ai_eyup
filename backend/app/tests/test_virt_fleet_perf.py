"""Virt filo merdiven — canlı kelime + coverage; DB/API yok."""
from datetime import datetime, timezone

from app.services.virt_fleet_perf import (
    wants_live_virt_sample,
    source_footnote,
    _has_coverage,
)


def test_wants_live_keywords():
    assert wants_live_virt_sample("canlı CPU top 20") is True
    assert wants_live_virt_sample("şu an ready nedir") is True
    assert wants_live_virt_sample("en çok CPU tüketen VM'ler") is False
    assert wants_live_virt_sample("CPU kullanımı %90 üzeri") is False
    assert wants_live_virt_sample("anlık demiyorum, son sync yeterli") is False
    assert wants_live_virt_sample(
        "olvm manager canlı SSH ile failed systemd unit tara"
    ) is False
    assert wants_live_virt_sample(
        "Office vCenter'da şu an canlı CPU ready top 20"
    ) is True


def test_coverage_requires_any_key():
    rows = [{"name": "a", "cpu_usage_pct": None, "cpu_ready_pct": 1.2}]
    assert _has_coverage(rows, ["cpu_ready_pct"]) is True
    assert _has_coverage(rows, ["cpu_usage_pct"]) is False
    assert _has_coverage([], ["cpu_usage_pct"]) is False
    assert _has_coverage(rows, []) is True


def test_fetch_fleet_skips_db_when_live(monkeypatch):
    from app.services import virt_fleet_perf as vfp

    monkeypatch.setattr(
        vfp, "list_latest_vm_perf_db",
        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("db")),
    )
    import app.services.vcenter_vm_performance as perf
    monkeypatch.setattr(
        perf, "fetch_live_vm_stats",
        lambda _db: {"vms": [{"name": "x", "cpu_usage_pct": 9}], "errors": []},
    )
    out = vfp.fetch_fleet_vm_stats(object(), "canlı cpu top", required_any=["cpu_usage_pct"])
    assert out["source"] == "live"
    assert out["vms"][0]["name"] == "x"


def test_footnote_db_vs_live():
    db = source_footnote({"source": "db", "as_of": datetime(2026, 1, 1, tzinfo=timezone.utc)})
    assert "metrik sync" in db
    assert "canlı" in db
    live = source_footnote({"source": "live"})
    assert "QueryPerf" in live or "anlık" in live
