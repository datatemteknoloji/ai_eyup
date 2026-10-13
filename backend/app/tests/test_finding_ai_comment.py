"""Bulgu AI yorumu: doğrulama kuralları, güven düzeyi, parmak izi, saklama/bayatlık/geri bildirim.

LLM çağrısı sahte (monkeypatch) — canlı modele ve canlı DB'ye dokunulmaz. Tablolar izole test DB'sinde oluşturulur.
Yorum OLAY tabanlıdır: (a) aynı kök bulgular tek yorum paylaşır, (b) diğer bulgular ilişkisiz ayrı listedir.
"""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys

import pytest

from app.models.infra_finding import InfraFinding
from app.services.findings import ai_comment as ac
from app.tests.isolated_db import isolated_db  # noqa: F401


def _facts(**over):
    f = {
        "olay": {"anahtar": "vmware|1|host:h1|hardware", "aile": "hardware", "uye_sayisi": 1, "varlik_turu": "host",
                 "varlik": "192.168.1.101", "platform": "vmware", "cluster": None},
        "olay_bulgulari": [{"id": 1, "kontrol": "hw.host.sensor_alarm", "kategori": "hardware",
                            "baslik": "Donanım sensörü uyarıda", "onem": "high", "durum": "fail", "aktif": True, "detay": "",
                            "oneri_kural": "", "ilk_gorulme": "2026-10-06T11:12:01", "son_gorulme": "2026-10-13T10:25:11",
                            "kanit": {"bad_count": 1, "sensors": [], "vendor": "HP"}}],
        "diger_bulgular": [{"id": 2, "kontrol": "vmw.host.ntp_running", "kategori": "health", "onem": "high",
                            "baslik": "NTP servisi çalışmıyor", "detay": "30 günde 30"}],
        "host_dusarse_etki": {"verdict": "fail", "vms": 10, "memory_gb": 86.0, "unplaced": 10, "remaining_hosts": 0,
                              "ozet_metin": "Bu host kapanırsa 10 VM (86.0 GB Memory) etkilenir."},
        "kural_rehberi": [],
    }
    f.update(over)
    return f


def _content(**over):
    c = {"ozet": "Host 192.168.1.101 sensör alarmı veriyor.", "olay_gorunumu": "Donanım sensörü uyarıda; tek olay.",
         "etki": "Bu host kapanırsa 10 VM (86.0 GB Memory) etkilenir.", "oncelik": "Önce sensör alarmı incelenmeli.",
         "gozlenen": ["Sensör alarmı var", "Uyarı sayısı 1"], "genel_bilgi": ["Sensörler donanım sağlığını izler."],
         "diger_iyilestirmeler": ["NTP servisi çalışmıyor — bu olayla doğrudan ilişkili değil."],
         "bilinmeyenler": ["Sensör türü"]}
    c.update(over)
    return c


# ── doğrulama ────────────────────────────────────────────────────────────────

def test_gecerli_yorum_gecer():
    assert ac.validate(_content(), _facts()) == []


@pytest.mark.parametrize("field,text,needle", [
    ("ozet", "Host üzerinde 47 sensör alarmı var.", "veride olmayan sayı"),
    ("ozet", "Firmware 2.5.1 sürümü etkileniyor.", "sürüm/IP"),
    ("ozet", "Bu sorun KB123456 ile ilgili.", "KB"),
    ("ozet", "CVE-2024-12345 açığı olabilir.", "CVE"),
    ("oncelik", "Önce `esxcli system maintenanceMode set` çalıştırılmalı.", "kod"),
    ("oncelik", "sudo reboot ile yeniden başlatın.", "komut"),
    ("oncelik", "Sorunu düzelttim ve servisi yeniden başlattım.", "eylem"),
    ("oncelik", "The issue was fixed automatically.", "eylem"),
    ("etki", "Bu host 10.0.0.55 adresinde.", "sürüm/IP"),
])
def test_uydurma_ve_eylem_iddiasi_reddedilir(field, text, needle):
    v = ac.validate(_content(**{field: text}), _facts())
    assert v and any(needle in x for x in v), v


def test_veride_olan_sayi_ip_ve_turetilmis_adet_kabul():
    # 86.0 → 86 (aynı sayı), 192.168.1.101 veride; olay üye adedi 1, diğer 1, toplam 2 türetilmiş
    c = _content(ozet="192.168.1.101: 86 GB Memory, 10 VM; 2 bulgu birlikte.")
    assert ac.validate(c, _facts()) == []


def test_tek_haneli_uydurma_sayi_da_reddedilir():
    v = ac.validate(_content(ozet="Son 7 gün içinde alarm var."), _facts())
    assert any("veride olmayan sayı" in x for x in v)


def test_genel_bilgi_rakam_ve_komut_icermez():
    v = ac.validate(_content(genel_bilgi=["30 gün sonra bakılmalı."]), _facts())
    assert any("genel bilgi" in x for x in v)
    v = ac.validate(_content(genel_bilgi=["Gerekirse sudo kullanın."]), _facts())
    assert any("komut" in x for x in v)


def test_komut_veride_varsa_kabul():
    f = _facts()
    f["kural_rehberi"] = [{"tur": "x", "adimlar": ["BMC günlüğünde sudo gerekmez"]}]
    assert ac.validate(_content(oncelik="sudo gerekmez."), f) == []


def test_normalize_sema_ve_ram_memory():
    out, v = ac.normalize({**_content(ozet="86 GB RAM kullanımda."), "ekstra": 1})
    assert v == [] and "Memory" in out["ozet"] and "RAM" not in out["ozet"] and "ekstra" not in out
    out, v = ac.normalize({"ozet": ""})
    assert out is None and v
    out, v = ac.normalize({**_content(), "gozlenen": "metin"})
    assert out is None and any("liste" in x for x in v)


def test_json_ayiklama():
    assert ac.parse_model_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert ac.parse_model_json('Şöyle: {"a": 2} bitti') == {"a": 2}
    assert ac.parse_model_json("düz metin") is None
    assert ac.parse_model_json("") is None


# ── güven ve parmak izi ──────────────────────────────────────────────────────

def test_guven_veri_eksikliginden_hesaplanir():
    c = ac.confidence(_facts())
    assert c["level"] == "medium" and set(c["reasons"]) == {"no_detail", "no_sensor_type"}
    f = _facts()
    f["olay_bulgulari"][0]["detay"] = "red"
    f["olay_bulgulari"][0]["kanit"] = {"sensors": [{"type": "Fan"}], "vendor": "HP"}
    assert ac.confidence(f) == {"level": "high", "reasons": []}
    assert ac.confidence(f, stale_source=True)["level"] == "low"
    thin = _facts(diger_bulgular=[])
    thin["olay_bulgulari"][0]["kanit"] = {}
    assert ac.confidence(thin)["level"] == "low"


