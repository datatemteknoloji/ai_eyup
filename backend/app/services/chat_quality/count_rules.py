"""Sayım kuralları (Adım 5b): "kaç VM / kapalı VM / host / datastore / cluster / node / proje" sorularını
LLM'e ve araca HİÇ gitmeden, SQL COUNT ile ve kapsam etiketli/kırılımlı cevaplar.

Bağlama noktası: `chat_chitchat_policy.canned_chitchat_answer` — eylem kapısından ve varlık kapısından SONRA
(sıra: eylem → varlık → sayım kuralı → LLM/araç). Dört sohbet hattı + Admin/Unified birlikte yararlanır;
Automic hattı bu noktadan geçmez.

Muhafazakârdır: yalnız net sayım cümlelerinde tetiklenir; tanınmayan sözcük, rakam (yanlış öncül),
zaman/metrik/eylem sözcüğü, birden çok soru varsa `None` (normal akış). Pod / hatalı pod ve Linux / Windows
sunucu sayımı `count_extra` (Adım 6, K2/K3).

RBAC: sanallaştırma konuları yalnız `virt` hattında veya Unified'da `allowed_modules is None | 'virt'`;
OpenShift konuları yalnız `openshift` hattında veya Unified'da `None | 'openshift'`. Yetkisiz platform
cevapta HİÇ görünmez (konu kapısı).

Saf kısım (`analyze`, `render_*`) DB'siz test edilir; veri çekme (`fetch_*`) salt-okunur SELECT'tir.
"""
from __future__ import annotations

import logging
import re
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.services.chat_quality import power_state as ps
from app.services.chat_quality.claims import fold
from app.services.chat_quality.count_scope import (
    HV, TYPE_LABEL, TYPE_WORDS, Scope, ScopeCatalog, resolve_ocp, resolve_virt, scope_label, tokenize,
)

logger = logging.getLogger(__name__)

# ── sözlükler (fold'lanmış) ───────────────────────────────────────────────────────

_COUNT_WORDS = {"kac", "kactir", "kactur"}
_COUNT_NOUNS = {"sayisi", "sayisini", "sayisinin", "adedi", "adedini"}

# Baş/son kısımda zararsız sözcükler (ve kesme ekleri)
_NEUTRAL = {
    "var", "vardir", "bulunuyor", "bulunmakta", "mevcut", "kayitli", "kayit", "durumda", "mi", "mu",
    "tane", "adet", "toplam", "tum", "butun", "su", "an", "simdi", "ortamda", "ortamdaki", "sistemde",
    "sistemdeki", "envanterde", "envanterdeki", "benim", "bizim", "sahibiz", "sahip", "bana", "bize",
    "soyle", "soyler", "misin", "misiniz", "verir", "verebilir", "lutfen", "acaba", "peki", "merhaba",
    "selam", "evet", "uzerinde", "uzerindeki", "icinde", "de", "da", "te", "ta", "nde", "nda", "ndeki",
    "ndaki", "deki", "daki", "teki", "taki", "ki", "in", "un", "nin", "nun", "i", "u", "si", "su", "ler",
    "lar", "im", "um", "lerim", "larim", "inde", "inda", "unda", "unde", "inin", "ve", "ile", "icin",
    "genel", "olarak", "hepsi", "toplamda", "ozet", "sanal", "virtual", "virtualization", "durum", "ne", "kadar",
    "nedir", "larda", "lerde", "larin", "lerin", "lardaki", "lerdeki", "larinda", "lerinde",
    # İngilizce
    "how", "many", "are", "there", "do", "we", "have", "is", "the", "of", "number", "total", "currently",
    "now", "all", "our", "my", "what", "s", "count", "show", "me", "on", "at", "a", "an", "powered",
}

_STATE = {
    "on": {"acik", "calisan", "calisiyor", "calisir", "calisanlar", "aktif", "running", "on"},
    "off": {"kapali", "kapalidir", "off", "stopped", "shutdown"},
    "suspended": {"askida", "suspended"},
}
_STATE_BY_WORD = {w: s for s, ws in _STATE.items() for w in ws}

# Sayım dışı niyet göstergeleri → kural devreye girmez (normal akış)
_BLOCK_RE = re.compile(
    r"\b(gb|tb|mb|kb|ghz|mhz|core|cores|cpu|vcpu|ram|bellek|memory|disk|diski|snapshot|snapshots|"
    r"restart|reboot|yeniden|alarm|alarmlar|olay|event|events|hata|error|uyari|warning|yuksek|dusuk|"
    r"kullan\w*|dolu|doluluk|sure|saat|dakika|saniye|gun|hafta|ay|yil|dun|bugun|gecen|onceki|son|"
    r"sil\w*|olustur\w*|tasi\w*|migrat\w*|vmotion|kritik|yedek|backup|lisans|maliyet|fiyat|ip|mac|vlan|"
    r"port|tools|template|sablon|idle|atil|bosta|overcommit|kapasite|capacity|performans|gecikme|latency|"
    r"iops|trafik|network|ag|pod|pods|deployment|deployments|service|route|log|loglar|sorunlu|hatali|"
    r"yesterday|today|last|week|month|year|hour|hours|day|days|alarms?|cores?|snapshot\w*|restart\w*|reboot\w*|"
    r"delete\w*|created|usage|high|low|"
    r"problemli|eski|yeni|eklen\w*|kapand\w*|acild\w*|basla\w*|durdur\w*|kapat\w*|ac|calistir\w*|liste\w*|"
    r"goster|detay|isim|ad|adi|adlari|hangileri|nelerdir|neler|oner\w*|yer|sigar|sigiyor)\b"
)
# Pod / sunucu sayımında da normal akışa bırakılan niyetler (hata/hatalı/pod burada engel değil)
_EXTRA_BLOCK_RE = re.compile(
    r"\b(gb|tb|mb|cpu|vcpu|ram|bellek|memory|disk|restart\w*|yeniden|reboot\w*|alarm\w*|olay|event\w*|"
    r"kullan\w*|yuksek|dusuk|en|sure|saat|dakika|gun|hafta|ay|yil|dun|bugun|gecen|onceki|son|"
    r"sil\w*|olustur\w*|log|loglar|liste\w*|goster|detay|isim|ad|adi|adlari|hangi|hangileri|nelerdir|neler|"
    r"namespace\w*|proje\w*|project\w*|node\w*|deployment\w*|vm\w*|acik|kapali|patch|guncelleme|update\w*|"
    r"yesterday|today|last|week|month|year|hour|day|usage|high|low|top)\b"
)
_GROUPBY_RE = re.compile(r"\b(hypervisor\w*|cluster\w*|platform\w*|vcenter\w*)\s+(?:gore|bazinda|bazli|basina)\b")
_NUM_RE = re.compile(r"(?<![\w.\-])\d+(?![\w.\-])")

