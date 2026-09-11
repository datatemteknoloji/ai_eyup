"""Düşük güven module planına LLM ikinci fikir — tam classifier değil.

Yalnız eşik/tie/zayıf sinyal. Mevcut planı ezmez:
- auto_explore / esnaf: daraltılamaz (disk→virt+linux kasıtlı)
- auto_multi_tie: bağlı çiftin alt kümesi seçilebilir
- diğer: birleşim (ekle, yerine yazma)
Devre açıksa veya parse/timeout olursa keyword planı kalır; sohbet 503 olmaz.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional, Sequence, Tuple

from app.services.module_orchestrator import (
    ALL_MODULES,
    ModulePlan,
    plan_with_modules,
)

logger = logging.getLogger(__name__)

# _CONF_MULTI=0.72 / _CONF_SINGLE=0.78 üstü LLM yok
HINT_CONF_MAX = 0.70
_TIMEOUT_SEC = 8.0
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

_SYSTEM = (
    "Altyapı sohbet yönlendiricisisin. Yalnız JSON yaz, başka metin yok. "
    "İzinli modüller: linux, windows, virt, openshift, exadata. "
    "Emin değilsen birden fazla yaz; tek kelimeyle (disk/cpu) tek domaine kilitleme."
)

_USER_TMPL = (
    "Soru: {question}\n"
    "Keyword plan: modules={modules} reason={reason} confidence={conf:.2f}\n"
    'Yanıt şekli: {{"modules":["virt","linux"],"reason":"kısa"}}'
)


def should_ask_route_hint(plan: ModulePlan) -> bool:
    if plan.reason in ("skip_ctx", "empty"):
        return False
    if plan.reason.startswith("esnaf_"):
        return False
    return float(plan.confidence or 0) <= HINT_CONF_MAX


def parse_hinted_modules(raw: str) -> Tuple[str, ...]:
    text = (raw or "").strip()
    if not text:
        return ()
    blob = text
    m = _JSON_RE.search(text)
    if m:
        blob = m.group(0)
    try:
        data = json.loads(blob)
    except Exception:
        return ()
    items = data.get("modules") if isinstance(data, dict) else data
    if isinstance(items, str):
        items = [items]
    if not isinstance(items, list):
        return ()
    allowed = set(ALL_MODULES)
    out: list = []
    for item in items:
        name = str(item or "").strip().lower()
        if name == "vcenter" or name == "vmware":
            name = "virt"
        if name == "ocp" or name == "k8s":
            name = "openshift"
        if name in allowed and name not in out:
            out.append(name)
    return tuple(out)


def merge_route_hint(plan: ModulePlan, hinted: Sequence[str], message: str) -> ModulePlan:
    hinted_t = tuple(m for m in hinted if m in ALL_MODULES)
    if not hinted_t:
        return plan
    orig = tuple(plan.modules or ())
    reason = plan.reason or ""
    new_conf = min(0.76, max(float(plan.confidence or 0), 0.70))

    if reason.startswith("auto_explore") or reason.startswith("esnaf_"):
        merged = tuple(dict.fromkeys(list(orig) + list(hinted_t)))
        if merged == orig:
            return plan
        return plan_with_modules(
            message, merged, reason=f"{reason}+llm_add", confidence=new_conf,
        )

    if reason.startswith("auto_multi_tie") and orig:
        if set(hinted_t) <= set(orig):
            return plan_with_modules(
                message, hinted_t, reason=f"{reason}+llm_pick", confidence=new_conf,
            )
        merged = tuple(dict.fromkeys(list(orig) + list(hinted_t)))
        return plan_with_modules(
            message, merged, reason=f"{reason}+llm_add", confidence=new_conf,
        )

    if not orig:
        return plan_with_modules(
            message, hinted_t, reason=f"{reason}+llm", confidence=new_conf,
        )

    if orig[0] in hinted_t:
        merged = hinted_t if set(orig) <= set(hinted_t) else tuple(
            dict.fromkeys(list(orig) + list(hinted_t))
        )
    else:
        merged = tuple(dict.fromkeys(list(orig) + list(hinted_t)))
    if merged == orig:
        return plan
    return plan_with_modules(
        message, merged, reason=f"{reason}+llm", confidence=new_conf,
    )


def apply_route_llm_hint(message: str, plan: ModulePlan) -> ModulePlan:
    """Başarısızlıkta planı olduğu gibi döndür."""
    try:
        from app.services import runtime_settings
        if not runtime_settings.get_bool("unified_route_llm_hint"):
            return plan
    except Exception:
        pass
    if not should_ask_route_hint(plan):
        return plan
    if not (message or "").strip():
        return plan

    try:
        from app.core.config import remote_llm_enabled
        from app.services import llm_availability
        if remote_llm_enabled() and llm_availability.is_open():
            logger.info("[RouteHint] devre açık — keyword planı korundu")
            return plan
    except Exception:
        pass

    hinted = _call_hint_llm(message, plan)
    if not hinted:
        return plan
    merged = merge_route_hint(plan, hinted, message)
    if merged is not plan and (
        merged.modules != plan.modules or merged.mode != plan.mode
    ):
        logger.info(
            "[RouteHint] %s %s → %s %s",
            plan.reason, plan.modules, merged.reason, merged.modules,
        )
    return merged


def _call_hint_llm(message: str, plan: ModulePlan) -> Tuple[str, ...]:
    try:
        from app.services.llm_gateway import generate_sync, resolve_model_for_tier
        model, _tier = resolve_model_for_tier("fast", None)
        prompt = _USER_TMPL.format(
            question=(message or "")[:800],
            modules=list(plan.modules or ()),
            reason=plan.reason,
            conf=float(plan.confidence or 0),
        )
        data = generate_sync(
            model=model,
            prompt=prompt,
            system=_SYSTEM,
            options={"temperature": 0.0},
            timeout=_TIMEOUT_SEC,
        )
        if data.get("error"):
            logger.info("[RouteHint] atlandı: %s", str(data.get("error"))[:160])
            return ()
        return parse_hinted_modules(data.get("response") or "")
    except Exception as exc:
        logger.info("[RouteHint] hata, keyword planı: %s", exc)
        return ()
