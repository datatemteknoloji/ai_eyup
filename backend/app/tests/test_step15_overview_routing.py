"""Adım 15 — «genel durum / tüm altyapı» sorusu ana modüllerin tümünden veri toplar; güçlü sinyalliler değişmez."""
import pytest

from app.services.module_orchestrator import plan_modules


@pytest.mark.parametrize("q", [
    "Altyapının genel durumunu analiz et, kritik sorunlar neler?",
    "Genel durum nedir?",
    "Tüm altyapı özeti",
    "tüm ortamın genel sağlığı nasıl",
])
def test_overview_questions_cover_main_modules(q):
    p = plan_modules(q)
    assert p.reason == "auto_explore:overview"
    assert {"vcenter", "linux", "windows", "openshift"} <= set(p.domains)


@pytest.mark.parametrize("q,reason", [
    ("disk doluluğu yüksek sunucular", "auto_explore:virt+linux"),
    ("Linux sunucuların genel durumu", "single:linux"),
    ("vCenter genel durum", "single:virt"),
    ("Hangi job lar hata verdi", "single:automic"),
])
def test_strong_signal_questions_unchanged(q, reason):
    assert plan_modules(q).reason == reason
