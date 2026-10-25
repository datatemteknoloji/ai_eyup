# Yönetici Raporları — Faz 1

Fizibilite analizi onaylandı. Bu dosya çalışma boyunca spesifikasyondur.

Yeni rapor ürünü kurulmayacak. Mevcut `report_engine.generate_report`, `platform_report_engine.generate_platform_report` ve `build_capacity` ortak bir "rapor gerçekleri" şemasıyla çağrılacak ve `infrastructure_reports` tablosuna yazılacak.

## Değişmez kurallar

1. Sayılar, tahminler, skorlar, sıralamalar yalnız backend'de. LLM sayı üretmez.
2. AI metni yalnız rapor gerçekleri JSON'unu okur ve **sayı kapısından** geçmeden yayımlanmaz.
3. Rapor üretimi vCenter/OLVM/OpenShift API'lerine gitmez; yalnız son senkron tablolarını okur (test).
4. Veri yetersizse bölüm `unmeasured`, entegrasyon yoksa `not_applicable`; uydurma yok.
5. Kapasite H.0 kurallarına göre cluster bazında; havuzlama yok, küme dışına taşıma önerisi yok.
6. Dilim T: her bölüm method registry anahtarı taşır, yöntem rozeti + (i); AI metni `AiBlock` içinde.
7. Para birimi yalnız müşteri maliyet parametresi tanımlıysa; varsayılan TL değerleriyle yönetici raporunda para gösterilmez.
8. Tek ajan, multitask yok. Her adımda commit, testler yeşil olmadan ilerleme.

## Adım 0 — Veri hijyeni ve saklama (önce bunlar)

### 0.1 Sentetik / demo veri ayrımı

- `ZZ-FAKE` VM'leri, `veeam_demo`, `hw_demo` ve diğer test/demo kayıtlarını tespit et; tümünü raporla (tablo, kayıt sayısı, nasıl tanındığı).
- Tek bir ayırt etme mekanizması öner ve uygula (ör. `is_synthetic` bayrağı veya mevcut demo kapısının genelleştirilmesi). Mevcut kayıtları **silme**; yalnız işaretle.
- **Faz 1'de dışlama yalnız yönetici raporu gerçekleri JSON'unda** (sayaçlar, skor, trend, riskler). Dashboard, sohbet ve `/infra-reports` varsayılanları değişmez. Bilinçli farklar listesine "yönetici raporu sentetik veriyi saymaz" yazılır. Demo bayrağı açıkken bile sentetik veri yönetici raporuna girmez (test).

### 0.2 "Veri yokken skor 100" düzeltmesi

- **"Olay yok" ile "veri yok" ayrılır.** İzlenen ve olayı olmayan filo A kalabilir. `not_measurable` yalnız popülasyon boşsa veya izleme hiç yoksa; bu durumda ortalamaya ve nota girmez (test).
- Bu düzeltme Yönetici Ekranı'ndaki notu da değiştirebilir; bilinçli düzeltme olarak listelenir. Eski ve yeni skor dağılımı final rapora koyulur.

### 0.3 Saklama süresi (karar için rapor, değişiklik yok)

- `hypervisor_host_metrics`, `virt_datastore_metrics`, `metric_data`, `system_events`, `incidents`, `infrastructure_reports` ve tahmin kayıtlarının saklama/retention ayarlarını (Timescale policy, cleanup job, config) listele.
- Her tablo için iki şeyi **ayrı** yaz: (a) eldeki en eski kaydın tarihi (seri ne zaman başladı), (b) silme politikası (varsa kaç günde siliyor). "Seri 31 gün" ile "politika 31 günde siliyor" farklı şeylerdir.
- Mevsimsellik için en az 13 ay gerekir. Mevcut ayarlar buna izin vermiyorsa: gerekli değişikliği, tahmini disk büyümesini ve (varsa) sıkıştırma/downsampling seçeneğini raporla. **Ayarı değiştirme; onay bekle.**

### 0.4 Eksik veri toplamayı başlat (raporları bekletmez)

Bu adım beş raporu bloklamaz; B1 bu fazda OCP ve Linux diskini zaten `unmeasured` gösterir. Amaç Faz 2 için geçmiş biriktirmeye şimdi başlamak.

