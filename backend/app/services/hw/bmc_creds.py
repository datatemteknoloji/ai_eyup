"""Faz 3b — BMC kimlik profili çözümü (SAF; I/O yok) + saklama yardımcıları.

Öncelik (en özelden genele, DETERMİNİSTİK): host'a özel > portal (entegrasyon) > üretici (dell/hpe) > global.
Seçilen hesap reddedilirse bir sonrakine GEÇİLMEZ (BMC hesap kilitlenmesin) — çağıran `auth_failed` yazar.
"""
from __future__ import annotations

import json
from typing import Any, Iterable, List, NamedTuple, Optional, Tuple

from app.core.encryption import decrypt_secret, encrypt_secret

LEVELS = ("host", "instance", "vendor", "global")
SCOPES = ("global", "vendor", "instance", "host")
VENDORS = ("dell", "hpe")


class Resolved(NamedTuple):
    profile: Optional[Any]
    level: Optional[str]          # host | instance | vendor | global | None


def has_credentials(profile: Any) -> bool:
    return bool(profile is not None and getattr(profile, "credential_ref", None))


def resolve(endpoint: Any, *, vendor: Optional[str], instance_id: Optional[int],
            profiles: Iterable[Any]) -> Resolved:
    """İlk TANIMLI (kimlik bilgisi dolu) seviye kazanır. Zincirleme deneme için DEĞİL, yalnız seçim içindir."""
    plist: List[Any] = [p for p in profiles if has_credentials(p)]
    pid = getattr(endpoint, "profile_id", None)
    if pid is not None:
        for p in plist:
            if p.id == pid:
                return Resolved(p, "host")
    if instance_id is not None:
        for p in plist:
            if p.scope == "instance" and p.instance_id == instance_id:
                return Resolved(p, "instance")
    v = (vendor or "").lower()
    if v:
        for p in plist:
            if p.scope == "vendor" and (p.vendor or "").lower() == v:
                return Resolved(p, "vendor")
    for p in plist:
        if p.scope == "global":
            return Resolved(p, "global")
    return Resolved(None, None)


def load(profile: Any) -> Tuple[str, str]:
    """(kullanıcı, parola) — yalnız bellekte; log'a/API'ye yazılmaz."""
    try:
        d = json.loads(decrypt_secret(profile.credential_ref) or "{}") if profile.credential_ref else {}
    except Exception:  # noqa: BLE001
        d = {}
    return str(d.get("username") or ""), str(d.get("password") or "")


def username_of(profile: Any) -> str:
    return load(profile)[0]


def store(profile: Any, username: str, password: Optional[str]) -> None:
    """Parola boşsa mevcut korunur."""
    prev_user, prev_pw = load(profile) if getattr(profile, "credential_ref", None) else ("", "")
    user = (username or prev_user or "").strip()
    pw = password if password else prev_pw
    profile.credential_ref = encrypt_secret(json.dumps({"username": user, "password": pw}))


def public_dict(profile: Any, *, level: Optional[str] = None) -> dict:
    """API çıktısı: parola ASLA yok."""
    return {
        "id": profile.id, "name": profile.name, "scope": profile.scope, "vendor": profile.vendor,
        "instance_id": profile.instance_id, "username": username_of(profile),
        "has_password": bool(load(profile)[1]), "verify_tls": bool(profile.verify_tls),
        **({"level": level} if level else {}),
    }
