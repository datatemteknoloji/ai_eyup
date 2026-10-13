"""Bulgular sayfası AI yorumu (Yapılandırma + Donanım) — kullanıcı butona basınca üretilir.

İlke: HESAP KODDA, model yalnız ANLATIR. Modele verilen her şey (bulgu, ilişkili bulgular, host düşerse etki,
kural rehberi) kodla hesaplanmış/okunmuş "gözlenen veri"dir. Model çıktısı kullanıcıya ulaşmadan önce
KURALLARLA doğrulanır; doğrulamayı geçemeyen yorum saklanmaz ve gösterilmez.

Doğrulama (bkz. `validate`):
  · Veride olmayan sayı / IP / sürüm / KB / CVE / komut / kod bloğu → ret.
  · "Düzelttim / yeniden başlattım ..." gibi eylem iddiası (sistem salt okunur) → ret.
  · `genel_bilgi` (veriden bağımsız bilgi) hiçbir rakam, sürüm, KB, komut içeremez.
Güven düzeyi modelin beyanı değildir; `confidence()` ile veri eksikliklerinden KODLA hesaplanır.

OLAY TABANLI: yorum bulgu başına değil OLAY başına üretilir (`events.py`: aynı host + aynı kök ailesi). Olayın üyeleri
(a) tek olay gibi anlatılır; aynı host'taki diğer açık bulgular (b) "bu olayla doğrudan ilişkili değil" diye ayrı verilir ve
yalnız `diger_iyilestirmeler` listesinde yer alır. Yorum, olayın tüm üye bulgularında aynı görünür.
Son işleme (öneri-gerçek denetimi, yumuşatma, sayım) `ai_postprocess.py` içindedir.

`llm_gateway` yalnız istemci olarak çağrılır (kodu değiştirilmez). Tablolar `models/finding_ai.py` içindedir
(`create_all` ile oluşur; referans SQL: `backend/migrations/add_finding_ai_comments.sql`).
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

import httpx
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.orm import Session

from app.models.infra_finding import InfraFinding
from app.services.findings import context as fctx
from app.services.findings import events as fevents
from app.services.findings.ai_postprocess import (  # noqa: F401  (testler/dışarısı için yeniden dışa aktarım)
    SENT_SPLIT as _SENT_SPLIT, _SOFTEN_RULES, postprocess, soften, soften_text)

logger = logging.getLogger(__name__)

# Sekme → kategori: Yapılandırma = health, Donanım = hardware
AI_CATEGORIES = ("health", "hardware")
TABLES = ("finding_ai_comments", "finding_ai_feedback")
MAX_RELATED = 12
LLM_TIMEOUT = 300.0
# Muhakeme (thinking) modelleri çıktı bütçesinin büyük kısmını düşünmeye harcar; düşük değer boş/kesik JSON üretir.
NUM_PREDICT = 4500

TABLES_MISSING_MSG = "AI yorum tabloları bulunamadı (backend yeniden başlatılınca oluşur; bkz. backend/migrations/add_finding_ai_comments.sql)."

NARRATIVE_EVENT_ONLY = ("ozet", "olay_gorunumu", "etki", "oncelik")
SECTION_LIMITS = {"ozet": 600, "olay_gorunumu": 900, "etki": 700, "oncelik": 600}
LIST_LIMITS = {"gozlenen": (8, 300), "genel_bilgi": (5, 300), "diger_iyilestirmeler": (8, 300), "bilinmeyenler": (6, 300)}


class AiCommentRejected(Exception):
    """Model çıktısı doğrulamayı geçemedi (kullanıcıya gösterilmez, saklanmaz)."""

    def __init__(self, violations: List[str]):
        super().__init__("; ".join(violations))
        self.violations = violations


class AiUnavailable(Exception):
    """LLM servisine ulaşılamadı."""


# ── Tablolar var mı? ─────────────────────────────────────────────────────────

def tables_ready(db: Session) -> bool:
    try:
        insp = sa_inspect(db.get_bind())
        return all(insp.has_table(t) for t in TABLES)
    except Exception:
        return False


# ── Gözlenen veri (modele verilen tek kaynak) ────────────────────────────────

def _trim(v: Any, n: int = 400) -> Any:
    if isinstance(v, str):
        return v if len(v) <= n else v[:n] + "…"
    if isinstance(v, list):
        return [_trim(x, n) for x in v[:20]]
    if isinstance(v, dict):
        return {str(k): _trim(x, n) for k, x in list(v.items())[:30]}
    return v


_VERDICT_TXT = {
    "tr": {"fit": "VM'ler kalan host'lara sığar", "tight": "VM'ler kalan host'lara sınırda sığar",
           "fail": "VM'ler kalan host'lara sığmaz", "no_vm": "etkilenen çalışan VM yok"},
    "en": {"fit": "the VMs fit on the remaining hosts", "tight": "the VMs fit on the remaining hosts only marginally",
           "fail": "the VMs do not fit on the remaining hosts", "no_vm": "there are no affected running VMs"},
}


def impact_text(imp: Dict[str, Any], locale: str) -> str:
    """Etki cümlesi KODLA üretilir (model yalnız aktarır)."""
    lang = "en" if locale == "en" else "tr"
    v = _VERDICT_TXT[lang].get(imp.get("verdict") or "", str(imp.get("verdict")))
    if lang == "en":
        t = (f"If this host goes down, {imp.get('vms')} VMs ({imp.get('memory_gb')} GB Memory) are affected; remaining hosts: "
             f"{imp.get('remaining_hosts')}; VMs that cannot be placed: {imp.get('unplaced')}; result: {v}.")
        if imp.get("remaining_hosts") == 0:
            t += " There is no other host in this scope, so failover is not possible."
        return t
    t = (f"Bu host kapanırsa {imp.get('vms')} VM ({imp.get('memory_gb')} GB Memory) etkilenir; kalan host sayısı: "
         f"{imp.get('remaining_hosts')}; yerleşemeyen VM sayısı: {imp.get('unplaced')}; sonuç: {v}.")
    if imp.get("remaining_hosts") == 0:
        t += " Bu kapsamda başka host yok; failover mümkün değil."
    return t


def _member(r: InfraFinding) -> Dict[str, Any]:
    return {
        "id": r.id, "kontrol": r.check_id, "kategori": r.category, "baslik": r.title, "onem": r.severity,
        "durum": r.result, "aktif": bool(r.active), "detay": r.detail or "", "oneri_kural": r.recommendation or "",
        "ilk_gorulme": r.first_seen.isoformat() if r.first_seen else None,
        "son_gorulme": r.last_seen.isoformat() if r.last_seen else None,
        "kanit": _trim(r.evidence or {}),
    }


def build_facts(db: Session, row: InfraFinding, locale: str = "tr") -> Dict[str, Any]:
    """OLAY için gözlenen veri: (a) `olay_bulgulari` (aynı kök, tek olay) ve (b) `diger_bulgular` (ilişkili DEĞİL)."""
    sp = fevents.event_split(db, row)
    members: List[InfraFinding] = sp["members"]
    rep = next((m for m in members if m.id == sp["representative_id"]), row)
    guides: List[Dict[str, Any]] = []
    for m in members:
        for g in ((fctx.sensor_guides(m, locale) or {}).get("guides") or []):
            if not any(x.get("title") == g.get("title") for x in guides):
                guides.append(g)
    impact = None
    if sp["family"] == "hardware" and row.entity_kind == "host":
        imp = fctx.host_impact(db, rep) if any(m.result == "fail" for m in members) else None
        if imp and imp.get("available"):
            impact = {k: imp.get(k) for k in ("cluster", "verdict", "limiting", "vms", "memory_gb", "unplaced",
                                              "remaining_hosts", "after_memory_pct", "threshold_pct")}
            impact["ozet_metin"] = impact_text(impact, locale)
    return {
        "olay": {"anahtar": sp["key"], "aile": sp["family"], "uye_sayisi": len(members),
                 "varlik_turu": row.entity_kind, "varlik": row.entity_name, "platform": row.platform,
                 "cluster": row.cluster_name},
        "olay_bulgulari": [_member(m) for m in members],
        "diger_bulgular": [{"id": o.id, "kontrol": o.check_id, "kategori": o.category, "onem": o.severity,
                            "baslik": o.title, "detay": o.detail or ""} for o in sp["others"][:MAX_RELATED]],
        "host_dusarse_etki": impact,
        "kural_rehberi": [{"tur": g.get("title"), "olasi_neden": g.get("cause"), "etki": g.get("impact"),
                           "adimlar": g.get("steps")} for g in guides],
    }


def input_hash(facts: Dict[str, Any]) -> str:
    """Parmak izi: ÜYELER + durumları + etki (kaynak değişince yorum 'güncel olmayabilir')."""
    imp = facts.get("host_dusarse_etki") or {}
    basis = {
        "uyeler": sorted((m["id"], m["durum"], m["aktif"], m["onem"], m["detay"]) for m in facts["olay_bulgulari"]),
        "diger": sorted((o["id"], o["onem"]) for o in facts["diger_bulgular"]),
        "etki": [imp.get(k) for k in ("verdict", "vms", "memory_gb", "unplaced", "remaining_hosts")] if imp else None,
    }
    return hashlib.sha256(json.dumps(basis, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


# ── Güven düzeyi (kodla) ─────────────────────────────────────────────────────

def confidence(facts: Dict[str, Any], *, stale_source: bool = False) -> Dict[str, Any]:
    """Veri eksikliğinden hesaplanır. Nedenler kod olarak döner (arayüz çevirir)."""
    members = facts["olay_bulgulari"]
    reasons: List[str] = []
    has_detail = any((m.get("detay") or "").strip() for m in members)
    ev_n = sum(len(m.get("kanit") or {}) for m in members)
    if not has_detail:
        reasons.append("no_detail")
    sensor_members = [m for m in members if m["kontrol"] in fctx._SENSOR_CHECKS]
    if sensor_members and not any(fctx._sensors(m.get("kanit") or {}) for m in sensor_members):
        reasons.append("no_sensor_type")
    o = facts["olay"]
    if o["varlik_turu"] == "host" and o["aile"] == "hardware" and not facts.get("host_dusarse_etki"):
        reasons.append("no_impact")
    if stale_source:
        reasons.append("stale_source")
    thin = not has_detail and ev_n < 2 and len(members) == 1 and not facts["diger_bulgular"]
    if stale_source or thin:
        level = "low"
    elif reasons:
        level = "medium"
    else:
        level = "high"
    return {"level": level, "reasons": reasons}


# ── Prompt ───────────────────────────────────────────────────────────────────

_SYSTEM = {
    "tr": (
        "Sen altyapı bulgularını yorumlayan SALT OKUNUR bir asistansın. Sistemde hiçbir şey değiştirmedin ve değiştiremezsin.\n"
        "KURALLAR:\n"
        "1. YALNIZCA VERİ bölümündeki bilgiyi kullan. Verilerde olmayan sayı, IP, sürüm, KB/CVE numarası, komut, "
        "cihaz/ürün adı veya tarih UYDURMA.\n"
        "2. Hesaplanmış değerleri (etki, adetler, yüzdeler) olduğu gibi aktar; kendin hesap yapma, yuvarlama yapma.\n"
        "3. Geçmiş zamanda eylem anlatma ('düzelttim', 'yeniden başlattım', 'uyguladım' YASAK). Öneri kipi kullan "
        "('... kontrol edilmesi önerilir').\n"
        "4. 'gozlenen': yalnız veride görülen olgular. 'genel_bilgi': veriden bağımsız genel bilgi; BU ALANDA rakam, sürüm, "
        "KB, komut, IP OLAMAZ. Bilinmeyenleri 'bilinmeyenler' alanına yaz (ör. sensör türü verilmemişse).\n"
        "5. 'olay_bulgulari' AYNI KÖKTEN gelen bulgulardır; hepsini TEK olay gibi anlat. Veri nedensellik göstermiyorsa "
        "'neden' deme, 'birlikte görülüyor' de.\n"
        "6. 'diger_bulgular' aynı host'taki BAŞKA açık bulgulardır ve bu olayla DOĞRUDAN İLİŞKİLİ DEĞİLDİR. Bunları olayın "
        "nedeni, parçası veya sonucu gibi ANLATMA; ozet/olay_gorunumu/etki/oncelik/gozlenen alanlarında ANMA. Yalnızca "
        "'diger_iyilestirmeler' listesine, her biri 'bu olayla doğrudan ilişkili değil' vurgusuyla kısa madde olarak yaz "
        "(başlıkla). Liste boşsa boş liste ver.\n"
        "7. 'RAM' deme; 'Memory' de. Kısa ve net yaz. Türkçe yaz.\n"
        "8. 'host_dusarse_etki' YALNIZCA 'host kapanırsa' senaryosudur; şu an yaşanan bir kesinti gibi anlatma. Sonucu "
        "belirsiz 'Bu durum' ile değil, senaryoyu açıkça söyleyerek yaz. 'remaining_hosts' 0 ise VM tahliye/taşıma/vMotion "
        "ÖNERME (hedef host yok).\n"
        "9. 'genel_bilgi'de emin olmadığın şeyi yazma; kesin hüküm yerine 'olabilir' gibi ihtiyatlı ifade kullan.\n"
        "ALANLAR:\n"
        "- ozet: 2-3 tam cümle; ne oluyor ve neden önemli (yalnız olay).\n"
        "- olay_gorunumu: 'olay_bulgulari'ndaki bulguları TEK olay gibi, başlıklarıyla an.\n"
        "- etki: 'host_dusarse_etki.ozet_metin' cümlesini AYNEN aktar ve kısaca yorumla; o alan yoksa 'etki hesaplanamadı' de.\n"
        "- oncelik: bu olay içinde neyin hangi sırayla ele alınması gerektiği ('olay_bulgulari' önemi ve etkiye göre); 1-3 cümle.\n"
        "- gozlenen: veriden kısa maddeler (her madde bir olgu; yalnız olay).\n"
        "- genel_bilgi: 1-3 TAM cümle, rakamsız genel bilgi (ör. bu tür sensör/durum neyi işaret edebilir).\n"
        "- diger_iyilestirmeler: 'diger_bulgular' için kısa maddeler (olayla ilişkili değil); yoksa [].\n"
        "- bilinmeyenler: veride olmayan ve sonucu etkileyen noktalar.\n"
        "ÇIKTI: yalnız şu anahtarlarla tek bir JSON nesnesi (başka metin yok):\n"
        '{"ozet": str, "olay_gorunumu": str, "etki": str, "oncelik": str, '
        '"gozlenen": [str], "genel_bilgi": [str], "diger_iyilestirmeler": [str], "bilinmeyenler": [str]}'
    ),
    "en": (
        "You are a READ-ONLY assistant that interprets infrastructure findings. You have not changed and cannot change anything.\n"
        "RULES:\n"
        "1. Use ONLY the information in the DATA section. Do NOT invent numbers, IPs, versions, KB/CVE ids, commands, "
        "device/product names or dates that are not in the data.\n"
        "2. Pass computed values (impact, counts, percentages) through unchanged; do not calculate or round.\n"
        "3. Never describe actions in the past tense ('I fixed', 'I restarted', 'applied' are FORBIDDEN). Use recommendation "
        "wording ('it is recommended to check ...').\n"
        "4. 'gozlenen': only facts seen in the data. 'genel_bilgi': general knowledge independent of the data; it MUST NOT "
        "contain digits, versions, KB ids, commands or IPs. Put unknowns in 'bilinmeyenler' (e.g. sensor type not provided).\n"
        "5. 'olay_bulgulari' come from the SAME ROOT; narrate them all as ONE incident. If the data shows no causality do not "
        "say 'because', say 'seen together'.\n"
        "6. 'diger_bulgular' are OTHER open findings on the same host and are NOT DIRECTLY RELATED to this event. Do NOT "
        "describe them as the cause, part or consequence of the event; do NOT mention them in ozet/olay_gorunumu/etki/"
        "oncelik/gozlenen. Write them ONLY in the 'diger_iyilestirmeler' list, one short item each, stressing 'not directly "
        "related to this event' (with title). Use an empty list if none.\n"
        "7. Say 'Memory', never 'RAM'. Be short and clear. Write in English.\n"
        "8. 'host_dusarse_etki' is ONLY an 'if the host goes down' scenario; do not describe it as an outage happening now. "
        "State the scenario explicitly instead of a vague 'This situation'. If 'remaining_hosts' is 0 do NOT recommend "
        "evacuating/migrating/vMotion (there is no target host).\n"
        "9. In 'genel_bilgi' do not write things you are unsure of; use cautious wording such as 'may' instead of firm claims.\n"
        "FIELDS:\n"
        "- ozet: 2-3 full sentences; what is happening and why it matters (event only).\n"
        "- olay_gorunumu: narrate the findings in 'olay_bulgulari' as ONE incident, naming them by title.\n"
        "- etki: pass 'host_dusarse_etki.ozet_metin' through VERBATIM and comment briefly; if that field is missing say 'impact could not be calculated'.\n"
        "- oncelik: in what order things should be handled within this event (by 'olay_bulgulari' severity and impact); 1-3 sentences.\n"
        "- gozlenen: short items from the data (one fact each; event only).\n"
        "- genel_bilgi: 1-3 FULL sentences of general knowledge without digits (e.g. what this kind of sensor/state may indicate).\n"
        "- diger_iyilestirmeler: short items for 'diger_bulgular' (not related to this event); [] if none.\n"
        "- bilinmeyenler: points missing from the data that affect the conclusion.\n"
        "OUTPUT: a single JSON object with exactly these keys (no other text):\n"
        '{"ozet": str, "olay_gorunumu": str, "etki": str, "oncelik": str, '
        '"gozlenen": [str], "genel_bilgi": [str], "diger_iyilestirmeler": [str], "bilinmeyenler": [str]}'
    ),
}


def build_prompt(facts: Dict[str, Any], locale: str, feedback: Optional[List[str]] = None) -> str:
    lang = "en" if locale == "en" else "tr"
    head = "DATA (JSON):" if lang == "en" else "VERİ (JSON):"
    p = f"{head}\n{json.dumps(facts, ensure_ascii=False, indent=1)}\n"
    if feedback:
        if lang == "en":
            p += "\nYour previous answer violated these rules; fix them and answer again:\n"
        else:
            p += "\nÖnceki yanıtın şu kurallara aykırıydı; düzelt ve yeniden yanıtla:\n"
        p += "\n".join(f"- {v}" for v in feedback[:8]) + "\n"
    p += "\nAll text fields must be written in English.\nJSON:" if lang == "en" else "\nTüm metin alanları TÜRKÇE yazılmalı (İngilizce cümle yok).\nJSON:"
    return p


# ── Doğrulama ────────────────────────────────────────────────────────────────

_NUM = re.compile(r"\d+(?:[.,]\d+)?")
_MULTI = re.compile(r"\b\d+(?:\.\d+){2,}\b")                 # sürüm / IP
_KB = re.compile(r"\bKB[\s\-]?\d+\b", re.I)
_CVE = re.compile(r"\bCVE-\d{4}-\d+\b", re.I)
_CMD = re.compile(r"\b(esxcli|vim-cmd|systemctl|sudo|chmod|chown|ipmitool|racadm|hpasmcli|powercli|"
                  r"set-vmhost|get-vmhost|get-esxcli|service\s+\S+\s+(?:restart|stop|start)|rm\s+-\w+|ssh\s+\S+@)", re.I)
_CODE = re.compile(r"```|`[^`]+`")
_ACTION = re.compile(
    r"\b(düzelttim|çözdüm|giderdim|yeniden başlattım|başlattım|durdurdum|değiştirdim|uyguladım|etkinleştirdim|"
    r"devre dışı bıraktım|kapattım|açtım|sildim|onardım|güncelledim|çalıştırdım|düzeltildi|giderildi|çözüldü|"
    r"uygulandı|yeniden başlatıldı|otomatik olarak (?:düzeltildi|giderildi)|"
    r"(?:i|we)\s+(?:have\s+)?(?:fixed|restarted|applied|changed|resolved|rebooted|remediated|disabled|enabled|updated)|"
    r"(?:has|have)\s+been\s+(?:fixed|restarted|resolved|applied|remediated)|was\s+(?:fixed|restarted|remediated))\b", re.I)


def _norm_num(s: str) -> str:
    try:
        f = float(s.replace(",", "."))
        return str(int(f)) if f == int(f) else repr(round(f, 4))
    except ValueError:
        return s


def _corpus(facts: Dict[str, Any]) -> Tuple[str, set]:
    text = json.dumps(facts, ensure_ascii=False)
    nums = {_norm_num(n) for n in _NUM.findall(text)}
    # türetilmiş sayılar: olay üye adedi, diğer bulgu adedi ve toplamları
    n_m = len(facts.get("olay_bulgulari") or [])
    n_o = len(facts.get("diger_bulgular") or [])
    nums |= {str(n_m), str(n_o), str(n_m + n_o)}
    return text.lower(), nums


def _strings(c: Dict[str, Any]) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    for k in SECTION_LIMITS:
        out.append((k, c.get(k) or ""))
    for k in LIST_LIMITS:
        for i, s in enumerate(c.get(k) or []):
            out.append((f"{k}[{i}]", s))
    return out


def parse_model_json(text: str) -> Optional[Dict[str, Any]]:
    if not text:
        return None
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t, flags=re.I)
    try:
        v = json.loads(t)
        return v if isinstance(v, dict) else None
    except ValueError:
        pass
    a, b = t.find("{"), t.rfind("}")
    if a >= 0 and b > a:
        try:
            v = json.loads(t[a:b + 1])
            return v if isinstance(v, dict) else None
        except ValueError:
            return None
    return None


def normalize(raw: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """Şemayı doğrular ve sadeleştirir. (içerik, ihlaller)"""
    viol: List[str] = []
    out: Dict[str, Any] = {}
    for k, n in SECTION_LIMITS.items():
        v = raw.get(k)
        if not isinstance(v, str) or not v.strip():
            viol.append(f"'{k}' alanı dolu bir metin olmalı")
            continue
        out[k] = v.strip()[:n]
    for k, (cnt, n) in LIST_LIMITS.items():
        v = raw.get(k, [])
        if v is None:
            v = []
        if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
            viol.append(f"'{k}' alanı metin listesi olmalı")
            continue
        out[k] = [x.strip()[:n] for x in v if x.strip()][:cnt]
    if not out.get("gozlenen") and "gozlenen" in out:
        viol.append("'gozlenen' en az bir olgu içermeli")
    for k, v in list(out.items()):
        out[k] = _mem(v) if isinstance(v, str) else [_mem(x) for x in v]
    return (None if viol else out), viol


_RAM = re.compile(r"\bRAM\b")


def _mem(s: str) -> str:
    """Ürün dili: arayüzde 'RAM' değil 'Memory' denir."""
    return _RAM.sub("Memory", s)


_EN_WORDS = re.compile(r"\b(?:the|and|is|are|was|will|with|to|of|for|if|that|this|there|first|next|finally|should|can|may|could|"
                       r"would|by|which|such|because|than|from|has|have|been)\b", re.I)
_TR_CHARS = re.compile(r"[çğıöşüÇĞİÖŞÜ]")


def looks_english(s: str) -> bool:
    """Türkçe beklenen alanda İngilizce cümle var mı? (deterministik sezgi: işlev sözcüğü + Türkçe harf yokluğu)"""
    hits = len(_EN_WORDS.findall(s))
    if hits >= 2:
        return True
    return hits == 1 and not _TR_CHARS.search(s) and len(s.split()) >= 4


_GENERIC = {"host", "servisi", "servis", "değil", "yok", "var", "tanımlı", "kapalı", "açık", "etkin", "mode", "switch", "sanal",
            "tek", "uzak", "hedefi", "çalışmıyor", "sorunu", "durumu", "olarak", "için", "ile", "olan"}


def other_markers(facts: Dict[str, Any]) -> List[str]:
    """(b) bulgularının AYIRT EDİCİ sözcükleri (ör. ntp, uplink, syslog, lockdown, vmotion): olayın (a) metninde
    geçmeyen başlık sözcükleri. Olay anlatımında geçmeleri (b)'nin olaya karıştığını gösterir."""
    mine = " ".join(json.dumps(facts.get(k), ensure_ascii=False) for k in ("olay_bulgulari", "host_dusarse_etki", "kural_rehberi")
                    ).lower() + " " + json.dumps(facts.get("olay"), ensure_ascii=False).lower()
    marks: List[str] = []
    for o in facts.get("diger_bulgular") or []:
        for tok in re.findall(r"[\w]{3,}", (o.get("baslik") or "").lower()):
            if tok in _GENERIC or tok in mine or tok.isdigit() or tok in marks:
                continue
            marks.append(tok)
    return marks


