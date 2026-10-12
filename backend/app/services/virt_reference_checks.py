"""Offline referans paketleri: CVE/VMSA, bilinen sorun (KB), yükseltme matrisi.

İnternet erişimi gerekmez: paketleri operatör JSON olarak yükler
(`infra_reference_data`). Eşleme deterministiktir — sürüm/build karşılaştırması.

Ürün anahtarları: esxi | vcenter | olvm_engine | olvm_host | ocp_virt | openshift
Sürüm aralığı sözdizimi: ">=7.0,<7.0.3" (virgül = VE); liste = VEYA.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.infra_finding import InfraReferenceData
from app.services import reference_sources as rsrc
from app.services.findings.registry import (
    ISO_VULN, ISO_CONFIG, RESULT_FAIL, RESULT_NOT_MEASURABLE, RESULT_PASS,
)
from app.services.findings.store import FindingDraft

KINDS = ("cve_feed", "kb_feed", "upgrade_matrix")
EOL_WARN_DAYS = 180
FEED_STALE_DAYS = 30
_SEV = {"critical": "critical", "important": "high", "high": "high", "moderate": "medium",
        "medium": "medium", "low": "low"}


# ── Sürüm karşılaştırma ──────────────────────────────────────────────────────

def vtuple(v: Any) -> Tuple:
    """'7.0.3', '7.0 U3', '8.0.2-22380479', '4.5.5-1.el8' → karşılaştırılabilir tuple."""
    s = str(v or "").strip().lower()
    if not s:
        return ()
    s = re.sub(r"\s*u(pdate)?\s*(\d+)", r".\2", s)
    s = s.split("-")[0]
    parts: List[Any] = []
    for p in re.split(r"[.\s_]+", s):
        m = re.match(r"^(\d+)([a-z]*)$", p)
        if m:
            parts.append(int(m.group(1)))
            if m.group(2):
                parts.append(m.group(2))
        elif p:
            parts.append(p)
    while parts and parts[-1] == 0:
        parts.pop()
    return tuple(parts)


def _cmp(a: Tuple, b: Tuple) -> int:
    for x, y in zip(a, b):
        if x == y:
            continue
        if isinstance(x, int) and isinstance(y, int):
            return -1 if x < y else 1
        # sayı < harf (7.0.3 < 7.0.3c)
        if isinstance(x, int):
            return -1
        if isinstance(y, int):
            return 1
        return -1 if str(x) < str(y) else 1
    return (len(a) > len(b)) - (len(a) < len(b))


def _match_clause(ver: Tuple, clause: str) -> bool:
    clause = clause.strip()
    if not clause:
        return True
    m = re.match(r"^(>=|<=|==|=|>|<)?\s*(.+)$", clause)
    op, val = (m.group(1) or "=="), vtuple(m.group(2))
    c = _cmp(ver, val)
    return {">=": c >= 0, "<=": c <= 0, ">": c > 0, "<": c < 0, "==": c == 0, "=": c == 0}[op]


def version_affected(version: Any, ranges: Iterable[str], build: Any = None,
                     fixed_build: Any = None) -> bool:
    ver = vtuple(version)
    if not ver:
        return False
    rs = [r for r in (ranges or []) if r]
    in_range = any(all(_match_clause(ver, c) for c in r.split(",")) for r in rs) if rs else True
    if not in_range:
        return False
    if fixed_build and build:
        try:
            return int(str(build).strip()) < int(str(fixed_build).strip())
        except ValueError:
            pass
    return True


# ── Paket yükleme ────────────────────────────────────────────────────────────

def get_ref(db: Session, kind: str) -> Optional[Dict[str, Any]]:
    row = db.query(InfraReferenceData).filter(InfraReferenceData.kind == kind).first()
    return row.payload if row else None


def canonical_json(payload: Dict[str, Any]) -> str:
    """Sağlama toplamı için kanonik JSON: anahtarlar sıralı, boşluksuz; üst düzey `sha256` alanı hariç."""
    body = {k: v for k, v in payload.items() if k != "sha256"}
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def compute_checksum(payload: Dict[str, Any]) -> str:
    return hashlib.sha256(canonical_json(payload).encode("utf-8")).hexdigest()


def parse_generated_at(value: Any) -> Optional[datetime]:
    """'2026-10-01' veya ISO tarih-saat → UTC datetime; geçersizse None."""
    if not isinstance(value, str) or not value.strip():
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v) if len(v) > 10 else datetime.combine(date.fromisoformat(v), datetime.min.time())
    except ValueError:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def validate_meta(payload: Dict[str, Any], *, now: Optional[datetime] = None) -> Tuple[bool, str]:
    """Yeni yüklemelerde üretim tarihi zorunlu; sağlama toplamı varsa doğrulanır."""
    now = now or datetime.now(timezone.utc)
    gen = parse_generated_at(payload.get("generated_at"))
    if gen is None:
        return False, "'generated_at' (üretim tarihi, YYYY-AA-GG) zorunlu"
    if gen > now + timedelta(days=1):
        return False, "'generated_at' gelecekte olamaz"
    claimed = payload.get("sha256")
    if claimed not in (None, ""):
        if not isinstance(claimed, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", claimed):
            return False, "'sha256' 64 karakterlik onaltılık değer olmalı"
        if claimed.lower() != compute_checksum(payload):
            return False, "Paket bütünlük doğrulaması başarısız: 'sha256' içerikle eşleşmiyor"
    return True, ""


def _records(kind: str, payload: Dict[str, Any]) -> List[Any]:
    if kind == "cve_feed":
        return payload.get("advisories") or []
    if kind == "kb_feed":
        return payload.get("articles") or []
    return []


def validate_package(kind: str, payload: Any) -> Tuple[bool, str, int]:
    if not isinstance(payload, dict):
        return False, "JSON nesnesi bekleniyor", 0
    if kind == "cve_feed":
        items = payload.get("advisories")
        if not isinstance(items, list):
            return False, "'advisories' listesi zorunlu", 0
        for a in items:
            if not isinstance(a, dict) or not a.get("id") or not isinstance(a.get("products"), list):
                return False, "Her advisory 'id' ve 'products' içermeli", 0
        n = len(items)
    elif kind == "kb_feed":
        items = payload.get("articles")
        if not isinstance(items, list):
            return False, "'articles' listesi zorunlu", 0
        for a in items:
            if not isinstance(a, dict) or not a.get("id") or not a.get("title"):
                return False, "Her makale 'id' ve 'title' içermeli", 0
        n = len(items)
    elif kind == "upgrade_matrix":
        if not isinstance(payload.get("products"), dict):
            return False, "'products' nesnesi zorunlu", 0
        n = len(payload["products"]) + len(payload.get("hardware") or [])
    else:
        return False, f"Bilinmeyen paket türü: {kind}", 0
    bad = rsrc.offenders(_records(kind, payload))
    if bad:
        shown = "; ".join(bad[:5]) + (f" … (+{len(bad) - 5})" if len(bad) > 5 else "")
        return False, ("Kayıt bağlantıları yalnız resmi üretici alan adlarına (https) izin verir; "
                       f"{len(bad)} kayıt reddedildi, paket yüklenmedi: {shown}"), 0
    return True, "", n


def save_package(db: Session, kind: str, payload: Dict[str, Any], *, user: str = "",
                 now: Optional[datetime] = None) -> Dict[str, Any]:
    ok, err, n = validate_package(kind, payload)
    if not ok:
        raise ValueError(err)
    ok, err = validate_meta(payload, now=now)
    if not ok:
        raise ValueError(err)
    row = db.query(InfraReferenceData).filter(InfraReferenceData.kind == kind).first()
    if row is None:
        row = InfraReferenceData(kind=kind)
        db.add(row)
    row.payload = payload
    row.item_count = n
    row.source_label = str(payload.get("source") or "")[:255]
    row.uploaded_by = user
    row.uploaded_at = now or datetime.now(timezone.utc)
    row.version = (str(payload.get("version"))[:64] if payload.get("version") not in (None, "") else None)
    row.generated_at = parse_generated_at(payload.get("generated_at"))
    row.sha256 = compute_checksum(payload)
    row.integrity = "verified" if payload.get("sha256") else "computed_only"
    db.flush()
    return {"kind": kind, "item_count": n, "source": row.source_label,
            "generated_at": row.generated_at.isoformat(), "sha256": row.sha256, "integrity": row.integrity}


def delete_package(db: Session, kind: str) -> bool:
    """Paketi siler. Mevcut bulgulara DOKUNMAZ: bir sonraki turda 'doğrulanamayan' olarak korunurlar."""
    row = db.query(InfraReferenceData).filter(InfraReferenceData.kind == kind).first()
    if row is None:
        return False
    db.delete(row)
    db.flush()
    return True


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt


def pack_age(row: Any, now: Optional[datetime] = None) -> Tuple[Optional[float], Optional[str], Optional[datetime]]:
    """(yaş_gün, temel, referans_zamanı). Temel: 'generated_at' (tercih) | 'uploaded_at' | None."""
    now = now or datetime.now(timezone.utc)
    ref, basis = _aware(getattr(row, "generated_at", None)), "generated_at"
    if ref is None:
        ref, basis = _aware(getattr(row, "uploaded_at", None)), "uploaded_at"
    if ref is None:
        return None, None, None
    return max(0.0, (now - ref).total_seconds() / 86400.0), basis, ref


def pack_info(db: Session, kind: str) -> Optional[Dict[str, Any]]:
    """Bulgu kanıtına yazılan paket künyesi (paket sonradan silinse de 'son bilinen durum' etiketi için)."""
    row = db.query(InfraReferenceData).filter(InfraReferenceData.kind == kind).first()
    if row is None:
        return None
    gen = _aware(getattr(row, "generated_at", None))
    return {"kind": kind, "version": getattr(row, "version", None),
            "generated_at": gen.date().isoformat() if gen else None,
            "uploaded_at": _aware(row.uploaded_at).date().isoformat() if row.uploaded_at else None,
            "sha256": getattr(row, "sha256", None)}


def package_status(db: Session, *, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    now = now or datetime.now(timezone.utc)
    rows = {r.kind: r for r in db.query(InfraReferenceData).all()}
    out = []
    for k in KINDS:
        r = rows.get(k)
        age, basis, _ = pack_age(r, now) if r else (None, None, None)
        if r is None:
            state = "missing"
        elif age is None:
            state = "unknown"
        else:
            state = "stale" if age > FEED_STALE_DAYS else "ok"
        gen = _aware(getattr(r, "generated_at", None)) if r else None
        out.append({
            "kind": k, "loaded": r is not None, "state": state,
            "item_count": r.item_count if r else 0,
            "source": r.source_label if r else None,
            "uploaded_by": r.uploaded_by if r else None,
            "uploaded_at": r.uploaded_at.isoformat() if r and r.uploaded_at else None,
            "version": getattr(r, "version", None) if r else None,
            "generated_at": gen.isoformat() if gen else None,
            "age_days": round(age, 1) if age is not None else None,
            "age_basis": basis,
            "stale_threshold_days": FEED_STALE_DAYS,
            "sha256": getattr(r, "sha256", None) if r else None,
            "integrity": getattr(r, "integrity", None) if r else None,
            "sources": rsrc.verified_sources(k),
        })
    return out


# ── Envanter → ürün sürümleri ────────────────────────────────────────────────

def product_targets(platform: str, collected: Dict[str, Any]) -> List[Dict[str, Any]]:
    """[{product, version, build, entity_kind, entity_ref, entity_name, cluster, vendor, model}]"""
    out: List[Dict[str, Any]] = []
    about = collected.get("about") or {}
    if platform == "vmware":
        if about.get("version"):
            out.append({"product": "vcenter", "version": about.get("version"), "build": about.get("build"),
                        "entity_kind": "platform", "entity_ref": "platform:vcenter",
                        "entity_name": about.get("fullName") or "vCenter", "cluster": None})
        for h in collected.get("hosts") or []:
            c = h["config"]
            if c.get("version"):
                out.append({"product": "esxi", "version": c.get("version"), "build": c.get("build"),
                            "entity_kind": "host", "entity_ref": f"host:{h['ref']}", "entity_name": h["name"],
                            "cluster": h.get("cluster"), "vendor": c.get("vendor"), "model": c.get("model")})
    elif platform == "olvm":
        if about.get("version"):
            out.append({"product": "olvm_engine", "version": about.get("version"), "build": None,
                        "entity_kind": "platform", "entity_ref": "platform:engine",
                        "entity_name": about.get("name") or "OLVM Manager", "cluster": None})
        for h in collected.get("hosts") or []:
            c = h["config"]
            if c.get("version"):
                out.append({"product": "olvm_host", "version": c.get("version"), "build": None,
                            "entity_kind": "host", "entity_ref": f"host:{h['ref']}", "entity_name": h["name"],
                            "cluster": h.get("cluster"), "vendor": c.get("vendor"), "model": c.get("model")})
    elif platform == "ocp_virt":
        hco = (collected.get("platform") or {}).get("hco") or {}
        if hco.get("version"):
            out.append({"product": "ocp_virt", "version": hco.get("version"), "build": None,
                        "entity_kind": "platform", "entity_ref": "platform:hco", "entity_name": "OpenShift Virtualization",
                        "cluster": (collected.get("platform") or {}).get("cluster_name")})
    elif platform == "ocp":
        cv = collected.get("cluster_version") or {}
        if cv.get("version"):
            out.append({"product": "openshift", "version": cv.get("version"), "build": None,
                        "entity_kind": "cluster", "entity_ref": "cluster:version", "entity_name": cv.get("name") or "cluster",
                        "cluster": cv.get("name")})
    return out


# ── Değerlendirme ────────────────────────────────────────────────────────────

def _event_text(db: Session, source_id: Optional[int], platform: str) -> List[Tuple[str, str, str]]:
    from app.models.event import SystemEvent
    since = datetime.now(timezone.utc) - timedelta(days=14)
    out = []
    for e in (db.query(SystemEvent).filter(SystemEvent.created_at >= since)
              .order_by(SystemEvent.created_at.desc()).limit(5000).all()):
        rd = e.raw_data if isinstance(e.raw_data, dict) else {}
        if platform != "ocp" and rd.get("hypervisor_id") not in (source_id, str(source_id)):
            continue
        out.append((str(rd.get("host_name") or rd.get("host") or ""), f"{e.title or ''} {e.description or ''}",
                    e.created_at.isoformat() if e.created_at else ""))
    return out


def vuln_findings(db: Session, platform: str, collected: Dict[str, Any]) -> Optional[List[FindingDraft]]:
    feed = get_ref(db, "cve_feed")
    if not feed:
        return None
    pack = pack_info(db, "cve_feed")
    targets = product_targets(platform, collected)
    out: List[FindingDraft] = []
    for adv in feed.get("advisories") or []:
        for prod in adv.get("products") or []:
            if not isinstance(prod, dict):
                continue
            for t in targets:
                if t["product"] != prod.get("product"):
                    continue
                hit = version_affected(t["version"], prod.get("affected") or [], t.get("build"), prod.get("fixed_build"))
                cves = adv.get("cve") or []
                out.append(FindingDraft(
                    f"vuln:{adv['id']}", t["entity_kind"], t["entity_ref"], t["entity_name"],
                    "fail" if hit else "pass",
                    evidence={"advisory": adv["id"], "cve": cves, "cvss": adv.get("cvss"),
                              "installed": t["version"], "build": t.get("build"),
                              "fixed": prod.get("fixed"), "fixed_build": prod.get("fixed_build"),
                              "url": rsrc.safe_source_url(rsrc.record_url(adv)),
                              "source_url": rsrc.safe_source_url(rsrc.record_url(adv)),
                              "workaround": adv.get("workaround"), "pack": pack},
                    detail=(f"Kurulu {t['version']} ({t.get('build') or '-'}) → düzeltme {prod.get('fixed') or '?'}"
                            + (f" / build {prod.get('fixed_build')}" if prod.get("fixed_build") else "")),
                    cluster_name=t.get("cluster"),
                    severity=_SEV.get(str(adv.get("severity") or "").lower(), "high"),
                    title=f"{adv['id']}: {adv.get('title') or ', '.join(cves[:3])}"[:480],
                    recommendation=(f"{prod.get('fixed') or 'Düzeltilmiş sürüme'} yükseltin."
                                    + (f" Geçici çözüm: {adv['workaround']}" if adv.get("workaround") else "")),
                    refs=[ISO_VULN],
                ))
    return out


def known_issue_findings(db: Session, platform: str, source_id: Optional[int],
                         collected: Dict[str, Any]) -> Optional[List[FindingDraft]]:
    feed = get_ref(db, "kb_feed")
    if not feed:
        return None
    pack = pack_info(db, "kb_feed")
    targets = product_targets(platform, collected)
    events = _event_text(db, source_id, platform)
    out: List[FindingDraft] = []
    for art in feed.get("articles") or []:
        pats = [re.compile(p, re.I) for p in (art.get("event_patterns") or art.get("symptoms") or []) if p]
        prods = art.get("products") or []
        for t in targets:
            applicable = False
            for prod in prods:
                if isinstance(prod, dict) and prod.get("product") == t["product"] and \
                        version_affected(t["version"], prod.get("affected") or [], t.get("build"), prod.get("fixed_build")):
                    applicable = True
                    break
            if not applicable:
                continue
            matched = []
            if pats:
                for host, txt, at in events:
                    if t["entity_kind"] == "host" and host and host != t["entity_name"]:
                        continue
                    if any(p.search(txt) for p in pats):
                        matched.append({"host": host, "text": txt[:200], "at": at})
                        if len(matched) >= 10:
                            break
            sev = "high" if matched else _SEV.get(str(art.get("severity") or "").lower(), "low")
            out.append(FindingDraft(
                f"kb:{art['id']}", t["entity_kind"], t["entity_ref"], t["entity_name"], "fail",
                evidence={"article": art["id"], "url": rsrc.safe_source_url(rsrc.record_url(art)),
                          "source_url": rsrc.safe_source_url(rsrc.record_url(art)), "installed": t["version"],
                          "symptom_matches": matched, "symptom_matched": bool(matched), "pack": pack},
                detail=("Belirti olaylarda görüldü" if matched else "Sürüm etkileniyor; belirti görülmedi"),
                cluster_name=t.get("cluster"), severity=sev,
                title=f"{art['id']}: {art['title']}"[:480],
                recommendation=str(art.get("resolution") or "Makaledeki çözümü uygulayın."),
            ))
    return out


def upgrade_findings(platform: str, collected: Dict[str, Any], matrix: Optional[Dict[str, Any]],
                     pack: Optional[Dict[str, Any]] = None) -> List[FindingDraft]:
    out: List[FindingDraft] = []
    targets = product_targets(platform, collected)
    hcl = collected.get("hcl") or {}
    if matrix:
        products = matrix.get("products") or {}
        hw = [h for h in (matrix.get("hardware") or []) if isinstance(h, dict)]
        today = date.today()
        for t in targets:
            spec = products.get(t["product"]) or {}
            if not spec:
                continue
            ver = vtuple(t["version"])
            eol_row = None
            for e in spec.get("eol") or []:
                ev = vtuple(e.get("version"))
                if ev and ver[:len(ev)] == ev:
                    eol_row = e
                    break
            if eol_row and eol_row.get("eol_date"):
                try:
                    eol = date.fromisoformat(str(eol_row["eol_date"])[:10])
                    days = (eol - today).days
                    out.append(FindingDraft(
                        "upg:eol", t["entity_kind"], t["entity_ref"], t["entity_name"],
                        "fail" if days <= EOL_WARN_DAYS else "pass",
                        evidence={"installed": t["version"], "eol_date": str(eol), "days_left": days, "pack": pack},
                        detail=(f"Destek bitti ({eol})" if days < 0 else f"Destek bitişine {days} gün ({eol})"),
                        cluster_name=t.get("cluster"), severity="critical" if days < 0 else "high",
                        title=f"{t['product']} {t['version']} destek sonu", refs=[ISO_VULN],
                        recommendation=f"Hedef sürüm: {spec.get('target') or 'destekli sürüm'}",
                    ))
                except ValueError:
                    pass
            target = spec.get("target")
            if target:
                behind = _cmp(ver, vtuple(target)) < 0
                path = None
                for p in spec.get("paths") or []:
                    fv = vtuple(p.get("from"))
                    if fv and ver[:len(fv)] == fv:
                        path = p
                        break
                blockers = []
                if t.get("model"):
                    for h in hw:
                        if str(h.get("model") or "").lower() == str(t["model"]).lower() and (
                                not h.get("vendor") or str(h["vendor"]).lower() in str(t.get("vendor") or "").lower()):
                            if h.get("max_version") and _cmp(vtuple(target), vtuple(h["max_version"])) > 0:
                                blockers.append({"model": t["model"], "max_version": h["max_version"],
                                                 "notes": h.get("notes")})
                out.append(FindingDraft(
                    "upg:target", t["entity_kind"], t["entity_ref"], t["entity_name"],
                    "fail" if behind else "pass",
                    evidence={"installed": t["version"], "target": target, "path": path, "hardware_blockers": blockers,
                              "pack": pack},
                    detail=(f"{t['version']} → {target}" + (f" (ara: {path.get('via')})" if path and path.get("via") else "")
                            + (" · donanım engeli" if blockers else "")),
                    cluster_name=t.get("cluster"),
                    severity="high" if blockers else ("medium" if behind else None),
                    title=f"{t['product']} hedef sürüm uyumu",
                    recommendation=(path or {}).get("notes") or "Yükseltme yolunu ve ön koşulları doğrulayın.",
                    refs=[ISO_VULN, ISO_CONFIG],
                ))
    for cname, h in hcl.items():
        if not isinstance(h, dict):
            continue
        avail = h.get("available")
        st = str(h.get("status") or "").upper()
        out.append(FindingDraft(
            "upg:vlcm_hcl", "cluster", f"cluster:{cname}", cname,
            "not_measurable" if not avail or st in ("", "HCL_DATA_UNAVAILABLE", "UNAVAILABLE") else
            ("fail" if st == "INCOMPATIBLE" else "pass"),
            evidence=h, detail=st or str(h.get("reason") or ""), cluster_name=cname,
            title="vLCM donanım uyumluluk (HCL) raporu",
            recommendation="Uyumsuz bileşen için firmware/driver güncelleyin veya hedef sürümü yeniden değerlendirin.",
            severity="high" if st == "INCOMPATIBLE" else None,
        ))
    return out


# Paket yokluğunda "değerlendirilemedi" bulguları (asla pass değil).
_UNASSESSED = {
    "cve_feed": ("ref.vuln.unassessed", "Zafiyet değerlendirmesi yapılamadı: zafiyet paketi yüklü değil",
                 "Zafiyet paketi (cve_feed) yüklenene kadar sürüm eşleştirmesi yapılamaz. Bu, 'zafiyet yok' anlamına gelmez."),
    "kb_feed": ("ref.kb.unassessed", "Bilinen sorun eşleştirmesi yapılamadı: bilinen sorunlar paketi yüklü değil",
                "Bilinen sorunlar paketi (kb_feed) yüklenene kadar eşleştirme yapılamaz. Bu, 'bilinen sorun yok' anlamına gelmez."),
    "upgrade_matrix": ("ref.upgrade.unassessed", "Yükseltme değerlendirmesi yapılamadı: yükseltme matrisi yüklü değil",
                       "Yükseltme matrisi (upgrade_matrix) yüklenene kadar EOL/hedef sürüm değerlendirilemez."),
}
# Paket yokluğunda KORUNAN (kapatılmayan) mevcut bulgu aileleri: kind → check_id önekleri
PRESERVED_ON_MISSING = {"cve_feed": ("vuln:",), "kb_feed": ("kb:",), "upgrade_matrix": ("upg:eol", "upg:target")}
STALE_KIND = "ref_pack_missing"


def unassessed_findings(kind: str) -> List[FindingDraft]:
    cid, title, rec = _UNASSESSED[kind]
    return [FindingDraft(
        cid, "cluster", f"feed:{kind}", kind, RESULT_NOT_MEASURABLE,
        evidence={"kind": kind, "reason": "package_missing"},
        detail="Paket yüklü değil — sonuç ölçülemedi (başarılı sayılmaz).",
        title=title, recommendation=rec, refs=[ISO_VULN],
    )]


def mark_pack_missing(db: Session, *, platform: str, source_id: Optional[int], kind: str) -> int:
    """Paket yokken mevcut aktif FAIL bulgularını 'son bilinen durum' olarak işaretler.

    Bulgular KAPANMAZ, sayımdan ÇIKMAZ; yalnız `stale=True` + kanıta etiket yazılır.
    Yeniden değerlendirme (yeni paket) `persist_findings` ile bayrağı ve etiketi temizler.
    """
    from app.models.infra_finding import InfraFinding
    from sqlalchemy import or_
    prefixes = PRESERVED_ON_MISSING[kind]
    q = db.query(InfraFinding).filter(
        InfraFinding.platform == platform, InfraFinding.active.is_(True), InfraFinding.result == RESULT_FAIL,
        or_(*[InfraFinding.check_id.like(p + "%") for p in prefixes]),
    )
    q = q.filter(InfraFinding.source_id == source_id) if source_id is not None else q.filter(InfraFinding.source_id.is_(None))
    n = 0
    for r in q.all():
        ev = dict(r.evidence or {})
        pk = ev.get("pack") or {}
        ver = pk.get("version") or "?"
        when = pk.get("generated_at") or pk.get("uploaded_at") or "tarih bilinmiyor"
        ev["stale_kind"] = STALE_KIND
        ev["stale_note"] = (f"Son bilinen durum: paket v{ver} ({when}) ile tespit edildi, şu an doğrulanamıyor"
                            if ver != "?" else
                            f"Son bilinen durum: paket ({when}) ile tespit edildi, şu an doğrulanamıyor")
        r.evidence = ev
        r.stale = True
        n += 1
    return n


def feed_age_findings(db: Session, *, now: Optional[datetime] = None) -> List[FindingDraft]:
    """Referans paketlerinin yaşı (`ref.feed.stale`): > FEED_STALE_DAYS gün → "güncel değil".

    Yaş, paketin ÜRETİM tarihinden hesaplanır (eski veriyi bugün yüklemek paketi taze göstermez);
    üretim tarihi yoksa (eski yüklemeler) yükleme zamanı kullanılır ve kanıtta belirtilir.
    Yüklü ama tarihi hiç belirlenemeyen paket ve YÜKLÜ OLMAYAN paket → not_measurable (asla pass değil).
    """
    now = now or datetime.now(timezone.utc)
    out: List[FindingDraft] = []
    loaded = set()
    for row in db.query(InfraReferenceData).all():
        if row.kind not in KINDS:
            continue
        loaded.add(row.kind)
        age_days, basis, ref = pack_age(row, now)
        if age_days is None:
            out.append(FindingDraft(
                "ref.feed.stale", "cluster", f"feed:{row.kind}", row.kind, RESULT_NOT_MEASURABLE,
                evidence={"kind": row.kind, "reason": "date_unknown", "source": row.source_label or None},
                detail=f"{row.kind} paketinin tarihi belirlenemedi — yaş ölçülemedi",
                title=f"Referans paketi yaşı ölçülemedi: {row.kind}",
                recommendation="Üretim tarihi ('generated_at') içeren güncel paketi yükleyin.", refs=[ISO_VULN],
            ))
            continue
        stale = age_days > FEED_STALE_DAYS
        what = "üretildi" if basis == "generated_at" else "yüklendi"
        out.append(FindingDraft(
            "ref.feed.stale", "cluster", f"feed:{row.kind}", row.kind,
            RESULT_FAIL if stale else RESULT_PASS,
            evidence={"kind": row.kind, "age_basis": basis, "reference_at": ref.isoformat(),
                      "uploaded_at": _aware(row.uploaded_at).isoformat() if row.uploaded_at else None,
                      "age_days": round(age_days, 1), "threshold_days": FEED_STALE_DAYS,
                      "source": row.source_label or None},
            detail=f"{row.kind} paketi {int(age_days)} gün önce {what} (eşik {FEED_STALE_DAYS} gün)",
            severity="medium" if stale else "info",
            title=f"Referans paketi güncel değil: {row.kind}",
            recommendation="Güncel CVE/KB/yükseltme paketini 'Paketler & hesaplar' sekmesinden yükleyin.",
            refs=[ISO_VULN],
        ))
    for kind in KINDS:
        if kind not in loaded:
            out.append(FindingDraft(
                "ref.feed.stale", "cluster", f"feed:{kind}", kind, RESULT_NOT_MEASURABLE,
                evidence={"kind": kind, "reason": "package_missing"},
                detail=f"{kind} paketi yüklü değil — yaş ölçülemedi",
                title=f"Referans paketi yüklü değil: {kind}",
                recommendation="İlgili referans paketini 'Paketler & hesaplar' sekmesinden yükleyin.", refs=[ISO_VULN],
            ))
    return out


def persist_reference_findings(db: Session, *, platform: str, source_id: Optional[int], source_name: str,
                               col: Dict[str, Any], run_id: Optional[int] = None,
                               now: Optional[datetime] = None) -> Dict[str, Any]:
    """vuln / known_issue / upgrade kategorilerini yazar.

    G.4 kuralı: paket yokluğu HİÇBİR mevcut bulguyu kapatmaz. Paket yoksa yalnız "ölçülemedi" kaydı yazılır
    (çözüm kapsamı bu kaydın kimliğiyle sınırlı); eski FAIL bulgular "son bilinen durum" olarak işaretlenir,
    sayımda KALIR. Yalnız yeni paketle yeniden değerlendirme (geçti) bulguyu çözer.
    """
    from app.services.findings import store
    kw = dict(platform=platform, source_id=source_id, source_name=source_name, run_id=run_id, now=now)
    stats: Dict[str, Any] = {}

    vdrafts = vuln_findings(db, platform, col)
    v_scope = None
    if vdrafts is None:
        vdrafts, v_scope = unassessed_findings("cve_feed"), ["ref.vuln.unassessed"]
        stats["vuln_stale_marked"] = mark_pack_missing(db, platform=platform, source_id=source_id, kind="cve_feed")
    stats["vuln"] = store.persist_findings(db, categories=("vuln",), drafts=vdrafts, resolve_checks=v_scope, **kw)

    kdrafts = known_issue_findings(db, platform, source_id, col)
    k_scope = None
    if kdrafts is None:
        kdrafts, k_scope = unassessed_findings("kb_feed"), ["ref.kb.unassessed"]
        stats["known_issue_stale_marked"] = mark_pack_missing(db, platform=platform, source_id=source_id, kind="kb_feed")
    stats["known_issue"] = store.persist_findings(db, categories=("known_issue",), drafts=kdrafts,
                                                  resolve_checks=k_scope, **kw)

    matrix = get_ref(db, "upgrade_matrix")
    udrafts = list(upgrade_findings(platform, col, matrix, pack=pack_info(db, "upgrade_matrix")))
    u_scope = None
    if not matrix:
        udrafts += unassessed_findings("upgrade_matrix")
        u_scope = ["upg:vlcm_hcl", "ref.upgrade.unassessed", "ref.feed.stale"]
        stats["upgrade_stale_marked"] = mark_pack_missing(db, platform=platform, source_id=source_id,
                                                          kind="upgrade_matrix")
    udrafts += feed_age_findings(db, now=now)
    stats["upgrade"] = store.persist_findings(db, categories=("upgrade",), drafts=udrafts,
                                              resolve_checks=u_scope, **kw)
    return stats
