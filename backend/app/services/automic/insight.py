"""Dashboard AI özeti (widget 15) — LLM + 15 dk Redis/bellek önbelleği.

Sayfa yükünde LLM bekletilmez: önbellek veya hızlı deterministik özet döner;
LLM arka planda üretilip önbelleğe yazılır. Senkron LLM yalnızca force=True.
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import json
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from app.models.automic import AutomicSystem

logger = logging.getLogger(__name__)

_TTL = 900  # 15 dk
_PREFIX = "ainew:automic:insight:"
_MEM: Dict[str, tuple] = {}
_MEM_LOCK: Dict[str, float] = {}


def _redis():
    try:
        from app.core.redis_client import get_redis
        return get_redis()
    except Exception as _exc:
        note_error("insight.silent_32", _exc)
        return None


def _key(system_id: int, range_: str, clients: Optional[List[int]]) -> str:
    cl = ",".join(str(c) for c in sorted(clients or [])) or "all"
    return f"{_PREFIX}{system_id}:{range_}:{cl}"


def cache_get(system_id: int, range_: str, clients: Optional[List[int]]) -> Optional[Dict[str, Any]]:
    key = _key(system_id, range_, clients)
    r = _redis()
    if r is not None:
        try:
            raw = r.get(key)
            if raw:
                data = json.loads(raw)
                return data if isinstance(data, dict) else None
        except Exception as exc:
            note_error("insight.cache_get", exc)
        return None
    hit = _MEM.get(key)
    if hit and hit[0] > time.monotonic():
        return hit[1]
    return None


def cache_put(system_id: int, range_: str, clients: Optional[List[int]], payload: Dict[str, Any]) -> None:
    key = _key(system_id, range_, clients)
    r = _redis()
    if r is not None:
        try:
            r.setex(key, _TTL, json.dumps(payload, ensure_ascii=False, default=str))
            return
        except Exception as exc:
            note_error("insight.cache_put", exc)
    _MEM[key] = (time.monotonic() + _TTL, payload)


def _lock_key(system_id: int, range_: str, clients: Optional[List[int]]) -> str:
    return _key(system_id, range_, clients) + ":lock"


def _llm_lock_held(system_id: int, range_: str, clients: Optional[List[int]]) -> bool:
    key = _lock_key(system_id, range_, clients)
    r = _redis()
    if r is not None:
        try:
            return bool(r.get(key))
        except Exception as _exc:
            note_error("insight.silent_81", _exc)
            return False
    return (_MEM_LOCK.get(key) or 0) > time.monotonic()


def _acquire_llm_lock(system_id: int, range_: str, clients: Optional[List[int]], ttl: int = 180) -> bool:
    """Aynı anahtar için tek LLM üretimi (stampede koruması)."""
    key = _lock_key(system_id, range_, clients)
    r = _redis()
    if r is not None:
        try:
            return bool(r.set(key, "1", nx=True, ex=ttl))
        except Exception as exc:
            note_error("insight._acquire_llm_lock", exc)
    now = time.monotonic()
    exp = _MEM_LOCK.get(key) or 0
    if exp > now:
        return False
    _MEM_LOCK[key] = now + ttl
    return True


def _release_llm_lock(system_id: int, range_: str, clients: Optional[List[int]]) -> None:
    key = _lock_key(system_id, range_, clients)
    r = _redis()
    if r is not None:
        try:
            r.delete(key)
        except Exception as _e:
            note_error("insight._release_llm_lock", _e)
    _MEM_LOCK.pop(key, None)


def _clear_regenerating_flag(system_id: int, range_: str, clients: Optional[List[int]]) -> None:
    hit = cache_get(system_id, range_, clients)
    if hit and hit.get("regenerating") and hit.get("source") != "llm":
        cache_put(system_id, range_, clients, {**hit, "regenerating": False})


def build_metrics_blob(db: Session, system: AutomicSystem, *, range_: str = "24h",
                       clients: Optional[List[int]] = None) -> Dict[str, Any]:
    """LLM'e gidecek kompakt, yorum içermeyen metrik paketi."""
    from .queries import overview

    ov = overview(db, system, range_=range_, clients=clients)
    kpi = ov.get("kpi") or {}
    prev = kpi.get("previous") or {}
    top = (ov.get("top_failed") or [])[:5]
    recent = (ov.get("recent_failures") or [])[:8]
    outliers = (ov.get("duration_outliers") or [])[:5]
    agents = (ov.get("agent_activity") or [])[:8]
    health = ov.get("health") or {}
    storage = ov.get("storage") or {}
    aw = ov.get("active_workflows") or {}
    quiet_agents = [a for a in agents if int(a.get("runs") or 0) == 0]
    hot_agents = sorted(agents, key=lambda a: int(a.get("failed") or 0), reverse=True)[:3]

    sigs: Dict[str, int] = {}
    for f in recent:
        s = f.get("error_signature")
        if s:
            sigs[s] = sigs.get(s, 0) + 1
    top_sigs = sorted(sigs.items(), key=lambda x: -x[1])[:5]

    return {
        "system": system.name,
        "range": range_,
        "from": ov.get("from"),
        "to": ov.get("to"),
        "kpi": {
            "total": kpi.get("total"), "ok": kpi.get("ok"), "failed": kpi.get("failed"),
            "cancelled": kpi.get("cancelled"), "running": kpi.get("running"),
            "success_rate_pct": kpi.get("success_rate_pct"),
            "failed_prev": prev.get("failed"), "total_prev": prev.get("total"),
        },
        "top_failed": [{"object_name": t.get("object_name"), "failed": t.get("failed"),
                        "runs": t.get("runs")} for t in top],
        "top_error_signatures": [{"signature": s, "count": n} for s, n in top_sigs],
        "duration_outliers": [{"object_name": o.get("object_name"), "ratio": o.get("ratio"),
                               "duration_sec": o.get("duration_sec"), "p95_sec": o.get("p95_sec")}
                              for o in outliers],
        "active_by_state": aw.get("by_state"),
        "agents_hot_failures": [{"agent": a.get("agent"), "failed": a.get("failed"),
                                 "runs": a.get("runs")} for a in hot_agents if a.get("failed")],
        "agents_quiet": [a.get("agent") for a in quiet_agents[:5]],
        "health": {
            "source_lag_sec": health.get("source_lag_sec"),
            "last_error": health.get("last_error"),
            "circuit_open_sec": health.get("circuit_open_sec"),
            "ingest_paused_reason": health.get("ingest_paused_reason"),
            "fake": health.get("fake"),
        },
        "storage": {
            "usage_pct": storage.get("usage_pct"),
            "level": storage.get("level"),
            "quota_gb": storage.get("quota_gb"),
        },
    }