_NOUN_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("vm", re.compile(r"^(?:vms?|vm(?:ler|lerim|lerin|leri|im|in|i)|makine[a-z]{0,8}|makina[a-z]{0,8}|machines?)$")),
    ("host", re.compile(r"^host(?!name)[a-z]{0,10}$")),
    ("datastore", re.compile(r"^datastore[a-z]{0,10}$")),
    ("cluster", re.compile(r"^cluster[a-z]{0,10}$")),
    ("node", re.compile(r"^node[a-z]{0,10}$")),
    ("project", re.compile(r"^(?:proje[a-z]{0,10}|project[a-z]{0,6}|namespace[a-z]{0,10})$")),
    ("hypervisor", re.compile(r"^hypervisor[a-z]{0,10}$")),
]
# Sayılan konunun yanında "kapsam sözcüğü" olarak geçebilen diğer isimler
_SCOPE_NOUNS = {
    "vm": {"cluster", "hypervisor"},
    "host": {"cluster", "hypervisor"},
    "datastore": {"cluster", "hypervisor"},
    "node": {"cluster"},
    "project": {"cluster"},
    "cluster": {"hypervisor"},
    "hypervisor": set(),
}
_LOC_WORDS = re.compile(r"^(?:hypervisor\w*|host\w*|hostta|cluster\w*|platform\w*|vcenter\w*|esxi\w*)$")
_LOC_NEUTRAL = {
    "vm", "vmi", "makine", "makinesi", "sunucu", "sunucusu", "server", "nerede", "calisiyor", "calisir",
    "calisiyorlar", "bulunuyor", "duruyor", "yer", "aliyor", "barinan", "konumlanmis", "nerde",
    "ve", "durumu", "hangi", "uzerinde", "icinde", "var", "mi", "mu", "kac", "kactir",
}
_NEUTRAL_LOC = _NEUTRAL | _LOC_NEUTRAL


@dataclass
class Plan:
    kind: str                       # count | compare | location
    topic: str = ""                 # vm | host | datastore | cluster | node | project | hypervisor
    state: str = "all"              # on | off | suspended | all
    domain: str = "virt"            # virt | ocp | both
    scope: Scope = field(default_factory=Scope)
    ocp_scope: Scope = field(default_factory=Scope)
    by: str = ""                    # compare: hypervisor | cluster
    candidates: List[str] = field(default_factory=list)   # location: aday ad token'ları
    pod_filter: str = ""            # pod: all | faulty | reason:<Ad> | status:<running|succeeded|pending>
    os_kinds: Tuple[str, ...] = ()  # server: ("linux",) | ("windows",) | ("linux", "windows")


# ── RBAC / platform ───────────────────────────────────────────────────────────────

def virt_ok(platform: Optional[str], allowed_modules: Any = None) -> bool:
    p = (platform or "").strip().lower()
    if p in ("virt", "hypervisor", "virtualization"):
        return True
    if p == "unified":
        return allowed_modules is None or "virt" in set(allowed_modules)
    return False


def ocp_ok(platform: Optional[str], allowed_modules: Any = None) -> bool:
    p = (platform or "").strip().lower()
    if p == "openshift":
        return True
    if p == "unified":
        return allowed_modules is None or "openshift" in set(allowed_modules)
    return False


# ── saf çözümleme ──────────────────────────────────────────────────────────────────

def _noun_topic(tok: str) -> Optional[str]:
    for topic, rx in _NOUN_PATTERNS:
        if rx.match(tok):
            return topic
    return None


def _prefilter(mf: str) -> bool:
    return bool(re.search(r"\b(kac|kactir|sayisi\w*|adedi\w*|how many|number of|hangi|nerede|nerde)\b", mf))


def analyze(message: str, cat: ScopeCatalog, *, platform: Optional[str], allowed_modules: Any = None) -> Optional[Plan]:
    """Mesaj → Plan (veya None → normal akış). Saf; DB'ye dokunmaz."""
    if not message or not cat or not cat.ok:
        return None
    if len(message) > 220 or message.count("\n") > 1:
        return None
    mf = fold(message)
    mf = re.sub(r"\baskiya\s+(?:alinmis|alinan|alindi|alinmislar)\b", "askida", mf)   # «askıya alınmış» = askıda
    changed = False
    # «hypervisor'lara göre / bazında … sayı» → dağılım isteği: sayım + hypervisor kırılımı (render_vm zaten kırılım verir)
    gb = _GROUPBY_RE.search(mf)
    if gb:
        if gb.group(1).startswith("cluster"):
            return None                      # cluster bazlı VM dağılımı bu kuralın kapsamı dışı → normal akış
        mf = _GROUPBY_RE.sub(" ", mf)
        mf = re.sub(r"\bsayi\b", "sayisi", mf)
        mf = re.sub(r"\b(?:olarak|ver|verir\s+misin|veriniz|ver\s+misin|goster\s+misin)\b", " ", mf)
        changed = True
    # «ortam/ortamlarındaki» ve «sanallaştırma» yalnız süs sözcüğü; sanallaştırma = VMware/KVM/OpenShift Virt tarafı (virt)
    virt_word = bool(re.search(r"\bsanallastirma\w*\b", mf))
    if re.search(r"\bortam\w*\b|\bsanallastirma\w*\b", mf):
        mf = re.sub(r"\bortam\w*\b|\bsanallastirma\w*\b", " ", mf)
        changed = True
    if changed:
        mf = re.sub(r"\s+", " ", mf).strip()
        message = mf                         # kapsam çözümü de süslerden arındırılmış (katlanmış) metinle
    if not _prefilter(mf):
        return None
    v_ok, o_ok = virt_ok(platform, allowed_modules), ocp_ok(platform, allowed_modules)
    from app.services.chat_quality import count_extra as cx
    if not (v_ok or o_ok or cx.linux_ok(platform, allowed_modules) or cx.windows_ok(platform, allowed_modules)):
        return None
    if _NUM_RE.search(mf):                    # rakam (yanlış öncül, "8 vCPU", "son 3 gün" …) → normal akış
        return None
    toks = tokenize(mf)
    words = [t for t, _, _ in toks]
    if cx.has_pod_word(words) or cx.has_server_word(words):
        if _EXTRA_BLOCK_RE.search(mf):
            return None
        return cx.analyze_extra(message, mf, toks, cat, neutral=set(_NEUTRAL),
                                platform=platform, allowed_modules=allowed_modules, o_ok=o_ok)
    if not (v_ok or o_ok):
        return None
    if "hangi" in words or "nerede" in words or "nerde" in words:
        return _analyze_which(message, mf, toks, cat, v_ok, o_ok)
    if _BLOCK_RE.search(mf):
        return None
    return _analyze_count(message, mf, toks, cat, platform, v_ok, o_ok, virt_word=virt_word)