def _mut(f, fn):
    g = json.loads(json.dumps(f))
    fn(g)
    return g


def test_parmak_izi_uyeler_durum_ve_etki_ile_degisir():
    f = _facts()
    h = ac.input_hash(f)
    assert h == ac.input_hash(json.loads(json.dumps(f)))
    assert ac.input_hash(_mut(f, lambda g: g["olay_bulgulari"][0].update(durum="pass"))) != h       # üye durumu
    assert ac.input_hash(_mut(f, lambda g: g["olay_bulgulari"][0].update(detay="yeni"))) != h       # üye detayı
    assert ac.input_hash(_mut(f, lambda g: g["olay_bulgulari"].append(                              # yeni üye
        {"id": 9, "kontrol": "hw.host.overall_status", "durum": "fail", "aktif": True, "onem": "low", "detay": ""}))) != h
    assert ac.input_hash(_mut(f, lambda g: g["host_dusarse_etki"].update(vms=11))) != h             # etki girdisi
    assert ac.input_hash(_mut(f, lambda g: g["host_dusarse_etki"].update(ozet_metin="başka"))) == h  # yalnız metin
    assert ac.input_hash(_mut(f, lambda g: g["diger_bulgular"].append({"id": 8, "onem": "low"}))) != h


def test_etki_metni_kodla_uretilir():
    imp = {"verdict": "fail", "vms": 10, "memory_gb": 86.0, "unplaced": 10, "remaining_hosts": 0}
    tr = ac.impact_text(imp, "tr")
    assert "10 VM" in tr and "86.0 GB Memory" in tr and "failover mümkün değil" in tr and "RAM" not in tr
    assert "no other host" in ac.impact_text(imp, "en")


# ── model kaydı / migration dosyaları ────────────────────────────────────────

def test_model_app_models_icinde_kayitli():
    code = ("import app.models; from app.core.database import Base; "
            "print('finding_ai_comments' in Base.metadata.tables, 'finding_ai_feedback' in Base.metadata.tables)")
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(__import__("pathlib").Path(__file__).resolve().parents[2]))
    assert out.stdout.strip().endswith("True True"), out.stdout + out.stderr


def test_tekillik_ve_indeksler_modelde():
    from app.models.finding_ai import FindingAiComment, FindingAiFeedback
    def uniques(t):
        return {tuple(c.name for c in cons.columns) for cons in t.__table__.constraints if cons.__class__.__name__ == "UniqueConstraint"}
    assert ("event_key", "version") in uniques(FindingAiComment)
    assert ("comment_id", "username") in uniques(FindingAiFeedback)
    idx = {i.name for i in FindingAiComment.__table__.indexes}
    assert "ix_finding_ai_comments_event_key" in idx


def _mig(name):
    import pathlib
    p = pathlib.Path(__file__).resolve().parents[2] / "migrations" / name
    if not p.exists():
        pytest.skip("migrations/ container imajında (bağlı değil); dosya ana makinede doğrulanır")
    return p.read_text(encoding="utf-8")


def test_migration_dosyasi_modelle_tutarli():
    sql = _mig("add_finding_ai_comments.sql")
    assert "CREATE TABLE IF NOT EXISTS finding_ai_comments" in sql and "CREATE TABLE IF NOT EXISTS finding_ai_feedback" in sql
    assert "ALTER TABLE" not in sql and "ÇALIŞTIRILMADI" not in sql
    assert "UNIQUE (event_key, version)" in sql and "UNIQUE (comment_id, username)" in sql
    from app.models.finding_ai import FindingAiComment, FindingAiFeedback
    for m in (FindingAiComment, FindingAiFeedback):
        for col in m.__table__.columns:
            assert col.name in sql, (m.__tablename__, col.name)


def test_rollback_dosyasi_iki_tabloyu_dusurur():
    sql = _mig("rollback_finding_ai_comments.sql")
    assert "DROP TABLE IF EXISTS finding_ai_feedback" in sql and "DROP TABLE IF EXISTS finding_ai_comments" in sql
    assert sql.index("finding_ai_feedback") < sql.index("finding_ai_comments;")      # önce bağımlı tablo


# ── saklama / bayatlık / geri bildirim (izole DB, sahte LLM) ─────────────────

@pytest.fixture()
def ai_db(isolated_db):  # noqa: F811
    from app.models.finding_ai import FindingAiComment, FindingAiFeedback
    eng = isolated_db.get_bind()
    FindingAiComment.__table__.create(eng, checkfirst=True)
    FindingAiFeedback.__table__.create(eng, checkfirst=True)
    return isolated_db


def _row(db, **kw):
    r = InfraFinding(platform="vmware", source_id=1, source_name="vc", category=kw.get("category", "hardware"),
                     check_id=kw.get("check_id", "hw.host.sensor_alarm"),
                     entity_kind="host", entity_ref=kw.get("entity_ref", "host:h1"), entity_name="esx01",
                     result=kw.get("result", "fail"), severity=kw.get("severity", "high"),
                     title=kw.get("title", "Donanım sensörü uyarıda"), detail=kw.get("detail", "red"),
                     evidence={"vendor": "HP"}, active=kw.get("active", True))
    db.add(r); db.commit(); db.refresh(r)
    return r


def _fake_llm(monkeypatch, replies):
    calls = []

    async def fake(db, prompt, system):
        calls.append(prompt)
        return replies[min(len(calls) - 1, len(replies) - 1)]
    monkeypatch.setattr(ac, "_ask", fake)
    monkeypatch.setattr("app.core.config.get_active_model", lambda db: "test-model")
    return calls


GOOD = json.dumps({"ozet": "esx01 sensör alarmı veriyor.", "olay_gorunumu": "Başka ilişkili bulgu yok.",
                   "etki": "etki hesaplanamadı.", "oncelik": "Önce sensör alarmı incelenmeli.",
                   "gozlenen": ["Donanım sensörü uyarıda"], "genel_bilgi": ["Sensörler donanım sağlığını izler."],
                   "diger_iyilestirmeler": [], "bilinmeyenler": ["Sensör türü"]}, ensure_ascii=False)
BAD = json.dumps({**json.loads(GOOD), "ozet": "esx01 üzerinde 47 sensör alarmı var."}, ensure_ascii=False)


