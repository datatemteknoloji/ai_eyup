"""Bulgu bağlamı: sensör türüne göre genel rehber, ilişkili bulgular, host düşerse etki."""
from app.models.infra_finding import InfraFinding
from app.services.findings import context as ctx
from app.tests.test_capacity_v2 import _seed, _vm


def _f(db, hv, check, host="esx1", cluster="A", result="fail", severity="high", evidence=None, category="hardware",
       title=None, kind="host"):
    row = InfraFinding(platform="vmware", source_id=hv.id, source_name=hv.name, category=category, check_id=check,
                       entity_kind=kind, entity_ref=f"host:{host}", entity_name=host, cluster_name=cluster,
                       result=result, severity=severity, title=title or check, evidence=evidence or {}, active=True)
    db.add(row)
    db.commit()
    return row


def test_guide_per_sensor_type_without_links_or_commands(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("esx1", "e1", 256, 50, "A"), ("esx2", "e2", 256, 50, "A")])
    row = _f(db, hv, "hw.host.sensor_alarm", evidence={"sensors": [
        {"name": "Power Supply 2", "type": "power", "state": "red"}, {"name": "System Fan 3", "type": "fan", "state": "yellow"},
        {"name": "Power Supply 1", "type": "Power", "state": "red"}], "vendor": "HP"})
    g = ctx.sensor_guides(row, "tr")
    assert [x["key"] for x in g["guides"]] == ["power", "fan"]        # tür başına tek rehber
    assert g["official_links"] == [] and g["vendor"] == "HP"           # doğrulanmış satıcı bağlantısı yok → uydurulmaz
    blob = " ".join(" ".join(x["steps"]) + x["cause"] for x in g["guides"])
    assert "http" not in blob and "KB" not in blob
    assert ctx.sensor_guides(row, "en")["guides"][0]["title"] == "Power supply / power sensor"


def test_guide_generic_when_type_missing_and_none_for_other_checks(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("esx1", "e1", 256, 50, "A")])
    row = _f(db, hv, "hw.host.overall_status", evidence={"status": "red"})
    assert [x["key"] for x in ctx.sensor_guides(row)["guides"]] == ["generic"]
    assert ctx.sensor_guides(_f(db, hv, "vmw.host.ntp", category="health")) is None
    assert ctx.sensor_guides(_f(db, hv, "hw.host.sensor_alarm", host="esx9", result="pass")) is None


def test_related_findings_same_host_sorted_by_severity(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("esx1", "e1", 256, 50, "A"), ("esx2", "e2", 256, 50, "A")])
    a = _f(db, hv, "hw.host.sensor_alarm", severity="high")
    _f(db, hv, "hw.host.overall_status", severity="critical")
    _f(db, hv, "vmw.host.ntp", severity="low", category="health")
    _f(db, hv, "hw.host.sensor_alarm", host="esx2")                          # başka host
    _f(db, hv, "hw.host.config_issue", result="pass")                        # geçen bulgu sayılmaz
    rel = ctx.related_findings(db, a)
    assert [r["check_id"] for r in rel] == ["hw.host.overall_status", "vmw.host.ntp"]


def test_host_impact_uses_host_failure_and_context_bundle(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("esx1", "e1", 256, 100, "A"), ("esx2", "e2", 256, 20, "A")])
    _vm(db, hv, "vm-a", "esx1", 40)
    row = _f(db, hv, "hw.host.sensor_alarm", evidence={"sensors": [{"name": "PS", "type": "power", "state": "red"}]})
    out = ctx.finding_context(db, row)
    assert out["impact"]["available"] and out["impact"]["verdict"] == "fit" and out["impact"]["vms"] == 1
    assert out["impact"]["remaining_hosts"] == 1 and out["guide"]["guides"][0]["key"] == "power"


def test_impact_only_for_failed_hardware_host_findings(isolated_db):
    db = isolated_db
    hv = _seed(db, "vc01", [("esx1", "e1", 256, 100, "A"), ("esx2", "e2", 256, 20, "A")])
    health = _f(db, hv, "vmw.host.ntp", category="health")
    assert ctx.finding_context(db, health)["impact"] is None
    cl = _f(db, hv, "vmw.cluster.ha", kind="cluster", category="health")
    assert ctx.finding_context(db, cl)["related"] == []
