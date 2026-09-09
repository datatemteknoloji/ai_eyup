# ainew — Sanallaştırma GUIDE

Yalnızca **Sanallaştırma** sol menü grubu: dashboard, altyapı raporları, virt AIOps (asistan, komuta, olay, incident, analiz).

OpenShift komuta merkezi / OCP envanteri ve oVirt bağlantı adımlarının tam anlatımı **OpenShift / oVirt GUIDE**’ındadır. Linux paket sayfaları burada yoktur.

**RBAC:** `virtualization`. Hypervisor **eklemek** için ayrıca `integrations`.

---

## Menüler (yalnızca bu grup)

| Menü | Yol | Ne yapılır |
|------|-----|------------|
| Dashboard | `/hypervisors` | Cluster, ESXi/host, VM, datastore, güç durumu |
| Altyapı raporları | `/infra-reports` | Kapasite, trend, Theil–Sen forecast, datastore doluluk |
| Asistan | `/virt/chat` | Yerleşim, host CPU, Tools, snapshot, “ne zaman dolar?” |
| Komuta merkezi | `/virt/ops` | Virt AIOps özet |
| Olaylar | `/virt/events` | Virt olayları |
| Incident | `/virt/incidents` | Incident |
| Analiz | `/virt/analysis` | Analiz |

```diagram
  Entegrasyonlar → vCenter/OLVM     (bağlantı burada; bu menü değil)
                    │
                    ▼
              hypervisor sync
                    │
                    ▼
           servers + virt_* 
                    │
         ┌──────────┼──────────┐
         ▼          ▼          ▼
   /hypervisors  /infra-reports  /virt/chat
   (dashboard)   (rapor)         (asistan)
```

Guest SSH gerekmez. Metrik hypervisor API (vCenter QuickStats, oVirt REST, …).

---

## Bu ekranlarda ne görülür

- **Dashboard:** bağlı tüm hypervisor tiplerinin (VMware, oVirt, Proxmox, Hyper-V, KubeVirt) senkron envanteri  
- **Raporlar:** kapasite ve tahmin — sohbetten bağımsız, tekrarlanabilir  
- **Asistan:** kapsam (tek VM adı ≠ filo); önce DB, gerekirse tek varlık canlı API  

Bağlantı yoksa bu sayfalar boştur. Ekleme: **Entegrasyonlar → vCenter/OLVM** (`/integrations/hypervisors`). `hostname` etiket olabilir; **IP/FQDN** kullanın.

---

## Sohbet / model (virt)

```diagram
  Soru (/virt/chat)
        │
        ▼
  Kapsam (VM / host / datastore adı)
        │
        ▼
  Tool → virt tabloları / nadiren canlı API
        │
        ▼
  LLM → SSE yanıt
```

Prometheus scrape yazılmaz.

---

## Limitler

oVirt ayrı menü değildir; VM’ler bu dashboard’da görünür, OLVM ekleme adımları OpenShift/oVirt GUIDE’da. KubeVirt proje/pod’ları OpenShift menüsündedir.
