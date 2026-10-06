"""Offline referans paketleri: CVE/VMSA, bilinen sorun (KB), yükseltme matrisi.

İnternet erişimi gerekmez: paketleri operatör JSON olarak yükler
(`infra_reference_data`). Eşleme deterministiktir — sürüm/build karşılaştırması.

Ürün anahtarları: esxi | vcenter | olvm_engine | olvm_host | ocp_virt | openshift
Sürüm aralığı sözdizimi: ">=7.0,<7.0.3" (virgül = VE); liste = VEYA.
"""
from __future__ import annotations

import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.infra_finding import InfraReferenceData
from app.services.findings.registry import ISO_VULN, ISO_CONFIG
from app.services.findings.store import FindingDraft

KINDS = ("cve_feed", "kb_feed", "upgrade_matrix")
EOL_WARN_DAYS = 180
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
        return True, "", len(items)
    if kind == "kb_feed":
        items = payload.get("articles")
        if not isinstance(items, list):
            return False, "'articles' listesi zorunlu", 0
        for a in items:
            if not isinstance(a, dict) or not a.get("id") or not a.get("title"):
                return False, "Her makale 'id' ve 'title' içermeli", 0
        return True, "", len(items)
    if kind == "upgrade_matrix":
        if not isinstance(payload.get("products"), dict):
            return False, "'products' nesnesi zorunlu", 0
        return True, "", len(payload["products"]) + len(payload.get("hardware") or [])
    return False, f"Bilinmeyen paket türü: {kind}", 0


def save_package(db: Session, kind: str, payload: Dict[str, Any], *, user: str = "") -> Dict[str, Any]:
    ok, err, n = validate_package(kind, payload)
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
    row.uploaded_at = datetime.now(timezone.utc)
    db.flush()
    return {"kind": kind, "item_count": n, "source": row.source_label}


def package_status(db: Session) -> List[Dict[str, Any]]:
    rows = {r.kind: r for r in db.query(InfraReferenceData).all()}
    return [{
        "kind": k, "loaded": k in rows,
        "item_count": rows[k].item_count if k in rows else 0,
        "source": rows[k].source_label if k in rows else None,
        "uploaded_by": rows[k].uploaded_by if k in rows else None,
        "uploaded_at": rows[k].uploaded_at.isoformat() if k in rows and rows[k].uploaded_at else None,
    } for k in KINDS]


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
                              "url": adv.get("url"), "workaround": adv.get("workaround")},
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
                evidence={"article": art["id"], "url": art.get("url"), "installed": t["version"],
                          "symptom_matches": matched, "symptom_matched": bool(matched)},
                detail=("Belirti olaylarda görüldü" if matched else "Sürüm etkileniyor; belirti görülmedi"),
                cluster_name=t.get("cluster"), severity=sev,
                title=f"{art['id']}: {art['title']}"[:480],
                recommendation=str(art.get("resolution") or "Makaledeki çözümü uygulayın."),
            ))
    return out


def upgrade_findings(platform: str, collected: Dict[str, Any], matrix: Optional[Dict[str, Any]]) -> List[FindingDraft]:
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
                        evidence={"installed": t["version"], "eol_date": str(eol), "days_left": days},
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
                    evidence={"installed": t["version"], "target": target, "path": path, "hardware_blockers": blockers},
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
