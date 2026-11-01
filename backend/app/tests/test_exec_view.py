"""Sayfa modeli demo sayıyı kilitli pakete koymaz."""
from app.services.exec_view import build_view, demo_cards, landscape_summary


def test_view_has_no_demo_numbers(isolated_db, monkeypatch):
    monkeypatch.delenv("BACKUP_DEMO_ENABLED", raising=False)
    monkeypatch.delenv("HW_DEMO_ENABLED", raising=False)
    view = build_view(isolated_db, [], {"text": "Özet.", "source": "template"})
    assert view["summary"]["source"] == "template"
    assert "demo" not in str(view).lower() or "Red Hat" in view["openshift_note"]
    blob = str(view)
    assert "veeam" not in blob.lower()
    titles = [card["title"] for card in demo_cards(isolated_db)]
    assert "Yedek kapsamı" not in titles
    assert "Donanım ve garanti" not in titles
    assert all(title == "UC4" for title in titles)
    assert "Başarısız iş" not in str(view)


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
    assert all(item["area"] not in ("Destek", "Garanti") for item in view["calendar"]["items"])
    assert "DEMO" not in str(view["idle"])
    assert view["coverage"]["total"] == 12


def test_virt_detail_lists_the_cluster_when_the_event_has_no_name(isolated_db, monkeypatch):
    monkeypatch.setattr(
        "app.services.exec_view._event_assets",
        lambda db: {"pairs": {"Sanallaştırma": [(4, 0)]}, "named": {}},
    )
    monkeypatch.setattr("app.services.exec_view._virt_population", lambda db, n: 1)
    monkeypatch.setattr(
        "app.services.exec_view._area_lines",
        lambda db: {"Sanallaştırma": ["depolama alanı doluluğu yüksek · 4"]},
    )
    monkeypatch.setattr("app.services.exec_view._uc4_area", lambda: None)
    facts = [{
        "sections": [{
            "id": "b1_virt",
            "rows": [{"cluster": "office", "memory_pct": 88.0, "status": "ok"}],
        }],
    }]
    view = build_view(isolated_db, facts, {"text": "Özet.", "source": "template"})
    virt = next(area for area in view["areas"] if area["name"] == "Sanallaştırma")
    assert virt["status"] == "Kritik"
    assert virt["assets"][0]["name"] == "office"
    assert virt["assets"][0]["usage"] == "%88"
    assert "depolama alanı" in virt["events"][0]
    assert "hostta kritik olay" in virt["reason"]


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
    assert "Yedek kapsamı" not in str(view)
    assert "Donanım ve garanti" not in str(view)


def test_template_names_environment_cluster_and_remedy():
    text = landscape_summary({
        "physical": "2",
        "virtual": "10",
        "environments": [
            {"name": "office", "kind": "VMware", "clusters": 1, "hosts": 2, "vms": 10},
        ],
        "datastores": [{"environment": "office", "name": "NVME", "usageLabel": "%91"}],
        "hosts": [{
            "host": "esx01", "problem": "Sensör uyarıda", "action": "Sensörü kontrol edin.",
            "cluster": "Kümesiz", "environment": "office",
        }],
        "reclaim": [{"environment": "office", "cluster": "Kümesiz", "count": "4", "vcpu": 8}],
    })
    assert "3 ortam" not in text
    assert "office" in text and "VMware" in text
    assert "küme" in text and "sanal makine" in text
    assert "Sensör" not in text
    assert "Olası çözüm" not in text
    assert "%91" not in text
    assert text.count(". ") + 1 <= 3
    assert "vCPU" not in text


def test_ip_named_host_is_labelled_by_platform():
    from app.services.exec_inventory import host_label
    assert host_label("192.168.1.101", "VMware") == "ESXi host (192.168.1.101)"
    assert host_label("192.168.1.112", "OLVM") == "KVM host (192.168.1.112)"
    assert host_label("dtkvm01", "OLVM") == "dtkvm01"
    assert host_label(None, "VMware") == "Adsız host"


def test_pct_is_clamped_to_100():
    from app.services.exec_inventory import _pct
    assert _pct(163.2) == 100.0
    assert _pct(-4) == 0.0
    assert _pct(None) is None


def test_attention_merges_one_row_per_entity():
    from app.services.exec_inventory import build_attention
    hosts = [
        {"host": "esx01", "problem": "Sensör uyarıda", "action": "a", "environment": "office", "kind": "VMware",
         "cluster": "c1", "hardware": True},
        {"host": "esx01", "problem": "Disk", "action": "a", "environment": "office", "kind": "VMware",
         "cluster": "c1", "hardware": False},
    ]
    risks = [
        {"entity": "ESX01", "sentence": "Sensör uyarıda", "action": "x", "age_days": 9, "area": "Sanallaştırma"},
        {"entity": "db-prod", "sentence": "Yedek yok", "action": "y", "age_days": 3, "area": "Yedek"},
    ]
    rows = build_attention(hosts, risks)
    assert [r["title"] for r in rows] == ["esx01", "db-prod"]
    assert rows[0]["extra"] == 1 and rows[0]["age_days"] == 9 and rows[0]["hardware"] is True


def test_bundle_payload_does_not_recompute_view():
    import app.services.exec_snapshot as snap
    assert not hasattr(snap, "present_bundle")
