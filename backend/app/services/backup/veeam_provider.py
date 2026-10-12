"""Veeam VBR sağlayıcıları: gerçek (`veeam_vbr`) ve demo/fixture (`veeam_demo`).

İkisi de AYNI normalizasyonu kullanır (``collect_snapshot``); fark yalnız
taşıyıcıdır: gerçek → ``VeeamRestClient`` (HTTPS REST), demo → ``DemoTransport``
(bellekte, Veeam-şekilli sentetik yanıt — GERÇEK DEĞİL, UI'da "DEMO" etiketli).

Alanlar yalnız ``veeam_api_ref.ENDPOINTS[*].fields_used`` içindekilerdir.
"""
from __future__ import annotations

import json
import re
import zlib
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from app.core.encryption import decrypt_secret
from app.services.backup.protocol import ConnTestResult, ProviderHealth, SyncCursor
from app.services.backup.registry import parse_meta, register_provider
from app.services.backup.veeam_api_ref import DEFAULT_PORT, DEFAULT_REVISION
from app.services.backup.veeam_cfg import (
    host_from_backup_object_path, parse_job_config, parse_proxy_config, parse_proxy_state,
)
from app.services.backup.veeam_client import VeeamApiError, VeeamRestClient, VeeamTransport, paged

KIND_REAL = "veeam_vbr"
KIND_DEMO = "veeam_demo"
CAPS = {"backup"}
DEFAULT_LOOKBACK_DAYS = 30
SESSION_WINDOW_HOURS = 24          # oturumlar sliding pencere (çalışan oturum sonradan biter)
SESSION_FIRST_DAYS = 14
RP_OVERLAP_MIN = 10
MAX_RESTORE_POINTS = 20000
MAX_OBJECT_RP_CALLS = 200          # F.1: sync başına en fazla bu kadar nesne-başı restorePoints çağrısı
OBJECT_RP_LIMIT = 5                # nesne başına en yeni N nokta (orderColumn=CreationTime, orderAsc=false)
_MOREF_RX = re.compile(r"^vm-\d+$")


# ── yardımcılar ──────────────────────────────────────────────────────────────

def parse_ts(v: Any) -> Optional[datetime]:
    """Veeam zaman damgası → aware UTC. Saat dilimsiz değerler UTC varsayılır (belirsiz: api_ref #7)."""
    if not v or not isinstance(v, str):
        return None
    s = v.strip().replace("Z", "+00:00")
    m = re.match(r"^(.*?T[\d:]+)(\.\d+)?(.*)$", s)
    if m:  # kesir 6 haneye sabitle (7 haneli örnekler var)
        frac = (m.group(2) or "")[:7].ljust(7, "0") if m.group(2) else ""
        s = f"{m.group(1)}{frac}{m.group(3)}"
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def job_kind(vbr_type: str) -> str:
    t = vbr_type or ""
    if "Replica" in t:
        return "replica"
    if "Copy" in t:
        return "copy"
    return "backup"


# ── normalize edilmiş anlık görüntü ──────────────────────────────────────────

def _extra(tp: VeeamTransport, key: str, snap: Dict[str, Any], params: Optional[Dict[str, Any]] = None,
           *, max_items: int = 2000, path: Optional[Dict[str, str]] = None) -> Optional[List[Dict[str, Any]]]:
    """F.1 tamamlayıcı okuma: yetki/sunucu hatası senkronu DÜŞÜRMEZ; ``snap['access'][key]`` işaretlenir.

    forbidden → alanlar "ölçülemedi (yetki)"; diğer API hataları → "ölçülemedi (hata)".
    auth/network/tls yeniden fırlatılır (ana okumalarla aynı davranış).
    """
    access: Dict[str, str] = snap.setdefault("access", {})
    try:
        rows = list(paged(tp, key, params, max_items=max_items, path=path))
    except VeeamApiError as e:
        if e.kind in ("auth", "network", "tls"):
            raise
        access[key] = "forbidden" if e.kind == "forbidden" else "error"
        if e.kind == "forbidden":
            snap["warnings"].append(f"{key} okunamadı (yetki yok) — ilgili alanlar 'ölçülemedi (yetki)'.")
        else:
            snap["warnings"].append(f"{key} okunamadı ({e.kind}) — ilgili alanlar 'ölçülemedi'.")
        return None
    access.setdefault(key, "ok")
    return rows