- **Linux dosya sistemi:** Prometheus'ta dosya sistemi metriği zaten varsa mevcut toplama yoluyla kaydet (yeni dış çağrı sayılmaz). Yoksa dur ve sor.
- **OpenShift node kullanımı:** `openshift_nodes` üzerindeki anlık değeri mevcut senkron ritminde **günlük kovaya** (günlük ortalama/maks) yaz; yeni API çağrısı yok.
- Tahmin kodu günlük örnek bekler. Ham senkron tick'leri "örnek" sayılmaz; 14 saatlik veri 14 günlük güven gibi görünmemeli (test).

## Adım 1 — Rapor altyapısı

### 1.1 Rapor gerçekleri şeması (C1)

```
report_facts = {
  report_id, report_type, period: {start, end}, generated_at,
  scope: {platforms, instances, clusters},
  data_readiness: [{section_id, status, reason, days_available, days_required}],
  sections: [{
    id, title, method_id,
    status: ok | unmeasured | not_applicable,
    numbers: {key: {value, unit, display: ["72", "%72", "72,4"]}},
    labels: {key: "..."},
    rows: [...], ranges: {...}, confidence, notes
  }]
}
```

- Mevcut rapor JSON'ları bu şemaya bir adaptörle dönüştürülür; mevcut rapor ekranları bozulmaz.

### 1.2 Sayı kapısı (C2)

- Saf fonksiyon: AI metnindeki tüm sayıları (tam sayı, ondalık, yüzde, tarih, süre, birimli değerler; Türkçe ondalık virgül dahil) ayıklar.
- **Eşitlikle çalışır, toleransla değil.** Backend her sayı için izin verilen gösterim biçimlerini `display` dizisinde verir (ör. `72`, `%72`, `72,4`). Metindeki her sayı bu kümelerden birinde birebir yoksa metin reddedilir. Model kendi yuvarlamasın diye kapı gevşetilmez; AI'a "yalnız `display` değerlerini kullan" denir.
- **`labels`** alanındaki adlar (risk adı, cluster, host, ör. `esx03`, `Edirne, bay 9`) sayı ayıklamasına girmez.
- **Sayı içermeyen metin:** A1 yönetici özetinde reddedilir (sayısız özet kaçış yolu olmasın). Diğer bölümlerde sayısız yorum geçebilir.
- Reddedilirse: bir kez yeniden üretim; yine reddedilirse AI metni gösterilmez, yerine kural tabanlı özet (şablon cümleler) gösterilir. Ret olayı loglanır.
- Testler: doğru metin geçer; uydurma sayı, yanlış yuvarlama, `display` dışı biçim, JSON'da olmayan tarih reddedilir; label içindeki rakam reddettirmez; A1'de sayısız metin reddedilir.

### 1.3 Aylık anlık görüntü (C3, ince)

- Yalnız **aylık** zamanlanmış üretim, mevcut arka plan iş altyapısıyla (haftalık bu fazda yok). Her üretim `infrastructure_reports`'a kilitli kayıt; `summary` kolonu AI metnini (kapıdan geçmişse) tutar.
- Ay-ay karşılaştırma yalnız iki kilitli aylık anlık görüntü arasında yapılır. İlk ayda karşılaştırma `unmeasured`; canlı olaylardan "geçen ay" doldurulmaz.

### 1.4 AI yolu

- `llm_gateway.generate_sync` üzerinden; gönderilen tek şey `report_facts`. VM listesi ve ham tablo gönderilmez; yalnız sayılar, agregatlar ve ilk 5 riskin adları (`labels`).
- Uzak LLM kullanılıyorsa gönderilen alanlar (i) içinde belirtilir.

## Adım 2 — İlk 5 rapor

