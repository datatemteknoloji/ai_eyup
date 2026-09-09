## 13. End-to-End Scenarios

### 13.1 vCenter

Entegrasyonlar → vCenter/OLVM → test → senkron → Sanallaştırma dashboard / rapor → `/virt/chat` (VM veya datastore adı).

### 13.2 Linux

Ayarlar → SSH → fiziksel host veya `/servers` → exporter + Prom job → `/metrics` veya `/linux/chat`. Yama: Paketler / Sistem güncelleme. Day-2 disk/LVM: Level 1.

### 13.3 OpenShift

Entegrasyonlar → OpenShift → komuta merkezi → `/openshift/chat`. KubeVirt: `/openshift/vms` ve virt dashboard.

### 13.4 oVirt / OLVM

Entegrasyonlar → vCenter/OLVM, tip oVirt/KVM → senkron → Sanallaştırma menüsü + `/virt/chat`.

### 13.5 Prometheus

Sohbette PromQL. Job adları Ayarlar → İzleme. Scrape listesi değişmez.

### 13.6 Level 1

`/level1` → eşlenmiş sunucu → sihirbaz → Talep → Preview → Apply → `/level1/jobs`.
