"""Kullanıcı ADI ile çalışma bulma — yalnız modül DB; kaynak LIKE/USR_Idnr kaldırıldı."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from app.services.automic import chat_support
from app.services.automic.source import templates
from app.services.automic.source.base import EXECUTION_FIELDS, SourceError
from app.tests.test_automic_official_schema import _full_mapping


def test_user_source_templates_removed_runid_filter():
    prof, mapping = _full_mapping()
    qs = prof.get("queries") or {}
    assert "user_objects_by_name" not in qs and "ended_by_users" not in qs
    sql = templates.render(
        prof, "ended_executions", schema="UC4", table_map=mapping["executions"],
        fields=list(EXECUTION_FIELDS), clients_bind=":c0", limit=100,
    )
    assert ":id_min" in sql and ":id_max" in sql
    assert "FETCH FIRST" in sql.upper()
    where = sql.upper().split("WHERE", 1)[-1]
    assert "TIMESTAMP4" not in where and "TIMESTAMP1" not in where


def test_oracle_find_users_removed():
    from app.services.automic.source import oracle

    prof, mapping = _full_mapping()
    src = oracle.OracleSource(992, {"user": "x"}, "y", {}, {"mapping": mapping, "schema": "UC4", "features": {}})
    with pytest.raises(SourceError) as ei:
        src.find_users("x")
    assert ei.value.code == "capability_removed"
    with pytest.raises(SourceError):
        src.fetch_runs_by_users([1], [100], datetime.now(timezone.utc), datetime.now(timezone.utc), limit=1)


def test_fake_source_user_lookup_removed():
    from app.services.automic.source.fake import FakeSource

    src = FakeSource(1, {}, None, {}, {})
    with pytest.raises(SourceError) as ei:
        src.find_users("batch")
    assert ei.value.code == "capability_removed"


@pytest.mark.parametrize("msg,user", [
    ("ahmet kullanıcısının son 7 gün çalıştırdığı joblar", "ahmet"),
    ("BATCH/OPS tarafından çalışan işler", "BATCH/OPS"),
    ("kullanıcı sched/auto hatalı joblar", "sched/auto"),
    ("user admin ne çalıştırdı", "admin"),
    ("kullanıcı OPS_BATCH son 3 günde ne çalıştırdı", "OPS_BATCH"),
    ("hangi kullanıcı hata aldı", None),
    ("kullanıcı bilgisi nerede", None),
    ("dün gece hata alan joblar", None),
])
def test_detect_user(msg, user):
    assert chat_support.detect_user(msg) == user


def test_plan_routes_user_questions():
    plan = chat_support.plan_fallback("ahmet kullanıcısının son 7 gün çalıştırdığı joblar")
    assert plan[0][0] == "automic_search_executions"
    assert plan[0][1]["user"] == "ahmet" and plan[0][1]["range"] == "7d"
    plan = chat_support.plan_fallback("BATCH/OPS tarafından şu an çalışan işler")
    assert [p[0] for p in plan] == ["automic_search_executions", "automic_active"]
    assert chat_support.plan_fallback("en çok iş çalıştıran kullanıcı kim")[0][1]["template_id"] == "user_activity"


def _adb_system():
    from app.services.automic.database import get_automic_thread_session
    from app.services.automic.service import resolve_system

    try:
        adb = get_automic_thread_session()
    except Exception:
        adb = None
    if adb is None:
        pytest.skip("Automic modül DB yok")
    try:
        system = resolve_system(adb, None)
    except Exception:
        adb.close()
        pytest.skip("Automic modül DB okunamıyor")
    if system is None or system.source_type != "fake":
        adb.close()
        pytest.skip("DEV-FAKE sistemi yok")
    return adb, system


def test_search_by_username_module_db_partial_name():
    from app.services.automic import queries as q
    from app.services.automic.database import ensure_schema
    from app.services.automic.source.factory import build_source
    from app.services.automic.users import sync_users_chunk

    ensure_schema()
    adb, system = _adb_system()
    try:
        with build_source(system) as src:
            b = src.user_object_id_bounds(list(system.clients or []))
            if b:
                sync_users_chunk(adb, system, src, id_min=b[0], id_max=b[1] + 1, limit=500)
        res = q.search_by_username(adb, system, user="batch", range_="24h", limit=5)
        assert res["data_source"] == "module_db" and res["live_lookup_performed"] is False
        if res["total"] > 0:
            # güncel ad join; silinmiş etiketi olmamalı
            assert all("BATCH" in (i.get("user") or "") for i in res["items"])
        miss = q.search_by_username(adb, system, user="olmayan.kisi", range_="24h")
        assert miss["total"] == 0 and miss.get("hint")
    finally:
        adb.close()


def test_search_by_username_live_ignored():
    """live=True kaynak araması yapmaz — modül DB kalır."""
    from app.services.automic import queries as q

    adb, system = _adb_system()
    try:
        res = q.search_by_username(adb, system, user="uc4/admin", range_="2h", limit=10, live=True)
        assert res["data_source"] == "module_db"
        assert res["live_lookup_performed"] is False
        assert "source_live" not in (res.get("data_source") or "")
    finally:
        adb.close()


def test_user_activity_template_and_active_filter():
    from app.services.automic import queries as q

    adb, system = _adb_system()
    try:
        # Fake veri sabit tarihli: "son 24 saat" gerçek saat ilerleyince boşalır → saati verinin sonuna sabitle
        from sqlalchemy import text as _t
        from datetime import timedelta
        from app.services.automic import clock
        last = adb.execute(_t("SELECT max(end_time) FROM automic_executions WHERE system_id = :s"),
                           {"s": system.id}).scalar()
        clock.set_now(last + timedelta(minutes=5) if last else None)
        try:
            res = q.run_history(adb, system, "user_activity", {"range": "24h", "limit": 5})
        finally:
            clock.set_now(None)
        assert res["ok"] and res["rows"]
        assert {"user", "runs", "failed", "cancelled", "active_now"} <= set(res["rows"][0])
        act = q.active_executions(adb, system, user="batch")
        assert all("BATCH" in (i["user"] or "") for i in act["items"]) if act["items"] else True
    finally:
        adb.close()


def test_tools_end_to_end_user_questions():
    from app.services.agent.tools import TOOLS

    adb, system = _adb_system()
    adb.close()
    ctx = {"platform": "automic", "domains": {"automic"}, "automic_system_id": system.id}
    res = TOOLS["automic_search_executions"].direct_handler(None, {"user": "ops", "range": "6h", "limit": 3}, ctx)
    assert res.get("ok", True) is not False
    res = TOOLS["automic_history"].direct_handler(None, {"template_id": "user_activity", "range": "24h"}, ctx)
    assert res.get("rows") is not None


@pytest.mark.parametrize("msg,tool,key", [
    ("en çok iş çalıştıran kullanıcı kim?", "automic_history", "user_activity"),
    ("hangi kullanıcının işleri en çok hata aldı son 7 günde?", "automic_history", "user_activity"),
    ("uc4 entegrasyon durumu ve kaynak gecikmesi", "automic_status", None),
    ("son 7 günün hata trendi", "automic_history", "failure_trend"),
    ("şu an çalışan işler hangileri", "automic_active", None),
    ("29859310102 RunID'sini kim çalıştırdı", "automic_execution", None),
])
def test_plan_other_custom_questions(msg, tool, key):
    plan = chat_support.plan_fallback(msg)
    assert plan[0][0] == tool
    if key:
        assert plan[0][1]["template_id"] == key


def test_plan_user_failed_filter():
    plan = chat_support.plan_fallback("sched/auto kullanıcısının hatalı joblarını listele")
    assert plan[0][1]["user"] == "sched/auto" and plan[0][1]["status_class"] == "failed"


def test_rag_query_terms_and_bonus():
    from app.services.automic import knowledge as k

    t = k.query_terms("EH_Signal değeri 2 ne demek? MRT ve 1801")
    assert "EH_Signal" in t["idents"] and "MRT" in t["acronyms"] and "1801" in t["numbers"]
    hit = "EH_Signal bitmask: 2 MRT aşıldı"
    miss = "OpenShift machine config pool"
    assert k.lexical_bonus(hit, t) > k.lexical_bonus(miss, t) == 0


@pytest.mark.parametrize("q,must", [
    ("AH_USR_Idnr nedir, kullanıcı adı nereden geliyor?", "AH_USR_Idnr"),
    ("EH_Signal değeri 2 ne demek?", "EH_Signal"),
    ("1801 ve 1850 durum kodları ne anlama geliyor?", "1850"),
    ("RT_Content boşsa rapor satırı nasıl okunur?", "RT_MsgInsert"),
    ("OH_DeleteFlag değerleri ne anlama geliyor?", "OH_DeleteFlag"),
    ("kullanıcı adıyla job nasıl bulunur?", "OH_OType"),
    ("EH_ERTCalc 3 ne demek?", "EH_ERTCalc"),
])
def test_rag_returns_automic_chunks(q, must):
    import asyncio

    from app.services.automic.knowledge import automic_rag_context

    try:
        ctx = asyncio.run(automic_rag_context(q))
    except Exception:
        pytest.skip("RAG yok")
    if not ctx:
        pytest.skip("RAG Automic parçaları yüklü değil")
    assert must.lower() in ctx.lower()
    assert "[AUTOMIC-" in ctx and "OCP-" not in ctx


def test_tool_live_flag_ignored(monkeypatch):
    from app.services.agent import tools_automic
    from app.services.automic import queries as q

    seen = {}

    def fake_by_user(adb, system, *, user, live=None, **kw):
        seen["live"] = live
        return {"ok": True, "total": 0, "items": [], "data_source": "module_db", "live_lookup_performed": False}

    monkeypatch.setattr(q, "search_by_username", fake_by_user)
    adb, system = _adb_system()
    adb.close()
    ctx = {"platform": "automic", "domains": {"automic"}, "automic_system_id": system.id}
    tools_automic._search(None, {"user": "x", "client": 0, "limit": 100}, ctx)
    assert "live" in seen


@pytest.mark.parametrize("msg,expected", [
    ("EH_Signal değeri 2 ne demek ve nereden okunuyor?", True),
    ("ERT nedir, hangi tablo ve kolondan okunuyor?", True),
    ("1801 ve 1850 durum kodları ne anlama geliyor?", True),
    ("MRT ile SRT arasındaki fark nedir?", True),
    ("son 7 günde hata veren jobların hata kodu ne demek", False),
    ("29859310102 RunID'si ne demek", False),
    ("BATCH/OPS kullanıcısı ne çalıştırdı", False),
    ("dün gece hata alan joblar", False),
])
def test_is_knowledge_question(msg, expected):
    assert chat_support.is_knowledge_question(msg) is expected
