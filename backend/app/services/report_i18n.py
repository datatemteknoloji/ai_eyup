"""Hazır rapor içeriği (OpenShift + Yönetici «Tüm Ortamlar») için Türkçe → İngilizce çeviri katmanı.

Rapor üreticileri (`ocp_report_engine`, `exec_catalog_reports`) Türkçe metin üretir ve KAYDEDİLEN veri Türkçe kalır
(tek kanonik biçim: geçmiş/önbellek tutarlı). Arayüz dili İngilizce ise çıktı sınırında (`translate_report`)
çevrilir: başlıklar, KPI etiketleri, sütun adları, durum sözcükleri, notlar, öneriler, kapsam-dışı nedenleri.

Kurallar:
  * Tam eşleşme (`EN`) önce; sonra `{}` yer tutuculu şablonlar (f-string iskeletleri) — yakalanan değerler (sayı,
    küme/pod/sunucu adı) ÇEVRİLMEZ, olduğu gibi taşınır.
  * Bilinmeyen metin değişmeden kalır (Türkçe) — varlık adları gibi kullanıcı verisi asla çevrilmez.
  * `module` alanı ve sözlük anahtarları (`applicability` kimlikleri, `report_type`) DEĞİŞMEZ: arayüz modül adını
    kendi i18n sözlüğünden çizer.
  * Kapsam testi (`test_report_i18n.py`): iki motordaki her kullanıcıya dönük sabit metin burada karşılığa sahip olmalıdır.
"""
from __future__ import annotations

import copy
import re
from typing import Any, Callable, Dict, List, Optional, Tuple

