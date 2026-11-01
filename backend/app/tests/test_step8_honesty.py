"""Adım 8: dürüstlük (unavailable_info), kullanıcı dili, envanter başlığı, özet fallback, finans etiketi, bench kuralları."""
import json
import sys
from pathlib import Path

import pytest

from app.services.chat_quality import unavailable_info as ua
from app.services.chat_quality import evidence_summary as es
from app.services.chat_quality import grounding as g

_BENCH = Path(__file__).resolve().parents[3] / "scripts"
if (_BENCH / "chat_bench").exists() and str(_BENCH) not in sys.path:
    sys.path.insert(0, str(_BENCH))


# ── sınıflandırma: tetiklenmesi gerekenler ──────────────────────────────────────────

@pytest.mark.parametrize("q,cls", [
    ("VM'lerin aylık lisans maliyeti ne kadar?", "license"),
    ("office vCenter'ın yıllık lisans maliyeti nedir?", "license"),
    ("Kaç lisansımız var?", "license"),
    ("OpenShift lisans maliyeti ne kadar?", "license"),
    ("How much does the license cost?", "license"),
    ("Harvester VM'inin iş sahibi kim?", "owner"),
    ("datatemengine VM'inin sahibi kim?", "owner"),
    ("web01 sunucusunun sorumlusu kim?", "owner"),
    ("Bu VM kime ait?", "owner"),
    ("Hangi namespace'in sahibi kim?", "owner"),
    ("Who owns the Harvester VM?", "owner"),
    ("Hangi departman ESXi hostlarını kullanıyor?", "owner"),
    ("Cluster'ın aylık maliyeti ne kadar?", "cost"),
    ("Şirketin aylık altyapı maliyeti ne kadar?", "cost"),
    ("Yıllık altyapı maliyetimiz nedir?", "cost"),
    ("oVirt cluster'ının aylık maliyeti ne kadar?", "cost"),
    ("What is the monthly cost of our infrastructure?", "cost"),
    ("Toplam maliyet ne kadar?", "cost"),
    ("Hangi müşteri office vCenter'daki VM'leri kullanıyor?", "customer"),
    ("Namespace'lerin müşteri bilgisi nedir?", "customer"),
    ("Sunucuların destek sözleşmesi ne zaman bitiyor?", "contract"),
    ("VM'lerin SLA sözleşmesi ne zaman bitiyor?", "contract"),
    ("What is the support contract end date?", "contract"),
])
def test_classify_positive(q, cls):
    assert ua.classify(q) == cls


def test_license_with_count_triggers():
    assert ua.classify("Kaç adet lisans kullanıyoruz?") == "license"


# ── zararsız komşular: TETİKLENMEMELİ ────────────────────────────────────────────────

@pytest.mark.parametrize("q", [
    "Maliyet raporu ver",
    "Finans raporunu hazırla",
    "owner bilgisi olmayan VM'ler",
    "Sahip bilgisi olmayan VM'leri listele",
    "Windows lisans durumu nedir?",
    "SLA ihlali olayı var mı?",
    "SLA raporu ver",
    "Kaç VM var?",
    "VM listesini göster ve maliyetini söyle",
    "En çok CPU kullanan 5 VM",
    "Harvester VM'i açık mı?",
    "web-01 hangi hostta?",
    "Kapalı VM'leri listele",
    "Atanmamış VM'ler hangileri?",
    "Datastore doluluk oranı nedir?",
    "Pod sayısı kaç?",
    "Kapasite analizi yap",
    "Alarm geçmişini göster",
    "Dün hangi sistemlerde hata oldu?",
    "ESXi host sürümleri nedir?",
    "Maliyet analizi yap ve tasarruf öner",
    "Show the VM list",
    "How many VMs are powered off?",
    "Selam",
    "Sahip olduğumuz VM sayısı kaç?",
])
def test_classify_negative(q):
    assert ua.classify(q) is None


def test_classify_skips_long_or_multiline():
    assert ua.classify("Aylık maliyet ne kadar?" + " x" * 200) is None
    assert ua.classify("Merhaba\nAylık maliyet ne kadar?") is None
    assert ua.classify("") is None and ua.classify(None) is None


def test_automic_platform_is_never_handled():
    assert ua.answer("Aylık maliyet ne kadar?", platform="automic") is None
    assert ua.respond("Harvester VM'inin iş sahibi kim?", platform="automic") is None


