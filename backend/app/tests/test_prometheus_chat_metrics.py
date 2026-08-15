from app.services.monitoring.prometheus_metrics import (
    linux_live_preset_queries,
    linux_promql_selector,
    resolve_prometheus_instances_from_message,
)


UP = {
    "carddrcdb03.sys.yapikredi.com.tr:9100": "1",
    "dpractdbdrc:9100": "1",
    "10.1.2.3:9100": "1",
}


def test_short_name_maps_to_fqdn_instance():
    got = resolve_prometheus_instances_from_message(
        "carddrcdb03 cpu değerini getir", UP,
    )
    assert got == ["carddrcdb03.sys.yapikredi.com.tr:9100"]


def test_hostname_instance_kept_as_is():
    got = resolve_prometheus_instances_from_message(
        "dpractdbdrc ram ve disk", UP,
    )
    assert got == ["dpractdbdrc:9100"]


def test_fleet_question_does_not_invent_hosts():
    got = resolve_prometheus_instances_from_message(
        "tüm sunucularda en yüksek cpu", UP,
    )
    assert got == []


def test_cpu_preset_uses_avg_by_instance_and_single_selector():
    sel = linux_promql_selector(["dpractdbdrc:9100"])
    q = linux_live_preset_queries(sel)
    assert "avg by (instance)" in q["cpu"]
    assert '{mode="idle"}{' not in q["cpu"]
    assert 'instance="dpractdbdrc:9100"' in q["cpu"]
    assert "node_network_receive_bytes_total" in q["net_rx"]
    assert "node_network_transmit_bytes_total" in q["net_tx"]
