"""
Chat Q&A Cache servisi (Adım 9 — yeniden tasarım).

Eski tasarım (karakter oranı ≥ 0,80 «fuzzy» eşleşme, kullanıcı/RBAC anahtarsız, her cevap, HIT'te TTL uzatma)
farklı varlık / yön / zaman sorularına yanlış cevap dönebiliyordu (esx01↔esx02 0,97; çalışıyor↔çalışmıyor 0,98).
Yeni kurallar:
- **Tam eşleşme:** normalize edilmiş soru birebir aynı olmalı (benzerlik YOK).
- **Anahtar:** `platform:sunucu-hash:rbac-imzası` — izinli modül kümesi farklı kullanıcılar birbirinin kaydını görmez.
- **Yalnız kavramsal cevaplar** girer (nedir / ne demek / nasıl çalışır …): veri, sayım, durum, zaman-göreli,
  varlık adı içeren, araç/canlı veri kullanan, «veri yok», ret, hata, doğrulayıcı-değiştirilmiş cevaplar GİRMEZ.
- **Sabit TTL** (`chat_cache_ttl_sec`, varsayılan 24 sa); HIT süreyi uzatmaz.
- **Kapatma anahtarı:** `chat_cache_enabled`.
- Her karar INFO log + sayaç (`get_stats()`); sessiz yutma yok.
"""
from __future__ import annotations

import hashlib
import logging
import re
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import List, Optional, Sequence, Tuple

from sqlalchemy.orm import Session

from app.models.chat_cache import ChatQACache

logger = logging.getLogger(__name__)

DEFAULT_TTL_SEC = 24 * 3600

_SKIP_PATTERNS = [
    r"^(merhaba|selam|nasılsın|teşekkür|tamam|peki|evet|hayır|ok|hi|hello|thanks)",
]

_VALID_PLATFORMS = frozenset({
    "linux", "windows", "unified", "virt", "openshift", "exadata",
})

_BAD_ANSWER_PATTERNS = [
    "bu bilgi mevcut değil", "bilgi mevcut degil", "ssh yapamam", "dogrudan baglanamam",
    "elde edilmediği için", "kesin olarak söyleyemeyiz", "belirlenemedi", "veri tabanındaki bilgileri",
    "bana sağlanan veri", "ssh bağlantısı sağlanamadı", "ssh baglantisi saglanamadi",
    "ssh bağlantısı sağlanamadığı", "ssh baglantisi saglanamadigi", "ssh bağlantısı kurulamadı",
    "ssh baglantisi kurulamadi", "ssh bağlantısı başarısız", "ssh baglantisi basarisiz",
    "veri alınamadı", "veri alinamadi", "veri toplanamadı", "veri toplanamadi", "veri toplanmadığı",
    "veri toplanmadigi", "veri sağlanamadı", "veri saglanamadi", "okuyamıyoruz", "okuyamiyoruz",
    "sağlayamıyorum", "saglayamiyorum", "göremiyorum", "goremiyorum", "erişim yok", "erisim yok",
    "zaman aşımı", "zaman asimi", "bağlanılamadı", "baglanilamadi", "bilgi alınamadı", "bilgi alinamadi",
    "winrm",
]

# Ret / hata / «sorgulanmadı» / eylem reddi cevap işaretleri (Adım 8 sabit cümleleri dahil)
_NEVER_CACHE_ANSWER_MARKERS = [
    "(hata:", "(yanıt alınamadı", "salt-okunur asistanım", "salt okunur asistanım", "yapamam;",
    "bu kaynak bu turda sorgulanmadı", "kayıt bulunamadı", "bu bilgi mevcut", "bilinmiyor",
    "erişim yetkiniz", "yetkiniz yok", "[context kes", "remote_unavailable",
    "uzak dil modeli şu anda yanıt vermiyor", "permission denied", "i cannot", "i can't help",
]

