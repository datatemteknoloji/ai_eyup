"""Basit profiller için LLM'siz şablon cevaplar (Adım 7h).

yesno | count | list | infra → araç sonuçlarından kod üretir; LLM çağrılmaz.
"""
from __future__ import annotations
from app.services.automic.errors import note_error

import re
from typing import Any, Dict, List, Optional, Tuple

from app.services.automic.answer_profile import classify_question
from app.services.automic.tr_grammar import tr_n_si

_OBJ_RE = re.compile(r"\b(?:JOBS|JOBP|JOBF|JOBG|SCRI|SCRP|EVNT|VARA)\.[A-Z0-9_.]+", re.I)
_AGENT_RE = re.compile(r"\b(?:LNX|WIN|SAP|UNIX|SOL|AIX)[A-Z0-9_-]{2,}\b")


def _res_list(structured: List[Dict[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
    out = []
    for sr in structured or []:
        if not isinstance(sr, dict):
            continue
        res = sr.get("result")
        if isinstance(res, dict) and res.get("ok") is not False:
            out.append((sr.get("tool") or "", res))
    return out


def _fmt_pct(v: Any) -> str:
    try:
        return f"{float(v):g}".replace(".", ",")
    except (TypeError, ValueError):
        return str(v)


_TR_MONTH = {
    "01": "Ocak", "02": "Şubat", "03": "Mart", "04": "Nisan", "05": "Mayıs", "06": "Haziran",
    "07": "Temmuz", "08": "Ağustos", "09": "Eylül", "10": "Ekim", "11": "Kasım", "12": "Aralık",
}


def _fmt_day_tr(iso10: str) -> str:
    """2026-10-08 → 08 Ekim"""
    if not iso10 or len(iso10) < 10:
        return iso10 or ""
    d, m = iso10[8:10], iso10[5:7]
    return f"{d} {_TR_MONTH.get(m, m)}"


def _coverage_note(res: Dict[str, Any]) -> str:
    cov = res.get("coverage") or {}
    dw = cov.get("days_with_records")
    rd = cov.get("range_days")
    pnote = str(res.get("partial_coverage_note") or "")
    if dw == 0 or "yalnızca 0 gününde" in pnote:
        # «yalnızca 0 gününde veri var» çelişkili okunur; doğrusu «hiçbir gününde veri yok».
        m = re.match(r"\s*(\d+)\s+günlük", pnote)
        n = rd if isinstance(rd, int) and rd > 0 else (int(m.group(1)) if m else 0)
        return f"{n} günlük aralığın hiçbir gününde veri yok." if n else ""
    note = res.get("partial_coverage_note")
    if note and "gününde veri" in str(note):
        return str(note)
    d0 = (cov.get("continuous_since") or cov.get("data_first_at") or "")[:10]
    d1 = (cov.get("data_last_at") or "")[:10]
    # Kısmi kapsam: ya days_without > 0 ya da days_with << range
    partial = bool(cov.get("days_without_records")) or (
        isinstance(dw, int) and isinstance(rd, int) and rd > 0 and dw < rd)
    if partial and d0 and d1 and dw is not None and rd:
        same_month = d0[5:7] == d1[5:7]
        if same_month:
            span = f"{d0[8:10]}–{d1[8:10]} {_TR_MONTH.get(d0[5:7], d0[5:7])}"
        else:
            span = f"{_fmt_day_tr(d0)} – {_fmt_day_tr(d1)}"
        return f"{rd} günlük aralığın yalnızca {dw} gününde veri var ({span})."
    return str(note) if note else ""


def _period_label(res: Dict[str, Any]) -> str:
    """Şablon başlığı için dönem ifadesi (son 30 gün / seçili dönem)."""
    fb = res.get("filtered_by") or {}
    rng = (fb.get("range") or res.get("range") or "").lower()
    if rng in ("30d", "30"):
        return "son 30 günde"
    if rng in ("7d", "7"):
        return "son 7 günde"
    if rng in ("24h", "1d"):
        return "son 24 saatte"
    # from/to süresinden tahmin
    try:
        from datetime import datetime
        a = datetime.fromisoformat(str(res.get("from") or "").replace("Z", "+00:00"))
        b = datetime.fromisoformat(str(res.get("to") or "").replace("Z", "+00:00"))
        days = (b - a).total_seconds() / 86400.0
        if 25 <= days <= 35:
            return "son 30 günde"
        if 6 <= days <= 8:
            return "son 7 günde"
    except Exception as _e:
        note_error("template_answers._period_label", _e)
    return "eşleşen dönemde"


def _from_search_yesno(message: str, res: Dict[str, Any], english: bool) -> str:
    uni = res.get("universe") or {}
    runs = int(uni.get("runs_total") or res.get("runs_total") or res.get("total") or 0)
    failed = int(uni.get("failed_total") or res.get("failed_total") or 0)
    rate = uni.get("failure_rate_pct")
    if rate is None and runs:
        rate = round(100.0 * failed / runs, 2)
    obj_m = _OBJ_RE.search(message or "")
    obj = obj_m.group(0) if obj_m else ""
    # "hiç hata vermedi" öncülü → Hayır eğer failed>0
    premise_none = bool(re.search(r"(?i)hi[cç]\s+hata|hep\s+ba[sş]ar|never\s+fail", message or ""))
    cov = _coverage_note(res)
    period = _period_label(res)
    # Olumlu kutup: "hata verdi/vermiş mi", "patladı mı", "did it fail" → hatalı çalışma varsa EVET
    from app.services.automic.tr_grammar import fold_tr
    _f = fold_tr(message or "")
    positive_fail = bool(re.search(r"\bhata\s*(?:ver|al)\w*|\bpatla\w*|\bfail(?:ed)?\b|\babend\w*|\bbasarisiz\w*", _f)) \
        and not re.search(r"vermedi|vermemis|vermiyor|\bhatasiz|sorunsuz|\bbasarili|\bhic\b|\bnever\b|didn.?t", _f)
    if positive_fail and not english:
        if failed > 0:
            head = (f"**Evet:** {period} {runs} çalışmanın {tr_n_si(failed)} hatalı"
                    + (f" (%{_fmt_pct(rate)})" if rate is not None else "") + ".")
        else:
            head = f"**Hayır:** {period} {runs} çalışmada hatalı çalışma yok."
        return "\n\n".join([head] + ([cov] if cov else []))
    if english:
        if premise_none and failed > 0:
            head = (f"**No:** in the period {failed} of {runs} runs failed"
                    + (f" ({_fmt_pct(rate)}%)" if rate is not None else "") + ".")
        elif failed == 0:
            head = f"**Yes:** {runs} runs, none failed."
        else:
            head = (f"**No:** {failed} of {runs} runs failed"
                    + (f" ({_fmt_pct(rate)}%)" if rate is not None else "") + ".")
    else:
        if premise_none and failed > 0:
            head = (f"**Hayır:** {period} {runs} çalışmanın {tr_n_si(failed)} hatalı"
                    + (f" (%{_fmt_pct(rate)})" if rate is not None else "") + ".")
        elif failed == 0:
            head = f"**Evet:** {period} {runs} çalışma, hatalı yok."
        else:
            head = (f"**Hayır:** {period} {runs} çalışmanın {tr_n_si(failed)} hatalı"
                    + (f" (%{_fmt_pct(rate)})" if rate is not None else "") + ".")
    bits = [head]
    if cov:
        bits.append(cov)
    return "\n\n".join(bits)


def _fmt_iso_day(v: Any) -> str:
    sv = str(v or "")
    return sv[:10] if len(sv) >= 10 else sv


def _local_day(v: Any, *, end: bool = False) -> str:
    """UTC ISO → yerel gün (YYYY-AA-GG); `end` ise (dışlayıcı bitiş) bir saniye geri alınır."""
    sv = str(v or "")
    if not sv:
        return ""
    try:
        import os
        from datetime import datetime, timedelta, timezone
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(sv.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        dt = dt.astimezone(ZoneInfo(os.environ.get("TZ", "Europe/Istanbul")))
        if end:
            dt -= timedelta(seconds=1)
        return dt.strftime("%Y-%m-%d")
    except (ValueError, KeyError) as exc:
        note_error("template_answers.local_day", exc, detail=sv[:40])
        return _fmt_iso_day(sv)


def _no_data_answer(res: Dict[str, Any], english: bool) -> str:
    cov = res.get("coverage") or {}
    d0, d1 = _fmt_iso_day(cov.get("data_first_at")), _fmt_iso_day(cov.get("data_last_at"))
    a, b = _local_day(res.get("from")), _local_day(res.get("to"), end=True)
    if english:
        head = "**No data for this period** — this is not the same as \"no failures\"."
        tail = (f" The module database only covers {d0} – {d1}." if d0 and d1 else "")
        return head + tail
    when = f" ({a} – {b})" if a and b else ""
    head = f"**Bu döneme ait veri yok{when}** — bu, «hata olmadı» demek değildir."
    pc = _coverage_note(res)          # aracın kısmi kapsam notu (ör. "365 günlük aralığın yalnızca 0 gününde veri var (08–12 Ekim).")
    if pc:
        head += " " + pc
    tail = (f" Modül veritabanındaki kayıtlar yalnızca {d0} – {d1} aralığını kapsıyor; "
            "bu aralığın dışındaki dönemler hakkında bilgi veremem." if d0 and d1 else "")
    return head + tail


def _fmt_ts_local(v: Any) -> str:
    sv = str(v or "")
    if not sv:
        return ""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(sv.replace("Z", "+00:00"))
        off = dt.strftime("%z")
        off = (off[:3] + ":" + off[3:]) if off else ""
        return dt.strftime("%Y-%m-%d %H:%M:%S") + off
    except ValueError as exc:
        note_error("template_answers.fmt_ts", exc, detail=sv[:40])
        return sv


def _from_last_run(message: str, res: Dict[str, Any], english: bool) -> Optional[str]:
    from app.services.chat_llm_context import fmt_duration

    items = [x for x in (res.get("items") or []) if isinstance(x, dict)]
    obj_m = _OBJ_RE.search(message or "")
    want = (obj_m.group(0) if obj_m else "").upper()
    if want:
        items = [x for x in items if str(x.get("object_name") or "").upper() == want] or []
    if not items:
        return None
    r = max(items, key=lambda x: str(x.get("start_time") or x.get("activation_time") or ""))
    name = r.get("object_name") or want
    start = _fmt_ts_local(r.get("start_time") or r.get("activation_time"))
    end = _fmt_ts_local(r.get("end_time"))
    dur = fmt_duration(r.get("duration_sec")) if r.get("duration_sec") is not None else ""
    cls = str(r.get("status_class") or "")
    code = r.get("status_code")
    if english:
        state = {"ok": "completed successfully", "failed": "ended with an error", "cancelled": "was cancelled"}.get(cls, "is still running")
        head = f"**`{name}` last ran at {start}**"
        tail = f" and {state}" + (f" (status code {code})" if code is not None and cls == 'failed' else "")
        extra = (f"; ended {end}" if end else "") + (f", duration {dur}" if dur else "")
        return head + tail + extra + (f"; agent `{r['agent']}`" if r.get("agent") else "") + "."
    state = {"ok": "başarıyla tamamlandı", "failed": "hatayla bitti", "cancelled": "iptal edildi"}.get(cls, "şu an çalışıyor")
    head = f"**`{name}` en son {start} tarihinde çalıştı**"
    tail = f" ve {state}" + (f" (durum kodu {code})" if code is not None and cls == "failed" else "")
    extra = ""
    if end and cls in ("ok", "failed", "cancelled"):
        extra += f"; bitiş {end}"
    if dur and cls in ("ok", "failed", "cancelled"):
        extra += f", süre {dur}"
    if r.get("agent"):
        extra += f"; agent `{r['agent']}`"
    return head + tail + extra + "."


def _from_search_list(message: str, res: Dict[str, Any], english: bool) -> str:
    by_obj = res.get("by_object") or []
    n_fail = int(res.get("failed_total") or (res.get("universe") or {}).get("failed_total")
                 or res.get("filtered_total") or res.get("total") or 0)
    n_jobs = int(res.get("distinct_failed_objects")
                 or (res.get("universe") or {}).get("distinct_objects_failed")
                 or len(by_obj))
    if not by_obj and n_fail == 0:
        return ("**Bu dönemde hatalı çalışma yok.**" if not english
                else "**No failed runs in this period.**")
    # Eşitlik: aynı failed_count
    top = by_obj[:5]
    parts = []
    for x in top:
        parts.append(f"{x['object_name']} ({x['failed_count']})")
    # Eşit gruplar
    if len(top) >= 2:
        from collections import defaultdict
        by_c: Dict[int, List[str]] = defaultdict(list)
        for x in top:
            by_c[int(x["failed_count"])].append(x["object_name"])
        ties = [f"{', '.join(v)} ({k} hata, eşit)" for k, v in by_c.items() if len(v) > 1]
    else:
        ties = []
    # "Dün gece" gibi varsayım zaten ayrı satırda; burada dönem etiketi ekle
    night = bool(re.search(r"(?i)gece|night", message or ""))
    if english:
        head = f"**{n_fail} failed runs across {n_jobs} distinct jobs.**"
        if parts:
            head += f" Most failing: {', '.join(parts)}."
    else:
        prefix = "Dün gece " if night else ""
        head = f"**{prefix}{n_fail} hatalı çalışma, {n_jobs} farklı job.**"
        if parts:
            head += f" En çok hata verenler: {', '.join(parts)}."
    out = [head]
    if ties:
        out.append("Eşitlik: " + "; ".join(ties) + ".")
    cov = _coverage_note(res)
    if cov:
        out.append(cov)
    return "\n\n".join(out)


def _from_history_top5(res: Dict[str, Any], english: bool) -> str:
    rows = res.get("rows") or []
    if not rows:
        return res.get("summary_tr") or ("**Veri yok.**" if not english else "**No data.**")
    # Her zaman satırlardan üret (summary_tr iç talimat içerebilir)
    cf = res.get("combined_failed")
    cr = res.get("combined_runs")
    cfp = res.get("combined_failure_rate_pct")
    ef = res.get("env_failure_rate_pct")
    if cf is None:
        cf = sum(int(x.get("failed") or 0) for x in rows)
    if cr is None:
        cr = sum(int(x.get("runs") or 0) for x in rows)
    if cfp is None and cr:
        cfp = round(100.0 * int(cf) / int(cr), 1)
    bits = [
        f"En çok hata veren {len(rows)} job: birleşik {cf} hatalı / {cr} çalışma "
        f"(%{_fmt_pct(cfp)})."
        + (f" Ortam geneli %{_fmt_pct(ef)}." if ef is not None else "")
    ]
    for i, x in enumerate(rows[:5], 1):
        bits.append(
            f"{i}. {x.get('object_name')} — {x.get('failed')} hata / {x.get('runs')} çalışma "
            f"(%{_fmt_pct(x.get('failure_rate_pct'))})"
        )
    ca = res.get("common_attributes") or {}
    attrs = ca.get("attributes") or []
    if attrs:
        bits.append("Ortak noktalar:")
        for a in attrs[:5]:
            bits.append("- " + (a.get("meaning_tr") or f"{a.get('attribute')}={a.get('value')}"))
    else:
        note = ca.get("note") or "Belirgin bir ortak nokta yok."
        bits.append(note if note.startswith("Belirgin") else "Belirgin bir ortak nokta yok.")
    return "**" + bits[0] + "**\n\n" + "\n".join(bits[1:])


def _from_object_host(res: Dict[str, Any], english: bool) -> str:
    if res.get("summary_tr"):
        # summary_tr zaten doğru formatta; talimat eklerini at
        s = res["summary_tr"]
        s = re.sub(r"(?i)\s*Sistem/ortam adı[^.]*\.", "", s)
        return f"**{s.strip()}**" if not s.strip().startswith("**") else s.strip()
    agents = res.get("agents") or []
    name = res.get("object_name") or "?"
    if not agents:
        return f"**`{name}` için seçili dönemde agent kaydı yok.**"
    n = int(res.get("distinct_agents") or len(agents))
    top = agents[:5]
    parts = []
    for a in top:
        host = a.get("hostname") or a.get("ip") or "?"
        src = a.get("hostname_source")
        label = f"{a.get('agent')} ({host}" + (f", kaynak: {src}" if src else "") + f") {a.get('runs_count')} kez"
        parts.append(label)
    last = agents[0]  # zaten runs DESC; son çalışma ayrı alanda olabilir
    # last_run_at en yeni
    by_last = sorted(agents, key=lambda x: str(x.get("last_run_at") or ""), reverse=True)
    last_a = by_last[0] if by_last else top[0]
    if english:
        return (f"**`{name}` ran on {n} agents.** Most: {', '.join(parts)}. "
                f"Last run: {last_a.get('agent')}.")
    return (f"**`{name}` seçili dönemde {n} farklı agent'ta çalıştı.** "
            f"En çok: {', '.join(parts)}. "
            f"Son çalışma: {last_a.get('agent')}"
            + (f", {str(last_a.get('last_run_at') or '')[:16]}" if last_a.get("last_run_at") else "")
            + ".")


def _from_engines(res: Dict[str, Any], english: bool) -> str:
    # Tercihen summary_tr; kopuk process ekle
    servers = res.get("servers") or []
    if not servers and isinstance(res.get("engines"), dict):
        servers = (res["engines"] or {}).get("servers") or []
        if not res.get("summary_tr"):
            res = {**res, **(res.get("engines") or {})}
    summary = (res.get("summary_tr") or "").strip()
    # Tekrarlayan IP satırlarını temizle; "Sistem/ortam..." talimatını at
    summary = re.sub(r"(?i)\s*Sistem/ortam adı[^.]*\.", "", summary)
    summary = re.sub(r"(?i)\s*IP/hostname kullan\.?", "", summary)
    disconnected = []
    for s in servers:
        for p in s.get("processes") or []:
            st = (p.get("status") or "").lower()
            if st in ("missing", "disconnected", "kopuk") or p.get("status_label") in ("kopuk", "kayıp"):
                disconnected.append(f"{s.get('ip')}'de {p.get('name')} kopuk")
    # Hostname yoksa IP tekrarını önle: summary zaten IP kullanıyor
    if summary:
        head = summary.split("Aktif PWP")[0].strip() if "Aktif PWP" in summary else summary
        # Bir kez yaz
        lines = [ln.strip() for ln in re.split(r"\s*-\s*", head) if ln.strip()]
        # Daha temiz: chat_note / summary_tr'nin ilk cümlesi
        text = summary
        # "Engine N sunucuda:" bloğunu sıkıştır
        m = re.search(r"Engine\s+(\d+)\s+sunucuda", summary, re.I)
        if m and servers:
            bits = []
            for s in servers:
                tc = s.get("type_counts") or {}
                parts = []
                if s.get("has_active_pwp"):
                    parts.append("PWP aktif")
                for pt in ("WP", "CP", "JWP", "JCP", "REST"):
                    if tc.get(pt):
                        parts.append(f"{tc[pt]} {pt}")
                ip = s.get("ip") or "?"
                node = s.get("node")
                # Hostname yoksa veya IP ile aynıysa tekrarlama
                if node and node != ip and not str(node).startswith(str(ip)):
                    label = f"{ip} ({node})"
                else:
                    label = str(ip)
                bits.append(f"{label} ({', '.join(parts)})" if parts else label)
            ap = res.get("active_pwp") or []
            text = f"Engine {len(servers)} sunucuda: " + "; ".join(bits) + "."
            if len(ap) == 1:
                text += f" Aktif PWP: {ap[0].get('name')} @ {ap[0].get('ip')}."
        if disconnected:
            text += " " + "; ".join(disconnected) + "."
        return f"**{text}**"
    return "**Engine sunucu bilgisi yok.**"


def _hhmm(v: Any) -> str:
    """ISO zamanı yerel saatte (TZ, varsayılan Europe/Istanbul) SS:DD — "son kontrol" ile "yaşam sinyali" aynı saat dilimi."""
    sv = str(v or "")
    if not sv:
        return "?"
    try:
        import os
        from datetime import datetime, timezone
        from zoneinfo import ZoneInfo
        dt = datetime.fromisoformat(sv.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ZoneInfo(os.environ.get("TZ", "Europe/Istanbul"))).strftime("%H:%M")
    except (ValueError, KeyError) as exc:
        note_error("template_answers.hhmm", exc, detail=sv[:40])
    if "T" in sv:
        return sv.split("T")[1][:5]
    return sv[:19]


def _from_agent_status(res: Dict[str, Any], message: str, english: bool) -> str:
    # list_agents veya agent detail
    agents = res.get("agents") or res.get("items") or []
    if isinstance(res.get("agent"), dict):
        agents = [res["agent"]]
    name_m = _AGENT_RE.search(message or "")
    want = (name_m.group(0) if name_m else "").upper()
    # kopuk listesi — altyapı ekranıyla aynı fonksiyon (infra.list_agents) ve aynı filtre (status=disconnected)
    if re.search(r"(?i)kopuk", message or ""):
        down = [a for a in agents if (a.get("status") or "").lower() == "disconnected"]
        sync_s = _hhmm(res.get("synced_at"))
        if not down:
            return (f"**Kopuk agent yok** (son kontrol {sync_s})." if not english
                    else f"**No disconnected agents** (last check {sync_s}).")
        from app.services.automic.infra_status import rule_label_tr
        bits = []
        for a in down[:20]:
            why = rule_label_tr(a.get("status_rule") or "")
            life = _hhmm(a.get("last_life_sign"))
            extra = ", ".join(x for x in (why, f"son yaşam sinyali {life}" if life != "?" else "") if x)
            bits.append(f"`{a.get('name') or a.get('agent')}`" + (f" ({extra})" if extra else ""))
        if english:
            return f"**Disconnected agents ({len(down)}):** " + "; ".join(bits) + f". Last check {sync_s}."
        return f"**Kopuk agent'lar ({len(down)}):** " + "; ".join(bits) + f". Son kontrol {sync_s}."
    # tek agent
    hit = None
    for a in agents:
        n = (a.get("name") or a.get("agent") or "").upper()
        if want and n == want:
            hit = a
            break
    if hit is None and len(agents) == 1:
        hit = agents[0]
    if hit is None and (res.get("status_label") or res.get("chat_note") or res.get("status")):
        # agent detail shape
        st = res.get("status") if isinstance(res.get("status"), dict) else {}
        label = (st.get("label") if st else None) or res.get("status_label") or "?"
        synced = (st.get("synced_at") if st else None) or res.get("synced_at") or "?"
        nm = res.get("name") or want or "?"
        # saat: HH:MM
        sync_s = str(synced)
        if "T" in sync_s:
            sync_s = sync_s.split("T")[1][:5]
        else:
            sync_s = sync_s[:19]
        return f"**{nm} {label} (son kontrol {sync_s}).**"
    if hit is None:
        return res.get("chat_note") or res.get("summary_tr") or "**Agent durumu bulunamadı.**"
    label = hit.get("status_label") or hit.get("status") or "?"
    synced = hit.get("synced_at") or hit.get("agent_synced_at") or "?"
    nm = hit.get("name") or hit.get("agent") or want
    sync_s = str(synced)
    if "T" in sync_s:
        sync_s = sync_s.split("T")[1][:5]
    else:
        sync_s = sync_s[:19]
    return f"**{nm} {label} (son kontrol {sync_s}).**"


def dependent_plan(profile: str, structured: List[Dict[str, Any]]) -> List[Tuple[str, Dict[str, Any]]]:
    """İlk araç sonucuna bağlı ikinci adım (ör. prevrun: SON'dan bir önceki çalışmanın raporu)."""
    if profile != "prevrun":
        return []
    for sr in structured or []:
        res = sr.get("result") if isinstance(sr, dict) else None
        if sr.get("tool") != "automic_search_executions" or not isinstance(res, dict):
            continue
        items = [x for x in (res.get("items") or []) if isinstance(x, dict)]
        if len(items) >= 2 and items[1].get("run_id") is not None:
            prev = items[1]
            args: Dict[str, Any] = {"run_id": int(prev["run_id"]), "aspect": "report", "report_type": "REP"}
            if prev.get("client") is not None:
                args["client"] = int(prev["client"])
            return [("automic_execution", args)]
    return []


def _from_active(message: str, structured: List[Dict[str, Any]], english: bool) -> Optional[str]:
    """Aktif işler (EH anlık görüntüsü): durum kırılımı, nesne/agent sorulduysa evet-hayır; LLM yok."""
    from app.services.chat_llm_context import fmt_duration

    res = None
    for sr in structured or []:
        r = sr.get("result") if isinstance(sr, dict) else None
        if isinstance(sr, dict) and sr.get("tool") == "automic_active" and isinstance(r, dict):
            res = r
    if res is None:
        return None
    if res.get("ok") is False:
        return f"**Aktif işler şu an okunamadı:** {res.get('error') or 'bu bilgi alınamadı'}."
    items = [x for x in (res.get("items") or []) if isinstance(x, dict)]
    total = int(res.get("matched") if res.get("matched") is not None else res.get("total") or 0)
    as_of = _fmt_ts_local(res.get("snapshot_at") or res.get("as_of")) if (res.get("snapshot_at") or res.get("as_of")) else ""
    tail = f" _(Anlık görüntü: {as_of}.)_" if as_of else ""
    from app.services.automic.tr_grammar import fold_tr
    yn = bool(re.search(r"\bm[iu]\b", fold_tr(message)))
    lead = "Evet, şu an" if yn else "Şu an"
    m = _OBJ_RE.search(message or "")
    am = _AGENT_RE.search(message or "")
    scope = (f" `{m.group(0)}`" if m else "") or (f" `{am.group(0)}` üzerinde" if am else "")
    if (m or am) and not items:
        return f"**{'Hayır, şu an' if yn else 'Şu an'}{scope} çalışan/aktif bir iş yok.**{tail}"
    by_state: Dict[str, int] = {}
    for it in items:
        by_state[str(it.get("state") or "")] = by_state.get(str(it.get("state") or ""), 0) + 1
    label = {"running": "çalışıyor", "waiting": "bekliyor", "blocked": "engelli"}
    parts = [f"{n} {label.get(k, k or 'diğer')}" for k, n in sorted(by_state.items(), key=lambda kv: -kv[1])]
    if m or am:
        first = items[0]
        run = fmt_duration(first.get("running_sec")) if first.get("running_sec") is not None else ""
        extra = f" (RunID `{first.get('run_id')}`{', çalışma süresi ' + run if run else ''}, agent `{first.get('agent')}`)"
        return f"**{lead}{scope} {total} aktif çalışması var{extra}.**{tail}"
    over = int(res.get("over_p95_count") or 0)
    shown = len(items)
    out = f"**{lead} {total} aktif iş var:** " + ", ".join(parts) + "."
    if shown < total:
        out += f" (Dökümde ilk {shown} gösterildi.)"
    if over:
        out += (f" Hepsi normal süresini (p95 × 1,2) aştı." if over >= shown else
                f" {tr_n_si(over)} normal süresini (p95 × 1,2) aştı.")
    return out + tail


def _from_prev_run(message: str, structured: List[Dict[str, Any]], english: bool) -> Optional[str]:
    from app.services.chat_llm_context import fmt_duration
    from app.services.automic.why_answer import _report_lines

    search = rep = None
    rep_err = None
    for sr in structured or []:
        if not isinstance(sr, dict):
            continue
        res = sr.get("result")
        if sr.get("tool") == "automic_search_executions" and isinstance(res, dict) and res.get("ok") is not False:
            search = res
        elif sr.get("tool") == "automic_execution":
            if isinstance(res, dict) and res.get("ok") is not False and isinstance(res.get("content"), str):
                rep = res
            elif isinstance(res, dict):
                rep_err = res.get("error")
    if search is None:
        return None
    items = [x for x in (search.get("items") or []) if isinstance(x, dict)]
    obj = (items[0].get("object_name") if items else None) or ""
    if len(items) < 2:
        n = len(items)
        return (f"**`{obj}` için önceki bir çalışma yok:** kayıtlarda yalnızca {n} çalışma var." if not english
                else f"**No earlier run for `{obj}`:** only {n} run on record.") if obj else None
    prev = items[1]
    name = prev.get("object_name") or obj
    start = _fmt_ts_local(prev.get("start_time") or prev.get("activation_time"))
    end = _fmt_ts_local(prev.get("end_time"))
    dur = fmt_duration(prev.get("duration_sec")) if prev.get("duration_sec") is not None else ""
    cls = str(prev.get("status_class") or "")
    code = prev.get("status_code")
    rc = prev.get("return_code")
    state = ({"ok": "başarıyla tamamlandı", "failed": "hatayla bitti", "cancelled": "iptal edildi"}.get(cls, "çalışıyor")
             if not english else
             {"ok": "completed successfully", "failed": "ended with an error", "cancelled": "was cancelled"}.get(cls, "is running"))
    head = (f"**`{name}` bir önceki çalışması (`RunID {prev.get('run_id')}`):** {start} tarihinde başladı, {state}"
            if not english else
            f"**`{name}` previous run (`RunID {prev.get('run_id')}`):** started {start}, {state}")
    bits = []
    if end:
        bits.append(f"bitiş {end}" if not english else f"ended {end}")
    if dur:
        bits.append(f"süre {dur}" if not english else f"duration {dur}")
    if prev.get("agent"):
        bits.append(f"agent `{prev['agent']}`")
    if cls == "failed" and code is not None:
        bits.append(f"durum kodu {code}" if not english else f"status code {code}")
    if rc is not None and cls == "failed":
        bits.append(f"dönüş kodu (return code) {rc}" if not english else f"return code {rc}")
    out = head + (" · " + " · ".join(bits) if bits else "") + "."
    # Rapor
    if rep is not None:
        lines = _report_lines(rep.get("content") or "")
        sig = rep.get("error_signature")
        rtype = rep.get("report_type") or "REP"
        if lines:
            body = "\n".join(f"- `{str(ln).replace(chr(96), chr(39))[:220]}`" for ln in lines)
            out += (f"\n\n**Rapor** ({rtype}) — hata satırları:\n{body}" if not english
                    else f"\n\n**Report** ({rtype}) — error lines:\n{body}")
        else:
            out += (f"\n\n**Rapor** ({rtype}) maskeli kırpıntısı mevcut; içinde hata satırı yok." if not english
                    else f"\n\n**Report** ({rtype}) excerpt is available; it contains no error lines.")
        if sig:
            out += (f"\n\n**Hata imzası:** `{str(sig)[:200]}`" if not english else f"\n\n**Error signature:** `{str(sig)[:200]}`")
    elif rep_err:
        out += (f"\n\n**Rapor alınamadı:** {rep_err}" if not english else f"\n\n**Report unavailable:** {rep_err}")
    else:
        out += ("\n\n**Rapor bilgisi alınamadı.**" if not english else "\n\n**Report information could not be retrieved.**")
    return out


def plan_deterministic(message: str, *, profile: Optional[str] = None) -> List[Tuple[str, Dict[str, Any]]]:
    """Basit profil için LLM'siz araç planı."""
    from app.services.automic.chat_support import detect_range

    profile = profile or classify_question(message)
    msg = message or ""
    rng = detect_range(msg)
    obj_m = _OBJ_RE.search(msg)
    obj = obj_m.group(0) if obj_m else None
    agent_m = _AGENT_RE.search(msg)
    agent = agent_m.group(0) if agent_m else None

    if profile == "infra":
        if re.search(r"(?i)\bpwp\b|\bengine\b", msg):
            return [("automic_infrastructure", {"aspect": "engines"})]
        if obj and re.search(r"(?i)sunucu|agent|host|nerede", msg):
            return [("automic_infrastructure", {
                "aspect": "object_host", "object_name": obj,
                "range": "7d" if rng == "24h" else rng,
            })]
        if re.search(r"(?i)kopuk", msg):
            # "kopuk" = disconnected (altyapı ekranıyla aynı filtre); "missing" = kayıt kayboldu, kopuk DEĞİL
            return [("automic_infrastructure", {"aspect": "agents", "status": "disconnected"})]
        if agent or re.search(r"(?i)ba[ğg]l[ıi]", msg):
            return [("automic_infrastructure", {"aspect": "agents"})]
        return [("automic_infrastructure", {"aspect": "engines"})]

    if profile == "list":
        if re.search(r"(?i)en\s+[cç]ok\s+hata|top\s*\d+|ortak\s+nokta", msg):
            return [("automic_history", {"template_id": "top_failed_objects", "range": rng if rng != "24h" else "7d", "limit": 5})]
        args: Dict[str, Any] = {"status_class": "failed", "range": rng, "limit": 50, "sort": "end_desc"}
        if obj:
            args["object_name"] = obj
        return [("automic_search_executions", args)]

    if profile == "yesno":
        args = {"range": "30d", "limit": 20, "sort": "end_desc"}
        if obj:
            args["object_name"] = obj
        if re.search(r"(?i)hata|fail", msg):
            # Universe için status filtresi YOK — oran doğru olsun; istenirse failed de ayrı
            pass
        return [("automic_search_executions", args)]

    if profile == "lastrun":
        args = {"object_name": obj, "sort": "end_desc", "limit": 1, "range": "30d"} if obj else {}
        return [("automic_search_executions", args)] if obj else []

    if profile == "active":
        args = {"limit": 500}
        if obj:
            args["object_name"] = obj
        if agent:
            args["agent"] = agent
        return [("automic_active", args)]

    if profile == "prevrun":
        # Nesne mesajda yoksa takip bağlamından (zorunlu filtre) gelir; son 2 çalışma, zaman sınırı geniş
        from app.services.automic.followup_context import forced_filters
        o = obj or (forced_filters() or {}).get("object_name")
        if not o:
            return []
        return [("automic_search_executions", {"object_name": o, "sort": "end_desc", "limit": 2, "range": "30d"})]

    if profile == "count":
        args = {"range": rng, "limit": 10}
        if re.search(r"(?i)hata|fail", msg):
            args["status_class"] = "failed"
        if obj:
            args["object_name"] = obj
        if re.search(r"(?i)aktif|[sş]u\s*an|running", msg):
            return [("automic_active", {"limit": 30})]
        return [("automic_search_executions", args)]

    return []


def try_template_answer(message: str, structured: List[Dict[str, Any]], *,
                        english: bool = False,
                        profile: Optional[str] = None) -> Optional[str]:
    """Uygunsa şablon cevap; değilse None (LLM yoluna bırak)."""
    profile = profile or classify_question(message)
    if profile not in ("yesno", "count", "list", "infra", "lastrun", "prevrun", "active"):
        return None
    if profile == "active":
        return _from_active(message, structured, english)
    if profile == "prevrun":
        return _from_prev_run(message, structured, english)
    items = _res_list(structured)
    if not items:
        return None

    # Veri yok / kapsam dışı: "hata yok / 0" DENMEZ — veri kapsamı söylenir (b1: "geçen yıl")
    if profile != "infra":
        for tool, res in items:
            if tool in ("automic_search_executions", "automic_history") and (
                    res.get("data_status") == "NO_DATA_IN_RANGE" or res.get("data_available") is False):
                return _no_data_answer(res, english)

    if profile == "infra":
        for tool, res in items:
            if tool == "automic_infrastructure":
                aspect = ""
                # recent/agents → object_host; servers → engines
                if res.get("agents") is not None and res.get("object_name"):
                    return _from_object_host(res, english)
                if res.get("servers") is not None or res.get("summary_tr") or res.get("active_pwp") is not None:
                    return _from_engines(res, english)
                if res.get("agents") is not None or res.get("status_label") or res.get("chat_note"):
                    return _from_agent_status(res, message, english)
        return None

    if profile == "yesno":
        for tool, res in items:
            if tool == "automic_search_executions":
                return _from_search_yesno(message, res, english)
            if tool == "automic_object" and res.get("stats"):
                st = res["stats"]
                failed = int(st.get("failed") or 0)
                runs = int(st.get("runs") or 0)
                rate = st.get("failure_rate_pct")
                if failed > 0:
                    return (f"**Hayır:** {runs} çalışmanın {tr_n_si(failed)} hatalı"
                            + (f" (%{_fmt_pct(rate)})" if rate is not None else "") + ".")
                return f"**Evet:** {runs} çalışma, hatalı yok."
        return None

    if profile == "list":
        for tool, res in items:
            if tool == "automic_history" and (
                    res.get("template_id") == "top_failed_objects" or res.get("rows")):
                if res.get("template_id") == "top_failed_objects" or "failed" in (res.get("rows") or [{}])[0]:
                    return _from_history_top5(res, english)
            if tool == "automic_search_executions" and (
                    res.get("by_object") is not None or res.get("filtered_by")):
                return _from_search_list(message, res, english)
        return None

    if profile == "lastrun":
        for tool, res in items:
            if tool == "automic_search_executions":
                ans = _from_last_run(message, res, english)
                if ans:
                    return ans
        return None

    if profile == "count":
        for tool, res in items:
            if tool == "automic_search_executions":
                uni = res.get("universe") or {}
                runs = int(uni.get("runs_total") or res.get("runs_total") or res.get("total") or 0)
                failed = int(uni.get("failed_total") or res.get("failed_total") or 0)
                rate = uni.get("failure_rate_pct")
                # Takip ("bunların kaçı X'teydi") durum filtresiyle gelmişse sayılan şey FİLTRELİ kümedir
                fb = res.get("filtered_by") or {}
                sc = str(fb.get("status_class") or "")
                if sc and sc != "all" and not re.search(r"(?i)hata|fail", message or ""):
                    n = int(res.get("filtered_total") if res.get("filtered_total") is not None else res.get("total") or 0)
                    label = {"failed": "hatalı", "ok": "başarılı", "cancelled": "iptal edilmiş"}.get(sc, sc)
                    scope = f" (bu kapsamda toplam {runs} çalışma)" if runs else ""
                    return (f"**{n} {label} çalışma**{scope}." if not english
                            else f"**{n} {sc} runs**{(' (of ' + str(runs) + ' runs in scope)') if runs else ''}.")
                if re.search(r"(?i)hata|fail", message or ""):
                    return (f"**{failed} hatalı çalışma** (toplam {runs}"
                            + (f", %{_fmt_pct(rate)}" if rate is not None else "") + ").")
                return f"**{runs} çalışma** (hatalı {failed})."
            if tool == "automic_active":
                return f"**Şu an {res.get('total', 0)} aktif iş.**"
        return None

    return None


def template_meta(profile: str) -> Dict[str, Any]:
    intent = {
        "yesno": "execution_search", "count": "execution_search", "lastrun": "execution_search",
        "prevrun": "execution_search", "active": "execution_search",
        "list": "failure_analysis",
        "infra": "status_overview",
    }.get(profile, "general_info")
    return {"intent": intent, "severity": "info", "confidence": "high", "scope": {},
            "entities": [], "follow_ups": [], "answer_source": "template"}
