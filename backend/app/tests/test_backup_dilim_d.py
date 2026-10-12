"""Dilim D: Veeam REST istemcisi (salt-okunur), doküman-örneği contract testleri, demo provider,
eşleştirme, RPO motoru, devre kesici, Veeam'siz kabul."""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timedelta, timezone

import pytest

from app.services.backup import matching, rpo_engine as eng
from app.services.backup.veeam_client import VeeamApiError, VeeamRestClient, paged
from app.services.backup.veeam_provider import (
    DemoTransport, VeeamDemoProvider, collect_snapshot, job_kind, parse_ts,
)
from app.services.findings.registry import (
    RESULT_FAIL, RESULT_NOT_APPLICABLE, RESULT_NOT_MEASURABLE, RESULT_PASS,
)

FIX = json.loads((pathlib.Path(__file__).parent / "fixtures" / "veeam" / "vbr_1_3_rev1_doc_examples.json").read_text())


class _DocTransport:
    """Doküman örneği yanıtlarını (GERÇEK VBR DEĞİL) endpoint anahtarına göre döndürür."""
    MAP = {"server_info": "serverInfo", "jobs_states": "jobs_states", "repositories_states": "repositories_states",
           "sessions": "sessions", "backups": "backups", "backup_objects": "backup_objects",
           "restore_points": "restore_points"}

    def get_json(self, key, params=None):
        return FIX[self.MAP[key]]


# ── contract (doküman örneği fixture) ────────────────────────────────────────

def test_contract_collect_snapshot_from_doc_examples():
    snap = collect_snapshot(_DocTransport(), {}, now=datetime(2025, 7, 30, tzinfo=timezone.utc))
    assert snap["server"]["build"] == "13.0.0.4883"
    assert [j["name"] for j in snap["jobs"]] == ["Linux backup job", "PostgreSQL backup"]
    assert snap["jobs"][0]["last_result"] == "Success" and snap["jobs"][0]["enabled"] is True
    assert snap["repos"][1]["free_gb"] == 16.4
    assert snap["sessions"][0]["result"] == "Failed"
    # yalnız type=VM nesneler; Template dışarıda
    assert [o["name"] for o in snap["objects"]] == ["appsrv001"]
    # objectId UUID → moref sayılmaz (api_ref #1)
    assert snap["objects"][0]["object_ref"] is None
    assert len(snap["restore_points"]) == 3
    assert snap["backup_job"]["f3b0fbc5-01cf-4464-976a-4881e6eda067"] == "53b87378-7958-477d-8def-fbe6740d4b6f"
    assert snap["next_cursor"]["rp_after"].endswith("Z")


def test_parse_ts_variants():
    assert parse_ts("2023-12-04T06:13:34.983+01:00") == datetime(2023, 12, 4, 5, 13, 34, 983000, tzinfo=timezone.utc)
    assert parse_ts("2024-01-25T18:31:50.7300443+01:00") is not None   # 7 haneli kesir
    assert parse_ts("2024-11-11T12:54:32.649649").tzinfo is not None     # naive → UTC
    assert parse_ts("") is None and parse_ts("saçma") is None


def test_job_kind():
    assert job_kind("VSphereBackup") == "backup"
    assert job_kind("VSphereReplica") == "replica"
    assert job_kind("BackupCopy") == "copy"


# ── istemci: salt-okunur, header, sayfalama ──────────────────────────────────

class _Resp:
    def __init__(self, status=200, body=None):
        self.status_code, self._b = status, body if body is not None else {}

    def json(self):
        return self._b


class _Sess:
    def __init__(self, get_resps):
        self.posts, self.gets, self._g = [], [], list(get_resps)

    def post(self, url, data=None, headers=None, **kw):
        self.posts.append((url, data, headers))
        return _Resp(200, {"access_token": "T", "refresh_token": "R", "expires_in": 900})

    def get(self, url, params=None, headers=None, **kw):
        self.gets.append((url, params, headers))
        return self._g.pop(0)