def _analyze_count(message: str, mf: str, toks, cat: ScopeCatalog, platform, v_ok: bool, o_ok: bool, *, virt_word: bool = False) -> Optional[Plan]:
    words = [t for t, _, _ in toks]
    kac_idx = [i for i, w in enumerate(words) if w in _COUNT_WORDS]
    cn_idx = [i for i, w in enumerate(words) if w in _COUNT_NOUNS]
    en = ("how" in words and "many" in words) or ("number" in words and "of" in words)
    if len(kac_idx) > 1 or len(cn_idx) > 1 or (en and (kac_idx or cn_idx)):
        return None
    if not (kac_idx or cn_idx or en):
        return None
    noun_at: Dict[int, str] = {}
    for i, w in enumerate(words):
        t = _noun_topic(w)
        if t:
            noun_at[i] = t
    # sayılan isim: "X sayısı" → sayım sözcüğünden ÖNCEKİ en yakın isim; "kaç X" / "how many X" → sonraki ilk isim
    topic = ""
    counted_idx = -1
    if cn_idx:
        before = [i for i in noun_at if i < cn_idx[0] and cn_idx[0] - i <= 4]
        if before:
            counted_idx = max(before)
    if counted_idx < 0:
        anchor = kac_idx[0] if kac_idx else (words.index("many") if en and "many" in words else (words.index("of") if en else -1))
        after = [i for i in noun_at if i > anchor and i - anchor <= 6]
        if after:
            counted_idx = min(after)
        elif kac_idx and kac_idx[0] == len(words) - 1:
            # «Kapalı VM kaç?» — sayım sözcüğü sonda: önündeki en yakın isim
            before = [i for i in noun_at if i < kac_idx[0] and kac_idx[0] - i <= 3]
            if before:
                counted_idx = max(before)
    esxi_only = False
    if counted_idx >= 0:
        topic = noun_at[counted_idx]
    elif any(w in ("esxi", "esx") for w in words):
        topic, esxi_only = "host", True
    if not topic:
        return None
    noun_idx: Set[int] = set(noun_at)
    # diğer isimler: yalnız izinli kapsam sözcüğü olabilir
    for i, t in noun_at.items():
        if i == counted_idx or t == topic:
            continue
        if t not in _SCOPE_NOUNS.get(topic, set()):
            return None
    state = "all"
    state_idx: Set[int] = set()
    for i, w in enumerate(words):
        s_ = _STATE_BY_WORD.get(w)
        if s_:
            if w == "on" and "powered" not in words:   # yalın İngilizce "on" → nötr
                continue
            if state != "all" and state != s_:
                return None
            state = s_
            state_idx.add(i)
    if state != "all" and topic != "vm":
        return None

    # domain + kapsam
    if topic in ("vm", "host", "datastore", "hypervisor"):
        domain = "virt"
    elif topic in ("node", "project"):
        domain = "ocp"
    else:  # cluster
        has_ocp_word = any(w in TYPE_WORDS["OPENSHIFT_VIRT"] for w in words)
        p = (platform or "").strip().lower()
        if p == "openshift":
            domain = "ocp"
        elif p in ("virt", "hypervisor", "virtualization"):
            domain = "virt"
        elif virt_word and v_ok and not has_ocp_word:
            domain = "virt"                     # «sanallaştırma cluster'ı» = sanallaştırma (OpenShift küme sayısı değil)
        elif has_ocp_word and o_ok:
            domain = "ocp"
        elif v_ok and o_ok:
            domain = "both"
        else:
            domain = "ocp" if o_ok else "virt"
    if domain == "virt" and not v_ok:
        return None
    if domain == "ocp" and not o_ok:
        return None

    neutral_for_prefix = set(_NEUTRAL) | _COUNT_WORDS | _COUNT_NOUNS | set(_STATE_BY_WORD)
    plan = Plan(kind="count", topic=topic, state=state, domain=domain)
    consumed: Set[int] = set(noun_idx) | state_idx
    if domain in ("virt", "both"):
        plan.scope = resolve_virt(message, cat, neutral=neutral_for_prefix)
        consumed |= plan.scope.consumed
    if domain in ("ocp", "both"):
        if domain == "both" and not plan.scope.is_all:
            # virt kapsamı çözüldüyse "both" yerine virt
            plan.domain = "virt"
        else:
            plan.ocp_scope = resolve_ocp(message, cat, neutral=neutral_for_prefix)
            consumed |= plan.ocp_scope.consumed
            if domain == "both" and not plan.ocp_scope.is_all:
                plan.domain = "ocp"
    if esxi_only:
        # 'esxi' hem konu hem VMware kapsamı: kapsam tüketimi zaten tür sözcüğü olarak işlendi
        pass
    # kalan token'lar: yalnız nötr/sayım sözcüğü olabilir; tanınmayan sözcük → normal akış
    for i, w in enumerate(words):
        if i in consumed or w in _NEUTRAL or w in _COUNT_WORDS or w in _COUNT_NOUNS:
            continue
        if w in ("vm", "vms") and topic == "vm":
            continue
        if w in ("hypervisor", "hypervisors") and plan.scope.kind in ("name", "type", "prefix", "cluster"):
            continue
        if w in ("cluster", "clusters") and topic == "cluster":
            continue
        if _noun_topic(w) == topic:
            continue
        if w in TYPE_WORDS["OPENSHIFT_VIRT"] or any(w in ws for ws in TYPE_WORDS.values()):
            continue
        return None
    return plan


def _analyze_which(message: str, mf: str, toks, cat: ScopeCatalog, v_ok: bool, o_ok: bool) -> Optional[Plan]:
    words = [t for t, _, _ in toks]
    if _BLOCK_RE.search(mf):
        return None
    # --- karşılaştırma: "hangi cluster'da daha fazla node var?" ---
    more = ("daha" in words and "fazla" in words) or ("en" in words and ("cok" in words or "fazla" in words))
    if more:
        nouns = [t for t in (_noun_topic(w) for w in words) if t in ("vm", "node", "project")]
        by_words = [w for w in words if re.match(r"^(?:cluster\w*|hypervisor\w*|platform\w*|vcenter\w*)$", w)]
        uniq = list(dict.fromkeys(nouns))
        if len(uniq) != 1 or not by_words:
            return None
        topic = uniq[0]
        by = "cluster" if any(w.startswith("cluster") for w in by_words) else "hypervisor"
        allowed_extra = _NEUTRAL | {"hangi", "daha", "fazla", "en", "cok"}
        for w in words:
            if w in allowed_extra or _noun_topic(w) == topic or re.match(r"^(?:cluster\w*|hypervisor\w*|platform\w*|vcenter\w*)$", w):
                continue
            return None
        if topic in ("node", "project"):
            if not o_ok:
                return None
            return Plan(kind="compare", topic=topic, domain="ocp", by="cluster")
        if not v_ok:
            return None
        return Plan(kind="compare", topic="vm", domain="virt", by=by)
    # --- konum: "<ad> VM'i hangi hypervisor üzerinde?" ---
    if not v_ok:
        return None
    if not any(_LOC_WORDS.match(w) for w in words) and "nerede" not in words and "nerde" not in words:
        return None
    sc = resolve_virt(message, cat, neutral=set(_NEUTRAL_LOC))
    cands: List[str] = []
    for i, w in enumerate(words):
        if i in sc.consumed or w in _NEUTRAL_LOC or _LOC_WORDS.match(w):
            continue
        if _noun_topic(w) in ("vm", "host", "cluster", "hypervisor"):
            continue
        cands.append(w)
    if not 1 <= len(cands) <= 2:
        return None
    return Plan(kind="location", topic="location", domain="virt", scope=sc, candidates=cands)


# ── veri (salt-okunur SELECT) ──────────────────────────────────────────────────────