def test_uret_sakla_bayat_ve_yeniden_uret(ai_db, monkeypatch):
    row = _row(ai_db)
    _fake_llm(monkeypatch, [GOOD])
    assert ac.get_state(ai_db, row, locale="tr", username="u")["comment"] is None
    r = asyncio.run(ac.generate(ai_db, row, locale="tr", user="u"))
    assert r["version"] == 1 and r["confidence"]["level"] in ("high", "medium", "low")
    st = ac.get_state(ai_db, row, locale="tr", username="u")["comment"]
    assert st["stale"] is False and st["generated_at"] and st["model"] == "test-model"
    row.detail = "yeni detay"; ai_db.commit()                                  # bulgu değişti
    assert ac.get_state(ai_db, row, locale="tr", username="u")["comment"]["stale"] is True
    r2 = asyncio.run(ac.generate(ai_db, row, locale="tr", user="u"))           # yeniden üret
    assert r2["version"] == 2
    st2 = ac.get_state(ai_db, row, locale="tr", username="u")["comment"]
    assert st2["version"] == 2 and st2["stale"] is False and st2["revisions"] == 2


def test_ihlalde_bir_kez_yeniden_dener_ve_duzelirse_kabul(ai_db, monkeypatch):
    row = _row(ai_db)
    calls = _fake_llm(monkeypatch, [BAD, GOOD])
    r = asyncio.run(ac.generate(ai_db, row, locale="tr", user="u"))
    assert len(calls) == 2 and r["validation"]["attempts"] == 2 and r["validation"]["violations_first_try"]
    assert "veride olmayan sayı" in calls[1]                                   # ihlal geri bildirimi modele iletildi


def test_iki_denemede_de_gecmezse_reddedilir_ve_saklanmaz(ai_db, monkeypatch):
    row = _row(ai_db)
    _fake_llm(monkeypatch, [BAD, BAD])
    with pytest.raises(ac.AiCommentRejected):
        asyncio.run(ac.generate(ai_db, row, locale="tr", user="u"))
    assert ac.get_state(ai_db, row, locale="tr", username="u")["comment"] is None


def test_json_degilse_reddedilir(ai_db, monkeypatch):
    row = _row(ai_db)
    _fake_llm(monkeypatch, ["bu bir JSON değil", "yine değil"])
    with pytest.raises(ac.AiCommentRejected):
        asyncio.run(ac.generate(ai_db, row, locale="tr", user="u"))


def test_desteklenmeyen_kategori(ai_db, monkeypatch):
    row = _row(ai_db)
    row.category = "reclaim"; ai_db.commit()
    with pytest.raises(ValueError):
        asyncio.run(ac.generate(ai_db, row, locale="tr", user="u"))
    assert ac.get_state(ai_db, row, locale="tr", username="u")["reason"] == "unsupported_category"


def test_dry_run_saklamaz(ai_db, monkeypatch):
    row = _row(ai_db)
    _fake_llm(monkeypatch, [GOOD])
    asyncio.run(ac.generate(ai_db, row, locale="tr", user="u", persist=False))
    assert ac.get_state(ai_db, row, locale="tr", username="u")["comment"] is None


def test_geri_bildirim_kullanici_basina_tek_oy(ai_db, monkeypatch):
    row = _row(ai_db)
    _fake_llm(monkeypatch, [GOOD])
    r = asyncio.run(ac.generate(ai_db, row, locale="tr", user="u"))
    assert ac.submit_feedback(ai_db, row, comment_id=r["id"], username="a", helpful=True) == {"mine": True, "helpful": 1, "not_helpful": 0}
    out = ac.submit_feedback(ai_db, row, comment_id=r["id"], username="a", helpful=False, note="yanlış")   # oy değişir
    assert out == {"mine": False, "helpful": 0, "not_helpful": 1}
    out = ac.submit_feedback(ai_db, row, comment_id=r["id"], username="b", helpful=True)
    assert out["helpful"] == 1 and out["not_helpful"] == 1
    assert ac.get_state(ai_db, row, locale="tr", username="b")["comment"]["feedback"]["mine"] is True
    with pytest.raises(LookupError):
        ac.submit_feedback(ai_db, row, comment_id=99999, username="a", helpful=True)


def test_tablo_yoksa_available_false(isolated_db):  # noqa: F811
    from app.models.finding_ai import FindingAiComment, FindingAiFeedback
    eng = isolated_db.get_bind()
    FindingAiFeedback.__table__.drop(eng, checkfirst=True)
    FindingAiComment.__table__.drop(eng, checkfirst=True)
    row = _row(isolated_db)
    st = ac.get_state(isolated_db, row, locale="tr", username="u")
    assert st["available"] is False and st["reason"] == "tables_missing"
    assert ac.tables_ready(isolated_db) is False


# ── kesin hüküm yumuşatma (deterministik; LLM yok) ───────────────────────────

def _sf(text, **facts_over):
    f = _facts(**facts_over)
    return ac.soften_text(text, f, json.dumps(f, ensure_ascii=False).lower())


@pytest.mark.parametrize("src,expect,rule", [
    ("Bu durum VM'lerin çalışmasını durdurur.", "Bu durum VM'lerin çalışmasını durdurabilir.", "tr_durdur"),
    ("Alarm veri kaybına yol açar.", "Alarm veri kaybına yol açabilir.", "tr_yol_ac"),
    ("Bu durumda kesinti olur.", "Bu durumda kesinti olabilir.", "tr_kesinti_olur"),
    ("Hizmet kesintiye uğrar.", "Hizmet kesintiye uğrayabilir.", "tr_kesintiye_ugrar"),
    ("Bu durum 10 VM'yi tehlikeye atıyor.", "Bu durum 10 VM'yi tehlikeye atabilir.", "tr_tehlike"),
    ("Sistem çöker.", "Sistem çökebilir.", "tr_coker"),
    ("Bu alarm hostun genel sağlığını olumsuz etkiliyor.", "Bu alarm hostun genel sağlığını olumsuz etkileyebilir.", "tr_etkiliyor"),
    ("This negatively affects the host.", "This may negatively affect the host.", "en_affects"),
    ("This leads to downtime.", "This may lead to downtime.", "en_leads"),
    ("The host will stop serving VMs.", "The host may stop serving VMs.", "en_will"),
])
def test_desteksiz_kesin_hukum_olasilik_diline_cevrilir(src, expect, rule):
    out, ch = _sf(src)
    assert out == expect
    assert len(ch) == 1 and ch[0]["rule"] == rule and ch[0]["before"] == src and ch[0]["after"] == expect


def test_yalniz_ilgili_cumle_degisir_bosluklar_korunur():
    src = "Sensör alarmı var. Bu durum VM'lerin çalışmasını durdurur. NTP servisi çalışmıyor."
    out, ch = _sf(src)
    assert out == "Sensör alarmı var. Bu durum VM'lerin çalışmasını durdurabilir. NTP servisi çalışmıyor."
    assert len(ch) == 1


