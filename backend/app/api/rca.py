"""
RCA API — Karşılaştırmalı analiz ve AWR parse/analiz endpoint'leri.

Endpoint'ler:
  POST /rca/compare-window    — İki zaman dilimi karşılaştırması + LLM
  POST /rca/awr-analyze       — AWR raporu parse + LLM performans analizi
  POST /rca/awr-parse-only    — AWR parse (LLM yok, sadece yapılandırılmış JSON)
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.config import get_active_model

logger = logging.getLogger(__name__)
router = APIRouter()


# ── Şemalar ──────────────────────────────────────────────────────────────────

class CompareWindowRequest(BaseModel):
    # Pencere A
    server_id_a: Optional[int] = None
    since_a: datetime
    until_a: datetime
    label_a: str = "Pencere A (önceki)"

    # Pencere B
    server_id_b: Optional[int] = None
    since_b: datetime
    until_b: datetime
    label_b: str = "Pencere B (sonraki)"

    # Filtreler
    event_types: Optional[List[str]] = None  # None → tümü
    context: str = ""                        # AWR özeti veya ek bağlam
    model: Optional[str] = None


class AWRAnalyzeRequest(BaseModel):
    """AWR içeriği text olarak gönderildiğinde kullanılır."""
    content: str
    filename: str = "report.txt"
    model: Optional[str] = None
    compare_with_awr: Optional[str] = None   # İkinci AWR içeriği (karşılaştırma için)
    compare_filename: str = "baseline.txt"


# ── Endpoint'ler ─────────────────────────────────────────────────────────────

@router.post("/compare-window")
async def compare_window(
    req: CompareWindowRequest,
    db: Session = Depends(get_db),
):
    """
    İki zaman dilimindeki log/event'leri karşılaştırır ve LLM analizi yapar.

    Kullanım senaryoları:
    - Sorun öncesi vs. sonrası (aynı sunucu, farklı zaman)
    - Sunucu A vs. Sunucu B (farklı sunucu, aynı zaman)
    - Haftalık baseline karşılaştırması

    Opsiyonel: context alanına AWR özeti eklenebilir.
    """
    from app.services.compare_windows import compare_windows

    if req.since_a >= req.until_a:
        raise HTTPException(status_code=400, detail="since_a, until_a'dan önce olmalı")
    if req.since_b >= req.until_b:
        raise HTTPException(status_code=400, detail="since_b, until_b'den önce olmalı")

    duration_a_h = (req.until_a - req.since_a).total_seconds() / 3600
    duration_b_h = (req.until_b - req.since_b).total_seconds() / 3600
    if duration_a_h > 168 or duration_b_h > 168:
        raise HTTPException(status_code=400, detail="Pencere maksimum 7 gün olabilir")

    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: compare_windows(
            db=db,
            server_id_a=req.server_id_a,
            since_a=req.since_a,
            until_a=req.until_a,
            server_id_b=req.server_id_b,
            since_b=req.since_b,
            until_b=req.until_b,
            label_a=req.label_a,
            label_b=req.label_b,
            event_types=req.event_types,
            context=req.context,
            model=req.model,
        ),
    )

    logger.info(
        f"[RCA/compare-window] A={req.label_a} B={req.label_b} "
        f"model={result.get('model')}"
    )
    return result


@router.post("/awr-analyze")
async def awr_analyze(
    req: AWRAnalyzeRequest,
    db: Session = Depends(get_db),
):
    """
    AWR raporunu parse eder ve LLM ile performans analizi yapar.

    - content: AWR HTML veya text içeriği
    - compare_with_awr: Opsiyonel baseline AWR (karşılaştırma için)
    """
    from app.services.awr_parser import parse_awr
    import requests as req_lib
    from app.services import llm_gateway

    if not req.content or len(req.content) < 100:
        raise HTTPException(status_code=400, detail="AWR içeriği çok kısa veya boş")

    # Parse
    report = parse_awr(req.content, req.filename)
    summary_text = report.to_llm_summary()

    # Karşılaştırma AWR varsa
    compare_summary = ""
    compare_report_dict = None
    if req.compare_with_awr:
        baseline = parse_awr(req.compare_with_awr, req.compare_filename)
        compare_report_dict = baseline.to_dict()
        compare_summary = "\n\n=== BASELINE AWR ===\n" + baseline.to_llm_summary()

    # LLM analizi
    active_model = req.model or get_active_model(db)
    prompt = _build_awr_analysis_prompt(summary_text, compare_summary)

    llm_analysis = {}
    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: llm_gateway.generate_sync(model=active_model, prompt=prompt, timeout=180)
        )
        if not data.get("error"):
            import json
            raw = (data.get("response") or "").strip()
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    llm_analysis = json.loads(raw[start:end])
                except Exception:
                    llm_analysis = {"summary": raw[:800], "confidence": "low"}
            else:
                llm_analysis = {"summary": raw[:800], "confidence": "low"}
        else:
            llm_analysis = {"summary": f"AI hatası: {data['error']}", "confidence": "low"}
    except req_lib.exceptions.ConnectionError:
        llm_analysis = {"summary": "LLM bağlantı hatası", "confidence": "low"}
    except req_lib.exceptions.Timeout:
        llm_analysis = {"summary": "LLM zaman aşımı", "confidence": "low"}
    except Exception as e:
        llm_analysis = {"summary": f"Hata: {str(e)[:200]}", "confidence": "low"}

    result = {
        "report": report.to_dict(),
        "llm_summary_sent": summary_text,
        "llm_analysis": llm_analysis,
        "model": active_model,
        "analyzed_at": datetime.utcnow().isoformat(),
    }
    if compare_report_dict is not None:
        result["baseline_report"] = compare_report_dict

    logger.info(
        f"[RCA/awr-analyze] DB={report.db_name} snap={report.snap_begin}→{report.snap_end} "
        f"model={active_model}"
    )
    return result


@router.post("/awr-analyze-upload")
async def awr_analyze_upload(
    file: UploadFile = File(...),
    baseline_file: Optional[UploadFile] = File(None),
    model: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """
    AWR raporunu dosya upload ile alır (multipart/form-data).
    HTML veya text format desteklenir. Max 10 MB.
    """
    MAX_SIZE = 10 * 1024 * 1024

    content_bytes = await file.read()
    if len(content_bytes) > MAX_SIZE:
        raise HTTPException(status_code=413, detail="Dosya 10 MB limitini aşıyor")

    try:
        content = content_bytes.decode("utf-8", errors="replace")
    except Exception:
        raise HTTPException(status_code=400, detail="Dosya UTF-8 ile okunamadı")

    compare_content = None
    compare_filename = "baseline.txt"
    if baseline_file:
        baseline_bytes = await baseline_file.read()
        if len(baseline_bytes) <= MAX_SIZE:
            compare_content = baseline_bytes.decode("utf-8", errors="replace")
            compare_filename = baseline_file.filename or compare_filename

    from app.services.awr_parser import parse_awr
    import json as json_lib
    from app.services import llm_gateway

    report = parse_awr(content, file.filename or "upload.html")
    summary_text = report.to_llm_summary()

    compare_report_dict = None
    compare_summary = ""
    if compare_content:
        baseline = parse_awr(compare_content, compare_filename)
        compare_report_dict = baseline.to_dict()
        compare_summary = "\n\n=== BASELINE AWR ===\n" + baseline.to_llm_summary()

    active_model = model or get_active_model(db)
    prompt = _build_awr_analysis_prompt(summary_text, compare_summary)

    llm_analysis = {}
    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: llm_gateway.generate_sync(model=active_model, prompt=prompt, timeout=180)
        )
        if not data.get("error"):
            raw = (data.get("response") or "").strip()
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    llm_analysis = json_lib.loads(raw[start:end])
                except Exception:
                    llm_analysis = {"summary": raw[:800], "confidence": "low"}
            else:
                llm_analysis = {"summary": raw[:800], "confidence": "low"}
        else:
            llm_analysis = {"summary": f"AI hatası: {data['error']}", "confidence": "low"}
    except Exception as e:
        llm_analysis = {"summary": f"Hata: {str(e)[:200]}", "confidence": "low"}

    result = {
        "report": report.to_dict(),
        "llm_analysis": llm_analysis,
        "model": active_model,
        "analyzed_at": datetime.utcnow().isoformat(),
    }
    if compare_report_dict:
        result["baseline_report"] = compare_report_dict

    return result


@router.post("/awr-parse-only")
async def awr_parse_only(
    req: AWRAnalyzeRequest,
    db: Session = Depends(get_db),
):
    """AWR parse eder, LLM'e göndermez. Hızlı yapılandırılmış JSON döner."""
    from app.services.awr_parser import parse_awr

    if not req.content or len(req.content) < 100:
        raise HTTPException(status_code=400, detail="AWR içeriği çok kısa veya boş")

    report = parse_awr(req.content, req.filename)
    return {
        "report": report.to_dict(),
        "llm_summary": report.to_llm_summary(),
        "parsed_at": datetime.utcnow().isoformat(),
    }


