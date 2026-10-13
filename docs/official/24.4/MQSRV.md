<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/MQSRV.html
Erişim tarihi: 2026-10-12
Sürüm: Automic Automation / Reference Guides 24.4

# MQSRV - Message Queue Server

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| MQSRV_Name | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | false | server name |
| MQSRV_System | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | false | system name |
| MQSRV_TcpIpAddr | varchar (64) | VARCHAR2 (64 CHAR) | varchar(64) | varchar (64) | false | IP address |
| MQSRV_TcpIpPort | int | NUMBER(38,0) | int | int | false | IP port number |
| MQSRV_Type | int | NUMBER(38,0) | int | int | false | type (1=CP, 2=WP, 4=PWP, 8=Agent, 16=JWP, 32=REST API, 64=JCP) |
| MQSRV_StartTime | datetime | DATE | timestamp | timestamp | true | start date |
| MQSRV_LastUpdate | datetime | DATE | timestamp | timestamp | true | last update |
| MQSRV_TcpIpAddr2 | varchar (64) | VARCHAR2 (64 CHAR) | varchar(64) | varchar (64) | true | local IP address |
| MQSRV_NetArea | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | Group CPs by this term |
| MQSRV_MQSet | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | 1 for new MQ1* and 2 for new MQ2* |
| MQSRV_RestEndpoint | varchar (128) | VARCHAR2 (128 CHAR) | varchar(128) | varchar (128) | true | REST Endpoint Url (protocol://hostname:port/api) for REST process and Websocket Url for JCP process |
| MQSRV_ConnCnt | int | NUMBER(38,0) | int | int | true | Connection count |
| MQSRV_PWPConnected | smallint | NUMBER(38,0) | smallint | smallint | true | Is Process connected to PWP |

### Indexes

| Name | Fields | Primary | Unique |
| --- | --- | --- | --- |
| PK_MQSRV | MQSRV_Name | true | true |
| NK_MQSRV_Type | MQSRV_Type | false | false |
