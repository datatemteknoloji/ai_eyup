"""Oracle Automic kaynak (automic_source) salt okunur adaptörü — python-oracledb.

Kaynak türü (primary / standby / kopya) varsayılmaz; kullanıcı kurulumda verdiği
bağlantı kullanılır. Rol yalnızca bilgilendirme için V$DATABASE'den okunur.

- Önce thin mod; NNE / eski verifier gibi thin desteklemeyen durumlarda thick moda geçer
  (Oracle Instant Client gerekir: ORACLE_CLIENT_LIB_DIR).
- Oturum: SET TRANSACTION READ ONLY; her çağrıda call_timeout; SQL → sql_guard.
- Yazma yetkisi / şema sahipliği keşifte uyarı olarak raporlanır.
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import logging
import os
import re
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple
from zoneinfo import ZoneInfo

from . import templates
from .base import (
    ACTIVE_FIELDS,
    EXECUTION_FIELDS,
    OBJECT_HEADER_FIELDS,
    USER_HEADER_FIELDS,
    AutomicSource,
    ConnectionResult,
    Freshness,
    ReportText,
    SourceError,
)
from .sql_guard import assert_read_only

logger = logging.getLogger(__name__)

_thick_lock = threading.Lock()
_thick_ready = False
_THICK_CODES = ("DPY-3001", "DPY-3010", "DPY-3015", "DPY-3012")

# OH (id → ad/tip/client) ve OFS (nesne → home klasör) çözümleme önbellekleri.
# Anahtar: (system_id, OH_Idnr). Kullanıcı/klasör adları nadiren değişir; TTL kısa tutulur.
_LOOKUP_TTL_SEC = 3600
_LOOKUP_MAX = 100_000
_IN_CHUNK = 500
_cache_lock = threading.Lock()
_name_cache: Dict[Tuple[int, int], Tuple[float, Optional[Dict[str, Any]]]] = {}
_home_cache: Dict[Tuple[int, int], Tuple[float, Optional[int]]] = {}

# OT_Type (resmi): 0 process, 1 pre-process, 2 post-process, 3 inherit post-process (child tasks)
_SCRIPT_SECTIONS = {1: "Pre-Process", 2: "Post-Process", 3: "Inherit Post-Process"}

_WRITE_PRIVS = (
    "CREATE ANY TABLE", "ALTER ANY TABLE", "DROP ANY TABLE", "INSERT ANY TABLE",
    "UPDATE ANY TABLE", "DELETE ANY TABLE", "CREATE TABLE", "CREATE ANY INDEX",
    "EXECUTE ANY PROCEDURE", "SYSDBA", "SYSOPER", "DBA",
)

_ERROR_HINTS: List[Tuple[str, str, str, bool]] = [
    ("ORA-01017", "auth_failed", "Kullanıcı adı veya şifre hatalı (ORA-01017).", False),
    ("ORA-28000", "account_locked", "Hesap kilitli (ORA-28000).", False),
    ("ORA-28001", "password_expired", "Şifre süresi dolmuş (ORA-28001).", False),
    ("ORA-12514", "service_unknown", "Listener servis adını tanımıyor (ORA-12514). Service name'i kontrol edin.", False),
    ("ORA-12505", "sid_unknown", "Listener SID'i tanımıyor (ORA-12505).", False),
    ("ORA-12541", "no_listener", "Hedefte listener yok (ORA-12541). Host/port kontrol edin.", True),
    ("ORA-12170", "timeout", "Bağlantı zaman aşımı (ORA-12170). Ağ/firewall kontrol edin.", True),
    ("DPY-6005", "connect_failed", "Veritabanına bağlanılamadı (DPY-6005). Ağ/DNS/firewall kontrol edin.", True),
    ("ORA-00942", "missing_grant", "Tablo yok veya SELECT yetkisi verilmemiş (ORA-00942).", False),
    ("ORA-01555", "snapshot_too_old", "Snapshot too old (ORA-01555) — dilim küçültülecek.", True),
    ("DPY-4024", "call_timeout", "Sorgu zaman aşımına uğradı (call_timeout).", True),
    ("ORA-01013", "call_timeout", "Sorgu iptal edildi / zaman aşımı (ORA-01013).", True),
    ("ORA-03113", "connection_lost", "Bağlantı koptu (ORA-03113).", True),
    ("ORA-03135", "connection_lost", "Bağlantı koptu (ORA-03135).", True),
    ("ORA-16000", "read_only", "Veritabanı salt okunur modda (ORA-16000) — yazma girişimi engellendi.", False),
]


def _translate(exc: Exception) -> SourceError:
    from app.services.automic.masking import redact_secrets

    msg = redact_secrets(str(exc))
    for marker, code, text, retry in _ERROR_HINTS:
        if marker in msg:
            if code == "connect_failed":
                cause = re.search(r"\[Errno -?\d+\][^\n(]*|Name or service not known|Connection refused"
                                  r"|timed out|DPY-\d{4}: (?!cannot connect)[^\n]*", msg[msg.find(marker) + 8:])
                if cause:
                    text = f"{text} Ayrıntı: {redact_secrets(cause.group(0).strip()[:160])}"
            return SourceError(text, code=code, retryable=retry)
    first = msg.splitlines()[0][:300] if msg else type(exc).__name__
    return SourceError(f"Kaynak hatası: {first}", code="source_error")


def _import_oracledb():
    try:
        import oracledb  # type: ignore
    except ImportError as exc:
        raise SourceError(
            "python-oracledb kurulu değil. Backend imajını yeniden derleyin (requirements: oracledb).",
            code="driver_missing", retryable=False,
        ) from exc
    return oracledb


def _init_thick(oracledb) -> None:
    global _thick_ready
    with _thick_lock:
        if _thick_ready:
            return
        lib_dir = (os.environ.get("ORACLE_CLIENT_LIB_DIR") or "").strip() or None
        try:
            oracledb.init_oracle_client(lib_dir=lib_dir)
        except Exception as exc:
            raise SourceError(
                "Thin mod bu veritabanında desteklenmiyor (ör. Native Network Encryption) ve "
                "thick mod başlatılamadı: Oracle Instant Client kurulu olmalı (ORACLE_CLIENT_LIB_DIR). "
                f"Ayrıntı: {str(exc).splitlines()[0][:200]}",
                code="thick_unavailable", retryable=False,
            ) from exc
        _thick_ready = True


class OracleSource(AutomicSource):
    source_type = "db_oracle"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._conn = None
        self._mode: Optional[str] = None
        prof_name = (self.capability.get("profile") or self.connection.get("profile") or "ae-24")
        self._profile = templates.load_profile("oracle", prof_name)
        self._mapping: Dict[str, Any] = self.capability.get("mapping") or {}
        self._schema: str = (self.capability.get("schema") or self.connection.get("schema") or "").upper()
        tz_mode = self.capability.get("timestamps") or self.connection.get("timestamps") or "utc"
        tz_name = self.connection.get("db_timezone") or "UTC"
        self._src_tz = timezone.utc if tz_mode == "utc" else ZoneInfo(tz_name)

    # ── bağlantı ──────────────────────────────────────────────────────────
    def _dsn(self) -> str:
        c = self.connection
        if c.get("dsn"):
            return str(c["dsn"])
        host = c.get("host")
        port = int(c.get("port") or 1521)
        if not host:
            raise SourceError("Host tanımlı değil.", code="config", retryable=False)
        proto = (c.get("protocol") or "tcp").lower()
        prefix = "tcps://" if proto == "tcps" else ""
        if c.get("service_name"):
            return f"{prefix}{host}:{port}/{c['service_name']}"
        if c.get("sid"):
            return (
                f"(DESCRIPTION=(ADDRESS=(PROTOCOL={proto.upper()})(HOST={host})(PORT={port}))"
                f"(CONNECT_DATA=(SID={c['sid']})))"
            )
        raise SourceError("Service name veya SID gerekli.", code="config", retryable=False)

    def _connect(self):
        if self._conn is not None:
            return self._conn
        oracledb = _import_oracledb()
        user = (self.connection.get("user") or "").strip()
        if not user or not self.secret:
            raise SourceError("Kullanıcı adı / şifre tanımlı değil.", code="config", retryable=False)
        mode_pref = (self.connection.get("driver_mode") or "auto").lower()
        if mode_pref == "thick":
            _init_thick(oracledb)
        params: Dict[str, Any] = {"user": user, "password": self.secret, "dsn": self._dsn()}
        if self.connection.get("wallet_location"):
            params["wallet_location"] = self.connection["wallet_location"]
        params["tcp_connect_timeout"] = float(self.connection.get("connect_timeout_sec") or 10)
        try:
            conn = oracledb.connect(**params)
        except Exception as exc:
            msg = str(exc)
            if mode_pref == "auto" and not _thick_ready and any(c in msg for c in _THICK_CODES):
                logger.info("Automic Oracle: thin mod desteklenmiyor (%s), thick moda geçiliyor", msg[:80])
                _init_thick(oracledb)
                try:
                    conn = oracledb.connect(**params)
                except Exception as exc2:
                    raise _translate(exc2) from exc2
            else:
                raise _translate(exc) from exc
        self._mode = "thin" if conn.thin else "thick"
        try:
            conn.autocommit = False
        except Exception as _e:
            note_error("oracle._connect", _e)
        try:
            conn.module = "ainew-automic"
            conn.action = "automic_source"
            conn.client_identifier = "ainew"
        except Exception as _e:
            note_error("oracle._connect", _e)
        self._ro_active = False
        self._ensure_read_only(conn)
        self._conn = conn
        return conn

    def _ensure_read_only(self, conn) -> None:
        """Her oturumda SET TRANSACTION READ ONLY (kaynak türünden bağımsız)."""
        if getattr(self, "_ro_active", False):
            return
        try:
            with conn.cursor() as cur:
                cur.execute("SET TRANSACTION READ ONLY")
            self._ro_active = True
        except Exception as exc:
            # Bazı ortamlarda desteklenmeyebilir; SQL guard + uygulama salt-okuma yine geçerli.
            logger.info("Automic kaynak: SET TRANSACTION READ ONLY uygulanamadı: %s", str(exc)[:160])
            self._ro_active = False

    def close(self) -> None:
        if self._conn is not None:
            try:
                self._conn.close()
            except Exception as _e:
                note_error("oracle.close", _e)
            self._conn = None
        self._ro_active = False

    def _timeout_ms(self, kind: str) -> int:
        g = self.settings.get("source_guard") or {}
        default = float(g.get("call_timeout_sec") or 30)
        if kind == "chat":
            sec = g.get("chat_timeout_sec") or default
        elif kind == "collector":
            sec = g.get("collector_timeout_sec") or default
        else:
            sec = default
        return int(float(sec) * 1000)

    def _default_fetch(self) -> int:
        g = self.settings.get("source_guard") or {}
        return int(g.get("default_fetch_limit") or g.get("max_rows_per_slice") or 500)

    def _disabled_templates(self) -> set:
        g = self.settings.get("source_guard") or {}
        return set(g.get("disabled_templates") or [])

    def _mark_template_slow(self, query_name: str, elapsed: float) -> None:
        """Yavaş şablonu durdur + yönetici uyarısı (settings üzerinden; caller DB'ye yazar)."""
        g = self.settings.setdefault("source_guard", {})
        disabled = list(g.get("disabled_templates") or [])
        if query_name not in disabled:
            disabled.append(query_name)
            g["disabled_templates"] = disabled
        g.setdefault("_slow_events", []).append({
            "query": query_name, "elapsed_sec": round(elapsed, 3),
            "at": datetime.now(timezone.utc).isoformat(),
        })
        logger.error(
            "YÖNETİCİ UYARISI: Automic kaynak şablonu '%s' %.1fs sürdü — otomatik durduruldu "
            "(eşik %ss). Plan kontrolü / indeks gerekir.",
            query_name, elapsed,
            g["slow_query_sec"] if g.get("slow_query_sec") is not None else 10,
        )
        self._templates_disabled_dirty = True

    def _query(self, sql: str, binds: Optional[Dict[str, Any]] = None, *, kind: str = "collector",
               max_rows: Optional[int] = None, query_name: str = "?") -> List[tuple]:
        if query_name and query_name in self._disabled_templates():
            raise SourceError(
                f"Şablon '{query_name}' yavaş sorgu nedeniyle durduruldu (yönetici / plan kontrolü).",
                code="template_disabled", retryable=False,
            )
        assert_read_only(sql)
        conn = self._connect()
        self._ensure_read_only(conn)
        conn.call_timeout = self._timeout_ms(kind)
        arraysize = int((self.settings.get("source_guard") or {}).get("arraysize") or 500)
        t0 = time.monotonic()
        rows: List[tuple] = []
        try:
            with conn.cursor() as cur:
                cur.arraysize = arraysize
                cur.prefetchrows = min(arraysize, 1000)
                cur.execute(sql, binds or {})
                rows = cur.fetchmany(max_rows) if max_rows else cur.fetchall()
        except SourceError:
            raise
        except Exception as exc:
            err = _translate(exc)
            if err.code in ("connection_lost", "call_timeout"):
                self.close()
            raise err from exc
        finally:
            elapsed = time.monotonic() - t0
            logger.info("automic_source query=%s kind=%s elapsed_sec=%.3f rows_cap=%s",
                        query_name, kind, elapsed, max_rows)
        raw_thresh = (self.settings.get("source_guard") or {}).get("slow_query_sec")
        thresh = float(10 if raw_thresh is None else raw_thresh)
        if query_name and query_name != "?" and elapsed >= thresh:
            self._mark_template_slow(query_name, elapsed)
            raise SourceError(
                f"Şablon '{query_name}' {elapsed:.1f}s sürdü (eşik {thresh:g}s) — durduruldu.",
                code="slow_query", retryable=False,
            )
        return rows

    def read_database_role(self) -> Dict[str, Optional[str]]:
        """V$DATABASE rolü — okunamazsa bilinmiyor (bağlantıyı engellemez)."""
        try:
            rows = self._query("SELECT database_role, open_mode FROM v$database", kind="chat", max_rows=1)
            if rows:
                return {
                    "database_role": str(rows[0][0]) if rows[0][0] is not None else None,
                    "open_mode": str(rows[0][1]) if rows[0][1] is not None else None,
                    "role_known": True,
                }
        except SourceError as _e:
            note_error("oracle.read_database_role", _e)
        return {"database_role": None, "open_mode": None, "role_known": False}

    # ── zaman ─────────────────────────────────────────────────────────────
    def _to_utc(self, v: Any) -> Optional[datetime]:
        if v is None or not isinstance(v, datetime):
            return None
        if v.tzinfo is None:
            v = v.replace(tzinfo=self._src_tz)
        return v.astimezone(timezone.utc)

    def _bind_dt(self, v: datetime) -> datetime:
        if v.tzinfo is None:
            v = v.replace(tzinfo=timezone.utc)
        return v.astimezone(self._src_tz).replace(tzinfo=None)

    # ── eşleme ────────────────────────────────────────────────────────────
    def _tmap(self, logical: str) -> Dict[str, Any]:
        m = self._mapping.get(logical) or {}
        if not m.get("available"):
            raise SourceError(
                f"'{logical}' kaynağı bu sistemde kullanılamıyor (keşif çalıştırın).",
                code="capability_missing", retryable=False,
            )
        return m

    def _render(self, query: str, logical: str, **kw) -> str:
        if "default_limit" not in kw:
            kw["default_limit"] = self._default_fetch()
        return templates.render(self._profile, query, schema=self._schema, table_map=self._tmap(logical), **kw)

    @staticmethod
    def _clients_binds(clients: List[int]) -> Tuple[str, Dict[str, Any]]:
        if not clients:
            raise SourceError("Client listesi boş.", code="config", retryable=False)
        names = [f":c{i}" for i in range(len(clients))]
        return ", ".join(names), {f"c{i}": int(c) for i, c in enumerate(clients)}

    def _rows_to_dicts(self, rows: List[tuple], fields: Tuple[str, ...]) -> List[Dict[str, Any]]:
        out = []
        for row in rows:
            d: Dict[str, Any] = {}
            for f, v in zip(fields, row):
                if f.endswith("_time"):
                    v = self._to_utc(v)
                elif f.endswith("_at"):
                    v = self._to_utc(v)
                elif f in ("client", "run_id", "parent_run_id", "top_run_id", "restart_ref_run_id",
                           "status_code", "return_code", "object_id", "user_id", "run_time_sec",
                           "ert_sec", "ert_calc", "signal", "mrt_sec", "srt_sec",
                           "created_user_id", "modified_user_id", "msg_nr"):
                    try:
                        v = int(v) if v is not None else None
                    except (TypeError, ValueError):
                        v = None
                    if f in ("parent_run_id", "top_run_id", "restart_ref_run_id", "ert_sec",
                             "mrt_sec", "srt_sec", "user_id", "created_user_id", "modified_user_id") and v == 0:
                        v = None
                elif isinstance(v, str):
                    v = v.strip() or None
                d[f] = v
            out.append(d)
        return out

    # ── kullanıcı / klasör çözümleme (resmi şema: USR→OH, OFS→OH) ─────────
    def _ids_binds(self, ids: List[int]) -> Tuple[str, Dict[str, Any]]:
        names = [f":i{n}" for n in range(len(ids))]
        return ", ".join(names), {f"i{n}": int(v) for n, v in enumerate(ids)}

    @staticmethod
    def _cache_get(cache: Dict, key: Tuple[int, int]):
        hit = cache.get(key)
        if hit and (time.monotonic() - hit[0]) < _LOOKUP_TTL_SEC:
            return True, hit[1]
        return False, None

    @staticmethod
    def _cache_put(cache: Dict, key: Tuple[int, int], val: Any) -> None:
        with _cache_lock:
            if len(cache) >= _LOOKUP_MAX:
                cache.clear()
            cache[key] = (time.monotonic(), val)

    def _lookup_names(self, ids: Iterable[int], *, kind: str = "collector") -> Dict[int, Dict[str, Any]]:
        """OH_Idnr → {name, type, client, delete_flag}.

        Kullanıcı için AH_USR_Idnr ↔ OH_Idnr varsayımı — gerçek veriyle doğrulanacak.
        """
        wanted = {int(i) for i in ids if i}
        out: Dict[int, Dict[str, Any]] = {}
        missing: List[int] = []
        for i in wanted:
            ok, val = self._cache_get(_name_cache, (self.system_id, i))
            if ok:
                if val:
                    out[i] = val
            else:
                missing.append(i)
        if not missing or not (self._mapping.get("object_headers") or {}).get("available"):
            return out
        fields = ["object_id", "object_name", "object_type", "client", "delete_flag"]
        oh_cols = (self._mapping.get("object_headers") or {}).get("columns") or {}
        if "delete_flag" not in oh_cols:
            fields = ["object_id", "object_name", "object_type", "client"]
        for n in range(0, len(missing), _IN_CHUNK):
            chunk = missing[n:n + _IN_CHUNK]
            ib, binds = self._ids_binds(chunk)
            sql = self._render("object_names_by_ids", "object_headers", fields=fields, ids_bind=ib)
            found: Set[int] = set()
            for tup in self._query(sql, binds, kind=kind):
                if not tup or tup[0] is None:
                    continue
                oid = int(tup[0])
                name = tup[1]
                otype = tup[2]
                client = tup[3]
                df = tup[4] if len(tup) > 4 else None
                rec = {"name": (str(name).strip() if name else None),
                       "type": (str(otype).strip() if otype else None),
                       "client": int(client) if client is not None else None,
                       "delete_flag": int(df) if df is not None else None}
                found.add(oid)
                out[oid] = rec
                self._cache_put(_name_cache, (self.system_id, oid), rec)
            for i in chunk:
                if i not in found:
                    self._cache_put(_name_cache, (self.system_id, i), None)
        return out

    def _home_folders(self, obj_ids: Iterable[int], *, kind: str = "collector") -> Dict[int, int]:
        """Nesne (OFS_OH_Idnr_O) → ana klasör (OFS_OH_Idnr_F, OFS_Link = 0)."""
        wanted = {int(i) for i in obj_ids if i}
        out: Dict[int, int] = {}
        missing: List[int] = []
        for i in wanted:
            ok, val = self._cache_get(_home_cache, (self.system_id, i))
            if ok:
                if val:
                    out[i] = val
            else:
                missing.append(i)
        if not missing or not (self._mapping.get("folders") or {}).get("available"):
            return out
        for n in range(0, len(missing), _IN_CHUNK):
            chunk = missing[n:n + _IN_CHUNK]
            ib, binds = self._ids_binds(chunk)
            sql = self._render("folder_links_by_objects", "folders", ids_bind=ib)
            found: Set[int] = set()
            for oid, fid in self._query(sql, binds, kind=kind):
                if oid is None or fid is None:
                    continue
                found.add(int(oid))
                out[int(oid)] = int(fid)
                self._cache_put(_home_cache, (self.system_id, int(oid)), int(fid))
            for i in chunk:
                if i not in found:
                    self._cache_put(_home_cache, (self.system_id, i), None)
        return out

    def _folder_paths(self, obj_ids: Iterable[int], *, kind: str = "collector") -> Dict[int, str]:
        """Nesne OH_Idnr → '/ÜstKlasör/Klasör' (OFS home-klasör zinciri; en çok 12 seviye, döngü korumalı)."""
        home = self._home_folders(obj_ids, kind=kind)
        if not home:
            return {}
        parent_of: Dict[int, Optional[int]] = {}
        frontier = set(home.values())
        for _ in range(12):
            todo = {f for f in frontier if f not in parent_of}
            if not todo:
                break
            parents = self._home_folders(todo, kind=kind)
            for f in todo:
                parent_of[f] = parents.get(f)
            frontier = {p for p in (parents.get(f) for f in todo) if p}
        names = self._lookup_names(set(parent_of) | {p for p in parent_of.values() if p}, kind=kind)
        paths: Dict[int, str] = {}
        for oid, fid in home.items():
            parts: List[str] = []
            seen: Set[int] = set()
            cur: Optional[int] = fid
            while cur and cur not in seen and len(parts) < 12:
                seen.add(cur)
                nm = (names.get(cur) or {}).get("name")
                if nm:
                    parts.append(nm)
                cur = parent_of.get(cur)
            if parts:
                paths[oid] = "/" + "/".join(reversed(parts))
        return paths

    def _enrich_runs(self, rows: List[Dict[str, Any]], *, kind: str = "collector") -> List[Dict[str, Any]]:
        """user_idnr + user_name_at_run (toplama anı) ve folder doldurur.

        Görüntülemede güncel ad automic_users join ile gelir. AH_USR_Idnr↔OH_Idnr
        eşleşmesi `_user_id_matched` ile işaretlenir (doğrulanacak varsayım).
        """
        if not rows:
            return rows
        try:
            names = self._lookup_names({r.get("user_id") for r in rows if r.get("user_id")}, kind=kind)
            paths = self._folder_paths({r.get("object_id") for r in rows if r.get("object_id")}, kind=kind)
        except SourceError as exc:
            note_error("oracle._enrich_runs", exc)
            names, paths = {}, {}
        for r in rows:
            uid = r.get("user_id")
            info = names.get(int(uid)) if uid is not None else None
            if info is None and uid is not None:
                info = names.get(uid)
            name = (info or {}).get("name")
            if uid is not None:
                try:
                    r["user_idnr"] = int(uid)
                except (TypeError, ValueError):
                    r["user_idnr"] = None
            else:
                r["user_idnr"] = None
            r["user_name_at_run"] = name
            r["user"] = name  # legacy / toplama anı
            matched = False
            if r.get("user_idnr") is not None and info and name:
                matched = True
                if info.get("client") is not None and r.get("client") is not None:
                    try:
                        if int(info["client"]) != int(r["client"]):
                            matched = False
                    except (TypeError, ValueError):
                        matched = False
                otype = (info.get("type") or "").upper()
                if otype and otype != "USER":
                    matched = False
            r["_user_id_matched"] = matched
            r["folder"] = paths.get(r.get("object_id"))
            # Fiili agent = AH_HostDst; grup = AH_HGDst; atanan = grup varsa grup, yoksa HostDst
            grp = (r.get("agent_group") or "").strip() or None
            r["agent_group"] = grp
            r["agent_assigned"] = grp or r.get("agent")
        return rows

    def _enrich_headers(self, rows: List[Dict[str, Any]], *, kind: str = "collector") -> List[Dict[str, Any]]:
        if not rows:
            return rows
        try:
            uids = {r.get(k) for r in rows for k in ("created_user_id", "modified_user_id") if r.get(k)}
            names = self._lookup_names(uids, kind=kind)
            paths = self._folder_paths({r.get("object_id") for r in rows if r.get("object_id")}, kind=kind)
        except SourceError as exc:
            note_error("oracle._enrich_headers", exc)
            names, paths = {}, {}
        for r in rows:
            r["created_by"] = (names.get(r.get("created_user_id")) or {}).get("name")
            r["modified_by"] = (names.get(r.get("modified_user_id")) or {}).get("name")
            r["folder"] = paths.get(r.get("object_id"))
        return rows

    # ── arayüz ────────────────────────────────────────────────────────────
    def test_connection(self) -> ConnectionResult:
        t0 = time.monotonic()
        try:
            conn = self._connect()
            rows = self._query("SELECT 1 FROM dual")
            ok = bool(rows)
        except SourceError as exc:
            return ConnectionResult(ok=False, message=str(exc), details={"code": exc.code})
        latency = round((time.monotonic() - t0) * 1000, 1)
        warnings: List[str] = []
        role_info = self.read_database_role()
        details: Dict[str, Any] = {
            "database_role": role_info.get("database_role"),
            "open_mode": role_info.get("open_mode"),
            "role_known": role_info.get("role_known"),
            "database_role_display": role_info.get("database_role") or "bilinmiyor",
            "open_mode_display": role_info.get("open_mode") or "bilinmiyor",
            "primary_warning": False,
            "requires_primary_ack": False,
        }
        role_u = (details["database_role"] or "").upper()
        if role_u == "PRIMARY":
            details["primary_warning"] = True
            details["requires_primary_ack"] = True
            warnings.append(
                "Canlı primary veritabanı; sorgular Automic performansını etkileyebilir. "
                "Kurulumu tamamlamak için açık onay gerekir."
            )
        elif not details["role_known"]:
            warnings.append("V$DATABASE rolü okunamadı (bilinmiyor); bağlantı yine de kullanılabilir.")
        if (self.connection.get("user") or "").strip().lower() in ("master", "uc4", "system", "sys"):
            warnings.append("Uygulama/şema kullanıcısı kullanılıyor; ayrı salt okunur servis kullanıcısı önerilir.")
        return ConnectionResult(
            ok=ok, message="Bağlantı başarılı" if ok else "Beklenmeyen yanıt",
            db_version=getattr(conn, "version", None), driver_mode=self._mode,
            latency_ms=latency, warnings=warnings, details=details,
        )

    def _find_schema(self) -> str:
        if self._schema:
            return self._schema
        rows = self._query(
            "SELECT owner FROM all_tables WHERE table_name = 'AH' ORDER BY owner", max_rows=10
        )
        owners = [r[0] for r in rows]
        if not owners:
            raise SourceError(
                "AE tablosu (AH) görünmüyor: kullanıcıya AE şeması tablolarında SELECT yetkisi verilmeli.",
                code="missing_grant", retryable=False,
            )
        if len(owners) > 1:
            logger.warning("Birden fazla AH sahibi: %s — ilki seçildi; bağlantıda schema belirtin", owners)
        return owners[0]

    def discover(self) -> Dict[str, Any]:
        conn = self._connect()
        warnings: List[str] = []
        schema = self._find_schema()
        self._schema = schema
        user = (self.connection.get("user") or "").upper()

        tables = sorted({t.upper() for spec in (self._profile.get("tables") or {}).values()
                         for t in spec.get("table") or []})
        tbl_binds = {f"t{i}": t for i, t in enumerate(tables)}
        tbl_in = ", ".join(f":t{i}" for i in range(len(tables)))
        cols_rows = self._query(
            f"SELECT table_name, column_name, data_type FROM all_tab_columns "
            f"WHERE owner = :o AND table_name IN ({tbl_in})",
            {"o": schema, **tbl_binds},
        )
        columns_by_table: Dict[str, set] = {}
        col_types: Dict[str, Dict[str, str]] = {}
        for t, c, dt in cols_rows:
            columns_by_table.setdefault(t, set()).add(c)
            col_types.setdefault(t, {})[c] = dt
        mapping = templates.resolve_mapping(self._profile, columns_by_table)
        self._mapping = mapping
        for lname, m in mapping.items():
            if not m["available"]:
                warnings.append(f"{lname}: eksik zorunlu alanlar {m['missing_required']} (tablo: {m['table']})")

        idx_rows = self._query(
            f"SELECT table_name, index_name, column_name, column_position FROM all_ind_columns "
            f"WHERE table_owner = :o AND table_name IN ({tbl_in}) ORDER BY table_name, index_name, column_position",
            {"o": schema, **tbl_binds},
        )
        indexes: Dict[str, Dict[str, List[str]]] = {}
        for t, ix, c, _pos in idx_rows:
            indexes.setdefault(t, {}).setdefault(ix, []).append(c)
        index_warnings = []
        ex = mapping.get("executions") or {}
        end_col = (ex.get("columns") or {}).get("end_time")
        if ex.get("table") and end_col:
            lead_cols = [cols[0] for cols in (indexes.get(ex["table"]) or {}).values() if cols]
            if end_col not in lead_cols:
                index_warnings.append(
                    f"{ex['table']}.{end_col} üzerinde öncü indeks yok — artımlı sorgular tam tarama yapabilir. "
                    "DBA ile indeks veya daha küçük dilim/aralık değerlendirin."
                )

        priv_rows = []
        try:
            priv_rows = [r[0] for r in self._query("SELECT privilege FROM session_privs")]
        except SourceError:
            warnings.append("session_privs okunamadı; yetki denetimi yapılamadı.")
        write_privs = sorted(p for p in priv_rows if p in _WRITE_PRIVS or p.endswith(" ANY TABLE"))
        try:
            role_rows = [r[0] for r in self._query("SELECT role FROM session_roles")]
        except SourceError:
            role_rows = []
        if "DBA" in role_rows:
            write_privs.append("DBA (rol)")
        tab_privs: List[str] = []
        try:
            tp = self._query(
                "SELECT DISTINCT privilege FROM all_tab_privs WHERE grantee = :u AND table_schema = :o "
                "AND privilege IN ('INSERT','UPDATE','DELETE','ALTER','INDEX','REFERENCES')",
                {"u": user, "o": schema},
            )
            tab_privs = [r[0] for r in tp]
        except SourceError as _e:
            note_error("oracle.discover", _e)
        is_owner = user == schema
        if is_owner:
            warnings.append("Bağlanan kullanıcı AE şemasının sahibi — salt okunur servis kullanıcısı kullanın.")
        if write_privs or tab_privs:
            warnings.append(
                "Kullanıcıda yazma yetkisi var: " + ", ".join(write_privs + tab_privs)
                + " — yalnızca SELECT verilmiş bir kullanıcı önerilir."
            )

        role_info = self.read_database_role()
        db_role = role_info.get("database_role")
        open_mode = role_info.get("open_mode")
        role_known = bool(role_info.get("role_known"))

        freshness_method = "unavailable"
        try:
            self._dataguard_lag()
            freshness_method = "dataguard"
        except SourceError:
            if (ex.get("columns") or {}).get("activation_time"):
                freshness_method = "max_timestamp"

        ts_mode = "utc"
        utc_now_db = local_now_db = None
        try:
            r = self._query("SELECT SYS_EXTRACT_UTC(SYSTIMESTAMP), SYSDATE FROM dual")
            utc_now_db, local_now_db = r[0]
        except SourceError as _e:
            note_error("oracle.discover", _e)

        clients_seen: List[Dict[str, Any]] = []
        status_dist: Dict[str, int] = {}
        # daily_profile / latest_activation kaynakta YOK (zaman kolonu = yüksek risk).
        # Client listesi bağlantı ayarından; 24s profil modül DB'den gelir.
        warnings.append(
            "Kaynak günlük profil/zaman taraması yapılmaz (30–40 TB koruması). "
            "Client ve istatistikler toplama sonrası modül DB'den okunur."
        )
        if utc_now_db is not None and local_now_db is not None and utc_now_db != local_now_db:
            # Kabaca: sürücü yerel SYSDATE ≠ UTC ise yerel damga ihtimali
            if abs((utc_now_db - local_now_db).total_seconds()) > 60:
                ts_mode = "local"
        if ts_mode == "local" and not self.connection.get("db_timezone"):
            warnings.append("AE zaman damgaları yerel saat görünüyor; bağlantıda db_timezone belirtin.")

        oh_ok = bool((mapping.get("object_headers") or {}).get("available"))
        ot_ok = bool((mapping.get("object_scripts") or {}).get("available"))
        usage_map = mapping.get("object_usage") or {}
        usage_ok = bool(usage_map.get("available") and (usage_map.get("columns") or {}).get("child_name"))
        features = {
            "ended_executions": bool(ex.get("available")),
            "active": bool((mapping.get("active") or {}).get("available")),
            "children": bool(ex.get("available") and (ex.get("columns") or {}).get("parent_run_id")),
            "restarts": bool(ex.get("available") and (ex.get("columns") or {}).get("restart_ref_run_id")),
            "reports": bool((mapping.get("report_text") or {}).get("available")),
            "freshness": freshness_method,
            "objects": True if oh_ok else "unavailable",
            "versions": True if ot_ok else "unavailable",
            "usage_graph": True if usage_ok else "unavailable",
            # kullanıcı adı: AH_USR_Idnr → OH_Name; klasör: OFS (OFS_Link = 0) → OH_Name
            "user_names": bool(ex.get("available") and (ex.get("columns") or {}).get("user_id") and oh_ok),
            "folders": bool(ex.get("available") and (ex.get("columns") or {}).get("object_id") and oh_ok
                            and (mapping.get("folders") or {}).get("available")),
            # ERT: AH_ERT / EH_Ert / EH_ERTEnd / OH_Ert (resmi AE kolonları)
            "ert": bool((ex.get("columns") or {}).get("ert_sec")
                        or (mapping.get("active") or {}).get("columns", {}).get("ert_sec")),
            "agents": True if (mapping.get("hosts") or {}).get("available") else "unavailable",
            "infrastructure": True if (
                (mapping.get("hosts") or {}).get("available")
                and (mapping.get("mqsrv") or {}).get("available")
            ) else "unavailable",
        }
        return {
            "engine": "oracle",
            "source_type": self.source_type,
            "profile": self._profile.get("profile"),
            "profile_rev": self._profile.get("rev"),
            "db_version": getattr(conn, "version", None),
            "driver_mode": self._mode,
            "schema": schema,
            "user": user,
            "database_role": db_role,
            "open_mode": open_mode,
            "role_known": role_known,
            "timestamps": ts_mode,
            "mapping": mapping,
            "column_types": {t: col_types.get(t, {}) for t in columns_by_table},
            "indexes": indexes,
            "index_warnings": index_warnings,
            "privileges": {
                "write_privileges": write_privs + tab_privs,
                "is_schema_owner": is_owner,
                "read_only_ok": not (write_privs or tab_privs or is_owner),
            },
            "features": features,
            "clients_seen": clients_seen,
            "status_distribution_24h": status_dist,
            "warnings": warnings,
            "discovered_at": datetime.now(timezone.utc).isoformat(),
        }

    @staticmethod
    def _parse_interval(val: str) -> Optional[float]:
        # '+00 00:05:12' veya '+00 00:05:12.345'
        m = re.match(r"^\s*\+?(\d+)\s+(\d+):(\d+):(\d+(?:\.\d+)?)", val or "")
        if not m:
            return None
        d, h, mi, s = m.groups()
        return int(d) * 86400 + int(h) * 3600 + int(mi) * 60 + float(s)

    def _dataguard_lag(self) -> Optional[float]:
        r = self._query("SELECT value FROM v$dataguard_stats WHERE name = 'apply lag'")
        if not r or r[0][0] is None:
            raise SourceError("apply lag yok", code="no_dataguard")
        return self._parse_interval(str(r[0][0]))

    def source_freshness(self) -> Freshness:
        """DG lag varsa kullan; kaynak zaman taraması yok (modül DB watermark)."""
        method = (self.capability.get("features") or {}).get("freshness") or "module_watermark"
        if method == "dataguard":
            try:
                lag = self._dataguard_lag()
                return Freshness(lag_sec=lag, method="dataguard",
                                 latest_at=datetime.now(timezone.utc) - timedelta(seconds=lag or 0))
            except SourceError as _e:
                note_error("oracle.source_freshness", _e)
        return Freshness(lag_sec=None, method="module_watermark", latest_at=None)

    def latest_run_id(self, client: int) -> Optional[int]:
        sql = self._render("latest_run_id", "executions", limit=1)
        rows = self._query(sql, {"client": int(client)}, kind="collector", query_name="latest_run_id")
        if not rows or rows[0][0] is None:
            return None
        return int(rows[0][0])

    def min_run_id(self) -> Optional[int]:
        """Kaynak MIN(AH_Idnr) — client filtresi yok (PK INDEX FULL SCAN MIN/MAX)."""
        sql = self._render("min_run_id", "executions", limit=1)
        rows = self._query(sql, {}, kind="collector", query_name="min_run_id")
        if not rows or rows[0][0] is None:
            return None
        return int(rows[0][0])

    def fetch_ended_executions(self, clients, t_from, t_to, *, limit, id_min=None, id_max=None):
        """AH_Idnr BETWEEN (PK); zaman süzmesi uygulama katmanında."""
        if id_min is None or id_max is None:
            raise SourceError(
                "RunID aralığı gerekli (zaman→RunID eşlemesi / bootstrap).",
                code="runid_bounds_required", retryable=False,
            )
        id_min, id_max = int(id_min), int(id_max)
        if id_max <= id_min:
            return []
        cb, binds = self._clients_binds(clients)
        sql = self._render("ended_executions", "executions", fields=list(EXECUTION_FIELDS),
                           clients_bind=cb, limit=limit + 1)
        binds.update({"id_min": id_min, "id_max": id_max})
        rows = self._enrich_runs(self._rows_to_dicts(
            self._query(sql, binds, kind="collector", query_name="ended_executions"), EXECUTION_FIELDS))
        out = []
        for r in rows:
            et = r.get("end_time") or r.get("activation_time")
            if et is not None and t_from <= et < t_to:
                out.append(r)
        return out

    def fetch_ended_by_runid_range(self, clients, id_min: int, id_max: int, *, limit: int):
        cb, binds = self._clients_binds(clients)
        sql = self._render("ended_executions", "executions", fields=list(EXECUTION_FIELDS),
                           clients_bind=cb, limit=limit + 1)
        binds.update({"id_min": int(id_min), "id_max": int(id_max)})
        return self._enrich_runs(self._rows_to_dicts(
            self._query(sql, binds, kind="collector", query_name="ended_executions"), EXECUTION_FIELDS))

    def count_ended_by_id_range(self, clients, id_min: int, id_max: int) -> int:
        """AH satır sayısı — yalnız PK aralığı (mutabakat)."""
        if int(id_max) <= int(id_min):
            return 0
        cb, binds = self._clients_binds(list(clients))
        binds.update({"id_min": int(id_min), "id_max": int(id_max)})
        sql = self._render("count_ended_by_id_range", "executions", clients_bind=cb, limit=1)
        rows = self._query(sql, binds, kind="collector", query_name="count_ended_by_id_range")
        if not rows or rows[0][0] is None:
            return 0
        return int(rows[0][0])

    def fetch_active_executions(self, clients, *, limit):
        cb, binds = self._clients_binds(clients)
        sql = self._render("active_executions", "active", fields=list(ACTIVE_FIELDS),
                           clients_bind=cb, limit=limit)
        t0 = time.monotonic()
        raw = self._query(sql, binds, kind="collector", query_name="active_executions")
        rows = self._enrich_runs(self._rows_to_dicts(raw, ACTIVE_FIELDS))
        g = self.settings.get("source_guard") or {}
        if g.get("cautious_mode", True):
            logger.info(
                "automic_source ACTIVE_EXECUTIONS cautious elapsed_sec=%.3f rows=%d clients=%s limit=%d",
                time.monotonic() - t0, len(rows), list(clients), limit,
            )
        return rows

    def find_users(self, pattern, *, limit=50):
        raise SourceError(
            "Kaynakta kullanıcı adı araması kaldırıldı (LIKE/USR_Idnr riski). "
            "Kullanıcı sorguları yalnız modül DB'den yanıtlanır.",
            code="capability_removed", retryable=False,
        )

    def fetch_runs_by_users(self, user_ids, clients, t_from, t_to, *, limit):
        raise SourceError(
            "Kaynakta kullanıcıya göre çalışma araması kaldırıldı. Modül DB kullanın.",
            code="capability_removed", retryable=False,
        )

    def fetch_execution(self, client, run_id):
        sql = self._render("execution_by_id", "executions", fields=list(EXECUTION_FIELDS), limit=1)
        rows = self._rows_to_dicts(
            self._query(sql, {"client": int(client), "run_id": int(run_id)}, kind="chat",
                        query_name="execution_by_id"),
            EXECUTION_FIELDS)
        rows = self._enrich_runs(rows, kind="chat")
        return rows[0] if rows else None

    def fetch_children(self, client, run_id, *, limit, id_min=None, id_max=None):
        if not self.supports("children"):
            return []
        if id_min is None or id_max is None:
            raise SourceError(
                "Alt görev sorgusu için AH_Idnr aralığı gerekli (üst RunID → zaman eşlemesi).",
                code="runid_bounds_required", retryable=False,
            )
        sql = self._render("children", "executions", fields=list(EXECUTION_FIELDS), limit=limit)
        binds = {
            "client": int(client), "run_id": int(run_id),
            "id_min": int(id_min), "id_max": int(id_max),
        }
        rows = self._rows_to_dicts(
            self._query(sql, binds, kind="chat", query_name="children"), EXECUTION_FIELDS)
        return self._enrich_runs(rows, kind="chat")

    def fetch_restarts(self, client, run_id, *, limit, id_min=None, id_max=None):
        if not self.supports("restarts"):
            return []
        if id_min is None or id_max is None:
            raise SourceError(
                "Restart sorgusu için AH_Idnr aralığı gerekli (üst RunID → zaman eşlemesi).",
                code="runid_bounds_required", retryable=False,
            )
        cur = self.fetch_execution(client, run_id)
        ref = (cur or {}).get("restart_ref_run_id") or int(run_id)
        sql = self._render("restarts", "executions", fields=list(EXECUTION_FIELDS), limit=limit)
        binds = {
            "client": int(client), "run_id": int(run_id), "ref_id": int(ref),
            "id_min": int(id_min), "id_max": int(id_max),
        }
        rows = self._query(sql, binds, kind="chat", query_name="restarts")
        rows = self._rows_to_dicts(rows, EXECUTION_FIELDS)
        return self._enrich_runs([r for r in rows if r.get("run_id") != int(run_id)], kind="chat")
    def list_reports(self, client, run_id):
        """Canlı: yalnız RH (düşük risk). RT DISTINCT orta risk — kullanılmaz."""
        if not self.supports("reports"):
            return []
        rh = self._mapping.get("report_headers") or {}
        lim = min(50, self._default_fetch())
        if not rh.get("available"):
            raise SourceError(
                "Rapor tipi listesi için RH gerekli (RT taraması canlıda yasak — orta risk).",
                code="template_risk", retryable=False,
            )
        rows = self._query(self._render("report_types_rh", "report_headers", limit=lim),
                           {"run_id": int(run_id)}, kind="chat", query_name="report_types_rh")
        return sorted({str(r[0]).strip() for r in rows if r[0] is not None})

    def fetch_report(self, client, run_id, report_type, *, head, tail, max_scan_lines):
        """Yalnız RT_AH_Idnr + RT_Type (+ LNR aralığı); FETCH FIRST ile sınırlı."""
        if not self.supports("reports"):
            raise SourceError("Rapor tabloları bu sistemde kullanılamıyor.", code="capability_missing",
                              retryable=False)
        g = self.settings.get("source_guard") or {}
        max_fetch = int(g.get("report_max_fetch") or 500)
        head = max(1, min(int(head), max_fetch))
        tail = max(0, min(int(tail), max_fetch - head))
        binds = {"run_id": int(run_id), "rtype": report_type}
        cnt = self._query(self._render("report_count", "report_text", limit=1), binds, kind="chat",
                          query_name="report_count")
        n_rows = int(cnt[0][0] or 0) if cnt else 0
        max_lnr = int(cnt[0][1] or 0) if cnt else 0
        if n_rows == 0:
            return ReportText(report_type=report_type, lines=[], total_lines=0, truncated=False)
        fields = ["line_no", "content", "msg_nr", "msg_insert"]
        # Her zaman head+tail yolu (tam tablo çekme yok); küçük raporlarda tail_from düşük kalır
        fetch_cap = min(max_fetch, head + tail + 2, max(1, int(max_scan_lines)))
        b = dict(binds, head_to=head, tail_from=max(head, max_lnr - tail) if max_lnr else head)
        rows = self._query(
            self._render("report_range", "report_text", fields=fields, limit=fetch_cap),
            b, kind="chat", query_name="report_range",
        )
        truncated = n_rows > fetch_cap or n_rows > (head + tail)
        lines: List[str] = []
        for _lnr, content, msg_nr, msg_insert in rows:
            if content is not None:
                text = content.read() if hasattr(content, "read") else str(content)
                lines.extend(text.splitlines() or [""])
            elif msg_nr or msg_insert:
                ins = str(msg_insert).strip() if msg_insert else ""
                lines.append(f"[MsgNr {int(msg_nr)}] {ins}".rstrip() if msg_nr else ins)
        return ReportText(report_type=report_type, lines=lines, total_lines=max(n_rows, len(lines)),
                          truncated=truncated)

    def fetch_object_header(self, client, object_name):
        if not self.supports("objects"):
            return None
        sql = self._render("object_header_by_name", "object_headers",
                           fields=list(OBJECT_HEADER_FIELDS), limit=1)
        rows = self._rows_to_dicts(
            self._query(sql, {"client": int(client), "name": object_name}, kind="chat",
                        query_name="object_header_by_name"),
            OBJECT_HEADER_FIELDS)
        rows = self._enrich_headers(rows, kind="chat")
        return rows[0] if rows else None

    def fetch_object_headers(self, clients, *, since=None, limit=500, id_min=None, id_max=None):
        """OH_Idnr PK aralığı. Zaman filtresi (since) kaynakta kullanılmaz."""
        if not self.supports("objects"):
            return []
        if id_min is None or id_max is None:
            raise SourceError(
                "OH senkron için OH_Idnr aralığı gerekli (zaman taraması yok).",
                code="runid_bounds_required", retryable=False,
            )
        cb, binds = self._clients_binds(list(clients))
        binds.update({"id_min": int(id_min), "id_max": int(id_max)})
        sql = self._render("object_headers_by_id_range", "object_headers",
                           fields=list(OBJECT_HEADER_FIELDS), clients_bind=cb, limit=limit)
        rows = self._rows_to_dicts(
            self._query(sql, binds, kind="chat", query_name="object_headers_by_id_range"),
            OBJECT_HEADER_FIELDS)
        return self._enrich_headers(rows, kind="chat")

    def fetch_users_by_id_range(self, clients, *, id_min: int, id_max: int, limit: int = 500):
        """OH OType=USER — PK aralığı; silinmişler dahil (USR tablosu yok)."""
        if not self.supports("objects"):
            return []
        if id_min is None or id_max is None:
            raise SourceError(
                "USER senkron için OH_Idnr aralığı gerekli.",
                code="runid_bounds_required", retryable=False,
            )
        oh = self._mapping.get("object_headers") or {}
        if not oh.get("available"):
            return []
        cols = oh.get("columns") or {}
        if "object_type" not in cols:
            raise SourceError("OH_OType yok — USER senkron yapılamaz", code="capability_missing",
                              retryable=False)
        fields = [f for f in USER_HEADER_FIELDS if f in cols]
        cb, binds = self._clients_binds(list(clients))
        binds.update({"id_min": int(id_min), "id_max": int(id_max)})
        sql = self._render(
            "object_headers_users_by_id_range", "object_headers",
            fields=fields, clients_bind=cb, limit=limit,
        )
        return self._rows_to_dicts(
            self._query(sql, binds, kind="collector", query_name="object_headers_users_by_id_range"),
            fields,
        )

    def user_object_id_bounds(self, clients: List[int]) -> Optional[Tuple[int, int]]:
        """USER nesnelerinin min/max OH_Idnr — PK yürüyüşü için (zaman taraması yok)."""
        if not self.supports("objects"):
            return None
        oh = self._mapping.get("object_headers") or {}
        if not oh.get("available") or "object_type" not in (oh.get("columns") or {}):
            return None
        cb, binds = self._clients_binds(list(clients))
        sql = self._render("user_object_id_bounds", "object_headers", clients_bind=cb, limit=1)
        rows = self._query(sql, binds, kind="collector", query_name="user_object_id_bounds")
        if not rows or rows[0][0] is None or rows[0][1] is None:
            return None
        return int(rows[0][0]), int(rows[0][1])

    def fetch_object_script(self, object_id, *, max_lines=20000):
        """OT satırları. OT_Type 0 = process script (başlıksız), 1/2/3 = pre/post/inherit-post bölümleri."""
        if not self.supports("versions"):
            raise SourceError("Nesne script tablosu (OT) bu sistemde kullanılamıyor.",
                              code="capability_missing", retryable=False)
        rows = self._query(
            self._render("object_script_lines", "object_scripts"),
            {"object_id": int(object_id)}, kind="chat", max_rows=max_lines + 1,
        )
        lines: List[str] = []
        last_type: Optional[int] = None
        for stype, _lnr, content in rows[:max_lines]:
            try:
                st = int(stype) if stype is not None else 0
            except (TypeError, ValueError):
                st = 0
            if st != last_type:
                if st in _SCRIPT_SECTIONS:
                    # "!" Automic script yorum karakteridir; bölüm başlığı yorum olarak eklenir.
                    lines.append(f"! ===== {_SCRIPT_SECTIONS[st]} (OT_Type={st}) =====")
                last_type = st
            if content is None:
                lines.append("")
                continue
            text = content.read() if hasattr(content, "read") else str(content)
            # OT satırı bazen birden fazla satır içerir
            parts = text.splitlines() or [text]
            lines.extend(parts)
        return lines

    def fetch_jpp_by_parent_range(self, id_min: int, id_max: int, *, limit: int):
        """JPP satırları — ebeveyn OH_Idnr PK aralığı (isim taraması yok)."""
        if not self.supports("usage_graph"):
            raise SourceError("Usage/bağımlılık (JPP) bu sistemde kullanılamıyor.",
                              code="capability_missing", retryable=False)
        id_min, id_max = int(id_min), int(id_max)
        if id_max <= id_min:
            return []
        fields = ["parent_id", "line_no", "child_name", "child_type"]
        sql = self._render("usage_by_parent_id_range", "object_usage", fields=fields, limit=limit)
        rows = self._query(
            sql, {"id_min": id_min, "id_max": id_max}, kind="collector",
            query_name="usage_by_parent_id_range",
        )
        out: List[Dict[str, Any]] = []
        for row in rows:
            d = dict(zip(fields, row))
            child = (d.get("child_name") or "").strip()
            if not child or d.get("parent_id") is None:
                continue
            out.append({
                "parent_object_id": int(d["parent_id"]),
                "line_no": int(d["line_no"] or 0),
                "child_name": child,
                "child_type": d.get("child_type"),
            })
        return out

    def fetch_object_usage(self, client, object_name, *, depth=1):
        raise SourceError(
            "Kaynakta canlı usage (isim/JPP_Object) sorgusu kaldırıldı; "
            "collector JPP senkronu + modül DB kullanın.",
            code="capability_removed", retryable=False,
        )

    def count_table(self, table: str) -> int:
        from app.services.automic.small_tables import is_small_ref_table
        t = (table or "").upper()
        if not is_small_ref_table(t):
            raise SourceError(f"{t} küçük referans listesinde değil", code="not_small_table", retryable=False)
        logical = {
            "HOST": "hosts", "MQSRV": "mqsrv", "OHG": "agent_groups", "OHGF": "agent_group_filters",
        }.get(t)
        if not logical:
            raise SourceError(f"count_table: {t}", code="unknown_table", retryable=False)
        tmap = self._tmap(logical)
        if not tmap.get("available"):
            return 0
        sql = self._render("table_row_count", logical, limit=1)
        rows = self._query(sql, {}, kind="collector", query_name="table_row_count")
        return int(rows[0][0]) if rows else 0

    def _oh_names(self, ids: List[int]) -> Dict[int, Dict[str, Any]]:
        if not ids:
            return {}
        # object_names_by_ids — mevcut şablon
        fields = ["object_id", "client", "object_name", "object_type"]
        out: Dict[int, Dict[str, Any]] = {}
        chunk = 200
        for i in range(0, len(ids), chunk):
            part = ids[i:i + chunk]
            binds = {f"i{j}": int(v) for j, v in enumerate(part)}
            ids_bind = ", ".join(f":i{j}" for j in range(len(part)))
            sql = self._render(
                "object_names_by_ids", "object_headers", fields=fields,
                ids_bind=ids_bind, limit=len(part) + 10,
            )
            rows = self._query(sql, binds, kind="collector", query_name="object_names_by_ids")
            for row in rows:
                d = dict(zip(fields, row))
                if d.get("object_id") is not None:
                    out[int(d["object_id"])] = d
        return out

    def fetch_hosts(self) -> List[Dict[str, Any]]:
        from app.services.automic.source.base import HOST_FIELDS
        tmap = self._tmap("hosts")
        if not tmap.get("available"):
            return []
        fields = [f for f in HOST_FIELDS if f in (tmap.get("columns") or {})]
        lim = int((self.settings.get("source_guard") or {}).get("small_table_row_threshold") or 10000)
        sql = self._render("hosts_all", "hosts", fields=fields, limit=lim)
        rows = self._query(sql, {}, kind="collector", query_name="hosts_all")
        raw = [dict(zip(fields, row)) for row in rows]
        names = self._oh_names([int(r["oh_idnr"]) for r in raw if r.get("oh_idnr") is not None])
        out = []
        for r in raw:
            oid = int(r["oh_idnr"]) if r.get("oh_idnr") is not None else None
            nh = names.get(oid or -1) or {}
            out.append({
                "oh_idnr": oid, "name": nh.get("object_name"), "client": nh.get("client"),
                "ip": r.get("ip"), "hostname": r.get("hostname"), "port": r.get("port"),
                "os": r.get("os"), "hardware": r.get("hardware"), "platform": r.get("platform"),
                "version": r.get("version"), "host_active": r.get("host_active"),
                "roles": r.get("roles"),
            })
        return out

    def fetch_mqsrv(self) -> List[Dict[str, Any]]:
        from app.services.automic.source.base import MQSRV_FIELDS
        tmap = self._tmap("mqsrv")
        if not tmap.get("available"):
            return []
        fields = [f for f in MQSRV_FIELDS if f in (tmap.get("columns") or {})]
        lim = int((self.settings.get("source_guard") or {}).get("small_table_row_threshold") or 10000)
        sql = self._render("mqsrv_all", "mqsrv", fields=fields, limit=lim)
        rows = self._query(sql, {}, kind="collector", query_name="mqsrv_all")
        return [dict(zip(fields, row)) for row in rows]

    def fetch_agent_groups(self) -> Dict[str, Any]:
        from app.services.automic.source.base import OHG_FIELDS, OHGF_FIELDS
        groups: List[Dict[str, Any]] = []
        members: List[Dict[str, Any]] = []
        tmap_g = self._tmap("agent_groups")
        tmap_f = self._tmap("agent_group_filters")
        lim = int((self.settings.get("source_guard") or {}).get("small_table_row_threshold") or 10000)
        if tmap_g.get("available"):
            fields = [f for f in OHG_FIELDS if f in (tmap_g.get("columns") or {})]
            sql = self._render("ohg_all", "agent_groups", fields=fields, limit=lim)
            rows = self._query(sql, {}, kind="collector", query_name="ohg_all")
            raw = [dict(zip(fields, row)) for row in rows]
            names = self._oh_names([int(r["oh_idnr"]) for r in raw if r.get("oh_idnr") is not None])
            for r in raw:
                oid = int(r["oh_idnr"]) if r.get("oh_idnr") is not None else None
                nh = names.get(oid or -1) or {}
                groups.append({
                    "oh_idnr": oid, "name": nh.get("object_name"), "client": nh.get("client"),
                    "platform": r.get("platform"), "mode": r.get("mode"),
                })
        if tmap_f.get("available"):
            fields = [f for f in OHGF_FIELDS if f in (tmap_f.get("columns") or {})]
            sql = self._render("ohgf_all", "agent_group_filters", fields=fields, limit=lim)
            rows = self._query(sql, {}, kind="collector", query_name="ohgf_all")
            raw = [dict(zip(fields, row)) for row in rows]
            names = self._oh_names([int(r["oh_idnr"]) for r in raw if r.get("oh_idnr") is not None])
            for r in raw:
                oid = int(r["oh_idnr"]) if r.get("oh_idnr") is not None else None
                nh = names.get(oid or -1) or {}
                an = (r.get("agent_name") or "").strip()
                if an:
                    members.append({"group_name": nh.get("object_name"), "agent_name": an})
        return {"groups": groups, "members": members}
