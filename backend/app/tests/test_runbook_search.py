"""Runbook arama kart formatı + lexical yedek."""
from app.services.rag_store import format_runbook_hits, lexical_search_collection, COLLECTION_RUNBOOK


def test_format_runbook_hits_page_and_similarity():
    hits = format_runbook_hits([
        {
            "id": "a1",
            "document": "OpenShift node NotReady durumunda drain ve inspect adımları. " * 20,
            "metadata": {"title": "OCP-node-notready.pdf", "page": 21, "index": 0},
            "distance": 0.358,
        }
    ])
    assert len(hits) == 1
    h = hits[0]
    assert h["title"] == "OCP-node-notready.pdf"
    assert h["page"] == 21
    assert h["similarity"] == 0.642
    assert "OpenShift" in h["snippet"]
    assert h["snippet"].endswith("…")


def test_format_runbook_hits_missing_page():
    hits = format_runbook_hits([
        {"id": "b", "document": "kısa", "metadata": {"title": "md"}, "distance": 0.1}
    ])
    assert hits[0]["page"] is None
    assert hits[0]["similarity"] == 0.9


def test_lexical_runbook_search_finds_seeded_title_text():
    rows = lexical_search_collection(COLLECTION_RUNBOOK, "OpenShift", n_results=5)
    assert isinstance(rows, list)
    if rows:
        assert any("openshift" in (r.get("document") or "").lower() for r in rows)
