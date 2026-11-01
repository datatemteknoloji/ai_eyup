"""Zaman penceresi çözümleyici (Adım 5c) — SAF fonksiyonlar; Automic'ten bağımsız.

`resolve(message, now, tz) -> Window | None`: mesajdaki zaman ifadesini TAKVİM penceresine çevirir.

  bugün · dün · evvelsi gün · bu hafta · geçen hafta · bu ay · geçen ay · bu yıl · geçen yıl
  son N saat|gün|hafta|ay|yıl|dakika (kayan pencere; "son bir hafta", "son 24 saat")
  N gün önce (o takvim günü) · ISO tarih (2026-10-14) · gg.aa.yyyy · «<yıl> Ocak» / «Ocak <yıl>» (ay)
  <yıl> yılında (yıl) — İngilizce karşılıkları: today, yesterday, this/last week|month|year, last N days…

Takvim kuralları: hafta PAZARTESİ başlar (ISO); «geçen hafta» = önceki Pzt 00:00 → bu Pzt 00:00;
«dün» = dün 00:00 → bugün 00:00; «bu hafta/ay/yıl» = dönem başı → şimdi; «son N …» kayan: şimdi−N → şimdi.
`now` = `chat_quality.clock.now()` (admin+debug_trace `now_override` ile dondurulur); `tz` varsayılan
`Europe/Istanbul` (ayar: `chat_timezone`). Birden fazla FARKLI ifade → belirsiz → `None` (normal akış).
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import List, Optional, Tuple

try:  # py3.9+
    from zoneinfo import ZoneInfo
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from app.services.chat_quality.claims import fold

DEFAULT_TZ = "Europe/Istanbul"
MAX_ROLLING_DAYS = 3650

_NUM_WORDS = {
    "bir": 1, "iki": 2, "uc": 3, "dort": 4, "bes": 5, "alti": 6, "yedi": 7, "sekiz": 8, "dokuz": 9, "on": 10,
    "on bir": 11, "on iki": 12, "on bes": 15, "yirmi": 20, "otuz": 30, "kirk": 40, "elli": 50, "altmis": 60, "doksan": 90,
    "yuz": 100,
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "twelve": 12, "fifteen": 15, "twenty": 20, "thirty": 30,
}
_NUMW_RE = "|".join(sorted((re.escape(w) for w in _NUM_WORDS), key=len, reverse=True))
_NUM = rf"(\d{{1,4}}|{_NUMW_RE})"

# birim → (anahtar, saniye)
_UNITS = {
    "dakika": ("minute", 60), "dk": ("minute", 60), "minute": ("minute", 60), "minutes": ("minute", 60), "min": ("minute", 60),
    "saat": ("hour", 3600), "hour": ("hour", 3600), "hours": ("hour", 3600),
    "gun": ("day", 86400), "day": ("day", 86400), "days": ("day", 86400),
    "hafta": ("week", 7 * 86400), "week": ("week", 7 * 86400), "weeks": ("week", 7 * 86400),
    "ay": ("month", 30 * 86400), "month": ("month", 30 * 86400), "months": ("month", 30 * 86400),
    "yil": ("year", 365 * 86400), "sene": ("year", 365 * 86400), "year": ("year", 365 * 86400), "years": ("year", 365 * 86400),
}
_UNIT_RE = "|".join(sorted((re.escape(u) for u in _UNITS), key=len, reverse=True))

_MONTHS = {
    "ocak": 1, "subat": 2, "mart": 3, "nisan": 4, "mayis": 5, "haziran": 6, "temmuz": 7, "agustos": 8,
    "eylul": 9, "ekim": 10, "kasim": 11, "aralik": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
    "september": 9, "october": 10, "november": 11, "december": 12,
}
_MONTH_RE = "|".join(sorted(_MONTHS, key=len, reverse=True))


@dataclass(frozen=True)
class Window:
    start: datetime          # tz'li
    end: datetime            # tz'li
    kind: str                # day | week | month | year | rolling | ago
    expr: str                # eşleşen metin
    tz_name: str
    name_tr: str = ""        # "dün", "geçen hafta" …

    def days_back(self, now: datetime) -> int:
        """Pencerenin başlangıcına kadar kaç GÜN geriye bakmak gerekir (≥1)."""
        return max(1, math.ceil((_aware(now, self.start.tzinfo) - self.start).total_seconds() / 86400))

    def span_days(self) -> float:
        return (self.end - self.start).total_seconds() / 86400

    @property
    def label(self) -> str:
        return f"{self.start:%Y-%m-%d %H:%M} – {self.end:%Y-%m-%d %H:%M} ({self.tz_name})"

    @property
    def title(self) -> str:
        name = (self.name_tr or self.expr).strip()
        name = name[:1].upper() + name[1:] if name else ""
        return f"{name}: {self.label}" if name else self.label

    def utc_range(self) -> Tuple[datetime, datetime]:
        import datetime as _dt
        return self.start.astimezone(_dt.timezone.utc), self.end.astimezone(_dt.timezone.utc)

    def contains(self, ts: datetime) -> bool:
        ts = _aware(ts, self.start.tzinfo)
        return self.start <= ts < self.end


def _tz(name: Optional[str]):
    nm = name or DEFAULT_TZ
    if ZoneInfo is None:
        import datetime as _dt
        return _dt.timezone(timedelta(hours=3)), "UTC+03:00"
    try:
        return ZoneInfo(nm), nm
    except Exception:
        return ZoneInfo(DEFAULT_TZ), DEFAULT_TZ


def _aware(dt: datetime, tz) -> datetime:
    """Naif → sistem yerel saati varsay; ardından tz'ye çevir."""
    if dt.tzinfo is None:
        dt = dt.astimezone()   # naif = yerel
    return dt.astimezone(tz)