def validate(content: Dict[str, Any], facts: Dict[str, Any], lang: Optional[str] = None) -> List[str]:
    """Kural tabanlı doğrulama. Boş liste = geçti. `lang='tr'` ise Türkçe yazım denetimi de yapılır."""
    viol: List[str] = []
    corpus, nums = _corpus(facts)
    others = [(o.get("baslik") or "", o.get("kontrol") or "") for o in facts.get("diger_bulgular") or []]
    marks = other_markers(facts)
    for key, s in _strings(content):
        general = key.startswith("genel_bilgi")
        if lang == "tr" and s and looks_english(s):
            viol.append(f"{key}: Türkçe yazılmalı (İngilizce cümle var)")
        if key in NARRATIVE_EVENT_ONLY or key.startswith("gozlenen"):
            for title, cid in others:
                if (len(title) >= 8 and title.lower() in s.lower()) or (cid and cid.lower() in s.lower()):
                    viol.append(f"{key}: olayla ilişkisiz bulgu ('{title or cid}') olay anlatımında geçiyor; "
                                "yalnız 'diger_iyilestirmeler' alanına yazılmalı")
            for m in marks:
                if re.search(rf"(?<![\w]){re.escape(m)}(?![\w])", s, re.I):
                    viol.append(f"{key}: olayla ilişkisiz bulgunun konusu ('{m}') olay anlatımında geçiyor; "
                                "yalnız 'diger_iyilestirmeler' alanına yazılmalı")
                    break
        if _ACTION.search(s):
            viol.append(f"{key}: eylem iddiası var (sistem salt okunur; geçmiş zamanda eylem anlatılamaz)")
        if _CODE.search(s) and (general or _CODE.search(s).group(0).strip("`").lower() not in corpus):
            viol.append(f"{key}: kod/komut bloğu veride yok")
        for m in _CMD.finditer(s):
            if general or m.group(0).lower() not in corpus:
                viol.append(f"{key}: veride olmayan komut ('{m.group(0)}')")
        for rx, label in ((_KB, "KB numarası"), (_CVE, "CVE numarası")):
            for m in rx.finditer(s):
                if general or m.group(0).lower() not in corpus:
                    viol.append(f"{key}: veride olmayan {label} ('{m.group(0)}')")
        for m in _MULTI.finditer(s):
            if general or m.group(0) not in corpus:
                viol.append(f"{key}: veride olmayan sürüm/IP ('{m.group(0)}')")
        if general:
            if re.search(r"\d", s):
                viol.append(f"{key}: genel bilgi alanında rakam olamaz")
            continue
        for n in _NUM.findall(s):
            nn = _norm_num(n)
            if nn in nums:
                continue
            viol.append(f"{key}: veride olmayan sayı ('{n}')")
    seen, uniq = set(), []
    for v in viol:
        if v not in seen:
            seen.add(v)
            uniq.append(v)
    return uniq


