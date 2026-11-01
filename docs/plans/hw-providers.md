# Opsiyonel Donanım Yönetimi Sağlayıcı Çerçevesi (Dell OME + HPE OneView/OVGD)

> Çalışma boyunca spesifikasyon için bu dosya esastır. Resmi doküman kaydı: `docs/plans/hw-api-sources.md`. Adım 0 raporu: `docs/plans/hw-step0-report.md`.
> Bu sürüm, ilk prompt'un kullanıcıyla yapılan doğrulama konuşmasından sonra DÜZELTİLMİŞ halidir (kararlar en altta).

## Kapsam

- **Dell:** OpenManage Enterprise (OME) **4.7.0** — tek seviye.
- **HPE:** OneView appliance'ları (**6.60.04 / 10.00 / 11.20 / 11.40**; API 3800 / 7600 / 9000) ve OneView Global Dashboard (**OVGD 3.00.00**, API 300; `x-api-version: 2` ile). OVGD ve OneView **tek kart**; OVGD yalnız toplama katmanıdır (appliance keşfi, birleşik alarm).
- Kapsam DIŞI: donanıma her türlü yazma; remote console / SSO / `mpSessionKey`; bulut portalları (COM, InfoSight, TechDirect, CloudIQ); Lenovo/Cisco; Faz 3 (iLO/iDRAC ham log) ve Faz 4 (genel Redfish) — **bu çalışmada yapılmaz**.

## Değişmez kurallar

1. **Opsiyonellik:** Hiçbir donanım entegrasyonu yoksa uygulama bugünkü gibi davranır; ekran, kart, bulgu, sohbet tool'u, senkron işi görünmez. Davranışı tabloların varlığı değil **capability** belirler.
2. **Capability:** etkin + sağlıklı en az bir sağlayıcı → `hw`; üretici bazında `hw.dell`, `hw.hpe`.
3. **Migration'lar koşulsuz:** `hw_*` tabloları her kurulumda oluşur (boş kalabilir); yalnız ekleme.
4. **Salt-okunur:** tüm hesaplar salt-okunur rolde (OME → VIEW yetkisi/“Viewer”; OneView/OVGD → salt-okunur rol).
5. **Sayılar deterministik motorda;** LLM yalnız anlatır; tahmin yok.
6. **Sohbet READ_ONLY.**
7. **Her şey resmi dokümana göre.** Kaynak kaydında olmayan endpoint çağrılmaz (test). Belirsiz alan `not_measurable` + “Doğrulanmadı”.
8. **Kimlik bilgisi** `encrypt_secret` ile `credential_ref`; API/log'da asla düz metin.
9. **Method registry (Dilim T):** her bulgu/kart/metrik/sohbet tool'u kayıtlı; rozet + (i).
10. **Automic dosyalarına dokunulmaz.**
11. **İstemci kısıtı:** yalnız GET + ürün başına açık allowlist'li oturum açma (POST) / kapatma (DELETE). Yasak uçlar kodda sabit liste + test.
12. **Kimlik doğrulama koruması (hesap kilitlenmesin):**
    - Her entegrasyonda kimlik doğrulama **1 kez** denenir. 401 / oturum reddi → yeniden deneme YOK; durum `auth_failed`; otomatik senkron durur; kullanıcıya Türkçe uyarı.
    - Yalnız başarılı “Bağlantıyı test et” sonrası yeniden başlar; bilgiyi kaydetmek tek başına senkronu başlatmaz.
    - Aynı hesapla çok sayıda appliance (OVGD → OneView): ilk auth hatasında kalanlara **denenmez**.
    - Durum veritabanında (çok worker) + `fleet_lock`; test düğmesinde bekleme süresi.
    - 403 de yeniden denenmez (“yetki yetersiz”). Yalnız ağ/5xx hataları sınırlı üstel bekleme ile.
13. **Sync kodu** `asyncio.to_thread`/arka plan kuralına uyar (async yolda senkron I/O yok).

## Mimari

