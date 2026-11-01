"""Adım 7b/7c — veriye dayalılık doğrulayıcısı (saf)."""
import time
from types import SimpleNamespace

import pytest

from app.services.chat_quality import grounding as g

VMS = {"ok": True, "total_matching": 1556, "vms": [
    {"name": "web-prod-01", "vm_power_state": "POWERED_ON", "memory_gb": 16, "cpu": 8},
    {"name": "db-prod-02", "vm_power_state": "POWERED_OFF", "memory_gb": 64, "cpu": 16},
    {"name": "Harvester", "vm_power_state": "POWERED_OFF", "memory_gb": 32, "cpu": 8},
]}
TOOLS = [("db_list_vms", {"limit": 3}, VMS)]


def v(answer, *, tools=TOOLS, user="VM'leri listele", hist="", paths=(), platform="unified"):
    return g.verify(answer, user_message=user, history_text=hist, tools=tools, paths=list(paths), platform=platform)


def classes(res):
    return {f["class"] for f in res["findings"]}


# ── sayı ──────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ans", [
    "Toplam 1556 VM var; 3 tanesi listelendi.",
    "Toplam 1.556 VM kayıtlı.",
    "web-prod-01 16 GB belleğe sahip.",
    "db-prod-02: 64 GB bellek, 16 vCPU.",
])
def test_number_grounded_or_not(ans):
    r = v(ans)
    nums = [f["text"] for f in r["findings"] if f["class"] == "ungrounded_number"]
    assert not nums, (ans, nums)


@pytest.mark.parametrize("ans,bad", [
    ("Toplam 1721 VM var.", "1721"),
    ("web-prod-01 50 GB belleğe sahip.", "50"),
    ("Sistemde 2300 VM çalışıyor.", "2300"),
    ("CPU kullanımı %87 seviyesinde.", "87"),
    ("Toplam 640 GB disk kullanılıyor.", "640"),
])
def test_number_ungrounded(ans, bad):
    r = v(ans)
    assert bad in [f["text"] for f in r["findings"] if f["class"] == "ungrounded_number"], ans


@pytest.mark.parametrize("ans,bad", [
    ("Ortalama bellek 37.3 GB.", "37.3"),           # model hesabı: üç değerin ortalaması (araç hesaplamalı) → bulgu
    ("Toplam bellek 112 GB.", "112"),               # üçlü toplam: yalnız ikili toplam/fark türevi kabul
])
def test_model_computed_aggregates_flagged(ans, bad):
    assert bad in [f["text"] for f in v(ans)["findings"] if f["class"] == "ungrounded_number"]


def test_number_in_user_message_is_evidence():
    r = v("46 VM istediniz.", user="46 VM göster")
    assert "ungrounded_number" not in classes(r)


def test_number_from_history_is_evidence():
    r = v("Önceki cevapta 777 VM demiştim.", hist="Ortamda 777 VM var")
    assert "ungrounded_number" not in classes(r)


def test_number_sum_and_diff_derived():
    tools = [("t", {}, {"on": 1470, "off": 86})]
    assert "ungrounded_number" not in classes(v("Toplam 1556 VM.", tools=tools))
    assert "ungrounded_number" not in classes(v("Fark 1384.", tools=tools))
    assert "ungrounded_number" in classes(v("Toplam 1600 VM.", tools=tools))


def test_number_percent_derived():
    tools = [("t", {}, {"on": 1470, "total": 1556})]
    assert "ungrounded_number" not in classes(v("Açık oranı %94.5.", tools=tools))
    assert "ungrounded_number" in classes(v("Açık oranı %70.", tools=tools))


def test_number_unit_conversions():
    tools = [("t", {}, {"memory_bytes": 17179869184, "uptime_sec": 7200})]
    assert "ungrounded_number" not in classes(v("Bellek 16 GB.", tools=tools))
    assert "ungrounded_number" not in classes(v("Uptime 120 dakika.", tools=tools))
    assert "ungrounded_number" not in classes(v("Uptime 2 saat.", tools=tools))
    assert "ungrounded_number" in classes(v("Bellek 25 GB.", tools=tools))