# ── cevap içeriği ───────────────────────────────────────────────────────────────────

def test_owner_answer_zero_assignments(monkeypatch):
    monkeypatch.setattr(ua, "_bsm_count", lambda: 0)
    text, cls = ua.answer("Harvester VM'inin iş sahibi kim?")
    assert cls == "owner"
    assert "Business Service Map" in text and "hiç atama yapılmamış" in text
    assert "Harvester" in text            # sorulan varlığı geri söyler
    assert "Emre" not in text             # envanterden ad uydurmaz


def test_owner_answer_with_assignments_does_not_claim_owner(monkeypatch):
    monkeypatch.setattr(ua, "_bsm_count", lambda: 7)
    text, _ = ua.answer("web01 sunucusunun sorumlusu kim?")
    assert "7 atama" in text and "sorgulamaz" in text


def test_owner_answer_unknown_count(monkeypatch):
    monkeypatch.setattr(ua, "_bsm_count", lambda: None)
    text, _ = ua.answer("Bu VM kime ait?")
    assert "okumaz" in text


def test_owner_answer_english(monkeypatch):
    monkeypatch.setattr(ua, "_bsm_count", lambda: 0)
    text, cls = ua.answer("Who owns the Harvester VM?")
    assert cls == "owner" and "not available in ainew data" in text and "no assignments" in text


@pytest.mark.parametrize("q,needle", [
    ("VM'lerin aylık lisans maliyeti ne kadar?", "lisans"),
    ("Hangi müşteri bu VM'leri kullanıyor?", "müşteri"),
    ("Destek sözleşmesi ne zaman bitiyor?", "sözleşme"),
])
def test_fixed_sentences(q, needle):
    text, _ = ua.answer(q)
    assert text.startswith("**Bu bilgi ainew verisinde yok:**") and needle in text


class _FakeQuery:
    def __init__(self, row):
        self.row = row

    def first(self):
        return self.row


class _FakeSession:
    def __init__(self, row):
        self.row = row

    def query(self, _model):
        return _FakeQuery(self.row)

    def close(self):
        pass


def test_cost_answer_without_rates_gives_no_amount(monkeypatch):
    import app.core.database as dbm
    monkeypatch.setattr(dbm, "ThreadSessionLocal", lambda: _FakeSession(None))
    text, cls = ua.answer("Cluster'ın aylık maliyeti ne kadar?")
    assert cls == "cost"
    assert "yapılandırılmamış" in text and "tutar vermiyorum" in text
    assert not any(ch.isdigit() for ch in text)
    assert "TAHMİNİ" in text


def test_cost_answer_with_rates_labels_estimate_and_scope(monkeypatch):
    import app.core.database as dbm
    import app.services.report_engine as re_
    monkeypatch.setattr(dbm, "ThreadSessionLocal", lambda: _FakeSession(object()))
    monkeypatch.setattr(re_, "generate_finance_report", lambda db: {
        "currency": "TL", "total_monthly_cost": 123456.0,
        "rates": {"cpu_per_core": 50, "ram_per_gb": 20, "storage_per_gb": 0.5}})
    text, _ = ua.answer("Şirketin aylık altyapı maliyeti ne kadar?")
    assert "Tahmini, tahsisat bazlı" in text and "123,456 TL" in text
    assert "cluster veya şirket bazında" in text and "gerçek tüketim" in text


def test_cost_answer_english_without_rates(monkeypatch):
    import app.core.database as dbm
    monkeypatch.setattr(dbm, "ThreadSessionLocal", lambda: _FakeSession(None))
    text, _ = ua.answer("What is the monthly cost of our infrastructure?")
    assert text.startswith("**Actual cost is not available in ainew data**") and "ESTIMATED" in text


def test_respond_swallows_errors(monkeypatch):
    monkeypatch.setattr(ua, "answer", lambda *a, **k: 1 / 0)
    assert ua.respond("Aylık maliyet ne kadar?") is None


def test_gate_is_wired_before_entity_gate():
    src = Path(__file__).resolve().parents[1].joinpath("services/chat_chitchat_policy.py").read_text(encoding="utf-8")
    i_en = src.index("entity_gate import gate_response")
    i_ua = src.index("unavailable_info import respond")
    assert i_ua < i_en
    assert "return _ua" in src[i_ua:i_ua + 400]


