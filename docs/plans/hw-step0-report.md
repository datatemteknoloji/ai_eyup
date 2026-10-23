# Adım 0 Raporu — Donanım Sağlayıcı Çerçevesi

Tarih: 2026-10-23. Kod yazılmadan önceki analiz (özet).

1. **Veeam çerçevesi — yeniden kullanılacak:** `integration_instances` (+ `credential_ref`, `last_status`), `services/capabilities.py::_collect`, sağlayıcı kaydı (`backup/registry.py`), tipler (`backup/protocol.py`), fleet job deseni (`fleet_jobs.run_backup_sync` + `fleet_lock`, `background_tasks._periodic_backup_sync`), method registry, bulgu kataloğu. **Genelleştirilecek:** `capabilities._collect` içindeki `has_real` kategoriye bakmıyor (Veeam gerçek instance'ı HW demosunu bastırır); `capabilities_payload` yalnız `has_backup`/`backup_demo`; kayıt ve tipler `services/backup/` altında.
2. **Seri/service tag/UUID/BMC alanları (tablo:kolon):** `hypervisor_host_inventory.vendor/model/uuid` (service tag/seri YOK; `vcenter_client` `otherIdentifyingInfo` bilerek atlıyor). OLVM: yalnız vendor/model (`findings/collectors/olvm.py`; `hardware_information` seri/UUID ve `power_management.address` okunmuyor). OpenShift: `BareMetalHost` repoda YOK; BMC adresi okunmuyor.
3. **Linux/Windows envanteri:** `servers` (tek tablo, `os_type`, `server_type` PHYSICAL/VIRTUAL) seri/UUID tutmuyor. Linux `dmidecode` yalnız canlı sohbet toplayıcısında (kaydedilmiyor); Windows yok.
4. **Madde 2 (donanım) kontrolleri:** `virt_health_checks.py` hardware bölümü vCenter sensör özeti tabanlı (`hw.host.*` check'leri). Yeni `hw.*` bulgular farklı kimlik alanı (`hw.server.*`, `hw.alert.*` ...) ile eklenir; çakışmada kaynak önceliği donanım sağlayıcısı > vCenter sensör.
5. **Olay zaman çizelgesi:** `virt_incident_timeline.py` yeni olay kaynağı eklenir (donanım alarmı).
6. **Çakışan/farklı isimlendirme:** `integration_instance.py` docstring kategorisi “bmc”; bu çalışma `hardware` kullanır. Mevcut `hw.host.*` method ailesi vCenter sensörleri içindir; yeni bulgular `hw.server.*`, `hw.alert.*`, `hw.warranty.*`, `hw.provider.*` olarak ayrı.
7. **Test ortamı:** OME 4.7.0 (Build 105); OVGD 3.00.00 (API 300); OneView 6.60.04 (3800), 10.00 (7600), 11.20 ve 11.40 (9000). iLO 5 (3.09/3.18) ve iLO 6 (1.59). Bu geliştirme ortamından müşteri portallarına erişim YOK (fixture/doküman tabanlı).
8. **Kaynak envanteri:** `hw-api-sources.md`. Erişilebilen: OME 4.7.0 API PDF (kullanıcı), OneView 3800/7600/9000 sayfaları (kullanıcı), OVGD v2 swagger (GitHub), HPE OVGD blog. Erişilemeyen: support.hpe.com (JS içerik), OVGD `/apidoc/` OpenAPI (müşteri ağı).
9. **Destek durumu (üretici yaşam döngüsü):** bu ortamdan doğrulanamadı; 6.60 için forum bildirimi (LTS 2023-12-31) kaynak sayılmaz — Doğrulanmadı.

Onay: kullanıcı planı onayladı; kod aşamasına geçildi.
