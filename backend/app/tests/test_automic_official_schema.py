"""Automic SQL profili resmi Broadcom AE DB şemasına (TechDocs 24.4) bağlı kalmalı.

Profil yalnızca `source/sql/official/ae-24.4-columns.yaml` içindeki kolonları kullanabilir;
kodda olup YAML'da olmayan kolon → test kırılır. Yerel kopya: `docs/official/24.4/`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Set

import pytest
import yaml

from app.services.automic.classify import ACTIVE_STATUS_GROUPS, active_state
from app.services.automic.source import templates
from app.services.automic.source.base import ACTIVE_FIELDS, EXECUTION_FIELDS, OBJECT_HEADER_FIELDS

_OFFICIAL = Path(templates.__file__).parent / "sql" / "official" / "ae-24.4-columns.yaml"


def _official_columns() -> Dict[str, Set[str]]:
    data = yaml.safe_load(_OFFICIAL.read_text(encoding="utf-8"))
    assert data.get("version") == "24.4"
    out: Dict[str, Set[str]] = {}
    for t, spec in data["tables"].items():
        cols = spec["columns"] if isinstance(spec, dict) else {}
        out[t.upper()] = {c.upper() for c in cols}
    return out


def _profile_columns() -> Dict[str, Set[str]]:
    prof = templates.load_profile("oracle", "ae-24")
    out: Dict[str, Set[str]] = {}
    for spec in prof["tables"].values():
        t = spec["table"][0].upper()
        for kind in ("required", "optional"):
            for cands in (spec.get(kind) or {}).values():
                out.setdefault(t, set()).add(cands[0].upper())
    return out


def test_official_yaml_is_24_4_and_has_doc_refs():
    data = yaml.safe_load(_OFFICIAL.read_text(encoding="utf-8"))
    assert data["version"] == "24.4"
    assert data.get("accessed") == "2026-10-10"
    for t, spec in data["tables"].items():
        assert spec["doc"].endswith(f"/{t}.md") or spec["doc"].endswith(f"{t}.md")
        assert "24-4" in spec["url"]
        for name, meta in spec["columns"].items():
            assert meta.get("description"), f"{t}.{name} description boş"
            assert "docs/official/24.4/" in meta.get("doc", "")


def test_profile_uses_only_official_columns():
    """Kodda (profilde) olup YAML'da olmayan kolon → kırılır."""
    off = _official_columns()
    prof = templates.load_profile("oracle", "ae-24")
    bad: List[str] = []
    for lname, spec in prof["tables"].items():
        for t in spec["table"]:
            t = t.upper()
            assert t in off, f"{lname}: {t} resmi 24.4 SELECT listesinde yok"
            for kind in ("required", "optional"):
                for field, cands in (spec.get(kind) or {}).items():
                    for c in cands:
                        if c.upper() not in off[t]:
                            bad.append(f"{t}.{c} ({lname}.{field})")
    assert not bad, f"Kodda olup ae-24.4-columns.yaml'da olmayan kolonlar: {bad}"


def test_yaml_columns_match_profile_exactly():
    """YAML yalnızca SELECT edilen kolonları tutar — fazla/eksik olmamalı."""
    off, prof = _official_columns(), _profile_columns()
    assert set(off) == set(prof), f"tablo farkı off-prof={set(off)-set(prof)} prof-off={set(prof)-set(off)}"
    for t in off:
        assert off[t] == prof[t], f"{t}: yaml-only={off[t]-prof[t]} code-only={prof[t]-off[t]}"


def test_profile_does_not_use_invented_columns():
    prof = templates.load_profile("oracle", "ae-24")
    used = {c.upper() for spec in prof["tables"].values()
            for kind in ("required", "optional") for cands in (spec.get(kind) or {}).values() for c in cands}
    for invented in ("AH_USRNAME", "AH_USR", "AH_FOLDER", "AH_QUEUENAME", "AH_HOSTNAME", "AH_HOSTTYPE",
                     "AH_PLATFORM", "OH_FOLDER", "OH_CRUSER", "OH_CRUSR", "OH_MODUSER", "OH_MODUSR",
                     "OH_MODIFIED", "RT_CLIENT", "EH_TIMESTAMP1", "EH_TIMESTAMP2", "EH_HOSTNAME",
                     "JPP_OBJECTNAME", "JPP_NAME", "JPP_ONAME"):
        assert invented not in used


