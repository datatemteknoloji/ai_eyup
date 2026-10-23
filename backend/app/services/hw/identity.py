"""Seri / UUID normalizasyonu ve kaynak-bazlı kimlik ayıklama (saf fonksiyonlar, I/O yok)."""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional

# SMBIOS/OEM yer tutucuları — eşleştirmede KULLANILMAZ (yanlış pozitif üretir)
_PLACEHOLDERS = {
    "", "0", "NONE", "NULL", "N/A", "NA", "NOTSPECIFIED", "NOTAVAILABLE", "UNKNOWN", "DEFAULTSTRING",
    "TOBEFILLEDBYO.E.M.", "TOBEFILLEDBYOEM", "SYSTEMSERIALNUMBER", "SERIALNUMBER", "O.E.M.", "OEM",
    "[UNKNOWN]", "UNSPECIFIED", "XXXXXXXX", "123456789", "0123456789", "00000000", "1234567890",
    "FFFFFFFF", "CHASSISSERIALNUMBER",
}
_UUID_RE = re.compile(r"^[0-9a-f]{8}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{4}-?[0-9a-f]{12}$", re.I)
_NIL_UUIDS = {"00000000-0000-0000-0000-000000000000", "ffffffff-ffff-ffff-ffff-ffffffffffff"}


def normalize_serial(v: Any) -> Optional[str]:
    """Büyük harf, boşluksuz seri. Yer tutucu/boş → None. Sanal seri önekleri ("VMware-") fiziksel sayılmaz."""
    if v is None:
        return None
    s = re.sub(r"\s+", "", str(v)).upper()
    if s.replace("-", "") in _PLACEHOLDERS or s in _PLACEHOLDERS:
        return None
    if len(s) < 4:
        return None
    if set(s) <= {"0"} or set(s) <= {"F"}:
        return None
    return s[:64]


def normalize_uuid(v: Any) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip().lower()
    if not _UUID_RE.match(s):
        return None
    if "-" not in s:
        s = f"{s[0:8]}-{s[8:12]}-{s[12:16]}-{s[16:20]}-{s[20:]}"
    if s in _NIL_UUIDS:
        return None
    return s


def uuid_swapped(u: Optional[str]) -> Optional[str]:
    """SMBIOS karışık-endian dönüşümü (ilk 3 alan bayt ters). Bazı araçlar (dmidecode/ESXi/OneView) farklı sıralar."""
    if not u:
        return None
    p = u.split("-")
    if len(p) != 5:
        return None

    def rev(h: str) -> str:
        return "".join(reversed([h[i:i + 2] for i in range(0, len(h), 2)]))

    return "-".join([rev(p[0]), rev(p[1]), rev(p[2]), p[3], p[4]])


def uuid_variants(u: Optional[str]) -> List[str]:
    n = normalize_uuid(u)
    if not n:
        return []
    out = [n]
    sw = uuid_swapped(n)
    if sw and sw != n:
        out.append(sw)
    return out


def short_host(name: Any) -> Optional[str]:
    """FQDN → kısa ad (küçük harf). IP adresleri ve boş değerler None."""
    if not name:
        return None
    s = str(name).strip().lower()
    if not s or re.match(r"^\d+\.\d+\.\d+\.\d+$", s) or ":" in s:
        return None
    return s.split(".")[0] or None


# ── vSphere HostSystemIdentificationInfo ────────────────────────────────────────────────────────────────────────
def vsphere_identity(hw_struct: Optional[Dict[str, Any]]) -> Dict[str, Optional[str]]:
    """`hardware.systemInfo` yapısından seri/enclosure/asset etiketi.

    HostSystemIdentificationInfo.identifierType.key: ServiceTag | SerialNumberTag | EnclosureSerialNumberTag | AssetTag
    (vSphere Web Services SDK). Sahada doğrulanmadı — bulunamazsa None (tahmin yok).
    """
    out: Dict[str, Optional[str]] = {"serial": None, "enclosure_serial": None, "asset_tag": None}
    if not isinstance(hw_struct, dict):
        return out
    items = hw_struct.get("otherIdentifyingInfo")
    if items is None:
        return out
    if not isinstance(items, list):
        items = [items]
    by_key: Dict[str, str] = {}
    for it in items:
        if not isinstance(it, dict):
            continue
        t = it.get("identifierType")
        key = (t.get("key") if isinstance(t, dict) else None) or ""
        val = it.get("identifierValue")
        if key and isinstance(val, str):
            by_key[key] = val
    out["serial"] = normalize_serial(by_key.get("ServiceTag") or by_key.get("SerialNumberTag"))
    out["enclosure_serial"] = normalize_serial(by_key.get("EnclosureSerialNumberTag"))
    out["asset_tag"] = normalize_serial(by_key.get("AssetTag"))
    return out


# ── Linux / Windows betik çıktıları ─────────────────────────────────────────────────────────────────────────────
# Linux: root gerekir (sysfs product_serial/product_uuid 0400). `sudo -n` yoksa alanlar boş kalır → not_measurable.
LINUX_IDENTITY_CMD = (
    "S=$(cat /sys/class/dmi/id/product_serial 2>/dev/null); U=$(cat /sys/class/dmi/id/product_uuid 2>/dev/null); "
    "if [ -z \"$S\" ]; then S=$(sudo -n dmidecode -s system-serial-number 2>/dev/null); fi; "
    "if [ -z \"$U\" ]; then U=$(sudo -n dmidecode -s system-uuid 2>/dev/null); fi; "
    "echo \"SERIAL=$S\"; echo \"UUID=$U\""
)

WINDOWS_IDENTITY_PS = (
    "$r=@{}; try{$r.Serial=(Get-CimInstance Win32_BIOS).SerialNumber}catch{}; "
    "try{$r.Uuid=(Get-CimInstance Win32_ComputerSystemProduct).UUID}catch{}; $r | ConvertTo-Json -Compress"
)


def parse_linux_identity(out: str) -> Dict[str, Optional[str]]:
    serial = uuid = None
    for line in (out or "").splitlines():
        if line.startswith("SERIAL="):
            serial = normalize_serial(line[7:])
        elif line.startswith("UUID="):
            uuid = normalize_uuid(line[5:])
    return {"serial": serial, "uuid": uuid}


def parse_windows_identity(out: str) -> Dict[str, Optional[str]]:
    import json
    try:
        d = json.loads((out or "").strip() or "{}")
    except Exception:  # noqa: BLE001
        d = {}
    return {"serial": normalize_serial(d.get("Serial")), "uuid": normalize_uuid(d.get("Uuid"))}


def first(values: Iterable[Any]) -> Optional[Any]:
    for v in values:
        if v:
            return v
    return None