- Veeam deseni genelleştirilir: `services/integrations/` (ortak tipler + sağlayıcı kaydı); `integration_instances.category = "hardware"`; kind: `dell_ome`, `hpe_oneview` (OneView appliance veya OVGD; kart içinde `mode`), `hw_demo`.
- `HardwareProvider` protokolü: `test_connection`, `capabilities`, `sync`, `health`.
- Normalize şema: `hw_managers`, `hw_servers`, `hw_enclosures`, `hw_components`, `hw_firmware`, `hw_alerts`, `hw_log_entries`, `hw_warranty`, `hw_utilization`, `hw_host_links`.
- Eşleştirme: seri/service tag/UUID (exact; HPE için fiziksel + sanal seri), hostname (low, işaretli), eşleşmeyen listeleri.
- `fleet.hw_sync`: ayrı job; yalnız etkin sağlayıcı varken; alarm 15 dk, envanter günlük, garanti günlük (kartta ayarlanabilir); bayatlık > 2 × aralık.
- RBAC: yeni **`hardware`** modülü (varsayılan yalnız Admin). Kart yapılandırma `integrations` + admin. Donanım verisi (`/api/v1/hw/*`, çekmece kartı, Donanım sayfası, sohbet tool'ları) `hardware` modülüyle. BMC IP / seri `/servers` API'lerine eklenmez.
- DEMO: `HW_DEMO_ENABLED` (production varsayılan kapalı), her ekranda “DEMO VERİ” bandı; demo veriden kanıt/rapor/skor üretilmez.

## Destek seviyeleri

- **Doğrulanmış:** dokümanı + fixture ile doğrulanmış sürümler (OME 4.7.0; OneView 10.00 / 11.x; OVGD v2 sözleşmesi).
- **Uyumlu (en iyi çaba):** aynı API ailesi; kart “doğrulanmadı” uyarısı verir; bulgular düşük güvenli.
- **Desteklenmeyen:** bağlantı reddedilir, nedeni yazılır.
- OneView 6.60.04 (API 3800): “Uyumlu”; üretici desteği resmi yaşam döngüsü sayfasından doğrulanmalı (Doğrulanmadı).
- OVGD 3.00: `x-api-version: 2` → “Uyumlu”; gerçek yanıt fixture'ı ile “Doğrulanmış”.

## Bulgu kataloğu (hepsi `requires_capability: ["hw"]`)

Bu çalışmada uygulanan: `hw.server.health_critical`, `hw.alert.recurring`, `hw.warranty.expired_prod`, `hw.server.unmatched`, `hw.server.unreachable`, `hw.provider.sync_failed`, `hw.provider.stale`.
Ertelenen (kaynak alanı doğrulanmadı → `not_measurable`): `hw.component.predictive_failure`, `hw.component.redundancy_lost`, `hw.memory.correctable_errors_recurring`, `hw.bmc.security_at_risk` (`securityStatus` hiçbir OneView API dokümanında yok).

## Sohbet

READ_ONLY tool'lar (yalnız capability `hw` + `hardware` modülü): `hw_server_status`, `hw_alerts_summary`. (`hw_logs_fetch` yok — Faz 3 kapsam dışı.)

## Firmware görünürlüğü ve referans karşılaştırma (Faz C; 2026-11-01)

**Adım C1 — görünürlük (bu adım; kapanış kriterleri koddan ÖNCE):**
1. Dell OME firmware envanteri (`fetch_firmware` açıkken) `firmware_max_per_run` sınırında **imleçle** döner: sınırdan fazla sunucu olsa da art arda turlarda HEPSİ okunur (imleç `meta.firmware_cursors["ome"]`; hata/yeniden başlatmada baştan başlamak güvenlidir). Sınır nedeniyle yarım kalan tur uyarı değil, ilerleme sayacıdır (`last_counts.firmware_read/firmware_total`).
2. `hw_firmware` her satırda **Status** (`Installed` | `Available`) ve **ComponentId** taşır (OME 4.7.0 `InventoryInfo`: `Status`, `ComponentId`; `DCIM:PREVIOUS#…` örnekleri `Available`). Karşılaştırma ileride YALNIZ `Installed` satırlarla yapılır; `Available` önceki/yedek sürüm olarak ayrı gösterilir.
3. Dell `bios_version`, firmware envanterinden (`SoftwareType=BIOS`, `Status=Installed`) doldurulur; envanter okunmayan turda önceki BIOS değeri SİLİNMEZ.
4. Sunucu ayrıntısında (Donanım sayfası, açılan satır) firmware listesi görünür (Installed önce, Available ayrı, okunma zamanı). Veri yoksa nedeni söylenir (Dell'de seçenek kapalı olabilir; HPE'de bileşen firmware henüz okunmuyor). Firmware yalnız `hardware` modülü görür (kısıtlı yanıtta YOK; sohbette paylaşılmaz).
5. Testler: imleç tüm sunucuları sınır < sunucu sayısında da kapsar; Status/ComponentId kalıcı; BIOS türetilir ve boş turda silinmez; API firmware listesi Installed önce.

**Adım C2 — referans karşılaştırma (2026-11-01; kararlar kullanıcıdan alındı).**

Kararlar: (1) referans kapsamı **model VE şasi**; şasi referansı model referansını geçersiz kılar (şasi > model; şasi referansı yalnız o şasideki AYNI modeli kapsar). (2) Sunucu başına **«Kabul edildi»**: yalnız kabul anındaki sürüm güncel sürümle AYNI olduğu sürece geçerli (sürüm değişince düşer). (3) HPE bileşen firmware'i okunur (yalnız OneView **appliance** modu; OVGD'de uç yok) ve Sunucular satırında her sunucunun firmware sürümleri görünür.

