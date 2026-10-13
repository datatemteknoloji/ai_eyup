<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/OFS.html
Erişim tarihi: 2026-10-10
Sürüm: Automic Automation / Reference Guides 24.4

# OFS - folder

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| OFS_Idnr | int | NUMBER(38,0) | int | int | false | primary key of the folder link |
| OFS_OH_Idnr_F | int | NUMBER(38,0) | int | int | false | OH_IDNR of the folder |
| OFS_Level | int | NUMBER(38,0) | int | int | false | hierarchy |
| OFS_OH_Idnr_O | int | NUMBER(38,0) | int | int | false | OH_IDNR of the object |
| OFS_Link | smallint | NUMBER(38,0) | smallint | smallint | true | Links: 0 = Home Folder, 1 = Linked Object |
| OFS_ModDate | datetime | DATE | timestamp | timestamp | true | creation/modification date; required for tracking changes and enabling the Lucene search indexer |

| Name | Fields | Primary | Unique | Clustered | Nonclustered |
| --- | --- | --- | --- | --- | --- |
| NK_OFS_F | OFS_OH_Idnr_F | false | false | false | false |
| NK_OFS_O | OFS_OH_Idnr_O | false | false | false | false |
| PK_OFS | OFS_Idnr | true | true | true | false |
| NK_OFS_ModDate | OFS_ModDate, OFS_OH_Idnr_F, OFS_OH_Idnr_O | false | false | false | false |

| Name | Local References | Foreign References |
| --- | --- | --- |
| FK_OFS_OH_O | OFS_OH_Idnr_O | OH_Idnr |
| FK_OFS_OH_F | OFS_OH_Idnr_F | OH_Idnr |