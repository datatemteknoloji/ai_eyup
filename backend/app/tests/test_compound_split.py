"""Adım 6c-1 — bileşik sayım sorusu ayrıştırma (saf)."""
import pytest

from app.services.chat_quality import compound as cp
from app.services.chat_quality import count_rules as cr
from app.services.chat_quality.count_scope import HV, ScopeCatalog


def _cat() -> ScopeCatalog:
    c = ScopeCatalog()
    c.hypervisors = [HV(1, "office", "VMWARE"), HV(2, "Datatem OLVM", "KVM"), HV(3, "oVirt (OpenShift Virt)", "OPENSHIFT_VIRT")]
    c.ocp_clusters = [(2, "oVirt"), (3, "ZZ-FAKE-OCP")]
    return c


CAT = _cat()


def topics(q, platform="unified", allowed=None):
    out, prev = [], None
    for part in cp.split_parts(q):
        eff = cp.resolve_pronoun(part, prev) or part
        p = cr.analyze(eff, CAT, platform=platform, allowed_modules=allowed)
        out.append(None if p is None else (p.topic, p.state if p.topic not in ("pod",) else p.pod_filter))
        prev = eff
    return out


# ── bileşik (≥ 40) — parça sayısı + parça konuları ─────────────────────────────────

COMPOUND = [
    ("Kaç VM var ve OpenShift'te toplam kaç node var?", [("vm", "all"), ("node", "all")]),
    ("Kapalı VM sayısı kaç, OpenShift'te hatalı pod sayısı kaç?", [("vm", "off"), ("pod", "faulty")]),
    ("Kaç Linux sunucum, kaç VM ve kaç OpenShift node var?", [("server", "all"), ("vm", "all"), ("node", "all")]),
    ("Kaç VM var, kaçı kapalı?", [("vm", "all"), ("vm", "off")]),
    ("office vCenter'da kaç VM var, kaçı kapalı?", [("vm", "all"), ("vm", "off")]),
    ("office vCenter'da kaç VM var ve kaçı açık?", [("vm", "all"), ("vm", "on")]),
    ("Kaç host var ve kaç datastore var?", [("host", "all"), ("datastore", "all")]),
    ("Kaç hypervisor ve kaç OpenShift cluster'ı kayıtlı?", [("hypervisor", "all"), ("cluster", "all")]),
    ("Kaç VM var; kaç host var?", [("vm", "all"), ("host", "all")]),
    ("Kaç VM var ayrıca kaç node var?", [("vm", "all"), ("node", "all")]),
    ("Kaç pod var ve kaç node var?", [("pod", "all"), ("node", "all")]),
    ("Kaç hatalı pod var, kaç node var?", [("pod", "faulty"), ("node", "all")]),
    ("OpenShift'te kaç pod CrashLoopBackOff durumunda ve kaç node var?", [("pod", "reason:CrashLoopBackOff"), ("node", "all")]),
    ("Kaç Windows sunucu var ve kaç Linux sunucu var?", [("server", "all"), ("server", "all")]),
    ("Kaç Linux sunucu, kaç Windows sunucu var?", [("server", "all"), ("server", "all")]),
    ("Kapalı VM kaç, açık VM kaç?", [("vm", "off"), ("vm", "on")]),
    ("Kaç kapalı VM, kaç açık VM var?", [("vm", "off"), ("vm", "on")]),
    ("Toplam VM sayısı kaç ve toplam host sayısı kaç?", [("vm", "all"), ("host", "all")]),
    ("VM sayısı kaç, node sayısı kaç?", [("vm", "all"), ("node", "all")]),
    ("Kaç proje var ve kaç node var?", [("project", "all"), ("node", "all")]),
    ("OpenShift'te kaç proje, kaç node ve kaç pod var?", [("project", "all"), ("node", "all"), ("pod", "all")]),
    ("Kaç VM, kaç host, kaç datastore ve kaç cluster var?", [("vm", "all"), ("host", "all"), ("datastore", "all"), ("cluster", "all")]),
    ("How many VMs and how many nodes?", [("vm", "all"), ("node", "all")]),
    ("How many VMs are there and how many hosts?", [("vm", "all"), ("host", "all")]),
    ("How many pods, how many nodes?", [("pod", "all"), ("node", "all")]),
    ("Datatem OLVM'de kaç VM var, kaçı kapalı?", [("vm", "all"), ("vm", "off")]),
    ("Kaç VM var ve kaç alarm var?", [("vm", "all"), None]),
    ("Kaç VM var ve kaç kullanıcı var?", [("vm", "all"), None]),
    ("Kaç node var ve en çok CPU kullanan kaç pod var?", [("node", "all"), None]),
    ("Kaç sunucu var ve kaç VM var?", [("server", "all"), ("vm", "all")]),
    ("Kaç VM askıda, kaç VM kapalı?", [("vm", "suspended"), ("vm", "off")]),
    ("Kaç çalışan VM var ve kaç bekleyen pod var?", [("vm", "on"), ("pod", "status:pending")]),
    ("office'te kaç VM var ve Datatem OLVM'de kaç VM var?", [("vm", "all"), ("vm", "all")]),
    ("Kaç datastore var, kaç cluster var?", [("datastore", "all"), ("cluster", "all")]),
    ("Kaç OpenShift cluster var ve kaç node var?", [("cluster", "all"), ("node", "all")]),
    ("Kaç VM var ve bunların kaçı kapalı?", [("vm", "all"), ("vm", "off")]),
    ("Hatalı pod sayısı kaç ve CrashLoopBackOff kaç pod var?", [("pod", "faulty"), ("pod", "reason:CrashLoopBackOff")]),
    ("Kaç host var, kaç VM var, kaç node var?", [("host", "all"), ("vm", "all"), ("node", "all")]),
    ("Kaç VM var hem de kaç node var?", [("vm", "all"), ("node", "all")]),
    ("Kaç Linux sunucum var ve kaç Windows sunucum var?", [("server", "all"), ("server", "all")]),
    ("Kaç VM var, kaç tanesi kapalı?", [("vm", "all"), ("vm", "off")]),
    ("Kaç VM ve kaçar vCPU?", [("vm", "all"), None]),
    ("Kaç sunucuda Linux ve kaçında Windows yüklü", [None, None]),
]


