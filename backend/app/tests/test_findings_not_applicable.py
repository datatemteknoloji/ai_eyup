"""Dilim B: not_applicable skor/payda dışı + RESULTS sabit kullanımı."""
from __future__ import annotations

from app.services.findings import registry as reg
from app.services.findings.registry import (
    MEASURED_RESULTS,
    RESULT_FAIL,
    RESULT_NOT_APPLICABLE,
    RESULT_NOT_MEASURABLE,
    RESULT_PASS,
    RESULTS,
)
from app.services.virt_compliance import compliance_report


def test_results_tuple_contains_not_applicable():
    assert RESULT_NOT_APPLICABLE in RESULTS
    assert RESULT_NOT_APPLICABLE not in MEASURED_RESULTS
    assert RESULT_PASS in MEASURED_RESULTS and RESULT_FAIL in MEASURED_RESULTS


def test_no_string_literal_not_applicable_in_registry_module():
    """registry dışında literal yasak değil; RESULTS kaynağı registry olmalı."""
    src = open(reg.__file__, encoding="utf-8").read()
    # Tanım satırı dışında tekrar literal olmasın
    assert src.count('"not_applicable"') == 1


def _result_leaves(node):
    """Koşullu ifadede yalnız DEĞER dallarını (body/orelse) gez; koşul kısmındaki karşılaştırma literalleri sonuç değildir."""
    import ast
    if isinstance(node, ast.IfExp):
        return _result_leaves(node.body) + _result_leaves(node.orelse)
    return [node]


def test_findingdraft_result_never_uses_string_literals():
    """A2: FindingDraft(result=...) tüm üretici modüllerde RESULT_* sabitleriyle verilir (literal yok)."""
    import ast
    import importlib

    mods = ("app.services.virt_health_checks", "app.services.virt_reference_checks",
            "app.services.virt_capacity_planner", "app.services.ocp_insights",
            "app.services.backup.rpo_engine", "app.services.backup.extras", "app.services.findings.drafts")
    bad = []
    for m in mods:
        mod = importlib.import_module(m)
        tree = ast.parse(open(mod.__file__, encoding="utf-8").read())
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "FindingDraft"):
                continue
            arg = node.args[4] if len(node.args) > 4 else next((k.value for k in node.keywords if k.arg == "result"), None)
            if arg is None:
                continue
            for n in _result_leaves(arg):
                if isinstance(n, ast.Constant) and n.value in RESULTS:
                    bad.append(f"{m}:{n.lineno} {n.value!r}")
    assert not bad, bad


def test_compliance_score_ignores_not_applicable(monkeypatch):
    items = [
        {"result": RESULT_PASS, "refs": ["ISO27001:A.8.6"], "exception": None},
        {"result": RESULT_FAIL, "refs": ["ISO27001:A.8.6"], "exception": None},
        {"result": RESULT_NOT_APPLICABLE, "refs": ["ISO27001:A.8.6"], "exception": None},
        {"result": RESULT_NOT_MEASURABLE, "refs": ["ISO27001:A.8.6"], "exception": None},
    ]

    def fake_query(*_a, **_k):
        return items

    monkeypatch.setattr("app.services.virt_compliance.query_findings", fake_query)
    rep = compliance_report(db=None, platforms=["vmware"])  # type: ignore[arg-type]
    ctrl = next(c for c in rep["controls"] if c["control"] == "ISO27001:A.8.6")
    assert ctrl["counts"][RESULT_NOT_APPLICABLE] == 1
    assert ctrl["counts"][RESULT_NOT_MEASURABLE] == 1
    # 1 pass / (1 pass + 1 fail) = 50
    assert ctrl["score_pct"] == 50.0


def test_summarize_skips_not_applicable_from_category_totals(monkeypatch):
    from types import SimpleNamespace
    from app.services.findings import store as st

    class FakeQ:
        def filter(self, *a, **k):
            return self

        def all(self):
            return [
                SimpleNamespace(
                    platform="vmware", source_id=1, entity_ref="a", check_id="x",
                    result=RESULT_FAIL, category="health", severity="high",
                    last_seen=None, active=True,
                ),
                SimpleNamespace(
                    platform="vmware", source_id=1, entity_ref="b", check_id="y",
                    result=RESULT_NOT_APPLICABLE, category="health", severity="info",
                    last_seen=None, active=True,
                ),
            ]

    class FakeDB:
        def query(self, *_):
            return FakeQ()

    monkeypatch.setattr(st, "exception_keys", lambda db: set())
    monkeypatch.setattr(st, "closure_metrics", lambda *a, **k: {"closed": 0})   # sahte DB; metrik ayrı test edilir
    s = st.summarize_findings(FakeDB())  # type: ignore[arg-type]
    assert s["not_applicable"] == 1
    assert s["by_category"]["health"]["total"] == 1
