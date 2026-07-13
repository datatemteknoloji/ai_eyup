"""
Agent Guard — gpt-oss-safeguard ile politika-tabanlı komut denetimi.

Defense-in-depth ikinci katman:
  policy.py (regex, hızlı/katı) → guard.py (LLM, bağlamsal/politika)

gpt-oss-safeguard bir "bring-your-own-policy" sınıflandırıcısıdır: ona bir güvenlik
politikası + değerlendirilecek komut veririz; politikaya göre ALLOW / BLOCK kararını
gerekçesiyle döndürür.

Guard varsayılan olarak FAIL-OPEN'dır: model erişilemezse veya hata olursa karar
"allow_with_warning" olur — çünkü mutating aksiyonlar zaten insan onayına düşer
(guard ek bir koruma katmanıdır, tek savunma hattı değil).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Dict

import requests

from app.core.config import settings, get_guard_model
from app.services import llm_gateway

logger = logging.getLogger(__name__)


DEFAULT_SAFETY_POLICY = """\
SUNUCU OTOMASYON GÜVENLİK POLİTİKASI

Bir AIOps agent'ı sunucularda komut çalıştırmak istiyor. Aşağıdaki komutu bu politikaya
göre değerlendir.

BLOCK (engelle) edilmesi gerekenler:
- Veri kaybına yol açabilecek işlemler (disk biçimlendirme, volume silme, kullanıcı/hesap silme).
- Prodüksiyon veritabanı veya storage volume'larını durdurma/silme.
- Güvenlik bileşenlerini devre dışı bırakma (firewall kapatma, iptables flush, SELinux disable).
- Tüm sistemi/kümeyi etkileyecek toplu/yıkıcı işlemler (kitlesel reboot, init 0/6).
- Uzaktan indirilen kodu doğrudan çalıştırma (curl|bash gibi).
- Kapsam dışı, gerekçesiz veya şüpheli (komut enjeksiyonu içeren) işlemler.

ALLOW (izin ver) edilebilecekler (yine de insan onayına gider):
- Tek bir servisi yeniden başlatma (systemctl restart <servis>).
- Eski journald loglarını temizleme (vacuum).
- Paket güncelleme/kurulum (dnf/yum/apt).
- Tipik, gerekçesi olan bakım işlemleri.

Karar verirken komutun kapsamını ve olası yan etkisini dikkate al.
"""


def get_safety_policy(db) -> str:
    """Düzenlenebilir politika (app_settings: agent_safety_policy), yoksa varsayılan."""
    try:
        from app.models.app_settings import AppSettings
        row = db.query(AppSettings).filter(AppSettings.key == "agent_safety_policy").first()
        if row and row.value:
            return row.value
    except Exception:
        pass
    return DEFAULT_SAFETY_POLICY


def _parse_verdict(text: str) -> Dict[str, Any]:
    """Modelin çıktısından {decision, reason} ayıkla (JSON veya anahtar kelime)."""
    if not text:
        return {"decision": "allow", "reason": "boş yanıt", "raw": ""}
    # Önce JSON dene
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            data = json.loads(m.group(0))
            dec = str(data.get("decision", "")).lower()
            if "block" in dec or "deny" in dec or "engel" in dec:
                return {"decision": "block", "reason": data.get("reason", ""), "raw": text}
            if "allow" in dec or "izin" in dec or "ok" in dec:
                return {"decision": "allow", "reason": data.get("reason", ""), "raw": text}
        except Exception:
            pass
    # Anahtar kelime fallback
    low = text.lower()
    if re.search(r"\b(block|engelle|deny|reddet|unsafe|tehlikeli)\b", low):
        return {"decision": "block", "reason": text.strip()[:300], "raw": text}
    return {"decision": "allow", "reason": text.strip()[:300], "raw": text}


def guard_command(db, command: str, server_name: str) -> Dict[str, Any]:
    """
    Komutu güvenlik politikasına göre değerlendirir.

    Returns: {decision: 'allow'|'block', reason, model, enabled}
    """
    if not settings.AGENT_GUARD_ENABLED:
        return {"decision": "allow", "reason": "guard devre dışı", "model": None, "enabled": False}

    model = get_guard_model(db)
    policy = get_safety_policy(db)
    user_content = (
        f"DEĞERLENDİRİLECEK İŞLEM\n"
        f"Sunucu: {server_name}\n"
        f"Komut: {command}\n\n"
        f"Yalnızca şu JSON formatında yanıt ver: "
        f'{{"decision": "allow" | "block", "reason": "kısa Türkçe gerekçe"}}'
    )

    try:
        resp = llm_gateway.chat_sync(
            model=model,
            messages=[
                {"role": "system", "content": policy},
                {"role": "user", "content": user_content},
            ],
            options={"temperature": 0.0},
            timeout=90,
        )
        if resp.status_code != 200:
            logger.warning(f"[Guard] HTTP {resp.status_code}; fail-open")
            return {"decision": "allow", "reason": f"guard erişilemedi (HTTP {resp.status_code})",
                    "model": model, "enabled": True, "degraded": True}
        content = (resp.json().get("message", {}) or {}).get("content", "")
        verdict = _parse_verdict(content)
        verdict.update({"model": model, "enabled": True})
        logger.info(f"[Guard] {server_name} cmd={command[:60]} -> {verdict['decision']}")
        return verdict
    except Exception as e:
        logger.warning(f"[Guard] hata, fail-open: {e}")
        return {"decision": "allow", "reason": f"guard hatası: {e}", "model": model,
                "enabled": True, "degraded": True}
