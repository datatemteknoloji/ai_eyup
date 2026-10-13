<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/OH.html
Erişim tarihi: 2026-10-10
Sürüm: Automic Automation / Reference Guides 24.4

# OH - The header of the object.

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| OH_Client | smallint | NUMBER(38,0) | smallint | smallint | false | Number/ID of the client. |
| OH_OType | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | false | Type of the object. |
| OH_Name | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | false | Name of the object. |
| OH_Idnr | int | NUMBER(38,0) | int | int | false | ID of the object. |
| OH_Title | varchar (512) | VARCHAR2 (512 CHAR) | varchar(512) | varchar (512) | true | Description of the object. |
| OH_CrUserIdnr | int | NUMBER(38,0) | int | int | true | ID of the user who created the object. |
| OH_CrDate | datetime | DATE | timestamp | timestamp | true | Creation date of the object. |
| OH_ModUserIdnr | int | NUMBER(38,0) | int | int | true | ID of the user who modified the object last. |
| OH_ModDate | datetime | DATE | timestamp | timestamp | true | Date of the object's last modification. |
| OH_ModCnt | int | NUMBER(38,0) | int | int | true | Number that indicates how often the object was modified so far. |
| OH_LastUserIdnr | int | NUMBER(38,0) | int | int | true | ID of the last user who used the object. |
| OH_LastDate | datetime | DATE | timestamp | timestamp | true | Date of the object's last usage. |
| OH_LastCnt | int | NUMBER(38,0) | int | int | true | Number that indicates how often the obejct was used so far. |
| OH_JPP_Count | smallint | NUMBER(38,0) | smallint | smallint | true | Number of children a schedule/workflow contains. |
| OH_Share | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | Indicates whether a client 0 object is visible in other clients. I = readable, R = referenceable |
| OH_C0Ref | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates a reference to a client 0 object. |
| OH_NoStatUpd | smallint | NUMBER(38,0) | smallint | smallint | true | Status of extended reports to be written. 0 = Default (UC_CLIENT_SETTINGS), 1 = ALL, 2 = None |
| OH_DeleteFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Delete flag of the object. 0 = not deleted, 1 = deleted, 2 = versioned, 5 = archived/reorganized |
| OH_ExpFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Marks object ready for transport/unload. 0 = not marked, 1 = object located in transport case |
| OH_MaxWait | int | NUMBER(38,0) | int | int | true | Number of seconds to wait before starting the object. |
| OH_MaxParallel2 | smallint | NUMBER(38,0) | smallint | smallint | true | Maximum number of parallel running tasks. |
| OH_MPElse | smallint | NUMBER(38,0) | smallint | smallint | true | Defines how the task proceeds in case the maximum number of parallel running tasks allowed has reached. 0 = not defined, 1 = wait for next slot, 2 = abort task |
| OH_Archive1 | varchar (512) | VARCHAR2 (512 CHAR) | varchar(512) | varchar (512) | true | Archive key #1 |
| OH_Archive2 | varchar (512) | VARCHAR2 (512 CHAR) | varchar(512) | varchar (512) | true | Archive key #2 |
| OH_OpenUserIdnr | int | NUMBER(38,0) | int | int | true | ID of the user who currently edits the object. |
| OH_OpenDate | datetime | DATE | timestamp | timestamp | true | Date and time the user opened the object for modification. |
| OH_MaxRetCode | int | NUMBER(38,0) | int | int | true | Up to this return code the tasks will end successfully (status = ENDED_OK). |
| OH_MrtMethod | int | NUMBER(38,0) | int | int | true | Method for calculating the maximum runtime of the object. 0 = no audit, 1 = fix in seconds, 2 = fix time, 4 = ERT + xx%, 256 = Cancel, 512 = Start Object, 65536 = SRT in seconds, 131072 = SRT ERT + xx% |
| OH_Mrt | int | NUMBER(38,0) | int | int | true | Maximum runtime time in seconds. |
| OH_MrtTime | char (6) | CHAR (6 CHAR) | char(6) | char (6) | true | Maximum runtime in time format ddhhmm. |
| OH_MrtErt | smallint | NUMBER(38,0) | smallint | smallint | true | MRT = ERT + xx% |
| OH_MrtExecute | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Object to start for runtime audit. |
| OH_Frt | int | NUMBER(38,0) | int | int | true | Fixed runtime in seconds. |
| OH_Ert | int | NUMBER(38,0) | int | int | true | Estimated runtime (ERT) in seconds. |
| OH_ErtCnt | smallint | NUMBER(38,0) | smallint | smallint | true | Check last x runs for ERT. |
| OH_ErtCorr | smallint | NUMBER(38,0) | smallint | smallint | true | Correction for estimated runtime in percentage. |
| OH_ErtIgn | smallint | NUMBER(38,0) | smallint | smallint | true | Ignore ERT > xx% deviation |
| OH_ErtMinCnt | smallint | NUMBER(38,0) | smallint | smallint | true | Ignore ERT below a certain number of runs. |
| OH_ErtMethod | int | NUMBER(38,0) | int | int | true | Method for calculating the estimated runtime of the object. 0 = default, 1 = fix, 2 = avg, 4 = max, 8 = line arregression, 256 = ignore deviation |
| OH_ErtTrend | int | NUMBER(38,0) | int | int | true | Trend of the estimated runtime. 0 = undefined, 1=constant downward, 2=downward, 4=upward, 8 = constant upward |
| OH_LastRuns | varbinary(100) | RAW(100) | varchar(100) for bit data | bytea | true | Runtime of the object's last 25 runs in seconds. |
| OH_Srt | int | NUMBER(38,0) | int | int | true | Shortest runtime (SRT) in seconds |
| OH_SrtErt | smallint | NUMBER(38,0) | smallint | smallint | true | SRT = ERT + xx% |
| OH_FcstStatus | int | NUMBER(38,0) | int | int | true | Default end status for forecast. |
| OH_UC4Priority | smallint | NUMBER(38,0) | smallint | smallint | true | Priority of the object. |
| OH_TZ | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Time zone of the object. |
| OH_MrtTZ | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Time zone used for max. runtime (when a fixed time is used). |
| OH_RefIdnr | int | NUMBER(38,0) | int | int | true | Reference id to original object, if object is versioned (OH_DeleteFlag = 2). |
| OH_OX_ContentLen | int | NUMBER(38,0) | int | int | true | Length of db field OX_Content (db table OX). |
| OH_ExtFlag | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | Indicates whether or not this task is used as an external dependency. |
| OH_OpenSession | int | NUMBER(38,0) | int | int | true | Session ID of the user who opened this object for modification. |
| OH_OV_Flag | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates whether the object contains object variables or not (0 = no object variables, 1 = object variabels available) |
| OH_OV_Mode | smallint | NUMBER(38,0) | smallint | smallint | true | Defines how object variables are passed to the objects children. 0 = inherit all, 1 = inherit defined, 2 = inherit none) |
| OH_HostFsc | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Name of the agent used for the file scan. |
| OH_LoginFsc | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Login object used for the file scan. |
| OH_MrcExecute | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Alarm object that is executed if max retcode is reached. |
| OH_PPFInherit | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | Defines where to apply the output filters to. N = parent task only, Y = parent and children tasks, C = children tasks only |
| OH_HostAttrTypeDst | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Platform of the destination agent. |
| OH_Queue | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Name of the queue the object runs within. |
| OH_ChildQueue | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Name of the queue the children are assigned to. |
| OH_OPU_Flag | smallint | NUMBER(38,0) | smallint | smallint | true | Object has prompt sets defined. |
| OH_OEO_Flag | smallint | NUMBER(38,0) | smallint | smallint | true | Object has external output files defined. |
| OH_ChildFlags | char (32) | CHAR (32 CHAR) | char(32) | char (32) | true | Flags for sub-tables. |
| OH_IsTemplate | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates that the object is a template or not. |
| OH_Icon | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Icon of the object. |
| OH_RollbackFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates, that rollback functionality is enabled for that object. |
| OH_Inactive | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates, that this object is active or not. |
| OH_SubType | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | The sub-type of the object. |
| OH_DeactDelay | int | NUMBER(38,0) | int | int | true | Deactivation delay in minutes. |
| OH_AutoDeact | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | Indicates wheter the object is automatically deactivated when finished.  A = always, N = no, F = when errorfree, J = during first error-free run |
| OH_DeactWhen | varchar (30) | VARCHAR2 (30 CHAR) | varchar(30) | varchar (30) | true | OK state for automatic deactivation. |
| OH_AEVersion | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | The minimum version of the AE system the object can be used with. |
| OH_LastCommitDate | datetime | DATE | timestamp | timestamp | true | Timestamp of the last commit |
| OH_VersioningId | varchar (255) | VARCHAR2 (255 CHAR) | varchar(255) | varchar (255) | true | Hashcode generated from the initial properties of the object and a salt to stay unique. Used to track the object in version control. |

