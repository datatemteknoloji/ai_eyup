"""
Sanallaştırma karar katmanı: kontrol kataloğu, sürüm eşleme, komut taslağı
kaçışı, sohbet tool görünürlüğü ve onaylı düzeltme izin listesi.
"""
import pytest

from app.models.infra_finding import InfraFinding
from app.services.agent.tools import TOOLS, domains_for_platform, tool_specs, tool_specs_read_only
from app.services.findings.drafts import _ps, _sh, build_draft
from app.services.findings.registry import CHECKS, catalog, category_of
from app.services.virt_reference_checks import validate_package, version_affected
from app.services.virt_remediation import ACTIONS, TOOL_NAME, propose

NEW_READ_TOOLS = {"virt_capacity_simulate", "virt_placement_recommend", "virt_reclaim_summary",
                  "virt_health_findings", "virt_incident_timeline"}
DRAFT_KEYS = {"vmw_ha_enable", "vmw_ntp_set", "vmw_ntp_restart", "vmw_snapshot_remove",
              "vmw_ssh_stop", "vmw_syslog_set", "ocpv_eviction"}


# ── Katalog ──────────────────────────────────────────────────────────────────

def test_check_ids_are_namespaced_and_consistent():
    cats = {"capacity", "health", "reclaim", "compliance", "drift", "hardware", "security", "upgrade", "kb"}
    for cid, d in CHECKS.items():
        assert d.id == cid
        assert d.category in cats, cid
        assert d.severity in {"critical", "high", "medium", "low", "info"}, cid
        assert d.platforms and set(d.platforms) <= {"vmware", "olvm", "ocp_virt", "ocp"}, cid
        assert d.title_tr and d.title_en, cid
        assert category_of(cid) == d.category


def test_draft_keys_are_known():
    used = {d.draft for d in CHECKS.values() if d.draft}
    assert used <= DRAFT_KEYS


def test_catalog_localized():
    tr = {c["id"]: c["title"] for c in catalog("tr")}
    en = {c["id"]: c["title"] for c in catalog("en")}
    assert tr.keys() == en.keys() == CHECKS.keys()
    assert en["cap.cluster.n_plus_one"] == CHECKS["cap.cluster.n_plus_one"].title_en


# ── Sürüm eşleme (offline CVE / yükseltme paketi) ────────────────────────────

@pytest.mark.parametrize("version,ranges,expected", [
    ("7.0.3", [">=7.0,<7.0.3"], False),
    ("7.0.2", [">=7.0,<7.0.3"], True),
    ("7.0.3", ["<7.0.3c"], True),
    ("7.0.3d", ["<7.0.3c"], False),
    ("8.0", ["==8.0.0"], True),
    ("8.0.1", [">=7.0,<8.0", ">=8.0,<8.0.2"], True),
    ("", [">=7.0"], False),
    ("8.0.1", [], True),
])
def test_version_affected_ranges(version, ranges, expected):
    assert version_affected(version, ranges) is expected


def test_version_affected_fixed_build():
    assert version_affected("8.0.1", [">=8.0"], build="21560480", fixed_build="22088981") is True
    assert version_affected("8.0.1", [">=8.0"], build="22088981", fixed_build="22088981") is False


def test_reference_package_validation():
    assert validate_package("cve_feed", {"advisories": [{"id": "X", "products": []}]})[0]
    assert not validate_package("cve_feed", {"advisories": [{"id": "X"}]})[0]
    assert not validate_package("kb_feed", {"articles": [{"id": "1"}]})[0]
    assert not validate_package("bogus", {})[0]


# ── Komut taslakları ─────────────────────────────────────────────────────────

def test_quoting_helpers():
    assert _ps("a'b") == "'a''b'"
    assert _ps(None) == "''"
    assert _sh("a'b") == "'a'\"'\"'b'"


def _finding(**kw):
    base = dict(id=1, platform="vmware", source_id=1, source_name="vc", category="health",
                entity_kind="host", entity_ref="host-1", entity_name="esx01", result="fail",
                active=True, title="t", evidence={})
    base.update(kw)
    return InfraFinding(**base)


def test_draft_escapes_entity_names():
    f = _finding(check_id="vmw.cluster.ha_enabled", entity_kind="cluster", entity_name="Prod'; Remove-VM *")
    d = build_draft(None, f)
    assert d and d["executes"] is False and d["language"] == "powershell"
    assert "'Prod''; Remove-VM *'" in d["script"]
    assert d["rollback"]


def test_draft_snapshot_lists_each_snapshot():
    f = _finding(check_id="reclaim.vm.snapshot_age", category="reclaim", entity_kind="vm", entity_name="app01",
                 evidence={"snapshots": [{"name": "pre-patch", "created": "2025-01-01"}, {"name": "o'k", "created": "x"}]})
    script = build_draft(None, f)["script"]
    assert "-Name 'pre-patch'" in script and "-Name 'o''k'" in script


def test_draft_absent_for_checks_without_template():
    f = _finding(check_id="cap.cluster.n_plus_one", category="capacity", entity_kind="cluster")
    assert build_draft(None, f) is None


# ── Sohbet tool'ları ─────────────────────────────────────────────────────────

def test_new_tools_registered_read_only_in_vcenter_domain():
    assert NEW_READ_TOOLS <= TOOLS.keys()
    vc = {s["function"]["name"] for s in tool_specs_read_only(domains_for_platform("virt"))}
    assert NEW_READ_TOOLS <= vc
    linux = {s["function"]["name"] for s in tool_specs_read_only(domains_for_platform("linux"))}
    assert not (NEW_READ_TOOLS & linux)


def test_remediation_tool_hidden_from_llm():
    assert TOOL_NAME in TOOLS
    assert TOOLS[TOOL_NAME].llm_visible is False
    for specs in (tool_specs(), tool_specs_read_only(None), tool_specs_read_only(domains_for_platform("virt"))):
        assert TOOL_NAME not in {s["function"]["name"] for s in specs}


# ── Onaylı düzeltme izin listesi ─────────────────────────────────────────────

def test_actions_map_to_known_vmware_checks():
    for a in ACTIONS.values():
        assert a.platforms == ("vmware",)
        for cid in a.check_ids:
            assert cid in CHECKS, cid
        assert a.rollback_note


def test_propose_rejects_non_allowlisted_check():
    f = _finding(check_id="cap.cluster.n_plus_one", category="capacity")
    r = propose(None, f, action_id=None, params={}, user=None)
    assert r["ok"] is False and "izinli" in r["error"]


def test_propose_rejects_action_check_mismatch():
    f = _finding(check_id="vmw.host.ntp_running")
    r = propose(None, f, action_id="vmw.ssh_stop", params={}, user=None)
    assert r["ok"] is False


def test_propose_rejects_other_platforms_and_passing_findings():
    assert propose(None, _finding(check_id="reclaim.vm.snapshot_age", platform="olvm"),
                   action_id=None, params={}, user=None)["ok"] is False
    r = propose(None, _finding(check_id="vmw.host.ntp_running", result="pass"), action_id=None, params={}, user=None)
    assert r["ok"] is False and "fail" in r["error"]
