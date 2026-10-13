<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/UC_OTYP.html
Erişim tarihi: 2026-10-10
Sürüm: Automic Automation / Reference Guides 24.4

# UC_OTYP - object types

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| OTYP_Type | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | false | object type (JOBS, JOBP....) |
| OTYP_Text | varchar (80) | VARCHAR2 (80 CHAR) | varchar(80) | varchar (80) | true | description |
| OTYP_Type1 | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | abbreviation |
| OTYP_Children | varchar (255) | VARCHAR2 (255 CHAR) | varchar(255) | varchar (255) | true | child tables |
| OTYP_Executable | smallint | NUMBER(38,0) | smallint | smallint | true | Executable object |
| OTYP_Caption | int | NUMBER(38,0) | int | int | true | caption (message nr.) |
| OTYP_Sort | smallint | NUMBER(38,0) | smallint | smallint | true | displayed sort order |
| OTYP_EH_Children | varchar (255) | VARCHAR2 (255 CHAR) | varchar(255) | varchar (255) | true | EH child tables |
| OTYP_Transportable | smallint | NUMBER(38,0) | smallint | smallint | true | 1 = exportable,  0 = non-exportable |

| Name | Fields | Primary | Unique | Clustered | Nonclustered |
| --- | --- | --- | --- | --- | --- |
| PK_OTYP | OTYP_Type | true | true | true | false |

| Name | Local References | Foreign References |
| --- | --- | --- |