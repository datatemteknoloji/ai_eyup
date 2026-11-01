"""Düşük güven module planına LLM ikinci fikir — tam classifier değil.

Yalnız eşik/tie/zayıf sinyal. Mevcut planı ezmez:
- YÜKSEK güvenli keyword planı (confidence > HINT_CONF_MAX) için ipucu HİÇ sorulmaz (`should_ask_route_hint`).
- auto_explore / esnaf: daraltılamaz (disk→virt+linux kasıtlı); yalnız modül EKLENEBİLİR
- auto_multi_tie: bağlı çiftin alt kümesi seçilebilir (düşük güvenli beraberlik)
- diğer: birleşim (ekle, yerine yazma); modülsüz plan (`no_module_signal`) ipucuyla doldurulur
Devre açıksa veya parse/timeout olursa keyword planı kalır; sohbet 503 olmaz.
İstem şablonunda hazır modül listesi örneği bulunmaz (Adım 3 / Parça 2C: model örneği kopyalıyordu).
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
from typing import Dict, Optional, Sequence, Tuple

from app.services.module_orchestrator import (
    ALL_MODULES,
    ModulePlan,
    plan_with_modules,
)

logger = logging.getLogger(__name__)

# _CONF_MULTI=0.72 / _CONF_SINGLE=0.78 üstü LLM yok
HINT_CONF_MAX = 0.70


def _timeout_sec() -> float:
    """Çağrı sınıfı `route_hint` zaman aşımı (varsayılan 8 sn; en çok 10 sn — llm_timeouts)."""
    try:
        from app.services import llm_timeouts
        return float(llm_timeouts.timeout_for("route_hint"))
    except Exception:
        return 8.0


# Aynı tur içinde (create_turn → boru hattı → tur sonu öneri) aynı mesaj/plan için hint tekrar tekrar
# sorulmasın: sonuç (başarı, boş, zaman aşımı, slot meşgul-atlandı) kısa süre önbelleklenir.
_CACHE_TTL_SEC = 60.0
_CACHE_MAX = 256
_cache: Dict[str, Tuple[float, Tuple[str, ...]]] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    with _cache_lock:
        _cache.clear()


def _cache_key(message: str, plan: ModulePlan) -> str:
    raw = "\x1f".join([(message or "")[:800], ",".join(plan.modules or ()), str(plan.reason), f"{float(plan.confidence or 0):.2f}"])
    return hashlib.sha1(raw.encode("utf-8", "ignore")).hexdigest()


def _cache_get(key: str) -> Optional[Tuple[str, ...]]:
    now = time.monotonic()
    with _cache_lock:
        hit = _cache.get(key)
        if hit and (now - hit[0]) < _CACHE_TTL_SEC:
            return hit[1]
        if hit:
            _cache.pop(key, None)
    return None


def _cache_put(key: str, value: Tuple[str, ...]) -> None:
    now = time.monotonic()
    with _cache_lock:
        if len(_cache) >= _CACHE_MAX:
            for k in [k for k, (t, _v) in _cache.items() if (now - t) >= _CACHE_TTL_SEC] or list(_cache)[: _CACHE_MAX // 4]:
                _cache.pop(k, None)
        _cache[key] = (now, value)


def _hint_limits() -> Tuple[int, str]:
    """(num_predict, think) — runtime_settings; hata olursa güvenli varsayılan."""
    try:
        from app.services import runtime_settings
        return (max(32, int(runtime_settings.get_int("route_hint_num_predict"))),
                str(runtime_settings.get_str("route_hint_think") or "low"))
    except Exception:
        return 128, "low"
_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)

# Adım 3 / Parça 2C: şablonda HAZIR modül listesi örneği YOK. Eski şablondaki
# {"modules":["virt","linux"],...} örneğini model sorudan bağımsız kopyalıyordu (ölçüm: 16 sorunun
# 12'sinde aynı çıktı; Windows/Linux/OpenShift soruları dahil). Şema yer tutucularla verilir ve
# "emin değilsen birden fazla yaz" kuralı daraltıldı (belirsizlikte boş liste = keyword planı kalır).
_SYSTEM = (
    "Altyapı sohbet yönlendiricisisin. Yalnız tek bir JSON nesnesi yaz, başka metin yok.\n"
    "Modüller: linux (Linux sunucu: SSH, systemd, disk/CPU/bellek, load), "
    "windows (Windows sunucu: WinRM, IIS, Active Directory, event log, Windows servisleri), "
    "virt (vCenter/ESXi/VM/datastore/hypervisor), "
    "openshift (OpenShift/Kubernetes: pod, namespace, cluster, node), "
    "exadata (Exadata/Oracle: cell, ASM, smart scan).\n"
    "Kurallar: Soru bir modülle açıkça ilgiliyse YALNIZ o modülü yaz. "
    "Soru gerçekten iki modüle bağlıysa en çok iki modül yaz. "
    "Windows ile Linux sunucuyu karıştırma: Windows, IIS, Active Directory, event log, WinRM geçiyorsa windows. "
    "Hiçbir modülle ilgili değilse (maliyet, genel bilgi) ya da soru önceki konuşmaya atıf yapıyorsa "
    "(bunlar, onlar, hepsi) modules boş liste olsun."
)

_USER_TMPL = (
    "Soru: {question}\n"
    "Keyword plan: modules={modules} reason={reason} confidence={conf:.2f}\n"
    'Yanıt şeması: {{"modules": ["<modül>", ...], "reason": "<kısa gerekçe>"}}'
)


def build_hint_prompt(message: str, plan: ModulePlan) -> Tuple[str, str]:
    """(system, user) istemi — uygulama çağrısı ve teşhis betiği (scripts/diag_route_hint.py) aynı fonksiyonu kullanır."""
    prompt = _USER_TMPL.format(
        question=(message or "")[:800],
        modules=list(plan.modules or ()),
        reason=plan.reason,
        conf=float(plan.confidence or 0),
    )
    return _SYSTEM, prompt


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
    try:
        from app.services import llm_activity
        llm_activity.note_hint_merge(
            list(merged.modules or ()), str(merged.reason or ""),
            changed=bool(merged is not plan and (merged.modules != plan.modules or merged.mode != plan.mode)),
        )
    except Exception:
        pass
    if merged is not plan and (
        merged.modules != plan.modules or merged.mode != plan.mode
    ):
        logger.info(
            "[RouteHint] %s %s → %s %s",
            plan.reason, plan.modules, merged.reason, merged.modules,
        )
    return merged


def _call_hint_llm(message: str, plan: ModulePlan) -> Tuple[str, ...]:
    key = _cache_key(message, plan)
    cached = _cache_get(key)
    if cached is not None:
        logger.info("[RouteHint] önbellekten (aynı tur) — LLM çağrılmadı")
        _note("cache", plan, hinted=cached)
        return cached
    result: Tuple[str, ...] = ()
    source, raw = "empty", ""
    try:
        from app.services.llm_gateway import generate_sync, resolve_model_for_tier
        model, _tier = resolve_model_for_tier("fast", None)
        system, prompt = build_hint_prompt(message, plan)
        num_predict, think = _hint_limits()
        data = generate_sync(
            model=model,
            prompt=prompt,
            system=system,
            # Çıktı kısa bir modül listesi: üretim sınırı + düşük düşünme seviyesi (gpt-oss).
            options={"temperature": 0.0, "num_predict": num_predict},
            think=think,
            timeout=_timeout_sec(),
            # İsteğe bağlı yan çağrı: zaman aşımı/hata uzak devre kesiciyi BESLEMEZ (Adım 3);
            # başarısızsa anahtar sözcük planı zaten kalıyor.
            best_effort=True,
            # LLM slotu meşgulse (ana cevap üretiliyor) hiç sorma: keyword planı anında kalır.
            skip_if_busy=True,
        )
        raw = str(data.get("response") or "")
        if data.get("skipped"):
            source = "skipped"
            logger.info("[RouteHint] LLM slotu meşgul — ipucu atlandı, keyword planı korundu")
        elif data.get("error"):
            source = "error"
            raw = str(data.get("error") or "")
            logger.info("[RouteHint] atlandı: %s", raw[:160])
        else:
            result = parse_hinted_modules(raw)
            source = "llm" if result else "empty"
    except Exception as exc:
        source, raw = "error", str(exc)
        logger.info("[RouteHint] hata, keyword planı: %s", exc)
    _note(source, plan, hinted=result, raw=raw)
    # Başarı/boş/hata/atlama fark etmeksizin tur içi tekrarları engelle
    _cache_put(key, result)
    return result


def _note(source: str, plan: ModulePlan, *, hinted: Sequence[str] = (), raw: str = "") -> None:
    """Ham ipucu çıktısını (≤300 karakter, maskeli) tur izine yazar; birleşme sonucu `apply_route_llm_hint`te eklenir."""
    try:
        from app.services import llm_activity
        llm_activity.note_hint(
            source, raw=raw, hinted=list(hinted),
            kw_modules=list(plan.modules or ()), kw_reason=str(plan.reason or ""),
            kw_confidence=float(plan.confidence or 0),
        )
    except Exception:
        pass
