"""Adım 6d — sayım kuralı takip bağlamı (iki turlu senaryolar, saf + sahte oturum)."""
import pytest

from app.services.chat_quality import count_followup as cf
from app.services.chat_quality import count_rules as cr
from app.services.chat_quality.count_scope import HV, ScopeCatalog


def _cat() -> ScopeCatalog:
    c = ScopeCatalog()
    c.hypervisors = [HV(1, "office", "VMWARE"), HV(2, "Datatem OLVM", "KVM"), HV(3, "oVirt (OpenShift Virt)", "OPENSHIFT_VIRT")]
    c.ocp_clusters = [(2, "oVirt"), (3, "ZZ-FAKE-OCP")]
    return c


CAT = _cat()


def an(q, platform="unified", allowed=None):
    return cr.analyze(q, CAT, platform=platform, allowed_modules=allowed)


def ctx_of(*qs, platform="unified"):
    plans = [an(q, platform) for q in qs]
    assert all(plans), qs
    return cf.context_for(list(qs), plans)


def two_turn(first, second, platform="unified", allowed=None):
    """1. tur sayım kuralı → bağlam; 2. tur takip → (tür, metin, plan)."""
    ctx = ctx_of(*([first] if isinstance(first, str) else first), platform=platform)
    if an(second, platform, allowed) is not None:
        return ("direct", second, an(second, platform, allowed))
    r = cf.resolve(second, ctx, lambda q: an(q, platform, allowed))
    if r is None:
        return (None, None, None)
    return (r[0], r[1], an(r[1], platform, allowed) if r[0] == "rewrite" else None)


# ── iki turlu senaryolar (≥ 15) ────────────────────────────────────────────────────

SCENARIOS = [
    # sayım → durum (zamir)
    ("office vCenter'da kaç VM var?", "Bunların kaçı kapalı?", ("vm", "off", [1])),
    ("office vCenter'da kaç VM var?", "Kaçı açık?", ("vm", "on", [1])),
    ("Datatem OLVM'de kaç VM var?", "Bunlardan kaç tanesi kapalı?", ("vm", "off", [2])),
    ("Kaç VM var?", "Bunların kaçı askıda?", ("vm", "suspended", None)),
    ("VM sayısı kaç?", "Kaçı kapalı?", ("vm", "off", None)),
    ("Kaç pod var?", "Bunların kaçı hatalı?", ("pod", "faulty", None)),
    ("oVirt'te kaç pod var?", "Kaçı bekleyen?", ("pod", "status:pending", None)),
    # sayım → platform değiştir
    ("office vCenter'da kaç kapalı VM var?", "Peki Datatem OLVM'de?", ("vm", "off", [2])),
    ("office vCenter'da kaç VM var?", "Ya Datatem OLVM için?", ("vm", "all", [2])),
    ("oVirt'te kaç hatalı pod var?", "Peki ZZ-FAKE-OCP'de?", ("pod", "faulty", None)),
    ("Kaç Linux sunucum var?", "Peki Windows?", ("server", "all", None)),
    ("office'te kaç host var?", "Peki Datatem OLVM'de?", ("host", "all", [2])),
]


@pytest.mark.parametrize("first,second,want", SCENARIOS)
def test_two_turn(first, second, want):
    kind, q, plan = two_turn(first, second)
    assert kind == "rewrite", (first, second, kind, q)
    topic, state, hv = want
    assert plan.topic == topic
    assert (plan.pod_filter if topic == "pod" else plan.state) == state
    if hv is not None:
        assert plan.scope.hv_ids == hv


def test_switch_keeps_os_kind():
    _, q, plan = two_turn("Kaç Linux sunucum var?", "Peki Windows?")
    assert plan.os_kinds == ("windows",)


def test_switch_ocp_cluster_scope():
    _, q, plan = two_turn("oVirt'te kaç hatalı pod var?", "Peki ZZ-FAKE-OCP'de?")
    assert plan.ocp_scope.ocp_ids == [3]


def test_new_explicit_scope_overrides_context():
    kind, q, plan = two_turn("office vCenter'da kaç VM var?", "Datatem OLVM'de kaç kapalı VM var?")
    assert kind == "direct" and plan.scope.hv_ids == [2]


def test_compound_context_disambiguates_by_state():
    # kapalı yalnız VM için anlamlı → tek aday
    kind, q, plan = two_turn(["Kaç VM var?", "OpenShift'te kaç node var?"], "Bunların kaçı kapalı?")
    assert kind == "rewrite" and plan.topic == "vm" and plan.state == "off"


def test_compound_context_ambiguous_asks():
    kind, text, _ = two_turn(["office vCenter'da kaç VM var?", "Datatem OLVM'de kaç VM var?"], "Bunların kaçı kapalı?")
    assert kind == "clarify" and "hangisini" in text.lower()
    assert "office" in text and "Datatem OLVM" in text


def test_no_context_no_rewrite():
    assert cf.resolve("Bunların kaçı kapalı?", None, an) is None
    assert cf.resolve("Bunların kaçı kapalı?", {"v": 1, "items": []}, an) is None


def test_non_followup_shape_ignored():
    ctx = ctx_of("Kaç VM var?")
    for q in ("Merhaba", "Harvester VM'i çalışıyor mu?", "En çok CPU kullanan VM hangisi?", "Peki durumu ne?"):
        assert cf.resolve(q, ctx, an) is None, q


def test_rbac_blocks_inherited_topic():
    ctx = ctx_of("Kaç pod var?")
    assert cf.resolve("Bunların kaçı hatalı?", ctx, lambda q: an(q, "unified", {"virt"})) is None


def test_pronoun_without_state_not_resolved():
    ctx = ctx_of("Kaç VM var?")
    assert cf.resolve("Bunların kaçı?", ctx, an) is None


def test_scenarios_at_least_15():
    assert len(SCENARIOS) + 8 >= 15


# ── bağlam kaydı / yükleme ─────────────────────────────────────────────────────────

def test_context_for_and_core():
    ctx = ctx_of("office vCenter'da kaç kapalı VM var?", "Kaç hatalı pod var?", "Kaç Linux sunucum var?")
    cores = [i["core"] for i in ctx["items"]]
    assert cores == ["kaç kapalı VM", "kaç hatalı pod", "kaç sunucu"]


def test_set_pop_context():
    cf.set_context({"v": 1, "items": [{"q": "x"}]})
    assert cf.pop_context() == {"v": 1, "items": [{"q": "x"}]}
    assert cf.pop_context() is None


class _Q:
    def __init__(self, rows):
        self.rows = rows

    def filter(self, *a):
        return self

    def order_by(self, *a):
        return self

    def limit(self, n):
        self.rows = self.rows[:n]
        return self

    def all(self):
        return [(r,) for r in self.rows]


class _DB:
    def __init__(self, rows):
        self.rows = rows

    def query(self, *a):
        return _Q(list(self.rows))


def test_load_recent_within_max_turns():
    c = {"v": 1, "items": [{"q": "Kaç VM var?", "topic": "vm", "core": "kaç VM"}]}
    assert cf.load_recent(_DB([{"intents": []}, {"count_context": c}]), 5) == c
    old = [{"intents": []}] * 3 + [{"count_context": c}]
    assert cf.load_recent(_DB(old), 5) is None
    assert cf.load_recent(_DB([{"count_context": c}]), None) is None
