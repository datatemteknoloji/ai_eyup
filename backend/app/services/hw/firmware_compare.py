"""Referans sunucu tabanlı firmware karşılaştırması — SALT-OKUNUR hesap (donanıma yazılmaz).

Kural özeti (ayrıntı: docs/plans/hw-providers.md › Faz C):
* Referans: model kapsamı (vendor+model, tüm sunucular) veya şasi kapsamı (yalnız o şasideki AYNI model). Şasi > model.
* Yalnız KURULU (`Installed`) bileşenler kıyaslanır; Dell'deki `Available` (önceki/yedek) satırlar yok sayılır.
* Bileşen anahtarı = normalize ad (+ HPE `componentLocation`). Aynı anahtar farklı sürümlerle tekrarlıyorsa belirsiz → kıyas dışı.
* Sürüm ayrıştırma SAVUNMACI: iki taraf da noktalı sayı dizisi vermiyorsa ya da ROM ailesi (`I42` ≠ `I41`) farklıysa «ölçülemedi» —
  asla «düşük» denmez, bulgu üretilmez.
* «Kabul edildi» yalnız kabul anındaki sürüm sunucudaki güncel sürümle AYNI olduğu sürece geçerlidir.
* Sunucuda hiç firmware satırı yoksa yalnız BMC/BIOS sürümleri (sunucu kaydından) sahte bileşen olarak kullanılır; bu anahtarlar
  gerçek bileşen satırlarıyla eşleşmez → karşılaştırma ölçülemedi kalır (sahte alarm yok).
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.hw import HwEnclosure, HwFirmware, HwFirmwareAccept, HwFirmwareReference, HwServer

ST_OK, ST_OUTDATED, ST_ACCEPTED, ST_UNKNOWN = "ok", "outdated", "accepted", "unknown"
ST_REFERENCE, ST_NO_REF, ST_NO_DATA, ST_REF_NO_DATA = "reference", "no_reference", "no_data", "reference_no_data"

_MAC = re.compile(r"\b[0-9A-Fa-f]{2}(?::[0-9A-Fa-f]{2}){5}\b")
_DOTTED = re.compile(r"\d+(?:\.\d+)+")
_FAMILY = re.compile(r"^\s*([A-Za-z]\d{2,3})\b")        # HPE ROM ailesi: `I42 v2.40 (04/09/2020)`


def norm_component_name(name: Optional[str]) -> str:
    n = _MAC.sub("", name or "")
    n = re.sub(r"\s+", " ", n).strip(" -\t").lower()
    return n


def component_key(name: Optional[str], location: Optional[str] = None) -> str:
    return f"{norm_component_name(name)}|{(location or '').strip().lower()}"[:400]


def parse_version(v: Optional[str]) -> Optional[Tuple[Tuple[int, ...], str]]:
    """(sayı dizisi, aile) veya None. İlk noktalı sayı dizisi alınır (`7.00.00.172`, `v2.40 (date)` → 2.40,
    `iLO 5 v2.78` → 2.78). Noktalı dizi yoksa None (ölçülemedi) — tek tamsayı güvenilir değil (tarih/yapı numarası olabilir)."""
    if not v or not isinstance(v, str):
        return None
    m = _DOTTED.search(v)
    if not m:
        return None
    try:
        nums = tuple(int(x) for x in m.group(0).split("."))
    except ValueError:
        return None
    fam = _FAMILY.match(v)
    return nums, (fam.group(1).upper() if fam else "")


def compare_versions(cur: Optional[str], ref: Optional[str]) -> str:
    """`ok` | `outdated` | `newer` | `unknown`."""
    if (cur or "").strip() == (ref or "").strip() and cur:
        return ST_OK
    a, b = parse_version(cur), parse_version(ref)
    if a is None or b is None or a[1] != b[1]:
        return ST_UNKNOWN
    x, y = list(a[0]), list(b[0])
    n = max(len(x), len(y))
    x += [0] * (n - len(x))
    y += [0] * (n - len(y))
    return ST_OK if x == y else (ST_OUTDATED if x < y else "newer")


def component_map(s: HwServer, fw: Iterable[HwFirmware]) -> Tuple[Dict[str, Dict[str, Any]], bool]:
    """(anahtar → {name, location, version}, gerçek_firmware_var_mı). Belirsiz (aynı anahtar, farklı sürüm) bileşen çıkarılır."""
    comps: Dict[str, Dict[str, Any]] = {}
    ambiguous: set = set()
    real = [f for f in fw if (f.status or "Installed") == "Installed" and (f.version or "").strip()]
    for f in real:
        k = component_key(f.name, f.location)
        if not k.strip("|"):
            continue
        if k in comps and comps[k]["version"] != f.version.strip():
            ambiguous.add(k)
            continue
        comps[k] = {"name": re.sub(r"\s+", " ", _MAC.sub("", f.name or "")).strip(" -\t") or (f.name or ""),
                    "location": f.location, "version": f.version.strip()}
    for k in ambiguous:
        comps.pop(k, None)
    if real:
        return comps, True
    for label, ver in (("BMC", s.bmc_version), ("BIOS", s.bios_version)):
        if (ver or "").strip():
            comps[component_key(label)] = {"name": label, "location": None, "version": ver.strip()}
    return comps, False


def _model_key(vendor: Optional[str], model: Optional[str]) -> Tuple[str, str]:
    return (vendor or "").lower(), re.sub(r"\s+", " ", (model or "").strip()).lower()


def enclosure_of(db: Session, servers: List[HwServer]) -> Dict[int, int]:
    """sunucu id → şasi id (kimlik; ad yalnız tekilse). `api.hw._blades_by_enclosure` ile AYNI mantık."""
    from app.api.hw import _blades_by_enclosure
    inst = list({s.instance_id for s in servers}) or [-1]
    encl = db.query(HwEnclosure).filter(HwEnclosure.instance_id.in_(inst)).all()
    blades = [s for s in servers if s.enclosure_ref or s.enclosure_name or (s.form_factor or "").lower() == "blade"]
    mapping, _un = _blades_by_enclosure(encl, blades)
    return {it["id"]: eid for eid, items in mapping.items() for it in items}


def compare_all(db: Session, servers: List[HwServer], *, full: bool = False) -> Dict[int, Dict[str, Any]]:
    """Her sunucu için karşılaştırma sonucu (sunucu id → sonuç). `full=False`: yalnız `ok` olmayan bileşenler listelenir.
    Sonuç `_server` (HwServer) anahtarı içerir — API katmanı bunu atar."""
    ids = [s.id for s in servers] or [-1]
    refs = db.query(HwFirmwareReference).all()
    need = set(ids) | {r.reference_server_id for r in refs}
    all_srv: Dict[int, HwServer] = {s.id: s for s in servers}
    missing = [i for i in need if i not in all_srv]
    if missing:
        for s in db.query(HwServer).filter(HwServer.id.in_(missing)).all():
            all_srv[s.id] = s
    fw_by: Dict[int, List[HwFirmware]] = {}
    for f in db.query(HwFirmware).filter(HwFirmware.server_id.in_(list(need) or [-1])).all():
        fw_by.setdefault(f.server_id, []).append(f)
    accepts: Dict[Tuple[int, str], HwFirmwareAccept] = {
        (a.server_id, a.component_key): a for a in db.query(HwFirmwareAccept).filter(HwFirmwareAccept.server_id.in_(ids)).all()}
    enc_of = enclosure_of(db, list(all_srv.values())) if any(r.scope == "chassis" for r in refs) else {}
    enc_names = {e.id: e.name for e in db.query(HwEnclosure).all()} if enc_of else {}

    model_ref: Dict[Tuple[str, str], HwFirmwareReference] = {}
    chassis_ref: Dict[Tuple[int, Tuple[str, str]], HwFirmwareReference] = {}
    for r in refs:
        rs = all_srv.get(r.reference_server_id)
        if rs is None or _model_key(rs.vendor, rs.model) != _model_key(r.vendor, r.model):
            continue                                     # referans sunucunun modeli değişmiş/kayıp → geçersiz
        mk = _model_key(r.vendor, r.model)
        if r.scope == "chassis" and r.enclosure_id is not None:
            chassis_ref[(r.enclosure_id, mk)] = r
        elif r.scope == "model":
            model_ref[mk] = r

    cmap_cache: Dict[int, Tuple[Dict[str, Dict[str, Any]], bool]] = {}

    def cmap(sid: int):
        if sid not in cmap_cache:
            cmap_cache[sid] = component_map(all_srv[sid], fw_by.get(sid, []))
        return cmap_cache[sid]

    out: Dict[int, Dict[str, Any]] = {}
    for s in servers:
        mk = _model_key(s.vendor, s.model)
        eid = enc_of.get(s.id)
        ref = chassis_ref.get((eid, mk)) if eid is not None else None
        if ref is None:
            ref = model_ref.get(mk)
        res: Dict[str, Any] = {"server_id": s.id, "status": ST_NO_REF, "reference": None, "components": [],
                               "compared": 0, "outdated": 0, "accepted": 0, "unknown": 0, "newer": 0, "_server": s}
        mine, real = cmap(s.id)
        if ref is not None:
            rs = all_srv[ref.reference_server_id]
            res["reference"] = {"id": ref.id, "server_id": rs.id, "name": rs.name, "scope": ref.scope,
                                "enclosure_id": ref.enclosure_id, "enclosure_name": enc_names.get(ref.enclosure_id)}
        if ref is None:
            out[s.id] = res
            continue
        if ref.reference_server_id == s.id:
            res["status"] = ST_REFERENCE
            out[s.id] = res
            continue
        if not mine:
            res["status"] = ST_NO_DATA
            out[s.id] = res
            continue
        theirs, _rreal = cmap(ref.reference_server_id)
        if not theirs:
            res["status"] = ST_REF_NO_DATA
            out[s.id] = res
            continue
        comps: List[Dict[str, Any]] = []
        for k, c in mine.items():
            rc = theirs.get(k)
            if rc is None:
                continue
            state = compare_versions(c["version"], rc["version"])
            acc = accepts.get((s.id, k))
            accepted = False
            if state == ST_OUTDATED and acc is not None and acc.accepted_version == c["version"]:
                state, accepted = ST_ACCEPTED, True
            res["compared"] += 1
            if state == ST_OUTDATED:
                res["outdated"] += 1
            elif state == ST_ACCEPTED:
                res["accepted"] += 1
            elif state == ST_UNKNOWN:
                res["unknown"] += 1
            elif state == "newer":
                res["newer"] += 1
            if full or state != ST_OK:
                comps.append({"key": k, "name": c["name"], "location": c["location"], "version": c["version"],
                              "reference_version": rc["version"], "state": state, "accepted": accepted,
                              "accepted_by": acc.accepted_by if accepted and acc else None,
                              "note": acc.note if accepted and acc else None})
        order = {ST_OUTDATED: 0, ST_ACCEPTED: 1, ST_UNKNOWN: 2, "newer": 3, ST_OK: 4}
        comps.sort(key=lambda c: (order.get(c["state"], 9), c["name"].lower(), c["location"] or ""))
        res["components"] = comps
        if res["outdated"]:
            res["status"] = ST_OUTDATED
        elif res["accepted"]:
            res["status"] = ST_ACCEPTED
        elif res["compared"] and res["unknown"] < res["compared"]:
            res["status"] = ST_OK
        else:
            res["status"] = ST_UNKNOWN
        out[s.id] = res
    return out
