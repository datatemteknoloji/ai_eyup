"""virt_inventory_contract — genel kapsam/granülerlik testleri.

Kullanıcı şikayeti: "NVME_DS'de hangi vmlere ait diskler var" sorusu TÜM
datastore'lardaki TÜM VM'lerin disk kırılımını döndürüyordu (kapsam + detay
hatası). Bu testler GENEL çözümü doğrular: (1) filters ile kapsam daraltma
her varlık tipi için çalışır, (2) fields ile yalnız istenen kolonlar render
edilir — sabit şablon yok.
"""
from app.services import virt_inventory_contract as vic
from app.services.chat_output_directives import OutputDirective


# ── detect_requested_vm_fields ───────────────────────────────────────────────

def test_membership_question_returns_name_only():
    # Kullanıcının tam şikayeti: "hangi vmlere ait bilgiler bulunuyor" — disk
    # kelimesi YOK, yalnız isim listesi beklenir.
    fields = vic.detect_requested_vm_fields("NVME_DS datastore'unda hangi vmlere ait bilgiler bulunuyor")
    assert fields == ["name"]


def test_disk_question_adds_disk_group():
    fields = vic.detect_requested_vm_fields("NVME_DS'de hangi vmlere ait diskler bulunuyor?")
    assert fields[0] == "name"
    assert "disk_gb" in fields
    assert "disk_count" in fields
    assert "disk_breakdown" in fields
    # datastore kelimesi geçmiyor bu cümlede zaten; yine de datastore kolon olarak eklenmemeli
    assert "datastore" not in fields


def test_datastore_keyword_is_scope_not_a_column():
    # "datastore" kelimesi kapsam belirtir (extract_entity_filters ile tüketilir),
    # kolon olarak tekrar İSTENMEZ.
    fields = vic.detect_requested_vm_fields("bu datastorede hangi vmlere ait bilgiler bulunuyor")
    assert fields == ["name"]


def test_ip_question():
    fields = vic.detect_requested_vm_fields("bu vmlerin ip adresleri nedir?")
    assert "ip" in fields
    assert "disk_gb" not in fields


def test_power_state_question():
    fields = vic.detect_requested_vm_fields("hangi vmler açık durumda?")
    assert "power_state" in fields


def test_no_false_positive_ip_inside_word():
    # "tip" içinde "ip" var ama word-boundary sayesinde tetiklenmemeli.
    fields = vic.detect_requested_vm_fields("bu vmlerin türü/tipi nedir?")
    assert "ip" not in fields


def test_host_keyword_suppressed_when_used_as_scope():
    # "esxi host'undaki" burada KAPSAM belirtiyor (192.168.1.101 zaten
    # extract_entity_filters ile host_name filtresi olarak çözülmüş) —
    # kolon olarak TEKRAR eklenmemeli; kullanıcı ayrıca "sadece isim" da dedi.
    fields = vic.detect_requested_vm_fields(
        "192.168.1.101 esxi host'undaki hangi vmler var, sadece isimlerini listele",
        filters={"host_name": "192.168.1.101"},
    )
    assert fields == ["name"]


def test_host_keyword_kept_when_no_specific_host_matched():
    # Belirli bir host adı YOK — "hangi host'ta" genel bir ATTRIBUTE isteği,
    # bu yüzden kolon olarak eklenmeli.
    fields = vic.detect_requested_vm_fields("vmler hangi esxi host'ta çalışıyor?", filters={})
    assert "host" in fields


def test_explicit_only_name_request_overrides_everything():
    fields = vic.detect_requested_vm_fields(
        "bu datastoredeki vmlerin disklerini ve IP'lerini de yaz ama sadece isim yeterli",
    )
    assert fields == ["name"]


# ── format_vm_table — yalnız istenen kolonlar ────────────────────────────────