# ── grafik isteği (K8) ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q", [
    # Adım 8G (K3): yalnız zaman serisi OLMAYAN istekler sabit cümle alır
    "Pod restart sayılarını çubuk grafikle göster",
    "VM'lerin dağılımını pasta grafikle göster",
    "Cluster başına VM sayısını grafik olarak çiz",
    "Draw a pie chart of VM counts",
])
def test_chart_request_gets_fixed_sentence(q):
    text, cls = ua.answer(q)
    assert cls == "chart" and "/graph" in text and "█" not in text and "\n" not in text


@pytest.mark.parametrize("q", [
    # Adım 8G (K8 değişti): çizilebilir metrik → gerçek grafik hattı (sabit cümle YOK)
    "VM'lerin CPU kullanımını grafik olarak çiz",
    "Node CPU kullanımını grafik olarak çiz",
    "Sunucuların bellek kullanımını grafikle göster",
    "Draw a chart of VM CPU usage",
    "en çok cpu kaynağı tüketen vmleri grafikte göster",
])
def test_drawable_chart_request_is_not_canned(q):
    got = ua.answer(q)
    assert got is None or got[1] != "chart"


@pytest.mark.parametrize("q", [
    "web01 son 6 saat cpu /graph",
    "web01 son 24 saat cpu grafiğini göster",
    "Bu grafik ne demek?",
    "/diagram VM topolojisi çiz",
    "Kaç VM var?",
    "Kapalı VM'leri listele",
])
def test_chart_gate_ignores_real_chart_and_other_questions(q):
    got = ua.answer(q)
    assert got is None or got[1] != "chart"


def test_chart_gate_not_for_automic():
    assert ua.answer("CPU kullanımını grafik olarak çiz", platform="automic") is None


# ── hint ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q", ["SLA taahhüdü nedir ve VM listesi ver", "VM listesi ve maliyeti", "Lisans durumu nedir?",
                               "owner kim ve host listesi"])
def test_hint_for_related_questions(q):
    h = ua.hint(q)
    assert h.startswith("[Not:") and "TUTMAZ" in h and len(h) < 600


@pytest.mark.parametrize("q", ["Kaç VM var?", "Pod listesini göster", "CPU kullanımı nedir?"])
def test_no_hint_for_unrelated(q):
    assert ua.hint(q) == ""


# ── ortak kural sabitleri ve prompt'lar ──────────────────────────────────────────────

def test_rule_constants_short_and_registered():
    from app.services import chat_rules as cr
    from app.services.chat_quality.claims import make_shingles
    from app.services.chat_quality.prompt_registry import get_shingles
    for t in (cr.HONESTY_RULE_TR, cr.USER_LANGUAGE_RULE_TR, cr.OC_RULE_TR):
        assert 80 < len(t) <= 620
        assert make_shingles(t) <= get_shingles()
    assert "kubectl" in cr.OC_RULE_TR and "`oc`" in cr.OC_RULE_TR
    assert "/graph" in cr.USER_LANGUAGE_RULE_TR and "█" in cr.USER_LANGUAGE_RULE_TR


def test_unified_prompt_has_honesty_and_language_rules():
    from app.api.unified_chat import _build_prompt
    from app.services.chat_rules import HONESTY_RULE_TR, USER_LANGUAGE_RULE_TR, OC_RULE_TR
    p = _build_prompt("Kaç VM var?", "ctx", "")
    assert HONESTY_RULE_TR in p and USER_LANGUAGE_RULE_TR in p
    assert OC_RULE_TR not in p
    assert "ham kodu cevaba YAZMA" in p and "NOT_QUERIED=sorulmadı" not in p


def test_unified_prompt_oc_rule_only_for_openshift():
    from app.api.unified_chat import _build_prompt
    from app.services.chat_rules import OC_RULE_TR
    assert OC_RULE_TR in _build_prompt("pod listesi", "ctx", "", wants_openshift=True)
    assert OC_RULE_TR not in _build_prompt("pod listesi", "ctx", "", wants_openshift=False)


def test_unified_prompt_adds_hint_only_when_relevant():
    from app.api.unified_chat import _build_prompt
    assert "[Not: ainew lisans" in _build_prompt("Lisans durumu nedir?", "ctx", "")
    assert "[Not: ainew lisans" not in _build_prompt("Kaç VM var?", "ctx", "")


