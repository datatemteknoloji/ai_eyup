"""Chat orchestrator — turn yaşam döngüsü ve arka plan runner."""
from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Callable, Dict, Optional

from sqlalchemy.orm import Session

import time
from app.core.chat_executor import run_chat_io as chat_run_io
from app.core.database import SessionLocal, release_txn
from app.models.chat_turn import ChatTurn
from app.services import chat_cancel
from app.services.chat_quality import trace as cq_trace
from app.services.chat_quality.stream_guard import StreamGuard
from app.services.chat_orchestrator import ai_gate, events, progress as chat_progress
from app.services.chat_source_planner import plan_sources, build_followup_suggestions

logger = logging.getLogger(__name__)

PipelineFn = Callable[[dict, Session], AsyncIterator[Any]]

_PIPELINES: Dict[str, PipelineFn] = {}
_consumer_started = False


def register_pipeline(platform: str, fn: PipelineFn) -> None:
    _PIPELINES[platform] = fn


def _now():
    return datetime.now(timezone.utc)


def create_turn(
    db: Session,
    *,
    platform: str,
    message: str,
    payload: dict,
    session_id: Optional[int] = None,
    user_id: Optional[int] = None,
    loop: Optional[asyncio.AbstractEventLoop] = None,
    turn_id: Optional[str] = None,
) -> ChatTurn:
    """Tur kaydını oluştur ve `run_turn`'u zamanla.

    `loop` verilirse (Adım 11: çağrı bir iş parçacığında, event döngüsü dışında yapılıyor) `run_turn` o döngüde
    `call_soon_threadsafe` ile başlatılır; verilmezse çağıranın çalışan döngüsü kullanılır.
    `turn_id` verilirse (Adım 13: `ai_gate.admit` kabul kaydı aynı kimlikle yazılmıştır) o kullanılır.
    """
    turn_id = turn_id or str(uuid.uuid4())
    # plan_sources (routing ipucu LLM'i dahil) tur izi bağlanmadan ÖNCE çalışır: tur kimliği verilir ki
    # ipucu çağrıları/ham çıktısı bu sohbet turuna (debug_trace.llm) bağlanabilsin.
    from app.services import llm_activity
    with llm_activity.trace_scope(turn_id):
        plan = plan_sources(
            message,
            scope=platform,
            skip_ctx=bool(payload.get("skip_server_context")),
            use_rag=payload.get("use_rag", True) is not False,
        )
    turn = ChatTurn(
        id=turn_id,
        session_id=session_id,
        user_id=user_id,
        platform=platform,
        status="queued",
        message=message,
        payload=payload or {},
        source_plan=plan.to_dict(),
        partial_response="",
        last_seq=0,
    )
    db.add(turn)
    db.commit()
    db.refresh(turn)
    events.publish_event(turn.id, {
        "queued": True,
        "turn_id": turn.id,
        "session_id": session_id,
        "position": ai_gate.queue_position(),
        "plan": plan.to_dict(),
    })
    events.enqueue_job(turn.id)
    try:
        if loop is not None:
            loop.call_soon_threadsafe(_spawn_turn, loop, turn.id)
        else:
            asyncio.get_running_loop().create_task(run_turn(turn.id))
    except RuntimeError:
        pass
    return turn


def _spawn_turn(loop: asyncio.AbstractEventLoop, turn_id: str) -> None:
    loop.create_task(run_turn(turn_id))


def get_turn(db: Session, turn_id: str) -> Optional[ChatTurn]:
    return db.query(ChatTurn).filter(ChatTurn.id == turn_id).first()


def cancel_turn(db: Session, turn_id: str) -> bool:
    """Turu iptal et — DB durumu + ÇALIŞAN pipeline'a ulaşan Redis bayrağı.

    Bayrak olmadan iptal kozmetikti: durum "cancelled" olsa bile pipeline
    döngüsü bunu görmediği için model token üretmeye ve `ai_gate` kotasını
    tutmaya devam ediyordu (bkz. chat_cancel).
    """
    row = get_turn(db, turn_id)
    if not row or row.status in ("completed", "failed", "cancelled"):
        return False
    # Bayrak DB commit'inden ÖNCE yazılır: pipeline döngüsü bayrağı ne kadar
    # erken görürse o kadar az token/kaynak harcanır.
    events.request_cancel(turn_id)
    row.status = "cancelled"
    row.finished_at = _now()
    db.commit()
    events.publish_event(turn_id, {
        "cancelled": True,
        "done": True,
        "notice": "Yanıt üretimi kullanıcı isteğiyle durduruldu.",
        "partial_response": row.partial_response or "",
    })
    return True


