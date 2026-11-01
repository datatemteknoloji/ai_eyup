"""Adım 9 — sohbet cache düzeltmesi: tam eşleşme, RBAC imzası, yalnız kavramsal cevap, sabit TTL, kapatma anahtarı, gözlemlenebilirlik."""
from __future__ import annotations

import inspect
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.models.chat_cache import ChatQACache
from app.services import chat_cache_service as cc
from app.services import runtime_settings as rts

ROOT = Path(__file__).resolve().parents[1]
ANS = "Bu, kavramsal bir açıklamadır; ilgili özelliğin ne işe yaradığını ve genel çalışma mantığını anlatır."


@pytest.fixture()
def db():
    eng = create_engine("sqlite://")
    ChatQACache.__table__.create(eng)
    s: Session = sessionmaker(bind=eng)()
    cc.reset_stats()
    yield s
    s.close()


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setattr(rts, "get_bool", lambda k: True if k == "chat_cache_enabled" else False)
    monkeypatch.setattr(rts, "get_int", lambda k: 86400 if k == "chat_cache_ttl_sec" else 0)


def _put(db, q, a=ANS, platform="unified", sig="all", ids=None):
    key = cc.make_context_key(platform, ids or [], sig)
    return cc._store(db, cc._normalize(q), a, key)


# ───────── C1: farklı varlık / benzer soru → yanlış isabet 0 (≥ 40 çift) ─────────
DATA_PAIRS = [  # (ilk soru, benzer ikinci soru) — veri/varlık/yön/zaman farkı
    ("office vCenter'da kaç VM var?", "ZZ-FAKE-vCenter'da kaç VM var?"),
    ("office vCenter'da kaç VM var?", "datatem vCenter'da kaç VM var?"),
    ("oVirt cluster'ında kaç node var mı?", "ZZ-FAKE-OCP cluster'ında kaç node var?"),
    ("prod-db01 sunucusunun cpu kullanımı nedir?", "prod-db02 sunucusunun cpu kullanımı nedir?"),
    ("esx01 hostunda kaç VM çalışıyor?", "esx02 hostunda kaç VM çalışıyor?"),
    ("openshift cluster-a'da kaç pod var?", "openshift cluster-b'de kaç pod var?"),
    ("kapalı VM sayısı kaç?", "açık VM sayısı kaç?"),
    ("son 1 saatte hata veren job sayısı?", "son 1 günde hata veren job sayısı?"),
    ("2025 Aralık'ta kaç VM vardı?", "2025 Ocak'ta kaç VM vardı?"),
    ("şu an kaç VM çalışıyor?", "şu an kaç VM çalışmıyor?"),
    ("vm01 kapalı mı?", "vm01 açık mı?"),
    ("hangi VM en çok CPU kullanıyor?", "hangi VM en az CPU kullanıyor?"),
    ("dün kaç alarm vardı?", "bugün kaç alarm var?"),
    ("web01 diski ne kadar dolu?", "web02 diski ne kadar dolu?"),
    ("db-prod-01 bellek kullanımı nedir?", "db-prod-02 bellek kullanımı nedir?"),
    ("10.0.0.5 sunucusunun durumu nedir?", "10.0.0.6 sunucusunun durumu nedir?"),
    ("node1 NotReady mi?", "node2 NotReady mi?"),
    ("3 node'lu cluster'da kaç pod var?", "5 node'lu cluster'da kaç pod var?"),
    ("bu sunucunun CPU'su nedir?", "bu VM'in CPU'su nedir?"),
    ("benim sunucularım kaç adet?", "bizim sunucularımız kaç adet?"),
]
CONCEPT_PAIRS = [  # kavramsal ama yakın metinli (eski fuzzy ≥0,80 isabet verirdi)
    ("ImagePullBackOff nedir?", "CrashLoopBackOff nedir?"),
    ("Exit code 137 ne demek?", "Exit code 143 ne demek?"),
    ("RunContainerError ne anlama geliyor?", "ImagePullBackOff ne anlama geliyor?"),
    ("vMotion nedir ve nasıl çalışır?", "Storage vMotion nedir ve nasıl çalışır?"),
    ("DRS nedir?", "HA nedir?"),
    ("Pod nedir?", "Node nedir?"),
    ("Requests ile limits farkı nedir?", "Requests ile quotas farkı nedir?"),
    ("PVC nedir?", "PV nedir?"),
    ("LVM nedir?", "RAID nedir?"),
    ("TCP nedir?", "UDP nedir?"),
    ("systemd nedir?", "cron nedir?"),
    ("What is a Deployment?", "What is a DaemonSet?"),
    ("What is vSAN?", "What is NSX?"),
    ("Snapshot nedir?", "Clone nedir?"),
    ("ClusterOperator Degraded ne demek?", "ClusterOperator Available ne demek?"),
    ("Taint nedir?", "Toleration nedir?"),
    ("Ingress nedir?", "Route nedir?"),
    ("Swap nedir?", "Page cache nedir?"),
    ("SELinux nedir?", "AppArmor nedir?"),
    ("Hypervisor nedir?", "Container nedir?"),
]


