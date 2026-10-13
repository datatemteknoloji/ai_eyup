"""Adım 7j: ASCII-Türkçe normalizasyon, aktif iş profili, önceki çalışma profili/takibi."""
from app.services.automic.answer_profile import classify_question
from app.services.automic.template_answers import (
    _from_active, _from_search_yesno, plan_deterministic, template_meta, try_template_answer,
)
from app.services.automic.tr_grammar import fold_tr


def test_fold_tr():
    assert fold_tr("ŞİMDİ çalışıyor ığüöç") == "simdi calisiyor iguoc"


def test_active_profile_ascii_and_typos():
    for q in ["joblar calisiyo mu simdi", "Şu an kaç iş çalışıyor?", "simdi neler calisiyor",
              "hangi joblar su an calisiyor", "şu an çalışan iş var mı"]:
        assert classify_question(q) == "active", q


def test_active_profile_not_hijacking_others():
    assert classify_question("JOBS.DWH.SYNC.01 en son ne zaman çalıştı?") == "lastrun"
    assert classify_question("Engine hangi sunucularda çalışıyor?") == "infra"
    assert classify_question("JOBS.FIN.EXTRACT.01 şu an hangi sunucuda çalışıyor?") != "active"
    assert classify_question("dün hangi joblar patladı") == "list"


def test_yesno_ascii_tail_and_prevrun():
    assert classify_question("JOBS.DWH.SYNC.01 hata vermis mi") == "yesno"
    assert classify_question("bir önceki calismasinin raporunu goster") == "prevrun"
    assert classify_question("bir önceki çalışmasının raporunu göster") == "prevrun"


def test_active_plan_and_answer_from_template():
    plan = plan_deterministic("joblar calisiyo mu simdi")
    assert plan == [("automic_active", {"limit": 500})]
    res = {"ok": True, "total": 3, "over_p95_count": 1, "snapshot_at": "2026-10-13T04:06:27+00:00",
           "items": [{"state": "running"}, {"state": "running"}, {"state": "waiting"}]}
    ans = try_template_answer("joblar calisiyo mu simdi",
                              [{"tool": "automic_active", "result": res}])
    assert ans and ans.startswith("**Evet, şu an 3 aktif iş var:** 2 çalışıyor, 1 bekliyor.")
    assert "1'i normal süresini" in ans
    assert template_meta("active")["answer_source"] == "template"


def test_active_answer_zero_for_object():
    res = {"ok": True, "total": 40, "matched": 0, "items": []}
    ans = _from_active("JOBS.X.Y.01 şu an çalışıyor mu", [{"tool": "automic_active", "result": res}], False)
    assert ans.startswith("**Hayır, Şu an `JOBS.X.Y.01`") or "yok" in ans


def test_yesno_polarity_hata_vermis_mi():
    res = {"universe": {"runs_total": 10, "failed_total": 3, "failure_rate_pct": 30.0}, "total": 10}
    assert _from_search_yesno("JOBS.A.B.01 hata vermis mi", res, False).startswith("**Evet:**")
    assert _from_search_yesno("JOBS.A.B.01 hiç hata vermedi mi", res, False).startswith("**Hayır:**")
    res0 = {"universe": {"runs_total": 10, "failed_total": 0}, "total": 10}
    assert _from_search_yesno("JOBS.A.B.01 hata verdi mi", res0, False).startswith("**Hayır:**")
