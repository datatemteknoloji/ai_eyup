"""'Neden hata verdi / rapordan neden' soruları için KOD üretimli cevap iskeleti (Adım 7c).

Cevap iki bölümden oluşur:
  1. **Gözlemler** — tamamen araç sonuçlarından KOD üretir (nesne, RunID, zaman, durum, return code, rapordaki hata satırları,
     `return_code_note`, `known_error_codes` açıklaması + kaynak). Model bu bölümü yazmaz.
  2. **Değerlendirme (yorum, doğrulanmamış)** — başlığı kod ekler; modelin serbest metni bu başlığın altına akar.

Gözlemler araçlar bittiğinde hemen (model düşünürken) akıtılır; değerlendirme model ürettikçe akar.
Hata kanıtı (hatalı çalışma / rapor hata satırı) yoksa bölüm üretilmez → normal cevap yolu.
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.automic.tr_grammar import tr_n_si

from app.services.automic.error_codes import (
    RETURN_CODE_NOTE, STATUS_CODE_NOTE, STATUS_CODE_NOTE_EN, find_known_codes,
    INJECTION_WARN_TR, INJECTION_WARN_EN, find_injection_lines,
)
OBS_HEADING = {"tr": "### Gözlemler (araç verisi — sistem yazdı)", "en": "### Observations (tool data — written by the system)"}
MISSING_HEADING = {"tr": "### Kanıt yok — önce veri toplayın", "en": "### No evidence — gather data first"}
EVAL_HEADING = {"tr": "### Değerlendirme (yorum, doğrulanmamış)", "en": "### Assessment (interpretation, unverified)"}
# kalite kontrolü / UI bu başlıkları tanır
EVAL_HEADING_RE = re.compile(r"^#{2,4}\s*(?:Değerlendirme\s*\(yorum, doğrulanmamış\)|Assessment\s*\(interpretation, unverified\))\s*$", re.M)
OBS_HEADING_RE = re.compile(r"^#{2,4}\s*(?:Gözlemler|Observations)\b.*$", re.M)

# "sebebi" = sebep + ünlü yumuşaması (p→b); "sebep\w*" "sebebi"yi yakalamaz
_WHY_RE = re.compile(
    r"\b(neden\w*|niçin|niye|sebeb\w*|sebep\w*|why|root\s+cause)\b|kök\s+neden"
    r"|\b(?:sorun|problem|hata)\w*\s+ne(?:ydi|dir)\b|\bne\s+oldu\b|what\s+went\s+wrong|what\s+was\s+the\s+(?:problem|issue)",
    re.IGNORECASE,
)
_LINE_RE = re.compile(r"(ERROR|FATAL|WARN(?:ING)?|EXCEPTION|ABEND|FAILED|ORA-\d{3,5}|SQLSTATE|aborted|return code|timed out|denied)", re.I)

_CLASS_TR = {"failed": "hatalı", "ok": "başarılı", "cancelled": "iptal", "running": "çalışıyor", "waiting": "bekliyor",
             "blocked": "bloke"}

_L = {
    "tr": {"summary": "Özet", "runs": "Hatalı çalışmalar", "run": "RunID", "state": "durum kodu", "start": "zaman", "agent": "agent",
           "rc": "dönüş kodu (return code)", "report": "Rapor", "report_lines": "hata satırları", "sig": "Hata imzası",
           "rc_note": "Dönüş kodu", "sc_note": "Durum kodu", "info": "Genel bilgi", "src": "Kaynak",
           "info_tail": "(sistem sözlüğünden; ortam verisi değil)",
           "total": "toplam", "failed": "hatalı", "rate": "hata oranı", "dur": "süre", "avg": "ort.", "max": "maks", "min": "min",
           "longest": "En uzun", "shortest": "En kısa", "listed_below": "Aşağıda hatalı çalışmalar listeleniyor."},
    "en": {"summary": "Summary", "runs": "Failed runs", "run": "RunID", "state": "status code", "start": "time", "agent": "agent",
           "rc": "return code", "report": "Report", "report_lines": "error lines", "sig": "Error signature",
           "rc_note": "Return code", "sc_note": "Status code", "info": "General information", "src": "Source",
           "info_tail": "(from the system dictionary; not environment data)",
           "total": "total", "failed": "failed", "rate": "failure rate", "dur": "duration", "avg": "avg", "max": "max", "min": "min",
           "longest": "Longest", "shortest": "Shortest", "listed_below": "Failed runs are listed below."},
}
_RC_NOTE_EN = ("The meaning of this return code is specific to the program/script that was run; it has no general meaning in Automic.")


def _universe_of(res: Dict[str, Any]) -> Dict[str, Any]:
    """Filtresiz toplamlar — yoksa rates/total'dan güvenli türetme (filtreli %100 tuzağına düşmeden)."""
    u = res.get("universe") if isinstance(res.get("universe"), dict) else None
    if u and u.get("runs_total") is not None:
        return u
    if res.get("runs_total") is not None:
        return {
            "runs_total": int(res["runs_total"]),
            "failed_total": int(res.get("failed_total") or 0),
            "failure_rate_pct": res.get("failure_rate_pct"),
            "distinct_objects_total": res.get("distinct_objects_total"),
            "distinct_objects_failed": res.get("distinct_objects_failed"),
        }
    # runs_ignoring_status_filter (eski alan) — filtresiz toplam
    ign = res.get("runs_ignoring_status_filter")
    if isinstance(ign, dict) and ign.get("total") is not None:
        cnt = ign.get("counts") or {}
        n = int(ign["total"])
        failed = int(cnt.get("failed") or 0)
        rate = (res.get("rates") or {}).get("failure_rate_pct")
        if rate is None and n:
            rate = round(100.0 * failed / n, 2)
        return {"runs_total": n, "failed_total": failed, "failure_rate_pct": rate}
    # Geriye dönük: durum filtresi yoksa total ≈ runs_total
    if not (res.get("filtered_by") or {}).get("status_class"):
        n = res.get("total")
        if isinstance(n, int):
            failed = (res.get("counts") or {}).get("failed")
            rate = (res.get("rates") or {}).get("failure_rate_pct")
            return {"runs_total": n, "failed_total": failed, "failure_rate_pct": rate}
    return {}