_SYSTEM = (
    "Sen ainew Automic dashboard özetleyicisisin. Yalnızca verilen metriklere dayan. "
    "Uydurma yok. Yanıt Türkçe Markdown: ### Özet (3–5 cümle) ve gerekirse ### Bulgular "
    "(madde işaretli, önem: critical/warning/info). Aksiyon emri yok; salt okunur. "
    "Tahmin/forecast yok. Meta blok yazma."
)


def _call_llm(metrics: Dict[str, Any], *, model: Optional[str] = None,
              masking: Optional[Dict[str, Any]] = None) -> tuple[str, Optional[str], Optional[str]]:
    from .masking import mask_obj

    safe = mask_obj(metrics, masking)
    prompt = (
        "Aşağıdaki Automic metrik paketinden 'Son dönemde öne çıkanlar' özeti yaz.\n"
        "Anormallikleri önem derecesiyle belirt: hata artışı, p95 üstü süreler, yeni/sık hata imzaları, "
        "aktif bloke işler, sessiz agent'lar, kaynak gecikmesi, kota.\n\n"
        f"```json\n{json.dumps(safe, ensure_ascii=False, indent=2, default=str)[:12000]}\n```"
    )
    text = ""
    err = None
    used_model = model
    try:
        from app.services import llm_gateway
        if not used_model:
            try:
                from app.core.database import SessionLocal
                from app.core.config import get_active_model
                _db = SessionLocal()
                try:
                    used_model = get_active_model(_db)
                finally:
                    _db.close()
            except Exception:
                used_model = llm_gateway.active_model_label()
        res = llm_gateway.generate_sync(
            model=used_model, prompt=prompt, system=_SYSTEM,
            options={"temperature": 0.2}, timeout=120.0,
        )
        text = (res.get("response") or "").strip()
        if res.get("error") and not text:
            err = res.get("error")
    except Exception as exc:
        logger.warning("automic insight LLM: %s", exc)
        err = f"{type(exc).__name__}: {exc}"
    return text, err, used_model


def _payload(system: AutomicSystem, range_: str, *, text: str, metrics: Dict[str, Any],
             used_model: Optional[str], err: Optional[str], source: str,
             regenerating: bool, cached: bool) -> Dict[str, Any]:
    return {
        "ok": True,
        "system": system.name,
        "system_id": system.id,
        "range": range_,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "expires_in_sec": _TTL,
        "model": used_model,
        "cached": cached,
        "source": source,
        "regenerating": regenerating,
        "llm_error": err,
        "markdown": text,
        "metrics": metrics,
        "findings": _extract_findings(text, metrics),
    }


def _spawn_llm_refresh(system_id: int, range_: str, clients: Optional[List[int]],
                       model: Optional[str] = None) -> bool:
    if not _acquire_llm_lock(system_id, range_, clients):
        return False

    def _run():
        db = None
        wrote = False
        try:
            from app.services.automic.database import get_automic_thread_session
            db = get_automic_thread_session()
            if db is None:
                return
            system = db.query(AutomicSystem).filter(AutomicSystem.id == system_id).first()
            if not system:
                return
            generate_insight(db, system, range_=range_, clients=clients, force=True, model=model)
            wrote = True
        except Exception as exc:
            logger.warning("automic insight arka plan LLM: %s", exc)
        finally:
            if not wrote:
                _clear_regenerating_flag(system_id, range_, clients)
            _release_llm_lock(system_id, range_, clients)
            if db is not None:
                try:
                    db.close()
                except Exception as _e:
                    note_error("insight._run", _e)

    threading.Thread(target=_run, name=f"automic-insight-{system_id}", daemon=True).start()
    return True


