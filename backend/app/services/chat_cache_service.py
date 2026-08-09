"""
Chat Q&A Cache servisi.
- Platform-scoped context_key (linux:/windows:/unified:/virt:/…)
- TTL (24s → hit ile uzar); süresi dolan / rejected kayıtlar hit olmaz
- Feedback (up/down/correction) ile güçlendirme veya red
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from typing import List, Optional, Sequence

from sqlalchemy.orm import Session

from app.models.chat_cache import ChatQACache

logger = logging.getLogger(__name__)

_SKIP_PATTERNS = [
    r"^(merhaba|selam|nasılsın|teşekkür|tamam|peki|evet|hayır|ok|hi|hello|thanks)",
]

# Plan: varsayılan 24 saat; sık kullanılanlar daha uzun hatırlanır
_BASE_TTL = timedelta(hours=24)
_WARM_TTL = timedelta(days=3)       # hit_count >= 3
_HOT_TTL = timedelta(days=7)        # hit_count >= 10
_WARM_HIT = 3
_HOT_HIT = 10

_VALID_PLATFORMS = frozenset({
    "linux", "windows", "unified", "virt", "openshift", "exadata",
})

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
    "ssh bağlantısı sağlanamadı", "ssh baglantisi saglanamadi",
    "ssh bağlantısı sağlanamadığı", "ssh baglantisi saglanamadigi",
    "ssh bağlantısı kurulamadı", "ssh baglantisi kurulamadi",
    "ssh bağlantısı başarısız", "ssh baglantisi basarisiz",
    "veri alınamadı", "veri alinamadi",
    "veri toplanamadı", "veri toplanamadi",
    "veri toplanmadığı", "veri toplanmadigi",
    "veri sağlanamadı", "veri saglanamadi",
    "okuyamıyoruz", "okuyamiyoruz",
    "sağlayamıyorum", "saglayamiyorum",
    "göremiyorum", "goremiyorum",
    "erişim yok", "erisim yok",
    "zaman aşımı", "zaman asimi",
    "bağlanılamadı", "baglanilamadi",
    "bilgi alınamadı", "bilgi alinamadi",
    "winrm",
]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[?!.,;:]+", "", t)
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


def _normalize_platform(platform: Optional[str]) -> str:
    p = (platform or "linux").strip().lower()
    if p in _VALID_PLATFORMS:
        return p
    return "linux"


def _ids_hash(server_ids: Optional[Sequence[int]]) -> str:
    if not server_ids:
        return "global"
    ids = sorted(int(x) for x in server_ids)
    return hashlib.md5(str(ids).encode()).hexdigest()[:12]


def make_context_key(platform: Optional[str], server_ids: Optional[Sequence[int]] = None) -> str:
    """Örn. linux:global, windows:a1b2c3d4e5f6, unified:global."""
    return f"{_normalize_platform(platform)}:{_ids_hash(server_ids)}"


def _ttl_for_hits(hit_count: int) -> timedelta:
    if hit_count >= _HOT_HIT:
        return _HOT_TTL
    if hit_count >= _WARM_HIT:
        return _WARM_TTL
    return _BASE_TTL


def _set_expiry(row: ChatQACache, *, hit_count: Optional[int] = None) -> None:
    hc = int(hit_count if hit_count is not None else (row.hit_count or 0))
    row.expires_at = _now() + _ttl_for_hits(hc)


def _is_alive(row: ChatQACache) -> bool:
    if getattr(row, "rejected", False):
        return False
    exp = getattr(row, "expires_at", None)
    if exp is None:
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > _now()


def _candidate_keys(platform: str, server_ids: Optional[Sequence[int]]) -> List[str]:
    """Aynı platformda spesifik + platform:global. Çapraz platform yok."""
    plat = _normalize_platform(platform)
    keys = [make_context_key(plat, server_ids)]
    g = f"{plat}:global"
    if g not in keys:
        keys.append(g)
    return keys


def get_cached_answer(
    db: Session,
    question: str,
    server_ids: list = None,
    *,
    platform: str = "linux",
) -> Optional[dict]:
    if not _should_cache(question):
        return None
    try:
        norm_q = _normalize(question)
        keys = _candidate_keys(platform, server_ids or [])
        candidates = (
            db.query(ChatQACache)
            .filter(ChatQACache.context_key.in_(keys))
            .order_by(ChatQACache.hit_count.desc())
            .limit(80)
            .all()
        )
        best_score = 0.0
        best = None
        for row in candidates:
            if getattr(row, "rejected", False):
                continue
            if not _is_alive(row):
                continue
            score = _similarity(norm_q, _normalize(row.question))
            if score > best_score:
                best_score = score
                best = row

        if best and best_score >= 0.80:
            logger.info("Cache HIT platform=%s score=%.2f: %s", platform, best_score, question[:60])
            best.hit_count = int(best.hit_count or 0) + 1
            best.last_used = _now()
            _set_expiry(best, hit_count=best.hit_count)
            db.commit()
            return {
                "answer": best.answer,
                "cached": True,
                "hit_count": best.hit_count,
                "cache_id": best.id,
                "platform": _normalize_platform(platform),
            }
    except Exception as e:
        logger.debug("Cache lookup failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
    return None


def purge_bad_cache_entries(db: Session) -> int:
    try:
        rows = db.query(ChatQACache).all()
        to_delete = [
            r for r in rows
            if any(bad in (r.answer or "").lower() for bad in _BAD_ANSWER_PATTERNS)
        ]
        for r in to_delete:
            db.delete(r)
        if to_delete:
            db.commit()
            logger.info("Chat cache temizliği: %s hatalı/eski yanıt silindi", len(to_delete))
        return len(to_delete)
    except Exception as e:
        logger.debug("Cache purge failed: %s", e)
        db.rollback()
        return 0


def purge_expired_cache_entries(db: Session) -> int:
    try:
        now = _now()
        n = (
            db.query(ChatQACache)
            .filter(ChatQACache.expires_at.isnot(None), ChatQACache.expires_at < now)
            .delete(synchronize_session=False)
        )
        if n:
            db.commit()
            logger.info("Chat cache TTL: %s süresi dolmuş kayıt silindi", n)
        return int(n or 0)
    except Exception as e:
        logger.debug("Cache TTL purge failed: %s", e)
        db.rollback()
        return 0


def save_to_cache(
    db: Session,
    question: str,
    answer: str,
    server_ids: list = None,
    *,
    platform: str = "linux",
) -> None:
    if not _should_cache(question) or not answer or len(answer) < 30:
        return
    answer_lower = answer.lower()
    for bad in _BAD_ANSWER_PATTERNS:
        if bad in answer_lower:
            logger.debug("Cache SKIP (bad pattern '%s'): %s", bad, question[:50])
            return
    try:
        norm_q = _normalize(question)
        ctx_key = make_context_key(platform, server_ids or [])
        existing = (
            db.query(ChatQACache)
            .filter(ChatQACache.context_key == ctx_key)
            .limit(200)
            .all()
        )
        for row in existing:
            if getattr(row, "rejected", False):
                continue
            if _similarity(norm_q, _normalize(row.question)) >= 0.92:
                row.answer = answer
                row.hit_count = int(row.hit_count or 0) + 1
                row.last_used = _now()
                row.rejected = False
                _set_expiry(row, hit_count=row.hit_count)
                db.commit()
                return
        entry = ChatQACache(
            question=norm_q,
            answer=answer,
            context_key=ctx_key,
            hit_count=0,
            rejected=False,
        )
        _set_expiry(entry, hit_count=0)
        db.add(entry)
        db.commit()
        logger.debug("Cache SAVE platform=%s: %s", platform, question[:60])
    except Exception as e:
        logger.debug("Cache save failed: %s", e)
        db.rollback()


def invalidate_context(
    db: Session,
    *,
    platform: Optional[str] = None,
    server_ids: Optional[Sequence[int]] = None,
    all_for_platform: bool = False,
) -> int:
    """Stale SSH/cevapları düşürmek için context_key sil."""
    try:
        q = db.query(ChatQACache)
        if all_for_platform and platform:
            prefix = f"{_normalize_platform(platform)}:"
            rows = q.filter(ChatQACache.context_key.like(f"{prefix}%")).all()
        elif platform is not None:
            keys = _candidate_keys(platform, server_ids)
            rows = q.filter(ChatQACache.context_key.in_(keys)).all()
        elif server_ids:
            # Tüm platformlarda aynı sunucu hash'i
            h = _ids_hash(server_ids)
            rows = q.filter(ChatQACache.context_key.like(f"%:{h}")).all()
        else:
            return 0
        n = len(rows)
        for r in rows:
            db.delete(r)
        if n:
            db.commit()
            logger.info("Chat cache invalidate: %s kayıt silindi", n)
        return n
    except Exception as e:
        logger.debug("Cache invalidate failed: %s", e)
        db.rollback()
        return 0


def apply_feedback(
    db: Session,
    *,
    platform: str,
    question: str,
    answer: Optional[str] = None,
    server_ids: Optional[Sequence[int]] = None,
    vote: str,
    correction_text: Optional[str] = None,
) -> dict:
    """
    vote=up → eşleşen kaydı güçlendir / yoksa kaydet
    vote=down → rejected + sil (bir daha hit olmasın)
    correction_text → düzeltilmiş cevabı upsert (yüksek öncelik)
    """
    vote = (vote or "").strip().lower()
    if vote not in ("up", "down"):
        raise ValueError("vote up|down olmalı")
    plat = _normalize_platform(platform)
    norm_q = _normalize(question or "")
    if not norm_q:
        raise ValueError("question gerekli")

    keys = _candidate_keys(plat, server_ids or [])
    rows = (
        db.query(ChatQACache)
        .filter(ChatQACache.context_key.in_(keys))
        .order_by(ChatQACache.hit_count.desc())
        .limit(80)
        .all()
    )
    matched = []
    for row in rows:
        if _similarity(norm_q, _normalize(row.question)) >= 0.80:
            matched.append(row)

    if vote == "down":
        n = 0
        for row in matched:
            row.rejected = True
            db.delete(row)
            n += 1
        db.commit()
        # Virt Redis cache
        if plat == "virt":
            try:
                from app.services import qa_cache as hv_qa
                hv_qa.invalidate_all()
            except Exception:
                pass
        return {"ok": True, "action": "rejected", "affected": n}

    # up veya correction
    final_answer = (correction_text or answer or "").strip()
    if not final_answer:
        raise ValueError("answer veya correction_text gerekli")

    if matched:
        row = matched[0]
        row.answer = final_answer
        row.question = norm_q
        row.rejected = False
        row.hit_count = int(row.hit_count or 0) + (5 if correction_text else 2)
        row.last_used = _now()
        _set_expiry(row, hit_count=row.hit_count)
        # Diğer benzerleri reddet (tek doğru cevap)
        for other in matched[1:]:
            db.delete(other)
        db.commit()
        return {"ok": True, "action": "boosted", "cache_id": row.id, "hit_count": row.hit_count}

    ctx_key = make_context_key(plat, server_ids or [])
    entry = ChatQACache(
        question=norm_q,
        answer=final_answer,
        context_key=ctx_key,
        hit_count=5 if correction_text else 2,
        rejected=False,
    )
    _set_expiry(entry, hit_count=entry.hit_count)
    db.add(entry)
    db.commit()
    db.refresh(entry)
    return {"ok": True, "action": "saved", "cache_id": entry.id, "hit_count": entry.hit_count}
