"""Adım 5a — kanonik güç durumu sınıflandırması (saf fonksiyonlar; DB gerekmez)."""
from __future__ import annotations

import pytest

from app.services.chat_quality import power_state as ps

# Canlı DB'de görülen ham değerler (2026-10-15) — hiçbiri `unknown`'a düşmemeli
DB_RAW_VALUES = {
    "poweredOn": ps.ON, "POWERED_ON": ps.ON, "POWERED_OFF": ps.OFF, "Running": ps.ON, "Stopped": ps.OFF,
}

CASES = [
    # VMware
    ("poweredOn", ps.ON), ("poweredOff", ps.OFF), ("suspended", ps.SUSPENDED), ("POWERED_ON", ps.ON),
    ("POWERED_OFF", ps.OFF), ("SUSPENDED", ps.SUSPENDED), ("powered on", ps.ON), ("Powered-Off", ps.OFF),
    ("poweredon", ps.ON), ("  poweredOn  ", ps.ON),
    # KubeVirt
    ("Running", ps.ON), ("Stopped", ps.OFF), ("Paused", ps.TRANSITIONAL), ("Starting", ps.TRANSITIONAL),
    ("Migrating", ps.TRANSITIONAL), ("Provisioning", ps.TRANSITIONAL), ("Terminating", ps.TRANSITIONAL),
    ("ErrorUnschedulable", ps.TRANSITIONAL), ("CrashLoopBackOff", ps.TRANSITIONAL), ("Stopping", ps.TRANSITIONAL),
    # oVirt / KVM
    ("up", ps.ON), ("UP", ps.ON), ("down", ps.OFF), ("DOWN", ps.OFF), ("powering_up", ps.TRANSITIONAL),
    ("powering_down", ps.TRANSITIONAL), ("reboot_in_progress", ps.TRANSITIONAL), ("wait_for_launch", ps.TRANSITIONAL),
    ("image_locked", ps.TRANSITIONAL), ("not_responding", ps.TRANSITIONAL), ("suspended", ps.SUSPENDED),
    # Proxmox / Hyper-V
    ("running", ps.ON), ("stopped", ps.OFF), ("Off", ps.OFF), ("Saved", ps.SUSPENDED), ("Paused", ps.TRANSITIONAL),
    # boş / bilinmeyen
    (None, ps.UNKNOWN), ("", ps.UNKNOWN), ("   ", ps.UNKNOWN), ("unknown", ps.UNKNOWN), ("Unknown", ps.UNKNOWN),
    ("weird_state", ps.UNKNOWN), ("XYZ", ps.UNKNOWN),
    # bench truth ile uyum
    ("on", ps.ON), ("active", ps.ON), ("shutoff", ps.OFF), ("shut off", ps.OFF), ("halted", ps.OFF),
]


@pytest.mark.parametrize("raw,expected", CASES)
def test_classify(raw, expected):
    assert ps.classify(raw) == expected


def test_case_count_at_least_40():
    assert len(CASES) >= 40


def test_db_values_never_unknown():
    for raw, exp in DB_RAW_VALUES.items():
        assert ps.classify(raw) == exp
        assert ps.classify(raw) != ps.UNKNOWN


def test_stopped_is_off_not_other():
    # 5a ana hata: Stopped (KubeVirt) "Diğer/bilinmeyen" sayılıyordu
    assert ps.is_off("Stopped")
    assert not ps.is_on("Stopped")


def test_running_capitalized_is_on():
    # report_engine büyük harfli Running'i tanımıyordu
    assert ps.is_on("Running")
    assert ps.is_on("running")


def test_unrecognized_not_silently_off_or_on():
    for raw in ("weird_state", "Paused", None, ""):
        assert not ps.is_on(raw)
        assert not ps.is_off(raw)


def test_suspend_prefix():
    assert ps.is_suspended("suspendedByUser")
    assert ps.is_suspended("SUSPENDED")


def test_is_recognized():
    assert ps.is_recognized("poweredOn")
    assert ps.is_recognized("Paused")
    assert ps.is_recognized(None)
    assert not ps.is_recognized("weird_state")


def test_summarize_counts_and_other_raw():
    raws = ["poweredOn"] * 3 + ["POWERED_OFF"] * 2 + ["Stopped"] * 4 + ["Running"] * 5 + ["suspended"] + ["Paused"] * 2 + ["X", None]
    s = ps.summarize(raws)
    assert s["total"] == len(raws)
    assert s["on"] == 8 and s["off"] == 6 and s["suspended"] == 1
    assert s["transitional"] == 2 and s["unknown"] == 2
    assert s["on"] + s["off"] + s["suspended"] + s["transitional"] + s["unknown"] == s["total"]
    assert s["other_raw"] == {"Paused": 2, "X": 1, "(boş)": 1}


