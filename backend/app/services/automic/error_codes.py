"""Bilinen hata kodları için küçük, kaynaklı sözlük + dönüş kodu notu.

Amaç: modelin ORA-xxxxx / OS hata mesajlarının anlamını KENDİ bilgisinden (etiketsiz, bazen yanlış) yazmasını
önlemek. Açıklama koddan gelir, "Genel bilgi:" etiketi ve kaynak kod tarafından eklenir; cevaba model değil sistem
ekler (`known_codes_block`). Sözlükte olmayan kod için açıklama ÜRETİLMEZ.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Tuple

ORACLE_SRC = "Oracle Database Error Messages (docs.oracle.com)"
POSIX_SRC = "POSIX errno (errno.h)"

RETURN_CODE_NOTE = ("Bu dönüş kodunun anlamı çalıştırılan programa/script'e özgüdür; "
                    "Automic'te genel bir anlamı yoktur.")

STATUS_CODE_NOTE = (
    "Automic durum kodu (örn. 1800 ENDED_NOT_OK) işin anormal bittiğini gösterir; "
    "nedeni hakkında bilgi vermez. Neden için rapor ve dönüş kodu incelenmelidir."
)
STATUS_CODE_NOTE_EN = (
    "An Automic status code (e.g. 1800 ENDED_NOT_OK) only shows the run ended abnormally; "
    "it does not explain why. Inspect the report and the return code for the cause."
)

# kod → kısa Türkçe açıklama (yalnız iyi bilinen, belgelenmiş kodlar)
ORA_CODES: Dict[str, str] = {
    "ORA-00001": "benzersiz (unique) kısıt ihlal edildi",
    "ORA-00018": "izin verilen azami oturum sayısı aşıldı",
    "ORA-00054": "kaynak meşgul (kilit); NOWAIT ile istendi veya bekleme süresi doldu",
    "ORA-00060": "kaynak beklenirken kilitlenme (deadlock) tespit edildi",
    "ORA-00904": "geçersiz tanımlayıcı (kolon/ad bulunamadı)",
    "ORA-00942": "tablo veya görünüm yok (veya erişim yetkisi yok)",
    "ORA-01017": "kullanıcı adı/parola geçersiz; oturum açma reddedildi",
    "ORA-01031": "yetersiz yetki",
    "ORA-01400": "NULL değer eklenemez (NOT NULL kolon)",
    "ORA-01555": "snapshot too old: sorgu için gereken eski (undo) veri artık mevcut değil",
    "ORA-01652": "TEMP tablespace'te geçici segment genişletilemedi (alan yetersiz)",
    "ORA-01653": "tablespace'te tablo genişletilemedi (alan yetersiz)",
    "ORA-01654": "tablespace'te indeks genişletilemedi (alan yetersiz)",
    "ORA-01722": "geçersiz sayı (sayıya dönüştürme hatası)",
    "ORA-01843": "geçerli bir ay değil (tarih biçimi hatası)",
    "ORA-03113": "iletişim kanalında dosya sonu (bağlantı koptu)",
    "ORA-03114": "ORACLE'a bağlı değil",
    "ORA-04031": "paylaşılan bellekte yer ayrılamadı",
    "ORA-06512": "PL/SQL hata izi satırı (tek başına neden değildir; asıl hata başka ORA kodudur)",
    "ORA-12154": "TNS: bağlantı tanımlayıcısı çözümlenemedi",
    "ORA-12170": "TNS: bağlantı zaman aşımı",
    "ORA-12514": "TNS: dinleyici istenen servisi tanımıyor",
    "ORA-12541": "TNS: dinleyici (listener) yok",
    "ORA-12545": "bağlantı kurulamadı: hedef sunucu/nesne yok",
    "ORA-28000": "hesap kilitli",
    "ORA-28001": "parolanın süresi dolmuş",
}

# OS düzeyi metinler (küçük harfle aranır)
OS_PHRASES: List[Tuple[str, str]] = [
    ("no space left on device", "disk/dosya sistemi dolu (ENOSPC)"),
    ("permission denied", "erişim izni yok (EACCES)"),
    ("connection refused", "bağlantı reddedildi (ECONNREFUSED)"),
    ("connection timed out", "bağlantı zaman aşımı (ETIMEDOUT)"),
    ("no such file or directory", "dosya veya dizin yok (ENOENT)"),
]

_ORA_RE = re.compile(r"ORA[-\u2010-\u2015\u2212]?\s?0*(\d{1,5})", re.I)


def _norm_ora(num: str) -> str:
    return f"ORA-{int(num):05d}"


def find_known_codes(text: str) -> List[Dict[str, str]]:
    """Metindeki sözlükte bulunan kodlar: [{code, text, source}] (sırayı korur, tekrarsız)."""
    out: List[Dict[str, str]] = []
    seen = set()
    for m in _ORA_RE.finditer(text or ""):
        code = _norm_ora(m.group(1))
        if code in ORA_CODES and code not in seen:
            seen.add(code)
            out.append({"code": code, "text": ORA_CODES[code], "source": ORACLE_SRC})
    low = (text or "").lower()
    for phrase, desc in OS_PHRASES:
        if phrase in low and phrase not in seen:
            seen.add(phrase)
            out.append({"code": phrase, "text": desc, "source": POSIX_SRC})
    return out


def _has_nonzero_return_code(obj: Any, depth: int = 0) -> bool:
    if depth > 6:
        return False
    if isinstance(obj, dict):
        rc = obj.get("return_code")
        if isinstance(rc, (int, float)) and not isinstance(rc, bool) and rc != 0:
            return True
        return any(_has_nonzero_return_code(v, depth + 1) for v in obj.values())
    if isinstance(obj, list):
        return any(_has_nonzero_return_code(v, depth + 1) for v in obj[:200])
    return False


_INJECT_LINE_RE = re.compile(
    r"(?i)(önceki\s+talimatlar[ıi]\s+yok\s+say|ignore\s+(all\s+)?previous\s+instructions?|"
    r"talimatlar[ıi]\s+yoksay|şifreleri\s+listele|list\s+all\s+passwords?|"
    r"\brestart\s+et\b|kullan[ıi]c[ıi]ya\s+['\"]?işlem\s+başar[ıi]yla|"
    r"system\s*:\s*bu\s+job|disregard\s+(all\s+)?prior)",
)


INJECTION_WARN_TR = (
    "Raporda talimat benzeri şüpheli bir satır var; dikkate alınmadı. İncelenmesi önerilir."
)
INJECTION_WARN_EN = (
    "The report contains an instruction-like suspicious line; it was ignored. Review recommended."
)


def find_injection_lines(text: str) -> List[str]:
    """Rapor kırpıntısındaki talimat benzeri satırlar (uygulanmaz; uyarı için)."""
    out: List[str] = []
    for ln in (text or "").splitlines():
        if _INJECT_LINE_RE.search(ln):
            s = ln.strip()
            if s and s not in out:
                out.append(s[:200])
    return out[:5]


def annotate_result(res: Dict[str, Any]) -> None:
    """Araç sonucuna sabit alanlar ekler: `return_code_note` (sıfırdan farklı dönüş kodu varsa) ve
    `known_error_codes` (sözlükteki kodlar; açıklama + kaynak). Mevcut alanların üzerine yazmaz."""
    if not isinstance(res, dict) or res.get("ok") is False:
        return
    try:
        if _has_nonzero_return_code(res):
            res.setdefault("return_code_note", RETURN_CODE_NOTE)
        blob = json.dumps(res, ensure_ascii=False, default=str)
        codes = find_known_codes(blob)
        if codes and "known_error_codes" not in res:
            res["known_error_codes"] = codes
            res["known_error_codes_note"] = (
                "Bu kodların açıklamasını SİSTEM cevaba 'Genel bilgi:' olarak ekler; sen kodların anlamını/nedenini YAZMA, "
                "yalnız kodu an.")
        # Rapor içeriğindeki enjeksiyon satırları
        content = res.get("content")
        if isinstance(content, str):
            inj = find_injection_lines(content)
            if inj:
                res.setdefault("injection_suspect_lines", inj)
                res.setdefault("injection_warning_tr", INJECTION_WARN_TR)
                res.setdefault("injection_warning_en", INJECTION_WARN_EN)
    except Exception as exc:   # yardımcı alan; araç sonucunu bozmasın (ama sessiz yutulmaz)
        from app.services.automic.errors import note_error
        note_error("error_codes.annotate_result", exc)
        return


def injection_warning_block(structured: Any, *, english: bool = False) -> str:
    """Cevaba kod tarafından eklenecek enjeksiyon uyarısı (yoksa '')."""
    lines: List[str] = []
    for sr in (structured if isinstance(structured, list) else [structured]):
        res = sr.get("result") if isinstance(sr, dict) else sr
        if not isinstance(res, dict):
            continue
        if res.get("injection_suspect_lines") or res.get("injection_warning_tr"):
            note = res.get("injection_warning_en" if english else "injection_warning_tr") or (
                INJECTION_WARN_EN if english else INJECTION_WARN_TR)
            if note not in lines:
                lines.append(note)
    if not lines:
        return ""
    return "**Uyarı:** " + " ".join(lines) if not english else "**Warning:** " + " ".join(lines)


def known_codes_block(structured: Any, *, answer_text: str = "") -> str:
    """Cevabın sonuna 'Genel bilgi' bloğu — yalnız cevap/gözlemlerde geçen kodlar (ilgisiz ORA yok).

    `answer_text` boşsa geriye dönük: structured içindeki imza/rapor alanlarından seçer
    (tüm JSON blob değil — uydurma genel bilgi engeli).
    """
    visible = (answer_text or "").strip()
    if visible:
        codes = find_known_codes(visible)
    else:
        # Yalnız hata imzası / rapor / items alanlarından tara (tüm structured değil)
        parts: List[str] = []
        for sr in (structured if isinstance(structured, list) else [structured]):
            res = (sr.get("result") if "result" in sr else sr) if isinstance(sr, dict) else sr
            if not isinstance(res, dict):
                continue
            for k in ("error_signature", "content", "summary", "summary_tr"):
                if res.get(k):
                    parts.append(str(res[k]))
            for it in (res.get("items") or [])[:50]:
                if isinstance(it, dict) and it.get("error_signature"):
                    parts.append(str(it["error_signature"]))
            for row in (res.get("rows") or [])[:30]:
                if isinstance(row, dict):
                    for k in ("signature", "error_signature"):
                        if row.get(k):
                            parts.append(str(row[k]))
            dist = res.get("error_signature_distribution") or []
            for d in dist[:20]:
                if isinstance(d, dict) and d.get("signature"):
                    parts.append(str(d["signature"]))
        codes = find_known_codes("\n".join(parts))
    if not codes:
        return ""
    lines = [f"- **{c['code']}** — {c['text']} _(Kaynak: {c['source']})_" for c in codes[:6]]
    return "**Genel bilgi:** (sistem tarafından eklendi; ortam verisi değil)\n" + "\n".join(lines)
