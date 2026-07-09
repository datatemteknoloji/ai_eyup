"""
Chat Q&A Cache servisi.
- Soruları normalize edip DB'de arar
- Benzerlik >= 0.80 ise cache hit döner
- Her başarılı yanıt cache'e kaydedilir
"""
import re
import hashlib
import logging
from typing import Optional
from difflib import SequenceMatcher
from sqlalchemy.orm import Session
from app.models.chat_cache import ChatQACache

logger = logging.getLogger(__name__)

# Cache'e kaydedilmeyecek genel konuşma kalıpları
_SKIP_PATTERNS = [
    r'^(merhaba|selam|nasılsın|teşekkür|tamam|peki|evet|hayır|ok|hi|hello|thanks)',
]

def _normalize(text: str) -> str:
    """Soruyu normalize et: küçük harf, gereksiz boşluk/noktalama kaldır."""
    t = text.lower().strip()
    t = re.sub(r'\s+', ' ', t)
    t = re.sub(r'[?!.,;:]+', '', t)
    return t

def _should_cache(question: str) -> bool:
    q = _normalize(question)
    if len(q) < 15:
        return False
    for pat in _SKIP_PATTERNS:
        if re.match(pat, q):
            return False
    return True

def _similarity(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()

def _context_key(server_ids: list) -> str:
    if not server_ids:
        return "global"
    ids = sorted(server_ids)
    return hashlib.md5(str(ids).encode()).hexdigest()[:12]

def get_cached_answer(db: Session, question: str, server_ids: list = None) -> Optional[dict]:
    """
    Benzer soru var mı diye bakar.
    Döndürür: {"answer": str, "cached": True, "hit_count": int} veya None
    """
    if not _should_cache(question):
        return None
    try:
        norm_q = _normalize(question)
        ctx_key = _context_key(server_ids or [])
        # Önce aynı bağlamda, sonra global ara
        candidates = (
            db.query(ChatQACache)
            .filter(ChatQACache.context_key.in_([ctx_key, "global"]))
            .order_by(ChatQACache.hit_count.desc())
            .limit(50)
            .all()
        )
        best_score = 0.0
        best = None
        for row in candidates:
            score = _similarity(norm_q, _normalize(row.question))
            if score > best_score:
                best_score = score
                best = row

        if best and best_score >= 0.80:
            logger.info(f"Cache HIT (score={best_score:.2f}): {question[:60]}")
            best.hit_count += 1
            from datetime import datetime, timezone
            best.last_used = datetime.now(timezone.utc)
            db.commit()
            return {"answer": best.answer, "cached": True, "hit_count": best.hit_count}
    except Exception as e:
        logger.debug(f"Cache lookup failed: {e}")
    return None

# Yanıtın gerçek veriye dayalı olmadığını gösteren kalıplar — cache'e kaydedilmez
_BAD_ANSWER_PATTERNS = [
    "bu bilgi mevcut değil",
    "bilgi mevcut degil",
    "ssh yapamam",
    "dogrudan baglanamam",
    "elde edilmediği için",
    "kesin olarak söyleyemeyiz",
    "belirlenemedi",
    "veri tabanındaki bilgileri",
    "bana sağlanan veri",
]


def save_to_cache(db: Session, question: str, answer: str, server_ids: list = None) -> None:
    """Başarılı yanıtı cache'e kaydet — kalitesiz yanıtları kaydetme."""
    if not _should_cache(question) or not answer or len(answer) < 30:
        return
    # Yanlış/hallucination yanıtları cache'e alma
    answer_lower = answer.lower()
    for bad in _BAD_ANSWER_PATTERNS:
        if bad in answer_lower:
            logger.debug(f"Cache SKIP (bad answer pattern '{bad}'): {question[:50]}")
            return
    try:
        norm_q = _normalize(question)
        ctx_key = _context_key(server_ids or [])
        # Aynı soru zaten var mı?
        existing = db.query(ChatQACache).filter(
            ChatQACache.context_key == ctx_key
        ).limit(200).all()
        for row in existing:
            if _similarity(norm_q, _normalize(row.question)) >= 0.92:
                # Güncelle
                row.answer = answer
                row.hit_count += 1
                db.commit()
                return
        entry = ChatQACache(
            question=norm_q,
            answer=answer,
            context_key=ctx_key,
        )
        db.add(entry)
        db.commit()
        logger.debug(f"Cache SAVE: {question[:60]}")
    except Exception as e:
        logger.debug(f"Cache save failed: {e}")
        db.rollback()
