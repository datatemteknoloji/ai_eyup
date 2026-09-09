"""hypervisor_intelligence._apply_entity_scope — entity bazlı context daraltma.

Regresyon: build_context() soru bağımsız olarak TÜM host/VM envanterini
LLM prompt'una dump ediyordu (62 host / 3720 VM'de bu ~90-125K token'a
çıkıyordu). Bu testler, kullanıcı belirli bir host/VM/datastore/cluster adı
verdiğinde detay bölümlerinin yalnızca o kapsama daraltıldığını doğrular —
token maliyeti artık FLEET büyüklüğünden değil sorgunun KAPSAMINDAN bağımsız
olmalı.

İkinci regresyon (kapsam sözleşmesi): kapsam yalnız host/VM listelerine
uygulanıyordu; host listesi datastore/VM kapsamında dokunulmadan kalıyordu.
Artık host listesi de kapsanan VM'lerin çalıştığı host'lardan türetilir ve
türetilemiyorsa BOŞ döner (deny-by-default) — filtresiz tam döküm basılmaz.
"""
import app.services.hypervisor_intelligence as hvi


def _host(name, hypervisor_id=1):
    return {"host": name, "hypervisor_id": hypervisor_id}


def _vm(name, host=None, cluster=None, datastore=None):
    return {"name": name, "host": host, "cluster": cluster, "datastore": datastore}


def test_host_scope_filters_hosts_and_vms(monkeypatch):
    monkeypatch.setattr(
        "app.services.virt_entity_resolver.extract_entity_filters",
        lambda db, msg: {"host_name": "isthol5esxia03"},
    )
    hosts = [_host("isthol5esxia03"), _host("isthol5esxia04")]
    vms = [
        _vm("web01", host="isthol5esxia03"),
        _vm("web02", host="isthol5esxia03"),
        _vm("db01", host="isthol5esxia04"),
    ]
    scoped_hosts, scoped_vms, note, scope = hvi._apply_entity_scope(
        None, "isthol5esxia03 host üzerindeki vmleri sorgula", hosts, vms, intents=["general"],
        vm_names_to_compare=None,
    )
    assert [h["host"] for h in scoped_hosts] == ["isthol5esxia03"]
    assert {v["name"] for v in scoped_vms} == {"web01", "web02"}
    assert note == "host=isthol5esxia03"
    assert scope.filters == {"host_name": "isthol5esxia03"}
    assert scope.locked is False


def test_datastore_scope_narrows_hosts_to_scoped_vms(monkeypatch):
    # Eski davranış: datastore kapsamında host listesi DOKUNULMADAN kalıyordu
    # (tüm ortamın host dökümü prompt'a giriyordu). Yeni davranış: host'lar
    # kapsanan VM'lerin çalıştığı host'lardan türetilir.
    monkeypatch.setattr(
        "app.services.virt_entity_resolver.extract_entity_filters",
        lambda db, msg: {"datastore": "NVME_DS"},
    )
    hosts = [_host("esx01"), _host("esx02")]
    vms = [
        _vm("web01", host="esx01", datastore="NVME_DS"),
        _vm("db01", host="esx02", datastore="SATA_DS"),
    ]
    scoped_hosts, scoped_vms, note, scope = hvi._apply_entity_scope(
        None, "NVME_DS datastoreundaki vmleri göster", hosts, vms, intents=["general"],
        vm_names_to_compare=None,
    )
    assert {v["name"] for v in scoped_vms} == {"web01"}
    assert [h["host"] for h in scoped_hosts] == ["esx01"]
    assert note == "datastore=NVME_DS"


def test_datastore_scope_matches_child_disk_datastore(monkeypatch):
    # Bir VM'in ikinci diski başka datastore'da olabilir; VM seviyesindeki
    # `datastore` alanı eşleşmese de disk kaydı eşleşiyorsa VM kapsamdadır.
    monkeypatch.setattr(
        "app.services.virt_entity_resolver.extract_entity_filters",
        lambda db, msg: {"datastore": "SSD_DS"},
    )
    vm = _vm("web01", host="esx01", datastore="NVME_DS")
    vm["disks"] = [
        {"label": "Hard disk 1", "capacity_gb": 40, "datastore": "NVME_DS"},
        {"label": "Hard disk 2", "capacity_gb": 100, "datastore": "SSD_DS"},
    ]
    hosts = [_host("esx01")]
    scoped_hosts, scoped_vms, note, scope = hvi._apply_entity_scope(
        None, "SSD_DS üzerinde hangi vm diskleri var", hosts, [vm, _vm("db01")],
        intents=["general"], vm_names_to_compare=None,
    )
    assert {v["name"] for v in scoped_vms} == {"web01"}


