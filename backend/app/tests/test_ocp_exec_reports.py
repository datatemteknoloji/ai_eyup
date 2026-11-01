"""OpenShift hazır raporları + MTV geçmişi + Yönetici «Tüm Ortamlar» raporları.

Saf kurallar (matris bütünlüğü, parse_plan, sentetik dışlama, şema) izole geçici DB'de koşar.
"""
from __future__ import annotations

from datetime import datetime, timezone

from app.models.event import SystemEvent
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.mtv import MtvPlanSnapshot
from app.models.openshift import OpenShiftCluster
from app.services import exec_catalog_reports as ex
from app.services import generic_report as gr
from app.services import method_registry as mr
from app.services import ocp_report_engine as oe
from app.services import report_method_notes as rmn
from app.services.openshift import mtv_history as mh


# ── Yönetici kapsam matrisi ──────────────────────────────────────────────────

def test_matrix_covers_every_report_and_module():
    assert set(ex.MATRIX) == set(ex.CATALOG) == set(ex.REPORT_TITLES) == set(ex.GENERATORS)
    for rt, row in ex.MATRIX.items():
        assert set(row) == set(ex.ORDER), rt
        for m, v in row.items():
            if isinstance(v, tuple):
                assert v[0] == "excluded" and len(v[1]) > 20, (rt, m)   # neden zorunlu
            else:
                assert v in ex._PROVIDERS, (rt, m, v)


def test_matrix_encodes_the_user_scope_decisions():
    # Kapasite tahmini: Windows ve Exadata anlamsız → kapsam dışı + neden
    fc = ex.applicability("forecast")
    assert fc["windows"]["included"] is False and fc["windows"]["reason"]
    assert fc["exadata"]["included"] is False and fc["exadata"]["reason"]
    assert all(fc[m]["included"] for m in ("virt", "openshift", "linux"))
    # MTV yalnız Sanallaştırma + OpenShift
    mig = ex.applicability("migration")
    assert [m for m, v in mig.items() if v["included"]] == ["virt", "openshift"]
    # Özet/risk/izleme hepsini kapsar
    for rt in ("executive_summary", "risk", "riskiest_assets", "monitoring_coverage"):
        assert all(v["included"] for v in ex.applicability(rt).values()), rt
    # Yedek (Veeam) kapsamda değil
    assert not any("backup" in t or "veeam" in t for t in ex.CATALOG)


def test_method_notes_registered_for_new_scopes():
    for t in ex.CATALOG:
        for mid in rmn.method_ids_for("executive", t):
            assert mr.resolve(mid), (t, mid)
    for t in oe.CATALOG:
        for mid in rmn.method_ids_for("openshift", t):
            assert mr.resolve(mid), (t, mid)
    for mid in ("report.mtv.history", "report.mtv.readiness", "report.exec.health", "report.exec.matrix"):
        m = mr.resolve(mid)
        assert m and m.method_tr and m.method_en and m.limits_tr and m.limits_en and not m.uses_ai


def test_report_titles_and_catalogs_are_consistent():
    assert set(oe.CATALOG) == set(oe.REPORT_TITLES) == set(oe.GENERATORS)
    assert "mtv_migration" in oe.CATALOG and "mtv_readiness" in oe.CATALOG
    assert len(oe.CATALOG) == 14


# ── Genel şema ───────────────────────────────────────────────────────────────

def test_generic_markdown_marks_unmeasured_and_excluded():
    data = gr.make_report(
        "executive", "forecast", "T",
        kpis=[gr.kpi("A", 3)],
        sections=[gr.unmeasured("Süre", "14 günden kısa seri", module="Linux"),
                  gr.table("Tablo", ["x", "y"], [[1, None]], module="OpenShift")],
        excluded=[{"module": "Windows", "reason": "Seri yok"}],
        recommendations=["Bir şey yap"],
    )
    assert data["view"] == "generic"
    md = gr.to_markdown(data, scope="executive", report_type="forecast")
    assert "Ölçülemedi: 14 günden kısa seri" in md
    assert "Kapsam dışı" in md and "Windows" in md and "Seri yok" in md
    assert "| 1 | — |" in md
    assert "## Yöntem notları" in md


def test_ocp_forecast_projection_clamped():
    assert oe._project(None, 1.0, 90) is None
    assert oe._project(80.0, 1.0, 90) == 100.0
    assert oe._project(10.0, -1.0, 90) == 0.0
    assert oe._project(50.0, 0.1, 30) == 53.0


# ── MTV: parse_plan ──────────────────────────────────────────────────────────

