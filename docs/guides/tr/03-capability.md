## 12. Capability Guide — menüler ve işlemler

Yetkisiz modül gizlenir. Yollar kanoniktir.

### 12.1 Dashboard

`/dashboard` — ortam özeti, kaynak kullanımı (son CPU/RAM/disk `metric_data`).

### 12.2 Yönetici ve AI

| Menü | Yol | İşlem |
|------|-----|--------|
| Yönetici özeti | `/executive` | Çok platformlu özet |
| Tüm altyapı asistanı | `/chat` | Çapraz tool; PDF |
| Ajan | `/agent` | Onaylı çok adımlı araç |

### 12.3 Linux (`linux`) — Linux GUIDE’da ayrıntı

| Menü | Yol | İşlem |
|------|-----|--------|
| Dashboard | `/linux/dashboard` | Filo özeti |
| Linux sunucuları | `/servers` | Envanter, SSH, AI-ready, terminal |
| Canlı metrik | `/metrics` | CPU / bellek / disk |
| Paketler | `/packages` | Paket işlemleri |
| Sistem güncelleme | `/system-update` | Yama |
| Yerel repo | `/repositories` | İç repo |
| Ansible / AWX | `/ansible` | Otomasyon |
| Raporlar | `/linux/reports` | Rapor |
| AIOps | `/linux/chat`, `/ops`, `/events`, `/incidents`, `/analysis` | Asistan ve AIOps |

İlgili: **Ayarlar → Linux SSH**, **Entegrasyonlar → Fiziksel hostlar**, **Level 1** (day-2).

### 12.4 Windows (`windows`)

| Menü | Yol | İşlem |
|------|-----|--------|
| Dashboard | `/windows/dashboard` | Özet |
| Sunucular | `/windows` | WinRM envanter |
| Canlı metrik | `/windows/live-metrics` | Exporter |
| Event Log | `/windows/events` | Olay günlüğü |
| Windows Update | `/windows/updates` | Güncelleme |
| Ansible | `/windows/ansible` | Otomasyon |
| Raporlar | `/windows/reports` | Rapor |
| AIOps | `/windows/aiops/chat` … `/analysis` | Asistan |

İlgili: **Ayarlar → WinRM**.

### 12.5 Sanallaştırma (`virtualization`) — Sanallaştırma GUIDE

| Menü | Yol | İşlem |
|------|-----|--------|
| Dashboard | `/hypervisors` | Host, cluster, VM, datastore |
| Altyapı raporları | `/infra-reports` | Kapasite, trend, forecast |
| Asistan | `/virt/chat` | VM / datastore / Tools |
| AIOps | `/virt/ops`, `/events`, `/incidents`, `/analysis` | Operasyon |

Bağlantı **bu menüde eklenmez**: **Entegrasyonlar → vCenter/OLVM**.

### 12.6 Exadata

`/exadata`, `/exadata/reports`, `/exadata/chat|ops|events|incidents|analysis`. Bağlantı: `/integrations/exadata`.

### 12.7 OpenShift ve oVirt — OpenShift GUIDE

OpenShift menüsü:

| Menü | Yol | İşlem |
|------|-----|--------|
| Komuta merkezi | `/openshift/ops` | Kritik özet |
| Envanter | `/openshift` | Cluster / node / proje |
| Sanal makineler | `/openshift/vms` | KubeVirt / OCP VM |
| Olaylar / incident | `/openshift/events`, `/incidents` | Cluster ops |
| Asistan | `/openshift/chat` | Pod, node, PVC |

oVirt / OLVM: **Entegrasyonlar → vCenter/OLVM** (tip `kvm`) + sonuçlar Sanallaştırma dashboard / `/virt/chat` içinde. OpenShift Virtualization: aynı virt envanteri + `/openshift/vms`.

### 12.8 Level 1

| Menü | Yol | Kim |
|------|-----|-----|
| Operasyon merkezi | `/level1` | level1 |
| Konsol | `/level1/console/:id` | level1 |
| Sihirbazlar | `/level1/ops/…` | level1 |
| İşler | `/level1/jobs` | level1 |
| Denetim / Ayarlar | `/level1/audit`, `/settings` | admin |

Sihirbazlar: terminal, kullanıcı, hostname, reboot, servis, sudoers, filesystem/LVM, paket, path, log, limits, sysctl, ağ/VLAN, ASM, posta.

**Akış:** Talep ID → Preview → Apply. Dropt ayrı DB.

```diagram
  Operasyon merkezi ──► Konsol / sihirbaz
                              │
                         Talep ID
                              │
                           Preview
                              │
                            Apply
                              │
                           İşler ──► Denetim
```

### 12.9 Entegrasyonlar

`/integrations` hub · `/integrations/ucmdb` · `/integrations/hypervisors` (vCenter/OLVM) · `/integrations/physical-hosts` · `/integrations/exadata` · `/integrations/openshift`.

### 12.10 Diğer

Uygulamalar `/applications` · Bilgi bankası `/knowledge-base` · Özel raporlar `/custom-reports` · Denetim `/audit` · Kullanıcılar `/users` · Ayarlar `/settings` (SSH, WinRM, AI, marka, RAG, izleme, güvenlik, gelişmiş, **Hakkında = GUIDE indir**).

### 12.11 Kullanıcı ne sorabilir

Named-host Linux/Windows · virt yerleşim/kapasite · OCP pod/node · PromQL (yazmaz). Level 1 sihirbazdır, virt sohbet değildir.
