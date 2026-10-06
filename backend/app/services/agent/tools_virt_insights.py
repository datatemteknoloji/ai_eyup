"""Sanallaştırma karar katmanı sohbet araçları (READ_ONLY, DB/motor).

Sayılar deterministik motorlardan gelir (virt_capacity_planner, virt_placement,
virt_reclaim, findings store, virt_incident_timeline); LLM yalnız anlatır.
`virt_remediate` LLM'e görünmez (llm_visible=False) — yalnız
/virt-insights/remediation/propose ile açılan AgentAction onayında çalışır.
"""
from __future__ import annotations

from typing import Any, Dict

from sqlalchemy.orm import Session

from app.services.agent.tools import RiskLevel, Tool


def _int(v: Any, default=None):
    try:
        return int(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _float(v: Any, default=None):
    try:
        return float(v) if v not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _slim_cluster(c: Dict[str, Any]) -> Dict[str, Any]:
    fc = (c.get("forecast") or {}).get("memory") or {}
    return {
        "platform": c.get("platform"), "hypervisor": c.get("hypervisor"), "cluster": c.get("cluster"),
        "hosts": c.get("hosts_total"), "hosts_usable": c.get("hosts_usable"),
        "memory": {k: (c.get("memory") or {}).get(k) for k in ("total_gb", "used_gb", "effective_gb", "effective_used_pct", "allocated_gb")},
        "cpu": {k: (c.get("cpu") or {}).get(k) for k in ("total_cores", "used_cores", "effective_used_pct", "vcpu_allocated", "vcpu_ratio")},
        "ha": c.get("ha"), "n_plus_one": c.get("n_plus_one"),
        "memory_runway": {k: fc.get(k) for k in ("days", "uncertainty", "confidence", "threshold")} if fc else None,
        "actions": [{k: a.get(k) for k in ("step", "kind", "title", "detail", "hosts_needed")} for a in c.get("actions") or []],
    }


def _capacity_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services import virt_capacity_planner as cp
        hv_id = _int(args.get("hypervisor_id"))
        cluster = (args.get("cluster") or "").strip() or None
        vcpu, mem = _int(args.get("vcpu")), _float(args.get("memory_gb"))
        if vcpu or mem:
            res = cp.simulate(db, vcpu=vcpu or 1, memory_gb=mem or 0, disk_gb=_float(args.get("disk_gb"), 0.0),
                              count=_int(args.get("count"), 1), hypervisor_id=hv_id, cluster=cluster)
            res["results"] = (res.get("results") or [])[:8]
            return {"ok": True, "mode": "what_if", **res}
        cap = cp.build_capacity(db, hypervisor_id=hv_id, cluster=cluster,
                                platform=(args.get("platform") or None))
        clusters = sorted(cap.get("clusters") or [],
                          key=lambda c: -((c.get("memory") or {}).get("effective_used_pct") or 0))
        return {
            "ok": True, "mode": "capacity", "method": cap.get("method"), "thresholds": cap.get("thresholds"),
            "clusters": [_slim_cluster(c) for c in clusters[:12]],
            "datastores_top": [{k: d.get(k) for k in ("hypervisor", "name", "usage_pct", "free_gb", "capacity_gb", "provisioned_pct")}
                               | {"runway_days": (d.get("forecast") or {}).get("days")}
                               for d in (cap.get("datastores") or [])[:10]],
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _placement_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.virt_placement import recommend_placement
        return recommend_placement(
            db, vm_name=(args.get("vm_name") or "").strip() or None, vcpu=_int(args.get("vcpu")),
            memory_gb=_float(args.get("memory_gb")), disk_gb=_float(args.get("disk_gb")),
            hypervisor_id=_int(args.get("hypervisor_id")), cluster=(args.get("cluster") or "").strip() or None,
            top_n=max(1, min(_int(args.get("top_n"), 5), 10)))
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _reclaim_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.virt_reclaim import build_reclaim
        rep = build_reclaim(db, hypervisor_id=_int(args.get("hypervisor_id")), platform=args.get("platform") or None,
                            cluster=(args.get("cluster") or "").strip() or None)
        lim = max(1, min(_int(args.get("limit"), 10), 30))
        out = {"ok": True, "summary": rep.get("summary"), "criteria": rep.get("criteria"), "notes": rep.get("notes")}
        for key in ("powered_off", "idle", "oversized", "snapshots", "orphans", "isos", "unused_datastores"):
            out[key] = (rep.get(key) or [])[:lim]
        return out
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _findings_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.findings.store import query_findings, summarize_findings
        plats = ["vmware", "olvm", "ocp_virt"]
        plat = (args.get("platform") or "").strip() or None
        cat = (args.get("category") or "").strip() or None
        rows = query_findings(db, category=cat, platform=plat, platforms=None if plat else plats,
                              cluster=(args.get("cluster") or "").strip() or None,
                              entity=(args.get("entity") or "").strip() or None,
                              severity_min=(args.get("severity_min") or None),
                              limit=max(1, min(_int(args.get("limit"), 25), 80)))
        slim = [{k: r.get(k) for k in ("id", "platform", "source_name", "cluster_name", "category", "check_id",
                                       "entity_name", "severity", "title", "detail", "recommendation", "first_seen")}
                for r in rows]
        return {"ok": True, "summary": summarize_findings(db, platforms=[plat] if plat else plats),
                "findings": slim,
                "note": "Bulgular saatlik toplanır (Ayarlar → virt_insights_interval_sec); 'not_measurable' API'nin göstermediği kontroldür."}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _timeline_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from app.services.virt_incident_timeline import build_incident_timeline, build_timeline
        before, after = max(10, min(_int(args.get("before_min"), 120), 720)), max(0, min(_int(args.get("after_min"), 60), 360))
        inc = _int(args.get("incident_id"))
        if inc:
            res = build_incident_timeline(db, incident_id=inc, before_min=before, after_min=after)
        else:
            res = build_timeline(db, host=(args.get("host") or None), vm=(args.get("vm") or None),
                                 datastore=(args.get("datastore") or None), at=(args.get("at") or None),
                                 before_min=before, after_min=after)
        if isinstance(res.get("items"), list):
            res["items"] = res["items"][:60]
        return res
    except Exception as e:
        return {"ok": False, "error": str(e)}


def _remediate_handler(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.virt_remediation import execute
    try:
        return execute(db, args, ctx)
    except Exception as e:
        return {"ok": False, "error": str(e)}


_SCOPE = {
    "hypervisor_id": {"type": "integer", "description": "Hypervisor (vCenter / OLVM / OCP Virt) id — boşsa tümü"},
    "cluster": {"type": "string", "description": "Cluster adı (tam ad)"},
}

VIRT_INSIGHTS_TOOLS: Dict[str, Tool] = {
    "virt_capacity_simulate": Tool(
        name="virt_capacity_simulate",
        description=(
            "SANALLAŞTIRMA KAPASİTE PLANLAMA (READ-ONLY, DB). vcpu/memory_gb verilirse WHAT-IF: "
            "'şu profilde N VM gelirse hangi cluster'a sığar' — N+1 sonrası, effective doluluk, datastore. "
            "Verilmezse cluster başına effective kapasite (HA rezervi düşülmüş), N+1 durumu, Memory tükenme "
            "tahmini (gün aralığı) ve ucuzdan pahalıya aksiyon sırası (geri kazanım → right-size → taşıma → "
            "yatırım/host adedi). 'kapasite yeter mi', 'kaç host lazım', 'ne zaman dolar', "
            "'10 tane 8 vCPU 32 GB VM gelirse' sorularında kullan."
        ),
        parameters={"type": "object", "properties": {
            **_SCOPE,
            "platform": {"type": "string", "enum": ["vmware", "olvm", "ocp_virt"]},
            "vcpu": {"type": "integer"}, "memory_gb": {"type": "number"},
            "disk_gb": {"type": "number"}, "count": {"type": "integer", "description": "VM adedi (varsayılan 1)"},
        }, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_capacity_handler, direct_label="Kapasite planlama",
    ),
    "virt_placement_recommend": Tool(
        name="virt_placement_recommend",
        description=(
            "VM YERLEŞİM ÖNERİSİ (READ-ONLY). Var olan VM (vm_name) veya yeni profil (vcpu+memory_gb) için "
            "host/cluster/datastore sıralaması: bakım, boş Memory, N+1, zorunlu DRS kuralları / OLVM affinity, "
            "datastore erişimi filtre; Memory/CPU/ready/latency/denge skoru. Taşımaz, yalnız önerir. "
            "'bu VM'i nereye taşıyayım', 'yeni VM hangi hosta' sorularında kullan."
        ),
        parameters={"type": "object", "properties": {
            **_SCOPE, "vm_name": {"type": "string"}, "vcpu": {"type": "integer"},
            "memory_gb": {"type": "number"}, "disk_gb": {"type": "number"}, "top_n": {"type": "integer"},
        }, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_placement_handler, direct_label="Yerleşim önerisi",
    ),
    "virt_reclaim_summary": Tool(
        name="virt_reclaim_summary",
        description=(
            "ATIL KAYNAK / GERİ KAZANIM (READ-ONLY). Kapalı VM'ler (son açılma), atıl ve aşırı boyutlu VM'ler "
            "(p95 tabanlı right-size), eski snapshot'lar (yaş, boyut, büyüme), sahipsiz VMDK/disk/PVC, kullanılmayan "
            "ISO ve datastore'lar; toplam geri kazanılabilir Memory/vCPU/disk. 'ne kadar yer açabilirim', "
            "'atıl VM', 'zombi disk', 'eski snapshot' sorularında kullan. Silme YAPMAZ."
        ),
        parameters={"type": "object", "properties": {
            **_SCOPE, "platform": {"type": "string", "enum": ["vmware", "olvm", "ocp_virt"]},
            "limit": {"type": "integer", "description": "Liste başına satır (varsayılan 10)"},
        }, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_reclaim_handler, direct_label="Geri kazanım özeti",
    ),
    "virt_health_findings": Tool(
        name="virt_health_findings",
        description=(
            "KONFİGÜRASYON / EN İYİ UYGULAMA / DONANIM / ZAFİYET / UYUM BULGULARI (READ-ONLY, DB). "
            "Kategoriler: health (HA, admission, DRS, NTP, DNS, vMotion, uplink, multipath, fencing, eviction), "
            "hardware, reclaim, drift (baseline sapması), vuln (yüklü CVE paketi), known_issue (KB), upgrade "
            "(EOL/HCL), compliance (SSH/shell/lockdown/syslog), capacity. 'best practice', 'yanlış konfigürasyon', "
            "'NTP sorunu', 'HA kapalı mı', 'hangi host zafiyetli', 'denetimde ne çıkar' sorularında kullan."
        ),
        parameters={"type": "object", "properties": {
            **_SCOPE, "platform": {"type": "string", "enum": ["vmware", "olvm", "ocp_virt"]},
            "category": {"type": "string", "enum": ["health", "hardware", "reclaim", "drift", "vuln",
                                                    "known_issue", "upgrade", "compliance", "capacity"]},
            "entity": {"type": "string", "description": "Host / VM / datastore adı (içerir)"},
            "severity_min": {"type": "string", "enum": ["low", "medium", "high", "critical"]},
            "limit": {"type": "integer"},
        }, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_findings_handler, direct_label="Karar katmanı bulguları",
    ),
    "virt_incident_timeline": Tool(
        name="virt_incident_timeline",
        description=(
            "OLAY ZAMAN ÇİZELGESİ + KÖK NEDEN ADAYLARI (READ-ONLY). incident_id veya host/vm/datastore + "
            "zaman (at, ISO) için öncesi/sonrası penceresinde event, alarm, metrik eşik geçişleri, bağlantı "
            "değişimleri, konfigürasyon değişiklikleri ve Zabbix problemlerini sıralar; güven puanlı aday "
            "nedenler ve doğrulama adımları verir. 'dün 14:00 ne oldu', 'bu olayın kök nedeni', "
            "'neden yavaşladı o saatte' sorularında kullan. Kesin hüküm değil — aday listesi."
        ),
        parameters={"type": "object", "properties": {
            "incident_id": {"type": "integer"}, "host": {"type": "string"}, "vm": {"type": "string"},
            "datastore": {"type": "string"}, "at": {"type": "string", "description": "ISO zaman; boşsa şimdi"},
            "before_min": {"type": "integer"}, "after_min": {"type": "integer"},
        }, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_timeline_handler, direct_label="Olay zaman çizelgesi",
    ),
    "virt_remediate": Tool(
        name="virt_remediate",
        description="Karar katmanı onaylı düzeltme (yalnız sunucu tarafı öneri akışı).",
        parameters={"type": "object", "properties": {}, "required": []},
        risk_level=RiskLevel.MUTATING, build_command=lambda a: "",
        direct_handler=_remediate_handler, direct_label="Onaylı düzeltme (karar katmanı)",
        llm_visible=False,
    ),
}
