"""
NLQ response formatter — Markdown from DB rows only (no LLM invented facts).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _fmt(v: Any) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:.1f}" if v != int(v) else str(int(v))
    return str(v)


def format_answer(
    question: str,
    validated: dict,
    exec_result: dict,
    *,
    live_diff: Optional[List[dict]] = None,
) -> str:
    summary = exec_result.get("summary") or {}
    results: List[dict] = exec_result.get("results") or []
    filters = validated.get("filters") or []

    filter_parts = []
    for f in filters:
        filter_parts.append(f"{f.get('field')} {f.get('operator')} {f.get('value')}")
    filter_txt = ", ".join(filter_parts) if filter_parts else "(filtre yok)"

    total = summary.get("total_found", len(results))
    lines = [
        f"**{total}** sunucu bulundu.",
        "",
        f"- Son veri toplama: {_fmt(summary.get('latest_collection_time'))}",
        f"- Erişilemeyen / eksik envanter: {summary.get('unreachable_count', 0)}",
        f"- Başarısız toplama: {summary.get('failed_collection_count', 0)}",
        f"- Verisi {summary.get('stale_threshold_minutes', 30)} dk’dan eski: {summary.get('stale_data_count', 0)}",
        f"- Kullanılan filtreler: `{filter_txt}`",
        "",
    ]

    if summary.get("unreachable_count") or summary.get("stale_data_count") or summary.get("failed_collection_count"):
        lines.append(
            "_Not: Eksik/eski satırlar collector turuna veya SSH erişimine bağlıdır; "
            "hostname/sayı uydurulmaz. Collector: `/collectors/linux-inventory/run`._"
        )
        lines.append("")

    if not results:
        lines.append("_Sonuç bulunamadı (filtreye uyan envanter satırı yok veya henüz toplanmadı)._")
        return "\n".join(lines)

    cols = validated.get("requested_columns") or [
        "hostname", "ip_address", "environment", "uptime_days",
        "boot_time", "collection_time", "collection_status",
    ]
    # Prefer readable header for uptime_days
    header = " | ".join(cols)
    sep = " | ".join(["---"] * len(cols))
    lines.append(header)
    lines.append(sep)
    for row in results:
        lines.append(" | ".join(_fmt(row.get(c)) for c in cols))

    if live_diff:
        lines.append("")
        lines.append("### Canlı doğrulama farkları")
        lines.append("Hostname | Alan | Envanter | Canlı")
        lines.append("--- | --- | --- | ---")
        for d in live_diff:
            lines.append(
                f"{_fmt(d.get('hostname'))} | {_fmt(d.get('field'))} | "
                f"{_fmt(d.get('inventory'))} | {_fmt(d.get('live'))}"
            )

    return "\n".join(lines)
