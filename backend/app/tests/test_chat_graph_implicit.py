"""Adım 8G — «grafikte göster» /graph yazmadan gerçek grafik (K8 değişti); varsayılan 6 saat; VM tespiti; Top-5."""
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services.chat_charts import (
    DEFAULT_CHART_HOURS,
    graph_request_kind,
    has_vm_word,
    normalize_duration_text,
    parse_chart_intent,
    try_build_chat_charts,
    _has_scope_noun,
)

PTS = [{"t": f"2026-10-27T10:0{i}:00Z", "v": float(i + 1)} for i in range(2)]


# ── G1: niyet tespiti ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q", [
    "en çok cpu kaynağı tüketen vmleri grafikte göster",
    "en çok cpu kullanan 5 vm'i grafik olarak çiz",
    "web01 cpu grafiğini göster",
    "sunucuların bellek kullanımını grafikle göster",
    "cpu kullanımını grafikte göster",
    "bana en yüksek cpu kullanan hostların grafiğini ver",
    "show the top 5 VMs by cpu as a chart",
    "Draw a chart of VM CPU usage",
    "plot memory of web01",
    "disk gecikmesini grafik olarak göster",
    "web01 son 2 saat cpu grafiğini göster",
    "Network trafiğini grafikle gösterir misin?",
])
def test_graph_request_kind_chart(q):
    assert graph_request_kind(q) == "chart"


@pytest.mark.parametrize("q", [
    "Bu grafik ne demek?",
    "grafik nedir",
    "grafiği nasıl okurum",
    "/diagram VM topolojisi çiz",
    "Kaç VM var?",
    "Grafana nedir",
    "cpu kullanımını göster",           # grafik sözcüğü yok
    "/graph web01 cpu",                 # slash → OutputDirective yolu
    "",
])
def test_graph_request_kind_none(q):
    assert graph_request_kind(q) is None


# ── G6: zaman serisi olmayanlar sabit cümleye gider ────────────────────────────────────

@pytest.mark.parametrize("q", [
    "Pod restart sayılarını çubuk grafikle göster",
    "VM'lerin dağılımını pasta grafikle göster",
    "Cluster başına VM sayısını grafik olarak çiz",
    "Draw a pie chart of VM counts",
    "en çok cpu kullanan 5 vm çubuk grafik göster",
])
def test_graph_request_kind_unsupported(q):
    assert graph_request_kind(q) == "unsupported"


def test_unsupported_does_not_build_chart():
    assert try_build_chat_charts(MagicMock(), message="Pod restart sayılarını çubuk grafikle göster",
                                 platform="unified", pool=[]) is None


# ── G2: varsayılan 6 saat + süre ifadeleri ──────────────────────────────────────────────

def test_default_is_six_hours():
    assert DEFAULT_CHART_HOURS == 6.0
    got = parse_chart_intent("cpu kullanımını grafikte göster", explicit=True)
    assert got["hours"] == 6.0 and got["hours_defaulted"] is True


@pytest.mark.parametrize("q,hours", [
    ("web01 son 2 saat cpu", 2.0),
    ("web01 cpu son bir saat", 1.0),
    ("web01 cpu son iki saat", 2.0),
    ("web01 cpu yarım saat", 0.5),
    ("web01 cpu son 3 gün", 72.0),
    ("web01 cpu son hafta", 168.0),
    ("web01 cpu last 2 hours", 2.0),
    ("web01 cpu 90 minutes", 1.5),
    ("web01 cpu 12h", 12.0),
    ("web01 cpu son on iki saat", 12.0),
])
def test_duration_expressions(q, hours):
    got = parse_chart_intent(q, explicit=True)
    assert got["hours"] == hours
    assert not got.get("hours_defaulted")


def test_duration_over_limit_is_clamped_and_flagged():
    got = parse_chart_intent("web01 cpu son 3 ay", explicit=True)
    assert got["hours"] == 720.0 and got["clamped"] is True


def test_normalize_does_not_touch_other_text():
    assert normalize_duration_text("web01 cpu") == "web01 cpu"


# ── G4: VM sözcüğü ekli biçimleri ───────────────────────────────────────────────────────

@pytest.mark.parametrize("q", ["vmleri göster", "vm'leri göster", "VM'ler", "top vms", "5 vm cpu", "vm cpu"])
def test_has_vm_word_true(q):
    assert has_vm_word(q)


