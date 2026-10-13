"""Automic (UC4) sohbet araçları — READ_ONLY, domain 'automic'.

Veri modül DB'sinden (:5435) okunur; tekil detay/rapor/alt adım gerektiğinde
Automic kaynak DB'ye (automic_source) guard + maskeleme ile gidilir.
Serbest SQL yok — yalnız önceden tanımlı şablonlar / parametreli araçlar.
Yalnızca Automic sohbetinde görünür (unified_tool_chat platform filtresi).
"""
from __future__ import annotations
from app.services.automic.errors import note_error

from typing import Any, Dict, Optional

from sqlalchemy.orm import Session

from app.services.agent.tools import RiskLevel, Tool
from app.services.automic.arg_sanitize import clean_str_filter as _clean_str_filter
from app.services.automic.arg_sanitize import sanitize_search_args as _sanitize_search_args

_SYSTEM = {"system": {"type": "string", "description": "AE sistem adı veya id (boş = varsayılan)"}}
_CLIENT = {"client": {"type": "integer", "description": "Client numarası (boş = izlenen tüm client'lar)"}}
_RANGE = {
    "range": {"type": "string", "description": "Zaman aralığı: 1h, 24h, 7d, 30d, 90d (varsayılan 24h)"},
    "from": {"type": "string", "description": "ISO başlangıç (range yerine)"},
    "to": {"type": "string", "description": "ISO bitiş"},
}


def _int(v: Any) -> Optional[int]:
    try:
        return int(v) if v not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _with_system(args: Dict[str, Any], ctx: Dict[str, Any], fn):
    from app.services.automic.database import get_automic_thread_session
    from app.services.automic.service import resolve_system
    from app.services.automic.source.base import SourceError

    plat = (ctx or {}).get("platform")
    doms = (ctx or {}).get("domains") or set()
    if plat != "automic" and "automic" not in doms:
        return {"ok": False, "error": "Automic araçları yalnız Automic kapsamında kullanılabilir."}
    adb = get_automic_thread_session()
    if adb is None:
        return {"ok": False, "error": "Automic modül veritabanına erişilemiyor."}
    try:
        system = resolve_system(adb, args.get("system") or ctx.get("automic_system_id"))
        if system is None and args.get("system") and ctx.get("automic_system_id"):
            # Model uydurma/yanlış bir sistem adı verdiyse (düşük think seviyesinde sık) sohbetin
            # bağlı olduğu sisteme düş — sohbet zaten tek sisteme bağlıdır.
            system = resolve_system(adb, ctx.get("automic_system_id"))
        if system is None:
            return {"ok": False, "error": "Tanımlı Automic sistemi yok veya bulunamadı."}
        try:
            res = fn(adb, system)
        except SourceError as exc:
            return {"ok": False, "error": str(exc), "code": exc.code}
        if isinstance(res, dict):
            res.setdefault("system", system.name)
            res.setdefault("system_id", system.id)
            from app.services.automic.error_codes import annotate_result
            annotate_result(res)
        return res
    finally:
        adb.close()


