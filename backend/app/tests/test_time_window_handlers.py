"""Adım 5c — zaman penceresi ↔ QA handler'ları. vCenter / DB sahte; saat sabit."""
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.services import hypervisor_intelligence as hi
from app.services import vcenter_vm_lifecycle as lc
from app.services.chat_quality import clock, time_window as tw

Z = tw._tz("Europe/Istanbul")[0]
NOW = datetime(2026, 10, 15, 14, 30, tzinfo=Z)


def utc(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=timezone.utc).isoformat()


def local(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=Z).astimezone(timezone.utc).isoformat()


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: NOW)
    from app.services import runtime_settings as rs
    real_str, real_int = rs.get_str, rs.get_int
    monkeypatch.setattr(rs, "get_str", lambda k: "Europe/Istanbul" if k == "chat_timezone" else real_str(k))
    monkeypatch.setattr(rs, "get_int", lambda k: 30 if k == "virt_live_event_retention_days" else real_int(k))


class FakeClient:
    def __init__(self, events):
        self.events = events
        self.days = None

    def query_lifecycle_events(self, ids, days=7, max_events=3000, **kw):
        self.days = days
        return {"events": [dict(e) for e in self.events], "errors": []}


def patch_vcenter(monkeypatch, events):
    client = FakeClient(events)
    monkeypatch.setattr(lc, "_vmware_hypervisors", lambda db: [SimpleNamespace(name="vc1")])
    monkeypatch.setattr(lc, "_build_client", lambda hv: client)
    return client


def fake_db():
    db = MagicMock()
    db.query.return_value.filter.return_value.all.return_value = []
    return db


def ev(vm, typ, ts):
    return {"vm_ref": None, "title": f"{vm} x", "vm_name": vm, "event_type_id": typ, "timestamp": ts}


def restart_pair(vm, off_ts, on_ts):
    return [ev(vm, "VmPoweredOffEvent", off_ts), ev(vm, "VmPoweredOnEvent", on_ts)]


# ── pencere: yalnızca [start, end) olayları ───────────────────────────────────────────────

def test_restart_yesterday_filters_to_yesterday(monkeypatch):
    events = (
        restart_pair("vm-in", local(2026, 10, 14, 10), local(2026, 10, 14, 10, 5))
        + restart_pair("vm-today", local(2026, 10, 15, 1), local(2026, 10, 15, 1, 5))      # bugün → dışarıda
        + restart_pair("vm-old", local(2026, 10, 13, 10), local(2026, 10, 13, 10, 5))      # evvelsi gün → dışarıda
        + restart_pair("vm-edge", local(2026, 10, 14, 23, 58), local(2026, 10, 15, 0, 1))  # off dünde, on bugün → çift yok
    )
    client = patch_vcenter(monkeypatch, events)
    out = hi.h_restart_week(fake_db(), "Dün kaç VM yeniden başladı?")
    assert "2026-10-14 00:00 – 2026-10-15 00:00 (Europe/Istanbul)" in out
    assert "vm-in" in out and "vm-today" not in out and "vm-old" not in out
    assert "**Toplam restart olayı:** 1 | **Etkilenen VM sayısı:** 1" in out
    assert client.days == 2   # dünün başına yetecek kadar geriye bak


def test_rule_routes_yeniden_basladi_to_restart_not_count(monkeypatch):
    patch_vcenter(monkeypatch, restart_pair("vm-in", local(2026, 10, 14, 10), local(2026, 10, 14, 10, 5)))
    # DB'ye dokunan başka kural çalışmasın: h_count_vms'e düşerse "VM sayısı" olur
    out = hi.try_deterministic_answer(fake_db(), "Dün kaç VM yeniden başladı?")
    assert out and "Restart Edilen VM" in out and "2026-10-14" in out


def test_no_window_keeps_old_title(monkeypatch):
    patch_vcenter(monkeypatch, [])
    out = hi.h_restart_week(fake_db(), "restart edilen vm sayısı")
    assert out.startswith("### Son 7 Günde Restart Edilen VM'ler")
    assert "Europe/Istanbul" not in out


def test_last_week_window(monkeypatch):
    events = (
        restart_pair("vm-lw", local(2026, 10, 7, 9), local(2026, 10, 7, 9, 2))
        + restart_pair("vm-this", local(2026, 10, 13, 9), local(2026, 10, 13, 9, 2))   # bu hafta → dışarıda
    )
    patch_vcenter(monkeypatch, events)
    out = hi.h_restart_week(fake_db(), "geçen hafta restart edilen VM'ler")
    assert "2026-10-05 00:00 – 2026-10-12 00:00" in out
    assert "vm-lw" in out and "vm-this" not in out