# ── Soru sınıflandırma ──
# Kavramsal (genel bilgi) soru kalıpları — YALNIZ bunlar önbelleğe girebilir.
_CONCEPTUAL_RE = re.compile(
    r"(\bnedir\b|\bne demek\b|\bne anlama\b|\bne işe yarar\b|\bnasıl çalışır\b|\bneden olur\b|"
    r"\bfarkı? nedir\b|\bfark(ı|lar)\b|\bnasıl (yapılır|yapılandırılır|kurulur|giderilir|çözülür)\b|"
    r"\bwhat is\b|\bwhat are\b|\bwhat does\b.*\bmean\b|\bhow does\b.*\bwork\b|\bdifference between\b|\bexplain\b)",
    re.I,
)
# Veri / durum / zaman-göreli / ortama özgü işaretler — GÖRÜLÜRSE önbelleğe girmez.
_DATA_RE = re.compile(
    r"(\bkaç\b|\bkac\b|\bsayısı\b|\bsayisi\b|\blistele\b|\bliste\b|\bhangi\b|\ben (çok|az|fazla|yüksek|düşük)\b|"
    r"\btop ?\d+\b|\bşu an\b|\bşimdi\b|\banlık\b|\bbugün\b|\bdün\b|\byarın\b|\bbu (hafta|ay|yıl)\b|\bgeçen\b|"
    r"\bson \d+\b|\bson (bir|1)\b|\bsaat\b|\bdakika\b|\bgün önce\b|\bdurum\w*|"
    r"\bçalışıyor\b|\bçalışmıyor\b|\baçık mı\b|\bkapalı mı\b|\bvar mı\b|\byok mu\b|\bnerede\b|\bkim\b|"
    r"\bsahibi\b|\bkullanım(ı|da)?\b|\bdoluluk\b|\bkapasite\b|\byüzde\b|\boran(ı)?\b|\bbenim\b|\bbizim\b|"
    r"\bsunucum\b|\bsunucumuz\b|\bortam(ım|ımız|ımızda)?\b|\b(bu|şu|o) (sunucu|vm|host|cluster|node|pod|job)\w*|"
    r"\bhow many\b|\bcount\b|\blist\b|\bwhich\b|\bcurrent(ly)?\b|"
    r"\bnow\b|\btoday\b|\byesterday\b|\bstatus of\b|\busage\b|\bour\b|\bmy\b)",
    re.I,
)
# Varlık adı benzeri belirteçler: harf+rakam karışık, tire/alt çizgi/nokta ile birleşik, IP, FQDN, tırnaklı ad
_ENTITY_TOKEN_RE = re.compile(
    r"([a-zçğıöşü]+\d+[\w-]*|\d+[a-zçğıöşü]+[\w-]*|[\w]+[-_.][\w][\w.-]*|\b\d{1,3}(\.\d{1,3}){3}\b)",
    re.I,
)
_QUOTED_ENTITY_RE = re.compile(r"[\"“”'‘’][^\"“”'‘’]{3,}[\"“”'‘’]")

_stats: Counter = Counter()
_stats_lock = threading.Lock()


def _bump(key: str) -> None:
    with _stats_lock:
        _stats[key] += 1


def get_stats() -> dict:
    """Süreç içi sayaçlar: hit/miss/save/update/skip:<neden>/error."""
    with _stats_lock:
        return dict(_stats)


def reset_stats() -> None:
    with _stats_lock:
        _stats.clear()


# ── ayarlar ──
def cache_enabled() -> bool:
    try:
        from app.services import runtime_settings as rs
        return bool(rs.get_bool("chat_cache_enabled"))
    except Exception:
        return True


def cache_ttl() -> timedelta:
    try:
        from app.services import runtime_settings as rs
        return timedelta(seconds=max(60, int(rs.get_int("chat_cache_ttl_sec"))))
    except Exception:
        return timedelta(seconds=DEFAULT_TTL_SEC)