@pytest.mark.parametrize("q", ["vmware nedir", "avm", "cpu"])
def test_has_vm_word_false(q):
    assert not has_vm_word(q)


@pytest.mark.parametrize("q", ["vmleri", "sanal makineleri", "sunucuları", "hostlar", "node'lar", "podları", "datastore"])
def test_scope_noun(q):
    assert _has_scope_noun(q)


def test_scope_noun_not_vmware():
    assert not _has_scope_noun("vmware cpu")


# ── G3/G4: örtük grafik → sanallaştırma yolu + Top-5 + not ──────────────────────────────

def _patch_virt(monkeypatch, captured):
    monkeypatch.setattr("app.services.chat_charts._virt_inventory_refs",
                        lambda *_a, **_k: [("vm-hot", "hv:1:vm-hot"), ("vm-cold", "hv:1:vm-cold")])
    monkeypatch.setattr("app.services.chat_charts._virt_inventory_names",
                        lambda *_a, **_k: ["vm-hot", "vm-cold"])

    def fake_rank(*_a, **kw):
        captured["rank"] = kw
        return (["vm-hot", "vm-cold"], "_Top-2_")

    def fake_build(*_a, **kw):
        captured["build"] = kw
        return ([{"type": "timeseries", "title": "CPU", "unit": "%",
                  "series": [{"metric_name": "x", "label": "vm-hot", "points": PTS}]}], ["vcenter"])

    monkeypatch.setattr("app.services.chat_charts._rank_virt_names", fake_rank)
    monkeypatch.setattr("app.services.chat_charts._build_virt_charts", fake_build)


def test_user_question_routes_to_virt_vm_top5_default_6h(monkeypatch):
    cap = {}
    _patch_virt(monkeypatch, cap)
    out = try_build_chat_charts(
        MagicMock(), message="en çok cpu kaynağı tüketen vmleri grafikte göster",
        platform="unified", pool=[], explicit=False,
    )
    assert out is not None and len(out["charts"]) == 1
    assert cap["rank"]["kind"] == "vm" and cap["rank"]["top_n"] == 5 and cap["rank"]["order"] == "highest"
    assert cap["rank"]["hours"] == 6.0 and cap["build"]["hours"] == 6.0
    assert "Süre belirtilmediği" in out["summary_text"]
    assert out["intents"][0] == "chart"


def test_vm_apostrophe_form_also_routes_to_virt(monkeypatch):
    cap = {}
    _patch_virt(monkeypatch, cap)
    out = try_build_chat_charts(
        MagicMock(), message="en çok cpu kullanan vm'leri grafikte göster",
        platform="unified", pool=[], explicit=False,
    )
    assert out is not None and cap["rank"]["kind"] == "vm"


def test_no_target_but_scope_noun_defaults_top5_with_note(monkeypatch):
    cap = {}
    _patch_virt(monkeypatch, cap)
    out = try_build_chat_charts(
        MagicMock(), message="sanal makinelerin cpu grafiğini göster son 2 saat",
        platform="unified", pool=[], explicit=False,
    )
    assert out is not None
    assert cap["rank"]["top_n"] == 5 and cap["rank"]["hours"] == 2.0
    assert "Hedef belirtmediğiniz" in out["summary_text"]
    assert "Süre belirtilmediği" not in out["summary_text"]


def test_no_target_no_scope_noun_explains_instead_of_guessing(monkeypatch):
    cap = {}
    _patch_virt(monkeypatch, cap)
    out = try_build_chat_charts(
        MagicMock(), message="bunu grafikte göster", platform="virt", pool=[], explicit=False,
    )
    assert out is not None and out["charts"] == []
    assert "rank" not in cap


