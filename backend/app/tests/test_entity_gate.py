"""Adım 4 — varlık çözümleyici kapısı birim testleri (DB gerekmez; sentetik katalog)."""
from __future__ import annotations

import pytest

from app.services.chat_quality import entity_gate as eg
from app.services.chat_quality.claims import fold
from app.tests import entity_gate_cases as C


def _rec(name, hv_name, hv_type, power="POWERED_OFF", host=None, ip="10.0.0.1", os_="Linux"):
    return {"name": name, "hypervisor_name": hv_name, "hypervisor_type": hv_type, "power": power,
            "host": host, "cluster": None, "ip": ip, "os": os_}


def _catalog() -> eg.Catalog:
    cat = eg.Catalog()
    for n in ("office", "Datatem OLVM", "oVirt (OpenShift Virt)", "VMware vCenter Server-Test", "web-prod-01",
              "app-server-1", "esx01.corp.local", "ds-fast-01", "kube-system", "openshift-monitoring",
              "ocp-cluster-a", "prod-ns-1", "node-worker-1", "mtv-testserver", "rhel8-10tst", "datatemengine"):
        cat.add(n)
    two = lambda n, a, b: [_rec(n, *a), _rec(n, *b)]
    off = ("office", "VMWARE")
    ovirt = ("oVirt (OpenShift Virt)", "OPENSHIFT_VIRT")
    olvm = ("Datatem OLVM", "KVM")
    cat.dupes = {
        "mtv-testserver": two("mtv-testserver", off, ovirt),
        "rhel8-10tst": two("rhel8-10tst", off, ovirt),
        "datatemengine": two("datatemengine", off, olvm),
    }
    return cat


@pytest.fixture
def cat():
    return _catalog()


# ── çıkarım ───────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("msg,expected", [
    ("ZZ-NOPE-VM-999 VM'i hangi hostta?", ["ZZ-NOPE-VM-999"]),
    ("nonexistent-ns namespace'inde kaç pod var?", ["nonexistent-ns"]),
    ("foo-bar-1 sunucusunun CPU'su?", ["foo-bar-1"]),
    ("web-01 çalışıyor mu?", []),                       # tip adı yok
    ("node-exporter sunucuda çalışıyor mu?", []),       # yazılım öneki + düz bulunma hâli
    ("10.0.0.5 sunucusu açık mı?", []),                 # IP
    ("df -h komutu sunucuda ne gösterir", []),
    ("rhel-9.4 sunucuları listele", []),                # yazılım öneki
    ("Linux sunucuda disk dolu mu", []),
    ("config.yaml dosyası sunucuda mı", []),            # dosya uzantısı
])
def test_candidate_tokens(msg, expected):
    assert eg.candidate_tokens(msg) == expected


def test_plain_locative_not_a_frame():
    # "sunucuda" düz bulunma hâli: niteleyici kullanım → aday yok
    assert eg.candidate_tokens("zz-nope-7 sunucuda çalışıyor mu") == []


def test_possessive_forms_are_frames():
    for suffix in ("sunucusunun", "sunucusu", "sunucunun"):
        assert eg.candidate_tokens(f"ghost-1 {suffix} durumu") == ["ghost-1"]


def test_english_frame():
    assert eg.candidate_tokens("Is ZZ-NOPE-VM-55 vm running?") == ["ZZ-NOPE-VM-55"]


def test_two_type_nouns_adjacent_ignored():
    assert eg.candidate_tokens("VM sunucu host listesi") == []


def test_identifier_like_rules():
    assert eg._identifier_like("ZZ-NOPE-1")
    assert eg._identifier_like("srv_07")
    assert not eg._identifier_like("sunucu")      # rakam/tire yok
    assert not eg._identifier_like("1234")
    assert not eg._identifier_like("10.1.1.1")
    assert not eg._identifier_like("kube-apiserver")
    assert not eg._identifier_like("log.txt")


# ── katalog eşleşmesi ──────────────────────────────────────────────────────────

def test_is_known_exact_and_case(cat):
    assert eg.is_known("WEB-PROD-01", cat)
    assert eg.is_known("web-prod-01", cat)


