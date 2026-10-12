"""F.4: Veeam fixture kümeleri üzerinde PARAMETRİK contract testleri + maskeleme + toplama scripti.

Fixture kümeleri:
  * ``doc-1.3-rev1`` — Veeam Help Center örneklerinden derlenmiş (GERÇEK DEĞİL), ``vbr_1_3_rev1_doc_examples.json``.
  * ``<sürüm>`` — ``backend/scripts/veeam_collect_fixtures.py`` ile gerçek VBR'den alınmış MASKELİ yanıtlar
    (``fixtures/veeam/<sürüm>/_manifest.json``, source=real). Klasör eklenince testler OTOMATİK onu da koşar.
"""
from __future__ import annotations

import json
import pathlib
from datetime import datetime, timezone
from typing import Any, Dict, List

import pytest

from app.services.backup import fixture_collect
from app.services.backup.fixture_mask import Masker, leaks
from app.services.backup.veeam_api_ref import ENDPOINTS, field_verification, unverified_endpoints
from app.services.backup.veeam_cfg import _g, _MISSING, host_from_backup_object_path, parse_job_config
from app.services.backup.veeam_client import VeeamApiError
from app.services.backup.veeam_provider import collect_snapshot

ROOT = pathlib.Path(__file__).parent / "fixtures" / "veeam"
DOC_FILE = ROOT / "vbr_1_3_rev1_doc_examples.json"
_DOC_KEYMAP = {"serverInfo": "server_info"}
NOW = datetime(2025, 7, 30, tzinfo=timezone.utc)

# Gerçek yanıtlarda da meşru biçimde eksik olabilen alanlar (ör. çalışmamış iş, Linux olmayan depo) — gerekçeli.
OPTIONAL: Dict[str, set] = {
    "jobs_states": {"lastRun", "nextRun", "nextRunPolicy", "sessionId", "repositoryId", "repositoryName"},
    "backups": {"repositoryId"},
    "backup_objects": {"objectId", "path", "restorePointsCount"},   # Template/UUID örnekleri (api_ref #1)
    "restore_points": set(),
    "sessions": {"endTime", "result.message"},
    "jobs": {"virtualMachines.includes[].hostName/name/type", "schedule.daily/monthly/periodically/continuously.isEnabled",
             "storage.advancedSettings.vSphere.changedBlockTracking.isEnabled",     # yalnız VMware işleri (api_ref #10)
             "storage.advancedSettings.storageData.encryption.isEnabled",
             "guestProcessing.appAwareProcessing.isEnabled", "schedule.retry.isEnabled/retryCount/awaitMinutes",
             "storage.gfsPolicy.isEnabled", "storage.advancedSettings.backupHealth.isEnabled",
             "schedule.runAutomatically", "schedule.backupWindow.isEnabled", "storage.backupRepositoryId",
             "storage.retentionPolicy.type/quantity"},
    "repositories_states": set(),
    "repositories": {"description"},
    "proxies": {"server.transportMode", "server.maxTaskCount"},
    "proxies_states": set(),
    "object_restore_points": set(),
}


def _sets() -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    doc = json.loads(DOC_FILE.read_text(encoding="utf-8"))
    out.append({"id": "doc-1.3-rev1", "real": False, "masked": False,
                "bodies": {_DOC_KEYMAP.get(k, k): v for k, v in doc.items() if not k.startswith("_") and k != "token"}})
    for m in sorted(ROOT.glob("*/_manifest.json")):
        man = json.loads(m.read_text(encoding="utf-8"))
        bodies = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in m.parent.glob("*.json") if not p.name.startswith("_")}
        out.append({"id": m.parent.name, "real": man.get("source") == "real", "masked": bool(man.get("masked")), "bodies": bodies})
    return out


SETS = _sets()


class FixtureTransport:
    def __init__(self, bodies: Dict[str, Any]):
        self.b = bodies

    def get_json(self, key, params=None, **kw):
        if key not in self.b:
            raise VeeamApiError("forbidden", f"{key}: fixture'da yok")
        return self.b[key]


def _rows(body: Any) -> List[Dict[str, Any]]:
    return [r for r in (body.get("data") if isinstance(body, dict) else None) or [] if isinstance(r, dict)] \
        if isinstance(body, dict) and "data" in body else ([body] if isinstance(body, dict) else [])


