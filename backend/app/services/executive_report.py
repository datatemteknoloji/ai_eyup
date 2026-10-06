"""
Yönetici raporu — tüm ortamlar (Linux, Windows, Sanallaştırma, OpenShift, Exadata) için
tek, deterministik (LLM'siz) özet rapor. Veri `executive_summary` çıktısından gelir;
Exadata ve öneriler burada eklenir. Çıktı: yapılandırılmış bölümler + Markdown.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

ENV_LABELS = {
    "linux": "Linux",
    "windows": "Windows",
    "virtualization": "Sanallaştırma",
    "openshift": "OpenShift",
    "exadata": "Exadata",
}


def _grade(score: Optional[int]) -> str:
    if score is None:
        return "—"
    if score >= 90:
        return "A"
    if score >= 75:
        return "B"
    if score >= 55:
        return "C"
    if score >= 35:
        return "D"
    return "F"


def _pct(part: int, whole: int) -> int:
    return round(part * 100 / whole) if whole else 0


def _env_rows(platforms: Dict[str, Any], exadata: Dict[str, Any]) -> List[Dict[str, Any]]:
    lin = platforms.get("linux") or {}
    win = platforms.get("windows") or {}
    vrt = platforms.get("virtualization") or {}
    ocp = platforms.get("openshift") or {}
    return [
        {
            "key": "linux", "label": ENV_LABELS["linux"],
            "inventory": f"{lin.get('server_count', 0)} sunucu",
            "monitoring": f"{lin.get('node_exporter_running', 0)}/{lin.get('server_count', 0)} node-exporter",
            "critical": lin.get("critical", 0), "warning": lin.get("warning", 0),
            "health_score": lin.get("health_score"), "grade": lin.get("grade") or _grade(lin.get("health_score")),
            "present": bool(lin.get("server_count")),
        },
        {
            "key": "windows", "label": ENV_LABELS["windows"],
            "inventory": f"{win.get('server_count', 0)} sunucu",
            "monitoring": f"{win.get('windows_exporter_running', 0)}/{win.get('server_count', 0)} windows-exporter",
            "critical": win.get("critical", 0), "warning": win.get("warning", 0),
            "health_score": win.get("health_score"), "grade": win.get("grade") or _grade(win.get("health_score")),
            "present": bool(win.get("server_count")),
        },
        {
            "key": "virtualization", "label": ENV_LABELS["virtualization"],
            "inventory": f"{vrt.get('hypervisor_count', 0)} hypervisor · {vrt.get('vm_count', 0)} VM "
                         f"({vrt.get('vm_running_count', 0)} çalışıyor)",
            "monitoring": ", ".join(vrt.get("includes") or []) or "—",
            "critical": vrt.get("critical", 0), "warning": vrt.get("warning", 0),
            "health_score": vrt.get("health_score"), "grade": vrt.get("grade") or _grade(vrt.get("health_score")),
            "present": bool(vrt.get("hypervisor_count")),
        },
        {
            "key": "openshift", "label": ENV_LABELS["openshift"],
            "inventory": f"{ocp.get('cluster_count', 0)} cluster",
            "monitoring": f"{ocp.get('unhealthy_clusters', 0)} sağlıksız cluster",
            "critical": ocp.get("critical", 0), "warning": ocp.get("warning", 0),
            "health_score": ocp.get("health_score"), "grade": ocp.get("grade") or _grade(ocp.get("health_score")),
            "present": bool(ocp.get("cluster_count")),
        },
        {
            "key": "exadata", "label": ENV_LABELS["exadata"],
            "inventory": f"{exadata.get('rack_count', 0)} rack · {exadata.get('node_count', 0)} düğüm",
            "monitoring": f"{exadata.get('racks_unhealthy', 0)} sorunlu rack",
            "critical": exadata.get("critical", 0), "warning": exadata.get("warning", 0),
            "health_score": exadata.get("health_score"), "grade": _grade(exadata.get("health_score")),
            "present": bool(exadata.get("rack_count")),
        },
    ]


def _recommendations(summary: Dict[str, Any], exadata: Dict[str, Any]) -> List[str]:
    p = summary.get("platforms") or {}
    ov = summary.get("overall") or {}
    out: List[str] = []
    if ov.get("critical_total"):
        out.append(f"{ov['critical_total']} kritik bulgu var — önce kritik olayları kapatın ('Öne çıkan bulgular').")
    lin, win = p.get("linux") or {}, p.get("windows") or {}
    n = int(lin.get("server_count") or 0)
    run = int(lin.get("node_exporter_running") or 0)
    if n and run < n:
        out.append(f"Linux izleme kapsamı %{_pct(run, n)} — {n - run} sunucuda node-exporter çalışmıyor.")
    ready = int(lin.get("ai_ready_count") or 0)
    if n and ready < n:
        out.append(f"{n - ready} Linux sunucu AI Ready değil (SSH/kimlik bilgisi kontrolü).")
    m = int(win.get("server_count") or 0)
    wrun = int(win.get("windows_exporter_running") or 0)
    if m and wrun < m:
        out.append(f"Windows izleme kapsamı %{_pct(wrun, m)} — {m - wrun} sunucuda windows-exporter çalışmıyor.")
    ocp = p.get("openshift") or {}
    if int(ocp.get("unhealthy_clusters") or 0):
        out.append(f"{ocp['unhealthy_clusters']} OpenShift cluster bağlantı/sağlık hatasında — token ve erişimi doğrulayın.")
    if int(exadata.get("racks_unhealthy") or 0):
        out.append(f"{exadata['racks_unhealthy']} Exadata rack sağlıklı değil — bağlantı ve hücre durumunu inceleyin.")
    if int(ov.get("open_incidents") or 0) > 10:
        out.append(f"{ov['open_incidents']} açık olay birikmiş — ilişkili olayları birleştirip sahiplerine atayın.")
    if not out:
        out.append("Kritik bir aksiyon gerekmiyor; düzenli kapasite ve yama gözden geçirmesine devam edin.")
    return out


def build_executive_report(summary: Dict[str, Any], exadata: Dict[str, Any]) -> Dict[str, Any]:
    ov = summary.get("overall") or {}
    envs = _env_rows(summary.get("platforms") or {}, exadata)
    alerts = (summary.get("top_alerts") or [])[:15]
    incidents = (summary.get("open_incident_items") or [])[:20]
    recs = _recommendations(summary, exadata)

    md: List[str] = []
    md.append("# Yönetici Raporu — Tüm Ortamlar")
    md.append(f"_Oluşturulma: {summary.get('generated_at', '')} (UTC)_\n")
    md.append("## Genel durum")
    md.append(
        f"- Sağlık skoru: **{ov.get('health_score', '—')}** ({ov.get('grade', '—')} — {ov.get('label', '')})\n"
        f"- Kritik bulgu: **{ov.get('critical_total', 0)}** · Uyarı: **{ov.get('warning_total', 0)}**\n"
        f"- Açık olay: **{ov.get('open_incidents', 0)}** · Toplam sunucu (Linux+Windows): **{ov.get('total_servers', 0)}**\n"
    )
    md.append("## Ortamlar")
    md.append("| Ortam | Envanter | İzleme | Kritik | Uyarı | Skor |")
    md.append("|---|---|---|---:|---:|---|")
    for e in envs:
        if not e["present"] and not (e["critical"] or e["warning"]):
            md.append(f"| {e['label']} | — | — | 0 | 0 | — |")
            continue
        score = e["health_score"] if e["health_score"] is not None else "—"
        md.append(
            f"| {e['label']} | {e['inventory']} | {e['monitoring']} | {e['critical']} | {e['warning']} | "
            f"{score} ({e['grade']}) |"
        )
    md.append("\n## Öne çıkan bulgular")
    if alerts:
        for a in alerts:
            plat = ENV_LABELS.get(a.get("platform") or "", a.get("platform") or "")
            md.append(f"- [{(a.get('severity') or '').upper()}] {plat} — {a.get('server_name') or '—'}: {a.get('title') or ''}")
    else:
        md.append("- Aktif kritik/uyarı bulgusu yok.")
    md.append("\n## Açık olaylar")
    if incidents:
        for i in incidents:
            plat = ENV_LABELS.get(i.get("platform") or "", i.get("platform") or "")
            md.append(f"- #{i.get('id')} [{(i.get('severity') or '').upper()}] {plat} — {i.get('title') or ''} "
                      f"({i.get('server_name') or '—'})")
    else:
        md.append("- Açık olay yok.")
    md.append("\n## Öneriler")
    md.extend(f"{n}. {r}" for n, r in enumerate(recs, 1))

    return {
        "generated_at": summary.get("generated_at"),
        "overall": ov,
        "environments": envs,
        "top_alerts": alerts,
        "open_incidents": incidents,
        "recommendations": recs,
        "markdown": "\n".join(md) + "\n",
    }
