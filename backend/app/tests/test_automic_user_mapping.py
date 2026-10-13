"""Kullanıcı eşlemesi: client join, silinmiş/bilinmeyen, ad değişikliği, wildcard, mismatch."""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from app.services.automic import users as u


def test_format_deleted_and_unknown():
    assert u.format_user_display(
        user_idnr=7, name="BATCH", department="OPS", delete_flag=1, found=True,
    ) == "BATCH/OPS (silinmiş)"
    assert u.format_user_display(user_idnr=99, found=False) == "bilinmeyen kullanıcı (ID: 99)"
    assert u.format_user_display(
        user_idnr=1, name="A", department="B", delete_flag=0, found=True,
    ) == "A/B"


def test_parse_user_search_dept_wildcard():
    assert u.parse_user_search_pattern("*/FIN") == (None, "FIN")
    assert u.parse_user_search_pattern("BATCH/*") == ("BATCH", None)
    assert u.parse_user_search_pattern("BATCH/OPS") == ("BATCH", "OPS")
    assert u.parse_user_search_pattern("batch") == ("batch", None)


def test_lookup_users_requires_client():
    db = MagicMock()
    with pytest.raises(ValueError, match="client zorunlu"):
        u.lookup_users(db, 1, [(None, 7)])
    # uid yokken client None sorun değil
    assert u.require_client_pairs([(None, None), (100, 7)]) == [(100, 7)]


def test_mismatch_warning_threshold():
    ok = [{"user_idnr": i, "_user_id_matched": True} for i in range(20)]
    assert u.mismatch_warning(ok, threshold=0.05) is None
    bad = ok[:18] + [{"user_idnr": 99, "_user_id_matched": False} for _ in range(2)]
    # 2/20 = 10% > 5%
    msg = u.mismatch_warning(bad, threshold=0.05)
    assert msg and "eşleşmeme" in msg and "doğrulanacak" in msg
    assert u.mismatch_warning(bad, threshold=0.15) is None


def test_split_oh_user_name():
    assert u.split_oh_user_name("BATCH/OPS") == ("BATCH", "OPS")
    assert u.split_oh_user_name("ADMIN") == ("ADMIN", None)


def test_enrich_sets_user_idnr_and_match_flag():
    from app.services.automic.source import oracle
    from app.tests.test_automic_official_schema import _StubOracle

    oracle._name_cache.clear()
    oracle._home_cache.clear()
    src, _ = _StubOracle.build({
        "FROM UC4.OH": [
            (7, "BATCH/OPS", "USER", 100, 0),
            (10, "TEAM", "FOLD", 100, 0),
            (11, "PROD", "FOLD", 100, 0),
        ],
        "FROM UC4.OFS": [(500, 10), (10, 11)],
    })
    out = src._enrich_runs([
        {"run_id": 1, "client": 100, "user_id": 7, "object_id": 500},
        {"run_id": 2, "client": 100, "user_id": 999, "object_id": None},
        {"run_id": 3, "client": 200, "user_id": 7, "object_id": None},  # client uyuşmazlığı
    ])
    assert out[0]["user_idnr"] == 7 and out[0]["user_name_at_run"] == "BATCH/OPS"
    assert out[0]["_user_id_matched"] is True
    assert out[1]["_user_id_matched"] is False and out[1]["user_idnr"] == 999
    assert out[2]["_user_id_matched"] is False  # OH client 100 ≠ run client 200


def test_users_query_template_no_live_filter():
    from app.services.automic.source import templates
    from app.services.automic.source.base import USER_HEADER_FIELDS
    from app.tests.test_automic_official_schema import _full_mapping

    prof, mapping = _full_mapping()
    sql = templates.render(
        prof, "object_headers_users_by_id_range", schema="UC4",
        table_map=mapping["object_headers"], fields=list(USER_HEADER_FIELDS),
        clients_bind=":c0", limit=100,
    )
    compact = sql.upper().replace(" ", "")
    assert "OH_OTYPE='USER'" in compact
    assert "OH_IDNR" in sql.upper()
    assert "DELETEFLAG=0" not in compact  # silinmişler de gelsin


def _adb_system():
    from app.services.automic.database import ensure_schema, get_automic_thread_session
    from app.services.automic.service import resolve_system

    try:
        ensure_schema()
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


def test_sync_users_and_search_wildcard_dept():
    from app.models.automic import AutomicUser
    from app.services.automic import queries as q
    from app.services.automic.source.factory import build_source
    from app.services.automic.users import sync_users_chunk

    adb, system = _adb_system()
    try:
        with build_source(system) as src:
            bounds = src.user_object_id_bounds(list(system.clients or []))
            assert bounds
            res = sync_users_chunk(
                adb, system, src, id_min=bounds[0], id_max=bounds[1] + 1, limit=500)
        assert res.get("ok") and res.get("upserted", 0) + res.get("unchanged", 0) > 0
        # client ayrımı: aynı ad farklı client
        u100 = adb.query(AutomicUser).filter_by(
            system_id=system.id, client=100, name="BATCH", department="OPS").first()
        u200 = adb.query(AutomicUser).filter_by(
            system_id=system.id, client=200, name="BATCH", department="OPS").first()
        if u100 and u200:
            assert u100.user_idnr != u200.user_idnr
        # silinmiş
        gone = adb.query(AutomicUser).filter_by(system_id=system.id, name="GONE").first()
        if gone:
            assert gone.delete_flag == 1
            assert "(silinmiş)" in u.format_user_display(
                user_idnr=gone.user_idnr, name=gone.name, department=gone.department,
                delete_flag=gone.delete_flag, found=True)
        # wildcard + departman
        hits = u.search_users(adb, system.id, list(system.clients or []), "*/OPS", limit=20)
        assert hits and all((h.get("department") or "").upper() == "OPS" for h in hits)
        hits2 = u.search_users(adb, system.id, list(system.clients or []), "batch*", limit=20)
        assert hits2 and any("BATCH" in (h["full_name"] or "").upper() for h in hits2)
        # bilinmeyen ad → öneri
        miss = q.search_by_username(adb, system, user="olmayan.xyz", range_="24h")
        assert miss["total"] == 0 and miss.get("hint", {}).get("known_users") is not None
        # ad değişikliği yansır
        if u100:
            old = u100.name
            u100.name = "BATCHREN"
            adb.commit()
            disp = u.resolve_user_display(
                adb, system.id, 100, u100.user_idnr, user_name_at_run="BATCH/OPS")
            assert disp and "BATCHREN" in disp
            u100.name = old
            adb.commit()
        # bilinmeyen ID
        assert u.resolve_user_display(adb, system.id, 100, 999999) == "bilinmeyen kullanıcı (ID: 999999)"
    finally:
        adb.close()


def test_client_join_in_attach_display():
    """Join her zaman (client, user_idnr) ile — client'sız id reddedilir."""
    adb, system = _adb_system()
    try:
        with pytest.raises(ValueError, match="client zorunlu"):
            u.lookup_users(adb, system.id, [(None, 7001)])
        items = [{"client": None, "user_idnr": 7001, "user_name_at_run": "X"}]
        u.attach_user_displays(adb, system.id, items)
        assert "bilinmeyen" in (items[0]["user"] or "")
    finally:
        adb.close()
