"""LLM sohbet politikası — think seviyesi, num_predict, soru derinliği (Adım 6b).

Ayarlar `runtime_settings` (llm_think_*, llm_num_predict_*) üzerinden değiştirilebilir.
gpt-oss (Harmony) dışındaki modellere `think` seviyesi GÖNDERİLMEZ (Ollama bool bekler).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

LEVELS = ("low", "medium", "high")

# Analiz: neden / karşılaştırma / ortak nokta / trend / değişim
_ANALYSIS_RE = re.compile(
    r"(?i)(\bneden\b|\bniçin\b|\bniye\b|\bwhy\b|kök\s*neden|sebep|"
    r"kar[şs][ıi]la[şs]t[ıi]r|k[ıi]yasla|\bfark(?:ı|lar[ıi])?\b|de[ğg]i[şs]ti|de[ğg]i[şs]im|"
    r"ge[çc]en\s+(?:hafta|ay)a?\s+g[öo]re|ortak\s+nokta|ortak\s+y[öo]n|ortakl[ıi]k|"
    r"\btrend|e[ğg]ilim|[öo]r[üu]nt[üu]|analiz|yorumla|de[ğg]erlendir|etkisi|"
    r"ili[şs]ki|korelasyon|\bcompare|\bdifference|\broot\s+cause|\bexplain|\bchanged?\b)"
)
# Basit veri soruları (UI tablo/KPI üretir; metin kısa kalmalı)
_SIMPLE_RE = re.compile(
    r"(?i)(\bka[çc]\b|\bne\s+zaman\b|\ben\s+son\b|\bhangi\b|\blistele|\bg[öo]ster|"
    r"\b[şs]u\s*an\b|\bvar\s+m[ıi]\b|\bkim\b|\bhatal[ıi]\s+i[şs]|\bhata\s+veren\b|"
    r"\bgrupla|\ben\s+uzun\s+s[üu]ren\b|\ben\s+uzun\b|\bsay[ıi]s[ıi]\b|\bdurum\b|"
    r"\bne\s+kadar\b|\bkaç\s+tane\b|"
    r"\bhow\s+many\b|\bwhich\b|\bwhen\b|\blist\b|\bshow\b|\bcount\b|\bright\s+now\b|\bcurrently\b|"
    r"\bhatalar\b|\bçal[ıi][şs][ıi]yo|\bcal[ıi][şs][ıi]yo|\bçal[ıi][şs][ıi]yor\s+mu|\bcal[ıi][şs][ıi]yor\s+mu)"
)


def classify_question_depth(message: str) -> str:
    """'simple' | 'analysis' | 'default' (emin değilse default → medium)."""
    msg = (message or "").strip()
    if not msg:
        return "default"
    if _ANALYSIS_RE.search(msg):
        return "analysis"
    if _SIMPLE_RE.search(msg) and len(msg) < 140:
        return "simple"
    if len(msg) <= 40 and "?" in msg:     # çok kısa soru ('hatalar?', 'dünkü sorun ne?') → kısa cevap
        return "simple"
    return "default"


def _setting(key: str, fallback: Any) -> Any:
    try:
        from app.services.runtime_settings import get_setting
        v = get_setting(key)
        return fallback if v is None or v == "" else v
    except Exception:
        return fallback


def _level(raw: Any, fallback: str) -> str:
    s = str(raw or "").strip().lower()
    return s if s in LEVELS else fallback


def _truthy(v: Any) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def think_level(depth: str, *, tool_selection: bool, sticky: Optional[bool] = None) -> str:
    """Turun amacına / soru derinliğine göre think seviyesi.

    `llm_think_sticky` açıkken (varsayılan) araç seçim turu da cevap seviyesini kullanır —
    gpt-oss'ta seviye değişimi prefix cache'i baştan geçersiz kılar.
    """
    _sticky = _truthy(_setting("llm_think_sticky", True)) if sticky is None else bool(sticky)   # sticky: istek bazlı A/B
    if tool_selection and not _sticky:
        return _level(_setting("llm_think_tool_selection", "low"), "low")
    if depth == "simple":
        return _level(_setting("llm_think_simple", "low"), "low")
    if depth == "analysis":
        return _level(_setting("llm_think_analysis", "medium"), "medium")
    return _level(_setting("llm_think_default", "medium"), "medium")


def temperature_for(*, answer_turn: bool, override: Optional[float] = None) -> float:
    """Tur amacına göre temperature (araç seçimi / cevap). `override` yalnız istek bazlı A/B içindir."""
    if answer_turn and override is not None:
        return max(0.0, min(1.5, float(override)))
    key, default = ("llm_temperature_answer", 0.2) if answer_turn else ("llm_temperature_tools", 0.1)
    try:
        return max(0.0, min(1.5, float(_setting(key, default))))
    except (TypeError, ValueError):
        return default


def num_predict_for(level: str) -> int:
    key = {"low": "llm_num_predict_low", "medium": "llm_num_predict_medium",
           "high": "llm_num_predict_high"}.get(level, "llm_num_predict_medium")
    default = {"low": 1536, "medium": 3072, "high": 6144}.get(level, 3072)
    try:
        return max(256, int(_setting(key, default)))
    except (TypeError, ValueError):
        return default


def bumped_num_predict(current: int) -> int:
    """Length retry: bir kez daha yüksek sınır (2x, en fazla 12288)."""
    return min(12288, max(int(current) * 2, int(current) + 1024))


def supports_think_level(model: Optional[str]) -> bool:
    """Yalnız gpt-oss: think='low|medium|high' string değeri kabul eder."""
    return "gpt-oss" in (model or "").lower()


def ctx_warn_ratio() -> float:
    try:
        return max(0.3, min(0.95, int(_setting("llm_ctx_warn_ratio_pct", 70)) / 100.0))
    except (TypeError, ValueError):
        return 0.7


def stream_final_enabled() -> bool:
    v = _setting("llm_chat_stream_final", True)
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


_LENGTH_HINTS = {
    "simple": (
        "- Yanıt boyu (bu soru): KISA. İlk satırda kalın sonuç cümlesi, en fazla 1–2 ek cümle. "
        "Başlık, madde veya satır satır döküm yazma; tablo/KPI arayüzde zaten gösterilir."
    ),
    "analysis": (
        "- Yanıt boyu (bu soru): ORTA. İlk satırda kalın sonuç cümlesi, ardından en fazla 3 kısa "
        "paragraf (öne çıkan bulgular + tek değerlendirme). Arayüzdeki tabloları tekrar listeleme."
    ),
    "default": (
        "- Yanıt boyu (bu soru): gerektiği kadar kısa; en fazla 2 kısa paragraf, veriyi tekrar dökme."
    ),
}

_USER_SUFFIXES = {
    "simple": "[Yanıt: doğrudan `**` ile başlayan kalın tek cümle + en fazla 1–2 kısa cümle; düşünce/ön söz yazma; başlık/madde yok; veride olmayanı söyleme; sonda ainew-meta bloğu.]",
    "analysis": "[Yanıt: doğrudan `**` ile başlayan kalın sonuç cümlesi + en fazla 3 kısa paragraf; düşünce/ön söz yazma; başlık yazma; yalnız araç verisine dayan, olası nedenleri `Değerlendirme:` altında 'olası' + güven seviyesiyle yaz; veri yoksa 'veri yok' de; sonda ainew-meta bloğu.]",
    "default": "[Yanıt: doğrudan `**` ile başla; kısa tut (en fazla 2 kısa paragraf); düşünce/ön söz yazma; yalnız araç verisine dayan; sonda ainew-meta bloğu.]",
}


def answer_length_hint(depth: str) -> str:
    """Soru derinliğine göre yanıt boyu yönergesi (çalışma zamanı bağlamının SONUNA eklenir)."""
    return _LENGTH_HINTS.get(depth, _LENGTH_HINTS["default"])


def user_suffix_for(depth: str) -> str:
    """Kullanıcı mesajının sonuna eklenen tek satırlık biçim/uzunluk hatırlatması."""
    return _USER_SUFFIXES.get(depth, _USER_SUFFIXES["default"])


_EN_WORDS = {
    "the", "is", "are", "was", "were", "how", "many", "which", "what", "when", "why", "who", "where",
    "show", "list", "count", "jobs", "job", "failed", "running", "right", "now", "yesterday", "today",
    "last", "did", "does", "do", "any", "there", "me", "of", "in", "on", "at", "to", "for", "with",
    "has", "have", "this", "that", "week", "days", "hours", "agent", "agents", "currently", "compare",
}
_TR_CHARS = set("çğıöşüÇĞİÖŞÜ")
_TR_WORDS = {
    "kaç", "hangi", "neden", "nedir", "mi", "mı", "mu", "mü", "bir", "ve", "ile", "için", "dün", "bugün",
    "şu", "son", "gün", "hata", "iş", "joblar", "calisiyo", "simdi", "kim", "ne", "nasıl", "bu", "var",
    "yok", "peki", "hatalar", "çalıştı", "çalışıyor", "kaçı", "onun", "bunlar", "bunların",
}


def language_hint(message: str) -> str:
    """Yalnız İngilizce yazılmış soru için cevap-dili hatırlatması döner (aksi halde boş).

    Sistem prompt'u Türkçe olduğundan model İngilizce soruya Türkçe cevap verebiliyor; dil tespiti
    kodda yapılır (karma / belirsiz metinde ipucu eklenmez, varsayılan Türkçe kalır).
    """
    import re as _re
    msg = (message or "").strip()
    if not msg or any(c in _TR_CHARS for c in msg):
        return ""
    words = [w for w in _re.findall(r"[a-zA-Z']+", msg.lower()) if len(w) > 1]
    if len(words) < 3:
        return ""
    en = sum(1 for w in words if w in _EN_WORDS)
    tr = sum(1 for w in words if w in _TR_WORDS)
    if en >= 2 and en > tr * 2:
        return ("[Reply language: English. Write the entire answer in English "
                "(keep job/agent names as-is); do not answer in Turkish.]")
    return ""


import re as _re_amb

_ENTITY_RE = _re_amb.compile(r"[A-Z][A-Z0-9_]*\.[A-Z0-9_.]+|\b\d{8,}\b|\b[A-Z]{3,}\d{2,}\b|\b(?:JOBS|JOBP|JOBF|VARA|SCRI)\b")
_DEICTIC_RE = _re_amb.compile(
    r"(?<!\w)(?:(?:şu|o|bu)\s+(?:job|iş|agent|workflow|akış|çalışma|sunucu|nesne|kullanıcı)\w*"
    r"|şunu|bunu|onu|şuna|ona|şunun|onun)(?!\w)", _re_amb.IGNORECASE)
_VAGUE_SCOPE_RE = _re_amb.compile(
    r"(?<!\w)(?:dünkü|bugünkü|geçen\s+haftaki|bu\s+haftaki|son)\s+(?:sorun|problem)\w*", _re_amb.IGNORECASE)


def needs_clarification(message: str, has_history: bool) -> bool:
    """Önceki konuşma YOK ve mesajda varlık adı yokken 'şu job / o agent / şunu…' gibi boş gönderme.

    Bu durumda LLM/araç çağrılmaz; deterministik tek kısa açıklayıcı soru döner (prompt kuralı tek başına
    yetmedi: model bağlamsız 'şunu' için rastgele hatalı iş seçip cevap uyduruyordu).
    """
    msg = (message or "").strip()
    if not msg or has_history or _ENTITY_RE.search(msg):
        return False
    return bool(_DEICTIC_RE.search(msg))


CLARIFY_ANSWER = ("**Hangi job, workflow, agent veya çalışmadan söz ettiğinizi anlayamadım.** "
                  "Nesne adını, RunID'yi veya agent adını yazar mısınız?")


def ambiguity_hint(message: str, has_history: bool) -> str:
    """Kapsamı belirsiz ama çıkarılabilir soru ('dünkü sorun ne?') için varsayım yönlendirmesi."""
    msg = (message or "").strip()
    if not msg or _ENTITY_RE.search(msg):
        return ""
    if _VAGUE_SCOPE_RE.search(msg):
        return ("[Kapsam belirsiz: makul varsayımla araç çağır (dün/ilgili dönem, hatalı çalışmalar) ve cevabın "
                "ilk cümlesini `Varsayım: …` ile başlat; sonra kalın sonucu yaz.]")
    return ""


# ── Adım 7 (tur 2): kodla çözülen zaman ifadesi, eylem isteği, olmayan bilgi, takip filtresi ────────────

_TR_MONTHS = ("Ocak", "Şubat", "Mart", "Nisan", "Mayıs", "Haziran", "Temmuz", "Ağustos", "Eylül", "Ekim", "Kasım", "Aralık")


def _iso(dt) -> str:
    return dt.isoformat(timespec="seconds")


_FOLD = str.maketrans({"ç": "c", "ğ": "g", "ı": "i", "İ": "i", "ö": "o", "ş": "s", "ü": "u",
                       "Ç": "c", "Ğ": "g", "Ö": "o", "Ş": "s", "Ü": "u", "â": "a", "î": "i", "û": "u"})
_MONTH_FOLD = ("ocak", "subat", "mart", "nisan", "mayis", "haziran", "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik")
_MON = "(" + "|".join(_MONTH_FOLD) + ")"


def _fold(text: str) -> str:
    """Türkçe harfleri ASCII'ye indirger + küçültür (uzunluk korunur → span'ler orijinalle hizalı)."""
    return (text or "").translate(_FOLD).lower()


# aynı mesajda KARŞILAŞTIRMA / birden çok dönem varsa pencere ZORLANMAZ (model iki dönemi yönetir).
# NOT: dün/bugün/bu hafta burada YOK — onlar resolve_time_window ile zorlanır (tek kaynak).
_NO_FORCE_RE = _re_amb.compile(
    r"karsilastir|kiyasla|compare|\bvs\b|degisti|\bfark|artis|azalis|\bile\b.{0,30}\barasinda|"
    r"\bson\s+\d+|\bson\s+(?:ay|yil|gun|saat)\b|\blast\s+\d+|\bonceki\b")


def resolve_time_window(message: str, now_local) -> Optional[Dict[str, Any]]:
    """Mesajdaki tarih ifadesini KODLA from/to'ya çevirir; model tarih hesaplamaz/üretmez.

    Desteklenen: dün, bugün, bu hafta, geçen hafta, dün gece / last night; 'geçen yıl',
    'N yıl|ay|gün önce', 'geçen ay', 'geçen/bu ayın 3'ü', '15 Mart [2026]', '2025 Aralık',
    'Mart ayında', '2025 yılında', '2026-03-15'.
    Mesajda birden çok farklı dönem varsa None. Dönüş: {expr, label, start, end, force}.
    """
    import re
    from datetime import datetime, timedelta
    m_fold = _fold(message)
    tz = now_local.tzinfo
    y, mo = now_local.year, now_local.month
    cands: List[tuple] = []   # (span, expr, start, end, label)
    spans: List[tuple] = []
    today0 = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    def month_range(yy: int, mm: int):
        while mm <= 0:
            mm += 12
            yy -= 1
        while mm > 12:
            mm -= 12
            yy += 1
        a = datetime(yy, mm, 1, tzinfo=tz)
        b = datetime(yy + (mm == 12), 1 if mm == 12 else mm + 1, 1, tzinfo=tz)
        return a, b, f"{_TR_MONTHS[mm - 1]} {yy}"

    def add(m, a, b, label):
        sp = m.span()
        if any(sp[0] < e and s_ < sp[1] for s_, e in spans):
            return
        spans.append(sp)
        cands.append((sp, (message or "")[sp[0]:sp[1]].strip(), a, b, label))

    def day_range(yy: int, mm: int, dd: int):
        a = datetime(yy, mm, dd, tzinfo=tz)
        return a, a + timedelta(days=1), a.strftime("%Y-%m-%d")

    def safe(fn, m, *a):
        try:
            r = fn(*a)
        except ValueError:
            return
        add(m, *r)

    # 0) takvim göreli: dün gece / dün(kü) / bugün / bu hafta / geçen hafta (kullanıcı TZ + gerçek şimdi)
    for m in re.finditer(r"\b(dun\s+gece|last\s+night)\b", m_fold):
        d0 = today0 - timedelta(days=1)
        add(m, d0.replace(hour=18), today0, d0.strftime("%Y-%m-%d") + " gece")
    for m in re.finditer(r"\b(dunk\w*|dun|yesterday)\b", m_fold):
        d0 = today0 - timedelta(days=1)
        add(m, d0, d0 + timedelta(days=1), d0.strftime("%Y-%m-%d"))
    for m in re.finditer(r"\b(bugun|today)\b", m_fold):
        add(m, today0, today0 + timedelta(days=1), today0.strftime("%Y-%m-%d"))
    for m in re.finditer(r"\b(bu\s+hafta|this\s+week)\b", m_fold):
        # ISO hafta: Pazartesi başlangıç
        week0 = today0 - timedelta(days=today0.weekday())
        add(m, week0, week0 + timedelta(days=7), f"{week0.strftime('%Y-%m-%d')} haftası")
    for m in re.finditer(r"\b(gecen\s+hafta|gectigimiz\s+hafta|last\s+week)\b", m_fold):
        week0 = today0 - timedelta(days=today0.weekday() + 7)
        add(m, week0, week0 + timedelta(days=7), f"{week0.strftime('%Y-%m-%d')} haftası")
    # 1) ayın belirli günü: "geçen ayın 3'ü", "bu ayın 15'i"
    for m in re.finditer(r"\b(gecen|gectigimiz|bu)\s+ay(?:in|inin)\s+(\d{1,2})\b", m_fold):
        base = mo - 1 if m.group(1) != "bu" else mo
        yy, mm = month_range(y, base)[0].year, month_range(y, base)[0].month
        safe(day_range, m, yy, mm, int(m.group(2)))
    # 2) "15 Mart [2026]"
    for m in re.finditer(rf"\b(\d{{1,2}})\s+{_MON}\w*(?:\s+(20\d{{2}}))?", m_fold):
        mm = _MONTH_FOLD.index(m.group(2)) + 1
        dd = int(m.group(1))
        if m.group(3):
            yy = int(m.group(3))
        else:
            yy = y
            try:
                if datetime(yy, mm, dd, tzinfo=tz) > now_local:
                    yy -= 1
            except ValueError:
                continue
        safe(day_range, m, yy, mm, dd)
    # 3) ISO tarih
    for m in re.finditer(r"\b(20\d{2})-(\d{2})-(\d{2})\b", m_fold):
        safe(day_range, m, int(m.group(1)), int(m.group(2)), int(m.group(3)))
    # 4) "2025 Aralık" / "Aralık 2025"
    for m in re.finditer(rf"\b(20\d{{2}})\s+{_MON}\b", m_fold):
        safe(month_range, m, int(m.group(1)), _MONTH_FOLD.index(m.group(2)) + 1)
    for m in re.finditer(rf"\b{_MON}\w*\s+(20\d{{2}})\b", m_fold):
        safe(month_range, m, int(m.group(2)), _MONTH_FOLD.index(m.group(1)) + 1)
    # 5) "Mart ayında" (yıl yok)
    for m in re.finditer(rf"\b{_MON}\s+ay\w*", m_fold):
        mm = _MONTH_FOLD.index(m.group(1)) + 1
        yy = y if datetime(y, mm, 1, tzinfo=tz) <= now_local else y - 1
        safe(month_range, m, yy, mm)
    # 6) "2025 yılında"
    for m in re.finditer(r"\b(20\d{2})\s+yil\w*", m_fold):
        yy = int(m.group(1))
        add(m, datetime(yy, 1, 1, tzinfo=tz), datetime(yy + 1, 1, 1, tzinfo=tz), str(yy))
    # 7) göreli dönemler
    for m in re.finditer(r"\b(gecen|gectigimiz)\s+yil\b", m_fold):
        add(m, datetime(y - 1, 1, 1, tzinfo=tz), datetime(y, 1, 1, tzinfo=tz), str(y - 1))
    for m in re.finditer(r"\b(\d+)\s*yil\s*once\b", m_fold):
        n = int(m.group(1))
        add(m, datetime(y - n, 1, 1, tzinfo=tz), datetime(y - n + 1, 1, 1, tzinfo=tz), str(y - n))
    for m in re.finditer(r"\b(gecen|gectigimiz)\s+ay\b", m_fold):
        add(m, *month_range(y, mo - 1))
    for m in re.finditer(r"\b(\d+)\s*ay\s*once\b", m_fold):
        add(m, *month_range(y, mo - int(m.group(1))))
    for m in re.finditer(r"\b(\d+)\s*gun\s*once\b", m_fold):
        d0 = (now_local - timedelta(days=int(m.group(1)))).replace(hour=0, minute=0, second=0, microsecond=0)
        add(m, d0, d0 + timedelta(days=1), d0.strftime("%Y-%m-%d"))

    if not cands:
        return None
    if len({(c[2], c[3]) for c in cands}) > 1:
        return None
    sp, expr, a, b, label = cands[0]
    rest = "".join(ch if not any(s_ <= i < e for s_, e in spans) else " " for i, ch in enumerate(m_fold))
    return {"expr": expr, "label": label, "start": a, "end": b, "force": not _NO_FORCE_RE.search(rest)}


def forced_window_iso(win: Optional[Dict[str, Any]]) -> Optional[tuple]:
    """Araç katmanına (clock.set_window) verilecek (from, to) UTC ISO; zorlanmayacaksa None."""
    from datetime import timezone
    if not win or not win.get("force"):
        return None
    return (win["start"].astimezone(timezone.utc).isoformat(timespec="seconds"),
            win["end"].astimezone(timezone.utc).isoformat(timespec="seconds"))


def time_expression_hint(message: str, now_local) -> str:
    """Açık/göreli tarih ifadesi → takvim dönemi from/to (KODLA hesaplanır; model tarih hesaplamaz).

    force=True ise araç katmanı pencereyi kendisi uygular (clock.set_window); model from/to/range vermez.
    'son N gün' ifadesi etkilenmez.
    """
    win = resolve_time_window(message, now_local)
    if not win:
        return ""
    a, b = win["start"], win["end"]
    if win["force"]:
        return (f"[Zaman (kodla çözüldü): '{win['expr']}' = takvim dönemi {win['label']}: from={_iso(a)} to={_iso(b)}. "
                "Sistem bu aralığı araç çağrılarına OTOMATİK uygular; araç çağrısında from/to/range VERME. "
                "Kendi 'Varsayım: dün …' tarih cümlesi YAZMA — varsayım metnini sistem ekler.]")
    return (f"[Zaman (kodla hesaplandı; aracı bu from/to ile çağır, `range` kullanma): '{win['expr']}' = takvim dönemi "
            f"{win['label']}: from={_iso(a)} to={_iso(b)}.]")


def time_window_assumption_text(win: Optional[Dict[str, Any]], english: bool = False) -> str:
    """Kodun ürettiği varsayım satırı (model kendi tarih varsayımı yazmasın)."""
    if not win or not win.get("force"):
        return ""
    label = win.get("label") or ""
    expr = win.get("expr") or ""
    if english:
        return f"**Assumption:** «{expr}» = {label} (computed by the system from the user's timezone)."
    return f"**Varsayım:** «{expr}» = {label} (kullanıcı saat dilimine göre sistem hesapladı)."


def canonical_time_phrase(win: Optional[Dict[str, Any]], english: bool = False) -> str:
    """Cevap metninde kullanılacak tek zaman ifadesi (kod penceresiyle aynı)."""
    if not win:
        return ""
    expr = (win.get("expr") or "").strip()
    label = (win.get("label") or "").strip()
    if not expr:
        return label
    return expr if not label else f"{expr} ({label})"


# Cevaptaki zaman ifadesi ↔ kod penceresi uyumu (kalite)
_TIME_PHRASE_RE = _re_amb.compile(
    r"(?i)\b(son\s+24\s+saat|son\s+\d+\s*(?:saat|g[uü]n)|d[uü]n\s+gece|d[uü]n|bug[uü]n|"
    r"bu\s+hafta|ge[cç]en\s+hafta|bu\s+ay|ge[cç]en\s+ay|last\s+night|yesterday|today|"
    r"this\s+week|last\s+week|last\s+\d+\s*(?:hours?|days?))\b"
)


_ACTION_VERBS = (r"restart|yeniden\s+başlat|iptal|durdur|başlat|güncelle|sil|çalıştır|tetikle|kill|stop|start|cancel|abort|delete|"
                 r"disable|enable|devre\s+dışı\s+bırak|onayla|askıya\s+al|serbest\s+bırak|release|hold|reset|düzelt|değiştir")
# buyruk kipi: fiil kökü TAM kelime (çalıştı/çalıştırdı eşleşmez) + isteğe bağlı "et" + cümle/ifade sonu
_ACTION_RE = _re_amb.compile(rf"(?<!\w)(?:{_ACTION_VERBS})(?:\s+et)?(?!\w)(?=\s*(?:[,.!;]|\bve\b|$))", _re_amb.IGNORECASE)
_ACTION_EN_RE = _re_amb.compile(rf"^\s*(?:please\s+)?(?:{_ACTION_VERBS})\b", _re_amb.IGNORECASE)
_QUESTION_WORD_RE = _re_amb.compile(r"\?|\b(neden|niçin|nasıl|ne\s+zaman|kaç|hangi|kim|nedir|var\s+mı|olur\s+mu)\b", _re_amb.IGNORECASE)
_OBJ_RE = _re_amb.compile(r"\b(?:JOBS|JOBP|JOBF|JOBG|VARA|SCRI|SCRP|EVNT|FILE|CALE|SYNC|HOST|XCOM)\.[A-Z0-9_.]+|\b[A-Z]{3,}\d{2,}\b")

# Nesne/agent + neden/son durum — zaman ifadesi yoksa pencere UYGULANMAZ (en son ilgili çalışma)
_ENTITY_LATEST_RE = _re_amb.compile(
    r"(neden\s+hata|ni[cç]in\s+hata|why\s+did|en\s+son\s+(?:ne\s+zaman|durum|calis|fail|hata)|"
    r"son\s+(?:durum|hatas[ıi]|calisma|calismalar|rapor)|last\s+(?:run|status|fail|error|report)|"
    r"hi[cç]\s+hata\s+vermedi|hep\s+basarili|always\s+succeed|"
    r"raporlarini\s+ozet|ile\s+baslayan|baslayan\s+job)",
    _re_amb.IGNORECASE,
)
_HAS_TIME_TOKEN_RE = _re_amb.compile(
    r"\b(dun|bugun|yesterday|today|bu\s+hafta|gecen\s+hafta|this\s+week|last\s+week|"
    r"son\s+\d+|last\s+\d+|gecen\s+ay|bu\s+ay|20\d{2}|ocak|subat|mart|nisan|mayis|haziran|"
    r"temmuz|agustos|eylul|ekim|kasim|aralik)\b",
    _re_amb.IGNORECASE,
)


def entity_latest_no_window(message: str) -> bool:
    """Belirli nesne/agent hakkında neden/son durum sorusu ve zaman token'ı yok → penceresiz (en son)."""
    msg = message or ""
    if not _OBJ_RE.search(msg) and not _re_amb.search(r"\b(LNX|WIN|SAP)[A-Z0-9]+\b", msg):
        return False
    f = _fold(msg)
    if _HAS_TIME_TOKEN_RE.search(f):
        return False
    return bool(_ENTITY_LATEST_RE.search(f))


