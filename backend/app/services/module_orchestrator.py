"""Unified Yönetici — module-first orkestrasyon (otomatik, kullanıcıya seçim yok).

Tek modül: exclusive uzman (tool + context + persona).
Çok modül: bilinçli kombinasyon (linux+ocp, ocp+virt, linux+virt, …) + join sözleşmesi.
Belirsiz / zayıf sinyalde bile clarify YOK — en olası domain seti açılır; model tool ile doğrular.
Genel kelimeler (disk/cpu) tek başına yanlış modüle kilitlemez; gerekirse multi açılır.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, FrozenSet, List, Optional, Sequence, Set, Tuple


# ── Modül kimlikleri ─────────────────────────────────────────────────────────
MOD_LINUX = "linux"
MOD_WINDOWS = "windows"
MOD_VIRT = "virt"          # vCenter / ESXi / VMware (+ tool domain vcenter)
MOD_OPENSHIFT = "openshift"
MOD_EXADATA = "exadata"

ALL_MODULES = (MOD_LINUX, MOD_WINDOWS, MOD_VIRT, MOD_OPENSHIFT, MOD_EXADATA)

MODULE_TO_DOMAINS: Dict[str, FrozenSet[str]] = {
    MOD_LINUX: frozenset({"linux", "infra"}),
    MOD_WINDOWS: frozenset({"windows", "infra"}),
    MOD_VIRT: frozenset({"vcenter", "infra"}),
    MOD_OPENSHIFT: frozenset({"openshift", "infra"}),
    MOD_EXADATA: frozenset({"linux", "infra"}),  # Exadata SSH linux tools
}

# Güçlü kimlik sinyalleri (yüksek skor)
_STRONG: Dict[str, Tuple[str, ...]] = {
    MOD_LINUX: (
        "linux", "rhel", "centos", "ubuntu", "debian", "rocky", "alma",
        "selinux", "systemctl", "journalctl", "systemd", "ssh ", " ssh",
        "firewalld", "iptables", "dmesg", "kernel panic",
        "df -", "fstab", "lvm", "xfs", "ext4",
    ),
    MOD_WINDOWS: (
        "windows", "winrm", "powershell", "defender", "event log", "olay günlüğü",
        "wsus", "active directory", "iis", "mssql", "hyper-v host os",
    ),
    MOD_VIRT: (
        "vcenter", "vsphere", "esxi", "esx", "vmware", "datastore", "vmotion",
        "sanallaştır", "sanallastir", "hypervisor", "disk rate", "disk requests",
        "virtual machine", "sanal makine", "poweredon", "poweredoff",
        "vmdk", "vdisk", "hard disk", "snapshot",
    ),
    MOD_OPENSHIFT: (
        "openshift", "ocp", "kubernetes", "k8s", "kube", "pod", "pods",
        "namespace", "crashloop", "deployment", "statefulset", "route", "scc",
        "operator", "etcd", "oc get", "kubectl", "kubevirt", "machineconfig",
        "clusterversion", "mtv", "migration toolkit",
    ),
    MOD_EXADATA: (
        "exadata", "cell server", "db node", "asm diskgroup", "oracle rac cell",
    ),
}

# Zayıf / genel — skor ekler ama tek başına tek modüle kilitlemez
_WEAK = (
    "cpu", "ram", "memory", "bellek", "disk", "performans", "performance",
    "kullanım", "usage", "yük", "load", "durum", "status", "özet", "ozet",
    "rapor", "servis", "service", "kaynak", "log", "hata", "error",
    "network", "ağ", "uptime", "latency", "iops", "metrik",
)

# Multi-module niyet kalıpları
_JOIN_KW = (
    "join", "eşleştir", "eslestir", "karşılaştır", "karsilastir", "birlikte",
    "çapraz", "capraz", "hem ", " hem", "ile birlikte", "ve ayrıca",
    "ssh", "guest", "içinden", "icinden", "içinde", "icinde",
    "üzerinde çalışan", "uzerinde calisan", "üzerinde", "uzerinde",
    "misafir", "guest os", "guest disk", "içeriden", "iceriden",
)
_CROSS_MIGRATE = (
    "taşı", "tasi", "migrate", "migration", "mtv", "göç", "goc", "aktar",
)

# Guest OS / SSH ile virt birlikte anıldığında linux de aç
_GUEST_OS_HINT = (
    "ssh", "guest", "df ", " df", "mount", "filesystem", "dosya sistemi",
    "inode", "fstab", "systemctl", "journalctl", "içinden", "icinden",
    "içinde çalışan", "icinde calisan", "guest os", "misafir os",
)

_CONF_SINGLE = 0.78
_CONF_MULTI = 0.72
_CONF_AUTO = 0.62

# vm / vms / vmler / vmlerdeki / vm'nin … (Türkçe ekler + İngilizce çoğul)
_VM_RE = re.compile(
    r"(?<![a-z0-9_])vm(?:s|ler|leri|lerin|lerde|lerdeki|ye|yi|nin|nın|nün|'s|’s)?(?![a-z0-9_])"
    r"|sanal\s*makine|guest\s*os",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ModulePlan:
    mode: str  # single | multi | knowledge  (ambiguous üretilmez — auto resolve)
    modules: Tuple[str, ...]
    domains: FrozenSet[str]
    confidence: float
    reason: str
    join_keys: Tuple[str, ...] = ()
    need_prometheus: bool = False
    need_linux_collect: bool = False
    need_windows_collect: bool = False
    persona_modules: Tuple[str, ...] = ()
    clarify_options: Tuple[str, ...] = ()  # geriye uyum; her zaman boş

    def primary(self) -> Optional[str]:
        return self.modules[0] if self.modules else None


def _norm(msg: str) -> str:
    return (msg or "").lower()


def _score_modules(ml: str) -> Dict[str, float]:
    scores = {m: 0.0 for m in ALL_MODULES}
    for mod, kws in _STRONG.items():
        for kw in kws:
            if kw in ml:
                scores[mod] += 2.0 + min(len(kw), 12) * 0.05
    weak_hit = any(w in ml for w in _WEAK)
    if weak_hit:
        for mod in ALL_MODULES:
            if scores[mod] > 0:
                scores[mod] += 0.35
    # "vm" / "vmlerdeki" / "vms" → güçlü virt (tek başına da single yeter)
    if _VM_RE.search(ml):
        scores[MOD_VIRT] = max(scores[MOD_VIRT], 2.4)
    if "node-exporter" in ml or "prometheus" in ml:
        scores[MOD_LINUX] += 1.5
    return scores


def _wants_multi(ml: str, strong: List[str], soft: List[str]) -> bool:
    pool = list(dict.fromkeys(strong + soft))
    if len(strong) >= 2:
        return True
    virtish = MOD_VIRT in pool or any(
        k in ml for k in ("vcenter", "esxi", "esx", "vmware")
    ) or bool(_VM_RE.search(ml))
    ocpish = MOD_OPENSHIFT in pool or any(
        k in ml for k in ("openshift", "ocp", "kubevirt", "mtv")
    )
    linuxish = MOD_LINUX in pool or any(k in ml for k in _GUEST_OS_HINT)
    winish = MOD_WINDOWS in pool

    if any(k in ml for k in _CROSS_MIGRATE) and virtish and ocpish:
        return True
    if any(k in ml for k in _JOIN_KW) and virtish and (linuxish or ocpish or winish):
        return True
    # VM + guest/SSH/filesystem → virt+linux
    if virtish and any(k in ml for k in _GUEST_OS_HINT):
        return True
    pairs = [
        (MOD_VIRT, MOD_OPENSHIFT),
        (MOD_LINUX, MOD_VIRT),
        (MOD_LINUX, MOD_OPENSHIFT),
        (MOD_WINDOWS, MOD_VIRT),
        (MOD_WINDOWS, MOD_OPENSHIFT),
        (MOD_LINUX, MOD_WINDOWS),
    ]
    for a, b in pairs:
        if a in strong and b in strong:
            return True
        if a in pool and b in pool and any(k in ml for k in _JOIN_KW):
            return True
    return False


def _infer_join_keys(ml: str, modules: Sequence[str]) -> Tuple[str, ...]:
    keys: List[str] = []
    if any(k in ml for k in ("hostname", "host adı", "host adi", "host_name", "esxi")):
        keys.append("hostname")
    if any(k in ml for k in ("vm", "sanal", "guest", "vm_name", "vm adı")) or _VM_RE.search(ml):
        keys.append("vm_name")
    if any(k in ml for k in ("ip", "adres")):
        keys.append("ip")
    if MOD_OPENSHIFT in modules and any(k in ml for k in ("pod", "namespace", "proje")):
        keys.append("pod_name")
        keys.append("namespace")
    if not keys:
        if MOD_VIRT in modules and MOD_LINUX in modules:
            keys = ["vm_name", "hostname", "ip"]
        elif MOD_VIRT in modules and MOD_OPENSHIFT in modules:
            keys = ["vm_name", "hostname"]
        elif MOD_LINUX in modules and MOD_OPENSHIFT in modules:
            keys = ["hostname", "ip", "node_name"]
        else:
            keys = ["hostname", "ip", "name"]
    seen = set()
    out = []
    for k in keys:
        if k not in seen:
            seen.add(k)
            out.append(k)
    return tuple(out)


def _domains_for_modules(modules: Sequence[str]) -> FrozenSet[str]:
    dom: Set[str] = set()
    for m in modules:
        dom |= set(MODULE_TO_DOMAINS.get(m, frozenset({"infra"})))
    return frozenset(dom) if dom else frozenset({"infra"})


def _multi_plan(
    ml: str,
    mods: Tuple[str, ...],
    *,
    reason: str,
    confidence: float = _CONF_MULTI,
) -> ModulePlan:
    domains = _domains_for_modules(mods)
    join_keys = _infer_join_keys(ml, mods)
    need_prom = (MOD_LINUX in mods or MOD_WINDOWS in mods) and any(
        w in ml for w in ("cpu", "ram", "disk", "performans", "metrik", "kaynak", "anlık", "anlik")
    )
    # Saf virt perf kelimeleri linux ile birlikte değilse prom kapalı kalır
    if MOD_VIRT in mods and MOD_LINUX not in mods and MOD_WINDOWS not in mods:
        need_prom = False
    # Esnaf anlık kaynak: linux varsa collect + prom dene (yoksa SSH'ye düşülür)
    try:
        from app.services.data_fetch_ladder import is_live_resource_query
        if is_live_resource_query(ml) and MOD_LINUX in mods:
            need_prom = True
    except Exception:
        pass
    return ModulePlan(
        mode="multi",
        modules=mods,
        domains=domains,
        confidence=confidence,
        reason=reason,
        join_keys=join_keys,
        need_prometheus=need_prom,
        need_linux_collect=MOD_LINUX in mods or MOD_EXADATA in mods,
        need_windows_collect=MOD_WINDOWS in mods,
        persona_modules=mods,
    )


def _single_plan(ml: str, primary: str, *, strong: bool, reason: str) -> ModulePlan:
    domains = _domains_for_modules([primary])
    need_prom = primary in (MOD_LINUX, MOD_WINDOWS, MOD_EXADATA) and any(
        w in ml for w in ("cpu", "ram", "disk", "performans", "metrik", "iops", "latency")
    )
    if primary == MOD_VIRT:
        need_prom = False
    return ModulePlan(
        mode="single",
        modules=(primary,),
        domains=domains,
        confidence=_CONF_SINGLE if strong else 0.65,
        reason=reason,
        join_keys=(),
        need_prometheus=need_prom,
        need_linux_collect=primary in (MOD_LINUX, MOD_EXADATA),
        need_windows_collect=primary == MOD_WINDOWS,
        persona_modules=(primary,),
    )


def plan_modules(message: str, *, skip_ctx: bool = False) -> ModulePlan:
    """Sorudan module-first plan üret — asla kullanıcıya modül seçtirmez."""
    if skip_ctx:
        return ModulePlan(
            mode="knowledge",
            modules=(),
            domains=frozenset({"infra"}),
            confidence=0.9,
            reason="skip_ctx",
        )

    ml = _norm(message)
    if not ml.strip():
        return ModulePlan(
            mode="knowledge",
            modules=(),
            domains=frozenset({"infra"}),
            confidence=0.5,
            reason="empty",
        )

    scores = _score_modules(ml)
    ranked = sorted(scores.items(), key=lambda x: -x[1])
    strong = [m for m, s in ranked if s >= 2.0]
    soft = [m for m, s in ranked if 0.8 <= s < 2.0]

    # Esnaf: anlık kaynak → guest SSH + virt (Prom yoksa SSH şart)
    try:
        from app.services.data_fetch_ladder import is_live_resource_query, wants_guest_os_metrics
        _live_res = is_live_resource_query(ml)
        _guest_m = wants_guest_os_metrics(ml)
    except Exception:
        _live_res, _guest_m = False, False

    if _live_res and _guest_m:
        # Esnaf: anlık kaynak için hem DB/vCenter hem SSH yolları açık olsun
        scores[MOD_LINUX] = max(scores[MOD_LINUX], 2.5)
        scores[MOD_VIRT] = max(scores[MOD_VIRT], 2.2)
        return _multi_plan(
            ml,
            (MOD_VIRT, MOD_LINUX),
            reason="esnaf_live_resource:virt+linux",
            confidence=_CONF_MULTI,
        )

    # Zayıf genel kelime, güçlü/soft yok → virt+linux otomatik keşif (seçim yok)
    if not strong and not soft:
        if any(w in ml for w in _WEAK):
            return _multi_plan(
                ml,
                (MOD_VIRT, MOD_LINUX),
                reason="auto_explore:virt+linux",
                confidence=_CONF_AUTO,
            )
        return ModulePlan(
            mode="knowledge",
            modules=(),
            domains=frozenset({"infra"}),
            confidence=0.7,
            reason="no_module_signal",
        )

    candidates = strong if strong else soft[:1]
    pool = list(dict.fromkeys(strong + soft))

    # Multi?
    if _wants_multi(ml, strong if strong else candidates, soft):
        mods = tuple(strong if len(strong) >= 2 else (strong + soft)[:2])
        if any(k in ml for k in _CROSS_MIGRATE):
            forced: List[str] = []
            if any(k in ml for k in _STRONG[MOD_VIRT]) or MOD_VIRT in mods or _VM_RE.search(ml):
                forced.append(MOD_VIRT)
            if any(k in ml for k in _STRONG[MOD_OPENSHIFT]) or MOD_OPENSHIFT in mods:
                forced.append(MOD_OPENSHIFT)
            if len(forced) >= 2:
                mods = tuple(dict.fromkeys(forced + list(mods)))
        if len(mods) < 2:
            virtish = MOD_VIRT in pool or bool(_VM_RE.search(ml))
            if virtish and any(k in ml for k in _GUEST_OS_HINT):
                mods = tuple(dict.fromkeys([MOD_VIRT, MOD_LINUX]))
            elif ("ssh" in ml or "guest" in ml) and MOD_OPENSHIFT in pool:
                mods = tuple(dict.fromkeys([MOD_OPENSHIFT, MOD_LINUX]))
            elif virtish and MOD_OPENSHIFT in pool:
                mods = tuple(dict.fromkeys([MOD_VIRT, MOD_OPENSHIFT]))
        if len(mods) >= 2:
            return _multi_plan(ml, mods, reason=f"multi:{'+'.join(mods)}")

    # Yakın skorlu iki güçlü aday → seçim sorma; multi aç
    if len(strong) >= 2:
        a, b = strong[0], strong[1]
        if abs(scores[a] - scores[b]) < 0.8:
            return _multi_plan(
                ml,
                (a, b),
                reason=f"auto_multi_tie:{a}+{b}",
                confidence=_CONF_AUTO,
            )

    primary = candidates[0]
    return _single_plan(
        ml,
        primary,
        strong=primary in strong,
        reason=f"single:{primary}",
    )


def persona_addendum(plan: ModulePlan) -> str:
    """Agent system prompt'una eklenecek uzman persona."""
    if plan.mode == "knowledge":
        return (
            "\n\nYÖNETİCİ MODU: Genel teknik soru — canlı envanter tool'u gerekmez; "
            "mühendislik bilginle kısa ve net cevapla.\n"
        )
    labels = {
        MOD_LINUX: "Kıdemli Linux Sysadmin (SSH/systemd/journal — read-only)",
        MOD_WINDOWS: "Kıdemli Windows Admin (WinRM — read-only)",
        MOD_VIRT: (
            "Kıdemli Sanallaştırma Admin (vCenter/ESXi QueryPerf/DB — read-only; "
            "Disk Rate/Requests için vcenter_perf_query; Prometheus node_disk KULLANMA; "
            "VM disk adet/boyut için db_list_vms + db_vm_detail (disks) — RAG uydurma)"
        ),
        MOD_OPENSHIFT: "Kıdemli OpenShift Admin (pod/project/event — read-only)",
        MOD_EXADATA: "Kıdemli Exadata Admin (read-only)",
    }
    if plan.mode == "single":
        lab = labels.get(plan.primary() or "", "Uzman admin")
        extra = ""
        try:
            from app.services.data_fetch_ladder import ladder_system_addendum, is_live_resource_query
            # plan.reason üzerinden değil; persona her single'da hafif — live ise ladder
            if plan.need_linux_collect or plan.primary() == MOD_LINUX:
                extra = ladder_system_addendum(has_prometheus=bool(plan.need_prometheus))
        except Exception:
            pass
        return (
            f"\n\nYÖNETİCİ → TEK MODÜL UZMANI: Bu turda sen {lab} gibi düşün ve cevap ver. "
            f"Diğer platformlara kayma; ama soru çapraz niyet taşırsa ilgili READ-ONLY aracı kullan. "
            f"Kullanıcıya modül seçtirme. Mutate yok.\n"
            f"Modül planı: {plan.reason} (conf={plan.confidence:.2f}).\n"
            f"{extra}"
        )
    # multi
    labs = [labels.get(m, m) for m in plan.modules]
    keys = ", ".join(plan.join_keys) or "hostname, ip, vm_name"
    extra = ""
    try:
        from app.services.data_fetch_ladder import ladder_system_addendum
        if "linux" in plan.modules or "virt" in plan.modules:
            extra = ladder_system_addendum(has_prometheus=bool(plan.need_prometheus))
    except Exception:
        pass
    return (
        "\n\nYÖNETİCİ → ÇOK MODÜL UZMAN ORKESTRASYON (otomatik; kullanıcıya seçim SORMA):\n"
        f"- Aktif uzmanlıklar: {' + '.join(labs)}\n"
        f"- Her bacaktan READ-ONLY veri topla (ilgili tool'lar); mutate yok.\n"
        f"- Sonuçları ortak anahtarla JOIN/MATCH et: [{keys}]. "
        "Eşleşmeyen satırları uydurma; 'eşleşmedi / eksik' diye belirt.\n"
        f"- Tek birleşik tablo/özet üret; hangi alanın hangi SoT'tan geldiğini kısaca etiketle "
        "(vcenter / ssh / ocp / prometheus / db).\n"
        f"- Plan: {plan.reason} | join_keys={keys}\n"
        "- cross_entity_match ile envanter anahtarlarını doğrulayabilirsin.\n"
        "- Eksik alan varsa bir sonraki SoT basamağına geç; RAG ile metrik uydurma.\n"
        f"{extra}"
    )


def collect_flags(plan: ModulePlan) -> Dict[str, bool]:
    """Unified collect kapıları."""
    return {
        "linux": bool(plan.need_linux_collect),
        "windows": bool(plan.need_windows_collect),
        "prometheus": bool(plan.need_prometheus),
        "agentic": plan.mode in ("single", "multi"),
        "clarify": False,  # modül seçimi yok
    }
