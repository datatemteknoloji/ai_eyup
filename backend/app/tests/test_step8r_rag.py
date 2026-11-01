"""Adım 8R: RAG seed (R1), modül kapsamı (R2), alaka eşiği (R3), metadata geri doldurma, rag_eval seti."""
import asyncio
import json
import sys
from pathlib import Path

import pytest

from app.services import rag_maintenance as maint
from app.services import rag_scope as scope
from app.services import rag_seed
from app.services import rag_service as rs
from app.services import rag_store as store

_SCRIPTS = Path(__file__).resolve().parents[3] / "scripts"
if (_SCRIPTS / "chat_bench").exists() and str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


# ── başlık → modül (K3) ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("title,mod", [
    ("OCP-4.18-Operators", "openshift"), ("OCP-4.21-Advanced-networking", "openshift"),
    ("OCP-node-notready", "openshift"), ("OCP-pending-crashloop", "openshift"),
    ("Huawei-eSDK-CSI-4.12", "openshift"), ("RHEL9-HA-clusters", "linux"),
    ("LINUX-disk-dolu", "linux"), ("LINUX-ssh-erisim", "linux"), ("CENTRIFY-zone-mgmt", "linux"),
    ("VIRT-ha-drs-alarm", "virtualization"), ("VIRT-ops-capability", "virtualization"),
    ("AINEW-chat-rag", "general"), ("AUTOMIC-basics", "automic"), ("ocp-lower-case", "openshift"),
    ("Kullanıcı yüklemesi.pdf", None), ("", None), (None, None),
])
def test_module_for_title(title, mod):
    assert store.module_for_title(title) == mod


# ── NUL temizliği (OCP-4.18-Storage kök nedeni) ─────────────────────────────────────

def test_clean_extracted_text_removes_nul():
    from app.services.pdf_parser import clean_extracted_text
    assert clean_extracted_text("ab\x00c\x00") == "abc"
    assert clean_extracted_text("") == "" and clean_extracted_text(None) is None


def test_sanitize_document():
    assert store.sanitize_document("x\x00y") == "xy"
    assert store.sanitize_document(None) == ""


def test_add_and_upsert_sanitize_documents():
    src = Path(store.__file__).read_text(encoding="utf-8")
    assert src.count("doc = sanitize_document(documents[i])") == 2


# ── modül SQL filtresi ───────────────────────────────────────────────────────────────

def test_module_filter_none_means_unrestricted():
    p = {}
    assert store._module_filter_sql(None, p) == "" and p == {}


def test_module_filter_includes_general_and_untagged():
    p = {}
    sql = store._module_filter_sql(["OpenShift"], p)
    assert p["mods"] == ["general", "openshift"]
    assert "NOT (metadata ? 'module')" in sql and "ANY(CAST(:mods AS text[]))" in sql


def test_module_filter_empty_set_is_general_only():
    p = {}
    sql = store._module_filter_sql([], p)
    assert p["mods"] == ["general"] and sql


def test_search_functions_accept_modules():
    src = Path(store.__file__).read_text(encoding="utf-8")
    assert "modules=modules," in src and "mod_sql" in src and "_module_filter_sql(modules, params)" in src


# ── rag_scope ────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("plat,exp", [
    ("linux", {"linux"}), ("windows", {"windows"}), ("openshift", {"openshift"}), ("ocp", {"openshift"}),
    ("virtualization", {"virtualization"}), ("exadata", {"exadata", "linux"}), ("automic", {"automic"}),
    ("LINUX", {"linux"}), ("bilinmeyen", None), (None, None), ("", None),
])
def test_modules_for_platform(plat, exp):
    assert scope.modules_for_platform(plat) == exp


def test_route_admin_unrestricted_without_route_modules():
    assert scope.modules_for_route((), None) is None
    assert scope.modules_for_route(None, None) is None


def test_route_admin_narrows_to_routed_modules():
    assert scope.modules_for_route(("virt",), None) == {"virtualization"}
    assert scope.modules_for_route(("virt", "openshift"), None) == {"virtualization", "openshift"}


def test_route_rbac_intersection():
    assert scope.modules_for_route(("virt", "openshift"), {"virt"}) == {"virtualization"}


def test_route_rbac_disjoint_gives_empty_set():
    assert scope.modules_for_route(("openshift",), {"linux"}) == set()


def test_route_rbac_without_route_uses_allowed():
    assert scope.modules_for_route((), {"linux", "windows"}) == {"linux", "windows"}


def test_route_rbac_empty_allowed_is_empty():
    assert scope.modules_for_route((), set()) == set()


def test_domains_prefer_platform_then_domains():
    assert scope.modules_for_domains({"openshift"}, "linux") == {"linux"}
    assert scope.modules_for_domains({"vcenter", "linux"}, "unified") == {"virtualization", "linux"}
    assert scope.modules_for_domains({"infra"}, "unified") is None
    assert scope.modules_for_domains(None, None) is None


