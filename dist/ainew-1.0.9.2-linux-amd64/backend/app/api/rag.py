"""
RAG API: Runbook, Incident ve Metrik açıklamaları ingest + durum.
PDF runbook ingest dahil.
"""
import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.services.rag_service import (
    ingest_runbook_append,
    ingest_incidents_from_db,
    ingest_events_from_db,
    ingest_metric_descriptions,
    get_rag_context_for_message,
)
from app.services.rag_store import (
    count_collection,
    list_runbook_documents,
    delete_runbook_by_title,
    COLLECTION_RUNBOOK,
    COLLECTION_INCIDENTS,
    COLLECTION_METRICS,
)
from app.data.default_metric_descriptions import DEFAULT_METRIC_DESCRIPTIONS

logger = logging.getLogger(__name__)

router = APIRouter()


class RunbookIngestRequest(BaseModel):
    title: str
    content: str


class MetricDescriptionItem(BaseModel):
    name: str
    description: str


class MetricDescriptionsSeedRequest(BaseModel):
    items: Optional[List[dict]] = None  # None ise varsayılan liste kullanılır


@router.post("/runbook/ingest")
async def rag_runbook_ingest(body: RunbookIngestRequest):
    """Runbook dokümanı ekle (chunk'lanıp embed'lenir)."""
    try:
        n = await ingest_runbook_append(title=body.title, content=body.content)
        return {"success": True, "chunks_added": n}
    except Exception as e:
        logger.exception("Runbook ingest failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/runbook/documents")
async def rag_runbook_list_documents():
    """Runbook'a eklenen dokümanları listele (başlık ve chunk sayısı)."""
    try:
        docs = list_runbook_documents()
        return {"success": True, "documents": docs}
    except Exception as e:
        logger.exception("Runbook list failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/runbook/documents")
async def rag_runbook_delete_document(title: str):
    """Runbook'dan başlığa göre doküman sil (tüm chunk'ları). Query: ?title=..."""
    if not title or not str(title).strip():
        raise HTTPException(status_code=400, detail="title gerekli (?title=...)")
    try:
        t = str(title).strip()
        deleted = delete_runbook_by_title(t)
        return {"success": True, "deleted_chunks": deleted, "title": t}
    except Exception as e:
        logger.exception("Runbook delete failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/runbook/ingest-pdf")
async def rag_runbook_ingest_pdf(
    file: UploadFile = File(..., description="PDF dosyası"),
    title: Optional[str] = Form(None, description="Başlık (boşsa dosya adı kullanılır)"),
):
    """PDF dosyasından metin çıkarıp runbook RAG'e ekler (chunk + embed)."""
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Sadece .pdf dosyası yükleyebilirsiniz.")
    try:
        from app.services.pdf_parser import extract_text_from_pdf

        pdf_bytes = await file.read()
        if len(pdf_bytes) > 50 * 1024 * 1024:  # 50 MB
            raise HTTPException(status_code=400, detail="PDF en fazla 50 MB olabilir.")
        text = extract_text_from_pdf(pdf_bytes)
        if not text or not text.strip():
            raise HTTPException(
                status_code=400,
                detail="PDF'den metin çıkarılamadı (boş veya korumalı olabilir).",
            )
        doc_title = (title or file.filename or "PDF").strip()
        if doc_title.endswith(".pdf"):
            doc_title = doc_title[:-4]
        n = await ingest_runbook_append(title=doc_title, content=text)
        return {"success": True, "chunks_added": n, "title": doc_title, "pages_extracted": True}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("PDF runbook ingest failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/incidents/reindex")
async def rag_incidents_reindex(db: Session = Depends(get_db)):
    """Incidents tablosunu RAG incidents collection'a indexle (mevcut içerik silinir)."""
    try:
        n = await ingest_incidents_from_db(db)
        return {"success": True, "chunks_added": n}
    except Exception as e:
        logger.exception("Incidents reindex failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/events/reindex")
async def rag_events_reindex(db: Session = Depends(get_db)):
    """SystemEvent kayıtlarını RAG incidents collection'a ekle."""
    try:
        n = await ingest_events_from_db(db)
        return {"success": True, "chunks_added": n}
    except Exception as e:
        logger.exception("Events reindex failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/metrics/seed")
async def rag_metrics_seed(body: Optional[MetricDescriptionsSeedRequest] = None):
    """Metrik açıklamalarını RAG'e ekle. body boş veya items verilmezse varsayılan liste kullanılır."""
    try:
        items = None
        if body and body.items:
            items = body.items
        if not items:
            items = DEFAULT_METRIC_DESCRIPTIONS
        n = await ingest_metric_descriptions(items)
        return {"success": True, "chunks_added": n}
    except Exception as e:
        logger.exception("Metrics seed failed")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def rag_status():
    """RAG collection'lardaki kayıt sayıları."""
    try:
        return {
            "runbook": count_collection(COLLECTION_RUNBOOK),
            "incidents": count_collection(COLLECTION_INCIDENTS),
            "metrics": count_collection(COLLECTION_METRICS),
        }
    except Exception as e:
        logger.warning(f"RAG status error: {e}")
        return {"runbook": 0, "incidents": 0, "metrics": 0}


@router.get("/preview")
async def rag_preview(message: str = "CPU kullanımı nedir?"):
    """Test: Verilen mesaj için RAG context'ini döndür (Chat'ta kullanılan yapı)."""
    try:
        ctx = await get_rag_context_for_message(message)
        return {
            "message": message,
            "runbook": ctx["runbook"][:500] + "..." if len(ctx["runbook"]) > 500 else ctx["runbook"],
            "incidents": ctx["incidents"][:500] + "..." if len(ctx["incidents"]) > 500 else ctx["incidents"],
            "metrics": ctx["metrics"][:500] + "..." if len(ctx["metrics"]) > 500 else ctx["metrics"],
        }
    except Exception as e:
        logger.exception("RAG preview failed")
        raise HTTPException(status_code=500, detail=str(e))
