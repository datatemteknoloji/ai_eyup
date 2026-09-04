"""Özel Rapor motoru (`app.services.custom_report_engine`) için birim testleri.

Kapsam:
  - `render_tool_result`: tool sonucu → markdown/json/brief render (kind'a bağımsız)
  - `is_capturable_tool`: hangi tool'ların "dondurulabilir" olduğu
  - `execute_definition`: kayıtlı bir tanımı deterministik yeniden çalıştırma
    (READ_ONLY + direct_handler zorunluluğu, virt inventory formatter fallback'i)
"""
import json

import pytest

from app.services import custom_report_engine as engine
from app.services.chat_output_directives import OutputDirective


class _FakeDefinition:
    def __init__(self, id=1, tool_name="db_list_vms", tool_args=None, platform="virt",
                 output_directive="table"):
        self.id = id
        self.tool_name = tool_name
        self.tool_args = tool_args or {}
        self.platform = platform
        self.output_directive = output_directive


# ── coerce_directive ─────────────────────────────────────────────────────────

def test_coerce_directive_valid_and_invalid():
    assert engine.coerce_directive("json") == OutputDirective.JSON
    assert engine.coerce_directive("TABLE") == OutputDirective.TABLE
    assert engine.coerce_directive(None) == OutputDirective.NONE
    assert engine.coerce_directive("bogus") == OutputDirective.NONE
    assert engine.coerce_directive(OutputDirective.BRIEF) == OutputDirective.BRIEF


# ── render_tool_result ───────────────────────────────────────────────────────

def test_render_tool_result_table_default():
    result = {
        "ok": True,
        "count": 2,
        "as_of": "2026-01-01T00:00:00",
        "vms": [
            {"name": "vm1", "disk_gb": 100},
            {"name": "vm2", "disk_gb": 50},
        ],
    }
    out = engine.render_tool_result(result, OutputDirective.TABLE)
    assert "| name | disk_gb |" in out or "name" in out
    assert "vm1" in out and "vm2" in out
    assert "as_of=" in out


def test_render_tool_result_json_directive():
    result = {"ok": True, "hosts": [{"name": "esx1"}, {"name": "esx2"}]}
    out = engine.render_tool_result(result, OutputDirective.JSON)
    assert out.startswith("```json")
    payload = json.loads(out.strip("`").split("json", 1)[1].strip())
    assert payload["count"] == 2


def test_render_tool_result_brief_directive():
    result = {"ok": True, "nodes": [{"name": "n1"}, {"name": "n2"}, {"name": "n3"}]}
    out = engine.render_tool_result(result, OutputDirective.BRIEF)
    assert "toplam 3" in out
    assert len(out.splitlines()) <= 3


def test_render_tool_result_error():
    result = {"ok": False, "error": "bağlantı hatası"}
    out = engine.render_tool_result(result, OutputDirective.TABLE)
    assert "hata" in out.lower()
    assert "bağlantı hatası" in out


def test_render_tool_result_no_row_list_falls_back_to_json():
    result = {"ok": True, "summary": "sadece metin, liste yok"}
    out = engine.render_tool_result(result, OutputDirective.TABLE)
    assert out.startswith("```json")


def test_render_tool_result_non_dict():
    out = engine.render_tool_result("plain string", OutputDirective.TABLE)
    assert "plain string" in out


# ── is_capturable_tool ───────────────────────────────────────────────────────

def test_is_capturable_tool_true_for_db_list_vms():
    assert engine.is_capturable_tool("db_list_vms") is True


def test_is_capturable_tool_false_for_unknown():
    assert engine.is_capturable_tool("does_not_exist_tool") is False


def test_is_capturable_tool_false_for_ssh_bound_tool():
    # SSH tabanlı tanı araçları (belirli bir sunucuya bağlı, direct_handler yok)
    # özel rapor için desteklenmemeli.
    assert engine.is_capturable_tool("get_system_summary") is False


# ── execute_definition ───────────────────────────────────────────────────────

def test_execute_definition_unknown_tool_returns_error(db_session=None):
    defn = _FakeDefinition(tool_name="does_not_exist_tool")
    out = engine.execute_definition(None, defn)
    assert out["ok"] is False
    assert "bulunamadı" in out["error"]


def test_execute_definition_rejects_non_capturable_tool():
    defn = _FakeDefinition(tool_name="get_system_summary")
    out = engine.execute_definition(None, defn)
    assert out["ok"] is False
    assert "desteklenmiyor" in out["error"]


def test_execute_definition_uses_inventory_formatter_for_db_list_vms(monkeypatch):
    from app.services.agent import tools as tool_mod

    fake_result = {
        "ok": True, "as_of": "2026-01-01T00:00:00", "vms": [
            {"name": "vm1", "disk_gb": 10, "disk_count": 1},
        ],
    }
    tool = tool_mod.get_tool("db_list_vms")
    monkeypatch.setattr(tool, "execute", lambda db, args, ctx: fake_result)

    defn = _FakeDefinition(
        tool_name="db_list_vms",
        tool_args={"include_disks": True, "fields": ["name", "disk_gb"]},
        output_directive="table",
    )
    out = engine.execute_definition(None, defn)
    assert out["ok"] is True
    assert "vm1" in out["rendered"]


def test_execute_definition_error_result_marks_not_ok(monkeypatch):
    from app.services.agent import tools as tool_mod

    tool = tool_mod.get_tool("db_list_vms")
    monkeypatch.setattr(tool, "execute", lambda db, args, ctx: {"ok": False, "error": "DB kapalı"})

    defn = _FakeDefinition(tool_name="db_list_vms", tool_args={})
    out = engine.execute_definition(None, defn)
    assert out["ok"] is False
    assert out["error"] == "DB kapalı"
