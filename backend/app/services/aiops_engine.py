"""
AIOps Engine — Kapalı döngü otomasyon çekirdeği.

Akış:
  Metrikler (TimescaleDB)
    → Anomali tespiti (anomaly_detector)
    → SystemEvent olarak kalıcılaştırma (dedup + auto-resolve)
    → Kritik event → otomatik Incident (incident_auto)
    → Otomatik AI RCA (Ollama)
    → RAG hafıza (periyodik reindex, background_tasks)

Bu modül arka plan thread'lerinden çağrılır; tüm DB işlemleri verilen
Session üzerinden yapılır, AI çağrıları senkron `requests` ile yapılır.
"""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

import requests
from sqlalchemy.orm import Session

from app.core.config import settings, get_active_model
from app.models.event import SystemEvent, Incident
from app.services.incident_auto import auto_create_or_link_incident
from app.services.baseline_engine import apply_baseline_filter

logger = logging.getLogger(__name__)

# Aynı metrik anomalisi için yeni event açmadan önce bakılacak aktif pencere.
ACTIVE_EVENT_WINDOW_HOURS = 6
# last_seen bu süreden eski olan metrik anomalileri "düzeldi" sayılır.
AUTO_RESOLVE_AFTER_HOURS = 2
# Tek RCA turunda analiz edilecek maksimum incident sayısı (Ollama yükünü sınırla).
MAX_RCA_PER_RUN = 3
METRIC_ANOMALY_TYPE = "metric_anomaly"


# ── 1) Anomali → SystemEvent ────────────────────────────────────────────────
def persist_anomalies_as_events(db: Session, anomalies: List[Dict[str, Any]]) -> Dict[str, int]:
    """
    Anomali dict listesini SystemEvent kayıtlarına dönüştürür.

    Dedup: Aynı (server_id, metric) için son ACTIVE_EVENT_WINDOW_HOURS içinde
    çözülmemiş bir event varsa yeni açmaz; last_seen + raw_data günceller.

    Kritik yeni event'ler için auto_create_or_link_incident çağrılır.
    """
    created = 0
    updated = 0
    incidents_touched = set()
    now = datetime.utcnow()
    window_start = now - timedelta(hours=ACTIVE_EVENT_WINDOW_HOURS)

    for a in anomalies:
        try:
            server_id = a.get("server_id")
            metric = a.get("metric_name")
            severity = a.get("severity", "warning")
            if severity not in ("warning", "critical"):
                continue

            # Aynı metrik için aktif (çözülmemiş) event var mı?
            existing = (
                db.query(SystemEvent)
                .filter(
                    SystemEvent.server_id == server_id,
                    SystemEvent.event_type == METRIC_ANOMALY_TYPE,
                    SystemEvent.resolved == False,  # noqa: E712
                    SystemEvent.created_at >= window_start,
                )
                .order_by(SystemEvent.created_at.desc())
                .all()
            )
            match = None
            for ev in existing:
                if (ev.raw_data or {}).get("metric") == metric:
                    match = ev
                    break

            raw = {
                "metric": metric,
                "current_value": a.get("current_value"),
                "mean_value": a.get("mean_value"),
                "stdev_value": a.get("stdev_value"),
                "z_score": a.get("z_score"),
                "is_iqr_outlier": a.get("is_iqr_outlier"),
                "threshold_warning": a.get("threshold_warning"),
                "threshold_critical": a.get("threshold_critical"),
                "detected_at": a.get("detected_at"),
            }

            # ── Baseline filtresi uygula ────────────────────────────────────
            baseline_result = apply_baseline_filter(
                db=db,
                server_id=server_id,
                metric_name=metric,
                severity=severity,
                event_type=METRIC_ANOMALY_TYPE,
                current_value=a.get("current_value"),
            )
            if baseline_result["suppress"]:
                logger.debug(
                    f"[AIOps] Baseline SUPPRESS: server={server_id} metric={metric} "
                    f"reason={baseline_result['downgrade_reason']}"
                )
                continue
            effective_severity = baseline_result["effective_severity"]
            if effective_severity != severity:
                logger.info(
                    f"[AIOps] Baseline DOWNGRADE: {severity}→{effective_severity} "
                    f"server={server_id} metric={metric} reason={baseline_result['downgrade_reason']}"
                )
            severity = effective_severity
            raw["baseline_downgrade"] = baseline_result.get("downgrade_reason")
            raw["recurrence_days"] = baseline_result.get("recurrence", {}).get("recurrence_days", 0)
            # ────────────────────────────────────────────────────────────────

            if match:
                # Mevcut anomaliyi güncelle (tekrar event açma)
                match.last_seen = now
                match.raw_data = raw
                match.occurrence_count = (match.occurrence_count or 1) + 1
                # Severity yükseldiyse (warning → critical) güncelle ve incident'a yansıt
                escalated = (match.severity != "critical" and severity == "critical")
                if escalated:
                    match.severity = "critical"
                    match.title = a.get("message", match.title)
                # Severity düştüyse de güncelle
                elif baseline_result["downgrade_reason"] and severity != match.severity:
                    match.severity = severity
                db.commit()
                updated += 1
                if escalated:
                    inc_id = auto_create_or_link_incident(db, match)
                    if inc_id:
                        incidents_touched.add(inc_id)
                continue

            # Yeni event oluştur
            event = SystemEvent(
                server_id=server_id,
                event_type=METRIC_ANOMALY_TYPE,
                severity=severity,
                source="prometheus",
                title=a.get("message") or f"{metric} anomalisi",
                description=_build_event_description(a),
                raw_data=raw,
                last_seen=now,
                occurrence_count=1,
            )
            db.add(event)
            db.commit()
            db.refresh(event)
            created += 1

            if severity == "critical":
                inc_id = auto_create_or_link_incident(db, event)
                if inc_id:
                    incidents_touched.add(inc_id)

        except Exception as e:
            db.rollback()
            logger.error(f"[AIOps] Anomali kalıcılaştırma hatası ({a.get('metric_name')}): {e}")

    # Düzelen (recovered) anomalileri otomatik çöz
    resolved = _auto_resolve_recovered(db, now)

    if created or updated or resolved:
        logger.warning(
            f"[AIOps] Metrik anomali: {created} yeni, {updated} güncel, "
            f"{resolved} düzeldi, {len(incidents_touched)} incident etkilendi"
        )

    return {
        "created": created,
        "updated": updated,
        "resolved": resolved,
        "incidents": len(incidents_touched),
    }