def _fmt_rate(v: Any) -> str:
    try:
        return f"{float(v):g}".replace(".", ",")
    except (TypeError, ValueError):
        return str(v)


def _summary_line(res: Dict[str, Any], lab: Dict[str, str], english: bool, tz: Any) -> str:
    u = _universe_of(res)
    bits = []
    if u.get("runs_total") is not None:
        n, f = int(u["runs_total"]), int(u.get("failed_total") or 0)
        rate = u.get("failure_rate_pct")
        if english:
            bits.append(f"In this period: {n} runs total; {f} failed"
                        + (f" ({_fmt(rate)}%)" if rate is not None else "") + ".")
        else:
            from app.services.automic.tr_grammar import tr_n_si
            bits.append(f"Bu dönemde toplam {n} çalışma; {tr_n_si(f)} hatalı"
                        + (f" (%{_fmt_rate(rate)})" if rate is not None else "") + ".")
        bits.append(lab["listed_below"])
        if u.get("distinct_objects_total") is not None:
            if english:
                bits.append(f"(runs={n}; distinct jobs={u['distinct_objects_total']}; "
                            f"distinct failing jobs={u.get('distinct_objects_failed') or 0})")
            else:
                bits.append(f"(çalışma sayısı={n}; farklı job={u['distinct_objects_total']}; "
                            f"hata veren farklı job={u.get('distinct_objects_failed') or 0})")
    else:
        # son çare — oran yazma
        if res.get("total") is not None:
            bits.append(f"{lab['total']} {res['total']} (filtreli liste; oran hesaplanmadı)")
    ds = res.get("duration_stats") or {}
    if ds.get("avg_duration_sec") is not None:
        from app.services.chat_llm_context import fmt_duration
        bits.append(f"{lab['dur']} {lab['avg']} {fmt_duration(ds['avg_duration_sec'])}"
                    f" ({lab['min']} {fmt_duration(ds.get('min_duration_sec'))}, {lab['max']} {fmt_duration(ds.get('max_duration_sec'))})")
    if res.get("from") and res.get("to"):
        bits.append(f"{_local(res['from'], tz)} → {_local(res['to'], tz)}")
    if res.get("partial_coverage_note"):
        bits.append(str(res["partial_coverage_note"]))
    return " ".join(bits)

MAX_RUNS = 6
MAX_REPORT_LINES = 6


def is_why_question(message: str) -> bool:
    return bool(_WHY_RE.search(message or ""))


def _inline(s: Any, limit: int = 220) -> str:
    return str(s).replace("`", "'").replace("\n", " ").strip()[:limit]


def _local(v: Any, tz: Any) -> str:
    if not v:
        return ""
    from app.services.chat_llm_context import _to_local
    return _to_local(str(v), tz) or str(v)


def _fmt(x: Any) -> str:
    try:
        return f"{float(x):g}"
    except (TypeError, ValueError):
        return str(x)


def _run_line(row: Dict[str, Any], tz: Any, lab: Dict[str, str]) -> str:
    from app.services.chat_llm_context import fmt_duration
    parts = [f"`{lab['run']} {row.get('run_id')}`"]
    if row.get("object_name"):
        parts.append(f"`{_inline(row['object_name'], 80)}`")
    cls = str(row.get("status_class") or "")
    state = f"{lab['state']} {row.get('status_code')}" if row.get("status_code") is not None else lab["state"]
    parts.append(f"{state} ({_CLASS_TR.get(cls, cls) if lab is _L['tr'] else cls})" if cls else state)
    if row.get("return_code") is not None:
        parts.append(f"{lab['rc']} {row['return_code']}")
    st, en = _local(row.get("start_time"), tz), _local(row.get("end_time"), tz)
    if st or en:
        dur = fmt_duration(row.get("duration_sec")) if row.get("duration_sec") is not None else ""
        parts.append(f"{st} → {en}" + (f" ({dur})" if dur else ""))
    if row.get("agent"):
        parts.append(f"{lab['agent']} {_inline(row['agent'], 40)}")
    return "- " + " · ".join(parts)


def _failed_rows(res: Dict[str, Any]) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for r in res.get("items") or []:
        if isinstance(r, dict) and r.get("run_id") and str(r.get("status_class")) == "failed":
            rows.append(r)
    ex = res.get("execution")
    if isinstance(ex, dict) and ex.get("run_id") and str(ex.get("status_class")) == "failed":
        rows.append(ex)
    return rows


def _report_lines(content: str) -> List[str]:
    out: List[str] = []
    for ln in (content or "").splitlines():
        if _LINE_RE.search(ln) and ln.strip() not in out:
            out.append(ln.strip())
    return out[-MAX_REPORT_LINES:]


