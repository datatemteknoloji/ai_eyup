"""Kapsam (scope) sözleşmesi — virt cevap yollarının TEK kapsam kaynağı.

Değişmez kural: **cevabın evreni = kullanıcının adlandırdığı kapsam.**

Önceki durum (regresyon): `extract_entity_filters` beş ayrı yerden bağımsız
çağrılıyordu (hypervisor_intelligence._apply_entity_scope, QA handler'ları,
unified_tool_chat prefetch/render) ve her çağıran sonucun yalnız kendi işine
yarayan parçasını uyguluyordu. Ortada kapsamı temsil eden tek bir nesne
olmadığı için varsayılan davranış "her şeyi bas", kapsam ise istisnaydı —
tek bir VM sorulduğunda bile TÜM datastore tablosu prompt'a giriyordu.

Bu modül üç kavramı birbirinden ayırır ve hepsini tek nesnede taşır:

  * KAPSAM (scope)       : hangi satırlar  → `Scope.filters`
  * ALAN (field)         : hangi kolonlar  → çağıran katman (projeksiyon)
  * GRANÜLERLİK          : satır neyi temsil ediyor (varlık mı alt-varlık mı)
                           → `Scope.granularity` / `Scope.child`

Kapsam boyutları elle yazılmış `if` blokları yerine `SCOPE_DIMENSIONS` kayıt
defterinden okunur; yeni bir boyut eklendiğinde satır filtresi, tool argüman
eşlemesi ve sabit-kolon daraltma kendiliğinden kapsar (datastore'a özel
değildir — herhangi bir isimlendirilmiş varlık için aynı çalışır).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

# ── Boyut kayıt defteri ──────────────────────────────────────────────────────
# boyut → { varlık_tipi: satırda o boyutu taşıyan anahtarlar }
# Bir varlık tipi listede yoksa, o tip bu boyutu İFADE EDEMEZ demektir
# (bkz. unsupported_dimensions → bölüm tamamen düşer, filtresiz basılmaz).
SCOPE_DIMENSIONS: Dict[str, Dict[str, Sequence[str]]] = {
    "vm_name": {
        "vm": ("name", "vm_name"),
    },
    "host_name": {
        "vm": ("host", "esxi_host", "host_name"),
        "host": ("name", "host", "host_name"),
        "cross": ("host",),
    },
    "cluster": {
        "vm": ("cluster", "cluster_name"),
        "host": ("cluster", "cluster_name"),
        "cluster": ("name",),
    },
    "datastore": {
        "vm": ("datastore",),
        "datastore": ("name",),
        "cross": ("datastore",),
    },
}

# Bir boyut, satırın ALT KOLEKSİYONUNDA da bulunabilir: bir VM'in diskleri
# farklı datastore'lara yayılmışsa VM seviyesindeki tek `datastore` değeri
# eksik/yanıltıcıdır — disk kayıtlarına da bakılır.
CHILD_SCOPE_KEYS: Dict[str, Dict[str, Tuple[str, str]]] = {
    "vm": {"datastore": ("disks", "datastore")},
}

# boyut → tool argüman adı (varlık tipine göre)
SCOPE_TOOL_ARGS: Dict[str, Dict[str, str]] = {
    "vm": {
        "vm_name": "name_filter",
        "host_name": "host_name",
        "cluster": "cluster",
        "datastore": "datastore",
    },
    "datastore": {"datastore": "name_filter"},
    "host": {"host_name": "name_filter"},
}

# Not satırındaki gösterim sırası ve etiketleri (geriye dönük uyumlu).
_NOTE_ORDER: Tuple[Tuple[str, str], ...] = (
    ("datastore", "datastore"),
    ("vm_name", "vm"),
    ("host_name", "host"),
    ("cluster", "cluster"),
)

# "sadece bu VM" gibi AÇIK kapsam kilidi. Uzun varyant kısa olandan önce
# gelmeli ("yalnızca" | "yalnız").
_LOCK_RE = re.compile(
    r"(?<![a-z0-9])(sadece|yalnızca|yalnizca|yalnız|yalniz|sırf|sirf|bir tek|only|just)(?![a-z0-9])",
    re.I,
)


@dataclass
class Scope:
    """Bir istek boyunca taşınan kapsam. Bir kez çözülür, her yerde kullanılır."""

    filters: Dict[str, str] = field(default_factory=dict)
    #: "sadece/yalnızca" gibi açık kilit — kapsam dışı TOPLU bölüm hiç basılmaz
    locked: bool = False
    #: "entity" → satır = varlık, "child" → satır = alt-varlık (ör. disk)
    granularity: str = "entity"
    #: granularity == "child" ise alt koleksiyon adı (ör. "disks")
    child: Optional[str] = None
    #: alt-varlık satırında gösterilecek alanlar
    child_fields: List[str] = field(default_factory=list)

    @property
    def dimensions(self) -> List[str]:
        return [k for k, v in self.filters.items() if v]

    def is_empty(self) -> bool:
        return not self.dimensions

    def value(self, dimension: str) -> Optional[str]:
        return self.filters.get(dimension) or None

    def note(self) -> Optional[str]:
        return scope_note(self)

    def is_child(self) -> bool:
        return self.granularity == "child" and bool(self.child)


def scope_note(scope: Optional[Scope]) -> Optional[str]:
    """`datastore=X, vm=Y` biçiminde okunabilir kapsam notu."""
    if scope is None or scope.is_empty():
        return None
    parts = [f"{label}={scope.filters[dim]}" for dim, label in _NOTE_ORDER if scope.filters.get(dim)]
    # Kayıt defterine sonradan eklenen boyutlar da nota girsin.
    known = {dim for dim, _ in _NOTE_ORDER}
    parts += [f"{dim}={v}" for dim, v in scope.filters.items() if dim not in known and v]
    return ", ".join(parts) or None


def detect_granularity(message: str) -> Tuple[str, Optional[str], List[str]]:
    """Sorunun satır granülerliğini şema kayıt defterinden çıkarır.

    "web01'in diskleri hangi datastore'da" → satır = DİSK (child), çünkü
    datastore disk başına değişebilir ve VM seviyesinde tek değerle
    gösterilemez. "web01'in disk boyutu" → satır = VM (entity).
    """
    m = (message or "").lower()
    if not m.strip():
        return "entity", None, []
    try:
        from app.services.entity_projection import VM_CHILD_COLLECTIONS
    except Exception:
        return "entity", None, []

    for child_name, spec in VM_CHILD_COLLECTIONS.items():
        if not any(k in m for k in spec.get("keywords", ())):
            continue
        aliases: Dict[str, Sequence[str]] = spec.get("fields", {})
        requested = [f for f, al in aliases.items() if any(a in m for a in al)]
        pivots = [f for f in spec.get("pivot_fields", ()) if f in requested]
        if not pivots:
            continue
        cols = [f for f in spec.get("base_fields", ()) if f in aliases]
        cols += [p for p in pivots if p not in cols]
        return "child", child_name, cols
    return "entity", None, []


def resolve_scope(
    db: Any,
    message: str,
    *,
    filters: Optional[Dict[str, str]] = None,
) -> Scope:
    """Kapsamı BİR KEZ çözer. `filters` verilirse yeniden DB'ye gidilmez."""
    if filters is None:
        try:
            from app.services.virt_entity_resolver import extract_entity_filters

            filters = extract_entity_filters(db, message or "") or {}
        except Exception:
            filters = {}
    clean = {k: v for k, v in (filters or {}).items() if v}
    locked = bool(clean) and bool(_LOCK_RE.search(message or ""))
    granularity, child, child_fields = detect_granularity(message or "")
    return Scope(
        filters=clean,
        locked=locked,
        granularity=granularity,
        child=child,
        child_fields=child_fields,
    )


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


