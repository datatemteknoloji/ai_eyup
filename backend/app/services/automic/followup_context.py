"""Takip sorularında sorgu bağlamı — kodla saklanır ve çözülür (modele bırakılmaz).

Her cevaptan sonra saklanan bağlam: zaman penceresi, filtreler, sıralı nesne listesi, odak nesne.
Takip ifadeleri ("bunların", "aynı job", "ilki"…) bu bağlama çözülür; çözülemezse netleştirme sorusu.
"""
from __future__ import annotations

import contextvars
import re
from typing import Any, Dict, List, Optional, Tuple

_CTX: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "automic_followup_ctx", default=None)
_FORCED: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar(
    "automic_forced_filters", default=None)

_OBJ_RE = re.compile(
    r"\b(?:JOBS|JOBP|JOBF|JOBG|VARA|SCRI|SCRP|EVNT|FILE|CALE|SYNC|HOST|XCOM)\.[A-Z0-9_.]+",
    re.I)
_AGENT_RE = re.compile(r"\b(?:LNX|WIN|SAP)[A-Z0-9]+\b")
_FOLLOW_RE = re.compile(
    r"(?i)(?<!\w)(bunlar\w*|şunlar\w*|onlar\w*|bunun|bunu|buna|şunun|"
    r"aynı\s+job|aynı\s+iş|o\s+agent|o\s+nesne|"
    r"ilki|ilkini|sonuncusu|sonuncusunu|bunlardan|bunların|"
    r"peki\b)")
_IDX_FIRST = re.compile(r"(?i)\b(ilk(?:i|inin|ini)?|birinci(?:si|sini|sinin)?)\b")
_IDX_LAST = re.compile(r"(?i)\b(sonuncu(?:su|sunu|sunun)?|son\s+olan)\b")
_EN_COK_HATA = re.compile(
    r"(?i)\ben\s+[cç]ok\s+hata\s+veren|\ben\s+[cç]ok\s+hata\s+verenin|\bmost\s+fail"
)
_AYNI_JOB = re.compile(r"(?i)\bayn[ıi]\s+(?:job|iş|nesne)\b")
_BUNLARIN = re.compile(r"(?i)\bbunlar(?:ın|in|dan|den)?\b|\bşunlar(?:ın|in|dan|den)?\b|\bonlar(?:ın|in|dan|den)?\b")


_PREV_RUN = re.compile(
    r"(?i)\b(?:bir\s+)?[öo]nceki\s+[cç]al[ıi][sş]ma\w*|\bprevious\s+(?:run|execution)\b")


def set_active(ctx: Optional[Dict[str, Any]]) -> None:
    _CTX.set(ctx)


def get_active() -> Optional[Dict[str, Any]]:
    return _CTX.get()


def set_forced_filters(filters: Optional[Dict[str, Any]]) -> None:
    _FORCED.set(filters)


def forced_filters() -> Optional[Dict[str, Any]]:
    return _FORCED.get()


def apply_forced_filters(args: dict) -> dict:
    """Zorunlu takip filtrelerini args üzerine yazar (aynı nesne — iz ile uyumlu)."""
    f = _FORCED.get()
    if not f:
        return args
    for k in ("status_class", "status_code", "agent", "user", "client", "object_name", "object_type",
              "from", "to", "range"):
        if f.get(k) not in (None, ""):
            args[k] = f[k]
    if f.get("from") and f.get("to"):
        args.pop("range", None)
    # dahili meta araç args'a gitmez
    args.pop("_focus_object", None)
    return args


def build_from_structured(
    structured: List[Dict[str, Any]],
    *,
    message: str = "",
    window_label: Optional[str] = None,
    from_iso: Optional[str] = None,
    to_iso: Optional[str] = None,
) -> Dict[str, Any]:
    """Araç sonuçlarından saklanacak sorgu bağlamı."""
    filters: Dict[str, Any] = {}
    objects: List[str] = []
    seen = set()
    for sr in structured or []:
        if not isinstance(sr, dict):
            continue
        args = sr.get("args") or {}
        for k in ("status_class", "status_code", "agent", "user", "client", "object_name", "object_type"):
            if args.get(k) not in (None, "") and k not in filters:
                filters[k] = args[k]
        res = sr.get("result") if isinstance(sr.get("result"), dict) else {}
        if not from_iso and res.get("from"):
            from_iso = res.get("from")
        if not to_iso and res.get("to"):
            to_iso = res.get("to")
        # by_object önce (failed_count DESC) — "en çok hata veren" takibi için
        for row in res.get("by_object") or []:
            if isinstance(row, dict) and row.get("object_name") and row["object_name"] not in seen:
                seen.add(row["object_name"])
                objects.append(str(row["object_name"]))
        for row in res.get("rows") or []:
            if isinstance(row, dict) and row.get("object_name") and row["object_name"] not in seen:
                seen.add(row["object_name"])
                objects.append(str(row["object_name"]))
        for it in res.get("items") or []:
            if not isinstance(it, dict):
                continue
            name = it.get("object_name")
            if name and name not in seen:
                seen.add(name)
                objects.append(str(name))
        ex = res.get("execution")
        if isinstance(ex, dict) and ex.get("object_name") and ex["object_name"] not in seen:
            seen.add(ex["object_name"])
            objects.append(str(ex["object_name"]))
    focus = None
    # Zorunlu takip filtresi (ör. "bunlardan ilki" → object_name) odak sayılır
    forced = forced_filters() or {}
    fo = forced.get("_focus_object") or forced.get("object_name") or filters.get("object_name")
    if fo and "*" not in str(fo) and "%" not in str(fo):
        focus = str(fo)
    m = _OBJ_RE.search(message or "")
    if m and not focus:
        focus = m.group(0)
    if not focus and objects:
        focus = objects[0]
    return {
        "window_label": window_label,
        "from": from_iso,
        "to": to_iso,
        "filters": filters,
        "objects": objects[:40],
        "focus_object": focus,
    }


