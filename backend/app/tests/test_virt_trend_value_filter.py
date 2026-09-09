"""Trend motoru değer filtresi (min_value / max_value / value_basis).

Neden gerekli: "CPU'su %80 üzerinde olan VM'ler" sorusu eskiden ya top-N
listesiyle (order=highest — eşiği aşanların TÜMÜNÜ vermez) ya da modelin
listeyi çekip kendi süzmesiyle cevaplanıyordu. İkisi de "kaç tane var"
sorusunda yanlış sayı üretir. Filtre artık motorda.
"""
import pytest

from app.services.virt_trend_query import (
    _apply_value_filter, _canon_basis, _canon_entity, _canon_metric,
    _classify_pattern, _float_or_none,
)


@pytest.mark.parametrize("raw,expected", [
    ("net_rx_kbps", "net_rx_kbps"), ("net_tx_kbps", "net_tx_kbps"),
    ("network", "net_tx_kbps"), ("throughput", "net_tx_kbps"),
    ("net", "net_tx_kbps"),
])
def test_vm_network_metric_aliases(raw, expected):
    """Q12 regresyonu: 'network throughput değeri en yüksek VM'ler' sorusu
    eskiden db_metric_trend'in vm ekseninde net_rx_kbps/net_tx_kbps
    tanımlanmadığı için cevaplanamıyordu — veri virt_vm_metrics'te vardı,
    sadece motor haritasında eksikti."""
    assert _canon_metric(_canon_entity("vm"), raw) == expected


@pytest.mark.parametrize("raw,expected", [
    (None, "last"), ("", "last"), ("son", "last"), ("current", "last"),
    ("güncel", "last"), ("avg", "avg"), ("ortalama", "avg"),
    ("p95", "p95"), ("max", "max"), ("peak", "max"), ("min", "min"),
    ("uydurma_basis", "last"),
])
def test_basis_normalization(raw, expected):
    assert _canon_basis(raw) == expected


@pytest.mark.parametrize("raw,expected", [
    (80, 80.0), ("80", 80.0), (0, 0.0), (None, None), ("", None), ("abc", None),
])
def test_bound_parsing(raw, expected):
    assert _float_or_none(raw) == expected


def _items():
    return [
        {"name": "web01", "last": 92.0, "avg": 40.0, "p95": 88.0, "max": 95.0},
        {"name": "db01", "last": 81.0, "avg": 78.0, "p95": 90.0, "max": 91.0},
        {"name": "idle01", "last": 3.0, "avg": 2.0, "p95": 4.0, "max": 9.0},
        {"name": "nodata", "last": None, "avg": None, "p95": None, "max": None},
    ]


def test_min_value_keeps_only_above_threshold():
    kept, unknown = _apply_value_filter(_items(), "last", 80.0, None)
    assert [i["name"] for i in kept] == ["web01", "db01"]
    assert unknown == 1  # değeri olmayan satır eşiği "sağlıyor" sayılmaz


def test_max_value_finds_idle_entities():
    kept, _ = _apply_value_filter(_items(), "last", None, 5.0)
    assert [i["name"] for i in kept] == ["idle01"]


def test_range_filter_uses_both_bounds():
    kept, _ = _apply_value_filter(_items(), "last", 50.0, 85.0)
    assert [i["name"] for i in kept] == ["db01"]


def test_basis_changes_which_entities_match():
    # web01 anlık %92 ama ortalaması düşük (ani sıçrama); db01 kalıcı yüksek.
    # "sürekli yüksek olanlar" sorusu avg/p95 ile farklı sonuç vermeli.
    by_last = _apply_value_filter(_items(), "last", 80.0, None)[0]
    by_avg = _apply_value_filter(_items(), "avg", 70.0, None)[0]
    assert [i["name"] for i in by_last] == ["web01", "db01"]
    assert [i["name"] for i in by_avg] == ["db01"]


def test_no_bounds_is_passthrough():
    items = _items()
    kept, unknown = _apply_value_filter(items, "last", None, None)
    assert kept is items and unknown == 0


def test_boundary_value_is_inclusive():
    kept, _ = _apply_value_filter(_items(), "last", 81.0, None)
    assert "db01" in [i["name"] for i in kept]


# ── _classify_pattern: ani sıçrama (spike) vs sürekli trend ─────────────────

def test_pattern_none_when_unreliable():
    assert _classify_pattern("artıyor", 50.0, 90.0, 88.0, reliable=False) is None


def test_pattern_sustained_rise_last_close_to_max():
    # Ortalama 40, tepe 90, son değer 88 → hâlâ tepede, yükseliş sürüyor.
    assert _classify_pattern("artıyor", 40.0, 90.0, 88.0, reliable=True) == "sürekli_yükseliş"


def test_pattern_spike_returns_to_normal():
    # Bir noktada 90'a sıçramış ama SON değer ortalamaya (40) çok yakın (45)
    # → geçmişte spike olmuş, şu an normal.
    assert _classify_pattern("sabit", 40.0, 90.0, 45.0, reliable=True) == "ani_sıçrama"


def test_pattern_wavy_rise_when_last_far_from_peak():
    # Artan eğim var ama son değer tepeye yakın değil (dalgalı).
    assert _classify_pattern("artıyor", 40.0, 90.0, 55.0, reliable=True) == "dalgalı_artış"


def test_pattern_sustained_fall():
    assert _classify_pattern("azalıyor", 80.0, 95.0, 20.0, reliable=True) == "sürekli_düşüş"


def test_pattern_stable_when_no_spike_no_trend():
    assert _classify_pattern("sabit", 40.0, 45.0, 41.0, reliable=True) == "kararlı"