def action_request_answer(message: str, english: bool = False) -> str:
    """Eylem isteği (restart/iptal/durdur…) ise deterministik cevap; değilse boş.

    Asistan salt-okunurdur: LLM/araç çağrılmaz → 'yapıldı' iddiası, komut/REST/payload ve uydurma AWI adımı imkânsız.
    """
    msg = (message or "").strip()
    if not msg or _QUESTION_WORD_RE.search(msg):
        return ""
    if not (_ACTION_RE.search(msg) or (english and _ACTION_EN_RE.search(msg))):
        return ""
    m = _OBJ_RE.search(msg)
    obj = m.group(0) if m else ""
    from app.services.automic.tr_grammar import action_offer_en, action_offer_tr
    if english:
        what = f" for `{obj}`" if obj else ""
        offer = action_offer_en(msg, obj)
        return (f"**I am a read-only assistant, so I cannot perform this action{what}.** "
                f"{offer}The action itself must be done manually by an authorized user in AWI.")
    what = f" `{obj}` için" if obj else ""
    offer = action_offer_tr(msg, obj)
    return (f"**Ben salt-okunur bir asistanım; bu işlemi{what} yapamam.** "
            f"İsterseniz {offer}işlemin kendisi AWI'da yetkili bir kullanıcı tarafından manuel yapılmalıdır.")


