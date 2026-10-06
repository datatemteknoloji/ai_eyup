"""Onaylı düzeltme — Agent onay akışı + AYRI yazma hesabı + izinli işlem listesi.

İlkeler:
  • Okuma hesabı (hypervisor kaydı) asla yazma için kullanılmaz; yazma işlemleri
    `connection_config.write_credential` (Fernet ile mühürlü) gerektirir.
  • Yalnız ACTIONS içindeki işlemler önerilebilir; serbest komut yoktur.
  • Öneri bir AgentAction(pending, mutating) kaydı açar; onay /agent ekranından
    (veya POST /agent/actions/{id}/approve) verilir — çalıştırma ancak o zaman olur.
  • Her işlem uygulamadan önce mevcut değeri okuyup sonuçta "rollback" bilgisini döner.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.hypervisor import Hypervisor
from app.models.infra_finding import InfraFinding

logger = logging.getLogger(__name__)
TOOL_NAME = "virt_remediate"


@dataclass(frozen=True)
class RemediationAction:
    id: str
    title: str
    platforms: Tuple[str, ...]
    check_ids: Tuple[str, ...]
    rollback_note: str


ACTIONS: Dict[str, RemediationAction] = {a.id: a for a in [
    RemediationAction("vmw.snapshot_remove", "VM snapshot sil", ("vmware",), ("reclaim.vm.snapshot_age",),
                      "Geri alınamaz — silmeden önce yedek zinciri doğrulanmalı."),
    RemediationAction("vmw.ntp_restart", "ESXi NTP servisini yeniden başlat", ("vmware",),
                      ("vmw.host.ntp_running",), "Servis politikası önceki değerine döndürülebilir."),
    RemediationAction("vmw.ntp_set_servers", "ESXi NTP sunucularını ayarla", ("vmware",),
                      ("vmw.host.ntp_configured", "vmw.cluster.ntp_consistency"),
                      "Önceki NTP sunucu listesi sonuçta saklanır; aynı işlemle geri yüklenir."),
    RemediationAction("vmw.ssh_stop", "ESXi SSH servisini durdur", ("vmware",), ("cmp.host.ssh_disabled",),
                      "StartService ile geri açılabilir; önceki politika sonuçta saklanır."),
]}
_DEFAULT_ACTION = {cid: a.id for a in ACTIONS.values() for cid in a.check_ids}


# ── Yazma hesabı ─────────────────────────────────────────────────────────────

def write_credential_status(db: Session, hypervisor_id: int) -> Dict[str, Any]:
    hv = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id).first()
    if not hv:
        return {"ok": False, "error": "Hypervisor bulunamadı"}
    wc = (hv.connection_config or {}).get("write_credential") or {}
    return {"ok": True, "configured": bool(wc.get("username") and wc.get("password")),
            "username": wc.get("username"), "updated_at": wc.get("updated_at")}


def set_write_credential(db: Session, hypervisor_id: int, username: str, password: str) -> Dict[str, Any]:
    from app.services.hypervisor_credentials import sealed
    hv = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id).first()
    if not hv:
        return {"ok": False, "error": "Hypervisor bulunamadı"}
    if (hv.username or "").strip().lower() == username.strip().lower():
        return {"ok": False, "error": "Yazma hesabı okuma hesabından farklı olmalı"}
    cc = dict(hv.connection_config or {})
    cc["write_credential"] = {"username": username.strip(), "password": sealed(password),
                              "updated_at": datetime.now(timezone.utc).isoformat()}
    hv.connection_config = cc
    db.commit()
    return {"ok": True, "configured": True, "username": username.strip()}


def clear_write_credential(db: Session, hypervisor_id: int) -> Dict[str, Any]:
    hv = db.query(Hypervisor).filter(Hypervisor.id == hypervisor_id).first()
    if not hv:
        return {"ok": False, "error": "Hypervisor bulunamadı"}
    cc = dict(hv.connection_config or {})
    cc.pop("write_credential", None)
    hv.connection_config = cc
    db.commit()
    return {"ok": True, "configured": False}


def _write_client(hv: Hypervisor):
    from app.services.findings.collectors.vmware import _versioned_cls
    from app.services.hypervisor_credentials import plain
    wc = (hv.connection_config or {}).get("write_credential") or {}
    if not (wc.get("username") and wc.get("password")):
        return None
    return _versioned_cls()(host=hv.ip_address or hv.hostname, username=wc["username"],
                         password=plain(wc["password"]), port=hv.port or 443,
                         verify_ssl=bool((hv.connection_config or {}).get("verify_ssl", False)))


# ── Öneri ────────────────────────────────────────────────────────────────────

def _preview(action: RemediationAction, f: InfraFinding, params: Dict[str, Any]) -> str:
    if action.id == "vmw.snapshot_remove":
        names = [s.get("name") for s in _snapshots(f, params)]
        return f"{f.source_name}: {f.entity_name} → snapshot sil: {', '.join(str(n) for n in names) or '-'}"
    if action.id == "vmw.ntp_set_servers":
        return f"{f.source_name}: {f.entity_name} → NTP = {', '.join(params.get('servers') or [])}"
    return f"{f.source_name}: {f.entity_name} → {action.title}"


def _snapshots(f: InfraFinding, params: Dict[str, Any]) -> List[Dict[str, Any]]:
    snaps = (f.evidence or {}).get("snapshots") or []
    wanted = set(params.get("snapshot_refs") or [])
    if wanted:
        return [s for s in snaps if s.get("ref") in wanted]
    min_days = int(params.get("older_than_days") or 3)
    now = datetime.now(timezone.utc)
    out = []
    for s in snaps:
        try:
            d = datetime.fromisoformat(str(s.get("created")).replace("Z", "+00:00"))
            d = d if d.tzinfo else d.replace(tzinfo=timezone.utc)
            if (now - d).days > min_days and s.get("ref"):
                out.append(s)
        except ValueError:
            continue
    return out


def propose(db: Session, f: InfraFinding, *, action_id: Optional[str], params: Dict[str, Any], user) -> Dict[str, Any]:
    from app.models.agent_action import AgentAction
    aid = action_id or _DEFAULT_ACTION.get(f.check_id)
    action = ACTIONS.get(aid or "")
    if not action or f.check_id not in action.check_ids or f.platform not in action.platforms:
        return {"ok": False, "error": "Bu bulgu için izinli bir düzeltme işlemi yok"}
    if f.result != "fail" or not f.active:
        return {"ok": False, "error": "Yalnız açık (fail) bulgular için düzeltme önerilebilir"}
    hv = db.query(Hypervisor).filter(Hypervisor.id == f.source_id).first()
    if not hv or not write_credential_status(db, hv.id).get("configured"):
        return {"ok": False, "error": "Bu vCenter için ayrı yazma hesabı tanımlı değil (Ayarlar → Karar katmanı)"}
    params = dict(params or {})
    if action.id == "vmw.ntp_set_servers":
        servers = [str(s).strip() for s in (params.get("servers") or []) if str(s).strip()]
        if not servers:
            from app.services.findings.drafts import _majority_ntp
            servers = _majority_ntp(db, f)
        if not servers or len(servers) > 8 or any(len(s) > 255 or " " in s for s in servers):
            return {"ok": False, "error": "Geçerli NTP sunucu listesi gerekli"}
        params["servers"] = servers
    if action.id == "vmw.snapshot_remove" and not _snapshots(f, params):
        return {"ok": False, "error": "Silinecek snapshot seçilmedi / eşleşmedi"}
    args = {"finding_id": f.id, "action_id": action.id, "hypervisor_id": hv.id, "params": params}
    preview = _preview(action, f, params)
    call_id = f"call_{TOOL_NAME}"
    transcript = [
        {"role": "system", "content": "Sanallaştırma karar katmanı onaylı düzeltme akışı. Sonucu kısaca Türkçe özetle."},
        {"role": "user", "content": f"Bulgu #{f.id} ({f.title} · {f.entity_name}) için '{action.title}' işlemini uygula."},
        {"role": "assistant", "content": "", "tool_calls": [{"id": call_id, "type": "function", "function": {
            "name": TOOL_NAME, "arguments": json.dumps(args, ensure_ascii=False)}}]},
    ]
    rec = AgentAction(session_id=None, server_id=None, tool_name=TOOL_NAME, arguments=args,
                      risk_level="mutating", status="pending", preview=preview, requires_root=False,
                      result={}, transcript=transcript, model="")
    db.add(rec)
    db.commit()
    db.refresh(rec)
    return {"ok": True, "agent_action_id": rec.id, "action_id": action.id, "title": action.title,
            "preview": preview, "rollback": action.rollback_note,
            "note": "Onay bekliyor: Agent → Bekleyen aksiyonlar ekranından onaylayın."}


# ── Çalıştırma (yalnız Agent onayından sonra) ────────────────────────────────

def _host_refs(client, sess, url, host_name: str) -> Dict[str, Any]:
    rows = client.retrieve_properties(
        "HostSystem", ["name", "configManager.serviceSystem", "configManager.dateTimeSystem",
                       "config.dateTimeInfo.ntpConfig.server", "config.service.service"],
        name_filter=host_name, limit=20, soap_session=sess, soap_url=url)
    for r in rows:
        if str(r.get("name") or "").lower() == host_name.lower():
            return r
    return {}


def _soap_call(client, sess, url, body_inner: str) -> Tuple[bool, str]:
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:vim25="urn:vim25">
  <soapenv:Body>{body_inner}</soapenv:Body>
</soapenv:Envelope>"""
    try:
        r = sess.post(url, data=body.encode("utf-8"), headers={"Content-Type": "text/xml; charset=utf-8"},
                      verify=client.verify_ssl, timeout=60)
        if r.status_code == 200:
            return True, ""
        return False, f"HTTP {r.status_code}: {(r.text or '')[:300]}"
    except Exception as exc:
        return False, str(exc)


