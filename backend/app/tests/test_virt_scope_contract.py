"""Kapsam sözleşmesi — MATRİS testi.

Tek bir değişmezi korur:

    Üretilen çıktıda (deterministik tablo veya bağlam bloğu) kapsam DIŞI
    hiçbir varlık adı geçmez.

Neden matris: tek örnek (ör. "web01'in diskleri hangi datastore'da") üzerinden
yazılan testler yalnızca o vakayı kapatır. Kapsam boyutu × alan kümesi ×
granülerlik kombinasyonlarını birlikte denemek, yeni bir bileşen eklendiğinde
sızıntının test seviyesinde yakalanmasını sağlar — düzeltmenin "tek soruya
yama" olmadığının kanıtı budur.
"""
import pytest

from app.services import virt_inventory_contract as vic
from app.services import virt_scope as vs

# ── Sabit fikstür: 3 VM, 2 host, 3 datastore, 2 cluster ─────────────────────
VMS = [
    {
        "name": "web01", "ip": "10.0.0.11", "host": "esx01", "cluster": "PROD",
        "datastore": "NVME_DS", "vcpu": 4, "memory_mb": 8192, "disk_gb": 140,
        "disks": [
            {"label": "Hard disk 1", "capacity_gb": 40, "thin": True, "datastore": "NVME_DS"},
            {"label": "Hard disk 2", "capacity_gb": 100, "thin": False, "datastore": "SSD_DS"},
        ],
    },
    {
        "name": "db01", "ip": "10.0.0.12", "host": "esx02", "cluster": "PROD",
        "datastore": "SATA_DS", "vcpu": 8, "memory_mb": 16384, "disk_gb": 500,
        "disks": [
            {"label": "Hard disk 1", "capacity_gb": 500, "thin": False, "datastore": "SATA_DS"},
        ],
    },
    {
        "name": "test01", "ip": "10.0.0.13", "host": "esx02", "cluster": "DEV",
        "datastore": "SATA_DS", "vcpu": 2, "memory_mb": 4096, "disk_gb": 60,
        "disks": [
            {"label": "Hard disk 1", "capacity_gb": 60, "thin": True, "datastore": "SATA_DS"},
        ],
    },
]

ALL_VM_NAMES = {v["name"] for v in VMS}
ALL_HOSTS = {"esx01", "esx02"}
ALL_DATASTORES = {"NVME_DS", "SSD_DS", "SATA_DS"}


def _render(message, filters, *, fields=None):
    """Mesaj + kapsam → deterministik VM tablosu (prod yolunun aynısı)."""
    scope = vs.resolve_scope(None, message, filters=filters)
    flds = fields if fields is not None else vic.detect_requested_vm_fields(
        message, filters=filters,
    )
    rows = vs.filter_rows("vm", VMS, scope)
    return vic.format_vm_table(
        rows, flds, filter_note=vs.scope_note(scope), scope=scope,
    ), scope, rows


def _out_of_scope_names(text, expected_names):
    """Çıktıda görünen ama kapsamda OLMAYAN VM adları."""
    return {n for n in ALL_VM_NAMES - set(expected_names) if n in text}


# ── 1) Kapsam boyutu × alan kümesi matrisi ──────────────────────────────────
@pytest.mark.parametrize(
    "message,filters,expected",
    [
        # VM kapsamı
        ("web01'in ip adresi nedir", {"vm_name": "web01"}, {"web01"}),
        ("web01 disk boyutu ve datastore", {"vm_name": "web01"}, {"web01"}),
        ("sadece web01 için cpu ram ve ip bilgisi", {"vm_name": "web01"}, {"web01"}),
        # host kapsamı
        ("esx01 üzerindeki vm'leri listele", {"host_name": "esx01"}, {"web01"}),
        ("esx02'deki vm'lerin datastore'ları", {"host_name": "esx02"}, {"db01", "test01"}),
        # cluster kapsamı
        ("DEV cluster'daki vm'ler", {"cluster": "DEV"}, {"test01"}),
        ("PROD kümesindeki vm'lerin ip ve ram bilgisi", {"cluster": "PROD"}, {"web01", "db01"}),
        # datastore kapsamı
        ("NVME_DS'de hangi vm'ler var", {"datastore": "NVME_DS"}, {"web01"}),
        ("SATA_DS üzerindeki vm'lerin disk boyutları", {"datastore": "SATA_DS"}, {"db01", "test01"}),
        # çoklu boyut
        (
            "PROD cluster'ında esx02 üzerindeki vm'ler",
            {"cluster": "PROD", "host_name": "esx02"},
            {"db01"},
        ),
        # kapsamsız
        ("tüm vm'lerin datastore bilgisi", {}, ALL_VM_NAMES),
    ],
)
def test_no_out_of_scope_entity_in_output(message, filters, expected):
    text, scope, rows = _render(message, filters)
    assert {r["name"] for r in rows} == expected
    assert not _out_of_scope_names(text, expected), text