def _plan(conds=None, vms=None, spec_vms=2, archived=False):
    return {
        "metadata": {"name": "p1", "uid": "u-1", "namespace": "openshift-mtv"},
        "spec": {"vms": [{}] * spec_vms, "archived": archived, "warm": True, "targetNamespace": "t",
                 "provider": {"source": {"name": "vc1"}}},
        "status": {"conditions": [{"type": c, "status": "True", "category": "Critical" if c == "Failed" else "Advisory",
                                   "message": "m"} for c in (conds or [])],
                   "migration": {"started": "2026-10-01T10:00:00Z", "vms": vms or []}},
    }


def _vm(name, ok=False, bad=False, done=None):
    conds = []
    if ok:
        conds.append({"type": "Succeeded", "status": "True"})
    if bad:
        conds.append({"type": "Failed", "status": "True"})
    return {"name": name, "phase": "Completed", "conditions": conds, "completed": done,
            "error": {"reasons": ["disk hatası"]} if bad else None}


def test_parse_plan_states():
    ok = mh.parse_plan(_plan(["Succeeded"], [_vm("a", ok=True, done="2026-10-01T11:00:00Z"), _vm("b", ok=True, done="2026-10-01T12:00:00Z")]))
    assert ok["state"] == "succeeded" and ok["vm_succeeded"] == 2 and ok["vm_total"] == 2
    assert ok["warm"] is True and ok["source_provider"] == "vc1"
    assert ok["completed_at"] == datetime(2026, 10, 1, 12, 0, tzinfo=timezone.utc)

    bad = mh.parse_plan(_plan(["Failed"], [_vm("a", ok=True), _vm("b", bad=True)]))
    assert bad["state"] == "failed" and bad["vm_failed"] == 1
    assert "disk hatası" in [v for v in bad["vms"] if v["result"] == "failed"][0]["error"]

    assert mh.parse_plan(_plan(["Executing"], [_vm("a")]))["state"] == "running"
    assert mh.parse_plan(_plan(["Ready"]))["state"] == "ready"
    assert mh.parse_plan(_plan([]))["state"] == "validating"
    assert mh.parse_plan(_plan(["Succeeded"], archived=True))["state"] == "archived"
    # Koşul yazılmadan VM sonuçlarından türet
    assert mh.parse_plan(_plan(["Ready"], [_vm("a", ok=True), _vm("b", ok=True)]))["state"] == "succeeded"


def test_parse_plan_uid_fallback_and_empty():
    p = {"metadata": {"name": "x"}, "spec": {}, "status": {}}
    out = mh.parse_plan(p)
    assert out["plan_uid"] == "name:x" and out["vm_total"] == 0 and out["state"] == "validating"


# ── MTV: kalıcılık (izole DB) ────────────────────────────────────────────────

def _cluster(db, name="oVirt"):
    c = OpenShiftCluster(name=name, api_url="https://x:6443")
    db.add(c)
    db.commit()
    return c


def test_upsert_never_deletes_and_marks_removed(isolated_db):
    db = isolated_db
    c = _cluster(db)
    now = datetime(2026, 10, 1, tzinfo=timezone.utc)
    a = mh.parse_plan(_plan(["Executing"], [_vm("a")]))
    b = {**mh.parse_plan(_plan(["Succeeded"], [_vm("b", ok=True)])), "plan_uid": "u-2", "plan_name": "p2"}
    assert mh.upsert_snapshots(db, c, [a, b], now) == {"added": 2, "updated": 0, "removed": 0}
    # a tamamlanır, b kümeden silinir
    a2 = mh.parse_plan(_plan(["Succeeded"], [_vm("a", ok=True)]))
    assert mh.upsert_snapshots(db, c, [a2], now) == {"added": 0, "updated": 1, "removed": 1}
    rows = {r.plan_uid: r for r in db.query(MtvPlanSnapshot).all()}
    assert set(rows) == {"u-1", "u-2"}                      # satır silinmedi
    assert rows["u-1"].state == "succeeded" and rows["u-1"].removed_at is None
    assert rows["u-2"].removed_at is not None and rows["u-2"].state == "succeeded"
    # tekrar görününce kapanış kalkar
    mh.upsert_snapshots(db, c, [a2, b], now)
    assert db.query(MtvPlanSnapshot).filter(MtvPlanSnapshot.removed_at.isnot(None)).count() == 0