def test_last_24h_rolling_excludes_older(monkeypatch):
    events = (
        restart_pair("vm-new", local(2026, 10, 15, 8), local(2026, 10, 15, 8, 1))
        + restart_pair("vm-30h", local(2026, 10, 14, 8), local(2026, 10, 14, 8, 1))
    )
    patch_vcenter(monkeypatch, events)
    out = hi.h_toggle_24h(fake_db(), "son 24 saatte kapanıp açılan VM'ler")
    assert "vm-new" in out and "vm-30h" not in out


def test_boundary_inclusive_start_exclusive_end(monkeypatch):
    events = [
        ev("vm-a", "VmResettingEvent", local(2026, 10, 14, 0, 0)),     # start dahil
        ev("vm-b", "VmResettingEvent", local(2026, 10, 15, 0, 0)),     # end hariç
    ]
    patch_vcenter(monkeypatch, events)
    out = hi.h_restart_week(fake_db(), "dün restart")
    assert "vm-a" in out and "vm-b" not in out


# ── saklama dışı / gelecek: «veri yok + kapsam» ───────────────────────────────────────────

def test_live_retention_outside(monkeypatch):
    client = patch_vcenter(monkeypatch, [])
    out = hi.h_removed_30d(fake_db(), "Geçen yıl hangi VM'ler silindi?")
    assert "Bu pencere için veri yok" in out
    assert "2025-01-01 00:00 – 2026-01-01 00:00" in out
    assert "2026-09-15" in out                    # en eski kapsam = şimdi − 30 gün
    assert "olmadığı anlamına gelmez" in out
    assert client.days is None                    # vCenter'a hiç sorulmadı


def test_future_window_says_future(monkeypatch):
    patch_vcenter(monkeypatch, [])
    out = hi.h_removed_30d(fake_db(), "2030 Ocak ayında hangi VM'ler silindi?")
    assert "Bu pencere için veri yok" in out and "gelecekte" in out and "2030-01-01" in out


def test_partial_window_adds_note(monkeypatch):
    patch_vcenter(monkeypatch, [])
    out = hi.h_restart_report_30d(fake_db(), "son 90 gün restart raporu")
    assert "eksik olabilir" in out


def test_no_window_unchanged_for_30d_default(monkeypatch):
    patch_vcenter(monkeypatch, [])
    out = hi.h_restart_report_30d(fake_db(), "restart raporu")
    assert out.startswith("### Son 30 Gün VM Restart Raporu")
    assert "eksik olabilir" not in out


# ── system_events (DB) handler'ları: tz'li since/until ────────────────────────────────────

class DbRec:
    def __init__(self, earliest, rows=()):
        self.calls = []
        self.earliest = earliest
        self.rows = list(rows)

    def execute(self, stmt, params=None):
        sql = str(stmt)
        self.calls.append((sql, params))
        res = MagicMock()
        if "min(created_at)" in sql:
            res.scalar.return_value = self.earliest
        else:
            res.all.return_value = self.rows
        return res


def test_db_handler_passes_window_params():
    db = DbRec(earliest=datetime(2026, 8, 14, tzinfo=Z))
    out = hi.h_critical_alarms_24h(db, "dün kritik alarm")
    sql, params = db.calls[-1]
    assert params["since"] == datetime(2026, 10, 14, tzinfo=Z)
    assert params["until"] == datetime(2026, 10, 15, tzinfo=Z)
    assert "created_at < CAST(:until" in sql
    assert "Kritik Alarmlar — Dün: 2026-10-14 00:00 – 2026-10-15 00:00" in out


def test_db_handler_no_window_has_null_until():
    db = DbRec(earliest=datetime(2026, 8, 14, tzinfo=Z))
    out = hi.h_critical_alarms_24h(db, "kritik alarm var mı")
    _sql, params = db.calls[-1]
    assert params["until"] is None
    assert out.startswith("### Son 24 Saatte Oluşan Kritik Alarmlar")


def test_db_handler_before_earliest_record():
    db = DbRec(earliest=datetime(2026, 8, 14, 0, 4, tzinfo=Z))
    out = hi.h_storage_alarms_30d(db, "2025 yılında storage alarmları")
    assert "Bu pencere için veri yok" in out and "2026-08-14 00:04" in out
    assert all("system_events\n" not in c[0] or "min(created_at)" in c[0] for c in db.calls)  # alarm sorgusu çalışmadı


def test_db_handler_partial_before_earliest():
    db = DbRec(earliest=datetime(2026, 8, 14, tzinfo=Z))
    out = hi.h_alarm_trend(db, "son 90 günde alarm trendi")
    assert "eksik olabilir" in out