def test_is_known_fqdn_short(cat):
    assert eg.is_known("esx01", cat)
    assert eg.is_known("esx01.corp.local", cat)


def test_is_known_rejects_short_prefix_collision(cat):
    cat.add("vcenter")
    assert not eg.is_known("vcenter-yok.local", cat)


def test_is_known_close_length_variant(cat):
    assert eg.is_known("web-prod-011", cat)        # uzunluk oranı ≥ 0.8


def test_multiword_name_last_token_not_flagged(cat):
    r = eg.resolve("VMware vCenter Server-Test VM'i hangi hostta?", cat)
    assert r is None


# ── çözümleme: sıfır eşleşme ──────────────────────────────────────────────────

def test_ghost_basic(cat):
    r = eg.resolve("ZZ-NOPE-VM-999 VM'i hangi hostta?", cat)
    assert r and r.kind == eg.KIND_NOT_FOUND and r.entity == "ZZ-NOPE-VM-999"
    assert "bulunamadı" in r.text and "tahmin yürütmüyorum" in r.text


def test_known_name_passes(cat):
    assert eg.resolve("web-prod-01 VM'i hangi hostta?", cat) is None
    assert eg.resolve("prod-ns-1 namespace'inde kaç pod var?", cat) is None
    assert eg.resolve("ocp-cluster-a cluster'ında kaç node var?", cat) is None


def test_similar_names_from_db_only(cat):
    r = eg.resolve("web-prod-02 VM'i açık mı?", cat)
    assert r and r.kind == eg.KIND_NOT_FOUND
    assert "web-prod-01" in r.text           # benzer ad DB'den
    r2 = eg.resolve("zzqq-9 VM'i açık mı?", cat)
    assert "Benzer adlar" not in r2.text


def test_ghost_set(cat):
    miss = []
    for q, ent in C.GHOST:
        r = eg.resolve(q, cat, allow_virt_list=True)
        if not (r and r.kind == eg.KIND_NOT_FOUND and r.entity == ent):
            miss.append(q)
    assert not miss, miss


def test_harmless_set_never_triggers(cat):
    bad = [q for q in C.HARMLESS if eg.resolve(q, cat, allow_virt_list=True)]
    assert not bad, bad


def test_harmless_never_triggers_without_virt(cat):
    assert not [q for q in C.HARMLESS if eg.resolve(q, cat, allow_virt_list=False)]


# ── çoklu eşleşme ─────────────────────────────────────────────────────────────

def test_multi_set(cat):
    miss = [q for q in C.MULTI
            if not ((r := eg.resolve(q, cat, allow_virt_list=True)) and r.kind == eg.KIND_AMBIGUOUS)]
    assert not miss, miss


def test_ambiguous_text_has_table_and_question(cat):
    r = eg.resolve("mtv-testserver açık mı?", cat, allow_virt_list=True)
    assert r.matches == 2
    assert "hangisini kastettiğinizi" in r.text
    assert "| # | Hypervisor |" in r.text
    assert "office" in r.text and "oVirt" in r.text
    assert "VMware vCenter" in r.text and "OpenShift Virtualization" in r.text


def test_narrowed_set_no_gate(cat):
    bad = [q for q in C.NARROWED if eg.resolve(q, cat, allow_virt_list=True)]
    assert not bad, bad


def test_narrow_by_hypervisor_name(cat):
    assert eg.resolve("office üzerindeki mtv-testserver açık mı?", cat, allow_virt_list=True) is None


def test_narrow_word_boundary(cat):
    # "datatem" sözcüğü "datatemengine" içinde geçse de daraltma sayılmaz
    r = eg.resolve("datatemengine hangi cluster'da?", cat, allow_virt_list=True)
    assert r and r.kind == eg.KIND_AMBIGUOUS


def test_ambiguous_requires_virt_access(cat):
    assert eg.resolve("mtv-testserver açık mı?", cat, allow_virt_list=False) is None


