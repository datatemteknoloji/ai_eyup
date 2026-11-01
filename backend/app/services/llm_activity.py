"""LLM çağrı etkinlik kaydı — kuyruk (Ollama Parallel:1) teşhisi için.

Her gateway çağrısı (chat_sync / chat stream / generate / stream_generate) başlangıç-bitiş
zamanı, model ve ÇAĞIRAN modül ile kaydedilir. Çok süreç / konteyner (backend + worker)
için Redis'e (fail-open) yazılır. `overlapping()` bir isteğin süresiyle çakışan DİĞER
çağrıları döner; admin: GET /settings/llm-activity.
"""
from __future__ import annotations

import contextlib
import contextvars
import json
import logging
import os
import sys
import threading
import time
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)

_REDIS_LIST = "ainew:llm_activity"
_REDIS_SKIPPED = "ainew:llm_activity:skipped"   # HASH: "<kind>:<neden>" → sayaç (24 sa)
_REDIS_TTL = 3600
_MAX = 500
_lock = threading.Lock()
_recent: List[Dict[str, Any]] = []
_inflight: Dict[int, Dict[str, Any]] = {}
_seq = 0

# Çağrı sınıfları (dinamik timeout, sağlık uyarıları): llm_timeouts ile aynı adlar.
CLASS_ROUTE_HINT = "route_hint"
CLASS_TOOL_TURN = "tool_turn"
CLASS_FINAL = "final_answer"
CLASS_BACKGROUND = "background"

# Etkin kayıt (aynı thread/bağlam): llm_usage.record(data) sağlayıcı yanıtındaki token sayılarını buraya işler.
_cur_rec: "contextvars.ContextVar[Optional[Dict[str, Any]]]" = contextvars.ContextVar(
    "ainew_llm_activity_rec", default=None
)

_SKIP_PREFIXES = (
    "app.services.llm_gateway", "app.services.llm_activity", "app.services.llm_usage",
    "app.services.agent.llm", "contextlib", "asyncio", "threading", "concurrent",
    "httpx", "requests", "anyio", "starlette",
)


def _caller_module() -> str:
    try:
        f = sys._getframe(2)
        depth = 0
        while f is not None and depth < 25:
            name = f.f_globals.get("__name__", "")
            if name and not name.startswith(_SKIP_PREFIXES):
                return f"{name}.{f.f_code.co_name}"
            f = f.f_back
            depth += 1
    except Exception:
        pass
    return "unknown"


def _redis():
    try:
        from app.core.redis_client import get_redis
        return get_redis()
    except Exception:
        return None


def classify(kind: str, label: str = "") -> str:
    """Kayıt → çağrı sınıfı. route_hint: etiketli isteğe bağlı çağrı; araç turu: `chat_sync`;
    cevap üretimi: akışlar; geri kalan generate_sync/diğer: background."""
    if label == "route_hint":
        return CLASS_ROUTE_HINT
    if kind in ("chat_sync",):
        return CLASS_TOOL_TURN
    if kind in ("stream_generate", "chat_stream", "generate_async"):
        return CLASS_FINAL
    return CLASS_BACKGROUND


# `create_turn` içindeki plan_sources (routing ipucu dahil) tur izi BAĞLANMADAN önce çalışır; tur kimliği
# ContextVar ile verilir ki ipucu çağrıları/kayıtları soruya bağlanabilsin (Adım 3 / Parça 2C).
_forced_trace: "contextvars.ContextVar[Optional[str]]" = contextvars.ContextVar(
    "ainew_llm_activity_trace", default=None
)


@contextlib.contextmanager
def trace_scope(trace_id: Optional[str]) -> Iterator[None]:
    """with llm_activity.trace_scope(turn_id): ... — içindeki LLM kayıtlarına `trace_id` yazılır."""
    tok = _forced_trace.set(str(trace_id) if trace_id else None)
    try:
        yield
    finally:
        try:
            _forced_trace.reset(tok)
        except Exception:
            _forced_trace.set(None)


