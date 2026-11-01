"""Hazır rapor içeriği EN çevirisi (`report_i18n`): kapsam, şablonlar, şema korunumu, markdown/sohbet dili."""
from __future__ import annotations

import ast
import re
from pathlib import Path

from app.services import generic_report as gr
from app.services import report_i18n as ri

_SVC = Path(__file__).resolve().parents[1] / "services"
_ENGINES = ("ocp_report_engine.py", "exec_catalog_reports.py")


def _ui_strings() -> set[str]:
    """İki motordaki kullanıcıya dönük sabit metinler (docstring/log/SQL/sözlük anahtarı/istisna hariç)."""
    out: set[str] = set()
    for fn in _ENGINES:
        tree = ast.parse((_SVC / fn).read_text(encoding="utf-8"))
        parent = {id(c): n for n in ast.walk(tree) for c in ast.iter_child_nodes(n)}
        doc = set()
        for n in ast.walk(tree):
            if isinstance(n, (ast.Module, ast.FunctionDef, ast.ClassDef, ast.AsyncFunctionDef)):
                b = n.body
                if b and isinstance(b[0], ast.Expr) and isinstance(b[0].value, ast.Constant):
                    doc.add(id(b[0].value))

        def skip(n) -> bool:
            p = parent.get(id(n))
            while p is not None:
                if isinstance(p, ast.Raise):
                    return True
                if isinstance(p, ast.Call):
                    f = p.func
                    if isinstance(f, ast.Attribute) and isinstance(f.value, ast.Name) and f.value.id in ("logger", "logging", "log"):
                        return True
                    if isinstance(f, ast.Attribute) and f.attr in ("execute", "text", "like", "ilike", "json_extract_path_text", "startswith", "endswith"):
                        return True
                    if isinstance(f, ast.Name) and f.id in ("text", "getattr", "HTTPException"):
                        return True
                if isinstance(p, ast.Subscript) and p.slice is n:
                    return True
                p = parent.get(id(p))
            return False

        for n in ast.walk(tree):
            s = None
            if isinstance(n, ast.JoinedStr):
                s = "".join(str(v.value) if isinstance(v, ast.Constant) else "{}" for v in n.values)
            elif isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in doc:
                if isinstance(parent.get(id(n)), ast.JoinedStr):
                    continue
                s = n.value
            if s is None or len(s.strip()) < 2 or skip(n):
                continue
            if isinstance(parent.get(id(n)), ast.Dict) and n in parent[id(n)].keys:
                continue
            if re.fullmatch(r"[a-z0-9_\.\-:/%\{\}\+ ]+", s) or re.search(r"\b(SELECT|FROM|WHERE|JOIN)\b", s):
                continue
            if re.fullmatch(r"[\W\d_]+", s):
                continue
            out.add(s)
    return out


def test_every_engine_string_has_an_english_translation():
    missing = sorted(s for s in _ui_strings() if ri.tr_str(s) is None)
    assert not missing, f"{len(missing)} çevrilmemiş rapor metni (report_i18n.EN'e ekleyin): {missing[:15]}"


def test_translation_placeholders_match():
    for tr, en in ri.EN.items():
        assert tr.count("{}") == en.count("{}"), (tr, en)


def test_translated_text_has_no_turkish_diacritics():
    bad = [(k, v) for k, v in ri.EN.items() if re.search(r"[çğıöşüÇĞİÖŞÜ]", v)]
    assert not bad, bad[:5]


def test_templates_keep_captured_values_untouched():
    assert ri.t("3 zaten taşındı", "en") == "3 already migrated"
    assert ri.t("Node kullanımı — prod-ocp", "en") == "Node usage — prod-ocp"
    # Ad ve sayı çevrilmez; bilinmeyen metin (kullanıcı verisi) aynen kalır
    assert ri.t("Kritik-küme-adı", "en") == "Kritik-küme-adı"
    assert ri.t("datastore-01", "en") == "datastore-01"
    assert ri.t("Sanallaştırma: Dikkat (4 kritik varlık, 27 kritik olay) — en riskli varlıklar tabloda.", "en") \
        == "Virtualization: Attention (4 critical assets, 27 critical events) — the riskiest assets are in the table."


def test_tr_is_identity_and_non_strings_pass_through():
    assert ri.t("Kritik", "tr") == "Kritik"
    assert ri.t(5, "en") == 5 and ri.t(None, "en") is None
    d = {"title": "OpenShift Kapasite Raporu", "kpis": [], "sections": []}
    assert ri.translate_report(d, "tr") is d