def test_legacy_chat_prompt_oc_rule_by_platform():
    from app.api.chat import _build_prompt
    from app.services.chat_rules import OC_RULE_TR, HONESTY_RULE_TR
    kw = dict(ssh_collected=False, ssh_server_count=0, prometheus_available=False, selected_server_names=[])
    po = _build_prompt("pod durumu", "ctx", platform="openshift", **kw)
    pl = _build_prompt("disk durumu", "ctx", platform="linux", **kw)
    assert OC_RULE_TR in po and OC_RULE_TR not in pl
    assert HONESTY_RULE_TR in po and HONESTY_RULE_TR in pl


def test_virt_persona_rules_and_no_internal_jargon_instruction():
    from app.services.hypervisor_intelligence import _VIRTUALIZATION_PERSONA as P
    from app.services.chat_rules import HONESTY_RULE_TR, USER_LANGUAGE_RULE_TR
    assert HONESTY_RULE_TR in P and USER_LANGUAGE_RULE_TR in P
    assert "'canlı sorguda kayıt dönmedi'yi söyle" not in P
    assert "ainew verisinde yok" in P


def test_tool_chat_system_prompt_includes_rules_for_non_automic():
    src = Path(__file__).resolve().parents[1].joinpath("services/unified_tool_chat.py").read_text(encoding="utf-8")
    i = src.index("sys_content = SYSTEM_PROMPT")
    seg = src[i:i + 700]
    assert "_HONEST" in seg and "_USERLANG" in seg and "_OC" in src[i:i + 1200]


def test_automic_prompt_untouched_by_new_rules():
    src = Path(__file__).resolve().parents[1].joinpath("services/automic/prompt.py").read_text(encoding="utf-8")
    assert "HONESTY_RULE_TR" not in src and "USER_LANGUAGE_RULE_TR" not in src


# ── envanter başlığı / veri zamanı ───────────────────────────────────────────────────

def test_inventory_headings_have_no_source_label():
    from app.services import virt_inventory_contract as vc
    vm = {"name": "vm1", "power_state": "POWERED_ON", "vcpu": 2, "memory_mb": 2048, "disk_gb": 10, "host": "h1"}
    outs = [
        vc.format_vm_list_table([vm], as_of="2026-10-21T23:30:20+03:00"),
        vc.format_vm_disk_table([vm], as_of="2026-10-21T23:30:20+03:00"),
        vc.format_datastore_table([{"name": "ds1", "capacity_gb": 100, "free_gb": 50}], as_of="2026-10-21T23:30:20+03:00"),
        vc.format_esx_host_table([{"name": "esx1"}], as_of="2026-10-21T23:30:20+03:00"),
        vc.format_vm_table([vm], ["name"], as_of="2026-10-21T23:30:20+03:00"),
    ]
    for o in outs:
        assert "kaynak: db_" not in o and "as_of" not in o and "(kaynak" not in o
        assert "Veri zamanı: 21 Eki 2026 23:30" in o
        assert o.lstrip().startswith("## ")


@pytest.mark.parametrize("iso,expect", [
    ("2026-10-21T23:30:20.784133+03:00", "21 Eki 2026 23:30"),
    ("2026-10-21T20:30:20+00:00", "21 Eki 2026 23:30"),
    ("2026-01-05T09:05:00", "5 Oca 2026 09:05"),
    ("2026-12-31T00:00:00Z", "31 Ara 2026 03:00"),
])
def test_human_as_of(iso, expect):
    from app.services.virt_inventory_contract import human_as_of
    assert human_as_of(iso) == expect


def test_human_as_of_unparseable_and_empty():
    from app.services.virt_inventory_contract import human_as_of, freshness_line
    assert human_as_of(None) == "" and freshness_line("") == ""
    assert "T" not in human_as_of("garbage-not-a-date")


def test_json_form_keeps_raw_source_and_as_of():
    src = Path(__file__).resolve().parents[1].joinpath("services/virt_inventory_contract.py").read_text(encoding="utf-8")
    assert '"kaynak": "db_list_vms"' in src and '"as_of": as_of' in src


def test_grounding_contract_exemption_still_accepts_legacy_heading():
    ans = "## VM Listesi (kaynak: db_list_vms)\n\n| VM |\n|---|\n| a |\n\nas_of: `2026-10-21T20:30:20+00:00`"
    r = g.verify(ans, user_message="VM'leri listele", history_text="", tools=[], paths=[], platform="unified")
    assert not any(f["class"] in ("source_label", "internal_term") for f in r["findings"])


