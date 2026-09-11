from app.services.chat_clause_check import (
    clause_tags_in_message,
    sufficiency_nudge,
    tool_covers,
    uncovered_clause_labels,
)


def test_single_topic_is_not_multi_clause():
    assert clause_tags_in_message("kaç VM var") == []
    assert uncovered_clause_labels("kaç VM var", ["db_list_vms"]) == []


def test_vm_and_openshift_needs_both_tools():
    q = "Bu VM OpenShift'in parçası mı ve diskleri neler, snapshot var mı?"
    tags = clause_tags_in_message(q)
    assert "openshift" in tags
    assert "snapshot" in tags
    missing = uncovered_clause_labels(q, ["db_list_vms"])
    assert "openshift" in missing
    assert "snapshot" in missing
    covered = uncovered_clause_labels(
        q, ["db_list_vms", "list_kubevirt_vms", "vcenter_snapshot_summary"],
    )
    assert covered == []


def test_perf_and_storage_partial():
    q = "VM neden yavaş ve datastore latency yüksek mi?"
    missing = uncovered_clause_labels(q, ["virt_bottleneck_diagnose"])
    assert "storage" in missing
    assert "perf" not in missing


def test_tool_covers_substring():
    assert tool_covers("openshift", ["list_ocp_pods"])
    assert not tool_covers("snapshot", ["db_list_vms"])


def test_iowait_and_slow_needs_cross_tool():
    q = "web01 iowait yüksek, VM neden yavaş?"
    tags = clause_tags_in_message(q)
    assert "guest_io" in tags
    assert "perf" in tags
    missing = uncovered_clause_labels(q, ["virt_bottleneck_diagnose"])
    assert "guest_io" in missing
    assert uncovered_clause_labels(q, ["linux_virt_io_correlate"]) == []


def test_exadata_and_perf_needs_exadata_tool():
    q = "Exadata cell server yavaş mı?"
    tags = clause_tags_in_message(q)
    assert "exadata" in tags
    assert "perf" in tags
    missing = uncovered_clause_labels(q, ["virt_bottleneck_diagnose"])
    assert "exadata" in missing
    assert uncovered_clause_labels(q, ["exadata_health_overview", "virt_bottleneck_diagnose"]) == []


def test_nudge_lists_missing():
    text = sufficiency_nudge(["snapshot", "openshift"])
    assert "snapshot" in text
    assert "openshift" in text
    assert "bitirme" in text
