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


def test_disk_uses_terabytes_and_calendar_marks_missing_warranty(isolated_db, monkeypatch):
    monkeypatch.delenv("BACKUP_DEMO_ENABLED", raising=False)
    monkeypatch.delenv("HW_DEMO_ENABLED", raising=False)
    facts = [{
        "sections": [{
            "id": "a2",
            "status": "ok",
            "numbers": {
                "powered_off": {"value": 29, "display": ["29"]},
                "wasted_vcpu": {"value": 126, "display": ["126"]},
                "wasted_ram_gb": {"value": 403.4, "display": ["403,4"]},
                "wasted_disk_gb": {"value": 5848, "display": ["5848"]},
            },
        }],
    }]
    view = build_view(isolated_db, facts, {"text": "Özet.", "source": "template"})
    assert "5,7 TB" in view["kpis"][2]["value"]
    assert "403,4 GB" in view["kpis"][2]["value"]
    assert any(item["event"] == "veri yok" for item in view["calendar"]["items"])
    assert "DEMO" not in str(view["idle"])
    assert view["coverage"]["total"] == 12


def test_open_critical_keeps_area_at_dikkat(isolated_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.exec_view._event_assets",
        lambda db: {"pairs": {"Linux": [(1, 0)]}, "named": {}},
    )
    monkeypatch.setattr(
        "app.services.exec_view._server_counts",
        lambda db: {"linux": 6, "linux_agent": 6, "windows": 4, "windows_agent": 0},
    )
    view = build_view(isolated_db, [], {"text": "Özet.", "source": "template"})
    linux = next(area for area in view["areas"] if area["name"] == "Linux")
    windows = next(area for area in view["areas"] if area["name"] == "Windows")
    assert linux["status"] == "Dikkat"
    assert linux["score"] == 95
    assert windows["status"] == "İzleme yok"
    assert "Otomatik kapanan" in view["operations"]


def test_demo_flag_does_not_enter_the_view(isolated_db, monkeypatch):
    monkeypatch.setenv("BACKUP_DEMO_ENABLED", "true")
    monkeypatch.setenv("HW_DEMO_ENABLED", "true")
    view = build_view(isolated_db, [], {"text": "Özet.", "source": "template"})
    assert view["kpis"]
    assert "Korunan nesne" not in str(view)