def test_zaten_ihtiyatli_ifade_ve_gozlem_degismez():
    for s in ("Bu durum VM'leri etkileyebilir.", "Kesinti riski vardır.", "NTP servisi çalışmıyor.", "It may stop."):
        out, ch = _sf(s)
        assert out == s and ch == []


def test_kodla_yazilmis_etki_cumlesi_ve_kural_rehberi_dokunulmaz():
    # etki cümlesi 'sığmaz' içerir; hesap 'fail' dese de, 'fit' dese de kodun cümlesi aynen kalır
    sent = "Bu host kapanırsa 10 VM (86.0 GB Memory) etkilenir; kalan host sayısı: 0."
    f = _facts()
    f["host_dusarse_etki"]["ozet_metin"] = sent + " Sonuç: VM'ler sığmaz."
    out, ch = ac.soften_text("Sonuç: VM'ler sığmaz.", f, json.dumps(f, ensure_ascii=False).lower())
    assert out == "Sonuç: VM'ler sığmaz." and ch == []
    f["kural_rehberi"] = [{"tur": "x", "etki": "Kalan PSU de düşerse host kapanır durur."}]
    out, ch = ac.soften_text("Kalan PSU de düşerse host kapanır durur.", f, json.dumps(f, ensure_ascii=False).lower())
    assert ch == []


def test_sigmaz_yalniz_hesap_fail_diyorsa_kalir():
    # fail: 'VM'ler diğer host'lara sığmaz' desteklenir
    out, ch = _sf("Bu host düşerse VM'ler diğer host'lara sığmaz.")
    assert out == "Bu host düşerse VM'ler diğer host'lara sığmaz." and ch == []
    out, ch = _sf("Failover mümkün değil.")
    assert ch == []
    # fit: desteksiz → yumuşatılır
    fit = {"host_dusarse_etki": {"verdict": "fit", "vms": 2, "memory_gb": 10.0, "unplaced": 0, "remaining_hosts": 2, "ozet_metin": "x"}}
    out, ch = _sf("Bu host düşerse VM'ler diğer host'lara sığmaz.", **fit)
    assert out == "Bu host düşerse VM'ler diğer host'lara sığmayabilir." and ch[0]["rule"] == "tr_sigmaz"
    # etki hiç yok: desteksiz
    out, ch = _sf("The VMs do not fit on other hosts.", host_dusarse_etki=None)
    assert out == "The VMs may not fit on other hosts." and ch[0]["rule"] == "en_nofit"


def test_soften_tum_alanlar_ve_listeler():
    c = _content(oncelik="Alarm veri kaybına yol açar.", gozlenen=["Sensör alarmı var", "NTP durur"],
                 genel_bilgi=["Fan arızası sıcaklığı artırır ve sistemi durdurur."])
    out, log = ac.soften(c, _facts())
    assert out["oncelik"] == "Alarm veri kaybına yol açabilir."
    assert out["gozlenen"] == ["Sensör alarmı var", "NTP durabilir"]
    assert out["genel_bilgi"] == ["Fan arızası sıcaklığı artırır ve sistemi durdurabilir."]
    assert {x["field"] for x in log} == {"oncelik", "gozlenen[1]", "genel_bilgi[0]"}
    assert out["ozet"] == c["ozet"] and c["oncelik"] == "Alarm veri kaybına yol açar."   # girdi değiştirilmez


def test_yumusatma_dogrulamayi_bozmaz():
    c = _content(oncelik="Alarm veri kaybına yol açar.", genel_bilgi=["Fan arızası sistemi durdurur."])
    out, _ = ac.soften(c, _facts())
    assert ac.validate(out, _facts()) == []


def test_generate_yumusatilan_cumleler_validation_alaninda_ikinci_llm_yok(ai_db, monkeypatch):
    row = _row(ai_db)
    reply = json.dumps({**json.loads(GOOD), "etki": "Bu durum VM'lerin çalışmasını durdurur.",
                        "gozlenen": ["Donanım sensörü uyarıda"]}, ensure_ascii=False)
    calls = _fake_llm(monkeypatch, [reply])
    r = asyncio.run(ac.generate(ai_db, row, locale="tr", user="u"))
    assert len(calls) == 1                                                      # ikinci LLM çağrısı yok, yeniden üretim yok
    assert r["content"]["etki"] == "Bu durum VM'lerin çalışmasını durdurabilir."
    v = r["validation"]
    assert v["attempts"] == 1 and v["softened_count"] == 1
    assert v["softened_sentences"][0]["field"] == "etki" and v["softened_sentences"][0]["rule"] == "tr_durdur"
    from app.models.finding_ai import FindingAiComment                          # saklanan satırda da var (yeni tablo/alan yok)
    stored = ai_db.query(FindingAiComment).filter(FindingAiComment.id == r["id"]).one()
    assert stored.validation["softened_sentences"] == v["softened_sentences"]
    assert stored.content["etki"].endswith("durdurabilir.")


def test_yumusatma_yoksa_bos_liste(ai_db, monkeypatch):
    row = _row(ai_db)
    _fake_llm(monkeypatch, [GOOD])
    r = asyncio.run(ac.generate(ai_db, row, locale="tr", user="u", persist=False))
    assert r["validation"]["softened_count"] == 0 and r["validation"]["softened_sentences"] == []


def test_yumusatma_loglanir(ai_db, monkeypatch, caplog):
    import logging
    row = _row(ai_db)
    reply = json.dumps({**json.loads(GOOD), "etki": "Alarm veri kaybına yol açar."}, ensure_ascii=False)
    _fake_llm(monkeypatch, [reply])
    with caplog.at_level(logging.INFO, logger=ac.logger.name):
        asyncio.run(ac.generate(ai_db, row, locale="tr", user="u", persist=False))
    assert any("yumuşatıldı" in r.getMessage() for r in caplog.records)


# ═════════════════════════════════════════════════════════════════════════════
# OLAY tabanlı yorum: (a)/(b) ayrımı, tek yorum, öneri-gerçek denetimi, yumuşatma ince ayarı, saklama
# ═════════════════════════════════════════════════════════════════════════════
from app.services.findings import ai_postprocess as pp          # noqa: E402
from app.services.findings import events as fev                 # noqa: E402


def test_olay_ailesi_ve_anahtari():
    assert fev.family_of("hw.host.sensor_alarm", "host") == "hardware"
    for c in ("hw.host.overall_status", "hw.host.sensor_repeat", "hw.host.event_pattern", "hw.host.config_issue"):
        assert fev.family_of(c, "host") == "hardware"
    assert fev.family_of("vmw.host.ntp_running", "host") == fev.family_of("vmw.host.ntp_configured", "host") == "time_sync"
    assert fev.family_of("cmp.host.ssh_disabled", "host") == "cmp.host.ssh_disabled"        # tanımsız: tek üyeli olay
    assert fev.family_of("hw.host.sensor_alarm", "vm") == "hw.host.sensor_alarm"            # yalnız host'ta gruplanır


