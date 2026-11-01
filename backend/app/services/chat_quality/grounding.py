"""Veriye dayalılık doğrulayıcısı (Adım 7b) — cevap BİTTİKTEN sonra, akışı geciktirmeden.

Girdi: nihai cevap, kullanıcı mesajı, (kısa) sohbet geçmişi, bu turun araç sonuçları (`TurnTrace.tools`).
Çıktı: sınıf başına bulgular (`findings`) — gölge modda yalnız iz/log; `enforce` modda yalnız eşiği geçen
sınıflar için cevabın SONUNA dürüst uyarı eklenir (cevap yutulmaz, yeniden yazılmaz).

Sınıflar:
  ungrounded_number   cevaptaki anlamlı sayı araç sonuçlarında / kullanıcı mesajında / basit türevde yok
  ungrounded_entity   cevaptaki ad (kod/kalın/tablo ilk sütunu/FQDN) araç sonuçlarında ve mesajda yok
  ungrounded_command  cevaptaki komutun ikilisi bağlamda yok ve genel salt-okunur tanı listesinde değil
  internal_term       araç adı / araç sonucu anahtarı (snake_case) / «veri bloku» gibi iç terim sızıntısı
  source_label        «(kaynak: db_list_vms)», «vcenter_ask (AI)» gibi kullanıcıya anlamsız kaynak etiketi
  premise_accepted    kullanıcının yanlış sayısı olumsuzlanmadan cevapta tekrar edilmiş

Tasarım ilkeleri: kesinlik > yakalama (şüphede bulgu verme); araç kanıtı yoksa sayı/ad/komut sınıfları
KOŞMAZ (kanıt bilinmiyor ≠ uydurma); kural/şablon yolu cevapları (`qa_rule`, `entity_gate`, `action_gate`)
kodla üretildiği için atlanır. Kendi başına cevap DEĞİŞTİRMEZ; `notice_for` çağıran karar verir.
"""
from __future__ import annotations

import json
import logging
import re
import time
from bisect import bisect_left
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.services.chat_quality.claims import fold

logger = logging.getLogger(__name__)

CLASSES = (
    "ungrounded_number", "ungrounded_entity", "ungrounded_command",
    "internal_term", "source_label", "premise_accepted",
)
SKIP_PATH_KINDS = {"qa_rule", "entity_gate", "action_gate"}
SKIP_PLATFORMS = {"automic", "automation"}          # Automic sohbeti kapsam dışı (kendi doğrulama hattı var)

MAX_FINDINGS = 12
MAX_WALK_NODES = 200_000
MAX_EVIDENCE_NUMBERS = 4000
MAX_EVIDENCE_CHARS = 3_000_000
PAIR_RATIO_MAX = 150

# ── ayarlar ──────────────────────────────────────────────────────────────────────

def mode() -> str:
    try:
        from app.services import runtime_settings
        v = (runtime_settings.get_str("chat_grounding_mode") or "shadow").strip().lower()
    except Exception:
        v = "shadow"
    return v if v in ("off", "shadow", "enforce") else "shadow"


def enforce_classes() -> Set[str]:
    try:
        from app.services import runtime_settings
        raw = runtime_settings.get_str("chat_grounding_enforce_classes") or ""
    except Exception:
        raw = ""
    return {c.strip() for c in raw.split(",") if c.strip() in CLASSES}


# ── kanıt ────────────────────────────────────────────────────────────────────────

_NUM_TOKEN = re.compile(
    r"\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?(?!\d)"
    r"|\d{1,3}(?:\.\d{3})+(?:,\d+)?(?!\d)"
    r"|\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)"
    r"|\d+(?:[.,]\d+)?"
)
_GLUED = re.compile(r"(?<=[A-Za-z_\-/#@])\d+(?:[.,]\d+)*")
_TRIVIAL = set(range(0, 11)) | {12, 24, 30, 60, 100, 1000, 1024}
_DATE_RE = re.compile(
    r"\b\d{4}[-/.]\d{1,2}[-/.]\d{1,2}(?:[ t]\d{1,2}:\d{2}(?::\d{2})?(?:\.\d+)?(?:z|[+-]\d{2}:?\d{2})?)?\b"
    r"|\b\d{1,2}[./]\d{1,2}[./]\d{2,4}\b|\b\d{1,2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:z\b|[+-]\d{2}:?\d{2}\b)?"
)
_VERSION_RE = re.compile(r"\b\d+(?:\.\d+){2,}\b")
_CODE_BLOCK = re.compile(r"```.*?```", re.S)
_INLINE_CODE = re.compile(r"`([^`\n]+)`")