def test_format_vm_table_name_only_is_minimal():
    vms = [{"name": "web01", "ip": "1.2.3.4", "disk_gb": 100}]
    out = vic.format_vm_table(vms, ["name"])
    assert "VM Adı" in out
    assert "IP" not in out
    assert "Disk" not in out
    assert "web01" in out
    assert "1.2.3.4" not in out


def test_format_vm_table_disk_group_renders_breakdown():
    vms = [{
        "name": "web01", "disk_gb": 120, "disk_count": 2,
        "disks": [{"label": "Hard disk 1", "capacity_gb": 100}, {"label": "Hard disk 2", "capacity_gb": 20}],
    }]
    out = vic.format_vm_table(vms, ["name", "disk_count", "disk_gb", "disk_breakdown"])
    assert "Hard disk 1: 100" in out
    assert "Hard disk 2: 20" in out
    assert "provisioned disk envanteridir" in out


def test_format_vm_table_filter_note_shown():
    out = vic.format_vm_table([{"name": "web01"}], ["name"], filter_note="datastore=NVME_DS")
    assert "Filtre: datastore=NVME_DS" in out


# ── prefetch_spec — filters gerçek tool argümanlarına akar ───────────────────

def test_prefetch_spec_applies_datastore_filter():
    tool, args = vic.prefetch_spec(
        vic.KIND_VM_DISK, filters={"datastore": "NVME_DS"}, fields=["name"],
    )
    assert tool == "db_list_vms"
    assert args["datastore"] == "NVME_DS"
    assert args["fields"] == ["datastore", "name"]  # savunmacı filtre alanı da çekilir
    assert args["include_disks"] is False


def test_prefetch_spec_applies_vm_name_filter():
    tool, args = vic.prefetch_spec(
        vic.KIND_VM_DISK, filters={"vm_name": "web01"}, fields=["name", "disk_count", "disk_gb", "disk_breakdown"],
    )
    assert args["name_filter"] == "web01"
    assert args["include_disks"] is True
    assert "disks" in args["fields"]


def test_prefetch_spec_datastore_kind_uses_name_filter():
    tool, args = vic.prefetch_spec(vic.KIND_DATASTORE, filters={"datastore": "NVME_DS"})
    assert tool == "db_list_datastores"
    assert args["name_filter"] == "NVME_DS"


def test_prefetch_spec_esx_host_kind_uses_name_filter():
    tool, args = vic.prefetch_spec(vic.KIND_ESX_HOST, filters={"host_name": "esx03"})
    assert tool == "db_list_esx_hosts"
    assert args["name_filter"] == "esx03"


def test_prefetch_spec_no_filters_backward_compatible():
    tool, args = vic.prefetch_spec(vic.KIND_VM_DISK)
    assert tool == "db_list_vms"
    assert "datastore" not in args
    assert "name_filter" not in args


# ── materialize_from_tool_results — kapsam + granülerlik birlikte ───────────

def _vms_payload():
    return {
        "ok": True,
        "as_of": "2026-09-04T00:00:00+03:00",
        "vms": [
            {"name": "web01", "datastore": "NVME_DS", "disk_gb": 100, "disk_count": 1},
            {"name": "db02", "datastore": "SATA_DS", "disk_gb": 200, "disk_count": 1},
        ],
    }


def test_materialize_scopes_by_datastore_defensively():
    # DB filtresi bir sebeple uygulanmasa/atlanmış olsa bile 2. savunma satırı
    # kapsamı daraltmalı (SATA_DS'deki db02 dışarıda kalmalı).
    tool_results = [{"tool": "db_list_vms", "result": _vms_payload()}]
    out = vic.materialize_from_tool_results(
        vic.KIND_VM_DISK, tool_results,
        filters={"datastore": "NVME_DS"}, fields=["name"],
    )
    assert "web01" in out
    assert "db02" not in out
    assert "Toplam:** 1 VM" in out