@pytest.mark.parametrize("q,want", COMPOUND)
def test_compound_parts(q, want):
    got = topics(q)
    assert len(got) == len(want), (q, cp.split_parts(q))
    assert got == want, (q, cp.split_parts(q), got)


def test_compound_count_at_least_40():
    assert len(COMPOUND) >= 40


def test_pronoun_inherits_scope():
    parts = cp.split_parts("office vCenter'da kaç VM var, kaçı kapalı?")
    eff = cp.resolve_pronoun(parts[1], parts[0])
    p = cr.analyze(eff, CAT, platform="unified")
    assert p.topic == "vm" and p.state == "off" and p.scope.hv_ids == [1]


def test_compound_rbac_parts():
    got = topics("Kaç VM var ve OpenShift'te kaç node var?", "unified", {"virt"})
    assert got == [("vm", "all"), None]


def test_server_kinds_in_compound():
    parts = cp.split_parts("Kaç Linux sunucu, kaç Windows sunucu var?")
    kinds = [cr.analyze(p, CAT, platform="unified").os_kinds for p in parts]
    assert kinds == [("linux",), ("windows",)]


# ── bölünmeyen (≥ 80) ─────────────────────────────────────────────────────────────

NOT_SPLIT = [
    "Kaç VM var?", "OpenShift'te kaç node var?", "Kaç VM ve host var?", "VM ve host sayısı kaç?",
    "Linux ve Windows sunucular arasındaki fark nedir?", "VM ve container arasındaki fark ne?",
    "Kaç VM'in CPU ve RAM'i yüksek?", "CPU ve RAM kullanımı en yüksek VM hangisi?",
    "office ve Datatem OLVM'deki VM'leri listele", "Kapalı ve askıdaki VM'leri göster",
    "Kaç VM açık ve çalışıyor?", "VM'leri ve hostları listele", "Hangi VM'ler kapalı ve neden?",
    "Pod ve node durumunu özetle", "Ağ ve disk gecikmesini kontrol et", "Kaç host var, hangileri bakımda?",
    "Kaç VM hangi hypervisor'da?", "Kaç gündür VM kapalı ve neden?", "VM sayısı neden arttı ve ne yapmalıyım?",
    "Tom ve Jerry VM'i açık mı?", "dev-ve-test cluster'ında kaç VM var?", "Kaç tane ve hangi VM kapalı?",
    "Snapshot ve yedek durumu nedir?", "Merhaba, nasılsın?", "Merhaba, kaç VM var?",
    "Lütfen, kaç VM var?", "Peki, kaç host var?", "VM'leri listele, kapalı olanları işaretle",
    "En çok restart eden pod hangisi?", "Son 1 saatte oVirt'te en çok CPU kullanan pod?",
    "JOBS.DWH.SYNC.01 en son ne zaman çalıştı?", "Şu an kaç iş çalışıyor?", "Hangi job'lar hata verdi?",
    "Harvester VM'i çalışıyor mu?", "2030 Ocak'ta kaç VM vardı?", "Bunların kaçı kapalı?",
    "office ve datatem arasındaki VM farkı ne?",
    "CPU, RAM ve disk kullanımını göster", "VM, host ve datastore listesini ver", "Linux, Windows ve VM özeti",
    "Kaç VM var diye sordum", "Kaç host bakımda ve neden?", "Kapalı VM'ler ve sahipleri kim?",
    "OpenShift ve VMware'i karşılaştır", "Kaç VM'i taşıyabilirim ve nereye?", "Kaç pod restart etti ve neden?",
    "Kaç namespace ve pod listesi?", "Disk ve bellek uyarıları neler?", "Kaç alarm aktif ve kritik?",
    "Host ve VM eşleşmesini göster", "Kaç VM, hangi cluster'da?", "Ve kaç VM var?",
    "kaç VM var", "KAÇ VM VAR?", "How many VMs?", "How many VMs and hosts?", "List VMs and hosts",
    "What is the difference between pods and VMs?", "Show CPU and memory usage",
    "VM'ler ve podlar nerede çalışıyor?", "Ağ, depolama ve hesaplama kapasitesi nedir?",
    "Kaç VM'de VMware Tools eski ve güncellenmeli?", "Kaç VM kapalı ve ne zamandır?",
    "Sunucular ve uygulamalar listesi", "OpenShift'teki job'lar ve cronjob'lar",
    "İş yükü ve kapasite özeti", "İşlemci ve bellek dağılımı",
    "VM sayısını ve host sayısını grafik olarak göster", "Kapasite planı ve önerileri ver",
    "Sağlık özeti ve riskler", "Kaç VM'in hem CPU'su hem RAM'i fazla?", "VM ve node arasındaki ilişki",
    "Bu hafta kaç VM açıldı ve kapandı?", "office vCenter'da ve OLVM'de kapalı VM'leri listele",
    "Kaç host, VM taşımaya uygun?", "Kaçı açık, kaçı kapalı göster",
    "a" * 310 + " kaç VM var, kaç host var?",
    "Kaç VM var, kaç host var, tablo olarak göster", "Kaç VM ve kaç host var, karşılaştır",
    "Kaç VM açık, kaç VM kapalı — grafik çiz", "Kaç pod var ve kaç node var, neden farklı?",
    "Kaç VM var ve kaç host var, listele", "Show how many VMs and how many hosts",
    "Kaçı açık, kaçı kapalı göster", "VM sayısını ve host sayısını grafik olarak göster",
    "Kaç host var ve hangisi en yoğun?", "Datastore ve cluster kapasitesi ne kadar?",
]


@pytest.mark.parametrize("q", NOT_SPLIT)
def test_not_split(q):
    assert len(cp.split_parts(q)) == 1, (q, cp.split_parts(q))


def test_not_split_count_at_least_80():
    assert len(NOT_SPLIT) >= 80


def test_multiline_not_split():
    assert len(cp.split_parts("Kaç VM var?\nKaç node var?")) == 1
