from app.services.monitoring.prometheus_metrics import (
    chat_metric_col_keys,
    format_joined_metric_table,
    join_series_by_instance,
    linux_live_preset_queries,
    linux_promql_selector,
    parse_prom_chat_intent,
    resolve_prometheus_instances_from_message,
)


UP = {
    "carddrcdb03.sys.yapikredi.com.tr:9100": "1",
    "dpractdbdrc:9100": "1",
    "10.1.2.3:9100": "1",
    "oprbigdata3.kfs.local:9100": "1",
    "oprbigdata5.kfs.local:9100": "1",
    "oprbigdata13.kfs.local:9100": "1",
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


def test_prefix_matches_cluster_hosts():
    got = resolve_prometheus_instances_from_message(
        "oprbigdata cpu ve ram", UP,
    )
    assert got == [
        "oprbigdata3.kfs.local:9100",
        "oprbigdata5.kfs.local:9100",
        "oprbigdata13.kfs.local:9100",
    ]


def test_metric_word_is_not_a_hostname():
    got = resolve_prometheus_instances_from_message("cpu ram disk", UP)
    assert got == []


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
    assert "node_memory_MemAvailable_bytes" in q["mem_avail"]
    assert "node_disk_read_bytes_total" in q["disk_read"]


def test_intent_short_metric_is_preset_family():
    intent = parse_prom_chat_intent("cpu ve ram getir")
    assert intent["depth"] == "preset"
    assert intent["families"] == {"cpu", "memory"}


def test_intent_general_resources_uses_all_presets():
    intent = parse_prom_chat_intent("kaynak kullanımı nasıl")
    assert intent["depth"] == "preset"
    assert intent["families"] == {"cpu", "memory", "disk", "load", "network"}


def test_intent_family_detail():
    intent = parse_prom_chat_intent("disk detay oprbigdata")
    assert intent["depth"] == "family"
    assert intent["families"] == {"disk"}


def test_intent_all_node():
    intent = parse_prom_chat_intent("en kapsamlı metrikler")
    assert intent["depth"] == "all_node"
    assert "cpu" in intent["families"]


def test_join_series_one_row_per_instance():
    rows = join_series_by_instance({
        "cpu": [
            {"instance": "a:9100", "value": 10},
            {"instance": "b:9100", "value": 20},
        ],
        "memory": [
            {"instance": "a:9100", "value": 40},
        ],
    })
    assert set(rows) == {"a:9100", "b:9100"}
    assert rows["a:9100"]["cpu"] == 10
    assert rows["a:9100"]["memory"] == 40
    assert "memory" not in rows["b:9100"]


def test_joined_table_empty_cell_not_missing_scrape():
    rows = {
        "a:9100": {"cpu": 11.0, "memory": 22.0},
        "b:9100": {"cpu": 33.0},
    }
    text = format_joined_metric_table(
        rows, [("cpu", "CPU%"), ("memory", "RAM%")],
    )
    assert "| a:9100 | 11.0 | 22.0 |" in text
    assert "| b:9100 | 33.0 |  |" in text
    assert "JOIN" in text
    assert "cpu" in {k for k, _ in chat_metric_col_keys({"cpu"}, depth="preset")}
