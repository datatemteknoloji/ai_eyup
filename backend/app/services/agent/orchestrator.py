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

from app.core.config import get_agent_model
from app.models.agent_action import AgentAction
from app.services.agent import tools as tool_mod
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


def _server_summary(db: Session, server_ids: List[int]) -> str:
    from app.models.server import Server
    q = db.query(Server).filter(Server.ai_ready == True)  # noqa: E712
    if server_ids:
        q = q.filter(Server.id.in_(server_ids))
    lines = []
    for s in q.all():
        lines.append(f"- {s.name} ({s.ip_address}) OS={s.os_version or s.os_type or 'Linux'} durum={s.status}")
    return "\n".join(lines)


def _record_action(
    db: Session, ctx: Dict[str, Any], tool: tool_mod.Tool,
    args: Dict[str, Any], status: str, result: Optional[Dict] = None,
    transcript: Optional[List] = None, model: str = "",
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
    """Tool-calling döngüsünü çalıştırır. pending bir mutating aksiyonda durur."""
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
            action = _record_action(
                db, ctx, tool, args, "pending",
                result={"guard": guard}, transcript=messages, model=model,
            )
            steps.append({"type": "approval_required", "tool": name, "args": args,
                          "preview": action.preview, "action_id": action.id, "guard": guard})
            return {"status": "pending", "action_id": action.id, "preview": action.preview,
                    "tool": name, "args": args, "guard": guard, "steps": steps,
                    "session_id": ctx.get("session_id")}

    return {"status": "max_steps", "answer": "Maksimum adım sayısına ulaşıldı.",
            "steps": steps, "session_id": ctx.get("session_id")}


def start_agent(
    db: Session, user_message: str, *,
    session_id: Optional[int] = None,
    server_ids: Optional[List[int]] = None,
    model: Optional[str] = None,
) -> Dict[str, Any]:
    server_ids = server_ids or []
    ctx = {
        "session_id": session_id,
        "server_ids": server_ids,
        "server_summary": _server_summary(db, server_ids),
    }
    use_model = model or get_agent_model(db)
    messages = _build_initial_messages(user_message, ctx)
    return _run_loop(db, messages, use_model, ctx, steps=[])


def continue_after_decision(db: Session, action: AgentAction, approved: bool,
                            decided_by: str = "user") -> Dict[str, Any]:
    """Onay/ret sonrası agent döngüsünü kaldığı yerden sürdürür."""
    ctx = {
        "session_id": action.session_id,
        "server_ids": [action.server_id] if action.server_id else [],
        "server_summary": _server_summary(db, [action.server_id] if action.server_id else []),
    }
    model = action.model or get_agent_model(db)
    messages: List[Dict[str, Any]] = list(action.transcript or [])
    tool = tool_mod.get_tool(action.tool_name)
    steps: List[Dict[str, Any]] = []

    action.decided_by = decided_by
    action.decided_at = datetime.utcnow()

    if not approved:
        action.status = "rejected"
        db.commit()
        messages.append({"role": "tool", "name": action.tool_name,
                         "content": json.dumps({"rejected": True,
                                                "note": "Kullanıcı bu işlemi reddetti."})})
        steps.append({"type": "rejected", "tool": action.tool_name, "preview": action.preview})
        return _run_loop(db, messages, model, ctx, steps=steps,
                         start_step=_step_estimate(messages))

    # Onaylandı → tool'u çalıştır
    if not tool:
        action.status = "failed"
        action.result = {"error": "tool bulunamadı"}
        db.commit()
        return {"status": "error", "error": "Tool bulunamadı", "steps": steps,
                "session_id": action.session_id}

    result = tool.execute(db, action.arguments or {}, ctx)
    action.status = "executed" if result.get("ok") else "failed"
    action.result = result
    action.executed_at = datetime.utcnow()
    db.commit()

    messages.append({"role": "tool", "name": action.tool_name,
                     "content": json.dumps(result, ensure_ascii=False)[:8000]})
    steps.append({"type": "executed", "tool": action.tool_name,
                  "preview": action.preview, "result": result})
    return _run_loop(db, messages, model, ctx, steps=steps,
                     start_step=_step_estimate(messages))


def continue_after_answer(db: Session, action: AgentAction, answer) -> Dict[str, Any]:
    """Kullanıcı ask_user sorusuna yanıt verdikten sonra döngüyü sürdürür."""
    ctx = {
        "session_id": action.session_id,
        "server_ids": [action.server_id] if action.server_id else [],
        "server_summary": _server_summary(db, [action.server_id] if action.server_id else []),
    }
    model = action.model or get_agent_model(db)
    messages: List[Dict[str, Any]] = list(action.transcript or [])

    action.status = "answered"
    action.decided_at = datetime.utcnow()
    action.result = {"selected": answer}
    db.commit()

    messages.append({"role": "tool", "name": "ask_user",
                     "content": json.dumps({"selected": answer}, ensure_ascii=False)})
    steps = [{"type": "answered", "question": (action.arguments or {}).get("question"),
              "selected": answer}]
    return _run_loop(db, messages, model, ctx, steps=steps,
                     start_step=_step_estimate(messages))


def _step_estimate(messages: List[Dict[str, Any]]) -> int:
    """Transcript'teki asistan tur sayısını kabaca adım sayar (MAX_STEPS koruması için)."""
    return sum(1 for m in messages if m.get("role") == "assistant")
