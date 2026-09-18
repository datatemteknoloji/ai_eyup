"""chat_charts — parse, overlay kuralları, SoT ayrımı (DB yok)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.chat_charts import (
    MAX_CHART_OBJECTS,
    detect_virt_kind,
    hours_to_range_key,
    match_named_entities,
    parse_chart_intent,
    resolve_os_targets,
    try_build_chat_charts,
)


def test_parse_implicit_requires_duration_and_metric():
    assert parse_chart_intent("cpu kullanımını göster") is None
    assert parse_chart_intent("son 1 saatlik durum") is None
    got = parse_chart_intent("son 1 saatlik cpu durumu")
    assert got is not None
    assert got["hours"] == 1.0
    assert "cpu" in got["groups"]
    assert got["explicit"] is False


def test_parse_explicit_defaults_hour_and_cpu_mem():
    got = parse_chart_intent("web01 ile web02 karşılaştır", explicit=True)
    assert got is not None
    assert got["hours"] == 1.0
    assert got["groups"] == ["cpu", "memory"]


def test_parse_cpu_and_memory_together():
    got = parse_chart_intent("son 8 saat cpu ve bellek grafiği")
    assert got is not None
    assert got["hours"] == 8.0
    assert "cpu" in got["groups"] and "memory" in got["groups"]


def test_hours_to_range_key_matches_monitoring():
    assert hours_to_range_key(0.25) == "15m"
    assert hours_to_range_key(1) == "1h"
    assert hours_to_range_key(8) == "8h"
    assert hours_to_range_key(24) == "24h"
    assert hours_to_range_key(168) == "7d"
    assert hours_to_range_key(720) == "30d"


def test_match_named_entities_longest_first_and_cap():
    names = ["web", "web-prod-01", "web-prod-02", "db"]
    found = match_named_entities("web-prod-01 ve web-prod-02 cpu", names)
    assert found == ["web-prod-01", "web-prod-02"]
    assert "web" not in found


def test_match_named_entities_caps_at_eight():
    inventory = [f"node-{i:02d}" for i in range(12)]
    msg = " ".join(inventory)
    found = match_named_entities(msg, inventory)
    assert len(found) == MAX_CHART_OBJECTS


def test_detect_virt_kind():
    assert detect_virt_kind("esxi host bellek") == "host"
    assert detect_virt_kind("datastore doluluk") == "datastore"
    assert detect_virt_kind("iki vm cpu") == "vm"


def test_resolve_os_targets_selected_not_whole_fleet():
    selected = [SimpleNamespace(id=1, name="web01", hostname=None, ip_address="10.0.0.1", vm_name=None)]
    pool = selected + [
        SimpleNamespace(id=2, name="web02", hostname=None, ip_address="10.0.0.2", vm_name=None)
    ]
    out = resolve_os_targets("son 1 saat cpu", selected=selected, pool=pool)
    assert [s.name for s in out] == ["web01"]


def test_resolve_os_targets_from_message():
    pool = [
        SimpleNamespace(id=1, name="alpha", hostname="alpha.local", ip_address="1.1.1.1", vm_name=None),
        SimpleNamespace(id=2, name="beta", hostname=None, ip_address="2.2.2.2", vm_name=None),
    ]
    out = resolve_os_targets("alpha ve beta son 1 saat cpu", pool=pool)
    assert {s.name for s in out} == {"alpha", "beta"}


def test_io_keyword_maps_to_disk_io_group():
    got = parse_chart_intent("carddrcdb01 son 24 saat cpu memory ve I/O /graph", explicit=True)
    assert got is not None
    assert "cpu" in got["groups"]
    assert "memory" in got["groups"]
    assert "disk_io" in got["groups"]


def test_resolve_linux_chart_hosts_prom_only(monkeypatch):
    up = {"carddrcdb01.sys.yapikredi.com.tr:9100": "1"}
    monkeypatch.setattr(
        "app.services.monitoring.prometheus_metrics.get_node_exporter_up_map",
        lambda: up,
    )
    from app.services.chat_charts import resolve_linux_chart_hosts
    hosts = resolve_linux_chart_hosts(
        "carddrcdb01 son 24 saat cpu /graph",
        pool=[],
    )
    assert len(hosts) == 1
    assert hosts[0].server is None
    assert hosts[0].instance == "carddrcdb01.sys.yapikredi.com.tr:9100"
    assert "carddrcdb01" in hosts[0].name.lower()


def test_try_build_prom_only_graph(monkeypatch):
    up = {"carddrcdb01.sys.yapikredi.com.tr:9100": "1"}
    monkeypatch.setattr(
        "app.services.monitoring.prometheus_metrics.get_node_exporter_up_map",
        lambda: up,
    )
    pts = [{"t": f"2026-09-12T10:0{i}:00Z", "v": float(i + 1)} for i in range(2)]

    def fake_prom(instance, metric_name, hours, **_k):
        assert "carddrcdb01" in instance
        return pts

    monkeypatch.setattr("app.services.chat_charts._prom_query_range_instance", fake_prom)
    out = try_build_chat_charts(
        MagicMock(),
        message="carddrcdb01 son 24 saat cpu /graph",
        platform="linux",
        pool=[],
        explicit=True,
    )
    assert out is not None
    assert out["charts"]
    assert "carddrcdb01" in out["summary_text"].lower() or "carddrcdb01" in (
        out["charts"][0].get("server_name") or ""
    )


def test_explicit_graph_without_targets_explains(monkeypatch):
    monkeypatch.setattr(
        "app.services.monitoring.prometheus_metrics.get_node_exporter_up_map",
        lambda: {},
    )
    db = MagicMock()
    out = try_build_chat_charts(db, message="grafik istiyorum", platform="linux", explicit=True)
    assert out is not None
    assert out["charts"] == []
    assert "sunucu" in out["summary_text"].lower()


def test_implicit_without_targets_falls_through(monkeypatch):
    monkeypatch.setattr(
        "app.services.monitoring.prometheus_metrics.get_node_exporter_up_map",
        lambda: {},
    )
    db = MagicMock()
    assert try_build_chat_charts(
        db, message="son 1 saat cpu", platform="linux", explicit=False,
    ) is None


def test_explicit_virt_without_names_explains(monkeypatch):
    db = MagicMock()
    monkeypatch.setattr("app.services.chat_charts._virt_inventory_names", lambda *_a, **_k: ["vm-a"])
    out = try_build_chat_charts(db, message="/yok", platform="virt", explicit=True)
    assert out is not None
    assert out["charts"] == []
    assert "VM" in out["summary_text"] or "vm" in out["summary_text"].lower()


def test_openshift_explicit_explains():
    db = MagicMock()
    out = try_build_chat_charts(db, message="cluster cpu", platform="openshift", explicit=True)
    assert out is not None
    assert "OpenShift" in out["summary_text"]


def test_os_overlay_two_servers_two_metrics(monkeypatch):
    pts = [{"t": f"2026-09-12T10:0{i}:00Z", "v": float(i)} for i in range(2)]

    def fake_fetch(_db, server, metric_name, hours, **_k):
        return pts, "timescale"

    monkeypatch.setattr("app.services.chat_charts._fetch_os_points", fake_fetch)
    monkeypatch.setattr("app.services.chat_charts._resolve_server_instance", lambda _s: None)
    s1 = SimpleNamespace(id=1, name="web01")
    s2 = SimpleNamespace(id=2, name="web02")
    from app.services.chat_charts import _build_os_charts
    charts, sources = _build_os_charts(MagicMock(), [s1, s2], 1.0, ["cpu", "memory"])
    assert sources == ["timescale"]
    assert len(charts) == 2
    labels0 = [s["label"] for s in charts[0]["series"]]
    assert "web01 — CPU Kullanımı" in labels0
    assert "web02 — CPU Kullanımı" in labels0
    assert charts[0]["unit"] == "%"
    assert charts[1]["unit"] == "%"
