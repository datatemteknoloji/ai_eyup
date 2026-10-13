"""Adım 7d — zaman penceresi (dün/bugün/bu hafta) tek kaynak: resolve_time_window."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from app.services.llm_chat_policy import (
    entity_latest_no_window,
    forced_window_iso,
    resolve_time_window,
    time_window_assumption_text,
)


TZ = ZoneInfo("Europe/Istanbul")
NOW = datetime(2026, 10, 12, 0, 45, tzinfo=TZ)


def test_dun_bugun_hafta_same_source():
    dun = resolve_time_window("Dünkü sorun neydi?", NOW)
    assert dun and dun["force"]
    assert dun["start"].date().isoformat() == "2026-10-11"
    assert dun["end"].date().isoformat() == "2026-10-12"
    fw = forced_window_iso(dun)
    assert fw and fw[0].startswith("2026-10-10T21:00:00")  # UTC = TR-3

    bugun = resolve_time_window("Bugün hata veren job'lar", NOW)
    assert bugun["start"].date().isoformat() == "2026-10-12"

    hafta = resolve_time_window("Bu hafta en çok hata verenler", NOW)
    # 2026-10-12 Pazartesi → ISO hafta başlangıcı bugün
    assert hafta["start"].date().isoformat() == "2026-10-12"

    gecen = resolve_time_window("Geçen hafta da hata vermiş mi?", NOW)
    assert gecen["start"].date().isoformat() == "2026-10-05"

    # Tüm yollar aynı sonuç (varsayım metni + force)
    assert "2026-10-11" in time_window_assumption_text(dun)


def test_entity_latest_skips_default_window():
    assert entity_latest_no_window("JOBS.DWH.SYNC.01 neden hata verdi?")
    assert entity_latest_no_window("JOBS.RISK.YEDEK.03 hiç hata vermedi değil mi?")
    assert entity_latest_no_window("JOBS.ADV ile başlayan job'ların son çalışmalarının raporlarını özetle")
    assert not entity_latest_no_window("JOBS.DWH.SYNC.01 dün neden hata verdi?")
    assert not entity_latest_no_window("En çok hata veren 5 job")
