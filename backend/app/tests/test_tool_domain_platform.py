"""
Platform → tool domain eşlemesi.

Tanınmayan bir platform adı sessizce Linux setine düşüyordu; o sohbette tüm
vCenter araçları kaybolduğu için model "canlı veri mevcut değil" cevabı
üretiyordu. Eşanlamlılar burada güvenceye alınır.
"""
import pytest

from app.services.agent.tools import domains_for_platform, tool_specs_read_only


@pytest.mark.parametrize("platform", [
    "virt", "virtualization", "vCenter", "VMware", "hypervisor", " sanallastirma ",
])
def test_virtualization_aliases_expose_vcenter_tools(platform):
    domains = domains_for_platform(platform)
    assert "vcenter" in domains
    names = {s["function"]["name"] for s in tool_specs_read_only(domains)}
    assert {"db_list_esx_hosts", "db_list_clusters", "virt_health_overview",
            "db_metric_trend", "vcenter_property_read"} <= names


def test_openshift_aliases():
    assert "openshift" in domains_for_platform("ocp")
    assert "openshift" in domains_for_platform("k8s")


def test_unified_has_no_domain_filter():
    assert domains_for_platform("unified") is None


def test_unknown_platform_falls_back_to_linux():
    assert domains_for_platform("bilinmeyen") == domains_for_platform("linux")


def test_trend_tool_available_in_every_platform_chat():
    for platform in ("linux", "windows", "openshift", "virt"):
        names = {
            s["function"]["name"]
            for s in tool_specs_read_only(domains_for_platform(platform))
        }
        assert "infra_report" in names
        assert "knowledge_search" in names