@pytest.mark.parametrize("first,second", DATA_PAIRS + CONCEPT_PAIRS)
def test_similar_question_never_gets_other_answer(db, first, second):
    _put(db, first, "BİRİNCİ CEVAP " + ANS)  # eğer eski fuzzy olsaydı ikinciye dönerdi
    assert cc.get_cached_answer(db, second, [], platform="unified", rbac_sig="all") is None


def test_pair_set_is_at_least_40():
    assert len(DATA_PAIRS) + len(CONCEPT_PAIRS) >= 40


@pytest.mark.parametrize("q", [p[0] for p in CONCEPT_PAIRS][:8])
def test_conceptual_exact_repeat_hits(db, q):
    assert cc.save_to_cache(db, q, ANS, [], platform="unified", rbac_sig="all") == "saved"
    r = cc.get_cached_answer(db, q, [], platform="unified", rbac_sig="all")
    assert r and r["cached"] and r["answer"] == ANS


def test_normalization_only_case_punct_space(db):
    cc.save_to_cache(db, "ImagePullBackOff   nedir?", ANS, [], platform="unified", rbac_sig="all")
    assert cc.get_cached_answer(db, "imagepullbackoff nedir", [], platform="unified", rbac_sig="all")
    assert not cc.get_cached_answer(db, "imagepullbackoff nedir acaba", [], platform="unified", rbac_sig="all")


def test_no_similarity_function_left_in_service():
    src = inspect.getsource(cc)
    assert "SequenceMatcher" not in src and "_similarity" not in src


# ───────── C2: RBAC / kullanıcı sızıntısı = 0 ─────────
def test_rbac_signature_deterministic_and_distinct():
    a = cc.rbac_signature_for_modules({"linux", "windows"})
    assert a == cc.rbac_signature_for_modules({"windows", "linux"})
    assert a != cc.rbac_signature_for_modules({"linux"})
    assert cc.rbac_signature_for_modules(None) == "all"
    assert cc.rbac_signature_for_modules(set()) != "all"
    assert cc.rbac_signature_for_modules(set()) != cc.rbac_signature_for_modules({"linux"})


def test_admin_entry_not_served_to_restricted_user(db):
    cc.save_to_cache(db, "ImagePullBackOff nedir?", ANS, [], platform="unified", rbac_sig="all")
    restricted = cc.rbac_signature_for_modules({"linux"})
    assert cc.get_cached_answer(db, "ImagePullBackOff nedir?", [], platform="unified", rbac_sig=restricted) is None


def test_restricted_entry_not_served_to_admin_or_other_role(db):
    r1 = cc.rbac_signature_for_modules({"linux"})
    r2 = cc.rbac_signature_for_modules({"linux", "exadata"})
    cc.save_to_cache(db, "Swap nedir?", ANS, [], platform="unified", rbac_sig=r1)
    assert cc.get_cached_answer(db, "Swap nedir?", [], platform="unified", rbac_sig="all") is None
    assert cc.get_cached_answer(db, "Swap nedir?", [], platform="unified", rbac_sig=r2) is None
    assert cc.get_cached_answer(db, "Swap nedir?", [], platform="unified", rbac_sig=r1)


