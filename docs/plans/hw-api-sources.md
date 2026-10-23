# Donanım API Kaynak Kaydı

Kural: kodda çağrılan her endpoint ve okunan her alan bu dosyada bir satırdır. İstemcideki endpoint listesi (`backend/app/services/hw/endpoints.py`) ile bu dosya `test_hw_api_sources.py` ile karşılaştırılır. Erişim tarihi: 2026-10-23.

Sütunlar: ürün | sürüm | endpoint/alan | anlamı | birim/tip | gerekli rol/lisans | doküman | sahada doğrulandı mı

## Dell OpenManage Enterprise 4.7.0

Doküman: **OpenManage Enterprise API 4.7.0** (Dell Developer Portal dışa aktarımı, PDF 4947 sayfa; `https://developer.dell.com/apis/5898/versions/4.7.0`).

| ürün | sürüm | endpoint / alan | anlamı | birim/tip | rol/lisans | doküman bölümü | sahada |
|---|---|---|---|---|---|---|---|
| OME | 4.7.0 | `POST /api/SessionService/Sessions` gövde `UserName`,`Password`,`SessionType="API"` → 201, yanıt başlığı `X-Auth-Token`, `Location` | oturum aç | string | RSA SecurID açık hesap REST kullanamaz | Getting Started › Authentication | Hayır |
| OME | 4.7.0 | `DELETE /api/SessionService/Sessions('<oturum Id>')` (oturum `Id` bir GUID'dir; oturum açma yanıtındaki `Id` / `Location` kullanılır) | oturum kapat | — | dokümanda `['VIEW','SECURITY_SETUP']` (Viewer ile silinebilirliği DOĞRULANMADI → en iyi çaba, başarısızlık yutulur) | SessionService › Delete session | Hayır |
| OME | 4.7.0 | `GET /api/ApplicationService/Info` → `Version` (ör. `4.7.0`), `Name` | OME sürümü → destek seviyesi (Doğrulanmış 4.7.x / Uyumlu / Desteklenmeyen <3) | string | VIEW | ApplicationService › Info | Hayır |
| OME | 4.7.0 | `GET /api/GroupService/Groups` → `Id`,`Name` (“All Devices” kök grup) | kök grup id'si | int/string | VIEW | GroupService › Groups | Hayır |
| OME | 4.7.0 | `GET /api/GroupService/Groups({groupId})/AllLeafDeviceSummaries` (`$top` ≤ 3000, `$skip`) | cihaz özeti (performans için `Devices` yerine önerilir) | DeviceMinModel: `Id` int, `DeviceName`, `Model`, `Identifier`, `DeviceServiceTag`, `Type` int (1000 Server, 2000 Chassis; diğer değerler kullanılmaz), `Status` int, `PowerState` int (1 Unknown, 17 ON, 18 OFF), `ConnectionState` bool, `ManagedState` int, `IpAddress`, `ChassisName`, `SlotName`, `DeviceManagement[].NetworkAddress`, `DeviceManagement[].ManagementProfile[].Version`, `.AgentName` | VIEW | Performance considerations (#4), GroupService › Get device data, Paginating data | Hayır |
| OME | 4.7.0 | `Status` değerleri 1000 Normal, 2000 Unknown, 3000 Warning, 4000 Critical, 5000 No Status | genel sağlık | int | — | dokümandaki global status enumu (AllLeafDeviceSummaries `Status` ile aynı olduğu DOĞRULANMADI; örnekte 1000 geliyor) | Hayır |
| OME | 4.7.0 | `GET /api/DeviceService/Devices({id})/InventoryDetails('deviceSoftware')` → `InventoryInfo[]`: `SoftwareType` (FRMW/BIOS/APAC), `DeviceDescription`, `Version`, `Status` (Installed/Available) | firmware envanteri | string | VIEW | DeviceService › InventoryDetails | Hayır |
| OME | 4.7.0 | `…/InventoryDetails('deviceLocation')` → `Datacenter`,`Rack`,`Aisle` | konum | string | VIEW | aynı | Hayır |
| OME | 4.7.0 | `GET /api/AlertService/Alerts` (`$orderby=TimeStamp desc`, `$top`,`$skip`; yalnız Warning(8)/Critical(16) saklanır) → `Id`,`SeverityType` (1 Unknown, 2 Info, 4 Normal, 8 Warning, 16 Critical),`AlertDeviceId`,`AlertDeviceIdentifier`,`CategoryName`,`SubCategoryName`,`StatusType`,`TimeStamp` (UTC metin),`Message`,`AlertMessageId` | alarmlar | — | VIEW | AlertService › Alerts | Hayır |
| OME | 4.7.0 | `GET /api/WarrantyService/Warranties` → `DeviceId`,`DeviceIdentifier`,`ServiceLevelDescription`,`ServiceLevelCode`,`ServiceLevelGroup`,`ServiceProvider`,`StartDate`,`EndDate` (`0001-01-01` = yok),`DaysRemaining` | garanti (cihaz başına birden çok kayıt) | — | VIEW; veriyi OME Dell'den alır (internetsiz OME'de boş: not_measurable) | WarrantyService › Warranties | Hayır |

**YASAK (çağrılmaz):** `…/VirtualSession`, `…/BlinkStatus`, `…/Actions/*`, tüm POST/PUT/PATCH/DELETE (oturum hariç), `…/HardwareLogs` (Faz 3 kapsamı dışı bırakıldı; endpoint doğrulandı: `GET /api/DeviceService/Devices({deviceId})/HardwareLogs`, VIEW — kullanılmıyor).

Doğrulanmadı: sayfalama dışında hız sınırı; `Devices.Status` ↔ rapor enumu eşitliği; Viewer rolünün oturum silmesi; `InventoryDetails` alt alan tipleri; blade/rack (`SlotName`/`ChassisName` ile form faktör; model adından türetme yok).

## HPE OneView (appliance)

Doküman: **HPE OneView REST API Reference** — API 3800 (OneView 6.60; `support.hpe.com/docs/display/public/dp00003325en_us`), API 7600 (10.00), API 9000 (11.20/11.40); kullanıcı tarafından appliance'tan kaydedilen sayfalar (yalnız arama dizini + uç nokta listesi okunabildi; alan tipi/birimi OKUNAMADI).

| ürün | sürüm | endpoint / alan | anlamı | birim/tip | rol/lisans | doküman | sahada |
|---|---|---|---|---|---|---|---|
| OneView | tümü | `GET /rest/version` → `currentVersion`,`minimumVersion` | API sürümü tespiti | int | oturumsuz | appliance `/rest/version` (kullanıcı doğruladı: 3800, 7600, 9000) | Evet (kullanıcı) |
| OneView | tümü | `POST /rest/login-sessions` gövde `userName`,`password`,`authLoginDomain`; başlık `X-API-Version`; yanıt `sessionID` → sonraki isteklerde `Auth` başlığı | oturum aç | string | — | Login Sessions (dizin: alan adları doğrulandı) | Hayır |
| OneView | tümü | `DELETE /rest/login-sessions` (başlık `Auth`) | oturum kapat | — | — | Login Sessions | Hayır |
| OneView | tümü | `GET /rest/server-hardware` (`start`,`count`; yanıt `members`,`nextPageUri`) ve `GET /rest/server-hardware/{id}` | sunucu envanteri | alanlar: `name`,`serverName`,`model`,`serialNumber`,`virtualSerialNumber`,`uuid`,`formFactor`,`locationUri`,`position`,`powerState`,`status`,`romVersion`,`mpHostInfo.mpHostName`,`mpHostInfo.mpIpAddresses[]`,`mpFirmwareVersion`,`serverProfileUri` (alan ADLARI dokümanda geçiyor; tip/birim DOĞRULANMADI) | salt-okunur rol | Server Hardware | Hayır |
| OneView | 10.00+ (7600+) | `GET /rest/server-hardware/{id}/firmwareInventory`, `/processors`, `/powerSupplies`, `/networkAdapters`, `/thermal`, `/softwareInventory`, `/chassis` | bileşen ayrıntısı | — | salt-okunur | Server Hardware (7600 farkı) | Hayır |
| OneView | tümü | `GET /rest/server-hardware/{id}/firmware`, `/utilization` | firmware (6.60+), kullanım | — | salt-okunur | Server Hardware | Hayır |
| OneView | tümü | `GET /rest/enclosures`, `/rest/logical-enclosures` | enclosure (arıza alanı) | — | salt-okunur | Enclosures | Hayır |
| OneView | tümü | `GET /rest/alerts` | appliance alarmları | — | salt-okunur | Alerts | Hayır |

**YASAK (çağrılmaz):** `PUT …/powerState`, `PUT …/refreshState`, `PUT …/mpFirmwareVersion`, `PATCH …/{id}`, `POST /rest/server-hardware`, `POST …/discovery`, `…/remoteConsoleUrl`, `…/javaRemoteConsoleUrl`, `…/iloSsoUrl`, `…/mpSessionKey` (11.x), `…/environmentalConfiguration` PUT.

Doğrulanmadı: `securityStatus` alanı hiçbir sürümde YOK (dizinde 0) → güvenlik durumu `not_measurable`; sayfalama varsayılan/maks `count`; 11.40 için ayrı doküman (yüklenen 8600 dokümanı 11.40 değil); 6.60 destek durumu (resmi lifecycle).

## HPE OVGD 3.00.00 (API v2 sözleşmesi)

Doküman: **HPE OneView Global Dashboard REST API (v2)** — `HewlettPackard/hpe-globaldashboard-swagger` (Swagger 2.0, `info.version=2`); OVGD `/apidoc/` (v300; OVGD 3.0 `minimumVersion 2`, `currentVersion 300` — kullanıcı doğruladı).

| ürün | sürüm | endpoint / alan | anlamı | birim/tip | rol/lisans | doküman | sahada |
|---|---|---|---|---|---|---|---|
| OVGD | 3.00 (x-api-version 2) | `GET /rest/version` | sürüm | int | oturumsuz | OVGD | Evet (kullanıcı) |
| OVGD | v2 | `POST /rest/login-sessions/` (`userName`,`password`,`authLoginDomain`); `DELETE /rest/login-sessions/` | oturum | — | — | swagger | Hayır |
| OVGD | v2 | `GET /rest/appliances` | appliance keşfi | — | salt-okunur | swagger | Hayır |
| OVGD | v2 | `GET /rest/resource-alerts` (`count`/`start` ile sayfalama; varsayılan/maks değerler DOĞRULANMADI) | birleşik alarm | — | salt-okunur | swagger | Hayır |
| OVGD | v2 | `GET /rest/server-hardware`, `/rest/enclosures` | özet envanter | — | salt-okunur | swagger | Hayır |

**YASAK:** `…/iloSsoUrl`, `/rest/enclosures/{id}/oaSsoUrl`, `/rest/appliances/{id}/sso`, `POST /rest/appliances`, `POST /rest/server-hardware`.

Doğrulanmadı: OVGD 3.0'ın v2 davranışı (2019 tarihli swagger) — fixture ile; API 300 farkı (`/apidoc/` OpenAPI indirilmedi).

## Ürün yaşam döngüsü

- OVGD 3.00.00, OME 4.7.0, OneView 10.00 / 11.20 / 11.40: destek durumu resmi sayfadan bu ortamdan doğrulanmadı (Doğrulanmadı).
- OneView 6.60: HPE forum bildirimi LTS 2023-12-31'de bitti diyor — forum kaynağı sayılmaz; resmi HPE yaşam döngüsü sayfası kullanıcı tarafından doğrulanacak.
