<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/OT.html
Erişim tarihi: 2026-10-10
Sürüm: Automic Automation / Reference Guides 24.4

# OT - object text

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| OT_OH_Idnr | int | NUMBER(38,0) | int | int | false | ID of the object. |
| OT_Type | smallint | NUMBER(38,0) | smallint | smallint | false | Type of the script. 0 = process, 1 = pre-process, 2 = post-process, 3 = inherit post process (child tasks) |
| OT_Lnr | smallint | NUMBER(38,0) | smallint | smallint | false | Sequenced number for the script lines. |
| OT_Content | varchar(max) | CLOB | clob(20480 k) INLINE LENGTH 30000 COMPACT | text | true | Content of the script line. |

| Name | Fields | Primary | Unique | Clustered | Nonclustered |
| --- | --- | --- | --- | --- | --- |
| PK_OT | OT_OH_Idnr, OT_Type, OT_Lnr | true | true | true | false |

| Name | Local References | Foreign References |
| --- | --- | --- |
| FK_OT_OH | OT_OH_Idnr | OH_Idnr |