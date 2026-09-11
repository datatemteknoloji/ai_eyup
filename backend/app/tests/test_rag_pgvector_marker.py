"""pgvector unsupported-marker recovery — DB'siz birim testleri."""
from pathlib import Path

import pytest

from app.services import rag_store


@pytest.fixture(autouse=True)
def _reset_rag_store_globals(tmp_path, monkeypatch):
    monkeypatch.setattr(rag_store, "_schema_ready", False)
    monkeypatch.setattr(rag_store, "_vector_disabled", False)
    monkeypatch.setattr(rag_store, "_vector_disable_reason", None)
    monkeypatch.setattr(rag_store, "_unsupported_marker", lambda: tmp_path / ".pgvector_unsupported")
    monkeypatch.delenv("RAG_PGVECTOR_FORCE", raising=False)
    yield
    monkeypatch.setattr(rag_store, "_schema_ready", False)
    monkeypatch.setattr(rag_store, "_vector_disabled", False)
    monkeypatch.setattr(rag_store, "_vector_disable_reason", None)


def test_stale_avx_marker_cleared_when_host_has_avx_and_extension(monkeypatch, tmp_path):
    marker = tmp_path / ".pgvector_unsupported"
    marker.write_text(rag_store._MARKER_AVX_TEXT, encoding="utf-8")

    monkeypatch.setattr(rag_store, "_host_has_avx", lambda: True)
    monkeypatch.setattr(rag_store, "_probe_vector_extension", lambda: True)

    ddl_calls = []

    class _Conn:
        def execute(self, *_a, **_k):
            ddl_calls.append(1)
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class _Engine:
        def begin(self):
            return _Conn()

        def connect(self):
            return _Conn()

    monkeypatch.setattr(rag_store, "engine", _Engine())

    rag_store.ensure_schema()

    assert rag_store._schema_ready is True
    assert rag_store.is_vector_disabled() is False
    assert not marker.is_file()
    assert ddl_calls  # table DDL ran


def test_no_avx_disables_without_create(monkeypatch, tmp_path):
    monkeypatch.setattr(rag_store, "_host_has_avx", lambda: False)

    created = {"n": 0}

    def _boom():
        created["n"] += 1
        raise AssertionError("CREATE should not run without AVX")

    monkeypatch.setattr(rag_store, "_probe_vector_extension", _boom)

    rag_store.ensure_schema()

    assert rag_store.is_vector_disabled() is True
    assert "AVX" in (rag_store.vector_disable_reason() or "")
    marker = tmp_path / ".pgvector_unsupported"
    assert marker.is_file()
    assert "AVX" in marker.read_text(encoding="utf-8")


def test_create_failed_marker_blocks_retry_when_extension_missing(monkeypatch, tmp_path):
    marker = tmp_path / ".pgvector_unsupported"
    marker.write_text(f"{rag_store._MARKER_CREATE_PREFIX} boom\n", encoding="utf-8")

    monkeypatch.setattr(rag_store, "_host_has_avx", lambda: True)
    monkeypatch.setattr(rag_store, "_probe_vector_extension", lambda: False)

    create_tried = {"n": 0}

    class _Conn:
        def execute(self, sql, *_a, **_k):
            create_tried["n"] += 1
            raise RuntimeError("should not CREATE")

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class _Engine:
        def begin(self):
            return _Conn()

    monkeypatch.setattr(rag_store, "engine", _Engine())

    rag_store.ensure_schema()

    assert rag_store.is_vector_disabled() is True
    assert create_tried["n"] == 0
    assert marker.is_file()


def test_create_failed_marker_cleared_when_extension_present(monkeypatch, tmp_path):
    marker = tmp_path / ".pgvector_unsupported"
    marker.write_text(f"{rag_store._MARKER_CREATE_PREFIX} old\n", encoding="utf-8")

    monkeypatch.setattr(rag_store, "_host_has_avx", lambda: True)
    monkeypatch.setattr(rag_store, "_probe_vector_extension", lambda: True)

    class _Conn:
        def execute(self, *_a, **_k):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_a):
            return False

    class _Engine:
        def begin(self):
            return _Conn()

    monkeypatch.setattr(rag_store, "engine", _Engine())

    rag_store.ensure_schema()

    assert rag_store._schema_ready is True
    assert not rag_store.is_vector_disabled()
    assert not marker.is_file()


def test_require_vector_ready_raises(monkeypatch):
    monkeypatch.setattr(rag_store, "_ensure_vector_ready", lambda: False)
    monkeypatch.setattr(rag_store, "_vector_disable_reason", "test kapalı")
    with pytest.raises(RuntimeError, match="vektör deposu"):
        rag_store._require_vector_ready()


def test_add_chunks_raises_when_disabled(monkeypatch):
    monkeypatch.setattr(rag_store, "_ensure_vector_ready", lambda: False)
    monkeypatch.setattr(rag_store, "_vector_disable_reason", "kapalı")
    with pytest.raises(RuntimeError, match="vektör deposu"):
        rag_store.add_chunks(
            rag_store.COLLECTION_RUNBOOK,
            ["id1"],
            ["doc"],
            [{}],
            [[0.0] * 768],
        )
