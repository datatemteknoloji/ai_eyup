"""Adım 8R (ikinci tur): lexical zaman/aday sınırı, incidents yaş bazlı budama (varsayılan KAPALI), eşik/ayar şeması."""
from __future__ import annotations

import inspect
import json
from contextlib import contextmanager
from pathlib import Path

import pytest

from app.services import rag_maintenance as rm
from app.services import rag_store as rs
from app.services import runtime_settings as rts


class _Res:
    def __init__(self, rows=None, rowcount=0):
        self._rows = rows or []
        self.rowcount = rowcount

    def fetchall(self):
        return self._rows

    def scalar(self):
        return self._rows[0][0] if self._rows else 0

    def __iter__(self):
        return iter(self._rows)


class _FakeConn:
    def __init__(self, log, rows=None, raise_on_select=None, delete_rowcount=0):
        self.log, self.rows, self.raise_on_select, self.delete_rowcount = log, rows or [], raise_on_select, delete_rowcount

    def execute(self, stmt, params=None):
        sql = str(getattr(stmt, "text", stmt))
        self.log.append((sql, params))
        if "set_config" in sql:
            return _Res()
        if "SELECT count(*) FROM rag_embeddings WHERE collection = :coll" in sql:
            return _Res([(10,)])
        if sql.strip().upper().startswith("DELETE"):
            return _Res(rowcount=self.delete_rowcount)
        if "FROM rag_embeddings" in sql and self.raise_on_select is not None and "SELECT id, document" in sql:
            raise self.raise_on_select
        return _Res(self.rows)

    def execution_options(self, **kw):
        return self


class _FakeEngine:
    def __init__(self, **kw):
        self.log = []
        self.kw = kw

    @contextmanager
    def begin(self):
        yield _FakeConn(self.log, **self.kw)

    @contextmanager
    def connect(self):
        yield _FakeConn(self.log, **self.kw)


class _PgTimeout(Exception):
    pgcode = "57014"


@pytest.fixture(autouse=True)
def _vector_ready(monkeypatch):
    monkeypatch.setattr(rs, "_ensure_vector_ready", lambda: True)


def _hit_row():
    return [("event_1", "doc", {"event_type": "vcenter_event"}, 0.5)]


# ── ayar şeması ──
def test_lexical_settings_in_schema_with_defaults():
    a = rts.ADVANCED_SCHEMA["rag_lexical_timeout_ms"]
    b = rts.ADVANCED_SCHEMA["rag_lexical_max_candidates"]
    assert a["default"] == 1500 and a["type"] == "int" and a["min"] == 0
    assert b["default"] == 2000 and b["type"] == "int" and b["min"] == 0


def test_retention_settings_default_off_and_60_days():
    assert rts.ADVANCED_SCHEMA["rag_incidents_retention_enabled"]["default"] is False
    assert rts.ADVANCED_SCHEMA["rag_incidents_retention_days"]["default"] == 60
    assert rts.ADVANCED_SCHEMA["rag_incidents_retention_days"]["min"] >= 1


def test_relevance_threshold_setting_still_exists_and_schema_default_off():
    # Eşik açma kararı DB ayarıyla verilir (kod varsayılanı KAPALI kalır)
    assert rts.ADVANCED_SCHEMA["rag_min_relevance_enabled"]["default"] is False


def test_lexical_limits_fallback_defaults(monkeypatch):
    monkeypatch.setattr(rts, "get_int", lambda k: {"rag_lexical_timeout_ms": 900, "rag_lexical_max_candidates": 50}[k])
    assert rs.lexical_limits() == (900, 50)


# ── lexical zaman / aday sınırı ──
def test_lexical_timeout_returns_empty_not_raise(monkeypatch):
    eng = _FakeEngine(raise_on_select=_PgTimeout("canceling statement due to statement timeout"))
    monkeypatch.setattr(rs, "engine", eng)
    monkeypatch.setattr(rs, "lexical_limits", lambda: (1500, 2000))
    monkeypatch.setattr(rs, "cached_collection_count", lambda c: 1_000_000)
    assert rs.lexical_search_collection("incidents", "vcenter alarm datastore") == []


def test_lexical_non_timeout_error_still_raises(monkeypatch):
    eng = _FakeEngine(raise_on_select=RuntimeError("bağlantı koptu"))
    monkeypatch.setattr(rs, "engine", eng)
    monkeypatch.setattr(rs, "lexical_limits", lambda: (1500, 2000))
    monkeypatch.setattr(rs, "cached_collection_count", lambda c: 1_000_000)
    with pytest.raises(RuntimeError):
        rs.lexical_search_collection("incidents", "x y")


def test_lexical_sets_statement_timeout_per_query(monkeypatch):
    eng = _FakeEngine(rows=_hit_row())
    monkeypatch.setattr(rs, "engine", eng)
    monkeypatch.setattr(rs, "lexical_limits", lambda: (1500, 0))
    monkeypatch.setattr(rs, "cached_collection_count", lambda c: 10)
    out = rs.lexical_search_collection("runbook", "ssh erişim")
    assert out and out[0]["source"] == "fts"
    cfg = [p for s, p in eng.log if "set_config" in s]
    assert cfg and cfg[0]["v"].endswith("ms") and int(cfg[0]["v"][:-2]) <= 1500