def _build_event_description(a: Dict[str, Any]) -> str:
    lines = [
        f"Metrik: {a.get('metric_name')}",
        f"Mevcut değer: {a.get('current_value')}",
    ]
    if a.get("mean_value") is not None:
        lines.append(f"Normal ortalama: {a.get('mean_value')}")
    if a.get("z_score") is not None:
        lines.append(f"Z-score: {a.get('z_score')} (normalden sapma)")
    if a.get("is_iqr_outlier"):
        lines.append("IQR aykırı değer: Evet")
    if a.get("threshold_critical") is not None:
        lines.append(f"Kritik eşik: {a.get('threshold_critical')}")
    elif a.get("threshold_warning") is not None:
        lines.append(f"Uyarı eşiği: {a.get('threshold_warning')}")
    lines.append(f"Tespit: {a.get('detected_at')}")
    return "\n".join(lines)


def _auto_resolve_recovered(db: Session, now: datetime) -> int:
    """last_seen güncellenmemiş (artık tespit edilmeyen) metrik anomalilerini çöz."""
    stale_before = now - timedelta(hours=AUTO_RESOLVE_AFTER_HOURS)
    stale = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.event_type == METRIC_ANOMALY_TYPE,
            SystemEvent.resolved == False,  # noqa: E712
            SystemEvent.last_seen < stale_before,
        )
        .all()
    )
    count = 0
    for ev in stale:
        ev.resolved = True
        ev.resolved_at = now
        count += 1
    if count:
        db.commit()
    return count


