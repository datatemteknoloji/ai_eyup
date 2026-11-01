"""Adım 7a — yanlış öncül kuralı (saf; DB sahte). Hüküm, sayım kuralının cevap başlığındaki sayıdan çıkar."""
import pytest

from app.services.chat_quality import count_rules as cr
from app.services.chat_quality import premise
from app.services.chat_quality import trace as cq_trace
from app.services.chat_quality.count_scope import HV, ScopeCatalog

TOTAL = {(1,): 33, (2,): 18, (3,): 4}
OFF = {33: 19, 18: 10, 4: 0, 1556: 86}


def _cat() -> ScopeCatalog:
    c = ScopeCatalog()
    c.hypervisors = [HV(1, "office", "VMWARE"), HV(2, "Datatem OLVM", "KVM"), HV(3, "labvc", "VMWARE")]
    c.ocp_clusters = [(2, "oVirt"), (3, "ZZ-FAKE-OCP")]
    return c


CAT = _cat()


def _fake_answer(plan, cat, db):
    if plan.topic == "vm":
        T = TOTAL.get(tuple(plan.scope.hv_ids or ()), 1556)
        off = OFF[T]
        if plan.state == "off":
            return f"**Kapalı VM: {off}** (kapsamdaki toplam {T} VM içinde)\n\nKapsam: x"
        if plan.state == "on":
            return f"**Çalışan (açık) VM: {T - off}** (kapsamdaki toplam {T} VM içinde)\n\nKapsam: x"
        if plan.state == "suspended":
            return f"**Askıda VM: 0** (kapsamdaki toplam {T} VM içinde)\n\nKapsam: x"
        return f"**Toplam VM: {T}**\n\nKapsam: x"
    if plan.topic == "pod":
        if plan.pod_filter == "faulty":
            return "**Hatalı pod: 112** (kapsamdaki toplam 333 pod içinde)\n\nKapsam: x"
        return "**Toplam pod: 333**\n\nKapsam: x"
    if plan.topic == "node":
        n = 3 if plan.ocp_scope.ocp_ids == [2] else 18
        return f"**Toplam node: {n}**\n\nKapsam: x"
    if plan.topic == "host":
        return "**Toplam host: 12**\n\nKapsam: x"
    if plan.topic == "cluster":
        return "**Toplam cluster: 4**\n\nKapsam: x"
    return None


class _DB:
    rows = [("master-0", "Ready", 2), ("master-1", "NotReady", 2), ("master-2", "Ready", 2)]

    def close(self):
        pass

    def execute(self, *a, **k):
        rows = self.rows

        class _R:
            def all(self_inner):
                return rows
        return _R()


@pytest.fixture(autouse=True)
def _setup(monkeypatch):
    cr.set_catalog_for_tests(CAT)
    monkeypatch.setattr(cr, "_enabled", lambda: True)
    monkeypatch.setattr(cr, "answer", _fake_answer)
    monkeypatch.setattr(cr, "fetch_ocp_last_sync", lambda db, ids: None)
    import app.core.database as dbm
    monkeypatch.setattr(dbm, "ThreadSessionLocal", lambda: _DB())
    yield
    cr.set_catalog_for_tests(None)


def run(q, platform="unified", allowed=None):
    return premise.respond(q, platform=platform, allowed_modules=allowed)


# ── öncüllü sorular (≥ 40; TR/EN; doğru ve yanlış karışık) ─────────────────────────