def test_callers_pass_modules():
    base = Path(store.__file__).resolve().parents[1]
    for rel, needle in [("api/chat.py", "modules_for_platform"), ("api/windows_chat.py", "modules_for_platform"),
                        ("api/unified_chat.py", "modules_for_route"), ("services/virt_chat_rag.py", "modules_for_platform"),
                        ("services/agent/tools.py", "modules_for_domains")]:
        assert needle in (base / rel).read_text(encoding="utf-8"), rel


# ── seed: manifest + manifest dışı, enabled:false, idempotans ────────────────────────

def _mk_seed(tmp_path, manifest_docs):
    (tmp_path / "manifest.json").write_text(json.dumps({"documents": manifest_docs}), encoding="utf-8")
    return tmp_path


def test_collect_docs_union_manifest_priority_and_disabled(tmp_path):
    (tmp_path / "A-manifest.md").write_text("a", encoding="utf-8")
    (tmp_path / "B-extra.md").write_text("b", encoding="utf-8")
    (tmp_path / "C-disabled.md").write_text("c", encoding="utf-8")
    (tmp_path / "README.md").write_text("r", encoding="utf-8")
    (tmp_path / "ignored.bin").write_text("x", encoding="utf-8")
    _mk_seed(tmp_path, [
        {"title": "A-title", "file": "A-manifest.md", "version": "2"},
        {"title": "C", "file": "C-disabled.md", "enabled": False},
    ])
    docs = rag_seed.collect_docs(tmp_path)
    by = {d["title"]: d for d in docs}
    assert set(by) == {"A-title", "B-extra"}
    assert by["A-title"]["source"] == "manifest" and by["A-title"]["version"] == "2"
    assert by["B-extra"]["source"] == "scan"


def test_collect_docs_without_manifest_scans_all(tmp_path):
    (tmp_path / "X.md").write_text("x", encoding="utf-8")
    assert [d["title"] for d in rag_seed.collect_docs(tmp_path)] == ["X"]


def test_collect_docs_scan_skips_file_already_in_manifest(tmp_path):
    (tmp_path / "A.md").write_text("a", encoding="utf-8")
    _mk_seed(tmp_path, [{"title": "Başlık", "file": "A.md"}])
    assert [d["title"] for d in rag_seed.collect_docs(tmp_path)] == ["Başlık"]


class _SeedEnv:
    def __init__(self, monkeypatch, tmp_path):
        self.state = {}
        self.titles = set()
        self.ingested = []
        monkeypatch.setattr(store, "load_seed_state", lambda: dict(self.state))
        monkeypatch.setattr(store, "save_seed_state", lambda st: self.state.update(st))
        monkeypatch.setattr(store, "list_runbook_documents", lambda *a, **k: [{"title": t} for t in self.titles])
        monkeypatch.setattr(store, "delete_runbook_by_title", lambda t: 0)
        monkeypatch.setattr(rag_seed, "_state_path", lambda root: tmp_path / "state.json")

        async def _append(title, content):
            self.ingested.append(title)
            self.titles.add(title)
            return 3

        async def _pages(title, pages):
            self.ingested.append(title)
            self.titles.add(title)
            return 5

        monkeypatch.setattr(rs, "ingest_runbook_append", _append)
        monkeypatch.setattr(rs, "ingest_runbook_pages", _pages)


def test_seed_is_idempotent_and_reports_off_manifest(monkeypatch, tmp_path):
    root = tmp_path / "seed"
    root.mkdir()
    (root / "A.md").write_text("alpha", encoding="utf-8")
    (root / "EXTRA.md").write_text("beta", encoding="utf-8")
    _mk_seed(root, [{"title": "A", "file": "A.md"}])
    env = _SeedEnv(monkeypatch, tmp_path)
    first = asyncio.run(rag_seed.seed_rag_from_directory(root))
    assert [a["title"] for a in first["added"]] == ["A", "EXTRA"] and first["off_manifest"] == ["EXTRA"]
    assert first["chunks_by_title"] == {"A": 3, "EXTRA": 3} and first["errors"] == []
    second = asyncio.run(rag_seed.seed_rag_from_directory(root))
    assert second["added"] == [] and sorted(second["skipped"]) == ["A", "EXTRA"]
    assert env.ingested == ["A", "EXTRA"]