def collect_snapshot(tp: VeeamTransport, cursor: Dict[str, Any], *, lookback_days: int = DEFAULT_LOOKBACK_DAYS,
                     now: Optional[datetime] = None) -> Dict[str, Any]:
    now = now or datetime.now(timezone.utc)
    warnings: List[str] = []
    snap: Dict[str, Any] = {"server": None, "jobs": [], "repos": [], "sessions": [], "backup_job": {},
                            "objects": [], "restore_points": [], "warnings": warnings, "access": {}}
    try:
        si = tp.get_json("server_info")
        snap["server"] = {"name": si.get("name"), "build": si.get("buildVersion"), "platform": si.get("platform")}
        snap["access"]["server_info"] = "ok"
    except VeeamApiError as e:
        if e.kind != "forbidden":
            raise
        snap["access"]["server_info"] = "forbidden"
        warnings.append("serverInfo okunamadı (Backup Viewer rolü yetkisiz) — VBR sürümü tespit edilemedi.")

    for j in paged(tp, "jobs_states"):
        snap["jobs"].append({
            "id": str(j.get("id")), "name": j.get("name") or "", "type": j.get("type") or "",
            "kind": job_kind(j.get("type") or ""), "status": j.get("status"),
            "last_result": j.get("lastResult"), "last_run": parse_ts(j.get("lastRun")),
            "next_run": parse_ts(j.get("nextRun")), "schedule": j.get("nextRunPolicy"),
            "repository_id": j.get("repositoryId"), "repository_name": j.get("repositoryName"),
            "objects_count": j.get("objectsCount"), "enabled": j.get("status") != "Disabled",
        })
    for r in paged(tp, "repositories_states"):
        cap, free = r.get("capacityGB"), r.get("freeGB")
        snap["repos"].append({
            "id": str(r.get("id")), "name": r.get("name") or "", "type": r.get("type"),
            "capacity_gb": cap if isinstance(cap, (int, float)) else None,
            "free_gb": free if isinstance(free, (int, float)) else None,
            "is_online": r.get("isOnline"),
        })
    since_s = now - timedelta(hours=SESSION_WINDOW_HOURS) if cursor.get("rp_after") else now - timedelta(days=SESSION_FIRST_DAYS)
    for s in paged(tp, "sessions", {"typeFilter": "BackupJob", "createdAfterFilter": _iso(since_s),
                                    "orderColumn": "CreationTime", "orderAsc": "false"}, max_items=2000):
        res = s.get("result") if isinstance(s.get("result"), dict) else {}
        snap["sessions"].append({
            "id": str(s.get("id")), "job_id": s.get("jobId"), "type": s.get("sessionType"),
            "state": s.get("state"), "created": parse_ts(s.get("creationTime")),
            "ended": parse_ts(s.get("endTime")), "result": res.get("result"), "message": res.get("message"),
        })
    for b in paged(tp, "backups"):
        if b.get("id") and b.get("jobId"):
            snap["backup_job"][str(b["id"])] = str(b["jobId"])
    for o in paged(tp, "backup_objects", {"platformNameFilter": "VMware"}):
        if o.get("type") != "VM":
            continue
        oid = o.get("objectId")
        snap["objects"].append({
            "id": str(o.get("id")), "name": o.get("name") or "", "platform": "vmware",
            # api_ref #1: objectId UUID veya moref olabilir — yalnız vm-<n> biçimi moref sayılır
            "object_ref": oid if isinstance(oid, str) and _MOREF_RX.match(oid) else None,
            "path": o.get("path"), "restore_points_count": o.get("restorePointsCount"),
            # F.1: path'in ilk bölümü vCenter hostName'i (doküman örneği; sahada doğrulanmadı — api_ref #8)
            "host_name": host_from_backup_object_path(o.get("path")),
        })
    after = parse_ts(cursor.get("rp_after")) or (now - timedelta(days=max(1, lookback_days)))
    newest: Optional[datetime] = None
    for rp in paged(tp, "restore_points", {"platformNameFilter": "VMware", "createdAfterFilter": _iso(after),
                                           "orderColumn": "CreationTime", "orderAsc": "false"},
                    max_items=MAX_RESTORE_POINTS):
        ts = parse_ts(rp.get("creationTime"))
        if ts is None:
            continue
        newest = ts if newest is None or ts > newest else newest
        snap["restore_points"].append({"id": str(rp.get("id")), "name": rp.get("name") or "",
                                       "type": rp.get("type"), "created": ts, "backup_id": rp.get("backupId")})
    _collect_f1(tp, snap, now)
    snap["next_cursor"] = {"rp_after": _iso((newest or after) - timedelta(minutes=RP_OVERLAP_MIN))}
    return snap