def test_lexical_timeout_zero_means_no_limit(monkeypatch):
    eng = _FakeEngine(rows=_hit_row())
    monkeypatch.setattr(rs, "engine", eng)
    monkeypatch.setattr(rs, "lexical_limits", lambda: (0, 0))
    monkeypatch.setattr(rs, "cached_collection_count", lambda c: 10)
    rs.lexical_search_collection("runbook", "ssh")
    assert not [1 for s, _ in eng.log if "set_config" in s]


def test_candidate_cap_only_on_large_collections(monkeypatch):
    big = _FakeEngine(rows=_hit_row())
    monkeypatch.setattr(rs, "engine", big)
    monkeypatch.setattr(rs, "lexical_limits", lambda: (1500, 2000))
    monkeypatch.setattr(rs, "cached_collection_count", lambda c: 1_100_000)
    rs.lexical_search_collection("incidents", "pod restart")
    sqls = [s for s, _ in big.log if "FROM rag_embeddings" in s or "FROM cand" in s]
    assert any("WITH cand AS MATERIALIZED" in s and "LIMIT :cand" in s for s in sqls)
    assert any(p and p.get("cand") == 2000 for _, p in big.log)

    small = _FakeEngine(rows=_hit_row())
    monkeypatch.setattr(rs, "engine", small)
    monkeypatch.setattr(rs, "cached_collection_count", lambda c: 13_986)
    rs.lexical_search_collection("runbook", "pod restart")
    assert not any("WITH cand" in s for s, _ in small.log)
    assert not any(p and "cand" in p for _, p in small.log)


def test_candidate_cap_zero_disables(monkeypatch):
    eng = _FakeEngine(rows=_hit_row())
    monkeypatch.setattr(rs, "engine", eng)
    monkeypatch.setattr(rs, "lexical_limits", lambda: (1500, 0))
    monkeypatch.setattr(rs, "cached_collection_count", lambda c: 1_100_000)
    rs.lexical_search_collection("incidents", "pod restart")
    assert not any("WITH cand" in s for s, _ in eng.log)


def test_hybrid_uses_vector_only_when_lexical_times_out(monkeypatch):
    vec = [{"id": "event_9", "document": "d", "metadata": {}, "distance": 0.1, "source": "vector"}]
    monkeypatch.setattr(rs, "query_collection", lambda *a, **k: list(vec))
    monkeypatch.setattr(rs, "lexical_search_collection", lambda *a, **k: [])
    out = rs.hybrid_search_collection("incidents", "pod", query_embedding=[0.1] * 4, n_results=5, code_rerank=False)
    assert [h["id"] for h in out] == ["event_9"]


def test_timeout_helper_detects_pgcode_and_message():
    assert rs._is_query_timeout(_PgTimeout("x"))
    assert rs._is_query_timeout(RuntimeError("canceling statement due to statement timeout"))
    assert not rs._is_query_timeout(RuntimeError("başka hata"))


def test_lexical_sql_keeps_module_filter(monkeypatch):
    eng = _FakeEngine(rows=_hit_row())
    monkeypatch.setattr(rs, "engine", eng)
    monkeypatch.setattr(rs, "lexical_limits", lambda: (1500, 2000))
    monkeypatch.setattr(rs, "cached_collection_count", lambda c: 1_100_000)
    rs.lexical_search_collection("incidents", "pod", modules=["linux"])
    assert any("metadata->>'module'" in s for s, _ in eng.log)


# ── retention (R4) ──
def test_retention_types_exclude_incident_and_alarms():
    assert "incident" not in rm.RETENTION_EVENT_TYPES
    for keep in ("vcenter_alarm", "vcenter_task", "virt_resource"):
        assert keep not in rm.RETENTION_EVENT_TYPES
    assert set(rm.RETENTION_EVENT_TYPES) == {"vcenter_event", "openshift_event", "openshift_virt_event", "log_entry", "virt_log"}
    assert rm.DEFAULT_RETENTION_DAYS == 60


def test_prune_default_is_dry_run_and_signature_safe():
    sig = inspect.signature(rm.prune_incidents_by_age)
    assert sig.parameters["dry_run"].default is True
    assert sig.parameters["days"].default == 60


def test_prune_dry_run_writes_nothing(monkeypatch):
    eng = _FakeEngine(rows=[("vcenter_event", 3, "2026-08-15", "2026-08-16", 300, 900)])
    import app.core.database as db
    monkeypatch.setattr(db, "engine", eng)
    called = []
    monkeypatch.setattr(rm, "backup_incidents_retention", lambda *a, **k: called.append(1))
    out = rm.prune_incidents_by_age(60)
    assert out["dry_run"] is True and out["would_delete"] == 3 and out["would_keep"] == 7
    assert not called
    assert not any(s.strip().upper().startswith("DELETE") for s, _ in eng.log)