def _parse_sse_chunk(raw: Any) -> Optional[dict]:
    if isinstance(raw, dict):
        return raw
    if not isinstance(raw, str):
        return None
    line = raw.strip()
    if line.startswith("data: "):
        line = line[6:]
    try:
        obj = json.loads(line)
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _start_turn_trace(db, row, payload: dict) -> "cq_trace.TurnTrace":
    """Tur izini oluşturur; `debug_trace`/`now_override` yalnız admin için etkinleşir."""
    role = None
    username = ""
    try:
        if row.user_id is not None:
            from app.models.user import User
            u = db.query(User).filter(User.id == row.user_id).first()
            role = getattr(u, "role", None)
            username = str(getattr(u, "username", "") or "")
    except Exception:
        role = None
    debug, now_override, ignored = cq_trace.resolve_flags(payload, role)
    if ignored:
        logger.info(
            "[ChatTurn] %s yetkisiz/geçersiz bayrak yok sayıldı: %s (user=%s)",
            row.id, ignored, row.user_id,
        )
    return cq_trace.TurnTrace(
        turn_id=str(row.id),
        platform=str(row.platform or ""),
        message=str(row.message or ""),
        debug_enabled=debug,
        username=username,
        user_id=row.user_id,
        now_override=now_override,
        ignored=ignored,
    )


def _make_guard(tr: "cq_trace.TurnTrace", row) -> StreamGuard:
    from app.services.chat_quality.action_gate import soft_action_intent
    from app.services.chat_quality.prompt_registry import get_shingles
    try:
        intent = soft_action_intent(row.message or "")
    except Exception:
        intent = False
    try:
        sh = get_shingles()
    except Exception:
        sh = None
    return StreamGuard(user_action_intent=intent, has_mutating_tool=tr.has_mutating_tool, shingles=sh)


def _history_text(db, row, n: int = 6) -> str:
    """Kanıt için son birkaç oturum mesajı (doğrulayıcı); hata → boş."""
    try:
        if row.session_id is None:
            return ""
        from app.models.chat_session import ChatMessage
        rows = (db.query(ChatMessage.content).filter(ChatMessage.session_id == row.session_id)
                .order_by(ChatMessage.id.desc()).limit(n).all())
        return "\n".join(str(r[0] or "")[:4000] for r in rows)
    except Exception:
        try:
            db.rollback()
        except Exception:
            pass
        return ""


def _apply_user_language(db, row, text: str, turn_id: str) -> str:
    """Adım 8: NOT_QUERIED / SUCCESS_EMPTY → insan dili (deterministik; doğrulayıcıdan ÖNCE). Değişirse
    UI'da cevap `replace_answer` ile yeniden akıtılır, DB mesajı ve partial_response güncellenir. Hata → eski metin."""
    try:
        from app.services.chat_quality import user_language
        fixed = user_language.normalize(text, directive=user_language.message_directive(row.message or ""))
        if fixed == text:
            return text
        events.publish_event(turn_id, {"replace_answer": True})
        for i in range(0, len(fixed), 240):
            events.publish_event(turn_id, {"token": fixed[i:i + 240]})
        row.partial_response = fixed
        from app.services.chat_quality.persist import fix_assistant_message
        fix_assistant_message(db, row, replace=fixed)
        logger.info("[UserLanguage] %s durum kodu insan diline çevrildi", turn_id)
        return fixed
    except Exception:
        logger.warning("[UserLanguage] %s eşleme atlandı", turn_id, exc_info=True)
        return text