def test_summarize_live_distribution():
    # canlı dağılım (2026-10-15): açık 1466, kapalı 86, diğer 0
    raws = ["poweredOn"] * 1000 + ["POWERED_ON"] * 18 + ["POWERED_OFF"] * 29 + ["Running"] * 448 + ["Stopped"] * 57
    s = ps.summarize(raws)
    assert (s["total"], s["on"], s["off"], s["suspended"], s["transitional"], s["unknown"]) == (1552, 1466, 86, 0, 0, 0)
    assert s["other_raw"] == {}


def test_other_note_formatting_and_cap():
    assert ps.other_note({"Paused": 2, "X": 1}) == "Paused:2, X:1"
    many = {f"v{i}": 1 for i in range(9)}
    note = ps.other_note(many, max_items=3)
    assert note.endswith("+6 değer daha") and note.count(":") == 3


def test_empty_summary():
    s = ps.summarize([])
    assert s["total"] == 0 and s["other_raw"] == {}


def test_normalize_key_variants_equal():
    keys = {ps.normalize_key(x) for x in ("POWERED_ON", "poweredOn", "powered on", "Powered-On", "powered.on")}
    assert keys == {"poweredon"}


def test_labels():
    assert ps.label_tr(ps.OFF) == "kapalı"
    assert ps.pstate_label(None) == "-"
    assert ps.pstate_label(" Stopped ") == "Stopped"


# ── hypervisor_intelligence entegrasyonu (DB yok: _get_vms taklidi) ─────────────────────────────

def _fake_vms(states):
    return [{"name": f"vm{i}", "power_state": s, "host": "h", "cluster": "c", "hypervisor_id": 1, "last_sync": None}
            for i, s in enumerate(states)]


def test_h_count_vms_stopped_is_off_and_no_other_row(monkeypatch):
    from app.services import hypervisor_intelligence as hi
    states = ["poweredOn"] * 2 + ["Running"] * 3 + ["POWERED_OFF"] * 1 + ["Stopped"] * 4
    monkeypatch.setattr(hi, "_get_vms", lambda db, hypervisor_id=None: _fake_vms(states))
    out = hi.h_count_vms(None, "kaç vm var")
    assert "**Toplam VM:** 10" in out
    assert "Çalışan (powered on): **5**" in out
    assert "Kapalı (powered off): **5**" in out
    assert "Diğer/bilinmeyen" not in out


def test_h_count_vms_other_lists_raw_values(monkeypatch):
    from app.services import hypervisor_intelligence as hi
    states = ["poweredOn", "Paused", "Paused", "weird", None]
    monkeypatch.setattr(hi, "_get_vms", lambda db, hypervisor_id=None: _fake_vms(states))
    out = hi.h_count_vms(None, "kaç vm var")
    assert "Diğer/bilinmeyen power state: **4** (Paused:2, (boş):1, weird:1)" in out


def test_powered_off_and_on_handlers_use_canonical(monkeypatch):
    from app.services import hypervisor_intelligence as hi
    states = ["Running", "Stopped", "Stopped", "poweredOff"]
    monkeypatch.setattr(hi, "_get_vms", lambda db, hypervisor_id=None: _fake_vms(states))
    assert "**1** VM çalışıyor" in hi.h_count_powered_on(None, "")
    assert hi._is_off({"power_state": "Stopped"}) and hi._is_on({"power_state": "Running"})
    assert not hi._is_suspended({"power_state": "Paused"})


# ── Aşama 0a: tanınmayan değer için süreç başına bir kez WARNING ─────────────────────────
import logging  # noqa: E402


def test_unrecognized_value_warns_once_per_value(caplog):
    ps.reset_warned()
    with caplog.at_level(logging.WARNING, logger="app.services.chat_quality.power_state"):
        for _ in range(5):
            assert ps.classify("Zzz-Weird") == ps.UNKNOWN
        assert ps.classify("ZZZ_WEIRD") == ps.UNKNOWN  # aynı normalize anahtar -> tekrar uyarı yok
        assert ps.classify("Other9") == ps.UNKNOWN
    msgs = [r.getMessage() for r in caplog.records if "tanınmayan ham güç durumu" in r.getMessage()]
    assert len(msgs) == 2  # zzzweird + other9, her biri bir kez
    ps.reset_warned()


def test_recognized_and_empty_values_do_not_warn(caplog):
    ps.reset_warned()
    with caplog.at_level(logging.WARNING, logger="app.services.chat_quality.power_state"):
        for v in ("poweredOn", "Stopped", "Paused", "suspendedByUser", None, "", "unknown", "N/A"):
            ps.classify(v)
    assert not [r for r in caplog.records if "tanınmayan" in r.getMessage()]
    ps.reset_warned()


def test_warning_set_is_bounded():
    ps.reset_warned()
    for i in range(ps._WARNED_MAX + 50):
        ps.classify(f"weird-value-{i}")
    assert len(ps._WARNED) <= ps._WARNED_MAX
    ps.reset_warned()
