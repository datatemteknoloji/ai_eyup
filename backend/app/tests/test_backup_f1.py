"""F.1: Veeam iş yapılandırması, proxy, restore point, yetki ve eşleşme anahtarı (doküman-örneği contract)."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from app.services.backup import matching, sync as bsync
from app.services.backup.veeam_api_ref import ENDPOINTS, ENDPOINT_ROLE_ROWS, viewer_closed_keys
from app.services.backup.veeam_cfg import (
    host_from_backup_object_path, host_matches, normalize_host, parse_job_config, tri,
)
from app.services.backup.veeam_client import VeeamApiError, VeeamRestClient
from app.services.backup.veeam_provider import VeeamDemoProvider, collect_snapshot
from app.tests.test_backup_dilim_d import FIX, _DocTransport, _demo_vms, _make_instance, db  # noqa: F401
from app.services.findings.registry import RESULT_FAIL, RESULT_NOT_APPLICABLE, RESULT_NOT_MEASURABLE, RESULT_PASS

NOW = datetime(2025, 7, 30, tzinfo=timezone.utc)


def test_job_config_from_doc_example_fields():
    snap = collect_snapshot(_DocTransport(), {}, now=NOW)
    c1 = snap["job_config"]["e35ef047-8cfa-4c3e-979e-de2e5399142f"]
    assert c1["encryption"] is False and c1["cbt"] is True and c1["app_aware"] is False
    assert (c1["retention_type"], c1["retention_quantity"]) == ("Days", 7)
    assert c1["gfs_enabled"] is False and c1["backup_health"] is False
    assert (c1["retry_enabled"], c1["retry_count"], c1["retry_wait_min"]) == (True, 3, 10)
    assert c1["window_enabled"] is False and c1["schedule_summary"] == "Günlük 10:00"
    assert c1["proxy_auto"] is True
    assert c1["vms"][0]["host"] == "vcenter01.tech.local" and c1["vms"][0]["object_id"] is None
    c2 = snap["job_config"]["508ae9cb-cc94-4705-8dda-5522a9ed60da"]
    assert c2["encryption"] is True and c2["cbt"] is False and c2["app_aware"] is True
    assert c2["gfs_enabled"] is True and c2["gfs"] == {"weekly": 4}
    assert c2["retry_enabled"] is False and c2["retry_count"] is None
    assert c2["vms"][0]["object_id"] == "vm-45006"


def test_missing_fields_are_none_not_false():
    c = parse_job_config({"id": "x", "type": "BackupCopy"})
    assert c["encryption"] is None and c["cbt"] is None and c["app_aware"] is None
    assert c["retention_quantity"] is None and c["gfs_enabled"] is None and c["retry_enabled"] is None
    assert tri("false") is None and tri(0) is None and tri(False) is False


def test_proxies_and_repository_types_from_doc():
    snap = collect_snapshot(_DocTransport(), {}, now=NOW)
    px = snap["proxies"][0]
    assert px["name"] == "VMware Backup Proxy" and px["is_online"] is True and px["is_out_of_date"] is False
    assert px["host_name"] == "This server" and px["transport_mode"] == "auto" and px["max_tasks"] == 2
    assert snap["repo_info"]["4e2a20fc-487d-44ed-a5a8-8058c62bc3a0"]["type"] == "LinuxLocal"


def test_endpoint_role_table_matches_doc():
    # "Available to" — Viewer yalnız serverInfo'da kapalı; yeni endpoint'ler Viewer'a açık (doküman 1.3-rev1)
    assert viewer_closed_keys() == ("server_info",)
    keys = {r[0] for r in ENDPOINT_ROLE_ROWS}
    assert {"jobs", "proxies_states", "proxies", "repositories", "object_restore_points"} <= keys
    assert all(ENDPOINTS[k].method == "GET" for k in keys if k not in ("token", "logout"))


def test_forbidden_extras_do_not_break_sync_and_are_marked():
    class T(_DocTransport):
        def get_json(self, key, params=None, **kw):
            if key in ("jobs", "proxies_states", "proxies"):
                raise VeeamApiError("forbidden", "403")
            return super().get_json(key, params, **kw)
    snap = collect_snapshot(T(), {}, now=NOW)
    assert snap["access"]["jobs"] == "forbidden" and snap["job_config"] == {}
    assert any("yetki" in w for w in snap["warnings"])
    assert len(snap["jobs"]) == 2    # ana okumalar etkilenmez


def test_auth_error_in_extras_is_not_swallowed():
    class T(_DocTransport):
        def get_json(self, key, params=None, **kw):
            if key == "jobs":
                raise VeeamApiError("auth", "401")
            return super().get_json(key, params, **kw)
    with pytest.raises(VeeamApiError):
        collect_snapshot(T(), {}, now=NOW)


def test_client_path_param_is_quoted_and_get_only():
    calls = []

    class R:
        status_code = 200

        def json(self):
            return {"data": [], "pagination": {"total": 0}}

    class S:
        def post(self, *a, **k):
            r = R()
            r.json = lambda: {"access_token": "t", "expires_in": 900}
            return r

        def get(self, url, **k):
            calls.append(url)
            return R()
    c = VeeamRestClient("h", "u", "p", session=S())
    c.get_json("object_restore_points", {"limit": 5}, path={"id": "a/b ../x"})
    assert calls[0].endswith("/api/v1/backupObjects/a%2Fb%20..%2Fx/restorePoints")
    with pytest.raises(VeeamApiError):
        c.get_json("object_restore_points")      # yol parametresi eksik


def test_object_restore_points_called_only_for_objects_missing_from_window_and_capped():
    calls = []

    class T(_DocTransport):
        def get_json(self, key, params=None, **kw):
            if key == "object_restore_points":
                calls.append(kw.get("path"))
            if key == "restore_points":
                return {"data": [], "pagination": {"total": 0}}      # pencerede hiç nokta yok
            return super().get_json(key, params, **kw)
    snap = collect_snapshot(T(), {}, now=NOW)
    assert len(calls) == 1 and calls[0] == {"id": "b74c6a02-e540-4a5c-8eac-e34550614b35"}
    assert list(snap["object_rps"].values())[0] == datetime(2025, 7, 29, 20, 1, 12, 123456, tzinfo=timezone.utc)
    # pencerede nokta bulunan nesne için çağrı yok (ek yük yok)
    calls.clear()
    collect_snapshot(_DocTransport(), {}, now=NOW)


# ── host normalizasyonu + eşleşme anahtarı ───────────────────────────────────

def test_host_normalization_and_matching():
    assert normalize_host("HTTPS://VC01.Tech.Local:443/") == "vc01.tech.local"
    assert normalize_host("vc01.tech.local.") == "vc01.tech.local"
    assert host_matches("vcenter01.tech.local", "VCENTER01") is True       # kısa ad
    assert host_matches("10.0.0.5", "10.0.0.5") is True
    assert host_matches("10.0.0.5", "10.0.0.50") is False                  # IP'de kısa ad kuralı yok
    assert host_from_backup_object_path("vcenter01.tech.local\\Prague\\Templates\\Manual\\win10_pro") == "vcenter01.tech.local"
    assert host_from_backup_object_path("noslash") is None


def test_host_only_narrows_never_rejects():
    vms = [{"id": 1, "name": "app", "ref": "vm-1", "vcenter_keys": ("vc-a.local",)},
           {"id": 2, "name": "app", "ref": "vm-1", "vcenter_keys": ("vc-b.local",)}]
    idx = matching.VmIndex(vms)
    # iki vCenter'da aynı ad + moref: host ile tekilleşir
    sid, method, conf = matching.match_object({"name": "app", "object_ref": "vm-1", "host_name": "vc-b.local"}, idx)
    assert (sid, conf) == (2, matching.CONF_EXACT) and method.endswith("+host")
    # host yok → belirsiz (eskisi gibi)
    assert matching.match_object({"name": "app", "object_ref": "vm-1"}, idx)[2] == matching.CONF_NONE
    # tek aday + uyuşmayan host → REDDEDİLMEZ (hostName sahada doğrulanmadı)
    idx1 = matching.VmIndex([vms[0]])
    sid, method, conf = matching.match_object({"name": "app", "object_ref": "vm-1", "host_name": "other.local"}, idx1)
    assert sid == 1 and conf == matching.CONF_EXACT and not method.endswith("+host")


# ── DB: upsert, bulgular, yetki durumu ───────────────────────────────────────

def _sync(db, monkeypatch, transport_cls=None):
    vms = _demo_vms(40)
    monkeypatch.setattr(bsync, "_vms", lambda _db: vms)
    row = _make_instance(db)
    prov = VeeamDemoProvider(row, vms=vms)
    if transport_cls is not None:
        prov._transport = lambda: transport_cls(vms)
    res = bsync.sync_instance(db, row, force=True, provider=prov)
    assert res["ok"] is True, res
    return row


def test_sync_writes_config_and_proxies_and_immutability_stays_not_measurable(db, monkeypatch):
    from app.models.backup import BkJob, BkProxy, BkRepository
    row = _sync(db, monkeypatch)
    jobs = {j.name: j for j in db.query(BkJob).filter(BkJob.instance_id == row.id).all()}
    d = jobs["DEMO Daily VMs"]
    assert d.config_state == "ok" and d.encryption_enabled is False and d.cbt_enabled is True
    assert (d.retention_type, d.retention_quantity) == ("Days", 14) and d.schedule_summary == "Günlük 22:00"
    cp = jobs["DEMO Copy to DR"]
    assert cp.encryption_enabled is None and cp.cbt_enabled is None          # alan yok → None, False değil
    assert db.query(BkProxy).filter(BkProxy.instance_id == row.id).count() == 2
    assert all(r.immutability_status == "not_measurable"
               for r in db.query(BkRepository).filter(BkRepository.instance_id == row.id).all())


def test_config_findings_pass_fail_not_measurable_not_applicable(db, monkeypatch):
    from app.services.backup import extras
    _sync(db, monkeypatch)
    by = {(f.check_id, f.entity_name): f.result for f in extras.job_config_findings(db)}
    assert by[("bk.job.encryption_off", "DEMO Daily VMs")] == RESULT_FAIL
    assert by[("bk.job.encryption_off", "DEMO Critical hourly")] == RESULT_PASS
    assert by[("bk.job.encryption_off", "DEMO Copy to DR")] == RESULT_NOT_MEASURABLE
    assert by[("bk.job.cbt_off", "DEMO Weekly DB")] == RESULT_FAIL
    assert by[("bk.job.cbt_off", "DEMO Daily VMs")] == RESULT_PASS
    assert by[("bk.job.cbt_off", "DEMO Copy to DR")] == RESULT_NOT_APPLICABLE   # VMware dışı iş
    assert {v for (c, _), v in by.items() if c == "bk.repo.immutability"} == {RESULT_NOT_MEASURABLE}


def test_forbidden_config_keeps_previous_values_and_marks_state(db, monkeypatch):
    from app.models.backup import BkJob
    from app.services.backup import extras
    row = _sync(db, monkeypatch)

    class Forbidden(type(VeeamDemoProvider(None, vms=[])._transport())):
        def get_json(self, key, params=None, **kw):
            if key == "jobs":
                raise VeeamApiError("forbidden", "403")
            return super().get_json(key, params, **kw)
    vms = _demo_vms(40)
    prov = VeeamDemoProvider(row, vms=vms)
    prov._transport = lambda: Forbidden(vms)
    assert bsync.sync_instance(db, row, force=True, provider=prov)["ok"] is True
    j = db.query(BkJob).filter(BkJob.instance_id == row.id, BkJob.name == "DEMO Daily VMs").one()
    assert j.config_state == "forbidden" and j.encryption_enabled is False       # önceki değer korunur
    f = {(x.check_id, x.entity_name): x for x in extras.job_config_findings(db)}
    x = f[("bk.job.encryption_off", "DEMO Daily VMs")]
    assert x.result == RESULT_NOT_MEASURABLE and "yetki" in x.detail


def test_evidence_item_for_encryption_and_not_checked_list(db, monkeypatch):
    from app.services.backup import extras
    _sync(db, monkeypatch)
    ev = extras.evidence(db)
    it = [i for i in ev["items"] if i["item"] == "Yedek işlerinde şifreleme"][0]
    assert it["status"] == "eksik"           # DEMO Daily şifresiz
    assert any("immutability" in x for x in ev["not_checked"])
