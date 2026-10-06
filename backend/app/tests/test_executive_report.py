from app.services.executive_report import build_executive_report


def _summary():
    return {
        "generated_at": "2026-01-01T00:00:00",
        "overall": {"health_score": 80, "grade": "B", "label": "İyi", "critical_total": 2,
                    "warning_total": 3, "open_incidents": 12, "total_servers": 10},
        "platforms": {
            "linux": {"server_count": 8, "node_exporter_running": 4, "ai_ready_count": 8, "critical": 1, "warning": 2, "health_score": 90},
            "windows": {"server_count": 2, "windows_exporter_running": 2, "critical": 0, "warning": 0, "health_score": 100},
            "virtualization": {"hypervisor_count": 1, "vm_count": 5, "vm_running_count": 3, "critical": 1, "warning": 0, "health_score": 70, "includes": ["vCenter"]},
            "openshift": {"cluster_count": 1, "unhealthy_clusters": 1, "critical": 0, "warning": 1, "health_score": 60},
        },
        "top_alerts": [{"severity": "critical", "platform": "linux", "server_name": "a", "title": "x"}],
        "open_incident_items": [{"id": 1, "severity": "warning", "platform": "openshift", "title": "t", "server_name": "—"}],
    }


def test_report_covers_all_environments_and_recommendations():
    r = build_executive_report(_summary(), {"rack_count": 2, "node_count": 6, "racks_unhealthy": 1,
                                            "critical": 0, "warning": 1, "health_score": 80})
    assert [e["key"] for e in r["environments"]] == ["linux", "windows", "virtualization", "openshift", "exadata"]
    md = r["markdown"]
    for name in ("Linux", "Windows", "Sanallaştırma", "OpenShift", "Exadata"):
        assert name in md
    recs = " ".join(r["recommendations"])
    assert "node-exporter" in recs and "Exadata rack" in recs and "OpenShift cluster" in recs and "açık olay" in recs


def test_report_without_findings_still_has_recommendation():
    r = build_executive_report({"overall": {}, "platforms": {}}, {})
    assert r["recommendations"]
