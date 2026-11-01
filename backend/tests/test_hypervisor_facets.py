"""Ortam (hypervisor) filtresi: hypervisor_ids, facet sayıları, credential sızıntısı yok, RBAC.

SQL testleri PostgreSQL gerektirir; veri `servers` ve `hypervisors` TEMP tabloları üzerindedir
(gerçek tablolar gölgelenir) ve işlem sonunda ROLLBACK ile atılır. DB yoksa atlanır.
"""
import json

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api import servers as api
from app.core import module_policy
from app.models.hypervisor import Hypervisor, HypervisorType
from app.models.server import Server
from app.services import platform_scope

SECRETS = ["SECRET-PW-123", "root-user-x", "TOKEN-ABC", "10.99.99.99", "vcenter.secret.local"]


# ── saf birim testleri ────────────────────────────────────────────────────────

def test_parse_hypervisor_ids_ignores_invalid():
    p = api.parse_hypervisor_ids
    assert p(None) == []
    assert p("") == []
    assert p("2,7,8") == [2, 7, 8]
    assert p(" 2 , 7 ,,abc, -1, 0, 1.5, 2") == [2, 7]  # çift, negatif, sıfır, ondalık, harf atılır
    assert p("abc,xyz") == []
    assert len(p(",".join(str(i) for i in range(1, 500)))) == api._HV_IDS_MAX


def test_rbac_same_as_server_list():
    # Facet uç noktası liste ile AYNI kuralı ve aynı kararı alır (modül önekine göre).
    facets = "/api/v1/servers/hypervisor-facets"
    listing = "/api/v1/servers/"
    assert module_policy.find_rule(facets) == module_policy.find_rule(listing)
    for role in ("viewer", "operator", "admin"):
        for modules in ([], ["linux"], ["windows"], ["virtualization"], ["monitoring"], ["openshift"], ["integrations"]):
            for plat in ("linux", "windows"):
                q = {"platform": plat}
                a = module_policy.decide(role=role, modules=modules, method="GET", path=facets, query=q)
                b = module_policy.decide(role=role, modules=modules, method="GET", path=listing, query=q)
                assert (a.allowed, a.status) == (b.allowed, b.status), (role, modules, plat)
    # Hiçbir modülü olmayan / ilgisiz modüldeki kullanıcı facet'i göremez
    assert not module_policy.decide(role="viewer", modules=[], method="GET", path=facets, query={"platform": "linux"}).allowed
    assert not module_policy.decide(role="viewer", modules=["monitoring"], method="GET", path=facets, query={"platform": "linux"}).allowed
    assert module_policy.decide(role="viewer", modules=["linux"], method="GET", path=facets, query={"platform": "linux"}).allowed
    # Windows sayfasının kendi uç noktası: windows modülü gerekir
    wpath = "/api/v1/windows/servers/hypervisor-facets"
    assert module_policy.decide(role="viewer", modules=["windows"], method="GET", path=wpath).allowed
    assert not module_policy.decide(role="viewer", modules=["linux"], method="GET", path=wpath).allowed


def test_invalid_platform_rejected():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as ei:
        api.hypervisor_facets(
            db=None, platform="virt", q=None, status=None, hide_offline=False, ai_ready=None,
            server_type=None, node_exporter=None, name_mismatch=None, os_filter=None, include_unclassified=False,
        )
    assert ei.value.status_code == 422


# ── PostgreSQL (TEMP tablolar) ────────────────────────────────────────────────

@pytest.fixture()
def db():
    try:
        from app.core.database import engine

        conn = engine.connect()
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"PostgreSQL erişilemiyor: {exc}")
    trans = conn.begin()
    platform_scope.invalidate_platform_id_cache()
    try:
        conn.execute(text("CREATE TEMP TABLE servers (LIKE public.servers) ON COMMIT DROP"))
        conn.execute(text("CREATE TEMP TABLE hypervisors (LIKE public.hypervisors) ON COMMIT DROP"))
        session = Session(bind=conn)
        yield session
        session.close()
    finally:
        trans.rollback()
        conn.close()
        platform_scope.invalidate_platform_id_cache()


def _hv(db, hid, name, htype, status="ONLINE"):
    db.add(Hypervisor(
        id=hid, name=name, hypervisor_type=htype, hostname="vcenter.secret.local",
        ip_address="10.99.99.99", username="root-user-x", password="SECRET-PW-123",
        connection_config={"token": "TOKEN-ABC"}, status=status,
    ))
    db.flush()


def _srv(db, sid, name, hv=None, **kw):
    kw.setdefault("os_type", "rhel")
    kw.setdefault("status", "ONLINE")
    db.add(Server(id=sid, name=name, hypervisor_id=hv, **kw))
    db.flush()


@pytest.fixture()
def seeded(db):
    _hv(db, 1, "vc-office", HypervisorType.VMWARE)
    _hv(db, 2, "vc-fake", HypervisorType.VMWARE, status="fake")
    _hv(db, 3, "olvm", HypervisorType.KVM)
    _hv(db, 4, "ocp-fake", HypervisorType.OPENSHIFT_VIRT, status="fake")
    _hv(db, 5, "hv-empty", HypervisorType.HYPERV)
    sid = 100
    for hv, n, off in ((1, 3, 1), (2, 5, 2), (3, 2, 0), (4, 4, 4)):
        for i in range(n):
            sid += 1
            _srv(db, sid, f"s{hv}-{i}", hv=hv, status="OFFLINE" if i < off else "ONLINE")
    _srv(db, 200, "bare-1")  # hypervisor yok
    _srv(db, 201, "bare-2", status="OFFLINE")
    _srv(db, 300, "win-1", hv=1, os_type="Microsoft Windows Server 2022 Standard")  # linux kapsamı dışı
    return db