_UNAVAILABLE_RE = _re_amb.compile(
    r"müşteri|customer|maliyet|cost|ücret|fatura|\bsla\b|iş\s+sahib|sahibi|owner|kim\s+yazdı|yazan|geliştirici|author|developer",
    _re_amb.IGNORECASE)


_CODE_MEANING_Q_RE = _re_amb.compile(
    r"neden|sebep|niçin|rapor|hata\s+kod|return\s*code|dönüş\s*kodu|\bwhy\b|\breport\b", _re_amb.IGNORECASE)


def code_meaning_hint(message: str) -> str:
    """Hata/dönüş kodu içerebilecek sorularda: kod anlamını modelin yazmaması (sistem 'Genel bilgi' bloğunu ekler).

    Örnek cümle VERİLMEZ (model örneği veriymiş gibi cevaba kopyalıyordu: j1'de uydurma ORA-01555)."""
    if _CODE_MEANING_Q_RE.search(message or ""):
        return ("[Kural: hata kodu ve return_code için gövdede AÇIKLAMA/NEDEN cümlesi yazma ('bu … anlamına gelir', 'genellikle … "
                "nedeniyle oluşur' YASAK); yalnız araç sonucunda GERÇEKTEN görülen hata satırını gözlem olarak alıntıla (araç sonucunda "
                "yoksa hiçbir kod/hata satırı yazma). Kodun anlamını sistem cevabın sonuna kaynağıyla 'Genel bilgi:' olarak ekler. "
                "return_code sıfırdan farklıysa araç sonucundaki `return_code_note` cümlesini aynen yaz. Olası nedenler yalnız "
                "`Değerlendirme:` paragrafında.]")
    return ""