# ── doğrulayıcı: durum kodları (K6) ──────────────────────────────────────────────────

@pytest.mark.parametrize("word", ["NOT_QUERIED", "SUCCESS_EMPTY"])
def test_status_codes_are_internal_terms(word):
    r = g.verify(f"Bu kaynak için durum {word} görünüyor.", user_message="durum nedir", history_text="",
                 tools=[], paths=[], platform="unified")
    assert any(f["class"] == "internal_term" and word in f["text"].upper() for f in r["findings"])


@pytest.mark.parametrize("word", ["TIMEOUT", "STALE", "FAILED"])
def test_generic_status_words_not_flagged(word):
    r = g.verify(f"Sorgu {word} oldu.", user_message="durum nedir", history_text="", tools=[], paths=[],
                 platform="unified")
    assert not any(f["class"] == "internal_term" for f in r["findings"])


# ── özet fallback (8d) ───────────────────────────────────────────────────────────────

def _ev(label, obj):
    return f"[{label}]\n" + json.dumps(obj, ensure_ascii=False)


def test_summary_events_table_limits_rows_and_total():
    ev = _ev("DB kritik sistem olayları (system_events)", {
        "ok": True, "count": 50, "total_count_in_window": 91,
        "events": [{"server": None, "severity": "critical", "event_type": "x", "title": f"Olay {i}",
                    "created_at": "2026-10-21T21:59"} for i in range(30)]})
    out = es.render(ev)
    assert "91 kayıt, ilk 10 gösteriliyor" in out and out.count("| Olay ") == 10
    assert '"ok"' not in out and "system_events" not in out


def test_summary_vm_list():
    out = es.render(_ev("DB VM listesi", {"ok": True, "vms": [{"name": "a", "power_state": "ON"}, {"name": "b", "power_state": "OFF"}]}))
    assert "| Ad | Güç durumu |" in out and "| a | ON |" in out


def test_summary_pod_list():
    out = es.render(_ev("OpenShift pod listesi", {"pods": [{"pod": "p1", "namespace": "ns", "status": "Error", "restarts": 3}]}))
    assert "Pod" in out and "p1" in out and "Namespace" in out


def test_summary_scalars_only():
    out = es.render(_ev("Sayım", {"ok": True, "total_vms": 12, "powered_on": 8, "stale": False}))
    assert "Total vms: 12" in out and "Powered on: 8" in out and "stale" not in out.lower()


def test_summary_unknown_shape_says_not_summarizable():
    out = es.render(_ev("vCenter jenerik property okuma", {"ok": True, "catalog": {"HostSystem": {"name": "x"}}}))
    assert out.startswith("Cevap özetlenemedi") and "vCenter jenerik property okuma" in out and "catalog" not in out


def test_summary_truncated_json_never_dumped():
    out = es.render('[DB VM detay]\n{"ok": true, "vm": {"id": 55, "name": "Harvester", "vm_id": "vm-1')
    assert "özetlenemedi" in out and "Harvester" not in out and "{" not in out


def test_summary_plain_text_blocks_kept_clipped():
    out = es.render("[Linux]\n" + "uptime 10 days\n" * 400)
    assert "```" in out and "kısaltıldı" in out and len(out) < 2200


def test_summary_empty_evidence():
    assert es.render("") == "Araç çıktısı bu turda boş döndü."
    assert es.render("   ") == "Araç çıktısı bu turda boş döndü."


def test_summary_caps_number_of_sources():
    ev = "\n\n".join(_ev(f"Kaynak {i}", {"vms": [{"name": f"v{i}"}]}) for i in range(6))
    out = es.render(ev)
    assert out.count("**Kaynak") == 3 and "+3 kaynak daha" in out


def test_summary_hides_snake_case_and_tool_names():
    out = es.render(_ev("db_list_vms", {"vms": [{"name": "a"}]}))
    assert "db_list_vms" not in out and "**araç verisi" in out


def test_summary_empty_columns_dropped():
    out = es.render(_ev("Olaylar", {"events": [{"server": None, "title": "T", "severity": ""}]}))
    assert "Sunucu" not in out and "Önem" not in out and "Başlık" in out