def test_anonymous_signature_isolated(db):
    anon = cc.rbac_signature_for_modules(set())
    cc.save_to_cache(db, "Swap nedir?", ANS, [], platform="unified", rbac_sig="all")
    assert cc.get_cached_answer(db, "Swap nedir?", [], platform="unified", rbac_sig=anon) is None


def test_platform_isolated(db):
    cc.save_to_cache(db, "Swap nedir?", ANS, [], platform="linux", rbac_sig="all")
    assert cc.get_cached_answer(db, "Swap nedir?", [], platform="windows", rbac_sig="all") is None


def test_server_scope_isolated(db):
    cc.save_to_cache(db, "Swap nedir?", ANS, [1, 2], platform="linux", rbac_sig="all")
    assert cc.get_cached_answer(db, "Swap nedir?", [3], platform="linux", rbac_sig="all") is None
    assert cc.get_cached_answer(db, "Swap nedir?", [1, 2], platform="linux", rbac_sig="all")


@pytest.mark.parametrize("fname", ["unified_chat.py", "chat.py", "windows_chat.py"])
def test_chat_routes_pass_rbac_signature(fname):
    src = (ROOT / "api" / fname).read_text(encoding="utf-8")
    assert "get_cached_answer(" in src and "rbac_sig=_cache_sig" in src
    assert src.count("rbac_sig=_cache_sig") >= 2  # okuma + yazma


def test_unified_cache_read_uses_chat_allowed_modules():
    src = (ROOT / "api" / "unified_chat.py").read_text(encoding="utf-8")
    i = src.index("get_cached_answer(\n")
    assert "_chat_allowed_modules(_auth_user, db)" in src[i - 700:i]


def test_feedback_endpoint_requires_auth_and_passes_signature():
    src = (ROOT / "api" / "chat.py").read_text(encoding="utf-8")
    i = src.index("def chat_feedback(")
    assert "get_current_user" in src[i:i + 300]
    assert "rbac_sig=_rbac_signature(user, db)" in src[i:i + 1200]


def test_invalidate_context_removes_all_signatures(db):
    for sig in ("all", cc.rbac_signature_for_modules({"linux"})):
        cc.save_to_cache(db, "Swap nedir?", ANS, [], platform="unified", rbac_sig=sig)
    cc.save_to_cache(db, "Swap nedir?", ANS, [], platform="linux", rbac_sig="all")
    assert cc.invalidate_context(db, platform="unified", all_for_platform=True) == 2
    assert db.query(ChatQACache).count() == 1


def test_invalidate_by_server_ids_removes_scoped_and_global(db):
    cc.save_to_cache(db, "Swap nedir?", ANS, [7], platform="linux", rbac_sig="all")
    cc.save_to_cache(db, "Taint nedir?", ANS, [], platform="linux", rbac_sig="all")
    cc.save_to_cache(db, "Pod nedir?", ANS, [9], platform="linux", rbac_sig="all")
    assert cc.invalidate_context(db, platform="linux", server_ids=[7]) == 2
    assert db.query(ChatQACache).count() == 1


# ───────── C3: bayat cevap yok ─────────
def test_hit_does_not_extend_ttl(db):
    cc.save_to_cache(db, "Swap nedir?", ANS, [], platform="unified", rbac_sig="all")
    row = db.query(ChatQACache).one()
    exp0 = row.expires_at
    for _ in range(12):  # eski tasarımda ≥10 hit → 7 gün
        assert cc.get_cached_answer(db, "Swap nedir?", [], platform="unified", rbac_sig="all")
    db.refresh(row)
    assert row.expires_at == exp0 and row.hit_count == 12


def test_expired_entry_not_served(db):
    cc.save_to_cache(db, "Swap nedir?", ANS, [], platform="unified", rbac_sig="all")
    row = db.query(ChatQACache).one()
    row.expires_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    db.commit()
    assert cc.get_cached_answer(db, "Swap nedir?", [], platform="unified", rbac_sig="all") is None


