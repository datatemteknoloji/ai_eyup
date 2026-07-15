"""
Chat oturumu icindeki onceki mesajlari (konusma gecmisi) LLM prompt'una eklemek
icin ortak yardimcilar.

SORUN: chat.py/unified_chat.py/windows_chat.py bir session_id ile gelen YENI
mesaji islerken, o session'daki ONCEKI mesajlari hic okumuyordu — sadece o anki
mesaj + taze SSH/Prometheus/RAG context'i tek seferlik bir prompt'a koyup LLM'e
gonderiyordu. Bu yuzden "peki cpu?", "o sunucuda ise ..." gibi bir onceki soruya
atifta bulunan takip sorulari, hangi sunucudan/konudan bahsedildigini bilemiyor,
sohbet diyalog gibi degil birbirinden bagimsiz tekil sorular gibi davraniyordu
(sadece hypervisor chat DB'den gecmisi okuyup prompt'a ekliyordu, digerleri
etmiyordu). Bu modul o eksigi ortak bir yardimci ile kapatir.
"""
from typing import Dict, List, Optional

from sqlalchemy.orm import Session


def fetch_recent_history(
    db: Session, session_id: int, limit: int = 8, exclude_message_id: Optional[int] = None
) -> List[Dict[str, str]]:
    """Bir session'daki son `limit` mesaji (eskiden yeniye siralanmis) dondurur."""
    from app.models.chat_session import ChatMessage

    if not session_id:
        return []
    q = db.query(ChatMessage).filter(ChatMessage.session_id == session_id)
    if exclude_message_id:
        q = q.filter(ChatMessage.id != exclude_message_id)
    rows = q.order_by(ChatMessage.id.desc()).limit(limit).all()
    rows.reverse()
    return [{"role": r.role, "content": r.content or ""} for r in rows]


def has_prior_messages(db: Session, session_id: Optional[int]) -> bool:
    """Bu session'da zaten en az bir mesaj var mi (yani bu bir takip sorusu mu)?"""
    if not session_id:
        return False
    from app.models.chat_session import ChatMessage

    return db.query(ChatMessage.id).filter(ChatMessage.session_id == session_id).first() is not None


def format_history_block(
    history: List[Dict[str, str]], max_turns: int = 6, max_chars_per_msg: int = 700
) -> str:
    """Gecmisi LLM prompt'una eklenebilecek kisa bir metin blogu haline getirir."""
    if not history:
        return ""
    lines = []
    for h in history[-max_turns:]:
        role_label = "Kullanici" if h.get("role") == "user" else "Asistan"
        content = (h.get("content") or "").strip()
        if not content:
            continue
        if len(content) > max_chars_per_msg:
            content = content[:max_chars_per_msg] + " …(kisaltildi)"
        lines.append(f"{role_label}: {content}")
    return "\n".join(lines)


# Placeholder titles used when "+ Yeni" creates an empty session
_PLACEHOLDER_TITLES = frozenset({
    "yeni chat",
    "yeni sohbet",
    "new chat",
    "new conversation",
})


def title_from_message(text: str, max_len: int = 60) -> str:
    """İlk kullanıcı mesajından sohbet listesi başlığı üret."""
    q = " ".join((text or "").strip().split())
    if not q:
        return "Yeni Chat"
    if len(q) > max_len:
        return q[: max_len - 1].rstrip() + "…"
    return q


def is_placeholder_title(title: Optional[str]) -> bool:
    t = (title or "").strip().lower()
    return (not t) or t in _PLACEHOLDER_TITLES


def maybe_set_session_title(session, message: str) -> bool:
    """Placeholder başlığıysa ilk mesajla değiştir. True = güncellendi."""
    if session is None or not is_placeholder_title(getattr(session, "title", None)):
        return False
    session.title = title_from_message(message)
    return True


def repair_session_title_from_first_user_message(db: Session, session) -> None:
    """Liste/API sırasında hâlâ 'Yeni Chat' olan dolu oturumları düzelt."""
    if session is None or not is_placeholder_title(getattr(session, "title", None)):
        return
    from app.models.chat_session import ChatMessage

    first = (
        db.query(ChatMessage)
        .filter(ChatMessage.session_id == session.id, ChatMessage.role == "user")
        .order_by(ChatMessage.id.asc())
        .first()
    )
    if first and (first.content or "").strip():
        session.title = title_from_message(first.content)
