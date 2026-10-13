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
| Kapasite | `/virt/capacity` | Sekmeler: Cluster, Datastore, What-if (yeni VM sığar mı?), **Host devre dışı kalırsa (N+1)**, Geri kazanım simülasyonu, Toplu yerleşim, Yerleşim, Eşikler |
| Geri kazanım | `/virt/reclaim` | Kapalı / atıl / oversized VM, snapshot, sahipsiz disk, ISO, kullanılmayan datastore |
| Sağlık kontrolleri | `/virt/health` | Sağlık, uyum (ISO 27001), donanım, CVE/KB, yükseltme bulguları; istisna, komut taslağı, onaylı düzeltme |
| Değişiklikler | `/virt/changes` | Host/cluster yapılandırma geçmişi (diff), baseline, sapma bulguları |
| Yedek & DR | `/virt/backup` | **Yalnız yedek sağlayıcısı (Veeam) bağlıysa görünür.** RPO/koruma, işler, depolar, eşleşmeyenler, RPO hedefleri, kanıt |

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
- **Yerleşim ve HA (kapasite):** What-if, Toplu yerleşim, Host devre dışı (N+1) ve Yerleşim aynı çekirdekle çalışır. vCenter *ayrılmış failover host* politikasında bu host'lar yerleşime kapalıdır (kapasiteleri rezerv sayılır; liste okunamazsa 1 host varsayılır ve etiketlenir). *Slot politikasında* (tolere edilen host arızası) boş slot kalmadıysa Memory yetse bile VM **sığmaz** (limit: HA slot); yeni VM'in rezervasyonu bilinmediğinden 1 slot/VM varsayılır ve slot sayısı son HA okumasındandır.
- **Host devre dışı kalırsa (N+1):** cluster seçilince **her host için ayrı** sonuç otomatik gelir (üzerindeki açık VM'ler kalan host'lara yerleştirilir). Memory *tanımlı* (en kötü durum, karar bunun üzerindendir) ve *p95* olarak, CPU p95 olarak ayrı ayrı gösterilir; satırlar riske göre sıralanır (Sığmaz → Sınırda → Sığar → VM yok). Satıra tıklayınca yerleşen/yerleşemeyen VM'ler açılır; birden çok host'u aynı anda düşürmek için host seçip **Seçilenlerle hesapla**. Bu ekran **simülasyondur, gerçek arıza değildir**: gerçek arızalar Sağlık kontrolleri › Bulgular'dadır. Donanım bulgularının *Etki* bloğundan ilgili host'un N+1 satırına gidilir. Affinity/DRS kuralları, VM rezervasyonları ve HA yeniden başlatma önceliği değerlendirilmez.
- **Runway:** Memory ve datastore için günlük ortalamanın Theil–Sen eğimiyle "eşiğe kalan gün" (varsayılan eşikler Memory %85, CPU %80, datastore %85 — Kapasite › Eşikler sekmesinden değiştirilir). En az 14 günlük veri gerekir; yoksa "veri yetersiz" yazılır, tahmin uydurulmaz.
- **Geri kazanım simülasyonu:** boşta ve aşırı boyutlu (p95 CPU'ya göre) VM'ler önerilen boyuta küçültülürse cluster'ın effective Memory %, vCPU:çekirdek oranı ve N+1 durumu yeniden hesaplanır. Salt okunur: VM'ler küçültülmez; vCPU azaltmak Memory boşaltmaz.
- **Toplu yerleşim:** birden çok VM profilini (vCPU / Memory / disk / adet; isteğe bağlı anti-affinity grubu) cluster başına bağımsız yerleştirir; CSV dışa aktarılır, plan kaydedilmez. Kapsam **opsiyonel** daraltılır (instance → datacenter → cluster; seçimler kaldırılabilir çipler olarak görünür). What-if ekranında host seçici yoktur; host daraltması yalnız Toplu yerleşim'de vardır. Kapasite cluster'lar arasında **toplanmaz**; cluster'sız host'lar bağımsız hesaplanır.
- **What-if varsayımları:** Memory'nin tamamen kullanıldığı, CPU'nun vCPU başına varsayımla hesaplandığı ve — **kontrol edilmeyen** — affinity/DRS kuralları, VM rezervasyonları ve VLAN/portgroup erişimi sonuç ekranında listelenir. OpenShift Virtualization için virt-launcher ek belleği hesaba katılmaz; Red Hat dokümanından gelen yaklaşık değer *doküman varsayımı* etiketiyle yazılır.
- **Yöntem rozetleri:** her sayı/kart yanında sınıf rozeti (Veri, Hesap, Tahmin, Kural, Eşleştirme, AI) ve (i) ile "nasıl üretildi / hangi veriden / sınırı ne" görülür. Tek kaynak: `GET /api/v1/methods`.
- **Yedek & DR (Veeam VBR, isteğe bağlı):** Entegrasyonlar › Yedekleme sağlayıcısı (opsiyonel) (`/integrations/backup`, admin) ile salt okunur Veeam REST bağlantısı kurulur; bağlantı yoksa menü, sekme, bulgu ve sohbet araçları **hiç görünmez** ve Veeam'siz ortam davranışı değişmez. Önerilen VBR rolü *Backup Viewer* (VBR sürümü `serverInfo` yalnız Administrator'a açıktır). Yalnız dokümanda doğrulanan `1.3-rev1` alanları kodlanmıştır; diğer revizyonlar (12.x dahil) seçilebilir ama **alanları doğrulanmadı** uyarısıyla gelir. Değişmezlik/şifreleme/CBT alanları doğrulanamadığı için *ölçülemedi*dir; RTO tahmin edilmez. DEMO/fixture sağlayıcı varsayılan **kapalıdır** (`BACKUP_DEMO_ENABLED`). Harici (uzak) LLM açıkken sohbet araçları VM/iş/depo **adlarını** ve durum/RPO özetini modele iletir; kimlik, endpoint ve ham API yanıtı iletilmez (Yedekleme sağlayıcısı sayfasında uyarı gösterilir).
- **Kapsam notu:** özellik planı 14 maddedir; **13 maddesi (Madde 6 — ServiceNow/Teams hariç)** uygulanmıştır. Madde 6 bu sürümde yoktur.
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
