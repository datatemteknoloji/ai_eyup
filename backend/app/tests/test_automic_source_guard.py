"""Automic kaynak DB korumaları — SQL guard, timeout, rol/PRIMARY onay, sapma."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException

from app.services.automic.defaults import DEFAULT_SETTINGS, effective_settings
from app.services.automic.source.base import SourceError
from app.services.automic.source.fake import FakeSource
from app.services.automic.source.sql_guard import UnsafeSqlError, assert_read_only
from app.services.automic.source_role import (
    build_source_info,
    check_system_role,
    require_primary_ack_or_raise,
    source_info_public,
)


def _fake(**conn) -> FakeSource:
    return FakeSource(1, conn, None, effective_settings({}), None)


# ── SQL guard (sahte bağlantı yolu) ───────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "UPDATE AH SET AH_STATUS = 1",
    "DELETE FROM AH WHERE AH_IDNR = 1",
    "BEGIN NULL; END",
    "DECLARE x NUMBER; BEGIN NULL; END",
    "SELECT * FROM AH FOR UPDATE",
    "SELECT 1 FROM dual; SELECT 2 FROM dual",
    "SELECT AH_IDNR INTO :x FROM AH",
    "MERGE INTO AH USING dual ON (1=1) WHEN MATCHED THEN UPDATE SET AH_STATUS=1",
])
def test_guard_rejects_dangerous_sql(sql):
    src = _fake()
    with pytest.raises(UnsafeSqlError):
        src.run_guarded_sql(sql)


def test_guard_allows_normal_select():
    src = _fake()
    assert src.run_guarded_sql("SELECT 1 FROM dual") == [(1,)]
    assert assert_read_only("WITH x AS (SELECT 1 AS n FROM dual) SELECT * FROM x")


def test_fake_timeout_cancels_with_meaningful_error():
    src = _fake(fake_timeout=True)
    with pytest.raises(SourceError) as ei:
        src.run_guarded_sql("SELECT 1 FROM dual")
    assert ei.value.code == "call_timeout"
    assert "zaman aşımı" in str(ei.value).lower() or "timeout" in str(ei.value).lower()


def test_default_call_timeout_is_30():
    g = DEFAULT_SETTINGS["source_guard"]
    assert g["call_timeout_sec"] == 30
    assert g["chat_timeout_sec"] == 30
    assert g["collector_timeout_sec"] == 60  # collector ayrı


# ── Rol / PRIMARY onay ───────────────────────────────────────────────────

def test_primary_requires_ack_blocks_without_ack():
    with pytest.raises(HTTPException) as ei:
        require_primary_ack_or_raise(database_role="PRIMARY", primary_ack=False)
    assert ei.value.status_code == 422
    assert "PRIMARY" in ei.value.detail


def test_primary_ack_allows_complete():
    require_primary_ack_or_raise(database_role="PRIMARY", primary_ack=True)
    require_primary_ack_or_raise(database_role="PHYSICAL STANDBY", primary_ack=False)
    require_primary_ack_or_raise(database_role=None, primary_ack=False)


def test_fake_primary_test_connection_warns():
    src = _fake(fake_database_role="PRIMARY")
    res = src.test_connection()
    assert res.ok
    assert res.details["requires_primary_ack"] is True
    assert res.details["database_role"] == "PRIMARY"
    assert any("primary" in w.lower() for w in res.warnings)
    info = build_source_info(src.read_database_role(), primary_ack=True, ack_user="admin")
    assert info["primary_ack"] is True and info["primary_ack_by"] == "admin"


def test_vdatabase_unknown_role_connection_still_ok():
    src = _fake(fake_role_unknown=True)
    res = src.test_connection()
    assert res.ok
    assert res.details["database_role_display"] == "bilinmiyor"
    assert res.details["role_known"] is False
    assert res.details["requires_primary_ack"] is False
    role = src.read_database_role()
    assert role["role_known"] is False
    require_primary_ack_or_raise(database_role=role.get("database_role"), primary_ack=False)


def test_role_drift_warns_but_access_continues():
    system = SimpleNamespace(
        id=42, name="uc4-prod", source_type="fake",
        connection={"fake_database_role": "PRIMARY"},
        secret_enc=None, capability=None,
        settings={
            "source_info": {
                "installed_database_role": "PHYSICAL STANDBY",
                "installed_role_known": True,
                "installed_at": "2026-01-01T00:00:00+00:00",
            },
        },
    )
    db = MagicMock()
    with patch("app.services.automic.source_role.build_source", return_value=_fake(fake_database_role="PRIMARY")):
        with patch("app.services.automic.source_role.record_audit"):
            out = check_system_role(db, system)
    assert out["ok"] is True
    assert out["role_drift"] is True
    assert "PRIMARY" in (out["source_info"]["role_drift_message"] or "")
    # Erişim kesilmedi — fonksiyon engel fırlatmadı; settings güncellendi
    assert system.settings["source_info"]["role_drift"] is True
    pub = source_info_public(system.settings)
    assert pub["role_drift"] is True


def test_oracle_timeout_ms_uses_defaults():
    from app.services.automic.source.oracle import OracleSource

    src = OracleSource(1, {}, None, effective_settings({}), None)
    assert src._timeout_ms("chat") == 30_000
    assert src._timeout_ms("collector") == 60_000
    assert src._timeout_ms("other") == 30_000