def _row_has(row: Dict[str, Any], keys: Sequence[str], needle: str) -> bool:
    n = needle.strip().lower()
    for key in keys:
        if key in row and n in _norm(row.get(key)):
            return True
    return False


def _child_has(row: Dict[str, Any], collection: str, field_name: str, needle: str) -> bool:
    items = row.get(collection)
    if not isinstance(items, list):
        return False
    n = needle.strip().lower()
    return any(
        isinstance(item, dict) and n in _norm(item.get(field_name))
        for item in items
    )


def row_in_scope(entity_type: str, row: Any, scope: Optional[Scope]) -> bool:
    """Jenerik satır filtresi — dört sabit `if` yerine kayıt defterinden.

    Savunmacı 2. kontroldür: DB/tool seviyesindeki filtre bir sebeple
    uygulanmamışsa bile kapsam dışı satır render EDİLMEZ.

    Satırın o boyutu hiç taşımadığı durumda (ör. datastore satırında
    `vm_name`) satır elenmez — o kararı bölüm seviyesi verir
    (`unsupported_dimensions`), aksi hâlde tüm tablo boşalırdı.
    """
    if not isinstance(row, dict) or scope is None or scope.is_empty():
        return True
    for dim in scope.dimensions:
        needle = scope.filters[dim]
        keys = SCOPE_DIMENSIONS.get(dim, {}).get(entity_type)
        child = CHILD_SCOPE_KEYS.get(entity_type, {}).get(dim)
        if not keys and not child:
            continue
        if keys and _row_has(row, keys, needle):
            continue
        if child and _child_has(row, child[0], child[1], needle):
            continue
        return False
    return True


