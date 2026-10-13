"""Geliştirme için sahte AE kaynağı (AUTOMIC_FAKE=1 veya source_type=fake).

Belirlenimli: aynı zaman aralığı her sorguda aynı kayıtları üretir; böylece
watermark/overlap/upsert davranışı gerçekçi test edilir. Gerçek veri içermez.
"""
from __future__ import annotations

import hashlib
import random
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .base import AutomicSource, ConnectionResult, Freshness, ReportText, SourceError
from .sql_guard import assert_read_only

_DOMAINS = ["FIN", "HR", "CRM", "DWH", "SAP", "BATCH", "OPS", "PAY", "RISK", "ETL"]
_STEPS = ["EXTRACT", "LOAD", "TRANSFORM", "GUNSONU", "RAPOR", "YEDEK", "TEMIZLIK", "SYNC", "KONTROL", "AKTARIM"]
# (name, platform, os, ip, hostname, port, active) — 2 kopuk (ACTIVE=0 / life stale)
_AGENT_META = [
    ("LNXAPP01", "UNIX", "Linux", "10.10.1.11", "lnxapp01.corp.local", 2300, 1),
    ("LNXAPP02", "UNIX", "Linux", "10.10.1.12", "lnxapp02.corp.local", 2300, 1),
    ("LNXDB01", "UNIX", "Linux", "10.10.1.21", "lnxdb01.corp.local", 2300, 1),
    ("LNXETL01", "UNIX", "Linux", "10.10.1.31", None, 2300, 1),  # hostname yok
    ("LNXBAT01", "UNIX", "Linux", "10.10.1.41", "lnxbat01.corp.local", 2300, 1),
    ("LNXBAT02", "UNIX", "Linux", "10.10.1.42", "lnxbat02.corp.local", 2300, 0),  # kopuk
    ("WINAPP01", "WINDOWS", "Windows", "10.10.2.11", "winapp01.corp.local", 2217, 1),
    ("WINRPT01", "WINDOWS", "Windows", "10.10.2.21", "winrpt01.corp.local", 2217, 1),
    ("WINBAT01", "WINDOWS", "Windows", "10.10.2.31", None, 2217, 1),
    ("SAPPRD01", "SAP", "Linux", "10.10.3.11", "sapprd01.corp.local", 2300, 1),
    ("SAPQAS01", "SAP", "Linux", "10.10.3.12", "sapqas01.corp.local", 2300, 1),
    ("DBORA01", "SQL", "Linux", "10.10.4.11", "dbora01.corp.local", 2300, 1),
    ("DBMSS01", "SQL", "Windows", "10.10.4.21", "dbmss01.corp.local", 2217, 0),  # kopuk
    ("RA.SOL01", "CIT", "Linux", "10.10.5.11", "rasol01.corp.local", 2300, 1),
]
_AGENTS = [(a[0], a[1]) for a in _AGENT_META]
_AGENT_GROUPS = [
    {"name": "HOSTG.LINUX.BATCH", "platform": "UNIX", "mode": "N", "members": ["LNXBAT01", "LNXBAT02", "LNXAPP01"]},
    {"name": "HOSTG.WIN.RPT", "platform": "WINDOWS", "mode": "A", "members": ["WINRPT01", "WINBAT01"]},
    {"name": "HOSTG.SAP", "platform": "SAP", "mode": "F", "members": ["SAPPRD01", "SAPQAS01"]},
]
_QUEUES = ["CLIENT_QUEUE", "Q_BATCH", "Q_HIGH"]
_USERS = ["BATCH/OPS", "SCHED/AUTO", "UC4/ADMIN"]
# Sabit USER OH_Idnr — client başına aynı ad farklı idnr (client*10000 + offset)
_USER_META = [
    ("BATCH", "OPS", 1),
    ("SCHED", "AUTO", 2),
    ("UC4", "ADMIN", 3),
]