def test_olay_ayrimi_a_b_ve_ortak_anahtar(ai_db):
    r1 = _row(ai_db)
    r2 = _row(ai_db, check_id="hw.host.overall_status", title="Genel durum kırmızı", severity="critical")
    r3 = _row(ai_db, check_id="hw.host.sensor_repeat", title="Sensör alarmı tekrarlıyor", severity="medium")
    o1 = _row(ai_db, check_id="vmw.host.ntp_running", category="health", title="NTP servisi çalışmıyor")
    o2 = _row(ai_db, check_id="hw.host.sensor_alarm", entity_ref="host:h2")                  # başka host
    sp = fev.event_split(ai_db, r3)
    assert {m.id for m in sp["members"]} == {r1.id, r2.id, r3.id}
    assert [o.id for o in sp["others"]] == [o1.id]                                          # (b): aynı host, başka aile
    assert sp["representative_id"] == r1.id
    keys = {fev.event_key(r) for r in (r1, r2, r3)}
    assert len(keys) == 1 and keys != {fev.event_key(o1)} and fev.event_key(o2) not in keys
    assert fev.event_key(r1) == "vmware|1|host:h1|hardware"


def test_facts_a_ve_b_ayri_verilir(ai_db):
    r1 = _row(ai_db)
    _row(ai_db, check_id="hw.host.overall_status", title="Genel durum kırmızı")
    _row(ai_db, check_id="vmw.host.ntp_running", category="health", title="NTP servisi çalışmıyor")
    f = ac.build_facts(ai_db, r1, "tr")
    assert f["olay"]["uye_sayisi"] == 2 and {m["kontrol"] for m in f["olay_bulgulari"]} == {"hw.host.sensor_alarm", "hw.host.overall_status"}
    assert [o["kontrol"] for o in f["diger_bulgular"]] == ["vmw.host.ntp_running"]
    assert "iliskili_bulgular" not in f and "bulgu" not in f


def test_context_ilgili_listesi_a_b_bolunmus_ve_geriye_uyumlu(ai_db):
    from app.services.findings.context import finding_context
    r1 = _row(ai_db)
    r2 = _row(ai_db, check_id="hw.host.overall_status", title="Genel durum kırmızı")
    o1 = _row(ai_db, check_id="vmw.host.ntp_running", category="health", title="NTP servisi çalışmıyor")
    c = finding_context(ai_db, r1)
    assert {x["id"] for x in c["related"]} == {r2.id, o1.id}                  # eski alan: hepsi (geriye uyumlu)
    assert [x["id"] for x in c["related_event"]] == [r2.id]
    assert [x["id"] for x in c["related_other"]] == [o1.id]
    assert sorted(c["event"]["member_ids"]) == [r1.id, r2.id] and c["event"]["key"].endswith("|hardware")


def test_tek_olay_tek_yorum_tum_uyelerde_ayni(ai_db, monkeypatch):
    r1 = _row(ai_db)
    r2 = _row(ai_db, check_id="hw.host.overall_status", title="Genel durum kırmızı")
    r3 = _row(ai_db, check_id="hw.host.sensor_repeat", title="Sensör alarmı tekrarlıyor")
    calls = _fake_llm(monkeypatch, [GOOD])
    res = asyncio.run(ac.generate(ai_db, r2, locale="tr", user="u"))               # herhangi bir üyeden üretilir
    assert len(calls) == 1 and res["version"] == 1
    states = [ac.get_state(ai_db, r, locale="tr", username="u")["comment"] for r in (r1, r2, r3)]
    assert all(s and s["id"] == res["id"] and s["content"] == states[0]["content"] for s in states)
    assert sorted(states[0]["event"]["member_ids"]) == sorted([r1.id, r2.id, r3.id]) and states[0]["event"]["representative_id"] == r1.id
    # yeniden üretim aynı olay anahtarında v2; başka üyeden üretilse bile
    res2 = asyncio.run(ac.generate(ai_db, r3, locale="tr", user="u"))
    assert res2["version"] == 2 and ac.get_state(ai_db, r1, locale="tr", username="u")["comment"]["version"] == 2
    # geri bildirim olayın herhangi bir üyesinden yapılır
    assert ac.submit_feedback(ai_db, r3, comment_id=res2["id"], username="a", helpful=True)["helpful"] == 1
    assert ac.get_state(ai_db, r1, locale="tr", username="a")["comment"]["feedback"]["mine"] is True


def test_baska_olay_yorumu_paylasmaz(ai_db, monkeypatch):
    r1 = _row(ai_db)
    o1 = _row(ai_db, check_id="vmw.host.ntp_running", category="health", title="NTP servisi çalışmıyor")
    _fake_llm(monkeypatch, [GOOD])
    asyncio.run(ac.generate(ai_db, r1, locale="tr", user="u"))
    assert ac.get_state(ai_db, o1, locale="tr", username="u")["comment"] is None


def test_olay_uyesi_degisince_yorum_bayat(ai_db, monkeypatch):
    r1 = _row(ai_db)
    _fake_llm(monkeypatch, [GOOD])
    asyncio.run(ac.generate(ai_db, r1, locale="tr", user="u"))
    assert ac.get_state(ai_db, r1, locale="tr", username="u")["comment"]["stale"] is False
    _row(ai_db, check_id="hw.host.overall_status", title="Genel durum kırmızı")      # olaya yeni üye
    assert ac.get_state(ai_db, r1, locale="tr", username="u")["comment"]["stale"] is True


def test_b_bulgusu_olay_anlatiminda_gecerse_reddedilir_ve_gozlenenden_dusurulur():
    f = _facts()
    v = ac.validate(_content(olay_gorunumu="NTP servisi çalışmıyor ve bu da sensörü tetikledi."), f)
    assert any("olayla ilişkisiz" in x for x in v)
    v = ac.validate(_content(oncelik="Önce vmw.host.ntp_running ele alınmalı."), f)
    assert any("olayla ilişkisiz" in x for x in v)
    # diger_iyilestirmeler'de serbest
    assert ac.validate(_content(diger_iyilestirmeler=["NTP servisi çalışmıyor — olayla ilişkili değil."]), f) == []
    out, dropped = ac.drop_unrelated_items(_content(gozlenen=["Sensör alarmı var", "NTP servisi çalışmıyor"]), f)
    assert out["gozlenen"] == ["Sensör alarmı var"] and dropped[0]["item"] == "NTP servisi çalışmıyor"