def test_unreachable_cluster_closes_nothing(isolated_db, monkeypatch):
    db = isolated_db
    c = _cluster(db)
    mh.upsert_snapshots(db, c, [mh.parse_plan(_plan(["Succeeded"], [_vm("a", ok=True)]))], datetime(2026, 10, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(mh, "fetch_cluster_plans", lambda cluster: None)      # Forklift API erişilemedi
    out = mh.sync_all_mtv_history(db)
    assert out["unavailable"] == 1
    assert db.query(MtvPlanSnapshot).filter(MtvPlanSnapshot.removed_at.isnot(None)).count() == 0


def test_sync_skips_synthetic_clusters(isolated_db, monkeypatch):
    db = isolated_db
    _cluster(db, "ZZ-FAKE-OCP")
    calls = []
    monkeypatch.setattr(mh, "fetch_cluster_plans", lambda cluster: calls.append(cluster.name) or [])
    assert mh.sync_all_mtv_history(db)["clusters"] == 0 and not calls


# ── Sentetik dışlama ─────────────────────────────────────────────────────────

def _hv(db, name):
    h = Hypervisor(name=name, hypervisor_type=HypervisorType.VMWARE, hostname=name, ip_address="10.0.0.1")
    db.add(h)
    db.commit()
    return h


def _ev(db, title, raw, sev="critical", source="virt_resource"):
    db.add(SystemEvent(event_type="x", severity=sev, title=title, source=source, raw_data=raw, resolved=False))


def test_executive_events_exclude_synthetic_even_without_hypervisor_id(isolated_db):
    db = isolated_db
    real, fake = _hv(db, "vc-real"), _hv(db, "ZZ-FAKE-vc")
    base = {"platform": "virt"}
    _ev(db, "gerçek", {**base, "hypervisor_id": real.id, "host_name": "esx1", "external_key": f"host-{real.id}-esx1-cpu"})
    _ev(db, "sahte-1", {**base, "hypervisor_id": fake.id, "host_name": "fake-esx-1.invalid", "external_key": f"host-{fake.id}-fake-esx-1.invalid-cpu"})
    # canlı veride görülen biçim: hypervisor_id boş, yalnız external_key `res-<id>-…`
    _ev(db, "sahte-2", {**base, "hypervisor_id": None, "host_name": "fake-esx-2.invalid", "external_key": f"res-{fake.id}-fake-esx-2.invalid-memory"})
    db.commit()
    ctx = ex.Ctx(db)
    titles = {t for (t,) in ctx.event_q("virt").with_entities(SystemEvent.title).all()}
    assert titles == {"gerçek"}
    a = ctx.area("virt")
    assert [e["name"] for e in a["entities"]] == ["esx1"]


def test_entity_key_groups_by_host_not_by_title():
    k1 = ex._ekey(None, {"host_name": "esx1", "hypervisor_id": 3}, "CPU doluluk %90")
    k2 = ex._ekey(None, {"host_name": "esx1", "hypervisor_id": None}, "RAM doluluk %80")
    k3 = ex._ekey(None, {"host_name": "esx2"}, "CPU doluluk %90")
    assert k1 == k2 != k3
    assert ex._ekey(7, {}, "x") == "s7"
    assert ex._ekey(None, {"cluster_id": 2, "source_object": "Pod/a"}, "t") == "c2:Pod/a"


def test_area_without_inventory_is_not_scored(isolated_db):
    a = ex.Ctx(isolated_db).area("exadata")
    assert a["monitored"] is False and a["score"] is None and a["status"] == "İzleme yok"


def test_unknown_report_type_rejected(isolated_db):
    import pytest
    with pytest.raises(ValueError):
        ex.generate(isolated_db, "yok_boyle", save=False)
    with pytest.raises(ValueError):
        oe.generate(isolated_db, "yok_boyle", save=False)


# ── Sentetik kapsam: kalan sızıntılar ───────────────────────────────────────

def test_hwdemo_servers_are_synthetic_by_name():
    from app.services.synthetic_scope import name_is_synthetic

    assert name_is_synthetic("zz-hwdemo-win-01") and name_is_synthetic("ZZ-HWDEMO-lnx-02")
    assert name_is_synthetic("ZZ-FAKE-vc")
    assert not name_is_synthetic("hwdemo-prod") and not name_is_synthetic("web-01")


def test_exec_facts_excludes_events_by_external_key_when_hypervisor_id_missing():
    from app.models.event import SystemEvent
    from app.services import exec_facts as ef

    ev = SystemEvent(raw_data={"external_key": "res-10-vm-123"})
    assert ef._exclude_event(ev, set(), set(), {10}) is True
    ev2 = SystemEvent(raw_data={"external_key": "host-10-esx1"})
    assert ef._exclude_event(ev2, set(), set(), {10}) is True
    # farklı hypervisor / anahtar yok / sentetik küme boş → dışlanmaz
    assert ef._exclude_event(SystemEvent(raw_data={"external_key": "res-11-vm-1"}), set(), set(), {10}) is False
    assert ef._exclude_event(SystemEvent(raw_data={}), set(), set(), {10}) is False
    assert ef._exclude_event(ev, set(), set(), set()) is False
