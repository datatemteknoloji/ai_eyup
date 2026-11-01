"""Adım 6c-2 — Unified sohbette Automic iş sinyali ve yönlendirme."""
import pytest

from app.services.chat_quality.automic_signal import automic_signal
from app.services.module_orchestrator import plan_modules


AUTOMIC_QS = [
    "JOBS.DWH.SYNC.01 en son ne zaman çalıştı?",
    "Şu an kaç iş çalışıyor?",
    "Hangi job'lar hata verdi?",
    "Kaç iş akışı başarısız oldu?",
    "Dün gece hata veren işler hangileri?",
    "Bugün kaç job abend oldu?",
    "Hangi jobs başarısız?",
    "Aktif işler neler?",
    "En uzun süren iş hangisi?",
    "JOBP.ETL.DAILY neden hata verdi?",
    "Bekleyen işler var mı?",
    "Hangi işler iptal edildi?",
    "JOBF.FTP.TRANSFER kaç kez başarısız oldu?",
    "EVNT.FILE.WATCH aktif mi?",
    "SCRI.CLEANUP en son ne zaman çalıştı?",
    "Son 24 saatte kaç job fail oldu?",
    "Hangi iş akışları tamamlandı?",
    "Bu gece çalışan işler bitti mi?",
    "Workflow'lardan hangisi hata verdi?",
    "En son biten job hangisi?",
    "JOBS.SAP.EXPORT ne kadar sürdü?",
    "Kaç iş bekliyor?",
]

NOT_AUTOMIC_QS = [
    "OpenShift'te hangi job'lar hata verdi?",
    "Linux sunucularda cron job hata verdi mi?",
    "Kaç CronJob var?",
    "İş yükü en yüksek VM hangisi?",
    "İşlemci kullanımı en yüksek host?",
    "Harvester VM'inin iş sahibi kim?",
    "İşletim sistemi dağılımı nedir?",
    "Kubernetes job'ları çalışıyor mu?",
    "Windows zamanlanmış görev hata verdi mi?",
    "Pod'lardaki işler çalışıyor mu?",
    "Bu iş günü kaç VM açıldı?",
    "Kaç VM çalışıyor?",
    "Merhaba",
    "",
    "OpenShift'te kaç job tamamlandı?",
    "OCP'de başarısız job var mı?",
    "Kaç pod'un job'ı hata verdi?",
    "Namespace'teki job'lar ne zaman çalıştı?",
    "Linux'ta cron işleri çalışıyor mu?",
    "Crontab'daki işler en son ne zaman çalıştı?",
    "Sunucudaki zamanlanmış işler hata verdi mi?",
    "Windows sunucuda başarısız zamanlanmış görev var mı?",
    "vCenter'da başarısız işler neler?",
    "VMware görevleri hata verdi mi?",
    "ESXi host'ta çalışan işler neler?",
    "Systemd servisi çalışıyor mu?",
    "Yedekleme işi başarısız oldu mu?",
    "Hangi VM'in iş yükü arttı?",
    "İş yükü dağılımı nasıl?",
    "İşlemci kullanımı neden yüksek?",
    "İşletim sistemi güncel mi?",
    "Bu iş gününde kaç alarm geldi?",
    "İş sahibi bilgisi var mı?",
    "Kubernetes CronJob en son ne zaman çalıştı?",
    "k8s job'u bitti mi?",
    "Kaç VM kapalı?",
    "Kaç host var?",
    "Job nedir?",
    "İş nedir?",
    "Ne iş yapıyorsun?",
    "Datastore doluluk oranı nedir?",
]


@pytest.mark.parametrize("q", AUTOMIC_QS)
def test_signal_positive(q):
    assert automic_signal(q) is not None


@pytest.mark.parametrize("q", NOT_AUTOMIC_QS)
def test_signal_negative(q):
    assert automic_signal(q) is None


def test_object_name_wins_over_platform_words():
    assert automic_signal("JOBS.LINUX.BACKUP hangi sunucuda çalıştı?") == "object"


def test_signal_reason_kinds():
    assert automic_signal("Hangi job'lar hata verdi?") == "job_word"
    assert automic_signal("Şu an kaç iş çalışıyor?") == "is_word"


def test_job_without_exec_hint_is_not_signal():
    assert automic_signal("Job nedir?") is None


@pytest.mark.parametrize("q", AUTOMIC_QS)
def test_plan_single_automic(q):
    p = plan_modules(q)
    assert p.mode == "single" and p.modules == ("automic",), (q, p.reason)
    assert p.domains == frozenset({"automic"})


@pytest.mark.parametrize("q,mod", [
    ("OpenShift'te hangi job'lar hata verdi?", "openshift"),
    ("Kaç CronJob var?", "openshift"),
    ("Linux sunucularda cron job hata verdi mi?", "linux"),
    ("İş yükü en yüksek VM hangisi?", "virt"),
])
def test_plan_keeps_other_platforms(q, mod):
    p = plan_modules(q)
    assert "automic" not in p.modules
    assert mod in p.modules


def test_route_unified_live_for_automic():
    from app.services.unified_intent_router import route_unified
    r = route_unified("Şu an kaç iş çalışıyor?")
    assert r.need_live and "automic" in r.modules and r.reason == "single:automic"


def test_route_denied_without_automation_module():
    from app.api.unified_chat import _route_denied_modules
    from app.services.unified_intent_router import route_unified
    r = route_unified("Hangi job'lar hata verdi?")
    assert _route_denied_modules(r, {"linux", "virt"}) == ["automic"]
    assert _route_denied_modules(r, {"automic"}) == []
    assert _route_denied_modules(r, None) == []


def test_live_path_agentic_for_automic_route():
    from app.services.chat_path_policy import resolve_live_path
    d = resolve_live_path(
        "Şu an kaç iş çalışıyor?",
        agentic_enabled=True,
        wants_fixed_collect=False,
        has_live_targets=False,
        allow_agentic_without_collect=True,
    )
    assert d.run_agentic and not d.run_fixed_collect