_CAT_TTL = 30.0
_cat_lock = threading.Lock()
_cat_cache: Tuple[float, Optional[ScopeCatalog]] = (0.0, None)
_cat_override: Optional[ScopeCatalog] = None


def set_catalog_for_tests(cat: Optional[ScopeCatalog]) -> None:
    global _cat_override, _cat_cache
    _cat_override = cat
    _cat_cache = (0.0, None)


def _type_key(value: Any) -> str:
    raw = getattr(value, "value", value)
    return str(raw or "").split(".")[-1].strip().upper()


def load_catalog(db) -> ScopeCatalog:
    from sqlalchemy import text

    cat = ScopeCatalog()
    for r in db.execute(text("select id, name, hypervisor_type::text from hypervisors order by id")).all():
        cat.hypervisors.append(HV(int(r[0]), str(r[1]), _type_key(r[2])))
    for r in db.execute(text("select id, name from openshift_clusters order by id")).all():
        cat.ocp_clusters.append((int(r[0]), str(r[1])))
    vc: Dict[str, Tuple[str, List[int]]] = {}
    for sql in (
        "select distinct vm_cluster, hypervisor_id from servers where hypervisor_id is not null and vm_cluster is not null and vm_cluster <> ''",
        "select distinct name, hypervisor_id from virt_clusters",
    ):
        try:
            for name, hid in db.execute(text(sql)).all():
                k = fold(str(name))
                disp, ids = vc.setdefault(k, (str(name), []))
                if hid is not None and int(hid) not in ids:
                    ids.append(int(hid))
        except Exception:
            db.rollback()
    cat.virt_clusters = vc
    return cat


def get_catalog() -> Optional[ScopeCatalog]:
    global _cat_cache
    if _cat_override is not None:
        return _cat_override
    now = time.monotonic()
    with _cat_lock:
        ts, cat = _cat_cache
    if cat is not None and now - ts < _CAT_TTL:
        return cat
    from app.core.database import ThreadSessionLocal
    db = ThreadSessionLocal()
    try:
        cat = load_catalog(db)
    except Exception:
        logger.warning("[CountRules] kapsam kataloğu yüklenemedi", exc_info=True)
        cat = None
    finally:
        db.close()
    with _cat_lock:
        _cat_cache = (now, cat)
    return cat


def warm_up() -> None:
    """Başlangıçta kapsam kataloğunu ve bir DB bağlantısını ısıt (arka plan; hata sessiz)."""
    def _run() -> None:
        try:
            get_catalog()
        except Exception:
            pass
    threading.Thread(target=_run, daemon=True, name="count-rules-warmup").start()


def _interval_sec() -> int:
    try:
        from app.services import runtime_settings
        return int(runtime_settings.get_int("esx_metric_interval_sec") or 900)
    except Exception:
        return 900


def stale_threshold_sec() -> int:
    """Bayat eşiği: o hypervisor'ın en yeni satırından 2 × esx_metric_interval_sec geride."""
    return 2 * _interval_sec()


def _ids(sc: Scope) -> Optional[List[int]]:
    return None if sc.hv_ids is None else list(sc.hv_ids)


def fetch_vm_counts(db, scope: Scope) -> List[Tuple[int, Optional[str], int]]:
    from sqlalchemy import text
    where = ["hypervisor_id is not null"]
    params: Dict[str, Any] = {}
    if scope.hv_ids is not None:
        where.append("hypervisor_id = ANY(:ids)")
        params["ids"] = list(scope.hv_ids)
    if scope.cluster_names:
        where.append("lower(vm_cluster) = ANY(:cl)")
        params["cl"] = [c.lower() for c in scope.cluster_names]
    sql = f"select hypervisor_id, vm_power_state, count(*) from servers where {' and '.join(where)} group by 1,2"
    return [(int(a), b, int(n)) for a, b, n in db.execute(text(sql), params).all()]


def fetch_hosts(db, scope: Scope) -> List[Dict[str, Any]]:
    """Host başına SON metrik satırı (hypervisor_host_metrics zaman serisi)."""
    from sqlalchemy import text
    where = ["1=1"]
    params: Dict[str, Any] = {}
    if scope.hv_ids is not None:
        where.append("hypervisor_id = ANY(:ids)")
        params["ids"] = list(scope.hv_ids)
    if scope.cluster_names:
        where.append("lower(cluster_name) = ANY(:cl)")
        params["cl"] = [c.lower() for c in scope.cluster_names]
    sql = (
        "select distinct on (hypervisor_id, host_name) hypervisor_id, host_name, timestamp "
        f"from hypervisor_host_metrics where {' and '.join(where)} "
        "order by hypervisor_id, host_name, timestamp desc"
    )
    return [{"hv": int(a), "name": str(b), "ts": c} for a, b, c in db.execute(text(sql), params).all()]


def fetch_datastores(db, scope: Scope) -> List[Dict[str, Any]]:
    from sqlalchemy import text
    params: Dict[str, Any] = {}
    where = "1=1"
    if scope.hv_ids is not None:
        where = "hypervisor_id = ANY(:ids)"
        params["ids"] = list(scope.hv_ids)
    sql = f"select hypervisor_id, name, as_of from virt_datastores where {where}"
    return [{"hv": int(a), "name": str(b), "ts": c} for a, b, c in db.execute(text(sql), params).all()]


def fetch_clusters(db, scope: Scope) -> List[Dict[str, Any]]:
    from sqlalchemy import text
    params: Dict[str, Any] = {}
    where = "1=1"
    if scope.hv_ids is not None:
        where = "hypervisor_id = ANY(:ids)"
        params["ids"] = list(scope.hv_ids)
    sql = f"select hypervisor_id, name, as_of from virt_clusters where {where}"
    return [{"hv": int(a), "name": str(b), "ts": c} for a, b, c in db.execute(text(sql), params).all()]


def fetch_ocp_counts(db, table: str, scope: Scope, cat: ScopeCatalog) -> Dict[int, int]:
    from sqlalchemy import text
    assert table in ("openshift_nodes", "openshift_projects")
    rows = db.execute(text(f"select cluster_id, count(*) from {table} group by 1")).all()
    cnt = {int(a): int(n) for a, n in rows}
    ids = scope.ocp_ids if scope.ocp_ids is not None else [cid for cid, _ in cat.ocp_clusters]
    return {cid: cnt.get(cid, 0) for cid in ids}


def fetch_last_sync(db, hv_ids: Optional[Iterable[int]]) -> Optional[datetime]:
    """Kapsamdaki hypervisor'ların en yeni `last_sync` değeri (None → hepsi)."""
    from sqlalchemy import text
    try:
        ids = list(hv_ids) if hv_ids is not None else None
        sql = "select max(last_sync) from hypervisors" + (" where id = ANY(:i)" if ids is not None else "")
        return db.execute(text(sql), {"i": ids} if ids is not None else {}).scalar()
    except Exception:
        db.rollback()
        return None


def fetch_ocp_last_sync(db, ocp_ids: Optional[Iterable[int]]) -> Optional[datetime]:
    from sqlalchemy import text
    try:
        ids = list(ocp_ids) if ocp_ids is not None else None
        sql = "select max(last_sync) from openshift_clusters" + (" where id = ANY(:i)" if ids is not None else "")
        return db.execute(text(sql), {"i": ids} if ids is not None else {}).scalar()
    except Exception:
        db.rollback()
        return None


