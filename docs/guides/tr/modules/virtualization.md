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
| Planlama ve Denetim (alt grup) | — | Kapasite, Geri kazanım, Sağlık kontrolleri, Değişiklikler sol menüde bu alt grupta toplanır |
| Kapasite | `/virt/capacity` | Effective kapasite, N+1, runway, what-if (yeni VM sığar mı?), yerleşim önerisi |
| Geri kazanım | `/virt/reclaim` | Kapalı / atıl / oversized VM, snapshot, sahipsiz disk, ISO, kullanılmayan datastore |
| Sağlık kontrolleri | `/virt/health` | Sağlık, uyum (ISO 27001), donanım, CVE/KB, yükseltme bulguları; istisna, komut taslağı, onaylı düzeltme |
| Değişiklikler | `/virt/changes` | Host/cluster yapılandırma geçmişi (diff), baseline, sapma bulguları |

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

## Karar katmanı (VMware · OLVM · OCP Virt)

Ortak, deterministik bir motor bulguları periyodik toplar (fleet job `virt_insights`; admin **Şimdi çalıştır** ile tetikler). Dashboard’da dört kart (Kapasite, Geri kazanım, Sağlık, Değişiklikler) ilgili sayfaya götürür.

- **Erişim:** yalnız vCenter, OLVM Manager ve OpenShift API. ESXi / KVM host’a SSH veya doğrudan bağlantı yoktur; host’tan okunamayan kontroller **ölçülemedi** olarak işaretlenir.
- **Kapasite:** HA rezervi düşülmüş effective Memory/CPU, en büyük host düşerse (N+1) durum, eşiğe kalan gün. What-if: vCPU / Memory / disk / adet girin → hangi cluster’a sığar. Yerleşim: skorlu host adayları, reddedilen host’lar gerekçesiyle.
- **Geri kazanım:** her kalem kazanılacak vCPU / Memory / GB ile; snapshot ve dosya taraması datastore tarayıcısından gelir (VM’e bağlı dosyalar ve OLVM snapshot diskleri sahipsiz sayılmaz).
- **Sağlık / uyum:** NTP, syslog, SSH, lockdown, HA/admission control, vMotion, uplink yedekliliği, multipath, OLVM fencing, OCP Virt eviction stratejisi. Uyum sekmesi ISO 27001 maddelerine göre gruplar; CSV/JSON dışa aktarılır. **Denetim Kanıtı** ve **Kapasite Planı (N+1)** raporları `/infra-reports`’ta.
- **İstisna:** admin bir bulguyu gerekçe + bitiş tarihiyle istisnaya alır; skorlarda ayrı sayılır.
- **Komut taslağı:** PowerCLI / `oc` taslağı + geri alma satırı. ainew taslağı **çalıştırmaz**.
- **Referans paketleri** (Ayarlar sekmesi, admin): offline CVE/VMSA, KB ve yükseltme/HCL matrisi JSON’u yüklenir (örnek şema indirilebilir). KB paketi isteğe bağlı RAG’e eklenir. İnternetten otomatik çekim yoktur.
- **Onaylı düzeltme (yalnız VMware):** izinli işlemler — eski snapshot silme, NTP servisini yeniden başlatma, NTP sunucularını ayarlama, SSH’i durdurma. Önce Ayarlar sekmesinde vCenter başına okuma hesabından **farklı** bir yazma hesabı tanımlanır. Öneri Agent’ta **bekleyen aksiyon** olur; onaylanınca uygulanır ve önceki değer sonuçta saklanır.
- **Sohbet:** “N+1 karşılanıyor mu / kaç host lazım”, “8 vCPU 32 GB VM nereye”, “ne geri kazanırım”, “açık sağlık bulguları”, “incident sırasında ne değişti” soruları motor çıktısına dayanır; model sayı üretmez.
- **Incident:** virt incident ekranında zaman çizelgesi (alarm, olay, yapılandırma değişikliği, bulgu) ve aday nedenler.

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

Prometheus scrape yazılmaz. `/virt/monitoring` ve hub → Sanallaştırma **vCenter ve OLVM/oVirt API → Timescale** (Prometheus ayrı bağlanır). Metrik listbox Timescale kolonlarının tamamını sunar; grafik serisi seçili nesneye kilitlidir.

---

## Limitler

oVirt ayrı menü değildir; VM’ler bu dashboard’da görünür, OLVM ekleme adımları OpenShift/oVirt GUIDE’da. KubeVirt proje/pod’ları OpenShift menüsündedir.