def test_normalize_diger_iyilestirmeler_opsiyonel_liste():
    c = {k: v for k, v in _content().items() if k != "diger_iyilestirmeler"}
    out, v = ac.normalize(c)
    assert v == [] and out["diger_iyilestirmeler"] == []
    out, v = ac.normalize({**_content(), "diger_iyilestirmeler": "metin"})
    assert out is None and any("liste" in x for x in v)


def test_generate_gozlenende_b_atfi_dusurur_telemetri(ai_db, monkeypatch):
    r1 = _row(ai_db)
    _row(ai_db, check_id="vmw.host.ntp_running", category="health", title="NTP servisi çalışmıyor")
    reply = json.dumps({**json.loads(GOOD), "gozlenen": ["Donanım sensörü uyarıda", "NTP servisi çalışmıyor"],
                        "diger_iyilestirmeler": ["NTP servisi çalışmıyor — bu olayla doğrudan ilişkili değil."]}, ensure_ascii=False)
    _fake_llm(monkeypatch, [reply])
    r = asyncio.run(ac.generate(ai_db, r1, locale="tr", user="u", persist=False))
    assert r["content"]["gozlenen"] == ["Donanım sensörü uyarıda"]
    assert r["validation"]["dropped_unrelated_items"][0]["item"] == "NTP servisi çalışmıyor"
    assert "ilişkili değil" in r["content"]["diger_iyilestirmeler"][0]


# ── öneri ↔ gerçek denetimi ──────────────────────────────────────────────────

ALT_TR = "başka bir cluster'a taşımayı veya bakım penceresi planlamayı değerlendirin"


@pytest.mark.parametrize("src", [
    "Önce VM'lerin başka host'lara tahliye edilmesi önerilir.",
    "VM'leri vMotion ile taşıyın.",
    "Bakım öncesi VM'ler migrate edilmeli.",
    "Host boşaltılmalı (drain).",
    "Consider evacuating the VMs first.",
])
def test_kalan_host_sifirsa_tasima_onerisi_sabit_alternatife_donusur(src):
    lang = "en" if src.startswith("Consider") else "tr"
    c = _content(oncelik=src)
    out, log, prot = pp.fix_recommendations(c, _facts(), lang)
    assert log and log[0]["rule"] == "no_remaining_host" and log[0]["before"] == src
    if lang == "tr":
        assert ALT_TR in out["oncelik"] and "mümkün değil" in out["oncelik"]
    else:
        assert "another cluster" in out["oncelik"] and "maintenance window" in out["oncelik"]
    assert c["oncelik"] == src                                              # girdi değişmez


def test_kalan_host_varsa_tasima_onerisi_dokunulmaz_ve_alan_ici_tek_alternatif():
    f = _facts()
    f["host_dusarse_etki"]["remaining_hosts"] = 2
    c = _content(oncelik="VM'lerin tahliye edilmesi önerilir.")
    out, log, _ = pp.fix_recommendations(c, f, "tr")
    assert out == c and log == []
    f["host_dusarse_etki"]["remaining_hosts"] = 0
    c = _content(oncelik="VM'leri tahliye edin. Sonra vMotion ile taşıyın. Sensörü inceleyin.")
    out, log, _ = pp.fix_recommendations(c, f, "tr")
    assert out["oncelik"].count(ALT_TR) == 1 and "Sensörü inceleyin." in out["oncelik"] and len(log) == 2
    # etki yoksa dokunma
    out, log, _ = pp.fix_recommendations(_content(oncelik="VM'leri tahliye edin."), _facts(host_dusarse_etki=None), "tr")
    assert log == []


def test_alternatif_cumle_zaten_cluster_bakim_diyorsa_degismez():
    c = _content(oncelik="VM'leri başka bir cluster'a taşımayı değerlendirin.")
    out, log, _ = pp.fix_recommendations(c, _facts(), "tr")
    assert log == [] and out == c


def test_oneri_duzeltme_telemetrisi_validation_alaninda(ai_db, monkeypatch):
    r1 = _row(ai_db)
    reply = json.dumps({**json.loads(GOOD), "oncelik": "Önce VM'ler başka host'lara tahliye edilmeli."}, ensure_ascii=False)
    _fake_llm(monkeypatch, [reply])
    monkeypatch.setattr(ac.fctx, "host_impact", lambda db, row: {"available": True, "cluster": "A", "verdict": "fail",
                        "limiting": ["no_host"], "vms": 10, "memory_gb": 86.0, "unplaced": 10, "remaining_hosts": 0,
                        "after_memory_pct": None, "threshold_pct": 85})
    r = asyncio.run(ac.generate(ai_db, r1, locale="tr", user="u", persist=False))
    assert ALT_TR in r["content"]["oncelik"]
    rf = r["validation"]["recommendation_fixes"]
    assert rf and rf[0]["field"] == "oncelik" and rf[0]["rule"] == "no_remaining_host"
    assert ac.validate(r["content"], r["facts"]) == []                       # düzeltilmiş cümle doğrulamayı bozmaz


# ── yumuşatma ince ayarı ─────────────────────────────────────────────────────

def test_fail_iken_senaryo_sonucu_cumleleri_yumusatilmaz_etki_alaninda():
    f = _facts()
    c = _content(etki="Host kapanırsa VM'ler çalışmaya devam edemez. Alarm kesintiye uğrar.")
    out, log = pp.soften(c, f)
    # fail + etki alanı: 'kesintiye uğrar' senaryo sonucu → desteklenir, kalır
    assert out["etki"] == c["etki"] and log == []


def test_fail_degilse_ayni_cumle_yumusatilir():
    f = _facts()
    f["host_dusarse_etki"]["verdict"] = "fit"
    out, log = pp.soften(_content(etki="Hizmet kesintiye uğrar."), f)
    assert out["etki"] == "Hizmet kesintiye uğrayabilir." and log[0]["rule"] == "tr_kesintiye_ugrar"


def test_fail_olsa_da_senaryo_disi_alanda_ve_veri_kaybinda_yumusatilir():
    f = _facts()
    out, log = pp.soften(_content(ozet="Alarm hizmeti durdurur.", etki="Host kapanırsa veri kaybı yaşanır."), f)
    assert out["ozet"] == "Alarm hizmeti durdurabilir."                      # ozet: senaryo bağlamı yok
    assert out["etki"] == "Host kapanırsa veri kaybı yaşanabilir."           # hesap veri kaybını göstermez
    # ozet'te açık senaryo ifadesi varsa fail ile desteklenir
    out, log = pp.soften(_content(oncelik="Host düşerse hizmet kesintiye uğrar."), f)
    assert out["oncelik"] == "Host düşerse hizmet kesintiye uğrar." and log == []