def test_ttl_comes_from_setting(db, monkeypatch):
    monkeypatch.setattr(rts, "get_int", lambda k: 600 if k == "chat_cache_ttl_sec" else 0)
    cc.save_to_cache(db, "Swap nedir?", ANS, [], platform="unified", rbac_sig="all")
    row = db.query(ChatQACache).one()
    exp = row.expires_at if row.expires_at.tzinfo else row.expires_at.replace(tzinfo=timezone.utc)
    assert timedelta(seconds=540) < exp - datetime.now(timezone.utc) <= timedelta(seconds=600)


def test_no_ttl_extension_code_left():
    src = inspect.getsource(cc)
    assert "_WARM_TTL" not in src and "_HOT_TTL" not in src and "_set_expiry" not in src


@pytest.mark.parametrize("q", [p[0] for p in DATA_PAIRS])
def test_data_questions_never_saved(db, q):
    res = cc.save_to_cache(db, q, ANS, [], platform="unified", rbac_sig="all")
    assert res.startswith("skip:")
    assert db.query(ChatQACache).count() == 0


# ───────── C4: önbelleğe giren/girmeyen cevap tipleri ─────────
Q = "ImagePullBackOff nedir?"


def test_conceptual_answer_saved(db):
    assert cc.save_to_cache(db, Q, ANS, [], platform="unified", rbac_sig="all") == "saved"
    assert cc.save_to_cache(db, Q, ANS + " v2", [], platform="unified", rbac_sig="all") == "updated"
    assert db.query(ChatQACache).count() == 1


@pytest.mark.parametrize("kw,reason", [
    ({"tools_used": ["db_list_vms"]}, "skip:tools_used"),
    ({"live_data": True}, "skip:live_data"),
    ({"modified": True}, "skip:answer_modified_by_verifier"),
    ({"followup": True}, "skip:followup"),
    ({"directive": True}, "skip:directive"),
    ({"ephemeral": True}, "skip:ephemeral"),
])
def test_turn_flags_block_saving(db, kw, reason):
    assert cc.save_to_cache(db, Q, ANS, [], platform="unified", rbac_sig="all", **kw) == reason
    assert db.query(ChatQACache).count() == 0


@pytest.mark.parametrize("bad", [
    "(Hata: uzak model yanıt vermedi, lütfen daha sonra yeniden deneyin lütfen)",
    "Ben salt-okunur asistanım; bu işlemi yapamam, ancak analiz edebilirim ve yardımcı olabilirim.",
    "Bu kaynak bu turda sorgulanmadı; bu nedenle bu konuda bir şey söyleyemem şu an için.",
    "Bu bilgi mevcut verilerde yok; kayıt bulunamadı ve dolayısıyla cevap veremiyorum şimdilik.",
    "SSH bağlantısı kurulamadı bu yüzden cevap veremiyorum, lütfen bağlantıyı kontrol edin tekrar.",
    "kısa cevap",
])
def test_error_refusal_nodata_answers_not_saved(db, bad):
    assert cc.save_to_cache(db, Q, bad, [], platform="unified", rbac_sig="all").startswith("skip:")
    assert db.query(ChatQACache).count() == 0


@pytest.mark.parametrize("q", [
    "hangi sunucular kapalı?", "Merhaba nasılsın", "ok", "esx01 nedir?", "ZZ-FAKE-vCenter nedir?",
    "kube-apiserver nedir?", "Linux load average nasıl yorumlanır?", "bu sunucu neden yavaş?",
])
def test_question_classifier_rejects_non_conceptual(q):
    ok, _ = cc.classify_question(q)
    assert ok is False


@pytest.mark.parametrize("q", [
    "ImagePullBackOff nedir?", "Pod'un exit code 137 ile sonlanması ne demek?", "vMotion nasıl çalışır?",
    "What is a DaemonSet?", "Requests ile limits farkı nedir?",
])
def test_question_classifier_accepts_conceptual(q):
    ok, why = cc.classify_question(q)
    assert ok is True and why == "conceptual"