def _current_trace_id() -> Optional[str]:
    """Aktif sohbet turu kimliği: açık `trace_scope` → chat_quality izi → None."""
    forced = _forced_trace.get()
    if forced:
        return forced
    try:
        from app.services.chat_quality import trace as _cq
        cur = _cq.current()
        tid = getattr(cur, "turn_id", None) if cur is not None else None
        return str(tid) if tid else None
    except Exception:
        return None


@contextlib.contextmanager
def track(
    kind: str, model: str, *, label: str = "", lease: Any = None, timeout: Optional[float] = None,
) -> Iterator[Dict[str, Any]]:
    """with llm_activity.track('chat_sync', model): ... — çağrıyı kaydeder.

    ``duration_ms`` slot ALINDIKTAN sonra ölçülür (scheduler kuyruk beklemesi hariç: `sched_wait_ms` ayrı).
    ``timeout``: çağrının etkin okuma zaman aşımı (sn) → `timeout_s` / `hit_timeout` (sınıra dayandı mı).
    """
    global _seq
    rec: Dict[str, Any] = {
        "kind": kind, "model": model, "label": label,
        "caller": _caller_module(), "start": time.time(),
        "request_id": None, "module": None,
        "tclass": classify(kind, label), "trace_id": _current_trace_id(),
    }
    if os.environ.get("PYTEST_CURRENT_TEST"):
        rec["test"] = True      # test çağrıları istatistik/dinamik timeout hesabına girmez
    if timeout is not None:
        try:
            rec["timeout_s"] = round(float(timeout), 2)
        except (TypeError, ValueError):
            pass
    if lease is not None:
        rec["priority"] = getattr(lease, "priority", None)
        rec["sched_wait_ms"] = round(float(getattr(lease, "wait_ms", 0.0) or 0.0), 1)
    try:
        from app.services import chat_request_metrics as crm
        cur = crm.current()
        if cur is not None:
            rec["request_id"] = cur.request_id
            rec["module"] = cur.module
    except Exception:
        pass
    with _lock:
        _seq += 1
        key = _seq
        _inflight[key] = rec
    _tok = _cur_rec.set(rec)
    try:
        yield rec
    finally:
        try:
            _cur_rec.reset(_tok)
        except Exception:
            pass
        rec["end"] = time.time()
        rec["duration_ms"] = round((rec["end"] - rec["start"]) * 1000, 1)
        t_s = rec.get("timeout_s")
        if t_s:
            # Okuma zaman aşımına dayandı mı (istemci tarafı kesti): süre ≥ %98 sınır ve yanıt (token) gelmedi
            rec["hit_timeout"] = bool(
                rec["duration_ms"] >= float(t_s) * 1000 * 0.98 and not rec.get("completion_tokens")
            )
        with _lock:
            _inflight.pop(key, None)
            _recent.append(rec)
            if len(_recent) > _MAX:
                del _recent[: len(_recent) - _MAX]
        _push_redis(rec)


def _push_redis(rec: Dict[str, Any]) -> None:
    r = _redis()
    if r is not None:
        try:
            r.lpush(_REDIS_LIST, json.dumps(rec, ensure_ascii=False, default=str))
            r.ltrim(_REDIS_LIST, 0, _MAX - 1)
            r.expire(_REDIS_LIST, _REDIS_TTL)
        except Exception as exc:
            logger.debug("llm_activity redis: %s", exc)