def _user_idnr(client: int, full_name: str) -> int:
    """Düşük OH_Idnr aralığı — USER senkron PK yürüyüşü tek parçada bitsin."""
    base = 7000 + (int(client) // 100) * 10
    for name, dept, off in _USER_META:
        if f"{name}/{dept}" == full_name:
            return base + off
    return base + 99


def _user_catalog(clients: List[int]) -> List[Dict[str, Any]]:
    now = datetime.now(timezone.utc)
    out = []
    for c in clients:
        base = 7000 + (int(c) // 100) * 10
        for name, dept, off in _USER_META:
            out.append({
                "object_id": base + off, "client": int(c),
                "object_name": f"{name}/{dept}", "object_type": "USER",
                "modified_at": now - timedelta(days=1), "delete_flag": 0,
            })
        if int(c) == 100:
            out.append({
                "object_id": 7008, "client": 100,
                "object_name": "GONE/OLD", "object_type": "USER",
                "modified_at": now - timedelta(days=30), "delete_flag": 1,
            })
    return out
_ERRORS = [
    ("ORA-00054: resource busy and acquire with NOWAIT specified", 1800),
    ("ORA-01653: unable to extend table DWH.FACT_SALES by 8192 in tablespace DWH_DATA", 1800),
    ("ORA-12541: TNS:no listener", 1800),
    ("No space left on device", 1800),
    ("Permission denied: /data/export/out.csv", 1800),
    ("java.lang.OutOfMemoryError: Java heap space", 1800),
    ("Connection timed out after 300 seconds", 1802),
    ("return code 8 from step TRANSFORM", 1800),
]
_RATE_PER_MIN = 6  # client başına dakikada ortalama üst çalışma
# Dakika başına RunID alanı — üretim, latest_run_id ve zaman→RunID aynı ölçekte olmalı.
# (slot ≤ 19*400 + ~40 satır; 1000'lik ölçek taşardı ve collector'ı 0 satıra kilitlerdi.)
_RUN_ID_PER_MINUTE = 10_000


def _seed(*parts: Any) -> int:
    return int(hashlib.sha1("|".join(map(str, parts)).encode()).hexdigest()[:12], 16)


def _minute_epoch(dt: datetime) -> int:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return int(dt.astimezone(timezone.utc).timestamp() // 60)


def run_id_lo_for_minute(minute_epoch: int) -> int:
    return int(minute_epoch) * _RUN_ID_PER_MINUTE


def run_id_hi_for_minute(minute_epoch: int) -> int:
    """Dakika için exclusive üst sınır."""
    return (int(minute_epoch) + 1) * _RUN_ID_PER_MINUTE


def _object_names() -> List[str]:
    names = []
    for d in _DOMAINS:
        for s in _STEPS:
            for i in range(1, 4):
                names.append(f"JOBS.{d}.{s}.{i:02d}")
    return names


_JOBS = _object_names()
_FLAKY = set(_JOBS[::37])  # sık hata veren nesneler


class FakeSource(AutomicSource):
    source_type = "fake"

    def supports(self, feature: str) -> bool:
        if feature in ("objects", "versions", "usage_graph", "ended_executions", "active",
                       "children", "restarts", "reports", "agents", "infrastructure"):
            return True
        return super().supports(feature)

    def _clients(self) -> List[int]:
        cl = self.connection.get("fake_clients") or [100, 200, 300]
        return [int(c) for c in cl]

    # ── üretim ────────────────────────────────────────────────────────────
    def _minute_items(self, client: int, minute_epoch: int) -> List[Dict[str, Any]]:
        rng = random.Random(_seed(self.system_id, client, minute_epoch))
        base = datetime.fromtimestamp(minute_epoch * 60, tz=timezone.utc)
        hour = base.hour
        load = 2.0 if 0 <= hour < 6 else (1.0 if 8 <= hour < 19 else 0.6)
        n = max(0, int(rng.gauss(_RATE_PER_MIN * load, 1.5)))
        items: List[Dict[str, Any]] = []
        # Gerçek AE gibi tek artan sayaç: üst çalışma, alt görev ve restart aynı diziden
        slot = ((client // 100 + client) % 20) * 400
        next_id = run_id_lo_for_minute(minute_epoch) + slot
        for i in range(min(n, 40)):
            run_id = next_id
            next_id += 1
            is_wf = rng.random() < 0.12
            if is_wf:
                d = _DOMAINS[rng.randrange(len(_DOMAINS))]
                name = f"JOBP.{d}.{_STEPS[rng.randrange(len(_STEPS))]}"
                otype = "JOBP"
                duration = rng.randint(300, 2400)
            else:
                name = _JOBS[rng.randrange(len(_JOBS))]
                otype = "JOBS"
                duration = max(1, int(rng.expovariate(1 / 180)))
            end = base + timedelta(seconds=rng.randint(0, 59))
            start = end - timedelta(seconds=duration)
            act = start - timedelta(seconds=rng.randint(1, 30))
            agent, platform = _AGENTS[rng.randrange(len(_AGENTS))]
            # ~15% iş agent grubu üzerinden (HGDst=grup, HostDst=fiili agent)
            use_group = otype == "JOBS" and rng.random() < 0.15
            agent_group = None
            agent_assigned = agent
            if use_group:
                g = _AGENT_GROUPS[rng.randrange(len(_AGENT_GROUPS))]
                agent_group = g["name"]
                agent_assigned = g["name"]
                if g["members"]:
                    agent = g["members"][rng.randrange(len(g["members"]))]
                    platform = g["platform"]
            fail_p = 0.25 if name in _FLAKY else 0.015
            r = rng.random()
            if r < fail_p:
                err_idx = rng.randrange(len(_ERRORS))
                status, rc = _ERRORS[err_idx][1], rng.choice([1, 8, 12, 255])
            elif r < fail_p + 0.004:
                status, rc, err_idx = 1850, 0, None
            else:
                status, rc, err_idx = rng.choice([1900, 1900, 1900, 1900, 1920]), 0, None
            domain = name.split(".")[1] if "." in name else "OPS"
            rec = {
                "client": client, "run_id": run_id, "parent_run_id": None, "top_run_id": run_id,
                "restart_ref_run_id": None, "object_name": name, "object_type": otype,
                "folder": f"/{domain}/", "status_code": status,
                "activation_time": act, "start_time": start, "end_time": end,
                "agent": None if otype == "JOBP" else agent,
                "agent_group": None if otype == "JOBP" else agent_group,
                "agent_assigned": None if otype == "JOBP" else agent_assigned,
                "platform": None if otype == "JOBP" else platform,
                "queue": _QUEUES[rng.randrange(len(_QUEUES))],
                "user": _USERS[rng.randrange(len(_USERS))],
                "return_code": rc, "_err": err_idx,
                "run_time_sec": duration, "ert_sec": max(1, int(duration * rng.uniform(0.8, 1.2))),
            }
            rec["user_id"] = _user_idnr(client, rec["user"])
            rec["user_idnr"] = rec["user_id"]
            rec["user_name_at_run"] = rec["user"]
            rec["_user_id_matched"] = True
            items.append(rec)
            if is_wf:
                n_child = rng.randint(3, 6)
                slot_dur = duration / n_child
                for k in range(n_child):
                    c_start = start + timedelta(seconds=int(slot_dur * k))
                    c_end = c_start + timedelta(seconds=max(1, int(slot_dur * rng.uniform(0.5, 0.95))))
                    c_agent, c_plat = _AGENTS[rng.randrange(len(_AGENTS))]
                    c_name = f"JOBS.{name.split('.')[1]}.{_STEPS[k % len(_STEPS)]}.{(k % 3) + 1:02d}"
                    c_fail = status != 1900 and status != 1920 and status != 1850 and k == n_child - 1
                    child_id = next_id
                    next_id += 1
                    items.append({
                        "client": client, "run_id": child_id,
                        "parent_run_id": run_id, "top_run_id": run_id, "restart_ref_run_id": None,
                        "object_name": c_name, "object_type": "JOBS", "folder": rec["folder"],
                        "status_code": rec["status_code"] if c_fail else 1900,
                        "activation_time": c_start - timedelta(seconds=2), "start_time": c_start,
                        "end_time": c_end, "agent": c_agent, "platform": c_plat,
                        "queue": rec["queue"], "user": rec["user"],
                        "user_id": rec["user_id"], "user_idnr": rec["user_idnr"],
                        "user_name_at_run": rec["user"],
                        "return_code": rec["return_code"] if c_fail else 0,
                        "_err": rec["_err"] if c_fail else None,
                        "run_time_sec": int((c_end - c_start).total_seconds()),
                        "ert_sec": max(1, int((c_end - c_start).total_seconds() * rng.uniform(0.8, 1.2))),
                    })
        # yeniden başlatma: aynı sayaçtan yeni RunID (üst çalışmadan büyük)
        for rec in list(items):
            if rec["parent_run_id"] is None and rec["status_code"] not in (1900, 1920, 1850) \
                    and _seed(rec["run_id"], "rs") % 3 == 0:
                rs_end = rec["end_time"] + timedelta(minutes=5)
                rs_id = next_id
                next_id += 1
                items.append(dict(
                    rec, run_id=rs_id, restart_ref_run_id=rec["run_id"],
                    status_code=1900, return_code=0, _err=None,
                    activation_time=rec["end_time"] + timedelta(seconds=30),
                    start_time=rs_end - (rec["end_time"] - rec["start_time"]), end_time=rs_end,
                ))
        return items

    def _window(self, clients: List[int], t_from: datetime, t_to: datetime) -> List[Dict[str, Any]]:
        out = []
        first = int((t_from - timedelta(hours=1)).timestamp() // 60)
        last = int(t_to.timestamp() // 60)
        now = datetime.now(timezone.utc)
        for c in clients:
            for m in range(first, last + 1):
                for rec in self._minute_items(c, m):
                    if t_from <= rec["end_time"] < t_to and rec["end_time"] <= now:
                        out.append(rec)
        out.sort(key=lambda r: r["end_time"])
        return out

    def _decode(self, client: int, run_id: int) -> Optional[Dict[str, Any]]:
        rid = int(run_id)
        # RunID = minute_epoch * 10_000 + slot + seq → dakika = rid // 10_000
        minute = rid // 10_000
        for m in (minute, minute - 1, minute + 1):
            if m < 0:
                continue
            for rec in self._minute_items(int(client), m):
                if rec["run_id"] == rid:
                    return rec
        return None

    @staticmethod
    def _public(rec: Dict[str, Any]) -> Dict[str, Any]:
        return {k: v for k, v in rec.items() if not k.startswith("_")}

    # ── arayüz ────────────────────────────────────────────────────────────
    def read_database_role(self) -> Dict[str, Any]:
        if self.connection.get("fake_role_unknown"):
            return {"database_role": None, "open_mode": None, "role_known": False}
        role = self.connection.get("fake_database_role")
        if role is None:
            role = "PHYSICAL STANDBY"
        open_mode = self.connection.get("fake_open_mode")
        if open_mode is None:
            open_mode = "READ ONLY WITH APPLY" if str(role).upper() != "PRIMARY" else "READ WRITE"
        return {"database_role": str(role), "open_mode": str(open_mode), "role_known": True}

    def run_guarded_sql(self, sql: str, *, kind: str = "chat") -> list:
        """Test/helper: SQL guard + isteğe bağlı zaman aşımı simülasyonu."""
        assert_read_only(sql)
        if self.connection.get("fake_timeout"):
            raise SourceError(
                "Sorgu zaman aşımına uğradı (call_timeout).",
                code="call_timeout", retryable=True,
            )
        g = self.settings.get("source_guard") or {}
        # timeout ayarının okunduğunu doğrula (ms)
        _ = int(float(g.get("chat_timeout_sec" if kind == "chat" else "collector_timeout_sec")
                      or g.get("call_timeout_sec") or 30) * 1000)
        return [(1,)]

    def test_connection(self) -> ConnectionResult:
        if self.connection.get("fake_fail"):
            return ConnectionResult(ok=False, message="Sahte kaynak: bağlantı hatası senaryosu (ORA-12541).",
                                    details={"code": "no_listener"})
        role_info = self.read_database_role()
        warnings: list = []
        details: Dict[str, Any] = {
            "database_role": role_info.get("database_role"),
            "open_mode": role_info.get("open_mode"),
            "role_known": role_info.get("role_known"),
            "database_role_display": role_info.get("database_role") or "bilinmiyor",
            "open_mode_display": role_info.get("open_mode") or "bilinmiyor",
            "primary_warning": False,
            "requires_primary_ack": False,
        }
        if (details["database_role"] or "").upper() == "PRIMARY":
            details["primary_warning"] = True
            details["requires_primary_ack"] = True
            warnings.append(
                "Canlı primary veritabanı; sorgular Automic performansını etkileyebilir. "
                "Kurulumu tamamlamak için açık onay gerekir."
            )
        elif not details["role_known"]:
            warnings.append("V$DATABASE rolü okunamadı (bilinmiyor); bağlantı yine de kullanılabilir.")
        return ConnectionResult(
            ok=True, message="Bağlantı başarılı (sahte kaynak)",
            db_version="19.21.0.0.0 (fake)", driver_mode="fake", latency_ms=3.2,
            warnings=warnings, details=details,
        )

    def discover(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        recs = self._window(self._clients(), now - timedelta(hours=1), now)
        per: Dict[int, Dict[str, int]] = {}
        dist: Dict[str, int] = {}
        for r in recs:
            p = per.setdefault(r["client"], {"count_24h": 0, "failed_24h": 0})
            p["count_24h"] += 24
            if 1800 <= r["status_code"] <= 1899 and r["status_code"] not in (1850, 1851):
                p["failed_24h"] += 24
            dist[str(r["status_code"])] = dist.get(str(r["status_code"]), 0) + 24
        role_info = self.read_database_role()
        freshness = "dataguard" if (role_info.get("database_role") or "").upper() != "PRIMARY" else "max_timestamp"
        return {
            "engine": "fake", "source_type": "fake", "profile": "ae-24", "db_version": "19.21.0.0.0 (fake)",
            "driver_mode": "fake", "schema": "UC4", "user": "SRVC_FAKE_RO",
            "database_role": role_info.get("database_role"),
            "open_mode": role_info.get("open_mode"),
            "role_known": role_info.get("role_known"),
            "timestamps": "utc",
            "mapping": {}, "indexes": {}, "index_warnings": [],
            "privileges": {"write_privileges": [], "is_schema_owner": False, "read_only_ok": True},
            "features": {"ended_executions": True, "active": True, "children": True, "restarts": True,
                         "reports": True, "freshness": freshness, "objects": True,
                         "versions": True, "usage_graph": True, "agents": True,
                         "infrastructure": True,
                         "user_names": True, "folders": True, "ert": True},
            "clients_seen": [{"client": c, **v} for c, v in sorted(per.items())],
            "status_distribution_24h": dist,
            "warnings": ["Sahte kaynak — gerçek AE verisi değil."],
            "discovered_at": now.isoformat(),
        }

    def source_freshness(self) -> Freshness:
        lag = 300 + (_seed(int(datetime.now().timestamp() // 600)) % 300)
        return Freshness(lag_sec=float(lag), method="dataguard",
                         latest_at=datetime.now(timezone.utc) - timedelta(seconds=lag))

    def latest_run_id(self, client: int):
        now = datetime.now(timezone.utc)
        return run_id_hi_for_minute(_minute_epoch(now)) - 1

    def min_run_id(self):
        """Kaynak MIN AH_Idnr (client'sız) — connection.fake_source_min ile simüle edilebilir."""
        override = self.connection.get("fake_source_min")
        if override is not None:
            return int(override)
        now = datetime.now(timezone.utc)
        oldest = now - timedelta(days=7)
        return run_id_lo_for_minute(_minute_epoch(oldest))

    def runid_bounds_for_time(self, t_from: datetime, t_to: datetime) -> Optional[tuple]:
        """Zaman aralığı → kesin RunID [lo, hi) — boş eşleme / yanlış ölçekte tarama önler."""
        if t_from is None or t_to is None:
            return None
        if t_to <= t_from:
            return None
        lo = run_id_lo_for_minute(_minute_epoch(t_from))
        hi = run_id_hi_for_minute(_minute_epoch(t_to - timedelta(microseconds=1)))
        if hi <= lo:
            hi = lo + _RUN_ID_PER_MINUTE
        return lo, hi

    def source_has_ended_after(self, after: datetime) -> bool:
        """Watermark'tan sonra üretilebilir bitmiş çalışma var mı? (5 dk lag ile)."""
        if after is None:
            return True
        if after.tzinfo is None:
            after = after.replace(tzinfo=timezone.utc)
        lag = timedelta(minutes=5)
        tip = datetime.now(timezone.utc) - lag
        return tip > after.astimezone(timezone.utc)

    def fetch_ended_executions(self, clients, t_from, t_to, *, limit, id_min=None, id_max=None):
        if self.connection.get("fake_fail"):
            raise SourceError("TNS:no listener (ORA-12541) — sahte hata", code="no_listener")
        if id_min is None or id_max is None:
            raise SourceError("RunID aralığı gerekli", code="runid_bounds_required", retryable=False)
        lag = timedelta(minutes=5)
        cutoff = min(t_to, datetime.now(timezone.utc) - lag)
        if cutoff <= t_from:
            return []
        id_min_i, id_max_i = int(id_min), int(id_max)
        # Yalnızca RunID dilimine düşen dakikaları üret (tam pencere × boş dilim felaketini önler)
        m_lo = max(_minute_epoch(t_from), id_min_i // _RUN_ID_PER_MINUTE)
        m_hi = min(_minute_epoch(cutoff), max(id_min_i, id_max_i - 1) // _RUN_ID_PER_MINUTE)
        if m_hi < m_lo:
            return []
        out: List[Dict[str, Any]] = []
        for minute in range(m_lo, m_hi + 1):
            for c in clients:
                for r in self._minute_items(int(c), minute):
                    rid = int(r["run_id"])
                    if rid < id_min_i or rid >= id_max_i:
                        continue
                    end = r.get("end_time")
                    if end is None or end < t_from or end >= cutoff:
                        continue
                    out.append(self._public(r))
                    if len(out) > limit:
                        return out
        return out

    def fetch_ended_by_runid_range(self, clients, id_min, id_max, *, limit):
        now = datetime.now(timezone.utc)
        return self.fetch_ended_executions(
            clients, now - timedelta(days=7), now, limit=limit, id_min=id_min, id_max=id_max)

    def count_ended_by_id_range(self, clients, id_min: int, id_max: int) -> int:
        now = datetime.now(timezone.utc)
        recs = self.fetch_ended_executions(
            list(clients), now - timedelta(days=7), now,
            limit=100_000, id_min=int(id_min), id_max=int(id_max))
        return len(recs)

    def find_users(self, pattern, *, limit=50):
        raise SourceError("Kaynak kullanıcı araması kaldırıldı", code="capability_removed", retryable=False)

    def fetch_runs_by_users(self, user_ids, clients, t_from, t_to, *, limit):
        raise SourceError("Kaynak kullanıcı araması kaldırıldı", code="capability_removed", retryable=False)

    def fetch_active_executions(self, clients, *, limit):
        now = datetime.now(timezone.utc)
        out = []
        bucket = int(now.timestamp() // 120)
        for c in clients:
            rng = random.Random(_seed(self.system_id, c, bucket))
            slot = ((c // 100 + c) % 20) * 400
            for i in range(rng.randint(5, 25)):
                name = _JOBS[rng.randrange(len(_JOBS))]
                # Başlangıç kovaya sabitlenir (aynı kova içinde aynı RunID); ayrı çağrılarda kayma yok
                started = datetime.fromtimestamp(bucket * 120, tz=timezone.utc) - timedelta(seconds=rng.randint(10, 7200))
                agent, plat = _AGENTS[rng.randrange(len(_AGENTS))]
                ert = rng.randint(60, 3600)
                running = max(0, int((now - started).total_seconds()))
                out.append({
                    "client": c,
                    # Gerçek AE gibi tek artan sayaç: bitmiş çalışmalarla aynı dakika başına RunID ölçeği
                    # (eski 7e12 tabanı collector'ın yeniden okuma aralığını devasa yapıp bütçeyi bitiriyordu).
                    # Bitmiş üretim slot+0..~40 kullanır; aktifler slot içinde 350+ aralığında kalır.
                    "run_id": run_id_lo_for_minute(_minute_epoch(started)) + slot + 350 + i,
                    "parent_run_id": None, "object_name": name, "object_type": "JOBS",
                    "status_code": rng.choice([1550, 1550, 1550, 1560, 1300, 1700]),
                    "activation_time": started - timedelta(seconds=5), "start_time": started, "agent": agent,
                    "platform": plat, "queue": _QUEUES[rng.randrange(len(_QUEUES))],
                    "user": _USERS[rng.randrange(len(_USERS))], "folder": f"/PROD/{name.split('.')[1]}",
                    "run_time_sec": running, "ert_sec": ert, "ert_end_time": started + timedelta(seconds=ert),
                    "ert_calc": 2, "signal": 0 if running <= ert else 2,
                })
                out[-1]["user_id"] = _user_idnr(c, out[-1]["user"])
                out[-1]["user_idnr"] = out[-1]["user_id"]
                out[-1]["user_name_at_run"] = out[-1]["user"]
                out[-1]["_user_id_matched"] = True
        return out[:limit]

    def fetch_execution(self, client, run_id):
        rec = self._decode(client, run_id)
        return self._public(rec) if rec else None

    def fetch_children(self, client, run_id, *, limit, id_min=None, id_max=None):
        if id_min is None or id_max is None:
            raise SourceError("RunID aralığı gerekli", code="runid_bounds_required", retryable=False)
        rec = self._decode(client, run_id)
        if not rec:
            return []
        minute = int(rec["run_id"]) // 10_000
        return [self._public(r) for r in self._minute_items(int(client), minute)
                if r.get("parent_run_id") == int(run_id)
                and int(id_min) <= int(r["run_id"]) < int(id_max)][:limit]

    def fetch_restarts(self, client, run_id, *, limit, id_min=None, id_max=None):
        if id_min is None or id_max is None:
            raise SourceError("RunID aralığı gerekli", code="runid_bounds_required", retryable=False)
        rid = int(run_id)
        rec = self._decode(client, rid)
        if not rec:
            return []
        origin = int(rec.get("restart_ref_run_id") or rid)
        minute = origin // 10_000
        out = []
        for r in self._minute_items(int(client), minute):
            rr = int(r["run_id"])
            if rr == rid:
                continue
            if not (int(id_min) <= rr < int(id_max)):
                continue
            if int(r.get("restart_ref_run_id") or 0) == origin or rr == origin:
                out.append(self._public(r))
        return out[:limit]

    def list_reports(self, client, run_id):
        rec = self._decode(client, run_id)
        if not rec:
            return []
        return ["ACT", "REP"] if rec["object_type"] == "JOBS" else ["ACT"]

    def fetch_report(self, client, run_id, report_type, *, head, tail, max_scan_lines):
        rec = self._decode(client, run_id)
        if not rec:
            return ReportText(report_type=report_type, lines=[], total_lines=0, truncated=False)
        rng = random.Random(_seed(run_id, report_type))
        name = rec["object_name"]
        lines = [
            f"{rec['start_time']:%Y-%m-%d %H:%M:%S} - U00011001 Job '{name}' (RunID '{run_id}') başlatıldı.",
            f"&DB_PASSWORD# = 'S3cr3t!{rng.randint(100, 999)}'",
            f"sqlplus batch_user/Gizli{rng.randint(10, 99)}@DWHPRD @/opt/scripts/{name.lower()}.sql",
            "export API_TOKEN=abcd1234efgh5678",
            f"Müşteri TCKN 10000000146 için kayıt işleniyor, IBAN TR330006100519786457841326",
            f"Bildirim: ops-team@example.com, tel 0532 123 45 67, sunucu 10.20.30.40",
        ]
        body_n = rng.randint(80, 400) if report_type == "REP" else rng.randint(10, 40)
        for i in range(body_n):
            lines.append(f"[{i:05d}] step {rng.choice(['read', 'write', 'commit', 'check'])} ok rows={rng.randint(1, 99999)}")
        if rec.get("_err") is not None:
            msg = _ERRORS[rec["_err"]][0]
            lines.extend(["WARNING: retry 1/3", f"ERROR: {msg}", f"FATAL: job aborted, return code {rec['return_code']}"])
        else:
            lines.append("Job tamamlandı, return code 0")
        total = len(lines)
        truncated = total > max_scan_lines
        if truncated:
            lines = lines[:head] + lines[-tail:]
        return ReportText(report_type=report_type, lines=lines, total_lines=total, truncated=truncated)

    _oid_names: Dict[int, str] = {}

    def _object_id(self, client: int, name: str) -> int:
        oid = _seed(self.system_id, client, name) % 900_000_000 + 100_000
        FakeSource._oid_names[oid] = name
        return oid

    def fetch_object_header(self, client, object_name):
        name = (object_name or "").strip()
        if not name:
            return None
        if name not in _JOBS and not name.startswith(("JOBS.", "JOBP.", "SCRI.", "JSCH.")):
            return None
        rng = random.Random(_seed(self.system_id, client, name))
        mod = datetime.now(timezone.utc) - timedelta(days=rng.randint(0, 40), hours=rng.randint(0, 20))
        otype = name.split(".")[0] if "." in name else "JOBS"
        return {
            "object_id": self._object_id(int(client), name),
            "client": int(client), "object_name": name, "object_type": otype,
            "title": f"{name} (fake)", "folder": f"/PROD/{name.split('.')[1] if '.' in name else 'GEN'}",
            "created_at": mod - timedelta(days=rng.randint(30, 400)),
            "created_by": "SCHED/AUTO", "modified_at": mod, "modified_by": rng.choice(_USERS),
        }

    def fetch_object_headers(self, clients, *, since=None, limit=500, id_min=None, id_max=None):
        if id_min is None or id_max is None:
            raise SourceError("OH_Idnr aralığı gerekli", code="runid_bounds_required", retryable=False)
        out = []
        for c in clients:
            for name in _JOBS:
                h = self.fetch_object_header(c, name)
                oid = int(h["object_id"])
                if not (int(id_min) <= oid < int(id_max)):
                    continue
                out.append(h)
                if len(out) >= limit:
                    return out
        return out

    def fetch_users_by_id_range(self, clients, *, id_min: int, id_max: int, limit: int = 500):
        out = [u for u in _user_catalog(list(clients))
               if int(id_min) <= int(u["object_id"]) < int(id_max)]
        return out[: max(1, int(limit))]

    def user_object_id_bounds(self, clients):
        ids = [u["object_id"] for u in _user_catalog(list(clients))]
        if not ids:
            return None
        return min(ids), max(ids)

    def fetch_object_script(self, object_id, *, max_lines=20000):
        rng = random.Random(int(object_id))
        name = FakeSource._oid_names.get(int(object_id)) or _JOBS[int(object_id) % len(_JOBS)]
        lines = [
            f"! Automic script — {name}",
            ":SET &HOST# = \"LNXAPP01\"",
            ":SET &DB_PASSWORD# = \"S3cr3tFake\"",
            f":SET &JOB# = \"{name}\"",
            ":PRINT &JOB# başlıyor",
            "sqlplus batch/HiddenPass@DWH @/opt/scripts/run.sql",
            ":IF &RETCODE# <> 0",
            ":  SET &ERR# = \"ORA-00054 resource busy\"",
            ":  SEND_MSG ADMIN,01,\"&ERR#\"",
            ":ENDIF",
            f"! generated lines for oid={object_id}",
        ]
        for i in range(rng.randint(5, 25)):
            lines.append(f":PRINT step {i} rows=&ROWS#")
        return lines[:max_lines]

    def fetch_jpp_by_parent_range(self, id_min: int, id_max: int, *, limit: int):
        # Sahte JOBP ebeveynleri (OH_Idnr aralığına düşenler)
        parents = [f"JOBP.{d}.GUNSONU" for d in ("FIN", "HR", "CRM", "DWH", "BAT")]
        out = []
        for c in self._clients():
            for name in parents:
                oid = self._object_id(c, name)
                if not (int(id_min) <= oid < int(id_max)):
                    continue
                d = name.split(".")[1]
                for i, step in enumerate(_STEPS[:4]):
                    out.append({
                        "parent_object_id": oid, "line_no": i + 1,
                        "child_name": f"JOBS.{d}.{step}.01", "child_type": "JOBS",
                        "client": c, "parent_object_name": name,
                    })
                    if len(out) >= limit:
                        return out
        return out

    def fetch_object_usage(self, client, object_name, *, depth=1):
        raise SourceError(
            "Kaynakta canlı usage kaldırıldı; modül DB kullanın.",
            code="capability_removed", retryable=False,
        )

    def count_table(self, table: str) -> int:
        t = (table or "").upper()
        if t == "HOST":
            return len(_AGENT_META)
        if t == "MQSRV":
            return len(self._mqsrv_rows())
        if t == "OHG":
            return len(_AGENT_GROUPS)
        if t == "OHGF":
            return sum(len(g["members"]) for g in _AGENT_GROUPS)
        return 0

    def _mqsrv_rows(self) -> List[Dict[str, Any]]:
        now = datetime.now(timezone.utc)
        rows = [
            # Engine sunucu 1 — PWP + WP + CP
            {"name": "PWP001", "mqsrv_type": 4, "ip": "10.10.0.11", "port": 2217,
             "last_update": now - timedelta(seconds=30), "connection_count": 12, "pwp_connected": 1},
            {"name": "WP001", "mqsrv_type": 2, "ip": "10.10.0.11", "port": 2218,
             "last_update": now - timedelta(seconds=45), "connection_count": 4, "pwp_connected": 1},
            {"name": "WP002", "mqsrv_type": 2, "ip": "10.10.0.11", "port": 2219,
             "last_update": now - timedelta(seconds=40), "connection_count": 3, "pwp_connected": 1},
            {"name": "CP001", "mqsrv_type": 1, "ip": "10.10.0.11", "port": 2217,
             "last_update": now - timedelta(seconds=20), "connection_count": 40, "pwp_connected": 1},
            # Engine sunucu 2 — WP + CP + JCP/REST; bir WP kopuk
            {"name": "WP003", "mqsrv_type": 2, "ip": "10.10.0.12", "port": 2218,
             "last_update": now - timedelta(seconds=50), "connection_count": 2, "pwp_connected": 1},
            {"name": "WP004", "mqsrv_type": 2, "ip": "10.10.0.12", "port": 2219,
             "last_update": now - timedelta(hours=2), "connection_count": 0, "pwp_connected": 0},  # kopuk
            {"name": "CP002", "mqsrv_type": 1, "ip": "10.10.0.12", "port": 2217,
             "last_update": now - timedelta(seconds=25), "connection_count": 35, "pwp_connected": 1},
            {"name": "JCP001", "mqsrv_type": 64, "ip": "10.10.0.12", "port": 8088,
             "last_update": now - timedelta(seconds=35), "connection_count": 8, "pwp_connected": 1,
             "rest_endpoint": "wss://ae2.corp.local:8443/"},
            {"name": "REST001", "mqsrv_type": 32, "ip": "10.10.0.12", "port": 8080,
             "last_update": now - timedelta(seconds=40), "connection_count": 5, "pwp_connected": 1,
             "rest_endpoint": "https://ae2.corp.local:8088/ae/api/v1"},
            {"name": "JWP001", "mqsrv_type": 16, "ip": "10.10.0.12", "port": 2220,
             "last_update": now - timedelta(seconds=55), "connection_count": 1, "pwp_connected": 1},
        ]
        # Agent life-sign (Type=8) — kopuk agent'larda eski LastUpdate
        for i, (name, plat, os_, ip, host, port, active) in enumerate(_AGENT_META):
            if active == 0:
                lu = now - timedelta(hours=3)
            else:
                lu = now - timedelta(seconds=20 + i * 3)
            rows.append({
                "name": name, "mqsrv_type": 8, "ip": ip, "port": port,
                "last_update": lu, "connection_count": 1 if active else 0, "pwp_connected": active,
            })
        return rows

    def fetch_hosts(self) -> List[Dict[str, Any]]:
        out = []
        for i, (name, plat, os_, ip, host, port, active) in enumerate(_AGENT_META):
            out.append({
                "name": name, "oh_idnr": 8000 + i, "client": 0,
                "ip": ip, "hostname": host, "port": port,
                "os": os_, "hardware": "x86_64", "platform": plat,
                "version": "24.4.0+build.fake", "host_active": active,
                "roles": "PROD" if "PRD" in name or name.endswith("01") else None,
            })
        return out

    def fetch_mqsrv(self) -> List[Dict[str, Any]]:
        return list(self._mqsrv_rows())

    def fetch_agent_groups(self) -> Dict[str, Any]:
        groups = []
        members = []
        for i, g in enumerate(_AGENT_GROUPS):
            groups.append({
                "name": g["name"], "oh_idnr": 9000 + i, "client": 0,
                "platform": g["platform"], "mode": g["mode"],
            })
            for m in g["members"]:
                members.append({"group_name": g["name"], "agent_name": m})
        return {"groups": groups, "members": members}