def test_inventory_summary_template_no_longer_cached():
    src = (ROOT / "api" / "chat.py").read_text(encoding="utf-8")
    i = src.index("INTENT_INVENTORY_SUMMARY:")
    j = src.index('yield _sse({"done": True, "session_id": session_id})', i)
    assert "save_to_cache(" not in src[i:j]


def test_other_deterministic_paths_do_not_save():
    src = (ROOT / "api" / "unified_chat.py").read_text(encoding="utf-8")
    assert src.count("save_to_cache(") == 1  # tek çağrı (LLM final cevabı)


# ───────── C6: kapatma anahtarı ─────────
def test_disabled_switch_blocks_read_and_write(db, monkeypatch):
    cc.save_to_cache(db, Q, ANS, [], platform="unified", rbac_sig="all")
    monkeypatch.setattr(rts, "get_bool", lambda k: False)
    assert cc.get_cached_answer(db, Q, [], platform="unified", rbac_sig="all") is None
    assert cc.save_to_cache(db, "Swap nedir?", ANS, [], platform="unified", rbac_sig="all") == "disabled"
    assert db.query(ChatQACache).count() == 1


def test_settings_schema():
    a, b = rts.ADVANCED_SCHEMA["chat_cache_enabled"], rts.ADVANCED_SCHEMA["chat_cache_ttl_sec"]
    assert a["default"] is True and a["type"] == "bool"
    assert b["default"] == 86400 and b["min"] >= 60


# ───────── C7: gözlemlenebilirlik ─────────
def test_stats_and_info_logs(db, caplog):
    caplog.set_level(logging.INFO, logger="app.services.chat_cache_service")
    cc.save_to_cache(db, "esx01 hostunda kaç VM var?", ANS, [], platform="unified", rbac_sig="all")
    cc.save_to_cache(db, Q, ANS, [], platform="unified", rbac_sig="all")
    cc.get_cached_answer(db, Q, [], platform="unified", rbac_sig="all")
    cc.get_cached_answer(db, "Swap nedir?", [], platform="unified", rbac_sig="all")
    st = cc.get_stats()
    assert st["skip:data_or_time_question"] == 1 and st["saved"] == 1 and st["hit"] == 1 and st["miss"] == 1
    text = caplog.text
    assert "Cache SKIP" in text and "neden=data_or_time_question" in text and "Cache HIT" in text and "Cache SAVED" in text


