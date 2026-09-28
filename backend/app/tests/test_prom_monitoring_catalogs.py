"""OCP / virt / custom prom catalog smoke tests (no live Prometheus)."""
from app.services.openshift.ocp_prom_monitoring import catalog as ocp_catalog, run_ocp_prom_query
from app.services.virt_prom_monitoring import catalog as virt_catalog, run_virt_prom_query
from app.services.custom_prom_monitoring import run_custom_prom_query


def test_ocp_catalog_families():
    all_m = ocp_catalog()
    assert any(m["id"] == "gpu_util" for m in all_m)
    assert any(m["id"] == "vmi_cpu" for m in all_m)
    assert any(m["id"] == "vg_cluster_cpu_utilization" for m in all_m)
    gpu = ocp_catalog("gpu")
    assert all(m["family"] == "gpu" for m in gpu)
    kv = ocp_catalog("kubevirt")
    assert all(m["family"] == "kubevirt" for m in kv)
    vg = ocp_catalog("global")
    assert all(m["family"] == "views_global" for m in vg)
    assert len(vg) >= 26
    assert any(m["id"] == "vg_kubernetes_resource_count" for m in vg)
    assert any("CPU Utilization by namespace" in m["title"] for m in vg)
    nodes = ocp_catalog("nodes")
    assert len(nodes) >= 35
    ns = ocp_catalog("namespaces")
    assert len(ns) >= 25
    pods = ocp_catalog("pods")
    assert len(pods) >= 25


def test_ocp_templates_default_views():
    from app.services.openshift.ocp_prom_monitoring import templates
    tpls = templates()
    assert tpls[0]["id"] == "views"
    assert tpls[0].get("default") is True
    ids = {t["id"] for t in tpls}
    assert {"views", "gpu", "kubevirt"} <= ids


def test_ocp_prom_overview_unconfigured():
    # Canlı ortamda openshift kaynağı olabilir; yapı yapılandırılmışsa da geçerli cevap beklenir.
    out = run_ocp_prom_query(mode="overview")
    assert isinstance(out, dict)
    assert "configured" in out
    if out.get("configured") is False:
        assert out.get("source") is None or "yapılandır" in (out.get("note") or "").lower()
    else:
        assert out.get("templates")


def test_virt_catalog():
    cats = virt_catalog()
    assert any(m["id"] == "vm_cpu" for m in cats)


def test_virt_prom_unconfigured():
    out = run_virt_prom_query(mode="overview")
    assert out.get("configured") is False


def test_custom_prom_no_source():
    out = run_custom_prom_query(mode="list_sources")
    assert out.get("ok") is True
    assert isinstance(out.get("sources"), list)