# ── 2) Otomatik AI RCA ──────────────────────────────────────────────────────
def run_rca_sync(db: Session, incident: Incident) -> bool:
    """
    Bir incident için Ollama ile senkron RCA çalıştırır.
    Başarılı olursa incident.rca_result + root_cause set edip True döner.
    """
    event_details = []
    if incident.related_events:
        events = db.query(SystemEvent).filter(SystemEvent.id.in_(incident.related_events)).all()
        for e in events:
            event_details.append(f"- [{e.severity}] {e.title}: {(e.description or 'N/A')[:300]}")

    server_details = []
    if incident.affected_servers:
        from app.models.server import Server
        servers = db.query(Server).filter(Server.id.in_(incident.affected_servers)).all()
        for s in servers:
            server_details.append(
                f"- {s.name} ({s.ip_address}): {s.status}, OS: {s.os_type}, "
                f"CPU: {s.cpu_cores} core, RAM: {s.memory_gb}GB"
            )

    prompt = f"""Sen bir AIOps Root Cause Analysis (Kök Neden Analizi) uzmanısın.
Aşağıdaki OTOMATİK tespit edilen incident için kök neden analizi yap. TÜRKÇE yanıt ver, kısa ve net ol.

INCIDENT: {incident.title}
Açıklama: {incident.description or 'Yok'}
Önem Derecesi: {incident.severity}

İLGİLİ EVENTLER:
{chr(10).join(event_details) if event_details else 'Henüz ilgili event yok'}

ETKİLENEN SUNUCULAR:
{chr(10).join(server_details) if server_details else 'Bilgi yok'}

Lütfen şu formatta analiz yap:
1. OLASI KÖK NEDEN: En olası kök nedeni belirt
2. ETKİ ANALİZİ: Hangi sistemler/servisler etkileniyor
3. ÇÖZÜM ÖNERİLERİ: Adım adım, çalıştırılabilir komutlarla
4. ÖNLEME: Gelecekte nasıl önlenebilir"""

    model = get_active_model(db)
    try:
        resp = requests.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=180,
        )
        if resp.status_code != 200:
            logger.warning(f"[AIOps] RCA HTTP {resp.status_code} (incident #{incident.id})")
            return False
        rca_text = resp.json().get("response", "").strip()
        if not rca_text:
            return False
        incident.rca_result = {
            "analysis": rca_text,
            "model": model,
            "analyzed_at": datetime.utcnow().isoformat(),
            "auto": True,
        }
        incident.root_cause = rca_text[:500]
        db.commit()
        logger.info(f"[AIOps] Otomatik RCA tamamlandı: incident #{incident.id} ({model})")
        try:
            from app.services.audit import record_audit
            record_audit(db, category="rca", action="rca.auto", actor="system",
                         target_type="incident", target_id=incident.id,
                         summary=f"Otomatik RCA: {incident.title}"[:200],
                         detail={"model": model})
        except Exception:
            pass
        return True
    except requests.exceptions.ConnectionError:
        logger.warning("[AIOps] Ollama'ya bağlanılamadı, RCA atlandı")
        return False
    except Exception as e:
        db.rollback()
        logger.error(f"[AIOps] RCA hatası (incident #{incident.id}): {e}")
        return False


def auto_rca_pending_incidents(db: Session) -> int:
    """
    Otomatik açılmış, henüz RCA'sı olmayan açık incident'lar için RCA çalıştırır.
    Tur başına en fazla MAX_RCA_PER_RUN incident işler.
    """
    candidates = (
        db.query(Incident)
        .filter(
            Incident.status.in_(["open", "investigating"]),
            Incident.source.ilike("auto_%"),
        )
        .order_by(Incident.created_at.desc())
        .limit(20)
        .all()
    )
    # RCA'sı olmayanları seç
    pending = [c for c in candidates if not (c.rca_result and c.rca_result.get("analysis"))]
    done = 0
    for inc in pending[:MAX_RCA_PER_RUN]:
        if run_rca_sync(db, inc):
            done += 1
    return done


# ── 3) Tek seferlik tam tur (background_tasks çağırır) ──────────────────────
def _run_aiops_cycle_legacy(db: Session, anomalies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """LangGraph kullanılamazsa devreye giren doğrudan zincir (yedek)."""
    persist_result = persist_anomalies_as_events(db, anomalies)
    rca_done = 0
    try:
        rca_done = auto_rca_pending_incidents(db)
    except Exception as e:
        logger.error(f"[AIOps] Auto-RCA turu hatası: {e}")
    return {**persist_result, "rca_done": rca_done}


def run_aiops_cycle(db: Session, anomalies: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Anomali listesini işle + bekleyen RCA'ları çalıştır. Özet döner.

    Orkestrasyon LangGraph (aiops_graph) üzerinden yürütülür; graph yüklenemezse
    eski doğrudan zincire (legacy) düşer.
    """
    try:
        from app.services.aiops_graph import run_aiops_graph
        return run_aiops_graph(db, anomalies)
    except Exception as e:
        logger.error(f"[AIOps] LangGraph turu başarısız, legacy zincire düşülüyor: {e}")
        return _run_aiops_cycle_legacy(db, anomalies)