def test_number_fraction_to_percent():
    tools = [("t", {}, {"cpu_ratio": 0.87})]
    assert "ungrounded_number" not in classes(v("CPU %87.", tools=tools))


def test_number_rounding():
    tools = [("t", {}, {"cpu_pct": 87.4, "mem": 12.345})]
    assert "ungrounded_number" not in classes(v("CPU %87 civarında.", tools=tools))
    assert "ungrounded_number" not in classes(v("Bellek 12.35 GB.", tools=tools))


def test_number_list_length_is_evidence():
    tools = [("t", {}, {"items": [{"n": i} for i in range(37)]})]
    assert "ungrounded_number" not in classes(v("Toplam 37 kayıt listelendi.", tools=tools))


@pytest.mark.parametrize("ans", [
    "1) Birinci adım\n2) İkinci adım",
    "### 3) Başlık",
    "2026-10-21 tarihinde, saat 14:35'te.",
    "Sürüm 4.14.2 kurulu.",
    "Adres 10.20.30.40 üzerinde.",
    "vm1000 ve node_3 ile ocp-4 kümesi.",
    "Çok küçük sayılar: 3 VM, 7 host, 10 pod.",
    "Yıl 2026 içinde.",
    "`SELECT 99999 FROM x` sorgusu.",
    "```\ndf -h 987654\n```",
])
def test_number_noise_ignored(ans):
    assert "ungrounded_number" not in classes(v(ans)), ans


def test_numbers_trivial_set_and_year():
    nums = [x for x, _ in g.answer_numbers("100 ve 1024 ve 2026 ve 7 ve 4321")]
    assert nums == [4321.0]


def test_parse_number_formats():
    assert g.parse_number("1.556") == 1556.0
    assert g.parse_number("1,556") == 1556.0
    assert g.parse_number("1 041 613") == 1041613.0
    assert g.parse_number("0,045") == 0.045
    assert g.parse_number("37.33") == 37.33
    assert g.parse_number("abc") is None


# ── ad ────────────────────────────────────────────────────────────────────────────

def test_entity_grounded():
    r = v("| VM | Güç |\n|---|---|\n| web-prod-01 | açık |\n| db-prod-02 | kapalı |\n\n**web-prod-01** açık.")
    assert "ungrounded_entity" not in classes(r)


@pytest.mark.parametrize("ans,bad", [
    ("| VM | Güç |\n|---|---|\n| cache-prod-77 | açık |", "cache-prod-77"),
    ("**mail-gw-03** kapalı görünüyor.", "mail-gw-03"),
    ("`fileserver-12` makinesi.", "fileserver-12"),
    ("Sunucu app01.corp.example.local yanıt vermiyor.", "app01.corp.example.local"),
])
def test_entity_ungrounded(ans, bad):
    r = v(ans)
    assert bad in [f["text"] for f in r["findings"] if f["class"] == "ungrounded_entity"]


def test_entity_from_user_message_is_evidence():
    r = v("**mail-gw-03** bulunamadı.", user="mail-gw-03 nerede?")
    assert "ungrounded_entity" not in classes(r)


def test_entity_case_and_turkish_fold():
    tools = [("t", {}, {"vms": [{"name": "Web-Prod-İstanbul-01"}]})]
    assert "ungrounded_entity" not in classes(v("**web-prod-istanbul-01** açık.", tools=tools))


def test_entity_plain_words_ignored():
    r = v("**Toplam**: 3 VM. **Harvester** kapalı. `Running` durumunda.")
    assert "ungrounded_entity" not in classes(r)


def test_entity_table_labels_ignored():
    r = v("| Açıklama | Değer |\n|---|---|\n| Aylık Maliyet | 5 |")
    assert "ungrounded_entity" not in classes(r)


def test_entity_files_urls_ignored():
    r = v("Bkz. `docs/guide.md`, `config.yaml`, https://example.com/a-b-c ve `/var/log/messages`.")
    assert "ungrounded_entity" not in classes(r)


