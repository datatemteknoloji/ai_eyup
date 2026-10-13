# Automic AE durum kodları, rapor tipleri ve metrikler

Kaynak ayrımı (2026-10-10):
- **24.4 resmi (DB Schema):** ERT/MRT/SRT/Signal/MrtMethod/DeleteFlag — `docs/official/24.4/AH.md|EH.md|OH.md`, `ae-24.4-columns.yaml`.
- **DOĞRULANMADI – gerçek veriyle kontrol edilecek:** durum kodu grupları, RH_Type değer listesi, nesne tipi kısaltma listesi. 24.4 TechDocs'ta "System Return Codes of Executable Objects" / "Task Status" sayfaları **bulunamadı** (`docs/official/24.4/STATUS_CODES_SEARCH.md`).

Sayı/RunID uydurma; canlı veri için `automic_*` araçlarını kullan.

## Durum kodu aileleri (AH_Status / EH_Status) — DOĞRULANMADI
Aşağıdaki aralıklar/listeler ainew'de kullanılan çalışma varsayımlarıdır; 24.4 resmi guide ile satır satır doğrulanmamıştır.
- **1300–1799** (çalışma varsayımı ANY_ACTIVE): görev hâlâ işleniyor olabilir.
- **1800–1899** (çalışma varsayımı ANY_ABEND): anormal bitiş ailesi. **1900–1999** (çalışma varsayımı ANY_OK): normal bitiş ailesi.
- Süreç İzleme grup listeleri (DOĞRULANMADI — `classify.ACTIVE_STATUS_GROUPS` / RAG eski derleme):
  - **ABEND**: 1800–1802, 1810, 1815, 1820–1830, 1850–1854, 1856, 1860
  - **BLOCKED**: 1544, 1547, 1560–1564, 1898
  - **WAITING**: 1301, 1543, 1552, 1553, 1556, 1655, 1665, 1681–1700, 1702, 1703, 1709–1711
  - **ACTIVE**: 1300, 1310, 1540–1542, 1545, 1546, 1550, 1551, 1554, 1557, 1558, 1565–1576, 1578–1584, 1590–1593, 1600, 1701, 1704, 1705
  - **ENDED OK**: 1900–1905, 1910–1913, 1919–1925, 1930–1933, 1940–1942, 1944, 1960, 1970, 1999
- Sık kod isimleri (DOĞRULANMADI): 1550, 1560, 1700, 1800, 1801, 1802, 1810, **1850**, **1851**, **1900**, …
- **ainew sınıfları** (ürün ayarı, resmi guide değil): `failed` = 1800–1899 (1850/1851 hariç), `cancelled` = 1850, 1851, `ok` = 1900–1999, `active` = EH. Sınıfı **araç sonucundaki `status_class`** belirler.
- Aktif `state` (`running`/`waiting`/`blocked`): ainew `classify.active_state` — DOĞRULANMADI.

## Dönüş kodu (AH_RetCode) — kısmen 24.4
- `AH_RetCode` = return code (`AH.md`). `AH_MaxRetCode` / `OH_MaxRetCode`: şemada "up to this retcode the activity is ENDED_OK" (`AH.md` / `OH.md`).
- Sistem durum kodu (`AH_Status`) ile uygulama dönüş kodunu (`AH_RetCode`) karıştırma.

## Süre ve tahmin metrikleri — 24.4 resmi (EH/OH/AH)
- **Runtime**: `AH_RunTime` / `EH_RunTime` (Runtime in Seconds).
- **ERT**: `OH_Ert` / `AH_ERT` / `EH_Ert` (Estimated Runtime); `EH_ERTEnd`; `EH_ERTCalc` (0/1/2/3 — `EH.md` birebir).
- **MRT**: `EH_Mrt` (maximum running time in seconds); `EH_MrtMethod` bitmask (`EH.md`).
- **SRT**: `EH_Srt` — şemadaki tanım: **SRT in Seconds** ( "minimum" deme ). `EH_SrtErt` = SRT=ERT+xx%.
- **Sinyaller** (`EH_Signal`, resmi): 1 = TCP exceeded, 2 = MRT exceeded, 4 = SRT not reached. Açılım uydurma.
- **ainew metrikleri** (AE resmi değil): `p95`, `over_p95`, `over_ert`, `duration_sec` (`AH_TimeStamp2`→`AH_TimeStamp4`).

## Rapor tipleri (RH_Type) — DOĞRULANMADI
`RH_Type` / `RT_Type` UC_RTYP'e referans verir (`RH.md`, `UC_RTYP.md` yalnız şema). ACT/REP/LOG… değer listesi 24.4 guide'da bulunamadı → gerçek DB `UC_RTYP` ile kontrol edilecek.
Çalışma notu (doğrulanmamış): job için sık REP, diğerleri için ACT; `RT_Content` boşken `RT_MsgNr`+`RT_MsgInsert` (şema: Content = memostype if MSGNR not present).

## Nesne tipleri (OH_OType) — DOĞRULANMADI
`UC_OTYP.md` yalnız şema; tam kısaltma listesi 24.4 guide'da bulunamadı → gerçek DB `UC_OTYP` ile kontrol edilecek.
Çalışma notu (doğrulanmamış örnekler): JOBS, JOBP, JSCH, EVNT, JOBF, SCRI, USER, HOST, QUEUE, FOLD, …

## Restart / silinen nesneler
- Restart: `AH_Restart` / `AH_RefNr` (şema alanları). Zincir: `automic_execution(aspect="restarts")`.
- `OH_DeleteFlag` (24.4 resmi): 0 not deleted · 1 deleted · 2 versioned · 5 archived/reorganized. ainew başlıklarda `= 0` okur.
