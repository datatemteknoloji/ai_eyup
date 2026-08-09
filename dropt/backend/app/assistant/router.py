from __future__ import annotations

import json
import re
from typing import Any

from sqlmodel import Session

from app.assistant.analyze import build_analysis
from app.assistant.catalog import catalog_for_prompt, get_capability, list_capabilities
from app.assistant.history import context_for_prompt
from app.assistant.ollama_client import build_direct_base, chat_json, normalize_base_url
from app.assistant.pending import clear_pending, get_pending, set_pending
from app.assistant.servers import (
    build_deep_link,
    classify_servers_in_message,
    resolve_servers_in_message,
)
from app.services import assistant_settings as aset

SYSTEM_PROMPT = """Sen Dropt Ops Portal operasyon asistanısın.
Görevin: kullanıcı talebini analiz edip YALNIZCA aşağıdaki katalogdaki operasyonlardan birine yönlendirmek.
ASLA job create/apply veya yazma aksiyonu yapma / yapma iddiasında bulunma.
Readonly envanter / portal DB sorgusu backend tarafından ayrıca eklenir.

Portal SORGU örnekleri → doğru operation_id:
- IP aralığı / envanter listesi / ready-unreachable → servers
- job durumu / failed job / job #68 → jobs
- audit / kim ne yaptı / talep audit → audit
- portal kullanıcı listesi (admin) → portal_users
- paket keyword/repo (admin) → package_repos
- SMTP / app adı / Centrify ayarları → settings_info
- izinli sysctl key / sudo şablon / vlan pool → ops_catalog

Ops yazma yönlendirme (katalog id birebir):
- ASM / oracleasm / LUN / multipath createdisk → asm_add_disk
- IP değiştir / ana IP / gateway değiştir → network_ip_change
- Yeni NIC / bond / ethernet IP → network_add
- VLAN ekle → vlan_add
- Hostname / FQDN / rename → hostname
- FS büyüt / LV extend → filesystem_extend; yeni FS → filesystem_create; böl → filesystem_organize
- Paket / dnf / docker kur → packages; servis start/stop → services

Önceki diyalog ve "bekleyen operasyon" varsa kısa cevapları (sadece hostname gibi) O operasyona bağla.
Kullanıcı yalnızca sunucu adı yazdıysa operation_id'yi servers yapma; bekleyen ops'u koru (envanter sorusu değilse).
"X gibi / benzer / referans" denilen sunucu REFERANStir; asıl işlem sunucusu HEDEFTir.

Emin değilsen operation_id null bırak.
clarifying_questions YALNIZCA: ops belirsiz, hedef sunucu yok (sunucu gerektiren ops), teknik alan eksik.
Envanter/IP/job/audit SORULARINDA sunucu sorma.
YASAK sorular: başarılı oldu mu, yardımcı oldu mu, devam edeyim mi.
JSON dışında hiçbir şey yazma.
ÖNEMLİ: Operasyon adını ASLA uydurma. summary_tr içinde title_tr birebir.

Kataloğ:
{catalog}

Yanıt şeması (JSON):
{{
  "operation_id": "servers veya null",
  "confidence": 0.0,
  "summary_tr": "kısa yönlendirme (title_tr birebir)",
  "checklist_tr": ["..."],
  "clarifying_questions": [],
  "out_of_scope_note": null
}}
"""

_BANNED_Q = re.compile(
    r"başarılı|yardımcı oldu|devam edeyim|şöyle mi|böyle mi|emin misin|doğru mu\s*\?|"
    r"was it successful|did that help|shall i continue|does that sound",
    re.IGNORECASE,
)

_OPS_NO_SERVER = frozenset(
    {
        "jobs",
        "servers",
        "audit",
        "portal_users",
        "package_repos",
        "settings_info",
        "ops_catalog",
    }
)


def _normalize(text: str) -> str:
    t = (text or "").lower()
    t = t.replace("ı", "i").replace("ğ", "g").replace("ü", "u")
    t = t.replace("ş", "s").replace("ö", "o").replace("ç", "c")
    return t


def filter_questions(questions: list[str] | None) -> list[str]:
    out: list[str] = []
    for q in questions or []:
        s = str(q).strip()
        if not s or _BANNED_Q.search(s):
            continue
        out.append(s)
    return out[:3]


