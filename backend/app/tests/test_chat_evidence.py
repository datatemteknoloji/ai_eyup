"""Unified + ortak kanıt guard — virt ile aynı karar, final stream paritesi."""
from app.services.chat_coverage import looks_like_no_data_answer
from app.services.chat_evidence import (
    answer_ignores_evidence,
    collect_unified_live_evidence,
    has_meaningful_evidence,
    maybe_fix_no_data_answer,
    needs_evidence_retry,
    render_raw_evidence_fallback,
    retry_answer_is_usable,
)

EVIDENCE = (
    '[Sanallaştırma sağlık özeti]\n{"ok": true, "health": {"score": 50, '
    '"label": "Sorunlu"}, "critical_hosts": [{"host": "192.168.1.101", '
    '"mem_pct": 95.5, "overall_status": "red"}]}'
)


def test_collect_ignores_short_and_rag_sized_noise():
    assert collect_unified_live_evidence(tool_text="ok", linux_ctx="x") == ""
    big = EVIDENCE + " " * 20
    got = collect_unified_live_evidence(tool_text=big, linux_ctx="kısa")
    assert "192.168.1.101" in got
    assert "kısa" not in got


def test_needs_retry_when_no_data_phrase_and_evidence():
    assert has_meaningful_evidence(EVIDENCE)
    assert needs_evidence_retry("Bu konuda canlı veri mevcut değil.", EVIDENCE)


def test_no_retry_without_evidence():
    assert not needs_evidence_retry("Bu konuda canlı veri mevcut değil.", "")
    assert not needs_evidence_retry("Bu konuda canlı veri mevcut değil.", "kısa")


def test_retry_usable_vs_second_no_data():
    good = "192.168.1.101 hostunda RAM 95.5, sağlık skoru 50."
    assert retry_answer_is_usable(good, EVIDENCE)
    assert not retry_answer_is_usable("Canlı veri mevcut değil.", EVIDENCE)
    assert not retry_answer_is_usable("", EVIDENCE)


def test_maybe_fix_uses_retry_when_model_recovers():
    def _gen(**kwargs):
        return {"response": "192.168.1.101 hostunda RAM 95.5, sağlık skoru 50."}

    out, reason = maybe_fix_no_data_answer(
        answer="Bu konuda canlı veri mevcut değil.",
        evidence=EVIDENCE,
        prompt="BAGLAM:\n" + EVIDENCE,
        model="test",
        generate_sync=_gen,
    )
    assert reason == "retry"
    assert "192.168.1.101" in out
    assert not looks_like_no_data_answer(out)


def test_maybe_fix_falls_back_when_retry_still_no_data():
    def _gen(**kwargs):
        return {"response": "Hâlâ canlı veri mevcut değil."}

    out, reason = maybe_fix_no_data_answer(
        answer="Bu konuda canlı veri mevcut değil.",
        evidence=EVIDENCE,
        prompt="p",
        model="test",
        generate_sync=_gen,
    )
    assert reason == "fallback"
    assert "192.168.1.101" in out
    assert not looks_like_no_data_answer(out)


def test_maybe_fix_falls_back_when_generate_raises():
    def _gen(**kwargs):
        raise RuntimeError("llm down")

    out, reason = maybe_fix_no_data_answer(
        answer="Canlı veri mevcut değil.",
        evidence=EVIDENCE,
        prompt="p",
        model="test",
        generate_sync=_gen,
    )
    assert reason == "fallback"
    assert "192.168.1.101" in out


def test_maybe_fix_noop_when_answer_uses_evidence():
    good = "192.168.1.101 hostunda RAM 95.5, sağlık skoru 50."
    out, reason = maybe_fix_no_data_answer(
        answer=good,
        evidence=EVIDENCE,
        prompt="p",
        model="test",
        generate_sync=lambda **k: {"response": "should not run"},
    )
    assert reason == ""
    assert out == good


def test_fallback_truncates():
    out = render_raw_evidence_fallback(EVIDENCE + "x" * 20000, max_chars=500)
    # Adım 8d: kesik/okunamayan JSON ham basılmaz; Adım 15: başlık «model yazamadı; kısa döküm»
    assert "kısa dökümü" in out
    assert '"ok"' not in out and "{" not in out
    assert len(out) < 1200


def test_ignore_heuristic_matches_virt_guard():
    assert answer_ignores_evidence(
        "vCenter bağlantısı sağlanamadı; sağlık raporu gelmedi.", EVIDENCE,
    )
    assert not answer_ignores_evidence(
        "192.168.1.101 hostunda RAM 95.5 seviyesinde, sağlık skoru 50.", EVIDENCE,
    )


