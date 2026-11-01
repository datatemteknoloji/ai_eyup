"""Adım 5c — zaman penceresi çözümleyici (saf) testleri. Sabit `now` + sabit TZ."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.chat_quality import time_window as tw

TZ = "Europe/Istanbul"
Z = tw._tz(TZ)[0]
# Perşembe 2026-10-15 14:30 (İstanbul)
NOW = datetime(2026, 10, 15, 14, 30, tzinfo=Z)


def R(msg, now=NOW, tz=TZ):
    return tw.resolve(msg, now=now, tz=tz)


def D(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=Z)


CASES = [
    # (mesaj, başlangıç, bitiş, tür)
    ("Dün kaç VM yeniden başladı?", D(2026, 10, 14), D(2026, 10, 15), "day"),
    ("DÜN neler oldu", D(2026, 10, 14), D(2026, 10, 15), "day"),
    ("yesterday restart report", D(2026, 10, 14), D(2026, 10, 15), "day"),
    ("Bugün kritik alarm var mı?", D(2026, 10, 15), NOW, "day"),
    ("today alarms", D(2026, 10, 15), NOW, "day"),
    ("bugünkü alarmlar", D(2026, 10, 15), NOW, "day"),
    ("dünkü olaylar", D(2026, 10, 14), D(2026, 10, 15), "day"),
    ("evvelsi gün ne oldu", D(2026, 10, 13), D(2026, 10, 14), "day"),
    ("önceki gün migration", D(2026, 10, 13), D(2026, 10, 14), "day"),
    ("bu hafta restart", D(2026, 10, 12), NOW, "week"),
    ("this week restarts", D(2026, 10, 12), NOW, "week"),
    ("bu haftaki alarmlar", D(2026, 10, 12), NOW, "week"),
    ("geçen hafta restart olan VM'ler", D(2026, 10, 5), D(2026, 10, 12), "week"),
    ("last week alarms", D(2026, 10, 5), D(2026, 10, 12), "week"),
    ("önceki hafta", D(2026, 10, 5), D(2026, 10, 12), "week"),
    ("bu ay kaç VM açıldı", D(2026, 10, 1), NOW, "month"),
    ("this month events", D(2026, 10, 1), NOW, "month"),
    ("geçen ay silinen VM'ler", D(2026, 9, 1), D(2026, 10, 1), "month"),
    ("last month removed VMs", D(2026, 9, 1), D(2026, 10, 1), "month"),
    ("bu yıl oluşturulan VM", D(2026, 1, 1), NOW, "year"),
    ("this year created", D(2026, 1, 1), NOW, "year"),
    ("geçen yıl silinen VM", D(2025, 1, 1), D(2026, 1, 1), "year"),
    ("last year removed", D(2025, 1, 1), D(2026, 1, 1), "year"),
    ("geçen sene", D(2025, 1, 1), D(2026, 1, 1), "year"),
    ("son 24 saat kritik alarm", NOW - timedelta(hours=24), NOW, "rolling"),
    ("son 6 saat", NOW - timedelta(hours=6), NOW, "rolling"),
    ("son 90 dakika", NOW - timedelta(minutes=90), NOW, "rolling"),
    ("son 3 gün", NOW - timedelta(days=3), NOW, "rolling"),
    ("son 15 gün içinde", NOW - timedelta(days=15), NOW, "rolling"),
    ("son 24 saatte kritik alarm", NOW - timedelta(hours=24), NOW, "rolling"),
    ("son 90 günde restart", NOW - timedelta(days=90), NOW, "rolling"),
    ("son 3 aylık trend", D(2026, 7, 15, 14, 30), NOW, "rolling"),
    ("son 2 haftada", NOW - timedelta(days=14), NOW, "rolling"),
    ("son bir hafta", NOW - timedelta(days=7), NOW, "rolling"),
    ("son iki hafta", NOW - timedelta(days=14), NOW, "rolling"),
    ("son 2 hafta", NOW - timedelta(days=14), NOW, "rolling"),
    ("son 30 gün restart", NOW - timedelta(days=30), NOW, "rolling"),
    ("son 3 ay", D(2026, 7, 15, 14, 30), NOW, "rolling"),
    ("son bir yıl", D(2025, 10, 15, 14, 30), NOW, "rolling"),
    ("last 7 days", NOW - timedelta(days=7), NOW, "rolling"),
    ("last 48 hours", NOW - timedelta(hours=48), NOW, "rolling"),
    ("last two weeks", NOW - timedelta(days=14), NOW, "rolling"),
    ("3 gün içinde", NOW - timedelta(days=3), NOW, "rolling"),
    ("2 gün önce ne oldu", D(2026, 10, 13), D(2026, 10, 14), "ago"),
    ("5 gün önce", D(2026, 10, 10), D(2026, 10, 11), "ago"),
    ("3 days ago", D(2026, 10, 12), D(2026, 10, 13), "ago"),
    ("2026-10-14 tarihinde", D(2026, 10, 14), D(2026, 10, 15), "day"),
    ("14.10.2026 günü ne oldu", D(2026, 10, 14), D(2026, 10, 15), "day"),
    ("1/9/2026 olayları", D(2026, 9, 1), D(2026, 9, 2), "day"),
    ("2030 Ocak ayında hangi VM'ler silindi?", D(2030, 1, 1), D(2030, 2, 1), "month"),
    ("Ocak 2030 alarmları", D(2030, 1, 1), D(2030, 2, 1), "month"),
    ("Eylül 2026 restart", D(2026, 9, 1), D(2026, 10, 1), "month"),
    ("December 2025 events", D(2025, 12, 1), D(2026, 1, 1), "month"),
    ("Aralık 2025", D(2025, 12, 1), D(2026, 1, 1), "month"),
    ("2024 yılında silinen VM'ler", D(2024, 1, 1), D(2025, 1, 1), "year"),
    ("2019 yılındaki olaylar", D(2019, 1, 1), D(2020, 1, 1), "year"),
]


@pytest.mark.parametrize("msg,start,end,kind", CASES)
def test_expressions(msg, start, end, kind):
    w = R(msg)
    assert w is not None, msg
    assert (w.start, w.end) == (start, end), (msg, w.start, w.end)
    assert w.kind == kind


NONE_CASES = [
    "kaç VM var",
    "Dün ve bugün alarm",              # iki farklı ifade → belirsiz
    "geçen hafta mı bu hafta mı",
    "son 99999 gün",                   # üst sınır
    "31.02.2026 olayları",             # geçersiz tarih
    "2026-13-45",
    "",
    "Ekim ayında restart",             # yıl yok → belirsiz
    "son hafta",                       # sayısız rolling: belirsiz
    "bu ayki restart ve geçen ayki",
    "son 0 gün",
]


@pytest.mark.parametrize("msg", NONE_CASES)
def test_none_or_ambiguous(msg):
    assert R(msg) is None, msg


def test_same_expression_twice_is_fine():
    assert R("dün dün restart") is not None


def test_week_starts_monday_on_monday():
    mon = datetime(2026, 10, 12, 9, 0, tzinfo=Z)
    w = R("bu hafta", now=mon)
    assert w.start == D(2026, 10, 12) and w.end == mon
    w = R("geçen hafta", now=mon)
    assert (w.start, w.end) == (D(2026, 10, 5), D(2026, 10, 12))


def test_week_on_sunday():
    sun = datetime(2026, 10, 18, 23, 0, tzinfo=Z)
    w = R("bu hafta", now=sun)
    assert w.start == D(2026, 10, 12)


def test_last_month_across_year_boundary():
    jan = datetime(2027, 1, 10, 12, 0, tzinfo=Z)
    w = R("geçen ay", now=jan)
    assert (w.start, w.end) == (D(2026, 12, 1), D(2027, 1, 1))
    w = R("son 2 ay", now=jan)
    assert w.start == datetime(2026, 11, 10, 12, 0, tzinfo=Z)


def test_month_clamp_rolling():
    m31 = datetime(2026, 3, 31, 10, 0, tzinfo=Z)
    w = R("son 1 ay", now=m31)
    assert w.start == datetime(2026, 2, 28, 10, 0, tzinfo=Z)


def test_leap_year_month_window():
    w = R("Şubat 2028 alarmları", now=NOW)
    assert (w.start, w.end) == (D(2028, 2, 1), D(2028, 3, 1))


def test_naive_now_is_local_and_converted():
    # naif now = konteyner yerel saati; Istanbul'a çevrilir (gün sınırı kayması olmamalı: ikisi de +03)
    naive = datetime(2026, 10, 15, 14, 30)
    other = tw.resolve("dün", now=naive, tz="UTC")
    assert other is not None and other.tz_name == "UTC"


def test_tz_changes_day_boundary():
    # 23:30 UTC 14 Ekim = 02:30 İstanbul 15 Ekim
    now = datetime(2026, 10, 14, 23, 30, tzinfo=timezone.utc)
    ist = tw.resolve("dün", now=now, tz="Europe/Istanbul")
    utc = tw.resolve("dün", now=now, tz="UTC")
    assert ist.start == D(2026, 10, 14)
    assert utc.start == datetime(2026, 10, 13, tzinfo=timezone.utc)


def test_label_and_title():
    w = R("dün")
    assert w.label == "2026-10-14 00:00 – 2026-10-15 00:00 (Europe/Istanbul)"
    assert w.title.startswith("Dün: 2026-10-14")


def test_days_back():
    assert R("dün").days_back(NOW) == 2
    assert R("son 24 saat").days_back(NOW) == 1
    assert R("geçen hafta").days_back(NOW) == 11
    assert R("bugün").days_back(NOW) == 1


def test_utc_range():
    s, e = R("dün").utc_range()
    assert s == datetime(2026, 10, 13, 21, 0, tzinfo=timezone.utc)
    assert e == datetime(2026, 10, 14, 21, 0, tzinfo=timezone.utc)


def test_contains_half_open():
    w = R("dün")
    assert w.contains(D(2026, 10, 14))
    assert w.contains(D(2026, 10, 14, 23, 59))
    assert not w.contains(D(2026, 10, 15))
    assert not w.contains(D(2026, 10, 13, 23, 59))


def test_now_override_via_clock(monkeypatch):
    from app.services.chat_quality import clock
    monkeypatch.setattr(clock, "now", lambda: datetime(2030, 1, 5, 10, 0, tzinfo=Z))
    w = tw.resolve("dün", tz=TZ)
    assert w.start == D(2030, 1, 4)


def test_retention_status():
    w = R("geçen yıl")
    assert tw.retention_status(w, D(2026, 8, 14), NOW) == "outside"
    w = R("son 90 gün")
    assert tw.retention_status(w, D(2026, 8, 14), NOW) == "partial"
    w = R("dün")
    assert tw.retention_status(w, D(2026, 8, 14), NOW) == "covered"
    assert tw.retention_status(w, None, NOW) == "covered"


def test_no_data_text_mentions_earliest_and_not_absence():
    w = R("2030 Ocak")
    t = tw.no_data_text(w, "Olay (system_events)", D(2026, 8, 14))
    assert "Bu pencere için veri yok" in t and "2026-08-14" in t
    assert "olmadığı anlamına gelmez" in t
    t2 = tw.no_data_text(w, "vCenter olayı", None)
    assert "kayıt kapsamı" in t2


def test_partial_note():
    w = R("son 90 gün")
    assert "eksik" in tw.partial_note(w, "Olay", D(2026, 8, 14))


def test_resolve_never_raises_on_garbage():
    for s in ["\x00\x01", "🙂" * 50, "son " * 200, "9999-99-99", "00.00.0000"]:
        R(s)