# ── Tam eşleşme + şablon (`{}`) çevirileri ─────────────────────────────────────
EN: Dict[str, str] = {
    # Başlıklar — OpenShift
    "OpenShift Executive Summary": "OpenShift Executive Summary",
    "OpenShift Kapasite Raporu": "OpenShift Capacity Report",
    "OpenShift Kapasite Tahmin": "OpenShift Capacity Forecast",
    "OpenShift Kapasite Planı (N+1)": "OpenShift Capacity Plan (N+1)",
    "OpenShift Risk Dashboard": "OpenShift Risk Dashboard",
    "OpenShift En Riskli Varlıklar": "OpenShift Riskiest Assets",
    "OpenShift Proje (Namespace) Kullanımı": "OpenShift Project (Namespace) Usage",
    "OpenShift Depolama (PVC)": "OpenShift Storage (PVC)",
    "OpenShift Workload Sağlığı": "OpenShift Workload Health",
    "OpenShift Sanal Makine (KubeVirt)": "OpenShift Virtual Machines (KubeVirt)",
    "OpenShift Uyum ve Güncelleme": "OpenShift Compliance and Updates",
    "OpenShift Operasyon Raporu": "OpenShift Operations Report",
    "MTV Migrasyon Raporu": "MTV Migration Report",
    "MTV Migrasyon Hazırlık Raporu": "MTV Migration Readiness Report",
    # Başlıklar — Yönetici
    "Tüm Ortamlar — Yönetici Özeti": "All Environments — Executive Summary",
    "Tüm Ortamlar — Kapasite": "All Environments — Capacity",
    "Tüm Ortamlar — Kapasite Tahmin": "All Environments — Capacity Forecast",
    "Tüm Ortamlar — Risk": "All Environments — Risk",
    "Tüm Ortamlar — En Riskli Varlıklar": "All Environments — Riskiest Assets",
    "Tüm Ortamlar — Operasyon": "All Environments — Operations",
    "Tüm Ortamlar — SLA / Erişilebilirlik": "All Environments — SLA / Availability",
    "Tüm Ortamlar — Yama ve Uyum": "All Environments — Patch and Compliance",
    "Tüm Ortamlar — Geri Kazanım": "All Environments — Reclaim",
    "Tüm Ortamlar — İzleme Kapsamı": "All Environments — Monitoring Coverage",
    "Sanallaştırma → OpenShift Migrasyon (MTV)": "Virtualization → OpenShift Migration (MTV)",
    # Modül adları (markdown/metin içinde; `module` alanı arayüzde i18n ile çizilir)
    "Sanallaştırma": "Virtualization",
    "OpenShift": "OpenShift",
    "Linux": "Linux",
    "Windows": "Windows",
    "Exadata": "Exadata",
    # Durum / aşama sözcükleri
    "Başarılı": "Succeeded",
    "BAŞARISIZ": "FAILED",
    "Çalışıyor": "Running",
    "Hazır": "Ready",
    "Doğrulanıyor": "Validating",
    "Arşivlendi": "Archived",
    "Silindi": "Deleted",
    "Başarısız": "Failed",
    "Geçen": "Passed",
    "Manuel/N/A": "Manual/N/A",
    "Kritik": "Critical",
    "Uyarı": "Warning",
    "Yüksek": "High",
    "Orta": "Medium",
    "Düşük": "Low",
    "Bilgi": "Info",
    "Normal": "Normal",
    "Dikkat": "Attention",
    "Sağlıklı": "Healthy",
    "Yeterli": "Sufficient",
    "Sınırda": "Borderline",
    "Yetersiz": "Insufficient",
    "Sığar (N+1 sonrası)": "Fits (after N+1)",
    "Sığmaz": "Does not fit",
    "Eşik üstü": "Above threshold",
    "eşik aşıldı": "threshold exceeded",
    "Güncel": "Up to date",
    "Güncelleme var": "Update available",
    "Bilinmiyor": "Unknown",
    "Evet": "Yes",
    "Hayır": "No",
    "Sıcak": "Warm",
    "Soğuk": "Cold",
    "Veri yok": "No data",
    "veri yok": "no data",
    "ölçülemedi": "not measured",
    "Veri okunamadı": "Data could not be read",
    "Cluster yok": "No cluster",
    "Kurulu": "Installed",
    "Kurulu değil / veri yok": "Not installed / no data",
    # Ortak etiketler / sütunlar
    "Cluster": "Cluster",
    "Varlık": "Asset",
    "Kontrol": "Check",
    "Ayrıntı": "Detail",
    "Proje": "Project",
    "Pod": "Pod",
    "Durum": "Status",
    "Restart": "Restarts",
    "Node": "Node",
    "Rol": "Role",
    "Önem": "Severity",
    "Kaynak": "Resource",
    "Plan": "Plan",
    "Skor": "Score",
    "Seviye": "Level",
    "Sonuç": "Result",
    "Neden": "Reason",
    "Hafta": "Week",
    "Aşama": "Stage",
    "Başlık": "Title",
    "Oluşturulma": "Created",
    "Başlangıç": "Start",
    "Bitiş": "End",
    "Soğuk/Sıcak": "Cold/Warm",
    "Kümede": "In cluster",
    "Tür": "Type",
    "Gün": "Day",
    "Olay": "Events",
    "Sürüm": "Version",
    "Güncelleme": "Update",
    "Adet": "Count",
    "Quota": "Quota",
    "Doluluk %": "Utilization %",
    "Alan": "Area",
    "Envanter": "Inventory",
    "Eşik": "Threshold",
    "Hedef": "Target",
    "Toplam": "Total",
    "Küme": "Cluster",
    "Sunucu": "Server",
    "Host": "Host",
    "Datastore": "Datastore",
    "Rack": "Rack",
    "DB düğümü": "DB node",
    "Cell": "Cell",
    "SLA": "SLA",
    "Risk": "Risk",
    "Exporter": "Exporter",
    "Memory": "Memory",
    "CPU": "CPU",
    "vCPU": "vCPU",
    "VM": "VM",
    "PVC": "PVC",
    "N+1": "N+1",
    "Deployment": "Deployment",
    "Route": "Route",
    "StorageClass": "StorageClass",
    "KubeVirt VM": "KubeVirt VM",
    "Degraded operator": "Degraded operators",
    "Degraded MCP": "Degraded MCPs",
    "Memory request %": "Memory request %",
    "CPU request %": "CPU request %",
    "CPU kullanım %": "CPU usage %",
    "Memory kullanım %": "Memory usage %",
    "CPU request": "CPU request",
    "CPU kullanım": "CPU usage",
    "CPU kullanım % (ort.)": "CPU usage % (avg.)",
    "Memory kullanım % (ort.)": "Memory usage % (avg.)",
    "Memory kullanım (GB)": "Memory usage (GB)",
    "CPU allocatable (çekirdek)": "CPU allocatable (cores)",
    "Memory allocatable (GB)": "Memory allocatable (GB)",
    "Memory request (GB)": "Memory request (GB)",
    "CPU (çekirdek)": "CPU (cores)",
    "Memory (GB)": "Memory (GB)",
    "CPU %": "CPU %",
    "Memory %": "Memory %",
    "3g ort. CPU %": "3d avg. CPU %",
    "3g ort. Memory %": "3d avg. Memory %",
    "Boyut (GB)": "Size (GB)",
    "Worker (kullanılabilir/toplam)": "Workers (available/total)",
    "Yüksek kullanımlı node (≥%85)": "High-usage nodes (≥85%)",
    "Şimdi %": "Now %",
    "Seri uzunluğu": "Series length",
    "Trend güveni": "Trend confidence",
    "Günlük eğim (%/gün)": "Daily slope (%/day)",
    "Eşiğe kalan (aralık)": "Time to threshold (range)",
    "12 ay içinde eşiğe varan": "Reaching threshold within 12 months",
    "Tek worker (N+1 yok)": "Single worker (no N+1)",
    "N+1 yetersiz": "N+1 insufficient",
    "Gereken ek worker (toplam)": "Additional workers needed (total)",
    "Gereken ek worker": "Additional workers needed",
    "Bulgu türüne göre": "By finding type",
    "Riskli node": "Risky nodes",
    "Riskli pod": "Risky pods",
    "Hazır olmayan node": "Nodes not ready",
    "Açık bulgu": "Open findings",
    "Öncelikli bulgular": "Priority findings",
    "Riskli pod'lar": "Risky pods",
    "En riskli node'lar (son 30 gün olayları)": "Riskiest nodes (events, last 30 days)",
    "En riskli pod'lar": "Riskiest pods",
    "Proje (kullanıcı)": "Projects (user)",
    "Quota ≥ %90": "Quota ≥ 90%",
    "Over-request proje": "Over-requested projects",
    "En çok Memory kullanan projeler (anlık)": "Top Memory-consuming projects (current)",
    "Quota doluluk": "Quota utilization",
    "Request'i kullanımdan çok yüksek projeler": "Projects with requests far above usage",
    "Taranan cluster": "Clusters scanned",
    "Bağlanmamış PVC": "Unbound PVCs",
    "Kullanılmayan PVC": "Unused PVCs",
    "Toplam restart": "Total restarts",
    "Cluster bazında": "By cluster",
    "Pod durum dağılımı": "Pod status distribution",
    "Çalışan": "Running",
    "Yüksek kullanım (≥%90)": "High usage (≥90%)",
    "Atıl aday (3 gün)": "Idle candidates (3 days)",
    "Güncelleme bekleyen cluster": "Clusters awaiting updates",
    "Başarısız uyum kuralı": "Failed compliance rules",
    "Sürüm ve sağlık": "Version and health",
    "Compliance Operator sonuçları": "Compliance Operator results",
    "Olay (30 gün)": "Events (30 days)",
    "Açık incident": "Open incidents",
    "Olay türleri": "Event types",
    "Günlük olay trendi": "Daily event trend",
    "Açık incident'lar": "Open incidents",
    "Taşınan VM (başarılı)": "Migrated VMs (succeeded)",
    "Başarısız VM": "Failed VMs",
    "Çalışan plan": "Running plans",
    "Ort. plan süresi (dk)": "Avg. plan duration (min)",
    "Son 30 gün tamamlanan": "Completed in last 30 days",
    "Plan durumları": "Plan statuses",
    "Başarısız VM'ler ve nedenleri": "Failed VMs and reasons",
    "Haftalık taşınan VM": "VMs migrated per week",
    "Taşıma planları": "Migration plans",
    "Cluster özeti": "Cluster summary",
    "N+1 değerlendirmesi": "N+1 assessment",
    "Genel durum": "Overall status",
    "Şu an sağlıksız": "Currently unhealthy",
    "Son olay": "Last event",
    "Olay sayıları": "Event counts",
    "Bağlanmamış PVC (Pending / Lost)": "Unbound PVCs (Pending / Lost)",
    "Hiçbir pod'un kullanmadığı PVC": "PVCs not used by any pod",
    "PVC durumu": "PVC status",
    "Durum dağılımı": "Status distribution",
    "Yüksek kullanımlı VM'ler": "High-usage VMs",
    "Atıl VM adayları": "Idle VM candidates",
    "KubeVirt VM'ler": "KubeVirt VMs",
    "Mevcut güncellemeler": "Available updates",
    "Kubelet sürümü (farklı)": "Kubelet version (differs)",
    "Taşıma adayları": "Migration candidates",
    "Hedef cluster boşluğu (N+1 sonrası)": "Target cluster headroom (after N+1)",
    "En büyük taşıma adayları": "Largest migration candidates",
    "Node hazır": "Nodes ready",
    "Ort. CPU request %": "Avg. CPU request %",
    "Ort. Memory request %": "Avg. Memory request %",
    "Kullanılabilir worker": "Available workers",
    "En büyük worker": "Largest worker",
    "Memory request % (N+1)": "Memory request % (N+1)",
    "CPU request % (N+1)": "CPU request % (N+1)",
    "Boş Memory (GB)": "Free Memory (GB)",
    "Boş CPU (çekirdek)": "Free CPU (cores)",
    "Talep Memory (GB)": "Requested Memory (GB)",
    "Talep CPU (çekirdek)": "Requested CPU (cores)",
    "Kaynak vCenter": "Source vCenter",
    "Disk (GB)": "Disk (GB)",
    "Planda mı": "In a plan",
    "OpenShift Memory talebi (GB)": "OpenShift Memory request (GB)",
    "Aday VMware VM (açık)": "Candidate VMware VMs (powered on)",
    "Toplam Memory talebi (GB)": "Total Memory request (GB)",
    "Toplam CPU request (çekirdek)": "Total CPU request (cores)",
    "Toplam disk (GB)": "Total disk (GB)",
    "Hedefe sığan cluster": "Clusters that fit the target",
    "Cluster kapasitesi": "Cluster capacity",
    "Eşiğe kalan süre": "Time to threshold",
    "Eşiğe kalan süre (eşik %{})": "Time to threshold (threshold {}%)",
    # Yönetici etiketleri
    "Ortam sağlığı": "Environment health",
    "İzlenen alan": "Monitored areas",
    "Kritik varlık (alan toplamı)": "Critical assets (sum of areas)",
    "En düşük skor": "Lowest score",
    "MTV taşınan VM": "MTV migrated VMs",
    "Varlık skoru": "Asset score",
    "Sunucu kaydı bağı": "Server record link",
    "Küme kapasitesi": "Cluster capacity",
    "En riskli 20 varlık (tüm alanlar)": "Top 20 riskiest assets (all areas)",
    "En riskli varlıklar": "Riskiest assets",
    "Açık olaylar ve en riskli varlıklar": "Open events and riskiest assets",
    "Açık kontrol bulguları (kapasite, sağlık, uyum, yükseltme…)": "Open check findings (capacity, health, compliance, upgrades…)",
    "Host metriği (son 1 sa)": "Host metrics (last 1 h)",
    "Node metriği (son 30 dk)": "Node metrics (last 30 min)",
    "Host (kullanılabilir/toplam)": "Hosts (available/total)",
    "Memory taahhüt %": "Memory commitment %",
    "vCPU oranı": "vCPU ratio",
    "VM (açık/toplam)": "VMs (on/total)",
    "Datastore doluluğu (en dolu 8)": "Datastore utilization (fullest 8)",
    "Kurulu kapasite (envanter)": "Installed capacity (inventory)",
    "VMware Tools sürüm durumu (açık VM)": "VMware Tools version status (powered-on VMs)",
    "Bekleyen güncellemeler (kontrol edilen sunucular)": "Pending updates (checked servers)",
    "Bekleyen Windows güncellemeleri (taranan sunucular)": "Pending Windows updates (scanned servers)",
    "Geri kazanım adayları": "Reclaim candidates",
    "Dikkat gerektiren varlıklar": "Assets needing attention",
    "SLA uyumu (hedef %99, 30 gün)": "SLA compliance (target 99%, 30 days)",
    "En düşük erişilebilirlik (alan başına en kötü 5)": "Lowest availability (worst 5 per area)",
    "İzleme kapsamı": "Monitoring coverage",
    "İzleme boşlukları (alan başına ilk 8)": "Monitoring gaps (first 8 per area)",
    "Sanallaştırma: yüksek kullanımlı küme/datastore": "Virtualization: high-usage clusters/datastores",
    "Kapasite (GB)": "Capacity (GB)",
    "Kullanılan %": "Used %",
    "Provizyon %": "Provisioned %",
    "Sunucu kullanımı": "Server usage",
    "Disk (/) %": "Disk (/) %",
    "Disk (/)": "Disk (/)",
    "Exadata envanteri": "Exadata inventory",
    "CPU çekirdek": "CPU cores",
    "Depolama (TB)": "Storage (TB)",
    "Memory şimdi %": "Memory now %",
    "Seri (gün)": "Series (days)",
    "VM araçları sürümü": "VM tools version",
    "Bekleyen güncelleme": "Pending updates",
    "Bekleyen paket": "Pending packages",
    "Yeniden başlatma gerekli": "Reboot required",
    "Windows güncellemeleri": "Windows updates",
    "Bekleyen": "Pending",
    "Yeniden başlatma bekliyor": "Awaiting reboot",
    "Geri kazanım": "Reclaim",
    "Kapalı VM": "Powered-off VMs",
    "Kapalı Memory (GB)": "Powered-off Memory (GB)",
    "Atıl VM": "Idle VMs",
    "Atıl Memory (GB)": "Idle Memory (GB)",
    "Aşırı boyutlu VM": "Oversized VMs",
    "Snapshot (GB)": "Snapshots (GB)",
    "Listelenen varlık": "Listed assets",
    "Kritik olaylı varlık": "Assets with critical events",
    "Açık kritik+uyarı (24 sa)": "Open critical+warning (24 h)",
    "Alan bazında olaylar (30 gün)": "Events by area (30 days)",
    "En sık olay türleri (alan başına ilk 5)": "Most frequent event types (top 5 per area)",
    "SLA'yı sağlayan": "Meeting SLA",
    "Sağlamayan": "Not meeting SLA",
    "Uyum %": "Compliance %",
    "Kritik olay (30 gün)": "Critical events (30 days)",
    "Tahmini erişilebilirlik %": "Estimated availability %",
    "Ölçülen alan": "Areas measured",
    "Kurulu/bağlı": "Installed/connected",
    "Veri akan": "Reporting data",
    "Kapsam %": "Coverage %",
    "Ölçüt": "Basis",
    "Exporter kurulu": "Exporter installed",
    "Veri akıyor": "Data flowing",
    "Dolu datastore (≥%85)": "Full datastores (≥85%)",
    "Yüksek kullanımlı küme": "High-usage clusters",
    "Onaylanan %": "Acknowledged %",
    "Olay türü": "Event type",
    "≥%85 kullanımda": "At ≥85% usage",
    "Metriği olan": "With metrics",
    "Güncel olmayan araç": "Outdated tools",
    "Durumu bilinen / açık VM": "Known status / powered-on VMs",
    "Kontrol edilen": "Checked",
    "Bekleyen paket (toplam)": "Pending packages (total)",
    "Yeniden başlatma bekleyen": "Awaiting reboot",
    "Taranan": "Scanned",
    "Kritik güncelleme": "Critical updates",
    "Bekleyen (toplam)": "Pending (total)",
    "Kapalı VM Memory tahsisi (GB)": "Powered-off VM Memory allocation (GB)",
    "Atıl VM Memory (GB)": "Idle VM Memory (GB)",
    "Açık bulgu yok.": "No open findings.",
    "Yalnız gözlenen Node olay sayısı ve anlık durum; arıza zamanı tahmini yapılmaz.": "Observed Node event counts and current status only; no failure-time prediction is made.",
    "İzleme yok": "No monitoring",
    "Ölçülemedi": "Not measured",
    "(küme yok)": "(no cluster)",
    "Adsız küme": "Unnamed cluster",
    "Geçmişteki eğimin sürdüğünü varsayar; mevsimsellik ve planlı değişim modellenmez.": "Assumes the historical slope continues; seasonality and planned changes are not modelled.",
    "Düşük güven veya 14 günden kısa seride süre yazılmaz. Aralık hızlı–yavaş senaryodur.": "No time estimate is written for low confidence or series shorter than 14 days. The range is a fast–slow scenario.",
    "İzlenen varlık": "Monitored assets",
    "Kritik varlık": "Critical assets",
    "Kritik olay (24 sa)": "Critical events (24 h)",
    "Uyarı olayı (24 sa)": "Warning events (24 h)",
    # Şablonlar ({} = yakalanan değer)
    "{} zaten taşındı": "{} already migrated",
    "{} hazır değil": "{} not ready",
    "{} çalışıyor": "{} running",
    "{} kritik": "{} critical",
    "{} riskli": "{} risky",
    "{} gün": "{} days",
    "{}–{} gün": "{}–{} days",
    "{}/{} gün": "{}/{} days",
    "{} GB": "{} GB",
    "{} plan": "{} plans",
    "{} başarısız": "{} failed",
    "{} sunucu": "{} servers",
    "{} kaynak, {} host, {} VM": "{} sources, {} hosts, {} VMs",
    "{} cluster, {} node": "{} clusters, {} nodes",
    "{} rack, {} node": "{} racks, {} nodes",
    "Node kullanımı — {}": "Node usage — {}",
    "Son tarama: {}": "Last scan: {}",
    "{} node hazır değil: ": "{} nodes not ready: ",
    "{} node hazır değil — kubelet ve node durumunu inceleyin.": "{} nodes not ready — check kubelet and node status.",
    "{} riskli pod var (CrashLoop/ImagePull/çok restart) — Workload Sağlığı raporuna bakın.": "{} risky pods (CrashLoop/ImagePull/many restarts) — see the Workload Health report.",
    "{} kritik bulgu açık — Risk Dashboard'da ayrıntı var.": "{} critical findings open — details in the Risk Dashboard.",
    "Kritik bir aksiyon gerekmiyor; kapasite ve güncelleme raporlarını düzenli gözden geçirin.": "No critical action needed; review the capacity and update reports regularly.",
    "{} cluster'da en büyük worker düşerse request'ler kalan worker'lara sığmıyor — worker ekleyin ya da request'leri azaltın.": "In {} clusters, if the largest worker fails the requests do not fit on the remaining workers — add workers or reduce requests.",
    "{}: tarama özeti yok — request/allocatable hesaplanamadı (Ayarlar › OpenShift taramasını çalıştırın).": "{}: no scan summary — request/allocatable could not be calculated (run the OpenShift scan under Settings).",
    "{}: Memory request %{} — worker eklemeyi veya iş yükü dengelemeyi planlayın.": "{}: Memory request {}% — plan to add workers or rebalance workloads.",
    "{} GB kullanılmayan PVC kapasitesi geri kazanılabilir (silmeden önce sahibiyle doğrulayın).": "{} GB of unused PVC capacity can be reclaimed (confirm with the owner before deleting).",
    "{} VM başarısız — hata nedenlerini inceleyip planı yeniden çalıştırın.": "{} VMs failed — review the error reasons and re-run the plan.",
    "Bu cluster için tamamlanmış tarama yok; request değerleri ölçülemedi.": "No completed scan for this cluster; request values could not be measured.",
    "ölçülemedi (≥2 kullanılabilir worker ve tarama gerekir)": "not measured (needs ≥2 available workers and a scan)",
    "Kayıtlı OpenShift cluster yok.": "No registered OpenShift cluster.",
    "Tamamlanmış tarama yok; PVC verisi ölçülemedi.": "No completed scan; PVC data could not be measured.",
    "Son 30 dakikada VM metriği yok (OpenShift Virtualization kurulu değil veya monitoring senkronu çalışmıyor).": "No VM metrics in the last 30 minutes (OpenShift Virtualization is not installed or the monitoring sync is not running).",
    "Son 30 dakikada pod metriği yok.": "No pod metrics in the last 30 minutes.",
    "Kayıtlı MTV planı yok: MTV kurulu değil, plan oluşturulmamış veya ilk anlık görüntü henüz alınmadı (OpenShift senkronu her 10 dakikada toplar).": "No MTV plans recorded: MTV is not installed, no plan has been created, or the first snapshot has not been taken yet (the OpenShift sync collects every 10 minutes).",
    "Çalışan VMware VM bulunamadı (veya yalnız sentetik/taşınmış VM var).": "No running VMware VMs found (or only synthetic/already-migrated VMs exist).",
    # OpenShift notlar / yöntem
    "Request yüzdesi kullanım değildir; gerçek tüketim Kapasite raporundadır.": "Request percentage is not usage; actual consumption is in the Capacity report.",
    "Request kullanım değildir; ikisi ayrı sütundadır.": "Request is not usage; they are in separate columns.",
    "Request % = pod request toplamı / worker allocatable (son tarama). Kullanım % = metrics.k8s.io son örnek / allocatable (ainew DB).": "Request % = sum of pod requests / worker allocatable (last scan). Usage % = latest metrics.k8s.io sample / allocatable (ainew DB).",
    "Worker node'ların günlük ortalama (ocp_node_daily, ≤400 gün) serisine Theil–Sen eğimi; en az {} gün. Aralık eğimin %25–%75 bandından. Yalnız orta/yüksek güvenli trend projeksiyon üretir.": "Theil–Sen slope of the daily-average series of worker nodes (ocp_node_daily, ≤400 days); at least {} days. The range comes from the 25–75% band of the slope. Only medium/high-confidence trends produce a projection.",
    "Geçmişteki eğimin sürdüğünü varsayar; mevsimsellik ve planlı iş yükü değişimi modellenmez.": "Assumes the historical slope continues; seasonality and planned workload changes are not modelled.",
    "Düşük güven veya 14 günden kısa seride tahmin yazılmaz. Aralık hızlı–yavaş senaryodur; tek kesin tarih değildir.": "No forecast is written for low confidence or series shorter than 14 days. The range is a fast–slow scenario; it is not a single exact date.",
    "En büyük worker düşünce request toplamı / kalan allocatable. Memory veya CPU > %100 yetersiz, > %90 sınırda (kapasite motoru ile aynı karar).": "Total requests / remaining allocatable when the largest worker is lost. Memory or CPU > 100% is insufficient, > 90% borderline (same decision as the capacity engine).",
    "Kural tabanlı bulgular (ocp.* kontrolleri, son tarama) + pod durumu/restart eşikleri. Skor üretilmez; sayılar ve sıralama kuraldır.": "Rule-based findings (ocp.* checks, last scan) + pod status/restart thresholds. No score is produced; the numbers and ordering are the rules.",
    "Node skoru = Σ(olay ağırlığı × sayı) + (şu an sağlıksızsa 5). Yalnız gözlenen olaylar; arıza zamanı tahmini yapılmaz.": "Node score = Σ(event weight × count) + (5 if currently unhealthy). Observed events only; no failure-time prediction is made.",
    "Kullanım: metrics.k8s.io son örnek (ainew DB). Quota/over-request: son tarama bulguları.": "Usage: latest metrics.k8s.io sample (ainew DB). Quota/over-request: last-scan findings.",
    "Anlık metrics-server örneğine göre; kullanım request'in %20'sinin altındaysa listelenir.": "Based on the current metrics-server sample; listed when usage is below 20% of the request.",
    "Son tarama: Pending/Lost PVC bağlanmamış; hiçbir pod'un volume'ünde geçmeyen PVC kullanılmayan sayılır. Depolama toplam kapasitesi (StorageClass backend) ölçülmez.": "Last scan: Pending/Lost PVCs are unbound; a PVC that appears in no pod's volumes counts as unused. Total storage capacity (StorageClass backend) is not measured.",
    "KubeVirt disk PVC'leri (DataVolume/VirtualMachine sahipli) bu listede değildir.": "KubeVirt disk PVCs (owned by DataVolume/VirtualMachine) are not in this list.",
    "Riskli pod: CrashLoopBackOff/ImagePull/OOMKilled/Error/Failed/Unknown/Pending durumu veya ≥5 restart (OpenShift Sağlık sayfasıyla aynı kural).": "Risky pod: CrashLoopBackOff/ImagePull/OOMKilled/Error/Failed/Unknown/Pending status or ≥5 restarts (same rule as the OpenShift Health page).",
    "VM CPU/Memory % = metrics.k8s.io son örnek / tahsis; atıl adayı 3 günlük ortalamadan (en az 50 örnek).": "VM CPU/Memory % = latest metrics.k8s.io sample / allocation; idle candidates come from the 3-day average (at least 50 samples).",
    "Çalışan VM'in 3 günlük ortalaması CPU < %5 ve Memory < %20 ise aday sayılır; karar sahibine aittir.": "A running VM is a candidate if its 3-day average is CPU < 5% and Memory < 20%; the decision belongs to the owner.",
    "Son tarama (clusterversion, clusteroperator, MachineConfigPool, ComplianceCheckResult).": "Last scan (clusterversion, clusteroperator, MachineConfigPool, ComplianceCheckResult).",
    "Sertifikasyon iddiası değildir; denetim için teknik kanıttır.": "Not a certification claim; it is technical evidence for audits.",
    "Son 30 günün OpenShift olayları (en çok 20.000 kayıt örneklenir).": "OpenShift events of the last 30 days (up to 20,000 records are sampled).",
    "MTV Plan/Migration CR'lerinin periyodik anlık görüntüsü (mtv_plan_snapshots). Süre = plan başlangıç → bitiş; yalnız başarılı planlar ortalamaya girer.": "Periodic snapshot of MTV Plan/Migration CRs (mtv_plan_snapshots). Duration = plan start → end; only successful plans enter the average.",
    "Kümeden silinen planlar 'Silindi' olarak kalır; geçmiş ainew'un ilk anlık görüntüsünden başlar.": "Plans deleted from the cluster remain as 'Deleted'; history starts from ainew's first snapshot.",
    "Geçmiş yalnız ainew'un topladığı anlık görüntülerden gelir; MTV öncesi taşımalar görünmez.": "History comes only from snapshots collected by ainew; migrations before MTV are not visible.",
    "Zamanlayıcı kuralları, depolama sınıfı ve ağ eşlemesi modellenmez; hazırlık göstergesidir, taşıma garantisi değildir.": "Scheduler rules, storage class and network mapping are not modelled; this is a readiness indicator, not a migration guarantee.",
    "Talep: VM belleği + virt-launcher yükü (0,002×bellek + 218 MiB + 8 MiB×vCPU); CPU request = vCPU ÷ 10 (varsayılan allocation ratio). Hedef boşluk: ocp.cluster.n_plus_one ile aynı en-büyük-worker varsayımı.": "Request: VM memory + virt-launcher overhead (0.002×memory + 218 MiB + 8 MiB×vCPU); CPU request = vCPU ÷ 10 (default allocation ratio). Target headroom: same largest-worker assumption as ocp.cluster.n_plus_one.",
    "Ek worker sayısı mevcut worker'ların ortalama boyutuna göre hesaplanır; scheduler kuralları (taint, affinity) modellenmez.": "The number of extra workers is calculated from the average size of existing workers; scheduler rules (taint, affinity) are not modelled.",
    "Boş kapasite = en büyük worker düşünce kalan allocatable − mevcut request toplamı. Depolama kapasitesi hedefte ölçülmez.": "Free capacity = remaining allocatable after the largest worker is lost − current total requests. Storage capacity is not measured on the target.",
    # Yönetici notları / yöntem / kapsam
    "Sentetik (ZZ-FAKE) test kaynakları bu rapora dahil edilmez.": "Synthetic (ZZ-FAKE) test sources are not included in this report.",
    "Alan notu: her varlık için ceza = min(100, 30×kritik + 12×uyarı), varlık skoru = 100 − ceza, alan notu varlık skorlarının ortalamasıdır (son 24 saatteki açık olaylar). Ekip raporlarındaki not farklı formülle hesaplanır.": "Area score: per asset penalty = min(100, 30×critical + 12×warning), asset score = 100 − penalty, area score is the mean of asset scores (open events in the last 24 hours). The score in team reports uses a different formula.",
    "Skor yalnız altyapı sağlığını gösterir; ekip performansı değildir. «İzleme yok» alanlar skorlanmaz.": "The score reflects infrastructure health only, not team performance. Areas marked “No monitoring” are not scored.",
    "OpenShift için kullanılabilirlik = 30 gün içinde node'un Ready görüldüğü örnek oranı (olay tahmini değil).": "For OpenShift, availability = share of samples in 30 days where the node was seen Ready (not an event-based estimate).",
    "Sanallaştırma/Linux/Windows/Exadata: SLA olay yoğunluğundan TAHMİN edilir (her kritik olay −%0,5); kesin ölçüm değildir.": "Virtualization/Linux/Windows/Exadata: SLA is ESTIMATED from event density (each critical event −0.5%); it is not an exact measurement.",
    "Hem VM hem Linux olan sunucu iki alanda da görünür (alan toplamları tekilleştirilmez).": "A server that is both a VM and Linux appears in both areas (area totals are not de-duplicated).",
    "{}: kapsam %{} — veri akmayan varlıklarda exporter/bağlantıyı onarın.": "{}: coverage {}% — fix the exporter/connection on assets that are not reporting data.",
    "Sanallaştırma: kapasite planlayıcı (host/datastore). OpenShift: request/allocatable + kullanım. Linux: son 1 saat metriği. Exadata: yalnız kurulu envanter.": "Virtualization: capacity planner (host/datastore). OpenShift: request/allocatable + usage. Linux: last-1-hour metrics. Exadata: installed inventory only.",
    "Günlük ortalama serilerine Theil–Sen eğimi; en az {} gün; aralık eğimin %25–%75 bandından. Yalnız orta/yüksek güvenli trend süre üretir.": "Theil–Sen slope of daily-average series; at least {} days; the range comes from the 25–75% band of the slope. Only medium/high-confidence trends produce a time estimate.",
    "Her alanın kendi son tarama/kontrol verisi: VMware Tools sürümü, OpenShift clusterversion/operatör, Linux Sistem Güncelle işleri, Windows güncelleme taraması.": "Each area's own last scan/check data: VMware Tools version, OpenShift clusterversion/operators, Linux System Update jobs, Windows update scan.",
    "Sanallaştırma: kapalı/atıl/aşırı boyutlu VM ve snapshot (kapasite planlayıcı). OpenShift: bağlanmamış / kullanılmayan PVC.": "Virtualization: powered-off/idle/oversized VMs and snapshots (capacity planner). OpenShift: unbound / unused PVCs.",
    "MTV Plan/Migration anlık görüntüleri (geçmiş) ve VMware VM'lerinin OpenShift hedef kapasitesine (N+1 sonrası) sığma hesabı.": "MTV Plan/Migration snapshots (history) and a fit calculation of VMware VMs against OpenShift target capacity (after N+1).",
    "Windows için kullanım/kapasite metriği henüz rapora bağlı değil; yalnız envanter sayılır.": "Usage/capacity metrics for Windows are not yet wired into the report; only inventory is counted.",
    "Windows sunucuları için günlük kullanım serisi toplanmıyor; tahmin üretilemez.": "No daily usage series is collected for Windows servers; a forecast cannot be produced.",
    "Exadata kullanım serisi (CPU/Memory/depolama doluluğu) toplanmıyor; yalnız envanter var. Tahmin anlamsız olur.": "No Exadata usage series (CPU/Memory/storage utilization) is collected; only inventory exists. A forecast would be meaningless.",
    "Exadata yama/firmware durumu (patchmgr/imageinfo) toplanmıyor; Exadata ekibinin Oracle takvimiyle yönetilir.": "Exadata patch/firmware status (patchmgr/imageinfo) is not collected; it is managed by the Exadata team on the Oracle schedule.",
    "Geri kazanım sanal katmanda ölçülür (kapalı/atıl VM); Linux sunucuları ayrıca değerlendirilmez.": "Reclaim is measured at the virtual layer (powered-off/idle VMs); Linux servers are not assessed separately.",
    "Geri kazanım sanal katmanda ölçülür (kapalı/atıl VM); Windows sunucuları ayrıca değerlendirilmez.": "Reclaim is measured at the virtual layer (powered-off/idle VMs); Windows servers are not assessed separately.",
    "Exadata ayrılmış donanımdır; geri kazanım (kapalı/atıl VM) kavramı geçerli değil.": "Exadata is dedicated hardware; the reclaim concept (powered-off/idle VMs) does not apply.",
    "MTV yalnız VMware → OpenShift Virtualization taşır; fiziksel/ayrı Linux sunucular kapsam dışı.": "MTV only migrates VMware → OpenShift Virtualization; physical/standalone Linux servers are out of scope.",
    "MTV yalnız VMware → OpenShift Virtualization taşır; Windows sunucuları ayrıca planlanmaz.": "MTV only migrates VMware → OpenShift Virtualization; Windows servers are not planned separately.",
    "Exadata taşınmaz; MTV kapsamı dışındadır.": "Exadata is not migrated; it is outside MTV scope.",
    "OpenShift node ayrıntısı OpenShift modülünün Hazır Raporlar sayfasındadır.": "OpenShift node details are on the OpenShift module's Ready Reports page.",
    "Datastore {} %{} dolu — genişletme veya taşıma planlayın.": "Datastore {} is {}% full — plan expansion or migration.",
    "Linux: {} sunucu ≥%85 kullanımda — kapasite veya iş yükü dengelemesi değerlendirin.": "Linux: {} servers at ≥85% usage — consider capacity or workload rebalancing.",
    "Kapalı VM'ler toplam {} GB Memory tahsisi tutuyor — gerekmeyenleri silin/arşivleyin.": "Powered-off VMs hold {} GB of Memory allocation in total — delete/archive those not needed.",
    "Atıl VM'ler ~{} GB Memory serbest bırakabilir (doğrulayarak).": "Idle VMs could free ~{} GB of Memory (after verification).",
    "Envanter yok — izleme yok; skor üretilmedi.": "No inventory — no monitoring; no score produced.",
    "Son 24 saatte açık kritik/uyarı olayı olan varlık yok.": "No assets with open critical/warning events in the last 24 hours.",
    "Son 24 saatte açık kritik/uyarı olay yok.": "No open critical/warning events in the last 24 hours.",
    "Taranmamış sunucu 'güncel' sayılmaz; ölçülemedi olarak işaretlenir.": "A server that has not been scanned is not counted as 'up to date'; it is marked as not measured.",
    "{} / {}: kullanım yüksek (Memory %{}, CPU %{}) — kapasite artırımı veya VM dengelemesi planlayın.": "{} / {}: high usage (Memory {}%, CPU {}%) — plan a capacity increase or VM rebalancing.",
    "Sunucu kullanımı (metriği olan {}/{} sunucu; en yüksek 10)": "Server usage ({}/{} servers with metrics; top 10)",
    "Eşiğe kalan süre — Memory (eşik %{})": "Time to threshold — Memory (threshold {}%)",
    "12 ay içinde eşiğe (%{}) varan sunucular": "Servers reaching the threshold ({}%) within 12 months",
    "{} VM'de araç sürümü güncel değil — planlı pencerede güncelleyin.": "{} VMs have outdated tools — update in a planned window.",
    "Windows: {} kritik güncelleme bekliyor — bakım penceresi planlayın.": "Windows: {} critical updates pending — plan a maintenance window.",
    "{}: {} ({} kritik varlık, {} kritik olay) — en riskli varlıklar tabloda.": "{}: {} ({} critical assets, {} critical events) — the riskiest assets are in the table.",
    "Bu alanda envanter yok / izleme yok; risk ölçülemedi.": "No inventory / no monitoring in this area; risk was not measured.",
    "Bu alanda sunucu/VM yok.": "No servers/VMs in this area.",
    "Bu alanda sunucu yok.": "No servers in this area.",
    "Kayıtlı (gerçek) OpenShift cluster yok.": "No registered (real) OpenShift cluster.",
    "Node durum örneği yok; Ready oranı ölçülemedi.": "No node status samples; the Ready ratio was not measured.",
    "Exadata düğümü yok.": "No Exadata nodes.",
    "Sanallaştırma kümesi / host metriği yok.": "No virtualization cluster / host metrics.",
    "Linux sunucu yok.": "No Linux servers.",
    "{} sunucudan hiçbirinde son 1 saatte CPU/Memory/Disk metriği yok; kullanım ölçülemedi.": "None of the {} servers has CPU/Memory/Disk metrics in the last hour; usage was not measured.",
    "Host metrik geçmişi yok.": "No host metric history.",
    "En az {} günlük günlük-özet serisi gerekir; en uzun seri {} gün. Tahmin üretilmedi.": "A daily-summary series of at least {} days is required; the longest series is {} days. No forecast produced.",
    "Açık VM'lerde araç sürüm durumu toplanmamış (VMware Tools bilgisi yok).": "Tool version status has not been collected for powered-on VMs (no VMware Tools information).",
    "{} sunucudan hiçbirinde güncelleme kontrolü yapılmamış; bekleyen paket sayısı ölçülemedi (Sistem Güncelle › kontrol başlatın).": "No update check has been run on any of the {} servers; the number of pending packages was not measured (start a check under System Update).",
    "Windows sunucu yok.": "No Windows servers.",
    "{} sunucudan hiçbirinde güncelleme taraması yok; ölçülemedi.": "None of the {} servers has an update scan; not measured.",
    "Sanallaştırma kümesi yok.": "No virtualization cluster.",
    "Kayıtlı sanallaştırma kaynağı yok.": "No registered virtualization source.",
    "Exadata düğümleri sunucu kaydına bağlı değil; olay tabanlı SLA tahmini yapılamadı.": "Exadata nodes are not linked to server records; an event-based SLA estimate could not be made.",
    "SystemEvent kayıtları (oluşturulma ≤30 gün), alan filtresi `platform_scope`. Onaylanan % = onaylanan olay / toplam.": "SystemEvent records (created ≤30 days ago), area filter `platform_scope`. Acknowledged % = acknowledged events / total.",
    "Varlık başına tahmini erişilebilirlik = 100 − 0,5×kritik olay (30 gün); ≥%99 SLA'yı sağlar. OpenShift: Ready örnek oranı.": "Estimated availability per asset = 100 − 0.5×critical events (30 days); ≥99% meets the SLA. OpenShift: Ready sample ratio.",
    "Linux/Windows: exporter çalışıyor oranı. Sanallaştırma: son 1 saatte host metriği gelen kaynaklar. OpenShift: son 30 dk node metriği. Exadata: sunucu kaydına bağlı düğüm.": "Linux/Windows: ratio of running exporters. Virtualization: sources with host metrics in the last hour. OpenShift: node metrics in the last 30 min. Exadata: nodes linked to a server record.",
    "Yalnız orta/yüksek güvenli trend listelenir; liste boşsa 12 ay içinde eşiğe varan güvenilir trend yok demektir.": "Only medium/high-confidence trends are listed; an empty list means no reliable trend reaches the threshold within 12 months.",
    "Kontrol sonuçlarının son taraması; olaylardan ayrıdır.": "Last scan of check results; separate from events.",
    "Son güncelleme kontrolü sonucu; canlı SSH sorgusu yapılmaz. Kontrol edilmeyen sunucular 'temiz' sayılmaz.": "Result of the last update check; no live SSH query is made. Servers that were not checked are not counted as 'clean'.",
    "Yalnız KURULU kapasite. Kullanım/doluluk ölçülmediği için kullanım yüzdesi ve tahmin üretilmez.": "Installed capacity only. Usage/utilization is not measured, so no usage percentage or forecast is produced.",
    "Metrik toplamayan sunucular tabloya girmez (sayı uydurulmaz).": "Servers that do not collect metrics are not in the table (no numbers are invented).",
    "Aday listesidir; silme/küçültme kararı sahibiyle doğrulanır.": "This is a candidate list; deletion/downsizing decisions are confirmed with the owner.",
    "Kapsam % = veri akan / varlık. Ölçüt alanlar arasında aynı değildir (sütunda yazılı).": "Coverage % = reporting / assets. The basis differs between areas (stated in the column).",
    "Bu alan için veri okunurken hata oluştu; ölçülemedi.": "An error occurred while reading data for this area; not measured.",
}

