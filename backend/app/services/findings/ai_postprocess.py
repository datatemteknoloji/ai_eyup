"""AI yorumu son işleme — deterministik, kural tabanlı, LLM'siz.

Sıra (`postprocess`): (1) öneri-gerçek denetimi, (2) kesin hüküm yumuşatma (+ belirsiz gönderme yeniden yazımı),
(3) yumuşatılmamış kesin cümle sayımı (telemetri). Hepsi yalnız ilgili CÜMLEYİ değiştirir; tüm yorumu reddetmez.
Kodla yazılmış cümleler (etki cümlesi, kural rehberi, bu modülün sabit cümleleri) dokunulmaz.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Set, Tuple

# ── Kesin hüküm yumuşatma ────────────────────────────────────────────────────
# Kesin hüküm yalnız HESAPLANMIŞ veriyle desteklenirse kalır; desteklenmiyorsa o cümle olasılık diline çevrilir.
# Destek türleri: None → her zaman yumuşat · "nofit" → host-düşerse sonucu 'fail' ise kalır ·
# "outage" → host-düşerse sonucu 'fail' VE cümle o senaryonun sonucuysa kalır (veri kaybı iddiası hariç).

def _w(p: str) -> str:
    return rf"(?<!\w)(?:{p})(?!\w)"


_SOFTEN_RULES: List[Tuple[str, "re.Pattern[str]", Optional[str], Optional[str]]] = [
    (rid, re.compile(_w(p), re.I), rep, sup) for rid, p, rep, sup in (
        # TR — kesin hüküm fiilleri
        ("tr_durdur", r"durdurur|durduruyor|durduracaktır|durduracak", "durdurabilir", "outage"),
        ("tr_yol_ac", r"yol açar|yol açıyor|yol açacaktır|yol açacak", "yol açabilir", "outage"),
        ("tr_neden", r"neden olur|neden oluyor|neden olacaktır|neden olacak", "neden olabilir", "outage"),
        ("tr_kesinti_olur", r"kesinti olur|kesinti olacaktır", "kesinti olabilir", "outage"),
        ("tr_kesinti_yasanir", r"kesinti yaşanır|kesinti yaşanacaktır|kesinti yaşanacak", "kesinti yaşanabilir", "outage"),
        ("tr_veri_kaybi", r"veri kaybı yaşanır|veri kaybı olur|veri kaybı yaşanacaktır", "veri kaybı yaşanabilir", None),
        ("tr_kesintiye_ugrar", r"kesintiye uğrar|kesintiye uğruyor|kesintiye uğrayacak", "kesintiye uğrayabilir", "outage"),
        ("tr_coker", r"çöker|çöküyor|çökecek", "çökebilir", None),
        ("tr_kaybolur", r"kaybolur|kayboluyor|kaybolacak", "kaybolabilir", None),
        ("tr_durur", r"durur|duruyor|duracak", "durabilir", "outage"),
        ("tr_engelle", r"engeller|engelliyor|engelleyecek", "engelleyebilir", None),
        ("tr_bozar", r"bozar|bozuyor|bozacak", "bozabilir", None),
        ("tr_tehlike", r"tehlikeye atar|tehlikeye atıyor", "tehlikeye atabilir", None),
        ("tr_risk", r"riske atar|riske atıyor", "riske atabilir", None),
        ("tr_etkiliyor", r"etkiliyor|etkileyecek", "etkileyebilir", None),
        ("tr_yasanir", r"yaşanır", "yaşanabilir", None),
        # TR — 'sığmaz' yalnız hesap 'fail' diyorsa kalır
        ("tr_sigmaz", r"sığmaz|sığmıyor", "sığmayabilir", "nofit"),
        ("tr_yerlesemez", r"yerleşemez|yerleşemiyor", "yerleşemeyebilir", "nofit"),
        ("tr_failover", r"failover mümkün değil", "failover mümkün olmayabilir", "nofit"),
        # EN
        ("en_will", r"will (?:stop|cause|lead to|result in|fail|crash|occur)", None, "outage"),
        ("en_affects", r"negatively affects|adversely affects", "may negatively affect", None),
        ("en_leads", r"leads to", "may lead to", "outage"),
        ("en_causes", r"causes", "may cause", "outage"),
        ("en_results", r"results in", "may result in", "outage"),
        ("en_stops", r"stops", "may stop", "outage"),
        ("en_crashes", r"crashes", "may crash", None),
        ("en_lost", r"(?:will be|is) lost", "may be lost", None),
        ("en_nofit", r"(?:do|does|will) not fit|cannot fit", "may not fit", "nofit"),
        ("en_noplace", r"cannot be placed", "may not be placed", "nofit"),
    )
]

_DATA_LOSS = re.compile(r"veri kayb|bellek kayb|data loss|lose data|lost data", re.I)
_SCENARIO = re.compile(r"host kapan|host düş|kapanması durumunda|kapanırsa|düşerse|arıza(?:sı)? durumunda|failover|kalan host|"
                       r"if the host|host goes down|fails over|remaining host", re.I)
# Belirsiz gönderme: "Bu durum ..." — hangi senaryo olduğu söylenmiyor
_VAGUE_TR = re.compile(r"^\s*(?:Bu durum\w*|Bu sonuç\w*|Bu da|Bu nedenle|Bu yüzden)\b", re.I)
_VAGUE_EN = re.compile(r"^\s*(?:This situation|This outcome|This result|This|That)\b", re.I)

SENT_SPLIT = re.compile(r"((?<=[.!?])\s+)")


def _impact(facts: Dict[str, Any]) -> Dict[str, Any]:
    return facts.get("host_dusarse_etki") or {}


def _supported(kind: Optional[str], facts: Dict[str, Any], field: str, sentence: str) -> bool:
    imp = _impact(facts)
    if imp.get("verdict") != "fail":
        return False
    if kind == "nofit":
        return True
    if kind == "outage":
        if _DATA_LOSS.search(sentence):
            return False                                  # hesap veri kaybını göstermez
        return field == "etki" or bool(_SCENARIO.search(sentence))
    return False


def _match_case(src: str, rep: str) -> str:
    return rep[:1].upper() + rep[1:] if src[:1].isupper() else rep


# Kodla yazılmış sabit cümleler (yeniden yazım / öneri düzeltme) — bunlara tekrar dokunulmaz
def consequence_sentence(facts: Dict[str, Any], lang: str) -> str:
    imp = _impact(facts)
    if lang == "en":
        return ("If the host goes down, these VMs cannot keep running; there is no other host in scope."
                if imp.get("remaining_hosts") == 0 else "If the host goes down, these VMs do not fit on the remaining hosts.")
    return ("Host kapanırsa bu VM'ler çalışmaya devam edemez; kapsamda başka host yok."
            if imp.get("remaining_hosts") == 0 else "Host kapanırsa bu VM'ler kalan host'lara sığmaz.")


def soften_text(text: str, facts: Dict[str, Any], corpus: str, field: str = "", protected: Optional[Set[str]] = None,
                lang: str = "tr") -> Tuple[str, List[Dict[str, str]]]:
    """Bir metindeki desteksiz kesin hükümleri cümle bazında olasılık diline çevirir; `etki` alanında belirsiz
    göndermeleri senaryoyu açıkça söyleyecek şekilde yeniden yazar. (yeni metin, değişiklikler)"""
    protected = protected or set()
    imp_verdict = _impact(facts).get("verdict")
    parts = SENT_SPLIT.split(text)
    changes: List[Dict[str, str]] = []
    seen_cons = False
    for i in range(0, len(parts), 2):
        sent = parts[i]
        core = sent.strip()
        low = core.lower()
        if not core or low in corpus or low in protected:   # kodla yazılmış cümle: dokunma
            continue
        new = sent
        used: List[str] = []
        # 1) belirsiz gönderme ("Bu durum ...") — yalnız etki alanında
        if field == "etki" and imp_verdict:
            vague = (_VAGUE_EN if lang == "en" else _VAGUE_TR).match(new)
            if vague:
                if imp_verdict == "fail":
                    cons = consequence_sentence(facts, lang)
                    lead = new[:len(new) - len(new.lstrip())]
                    trail = new[len(new.rstrip()):]
                    new = "" if seen_cons else lead + cons + trail
                    seen_cons = True
                    used.append("vague_to_scenario")
                else:
                    body = new.strip()
                    lead = new[:len(new) - len(new.lstrip())]
                    new = lead + ("If the host goes down, " if lang == "en" else "Host kapanırsa ") + body[:1].lower() + body[1:]
                    used.append("vague_prefix")
        if used and not new.strip():
            parts[i] = ""
            changes.append({"rule": ",".join(used), "before": core[:300], "after": ""})
            continue
        if "vague_to_scenario" in used:
            parts[i] = new
            changes.append({"rule": ",".join(used), "before": core[:300], "after": new.strip()[:300]})
            protected.add(new.strip().lower())
            continue
        # 2) kesin hüküm fiilleri
        for rid, rx, rep, sup in _SOFTEN_RULES:
            if sup and _supported(sup, facts, field, new):
                continue

            def sub(m, rid=rid, rep=rep):
                used.append(rid)
                if rep is None:                              # İngilizce 'will X' → 'may X'
                    return "may " + m.group(0).split(" ", 1)[1]
                return _match_case(m.group(0), rep)
            new = rx.sub(sub, new)
        if new != sent:
            parts[i] = new
            changes.append({"rule": ",".join(dict.fromkeys(used)), "before": core[:300], "after": new.strip()[:300]})
    out = "".join(parts)
    if any(not c["after"] for c in changes):                 # cümle düşürüldüyse boşlukları toparla
        out = re.sub(r"\s{2,}", " ", out).strip()
    return out, changes


def _map_fields(content: Dict[str, Any], fn) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    """İçeriğin tüm metin/liste alanlarına `fn(text, field) -> (yeni, değişiklikler)` uygular."""
    out: Dict[str, Any] = {}
    log: List[Dict[str, str]] = []
    for k, v in content.items():
        if isinstance(v, str):
            nv, ch = fn(v, k)
            out[k] = nv
            log += [{"field": k, **c} for c in ch]
        elif isinstance(v, list):
            items = []
            for n, x in enumerate(v):
                nx, ch = fn(x, f"{k}[{n}]") if isinstance(x, str) else (x, [])
                items.append(nx)
                log += [{"field": f"{k}[{n}]", **c} for c in ch]
            out[k] = items
        else:
            out[k] = v
    return out, log


def _corpus_lower(facts: Dict[str, Any]) -> str:
    return json.dumps(facts, ensure_ascii=False).lower()


def soften(content: Dict[str, Any], facts: Dict[str, Any], lang: str = "tr",
           protected: Optional[Set[str]] = None) -> Tuple[Dict[str, Any], List[Dict[str, str]]]:
    corpus = _corpus_lower(facts)
    prot = set(protected or ())
    return _map_fields(content, lambda text, field: soften_text(text, facts, corpus, field.split("[")[0], prot, lang))


# ── Öneri ↔ gerçek denetimi ──────────────────────────────────────────────────
# Kalan host 0 iken tahliye/taşıma/vMotion/boşaltma ÖNERİSİ verilemez (hedef yok): cümle sabit alternatifle değişir.
# Yalnız ÖNERİ/EYLEM cümleleri değişir; bulgu başlığı/gözlem cümlesi ("vMotion etkin VMkernel yok") dokunulmaz.
# Sabit alternatif cümle yalnız BİR yerde (öncelik > etki > özet > olay > listeler) yazılır; diğer yerlerde cümle düşer.
_MOVE_TR = re.compile(r"tahliye|boşalt|taşı(?:n|ma|mak|y|r|d|t)\w*|vmotion|migrat\w*|evacuat\w*|live[- ]migrat\w*|\bdrain\w*", re.I)
_ALT_OK = re.compile(r"cluster|bakım penceresi|maintenance window", re.I)
_REC_CUE = re.compile(r"öner|\bedin\b|\bediniz\b|edilmeli|edilmesi|\w+(?:malı|meli)\b|taşıyın|boşaltın|aktarın|yapın|planla\w*|gerek\w*|"
                      r"değerlendir\w*|düşün\w*|\bshould\b|\bconsider\b|\bplan\w*|recommend\w*|\bmust\b|\bneed\w*|\bavoid\b|"
                      r"\bbefore\b|\bfirst\b|\bnext\b|\bthen\b|\bmigrate\b|\bevacuate\b|\bdrain\b", re.I)
_FIX_ORDER = ("oncelik", "etki", "ozet", "olay_gorunumu", "gozlenen", "genel_bilgi", "diger_iyilestirmeler", "bilinmeyenler")


def alternative_sentence(lang: str) -> str:
    if lang == "en":
        return ("Because there is no other host in scope, moving VMs between hosts is not possible; "
                "consider moving them to another cluster or planning a maintenance window.")
    return ("Kapsamda başka host olmadığı için VM'leri host'lar arasında taşımak mümkün değil; "
            "başka bir cluster'a taşımayı veya bakım penceresi planlamayı değerlendirin.")


def _fact_titles(facts: Dict[str, Any]) -> List[str]:
    out = []
    for k in ("olay_bulgulari", "diger_bulgular"):
        for m in facts.get(k) or []:
            t = (m.get("baslik") or "").strip().lower()
            if len(t) >= 8:
                out.append(t)
    return out


def fix_recommendations(content: Dict[str, Any], facts: Dict[str, Any], lang: str = "tr"
                        ) -> Tuple[Dict[str, Any], List[Dict[str, str]], Set[str]]:
    """Kalan host sayısı 0 ise hedefsiz taşıma/tahliye önerilerini sabit alternatifle değiştirir (deterministik)."""
    imp = _impact(facts)
    if imp.get("remaining_hosts") != 0 or not imp:
        return content, [], set()
    corpus = _corpus_lower(facts)
    titles = _fact_titles(facts)
    alt = alternative_sentence(lang)
    protected = {alt.lower()}
    state = {"done": any(alt.lower() in (v.lower() if isinstance(v, str) else " ".join(v).lower())
                         for v in content.values() if isinstance(v, (str, list)))}
    log: List[Dict[str, str]] = []

    def fix_text(text: str, field: str) -> str:
        parts = SENT_SPLIT.split(text)
        changed = False
        for i in range(0, len(parts), 2):
            sent = parts[i]
            core = sent.strip()
            low = core.lower()
            if not core or low in corpus or low in protected:
                continue
            if any(t in low for t in titles):                       # bulgu başlığı/gözlem: öneri değil
                continue
            if _MOVE_TR.search(core) and _REC_CUE.search(core) and not _ALT_OK.search(core):
                lead = sent[:len(sent) - len(sent.lstrip())]
                replaced = "" if state["done"] else alt
                state["done"] = True
                parts[i] = (lead + replaced) if replaced else ""
                changed = True
                log.append({"field": field, "rule": "no_remaining_host", "before": core[:300], "after": replaced})
        out = "".join(parts)
        return re.sub(r"\s{2,}", " ", out).strip() if changed else out

    new: Dict[str, Any] = dict(content)
    order = [k for k in _FIX_ORDER if k in new] + [k for k in new if k not in _FIX_ORDER]
    for k in order:
        v = new[k]
        if isinstance(v, str):
            new[k] = fix_text(v, k)
        elif isinstance(v, list):
            items = [fix_text(x, f"{k}[{n}]") if isinstance(x, str) else x for n, x in enumerate(v)]
            new[k] = [x for x in items if not (isinstance(x, str) and not x.strip())]
    return new, log, (protected if log else set())


# ── Yumuşatılmamış kesin cümle sayımı (telemetri) ────────────────────────────
_CONSEQ = re.compile(r"kesinti|kayb|hizmet dışı|erişilemez|çalışma(?:sı|ması|yı|sını|ya devam)|outage|downtime|data loss|unavailable", re.I)
_HEDGED = re.compile(r"olabilir|olabilecek|\w+(?:abilir|ebilir|abileceği|ebileceği)|\brisk\w*|muhtemel|olası|ihtimal|önerilir|"
                     r"gerekir|gerekli\w*|\w+(?:malı|meli)\b|değerlendirin|\bmay\b|\bmight\b|\bcould\b|\bcan\b|possible|likely|"
                     r"potential|recommend|should|consider", re.I)
_FINITE_TR = re.compile(r"\w{3,}(?:ar|er|ır|ir|ur|ür|yor|ıyor|uyor|üyor|ecek|acak|ez|maz|mez|dır|dir|dur|dür)$", re.I)
_NARRATIVE = ("ozet", "olay_gorunumu", "etki", "oncelik", "genel_bilgi", "diger_iyilestirmeler")


def unsoftened_definitive(content: Dict[str, Any], facts: Dict[str, Any], changed: List[Dict[str, str]],
                          lang: str = "tr") -> List[Dict[str, str]]:
    """Sözlükte olmayan kesin fiillerle yazılmış (yumuşatılmamış, desteksiz) sonuç cümleleri — eksik fiilleri görmek için."""
    corpus = _corpus_lower(facts)
    touched = {c.get("after", "").strip().lower() for c in changed}
    found: List[Dict[str, str]] = []
    for field in _NARRATIVE:
        v = content.get(field)
        items = [v] if isinstance(v, str) else (v or [])
        for n, text in enumerate(items):
            for sent in SENT_SPLIT.split(text)[::2]:
                core = sent.strip()
                low = core.lower()
                if not core or low in corpus or low in touched or low in (consequence_sentence(facts, lang).lower(), alternative_sentence(lang).lower()):
                    continue
                if not _CONSEQ.search(core) or _HEDGED.search(core):
                    continue
                last = re.sub(r"[^\w]+$", "", core).split(" ")[-1] if core else ""
                finite = bool(_FINITE_TR.search(last)) if lang != "en" else bool(re.search(r"\bwill\b", core, re.I))
                if not finite:
                    continue
                if _supported("outage", facts, field, core):
                    continue
                found.append({"field": field if isinstance(v, str) else f"{field}[{n}]", "sentence": core[:300]})
    return found


def postprocess(content: Dict[str, Any], facts: Dict[str, Any], lang: str = "tr"
                ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """(yeni içerik, telemetri). Telemetri `validation` alanına yazılır."""
    content, rec_fixes, protected = fix_recommendations(content, facts, lang)
    content, softened = soften(content, facts, lang, protected)
    left = unsoftened_definitive(content, facts, softened + rec_fixes, lang)
    return content, {
        "softened_count": len(softened), "softened_sentences": softened,
        "recommendation_fixes": rec_fixes,
        "unsoftened_definitive_count": len(left), "unsoftened_definitive": left[:10],
    }