def filter_rows(entity_type: str, rows: Sequence[Any], scope: Optional[Scope]) -> List[Any]:
    return [r for r in rows if row_in_scope(entity_type, r, scope)]


def unsupported_dimensions(entity_type: str, scope: Optional[Scope]) -> List[str]:
    """Bu varlık tipinin İFADE EDEMEDİĞİ aktif kapsam boyutları.

    Boş değilse çağıran bölüm, filtresiz veri basmak yerine tamamen
    düşmelidir (deny-by-default) — kapsam sızıntısının kapandığı yer burasıdır.
    """
    if scope is None or scope.is_empty():
        return []
    out = []
    for dim in scope.dimensions:
        if SCOPE_DIMENSIONS.get(dim, {}).get(entity_type):
            continue
        if CHILD_SCOPE_KEYS.get(entity_type, {}).get(dim):
            continue
        out.append(dim)
    return out


def section_allowed(entity_type: str, scope: Optional[Scope]) -> bool:
    """Bölüm bu kapsamla basılabilir mi? (kilitli kapsamda daha katı)"""
    if scope is None or scope.is_empty():
        return True
    return not unsupported_dimensions(entity_type, scope)


def tool_args(entity_type: str, scope: Optional[Scope]) -> Dict[str, str]:
    """Kapsamı tool çağrısı argümanlarına çevirir (elle `if` zinciri yerine)."""
    if scope is None or scope.is_empty():
        return {}
    mapping = SCOPE_TOOL_ARGS.get(entity_type, {})
    return {arg: scope.filters[dim] for dim, arg in mapping.items() if scope.filters.get(dim)}


def scope_row_keys(entity_type: str, dimension: str) -> Sequence[str]:
    return SCOPE_DIMENSIONS.get(dimension, {}).get(entity_type, ())


def collapse_constant_columns(
    entity_type: str,
    rows: Sequence[Dict[str, Any]],
    columns: Sequence[str],
    scope: Optional[Scope],
) -> List[str]:
    """Kapsam boyutu olan VE tüm satırlarda tek değere düşen kolonu gizler.

    "Bilgi kirliliği" önlemi burada VERİYE göre verilir, kelimeye göre değil:
    `NVME_DS'de hangi VM'ler var` sorusunda Datastore kolonu 40 satır boyunca
    aynı değeri tekrarlayacağı için gizlenir (değer zaten filtre notunda), ama
    `VM'ler hangi datastore'da` veya `web01'in diskleri hangi datastore'da`
    sorularında kolon KORUNUR. Eski davranış "datastore kelimesi kolon listesine
    hiç girmez" şeklinde koşulsuz bir yasaktı ve bu ikinci grubu da kesiyordu.
    """
    cols = list(columns)
    if scope is None or scope.is_empty() or not rows:
        return cols
    data = [r for r in rows if isinstance(r, dict)]
    if not data:
        return cols
    for dim in scope.dimensions:
        keys = SCOPE_DIMENSIONS.get(dim, {}).get(entity_type) or ()
        for key in keys:
            if key not in cols:
                continue
            values = {_norm(r.get(key)) for r in data}
            if len(values) == 1 and _norm(scope.filters[dim]) in values:
                cols.remove(key)
    return cols


