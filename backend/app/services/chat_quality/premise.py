"""Yanlış öncül kuralı (Adım 7a) — sayım kuralı katmanı, LLM'e/araca gitmeden.

Kapsanan biçimler (tam cümle; çapa `^…$`):
  1. Sayı öncülü      «office vCenter'da 46 VM var, bunların kaçı kapalı?» · «Ortamda 3000 VM var, doğru mu?»
                      «We have 3000 VMs, how many are off?»
  2. Evrensel öncül   «Tüm VM'ler çalışıyor, değil mi?» · «All VMs are running, right?»
  3. Yokluk öncülü    «Datatem OLVM'de hiç kapalı VM yok, doğru mu?» · «Tüm clusterlarda hiç hatalı pod yok, değil mi?»
  4. Node durumu      «oVirt cluster'ında 12 node var, hangisi NotReady?» (yalnız node Ready/NotReady)

Yöntem: öncülden SORULAN sayım sorusu kurulur (`«<kapsam> kaç <durum> <isim> var?»`) ve mevcut sayım kuralı
(`count_rules.analyze` + `answer`) çalıştırılır; kapsam çözümü, RBAC, tazelik ve render AYNEN oradan gelir.
Hüküm (öncül doğru/yanlış, evet/hayır) cevabın başlığındaki sayılardan çıkar — hüküm ile gösterilen sayı
birbirinden ayrışamaz. Çözümlenemeyen her şey `None` (normal akış; sessiz yanlış yok).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.chat_quality.claims import fold

logger = logging.getLogger(__name__)

_APO = r"(?:'[a-z]+)?"
_NOUN = (
    r"(?:vm|vms|vm(?:ler|lerim|lerin|leri|im|in|i)|sanal\s+makine\w*|makine\w*|machines?|host\w*|node\w*|pod\w*|"
    r"cluster\w*|datastore\w*|sunucu\w*|servers?|proje\w*|projects?|namespace\w*)"
)
_TAIL = r"(?:degil\s+mi|dogru\s+mu|oyle\s+mi|dogru\s+degil\s+mi|mi|mu)"
_VERIFY_RE = re.compile(r"^(?:dogru\s+mu|degil\s+mi|oyle\s+mi|dogru\s+degil\s+mi)$")

# ── Türkçe ────────────────────────────────────────────────────────────────────────
_CLAIM_TR = re.compile(
    rf"^(?P<pre>.*?)(?<![\w.\-])(?P<n>\d{{1,7}})\s+(?P<noun>{_NOUN}){_APO}\s+"
    r"(?:var|bulunuyor|bulunmakta|mevcut|kayitli)\s*(?:[,;.]|\bve\b)?\s*(?P<rest>.*)$"
)
_ABS_TR = re.compile(
    rf"^(?P<pre>.*?)\bhic\s+(?P<st>[a-z]+)\s+(?P<noun>{_NOUN}){_APO}\s+"
    rf"(?:yok|bulunmuyor|bulunmamakta|mevcut\s+degil)\s*(?:[,;.]\s*)?(?P<tag>{_TAIL})?\s*\??$"
)
_UNIV_TR = re.compile(
    rf"^(?P<pre>.*?)\b(?:tum|butun)\s+(?P<noun>{_NOUN}){_APO}\s+(?P<st>[a-z]+)\s*(?:[,;.]\s*)?"
    rf"(?P<tag>{_TAIL})?\s*\??$"
)
_REST_LEAD = re.compile(r"^(?:peki\s+)?(?:bunlarin|bunlardan|bunlar|bu)?\s*")
_ASK_COUNT = re.compile(r"^(?:kaci|kac\s+tanesi|kacini|kac\s+adedi|kac\s+adet|kac)\s*(?P<st>[a-z]*)$")
_ASK_WHICH = re.compile(r"^(?:hangisi|hangileri)\s+(?P<st>[a-z]+)$")

# ── İngilizce ─────────────────────────────────────────────────────────────────────
_CLAIM_EN = re.compile(
    rf"^(?:we\s+have|there\s+are|i\s+have|the\s+environment\s+has|our\s+environment\s+has)\s+(?P<n>\d{{1,7}})\s+"
    rf"(?P<noun>{_NOUN})(?:\s+(?:on|in|at)\s+(?P<loc>[a-z0-9 ._\-']+?))?\s*[,;.]\s*(?:and\s+)?"
    r"how\s+many\s+(?:of\s+(?:them|these)\s+)?(?:are\s+)?(?P<st>[a-z ]+?)\s*\??$"
)
_ABS_EN = re.compile(
    rf"^(?:there\s+(?:are|is)\s+no|no)\s+(?P<st>[a-z ]+?)\s+(?P<noun>{_NOUN})"
    r"(?:\s+(?:on|in|at)\s+(?P<loc>[a-z0-9 ._\-']+?))?\s*[,;.]?\s*(?:right|correct|is\s+that\s+(?:right|correct))\s*\??$"
)
_UNIV_EN = re.compile(
    rf"^all\s+(?:the\s+|of\s+the\s+)?(?P<noun>{_NOUN})(?:\s+(?:on|in|at)\s+(?P<loc>[a-z0-9 ._\-']+?))?\s+"
    r"(?:are\s+)?(?P<st>[a-z ]+?)\s*[,;.]?\s*(?:right|correct|aren't\s+they|isn't\s+that\s+so)\s*\??$"
)

_NODE_STATES = {
    "notready": "notready", "hazirdegil": "notready", "ready": "ready", "hazir": "ready",
}
_FAULTY_WORDS = {"hatali", "sorunlu", "problemli", "bozuk", "failed", "faulty", "unhealthy", "broken", "crashloopbackoff"}
_LABEL = {"vm": "VM", "host": "host", "node": "node", "pod": "pod", "cluster": "cluster",
          "datastore": "datastore", "project": "proje", "server": "sunucu", "hypervisor": "hypervisor"}
_STATE_LABEL = {"on": "çalışan (açık)", "off": "kapalı", "suspended": "askıda", "all": ""}

_HEAD_N = re.compile(r"\*\*[^*\n:]+:\s*(\d+)\*\*")
_HEAD_TOTAL = re.compile(r"kapsamdaki toplam (\d+)")


def _norm(message: str) -> str:
    mf = fold(message or "")
    mf = re.sub(r"[\u2019`´]", "'", mf)
    return re.sub(r"\s+", " ", mf).strip()


def _noun_label(noun: str) -> str:
    n = noun.strip()
    for key, rx in (
        ("vm", r"^(?:vm\w*|sanal|makine\w*|machine\w*)"), ("host", r"^host"), ("node", r"^node"),
        ("pod", r"^pod"), ("cluster", r"^cluster"), ("datastore", r"^datastore"),
        ("server", r"^(?:sunucu|server)"), ("project", r"^(?:proje|project|namespace)"),
    ):
        if re.match(rx, n):
            return key
    return ""


def looks_like_premise(message: str) -> bool:
    """Ucuz sözdizimi denemesi (DB yok) — tam tarama onay kapısı bu mesajı atlar."""
    mf = _norm(message)
    if not mf or len(mf) > 220 or "\n" in (message or ""):
        return False
    return _parse(mf) is not None


def _state_for_vm(st: str) -> Optional[str]:
    from app.services.chat_quality.count_rules import _STATE_BY_WORD
    return _STATE_BY_WORD.get(st)


_EN_STATE = {"off": "kapali", "powered off": "kapali", "stopped": "kapali", "shut down": "kapali",
             "on": "acik", "powered on": "acik", "running": "calisan", "up": "calisan",
             "suspended": "askida", "faulty": "hatali", "failing": "hatali", "failed": "hatali",
             "unhealthy": "hatali", "broken": "hatali", "problematic": "hatali"}


def _parse(mf: str) -> Optional[Dict[str, Any]]:
    """Folded mesaj → {form, topic, n, pre|loc, st, verify, lang} ya da None."""
    m = _ABS_TR.match(mf)
    if m:
        t = _noun_label(m.group("noun"))
        if t and (m.group("tag") or mf.rstrip().endswith("?")):
            return {"form": "absence", "topic": t, "pre": m.group("pre"), "st": m.group("st"), "lang": "tr"}
    m = _UNIV_TR.match(mf)
    if m and m.group("tag"):
        t = _noun_label(m.group("noun"))
        if t and m.group("st") not in ("var", "yok", "hic"):
            return {"form": "universal", "topic": t, "pre": m.group("pre"), "st": m.group("st"), "lang": "tr"}
    m = _CLAIM_TR.match(mf)
    if m:
        t = _noun_label(m.group("noun"))
        rest = _REST_LEAD.sub("", m.group("rest").strip(" ?.!,;")).strip()
        if t and rest:
            if _VERIFY_RE.match(rest):
                return {"form": "claim", "topic": t, "pre": m.group("pre"), "n": int(m.group("n")),
                        "st": "", "verify": True, "lang": "tr"}
            a = _ASK_COUNT.match(rest)
            if a:
                return {"form": "claim", "topic": t, "pre": m.group("pre"), "n": int(m.group("n")),
                        "st": a.group("st") or "", "lang": "tr"}
            w = _ASK_WHICH.match(rest)
            if w and t == "node":
                return {"form": "claim_which", "topic": t, "pre": m.group("pre"), "n": int(m.group("n")),
                        "st": w.group("st"), "lang": "tr"}
    m = _CLAIM_EN.match(mf)
    if m:
        t = _noun_label(m.group("noun"))
        if t:
            return {"form": "claim", "topic": t, "loc": m.group("loc") or "", "n": int(m.group("n")),
                    "st": m.group("st").strip(), "lang": "en"}
    m = _ABS_EN.match(mf)
    if m:
        t = _noun_label(m.group("noun"))
        if t:
            return {"form": "absence", "topic": t, "loc": m.group("loc") or "", "st": m.group("st").strip(), "lang": "en"}
    m = _UNIV_EN.match(mf)
    if m:
        t = _noun_label(m.group("noun"))
        if t:
            return {"form": "universal", "topic": t, "loc": m.group("loc") or "", "st": m.group("st").strip(), "lang": "en"}
    return None


def _ask_question(p: Dict[str, Any], st_override: Optional[str] = None) -> str:
    """Parse sonucundan sayım sorusu kur (katlanmış metin)."""
    st = p["st"] if st_override is None else st_override
    noun = {"vm": "vm", "host": "host", "node": "node", "pod": "pod", "cluster": "cluster",
            "datastore": "datastore", "server": "sunucu", "project": "proje"}.get(p["topic"], p["topic"])
    if p["lang"] == "en":
        st = _EN_STATE.get(st, st)
        loc = f" on {p['loc']}" if p.get("loc") else ""
        return re.sub(r"\s+", " ", f"how many {st} {noun}{loc}?").strip()
    st = _EN_STATE.get(st, st)
    return re.sub(r"\s+", " ", f"{p.get('pre', '')} kac {st} {noun} var?").strip()


def _parse_head(text: str) -> Optional[Tuple[int, int]]:
    """Cevap metninden (sayı, kapsamdaki toplam)."""
    m = _HEAD_N.search(text or "")
    if not m:
        return None
    n = int(m.group(1))
    t = _HEAD_TOTAL.search(text)
    return n, (int(t.group(1)) if t else n)


def _state_label(plan) -> str:
    if getattr(plan, "pod_filter", ""):
        pf = plan.pod_filter
        if pf == "faulty":
            return "hatalı"
        if pf.startswith("reason:"):
            return pf.split(":", 1)[1]
        if pf.startswith("status:"):
            return pf.split(":", 1)[1]
        return ""
    return _STATE_LABEL.get(getattr(plan, "state", "all"), "")


def _node_state_text(p: Dict[str, Any], cat, db) -> Optional[Tuple[str, Any]]:
    """«N node var, hangisi NotReady?» — yalnız node Ready/NotReady; (metin, Plan) ya da None."""
    from sqlalchemy import text as sql
    from app.services.chat_quality import count_rules as cr
    from app.services.chat_quality.count_scope import resolve_ocp, scope_label, tokenize
    st = _NODE_STATES.get(p["st"].replace("_", "").replace("-", ""))
    if not st:
        return None
    pre = p.get("pre", "")
    toks = [t for t, _, _ in tokenize(pre)]
    neutral = set(cr._NEUTRAL) | set(cr._COUNT_WORDS)
    sc = resolve_ocp(pre, cat, neutral=neutral)
    for i, w in enumerate(toks):
        if i in sc.consumed or w in neutral or w in ("cluster", "clusterinda", "clusterda", "cluster'inda"):
            continue
        if cr._noun_topic(w) in ("cluster", "node"):
            continue
        return None
    ids = sc.ocp_ids if sc.ocp_ids is not None else [cid for cid, _ in cat.ocp_clusters]
    if not ids:
        return None
    rows = db.execute(
        sql("select name, status, cluster_id from openshift_nodes where cluster_id = any(:ids) order by name"),
        {"ids": list(ids)},
    ).all()
    total = len(rows)
    ready = [r for r in rows if str(r[1] or "").strip().lower() == "ready"]
    notready = [r for r in rows if r not in ready]
    want = notready if st == "notready" else ready
    label = "NotReady" if st == "notready" else "Ready"
    plan = cr.Plan(kind="count", topic="node", state="all", domain="ocp")
    plan.ocp_scope = sc
    L = [_premise_line(p["n"], total, "node"), ""]
    L.append(f"{label} node: **{len(want)}** (kapsamdaki toplam {total} node içinde; Ready {len(ready)}, NotReady {len(notready)})")
    if want and len(want) <= 20:
        L += ["", f"| {label} node | Durum |", "|---|---|"] + [f"| {cr._cell(r[0])} | {cr._cell(r[1])} |" for r in want]
    L += ["", f"Kapsam: {scope_label(sc, cat, domain='ocp')}"]
    L += ["", cr._source_line(cr.fetch_ocp_last_sync(db, ids))]
    return "\n".join(L), plan


def _premise_line(claimed: int, actual: int, topic: str) -> str:
    label = _LABEL.get(topic, topic)
    if claimed == actual:
        return f"**Öncül doğru:** kayıtta bu kapsamda **{actual}** {label} var."
    return (f"**Öncül yanlış:** sorunuzda **{claimed}** {label} var deniyor; kayıtta bu kapsamda "
            f"**{actual}** {label} var ({claimed} değil).")


def respond(message: str, *, platform: Optional[str] = None, allowed_modules: Any = None) -> Optional[Tuple[str, Any, str, Dict[str, Any]]]:
    """(metin, plan, eff_soru, iz) ya da None. Hata → None (normal akış)."""
    mf = _norm(message)
    if not mf or len(mf) > 220 or "\n" in (message or ""):
        return None
    p = _parse(mf)
    if p is None:
        return None
    try:
        from app.core.database import ThreadSessionLocal
        from app.services.chat_quality import count_rules as cr
        if not cr._enabled():
            return None
        cat = cr.get_catalog()
        if cat is None:
            return None
        form, topic = p["form"], p["topic"]

        if form == "claim_which":
            if not cr.ocp_ok(platform, allowed_modules):
                return None
            db = ThreadSessionLocal()
            try:
                out = _node_state_text(p, cat, db)
            finally:
                db.close()
            if out is None:
                return None
            text, plan = out
            return text, plan, mf, {"form": form, "claimed": p["n"], "topic": topic}

        # soru: claim → (durum varsa durumlu), absence → durumlu, universal → durumlu
        q = _ask_question(p)
        plan = cr.analyze(q, cat, platform=platform, allowed_modules=allowed_modules)
        if plan is None or plan.topic != topic:
            return None
        if form in ("absence", "universal") and not (plan.pod_filter or plan.state != "all"):
            return None                       # durum çözülemedi → öncül hükmü verilemez
        db = ThreadSessionLocal()
        try:
            body = cr.answer(plan, cat, db)
        finally:
            db.close()
        if not body:
            return None
        head = _parse_head(body)
        if head is None:
            return None
        n, total = head
        trace = {"form": form, "topic": topic, "n": n, "total": total}
        if form == "claim":
            trace["claimed"] = p["n"]
            line = _premise_line(p["n"], total, topic)
            return f"{line}\n\n{body}", plan, q, trace
        sl = _state_label(plan)
        label = _LABEL.get(topic, topic)
        if form == "absence":
            if n == 0:
                line = f"**Evet:** kapsamda {sl} {label} yok (0)."
            else:
                line = f"**Hayır:** kapsamda **{n}** {sl} {label} var."
        else:  # universal
            if total > 0 and n == total:
                line = f"**Evet:** kapsamdaki {total} {label} içinde hepsi {sl}."
            else:
                line = (f"**Hayır:** kapsamdaki toplam {total} {label} içinde {sl} olan {n}; "
                        f"{sl} olmayan **{total - n}**.")
        trace["verdict"] = line.split(":")[0].strip("*")
        return f"{line}\n\n{body}", plan, q, trace
    except Exception:
        logger.warning("[Premise] kural hatası (normal akışa dönülüyor)", exc_info=True)
        return None
