"""Adım 17 — canlı akış ortak yardımcıları (Yönetici / Windows / Linux·OpenShift / Sanallaştırma).

Adım 14'te yalnız Yönetici sohbetinde (`api/unified_chat.py`) bulunan mantık burada toplanır:

* `live_loop_kwargs(user, provider)` — `run_read_only_tool_loop(stream_final, forward_thinking, final_reminder)` bayrakları.
* `LiveFinal` — araç döngüsünün canlı çıktısını (thinking / answer_start / token / answer_reset / final) SSE'ye çevirir ve
  «tek geçiş mi, ikinci üretim mi» kararını verir (`settle()`).
* `LiveSink` + `generate_live_sync` — iş parçacığında koşan senkron hatlar (Sanallaştırma) için thread-güvenli olay kuyruğu
  ve token token akan LLM çağrısı.
* `paced_chunks` — hazır metni tek patlama yerine ≤ ~1,2 sn'ye yayar.

Kural: bu modül `async def` yolunda SENKRON iş yapmaz (`generate_live_sync` yalnız iş parçacığında çağrılır).
"""
from __future__ import annotations

import asyncio
import contextvars
import json
import logging
import queue
import time
from typing import Any, AsyncIterator, Dict, List, Optional

from app.services import runtime_settings as runtime_settings_mod
from app.services.chat_rules import NUMBER_RULE_TR
from app.services.chat_text_norm import normalize_hyphens

logger = logging.getLogger(__name__)

_EXTERNAL_PROVIDERS = ("groq", "openai", "openrouter")

# Tek geçişte (araç turu cevabı da yazar) ikinci üretim isteminin kuralları son tur için hatırlatılır.
SINGLE_PASS_RULES = (
    "\n\nCEVAP BİÇİMİ (araçlardan sonraki SON yanıt için):\n"
    + NUMBER_RULE_TR + "\n"
    "- Türkçe, Markdown yanıtla. Akıl yürütmeni / analizini / 'User asked…' gibi iç düşünceyi cevaba ASLA yazma; "
    "yalnız kullanıcıya yönelik nihai cevabı yaz.\n"
    "- YANIT UZUNLUĞU varsayılan KISA: basit soruya 1-3 cümle ya da küçük tablo; kullanıcı 'detaylı/kök neden' "
    "istemedikçe giriş cümlesi, arka plan bilgisi ve sabit şablon ekleme.\n"
    "- Araç adlarını (snake_case, ör. list_xxx / get_xxx) ve JSON alan adlarını (data_status, over_p95, run_id, "
    "object_name gibi) cevaba ASLA yazma; kaynak belirtirken 'sistemdeki iş kayıtları' gibi insan diliyle söyle. "
    "SUCCESS=alındı, SUCCESS_EMPTY=bu aralıkta kayıt yok, FAILED=veri alınamadı, TIMEOUT=zaman aşımı, "
    "NOT_QUERIED=sorgulanmadı, STALE=veri eski — kullanıcı diliyle söyle.\n"
)

PACE_TOTAL_S = 1.2        # tüm cevap için toplam üst sınır
PACE_MAX_CHUNKS = 60      # uzun cevapta parça sayısı (parça büyür, gecikme sabit kalır)

# Adım 14: ilk ~80 karakter tutulur; akıl yürütme sızıntısı kullanıcıya gitmesin
LEAD_HOLD_CHARS = 80


def sse(obj: dict) -> str:
    return "data: " + json.dumps(obj, ensure_ascii=False, default=str) + "\n\n"


# ── Ayarlar / kapılar ────────────────────────────────────────────────────────

def thinking_allowed(user, provider: str) -> bool:
    """Düşünme akışı (`chat_stream_thinking`: off|admin|all) bu kullanıcıya açık mı? (harici sağlayıcıda kapalı)"""
    if provider in _EXTERNAL_PROVIDERS:
        return False
    try:
        mode = str(runtime_settings_mod.get_setting("chat_stream_thinking") or "admin").strip().lower()
    except Exception:
        return False
    return mode == "all" or (mode == "admin" and getattr(user, "role", None) in ("admin", "superadmin"))


def final_think_level(model: str) -> Optional[str]:
    """İkinci üretim için gpt-oss think seviyesi (`chat_final_think`; boş = model varsayılanı)."""
    try:
        from app.services import llm_chat_policy as _lcp
        lvl = str(runtime_settings_mod.get_setting("chat_final_think") or "").strip().lower()
        if lvl in ("low", "medium", "high") and _lcp.supports_think_level(model):
            return lvl
    except Exception:
        pass
    return None


def stream_final_enabled(provider: str) -> bool:
    """Araç döngüsünün son turu canlı akıtılsın mı? (`chat_unified_stream_final`; harici sağlayıcıda kapalı)"""
    try:
        return bool(
            runtime_settings_mod.get_bool("chat_unified_stream_final")
            and provider not in _EXTERNAL_PROVIDERS
        )
    except Exception:
        return False


