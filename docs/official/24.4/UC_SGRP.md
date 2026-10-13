<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/UC_SGRP.html
Erişim tarihi: 2026-10-10
Sürüm: Automic Automation / Reference Guides 24.4

# UC_SGRP - Status Groups

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| SGRP_Group | varchar (16) | VARCHAR2 (16 CHAR) | varchar(16) | varchar (16) | false | Status group |
| SGRP_MainRange | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | false | Main number range of status group |
| SGRP_SubRanges | varchar(1024) | VARCHAR2 (1024 CHAR) | varchar(1024) | varchar(1024) | true | Sub number ranges + single numbers |
| SGRP_ExcludeForTL | varchar(512) | VARCHAR2 (512 CHAR) | varchar(512) | varchar(512) | true | Numbers excluded for trafic lights e.g. 1700 in waiting blue |

| Name | Fields | Primary | Unique | Clustered | Nonclustered |
| --- | --- | --- | --- | --- | --- |
| PK_SGRP | SGRP_Group, SGRP_MainRange | true | true | false | false |

| Name | Local References | Foreign References |
| --- | --- | --- |