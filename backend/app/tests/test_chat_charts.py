"""chat_charts — parse, overlay kuralları, SoT ayrımı (DB yok)."""
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.services.chat_charts import (
    MAX_CHART_OBJECTS,
    detect_virt_kind,
    hours_to_range_key,
    match_named_entities,
    parse_chart_intent,
    parse_rank_intent,
    resolve_os_targets,
    try_build_chat_charts,
    _normalize_virt_chart_groups,
    _rank_metric_virt,
)


def test_parse_implicit_requires_duration_and_metric():
    assert parse_chart_intent("cpu kullanımını göster") is None
    assert parse_chart_intent("son 1 saatlik durum") is None
    got = parse_chart_intent("son 1 saatlik cpu durumu")
    assert got is not None
    assert got["hours"] == 1.0
    assert "cpu" in got["groups"]
    assert got["explicit"] is False


def test_parse_rank_intent_top_n():
    assert parse_rank_intent("web01 cpu") is None
    r = parse_rank_intent("en yüksek I/O yapan 5 vm /grafik")
    assert r is not None
    assert r["top_n"] == 5
    assert r["order"] == "highest"
    r2 = parse_rank_intent("top 3 host cpu")
    assert r2["top_n"] == 3
    r3 = parse_rank_intent("en düşük bellek 2 sunucu")
    assert r3["top_n"] == 2 and r3["order"] == "lowest"
    r4 = parse_rank_intent("en yüksek cpu")
    assert r4["top_n"] == 5


def test_normalize_virt_disk_io_to_iops():
    assert _normalize_virt_chart_groups(["disk_io", "cpu"]) == ["iops", "cpu"]
    assert _rank_metric_virt("vm", ["disk_io"]) == "disk_read_iops"


def test_parse_explicit_defaults_hour_and_cpu_mem():
    got = parse_chart_intent("web01 ile web02 karşılaştır", explicit=True)
    assert got is not None
    assert got["hours"] == 24.0
    assert got["groups"] == ["cpu", "memory"]


def test_parse_explicit_default_is_24h():
    got = parse_chart_intent("cpu /grafik", explicit=True)
    assert got is not None
    assert got["hours"] == 24.0


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
    monkeypatch.setattr("app.services.chat_charts._virt_inventory_refs", lambda *_a, **_k: [("vm-a", "1:vm-a")])
    monkeypatch.setattr("app.services.chat_charts.parse_rank_intent", lambda *_a, **_k: None)
    out = try_build_chat_charts(db, message="/yok", platform="virt", explicit=True)
    assert out is not None
    assert out["charts"] == []
    assert "VM" in out["summary_text"] or "vm" in out["summary_text"].lower()


def test_virt_rank_then_chart(monkeypatch):
    db = MagicMock()
    pts = [{"t": f"2026-09-12T10:0{i}:00Z", "v": float(i + 1)} for i in range(2)]
    monkeypatch.setattr(
        "app.services.chat_charts._virt_inventory_refs",
        lambda *_a, **_k: [("vm-hot", "hv:1:vm-hot"), ("vm-cold", "hv:1:vm-cold")],
    )
    monkeypatch.setattr(
        "app.services.chat_charts._rank_virt_names",
        lambda *_a, **_k: (["vm-hot", "vm-cold"], "_Top-2_"),
    )

    def fake_build(*_a, **_k):
        names = set(_k.get("names") or [])
        assert names == {"hv:1:vm-hot", "hv:1:vm-cold"}
        return ([{
            "type": "timeseries",
            "title": "IOPS",
            "unit": "IOPS",
            "series": [{"metric_name": "x", "label": "vm-hot", "points": pts}],
        }], ["virt"])

    monkeypatch.setattr("app.services.chat_charts._build_virt_charts", fake_build)
    out = try_build_chat_charts(
        db,
        message="en yüksek I/O yapan 5 vm /grafik",
        platform="virt",
        explicit=True,
    )
    assert out is not None
    assert len(out["charts"]) == 1
    assert "Top-2" in out["summary_text"] or "vm-hot" in out["summary_text"]


def test_linux_rank_then_chart(monkeypatch):
    db = MagicMock()
    pts = [{"t": f"2026-09-12T10:0{i}:00Z", "v": float(i + 1)} for i in range(2)]
    s1 = SimpleNamespace(id=1, name="web-hot")
    s2 = SimpleNamespace(id=2, name="web-cold")
    from app.services.chat_charts import ChartHost

    monkeypatch.setattr(
        "app.services.monitoring.prometheus_metrics.get_node_exporter_up_map",
        lambda: {},
    )
    monkeypatch.setattr(
        "app.services.chat_charts.resolve_linux_chart_hosts",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "app.services.chat_charts._rank_linux_hosts",
        lambda *_a, **_k: (
            [ChartHost(name="web-hot", server=s1), ChartHost(name="web-cold", server=s2)],
            "_Top-2_",
        ),
    )
    monkeypatch.setattr(
        "app.services.chat_charts._build_linux_charts",
        lambda *_a, **_k: ([{
            "type": "timeseries",
            "title": "CPU",
            "unit": "%",
            "series": [{"metric_name": "x", "label": "web-hot", "points": pts}],
        }], ["timescale"]),
    )
    out = try_build_chat_charts(
        db,
        message="en yüksek cpu 2 sunucu /grafik",
        platform="linux",
        pool=[s1, s2],
        explicit=True,
    )
    assert out is not None
    assert len(out["charts"]) == 1
    assert "web-hot" in out["summary_text"]


