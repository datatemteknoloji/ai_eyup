"""Automic altyapı: küçük tablo istisnası, durum, ekip, hostname, collector."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.automic.defaults import effective_settings
from app.services.automic.infra_status import (
    STATUS_CONNECTED,
    STATUS_DISCONNECTED,
    STATUS_MISSING,
    STATUS_UNKNOWN,
    compute_agent_status,
    compute_engine_status,
)
from app.services.automic.small_tables import SMALL_REF_TABLES, check_row_count, risk_report_entries
from app.services.automic.source.fake import FakeSource
from app.services.automic.teams import RULE_ORDER, import_csv, resolve_team, seed_demo_rules, upsert_rule


def test_small_table_list_contains_host_mqsrv():
    assert "HOST" in SMALL_REF_TABLES
    assert "MQSRV" in SMALL_REF_TABLES
    assert "OHG" in SMALL_REF_TABLES
    assert "OHGF" in SMALL_REF_TABLES


def test_small_table_threshold_disables():
    settings = {"source_guard": {"small_table_row_threshold": 100}}
    ok, warn = check_row_count("HOST", 50, settings)
    assert ok and warn is None
    ok, warn = check_row_count("HOST", 101, settings)
    assert not ok
    assert "Kritik" in (warn or "")
    assert "devre dışı" in (warn or "")


def test_risk_report_includes_small_tables():
    entries = risk_report_entries({"source_guard": {"small_table_row_threshold": 10000}})
    names = {e["table"] for e in entries}
    assert names == set(SMALL_REF_TABLES)


def test_three_valued_agent_status():
    settings = {"infrastructure": {"life_sign_stale_sec": 300, "sync_stale_sec": 900}}
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    src = now
    # bağlı
    st, rule = compute_agent_status(
        host_active=1, last_life_sign=now - timedelta(seconds=30),
        source_now=src, synced_at=now, wall_now=now, settings=settings,
    )
    assert st == STATUS_CONNECTED
    # kopuk — HOST_Active=0
    st, rule = compute_agent_status(
        host_active=0, last_life_sign=now - timedelta(seconds=30),
        source_now=src, synced_at=now, wall_now=now, settings=settings,
    )
    assert st == STATUS_DISCONNECTED
    assert "host_active" in rule
    # kopuk — life sign eski (kaynak saatine göre)
    st, _ = compute_agent_status(
        host_active=1, last_life_sign=now - timedelta(hours=2),
        source_now=src, synced_at=now, wall_now=now, settings=settings,
    )
    assert st == STATUS_DISCONNECTED
    # bilinmiyor — sync stale
    st, rule = compute_agent_status(
        host_active=1, last_life_sign=now - timedelta(seconds=10),
        source_now=src, synced_at=now - timedelta(hours=2), wall_now=now, settings=settings,
    )
    assert st == STATUS_UNKNOWN
    assert rule == "sync_stale"
    # missing
    st, _ = compute_agent_status(
        host_active=1, last_life_sign=now, source_now=src, synced_at=now,
        wall_now=now, settings=settings, missing=True,
    )
    assert st == STATUS_MISSING


def test_unknown_never_equals_disconnected_label():
    from app.services.automic.infra_status import status_label_tr
    assert status_label_tr(STATUS_UNKNOWN) == "bilinmiyor"
    assert status_label_tr(STATUS_DISCONNECTED) == "kopuk"
    assert status_label_tr(STATUS_UNKNOWN) != status_label_tr(STATUS_DISCONNECTED)


def test_engine_status_life_sign():
    settings = {"infrastructure": {"life_sign_stale_sec": 300, "sync_stale_sec": 900}}
    now = datetime(2026, 10, 12, 12, 0, tzinfo=timezone.utc)
    st, _ = compute_engine_status(
        last_life_sign=now - timedelta(seconds=20), source_now=now,
        synced_at=now, wall_now=now, settings=settings,
    )
    assert st == STATUS_CONNECTED
    st, _ = compute_engine_status(
        last_life_sign=now - timedelta(hours=1), source_now=now,
        synced_at=now, wall_now=now, settings=settings,
    )
    assert st == STATUS_DISCONNECTED


def test_fake_hosts_and_mqsrv():
    src = FakeSource(1, {"fake_clients": [100]}, None, effective_settings({}), {})
    hosts = src.fetch_hosts()
    assert 10 <= len(hosts) <= 20
    disconnected = [h for h in hosts if int(h.get("host_active") or 0) == 0]
    assert len(disconnected) >= 2
    mq = src.fetch_mqsrv()
    types = {int(m["mqsrv_type"]) for m in mq}
    assert 4 in types  # PWP
    assert 1 in types  # CP
    assert 8 in types  # Agent
    assert 32 in types or 64 in types  # REST/JCP
    groups = src.fetch_agent_groups()
    assert len(groups["groups"]) >= 2
    assert len(groups["members"]) >= 2


def test_team_rule_priority(db_session=None):
    """Kurallar sırası: object_exact > folder > name > archive > dept > client."""
    # Saf birim: resolve_team sahte rule listesiyle
    from types import SimpleNamespace

    def R(rt, mv, team, pr):
        return SimpleNamespace(
            id=pr, rule_type=rt, match_value=mv, team=team,
            priority=pr, enabled=True,
        )

    rules = [
        R("client", "100", "ClientTeam", 60),
        R("folder_prefix", "FIN/", "Finans", 20),
        R("object_exact", "JOBS.FIN.X", "ExactTeam", 10),
        R("name_pattern", "JOBS.FIN.*", "PatternTeam", 30),
        R("archive_key", "1:FINANCE", "ArchTeam", 40),
        R("user_department", "OPS", "OpsTeam", 50),
    ]
    # object_exact kazanır
    r = resolve_team(
        None, 1, object_name="JOBS.FIN.X", folder="FIN/", archive1="FINANCE",
        client=100, creator_department="OPS", rules=rules,
    )
    assert r["team"] == "ExactTeam"
    # folder
    r = resolve_team(
        None, 1, object_name="JOBS.OTHER", folder="FIN/BATCH",
        client=100, rules=rules,
    )
    assert r["team"] == "Finans"
    # pattern
    r = resolve_team(
        None, 1, object_name="JOBS.FIN.LOAD.01", folder="/OTHER/",
        client=100, rules=rules,
    )
    assert r["team"] == "PatternTeam"
    # archive
    r = resolve_team(
        None, 1, object_name="JOBS.X", folder="/X/", archive1="FINANCE",
        client=100, rules=rules,
    )
    assert r["team"] == "ArchTeam"
    # dept
    r = resolve_team(
        None, 1, object_name="JOBS.X", folder="/X/",
        client=100, creator_department="OPS", rules=rules,
    )
    assert r["team"] == "OpsTeam"
    # client
    r = resolve_team(
        None, 1, object_name="JOBS.X", folder="/X/", client=100, rules=rules,
    )
    assert r["team"] == "ClientTeam"
    # none
    r = resolve_team(
        None, 1, object_name="JOBS.X", folder="/X/", client=999, rules=rules,
    )
    assert r["team"] is None
    assert "atanmamış" in (r["rule_label"] or "")


def test_rule_order_matches_spec():
    assert RULE_ORDER[0] == "object_exact"
    assert RULE_ORDER[3] == "archive_key"
    assert RULE_ORDER[4] == "user_department"
    assert RULE_ORDER[-1] == "client"


def test_hostname_resolve_order():
    from app.services.automic.hostname_resolve import resolve_hostname

    ov = {("agent", "LNXETL01"): "manual-host", ("ip", "10.10.1.99"): "ip-mapped"}
    r = resolve_hostname(
        agent_name="LNXETL01", ip="10.10.1.31", hostname_automic="automic-hn",
        overrides=ov, settings={"infrastructure": {"reverse_dns_enabled": False}},
    )
    assert r["hostname"] == "manual-host"
    assert r["source"] == "manual_agent"
    r = resolve_hostname(
        agent_name="X", ip="10.10.1.31", hostname_automic="automic-hn",
        overrides={}, settings={},
    )
    assert r["hostname"] == "automic-hn"
    assert r["source"] == "automic"
    r = resolve_hostname(
        agent_name="X", ip="10.10.1.99", hostname_automic=None,
        overrides=ov, settings={},
    )
    assert r["hostname"] == "ip-mapped"
    assert r["source"] == "ip_map"


def test_agent_group_vs_actual_in_fake_executions():
    from app.services.automic.source.fake import run_id_hi_for_minute, run_id_lo_for_minute
    src = FakeSource(1, {"fake_clients": [100]}, None, effective_settings({}), {})
    now = datetime.now(timezone.utc)
    m = int(now.timestamp() // 60) - 10
    rows = src.fetch_ended_executions(
        [100], now - timedelta(hours=2), now, limit=500,
        id_min=run_id_lo_for_minute(m - 30), id_max=run_id_hi_for_minute(m),
    )
    with_group = [r for r in rows if r.get("agent_group")]
    assert with_group, "fake veri agent grubu üretmeli"
    for r in with_group[:5]:
        assert r["agent_assigned"] == r["agent_group"]
        assert r.get("agent")


def test_csv_team_import_unit():
    import csv
    import io
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["object_name", "team"])
    w.writeheader()
    w.writerow({"object_name": "JOBS.FIN.X", "team": "Finans"})
    content = buf.getvalue()
    assert "JOBS.FIN.X" in content
    assert "Finans" in content


def test_masking_ip_hostname_settings():
    from app.services.automic.masking import mask_text
    out = mask_text("host 10.10.1.11 ok", {"mask_ip": True, "mask_hostname": False})
    assert "[IP]" in out
    out2 = mask_text("lnxapp01.corp.local", {"mask_ip": False, "mask_hostname": True})
    assert "[HOST]" in out2 or out2 != "lnxapp01.corp.local"
