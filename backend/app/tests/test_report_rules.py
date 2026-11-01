"""Adım 21 — sohbette «Rapor soruları» (OpenShift + Yönetici): saf tespit kuralları ve KISA özet biçimi.

DB gerektirmez: `detect` saf, `to_chat_markdown` şemadan çalışır. Chip metinleri (TR + EN) burada kilitlenir —
arayüzdeki listeyle aynı olmalı (frontend `chatReportQuestions.ts`).
"""
from __future__ import annotations

import pytest

from app.services import exec_catalog_reports as ex
from app.services import generic_report as gr
from app.services import ocp_report_engine as oe
from app.services.chat_quality import report_rules as rr

# frontend/src/config/chatReportQuestions.ts ile aynı (TR) + beklenen tip
OCP_CHIPS = [
    ("Executive Summary raporu oluştur", "executive_summary"),
    ("Kapasite raporu göster", "capacity"),
    ("Kapasite tahmin raporu üret", "forecast"),
    ("Risk dashboard raporu ver", "risk"),
    ("MTV migrasyon raporu göster", "mtv_migration"),
    ("MTV migrasyon hazırlık raporu oluştur", "mtv_readiness"),
    ("Namespace kullanım raporu göster", "namespace_usage"),
    ("Depolama (PVC) raporu göster", "storage"),
    ("Workload sağlığı raporu üret", "workload_health"),
    ("KubeVirt sanal makine raporu göster", "vm_health"),
    ("Uyum ve güncelleme raporu göster", "compliance_update"),
    ("Operasyon raporu göster", "operations"),
]
EXEC_CHIPS = [
    ("Yönetici özeti raporu oluştur", "executive_summary"),
    ("Tüm ortamlar kapasite raporu göster", "capacity"),
    ("Tüm ortamlar kapasite tahmin raporu üret", "forecast"),
    ("Tüm ortamlar risk raporu ver", "risk"),
    ("En riskli varlıklar raporu göster", "riskiest_assets"),
    ("SLA ve erişilebilirlik raporu üret", "sla"),
    ("Yama ve uyum raporu göster", "patch_compliance"),
    ("Geri kazanım raporu oluştur", "reclaim"),
    ("İzleme kapsamı raporu göster", "monitoring_coverage"),
    ("Operasyon raporu göster", "operations"),
    ("Migrasyon (MTV) raporu göster", "migration"),
]
EN_OCP = [
    ("Create executive summary report", "executive_summary"),
    ("Show capacity report", "capacity"),
    ("Show risk dashboard report", "risk"),
    ("Show MTV migration report", "mtv_migration"),
    ("Create MTV migration readiness report", "mtv_readiness"),
    ("Show capacity forecast report", "forecast"),
    ("Show namespace usage report", "namespace_usage"),
    ("Show storage (PVC) report", "storage"),
    ("Show workload health report", "workload_health"),
    ("Show KubeVirt virtual machine report", "vm_health"),
    ("Show compliance and update report", "compliance_update"),
    ("Show operations report", "operations"),
]
EN_EXEC = [
    ("Create executive summary report", "executive_summary"),
    ("Show all environments capacity report", "capacity"),
    ("Show all environments capacity forecast report", "forecast"),
    ("Show all environments risk report", "risk"),
    ("Show riskiest assets report", "riskiest_assets"),
    ("Show SLA and availability report", "sla"),
    ("Show patch and compliance report", "patch_compliance"),
    ("Show reclaim report", "reclaim"),
    ("Show monitoring coverage report", "monitoring_coverage"),
    ("Show operations report", "operations"),
    ("Show migration (MTV) report", "migration"),
]


@pytest.mark.parametrize("q,rtype", OCP_CHIPS + EN_OCP)
def test_openshift_chips_resolve(q, rtype):
    got = rr.detect(q, platform="openshift", ocp_ok=True)
    assert got == rr.ReportIntent("openshift", rtype), q
    assert rtype in oe.CATALOG


@pytest.mark.parametrize("q,rtype", EXEC_CHIPS + EN_EXEC)
def test_executive_chips_resolve(q, rtype):
    got = rr.detect(q, platform="unified", ocp_ok=True, exec_ok=True)
    assert got == rr.ReportIntent("executive", rtype), q
    assert rtype in ex.CATALOG