def score_catalog(message: str) -> list[tuple[float, dict[str, Any]]]:
    text = _normalize(message)
    scored: list[tuple[float, dict[str, Any]]] = []
    for cap in list_capabilities():
        score = 0.0
        for kw in cap.get("keywords") or []:
            k = _normalize(str(kw))
            if not k:
                continue
            if k in text:
                score += 2.5 + min(len(k), 12) * 0.05
        for ex in cap.get("example_intents") or []:
            tokens = [w for w in re.split(r"\W+", _normalize(str(ex))) if len(w) > 3]
            hit = sum(1 for w in tokens if w in text)
            if tokens:
                score += (hit / len(tokens)) * 1.5
        if score > 0:
            scored.append((score, cap))
    scored.sort(key=lambda x: -x[0])
    return scored


def _attach_servers(result: dict[str, Any], session: Session, message: str) -> dict[str, Any]:
    classified = classify_servers_in_message(session, message)
    targets = list(classified.get("targets") or [])
    references = list(classified.get("references") or [])
    ambiguous = bool(classified.get("ambiguous"))

    result["server_ids"] = [int(m["id"]) for m in targets]
    result["server_hostnames"] = [str(m.get("hostname") or "") for m in targets]
    result["reference_server_ids"] = [int(m["id"]) for m in references]
    result["reference_hostnames"] = [str(m.get("hostname") or "") for m in references]
    result["deep_link"] = build_deep_link(result.get("route"), targets if not ambiguous else [])

    questions = list(result.get("clarifying_questions") or [])
    # Drop stale "multiple servers" questions if we successfully split target/ref
    if references and targets and not ambiguous:
        questions = [
            q
            for q in questions
            if "birden fazla sunucu" not in (q or "").lower()
            and "hangisi için" not in (q or "").lower()
        ]

    if ambiguous:
        names = ", ".join(result["server_hostnames"][:5])
        q = f"Birden fazla hedef sunucu eşleşti ({names}). Hangisi için işlem yapılacak?"
        if q not in questions:
            questions.insert(0, q)
        result["deep_link"] = result.get("route")
    elif not targets and result.get("operation_id") and result.get("operation_id") not in _OPS_NO_SERVER:
        if not any("sunucu" in _normalize(q) for q in questions):
            questions.append("İşlem hangi sunucu için? (hostname yazın)")
    result["clarifying_questions"] = filter_questions(questions)
    return result


