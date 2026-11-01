"""Adım 10 — ilk token ÖNCESİ ilerleme olayları (`type: "progress"`), tüm sohbet hatları için tek noktadan.

Olay: {"type": "progress", "step": <adım>, "text": <sabit şablon>, "elapsed_s": N [, "heartbeat": true]}
(Automic'in `progress` olayıyla aynı `type/step/text` alanları.)

Kaynaklar
  1. Hat olayları (`phase`, `tool_call`, `tool_result`) → aşama değişimi.
  2. Sessizlik bekçisi (`tick`): son olaydan beri ≥ `heartbeat_s` geçtiyse «kalp atışı» (virt gibi tek-blok hatlarda da).
  3. `TurnTrace.tools` (araç TAMAMLANINCA dolar) → hat `tool_call` olayı yayınlamıyorsa «sorgu tamamlandı».

Güvenlik/gizlilik: metin yalnız SABİT şablon + (varsa) araç ETİKETİ (≤ 48 karakter, satır sonu/kontrol karakteri atılır);
kullanıcı mesajı, araç argümanı/sonucu, sunucu/VM adı ASLA konmaz. İlk token gelince susar. Tur başına ≤ MAX_EVENTS aşama olayı; kalp atışı ayrıca (MAX_HEARTBEATS) — uzun beklemede susmaz.
LLM/araç çağırmaz, DB'ye yazmaz; yalnız Redis olayı üretir (yayın çağıranda).
"""
from __future__ import annotations

import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional, Sequence

MAX_EVENTS = 60          # aşama olayı sınırı (tur başına)
MAX_HEARTBEATS = 720     # kalp atışı sınırı (5 sn aralıkla ≈ 1 saat) — uzun beklemede sessizlik OLMAMALI
DEFAULT_HEARTBEAT_S = 5.0

STEPS = ("queued", "understood", "selecting", "querying", "queried", "thinking", "answering", "waiting")

_TEXT = {
    "queued": "Sırada bekleniyor",
    "understood": "Soru anlaşıldı, kaynaklar belirleniyor",
    "selecting": "Hangi veri kaynaklarının gerekeceği belirleniyor",
    "querying": "Veriler sorgulanıyor",
    "queried": "Sorgu tamamlandı, sonuçlar değerlendiriliyor",
    "thinking": "Sonuçlar değerlendiriliyor",
    "answering": "Cevap yazılıyor",
}

_CTRL = re.compile(r"[\x00-\x1f\x7f]+")


def safe_label(label: Any, limit: int = 48) -> str:
    """Araç etiketi: kontrol karakteri/satır sonu atılır, kısaltılır. Boş olabilir."""
    s = _CTRL.sub(" ", str(label or "")).strip()
    s = re.sub(r"\s+", " ", s)
    return s[:limit]