def _present(row: Dict[str, Any], field: str) -> bool:
    if "[]" in field:
        head, _, tail = field.partition("[]")
        arr = _g(row, *[p for p in head.split(".") if p])
        if not isinstance(arr, list):
            return False
        sub = tail.lstrip(".")
        names = sub.split("/") if sub else []
        return any(isinstance(x, dict) and all(n in x for n in names) for x in arr)
    if "/" in field:                       # "a.b.c/d": son bölüm ortak ebeveynde alternatifler
        head, _, last = field.rpartition(".")
        base = [p for p in head.split(".") if p]
        return all(_g(row, *base, n) is not _MISSING for n in field.split(".")[-1].split("/"))
    return _g(row, *field.split(".")) is not _MISSING


@pytest.mark.parametrize("fx", SETS, ids=[s["id"] for s in SETS])
def test_snapshot_builds_from_fixture_set(fx):
    snap = collect_snapshot(FixtureTransport(fx["bodies"]), {}, now=NOW)
    for k in ("jobs", "repos", "sessions", "objects", "restore_points", "job_config", "proxies", "repo_info", "access"):
        assert k in snap
    # eksik endpoint (fixture'da yok) senkronu düşürmez; yetki gibi işaretlenir
    for k in ("jobs", "proxies_states", "proxies", "repositories"):
        if k not in fx["bodies"]:
            assert snap["access"].get(k) == "forbidden"


@pytest.mark.parametrize("fx", SETS, ids=[s["id"] for s in SETS])
def test_fields_used_present_in_fixture_rows(fx):
    for key, body in fx["bodies"].items():
        ep = ENDPOINTS.get(key)
        rows = _rows(body)
        if ep is None or not rows or not isinstance(body, dict):
            continue
        missing = {f for f in ep.fields_used if not any(_present(r, f) for r in rows)}
        extra = missing - OPTIONAL.get(key, set())
        assert not extra, f"[{fx['id']}] {key}: dokümandaki alanlar yanıtta yok: {sorted(extra)}"


@pytest.mark.parametrize("fx", SETS, ids=[s["id"] for s in SETS])
def test_job_config_is_tristate_only(fx):
    for r in _rows(fx["bodies"].get("jobs", {"data": []})):
        c = parse_job_config(r)
        for k in ("encryption", "cbt", "app_aware", "backup_health", "gfs_enabled", "retry_enabled", "window_enabled", "disabled"):
            assert c[k] is None or isinstance(c[k], bool), (fx["id"], k, c[k])
        assert c["retention_quantity"] is None or isinstance(c["retention_quantity"], int)


@pytest.mark.parametrize("fx", [s for s in SETS if s["masked"]] or [{"id": "none", "bodies": {}, "masked": True}],
                         ids=lambda f: f["id"])
def test_masked_real_fixtures_have_no_leaks(fx):
    assert leaks(fx["bodies"]) == []


def test_unverified_endpoint_list_matches_real_fixtures():
    real = [s for s in SETS if s["real"]]
    unv = set(unverified_endpoints())
    if not real:
        # Gerçek VBR fixture'ı yok → TÜM endpoint'ler sahada doğrulanmadı (doküman örneği saha kanıtı değildir)
        assert unv == {r["key"] for r in field_verification()} and "jobs" in unv and "server_info" in unv
    else:
        assert unv <= {r["key"] for r in field_verification()}


# ── maskeleme ────────────────────────────────────────────────────────────────

def test_mask_removes_hosts_ips_users_paths_but_keeps_structure_and_ids():
    doc = json.loads(DOC_FILE.read_text(encoding="utf-8"))
    assert leaks(doc), "örnek dosya maskesiz olduğu için sızıntı içermeli (testin anlamlı olması için)"
    m = Masker()
    out = m.mask(doc)
    assert leaks(out) == []
    # yapı korunur
    def keys(o):
        return {k: keys(v) for k, v in o.items()} if isinstance(o, dict) else ([keys(o[0])] if isinstance(o, list) and o else None)
    assert keys(out) == keys(doc)
    # UUID'ler, sürüm numaraları, adlar korunur
    assert out["jobs"]["data"][0]["id"] == doc["jobs"]["data"][0]["id"]
    assert out["serverInfo"]["buildVersion"] == doc["serverInfo"]["buildVersion"]
    assert out["jobs"]["data"][0]["name"] == doc["jobs"]["data"][0]["name"]
    assert "vcenter01.tech.local" not in json.dumps(out) and "sheila.d.cory" not in json.dumps(out)


