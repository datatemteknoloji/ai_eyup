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

OpenShift Virtualization (KubeVirt) her iki tarafa da düşer: OCP `/openshift/vms` + virt envanter.

---

## OpenShift menüleri

| Menü | Yol | Ne yapılır |
|------|-----|------------|
| Komuta merkezi | `/openshift/ops` | Kritik iş yükü / cluster (kırmızı rozet) |
| Envanter | `/openshift` | Cluster, node, proje, workload |
| Virtual Machines | `/openshift/vms` | KubeVirt / OCP VM |
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
  /openshift/ops ── /openshift ── /openshift/vms
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

Tip `openshift_virt`: kube API + token veya OAuth. VM’ler virt senkronu + `/openshift/vms`. Proje/pod soruları OCP asistanında; datastore/host kapasitesi virt rapor/sohbette olabilir.

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

PromQL yazmaz; scrape değişmez.

---

## Limitler

OCP sohbeti Linux SSH yerine geçmez. OLVM engine erişilemezse virt sayfaları boş kalır. ainew, OpenShift’e **kendini** operator olarak kurmaz; OCP’yi **yönetir**.