def test_seed_empty_pdf_is_error_not_silent(monkeypatch, tmp_path, caplog):
    from pypdf import PdfWriter
    root = tmp_path / "seed"
    root.mkdir()
    w = PdfWriter()
    w.add_blank_page(width=100, height=100)
    with (root / "BOS.pdf").open("wb") as fh:
        w.write(fh)
    env = _SeedEnv(monkeypatch, tmp_path)
    with caplog.at_level("WARNING"):
        res = asyncio.run(rag_seed.seed_rag_from_directory(root))
    assert res["added"] == [] and res["errors"] and res["errors"][0]["title"] == "BOS"
    assert [s["title"] for s in res["short_source"]] == ["BOS"]
    assert any("kaynak dosya kısa" in r.getMessage() for r in caplog.records)
    assert env.ingested == []


def test_seed_zero_chunks_is_error(monkeypatch, tmp_path):
    root = tmp_path / "seed"
    root.mkdir()
    (root / "A.md").write_text("alpha", encoding="utf-8")
    env = _SeedEnv(monkeypatch, tmp_path)

    async def _zero(title, content):
        return 0

    monkeypatch.setattr(rs, "ingest_runbook_append", _zero)
    res = asyncio.run(rag_seed.seed_rag_from_directory(root))
    assert res["added"] == [] and res["errors"] and "A" not in env.state


def test_seed_pdf_uses_page_aware_ingest(monkeypatch, tmp_path):
    root = tmp_path / "seed"
    root.mkdir()
    (root / "DOC.pdf").write_bytes(b"%PDF-fake" * 20)
    env = _SeedEnv(monkeypatch, tmp_path)
    import app.services.pdf_parser as pp
    monkeypatch.setattr(pp, "extract_pages_from_pdf", lambda b, max_pages=None: [(1, "sayfa bir"), (2, "sayfa iki")])
    res = asyncio.run(rag_seed.seed_rag_from_directory(root))
    assert res["chunks_by_title"] == {"DOC": 5} and env.ingested == ["DOC"]


# ── ingest metadata: module ───────────────────────────────────────────────────────────

def test_ingest_functions_tag_module_from_title():
    src = Path(rs.__file__).read_text(encoding="utf-8")
    assert src.count('module_for_title(title or "") or module_for_collection(') == 2


def test_ingest_runbook_pages_writes_module_and_page(monkeypatch):
    captured = {}

    async def _emb(chunks):
        return [[0.1] * 4 for _ in chunks]

    import app.services.embedding as emb
    monkeypatch.setattr(emb, "get_embeddings_batch", _emb)
    monkeypatch.setattr(rs, "_filter_valid_embeddings", lambda c, e, m, i: (c, e, m, i))
    monkeypatch.setattr(rs, "add_chunks", lambda coll, **kw: captured.update(kw, coll=coll))
    monkeypatch.setattr(rs, "_store_model_dim", lambda: ("m", 4))
    n = asyncio.run(rs.ingest_runbook_pages("OCP-4.18-Test", [(7, "metin bir"), (8, "metin iki")]))
    assert n == 2 and captured["coll"] == "runbook"
    assert [m["module"] for m in captured["metadatas"]] == ["openshift", "openshift"]
    assert [m["page"] for m in captured["metadatas"]] == [7, 8]


# ── metadata geri doldurma ───────────────────────────────────────────────────────────

def test_backfill_dry_run_writes_nothing(monkeypatch):
    monkeypatch.setattr(maint, "plan_runbook_module_backfill", lambda: {
        "titles": [{"title": "OCP-x", "module": "openshift", "rows": 3}], "rows_total": 3, "rows_mappable": 3, "unmapped": []})
    r = maint.backfill_runbook_module(dry_run=True)
    assert r["dry_run"] and r["updated"] == 0 and r["backup"] is None


def test_backfill_real_run_requires_backup_path(monkeypatch):
    monkeypatch.setattr(maint, "plan_runbook_module_backfill", lambda: {
        "titles": [{"title": "OCP-x", "module": "openshift", "rows": 3}], "rows_total": 3, "rows_mappable": 3, "unmapped": []})
    with pytest.raises(ValueError):
        maint.backfill_runbook_module(dry_run=False)


def test_backfill_nothing_to_do_is_noop(monkeypatch):
    monkeypatch.setattr(maint, "plan_runbook_module_backfill", lambda: {
        "titles": [], "rows_total": 0, "rows_mappable": 0, "unmapped": []})
    assert maint.backfill_runbook_module(dry_run=False, backup_path="/nonexistent/x")["updated"] == 0


def test_backfill_source_is_metadata_only():
    src = Path(maint.__file__).read_text(encoding="utf-8")
    assert "SET metadata = metadata ||" in src
    assert "SET embedding" not in src and "SET document" not in src and "SET collection" not in src
    assert "güncellenen satır" in src  # sayı uyuşmazlığında işlem geri alınır


# ── alaka eşiği (R3) ─────────────────────────────────────────────────────────────────

def test_threshold_setting_defaults_off():
    from app.services.runtime_settings import ADVANCED_SCHEMA
    assert ADVANCED_SCHEMA["rag_min_relevance_enabled"]["default"] is False
    assert ADVANCED_SCHEMA["rag_min_relevance"]["type"] == "float"


