"""Kasalar (şasi → blade) eşleşmesi ve sıralaması. Ağa ÇIKMAZ.

Kapsam: (1) kimlik tabanlı eşleşme (OneView `enclosure_ref`), (2) ad eşleşmesi yalnız yönetim noktası içinde ve TEKİL ise,
(3) doğal sıralama (`Sled-2` < `Sled-10`, `1a` < `1b`)."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

import app.models.infrastructure_report  # noqa: F401
from app.api.hw import _blades_by_enclosure, _empty_bays, _nat_key, _ref_tail
from app.models.hw import HwEnclosure, HwManager, HwServer
from app.tests import hw_fakes as F
from app.tests.test_hw_bmc_api import _client


@pytest.fixture()
def db(isolated_db):
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()
    yield isolated_db
    invalidate_capabilities()


def _e(id, name, ref, mgr=1, inst=1):
    return SimpleNamespace(id=id, name=name, provider_ref=ref, instance_id=inst, manager_id=mgr)


def _s(id, name, bay, *, encl_name=None, encl_ref=None, mgr=1, inst=1):
    return SimpleNamespace(id=id, name=name, bay=bay, health="ok", model="m", instance_id=inst, manager_id=mgr,
                           enclosure_name=encl_name, enclosure_ref=encl_ref)


def test_ref_tail_forms():
    assert _ref_tail("10.0.0.5|/rest/enclosures/0000A1") == "0000A1"      # OneView / OVGD
    assert _ref_tail("10100") == "10100"                                   # OME şasi Id
    assert _ref_tail("demo-encl1") == "demo-encl1"
    assert _ref_tail("") is None and _ref_tail(None) is None


def test_nat_key_orders_numbers_and_letters():
    bays = ["Sled-10", "Sled-2", "Sled-1", "Sled-9"]
    assert sorted(bays, key=_nat_key) == ["Sled-1", "Sled-2", "Sled-9", "Sled-10"]
    assert sorted(["2a", "1b", "10a", "1a"], key=_nat_key) == ["1a", "1b", "2a", "10a"]
    assert sorted(["Encl-10", "encl-2"], key=_nat_key) == ["encl-2", "Encl-10"]


def test_same_enclosure_name_in_two_managers_does_not_mix_blades():
    encl = [_e(1, "Encl1", "a|/rest/enclosures/E1", mgr=1), _e(2, "Encl1", "b|/rest/enclosures/E1", mgr=2)]
    srv = [_s(10, "Encl1, bay 1", "1", encl_name="Encl1", encl_ref="E1", mgr=1),
           _s(20, "Encl1, bay 1", "1", encl_name="Encl1", encl_ref="E1", mgr=2)]
    out, un = _blades_by_enclosure(encl, srv)
    assert [b["id"] for b in out[1]] == [10] and [b["id"] for b in out[2]] == [20] and un == []


def test_same_name_in_two_instances_does_not_mix_blades_for_name_match():
    encl = [_e(1, "MX-A", "100", mgr=1, inst=1), _e(2, "MX-A", "100", mgr=5, inst=2)]
    srv = [_s(10, "n1", "Sled-1", encl_name="MX-A", mgr=1, inst=1), _s(20, "n2", "Sled-1", encl_name="MX-A", mgr=5, inst=2)]
    out, un = _blades_by_enclosure(encl, srv)
    assert [b["id"] for b in out[1]] == [10] and [b["id"] for b in out[2]] == [20] and un == []


def test_ref_wins_over_duplicate_name_in_one_manager():
    encl = [_e(1, "Encl1", "a|/rest/enclosures/E1"), _e(2, "Encl1", "a|/rest/enclosures/E2")]
    srv = [_s(10, "x", "1", encl_name="Encl1", encl_ref="E2")]
    out, _ = _blades_by_enclosure(encl, srv)
    assert 1 not in out and [b["id"] for b in out[2]] == [10]


def test_ambiguous_name_without_ref_is_not_guessed():
    encl = [_e(1, "Dup", "100"), _e(2, "Dup", "101")]
    srv = [_s(10, "x", "Sled-1", encl_name="Dup")]
    out, un = _blades_by_enclosure(encl, srv)
    assert out == {} and [u["id"] for u in un] == [10] and un[0]["enclosure"] == "Dup"     # kaybolmaz: «şasisi belirlenemeyen»


def test_unknown_enclosure_goes_to_unassigned():
    out, un = _blades_by_enclosure([_e(1, "A", "1")], [_s(10, "x", "1", encl_name="Yok"), _s(11, "y", "2", encl_ref="ZZ")])
    assert out == {} and sorted(u["id"] for u in un) == [10, 11]


def test_empty_bays_only_when_computable():
    sv = lambda *bays: [{"bay": b} for b in bays]
    assert _empty_bays(8, sv("1", "2", "5")) == [3, 4, 6, 7, 8]
    assert _empty_bays(4, []) == [1, 2, 3, 4]                       # sunucu kaydı yok → hepsi «kayıt yok»
    assert _empty_bays(4, sv("1", "1", "2")) == [3, 4]              # aynı yuvada iki sunucu → yuva bir kez dolu
    assert _empty_bays(None, sv("1")) is None                       # yuva sayısı bilinmiyor (Dell)
    assert _empty_bays(0, sv()) is None and _empty_bays(1000, sv()) is None and _empty_bays(True, sv()) is None
    assert _empty_bays(8, sv("1", "1a")) is None                    # sayısal olmayan yuva (quarter-height) → hesaplanmaz
    assert _empty_bays(8, sv("1", None)) is None                    # yuvası bilinmeyen sunucu → doluluk bilinmez
    assert _empty_bays(4, sv("9")) is None                          # aralık dışı → tutarsız veri


def test_enclosures_api_orders_bays_and_enclosures_naturally(db):
    inst = F.make_row(db)
    inst.last_status = "ok"
    db.commit()
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()
    mgr = HwManager(instance_id=inst.id, provider_key="ome", manager_kind="ome", name="ome", status="ok")
    db.add(mgr)
    db.flush()
    db.add_all([HwEnclosure(instance_id=inst.id, manager_id=mgr.id, provider_ref="2", name="MX-10", health="ok"),
                HwEnclosure(instance_id=inst.id, manager_id=mgr.id, provider_ref="1", name="MX-2", health="ok")])
    for i, bay in enumerate(["Sled-10", "Sled-2", "Sled-1"]):
        db.add(HwServer(instance_id=inst.id, manager_id=mgr.id, provider_ref=f"s{i}", vendor="dell", name=f"n{i}", serial=f"S{i}",
                        form_factor="blade", enclosure_name="MX-2", bay=bay))
    db.add(HwServer(instance_id=inst.id, manager_id=mgr.id, provider_ref="nobay", vendor="dell", name="nb", serial="NB",
                    form_factor="blade", enclosure_name="MX-2", bay=None))
    db.commit()
    j = _client(db).get("/hw/enclosures").json()
    assert [e["name"] for e in j["enclosures"]] == ["MX-2", "MX-10"]
    assert [s["bay"] for s in j["enclosures"][0]["servers"]] == ["Sled-1", "Sled-2", "Sled-10", None]   # bay'siz sona
    assert j["enclosures"][0]["empty_bays"] is None and j["unassigned"] == []                           # Dell: yuva sayısı yok


def test_enclosures_api_empty_bays_shared_bay_and_unassigned(db):
    inst = F.make_row(db)
    inst.last_status = "ok"
    db.commit()
    from app.services.capabilities import invalidate_capabilities
    invalidate_capabilities()
    mgr = HwManager(instance_id=inst.id, provider_key="ov", manager_kind="oneview", name="ov", status="ok")
    db.add(mgr)
    db.flush()
    db.add(HwEnclosure(instance_id=inst.id, manager_id=mgr.id, provider_ref="ov|/rest/enclosures/E1", name="Encl1",
                       health="ok", bay_count=6))
    for ref, bay in (("a", "1"), ("b", "3"), ("c", "3")):                    # 3. yuvada iki düğüm
        db.add(HwServer(instance_id=inst.id, manager_id=mgr.id, provider_ref=ref, vendor="hpe", name=f"Encl1, bay {bay}{ref}",
                        serial=ref.upper(), form_factor="blade", enclosure_ref="E1", enclosure_name="Encl1", bay=bay))
    db.add(HwServer(instance_id=inst.id, manager_id=mgr.id, provider_ref="o", vendor="hpe", name="orphan", serial="O",
                    form_factor="blade", enclosure_ref="GONE", enclosure_name=None, bay="2"))
    db.commit()
    j = _client(db).get("/hw/enclosures").json()
    e = j["enclosures"][0]
    assert [s["bay"] for s in e["servers"]] == ["1", "3", "3"] and e["empty_bays"] == [2, 4, 5, 6]
    assert [u["name"] for u in j["unassigned"]] == ["orphan"]