def _collect_f1(tp: VeeamTransport, snap: Dict[str, Any], now: datetime) -> None:
    """F.1: iş yapılandırması, proxy'ler, depo türleri, nesne-başı restore point (mevcut senkron döngüsünde)."""
    snap["job_config"], snap["proxies"], snap["repo_info"], snap["object_rps"] = {}, [], {}, {}
    # Jobs → Get All Jobs (Viewer dahil). Şifreleme/CBT/saklama/GFS/zamanlama/yeniden deneme/app-aware.
    rows = _extra(tp, "jobs", snap)
    if rows is not None:
        for j in rows:
            if j.get("id"):
                snap["job_config"][str(j["id"])] = parse_job_config(j)
    # Proxies → Get All Proxy States + Get All Proxies (Viewer dahil)
    states = _extra(tp, "proxies_states", snap)
    cfgs = _extra(tp, "proxies", snap)
    if states is not None:
        by_cfg = {str(c.get("id")): parse_proxy_config(c) for c in (cfgs or [])}
        for st in states:
            px = parse_proxy_state(st)
            px.update({k: v for k, v in by_cfg.get(px["id"], {}).items() if k != "id"})
            snap["proxies"].append(px)
    # Repositories → Get All Repositories: yalnız description/type (immutability alanı dokümanda yok)
    repos = _extra(tp, "repositories", snap)
    if repos is not None:
        for r in repos:
            if r.get("id"):
                snap["repo_info"][str(r["id"])] = {"type": r.get("type")}
    # Backup Objects → restorePoints: toplu liste penceresinde nokta bulunamayan nesneler için nesne-başı (sınırlı)
    seen = {rp["name"] for rp in snap["restore_points"]}
    todo = [o for o in snap["objects"] if o["name"] not in seen and (o.get("restore_points_count") or 0) > 0]
    for ob in todo[:MAX_OBJECT_RP_CALLS]:
        pts = _extra(tp, "object_restore_points", snap, {"orderColumn": "CreationTime", "orderAsc": "false"},
                     max_items=OBJECT_RP_LIMIT, path={"id": ob["id"]})
        if pts is None:
            break   # yetki/hata: tekrar deneme yok (ek yük yok)
        times = [t for t in (parse_ts(x.get("creationTime")) for x in pts) if t]
        if times:
            snap["object_rps"][ob["id"]] = max(times)
    if len(todo) > MAX_OBJECT_RP_CALLS:
        snap["warnings"].append(f"{len(todo) - MAX_OBJECT_RP_CALLS} nesne için restore point sorgusu bu senkronda atlandı (üst sınır {MAX_OBJECT_RP_CALLS}).")


# ── sağlayıcılar ─────────────────────────────────────────────────────────────

