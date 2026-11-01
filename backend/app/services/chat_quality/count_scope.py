"""Sayım kuralları için kapsam çözümü (Adım 5b) — SAF fonksiyonlar (DB yok; katalog verilir).

Mesajdaki kapsam sözcüklerini (hypervisor adı, OpenShift cluster adı, sanallaştırma cluster adı, tür
sözcüğü: vcenter/vmware/esxi · kvm/olvm/ovirt · openshift/ocp/kubevirt) katalogla eşleştirir.

Öncelik: TAM AD > sanallaştırma cluster adı > TÜR SÖZCÜĞÜ > ÖNEK. Tam ad bulunduysa tür sözcükleri yok
sayılır ("office vCenter'da" → `office`). Kapsam bulunamazsa `kind="all"` (toplam + kırılım).

Tüketilen token'lar (`Scope.consumed`) çağırana döner; çağıran kalan tanınmayan token'ı
"bilinmeyen kapsam sözcüğü" sayıp kuralı devre dışı bırakır (sessiz yok sayma yok).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set, Tuple

from app.services.chat_quality.claims import fold

TYPE_WORDS: Dict[str, Tuple[str, ...]] = {
    "VMWARE": ("vcenter", "vmware", "esxi", "esx"),
    "KVM": ("kvm", "olvm", "ovirt"),
    "OPENSHIFT_VIRT": ("openshift", "ocp", "kubevirt"),
}
TYPE_LABEL = {"VMWARE": "VMware vCenter", "KVM": "KVM / OLVM", "OPENSHIFT_VIRT": "OpenShift Virtualization"}
_TYPE_BY_WORD = {w: t for t, ws in TYPE_WORDS.items() for w in ws}

_TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._\-]*")


@dataclass(frozen=True)
class HV:
    id: int
    name: str
    type: str


@dataclass
class ScopeCatalog:
    hypervisors: List[HV] = field(default_factory=list)
    ocp_clusters: List[Tuple[int, str]] = field(default_factory=list)
    # fold(cluster adı) -> (görünen ad, hypervisor id'leri)  (VM/host tablolarındaki vm_cluster / cluster_name)
    virt_clusters: Dict[str, Tuple[str, List[int]]] = field(default_factory=dict)
    ok: bool = True


@dataclass
class Scope:
    kind: str = "all"                         # all | name | cluster | type | prefix
    hv_ids: Optional[List[int]] = None        # None → kısıt yok
    ocp_ids: Optional[List[int]] = None
    cluster_names: Optional[List[str]] = None  # görünen vm_cluster adları
    matched: List[str] = field(default_factory=list)   # eşleşen görünen adlar / sözcükler
    consumed: Set[int] = field(default_factory=set)    # tüketilen token indeksleri
    types: Set[str] = field(default_factory=set)

    @property
    def is_all(self) -> bool:
        return self.kind == "all"


def tokenize(message_fold: str) -> List[Tuple[str, int, int]]:
    """(token, başlangıç, bitiş) — token sonundaki `.-_` atılır."""
    out: List[Tuple[str, int, int]] = []
    for m in _TOKEN_RE.finditer(message_fold):
        tok = m.group(0).rstrip(".-_")
        if tok:
            out.append((tok, m.start(), m.start() + len(tok)))
    return out


def _span_tokens(tokens: Sequence[Tuple[str, int, int]], a: int, b: int) -> Set[int]:
    return {i for i, (_, s, e) in enumerate(tokens) if s < b and e > a}


def _find_names(mfold: str, names: Sequence[Tuple[str, object]], used: List[Tuple[int, int]]) -> List[Tuple[object, int, int]]:
    """Tam ad eşleşmeleri (uzun ad önce; çakışan aralıklar tüketilir)."""
    hits: List[Tuple[object, int, int]] = []
    for nf, payload in sorted(names, key=lambda x: -len(x[0])):
        if len(nf) < 2:
            continue
        for m in re.finditer(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(nf), mfold):
            a, b = m.start(), m.end()
            if any(a < ub and b > ua for ua, ub in used):
                continue
            used.append((a, b))
            hits.append((payload, a, b))
    return hits


def _dedupe(seq: Sequence) -> List:
    out: List = []
    for x in seq:
        if x not in out:
            out.append(x)
    return out


def resolve_virt(message: str, cat: ScopeCatalog, *, neutral: Set[str] = frozenset()) -> Scope:
    """Sanallaştırma kapsamı (VM / host / datastore / cluster). `neutral`: önek eşleşmesinde atlanacak sözcükler."""
    mf = fold(message)
    toks = tokenize(mf)
    used: List[Tuple[int, int]] = []
    sc = Scope()

    # 1) tam ad
    hv_hits = _find_names(mf, [(fold(h.name), h) for h in cat.hypervisors], used)
    if hv_hits:
        sc.kind = "name"
        sc.hv_ids = _dedupe([h.id for h, _, _ in hv_hits])
        sc.matched = _dedupe([h.name for h, _, _ in hv_hits])
        for _, a, b in hv_hits:
            sc.consumed |= _span_tokens(toks, a, b)
        return sc

    # 2) sanallaştırma cluster adı (yalın sözcük riski: ad rakam/tire içermiyorsa 'cluster' sözcüğü şart)
    has_cluster_word = bool(re.search(r"(?<![a-z0-9])(cluster|kume)", mf))
    cl_names = [(k, (disp, ids)) for k, (disp, ids) in cat.virt_clusters.items()
                if re.search(r"[\d\-]", k) or has_cluster_word]
    cl_hits = _find_names(mf, cl_names, used)
    if cl_hits:
        sc.kind = "cluster"
        sc.cluster_names = _dedupe([p[0] for p, _, _ in cl_hits])
        ids: List[int] = []
        for p, _, _ in cl_hits:
            ids += p[1]
        sc.hv_ids = _dedupe(ids)
        sc.matched = list(sc.cluster_names)
        for _, a, b in cl_hits:
            sc.consumed |= _span_tokens(toks, a, b)
        return sc

    # 3) tür sözcüğü
    type_idx = [(i, _TYPE_BY_WORD[t]) for i, (t, _, _) in enumerate(toks) if t in _TYPE_BY_WORD]
    if type_idx:
        types = {t for _, t in type_idx}
        sc.kind = "type"
        sc.types = types
        sc.hv_ids = [h.id for h in cat.hypervisors if h.type in types]
        sc.matched = [TYPE_LABEL.get(t, t) for t in sorted(types)]
        sc.consumed = {i for i, _ in type_idx}
        return sc

    # 4) önek ("datatem", "zz-fake")
    pref: List[HV] = []
    consumed: Set[int] = set()
    for i, (t, _, _) in enumerate(toks):
        if t in neutral or len(t) < 4 or not re.search(r"[a-z]", t):
            continue
        if not (len(t) >= 5 or "-" in t):
            continue
        ms = [h for h in cat.hypervisors if fold(h.name).startswith(t)]
        if ms:
            pref += ms
            consumed.add(i)
    if pref:
        sc.kind = "prefix"
        sc.hv_ids = _dedupe([h.id for h in pref])
        sc.matched = _dedupe([h.name for h in pref])
        sc.consumed = consumed
    return sc


def resolve_ocp(message: str, cat: ScopeCatalog, *, neutral: Set[str] = frozenset()) -> Scope:
    """OpenShift kapsamı (node / proje / cluster). Tür sözcüğü (openshift/ocp/kubevirt) = tüm cluster'lar."""
    mf = fold(message)
    toks = tokenize(mf)
    used: List[Tuple[int, int]] = []
    sc = Scope()
    hits = _find_names(mf, [(fold(n), (cid, n)) for cid, n in cat.ocp_clusters], used)
    if hits:
        sc.kind = "name"
        sc.ocp_ids = _dedupe([p[0] for p, _, _ in hits])
        sc.matched = _dedupe([p[1] for p, _, _ in hits])
        for _, a, b in hits:
            sc.consumed |= _span_tokens(toks, a, b)
    # tür sözcüğü: yalnız tüketilir (kapsam daraltmaz)
    for i, (t, _, _) in enumerate(toks):
        if t in TYPE_WORDS["OPENSHIFT_VIRT"] and i not in sc.consumed:
            sc.consumed.add(i)
    if hits:
        return sc
    # önek ("zz-fake")
    pref: List[Tuple[int, str]] = []
    consumed: Set[int] = set()
    for i, (t, _, _) in enumerate(toks):
        if i in sc.consumed or t in neutral or len(t) < 4 or not re.search(r"[a-z]", t):
            continue
        if not (len(t) >= 5 or "-" in t):
            continue
        ms = [(cid, n) for cid, n in cat.ocp_clusters if fold(n).startswith(t)]
        if ms:
            pref += ms
            consumed.add(i)
    if pref:
        sc.kind = "prefix"
        sc.ocp_ids = _dedupe([c for c, _ in pref])
        sc.matched = _dedupe([n for _, n in pref])
        sc.consumed |= consumed
    return sc


def scope_label(sc: Scope, cat: ScopeCatalog, *, domain: str) -> str:
    """Cevapta yazılan kapsam etiketi."""
    if sc.is_all:
        if domain == "ocp":
            return f"tüm OpenShift cluster'ları ({len(cat.ocp_clusters)})"
        return f"tüm platformlar ({len(cat.hypervisors)} hypervisor)"
    if sc.kind == "type":
        return " + ".join(sc.matched) + " (tür: tüm kayıtlar)"
    if sc.kind == "prefix":
        return "ad önekiyle eşleşenler: " + ", ".join(sc.matched)
    return ", ".join(sc.matched)
