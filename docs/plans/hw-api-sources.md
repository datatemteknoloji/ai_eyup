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
| OME | 4.7.0 | `GET /api/DeviceService/Devices({id})/InventoryDetails('deviceSoftware')` → `InventoryInfo[]`: `SoftwareType` (FRMW/BIOS/APAC), `DeviceDescription`, `Version`, `Status` (Installed/Available; PDF örneğinde `DCIM:PREVIOUS#…` satırları `Available`), `ComponentId` (string). Karşılaştırma yalnız `Installed`; Dell `bios_version` = `SoftwareType=BIOS` + `Status=Installed` | firmware envanteri | string | VIEW | DeviceService › InventoryDetails | Hayır |
| OME | 4.7.0 | `…/InventoryDetails('deviceLocation')` → `Datacenter`,`Rack`,`Aisle` | konum | string | VIEW | aynı | Hayır |
| OME | 4.7.0 | `GET /api/AlertService/Alerts` (`$orderby=TimeStamp desc`, `$top`,`$skip`; yalnız Warning(8)/Critical(16) saklanır) → `Id`,`SeverityType` (1 Unknown, 2 Info, 4 Normal, 8 Warning, 16 Critical),`AlertDeviceId`,`AlertDeviceIdentifier`,`CategoryName`,`SubCategoryName`,`StatusType`,`TimeStamp` (UTC metin),`Message`,`AlertMessageId` | alarmlar | — | VIEW | AlertService › Alerts | Hayır |
| OME | 4.7.0 | `GET /api/WarrantyService/Warranties` → `DeviceId`,`DeviceIdentifier`,`ServiceLevelDescription`,`ServiceLevelCode`,`ServiceLevelGroup`,`ServiceProvider`,`StartDate`,`EndDate` (`0001-01-01` = yok),`DaysRemaining` | garanti (cihaz başına birden çok kayıt) | — | VIEW; veriyi OME Dell'den alır (internetsiz OME'de boş: not_measurable) | WarrantyService › Warranties | Hayır |

**YASAK (çağrılmaz):** `…/VirtualSession`, `…/BlinkStatus`, `…/Actions/*`, tüm POST/PUT/PATCH/DELETE (oturum hariç), `…/HardwareLogs` (Faz 3 kapsamı dışı bırakıldı; endpoint doğrulandı: `GET /api/DeviceService/Devices({deviceId})/HardwareLogs`, VIEW — kullanılmıyor).

Şasi/yuva (2026-11-01, OME 4.7.0 PDF tarandı): `DeviceMinModel` (AllLeafDeviceSummaries) şasi/yuva için YALNIZ `ChassisName` ve `SlotName` verir; `SlotNumber` ve `ChassisServiceTag` bu şemada YOK (`SlotConfiguration` şeması yalnız `ChassisName` içerir). Bunlar yalnız OME-Modular (MX) örneklerinde (Dell `dellemc-openmanage-ansible-modules`) görülür ve OME 4.7.0 dokümanında geçmez → okunmaz. `SlotName` kullanıcı tarafından yeniden adlandırılabilir (`ome_chassis_slots`); bu yüzden Dell şasi–blade eşleşmesi `ChassisName` adıyla, yalnız aynı yönetim noktasında ad TEKİL ise yapılır (belirsizse eşleştirilmez). OneView/OVGD'de kimlik (`locationUri` kuyruğu ↔ enclosure `uri`) kullanılır.

Doğrulanmadı: sayfalama dışında hız sınırı; `Devices.Status` ↔ rapor enumu eşitliği; Viewer rolünün oturum silmesi; `InventoryDetails` alt alan tipleri; blade/rack (`SlotName`/`ChassisName` ile form faktör; model adından türetme yok).

## VMware vCenter — host donanım logları (Faz 3a)

Doküman: **vSphere Web Services API** (`HostHealthStatusSystem`, `DiagnosticManager`). Mevcut vCenter SOAP oturumu kullanılır (yeni hesap/port yok). **Sahada doğrulandı (2026-10-27, vCenter «office», ESXi 8.0.1, HP ProLiant DL380 G7):** (1) isteklerde `SOAPAction: "urn:vim25/6.7"` başlığı ZORUNLU — yoksa vCenter 2.5u2 sürümüyle çözer ve `FetchSystemEventLog` "Unable to resolve WSDL method name" fault'u verir (5.5 başlığı da çözemez); (2) `FetchSystemEventLog` gerçek SEL döndürür (64 kayıt, 2011–2023; ESXi 8'de boş DEĞİL); (3) `QueryDescriptions` bu host'ta `fdm, hostd, vmkernel, vpxa` verir → `vmkwarning` anahtarı YOK (`InvalidArgument`); (4) `BrowseDiagnosticLog` `start` verilmezse dosyanın BAŞINI döndürür; aralık dışı `start` ile `lineEnd` toplam satırı verir → kuyruk = (toplamı sorgula, `total-N+1`'den oku). İH (insan testi) hâlâ bekliyor.