# ── komut ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("ans,binary", [
    ("```\nvmware-vim-cmd vmsvc/device.getinfo 12\n```", "vmware-vim-cmd"),
    ("Şunu çalıştırın: `esxcli network nic list`", "esxcli"),
    ("```bash\ngovc vm.info web-prod-01\n```", "govc"),
    ("```\nvirsh list --all\n```", "virsh"),
])
def test_command_ungrounded(ans, binary):
    r = v(ans)
    assert binary in [f["detail"] for f in r["findings"] if f["class"] == "ungrounded_command"], ans


@pytest.mark.parametrize("ans", [
    "```\ndf -h\nfree -m\n```",
    "`journalctl -u sshd`",
    "```\nkubectl get pods -A\n```",
    "`ls -l /tmp`",
])
def test_command_safe_diagnostics(ans):
    assert "ungrounded_command" not in classes(v(ans))


def test_command_grounded_by_tool_result():
    tools = [("t", {}, {"hint": "virsh list --all çıktısı"})]
    assert "ungrounded_command" not in classes(v("```\nvirsh list --all\n```", tools=tools))


# ── iç terim / kaynak etiketi ─────────────────────────────────────────────────────

def test_internal_tool_name():
    r = v("Veriler db_list_vms aracından geldi.")
    f = [x for x in r["findings"] if x["class"] == "internal_term"]
    assert f and f[0]["text"] == "db_list_vms"


def test_internal_result_key():
    tools = [("t", {}, {"memory_request_gb": 4})]
    r = v("memory_request_gb alanı 4.", tools=tools)
    assert "internal_term" in classes(r)


def test_internal_term_user_used_it():
    tools = [("t", {}, {"memory_request_gb": 4})]
    r = v("memory_request_gb alanı 4.", tools=tools, user="memory_request_gb nedir?")
    assert "internal_term" not in classes(r)


@pytest.mark.parametrize("ans", [
    "Veri bloku boş döndü.", "tool result boş.", "structured_results içinde yok.",
])
def test_internal_phrases(ans):
    assert "internal_term" in classes(v(ans, tools=[]))


def test_internal_terms_ignore_code_blocks_and_plain_words():
    assert "internal_term" not in classes(v("```\nx = db_list_vms\n```\nTamam."))
    assert "internal_term" not in classes(v("Sanal makine durumu: powered_off değil, çalışıyor."))


@pytest.mark.parametrize("ans", [
    "## Liste (kaynak: db_list_vms)",
    "Sonuç (kaynak: vcenter_ask (AI))",
    "vcenter_ask (AI) bunu söyledi.",
])
def test_source_label(ans):
    assert "source_label" in classes(v(ans, tools=[]))


def test_source_label_plain_source_ok():
    assert "source_label" not in classes(v("_Kaynak: envanter veritabanı; son senkron: dün._", tools=[]))


def test_source_label_not_double_counted_as_internal():
    r = v("## Liste (kaynak: db_list_vms)")
    assert "source_label" in classes(r) and "internal_term" not in classes(r)


# ── kabul edilen yanlış öncül ────────────────────────────────────────────────────

def test_premise_accepted():
    r = v("office vCenter'da 46 VM var; kapalı olanlar şunlar.", user="office vCenter'da 46 VM var, bunların kaçı kapalı?")
    assert "premise_accepted" in classes(r)


@pytest.mark.parametrize("ans", [
    "Sorunuzda 46 VM yazıyor ama aslında 33 VM var; 19'u kapalı.",
    "46 değil, 33 VM var.",
    "Hayır, 46 VM yok; yalnız 33 VM kayıtlı.",
])
def test_premise_corrected_not_flagged(ans):
    r = v(ans, user="office vCenter'da 46 VM var, bunların kaçı kapalı?")
    assert "premise_accepted" not in classes(r), ans


def test_premise_not_repeated_not_flagged():
    r = v("33 VM var; 19'u kapalı.", user="office vCenter'da 46 VM var, bunların kaçı kapalı?")
    assert "premise_accepted" not in classes(r)