def test_belirsiz_bu_durum_fail_iken_senaryoyu_acik_yazar():
    f = _facts()
    out, log = pp.soften(_content(etki="Bu durum çalışan VM'leri etkiler. Ek not."), f)
    assert out["etki"].startswith("Host kapanırsa bu VM'ler çalışmaya devam edemez; kapsamda başka host yok.")
    assert out["etki"].endswith("Ek not.") and log[0]["rule"] == "vague_to_scenario"
    out2, _ = pp.soften(_content(etki="Bu durum A. Bu sonuç B."), f)
    assert out2["etki"].count("Host kapanırsa bu VM'ler çalışmaya devam edemez") == 1   # tekrar etmez
    # kalan host > 0 → farklı cümle
    f["host_dusarse_etki"]["remaining_hosts"] = 2
    out3, _ = pp.soften(_content(etki="Bu durum sorun yaratır."), f)
    assert out3["etki"] == "Host kapanırsa bu VM'ler kalan host'lara sığmaz."
    en, _ = pp.soften(_content(etki="This situation is bad."), _facts(), "en")
    assert en["etki"] == "If the host goes down, these VMs cannot keep running; there is no other host in scope."


def test_belirsiz_bu_durum_fail_degilse_oneklenir_ve_etkisizse_dokunulmaz():
    f = _facts()
    f["host_dusarse_etki"]["verdict"] = "fit"
    out, log = pp.soften(_content(etki="Bu durum çalışan VM'leri etkiler."), f)
    assert out["etki"] == "Host kapanırsa bu durum çalışan VM'leri etkiler." and log[0]["rule"] == "vague_prefix"
    out, log = pp.soften(_content(etki="Bu durum çalışan VM'leri etkiler."), _facts(host_dusarse_etki=None))
    assert log == []
    out, log = pp.soften(_content(oncelik="Bu durum önemli."), _facts())          # yalnız etki alanında
    assert log == []


def test_yumusatilmamis_kesin_cumle_sayilir():
    f = _facts()
    f["host_dusarse_etki"]["verdict"] = "fit"
    # 'bozulur' sözlükte yok → yumuşatılmaz ama kesin hüküm → sayılır
    c = _content(ozet="Fan arızası sistemde kesinti yaratır.", genel_bilgi=["Sıcaklık artarsa sistem hizmet dışı kalır."])
    out, post = ac.postprocess(c, f, "tr")
    assert out["ozet"] == c["ozet"]
    assert post["unsoftened_definitive_count"] == 2
    assert {x["field"] for x in post["unsoftened_definitive"]} == {"ozet", "genel_bilgi[0]"}
    # ihtiyatlı / gözlem / yumuşatılmış cümleler sayılmaz
    ok = _content(ozet="Kesinti riski vardır. NTP servisi çalışmaması gözlendi. Alarm hizmeti durdurur.")
    out, post = ac.postprocess(ok, f, "tr")
    assert post["unsoftened_definitive_count"] == 0 and post["softened_count"] == 1


def test_unsoftened_sayisi_validation_ve_logda(ai_db, monkeypatch, caplog):
    import logging
    r1 = _row(ai_db)
    reply = json.dumps({**json.loads(GOOD), "ozet": "Fan arızası sistemde kesinti yaratır."}, ensure_ascii=False)
    _fake_llm(monkeypatch, [reply])
    with caplog.at_level(logging.INFO, logger=ac.logger.name):
        r = asyncio.run(ac.generate(ai_db, r1, locale="tr", user="u", persist=False))
    assert r["validation"]["unsoftened_definitive_count"] == 1
    assert any("yumuşatılamadı" in x.getMessage() for x in caplog.records)


# ── saklama (retention) ──────────────────────────────────────────────────────

def _comment(db, key, version, age_days, finding_id=None):
    from datetime import datetime, timedelta, timezone
    from app.models.finding_ai import FindingAiComment
    c = FindingAiComment(finding_id=finding_id, event_key=key, version=version, model="m", locale="tr", content={}, confidence={},
                         input_hash="h", facts={}, generated_at=datetime.now(timezone.utc) - timedelta(days=age_days))
    db.add(c); db.commit(); db.refresh(c)
    return c


def test_saklama_suresi_env_varsayilan_90_ve_alt_sinir(monkeypatch):
    monkeypatch.delenv("VIRT_AI_COMMENT_RETENTION_DAYS", raising=False)
    assert ac.retention_days() == 90
    monkeypatch.setenv("VIRT_AI_COMMENT_RETENTION_DAYS", "30")
    assert ac.retention_days() == 30
    monkeypatch.setenv("VIRT_AI_COMMENT_RETENTION_DAYS", "1")
    assert ac.retention_days() == ac.MIN_RETENTION_DAYS
    monkeypatch.setenv("VIRT_AI_COMMENT_RETENTION_DAYS", "abc")
    assert ac.retention_days() == 90


def test_saklama_eski_surumleri_siler_son_surum_her_zaman_kalir(ai_db):
    from app.models.finding_ai import FindingAiComment, FindingAiFeedback
    a1, a2, a3 = (_comment(ai_db, "k|A", 1, 200), _comment(ai_db, "k|A", 2, 120), _comment(ai_db, "k|A", 3, 100))
    b1 = _comment(ai_db, "k|B", 1, 400)                 # tek sürüm, çok eski → son sürüm: KALIR
    c1, c2 = _comment(ai_db, "k|C", 1, 100), _comment(ai_db, "k|C", 2, 10)
    ai_db.add(FindingAiFeedback(comment_id=a1.id, username="u", helpful=True)); ai_db.commit()
    assert ac.purge_old_versions(ai_db, days=90) == 3   # a1, a2, c1
    left = {(c.event_key, c.version) for c in ai_db.query(FindingAiComment).all()}
    assert left == {("k|A", 3), ("k|B", 1), ("k|C", 2)}
    assert ai_db.query(FindingAiFeedback).count() == 0   # silinen sürümün oyu da gider
    assert ac.purge_old_versions(ai_db, days=90) == 0    # tekrar çalıştırmak zararsız


def test_saklama_yeni_surumleri_ve_env_suresini_kullanir(ai_db, monkeypatch):
    from app.models.finding_ai import FindingAiComment
    _comment(ai_db, "k|A", 1, 40); _comment(ai_db, "k|A", 2, 5)
    monkeypatch.setenv("VIRT_AI_COMMENT_RETENTION_DAYS", "90")
    assert ac.purge_old_versions(ai_db) == 0
    monkeypatch.setenv("VIRT_AI_COMMENT_RETENTION_DAYS", "30")
    assert ac.purge_old_versions(ai_db) == 1
    assert ai_db.query(FindingAiComment).count() == 1


