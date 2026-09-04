"""P0-P3 aksiyon planı düzeltmeleri için hedefli regresyon testleri.

Bkz. sohbet: "10 soruluk gerçek kullanıcı testi" sonrası çıkarılan aksiyon
planının P0-P3 maddeleri. Her test, ilgili maddenin kod seviyesindeki kök
neden düzeltmesini doğrular (uçtan uca chat testleri ayrıca manuel/agentic
olarak da doğrulanmıştır — bkz. sohbet geçmişi).
"""
from __future__ import annotations

import re

import pytest


# ── P0-6: vCenter QA_RULES snapshot regex + virt_inventory_contract exclusion ──

def test_qa_rules_snapshot_regex_matches_natural_phrasing():
    """'VM'lerde aktif snapshot var mı, kaç tane?' artık h_snapshot_vms'e düşmeli.

    Önceki regresyon: bu soru hiçbir QA_RULES deseniyle eşleşmiyordu, bu yüzden
    virt_inventory_contract'ın genel 'vm' + 'kaç' -> KIND_VM_LIST fallback'i
    devreye girip ilgisiz bir VM listesi döndürüyordu.
    """
    from app.services.hypervisor_intelligence import QA_RULES, _normalize_virt_question

    q = "vCenter'daki VM'lerde aktif snapshot var mı, kaç tane?"
    qn = _normalize_virt_question(q)
    matched = None
    for pattern, handler in QA_RULES:
        if re.search(pattern, qn, re.I):
            matched = handler.__name__
            break
    assert matched == "h_snapshot_vms"


@pytest.mark.parametrize(
    "q",
    [
        "kaç snapshot var?",
        "snapshot sayısı ne kadar?",
        "aktif snapshot var mı?",
    ],
)
def test_qa_rules_snapshot_regex_additional_phrasings(q):
    from app.services.hypervisor_intelligence import QA_RULES, _normalize_virt_question

    qn = _normalize_virt_question(q)
    matched = any(re.search(pattern, qn, re.I) for pattern, handler in QA_RULES if handler.__name__ == "h_snapshot_vms")
    assert matched, f"snapshot deseni eşleşmedi: {q!r}"


def test_virt_inventory_contract_excludes_snapshot_questions():
    """Defansif katman: snapshot/olay/alarm sorguları VM_LIST/VM_DISK'e hiç düşmemeli."""
    from app.services.virt_inventory_contract import detect_virt_inventory_kind

    assert detect_virt_inventory_kind("VM'lerde aktif snapshot var mı, kaç tane?") is None
    assert detect_virt_inventory_kind("son 24 saatte kritik alarm var mı?") is None
    assert detect_virt_inventory_kind("hangi vm'lerde eski snapshot var, kaç tane?") is None


def test_virt_inventory_contract_still_detects_plain_vm_list():
    """Snapshot exclusion, alakasız düz VM listesi sorularını bozmamalı."""
    from app.services.virt_inventory_contract import detect_virt_inventory_kind, KIND_VM_LIST

    assert detect_virt_inventory_kind("tüm vm'leri listele") == KIND_VM_LIST


# ── P0-3: db_list_critical_events tool kaydı ────────────────────────────────

def test_db_list_critical_events_tool_registered_with_infra_domain():
    from app.services.agent import tools as tool_mod

    assert "db_list_critical_events" in tool_mod.TOOLS
    tool = tool_mod.TOOLS["db_list_critical_events"]
    assert tool.domains == frozenset({"infra"})
    assert tool.risk_level.name == "READ_ONLY"


# ── P1-8: çok parçalı / çapraz domain soru tespiti ──────────────────────────

@pytest.mark.parametrize(
    "q,expected",
    [
        ("NVME_DS'de hangi VM'lerin diskleri var ve bu VM'lerden biri OpenShift cluster'ının parçası mı?", True),
        ("NVME_DS'de hangi VM'lerin diskleri var?", False),
        ("bu vm'ler ile openshift node'ları arasında bir ilişki var mı?", True),
        ("tüm vm'leri listele", False),
    ],
)
def test_has_unaddressed_cross_domain_clause(q, expected):
    from app.services.unified_tool_chat import _has_unaddressed_cross_domain_clause

    assert _has_unaddressed_cross_domain_clause(q, None) is expected


# ── P0-1/P0-2: OpenShiftClient last_error ayrımı ────────────────────────────

def test_ocp_client_describe_http_error():
    from app.services.openshift.ocp_client import OpenShiftClient

    class _FakeResp:
        def __init__(self, code, text=""):
            self.status_code = code
            self.text = text

    assert "401" in OpenShiftClient._describe_http_error(_FakeResp(401))
    assert "403" in OpenShiftClient._describe_http_error(_FakeResp(403))
    assert "500" in OpenShiftClient._describe_http_error(_FakeResp(500, "boom"))


def test_ocp_client_last_error_initialized():
    from app.services.openshift.ocp_client import OpenShiftClient

    c = OpenShiftClient(api_url="https://example.invalid:6443", token="dummy")
    assert c.last_error == ""