_P_SPACED = re.compile(r"\d{1,3}(?: \d{3})+")
_P_ZERO = re.compile(r"0[.,]\d+")
_P_DOT3 = re.compile(r"\d{1,3}(?:\.\d{3})+")
_P_COMMA3 = re.compile(r"\d{1,3}(?:,\d{3})+")
_P_COMMA_DEC = re.compile(r"\d+,\d+")
_P_PLAIN = re.compile(r"\d+(?:\.\d+)?")
_HAS_DIGIT = re.compile(r"\d")


def parse_number(tok: str) -> Optional[float]:
    if tok.isascii() and tok.isdigit():
        return float(tok)                               # hızlı yol: düz tamsayı
    t = tok.strip().replace("\u00a0", " ").replace("\u202f", " ")
    if _P_SPACED.fullmatch(t):
        return float(t.replace(" ", ""))
    t = t.replace(" ", "")
    if not t:
        return None
    if _P_ZERO.fullmatch(t):
        return float(t.replace(",", "."))
    if _P_DOT3.fullmatch(t) or _P_COMMA3.fullmatch(t):
        return float(t.replace(".", "").replace(",", ""))
    if _P_COMMA_DEC.fullmatch(t):
        return float(t.replace(",", "."))
    if _P_PLAIN.fullmatch(t):
        return float(t)
    return None


def _numbers_in_text(s: str) -> List[float]:
    out: List[float] = []
    if not s or not _HAS_DIGIT.search(s):
        return out
    for m in _NUM_TOKEN.finditer(s or ""):
        v = parse_number(m.group(0))
        if v is not None:
            out.append(v)
    return out


def _walk(obj: Any, nums: Set[float], keys: Set[str], texts: List[str], budget: List[int]) -> None:
    if budget[0] <= 0:
        return
    budget[0] -= 1
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        nums.add(float(obj))
        return
    if isinstance(obj, str):
        if budget[1] > 0:
            texts.append(obj)
            budget[1] -= len(obj) + 1
        for v in _numbers_in_text(obj[:20000]):
            nums.add(v)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(k, str):
                if k not in keys:
                    keys.add(k)
                    if budget[1] > 0:
                        texts.append(k)
                        budget[1] -= len(k) + 1
            _walk(v, nums, keys, texts, budget)
        return
    if isinstance(obj, (list, tuple)):
        nums.add(float(len(obj)))
        for v in obj:
            _walk(v, nums, keys, texts, budget)
        return


def _fast_fold(s: str) -> str:
    """ASCII parçada yalnız lower(); diğerlerinde tam `fold` (yüzlerce bin kısa parçada maliyet düşer)."""
    return s.lower() if s.isascii() else fold(s)