| # | Rapor | Kapsam | Notlar |
|---|---|---|---|
| A1 | Aylık yönetici özeti | Bulgu ve olay sayıları, şiddet dağılımı, ay-ay fark (yalnız kilitli anlık görüntülerden), en büyük 5 risk (kural tabanlı sıralama) | AI: 5–6 cümle özet + "neden önemli". OpenShift kartı boşsa `unmeasured`, gizlenmez |
| B1 | Kapasite tükenme | Yalnız sanal cluster (memory/CPU) ve datastore; Theil–Sen + %25–%75 aralık. 14 günlük örnek altı **veya** güven `low`/`none` ise `unmeasured` (mevcut kural) | OCP node ve Linux dosya sistemi bu fazda `unmeasured` + neden |
| B2 | Yatırım ihtiyacı | `generate_capacity_plan_report` → cluster bazında `hosts_needed`, N+1 | RAM/disk alımı ayrı formül değil; host profili yoksa yalnız host adedi |
| A2 | Atıl kaynak | **Mevcut konsolidasyon raporuyla sınırlı:** kapalı VM ve boşa tahsis (vCPU/RAM/disk). Yetim disk yalnız hazır sorgu varsa ek satır, yoksa `unmeasured`. Idle, oversized, snapshot Faz 2 | "Tahsis, tüketim değil" notu; maliyet parametresi yoksa para yok |
| A6 | Olay ve operasyon özeti | Olay adedi (`system_events`), çözüm süresi **p50 / p95** (`incidents.created_at` → `resolved_at`; ortalama rapora yazılmaz), en sık 3 bileşen | Aynı saniyede kapanan yığın (toplu/otomatik kapatma) p95'e girmez; adedi ayrıca gösterilir ve bölümde not düşülür |

Her bölüm `data_readiness` doldurur.

## Adım 3 — Yönetici ekranı (C5) + dışa aktarım (C6)

- Yönetici Raporları sayfası: dönem seçici, 5 rapor kartı, her kartta rozet + (i), AI özeti `AiBlock` içinde.
- **Veri hazırlığı paneli:** Üretilemeyen veya kısmi raporlar ve nedeni; ör. "Yaşam döngüsü takvimi — referans paketi yüklenmedi", "Mevsimsel yük — 72/395 gün veri", "Yedek uyumu — Veeam bağlı değil", "Lisans ihtiyacı — lisans parametresi tanımlı değil".
- Detay için mevcut `/infra-reports` görünümlerine bağlantı.
- PDF (yöntem notları dahil) ve CSV.

## Faz 2'ye kalanlar (bu turda kod yok, yalnız not)

- Sentetik veri dışlamasının dashboard, sohbet ve `/infra-reports`'a genişletilmesi (ayrı karar; VM sayıları değişir).
- A2 genişletme: idle, oversized, snapshot, yetim disk.
- A3 yaşam döngüsü takvimi (referans paketi gerekir), A4 güvenlik (paket + gerçek BMC), A5/B6 yedek (gerçek Veeam), B3 büyüme (iş servisi haritası), B4 lisans (yeni parametre tablosu), B5 mevsimsellik (≥13 ay veri + statsmodels offline), B7 donanım (gerçek OME/OneView), B8 Linux (kök disk serisi), B9 platform geçişi, C4 tahmin isabet tablosu, A7 SLA (gerçek uptime kaynağı olmadan yapılmaz).

## Kabul kriterleri

- [ ] Sentetik/demo veri yönetici raporu gerçeklerine (sayaç, skor, trend, risk) girmiyor; diğer ekranlar değişmedi (test).
- [x] "Olay yok" ve "veri yok" ayrı; `not_measurable` yalnız popülasyon boşsa veya izleme yoksa; eski/yeni skor dağılımı raporlandı.
- [ ] OCP günlük kova yazılıyor; ham tick'ler örnek sayılmıyor (test).
- [x] Saklama ayarları raporlandı; değişiklik yapılmadı.
- [ ] Sayı kapısı testleri geçiyor; kapıdan geçmeyen AI metni yayımlanmıyor.
- [ ] Ay-ay fark yalnız kilitli aylık anlık görüntülerden; ilk ayda `unmeasured`.
- [ ] 5 rapor üretiliyor; her bölüm `status` ve `data_readiness` taşıyor.
- [ ] Rapor üretimi platform API'lerine çağrı yapmıyor (test).
- [ ] Mevcut `/infra-reports`, dashboard ve sohbet çıktısı değişmedi; bilinçli farklar listeli (sağlık skoru düzeltmesi, Yönetici Ekranı notu).

## Final rapor

Yapılanlar, commit'ler, migration'lar, test sonuçları, sentetik veri envanteri, saklama ayarları ve öneri, eski/yeni skor dağılımı, A6 çözüm süresi veri kalitesi notu, "Doğrulanmadı" listesi, "Verdiğim kararlar" listesi, görsel kontrol edilecek ekranlar.

**Dur ve sor:** veri silen/geri alınamaz migration; saklama ayarı değişikliği; yeni dış çağrı veya yeni bağımlılık; Automic veya kapsam dışı dosyalar.

## Bilinçli farklar