def is_why_without_evidence(structured: List[Dict[str, Any]]) -> bool:
    """'Neden' sorusu için hatalı çalışma / rapor hata satırı kanıtı yok."""
    return not build_blocks(structured)


def missing_evidence_blocks(structured: List[Dict[str, Any]], english: bool = False) -> List[Tuple[str, str]]:
    """Eksik kanıt parçalarını ve nasıl toplanacağını açıklayan (anahtar, markdown) blokları."""
    failed_rows: List[Dict[str, Any]] = []
    has_report = False
    has_report_tool = False
    for sr in structured or []:
        if not isinstance(sr, dict):
            continue
        tool = sr.get("tool") or ""
        res = sr.get("result")
        if not isinstance(res, dict) or res.get("ok") is False:
            continue
        failed_rows.extend(_failed_rows(res))
        args = sr.get("args") or {}
        if tool == "automic_execution" and (args.get("aspect") or "").lower() == "report":
            has_report_tool = True
            if isinstance(res.get("content"), str) and res.get("content", "").strip():
                has_report = True
    blocks: List[Tuple[str, str]] = []
    if not failed_rows:
        if english:
            blocks.append(("need_failed", (
                "- No **failed run** was found in the tool results. Ask for failed runs of a named job "
                "or a time range (e.g. last night), or open a specific RunID."
            )))
        else:
            blocks.append(("need_failed", (
                "- Araç sonuçlarında **hatalı çalışma** yok. Belirli bir job adı veya zaman aralığı "
                "(ör. dün gece) ile hatalı çalışmaları sorun; ya da belirli bir RunID'yi açın."
            )))
    if failed_rows and not has_report:
        rid = failed_rows[0].get("run_id")
        if english:
            blocks.append(("need_report", (
                f"- Failed run **`RunID {rid}`** is listed but no report error lines were loaded. "
                "Ask to show the report for this RunID."
            )))
        else:
            blocks.append(("need_report", (
                f"- Hatalı çalışma **`RunID {rid}`** görünüyor ama rapor/hata satırı yüklenmedi. "
                "Bu RunID'nin raporunu göstermemi isteyin."
            )))
    if has_report_tool and not has_report and not failed_rows:
        if english:
            blocks.append(("report_empty", (
                "- A report was requested but returned empty. The run may be successful (reports are not stored "
                "without live read) or the collector excerpt may be missing for a failed run."
            )))
        else:
            blocks.append(("report_empty", (
                "- Rapor istendi ama içerik gelmedi. Çalışma başarılı olabilir (canlı okuma kapalıyken rapor "
                "saklanmaz) veya hatalı çalışma için collector kırpıntısı henüz toplanmamış olabilir."
            )))
    if not blocks:
        tail = ("Without failed-run and report evidence, a root-cause list cannot be written."
                if english else "Hatalı çalışma ve rapor kanıtı olmadan kök neden listesi yazılamaz.")
        blocks.append(("generic", f"- {tail}"))
    blocks.append(("no_eval", (
        "_Assessment is skipped until the observations above are available._"
        if english else "_Yukarıdaki kanıtlar toplanana kadar olası neden değerlendirmesi yapılmaz._"
    )))
    return blocks


def missing_evidence_markdown(structured: List[Dict[str, Any]], tz: Any = None, english: bool = False) -> str:
    """Kanıt yokken kullanıcıya gösterilecek tam Markdown (model değerlendirmesi yok)."""
    _ = tz
    parts = [MISSING_HEADING["en" if english else "tr"]]
    for _, text in missing_evidence_blocks(structured, english):
        parts.append(text)
    return "\n\n".join(parts) + "\n"


