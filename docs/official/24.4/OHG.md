<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/OHG.html
Erişim tarihi: 2026-10-12
Sürüm: Automic Automation / Reference Guides 24.4

# OHG - agent group attributes

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| OHG_OH_Idnr | int | NUMBER(38,0) | int | int | false | ID of the agent group. |
| OHG_HostAttrType | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | false | Platform the selected agents run on. |
| OHG_Mode | char (1) | CHAR (1 CHAR) | char(1) | char (1) | false | Mode of the agent group. A = any, F = first, N = next, L = load dependent, X = all |
| OHG_MaxParallel | smallint | NUMBER(38,0) | smallint | smallint | true | Tasks that are allowed to be parallel in mode X (all) |
| OHG_Enforced | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates whether or not a task can be activated using agents that are currently not active in mode X (all). |
| OHG_NextCnt | int | NUMBER(38,0) | int | int | true | Current position within the agent group in mode N (next). |
| OHG_CITName | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Name of the selected RA solution. |

### Indexes

| Name | Fields | Primary | Unique |
| --- | --- | --- | --- |
| PK_OHG | OHG_OH_Idnr | true | true |

### Foreign Keys

| Name | Local | Foreign |
| --- | --- | --- |
| FK_OHG_OH | OHG_OH_Idnr | OH_Idnr |