def _day_start(d: datetime) -> datetime:
    return d.replace(hour=0, minute=0, second=0, microsecond=0)


def _add_months(d: date, n: int) -> date:
    y, m = divmod(d.year * 12 + (d.month - 1) + n, 12)
    return date(y, m + 1, 1)


def _mk(tz, y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, 0, 0, 0, tzinfo=tz)


def _to_n(tok: str) -> Optional[int]:
    tok = tok.strip()
    if tok.isdigit():
        return int(tok)
    return _NUM_WORDS.get(tok)


def _find_all(mf: str, now_l: datetime, tz, tzn: str) -> List[Window]:
    out: List[Window] = []
    today0 = _day_start(now_l)

    def add(w: Window) -> None:
        out.append(w)

    # --- tarih (ISO) ---
    for m in re.finditer(r"(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)", mf):
        try:
            s = _mk(tz, int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return [None]  # type: ignore  # geçersiz tarih → belirsiz
        add(Window(s, s + timedelta(days=1), "day", m.group(0), tzn, m.group(0)))
    # --- gg.aa.yyyy / gg/aa/yyyy ---
    for m in re.finditer(r"(?<!\d)(\d{1,2})[./](\d{1,2})[./](\d{4})(?!\d)", mf):
        try:
            s = _mk(tz, int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return [None]  # type: ignore
        add(Window(s, s + timedelta(days=1), "day", m.group(0), tzn, m.group(0)))
    # --- ay adı + yıl ---
    for m in re.finditer(rf"(?<![a-z])({_MONTH_RE})(?:'?\w{{0,8}})?\s+(\d{{4}})(?!\d)|(?<!\d)(\d{{4}})\s+({_MONTH_RE})(?![a-z])", mf):
        mon_name = m.group(1) or m.group(4)
        year = int(m.group(2) or m.group(3))
        mon = _MONTHS[mon_name]
        s = _mk(tz, year, mon, 1)
        e_d = _add_months(date(year, mon, 1), 1)
        add(Window(s, _mk(tz, e_d.year, e_d.month, 1), "month", m.group(0), tzn, f"{year} {mon_name.capitalize()}"))
    # --- yıl ("2030 yılında") ---
    for m in re.finditer(r"(?<![\d.\-/])((?:19|20)\d{2})\s*(?:yil|yilinda|yilindaki|yili|senesinde)\b", mf):
        y = int(m.group(1))
        add(Window(_mk(tz, y, 1, 1), _mk(tz, y + 1, 1, 1), "year", m.group(0), tzn, f"{y} yılı"))

    # --- sabit sözcükler ---
    fixed = [
        (r"\bevvelsi\s+gun\b|\bonceki\s+gun\b|\bday\s+before\s+yesterday\b", "day", -2, "evvelsi gün"),
        (r"\bbugun(?:ku)?\b|\btoday\b", "today", 0, "bugün"),
        (r"\bdun(?:ku)?\b|\byesterday\b", "day", -1, "dün"),
    ]
    for rx, kind, off, nm in fixed:
        for m in re.finditer(rx, mf):
            if kind == "today":
                add(Window(today0, now_l, "day", m.group(0), tzn, "bugün"))
            else:
                s = today0 + timedelta(days=off)
                add(Window(s, s + timedelta(days=1), "day", m.group(0), tzn, nm))

    wk0 = today0 - timedelta(days=today0.weekday())
    for m in re.finditer(r"\bbu\s+hafta(?:ki)?\b|\bthis\s+week\b", mf):
        add(Window(wk0, now_l, "week", m.group(0), tzn, "bu hafta"))
    for m in re.finditer(r"\bgecen\s+hafta\b|\bgecen\s+haftaki\b|\bonceki\s+hafta\b|\blast\s+week\b", mf):
        add(Window(wk0 - timedelta(days=7), wk0, "week", m.group(0), tzn, "geçen hafta"))

    mo0 = _mk(tz, now_l.year, now_l.month, 1)
    for m in re.finditer(r"\bbu\s+ay(?:ki)?\b|\bthis\s+month\b", mf):
        add(Window(mo0, now_l, "month", m.group(0), tzn, "bu ay"))
    for m in re.finditer(r"\bgecen\s+ay(?:ki)?\b|\bonceki\s+ay\b|\blast\s+month\b", mf):
        p = _add_months(date(now_l.year, now_l.month, 1), -1)
        add(Window(_mk(tz, p.year, p.month, 1), mo0, "month", m.group(0), tzn, "geçen ay"))

    yr0 = _mk(tz, now_l.year, 1, 1)
    for m in re.finditer(r"\bbu\s+(?:yil|sene)(?:ki)?\b|\bthis\s+year\b", mf):
        add(Window(yr0, now_l, "year", m.group(0), tzn, "bu yıl"))
    for m in re.finditer(r"\bgecen\s+(?:yil|sene)(?:ki)?\b|\bonceki\s+yil\b|\blast\s+year\b", mf):
        add(Window(_mk(tz, now_l.year - 1, 1, 1), yr0, "year", m.group(0), tzn, "geçen yıl"))

    # --- kayan: son N birim / last N units / N birim içinde ---
    for m in re.finditer(rf"\b(?:son|last|past)\s+{_NUM}\s*({_UNIT_RE})(?:de|da|te|ta|lik|luk)?\b", mf):
        n = _to_n(m.group(1))
        unit = m.group(2)
        if not n:
            continue
        key, sec = _UNITS[unit]
        add(_rolling(now_l, n, key, sec, m.group(0), tzn, tz))
    for m in re.finditer(rf"\b{_NUM}\s*({_UNIT_RE})\s+(?:icinde|icerisinde)\b", mf):
        n = _to_n(m.group(1))
        if not n:
            continue
        key, sec = _UNITS[m.group(2)]
        add(_rolling(now_l, n, key, sec, m.group(0), tzn, tz))
    # --- N birim önce (takvim günü) ---
    for m in re.finditer(rf"\b{_NUM}\s*(gun|day|days)\s+(?:once|evvel|ago)\b", mf):
        n = _to_n(m.group(1))
        if n is None:
            continue
        s = today0 - timedelta(days=n)
        add(Window(s, s + timedelta(days=1), "ago", m.group(0), tzn, f"{n} gün önce"))
    return out


def _rolling(now_l: datetime, n: int, key: str, sec: int, expr: str, tzn: str, tz) -> Optional[Window]:
    if key in ("minute", "hour"):
        start = now_l - timedelta(seconds=n * sec)
    elif key == "day":
        if n > MAX_ROLLING_DAYS:
            return None  # type: ignore
        start = now_l - timedelta(days=n)
    elif key == "week":
        if n * 7 > MAX_ROLLING_DAYS:
            return None  # type: ignore
        start = now_l - timedelta(days=7 * n)
    elif key == "month":
        d = _add_months(date(now_l.year, now_l.month, 1), -n)
        if n * 30 > MAX_ROLLING_DAYS:
            return None  # type: ignore
        start = now_l.replace(year=d.year, month=d.month, day=min(now_l.day, _month_len(d.year, d.month)))
    else:  # year
        if n * 365 > MAX_ROLLING_DAYS:
            return None  # type: ignore
        y = now_l.year - n
        start = now_l.replace(year=y, day=min(now_l.day, _month_len(y, now_l.month)))
    unit_tr = {"minute": "dakika", "hour": "saat", "day": "gün", "week": "hafta", "month": "ay", "year": "yıl"}[key]
    return Window(start, now_l, "rolling", expr, tzn, f"son {n} {unit_tr}")


def _month_len(y: int, m: int) -> int:
    nxt = _add_months(date(y, m, 1), 1)
    return (nxt - date(y, m, 1)).days


def resolve(message: str, now: Optional[datetime] = None, tz: Optional[str] = None) -> Optional[Window]:
    """Mesajdaki TEK zaman ifadesini pencereye çevirir; yok/belirsiz → None."""
    if not message:
        return None
    zone, zname = _tz(tz)
    if now is None:
        from app.services.chat_quality import clock
        now = clock.now()
    now_l = _aware(now, zone)
    mf = fold(message)
    found = _find_all(mf, now_l, zone, zname)
    if any(w is None for w in found):
        return None
    ws: List[Window] = [w for w in found if w is not None]
    if not ws:
        return None
    # aynı pencereyi tarif eden tekrarlar (ör. "dün" iki kez) tek sayılır; farklı pencereler belirsiz
    uniq: List[Window] = []
    for w in ws:
        if not any(u.start == w.start and u.end == w.end for u in uniq):
            uniq.append(w)
    # "bugün" + "son 24 saat" gibi iç içe ifade yok sayılmaz: farklıysa belirsiz
    if len(uniq) > 1:
        return None
    return uniq[0]


def configured_tz() -> str:
    try:
        from app.services import runtime_settings
        return runtime_settings.get_str("chat_timezone") or DEFAULT_TZ
    except Exception:
        return DEFAULT_TZ


def resolve_for_chat(message: str) -> Optional[Window]:
    """Sohbet yolu girişi: saat = clock.now() (now_override destekli), tz = ayar."""
    try:
        return resolve(message, tz=configured_tz())
    except Exception:
        return None


# ── veri saklama (retention) yardımcıları (saf) ────────────────────────────────────────

def retention_status(window: Window, earliest: Optional[datetime], now: datetime) -> str:
    """`outside` (pencere tamamen kayıt kapsamından ESKİ ya da en eski kayıttan önce), `partial`, `covered`."""
    if earliest is None:
        return "covered"
    e = _aware(earliest, window.start.tzinfo)
    if window.end <= e:
        return "outside"
    if window.start < e:
        return "partial"
    return "covered"


def no_data_text(window: Window, source_label: str, earliest: Optional[datetime], *, earliest_is_policy: bool = False,
                 future: bool = False) -> str:
    """Pencere kayıt kapsamı dışında: «veri yok + kapsam»; «olmadı» DENMEZ."""
    if earliest is not None:
        e = _aware(earliest, window.start.tzinfo)
        cov = (f"{source_label} kayıtları en eski **{e:%Y-%m-%d %H:%M}** ({window.tz_name}) tarihinden başlıyor"
               + (" (yapılandırılmış saklama sınırı)" if earliest_is_policy else ""))
    else:
        cov = f"{source_label} için kayıt kapsamı bu pencereyi içermiyor"
    tail = ("Bu pencere henüz yaşanmadı (gelecekte); olay kaydı olamaz."
            if future else
            "Bu, o dönemde olay olmadığı anlamına gelmez — yalnızca kayıt tutulmuyor/saklanmıyor.")
    return (
        f"**Bu pencere için veri yok:** {window.title}.\n\n"
        f"{cov}; bu nedenle istenen dönem hakkında bilgi veremem. {tail}"
    )


def partial_note(window: Window, source_label: str, earliest: datetime) -> str:
    e = _aware(earliest, window.start.tzinfo)
    return (f"_Not: pencerenin ilk kısmı ({window.start:%Y-%m-%d %H:%M} – {e:%Y-%m-%d %H:%M}) {source_label} "
            "kayıt kapsamı dışında; sonuçlar eksik olabilir._")
