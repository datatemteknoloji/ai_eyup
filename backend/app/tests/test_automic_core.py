"""Automic modülü — DB gerektirmeyen çekirdek testler."""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.automic.classify import classify_status, failed_rule_text
from app.services.automic.defaults import DEFAULT_SETTINGS, effective_settings, validate_settings
from app.services.automic.excerpt import build_excerpt, error_signature
from app.services.automic.masking import is_valid_tckn, mask_text, validate_custom_patterns
from app.services.automic.prompt import split_meta
from app.services.automic.schedule import collection_allowed
from app.services.automic.source import templates
from app.services.automic.source.base import EXECUTION_FIELDS
from app.services.automic.source.base import SourceError
from app.services.automic.source.fake import FakeSource
from app.services.automic.source.sql_guard import UnsafeSqlError, assert_read_only

SC = DEFAULT_SETTINGS["status_classes"]


# ── SQL guard ──

@pytest.mark.parametrize("sql", [
    "SELECT 1 FROM dual",
    "WITH x AS (SELECT 1 FROM dual) SELECT * FROM x",
    "SELECT AH_IDNR FROM UC4.AH WHERE AH_NAME = 'DROP TABLE x;'",
])
def test_guard_allows_select(sql):
    assert assert_read_only(sql) == sql


@pytest.mark.parametrize("sql", [
    "UPDATE AH SET AH_STATUS = 1",
    "DELETE FROM AH",
    "SELECT 1 FROM dual; DROP TABLE AH",
    "SELECT * FROM AH FOR UPDATE",
    "BEGIN dbms_output.put_line('x'); END",
    "SELECT 1 FROM dual -- yorum",
    "SELECT dbms_lock.sleep(10) FROM dual",
    "  insert into AH values (1)",
    "",
])
def test_guard_blocks_writes(sql):
    with pytest.raises(UnsafeSqlError):
        assert_read_only(sql)


def test_all_template_queries_pass_guard():
    prof = templates.load_profile("oracle", "ae-24")
    cols = {}
    for spec in prof["tables"].values():
        t = spec["table"][0].upper()
        for kind in ("required", "optional"):
            for cands in (spec.get(kind) or {}).values():
                cols.setdefault(t, set()).add(cands[0].upper())
    mapping = templates.resolve_mapping(prof, cols)
    assert all(m["available"] for m in mapping.values()), {
        k: v.get("missing_required") for k, v in mapping.items() if not v["available"]
    }
    q2t = {"ended_executions": "executions", "latest_run_id": "executions",
           "min_run_id": "executions", "count_ended_by_id_range": "executions",
           "execution_by_id": "executions", "children": "executions",
           "restarts": "executions", "active_executions": "active", "report_types_rh": "report_headers",
           "report_types_rt": "report_text", "report_count": "report_text",
           "report_range": "report_text", "object_header_by_name": "object_headers",
           "object_script_lines": "object_scripts", "usage_children": "object_usage",
           "usage_by_parent_id_range": "object_usage", "object_headers_by_id_range": "object_headers",
           "object_names_by_ids": "object_headers", "folder_links_by_objects": "folders",
           "hosts_all": "hosts", "mqsrv_all": "mqsrv", "ohg_all": "agent_groups",
           "ohgf_all": "agent_group_filters", "table_row_count": "hosts"}
    from app.services.automic.source.base import HOST_FIELDS, MQSRV_FIELDS, OHG_FIELDS, OHGF_FIELDS
    field_map = {
        "hosts": list(HOST_FIELDS), "mqsrv": list(MQSRV_FIELDS),
        "agent_groups": list(OHG_FIELDS), "agent_group_filters": list(OHGF_FIELDS),
    }
    for q, lt in q2t.items():
        fields = field_map.get(lt, list(EXECUTION_FIELDS))
        sql = templates.render(prof, q, schema="UC4", table_map=mapping[lt], fields=fields,
                               clients_bind=":c0", ids_bind=":i0", limit=10)
        assert sql.startswith("SELECT")
        assert "UC4." in sql
        assert "{" not in sql  # doldurulmamış yer tutucu kalmamalı
        assert "FETCH FIRST" in sql.upper()
        if q in ("children", "restarts", "usage_by_parent_id_range"):
            assert ":id_min" in sql and ":id_max" in sql
    # Zaman / LIKE / USR_Idnr / isimle JPP şablonları kaldırıldı
    for gone in ("daily_profile", "latest_activation", "user_objects_by_name", "ended_by_users",
                 "object_headers_since", "object_headers_by_clients", "usage_parents"):
        assert gone not in (prof.get("queries") or {})