def test_client_headers_and_readonly_guard():
    s = _Sess([_Resp(200, {"data": [], "pagination": {"total": 0}})])
    c = VeeamRestClient("https://vbr.local:9419", "u", "p", revision="1.3-rev1", session=s)
    c.get_json("jobs_states", {"limit": 1})
    url, form, h = s.posts[0]
    assert url == "https://vbr.local:9419/api/oauth2/token"
    assert form == {"grant_type": "password", "username": "u", "password": "p"}
    assert h["x-api-version"] == "1.3-rev1"
    gurl, params, gh = s.gets[0]
    assert gurl == "https://vbr.local:9419/api/v1/jobs/states" and gh["Authorization"] == "Bearer T"
    for bad in ("token", "logout", "olmayan"):
        with pytest.raises(VeeamApiError) as ei:
            c.get_json(bad)
        assert ei.value.kind == "readonly"


def test_client_rejects_unknown_revision_and_403():
    with pytest.raises(VeeamApiError):
        VeeamRestClient("h", "u", "p", revision="9.9-rev9")
    s = _Sess([_Resp(403)])
    c = VeeamRestClient("h", "u", "p", session=s)
    with pytest.raises(VeeamApiError) as ei:
        c.get_json("server_info")
    assert ei.value.kind == "forbidden"


def test_paged_follows_skip_limit():
    class T:
        calls = []

        def get_json(self, key, params=None):
            self.calls.append(dict(params))
            skip = params["skip"]
            rows = [{"i": i} for i in range(skip, min(skip + 200, 450))]
            return {"data": rows, "pagination": {"total": 450}}
    t = T()
    got = list(paged(t, "sessions"))
    assert len(got) == 450 and [c["skip"] for c in t.calls] == [0, 200, 400]


# ── eşleştirme ───────────────────────────────────────────────────────────────

VMS = [{"id": 1, "name": "web01", "ref": "vm-10", "cluster": "C1", "powered_on": True},
       {"id": 2, "name": "db01.corp.local", "ref": "vm-11", "cluster": "C1", "powered_on": True},
       {"id": 3, "name": "dup", "ref": "vm-12", "cluster": "C2", "powered_on": True},
       {"id": 4, "name": "dup", "ref": "vm-99", "cluster": "C3", "powered_on": True}]


def test_matching_levels():
    r = {o["name"]: (sid, m, c) for o, sid, m, c in matching.match_all([
        {"name": "web01", "object_ref": "vm-10"},      # moref + ad → exact
        {"name": "web01", "object_ref": None},          # ad → high
        {"name": "renamed", "object_ref": "vm-11"},     # moref → high
        {"name": "WEB01", "object_ref": None},          # ci → low
        {"name": "db01", "object_ref": None},           # kısa ad → low
        {"name": "dup", "object_ref": None},            # belirsiz → none
        {"name": "ghost", "object_ref": None},
    ], VMS)}
    assert r["renamed"][2] == "high" and r["WEB01"][2] == "low" and r["db01"][2] == "low"
    assert r["dup"][2] == "none" and r["dup"][1] == "ambiguous_name" and r["ghost"][2] == "none"
    exact = [c for o, s, m, c in matching.match_all([{"name": "web01", "object_ref": "vm-10"}], VMS)]
    assert exact == ["exact"]


# ── demo provider + sync + RPO motoru (canlı DB; test verisi sonunda silinir) ─

def _skip_if_user_has_backup(db):
    from app.models.integration_instance import IntegrationInstance
    if db.query(IntegrationInstance).filter(IntegrationInstance.category == "backup").count():
        pytest.skip("Ortamda gerçek backup instance'ı var — canlı veriye dokunulmaz")