def test_openshift_explicit_without_names_explains(monkeypatch):
    db = MagicMock()
    cluster = MagicMock()
    cluster.id = 1
    cluster.name = "ocp-lab"
    monkeypatch.setattr(
        "app.services.chat_charts._ocp_resolve_cluster",
        lambda *_a, **_k: cluster,
    )
    monkeypatch.setattr(
        "app.services.chat_charts._ocp_inventory_refs",
        lambda *_a, **_k: [("worker-1", "1:node:worker-1")],
    )
    monkeypatch.setattr("app.services.chat_charts.parse_rank_intent", lambda *_a, **_k: None)
    out = try_build_chat_charts(db, message="cpu /grafik", platform="openshift", explicit=True)
    assert out is not None
    assert out["charts"] == []
    assert (
        "node" in out["summary_text"].lower()
        or "pod" in out["summary_text"].lower()
        or "Top-N" in out["summary_text"]
    )


def test_ocp_rank_then_chart(monkeypatch):
    db = MagicMock()
    cluster = MagicMock()
    cluster.id = 1
    cluster.name = "ocp-lab"
    pts = [{"t": f"2026-09-12T10:0{i}:00Z", "v": float(i + 1)} for i in range(2)]
    monkeypatch.setattr(
        "app.services.chat_charts._ocp_resolve_cluster",
        lambda *_a, **_k: cluster,
    )
    monkeypatch.setattr(
        "app.services.chat_charts._ocp_inventory_refs",
        lambda *_a, **_k: [],
    )
    monkeypatch.setattr(
        "app.services.chat_charts._rank_ocp_refs",
        lambda *_a, **_k: (
            ["1:node:w1", "1:node:w2"],
            ["w1", "w2"],
            "_Top-2_",
        ),
    )
    monkeypatch.setattr(
        "app.services.chat_charts._build_ocp_charts",
        lambda *_a, **_k: ([{
            "type": "timeseries",
            "title": "CPU",
            "unit": "%",
            "series": [{"metric_name": "x", "label": "w1", "points": pts}],
        }], ["ocp_resource_metrics"]),
    )
    out = try_build_chat_charts(
        db,
        message="en yüksek cpu 2 node /grafik",
        platform="openshift",
        explicit=True,
    )
    assert out is not None
    assert len(out["charts"]) == 1


def test_named_target_skips_rank(monkeypatch):
    """İsim verilmişse Top-N sıralama çağrılmaz (mevcut düzen)."""
    db = MagicMock()
    called = {"rank": False}
    monkeypatch.setattr(
        "app.services.chat_charts._virt_inventory_refs",
        lambda *_a, **_k: [("vm-a", "hv:1:vm-a")],
    )

    def boom(*_a, **_k):
        called["rank"] = True
        return [], ""

    monkeypatch.setattr("app.services.chat_charts._rank_virt_names", boom)
    monkeypatch.setattr(
        "app.services.chat_charts._build_virt_charts",
        lambda *_a, **_k: ([{
            "type": "timeseries",
            "title": "CPU",
            "unit": "%",
            "series": [{"metric_name": "x", "label": "vm-a", "points": [
                {"t": "2026-09-12T10:00:00Z", "v": 1.0},
                {"t": "2026-09-12T10:01:00Z", "v": 2.0},
            ]}],
        }], ["virt"]),
    )
    out = try_build_chat_charts(
        db, message="vm-a son 1 saat cpu /grafik", platform="virt", explicit=True,
    )
    assert out is not None
    assert called["rank"] is False


def test_openshift_named_builds_charts(monkeypatch):
    db = MagicMock()
    cluster = MagicMock()
    cluster.id = 1
    cluster.name = "ocp-lab"
    pts = [{"t": f"2026-09-12T10:0{i}:00Z", "v": float(i + 1)} for i in range(2)]

    monkeypatch.setattr(
        "app.services.chat_charts._ocp_resolve_cluster",
        lambda *_a, **_k: cluster,
    )
    monkeypatch.setattr(
        "app.services.chat_charts._ocp_inventory_refs",
        lambda *_a, **_k: [("worker-1", "1:node:worker-1")],
    )

    def fake_build(*_a, **_k):
        return ([{
            "type": "timeseries",
            "title": "CPU",
            "unit": "%",
            "series": [{"metric_name": "w:cpu", "label": "worker-1 — CPU %", "points": pts}],
        }], ["ocp_resource_metrics"])

    monkeypatch.setattr("app.services.chat_charts._build_ocp_charts", fake_build)
    out = try_build_chat_charts(
        db, message="worker-1 son 1 saat cpu /grafik", platform="openshift", explicit=True,
    )
    assert out is not None
    assert len(out["charts"]) == 1
    assert "ocp-lab" in out["summary_text"] or out["charts"][0]["series"]


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