Kapanış kriterleri (kod bunlardan ÖNCE yazılmadı sayılmaz; testler `test_hw_firmware_compare.py`):
1. HPE appliance: `fetch_firmware` açıkken her sunucu için `GET /rest/server-hardware/{id}/firmware` (izin listesinde; Dell ile aynı imleç/`firmware_max_per_run`; `meta.firmware_cursors[<yönetim noktası>]`). Biçim tanınmazsa boş (hata yok). Cihaz bazlı 404 atlanır; ağ/5xx döngüyü keser. Kimlik/yetki hatası mevcut `AuthHalt` kuralını izler.
2. Karşılaştırma yalnız `Installed` bileşenlerle; anahtar = normalize ad (MAC çıkarılır) + HPE konumu; aynı anahtar farklı sürümle tekrarlıyorsa belirsiz → kıyas dışı. Firmware satırı hiç yoksa yalnız BMC/BIOS sürümleri kullanılır (gerçek bileşen satırlarıyla eşleşmez → ölçülemedi).
3. Sürüm: ilk noktalı sayı dizisi sayısal karşılaştırılır; HPE ROM ailesi (`I42` ≠ `I41`) farklıysa, ya da biri ayrıştırılamazsa **ölçülemedi** — ASLA «düşük» denmez, bulgu üretilmez. Tek tamsayı güvenilir sayılmaz.
4. `hw.firmware.outdated` (orta) yalnız `outdated` durumunda (kabul edilmemiş, ≥1 bileşen düşük). Metin/kanıtta sürüm, BMC IP, seri YOK (yalnız bileşen adları + sayı).
5. API: `GET /hw/firmware/compare`; `POST/DELETE /hw/firmware/references`, `POST/DELETE /hw/firmware/accept` (yazma = operator; yalnız ainew tablolarına yazar, donanıma dokunmaz); sunucu ayrıntısında `firmware_status`. Firmware yalnız `hardware` modülü (`/hw/*`); kısıtlı yanıtta firmware alanları YOK.
6. Referans: modeli boş ya da firmware/BMC/BIOS verisi olmayan sunucu referans yapılamaz; şasisi belirlenemeyen sunucu şasi referansı olamaz.

Bilinen sınırlar: HPE `components[]` alan tipleri doğrulanmadı (sahada: Hayır); firmware okuması isteğe bağlı ve envanter aralığıyla (günlük) döner → 500 sunucu/200 sınır ≈ 3 gün; karşılaştırma verisi okunma zamanı kadar eskidir.

## Kararlar (kullanıcı onayı)