def build_blocks(structured: List[Dict[str, Any]], tz: Any = None, english: bool = False) -> List[Tuple[str, str]]:
    """Araç sonuçlarından sıralı (anahtar, markdown) blokları. Hata kanıtı yoksa boş liste.

    Anahtarlar tekrar çağrılarda aynıdır → çağıran yalnız yeni anahtarları akıtır (artımlı gösterim).
    """
    lab = _L["en" if english else "tr"]
    from datetime import timezone
    tz = tz or timezone.utc
    summaries: List[Tuple[str, str]] = []
    runs: List[Tuple[str, str]] = []
    seen_runs = set()
    reports: List[Tuple[str, str]] = []
    sigs: List[Tuple[str, str]] = []
    any_rc = False
    code_blob: List[str] = []
    for i, sr in enumerate(structured or []):
        res = sr.get("result") if isinstance(sr, dict) else None
        if not isinstance(res, dict) or res.get("ok") is False:
            continue
        rows = _failed_rows(res)
        if rows and res.get("items") is not None and (
                res.get("total") is not None or res.get("summary") or res.get("runs_total") is not None):
            line = _summary_line(res, lab, english, tz)
            if line:
                summaries.append((f"sum:{i}", f"**{lab['summary']}:** {line}"))
        for r in rows:
            rid = r.get("run_id")
            if rid in seen_runs or len(seen_runs) >= MAX_RUNS:
                continue
            seen_runs.add(rid)
            runs.append((f"run:{rid}", _run_line(r, tz, lab)))
            if r.get("return_code") not in (None, 0):
                any_rc = True
            code_blob.append(str(r.get("error_signature") or ""))
        sig = res.get("error_signature")
        if sig and res.get("content") is None:
            sigs.append((f"sig:{_inline(sig, 60)}", f"**{lab['sig']}:** `{_inline(sig)}`"))
            code_blob.append(str(sig))
        content = res.get("content")
        if isinstance(content, str) and content.strip():
            args = sr.get("args") or {}
            rid = args.get("run_id") or res.get("run_id")
            obj = args.get("object_name") or res.get("object_name") or ""
            lines = _report_lines(content)
            sg = res.get("error_signature")
            if lines or sg:
                body = "\n".join(f"- `{_inline(ln)}`" for ln in lines) if lines else f"- `{_inline(sg)}`"
                rtype = res.get("report_type") or ""
                head = f"**{lab['report']}** ({lab['run']} {rid}"
                if obj:
                    head += f", `{_inline(obj, 60)}`"
                head += f", {rtype})" if rtype else ")"
                reports.append((f"rep:{rid}:{len(lines)}", f"{head} — {lab['report_lines']}:\n{body}"))
                code_blob.append("\n".join(lines))
                if re.search(r"return code\s*[1-9]\d*", content, re.I):
                    any_rc = True
                if sg:
                    code_blob.append(str(sg))
    if not runs and not reports:
        return []
    blocks: List[Tuple[str, str]] = []
    blocks.extend(summaries)
    if runs:
        blocks.append(("runs_head", f"**{lab['runs']}:**"))
        blocks.extend(runs)
    # Hata imzası dağılımı — araçtaki GERÇEK dağılım (automic_failed_index JOIN); listelenen satırlarda
    # alan yok diye "rapor yok" sayılmaz (eski sayaç listenin uzunluğunu "rapor yok" diye yazıyordu).
    from collections import Counter
    sig_counts: Counter = Counter()
    item_sig_counts: Counter = Counter()
    coverage_note = ""
    unavailable_note = ""
    for sr in structured or []:
        res = sr.get("result") if isinstance(sr, dict) else None
        if not isinstance(res, dict):
            continue
        for r in _failed_rows(res):
            sg = (r.get("error_signature") or "").strip()
            if sg:
                item_sig_counts[sg[:160]] += 1
        for d in res.get("error_signature_distribution") or []:
            if not isinstance(d, dict) or not d.get("signature"):
                continue
            sg = str(d["signature"])[:160]
            if "rapor" in sg.lower() and "yok" in sg.lower():
                continue  # eski biçim: gerçek imza değil
            sig_counts[sg] += int(d.get("count") or 1)
        rc = res.get("report_coverage")
        if isinstance(rc, dict) and rc.get("failed_total"):
            tot, wr, wo = int(rc["failed_total"]), int(rc.get("with_report") or 0), int(rc.get("without_report") or 0)
            pct = rc.get("coverage_pct")
            if english:
                coverage_note = (f"**Report coverage:** {wr} of {tot} failed runs have a report excerpt"
                                 + (f" ({_fmt(pct)}%)" if pct is not None else "")
                                 + (f"; {wo} not collected yet." if wo else "."))
            else:
                pend, una = int(rc.get("pending_report") or 0), int(rc.get("report_unavailable") or 0)
                tail = []
                if pend:
                    tail.append(f"{pend} tanesi henüz toplanmadı")
                if una:
                    tail.append(f"{una} tanesi için kaynakta rapor alınamadı")
                coverage_note = (f"**Rapor kapsamı:** {tot} hatalı çalışmanın {wr} tanesinde rapor kırpıntısı var"
                                 + (f" (%{_fmt_rate(pct)})" if pct is not None else "")
                                 + ("; " + ", ".join(tail) + "." if tail else "."))
        if res.get("unavailable"):
            lst = ", ".join(str(x) for x in res["unavailable"])
            unavailable_note = (f"**Information not available:** {lst} could not be retrieved (this is not a zero)."
                                if english else
                                f"**Alınamayan bilgi:** {lst} sorgusu başarısız oldu; bu bilgi alınamadı (sıfır veya \"rapor yok\" anlamına gelmez).")
    if not sig_counts:
        sig_counts = item_sig_counts
    if sig_counts:
        top_sigs = sig_counts.most_common(8)
        if english:
            dist_txt = ", ".join(f"`{_inline(s, 80)}`: {c}" for s, c in top_sigs)
            blocks.append(("sig_dist", f"**Error signature distribution:** {dist_txt}"))
        else:
            dist_txt = ", ".join(f"`{_inline(s, 80)}`: {c}" for s, c in top_sigs)
            blocks.append(("sig_dist", f"**Hata imzası dağılımı:** {dist_txt}"))
        for s, _c in top_sigs:
            code_blob.append(s)
    if coverage_note:
        blocks.append(("rep_cov", coverage_note))
    if unavailable_note:
        blocks.append(("unavail", unavailable_note))
    blocks.extend(sigs if not reports else [])
    # Her rapor ayrı blok — model "aynısı" genellemesi yapamasın
    blocks.extend(reports)
    # Enjeksiyon uyarısı (talimat benzeri satır — uygulanmaz)
    inj_hits = find_injection_lines("\n".join(code_blob))
    for sr in structured or []:
        res = sr.get("result") if isinstance(sr, dict) else None
        if isinstance(res, dict):
            inj_hits.extend(res.get("injection_suspect_lines") or [])
            if isinstance(res.get("content"), str):
                inj_hits.extend(find_injection_lines(res["content"]))
    if inj_hits:
        note = INJECTION_WARN_EN if english else INJECTION_WARN_TR
        blocks.append(("inject_warn", f"**{'Warning' if english else 'Uyarı'}:** {note}"))
    if any_rc:
        blocks.append(("rc_note", f"**{lab['rc_note']}:** " + (_RC_NOTE_EN if english else RETURN_CODE_NOTE)))
    blocks.append(("sc_note", f"**{lab['sc_note']}:** " + (STATUS_CODE_NOTE_EN if english else STATUS_CODE_NOTE)))
    codes = find_known_codes("\n".join(code_blob))
    if codes:
        lines = "\n".join(f"- **{c['code']}** — {c['text']} _({lab['src']}: {c['source']})_" for c in codes[:6])
        blocks.append((f"codes:{','.join(c['code'] for c in codes[:6])}", f"**{lab['info']}:** {lab['info_tail']}\n{lines}"))
    return blocks