def test_materialize_renders_only_requested_fields():
    tool_results = [{"tool": "db_list_vms", "result": _vms_payload()}]
    out = vic.materialize_from_tool_results(
        vic.KIND_VM_DISK, tool_results,
        filters={"datastore": "NVME_DS"}, fields=["name"],
    )
    assert "Disk" not in out  # yalnız isim istendi, disk kolonu YOK


def test_materialize_disk_group_shows_breakdown():
    payload = {
        "ok": True,
        "vms": [{
            "name": "web01", "datastore": "NVME_DS", "disk_gb": 120, "disk_count": 2,
            "disks": [{"label": "Hard disk 1", "capacity_gb": 100}, {"label": "Hard disk 2", "capacity_gb": 20}],
        }],
    }
    tool_results = [{"tool": "db_list_vms", "result": payload}]
    out = vic.materialize_from_tool_results(
        vic.KIND_VM_DISK, tool_results,
        filters={"datastore": "NVME_DS"},
        fields=["name", "disk_count", "disk_gb", "disk_breakdown"],
    )
    assert "Hard disk 1: 100" in out


def test_materialize_no_fields_falls_back_to_legacy_template():
    # Geriye dönük uyumluluk: fields=None → eski sabit şablon.
    tool_results = [{"tool": "db_list_vms", "result": _vms_payload()}]
    out = vic.materialize_from_tool_results(vic.KIND_VM_DISK, tool_results)
    assert "Diskler (label: GB)" in out
    assert "web01" in out and "db02" in out  # filtre yok → hepsi


def test_materialize_datastore_kind_defensive_filter():
    payload = {
        "ok": True,
        "datastores": [
            {"name": "NVME_DS", "capacity_gb": 500},
            {"name": "SATA_DS", "capacity_gb": 1000},
        ],
    }
    tool_results = [{"tool": "db_list_datastores", "result": payload}]
    out = vic.materialize_from_tool_results(
        vic.KIND_DATASTORE, tool_results, filters={"datastore": "NVME_DS"},
    )
    assert "NVME_DS" in out
    assert "SATA_DS" not in out


def test_materialize_json_directive_returns_json_block():
    tool_results = [{"tool": "db_list_vms", "result": _vms_payload()}]
    out = vic.materialize_from_tool_results(
        vic.KIND_VM_DISK, tool_results,
        filters={"datastore": "NVME_DS"}, fields=["name"], directive=OutputDirective.JSON,
    )
    assert out.startswith("```json")
    assert '"name": "web01"' in out
    assert "db02" not in out  # kapsam daraltma JSON'da da geçerli


def test_materialize_brief_directive_returns_short_sentence():
    tool_results = [{"tool": "db_list_vms", "result": _vms_payload()}]
    out = vic.materialize_from_tool_results(
        vic.KIND_VM_DISK, tool_results,
        filters={"datastore": "NVME_DS"}, fields=["name"], directive=OutputDirective.BRIEF,
    )
    assert "web01" in out
    assert "toplam 1 kayıt" in out
    assert len(out.splitlines()) <= 2


def test_materialize_datastore_json_directive():
    payload = {"ok": True, "datastores": [{"name": "NVME_DS", "capacity_gb": 500}]}
    tool_results = [{"tool": "db_list_datastores", "result": payload}]
    out = vic.materialize_from_tool_results(
        vic.KIND_DATASTORE, tool_results, directive=OutputDirective.JSON,
    )
    assert out.startswith("```json")
    assert "NVME_DS" in out


def test_materialize_esx_host_kind_defensive_filter():
    payload = {
        "ok": True,
        "hosts": [{"name": "esx03"}, {"name": "esx04"}],
    }
    tool_results = [{"tool": "db_list_esx_hosts", "result": payload}]
    out = vic.materialize_from_tool_results(
        vic.KIND_ESX_HOST, tool_results, filters={"host_name": "esx03"},
    )
    assert "esx03" in out
    assert "esx04" not in out