def _run_grounding(db, row, tr, text: str, turn_id: str) -> None:
    """Veriye dayalılık doğrulayıcısı (Adım 7b/7c): akış bittikten sonra; gölge modda yalnız iz/log,
    enforce modda eşiği geçen sınıflar için cevabın sonuna uyarı. Hata hiçbir zaman turu düşürmez."""
    try:
        from app.services.chat_quality import grounding
        res = grounding.verify_turn(tr, text, history_text=_history_text(db, row))
        if res is None:
            return
        notice = ""
        if res.get("mode") == "enforce":
            classes = grounding.enforce_classes()
            notice = grounding.notice_for(res, classes)
            res["enforced"] = sorted(classes)
            res["notice_added"] = bool(notice)
        tr.grounding = res
        if res.get("findings") or res.get("error"):
            logger.info("[Grounding] %s mode=%s ms=%s counts=%s skipped=%s", turn_id, res.get("mode"), res.get("ms"),
                        res.get("counts"), res.get("skipped"))
        if notice:
            events.publish_event(turn_id, {"token": notice})
            from app.services.chat_quality.persist import fix_assistant_message
            fix_assistant_message(db, row, append=notice)
    except Exception:
        logger.warning("[Grounding] %s doğrulayıcı çalıştırılamadı", turn_id, exc_info=True)


def _on_violation(db, row, violation, tr) -> None:
    """Akış kesildi: DB'deki asistan mesajını şablonla değiştir + iz + audit."""
    from app.services.chat_quality.persist import fix_assistant_message
    from app.services.chat_quality.masking import mask_text
    fix_assistant_message(db, row, replace=violation.db_text)
    if tr is not None:
        tr.note_path("verifier_block", violation_kind=violation.kind, level=violation.level,
                     sentence=mask_text(violation.sentence)[:160])
    logger.warning("[ChatGuard] %s akış engellendi kind=%s level=%s: %.100s",
                   row.id, violation.kind, violation.level, violation.sentence)
    try:
        from app.services.audit import record_audit
        record_audit(
            None, category="ai_guard", action=f"chat.verifier.{violation.kind}", status="blocked",
            actor=(getattr(tr, "username", None) or None),
            summary=mask_text(violation.sentence)[:140],
            detail={"turn_id": str(row.id), "level": violation.level, "platform": row.platform},
        )
    except Exception:
        pass


def _progress_watch_loop(turn_id: str, tracker: "chat_progress.ProgressTracker", holder: dict, wait: Callable[[float], bool]) -> None:
    """Adım 10: ilk token öncesi sessizlik bekçisi — ~1 sn'de bir; yalnız olay üretir (LLM/DB yok).
    AYRI İŞ PARÇACIĞINDA koşar: hat senkron iş yaparak event döngüsünü bloklasa da kalp atışı çıkar.
    `wait(sn)` durdurulunca True döner (testte sahte saat verilir)."""
    try:
        while not tracker.done:
            if wait(1.0):
                return
            _rn = holder.get("renew")          # Adım 13: ilk token öncesi uzun sessizlikte lease'i yenile
            if _rn is not None:
                _m = time.monotonic()
                if _m - holder.get("_renewed", 0.0) > ai_gate.RENEW_EVERY_SEC:
                    holder["_renewed"] = _m
                    try:
                        _rn()
                    except Exception:
                        pass
            tr = holder.get("tr")
            names = tr.tool_names() if tr is not None else None
            qpos = None
            if tracker.step == "queued":
                try:
                    qpos = ai_gate.queue_position(turn_id) or ai_gate.queue_position()   # Adım 13: kendi sıram
                except Exception:
                    qpos = None
            for ev in tracker.tick(trace_tools=names, queue_position=qpos):
                events.publish_event(turn_id, ev)
    except Exception:
        logger.debug("[Progress] bekçi durdu", exc_info=True)


def _start_progress_watch(turn_id: str, tracker: "chat_progress.ProgressTracker", holder: dict):
    import threading
    stop = threading.Event()
    th = threading.Thread(
        target=_progress_watch_loop, args=(turn_id, tracker, holder, stop.wait),
        name=f"chat-progress-{turn_id[:8]}", daemon=True,
    )
    th.start()
    return stop