def fetch_locations(db, candidates: Sequence[str]) -> List[Dict[str, Any]]:
    from sqlalchemy import text
    c = [x.lower() for x in candidates]
    sql = (
        "select name, vm_name, hostname, hypervisor_id, vm_power_state, vm_host_name, vm_cluster, "
        "coalesce(vm_guest_ip, ip_address) from servers where hypervisor_id is not null and ("
        "lower(name) = ANY(:c) or lower(vm_name) = ANY(:c) or lower(hostname) = ANY(:c) or lower(vm_guest_hostname) = ANY(:c)) "
        "order by hypervisor_id, name"
    )
    return [{"name": (r[1] or r[0]), "hv": int(r[3]), "power": r[4], "host": r[5], "cluster": r[6], "ip": r[7]}
            for r in db.execute(text(sql), {"c": c}).all()]


def fetch_vm_group_counts(db, by: str) -> List[Tuple[str, int]]:
    from sqlalchemy import text
    if by == "cluster":
        sql = ("select coalesce(nullif(vm_cluster,''), '(cluster bilgisi yok)'), count(*) from servers "
               "where hypervisor_id is not null group by 1 order by 2 desc, 1")
    else:
        sql = ("select h.name, count(*) from servers s join hypervisors h on h.id = s.hypervisor_id "
               "group by 1 order by 2 desc, 1")
    return [(str(a), int(n)) for a, n in db.execute(text(sql)).all()]


# ── yerleşim (saf) ──────────────────────────────────────────────────────────────────

def _cell(v: Any) -> str:
    s = str(v if v not in (None, "") else "—").replace("|", "/").replace("\n", " ")
    return s[:80]


def _fmt_ts(ts: Optional[datetime]) -> str:
    if ts is None:
        return "bilinmiyor"
    try:
        if ts.tzinfo is not None:
            ts = ts.astimezone()
        return ts.strftime("%Y-%m-%d %H:%M")
    except Exception:
        return str(ts)


def _source_line(ts: Optional[datetime], extra: str = "") -> str:
    return f"_Kaynak: envanter veritabanı{extra}; son senkron: {_fmt_ts(ts)}._"


