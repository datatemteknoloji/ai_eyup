"""Dilim T — yöntem kaydı: kayıtsız bileşen CI'da başarısız olur."""
import json
import os
import re

from app.services import method_registry as mr
from app.services.agent import tools as T
from app.services.findings.registry import CHECKS

SNAPSHOT = os.path.join(os.path.dirname(__file__), "..", "data", "method_ids.json")

FORBIDDEN_NON_AI = [
    "ai öngör", "ai tespit", "akıllı tahmin", "ai predicted", "ai detected", "smart forecast", "ai-powered",
]


def test_every_finding_check_has_registered_method():
    missing = [cid for cid in CHECKS if mr.resolve(cid) is None]
    assert not missing, f"Yöntem kaydı olmayan check'ler: {missing}"


def test_dynamic_finding_prefixes_registered():
    for cid in ("vuln:VMSA-2024-0001", "kb:KB123456", "upg:eol", "upg:target", "upg:vlcm_hcl", "upg:feed_stale"):
        m = mr.resolve(cid)
        assert m is not None, cid
        assert m.cls in (mr.CLASS_ESLESTIRME, mr.CLASS_KURAL), cid


def test_every_readonly_chat_tool_has_registered_method():
    missing = []
    for name, t in T.TOOLS.items():
        if t.risk_level == T.RiskLevel.READ_ONLY and t.llm_visible and mr.resolve_tool(name) is None:
            missing.append(name)
    assert not missing, f"Yöntem kaydı olmayan sohbet tool'ları: {missing}"


def test_classes_are_the_fixed_six():
    assert set(mr.CLASSES) == {"veri", "hesap", "tahmin", "kural", "eslestirme", "ai"}
    for m in mr.all_methods():
        assert m.cls in mr.CLASSES, m.id


def test_entries_are_complete_and_bilingual():
    for m in mr.all_methods():
        for f in ("method_tr", "method_en", "source_tr", "source_en", "limits_tr", "limits_en"):
            assert getattr(m, f).strip(), f"{m.id}.{f} boş"
    # her sınıfın etiketi ve açıklaması var
    for c in mr.CLASSES:
        assert mr.CLASS_INFO[c]["label_tr"] and mr.CLASS_INFO[c]["desc_en"]


def test_ids_are_unique():
    ids = [m.id for m in mr.all_methods()]
    assert len(ids) == len(set(ids))


def test_forecast_class_states_range_or_history_limit():
    for m in mr.all_methods():
        if m.cls == mr.CLASS_TAHMIN:
            txt = (m.method_tr + " " + m.limits_tr).lower()
            assert "aralık" in txt or "geçmiş" in txt, f"{m.id}: tahmin sınıfı aralık/geçmiş sınırı belirtmeli"


def test_ai_flag_consistency():
    for m in mr.all_methods():
        if m.cls == mr.CLASS_AI:
            assert m.uses_ai, m.id


def test_non_ai_text_does_not_claim_ai():
    for m in mr.all_methods():
        if m.cls == mr.CLASS_AI or m.uses_ai:
            continue
        blob = " ".join([m.method_tr, m.method_en, m.source_tr, m.source_en, m.limits_tr, m.limits_en]).lower()
        for bad in FORBIDDEN_NON_AI:
            assert bad not in blob, f"{m.id}: AI olmayan yöntemde '{bad}' ifadesi"


def test_ai_note_present():
    assert "Sayılar ve sonuç backend'den gelir" in mr.AI_NOTE_TR
    assert "ortamınızdan alınmadı" in mr.GENERAL_KNOWLEDGE_TR


def test_resolve_prefers_exact_then_longest_pattern():
    assert mr.resolve("tool:vcenter_ask").cls == mr.CLASS_AI           # tam kayıt
    assert mr.resolve("tool:vcenter_live_alarms").id == "tool:vcenter_*"  # aile
    assert mr.resolve("hw.host.sensor_repeat").id == "hw.host.*"
    assert mr.resolve("ocp.cluster.n_plus_one").cls == mr.CLASS_HESAP     # tam kayıt desenden önce
    assert mr.resolve("ocp.node.condition").id == "ocp.*"
    assert mr.resolve("unknown.component") is None


def test_snapshot_file_matches_registry():
    """Frontend vitest bu dosyayla kullanılan method id'lerini doğrular. Güncellemek için:
    python -c "import json;from app.services import method_registry as m;print(json.dumps(m.ids(),indent=1))" """
    with open(SNAPSHOT, encoding="utf-8") as f:
        snap = json.load(f)
    assert snap == mr.ids(), "backend/app/data/method_ids.json güncel değil — yeniden üretin"
    # Frontend kopyası (frontend/src/test/method_ids.json): repo kökünden çalışırken de aynı olmalı.
    # Konteynerde frontend dizini yoktur; orada yalnız backend kopyası doğrulanır.
    fe = os.path.join(os.path.dirname(__file__), "..", "..", "..", "frontend", "src", "test", "method_ids.json")
    if os.path.exists(fe):
        with open(fe, encoding="utf-8") as f:
            assert json.load(f) == mr.ids(), "frontend/src/test/method_ids.json güncel değil — backend kopyasından kopyalayın"


def test_chat_sources_use_registry_classes():
    from app.services.chat_evidence_badge import evidence_sse_field, score_evidence_badge
    b = score_evidence_badge(kind="live", tools_used=["virt_capacity_simulate", "db_list_vms"], has_tool_text=True)
    ev = evidence_sse_field(b)["evidence"]
    src = {s["tool"]: s for s in ev["sources"]}
    assert src["virt_capacity_simulate"]["class"] == "hesap"
    assert src["db_list_vms"]["class"] == "veri"
    assert re.match(r"\d{4}-\d{2}-\d{2}T", src["db_list_vms"]["at"])
    assert not ev.get("general")


def test_chat_general_knowledge_marker():
    from app.services.chat_evidence_badge import evidence_sse_field, score_evidence_badge
    # kavramsal soru: rozet yok ama "AI genel bilgisi" işareti var
    ev = evidence_sse_field(score_evidence_badge(kind="knowledge"))["evidence"]
    assert ev["general"] is True and ev["level"] == "hidden"
    # selam: işaret yok
    assert evidence_sse_field(score_evidence_badge(kind="chitchat")) == {}
    # kanıtsız canlı soru: düşük kanıt + genel bilgi işareti
    ev = evidence_sse_field(score_evidence_badge(kind="live"))["evidence"]
    assert ev["level"] == "low" and ev["general"] is True
