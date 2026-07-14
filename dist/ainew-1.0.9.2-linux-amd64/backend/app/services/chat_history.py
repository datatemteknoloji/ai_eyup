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