def test_premise_loose_pattern():
    r = v("Ortamda 3000 VM var.", user="Ortamda 3000 VM var, bunlar yeterli mi?")
    assert "premise_accepted" in classes(r)


# ── atlama kuralları ──────────────────────────────────────────────────────────────

def test_skipped_rule_path():
    r = v("Toplam 9999 VM.", paths=[{"kind": "qa_rule", "handler": "x"}])
    assert r["skipped"] == "rule_path" and not r["findings"]


@pytest.mark.parametrize("p", ["entity_gate", "action_gate"])
def test_skipped_gate_paths(p):
    assert v("Toplam 9999 VM.", paths=[{"kind": p}])["skipped"] == "rule_path"


@pytest.mark.parametrize("pl", ["automic", "automation", "Automic"])
def test_skipped_automic(pl):
    assert v("Toplam 9999 VM.", platform=pl)["skipped"] == "platform"


def test_skipped_empty_answer():
    assert v("   ")["skipped"] == "empty"


def test_no_tools_skips_evidence_classes_but_keeps_internal():
    r = v("Toplam 9999 VM, **mail-gw-03** ve db_list_vms.", tools=[])
    assert r["no_tool_evidence"] and "ungrounded_number" not in classes(r) and "ungrounded_entity" not in classes(r)


