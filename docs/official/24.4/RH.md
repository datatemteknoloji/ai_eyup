<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/RH.html
Erişim tarihi: 2026-10-10
Sürüm: Automic Automation / Reference Guides 24.4

# RH - report header

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| RH_Client | smallint | NUMBER(38,0) | smallint | smallint | false | client |
| RH_AH_Idnr | int | NUMBER(38,0) | int | int | false | reference to the archive header (AH) |
| RH_Type | varchar (4) | VARCHAR2 (4 CHAR) | varchar(4) | varchar (4) | false | report type (reference to type UC_RTYP) |
| RH_TimeStamp1 | datetime | DATE | timestamp | timestamp | true | timestamp of report creation (open) |
| RH_TimeStamp4 | datetime | DATE | timestamp | timestamp | true | timestamp of report close |
| RH_DeleteFlag | smallint | NUMBER(38,0) | smallint | smallint | true | delete flag |
| RH_ArchiveFlag | smallint | NUMBER(38,0) | smallint | smallint | true | archive flag |
| RH_BlkSize | int | NUMBER(38,0) | int | int | true | Bytes per block |
| RH_Title | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Alternate title of reports |
| RH_XMLFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Flag for XML Reports (0=not an XML Report, 1=XML Report) |
| RH_FileFullPath | varchar (1024) | VARCHAR2 (1024 CHAR) | varchar(1024) | varchar (1024) | true | Full path name of output file |
| RH_FileOnAgent | smallint | NUMBER(38,0) | smallint | smallint | true | Report as file available on Agent side |
| RH_FileInDB | smallint | NUMBER(38,0) | smallint | smallint | true | Report in DB available |
| RH_UsersLogin | smallint | NUMBER(38,0) | smallint | smallint | true | Require Users Login |

| Name | Fields | Primary | Unique | Clustered | Nonclustered |
| --- | --- | --- | --- | --- | --- |
| NK_RH_AH_IDNR | RH_AH_Idnr, RH_ArchiveFlag, RH_Type | false | false | false | false |
| NK_RH_Archive1 | RH_DeleteFlag, RH_ArchiveFlag, RH_Client, RH_AH_Idnr, RH_Type | false | false | false | false |
| NK_RH_Archive2 | RH_DeleteFlag, RH_AH_Idnr, RH_Type, RH_TimeStamp4, RH_ArchiveFlag | false | false | false | false |
| NK_RH_DelFlag | RH_DeleteFlag, RH_Client, RH_AH_Idnr, RH_Type | false | false | false | false |
| NK_RH_Timestamp4 | RH_AH_Idnr, RH_TimeStamp4 | false | false | false | false |
| PK_RH | RH_AH_Idnr, RH_Type | true | true | true | false |
| UK_RH_Typ | RH_Client, RH_AH_Idnr, RH_Type | false | true | false | false |

| Name | Local References | Foreign References |
| --- | --- | --- |
| FK_RH_AH | RH_AH_Idnr | AH_Idnr |