# ── Hızlı Event RCA ──────────────────────────────────────────────────────────

class QuickRCARequest(BaseModel):
    event_id: Optional[int] = None
    event_ids: Optional[List[int]] = None   # Storm için: birden fazla event
    server_id: Optional[int] = None
    metric: Optional[str] = None
    is_storm: bool = False
    model: Optional[str] = None


@router.post("/quick-analyze")
async def quick_analyze(req: QuickRCARequest, db: Session = Depends(get_db)):
    """
    Tek event, server+metric, veya storm (çoklu event) için hızlı LLM kök neden analizi.
    OpsCenter'dan inline çağrılır.
    """
    import json as json_lib
    from app.models.event import SystemEvent
    from app.models.server import Server
    from datetime import timedelta

    # Tüm event ID'leri birleştir
    all_event_ids: List[int] = []
    if req.event_ids:
        all_event_ids = req.event_ids[:30]  # max 30 event
    elif req.event_id:
        all_event_ids = [req.event_id]

    # Event'leri yükle
    seed_events: List[SystemEvent] = []
    if all_event_ids:
        seed_events = db.query(SystemEvent).filter(
            SystemEvent.id.in_(all_event_ids)
        ).all()

    # Metrik ve server bilgisi
    metric = req.metric
    if not metric and seed_events:
        metric = (seed_events[0].raw_data or {}).get("metric") or seed_events[0].event_type

    # Storm veya tek sunucu?
    is_storm = req.is_storm or len({e.server_id for e in seed_events if e.server_id}) > 1

    # Etkilenen sunucuları topla
    server_ids = list({e.server_id for e in seed_events if e.server_id})
    if req.server_id and req.server_id not in server_ids:
        server_ids.append(req.server_id)

    # Sunucu bilgileri
    servers_map: dict = {}
    for s in db.query(Server).filter(Server.id.in_(server_ids)).all():
        servers_map[s.id] = s

    # Son 6 saatteki ilgili eventleri her sunucu için topla
    since = datetime.utcnow() - timedelta(hours=6)
    related_events: List[SystemEvent] = (
        db.query(SystemEvent)
        .filter(
            SystemEvent.server_id.in_(server_ids),
            SystemEvent.last_seen >= since,
        )
        .order_by(SystemEvent.last_seen.desc())
        .limit(50)
        .all()
    )

    # Her sunucu için özet satır oluştur
    by_server: dict = {}
    for ev in related_events:
        sid = ev.server_id
        if sid not in by_server:
            by_server[sid] = []
        by_server[sid].append(ev)

    # Prompt bağlamı
    if is_storm:
        server_sections = []
        for sid, evs in by_server.items():
            s = servers_map.get(sid)
            sname = s.name if s else f"server#{sid}"
            ip = s.ip_address if s else "?"
            tier = getattr(s, "tier", "unknown") or "unknown" if s else "unknown"
            lines = []
            for ev in evs[:5]:
                raw = ev.raw_data or {}
                m = raw.get("metric") or ev.event_type
                val = raw.get("current_value")
                val_str = f" %{val:.0f}" if val is not None else ""
                lines.append(f"    [{ev.severity.upper()}] {m}{val_str} — {ev.title[:80]} ({ev.occurrence_count or 1}x)")
            server_sections.append(
                f"  {sname} ({ip}, {tier}):\n" + "\n".join(lines)
            )

        context_block = "\n".join(server_sections) or "  (veri yok)"
        prompt = f"""Sen bir Linux/altyapı uzmanısın. Aynı anda {len(server_ids)} farklı sunucuyu etkileyen ALARM FIRTINASI için kök neden analizi yap.

Metrik: {metric}
Etkilenen sunucular ({len(server_ids)}):
{context_block}

Bu alarm fırtınası büyük ihtimalle ortak bir altyapı sorununa işaret ediyor (ağ, depolama, NTP, shared storage, hypervisor vb.).

Yalnızca şu JSON formatında yanıt ver:
{{
  "root_cause": "Ortak kök neden — 1-2 cümle, teknik ve net",
  "likely_cause": "En olası ortak sebep (paylaşılan altyapı unsuru)",
  "impact": "Etkilenen servisler ve sistemdeki genel etki",
  "actions": [
    "Hemen yap: ...",
    "Kontrol et: ..."
  ],
  "affected_summary": "Hangi tier/tip sunucular etkilendi özeti",
  "severity_assessment": "critical|high|medium|low",
  "confidence": "high|medium|low"
}}"""
    else:
        # Tek sunucu analizi
        server = servers_map.get(server_ids[0]) if server_ids else None
        server_name = server.name if server else f"server_id={server_ids[0] if server_ids else '?'}"
        tier = getattr(server, "tier", "unknown") or "unknown" if server else "unknown"
        ip = server.ip_address if server else "?"

        event_lines = []
        for ev in (related_events[:15]):
            raw = ev.raw_data or {}
            m = raw.get("metric") or ev.event_type
            val = raw.get("current_value")
            val_str = f" %{val:.0f}" if val is not None else ""
            event_lines.append(
                f"  [{ev.severity.upper()}] {m}{val_str} — {ev.title[:80]} "
                f"({ev.occurrence_count or 1}x, {ev.last_seen.strftime('%H:%M') if ev.last_seen else '?'})"
            )
        ctx = "\n".join(event_lines) or "  (event verisi yok)"

        prompt = f"""Sen bir Linux/altyapı uzmanısın. Aşağıdaki alarm için KISA ve NET bir kök neden analizi yap.

Sunucu: {server_name} (IP: {ip}, Tier: {tier})
Metrik: {metric}

Son 6 saatteki alarmlar:
{ctx}

Yalnızca şu JSON formatında yanıt ver:
{{
  "root_cause": "Kök neden — 1-2 cümle, teknik ve net",
  "likely_cause": "En olası sebep",
  "impact": "Sistemdeki etkisi",
  "actions": [
    "Hemen yap: ...",
    "Kontrol et: ..."
  ],
  "severity_assessment": "critical|high|medium|low",
  "confidence": "high|medium|low"
}}"""

    import requests as req_lib
    from app.services import llm_gateway
    active_model = req.model or get_active_model(db)
    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: llm_gateway.generate_sync(model=active_model, prompt=prompt, timeout=60)
        )
        if not data.get("error"):
            raw_text = (data.get("response") or "").strip()
            start = raw_text.find("{")
            end = raw_text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    analysis = json_lib.loads(raw_text[start:end])
                except Exception:
                    analysis = {"root_cause": raw_text[:600], "confidence": "low"}
            else:
                analysis = {"root_cause": raw_text[:600], "confidence": "low"}
        else:
            analysis = {"root_cause": f"AI yanıt vermedi: {data['error']}", "confidence": "low"}
    except req_lib.exceptions.ConnectionError:
        analysis = {"root_cause": "LLM bağlantı hatası — AI servisi çalışmıyor olabilir", "confidence": "low"}
    except req_lib.exceptions.Timeout:
        analysis = {"root_cause": "AI yanıt süresi aşıldı (60s)", "confidence": "low"}

    display_server = (
        f"{len(server_ids)} sunucu (fırtına)" if is_storm
        else (servers_map[server_ids[0]].name if server_ids and server_ids[0] in servers_map else "?")
    )
    return {
        "server": display_server,
        "metric": metric,
        "event_count": len(related_events),
        "is_storm": is_storm,
        "server_count": len(server_ids),
        "analysis": analysis,
        "model": active_model,
        "analyzed_at": datetime.utcnow().isoformat(),
    }


# ── Yardımcı ─────────────────────────────────────────────────────────────────

def _build_awr_analysis_prompt(summary: str, compare_summary: str = "") -> str:
    return f"""Sen bir Oracle DBA ve performans uzmanısın.
Aşağıdaki AWR raporu özetini analiz et ve TÜRKÇE performans değerlendirmesi yap.
{compare_summary}
=== AWR RAPORU ===
{summary}

Lütfen yalnızca aşağıdaki JSON formatında yanıt ver:
{{
  "summary": "Genel performans değerlendirmesi (2-4 cümle)",
  "bottlenecks": [
    "darboğaz 1 — kanıt ve etki",
    "darboğaz 2"
  ],
  "top_sql_findings": [
    "problematik SQL ve önerilen aksiyon"
  ],
  "wait_event_analysis": [
    "önemli wait event yorumu"
  ],
  "recommendations": [
    "öncelikli öneri 1",
    "öneri 2"
  ],
  "baseline_comparison": "Baseline AWR ile karşılaştırma özeti (varsa, yoksa boş string)",
  "severity": "critical|high|medium|low",
  "confidence": "high|medium|low"
}}"""