class Evidence:
    def __init__(self, user_message: str, history_text: str, tools: Sequence[Tuple[str, Any, Any]]):
        self.tool_names = [t[0] for t in tools]
        self.has_tools = any(t[2] is not None for t in tools)
        nums: Set[float] = set()
        keys: Set[str] = set()
        texts: List[str] = []
        budget = [MAX_WALK_NODES, MAX_EVIDENCE_CHARS]
        for _, args, result in tools:
            _walk(args, nums, keys, texts, budget)
            _walk(result, nums, keys, texts, budget)
        for v in _numbers_in_text(user_message or ""):
            nums.add(v)
        for v in _numbers_in_text(history_text or ""):
            nums.add(v)
        self.keys = keys
        self.user_message = user_message or ""
        self.tool_text = " \n ".join(_fast_fold(t) for t in texts)[:3_000_000]
        self.text = (self.tool_text + " \n " + fold(user_message or "") + " \n " + fold(history_text or ""))[:3_000_000]
        self.capped = len(nums) > MAX_EVIDENCE_NUMBERS
        nums_list = sorted(nums)[:MAX_EVIDENCE_NUMBERS] if self.capped else sorted(nums)
        self.nums = nums_list
        self._derived = self._derive(nums_list)
        self._all = sorted(set(nums_list) | self._derived)
        self._keys2 = {round(v, 2) for v in nums_list}

    @staticmethod
    def _derive(nums: List[float]) -> Set[float]:
        d: Set[float] = set()
        for e in nums:
            for f in (1024.0, 1024.0 ** 2, 1024.0 ** 3, 1000.0, 1e6, 1e9, 60.0, 3600.0, 86400.0):
                d.add(e / f)                    # bayt→GB, sn→dk/sa/gün; yukarı çarpma türevi YOK (yuvarlak sayıları meşrulaştırır)
            if 0 <= e <= 1.0:
                d.add(e * 100.0)
        return d

    @staticmethod
    def _close(x: float, e: float) -> bool:
        if x == e:
            return True
        if abs(x - e) <= 0.51 and float(x).is_integer():
            return True                         # yuvarlama
        if abs(x - e) <= 0.051:
            return True
        return abs(x - e) <= 0.005 * max(abs(x), abs(e))

    def _near(self, arr: List[float], x: float) -> bool:
        i = bisect_left(arr, x)
        for j in (i - 1, i, i + 1):
            if 0 <= j < len(arr) and self._close(x, arr[j]):
                return True
        return False

    def grounded(self, x: float, pct: bool = False) -> bool:
        if self._near(self._all, x):
            return True
        for e in self.nums:                     # toplam / fark
            if round(abs(x - e), 2) in self._keys2 or round(x + e, 2) in self._keys2:
                return True
        if pct and len(self.nums) <= PAIR_RATIO_MAX:    # yüzde: yalnız cevapta «%»/«yüzde»/«oran» ile yazılan sayı
            for a in self.nums:
                for b in self.nums:
                    if b and self._close(x, 100.0 * a / b):
                        return True
        return False


# ── cevap ayrıştırma ─────────────────────────────────────────────────────────────

def _strip_code(s: str) -> str:
    s = _CODE_BLOCK.sub(" ", s or "")
    return _INLINE_CODE.sub(" ", s)


def answer_numbers(answer: str) -> List[Tuple[float, str]]:
    """Anlamlı (önemsiz olmayan) sayılar: (değer, bağlam)."""
    s = _strip_code(answer).replace("\u2011", "-").replace("\u2010", "-").replace("\u2013", "-")
    s = _DATE_RE.sub(" ", s)
    s = _VERSION_RE.sub(" ", s)
    s = re.sub(r"\b\d{1,3}(?:\.\d{1,3}){3}\b", " ", s)                 # IP
    s = re.sub(r"(?m)^\s*(?:#+\s*)?\d+[.)]\s", " ", s)                  # liste/başlık numarası
    s = _GLUED.sub(" ", s)                                              # «vm1000», «-01», «node_3», «/dev/sda1»
    out: List[Tuple[float, str]] = []
    for m in _NUM_TOKEN.finditer(s):
        a, b = m.start(), m.end()
        v = parse_number(m.group(0))
        if v is None:
            continue
        if float(v).is_integer() and int(v) in _TRIVIAL:
            continue
        if 1900 <= v <= 2100 and float(v).is_integer():
            continue
        out.append((v, s[max(0, a - 30): b + 20].replace("\n", " ")))
    return out


_ENTITY_STOP = {"toplam", "total", "-", "—", "–", "ad", "adı", "isim", "name", "durum", "status", "kapsam"}
_HOSTLIKE = re.compile(r"(?<![\w./@-])([a-z0-9][a-z0-9_]*(?:[.\-][a-z0-9_]+){2,})(?![\w@-])", re.I)
_BOLD = re.compile(r"\*\*([^*\n]{2,60})\*\*")
_NAMEY = re.compile(r"^[\w.\-:/@]+$")


