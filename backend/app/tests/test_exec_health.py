"""Yönetici alanı notu varlık ortalamasıdır. Popülasyona bölünen formül burada yoktur."""
from app.services.exec_health import asset_score, score_area


def test_one_critical_on_one_of_six_is_dikkat_not_normal():
    assets = [(1, 0)] + [(0, 0)] * 5
    out = score_area(assets, monitored=True)
    assert asset_score(1, 0) == 70
    assert out["score"] == 95
    assert out["status"] == "Dikkat"


def test_clean_fleet_stays_normal():
    out = score_area([(0, 0)] * 4, monitored=True)
    assert out["score"] == 100
    assert out["status"] == "Normal"


def test_warning_does_not_force_dikkat_when_average_is_normal():
    assets = [(0, 1)] + [(0, 0)] * 5
    out = score_area(assets, monitored=True)
    assert asset_score(0, 1) == 88
    assert out["score"] == 98
    assert out["status"] == "Normal"


def test_many_criticals_on_one_asset_caps_that_asset():
    assets = [(4, 0)] + [(0, 0)] * 5
    out = score_area(assets, monitored=True)
    assert asset_score(4, 0) == 0
    assert out["score"] == 83
    assert out["status"] == "Dikkat"


def test_low_average_stays_kritik():
    out = score_area([(4, 0), (4, 0)], monitored=True)
    assert out["score"] == 0
    assert out["status"] == "Kritik"


def test_unmonitored_has_no_score():
    out = score_area([], monitored=False)
    assert out["score"] is None
    assert out["status"] == "İzleme yok"


def test_monitored_without_assets_is_unmeasured():
    out = score_area([], monitored=True)
    assert out["status"] == "Ölçülemedi"


def test_info_weight_is_zero():
    assert asset_score(0, 0) == 100
