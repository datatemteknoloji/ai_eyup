"""Öksüz RAG chunk bakımı — kaynağı silinmiş event/incident kayıtları.

Event retention temizliği `system_events` satırlarını silince gömme
(embedding) satırları arkada kalıyordu; bu bakım işi onları SQL tarafında
bulup kontrollü partiler hâlinde siler.
"""
import pytest

from app.services import rag_store


def test_only_known_prefixes_allowed():
    with pytest.raises(ValueError):
        rag_store.prune_orphan_source_chunks("incidents", id_prefix="kb_")
    with pytest.raises(ValueError):
        # SQL enjeksiyon denemesi de aynı kapıdan geri döner
        rag_store.prune_orphan_source_chunks("incidents", id_prefix="x_; DROP TABLE")


def test_known_prefixes_map_to_source_tables():
    assert rag_store._ORPHAN_SOURCES["event_"] == "system_events"
    assert rag_store._ORPHAN_SOURCES["incident_"] == "incidents"


def test_returns_early_when_vector_disabled(monkeypatch):
    monkeypatch.setattr(rag_store, "_ensure_vector_ready", lambda: False)
    out = rag_store.prune_orphan_source_chunks("incidents", id_prefix="event_")
    assert out["deleted"] == 0
    assert out["skipped"] == "vector_disabled"


def test_maintenance_job_is_registered_for_celery():
    from app.worker import _FLEET_TASKS

    assert _FLEET_TASKS["fleet.rag_maintenance"] == "run_rag_maintenance"
    from app.services import fleet_jobs

    assert callable(fleet_jobs.run_rag_maintenance)


def test_maintenance_job_skips_when_lock_held(monkeypatch):
    """Aynı anda ikinci bir tur çalışmaz (fleet mutex)."""
    import contextlib

    from app.services import fleet_jobs

    @contextlib.contextmanager
    def _busy(*_a, **_kw):
        yield False

    monkeypatch.setattr("app.services.fleet_mutex.fleet_lock", _busy)
    assert fleet_jobs.run_rag_maintenance() == {"skipped": True}
