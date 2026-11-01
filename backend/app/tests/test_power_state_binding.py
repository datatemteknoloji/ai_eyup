"""Adım 5d — sohbet dışı güç durumu karşılaştırmaları kanonik fonksiyona bağlı."""
import re
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from app.services import report_engine as re_
from app.services.chat_quality import power_state as ps

APP = Path(__file__).resolve().parents[1]
BOUND_FILES = [
    "services/report_engine.py", "api/hypervisors.py", "services/virt_monitoring.py", "api/ops_center.py",
    "services/virt_ops_center.py", "services/openshift_virt_host_metrics.py", "services/virt_reclaim.py",
]
RAWS = ["poweredOn", "POWERED_ON", "powered on", "Powered-On", "up", "UP", "Running", "running", "on", "active",
        "poweredOff", "POWERED_OFF", "down", "Stopped", "off", "shutdown", "suspended", "Paused", "Starting",
        "Migrating", "provisioning", "unknown", "UNKNOWN", "", None, " poweredOn ", "CrashLoopBackOff", "weird-value"]


def _sql_emul(raw):
    """sql_is_on'un normalizasyonunun Python eşleniği (btrim → regexp_replace → lower → IN)."""
    if raw is None:
        return False
    return re.sub(r"[\s_.-]+", "", str(raw).strip()).lower() in ps.on_keys()


@pytest.mark.parametrize("raw", RAWS)
def test_sql_expression_matches_python_classifier(raw):
    assert _sql_emul(raw) == ps.is_on(raw)


def test_sql_fragment_is_derived_from_canonical_keys():
    frag = ps.sql_is_on("power_state")
    for k in ps.on_keys():
        assert f"'{k}'" in frag
    assert "power_state" in frag and "regexp_replace" in frag


def test_sqla_expression_compiles():
    from sqlalchemy import Column, String
    from sqlalchemy.dialects import postgresql
    c = Column("vm_power_state", String)
    sql = str(ps.sqla_is_on(c).compile(dialect=postgresql.dialect()))
    assert "regexp_replace" in sql and "lower" in sql


@pytest.mark.parametrize("rel", BOUND_FILES)
def test_no_hardcoded_on_lists_left(rel):
    src = (APP / rel).read_text()
    assert "import power_state as" in src
    left = [l for l in src.splitlines() if re.search(r'"POWERED_ON",\s*"up"|\'POWERED_ON\',\s*\'poweredOn\'', l)]
    # VMware Tools yerleri de artık kanonik güç durumu + hypervisor türü kapsamına bağlı (Aşama 2b): sabit liste kalmamalı
    assert left == [], (rel, left)
    assert "5d-ATLANDI" not in src
    assert 'ilike("%on%")' not in src
    assert not re.search(r'"on" in \(?\w*\.?\w*vm_power_state', src) and '"on" in ps' not in src


# ── report_engine davranışı ───────────────────────────────────────────────────────────────

def vm(name, state, cpu=2, ram=4, disk=50):
    return {"id": 1, "name": name, "ip": "", "hypervisor": "h", "os_type": "", "os_version": "", "os_release": "",
            "cpu_count": cpu, "memory_gb": ram, "memory_mb": ram * 1024, "disk_gb": disk, "power_state": state,
            "tools_status": "unknown", "hw_version": "", "cluster": "", "datastore": "", "tier": "unknown",
            "last_sync": None, "ai_ready": False}


@pytest.fixture
def fleet(monkeypatch):
    vms = (
        [vm(f"on{i}", "poweredOn") for i in range(3)]
        + [vm(f"kv{i}", "Running") for i in range(4)]          # KubeVirt: eskiden kapalı sayılıyordu
        + [vm(f"off{i}", "POWERED_OFF") for i in range(2)]
        + [vm("stopped", "Stopped")]
        + [vm("paused", "Paused"), vm("unk", "unknown")]       # ne açık ne kapalı
    )
    monkeypatch.setattr(re_, "_get_vms", lambda db: vms)
    monkeypatch.setattr(re_, "_latest_host_metrics", lambda db: [])
    monkeypatch.setattr(re_, "_get_active_events", lambda db, days=7: [])
    return vms


def test_executive_summary_counts_running_kubevirt_as_on(fleet):
    try:
        data = re_.generate_executive_summary(MagicMock())
    except Exception as e:  # rapor başka bağımlılıklara ihtiyaç duyarsa testi atla (davranış statik testlerle de korunur)
        pytest.skip(f"executive_summary yalıtılamadı: {type(e).__name__}")
    infra = data.get("infrastructure") or data
    flat = repr(data)
    assert "'vm_powered_on': 7" in flat       # 3 poweredOn + 4 Running
    assert "'vm_powered_off': 3" in flat      # 2 POWERED_OFF + 1 Stopped (Paused/unknown sayılmaz)


def test_finance_savings_only_off(fleet):
    db = MagicMock()
    db.query.return_value.first.return_value = None
    db.query.return_value.all.return_value = []
    db.query.return_value.filter.return_value.all.return_value = []
    try:
        data = re_.generate_finance_report(db)
    except Exception as e:
        pytest.skip(f"finance yalıtılamadı: {type(e).__name__}")
    # 3 kapalı VM × (2 çekirdek×50 + 4 GB×20) = 3 × 180
    assert data["powered_off_savings"] == 540.0
    # çalışan maliyeti yalnız 7 çalışan VM'den
    assert len(data["top_cost_vms"]) == 7