def live_loop_kwargs(user, provider: str) -> Dict[str, Any]:
    """`run_read_only_tool_loop` için canlı akış bayrakları (bayrak kapalıyken eski davranış)."""
    sf = stream_final_enabled(provider)
    return {
        "stream_final": sf,
        "forward_thinking": thinking_allowed(user, provider),
        "final_reminder": SINGLE_PASS_RULES if sf else None,
    }


# ── Aralıklı gönderim ────────────────────────────────────────────────────────

def paced_plan(n_chars: int) -> tuple:
    """(parça boyu, parçalar arası bekleme sn) — toplam bekleme ≤ `PACE_TOTAL_S`."""
    if n_chars <= 0:
        return 8, 0.0
    step = max(8, -(-n_chars // PACE_MAX_CHUNKS))
    n_chunks = -(-n_chars // step)
    delay = min(0.04, PACE_TOTAL_S / max(1, n_chunks))
    return step, delay


async def paced_chunks(text: str) -> AsyncIterator[str]:
    """Önceden bilinen metni `{"token":…}` SSE parçaları olarak, parçalar arasında kısa beklemeyle üretir."""
    text = text or ""
    step, delay = paced_plan(len(text))
    for i in range(0, len(text), step):
        yield sse({"token": text[i:i + step]})
        if delay and i + step < len(text):
            await asyncio.sleep(delay)


# ── Araç döngüsü canlı çıktısı → SSE + tek geçiş kararı ───────────────────────

class LiveFinal:
    """`run_read_only_tool_loop` olaylarından canlı cevap durumunu tutar.

    Kullanım (SSE üreticisinde):
        lf = LiveFinal(timing=_timing)
        ...
        for raw in lf.on_item(item): yield raw        # tool_call/tool_result çağıranın işi
        ...
        async for raw in lf.settle(): yield raw        # döngü bitince
        if lf.use_loop_final: full_response = lf.loop_text  (ikinci üretim YOK)
    """

    def __init__(self, timing=None) -> None:
        self.timing = timing
        self.live_text = ""
        self.ttft_noted = False
        self.loop_text = ""
        self.streamed = False
        self.done_reason: Optional[str] = None
        self.use_loop_final = False

    def on_item(self, item: Dict[str, Any]) -> List[str]:
        t = item.get("type")
        if t == "thinking":
            return [sse({"type": "thinking", "text": item["text"]})] if item.get("text") else []
        if t == "answer_start":
            return [sse({"phase": "answering"})]
        if t == "token":
            piece = normalize_hyphens(item.get("text") or "")      # Adım 19: kırılmaz tire → '-'
            if not piece:
                return []
            self.live_text += piece
            if not self.ttft_noted:
                self.ttft_noted = True
                try:
                    if self.timing is not None:
                        self.timing.note_ttft()
                except Exception:
                    pass
            return [sse({"token": piece})]
        if t == "answer_reset":
            if self.live_text:
                self.live_text = ""
                return [sse({"replace_answer": True})]
            return []
        if t == "final":
            self.loop_text = normalize_hyphens(item.get("final_text") or "")
            self.streamed = bool(item.get("final_streamed"))
            self.done_reason = item.get("final_done_reason")
        return []

    def decide(self) -> bool:
        return bool(
            self.streamed and self.loop_text.strip()
            and (self.done_reason or "") not in ("length", "stream_error")
        )

    async def settle(self) -> AsyncIterator[str]:
        """Döngü bittikten sonra: canlı metin kullanılabilirse korunur/düzeltilir, değilse ekrandan silinir."""
        self.use_loop_final = self.decide()
        if self.streamed or self.live_text:
            logger.info(
                "[LiveFinal] tek geçiş=%s streamed=%s done_reason=%s final_len=%s live_len=%s",
                self.use_loop_final, self.streamed, self.done_reason, len(self.loop_text), len(self.live_text),
            )
        if self.live_text and not self.use_loop_final:
            self.live_text = ""
            yield sse({"replace_answer": True})
        elif self.use_loop_final and self.live_text.strip() != self.loop_text.strip():
            yield sse({"replace_answer": True})
            async for raw in paced_chunks(self.loop_text):
                yield raw
            self.live_text = self.loop_text


# ── Senkron hatlar için: thread-güvenli kuyruk + canlı LLM çağrısı ─────────────

class LiveSink:
    """İş parçacığında koşan senkron hat (Sanallaştırma) → SSE üreticisi arasında olay kuyruğu."""

    def __init__(self, allow_thinking: bool) -> None:
        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.allow_thinking = bool(allow_thinking)
        self.live_text = ""
        self.token_started = False

    def thinking(self, text: str) -> None:
        if self.allow_thinking and text:
            self.q.put(("thinking", text))

    def token(self, text: str) -> None:
        text = normalize_hyphens(text)
        if text:
            self.live_text += text
            self.q.put(("token", text))

    def event(self, obj: Dict[str, Any]) -> None:
        """Hazır SSE nesnesi (ör. tool_call / tool_result)."""
        self.q.put(("raw", obj))

    def reset(self) -> None:
        """Ekrandaki canlı metni geri al (kullanılamaz cevap)."""
        if self.live_text:
            self.live_text = ""
            self.q.put(("reset", ""))

    def drain(self) -> List[str]:
        out: List[str] = []
        while True:
            try:
                kind, text = self.q.get_nowait()
            except queue.Empty:
                return out
            if kind == "thinking":
                out.append(sse({"type": "thinking", "text": text}))
            elif kind == "token":
                if not self.token_started:
                    self.token_started = True
                    out.append(sse({"phase": "answering"}))
                out.append(sse({"token": text}))
            elif kind == "raw":
                out.append(sse(text))
            elif kind == "reset":
                self.token_started = False
                out.append(sse({"replace_answer": True}))


live_sink_var: "contextvars.ContextVar[Optional[LiveSink]]" = contextvars.ContextVar("chat_live_sink", default=None)


def current_sink() -> Optional[LiveSink]:
    return live_sink_var.get()


def generate_live_sync(
    *,
    model: str,
    prompt: str,
    timeout: float = 120.0,
    think: Optional[str] = None,
    sink: Optional[LiveSink] = None,
) -> Dict[str, Any]:
    """`llm_gateway.generate_sync` yerine: sink varsa cevap token token sink'e akar.

    Dönüş her durumda `generate_sync` ile aynı biçimde `{"response", "error"?}`. Harici sağlayıcı, sızıntı ya da
    akış hatasında (henüz hiçbir token gitmediyse) eski bloklayan yola düşer. YALNIZ iş parçacığında çağrılır.
    """
    from app.services import llm_gateway

    sink = sink if sink is not None else current_sink()
    if sink is None:
        return llm_gateway.generate_sync(model=model, prompt=prompt, timeout=timeout)

    try:
        from app.services.llm_external import resolve_external_chat_target
        if resolve_external_chat_target(model):
            return llm_gateway.generate_sync(model=model, prompt=prompt, timeout=timeout)
        from app.services.llm_ai_source import resolve_ai_source
        prompt, _ = llm_gateway.budget.enforce_prompt_budget(
            prompt, system=None, label="generate_live", ai_source=resolve_ai_source(None),
        )
    except Exception:
        pass

    from app.services.unified_tool_chat import looks_like_reasoning_leak

    content = ""
    lead = ""
    lead_ok = False
    leak = False
    err: Optional[str] = None
    tbuf, tlast = "", time.monotonic()
    t_end = time.monotonic() + float(timeout)
    gen = llm_gateway.chat_stream_iter(
        model, [{"role": "user", "content": prompt}],
        options={"temperature": 0.2}, timeout=int(timeout), think=think,
    )
    try:
        for ev in gen:
            et = ev.get("type")
            if et == "thinking":
                tbuf += ev.get("text") or ""
                now = time.monotonic()
                if len(tbuf) >= 40 or (tbuf and now - tlast >= 0.3):
                    sink.thinking(tbuf)
                    tbuf, tlast = "", now
            elif et == "content":
                piece = ev.get("text") or ""
                content += piece
                if leak:
                    continue
                if not lead_ok:
                    lead += piece
                    if len(lead) < LEAD_HOLD_CHARS:
                        continue
                    if looks_like_reasoning_leak(lead):
                        leak = True
                        sink.thinking(lead)       # sızan metin aslında akıl yürütme → yetkiliye düşünme olarak
                        break
                    lead_ok = True
                    piece, lead = lead, ""
                sink.token(piece)
            elif et == "error":
                err = f"HTTP {ev.get('status')}: {(ev.get('text') or '')[:300]}"
                break
            if time.monotonic() > t_end:
                err = f"LLM yanıt süresi aşıldı ({int(timeout)}s)"
                break
    finally:
        try:
            gen.close()
        except Exception:
            pass
    if tbuf:
        sink.thinking(tbuf)
    if not leak and not lead_ok and lead and not err:
        if looks_like_reasoning_leak(lead):
            leak = True
            sink.thinking(lead)
        else:
            sink.token(lead)
            lead_ok = True

    if leak or (err and not sink.live_text):
        logger.warning("[LiveGenerate] canlı üretim kullanılamadı (leak=%s err=%s) → bloklayan yola düşülüyor", leak, err)
        sink.reset()
        return llm_gateway.generate_sync(model=model, prompt=prompt, timeout=timeout)
    # (token kullanımı `chat_stream_iter` içinde kaydedilir)
    content = normalize_hyphens(content)
    if err:
        return {"response": content.strip(), "done": True, "error": err}
    return {"response": content.strip(), "done": True}