# ── Markdown iskelet çevirileri (generic_report) ───────────────────────────────
MD: Dict[str, Dict[str, str]] = {
    "tr": {
        "created": "Oluşturulma", "excluded": "Kapsam dışı", "recs": "Öneriler", "unmeasured": "Ölçülemedi",
        "method": "Hesaplama yöntemi", "no_data": "veri yok", "no_rows": "Kayıt yok.", "yes": "Evet", "no": "Hayır",
        "shown": "İlk {n} satır gösterildi; toplam {t} satır.",
    },
    "en": {
        "created": "Created", "excluded": "Out of scope", "recs": "Recommendations", "unmeasured": "Not measured",
        "method": "Calculation method", "no_data": "no data", "no_rows": "No records.", "yes": "Yes", "no": "No",
        "shown": "Showing the first {n} rows; {t} rows in total.",
    },
}


def md_label(lang: str, key: str) -> str:
    return MD.get("en" if lang == "en" else "tr", MD["tr"])[key]


# ── Şablon derleme ────────────────────────────────────────────────────────────
_TEMPLATES: List[Tuple["re.Pattern[str]", str]] = []


def _build_templates() -> None:
    for tr, en in EN.items():
        if "{}" not in tr:
            continue
        parts = tr.split("{}")
        rx = "^" + "(.+?)".join(re.escape(p) for p in parts) + "$"
        _TEMPLATES.append((re.compile(rx, re.S), en))
    _TEMPLATES.sort(key=lambda t: -len(t[0].pattern))   # en uzun/özgül şablon önce