class Streamer:
    """Gözlemleri artımlı, değerlendirme başlığını bir kez akıtmak için durum tutar (istek başına bir tane)."""

    def __init__(self, english: bool = False, tz: Any = None) -> None:
        self.english = english
        self.tz = tz
        self.emitted: set = set()
        self.head_done = False
        self.eval_done = False
        self.last = ""

    @property
    def engaged(self) -> bool:
        return self.head_done

    def _sep(self, text: str) -> str:
        """Liste maddeleri arasında tek satır sonu (sıkı liste), diğer bloklar arasında boş satır."""
        prev = self.last
        if prev and text.startswith("- ") and (prev.startswith("- ") or prev.rstrip().endswith(":**") or prev.rstrip().endswith(":")):
            return "\n"
        return "\n\n"

    def new_text(self, structured: List[Dict[str, Any]]) -> str:
        """Henüz akıtılmamış gözlem blokları (başlık dahil); yoksa ''."""
        blocks = build_blocks(structured, self.tz, self.english)
        out = ""
        for key, text in blocks:
            if key in self.emitted:
                continue
            if not self.head_done:
                out += OBS_HEADING["en" if self.english else "tr"]
                self.head_done = True
            out += self._sep(text) + text
            self.last = text
            self.emitted.add(key)
        return out

    def eval_heading(self) -> str:
        """Gözlem akıtıldıysa ve başlık henüz yazılmadıysa değerlendirme başlığı."""
        if self.head_done and not self.eval_done:
            self.eval_done = True
            return "\n\n" + EVAL_HEADING["en" if self.english else "tr"] + "\n\n"
        return ""


_BULLET_RE = re.compile(r"^(?:[-*•]\s+|\d+[.)]\s+)")
_HEDGE = re.compile(r"olası|muhtemel|olabilir|ihtimal|possible|likely|\bmay\b|\bmight\b|\bcould\b", re.I)
_TS = re.compile(r"\d{4}-\d{2}-\d{2}[ T]\d{2}:\d{2}|\b\d{9,}\b")
_KEEP_HEAD = re.compile(r"(?i)^(düzeltme|correction)\s*:")
_CONF = re.compile(r"(?i)^(güven|confidence)\b")
_CONF_MED_HI = re.compile(r"(?i)\b(orta|yüksek|medium|high)\b")
_CLAIM_N = re.compile(
    r"(?i)(?:dün\s+)?(\d+)\s*kez\s+hata|(\d+)\s*times?\s+fail|hata\s+oran[ıi]\s*%?\s*(\d+)|"
    r"%\s*(\d+)\s*hata|hep\s+başarısız|always\s+fail")
_CLAIM_NONE = re.compile(r"(?i)hi[cç]\s+hata\s+vermedi|hi[cç]\s+hata\s+yok|never\s+fail|no\s+failures?")
_CLAIM_ALL = re.compile(r"(?i)hepsi\s+hatal[ıi]|all\s+failed|%?\s*100")
FALLBACK_TR = ("- Olası neden belirlenemedi: araç verisi hatanın kök nedenini söylemiyor; "
               "yukarıda yalnızca gözlenen kod/imza var (düşük güven).\nGüven: düşük\n")
FALLBACK_EN = "- No possible cause could be determined: the tool data does not contain the cause (low confidence).\nConfidence: low\n"


def _has_report_evidence(structured: List[Dict[str, Any]]) -> bool:
    for sr in structured or []:
        res = sr.get("result") if isinstance(sr, dict) else None
        if not isinstance(res, dict):
            continue
        content = res.get("content")
        if isinstance(content, str) and _LINE_RE.search(content):
            return True
        if res.get("error_signature"):
            return True
    return False


