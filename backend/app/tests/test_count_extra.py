"""Adım 6 K2/K3 — pod / hatalı pod ve Linux / Windows sunucu sayım kuralı (saf kısım)."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.chat_quality import count_extra as cx
from app.services.chat_quality import count_rules as cr
from app.services.chat_quality import ocp_pod_stats as ps
from app.services.chat_quality.count_scope import HV, ScopeCatalog


def _cat() -> ScopeCatalog:
    c = ScopeCatalog()
    c.hypervisors = [HV(1, "office", "VMWARE")]
    c.ocp_clusters = [(2, "oVirt"), (3, "ZZ-FAKE-OCP")]
    return c


CAT = _cat()
NOW = datetime(2026, 10, 21, 12, 0, tzinfo=timezone.utc)
SYNCS = {2: NOW - timedelta(minutes=5), 3: NOW - timedelta(days=7)}
GROUPS = [
    (2, "Running", "", 0, 226), (2, "Running", "PodInitializing", 0, 4), (2, "Running", "RunContainerError", 0, 7),
    (2, "Running", "", 1, 3), (2, "Succeeded", "", 0, 81), (2, "CrashLoopBackOff", "CrashLoopBackOff", 1, 2),
    (2, "Error", "Error", 0, 10), (2, "Pending", "", 0, 2), (3, "Running", "", 0, 443), (3, "Succeeded", "", 0, 57),
]


def an(q, platform="unified", allowed=None):
    return cr.analyze(q, CAT, platform=platform, allowed_modules=allowed)


# ── pod çözümleme ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q,filt", [
    ("Kaç pod var?", "all"),
    ("OpenShift'te kaç pod var?", "all"),
    ("OpenShift'te toplam kaç pod var?", "all"),
    ("Pod sayısı kaç?", "all"),
    ("Kaç hatalı pod var?", "faulty"),
    ("OpenShift'te hatalı pod sayısı kaç?", "faulty"),
    ("Kaç sorunlu pod var?", "faulty"),
    ("Hata veren kaç pod var?", "faulty"),
    ("OpenShift'te kaç pod CrashLoopBackOff durumunda?", "reason:CrashLoopBackOff"),
    ("Kaç pod ImagePullBackOff durumunda?", "reason:ImagePullBackOff"),
    ("Kaç pod Error durumunda?", "reason:Error"),
    ("Kaç pod Pending?", "status:pending"),
    ("Kaç bekleyen pod var?", "status:pending"),
    ("Kaç çalışan pod var?", "status:running"),
    ("How many pods are running?", "status:running"),
    ("Kaç pod'lar tamamlanmış durumda?", "status:succeeded"),
])
def test_pod_plan(q, filt):
    p = an(q)
    assert p is not None and p.topic == "pod" and p.domain == "ocp", q
    assert p.pod_filter == filt


def test_pod_cluster_scope_by_name():
    p = an("oVirt'te kaç pod var?")
    assert p.topic == "pod" and p.ocp_scope.ocp_ids == [2]
    p = an("ZZ-FAKE-OCP cluster'ında kaç hatalı pod var?")
    assert p.ocp_scope.ocp_ids == [3] and p.pod_filter == "faulty"


@pytest.mark.parametrize("q", [
    "En çok restart eden pod hangisi?", "Kaç pod restart etti?", "Son 1 saatte kaç pod çöktü?",
    "Hangi pod'lar hatalı?", "Hatalı podları listele", "Kaç pod hem Error hem Pending?",
    "Kaç pod 5 kez restart etti?", "Kaç pod kapalı?", "openshift-monitoring namespace'inde kaç pod var?",
    "Kaç pod ve kaç node var?", "Kaç pod CPU kullanıyor?", "Dün kaç pod hatalıydı?",
    "Kaç pod var, kaçı hatalı?",
])
def test_pod_not_rule(q):
    assert an(q) is None, q


def test_pod_rbac():
    assert an("Kaç pod var?", "unified", {"virt"}) is None
    assert an("Kaç pod var?", "virt") is None
    assert an("Kaç pod var?", "linux") is None
    assert an("Kaç pod var?", "openshift") is not None
    assert an("Kaç pod var?", "unified", {"openshift"}) is not None


# ── pod sınıflandırma (araçla ortak) ──────────────────────────────────────────────

def test_is_problem_matches_tool_definition():
    assert not ps.is_problem("Running", "", 0)
    assert not ps.is_problem("Succeeded", "Completed", 0)
    assert ps.is_problem("Running", "PodInitializing", 0)
    assert ps.is_problem("Pending", "", 0)
    assert ps.is_problem("Running", "", 5)
    assert not ps.is_problem("Running", "", 4)


def test_summarize_breakdown():
    pods = [{"status": "Running"}, {"status": "CrashLoopBackOff", "reason": "CrashLoopBackOff", "restart_count": 9},
            {"status": "Error", "reason": "Error"}, {"status": "Running", "restart_count": 7}]
    s = ps.summarize(pods)
    assert s["total"] == 4 and s["problem_count"] == 3
    assert s["by_reason"]["CrashLoopBackOff"] == 1 and s["by_reason"]["Error"] == 1
    assert s["by_reason"]["5+ restart (Running)"] == 1
    assert "Hatalı pod tanımı" in s["problem_definition"]


# ── pod yerleşim ──────────────────────────────────────────────────────────────────

def _render(q):
    return cx.render_pods(an(q), CAT, GROUPS, SYNCS, NOW, 1800)


def test_render_total_excludes_stale_cluster():
    t = _render("Kaç pod var?")
    assert t.startswith("**Toplam pod: 335**")
    assert "ZZ-FAKE-OCP" in t and "toplama katılmadı" in t and "500 pod" in t
    assert "Hatalı pod: **28**" in t
    assert "Hatalı pod tanımı" in t


def test_render_faulty_with_reasons():
    t = _render("Kaç hatalı pod var?")
    assert t.startswith("**Hatalı pod: 28** (kapsamdaki toplam 335 pod içinde)")
    assert "| Error | 10 |" in t and "| CrashLoopBackOff | 2 |" in t and "| RunContainerError | 7 |" in t
    assert "| 5+ restart (Running) | 3 |" in t
    assert "| OpenShift cluster | Hatalı | Toplam pod | Son senkron |" in t


def test_render_crashloop_count():
    t = _render("OpenShift'te kaç pod CrashLoopBackOff durumunda?")
    assert t.startswith("**CrashLoopBackOff durumundaki pod: 2**")


def test_render_single_fresh_cluster():
    t = cx.render_pods(an("oVirt'te kaç pod var?"), CAT, GROUPS, SYNCS, NOW, 1800)
    assert t.startswith("**Toplam pod: 335**") and "OpenShift cluster: oVirt" in t and "ZZ-FAKE" not in t


def test_render_all_stale():
    t = cx.render_pods(an("ZZ-FAKE-OCP cluster'ında kaç pod var?"), CAT, GROUPS, SYNCS, NOW, 1800)
    assert "güncel sayı bilinmiyor" in t and "443" not in t.split("\n")[0]


def test_split_clusters_naive_ts_and_missing():
    f, s = cx.split_clusters({2: datetime(2026, 10, 21, 11, 55), 3: None}, [2, 3], NOW, 1800)
    assert f == [2] and s == [3]


# ── sunucu ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("q,kinds", [
    ("Kaç Linux sunucum var?", ("linux",)),
    ("Kaç Linux sunucu var?", ("linux",)),
    ("Linux sunucu sayısı kaç?", ("linux",)),
    ("Kaç Windows sunucu var?", ("windows",)),
    ("Windows sunucu sayısı nedir?", ("windows",)),
    ("Kaç sunucu var?", ("linux", "windows")),
    ("How many servers are there?", ("linux", "windows")),
    ("How many Linux servers do we have?", ("linux",)),
])
def test_server_plan(q, kinds):
    p = an(q)
    assert p is not None and p.topic == "server" and p.os_kinds == kinds, q


@pytest.mark.parametrize("q", [
    "Kaç sunucuda CPU yüksek?", "Kaç Linux sunucu kapalı?", "Hangi sunucular Linux?",
    "Kaç sunucu son 1 günde eklendi?", "Kaç Linux sunucu ve kaç VM var?", "Kaç sunucuda patch eksik?",
    "Kaç RHEL sunucu var?", "Sunucu listesini göster",
])
def test_server_not_rule(q):
    assert an(q) is None, q


def test_server_rbac():
    assert an("Kaç Linux sunucum var?", "unified", {"virt"}) is None
    assert an("Kaç Windows sunucu var?", "unified", {"linux"}) is None
    assert an("Kaç sunucu var?", "unified", {"linux"}).os_kinds == ("linux",)
    assert an("Kaç sunucu var?", "linux").os_kinds == ("linux",)
    assert an("Kaç sunucu var?", "windows").os_kinds == ("windows",)
    assert an("Kaç Linux sunucum var?", "virt") is None
    assert an("Kaç Linux sunucum var?", "openshift") is None


def test_render_servers():
    p = an("Kaç sunucu var?")
    t = cx.render_servers(p, {"linux": {"total": 1068, "vm": 1068, "physical": 0, "os_unknown": 23},
                              "windows": {"total": 484, "vm": 484, "physical": 0, "os_unknown": 0}}, None)
    assert "Linux **1068**" in t and "Windows **484**" in t
    assert "Linux modülü envanteri" in t and "İşletim sistemi bilgisi boş/diğer: **23** kayıt (bu toplamın içinde)" in t
    p1 = an("Kaç Linux sunucum var?")
    t1 = cx.render_servers(p1, {"linux": {"total": 1068, "vm": 1060, "physical": 8, "os_unknown": 0}}, None)
    assert t1.startswith("**Linux sunucu: 1068**") and "fiziksel **8**" in t1


def test_existing_topics_unchanged():
    assert an("Kaç VM var?").topic == "vm"
    assert an("OpenShift'te kaç node var?").topic == "node"
    assert an("Kaç job çalışıyor?") is None
