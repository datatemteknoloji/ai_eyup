"""
ESXi host tablosu kolonları satırdaki gerçek alanlardan türemeli.

Sabit kolon listesiyle iki ayrı şikâyet oluşuyordu: kapasite sorusunda
"CPU % / Mem %" sütunları boş (—) görünüyor, donanım sağlığı sorusunda ise
istenen sensör alanları tabloya hiç yansımıyordu.
"""
from app.services.virt_inventory_contract import format_esx_host_table

CAPACITY_ROW = {
    "name": "192.168.1.101", "ip": "192.168.1.101", "version": "8.0.1",
    "cluster": None, "cpu_pct": 28.5, "mem_pct": 95.5, "ds_pct": 54.2,
    "vms_running": 18, "overall_status": "red", "connection_state": "connected",
    "hypervisor": "office",
}

SENSOR_ROW = {
    "name": "192.168.1.101", "overall_status": "red", "sensor_bad_count": 1,
    "bad_sensors": [{"name": "Power Supply 2"}], "config_issues": [],
}


def test_capacity_columns_render_actual_values():
    out = format_esx_host_table([CAPACITY_ROW], as_of="2026-09-05T17:00:00")
    assert "CPU %" in out and "28.5" in out
    assert "Mem %" in out and "95.5" in out
    assert "as_of" in out


def test_all_empty_columns_are_dropped():
    out = format_esx_host_table([CAPACITY_ROW])
    # cluster tüm satırlarda boş → sütun hiç açılmamalı
    assert "Cluster" not in out


def test_sensor_fields_are_rendered_when_requested():
    out = format_esx_host_table([SENSOR_ROW])
    assert "Sorunlu sensör" in out
    assert "Power Supply 2" in out
    assert "CPU %" not in out


def test_list_cells_are_truncated_readably():
    row = {"name": "h1", "bad_sensors": [{"name": f"S{i}"} for i in range(6)]}
    out = format_esx_host_table([row])
    assert "(+3)" in out


def test_empty_input_still_produces_header():
    out = format_esx_host_table([])
    assert "ESXi Host Envanteri" in out
    assert "| Host |" in out