def premise_correction(message: str, structured: List[Dict[str, Any]], english: bool = False) -> str:
    """Kullanıcı sayısal/evet-hayır iddiasını filtresiz toplamlarla karşılaştır; kod öneki üretir."""
    msg = message or ""
    uni = {}
    for sr in structured or []:
        res = sr.get("result") if isinstance(sr, dict) else None
        if isinstance(res, dict):
            u = _universe_of(res)
            if u.get("runs_total") is not None:
                uni = u
                break
    if not uni:
        return ""
    n = int(uni.get("runs_total") or 0)
    f = int(uni.get("failed_total") or 0)
    rate = uni.get("failure_rate_pct")
    # "hiç hata vermedi"
    if _CLAIM_NONE.search(msg) and f > 0:
        if english:
            return (f"**No:** in the matching period there were {n} runs and {f} failed"
                    + (f" ({_fmt(rate)}%)" if rate is not None else "") + ".\n\n")
        return (f"**Hayır:** eşleşen dönemde {n} çalışmanın {tr_n_si(f)} hatalı"
                + (f" (%{_fmt_rate(rate)})" if rate is not None else "") + ".\n\n")
    # "N kez hata"
    m = _CLAIM_N.search(msg)
    if m:
        claimed = next((int(g) for g in m.groups() if g), None)
        if claimed is not None and claimed != f:
            if english:
                return f"**Correction:** not {claimed} — there were {f} failed runs (of {n} total).\n\n"
            return f"**Düzeltme:** Belirttiğiniz {claimed} değil: bu dönemde {f} hatalı çalışma var (toplam {n}).\n\n"
    # "hepsi hatalı" / %100 — yalnız gerçekten %100 ise onayla, değilse düzelt
    if _CLAIM_ALL.search(msg) and n > 0 and f < n:
        if english:
            return f"**Correction:** not all failed — {f}/{n} failed ({_fmt(rate)}%).\n\n"
        return f"**Düzeltme:** Hepsi hatalı değil — {f}/{n} hatalı (%{_fmt_rate(rate)}).\n\n"
    return ""


_OBJ_NAME_RE = re.compile(
    r"\b(?:JOBS|JOBP|JOBF|JOBG|VARA|SCRI|SCRP|EVNT|JSCH|CALL)\.[A-Z0-9_.]+\b", re.I)
_AGENT_NAME_RE = re.compile(r"\b(?:LNX|WIN|SAP|DB|APP|BAT)[A-Z0-9]{2,}\b")
_USER_NAME_RE = re.compile(r"\b[A-Z]{2,}(?:/[A-Z0-9._-]+)+\b")  # BATCH/OPS vb.
_RUN_ID_RE = re.compile(r"\b(?:RunID\s*)?(\d{9,})\b", re.I)


def allowed_entities_from_structured(structured: List[Dict[str, Any]]) -> Dict[str, set]:
    """Araç verisindeki nesne/agent/kullanıcı/RunID kümeleri (Değerlendirme varlık kontrolü)."""
    objs, agents, users, runs = set(), set(), set(), set()
    for sr in structured or []:
        res = sr.get("result") if isinstance(sr, dict) else None
        if not isinstance(res, dict):
            continue
        for it in (res.get("items") or []):
            if not isinstance(it, dict):
                continue
            if it.get("object_name"):
                objs.add(str(it["object_name"]).upper())
            if it.get("agent"):
                agents.add(str(it["agent"]).upper())
            if it.get("user"):
                users.add(str(it["user"]).upper())
            if it.get("run_id") is not None:
                runs.add(str(it["run_id"]))
        for k in ("object_name", "agent", "user"):
            if res.get(k):
                (objs if k == "object_name" else agents if k == "agent" else users).add(str(res[k]).upper())
        if res.get("run_id") is not None:
            runs.add(str(res["run_id"]))
        args = sr.get("args") if isinstance(sr, dict) else None
        if isinstance(args, dict):
            if args.get("object_name"):
                objs.add(str(args["object_name"]).upper())
            if args.get("agent"):
                agents.add(str(args["agent"]).upper())
            if args.get("run_id") is not None:
                runs.add(str(args["run_id"]))
    return {"objects": objs, "agents": agents, "users": users, "run_ids": runs}


_EV_STOP = {
    "error", "errors", "failed", "failure", "fail", "hata", "hatalı", "return", "code", "from", "step", "with", "that",
    "this", "have", "been", "olarak", "ancak", "olası", "muhtemel", "olabilir", "neden", "sebep", "için", "gibi", "kodu",
    "adım", "adımı", "güven", "orta", "yüksek", "düşük", "bağlı", "çalışma", "çalışması", "durum", "agent",
    "warning", "fatal", "exception", "aborted", "timed", "denied",
}


# Veride bulunmadıkça neden olarak ANILAMAYACAK özgül varsayımlar (modelin sık uydurduğu "sızıntı / aşırı yük / donanım…")
_INVENT_RE = re.compile(
    r"(?i)(sızıntı|leak|aşırı|yoğun|donanım|hardware|güvenlik\s+duvar|firewall|yedekleme|backup|bakım|saldırı|ddos|"
    r"ağ\s+(?:kesintisi|sorunu|gecikmesi)|network\s+(?:outage|issue|latency))")


def evidence_tokens_from_structured(structured: List[Dict[str, Any]]) -> set:
    """Araç sonuçlarındaki NEDEN kanıtından ayırt edici kelimeler: rapor hata satırları, hata imzaları, bilinen kod açıklamaları."""
    parts: List[str] = []

    def add_sig(v: Any) -> None:
        if isinstance(v, str) and v.strip():
            parts.append(v)

    for sr in structured or []:
        res = sr.get("result") if isinstance(sr, dict) else None
        if not isinstance(res, dict):
            continue
        content = res.get("content")
        if isinstance(content, str):
            parts.extend(ln for ln in content.splitlines() if _LINE_RE.search(ln))
        add_sig(res.get("error_signature"))
        for d in (res.get("error_signature_distribution") or []):
            add_sig(d.get("signature") if isinstance(d, dict) else d)
        for it in (res.get("items") or []):
            if isinstance(it, dict):
                add_sig(it.get("error_signature"))
        for k in ("known_error_codes",):
            v = res.get(k)
            if v:
                parts.append(json.dumps(v, ensure_ascii=False, default=str))
    text = " ".join(parts).lower()
    toks = _EvidenceSet(w for w in re.findall(r"[a-z0-9çğıöşü_]{4,}", text) if w not in _EV_STOP and not w.isdigit())
    toks.text = text
    return toks


