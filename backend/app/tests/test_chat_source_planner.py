from app.services.chat_source_planner import plan_sources, clamp_domains, build_followup_suggestions


def test_linux_scope_excludes_windows_and_ocp():
    p = plan_sources("web01 neden yavaş?", scope="linux")
    assert "windows" not in p.domains
    assert "openshift" not in p.domains
    assert "linux" in p.domains
    assert "prometheus" in p.sources
    assert p.need_prometheus is True


def test_inventory_skips_rag_and_live():
    p = plan_sources("Linux sunucuları listele", scope="linux")
    assert p.intent == "inventory"
    assert p.need_rag is False
    assert p.need_live is False
    assert "db" in p.sources


def test_unified_can_include_vcenter_and_ocp():
    p = plan_sources(
        "VMware VM'yi OpenShift Virtualization'a taşıyabilir miyim?",
        scope="unified",
    )
    assert "vcenter" in p.domains or "openshift" in p.domains


def test_clamp_linux():
    d = clamp_domains("linux", frozenset({"linux", "windows", "openshift", "infra"}))
    assert "windows" not in d
    assert "openshift" not in d


def test_suggestions_are_rule_based():
    p = plan_sources("pod crashloop oluyor", scope="openshift")
    items = build_followup_suggestions(p)
    assert items
    assert all("label" in i for i in items)
