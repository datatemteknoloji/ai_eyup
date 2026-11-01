"""İç tur izi (TurnTrace) ve `debug_trace` / `now_override` sözleşmesi.

- İz HER turda (sohbet orkestratörü üzerinden) tutulur: araç adı/argüman/sonuç
  referansı, karar yolu notları, gözlenen olay türleri. Doğrulayıcı (sonraki adımlar)
  buradan okur.
- `debug_trace` olayı yalnız admin/superadmin + açık bayrakla kullanıcıya gider;
  araç sonuçları maskelenir ve boyut sınırlanır. Normal akış değişmez.
- Bağlı iz yoksa tüm yardımcılar no-op'tur (Automic gibi bu yoldan geçmeyenler etkilenmez).
"""
from __future__ import annotations

import contextvars
import json
import logging
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.services.chat_quality.masking import mask_obj, mask_text

logger = logging.getLogger(__name__)

ADMIN_ROLES = frozenset({"admin", "superadmin"})
# Sohbet yolundaki araçların hiçbiri eylem yapmaz; ileride eklenecek eylem araçları buraya yazılır.
MUTATING_TOOL_NAMES: frozenset = frozenset()
MAX_EVENT_BYTES = 256 * 1024
MAX_RESULT_CHARS = 20_000
MAX_TOOLS = 60
MAX_PATHS = 40
MAX_ANSWER_CHARS = 8_000

_CURRENT: contextvars.ContextVar[Optional["TurnTrace"]] = contextvars.ContextVar(
    "chat_quality_turn_trace", default=None
)


@dataclass
class ToolRecord:
    tool: str
    args: Any
    result: Any  # referans — kopyalanmaz
    ts: float = field(default_factory=time.time)
    source: str = "loop"


@dataclass
class TurnTrace:
    turn_id: str = ""
    platform: str = ""
    message: str = ""
    debug_enabled: bool = False
    username: str = ""
    user_id: Optional[int] = None
    now_override: Optional[datetime] = None
    started: float = field(default_factory=time.time)
    tools: List[ToolRecord] = field(default_factory=list)
    paths: List[Dict[str, Any]] = field(default_factory=list)
    event_types: Counter = field(default_factory=Counter)
    flags: Dict[str, Any] = field(default_factory=dict)
    ignored: List[str] = field(default_factory=list)
    guard: Optional[Dict[str, Any]] = None   # StreamGuard özeti (gecikme ölçümü, engelleme)
    grounding: Optional[Dict[str, Any]] = None   # Veriye dayalılık doğrulayıcısı sonucu (Adım 7b)

    # ── yazma ──────────────────────────────────────────────────────────
    def note_tool(self, tool: str, args: Any, result: Any, source: str = "loop") -> None:
        if len(self.tools) < MAX_TOOLS:
            self.tools.append(ToolRecord(str(tool), args, result, source=source))

    def note_path(self, kind: str, **detail: Any) -> None:
        if len(self.paths) < MAX_PATHS:
            self.paths.append({"kind": kind, **detail})

    def note_chunk(self, chunk: dict) -> None:
        """Orkestratörün gördüğü SSE parçasından hafif sinyal çıkarır (token hariç)."""
        if not isinstance(chunk, dict) or chunk.get("token"):
            return
        key = chunk.get("type") or chunk.get("phase")
        if key:
            self.event_types[str(key)] += 1
        for flag in ("from_cache", "needs_confirmation", "queued"):
            if chunk.get(flag):
                self.flags[flag] = True

    def _llm_summary(self) -> Optional[Dict[str, Any]]:
        """Bu turun LLM çağrı özeti (kuyruk beklemesi, atlanan ipucu, sınıra dayanan çağrı). Kayıt yoksa None."""
        try:
            from app.services import llm_activity
            return llm_activity.summary_for_trace(self.turn_id)
        except Exception:
            return None

    # ── okuma ──────────────────────────────────────────────────────────
    def tool_names(self) -> List[str]:
        return [t.tool for t in self.tools]

    def has_mutating_tool(self) -> bool:
        """Sohbet araçları salt-okunurdur; yine de ileride eklenirse burada işaretlenir."""
        return any(t.tool in MUTATING_TOOL_NAMES for t in self.tools)

    def to_debug_dict(self, answer: Optional[str] = None) -> Dict[str, Any]:
        """Maskeli, boyut sınırlı, JSON-uyumlu görünüm."""
        out = self._build(MAX_RESULT_CHARS, answer)
        if _size(out) > MAX_EVENT_BYTES:
            out = self._build(2_000, answer)
            out["truncated"] = True
        if _size(out) > MAX_EVENT_BYTES:
            for t in out["tools"]:
                t["result"] = {"_truncated": True, "chars": t.get("result_chars", 0)}
            out["truncated"] = True
        return out

    def _build(self, result_cap: int, answer: Optional[str]) -> Dict[str, Any]:
        tools = []
        for t in self.tools:
            masked = mask_obj(t.result)
            raw = _dumps(masked)
            if len(raw) > result_cap:
                res: Any = {"_truncated": True, "chars": len(raw), "head": raw[:result_cap]}
            else:
                res = masked
            tools.append({
                "tool": t.tool,
                "args": mask_obj(t.args),
                "result": res,
                "result_chars": len(raw),
                "source": t.source,
                "t_ms": int((t.ts - self.started) * 1000),
            })
        d: Dict[str, Any] = {
            "turn_id": self.turn_id,
            "platform": self.platform,
            "elapsed_ms": int((time.time() - self.started) * 1000),
            "paths": mask_obj(self.paths),
            "tools": tools,
            "event_types": dict(self.event_types),
            "flags": dict(self.flags),
            "now_override": self.now_override.isoformat() if self.now_override else None,
            "truncated": False,
            "guard": self.guard,
            "grounding": self.grounding,
        }
        if self.ignored:
            d["ignored"] = list(self.ignored)
        llm = self._llm_summary()
        if llm:
            d["llm"] = llm
        if answer is not None:
            d["answer_chars"] = len(answer)
            d["answer"] = mask_text(answer)[:MAX_ANSWER_CHARS]
        return d