def _enrich_analysis(
    result: dict[str, Any],
    session: Session,
    message: str,
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    """Readonly probe + portal DB query; never blocks routing on failure."""
    try:
        from app.assistant.servers import load_server_index
        from app.models.user import User

        classified = classify_servers_in_message(session, message)
        targets = list(classified.get("targets") or [])
        references = list(classified.get("references") or [])
        idx = {int(r["id"]): r for r in load_server_index(session)}

        if result.get("server_ids"):
            targets = [idx[i] for i in result["server_ids"] if i in idx] or targets
        if result.get("reference_server_ids"):
            references = [idx[i] for i in result["reference_server_ids"] if i in idx] or references
        elif classified.get("references"):
            result["reference_server_ids"] = [int(m["id"]) for m in references]
            result["reference_hostnames"] = [str(m.get("hostname") or "") for m in references]

        user = session.get(User, user_id) if user_id is not None else None
        analysis = build_analysis(
            session,
            operation_id=result.get("operation_id"),
            message=message,
            targets=targets,
            references=references,
            user=user,
        )
        result["analysis_tr"] = analysis.get("analysis_tr") or ""
        result["analysis_probed"] = bool(analysis.get("probed"))
        if analysis.get("probe_kind"):
            result["analysis_probe"] = analysis["probe_kind"]
    except Exception as exc:  # noqa: BLE001
        result["analysis_tr"] = f"Readonly analiz atlandı: {exc}"[:240]
        result["analysis_probed"] = False
    return result


def _finalize(
    result: dict[str, Any],
    session: Session,
    message: str,
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    attached = _attach_servers(result, session, message)
    return _enrich_analysis(attached, session, message, user_id=user_id)


def _result_from_cap(
    cap: dict[str, Any] | None,
    *,
    confidence: float,
    summary: str | None = None,
    questions: list[str] | None = None,
    source: str,
) -> dict[str, Any]:
    base = {
        "reference_server_ids": [],
        "reference_hostnames": [],
        "analysis_tr": "",
        "analysis_probed": False,
    }
    if not cap:
        return {
            **base,
            "operation_id": None,
            "title_tr": None,
            "route": None,
            "deep_link": None,
            "server_ids": [],
            "server_hostnames": [],
            "confidence": confidence,
            "summary_tr": summary
            or "Talebi netleştiremedim. İstediğiniz işlemi ve sunucu hostname’ini yazar mısınız?",
            "checklist_tr": [],
            "clarifying_questions": filter_questions(questions)
            or ["İstediğiniz işlem nedir? (ör. FileSystem Management, ASM disk ekle, VLAN ekle)"],
            "out_of_scope_note": None,
            "required_inputs": [],
            "source": source,
        }
    return {
        **base,
        "operation_id": cap.get("id"),
        "title_tr": cap.get("title_tr"),
        "route": cap.get("route"),
        "deep_link": cap.get("route"),
        "server_ids": [],
        "server_hostnames": [],
        "confidence": round(min(1.0, confidence), 3),
        "summary_tr": summary or cap.get("summary_tr") or "",
        "checklist_tr": list(cap.get("checklist_tr") or []),
        "clarifying_questions": filter_questions(questions),
        "out_of_scope_note": cap.get("out_of_scope_tr"),
        "required_inputs": list(cap.get("required_inputs") or []),
        "source": source,
    }


def route_by_catalog(message: str) -> dict[str, Any]:
    from app.assistant.queries import parse_ipv4_filter, parse_job_id

    # Strong shortcuts for portal Q&A (before fuzzy keyword scoring)
    if parse_ipv4_filter(message):
        cap = get_capability("servers")
        return _result_from_cap(
            cap,
            confidence=0.93,
            summary="Portal envanterinde IP filtresine göre sunucu listesi.",
            source="catalog",
        )
    jid = parse_job_id(message)
    if jid is not None:
        cap = get_capability("jobs")
        return _result_from_cap(
            cap,
            confidence=0.92,
            summary=f"Job #{jid} durumu / özeti.",
            source="catalog",
        )

    scored = score_catalog(message)
    if not scored:
        return _result_from_cap(None, confidence=0.0, source="catalog")
    best_score, best = scored[0]
    conf = min(0.95, best_score / 8.0)
    second = scored[1][0] if len(scored) > 1 else 0.0
    if best_score < 2.0:
        return _result_from_cap(
            None,
            confidence=conf,
            source="catalog",
            questions=["İstediğiniz işlem nedir? (ör. FileSystem Management, ASM disk ekle)"],
        )
    if second > 0 and best_score - second < 1.2:
        alts = [scored[0][1].get("title_tr"), scored[1][1].get("title_tr")]
        return _result_from_cap(
            best,
            confidence=max(0.35, conf - 0.15),
            summary=(
                f"Birden fazla olası işlem: {alts[0]} veya {alts[1]}. "
                f"Şimdilik en yakın aday: {best.get('title_tr')}."
            ),
            questions=[f"Doğru işlem {alts[0]} mı, {alts[1]} mi?"],
            source="catalog",
        )
    return _result_from_cap(
        best,
        confidence=conf,
        summary=f"Bu talep için önerilen operasyon: {best.get('title_tr')}.",
        source="catalog",
    )


def _parse_llm_json(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


def resolve_ollama_base(session: Session) -> tuple[str, str | None]:
    mode = aset.get_assistant_ollama_mode(session)
    if mode == "gateway":
        base = normalize_base_url(aset.get_assistant_gateway_url(session))
        key = aset.get_assistant_gateway_api_key(session)
        return base, key
    base = build_direct_base(
        aset.get_assistant_direct_host(session),
        aset.get_assistant_direct_port(session),
    )
    return base, None


def _is_dismiss_message(message: str) -> bool:
    text = _normalize(message).strip()
    if not text or len(text) > 60:
        return False
    text = re.sub(r"[!?.…,]+", " ", text)
    tokens = [t for t in text.split() if t]
    if not tokens or len(tokens) > 6:
        return False
    dismiss_tokens = {
        "tesekkur",
        "tesekkurler",
        "sagol",
        "eyvallah",
        "tamam",
        "tamm",
        "tm",
        "ok",
        "okay",
        "okey",
        "peki",
        "rica",
        "ederim",
        "yok",
        "hayir",
        "iptal",
        "vazgec",
        "et",
        "selam",
        "merhaba",
        "hey",
        "hi",
        "hello",
        "gunaydin",
        "iyi",
        "gunler",
        "bitti",
        "yeter",
        "kapat",
        "temizle",
        "clear",
        "thanks",
        "thank",
        "you",
        "thx",
        "bye",
        "gorusuruz",
    }
    return all(t in dismiss_tokens for t in tokens)


def _looks_like_hostname_reply(message: str, session: Session) -> bool:
    words = [w for w in re.split(r"\s+", (message or "").strip()) if w]
    if not words or len(words) > 4 or len(message) > 64:
        return False
    return bool(resolve_servers_in_message(session, message).get("matches"))


def _should_use_pending(
    message: str,
    pending: dict[str, Any] | None,
    catalog_result: dict[str, Any],
    session: Session,
) -> bool:
    if not pending or not pending.get("operation_id"):
        return False
    if _is_dismiss_message(message):
        return False

    pending_op = str(pending["operation_id"])
    cat_op = catalog_result.get("operation_id")
    cat_conf = float(catalog_result.get("confidence") or 0)

    # New intent for a different op → leave pending
    if cat_op and cat_op != pending_op and cat_op != "servers" and cat_conf >= 0.35:
        return False

    # Hostname answer while waiting for server
    if _looks_like_hostname_reply(message, session):
        if not cat_op or cat_op in ("servers", pending_op) or cat_conf < 0.45:
            return True
        return False

    # Same op with more detail
    if cat_op == pending_op and cat_conf >= 0.35:
        return True

    return False


def _route_with_pending(
    session: Session,
    message: str,
    pending: dict[str, Any],
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    cap = get_capability(str(pending["operation_id"]))
    hint = (pending.get("hint") or "").strip()
    title = (cap or {}).get("title_tr") or pending["operation_id"]
    summary = f"Önceki talebe devam: {title}."
    if hint:
        summary = f"{summary} ({hint[:120]})"
    out = _result_from_cap(
        cap,
        confidence=0.92,
        summary=summary,
        source="pending",
    )
    # Carry reference hosts from original request into this follow-up
    ref_ids = pending.get("reference_ids") or []
    ref_hosts = pending.get("reference_hostnames") or []
    if ref_ids:
        out["reference_server_ids"] = [int(x) for x in ref_ids]
        out["reference_hostnames"] = [str(x) for x in ref_hosts]
    out = _finalize(out, session, message, user_id=user_id)
    # If follow-up message had no refs, restore pending refs for analysis display
    if ref_ids and not out.get("reference_server_ids"):
        out["reference_server_ids"] = [int(x) for x in ref_ids]
        out["reference_hostnames"] = [str(x) for x in ref_hosts]
        out = _enrich_analysis(out, session, hint or message, user_id=user_id)
    return out


def _dismiss_result() -> dict[str, Any]:
    return {
        "operation_id": None,
        "title_tr": None,
        "route": None,
        "deep_link": None,
        "server_ids": [],
        "server_hostnames": [],
        "reference_server_ids": [],
        "reference_hostnames": [],
        "confidence": 0.0,
        "summary_tr": "Rica ederim. Yeni bir işlem için talebi yazmanız yeterli.",
        "checklist_tr": [],
        "clarifying_questions": [],
        "out_of_scope_note": None,
        "required_inputs": [],
        "analysis_tr": "",
        "source": "dismiss",
    }


def _update_pending_after(user_id: int | None, result: dict[str, Any], message: str) -> None:
    if user_id is None:
        return
    if result.get("source") == "dismiss" or _is_dismiss_message(message):
        clear_pending(user_id)
        return
    op = result.get("operation_id")
    questions = result.get("clarifying_questions") or []
    needs_more = bool(questions) or (
        op
        and op not in _OPS_NO_SERVER
        and not (result.get("server_ids") or [])
    )
    if op and needs_more:
        existing = get_pending(user_id)
        words = [w for w in re.split(r"\s+", (message or "").strip()) if w]
        if existing and existing.get("hint") and len(words) <= 4 and len(message) <= 64:
            hint = str(existing["hint"])
        else:
            hint = message[:200]
        ref_ids = list(result.get("reference_server_ids") or [])
        ref_hosts = list(result.get("reference_hostnames") or [])
        if not ref_ids and existing:
            ref_ids = list(existing.get("reference_ids") or [])
            ref_hosts = list(existing.get("reference_hostnames") or [])
        set_pending(
            user_id,
            str(op),
            hint=hint,
            reference_ids=ref_ids,
            reference_hostnames=ref_hosts,
        )
    else:
        clear_pending(user_id)

def _fix_summary_titles(summary: str | None, resolved_cap: dict[str, Any] | None) -> str | None:
    if not summary or not resolved_cap or not resolved_cap.get("title_tr"):
        return summary
    for wrong in (
        "Dosya sistemi / LVM",
        "Dosya sistemi",
        "Filesystem / LVM",
        "Systemd servis",
        "Paket kurulum",
        "Mail (sendmail) yapılandır",
        "Log toplama",
        "Web terminal",
        "Sunucu envanteri",
        "İşler (Jobs)",
        "Path sahibi / izin",
        "VLAN arayüzü ekle",
        "Kernel / HugePages (sysctl)",
        "Security limits",
    ):
        if wrong in summary and wrong != resolved_cap.get("title_tr"):
            summary = summary.replace(wrong, str(resolved_cap["title_tr"]))
    return summary


async def route_message(
    session: Session,
    message: str,
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    message = (message or "").strip()
    if not message:
        raise ValueError("Mesaj boş olamaz")
    if not aset.is_assistant_enabled(session):
        raise ValueError("Asistan devre dışı")

    pending = get_pending(user_id) if user_id is not None else None
    catalog_result = route_by_catalog(message)

    # Thanks / selam / tamam → drop sticky pending and acknowledge
    if _is_dismiss_message(message):
        if user_id is not None:
            clear_pending(user_id)
        out = _dismiss_result()
        return out

    # Inventory IP / job-id shortcuts: prefer catalog over sticky pending of unrelated ops
    from app.assistant.queries import parse_ipv4_filter, parse_job_id, is_db_query_op

    if parse_ipv4_filter(message) or parse_job_id(message) is not None:
        if pending and not is_db_query_op(str(pending.get("operation_id") or "")):
            clear_pending(user_id) if user_id is not None else None
            pending = None
        out = _finalize({**catalog_result, "source": "catalog"}, session, message, user_id=user_id)
        _update_pending_after(user_id, out, message)
        return out

    if pending and _should_use_pending(message, pending, catalog_result, session):
        out = _route_with_pending(session, message, pending, user_id=user_id)
        _update_pending_after(user_id, out, message)
        return out

    # New intent → drop stale pending
    if (
        user_id is not None
        and pending
        and catalog_result.get("operation_id")
        and catalog_result.get("operation_id") != pending.get("operation_id")
        and float(catalog_result.get("confidence") or 0) >= 0.35
        and catalog_result.get("operation_id") != "servers"
    ):
        clear_pending(user_id)
        pending = None

    # Portal DB Q&A with solid catalog match → skip LLM (inventory/jobs/audit/…)
    cat_op = catalog_result.get("operation_id")
    cat_conf = float(catalog_result.get("confidence") or 0)
    if (
        is_db_query_op(str(cat_op) if cat_op else None)
        and cat_conf >= 0.45
        and not (catalog_result.get("clarifying_questions") or [])
    ):
        if pending and not is_db_query_op(str(pending.get("operation_id") or "")):
            if user_id is not None:
                clear_pending(user_id)
            pending = None
        out = _finalize({**catalog_result, "source": "catalog"}, session, message, user_id=user_id)
        _update_pending_after(user_id, out, message)
        return out

    model = aset.get_assistant_model(session)
    base, api_key = resolve_ollama_base(session)

    if not base or not model:
        out = _finalize({**catalog_result, "source": "catalog"}, session, message, user_id=user_id)
        _update_pending_after(user_id, out, message)
        return out

    system = SYSTEM_PROMPT.format(catalog=catalog_for_prompt())
    history_txt = context_for_prompt(session, user_id) if user_id is not None else ""
    pending_line = ""
    if pending and pending.get("operation_id"):
        hint = str(pending.get("hint") or "").strip()
        hint_part = f" (ipucu: {hint})" if hint else ""
        pending_line = (
            f"\nBekleyen operasyon: {pending['operation_id']}{hint_part}\n"
            "Kısa hostname cevabında bu operasyonu koru; servers seçme.\n"
        )
    user = ""
    if history_txt:
        user += f"Önceki diyalog:\n{history_txt}\n\n"
    user += pending_line
    user += f"Kullanıcı talebi:\n{message}"

    try:
        raw = await chat_json(base, model, system, user, api_key=api_key)
        data = _parse_llm_json(raw)
        if not data:
            catalog_result["source"] = "catalog_fallback"
            out = _finalize(catalog_result, session, message, user_id=user_id)
            _update_pending_after(user_id, out, message)
            return out

        op_id = data.get("operation_id")
        cap = get_capability(str(op_id)) if op_id else None
        conf = float(data.get("confidence") or 0)
        if conf > 1:
            conf = conf / 100.0
        conf = max(0.0, min(1.0, conf))

        # LLM wrongly picked servers while we still had pending and hostname in message
        if (
            pending
            and str(op_id) == "servers"
            and resolve_servers_in_message(session, message).get("matches")
        ):
            out = _route_with_pending(session, message, pending, user_id=user_id)
            _update_pending_after(user_id, out, message)
            return out

        if op_id and not cap:
            out = _finalize({**catalog_result, "source": "catalog_fallback"}, session, message, user_id=user_id)
            _update_pending_after(user_id, out, message)
            return out

        if conf < 0.35 and not cap:
            out = _result_from_cap(
                None,
                confidence=conf,
                summary=str(data.get("summary_tr") or "") or None,
                questions=list(data.get("clarifying_questions") or []),
                source="llm",
            )
            out = _finalize(out, session, message, user_id=user_id)
            _update_pending_after(user_id, out, message)
            return out

        resolved_cap = cap or (
            get_capability(str(catalog_result["operation_id"]))
            if catalog_result.get("operation_id")
            else None
        )
        summary = _fix_summary_titles(str(data.get("summary_tr") or "") or None, resolved_cap)
        checklist = list(data.get("checklist_tr") or [])
        questions = filter_questions(list(data.get("clarifying_questions") or []))
        out = _result_from_cap(
            resolved_cap,
            confidence=conf if cap else catalog_result.get("confidence") or conf,
            summary=summary,
            questions=questions,
            source="llm",
        )
        if resolved_cap:
            out["title_tr"] = resolved_cap.get("title_tr")
            out["route"] = resolved_cap.get("route")
        if checklist:
            out["checklist_tr"] = checklist
        note = data.get("out_of_scope_note")
        if note:
            out["out_of_scope_note"] = str(note)
        if (not out.get("operation_id")) and catalog_result.get("operation_id") and (
            catalog_result.get("confidence") or 0
        ) >= 0.45:
            out = _finalize({**catalog_result, "source": "catalog_fallback"}, session, message, user_id=user_id)
            _update_pending_after(user_id, out, message)
            return out
        out = _finalize(out, session, message, user_id=user_id)
        _update_pending_after(user_id, out, message)
        return out
    except Exception as exc:  # noqa: BLE001
        catalog_result["source"] = "catalog_fallback"
        catalog_result["summary_tr"] = (
            f"{catalog_result.get('summary_tr') or ''} "
            f"(Model şu an kullanılamadı: {exc}; katalog yönlendirmesi.)"
        ).strip()
        out = _finalize(catalog_result, session, message, user_id=user_id)
        _update_pending_after(user_id, out, message)
        return out
