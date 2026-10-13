<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/EH.html
Erişim tarihi: 2026-10-10
Sürüm: Automic Automation / Reference Guides 24.4

# EH - executive header

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| EH_Client | smallint | NUMBER(38,0) | smallint | smallint | false | client |
| EH_OType | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | false | type of the activity |
| EH_USR_Idnr | int | NUMBER(38,0) | int | int | true | executing user |
| EH_OH_Idnr | int | NUMBER(38,0) | int | int | false | reference to the object header (OH) |
| EH_Name | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | name of the object |
| EH_AH_Idnr | int | NUMBER(38,0) | int | int | false | reference to the archive header (AH), Primary Key |
| EH_ParentAct | int | NUMBER(38,0) | int | int | true | AH_Idnr of activator parent |
| EH_ParentPrc | int | NUMBER(38,0) | int | int | true | AH_Idnr of processor parent |
| EH_EJPP_Lnr | smallint | NUMBER(38,0) | smallint | smallint | true | reference to the process line in parent jobplan |
| EH_StartTime | datetime | DATE | timestamp | timestamp | true | job starttime |
| EH_Status | int | NUMBER(38,0) | int | int | true | job state |
| EH_HostDst | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | host name |
| EH_LoginDst | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | name of login object |
| EH_CodeNameDst | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | code table for  FT |
| EH_FileNameDst | varchar(max) | VARCHAR2 (1024 CHAR) | varchar(1024) | text | true | filename for FT |
| EH_HostSrc | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | host name (sender) |
| EH_LoginSrc | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | name of login object |
| EH_CodeNameSrc | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | code table (sender) |
| EH_FileNameSrc | varchar(max) | VARCHAR2 (1024 CHAR) | varchar(1024) | text | true | filename for FT (sender); EMail notification: Attached File |
| EH_FileType | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | text, binary ... |
| EH_Ov | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | overwrite |
| EH_StartType | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | starttype |
| EH_MaxCpu | int | NUMBER(38,0) | int | int | true | max. CPU time |
| EH_Message | varchar(256) | VARCHAR2 (256 CHAR) | varchar(256) | varchar(256) | true | actual script line in progress |
| EH_Priority | varchar (5) | VARCHAR2 (5 CHAR) | varchar(5) | varchar (5) | true | . priority |
| EH_Express | smallint | NUMBER(38,0) | smallint | smallint | true | . express |
| EH_Output | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | . destination of the job reports       QueueM: destination of the job reports |
| EH_JobClass | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | . job class |
| EH_Rest | varchar(1024) | VARCHAR2 (1024 CHAR) | varchar(1024) | varchar(1024) | true | . additional attributes |
| EH_ProcessId | varchar (10) | VARCHAR2 (10 CHAR) | varchar(10) | varchar (10) | true | TSN / process id |
| EH_CpuTime | int | NUMBER(38,0) | int | int | true | used CPU time |
| EH_KernelTime | int | NUMBER(38,0) | int | int | true | used kernel time |
| EH_UserTime | int | NUMBER(38,0) | int | int | true | used user time |
| EH_IOCount | int | NUMBER(38,0) | int | int | true | job: number of I/O's     cockpit: frm_hight |
| EH_InfoText | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | text from Executor |
| EH_Count | bigint | NUMBER(38,0) | bigint | bigint | true | FT:number of bytes transferred (in progress)    JP: recursive level       group: number of tasks with errors     cockpit: frm_width |
| EH_FileSize | bigint | NUMBER(38,0) | bigint | bigint | true | bytes of the complete file |
| EH_Records | int | NUMBER(38,0) | int | int | true | number of records |
| EH_HostAttrType | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | attribute type of the host |
| EH_TaskCount | smallint | NUMBER(38,0) | smallint | smallint | true | number of EJPP |
| EH_IntAccount | varchar (16) | VARCHAR2 (16 CHAR) | varchar(16) | varchar (16) | true | Account |
| EH_Erase | smallint | NUMBER(38,0) | smallint | smallint | true | delete file after filetransfer |
| EH_AutoDeact | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | automatic deaktivation, QueueM: terminate automatically |
| EH_ActAtRun | smallint | NUMBER(38,0) | smallint | smallint | true | activation at runtime? |
| EH_MaxParallel | smallint | NUMBER(38,0) | smallint | smallint | true | group: maximum number of parallel tasks         FT: maximum number of parallel filetransfers using wildcard characters    QueueM: maximum number of parallel running jobs |
| EH_Restart | smallint | NUMBER(38,0) | smallint | smallint | true | restart activation? |
| EH_RefNr | int | NUMBER(38,0) | int | int | true | reference job number |
| EH_RestartPoint | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | restart point from where the task was restarted |
| EH_LastRP | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | last processed restart point |
| EH_EventType | char (2) | CHAR (2 CHAR) | char(2) | char (2) | true | Evnt: TT time event(timer), TS time event(time of execution) FS/FT filesystem,  CN console, FA = filesystem automatic Call-Op: OOA_TYP: question, message or alarm |
| EH_RepeatType | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | EV: R=repeated, S=single           FT: include subdirectories R=yes S=no       QueueM: Replicate Children |
| EH_TExecType | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | EV-TS: start after 'start time' E=execute N=noexecute EV-TT:S=start immediately FT: 1=filetransfer using wildcard characters; QueueM: Start ext. Jobs |
| EH_TimePeriod | char (4) | CHAR (4 CHAR) | char(4) | char (4) | true | evnt: period in minutes or HHMM depending on the event type            Call-Op: escalation time           schedule: period |
| EH_NextCheck | datetime | DATE | timestamp | timestamp | true | evnt: time when the event will be checked the next time       Call-Op: time when to escalate           schedule: end of the period |
| EH_Cancel | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | cancel flag: M=manually |
| EH_Max1 | int | NUMBER(38,0) | int | int | true | maximum...     FT: max. number of lines    QueueM: Up to this retcode the ext. task is ENDED_OK |
| EH_QuSRName | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | serverroutine which has to be notified when the task ends |
| EH_QuAcv | int | NUMBER(38,0) | int | int | true | ACV for the message |
| EH_RetCode | int | NUMBER(38,0) | int | int | true | user returncode |
| EH_EJ_ContentLen | int | NUMBER(38,0) | int | int | true | text length of EJ_Inhalt (EJ_content) |
| EH_MaxParallel2 | smallint | NUMBER(38,0) | smallint | smallint | true | maximum number of parallel running jobs |
| EH_MPElse | smallint | NUMBER(38,0) | smallint | smallint | true | bitarray for max parallel checkpoint and for what to do when the max. number is exceeded |
| EH_QuAddr | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | address for late confirmation |
| EH_MaxRetCode | int | NUMBER(38,0) | int | int | true | up to this retcode the activity is ENDED_OK |
| EH_Ert | int | NUMBER(38,0) | int | int | true | Estimated Runtime |
| EH_MrtTimeT | datetime | DATE | timestamp | timestamp | true | MRT as Timestamp f. Check |
| EH_ManualRelease | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | Y = task waits for manual release before start |
| EH_Signal | int | NUMBER(38,0) | int | int | true | Signals in this task (bitmask): 1=TCP exceeded, 2=MRT exceeded, 4=SRT not reached |
| EH_LDate | datetime | DATE | timestamp | timestamp | true | logical date |
| EH_RDate | datetime | DATE | timestamp | timestamp | true | real date |
| EH_TopNr | int | NUMBER(38,0) | int | int | true | job number of the topmost activity |
| EH_LastCheck | datetime | DATE | timestamp | timestamp | true | time of last event check |
| EH_LastOccur | datetime | DATE | timestamp | timestamp | true | time of last event occurrence |
| EH_CheckCount | int | NUMBER(38,0) | int | int | true | number of checks |
| EH_OccurCount | int | NUMBER(38,0) | int | int | true | number of occurred events |
| EH_LastMsgNr | int | NUMBER(38,0) | int | int | true | last message number |
| EH_LastMsgInsert | varchar (1024) | VARCHAR2 (1024 CHAR) | varchar(1024) | varchar (1024) | true | last messege insert |
| EH_EventSubType | varchar (2) | VARCHAR2 (2 CHAR) | varchar(2) | varchar (2) | true | event sub type |
| EH_Operator | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | G = greater L = less E = equal N = notequal |
| EH_Value | int | NUMBER(38,0) | int | int | true | value to compare at file events       console event: eventcounter       job/ft: status counter |
| EH_Object1 | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Call-OP: name of the Call-Op when an escalation occurs  Cockpit: Resource JOBP/JSCH: global alerting object    QueueM: Alarm Object |
| EH_Text | varchar(max) | CLOB | clob(20480 k) INLINE LENGTH 1004 COMPACT | text | true | Call-OP: text to send |
| EH_Execute | varchar (255) | VARCHAR2 (255 CHAR) | varchar(255) | varchar (255) | true | Call-OP: action to be executed (e.g. play .wav file)             job: actually running program |
| EH_MaxWait | int | NUMBER(38,0) | int | int | true | maximum time to wait before execution (in seconds)        QueueM: polling interval of the queue-object within the executor |
| EH_MrtMethod | int | NUMBER(38,0) | int | int | true | Method for Max. Runtime (bitmask) 0=no audit, 1=fix in seconds, 2=fix time, 4=ERT+xx%, 256=Cancel, 512=Start Object 65536=SRT in seconds, 131072=SRT ERT+xx% |
| EH_Mrt | int | NUMBER(38,0) | int | int | true | maximum running time (in seconds) |
| EH_MrtTime | varchar (6) | VARCHAR2 (6 CHAR) | varchar(6) | varchar (6) | true | Max. runtime in time ddhhmm or ssssss |
| EH_MrtErt | smallint | NUMBER(38,0) | smallint | smallint | true | MRT=ERT+xx% |
| EH_MrtExecute | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Call-Operator for auditing |
| EH_Srt | int | NUMBER(38,0) | int | int | true | SRT in Seconds |
| EH_SrtErt | smallint | NUMBER(38,0) | smallint | smallint | true | SRT=ERT+xx% |
| EH_Unit | int | NUMBER(38,0) | int | int | true | file event: unit of the value 0=host specific, 1 = byte, 2=KB, 3 = MB, 4=GB, 5=TB |
| EH_Source | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | WIN_EVENT: source; Mail Notification: Attached Reports |
| EH_Category | int | NUMBER(38,0) | int | int | true | WIN_EVENT: category      QueueM: Queue Type Message Number |
| EH_External | int | NUMBER(38,0) | int | int | true | bit array for external notification 1=SNMP, 2=eMail |
| EH_Archive1 | varchar (512) | VARCHAR2 (512 CHAR) | varchar(512) | varchar (512) | true | archive key 1 |
| EH_Archive2 | varchar (512) | VARCHAR2 (512 CHAR) | varchar(512) | varchar (512) | true | archive key 2 |
| EH_GrpRestart | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | Y=restart in group and not immediately |
| EH_FiFoNr | bigint | NUMBER(38,0) | bigint | bigint | true | FirstInFirstOut Ranking |
| EH_UC4Priority | smallint | NUMBER(38,0) | smallint | smallint | true | UC4 priority |
| EH_MPOk | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | maximum number of parallel running jobs is checked |
| EH_MPWaiting | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | maximum number of parallel running jobs: tasks are waiting |
| EH_DeactDelay | int | NUMBER(38,0) | int | int | true | delay in minutes |
| EH_MrtTZ | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Timezone for max. runtime when HHMM is used |
| EH_TimePeriodTZ | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Timezone for time period when HHMM is used |
| EH_TZ | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Timezone for this object and script |
| EH_DeactWhen | varchar (30) | VARCHAR2 (30 CHAR) | varchar(30) | varchar (30) | true | ok state for autom. deactivation |
| EH_RWhen | varchar (30) | VARCHAR2 (30 CHAR) | varchar(30) | varchar (30) | true | ok state global result |
| EH_ProcFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Processor Task? (1=Yes, 0=No) |
| EH_ParentHir | int | NUMBER(38,0) | int | int | true | AH_Idnr of hirarchical parent |
| EH_ReloadFlag | smallint | NUMBER(38,0) | smallint | smallint | true | for dynamic schedule |
| EH_Transferred | bigint | NUMBER(38,0) | bigint | bigint | true | Transferred Bytes |
| EH_Compress | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | Compress level |
| EH_ExtFlag | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | 1=This task is used as an external dependency |
| EH_EndTime | datetime | DATE | timestamp | timestamp | true | job endtime |
| EH_CmtFlag | smallint | NUMBER(38,0) | smallint | smallint | true | 0/1 flag for menue prompting + flag in runnr# field |
| EH_SkipMaxPar | smallint | NUMBER(38,0) | smallint | smallint | true | 0=check host max_parallel_settings, 1=ignore host max_parallel_settings |
| EH_StartUC4 | smallint | NUMBER(38,0) | smallint | smallint | true | 1=JOBD started by UC4 |
| EH_RemoteStatus | int | NUMBER(38,0) | int | int | true | Msgnr of actual state |
| EH_HostAttrTypeSrc | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | attribute type of the host (source) |
| EH_ReuseHostGroup | smallint | NUMBER(38,0) | smallint | smallint | true | Reuse hostgroup resolution within job plan? (1=Yes, 0=No) |
| EH_HGSrc | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | Name of source hostgroup |
| EH_HGDst | varchar (32) | VARCHAR2 (32 CHAR) | varchar(32) | varchar (32) | true | Name of destination hostgroup |
| EH_MaxParallelHG | int | NUMBER(38,0) | int | int | true | max amount of parallel running tasks in host group |
| EH_ChildCnt | int | NUMBER(38,0) | int | int | true | Amount of childs |
| EH_ChildCntActive | int | NUMBER(38,0) | int | int | true | Amount of childs that are active at the moment |
| EH_ChildCntEnded | int | NUMBER(38,0) | int | int | true | Amount of finished childs |
| EH_ChildNr | int | NUMBER(38,0) | int | int | true | Running number of child (X st child) |
| EH_ChildCntFail | int | NUMBER(38,0) | int | int | true | Failed childs (successful restarts compensate failures) |
| EH_ChildCntFailAll | int | NUMBER(38,0) | int | int | true | Failed childs |
| EH_ChildCntRestart | int | NUMBER(38,0) | int | int | true | Count of restarted childs |
| EH_ContainerType | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Original type of object (job, ft, ...) |
| EH_ErrorCount | int | NUMBER(38,0) | int | int | true | count of errors |
| EH_NextOccur | datetime | DATE | timestamp | timestamp | true | Next dispatch |
| EH_Resource | int | NUMBER(38,0) | int | int | true | Count of resources used by this object (JOBS, FT, JOBD) |
| EH_EV_Flag | smallint | NUMBER(38,0) | smallint | smallint | true | 1=EV is defined, 0=there is no EV |
| EH_RunTime | int | NUMBER(38,0) | int | int | true | Runtime in Seconds |
| EH_LocalDate | datetime | DATE | timestamp | timestamp | true | local LDATE after script processing with time 0:00:00 |
| EH_EV_Mode | smallint | NUMBER(38,0) | smallint | smallint | true | Mode for heritage of values (0=InheritAll, 1=InheritDefined, 2=InheritNone) |
| EH_EV_Inherit | int | NUMBER(38,0) | int | int | true | Inherit values from father? (0=no inherit, 1=yest) |
| EH_ModUserIdnr | int | NUMBER(38,0) | int | int | true | User who is modifying this task |
| EH_ModDate | datetime | DATE | timestamp | timestamp | true | Date/Time since this task is modifying |
| EH_LastModUserIdnr | int | NUMBER(38,0) | int | int | true | Last User who modified this task |
| EH_EventId | int | NUMBER(38,0) | int | int | true | Events: First AH_Idnr, used as ID for communication with Executors |
| EH_ModFlag | smallint | NUMBER(38,0) | smallint | smallint | true | 1 = Task was modified |
| EH_EventSubType2 | varchar (2) | VARCHAR2 (2 CHAR) | varchar(2) | varchar (2) | true | Second check type (FC=File changed; FS=File stable) |
| EH_CheckWithin | int | NUMBER(38,0) | int | int | true | Seconds in the past within the Event has to check |
| EH_InclSubDir | smallint | NUMBER(38,0) | smallint | smallint | true | Check includes sub directores (0=no, 1=yes) |
| EH_Subject | varchar (512) | VARCHAR2 (512 CHAR) | varchar(512) | varchar (512) | true | Subject (for mail notification) |
| EH_OptReport | varchar (64) | VARCHAR2 (64 CHAR) | varchar(64) | varchar (64) | true | Optional reports |
| EH_ConsiderAll | smallint | NUMBER(38,0) | smallint | smallint | true | Fileevent: Consider all files (0=no, 1=yes) |
| EH_RandomId | int | NUMBER(38,0) | int | int | true | Randomly generated ID by an agent to identify jobs also activated by this agent. (Default=0) |
| EH_HostFsc | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Filescan Host |
| EH_LoginFsc | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Filescan Login Object |
| EH_PPFFlag | smallint | NUMBER(38,0) | smallint | smallint | true | 1=PPF is defined, 0=no PPF |
| EH_MrcExecute | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Alarm object for max retcode |
| EH_PPFInherit | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | OutputScanTarget (N=no children,Y=with children,C=children only) |
| EH_Queue | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Name of the Queue the Object runs within |
| EH_ChildQueue | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | The children are assigned to this Queue |
| EH_QueueSlot | smallint | NUMBER(38,0) | smallint | smallint | true | Task occupies a Queue Slot (0=no, 1=yes) |
| EH_QueueSlotOK | smallint | NUMBER(38,0) | smallint | smallint | true | Is Queue Slot already assigned? (0=no, 1=yes) |
| EH_QueuePriority | smallint | NUMBER(38,0) | smallint | smallint | true | Priority of the Queue |
| EH_ERTEnd | datetime | DATE | timestamp | timestamp | true | Estimated end of the Task |
| EH_Sent | int | NUMBER(38,0) | int | int | true | Files already sent/transferred |
| EH_Successful | int | NUMBER(38,0) | int | int | true | Files sent successfully |
| EH_FTRestart | smallint | NUMBER(38,0) | smallint | smallint | true | Restart behavior during new file transfer (0 = none, 1 = continue, 2 = new) |
| EH_KeepAtt | smallint | NUMBER(38,0) | smallint | smallint | true | Keep file attributes (only on the same OS possible) (0=no, 1=yes) |
| EH_CancelOn1stErr | smallint | NUMBER(38,0) | smallint | smallint | true | Shall a FT be cancelled when an error occurs during a wildcard FT or not. (0 = no, 1 = yes) |
| EH_SubStatus | int | NUMBER(38,0) | int | int | true | job state |
| EH_BH_Idnr | int | NUMBER(38,0) | int | int | true | reference of the used buffer header |
| EH_TotalFiles | int | NUMBER(38,0) | int | int | true | Number of files to be transferred |
| EH_StreamSize | bigint | NUMBER(38,0) | bigint | bigint | true | Size (Bytes) of uncompressed data streamed from the sender to the receiver agent |
| EH_MemID | int | NUMBER(38,0) | int | int | true | MemID of GENX Message, saved at prompt-start |
| EH_DVAR_Memid | int | NUMBER(38,0) | int | int | true | MQMEM_Id; entry with infos for UCDVAR_R |
| EH_RemoteStatusIns | varchar (100) | VARCHAR2 (100 CHAR) | varchar(100) | varchar (100) | true | MsgInsert for MsgNr in EH_RemoteStatus |
| EH_MemIDLen | int | NUMBER(38,0) | int | int | true | L�nge des Speichers in EH_MemID |
| EH_DynFileCount | smallint | NUMBER(38,0) | smallint | smallint | true | Number dynamic registered Outputfiles |
| EH_EPUD_Flag | smallint | NUMBER(38,0) | smallint | smallint | true | Task has EPUDs |
| EH_ParentEJPPVFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Task has EJPPVs |
| EH_OEO_Flag | smallint | NUMBER(38,0) | smallint | smallint | true | Task OEOs |
| EH_GeneratedFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Task is already generated |
| EH_ReportSrc | smallint | NUMBER(38,0) | smallint | smallint | true | Source of attached reports (0=Database, 1=Ext. files, 2=All) |
| EH_Alias | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Alias Name for ProcessFlow task |
| EH_ChildFlags | char (32) | CHAR (32 CHAR) | char(32) | char (32) | true | Flags for Subtables |
| EH_PromptTimeout | datetime | DATE | timestamp | timestamp | true | Prompt-Timeout time for Timer processing |
| EH_Session | int | NUMBER(38,0) | int | int | true | Orignial session of the start-user |
| EH_Title | varchar (512) | VARCHAR2 (512 CHAR) | varchar(512) | varchar (512) | true | The title of OH_Title |
| EH_Icon | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | object icon |
| EH_Deployment | smallint | NUMBER(38,0) | smallint | smallint | true | Is deployment Tab active or not |
| EH_WFType | smallint | NUMBER(38,0) | smallint | smallint | true | Deployment Workflow Type (0 standard, 1 application, 2 component) |
| EH_AppName | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Deployment Application Name |
| EH_ComponentName | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Deployment Component Name |
| EH_RollbackFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Rollback is enabled for object |
| EH_LoopIteration | int | NUMBER(38,0) | int | int | true | Iteration of loop in which task has been started |
| EH_RBCount | int | NUMBER(38,0) | int | int | true | Number of Rollbacks |
| EH_RBErrCount | int | NUMBER(38,0) | int | int | true | Number of Errors during Rollback |
| EH_SubDirStruct | smallint | NUMBER(38,0) | smallint | smallint | true | Transfer complete subfolder structure |
| EH_ReqParameters | smallint | NUMBER(38,0) | smallint | smallint | true | Request Parameters (0=No, 1=Yes) |
| EH_HostVara | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Agent for resolving Filelist or Backen VARA we are waiting for |
| EH_SubType | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | OType specific SubType |
| EH_RerunState | smallint | NUMBER(38,0) | smallint | smallint | true | State for Rerun |
| EH_ActivationTime | datetime | DATE | timestamp | timestamp | true | Activation time (= AH_Timestamp1) |
| EH_ERTCalc | smallint | NUMBER(38,0) | smallint | smallint | true | The status of ERT calculation (0=no ERT, 1=ERT calculation active, 2=ERT calculation succeeded, 3=ERT calculation failed) |
| EH_ERTStatus | smallint | NUMBER(38,0) | smallint | smallint | true | Status of the job before start of ERT calculation |
| EH_DeplDescIdnr | int | NUMBER(38,0) | int | int | true | Task which stores the Deployment Descriptor |
| EH_MsgMemId | int | NUMBER(38,0) | int | int | true | MemID of saved message |
| EH_MsgMemIdLen | int | NUMBER(38,0) | int | int | true | Length of memory in EH_MsgMemId |
| EH_WFName | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Deployment Workflow Name |
| EH_AutoQuit | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | J=Quit automatically on escalation |
| EH_Description | varchar (255) | VARCHAR2 (255 CHAR) | varchar(255) | varchar (255) | true | Period description for periodic tasks |
| EH_AEVersion | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | AE system version |
| EH_MQSet | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | 1 for new MQ1* and 2 for new MQ2* |
| EH_ComplRate | int | NUMBER(38,0) | int | int | true | Number of completed tasks in a workflow |
| EH_PassPrio | smallint | NUMBER(38,0) | smallint | smallint | true | Pass on Workflow priority to children: 1 means True, 0 is False |
| EH_ModCnt | int | NUMBER(38,0) | int | int | true | modification counter |
| EH_AgentSession | int | NUMBER(38,0) | int | int | true | CAU agent session number |
| EH_StoreName | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Identification of STORE object (EVNT.IA.*) |
| EH_Language | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | Language for the webhook callback |
| EH_HasCallback | smallint | NUMBER(38,0) | smallint | smallint | true | Does this EH have an associated webhook callback |
| EH_Cert_Sync | int | NUMBER(38,0) | int | int | true | 0=no root cert sync has been done, 1=one quitt was received for PUSHCERT messages, 2=two quitt-s received, FT can be restarted |
| EH_Gateway | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Used Gateway for Filetransfer |
| EH_SelectedGWList | varchar (256) | VARCHAR2 (256 CHAR) | varchar(256) | varchar (256) | true | Used Gateway OH_Idnr-s comma separated for this file transfer |
| EH_Event_MemID | int | NUMBER(38,0) | int | int | true | MQMEM_ID; entry with infos for Event |
| EH_Recursivelevel | int | NUMBER(38,0) | int | int | true | Execution recursive level |