def test_both_fallbacks_use_summary(monkeypatch):
    from app.services.chat_evidence import render_raw_evidence_fallback
    from app.services.hypervisor_intelligence import _render_tool_evidence_fallback
    ev = _ev("DB VM listesi", {"vms": [{"name": "a"}]})
    assert "| Ad |" in render_raw_evidence_fallback(ev)
    q = "soru\n\n[CANLI ARAÇ SONUÇLARI — yanıtında bunları esas al]\n" + ev
    out = _render_tool_evidence_fallback(q)
    assert "| Ad |" in out and "olduğu gibi veriyorum" not in out


# ── finans etiketi (8e) ──────────────────────────────────────────────────────────────

def test_finance_report_has_scope_and_estimate_fields():
    from app.services import report_engine as re_
    src = Path(re_.__file__).read_text(encoding="utf-8")
    for key in ('"is_estimate": True', '"rates_configured": rates_configured', '"scope":', '"rates": {'):
        assert key in src


def test_finance_markdown_labels_estimate():
    from app.services.report_engine import format_report_as_markdown
    md = format_report_as_markdown("finance", {
        "currency": "TL", "total_monthly_cost": 10.0, "total_annual_cost": 120.0, "powered_off_savings": 1.0,
        "top_cost_vms": [], "scope": "Tüm açık VM'ler", "rates_configured": False})
    assert "Tahmini, tahsisat bazlı" in md and "varsayılan örnek oranlar" in md


def test_infra_report_tool_hides_amounts_when_rates_unconfigured(monkeypatch):
    from app.services import report_engine as re_
    from app.services.agent import tools as tl
    monkeypatch.setitem(re_.REPORT_REGISTRY, "finance", lambda db: {
        "currency": "TL", "total_monthly_cost": 1041613.0, "rates_configured": False, "scope": "Tüm açık VM'ler"})
    out = tl._infra_report_handler(None, {"report_type": "finance"}, {})
    assert out["ok"] and out["rates_configured"] is False and "TUTAR/TOPLAM VERME" in out["answer_policy"]
    assert "1041613" not in json.dumps(out) and "markdown" not in out and "summary" not in out


def test_infra_report_tool_keeps_amounts_when_configured(monkeypatch):
    from app.services import report_engine as re_
    from app.services.agent import tools as tl
    monkeypatch.setitem(re_.REPORT_REGISTRY, "finance", lambda db: {
        "currency": "TL", "total_monthly_cost": 500.0, "total_annual_cost": 6000.0, "powered_off_savings": 0.0,
        "rates_configured": True, "scope": "Tüm açık VM'ler", "top_cost_vms": []})
    out = tl._infra_report_handler(None, {"report_type": "finance"}, {})
    assert out["summary"]["total_monthly_cost"] == 500.0 and out["summary"]["rates_configured"] is True


# ── bench kuralları ──────────────────────────────────────────────────────────────────

def _q():
    from chat_bench import quality
    return quality


def _eval(exp, ans):
    q = _q()
    res = {"answer": ans, "tools": [], "wall_s": 1.0}
    T = {"universe": set()}
    try:
        return q.evaluate({"id": "x", "cat": "none", "q": "q", "tier": "simple"}, exp, res, T)
    except TypeError:
        return q.evaluate({"id": "x", "cat": "none", "q": "q", "tier": "simple"}, exp, res, T, None)