def test_invented_ip_is_rejected_even_in_long_answer():
    from app.services.chat_evidence import answer_invents_ips
    long = (
        "Prod-Cluster tek bir ESXi hostu (192.168.1.101) içeriyor. "
        "Ayrıca esx-prod-01 (192.168.1.102) ve esx-prod-02 (192.168.1.103) "
        "gibi hostlar da olabilir. " * 5
    )
    evidence = (
        'host_names=["192.168.1.101","esx-prod-01","esx-prod-02"] '
        "Prod-Cluster hosts=3 ha_verdict=Failover kapasitesi var"
    )
    assert answer_invents_ips(long, evidence)
    assert answer_ignores_evidence(long, evidence)


def test_missing_host_names_while_talking_hosts_is_rejected():
    evidence = (
        "Prod-Cluster host_names=esx-prod-01,esx-prod-02,192.168.1.101 "
        "Lab-Cluster host_names=esx-lab-01 count=3"
    )
    bad = (
        "Prod-Cluster tek bir ESXi hostu içeriyor. "
        "HA yalnızca en az iki hostlu kümede çalışır. "
        "Dolayısıyla VM'ler otomatik kurtarılamaz."
    )
    assert answer_ignores_evidence(bad, evidence)


# ── Adım 15: kapsamlı cevap yanlış reddedilmez; koşul adı döner; "ha" alt-dize hatası yok ──
_EV15 = (
    "[Sanallaştırma sağlık özeti]\n"
    '{"hosts": 15, "alarms": 622, "datastores": 48, "critical": 23, "vm_total": 1563, "ocp_pods": 2410}\n'
    "[Linux]\n{\"servers\": 506, \"disk_high\": 37}\n" * 3
)


def _long_answer(extra: str = "") -> str:
    return (
        "## Genel altyapı durumu\n\n"
        "- Sanallaştırma: 15 host, 622 alarm, 48 datastore izleniyor; 23 kritik uyarı var.\n"
        "- Toplam 1563 sanal makine ve 506 Linux sunucu; 37 sunucuda disk doluluğu yüksek.\n"
        "- OpenShift kümesinde 2410 pod çalışıyor.\n"
        + extra
        + "\n" + ("Ayrıntılar için ilgili modüllere bakabilirsiniz. " * 15)
    )


def test_long_rich_answer_with_one_no_data_line_is_kept():
    from app.services.chat_evidence import evidence_retry_reason
    ans = _long_answer("- Exadata: veri bulunamadı (entegrasyon kapalı).")
    assert len(ans) > 700
    assert evidence_retry_reason(ans, _EV15) == ""
    assert not needs_evidence_retry(ans, _EV15)


def test_short_refusal_still_retried_with_reason():
    from app.services.chat_evidence import evidence_retry_reason
    assert evidence_retry_reason("Bu konuda canlı veri mevcut değil.", _EV15) == "no_data"


def test_long_refusal_without_anchors_still_retried():
    from app.services.chat_evidence import evidence_retry_reason
    ans = "Üzgünüm, ilgili verilere erişimim yok. " + ("Lütfen daha sonra tekrar deneyin. " * 30)
    assert evidence_retry_reason(ans, _EV15) == "no_data"


def test_ignore_reason_names_the_condition():
    from app.services.chat_evidence import ignore_reason
    assert ignore_reason("Sunucu 10.9.8.7 adresinde.", "esx-01.corp 192.168.1.5 " * 10) == "invented_ip"
    ev = "esx-01.local ve esx-02.local hostları: cpu 91 ram 80 disk 70"
    assert ignore_reason("Tek host var ve failover yok.", ev) == "no_names"
    assert ignore_reason("Genel görünüm normal.", ev) == "no_anchor"
    assert ignore_reason("esx-01.local cpu 91 görünüyor.", ev) == ""


def test_ha_substring_no_longer_triggers_no_names():
    """«hata» / «Hangi» içindeki 'ha' tam sözcük değildir → no_names tetiklenmez."""
    from app.services.chat_evidence import ignore_reason
    ev = "esx-01.local ve esx-02.local: cpu 91 ram 80 disk 70 sayaç 123"
    ans = "Hangi sunucuda hata var? Kayıtlı hata yok; değerler 91 ve 80."
    assert ignore_reason(ans, ev) == ""


def test_no_names_not_raised_when_answer_uses_evidence_numbers():
    from app.services.chat_evidence import ignore_reason
    ev = "esx-01.local ve esx-02.local hostları: cpu 91 ram 803 disk 704 sayaç 1234"
    ans = "Genel görünüm: host yükü yüksek; CPU 91, RAM 803, disk 704 ve sayaç 1234 değerleri öne çıkıyor."
    assert ignore_reason(ans, ev) == ""
    assert ignore_reason("Tek host var ve failover yok.", ev) == "no_names"   # eski koruma sürüyor