def answer_entities(answer: str) -> List[str]:
    cands: List[str] = []
    for m in _INLINE_CODE.finditer(answer or ""):
        t = m.group(1).strip()
        if _NAMEY.match(t) and re.search(r"[\d\-._]", t) and not t.startswith(("/", "-", ".", "$")):
            cands.append(t)
    body = _CODE_BLOCK.sub(" ", answer or "")
    for m in _BOLD.finditer(body):
        t = m.group(1).strip().rstrip(":")
        if _NAMEY.match(t) and re.search(r"[\d\-._]", t) and not re.fullmatch(r"[\d.,%\s]+", t):
            cands.append(t)
    lines = body.split("\n")
    in_table = False
    for i, ln in enumerate(lines):
        if re.match(r"^\s*\|.*\|\s*$", ln):
            nxt = lines[i + 1] if i + 1 < len(lines) else ""
            if re.match(r"^\s*\|?\s*:?-{2,}", nxt):          # başlık satırı
                in_table = True
                continue
            if re.match(r"^\s*\|?\s*:?-{2,}", ln):
                continue
            if in_table:
                cells = [c.strip() for c in ln.strip().strip("|").split("|")]
                if cells:
                    c0 = re.sub(r"[*_`]", "", cells[0]).strip()
                    if c0 and _NAMEY.match(c0) and re.search(r"[\d\-._]", c0) and not re.fullmatch(r"[\d.,%\s:\-]+", c0):
                        cands.append(c0)
        else:
            in_table = False
    for m in _HOSTLIKE.finditer(_DATE_RE.sub(" ", _strip_code(body))):
        t = m.group(1)
        if re.search(r"[a-z]", t, re.I) and not _VERSION_RE.fullmatch(t) and not re.fullmatch(r"\d[\d.\-]*", t):
            cands.append(t)
    out: List[str] = []
    seen: Set[str] = set()
    for c in cands:
        k = fold(c).strip(" .,:;()[]")
        if len(k) < 4 or k in _ENTITY_STOP or k in seen:
            continue
        if re.fullmatch(r"[\d.,%\s:\-]+", k) or "://" in k or k.startswith(("/", "http", "www.")):
            continue
        if re.search(r"\d{4}-\d{2}-\d{2}", k) or k.endswith((".md", ".json", ".yaml", ".yml", ".py", ".log", ".txt", ".csv")):
            continue
        seen.add(k)
        out.append(c)
    return out[:40]


_SAFE_BINS = {
    "ls", "cat", "df", "du", "free", "top", "htop", "ps", "uptime", "ss", "ip", "ping", "dmesg", "uname",
    "whoami", "hostname", "hostnamectl", "grep", "egrep", "head", "tail", "lsblk", "mount", "findmnt",
    "vmstat", "iostat", "mpstat", "sar", "netstat", "lscpu", "lsmem", "lsof", "id", "date", "w", "who",
    "last", "env", "echo", "pwd", "wc", "sort", "uniq", "awk", "cut", "tr", "less", "more", "stat", "file",
    "nproc", "ulimit", "traceroute", "nslookup", "dig", "curl", "wget", "journalctl", "timedatectl",
    "get-process", "get-service", "get-eventlog", "get-counter", "get-wmiobject", "get-ciminstance",
    "get-disk", "get-volume", "systemctl", "kubectl", "oc", "ethtool", "lspci", "lsmod", "blkid", "pvs", "vgs",
    "lvs", "pvdisplay", "vgdisplay", "lvdisplay", "multipath", "chronyc", "ntpq", "sysctl", "rpm", "dnf", "yum",
}
_CMD_START = re.compile(r"^\s*(?:\$\s*|#\s*|PS>\s*)?(?:sudo\s+)?([A-Za-z][\w.\-]*)(?:\s|$)")


def answer_commands(answer: str) -> List[str]:
    lines: List[str] = []
    for blk in _CODE_BLOCK.findall(answer or ""):
        for ln in blk.strip("`").split("\n")[1:]:
            if ln.strip():
                lines.append(ln.strip())
    for m in _INLINE_CODE.finditer(_CODE_BLOCK.sub(" ", answer or "")):
        t = m.group(1).strip()
        if " " in t:
            lines.append(t)
    out: List[str] = []
    for ln in lines:
        m = _CMD_START.match(ln)
        if not m:
            continue
        b = m.group(1)
        if b.lower() in _SAFE_BINS:
            continue
        if "/" in b and not b.startswith(("./", "/")):
            continue
        if not re.search(r"[a-z]", b, re.I) or len(b) < 3:
            continue
        if not re.match(r"^[a-z][a-z0-9_.\-]*$", b, re.I):
            continue
        out.append(ln)
    return out[:20]


_SOURCE_RE = re.compile(r"\(?\bkaynak:\s*([a-z][a-z0-9]*(?:_[a-z0-9]+)+)\s*(?:\((?:AI|LLM)\))?\)?|\b[a-z]+_[a-z]+\s*\((?:AI|LLM)\)", re.I)
_PHRASE_RE = re.compile(r"\b(?:veri\s+blo(?:k|ku|ğu)\w*|tool\s+result\w*|structured[_ ]results?|debug_trace|llm_view|NOT_QUERIED|SUCCESS_EMPTY)\b", re.I)
_SNAKE_RE = re.compile(r"(?<![\w/.\-])([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?![\w/\-])")