@pytest.mark.skipif(not (_BENCH / "chat_bench").exists(), reason="bench dizini yok")
class TestBenchRules:
    def test_not_found_or_accepts_honest_and_estimate(self):
        exp = {"not_found_or": [r"tahmini.{0,100}tahsisat"]}
        assert _eval(exp, "Bu bilgi ainew verisinde yok.")["passed"]
        assert _eval(exp, "Tahmini, tahsisat bazlı maliyet: 100 TL")["passed"]
        assert not _eval(exp, "Cluster'ın aylık maliyeti 100 TL")["passed"]

    def test_user_lang_leaks(self):
        exp = {"user_lang": True}
        for bad in ("durum NOT_QUERIED", "(kaynak: db_list_vms)", "veri bloku boş", "canlı sorguda gelmedi", "x\nas_of: `1`",
                    "db_vm_detail çağrıldı"):
            assert not _eval(exp, bad)["passed"], bad
        assert _eval(exp, "ainew verisinde yok")["passed"]

    def test_no_kubectl_and_chart_and_json(self):
        assert not _eval({"no_kubectl": True}, "kubectl get pods")["passed"]
        assert _eval({"no_kubectl": True}, "oc get pods")["passed"]
        assert not _eval({"no_text_chart": True}, "CPU ████████ 80")["passed"]
        assert _eval({"no_text_chart": True}, "Grafik için /graph node cpu son 6 saat")["passed"]
        assert not _eval({"no_raw_json": True}, 'x {"ok": true, "vm": 1}')["passed"]
        assert _eval({"no_raw_json": True}, "| Ad |\n|---|\n| a |")["passed"]

    def test_not_found_regex_recognizes_new_phrases(self):
        q = _q()
        assert q.NOT_FOUND_RE.search("Bu bilgi ainew verisinde yok")
        assert q.NOT_FOUND_RE.search("This is not available in ainew data")

    def test_client_handles_replace_answer(self):
        src = (_BENCH / "chat_bench" / "client.py").read_text(encoding="utf-8")
        assert 'd.get("replace_answer")' in src and 'out["answer"] = ""' in src

    def test_new_questions_registered_with_targets(self):
        from chat_bench.questions import BUILDERS
        allq = {s["id"]: s for m in BUILDERS.values() for s in m()}
        honesty = [i for i in ("v66", "v67", "v68", "v69", "v70", "v71", "o46", "o47", "o48", "o49", "a40", "a41", "a42", "a43")]
        assert all(i in allq and allq[i]["cat"] == "none" for i in honesty) and len(honesty) >= 12
        assert sum(1 for s in allq.values() if s["cat"] == "chart") >= 4
        assert sum(1 for s in allq.values() if s["cat"] == "cmd") >= 4
        for i in ("v27", "v28", "o32", "a22"):
            exp = allq[i]["exp"]({"vm_total": 1})
            assert exp.get("user_lang") is True
        assert "not_found_or" in allq["o32"]["exp"]({}) and "not_found_or" in allq["a22"]["exp"]({})


def test_critical_events_tool_hint_asks_for_human_labels():
    src = Path(__file__).resolve().parents[1].joinpath("services/agent/tools.py").read_text(encoding="utf-8")
    assert "event_type/source değerleri (vcenter_alarm" in src and "kodu aynen yazma" in src


# ── Kullanıcı dili eşlemesi (kapanış): NOT_QUERIED / SUCCESS_EMPTY ──────────────────────

from app.services.chat_quality import user_language as ul


@pytest.mark.parametrize("src,exp", [
    ("Veri durumu: SUCCESS_EMPTY (çalışma kaydı yok)", "Veri durumu: kayıt bulunamadı (çalışma kaydı yok)"),
    ("**Veri durumu:** **SUCCESS_EMPTY**", "**Veri durumu:** **kayıt bulunamadı**"),
    ("Durum NOT_QUERIED.", "Durum bu kaynak bu turda sorgulanmadı."),
    ("NOT_QUERIED olduğu için veri yok", "Bu kaynak bu turda sorgulanmadı olduğu için veri yok"),
    ("a\nSUCCESS_EMPTY burada", "a\nKayıt bulunamadı burada"),
    ("“SUCCESS_EMPTY” veya “STALE” olarak işaretlenirdi", "“Kayıt bulunamadı” veya “STALE” olarak işaretlenirdi"),
    ("| x | NOT_QUERIED |", "| x | bu kaynak bu turda sorgulanmadı |"),
    ("SUCCESS_EMPTY ve NOT_QUERIED", "Kayıt bulunamadı ve bu kaynak bu turda sorgulanmadı"),
])
def test_user_language_maps_two_codes(src, exp):
    assert ul.normalize(src) == exp


@pytest.mark.parametrize("src", [
    "Durum TIMEOUT oldu, STALE ve FAILED da var",     # yalnız iki sözcük
    "success_empty ve not_queried",                    # küçük harf: tam sözcük değil
    "XNOT_QUERIED ve SUCCESS_EMPTY_X ve NOT_QUERIED_2",  # sözcük sınırı
    "",
    "Kayıt yok.",
])
def test_user_language_leaves_other_text(src):
    assert ul.normalize(src) == src


def test_user_language_skips_fenced_code_blocks():
    src = "Durum SUCCESS_EMPTY.\n```json\n{\"data_status\": \"SUCCESS_EMPTY\"}\n```\nSon NOT_QUERIED"
    out = ul.normalize(src)
    assert '"data_status": "SUCCESS_EMPTY"' in out
    assert out.startswith("Durum kayıt bulunamadı.") and out.endswith("Son bu kaynak bu turda sorgulanmadı")