def test_profile_maps_official_user_and_ert_columns():
    prof = templates.load_profile("oracle", "ae-24")
    ex, act = prof["tables"]["executions"]["optional"], prof["tables"]["active"]["optional"]
    assert ex["user_id"] == ["AH_USR_IDNR"] and ex["ert_sec"] == ["AH_ERT"]
    assert ex["platform"] == ["AH_HOSTATTRTYPED"] and ex["queue"] == ["AH_QUEUE"]
    assert act["ert_end_time"] == ["EH_ERTEND"] and act["signal"] == ["EH_SIGNAL"]
    assert prof["tables"]["folders"]["table"] == ["OFS"]


def _full_mapping():
    prof = templates.load_profile("oracle", "ae-24")
    cols: Dict[str, set] = {}
    for spec in prof["tables"].values():
        t = spec["table"][0].upper()
        for kind in ("required", "optional"):
            for cands in (spec.get(kind) or {}).values():
                cols.setdefault(t, set()).add(cands[0].upper())
    return prof, templates.resolve_mapping(prof, cols)


def test_live_filter_added_only_when_delete_flag_mapped():
    prof, mapping = _full_mapping()
    sql = templates.render(prof, "object_header_by_name", schema="UC4",
                           table_map=mapping["object_headers"], fields=list(OBJECT_HEADER_FIELDS), limit=1)
    assert "OH_DELETEFLAG = 0" in sql
    no_flag = dict(mapping["object_headers"], columns={k: v for k, v in mapping["object_headers"]["columns"].items()
                                                       if k != "delete_flag"})
    sql2 = templates.render(prof, "object_header_by_name", schema="UC4", table_map=no_flag,
                            fields=list(OBJECT_HEADER_FIELDS), limit=1)
    assert "DELETEFLAG" not in sql2


def test_script_query_orders_by_ot_type():
    prof, mapping = _full_mapping()
    sql = templates.render(prof, "object_script_lines", schema="UC4", table_map=mapping["object_scripts"])
    assert "ORDER BY OT_TYPE, OT_LNR" in sql


def test_folder_query_only_home_folder():
    prof, mapping = _full_mapping()
    sql = templates.render(prof, "folder_links_by_objects", schema="UC4", table_map=mapping["folders"],
                           ids_bind=":i0, :i1")
    assert "OFS_LINK = 0" in sql and "OFS_OH_IDNR_O IN (:i0, :i1)" in sql


def test_fields_are_logical_not_invented_columns():
    assert "user_id" in EXECUTION_FIELDS and "user" not in EXECUTION_FIELDS
    assert "folder" not in EXECUTION_FIELDS and "object_id" in EXECUTION_FIELDS
    assert {"ert_sec", "ert_end_time", "signal"} <= set(ACTIVE_FIELDS)


# ── aktif durum grupları (DOĞRULANMADI – 24.4 Task Status sayfası bulunamadı) ──

@pytest.mark.parametrize("code,state", [
    (1550, "running"), (1300, "running"), (1701, "running"), (1600, "running"), (1593, "running"),
    (1700, "waiting"), (1301, "waiting"), (1681, "waiting"), (1711, "waiting"), (1655, "waiting"),
    (1560, "blocked"), (1564, "blocked"), (1544, "blocked"), (1898, "blocked"),
    (1599, "other"), (1800, "other"), (None, "unknown"),
])
def test_active_state_groups(code, state):
    assert active_state(code) == state


def test_active_groups_disjoint():
    names = list(ACTIVE_STATUS_GROUPS)
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            assert not (ACTIVE_STATUS_GROUPS[a] & ACTIVE_STATUS_GROUPS[b]), (a, b)


