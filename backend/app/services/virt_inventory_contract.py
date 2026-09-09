"""Virt envanter sözleşmesi — sınıf bazlı (tek soruya yama değil).

Amaç: VM disk / datastore / ESX özet gibi SoT sorularında
  1) Doğru db_* tool verisinin garanti çekilmesi (prefetch)
  2) Cevabın tool JSON'undan üretilmesi (model 'eksik/uydurma' yazamasın)
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Sequence, Tuple


# ── Niyet sınıfları ──────────────────────────────────────────────────────────
KIND_VM_DISK = "vm_disk"
KIND_DATASTORE = "datastore"
KIND_ESX_HOST = "esx_host"
KIND_VM_LIST = "vm_list"

_VM_RE = re.compile(
    r"(?<![a-z0-9_])vm(?:s|ler|leri|lerin|lerde|lerdeki|ye|yi|nin|nın|nün|'s|’s)?(?![a-z0-9_])"
    r"|sanal\s*makine|virtual\s*machine",
    re.I,
)


def detect_virt_inventory_kind(
    message: str,
    *,
    scope: Optional["object"] = None,
) -> Optional[str]:
    """Soru virt DB envanter sınıfına giriyor mu? (perf/QueryPerf hariç)

    `scope` verilirse kapsam, kelime kalıplarından ÖNCE gelir: mesajda gerçek
    bir VM adı çözülmüşse ve soru disk/datastore'a değiniyorsa sınıf
    KIND_VM_DISK olur. Aksi hâlde "web01'in diskleri hangi datastore'da"
    sorusu — içinde "vm" kelimesi geçmediği için — saf datastore listesine
    düşüyor ve tüm datastore'lar basılıyordu.
    """
    from app.services.chat_intent import (
        ChatIntentKind,
        classify_chat_intent,
        should_skip_inventory_prefetch,
    )

    if should_skip_inventory_prefetch(message):
        return None

    intent = classify_chat_intent(message)
    # Savunma: yalnızca açık envanter / canlı-liste niyetinde prefetch
    if intent.kind not in (ChatIntentKind.INVENTORY, ChatIntentKind.LIVE):
        return None

    m = (message or "").lower()
    if not m.strip():
        return None

    # Kapsam, kelime kalıplarından ÖNCE gelir: gerçek bir VM adı çözülmüşse
    # disk/datastore sorusu VM disk envanteridir, saf datastore listesi değil.
    scope_filters: Dict[str, str] = dict(getattr(scope, "filters", {}) or {})
    if scope_filters.get("vm_name"):
        if getattr(scope, "is_child", None) and scope.is_child():
            return KIND_VM_DISK
        if any(k in m for k in ("disk", "vmdk", "datastore", "depolama", "storage")):
            return KIND_VM_DISK

    # Snapshot/olay/alarm soruları VM_LIST/VM_DISK genel eşleşmesine (aşağıdaki
    # "vm" + "kaç/liste" bloğu) ASLA düşmemeli — bu sınıfların kendi özel
    # handler'ları (QA_RULES: h_snapshot_vms / h_critical_alarms_24h, ya da
    # agentic loop'taki vcenter_snapshot_summary/db_list_critical_events) var.
    # Gözlemlenen regresyon: "VM'lerde aktif snapshot var mı, kaç tane?" —
    # "vm" + "kaç" eşleşip generic VM listesine dönüşüyordu, snapshot hiç
    # sorgulanmıyordu. Bu blok o hijack'i engeller (fall-through → None →
    # QA_RULES / agentic tool loop devreye girer).
    if any(k in m for k in ("snapshot", "olay", "event", "alarm")) and not any(
        k in m for k in ("disk", "vmdk", "datastore")
    ):
        return None

    # Canlı perf / latency bağlamı — provisioned disk envanteri değil
    if any(k in m for k in (
        "disk rate", "disk requests", "disk latency", "disk gecikme",
        "iops", "queryperf", "kbps", "latency",
    )):
        if not any(k in m for k in (
            "disk adet", "disk sayısı", "disk sayisi", "disk boyutu", "disk boyut",
            "capacity_gb", "vmdk", "provisioned", "hangi vm", "listele",
        )):
            return None

    if any(k in m for k in ("datastore", "datastores", "ds doluluk", "datastore doluluk")):
        # Datastore içindeki VM diskleri → VM disk envanteri; saf DS listesi → datastore
        diskish_vm = any(
            k in m for k in ("disk", "disks", "vmdk", "vm", "sanal")
        ) and any(
            k in m for k in ("içerisinde", "icerisinde", "ait", "hangi", "barındır", "barindir")
        )
        if diskish_vm and (_VM_RE.search(m) or "vm" in m):
            return KIND_VM_DISK
        if intent.kind == ChatIntentKind.INVENTORY:
            return KIND_DATASTORE
        return None

    if any(k in m for k in ("esxi host", "esx host", "host list", "host özet", "host ozet")):
        if "vm" not in m and not _VM_RE.search(m):
            return KIND_ESX_HOST

    diskish = any(
        k in m
        for k in (
            "disk", "disks", "vmdk", "disk_gb", "disk boyutu", "disk boyut",
            "disk adet", "disk sayısı", "disk sayisi", "her bir disk",
            "hard disk", "storage_gb", "provisioned",
        )
    )
    if diskish and (_VM_RE.search(m) or "sanal" in m or "vcenter" in m or "vmware" in m):
        return KIND_VM_DISK

    # "tüm vm'ler" / poweredOn listesi
    #
    # NOT: bu eylem-fiili listesi asla "tam" olamaz (Türkçe'de sonsuz ifade
    # çeşitliliği — sorgula/getir/çek/ilet/çıkar/kontrol et/incele/bak/ver/
    # bul/...). Eksik kalması burada YANLIŞ CEVABA yol açmaz: asıl güvenlik
    # ağı unified_tool_chat.py::_finalize()'daki decouple mekanizmasıdır
    # (bkz. infer_kind_from_tool_call) — model kendi kararıyla db_list_vms
    # çağırırsa, bu regex hiçbir şey yakalamasa bile deterministik tablo yine
    # denenir. Buradaki liste yalnızca PROAKTİF prefetch'i tetikler.
    if _VM_RE.search(m) and any(
        k in m for k in (
            "liste", "list", "kaç", "kac", "özet", "ozet", "hepsi", "tüm", "tum", "table", "/table",
            "sorgula", "getir", "çek", "cek", "ilet", "çıkar", "cikar",
            "kontrol et", "incele", "teyit et", "doğrula", "dogrula",
        )
    ):
        if diskish:
            return KIND_VM_DISK
        return KIND_VM_LIST

    if diskish and any(k in m for k in ("vcenter", "esxi", "esx", "hypervisor", "sanallaş", "sanallas")):
        return KIND_VM_DISK

    return None


def inventory_system_addendum(kind: str) -> str:
    """Tool-loop system ek — prefetch yanında modele de hatırlatma."""
    common = (
        "\n\nVIRT ENVANTER SÖZLEŞMESİ (zorunlu):\n"
        "- Cevabı YALNIZ db_* tool JSON satırlarından kur; RAG/tahmin yok.\n"
        "- Tool'da disk_gb/disk_count doluysa ASLA 'toplanmadı/eksik/bilinmiyor' yazma.\n"
        "- disk_gb null olan satır için 'DB null (sync enrichment gerekir)' de.\n"
        "- Kullanıcı /table veya tablo istediyse markdown tablo üret.\n"
    )
    if kind == KIND_VM_DISK:
        return common + (
            "- VM disk sorusu: db_list_vms (disk_gb, disk_count, disks zorunlu alanlar). "
            "Tek tek db_vm_detail döngüsü YAPMA — liste zaten disks[] içerir.\n"
            "- Her VM için: adet=disk_count, toplam=disk_gb, kırılım=disks[].label/capacity_gb.\n"
        )
    if kind == KIND_DATASTORE:
        return common + "- Datastore: db_list_datastores (capacity/free/usage).\n"
    if kind == KIND_ESX_HOST:
        return common + "- ESXi host: db_list_esx_hosts (fields ile istenen kolonlar).\n"
    if kind == KIND_VM_LIST:
        return common + "- VM listesi: db_list_vms (name, ip, power_state, host, disk_gb).\n"
    return common


def _disk_count(disks: Any, disk_gb: Any) -> Optional[int]:
    if isinstance(disks, list):
        return len(disks)
    if disk_gb is None:
        return None
    return None


def enrich_vm_row(row: Dict[str, Any]) -> Dict[str, Any]:
    """Satıra disk_count ekle (yoksa disks uzunluğundan)."""
    out = dict(row)
    disks = out.get("disks")
    if out.get("disk_count") is None:
        n = _disk_count(disks, out.get("disk_gb"))
        if n is not None:
            out["disk_count"] = n
    return out


def detect_requested_vm_fields(
    message: str,
    *,
    filters: Optional[Dict[str, str]] = None,
) -> List[str]:
    """Kullanıcının mesajdan GERÇEKTEN istediği VM kolonları — genel kural.

    "Bilgi kirliliği" önlemi: hiçbir alan-spesifik kelime yoksa yalnız
    ``name`` döner (ör. "bu datastore'da hangi VM'ler var" → sadece isim
    listesi; "diskleri neler" → isim + disk kırılımı; "IP'leri nedir" →
    isim + IP).

    KAPSAM (scope) ile ALAN (kolon) ayrımı BURADA YAPILMAZ — aynı kelime
    ("datastore"/"host"/"cluster") hem varlığı filtrelemek hem de kolon
    istemek için kullanılabildiğinden, kolonu bastırma kararı veriye bakarak
    render katmanında verilir (`virt_scope.collapse_constant_columns`): kolon,
    o boyut kapsamsa VE tüm satırlarda tek değere düşüyorsa gizlenir, değeri
    filtre notunda gösterilir.

    Neden değişti: eski sürümde `host`/`cluster` için "isim eşleşmediyse kolon
    ekle" koşulu vardı ama `datastore` için karşılığı hiç yoktu — koşullu
    olması gereken kural datastore'da KOŞULSUZ yasağa dönüşmüştü. Bu yüzden
    "VM'ler hangi datastore'da" veya "web01'in diskleri hangi datastore'da"
    gibi meşru sorularda kolon sessizce düşüyordu.

    Ayrıca "sadece/yalnız isim" gibi AÇIK bir minimal istek varsa, diğer
    tüm sinyalleri geçersiz kılıp yalnız ``name`` döner.
    Bu fonksiyon datastore'a özel değildir; herhangi bir VM/disk/ait
    sorusu senaryosunda aynı şekilde çalışır.
    """
    filters = filters or {}
    m = (message or "").lower()

    def has(*keywords: str) -> bool:
        return any(k in m for k in keywords)

    def has_token(*tokens: str) -> bool:
        return any(re.search(r"(?<![a-z0-9_])" + re.escape(t), m) for t in tokens)

    # Açık minimal istek — diğer tüm sinyalleri ezer.
    if has(
        "sadece isim", "sadece ad", "yalnız isim", "yalnızca isim",
        "yalniz isim", "yalnizca isim", "isim yeterli", "ismi yeterli",
        "adı yeterli", "adi yeterli", "sadece vm adı", "sadece vm ismi",
    ):
        return ["name"]

    fields: List[str] = ["name"]
    if has("disk", "vmdk", "boyut", "kapasite", "depolama", "storage", "provisioned", "hard disk"):
        fields += ["disk_count", "disk_gb", "disk_breakdown"]
    if has_token("ip", "adres"):
        fields.append("ip")
    if has("power", "açık", "acik", "kapalı", "kapali", "durum", "status", "poweredon", "poweredoff"):
        fields.append("power_state")
    if has_token("cpu") or has("vcpu", "işlemci", "islemci"):
        fields.append("vcpu")
    if has("ram", "memory", "bellek"):
        fields.append("memory_mb")
    if has("esxi", "esx", "host"):
        fields.append("host")
    if has("cluster", "küme", "kume"):
        fields.append("cluster")
    if has("datastore", "depolama alanı", "depolama alani") or has_token("ds"):
        fields.append("datastore")
    if has("işletim sistemi", "isletim sistemi", "guest os"):
        fields.append("guest_os")
    return list(dict.fromkeys(fields))


def _as_scope(
    filters: Optional[Dict[str, str]] = None,
    scope: Optional["object"] = None,
):
    """`filters` dict'i veya hazır `Scope` → tek tip Scope nesnesi.

    Geriye dönük uyumluluk: bu modülün fonksiyonları uzun süre `filters`
    dict'i aldı; çağıranlar kademeli olarak Scope'a geçiyor.
    """
    from app.services.virt_scope import Scope

    if scope is not None:
        return scope
    return Scope(filters={k: v for k, v in (filters or {}).items() if v})


def _row_matches_filters(
    row: Dict[str, Any],
    filters: Dict[str, str],
    *,
    entity_type: str = "vm",
    scope: Optional["object"] = None,
) -> bool:
    """Savunmacı 2. kontrol — jenerik kapsam filtresine devreder.

    Eski sürüm dört boyutu elle yazılmış `if` bloklarıyla kontrol ediyordu;
    beşinci bir boyut eklendiğinde sessizce geçiyordu. Artık boyutlar
    `virt_scope.SCOPE_DIMENSIONS` kayıt defterinden okunur ve alt koleksiyon
    (ör. bir VM'in diskleri) da kapsama dahil edilir.
    """
    from app.services.virt_scope import row_in_scope

    return row_in_scope(entity_type, row, _as_scope(filters, scope))


def _filter_note(
    filters: Optional[Dict[str, str]] = None,
    scope: Optional["object"] = None,
) -> Optional[str]:
    from app.services.virt_scope import scope_note

    return scope_note(_as_scope(filters, scope))


_VM_FIELD_LABELS: Dict[str, str] = {
    "name": "VM Adı",
    "ip": "IP",
    "power_state": "Power",
    "vcpu": "vCPU",
    "memory_mb": "RAM (MB)",
    "host": "ESXi Host",
    "esxi_host": "ESXi Host",
    "cluster": "Cluster",
    "datastore": "Datastore",
    "hypervisor": "vCenter",
    "guest_os": "Guest OS",
    "disk_count": "Disk Adedi",
    "disk_gb": "Toplam Disk (GB)",
    "disk_breakdown": "Diskler (label: GB)",
}
_VM_NUMERIC_FIELDS = {"vcpu", "memory_mb", "disk_count", "disk_gb"}


def _vm_field_value(v: Dict[str, Any], field: str) -> str:
    if field == "disk_breakdown":
        disks = v.get("disks") if isinstance(v.get("disks"), list) else []
        if not disks:
            return "—"
        return "; ".join(
            f"{(d.get('label') or 'disk')}: {d.get('capacity_gb', '?')}"
            for d in disks
            if isinstance(d, dict)
        ) or "—"
    val = v.get(field)
    if val is None or val == "":
        return "—"
    return str(val)


def format_vm_table(
    vms: Sequence[Dict[str, Any]],
    fields: Sequence[str],
    *,
    as_of: Optional[str] = None,
    filter_note: Optional[str] = None,
    scope: Optional["object"] = None,
) -> str:
    """GENEL VM tablosu — YALNIZ `fields` içinde istenen kolonları render eder.

    Sabit şablon yok: kullanıcı ne istediyse (detect_requested_vm_fields) o
    gösterilir. Bu fonksiyon herhangi bir senaryo (datastore/host/cluster/VM
    adı filtreli veya filtresiz) için aynı şekilde çalışır — genel kuraldır.

    `scope` verilirse iki ek kural işler:
      * Granülerlik `child` ise satır = ALT VARLIK (ör. disk) — bir VM'in
        diskleri farklı datastore'lara yayılabildiği için VM başına tek satır
        yanlış cevap verirdi.
      * Kapsam boyutu olan ve tüm satırlarda tek değere düşen kolon gizlenir;
        değeri filtre notunda görünür (`collapse_constant_columns`).
    """
    from app.services.virt_scope import collapse_constant_columns

    sc = _as_scope(None, scope) if scope is not None else None
    if sc is not None and sc.is_child():
        return _format_vm_child_table(
            vms, sc, as_of=as_of, filter_note=filter_note,
        )

    cols = [f for f in dict.fromkeys(fields) if f in _VM_FIELD_LABELS] or ["name"]
    if sc is not None:
        kept = collapse_constant_columns("vm", list(vms), cols, sc)
        # `name` her zaman kalır (kapsam tek VM olsa bile satırı tanımlar).
        cols = ["name"] + [c for c in kept if c != "name"]
    header = "| " + " | ".join(_VM_FIELD_LABELS[c] for c in cols) + " |"
    sep = "|" + "|".join(("---:" if c in _VM_NUMERIC_FIELDS else "---") for c in cols) + "|"
    lines = ["## VM Listesi (kaynak: db_list_vms)", ""]
    if filter_note:
        lines.append(f"_Filtre: {filter_note}_")
        lines.append("")
    lines += [header, sep]
    for raw in vms:
        v = enrich_vm_row(raw if isinstance(raw, dict) else {})
        lines.append("| " + " | ".join(_vm_field_value(v, c) for c in cols) + " |")
    lines.append("")
    lines.append(f"**Toplam:** {len(vms)} VM")
    if as_of:
        lines.append(f"as_of: `{as_of}`")
    if {"disk_gb", "disk_count", "disk_breakdown"} & set(cols):
        lines.append(
            "_Not: Adet/boyut vCenter provisioned disk envanteridir (guest `df` değil)._"
        )
    return "\n".join(lines)


def _format_vm_child_table(
    vms: Sequence[Dict[str, Any]],
    scope: Any,
    *,
    as_of: Optional[str] = None,
    filter_note: Optional[str] = None,
) -> str:
    """Alt-varlık granülerliği: satır = disk (VM değil).

    "web01'in disklerini ve bulundukları datastore'ları göster" sorusunun
    doğru şekli budur; VM başına tek satırda datastore gösterilirse diskleri
    farklı datastore'lara yayılmış VM'lerde cevap eksik kalır.
    """
    from app.services.entity_projection import VM_CHILD_COLLECTIONS

    spec = VM_CHILD_COLLECTIONS.get(scope.child or "", {})
    row_key = spec.get("row_key") or scope.child or "disks"
    labels: Dict[str, str] = dict(spec.get("labels") or {})
    numeric = set(spec.get("numeric") or ())
    child_cols = [c for c in (scope.child_fields or spec.get("base_fields") or ()) if c in labels]
    if not child_cols:
        child_cols = list(spec.get("base_fields") or ("label",))

    parent_col_needed = len([v for v in vms if isinstance(v, dict)]) != 1
    header_cells = (["VM Adı"] if parent_col_needed else []) + [labels.get(c, c) for c in child_cols]
    sep_cells = (["---"] if parent_col_needed else []) + [
        "---:" if c in numeric else "---" for c in child_cols
    ]

    lines = ["## VM Disk Kırılımı (kaynak: db_list_vms)", ""]
    if filter_note:
        lines += [f"_Filtre: {filter_note}_", ""]
    lines += ["| " + " | ".join(header_cells) + " |", "|" + "|".join(sep_cells) + "|"]

    rows = 0
    missing_child = 0
    for raw in vms:
        if not isinstance(raw, dict):
            continue
        items = raw.get(row_key)
        if not isinstance(items, list) or not items:
            missing_child += 1
            continue
        for item in items:
            if not isinstance(item, dict):
                continue
            cells = [str(raw.get("name") or "—")] if parent_col_needed else []
            for col in child_cols:
                val = item.get(col)
                if col == "thin" and isinstance(val, bool):
                    cells.append("thin" if val else "thick")
                elif val is None or val == "":
                    cells.append("DB null (sync gerekir)" if col == "datastore" else "—")
                else:
                    cells.append(str(val))
            lines.append("| " + " | ".join(cells) + " |")
            rows += 1

    lines.append("")
    lines.append(f"**Toplam:** {rows} disk / {len([v for v in vms if isinstance(v, dict)])} VM")
    if missing_child:
        lines.append(
            f"_{missing_child} VM için disk kırılımı DB'de boş — hypervisor envanter sync gerekir._"
        )
    if as_of:
        lines.append(f"as_of: `{as_of}`")
    lines.append(
        "_Not: Kapasite vCenter provisioned disk envanteridir (guest `df` değil); "
        "datastore her diskin VMDK backing bilgisinden okunur._"
    )
    return "\n".join(lines)


def format_vm_disk_table(vms: Sequence[Dict[str, Any]], *, as_of: Optional[str] = None) -> str:
    """Tool satırlarından deterministik VM disk tablosu."""
    lines = [
        "## VM Disk Envanteri (kaynak: db_list_vms)",
        "",
        "| VM Adı | IP | Disk Adedi | Toplam (GB) | Diskler (label: GB) |",
        "|---|---|---:|---:|---|",
    ]
    filled = 0
    empty = 0
    for raw in vms:
        v = enrich_vm_row(raw if isinstance(raw, dict) else {})
        name = v.get("name") or "—"
        ip = v.get("ip") or "—"
        dgb = v.get("disk_gb")
        dcnt = v.get("disk_count")
        disks = v.get("disks") if isinstance(v.get("disks"), list) else []
        if dcnt is None and disks:
            dcnt = len(disks)
        if dgb is None and not disks:
            empty += 1
            parts = "DB null"
            dcnt_s = "—"
            dgb_s = "—"
        else:
            filled += 1
            dcnt_s = str(dcnt if dcnt is not None else (len(disks) if disks else "—"))
            dgb_s = str(dgb if dgb is not None else "—")
            if disks:
                parts = "; ".join(
                    f"{(d.get('label') or 'disk')}: {d.get('capacity_gb', '?')}"
                    for d in disks
                    if isinstance(d, dict)
                ) or "—"
            else:
                parts = "—"
        lines.append(f"| {name} | {ip} | {dcnt_s} | {dgb_s} | {parts} |")

    lines.extend([
        "",
        f"**Özet:** {len(vms)} VM — disk_gb dolu: {filled}, DB null: {empty}.",
    ])
    if as_of:
        lines.append(f"as_of: `{as_of}`")
    lines.append(
        "_Not: Adet/boyut vCenter provisioned disk envanteridir (guest `df` değil)._"
    )
    return "\n".join(lines)


def format_datastore_table(rows: Sequence[Dict[str, Any]], *, as_of: Optional[str] = None) -> str:
    lines = [
        "## Datastore Envanteri (kaynak: db_list_datastores)",
        "",
        "| Datastore | Kapasite (GB) | Boş (GB) | Kullanım % | vCenter |",
        "|---|---:|---:|---:|---|",
    ]
    for r in rows:
        if not isinstance(r, dict):
            continue
        lines.append(
            f"| {r.get('name') or '—'} | {r.get('capacity_gb', '—')} | "
            f"{r.get('free_gb', '—')} | {r.get('usage_pct', '—')} | {r.get('hypervisor') or '—'} |"
        )
    if as_of:
        lines.extend(["", f"as_of: `{as_of}`"])
    return "\n".join(lines)


# ESXi tablosu kolon sırası + başlıkları. (alan, başlık, sağa_yasla)
_ESX_COLUMNS: Tuple[Tuple[str, str, bool], ...] = (
    ("name", "Host", False),
    ("ip", "IP", False),
    ("version", "Version", False),
    ("cluster", "Cluster", False),
    ("cpu_pct", "CPU %", True),
    ("mem_pct", "Mem %", True),
    ("ds_pct", "Disk %", True),
    ("vms_running", "VM (açık)", True),
    ("vms_total", "VM (toplam)", True),
    ("cpu_cores", "Core", True),
    ("vendor", "Üretici", False),
    ("model", "Model", False),
    ("overall_status", "Donanım", False),
    ("sensor_bad_count", "Sorunlu sensör", True),
    ("bad_sensors", "Sensör detayı", False),
    ("config_issues", "Yapılandırma uyarısı", False),
    ("connection_state", "Durum", False),
    ("maintenance", "Bakım", False),
    ("hypervisor", "vCenter", False),
)


def _cell(value: Any) -> str:
    """Tablo hücresi — liste/dict alanları da okunur biçime indirger."""
    if value is None or value == "":
        return "—"
    if isinstance(value, bool):
        return "evet" if value else "hayır"
    if isinstance(value, (list, tuple)):
        parts = [_cell(v) for v in value if v not in (None, "")]
        if not parts:
            return "—"
        text = ", ".join(parts[:3])
        return text + (f" (+{len(parts) - 3})" if len(parts) > 3 else "")
    if isinstance(value, dict):
        label = value.get("name") or value.get("title") or value.get("label")
        return str(label) if label else ", ".join(f"{k}={v}" for k, v in list(value.items())[:3])
    return str(value)


def format_esx_host_table(rows: Sequence[Dict[str, Any]], *, as_of: Optional[str] = None) -> str:
    """Kolonlar satırlardaki GERÇEK alanlardan türetilir.

    Sabit kolon listesi iki yönde de hatalıydı: model donanım sağlığı alanları
    istediğinde onlar tabloda hiç görünmüyor, istemediğinde ise "CPU % —"
    gibi boş sütunlar kalıyordu.
    """
    data = [r for r in rows if isinstance(r, dict)]
    present = [
        (key, title, right)
        for key, title, right in _ESX_COLUMNS
        if any(r.get(key) not in (None, "", [], {}) for r in data)
    ]
    if not present:
        present = [("name", "Host", False)]

    header = "| " + " | ".join(t for _, t, _ in present) + " |"
    sep = "|" + "|".join("---:" if right else "---" for _, _, right in present) + "|"
    lines = ["## ESXi Host Envanteri (kaynak: db_list_esx_hosts)", "", header, sep]
    for r in data:
        lines.append("| " + " | ".join(_cell(r.get(k)) for k, _, _ in present) + " |")
    if as_of:
        lines.extend(["", f"as_of: `{as_of}`"])
    return "\n".join(lines)


def format_vm_list_table(vms: Sequence[Dict[str, Any]], *, as_of: Optional[str] = None) -> str:
    lines = [
        "## VM Listesi (kaynak: db_list_vms)",
        "",
        "| VM Adı | IP | Power | ESXi host | Disk (GB) | vCPU | RAM (MB) |",
        "|---|---|---|---|---:|---:|---:|",
    ]
    for v in vms:
        if not isinstance(v, dict):
            continue
        lines.append(
            f"| {v.get('name') or '—'} | {v.get('ip') or '—'} | {v.get('power_state') or '—'} | "
            f"{v.get('host') or v.get('esxi_host') or '—'} | {v.get('disk_gb', '—')} | "
            f"{v.get('vcpu', '—')} | {v.get('memory_mb', '—')} |"
        )
    lines.extend(["", f"**Toplam:** {len(vms)} VM"])
    if as_of:
        lines.append(f"as_of: `{as_of}`")
    return "\n".join(lines)


def materialize_from_tool_results(
    kind: str,
    tool_results: Sequence[Dict[str, Any]],
    *,
    filters: Optional[Dict[str, str]] = None,
    fields: Optional[List[str]] = None,
    directive: Optional["OutputDirective"] = None,
    scope: Optional["object"] = None,
) -> Optional[str]:
    """Prefetch/tool sonuçlarından deterministik cevap. Yoksa None.

    filters: extract_entity_filters() çıktısı (datastore/vm_name/host_name/cluster) —
        DB seviyesi filtre uygulanmış olsa da burada SAVUNMACI 2. kontrol yapılır.
    fields: detect_requested_vm_fields() çıktısı — VM kind'ları için hangi
        kolonların render edileceğini belirler. None ise geriye dönük uyumlu
        eski sabit şablonlar (format_vm_disk_table/format_vm_list_table) kullanılır.
    directive: kullanıcının /table, /json, /brief komutu (chat_output_directives).
        JSON/BRIEF ise LLM'siz bu katmanda DOĞRUDAN o formatta üretilir — deterministik
        tablo LLM'e gitmeden döndüğü için (early_stop) komut burada uygulanmazsa hiç
        uygulanmaz.
    """
    from app.services.chat_output_directives import (
        OutputDirective,
        render_rows_as_brief,
        render_rows_as_json,
    )

    sc = _as_scope(filters, scope)
    filters = dict(sc.filters)
    by_name: Dict[str, Any] = {}
    for tr in tool_results:
        if not isinstance(tr, dict):
            continue
        name = tr.get("tool") or tr.get("name")
        payload = tr.get("result")
        if name and payload is not None:
            by_name[str(name)] = payload

    if kind in (KIND_VM_DISK, KIND_VM_LIST):
        payload = by_name.get("db_list_vms")
        if not isinstance(payload, dict) or not payload.get("ok"):
            return None
        vms = payload.get("vms") or []
        if not isinstance(vms, list):
            return None
        vms = [v for v in vms if _row_matches_filters(v, filters, entity_type="vm", scope=sc)]
        as_of = payload.get("as_of")

        if directive == OutputDirective.JSON:
            return render_rows_as_json(vms, meta={
                "kaynak": "db_list_vms", "as_of": as_of, "filtre": _filter_note(scope=sc),
            })
        if directive == OutputDirective.BRIEF:
            extra = None
            if vms and any(v.get("disk_gb") is not None for v in vms if isinstance(v, dict)):
                total_gb = sum((v.get("disk_gb") or 0) for v in vms if isinstance(v, dict))
                extra = f"Toplam disk: {total_gb} GB."
            subject = "VM listesi" + (f" ({_filter_note(scope=sc)})" if filters else "")
            return render_rows_as_brief(vms, subject=subject, extra=extra)

        if fields is None and not sc.is_child():
            # Geriye dönük uyumluluk: fields hesaplanmadıysa eski sabit şablon.
            if kind == KIND_VM_DISK:
                return format_vm_disk_table(vms, as_of=as_of)
            return format_vm_list_table(vms, as_of=as_of)
        return format_vm_table(
            vms,
            fields or ["name"],
            as_of=as_of,
            filter_note=_filter_note(scope=sc),
            scope=sc,
        )

    if kind == KIND_DATASTORE:
        payload = by_name.get("db_list_datastores")
        if not isinstance(payload, dict) or not payload.get("ok"):
            return None
        rows = payload.get("datastores") or payload.get("items") or []
        if not isinstance(rows, list):
            return None
        rows = [
            r for r in rows
            if _row_matches_filters(r, filters, entity_type="datastore", scope=sc)
        ]
        if directive == OutputDirective.JSON:
            return render_rows_as_json(rows, meta={"kaynak": "db_list_datastores", "as_of": payload.get("as_of")})
        if directive == OutputDirective.BRIEF:
            return render_rows_as_brief(rows, subject="Datastore listesi")
        return format_datastore_table(rows, as_of=payload.get("as_of"))

    if kind == KIND_ESX_HOST:
        payload = by_name.get("db_list_esx_hosts")
        if not isinstance(payload, dict) or not payload.get("ok"):
            return None
        rows = payload.get("hosts") or payload.get("items") or []
        if not isinstance(rows, list):
            return None
        rows = [
            r for r in rows
            if _row_matches_filters(r, filters, entity_type="host", scope=sc)
        ]
        if directive == OutputDirective.JSON:
            return render_rows_as_json(rows, meta={"kaynak": "db_list_esx_hosts", "as_of": payload.get("as_of")})
        if directive == OutputDirective.BRIEF:
            return render_rows_as_brief(rows, subject="ESXi host listesi")
        return format_esx_host_table(rows, as_of=payload.get("as_of"))

    return None


def infer_kind_from_tool_call(tool_name: str, tool_args: Optional[Dict[str, Any]] = None) -> Optional[str]:
    """DECOUPLE: regex niyet tespiti (detect_virt_inventory_kind) başarısız olsa
    bile, LLM'in KENDİ kararıyla çağırdığı tool'dan envanter sınıfını geriye
    türetir.

    Neden gerekli: Türkçe ifade çeşitliliği pratikte sonsuzdur (bkz.
    detect_virt_inventory_kind yorumları) — kelime listesi her zaman bir
    ifadeyi kaçırabilir. Ama model kendi tool-calling mekanizmasıyla zaten
    doğru db_* aracını çağırmış olabilir (ör. "... host üzerindeki VM'leri
    ... sorgula" gibi regex'in tanımadığı ama modelin doğru anladığı bir
    ifade). Bu durumda deterministik render'ı yalnızca regex'e bağlı tutmak,
    zaten elde edilmiş doğru sonucu ham/devasa context'e boğar. Bu fonksiyon
    ikinci bir güvenlik ağı sağlar: render kararı artık YA regex YA DA
    gerçekleşmiş tool çağrısına dayanabilir.
    """
    args = tool_args or {}
    if tool_name == "db_list_vms":
        fields = args.get("fields") or []
        if args.get("include_disks") or "disks" in fields or "disk_gb" in fields:
            return KIND_VM_DISK
        return KIND_VM_LIST
    if tool_name == "db_list_datastores":
        return KIND_DATASTORE
    if tool_name == "db_list_esx_hosts":
        return KIND_ESX_HOST
    return None


def prefetch_spec(
    kind: str,
    *,
    filters: Optional[Dict[str, str]] = None,
    fields: Optional[List[str]] = None,
    scope: Optional["object"] = None,
) -> Optional[Tuple[str, Dict[str, Any]]]:
    """(tool_name, args) — loop başında zorunlu çekim.

    filters: extract_entity_filters() çıktısı — kullanıcı belirli bir
        datastore/VM/host/cluster adı verdiyse tool çağrısına GERÇEK filtre
        olarak eklenir (kapsam daraltma — "bilgi kirliliği" önlemi, GENEL
        kural: herhangi bir varlık tipi/senaryo için aynı şekilde çalışır).
    fields: detect_requested_vm_fields() çıktısı — yalnız gerçekten istenen
        kolonlar tool'dan çekilir. None ise (çağıran taraf hesaplamadıysa)
        geriye dönük uyumluluk için eski tam alan seti istenir.
    """
    from app.services.virt_scope import tool_args as scope_tool_args

    sc = _as_scope(filters, scope)
    filters = dict(sc.filters)
    if kind in (KIND_VM_DISK, KIND_VM_LIST):
        display_fields = list(fields) if fields else [
            "name", "ip", "power_state", "host", "cluster", "datastore",
            "hypervisor", "vcpu", "memory_mb", "disk_gb", "disk_count", "disk_breakdown",
        ]
        tool_fields = {"name"}
        for f in display_fields:
            tool_fields.add("disks" if f == "disk_breakdown" else f)
        # Savunmacı filtreleme için, kolon olarak gösterilmese bile filtre
        # boyutlarını tool'dan çek (materialize_from_tool_results 2. kontrolü yapabilsin).
        for dim, key in (("datastore", "datastore"), ("host_name", "host"), ("cluster", "cluster")):
            if filters.get(dim):
                tool_fields.add(key)
        # Alt-varlık granülerliği disk kayıtlarını ZORUNLU kılar (satır = disk).
        if sc.is_child():
            tool_fields.add(sc.child or "disks")
        args: Dict[str, Any] = {
            "limit": 500,
            "include_disks": "disks" in tool_fields,
            "fields": sorted(tool_fields),
        }
        args.update(scope_tool_args("vm", sc))
        return ("db_list_vms", args)
    if kind == KIND_DATASTORE:
        args = {"limit": 200}
        args.update(scope_tool_args("datastore", sc))
        return ("db_list_datastores", args)
    if kind == KIND_ESX_HOST:
        args = {
            "fields": [
                "name", "ip", "version", "cpu_pct", "mem_pct",
                "connection_state", "hypervisor",
            ],
        }
        args.update(scope_tool_args("host", sc))
        return ("db_list_esx_hosts", args)
    return None


def parse_tool_payloads_from_text(tool_text: str) -> List[Dict[str, Any]]:
    """Eski final.tool_text'ten kurtarma (JSON blokları)."""
    out: List[Dict[str, Any]] = []
    if not tool_text:
        return out
    # [label]\n{json} kalıbı
    parts = re.split(r"\n(?=\[)", tool_text)
    for part in parts:
        part = part.strip()
        if not part.startswith("["):
            continue
        nl = part.find("\n")
        if nl < 0:
            continue
        body = part[nl + 1 :].strip()
        if not body.startswith("{"):
            continue
        try:
            payload = json.loads(body)
        except Exception:
            continue
        label = part[1:part.find("]")].strip().lower()
        tool = None
        if "db_list_vms" in label or "vm listesi" in label:
            tool = "db_list_vms"
        elif "datastore" in label:
            tool = "db_list_datastores"
        elif "esxi" in label or "esx" in label:
            tool = "db_list_esx_hosts"
        if tool:
            out.append({"tool": tool, "result": payload})
    return out