def test_mapping_missing_required_marks_unavailable():
    prof = templates.load_profile("oracle", "ae-24")
    m = templates.resolve_mapping(prof, {"AH": {"AH_IDNR", "AH_CLIENT", "AH_NAME"}})
    assert m["executions"]["available"] is False
    assert "status_code" in m["executions"]["missing_required"]
    assert m["active"]["available"] is False


def test_safe_ident_rejects_injection():
    with pytest.raises(ValueError):
        templates.safe_ident("AH; DROP")


# ── sınıflandırma ──

@pytest.mark.parametrize("code,cls", [
    (1800, "failed"), (1802, "failed"), (1899, "failed"),
    (1850, "cancelled"), (1851, "cancelled"),
    (1900, "ok"), (1920, "ok"), (1999, "ok"),
    (1550, "other"), (None, "other"),
])
def test_classify(code, cls):
    assert classify_status(code, SC) == cls


def test_classify_custom_rule():
    sc = {"failed": {"codes": [1700]}, "ok": {"ranges": [[1900, 1999]]}}
    assert classify_status(1700, sc) == "failed"
    assert classify_status(1800, sc) == "other"


def test_failed_rule_text():
    assert "ANY_ABEND" in failed_rule_text(SC)
    assert "1850" in failed_rule_text(SC)


# ── maskeleme ──

def test_tckn_checksum():
    assert is_valid_tckn("10000000146")
    assert not is_valid_tckn("12345678901")


@pytest.mark.parametrize("raw,leak", [
    ("&DB_PASSWORD# = 'S3cr3t!1'", "S3cr3t!1"),
    ("sqlplus batch/Gizli42@DWHPRD @x.sql", "Gizli42"),
    ("export API_TOKEN=abcd1234", "abcd1234"),
    ("password: hunter2", "hunter2"),
    ("--password=xyz123 --user a", "xyz123"),
    ("Authorization: Bearer eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.abcdefghijkl", "eyJhbGci"),
    ("jdbc:oracle:thin:@h:1521/s;password=p4ss", "p4ss"),
    ("https://user:p%40ss@host/x", "p%40ss"),
    ("TCKN 10000000146", "10000000146"),
    ("IBAN TR330006100519786457841326", "TR330006100519786457841326"),
    ("tel 0532 123 45 67", "0532 123 45 67"),
    ("mail ops@example.com", "ops@example.com"),
    ("host 10.20.30.40", "10.20.30.40"),
])
def test_masking(raw, leak):
    assert leak not in mask_text(raw, {"country_pack": "tr", "mask_ip": True})


def test_masking_keeps_non_sensitive():
    s = "mkdir -p /data/out; return code 8; RunID 12345678901 ORA-00054"
    out = mask_text(s, {"country_pack": "tr", "mask_ip": True})
    assert "mkdir -p /data/out" in out and "ORA-00054" in out and "return code 8" in out


def test_masking_custom_pattern_and_validation():
    cfg = {"custom_patterns": [{"name": "musteri", "regex": r"MUS-\d{6}"}]}
    assert "MUS-123456" not in mask_text("kayıt MUS-123456", cfg)
    assert validate_custom_patterns([{"name": "bad", "regex": "("}])


# ── alıntı / imza ──

def test_excerpt_keeps_head_errors_tail():
    lines = [f"line {i}" for i in range(1000)]
    lines[500] = "ERROR: ORA-01653: unable to extend table X by 8192"
    text, trunc = build_excerpt(lines, {"head_lines": 5, "tail_lines": 5, "context_lines": 2,
                                        "max_kb": 64, "patterns": ["ERROR", "ORA-"]})
    assert trunc and "line 0" in text and "line 999" in text and "ORA-01653" in text and "line 498" in text
    assert "line 300" not in text


