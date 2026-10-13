"""Adım 2 kapanış denetimi: LLM SQL yolu, sql_guard, secret_enc, test/discover korumaları."""
from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

from app.core.encryption import decrypt_secret, encrypt_secret, is_encrypted
from app.services.agent import tools as agent_tools
from app.services.agent.tools import RiskLevel
from app.services.automic import guard
from app.services.automic.masking import redact_secrets
from app.services.automic.queries import HISTORY_TEMPLATES, run_history
from app.services.automic.source.base import SourceError
from app.services.automic.source.sql_guard import UnsafeSqlError, assert_read_only


# ── 1) LLM serbest SQL yolu yok ───────────────────────────────────────────

def test_automic_tools_have_no_raw_sql_parameters():
    forbidden = {"sql", "query", "statement", "raw_sql", "plsql"}
    automic = {n: t for n, t in agent_tools.TOOLS.items() if n.startswith("automic_")}
    assert len(automic) == 8
    for name, tool in automic.items():
        props = ((tool.parameters or {}).get("properties") or {})
        overlap = forbidden & set(props)
        assert not overlap, f"{name} serbest SQL parametresi içeriyor: {overlap}"
        assert tool.risk_level == RiskLevel.READ_ONLY


def test_history_rejects_unknown_template_and_ignores_sql_param():
    """template_id kapalı küme; params içindeki sql çalıştırılmaz."""
    class _Sys:
        id = 1
        name = "t"
        clients = [100]
        settings = {}
        capability = {}

    out = run_history(None, _Sys(), "DROP TABLE AH; --", {"sql": "DELETE FROM AH"})
    assert out["ok"] is False
    assert "Bilinmeyen şablon" in out["error"]
    assert "DROP TABLE AH; --" not in HISTORY_TEMPLATES


def test_history_templates_are_closed_set():
    assert "top_failed_objects" in HISTORY_TEMPLATES
    assert "sql" not in HISTORY_TEMPLATES


# ── 2) sql_guard saldırı girdileri ────────────────────────────────────────

@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM dual /* DELETE FROM AH */",
    "SELECT 1 FROM dual -- DELETE FROM AH",
    "SELECT 1 FROM AH WHERE x=1 /*\nUPDATE AH SET AH_STATUS=1\n*/",
    "  SeLeCt 1 FROM dual; dElEtE FROM AH",
    "SELECT 1 FROM dual; UPDATE AH SET AH_STATUS=1",
    "dElEtE FROM AH",
    "SELECT DBMS_LOCK.SLEEP(10) FROM dual",
    "SELECT UTL_HTTP.REQUEST('http://x') FROM dual",
])
def test_sql_guard_blocks_comment_case_and_multi(sql):
    with pytest.raises(UnsafeSqlError):
        assert_read_only(sql)


def test_sql_guard_allows_select_with_plain_function():
    """SELECT fonksiyon() FROM dual — salt okunur SQL fonksiyon çağrısı izinli (EXECUTE grant yok)."""
    assert assert_read_only("SELECT fonksiyon() FROM dual") == "SELECT fonksiyon() FROM dual"
    assert assert_read_only("SELECT SYS_EXTRACT_UTC(SYSTIMESTAMP) FROM dual")


# ── 3) secret_enc ─────────────────────────────────────────────────────────

def test_secret_enc_fernet_from_secret_key_env():
    assert (os.environ.get("SECRET_KEY") or "").strip(), "SECRET_KEY ortam değişkeni gerekli"
    plain = "S3cr3t!Automic-Test"
    enc = encrypt_secret(plain)
    assert enc and enc != plain and is_encrypted(enc)
    assert decrypt_secret(enc) == plain
    from app.core import encryption as enc_mod
    from app.core import config as cfg_mod
    assert "Fernet" in open(enc_mod.__file__, encoding="utf-8").read()
    assert "SECRET_KEY" in open(cfg_mod.__file__, encoding="utf-8").read()
    assert "os.getenv" in open(cfg_mod.__file__, encoding="utf-8").read()


def test_redact_secrets_masks_password_in_errors():
    raw = "ORA-01017: user/S3cretPass@UC4DB logon denied password=S3cretPass"
    out = redact_secrets(raw)
    assert "S3cretPass" not in out
    assert "***" in out


# ── 4) test/discover: RBAC + rate limit ───────────────────────────────────

def test_probe_endpoints_require_operator_integrations_not_viewer_only():
    """Admin-only değil: integrations + operator. Bağımlılık fonksiyonu bunu zorunlu kılar."""
    import inspect
    from app.api import automation as api

    assert "_require_operator_integrations" in inspect.getsource(api.test_connection_ep)
    assert "_require_operator_integrations" in inspect.getsource(api.discover_ep)
    dep_src = inspect.getsource(api._require_operator_integrations)
    assert "integrations" in dep_src and "operator" in dep_src


def test_source_probe_rate_limit_trips(monkeypatch):
    monkeypatch.setattr("app.services.automic.guard.get_redis", lambda: None)
    guard._probe_hits.clear()
    uid = 99001
    for _ in range(10):
        guard.check_source_probe_rate(uid, ip="127.0.0.1", limit=10, window_sec=60)
    with pytest.raises(SourceError) as ei:
        guard.check_source_probe_rate(uid, ip="127.0.0.1", limit=10, window_sec=60)
    assert ei.value.code == "rate_limited"


def test_probe_guard_maps_rate_limit_to_http_429(monkeypatch):
    from app.api.automation import _probe_guard

    user = MagicMock(id=42)
    req = MagicMock()

    def _boom(*_a, **_k):
        raise SourceError("çok fazla", code="rate_limited")

    monkeypatch.setattr("app.services.automic.guard.check_source_probe_rate", _boom)
    monkeypatch.setattr("app.api.automation.client_ip", lambda r: "1.2.3.4")
    with pytest.raises(HTTPException) as ei:
        _probe_guard(req, user)
    assert ei.value.status_code == 429