def _svc(row: Dict[str, Any], key: str) -> Dict[str, Any]:
    from app.services.findings.collectors import as_list
    for s in as_list(row.get("config.service.service")):
        if isinstance(s, dict) and s.get("key") == key:
            return s
    return {}


def execute(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.vmware.vcenter_client import _xml_text
    action = ACTIONS.get(str(args.get("action_id") or ""))
    f = db.query(InfraFinding).filter(InfraFinding.id == int(args.get("finding_id") or 0)).first()
    if not action or not f or f.check_id not in action.check_ids:
        return {"ok": False, "error": "İzinli olmayan / eşleşmeyen düzeltme isteği"}
    hv = db.query(Hypervisor).filter(Hypervisor.id == f.source_id).first()
    if not hv or hv.id != int(args.get("hypervisor_id") or 0):
        return {"ok": False, "error": "Hypervisor eşleşmedi"}
    client = _write_client(hv)
    if client is None:
        return {"ok": False, "error": "Yazma hesabı tanımlı değil"}
    params = args.get("params") or {}
    if action.id == "vmw.snapshot_remove":
        vm_ref = (f.entity_ref or "").split(":", 1)[-1]
        results = []
        for s in _snapshots(f, params):
            ok, msg = client.delete_snapshot(vm_ref, s["ref"])
            results.append({"snapshot": s.get("name"), "ref": s["ref"], "ok": ok, "message": msg})
        return {"ok": all(r["ok"] for r in results) and bool(results), "results": results,
                "rollback": action.rollback_note}
    from app.services.findings.collectors.vmware import versioned_session
    sess, url, _about = versioned_session(client)
    if not sess:
        return {"ok": False, "error": "Yazma hesabıyla vCenter oturumu açılamadı"}
    try:
        row = _host_refs(client, sess, url, f.entity_name or "")
        if not row:
            return {"ok": False, "error": f"Host bulunamadı: {f.entity_name}"}
        from app.services.findings.collectors.vmware import _ref_key
        svc_sys = _xml_text(_ref_key(row.get("configManager.serviceSystem")))
        dt_sys = _xml_text(_ref_key(row.get("configManager.dateTimeSystem")))
        if not svc_sys:
            return {"ok": False, "error": "Host servis sistemi okunamadı (yetki?)"}
        if action.id == "vmw.ntp_restart":
            before = _svc(row, "ntpd")
            ok1, e1 = _soap_call(client, sess, url, f'<vim25:UpdateServicePolicy><vim25:_this type="HostServiceSystem">{svc_sys}</vim25:_this><vim25:id>ntpd</vim25:id><vim25:policy>on</vim25:policy></vim25:UpdateServicePolicy>')
            ok2, e2 = _soap_call(client, sess, url, f'<vim25:RestartService><vim25:_this type="HostServiceSystem">{svc_sys}</vim25:_this><vim25:id>ntpd</vim25:id></vim25:RestartService>')
            return {"ok": ok1 and ok2, "error": e1 or e2 or None,
                    "rollback": {"previous_policy": before.get("policy"), "previous_running": before.get("running")}}
        if action.id == "vmw.ssh_stop":
            before = _svc(row, "TSM-SSH")
            ok1, e1 = _soap_call(client, sess, url, f'<vim25:StopService><vim25:_this type="HostServiceSystem">{svc_sys}</vim25:_this><vim25:id>TSM-SSH</vim25:id></vim25:StopService>')
            ok2, e2 = _soap_call(client, sess, url, f'<vim25:UpdateServicePolicy><vim25:_this type="HostServiceSystem">{svc_sys}</vim25:_this><vim25:id>TSM-SSH</vim25:id><vim25:policy>off</vim25:policy></vim25:UpdateServicePolicy>')
            return {"ok": ok1 and ok2, "error": e1 or e2 or None,
                    "rollback": {"previous_policy": before.get("policy"), "previous_running": before.get("running")}}
        if action.id == "vmw.ntp_set_servers":
            from app.services.findings.collectors import as_list
            prev = [str(x) for x in as_list(row.get("config.dateTimeInfo.ntpConfig.server")) if x]
            servers = [str(s) for s in params.get("servers") or []]
            srv_xml = "".join(f"<vim25:server>{_xml_text(s)}</vim25:server>" for s in servers)
            ok, err = _soap_call(client, sess, url, f'<vim25:UpdateDateTimeConfig><vim25:_this type="HostDateTimeSystem">{dt_sys}</vim25:_this><vim25:config><vim25:ntpConfig>{srv_xml}</vim25:ntpConfig></vim25:config></vim25:UpdateDateTimeConfig>')
            if ok:
                _soap_call(client, sess, url, f'<vim25:RestartService><vim25:_this type="HostServiceSystem">{svc_sys}</vim25:_this><vim25:id>ntpd</vim25:id></vim25:RestartService>')
            return {"ok": ok, "error": err or None, "rollback": {"previous_servers": prev}, "applied": servers}
        return {"ok": False, "error": "Bilinmeyen işlem"}
    finally:
        from app.services.findings.collectors.vmware import _soap_logout
        _soap_logout(client, sess, url)
