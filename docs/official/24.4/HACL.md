<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/HACL.html
Erişim tarihi: 2026-10-12
Sürüm: Automic Automation / Reference Guides 24.4

# HACL - host authorizations

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| HACL_OH_Idnr | int | NUMBER(38,0) | int | int | false | ID of the user (group) object. |
| HACL_Client | smallint | NUMBER(38,0) | smallint | smallint | false | The client for which this agent authorizations are valid for. |
| HACL_Read | smallint | NUMBER(38,0) | smallint | smallint | true | Determines whether read authorizations are set or not. |
| HACL_Write | smallint | NUMBER(38,0) | smallint | smallint | true | Determines whether write authorizations are set or not. |
| HACL_Execute | smallint | NUMBER(38,0) | smallint | smallint | true | Determines whether execute authorizations are set or not. |

### Indexes

| Name | Fields | Primary | Unique |
| --- | --- | --- | --- |
| PK_HACL | HACL_OH_Idnr, HACL_Client | true | true |

### Foreign Keys

| Name | Local | Foreign |
| --- | --- | --- |
| FK_HACL_OH | HACL_OH_Idnr | OH_Idnr |