def _search(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from datetime import datetime, timedelta, timezone

    from app.services.automic import queries as q
    from app.services.automic.clock import apply_window, now_utc, window_mode
    from app.services.automic.followup_context import apply_forced_filters
    args = _sanitize_search_args(apply_forced_filters(apply_window(args)))
    mode = window_mode()

    def run(adb, system):
        local_args = dict(args)
        # Nesne/son durum: zaman yoksa 90g rolling DEĞİL — mevcut veri kapsamına hizala
        # (90g, kapsam öncesi boş günler yüzünden sahte "veri yok" notu üretiyordu).
        if mode == "entity_latest" and not local_args.get("from") and not local_args.get("to"):
            try:
                cl = system.clients or []
                tip = now_utc()
                cov = q.data_coverage(
                    adb, system, [int(c) for c in cl],
                    tip - timedelta(days=3650), tip + timedelta(days=1),
                )
                t0 = cov.get("continuous_since") or cov.get("data_first_at")
                t1 = cov.get("data_last_at")
                if t0 and t1:
                    local_args["from"] = t0
                    # bitiş exclusive: son kaydı dahil et
                    try:
                        end = datetime.fromisoformat(str(t1).replace("Z", "+00:00")) + timedelta(seconds=1)
                        local_args["to"] = end.isoformat()
                    except (TypeError, ValueError):
                        local_args["to"] = t1
                    local_args.pop("range", None)
            except Exception:
                local_args["range"] = "90d"
        kw = dict(
            object_name=local_args.get("object_name"), object_type=local_args.get("object_type"),
            status_class=local_args.get("status_class"), status_code=_int(local_args.get("status_code")),
            agent=local_args.get("agent"), folder=local_args.get("folder"),
            clients=[_int(local_args["client"])] if _int(local_args.get("client")) else None,
            range_=local_args.get("range"), t_from=local_args.get("from"), t_to=local_args.get("to"),
            min_duration_sec=local_args.get("min_duration_sec"), parent_run_id=_int(local_args.get("parent_run_id")),
            sort=local_args.get("sort") or "end_desc", limit=_int(local_args.get("limit")) or 25,
            offset=_int(local_args.get("offset")) or 0,
        )
        user = _clean_str_filter(local_args.get("user"))
        if user:
            res = q.search_by_username(adb, system, user=user, **kw)
        else:
            res = q.search_executions(adb, system, **kw)
        # Varsayılan 24h boş + açık kullanıcı tarihi yok → aynı uzunlukta en son veri dönemine kaydır
        if (
            isinstance(res, dict)
            and int(res.get("total") or 0) == 0
            and res.get("data_status") == "NO_DATA_IN_RANGE"
            and mode != "entity_latest"
            and not local_args.get("from")
            and (local_args.get("range") in (None, "", "24h") or not local_args.get("range"))
        ):
            cov = res.get("coverage") or {}
            last_s = cov.get("data_last_at")
            if last_s:
                try:
                    last = datetime.fromisoformat(str(last_s).replace("Z", "+00:00"))
                    if last.tzinfo is None:
                        last = last.replace(tzinfo=timezone.utc)
                    span = timedelta(hours=24)
                    t1 = last + timedelta(seconds=1)
                    t0 = t1 - span
                    kw2 = dict(kw, range_=None, t_from=t0.isoformat(), t_to=t1.isoformat())
                    res2 = (
                        q.search_by_username(adb, system, user=user, **kw2) if user
                        else q.search_executions(adb, system, **kw2)
                    )
                    if isinstance(res2, dict) and int(res2.get("total") or 0) > 0:
                        note = (
                            f"Son 24 saatte veri yok; en son veriler {last_s} itibarıyla — "
                            f"aynı uzunlukta o dönemi gösteriyorum ({t0.isoformat()} – {t1.isoformat()})."
                        )
                        res2 = dict(res2)
                        res2["window_fallback"] = True
                        res2["window_note"] = note
                        res2["summary"] = note + " " + (res2.get("summary") or "")
                        return res2
                except (TypeError, ValueError) as _e:
                    note_error("tools_automic.run", _e)
        # Açık kullanıcı dönemi boş kaldıysa: kapsamı belirt (yeniden sorgulama yok)
        if (
            isinstance(res, dict)
            and int(res.get("total") or 0) == 0
            and res.get("data_status") == "NO_DATA_IN_RANGE"
            and local_args.get("from")
        ):
            cov = res.get("coverage") or {}
            last_s = cov.get("data_last_at")
            if last_s:
                res = dict(res)
                res["summary"] = (
                    (res.get("summary") or "")
                    + f" Bu döneme ait veri yok; en son veri {last_s}."
                )
        return res
    return _with_system(args, ctx, run)


def _execution(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.automic import queries as q

    aspect = (args.get("aspect") or "detail").lower()
    _RUN_ID_MISSING = {
        "ok": False,
        "error": "Çalışma kimliği (RunID) bulunamadı; önce ilgili işin son hatalı çalışmasını arayın.",
        "code": "run_id_missing",
    }

    def run(adb, system):
        run_id = _int(args.get("run_id"))
        if not run_id:
            obj = (args.get("object_name") or "").strip()
            kw = dict(status_class="failed", sort="end_desc", limit=1)
            sr = q.search_executions(adb, system, object_name=obj or None, **kw)
            items = sr.get("items") or []
            if items and items[0].get("run_id") is not None:
                run_id = int(items[0]["run_id"])
            if not run_id:
                return _RUN_ID_MISSING
        client = _int(args.get("client")) or None   # model sık sık client=0 ("belirtilmedi") gönderir
        if client is None:
            rec = q.find_run(adb, system, run_id)
            client = int(rec["client"]) if rec else None
        uid = (ctx or {}).get("user_id")
        allow = args.get("allow_live")
        if allow is not None:
            allow = bool(allow)
        if aspect == "detail":
            return q.execution_detail(adb, system, client, run_id, allow_live=allow, user_id=uid)
        if client is None:
            return {"ok": False, "error": f"RunID {run_id} modül DB'de yok; client numarası belirtin."}
        if aspect == "children":
            return q.execution_children(
                adb, system, client, run_id, allow_live=allow, user_id=uid)
        if aspect == "restarts":
            return q.execution_restarts(adb, system, client, run_id)
        if aspect == "reports":
            return q.list_reports(adb, system, client, run_id, allow_live=allow, user_id=uid)
        if aspect == "report":
            # from_source geriye uyum → allow_live=True talebi (politika yine zorunlu)
            if allow is None and args.get("from_source") is True:
                allow = True
            return q.get_report(
                adb, system, client, run_id, args.get("report_type") or "REP",
                prefer="source" if allow is True else "auto",
                allow_live=allow, user_id=uid)
        return {"ok": False, "error": f"Geçersiz aspect: {aspect}"}
    return _with_system(args, ctx, run)


def _active(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.automic import queries as q

    def run(adb, system):
        res = q.active_executions(
            adb, system, object_name=args.get("object_name"), agent=args.get("agent"), user=args.get("user"),
            clients=[_int(args["client"])] if _int(args.get("client")) else None,
            min_running_sec=args.get("min_running_sec"), limit=_int(args.get("limit")) or 50,
        )
        from app.services.automic.service import system_status
        st = system_status(adb, system)
        res["source_lag_sec"] = st.get("source_lag_sec")
        as_of = res.get("as_of") or st.get("active_snapshot_at") or st.get("last_success_at")
        res["note"] = (
            f"Son toplama: {as_of}. EH anlık görüntüsü (modül DB); canlı EH okuma yok."
            if as_of else "EH anlık görüntüsü henüz yok — collector sonrası dolar."
        )
        return res
    return _with_system(args, ctx, run)


def _object(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.automic import objects as obj_svc
    from app.services.automic import queries as q

    name = (args.get("name") or "").strip()
    if not name:
        return {"ok": False, "error": "name gerekli"}
    aspect = (args.get("aspect") or "recent_runs").lower()

    def run(adb, system):
        client = _int(args.get("client"))
        if aspect in ("header", "recent_runs"):
            return q.object_summary(adb, system, name, client=client, days=_int(args.get("days")) or 30)
        uid = (ctx or {}).get("user_id")
        allow = args.get("allow_live")
        if allow is not None:
            allow = bool(allow)
        if aspect == "script":
            cl = client if client is not None else (system.clients or [None])[0]
            if cl is None:
                return {"ok": False, "error": "client gerekli"}
            return obj_svc.fetch_and_store_script(
                adb, system, int(cl), name, force=bool(args.get("force")),
                allow_live=allow, user_id=uid)
        if aspect == "versions":
            cl = client if client is not None else (system.clients or [None])[0]
            if cl is None:
                return {"ok": False, "error": "client gerekli"}
            return {"ok": True, "client": cl, "object_name": name,
                    "versions": obj_svc.list_versions(adb, system, int(cl), name),
                    "data_source": "module_db"}
        if aspect == "diff":
            cl = client if client is not None else (system.clients or [None])[0]
            if cl is None:
                return {"ok": False, "error": "client gerekli"}
            return obj_svc.script_diff(adb, system, int(cl), name,
                                      a=_int(args.get("version_a")), b=_int(args.get("version_b")))
        if aspect == "usage":
            cl = client if client is not None else (system.clients or [None])[0]
            if cl is None:
                return {"ok": False, "error": "client gerekli"}
            return obj_svc.object_usage(adb, system, int(cl), name, depth=_int(args.get("depth")) or 1)
        return {"ok": False, "error": f"Geçersiz aspect: {aspect}"}
    return _with_system(args, ctx, run)


def _agent(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.automic import infra as infra_svc
    from app.services.automic import queries as q
    from app.services.automic.infra_status import status_label_tr

    name = (args.get("name") or args.get("agent") or "").strip()
    status_filter = (args.get("status") or "").strip().lower() or None
    if not name and not status_filter and not args.get("list_disconnected"):
        return {"ok": False, "error": "name (agent) veya status/list_disconnected gerekli"}

    def run(adb, system):
        if args.get("list_disconnected") or status_filter in ("disconnected", "kopuk", "unknown", "bilinmiyor", "connected", "bağlı"):
            st = {
                "kopuk": "disconnected", "bağlı": "connected", "bilinmiyor": "unknown",
            }.get(status_filter or "", status_filter)
            if args.get("list_disconnected"):
                st = "disconnected"
            res = infra_svc.list_agents(adb, system, status=st)
            # bilinmiyor asla kopuk/bağlı diye anlatılmasın — ham status döner
            for a in res.get("agents") or []:
                a["status_label"] = status_label_tr(a.get("status") or "")
            res["note"] = (res.get("note") or "") + (
                f" Son kontrol: {res.get('synced_at') or 'yok'}."
            )
            return res
        detail = infra_svc.agent_detail(adb, system, name)
        # aktivite özeti de ekle
        if detail.get("ok"):
            act = q.agent_summary(
                adb, system, name, range_=args.get("range") or "7d",
                clients=[_int(args["client"])] if _int(args.get("client")) else None,
            )
            detail["activity"] = act
            st = (detail.get("status") or {})
            detail["chat_note"] = (
                f"Durum: {st.get('label')} (kural: {st.get('rule_label')}). "
                f"Son kontrol: {st.get('synced_at') or 'yok'}. "
                "Durum anlık değil."
            )
        return detail
    return _with_system(args, ctx, run)


def _infrastructure(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.automic import infra as infra_svc
    from app.services.automic.teams import resolve_team_for_object

    aspect = (args.get("aspect") or "overview").lower()

    def run(adb, system):
        if aspect in ("overview", "engines"):
            if aspect == "engines":
                res = infra_svc.list_engine_servers(adb, system)
            else:
                res = infra_svc.infrastructure_overview(adb, system)
                # overview içindeki engines özetini yüzeye çıkar
                eng = res.get("engines") if isinstance(res.get("engines"), dict) else {}
                if eng.get("summary_tr"):
                    res["summary_tr"] = eng["summary_tr"]
                    res["active_pwp"] = eng.get("active_pwp")
            res["chat_note"] = (
                (res.get("summary_tr") + " " if res.get("summary_tr") else "")
                + f"Son kontrol: {res.get('synced_at') or 'yok'}. Durum anlık değil. "
                "Sistem adı sunucu değildir."
            )
            return res
        if aspect == "engine_server":
            ip = (args.get("ip") or "").strip()
            # ip yoksa / PWP sorusu → tüm engine özeti (aktif PWP burada)
            if not ip:
                res = infra_svc.list_engine_servers(adb, system)
                res["chat_note"] = (
                    (res.get("summary_tr") + " " if res.get("summary_tr") else "")
                    + f"Son kontrol: {res.get('synced_at') or 'yok'}. "
                    "PWP için active_pwp alanına bak; sistem adı sunucu değildir."
                )
                return res
            return infra_svc.engine_server_detail(adb, system, ip)
        if aspect == "agents":
            return infra_svc.list_agents(
                adb, system, status=args.get("status"), platform=args.get("platform"),
                team=args.get("team"), group=args.get("group"),
            )
        if aspect == "team":
            name = (args.get("object_name") or "").strip()
            client = _int(args.get("client")) or (system.clients or [None])[0]
            if not name or client is None:
                return {"ok": False, "error": "object_name ve client gerekli"}
            t = resolve_team_for_object(adb, system.id, int(client), name)
            return {"ok": True, "object_name": name, "client": client, **t}
        if aspect == "object_host":
            # Job hangi agent/sunucuda — sistem adı (DEV-FAKE) asla "sunucu" değil
            from app.services.automic import queries as q
            from app.services.automic.clock import apply_window
            name = (args.get("object_name") or "").strip()
            if not name:
                return {"ok": False, "error": "object_name gerekli"}
            aargs = apply_window(dict(args))
            hosts = q.object_run_hosts(
                adb, system, name,
                range_=aargs.get("range") or "7d",
                from_=aargs.get("from"), to_=aargs.get("to"),
                clients=[_int(args["client"])] if _int(args.get("client")) else None,
            )
            hosts["system"] = system.name
            hosts["system_is_not_server"] = True
            hosts["note"] = (
                "Sistem adı (ör. ortam etiketi) sunucu değildir. "
                "Durum anlık değil; son kontrol zamanına aittir. "
                + (hosts.get("note") or "")
            )
            return hosts

        return {"ok": False, "error": f"Geçersiz aspect: {aspect}"}
    return _with_system(args, ctx, run)


def _history(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.automic import queries as q

    from app.services.automic.clock import apply_window, forced_window
    from app.services.automic.followup_context import apply_forced_filters
    args = _sanitize_search_args(apply_forced_filters(apply_window(args)))
    tid = (args.get("template_id") or "").strip()
    params = _sanitize_search_args(dict(args.get("params") or {}))
    if forced_window():   # kodla çözülmüş açık tarih: params içindeki zaman alanlarının üstüne yazar
        params.pop("range", None)
        params["from"], params["to"] = args["from"], args["to"]
    for k in ("range", "from", "to", "object_name", "client", "limit", "bucket", "object_type",
              "status_class", "agent", "user"):
        if args.get(k) not in (None, "") and k not in params:
            params[k] = args[k]
    return _with_system(args, ctx, lambda adb, system: q.run_history(adb, system, tid, params))


def _status(db: Session, args: Dict[str, Any], ctx: Dict[str, Any]) -> Dict[str, Any]:
    from app.services.automic.collector import collector_runs_summary
    from app.services.automic.retention import quota_status
    from app.services.automic.service import capability_summary, list_systems, system_status

    def run(adb, system):
        return {
            "ok": True, **system_status(adb, system),
            "runs_24h": collector_runs_summary(adb, system.id, 24),
            "quota": quota_status(adb),
            "capability": capability_summary(system.capability),
            "systems": [s.name for s in list_systems(adb)],
        }
    return _with_system(args, ctx, run)


_TEMPLATES_DESC = (
    "top_failed_objects, slowest_objects, failure_trend, duration_trend (object_name zorunlu), volume, "
    "error_signatures, agent_activity, duration_outliers, month_end_compare, hourly_heatmap, "
    "expected_tonight (geçmiş gece örüntüsü; forecast değil), user_activity (kullanıcı adına göre çalışma/hata/aktif), "
    "period_compare ('bu hafta/geçen hafta', 'bu ay/geçen ay', 'öncekine göre ne değişti': range=7d/30d; iki dönemi "
    "KAPSAM bilgisiyle ve sunucuda hesaplanmış farklarla döndürür — karşılaştırma için bunu kullan, iki ayrı sorguyla elle hesaplama)"
)

AUTOMIC_TOOLS: Dict[str, Tool] = {
    "automic_search_executions": Tool(
        name="automic_search_executions",
        description=(
            "AUTOMIC (UC4) çalışma arama (READ-ONLY, modül DB). Biten job/workflow çalışmalarını filtreler: "
            "nesne adı (wildcard * ?), tip (JOBS/JOBP/…), sınıf (failed/ok/cancelled/other), durum kodu, "
            "agent, kullanıcı ADI (userID değil; 'ahmet', 'BATCH/OPS', 'ops*' — yalnız modül DB'de çözülmüş ad; "
            "kaynak canlı kullanıcı araması yok), klasör, client, zaman aralığı, "
            "minimum süre, parent_run_id. "
            "'dün gece hata alan job'lar', 'X job'ı en son ne zaman çalıştı', 'şu agent'ta hatalılar' sorularında."
        ),
        parameters={"type": "object", "properties": {
            **_SYSTEM, **_CLIENT, **_RANGE,
            "object_name": {"type": "string"}, "object_type": {"type": "string"},
            "status_class": {"type": "string", "enum": ["failed", "ok", "cancelled", "other"]},
            "status_code": {"type": "integer"}, "agent": {"type": "string"},
            "user": {"type": "string", "description": "Kullanıcı ADI (OH_Name); kısmi ad/joker olur. ID verme."},
            "folder": {"type": "string"}, "min_duration_sec": {"type": "number"},
            "parent_run_id": {"type": "integer"},
            "sort": {"type": "string", "enum": ["end_desc", "end_asc", "duration_desc", "duration_asc"]},
            "limit": {"type": "integer", "description": "En fazla 500, varsayılan 25"},
            "offset": {"type": "integer"},
        }, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_search, direct_label="Automic çalışma arama", domains=frozenset({"automic"}),
    ),
    "automic_execution": Tool(
        name="automic_execution",
        description=(
            "AUTOMIC tek çalışma (RunID) ayrıntısı (READ-ONLY). aspect: detail (durum, süreler, agent, kullanıcı "
            "(AH_USR_Idnr→OH_Name), kuyruk, klasör (OFS), run_time_sec (AH_RunTime), ert_sec (AH_ERT), dönüş kodu, "
            "hata imzası, parent, restart, 30 g istatistik) | children (workflow alt adımları, hatalı adım) | "
            "restarts | reports (rapor listesi) | report (report_type ile içerik; hatalıysa önce maskeli DB "
            "kırpıntısı, değilse kaynaktan satır sınırlı/maskeli)."
        ),
        parameters={"type": "object", "properties": {
            **_SYSTEM, **_CLIENT,
            "run_id": {"type": "integer"},
            "aspect": {"type": "string", "enum": ["detail", "children", "restarts", "reports", "report"]},
            "report_type": {"type": "string", "description": "REP, ACT, LOG, POST … (aspect=report)"},
            "allow_live": {
                "type": "boolean",
                "description": (
                    "true=canlı kaynak talebi (yalnız politika izin verirse); "
                    "false=asla canlı; yok=politika varsayılanı. "
                    "false otomatik sayılmaz."
                ),
            },
        }, "required": ["run_id"]},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_execution, direct_label="Automic çalışma detayı", domains=frozenset({"automic"}),
    ),
    "automic_active": Tool(
        name="automic_active",
        description=(
            "AUTOMIC şu an çalışan/bekleyen işler (READ-ONLY, son EH anlık görüntüsü). Nesne/agent/client filtresi, "
            "min_running_sec; p95 süreyi aşanlar 'over_p95'. Resmi EH alanları: state (running/waiting/blocked), "
            "user, queue, platform, ert_sec (EH_Ert), ert_end_time (EH_ERTEnd, tahmini bitiş), over_ert, "
            "signals (EH_Signal: TCP/MRT aşıldı, SRT altında). 'şu an ne çalışıyor', 'uzun süren işler', "
            "'tahmini bitiş' sorularında."
        ),
        parameters={"type": "object", "properties": {
            **_SYSTEM, **_CLIENT,
            "object_name": {"type": "string"}, "agent": {"type": "string"},
            "user": {"type": "string", "description": "Kullanıcı ADI (kısmi/joker)"},
            "min_running_sec": {"type": "number"}, "limit": {"type": "integer"},
        }, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_active, direct_label="Automic aktif işler", domains=frozenset({"automic"}),
    ),
    "automic_object": Tool(
        name="automic_object",
        description=(
            "AUTOMIC nesne (job/workflow) (READ-ONLY). aspect: recent_runs|header (istatistik, imza, agent), "
            "script (maskeli OT metni + sürüm), versions, diff, usage (JPP bağımlılık grafiği; yetenek varsa)."
        ),
        parameters={"type": "object", "properties": {
            **_SYSTEM, **_CLIENT,
            "name": {"type": "string", "description": "Nesne adı (tam veya wildcard)"},
            "aspect": {"type": "string", "enum": ["recent_runs", "header", "script", "versions", "diff", "usage"]},
            "days": {"type": "integer", "description": "Dönem (varsayılan 30)"},
            "version_a": {"type": "integer"}, "version_b": {"type": "integer"},
            "depth": {"type": "integer", "description": "usage derinlik (varsayılan 1)"},
            "force": {"type": "boolean", "description": "script için kaynaktan yenile talebi (politika gerekir)"},
            "allow_live": {
                "type": "boolean",
                "description": "true=canlı talep; false=modül DB; yok=politika varsayılanı",
            },
        }, "required": ["name"]},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_object, direct_label="Automic nesne özeti", domains=frozenset({"automic"}),
    ),
    "automic_agent": Tool(
        name="automic_agent",
        description=(
            "AUTOMIC agent durumu ve aktivitesi (READ-ONLY). name ile detay: üç değerli durum "
            "(bağlı/kopuk/bilinmiyor), hostname/IP, yaşam sinyali, son kontrol zamanı, iş yükü. "
            "list_disconnected=true veya status=disconnected/unknown/connected ile liste. "
            "Bilinmiyor asla kopuk/bağlı diye anlatılmaz; son kontrol zamanı zorunlu."
        ),
        parameters={"type": "object", "properties": {
            **_SYSTEM, **_CLIENT, **_RANGE,
            "name": {"type": "string", "description": "Agent adı"},
            "agent": {"type": "string", "description": "name ile aynı"},
            "status": {"type": "string", "description": "connected|disconnected|unknown"},
            "list_disconnected": {"type": "boolean", "description": "Kopuk agent listesi"},
        }, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_agent, direct_label="Automic agent", domains=frozenset({"automic"}),
    ),
    "automic_infrastructure": Tool(
        name="automic_infrastructure",
        description=(
            "AUTOMIC altyapı (READ-ONLY, modül DB): Engine process'leri (PWP/WP/CP/JWP/JCP/REST), "
            "agent listesi, job→sunucu/agent eşlemesi, ekip eşlemesi. aspect: overview|engines|"
            "engine_server|agents|object_host|team. "
            "'Engine hangi sunucularda', 'kaç CP ayakta', 'PWP nerede', 'JOBS.X hangi sunucuda', "
            "'Finans ekibinin işleri / ekip kim' sorularında. Hesaplama araçta; durum anlık değil."
        ),
        parameters={"type": "object", "properties": {
            **_SYSTEM, **_CLIENT,
            "aspect": {"type": "string", "enum": [
                "overview", "engines", "engine_server", "agents", "object_host", "team"]},
            "ip": {"type": "string"}, "object_name": {"type": "string"},
            "status": {"type": "string"}, "platform": {"type": "string"},
            "team": {"type": "string"}, "group": {"type": "string"},
        }, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_infrastructure, direct_label="Automic altyapı", domains=frozenset({"automic"}),
    ),
    "automic_history": Tool(
        name="automic_history",
        description=(
            "AUTOMIC parametreli analiz şablonları (READ-ONLY, serbest SQL yok). template_id: "
            f"{_TEMPLATES_DESC}. Parametreler: range, from, to, object_name, client, limit, bucket (hour/day), "
            "object_type. Trend, en çok hata veren, en yavaş, hata imzası, agent, süre sapması, ay sonu soruları."
        ),
        parameters={"type": "object", "properties": {
            **_SYSTEM, **_CLIENT, **_RANGE,
            "template_id": {"type": "string", "enum": [
                "top_failed_objects", "slowest_objects", "failure_trend", "duration_trend", "volume",
                "error_signatures", "agent_activity", "duration_outliers", "month_end_compare",
                "hourly_heatmap", "expected_tonight", "user_activity", "period_compare"]},
            "object_name": {"type": "string"}, "object_type": {"type": "string"},
            "limit": {"type": "integer"}, "bucket": {"type": "string", "enum": ["hour", "day"]},
        }, "required": ["template_id"]},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_history, direct_label="Automic analiz", domains=frozenset({"automic"}),
    ),
    "automic_status": Tool(
        name="automic_status",
        description=(
            "AUTOMIC entegrasyon durumu (READ-ONLY): kaynak gecikmesi, son/sonraki toplama, collector hatası, "
            "devre kesici, kota kullanımı, yetenek matrisi özeti. Veri güncelliği sorulduğunda veya veri "
            "eksik/eski göründüğünde kullan."
        ),
        parameters={"type": "object", "properties": {**_SYSTEM}, "required": []},
        risk_level=RiskLevel.READ_ONLY, build_command=lambda a: "",
        direct_handler=_status, direct_label="Automic durum", domains=frozenset({"automic"}),
    ),
}
