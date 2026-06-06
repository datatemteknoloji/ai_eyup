"""
Agent Orchestrator — iteratif tool-calling döngüsü + insan onayı (human-in-the-loop).

Akış:
  start_agent(user mesajı)
    → LLM'e tool şeması ile sorulur
    → READ_ONLY tool çağrıları otomatik çalıştırılır, sonuç geri beslenir, döngü sürer
    → MUTATING tool çağrısında döngü DURUR; AgentAction(pending) kaydı oluşturulur
       ve onay beklenir (transcript saklanır)
    → onay/ret sonrası continue_after_decision ile kaldığı yerden devam eder
    → tool çağrısı kalmayınca LLM'in final yanıtı döner

Güvenlik: tüm gerçek çalıştırmalar tools.Tool.execute → executor → policy zincirinden geçer.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.core.config import get_agent_model, settings
from app.models.agent_action import AgentAction
from app.models.chat_session import ChatSession, ChatMessage
from app.services.audit import record_audit
from app.services.agent import tools as tool_mod
from app.services.agent.executor import get_default_credential
from app.services.agent.guard import guard_command
from app.services.agent.llm import chat_with_tools
from app.services.agent.policy import RiskLevel
from app.services.agent.tools import resolve_server

logger = logging.getLogger(__name__)

MAX_STEPS = 8

SYSTEM_PROMPT = (
    "Sen bir AIOps Linux altyapı asistanısın. Görevin sunucularda teşhis yapmak ve "
    "gerektiğinde düzeltici işlemleri UYGULAMAKTIR.\n"
    "KURALLAR:\n"
    "1. Salt-okunur teşhis tool'larını (run_diagnostic, read_service_logs) serbestçe kullan.\n"
    "2. Bir değişiklik yapman gerekiyorsa (clean_logs, restart_service, update_packages) "
    "ONAY İÇİN KULLANICIYA METİNLE SORMA. Doğrudan ilgili tool'u çağır. "
    "Sistem, değişiklik yapan tool çağrılarını otomatik olarak duraklatıp insan onayına "
    "sunar; onaylanırsa senin yerine çalıştırır. Yani 'onayınızı bekliyorum' deme, tool'u çağır.\n"
    "3. Bir parametreyi (hangi disk, hangi volume group, hangi boyut vb.) KESİN bilmiyorsan "
    "TAHMİN ETME. Önce salt-okunur tool'larla adayları topla (örn. yeni VG için "
    "list_free_disks ile diskleri bul). Sonra kullanıcının seçmesi gereken bir durum varsa "
    "seçenekleri DÜZ METİN olarak yazıp DURMA; bunun yerine MUTLAKA 'ask_user' tool'unu çağır "
    "ve options dizisine her adayı (örn. '/dev/sdb (64G, boş)') koy. Seçenekleri metinle "
    "listeleyip yanıtı sonlandırmak YANLIŞTIR — ask_user kullan. Kullanıcı zaten net "
    "belirttiyse (disk/boyut/ad verdiyse) sormadan doğrudan ilerle.\n"
    "4. Komut çıktısı uydurma; yalnızca tool sonuçlarına dayan.\n"
    "5. Tool sonuçları döndükten ve işin bittikten sonra TÜRKÇE, kısa ve net bir özet ile bitir.\n"
    "6. Hangi sunucuda işlem yaptığını belirt."
)


def _build_initial_messages(user_message: str, ctx: Dict[str, Any]) -> List[Dict[str, Any]]:
    server_hint = ""
    ids = ctx.get("server_ids") or []
    if ctx.get("server_summary"):
        server_hint = "\n\nKULLANILABİLİR SUNUCULAR:\n" + ctx["server_summary"]
    return [
        {"role": "system", "content": SYSTEM_PROMPT + server_hint},
        {"role": "user", "content": user_message},
    ]


def _actor_name(actor) -> str:
    if actor is None:
        return "system"
    if isinstance(actor, str):
        return actor
    return getattr(actor, "username", None) or "system"


def _ensure_session(db: Session, session_id: Optional[int], first_message: str,
                    server_ids: List[int]) -> Optional[int]:
    """Agent konuşması için ChatSession garanti eder; yoksa oluşturur."""
    try:
        if session_id:
            exists = db.query(ChatSession).filter(ChatSession.id == session_id).first()
            if exists:
                return session_id
        title = (first_message or "Agent").strip()[:60] or "Agent"
        sess = ChatSession(title=f"[Agent] {title}", server_ids=server_ids or [])
        db.add(sess)
        db.commit()
        db.refresh(sess)
        return sess.id
    except Exception as e:
        logger.warning(f"[Agent] ChatSession oluşturulamadı: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return session_id


def _save_msg(db: Session, session_id: Optional[int], role: str, content: str) -> None:
    if not session_id or not content:
        return
    try:
        db.add(ChatMessage(session_id=session_id, role=role, content=content[:20000]))
        db.commit()
    except Exception as e:
        logger.warning(f"[Agent] mesaj kaydedilemedi: {e}")
        try:
            db.rollback()
        except Exception:
            pass


def _persist_final(db: Session, result: Dict[str, Any]) -> None:
    """Tur bittiğinde (done/max_steps) asistan yanıtını konuşmaya yazar."""
    if result.get("status") in ("done", "max_steps"):
        _save_msg(db, result.get("session_id"), "assistant", result.get("answer") or "")


def _server_summary(db: Session, server_ids: List[int]) -> str:
    from app.models.server import Server
    q = db.query(Server).filter(Server.ai_ready == True)  # noqa: E712
    if server_ids:
        q = q.filter(Server.id.in_(server_ids))
    lines = []
    for s in q.all():
        lines.append(f"- {s.name} ({s.ip_address}) OS={s.os_version or s.os_type or 'Linux'} durum={s.status}")
    return "\n".join(lines)


def _requires_root_prompt(db: Session, tool: tool_mod.Tool, command_str: str) -> bool:
    """
    Mutating bir işlem sudo gerektiriyor ama kullanılabilir bir sudo yetkisi yoksa
    (kayıtlı sudo şifresi yok ya da AGENT_FORCE_ROOT_PROMPT açık), kullanıcıdan
    onay anında root şifresi istenir.
    """
    needs_sudo = bool(getattr(tool, "allow_sudo", False)) and command_str.strip().startswith("sudo ")
    if not needs_sudo:
        return False
    if settings.AGENT_FORCE_ROOT_PROMPT:
        return True
    cred = get_default_credential(db)
    has_sudo = bool(cred and (cred.sudo_password or "").strip())
    return not has_sudo


def _record_action(
    db: Session, ctx: Dict[str, Any], tool: tool_mod.Tool,
    args: Dict[str, Any], status: str, result: Optional[Dict] = None,
    transcript: Optional[List] = None, model: str = "",
    requires_root: bool = False,
) -> AgentAction:
    server = resolve_server(db, args, ctx)
    action = AgentAction(
        session_id=ctx.get("session_id"),
        server_id=server.id if server else None,
        tool_name=tool.name,
        arguments=args,
        risk_level=tool.risk_level.value,
        status=status,
        preview=tool.preview(db, args, ctx),
        requires_root=requires_root,
        result=result or {},
        transcript=transcript or [],
        model=model,
    )
    if status == "executed":
        action.executed_at = datetime.utcnow()
    db.add(action)
    db.commit()
    db.refresh(action)
    return action


def _run_loop(
    db: Session, messages: List[Dict[str, Any]], model: str,
    ctx: Dict[str, Any], steps: List[Dict[str, Any]], start_step: int = 0,
) -> Dict[str, Any]:
    """Tool-calling döngüsünü çalıştırır. pending bir mutating aksiyonda durur.

    Orkestrasyon LangGraph (agent.graph) üzerinden yürütülür; graph yüklenemezse
    aşağıdaki doğrudan döngüye (legacy) düşülür.
    """
    try:
        from app.services.agent.graph import run_agent_graph
        return run_agent_graph(db, messages, model, ctx, steps, start_step=start_step)
    except Exception as e:
        logger.error(f"[Agent] LangGraph döngüsü başarısız, legacy döngüye düşülüyor: {e}",
                     exc_info=True)
        return _run_loop_legacy(db, messages, model, ctx, steps, start_step=start_step)


def _run_loop_legacy(
    db: Session, messages: List[Dict[str, Any]], model: str,
    ctx: Dict[str, Any], steps: List[Dict[str, Any]], start_step: int = 0,
) -> Dict[str, Any]:
    """Tool-calling döngüsü — LangGraph kullanılamazsa devreye giren yedek."""
    specs = tool_mod.tool_specs()

    for step in range(start_step, MAX_STEPS):
        llm = chat_with_tools(model, messages, specs)
        if llm["error"]:
            return {"status": "error", "error": llm["error"], "steps": steps,
                    "answer": "", "session_id": ctx.get("session_id")}

        tool_calls = llm["tool_calls"]
        content = llm["content"]

        # Tool çağrısı yoksa → final yanıt
        if not tool_calls:
            return {"status": "done", "answer": content or "(boş yanıt)",
                    "steps": steps, "session_id": ctx.get("session_id")}

        # Asistanın tool isteğini transcript'e ekle
        messages.append({"role": "assistant", "content": content,
                         "tool_calls": [{"function": {"name": tc["name"], "arguments": tc["arguments"]}}
                                        for tc in tool_calls]})

        for tc in tool_calls:
            name = tc["name"]
            args = tc["arguments"] or {}

            # ask_user: shell tool değil — kullanıcıya seçenek sun ve duraklat.
            if name == "ask_user":
                question = args.get("question") or "Lütfen seçim yapın"
                options = args.get("options") or []
                allow_multiple = bool(args.get("allow_multiple"))
                action = AgentAction(
                    session_id=ctx.get("session_id"),
                    tool_name="ask_user",
                    arguments={"question": question, "options": options,
                               "allow_multiple": allow_multiple},
                    risk_level="read_only",
                    status="awaiting_input",
                    preview=question,
                    transcript=messages,
                    model=model,
                )
                db.add(action)
                db.commit()
                db.refresh(action)
                steps.append({"type": "question", "question": question, "options": options,
                              "allow_multiple": allow_multiple, "action_id": action.id})
                return {"status": "question", "action_id": action.id, "question": question,
                        "options": options, "allow_multiple": allow_multiple,
                        "steps": steps, "session_id": ctx.get("session_id")}

            tool = tool_mod.get_tool(name)

            if not tool:
                messages.append({"role": "tool", "name": name,
                                 "content": json.dumps({"error": f"Bilinmeyen tool: {name}"})})
                steps.append({"type": "error", "tool": name, "detail": "bilinmeyen tool"})
                continue

            if tool.risk_level == RiskLevel.READ_ONLY:
                result = tool.execute(db, args, ctx)

                # Permission denied + sudo şifresi yok → chat'te sor, beklet.
                if result.get("needs_sudo") and not ctx.get("sudo_password_override"):
                    srv = tool_mod.resolve_server(db, args, ctx)
                    action = AgentAction(
                        session_id=ctx.get("session_id"),
                        server_id=srv.id if srv else None,
                        tool_name="__needs_sudo__",
                        arguments={"tool": name, "args": args},
                        risk_level="read_only",
                        requires_root=True,
                        status="pending",
                        preview=f"Root yetkisi gerekiyor: {result.get('command', name)}",
                        transcript=messages,
                        model=model,
                    )
                    db.add(action); db.commit(); db.refresh(action)
                    steps.append({"type": "approval_required", "tool": name, "args": args,
                                  "preview": action.preview, "action_id": action.id,
                                  "guard": {}, "requires_root": True})
                    return {"status": "pending", "action_id": action.id,
                            "preview": action.preview, "tool": name,
                            "requires_root": True, "needs_sudo": True,
                            "steps": steps, "session_id": ctx.get("session_id")}

                _record_action(db, ctx, tool, args, "executed", result=result, model=model)
                messages.append({"role": "tool", "name": name,
                                 "content": json.dumps(result, ensure_ascii=False)[:8000]})
                steps.append({"type": "read_only", "tool": name, "args": args,
                              "preview": tool.preview(db, args, ctx), "result": result})
                continue

            # MUTATING → önce GUARD (safety classifier), sonra insan onayı.
            server = resolve_server(db, args, ctx)
            try:
                command_str = tool.build_command(args)
            except Exception as e:
                command_str = f"(komut oluşturulamadı: {e})"
            guard = guard_command(db, command_str, server.name if server else "?")

            if guard.get("decision") == "block":
                # Guard engelledi → çalıştırma, agent'a geri besle (alternatif üretebilir).
                _record_action(db, ctx, tool, args, "blocked",
                               result={"guard": guard}, model=model)
                messages.append({"role": "tool", "name": name,
                                 "content": json.dumps(
                                     {"blocked_by_guard": True, "reason": guard.get("reason", "")},
                                     ensure_ascii=False)})
                steps.append({"type": "blocked", "tool": name, "args": args,
                              "preview": (tool.preview(db, args, ctx)),
                              "guard": guard})
                continue

            # Guard izin verdi (veya devre dışı/degraded) → onay için dur.
            requires_root = _requires_root_prompt(db, tool, command_str)
            action = _record_action(
                db, ctx, tool, args, "pending",
                result={"guard": guard}, transcript=messages, model=model,
                requires_root=requires_root,
            )
            steps.append({"type": "approval_required", "tool": name, "args": args,
                          "preview": action.preview, "action_id": action.id,
                          "guard": guard, "requires_root": requires_root})
            return {"status": "pending", "action_id": action.id, "preview": action.preview,
                    "tool": name, "args": args, "guard": guard, "requires_root": requires_root,
                    "steps": steps, "session_id": ctx.get("session_id")}

    return {"status": "max_steps", "answer": "Maksimum adım sayısına ulaşıldı.",
            "steps": steps, "session_id": ctx.get("session_id")}


def start_agent(
    db: Session, user_message: str, *,
    session_id: Optional[int] = None,
    server_ids: Optional[List[int]] = None,
    model: Optional[str] = None,
    actor=None,
) -> Dict[str, Any]:
    server_ids = server_ids or []
    actor_name = _actor_name(actor)
    session_id = _ensure_session(db, session_id, user_message, server_ids)
    _save_msg(db, session_id, "user", user_message)

    record_audit(db, category="agent", action="agent.ask", actor=actor,
                 target_type="session", target_id=session_id,
                 server_id=server_ids[0] if server_ids else None,
                 summary=f"Agent'a soruldu: {user_message[:120]}")

    ctx = {
        "session_id": session_id,
        "server_ids": server_ids,
        "server_summary": _server_summary(db, server_ids),
        "actor_name": actor_name,
    }
    use_model = model or get_agent_model(db)
    messages = _build_initial_messages(user_message, ctx)
    result = _run_loop(db, messages, use_model, ctx, steps=[])
    _persist_final(db, result)
    return result


def continue_after_decision(db: Session, action: AgentAction, approved: bool,
                            decided_by: str = "user",
                            sudo_password: Optional[str] = None) -> Dict[str, Any]:
    """Onay/ret sonrası agent döngüsünü kaldığı yerden sürdürür.

    sudo_password: kullanıcının onay anında girdiği geçici root/sudo şifresi.
    Yalnızca bu çalıştırma için ctx üzerinden executor'a iletilir; DB'ye YAZILMAZ.
    """
    ctx = {
        "session_id": action.session_id,
        "server_ids": [action.server_id] if action.server_id else [],
        "server_summary": _server_summary(db, [action.server_id] if action.server_id else []),
        "sudo_password_override": (sudo_password or None),
        "actor_name": decided_by,
    }
    model = action.model or get_agent_model(db)
    messages: List[Dict[str, Any]] = list(action.transcript or [])
    tool = tool_mod.get_tool(action.tool_name)
    steps: List[Dict[str, Any]] = []

    action.decided_by = decided_by
    action.decided_at = datetime.utcnow()

    # ── __needs_sudo__ özel kolu ──────────────────────────────────────────────
    # READ_ONLY araç permission denied verdi, kullanıcı onay ekranında sudo
    # şifresini girdi. Şimdi aynı aracı sudo ile yeniden çalıştır.
    if action.tool_name == "__needs_sudo__":
        orig_tool_name = (action.arguments or {}).get("tool", "")
        orig_args = (action.arguments or {}).get("args", {})
        orig_tool = tool_mod.get_tool(orig_tool_name)

        if not approved:
            action.status = "rejected"; db.commit()
            record_audit(db, category="agent", action="agent.reject", status="rejected",
                         actor=decided_by, target_type="action", target_id=action.id,
                         summary=f"Sudo reddedildi: {orig_tool_name}")
            messages.append({"role": "tool", "name": orig_tool_name,
                             "content": json.dumps({"rejected": True, "note": "Sudo reddedildi."})})
            result = _run_loop(db, messages, model, ctx, steps=steps,
                               start_step=_step_estimate(messages))
            _persist_final(db, result)
            return result

        if not orig_tool:
            action.status = "failed"; db.commit()
            return {"status": "error", "error": "Orijinal araç bulunamadı", "steps": steps}

        record_audit(db, category="agent", action="agent.sudo_granted", actor=decided_by,
                     target_type="action", target_id=action.id, server_id=action.server_id,
                     summary=f"Sudo onaylandı: {orig_tool_name}")

        # sudo_password_override ctx'e eklendi → executor otomatik kullanır
        exec_result = orig_tool.execute(db, orig_args, ctx)
        action.status = "executed" if exec_result.get("ok") else "failed"
        action.result = exec_result
        action.executed_at = datetime.utcnow()
        db.commit()

        record_audit(db, category="agent", action="agent.execute",
                     status="success" if exec_result.get("ok") else "failure",
                     actor=decided_by, server_id=action.server_id,
                     summary=f"Sudo ile çalıştırıldı: {orig_tool_name}",
                     detail={"ok": exec_result.get("ok"), "ran_as_sudo": exec_result.get("ran_as_sudo")})

        messages.append({"role": "tool", "name": orig_tool_name,
                         "content": json.dumps(exec_result, ensure_ascii=False)[:8000]})
        steps.append({"type": "executed", "tool": orig_tool_name,
                      "preview": f"sudo: {orig_tool_name}", "result": exec_result})
        final_result = _run_loop(db, messages, model, ctx, steps=steps,
                                 start_step=_step_estimate(messages))
        _persist_final(db, final_result)
        return final_result
    # ─────────────────────────────────────────────────────────────────────────

    if not approved:
        action.status = "rejected"
        db.commit()
        record_audit(db, category="agent", action="agent.reject", status="rejected",
                     actor=decided_by, target_type="action", target_id=action.id,
                     server_id=action.server_id,
                     summary=f"Reddedildi: {action.tool_name} — {action.preview or ''}"[:200])
        messages.append({"role": "tool", "name": action.tool_name,
                         "content": json.dumps({"rejected": True,
                                                "note": "Kullanıcı bu işlemi reddetti."})})
        steps.append({"type": "rejected", "tool": action.tool_name, "preview": action.preview})
        result = _run_loop(db, messages, model, ctx, steps=steps,
                           start_step=_step_estimate(messages))
        _persist_final(db, result)
        return result

    # Onaylandı → tool'u çalıştır
    if not tool:
        action.status = "failed"
        action.result = {"error": "tool bulunamadı"}
        db.commit()
        return {"status": "error", "error": "Tool bulunamadı", "steps": steps,
                "session_id": action.session_id}

    record_audit(db, category="agent", action="agent.approve", actor=decided_by,
                 target_type="action", target_id=action.id, server_id=action.server_id,
                 summary=f"Onaylandı: {action.tool_name} — {action.preview or ''}"[:200])

    result = tool.execute(db, action.arguments or {}, ctx)
    action.status = "executed" if result.get("ok") else "failed"
    action.result = result
    action.executed_at = datetime.utcnow()
    db.commit()

    record_audit(db, category="agent", action="agent.execute",
                 status="success" if result.get("ok") else "failure",
                 actor=decided_by, target_type="action", target_id=action.id,
                 server_id=action.server_id,
                 summary=f"Çalıştırıldı: {action.tool_name}",
                 detail={"ok": result.get("ok"), "error": result.get("error")})

    messages.append({"role": "tool", "name": action.tool_name,
                     "content": json.dumps(result, ensure_ascii=False)[:8000]})
    steps.append({"type": "executed", "tool": action.tool_name,
                  "preview": action.preview, "result": result})
    decision_result = _run_loop(db, messages, model, ctx, steps=steps,
                                start_step=_step_estimate(messages))
    _persist_final(db, decision_result)
    return decision_result


def continue_after_answer(db: Session, action: AgentAction, answer,
                          decided_by: str = "user") -> Dict[str, Any]:
    """Kullanıcı ask_user sorusuna yanıt verdikten sonra döngüyü sürdürür."""
    ctx = {
        "session_id": action.session_id,
        "server_ids": [action.server_id] if action.server_id else [],
        "server_summary": _server_summary(db, [action.server_id] if action.server_id else []),
        "actor_name": decided_by,
    }
    model = action.model or get_agent_model(db)
    messages: List[Dict[str, Any]] = list(action.transcript or [])

    action.status = "answered"
    action.decided_by = decided_by
    action.decided_at = datetime.utcnow()
    action.result = {"selected": answer}
    db.commit()

    record_audit(db, category="agent", action="agent.answer", actor=decided_by,
                 target_type="action", target_id=action.id, server_id=action.server_id,
                 summary=f"Soru yanıtlandı: {str(answer)[:120]}")

    messages.append({"role": "tool", "name": "ask_user",
                     "content": json.dumps({"selected": answer}, ensure_ascii=False)})
    steps = [{"type": "answered", "question": (action.arguments or {}).get("question"),
              "selected": answer}]
    result = _run_loop(db, messages, model, ctx, steps=steps,
                       start_step=_step_estimate(messages))
    _persist_final(db, result)
    return result


def _step_estimate(messages: List[Dict[str, Any]]) -> int:
    """Transcript'teki asistan tur sayısını kabaca adım sayar (MAX_STEPS koruması için)."""
    return sum(1 for m in messages if m.get("role") == "assistant")
