<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/AH.html
Erişim tarihi: 2026-10-10
Sürüm: Automic Automation / Reference Guides 24.4

# AH - archive header

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| AH_Client | smallint | NUMBER(38,0) | smallint | smallint | true | number of the client |
| AH_OType | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | objecttype |
| AH_SType | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | subtype of the activity |
| AH_Idnr | int | NUMBER(38,0) | int | int | false | primary key of the archive header |
| AH_USR_Idnr | int | NUMBER(38,0) | int | int | true | IDNR of the user that executed this activity |
| AH_OH_Idnr | int | NUMBER(38,0) | int | int | true | processed IDNR |
| AH_TimeStamp1 | datetime | DATE | timestamp | timestamp | true | activation time |
| AH_TimeStamp2 | datetime | DATE | timestamp | timestamp | true | start time |
| AH_TimeStamp3 | datetime | DATE | timestamp | timestamp | true | end time (before post processing if available) |
| AH_TimeStamp4 | datetime | DATE | timestamp | timestamp | true | end time (including post processing time if available) |
| AH_MsgNr | int | NUMBER(38,0) | int | int | true | return code |
| AH_MsgInsert | varchar (1024) | VARCHAR2 (1024 CHAR) | varchar(1024) | varchar (1024) | true | message insert to the message number |
| AH_Info | varchar (20) | VARCHAR2 (20 CHAR) | varchar(20) | varchar (20) | true | additional information like job number |
| AH_HostDst | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | name of the host or hostgroup |
| AH_LoginDst | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | name of login object |
| AH_CodeNameDst | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | codetable for filetransfer |
| AH_FileNameDst | varchar(max) | VARCHAR2 (1024 CHAR) | varchar(1024) | text | true | filename for filetransfer |
| AH_CpuTime | int | NUMBER(38,0) | int | int | true | used CPU time |
| AH_KernelTime | int | NUMBER(38,0) | int | int | true | used kernel time |
| AH_UserTime | int | NUMBER(38,0) | int | int | true | used user time |
| AH_IOCount | int | NUMBER(38,0) | int | int | true | count of I/Os |
| AH_InfoText | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | text from Exekutor |
| AH_HostSrc | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | name of host (sender) |
| AH_LoginSrc | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | name of login object for sender file |
| AH_CodeNameSrc | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | codetable for filetransfer (sender) |
| AH_FileNameSrc | varchar(max) | VARCHAR2 (1024 CHAR) | varchar(1024) | text | true | filename for filetransfer (sender) |
| AH_IntAccount | varchar (16) | VARCHAR2 (16 CHAR) | varchar(16) | varchar (16) | true | account |
| AH_ProcessId | varchar (10) | VARCHAR2 (10 CHAR) | varchar(10) | varchar (10) | true | TSN / process id |
| AH_Count | bigint | NUMBER(38,0) | bigint | bigint | true | filetransfer: bytes transfered     group: number of started activities |
| AH_FileSize | bigint | NUMBER(38,0) | bigint | bigint | true | bytes of the complete file |
| AH_Records | int | NUMBER(38,0) | int | int | true | number of records |
| AH_Status | int | NUMBER(38,0) | int | int | true | state of the activity |
| AH_RetCode | int | NUMBER(38,0) | int | int | true | return code |
| AH_ParentAct | int | NUMBER(38,0) | int | int | true | AH_Idnr of activator parent |
| AH_ParentPrc | int | NUMBER(38,0) | int | int | true | AH_Idnr of processor parent |
| AH_Restart | smallint | NUMBER(38,0) | smallint | smallint | true | was this a restarted activation? |
| AH_RefNr | int | NUMBER(38,0) | int | int | true | reference job number |
| AH_RestartPoint | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | restart point from where the task was restarted |
| AH_LastRP | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | last processed restart point |
| AH_EventType | char (2) | CHAR (2 CHAR) | char(2) | char (2) | true | TT time event(timer), TS time event(time of execution) FS/FT filesystem,  CN console, FA = filesystem automatic |
| AH_RepeatType | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | EV: R=repeated, S=single    FT: include subdirectories R=yes S=no      QueueM: replicate children |
| AH_TimePeriod | char (4) | CHAR (4 CHAR) | char(4) | char (4) | true | period in minutes or HHMM depending on the event type |
| AH_CheckCount | int | NUMBER(38,0) | int | int | true | number of checks |
| AH_OccurCount | int | NUMBER(38,0) | int | int | true | number of occourred events |
| AH_EventSubType | char (2) | CHAR (2 CHAR) | char(2) | char (2) | true | event sub type |
| AH_Operator | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | G = Greater L = Less E = Equal N = NotEqual |
| AH_Value | int | NUMBER(38,0) | int | int | true | value to compare |
| AH_DeleteFlag | smallint | NUMBER(38,0) | smallint | smallint | true | the delete flag |
| AH_Cancel | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | the cancel flag: M=manually |
| AH_TaskCount | smallint | NUMBER(38,0) | smallint | smallint | true | number of AJPP |
| AH_Unit | int | NUMBER(38,0) | int | int | true | unit of AH_Wert: 0=host specific, 1 = Byte, 2=KB, 3 = MB, 4=GB, 5=TB |
| AH_Source | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | WIN_EVENT: Source |
| AH_Category | int | NUMBER(38,0) | int | int | true | WIN_EVENT: Category |
| AH_TExecType | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | EV-TS: start after 'start time' E=Execute N=NoExecute EV-TT:S=start immediately     FT: 1=filetransfer with wildcard characters    QueueM: start ext. jobs |
| AH_Archive1 | varchar (512) | VARCHAR2 (512 CHAR) | varchar(512) | varchar (512) | true | archive key 1 |
| AH_Archive2 | varchar (512) | VARCHAR2 (512 CHAR) | varchar(512) | varchar (512) | true | archive key 2 |
| AH_MaxRetCode | int | NUMBER(38,0) | int | int | true | up to this retcode the activity is ENDED_OK |
| AH_ArchiveFlag | smallint | NUMBER(38,0) | smallint | smallint | true | archive flag |
| AH_Rest | varchar(1024) | VARCHAR2 (1024 CHAR) | varchar(1024) | varchar(1024) | true | . additional attributes |
| AH_TZ | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Timezone for object and script |
| AH_TimePeriodTZ | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Timezone for time period (event) when HHMM is used |
| AH_Name | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | name of the object |
| AH_LDate | datetime | DATE | timestamp | timestamp | true | logical date |
| AH_Transferred | bigint | NUMBER(38,0) | bigint | bigint | true | Transferred bytes |
| AH_Compress | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | Compress level |
| AH_LoginSrcO | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Original Login Source Name |
| AH_LoginDstO | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Original Login Destination Name |
| AH_ModCnt | int | NUMBER(38,0) | int | int | true | modification counter |
| AH_ProcFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Processor Task? (1=Yes, 0=No) |
| AH_RunTime | int | NUMBER(38,0) | int | int | true | Runtime in Seconds |
| AH_HostAttrTypeS | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | attribute type of the host (source) |
| AH_HostAttrTypeD | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | attribute type of the host (destination) |
| AH_CmtFlag | smallint | NUMBER(38,0) | smallint | smallint | true | 0/1 flag for menue prompting + flag in runnr# field |
| AH_SkipMaxPar | smallint | NUMBER(38,0) | smallint | smallint | true | 0=evaluation of host max_parallel_settings, 1=ignore host max_parallel_settings |
| AH_StartUC4 | smallint | NUMBER(38,0) | smallint | smallint | true | 1=JOBD started by UC4 |
| AH_RemoteStatus | int | NUMBER(38,0) | int | int | true | Msgnr of actual state |
| AH_ERT | int | NUMBER(38,0) | int | int | true | Estimated Runtime |
| AH_ReuseHostGroup | smallint | NUMBER(38,0) | smallint | smallint | true | Reuse hostgroup resolution within job plan? (1=Yes, 0=No) |
| AH_HGSrc | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | Name of source hostgroup |
| AH_HGDst | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | Name of destination hostgroup |
| AH_MaxParallelHG | int | NUMBER(38,0) | int | int | true | max amount of parallel running tasks in host group |
| AH_ChildCnt | int | NUMBER(38,0) | int | int | true | Amount of childs |
| AH_ChildCntFail | int | NUMBER(38,0) | int | int | true | Failed childs (successful restarts compensate failures) |
| AH_ChildCntFailAll | int | NUMBER(38,0) | int | int | true | Failed childs |
| AH_ChildCntRestart | int | NUMBER(38,0) | int | int | true | Count of restarted childs |
| AH_ContainerType | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Original type of object (job, ft, ...) |
| AH_ErrorCount | int | NUMBER(38,0) | int | int | true | count of errors |
| AH_Resource | int | NUMBER(38,0) | int | int | true | Count of resources used by this object (JOBS, FT, JOBD) |
| AH_LocalDate | datetime | DATE | timestamp | timestamp | true | local LDATE after script processing with time 0:00:00 |
| AH_TopNr | int | NUMBER(38,0) | int | int | true | job number of the topmost activity |
| AH_EventId | int | NUMBER(38,0) | int | int | true | Events: First AH_Idnr, used as ID for communication with Executors |
| AH_ModFlag | smallint | NUMBER(38,0) | smallint | smallint | true | 1=Task was  modified |
| AH_EventSubType2 | varchar (2) | VARCHAR2 (2 CHAR) | varchar(2) | varchar (2) | true | Second check type (FC=File changed; FS=File stable) |
| AH_CheckWithin | int | NUMBER(38,0) | int | int | true | Seconds in the past within the Event has to check |
| AH_InclSubDir | smallint | NUMBER(38,0) | smallint | smallint | true | Check includes sub directores (0=no, 1=yes) |
| AH_ConsiderAll | smallint | NUMBER(38,0) | smallint | smallint | true | Fileevent: Consider all files (0=no, 1=yes) |
| AH_HostFsc | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Filescan Host |
| AH_LoginFsc | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Filescan Login Object |
| AH_MrcExecute | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Alarm object for max retcode |
| AH_PPFInherit | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | OutputScanTarget (N=no children,Y=with children,C=children only) |
| AH_Queue | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Name of the Queue the Object runs within |
| AH_QueueSlot | smallint | NUMBER(38,0) | smallint | smallint | true | Task occupies a Queue Slot (0=no, 1=yes) |
| AH_Sent | int | NUMBER(38,0) | int | int | true | Files already sent/transferred |
| AH_Successful | int | NUMBER(38,0) | int | int | true | Files sent successfully |
| AH_TotalFiles | int | NUMBER(38,0) | int | int | true | Number of files to be transferred |
| AH_StreamSize | bigint | NUMBER(38,0) | bigint | bigint | true | Size (Bytes) of uncompressed data streamed from the sender to the receiver agent |
| AH_Alias | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Alias Name for ProcessFlow task |
| AH_Title | varchar (512) | VARCHAR2 (512 CHAR) | varchar(512) | varchar (512) | true | The title of OH_Title |
| AH_Icon | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | object icon |
| AH_Token | varchar (128) | VARCHAR2 (128 CHAR) | varchar(128) | varchar (128) | true | encrypted token |
| AH_Deployment | smallint | NUMBER(38,0) | smallint | smallint | true | Is deployment Tab active or not |
| AH_WFType | smallint | NUMBER(38,0) | smallint | smallint | true | Deployment Workflow Type (0 standard, 1 application, 2 component) |
| AH_AppName | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Deployment Application Name |
| AH_ComponentName | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Deployment Component Name |
| AH_RollbackFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Rollback is enabled for object |
| AH_ChildFlags | char (32) | CHAR (32 CHAR) | char(32) | char (32) | true | Flags for Subtables |
| AH_RBCount | int | NUMBER(38,0) | int | int | true | Number of Rollbacks |
| AH_RBErrCount | int | NUMBER(38,0) | int | int | true | Number of Errors during Rollback |
| AH_SubDirStruct | smallint | NUMBER(38,0) | smallint | smallint | true | Transfer complete subfolder structure |
| AH_SubType | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | OType specific SubType |
| AH_RemoteStatusIns | varchar (100) | VARCHAR2 (100 CHAR) | varchar(100) | varchar (100) | true | MsgInsert for MsgNr in EH_RemoteStatus |
| AH_DeplDescIdnr | int | NUMBER(38,0) | int | int | true | Task which stores the Deployment Descriptor |
| AH_AV_Mode | smallint | NUMBER(38,0) | smallint | smallint | true | Mode for heritage of values (0=InheritAll, 1=InheritDefined, 2=InheritNone |
| AH_Description | varchar (255) | VARCHAR2 (255 CHAR) | varchar(255) | varchar (255) | true | Period description for periodic tasks |
| AH_ParentHir | int | NUMBER(38,0) | int | int | true | AH_Idnr of hirarchical parent |
| AH_UC4Priority | smallint | NUMBER(38,0) | smallint | smallint | true | UC4 priority |
| AH_AJPP_Lnr | smallint | NUMBER(38,0) | smallint | smallint | true | reference to the process line in parent jobplan |
| AH_AEVersion | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | AE system version |
| AH_Version | varchar (270) | VARCHAR2 (270 CHAR) | varchar(270) | varchar (270) | true | Full verion of a component (Agent,Server) |
| AH_StoreName | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Identification of STORE object (EVNT.IA.*) |

| Name | Fields | Primary | Unique | Clustered | Nonclustered |
| --- | --- | --- | --- | --- | --- |
| NK_AH_Archive | AH_Client, AH_ArchiveFlag, AH_DeleteFlag, AH_TimeStamp4, AH_Idnr | false | false | false | false |
| NK_AH_Archive1 | AH_Archive1, AH_Client, AH_Idnr | false | false | false | false |
| NK_AH_Archive2 | AH_Archive2, AH_Client, AH_Idnr | false | false | false | false |
| NK_AH_Atyp | AH_Client, AH_OType, AH_SType, AH_TimeStamp1, AH_TimeStamp4, AH_Idnr, AH_EventId | false | false | false | false |
| NK_AH_CmtFlag | AH_CmtFlag, AH_Client, AH_Idnr | false | false | false | false |
| NK_AH_Date2 | AH_Client, AH_TimeStamp2, AH_OType, AH_Idnr | false | false | false | false |
| NK_AH_Date4_1 | AH_Client, AH_TimeStamp4, AH_Idnr | false | false | false | false |
| NK_AH_Date4_2 | AH_Idnr, AH_Client, AH_TimeStamp4 | false | false | false | false |
| NK_AH_DelFlag | AH_DeleteFlag, AH_Client, AH_Idnr | false | false | false | false |
| NK_AH_ExtCond | AH_Client, AH_LocalDate, AH_Name, AH_Idnr | false | false | false | false |
| NK_AH_IDNR_bearb | AH_Client, AH_OH_Idnr, AH_OType, AH_TimeStamp1, AH_TimeStamp4, AH_Idnr | false | false | false | false |
| NK_AH_Name2 | AH_TimeStamp4, AH_Name, AH_Client, AH_Idnr | false | false | false | false |
| NK_AH_Name3 | AH_Name, AH_TimeStamp4, AH_Client, AH_Idnr, AH_Status, AH_RetCode | false | false | false | false |
| NK_AH_OH_Idnr | AH_Client, AH_Idnr, AH_OH_Idnr | false | false | false | false |
| NK_AH_ParentAct | AH_ParentAct, AH_Idnr, AH_Otype | false | false | false | false |
| NK_AH_ParentHir | AH_Client, AH_ParentHir, AH_Idnr | false | false | false | false |
| NK_AH_ParentPrc | AH_ParentPrc, AH_Idnr | false | false | false | false |
| NK_AH_Queue | AH_Client, AH_Queue, AH_TimeStamp1, AH_TimeStamp4, AH_Idnr | false | false | false | false |
| NK_AH_Reorg | AH_Client, AH_TimeStamp4, AH_Idnr, AH_OType, AH_SType, AH_OH_Idnr, AH_Status | false | false | false | false |
| NK_AH_Run_EvntId | AH_Client, AH_OType, AH_Idnr, AH_EventId | false | false | false | false |
| NK_AH_Timestamp4 | AH_TimeStamp4, AH_OH_Idnr, AH_Idnr | false | false | false | false |
| NK_AH_TopNr | AH_TopNr, AH_Idnr | false | false | false | false |
| NK_AH_USR | AH_USR_Idnr, AH_ParentPrc, AH_Idnr | false | false | false | false |
| PK_AH | AH_Idnr | true | true | true | false |
| NK_AH_Name | AH_Name, AH_Client, AH_Timestamp1, AH_Idnr | false | false | false | false |
| NK_AH_Alias | AH_Client, AH_Alias, AH_Timestamp1, AH_Idnr | false | false | false | false |
| NK_AH_Date1 | AH_Client, AH_TimeStamp1, AH_OType, AH_Idnr | false | false | false | false |
| NK_AH_RefNr | AH_RefNr, AH_Restart, AH_CmtFlag, AH_Idnr | false | false | false | false |

| Name | Local References | Foreign References |
| --- | --- | --- |