# (soru, hüküm anahtar sözcüğü, metinde geçmesi gereken sayı/parça)
PREMISES = [
    # sayı öncülü — yanlış
    ("office vCenter'da 46 VM var, bunların kaçı kapalı?", "Öncül yanlış", "**33**"),
    ("Ortamda 3000 VM var, kaçı kapalı?", "Öncül yanlış", "**1556**"),
    ("Datatem OLVM'de 40 VM var, kaçı kapalı?", "Öncül yanlış", "**18**"),
    ("Ortamda 2000 VM var, kaçı açık?", "Öncül yanlış", "**1556**"),
    ("office'te 50 VM var, bunlardan kaç tanesi çalışıyor?", "Öncül yanlış", "**33**"),
    ("Sistemde 5000 VM var, doğru mu?", "Öncül yanlış", "**1556**"),
    ("Ortamda 100 VM var, değil mi?", "Öncül yanlış", "**1556**"),
    ("Ortamda 20 VM var ve kaçı kapalı?", "Öncül yanlış", "**1556**"),
    ("Datatem OLVM'de 200 VM var, peki kaçı kapalı?", "Öncül yanlış", "**18**"),
    ("OpenShift'te 99 node var, doğru mu?", "Öncül yanlış", "**18**"),
    ("oVirt cluster'ında 12 node var, doğru mu?", "Öncül yanlış", "**3**"),
    ("OpenShift'te 500 pod var, kaçı hatalı?", "Öncül yanlış", "**333**"),
    ("Ortamda 7 cluster var, doğru mu?", "Öncül yanlış", "**4**"),
    ("Ortamda 100 host var, doğru mu?", "Öncül yanlış", "**12**"),
    # sayı öncülü — doğru
    ("Ortamda 1556 VM var, doğru mu?", "Öncül doğru", "**1556**"),
    ("Datatem OLVM'de 18 VM var, bunların kaçı kapalı?", "Öncül doğru", "**18**"),
    ("office vCenter'da 33 VM var, kaçı kapalı?", "Öncül doğru", "**33**"),
    ("Ortamda 1556 VM var, kaçı açık?", "Öncül doğru", "**1556**"),
    ("OpenShift'te 333 pod var, kaçı hatalı?", "Öncül doğru", "**333**"),
    ("oVirt cluster'ında 3 node var, doğru mu?", "Öncül doğru", "**3**"),
    # İngilizce sayı öncülü
    ("We have 3000 VMs, how many are off?", "Öncül yanlış", "**1556**"),
    ("There are 46 VMs on office, how many are off?", "Öncül yanlış", "**33**"),
    ("We have 1556 VMs, how many are powered off?", "Öncül doğru", "**1556**"),
    # yokluk öncülü
    ("Datatem OLVM'de hiç kapalı VM yok, doğru mu?", "Hayır", "**10**"),
    ("Hiç kapalı VM yok, değil mi?", "Hayır", "**86**"),
    ("office vCenter'da hiç kapalı VM yok, doğru mu?", "Hayır", "**19**"),
    ("Hiç askıda VM yok, değil mi?", "Evet", "yok (0)"),
    ("labvc'de hiç kapalı VM yok, doğru mu?", "Evet", "yok (0)"),
    ("Tüm clusterlarda hiç hatalı pod yok, değil mi?", "Hayır", "**112**"),
    ("OpenShift'te hiç sorunlu pod yok, değil mi?", "Hayır", "**112**"),
    ("Hiç hatalı pod yok mu?", "Hayır", "**112**"),
    ("There are no powered off VMs, right?", "Hayır", "**86**"),
    ("No suspended VMs, correct?", "Evet", "yok (0)"),
    # evrensel öncül
    ("Tüm VM'ler çalışıyor, değil mi?", "Hayır", "olmayan **86**"),
    ("Bütün VM'ler açık, doğru mu?", "Hayır", "olmayan **86**"),
    ("Datatem OLVM'de tüm VM'ler çalışıyor, değil mi?", "Hayır", "olmayan **10**"),
    ("Tüm VM'ler kapalı, doğru mu?", "Hayır", "olmayan **1470**"),
    ("Tüm VM'ler çalışıyor mu?", "Hayır", "olmayan **86**"),
    ("labvc'de tüm VM'ler çalışıyor, değil mi?", "Evet", "hepsi"),
    ("All VMs are running, right?", "Hayır", "olmayan **86**"),
    ("All VMs are off, correct?", "Hayır", "olmayan **1470**"),
    ("All the VMs are running, right?", "Hayır", "olmayan **86**"),
]


def test_premise_count_at_least_40():
    assert len(PREMISES) >= 40


@pytest.mark.parametrize("q,verdict,needle", PREMISES)
def test_premise_verdict(q, verdict, needle):
    r = run(q)
    assert r is not None, q
    text, plan, eff, trace = r
    assert verdict in text.split("\n")[0], (q, text.split("\n")[0])
    assert needle in text, (q, text[:300])
    assert plan is not None and eff