# Modül verisinde HİÇ tutulmayan bilgi kategorileri (folded = ASCII-küçük harf metin üzerinde aranır)
_UNAVAILABLE_CATS = (
    ("owner", "iş sahibi / yazar", "business owner / author",
     r"\bis\s+sahib\w*|business\s+owner|\bowner\b|\bsahibi\b|kim\s+(?:yazdi|yazmis|olusturdu|gelistirdi|hazirladi)|"
     r"\byazari\b|yazan\s+kisi|gelistirici\w*|\bauthor\b|\bdeveloper\b|who\s+(?:wrote|created|owns|developed|built)"),
    ("cost", "maliyet", "cost",
     r"maliyet\w*|\bcosts?\b|ucret\w*|fatura\w*|butce\w*|\bbudget\b|\bprice\b|\bpricing\b"),
    ("customer", "müşteri / iş etkisi", "customer / business impact",
     r"musteri\w*|\bcustomers?\b|is\s+etkisi|business\s+impact|hangi\s+birim\w*"),
    ("sla", "SLA", "SLA", r"\bsla\b|servis\s+seviye\w*|service\s+level"),
)
# soru veri de istiyorsa (kaç kez, hata, süre…) LLM'e gider; yalnız saf "veride olmayan bilgi" soruları sabit cevaplanır
_DATA_WORDS_RE = _re_amb.compile(
    r"\bkac\b|calist|\bhata|basarisiz|\bdurum|\bsure|\bson\b|\bagent|listele|goster|\bhow\s+many\b|\bfailed\b|\bduration\b")


