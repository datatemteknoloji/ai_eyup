"""Exadata DB tool'ları — envanter, domain, uydurma yok."""
from types import SimpleNamespace

from app.services.chat_data_status import SUCCESS, SUCCESS_EMPTY
from app.services.exadata_inventory import (
    exadata_health_overview,
    list_exadata_nodes,
    list_exadata_racks,
    parse_role,
    rack_health,
    role_value,
)
from app.services.agent.tools import domains_for_platform, tool_specs_read_only
from app.services.module_orchestrator import MODULE_TO_DOMAINS, MOD_EXADATA, plan_modules
from app.models.exadata import ExadataNodeRole


def test_parse_role_aliases():
    assert parse_role("cell") == ExadataNodeRole.STORAGE_CELL
    assert parse_role("compute") == ExadataNodeRole.COMPUTE_NODE
    assert parse_role("bogus") is None


def test_rack_health_rules():
    assert rack_health(["ONLINE", "OK"]) == "healthy"
    assert rack_health(["ONLINE", "CRITICAL"]) == "critical"
    assert rack_health(["WARNING"]) == "warning"
    assert rack_health([]) == "unknown"


def test_role_value_enum_and_str():
    assert role_value(ExadataNodeRole.STORAGE_CELL) == "storage_cell"
    assert role_value("compute_node") == "compute_node"


class _Q:
    def __init__(self, rows):
        self._rows = rows

    def options(self, *_a):
        return self

    def order_by(self, *_a):
        return self

    def filter(self, *_a):
        return self

    def join(self, *_a):
        return self

    def limit(self, *_a):
        return self

    def all(self):
        return self._rows


def test_empty_racks_is_success_empty():
    db = SimpleNamespace(query=lambda *_a, **_k: _Q([]))
    out = list_exadata_racks(db)
    assert out["ok"] is True
    assert out["data_status"] == SUCCESS_EMPTY
    assert out["racks"] == []
    assert "cell" in out["note"].lower() or "canlı" in out["note"].lower()


def test_health_empty_does_not_invent_asm():
    db = SimpleNamespace(query=lambda *_a, **_k: _Q([]))
    out = exadata_health_overview(db)
    assert out["data_status"] == SUCCESS_EMPTY
    assert out["rack_count"] == 0
    assert "uydurma" in out["note"] or "yok" in out["note"]


def test_list_nodes_invalid_role():
    db = SimpleNamespace(query=lambda *_a, **_k: _Q([]))
    out = list_exadata_nodes(db, role="mars")
    assert out["ok"] is False
    assert out["nodes"] == []


def test_list_nodes_with_row():
    rack = SimpleNamespace(name="X9-1")
    node = SimpleNamespace(
        id=1, rack_id=1, rack=rack, role=ExadataNodeRole.STORAGE_CELL,
        name="cel01", hostname="cel01", ip_address="10.0.0.8",
        ilom_ip=None, status="ONLINE", position_in_rack="U5",
        cpu_cores=32, memory_gb=128, storage_tb=40,
        cell_disk_info={"griddisks": 12}, server_id=None,
    )
    db = SimpleNamespace(query=lambda *_a, **_k: _Q([node]))
    out = list_exadata_nodes(db, role="cell")
    assert out["data_status"] == SUCCESS
    assert out["nodes"][0]["role"] == "storage_cell"
    assert out["nodes"][0]["cell_disk_info"] == {"griddisks": 12}
    assert "cellcli" in (out["nodes"][0]["note"] or "").lower()


def test_tools_on_exadata_not_linux():
    exa = {s["function"]["name"] for s in tool_specs_read_only(domains_for_platform("exadata"))}
    linux = {s["function"]["name"] for s in tool_specs_read_only(domains_for_platform("linux"))}
    virt = {s["function"]["name"] for s in tool_specs_read_only(domains_for_platform("virt"))}
    assert {"db_list_exadata_racks", "db_list_exadata_nodes", "exadata_health_overview"} <= exa
    assert "get_system_summary" in exa  # linked compute OS
    assert "db_list_exadata_racks" not in linux
    assert "db_list_exadata_racks" not in virt


def test_module_plan_exadata_opens_exadata_domain():
    assert "exadata" in MODULE_TO_DOMAINS[MOD_EXADATA]
    plan = plan_modules("exadata cell server durumu")
    assert "exadata" in plan.modules
    assert "exadata" in plan.domains
