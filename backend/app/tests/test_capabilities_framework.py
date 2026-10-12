"""Dilim B: capability registry, invalidate, tool filtresi."""
from __future__ import annotations

import pytest

from app.services import capabilities as cap_mod
from app.services.agent import tools as tools_mod
from app.services.agent.tools import RiskLevel, Tool, TOOLS, tool_specs_read_only
from app.services.backup.registry import register_provider, capabilities_for_instance
from app.services.findings.registry import RESULT_NOT_APPLICABLE


@pytest.fixture(autouse=True)
def _isolate_from_live_instances(monkeypatch):
    """Testler canlı DB'deki gerçek/demo sağlayıcılardan etkilenmesin: yalnız `_test_*` kind'lar sayılır."""
    from app.services.backup import registry as breg
    real = breg.capabilities_for_instance
    monkeypatch.setattr(breg, "capabilities_for_instance",
                        lambda row: real(row) if str(getattr(row, "kind", "")).startswith("_test") else set())
    cap_mod.invalidate_capabilities()
    yield
    cap_mod.invalidate_capabilities()


def setup_function(_):
    cap_mod.invalidate_capabilities()


def teardown_function(_):
    TOOLS.pop("_test_backup_only_tool", None)
    cap_mod.invalidate_capabilities()


def test_capabilities_empty_without_instances():
    payload = cap_mod.capabilities_payload()
    assert payload["ok"] is True
    assert payload["has_backup"] is False
    assert "backup" not in payload["capabilities"]


def test_tool_without_capability_hidden(monkeypatch):
    TOOLS["_test_backup_only_tool"] = Tool(
        name="_test_backup_only_tool",
        description="test",
        parameters={"type": "object", "properties": {}},
        risk_level=RiskLevel.READ_ONLY,
        build_command=lambda a: "true",
        domains=frozenset({"vcenter"}),
        requires_capability=frozenset({"backup"}),
    )
    monkeypatch.setattr(cap_mod, "get_capabilities", lambda **k: frozenset())
    names = {s["function"]["name"] for s in tool_specs_read_only(domains=frozenset({"vcenter"}))}
    assert "_test_backup_only_tool" not in names

    monkeypatch.setattr(cap_mod, "get_capabilities", lambda **k: frozenset({"backup"}))
    names2 = {s["function"]["name"] for s in tool_specs_read_only(domains=frozenset({"vcenter"}))}
    assert "_test_backup_only_tool" in names2


def test_invalidate_refreshes_capabilities(monkeypatch):
    state = {"caps": frozenset()}

    def fake_collect():
        return set(state["caps"])

    monkeypatch.setattr(cap_mod, "_collect", fake_collect)
    cap_mod.invalidate_capabilities()
    assert "backup" not in cap_mod.get_capabilities(force_refresh=True)

    state["caps"] = frozenset({"backup", "backup.replica"})
    # cache dolu olsa bile invalidate sonrası yenilenmeli
    cap_mod.invalidate_capabilities()
    got = cap_mod.get_capabilities(force_refresh=True)
    assert "backup" in got


def test_disable_instance_clears_capability(db_session=None):
    """Enabled→disabled sonrası GET capabilities ve tool listesi güncellenir."""
    from app.core.database import SessionLocal, Base, engine
    from app.models.integration_instance import IntegrationInstance
    import app.models  # noqa: F401

    Base.metadata.create_all(bind=engine)
    db = SessionLocal()
    try:
        # demo kind capability kaydı
        class _P:
            kind = "_test_bk_kind"

            def capabilities(self):
                return {"backup", "backup.replica"}

            def test_connection(self):
                return None

            def sync(self, cursor):
                return cursor

            def health(self):
                return None

        register_provider("_test_bk_kind", lambda row: _P(), capabilities={"backup", "backup.replica"})
        row = IntegrationInstance(
            category="backup",
            kind="_test_bk_kind",
            label="demo",
            endpoint="https://demo.local",
            enabled=True,
            last_status="ok",
        )
        db.add(row)
        db.commit()
        cap_mod.invalidate_capabilities()
        assert "backup" in cap_mod.get_capabilities(force_refresh=True)

        TOOLS["_test_backup_only_tool"] = Tool(
            name="_test_backup_only_tool",
            description="test",
            parameters={"type": "object", "properties": {}},
            risk_level=RiskLevel.READ_ONLY,
            build_command=lambda a: "true",
            domains=frozenset({"vcenter"}),
            requires_capability=frozenset({"backup"}),
        )
        names = {s["function"]["name"] for s in tool_specs_read_only(domains=frozenset({"vcenter"}))}
        assert "_test_backup_only_tool" in names

        row.enabled = False
        db.commit()
        cap_mod.invalidate_capabilities()
        assert "backup" not in cap_mod.get_capabilities(force_refresh=True)
        names2 = {s["function"]["name"] for s in tool_specs_read_only(domains=frozenset({"vcenter"}))}
        assert "_test_backup_only_tool" not in names2
    finally:
        db.query(IntegrationInstance).filter(IntegrationInstance.kind == "_test_bk_kind").delete()
        db.commit()
        db.close()
        TOOLS.pop("_test_backup_only_tool", None)
        cap_mod.invalidate_capabilities()


def test_result_not_applicable_constant_export():
    assert isinstance(RESULT_NOT_APPLICABLE, str)
    assert RESULT_NOT_APPLICABLE in ("not_applicable",)