def test_vm_most_alarms_window():
    db = DbRec(earliest=datetime(2026, 8, 14, tzinfo=Z), rows=[SimpleNamespace(name="vmx", cnt=3)])
    out = hi.h_vm_most_alarms_7d(db, "geçen hafta en çok alarm üreten VM")
    _sql, params = db.calls[-1]
    assert params["since"] == datetime(2026, 10, 5, tzinfo=Z) and params["until"] == datetime(2026, 10, 12, tzinfo=Z)
    assert "vmx" in out and "2026-10-05" in out


# ── gerçek bir bozuk-soru: ifade çözülemezse eski yol ─────────────────────────────────────

def test_ambiguous_expression_uses_legacy_days(monkeypatch):
    patch_vcenter(monkeypatch, [])
    out = hi.h_restart_week(fake_db(), "dün ve bugün restart")
    assert "Europe/Istanbul" not in out  # belirsiz → pencere yazılmaz (eski davranış)


def test_rule_routes_hangi_vm_silindi_to_removed(monkeypatch):
    client = patch_vcenter(monkeypatch, [])
    out = hi.try_deterministic_answer(fake_db(), "Geçen yıl hangi VM'ler silindi?")
    assert out and "Bu pencere için veri yok" in out
    assert client.days is None


def test_rule_snapshot_silindi_not_hijacked(monkeypatch):
    patch_vcenter(monkeypatch, [])
    # snapshot silme sorusu olay-arama kuralına gitmeli, h_removed_30d'ye değil
    out = hi.try_deterministic_answer(fake_db(), "hangi VM'lerin snapshot'ı silindi")
    assert not out or "Silinen / Envanterden" not in out


def test_rule_kapandi_not_counted_as_total_vm(monkeypatch):
    out = hi.try_deterministic_answer(fake_db(), "Dün kaç VM kapandı?")
    assert not out or "VM Sayısı" not in out


# ── kaynak hatası dürüstlüğü (IH5 bulgusu: vCenter ulaşılamaz → pencere/kapsam/durum yazılmalı) ──────────

class MixedClient:
    """İlk vCenter yanıt verir, ikincisi hata fırlatır."""
    def __init__(self, events, fail):
        self.events, self.fail = events, fail

    def query_lifecycle_events(self, ids, days=7, max_events=3000, **kw):
        if self.fail:
            raise RuntimeError("SOAP oturumu açılamadı")
        return {"events": [dict(e) for e in self.events], "errors": []}


def patch_two_vcenters(monkeypatch, events, fail_second=True, fail_first=False):
    hvs = [SimpleNamespace(name="office"), SimpleNamespace(name="ZZ-FAKE-vCenter")]
    clients = {"office": MixedClient(events, fail_first), "ZZ-FAKE-vCenter": MixedClient([], fail_second)}
    monkeypatch.setattr(lc, "_vmware_hypervisors", lambda db: hvs)
    monkeypatch.setattr(lc, "_build_client", lambda hv: clients[hv.name])


def test_partial_failure_keeps_window_result_and_states_unreachable(monkeypatch):
    patch_two_vcenters(monkeypatch, [])
    out = hi.h_restart_week(fake_db(), "Dün kaç VM yeniden başladı?")
    assert "2026-10-14 00:00 – 2026-10-15 00:00 (Europe/Istanbul)" in out        # pencere cevapta
    assert "restart tespit edilmedi" in out                                       # erişilebilen kaynak: olay yok
    assert "Kaynak durumu" in out and "ZZ-FAKE-vCenter" in out and "bilinmiyor" in out
    assert "yalnız VMware (vCenter) olayları" in out                              # kapsam sınırı
    assert "Ortam bağlantısı varsa" not in out


def test_total_failure_states_window_and_unknown(monkeypatch):
    patch_two_vcenters(monkeypatch, [], fail_first=True)
    out = hi.h_restart_week(fake_db(), "Dün kaç VM yeniden başladı?")
    assert "2026-10-14 00:00 – 2026-10-15 00:00" in out
    assert "hiçbir vCenter kaynağına ulaşılamadı" in out and "bilinmiyor" in out
    assert "Ortam bağlantısı varsa" not in out


def test_partial_failure_with_events_still_lists_them(monkeypatch):
    patch_two_vcenters(monkeypatch, restart_pair("vm-in", local(2026, 10, 14, 10), local(2026, 10, 14, 10, 5)))
    out = hi.h_restart_week(fake_db(), "Dün kaç VM yeniden başladı?")
    assert "vm-in" in out and "**Toplam restart olayı:** 1" in out and "Kaynak durumu" in out


def test_no_errors_no_source_note_for_created(monkeypatch):
    patch_vcenter(monkeypatch, [])
    out = hi.h_created_30d(fake_db(), "son 30 günde oluşturulan VM'ler")
    assert "Kaynak durumu" not in out