def test_excerpt_size_limit():
    lines = ["x" * 1000] * 500
    text, trunc = build_excerpt(lines, {"head_lines": 500, "tail_lines": 0, "max_kb": 8, "patterns": []})
    assert trunc and len(text.encode()) < 9 * 1024


def test_error_signature_normalizes():
    a = error_signature(["ERROR: ORA-01653: unable to extend table DWH.F by 8192 in tablespace X"], ["ERROR"])
    b = error_signature(["ERROR: ORA-01653: unable to extend table DWH.F by 1024 in tablespace X"], ["ERROR"])
    assert a == b and a.startswith("ORA-01653")


# ── ayarlar ──

def test_settings_limits():
    assert validate_settings({}) == []
    errs = validate_settings({"retention": {"executions_days": 365}, "collection": {"interval_min": 1}})
    assert len(errs) == 2
    eff = effective_settings({"storage": {"quota_gb": 200}})
    assert eff["storage"]["quota_gb"] == 200 and eff["storage"]["warn_pct"] == 70


def test_collection_windows():
    coll = {"timezone": "UTC", "windows": [{"days": [0, 1, 2, 3, 4], "from": "08:00", "to": "18:00"}],
            "blackout": [{"from": "12:00", "to": "12:30"}]}
    mon_10 = datetime(2026, 10, 5, 10, 0, tzinfo=timezone.utc)  # Pazartesi
    assert collection_allowed(coll, mon_10)
    assert not collection_allowed(coll, mon_10.replace(hour=12, minute=15))
    assert not collection_allowed(coll, mon_10.replace(hour=20))
    assert not collection_allowed(coll, mon_10 + timedelta(days=5))  # Cumartesi
    assert collection_allowed({"timezone": "UTC", "windows": [{"from": "22:00", "to": "02:00"}]},
                              mon_10.replace(hour=1))


def test_storage_projection_matches_policy_example():
    from app.services.automic.retention import storage_projection

    p = storage_projection(effective_settings({"projection": {
        "daily_exec": 870000, "failure_rate": 0.01, "active_objects_daily": 50000}}))
    assert 43 <= p["estimated_db_gb"] <= 45
    assert p["min_disk_gb"] == 150.0 and p["fits"] is True


def test_automic_tools_isolated_from_other_chats():
    from app.services.agent import tools as t

    def names(specs):
        return {s["function"]["name"] for s in specs}

    automic = {n for n in t.TOOLS if n.startswith("automic_")}
    assert len(automic) == 8
    assert "automic_agent" in automic
    assert "automic_infrastructure" in automic
    assert not automic & names(t.tool_specs())
    assert not automic & names(t.tool_specs_read_only(None))
    assert not automic & names(t.tool_specs_read_only(t.domains_for_platform("linux")))
    assert automic == names(t.tool_specs_read_only(t.domains_for_platform("automic")))
    res = t.get_tool("automic_status").execute(None, {}, {"platform": "unified"})
    assert res["ok"] is False
    # Unified + domains=automic → platform kontrolü geçer (DB yoksa bağlantı hatası)
    res2 = t.get_tool("automic_status").execute(None, {}, {"platform": "unified", "domains": {"automic"}})
    assert res2.get("error") != "Automic araçları yalnız Automic kapsamında kullanılabilir."


# ── meta ──

def test_split_meta():
    txt = "### Özet\nTamam.\n\n```ainew-meta\n{\"intent\": \"failure_analysis\", \"severity\": \"critical\", " \
          "\"entities\": [{\"kind\": \"execution\", \"run_id\": 1}, {\"kind\": \"bad\"}], \"follow_ups\": [\"a\"]}\n```"
    body, meta = split_meta(txt)
    assert "ainew-meta" not in body and meta["intent"] == "failure_analysis"
    assert len(meta["entities"]) == 1 and meta["follow_ups"] == ["a"]
    body2, meta2 = split_meta("yalnız metin")
    assert meta2 is None and body2 == "yalnız metin"