def test_error_never_raises(monkeypatch):
    monkeypatch.setattr(g, "Evidence", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    r = v("Toplam 9999 VM.")
    assert r.get("error") is True and r["findings"] == []


def test_findings_capped():
    ans = " ".join(f"{1000 + i * 7} VM" for i in range(40))
    r = v(ans)
    assert len(r["findings"]) == g.MAX_FINDINGS and r["counts"]["ungrounded_number"] >= 30


# ── mod / uyarı ───────────────────────────────────────────────────────────────────

def _tr(**kw):
    base = dict(tools=[SimpleNamespace(tool="db_list_vms", args={}, result=VMS)], paths=[], message="VM'leri listele",
                platform="unified")
    base.update(kw)
    return SimpleNamespace(**base)


def test_mode_defaults_and_values(monkeypatch):
    from app.services import runtime_settings as rs
    monkeypatch.setattr(rs, "get_str", lambda k: "")
    assert g.mode() == "shadow" and g.enforce_classes() == set()
    monkeypatch.setattr(rs, "get_str", lambda k: "ENFORCE" if k == "chat_grounding_mode" else "internal_term, bogus,source_label")
    assert g.mode() == "enforce" and g.enforce_classes() == {"internal_term", "source_label"}
    monkeypatch.setattr(rs, "get_str", lambda k: "weird")
    assert g.mode() == "shadow"


def test_verify_turn_off(monkeypatch):
    monkeypatch.setattr(g, "mode", lambda: "off")
    assert g.verify_turn(_tr(), "Toplam 9999 VM") is None


def test_verify_turn_shadow(monkeypatch):
    monkeypatch.setattr(g, "mode", lambda: "shadow")
    r = g.verify_turn(_tr(), "Toplam 9999 VM")
    assert r["mode"] == "shadow" and "ungrounded_number" in classes(r)


def test_notice_only_for_selected_classes():
    r = v("Toplam 9999 VM; db_list_vms.")
    assert g.notice_for(r, {"source_label"}) == ""
    n = g.notice_for(r, {"internal_term"})
    assert "Doğrulama uyarısı" in n and "db_list_vms" in n and "9999" not in n
    n2 = g.notice_for(r, {"internal_term", "ungrounded_number"})
    assert "9999" in n2 and "db_list_vms" in n2
    assert g.notice_for(None, {"internal_term"}) == ""


# ── bozulmuş cevap seti: yakalama (≥ 40, hedef ≥ %80) ──────────────────────────────

_GOOD = (
    "| VM | Güç |\n|---|---|\n| web-prod-01 | açık |\n| db-prod-02 | kapalı |\n\n"
    "Toplam 1556 VM kayıtlı; web-prod-01 16 GB, db-prod-02 64 GB belleğe sahip."
)

CORRUPT = (
    # sayı değiştir
    [("ungrounded_number", _GOOD.replace("1556", str(n))) for n in (1655, 1700, 1842, 2200, 2311, 999, 3456, 4000, 1821, 1333)]
    + [("ungrounded_number", _GOOD.replace("64 GB", f"{n} GB")) for n in (50, 70, 90, 130, 300, 500, 700, 900)]
    # uydurma ad ekle
    + [("ungrounded_entity", _GOOD + f"\n\n**{nm}** de kapalı.") for nm in (
        "cache-prod-77", "mail-gw-03", "ftp-old-09", "ldap-dc-02", "backup-srv-11", "proxy-edge-05")]
    + [("ungrounded_entity", _GOOD.replace("| db-prod-02 | kapalı |", f"| db-prod-02 | kapalı |\n| {nm} | açık |"))
       for nm in ("app-node-31", "qa-vm-204", "dev-box-17", "gw-int-01")]
    # bağlam dışı komut
    + [("ungrounded_command", _GOOD + f"\n\n```\n{c}\n```") for c in (
        "vmware-vim-cmd vmsvc/getallvms", "esxcli system version get", "govc ls /dc1", "virsh list --all",
        "pvesh get /nodes", "ovirt-shell list vms")]
    # iç terim sızıntısı
    + [("internal_term", _GOOD + f"\n\nVeri {t} ile alındı.") for t in ("db_list_vms", "list_ocp_pods", "infra_report")]
    + [("internal_term", _GOOD + "\n\nveri bloku boş değil."), ("internal_term", _GOOD + "\n\ntool result alındı.")]
    # kaynak etiketi
    + [("source_label", f"## VM Listesi (kaynak: {t})\n\n{_GOOD}") for t in ("db_list_vms", "list_ocp_pods", "vcenter_ask")]
    + [("source_label", _GOOD + "\n\nvcenter_ask (AI) yanıtı.")]
)


def test_corrupt_set_size():
    assert len(CORRUPT) >= 40


def test_corrupt_set_baseline_clean():
    r = v(_GOOD)
    assert not r["findings"], r["findings"]


def test_corrupt_capture_rate():
    hit = 0
    miss = []
    for cls, ans in CORRUPT:
        r = v(ans)
        if cls in classes(r):
            hit += 1
        else:
            miss.append((cls, ans[-60:]))
    assert hit / len(CORRUPT) >= 0.8, miss


# ── performans ────────────────────────────────────────────────────────────────────

def test_latency_large_evidence():
    big = {"vms": [{"name": f"vm-{i:05d}", "mem": i * 3 % 977, "cpu": i % 64, "state": "on"} for i in range(3000)]}
    tools = [("db_list_vms", {}, big)]
    ans = "Toplam 3000 VM; **vm-00042** açık, **vm-99999** yok; bellek 977 GB; oran %61.\n" * 4
    ts = []
    for _ in range(12):
        t = time.perf_counter()
        r = g.verify(ans, user_message="x", tools=tools, paths=[], platform="unified")
        ts.append((time.perf_counter() - t) * 1000)
    ts.sort()
    assert ts[int(len(ts) * 0.95) - 1] < 400      # kötü durum (3000 satırlık sonuç); gerçek p95 ölçümü canlıda


# ── orkestratör bağlantısı (_run_grounding) ────────────────────────────────────────

def _svc():
    from app.services.chat_orchestrator import service
    return service


def _trace(**kw):
    from app.services.chat_quality import trace as cq_trace
    tr = cq_trace.TurnTrace(turn_id="t1", platform="unified", message="VM'leri listele")
    tr.note_tool("db_list_vms", {}, VMS)
    for k, val in kw.items():
        setattr(tr, k, val)
    return tr


def test_run_grounding_shadow_sets_trace_and_does_not_publish(monkeypatch):
    svc = _svc()
    monkeypatch.setattr(g, "mode", lambda: "shadow")
    pub = []
    monkeypatch.setattr(svc.events, "publish_event", lambda tid, ev: pub.append(ev))
    monkeypatch.setattr(svc, "_history_text", lambda db, row: "")
    tr = _trace()
    svc._run_grounding(None, SimpleNamespace(session_id=None), tr, "Toplam 9999 VM; db_list_vms.", "t1")
    assert tr.grounding["mode"] == "shadow" and "ungrounded_number" in {f["class"] for f in tr.grounding["findings"]}
    assert pub == []
    assert tr.to_debug_dict(answer="x")["grounding"]["counts"]["ungrounded_number"] >= 1


def test_run_grounding_enforce_appends_notice(monkeypatch):
    svc = _svc()
    from app.services.chat_quality import persist
    monkeypatch.setattr(g, "mode", lambda: "enforce")
    monkeypatch.setattr(g, "enforce_classes", lambda: {"internal_term"})
    pub, fixed = [], []
    monkeypatch.setattr(svc.events, "publish_event", lambda tid, ev: pub.append(ev))
    monkeypatch.setattr(persist, "fix_assistant_message", lambda db, row, **k: fixed.append(k) or True)
    monkeypatch.setattr(svc, "_history_text", lambda db, row: "")
    tr = _trace()
    svc._run_grounding(None, SimpleNamespace(session_id=1), tr, "Toplam 9999 VM; db_list_vms.", "t1")
    assert tr.grounding["notice_added"] is True and tr.grounding["enforced"] == ["internal_term"]
    assert len(pub) == 1 and "Doğrulama uyarısı" in pub[0]["token"] and "db_list_vms" in pub[0]["token"]
    assert "9999" not in pub[0]["token"]
    assert fixed and "Doğrulama uyarısı" in fixed[0]["append"]


def test_run_grounding_enforce_without_classes_is_shadow(monkeypatch):
    svc = _svc()
    monkeypatch.setattr(g, "mode", lambda: "enforce")
    monkeypatch.setattr(g, "enforce_classes", lambda: set())
    pub = []
    monkeypatch.setattr(svc.events, "publish_event", lambda tid, ev: pub.append(ev))
    monkeypatch.setattr(svc, "_history_text", lambda db, row: "")
    tr = _trace()
    svc._run_grounding(None, SimpleNamespace(session_id=1), tr, "Toplam 9999 VM; db_list_vms.", "t1")
    assert pub == [] and tr.grounding["notice_added"] is False


def test_run_grounding_off_leaves_trace_empty(monkeypatch):
    svc = _svc()
    monkeypatch.setattr(g, "mode", lambda: "off")
    tr = _trace()
    svc._run_grounding(None, SimpleNamespace(session_id=1), tr, "Toplam 9999 VM", "t1")
    assert tr.grounding is None


def test_run_grounding_never_raises(monkeypatch):
    svc = _svc()
    monkeypatch.setattr(g, "verify_turn", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("x")))
    monkeypatch.setattr(svc, "_history_text", lambda db, row: "")
    svc._run_grounding(None, SimpleNamespace(session_id=1), _trace(), "x", "t1")