def test_wrong_premise_names_both_numbers():
    text = run("Ortamda 3000 VM var, kaçı kapalı?")[0]
    first = text.split("\n")[0]
    assert "3000" in first and "1556" in first and "değil" in first
    assert "Kapalı VM: 86" in text      # sorulan sayım yine cevaplanır


def test_trace_dict():
    _, _, _, tr = run("office vCenter'da 46 VM var, bunların kaçı kapalı?")
    assert tr["form"] == "claim" and tr["claimed"] == 46 and tr["total"] == 33 and tr["n"] == 19
    _, _, _, tr = run("Tüm VM'ler çalışıyor, değil mi?")
    assert tr["form"] == "universal" and tr["verdict"] == "Hayır"
    _, _, _, tr = run("Datatem OLVM'de hiç kapalı VM yok, doğru mu?")
    assert tr["form"] == "absence" and tr["verdict"] == "Hayır"


# ── node Ready/NotReady (o35) ─────────────────────────────────────────────────────

def test_node_notready_wrong_claim():
    text, plan, _, tr = run("oVirt cluster'ında 12 node var, hangisi NotReady?")
    assert "Öncül yanlış" in text and "**12**" in text and "**3**" in text
    assert "NotReady node: **1**" in text and "master-1" in text
    assert tr["form"] == "claim_which"


def test_node_ready_claim_right():
    text = run("oVirt cluster'ında 3 node var, hangileri Ready?")[0]
    assert "Öncül doğru" in text and "Ready node: **2**" in text


def test_node_which_unknown_state_not_handled():
    assert run("oVirt cluster'ında 12 node var, hangisi kapalı?") is None


def test_which_for_vm_not_handled():
    assert run("office'te 46 VM var, hangileri kapalı?") is None


# ── RBAC ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q,platform,allowed", [
    ("Ortamda 3000 VM var, kaçı kapalı?", "unified", {"openshift"}),
    ("Tüm VM'ler çalışıyor, değil mi?", "unified", {"openshift"}),
    ("Datatem OLVM'de hiç kapalı VM yok, doğru mu?", "unified", {"linux"}),
    ("Tüm clusterlarda hiç hatalı pod yok, değil mi?", "unified", {"virt"}),
    ("OpenShift'te 99 node var, doğru mu?", "unified", {"virt"}),
    ("oVirt cluster'ında 12 node var, hangisi NotReady?", "unified", {"virt"}),
    ("Tüm clusterlarda hiç hatalı pod yok, değil mi?", "virt", None),
    ("Ortamda 3000 VM var, kaçı kapalı?", "openshift", None),
    ("Ortamda 3000 VM var, kaçı kapalı?", "linux", None),
    ("Tüm VM'ler çalışıyor, değil mi?", "windows", None),
])
def test_rbac_no_leak(q, platform, allowed):
    assert run(q, platform=platform, allowed=allowed) is None


@pytest.mark.parametrize("q,platform,allowed", [
    ("Ortamda 3000 VM var, kaçı kapalı?", "unified", {"virt"}),
    ("Ortamda 3000 VM var, kaçı kapalı?", "virt", None),
    ("Tüm clusterlarda hiç hatalı pod yok, değil mi?", "unified", {"openshift"}),
    ("Tüm clusterlarda hiç hatalı pod yok, değil mi?", "openshift", None),
    ("oVirt cluster'ında 12 node var, hangisi NotReady?", "openshift", None),
])
def test_rbac_allowed(q, platform, allowed):
    assert run(q, platform=platform, allowed=allowed) is not None


# ── öncülsüz / zararsız sorular: kural girmez (≥ 80) ───────────────────────────────

