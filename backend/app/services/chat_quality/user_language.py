"""Kullanıcı dili eşlemesi (Adım 8 kapanış): cevap BİTTİKTEN sonra, doğrulayıcıdan ÖNCE deterministik.

Yalnız iki TAM sözcük (büyük harf, sözcük sınırlı) insan diline çevrilir:
  NOT_QUERIED   → «bu kaynak bu turda sorgulanmadı»
  SUCCESS_EMPTY → «kayıt bulunamadı»
Çitli kod blokları (``` … ```) ve `/json` komutlu turlar dokunulmaz; LLM kullanılmaz.
"""
from __future__ import annotations

import re
from typing import Optional

_MAP = {
    "NOT_QUERIED": "bu kaynak bu turda sorgulanmadı",
    "SUCCESS_EMPTY": "kayıt bulunamadı",
}
_WORD_RE = re.compile(r"(?<![A-Za-z0-9_])(NOT_QUERIED|SUCCESS_EMPTY)(?![A-Za-z0-9_])")
_FENCE_RE = re.compile(r"(```.*?(?:```|\Z))", re.S)


def _sub(m: "re.Match[str]", s: str) -> str:
    out = _MAP[m.group(1)]
    # Cümle/satır başında ise ilk harf büyük
    before = s[:m.start()].rstrip(" *_>#-\t\"“‘'(")
    if not before or before[-1] in ".!?\n":
        out = out[:1].upper() + out[1:]
    return out


def _apply(chunk: str) -> str:
    return _WORD_RE.sub(lambda m: _sub(m, chunk), chunk)


def normalize(text: str, *, directive: Optional[str] = None) -> str:
    """Düzeltilmiş metin; değişiklik yoksa girdi aynen döner. `directive='json'` → dokunma."""
    if not text or (directive or "").lower() == "json":
        return text
    if "NOT_QUERIED" not in text and "SUCCESS_EMPTY" not in text:
        return text
    parts = _FENCE_RE.split(text)
    # tek sayılı indeksler = kod blokları
    return "".join(p if i % 2 else _apply(p) for i, p in enumerate(parts))


def message_directive(message: str) -> str:
    """Kullanıcı mesajındaki çıktı komutu adı ('json' vb.; yoksa '')."""
    try:
        from app.services.chat_output_directives import extract_output_directive
        return extract_output_directive(message or "")[1].value
    except Exception:
        return ""