def note_result(data: Any, usage: Optional[Dict[str, int]] = None) -> None:
    """Sağlayıcı yanıtından (Ollama done chunk / OpenAI usage) token ve `done_reason` bilgisini etkin kayda ekler.

    Tahmin üretmez; alan yoksa kayıt değişmez. `llm_usage.record` çağırır (tüm gateway yolları).
    """
    rec = _cur_rec.get()
    if rec is None or not isinstance(data, dict):
        return
    try:
        if usage:
            if usage.get("completion_tokens"):
                rec["completion_tokens"] = max(int(rec.get("completion_tokens") or 0), int(usage["completion_tokens"]))
            if usage.get("prompt_tokens"):
                rec["prompt_tokens"] = max(int(rec.get("prompt_tokens") or 0), int(usage["prompt_tokens"]))
        dr = data.get("done_reason")
        if not dr:
            ch = (data.get("choices") or [{}])[0] if isinstance(data.get("choices"), list) and data.get("choices") else {}
            dr = (ch or {}).get("finish_reason")
        if isinstance(dr, str) and dr:
            rec["done_reason"] = dr
        ed = data.get("eval_duration")
        if isinstance(ed, (int, float)) and ed > 0:
            rec["eval_ms"] = round(float(ed) / 1e6, 1)
    except Exception:
        pass


_skipped_local: Dict[str, int] = {}


def note_skipped(kind: str, reason: str, *, label: str = "") -> None:
    """İsteğe bağlı bir LLM çağrısı atlandı (ör. slot meşgul → route-hint). Sayaç + `recent()` kaydı."""
    key = f"{label or kind}:{reason}"
    now = time.time()
    rec: Dict[str, Any] = {
        "kind": kind, "model": "", "label": label, "caller": _caller_module(),
        "start": now, "end": now, "duration_ms": 0.0, "request_id": None, "module": None,
        "skipped": reason, "tclass": classify(kind, label), "trace_id": _current_trace_id(),
    }
    if os.environ.get("PYTEST_CURRENT_TEST"):
        rec["test"] = True
    with _lock:
        _skipped_local[key] = _skipped_local.get(key, 0) + 1
        _recent.append(rec)
        if len(_recent) > _MAX:
            del _recent[: len(_recent) - _MAX]
    _push_redis(rec)    # pencere bazlı sağlık uyarısı (tüm worker'lar) için
    r = _redis()
    if r is not None:
        try:
            r.hincrby(_REDIS_SKIPPED, key, 1)
            r.expire(_REDIS_SKIPPED, 86400)
        except Exception as exc:
            logger.debug("llm_activity skipped redis: %s", exc)


def skipped_counts() -> Dict[str, int]:
    """Atlanan isteğe bağlı çağrı sayıları ("<etiket>:<neden>" → adet). Redis varsa tüm süreçler toplamı."""
    r = _redis()
    if r is not None:
        try:
            raw = r.hgetall(_REDIS_SKIPPED) or {}
            out = {}
            for k, v in raw.items():
                kk = k.decode() if isinstance(k, bytes) else str(k)
                out[kk] = int(v)
            return out
        except Exception:
            pass
    with _lock:
        return dict(_skipped_local)


