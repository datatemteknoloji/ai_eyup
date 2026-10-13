# Automic kaynak DB — DBA SELECT yetki listesi (24.4)

Ainew, Automic kaynak veritabanına **yalnızca SELECT** ile bağlanır. Kaynak türü
(primary / standby / kopya) varsayılmaz; bağlantı kurulumda kullanıcı tarafından verilir.

Kaynak: `backend/app/services/automic/source/sql/official/ae-24.4-columns.yaml`
(kodda gerçekten SELECT edilen kolonlar). Yerel şema özeti: `docs/official/24.4/`.

## Servis kullanıcısı

- Ayrı salt okunur kullanıcı (ör. `AINNEW_AUTOMIC_RO`); şema sahibi / `master` / `uc4` / `system` / `sys` kullanmayın.
- Uygulama oturumunda `SET TRANSACTION READ ONLY` ve merkezi SQL guard uygulanır.

## AE şema tabloları (SELECT)

`<AE_SCHEMA>` yerine kurumdaki Automic şema sahibini yazın (ör. `UC4`).

```sql
-- AH: AH_Client, AH_ERT, AH_HostAttrTypeD, AH_HostDst, AH_Idnr, AH_Name, AH_OH_Idnr, AH_OType, AH_ParentAct, AH_Queue, AH_RefNr, AH_RetCode, AH_RunTime, AH_Status, AH_TimeStamp1, AH_TimeStamp2, AH_TimeStamp4, AH_TopNr, AH_USR_Idnr
GRANT SELECT ON <AE_SCHEMA>.AH TO <AINNEW_RO_USER>;

-- EH: EH_AH_Idnr, EH_ActivationTime, EH_Client, EH_ERTCalc, EH_ERTEnd, EH_Ert, EH_HostAttrType, EH_HostDst, EH_Mrt, EH_Name, EH_OH_Idnr, EH_OType, EH_ParentAct, EH_Queue, EH_RunTime, EH_Signal, EH_Srt, EH_StartTime, EH_Status, EH_TopNr, EH_USR_Idnr
GRANT SELECT ON <AE_SCHEMA>.EH TO <AINNEW_RO_USER>;

-- JPP: JPP_Lnr, JPP_OH_Idnr, JPP_OType, JPP_Object
GRANT SELECT ON <AE_SCHEMA>.JPP TO <AINNEW_RO_USER>;

-- OFS: OFS_Link, OFS_OH_Idnr_F, OFS_OH_Idnr_O
GRANT SELECT ON <AE_SCHEMA>.OFS TO <AINNEW_RO_USER>;

-- OH: OH_Client, OH_CrDate, OH_CrUserIdnr, OH_DeleteFlag, OH_Ert, OH_Idnr, OH_ModDate, OH_ModUserIdnr, OH_Name, OH_OType, OH_Title
GRANT SELECT ON <AE_SCHEMA>.OH TO <AINNEW_RO_USER>;

-- OT: OT_Content, OT_Lnr, OT_OH_Idnr, OT_Type
GRANT SELECT ON <AE_SCHEMA>.OT TO <AINNEW_RO_USER>;

-- RH: RH_AH_Idnr, RH_Client, RH_Type
GRANT SELECT ON <AE_SCHEMA>.RH TO <AINNEW_RO_USER>;

-- RT: RT_AH_Idnr, RT_Content, RT_Lnr, RT_MsgInsert, RT_MsgNr, RT_Type
GRANT SELECT ON <AE_SCHEMA>.RT TO <AINNEW_RO_USER>;

```

## Oracle dinamik performans görünümleri

```sql
-- Rol / open mode (kurulum testi + periyodik bilgilendirme; zorunlu değil — okunamazsa "bilinmiyor")
GRANT SELECT ON SYS.V_$DATABASE TO <AINNEW_RO_USER>;

-- Opsiyonel: Data Guard apply lag (yetki yoksa veya kaynak standby değilse sessizce atlanır)
GRANT SELECT ON SYS.V_$DATAGUARD_STATS TO <AINNEW_RO_USER>;

-- Plan kontrol aracı (ainew): şablon SELECT sonrası V$SQL_PLAN okuma
-- EXPLAIN PLAN / PLAN_TABLE / DBMS_XPLAN kullanılmaz (yazma yok).
GRANT SELECT ON SYS.V_$SESSION TO <AINNEW_RO_USER>;
GRANT SELECT ON SYS.V_$SQL TO <AINNEW_RO_USER>;
GRANT SELECT ON SYS.V_$SQL_PLAN TO <AINNEW_RO_USER>;
```

## Zorunlu kısıtlar (DBA)

Kullanıcıya **yalnızca yukarıda listelenen tablolarda / görünümlerde SELECT** verilir.

- **EXECUTE yok:** hiçbir paket, fonksiyon veya prosedürde `EXECUTE` / `EXECUTE ANY` verilmez (DBMS_XPLAN dahil).
- **DB link yok:** `CREATE DATABASE LINK` / uzak DB yetkisi verilmez.
- **ANY yetkisi yok:** `SELECT ANY TABLE`, `SELECT ANY DICTIONARY`, `INSERT ANY`, `UPDATE ANY`, `DELETE ANY`, `ALTER ANY`, `DROP ANY`, `CREATE ANY` vb. verilmez.
- **Yazma yok:** `INSERT` / `UPDATE` / `DELETE` / `MERGE` / DDL / `EXPLAIN PLAN` yetkisi verilmez.
- `SELECT_CATALOG_ROLE` veya DBA rolü vermeyin; mümkünse yalnızca yukarıdaki nesne bazlı `GRANT SELECT`.

## Notlar

- `V_$DATABASE` / `V_$DATAGUARD_STATS` / `V_$SESSION` / `V_$SQL` / `V_$SQL_PLAN` için `SYS` üzerinden grant; tablo bazlı grant tercih edilir.
- Keşif sırasında `ALL_TAB_COLUMNS` / `SESSION_PRIVS` okunur (standart kullanıcı yetkileri yeterli).
- Plan aracı: `python -m app.services.automic.explain_plans --system-id N` — tüm SQL `sql_guard` + `SET TRANSACTION READ ONLY` altındadır.

İngilizce kopya: aynı içerik `docs/guides/en/modules/automic-source-dba-grants.md`.