def test_history_text_failure_is_empty():
    svc = _svc()

    class _DB:
        def query(self, *a):
            raise RuntimeError("db")

        def rollback(self):
            pass
    assert svc._history_text(_DB(), SimpleNamespace(session_id=3)) == ""
    assert svc._history_text(_DB(), SimpleNamespace(session_id=None)) == ""


def test_large_tool_result_entity_late_row_grounded():
    """3000 satırlık sonuçta geç satırdaki ad kanıt sayılır (metin kanıtı satır sayısıyla kesilmez)."""
    rows = [{"name": f"vm-{i}-prod", "host": f"esx{i % 40}.dc.local", "cpu": i % 32} for i in range(3000)]
    tools = [("db_list_vms", {"limit": 3000}, {"ok": True, "vms": rows, "count": 3000})]
    res = g.verify("**vm-2999-prod** açık; toplam 3000 VM.", user_message="listele", history_text="",
                           tools=tools, paths=[], platform="unified")
    assert not [f for f in res["findings"] if f["class"] == "ungrounded_entity"]
    bad = g.verify("**vm-9999-prod** açık.", user_message="listele", history_text="",
                           tools=tools, paths=[], platform="unified")
    assert [f for f in bad["findings"] if f["class"] == "ungrounded_entity"]


def test_parse_number_fast_path_and_unicode_digit():
    assert g.parse_number("1556") == 1556.0
    assert g.parse_number("1.556") == 1556.0
    assert g.parse_number("²") is None