class _EvidenceSet(set):
    text: str = ""


class EvalFilter:
    """Değerlendirme bölümünde modelin yazabileceği satırları KOD belirler (satır satır, akışı bozmadan).

    Kalanlar: 'Düzeltme:' satırı (yanlış öncül), 'Olası neden…' başlık satırı ve altındaki maddeler, hedge'li ('olası/olabilir…')
    zaman/RunID içermeyen maddeler, 'Güven: …' satırı. ainew-meta çiti akıtılmaz, flush'ta EN SONA konur. Gözlemleri yeniden yazan
    giriş cümleleri, gözlem tekrarı maddeleri, 'Değerlendirme:'/'Genel bilgi' bölümleri atılır (gözlemler zaten kod tarafından yazıldı;
    yanlış eşleştirme/uydurma riskini kökten keser). Hiç neden maddesi yoksa sabit bir "belirlenemedi" maddesi eklenir.
    """

    _CAUSE_HEAD = re.compile(r"(?i)^(olası|muhtemel|possible|likely)\s+(neden|sebep|cause|reason)")

    def __init__(self, english: bool = False, *, allow_med_high: bool = False,
                 allowed_entities: Optional[Dict[str, set]] = None) -> None:
        self.english = english
        self.allow_med_high = allow_med_high  # yalnız raporda hata satırı kanıtı varsa
        self.allowed = allowed_entities or {}
        self.buf = ""
        self.in_meta = False
        self.meta_lines: List[str] = []
        self.kept_cause = False
        self.in_cause_list = False
        self.last_blank = True
        self.dropped = 0
        self._conf_forced_low = False
        self.evidence: Optional[set] = None
        self._pending_head = ""
        self.notes: List[Dict[str, Any]] = []   # atılan satırların telemetrisi (doğrulayıcı kuralı biliniyorsa adıyla)

    def _note_drop(self, reason: str, line: str) -> None:
        text_ = (line or "").strip()
        if not text_ or text_.startswith("```") or len(self.notes) >= 40:
            return
        rule = reason
        try:
            from app.services.automic.answer_validator import validate_answer
            _, iv = validate_answer(text_, english=self.english)
            if iv:
                rule = iv[0].get("rule") or reason
        except Exception as exc:
            from app.services.automic.errors import note_error
            note_error("why_answer.evalfilter_note", exc)
        self.notes.append({"rule": rule, "reason": reason, "excerpt": text_[:120], "stage": "eval_filter"})

    def take_notes(self) -> List[Dict[str, Any]]:
        out, self.notes = self.notes, []
        return out

    def set_allowed_entities(self, structured: List[Dict[str, Any]]) -> None:
        self.allowed = allowed_entities_from_structured(structured)
        self.evidence = evidence_tokens_from_structured(structured)

    def _grounded(self, plain: str) -> bool:
        """Neden maddesi araç verisindeki (rapor hata satırı / hata imzası / bilinen kod) en az bir ayırt edici kelimeyi anmalı.

        Kanıt kümesi hiç kurulmadıysa (None) denetim yapılmaz; kurulduysa ve boşsa hiçbir neden maddesi geçmez."""
        ev = getattr(self, "evidence", None)
        if ev is None:
            return True
        words = {w for w in re.findall(r"[a-z0-9çğıöşü_]{4,}", plain.lower())}
        if not (words & ev):
            return False
        blob = getattr(ev, "text", "")
        return all(m.group(0).lower() in blob for m in _INVENT_RE.finditer(plain))

    def _entity_ok(self, plain: str) -> bool:
        """Araç verisinde olmayan nesne/agent/kullanıcı/RunID geçen satırları reddet."""
        allow = self.allowed or {}
        if not allow:
            return True
        for m in _OBJ_NAME_RE.findall(plain):
            if m.upper() not in (allow.get("objects") or set()):
                return False
        for m in _AGENT_NAME_RE.findall(plain):
            # Yalnız bilinen agent kalıplarını kontrol et; küme boşsa atlama
            agents = allow.get("agents") or set()
            if agents and m.upper() not in agents:
                return False
        for m in _USER_NAME_RE.findall(plain):
            users = allow.get("users") or set()
            if users and m.upper() not in users:
                return False
            if not users and m.upper() not in (allow.get("objects") or set()):
                # Hiç kullanıcı yokken BATCH/OPS uydurmasını kes
                return False
        for m in _RUN_ID_RE.findall(plain):
            runs = allow.get("run_ids") or set()
            if runs and m not in runs:
                return False
        return True

    def _decide(self, line: str) -> Optional[str]:
        s = line.strip()
        if self.in_meta:
            self.meta_lines.append(line)
            if s.startswith("```"):
                self.in_meta = False
            return None
        if s.startswith("```ainew-meta"):
            self.in_meta = True
            self.meta_lines.append(line)
            return None
        if s.startswith("```"):          # ```markdown sarmalı (açılış/kapanış) → at
            return None
        if not s:
            if self.last_blank:
                return None
            self.last_blank = True
            return ""
        is_bullet = bool(_BULLET_RE.match(s))
        plain = re.sub(r"[*_`#]+", "", _BULLET_RE.sub("", s)).strip()
        # Durum/dönüş koduna neden anlamı yükleyen maddeleri at
        if re.search(r"(?i)(return\s*code|dönüş\s*kodu|durum\s*kodu|status\s*code|\b1800\b|\bRC\b|\bexit\s*code\b)", plain) and \
                re.search(r"(?i)(anlam|işaret|belirt|neden|genellikle|örneğin|means|indicates|usually|e\.g\.)", plain):
            self.dropped += 1
            self._note_drop("code_meaning", s)
            return None
        if not self._entity_ok(plain):
            self.dropped += 1
            self._note_drop("ungrounded_entity", s)
            return None
        # Kanıt yoksa güven orta/yüksek → düşük
        if _CONF.match(plain) and not self.allow_med_high and _CONF_MED_HI.search(plain):
            plain = "Güven: düşük" if not self.english else "Confidence: low"
            line = plain
            self._conf_forced_low = True
        if is_bullet and not self.allow_med_high:
            line = re.sub(r"(?i)\(\s*güven:\s*(orta|yüksek)\s*\)", "(güven: düşük)", line)
            line = re.sub(r"(?i)\(\s*confidence:\s*(medium|high)\s*\)", "(confidence: low)", line)
            plain = re.sub(r"[*_`#]+", "", _BULLET_RE.sub("", line.strip())).strip()
        keep = False
        if _CONF.match(plain) and not self.kept_cause:
            # Kanıta dayalı neden maddesi yok → sabit "belirlenemedi" bloğu (kendi güven satırıyla) yazılacak
            self.dropped += 1
            self._note_drop("conf_without_cause", s)
            return None
        if _KEEP_HEAD.match(plain) or _CONF.match(plain):
            keep = True
            self.in_cause_list = False
        elif self._CAUSE_HEAD.match(plain) and not is_bullet:
            # Başlık yalnız arkasından GERÇEKTEN bir (kanıta dayalı) madde geçerse yazılır
            self.in_cause_list = True
            self._pending_head = line
            return None
        elif is_bullet and not _TS.search(plain) and (_HEDGE.search(plain) or self.in_cause_list):
            if self._grounded(plain):
                keep = True
                self.kept_cause = True
                if self._pending_head:
                    line, self._pending_head = self._pending_head + "\n" + line, ""
            else:
                self.dropped_ungrounded = getattr(self, "dropped_ungrounded", 0) + 1
                self._note_drop("ungrounded_cause", s)
        elif not is_bullet:
            self.in_cause_list = False
        if not keep:
            self.dropped += 1
            self._note_drop("not_allowed_line", s)
            return None
        self.last_blank = False
        return line
    def feed(self, text: str) -> str:
        self.buf += text or ""
        out = ""
        while "\n" in self.buf:
            line, self.buf = self.buf.split("\n", 1)
            d = self._decide(line)
            if d is not None:
                out += d + "\n"
        return out

    def flush(self) -> str:
        out = ""
        if self.buf:
            d = self._decide(self.buf)
            self.buf = ""
            if d is not None:
                out += d + "\n"
        if not self.kept_cause:
            self.kept_cause = True
            out += FALLBACK_EN if self.english else FALLBACK_TR
        if self.meta_lines:
            out += "\n" + "\n".join(self.meta_lines) + "\n"
            self.meta_lines = []
        return out


