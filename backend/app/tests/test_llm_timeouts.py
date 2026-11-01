"""llm_timeouts: çağrı sınıfına göre dinamik okuma zaman aşımı (Adım 3 / Parça 2B)."""
import pytest

from app.services import llm_activity, llm_timeouts as lt


@pytest.fixture(autouse=True)
def _temiz(monkeypatch):
    lt.clear_cache()
    # Ayarlar: varsayılanlar (DB/env'den bağımsız)
    monkeypatch.setattr(lt, "_setting", lambda key, fb: fb)
    yield
    lt.clear_cache()


def _samples(monkeypatch, values):
    monkeypatch.setattr(llm_activity, "class_samples", lambda cls, **kw: list(values))


def test_ornek_yokken_varsayilan(monkeypatch):
    _samples(monkeypatch, [])
    assert lt.timeout_for("tool_turn") == 90.0
    assert lt.timeout_for("route_hint") == 8.0
    assert lt.timeout_for("final_answer") == 120.0
    assert lt.timeout_for("background") == 120.0


def test_yetersiz_ornek_varsayilan(monkeypatch):
    _samples(monkeypatch, [80.0] * 9)       # < 10 örnek
    assert lt.timeout_for("tool_turn") == 90.0


def test_p95_k_hesabi_ve_ust_sinir(monkeypatch):
    _samples(monkeypatch, [60.0] * 20)      # p95=60 × k2 = 120 → 90 ile 180 arasında
    assert lt.timeout_for("tool_turn") == pytest.approx(120.0)
    lt.clear_cache()
    _samples(monkeypatch, [200.0] * 20)     # 400 → üst sınır 180
    assert lt.timeout_for("tool_turn") == 180.0


def test_alt_sinir_asagi_inmez(monkeypatch):
    _samples(monkeypatch, [2.0] * 30)       # p95×k = 4 → alt sınır 90
    assert lt.timeout_for("tool_turn") == 90.0     # mevcut 90 sn davranışı korunur
    lt.clear_cache()
    assert lt.timeout_for("final_answer") == 120.0


def test_floor_cagri_noktasi_varsayilani(monkeypatch):
    _samples(monkeypatch, [])
    assert lt.timeout_for("final_answer", floor=180.0) == 180.0     # httpx varsayılanı 180
    assert lt.timeout_for("background", floor=120.0) == 120.0
    lt.clear_cache()
    _samples(monkeypatch, [150.0] * 20)                              # 300 → final üst 240
    assert lt.timeout_for("final_answer", floor=180.0) == 240.0


def test_route_hint_ust_siniri_10(monkeypatch):
    _samples(monkeypatch, [8.0] * 50)       # 8 × 1.5 = 12 → en fazla 10
    assert lt.timeout_for("route_hint") == 10.0
    # ayar 600 olsa bile route_hint 10'u aşamaz
    monkeypatch.setattr(lt, "_setting", lambda key, fb: 600 if key == "llm_timeout_route_hint_max_sec" else fb)
    lt.clear_cache()
    assert lt.timeout_for("route_hint") <= 10.0
    assert lt.params("route_hint")[2] == 10.0


def test_route_hint_floor_yok_sayilir(monkeypatch):
    _samples(monkeypatch, [])
    assert lt.timeout_for("route_hint", floor=100.0) == 8.0


def test_dinamik_kapali(monkeypatch):
    _samples(monkeypatch, [100.0] * 30)
    monkeypatch.setattr(lt, "_setting", lambda key, fb: False if key == "llm_timeout_dynamic" else fb)
    assert lt.timeout_for("tool_turn") == 90.0


def test_tutarsiz_ayar_max_min_olur(monkeypatch):
    vals = {"llm_timeout_tool_turn_min_sec": 100, "llm_timeout_tool_turn_max_sec": 50}
    monkeypatch.setattr(lt, "_setting", lambda key, fb: vals.get(key, fb))
    k, lo, hi = lt.params("tool_turn")
    assert lo == 100 and hi == 100


def test_bilinmeyen_sinif_background(monkeypatch):
    _samples(monkeypatch, [])
    assert lt.timeout_for("yok") == 120.0


def test_tool_turn_varsayilani_90_altina_dusmez(monkeypatch):
    for samples in ([], [1.0] * 40, [89.0] * 40):
        lt.clear_cache()
        _samples(monkeypatch, samples)
        assert lt.timeout_for("tool_turn") >= 90.0


def test_asiri_deger_timeouti_sisirmez(monkeypatch):
    # tek bir aşırı değer p95'i yükseltmez (49 normal + 1 aşırı → p95 normal örnek)
    _samples(monkeypatch, [10.0] * 49 + [3000.0])
    assert lt.timeout_for("tool_turn") == 90.0


def test_kuyruk_suresi_haric_class_samples(monkeypatch):
    """class_samples `duration_ms` kullanır (slot alındıktan sonra ölçülür); sched_wait_ms'e bakmaz."""
    import time
    now = time.time()
    rows = [
        {"tclass": "tool_turn", "duration_ms": 5000.0, "sched_wait_ms": 90000.0, "start": now - 5, "end": now,
         "caller": "app.services.x.f"},
        {"tclass": "tool_turn", "skipped": "slot_busy", "duration_ms": 0.0, "start": now - 4, "end": now,
         "caller": "app.services.x.f"},
        {"tclass": "route_hint", "duration_ms": 900.0, "start": now - 3, "end": now, "caller": "app.services.x.f"},
        {"tclass": "tool_turn", "duration_ms": 7000.0, "start": now - 2, "end": now,
         "caller": "app.tests.test_x.test_y"},       # test çağrısı hariç
    ]
    monkeypatch.setattr(llm_activity, "recent", lambda limit=0, since=None: rows)
    assert llm_activity.class_samples("tool_turn") == [5.0]


def test_ayarlar_kayitli():
    from app.services.runtime_settings import ADVANCED_SCHEMA as A
    for cls in lt.CLASSES:
        for suf in ("k", "min_sec", "max_sec"):
            assert f"llm_timeout_{cls}_{suf}" in A
        k, lo, hi = lt.DEFAULTS[cls]
        assert A[f"llm_timeout_{cls}_k"]["default"] == k
        assert A[f"llm_timeout_{cls}_min_sec"]["default"] == lo
        assert A[f"llm_timeout_{cls}_max_sec"]["default"] == hi
        assert A[f"llm_timeout_{cls}_k"]["group"] == "llm_chat"
    assert A["llm_timeout_route_hint_max_sec"]["max"] == 10
    assert A["llm_timeout_tool_turn_min_sec"]["default"] == 90
    assert A["llm_timeout_dynamic"]["default"] is True


def test_gateway_varsayilanlari_timeouttan_beslenir(monkeypatch):
    from app.services import llm_gateway as gw
    _samples(monkeypatch, [])
    assert gw._requests_timeout(None)[1] == 120.0       # eski varsayılan
    assert gw._httpx_timeout(None).read == 180.0        # eski varsayılan
    # Açık timeout önceliklidir
    assert gw._requests_timeout(33)[1] == 33.0
    assert gw._httpx_timeout(44).read == 44.0
    # Dinamik üst: final_answer p95 150 → 300 → üst 240 (httpx floor 180)
    lt.clear_cache()
    _samples(monkeypatch, [150.0] * 20)
    assert gw._httpx_timeout(None).read == 240.0