# ── Üretim ───────────────────────────────────────────────────────────────────

async def _ask(db: Session, prompt: str, system: str) -> str:
    from app.core.config import get_active_model
    from app.services import llm_gateway
    try:
        async with httpx.AsyncClient(timeout=LLM_TIMEOUT) as client:
            data = await llm_gateway.generate_async(
                client, model=get_active_model(db), prompt=prompt, system=system,
                options={"temperature": 0.15, "num_predict": NUM_PREDICT})
    except httpx.HTTPError as exc:
        raise AiUnavailable(str(exc)) from exc
    if data.get("error"):
        raise AiUnavailable(str(data.get("error")))
    return data.get("response") or ""


def drop_unrelated_items(content: Dict[str, Any], facts: Dict[str, Any]) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """`gozlenen` maddelerinden (b) bulgularına (olayla ilişkisiz) atıf yapanları çıkarır (deterministik)."""
    others = [(o.get("baslik") or "", o.get("kontrol") or "") for o in facts.get("diger_bulgular") or []]
    marks = other_markers(facts)
    kept, dropped = [], []
    for it in content.get("gozlenen") or []:
        low = it.lower()
        if any((len(t) >= 8 and t.lower() in low) or (c and c.lower() in low) for t, c in others) or \
                any(re.search(rf"(?<![\w]){re.escape(m)}(?![\w])", low) for m in marks):
            dropped.append({"field": "gozlenen", "item": it[:300]})
        else:
            kept.append(it)
    if not dropped:
        return content, []
    return {**content, "gozlenen": kept}, dropped