async def run_turn(turn_id: str) -> None:
    if not events.acquire_turn_lock(turn_id):
        return
    db = SessionLocal()
    _pw_stop = None   # threading.Event
    _pw_tracker: Optional["chat_progress.ProgressTracker"] = None
    _pw_holder: dict = {}
    _sess_id: Optional[int] = None     # Adım 13: oturum kilidi (aynı oturumda turlar sırayla)
    _gate_held = False                 # Adım 13: kapı lease'i bizde mi (outer finally güvence)
    _gate_t0: Optional[float] = None
    try:
        row = get_turn(db, turn_id)
        if not row or row.status in ("completed", "failed", "cancelled"):
            return
        if row.status == "cancelled":
            return
        pipeline = _PIPELINES.get(row.platform)
        if pipeline is None:
            row.status = "failed"
            row.error = f"pipeline yok: {row.platform}"
            row.finished_at = _now()
            db.commit()
            events.publish_event(turn_id, {"error": row.error, "done": True})
            return

        row.status = "running"
        db.commit()
        events.publish_event(turn_id, {"phase": "collecting", "turn_id": turn_id})

        # Adım 13: aynı oturumda önceki tur bitene kadar bekle (kuyruk slotu tutmadan)
        async def _sess_wait_notice() -> None:
            await chat_run_io(events.publish_event, turn_id, {
                "queued": True,
                "message": "Bu sohbetteki önceki soru bitince başlayacak.",
            })

        _sess_id = row.session_id
        _gate_msg = row.message
        # Bekleme (oturum sırası + kapı, ≤ ~3 dk) boyunca bu oturum «idle in transaction» KALMASIN: Postgres rolünde
        # idle_in_transaction_session_timeout=120s var → bağlantı öldürülür, pipeline'ın ilk yazısında PendingRollbackError.
        db.commit()
        _sg = await ai_gate.session_acquire(_sess_id, turn_id, on_wait=_sess_wait_notice)
        if not _sg.ok:
            _sess_id = None   # kilit bizde değil → finally'de bırakma
            if _sg.reason == "cancelled":
                row.status = "cancelled"
                row.finished_at = _now()
                db.commit()
                events.clear_cancel(turn_id)
                events.publish_event(turn_id, {
                    "cancelled": True, "done": True, "turn_id": turn_id,
                    "notice": "İstek kuyrukta beklerken iptal edildi.",
                })
            else:
                row.status = "failed"
                row.error = _sg.message or "Oturum sırası zaman aşımı"
                row.finished_at = _now()
                db.commit()
                events.publish_event(turn_id, {"error": row.error, "done": True})
            return

        pos = await chat_run_io(ai_gate.expected_position)
        # Adım 10: ilerleme olayları (kapalıysa tracker.done=True → hiçbir şey yayınlanmaz)
        _pw_tracker = chat_progress.build_tracker()
        for _pev in _pw_tracker.start("understood"):
            events.publish_event(turn_id, _pev)
        if pos > 0:
            _eta = await chat_run_io(ai_gate.eta_seconds, pos)
            events.publish_event(turn_id, {
                "queued": True,
                "position": pos,
                **({"eta_sec": _eta} if _eta else {}),
                "message": f"Sıradasınız: {pos}" + (f" (tahmini ~{_eta} sn)" if _eta else ""),
            })
            if not _pw_tracker.done:
                _qev = _pw_tracker._mk("queued", f"{chat_progress._TEXT['queued']} (sıranız: {int(pos)})")
                if _qev:
                    events.publish_event(turn_id, _qev)
        if not _pw_tracker.done:
            _pw_stop = _start_progress_watch(turn_id, _pw_tracker, _pw_holder)
        _gate = await ai_gate.acquire(turn_id, message=_gate_msg)
        if _gate.ok:
            _gate_held = True
            _gate_t0 = time.monotonic()
            _pw_holder["renew"] = lambda: ai_gate.renew(turn_id, _sess_id)
        if _gate.ok and _pw_tracker is not None and _pw_tracker.step == "queued":
            for _pev in _pw_tracker.start("understood"):
                events.publish_event(turn_id, _pev)
        if not _gate.ok and _gate.reason != "cancelled":
            row.status = "failed"
            row.error = _gate.message or "AI kuyruğu zaman aşımı"
            row.finished_at = _now()
            db.commit()
            events.publish_event(turn_id, {"error": row.error, "done": True})
            return

        # Kuyrukta beklerken iptal edilmiş olabilir — kotayı alıp hemen bırak,
        # pipeline'ı hiç başlatma.
        if _gate.reason == "cancelled" or chat_cancel.is_cancelled_for(turn_id):
            if _gate_held:
                ai_gate.release(turn_id, _gate_t0)
                _gate_held = False
            row.status = "cancelled"
            row.finished_at = _now()
            db.commit()
            events.clear_cancel(turn_id)
            events.publish_event(turn_id, {
                "cancelled": True, "done": True, "turn_id": turn_id,
                "notice": "İstek kuyrukta beklerken iptal edildi.",
            })
            return

        full = []
        token_n = 0
        cancelled = False
        cancel_token = chat_cancel.bind(turn_id)
        from app.services import llm_gateway as _llm_gw
        _rel_token = _llm_gw.bind_release_hook(lambda: release_txn(db))
        gen = None
        tr = None
        tr_token = None
        guard: Optional[StreamGuard] = None
        violation = None
        try:
            payload = dict(row.payload or {})
            payload.setdefault("message", row.message)
            payload.setdefault("session_id", row.session_id)
            tr = _start_turn_trace(db, row, payload)
            _pw_holder["tr"] = tr
            tr.note_path("gate", wait_ms=round(_gate.wait_ms), lane=_gate.lane, position=int(_gate.first_position),
                         session_wait_ms=round(_sg.wait_ms))
            tr_token = cq_trace.bind(tr)
            try:
                guard = _make_guard(tr, row)
            except Exception:
                logger.warning("[ChatGuard] guard oluşturulamadı; varsayılan", exc_info=True)
                guard = StreamGuard(has_mutating_tool=tr.has_mutating_tool)
            gen = pipeline(payload, db)
            _last_release = 0.0
            _last_renew = time.monotonic()
            async for raw in gen:
                events.refresh_turn_lock(turn_id)
                if time.monotonic() - _last_renew > ai_gate.RENEW_EVERY_SEC:
                    ai_gate.renew(turn_id, _sess_id)   # Adım 13: lease + oturum kilidi uzat
                    _last_renew = time.monotonic()
                # Okuma işlemi LLM/araç beklemesi boyunca açık kalmasın (idle in transaction → retention kilidi kuyruğu)
                _mono = time.monotonic()
                if _mono - _last_release > 3.0:
                    release_txn(db)
                    _last_release = _mono
                # İptal kontrolü: her olayda, Redis okuması 250 ms kısmalı
                # (bkz. chat_cancel). Döngüden çıkmak generator'ı kapatır ve
                # GeneratorExit `async with client.stream(...)` bloklarına
                # kadar yayılır → uzak LLM bağlantısı fiilen kesilir.
                if chat_cancel.is_cancelled():
                    cancelled = True
                    break
                chunk = _parse_sse_chunk(raw)
                if not chunk:
                    continue
                tr.note_chunk(chunk)
                if _pw_tracker is not None and not chunk.get("token"):
                    for _pev in _pw_tracker.on_chunk(chunk):
                        events.publish_event(turn_id, _pev)
                if row.session_id is None and chunk.get("session_id"):
                    try:
                        row.session_id = int(chunk["session_id"])
                        db.commit()
                    except Exception:
                        db.rollback()
                if chunk.get("token"):
                    full.append(str(chunk["token"]))
                    token_n += 1
                    if token_n == 1:
                        row.status = "streaming"
                    if token_n % 24 == 0:
                        row.partial_response = "".join(full)
                        db.commit()
                # ── Geri tutma tamponu: token'lar ~1 cümle bekletilip denetlenir (stream_guard) ──
                if chunk.get("token") and not chunk.get("done") and not chunk.get("error"):
                    released = guard.feed(str(chunk["token"]))
                    if guard.violation:
                        violation = guard.violation
                        events.publish_event(turn_id, {"token": violation.template})
                        break
                    if released:
                        events.publish_event(turn_id, {**chunk, "token": released})
                        if _pw_tracker is not None:
                            _pw_tracker.on_token()   # kullanıcı ilk token'ı GÖRDÜ → ilerleme susar
                    continue
                # Token olmayan olaydan önce bekleyen metni bırak (olay sırası korunur)
                pending = guard.flush()
                if guard.violation:
                    violation = guard.violation
                    events.publish_event(turn_id, {"token": violation.template})
                    break
                if pending:
                    events.publish_event(turn_id, {"token": pending})
                    if _pw_tracker is not None:
                        _pw_tracker.on_token()
                if chunk.get("replace_answer"):
                    # Adım 14: ekrandaki cevap silinip yeniden akıtılacak → kayıtlı kısmi metin de sıfırlanır
                    # (aksi halde eski + yeni metin birleşip partial_response/koruma metnine çift girerdi).
                    full.clear()
                if chunk.get("error") and not chunk.get("done"):
                    events.publish_event(turn_id, chunk)
                    continue
                if chunk.get("done"):
                    break
                events.publish_event(turn_id, chunk)
                if chunk.get("replace_answer") and _pw_tracker is not None:
                    # Ekran temizlendi → sessizlik olmasın: ilerleme/kalp atışı yeniden açılır (ilk token'da susar)
                    _rev = _pw_tracker.rearm()
                    for _pev in _rev:
                        events.publish_event(turn_id, _pev)
                    if _rev and "stop2" not in _pw_holder:
                        _pw_holder["stop2"] = _start_progress_watch(turn_id, _pw_tracker, _pw_holder)
        except chat_cancel.ChatCancelled:
            cancelled = True
        finally:
            chat_cancel.unbind(cancel_token)
            _llm_gw.unbind_release_hook(_rel_token)
            if tr_token is not None:
                cq_trace.unbind(tr_token)
            if gen is not None:
                # Generator'ı AÇIKÇA kapat: `break` ile çıkıldığında kapanma
                # GC'ye bırakılırsa HTTP stream'i (ve uzak model üretimi)
                # belirsiz bir süre daha açık kalabilir.
                try:
                    await gen.aclose()
                except Exception:
                    pass
            _pw_holder.pop("renew", None)   # release sonrası geç yenileme lease'i diriltmesin
            ai_gate.release(turn_id, _gate_t0)
            _gate_held = False

        guard_tail = ""
        if guard is not None and not cancelled:
            if violation is None:
                guard_tail = guard.finish()
                if guard.violation:
                    violation = guard.violation
                    events.publish_event(turn_id, {"token": violation.template})
                    guard_tail = ""
                elif guard_tail:
                    events.publish_event(turn_id, {"token": guard_tail})
        if guard is not None and tr is not None:
            tr.guard = guard.stats.summary()
            if guard.stats.delays_ms:
                logger.info("[ChatGuard] %s hold_ms p50=%s p95=%s max=%s ttft_added=%s blocked=%s risk_cmds=%s",
                            turn_id, tr.guard["hold_ms_p50"], tr.guard["hold_ms_p95"], tr.guard["hold_ms_max"],
                            tr.guard["ttft_added_ms"], tr.guard["blocked"], tr.guard["risk_cmds"])
        text = "".join(full).strip()
        if violation is not None:
            text = violation.db_text
        elif guard_tail:
            text = (text + guard_tail).strip()
        # Durum başka bir worker'dan iptal edilmiş olabilir; kendi oturumumuzdaki
        # eski değere güvenip "completed" yazmak iptali sessizce ezerdi. Kontrol
        # partial_response yazılmadan ÖNCE yapılır (refresh bekleyen değişikliği
        # geri alır).
        if not cancelled:
            try:
                db.refresh(row)
            except Exception:
                pass
            cancelled = (
                row.status == "cancelled"
                or chat_cancel.is_cancelled_for(turn_id)
            )
        row.partial_response = text
        if cancelled:
            row.status = "cancelled"
            row.finished_at = _now()
            db.commit()
            events.clear_cancel(turn_id)
            events.publish_event(turn_id, {
                "cancelled": True,
                "done": True,
                "session_id": row.session_id,
                "turn_id": turn_id,
                "notice": "Yanıt üretimi kullanıcı isteğiyle durduruldu.",
            })
            logger.info(
                "[ChatTurn] %s kullanıcı isteğiyle iptal edildi (%s token üretilmişti)",
                turn_id, token_n,
            )
            return
        if violation is not None:
            _on_violation(db, row, violation, tr)
        elif guard_tail:
            from app.services.chat_quality.persist import fix_assistant_message
            fix_assistant_message(db, row, append=guard_tail)
        if tr is not None and violation is None:
            text = _apply_user_language(db, row, text, turn_id)
            _run_grounding(db, row, tr, text, turn_id)
        if tr is not None and tr.debug_enabled:
            # Yalnız admin + açık bayrak: maskeli, boyut sınırlı iz (done'dan önce tek olay).
            # Durum "completed" yazılmadan ÖNCE yayınlanır: subscribe_sse boşta kalınca
            # completed durumunu görüp sentetik `done` ile bitirir; maskeleme uzarsa iz kaybolurdu.
            try:
                events.publish_event(turn_id, {
                    "type": "debug_trace",
                    "trace": tr.to_debug_dict(answer=text),
                })
            except Exception:
                logger.warning("[ChatTurn] %s debug_trace yayınlanamadı", turn_id, exc_info=True)
        row.status = "completed"
        row.finished_at = _now()
        plan = row.source_plan if isinstance(row.source_plan, dict) else {}
        try:
            from app.services.chat_quality.action_gate import check_message as _gate_check
            if _gate_check(row.message or "") is not None:
                suggestions = []
            else:
                # Tur izi artık çözülmüş; bu plan_sources çağrısı (ipucu önbelleği dolmuşsa yeniden sorar/atlanır)
                # yine de bu tura bağlanır (debug_trace.llm.route_hint / llm_activity trace_id).
                from app.services import llm_activity
                with llm_activity.trace_scope(turn_id):
                    # Adım 11: senkron ipucu LLM'i event döngüsünü bloklamasın (ipucu önbelleği çoğu zaman dolu)
                    _end_plan = await chat_run_io(plan_sources, row.message, scope=row.platform)
                suggestions = build_followup_suggestions(
                    _end_plan,
                    used_sources=plan.get("sources"),
                )
        except Exception:
            suggestions = []
        db.commit()
        events.publish_event(turn_id, {
            "done": True,
            "session_id": row.session_id,
            "turn_id": turn_id,
            "suggestions": suggestions,
            # Adım 9: akıştaki `from_cache` bayrağı (tr.note_chunk) istemciye de iletilir — eskiden son `done` olayı bunu düşürüyordu
            **({"from_cache": True} if (tr is not None and getattr(tr, "flags", {}).get("from_cache")) else {}),
        })
    except Exception as e:
        logger.error("run_turn failed %s: %s", turn_id, e, exc_info=True)
        try:
            db.rollback()
            row = get_turn(db, turn_id)
            if row:
                row.status = "failed"
                row.error = str(e)
                row.finished_at = _now()
                db.commit()
            events.publish_event(turn_id, {"error": str(e), "done": True})
        except Exception:
            pass
    finally:
        if _pw_tracker is not None:
            _pw_tracker.first_token = True   # bekçiyi durdur
        if _pw_stop is not None:
            _pw_stop.set()
        _st2 = _pw_holder.get("stop2")
        if _st2 is not None:
            _st2.set()
        if _gate_held:
            ai_gate.release(turn_id, _gate_t0)   # pipeline'a girmeden çıkış (ör. iz/bağlama hatası) slot sızdırmasın
        ai_gate.session_release(_sess_id, turn_id)
        ai_gate.turn_finished(turn_id)
        events.release_turn_lock(turn_id)
        db.close()