- RBAC: yeni `hardware` modülü. Sağlık bulguları herkese görünür; ayrıntılı donanım kartı `hardware` yetkisine bağlı; bulgu metninde BMC IP yok.
- Aralıklar: alarm 15 dk, envanter ve garanti günlük.
- OVGD: `x-api-version: 2` ile başla.
- Faz 3 atlandı (çalışma sonunda hatırlatılır).

## Kullanım derinleştirme (olay/incident, modüllere gömme, iki seviyeli yetki)

- **Olay/incident:** `services/hw/events.py` — sağlayıcı DURUMU → `SystemEvent` (`hw_health_critical`, `hw_alert` kritik; `hw_alert_recurring` uyarı ≥3×/24s). Dedupe `raw_data.external_key`; koşul kalkınca `resolved`, dönünce yeniden açılır. Kritik olay `incident_auto` ile incident açar; **aynı fiziksel sunucu = tek incident** (`hw|{hw_server_key}`). Platform etiketi: Linux/Windows eşleşmesi → o platform, ESXi → `virt`, eşleşmesiz → platformsuz. Metin/raw_data BMC IP, seri, UUID, URL içermez (`sanitize_text`). DEMO varsayılan olay üretmez; `scripts/hw_demo_seed.py events` opt-in (`[DEMO]`, kaynak `hw_demo`), `cleanup` yalnız onları ve onlardan doğan incident'ları siler.
- **Etki alanı:** `services/hw/impact.py` — ESXi host → VM sayısı/açık VM → `business_service_map` iş servisleri (kritik katman önce) → küme (`ha_risk`: kalan sağlıklı host < 2). Olay `raw_data.impact`, incident kartı ve donanım detayında.
- **Gömme:** liste rozeti (`HwBadge`; yalnız sorun varken), `/hw/targets-health`; incident detayında «İlgili donanım» (`/incidents/{id}/hardware`).
- **İki seviyeli yetki:** `linux`/`windows`/`virtualization` → yalnız `/hw/servers/by-target` + `/hw/targets-health` (GRANTS), yanıt `restricted` (BMC/seri/UUID/firmware/konsol YOK, alarm metni maskeli). Filo, rapor, eşleştirme ve tüm diğer `/hw/*` → `hardware` modülü. `/hardware` sayfası entegrasyon yoksa ana sayfaya yönlendirir.
- **Garanti/yenileme raporu** (`/hw/warranty-report`, CSV), **geçmiş** (olaylardan; ek tablo yok), **eşleşmeyen için öneri + elle bağlama** (`POST/DELETE /hw/links`, `method=manual`, otomatik eşleştirme bozmaz; operatör rolü).
- **Bilinçli olarak yapılmadı:** bildirim kanalı (ainew'de SMTP/webhook altyapısı yok; donanım olayları mevcut olay/incident hattına girer), ayrı sağlık-geçmişi tablosu (olaylar yeterli), BMC ham logları (Faz 3b).

## Faz 3a — Host donanım logları (iLO/iDRAC'e BAĞLANMADAN; firewall/ağ değişikliği YOK)

Karar (kullanıcı, 2026-10-27): Faz 3 ikiye bölündü. **3a** bu bölümdür; **3b** (doğrudan BMC/Redfish, BMC VLAN erişimi, BMC başına hesap) hâlâ kapsam dışıdır.

### Ne yapar

Mevcut erişimlerle (vCenter API, mevcut Linux/Windows log toplayıcıları) host kaynaklı DONANIM kayıtlarını `hw_log_entries` tablosunda toplar, sınıflandırır, gösterir:

| Kaynak | Hedef | Nasıl | Yeni erişim |
|---|---|---|---|
| `esxi_sel` | ESXi host | vCenter `HostHealthStatusSystem.FetchSystemEventLog` (IPMI SEL; salt-okunur) | Yok (mevcut vCenter oturumu) |
| `esxi_vmkernel` | ESXi host | vCenter `DiagnosticManager.BrowseDiagnosticLog` key `vmkernel`/`vmkwarning` (son N satır) → donanım kalıplarına süzülür | Yok; vCenter rolünde `Global.Diagnostics` gerekir |
| `linux_journal` | Linux fiziksel sunucu | Mevcut `log_collector` kaydı (`SystemEvent`, `source=log_collector`) donanım kalıplarına göre ayrıştırılır (MCE, EDAC/ECC, PCIe AER, thermal, PSU, IPMI, NVMe/SMART, `Hardware Error`) | Yok (yeni SSH komutu YOK) |
| `windows_event` | Windows fiziksel sunucu | Mevcut `windows_log_collector` kaydı (`source=windows_collector`) — WHEA-Logger, Kernel-Processor-Power, disk/`storahci`/`stornvme`, volmgr | Yok (yeni WinRM komutu YOK) |

Değişmez kurallar: yalnız okuma (`ClearSystemEventLog`, `ResetSystemHealthInfo` dahil tüm mutate metotlar `SOAP_MUTATE_DENY`'da); vCenter oturumu tur başına 1 kez açılır, açılamazsa o vCenter'ın tüm host'ları atlanır (yeniden deneme yok); host başına hata diğer host'ları durdurmaz; metin sunucuya gösterilmeden önce IPv4/seri maskelenir.

### Opsiyonellik / varsayılan

- `hw_host_logs_enabled` (Gelişmiş Ayarlar) **varsayılan KAPALI**. Kapalıyken: iş kuyruğa girmez, kart/uç hiçbir şey göstermez, vCenter'a ek çağrı yok. İlk canlı çalıştırmada (ESXi 8.0.1) üç hata bulunup düzeltildi: SOAPAction başlığı eksikti, `vmkwarning` anahtarı yoktu, log kuyruğu yerine başı okunuyordu (ayrıntı: `hw-api-sources.md`). Açma kararı kullanıcıya aittir.
- Aralık `hw_host_logs_interval_sec` (varsayılan 3600, min 900). Saklama 30 gün.
- Donanım sağlayıcı (OME/OneView) şart DEĞİL; capability `hw` ile bağlı değildir.

### Kapanış kriterleri (kod ÖNCE bunlara göre)

1. `hw_log_entries` genişler (idempotent ALTER; `server_id` artık opsiyonel); mevcut kurulum bozulmaz; tablo boş kalabilir.
2. Sınıflandırıcı saf fonksiyondur ve testlidir: bilinen kalıp → (kategori, önem); donanımla ilgisiz satır → eşleşme YOK (gürültü üretmez); bellek tek-bit düzeltilmiş (CE) = uyarı, düzeltilemez (UE)/MCE = kritik.
3. Tekilleştirme: aynı hedef + aynı normalize kayıt = TEK satır (`occurrences` artar, `last_seen_at` güncellenir); iki tur arka arkaya çalışınca satır sayısı değişmez.
4. vCenter ulaşılamaz/oturum açılamaz → yalnız o hypervisor atlanır, hata sayaçta; diğer kaynaklar (Linux/Windows) etkilenmez; mevcut veri silinmez.
5. API `GET /hw/host-logs` (`kind`,`id`,`severity`,`days`,`limit`): metin maskeli; `hardware` modülü tüm uca, `linux`/`windows`/`virtualization` yalnız kendi hedef kartına (GRANTS). Özellik kapalı/veri yok → `enabled=false`/boş (404/500 değil).
6. UI: Linux/Windows çekmecesi ve ESXi host paneli «Donanım günlükleri» kartı YALNIZ kayıt varken görünür; yoksa hiçbir şey render edilmez. TR/EN `t('key')`.
7. Salt-okunur testi: vCenter istemcisinin yeni çağrıları yalnız `FetchSystemEventLog` + `BrowseDiagnosticLog`; mutate metot listesi testle sabit.
8. Testler: sınıflandırıcı, tekilleştirme, vCenter yanıt ayrıştırma (örnek XML), kapalı bayrakta no-op, API yetki/maskeleme, UI kartı (kayıt yok → render yok).
9. **Kapandı** yalnız insan testi (İH) sonrası yazılır: gerçek vCenter'da bayrak açılır, en az 1 ESXi host için SEL/vmkernel sonucu (veya açık "boş/desteklenmiyor" nedeni) görülür. Bu yapılmadan durum «Uygulandı, İH bekliyor».

### Durum (2026-10-27)

**Uygulandı, İH bekliyor.** Kriter 1–8 karşılandı: `host_log_rules.py` (sınıflandırıcı), `host_logs.py` (toplama/tekilleştirme/saklama), `vcenter_client.get_host_hw_logs`, `GET /hw/host-logs` (+ GRANTS), `HwHostLogsCard` (Linux/Windows çekmecesi + ESXi host paneli), `fleet.hw_host_logs` (bayrak kapalıyken iş üretmez), testler `test_hw_host_logs.py` (65) + `hwHostLogs.test.tsx` (4). Kriter 9 (gerçek vCenter'da bayrak açıp en az 1 host için SEL/vmkernel sonucu veya açık «desteklenmiyor» nedeni görmek) yapılmadan «Kapandı» YAZILMAZ. Frontend imajı yeniden derlenmedi (kart kayıt yokken görünmez; derleme dağıtımla).

### Kapsam dışı (3a)

Sohbet tool'u (`hw_logs_fetch`) ve olay/incident üretimi bu adımda YOK (Linux/Windows kayıtları zaten `SystemEvent` hattında; ESXi için vCenter olayları zaten toplanıyor); ipmitool SEL / `ipmitool` SSH komutu (sudo + paket gerekir); iLO IML / iDRAC LCL (3b).

## Host sınıfı gruplaması (Hardware sayfası, Sunucular sekmesi)

Her portal kaydı (`hw_servers`) TAM BİR sınıfa girer; sınıf toplamı = kayıt toplamı. Öncelik: **hypervisor host eşleşmesi > şasi/blade > tekil fiziksel**.

| Sınıf | Kural |
|---|---|
| `esxi` / `ocp` / `olvm` / `hv_other` | `HwHostLink` bir `HypervisorHostInventory` kaydına bağlı; sınıf `Hypervisor.hypervisor_type`'tan (VMWARE / OPENSHIFT_VIRT / KVM / diğer) |
| `chassis` | hypervisor'e eşleşmemiş + `form_factor=blade` veya şasi/yuva bilgisi var |
| `physical` | Linux/Windows sunucuya eşleşmiş VEYA eşleşmemiş rack/standalone |

- API: `GET /hw/servers?host_class=…` (geçersiz değer 422), `GET /hw/summary` → `by_class`, satırlarda `host_class`.
- Yeni hedef türü GEREKMEDİ: OpenShift/OLVM host'ları da `hypervisor_host_inventory`'dedir (`target_kind='esxi'` aslında «hypervisor host»).
- **Sınır:** OpenShift/OLVM host envanterinde seri numarası YOK (`serial_number` boş) → otomatik eşleşme yalnız hostname ile (düşük güven) yapılır; bu yüzden bu sınıflar çoğu ortamda boş kalır. Seri/UUID kaynağı ayrı bir iştir (Faz 2).
- Bir blade ESXi'ye eşleşmişse `esxi` sayılır (şasi adı satırda görünmeye devam eder); «Şasi / blade» chip'i yalnız hypervisor'e eşleşmemiş blade'leri sayar.
- Sınıf yalnız gruplama/filtredir; yeni veri toplamaz, ek bağlantı yoktur.

## Faz 3b — Donanım Logları sekmesi, şasi alarmı, in-band ipmitool, BMC/Redfish (2026-10-27)

Karar (kullanıcı): Hardware sayfasının hedefi **donanım logları**dır (K8s/oVirt/genel OS olayları değil). ESXi (vCenter), OLVM/OpenShift host'ları, tekil fizikseller (portal + Linux sayfası) ve HP/Dell şasi logları tek yerde görünür. Sıra: (A) «Donanım Logları» sekmesi + şasi alarm eşlemesi, (B) Linux fizikselde in-band `ipmitool` (BMC hesabı gerekmez), (C) BMC IP alanı + kimlik profilleri, (D) Redfish toplayıcı. Hepsi ayrı bayrakla, **varsayılan KAPALI**.

### Kimlik bilgisi çözümü (C)
Deterministik, en özelden genele: **host'a özel profil > portal (entegrasyon) profili > üretici (dell/hpe) varsayılanı > global**. Seçilen hesap reddedilirse o host `auth_failed` olur ve düzeltilene kadar durur; **zincirleme (bir sonrakini deneme) YOK** (BMC hesap kilidi). BMC IP önceliği: **manuel > portal (`hw_servers.bmc_ip`) > keşif (`ipmitool lan print`)**; keşif manuelin üzerine yazmaz.

### Kapanış kriterleri (kod ÖNCE bunlara göre)

**A — Donanım Logları sekmesi + şasi**
1. `GET /hw/log-overview` yalnız `hardware` modülü (diğerleri 403); tüm `hw_log_entries` kaynakları + şasi alarmları; her satırda `host_class` (`esxi|ocp|olvm|hv_other|chassis|physical`) ve `source`; `class/source/severity/days` süzgeçleri; `counts.by_class/by_source/by_severity`; `sources[]` (kaynak başına bayrak, son toplama, kayıt sayısı). Veri yoksa `enabled/available=false` + boş (404/500 değil). Metinler maskeli.
2. Şasi alarmı: OME `HwAlert.server_ref == HwEnclosure.provider_ref`, OneView `HwAlert.entity_name == HwEnclosure.name` (aynı instance) → sınıf `chassis`, kaynak `portal_alert`. Sunucu/blade'e ait alarm şasiye YAZILMAZ (çift sayım yok). OME yalnız Warning/Critical saklar (not düşülür).
3. UI: sekme «Donanım Logları» (sınıf chip'leri, kaynak/önem/gün süzgeci, kaynak etiketi, boşken açık neden). TR/EN.

**B — in-band ipmitool (Linux fiziksel)**
4. Komutlar sabit izin listesinde: `ipmitool sel elist`, `ipmitool lan print <1–8>`, `ipmitool mc info`, `ipmitool sel time get`; hepsi `sudo -n`. `sel clear/delete`, `power`, `mc reset`, `raw` vb. kodda YOK (test). Kurulum/modprobe YOK.
5. `ipmitool` yok / `/dev/ipmi0` yok / sudo yetkisi yok → hedef durumu (`no_ipmitool|no_device|no_sudo`), hata sayılmaz; VM (`VIRTUAL`) ve Windows atlanır.
6. SEL ayrıştırıcı (saf): `ID | tarih | saat | sensör | olay | Asserted/Deasserted` → mesaj (kayıt no ve zaman düşülür) + sınıflandırıcı; tekilleştirme mevcut `(target, source=ipmi_sel, event_key)`. BMC saati: ana makine UTC'si ile fark ≤15 dk → UTC; 30 dk katı sapma (≤14 sa) → saat dilimi; aksi → toplama zamanı (çıktıya «BMC saati şüpheli»).
7. `hw_ipmi_inband_enabled` varsayılan KAPALI; kapalıyken SSH'a ek komut gitmez. Seyrek (host log aralığı), host başına tek komut, düşük eşzamanlılık, komut zaman aşımı.
8. BMC IP keşfi: kanal 1–8, geçerli IP (0.0.0.0 değil) → `hw_bmc_endpoints` (`ip_source=discovered`); `manual` ise ezilmez.

**C — BMC IP + kimlik profilleri**
9. Tablolar `hw_bmc_profiles` (scope global|vendor|instance, vendor, instance_id, `credential_ref` şifreli, `verify_tls`) ve `hw_bmc_endpoints` (hedef, bmc_ip, ip_source, profile_id, enabled, status, last_error, auth_halted). Parola hiçbir yanıtta/log'da dönmez.
10. Çözümleme saf fonksiyon + test: öncelik sırası, zincirleme YOK, kimlik yoksa `no_cred`, IP yoksa `no_ip`.
11. API (`hardware` modülü okur; **admin** yazar): profil CRUD, uç nokta oluştur/güncelle (manuel IP, profil, aç/kapa), toplu atama, tek-deneme **Bağlantıyı test et** (bekleme süresi; yalnız başarılıysa `auth_halted` kalkar; kaydetmek tek başına kaldırmaz).
12. UI: Ayarlar → «BMC» sekmesi (global/üretici profil + durum), portal entegrasyon formunda opsiyonel BMC hesabı (instance profili), Hardware → «BMC» sekmesi (host tablosu, manuel IP, toplu atama, test, durum).

**D — Redfish toplayıcı**
13. İstemci yalnız GET (oturum için POST YOK — Basic auth); yollar `/redfish/v1/` kökünden bağlantı izlenerek (`Managers`/`Systems` → `LogServices` → `Entries`) bulunur; üretici yolu sabitlenmez; yazma yöntemi kodda yok (test).
14. Kimlik reddi (401/403) → o uç nokta `auth_failed`, **aynı profili kullanan kalan uç noktalara bu turda denenmez**; yeniden deneme YOK; ağ/zaman aşımı → `unreachable`, sonraki turda tekrar.
15. Sıralı, düşük eşzamanlılık, uç nokta başına zaman aşımı, tur başına süre bütçesi. TLS doğrulaması profil bazında (varsayılan kapalı + UI uyarısı; CA yolu desteklenir).
16. Girdi: `Created` (RFC3339, UTC'ye çevrilir), `Severity` (OK→info, Warning→warning, Critical→critical), `Message`/`EntryCode`; saklama 30 gün; mevcut tekilleştirme/maskeleme; kaynak `bmc_redfish`.
17. `hw_bmc_logs_enabled` varsayılan KAPALI; kapalıyken BMC'ye hiç bağlanılmaz; uç nokta aç/kapa; portal kaydı olup bağlı hedef varsa log o hedefe (server|esxi), yoksa `hw` hedefine yazılır.
18. Testler: sahte (mock) Redfish yanıtları — gerçek BMC bu ortamda YOK.

**İH:** (a) gerçek fiziksel Linux hostta `hw_ipmi_inband_enabled` açıp `ipmi_sel` kaydı veya açık neden görmek, (b) gerçek iLO/iDRAC'te Redfish ile en az 1 log veya açık neden. **Bunlar yapılmadan «Kapandı» YAZILMAZ** (durum: «Uygulandı, İH bekliyor»).

### Durum — Faz 3b (2026-10-27): **Uygulandı, İH bekliyor** (Kapandı DEĞİL)

- Kod: A (log-overview + şasi alarmı + «Donanım Logları» sekmesi), B (in-band ipmitool), C (BMC profilleri/uç noktalar + Ayarlar → BMC + portal formunda BMC hesabı + Hardware → BMC sekmesi), D (Redfish toplayıcı + kanarya/`auth_halted` orkestrasyonu) tamam; üç bayrak (`hw_host_logs_enabled`, `hw_ipmi_inband_enabled`, `hw_bmc_logs_enabled`) varsayılan KAPALI.
- Doğrulama: backend `test_hw_bmc.py` + `test_hw_bmc_api.py` (mock BMC/ipmitool; salt-GET, yasak yol, tek kimlik denemesi, zincirleme yok, parola dönmez); frontend `hwBmcTabs.test.tsx`; tam backend paketi geçti (2 test yalnız tam koşuda kırıldı, tek başına geçiyor: `test_exec_snapshot`, `test_llm_6c` — bu işle ilgisiz).
- **Gerçek BMC / fiziksel sunucu bu ortamda YOK** → B ve D yalnız sahte yanıtlarla doğrulandı.
- Bekleyen İH: (a) gerçek fiziksel Linux hostta `hw_ipmi_inband_enabled` açıp `ipmi_sel` kaydı veya açık neden (`no_ipmitool|no_device|no_sudo`) görmek; (b) gerçek iLO/iDRAC'te Redfish ile ≥1 log veya açık neden (`auth_failed|unreachable|unsupported`) görmek. Kimlik hatası olursa BMC durur; yalnız başarılı «Bağlantıyı test et» sürdürür.
- Yapılmadı: «Linux sunucusu eklerken isteğe bağlı BMC IP/profil sorusu» (şimdilik Hardware → BMC sekmesinden elle girilir / ipmitool ile keşfedilir).
