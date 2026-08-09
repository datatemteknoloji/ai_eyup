"""Katı IPv4 format doğrulama (VLAN ve ağ formları)."""

from __future__ import annotations


def _parse_strict_octets(value: str) -> tuple[int, int, int, int]:
    s = (value or "").strip()
    parts = s.split(".")
    if len(parts) != 4:
        raise ValueError("IPv4 dört octet olmalı (örn. 192.168.1.1)")
    octets: list[int] = []
    for part in parts:
        if not part.isdigit():
            raise ValueError("IPv4 yalnızca rakam ve nokta içermeli")
        if len(part) > 1 and part.startswith("0"):
            raise ValueError("Octet başında sıfır olamaz (örn. 01 geçersiz)")
        n = int(part)
        if n > 255:
            raise ValueError("Her octet 0–255 arasında olmalı")
        octets.append(n)
    return octets[0], octets[1], octets[2], octets[3]


def validate_host_ipv4(value: str) -> str:
    a, b, c, d = _parse_strict_octets(value)
    octets = (a, b, c, d)
    if all(n == 0 for n in octets):
        raise ValueError("0.0.0.0 geçerli bir IP değil")
    if all(n == 255 for n in octets):
        raise ValueError("255.255.255.255 geçerli bir IP değil")
    if a == 127:
        raise ValueError("Loopback (127.x) kullanılamaz")
    if a >= 224:
        raise ValueError("Multicast adresi kullanılamaz")
    return ".".join(str(n) for n in octets)


def validate_gateway_ipv4(value: str) -> str:
    a, b, c, d = _parse_strict_octets(value)
    octets = (a, b, c, d)
    if a == 0:
        raise ValueError("Gateway 0.x.x.x olamaz")
    if all(n == 0 for n in octets):
        raise ValueError("0.0.0.0 gateway olamaz")
    if all(n == 255 for n in octets):
        raise ValueError("255.255.255.255 gateway olamaz")
    if a == 127:
        raise ValueError("Loopback gateway olamaz")
    if a >= 224:
        raise ValueError("Multicast gateway olamaz")
    return ".".join(str(n) for n in octets)