@pytest.fixture()
def db():
    from app.core.database import SessionLocal, Base, engine
    import app.models  # noqa: F401
    from app.services.findings.schema_ensure import ensure_backup_columns
    Base.metadata.create_all(bind=engine)
    ensure_backup_columns(engine)
    s = SessionLocal()
    _skip_if_user_has_backup(s)
    yield s
    from app.models.backup import BkRpoPolicy
    from app.models.integration_instance import IntegrationInstance
    s.rollback()
    s.query(BkRpoPolicy).filter(BkRpoPolicy.label == "_t").delete()
    s.query(IntegrationInstance).filter(IntegrationInstance.label == "_t_demo").delete()
    s.commit()
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()
    s.close()


def _demo_vms(n=40):
    return [{"id": 1000 + i, "name": f"demo-vm-{i:03d}", "ref": f"vm-{2000 + i}", "cluster": "C1" if i % 2 else "C2",
             "powered_on": True} for i in range(n)]


def _make_instance(db, **kw):
    from app.models.integration_instance import IntegrationInstance
    row = IntegrationInstance(category="backup", kind="veeam_demo", label="_t_demo", endpoint="demo", enabled=True,
                              last_status="never", sync_interval_sec=3600, **kw)
    db.add(row)
    db.commit()
    return row


def test_demo_sync_rpo_and_findings(db, monkeypatch):
    from app.models.backup import BkRpoPolicy
    from app.services.backup import sync as bsync
    vms = _demo_vms()
    monkeypatch.setattr(bsync, "_vms", lambda _db: vms)
    row = _make_instance(db)
    res = bsync.sync_instance(db, row, force=True, provider=VeeamDemoProvider(row, vms=vms))
    assert res["ok"] is True and res["counts"]["objects"] > 0
    db.refresh(row)
    assert row.last_status == "ok" and row.last_sync_at is not None

    rows = eng.vm_protection(db, vms=vms)
    states = {r["state"] for r in rows}
    assert "protected" in states and "unprotected" in states
    # hedef yok → hiçbir RPO ihlali yok, no_target
    prot = [r for r in rows if r["state"] == "protected"]
    assert prot and all(r["rpo_state"] == "no_target" for r in prot)
    f0 = eng.backup_findings(db, vms=vms)
    rpo0 = [f for f in f0 if f.check_id == "bk.vm.rpo_breach"]
    assert rpo0 and all(f.result == RESULT_NOT_APPLICABLE for f in rpo0)

    # hedef (3 saat) → demo'da yaşı > 180 dk olanlar ihlal
    db.add(BkRpoPolicy(scope_kind="all", scope_ref="", target_rpo_min=180, label="_t"))
    db.commit()
    rows = eng.vm_protection(db, vms=vms)
    prot = [r for r in rows if r["state"] == "protected"]
    ok = [r for r in prot if r["rpo_state"] == "ok"]
    breach = [r for r in prot if r["rpo_state"] == "breach"]
    assert breach and ok, "demo verisi hem uyumlu hem ihlalli VM üretmeli"
    assert all(r["rpo_age_min"] > 180 for r in breach) and all(r["rpo_age_min"] <= 180 for r in ok)
    f1 = eng.backup_findings(db, vms=vms)
    by = {}
    for f in f1:
        by.setdefault(f.check_id, []).append(f)
    assert any(f.result == RESULT_FAIL for f in by["bk.vm.unprotected"])
    assert any(f.result == RESULT_FAIL for f in by["bk.vm.rpo_breach"])
    assert any(f.result == RESULT_FAIL for f in by["bk.job.failed_recent"])      # DEMO Weekly DB
    assert any(f.result == RESULT_FAIL for f in by["bk.repo.capacity"])          # DEMO Repo A %91
    assert all(f.result in (RESULT_PASS,) for f in by["bk.provider.sync_failed"])
    # RTO tahmin edilmez: motorda RTO hesabı yok, yalnız hedef saklanır
    assert all("rto" not in str(f.evidence).lower() for f in by["bk.vm.rpo_breach"])