async def generate(db: Session, row: InfraFinding, *, locale: str = "tr", user: str = "",
                   persist: bool = True) -> Dict[str, Any]:
    """OLAY yorumu üretir. Doğrulama geçmezse bir kez geri bildirimle yeniden dener; yine geçmezse AiCommentRejected."""
    if row.category not in AI_CATEGORIES:
        raise ValueError("Bu bulgu kategorisi için AI yorumu desteklenmiyor")
    lang = "en" if locale == "en" else "tr"
    facts = build_facts(db, row, lang)
    h = input_hash(facts)
    t0 = time.time()
    feedback: Optional[List[str]] = None
    first_viol: List[str] = []
    attempts = 0
    content: Optional[Dict[str, Any]] = None
    last_viol: List[str] = []
    dropped: List[Dict[str, str]] = []
    for attempts in (1, 2):
        text = await _ask(db, build_prompt(facts, lang, feedback), _SYSTEM[lang])
        raw = parse_model_json(text)
        if raw is None:
            last_viol = ["Yanıt geçerli bir JSON nesnesi değil"]
        else:
            norm, last_viol = normalize(raw)
            if norm is not None:
                norm, dropped = drop_unrelated_items(norm, facts)
                if not norm.get("gozlenen"):
                    last_viol = ["'gozlenen' en az bir olay olgusu içermeli (olayla ilişkisiz bulgular hariç)"]
                else:
                    last_viol = validate(norm, facts, lang)
                if not last_viol:
                    content = norm
                    break
        if attempts == 1:
            first_viol = list(last_viol)
            feedback = last_viol
    if content is None:
        logger.info("AI yorumu reddedildi (finding=%s): %s", row.id, last_viol)
        raise AiCommentRejected(last_viol)
    content, post = postprocess(content, facts, lang)
    if post["softened_count"] or post["recommendation_fixes"]:
        # son işleme yalnız cümle kipini/sabit cümleyi değiştirir; güvence olarak yeniden doğrula
        if validate(content, facts, lang):
            logger.warning("AI yorumu son işleme sonrası doğrulamayı geçemedi (finding=%s)", row.id)
            raise AiCommentRejected(["Son işleme sonrası doğrulama başarısız"])
        logger.info("AI yorumu: %d cümle yumuşatıldı, %d öneri düzeltildi (finding=%s): %s", post["softened_count"],
                    len(post["recommendation_fixes"]), row.id,
                    [(x["field"], x["rule"]) for x in post["softened_sentences"] + post["recommendation_fixes"]])
    if post["unsoftened_definitive_count"]:
        logger.info("AI yorumu: %d kesin hüküm cümlesi sözlükte olmadığı için yumuşatılamadı (finding=%s): %s",
                    post["unsoftened_definitive_count"], row.id, [x["sentence"][:80] for x in post["unsoftened_definitive"]])
    from app.core.config import get_active_model
    result = {
        "content": content, "confidence": confidence(facts, stale_source=any(
            m.stale for m in fevents.event_split(db, row)["members"])),
        "input_hash": h, "facts": facts, "model": get_active_model(db), "locale": lang,
        "event_key": facts["olay"]["anahtar"],
        "validation": {"attempts": attempts, "violations_first_try": first_viol,
                       "dropped_unrelated_items": dropped, **post},
        "duration_ms": int((time.time() - t0) * 1000), "generated_by": user or None,
    }
    if persist:
        result = _store(db, row, result)
    return result


