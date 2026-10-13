"""Sohbet isteği performans ölçümü — log + admin ring buffer.

Optimizasyon yapmaz; gateway/tool/RAG yollarına ölçüm kancaları ekler.
"""
from __future__ import annotations

import contextvars
import logging
import threading
import re
import time
import uuid
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import Any, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)

_MAX_STORED = 200
_REDIS_LIST = "ainew:chat_request_metrics"
_REDIS_ITEM = "ainew:chat_request_metrics:item:"
_REDIS_TTL_SEC = 86400
_lock = threading.Lock()
_store: Deque[Dict[str, Any]] = deque(maxlen=_MAX_STORED)
_current: contextvars.ContextVar[Optional["ChatRequestMetrics"]] = contextvars.ContextVar(
    "ainew_chat_request_metrics", default=None,
)


def _redis_publish(payload: Dict[str, Any]) -> None:
    """Çok worker: ring buffer Redis'te (fail-open)."""
    try:
        import json
        from app.core.redis_client import get_redis
        r = get_redis()
        if r is None:
            return
        rid = payload.get("request_id") or ""
        blob = json.dumps(payload, ensure_ascii=False, default=str)
        if rid:
            r.setex(f"{_REDIS_ITEM}{rid}", _REDIS_TTL_SEC, blob)
        r.lpush(_REDIS_LIST, blob)
        r.ltrim(_REDIS_LIST, 0, _MAX_STORED - 1)
        r.expire(_REDIS_LIST, _REDIS_TTL_SEC)
    except Exception as exc:
        logger.debug("chat_perf redis publish: %s", exc)