def test_threshold_disabled_returns_input(monkeypatch):
    monkeypatch.setattr(rs, "relevance_threshold", lambda: None)
    hits = [{"rerank_score": -9.0}, {"rerank_score": 3.0}]
    assert rs.apply_relevance_threshold(hits) == hits


def test_threshold_filters_below_and_keeps_unscored():
    hits = [{"id": 1, "rerank_score": -9.0}, {"id": 2, "rerank_score": 3.0}, {"id": 3}]
    assert [h["id"] for h in rs.apply_relevance_threshold(hits, threshold=-4.0)] == [2, 3]


def test_threshold_all_below_gives_empty():
    assert rs.apply_relevance_threshold([{"rerank_score": -9.0}, {"rerank_score": -7.0}], threshold=-4.0) == []


def test_threshold_boundary_is_inclusive():
    assert len(rs.apply_relevance_threshold([{"rerank_score": -4.0}], threshold=-4.0)) == 1


def test_relevance_threshold_reads_settings(monkeypatch):
    from app.services import runtime_settings as rt
    vals = {"rag_min_relevance_enabled": True, "rag_min_relevance": -4.0}
    monkeypatch.setattr(rt, "get_bool", lambda k: vals[k])
    monkeypatch.setattr(rt, "get_float", lambda k: vals[k])
    assert rs.relevance_threshold() == -4.0
    vals["rag_min_relevance_enabled"] = False
    assert rs.relevance_threshold() is None


def test_rerank_hits_attaches_scores_and_applies_threshold(monkeypatch):
    import app.services.reranker as rr
    monkeypatch.setattr(rr, "rerank_scored", lambda q, d, k: [(1, 2.0), (0, -8.0)])
    monkeypatch.setattr(rs, "relevance_threshold", lambda: -4.0)
    hits = [{"id": "a", "document": "x"}, {"id": "b", "document": "y"}]
    out = asyncio.run(rs._rerank_hits("q", hits, 5))
    assert [h["id"] for h in out] == ["b"] and out[0]["rerank_score"] == 2.0


def test_rerank_hits_threshold_off_keeps_all(monkeypatch):
    import app.services.reranker as rr
    monkeypatch.setattr(rr, "rerank_scored", lambda q, d, k: [(1, 2.0), (0, -8.0)])
    monkeypatch.setattr(rs, "relevance_threshold", lambda: None)
    out = asyncio.run(rs._rerank_hits("q", [{"id": "a", "document": "x"}, {"id": "b", "document": "y"}], 5))
    assert [h["id"] for h in out] == ["b", "a"]


def test_rerank_hits_reranker_off_falls_back_unscored(monkeypatch):
    import app.services.reranker as rr
    monkeypatch.setattr(rr, "is_enabled", lambda: False)
    monkeypatch.setattr(rs, "relevance_threshold", lambda: -4.0)
    hits = [{"id": "a", "document": "x"}, {"id": "b", "document": "y"}]
    out = asyncio.run(rs._rerank_hits("q", hits, 1))
    assert [h["id"] for h in out] == ["a"] and "rerank_score" not in out[0]


def test_rerank_scored_matches_rerank_order(monkeypatch):
    import app.services.reranker as rr

    class _M:
        def predict(self, pairs):
            return [0.1, 5.0, -2.0]

    monkeypatch.setattr(rr, "is_enabled", lambda: True)
    monkeypatch.setattr(rr, "_load_model", lambda name, allow_download=False: _M())
    out = rr.rerank_scored("q", ["a", "b", "c"], 2)
    assert out == [(1, 5.0), (0, 0.1)]
    assert [i for i, _ in out] == rr.rerank("q", ["a", "b", "c"], 2)


def test_rerank_scored_disabled_is_unscored(monkeypatch):
    import app.services.reranker as rr
    monkeypatch.setattr(rr, "is_enabled", lambda: False)
    assert rr.rerank_scored("q", ["a", "b"], 5) == [(0, None), (1, None)]
    assert rr.rerank_scored("q", [], 5) == []


# ── rag_eval seti ────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(not (_SCRIPTS / "chat_bench").exists(), reason="bench dizini yok")
def test_rag_eval_sets_meet_criteria():
    from chat_bench import rag_eval as ev
    assert len(ev.R2) >= 24
    scopes = {}
    for d in ev.R2:
        scopes.setdefault(d["scope"], []).append(d)
    assert set(scopes) >= {"openshift", "linux", "virtualization", "windows", "exadata", "automic", "general"}
    assert all(len(v) >= 3 for v in scopes.values())
    assert len(ev.R3) >= 50
    assert sum(1 for d in ev.R3 if not d["rel"]) >= 25 and sum(1 for d in ev.R3 if d["rel"]) >= 20
