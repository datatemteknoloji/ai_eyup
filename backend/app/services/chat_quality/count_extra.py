"""Sayım kuralı ek konuları (Adım 6, K2/K3): OpenShift pod / hatalı pod ve Linux / Windows sunucu.

Pod: kaynak `openshift_workloads` (kind='pod'; senkron prune ile canlıya eşit). Cluster tazeliği
`openshift_clusters.last_sync` ile ölçülür: 3 × `openshift_sync_interval_sec`'ten eski cluster BAYAT sayılır,
toplama girmez, ayrı satırda «güncel sayı bilinmiyor» yazılır. Hatalı pod tanımı `ocp_pod_stats` (araçla aynı).

Sunucu: Linux / Windows modül envanteri tanımı (`platform_scope.get_linux_module_server_ids` /
`get_windows_server_ids`) — modül sayfasıyla aynı sayı. RBAC: `linux` / `windows` modülleri.

Saf kısım (`analyze_extra`, `render_*`) DB'siz test edilir.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.services.chat_quality import ocp_pod_stats as pstats
from app.services.chat_quality.count_scope import TYPE_WORDS, ScopeCatalog, resolve_ocp, scope_label

_POD_RE = re.compile(r"^pod(?:s|lar|ler|u|un|lari|larin|larda|lardaki|lardan|da|daki)?$")
_SERVER_RE = re.compile(r"^(?:sunucu(?:m|muz|lar|larim|larimiz|lari|larin|larda|lardaki|su|yu)?|servers?)$")

# Pod durum filtreleri: anahtar → (eşleşen sözcükler, görünen başlık)
_POD_FAULTY = {"hatali", "sorunlu", "problemli", "calismayan", "basarisiz", "bozuk", "unhealthy", "failing", "faulty"}
_POD_STATUS_WORDS = {
    "running": ({"calisan", "running", "calisiyor"}, "Running"),
    "succeeded": ({"tamamlanmis", "tamamlanan", "succeeded", "completed"}, "Succeeded"),
    "pending": ({"bekleyen", "beklemede", "pending"}, "Pending"),
}
_POD_REASONS = {
    "crashloopbackoff": "CrashLoopBackOff", "imagepullbackoff": "ImagePullBackOff", "errimagepull": "ErrImagePull",
    "error": "Error", "oomkilled": "OOMKilled", "containercreating": "ContainerCreating",
    "createcontainerconfigerror": "CreateContainerConfigError", "runcontainererror": "RunContainerError",
    "podinitializing": "PodInitializing", "evicted": "Evicted", "terminating": "Terminating", "failed": "Failed",
    "unknown": "Unknown",
}
_POD_NEUTRAL = {
    "veren", "olan", "durumunda", "durumundaki", "durumdaki", "halinde", "state", "status", "in", "with",
    "hata", "cluster", "clusterda", "clusterdaki", "clusterinda", "clusterlarda", "kume", "kumede",
}
_SERVER_NEUTRAL = {"modulunde", "modulu", "envanterinde"}

_COUNT = {"kac", "kactir", "kactur"}
_COUNT_NOUNS = {"sayisi", "sayisini", "sayisinin", "adedi", "adedini"}


def linux_ok(platform: Optional[str], allowed_modules: Any = None) -> bool:
    p = (platform or "").strip().lower()
    if p == "linux":
        return True
    if p == "unified":
        return allowed_modules is None or "linux" in set(allowed_modules)
    return False


def windows_ok(platform: Optional[str], allowed_modules: Any = None) -> bool:
    p = (platform or "").strip().lower()
    if p == "windows":
        return True
    if p == "unified":
        return allowed_modules is None or "windows" in set(allowed_modules)
    return False


def has_pod_word(words: Sequence[str]) -> bool:
    return any(_POD_RE.match(w) for w in words)


def has_server_word(words: Sequence[str]) -> bool:
    return any(_SERVER_RE.match(w) for w in words)


def _count_ok(words: Sequence[str]) -> bool:
    k = sum(1 for w in words if w in _COUNT)
    c = sum(1 for w in words if w in _COUNT_NOUNS)
    en = ("how" in words and "many" in words) or ("number" in words and "of" in words)
    if k > 1 or c > 1 or (en and (k or c)):
        return False
    return bool(k or c or en)


def analyze_extra(message: str, mf: str, toks, cat: ScopeCatalog, *, neutral: Set[str],
                  platform: Optional[str], allowed_modules: Any, o_ok: bool):
    """Pod / sunucu sayımı → `count_rules.Plan` veya None. `neutral`: count_rules nötr sözlüğü."""
    from app.services.chat_quality.count_rules import Plan

    words = [t for t, _, _ in toks]
    if not _count_ok(words):
        return None
    if has_pod_word(words):
        return _analyze_pod(message, words, cat, neutral=neutral, o_ok=o_ok, Plan=Plan)
    if has_server_word(words):
        return _analyze_server(words, neutral=neutral, platform=platform, allowed_modules=allowed_modules, Plan=Plan)
    return None


def _analyze_pod(message: str, words: List[str], cat: ScopeCatalog, *, neutral: Set[str], o_ok: bool, Plan):
    if not o_ok:
        return None
    filt = ""
    used: Set[int] = set()

    def _set(f: str, i: int) -> bool:
        nonlocal filt
        if filt and filt != f:
            return False
        filt = f
        used.add(i)
        return True

    for i, w in enumerate(words):
        if w in _POD_FAULTY:
            if not _set("faulty", i):
                return None
        elif w in _POD_REASONS:
            if not _set("reason:" + _POD_REASONS[w], i):
                return None
        else:
            for key, (ws, _) in _POD_STATUS_WORDS.items():
                if w in ws:
                    if not _set("status:" + key, i):
                        return None
    # «hata veren pod» → hatalı
    if not filt and "hata" in words and "veren" in words:
        filt = "faulty"
    sc = resolve_ocp(message, cat, neutral=set(neutral) | _POD_NEUTRAL)
    for i, w in enumerate(words):
        if i in used or i in sc.consumed or _POD_RE.match(w):
            continue
        if w in neutral or w in _POD_NEUTRAL or w in _COUNT or w in _COUNT_NOUNS:
            continue
        if w in TYPE_WORDS["OPENSHIFT_VIRT"]:
            continue
        return None
    return Plan(kind="count", topic="pod", domain="ocp", ocp_scope=sc, pod_filter=filt or "all")


def _analyze_server(words: List[str], *, neutral: Set[str], platform, allowed_modules, Plan):
    l_ok, w_ok = linux_ok(platform, allowed_modules), windows_ok(platform, allowed_modules)
    want: List[str] = []
    for w in words:
        if w == "linux" and "linux" not in want:
            want.append("linux")
        elif w == "windows" and "windows" not in want:
            want.append("windows")
    if not want:
        want = [o for o, ok in (("linux", l_ok), ("windows", w_ok)) if ok]
    if not want or ("linux" in want and not l_ok) or ("windows" in want and not w_ok):
        return None
    for w in words:
        if _SERVER_RE.match(w) or w in ("linux", "windows") or w in neutral or w in _SERVER_NEUTRAL:
            continue
        if w in _COUNT or w in _COUNT_NOUNS:
            continue
        return None
    return Plan(kind="count", topic="server", domain="os", os_kinds=tuple(want))


# ── veri (salt-okunur) ────────────────────────────────────────────────────────────

def ocp_stale_threshold_sec() -> int:
    try:
        from app.services import runtime_settings
        return 3 * int(runtime_settings.get_int("openshift_sync_interval_sec") or 600)
    except Exception:
        return 1800


def _now() -> datetime:
    try:
        from app.services.chat_quality import clock
        return clock.now_aware()
    except Exception:
        return datetime.now(timezone.utc)


def fetch_pod_groups(db, cluster_ids: Optional[Sequence[int]]) -> List[Tuple[int, str, str, int, int]]:
    """(cluster_id, status, reason, restart_count≥eşik?, adet) grupları."""
    from sqlalchemy import text
    where = "kind = 'pod'"
    params: Dict[str, Any] = {"rmin": pstats.PROBLEM_RESTART_MIN}
    if cluster_ids is not None:
        where += " and cluster_id = ANY(:ids)"
        params["ids"] = list(cluster_ids)
    sql = (
        "select cluster_id, coalesce(status,''), coalesce(meta_data->>'reason',''), "
        "case when coalesce(restart_count,0) >= :rmin then 1 else 0 end, count(*) "
        f"from openshift_workloads where {where} group by 1,2,3,4"
    )
    return [(int(a), str(b), str(c), int(d), int(n)) for a, b, c, d, n in db.execute(text(sql), params).all()]


def fetch_cluster_syncs(db) -> Dict[int, Optional[datetime]]:
    from sqlalchemy import text
    return {int(a): b for a, b in db.execute(text("select id, last_sync from openshift_clusters")).all()}


def fetch_server_counts(db, kinds: Sequence[str]) -> Dict[str, Dict[str, int]]:
    """OS türü → {total, vm, physical, os_unknown}. Modül envanteri tanımıyla aynı kimlik kümesi."""
    from app.models.server import Server
    from app.services import platform_scope as ps_
    out: Dict[str, Dict[str, int]] = {}
    for k in kinds:
        ids = ps_.get_linux_module_server_ids(db) if k == "linux" else ps_.get_windows_server_ids(db)
        d = {"total": len(ids), "vm": 0, "physical": 0, "os_unknown": 0}
        if ids:
            for s in db.query(Server.hypervisor_id, Server.server_type, Server.os_type).filter(Server.id.in_(ids)).all():
                if s[0] is not None or (s[1] or "").upper() == "VIRTUAL":
                    d["vm"] += 1
                else:
                    d["physical"] += 1
                if (s[2] or "").strip().lower() in ("", "other", "unknown"):
                    d["os_unknown"] += 1
        out[k] = d
    return out


# ── yerleşim (saf) ────────────────────────────────────────────────────────────────

def _fmt_ts(ts: Optional[datetime]) -> str:
    from app.services.chat_quality.count_rules import _fmt_ts as f
    return f(ts)


def split_clusters(syncs: Dict[int, Optional[datetime]], ids: Sequence[int], now: datetime,
                   threshold_sec: int) -> Tuple[List[int], List[int]]:
    fresh, stale = [], []
    for cid in ids:
        ts = syncs.get(cid)
        if ts is None:
            stale.append(cid)
            continue
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        (stale if (now - ts).total_seconds() > threshold_sec else fresh).append(cid)
    return fresh, stale


def _filter_head(f: str) -> Tuple[str, str]:
    """(başlık, tablo sütunu)"""
    if f == "faulty":
        return "Hatalı pod", "Hatalı"
    if f.startswith("reason:"):
        r = f.split(":", 1)[1]
        return f"{r} durumundaki pod", r
    if f.startswith("status:"):
        lab = _POD_STATUS_WORDS[f.split(":", 1)[1]][1]
        return f"{lab} durumundaki pod", lab
    return "Toplam pod", "Pod"


def _row_match(f: str, status: str, reason: str, high_restart: int) -> bool:
    if f == "all":
        return True
    if f == "faulty":
        return pstats.is_problem(status, reason, pstats.PROBLEM_RESTART_MIN if high_restart else 0)
    if f.startswith("reason:"):
        return pstats.matches_state(status, reason, f.split(":", 1)[1])
    if f.startswith("status:"):
        return (status or "").lower() == f.split(":", 1)[1]
    return False


def render_pods(plan, cat: ScopeCatalog, groups: List[Tuple[int, str, str, int, int]],
                syncs: Dict[int, Optional[datetime]], now: datetime, threshold_sec: int) -> str:
    names = {cid: n for cid, n in cat.ocp_clusters}
    ids = plan.ocp_scope.ocp_ids if plan.ocp_scope.ocp_ids is not None else [cid for cid, _ in cat.ocp_clusters]
    fresh, stale = split_clusters(syncs, ids, now, threshold_sec)
    f = plan.pod_filter or "all"
    head, col = _filter_head(f)
    per: Dict[int, Dict[str, int]] = {cid: {"total": 0, "match": 0, "problem": 0} for cid in ids}
    reasons: Dict[str, int] = {}
    stale_rows: Dict[int, int] = {cid: 0 for cid in stale}
    for cid, st, rs, hr, n in groups:
        if cid not in per:
            continue
        if cid in stale_rows:
            stale_rows[cid] += n
            continue
        per[cid]["total"] += n
        prob = pstats.is_problem(st, rs, pstats.PROBLEM_RESTART_MIN if hr else 0)
        if prob:
            per[cid]["problem"] += n
        if _row_match(f, st, rs, hr):
            per[cid]["match"] += n
            if f in ("faulty", "all") and prob:
                k = pstats.problem_key(st, rs, pstats.PROBLEM_RESTART_MIN if hr else 0)
                reasons[k] = reasons.get(k, 0) + n
    tot = sum(per[c]["total"] for c in fresh)
    match = sum(per[c]["match"] for c in fresh)
    label = scope_label(plan.ocp_scope, cat, domain="ocp")
    if not fresh:
        L = [f"**{head}: güncel sayı bilinmiyor**", "", f"Kapsam: {label}"]
    else:
        n = tot if f == "all" else match
        L = [f"**{head}: {n}**" + ("" if f == "all" else f" (kapsamdaki toplam {tot} pod içinde)"), "", f"Kapsam: {label}"]
        if len(ids) > 1 or stale:
            cols = [col] if f == "all" else [col, "Toplam pod"]
            if f != "faulty":
                cols.append("Hatalı")
            L += ["", "| OpenShift cluster | " + " | ".join(cols) + " | Son senkron |",
                  "|---|" + "---:|" * len(cols) + "---|"]
            for cid in sorted(fresh, key=lambda c: str(names.get(c, c))):
                d = per[cid]
                vals = [d["total"]] if f == "all" else [d["match"], d["total"]]
                if f != "faulty":
                    vals.append(d["problem"])
                L.append(f"| {names.get(cid, cid)} | " + " | ".join(str(v) for v in vals) + f" | {_fmt_ts(syncs.get(cid))} |")
        else:
            cid = fresh[0]
            L.append(f"OpenShift cluster: {names.get(cid, cid)} · son senkron {_fmt_ts(syncs.get(cid))}")
        if f in ("faulty", "all") and reasons:
            items = sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))
            if f == "all":
                L.append("")
                L.append(f"Hatalı pod: **{sum(reasons.values())}** — " + " · ".join(f"{k} {v}" for k, v in items))
            else:
                L += ["", "| Neden / durum | Pod |", "|---|---:|"] + [f"| {k} | {v} |" for k, v in items]
        if f in ("faulty", "all"):
            L += ["", pstats.PROBLEM_DEFINITION_TR]
    if stale:
        mins = threshold_sec // 60
        parts = [f"{names.get(c, c)} (son başarılı senkron {_fmt_ts(syncs.get(c))}; veritabanındaki eski kayıt "
                 f"{stale_rows.get(c, 0)} pod)" for c in stale]
        L += ["", f"Güncel olmayan cluster (toplama katılmadı; sonuç bilinmiyor): " + "; ".join(parts)
              + f". Son senkron {mins} dk'dan eski — cluster'a ulaşılamıyor olabilir."]
    newest = max((syncs.get(c) for c in fresh if syncs.get(c)), default=None)
    L += ["", f"_Kaynak: OpenShift envanter veritabanı (pod kayıtları); son senkron: {_fmt_ts(newest)}._"]
    return "\n".join(L)


_OS_LABEL = {"linux": "Linux", "windows": "Windows"}
_OS_SCOPE = {
    "linux": "Linux modülü envanteri (Windows ve Exadata dışındaki tüm sunucu kayıtları; Linux guest OS'li VM'ler dahil)",
    "windows": "Windows modülü envanteri (işletim sistemi Windows olan ya da WinRM ile bağlanan sunucular)",
}


def render_servers(plan, counts: Dict[str, Dict[str, int]], last_sync: Optional[datetime]) -> str:
    L: List[str] = []
    kinds = list(plan.os_kinds)
    if len(kinds) > 1:
        L.append("**Sunucu sayısı (işletim sistemine göre)**: " + " · ".join(
            f"{_OS_LABEL[k]} **{counts[k]['total']}**" for k in kinds))
        L.append("")
    for k in kinds:
        d = counts[k]
        if len(kinds) == 1:
            L.append(f"**{_OS_LABEL[k]} sunucu: {d['total']}**")
            L.append("")
        else:
            L.append(f"**{_OS_LABEL[k]}: {d['total']}**")
        L.append(f"Kapsam: {_OS_SCOPE[k]}")
        line = f"Dağılım: sanal (VM) **{d['vm']}** · fiziksel **{d['physical']}**"
        if d["os_unknown"]:
            line += f". İşletim sistemi bilgisi boş/diğer: **{d['os_unknown']}** kayıt (bu toplamın içinde)"
        L.append(line)
        L.append("")
    L.append(f"_Kaynak: envanter veritabanı (sunucu kayıtları); son senkron: {_fmt_ts(last_sync)}._")
    return "\n".join(L)