def unavailable_info_categories(message: str) -> list:
    """Sorudaki 'veride olmayan' bilgi kategorileri: [(id, tr_ad, en_ad)] (kodla tanınır, LLM'e gidilmez)."""
    f = _fold(message)
    return [(cid, tr, en) for cid, tr, en, rx in _UNAVAILABLE_CATS if _re_amb.search(rx, f)]


def unavailable_info_answer(message: str, english: bool = False) -> str:
    """Saf 'veride olmayan bilgi' sorusu için LLM'siz SABİT cevap; değilse ''.

    Cevap hiçbir koşulda DB tablo/kolon adı önermez; yalnız gösterilebilecek kavramsal bilgileri sayar.
    """
    cats = unavailable_info_categories(message)
    if not cats or _DATA_WORDS_RE.search(_fold(message)):
        return ""
    m = _OBJ_RE.search(message or "")
    obj = m.group(0) if m else ""
    if english:
        names = ", ".join(c[2] for c in cats)
        what = f" for `{obj}`" if obj else ""
        return (f"**This information is not available in the current Automic data** ({names}){what}. "
                "I can show instead: run history and failure rate, duration statistics, the agent and client it ran on "
                "(a client is an Automic mandant number, not a customer), the user who started the runs (not an owner/author), "
                "child/parent runs and the latest error reports.")
    names = ", ".join(c[1] for c in cats)
    what = f" `{obj}` için" if obj else ""
    return (f"**Bu bilgi mevcut Automic verisinde yok** ({names}){what}. "
            "Şunları gösterebilirim: çalışma geçmişi ve hata oranı, süre istatistikleri, hangi agent ve client'ta çalıştığı "
            "(client bir Automic mandant numarasıdır, müşteri değildir), çalıştıran kullanıcı (sahip/yazar değildir), "
            "alt/üst çalışmalar ve son hata raporları.")


