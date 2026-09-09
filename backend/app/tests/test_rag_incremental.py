"""RAG artımlı indeksleme — değişmemiş içerik yeniden embed edilmez."""
from app.services.rag_service import content_hash, select_changed_chunks


def test_content_hash_stable_and_model_scoped():
    a = content_hash("disk doldu", model="nomic-embed-text")
    b = content_hash("disk doldu", model="nomic-embed-text")
    c = content_hash("disk doldu", model="other-model")
    d = content_hash("disk dolmadı", model="nomic-embed-text")
    assert a == b
    assert a != c  # model değişirse yeniden embed gerekir
    assert a != d


def test_unchanged_rows_are_skipped():
    ids = ["event_1", "event_2"]
    texts = ["ilk olay", "ikinci olay"]
    metas = [{"event_id": 1}, {"event_id": 2}]
    existing = {
        "event_1": content_hash("ilk olay"),
        "event_2": content_hash("ikinci olay"),
    }

    kept_ids, kept_texts, kept_metas, skipped = select_changed_chunks(ids, texts, metas, existing)
    assert kept_ids == []
    assert kept_texts == []
    assert kept_metas == []
    assert skipped == 2


def test_new_and_changed_rows_are_selected():
    ids = ["event_1", "event_2", "event_3"]
    texts = ["ilk olay", "ikinci olay DEĞİŞTİ", "yeni olay"]
    metas = [{"event_id": 1}, {"event_id": 2}, {"event_id": 3}]
    existing = {
        "event_1": content_hash("ilk olay"),
        "event_2": content_hash("ikinci olay"),
    }

    kept_ids, kept_texts, kept_metas, skipped = select_changed_chunks(ids, texts, metas, existing)
    assert kept_ids == ["event_2", "event_3"]
    assert skipped == 1
    # chash metadata'ya yazılır ki sonraki turda atlanabilsin
    assert all(m.get("chash") for m in kept_metas)
    assert kept_metas[1]["chash"] == content_hash("yeni olay")


def test_empty_existing_index_selects_everything():
    ids = ["incident_9"]
    kept_ids, _, kept_metas, skipped = select_changed_chunks(
        ids, ["kök neden"], [{"incident_id": 9}], {},
    )
    assert kept_ids == ids
    assert skipped == 0
    assert kept_metas[0]["chash"]


def test_metadata_is_not_mutated_in_place():
    meta = {"event_id": 1}
    select_changed_chunks(["event_1"], ["metin"], [meta], {})
    assert "chash" not in meta