| Name | Fields | Primary | Unique | Clustered | Nonclustered |
| --- | --- | --- | --- | --- | --- |
| NK_EH_ChildNr | EH_ParentPrc, EH_Status, EH_ChildNr, EH_AH_Idnr | false | false | false | false |
| NK_EH_EventId | EH_EventId | false | false | false | false |
| NK_EH_Mrt | EH_MrtTimeT | false | false | false | false |
| NK_EH_Name | EH_Name, EH_Alias, EH_Client, EH_OType, EH_Status, EH_StartType | false | false | false | false |
| NK_EH_NextCheck | EH_NextCheck, EH_OType, EH_Status | false | false | false | false |
| NK_EH_OH_IDNR | EH_OH_Idnr, EH_Status, EH_Client, EH_AH_Idnr | false | false | false | false |
| NK_EH_OType | EH_OType, EH_StartTime | false | false | false | false |
| NK_EH_ParentAct | EH_ParentAct, EH_Client | false | false | false | false |
| NK_EH_ParentPrc | EH_ParentPrc, EH_Client | false | false | false | false |
| NK_EH_StartType | EH_StartType, EH_Status, EH_Client | false | false | false | false |
| NK_EH_TopNr | EH_TopNr | false | false | false | false |
| PK_EH | EH_AH_Idnr | true | true | true | false |
| NK_EH_RefNr | EH_RefNr, EH_Restart, EH_CmtFlag | false | false | false | false |
| NK_EH_Status | EH_Status, EH_Client, EH_Restart, EH_QueuePriority, EH_UC4Priority, EH_ComplRate, EH_FifoNr | false | false | false | false |
| NK_EH_Queue | EH_Queue, EH_Status, EH_Client, EH_QueueSlotOK, EH_QueuePriority, EH_UC4Priority, EH_ComplRate, EH_FiFoNr | false | false | false | false |
| NK_EH_HOST | EH_OType, EH_SubType, EH_EventSubType, EH_Status, EH_HostDst, EH_HostSrc, EH_Hostfsc, EH_HostVara | false | false | false | false |
| NK_EH_ParentHir | EH_Parenthir, EH_Client, EH_Otype | false | false | false | false |

| Name | Local References | Foreign References |
| --- | --- | --- |