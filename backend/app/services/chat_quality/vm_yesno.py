"""Evet/hayır VM güç durumu şablonu (Adım 6b-1).

«Harvester VM'i çalışıyor mu?», «dttadvance açık mı?», «X kapalı mı?» → envanterdeki (servers) güç durumu ile
«Evet/Hayır — <ad> kapalı (POWERED_OFF)» + hypervisor/host + son senkron. Aynı adla birden çok kayıt → hepsi
tabloda. Kayıt yoksa None (varlık kapısı / normal akış). RBAC: yalnız sanallaştırma erişimi (`count_rules.virt_ok`).
"""
from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.chat_quality import power_state as ps
from app.services.chat_quality.claims import fold
from app.services.chat_quality.count_scope import TYPE_LABEL, tokenize

logger = logging.getLogger(__name__)

# (soru yüklemi, beklenen durum)
_PRED = [
    (("calisiyor", "mu"), "on"), (("calisiyor", "mi"), "on"), (("acik", "mi"), "on"), (("ayakta", "mi"), "on"),
    (("running", "mi"), "on"), (("kapali", "mi"), "off"), (("askida", "mi"), "suspended"),
    (("is", "running"), "on"), (("powered", "on"), "on"), (("powered", "off"), "off"),
]
_FILLER = {"vm", "vmi", "vm'i", "i", "si", "in", "sanal", "makine", "makinesi", "makina", "makinasi", "su", "an",
           "simdi", "hala", "hl", "the", "is", "isimli", "adli"}
_BLOCK = {"hangi", "kac", "neden", "ne", "zaman", "nezaman", "dun", "bugun", "son", "en", "tum", "butun", "hepsi",
          "vmler", "vmleri", "listele", "goster", "host", "hostlar", "cluster", "pod", "node", "servis", "service",
          "disk", "cpu", "ram", "uygulama", "web", "veritabani", "db", "ve", "veya", "and", "or",
          "ler", "lar", "leri", "lari", "lerin", "larin"}


def parse(message: str) -> Optional[Tuple[str, str]]:
    """→ (aday ad, beklenen durum) veya None."""
    if not message or len(message) > 120:
        return None
    mf = fold(message)
    words = [t for t, _, _ in tokenize(mf.replace("'", " ").replace("’", " "))]
    if len(words) < 3:
        return None
    want = None
    for pred, st in _PRED:
        n = len(pred)
        if tuple(words[-n:]) == pred:
            want = st
            words = words[:-n]
            break
    if want is None:
        return None
    if any(w in _BLOCK for w in words):
        return None
    name = [w for w in words if w not in _FILLER]
    if len(name) != 1 or len(name[0]) < 3:
        return None
    return name[0], want


def fetch(db, name: str) -> List[Dict[str, Any]]:
    from sqlalchemy import text
    sql = (
        "select coalesce(vm_name, name), hypervisor_id, vm_power_state, vm_host_name, vm_cluster, vm_last_sync "
        "from servers where hypervisor_id is not null and ("
        "lower(name) = :n or lower(vm_name) = :n or lower(hostname) = :n or lower(vm_guest_hostname) = :n) "
        "order by hypervisor_id, name"
    )
    return [{"name": r[0], "hv": int(r[1]), "power": r[2], "host": r[3], "cluster": r[4], "ts": r[5]}
            for r in db.execute(text(sql), {"n": name.lower()}).all()]


def _verdict(cls: str, want: str) -> str:
    if cls in ("transitional", "unknown"):
        return "Belirsiz"
    return "Evet" if cls == want else "Hayır"


def render(recs: List[Dict[str, Any]], want: str, hv_names: Dict[int, Tuple[str, str]]) -> str:
    from app.services.chat_quality.count_rules import _cell, _fmt_ts
    if len(recs) == 1:
        r = recs[0]
        cls = ps.classify(r.get("power"))
        hv = hv_names.get(r["hv"], (str(r["hv"]), ""))
        L = [f"**{_verdict(cls, want)}** — {_cell(r['name'])} {ps.label_tr(cls)} ({_cell(ps.pstate_label(r.get('power')))}).",
             "", f"- Hypervisor: {hv[0]} ({TYPE_LABEL.get(hv[1], hv[1])})", f"- Host: {_cell(r.get('host'))}",
             f"- Cluster: {_cell(r.get('cluster'))}", "",
             f"_Kaynak: envanter veritabanı; son senkron: {_fmt_ts(r.get('ts'))}._"]
        return "\n".join(L)
    verdicts = {_verdict(ps.classify(r.get("power")), want) for r in recs}
    head = next(iter(verdicts)) if len(verdicts) == 1 else "Kayda göre değişiyor"
    L = [f"**{head}** — «{_cell(recs[0]['name'])}» adıyla **{len(recs)} kayıt** var:", "",
         "| Hypervisor | Tür | Host | Güç durumu | Cevap | Son senkron |", "|---|---|---|---|---|---|"]
    for r in recs:
        cls = ps.classify(r.get("power"))
        hv = hv_names.get(r["hv"], (str(r["hv"]), ""))
        L.append(f"| {_cell(hv[0])} | {_cell(TYPE_LABEL.get(hv[1], hv[1]))} | {_cell(r.get('host'))} | "
                 f"{_cell(ps.pstate_label(r.get('power')))} | {_verdict(cls, want)} | {_fmt_ts(r.get('ts'))} |")
    L += ["", "_Kaynak: envanter veritabanı._"]
    return "\n".join(L)


def respond(message: str, *, platform: Optional[str] = None, allowed_modules: Any = None) -> Optional[str]:
    from app.services.chat_quality.count_rules import _enabled, get_catalog, virt_ok
    try:
        if not _enabled() or not virt_ok(platform, allowed_modules):
            return None
        p = parse(message)
        if p is None:
            return None
        cat = get_catalog()
        if cat is None:
            return None
        from app.core.database import ThreadSessionLocal
        db = ThreadSessionLocal()
        try:
            recs = fetch(db, p[0])
        finally:
            db.close()
        if not recs:
            return None
        text = render(recs, p[1], {h.id: (h.name, h.type) for h in cat.hypervisors})
    except Exception:
        logger.warning("[VmYesNo] hata (normal akışa dönülüyor)", exc_info=True)
        return None
    try:
        from app.services.chat_quality import trace as cq_trace
        cq_trace.note_path("qa_rule", handler="vm_yesno", rule="vm_yesno", want=p[1], records=len(recs))
    except Exception:
        pass
    return text
