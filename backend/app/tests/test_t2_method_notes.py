"""T2: rapor 'Yöntem notları' registry'den üretilir; eski sohbet akışları kaynak satırı verir."""
from app.services import method_registry as mr
from app.services import report_method_notes as rmn
from app.services.chat_evidence_badge import collect_sources_evidence, evidence_sse_field, merge_evidence_meta


def test_every_mapped_method_id_is_registered():
    ids = set(rmn._BASE)
    for v in rmn._EXTRA.values():
        ids |= set(v)
    for v in rmn._SCOPE_SOURCE.values():
        ids |= set(v)
    assert ids
    for i in ids:
        assert mr.resolve(i), f"kayıtsız yöntem kimliği: {i}"


def test_notes_are_generated_from_registry_not_hardcoded():
    md = rmn.method_notes_markdown("linux", "capacity")
    assert "## Yöntem notları" in md
    for mid in ("report.numbers", "report.narrative", "report.capacity_trend", "linux.metrics"):
        m = mr.resolve(mid)
        assert m.method_tr in md and m.source_tr in md and m.limits_tr in md
    assert "Tahmin" in md and "Veri" in md      # sınıf etiketleri registry'den


def test_notes_english_and_ai_note_only_when_ai_method():
    en = rmn.method_notes_markdown("virt", "capacity", lang="en")
    assert "## Method notes" in en and "Source:" in en and "Limits:" in en
    assert mr.AI_NOTE_EN not in en and mr.AI_NOTE_TR not in en
    ai = rmn.method_notes_markdown("virt", "capacity", extra_ids=["ai.awr"])
    assert mr.AI_NOTE_TR in ai


def test_unmapped_report_type_still_gets_base_notes():
    md = rmn.method_notes_markdown("virt", "yok_boyle_bir_rapor")
    assert mr.resolve("report.numbers").method_tr in md
    assert mr.resolve("report.narrative").method_tr in md


def test_virt_report_markdown_has_notes():
    from app.services.report_engine import format_report_as_markdown
    md = format_report_as_markdown("capacity", {"generated_at": "2026-01-01T00:00:00"})
    assert "## Yöntem notları" in md and "Theil–Sen" in md
    md2 = format_report_as_markdown("risk", {"generated_at": "2026-01-01T00:00:00"})
    assert "## Yöntem notları" in md2 and "Theil–Sen" not in md2


def test_platform_report_markdown_has_notes_per_platform():
    from app.services.platform_report_engine import format_platform_report_markdown
    d = {"generated_at": "2026-01-01T00:00:00"}
    lin = format_platform_report_markdown("linux", "capacity", d)
    win = format_platform_report_markdown("windows", "risk", d)
    exa = format_platform_report_markdown("exadata", "node_health", d)
    assert mr.resolve("linux.metrics").source_tr in lin and "Theil–Sen" in lin
    assert mr.resolve("win.metrics").source_tr in win and "Theil–Sen" not in win
    assert mr.resolve("exa.health").source_tr in exa
    for md in (lin, win, exa):
        assert "## Yöntem notları" in md


def test_executive_report_has_notes():
    from app.services.executive_report import build_executive_report
    r = build_executive_report({"generated_at": "x", "overall": {}, "platforms": {}}, {})
    assert "## Yöntem notları" in r["markdown"]
    assert mr.resolve("ops.health_score").method_tr in r["markdown"]


# ── eski sohbet akışları: kaynak satırı ────────────────────────────────────────

def test_no_source_means_no_claim():
    assert collect_sources_evidence() is None
    assert evidence_sse_field(None) == {}


def test_live_collect_is_high_with_registry_class():
    b = collect_sources_evidence(ssh=True, prometheus=True)
    assert b["level"] == "high"
    tools = {s["tool"]: s for s in b["sources"]}
    assert set(tools) == {"collect_ssh", "collect_prometheus"}
    assert all(s["class"] == "veri" and s.get("at") for s in tools.values())
    assert "general" not in b            # 'ortamınızdan alınmadı' iddiası yok


def test_inventory_only_is_medium_and_winrm_resolves():
    b = collect_sources_evidence(inventory=True)
    assert b["level"] == "medium"
    assert [s["tool"] for s in b["sources"]] == ["collect_inventory"]
    w = collect_sources_evidence(winrm=True, inventory=True)
    assert w["level"] == "high" and {s["tool"] for s in w["sources"]} == {"collect_winrm", "collect_inventory"}


def test_evidence_roundtrips_through_message_meta():
    b = collect_sources_evidence(ssh=True)
    meta = merge_evidence_meta({"intents": []}, b)
    assert meta["evidence"]["sources"][0]["tool"] == "collect_ssh"
    assert meta["evidence"]["level"] == "high"
    assert evidence_sse_field(b)["evidence"] == meta["evidence"]


def test_new_registry_entries_present_and_classified():
    for mid, cls in (("linux.metrics", "veri"), ("win.metrics", "veri"), ("exa.health", "veri"),
                     ("awr.parse", "veri"), ("ai.awr", "ai"), ("report.capacity_trend", "tahmin"),
                     ("tool:collect_ssh", "veri"), ("tool:collect_winrm", "veri"),
                     ("tool:collect_prometheus", "veri"), ("tool:collect_inventory", "veri")):
        m = mr.resolve(mid)
        assert m and m.cls == cls, mid
    assert mr.resolve("ai.awr").uses_ai
