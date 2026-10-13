"""Adım 7e — filtresiz oranlar, takip bağlamı, kod anlamları, öncül düzeltme."""
from __future__ import annotations

from app.services.automic import followup_context as fctx
from app.services.automic import why_answer as wa
from app.services import llm_chat_policy as lcp


def test_why_summary_uses_universe_not_filtered_total():
    structured = [{
        "tool": "automic_search_executions",
        "args": {"status_class": "failed", "object_name": "JOBS.DWH.SYNC.01"},
        "result": {
            "ok": True,
            "total": 63,
            "counts": {"failed": 63},
            "rates": {"failure_rate_pct": 5.1},
            "runs_total": 1240,
            "failed_total": 63,
            "failure_rate_pct": 5.1,
            "universe": {
                "runs_total": 1240, "failed_total": 63, "failure_rate_pct": 5.1,
                "distinct_objects_total": 1, "distinct_objects_failed": 1,
            },
            "from": "2026-10-01T00:00:00+00:00",
            "to": "2026-10-12T00:00:00+00:00",
            "items": [{
                "run_id": 1, "object_name": "JOBS.DWH.SYNC.01", "status_class": "failed",
                "status_code": 1800, "return_code": 8,
            }],
        },
    }]
    blocks = dict(wa.build_blocks(structured))
    summary = next(v for k, v in blocks.items() if k.startswith("sum:"))
    assert "1240" in summary or "1.240" in summary.replace(".", "")
    assert "63" in summary
    assert "%100" not in summary and "hata oranı %100" not in summary
    assert "hatalı çalışmalar listeleniyor" in summary.lower() or "listeleniyor" in summary


def test_premise_correction_count():
    structured = [{
        "result": {
            "ok": True,
            "runs_total": 100, "failed_total": 11, "failure_rate_pct": 11.0,
            "universe": {"runs_total": 100, "failed_total": 11, "failure_rate_pct": 11.0},
        }
    }]
    txt = wa.premise_correction("JOBS.X dün 50 kez hata verdi, sebebi ne?", structured)
    assert "50" in txt and "11" in txt
    assert "Düzeltme" in txt or "değil" in txt


def test_premise_correction_never_failed():
    structured = [{
        "result": {
            "ok": True,
            "runs_total": 1240, "failed_total": 45, "failure_rate_pct": 3.6,
            "universe": {"runs_total": 1240, "failed_total": 45, "failure_rate_pct": 3.6},
        }
    }]
    txt = wa.premise_correction("JOBS.RISK.YEDEK.03 hiç hata vermedi değil mi?", structured)
    assert "Hayır" in txt
    assert "45" in txt


def test_followup_keeps_window_adds_agent():
    prev = {
        "window_label": "dün gece",
        "from": "2026-10-11T15:00:00+00:00",
        "to": "2026-10-12T00:00:00+00:00",
        "filters": {"status_class": "failed"},
        "objects": ["JOBP.SAP.YEDEK", "JOBS.DWH.KONTROL.03"],
        "focus_object": "JOBP.SAP.YEDEK",
    }
    forced, assumption, clarify = fctx.resolve(
        "Peki bunların kaçı LNXAPP01'deydi?", prev)
    assert clarify is None
    assert forced["from"] == prev["from"]
    assert forced["status_class"] == "failed"
    assert forced["agent"] == "LNXAPP01"
    assert "dün gece" in assumption


def test_followup_same_job():
    prev = {
        "from": "a", "to": "b", "filters": {"status_class": "failed"},
        "objects": ["JOBS.SAP.KONTROL.02"], "focus_object": "JOBS.SAP.KONTROL.02",
    }
    forced, _, clarify = fctx.resolve("Aynı job geçen hafta da hata vermiş mi?", prev)
    assert clarify is None
    assert forced["object_name"] == "JOBS.SAP.KONTROL.02"


def test_entity_latest_last_run_question():
    assert lcp.entity_latest_no_window("JOBS.DWH.SYNC.01 en son ne zaman çalıştı?")
    assert not lcp.entity_latest_no_window("JOBS.DWH.SYNC.01 dün ne zaman çalıştı?")


def test_eval_filter_strips_status_meaning_and_forces_low_conf():
    flt = wa.EvalFilter(english=False, allow_med_high=False)
    out = flt.feed(
        "- Olası neden: 1800 genelde kaynak meşguliyetine işaret eder (güven: orta).\n"
        "- Olası neden: script hatası olabilir (güven: düşük).\n"
        "Güven: orta\n"
    )
    out += flt.flush()
    assert "kaynak meşgul" not in out
    assert "script hatası" in out
    assert "Güven: düşük" in out
    assert "Güven: orta" not in out
