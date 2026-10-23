"""Donanım (Dell OME / HPE OneView) sohbet araçları — READ_ONLY, DB, deterministik.

YALNIZ `hw` capability varken (veya DEMO bayrağı açıkken, etiketli) görünür; alan adı `hw` olduğundan yalnız
Unified sohbette ve donanım niyeti taşıyan sorularda araç setine girer. Çağıranın `hardware` modülü yoksa
(`ctx["hw_allowed"]` False) araç veri DÖNDÜRMEZ.

LLM'e BMC IP'si, seri/service tag, UUID, kimlik, web_url ve ham alarm gövdesi GİTMEZ; yalnız ad, model, sağlık,
form faktörü, kasa/yuva, garanti özeti ve alarm sayıları döner.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.services.agent.tools import RiskLevel, Tool

_NO_PROVIDER = {"ok": False, "error": "Donanım sağlayıcısı (Dell OME / HPE OneView) yapılandırılmadı veya devre dışı; "
                                     "fiziksel sunucu donanım durumu bilinmiyor."}
_DENIED = {"ok": False, "error": "Donanım verisi için `hardware` modülü yetkiniz yok."}

# LLM'e giden alanların TEK kaynağı (sızıntı testi bunu kullanır).
LLM_EGRESS_FIELDS = ("name", "vendor", "model", "form_factor", "enclosure", "health", "power", "matched_to",
                     "warranty_end", "warranty_expired", "active_alerts")


from app.services.hw.intent import (  # noqa: E402,F401
    hw_active, hw_intent, hw_vendor_signal, other_platform_signal,
)


def _mode(db: Session) -> str:
    from app.services.capabilities import get_capabilities
    from app.services.hw.demo_gate import hw_mode
    caps = get_capabilities()
    m = hw_mode(db)
    if m == "real" and "hw" in caps:
        return "real"
    if m == "demo" and "hw_demo" in caps:
        return "demo"
    return "none"


def _gate(db: Session, ctx: Dict[str, Any]):
    """(mode, error_dict|None)."""
    mode = _mode(db)
    if mode == "none":
        return mode, dict(_NO_PROVIDER)
    if not (ctx or {}).get("hw_allowed"):
        return mode, dict(_DENIED)
    return mode, None


def _label(out: Dict[str, Any], mode: str) -> Dict[str, Any]:
    if out.get("ok") and mode == "demo":
        from app.services.hw.demo_gate import BANNER_TR
        out["demo"] = True
        out["data_label"] = BANNER_TR
        out["note"] = ("Bu veriler DEMO'dur; gerçek donanım değildir. Yanıtta 'DEMO veri' olduğunu açıkça belirt. "
                       + (out.get("note") or "")).strip()
    return out


def _ids(db: Session, mode: str) -> List[int]:
    from app.services.hw.demo_gate import active_instances
    return [r.id for r in active_instances(db, include_demo=(mode == "demo"))]


def _aware(dt):
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _status_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    mode, err = _gate(db, ctx)
    if err:
        return err
    try:
        from app.models.hw import HwAlert, HwHostLink, HwServer, HwWarranty
        from app.models.hypervisor_inventory import HypervisorHostInventory
        from app.models.server import Server

        ids = _ids(db, mode)
        q = db.query(HwServer).filter(HwServer.instance_id.in_(ids or [-1]))
        total_all = q.count()                       # süzgeçten bağımsız toplam (cevapta "kaç sunucu var" için)
        name = (args.get("name") or "").strip()
        if name:
            like = f"%{name}%"
            q = q.filter((HwServer.name.ilike(like)) | (HwServer.os_hostname.ilike(like)))
        health = (args.get("health") or "").strip().lower()
        if health in ("ok", "warning", "critical", "unknown"):
            q = q.filter(HwServer.health == health)
        vendor = (args.get("vendor") or "").strip().lower()
        if vendor in ("dell", "hpe"):
            q = q.filter(HwServer.vendor == vendor)
        encl = (args.get("enclosure") or "").strip()
        if encl:
            q = q.filter(HwServer.enclosure_name.ilike(f"%{encl}%"))
        wf = (args.get("warranty") or "").strip().lower()
        if wf in ("expired", "expiring_90"):
            now0 = datetime.now(timezone.utc)
            latest: Dict[tuple, Any] = {}
            for w in db.query(HwWarranty).filter(HwWarranty.instance_id.in_(ids or [-1])).all():
                e = _aware(w.end_date)
                k = (w.instance_id, w.server_ref)
                if e is not None and (k not in latest or e > latest[k]):
                    latest[k] = e
            lim = now0 + timedelta(days=90)
            hit = {k[1] for k, e in latest.items() if (e < now0 if wf == "expired" else now0 <= e <= lim)}
            q = q.filter(HwServer.provider_ref.in_(list(hit) or ["-"]))
        try:
            limit = max(1, min(int(args.get("limit") or 30), 100))
        except (TypeError, ValueError):
            limit = 30
        total = q.count()
        from sqlalchemy import case
        sev = case((HwServer.health == "critical", 0), (HwServer.health == "warning", 1),
                   (HwServer.health == "unknown", 2), else_=3)
        rows = q.order_by(sev, HwServer.name).limit(limit).all()
        hids = [r.id for r in rows]
        links = {l.hw_server_id: l for l in db.query(HwHostLink).filter(HwHostLink.hw_server_id.in_(hids or [-1])).all()}
        snames = {s.id: s.name for s in db.query(Server).filter(
            Server.id.in_([l.target_id for l in links.values() if l.target_kind == "server"] or [-1])).all()}
        enames = {e.id: e.host_name for e in db.query(HypervisorHostInventory).filter(
            HypervisorHostInventory.id.in_([l.target_id for l in links.values() if l.target_kind == "esxi"] or [-1])).all()}
        refs = [r.provider_ref for r in rows]
        act = {}
        for ref, n in db.query(HwAlert.server_ref, func.count(HwAlert.id)).filter(
                HwAlert.instance_id.in_(ids or [-1]), HwAlert.state == "active",
                HwAlert.server_ref.in_(refs or ["-"])).group_by(HwAlert.server_ref).all():
            act[ref] = n
        now = datetime.now(timezone.utc)
        wend: Dict[tuple, Any] = {}
        for w in db.query(HwWarranty).filter(HwWarranty.instance_id.in_(ids or [-1]),
                                             HwWarranty.server_ref.in_(refs or ["-"])).all():
            e = _aware(w.end_date)
            k = (w.instance_id, w.server_ref)
            if e is not None and (k not in wend or e > wend[k]):
                wend[k] = e
        out_rows = []
        for r in rows:
            l = links.get(r.id)
            matched = None
            if l is not None:
                matched = snames.get(l.target_id) if l.target_kind == "server" else enames.get(l.target_id)
            e = wend.get((r.instance_id, r.provider_ref))
            out_rows.append({
                "name": r.name, "vendor": r.vendor, "model": r.model, "form_factor": r.form_factor,
                "enclosure": (f"{r.enclosure_name} / {r.bay}" if r.enclosure_name and r.bay else r.enclosure_name),
                "health": r.health, "power": r.power_state, "matched_to": matched,
                "warranty_end": e.date().isoformat() if e else None,
                "warranty_expired": (e < now) if e else None,
                "active_alerts": act.get(r.provider_ref, 0),
            })
        by_health_f: Dict[str, int] = {}
        for h, n in q.order_by(None).with_entities(HwServer.health, func.count(HwServer.id)).group_by(HwServer.health).all():
            by_health_f[h] = n
        by_health: Dict[str, int] = {}
        for h, n in db.query(HwServer.health, func.count(HwServer.id)).filter(
                HwServer.instance_id.in_(ids or [-1])).group_by(HwServer.health).all():
            by_health[h] = n
        _tr = {"critical": "kritik", "warning": "uyarı", "unknown": "bilinmeyen", "ok": "sağlıklı"}
        _filt = {k: v for k, v in (args or {}).items() if k != "limit" and v}
        _ozet = (f"{total} sunucu eşleşti" + (f" (süzgeç: {', '.join(f'{k}={v}' for k, v in _filt.items())})" if _filt else "")
                 + "; dağılım: " + (", ".join(f"{_tr.get(h, h)} {n}" for h, n in sorted(by_health_f.items(), key=lambda x: -x[1])) or "yok")
                 + f". Tüm kayıt: {total_all}.")
        return _label({"ok": True, "ozet": _ozet, "total": total, "total_all_servers": total_all, "returned": len(out_rows),
                       "truncated": total > len(out_rows), "by_health": by_health_f, "by_health_all": by_health,
                       "as_of": datetime.now(timezone.utc).date().isoformat(),
                       "filters_applied": {k: v for k, v in (args or {}).items() if k != "limit" and v},
                       "servers": out_rows,
                       "note": "Sağlık değeri sağlayıcının bildirdiği durumdur; ölçülemeyen alanlar boştur (tahmin etme)."},
                      mode)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Donanım durumu okunamadı: {type(e).__name__}"}


def _alerts_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    mode, err = _gate(db, ctx)
    if err:
        return err
    try:
        from app.models.hw import HwAlert

        ids = _ids(db, mode)
        try:
            hours = max(1, min(int(args.get("hours") or 24), 24 * 14))
        except (TypeError, ValueError):
            hours = 24
        try:
            limit = max(1, min(int(args.get("limit") or 15), 50))
        except (TypeError, ValueError):
            limit = 15
        since = datetime.now(timezone.utc) - timedelta(hours=hours)
        base = db.query(HwAlert).filter(HwAlert.instance_id.in_(ids or [-1]), HwAlert.occurred_at >= since)
        sev = (args.get("severity") or "").strip().lower()
        if sev in ("critical", "warning"):
            base = base.filter(HwAlert.severity == sev)
        groups = (db.query(HwAlert.fingerprint, HwAlert.category, HwAlert.severity, func.count(HwAlert.id),
                           func.count(func.distinct(HwAlert.server_ref)), func.max(HwAlert.occurred_at))
                  .filter(HwAlert.instance_id.in_(ids or [-1]), HwAlert.occurred_at >= since))
        if sev in ("critical", "warning"):
            groups = groups.filter(HwAlert.severity == sev)
        groups = groups.group_by(HwAlert.fingerprint, HwAlert.category, HwAlert.severity) \
            .order_by(func.count(HwAlert.id).desc()).limit(limit).all()
        out = [{"category": c, "severity": s, "count": n, "servers": ns,
                "last_at": (_aware(last).isoformat() if last else None)} for _fp, c, s, n, ns, last in groups]
        return _label({"ok": True, "window_hours": hours, "total_alerts": base.count(), "groups": out,
                       "note": "Yalnız Uyarı/Kritik alarmlar saklanır; ham alarm metni ve BMC adresi paylaşılmaz."}, mode)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": f"Donanım alarmları okunamadı: {type(e).__name__}"}


HW_TOOLS: Dict[str, Tool] = {
    "hw_server_status": Tool(
        name="hw_server_status",
        description=(
            "FİZİKSEL SUNUCU DONANIM DURUMU (READ-ONLY, DB, deterministik; Dell OME / HPE OneView). Model, form faktörü, "
            "kasa/yuva, sağlık, güç, garanti bitişi, aktif alarm sayısı ve eşleşen sunucu adı. 'donanım sağlığı', "
            "'hangi blade kritik', 'garantisi biten sunucular' (warranty=expired), 'iDRAC/iLO uyarısı olan' sorularında kullan. "
            "Sonuç sağlık önceliğine göre (kritik→uyarı→ok) sıralıdır; 'ozet' hazır sayı cümlesidir (sayıyı oradan al, satır sayma); 'total' ve 'by_health' SÜZGEÇLİDİR (sorulan kapsamın sayısı budur), 'total_all_servers' ve 'by_health_all' süzgeçsiz tüm kayıtlardır; "
            "'truncated' true ise listeyi tam sayma, toplamı 'total'dan oku. 'as_of' bugünün tarihidir (garanti karşılaştırması bu tarihe göre; kendi tahmini tarihini kullanma). "
            "BMC IP / seri numarası verilmez. Sağlayıcı yoksa araç görünmez — donanım durumunu tahmin etme."
        ),
        parameters={"type": "object", "properties": {
            "name": {"type": "string", "description": "Sunucu adı (içerir)"},
            "health": {"type": "string", "enum": ["ok", "warning", "critical", "unknown"]},
            "vendor": {"type": "string", "enum": ["dell", "hpe"], "description": "Üretici süzgeci"},
            "enclosure": {"type": "string", "description": "Kasa adı (içerir), ör. DEMO-Encl1"},
            "warranty": {"type": "string", "enum": ["expired", "expiring_90"],
                         "description": "expired = garantisi bitmiş; expiring_90 = 90 gün içinde bitecek"},
            "limit": {"type": "integer"},
        }, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_status_handler, direct_label="Donanım durumu",
        requires_capability=frozenset({"hw"}), domains=frozenset({"hw"}),
    ),
    "hw_alerts_summary": Tool(
        name="hw_alerts_summary",
        description=(
            "DONANIM ALARM ÖZETİ (READ-ONLY, DB). Son N saatte donanım yönetim sistemlerinden (OME/OneView) gelen "
            "Uyarı/Kritik alarmların kategoriye göre gruplanmış sayıları ve etkilenen sunucu sayısı. "
            "Ham alarm metni/BMC adresi vermez."
        ),
        parameters={"type": "object", "properties": {
            "hours": {"type": "integer", "description": "Pencere (saat, varsayılan 24)"},
            "severity": {"type": "string", "enum": ["critical", "warning"]},
            "limit": {"type": "integer"},
        }, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_alerts_handler, direct_label="Donanım alarmları",
        requires_capability=frozenset({"hw"}), domains=frozenset({"hw"}),
    ),
}
