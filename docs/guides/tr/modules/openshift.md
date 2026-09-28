# ainew — OpenShift ve oVirt GUIDE

OpenShift Container Platform **ve** oVirt / OLVM (ve OpenShift Virtualization / KubeVirt) ile ilgili her şey: bağlantı, menüler, sohbet, veri akışı.

VMware-only kapasite raporunun derinliği Sanallaştırma GUIDE’dadır; OCP/OLVM operatörü için gereken virt kesiti buradadır.

**RBAC:** `openshift` (OCP menüleri), `virtualization` (OLVM sonuçları dashboard/sohbet), `integrations` (bağlantı).

---

## İki platform, bir ürün

```diagram
                    ainew
                      │
         ┌────────────┼────────────┐
         ▼                         ▼
   OpenShift API              oVirt / OLVM
   (kube API + token)         (REST :443, type=kvm)
         │                         │
         ▼                         ▼
  /openshift/*                hypervisor sync
  ops, envanter,              → servers + virt_*
  vms, events,                     │
  chat                        /hypervisors
                              /virt/chat
                              /infra-reports
```

OpenShift Virtualization (KubeVirt) her iki tarafa da düşer: OCP `/openshift/vms` + virt/Linux `servers` envanteri (cluster sync otomatik köprüler). VM adı (`vm_name`) ile OS hostname uyuşmazlığı VMware ile aynı filtredir (guest agent veya SSH OS yenileme).

---

## OpenShift menüleri

| Menü | Yol | Ne yapılır |
|------|-----|------------|
| Komuta merkezi | `/openshift/ops` | Kritik iş yükü / cluster (kırmızı rozet) |
| Envanter | `/openshift` | Cluster, node, proje, workload |
| Virtual Machines | `/openshift/vms` | KubeVirt / OCP VM |
| Monitoring | `/openshift/monitoring` | API: Node/Pod/VM + `metrics.k8s.io` → Timescale. Prometheus: DCGM + kubevirt (Settings binding). Hub `/monitoring` |
| Events | `/openshift/events` | Cluster olayları |
| Incidents | `/openshift/incidents` | Incident |
| Asistan | `/openshift/chat` | Pod, node, proje, PVC, CrashLoop |

**Bağlantı:** Entegrasyonlar → OpenShift envanteri (`/integrations/openshift`). Host `/etc/hosts` ile dahili API adları (compose `extra_hosts` yazılmaz).

```diagram
  Entegrasyonlar → OpenShift
           │
           ▼
     kube API (token / OAuth)
           │
           ▼
  /openshift/ops ── /openshift ── /openshift/vms ── /openshift/monitoring
           │
           ▼
     /openshift/chat  →  tool  →  API / DB  →  LLM
```

---

## oVirt / OLVM

Ayrı sol menü grubu **yoktur**.

1. **Entegrasyonlar → vCenter/OLVM** (`/integrations/hypervisors`)  
2. Tip **oVirt / KVM** (`kvm`), engine FQDN/IP, kullanıcı/şifre, port 443  
3. Bağlantıyı test et → kaydet → VM senkron  
4. Sonuç: **Sanallaştırma → Dashboard** (`/hypervisors`), **Altyapı raporları**, **Asistan** (`/virt/chat`)

```diagram
  OLVM Engine (REST)
        │
        ▼
  type = kvm kayıt
        │
        ▼
  sync-vms / host / storage domain
        │
        ▼
  /hypervisors   /infra-reports   /virt/chat
```

vCenter (`vmware`) aynı entegrasyon sayfasındadır; protokol SOAP’tır. Bu GUIDE’nin oVirt dilimi `kvm` kaydıdır.

---

## OpenShift Virtualization

KubeVirt VM'ler iki yerde görünür:

1. **OpenShift → Virtual Machines** (`/openshift/vms`) — canlı API listesi  
2. **Linux Sunucular / Sanallaştırma envanteri** (`/servers`, hypervisor sync) — `servers` tablosu  

OpenShift cluster sync (`/integrations/openshift` → Sync) otomatik olarak yönetilen bir `openshift_virt` hypervisor kaydı oluşturur/günceller ve KubeVirt VM'leri `servers`'a yazar. Ayrı manuel hypervisor kaydı **gerekmez**. Linux guest'ler **Linux Yönetimi → Linux Sunucular** listesine düşer.

---

## Model / sohbet

```diagram
  /openshift/chat          /virt/chat (OLVM / KubeVirt)
         │                         │
         ▼                         ▼
  Intent: OCP nesnesi        Intent: VM / domain
         │                         │
         └──────────┬──────────────┘
                    ▼
                 LLM + tool
```

PromQL scrape yazılmaz. Monitoring **API modu** `metrics.k8s.io` anlık CPU/bellek kullanır; **Prometheus modu** Ayarlar’daki OpenShift Prometheus kaynağından DCGM / kubevirt okur. Other kaynaklar hub’da label ile; Unified chat’te tam label gerekir.

---

## Limitler

OCP sohbeti Linux SSH yerine geçmez. OLVM engine erişilemezse virt sayfaları boş kalır. ainew, OpenShift’e **kendini** operator olarak kurmaz; OCP’yi **yönetir**.