# ── sahte kaynak ──

def _fake():
    return FakeSource(1, {"fake_clients": [100, 200]}, None, effective_settings({}), {})


def test_fake_deterministic_and_windowed():
    src = _fake()
    end = datetime.now(timezone.utc) - timedelta(hours=2)
    start = end - timedelta(minutes=30)
    # PK dilimi: fake RunID = dakika_epoch*10000+slot+seq — geniş aralık test için yeterli
    bounds = dict(id_min=0, id_max=10**15)
    a = src.fetch_ended_executions([100, 200], start, end, limit=100000, **bounds)
    b = src.fetch_ended_executions([100, 200], start, end, limit=100000, **bounds)
    assert a == b and len(a) > 0
    assert all(start <= r["end_time"] < end for r in a)
    assert {r["client"] for r in a} <= {100, 200}
    keys = [(r["client"], r["run_id"]) for r in a]
    assert len(keys) == len(set(keys))


def test_fake_children_and_reports():
    src = _fake()
    end = datetime.now(timezone.utc) - timedelta(hours=1)
    recs = src.fetch_ended_executions(
        [100], end - timedelta(hours=3), end, limit=100000, id_min=0, id_max=10**15)
    wf = next(r for r in recs if r["object_type"] == "JOBP")
    kids = src.fetch_children(100, wf["run_id"], limit=50, id_min=int(wf["run_id"]), id_max=10**15)
    assert kids and all(k["parent_run_id"] == wf["run_id"] for k in kids)
    # Alt görevler aynı artan sayaçtan; 9e12 ofset yok; üstten büyük
    assert all(k["run_id"] > wf["run_id"] for k in kids)
    assert all(k["run_id"] < 9_000_000_000_000 for k in kids)
    assert all(r["run_id"] < 8_000_000_000_000 for r in recs)
    failed = next(r for r in recs if 1800 <= r["status_code"] <= 1899 and r["status_code"] not in (1850, 1851)
                  and r["object_type"] == "JOBS")  # 1850/1851 = iptal (hata metni yok)
    assert src.fetch_execution(100, failed["run_id"])["run_id"] == failed["run_id"]
    rep = src.fetch_report(100, failed["run_id"], "REP", head=50, tail=200, max_scan_lines=5000)
    joined = "\n".join(rep.lines)
    assert "ERROR" in joined
    masked = mask_text(joined, {"country_pack": "tr"})
    assert "S3cr3t" not in masked and "10000000146" not in masked


def test_split_meta_intent_list():
    from app.services.automic.prompt import split_meta

    _, meta = split_meta('ok\n```ainew-meta\n{"intent": ["failure_analysis", "x"], "scope": {}}\n```')
    assert meta["intent"] == "failure_analysis"


def test_leak_guard_drops_preamble_and_unwraps():
    from app.services.automic.chat_support import AnswerLeakGuard

    g = AnswerLeakGuard()
    text = "We need to produce the answer...\n```markdown\n### Özet\nTamam.\n```\n```ainew-meta\n{}\n```"
    out = "".join(g.feed(text[i:i + 7]) for i in range(0, len(text), 7)) + g.flush()
    assert out.startswith("### Özet") and g.dropped > 0
    cleaned = g.clean_full(out)
    assert "```ainew-meta" in cleaned and not cleaned.split("```ainew-meta")[0].rstrip().endswith("```")


def test_leak_guard_passthrough_without_heading():
    from app.services.automic.chat_support import AnswerLeakGuard

    g = AnswerLeakGuard(hold_chars=20)
    assert g.feed("kısa") == ""
    assert g.flush() == "kısa"


def test_fallback_plan():
    from app.services.automic.chat_support import detect_range, plan_fallback

    assert detect_range("son 3 gün") == "3d" and detect_range("son 6 saat") == "6h"
    assert plan_fallback("RunID 123456789 neden düştü")[0][0] == "automic_execution"
    assert plan_fallback("şu an çalışan işler")[0][0] == "automic_active"
    assert [p[1]["template_id"] for p in plan_fallback("en çok hata veren")[:2]] == ["top_failed_objects", "error_signatures"]