def test_saklama_tablo_yoksa_sifir(isolated_db):  # noqa: F811
    from app.models.finding_ai import FindingAiComment, FindingAiFeedback
    eng = isolated_db.get_bind()
    FindingAiFeedback.__table__.drop(eng, checkfirst=True)
    FindingAiComment.__table__.drop(eng, checkfirst=True)
    assert ac.purge_old_versions(isolated_db) == 0


def test_run_cycle_saklama_kancasi_hatayi_yutar(monkeypatch):
    from app.services.findings import runner

    class _Db:
        def rollback(self):
            self.rolled = True
    db = _Db()
    monkeypatch.setattr("app.services.findings.ai_comment.purge_old_versions",
                        lambda d: (_ for _ in ()).throw(RuntimeError("x")))
    runner._purge_ai_comments(db)                      # tur bozulmaz
    assert getattr(db, "rolled", False)
    called = []
    monkeypatch.setattr("app.services.findings.ai_comment.purge_old_versions", lambda d: called.append(d))
    runner._purge_ai_comments(db)
    assert called == [db]


def test_ayni_olay_icin_surum_cakismasi_yeniden_denenir(ai_db, monkeypatch):
    r1 = _row(ai_db)
    _fake_llm(monkeypatch, [GOOD])
    res = asyncio.run(ac.generate(ai_db, r1, locale="tr", user="u", persist=False))
    key = res["event_key"]
    stale = {"n": 0}
    real = ac._latest

    def racy(db, k):                                    # ilk okuma eski (v0): v1'i başka biri yazmış gibi
        stale["n"] += 1
        if stale["n"] == 1:
            _comment(db, key, 1, 0, finding_id=r1.id)
            return None
        return real(db, k)
    monkeypatch.setattr(ac, "_latest", racy)
    stored = ac._store(ai_db, r1, res)
    assert stored["version"] == 2


# ── canlı çıktıdan çıkan düzeltmeler: başlık ≠ öneri, alternatif tek yerde, dil ve (b) sözcükleri ─────────

def test_bulgu_basligi_ve_gozlem_cumlesi_oneri_sayilmaz():
    f = _facts()
    f["diger_bulgular"] = [{"id": 5, "kontrol": "vmw.host.vmotion_vmknic", "kategori": "health", "onem": "medium",
                            "baslik": "vMotion etkin VMkernel yok", "detay": ""}]
    c = _content(diger_iyilestirmeler=["vMotion etkin VMkernel yok (bu olayla doğrudan ilişkili değil)"],
                 genel_bilgi=["Host'ta vMotion kullanılır."])                     # öneri imi yok → dokunulmaz
    out, log, _ = pp.fix_recommendations(c, f, "tr")
    assert out == c and log == []


def test_alternatif_cumle_tek_yerde_digerleri_dusurulur():
    c = _content(oncelik="VM'leri tahliye edin.", genel_bilgi=["VM migration should be planned."],
                 diger_iyilestirmeler=["Host boşaltılmalı."], gozlenen=["Sensör alarmı var"])
    out, log, _ = pp.fix_recommendations(c, _facts(), "tr")
    everything = " ".join([out["ozet"], out["olay_gorunumu"], out["etki"], out["oncelik"], *out["gozlenen"], *out["genel_bilgi"],
                           *out["diger_iyilestirmeler"], *out["bilinmeyenler"]])
    assert everything.count(ALT_TR) == 1 and ALT_TR in out["oncelik"]
    assert out["genel_bilgi"] == [] or all("migration" not in x for x in out["genel_bilgi"])
    assert out["diger_iyilestirmeler"] == [] and len(log) == 3


def test_turkce_beklenirken_ingilizce_cumle_reddedilir():
    f = _facts()
    assert ac.validate(_content(), f, "tr") == []
    v = ac.validate(_content(oncelik="First, investigate the overall host health."), f, "tr")
    assert any("Türkçe yazılmalı" in x for x in v)
    v = ac.validate(_content(genel_bilgi=["Hardware sensor failures can indicate impending hardware failure."]), f, "tr")
    assert any("genel_bilgi[0]: Türkçe yazılmalı" in x for x in v)
    assert ac.validate(_content(oncelik="First, investigate the overall host health."), f) == []      # lang verilmezse denetim yok
    assert ac.validate(_content(oncelik="First, investigate the overall host health."), f, "en") == []
    # veriden alıntı İngilizce kısa terimler sorun değil
    assert ac.validate(_content(gozlenen=["Sensör türü: overall status red"]), f, "tr") == []


def test_b_bulgusunun_ayirt_edici_sozcugu_olay_anlatiminda_gecemez():
    f = _facts()
    f["diger_bulgular"] = [{"id": 2, "kontrol": "vmw.host.uplink_redundancy", "kategori": "health", "onem": "high",
                            "baslik": "Tek uplink'li sanal switch", "detay": ""},
                           {"id": 3, "kontrol": "vmw.host.ntp_running", "kategori": "health", "onem": "high",
                            "baslik": "NTP servisi çalışmıyor", "detay": ""}]
    assert set(ac.other_markers(f)) == {"uplink", "ntp"}                       # genel sözcükler (sanal, switch, tek...) dışarıda
    v = ac.validate(_content(oncelik="Sonra diğer sağlık sorunları (NTP ve uplink) ele alınmalı."), f, "tr")
    assert any("olayla ilişkisiz bulgunun konusu" in x for x in v)
    assert ac.validate(_content(diger_iyilestirmeler=["NTP — bu olayla doğrudan ilişkili değil"]), f, "tr") == []
    out, dropped = ac.drop_unrelated_items(_content(gozlenen=["Sensör alarmı var", "uplink tek"]), f)
    assert out["gozlenen"] == ["Sensör alarmı var"] and len(dropped) == 1
    # (a) metninde geçen sözcük ayırt edici sayılmaz
    f["olay_bulgulari"][0]["detay"] = "ntp saati sapmış"
    assert "ntp" not in ac.other_markers(f)


def test_generate_ingilizce_yaniti_geri_bildirimle_yeniden_dener(ai_db, monkeypatch):
    r1 = _row(ai_db)
    en = json.dumps({**json.loads(GOOD), "ozet": "The host has a hardware problem and it should be checked."}, ensure_ascii=False)
    calls = _fake_llm(monkeypatch, [en, GOOD])
    r = asyncio.run(ac.generate(ai_db, r1, locale="tr", user="u", persist=False))
    assert len(calls) == 2 and "Türkçe yazılmalı" in calls[1] and r["validation"]["attempts"] == 2
    assert "TÜRKÇE" in calls[0]