# Bağlam bloğundan (araç çıktısı olmadan) gelen, kullanıcıya anlamsız alan adları — iz'de yok ama sızıntıdır.
_CONTEXT_FIELDS = {
    "problem_pod_count", "problem_pods_sample", "pods_by_status", "pod_count", "node_count", "project_count",
    "by_status", "by_reason", "by_namespace", "by_object", "failed_count", "total_count_in_window",
    "question_hint", "as_of", "live_connection_failed", "problem_count", "count_context",
    "error_state_count", "error_state_breakdown", "error_state_definition",
}


# Envanter sözleşmesi (`virt_inventory_contract`) biçimi BİLEREK «(kaynak: db_…)» başlığı ve «as_of: `…`» satırı üretir;
# bu ürün biçimi kod tarafından sabittir — doğrulayıcı sızıntı saymaz (etiketin sözleşmeden kaldırılması ürün kararı).
_CONTRACT_HEAD = re.compile(
    r"(?m)^##\s+(?:VM Listesi|VM Disk Kırılımı|VM Disk Envanteri|Datastore Envanteri|ESXi Host Envanteri)\s+\(kaynak: db_[a-z_]+\)\s*$")
_CONTRACT_ASOF = re.compile(r"(?m)^as_of: `[^`\n]*`\s*$")


def _tool_names() -> Set[str]:
    try:
        from app.services.agent.tools import TOOLS
        return set(TOOLS.keys())
    except Exception:
        return set()


# ── ana giriş ────────────────────────────────────────────────────────────────────

_NEGATION = re.compile(r"\b(?:degil|yanlis|aslinda|hayir|olmayan|oysa|ancak|fakat|not|actually|however|only|yalniz|sadece)\b")


def _premise_claims(user_message: str) -> List[int]:
    from app.services.chat_quality import premise
    mf = premise._norm(user_message)
    p = premise._parse(mf)
    out: List[int] = []
    if p and p.get("n") is not None:
        out.append(int(p["n"]))
    for m in re.finditer(r"(?<![\w.\-])(\d{2,7})\s+(?:vm|host|node|pod|cluster|sunucu|server|datastore|makine)\w*\s+(?:var|bulunuyor|mevcut)\b", mf):
        out.append(int(m.group(1)))
    return sorted(set(out))


def verify(answer: str, *, user_message: str = "", history_text: str = "",
           tools: Sequence[Tuple[str, Any, Any]] = (), paths: Sequence[Dict[str, Any]] = (),
           platform: str = "") -> Dict[str, Any]:
    t0 = time.perf_counter()
    res: Dict[str, Any] = {"findings": [], "counts": {}, "skipped": None, "ms": 0.0}
    try:
        if not (answer or "").strip():
            res["skipped"] = "empty"
            return res
        if (platform or "").strip().lower() in SKIP_PLATFORMS:
            res["skipped"] = "platform"
            return res
        if any(isinstance(p, dict) and p.get("kind") in SKIP_PATH_KINDS for p in paths):
            res["skipped"] = "rule_path"
            return res
        ev = Evidence(user_message, history_text, tools)
        f: List[Dict[str, Any]] = []

        def add(cls: str, text: str, detail: str = "") -> None:
            res["counts"][cls] = res["counts"].get(cls, 0) + 1
            if len(f) < MAX_FINDINGS:
                f.append({"class": cls, "text": text[:120], "detail": detail[:160]})

        if ev.has_tools:
            for v, ctx in answer_numbers(answer):
                if not ev.grounded(v, pct=bool(re.search(r"%|yüzde|yuzde|oran|percent", ctx, re.I))):
                    add("ungrounded_number", f"{v:g}", ctx)
            for e in answer_entities(answer):
                k = fold(e).strip(" .,:;()[]")
                if k not in ev.text:
                    add("ungrounded_entity", e)
            for ln in answer_commands(answer):
                m = _CMD_START.match(ln)
                b = (m.group(1) if m else "").lower()
                if b and b not in ev.text and fold(ln) not in ev.text:
                    add("ungrounded_command", ln, b)
        else:
            res["no_tool_evidence"] = True

        # iç terim / kaynak etiketi (kanıttan bağımsız)
        spans: List[Tuple[int, int]] = [m.span() for m in _CONTRACT_HEAD.finditer(answer)]
        spans += [m.span() for m in _CONTRACT_ASOF.finditer(answer)]
        for m in _SOURCE_RE.finditer(answer):
            if any(a <= m.start() < b for a, b in spans):
                continue                        # sözleşme başlığı: sızıntı değil
            add("source_label", m.group(0).strip(" ()"))
            spans.append(m.span())
        names = _tool_names()
        uf = fold(user_message)
        seen_terms: Set[str] = set()
        body = _CODE_BLOCK.sub(lambda m: " " * len(m.group(0)), answer)     # aynı uzunluk: span ofsetleri tutsun
        for m in _SNAKE_RE.finditer(body):
            if any(a <= m.start() < b for a, b in spans):
                continue
            tok = m.group(1)
            tl = tok.lower()
            if tl in seen_terms or tl in uf:
                continue
            if tok in names or tok in ev.keys or tok in _CONTEXT_FIELDS:
                seen_terms.add(tl)
                add("internal_term", tok, "araç adı" if tok in names else "araç alanı")
        for m in _PHRASE_RE.finditer(answer):
            add("internal_term", m.group(0), "ifade")

        # kabul edilen yanlış öncül
        af = fold(answer)
        for n in _premise_claims(user_message):
            for m in re.finditer(rf"(?<![\d.,]){n}(?![\d])", af):
                w = af[max(0, m.start() - 140): m.end() + 140]
                if not _NEGATION.search(w):
                    add("premise_accepted", str(n), "kullanıcının sayısı olumsuzlanmadan tekrarlandı")
                    break

        res["findings"] = f
        res["evidence"] = {"tools": len(ev.tool_names), "numbers": len(ev.nums), "capped": ev.capped}
    except Exception:
        logger.warning("[Grounding] doğrulayıcı hatası", exc_info=True)
        res["error"] = True
    finally:
        res["ms"] = round((time.perf_counter() - t0) * 1000.0, 1)
    return res