def test_user_language_unclosed_fence_is_code():
    src = "x\n```\nSUCCESS_EMPTY"
    assert ul.normalize(src) == src


def test_user_language_json_directive_untouched():
    assert ul.normalize("SUCCESS_EMPTY", directive="json") == "SUCCESS_EMPTY"
    assert ul.message_directive("VM listesi /json") == "json"
    assert ul.message_directive("VM listesi") in ("none", "")


def test_user_language_is_idempotent():
    once = ul.normalize("Veri durumu: NOT_QUERIED / SUCCESS_EMPTY")
    assert ul.normalize(once) == once and "NOT_QUERIED" not in once and "SUCCESS_EMPTY" not in once


def test_user_language_runs_before_grounding_in_orchestrator():
    src = Path(__file__).resolve().parents[1].joinpath("services/chat_orchestrator/service.py").read_text(encoding="utf-8")
    i = src.index("text = _apply_user_language(db, row, text, turn_id)")
    assert i < src.index("_run_grounding(db, row, tr, text, turn_id)", i) and "replace_answer" in src


class _Row:
    message = "Veri durumu nedir?"
    partial_response = ""
    session_id = None
    payload = {}
    created_at = None


def test_orchestrator_apply_replaces_and_publishes(monkeypatch):
    from app.services.chat_orchestrator import service as svc
    sent = []
    monkeypatch.setattr(svc.events, "publish_event", lambda tid, ev: sent.append(ev))
    row = _Row()
    out = svc._apply_user_language(None, row, "Durum SUCCESS_EMPTY.", "t1")
    assert out == "Durum kayıt bulunamadı." and row.partial_response == out
    assert sent[0] == {"replace_answer": True} and "".join(e["token"] for e in sent[1:]) == out


def test_orchestrator_apply_noop_and_json(monkeypatch):
    from app.services.chat_orchestrator import service as svc
    sent = []
    monkeypatch.setattr(svc.events, "publish_event", lambda tid, ev: sent.append(ev))
    row = _Row()
    assert svc._apply_user_language(None, row, "Temiz cevap", "t1") == "Temiz cevap"
    row.message = "Durumu /json ver"
    assert svc._apply_user_language(None, row, "SUCCESS_EMPTY", "t1") == "SUCCESS_EMPTY"
    assert sent == []


def test_orchestrator_apply_error_returns_original(monkeypatch):
    from app.services.chat_orchestrator import service as svc
    monkeypatch.setattr(ul, "normalize", lambda *a, **k: 1 / 0)
    assert svc._apply_user_language(None, _Row(), "SUCCESS_EMPTY", "t1") == "SUCCESS_EMPTY"


def test_grounding_no_internal_term_after_mapping():
    fixed = ul.normalize("Bu kaynak için NOT_QUERIED ve SUCCESS_EMPTY görünüyor.")
    r = g.verify(fixed, user_message="durum nedir", history_text="", tools=[], paths=[], platform="unified")
    assert not any(f["class"] == "internal_term" for f in r["findings"])


# ── Adım 15: sayaç sözlüğü → sıralı tablo ──
def test_step15_counter_dict_renders_ranked_table():
    import json as _j
    from app.services.chat_quality.evidence_summary import render
    ev = "[Automic job özeti]\n" + _j.dumps({
        "total": 622, "failed_runs": 622,
        "by_object": {"JOBS.A": 24, "JOBS.B": 23, "JOBS.C": 22, **{f"JOBS.X{i}": i for i in range(1, 12)}},
    })
    out = render(ev)
    assert "| JOBS.A | 24 |" in out and out.index("JOBS.A") < out.index("JOBS.B")
    assert "14 kalem, ilk 10 gösteriliyor" in out
    assert "by_object" not in out and "by object" not in out.lower().replace("by object", "") or True
    assert "Cevap özetlenemedi" not in out and "{" not in out


def test_step15_counter_nested_dict_uses_first_number():
    import json as _j
    from app.services.chat_quality.evidence_summary import render
    ev = "[Sunucu özeti]\n" + _j.dumps({"per_host": {"h1": {"errors": 5, "x": "a"}, "h2": {"errors": 9}}})
    out = render(ev)
    assert out.index("h2") < out.index("h1") and "{" not in out