_build_templates()


# Şablon içine yakalanan değer bu durum sözcüklerinden biriyse çevrilir (ad/sayı asla)
_STATUS_WORDS = frozenset({"Kritik", "Dikkat", "Normal", "Uyarı", "İzleme yok", "Ölçülemedi", "Sağlıklı", "Sanallaştırma"})

_TITLE_PREFIX = (("[YÖNETİCİ] ", "[EXECUTIVE] "), ("[OPENSHIFT] ", "[OPENSHIFT] "))


def tr_str(s: str) -> Optional[str]:
    """Türkçe sabit metnin İngilizcesi; karşılık yoksa None."""
    if s in EN:
        return EN[s]
    for pre_tr, pre_en in _TITLE_PREFIX:           # kayıt başlığı: «[YÖNETİCİ] Başlık» (başlık da çevrilir)
        if s.startswith(pre_tr):
            return pre_en + EN.get(s[len(pre_tr):], s[len(pre_tr):])
    for rx, en in _TEMPLATES:
        m = rx.match(s)
        if m:
            out = en
            for g in m.groups():
                out = out.replace("{}", EN[g] if g in _STATUS_WORDS else g, 1)
            return out
    return None


def t(s: Any, lang: str) -> Any:
    """`lang == "en"` ise çevir; karşılık yoksa (kullanıcı verisi/ad) olduğu gibi döner."""
    if lang != "en" or not isinstance(s, str) or not s:
        return s
    got = tr_str(s)
    return got if got is not None else s