class _Base:
    kind = KIND_REAL

    def __init__(self, instance: Any):
        self.instance = instance
        self.meta = parse_meta(instance) if instance is not None else {}
        self.last_snapshot: Optional[Dict[str, Any]] = None

    def capabilities(self) -> Set[str]:
        return set(CAPS)

    def _transport(self) -> VeeamTransport:  # pragma: no cover - alt sınıf
        raise NotImplementedError

    def _lookback(self) -> int:
        try:
            return max(1, int(self.meta.get("lookback_days") or DEFAULT_LOOKBACK_DAYS))
        except (TypeError, ValueError):
            return DEFAULT_LOOKBACK_DAYS

    def sync(self, cursor: SyncCursor) -> SyncCursor:
        cur: Dict[str, Any] = {}
        if cursor and cursor.token:
            try:
                cur = json.loads(cursor.token)
            except ValueError:
                cur = {}
        snap = collect_snapshot(self._transport(), cur, lookback_days=self._lookback())
        self.last_snapshot = snap
        return SyncCursor(token=json.dumps(snap.get("next_cursor") or {}), updated_at=datetime.now(timezone.utc))

    def health(self) -> ProviderHealth:
        return ProviderHealth(ok=True)

    def test_connection(self) -> ConnTestResult:
        try:
            tp = self._transport()
            details: Dict[str, Any] = {"api_revision": self.meta.get("api_revision") or DEFAULT_REVISION}
            try:
                si = tp.get_json("server_info")
                details.update(server_name=si.get("name"), build=si.get("buildVersion"))
            except VeeamApiError as e:
                if e.kind != "forbidden":
                    raise
                details["version_note"] = "VBR sürümü okunamadı: serverInfo yalnız Backup Administrator rolüne açık."
            jobs = tp.get_json("jobs_states", {"limit": 1})
            repos = tp.get_json("repositories_states", {"limit": 1})
            objs = tp.get_json("backup_objects", {"platformNameFilter": "VMware", "limit": 50})
            vms = [o.get("name") for o in (objs.get("data") or []) if isinstance(o, dict) and o.get("type") == "VM"]
            details.update(jobs=(jobs.get("pagination") or {}).get("total"),
                           repositories=(repos.get("pagination") or {}).get("total"),
                           sample_vms=vms[:3])
            return ConnTestResult(True, details["api_revision"], "Bağlantı başarılı", details)
        except VeeamApiError as e:
            return ConnTestResult(False, None, str(e), {"error_kind": e.kind})
        finally:
            close = getattr(getattr(self, "_client", None), "logout", None)
            if close:
                close()


class VeeamVbrProvider(_Base):
    kind = KIND_REAL

    def _creds(self) -> Tuple[str, str]:
        raw = decrypt_secret(self.instance.credential_ref) if self.instance.credential_ref else None
        try:
            j = json.loads(raw or "{}")
        except ValueError:
            j = {}
        return str(j.get("username") or ""), str(j.get("password") or "")

    def _transport(self) -> VeeamTransport:
        u, p = self._creds()
        if not u or not p:
            raise VeeamApiError("auth", "Kullanıcı adı / parola tanımlı değil")
        verify: Any = bool(self.instance.verify_ssl)
        ca = self.meta.get("ca_bundle_path")
        if verify and ca:
            verify = ca
        self._client = VeeamRestClient(
            self.instance.endpoint, u, p, port=int(self.meta.get("port") or DEFAULT_PORT), verify=verify,
            revision=str(self.meta.get("api_revision") or DEFAULT_REVISION))
        return self._client


# ── DEMO / fixture ───────────────────────────────────────────────────────────