def test_cluster_scope_filters_vms_and_their_hosts(monkeypatch):
    monkeypatch.setattr(
        "app.services.virt_entity_resolver.extract_entity_filters",
        lambda db, msg: {"cluster": "PROD"},
    )
    hosts = [_host("esx01"), _host("esx02"), _host("esx03")]
    vms = [
        _vm("web01", host="esx01", cluster="PROD"),
        _vm("db01", host="esx02", cluster="DEV"),
    ]
    scoped_hosts, scoped_vms, note, scope = hvi._apply_entity_scope(
        None, "PROD cluster'daki vmler", hosts, vms, intents=["general"], vm_names_to_compare=None,
    )
    assert {v["name"] for v in scoped_vms} == {"web01"}
    assert [h["host"] for h in scoped_hosts] == ["esx01"]
    assert note == "cluster=PROD"


def test_vm_name_scope_filters_to_single_vm_and_its_host(monkeypatch):
    monkeypatch.setattr(
        "app.services.virt_entity_resolver.extract_entity_filters",
        lambda db, msg: {"vm_name": "web01"},
    )
    hosts = [_host("esx01"), _host("esx02")]
    vms = [_vm("web01", host="esx01"), _vm("web02", host="esx02")]
    scoped_hosts, scoped_vms, note, scope = hvi._apply_entity_scope(
        None, "web01 nerede çalışıyor?", hosts, vms, intents=["general"], vm_names_to_compare=None,
    )
    assert {v["name"] for v in scoped_vms} == {"web01"}
    assert [h["host"] for h in scoped_hosts] == ["esx01"]
    assert note == "vm=web01"


def test_explicit_only_wording_locks_scope(monkeypatch):
    monkeypatch.setattr(
        "app.services.virt_entity_resolver.extract_entity_filters",
        lambda db, msg: {"vm_name": "web01"},
    )
    hosts = [_host("esx01")]
    vms = [_vm("web01", host="esx01"), _vm("web02", host="esx01")]
    _, scoped_vms, note, scope = hvi._apply_entity_scope(
        None, "sadece web01 için datastore bilgisini ver", hosts, vms,
        intents=["general"], vm_names_to_compare=None,
    )
    assert {v["name"] for v in scoped_vms} == {"web01"}
    assert scope.locked is True


def test_no_entity_mentioned_returns_full_unscoped_lists(monkeypatch):
    monkeypatch.setattr(
        "app.services.virt_entity_resolver.extract_entity_filters",
        lambda db, msg: {},
    )
    hosts = [_host("esx01"), _host("esx02")]
    vms = [_vm("web01"), _vm("web02")]
    scoped_hosts, scoped_vms, note, scope = hvi._apply_entity_scope(
        None, "tüm vm'leri listele", hosts, vms, intents=["general"], vm_names_to_compare=None,
    )
    assert scoped_hosts == hosts
    assert scoped_vms == vms
    assert note is None
    assert scope.is_empty()


def test_compare_vms_intent_bypasses_scoping_entirely(monkeypatch):
    # compare_vms kendi hedef seçimini yapar (bkz. build_context çağıran kod);
    # entity scope bu intent'te devreye GİRMEMELİ.
    monkeypatch.setattr(
        "app.services.virt_entity_resolver.extract_entity_filters",
        lambda db, msg: {"host_name": "esx01"},
    )
    hosts = [_host("esx01"), _host("esx02")]
    vms = [_vm("web01", host="esx01"), _vm("db01", host="esx02")]
    scoped_hosts, scoped_vms, note, scope = hvi._apply_entity_scope(
        None, "web01 ile db01'i karşılaştır", hosts, vms,
        intents=["compare_vms"], vm_names_to_compare=["web01", "db01"],
    )
    assert scoped_hosts == hosts
    assert scoped_vms == vms
    assert note is None
    assert scope.is_empty()


def test_scope_falls_back_to_full_when_no_match_found(monkeypatch):
    # extract_entity_filters bir isim döndürse bile esx_hosts/vms içinde
    # gerçek bir eşleşme yoksa (veri tutarsızlığı/edge case), sessizce boş
    # context üretmek yerine TAM listeye düşülür (veri kaybı yerine güvenli
    # varsayılan).
    monkeypatch.setattr(
        "app.services.virt_entity_resolver.extract_entity_filters",
        lambda db, msg: {"host_name": "does-not-exist"},
    )
    hosts = [_host("esx01")]
    vms = [_vm("web01", host="esx01")]
    scoped_hosts, scoped_vms, note, scope = hvi._apply_entity_scope(
        None, "does-not-exist host'taki vmler", hosts, vms, intents=["general"],
        vm_names_to_compare=None,
    )
    assert scoped_hosts == hosts
    assert scoped_vms == vms
    assert note is None
    assert scope.is_empty()