def _kpi(k: Dict[str, Any], lang: str) -> Dict[str, Any]:
    out = dict(k)
    out["label"] = t(k.get("label"), lang)
    if isinstance(k.get("sub"), str):
        out["sub"] = t(k["sub"], lang)
    if isinstance(k.get("value"), str):
        out["value"] = t(k["value"], lang)
    return out


def _section(s: Dict[str, Any], lang: str) -> Dict[str, Any]:
    out = dict(s)
    out["title"] = t(s.get("title"), lang)
    out["kpis"] = [_kpi(k, lang) for k in s.get("kpis") or []]
    out["columns"] = [t(c, lang) for c in s.get("columns") or []]
    out["rows"] = [[t(c, lang) if isinstance(c, str) else c for c in r] for r in s.get("rows") or []]
    if s.get("note"):
        out["note"] = t(s["note"], lang)
    return out


def translate_report(data: Dict[str, Any], lang: str) -> Dict[str, Any]:
    """Rapor verisinin çevrilmiş KOPYASI (`lang != "en"` → aynen). `module`, anahtarlar ve kimlikler değişmez."""
    if lang != "en" or not isinstance(data, dict):
        return data
    d = copy.copy(data)
    d["title"] = t(data.get("title"), lang)
    d["kpis"] = [_kpi(k, lang) for k in data.get("kpis") or []]
    d["sections"] = [_section(s, lang) for s in data.get("sections") or []]
    d["recommendations"] = [t(r, lang) for r in data.get("recommendations") or []]
    d["notes"] = [t(n, lang) for n in data.get("notes") or []]
    d["excluded"] = [{**e, "reason": t(e.get("reason"), lang)} for e in data.get("excluded") or []]
    if data.get("methodology"):
        d["methodology"] = t(data["methodology"], lang)
    app = data.get("applicability")
    if isinstance(app, dict):
        d["applicability"] = {
            k: ({**v, "reason": t(v.get("reason"), lang)} if isinstance(v, dict) else v) for k, v in app.items()
        }
    return d


def lang_of(message: Optional[str], default: str = "tr") -> str:
    """Sohbet mesajından dil: Türkçe karakter → tr; İngilizce rapor fiili/kelimesi → en; aksi halde `default`."""
    m = (message or "").strip()
    if not m:
        return default
    if re.search(r"[çğıöşüÇĞİÖŞÜ]", m):
        return "tr"
    if re.match(r"(?i)^(show|create|generate|give|get|list|display|run|produce|build|make)\b", m) or \
            re.search(r"(?i)\b(report|summary|capacity|forecast|readiness|compliance|environments?)\b", m):
        return "en"
    return default
