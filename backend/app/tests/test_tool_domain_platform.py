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


_VIRT_DB_ONLY = {
    "db_list_vms",
    "db_vm_detail",
    "db_list_datastores",
    "db_list_esx_hosts",
    "db_list_clusters",
    "virt_health_overview",
    "virt_bottleneck_diagnose",
    "db_metric_trend",
    "db_virt_alarms",
    "db_virt_cross_match",
}


def _names(domains):
    return {s["function"]["name"] for s in tool_specs_read_only(domains)}


def test_virt_db_tools_hidden_on_linux_windows_ocp_platforms():
    for platform in ("linux", "windows", "openshift"):
        names = _names(domains_for_platform(platform))
        leaked = names & _VIRT_DB_ONLY
        assert not leaked, f"{platform} sızdırdı: {leaked}"


def test_virt_db_tools_visible_on_virt_platform():
    names = _names(domains_for_platform("virt"))
    assert _VIRT_DB_ONLY <= names


def test_virt_db_tools_hidden_on_linux_only_unified_plan():
    from app.services.unified_intent_router import route_unified

    q = (
        "olvm manager sunucusunun canlı SSH ile failed systemd unit'lerini tara; "
        "vCenter event listesine düşme."
    )
    ru = route_unified(q)
    assert "vcenter" not in ru.domains
    names = _names(ru.domains)
    assert not (names & _VIRT_DB_ONLY)
    assert "get_failed_services" in names or "run_diagnostic" in names


def test_virt_db_tools_visible_on_virt_only_unified_plan():
    from app.services.unified_intent_router import route_unified

    ru = route_unified(
        "Filodaki VM'lerin CPU kullanımı yüzde 90'ın üzerinde olanları sırala; "
        "anlık demiyorum, son sync yeterli."
    )
    assert "vcenter" in ru.domains
    names = _names(ru.domains)
    assert "db_list_vms" in names
    assert "db_virt_cross_match" in names


def test_linux_windows_compare_hides_virt_db():
    from app.services.unified_intent_router import route_unified

    ru = route_unified(
        "minio1 (Linux) ile Winserver01 (Windows) kaynak kullanımını karşılaştır; "
        "peki CPU? Windows'u Linux SSH'e veya VM QueryPerf'e kaydırma."
    )
    assert "vcenter" not in ru.domains
    assert "windows" in ru.domains and "linux" in ru.domains
    names = _names(ru.domains)
    assert not (names & _VIRT_DB_ONLY)
    assert "get_system_summary" in names


def test_shared_infra_tools_still_everywhere():
    for platform in ("linux", "windows", "openshift", "virt"):
        names = _names(domains_for_platform(platform))
        assert "db_list_critical_events" in names
        assert "prometheus_query" in names