def test_save_failure_is_logged_not_silent(db, caplog, monkeypatch):
    caplog.set_level(logging.WARNING, logger="app.services.chat_cache_service")
    monkeypatch.setattr(cc, "_store", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cc.save_to_cache(db, Q, ANS, [], platform="unified", rbac_sig="all") == "error"
    assert "Cache save failed" in caplog.text and cc.get_stats()["error"] == 1


def test_routes_report_cache_decision_in_metrics():
    for fname in ("unified_chat.py", "chat.py", "windows_chat.py"):
        assert '"cache": _cache_res' in (ROOT / "api" / fname).read_text(encoding="utf-8")


def test_virt_stream_exposes_from_cache_flag():
    src = (ROOT / "api" / "hypervisors.py").read_text(encoding="utf-8")
    assert '"from_cache": True} if result.get("cached")' in src


# ───────── feedback ─────────
def test_feedback_down_deletes_across_signatures(db):
    for sig in ("all", cc.rbac_signature_for_modules({"linux"})):
        cc.save_to_cache(db, Q, ANS, [], platform="unified", rbac_sig=sig)
    r = cc.apply_feedback(db, platform="unified", question=Q, vote="down")
    assert r["affected"] == 2 and db.query(ChatQACache).count() == 0


def test_feedback_up_skips_non_conceptual(db):
    r = cc.apply_feedback(db, platform="unified", question="esx01 hostunda kaç VM var?", answer=ANS, vote="up", rbac_sig="all")
    assert r["action"] == "skipped" and db.query(ChatQACache).count() == 0


def test_feedback_correction_scoped_to_user_signature(db):
    sig = cc.rbac_signature_for_modules({"linux"})
    r = cc.apply_feedback(db, platform="unified", question="Swap nedir?", correction_text="Düzeltilmiş cevap metni burada.", vote="up", rbac_sig=sig)
    assert r["action"] == "saved"
    assert cc.get_cached_answer(db, "Swap nedir?", [], platform="unified", rbac_sig=sig)
    assert cc.get_cached_answer(db, "Swap nedir?", [], platform="unified", rbac_sig="all") is None


# ───────── C7: «0 yazma» kök nedeni — kullanıcı mesajı önce kaydedildiği için has_prior_messages hep True ─────────
def test_has_prior_messages_is_always_true_after_user_message_saved_root_cause():
    from app.models.chat_session import ChatMessage, ChatSession
    from app.services.chat_history import has_prior_messages, has_real_prior_messages

    eng = create_engine("sqlite://")
    ChatSession.__table__.create(eng)
    ChatMessage.__table__.create(eng)
    s = sessionmaker(bind=eng)()
    s.add(ChatSession(id=1, title="t"))
    s.add(ChatMessage(session_id=1, role="user", content="ImagePullBackOff nedir?"))  # hatlar bunu has_prior'dan ÖNCE yazar
    s.commit()
    assert has_prior_messages(s, 1) is True          # eski sinyal: ilk tur bile «takip» → cache hiç yazılmıyordu
    assert has_real_prior_messages(s, 1) is False    # yeni sinyal: gerçek takip değil
    s.add(ChatMessage(session_id=1, role="assistant", content="cevap"))
    s.add(ChatMessage(session_id=1, role="user", content="peki ya diğeri?"))
    s.commit()
    assert has_real_prior_messages(s, 1) is True
    assert has_real_prior_messages(s, None) is False
    s.close()


@pytest.mark.parametrize("fname", ["unified_chat.py", "chat.py", "windows_chat.py"])
def test_routes_use_real_followup_signal_for_cache(fname):
    src = (ROOT / "api" / fname).read_text(encoding="utf-8")
    assert "has_real_prior_messages(db, session_id)" in src
    assert "followup=_cache_followup" in src
    i = src.index("get_cached_answer(\n")
    assert "_cache_followup" in src[i - 200:i]


def test_orchestrator_done_event_forwards_from_cache():
    src = (ROOT / "services" / "chat_orchestrator" / "service.py").read_text(encoding="utf-8")
    i = src.index('"suggestions": suggestions,')
    assert '"from_cache": True' in src[i:i + 500] and 'flags' in src[i:i + 500]


# ───────── virt: qa_cache HIT ağır araç turunu atlar ─────────
class _FakeRedis:
    def __init__(self):
        self.d, self.incr_calls, self.expire_calls = {}, 0, 0

    def get(self, k):
        return self.d.get(k)

    def incr(self, k):
        self.incr_calls += 1
        return 1

    def expire(self, *a):
        self.expire_calls += 1


def test_qa_cache_peek_does_not_touch_hits_or_ttl(monkeypatch):
    import json
    from app.services import qa_cache
    fr = _FakeRedis()
    monkeypatch.setattr(qa_cache, "_get_redis", lambda: fr)
    fr.d[qa_cache._KEY_PREFIX + qa_cache._cache_key("vMotion nedir?", "m")] = json.dumps({"answer": ANS})
    assert qa_cache.peek_cached_answer("vMotion nedir?", "m")["answer"] == ANS
    assert qa_cache.peek_cached_answer("vMotion nedir? farkı", "m") is None
    assert fr.incr_calls == 0 and fr.expire_calls == 0


def test_virt_stream_skips_agentic_turn_on_conceptual_cache_hit():
    src = (ROOT / "api" / "hypervisors.py").read_text(encoding="utf-8")
    i = src.index("_early_cached = False")
    blk = src[i:i + 1600]
    assert "classify_q" in blk and "peek_cached_answer" in blk and "looks_like_no_data_answer" in blk
    assert "if _early_cached:\n                    live_hint = False" in src