def generate_insight(db: Session, system: AutomicSystem, *, range_: str = "24h",
                     clients: Optional[List[int]] = None, force: bool = False,
                     model: Optional[str] = None) -> Dict[str, Any]:
    if not force:
        hit = cache_get(system.id, range_, clients)
        if hit:
            out = {**hit, "cached": True}
            pending = bool(hit.get("regenerating") and hit.get("source") != "llm")
            if pending:
                if _llm_lock_held(system.id, range_, clients):
                    out["regenerating"] = True
                else:
                    # Önceki arka plan işi düşmüş — yeniden dene veya bayrağı temizle
                    started = _spawn_llm_refresh(system.id, range_, clients, model=model)
                    out["regenerating"] = started
                    if not started:
                        _clear_regenerating_flag(system.id, range_, clients)
                        out["regenerating"] = False
            return out

        # Cache miss: kullanıcıyı LLM ile bekletme — hızlı metrik özeti + arka plan LLM
        metrics = build_metrics_blob(db, system, range_=range_, clients=clients)
        text = _deterministic_insight(metrics, None)
        started = _spawn_llm_refresh(system.id, range_, clients, model=model)
        out = _payload(
            system, range_, text=text, metrics=metrics, used_model=None, err=None,
            source="deterministic", regenerating=started, cached=False,
        )
        cache_put(system.id, range_, clients, {**out, "cached": False})
        return out

    # force=True — senkron LLM (veya LLM yoksa deterministik)
    from .masking import masking_cfg_for_system

    metrics = build_metrics_blob(db, system, range_=range_, clients=clients)
    text, err, used_model = _call_llm(
        metrics, model=model, masking=masking_cfg_for_system(system.settings))
    source = "llm"
    if not text:
        text = _deterministic_insight(metrics, err)
        source = "deterministic"
    out = _payload(
        system, range_, text=text, metrics=metrics, used_model=used_model, err=err,
        source=source, regenerating=False, cached=False,
    )
    cache_put(system.id, range_, clients, out)
    return out


def _deterministic_insight(m: Dict[str, Any], err: Optional[str]) -> str:
    kpi = m.get("kpi") or {}
    failed = int(kpi.get("failed") or 0)
    prev = int(kpi.get("failed_prev") or 0)
    lines = ["### Özet"]
    if err:
        lines.append(f"Dil modeli yanıt üretemedi ({err}). Aşağıdaki özet yalnızca metriklere dayanır.")
    delta = ""
    if prev:
        pct = round((failed - prev) / prev * 100, 1)
        delta = f" (önceki döneme göre %{pct:+.1f})"
    lines.append(
        f"{m.get('system')} sisteminde seçili aralıkta {kpi.get('total') or 0} çalışma, "
        f"{failed} hatalı{delta}, şu an {kpi.get('running') or 0} aktif iş var."
    )
    top = m.get("top_failed") or []
    if top:
        names = ", ".join(t["object_name"] for t in top[:3])
        lines.append(f"En çok hata verenler: {names}.")
    lag = (m.get("health") or {}).get("source_lag_sec")
    if lag and float(lag) > 1800:
        lines.append(f"Kaynak gecikmesi yüksek: {int(float(lag) // 60)} dk.")
    st = m.get("storage") or {}
    if st.get("level") in ("warn", "prune", "critical"):
        lines.append(f"Depolama kotası %{st.get('usage_pct')} ({st.get('level')}).")
    findings = []
    for t in top[:5]:
        findings.append(f"- **warning** {t['object_name']}: {t['failed']} hata / {t['runs']} çalışma")
    for s in (m.get("top_error_signatures") or [])[:3]:
        findings.append(f"- **critical** İmza ({s['count']}×): `{s['signature'][:120]}`")
    if findings:
        lines.append("\n### Bulgular")
        lines.extend(findings)
    return "\n".join(lines)


def _extract_findings(md: str, metrics: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for line in (md or "").splitlines():
        s = line.strip()
        if not s.startswith(("-", "*")):
            continue
        tone = "info"
        low = s.lower()
        if "critical" in low or "kritik" in low:
            tone = "critical"
        elif "warning" in low or "uyarı" in low or "warning" in s:
            tone = "warning"
        out.append({"tone": tone, "text": s.lstrip("-* ").strip()})
    if out:
        return out[:8]
    for t in (metrics.get("top_failed") or [])[:3]:
        out.append({"tone": "warning",
                    "text": f"{t['object_name']}: {t['failed']} hata / {t['runs']} çalışma"})
    return out