_NUMS = (1, 5, 46, 100, 2500, 3000)
BENIGN = (
    [f"{n} numaralı VM nerede?" for n in _NUMS]
    + [f"{n} host'u listele" for n in _NUMS]
    + [f"VM{n} hangi hostta?" for n in _NUMS]
    + [f"Son {n} günde kaç VM oluşturuldu?" for n in _NUMS]
    + [f"{n} vCPU'lu VM hangileri?" for n in _NUMS]
    + [f"{n} GB RAM'i olan VM'ler" for n in _NUMS]
    + [f"En çok CPU kullanan {n} VM" for n in _NUMS]
    + [f"İlk {n} VM'i göster" for n in _NUMS]
    + [
        "Kaç VM var?", "Kaç host var?", "Kapalı VM'ler hangileri?", "Tüm VM'leri listele",
        "Tüm VM'lerin CPU kullanımı nedir?", "Tüm host'lar nerede?", "Bütün VM'leri göster",
        "Hiç VM açma", "Hiçbir VM kapatılmasın", "VM var mı?", "Kapalı VM var mı?", "46 VM var mı?",
        "Hiç kapalı VM var mı?", "Harvester VM'i çalışıyor mu?", "Merhaba", "Tüm clusterlar nerede?",
        "OpenShift'te kaç pod var?", "Kaç node var?", "3000 VM'i dışa aktar", "46 VM'i kapat",
        "Tüm VM'ler hangi hypervisor'da?", "Tüm VM'lerin adı", "Hiç alarm yok mu?", "Alarm yok, değil mi?",
        "Bugün 46 VM açıldı, doğru mu?", "Dün 100 VM kapandı, değil mi?", "Son 3 günde hiç restart yok, değil mi?",
        "CPU kullanımı yüzde 90, doğru mu?", "Disk 500 GB dolu, değil mi?", "VM sayısı kaç, 46 mı?",
        "46", "VM", "", "Tüm", "hiç yok",
    ]
)


def test_benign_count_at_least_80():
    assert len(BENIGN) >= 80


@pytest.mark.parametrize("q", BENIGN)
def test_benign_not_premise(q):
    assert run(q) is None, q


def test_looks_like_premise_matches_respond_shapes():
    for q, *_ in PREMISES:
        assert premise.looks_like_premise(q), q
    for q in BENIGN:
        assert not premise.looks_like_premise(q), q


def test_long_or_multiline_ignored():
    assert run("Ortamda 3000 VM var, kaçı kapalı?\nBir de şunu sor") is None
    assert run("x " * 200 + "Ortamda 3000 VM var, kaçı kapalı?") is None


# ── sayım kuralı entegrasyonu: iz, bağlam, kapatma ─────────────────────────────────

def test_count_response_traces_premise():
    tr = cq_trace.TurnTrace(turn_id="t")
    tok = cq_trace.bind(tr)
    try:
        text = cr.count_response("Ortamda 3000 VM var, kaçı kapalı?", platform="unified", allowed_modules=None)
    finally:
        cq_trace.unbind(tok)
    assert text and "Öncül yanlış" in text
    qa = [p for p in tr.paths if p.get("kind") == "qa_rule"]
    assert qa and qa[0]["handler"] == "count_rules.premise.claim"
    assert qa[0]["premise"]["claimed"] == 3000 and qa[0]["premise"]["total"] == 1556


def test_count_response_sets_followup_context():
    from app.services.chat_quality import count_followup as cf
    cr.count_response("Tüm VM'ler çalışıyor, değil mi?", platform="unified", allowed_modules=None)
    ctx = cf.pop_context()
    assert ctx and ctx["items"] and ctx["items"][0]["topic"] == "vm"


def test_kill_switch(monkeypatch):
    monkeypatch.setattr(cr, "_enabled", lambda: False)
    assert run("Ortamda 3000 VM var, kaçı kapalı?") is None


def test_normal_count_unchanged():
    text = cr.count_response("Kaç VM var?", platform="unified", allowed_modules=None)
    assert text and "Öncül" not in text


# ── tam tarama onay kapısı ─────────────────────────────────────────────────────────

def test_full_scan_gate_skipped_for_premise():
    from app.services.chat_full_scan_policy import resolve_full_scan_turn
    r = resolve_full_scan_turn(None, session_id=None, message="Tüm VM'ler çalışıyor, değil mi?", platform="virt")
    assert r["action"] == "proceed" and not r["full_scan"] and r.get("premise_gate")


def test_full_scan_gate_still_for_list_requests(monkeypatch):
    from app.services import chat_full_scan_policy as fsp
    monkeypatch.setattr(fsp, "count_fleet_candidates", lambda db, platform=None: 1552)
    monkeypatch.setattr(fsp, "set_full_scan_pending", lambda *a, **k: None)
    r = fsp.resolve_full_scan_turn(None, session_id=None, message="Tüm VM'leri listele", platform="virt")
    assert r["action"] == "clarify"