# ── Saklama / okuma ──────────────────────────────────────────────────────────

def _latest(db: Session, event_key: str):
    from app.models.finding_ai import FindingAiComment
    return (db.query(FindingAiComment).filter(FindingAiComment.event_key == event_key)
            .order_by(FindingAiComment.version.desc()).first())


def _store(db: Session, row: InfraFinding, r: Dict[str, Any]) -> Dict[str, Any]:
    """Olay anahtarı başına sürümlenir; `finding_id` olayın temsilci (en küçük id'li) bulgusudur."""
    from app.models.finding_ai import FindingAiComment
    key = r["event_key"]
    rep_id = fevents.event_split(db, row)["representative_id"]
    from sqlalchemy.exc import IntegrityError
    obj = None
    for _ in range(3):                       # eşzamanlı üretimde (event_key, version) çakışırsa sonraki sürümle yeniden dene
        last = _latest(db, key)
        obj = FindingAiComment(
            finding_id=rep_id, event_key=key, version=(last.version + 1) if last else 1, model=r["model"],
            locale=r["locale"], content=r["content"], confidence=r["confidence"], input_hash=r["input_hash"],
            facts=r["facts"], validation=r["validation"], generated_by=r["generated_by"], duration_ms=r["duration_ms"],
            generated_at=datetime.now(timezone.utc))      # tamamlanma anı (server_default işlem BAŞLANGICINI verirdi)
        db.add(obj)
        try:
            db.commit()
            break
        except IntegrityError:
            db.rollback()
            obj = None
    if obj is None:
        raise RuntimeError("AI yorumu saklanamadı (sürüm çakışması)")
    db.refresh(obj)
    return {**r, "id": obj.id, "version": obj.version, "generated_at": obj.generated_at.isoformat() if obj.generated_at else None}