def unavailable_info_hint(message: str) -> str:
    """Modül verisinde hiç tutulmayan kavramlar sorulduysa tek satırlık not (model `client` numarasını müşteri sanıyordu)."""
    if _UNAVAILABLE_RE.search(message or ""):
        return ("[Not: müşteri, maliyet, SLA, iş sahibi, yazar bilgisi Automic modül verisinde TUTULMAZ. `client` bir mandant "
                "numarasıdır (müşteri DEĞİL); `user` çalıştıran kullanıcıdır (sahip DEĞİL). Soru buna ilişkinse "
                "'bu bilgi mevcut veride yok' de; client/user değerini bu sorunun cevabıymış gibi sunma.]")
    return ""


_FOLLOWUP_RE = _re_amb.compile(
    r"(?<!\w)(bunlar\w*|şunlar\w*|onlar\w*|bunun|bunu|buna|şunun|bu\s+işler\w*|aynı\s+(?:aralık|dönem|filtre)\w*)(?!\w)|^\s*peki\b",
    _re_amb.IGNORECASE)


def followup_hint(message: str, last_queries: Optional[list]) -> str:
    """'bunlardan en uzun…' gibi takip sorusu + önceki sorgu varsa: filtreleri aynen koruma talimatı (kodla eklenir)."""
    if not last_queries or not _FOLLOWUP_RE.search(message or ""):
        return ""
    q = " | ".join(str(x)[:240] for x in last_queries[:2])
    return (f"[Takip sorusu: 'bunlar/onlar' önceki sorgunun sonucudur. Önceki sorgunun durum/zaman/nesne filtrelerini AYNEN koru "
            f"(yeni filtre ekle, eskisini bırakma): {q}]")