class DemoTransport:
    """Veeam-şekilli sentetik yanıtlar. GERÇEK DEĞİL — yalnız demo/test.

    ainew envanterindeki VM adlarından deterministik veri üretir ki eşleştirme,
    RPO ve bulgu akışı uçtan uca denenebilsin. Yazma yok.
    """

    def __init__(self, vms: List[Dict[str, Any]], now: Optional[datetime] = None):
        self.now = now or datetime.now(timezone.utc)
        self.vms = vms
        self._build()

    @staticmethod
    def _bucket(name: str) -> int:
        return zlib.crc32(name.encode()) % 10

    def _build(self) -> None:
        n = self.now
        job_ids = {k: f"demo-job-{k}" for k in ("daily", "hourly", "weekly", "copy")}
        backup_ids = {k: f"demo-bkp-{k}" for k in job_ids}
        self._jobs = [
            self._job(job_ids["daily"], "DEMO Daily VMs", "VSphereBackup", "Success", 5, "demo-repo-a"),
            self._job(job_ids["hourly"], "DEMO Critical hourly", "VSphereBackup", "Success", 1, "demo-repo-a"),
            self._job(job_ids["weekly"], "DEMO Weekly DB", "VSphereBackup", "Failed", 6, "demo-repo-b"),
            self._job(job_ids["copy"], "DEMO Copy to DR", "BackupCopy", "Success", 3, "demo-repo-b"),
        ]
        self._repos = [
            {"type": "LinuxLocal", "id": "demo-repo-a", "name": "DEMO Repo A", "capacityGB": 10000.0,
             "freeGB": 900.0, "isOnline": True},
            {"type": "LinuxLocal", "id": "demo-repo-b", "name": "DEMO Repo B", "capacityGB": 20000.0,
             "freeGB": 12000.0, "isOnline": True},
        ]
        self._job_cfgs = [self._job_cfg(job_ids["daily"], "DEMO Daily VMs", enc=False, cbt=True, aa=False, ret=("Days", 14)),
                          self._job_cfg(job_ids["hourly"], "DEMO Critical hourly", enc=True, cbt=True, aa=True, ret=("Days", 7)),
                          self._job_cfg(job_ids["weekly"], "DEMO Weekly DB", enc=True, cbt=False, aa=True, ret=("RestorePoints", 4)),
                          self._job_cfg(job_ids["copy"], "DEMO Copy to DR", enc=None, cbt=None, aa=None, ret=("Days", 30), typ="BackupCopy")]
        self._proxy_states = [
            {"type": "ViProxy", "id": "demo-proxy-1", "name": "DEMO Proxy 1", "hostId": "demo-host", "hostName": "This server",
             "isDisabled": False, "isOnline": True, "isOutOfDate": False},
            {"type": "ViProxy", "id": "demo-proxy-2", "name": "DEMO Proxy 2", "hostId": "demo-host-2", "hostName": "demo-proxy2.local",
             "isDisabled": False, "isOnline": True, "isOutOfDate": True}]
        self._proxy_cfgs = [
            {"type": "ViProxy", "id": "demo-proxy-1", "name": "DEMO Proxy 1", "server": {"transportMode": "auto", "maxTaskCount": 4}},
            {"type": "ViProxy", "id": "demo-proxy-2", "name": "DEMO Proxy 2", "server": {"transportMode": "network", "maxTaskCount": 2}}]
        self._backups = [{"id": backup_ids[k], "jobId": job_ids[k], "jobType": "VSphereBackup", "name": k,
                          "platformName": "VMware"} for k in ("daily", "hourly", "weekly")]
        self._objects, self._rps = [], []
        for v in self.vms:
            name = str(v.get("name") or "")
            if not name:
                continue
            b = self._bucket(name)
            if b <= 1:
                continue  # korumasız (demo)
            key = "hourly" if b == 9 else ("weekly" if b == 8 else "daily")
            age_h = {2: 72.0, 3: 30.0, 4: 30.0}.get(b, 2.0 + (zlib.crc32(name.encode()) % 40) / 10.0)
            step = 1 if key == "hourly" else 24
            ref = v.get("ref")
            self._objects.append({
                "platformName": "VMware", "id": f"demo-obj-{zlib.crc32(name.encode()):08x}", "name": name,
                "type": "VM", "restorePointsCount": 5,
                "objectId": ref if isinstance(ref, str) and _MOREF_RX.match(ref) else None,
            })
            for i in range(5):
                ts = n - timedelta(hours=age_h + i * step)
                self._rps.append({"platformName": "VMware", "type": "Increment", "id": f"demo-rp-{zlib.crc32(name.encode()):08x}-{i}",
                                  "name": name, "creationTime": ts.isoformat(), "backupId": backup_ids[key]})
        self._rps.sort(key=lambda r: r["creationTime"], reverse=True)
        self._sessions = []
        for k in ("daily", "hourly", "weekly"):
            for d in range(3):
                failed = (k == "weekly" and d == 0)
                st = n - timedelta(hours=6 + 24 * d)
                self._sessions.append({
                    "sessionType": "BackupJob", "state": "Stopped", "id": f"demo-sess-{k}-{d}", "name": f"DEMO {k}",
                    "jobId": job_ids[k], "creationTime": st.isoformat(),
                    "endTime": (st + timedelta(minutes=20)).isoformat(),
                    "result": {"result": "Failed" if failed else "Success",
                               "message": "DEMO: örnek hata" if failed else "Success", "isCanceled": False}})

    @staticmethod
    def _job_cfg(jid: str, name: str, *, enc: Optional[bool], cbt: Optional[bool], aa: Optional[bool],
                 ret: Tuple[str, int], typ: str = "VSphereBackup") -> Dict[str, Any]:
        """Veeam-şekilli (Get All Jobs) SENTETİK iş yapılandırması — GERÇEK DEĞİL."""
        adv: Dict[str, Any] = {"backupModeType": "Incremental", "backupHealth": {"isEnabled": False}}
        if enc is not None:
            adv["storageData"] = {"encryption": {"isEnabled": enc}}
        if cbt is not None:
            adv["vSphere"] = {"changedBlockTracking": {"isEnabled": cbt}}
        j: Dict[str, Any] = {"id": jid, "name": name, "type": typ, "isDisabled": False,
                             "storage": {"retentionPolicy": {"type": ret[0], "quantity": ret[1]},
                                         "gfsPolicy": {"isEnabled": False}, "advancedSettings": adv},
                             "schedule": {"runAutomatically": True, "daily": {"isEnabled": True, "localTime": "22:00"},
                                          "retry": {"isEnabled": True, "retryCount": 3, "awaitMinutes": 10},
                                          "backupWindow": {"isEnabled": False}}}
        if aa is not None:
            j["guestProcessing"] = {"appAwareProcessing": {"isEnabled": aa}}
        return j

    def _job(self, jid: str, name: str, typ: str, res: str, ago_h: int, repo: str) -> Dict[str, Any]:
        return {"type": typ, "status": "Stopped", "lastResult": res, "workload": "Vm", "id": jid, "name": name,
                "lastRun": (self.now - timedelta(hours=ago_h)).isoformat(),
                "nextRun": (self.now + timedelta(hours=24 - ago_h)).isoformat(), "nextRunPolicy": "DEMO",
                "repositoryId": repo, "repositoryName": "DEMO Repo", "objectsCount": len(self.vms), "sessionId": f"demo-sess-{jid}"}

    def get_json(self, key: str, params: Optional[Dict[str, Any]] = None, **kw: Any) -> Dict[str, Any]:
        p = dict(params or {})
        data: List[Dict[str, Any]]
        if key == "server_info":
            return {"name": "demo-vbr.local", "buildVersion": "DEMO", "platform": "Demo"}
        if key == "jobs_states":
            data = self._jobs
        elif key == "repositories_states":
            data = self._repos
        elif key == "jobs":
            data = self._job_cfgs
        elif key == "proxies_states":
            data = self._proxy_states
        elif key == "proxies":
            data = self._proxy_cfgs
        elif key == "repositories":
            data = [{"id": r["id"], "name": r["name"], "type": r["type"]} for r in self._repos]
        elif key == "object_restore_points":
            oid = (kw.get("path") or {}).get("id")
            nm = next((o["name"] for o in self._objects if o["id"] == oid), None)
            data = [r for r in self._rps if r["name"] == nm]
        elif key == "backups":
            data = self._backups
        elif key == "backup_objects":
            data = self._objects
        elif key == "sessions":
            data = self._sessions
            after = parse_ts(p.get("createdAfterFilter"))
            if after:
                data = [s for s in data if (parse_ts(s["creationTime"]) or after) >= after]
        elif key == "restore_points":
            data = self._rps
            after = parse_ts(p.get("createdAfterFilter"))
            if after:
                data = [r for r in data if (parse_ts(r["creationTime"]) or after) >= after]
        else:
            raise VeeamApiError("readonly", f"demo: bilinmeyen endpoint {key}")
        skip, limit = int(p.get("skip") or 0), int(p.get("limit") or 200)
        page = data[skip:skip + limit]
        return {"data": page, "pagination": {"total": len(data), "count": len(page), "skip": skip, "limit": limit}}


def _demo_vms() -> List[Dict[str, Any]]:
    """ainew envanterindeki VMware VM'leri (yalnız okuma)."""
    try:
        from app.core.database import SessionLocal
        from app.models.server import Server
        db = SessionLocal()
        try:
            rows = db.query(Server).filter(Server.hypervisor_id.isnot(None)).all()
            return [{"name": s.vm_name or s.name, "ref": s.hypervisor_vm_id} for s in rows
                    if (s.vm_name or s.name)][:500]
        finally:
            db.close()
    except Exception:  # noqa: BLE001
        return []


class VeeamDemoProvider(_Base):
    kind = KIND_DEMO

    def __init__(self, instance: Any, *, vms: Optional[List[Dict[str, Any]]] = None):
        super().__init__(instance)
        self._vms = vms

    def _transport(self) -> VeeamTransport:
        return DemoTransport(self._vms if self._vms is not None else _demo_vms())


register_provider(KIND_REAL, lambda inst: VeeamVbrProvider(inst), capabilities=CAPS)
register_provider(KIND_DEMO, lambda inst: VeeamDemoProvider(inst), capabilities=CAPS)