- Yönetici raporu sentetik veriyi saymaz. Dashboard, sohbet ve `/infra-reports` sayaçları bu fazda değişmez.
- Sağlık skoru: popülasyon boş veya izleme yoksa `not_measurable`; Yönetici Ekranı notu buna göre değişebilir.

## Adım 0.3 — saklama (25 Ekim 2026, ayar değişmedi)

Seri başlangıcı = eldeki en eski satır. Politika = silme kuralı. İkisi ayrıdır.

| Tablo | En eski satır | Seri | Silme politikası | Boyut |
|---|---|---|---|---|
| hypervisor_host_metrics | 2026-08-15 | 71 gün | Timescale 90 gün (hypertable 3) + 7 gün sonra sıkıştırma | 23 MB |
| virt_datastore_metrics | 2026-09-05 | 50 gün | Timescale 180 gün (35) + 7 gün sonra sıkıştırma | 3 MB |
| metric_data | 2026-09-24 | 31 gün | Timescale 30 gün (1) + 3 gün sonra sıkıştırma | 27 MB |
| system_events | 2026-08-14 | 72 gün | Uygulama işi `event_retention_days` varsayılan 180 (Timescale değil) | 1,4 GB |
| incidents | 2026-08-14 | 72 gün | RAG retention varsayılan kapalı (`rag_incidents_retention_enabled=false`, 60 gün) | 1,6 MB |
| infrastructure_reports (tahmin satırları da burada) | 2026-09-02 | 42 gün | Silme politikası yok | 408 KB |
| ocp_resource_metrics (ham tick, 0.4 notu) | 2026-09-24 | 32 gün | Timescale 30 gün (43) + 3 gün sonra sıkıştırma | 354 MB |

Mevsimsellik için 395 gün gerekir. Mevcut politikalar buna izin vermez. Öneri (uygulanmadı):

- `metric_data` 30 → 395 gün: ~27 MB / 31 gün × 395 ≈ 340 MB. Sıkıştırma zaten 3 günden sonra açık.
- `hypervisor_host_metrics` 90 → 395 gün: ~23 MB / 71 gün × 395 ≈ 130 MB.
- `virt_datastore_metrics` 180 → 395 gün: ~25 MB.
- `system_events` 180 → 395 gün: bugünkü 1,4 GB / 72 gün × 395 ≈ 8 GB. Asıl büyüme burada.
- `ocp_resource_metrics` ham tick'i 13 ay tutmak ~4 GB. Günlük kova tercih; ham seri 30 günde kalsın.
- `incidents` ve `infrastructure_reports` için ek politika gerekmez.

## Adım 0.2 — skor dağılımı (canlı, 24 saat penceresi)

| Platform | Eski | Yeni |
|---|---|---|
| Linux (1077 sunucu, exporter 0, 3000 olay) | 100 / A | 100 / A (olay var, izleniyor) |
| Windows (486 sunucu, exporter 0, olay 0) | 100 / A | ölçülemedi (izleme yok) |
| Sanallaştırma (5 hypervisor) | 72 / C | 72 / C |
| OpenShift (2 cluster, 242 olay) | 0 / F | 0 / F |
| Genel (ağırlıklı) | 100 / A | 100 / A (Linux ağırlığı baskın) |

## Adım 0.4 — Linux dosya sistemi (25 Ekim 2026)

Canlı Prometheus yapılandırmasında `metric_relabel_configs` veya `drop` kuralı yok. `node-exporter` işi file_sd ile duruyor; hedef dosyası `[]`. `node_exporter_installed` sunucu sayısı 0. `node_*` metrik adı 0.

Eksik olma nedeni collector bayrağı değil: scrape edilen node_exporter yok. Test ortamında metrik açmak exporter kurulumu ister; bu yeni dış çağrıdır, yapılmadı. Müşteri ortamında ainew Prometheus yapılandırmasını değiştirmez.

B1/B8 ölçülemedi der ve şu listeyi gösterir: `node_filesystem_size_bytes`, `node_filesystem_avail_bytes`, `node_filesystem_files`, `node_filesystem_files_free`. tmpfs, overlay, squashfs sayılmaz.

## OpenShift notu, sentetik hariç (25 Ekim 2026, 24 saat)

ZZ-FAKE-OCP olay üretmiyor (collector atlıyor). Eyleme dönük 91 olayın tamamı gerçek oVirt kümesinde: 12 kritik, 79 uyarı. Ceza her iki popülasyonda da 100'e tıkanıyor.