def serialize(obj: Any, current_hash: str, mine: Optional[bool], up: int, down: int, revisions: int) -> Dict[str, Any]:
    facts = obj.facts or {}
    ev = facts.get("olay") or {}
    return {
        "id": obj.id, "version": obj.version, "model": obj.model, "locale": obj.locale,
        "content": obj.content, "confidence": obj.confidence, "facts": facts,
        "event": {"key": obj.event_key, "family": ev.get("aile"), "member_count": ev.get("uye_sayisi"),
                  "member_ids": [m.get("id") for m in facts.get("olay_bulgulari") or []],
                  "representative_id": obj.finding_id},
        "generated_at": obj.generated_at.isoformat() if obj.generated_at else None,
        "generated_by": obj.generated_by,
        "stale": obj.input_hash != current_hash,
        "feedback": {"mine": mine, "helpful": up, "not_helpful": down},
        "revisions": revisions,
    }


def get_state(db: Session, row: InfraFinding, *, locale: str, username: str) -> Dict[str, Any]:
    """Kayıtlı OLAY yorumu + güncel olup olmadığı. Tablo yoksa available=False. Yorum ÜRETMEZ."""
    base = {"supported": row.category in AI_CATEGORIES}
    if not base["supported"]:
        return {**base, "available": False, "comment": None, "reason": "unsupported_category"}
    if not tables_ready(db):
        return {**base, "available": False, "comment": None, "reason": "tables_missing"}
    from app.models.finding_ai import FindingAiComment, FindingAiFeedback
    key = fevents.event_key(row)
    cur = _latest(db, key)
    if not cur:
        return {**base, "available": True, "comment": None, "event_key": key}
    h = input_hash(build_facts(db, row, "en" if locale == "en" else "tr"))
    fb = db.query(FindingAiFeedback).filter(FindingAiFeedback.comment_id == cur.id).all()
    mine = next((f.helpful for f in fb if f.username == username), None)
    n = db.query(FindingAiComment).filter(FindingAiComment.event_key == key).count()
    return {**base, "available": True, "event_key": key,
            "comment": serialize(cur, h, mine, sum(1 for f in fb if f.helpful), sum(1 for f in fb if not f.helpful), n)}


