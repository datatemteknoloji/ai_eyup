# Automic source DB — DBA SELECT grant list (24.4)

Ainew connects to the Automic source database with **SELECT only**. The source type
(primary / standby / replica) is not assumed; the connection is provided at setup.

Source: `backend/app/services/automic/source/sql/official/ae-24.4-columns.yaml`.

## Service user

- Dedicated read-only user; do not use schema owner / `master` / `uc4` / `system` / `sys`.
- Sessions use `SET TRANSACTION READ ONLY` and a central SQL guard.

## AE schema tables (SELECT)

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

## Oracle dynamic performance views

```sql
GRANT SELECT ON SYS.V_$DATABASE TO <AINNEW_RO_USER>;
-- Optional apply lag
GRANT SELECT ON SYS.V_$DATAGUARD_STATS TO <AINNEW_RO_USER>;

-- Plan check tool: probe SELECT then read V$SQL_PLAN (no EXPLAIN PLAN / PLAN_TABLE / DBMS_XPLAN)
GRANT SELECT ON SYS.V_$SESSION TO <AINNEW_RO_USER>;
GRANT SELECT ON SYS.V_$SQL TO <AINNEW_RO_USER>;
GRANT SELECT ON SYS.V_$SQL_PLAN TO <AINNEW_RO_USER>;
```

## Hard constraints (DBA)

Grant **SELECT only** on the tables/views listed above.

- **No EXECUTE** on any package, function, or procedure (`EXECUTE` / `EXECUTE ANY`, including DBMS_XPLAN).
- **No DB links** (`CREATE DATABASE LINK` / remote DB privileges).
- **No ANY privileges** (`SELECT ANY TABLE`, `SELECT ANY DICTIONARY`, `INSERT/UPDATE/DELETE/ALTER/DROP/CREATE ANY`, …).
- **No write / DDL / EXPLAIN PLAN**.
- Do not grant `SELECT_CATALOG_ROLE` or DBA; prefer object-level `GRANT SELECT` only.