def test_prune_real_run_requires_backup_path():
    with pytest.raises(ValueError):
        rm.prune_incidents_by_age(60, dry_run=False)


def test_prune_rolls_back_when_deleted_differs_from_backup(monkeypatch, tmp_path):
    import app.core.database as db
    eng = _FakeEngine(delete_rowcount=1)
    monkeypatch.setattr(db, "engine", eng)
    bp = tmp_path / "bk.jsonl"
    bp.write_text("".join(json.dumps({"id": f"event_{i}"}) + "\n" for i in range(3)), encoding="utf-8")
    monkeypatch.setattr(rm, "backup_incidents_retention", lambda *a, **k: {"path": str(bp), "rows": 3, "bytes": 1, "sha256": "x"})
    with pytest.raises(RuntimeError):
        rm.prune_incidents_by_age(60, dry_run=False, backup_path=str(bp))


def test_prune_deletes_only_ids_from_backup(monkeypatch, tmp_path):
    import app.core.database as db
    eng = _FakeEngine(delete_rowcount=2)
    monkeypatch.setattr(db, "engine", eng)
    bp = tmp_path / "bk.jsonl"
    bp.write_text("".join(json.dumps({"id": f"event_{i}"}) + "\n" for i in range(2)), encoding="utf-8")
    monkeypatch.setattr(rm, "backup_incidents_retention", lambda *a, **k: {"path": str(bp), "rows": 2, "bytes": 1, "sha256": "x"})
    out = rm.prune_incidents_by_age(60, dry_run=False, backup_path=str(bp))
    assert out["deleted"] == 2
    dels = [s for s, _ in eng.log if s.strip().upper().startswith("DELETE")]
    assert len(dels) == 1 and "_rag_prune_ids" in dels[0] and "collection" in dels[0]


def test_backup_refuses_to_overwrite(tmp_path):
    p = tmp_path / "x.jsonl"
    p.write_text("var", encoding="utf-8")
    with pytest.raises(FileExistsError):
        rm.backup_incidents_retention(str(p))


def test_backup_sql_excludes_embedding_column():
    src = inspect.getsource(rm.backup_incidents_retention)
    assert "SELECT id, document, metadata, created_at" in src
    assert "embedding," not in src.split("SELECT id, document, metadata, created_at")[0].split("text(")[-1]


def test_invalid_retention_days_rejected():
    with pytest.raises(ValueError):
        rm.plan_incidents_retention(0)


def test_job_disabled_does_nothing(monkeypatch):
    monkeypatch.setattr(rts, "get_bool", lambda k: False)
    called = []
    monkeypatch.setattr(rm, "prune_incidents_by_age", lambda *a, **k: called.append(1))
    assert rm.run_incidents_retention_job() == {"skipped": "disabled"}
    assert not called


def test_job_enabled_runs_real_prune_with_backup_and_cap(monkeypatch):
    monkeypatch.setattr(rts, "get_bool", lambda k: True)
    monkeypatch.setattr(rts, "get_int", lambda k: {"rag_incidents_retention_days": 60, "rag_maintenance_max_delete": 777}[k])
    seen = {}
    monkeypatch.setattr(rm, "plan_incidents_retention", lambda days, **k: {"would_delete": 5})
    monkeypatch.setattr(rm, "prune_incidents_by_age", lambda days, **k: seen.update(days=days, **k) or {"deleted": 0})
    rm.run_incidents_retention_job()
    assert seen["days"] == 60 and seen["dry_run"] is False and seen["limit"] == 777
    assert seen["backup_path"].startswith(rm.RETENTION_BACKUP_DIR)


def test_fleet_maintenance_calls_retention_hook_only_via_job():
    src = Path(inspect.getsourcefile(__import__("app.services.fleet_jobs", fromlist=["x"]))).read_text(encoding="utf-8")
    assert "run_incidents_retention_job" in src
    assert "prune_incidents_by_age" not in src  # silme yalnız ayar-kapılı iş üzerinden


def test_no_other_caller_prunes_incidents_by_age():
    root = Path(__file__).resolve().parents[1]
    offenders = []
    for p in root.rglob("*.py"):
        if "tests" in p.parts or p.name == "rag_maintenance.py":
            continue
        if "prune_incidents_by_age" in p.read_text(encoding="utf-8", errors="ignore"):
            offenders.append(str(p))
    assert not offenders


def test_job_enabled_but_nothing_to_delete_writes_no_backup(monkeypatch):
    monkeypatch.setattr(rts, "get_bool", lambda k: True)
    monkeypatch.setattr(rts, "get_int", lambda k: {"rag_incidents_retention_days": 60, "rag_maintenance_max_delete": 50000}[k])
    monkeypatch.setattr(rm, "plan_incidents_retention", lambda days, **k: {"would_delete": 0})
    called = []
    monkeypatch.setattr(rm, "prune_incidents_by_age", lambda *a, **k: called.append(1))
    out = rm.run_incidents_retention_job()
    assert out["deleted"] == 0 and not called
