"""Automic sohbeti yardımcıları — deterministik araç yedeği ve yanıt sızıntı filtresi.

Araç döngüsü LLM hatası/zaman aşımı yüzünden hiç veri getiremezse soru anahtar
kelimelerle sınıflandırılıp ilgili READ_ONLY araçlar doğrudan çağrılır; nihai yanıt
yine veriye dayanır. Kanal tabanlı modeller (gpt-oss vb.) iç monoloğu içerik kanalına
sızdırabildiği için akış ilk Markdown başlığına kadar tamponlanır.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

_MAX_TOOL_TEXT = 8000

_RUN_ID_RE = re.compile(r"(?i)(?:run\s*-?id|runid|çalışma)\D{0,12}(\d{5,})|\b(\d{7,})\b")
_RANGE_RE = re.compile(r"(?i)son\s+(\d{1,3})\s*(saat|gün|gun|hafta|ay|dakika|dk)")
_ACTIVE_RE = re.compile(r"(?i)\b(aktif|çalışan|calisan|şu\s*an|su\s*an|koşan|running|bekleyen|takılı|uzun\s+süren)")
_TREND_RE = re.compile(r"(?i)\b(trend|eğilim|artış|azalış|kıyas|karşılaştır|ay\s*sonu)")
_SLOW_RE = re.compile(r"(?i)\b(yavaş|uzun\s+süren|en\s+uzun|süre(?:si)?\s+artan|gecik)")
_STATUS_RE = re.compile(r"(?i)\b(durum|sağlık|bağlantı|collector|toplayıcı|gecikme|lag\b|kota)")
# Kullanıcı ADI ifadeleri: "ahmet kullanıcısının", "kullanıcı BATCH/OPS", "ops tarafından", "user admin"
_USER_TOKEN = r"([\w][\w./\\*?\-]{1,63})"
_USER_RE = re.compile(
    r"(?i)(?:\bkullan[ıi]c[ıi](?:s[ıi]|lar[ıi]|n[ıi]n|s[ıi]n[ıi]n|yla|ya|\s*ad[ıi])?\s*[:=]?\s+" + _USER_TOKEN
    + r"|\buser\s*[:=]?\s+" + _USER_TOKEN
    + r"|" + _USER_TOKEN + r"\s+(?:kullan[ıi]c[ıi]s[ıi]n?[ıi]?n?|tarafından|adlı\s+kullanıcı))")
_USER_STOP = {"bilgisi", "adı", "adi", "için", "icin", "ile", "olan", "hangi", "kim", "kimin", "bir", "bu", "şu", "su",
              "ve", "veya", "hata", "hatalı", "hatali", "aldı", "aldi", "alan", "başarısız", "basarisiz", "en", "çok", "cok", "kaç", "kac", "ne", "nerede", "nasıl", "nasil", "tüm", "tum", "son", "dün", "bugün", "listele", "göster", "goster", "çalıştırdığı", "calistirdigi", "çalıştırdı", "calistirdi", "çalıştıran", "calistiran", "var", "yok", "id", "idsi"}


def detect_user(message: str) -> Optional[str]:
    for m in _USER_RE.finditer(message or ""):
        tok = next((g for g in m.groups() if g), None)
        tok = (tok or "").rstrip("?.,;:!")
        if tok and tok.lower() not in _USER_STOP and not tok.isdigit() and len(tok) > 1:
            return tok
    return None


def detect_range(message: str) -> str:
    m = _RANGE_RE.search(message or "")
    if m:
        n = max(1, int(m.group(1)))
        unit = m.group(2).lower()
        if unit in ("dakika", "dk"):
            return f"{max(1, n // 60) if n >= 60 else 1}h"
        if unit == "saat":
            return f"{n}h"
        if unit in ("gün", "gun"):
            return f"{n}d"
        if unit == "hafta":
            return f"{n * 7}d"
        return f"{n * 30}d"
    # dün/bugün/bu hafta → resolve_time_window + clock.set_window (takvim günü); yedek planda
    # rolling 48h kullanılmaz (tutarsız "dün" yorumunu önlemek için).
    low = (message or "").lower()
    if "bu ay" in low or "aylık" in low:
        return "30d"
    return "24h"


_INFRA_RE = re.compile(
    r"(?i)\b(engine|pwp|\bwp\b|\bcp\b|jcp|jwp|kopuk\s+agent|ba[ğg]l[ıi]\s+m[ıi]|"
    r"hangi\s+sunucu|sunucuda\s+[cç]al[ıi][sş])"
)
_OBJ_HOST_RE = re.compile(
    r"(?i)\b(?:JOBS|JOBP|JOBF|JOBG|SCRI)\.[A-Z0-9_.]+\b.{0,40}"
    r"(?:hangi\s+sunucu|hangi\s+agent|nerede\s+[cç]al[ıi][sş]|which\s+(?:server|host|agent))"
)


def plan_fallback(message: str) -> List[Tuple[str, Dict[str, Any]]]:
    msg = message or ""
    rng = detect_range(msg)
    m = _RUN_ID_RE.search(msg)
    if m:
        return [("automic_execution", {"run_id": int(m.group(1) or m.group(2)), "aspect": "detail"})]
    # Engine / PWP / agent durumu
    if re.search(r"(?i)\bpwp\b", msg):
        return [("automic_infrastructure", {"aspect": "engines"})]
    if re.search(r"(?i)\bengine\b", msg):
        return [("automic_infrastructure", {"aspect": "engines"})]
    if re.search(r"(?i)\b(kopuk|ba[ğg]l[ıi])\b.*\bagent|agent.*\b(kopuk|ba[ğg]l[ıi])", msg):
        if re.search(r"(?i)kopuk", msg):
            return [("automic_infrastructure", {"aspect": "agents", "status": "disconnected"})]
        return [("automic_infrastructure", {"aspect": "agents"})]
    oh = _OBJ_HOST_RE.search(msg) or (
        re.search(r"(?i)\b(?:JOBS|JOBP)\.[A-Z0-9_.]+", msg)
        and re.search(r"(?i)(sunucu|agent|host)", msg)
        and not re.search(r"(?i)hata|fail|neden", msg)
    )
    if oh:
        om = re.search(r"(?i)\b(?:JOBS|JOBP|JOBF|JOBG|SCRI)\.[A-Z0-9_.]+", msg)
        if om:
            return [("automic_infrastructure", {
                "aspect": "object_host", "object_name": om.group(0), "range": rng if rng != "24h" else "7d",
            })]
    usr = detect_user(msg)
    agg = re.search(r"(?i)kullan[ıi]c[ıi]", msg) and re.search(
        r"(?i)\b(hangi|kim|en\s+çok|en\s+cok|sıralama|dağılım|dagilim|bazında|bazinda|aktivite)", msg)
    if agg and not (usr and re.search(r"[/*]", usr)):
        return [("automic_history", {"template_id": "user_activity", "range": rng if rng != "24h" else "7d"})]
    if usr:
        args: Dict[str, Any] = {"user": usr, "range": rng, "limit": 25}
        if re.search(r"(?i)\b(hata|hatalı|hatali|başarısız|basarisiz|fail|abend)", msg):
            args["status_class"] = "failed"
        plan = [("automic_search_executions", args)]
        if _ACTIVE_RE.search(msg):
            plan.append(("automic_active", {"user": usr, "limit": 30}))
        return plan
    if _STATUS_RE.search(msg) and not re.search(r"(?i)hata|fail|abend", msg):
        return [("automic_status", {})]
    if _ACTIVE_RE.search(msg):
        return [("automic_active", {"limit": 30})]
    if _SLOW_RE.search(msg):
        return [("automic_history", {"template_id": "slowest_objects", "range": rng}),
                ("automic_history", {"template_id": "duration_outliers", "range": rng})]
    if _TREND_RE.search(msg):
        return [("automic_history", {"template_id": "failure_trend", "range": rng if rng.endswith("d") else "7d"})]
    return [
        ("automic_history", {"template_id": "top_failed_objects", "range": rng}),
        ("automic_history", {"template_id": "error_signatures", "range": rng}),
        ("automic_search_executions", {"status_class": "failed", "range": rng, "limit": 10}),
    ]


def run_fallback(message: str, system_id: int) -> Tuple[str, List[Dict[str, Any]], List[str]]:
    """Plan edilen araçları doğrudan çalıştırır → (tool_text, structured_results, tools_used)."""
    from app.services.agent.tools import TOOLS

    ctx = {"platform": "automic", "automic_system_id": system_id}
    texts: List[str] = []
    structured: List[Dict[str, Any]] = []
    used: List[str] = []
    for name, args in plan_fallback(message):
        tool = TOOLS.get(name)
        if tool is None or tool.direct_handler is None:
            continue
        try:
            res = tool.direct_handler(None, args, ctx)
        except Exception as exc:
            res = {"ok": False, "error": f"Araç hatası: {exc}"}
        used.append(name)
        structured.append({"tool": name, "args": args, "result": res})
        body = json.dumps(res, ensure_ascii=False, default=str)
        texts.append(f"[{tool.direct_label or name} — {json.dumps(args, ensure_ascii=False)}]\n{body[:_MAX_TOOL_TEXT]}")
    return "\n\n".join(texts), structured, used


# Yanıt başlangıcı: Markdown başlığı VEYA kapanmış kalın giriş cümlesi.
# Sızan iç monolog bu işaretten önceki metindir. Çıplak `**` (kapanmamış) hızlı akıtılmaz —
# "Provide bold… Let's craft" gibi planlama sızıntısı `**` ile başlayabiliyordu.
_HEADING_RE = re.compile(r"(?m)(^#{1,4}\s+\S|(?:^|(?<=[.!?:\n]))\*\*[^*\n]{2,1200}\*\*[.:!?]?\s*)")
_FENCE_OPEN_RE = re.compile(r"(?m)^```(?:markdown|md)\s*\n")
# İngilizce iç planlama / talimat sızıntısı — tek kaynak: answer_validator
from app.services.automic.answer_validator import (  # noqa: E402
    FORBIDDEN_PHRASES as _FORBIDDEN_PHRASES,
    _PLAN_LEAK_RE,
)
_META_VISIBLE_RE = re.compile(
    r"(?im)^(?:\*\*)?\s*(?:Ainew-?meta|Follow-?ups?|ainew-meta)\s*(?:\*\*)?\s*:?\s*$"
)
_META_INLINE_RE = re.compile(
    r"(?im)(?:^|\n)\s*(?:\*\*)?\s*Ainew-?meta\s*(?:\*\*)?\s*:?\s*(?=\n|```|$)"
)
_TOOL_SYNTAX_RE = re.compile(
    r"(?i)\bautomic_[a-z_]+\s*\(|\baspect\s*=\s*[\"']?\w+|template_id\s*=\s*[\"']?\w+"
)


def looks_like_planning_leak(text: str) -> bool:
    """Cevap gövdesinde İngilizce planlama / iç monolog sızıntısı var mı?"""
    if not text or not text.strip():
        return False
    head = text.lstrip()[:800]
    if _PLAN_LEAK_RE.search(head):
        return True
    # Türkçe cevapta uzun İngilizce cümle bloğu (3+ ardışık EN kelime kalıbı)
    if re.search(r"(?i)\b(Provide|Should|Probably|Let's)\b.{0,80}\b(list|craft|answer|bold)\b", head):
        return True
    return False


def strip_planning_leak(text: str) -> str:
    """Sızan planlama önekini kes; ilk geçerli kalın/başlık satırından itibaren bırak."""
    if not text:
        return text
    m = _HEADING_RE.search(text)
    if m and m.start() > 0:
        return text[m.start():]
    # Satır satır: planlama satırlarını at
    lines = text.splitlines(keepends=True)
    kept: List[str] = []
    started = False
    for ln in lines:
        if not started:
            if _PLAN_LEAK_RE.search(ln) or (ln.strip().startswith("**") and "**" not in ln.strip()[2:]):
                continue
            if ln.strip().startswith(("**", "#")) or (ln.strip() and not _PLAN_LEAK_RE.search(ln)):
                started = True
                kept.append(ln)
        else:
            kept.append(ln)
    return "".join(kept) if kept else text


def strip_internal_labels(text: str) -> str:
    """Kullanıcıya iç etiket / meta başlığı / araç sözdizimi gösterme."""
    if not text:
        return text
    idx = text.find("```ainew-meta")
    head, tail = (text[:idx], text[idx:]) if idx >= 0 else (text, "")
    head = _META_INLINE_RE.sub("\n", head)
    lines = []
    for ln in head.splitlines(keepends=True):
        if _META_VISIBLE_RE.match(ln.strip("\n")):
            continue
        if _TOOL_SYNTAX_RE.search(ln):
            continue
        lines.append(ln)
    return "".join(lines) + tail


class AnswerLeakGuard:
    """Yanıt başlangıcından (başlık veya kapanmış kalın giriş) önceki sızan monoloğu atar.

    Çıplak `**` ile hızlı akıtma YOK — kapanmış `**…**` veya `#` gerekir.
    ```markdown sarmalı açılır; meta çiti korunur.
    """

    def __init__(self, hold_chars: int = 3000):
        self.hold_chars = hold_chars
        self.buf = ""
        self.released = False
        self.unwrap_fence = False
        self.dropped = 0
        self.dropped_text = ""   # atılan sızıntının başı (teşhis; kullanıcıya gitmez)
        self.fast_released = False
        self.leak_suspected = False

    def feed(self, tok: str) -> str:
        if self.released:
            return tok
        self.buf += tok
        lead = self.buf.lstrip()
        if lead and not self.fast_released:
            # Yalnız TAM kapanmış kalın cümle veya # başlık → hızlı akıt
            if lead.startswith("#"):
                out, self.buf, self.released, self.fast_released = lead, "", True, True
                return out
            m_lead = re.match(r"^\*\*[^*\n]{2,1200}\*\*", lead)
            if m_lead and not _PLAN_LEAK_RE.search(m_lead.group(0)):
                out, self.buf, self.released, self.fast_released = lead, "", True, True
                return out
            # Çıplak `**` veya planlama → tut
            if _PLAN_LEAK_RE.search(lead[:400]):
                self.leak_suspected = True
        m = _HEADING_RE.search(self.buf)
        if m:
            pre = self.buf[:m.start()]
            if _FENCE_OPEN_RE.search(pre):
                self.unwrap_fence = True
            if pre.strip() and (_PLAN_LEAK_RE.search(pre) or looks_like_planning_leak(pre)):
                self.leak_suspected = True
            # Başlangıçtaki kalın cümle kendisi planlama mı?
            cand = self.buf[m.start():m.start() + 200]
            if _PLAN_LEAK_RE.search(cand):
                self.leak_suspected = True
                # Bu "başlık" sızıntı — sonraki gerçek başlığı bekle
                rest = self.buf[m.end():]
                m2 = _HEADING_RE.search(rest)
                if m2:
                    pre2 = self.buf[:m.end() + m2.start()]
                    self.dropped = len(pre2) if pre2.strip() else 0
                    self.dropped_text = pre2.strip()[:160]
                    out = rest[m2.start():]
                    self.released = True
                    self.buf = ""
                    return out
                return ""
            self.dropped = len(pre) if pre.strip() else 0
            self.dropped_text = pre.strip()[:160] if pre.strip() else ""
            out = self.buf[m.start():]
            self.released = True
            self.buf = ""
            return out
        if len(self.buf) >= self.hold_chars:
            raw = self.buf
            if looks_like_planning_leak(raw):
                self.leak_suspected = True
                cleaned = strip_planning_leak(raw)
                if cleaned != raw:
                    self.dropped = max(0, len(raw) - len(cleaned))
                    self.dropped_text = raw.strip()[:160]
                out, self.buf, self.released = cleaned, "", True
                return out
            out, self.buf, self.released = raw, "", True
            return out
        return ""

    def flush(self) -> str:
        out, self.buf = self.buf, ""
        self.released = True
        if out and looks_like_planning_leak(out):
            self.leak_suspected = True
            return strip_planning_leak(out)
        return out

    def clean_full(self, text: str) -> str:
        """Kaydedilecek tam metin: sarmal ```markdown kapanışını kaldırır; sızıntı/etiket temizler."""
        if self.unwrap_fence:
            idx = text.find("```ainew-meta")
            head, tail = (text[:idx], text[idx:]) if idx >= 0 else (text, "")
            head = re.sub(r"\n```\s*$", "\n", head.rstrip() + "\n")
            text = head + ("\n" + tail if tail else "")
        if looks_like_planning_leak(text) or self.leak_suspected:
            self.leak_suspected = True
            body_idx = text.find("```ainew-meta")
            body, meta = (text[:body_idx], text[body_idx:]) if body_idx >= 0 else (text, "")
            body = strip_planning_leak(body)
            text = body + meta
        return strip_internal_labels(text)


def deterministic_answer(structured: List[Dict[str, Any]], reason: str = "") -> str:
    """LLM yanıt veremediğinde araç sonuçlarından kısa Türkçe özet (tablolar bileşen olarak gelir).

    Sunum: kalın giriş cümlesi + kısa bulgu paragrafları (sabit başlık şablonu yok)."""
    items: List[str] = []

    def add(title: str, text: str) -> None:
        items.append(f"**{title}** · {text}")

    for sr in structured or []:
        res = sr.get("result") if isinstance(sr.get("result"), dict) else {}
        tool = sr.get("tool") or ""
        if res.get("ok") is False:
            add("Araç hatası", f"{tool}: {res.get('error') or 'araç hatası'}")
            continue
        tid = res.get("template_id")
        rows = res.get("rows") or []
        if tid == "top_failed_objects" and rows:
            add("En çok hata veren nesneler", ", ".join(
                f"`{r['object_name']}` ({r['failed']}/{r['runs']}, %{r['failure_rate_pct']})" for r in rows[:5]))
        elif tid == "error_signatures" and rows:
            add("En sık hata imzaları", "; ".join(
                f"`{str(r['signature'])[:120]}` ({r['count']} kez)" for r in rows[:3]))
        elif tid and rows:
            add(str(res.get("label") or tid), f"{len(rows)} satır (tabloya bakın)")
        elif tool == "automic_search_executions":
            c = res.get("counts") or {}
            add("Eşleşen çalışma", f"{res.get('total', 0)} (hatalı {c.get('failed', 0)}, "
                                   f"iptal {c.get('cancelled', 0)}, başarılı {c.get('ok', 0)})")
            if res.get("user_query"):
                src = "kaynaktan canlı" if res.get("data_source") == "source_live" else "modül DB"
                names = ", ".join(u.get("name") or u.get("user") or "?"
                                  for u in (res.get("source_users") or res.get("matched_users") or [])[:5]) or "yok"
                add("Kullanıcı", f"'{res['user_query']}' ({src}); eşleşen kullanıcılar: {names}")
        elif tool == "automic_active":
            add("Aktif çalışma", f"{res.get('total', 0)}; p95 üstü: {len(res.get('over_p95') or [])}")
        elif tool == "automic_execution" and res.get("execution"):
            e = res["execution"]
            add(f"RunID {e.get('run_id')}", f"`{e.get('object_name')}` {e.get('status_class')} "
                                            f"({e.get('status_code')}), süre {e.get('duration_sec')} sn")
            if res.get("error_signature"):
                add("Hata imzası", f"`{str(res['error_signature'])[:200]}`")
        elif tool == "automic_status":
            add("Kaynak gecikmesi", f"{res.get('source_lag_sec')} sn; son toplama: {res.get('last_collect_at')}")
    out = ["**Dil modeli şu an yanıt üretemedi; veriler doğrudan Automic'ten okundu.**", "",
           "Aşağıdakiler yorum veya kök neden analizi içermez."]
    out += [""] + ["\n\n".join(items)] if items else ["", "Araç sonucu yok."]
    if reason:
        out += ["", f"_LLM hatası: {reason[:160]}_"]
    return "\n".join(out)


_DEFINE_RE = re.compile(r"(?i)\b(nedir|ne\s+demek|ne\s+anlama|anlama\s+gel|ne\s+işe\s+yar|açıkla|acikla|tanım|fark[ıi]?\s+nedir|"
                        r"farkı|arasındaki\s+fark|what\s+is|meaning|nasıl\s+(?:hesaplan|okun|çözül|bulun))")
_DATA_RE = re.compile(r"(?i)(\bson\s+\d|\bdün\b|\bbugün\b|\bbu\s+(?:gece|hafta|ay)\b|\blistele|\bkaç\b|\bşu\s*an\b|"
                      r"\bhangi\s+(?:job|iş|nesne|agent|kullanıcı|workflow)|\b\d{7,}\b|\bhatalı\s+job|\bçalıştır(?:dı|an)\b)")

# Açık meta/sohbet — yalnızca bunlar VE veri sinyali yoksa "meta" (kısa mesaj)
_META_RE = re.compile(
    r"(?i)\b("
    r"merhaba|selam|hey|hi|hello|günaydın|iyi\s+akşamlar|"
    r"teşekkür(?:ler| ederim)?|sağ\s*ol|thanks|thank\s*you|"
    r"sen\s+kimsin|kendini\s+tan[ıi]t|who\s+are\s+you|"
    r"(?:sen\s+)?(?:hangi|ne)\s+model(?:sin|siniz|i\s+kullanıyorsun)?|"
    r"ne\s+yapabilirsin|yeteneklerin(?:\s+neler)?|nasıl\s+yardım(?:\s+edebilirsin)?|"
    r"verileri\s+nereden\s+al(?:ıyorsun|ırsın)|"
    r"nasıl\s+çalışıyorsun|nerede\s+çalışıyorsun|"
    r"salt\s+okunur\s+musun|yazabilir\s+misin"
    r")\b"
)
# Automic veri varlığı / operasyon kelimeleri — varsa asla meta sayma
_DATA_SIGNAL_RE = re.compile(
    r"(?i)("
    r"\b(?:job|jobs|iş|işler|nesne|object|agent|workflow|jobp|rapor|report|"
    r"çalışma|calisma|runid|run\s*-?id|hata|hatal[ıi]|abend|fail(?:ed|ure)?|"
    r"aktif|bekleyen|ert|queue|kuyruk|client|toplama|collector|lag|kota|"
    r"trend|imza|signature|restart|workflow)\b|"
    r"\b\d{7,}\b|"  # RunID benzeri
    r"[A-Z]{2,}[./][A-Z0-9_.]{2,}"  # JOBS.DWH.SYNC.01 benzeri
    r")"
)


def is_knowledge_question(message: str) -> bool:
    """Tanım/şema/metrik soruları (ör. "EH_Signal 2 ne demek"): araç yedeği çalıştırma, RAG yeter."""
    msg = message or ""
    if not _DEFINE_RE.search(msg) or _DATA_RE.search(msg):
        return False
    return detect_user(msg) is None


def classify_chat_intent(message: str) -> str:
    """Temkinli niyet: yalnız açık meta + veri sinyali yok → ``meta``.

    Tanım soruları → ``knowledge``. Şüphede / veri sinyali → ``data``.
    """
    msg = (message or "").strip()
    if not msg:
        return "data"
    if _DATA_SIGNAL_RE.search(msg) or detect_user(msg) or _RUN_ID_RE.search(msg):
        return "data"
    # Kısa meta kalıbı (tüm cümle veya başı)
    if _META_RE.search(msg) and len(msg) < 160:
        return "meta"
    if is_knowledge_question(msg):
        return "knowledge"
    return "data"


def needs_fallback(tool_text: str, tools_used: Optional[List[str]]) -> bool:
    return not (tool_text or "").strip() or not tools_used


def deterministic_identity_answer(
    *,
    app_name: str = "ainew",
    model: str = "",
    llm_deployment: str = "internal",
    system_name: str = "",
    source_label: str = "",
    last_collection: str = "",
    capabilities_note: str = "",
    with_meta: bool = True,
) -> str:
    """Meta/kimlik soruları için sabit yanıt (LLM yok — uydurma ortam adı engellenir).

    ``system_name`` Entegrasyonlar’daki Automic sistem adıdır (ör. DEV-FAKE).
    """
    dep = (llm_deployment or "internal").strip().lower()
    dep_tr = "kurum içinde (internal)" if dep == "internal" else "kurum dışı gateway (external)"
    model_s = (model or "").strip() or "yapılandırılmış dil modeli"
    env = (system_name or "").strip() or "tanımsız"
    src = (source_label or "Automic kaynak veritabanı (salt okunur)").strip()
    last = (last_collection or "henüz yok").strip()
    # ISO → okunabilir kısaltma
    if "T" in last and len(last) >= 19:
        last = last.replace("T", " ")[:19]
    caps = (capabilities_note or (
        "çalışma/hata arama, aktif işler, nesne/script, trend ve agent aktivitesi"
    )).strip()
    body = (
        f"**{app_name} Automic Asistanı’yım; dil modelim `{model_s}`.**\n\n"
        f"**Kimlik** · {app_name} içindeki salt okunur Automic (UC4) asistanıyım. "
        f"Bağlı sistem: `{env}`. LLM konumu: {dep_tr}. "
        f"Automic’te başlatma/iptal/değişiklik yapmam.\n\n"
        f"**Veri** · Öncelik toplanmış modül veritabanı; kaynak: {src}. "
        f"Son toplama: {last}.\n\n"
        f"**Yetenekler** · {caps}. "
        f"Ortam verisi sorularında araç kullanırım; kimlik/selam sorularında araç çağırmam."
    )
    if not with_meta:
        return body
    meta_obj = {
        "intent": "general_info",
        "severity": "info",
        "confidence": "high",
        "scope": {},
        "entities": [],
        "follow_ups": [
            "Dün gece hata veren job'lar neler?",
            "Şu an aktif işler var mı?",
        ],
    }
    return body + "\n\n```ainew-meta\n" + json.dumps(meta_obj, ensure_ascii=False) + "\n```"


_QUERY_SKIP = {"system", "system_id", "limit", "sort", "offset", "client"}


def compact_query(tool: Optional[str], args: Optional[Dict[str, Any]]) -> str:
    """Araç çağrısının filtre özetini üretir (ör. ``automic_search_executions status_class=failed from=…``).

    Sohbet geçmişine eklenir: "bunlardan / onların" gibi takip sorularında model önceki sorgunun
    durum/aralık/nesne filtresini yeniden kullanabilsin (asistan metni tek başına bu bilgiyi taşımaz).
    """
    if not tool or not isinstance(args, dict):
        return ""
    parts = []
    for k, v in args.items():
        if k in _QUERY_SKIP or v in (None, "", 0, "*", [], {}):
            continue
        parts.append(f"{k}={v}")
    return f"{tool} " + " ".join(parts)[:200] if parts else str(tool)