def recent(limit: int = 100, since: Optional[float] = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    r = _redis()
    if r is not None:
        try:
            for blob in r.lrange(_REDIS_LIST, 0, _MAX - 1) or []:
                try:
                    x = json.loads(blob)
                except Exception:
                    continue
                k = (x.get("start"), x.get("caller"), x.get("kind"))
                if k in seen:
                    continue
                seen.add(k)
                out.append(x)
        except Exception:
            pass
    with _lock:
        for x in list(_recent) + list(_inflight.values()):
            k = (x.get("start"), x.get("caller"), x.get("kind"))
            if k in seen:
                continue
            seen.add(k)
            out.append(x)
    if since is not None:
        out = [x for x in out if (x.get("end") or time.time()) >= since]
    out.sort(key=lambda x: x.get("start") or 0, reverse=True)
    return out[: max(1, limit)]


def overlapping(t0: float, t1: float, *, exclude_request_id: Optional[str] = None) -> List[Dict[str, Any]]:
    """[t0, t1] ile çakışan, belirtilen isteğe AİT OLMAYAN LLM çağrıları (özet)."""
    res: List[Dict[str, Any]] = []
    for x in recent(limit=_MAX, since=t0):
        s = x.get("start") or 0
        e = x.get("end") or time.time()
        if s > t1 or e < t0:
            continue
        if exclude_request_id and x.get("request_id") == exclude_request_id:
            continue
        if x.get("skipped"):
            continue    # atlanan çağrı LLM'e hiç gitmedi
        ov = max(0.0, min(e, t1) - max(s, t0))
        res.append({
            "kind": x.get("kind"), "model": x.get("model"), "caller": x.get("caller"),
            "module": x.get("module"), "request_id": x.get("request_id"),
            "overlap_ms": round(ov * 1000, 1), "duration_ms": x.get("duration_ms"),
        })
    return res


# ── istatistik (dinamik timeout, sağlık uyarıları, debug_trace) ──────────────

def _is_test_rec(x: Dict[str, Any]) -> bool:
    return bool(x.get("test")) or "app.tests." in str(x.get("caller") or "")


def window_records(window_sec: float = 1800.0, *, limit: int = _MAX) -> List[Dict[str, Any]]:
    """Son `window_sec` içindeki (tamamlanmış ya da atlanmış) kayıtlar; test çağrıları hariç."""
    since = time.time() - float(window_sec)
    return [
        x for x in recent(limit=limit, since=since)
        if not _is_test_rec(x) and x.get("end") and (x.get("end") or 0) >= since
    ]


def _percentile(values: List[float], q: float) -> float:
    if not values:
        return 0.0
    v = sorted(values)
    i = min(len(v) - 1, max(0, int(round(q * (len(v) - 1)))))
    return float(v[i])


def class_samples(tclass: str, *, window_sec: float = 1800.0, last_n: int = 50) -> List[float]:
    """Sınıfın son N (ve pencere içi) çağrı süreleri (sn). `duration_ms` scheduler beklemesini İÇERMEZ."""
    rows = [
        x for x in window_records(window_sec)
        if x.get("tclass") == tclass and not x.get("skipped") and x.get("duration_ms") is not None
    ]
    rows.sort(key=lambda x: x.get("start") or 0, reverse=True)
    return [float(x["duration_ms"]) / 1000.0 for x in rows[: max(1, int(last_n))]]


def window_stats(window_sec: float = 1800.0) -> Dict[str, Any]:
    """Sağlık kartı / uyarılar için pencere özeti."""
    rows = window_records(window_sec)
    done = [x for x in rows if not x.get("skipped")]
    waits = [float(x.get("sched_wait_ms") or 0.0) for x in done if x.get("sched_wait_ms") is not None]
    by_class: Dict[str, Dict[str, Any]] = {}
    for x in done:
        c = by_class.setdefault(str(x.get("tclass") or CLASS_BACKGROUND), {"calls": 0, "hit_timeout": 0, "_d": []})
        c["calls"] += 1
        c["hit_timeout"] += 1 if x.get("hit_timeout") else 0
        c["_d"].append(float(x.get("duration_ms") or 0.0) / 1000.0)
    for c in by_class.values():
        d = c.pop("_d")
        c["p50_s"] = round(_percentile(d, 0.5), 1)
        c["p95_s"] = round(_percentile(d, 0.95), 1)
    skipped: Dict[str, int] = {}
    for x in rows:
        if x.get("skipped"):
            k = f"{x.get('label') or x.get('kind')}:{x.get('skipped')}"
            skipped[k] = skipped.get(k, 0) + 1
    return {
        "window_sec": int(window_sec),
        "calls": len(done),
        "sched_wait_ms_avg": round(sum(waits) / len(waits), 1) if waits else 0.0,
        "sched_wait_ms_p95": round(_percentile(waits, 0.95), 1),
        "by_class": by_class,
        "skipped": skipped,
        "priority": {p: sum(1 for x in done if x.get("priority") == p) for p in ("chat", "background")},
    }


_HINT_NOTES_MAX = 256
_HINT_RAW_MAX = 300
_hint_notes: "Dict[str, List[Dict[str, Any]]]" = {}


def note_hint(
    source: str, *, raw: str = "", hinted: Optional[List[str]] = None,
    kw_modules: Optional[List[str]] = None, kw_reason: str = "", kw_confidence: Optional[float] = None,
    merged_modules: Optional[List[str]] = None, merged_reason: str = "",
    trace_id: Optional[str] = None,
) -> None:
    """Routing ipucunun sonucunu tura bağlı kaydeder (admin `debug_trace.llm.route_hint`).

    source: llm | cache | skipped | error | empty. `raw` ≤300 karakter ve maskelenmiş yazılır.
    İz kimliği yoksa (turdan bağımsız çağrı) kayıt tutulmaz. Hata sohbeti etkilemez.
    """
    try:
        tid = trace_id or _current_trace_id()
        if not tid:
            return
        text = (raw or "").strip()
        if text:
            try:
                from app.services.chat_quality.masking import mask_text
                text = mask_text(text)
            except Exception:
                pass
        entry = {
            "source": source,
            "raw": text[:_HINT_RAW_MAX],
            "hinted": list(hinted or []),
            "kw_modules": list(kw_modules or []),
            "kw_reason": kw_reason,
            "kw_confidence": kw_confidence,
            "merged_modules": list(merged_modules or []),
            "merged_reason": merged_reason,
        }
        with _lock:
            lst = _hint_notes.setdefault(str(tid), [])
            if len(lst) < 5:
                lst.append(entry)
            while len(_hint_notes) > _HINT_NOTES_MAX:
                _hint_notes.pop(next(iter(_hint_notes)))
    except Exception:
        logger.debug("llm_activity note_hint hata", exc_info=True)


def note_hint_merge(merged_modules: List[str], merged_reason: str, changed: bool) -> None:
    """Son ipucu kaydına birleşme sonucunu ekler (plan değişti mi, hangi modüller)."""
    try:
        tid = _current_trace_id()
        if not tid:
            return
        with _lock:
            lst = _hint_notes.get(str(tid))
            if lst:
                lst[-1]["merged_modules"] = list(merged_modules)
                lst[-1]["merged_reason"] = merged_reason
                lst[-1]["plan_changed"] = bool(changed)
    except Exception:
        logger.debug("llm_activity note_hint_merge hata", exc_info=True)


def hint_notes_for(trace_id: Optional[str]) -> List[Dict[str, Any]]:
    if not trace_id:
        return []
    with _lock:
        return [dict(x) for x in _hint_notes.get(str(trace_id), [])]


def summary_for_trace(trace_id: Optional[str]) -> Optional[Dict[str, Any]]:
    """Bir sohbet turuna ait LLM çağrılarının özeti (admin `debug_trace`). Kayıt yoksa None."""
    if not trace_id:
        return None
    with _lock:
        rows = [x for x in list(_recent) if x.get("trace_id") == trace_id]
    notes = hint_notes_for(trace_id)
    if not rows and not notes:
        return None
    done = [x for x in rows if not x.get("skipped")]
    out: Dict[str, Any] = {
        "calls": len(done),
        "sched_wait_ms_total": round(sum(float(x.get("sched_wait_ms") or 0.0) for x in done), 1),
        "sched_wait_ms_max": round(max([float(x.get("sched_wait_ms") or 0.0) for x in done] or [0.0]), 1),
        "skipped": sum(1 for x in rows if x.get("skipped")),
        "hit_timeout": sum(1 for x in done if x.get("hit_timeout")),
        "priorities": sorted({str(x.get("priority")) for x in done if x.get("priority")}),
        "calls_detail": [
            {
                "class": x.get("tclass"), "kind": x.get("kind"),
                "duration_ms": x.get("duration_ms"), "sched_wait_ms": x.get("sched_wait_ms"),
                "timeout_s": x.get("timeout_s"), "hit_timeout": bool(x.get("hit_timeout")),
                "completion_tokens": x.get("completion_tokens"), "done_reason": x.get("done_reason"),
                "skipped": x.get("skipped"),
            }
            for x in rows[:20]
        ],
    }
    if notes:
        out["route_hint"] = notes
    return out
