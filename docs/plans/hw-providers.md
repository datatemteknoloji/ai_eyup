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
Ertelenen (kaynak alanı doğrulanmadı → `not_measurable`): `hw.component.predictive_failure`, `hw.component.redundancy_lost`, `hw.memory.correctable_errors_recurring`, `hw.firmware.outdated`, `hw.bmc.security_at_risk` (`securityStatus` hiçbir OneView API dokümanında yok).

## Sohbet

READ_ONLY tool'lar (yalnız capability `hw` + `hardware` modülü): `hw_server_status`, `hw_alerts_summary`. (`hw_logs_fetch` yok — Faz 3 kapsam dışı.)

## Kararlar (kullanıcı onayı)

- RBAC: yeni `hardware` modülü. Sağlık bulguları herkese görünür; ayrıntılı donanım kartı `hardware` yetkisine bağlı; bulgu metninde BMC IP yok.
- Aralıklar: alarm 15 dk, envanter ve garanti günlük.
- OVGD: `x-api-version: 2` ile başla.
- Faz 3 atlandı (çalışma sonunda hatırlatılır).
