"""Sayım kuralı takip bağlamı (Adım 6d).

Sayım kuralı cevapladığında çözülmüş soru(lar) `meta.count_context` olarak asistan mesajına yazılır
(uç nokta `pop_context()` ile alır). Sonraki turda takip sorusu:
- zamir + durum («Bunların kaçı kapalı?», «kaç tanesi hatalı?») → önceki sorunun «kaç»ına durum eklenir;
- kapsam değişimi («Peki Datatem OLVM'de?», «ya oVirt'te?») → yeni kapsam + önceki sayım çekirdeği.
Bağlam yalnız aynı oturumun son `MAX_TURNS` asistan mesajından alınır; yeni mesajın kendi konusu/kapsamı
varsa (doğrudan sayım kuralına uyuyorsa) devralma yapılmaz. Birden çok aday kalırsa netleştirme sorulur.
"""
from __future__ import annotations

import contextvars
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.services.chat_quality.claims import fold
from app.services.chat_quality.compound import _PRONOUN_RE, resolve_pronoun

MAX_TURNS = 3

_CTX: contextvars.ContextVar[Optional[Dict[str, Any]]] = contextvars.ContextVar("count_followup_ctx", default=None)

_NOUN = {"vm": "VM", "host": "host", "datastore": "datastore", "node": "node", "project": "proje",
         "hypervisor": "hypervisor", "pod": "pod"}
_STATE = {"on": "açık", "off": "kapalı", "suspended": "askıda"}
_POD_STATUS = {"running": "çalışan", "pending": "bekleyen", "succeeded": "tamamlanmış"}

_SWITCH_RE = re.compile(r"^\s*(?:peki|ya|ayni\s+sey|ayni\s+soru|what about|and)\s+(.+?)\s*\??\s*$")
_SWITCH_TAIL = re.compile(r"(?:\s+(?:icin|için|ne\s+durumda|nasil|nasıl))?\s*\??\s*$", re.IGNORECASE)
_BUNLAR_RE = re.compile(r"\b(?:bunlar\w*|onlar\w*|bunun|bunlardan|of them|of those)\b")


def core_for(plan) -> Optional[str]:
    """Plan → kapsamsız sayım çekirdeği («kaç kapalı VM»)."""
    t = plan.topic
    if t == "pod":
        f = plan.pod_filter or "all"
        if f == "faulty":
            return "kaç hatalı pod"
        if f.startswith("reason:"):
            return f"kaç {f.split(':', 1)[1]} pod"
        if f.startswith("status:"):
            return f"kaç {_POD_STATUS.get(f.split(':', 1)[1], '')} pod".replace("  ", " ")
        return "kaç pod"
    if t == "server":
        return "kaç sunucu"            # işletim sistemi kapsam sayılır: «Peki Windows?» onu değiştirir
    if t == "cluster":
        return "kaç OpenShift cluster" if plan.domain == "ocp" else "kaç cluster"
    if t in _NOUN:
        st = _STATE.get(plan.state, "")
        return f"kaç {st + ' ' if st else ''}{_NOUN[t]}"
    return None


def context_for(questions: List[str], plans: List[Any]) -> Dict[str, Any]:
    return {"v": 1, "items": [{"q": q, "topic": p.topic, "core": core_for(p)} for q, p in zip(questions, plans) if p]}


def set_context(ctx: Optional[Dict[str, Any]]) -> None:
    _CTX.set(ctx)


def pop_context() -> Optional[Dict[str, Any]]:
    ctx = _CTX.get()
    _CTX.set(None)
    return ctx


def load_recent(db, session_id: Optional[int], *, max_turns: int = MAX_TURNS) -> Optional[Dict[str, Any]]:
    """Oturumun son `max_turns` asistan mesajı içindeki en yeni `count_context`."""
    if not session_id:
        return None
    from app.models.chat_session import ChatMessage
    rows = (db.query(ChatMessage.meta).filter(ChatMessage.session_id == int(session_id), ChatMessage.role == "assistant")
            .order_by(ChatMessage.id.desc()).limit(max_turns).all())
    for (meta,) in rows:
        if isinstance(meta, dict) and isinstance(meta.get("count_context"), dict):
            return meta["count_context"]
    return None


def is_followup_shape(message: str) -> bool:
    mf = fold(message or "")
    if len(mf) > 120:
        return False
    return bool(_PRONOUN_RE.search(mf) or _SWITCH_RE.match(mf))


def resolve(message: str, ctx: Optional[Dict[str, Any]], analyze: Callable[[str], Any]) -> Optional[Tuple[str, str]]:
    """→ ("rewrite", yeni_soru) | ("clarify", metin) | None. `analyze(q)` Plan veya None döner."""
    items = (ctx or {}).get("items") or []
    if not items or not is_followup_shape(message):
        return None
    mf = fold(message)
    cands: List[str] = []
    if _PRONOUN_RE.search(mf):
        for it in items:
            q = resolve_pronoun(message, it.get("q"))
            if q and analyze(q) is not None:
                cands.append(q)
    else:
        m = _SWITCH_RE.match(mf)
        raw = re.sub(r"^\s*(?:peki|ya|aynı\s+şey|ayni\s+sey|aynı\s+soru|ayni\s+soru|what about|and)\s+", "",
                     message.strip(), flags=re.IGNORECASE)
        raw = _SWITCH_TAIL.sub("", raw).strip()
        if m and raw:
            for it in items:
                core = it.get("core")
                if not core:
                    continue
                q = f"{raw} {core} var?"
                if analyze(q) is not None:
                    cands.append(q)
    cands = list(dict.fromkeys(cands))
    if len(cands) == 1:
        return ("rewrite", cands[0])
    if len(cands) > 1:
        opts = "\n".join(f"- «{c}»" for c in cands)
        return ("clarify", "Önceki cevapta birden fazla sayım vardı; hangisini kastettiniz?\n\n" + opts)
    return None
