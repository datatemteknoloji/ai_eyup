<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/HOST.html
Erişim tarihi: 2026-10-12
Sürüm: Automic Automation / Reference Guides 24.4

# HOST - host definition

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| HOST_OH_Idnr | int | NUMBER(38,0) | int | int | false | Primary Key |
| HOST_HTYP_HW | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | hardware |
| HOST_HTYP_SW | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | software |
| HOST_HTYP_SWVers | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | version |
| HOST_CodeName | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | name of code table |
| HOST_JCLVar | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | type of the job control language |
| HOST_HostAttrType | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | attribute type corresponding to table UC_HTYP |
| HOST_TcpIpAddr | varchar (64) | VARCHAR2 (64 CHAR) | varchar(64) | varchar (64) | true | TCP/IP address |
| HOST_TcpIpPort | int | NUMBER(38,0) | int | int | true | TCP/IP port number |
| HOST_Active | smallint | NUMBER(38,0) | smallint | smallint | true | PEER active = 1 |
| HOST_JobCnt | int | NUMBER(38,0) | int | int | true | Aktual running jobs |
| HOST_MaxWaiting | smallint | NUMBER(38,0) | smallint | smallint | true | 1=jobs are waiting because of max parallel limit |
| HOST_Daylight | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | is actual time day light saving time? |
| HOST_LicenceClass | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | licence class |
| HOST_Version | varchar (270) | VARCHAR2 (270 CHAR) | varchar(270) | varchar (270) | true | Executor Version |
| HOST_JobMd | varchar (1024) | VARCHAR2 (1024 CHAR) | varchar(1024) | varchar (1024) | true | Job messenger |
| HOST_PathBin | varchar (1024) | VARCHAR2 (1024 CHAR) | varchar(1024) | varchar (1024) | true | Installation path |
| HOST_PathJobReport | varchar (1024) | VARCHAR2 (1024 CHAR) | varchar(1024) | varchar (1024) | true | Jobreport path |
| HOST_PathTemp | varchar (1024) | VARCHAR2 (1024 CHAR) | varchar(1024) | varchar (1024) | true | Temp path |
| HOST_ProcessName | varchar (255) | VARCHAR2 (255 CHAR) | varchar(255) | varchar (255) | true | Process Name (nsk executor) |
| HOST_VolumeTemp | varchar (255) | VARCHAR2 (255 CHAR) | varchar(255) | varchar (255) | true | Temp volume |
| HOST_ProcessMask | varchar (255) | VARCHAR2 (255 CHAR) | varchar(255) | varchar (255) | true | Mask f. PrepProcess |
| HOST_LoginMask | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | login description mask |
| HOST_MibMonitoring | smallint | NUMBER(38,0) | smallint | smallint | true | Flag f. MIB |
| HOST_MibInfo | varchar (255) | VARCHAR2 (255 CHAR) | varchar(255) | varchar (255) | true | Info f. MIB |
| HOST_LicCategory | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | Licence Category |
| HOST_MaxWaitingFT | smallint | NUMBER(38,0) | smallint | smallint | true | 1=filtransfers are waiting because of max_parallel_ft limit |
| HOST_FTCount | int | NUMBER(38,0) | int | int | true | Actual running FT |
| HOST_HostRoles | varchar(256) | VARCHAR2 (256 CHAR) | varchar(256) | varchar(256) | true | Role of host (from INI or edited in object) |
| HOST_MaxResJob | int | NUMBER(38,0) | int | int | true | Maximum number of available job resources (0-100000, -1 = Unlimited) |
| HOST_MaxResFT | int | NUMBER(38,0) | int | int | true | Maximum number of available ft resources (0-100000, -1 = Unlimited) |
| HOST_Authenticated | smallint | NUMBER(38,0) | smallint | smallint | true | Is Executor already authenticated (0=no, 1=yes) |
| HOST_CPName | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | A host that is not authenticated is connected with this CP |
| HOST_CITName | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Name of the CIT solution the host is associated with |
| HOST_TrustedIPs | varchar(256) | VARCHAR2 (256 CHAR) | varchar(256) | varchar(256) | true | List of IP addresses where non encrypted connections are allowed (separated via semicolons) |
| HOST_CITCN | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | Vendor of the Solution determined from Deploytool. Either 'UC4' or '3DPTY' |
| HOST_CITOU | varchar (64) | VARCHAR2 (64 CHAR) | varchar(64) | varchar (64) | true | Oranizational Unit Name of the certificate |
| HOST_SmPhrase | varchar (16) | VARCHAR2 (16 CHAR) | varchar(16) | varchar (16) | true | ServiceManager Phrase Name |
| HOST_SmTcpIpPort | int | NUMBER(38,0) | int | int | true | ServiceManager Tcp/Ip Port Number |
| HOST_SmDisplayName | varchar (64) | VARCHAR2 (64 CHAR) | varchar(64) | varchar (64) | true | Service Manager Dialog Display Name |
| HOST_SmLookupFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Flag for SmgrLookup to avoid lookup for any startup of an agent (0: no lookup, 1: lookup done) |
| HOST_SmLinkFlag | smallint | NUMBER(38,0) | smallint | smallint | true | For GUI-purposes: Service is linked to Service Manager(0: no, 1: yes) |
| HOST_HostName | varchar (256) | VARCHAR2 (256 CHAR) | varchar(256) | varchar (256) | true | Hostname of CP/WP-Processes |
| HOST_NetArea | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | The NetArea in which this Agent runs |
| HOST_PathBackup | varchar (1024) | VARCHAR2 (1024 CHAR) | varchar(1024) | varchar (1024) | true | Backup path |
| HOST_PathCache | varchar (1024) | VARCHAR2 (1024 CHAR) | varchar(1024) | varchar (1024) | true | Cache path |
| HOST_TargetVersion | varchar (270) | VARCHAR2 (270 CHAR) | varchar(270) | varchar (270) | true | The target version of CAU |
| HOST_UpgradeRunId | int | NUMBER(38,0) | int | int | true | AH_Idnr of agent upgrade (report) |
| HOST_Tls | smallint | NUMBER(38,0) | smallint | smallint | true | Support of the TLS protocol. Allowed values 1/0 |
| HOST_Gateway | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | Gateway name |
| HOST_Unicode | smallint | NUMBER(38,0) | smallint | smallint | true | Support of unicode. Allowed values 1/0 |

### Indexes

| Name | Fields | Primary | Unique |
| --- | --- | --- | --- |
| PK_HOST | HOST_OH_Idnr | true | true |
| NK_HOST_Ip_AttrType | HOST_TcpIpAddr, HOST_HostAttrType | false | false |

### Foreign Keys

| Name | Local | Foreign |
| --- | --- | --- |
| FK_HOST_OH | HOST_OH_Idnr | OH_Idnr |