def test_stale_provider_makes_vm_results_not_measurable(db, monkeypatch):
    from app.models.backup import BkRpoPolicy
    from app.services.backup import sync as bsync
    vms = _demo_vms(10)
    monkeypatch.setattr(bsync, "_vms", lambda _db: vms)
    row = _make_instance(db)
    bsync.sync_instance(db, row, force=True, provider=VeeamDemoProvider(row, vms=vms))
    db.add(BkRpoPolicy(scope_kind="all", scope_ref="", target_rpo_min=60, label="_t"))
    row.last_sync_at = datetime.now(timezone.utc) - timedelta(hours=5)   # > 2×1sa
    db.commit()
    fs = eng.backup_findings(db, vms=vms)
    rpo = [f for f in fs if f.check_id == "bk.vm.rpo_breach"]
    assert rpo and all(f.result == RESULT_NOT_MEASURABLE and f.stale for f in rpo)
    st = [f for f in fs if f.check_id == "bk.provider.stale"]
    assert st and st[0].result == RESULT_FAIL


def test_circuit_breaker_and_capability_retention(db, monkeypatch):
    from app.services.backup import sync as bsync
    from app.services.capabilities import get_capabilities
    row = _make_instance(db)
    vms = _demo_vms(5)
    monkeypatch.setattr(bsync, "_vms", lambda _db: vms)
    assert bsync.sync_instance(db, row, force=True, provider=VeeamDemoProvider(row, vms=vms))["ok"]
    assert "backup" in get_capabilities(force_refresh=True)

    class Boom:
        def sync(self, cur):
            raise VeeamApiError("network", "bağlantı yok")
    for _ in range(3):
        r = bsync.sync_instance(db, row, force=True, provider=Boom())
        assert r["ok"] is False
    db.refresh(row)
    assert row.last_status == "error" and "bağlantı yok" in (row.last_error or "")
    # geçici hata: daha önce başarılı olduğu için capability düşmez (veri bayat işaretlenir)
    assert "backup" in get_capabilities(force_refresh=True)
    r = bsync.sync_instance(db, row, provider=Boom())          # force yok → devre kesici açık
    assert r.get("skipped") == "circuit_open"
    fs = eng.backup_findings(db, vms=vms)
    assert any(f.check_id == "bk.provider.sync_failed" and f.result == RESULT_FAIL for f in fs)


def test_auth_failure_never_enables_capability(db):
    from app.services.backup import sync as bsync
    from app.services.capabilities import get_capabilities
    row = _make_instance(db)

    class Deny:
        def sync(self, cur):
            raise VeeamApiError("auth", "reddedildi", 401)
    r = bsync.sync_instance(db, row, force=True, provider=Deny())
    db.refresh(row)
    assert r["ok"] is False and row.last_status == "auth_failed" and row.last_sync_at is None
    assert "backup" not in get_capabilities(force_refresh=True)


# ── Veeam'siz kabul ──────────────────────────────────────────────────────────

def test_veeam_less_environment_is_unchanged(db):
    from app.api import backup_insights
    from app.services.agent.tools import tool_specs, tool_specs_read_only
    from app.services.backup.sync import has_enabled_backup_instance
    from app.services.capabilities import capabilities_payload, invalidate_capabilities
    invalidate_capabilities()
    assert capabilities_payload()["has_backup"] is False
    assert has_enabled_backup_instance() is False           # fleet.backup_sync iş üretmez
    assert eng.backup_findings(db) == []                      # hiçbir bulgu üretilmez
    assert backup_insights.backup_summary(db=db, _u=None) == {"enabled": False}
    with pytest.raises(Exception):
        backup_insights.backup_jobs(db=db, _u=None)
    names = {s["function"]["name"] for s in tool_specs_read_only(domains=frozenset({"vcenter"}))}
    names |= {s["function"]["name"] for s in tool_specs()}
    assert "virt_backup_status" not in names and "virt_rpo_compliance" not in names


