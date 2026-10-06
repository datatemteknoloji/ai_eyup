"""OpenShift olay zaman çizelgesi + kök neden adayları (deterministik; LLM yok).

Bir OCP incident'ı için tek eksende toplar:
  • DB'deki SystemEvent kayıtları (aynı cluster; aynı nesne / namespace)
  • aktif karar-katmanı bulguları (ClusterOperator, node condition, MCP, kota)
  • canlı (best-effort, salt okunur): pod durumu (lastState/waiting), K8s event'leri, pod log kuyruğu
Adaylar kural + kanıt sayısıyla sıralanır; log satırları sır maskelenerek kısaltılır.
Canlı okuma başarısızsa (RBAC/erişim) yalnız DB kanıtı kullanılır ve `live.error` döner.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

_ERR_RE = re.compile(r"(panic|fatal|error|exception|traceback|failed|denied|refused|timeout|timed out|"
                     r"oom|out of memory|cannot|unable to|no such file|x509|certificate)", re.I)
_SECRET_RE = re.compile(r"(?i)\b(password|passwd|secret|token|authorization|api[-_]?key|bearer)\b"
                        r"(?:\s*[:=]\s*|\s+)(?:bearer\s+|basic\s+)?\S+")
_OBJ_RE = re.compile(r"^(Pod|Node|Deployment|StatefulSet|DaemonSet|Job|ClusterOperator|PersistentVolumeClaim)/(.+)$")


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _iso(dt: Optional[datetime]) -> Optional[str]:
    return _aware(dt).isoformat() if dt else None


def _parse_ts(v: Any) -> Optional[datetime]:
    if not v:
        return None
    try:
        return _aware(datetime.fromisoformat(str(v).replace("Z", "+00:00")))
    except ValueError:
        return None


def _mask(line: str, limit: int = 300) -> str:
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}=***", line)[:limit]


def _targets(db: Session, inc) -> Tuple[Optional[int], List[Dict[str, str]], List[Any]]:
    """(cluster_id, [{kind,name,namespace}], related SystemEvent listesi)"""
    from app.models.event import SystemEvent
    ev_ids = [int(x) for x in (inc.related_events or []) if str(x).isdigit()]
    events = db.query(SystemEvent).filter(SystemEvent.id.in_(ev_ids)).all() if ev_ids else []
    cluster_id: Optional[int] = None
    objs: Dict[Tuple[str, str, str], Dict[str, str]] = {}

    def add(src: str, ns: str):
        m = _OBJ_RE.match(src or "")
        if m:
            objs[(m.group(1), m.group(2), ns or "")] = {"kind": m.group(1), "name": m.group(2), "namespace": ns or ""}

    for e in events:
        rd = e.raw_data if isinstance(e.raw_data, dict) else {}
        if rd.get("platform") != "openshift":
            continue
        if cluster_id is None and rd.get("cluster_id") is not None:
            try:
                cluster_id = int(rd["cluster_id"])
            except (TypeError, ValueError):
                pass
        add(str(rd.get("source_object") or ""), str(rd.get("namespace") or ""))
    pk = (inc.problem_key or "").split("|")
    if pk and pk[0] == "ocp":
        if cluster_id is None and len(pk) > 1 and pk[1].isdigit():
            cluster_id = int(pk[1])
        if len(pk) > 4:
            add(pk[4], pk[2])
    return cluster_id, list(objs.values()), events


def _live(cluster, targets: List[Dict[str, str]]) -> Dict[str, Any]:
    """Pod durumu + K8s event + log kuyruğu. Salt okunur; hata → live.error."""
    from app.services.openshift.cluster_ops import _events_for, _get_json, client_from_cluster, pod_logs
    out: Dict[str, Any] = {"ok": True, "pods": [], "events": [], "logs": [], "nodes": [], "error": None}
    try:
        client = client_from_cluster(cluster)
    except Exception as exc:
        return {**out, "ok": False, "error": str(exc)[:200]}
    for t in targets[:3]:
        if t["kind"] == "Pod" and t["namespace"]:
            pod = _get_json(client, f"/api/v1/namespaces/{t['namespace']}/pods/{t['name']}", timeout=15)
            info: Dict[str, Any] = {"name": t["name"], "namespace": t["namespace"], "found": bool(pod)}
            if pod:
                st = pod.get("status") or {}
                info.update({"phase": st.get("phase"), "node": (pod.get("spec") or {}).get("nodeName"),
                             "containers": []})
                for cs in (st.get("containerStatuses") or []) + (st.get("initContainerStatuses") or []):
                    last = (cs.get("lastState") or {}).get("terminated") or {}
                    wait = (cs.get("state") or {}).get("waiting") or {}
                    info["containers"].append({
                        "name": cs.get("name"), "ready": cs.get("ready"), "restarts": cs.get("restartCount"),
                        "waiting": wait.get("reason"), "last_reason": last.get("reason"),
                        "last_exit": last.get("exitCode"), "last_finished": last.get("finishedAt"),
                    })
                if info["containers"]:
                    bad = next((c for c in info["containers"] if c["waiting"] or c["last_reason"]), info["containers"][0])
                    lg = pod_logs(client, t["namespace"], t["name"], container=bad["name"], tail=200,
                                  previous=bool(bad.get("restarts")), timestamps=False)
                    if not lg.get("ok") and bad.get("restarts"):
                        lg = pod_logs(client, t["namespace"], t["name"], container=bad["name"], tail=200,
                                      previous=False, timestamps=False)
                    if lg.get("ok"):
                        lines = [ln for ln in (lg.get("logs") or "").splitlines() if ln.strip()]
                        err = [ln for ln in lines if _ERR_RE.search(ln)][-6:]
                        out["logs"].append({"pod": t["name"], "container": bad["name"], "lines": len(lines),
                                            "error_lines": [_mask(x) for x in err]})
                    else:
                        out["logs"].append({"pod": t["name"], "container": bad["name"], "lines": 0,
                                            "error_lines": [], "error": lg.get("error")})
                if info.get("node"):
                    out["nodes"].append(info["node"])
            out["pods"].append(info)
            for ev in _events_for(client, t["namespace"], kind="Pod", name=t["name"], limit=30):
                out["events"].append({**ev, "object": f"Pod/{t['name']}"})
        elif t["kind"] == "Node":
            out["nodes"].append(t["name"])
    for node in sorted(set(out["nodes"]))[:2]:
        for ev in _events_for(client, None, kind="Node", name=node, limit=20):
            out["events"].append({**ev, "object": f"Node/{node}"})
    return out


def _sev(t: Optional[str]) -> str:
    return "high" if (t or "").lower() == "warning" else "info"


def _candidates(db: Session, cluster_id: Optional[int], events_db: List[Any], live: Dict[str, Any],
                findings: List[Any]) -> List[Dict[str, Any]]:
    reasons: List[str] = []
    for e in events_db:
        rd = e.raw_data if isinstance(e.raw_data, dict) else {}
        reasons.append(str(rd.get("reason") or ""))
    msgs = [f"{ev.get('reason') or ''} {ev.get('message') or ''}" for ev in live.get("events", [])]
    blob = " ".join(reasons + msgs).lower()
    conts = [c for p in live.get("pods", []) for c in p.get("containers", [])]
    cands: List[Dict[str, Any]] = []

    def add(cid: str, title: str, conf: float, evidence: List[str], verify: List[str]):
        if evidence:
            cands.append({"id": cid, "title": title, "confidence": round(min(conf, 0.95), 2),
                          "evidence": [" ".join(str(e).split())[:240] for e in evidence[:6]], "verify": verify})

    oom = [c for c in conts if (c.get("last_reason") or "") == "OOMKilled" or c.get("last_exit") == 137]
    if oom or "oomkill" in blob:
        ev = [f"{c['name']}: son sonlanma {c.get('last_reason') or 'exit ' + str(c.get('last_exit'))}, restart {c.get('restarts')}" for c in oom]
        add("oom", "Container Memory limitini aşıp sonlandırıldı (OOMKilled)", 0.85, ev or ["OOM olayı görüldü"],
            ["Pod'un Memory limit/request değerlerini gerçek kullanımla karşılaştırın",
             "Namespace ResourceQuota ve node Memory baskısını kontrol edin"])
    pull = [c for c in conts if (c.get("waiting") or "") in ("ErrImagePull", "ImagePullBackOff")]
    if pull or "errimagepull" in blob or "imagepullbackoff" in blob or "failed to pull image" in blob:
        add("image_pull", "İmaj çekilemiyor (registry / pull secret / etiket)", 0.8,
            [f"{c['name']}: {c.get('waiting')}" for c in pull] or ["ImagePull olayı görüldü"],
            ["İmaj adı/etiketi ve registry erişimini doğrulayın", "Pull secret ve ImageContentSourcePolicy/mirror ayarını kontrol edin"])
    if "failedscheduling" in blob:
        add("scheduling", "Pod zamanlanamıyor (kaynak / taint / affinity)", 0.75,
            [m for m in msgs if "failedscheduling" in m.lower()][:2] or ["FailedScheduling olayı"],
            ["Node'ların allocatable ve request toplamını (Kapasite ekranı) kontrol edin", "Taint / nodeSelector / affinity kurallarını gözden geçirin"])
    if any(k in blob for k in ("failedmount", "failedattachvolume", "volumefailed", "multi-attach")):
        add("volume", "Volume bağlanamadı (PVC / CSI)", 0.75,
            [m for m in msgs if any(k in m.lower() for k in ("mount", "attach"))][:2] or ["Volume olayı görüldü"],
            ["PVC durumunu ve StorageClass/CSI sürücü pod'larını kontrol edin", "Volume'un başka node'a bağlı olup olmadığına bakın"])
    if "unhealthy" in blob and ("probe" in blob):
        add("probe", "Probe (liveness/readiness/startup) başarısız", 0.6,
            [m for m in msgs if "probe" in m.lower()][:2], ["Probe yolunu/portunu ve uygulama başlangıç süresini doğrulayın"])
    logs = [lg for lg in live.get("logs", []) if lg.get("error_lines")]
    crash = [c for c in conts if c.get("waiting") == "CrashLoopBackOff" or "crashloopbackoff" in blob]
    if crash or logs:
        ev = []
        for c in crash[:2]:
            ev.append(f"{c['name']}: restart {c.get('restarts')}"
                      + (f", son çıkış kodu {c.get('last_exit')}" if c.get("last_exit") is not None else ""))
        for lg in logs[:1]:
            ev += [f"log: {x}" for x in lg["error_lines"][-3:]]
        add("app_crash", "Uygulama başlangıçta/çalışırken hata veriyor (CrashLoop / log hatası)",
            0.55 + (0.15 if logs else 0), ev, ["Önceki container logunu (`oc logs --previous`) inceleyin",
                                                 "ConfigMap/Secret/env değişikliklerini kontrol edin"])
    node_bad = [f for f in findings if f.check_id == "ocp.node.condition" and f.result == "fail"
                and f.entity_name in set(live.get("nodes", []))]
    if node_bad:
        add("node", "Pod'un bulunduğu node sağlıksız", 0.7,
            [f"Node {f.entity_name}: {(f.evidence or {}).get('detail') or f.title}" for f in node_bad],
            ["Node condition ve kubelet durumunu doğrulayın (`oc describe node`)", "Gerekirse node'u drain edip inceleyin"])
    ops = [f for f in findings if f.check_id == "ocp.operator.health" and f.result == "fail"]
    if ops:
        add("operator", "ClusterOperator Degraded/Unavailable", 0.5,
            [f"{f.entity_name}: {(f.evidence or {}).get('detail') or f.title}" for f in ops[:4]],
            ["`oc get co` ve ilgili operatörün koşul mesajını inceleyin"])
    cands.sort(key=lambda c: (-c["confidence"], -len(c["evidence"])))
    return cands


def _config_changes(db: Session, cluster_id: int, start: datetime, end: datetime) -> List[Dict[str, Any]]:
    from app.models.infra_finding import VirtConfigSnapshot as V
    from app.services.virt_config_drift import diff_configs
    out: List[Dict[str, Any]] = []
    rows = db.query(V).filter(V.platform == "ocp", V.source_id == cluster_id,
                              V.captured_at >= start, V.captured_at <= end).all()
    for s in rows:
        prev = (db.query(V).filter(V.platform == s.platform, V.source_id == s.source_id,
                                   V.entity_kind == s.entity_kind, V.entity_ref == s.entity_ref,
                                   V.captured_at < s.captured_at).order_by(V.captured_at.desc()).first())
        if prev is None:
            continue
        diff = diff_configs((prev.payload or {}).get("config") or {}, (s.payload or {}).get("config") or {})
        if diff:
            out.append({"t": _iso(s.captured_at), "entity": s.entity_name,
                        "title": f"{s.entity_kind} {s.entity_name}: {len(diff)} yapılandırma değişikliği",
                        "detail": "; ".join(f"{d['path']}: {d['old']} → {d['new']}" for d in diff[:5])[:500]})
    return out


def build_ocp_incident_timeline(db: Session, *, incident_id: int, before_min: int = 120,
                                after_min: int = 60, live_read: bool = True) -> Dict[str, Any]:
    from app.models.event import Incident, SystemEvent
    from app.models.infra_finding import InfraFinding
    from app.models.openshift import OpenShiftCluster
    inc = db.query(Incident).filter(Incident.id == incident_id).first()
    if not inc:
        return {"ok": False, "not_found": True, "error": "Olay bulunamadı"}
    cluster_id, targets, rel = _targets(db, inc)
    if cluster_id is None and not targets:
        return {"ok": True, "applicable": False, "incident_id": inc.id,
                "note": "Olayda OpenShift nesnesi yok — zaman çizelgesi uygulanmaz."}
    at = _aware(inc.created_at) or datetime.now(timezone.utc)
    start, end = at - timedelta(minutes=before_min), at + timedelta(minutes=after_min)
    items: List[Dict[str, Any]] = []

    names = {t["name"] for t in targets}
    nss = {t["namespace"] for t in targets if t["namespace"]}
    seen = set()
    q = (db.query(SystemEvent).filter(SystemEvent.created_at >= start, SystemEvent.created_at <= end)
         .order_by(SystemEvent.created_at).limit(4000).all())
    for e in list(rel) + q:
        if e.id in seen:
            continue
        rd = e.raw_data if isinstance(e.raw_data, dict) else {}
        if rd.get("platform") != "openshift":
            continue
        if cluster_id is not None and rd.get("cluster_id") not in (cluster_id, str(cluster_id)):
            continue
        obj = str(rd.get("source_object") or "")
        related = e in rel or obj.split("/", 1)[-1] in names or (rd.get("namespace") in nss and rd.get("namespace"))
        if not related:
            continue
        seen.add(e.id)
        items.append({"t": _iso(e.created_at), "kind": "event", "source": "olay", "entity": obj,
                      "title": (e.title or "")[:300], "detail": (e.description or "")[:400],
                      "severity": e.severity or "info", "ref": {"event_id": e.id}})

    findings: List[Any] = []
    if cluster_id is not None:
        findings = (db.query(InfraFinding).filter(InfraFinding.platform == "ocp", InfraFinding.source_id == cluster_id,
                                                  InfraFinding.active.is_(True), InfraFinding.result == "fail",
                                                  InfraFinding.category.in_(("health", "capacity", "drift"))).all())
        for f in findings:
            items.append({"t": _iso(f.last_seen), "kind": "finding", "source": "bulgu", "entity": f.entity_name,
                          "title": f.title, "detail": (f.evidence or {}).get("detail") or "",
                          "severity": f.severity or "medium", "ref": {"finding_id": f.id}})

    cfg_changes: List[Dict[str, Any]] = []
    if cluster_id is not None:
        cfg_changes = _config_changes(db, cluster_id, start, end)
        for c in cfg_changes:
            items.append({"t": c["t"], "kind": "config_change", "source": "yapılandırma", "entity": c["entity"],
                          "title": c["title"], "detail": c["detail"], "severity": "medium", "ref": {}})

    live: Dict[str, Any] = {"ok": False, "pods": [], "events": [], "logs": [], "nodes": [], "error": "okunmadı"}
    if live_read and cluster_id is not None:
        cl = db.query(OpenShiftCluster).filter(OpenShiftCluster.id == cluster_id).first()
        if cl:
            live = _live(cl, targets)
        else:
            live["error"] = "Cluster kaydı bulunamadı"
    for ev in live.get("events", []):
        ts = _parse_ts(ev.get("last_timestamp"))
        if ts and not (start <= ts <= end):
            continue
        items.append({"t": _iso(ts), "kind": "k8s_event", "source": "k8s", "entity": ev.get("object"),
                      "title": f"{ev.get('reason')}: {(ev.get('message') or '')[:200]}",
                      "detail": "", "severity": _sev(ev.get("type")), "ref": {"count": ev.get("count")}})
    for lg in live.get("logs", []):
        for ln in lg.get("error_lines", [])[-3:]:
            items.append({"t": None, "kind": "log", "source": "log", "entity": f"{lg['pod']}/{lg['container']}",
                          "title": ln, "detail": "", "severity": "info", "ref": {}})
    items.sort(key=lambda x: (x["t"] is None, x["t"] or ""))

    cands = _candidates(db, cluster_id, rel, live, findings)
    if cfg_changes:
        cands.append({"id": "config_change", "title": "Pencerede yapılandırma değişikliği var", "confidence": 0.45,
                      "evidence": [f"{c['title']}: {c['detail']}"[:240] for c in cfg_changes[:5]],
                      "verify": ["Değişikliğin planlı olup olmadığını doğrulayın (Değişiklikler ekranı)",
                                 "Onaylıysa baseline'ı güncelleyin, değilse geri alın"]})
        cands.sort(key=lambda c: (-c["confidence"], -len(c["evidence"])))
    return {
        "ok": True, "applicable": True, "incident_id": inc.id, "incident_title": inc.title,
        "window": {"at": _iso(at), "start": _iso(start), "end": _iso(end), "before_min": before_min,
                   "after_min": after_min},
        "scope": {"hosts": sorted({n for n in live.get("nodes", [])}), "vms": [f"{t['kind']}/{t['name']}" for t in targets],
                  "datastores": sorted(nss)},
        "items": items[:500], "candidates": cands,
        "live": {"ok": live.get("ok"), "error": live.get("error"),
                 "pods": live.get("pods"), "log_summary": [{k: v for k, v in lg.items() if k != "error_lines"}
                                                           for lg in live.get("logs", [])]},
        "notes": ["Adaylar kural + kanıt sayısıyla sıralanır; kesin kök neden değildir.",
                  "Pod logu yalnız hata satırları, sırlar maskelenmiş ve kısaltılmış olarak gösterilir.",
                  "Canlı okuma başarısızsa yalnız DB olayları ve bulgular kullanılır."],
    }
