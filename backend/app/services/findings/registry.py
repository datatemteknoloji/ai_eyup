"""Kontrol kataloğu.

Her bulgu bir `check_id` taşır; başlık/öneri/uyum referansı burada tek yerde
tanımlanır. Dinamik kontroller (CVE, KB, yükseltme yolu) `vuln:` / `kb:` /
`upg:` önekiyle gelir ve başlığını bulgunun kendisinden alır.

Uyum referansları "kanıt eşlemesi"dir — sertifikasyon iddiası değildir.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

PLATFORMS = ("vmware", "olvm", "ocp_virt", "ocp")
CATEGORIES = (
    "capacity", "reclaim", "health", "hardware", "drift",
    "vuln", "known_issue", "upgrade", "compliance",
)
SEVERITIES = ("critical", "high", "medium", "low", "info")
SEVERITY_RANK = {s: i for i, s in enumerate(SEVERITIES)}
RESULTS = ("pass", "fail", "not_measurable")

# ISO/IEC 27001:2022 Ek A + CIS benchmark başlık eşlemesi (kanıt amaçlı)
ISO_CLOCK = "ISO27001:A.8.17"
ISO_LOGGING = "ISO27001:A.8.15"
ISO_CONFIG = "ISO27001:A.8.9"
ISO_VULN = "ISO27001:A.8.8"
ISO_CAPACITY = "ISO27001:A.8.6"
ISO_REDUNDANCY = "ISO27001:A.8.14"
ISO_ACCESS = "ISO27001:A.8.2"
ISO_BACKUP = "ISO27001:A.8.13"

CONTROL_TITLES: Dict[str, str] = {
    ISO_CLOCK: "A.8.17 Saat senkronizasyonu",
    ISO_LOGGING: "A.8.15 Kayıt tutma (logging)",
    ISO_CONFIG: "A.8.9 Yapılandırma yönetimi",
    ISO_VULN: "A.8.8 Teknik zafiyet yönetimi",
    ISO_CAPACITY: "A.8.6 Kapasite yönetimi",
    ISO_REDUNDANCY: "A.8.14 Bilgi işleme tesislerinin yedekliliği",
    ISO_ACCESS: "A.8.2 Ayrıcalıklı erişim hakları",
    ISO_BACKUP: "A.8.13 Bilgi yedekleme",
}

# Otomatik ölçülemeyen ama denetimde sorulan maddeler (manuel inceleme listesi)
MANUAL_REVIEW_ITEMS: List[Dict[str, str]] = [
    {"control": ISO_BACKUP, "title": "Yedekleme kapsamı ve geri dönüş testleri",
     "note": "Veeam entegrasyonu kapsam dışı; yedek raporu ayrıca eklenmeli."},
    {"control": ISO_ACCESS, "title": "vCenter / OLVM Manager rol ve yetki gözden geçirmesi",
     "note": "Rol atamaları dönemsel olarak gözden geçirilmeli (SSO/LDAP grupları)."},
    {"control": ISO_LOGGING, "title": "Merkezi log saklama süresi",
     "note": "Syslog hedefi doğrulanır; saklama süresi SIEM tarafında kanıtlanmalı."},
    {"control": ISO_CONFIG, "title": "Değişiklik onay kayıtları",
     "note": "Sapma ekranı değişikliği gösterir; onay kaydı ITSM tarafındadır."},
]


@dataclass(frozen=True)
class CheckDef:
    id: str
    category: str
    platforms: Tuple[str, ...]
    entity_kind: str
    severity: str
    title_tr: str
    title_en: str
    recommendation_tr: str
    recommendation_en: str = ""
    refs: Tuple[str, ...] = ()
    # Komut taslağı şablonu türü (draft.py içindeki üretici anahtarı)
    draft: Optional[str] = None
    rationale_tr: str = ""


_ALL = ("vmware", "olvm", "ocp_virt")
_V = ("vmware",)
_O = ("olvm",)
_K = ("ocp_virt",)
_OCP = ("ocp",)

_DEFS: List[CheckDef] = [
    # ── Kapasite (tüm sanallaştırma platformları) ────────────────────────────
    CheckDef("cap.cluster.n_plus_one", "capacity", _ALL, "cluster", "critical",
             "Cluster N+1 karşılanmıyor", "Cluster does not satisfy N+1",
             "En büyük host düştüğünde çalışan VM'lerin Memory'si kalan hostlara sığmıyor. "
             "Önce geri kazanım (kapalı/atıl VM, snapshot), sonra right-size, gerekirse host ekleyin.",
             "Running VM memory does not fit if the largest host fails. Reclaim, right-size, then add hosts.",
             refs=(ISO_CAPACITY, ISO_REDUNDANCY),
             rationale_tr="Tek host arızasında HA yeniden başlatma başarısız olur."),
    CheckDef("cap.cluster.mem_runway", "capacity", _ALL, "cluster", "high",
             "Cluster Memory eşiğe yaklaşıyor", "Cluster memory runway is short",
             "Trend devam ederse Memory %85 eşiğine kısa sürede ulaşılır; geri kazanım ve yatırım planlayın.",
             "Memory will hit 85% soon at current trend; plan reclaim and investment.",
             refs=(ISO_CAPACITY,)),
    CheckDef("cap.cluster.cpu_runway", "capacity", _ALL, "cluster", "medium",
             "Cluster CPU eşiğe yaklaşıyor", "Cluster CPU runway is short",
             "CPU %80 eşiğine yaklaşılıyor; CPU ready değerlerini ve oversized VM'leri inceleyin.",
             "CPU nears 80%; review CPU ready and oversized VMs.", refs=(ISO_CAPACITY,)),
    CheckDef("cap.cluster.vcpu_ratio", "capacity", _ALL, "cluster", "low",
             "vCPU:çekirdek oranı yüksek", "High vCPU:core ratio",
             "4:1 üzerindeki oranlarda CPU ready artar; büyük vCPU'lu atıl VM'leri küçültün.",
             "Ratios above 4:1 raise CPU ready; shrink idle large VMs.", refs=(ISO_CAPACITY,)),
    CheckDef("cap.datastore.usage", "capacity", ("vmware", "olvm"), "datastore", "high",
             "Datastore doluluğu yüksek", "Datastore usage is high",
             "Snapshot, sahipsiz disk ve ISO temizliğiyle başlayın; sonra VM taşıma / genişletme.",
             "Start with snapshot/orphan/ISO cleanup, then move VMs or extend.", refs=(ISO_CAPACITY,)),
    CheckDef("cap.datastore.runway", "capacity", ("vmware", "olvm"), "datastore", "high",
             "Datastore doluluk eşiğine yaklaşıyor", "Datastore runway is short",
             "Trende göre %85 eşiğine kısa sürede ulaşılacak.", "Will hit 85% soon at current trend.",
             refs=(ISO_CAPACITY,)),

    # ── Sağlık: VMware ───────────────────────────────────────────────────────
    CheckDef("vmw.cluster.ha_enabled", "health", _V, "cluster", "high",
             "vSphere HA kapalı", "vSphere HA disabled",
             "Cluster ayarlarından vSphere HA'yı etkinleştirin; host arızasında VM'ler otomatik yeniden başlamaz.",
             "Enable vSphere HA; VMs will not restart after a host failure.",
             refs=(ISO_REDUNDANCY,), draft="vmw_ha_enable"),
    CheckDef("vmw.cluster.admission_control", "health", _V, "cluster", "high",
             "HA admission control kapalı", "HA admission control disabled",
             "Admission control kapalıyken failover kapasitesi garanti edilmez; yüzde politikasıyla açın.",
             "Without admission control failover capacity is not reserved.",
             refs=(ISO_REDUNDANCY, ISO_CAPACITY)),
    CheckDef("vmw.cluster.host_monitoring", "health", _V, "cluster", "medium",
             "HA host monitoring kapalı", "HA host monitoring disabled",
             "Bakım dışında host monitoring açık olmalı; aksi halde HA arızayı algılamaz.",
             "Host monitoring must be on outside maintenance.", refs=(ISO_REDUNDANCY,)),
    CheckDef("vmw.cluster.drs_enabled", "health", _V, "cluster", "medium",
             "DRS kapalı", "DRS disabled",
             "DRS kapalıyken yük dengeleme ve bakım modunda otomatik tahliye yapılmaz.",
             "Without DRS no load balancing or automatic evacuation."),
    CheckDef("vmw.cluster.drs_automation", "health", _V, "cluster", "low",
             "DRS otomasyon seviyesi manuel", "DRS automation is manual",
             "Manuel modda öneriler uygulanmaz; partiallyAutomated veya fullyAutomated değerlendirin.",
             "In manual mode recommendations are not applied."),
    CheckDef("vmw.cluster.isolation_address", "health", _V, "cluster", "info",
             "HA izolasyon adresi tanımlı değil", "No custom HA isolation address",
             "Varsayılan gateway erişilemezse izolasyon yanlış algılanabilir; das.isolationaddress tanımlamayı değerlendirin.",
             "Consider das.isolationaddressX if the default gateway is not reliable."),
    CheckDef("vmw.cluster.version_consistency", "health", _V, "cluster", "medium",
             "Cluster içinde farklı ESXi sürümleri", "Mixed ESXi versions in cluster",
             "Aynı cluster'daki hostlar aynı build'de olmalı; vMotion/EVC ve destek açısından risklidir.",
             "Hosts in one cluster should share a build.", refs=(ISO_CONFIG,)),
    CheckDef("vmw.cluster.ntp_consistency", "health", _V, "cluster", "medium",
             "Cluster hostlarında farklı NTP sunucuları", "Inconsistent NTP servers in cluster",
             "Tüm hostlarda aynı NTP kaynağını kullanın.", "Use the same NTP source on all hosts.",
             refs=(ISO_CLOCK, ISO_CONFIG)),
    CheckDef("vmw.cluster.path_policy_consistency", "health", _V, "cluster", "low",
             "Aynı LUN için farklı multipath politikası", "Inconsistent multipath policy for a LUN",
             "Aynı LUN'u gören hostlarda path selection policy aynı olmalı (ör. VMW_PSP_RR).",
             "Hosts sharing a LUN should use the same PSP.", refs=(ISO_CONFIG,)),
    CheckDef("vmw.host.ntp_configured", "health", _V, "host", "high",
             "Host'ta NTP sunucusu tanımlı değil", "No NTP server on host",
             "Saat kayması log korelasyonunu, Kerberos/SSO'yu ve sertifika doğrulamasını bozar.",
             "Clock drift breaks log correlation, SSO and certificates.",
             refs=(ISO_CLOCK,), draft="vmw_ntp_set"),
    CheckDef("vmw.host.ntp_running", "health", _V, "host", "high",
             "NTP servisi çalışmıyor", "NTP service not running",
             "ntpd servisini başlatın ve politikasını 'on' yapın.", "Start ntpd and set policy to on.",
             refs=(ISO_CLOCK,), draft="vmw_ntp_restart"),
    CheckDef("vmw.host.dns_configured", "health", _V, "host", "low",
             "Host'ta DNS sunucusu tanımlı değil", "No DNS server on host",
             "HA ve vCenter iletişimi için DNS gereklidir.", "DNS is required for HA and vCenter.",
             refs=(ISO_CONFIG,)),
    CheckDef("vmw.host.vmotion_vmknic", "health", _V, "host", "medium",
             "vMotion etkin VMkernel yok", "No vMotion-enabled VMkernel",
             "vMotion için ayrılmış vmknic tanımlayın; DRS ve bakım tahliyesi çalışmaz.",
             "Add a vMotion vmknic; DRS and evacuation depend on it."),
    CheckDef("vmw.host.uplink_redundancy", "health", _V, "host", "high",
             "Tek uplink'li sanal switch", "Virtual switch with a single uplink",
             "Kullanımdaki vSwitch'lere en az iki fiziksel uplink bağlayın.",
             "Attach at least two physical uplinks to in-use vSwitches.", refs=(ISO_REDUNDANCY,)),
    CheckDef("vmw.host.storage_path_redundancy", "health", _V, "host", "high",
             "Tek yollu (single-path) LUN", "Single-path LUN",
             "SAN LUN'larının en az iki aktif yolu olmalı; tek HBA/switch arızası erişimi keser.",
             "SAN LUNs need at least two active paths.", refs=(ISO_REDUNDANCY,)),
    CheckDef("vmw.host.connection", "health", _V, "host", "critical",
             "Host bağlantısı yok", "Host disconnected",
             "Host vCenter'a bağlı değil; yönetim ağı ve hostd/vpxa servislerini kontrol edin.",
             "Host is not connected to vCenter; check management network and agents."),
    CheckDef("vmw.host.long_maintenance", "health", _V, "host", "medium",
             "Host uzun süredir bakım modunda", "Host in maintenance for a long time",
             "Bakımdaki host kapasiteden düşülür; işi bittiyse bakımdan çıkarın.",
             "Hosts in maintenance are excluded from capacity."),
    CheckDef("vmw.datastore.accessible", "health", _V, "datastore", "critical",
             "Datastore erişilemiyor", "Datastore inaccessible",
             "Datastore erişilemez durumda; depolama bağlantısını kontrol edin.",
             "Datastore is inaccessible; check storage connectivity."),
    CheckDef("vmw.datastore.cluster_visibility", "health", _V, "datastore", "medium",
             "Paylaşımlı datastore cluster'ın tüm hostlarına bağlı değil",
             "Shared datastore not mounted on all cluster hosts",
             "Eksik hostlarda HA yeniden başlatma ve vMotion bu datastore için çalışmaz.",
             "HA restarts and vMotion fail for hosts missing the mount.", refs=(ISO_REDUNDANCY,)),
    CheckDef("vmw.datastore.overcommit", "health", _V, "datastore", "medium",
             "Datastore thin provisioning aşırı taahhütlü", "Datastore heavily overcommitted",
             "Provisioned / kapasite oranı yüksek; thin diskler büyürse datastore dolar.",
             "Provisioned/capacity ratio is high."),

    # ── Sağlık: OLVM ─────────────────────────────────────────────────────────
    CheckDef("olvm.host.power_management", "health", _O, "host", "high",
             "Host power management (fencing) kapalı", "Host power management disabled",
             "Power management olmadan host arızasında HA VM'leri güvenle yeniden başlatamaz.",
             "Without power management HA cannot safely restart VMs.", refs=(ISO_REDUNDANCY,)),
    CheckDef("olvm.cluster.fencing_policy", "health", _O, "cluster", "high",
             "Cluster fencing politikası kapalı", "Cluster fencing policy disabled",
             "Fencing kapalıyken yanıt vermeyen host izole edilemez.",
             "Unresponsive hosts cannot be fenced.", refs=(ISO_REDUNDANCY,)),
    CheckDef("olvm.cluster.ha_reservation", "health", _O, "cluster", "low",
             "HA reservation kapalı", "HA reservation disabled",
             "HA reservation, failover için yeterli kaynak kalmadığında uyarır; açmayı değerlendirin.",
             "HA reservation warns when failover capacity is gone.", refs=(ISO_CAPACITY,)),
    CheckDef("olvm.cluster.scheduling_policy", "health", _O, "cluster", "info",
             "Scheduling politikası", "Scheduling policy",
             "Bilgi amaçlıdır: politika ve parametreleri kurum standardıyla karşılaştırın.",
             "Informational: compare with your standard."),
    CheckDef("olvm.cluster.version_consistency", "health", _O, "cluster", "medium",
             "Cluster içinde farklı host sürümleri", "Mixed host versions in cluster",
             "Aynı cluster'daki hostlar aynı sürümde olmalı.", "Hosts should share a version.",
             refs=(ISO_CONFIG,)),
    CheckDef("olvm.host.status", "health", _O, "host", "critical",
             "Host çalışır durumda değil", "Host not up",
             "Host 'up' değil; Manager olaylarını ve VDSM servisini kontrol edin.",
             "Host is not up; check Manager events and VDSM."),
    CheckDef("olvm.host.long_maintenance", "health", _O, "host", "medium",
             "Host uzun süredir bakım modunda", "Host in maintenance for a long time",
             "Bakımdaki host kapasiteden düşülür.", "Hosts in maintenance are excluded from capacity."),
    CheckDef("olvm.storage.status", "health", _O, "datastore", "critical",
             "Storage domain aktif değil", "Storage domain not active",
             "Storage domain erişilemez veya inaktif.", "Storage domain is inactive or unreachable."),
    CheckDef("olvm.host.ntp", "health", _O, "host", "medium",
             "Host NTP durumu", "Host NTP status",
             "OLVM Manager API host NTP yapılandırmasını göstermez; host erişimi olmadan ölçülemez.",
             "Manager API does not expose host NTP; needs host access.", refs=(ISO_CLOCK,)),
    CheckDef("olvm.host.multipath", "health", _O, "host", "medium",
             "Host multipath durumu", "Host multipath status",
             "OLVM Manager API yol (path) sayısını göstermez; host erişimi olmadan ölçülemez.",
             "Manager API does not expose path counts.", refs=(ISO_REDUNDANCY,)),

    # ── Sağlık: OpenShift Virtualization ─────────────────────────────────────
    CheckDef("ocpv.vm.eviction_strategy", "health", _K, "vm", "high",
             "VM node drenajında canlı taşınmıyor", "VM is not live-migrated on drain",
             "evictionStrategy: LiveMigrate tanımlayın; aksi halde node bakımında VM kapanır.",
             "Set evictionStrategy: LiveMigrate or the VM stops on node drain.", refs=(ISO_REDUNDANCY,),
             draft="ocpv_eviction"),
    CheckDef("ocpv.vm.live_migratable", "health", _K, "vm", "medium",
             "VM canlı taşınabilir değil", "VM is not live-migratable",
             "LiveMigratable=False; genellikle RWO disk, host device veya SR-IOV nedeniyle. Gerekçeyi inceleyin.",
             "LiveMigratable=False, usually RWO volume or host devices."),
    CheckDef("ocpv.vm.run_strategy", "health", _K, "vm", "low",
             "VM runStrategy manuel", "VM runStrategy is Manual",
             "Manual runStrategy ile VM node arızasında otomatik başlatılmaz.",
             "Manual runStrategy VMs are not auto-restarted."),
    CheckDef("ocpv.platform.hco_health", "health", _K, "platform", "high",
             "OpenShift Virtualization (HyperConverged) sağlıksız", "HyperConverged not healthy",
             "HyperConverged Available=False veya Degraded=True; operator durumunu inceleyin.",
             "HyperConverged is unavailable or degraded."),

    # ── Donanım riski ────────────────────────────────────────────────────────
    CheckDef("hw.host.sensor_alarm", "hardware", ("vmware",), "host", "high",
             "Donanım sensörü uyarıda", "Hardware sensor alarm",
             "Sensör sarı/kırmızı; vendor destek kaydı açın ve VM'leri planlı tahliye edin.",
             "Sensor yellow/red; open a vendor case and plan evacuation."),
    CheckDef("hw.host.overall_status", "hardware", ("vmware", "olvm"), "host", "medium",
             "Host genel durumu sağlıksız", "Host overall status not green",
             "Host durumunu ve yapılandırma uyarılarını inceleyin.", "Review host status and config issues."),
    CheckDef("hw.host.config_issue", "hardware", ("vmware",), "host", "low",
             "Host yapılandırma uyarısı", "Host configuration issue",
             "vCenter'ın raporladığı configIssue maddelerini giderin.", "Resolve reported config issues."),
    CheckDef("hw.host.event_pattern", "hardware", ("vmware", "olvm"), "host", "medium",
             "Tekrarlayan donanım olayı", "Recurring hardware events",
             "Son 14 günde tekrarlayan donanım olayları; arıza öncesi belirti olabilir.",
             "Recurring hardware events in the last 14 days may precede a failure."),

    # ── Geri kazanım ─────────────────────────────────────────────────────────
    CheckDef("reclaim.vm.snapshot_age", "reclaim", ("vmware", "olvm"), "vm", "medium",
             "Eski snapshot", "Old snapshot",
             "Snapshot yedek değildir; delta disk büyür ve performansı düşürür. Konsolide edin/silin.",
             "Snapshots are not backups; consolidate/remove.", draft="vmw_snapshot_remove"),
    CheckDef("reclaim.file.orphan_disk", "reclaim", ("vmware", "olvm", "ocp_virt"), "file", "medium",
             "Sahipsiz disk", "Orphaned disk",
             "Hiçbir VM/şablon tarafından kullanılmayan disk. Sahibini doğrulayıp arşivleyin veya silin.",
             "Disk not used by any VM/template. Verify owner, archive or delete."),
    CheckDef("reclaim.file.unused_iso", "reclaim", ("vmware", "olvm"), "file", "low",
             "Kullanılmayan ISO", "Unused ISO",
             "Hiçbir VM'e bağlı olmayan ISO; merkezi kütüphaneye taşıyın veya silin.",
             "ISO not attached to any VM."),

    # ── Sapma ────────────────────────────────────────────────────────────────
    CheckDef("drift.entity.baseline", "drift", _ALL + _OCP, "any", "medium",
             "Onaylı temel yapılandırmadan sapma", "Deviation from approved baseline",
             "Değişikliği doğrulayın: onaylıysa yeni temel olarak işaretleyin, değilse geri alın.",
             "Verify: accept as new baseline or revert.", refs=(ISO_CONFIG,)),

    # ── Denetim (uyum) ───────────────────────────────────────────────────────
    CheckDef("cmp.host.ssh_disabled", "compliance", _V, "host", "medium",
             "ESXi SSH servisi açık", "ESXi SSH service running",
             "SSH yalnızca bakım süresince açılmalı; politikası 'off' olmalı.",
             "SSH should be off outside maintenance.", refs=(ISO_ACCESS, ISO_CONFIG), draft="vmw_ssh_stop"),
    CheckDef("cmp.host.shell_disabled", "compliance", _V, "host", "low",
             "ESXi Shell servisi açık", "ESXi Shell running",
             "ESXi Shell kapalı olmalı.", "ESXi Shell should be off.", refs=(ISO_ACCESS,)),
    CheckDef("cmp.host.lockdown_mode", "compliance", _V, "host", "low",
             "Lockdown mode kapalı", "Lockdown mode disabled",
             "Kurum politikası gerektiriyorsa normal lockdown mode etkinleştirin.",
             "Enable normal lockdown if policy requires.", refs=(ISO_ACCESS,)),
    CheckDef("cmp.host.syslog_remote", "compliance", _V, "host", "medium",
             "Uzak syslog hedefi tanımlı değil", "No remote syslog target",
             "Syslog.global.logHost ile merkezi log hedefi tanımlayın.",
             "Set Syslog.global.logHost.", refs=(ISO_LOGGING,), draft="vmw_syslog_set"),
    CheckDef("cmp.platform.time_source", "compliance", ("olvm", "ocp_virt"), "platform", "low",
             "Saat kaynağı kanıtı", "Time source evidence",
             "Manager/kube API saat yapılandırmasını göstermez; host/MachineConfig kanıtı manuel eklenmeli.",
             "Time config is not exposed via API; attach manual evidence.", refs=(ISO_CLOCK,)),

    # ── OpenShift platform dalgası ───────────────────────────────────────────
    CheckDef("ocp.cluster.n_plus_one", "capacity", _OCP, "cluster", "critical",
             "Worker N+1 karşılanmıyor", "Workers do not satisfy N+1",
             "En büyük worker drenajında pod request'leri kalan worker'lara sığmıyor.",
             "Pod requests do not fit if the largest worker is drained.", refs=(ISO_CAPACITY,)),
    CheckDef("ocp.cluster.request_pressure", "capacity", _OCP, "cluster", "high",
             "Worker request doluluğu yüksek", "High worker request allocation",
             "Allocatable'a göre request %85 üzerinde; yeni pod'lar planlanamayabilir.",
             "Requests above 85% of allocatable.", refs=(ISO_CAPACITY,)),
    CheckDef("ocp.namespace.quota", "capacity", _OCP, "namespace", "medium",
             "Namespace kotası dolmak üzere", "Namespace quota nearly exhausted",
             "ResourceQuota kullanımı %90 üzerinde.", "ResourceQuota usage above 90%."),
    CheckDef("ocp.pvc.unbound", "reclaim", _OCP, "pvc", "low",
             "Bağlanmamış (Pending/Lost) PVC", "Unbound PVC",
             "Pending/Lost PVC'leri temizleyin veya StorageClass sorununu giderin.",
             "Clean up Pending/Lost PVCs."),
    CheckDef("ocp.pvc.unused", "reclaim", _OCP, "pvc", "low",
             "Hiçbir pod tarafından kullanılmayan PVC", "PVC not used by any pod",
             "Sahibini doğrulayın; gereksizse silin.", "Verify owner; delete if not needed."),
    CheckDef("ocp.pod.over_request", "reclaim", _OCP, "namespace", "low",
             "Request'i kullanımın çok üzerinde olan iş yükü", "Over-requested workload",
             "CPU/Memory request'lerini gerçek kullanıma göre düşürün.", "Right-size requests."),
    CheckDef("ocp.operator.health", "health", _OCP, "operator", "high",
             "ClusterOperator sağlıksız", "ClusterOperator unhealthy",
             "Available=False / Degraded=True; operator loglarını inceleyin.", "Inspect operator."),
    CheckDef("ocp.node.condition", "health", _OCP, "node", "high",
             "Node koşulu sağlıksız", "Node condition unhealthy",
             "NotReady veya Memory/Disk/PID baskısı.", "NotReady or pressure condition."),
    CheckDef("ocp.mcp.degraded", "drift", _OCP, "mcp", "high",
             "MachineConfigPool sapmada / degraded", "MachineConfigPool degraded",
             "MCP Degraded veya güncellenemeyen makine var; MachineConfig değişikliğini inceleyin.",
             "MCP is degraded.", refs=(ISO_CONFIG,)),
    CheckDef("ocp.cluster.update_available", "upgrade", _OCP, "cluster", "info",
             "Küme güncellemesi mevcut", "Cluster update available",
             "Kanal üzerinde yeni sürüm var; yükseltme planını değerlendirin.", "Plan the upgrade.",
             refs=(ISO_VULN,)),
    CheckDef("ocp.compliance.result", "compliance", _OCP, "rule", "medium",
             "Compliance Operator kuralı başarısız", "Compliance Operator rule failed",
             "ComplianceCheckResult FAIL; kural açıklamasındaki düzeltmeyi uygulayın.", "Apply remediation.",
             refs=(ISO_CONFIG,)),
]

CHECKS: Dict[str, CheckDef] = {d.id: d for d in _DEFS}

_DYNAMIC_PREFIX_CATEGORY = {"vuln:": "vuln", "kb:": "known_issue", "upg:": "upgrade"}


def get_check(check_id: str) -> Optional[CheckDef]:
    return CHECKS.get(check_id)


def category_of(check_id: str) -> str:
    d = CHECKS.get(check_id)
    if d:
        return d.category
    for pfx, cat in _DYNAMIC_PREFIX_CATEGORY.items():
        if check_id.startswith(pfx):
            return cat
    return "health"


def catalog(locale: str = "tr") -> List[Dict[str, object]]:
    en = locale == "en"
    return [
        {
            "id": d.id,
            "category": d.category,
            "platforms": list(d.platforms),
            "entity_kind": d.entity_kind,
            "severity": d.severity,
            "title": d.title_en if en and d.title_en else d.title_tr,
            "recommendation": d.recommendation_en if en and d.recommendation_en else d.recommendation_tr,
            "refs": list(d.refs),
            "has_draft": bool(d.draft),
        }
        for d in _DEFS
    ]