def test_ambiguous_name_not_matched_inside_longer_name(cat):
    assert eg.resolve("mtv-testserver-2 durumu ne?", cat, allow_virt_list=True) is None


# ── RBAC / platform ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("plat,mods,expected", [
    ("virt", None, True), ("hypervisor", None, True), ("virtualization", set(), True),
    ("unified", None, True), ("unified", {"virt", "linux"}, True), ("unified", {"linux"}, False),
    ("unified", set(), False), ("windows", None, False), ("ocp", None, False), (None, None, False),
])
def test_virt_list_allowed(plat, mods, expected):
    assert eg.virt_list_allowed(plat, mods) is expected


# ── metin güvenliği ───────────────────────────────────────────────────────────

def test_echo_escapes_markdown_and_truncates():
    t = eg._echo("**bold** `x` [l](u) <b> | _z_")
    for ch in "*`[]()<>|_":
        assert "\\" + ch in t
    assert len(eg._echo("a" * 500)) <= eg._MAX_ECHO


def test_cell_pipe_and_none():
    assert eg._cell(None) == "—"
    assert "|" not in eg._cell("a|b").replace("\\|", "")


def test_not_found_text_escapes_entity():
    t = eg.not_found_text("zz-1_<script>", [])
    assert "<script>" not in t


def test_type_key_normalisation():
    import enum

    class T(str, enum.Enum):
        VMWARE = "vmware"
    assert eg._type_key(T.VMWARE) == "VMWARE"
    assert eg._type_key("HypervisorType.KVM") == "KVM"
    assert eg._type_key("openshift_virt") == "OPENSHIFT_VIRT"
    assert eg._type_key(None) == ""


def test_narrow_with_enum_style_type():
    recs = [_rec("x-1", "alpha", "HypervisorType.VMWARE"), _rec("x-1", "beta", "HypervisorType.KVM")]
    assert len(eg._narrow(fold("vmware üzerindeki x-1"), recs)) == 1


# ── kapı (DB'siz) + kapatma anahtarı ──────────────────────────────────────────

@pytest.fixture
def injected(cat):
    eg.set_catalog_for_tests(cat)
    yield cat
    eg.set_catalog_for_tests(None)


def test_gate_response_ghost(injected):
    out = eg.gate_response("ZZ-NOPE-VM-999 VM'i hangi hostta?", platform="virt")
    assert out and "bulunamadı" in out


def test_gate_response_multi_virt_vs_linux(injected):
    assert eg.gate_response("mtv-testserver açık mı?", platform="virt")
    assert eg.gate_response("mtv-testserver açık mı?", platform="unified", allowed_modules={"virt"})
    assert eg.gate_response("mtv-testserver açık mı?", platform="unified", allowed_modules={"linux"}) is None
    assert eg.gate_response("mtv-testserver açık mı?", platform="windows") is None


def test_gate_off_switch(injected, monkeypatch):
    monkeypatch.setattr(eg, "_enabled", lambda: False)
    assert eg.gate_response("ZZ-NOPE-VM-999 VM'i hangi hostta?", platform="virt") is None


def test_gate_off_when_catalog_incomplete(injected):
    injected.ok = False
    assert eg.gate_response("ZZ-NOPE-VM-999 VM'i hangi hostta?", platform="virt") is None


def test_gate_off_when_catalog_empty():
    eg.set_catalog_for_tests(eg.Catalog())
    try:
        assert eg.gate_response("ZZ-NOPE-VM-999 VM'i hangi hostta?", platform="virt") is None
    finally:
        eg.set_catalog_for_tests(None)


def test_gate_db_failure_is_safe(monkeypatch):
    eg.set_catalog_for_tests(None)
    eg.clear_cache()
    monkeypatch.setattr(eg, "_load_catalog", lambda: (_ for _ in ()).throw(RuntimeError("db down")))
    assert eg.gate_response("ZZ-NOPE-VM-999 VM'i hangi hostta?", platform="virt") is None
    eg.clear_cache()