def _note_delivery_lag(turn_id: str, batch, t_submit: float, tm: dict) -> None:
    """SSE teslim gecikmesi tanısı (Adım 11): XADD → istemciye yield arası > 1,5 sn ise bileşenleri logla.

    Bileşenler: executor kuyruğu (submit→start), XREAD süresi (start→end), döngü uyanma (end→şimdi).
    """
    try:
        now = time.time()
        newest = max(int(str(eid).split("-")[0]) for eid, _ in batch)
        lag = now - newest / 1000.0
        if lag < 1.5:
            return
        st, en = tm.get("start", t_submit), tm.get("end", now)
        logger.warning(
            "[SSELag] turn=%s lag=%.2fs executor_wait=%.2fs xread=%.2fs loop_wake=%.2fs n=%d",
            turn_id[:8], lag, max(0.0, st - t_submit), max(0.0, en - st), max(0.0, now - en), len(batch),
        )
    except Exception:
        pass


async def subscribe_sse(turn_id: str, after_id: str = "0-0") -> AsyncIterator[str]:
    last = after_id or "0-0"
    idle_rounds = 0
    db = SessionLocal()
    try:
        row = get_turn(db, turn_id)
        terminal = row and row.status in ("completed", "failed", "cancelled")
    finally:
        db.close()

    # önce snapshot replay
    for ev in events.snapshot_events(turn_id, after_id=last):
        eid = ev.pop("_id", last)
        last = eid
        yield "data: " + json.dumps(ev, ensure_ascii=False, default=str) + "\n\n"
        if ev.get("done"):
            return

    while True:
        _t_submit = time.time()
        _tm: dict = {}

        def _timed_read(_tid=turn_id, _last=last, _tm=_tm):
            _tm["start"] = time.time()
            try:
                return events.read_new_events(_tid, _last, 1500, 50)
            finally:
                _tm["end"] = time.time()

        batch = await chat_run_io(_timed_read)
        if batch:
            _note_delivery_lag(turn_id, batch, _t_submit, _tm)
            idle_rounds = 0
            for eid, ev in batch:
                last = eid
                ev.pop("_id", None)
                yield "data: " + json.dumps(ev, ensure_ascii=False, default=str) + "\n\n"
                if ev.get("done"):
                    return
            continue
        idle_rounds += 1
        db = SessionLocal()
        try:
            row = get_turn(db, turn_id)
            if row and row.status in ("completed", "failed", "cancelled"):
                # Yarış düzeltmesi: son XREAD zaman aşımı ile bu durum kontrolü arasında
                # tur bitmiş olabilir; yayınlanmış ama okunmamış olayları (token, iz, done)
                # önce boşalt — yoksa kullanıcı boş cevap görür (cevap DB'de durur).
                while True:
                    rest = await asyncio.to_thread(events.snapshot_events, turn_id, last)
                    if not rest:
                        break
                    for ev in rest:
                        last = ev.pop("_id", last)
                        yield "data: " + json.dumps(ev, ensure_ascii=False, default=str) + "\n\n"
                        if ev.get("done"):
                            return
                extra = {"done": True, "session_id": row.session_id, "turn_id": turn_id}
                if row.error:
                    extra["error"] = row.error
                yield "data: " + json.dumps(extra, ensure_ascii=False) + "\n\n"
                return
        finally:
            db.close()
        if idle_rounds > 240:
            yield "data: " + json.dumps({"error": "Turn zaman aşımı", "done": True}) + "\n\n"
            return


async def consumer_loop() -> None:
    logger.info("Chat turn consumer başladı")
    while True:
        try:
            turn_id = await asyncio.to_thread(events.dequeue_job, 2)
            if turn_id:
                asyncio.create_task(run_turn(turn_id))
            else:
                await asyncio.sleep(0.05)
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.warning("chat consumer: %s", e)
            await asyncio.sleep(1.0)


def start_consumer_if_needed() -> None:
    global _consumer_started
    if _consumer_started:
        return
    role = ""
    try:
        import os
        role = (os.getenv("AINEW_SERVICE_ROLE") or "all").strip().lower()
    except Exception:
        role = "all"
    if role not in ("chat",):
        logger.info("Chat Redis consumer atlandı (AINEW_SERVICE_ROLE=%s; iş kabul eden worker çalıştırır)", role)
        return
    _consumer_started = True
    try:
        loop = asyncio.get_event_loop()
        loop.create_task(consumer_loop())
    except Exception as e:
        logger.warning("chat consumer start failed: %s", e)
