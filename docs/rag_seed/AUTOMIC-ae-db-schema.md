# Automic AE veritabanı şeması (24.4 resmi) — ainew referansı

Kaynak: Broadcom TechDocs **Automic DB Schema** (24.4) —
yerel kopya `docs/official/24.4/<TABLO>.md` (erişim 2026-10-10);
URL `…/automic-reference-guides/24-4/automic-db-schema/<TABLO>.html`.
SELECT edilen kolonlar: `backend/.../sql/official/ae-24.4-columns.yaml`.
Canlı sayı/RunID için `automic_*` araçlarını kullan; buradan sayı uydurma.

## Genel kurallar
- Zaman damgaları: `AH_TimeStamp1` = activation time, `AH_TimeStamp2` = start time, `AH_TimeStamp3` = end before post processing, `AH_TimeStamp4` = end including post processing (`docs/official/24.4/AH.md`).
- Her aktivasyonun **RunID**'si `AH_Idnr`'dir. Biten kayıtlar **AH**'dadır; şu an çalışan/bekleyen **EH**'dadır.
- Nesne tanımı **OH**'dadır (`OH_Idnr`). ainew AE'ye **yazmaz**; `USR_Pw*` / hash alanları asla seçilmez.

## Çekirdek tablolar (SELECT edilen alanlar)

### AH — archive header (`docs/official/24.4/AH.md`)
- Kimlik: `AH_Idnr` (primary key), `AH_Client`, `AH_Name`, `AH_OType`, `AH_OH_Idnr` (processed IDNR).
- Durum: `AH_Status` (state of the activity), `AH_RetCode` (return code).
- Zaman: `AH_TimeStamp1`/`2`/`4` (yukarıda); `AH_TimeStamp3` SELECT edilmez ama şemada tanımlıdır.
- Süre: `AH_RunTime` (Runtime in Seconds), `AH_ERT` (Estimated Runtime).
- Ağaç/yer: `AH_ParentAct` (activator parent), `AH_TopNr`, `AH_RefNr` (reference job number), `AH_USR_Idnr` (user that executed), `AH_HostDst` (host or hostgroup), `AH_HostAttrTypeD` (destination host attribute type), `AH_Queue`.

### EH — executive header (`docs/official/24.4/EH.md`)
- `EH_AH_Idnr`, `EH_Client`, `EH_Name`, `EH_OType`, `EH_OH_Idnr`, `EH_Status`, `EH_USR_Idnr`, `EH_HostDst`, `EH_HostAttrType`, `EH_Queue`, `EH_ParentAct`, `EH_TopNr`.
- Zaman: `EH_ActivationTime` (= AH_Timestamp1), `EH_StartTime`, `EH_RunTime` (Runtime in Seconds).
- Süre denetimi: `EH_Ert` (Estimated Runtime), `EH_ERTEnd` (Estimated end of the Task), `EH_ERTCalc` (0=no ERT, 1=active, 2=succeeded, 3=failed), `EH_Mrt` (maximum running time in seconds), **`EH_Srt`** (şemadaki tanım: **SRT in Seconds** — "minimum" ifadesi kullanma), `EH_Signal` (1=TCP exceeded, 2=MRT exceeded, 4=SRT not reached). TCP/SRT açılımı şemada yok; uydurma.

### OH — object header (`docs/official/24.4/OH.md`)
- `OH_Idnr`, `OH_Client`, `OH_OType`, `OH_Name`, `OH_Title`, `OH_CrUserIdnr`/`OH_CrDate`, `OH_ModUserIdnr`/`OH_ModDate`, `OH_Ert`.
- **`OH_DeleteFlag`** (24.4 resmi): 0 = not deleted, 1 = deleted, 2 = versioned, 5 = archived/reorganized. Güncel nesne: `OH_DeleteFlag = 0`.

### OFS — folder (`docs/official/24.4/OFS.md`)
`OFS_OH_Idnr_O` (object), `OFS_OH_Idnr_F` (folder), **`OFS_Link`**: 0 = Home Folder, 1 = Linked Object (24.4 resmi; tahmin değil).

### OT — object text (`docs/official/24.4/OT.md`)
`OT_OH_Idnr`, `OT_Type` (0 = process, 1 = pre-process, 2 = post-process, 3 = inherit post process), `OT_Lnr`, `OT_Content`.

### JPP — jobplan process (`docs/official/24.4/JPP.md`)
`JPP_OH_Idnr`, `JPP_Lnr`, `JPP_Object` (Name of the workflow task), `JPP_OType`.

### RH / RT (`docs/official/24.4/RH.md`, `RT.md`)
- RH: `RH_AH_Idnr`, `RH_Type` (reference to UC_RTYP), `RH_Client`.
- RT: `RT_AH_Idnr`, `RT_Type`, `RT_Lnr`, `RT_Content` (memostype text if MSGNR is not present), `RT_MsgNr` (if logging record), `RT_MsgInsert`.

## ainew kullanımı
| Gösterilen | 24.4 kaynak |
|---|---|
| Kullanıcı | `AH_USR_Idnr`/`EH_USR_Idnr` → `OH_Name` (USER) |
| Klasör | `OFS_Link = 0` (Home Folder) → `OH_Name` |
| Kuyruk / platform / agent | `AH_Queue`/`EH_Queue`, `AH_HostAttrTypeD`/`EH_HostAttrType`, `AH_HostDst`/`EH_HostDst` |
| AE ERT | `AH_ERT`/`EH_Ert`/`OH_Ert`, bitiş `EH_ERTEnd` |

HOST/ACTEX/USR ainew tarafından SELECT edilmez (parola/agent bağlantı alanı toplanmaz).