def verify_turn(tr, answer: str, *, history_text: str = "") -> Optional[Dict[str, Any]]:
    """`TurnTrace` üzerinden çalıştır (mod `off` ise None)."""
    m = mode()
    if m == "off":
        return None
    tools = [(t.tool, t.args, t.result) for t in getattr(tr, "tools", [])]
    res = verify(
        answer, user_message=getattr(tr, "message", "") or "", history_text=history_text,
        tools=tools, paths=getattr(tr, "paths", []), platform=getattr(tr, "platform", "") or "",
    )
    res["mode"] = m
    return res


_NOTICE_TEXT = {
    "ungrounded_number": "sayı",
    "ungrounded_entity": "ad",
    "ungrounded_command": "komut",
    "internal_term": "iç terim",
    "source_label": "kaynak etiketi",
    "premise_accepted": "sorunuzdaki sayı",
}


_LEAK_CLASSES = ("internal_term", "source_label")


def notice_for(res: Optional[Dict[str, Any]], classes: Iterable[str]) -> str:
    """`enforce` modunda eşiği geçen sınıflar için cevabın sonuna eklenecek uyarı (yoksa boş).
    Veri sınıfları (sayı/ad/komut/öncül): «araç verisinde doğrulanamadı»; sızıntı sınıfları (iç terim/kaynak
    etiketi): «sistem içi ad, kullanıcıya yönelik değil»."""
    if not res or not res.get("findings"):
        return ""
    cls = set(classes)
    hits = [x for x in res["findings"] if x["class"] in cls]
    if not hits:
        return ""

    def fmt(group: Iterable[str]) -> str:
        parts: List[str] = []
        for c in dict.fromkeys(x["class"] for x in hits if x["class"] in group):
            vals = [x["text"] for x in hits if x["class"] == c][:4]
            parts.append(f"{_NOTICE_TEXT.get(c, c)}: " + ", ".join(f"`{v}`" for v in vals))
        return "; ".join(parts)

    data = fmt([c for c in CLASSES if c not in _LEAK_CLASSES])
    leak = fmt(_LEAK_CLASSES)
    out = "\n\n---\n**Doğrulama uyarısı:** "
    if data:
        out += "Bu cevaptaki şu ifadeler araç verisinde doğrulanamadı — " + data + ". Kaynak veriyi kontrol edin."
    if leak:
        out += (" " if data else "") + "Şu ifadeler sistem içi ad/alan adıdır, kullanıcıya yönelik değildir — " + leak + "."
    return out
