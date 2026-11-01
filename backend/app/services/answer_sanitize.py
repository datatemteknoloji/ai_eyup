"""LLM cevap post-filter: yasaklı 'bilinmiyor' kaçışlarını temizle."""
from __future__ import annotations

import re
from typing import Optional

_BILINMIYOR_SENTENCE = re.compile(
    r"[^.!\n]*\bbilinmiyor\b[^.!\n]*[.!]?\s*",
    re.IGNORECASE,
)
_BILMIYORUM = re.compile(r"[^.!\n]*\bbilmiyorum\b[^.!\n]*[.!]?\s*", re.IGNORECASE)


def sanitize_llm_answer(text: Optional[str]) -> str:
    """Cevaptan 'bilinmiyor/bilmiyorum' cümlelerini düşür; kalan boşsa güvenli fallback."""
    if not text:
        return ""
    # Adım 19: model U+2011 (kırılmaz tire) vb. yazabiliyor → kullanıcı adı kopyalayınca eşleşme bozulur
    from app.services.chat_text_norm import normalize_hyphens
    text = normalize_hyphens(text)
    out = _BILINMIYOR_SENTENCE.sub("", text)
    out = _BILMIYORUM.sub("", out)
    out = re.sub(r"\n{3,}", "\n\n", out).strip()
    if not out:
        # Orijinalde sadece bilinmiyor vardı — yumuşak yönlendirme
        return "Bu bilgi mevcut taramada toplanmadi."
    return out
