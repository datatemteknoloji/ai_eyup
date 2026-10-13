<!-- resmi kaynak kaydı -->
URL: https://techdocs.broadcom.com/us/en/ca-enterprise-software/intelligent-automation/automic-reference-guides/24-4/automic-db-schema/JPP.html
Erişim tarihi: 2026-10-10
Sürüm: Automic Automation / Reference Guides 24.4

# JPP - jobplan process

| Name | Type MSSql | Type Oracle | Type DB2 | Type Postgresql | Nullable | Description |
| --- | --- | --- | --- | --- | --- | --- |
| JPP_OH_Idnr | int | NUMBER(38,0) | int | int | false | ID of the object. |
| JPP_Lnr | smallint | NUMBER(38,0) | smallint | smallint | false | Sequenced number of the workflow tasks. |
| JPP_OType | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Type of the workflow task. |
| JPP_Object | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Name of the workflow task. |
| JPP_Comment | varchar (40) | VARCHAR2 (40 CHAR) | varchar(40) | varchar (40) | true | Comment |
| JPP_ErlstStTime | varchar (10) | VARCHAR2 (10 CHAR) | varchar(10) | varchar (10) | true | Earliest start time of the workflow task. |
| JPP_LtstStTime | varchar (10) | VARCHAR2 (10 CHAR) | varchar(10) | varchar (10) | true | Latest start time of the workflow task. |
| JPP_LtstEndTime | varchar (10) | VARCHAR2 (10 CHAR) | varchar(10) | varchar (10) | true | Latest end time of the workflow task. |
| JPP_WElse | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | Defines the action that will be triggered, if the status of any predecessor is not successful. S = skip, H = halt, A = abend, X = block and abort |
| JPP_WCType | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | Conjunction for the pre-conditions. |
| JPP_CCType | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | Calendar condition of the workflow task. 1 = and, 2 = equal, 3 = not equal, 4 = ext. |
| JPP_PreCnt | smallint | NUMBER(38,0) | smallint | smallint | true | Number of this workflow task's predecessors. |
| JPP_Row | smallint | NUMBER(38,0) | smallint | smallint | true | y-coordinate of the workflow task (for the graphical representation within the workflow editor/monitor). |
| JPP_Col | smallint | NUMBER(38,0) | smallint | smallint | true | x-coordinate of the workflow task (for the graphical representation within the workflow editor/monitor). |
| JPP_WhenExecute | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Name of the object, that will be triggered, if the status of any predecessor is not successful. |
| JPP_Active | smallint | NUMBER(38,0) | smallint | smallint | true | bit 1: active/inactive, bit 2: hold/normal |
| JPP_RWhen | varchar (30) | VARCHAR2 (30 CHAR) | varchar(30) | varchar (30) | true | Possible success status of the line's precondition (e.g. ANY_OK, ENDED_SKIPPED, ENDED_NOT_OK). |
| JPP_RExecute | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Name of the object, that will be triggered, if the workflow task does not end successfully. |
| JPP_RElse | int | NUMBER(38,0) | int | int | true | Workflow action, that will be triggered, if the workflow task does not end successfully. 1 = halt, 2 = ignore, 3 = abend workflow |
| JPP_RRepMTimes | int | NUMBER(38,0) | int | int | true | Maximum number of repeats, if the workflow task does not end successfully. |
| JPP_RRepWait | int | NUMBER(38,0) | int | int | true | Wait time between retries in minutes. |
| JPP_MrtMethod | int | NUMBER(38,0) | int | int | true | Method for the maximum runtime. 0 = no audit, 1 = fix in seconds, 2 = fix time, 4 = ERT+xx%, 256 = Cancel, 512 = Start Object, 1024 = worflow overwrites object settings |
| JPP_Mrt | int | NUMBER(38,0) | int | int | true | Maximum runtime (MRT) in seconds. |
| JPP_MrtTime | char (6) | CHAR (6 CHAR) | char(6) | char (6) | true | Maxium runtime in time. Format: ddhhmm |
| JPP_MrtErt | smallint | NUMBER(38,0) | smallint | smallint | true | MRT = ERT + xx% |
| JPP_MrtExecute | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Object to start for runtime audit. |
| JPP_TcpATime | char (6) | CHAR (6 CHAR) | char(6) | char (6) | true | after time > time |
| JPP_TcpExecute | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Object to start. |
| JPP_Srt | int | NUMBER(38,0) | int | int | true | Shortest runtime (SRT) in seconds. |
| JPP_SrtErt | smallint | NUMBER(38,0) | smallint | smallint | true | SRT = ERT + xx% |
| JPP_TcpATimetTZ | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Timezone for time check point. |
| JPP_ErlstStTimeTZ | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Timezone for erleast start time. |
| JPP_LtstTimeTZ | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Timezone for latest time. |
| JPP_MrtTZ | varchar (8) | VARCHAR2 (8 CHAR) | varchar(8) | varchar (8) | true | Timezone for max. Runtime when a fixed time is used. |
| JPP_ConFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates whether or not the workflow task is connected to the end task. |
| JPP_RExecFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates when the alarm object is triggered. 0 = execute after each unsuccessful execution, 1 = execute only after all retries are unsuccessful |
| JPP_PreCntExt | smallint | NUMBER(38,0) | smallint | smallint | true | Number of external predecessors. |
| JPP_ParentObject | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Name of the workflow. (only for external dependencies) |
| JPP_ExtWhen | varchar (30) | VARCHAR2 (30 CHAR) | varchar(30) | varchar (30) | true | External Precondition: Possible success status (e.g. ANY_OK, ENDED_SKIPPED, ENDED_NOT_OK). |
| JPP_ExtSLTType | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | External Precondition: Type of the satisfaction lead time. 0 = since last run, 1 = after start of workflow, 2 = within time in seconds |
| JPP_ExtSLTWithin | int | NUMBER(38,0) | int | int | true | External Precondition: Time in seconds |
| JPP_ExtElse | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | External Precondition: Workflow action that is triggered, if the precondition fails. 0 = wait, 1 = skip, 2 = abend workflow |
| JPP_ExtElseAlarm | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | External Precondition: Indicates whether or not an alarm object is triggered, if the precondition fails. 0 = no, 1 = yes |
| JPP_ExtTimeout | int | NUMBER(38,0) | int | int | true | External Precondition: Timeout in seconds. |
| JPP_ExtTimeoutE | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | External Precondition: Workflow action that is triggered, if the precondition timeout occurs. 0 = wait, 1 = Skip, 2 = abend workflow |
| JPP_ExtTimeoutA | char (1) | CHAR (1 CHAR) | char(1) | char (1) | true | External Precondition: Indicates whether or not an alarm object is triggered, if the precondition timeout occurs. 0 = no, 1 = yes |
| JPP_ExtExecute | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | External Precondition: Name of the alarm object that is executed, if the precondition fails. |
| JPP_TimeoutFlag | smallint | NUMBER(38,0) | smallint | smallint | true | External Precondition: Indicates whether or not the AE checks for the timeout. 0 = off, 1 = on |
| JPP_JPPV_Flag | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates whether or not workflow task has object variables in its task properties. |
| JPP_PreCondFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates whether or not workflow task has preconditions. |
| JPP_PostCondFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates whether or not workflow task has postconditions. |
| JPP_Alias | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Display name of the workflow task. |
| JPP_ParentAlias | varchar (200) | VARCHAR2 (200 CHAR) | varchar(200) | varchar (200) | true | Display name of the workflow task in external dependencies. |
| JPP_ChildFlags | char (16) | CHAR (16 CHAR) | char(16) | char (16) | true | Flags for child tables. |
| JPP_ShowPrompt | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates whether or not prompts will be shown. |
| JPP_PromptAtGen | smallint | NUMBER(38,0) | smallint | smallint | true | Show prompt during workflow generation or workflow task generation. |
| JPP_BranchType | smallint | NUMBER(38,0) | smallint | smallint | true | Type of branch in case of a IF or FOREACH workflow. IF: 1 = true, 2 = false, FOREACH: 1 = loop path, 2 = end path |
| JPP_RunPerPatch | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates whether task is running per patch or not. |
| JPP_RollbackFlag | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates whether or not rollback is enabled for the workflow task. (overrides OH_RollbackFlag) |
| JPP_RunPerTarget | smallint | NUMBER(38,0) | smallint | smallint | true | Indicates how to run the workflow per deployment target. 1 = serial, 2 = parallel |

| Name | Fields | Primary | Unique | Clustered | Nonclustered |
| --- | --- | --- | --- | --- | --- |
| NK_JPP_ExtExecute | JPP_ExtExecute | false | false | false | false |
| NK_JPP_MrtExecute | JPP_MrtExecute | false | false | false | false |
| NK_JPP_Object | JPP_Object, JPP_OType | false | false | false | false |
| NK_JPP_ParObject | JPP_ParentObject | false | false | false | false |
| NK_JPP_RExecute | JPP_RExecute | false | false | false | false |
| NK_JPP_TcpExecute | JPP_TcpExecute | false | false | false | false |
| NK_JPP_WhenExecute | JPP_WhenExecute | false | false | false | false |
| PK_JPP | JPP_OH_Idnr, JPP_Lnr | true | true | true | false |
| NK_JPP_Alias | JPP_Alias, JPP_OType | false | false | false | false |
| NK_JPP_ParentAlias | JPP_ParentAlias, JPP_OType | false | false | false | false |

| Name | Local References | Foreign References |
| --- | --- | --- |
| FK_JPP_OH | JPP_OH_Idnr | OH_Idnr |