def submit_feedback(db: Session, row: InfraFinding, *, comment_id: int, username: str, helpful: bool,
                    note: Optional[str] = None) -> Dict[str, Any]:
    from app.models.finding_ai import FindingAiComment, FindingAiFeedback
    c = db.query(FindingAiComment).filter(FindingAiComment.id == comment_id,
                                          FindingAiComment.event_key == fevents.event_key(row)).first()
    if not c:
        raise LookupError("Yorum bulunamadı")
    fb = db.query(FindingAiFeedback).filter(FindingAiFeedback.comment_id == c.id,
                                            FindingAiFeedback.username == username).first()
    if fb:
        fb.helpful, fb.note = helpful, (note or None)
    else:
        db.add(FindingAiFeedback(comment_id=c.id, username=username, helpful=helpful, note=(note or None)))
    db.commit()
    rows = db.query(FindingAiFeedback).filter(FindingAiFeedback.comment_id == c.id).all()
    return {"mine": helpful, "helpful": sum(1 for f in rows if f.helpful), "not_helpful": sum(1 for f in rows if not f.helpful)}


# ── Saklama süresi (retention) ───────────────────────────────────────────────
# Eski yorum SÜRÜMLERİ süre dolunca silinir; her olayın en son (en büyük version) yorumu HER ZAMAN kalır.
# Süre: virt'e özgü env `VIRT_AI_COMMENT_RETENTION_DAYS` (varsayılan 90, en az 7). Paylaşılan runtime_settings'e dokunulmaz.
DEFAULT_RETENTION_DAYS = 90
MIN_RETENTION_DAYS = 7


