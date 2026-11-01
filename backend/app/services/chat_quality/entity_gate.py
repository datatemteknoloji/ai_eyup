"""Varlık çözümleyici kapısı (Adım 4): sıfır eşleşme → "bulunamadı"; çoklu eşleşme → sor.

Dört sohbet hattı `chat_chitchat_policy.canned_chitchat_answer` noktasından (eylem kapısından
SONRA) çağırır; LLM'e/araca HİÇ gitmeden şablon cevap döner. Muhafazakârdır: kapı yalnız net
iki durumda tetiklenir, belirsizlikte `None` (normal akış) döner.

A. Sıfır eşleşme: mesajda tip adı (VM, sunucu, host, cluster, namespace/proje, node, hypervisor,
   datastore, vCenter) ile sahiplik/yalın biçimde bağlı, KİMLİK BİÇİMLİ (rakam/tire/alt çizgi/nokta
   içeren) bir token envanterin HİÇBİR katalogunda yoksa → "bulunamadı" + benzer adlar (yalnız DB).
B. Çoklu eşleşme: mesajdaki ad `servers`'ta ≥2 kayıtla eşleşiyor ve mesaj platformu tek kayda
   daraltmıyorsa → kayıtlar tablosu + "Hangisini kastettiniz?" (yalnız sanallaştırma erişimi olana).

Saf çözümleme (`resolve`) katalogla çalışır → birim testte DB gerekmez. Katalog 60 sn önbellekli;
DB hatasında/eksik katalogda kapı kapalı (None).
"""
from __future__ import annotations

import difflib
import logging
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.services.chat_quality.claims import fold

logger = logging.getLogger(__name__)

KIND_NOT_FOUND = "not_found"
KIND_AMBIGUOUS = "ambiguous"

_MAX_ECHO = 80
_MIN_TOKEN_LEN = 4
_CATALOG_TTL_SEC = 60.0

# ── tip adları + izinli ekler (fold'lanmış) ──────────────────────────────────
_NOUNS = (
    "vm", "sunucu", "server", "host", "cluster", "namespace", "proje", "project", "node",
    "hypervisor", "datastore", "vcenter", "esx", "esxi",
)
# Yalın / belirtme / tamlayan / iyelik(+hâl) ekleri. Düz bulunma/yönelme/ayrılma ("sunucuda",
# "sunucuya", "sunucudan") BİLEREK yok: "node-exporter sunucuda çalışıyor mu" gibi niteleyici kullanım.
_SUFFIXES = (
    "", "i", "u", "in", "un", "nin", "nun", "si", "su", "sinin", "sunun", "ini", "inin", "unu", "unun",
    "inde", "inda", "inden", "indan", "ine", "ina", "unda", "unde", "undan", "unden", "une", "una",
    "nde", "nda", "nden", "ndan", "ne", "na", "ni", "nu", "yi", "yu", "sini", "sunu", "sine", "suna",
    "sinde", "sunda", "sinden", "sundan",
)
_NOUN_RE = re.compile(r"^(?:%s)(?:%s)$" % ("|".join(_NOUNS), "|".join(s for s in _SUFFIXES if s) + "|"))

# Tokenizer: kelime (harf/rakam/_ . -) + isteğe bağlı kesme ekli sonek
_WORD_RE = re.compile(r"([\w][\w.\-]*)(?:['’`´]([\w]+))?", re.UNICODE)

# Yazılım/OS/protokol önekleri: kimlik biçimli görünür ama envanter adı değildir
_SOFTWARE_PREFIXES = (
    "kube", "rhel", "centos", "ubuntu", "debian", "fedora", "suse", "oracle", "postgres", "mysql",
    "redis", "nginx", "apache", "tomcat", "node-exporter", "windows-exporter", "http", "https", "ssh",
    "vmware", "openshift", "kubernetes", "docker", "podman", "systemd", "ipv", "tcp", "udp", "icmp",
    "python", "java", "gpt", "llama", "x86", "arm64", "amd64", "win10", "win11", "win2",
)
_IP_RE = re.compile(r"^\d{1,3}(?:\.\d{1,3}){3}$")
_NUM_RE = re.compile(r"^[\d.,\-_:]+$")
_FILE_EXT_RE = re.compile(r"\.(?:txt|log|conf|cfg|yaml|yml|json|xml|sh|py|csv|pdf|png|jpg|md)$", re.I)