class TracedResults(list):
    """`structured_results` yerine kullanılır: append aynı zamanda ize yazar."""

    def append(self, item: Any) -> None:  # type: ignore[override]
        super().append(item)
        try:
            if isinstance(item, dict) and "tool" in item:
                note_tool(item.get("tool"), item.get("args"), item.get("result"))
        except Exception:  # iz hiçbir zaman sohbeti düşürmemeli
            logger.debug("trace tool note failed", exc_info=True)


# ── bağlama / modül düzeyi yardımcılar (hepsi no-op güvenli) ───────────────────

def bind(trace: TurnTrace) -> contextvars.Token:
    return _CURRENT.set(trace)


def unbind(token: contextvars.Token) -> None:
    try:
        _CURRENT.reset(token)
    except Exception:
        _CURRENT.set(None)


def current() -> Optional[TurnTrace]:
    return _CURRENT.get()


def run_in_trace(tr: Optional[TurnTrace], fn, *args: Any):
    """`loop.run_in_executor` ContextVar kopyalamaz; bu sarmalayıcı yalnız tur izini iş parçacığına bağlar.

    Kullanım: `await loop.run_in_executor(None, run_in_trace, current(), fn, *args)`.
    Diğer ContextVar'lara (ör. iptal) dokunmaz → mevcut davranış değişmez.
    """
    if tr is None:
        return fn(*args)
    tok = _CURRENT.set(tr)
    try:
        return fn(*args)
    finally:
        try:
            _CURRENT.reset(tok)
        except Exception:
            _CURRENT.set(None)


def note_tool(tool: Any, args: Any, result: Any, source: str = "loop") -> None:
    t = _CURRENT.get()
    if t is not None:
        t.note_tool(str(tool), args, result, source=source)


def note_path(kind: str, **detail: Any) -> None:
    t = _CURRENT.get()
    if t is not None:
        t.note_path(kind, **detail)


# ── bayraklar ───────────────────────────────────────────────────────────

def parse_now_override(raw: Any) -> Optional[datetime]:
    if not raw:
        return None
    try:
        s = str(raw).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is not None:  # datetime.now() naive → tutarlılık için yerel naive
            dt = dt.astimezone().replace(tzinfo=None)
        return dt
    except Exception:
        return None


def is_admin_role(role: Optional[str]) -> bool:
    return (role or "").strip().lower() in ADMIN_ROLES


def resolve_flags(payload: dict, role: Optional[str]) -> Tuple[bool, Optional[datetime], List[str]]:
    """(debug_enabled, now_override, ignored_notes).

    `debug_trace`: admin + açık bayrak. `now_override`: admin + `debug_trace` açık
    (Automic sözleşmesiyle aynı). Aksi halde yok sayılır ve nota yazılır.
    """
    want_debug = bool(payload.get("debug_trace"))
    want_now = payload.get("now_override")
    admin = is_admin_role(role)
    ignored: List[str] = []
    debug = want_debug and admin
    now: Optional[datetime] = None
    if want_debug and not admin:
        ignored.append("debug_trace")
    if want_now:
        if not debug:
            ignored.append("now_override")
        else:
            now = parse_now_override(want_now)
            if now is None:
                ignored.append("now_override_invalid")
    return debug, now, ignored


def _dumps(obj: Any) -> str:
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)


def _size(obj: Any) -> int:
    return len(_dumps(obj).encode("utf-8", "ignore"))