# ── 2) Granülerlik: disk başına satır + datastore kolonu ────────────────────
def test_child_granularity_gives_one_row_per_disk_with_datastore():
    msg = "web01'in tüm diskleri ve bu disklerin bulunduğu datastore bilgisi"
    text, scope, rows = _render(msg, {"vm_name": "web01"})
    assert scope.is_child() and scope.child == "disks"
    # İki disk → iki satır, ikisinin de datastore'u görünür
    assert "Hard disk 1" in text and "Hard disk 2" in text
    assert "NVME_DS" in text and "SSD_DS" in text
    # Kapsam dışı VM/datastore yok
    assert "db01" not in text and "SATA_DS" not in text


def test_entity_granularity_when_no_pivot_field_requested():
    # "disk boyutu" disk başına datastore istemiyor → satır = VM
    _, scope, _ = _render("web01 disk boyutu nedir", {"vm_name": "web01"})
    assert scope.granularity == "entity"


# ── 3) Alan kuralı: datastore artık koşulsuz yasaklı DEĞİL ──────────────────
def test_datastore_column_present_when_asked_without_scope():
    fields = vic.detect_requested_vm_fields("vm'ler hangi datastore'da", filters={})
    assert "datastore" in fields


def test_datastore_column_present_when_scope_is_another_dimension():
    fields = vic.detect_requested_vm_fields(
        "web01'in datastore bilgisi", filters={"vm_name": "web01"},
    )
    assert "datastore" in fields


def test_constant_scope_column_collapses_into_filter_note():
    # "NVME_DS'de hangi vm'ler var" → Datastore kolonu her satırda aynı olur,
    # bu yüzden kolon gizlenir ama değer filtre notunda görünür.
    text, scope, rows = _render("NVME_DS'de hangi vm'ler var", {"datastore": "NVME_DS"})
    assert "_Filtre: datastore=NVME_DS_" in text
    header = [ln for ln in text.splitlines() if ln.startswith("| VM Adı")][0]
    assert "Datastore" not in header


def test_varying_scope_column_is_kept():
    # Kapsam host; datastore satırdan satıra değişiyor → kolon KORUNUR.
    text, _, _ = _render("esx02'deki vm'lerin datastore'ları", {"host_name": "esx02"})
    header = [ln for ln in text.splitlines() if ln.startswith("| VM Adı")][0]
    assert "Datastore" in header


# ── 4) Jenerik satır filtresi + bölüm seviyesi karar ────────────────────────
def test_row_in_scope_uses_child_collection_for_datastore():
    scope = vs.Scope(filters={"datastore": "SSD_DS"})
    assert vs.row_in_scope("vm", VMS[0], scope) is True   # 2. diski SSD_DS'de
    assert vs.row_in_scope("vm", VMS[1], scope) is False


def test_unsupported_dimension_marks_section_not_allowed():
    scope = vs.Scope(filters={"vm_name": "web01"})
    # Datastore satırı `vm_name` boyutunu ifade edemez → bölüm filtresiz
    # basılmak yerine düşmeli.
    assert vs.unsupported_dimensions("datastore", scope) == ["vm_name"]
    assert vs.section_allowed("datastore", scope) is False
    assert vs.section_allowed("vm", scope) is True


def test_tool_args_derive_from_registry():
    scope = vs.Scope(filters={"host_name": "esx02", "datastore": "SATA_DS"})
    assert vs.tool_args("vm", scope) == {"host_name": "esx02", "datastore": "SATA_DS"}
    assert vs.tool_args("datastore", scope) == {"name_filter": "SATA_DS"}
    assert vs.tool_args("host", scope) == {"name_filter": "esx02"}


# ── 5) Kilit ("sadece/yalnızca") ────────────────────────────────────────────
@pytest.mark.parametrize(
    "message,expected",
    [
        ("sadece web01 için datastore bilgisi", True),
        ("yalnızca web01'i göster", True),
        ("bir tek web01 lazım", True),
        ("web01 ve diğer vm'leri karşılaştır", False),
    ],
)
def test_lock_detection(message, expected):
    scope = vs.resolve_scope(None, message, filters={"vm_name": "web01"})
    assert scope.locked is expected


def test_lock_requires_resolved_scope():
    # Kapsam yoksa "sadece" kelimesi kilit anlamına gelmez.
    scope = vs.resolve_scope(None, "sadece açık olan vm'leri listele", filters={})
    assert scope.locked is False


# ── 6) Kapsam prefetch argümanlarına ve child alanına yansır ───────────────
def test_prefetch_forces_child_collection_for_per_disk_question():
    scope = vs.resolve_scope(
        None, "web01'in diskleri hangi datastore'da", filters={"vm_name": "web01"},
    )
    name, args = vic.prefetch_spec(vic.KIND_VM_DISK, scope=scope)
    assert name == "db_list_vms"
    assert args["include_disks"] is True
    assert args["name_filter"] == "web01"


def test_inventory_kind_prefers_vm_disk_when_vm_named(monkeypatch):
    # "web01'in diskleri hangi datastore'da" içinde "vm" kelimesi GEÇMİYOR;
    # eski kod bu yüzden saf datastore listesine düşüyordu.
    scope = vs.Scope(filters={"vm_name": "web01"}, granularity="child", child="disks",
                     child_fields=["label", "capacity_gb", "datastore"])
    kind = vic.detect_virt_inventory_kind(
        "web01'in diskleri hangi datastore'da bulunuyor listele", scope=scope,
    )
    assert kind == vic.KIND_VM_DISK