def _estimate_tokens(text: str) -> int:
    try:
        from app.services.llm_context_budget import estimate_tokens
        return int(estimate_tokens(text or ""))
    except Exception:
        return max(1, (len(text or "") + 2) // 3)


@dataclass
class LlmTurnMetrics:
    purpose: str  # tool_selection | final_answer
    prompt_eval_count: int = 0
    prompt_eval_duration_ns: int = 0
    eval_count: int = 0
    eval_duration_ns: int = 0
    load_duration_ns: int = 0
    total_duration_ns: int = 0
    thinking_chars: int = 0
    thinking_tokens_est: int = 0
    first_token_ms: Optional[float] = None
    empty_turn: bool = False
    tool_parse_error: bool = False
    content_chars: int = 0
    content_head: str = ""      # görünür içeriğin ilk ~160 karakteri (sızıntı teşhisi)
    leak_suspect: bool = False   # içerik başında düşünce benzeri metin (İngilizce monolog) var mı
    token_sections: Dict[str, int] = field(default_factory=dict)
    wall_ms: float = 0.0
    # Adım 6b
    think: Optional[str] = None
    num_predict: Optional[int] = None
    done_reason: Optional[str] = None
    streamed: bool = False
    queue_ms: float = 0.0  # LLM çağrı süresi − Ollama total_duration (kuyruk/ağ/bekleme; sched_wait DAHİL)
    sched_wait_ms: float = 0.0   # ainew semafor kuyruğunda bekleme (llm_scheduler) — queue_ms'in alt kümesi
    sched_priority: str = ""     # chat | background
    start_offset_ms: float = 0.0
    ctx_ratio_est: Optional[float] = None
    empty_reason: Optional[str] = None
    retry_note: Optional[str] = None
    prefix_hash: Optional[str] = None   # sistem mesajının sabit kısmı (çalışma zamanı bağlamından önce)
    tools_hash: Optional[str] = None    # araç tanımları JSON
    prefix_chars: int = 0
    temperature: Optional[float] = None   # bu turda Ollama'ya giden temperature (Adım 7)


@dataclass
class ToolCallMetrics:
    name: str
    duration_ms: float
    rows: int = 0
    chars: int = 0
    triggered_by: str = "llm"  # llm | fallback_plan


@dataclass
class ChatRequestMetrics:
    request_id: str
    module: str
    message: str
    intent: Optional[str] = None
    started_at: float = field(default_factory=time.time)
    total_ms: float = 0.0
    rag_ms: float = 0.0
    rag_collection: Optional[str] = None
    llm_turns: List[LlmTurnMetrics] = field(default_factory=list)
    tools: List[ToolCallMetrics] = field(default_factory=list)
    request_params: Dict[str, Any] = field(default_factory=dict)
    prompt_variable_fields: List[Dict[str, str]] = field(default_factory=list)
    notes: List[str] = field(default_factory=list)
    first_visible_token_ms: Optional[float] = None
    final_turn_reason: Optional[str] = None
    leak_dropped_chars: int = 0     # yanıt başında filtrelenen sızan düşünce metni (karakter)
    leak_text_head: str = ""
    validator_interventions: List[Dict[str, Any]] = field(default_factory=list)  # Adım 7h
    phase_ms: Dict[str, float] = field(default_factory=dict)  # LLM öncesi/sonrası aşamalar
    tool_llm_payloads: List[Dict[str, Any]] = field(default_factory=list)
    queue_ms_total: float = 0.0
    sched_wait_ms_total: float = 0.0   # ainew semafor beklemesi (kullanıcı sohbeti ↔ arka plan sıralaması)
    ollama_queue_ms_total: float = 0.0  # queue_ms_total − sched_wait (Ollama tarafı kuyruk/ağ)
    unaccounted_ms: float = 0.0
    concurrent_llm: List[Dict[str, Any]] = field(default_factory=list)
    _tok: Any = field(default=None, repr=False)
    _turn_t0: float = field(default=0.0, repr=False)
    _first_token_t0: Optional[float] = field(default=None, repr=False)

    def to_dict(self) -> Dict[str, Any]:
        # contextvars.Token pickle edilemez — asdict kullanma
        turns = []
        for t in self.llm_turns:
            td = asdict(t)
            for k in (
                "prompt_eval_duration_ns", "eval_duration_ns",
                "load_duration_ns", "total_duration_ns",
            ):
                ns = int(td.get(k) or 0)
                td[k.replace("_ns", "_ms")] = round(ns / 1e6, 2) if ns else 0.0
            turns.append(td)
        return {
            "request_id": self.request_id,
            "module": self.module,
            "message": self.message,
            "intent": self.intent,
            "started_at": self.started_at,
            "total_ms": self.total_ms,
            "rag_ms": self.rag_ms,
            "rag_collection": self.rag_collection,
            "llm_turns": turns,
            "tools": [asdict(t) for t in self.tools],
            "request_params": dict(self.request_params or {}),
            "prompt_variable_fields": list(self.prompt_variable_fields or []),
            "notes": list(self.notes or []),
            "first_visible_token_ms": self.first_visible_token_ms,
            "final_turn_reason": self.final_turn_reason,
            "phase_ms": dict(self.phase_ms or {}),
            "leak_dropped_chars": self.leak_dropped_chars,
            "leak_text_head": self.leak_text_head,
            "validator_interventions": list(self.validator_interventions or []),
            "tool_llm_payloads": list(self.tool_llm_payloads or []),
            "queue_ms_total": self.queue_ms_total,
            "sched_wait_ms_total": self.sched_wait_ms_total,
            "ollama_queue_ms_total": self.ollama_queue_ms_total,
            "unaccounted_ms": self.unaccounted_ms,
            "concurrent_llm": list(self.concurrent_llm or []),
        }


def _finalize_timing(m: ChatRequestMetrics) -> None:
    """Kuyruk / açıklanamayan süre + aynı aralıktaki diğer LLM çağrıları."""
    accounted = 0.0
    queue = 0.0
    sched = 0.0
    for t in m.llm_turns:
        accounted += (t.prompt_eval_duration_ns + t.eval_duration_ns + t.load_duration_ns) / 1e6
        queue += t.queue_ms
        sched += t.sched_wait_ms
    accounted += sum(x.duration_ms for x in m.tools) + (m.rag_ms or 0.0)
    m.queue_ms_total = round(queue, 1)
    m.sched_wait_ms_total = round(sched, 1)
    m.ollama_queue_ms_total = round(max(0.0, queue - sched), 1)
    m.unaccounted_ms = round(max(0.0, m.total_ms - accounted), 1)
    try:
        from app.services import llm_activity
        m.concurrent_llm = llm_activity.overlapping(
            m.started_at, time.time(), exclude_request_id=m.request_id)
    except Exception:
        pass


def start(module: str, message: str) -> ChatRequestMetrics:
    m = ChatRequestMetrics(
        request_id=uuid.uuid4().hex[:16],
        module=(module or "").strip() or "unknown",
        message=(message or "")[:500],
    )
    m._tok = _current.set(m)
    return m


def current() -> Optional[ChatRequestMetrics]:
    return _current.get()


def finish(m: Optional[ChatRequestMetrics] = None) -> Optional[Dict[str, Any]]:
    m = m or _current.get()
    if m is None:
        return None
    m.total_ms = round((time.time() - m.started_at) * 1000, 1)
    try:
        _finalize_timing(m)
    except Exception as exc:
        logger.debug("chat_perf timing finalize: %s", exc)
    payload = m.to_dict()
    with _lock:
        _store.appendleft(payload)
    _redis_publish(payload)
    logger.info(
        "chat_perf module=%s intent=%s total_ms=%.1f llm_turns=%s empty=%s tools=%s "
        "rag_ms=%.1f req=%s",
        m.module, m.intent, m.total_ms, len(m.llm_turns),
        sum(1 for t in m.llm_turns if t.empty_turn),
        len(m.tools), m.rag_ms, m.request_id,
    )
    try:
        if m._tok is not None:
            _current.reset(m._tok)
    except Exception:
        pass
    return payload


def set_intent(intent: str) -> None:
    m = _current.get()
    if m:
        m.intent = intent


def set_request_params(params: Dict[str, Any]) -> None:
    m = _current.get()
    if m:
        m.request_params = dict(params or {})


def set_prompt_variable_fields(fields: List[Dict[str, str]]) -> None:
    m = _current.get()
    if m:
        m.prompt_variable_fields = list(fields or [])


def record_rag(collection: str, duration_ms: float) -> None:
    m = _current.get()
    if not m:
        return
    m.rag_collection = collection
    m.rag_ms = round(float(duration_ms or 0), 2)


def begin_llm_turn(
    purpose: str, *, think: Optional[str] = None, num_predict: Optional[int] = None,
    streamed: bool = False,
) -> None:
    m = _current.get()
    if not m:
        return
    m._turn_t0 = time.perf_counter()
    m._first_token_t0 = None
    try:
        from app.services.agent.llm import _temp as _turn_temp
        _t = _turn_temp()
    except Exception:
        _t = None
    m.llm_turns.append(LlmTurnMetrics(
        purpose=purpose, think=think, num_predict=num_predict, streamed=streamed, temperature=_t,
        start_offset_ms=round((time.time() - m.started_at) * 1000, 1),
    ))


def set_turn_temperature(value: Optional[float]) -> None:
    """Son LLM turunun gerçekten gönderilen temperature'ı (açık parametreyle çağıran yollar için)."""
    m = _current.get()
    if m and m.llm_turns and value is not None:
        m.llm_turns[-1].temperature = float(value)


def set_turn_retry_note(note: str) -> None:
    m = _current.get()
    if m and m.llm_turns:
        m.llm_turns[-1].retry_note = note[:200]


def set_turn_prefix_fingerprint(prefix_hash: str, tools_hash: str, prefix_chars: int) -> None:
    m = _current.get()
    if m and m.llm_turns:
        t = m.llm_turns[-1]
        t.prefix_hash, t.tools_hash, t.prefix_chars = prefix_hash, tools_hash, int(prefix_chars)


def set_turn_ctx_ratio(ratio: float) -> None:
    m = _current.get()
    if m and m.llm_turns:
        m.llm_turns[-1].ctx_ratio_est = round(float(ratio), 3)


def note_visible_token() -> None:
    """İstek başından ilk KULLANICIYA görünür token'a kadar süre (bir kez)."""
    m = _current.get()
    if m and m.first_visible_token_ms is None:
        m.first_visible_token_ms = round((time.time() - m.started_at) * 1000, 1)


def note_leak(dropped_chars: int, head: str = "") -> None:
    m = _current.get()
    if m:
        m.leak_dropped_chars = int(dropped_chars or 0)
        m.leak_text_head = (head or "")[:160]


def note_validator(interventions: Optional[List[Dict[str, Any]]] = None) -> None:
    """Çalışma zamanı cevap doğrulayıcısı müdahaleleri (Adım 7h)."""
    m = _current.get()
    if m and interventions:
        m.validator_interventions.extend(list(interventions)[:40])


def note_phase(name: str) -> None:
    """İstek başından bu ana kadar geçen süreyi (ms, kümülatif) aşama adıyla kaydeder."""
    m = _current.get()
    if m:
        m.phase_ms[name] = round((time.time() - m.started_at) * 1000, 1)


def set_final_turn_reason(reason: str) -> None:
    m = _current.get()
    if m:
        m.final_turn_reason = reason[:300]


def record_tool_llm_payload(name: str, *, raw_tokens: int, llm_tokens: int, rows_cap: int) -> None:
    m = _current.get()
    if m:
        m.tool_llm_payloads.append({
            "tool": name, "raw_tokens_est": int(raw_tokens),
            "llm_tokens_est": int(llm_tokens), "rows_cap": int(rows_cap),
        })


def note_first_token() -> None:
    m = _current.get()
    if not m or not m.llm_turns:
        return
    turn = m.llm_turns[-1]
    if turn.first_token_ms is not None:
        return
    if m._turn_t0:
        turn.first_token_ms = round((time.perf_counter() - m._turn_t0) * 1000, 2)


def record_ollama_stats(data: Any) -> None:
    """Ollama native done chunk / chat yanıtından süre ve token alanları."""
    m = _current.get()
    if not m or not isinstance(data, dict):
        return
    if not m.llm_turns:
        begin_llm_turn("unknown")
    turn = m.llm_turns[-1]

    def _i(key: str) -> int:
        try:
            return max(0, int(data.get(key) or 0))
        except (TypeError, ValueError):
            return 0

    turn.prompt_eval_count = _i("prompt_eval_count") or turn.prompt_eval_count
    turn.prompt_eval_duration_ns = _i("prompt_eval_duration") or turn.prompt_eval_duration_ns
    turn.eval_count = _i("eval_count") or turn.eval_count
    turn.eval_duration_ns = _i("eval_duration") or turn.eval_duration_ns
    turn.load_duration_ns = _i("load_duration") or turn.load_duration_ns
    turn.total_duration_ns = _i("total_duration") or turn.total_duration_ns
    dr = data.get("done_reason")
    if isinstance(dr, str) and dr:
        turn.done_reason = dr

    msg = data.get("message") if isinstance(data.get("message"), dict) else {}
    thinking = (
        data.get("thinking")
        or (msg or {}).get("thinking")
        or data.get("reasoning")
        or ""
    )
    if isinstance(thinking, str) and thinking:
        turn.thinking_chars = len(thinking)
        turn.thinking_tokens_est = _estimate_tokens(thinking)

    content = data.get("response") or (msg or {}).get("content") or ""
    if isinstance(content, str):
        turn.content_chars = max(turn.content_chars, len(content))
        _note_content_head(turn, content)

    if m._turn_t0:
        turn.wall_ms = round((time.perf_counter() - m._turn_t0) * 1000, 2)
        engine_ms = (
            turn.total_duration_ns
            or (turn.prompt_eval_duration_ns + turn.eval_duration_ns + turn.load_duration_ns)
        ) / 1e6
        turn.queue_ms = round(max(0.0, turn.wall_ms - engine_ms), 1)


_LEAK_HEAD_RE = re.compile(
    r"^\s*(We |We'|Need |Let's |Let me |The user|User |I need|I should|Okay,|So |First,|Provide |Actually|Now )")


def _note_content_head(turn, content: str) -> None:
    if content and not turn.content_head:
        turn.content_head = content[:160]
        turn.leak_suspect = bool(_LEAK_HEAD_RE.match(content))


def note_sched_wait(wait_ms: float, priority: str = "") -> None:
    """Semafor kuyruğunda beklenen süre (son LLM turuna işlenir; tur henüz yoksa atlanır)."""
    m = _current.get()
    if not m or not m.llm_turns:
        return
    t = m.llm_turns[-1]
    t.sched_wait_ms = round(t.sched_wait_ms + float(wait_ms or 0.0), 1)
    if priority:
        t.sched_priority = priority


def note_stream_text(*, thinking_chars: int = 0, content_chars: int = 0, content_head: str = "") -> None:
    """Stream turunda biriken reasoning/içerik uzunluğu (done chunk'ta metin yok)."""
    m = _current.get()
    if not m or not m.llm_turns:
        return
    turn = m.llm_turns[-1]
    if thinking_chars:
        turn.thinking_chars = int(thinking_chars)
        # ~3 karakter/token (İngilizce reasoning için kaba tahmin)
        turn.thinking_tokens_est = max(1, int(thinking_chars) // 3)
    if content_chars:
        turn.content_chars = max(turn.content_chars, int(content_chars))
    if content_head:
        _note_content_head(turn, content_head)


def mark_empty_turn(*, tool_parse_error: bool = False) -> None:
    m = _current.get()
    if not m or not m.llm_turns:
        return
    turn = m.llm_turns[-1]
    turn.empty_turn = True
    turn.tool_parse_error = bool(tool_parse_error)
    turn.empty_reason = (
        "tool_call_parse_error" if tool_parse_error
        else f"done_reason={turn.done_reason or '?'} eval={turn.eval_count} "
             f"thinking_tokens~{turn.thinking_tokens_est} content_chars={turn.content_chars}"
    )


def set_turn_token_sections(sections: Dict[str, int]) -> None:
    m = _current.get()
    if not m or not m.llm_turns:
        return
    m.llm_turns[-1].token_sections = {k: int(v) for k, v in (sections or {}).items()}


def record_tool(
    name: str,
    *,
    duration_ms: float,
    rows: int = 0,
    chars: int = 0,
    triggered_by: str = "llm",
) -> None:
    m = _current.get()
    if not m:
        return
    m.tools.append(ToolCallMetrics(
        name=name,
        duration_ms=round(float(duration_ms or 0), 2),
        rows=int(rows or 0),
        chars=int(chars or 0),
        triggered_by=triggered_by,
    ))


def estimate_section_tokens(
    *,
    system: str = "",
    rag: str = "",
    tools_results: str = "",
    history: str = "",
    tool_defs_json: str = "",
    user: str = "",
    budget_tokens: int = 32768,
) -> Dict[str, int]:
    sections = {
        "system": _estimate_tokens(system),
        "rag": _estimate_tokens(rag),
        "tool_results": _estimate_tokens(tools_results),
        "history": _estimate_tokens(history),
        "tool_definitions": _estimate_tokens(tool_defs_json),
        "user": _estimate_tokens(user),
    }
    used = sum(sections.values())
    sections["answer_reserve"] = max(0, int(budget_tokens) - used)
    return sections


def list_recent(*, module: Optional[str] = None, limit: int = 50) -> List[Dict[str, Any]]:
    lim = max(1, min(int(limit or 50), _MAX_STORED))
    items: List[Dict[str, Any]] = []
    seen = set()
    try:
        import json
        from app.core.redis_client import get_redis
        r = get_redis()
        if r is not None:
            for blob in r.lrange(_REDIS_LIST, 0, lim * 2) or []:
                try:
                    x = json.loads(blob)
                except Exception:
                    continue
                rid = x.get("request_id")
                if rid and rid in seen:
                    continue
                if rid:
                    seen.add(rid)
                items.append(x)
    except Exception as exc:
        logger.debug("chat_perf redis list: %s", exc)
    with _lock:
        for x in _store:
            rid = x.get("request_id")
            if rid and rid in seen:
                continue
            if rid:
                seen.add(rid)
            items.append(x)
    if module:
        items = [x for x in items if x.get("module") == module]
    return items[:lim]


def get_request(request_id: str) -> Optional[Dict[str, Any]]:
    rid = (request_id or "").strip()
    if not rid:
        return None
    with _lock:
        for x in _store:
            if x.get("request_id") == rid:
                return x
    try:
        import json
        from app.core.redis_client import get_redis
        r = get_redis()
        if r is not None:
            blob = r.get(f"{_REDIS_ITEM}{rid}")
            if blob:
                return json.loads(blob)
    except Exception as exc:
        logger.debug("chat_perf redis get: %s", exc)
    return None


def summarize_for_report(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Benchmark satırlarından özet istatistik."""
    if not rows:
        return {}
    totals = [float(r.get("total_ms") or 0) for r in rows]
    rag = [float(r.get("rag_ms") or 0) for r in rows]
    tool_ms = [
        sum(float(t.get("duration_ms") or 0) for t in (r.get("tools") or []))
        for r in rows
    ]
    prompt_ms = []
    eval_ms = []
    for r in rows:
        p = e = 0.0
        for t in r.get("llm_turns") or []:
            p += float(t.get("prompt_eval_duration_ms") or 0)
            e += float(t.get("eval_duration_ms") or 0)
        prompt_ms.append(p)
        eval_ms.append(e)
    return {
        "n": len(rows),
        "avg_total_ms": round(sum(totals) / len(totals), 1),
        "avg_rag_ms": round(sum(rag) / len(rag), 1),
        "avg_tool_ms": round(sum(tool_ms) / len(tool_ms), 1),
        "avg_prompt_eval_ms": round(sum(prompt_ms) / len(prompt_ms), 1),
        "avg_eval_ms": round(sum(eval_ms) / len(eval_ms), 1),
    }