def answer_note(structured: List[Dict[str, Any]], tz: Any = None, english: bool = False) -> Optional[str]:
    """Gözlemler üretilecekse modele giden KISA talimat (yalnız Değerlendirme yaz)."""
    if not build_blocks(structured, tz, english):
        return None
    if english:
        return ("[System] The system has already shown the failure data (RunID, object, time, status, error lines, return code, "
                "error-code explanations) to the user as an 'Observations' section. Write ONLY the assessment. Exact output format: "
                "at most 3 bullets '- Possible cause: … (confidence)', then one line 'Confidence: low|medium|high', then the ainew-meta "
                "block. Nothing else: no summary/bold lead sentence, no heading or 'Assessment:' label, no 'General information', "
                "do not repeat observations (times, RunIDs, agents, numbers), add no new numbers/RunIDs/object or agent names/dates, "
                "do not explain error codes or return codes. If the question has a premise that contradicts the observations (count, "
                "'always failed'), correct it in one line 'Correction: …' before the bullets. Lines not in this format are dropped by the system.")
    evid = _has_report_evidence(structured)
    conf = "düşük|orta|yüksek" if evid else "düşük"
    return ("[Sistem] Hata verisini (RunID, nesne, zaman, durum kodu, hata satırları, dönüş kodu) kullanıcıya "
            "'Gözlemler' bölümü olarak SİSTEM zaten gösterdi. YALNIZCA değerlendirmeyi yaz. Çıktı biçimi tam olarak: en çok 3 madde "
            f"'- Olası neden: … (güven)', ardından tek satır 'Güven: {conf}', ardından ainew-meta bloğu. "
            "Başka hiçbir şey yazma: özet/kalın giriş, başlık, 'Genel bilgi' YOK; gözlemleri tekrar etme; "
            "gözlemlerde OLMAYAN kullanıcı/agent/nesne/RunID EKLEME; durum kodu (1800…) veya dönüş koduna neden/anlam yükleme. "
            "Öncül düzeltmesini sistem önde yazar — 'Düzeltme:' tekrarlama. Bu biçime uymayan satırlar atılır.")