| Name | Fields | Primary | Unique | Clustered | Nonclustered |
| --- | --- | --- | --- | --- | --- |
| NK_OH_DelFlag | OH_DeleteFlag, OH_Client, OH_OpenUserIdnr, OH_Idnr | false | false | false | false |
| NK_OH_ModDate | OH_OType, OH_ModDate | false | false | false | false |
| NK_OH_MrtExecute | OH_MrtExecute, OH_Client | false | false | false | false |
| NK_OH_OpenSess | OH_OpenSession | false | false | false | false |
| NK_OH_OType | OH_Client, OH_OType, OH_Name, OH_Idnr | false | false | false | false |
| NK_OH_RefIdnr | OH_RefIdnr, OH_ModCnt, OH_Idnr | false | false | false | false |
| NK_OH_Reorg | OH_Client, OH_DeleteFlag, OH_ModDate, OH_RefIdnr, OH_Idnr | false | false | false | false |
| NK_OH_Search | OH_Client, OH_DeleteFlag, OH_OType, OH_Name, OH_Idnr | false | false | false | false |
| NK_OH_Search2 | OH_Client, OH_Name | false | false | false | false |
| PK_OH | OH_Idnr | true | true | true | false |
| UK_OH_Name | OH_Name, OH_Client | false | true | false | false |
| NK_OH_OType2 | OH_Idnr, OH_Client, OH_OType | false | false | false | false |
| NK_OH_ModDate2 | OH_ModDate, OH_DeleteFlag | false | false | false | false |
| NK_OH_CrDate | OH_CrDate, OH_DeleteFlag | false | false | false | false |
| NK_OH_VersioningId | OH_VersioningId | false | false | false | false |
| NK_OH_Search3 | OH_LastDate, OH_ModDate, OH_CrDate, OH_Idnr | false | false | false | false |

| Name | Local References | Foreign References |
| --- | --- | --- |