class ProgressTracker:
    def __init__(
        self,
        *,
        enabled: bool = True,
        heartbeat_s: float = DEFAULT_HEARTBEAT_S,
        clock: Callable[[], float] = time.monotonic,
        max_events: int = MAX_EVENTS,
        max_heartbeats: int = MAX_HEARTBEATS,
    ) -> None:
        self.enabled = bool(enabled)
        self.heartbeat_s = max(1.0, float(heartbeat_s))
        self._clock = clock
        self.max_events = max_events
        self.max_heartbeats = max_heartbeats
        self.n_heartbeats = 0
        self.t0 = clock()
        self.last_emit = self.t0
        self.step = ""
        self.text = ""
        self.first_token = False
        self.n_emitted = 0
        self.chunk_tools = 0          # hat tool_call olayı yayınlıyor mu (trace tabanlı «queried» çift saymasın)
        self._trace_seen = 0
        self._last_key = ("", "")
        self._lock = threading.RLock()   # bekçi ayrı iş parçacığında (event döngüsü bloklansa da kalp atışı çıkar)

    # ── yardımcılar ────────────────────────────────────────────────────
    @property
    def done(self) -> bool:
        return (not self.enabled) or self.first_token or self.n_heartbeats >= self.max_heartbeats

    def _elapsed(self) -> int:
        return int(max(0.0, self._clock() - self.t0))

    def _mk(self, step: str, text: str, *, heartbeat: bool = False) -> Optional[Dict[str, Any]]:
        if self.done:
            return None
        if not heartbeat and ((step, text) == self._last_key or self.n_emitted >= self.max_events):
            return None
        if heartbeat:
            self.n_heartbeats += 1
        else:
            self.n_emitted += 1
        self.last_emit = self._clock()
        if not heartbeat:
            self.step, self.text = step, text
            self._last_key = (step, text)
        ev: Dict[str, Any] = {"type": "progress", "step": step, "text": text, "elapsed_s": self._elapsed()}
        if heartbeat:
            ev["heartbeat"] = True
        return ev

    # ── girdiler ───────────────────────────────────────────────────────
    def start(self, step: str = "understood", extra: str = "") -> List[Dict[str, Any]]:
        with self._lock:
            return self._start(step, extra)

    def _start(self, step: str, extra: str) -> List[Dict[str, Any]]:
        ev = self._mk(step, _TEXT.get(step, "Çalışıyor") + (f" ({extra})" if extra else ""))
        return [ev] if ev else []

    def on_token(self) -> None:
        with self._lock:
            self.first_token = True

    def rearm(self, text: str = "Cevap yeniden hazırlanıyor") -> List[Dict[str, Any]]:
        """Ekrandaki cevap silindiyse (`replace_answer`: kesik/sızıntılı canlı cevap → ikinci üretim) ilerleme
        yeniden açılır; yoksa kullanıcı dakikalarca boş ekran görür (Adım 14)."""
        with self._lock:
            if not self.enabled or self.n_heartbeats >= self.max_heartbeats:
                return []
            self.first_token = False
            self.last_emit = self._clock()
            self._last_key = ("", "")
            ev = self._mk("thinking", text)
            return [ev] if ev else []

    def on_chunk(self, chunk: Dict[str, Any]) -> List[Dict[str, Any]]:
        with self._lock:
            return self._on_chunk(chunk)

    def _on_chunk(self, chunk: Dict[str, Any]) -> List[Dict[str, Any]]:
        if self.done or not isinstance(chunk, dict) or chunk.get("token"):
            return []
        out: List[Optional[Dict[str, Any]]] = []
        phase = chunk.get("phase")
        typ = chunk.get("type")
        if phase == "collecting":
            out.append(self._mk("understood", _TEXT["understood"]))
        elif phase == "tools":
            out.append(self._mk("selecting", _TEXT["selecting"]))
        elif phase == "answering":
            out.append(self._mk("answering", _TEXT["answering"]))
        elif typ == "tool_call":
            self.chunk_tools += 1
            lab = safe_label(chunk.get("label") or chunk.get("tool"))
            out.append(self._mk("querying", _TEXT["querying"] + (f" ({lab})" if lab else "")))
        elif typ == "tool_result":
            lab = safe_label(chunk.get("label") or chunk.get("tool"))
            out.append(self._mk("queried", f"Sorgu tamamlandı{f' ({lab})' if lab else ''}, sonuçlar değerlendiriliyor"))
        return [e for e in out if e]

    def tick(self, trace_tools: Optional[Sequence[str]] = None, queue_position: Optional[int] = None) -> List[Dict[str, Any]]:
        """Bekçi her ~1 sn çağırır. trace_tools: TurnTrace'te tamamlanmış araç adları (sırayla)."""
        with self._lock:
            return self._tick(trace_tools, queue_position)

    def _tick(self, trace_tools: Optional[Sequence[str]], queue_position: Optional[int]) -> List[Dict[str, Any]]:
        if self.done:
            return []
        out: List[Optional[Dict[str, Any]]] = []
        if trace_tools is not None and self.chunk_tools == 0 and len(trace_tools) > self._trace_seen:
            lab = safe_label(trace_tools[-1])
            self._trace_seen = len(trace_tools)
            out.append(self._mk("queried", f"Sorgu tamamlandı{f' ({lab})' if lab else ''}, sonuçlar değerlendiriliyor"))
        elif self._clock() - self.last_emit >= self.heartbeat_s:
            if self.step == "queued" and queue_position is not None:
                base = f"{_TEXT['queued']} (sıranız: {int(queue_position)})"
            else:
                base = self.text or "Çalışıyor"
            out.append(self._mk("waiting", f"{base} — {self._elapsed()} sn", heartbeat=True))
        return [e for e in out if e]


def build_tracker() -> ProgressTracker:
    """Ayarlardan (`chat_progress_enabled`, `chat_progress_heartbeat_sec`) kurar; hata → güvenli varsayılan (açık, 5 sn)."""
    enabled, hb = True, DEFAULT_HEARTBEAT_S
    try:
        from app.services import runtime_settings as rts
        enabled = bool(rts.get_bool("chat_progress_enabled"))
        hb = float(rts.get_int("chat_progress_heartbeat_sec") or DEFAULT_HEARTBEAT_S)
    except Exception:
        pass
    return ProgressTracker(enabled=enabled, heartbeat_s=min(30.0, max(2.0, hb)))
