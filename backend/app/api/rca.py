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
    from app.core.config import settings

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
        resp = req_lib.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json={"model": active_model, "prompt": prompt, "stream": False},
            timeout=180,
        )
        if resp.status_code == 200:
            import json
            raw = resp.json().get("response", "").strip()
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
            llm_analysis = {"summary": f"AI HTTP {resp.status_code}", "confidence": "low"}
    except req_lib.exceptions.ConnectionError:
        llm_analysis = {"summary": "Ollama bağlantı hatası", "confidence": "low"}
    except req_lib.exceptions.Timeout:
        llm_analysis = {"summary": "Ollama zaman aşımı", "confidence": "low"}
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
    import requests as req_lib
    import json as json_lib
    from app.core.config import settings

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
        resp = req_lib.post(
            f"{settings.OLLAMA_URL}/api/generate",
            json={"model": active_model, "prompt": prompt, "stream": False},
            timeout=180,
        )
        if resp.status_code == 200:
            raw = resp.json().get("response", "").strip()
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
            llm_analysis = {"summary": f"AI HTTP {resp.status_code}", "confidence": "low"}
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