def test_context_only_field_name_flagged_without_tool_key():
    res = g.verify("oVirt için `problem_pod_count` alanı 110.", user_message="hatalı pod sayısı?", history_text="",
                   tools=[("list_ocp_pods", {}, {"ok": True, "count": 3})], paths=[], platform="unified")
    assert [f for f in res["findings"] if f["class"] == "internal_term" and f["text"] == "problem_pod_count"]


def test_context_field_in_user_message_not_flagged():
    res = g.verify("`problem_pod_count` değeri nedir? Bu alan sorunlu pod sayısıdır.", user_message="problem_pod_count nedir?",
                   history_text="", tools=[], paths=[], platform="unified")
    assert not res["findings"]


def test_timestamp_with_microseconds_and_nb_hyphens_not_a_number():
    ans = "Snapshot zamanı: 2026\u201110\u201121 22:04:48.750342+03:00 ve 21:03:07.123456Z."
    res = g.verify(ans, user_message="", history_text="", tools=[("automic_active", {}, {"ok": True, "count": 14})],
                   paths=[], platform="unified")
    assert not [f for f in res["findings"] if f["class"] == "ungrounded_number"]


def test_notice_wording_per_group():
    r = v("Toplam 9999 VM; db_list_vms.")
    leak_only = g.notice_for(r, {"internal_term"})
    assert "sistem içi" in leak_only and "doğrulanamadı" not in leak_only
    data_only = g.notice_for(r, {"ungrounded_number"})
    assert "doğrulanamadı" in data_only and "sistem içi" not in data_only and "db_list_vms" not in data_only
    both = g.notice_for(r, {"ungrounded_number", "internal_term"})
    assert "doğrulanamadı" in both and "sistem içi" in both


def test_inventory_contract_format_not_flagged():
    ans = ("## VM Listesi (kaynak: db_list_vms)\n\n| VM Adı | Power |\n|---|---|\n| a-1 | Running |\n\n"
           "**Toplam:** 1 VM\nas_of: `2026-10-21T22:08:42.721285+03:00`")
    res = g.verify(ans, user_message="vm listesi", history_text="",
                   tools=[("db_list_vms", {}, {"ok": True, "as_of": "2026-10-21T22:08:42+03:00", "vms": [{"name": "a-1"}]})],
                   paths=[], platform="unified")
    assert not [f for f in res["findings"] if f["class"] in ("source_label", "internal_term")], res["findings"]


def test_source_label_outside_contract_still_flagged_with_code_block_before():
    ans = "```\nls -la\n```\n\nKaynak bilgisi: (kaynak: db_list_vms) burada. Ayrıca as_of alanı gelmiş."
    res = g.verify(ans, user_message="", history_text="",
                   tools=[("db_list_vms", {}, {"ok": True, "as_of": "x"})], paths=[], platform="unified")
    cl = {f["class"] for f in res["findings"]}
    assert "source_label" in cl and "internal_term" in cl


def test_schema_defaults_enforce_passing_classes_only():
    from app.services import runtime_settings as rs
    assert rs.ADVANCED_SCHEMA["chat_grounding_mode"]["default"] == "enforce"
    cls = set(rs.ADVANCED_SCHEMA["chat_grounding_enforce_classes"]["default"].split(","))
    assert cls == {"internal_term", "source_label", "ungrounded_entity", "ungrounded_command"}
    assert "ungrounded_number" not in cls and "premise_accepted" not in cls   # gölgede: örneklem/ölçüm yetersiz
    assert cls <= set(g.CLASSES)
