<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/RT.html
Erişim tarihi: 2026-10-10
Sürüm: Automic Automation / Reference Guides 24.4

# RT - report content

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| RT_AH_Idnr | int | NUMBER(38,0) | int | int | false | reference to RH/AH |
| RT_Type | varchar (4) | VARCHAR2 (4 CHAR) | varchar(4) | varchar (4) | false | report type (reference to type UC_RTYP) |
| RT_Lnr | int | NUMBER(38,0) | int | int | false | ascending number of the report text |
| RT_TimeStamp | datetime | DATE | timestamp | timestamp | true | timestamp |
| RT_MsgNr | int | NUMBER(38,0) | int | int | false | MSGNR if this is a logging record |
| RT_Content | varchar(max) | CLOB | clob(20480 k) INLINE LENGTH 1024 COMPACT | text | true | memostype text if MSGNR is not present |
| RT_MsgInsert | varchar (1024) | VARCHAR2 (1024 CHAR) | varchar(1024) | varchar (1024) | true | MSG_Insert if this is a logging record |

| Name | Fields | Primary | Unique | Clustered | Nonclustered |
| --- | --- | --- | --- | --- | --- |
| PK_RT | RT_AH_Idnr, RT_Type, RT_Lnr | true | true | true | false |

| Name | Local References | Foreign References |
| --- | --- | --- |
| FK_RT_RH | RT_AH_Idnr, RT_Type | RH_AH_Idnr, RH_Type |