def test_linux_host_named_in_unified_stays_linux(monkeypatch):
    """«web01 vm'i cpu grafiğini göster»: ad yalnız Linux envanterinde → Linux yolu (virt'e düşmez)."""
    from app.services.chat_charts import ChartHost
    s1 = SimpleNamespace(id=1, name="web01")
    monkeypatch.setattr("app.services.chat_charts._virt_inventory_names", lambda *_a, **_k: ["vm-a"])
    monkeypatch.setattr("app.services.chat_charts.resolve_linux_chart_hosts",
                        lambda *_a, **_k: [ChartHost(name="web01", server=s1)])
    monkeypatch.setattr("app.services.chat_charts._build_linux_charts",
                        lambda *_a, **_k: ([{"type": "timeseries", "title": "CPU", "unit": "%",
                                             "series": [{"metric_name": "x", "label": "web01", "points": PTS}]}],
                                           ["timescale"]))
    monkeypatch.setattr("app.services.chat_charts._build_virt_charts",
                        lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("virt yoluna düşmemeli")))
    out = try_build_chat_charts(
        MagicMock(), message="web01 vm'i cpu grafiğini göster", platform="unified", pool=[s1], explicit=False,
    )
    assert out is not None and "web01" in out["summary_text"]


# ── G7: dürüst başlık ───────────────────────────────────────────────────────────────

def test_expanded_window_is_declared(monkeypatch):
    cap = {}
    _patch_virt(monkeypatch, cap)
    monkeypatch.setattr(
        "app.services.chat_charts._build_virt_charts",
        lambda *_a, **_k: ([{"type": "timeseries", "title": "CPU — Son 1 gün", "unit": "%",
                             "series": [{"metric_name": "x", "label": "vm-hot", "points": PTS}]}],
                           ["vcenter", "expanded_24h"]),
    )
    out = try_build_chat_charts(
        MagicMock(), message="vm-hot cpu grafiğini göster son 2 saat", platform="virt", explicit=False,
    )
    assert out is not None
    assert "yeterli örnek yok" in out["summary_text"] and "1 gün" in out["summary_text"]


def test_clamped_note(monkeypatch):
    cap = {}
    _patch_virt(monkeypatch, cap)
    out = try_build_chat_charts(
        MagicMock(), message="en çok cpu kullanan vmleri grafikte göster son 3 ay", platform="unified", pool=[],
    )
    assert out is not None and "üst sınırı" in out["summary_text"]


# ── G5: sahte hariç ────────────────────────────────────────────────────────────────

def test_rank_virt_excludes_synthetic_hypervisors(monkeypatch):
    from app.services import chat_charts as cc
    seen = {}

    def fake_trend(db, **kw):
        seen.update(kw)
        return {"items": [{"name": "real-vm"}]}

    monkeypatch.setattr("app.services.virt_trend_query.run_metric_trend", fake_trend)
    monkeypatch.setattr("app.services.synthetic_scope.synthetic_hypervisor_ids", lambda db: {8, 10})
    names, note = cc._rank_virt_names(MagicMock(), kind="vm", groups=["cpu"], hours=6, top_n=5, order="highest")
    assert names == ["real-vm"] and seen["exclude_hypervisor_ids"] == [8, 10]
    assert "6 saat" in note


def test_rank_linux_excludes_synthetic_servers(monkeypatch):
    from app.services import chat_charts as cc
    monkeypatch.setattr("app.services.synthetic_scope.synthetic_server_ids", lambda db: {2})
    db = MagicMock()
    db.execute.return_value.mappings.return_value.all.return_value = [{"server_id": 1, "value": 9.0}]
    pool = [SimpleNamespace(id=1, name="real"), SimpleNamespace(id=2, name="zz-fake")]
    hosts, _ = cc._rank_linux_hosts(db, pool=pool, groups=["cpu"], hours=6, top_n=5, order="highest")
    ids_param = db.execute.call_args[0][1]["ids"]
    assert ids_param == [1] and [h.name for h in hosts] == ["real"]


# ── kısa anahtar sözcük tuzağı: «kaynağı» içindeki «ağ» ağ grafiği tetiklemesin ─────────────

def test_short_keyword_inside_word_does_not_add_network():
    got = parse_chart_intent("en çok cpu kaynağı tüketen vmleri grafikte göster", explicit=True)
    assert got["groups"] == ["cpu"]


@pytest.mark.parametrize("q,expected", [
    ("ağ trafiği grafikte göster", "network"),
    ("vCPU grafiğini göster", "cpu"),
    ("ram kullanımını göster", "memory"),
])
def test_short_keywords_still_work_at_word_start(q, expected):
    assert expected in parse_chart_intent(q, explicit=True)["groups"]


def test_program_or_dagilim_do_not_match():
    assert parse_chart_intent("program çalışmasını son 2 saat göster") is None      # «ram» sözcük içinde → metrik yok