# ── yardımcılar ──
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize(text: str) -> str:
    t = (text or "").lower().strip()
    t = re.sub(r"\s+", " ", t)
    t = re.sub(r"[?!.,;:]+", "", t)
    return t


def _should_cache(question: str) -> bool:
    q = _normalize(question)
    if len(q) < 8:
        return False
    for pat in _SKIP_PATTERNS:
        if re.match(pat, q):
            return False
    return True


def _normalize_platform(platform: Optional[str]) -> str:
    p = (platform or "linux").strip().lower()
    return p if p in _VALID_PLATFORMS else "linux"


def _ids_hash(server_ids: Optional[Sequence[int]]) -> str:
    if not server_ids:
        return "global"
    ids = sorted(int(x) for x in server_ids)
    return hashlib.md5(str(ids).encode()).hexdigest()[:12]


def rbac_signature_for_modules(allowed) -> str:
    """İzinli modül kümesi imzası. None → kısıtsız (`all`); küme → sıralı sha1[:10] (boş küme dahil)."""
    if allowed is None:
        return "all"
    items = sorted(str(x) for x in allowed)
    return "m" + hashlib.sha1(",".join(items).encode()).hexdigest()[:10]


def rbac_signature(user, db: Session) -> str:
    """Kullanıcının sohbet modül yetkisinden imza (unified_chat ile AYNI kaynak: `_chat_allowed_modules`)."""
    try:
        from app.api.unified_chat import _chat_allowed_modules
        return rbac_signature_for_modules(_chat_allowed_modules(user, db))
    except Exception as e:  # imza hesaplanamazsa en kısıtlı imza (diğer kullanıcılarla paylaşılmaz)
        logger.warning("chat cache rbac imzası hesaplanamadı (%s) — kayıt kullanıcıya özel 'err'", e)
        return "err"


def make_context_key(platform: Optional[str], server_ids: Optional[Sequence[int]] = None, rbac_sig: str = "") -> str:
    """Örn. unified:global:all · linux:ab12cd34ef56:m1a2b3c4d5e. `rbac_sig` boşsa imzasız eski biçim (yalnız test/geri uyum)."""
    base = f"{_normalize_platform(platform)}:{_ids_hash(server_ids)}"
    return f"{base}:{rbac_sig}" if rbac_sig else base


def _is_alive(row: ChatQACache) -> bool:
    if getattr(row, "rejected", False):
        return False
    exp = getattr(row, "expires_at", None)
    if exp is None:
        return True
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    return exp > _now()


def classify_question(question: str) -> Tuple[bool, str]:
    """(girebilir mi, neden). Kavramsal kalıp ZORUNLU; veri/zaman/varlık işareti YASAK."""
    if not _should_cache(question):
        return False, "short_or_smalltalk"
    q = question or ""
    if _DATA_RE.search(q):
        return False, "data_or_time_question"
    if _ENTITY_TOKEN_RE.search(q) or _QUOTED_ENTITY_RE.search(q):
        return False, "entity_in_question"
    if not _CONCEPTUAL_RE.search(q):
        return False, "not_conceptual"
    return True, "conceptual"


def classify_answer(answer: str) -> Tuple[bool, str]:
    if not answer or len(answer) < 30:
        return False, "answer_short"
    low = answer.lower()
    for m in _NEVER_CACHE_ANSWER_MARKERS:
        if m in low:
            return False, "answer_refusal_error_or_nodata"
    for bad in _BAD_ANSWER_PATTERNS:
        if bad in low:
            return False, "answer_bad_pattern"
    try:
        from app.services.chat_coverage import looks_like_no_data_answer
        if looks_like_no_data_answer(answer):
            return False, "answer_no_data"
    except Exception:
        pass
    return True, "ok"