def test_mask_is_deterministic_and_keeps_host_correlation():
    m = Masker()
    inc = m.mask({"hostName": "VCenter01.Tech.Local"})["hostName"]
    path = m.mask({"path": "vcenter01.tech.local\\Prague\\Templates\\win10"})["path"]
    assert host_from_backup_object_path(path) == inc.lower()           # job hostName ↔ backupObjects.path eşleşmesi korunur
    assert m.mask({"hostName": "vcenter01.tech.local"})["hostName"] == inc
    assert m.mask({"x": "Created by TECH\\sheila"})["x"] == m.mask({"x": "Created by TECH\\sheila"})["x"]
    assert m.mask({"ip": "10.1.2.3"})["ip"].startswith("192.0.2.")
    assert Masker(mask_names=True).mask({"name": "vm1"})["name"] == "name1"
    assert Masker().mask({"name": "vm1"})["name"] == "vm1"


def test_leaks_detects_unmasked_values():
    assert leaks({"a": "10.0.0.5"}) and leaks({"a": "dc01.corp.local"}) and leaks({"a": "CORP\\admin"})
    assert leaks({"a": "192.0.2.4", "b": "host-1.example.invalid", "buildVersion": "13.0.1.180"}) == []


# ── toplama scripti (salt-okunur) ────────────────────────────────────────────

class _FakeClient:
    gets: List[str] = []

    def __init__(self, host, user, pw, **kw):
        self.kw = kw

    def logout(self):
        pass

    def get_json(self, key, params=None, *, path=None):
        _FakeClient.gets.append(key)
        doc = json.loads(DOC_FILE.read_text(encoding="utf-8"))
        if key == "server_info":
            raise VeeamApiError("forbidden", "403", 403)
        return doc[_DOC_KEYMAP.get(key, key)] if key in doc or key == "serverInfo" else {"data": [], "pagination": {"total": 0}}


def test_collect_script_is_read_only_masks_and_records_forbidden(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(fixture_collect, "VeeamRestClient", _FakeClient)
    monkeypatch.setenv("VBR_PASSWORD", "S3cr3t-PW!")
    _FakeClient.gets = []
    rc = fixture_collect.main(["--host", "vbr.corp.local", "--user", "svc", "--version", "9.9.9.9", "--out", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0 and "S3cr3t-PW!" not in out
    d = tmp_path / "9.9.9.9"
    man = json.loads((d / "_manifest.json").read_text())
    assert man["source"] == "real" and man["masked"] is True
    assert man["endpoints"]["server_info"]["status"] == "forbidden" and not (d / "server_info.json").exists()
    assert man["endpoints"]["jobs"]["status"] == "ok" and (d / "jobs.json").exists()
    assert leaks({p.stem: json.loads(p.read_text()) for p in d.glob("*.json") if p.name != "_manifest.json"}) == []
    # yalnız ENDPOINTS'teki GET anahtarları istendi (token/logout hariç)
    assert set(_FakeClient.gets) <= {k for k, e in ENDPOINTS.items() if e.method == "GET"}


def test_collect_script_refuses_to_write_on_leak_and_dry_run_writes_nothing(tmp_path, monkeypatch, capsys):
    class Leaky(_FakeClient):
        def get_json(self, key, params=None, *, path=None):
            if key == "jobs":
                return {"data": [{"id": "x", "name": "n", "note": "ldap://10.9.9.9"}]}   # IP:'ldap://10.9.9.9' → maskelenir
            return super().get_json(key, params, path=path)
    monkeypatch.setattr(fixture_collect, "VeeamRestClient", Leaky)
    monkeypatch.setattr(fixture_collect, "leaks", lambda o: ["ip:1.2.3.4"])       # maskelemeye rağmen sızıntı varsayımı
    monkeypatch.setenv("VBR_PASSWORD", "pw")
    assert fixture_collect.main(["--host", "h", "--user", "u", "--version", "1.0", "--out", str(tmp_path)]) == 2
    assert not (tmp_path / "1.0").exists()
    monkeypatch.setattr(fixture_collect, "leaks", leaks)
    assert fixture_collect.main(["--host", "h", "--user", "u", "--version", "1.0", "--out", str(tmp_path), "--dry-run"]) == 0
    assert not (tmp_path / "1.0").exists()