def retention_days() -> int:
    raw = os.getenv("VIRT_AI_COMMENT_RETENTION_DAYS", "").strip()
    try:
        d = int(raw) if raw else DEFAULT_RETENTION_DAYS
    except ValueError:
        d = DEFAULT_RETENTION_DAYS
    return max(MIN_RETENTION_DAYS, d)


def purge_old_versions(db: Session, *, days: Optional[int] = None, now: Optional[datetime] = None) -> int:
    """`days`'ten eski ve olayının en son sürümü OLMAYAN yorumları (geri bildirimleriyle) siler. Silinen adet döner."""
    if not tables_ready(db):
        return 0
    from sqlalchemy import func
    from app.models.finding_ai import FindingAiComment, FindingAiFeedback
    d = max(MIN_RETENTION_DAYS, days) if days is not None else retention_days()
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=d)
    latest = (db.query(FindingAiComment.event_key.label("k"), func.max(FindingAiComment.version).label("v"))
              .group_by(FindingAiComment.event_key).subquery())
    ids = [i for (i,) in (db.query(FindingAiComment.id)
                          .join(latest, FindingAiComment.event_key == latest.c.k)
                          .filter(FindingAiComment.generated_at < cutoff, FindingAiComment.version < latest.c.v).all())]
    if not ids:
        return 0
    db.query(FindingAiFeedback).filter(FindingAiFeedback.comment_id.in_(ids)).delete(synchronize_session=False)
    db.query(FindingAiComment).filter(FindingAiComment.id.in_(ids)).delete(synchronize_session=False)
    db.commit()
    logger.info("AI yorum saklama: %d eski sürüm silindi (>%d gün)", len(ids), d)
    return len(ids)