def system_addendum(scope: Optional[Scope]) -> str:
    """Modele giden kapsam talimatı.

    Prompt talimatı tek başına yeterli DEĞİLDİR (bağlamda kapsam dışı veri
    fiziksel olarak duruyorsa model onu kullanır) — asıl zorlama veriyi
    bağlama hiç koymamaktır. Bu metin ikinci savunma katmanıdır.
    """
    if scope is None or scope.is_empty():
        return ""
    lines = [
        "",
        "",
        "KAPSAM SÖZLEŞMESİ (zorunlu):",
        f"- Soru şu kapsama işaret ediyor: {scope_note(scope)}.",
        "- Cevabı YALNIZ bu kapsamdaki satırlardan kur; kapsam dışı varlık listeleme.",
    ]
    if scope.locked:
        lines.append(
            "- Kullanıcı kapsamı AÇIKÇA sınırladı ('sadece/yalnızca'): kapsam dışı "
            "özet, toplam veya karşılaştırma tablosu EKLEME."
        )
    if scope.is_child():
        lines.append(
            "- Satır granülerliği ALT VARLIK: her disk için ayrı satır ver "
            "(etiket, kapasite, datastore) — VM başına tek satırda birleştirme."
        )
    return "\n".join(lines) + "\n"


def child_datastore_names(vms: Sequence[Dict[str, Any]]) -> Set[str]:
    """Kapsanan VM'lerin FİİLEN kullandığı datastore adları.

    Tek VM sorulduğunda datastore bölümünün tüm ortam yerine yalnız bu
    kümeye daraltılması için kullanılır (bkz. build_context Bölüm 4).
    """
    out: Set[str] = set()
    for vm in vms or []:
        if not isinstance(vm, dict):
            continue
        primary = (vm.get("datastore") or "").strip()
        if primary:
            out.add(primary)
        disks = vm.get("disks")
        if isinstance(disks, list):
            for d in disks:
                if isinstance(d, dict):
                    name = (d.get("datastore") or "").strip()
                    if name:
                        out.add(name)
    return out


# ── Çoklu vCenter kimliği ────────────────────────────────────────────────────
# Aynı ad iki vCenter'da ayrı nesnedir. Grafik/seçici ref'i: hv:{id}:{ad}

_REF_RE = re.compile(r"^hv:(\d+):(.*)$", re.DOTALL)


def encode_ref(hypervisor_id: Optional[int], name: str) -> str:
    name = (name or "").strip()
    if hypervisor_id is None or not name:
        return name
    return f"hv:{int(hypervisor_id)}:{name}"


def parse_ref(token: str) -> Tuple[Optional[int], str]:
    raw = (token or "").strip()
    m = _REF_RE.match(raw)
    if m and m.group(2):
        return int(m.group(1)), m.group(2)
    return None, raw


def owned_by_other_vcenter(existing_hv_id: Optional[int], this_hv_id: int) -> bool:
    return existing_hv_id is not None and int(existing_hv_id) != int(this_hv_id)


def disambiguate(
    name: str,
    hypervisor_id: Optional[int],
    name_counts: Dict[str, int],
    hv_names: Dict[int, str],
) -> str:
    """Aynı ad birden fazla vCenter'da varsa etikete vCenter adını ekle."""
    if name_counts.get(name, 0) <= 1:
        return name
    label = hv_names.get(int(hypervisor_id)) if hypervisor_id is not None else None
    return f"{name} ({label or f'vCenter {hypervisor_id}'})"


def count_names(pairs: Iterable[Tuple[Optional[int], str]]) -> Dict[str, int]:
    seen = set()
    counts: Dict[str, int] = {}
    for hv_id, name in pairs:
        if not name:
            continue
        key = (hv_id, name)
        if key in seen:
            continue
        seen.add(key)
        counts[name] = counts.get(name, 0) + 1
    return counts


def sql_pair_filter(
    pairs: Sequence[Tuple[int, str]], *, hv_col: str, name_col: str,
) -> Tuple[str, Dict[str, object]]:
    """(hypervisor_id, name) OR zinciri. Boşsa 'FALSE'."""
    if not pairs:
        return "FALSE", {}
    parts = []
    params: Dict[str, object] = {}
    for i, (hv_id, name) in enumerate(pairs):
        parts.append(f"({hv_col} = :hv{i} AND {name_col} = :nm{i})")
        params[f"hv{i}"] = int(hv_id)
        params[f"nm{i}"] = name
    return "(" + " OR ".join(parts) + ")", params
