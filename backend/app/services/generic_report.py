"""Ortak rapor şeması — OpenShift ve Yönetici hazır raporları için.

Mevcut ekip raporlarının (Sanallaştırma/Linux/Windows/Exadata) çıktısı değişmez; bu şema yalnız
yeni raporlar içindir. UI tek bir görsel (`GenericReportView`) ile hepsini çizer:

    {
      "view": "generic", "platform", "report_type", "title", "generated_at",
      "kpis":     [{"label", "value", "sub", "tone"}],
      "sections": [{"title", "module", "status", "kpis", "columns", "rows", "note"}],
      "recommendations": [str], "notes": [str],
      "excluded": [{"module", "reason"}],      # yönetici: kapsam dışı modül + neden
      "methodology": str
    }

`status`: ok | unmeasured (veri yok / yetersiz — sayı uydurulmaz) | excluded.
`tone`: ok | warn | crit | info | muted (UI renk ipucu).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional, Sequence

from app.core.timeutil import utc_now

TONES = ("ok", "warn", "crit", "info", "muted")


def kpi(label: str, value: Any, sub: Optional[str] = None, tone: str = "info") -> Dict[str, Any]:
    return {"label": label, "value": value, "sub": sub, "tone": tone if tone in TONES else "info"}


def table(
    title: str,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    note: Optional[str] = None,
    module: Optional[str] = None,
    status: str = "ok",
    kpis: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "title": title,
        "module": module,
        "status": status,
        "kpis": kpis or [],
        "columns": list(columns),
        "rows": [list(r) for r in rows],
        "note": note,
    }


def unmeasured(title: str, reason: str, *, module: Optional[str] = None) -> Dict[str, Any]:
    """Veri yok / yetersiz: bölüm görünür ama rakam yazılmaz."""
    return {"title": title, "module": module, "status": "unmeasured", "kpis": [],
            "columns": [], "rows": [], "note": reason}


def make_report(
    platform: str,
    report_type: str,
    title: str,
    *,
    kpis: Optional[List[Dict[str, Any]]] = None,
    sections: Optional[List[Dict[str, Any]]] = None,
    recommendations: Optional[List[str]] = None,
    notes: Optional[List[str]] = None,
    excluded: Optional[List[Dict[str, str]]] = None,
    methodology: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "view": "generic",
        "platform": platform,
        "report_type": report_type,
        "title": title,
        "generated_at": utc_now().isoformat(),
        "kpis": kpis or [],
        "sections": sections or [],
        "recommendations": recommendations or [],
        "notes": notes or [],
        "excluded": excluded or [],
        "methodology": methodology or "",
    }
    if extra:
        out.update(extra)
    return out


def pct(part: float, whole: float, ndigits: int = 1) -> Optional[float]:
    return round(100.0 * part / whole, ndigits) if whole else None


def r1(v: Any, n: int = 1) -> Optional[float]:
    try:
        return None if v is None else round(float(v), n)
    except (TypeError, ValueError):
        return None


def tone_for_pct(value: Optional[float], warn: float = 70.0, crit: float = 85.0) -> str:
    if value is None:
        return "muted"
    if value >= crit:
        return "crit"
    if value >= warn:
        return "warn"
    return "ok"


def _cell(v: Any, lang: str = "tr") -> str:
    if v is None or v == "":
        return "—"
    if isinstance(v, bool):
        return ("Yes" if v else "No") if lang == "en" else ("Evet" if v else "Hayır")
    if isinstance(v, float):
        return f"{v:.1f}".rstrip("0").rstrip(".") if v != int(v) else str(int(v))
    return str(v).replace("|", "\\|").replace("\n", " ")


def _tm(module: Any, lang: str) -> Any:
    from app.services.report_i18n import t as _t

    return _t(module, lang)


def _kpi_line(k: Dict[str, Any], lang: str = "tr") -> str:
    """«- **Etiket:** değer — alt metin» (alt metin «/N» ise «değer /N» — «2 — /2» okunmaz)."""
    sub = k.get("sub")
    val = _cell(k.get("value"), lang)
    if not sub:
        return f"- **{k['label']}:** {val}"
    if str(sub).startswith("/"):
        return f"- **{k['label']}:** {val} {sub}"
    return f"- **{k['label']}:** {val} — {sub}"


def to_markdown(data: Dict[str, Any], *, scope: str, report_type: str, lang: str = "tr") -> str:
    """Genel şemadan Markdown. Yöntem notları `method_registry`den üretilir. `lang="en"` → içerik İngilizce."""
    from app.services.report_i18n import md_label as L, translate_report

    data = translate_report(data, lang)
    title = data.get("title") or report_type
    ts = (data.get("generated_at") or "")[:16]
    lines: List[str] = [f"# {title}", f"*{L(lang, 'created')}: {ts} (UTC)*", ""]
    kpis = data.get("kpis") or []
    if kpis:
        for k in kpis:
            lines.append(_kpi_line(k, lang))
        lines.append("")
    for sec in data.get("sections") or []:
        head = sec.get("title") or ""
        if sec.get("module"):
            head = f"{_tm(sec['module'], lang)} — {head}"
        lines.append(f"## {head}")
        if sec.get("status") == "unmeasured":
            lines.append(f"_{L(lang, 'unmeasured')}: {sec.get('note') or L(lang, 'no_data')}_")
            lines.append("")
            continue
        for k in sec.get("kpis") or []:
            lines.append(_kpi_line(k, lang))
        cols = sec.get("columns") or []
        rows = sec.get("rows") or []
        if cols and rows:
            lines.append("")
            lines.append("| " + " | ".join(str(c) for c in cols) + " |")
            lines.append("| " + " | ".join("---" for _ in cols) + " |")
            for row in rows:
                lines.append("| " + " | ".join(_cell(c, lang) for c in row) + " |")
        if sec.get("note"):
            lines.append("")
            lines.append(f"_{sec['note']}_")
        lines.append("")
    excluded = data.get("excluded") or []
    if excluded:
        lines.append(f"## {L(lang, 'excluded')}")
        for e in excluded:
            lines.append(f"- **{_tm(e.get('module'), lang)}:** {e.get('reason')}")
        lines.append("")
    recs = data.get("recommendations") or []
    if recs:
        lines.append(f"## {L(lang, 'recs')}")
        lines.extend(f"{i}. {r}" for i, r in enumerate(recs, 1))
        lines.append("")
    for n in data.get("notes") or []:
        lines.append(f"*{n}*")
    if data.get("methodology"):
        lines.append("")
        lines.append(f"**{L(lang, 'method')}:** {data['methodology']}")
    from app.services.report_method_notes import method_notes_markdown

    return "\n".join(lines) + "\n" + method_notes_markdown(scope, report_type, lang=lang)


def to_chat_markdown(data: Dict[str, Any], *, max_rows: int = 8, full_hint: str = "", lang: str = "tr") -> str:
    """Sohbet için KISA özet: başlık, KPI'lar, bölümlerin ilk `max_rows` satırı, öneriler.

    Rakamların tamamı motordan gelir (LLM yok). Tam liste ve yöntem notları Hazır Raporlar sayfasındadır.
    """
    from app.services.report_i18n import md_label as L, translate_report

    data = translate_report(data, lang)
    title = data.get("title") or data.get("report_type") or ("Report" if lang == "en" else "Rapor")
    ts = (data.get("generated_at") or "")[:16].replace("T", " ")
    lines: List[str] = [f"## {title}", f"*{L(lang, 'created')}: {ts} (UTC)*", ""]
    for k in data.get("kpis") or []:
        lines.append(_kpi_line(k, lang))
    if data.get("kpis"):
        lines.append("")
    for sec in data.get("sections") or []:
        head = sec.get("title") or ""
        if sec.get("module"):
            head = f"{_tm(sec['module'], lang)} — {head}"
        lines.append(f"### {head}")
        if sec.get("status") == "unmeasured":
            lines.append(f"_{L(lang, 'unmeasured')}: {sec.get('note') or L(lang, 'no_data')}_")
            lines.append("")
            continue
        for k in sec.get("kpis") or []:
            lines.append(_kpi_line(k, lang))
        cols = sec.get("columns") or []
        rows = sec.get("rows") or []
        if cols and rows:
            lines.append("")
            lines.append("| " + " | ".join(str(c) for c in cols) + " |")
            lines.append("| " + " | ".join("---" for _ in cols) + " |")
            for row in rows[:max_rows]:
                lines.append("| " + " | ".join(_cell(c, lang) for c in row) + " |")
            if len(rows) > max_rows:
                lines.append("")
                lines.append("_" + L(lang, "shown").format(n=max_rows, t=len(rows)) + "_")
        elif not (sec.get("kpis") or sec.get("note")):
            lines.append(f"_{L(lang, 'no_rows')}_")
        if sec.get("note"):
            lines.append("")
            lines.append(f"_{sec['note']}_")
        lines.append("")
    excluded = data.get("excluded") or []
    if excluded:
        lines.append(f"### {L(lang, 'excluded')}")
        for e in excluded:
            lines.append(f"- **{_tm(e.get('module'), lang)}:** {e.get('reason')}")
        lines.append("")
    recs = data.get("recommendations") or []
    if recs:
        lines.append(f"### {L(lang, 'recs')}")
        lines.extend(f"{i}. {r}" for i, r in enumerate(recs[:6], 1))
        lines.append("")
    if full_hint:
        lines.append(full_hint)
    return "\n".join(lines).rstrip() + "\n"
