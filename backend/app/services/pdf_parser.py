"""
PDF'den metin çıkarma - RAG runbook ingest için.
"""
import logging
from io import BytesIO
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)


def extract_pages_from_pdf(pdf_bytes: bytes, max_pages: Optional[int] = None) -> List[Tuple[int, str]]:
    """Sayfa numarası (1-based) + metin. Boş sayfalar atlanır."""
    if not pdf_bytes or len(pdf_bytes) < 100:
        return []
    try:
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(pdf_bytes))
        pages = reader.pages
        if max_pages is not None and max_pages > 0:
            pages = pages[:max_pages]
        out: List[Tuple[int, str]] = []
        for i, page in enumerate(pages):
            try:
                text = page.extract_text()
                if text and text.strip():
                    out.append((i + 1, text.strip()))
            except Exception as e:
                logger.debug(f"PDF sayfa {i + 1} atlandı: {e}")
        return out
    except Exception as e:
        logger.warning(f"PDF parse hatası: {e}")
        return []


def extract_text_from_pdf(pdf_bytes: bytes, max_pages: Optional[int] = None) -> str:
    """
    PDF byte içeriğinden metin çıkarır.
    max_pages: None ise tüm sayfalar, sayı verilirse ilk N sayfa.
    """
    parts = [t for _, t in extract_pages_from_pdf(pdf_bytes, max_pages=max_pages)]
    return "\n\n".join(parts) if parts else ""
