"""Yedekleme/DR sohbet araçları (READ_ONLY, DB/motor) — YALNIZ `backup` capability varken görünür.

Rakamlar `backup.rpo_engine` deterministik motorundan gelir; LLM yalnız anlatır.
RPO/RTO LLM'e hesaplatılmaz; RTO tahmin edilmez (yalnız kullanıcı hedefi saklanır).
Ham yedek verisi (depo yolu, kimlik, oturum mesajı) araç çıktısına konmaz.
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.services.agent.tools import RiskLevel, Tool

_NO_PROVIDER = {"ok": False, "error": "Yedek sağlayıcısı yapılandırılmadı veya devre dışı; yedek durumu bilinmiyor."}


def _int(v: Any, default: int) -> int:
    try:
        return int(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _have() -> bool:
    """Gerçek sağlayıcı VEYA (bayrak açıkken) demo — demo etiketi çıktıya zorunlu eklenir."""
    from app.services.capabilities import get_capabilities
    from app.services.backup.demo_gate import demo_tools_active
    return "backup" in get_capabilities() or demo_tools_active()


def _demo() -> bool:
    from app.services.backup.demo_gate import demo_tools_active
    return demo_tools_active()


def _label(out: Dict[str, Any]) -> Dict[str, Any]:
    """Demo modunda çıktıyı 'DEMO veri' ile etiketle (LLM'e açıkça belirtme talimatı dahil)."""
    if out.get("ok") and _demo():
        from app.services.backup.demo_gate import DEMO_LABEL_TR, DEMO_TOOL_NOTE_TR
        out["demo"] = True
        out["data_label"] = DEMO_LABEL_TR
        out["note"] = f"{DEMO_TOOL_NOTE_TR} {out.get('note') or ''}".strip()
    return out


def _slim(r: Dict[str, Any]) -> Dict[str, Any]:
    return {k: r.get(k) for k in ("name", "cluster", "state", "match_confidence", "last_restore_point_at",
                                  "rpo_age_min", "target_rpo_min", "rpo_state", "stale")}


def _status_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _have():
        return dict(_NO_PROVIDER)
    try:
        from app.models.backup import BkJob
        from app.services.backup import rpo_engine as eng
        inc = _demo()
        summ = eng.summary(db, include_demo=inc)
        out: Dict[str, Any] = {
            "ok": True, "summary": {k: v for k, v in summ.items() if k != "providers"},
            "providers": [{k: p.get(k) for k in ("label", "demo", "stale", "last_status", "data_age_sec")}
                          for p in summ["providers"]],
            "demo": any(p.get("demo") for p in summ["providers"]),
            "note": "Rakamlar deterministik motordan; hedef RPO tanımsız VM'ler 'no_target'. RTO tahmin edilmez.",
        }
        ids = [i.id for i in eng.backup_instances(db, include_demo=inc)]
        failed = db.query(BkJob).filter(BkJob.instance_id.in_(ids or [-1]), BkJob.last_result == "Failed").limit(10).all()
        out["failed_jobs"] = [{"name": j.name, "last_run_at": j.last_run_at.isoformat() if j.last_run_at else None}
                              for j in failed]
        from app.models.backup import BkRepository
        repos = db.query(BkRepository).filter(BkRepository.instance_id.in_(ids or [-1])).all()
        out["repositories_at_risk"] = [{"name": r.name, "used_pct": eng.repo_used_pct(r), "online": r.is_online}
                                       for r in repos if (eng.repo_used_pct(r) or 0) >= eng.REPO_WARN_PCT
                                       or r.is_online is False]
        vm = (args.get("vm_name") or "").strip().lower()
        if vm:
            out["vms"] = [_slim(r) for r in eng.vm_protection(db, include_demo=inc)
                         if vm in str(r["name"] or "").lower()][:10]
        return _label(out)
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


def _rpo_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    if not _have():
        return dict(_NO_PROVIDER)
    try:
        from app.services.backup import rpo_engine as eng
        inc = _demo()
        rows = eng.vm_protection(db, include_demo=inc)
        lim = max(1, min(_int(args.get("limit"), 15), 40))
        which = (args.get("filter") or "breach").strip()
        if which == "unprotected":
            sel = [r for r in rows if r["state"] == "unprotected" and r["powered_on"]]
        elif which == "no_target":
            sel = [r for r in rows if r["rpo_state"] == "no_target"]
        else:
            sel = [r for r in rows if r["rpo_state"] == "breach"]
        sel.sort(key=lambda r: -(r["rpo_age_min"] or 10 ** 9))
        s = eng.summary(db, include_demo=inc)
        return _label({"ok": True, "filter": which, "count": len(sel), "vms": [_slim(r) for r in sel[:lim]],
                "totals": {k: s[k] for k in ("powered_on", "protected", "unprotected", "protected_pct", "rpo_ok",
                                             "rpo_breach", "rpo_no_target", "low_match")},
                "demo": any(p.get("demo") for p in s["providers"]),
                "note": "RPO = şimdi − son geri dönüş noktası; hedef ainew politikasından. RTO ölçülmez/tahmin edilmez."})
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)}


BACKUP_TOOLS: Dict[str, Tool] = {
    "virt_backup_status": Tool(
        name="virt_backup_status",
        description=(
            "YEDEKLEME DURUMU (READ-ONLY, DB). Yedek sağlayıcısı (ör. Veeam) bağlıysa: korunan/korumasız VM sayısı, "
            "RPO uyumu özeti, başarısız işler, dolan/çevrimdışı depolar, sağlayıcı verisi bayat mı. vm_name verilirse "
            "o VM'in son geri dönüş noktası. 'yedekler sağlıklı mı', 'şu VM yedekleniyor mu', 'hangi iş patladı' "
            "sorularında kullan. Sağlayıcı yoksa araç hiç görünmez — yedek durumu hakkında tahmin yürütme."
        ),
        parameters={"type": "object", "properties": {
            "vm_name": {"type": "string", "description": "VM adı (içerir)"},
        }, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_status_handler, direct_label="Yedek durumu",
        requires_capability=frozenset({"backup"}),
    ),
    "virt_rpo_compliance": Tool(
        name="virt_rpo_compliance",
        description=(
            "RPO UYUMU (READ-ONLY, DB, deterministik). Hedef RPO'yu aşan (breach), korumasız (unprotected) veya hedefi "
            "tanımsız (no_target) VM listesi ve toplamlar. filter: breach | unprotected | no_target. "
            "RPO/RTO'yu kendin HESAPLAMA; araç çıktısını aktar. RTO tahmin edilmez."
        ),
        parameters={"type": "object", "properties": {
            "filter": {"type": "string", "enum": ["breach", "unprotected", "no_target"]},
            "limit": {"type": "integer"},
        }, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_rpo_handler, direct_label="RPO uyumu",
        requires_capability=frozenset({"backup"}),
    ),
}
