"""
Sağlık skoru etiketi bulgu şiddetiyle tutarlı olmalı.

Ceza varlık sayısına bölündüğü için tek host'lu ortamda bir kritik bulgu
92 puan / "Sağlıklı" üretiyordu — kullanıcıya RAM %96 kritiğiyle birlikte
"Sağlıklı" göstermek yanıltıcı.
"""
from app.services.virt_ops_center import _health_score


def test_critical_finding_cannot_be_labeled_healthy():
    h = _health_score(critical=1, warning=0, host_count=1, manager_count=1)
    assert h["score"] <= 74
    assert h["label"] != "Sağlıklı"


def test_warning_only_is_not_grade_a():
    h = _health_score(critical=0, warning=1, host_count=1, manager_count=1)
    assert h["grade"] != "A"
    assert h["score"] <= 89


def test_clean_environment_stays_healthy():
    h = _health_score(critical=0, warning=0, host_count=4, manager_count=1)
    assert h["score"] == 100
    assert h["label"] == "Sağlıklı"


def test_many_criticals_score_lower_than_single_critical():
    one = _health_score(critical=1, warning=0, host_count=6, manager_count=1)
    many = _health_score(critical=6, warning=0, host_count=6, manager_count=1)
    assert many["score"] < one["score"]


def test_empty_inventory_reports_no_data():
    h = _health_score(critical=0, warning=0, host_count=0, manager_count=0)
    assert h["label"] == "Veri Yok"