def test_deterministic_answer():
    from app.services.automic.chat_support import deterministic_answer

    txt = deterministic_answer([
        {"tool": "automic_history", "result": {"template_id": "top_failed_objects", "rows": [
            {"object_name": "JOBS.A", "failed": 3, "runs": 10, "failure_rate_pct": 30.0}]}},
        {"tool": "automic_history", "result": {"template_id": "error_signatures", "rows": [
            {"signature": "ORA-12541: TNS:no listener", "count": 9}]}},
    ], "ReadTimeout")
    assert txt.startswith("**") and "###" not in txt and "JOBS.A" in txt and "ORA-12541" in txt and "ReadTimeout" in txt


def test_fake_object_header_and_script():
    src = _fake()
    cap = src.discover()
    assert cap["features"]["objects"] is True and cap["features"]["versions"] is True
    h = src.fetch_object_header(100, "JOBS.FIN.EXTRACT.01")
    assert h and h["object_id"] and h["object_name"] == "JOBS.FIN.EXTRACT.01"
    lines = src.fetch_object_script(h["object_id"])
    assert any("Automic script" in ln or ":SET" in ln for ln in lines)


def test_sql_profile_has_object_tables():
    prof = templates.load_profile("oracle", "ae-24")
    assert "object_headers" in prof["tables"] and "object_scripts" in prof["tables"]
    assert "object_header_by_name" in prof["queries"] and "object_script_lines" in prof["queries"]


def test_unified_routes_automic():
    from app.services.module_orchestrator import MOD_AUTOMIC, plan_modules

    plan = plan_modules("automic uc4 RunID 123456789 neden abend aldı")
    assert MOD_AUTOMIC in plan.modules
    assert "automic" in plan.domains


# ── Faz 3 ──

def test_fake_jpp_range_and_live_usage_removed():
    src = _fake()
    assert src.supports("usage_graph") is True
    with pytest.raises(SourceError) as ei:
        src.fetch_object_usage(100, "JOBP.FIN.GUNSONU", depth=1)
    assert ei.value.code == "capability_removed"
    rows = src.fetch_jpp_by_parent_range(0, 10**12, limit=50)
    assert rows and all("parent_object_id" in r and "child_name" in r for r in rows)


def test_sql_profile_has_usage_queries():
    prof = templates.load_profile("oracle", "ae-24")
    assert "object_usage" in prof["tables"]
    assert "usage_children" in prof["queries"] and "usage_by_parent_id_range" in prof["queries"]
    assert "usage_parents" not in prof["queries"]


def test_insight_cache_roundtrip():
    from app.services.automic import insight as ins

    key_clients = [100, 200]
    payload = {"ok": True, "markdown": "test özet", "generated_at": "now"}
    ins.cache_put(99, "24h", key_clients, payload)
    hit = ins.cache_get(99, "24h", key_clients)
    assert hit and hit["markdown"] == "test özet"
    assert ins.cache_get(99, "24h", [100]) is None  # farklı client anahtarı


def test_insight_deterministic_without_llm():
    from app.services.automic.insight import _deterministic_insight

    md = _deterministic_insight({
        "system": "demo",
        "kpi": {"total": 100, "failed": 12, "failed_prev": 5, "running": 2},
        "top_failed": [{"object_name": "JOBS.A", "failed": 5, "runs": 10}],
        "top_error_signatures": [{"signature": "ORA-12541: TNS:no listener", "count": 3}],
        "storage": {"usage_pct": 82, "level": "warn"},
        "health": {"source_lag_sec": 100},
    }, err="ReadTimeout")
    assert "JOBS.A" in md and "ORA-12541" in md and "Depolama" in md and "ReadTimeout" in md


def test_analysis_kinds():
    from app.services.automic.analyses import KINDS

    assert set(KINDS) >= {"failure_pack", "overnight_review", "impact_analysis"}


def test_history_templates_include_expected_tonight():
    from app.services.automic.queries import HISTORY_TEMPLATES

    assert "expected_tonight" in HISTORY_TEMPLATES