# Platform daraltma anahtar sözcükleri (fold'lanmış) → hypervisor_type
_TYPE_WORDS = {
    "VMWARE": ("vcenter", "vmware", "esxi", "esx"),
    "KVM": ("kvm", "olvm", "ovirt"),
    "OPENSHIFT_VIRT": ("openshift", "ocp", "kubevirt"),
}
_TYPE_LABEL = {"VMWARE": "VMware vCenter", "KVM": "KVM / OLVM", "OPENSHIFT_VIRT": "OpenShift Virtualization"}


@dataclass
class Catalog:
    names: set = field(default_factory=set)              # fold'lanmış tüm bilinen adlar (+ FQDN kısa adı)
    display: Dict[str, str] = field(default_factory=dict)  # fold → görünen ad (benzer ad önerisi)
    dupes: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)   # fold ad → kayıtlar (≥2)
    hypervisors: Dict[int, Dict[str, Any]] = field(default_factory=dict)
    ok: bool = True                                       # kritik kaynaklar yüklendi mi

    def add(self, value: Any) -> None:
        text = str(value or "").strip()
        if len(text) < 2:
            return
        key = fold(text)
        self.names.add(key)
        self.display.setdefault(key, text)
        short = key.split(".")[0]
        if short and short != key and len(short) >= 2:
            self.names.add(short)
            self.display.setdefault(short, text)


@dataclass
class GateResult:
    kind: str
    text: str
    entity: str = ""
    matches: int = 0
    reason: str = ""


# ── çıkarım ───────────────────────────────────────────────────────────────────

def _type_key(value: Any) -> str:
    """Enum / 'HypervisorType.VMWARE' / 'vmware' → 'VMWARE'."""
    raw = getattr(value, "value", value)
    return str(raw or "").split(".")[-1].strip().upper()


def _identifier_like(tok: str) -> bool:
    if len(tok) < _MIN_TOKEN_LEN or len(tok) > 120:
        return False
    if _IP_RE.match(tok) or _NUM_RE.match(tok) or _FILE_EXT_RE.search(tok):
        return False
    if not re.search(r"[A-Za-z]", tok):
        return False
    if not re.search(r"[\d\-_.]", tok):
        return False
    low = fold(tok)
    return not any(low.startswith(p) for p in _SOFTWARE_PREFIXES)