def split_fresh(rows: List[Dict[str, Any]], threshold_sec: int) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Her hypervisor için en yeni zamandan `threshold_sec` fazla geride olan satırlar BAYAT."""
    newest: Dict[int, datetime] = {}
    for r in rows:
        ts = r.get("ts")
        if ts is not None and (r["hv"] not in newest or ts > newest[r["hv"]]):
            newest[r["hv"]] = ts
    fresh: List[Dict[str, Any]] = []
    stale: List[Dict[str, Any]] = []
    for r in rows:
        ts = r.get("ts")
        top = newest.get(r["hv"])
        if ts is None or top is None or (top - ts).total_seconds() > threshold_sec:
            stale.append(r)
        else:
            fresh.append(r)
    return fresh, stale


def _hv_map(cat: ScopeCatalog) -> Dict[int, HV]:
    return {h.id: h for h in cat.hypervisors}


def _hv_title(h: Optional[HV]) -> str:
    return f"{h.name} ({TYPE_LABEL.get(h.type, h.type)})" if h else "—"


def render_vm(plan: Plan, cat: ScopeCatalog, rows: List[Tuple[int, Optional[str], int]], last_sync: Optional[datetime]) -> str:
    hvm = _hv_map(cat)
    per: Dict[int, Dict[str, Any]] = {}
    for hid, raw, n in rows:
        d = per.setdefault(hid, {"raws": []})
        d["raws"] += [raw] * n
    tot = {"total": 0, "on": 0, "off": 0, "suspended": 0, "transitional": 0, "unknown": 0}
    other_raw: Dict[str, int] = {}
    table = []
    for hid in sorted(per):
        s = ps.summarize(per[hid]["raws"])
        for k in tot:
            tot[k] += s[k]
        for k, v in s["other_raw"].items():
            other_raw[k] = other_raw.get(k, 0) + v
        table.append((hid, s))
    label = scope_label(plan.scope, cat, domain="virt")
    if plan.state == "on":
        head, n = "Çalışan (açık) VM", tot["on"]
    elif plan.state == "off":
        head, n = "Kapalı VM", tot["off"]
    elif plan.state == "suspended":
        head, n = "Askıdaki VM", tot["suspended"]
    else:
        head, n = "Toplam VM", tot["total"]
    L = [f"**{head}: {n}**"]
    if plan.state != "all":
        L[0] += f" (kapsamdaki toplam {tot['total']} VM içinde)"
    L.append("")
    L.append(f"Kapsam: {label}")
    dist = (f"Dağılım: açık **{tot['on']}** · kapalı **{tot['off']}** · askıda **{tot['suspended']}**"
            f" · toplam **{tot['total']}**")
    other = tot["transitional"] + tot["unknown"]
    if other:
        dist += f" · diğer/bilinmeyen **{other}** ({ps.other_note(other_raw)})"
    L.append(dist)
    if len(table) > 1:
        L += ["", "| Hypervisor | Tür | Toplam | Açık | Kapalı | Askıda | Diğer |", "|---|---|---:|---:|---:|---:|---:|"]
        for hid, s in table:
            h = hvm.get(hid)
            L.append(f"| {_cell(h.name if h else hid)} | {_cell(TYPE_LABEL.get(h.type, h.type) if h else '')} | "
                     f"{s['total']} | {s['on']} | {s['off']} | {s['suspended']} | {s['transitional'] + s['unknown']} |")
    elif len(table) == 1:
        h = hvm.get(table[0][0])
        L.append(f"Hypervisor: {_hv_title(h)}")
    L += ["", _source_line(last_sync)]
    return "\n".join(L)


def _stale_note(stale: List[Dict[str, Any]], noun: str) -> str:
    if not stale:
        return ""
    items = ", ".join(f"{_cell(r['name'])} (son görülme {_fmt_ts(r['ts'])})" for r in sorted(stale, key=lambda r: str(r["name"]))[:6])
    more = f" +{len(stale) - 6} daha" if len(stale) > 6 else ""
    return (f"Bayat {noun} (toplama katılmadı): **{len(stale)}** — {items}{more}. "
            "Senkron kaydı bu hypervisor'ın en yeni kaydından 30 dk'dan fazla geride; "
            "adı değişmiş veya envanterden çıkmış olabilir.")


def render_fresh_count(title: str, noun: str, plan: Plan, cat: ScopeCatalog, rows: List[Dict[str, Any]],
                       last_sync: Optional[datetime], threshold_sec: int) -> str:
    hvm = _hv_map(cat)
    fresh, stale = split_fresh(rows, threshold_sec)
    per: Dict[int, int] = {}
    for r in fresh:
        per[r["hv"]] = per.get(r["hv"], 0) + 1
    L = [f"**{title}: {len(fresh)}**", "", f"Kapsam: {scope_label(plan.scope, cat, domain='virt')}"]
    if len(per) > 1:
        L += ["", f"| Hypervisor | Tür | {noun.capitalize()} |", "|---|---|---:|"]
        for hid in sorted(per):
            h = hvm.get(hid)
            L.append(f"| {_cell(h.name if h else hid)} | {_cell(TYPE_LABEL.get(h.type, h.type) if h else '')} | {per[hid]} |")
    elif len(per) == 1:
        L.append(f"Hypervisor: {_hv_title(hvm.get(next(iter(per))))}")
    note = _stale_note(stale, noun)
    if note:
        L += ["", note]
    L += ["", _source_line(last_sync, "")]
    return "\n".join(L)


def render_hypervisor(plan: Plan, cat: ScopeCatalog, last_sync: Optional[datetime]) -> str:
    hv = [h for h in cat.hypervisors if plan.scope.hv_ids is None or h.id in plan.scope.hv_ids]
    L = [f"**Toplam hypervisor: {len(hv)}**", "", f"Kapsam: {scope_label(plan.scope, cat, domain='virt')}", "",
         "| Hypervisor | Tür |", "|---|---|"]
    for h in hv:
        L.append(f"| {_cell(h.name)} | {_cell(TYPE_LABEL.get(h.type, h.type))} |")
    L += ["", _source_line(last_sync)]
    return "\n".join(L)


def render_ocp(plan: Plan, cat: ScopeCatalog, counts: Dict[int, int], noun_head: str, noun_col: str,
               last_sync: Optional[datetime]) -> str:
    names = {cid: n for cid, n in cat.ocp_clusters}
    total = sum(counts.values())
    L = [f"**{noun_head}: {total}**", "", f"Kapsam: {scope_label(plan.ocp_scope, cat, domain='ocp')}"]
    if len(counts) > 1:
        L += ["", f"| OpenShift cluster | {noun_col} |", "|---|---:|"]
        for cid in sorted(counts, key=lambda c: (-counts[c], str(names.get(c)))):
            L.append(f"| {_cell(names.get(cid, cid))} | {counts[cid]} |")
    elif len(counts) == 1:
        cid = next(iter(counts))
        L.append(f"OpenShift cluster: {names.get(cid, cid)}")
    L += ["", _source_line(last_sync)]
    return "\n".join(L)


def _ocp_stale_note(stale: List[int], names: Dict[int, str], syncs: Dict[int, Optional[datetime]],
                    counts: Dict[int, int], noun: str, threshold_sec: int) -> str:
    parts = [f"{names.get(c, c)} (son başarılı senkron {_fmt_ts(syncs.get(c))}; veritabanındaki eski kayıt {counts.get(c, 0)} {noun})"
             for c in sorted(stale, key=lambda c: str(names.get(c, c)))]
    return ("Güncel olmayan cluster (toplama katılmadı; sonuç bilinmiyor): " + "; ".join(parts)
            + f". Son senkron {threshold_sec // 60} dk'dan eski — cluster'a ulaşılamıyor olabilir.")


def split_ocp_fresh(db, counts: Dict[int, int]) -> Tuple[Dict[int, int], List[int], Dict[int, Optional[datetime]], int]:
    """Cluster başına sayımları bayatlık eşiğine göre ayır (pod sayımıyla AYNI eşik: 3 × senkron aralığı)."""
    from app.services.chat_quality import count_extra as cx
    thr = cx.ocp_stale_threshold_sec()
    syncs = cx.fetch_cluster_syncs(db)
    fresh, stale = cx.split_clusters(syncs, list(counts), cx._now(), thr)
    return {c: counts[c] for c in fresh}, stale, syncs, thr


def render_ocp_nodes(plan: Plan, cat: ScopeCatalog, counts: Dict[int, int], noun_head: str, noun_col: str,
                     last_sync: Optional[datetime], fresh: Dict[int, int], stale: List[int],
                     syncs: Dict[int, Optional[datetime]], thr: int) -> str:
    """Node sayımı: bayat cluster toplama KATILMAZ, ayrı satırda «sonuç bilinmiyor» (pod sayımıyla aynı kural)."""
    if not stale:
        return render_ocp(plan, cat, counts, noun_head, noun_col, last_sync)
    names = {cid: n for cid, n in cat.ocp_clusters}
    label = scope_label(plan.ocp_scope, cat, domain='ocp')
    if not fresh:
        L = [f"**{noun_head}: güncel sayı bilinmiyor**", "", f"Kapsam: {label}"]
    else:
        L = [f"**{noun_head}: {sum(fresh.values())}**", "", f"Kapsam: {label}"]
        if len(fresh) > 1:
            L += ["", f"| OpenShift cluster | {noun_col} |", "|---|---:|"]
            for cid in sorted(fresh, key=lambda c: (-fresh[c], str(names.get(c)))):
                L.append(f"| {_cell(names.get(cid, cid))} | {fresh[cid]} |")
        else:
            L.append(f"OpenShift cluster: {names.get(next(iter(fresh)), next(iter(fresh)))}")
    L += ["", _ocp_stale_note(stale, names, syncs, counts, "node", thr), "", _source_line(last_sync)]
    return "\n".join(L)


def render_ocp_clusters(plan: Plan, cat: ScopeCatalog, last_sync: Optional[datetime]) -> str:
    cl = [(cid, n) for cid, n in cat.ocp_clusters if plan.ocp_scope.ocp_ids is None or cid in plan.ocp_scope.ocp_ids]
    L = [f"**OpenShift cluster sayısı: {len(cl)}**", "", f"Kapsam: {scope_label(plan.ocp_scope, cat, domain='ocp')}", ""]
    L += ["| OpenShift cluster |", "|---|"] + [f"| {_cell(n)} |" for _, n in cl]
    L += ["", _source_line(last_sync)]
    return "\n".join(L)


def render_compare(plan: Plan, groups: List[Tuple[str, int]], noun_head: str, by_label: str,
                   last_sync: Optional[datetime]) -> str:
    if not groups:
        return ""
    groups = sorted(groups, key=lambda g: (-g[1], g[0]))
    top_n = groups[0][1]
    leaders = [g[0] for g in groups if g[1] == top_n]
    if len(leaders) == 1:
        head = f"**En çok {noun_head}: {leaders[0]} — {top_n}**"
    else:
        head = f"**En çok {noun_head} (eşit): {', '.join(leaders)} — {top_n}**"
    col = noun_head if noun_head.isupper() else noun_head.capitalize()
    L = [head, "", f"| {by_label} | {col} |", "|---|---:|"]
    for n, c in groups[:15]:
        L.append(f"| {_cell(n)} | {c} |")
    if len(groups) > 15:
        L.append(f"| … (+{len(groups) - 15} satır) | |")
    L += ["", _source_line(last_sync)]
    return "\n".join(L)


def render_location(plan: Plan, cat: ScopeCatalog, recs: List[Dict[str, Any]], last_sync: Optional[datetime]) -> str:
    hvm = _hv_map(cat)
    if len(recs) == 1:
        r = recs[0]
        h = hvm.get(r["hv"])
        cls = ps.label_tr(ps.classify(r.get("power")))
        L = [f"**{_cell(r['name'])}** şu hypervisor üzerinde: **{_hv_title(h)}**", "",
             f"- Host: {_cell(r.get('host'))}", f"- Cluster: {_cell(r.get('cluster'))}",
             f"- Güç durumu: {_cell(ps.pstate_label(r.get('power')))} ({cls})", f"- IP: {_cell(r.get('ip'))}"]
    else:
        L = [f"**{_cell(recs[0]['name'])}** adıyla **{len(recs)} kayıt** var (hepsi aşağıda; hangisini kastettiğinizi belirtebilirsiniz):", "",
             "| Hypervisor | Tür | Host | Cluster | Güç durumu | IP |", "|---|---|---|---|---|---|"]
        for r in recs:
            h = hvm.get(r["hv"])
            L.append(f"| {_cell(h.name if h else r['hv'])} | {_cell(TYPE_LABEL.get(h.type, h.type) if h else '')} | "
                     f"{_cell(r.get('host'))} | {_cell(r.get('cluster'))} | {_cell(ps.pstate_label(r.get('power')))} | {_cell(r.get('ip'))} |")
    L += ["", _source_line(last_sync)]
    return "\n".join(L)


# ── uçtan uca ───────────────────────────────────────────────────────────────────────

def _enabled() -> bool:
    try:
        from app.services import runtime_settings
        return bool(runtime_settings.get_bool("chat_count_rules_enabled"))
    except Exception:
        return True


def answer(plan: Plan, cat: ScopeCatalog, db) -> Optional[str]:
    """Plan → cevap metni (veya None). Salt-okunur SQL; hata çağırana gider."""
    thr = stale_threshold_sec()
    if plan.kind == "location":
        recs = fetch_locations(db, plan.candidates)
        if plan.scope.hv_ids is not None:
            recs = [r for r in recs if r["hv"] in plan.scope.hv_ids]
        if not recs:
            return None
        return render_location(plan, cat, recs, fetch_last_sync(db, sorted({r["hv"] for r in recs})))
    if plan.kind == "compare":
        if plan.topic == "vm":
            groups = fetch_vm_group_counts(db, plan.by)
            return render_compare(plan, groups, "VM", "Cluster" if plan.by == "cluster" else "Hypervisor",
                                  fetch_last_sync(db, None))
        table = "openshift_nodes" if plan.topic == "node" else "openshift_projects"
        counts = fetch_ocp_counts(db, table, Scope(), cat)
        names = {cid: n for cid, n in cat.ocp_clusters}
        stale_note = ""
        if plan.topic == "node":
            fresh_c, stale_c, syncs_c, thr_c = split_ocp_fresh(db, counts)
            if stale_c:
                stale_note = _ocp_stale_note(stale_c, names, syncs_c, counts, "node", thr_c)
                counts = fresh_c
        txt = render_compare(plan, [(names.get(c, str(c)), n) for c, n in counts.items()],
                             "node" if plan.topic == "node" else "proje (namespace)", "OpenShift cluster",
                             fetch_ocp_last_sync(db, None))
        if stale_note and txt:
            txt = txt.replace("\n\n_Kaynak", "\n\n" + stale_note + "\n\n_Kaynak", 1) if "\n\n_Kaynak" in txt else txt + "\n\n" + stale_note
        return txt
    if plan.topic == "pod":
        from app.services.chat_quality import count_extra as cx
        ids = plan.ocp_scope.ocp_ids
        return cx.render_pods(plan, cat, cx.fetch_pod_groups(db, ids), cx.fetch_cluster_syncs(db), cx._now(),
                              cx.ocp_stale_threshold_sec())
    if plan.topic == "server":
        from app.services.chat_quality import count_extra as cx
        return cx.render_servers(plan, cx.fetch_server_counts(db, plan.os_kinds), fetch_last_sync(db, None))
    # count
    out: List[str] = []
    if plan.domain in ("virt", "both"):
        ls = fetch_last_sync(db, _ids(plan.scope))
        if plan.topic == "vm":
            out.append(render_vm(plan, cat, fetch_vm_counts(db, plan.scope), ls))
        elif plan.topic == "host":
            out.append(render_fresh_count("Toplam host", "host", plan, cat, fetch_hosts(db, plan.scope), ls, thr))
        elif plan.topic == "datastore":
            out.append(render_fresh_count("Toplam datastore", "datastore", plan, cat, fetch_datastores(db, plan.scope), ls, thr))
        elif plan.topic == "cluster":
            out.append(render_fresh_count("Sanallaştırma cluster sayısı", "cluster", plan, cat, fetch_clusters(db, plan.scope), ls, thr))
        elif plan.topic == "hypervisor":
            out.append(render_hypervisor(plan, cat, ls))
    if plan.domain in ("ocp", "both"):
        ls = fetch_ocp_last_sync(db, plan.ocp_scope.ocp_ids)
        if plan.topic == "node":
            _nc = fetch_ocp_counts(db, "openshift_nodes", plan.ocp_scope, cat)
            _fr, _st, _sy, _th = split_ocp_fresh(db, _nc)
            out.append(render_ocp_nodes(plan, cat, _nc, "Toplam node", "Node", ls, _fr, _st, _sy, _th))
        elif plan.topic == "project":
            out.append(render_ocp(plan, cat, fetch_ocp_counts(db, "openshift_projects", plan.ocp_scope, cat),
                                  "Toplam proje (namespace)", "Proje", ls))
        elif plan.topic == "cluster":
            out.append(render_ocp_clusters(plan, cat, ls))
    out = [o for o in out if o]
    if not out:
        return None
    return "\n\n---\n\n".join(out)


def count_response(message: str, *, platform: Optional[str] = None, allowed_modules: Any = None,
                   session_id: Optional[int] = None) -> Optional[str]:
    """`canned_chitchat_answer` içinden çağrılır: şablon cevap veya None (normal akış). Hata → None.

    Cevaplanınca çözülen soru(lar) `count_followup.set_context` ile bırakılır (uç nokta `meta.count_context`).
    """
    from app.services.chat_quality import count_followup as cf
    cf.set_context(None)
    prefix = ""
    try:
        if not _enabled():
            return None
        cat = get_catalog()
        if cat is None:
            return None
        from app.services.chat_quality import premise
        pr = premise.respond(message, platform=platform, allowed_modules=allowed_modules)
        if pr is not None:
            ptext, pplan, peff, ptrace = pr
            cf.set_context(cf.context_for([peff], [pplan]))
            try:
                from app.services.chat_quality import trace as cq_trace
                cq_trace.note_path(
                    "qa_rule", handler=f"count_rules.premise.{ptrace['form']}", rule="count_rules",
                    topic=ptrace.get("topic"), premise=ptrace, platform=platform or "",
                )
            except Exception:
                pass
            logger.info("[CountRules] premise form=%s topic=%s platform=%s", ptrace["form"], ptrace.get("topic"), platform)
            return ptext
        from app.services.chat_quality import compound
        parts = compound.split_parts(message)
        if len(parts) > 1:
            return _compound_response(parts, cat, platform=platform, allowed_modules=allowed_modules)
        plan = analyze(message, cat, platform=platform, allowed_modules=allowed_modules)
        eff = message
        from app.core.database import ThreadSessionLocal
        if plan is None:
            ts = _time_scoped(message, cat, platform=platform, allowed_modules=allowed_modules)
            if ts is not None:
                return _time_scoped_response(*ts, cat)
            if not (session_id and cf.is_followup_shape(message)):
                return None
            db = ThreadSessionLocal()
            try:
                ctx = cf.load_recent(db, session_id)
            finally:
                db.close()
            r = cf.resolve(message, ctx, lambda q: analyze(q, cat, platform=platform, allowed_modules=allowed_modules))
            if r is None:
                return None
            if r[0] == "clarify":
                try:
                    from app.services.chat_quality import trace as cq_trace
                    cq_trace.note_path("qa_rule", handler="count_rules.followup.clarify", rule="count_rules")
                except Exception:
                    pass
                return r[1]
            eff = r[1]
            plan = analyze(eff, cat, platform=platform, allowed_modules=allowed_modules)
            if plan is None:
                return None
            prefix = f"_Önceki soruya göre yorumlandı: «{eff}»_\n\n"
        db = ThreadSessionLocal()
        try:
            text = answer(plan, cat, db)
        finally:
            db.close()
    except Exception:
        logger.warning("[CountRules] kural hatası (normal akışa dönülüyor)", exc_info=True)
        return None
    if not text:
        return None
    cf.set_context(cf.context_for([eff], [plan]))
    text = prefix + text
    try:
        from app.services.chat_quality import trace as cq_trace
        cq_trace.note_path(
            "qa_rule", handler=f"count_rules.{plan.kind}.{plan.topic}", rule="count_rules", topic=plan.topic,
            followup=bool(prefix),
            state=plan.pod_filter or plan.state, domain=plan.domain,
            scope=(plan.scope.kind if plan.domain != "ocp" else plan.ocp_scope.kind), platform=platform or "",
        )
    except Exception:
        pass
    logger.info("[CountRules] %s/%s state=%s domain=%s platform=%s", plan.kind, plan.topic, plan.state, plan.domain, platform)
    return text


def _compound_response(parts: List[str], cat: ScopeCatalog, *, platform: Optional[str], allowed_modules: Any) -> Optional[str]:
    """Bileşik soru: parça başına sayım kuralı; desteklenmeyen parça açık not. Hiç parça yoksa None."""
    from app.services.chat_quality import compound
    from app.core.database import ThreadSessionLocal

    from app.services.chat_quality import count_followup as cf
    sections: List[Tuple[str, Optional[str], Optional[Plan]]] = []
    effs: List[str] = []
    prev: Optional[str] = None
    db = ThreadSessionLocal()
    try:
        for part in parts:
            eff = compound.resolve_pronoun(part, prev) or part
            plan = analyze(eff, cat, platform=platform, allowed_modules=allowed_modules)
            text = answer(plan, cat, db) if plan is not None else None
            sections.append((part, text, plan))
            effs.append(eff)
            prev = eff
    finally:
        db.close()
    if not any(t for _, t, _ in sections):
        return None
    answered = [(e, pl) for e, (_, t, pl) in zip(effs, sections) if t and pl is not None]
    cf.set_context(cf.context_for([e for e, _ in answered], [pl for _, pl in answered]))
    L = [f"Sorunuz **{len(parts)} parçaya** ayrıldı; her parça ayrı hesaplandı."]
    for i, (part, text, _) in enumerate(sections, 1):
        L += ["", f"### {i}) {part}", ""]
        L.append(text if text else (
            "Bu kısım sayım kuralıyla yanıtlanamadı (desteklenmeyen konu/ifade ya da yetki dışı). "
            f"Ayrı bir soru olarak sorabilirsiniz: «{part}»"))
    try:
        from app.services.chat_quality import trace as cq_trace
        cq_trace.note_path(
            "qa_rule", handler="count_rules.compound", rule="count_rules", topic="compound",
            parts=[{"q": p, "topic": (pl.topic if pl else None), "answered": bool(t)} for p, t, pl in sections],
            platform=platform or "",
        )
    except Exception:
        pass
    logger.info("[CountRules] compound parts=%d answered=%d platform=%s", len(parts),
                sum(1 for _, t, _ in sections if t), platform)
    return "\n".join(L)


# ── zaman ifadeli sayım (Adım 6b-3) ─────────────────────────────────────────────────

_TENSE_RE = re.compile(r"\b(?:vardi|varmis|varmiydi|olacak|olacakti|olur|bulunuyordu|mevcuttu|kayitliydi)\b")
_TIME_FILLER_RE = re.compile(
    r"\b(?:ayinda|ayi|yilinda|yili|tarihinde|itibariyle|itibariyla|doneminde|gunu|haftasi|haftasinda|"
    r"tarihi|tarihli|in|on|at|during)\b"
)


def _time_scoped(message: str, cat: ScopeCatalog, *, platform: Optional[str], allowed_modules: Any):
    """Zaman ifadesi ayıklanınca sayım kuralına uyan soru → (pencere, plan, temiz soru) veya None."""
    from app.services.chat_quality import time_window as tw
    w = tw.resolve_for_chat(message)
    if w is None or not w.expr:
        return None
    mf = fold(message)
    e = fold(w.expr)
    if e not in mf:
        return None
    rest = mf.replace(e, " ")
    rest = _TENSE_RE.sub("var", rest)
    rest = _TIME_FILLER_RE.sub(" ", rest)
    rest = re.sub(r"\s+", " ", rest).strip()
    plan = analyze(rest, cat, platform=platform, allowed_modules=allowed_modules)
    if plan is None or plan.kind != "count":
        return None
    return w, plan, rest


def _time_scoped_response(w, plan: Plan, rest: str, cat: ScopeCatalog) -> Optional[str]:
    from app.services.chat_quality import clock
    from app.services.chat_quality import count_followup as cf
    from app.core.database import ThreadSessionLocal

    now = clock.now_aware(w.tz_name)
    if w.start > now:
        mode = "future"
        head = (f"**Bu dönem için veri yok — {w.title}: henüz yaşanmadı.** "
                "Gelecekteki bir tarih için envanter sayısı olamaz.")
    elif w.start <= now <= w.end:
        mode = "current"
        head = f"_Zaman ifadesi («{w.expr}») şu anı kapsıyor; aşağıdaki sayı güncel envanterdir._"
    else:
        mode = "past"
        head = (f"**Bu dönem için veri yok — {w.title}.** Geçmişe dönük envanter sayımı (tarihsel anlık görüntü) "
                "tutulmuyor; o tarihteki sayıyı veremem.")
    db = ThreadSessionLocal()
    try:
        body = answer(plan, cat, db)
    finally:
        db.close()
    if not body:
        return None
    if mode != "current":
        body = "Karşılaştırma için **güncel** değer (geçmiş/gelecek değil):\n\n" + body
    cf.set_context(cf.context_for([rest], [plan]))
    try:
        from app.services.chat_quality import trace as cq_trace
        cq_trace.note_path("qa_rule", handler=f"count_rules.time.{mode}.{plan.topic}", rule="count_rules",
                           topic=plan.topic, window=w.label)
    except Exception:
        pass
    logger.info("[CountRules] time-scoped %s/%s mode=%s", plan.kind, plan.topic, mode)
    return head + "\n\n" + body