| ürün | sürüm | metot / alan | anlamı | birim/tip | rol | doküman | sahada |
|---|---|---|---|---|---|---|---|
| vCenter | 6.7+ (ESXi 8'de boş/fault olabilir) | `HostHealthStatusSystem.FetchSystemEventLog` → `SystemEventInfo[]`: `recordId`, `when`, `selType`, `message`, `sensorNumber` | host IPMI SEL kayıtları (salt-okunur) | string/int | Read-only (Host.Config.… gerekmez; sağlık sorgusu) | vim.host.HealthStatusSystem | Hayır |
| vCenter | 6.7+ | `DiagnosticManager.BrowseDiagnosticLog(host, key, start?, lines)` → `DiagnosticManagerLogHeader`: `lineStart`, `lineEnd`, `lineText[]`; `key` yalnız `vmkernel`, `vmkwarning` | ESXi log dosyasının son N satırı (`start` verilmezse BAŞI döner; toplam satır aralık dışı `start` ile öğrenilir, sonra kuyruk okunur) | string | `Global.Diagnostics` | vim.DiagnosticManager | Hayır |
| vCenter | 6.7+ | `HostSystem` property: `configManager.healthStatusSystem`, `runtime.connectionState`, `name` | SEL için MOR; bağlı olmayan host atlanır | MOR/string | Read-only | vim.HostSystem | Hayır |

**YASAK (çağrılmaz; `SOAP_MUTATE_DENY`):** `ClearSystemEventLog`, `ResetSystemHealthInfo`, `RefreshHealthStatusSystem`. Linux/Windows için yeni SSH/WinRM komutu YOKTUR (mevcut `SystemEvent` kayıtları ayrıştırılır).

`lineText` zaman damgası ISO `…Z` (doğrulandı); SEL `when` saat dilimsiz (UTC varsayılır); SEL kalıcı geçmiştir → saklama penceresinden (30 gün) eski kayıtlar atlanır. Doğrulanmadı: büyük kümelerde `BrowseDiagnosticLog` süresi (host başına 2 çağrı, 45 sn zaman aşımı).

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
| OneView (appliance modu) | API ≥ 300 | **KULLANILIYOR:** `GET /rest/server-hardware/{id}/firmware` → `components[]`: `componentName`, `componentVersion`, `componentLocation` (model `ServerFirmwareInventory`; alan adları API doküman dizininden) | bileşen firmware (kurulu sürüm) | alan TİPLERİ doğrulanmadı → yalnız metin/sayı kabul edilir, tanınmayan biçim = boş (ölçülemedi) | salt-okunur | OneView REST API › Server Hardware | **Hayır** (sahada doğrulanmadı) |
| OVGD | — | `/rest/server-hardware/{id}/firmware` OVGD'de YOK: bileşen firmware yalnız appliance modunda | — | — | — | — | — |
| OneView | tümü | `GET /rest/enclosures`, `/rest/logical-enclosures` | enclosure (arıza alanı) | — | salt-okunur | Enclosures | Hayır |
| OneView | tümü | `GET /rest/alerts` | appliance alarmları | — | salt-okunur | Alerts | Hayır |

Kasa yuvaları (2026-11-01): OneView `GET /rest/enclosures` → `deviceBayCount` (yuva sayısı; kullanılır, tip DOĞRULANMADI → yalnız `int` kabul edilir). Dizinde `deviceBays[]` (`bayNumber`, `devicePresence`), `subsumed` ve `empty` sözcükleri geçer ama alan tipi/değer kümesi OKUNAMADI → okunmaz. Bu yüzden arayüz «boş yuva» DEMEZ: `deviceBayCount` içinde sunucu kaydı olmayan yuva için «Sunucu kaydı yok» (geniş blade'in ikinci yuvası da olabilir) gösterir; yuva sayısı bilinmiyorsa (Dell) veya yuva sayısal değilse (`1a`, `Sled-3`) yer tutucu üretilmez. Aynı yuvada birden çok sunucu kaydı (çok düğümlü blade/sled) tek hücrede gruplanır (OneView/OME'de böyle bir kaydın alan biçimi sahada DOĞRULANMADI).

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

## Faz 3b — Redfish (iLO / iDRAC) ve in-band ipmitool

> **Durum: DOĞRULANMADI (sahada).** Bu ortamda gerçek iLO/iDRAC ve fiziksel Linux sunucu YOK; ayrıştırıcılar DMTF Redfish şemasına ve `ipmitool` çıktı biçimine göre yazıldı, **sahte (mock) yanıtlarla** test edildi. Üretici yolları (iDRAC `…/LogServices/Sel|Lclog`, iLO `…/LogServices/IML|IEL`) HAFIZADAN anılır; istemci yolları sabitlemez, kökten bağlantı izler. İH sırasında gerçek BMC çıktısı bu kayda eklenecek.

### Redfish (DMTF) — yalnız GET

Doküman: **DMTF Redfish Specification (DSP0266)** ve **LogService / LogEntry şeması (DSP2046 kaynak şeması)**; üretici kılavuzları: Dell iDRAC9 Redfish API Guide, HPE iLO 5 Redfish API Reference (yollar/yetkiler **doğrulanmadı**).

| ürün | endpoint / alan | anlamı | rol | doküman | sahada |
|---|---|---|---|---|---|
| Redfish | `GET /redfish/v1/` → `RedfishVersion`, `Vendor`, `Managers`, `Systems` | servis kökü (kimliksiz; yanlış kimlik başlığı gönderilmez) | — | DSP0266 | Hayır |
| Redfish | `GET /redfish/v1/Managers`, `GET /redfish/v1/Systems` (+ `/{id}`) | yönetici/sistem koleksiyonu ve üyesi; **ilk KİMLİKLİ istek `Managers`** | Salt-okunur (ReadOnly/Operator değil «Viewer») | DSP0266 | Hayır |
| Redfish | `GET …/{Managers\|Systems}/{id}/LogServices` ve `…/LogServices/{svc}` | log servisleri (SEL, IML, IEL, Lclog…) | ReadOnly | DSP2046 | Hayır |
| Redfish | `GET …/LogServices/{svc}/Entries` (+ `/{id}`; `Members@odata.count`, `Members@odata.nextLink`, `?$skip=`) | log kayıtları: `Created`, `Severity` (OK/Warning/Critical), `Message`, `EntryCode`, `Id` | ReadOnly | DSP2046 | Hayır |

**YASAK (kodda reddedilir, test):** `…/Actions/*` (Reset, ClearLog, SubmitTestEvent…), `SessionService/Sessions` (oturum POST'u — Basic auth kullanılır), `AccountService`, her türlü POST/PUT/PATCH/DELETE.

Doğrulanmadı: `$skip`/`$top` desteği (iLO/iDRAC sürümüne göre; desteklenmezse ilk sayfalarla yetinilir), iLO 4 / iDRAC 8 eski sürümlerin Redfish kapsamı, `Members` yalnız bağlantı döndüğünde tek tek okuma üst sınırı (50), iLO 3 (Redfish YOK → «desteklenmiyor»).

### ipmitool (in-band; SSH ile; yalnız okuma)

Doküman: `ipmitool(1)` man sayfası (alt komutlar `mc info`, `sel elist`, `sel time get`, `lan print <kanal>`).

| komut | anlamı | çıktı alanları | sahada |
|---|---|---|---|
| `ipmitool mc info` | BMC/üretici | `Manufacturer Name` | Hayır |
| `ipmitool sel time get` | BMC saati | `MM/DD/YYYY HH:MM:SS` | Hayır |
| `ipmitool sel elist` | SEL kayıtları | `ID \| MM/DD/YYYY \| HH:MM:SS \| Sensör \| Olay \| Asserted/Deasserted` (Pre-Init kayıtlar atlanır) | Hayır |
| `ipmitool lan print <1-8>` | BMC IP | `IP Address`, `IP Address Source` | Hayır |

**YASAK:** `sel clear`, `sel delete`, `chassis power`, `mc reset`, `raw`, `user`, `lan set`, paket kurulumu, `modprobe`. Root değilse `sudo -n` (parola SORULMAZ).

Doğrulanmadı: kanal numarası (1/2/3, üreticiye göre), `sel elist` sütun sayısı (bazı sürümlerde 5), BMC saatinin saat dilimi (UTC mi yerel mi) — saat sapması sezgisi (`clock_offset`) saha çıktısıyla ayarlanmalı.
