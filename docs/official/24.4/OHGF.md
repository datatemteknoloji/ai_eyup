<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/OHGF.html
Erişim tarihi: 2026-10-12
Sürüm: Automic Automation / Reference Guides 24.4

# OHGF - filter table for host group

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| OHGF_OH_Idnr | int | NUMBER(38,0) | int | int | false | ID of the agent group. |
| OHGF_Lnr | int | NUMBER(38,0) | int | int | false | Sequenced number for the filter entries. |
| OHGF_Type | char (1) | CHAR (1 CHAR) | char(1) | char (1) | false | Type of the filter. H = single agent, F = filter |
| OHGF_Name | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | Filter for the name of the agent. |
| OHGF_Version | varchar (270) | VARCHAR2 (270 CHAR) | varchar(270) | varchar (270) | true | Filter for the version of the agent. |
| OHGF_HW | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | Filter for the hardware of the host. |
| OHGF_SW | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | Filter for the software of the host. |
| OHGF_SWVers | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | Filter for the version of the software. |
| OHGF_Archive1 | varchar (512) | VARCHAR2 (512 CHAR) | varchar(512) | varchar (512) | true | Filter for the archive key #1 |
| OHGF_Archive2 | varchar (512) | VARCHAR2 (512 CHAR) | varchar(512) | varchar (512) | true | Filter for the archive key #2 |
| OHGF_HostRole | varchar(256) | VARCHAR2 (256 CHAR) | varchar(256) | varchar(256) | true | Filter for the role of the agent. |

### Indexes

| Name | Fields | Primary | Unique |
| --- | --- | --- | --- |
| PK_OHGF | OHGF_OH_Idnr, OHGF_Lnr | true | true |

### Foreign Keys

| Name | Local | Foreign |
| --- | --- | --- |
| FK_OHGF_OHG | OHGF_OH_Idnr | OHG_OH_Idnr |
