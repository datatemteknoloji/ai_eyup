<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/OHAA.html
Erişim tarihi: 2026-10-12
Sürüm: Automic Automation / Reference Guides 24.4

# OHAA - client allocation

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| OHAA_OH_Idnr | int | NUMBER(38,0) | int | int | false | ID of the agent authorization object. |
| OHAA_Client | smallint | NUMBER(38,0) | smallint | smallint | false | Client for which this authorizations are for. |
| OHAA_Use | smallint | NUMBER(38,0) | smallint | smallint | true | Has authorization to use. |
| OHAA_Read | smallint | NUMBER(38,0) | smallint | smallint | true | Has authorization to read. |
| OHAA_Write | smallint | NUMBER(38,0) | smallint | smallint | true | Has authorization to write. |
| OHAA_Execute | smallint | NUMBER(38,0) | smallint | smallint | true | Has authorization to execute. |

### Indexes

| Name | Fields | Primary | Unique |
| --- | --- | --- | --- |
| PK_OHAA | OHAA_OH_Idnr, OHAA_Client | true | true |

### Foreign Keys

| Name | Local | Foreign |
| --- | --- | --- |
| FK_OHAA_OH | OHAA_OH_Idnr | OH_Idnr |