def test_backup_tools_visible_only_with_capability(db, monkeypatch):
    from app.services.agent.tools import TOOLS, tool_specs_read_only
    from app.services.backup import sync as bsync
    vms = _demo_vms(5)
    monkeypatch.setattr(bsync, "_vms", lambda _db: vms)
    row = _make_instance(db)
    bsync.sync_instance(db, row, force=True, provider=VeeamDemoProvider(row, vms=vms))
    names = {s["function"]["name"] for s in tool_specs_read_only(domains=frozenset({"vcenter"}))}
    assert {"virt_backup_status", "virt_rpo_compliance"} <= names
    for n in ("virt_backup_status", "virt_rpo_compliance"):
        t = TOOLS[n]
        assert t.risk_level.name == "READ_ONLY" and t.requires_capability == frozenset({"backup"})
    out = TOOLS["virt_rpo_compliance"].direct_handler(db, {"filter": "unprotected"}, {})
    assert out["ok"] and out["demo"] is True


def test_credentials_never_returned(db):
    from app.api.backup_integrations import InstanceBody, _apply, _dict
    from app.models.integration_instance import IntegrationInstance
    row = IntegrationInstance(category="backup", kind="veeam_vbr", enabled=False)
    _apply(row, InstanceBody(kind="veeam_vbr", label="_t_demo", endpoint="vbr.local", username="svc",
                             password="S3cret!"))
    assert "S3cret!" not in (row.credential_ref or "")          # mühürlü
    d = _dict(row)
    assert d["has_credentials"] is True and d["username"] == "svc"
    assert "S3cret!" not in json.dumps(d) and "password" not in d
    # parola boş bırakılınca mevcut korunur
    _apply(row, InstanceBody(kind="veeam_vbr", label="_t_demo", endpoint="vbr.local", username="svc", password=""))
    from app.core.encryption import decrypt_secret
    assert json.loads(decrypt_secret(row.credential_ref))["password"] == "S3cret!"


def test_demo_transport_shapes_match_documented_fields():
    t = DemoTransport(_demo_vms(10))
    for key, fields in (("jobs_states", ("id", "name", "type", "status", "lastResult")),
                        ("repositories_states", ("id", "name", "capacityGB", "freeGB", "isOnline")),
                        ("restore_points", ("name", "creationTime", "backupId", "platformName"))):
        row = t.get_json(key)["data"][0]
        assert all(f in row for f in fields), key


def test_snapshot_guard_blocks_only_vm_with_running_job_session(db, monkeypatch):
    from app.models.backup import BkJob, BkProtectedObject, BkSession
    from app.services.backup import sync as bsync
    from app.services.backup.snapshot_guard import check_snapshot_remove
    vms = _demo_vms(10)
    monkeypatch.setattr(bsync, "_vms", lambda _db: vms)
    row = _make_instance(db)
    bsync.sync_instance(db, row, force=True, provider=VeeamDemoProvider(row, vms=vms))
    obj = (db.query(BkProtectedObject).filter(BkProtectedObject.instance_id == row.id,
                                              BkProtectedObject.job_provider_id.isnot(None)).first())
    assert obj is not None and obj.matched_vm_id
    other = (db.query(BkProtectedObject).filter(BkProtectedObject.instance_id == row.id,
                                                BkProtectedObject.job_provider_id != obj.job_provider_id).first())
    job = db.query(BkJob).filter(BkJob.instance_id == row.id, BkJob.provider_job_id == obj.job_provider_id).one()
    db.add(BkSession(job_id=job.id, provider_session_id="running-1", started_at=datetime.now(timezone.utc),
                     ended_at=None, result="None"))
    db.commit()
    snaps = [{"name": "manual-before-patch"}]
    r = check_snapshot_remove(db, snapshots=snaps, vm_name=obj.name, matched_vm_id=obj.matched_vm_id)
    assert r["ok"] is False and r["reason"] == "active_backup_session"
    if other is not None and other.matched_vm_id:
        r2 = check_snapshot_remove(db, snapshots=snaps, vm_name=other.name, matched_vm_id=other.matched_vm_id)
        assert r2["ok"] is True