| Kapsam | Küme | Skor |
|---|---|---|
| Sentetik dahil | 2 | 0 / F |
| ZZ-FAKE-OCP hariç | 1 (oVirt) | 0 / F |

Genel not artık sunucu ağırlıklı ortalama değil; ölçülen platformların en kötüsü. Windows ölçülemediği için nota girmez.

## Günlük özet diski (400 gün, bugünkü kardinalite)

Ham politikalar aynı. Ölçülen günlük özet: metric 872 KB / 32 gün, host 352 KB / 72 gün, datastore 176 KB / 51 gün, ocp node 384 KB / 31 gün, olay sayımı 144 KB / 74 gün. 400 güne uzatma yaklaşık 20 MB. Ham OpenShift tick serisi 30 günde kaldı.

## Yayın kapısı (25 Ekim 2026)

«oVirt» adı OpenShift cluster id 2'dir: API `https://192.168.1.241:6443`, sürüm v1.34.6, node `master-0.ocp.datatem.local`. Aynı adres hypervisor 6 üzerinde OpenShift Virtualization'dır. OLVM hypervisor 7'dir. OpenShift notu yalnız `openshift_collector` / `platform=openshift` olaylarındandır. `openshift_virt_event` ve `ovirt_event` sanallaştırmadadır; filtre bunları OpenShift notuna almaz. Sentetik küme dışarıda. Eski formülle de yeni formülle de not 0/F: 24 saatte tekilleştirilmiş 33 kritik ve 102 uyarı, payda 3 node.

| Platform | Eski | Yeni | Payda |
|---|---|---|---|
| Linux | 100 A | 100 A | 1077 sunucu |
| Windows | ölçülemedi | ölçülemedi | izleme yok |
| Sanallaştırma | 70 C | 94 A | 41 host |
| OpenShift | 0 F | 0 F | 3 node |
| Genel | 0 F | 0 F | en kötü platform |

Formül: 24 saatte aynı varlık + aynı olay türü bir kez; ceza = (30×kritik + 12×uyarı) / popülasyon, tavan 100; skor = 100 − ceza. Bilgi cezaya girmez. Kayıt `ops.health_score`, (i) formül alanını basar.

A6: bu dönemde 415 kapanışın tamamı «Otomatik kapatıldı…» / `auto_*`. Manuel veya kural kapanış yok; p50/p95 yazılmadı. p95 üstü kuyruk hesaplanmadı. Kapanış türü ayırt ediliyor.

Rapor kartı: OpenShift 1 küme, 3 node. Sentetik küme sayılmaz. Sayfa açılışı kilitli satırı okur (ölçülen GET 26 ms). «Şimdi yenile» arka plan işidir.

Canlı model `llama3.2:3b`, beş üretim (kapı düzeltmesinden önce). İlk ret / ikinci ret / şablon: A1 3/5, 2, 2; B1 5/5, 2, 2; B2 2/5, 1, 1; A2 4/5, 4, 4; A6 2/5, 0, 0. Ret nedeni display dışı token: dönem ISO'su ve `00`, IP/sürüm parçaları, nokta ondalık `403.4` (kayıt `403,4`), yanlış birim `15 sn`, kardeş bölümün sayısı.

Aynı gün yeniden ölçüm. Sanallaştırma notu canlı olayla 95 A / eski 71 iken 94 A / eski 70 oldu. Sayfa kilitli raporu açıyor. (i) formülü basıyor: «Süre = kapanış − açılış…». CSV ilk satırları `533816`, OpenShift `1` küme ve `3` node. PDF `window.print`; yazdırma penceresi açılmadı.

Kapı düzeltmesinden sonra (`f9a20a20`, dönem tarihi prompt'ta yok) beş üretim daha. İlk ret / ikinci ret / şablon: A1 5/5, 5, 5; B1 3/5, 1, 1; B2 4/5, 4, 4; A2 4/5, 3, 3; A6 3/5, 3, 3. IP, binlik ayırıcı ve dönem kopyası kalmadı. Kalan retler uydurma sayı (`1`–`5` madde sırası, `14`, `100`, `%100`, `95`, `50`), yabancı ondalık `403.4` ve yanlış birim `15 sn`. Şablon yedeği bunları yayımlamaz.