def _sample() -> dict:
    return gr.make_report(
        "openshift", "capacity", "OpenShift Kapasite Raporu",
        kpis=[gr.kpi("Cluster", 2, "/2", "ok"), gr.kpi("Kritik varlık", 1, tone="crit")],
        sections=[
            gr.table("Cluster özeti", ["Cluster", "Durum", "Memory request %"], [["prod-1", "Kritik", 91.5], ["dev-1", "Normal", None]],
                     module="OpenShift", note="Request kullanım değildir; ikisi ayrı sütundadır."),
            gr.unmeasured("Küme kapasitesi", "Tamamlanmış tarama yok; PVC verisi ölçülemedi.", module="Sanallaştırma"),
            gr.table("Açık incident'lar", ["Cluster"], [], module=None),
        ],
        recommendations=["3 VM başarısız — hata nedenlerini inceleyip planı yeniden çalıştırın."],
        notes=["Sentetik (ZZ-FAKE) test kaynakları bu rapora dahil edilmez."],
        excluded=[{"module": "Exadata", "reason": "Exadata taşınmaz; MTV kapsamı dışındadır."}],
        methodology="Request % = pod request toplamı / worker allocatable (son tarama). Kullanım % = metrics.k8s.io son örnek / allocatable (ainew DB).",
        extra={"applicability": {"exadata": {"included": False, "reason": "Exadata taşınmaz; MTV kapsamı dışındadır."}}},
    )


def test_translate_report_keeps_schema_keys_modules_and_values():
    src = _sample()
    en = ri.translate_report(src, "en")
    assert en is not src and src["title"] == "OpenShift Kapasite Raporu"      # kaynak değişmez
    assert en["title"] == "OpenShift Capacity Report"
    assert [k["label"] for k in en["kpis"]] == ["Cluster", "Critical assets"]
    assert en["kpis"][0]["sub"] == "/2" and en["kpis"][0]["value"] == 2 and en["kpis"][0]["tone"] == "ok"
    s0 = en["sections"][0]
    assert s0["title"] == "Cluster summary" and s0["columns"] == ["Cluster", "Status", "Memory request %"]
    assert s0["rows"] == [["prod-1", "Critical", 91.5], ["dev-1", "Normal", None]]      # ad/sayı aynen
    assert s0["module"] == "OpenShift" and en["sections"][1]["module"] == "Sanallaştırma"   # module değişmez (UI i18n çizer)
    assert en["sections"][1]["note"].startswith("No completed scan")
    assert en["recommendations"][0].startswith("3 VMs failed")
    assert en["excluded"][0]["module"] == "Exadata" and en["excluded"][0]["reason"].startswith("Exadata is not migrated")
    assert en["applicability"]["exadata"]["included"] is False
    assert en["applicability"]["exadata"]["reason"].startswith("Exadata is not migrated")
    assert en["methodology"].startswith("Request % = sum of pod requests")
    assert en["report_type"] == "capacity" and en["view"] == "generic"


def test_markdown_en_has_english_skeleton_and_method_notes():
    md = gr.to_markdown(_sample(), scope="openshift", report_type="capacity", lang="en")
    assert "# OpenShift Capacity Report" in md and "*Created:" in md
    assert "Virtualization — Cluster capacity" in md          # modül adı markdown'da çevrilir
    assert "_Not measured: No completed scan; PVC data could not be measured._" in md
    assert "## Out of scope" in md and "## Recommendations" in md and "**Calculation method:**" in md
    assert "## Method notes" in md                   # method_notes_markdown(lang="en")
    assert not re.search(r"[çğıöşüÇĞİÖŞÜ]", md.replace("Sanallaştırma", ""))
    tr = gr.to_markdown(_sample(), scope="openshift", report_type="capacity")
    assert "## Kapsam dışı" in tr and "*Oluşturulma:" in tr and "## Yöntem notları" in tr


def test_chat_markdown_en_and_tr():
    en = gr.to_chat_markdown(_sample(), lang="en", full_hint="_hint_")
    assert en.startswith("## OpenShift Capacity Report") and "### OpenShift — Cluster summary" in en
    assert "### Recommendations" in en and "_No records._" in en and "_Not measured:" in en
    tr = gr.to_chat_markdown(_sample(), full_hint="_ipucu_")
    assert tr.startswith("## OpenShift Kapasite Raporu") and "### Öneriler" in tr and "_Kayıt yok._" in tr
    many = gr.make_report("openshift", "x", "T", sections=[gr.table("S", ["A"], [[i] for i in range(12)])])
    assert "Showing the first 8 rows; 12 rows in total." in gr.to_chat_markdown(many, lang="en")


def test_bool_cells_follow_language():
    assert gr._cell(True, "en") == "Yes" and gr._cell(False, "en") == "No"
    assert gr._cell(True) == "Evet" and gr._cell(False) == "Hayır"


def test_lang_of_message():
    assert ri.lang_of("Show MTV migration report") == "en"
    assert ri.lang_of("Generate the executive summary report") == "en"
    assert ri.lang_of("OpenShift capacity report") == "en"
    assert ri.lang_of("Kapasite raporu göster") == "tr"
    assert ri.lang_of("kapasite raporu") == "tr"
    assert ri.lang_of("") == "tr"


def test_history_title_prefix_is_translated():
    assert ri.t("[YÖNETİCİ] Tüm Ortamlar — Risk", "en") == "[EXECUTIVE] All Environments — Risk"
    assert ri.t("[OPENSHIFT] OpenShift Kapasite Raporu", "en") == "[OPENSHIFT] OpenShift Capacity Report"