# ── OracleSource kullanıcı/klasör çözümleme (DB'siz) ──

class _StubOracle:
    """OracleSource'u bağlantısız çalıştırmak için _query'yi taklit eder."""

    @staticmethod
    def build(rows_by_marker: Dict[str, list]):
        from app.services.automic.source import oracle

        prof, mapping = _full_mapping()
        src = oracle.OracleSource(991, {"user": "x"}, "y", {}, {"mapping": mapping, "schema": "UC4",
                                                              "features": {"objects": True}})
        calls: List[str] = []

        def fake_query(sql, binds=None, *, kind="collector", max_rows=None):
            calls.append(sql)
            for marker, rows in rows_by_marker.items():
                if marker in sql:
                    return rows
            return []

        src._query = fake_query  # type: ignore[assignment]
        return src, calls


def test_enrich_runs_resolves_user_and_folder_path():
    from app.services.automic.source import oracle

    oracle._name_cache.clear()
    oracle._home_cache.clear()
    src, calls = _StubOracle.build({
        "FROM UC4.OFS": [(500, 10), (10, 11)],            # nesne 500 → klasör 10 → üst klasör 11
        "FROM UC4.OH": [(7, "BATCH/OPS", "USER", 0), (10, "TEAM", "FOLD", 100), (11, "PROD", "FOLD", 100)],
    })
    rows = [
        {"run_id": 1, "client": 0, "user_id": 7, "object_id": 500},
        {"run_id": 2, "client": 0, "user_id": None, "object_id": None},
    ]
    out = src._enrich_runs(rows)
    assert out[0]["user"] == "BATCH/OPS" and out[0]["user_idnr"] == 7
    assert out[0]["user_name_at_run"] == "BATCH/OPS"
    assert out[0]["folder"] == "/PROD/TEAM"
    assert out[1]["user"] is None and out[1]["folder"] is None
    n = len(calls)
    src._enrich_runs([{"run_id": 3, "user_id": 7, "object_id": 500}])
    assert len(calls) == n


def test_enrich_survives_source_error():
    from app.services.automic.source import oracle
    from app.services.automic.source.base import SourceError

    oracle._name_cache.clear()
    oracle._home_cache.clear()
    src, _ = _StubOracle.build({})

    def boom(*a, **k):
        raise SourceError("zaman aşımı", code="call_timeout")

    src._query = boom  # type: ignore[assignment]
    out = src._enrich_runs([{"run_id": 1, "user_id": 9, "object_id": 9}])
    assert out[0]["user"] is None and out[0]["folder"] is None


def test_script_sections_and_report_message_records():
    from app.services.automic.source import oracle

    src, _ = _StubOracle.build({
        "OT_TYPE": [(0, 1, ":PRINT a"), (0, 2, ":PRINT b"), (1, 1, ":SET &X# = 1"), (2, 1, ":PRINT done")],
    })
    src.capability = {"features": {"versions": True}}
    lines = src.fetch_object_script(5)
    assert lines[:2] == [":PRINT a", ":PRINT b"]
    assert any("Pre-Process (OT_Type=1)" in ln for ln in lines)
    assert any("Post-Process (OT_Type=2)" in ln for ln in lines)
    assert lines.index(":SET &X# = 1") < lines.index(":PRINT done")


def test_fake_source_provides_official_metrics():
    from app.services.automic.source.fake import FakeSource
    from datetime import datetime, timedelta, timezone

    src = FakeSource(1, {"fake_clients": [100]}, None, {})
    now = datetime.now(timezone.utc)
    recs = src.fetch_ended_executions(
        [100], now - timedelta(hours=1), now, limit=50, id_min=0, id_max=10**15)
    assert recs and all("ert_sec" in r and "run_time_sec" in r for r in recs)
    act = src.fetch_active_executions([100], limit=20)
    assert act and all("ert_end_time" in a and "user" in a for a in act)