def _words(message: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for m in _WORD_RE.finditer(message or ""):
        word = m.group(1).rstrip(".-")
        if word:
            out.append((word, m.group(2) or ""))
    return out


def candidate_tokens(message: str) -> List[str]:
    """Tip adıyla (sahiplik/yalın biçimde) bağlı kimlik biçimli token'lar (sıralı, tekrarsız)."""
    ws = _words(message)
    found: List[str] = []
    for i in range(len(ws) - 1):
        tok, _tok_suffix = ws[i]
        noun_word, noun_suffix = ws[i + 1]
        if not _NOUN_RE.match(fold(noun_word + noun_suffix)):
            continue
        if _NOUN_RE.match(fold(tok)):      # "VM sunucu" gibi iki tip adı yan yana
            continue
        if _identifier_like(tok) and tok not in found:
            found.append(tok)
    return found


# ── katalog eşleşmesi ──────────────────────────────────────────────────────────

def is_known(token: str, cat: Catalog) -> bool:
    t = fold(token).strip(".-_")
    if not t:
        return True
    if t in cat.names or t.split(".")[0] in cat.names:
        return True
    if len(t) >= 5:
        # Kısaltılmış/uzatılmış yazım toleransı: yalnız uzunlukları yakınsa (kısa/uzun ≥ 0.8).
        # "vcenter-yok.local" gibi uydurma ad, katalogdaki kısa "vcenter" adıyla eşleşmemeli.
        for n in cat.names:
            if len(n) < _MIN_TOKEN_LEN:
                continue
            short, long_ = (n, t) if len(n) <= len(t) else (t, n)
            if short in long_ and len(short) / len(long_) >= 0.8:
                return True
    return False


def _similar(token: str, cat: Catalog, n: int = 3) -> List[str]:
    keys = list(cat.display.keys())
    close = difflib.get_close_matches(fold(token), keys, n=n, cutoff=0.72)
    seen: List[str] = []
    for k in close:
        d = cat.display.get(k, k)
        if d not in seen:
            seen.append(d)
    return seen


# ── metin yardımcıları ────────────────────────────────────────────────────────

_MD_ESCAPE = re.compile(r"([\\`*_{}\[\]()#+!|<>~])")


def _echo(text: str) -> str:
    s = (text or "").strip()[:_MAX_ECHO]
    return _MD_ESCAPE.sub(r"\\\1", s)


def _cell(v: Any) -> str:
    s = str(v if v not in (None, "") else "—").replace("|", "/").replace("\n", " ")
    return _MD_ESCAPE.sub(r"\\\1", s)[:80]


def not_found_text(token: str, similar: Sequence[str]) -> str:
    lines = [
        f"**{_echo(token)}** adıyla envanterde kayıt bulunamadı "
        "(VM, sunucu, ESX host, cluster, datastore, hypervisor ve OpenShift proje/node/cluster kayıtlarında arandı; "
        "son senkronizasyona göre).",
        "",
        "Bu ad için durum veya ayrıntı bilgisi veremem; tahmin yürütmüyorum.",
    ]
    if similar:
        lines += ["", "Benzer adlar: " + ", ".join(f"`{s}`" for s in similar)]
    lines += ["", "Adı kontrol edip yeniden sorabilirsiniz."]
    return "\n".join(lines)


def ambiguous_text(name: str, recs: Sequence[Dict[str, Any]]) -> str:
    head = (
        f"**{_echo(name)}** adıyla **{len(recs)} kayıt** var; hangisini kastettiğinizi netleştirir misiniz? "
        "Kayıtlar aşağıda:"
    )
    rows = ["| # | Hypervisor | Tür | Güç durumu | Host / Cluster | IP | OS |", "|---|---|---|---|---|---|---|"]
    for i, r in enumerate(recs, 1):
        rows.append(
            "| {} | {} | {} | {} | {} | {} | {} |".format(
                i, _cell(r.get("hypervisor_name")), _cell(_TYPE_LABEL.get(_type_key(r.get("hypervisor_type")), _type_key(r.get("hypervisor_type")) or "—")),
                _cell(r.get("power") or r.get("status")),
                _cell(r.get("host") or r.get("cluster")), _cell(r.get("ip")), _cell(r.get("os")),
            )
        )
    first = recs[0].get("hypervisor_name") or "ilk"
    tail = (
        f"Örneğin şöyle sorabilirsiniz: \"{first} üzerindeki {_echo(name)} VM'inin durumu ne?\""
    )
    return "\n".join([head, "", *rows, "", tail])


# ── çözümleme (saf) ────────────────────────────────────────────────────────────

def _narrow(message_fold: str, recs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Mesajdaki platform ipuçlarına (hypervisor adı / tür sözcüğü) göre kayıtları daralt."""
    def _has(word: str) -> bool:
        return bool(re.search(r"(?<![a-z0-9])%s(?![a-z0-9])" % re.escape(word), message_fold))

    kept: List[Dict[str, Any]] = []
    any_qual = False
    for r in recs:
        quals = set()
        for w in re.split(r"[^a-z0-9]+", fold(str(r.get("hypervisor_name") or ""))):
            if len(w) >= 3 and w not in ("virt", "the"):
                quals.add(w)
        quals.update(_TYPE_WORDS.get(_type_key(r.get("hypervisor_type")), ()))
        hit = {q for q in quals if _has(q)}
        if hit:
            any_qual = True
            kept.append(r)
    return kept if any_qual else list(recs)


def _in_multiword_name(token: str, message_fold: str, cat: Catalog) -> bool:
    """Boşluklu gerçek ad ("VMware vCenter Server-Test"): token adın son sözcüğüdür, ad mesajda tam geçiyor."""
    t = fold(token)
    for n in cat.names:
        if " " in n and t in n and n in message_fold:
            return True
    return False


def resolve(message: str, cat: Catalog, *, allow_virt_list: bool = False) -> Optional[GateResult]:
    if not message or not cat or not cat.ok or not cat.names:
        return None
    mfold = fold(message)

    # B. çoklu eşleşme (yalnız yetkili + sanallaştırma bağlamı)
    if allow_virt_list and cat.dupes:
        for name_fold, recs in cat.dupes.items():
            if len(name_fold) < 3:
                continue
            if re.search(r"(?<![a-z0-9._\-])%s(?![a-z0-9_\-]|\.[a-z0-9])" % re.escape(name_fold), mfold):
                left = _narrow(mfold, recs)
                if len(left) >= 2:
                    shown = recs[0].get("name") or name_fold
                    return GateResult(
                        kind=KIND_AMBIGUOUS, text=ambiguous_text(shown, left), entity=str(shown),
                        matches=len(left), reason="duplicate_name",
                    )
                return None        # tek kayda daraldı → normal akış

    # A. sıfır eşleşme
    unknown = [t for t in candidate_tokens(message)
               if not is_known(t, cat) and not _in_multiword_name(t, mfold, cat)]
    if unknown:
        tok = unknown[0]
        return GateResult(
            kind=KIND_NOT_FOUND, text=not_found_text(tok, _similar(tok, cat)), entity=tok, matches=0,
            reason="unknown_identifier",
        )
    return None


# ── katalog yükleme (DB; 60 sn önbellek) ─────────────────────────────────────────

_cache_lock = threading.Lock()
_cache: Tuple[float, Optional[Catalog]] = (0.0, None)
_override: Optional[Catalog] = None      # yalnız testler


def set_catalog_for_tests(cat: Optional[Catalog]) -> None:
    global _override, _cache
    _override = cat
    _cache = (0.0, None)


def clear_cache() -> None:
    global _cache
    with _cache_lock:
        _cache = (0.0, None)


def _load_catalog() -> Catalog:
    from app.core.database import ThreadSessionLocal
    from app.models.hypervisor import Hypervisor
    from app.models.server import Server

    cat = Catalog()
    db = ThreadSessionLocal()
    try:
        # kritik: sunucular + hypervisor'lar (yüklenemezse kapı kapalı)
        try:
            for h in db.query(Hypervisor).all():
                cat.hypervisors[h.id] = {"name": h.name, "type": _type_key(h.hypervisor_type)}
                cat.add(h.name)
                cat.add(h.hostname)
            groups: Dict[str, List[Dict[str, Any]]] = {}
            for s in db.query(Server).all():
                for v in (s.name, s.hostname, s.vm_name, s.vm_guest_hostname):
                    cat.add(v)
                key = fold(str(s.vm_name or s.name or "")).strip()
                if len(key) >= 3:
                    hv = cat.hypervisors.get(s.hypervisor_id) or {}
                    groups.setdefault(key, []).append({
                        "name": s.vm_name or s.name, "hypervisor_id": s.hypervisor_id,
                        "hypervisor_name": hv.get("name"), "hypervisor_type": hv.get("type"),
                        "power": s.vm_power_state, "status": s.status,
                        "host": s.vm_host_name, "cluster": s.vm_cluster,
                        "ip": s.vm_guest_ip or s.ip_address, "os": s.vm_guest_os_full or s.os_type,
                    })
            for key, recs in groups.items():
                if len(recs) >= 2:
                    recs.sort(key=lambda r: (r.get("hypervisor_id") or 0))
                    cat.dupes[key] = recs
        except Exception:
            logger.warning("[EntityGate] sunucu/hypervisor kataloğu yüklenemedi", exc_info=True)
            cat.ok = False
            return cat

        # tamamlayıcı kaynaklar (hata verirse o kaynak atlanır; katalog "bilinen"i azalmaz, kapı yine de güvenli
        # çünkü eksik katalog "yok" demeyi artırır → bu yüzden başarısız tamamlayıcıda kapıyı kapat)
        def _names(model_path: str, cls: str, *cols: str) -> None:
            mod = __import__(model_path, fromlist=[cls])
            M = getattr(mod, cls)
            for col in cols:
                attr = getattr(M, col, None)
                if attr is None:           # model bu sütunu taşımıyor → atla
                    continue
                for (v,) in db.query(attr).distinct().all():
                    cat.add(v)

        sources = (
            ("app.models.hypervisor_inventory", "HypervisorHostInventory", ("host_name", "cluster_name", "parent_name")),
            ("app.models.hypervisor_metric", "HypervisorHostMetric", ("host_name", "cluster_name")),
            ("app.models.virt_cluster", "VirtCluster", ("name",)),
            ("app.models.virt_datastore", "VirtDatastore", ("name",)),
            ("app.models.openshift", "OpenShiftCluster", ("name",)),
            ("app.models.openshift", "OpenShiftNode", ("name",)),
            ("app.models.openshift", "OpenShiftProject", ("name", "display_name")),
            ("app.models.openshift", "OpenShiftWorkload", ("name", "node_name")),
            # Donanım sağlayıcısı (Adım 12): OME/OneView sunucu + kasa adları — eşleşmemiş donanım adı «bulunamadı» OLMASIN
            ("app.models.hw", "HwServer", ("name", "os_hostname", "enclosure_name")),
            ("app.models.hw", "HwEnclosure", ("name",)),
        )
        for mp, cls, cols in sources:
            try:
                _names(mp, cls, *cols)
            except Exception:
                logger.warning("[EntityGate] katalog kaynağı atlandı: %s", cls, exc_info=True)
                cat.ok = False
                db.rollback()
        for mp, cls, cols in (
            ("app.models.exadata", "ExadataNode", ("name", "hostname")),
            ("app.models.exadata", "ExadataRack", ("name", "rack_name", "hostname")),
        ):
            try:           # Exadata tabloları isteğe bağlı (boş olabilir); model yoksa sessiz geç
                _names(mp, cls, *cols)
            except ImportError:
                pass
            except AttributeError:
                pass
            except Exception:
                logger.warning("[EntityGate] Exadata kataloğu atlandı", exc_info=True)
                cat.ok = False
                db.rollback()
        return cat
    finally:
        db.close()


_MAX_STALE_SEC = 600.0
_refreshing = False


def _refresh_in_background() -> None:
    """Süresi dolan katalogu arka planda yenile (tek uçuş); kullanıcı isteği yüklemeyi beklemez."""
    global _refreshing
    with _cache_lock:
        if _refreshing:
            return
        _refreshing = True

    def _run() -> None:
        global _cache, _refreshing
        try:
            cat = _load_catalog()
            with _cache_lock:
                _cache = (time.monotonic(), cat)
        except Exception:
            logger.warning("[EntityGate] katalog arka plan yenilemesi başarısız", exc_info=True)
        finally:
            with _cache_lock:
                _refreshing = False

    threading.Thread(target=_run, daemon=True, name="entity-gate-catalog").start()


def get_catalog() -> Optional[Catalog]:
    """Katalog (TTL 60 sn; süresi dolunca eski kopya dönülür + arka planda yenilenir; 10 dk'dan eskiyse eşzamanlı yüklenir)."""
    global _cache
    if _override is not None:
        return _override
    now = time.monotonic()
    with _cache_lock:
        ts, cat = _cache
    if cat is not None:
        age = now - ts
        if age < _CATALOG_TTL_SEC:
            return cat
        if age < _MAX_STALE_SEC:
            _refresh_in_background()
            return cat
    try:
        cat = _load_catalog()
    except Exception:
        logger.warning("[EntityGate] katalog yüklenemedi", exc_info=True)
        cat = None
    with _cache_lock:
        _cache = (now, cat)
    return cat


def warm_up() -> None:
    """Başlangıçta katalogu ısıt (arka plan iş parçacığı; hata sessiz)."""
    def _run() -> None:
        try:
            get_catalog()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True, name="entity-gate-warmup").start()


# ── pipeline girişi ─────────────────────────────────────────────────────────────

def _enabled() -> bool:
    try:
        from app.services import runtime_settings
        return bool(runtime_settings.get_bool("chat_entity_gate_enabled"))
    except Exception:
        return True


def virt_list_allowed(platform: Optional[str], allowed_modules: Any = None) -> bool:
    """Çoklu eşleşme listesi sanallaştırma verisi gösterir: yalnız o bağlamda yetkili kullanıcıya."""
    plat = (platform or "").strip().lower()
    if plat in ("virt", "hypervisor", "virtualization"):
        return True
    if plat == "unified":
        return allowed_modules is None or "virt" in set(allowed_modules)
    return False


def gate_response(message: str, *, platform: Optional[str] = None, allowed_modules: Any = None) -> Optional[str]:
    """Pipeline'ların chitchat noktasından çağrılır: şablon cevap (veya None → normal akış)."""
    try:
        if not _enabled():
            return None
        cat = get_catalog()
        if cat is None:
            return None
        res = resolve(message, cat, allow_virt_list=virt_list_allowed(platform, allowed_modules))
    except Exception:
        logger.warning("[EntityGate] kontrol hatası", exc_info=True)
        return None
    if res is None:
        return None
    try:
        from app.services.chat_quality import trace as cq_trace
        cq_trace.note_path("entity_gate", gate=res.kind, entity=res.entity[:60], matches=res.matches,
                           reason=res.reason, platform=platform or "")
    except Exception:
        pass
    logger.info("[EntityGate] %s entity=%r matches=%s platform=%s", res.kind, res.entity[:60], res.matches, platform)
    return res.text
