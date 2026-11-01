"""Sohbet metni normalizasyonu (Adım 19).

Model (özellikle gpt-oss) cevaplarında ad/IP içindeki ``-`` yerine Unicode «kırılmaz tire» (U+2011) vb. yazabiliyor.
Kullanıcı bu adı kopyalayıp sorunca varlık eşleşmesi (VM/host/sunucu adı, grafik niyeti) başarısız olup yavaş LLM
yoluna düşülüyordu. Çözüm iki yönlüdür: kullanıcı girdisi normalize edilir, model çıktısı da normal tireyle yazılır.
"""
from __future__ import annotations

import re
from typing import Optional

# U+2010 hyphen, 2011 non-breaking hyphen, 2012 figure dash, 2013 en, 2014 em, 2015 horizontal bar,
# 2212 minus, FE58 small em dash, FE63 small hyphen-minus, FF0D fullwidth hyphen-minus
_DASHES = re.compile("[\u2010\u2011\u2012\u2013\u2014\u2015\u2212\ufe58\ufe63\uff0d]")
# Çıktı için YALNIZ tire-benzeri (ad/IP içinde kullanılanlar): en/em çizgi (U+2013/2014) tipografik olarak korunur
_HYPHENS = re.compile("[\u2010\u2011\u2012\u2212\ufe63\uff0d]")
_SPACES = re.compile("[\u00a0\u2007\u2009\u202f]")
_ZERO_WIDTH = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")


def normalize_dashes(text: Optional[str]) -> str:
    """TÜM Unicode tire/çizgileri `-` yapar (kullanıcı girdisi için; tek karakter→tek karakter)."""
    if not text:
        return text or ""
    return _DASHES.sub("-", text)


def normalize_hyphens(text: Optional[str]) -> str:
    """Model ÇIKTISI için: yalnız tire-benzeri karakterler (U+2010/2011/2012, eksi U+2212, FE63, FF0D) → `-`.

    En/em çizgi (U+2013/U+2014) korunur — cümle içi tipografi bozulmasın; ad/IP içinde kullanılmazlar.
    """
    if not text:
        return text or ""
    return _HYPHENS.sub("-", text)


def normalize_user_text(text: Optional[str]) -> str:
    """Kullanıcı girdisi: tireler → `-`, kırılmaz/dar boşluklar → ' ', sıfır genişlikli karakterler silinir."""
    if not text:
        return text or ""
    out = _ZERO_WIDTH.sub("", text)
    out = _SPACES.sub(" ", out)
    return _DASHES.sub("-", out)