def is_cacheable(
    question: str, answer: str, *, tools_used: Optional[Sequence[str]] = None,
    live_data: bool = False, modified: bool = False, followup: bool = False,
    directive: bool = False, ephemeral: bool = False,
) -> Tuple[bool, str]:
    if followup:
        return False, "followup"
    if directive:
        return False, "directive"
    if ephemeral:
        return False, "ephemeral"
    if tools_used:
        return False, "tools_used"
    if live_data:
        return False, "live_data"
    if modified:
        return False, "answer_modified_by_verifier"
    ok, why = classify_question(question)
    if not ok:
        return False, why
    ok, why = classify_answer(answer)
    if not ok:
        return False, why
    return True, "ok"


# ── okuma ──
def get_cached_answer(
    db: Session,
    question: str,
    server_ids: list = None,
    *,
    platform: str = "linux",
    rbac_sig: str = "",
) -> Optional[dict]:
    """Tam (normalize) eşleşme. Kapalıysa / kavramsal değilse / süresi dolmuşsa None. HIT TTL'i UZATMAZ."""
    if not cache_enabled():
        _bump("get_disabled")
        return None
    if not _should_cache(question):
        return None
    ok, why = classify_question(question)
    if not ok:
        _bump(f"miss_skip:{why}")
        return None
    try:
        key = make_context_key(platform, server_ids or [], rbac_sig)
        norm_q = _normalize(question)
        row = (
            db.query(ChatQACache)
            .filter(ChatQACache.context_key == key, ChatQACache.question == norm_q)
            .order_by(ChatQACache.id.desc())
            .first()
        )
        if row is None or not _is_alive(row):
            _bump("miss")
            return None
        row.hit_count = int(row.hit_count or 0) + 1
        row.last_used = _now()
        db.commit()
        _bump("hit")
        logger.info("Cache HIT platform=%s key=%s hits=%s: %s", platform, key, row.hit_count, question[:60])
        return {
            "answer": row.answer, "cached": True, "hit_count": row.hit_count,
            "cache_id": row.id, "platform": _normalize_platform(platform),
        }
    except Exception as e:
        _bump("error")
        logger.warning("Cache lookup failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
    return None


# ── yazma ──
def _store(db: Session, norm_q: str, answer: str, key: str, hit_count: int = 0) -> str:
    row = (
        db.query(ChatQACache)
        .filter(ChatQACache.context_key == key, ChatQACache.question == norm_q)
        .first()
    )
    exp = _now() + cache_ttl()
    if row is not None:
        row.answer = answer
        row.rejected = False
        row.last_used = _now()
        row.expires_at = exp
        db.commit()
        return "updated"
    db.add(ChatQACache(
        question=norm_q, answer=answer, context_key=key, hit_count=hit_count, rejected=False, expires_at=exp,
    ))
    db.commit()
    return "saved"


def save_to_cache(
    db: Session,
    question: str,
    answer: str,
    server_ids: list = None,
    *,
    platform: str = "linux",
    rbac_sig: str = "",
    tools_used: Optional[Sequence[str]] = None,
    live_data: bool = False,
    modified: bool = False,
    followup: bool = False,
    directive: bool = False,
    ephemeral: bool = False,
) -> str:
    """Kaydetme kararı + yazma. Dönüş: `saved` | `updated` | `skip:<neden>` | `disabled` | `error`. Her sonuç loglanır/sayılır."""
    if not cache_enabled():
        _bump("save_disabled")
        return "disabled"
    ok, why = is_cacheable(
        question, answer, tools_used=tools_used, live_data=live_data, modified=modified,
        followup=followup, directive=directive, ephemeral=ephemeral,
    )
    if not ok:
        _bump(f"skip:{why}")
        logger.info("Cache SKIP platform=%s neden=%s: %s", platform, why, (question or "")[:60])
        return f"skip:{why}"
    try:
        key = make_context_key(platform, server_ids or [], rbac_sig)
        res = _store(db, _normalize(question), answer, key)
        _bump(res)
        logger.info("Cache %s platform=%s key=%s: %s", res.upper(), platform, key, question[:60])
        return res
    except Exception as e:
        _bump("error")
        logger.warning("Cache save failed: %s", e)
        try:
            db.rollback()
        except Exception:
            pass
        return "error"


# ── bakım / geçersizleme ──
def purge_bad_cache_entries(db: Session) -> int:
    try:
        rows = db.query(ChatQACache).all()
        to_delete = [
            r for r in rows
            if any(bad in (r.answer or "").lower() for bad in _BAD_ANSWER_PATTERNS)
            or any(m in (r.answer or "").lower() for m in _NEVER_CACHE_ANSWER_MARKERS)
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
        n = (
            db.query(ChatQACache)
            .filter(ChatQACache.expires_at.isnot(None), ChatQACache.expires_at < _now())
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


def _key_clauses(platform: str, server_ids: Optional[Sequence[int]]) -> List[str]:
    """`plat:hash`, `plat:hash:%`, `plat:global`, `plat:global:%` (imzalı/imzasız tüm kayıtlar)."""
    plat = _normalize_platform(platform)
    out = []
    for h in {_ids_hash(server_ids), "global"}:
        out += [f"{plat}:{h}", f"{plat}:{h}:%"]
    return out


def invalidate_context(
    db: Session,
    *,
    platform: Optional[str] = None,
    server_ids: Optional[Sequence[int]] = None,
    all_for_platform: bool = False,
) -> int:
    """Stale cevapları düşür (imzadan bağımsız tüm kullanıcı kayıtları)."""
    try:
        from sqlalchemy import or_
        q = db.query(ChatQACache)
        if all_for_platform and platform:
            rows = q.filter(ChatQACache.context_key.like(f"{_normalize_platform(platform)}:%")).all()
        elif platform is not None:
            pats = _key_clauses(platform, server_ids)
            rows = q.filter(or_(*[
                ChatQACache.context_key == p if "%" not in p else ChatQACache.context_key.like(p) for p in pats
            ])).all()
        elif server_ids:
            h = _ids_hash(server_ids)
            rows = q.filter(or_(ChatQACache.context_key.like(f"%:{h}"), ChatQACache.context_key.like(f"%:{h}:%"))).all()
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
    rbac_sig: str = "",
) -> dict:
    """vote=down → o sorunun TÜM imzalardaki kayıtları silinir; up → eşleşen (tam) kaydı yeniler/ekler
    (yalnız kavramsal cevap); correction_text → kullanıcının düzeltmesi bu kullanıcının imzasıyla saklanır."""
    vote = (vote or "").strip().lower()
    if vote not in ("up", "down"):
        raise ValueError("vote up|down olmalı")
    plat = _normalize_platform(platform)
    norm_q = _normalize(question or "")
    if not norm_q:
        raise ValueError("question gerekli")

    if vote == "down":
        rows = (
            db.query(ChatQACache)
            .filter(ChatQACache.context_key.like(f"{plat}:%"), ChatQACache.question == norm_q)
            .all()
        )
        for row in rows:
            db.delete(row)
        db.commit()
        if plat == "virt":
            try:
                from app.services import qa_cache as hv_qa
                hv_qa.invalidate_all()
            except Exception:
                pass
        return {"ok": True, "action": "rejected", "affected": len(rows)}

    final_answer = (correction_text or answer or "").strip()
    if not final_answer:
        raise ValueError("answer veya correction_text gerekli")
    if not correction_text:
        ok, why = is_cacheable(question, final_answer)
        if not ok:
            return {"ok": True, "action": "skipped", "reason": why}
    key = make_context_key(plat, server_ids or [], rbac_sig)
    res = _store(db, norm_q, final_answer, key, hit_count=5 if correction_text else 2)
    row = db.query(ChatQACache).filter(ChatQACache.context_key == key, ChatQACache.question == norm_q).first()
    return {"ok": True, "action": "boosted" if res == "updated" else "saved",
            "cache_id": getattr(row, "id", None), "hit_count": getattr(row, "hit_count", None)}