def test_catalog_cached(monkeypatch):
    eg.set_catalog_for_tests(None)
    eg.clear_cache()
    calls = []
    monkeypatch.setattr(eg, "_load_catalog", lambda: calls.append(1) or _catalog())
    eg.get_catalog()
    eg.get_catalog()
    assert len(calls) == 1
    eg.clear_cache()


def test_setting_registered_default_on():
    from app.services import runtime_settings as rs
    assert rs.get_bool("chat_entity_gate_enabled") is True


# ── hat entegrasyonu ──────────────────────────────────────────────────────────

def test_canned_answer_integration(injected):
    from app.services.chat_chitchat_policy import canned_chitchat_answer
    out = canned_chitchat_answer("ZZ-NOPE-VM-999 VM'i hangi hostta?", platform="virt")
    assert out and "bulunamadı" in out
    assert canned_chitchat_answer("web-prod-01 VM'i hangi hostta?", platform="virt") is None
    assert canned_chitchat_answer("mtv-testserver açık mı?", platform="unified", allowed_modules=None)
    assert canned_chitchat_answer("mtv-testserver açık mı?", platform="unified", allowed_modules={"linux"}) is None


def test_action_gate_has_priority(injected):
    from app.services.chat_chitchat_policy import canned_chitchat_answer
    out = canned_chitchat_answer("datatemengine VM'ini kapat", platform="unified", allowed_modules=None)
    assert out and "| # | Hypervisor |" not in out      # eylem reddi; çoklu eşleşme listesi değil
    assert eg.resolve("datatemengine VM'ini kapat", injected, allow_virt_list=True)   # kapı tek başına tetiklerdi


def test_chitchat_still_works(injected):
    from app.services.chat_chitchat_policy import canned_chitchat_answer
    assert canned_chitchat_answer("merhaba", platform="virt")


def test_gate_error_does_not_break_pipeline(monkeypatch):
    from app.services.chat_chitchat_policy import canned_chitchat_answer
    monkeypatch.setattr(eg, "get_catalog", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert canned_chitchat_answer("web-prod-01 VM'i hangi hostta?", platform="virt") is None


# ── önbellek: bayat kopya + arka plan yenileme ────────────────────────────────

def test_expired_cache_returns_stale_and_refreshes(monkeypatch):
    import threading
    import time as _t
    eg.set_catalog_for_tests(None)
    eg.clear_cache()
    stale = _catalog()
    fresh = _catalog()
    fresh.add("brand-new-vm-1")
    calls = []
    done = threading.Event()

    def loader():
        calls.append(1)
        done.set()
        return fresh

    monkeypatch.setattr(eg, "_load_catalog", loader)
    eg._cache = (_t.monotonic() - eg._CATALOG_TTL_SEC - 5, stale)   # süresi dolmuş ama taze sayılacak kadar yeni
    got = eg.get_catalog()
    assert got is stale                      # kullanıcı yüklemeyi beklemedi
    assert done.wait(2)
    for _ in range(50):
        if eg._cache[1] is fresh:
            break
        _t.sleep(0.02)
    assert eg._cache[1] is fresh and len(calls) == 1
    eg.clear_cache()


def test_very_old_cache_reloads_synchronously(monkeypatch):
    import time as _t
    eg.set_catalog_for_tests(None)
    fresh = _catalog()
    monkeypatch.setattr(eg, "_load_catalog", lambda: fresh)
    eg._cache = (_t.monotonic() - eg._MAX_STALE_SEC - 5, _catalog())
    assert eg.get_catalog() is fresh
    eg.clear_cache()


def test_refresh_is_single_flight(monkeypatch):
    import threading
    import time as _t
    eg.set_catalog_for_tests(None)
    eg.clear_cache()
    gate = threading.Event()
    calls = []

    def slow():
        calls.append(1)
        gate.wait(2)
        return _catalog()

    monkeypatch.setattr(eg, "_load_catalog", slow)
    eg._cache = (_t.monotonic() - eg._CATALOG_TTL_SEC - 1, _catalog())
    for _ in range(5):
        eg.get_catalog()
    gate.set()
    _t.sleep(0.2)
    assert len(calls) == 1
    eg.clear_cache()
