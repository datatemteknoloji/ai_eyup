"""Sayfa modeli demo sayıyı kilitli pakete koymaz."""
from app.services.exec_view import build_view, demo_cards


def test_view_has_no_demo_numbers(isolated_db, monkeypatch):
    monkeypatch.delenv("BACKUP_DEMO_ENABLED", raising=False)
    monkeypatch.delenv("HW_DEMO_ENABLED", raising=False)
    view = build_view(isolated_db, [], {"text": "Özet.", "source": "template"})
    assert view["summary"]["source"] == "template"
    assert "demo" not in str(view).lower() or "Red Hat" in view["openshift_note"]
    blob = str(view)
    assert "veeam" not in blob.lower()
    cards = demo_cards(isolated_db)
    assert all(card["demo"] is False for card in cards)
    assert all(card["status"] == "Ölçülemedi" for card in cards)


def test_demo_flag_does_not_enter_the_view(isolated_db, monkeypatch):
    monkeypatch.setenv("BACKUP_DEMO_ENABLED", "true")
    monkeypatch.setenv("HW_DEMO_ENABLED", "true")
    view = build_view(isolated_db, [], {"text": "Özet.", "source": "template"})
    assert view["kpis"]
    assert "Korunan nesne" not in str(view)