def resolve(message: str, prev: Optional[Dict[str, Any]], english: bool = False
            ) -> Tuple[Optional[Dict[str, Any]], str, Optional[str]]:
    """Takip ifadesini çöz.

    Döner: (forced_filters | None, assumption_line, clarify_question | None)
    """
    msg = (message or "").strip()
    # "bir önceki çalışmasının raporu": mesajda nesne yoksa odak nesne önceki bağlamdan KODLA çözülür
    if _PREV_RUN.search(msg) and not _OBJ_RE.search(msg):
        focus = (prev or {}).get("focus_object")
        if not focus:
            return None, "", ("Hangi job'un önceki çalışmasını kastediyorsunuz?" if not english
                              else "Which job's previous run do you mean?")
        return ({"object_name": focus, "_focus_object": focus},
                (f"**(Önceki sorudaki nesne: `{focus}`.)**" if not english
                 else f"**(Object from the previous question: `{focus}`.)**"), None)
    if not prev or not _FOLLOW_RE.search(msg):
        return None, "", None

    filters = dict(prev.get("filters") or {})
    forced: Dict[str, Any] = {}
    # önceki pencere
    if prev.get("from") and prev.get("to"):
        forced["from"], forced["to"] = prev["from"], prev["to"]
    for k in ("status_class", "status_code", "user", "client", "object_type"):
        if filters.get(k) not in (None, ""):
            forced[k] = filters[k]

    note_parts = []
    label = prev.get("window_label") or ""
    if label:
        note_parts.append(f"önceki sorudaki «{label}» kapsamında" if not english
                          else f"within previous «{label}» scope")

    # "bunların kaçı X'teydi" → agent ek filtre
    ag = _AGENT_RE.search(msg)
    if ag and _BUNLARIN.search(msg):
        forced["agent"] = ag.group(0)
        note_parts.append(f"agent={ag.group(0)}")
        if "status_class" not in forced and filters.get("status_class"):
            forced["status_class"] = filters["status_class"]

    # "aynı job"
    if _AYNI_JOB.search(msg):
        focus = prev.get("focus_object")
        if not focus:
            q = ("Hangi job'u kastediyorsunuz?" if not english else "Which job do you mean?")
            return None, "", q
        forced["object_name"] = focus
        note_parts.append(f"nesne={focus}" if not english else f"object={focus}")

    # "bunlardan ilki / sonuncusu / en çok hata vereni" → odak nesne
    objs = list(prev.get("objects") or [])
    if objs and (_IDX_FIRST.search(msg) or _IDX_LAST.search(msg) or _EN_COK_HATA.search(msg)):
        if _EN_COK_HATA.search(msg) or _IDX_FIRST.search(msg):
            pick = objs[0]
            how = "en çok hata veren" if _EN_COK_HATA.search(msg) else "ilk"
        else:
            pick = objs[-1]
            how = "son"
        forced["object_name"] = pick
        forced["status_class"] = forced.get("status_class") or "failed"
        forced["_focus_object"] = pick  # build_from_structured / sonraki "aynı job"
        note_parts.append(
            (f"listedeki {how} nesne: {pick}" if not english
             else f"{how} in list: {pick}"))

    # genel "bunların/peki" — pencere + filtreleri koru
    if not forced and not (_AYNI_JOB.search(msg) or ag):
        # en azından önceki filtreleri taşı
        for k, v in filters.items():
            if v not in (None, ""):
                forced[k] = v
        if prev.get("from") and prev.get("to"):
            forced["from"], forced["to"] = prev["from"], prev["to"]

    if not forced:
        q = ("Önceki sonuçlardan hangisini kastediyorsunuz?" if not english
             else "Which of the previous results do you mean?")
        return None, "", q

    if english:
        assumption = ("**(Previous scope:** " + "; ".join(note_parts) + ".)" if note_parts
                      else "**(Continuing previous query filters.)**")
    else:
        assumption = ("**(Önceki sorudaki kapsam:** " + "; ".join(note_parts) + ".)" if note_parts
                      else "**(Önceki sorgu filtreleri korunuyor.)**")
    return forced, assumption, None
