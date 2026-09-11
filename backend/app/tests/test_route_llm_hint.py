"""Düşük güven routing LLM — birleşim kuralları, ezme yok."""
from app.services.module_orchestrator import ModulePlan, plan_modules, plan_with_modules
from app.services.route_llm_hint import (
    apply_route_llm_hint,
    merge_route_hint,
    parse_hinted_modules,
    should_ask_route_hint,
)
from app.services.unified_intent_router import route_unified


def test_parse_modules_json_and_aliases():
    assert parse_hinted_modules('{"modules":["vcenter","ocp"]}') == ("virt", "openshift")
    assert parse_hinted_modules("önce metin {\"modules\":[\"linux\"]} sonra") == ("linux",)
    assert parse_hinted_modules("değil json") == ()
    assert parse_hinted_modules('{"modules":["mars"]}') == ()


def test_should_ask_only_low_confidence():
    explore = plan_modules("disk durumu")
    assert explore.reason.startswith("auto_explore")
    assert should_ask_route_hint(explore)

    strong = plan_modules("vcenter datastore kapasitesi")
    assert strong.confidence > 0.70
    assert not should_ask_route_hint(strong)

    skip = ModulePlan(
        mode="knowledge", modules=(), domains=frozenset({"infra"}),
        confidence=0.4, reason="skip_ctx",
    )
    assert not should_ask_route_hint(skip)


def test_auto_explore_cannot_shrink():
    plan = plan_modules("disk durumu")
    assert plan.modules == ("virt", "linux")
    merged = merge_route_hint(plan, ("linux",), "disk durumu")
    assert merged.modules == ("virt", "linux")
    assert merged.reason.startswith("auto_explore")


def test_auto_explore_can_add():
    plan = plan_modules("disk durumu")
    merged = merge_route_hint(plan, ("virt", "linux", "windows"), "disk durumu")
    assert "windows" in merged.modules
    assert "virt" in merged.modules
    assert "linux" in merged.modules
    assert merged.reason.endswith("+llm_add")


def test_tie_may_pick_subset():
    plan = plan_with_modules(
        "vm ve pod",
        ("virt", "openshift"),
        reason="auto_multi_tie:virt+openshift",
        confidence=0.62,
    )
    picked = merge_route_hint(plan, ("openshift",), "sadece pod")
    assert picked.modules == ("openshift",)
    assert "+llm_pick" in picked.reason


def test_no_signal_can_become_live():
    plan = ModulePlan(
        mode="knowledge", modules=(), domains=frozenset({"infra"}),
        confidence=0.7, reason="no_module_signal",
    )
    merged = merge_route_hint(plan, ("linux",), "sunucu neden ağır")
    assert merged.modules == ("linux",)
    assert merged.mode == "single"


def test_soft_single_does_not_replace():
    plan = plan_with_modules(
        "selinux ne durumda",
        ("linux",),
        reason="single:linux",
        confidence=0.65,
    )
    merged = merge_route_hint(plan, ("windows",), "selinux ne durumda")
    assert merged.modules[0] == "linux"
    assert "windows" in merged.modules


def test_apply_skips_when_circuit_open(monkeypatch):
    plan = plan_modules("disk durumu")
    called = {"n": 0}

    monkeypatch.setattr("app.services.runtime_settings.get_bool", lambda *_a, **_k: True)
    monkeypatch.setattr("app.core.config.remote_llm_enabled", lambda: True)
    monkeypatch.setattr("app.services.llm_availability.is_open", lambda: True)

    def _boom(*_a, **_k):
        called["n"] += 1
        raise AssertionError("LLM çağrılmamalı")

    monkeypatch.setattr("app.services.llm_gateway.generate_sync", _boom)
    out = apply_route_llm_hint("disk durumu", plan)
    assert out.modules == plan.modules
    assert called["n"] == 0


def test_apply_uses_llm_then_merges(monkeypatch):
    plan = ModulePlan(
        mode="knowledge", modules=(), domains=frozenset({"infra"}),
        confidence=0.7, reason="no_module_signal",
    )
    monkeypatch.setattr("app.services.runtime_settings.get_bool", lambda *_a, **_k: True)
    monkeypatch.setattr("app.core.config.remote_llm_enabled", lambda: False)
    monkeypatch.setattr(
        "app.services.llm_gateway.generate_sync",
        lambda **_k: {"response": '{"modules":["linux"]}', "done": True},
    )
    monkeypatch.setattr(
        "app.services.llm_gateway.resolve_model_for_tier",
        lambda *_a, **_k: ("fast-model", "fast"),
    )
    out = apply_route_llm_hint("sunucu neden ağır", plan)
    assert out.modules == ("linux",)


def test_route_unified_high_conf_does_not_call_llm(monkeypatch):
    called = {"n": 0}

    def _gen(**_k):
        called["n"] += 1
        return {"response": '{"modules":["windows"]}', "done": True}

    monkeypatch.setattr("app.services.llm_gateway.generate_sync", _gen)
    route = route_unified("vcenter datastore kapasitesi")
    assert called["n"] == 0
    assert "vcenter" in route.domains
    assert route.confidence > 0.70


def test_flag_off_skips(monkeypatch):
    plan = plan_modules("disk durumu")
    monkeypatch.setattr("app.services.runtime_settings.get_bool", lambda *_a, **_k: False)
    monkeypatch.setattr(
        "app.services.llm_gateway.generate_sync",
        lambda **_k: (_ for _ in ()).throw(AssertionError("kapalıyken çağrı")),
    )
    assert apply_route_llm_hint("disk durumu", plan) is plan
