<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/UC_RTYP.html
Erişim tarihi: 2026-10-10
Sürüm: Automic Automation / Reference Guides 24.4

# UC_RTYP - report types

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| RTYP_Type | varchar (4) | VARCHAR2 (4 CHAR) | varchar(4) | varchar (4) | false | type of the report |
| RTYP_Text | varchar (50) | VARCHAR2 (50 CHAR) | varchar(50) | varchar (50) | true | description |
| RTYP_Caption | int | NUMBER(38,0) | int | int | true | ZUHELP key for headline (caption) |
| RTYP_Flag | smallint | NUMBER(38,0) | smallint | smallint | true | 0= standard report, 1=dynamic report (caption in rh_title) |
| RTYP_StartType | smallint | NUMBER(38,0) | smallint | smallint | true | 0=start reports at end of job; 1=start reports at job start |

| Name | Fields | Primary | Unique | Clustered | Nonclustered |
| --- | --- | --- | --- | --- | --- |
| PK_RTYP | RTYP_Type | true | true | true | false |

| Name | Local References | Foreign References |
| --- | --- | --- |