def test_rag_seed_automic_manifest():
    import json
    from pathlib import Path

    candidates = [
        Path(__file__).resolve().parents[3] / "docs" / "rag_seed",
        Path("/dttadvance/app/docs/rag_seed"),
    ]
    root = next((p for p in candidates if (p / "manifest.json").is_file()), None)
    if root is None:
        pytest.skip("docs/rag_seed bu ortamda yok")
    man = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    titles = {d["title"] for d in man["documents"]}
    assert "AUTOMIC-basics" in titles and "AUTOMIC-ops-patterns" in titles
    assert (root / "AUTOMIC-basics.md").is_file()
    assert (root / "AUTOMIC-ops-patterns.md").is_file()


def test_requirements_lists_ports_and_select():
    from app.services.automic.requirements import build_requirements, module_db_endpoint

    mdb = module_db_endpoint()
    assert mdb["port"] == "5435" or mdb["port"]
    groups = build_requirements(
        connection={"host": "ae-source.example", "port": 1731, "service_name": "UC4DB"},
        source_type="db_oracle", quota_gb=100, disk_overhead=1.5,
    )
    titles = {g["title"] for g in groups}
    assert "Automic kaynak DB (automic_source, salt okunur)" in titles
    assert "Modül veritabanı (ainew tarafı)" in titles
    blob = " ".join(it["text"] for g in groups for it in g["items"])
    assert "1731" in blob and "ae-source.example" in blob
    assert "5435" in blob or mdb["port"] in blob
    assert "SELECT" in blob and "automation" in blob
    assert "REST" in blob  # sonraki sürüm — zorunlu değil
    assert "Unified Yönetici" in blob and "gerekmez" in blob
    must = [it for g in groups for it in g["items"] if it["must"]]
    assert len(must) >= 8
    # Unified satırı zorunlu değil (must=False)
    unified_items = [it for g in groups for it in g["items"] if "Unified Yönetici" in it["text"]]
    assert unified_items and not unified_items[0]["must"]


def test_requirements_fake_skips_oracle_must():
    from app.services.automic.requirements import build_requirements

    groups = build_requirements(source_type="fake")
    assert any("fake" in g["title"].lower() or "Geliştirme" in g["title"] for g in groups)


def test_fill_time_buckets_pads_missing_days():
    from app.services.automic.queries import fill_time_buckets

    start = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
    end = datetime(2026, 10, 8, 12, tzinfo=timezone.utc)
    # +03 duvar saatiyle 8 Ekim günü (compose TZ ile hizalı)
    rows = [{"bucket": "2026-10-08T00:00:00+03:00", "failed": 5, "total": 100}]
    filled = fill_time_buckets(rows, start, end, "day", value_keys=["failed", "total"])
    assert len(filled) >= 7
    hit = next(r for r in filled if r["failed"] == 5)
    assert hit["total"] == 100
    assert sum(1 for r in filled if r["total"] == 0) >= 6


def test_leak_guard_releases_on_bold_lead_sentence():
    """Başlıksız yeni sunum: kalın tek satırlık giriş cümlesi yanıt başlangıcıdır."""
    from app.services.automic.chat_support import AnswerLeakGuard

    g = AnswerLeakGuard()
    text = ("We should answer in Turkish. Let me think.\n\n"
            "**BATCH/OPS son 6 saatte 44 hatalı job çalıştırdı.**\n\nAyrıntılar aşağıda.\n")
    out = "".join(g.feed(text[i:i + 5]) for i in range(0, len(text), 5)) + g.flush()
    assert out.startswith("**BATCH/OPS") and g.dropped > 0
    assert "Let me think" not in out


def test_leak_guard_streams_plain_answer_after_limit():
    from app.services.automic.chat_support import AnswerLeakGuard

    g = AnswerLeakGuard()
    assert g.hold_chars <= 3000
    long_text = "Düz metin yanıt. " * 400
    out = "".join(g.feed(long_text[i:i + 50]) for i in range(0, len(long_text), 50)) + g.flush()
    assert out == long_text