def test_rbac_gates():
    assert rr.detect("Kapasite raporu göster", platform="openshift", ocp_ok=False) is None
    assert rr.detect("Yönetici özeti raporu oluştur", platform="unified", ocp_ok=True, exec_ok=False) is None
    # Yönetici yetkisi yok ama OpenShift var → OpenShift sözcüğüyle OCP raporu
    assert rr.detect("OpenShift kapasite raporu", platform="unified", ocp_ok=True, exec_ok=False) == \
        rr.ReportIntent("openshift", "capacity")
    assert rr.detect("MTV migrasyon raporu", platform="unified", ocp_ok=True, exec_ok=False) == \
        rr.ReportIntent("openshift", "mtv_migration")


def test_unified_openshift_words_route_to_openshift_engine():
    assert rr.detect("OpenShift namespace kullanım raporu", platform="unified", ocp_ok=True, exec_ok=True) == \
        rr.ReportIntent("openshift", "namespace_usage")


@pytest.mark.parametrize("q", [
    "Kapasite nedir?",                                  # rapor kelimesi yok
    "Kapasite raporu nasıl hesaplanıyor?",              # yöntem sorusu → normal akış
    "Neden risk raporu boş geldi?",                     # nedensellik
    "Kaç node var?",                                    # sayım kuralı
    "Linux sunucuları için kapasite raporu göster",     # yalnız belirli platform → infra_report
    "VMware VM sağlık skoru raporu üret",               # sanallaştırma raporu → mevcut yol
    "Maliyet raporu oluştur",                           # eşleşen rapor tipi yok
    "x" * 300,
])
def test_non_report_or_out_of_scope_messages_fall_through(q):
    assert rr.detect(q, platform="unified", ocp_ok=True, exec_ok=True) is None


def test_other_platforms_never_trigger():
    for p in ("linux", "windows", "exadata", "virt", None):
        assert rr.detect("Kapasite raporu göster", platform=p, ocp_ok=True, exec_ok=True) is None


def test_all_environment_phrase_overrides_platform_word_filter():
    assert rr.detect("Tüm ortamlar için linux ve vm risk raporu ver", platform="unified",
                     ocp_ok=True, exec_ok=True) == rr.ReportIntent("executive", "risk")


def _sample():
    rows = [[f"ns-{i}", i] for i in range(20)]
    return gr.make_report(
        "openshift", "namespace_usage", "Örnek Rapor",
        kpis=[gr.kpi("Toplam", 20)],
        sections=[
            gr.table("Tablo", ["Ad", "Değer"], rows, module="OpenShift"),
            gr.unmeasured("Eksik", "veri yok", module="Linux"),
        ],
        recommendations=[f"öneri {i}" for i in range(10)],
        excluded=[{"module": "Windows", "reason": "anlamsız"}],
    )


def test_chat_markdown_is_short_and_deterministic():
    md = gr.to_chat_markdown(_sample(), max_rows=8, full_hint="HINT")
    assert md.startswith("## Örnek Rapor")
    assert "- **Toplam:** 20" in md
    assert "ns-7" in md and "ns-8" not in md          # yalnız ilk 8 satır
    assert "toplam 20 satır" in md
    assert "_Ölçülemedi: veri yok_" in md
    assert "Kapsam dışı" in md and "**Windows:** anlamsız" in md
    assert "öneri 5" in md and "öneri 6" not in md    # ≤6 öneri
    assert md.rstrip().endswith("HINT")
    assert "Hesaplama yöntemi" not in md and "Yöntem" not in md   # uzun yöntem notları tam raporda


def test_kpi_sub_slash_is_not_rendered_as_dash():
    d = gr.make_report("openshift", "x", "T", kpis=[gr.kpi("Taşınan", 2, "/5")])
    assert "- **Taşınan:** 2 /5" in gr.to_chat_markdown(d)
    assert "2 — /5" not in gr.to_markdown(d, scope="openshift", report_type="mtv_migration")


def test_intent_language_follows_message():
    en = rr.detect("Show MTV migration report", platform="unified", exec_ok=True)
    assert en and en.report_type == "migration" and en.lang == "en"
    tr = rr.detect("MTV migrasyon raporu göster", platform="unified", exec_ok=True)
    assert tr and tr.lang == "tr"
    assert rr.detect("OpenShift capacity report", platform="openshift", ocp_ok=True).lang == "en"
