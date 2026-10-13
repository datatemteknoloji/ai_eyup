"""Maskeleme politikası: gizli → her zaman; Automic kullanıcı korunur; IP/hostname ayarlı; llm_deployment audit."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from app.services.automic.defaults import DEFAULT_SETTINGS, effective_settings, validate_settings
from app.services.automic.masking import (
    SECRETS_ONLY,
    mask_obj,
    mask_text,
    normalize_masking_cfg,
    redact_secrets,
)


@pytest.mark.parametrize("raw,leak", [
    ("password: hunter2", "hunter2"),
    ("PWD=SuperSecret99;", "SuperSecret99"),
    ("Connection;PWD=abc123;UID=app", "abc123"),
    ("--password=xyz123 --user a", "xyz123"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijkl", "eyJhbGci"),
    ("jdbc:oracle:thin:@h:1521/s;password=p4ss", "p4ss"),
    ("https://user:p%40ss@host/x", "p%40ss"),
    ("sqlplus batch/HiddenPass@DWHPRD @/opt/run.sql", "HiddenPass"),
    ("&DB_PASSWORD# = \"S3cr3tFake\"", "S3cr3tFake"),
    ("API_TOKEN=abcd1234efgh5678", "abcd1234efgh5678"),
])
def test_secrets_always_masked_default_cfg(raw, leak):
    """Varsayılan cfg ile (IP açık) gizli değerler yine maskelenir."""
    cfg = normalize_masking_cfg(DEFAULT_SETTINGS["masking"])
    assert cfg["mask_ip"] is False and cfg["mask_hostname"] is False
    out = mask_text(raw, cfg)
    assert leak not in out


def test_automic_username_not_masked():
    s = "Kullanıcı BATCH/OPS çalıştırdı; SCHED/AUTO zinciri; UC4/ADMIN onayladı"
    out = mask_text(s, DEFAULT_SETTINGS["masking"])
    assert "BATCH/OPS" in out and "SCHED/AUTO" in out and "UC4/ADMIN" in out


def test_connect_string_masked_but_username_kept():
    s = "BATCH/OPS job ok; sqlplus app/Secret99@ORCL"
    out = mask_text(s, {})
    assert "BATCH/OPS" in out
    assert "Secret99" not in out
    assert "***/" in out or "***@" in out or "app/***" in out


def test_ip_shown_by_default_masked_when_enabled():
    s = "host 10.20.30.40 failed"
    assert "10.20.30.40" in mask_text(s, {"mask_ip": False})
    assert "10.20.30.40" not in mask_text(s, {"mask_ip": True})
    assert "[IP]" in mask_text(s, {"mask_ip": True})


def test_hostname_masked_when_enabled():
    s = "hostname: lnxapp01.corp.example.com connected"
    assert "lnxapp01.corp.example.com" in mask_text(s, {"mask_hostname": False})
    out = mask_text(s, {"mask_hostname": True})
    assert "lnxapp01.corp.example.com" not in out
    assert "[HOST]" in out or "***" in out


def test_mask_obj_and_redact_for_audit_paths():
    payload = {
        "report": "PWD=leakme; user BATCH/OPS",
        "nested": ["token=abcXYZ99", "ok"],
    }
    out = mask_obj(payload, DEFAULT_SETTINGS["masking"])
    assert "leakme" not in str(out) and "abcXYZ99" not in str(out)
    assert "BATCH/OPS" in str(out)
    assert "hunter2" not in redact_secrets("password=hunter2 BATCH/OPS")
    assert "BATCH/OPS" in redact_secrets("password=hunter2 BATCH/OPS")
    assert "10.1.1.1" in mask_text("ip 10.1.1.1", SECRETS_ONLY)


def test_llm_deployment_validation():
    assert validate_settings({"llm_deployment": "internal"}) == []
    assert validate_settings({"llm_deployment": "external"}) == []
    assert any("llm_deployment" in e for e in validate_settings({"llm_deployment": "cloud"}))
    assert effective_settings({}).get("llm_deployment") == "internal"


def test_llm_deployment_change_audited():
    """external'a geçişte llm_deployment_change audit çağrılır."""
    from types import SimpleNamespace

    from app.api import automation as api
    from app.models.automic import AutomicSystem

    user = MagicMock()
    user.id = 1
    user.username = "admin"
    request = MagicMock()
    # MagicMock(name=...) özel; SimpleNamespace kullan
    body = SimpleNamespace(
        settings={**DEFAULT_SETTINGS, "llm_deployment": "external"},
        source_type=None, name=None, connection=None, password=None,
        clients=None, enabled=None, is_default=False, primary_ack=False,
    )

    s = AutomicSystem(
        id=42, name="AE-TEST", source_type="fake",
        connection={}, clients=[100],
        settings={**DEFAULT_SETTINGS, "llm_deployment": "internal"},
        is_default=True, enabled=True,
    )
    adb = MagicMock()
    adb.get.return_value = s

    audits = []

    def fake_audit(req, usr, action, summary, **kw):
        audits.append({"action": action, "summary": summary, **kw})

    with patch.object(api, "_audit", side_effect=fake_audit), \
         patch("app.services.automic.service.system_public", return_value={"id": 42}), \
         patch.object(api, "_validate"):
        api.update_system_ep(42, body, request, user=user, adb=adb)

    dep = [a for a in audits if a["action"] == "llm_deployment_change"]
    assert dep, f"audit yok: {audits}"
    assert dep[0]["detail"]["from"] == "internal" and dep[0]["detail"]["to"] == "external"


def test_audit_helper_masks_secrets_in_summary():
    from app.api import automation as api

    with patch("app.api.automation.SessionLocal") as SL, \
         patch("app.api.automation.record_audit") as ra, \
         patch("app.api.automation.client_ip", return_value="127.0.0.1"):
        sess = MagicMock()
        SL.return_value = sess
        api._audit(
            MagicMock(), MagicMock(), "chat",
            "Hata: password=SuperSecret BATCH/OPS",
            detail={"pwd": "PWD=OtherSecret;", "user": "BATCH/OPS"},
        )
        args, kwargs = ra.call_args
        assert "SuperSecret" not in (kwargs.get("summary") or "")
        assert "BATCH/OPS" in (kwargs.get("summary") or "")
        detail = kwargs.get("detail") or {}
        assert "OtherSecret" not in str(detail)
        assert "BATCH/OPS" in str(detail)