def _facets(db, **kw):
    return api.build_hypervisor_facets(db, "linux", **kw)


def _env_counts(res):
    return {e["id"]: e["count"] for g in res["groups"] for e in g["environments"]}


def test_facet_counts_and_groups(seeded):
    res = _facets(seeded)
    assert _env_counts(res) == {1: 3, 2: 5, 3: 2, 4: 4, 5: 0}
    assert res["unassigned_count"] == 2
    assert [g["type"] for g in res["groups"]] == ["vmware", "kvm", "openshift_virt", "hyperv"]
    assert res["groups"][0]["label"] == "VMware vCenter"
    vmware = res["groups"][0]["environments"]
    assert [e["name"] for e in vmware] == ["vc-fake", "vc-office"]  # ada göre sıralı
    assert {e["name"]: e["status"] for e in vmware} == {"vc-office": "ONLINE", "vc-fake": "fake"}
    assert set(res.keys()) == {"groups", "unassigned_count"}


def test_facet_windows_server_not_counted_in_linux(seeded):
    assert _env_counts(_facets(seeded))[1] == 3  # win-1 (hv=1) sayılmaz


def test_facet_respects_other_filters_but_not_hypervisor(seeded):
    res = _facets(seeded, hide_offline=True)
    assert _env_counts(res) == {1: 2, 2: 3, 3: 2, 4: 0, 5: 0}
    assert res["unassigned_count"] == 1
    assert _facets(seeded, q="bare")["unassigned_count"] == 2
    assert _env_counts(_facets(seeded, q="s2-"))[2] == 5
    assert _env_counts(_facets(seeded, status="OFFLINE")) == {1: 1, 2: 2, 3: 0, 4: 4, 5: 0}


def test_facet_os_filter(seeded):
    _srv(seeded, 400, "odd", hv=3, os_type="other")
    assert _env_counts(_facets(seeded, os_filter="other"))[3] == 1
    assert _env_counts(_facets(seeded, os_filter="linux"))[3] == 2


def test_facet_no_credential_leak(seeded):
    res = _facets(seeded)
    blob = json.dumps(res)
    for secret in SECRETS:
        assert secret not in blob
    for g in res["groups"]:
        assert set(g.keys()) == {"type", "label", "environments"}
        for e in g["environments"]:
            assert set(e.keys()) == {"id", "name", "status", "count"}


def test_facet_dynamic_types(db):
    for i, t in enumerate(HypervisorType, start=1):
        _hv(db, i, f"env-{t.value}", t)
    res = _facets(db)
    assert {g["type"] for g in res["groups"]} == {t.value for t in HypervisorType}
    assert res["unassigned_count"] == 0


def _ids(db, **kw):
    q = api._apply_server_list_filters(db.query(Server), **kw)
    return {s.name for s in q.all()}


def test_hypervisor_ids_filter(seeded):
    assert _ids(seeded, hypervisor_ids="3") == {"s3-0", "s3-1"}
    assert len(_ids(seeded, hypervisor_ids="1,3")) == 3 + 2 + 1  # +win-1 (platform filtresi yok)


def test_hypervisor_ids_plus_unassigned_is_or(seeded):
    got = _ids(seeded, hypervisor_ids="3", unassigned_hypervisor=True)
    assert got == {"s3-0", "s3-1", "bare-1", "bare-2"}
    assert _ids(seeded, unassigned_hypervisor=True) == {"bare-1", "bare-2"}


def test_hypervisor_ids_unknown_and_invalid(seeded):
    assert _ids(seeded, hypervisor_ids="99999") == set()  # bilinmeyen id → boş sonuç
    assert _ids(seeded, hypervisor_ids="99999", unassigned_hypervisor=True) == {"bare-1", "bare-2"}
    # yalnızca geçersiz değerler → filtre yok sayılır (tüm kayıtlar)
    assert len(_ids(seeded, hypervisor_ids="abc,-1,0")) == 3 + 5 + 2 + 4 + 2 + 1
    # karışık: geçerli olan uygulanır
    assert _ids(seeded, hypervisor_ids="abc,3") == {"s3-0", "s3-1"}


def test_hypervisor_types_backward_compatible(seeded):
    assert len(_ids(seeded, hypervisor_types="kvm")) == 2
    assert len(_ids(seeded, hypervisor_types="vmware")) == 3 + 5 + 1


def test_windows_facets_use_windows_row_set(db):
    _hv(db, 1, "vc", HypervisorType.VMWARE)
    _srv(db, 1, "w1", hv=1, os_type="Microsoft Windows Server 2022 Standard")
    _srv(db, 2, "w2", hv=None, os_type="windows")
    _srv(db, 3, "l1", hv=1, os_type="rhel")
    try:
        res = api.build_hypervisor_facets(db, "windows")
    except Exception as exc:  # WinRM global ayarı vb. ortam bağımlılığı
        pytest.skip(f"windows satırları üretilemedi: {exc}")
    assert _env_counts(res) == {1: 1}
    assert res["unassigned_count"] == 1
