--
-- PostgreSQL database dump
--

-- Dumped from database version 15.13
-- Dumped by pg_dump version 15.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

--
-- Name: timescaledb; Type: EXTENSION; Schema: -; Owner: -
--

CREATE EXTENSION IF NOT EXISTS timescaledb WITH SCHEMA public;


--
-- Name: EXTENSION timescaledb; Type: COMMENT; Schema: -; Owner: 
--

COMMENT ON EXTENSION timescaledb IS 'Enables scalable inserts and complex queries for time-series data (Community Edition)';


--
-- Name: hypervisortype; Type: TYPE; Schema: public; Owner: postgres
--

CREATE TYPE public.hypervisortype AS ENUM (
    'VMWARE',
    'HYPERV',
    'KVM',
    'XEN'
);


ALTER TYPE public.hypervisortype OWNER TO postgres;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: metric_data; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.metric_data (
    id integer,
    server_id integer NOT NULL,
    metric_name character varying(255) NOT NULL,
    value double precision NOT NULL,
    unit character varying(50),
    labels text,
    "timestamp" timestamp with time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.metric_data OWNER TO postgres;

--
-- Name: _direct_view_6; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._direct_view_6 AS
 SELECT metric_data.server_id,
    metric_data.metric_name,
    public.time_bucket('01:00:00'::interval, metric_data."timestamp") AS bucket,
    avg(metric_data.value) AS avg_value,
    min(metric_data.value) AS min_value,
    max(metric_data.value) AS max_value,
    count(*) AS count
   FROM public.metric_data
  GROUP BY metric_data.server_id, metric_data.metric_name, (public.time_bucket('01:00:00'::interval, metric_data."timestamp"));


ALTER TABLE _timescaledb_internal._direct_view_6 OWNER TO postgres;

--
-- Name: _hyper_5_1_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._hyper_5_1_chunk (
    CONSTRAINT constraint_1 CHECK ((("timestamp" >= '2026-02-23 00:00:00+00'::timestamp with time zone) AND ("timestamp" < '2026-02-24 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.metric_data);


ALTER TABLE _timescaledb_internal._hyper_5_1_chunk OWNER TO postgres;

--
-- Name: _hyper_5_3_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._hyper_5_3_chunk (
    CONSTRAINT constraint_3 CHECK ((("timestamp" >= '2026-02-24 00:00:00+00'::timestamp with time zone) AND ("timestamp" < '2026-02-25 00:00:00+00'::timestamp with time zone)))
)
INHERITS (public.metric_data);


ALTER TABLE _timescaledb_internal._hyper_5_3_chunk OWNER TO postgres;

--
-- Name: _materialized_hypertable_6; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._materialized_hypertable_6 (
    server_id integer,
    metric_name character varying(255),
    bucket timestamp with time zone NOT NULL,
    avg_value double precision,
    min_value double precision,
    max_value double precision,
    count bigint
);


ALTER TABLE _timescaledb_internal._materialized_hypertable_6 OWNER TO postgres;

--
-- Name: _hyper_6_2_chunk; Type: TABLE; Schema: _timescaledb_internal; Owner: postgres
--

CREATE TABLE _timescaledb_internal._hyper_6_2_chunk (
    CONSTRAINT constraint_2 CHECK (((bucket >= '2026-02-16 00:00:00+00'::timestamp with time zone) AND (bucket < '2026-02-26 00:00:00+00'::timestamp with time zone)))
)
INHERITS (_timescaledb_internal._materialized_hypertable_6);


ALTER TABLE _timescaledb_internal._hyper_6_2_chunk OWNER TO postgres;

--
-- Name: _partial_view_6; Type: VIEW; Schema: _timescaledb_internal; Owner: postgres
--

CREATE VIEW _timescaledb_internal._partial_view_6 AS
 SELECT metric_data.server_id,
    metric_data.metric_name,
    public.time_bucket('01:00:00'::interval, metric_data."timestamp") AS bucket,
    avg(metric_data.value) AS avg_value,
    min(metric_data.value) AS min_value,
    max(metric_data.value) AS max_value,
    count(*) AS count
   FROM public.metric_data
  GROUP BY metric_data.server_id, metric_data.metric_name, (public.time_bucket('01:00:00'::interval, metric_data."timestamp"));


ALTER TABLE _timescaledb_internal._partial_view_6 OWNER TO postgres;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO postgres;

--
-- Name: alerts; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.alerts (
    id integer NOT NULL,
    server_id integer,
    alert_type character varying(100) NOT NULL,
    severity character varying(20),
    title character varying(500) NOT NULL,
    description text,
    metric_name character varying(200),
    metric_value double precision,
    threshold_value double precision,
    is_active boolean,
    fired_at timestamp with time zone DEFAULT now(),
    resolved_at timestamp with time zone
);


ALTER TABLE public.alerts OWNER TO postgres;

--
-- Name: alerts_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.alerts_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.alerts_id_seq OWNER TO postgres;

--
-- Name: alerts_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.alerts_id_seq OWNED BY public.alerts.id;


--
-- Name: baseline_metrics; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.baseline_metrics (
    id integer NOT NULL,
    server_id integer,
    metric_name character varying(200) NOT NULL,
    avg_value double precision,
    min_value double precision,
    max_value double precision,
    std_dev double precision,
    percentile_95 double precision,
    sample_count integer,
    period character varying(50),
    calculated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.baseline_metrics OWNER TO postgres;

--
-- Name: baseline_metrics_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.baseline_metrics_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.baseline_metrics_id_seq OWNER TO postgres;

--
-- Name: baseline_metrics_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.baseline_metrics_id_seq OWNED BY public.baseline_metrics.id;


--
-- Name: chat_messages; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.chat_messages (
    id integer NOT NULL,
    session_id integer NOT NULL,
    role character varying(20) NOT NULL,
    content text NOT NULL,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.chat_messages OWNER TO postgres;

--
-- Name: chat_messages_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.chat_messages_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.chat_messages_id_seq OWNER TO postgres;

--
-- Name: chat_messages_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.chat_messages_id_seq OWNED BY public.chat_messages.id;


--
-- Name: chat_sessions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.chat_sessions (
    id integer NOT NULL,
    title character varying(255) NOT NULL,
    server_ids json,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.chat_sessions OWNER TO postgres;

--
-- Name: chat_sessions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.chat_sessions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.chat_sessions_id_seq OWNER TO postgres;

--
-- Name: chat_sessions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.chat_sessions_id_seq OWNED BY public.chat_sessions.id;


--
-- Name: global_credentials; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.global_credentials (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    username character varying(255) NOT NULL,
    password character varying(512),
    private_key text,
    sudo_password character varying(512),
    port integer,
    is_default boolean,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone
);


ALTER TABLE public.global_credentials OWNER TO postgres;

--
-- Name: global_credentials_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.global_credentials_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.global_credentials_id_seq OWNER TO postgres;

--
-- Name: global_credentials_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.global_credentials_id_seq OWNED BY public.global_credentials.id;


--
-- Name: hypervisors; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.hypervisors (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    hypervisor_type public.hypervisortype NOT NULL,
    hostname character varying(255) NOT NULL,
    ip_address character varying(45) NOT NULL,
    port integer,
    username character varying(255),
    password character varying(255),
    connection_config json NOT NULL,
    status character varying(50),
    last_sync timestamp with time zone,
    meta_data json,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone
);


ALTER TABLE public.hypervisors OWNER TO postgres;

--
-- Name: hypervisors_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.hypervisors_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.hypervisors_id_seq OWNER TO postgres;

--
-- Name: hypervisors_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.hypervisors_id_seq OWNED BY public.hypervisors.id;


--
-- Name: incidents; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.incidents (
    id integer NOT NULL,
    title character varying(500) NOT NULL,
    description text,
    severity character varying(20),
    status character varying(50),
    source character varying(100),
    affected_servers json,
    related_events json,
    root_cause text,
    resolution text,
    rca_result json,
    assigned_to character varying(100),
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    resolved_at timestamp with time zone
);


ALTER TABLE public.incidents OWNER TO postgres;

--
-- Name: incidents_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.incidents_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.incidents_id_seq OWNER TO postgres;

--
-- Name: incidents_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.incidents_id_seq OWNED BY public.incidents.id;


--
-- Name: metric_aggregations; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.metric_aggregations (
    id integer NOT NULL,
    server_id integer NOT NULL,
    metric_name character varying(255) NOT NULL,
    period character varying(20) NOT NULL,
    period_start timestamp with time zone NOT NULL,
    avg_value double precision,
    min_value double precision,
    max_value double precision,
    sum_value double precision,
    count integer,
    unit character varying(50),
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.metric_aggregations OWNER TO postgres;

--
-- Name: metric_aggregations_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.metric_aggregations_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.metric_aggregations_id_seq OWNER TO postgres;

--
-- Name: metric_aggregations_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.metric_aggregations_id_seq OWNED BY public.metric_aggregations.id;


--
-- Name: metric_data_hourly; Type: VIEW; Schema: public; Owner: postgres
--

CREATE VIEW public.metric_data_hourly AS
 SELECT _materialized_hypertable_6.server_id,
    _materialized_hypertable_6.metric_name,
    _materialized_hypertable_6.bucket,
    _materialized_hypertable_6.avg_value,
    _materialized_hypertable_6.min_value,
    _materialized_hypertable_6.max_value,
    _materialized_hypertable_6.count
   FROM _timescaledb_internal._materialized_hypertable_6;


ALTER TABLE public.metric_data_hourly OWNER TO postgres;

--
-- Name: metric_thresholds; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.metric_thresholds (
    id integer NOT NULL,
    server_id integer,
    metric_name character varying(255) NOT NULL,
    warning_threshold double precision,
    critical_threshold double precision,
    operator character varying(10),
    duration_seconds integer,
    enabled integer,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone
);


ALTER TABLE public.metric_thresholds OWNER TO postgres;

--
-- Name: metric_thresholds_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.metric_thresholds_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.metric_thresholds_id_seq OWNER TO postgres;

--
-- Name: metric_thresholds_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.metric_thresholds_id_seq OWNED BY public.metric_thresholds.id;


--
-- Name: runbook_executions; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.runbook_executions (
    id integer NOT NULL,
    server_id integer,
    incident_id integer,
    runbook_name character varying(200) NOT NULL,
    trigger_type character varying(50),
    status character varying(50),
    steps_total integer,
    steps_completed integer,
    output text,
    error text,
    started_at timestamp with time zone DEFAULT now(),
    completed_at timestamp with time zone
);


ALTER TABLE public.runbook_executions OWNER TO postgres;

--
-- Name: runbook_executions_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.runbook_executions_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.runbook_executions_id_seq OWNER TO postgres;

--
-- Name: runbook_executions_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.runbook_executions_id_seq OWNED BY public.runbook_executions.id;


--
-- Name: servers; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.servers (
    id integer NOT NULL,
    name character varying(255) NOT NULL,
    hostname character varying(255),
    ip_address character varying(45),
    status character varying(50),
    os_type character varying(50),
    os_version character varying(255),
    server_type character varying(50),
    cpu_cores integer,
    memory_gb integer,
    ai_ready boolean,
    connection_config json,
    created_at timestamp with time zone DEFAULT now(),
    updated_at timestamp with time zone,
    node_exporter_installed boolean DEFAULT false,
    node_exporter_running boolean DEFAULT false,
    node_exporter_last_check timestamp with time zone,
    hypervisor_id integer,
    hypervisor_vm_id character varying(255)
);


ALTER TABLE public.servers OWNER TO postgres;

--
-- Name: servers_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.servers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.servers_id_seq OWNER TO postgres;

--
-- Name: servers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.servers_id_seq OWNED BY public.servers.id;


--
-- Name: system_events; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.system_events (
    id integer NOT NULL,
    server_id integer,
    event_type character varying(100) NOT NULL,
    severity character varying(20),
    source character varying(100),
    title character varying(500) NOT NULL,
    description text,
    raw_data json,
    is_acknowledged boolean,
    acknowledged_by character varying(100),
    acknowledged_at timestamp with time zone,
    resolved boolean,
    resolved_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now()
);


ALTER TABLE public.system_events OWNER TO postgres;

--
-- Name: system_events_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.system_events_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER TABLE public.system_events_id_seq OWNER TO postgres;

--
-- Name: system_events_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.system_events_id_seq OWNED BY public.system_events.id;


--
-- Name: _hyper_5_1_chunk timestamp; Type: DEFAULT; Schema: _timescaledb_internal; Owner: postgres
--

ALTER TABLE ONLY _timescaledb_internal._hyper_5_1_chunk ALTER COLUMN "timestamp" SET DEFAULT now();


--
-- Name: _hyper_5_3_chunk timestamp; Type: DEFAULT; Schema: _timescaledb_internal; Owner: postgres
--

ALTER TABLE ONLY _timescaledb_internal._hyper_5_3_chunk ALTER COLUMN "timestamp" SET DEFAULT now();


--
-- Name: alerts id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alerts ALTER COLUMN id SET DEFAULT nextval('public.alerts_id_seq'::regclass);


--
-- Name: baseline_metrics id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baseline_metrics ALTER COLUMN id SET DEFAULT nextval('public.baseline_metrics_id_seq'::regclass);


--
-- Name: chat_messages id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.chat_messages ALTER COLUMN id SET DEFAULT nextval('public.chat_messages_id_seq'::regclass);


--
-- Name: chat_sessions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.chat_sessions ALTER COLUMN id SET DEFAULT nextval('public.chat_sessions_id_seq'::regclass);


--
-- Name: global_credentials id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.global_credentials ALTER COLUMN id SET DEFAULT nextval('public.global_credentials_id_seq'::regclass);


--
-- Name: hypervisors id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.hypervisors ALTER COLUMN id SET DEFAULT nextval('public.hypervisors_id_seq'::regclass);


--
-- Name: incidents id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.incidents ALTER COLUMN id SET DEFAULT nextval('public.incidents_id_seq'::regclass);


--
-- Name: metric_aggregations id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metric_aggregations ALTER COLUMN id SET DEFAULT nextval('public.metric_aggregations_id_seq'::regclass);


--
-- Name: metric_thresholds id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metric_thresholds ALTER COLUMN id SET DEFAULT nextval('public.metric_thresholds_id_seq'::regclass);


--
-- Name: runbook_executions id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.runbook_executions ALTER COLUMN id SET DEFAULT nextval('public.runbook_executions_id_seq'::regclass);


--
-- Name: servers id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.servers ALTER COLUMN id SET DEFAULT nextval('public.servers_id_seq'::regclass);


--
-- Name: system_events id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_events ALTER COLUMN id SET DEFAULT nextval('public.system_events_id_seq'::regclass);


--
-- Data for Name: hypertable; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.hypertable (id, schema_name, table_name, associated_schema_name, associated_table_prefix, num_dimensions, chunk_sizing_func_schema, chunk_sizing_func_name, chunk_target_size, compression_state, compressed_hypertable_id, status) FROM stdin;
5	public	metric_data	_timescaledb_internal	_hyper_5	1	_timescaledb_functions	calculate_chunk_interval	0	0	\N	0
6	_timescaledb_internal	_materialized_hypertable_6	_timescaledb_internal	_hyper_6	1	_timescaledb_functions	calculate_chunk_interval	0	0	\N	0
\.


--
-- Data for Name: chunk; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.chunk (id, hypertable_id, schema_name, table_name, compressed_chunk_id, dropped, status, osm_chunk, creation_time) FROM stdin;
1	5	_timescaledb_internal	_hyper_5_1_chunk	\N	f	0	f	2026-02-23 20:56:47.523198+00
2	6	_timescaledb_internal	_hyper_6_2_chunk	\N	f	0	f	2026-02-23 22:22:04.780552+00
3	5	_timescaledb_internal	_hyper_5_3_chunk	\N	f	0	f	2026-02-24 00:06:57.12689+00
\.


--
-- Data for Name: chunk_column_stats; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.chunk_column_stats (id, hypertable_id, chunk_id, column_name, range_start, range_end, valid) FROM stdin;
\.


--
-- Data for Name: dimension; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.dimension (id, hypertable_id, column_name, column_type, aligned, num_slices, partitioning_func_schema, partitioning_func, interval_length, compress_interval_length, integer_now_func_schema, integer_now_func) FROM stdin;
5	5	timestamp	timestamp with time zone	t	\N	\N	\N	86400000000	\N	\N	\N
6	6	bucket	timestamp with time zone	t	\N	\N	\N	864000000000	\N	\N	\N
\.


--
-- Data for Name: dimension_slice; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.dimension_slice (id, dimension_id, range_start, range_end) FROM stdin;
1	5	1771804800000000	1771891200000000
2	6	1771200000000000	1772064000000000
3	5	1771891200000000	1771977600000000
\.


--
-- Data for Name: chunk_constraint; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.chunk_constraint (chunk_id, dimension_slice_id, constraint_name, hypertable_constraint_name) FROM stdin;
1	1	constraint_1	\N
1	\N	1_1_metric_data_pkey	metric_data_pkey
1	\N	1_2_metric_data_server_id_fkey	metric_data_server_id_fkey
2	2	constraint_2	\N
3	3	constraint_3	\N
3	\N	3_3_metric_data_pkey	metric_data_pkey
3	\N	3_4_metric_data_server_id_fkey	metric_data_server_id_fkey
\.


--
-- Data for Name: compression_chunk_size; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.compression_chunk_size (chunk_id, compressed_chunk_id, uncompressed_heap_size, uncompressed_toast_size, uncompressed_index_size, compressed_heap_size, compressed_toast_size, compressed_index_size, numrows_pre_compression, numrows_post_compression, numrows_frozen_immediately) FROM stdin;
\.


--
-- Data for Name: compression_settings; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.compression_settings (relid, compress_relid, segmentby, orderby, orderby_desc, orderby_nullsfirst, index) FROM stdin;
\.


--
-- Data for Name: continuous_agg; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.continuous_agg (mat_hypertable_id, raw_hypertable_id, parent_mat_hypertable_id, user_view_schema, user_view_name, partial_view_schema, partial_view_name, direct_view_schema, direct_view_name, materialized_only, finalized) FROM stdin;
6	5	\N	public	metric_data_hourly	_timescaledb_internal	_partial_view_6	_timescaledb_internal	_direct_view_6	t	t
\.


--
-- Data for Name: continuous_agg_migrate_plan; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.continuous_agg_migrate_plan (mat_hypertable_id, start_ts, end_ts, user_view_definition) FROM stdin;
\.


--
-- Data for Name: continuous_agg_migrate_plan_step; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.continuous_agg_migrate_plan_step (mat_hypertable_id, step_id, status, start_ts, end_ts, type, config) FROM stdin;
\.


--
-- Data for Name: continuous_aggs_bucket_function; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.continuous_aggs_bucket_function (mat_hypertable_id, bucket_func, bucket_width, bucket_origin, bucket_offset, bucket_timezone, bucket_fixed_width) FROM stdin;
6	public.time_bucket(interval,timestamp with time zone)	01:00:00	\N	\N	\N	t
\.


--
-- Data for Name: continuous_aggs_hypertable_invalidation_log; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.continuous_aggs_hypertable_invalidation_log (hypertable_id, lowest_modified_value, greatest_modified_value) FROM stdin;
\.


--
-- Data for Name: continuous_aggs_invalidation_threshold; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.continuous_aggs_invalidation_threshold (hypertable_id, watermark) FROM stdin;
5	1771923600000000
\.


--
-- Data for Name: continuous_aggs_materialization_invalidation_log; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.continuous_aggs_materialization_invalidation_log (materialization_id, lowest_modified_value, greatest_modified_value) FROM stdin;
6	-9223372036854775808	1770803999999999
6	1771923600000000	9223372036854775807
\.


--
-- Data for Name: continuous_aggs_materialization_ranges; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.continuous_aggs_materialization_ranges (materialization_id, lowest_modified_value, greatest_modified_value) FROM stdin;
\.


--
-- Data for Name: continuous_aggs_watermark; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.continuous_aggs_watermark (mat_hypertable_id, watermark) FROM stdin;
6	1771923600000000
\.


--
-- Data for Name: metadata; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.metadata (key, value, include_in_telemetry) FROM stdin;
install_timestamp	2026-02-11 12:17:47.762287+00	t
timescaledb_version	2.24.0	f
exported_uuid	cd4033a1-3dd6-4534-af83-a608bce01a7b	t
\.


--
-- Data for Name: tablespace; Type: TABLE DATA; Schema: _timescaledb_catalog; Owner: postgres
--

COPY _timescaledb_catalog.tablespace (id, hypertable_id, tablespace_name) FROM stdin;
\.


--
-- Data for Name: bgw_job; Type: TABLE DATA; Schema: _timescaledb_config; Owner: postgres
--

COPY _timescaledb_config.bgw_job (id, application_name, schedule_interval, max_runtime, max_retries, retry_period, proc_schema, proc_name, owner, scheduled, fixed_schedule, initial_start, hypertable_id, config, check_schema, check_name, timezone) FROM stdin;
1000	Refresh Continuous Aggregate Policy [1000]	01:00:00	00:00:00	-1	01:00:00	_timescaledb_functions	policy_refresh_continuous_aggregate	postgres	t	f	\N	6	{"end_offset": "01:00:00", "start_offset": "03:00:00", "mat_hypertable_id": 6}	_timescaledb_functions	policy_refresh_continuous_aggregate_check	\N
1001	Retention Policy [1001]	1 day	00:05:00	-1	00:05:00	_timescaledb_functions	policy_retention	postgres	t	f	\N	5	{"drop_after": "30 days", "hypertable_id": 5}	_timescaledb_functions	policy_retention_check	\N
\.


--
-- Data for Name: _hyper_5_1_chunk; Type: TABLE DATA; Schema: _timescaledb_internal; Owner: postgres
--

COPY _timescaledb_internal._hyper_5_1_chunk (id, server_id, metric_name, value, unit, labels, "timestamp") FROM stdin;
\N	133	cpu_usage_percent	0.4820175438286185	percent	\N	2026-02-23 20:44:47.498+00
\N	133	cpu_usage_percent	0.4745614035627028	percent	\N	2026-02-23 20:45:47.498+00
\N	133	cpu_usage_percent	0.7083333333088433	percent	\N	2026-02-23 20:46:47.498+00
\N	133	cpu_usage_percent	0.5859649122954096	percent	\N	2026-02-23 20:47:47.498+00
\N	133	cpu_usage_percent	0.5807017543957897	percent	\N	2026-02-23 20:48:47.498+00
\N	133	cpu_usage_percent	0.589035087706236	percent	\N	2026-02-23 20:49:47.498+00
\N	133	cpu_usage_percent	0.3657894737185359	percent	\N	2026-02-23 20:50:47.498+00
\N	133	cpu_usage_percent	0.35350877191186214	percent	\N	2026-02-23 20:51:47.498+00
\N	133	cpu_usage_percent	0.4649122806445831	percent	\N	2026-02-23 20:52:47.498+00
\N	133	cpu_usage_percent	0.473684210518158	percent	\N	2026-02-23 20:53:47.498+00
\N	133	cpu_usage_percent	0.47850877193637587	percent	\N	2026-02-23 20:54:47.498+00
\N	133	cpu_usage_percent	0.48508771940282713	percent	\N	2026-02-23 20:55:47.498+00
\N	133	cpu_usage_percent	0.49780701748667866	percent	\N	2026-02-23 20:56:47.498+00
\N	133	cpu_usage_percent	9.11403508771113	percent	\N	2026-02-23 21:04:48.39+00
\N	133	cpu_usage_percent	9.105701754278144	percent	\N	2026-02-23 21:05:48.39+00
\N	133	cpu_usage_percent	6.574122807084535	percent	\N	2026-02-23 21:06:48.39+00
\N	133	cpu_usage_percent	3.844298245589542	percent	\N	2026-02-23 21:07:48.39+00
\N	133	cpu_usage_percent	1.4434210526381293	percent	\N	2026-02-23 21:08:48.39+00
\N	133	cpu_usage_percent	0.7907894737365098	percent	\N	2026-02-23 21:09:48.39+00
\N	133	cpu_usage_percent	0.43815789478750844	percent	\N	2026-02-23 21:10:48.39+00
\N	236	cpu_usage_percent	1.607017543885803	percent	\N	2026-02-23 20:44:47.613+00
\N	236	cpu_usage_percent	1.564912280688688	percent	\N	2026-02-23 20:45:47.613+00
\N	236	cpu_usage_percent	2.038596491247688	percent	\N	2026-02-23 20:46:47.613+00
\N	236	cpu_usage_percent	1.9263157895521203	percent	\N	2026-02-23 20:47:47.613+00
\N	236	cpu_usage_percent	1.8982456140873865	percent	\N	2026-02-23 20:48:47.613+00
\N	236	cpu_usage_percent	1.9052631579535557	percent	\N	2026-02-23 20:49:47.613+00
\N	236	cpu_usage_percent	1.4526315788297381	percent	\N	2026-02-23 20:50:47.613+00
\N	236	cpu_usage_percent	1.4385964912607534	percent	\N	2026-02-23 20:51:47.613+00
\N	236	cpu_usage_percent	1.5894736843020354	percent	\N	2026-02-23 20:52:47.613+00
\N	236	cpu_usage_percent	1.617543859603387	percent	\N	2026-02-23 20:53:47.613+00
\N	236	cpu_usage_percent	1.617543859603387	percent	\N	2026-02-23 20:54:47.613+00
\N	236	cpu_usage_percent	1.6000000000196195	percent	\N	2026-02-23 20:55:47.613+00
\N	236	cpu_usage_percent	1.5964912280048225	percent	\N	2026-02-23 20:56:47.613+00
\N	133	cpu_usage_percent	0.3302631579061881	percent	\N	2026-02-23 21:11:48.39+00
\N	133	cpu_usage_percent	0.43114035075792856	percent	\N	2026-02-23 21:12:48.39+00
\N	133	cpu_usage_percent	0.546929824509121	percent	\N	2026-02-23 21:13:48.39+00
\N	133	cpu_usage_percent	0.5508771929644922	percent	\N	2026-02-23 21:14:48.39+00
\N	133	cpu_usage_percent	0.5447368421836956	percent	\N	2026-02-23 21:15:48.39+00
\N	133	cpu_usage_percent	0.4368421052615332	percent	\N	2026-02-23 21:16:48.39+00
\N	133	cpu_usage_percent	0.5385964912803587	percent	\N	2026-02-23 21:34:49.596+00
\N	248	cpu_usage_percent	2.682017543835144	percent	\N	2026-02-23 20:44:47.686+00
\N	248	cpu_usage_percent	2.669298245587896	percent	\N	2026-02-23 20:45:47.686+00
\N	248	cpu_usage_percent	2.8377192982537878	percent	\N	2026-02-23 20:46:47.686+00
\N	248	cpu_usage_percent	2.728947368409635	percent	\N	2026-02-23 20:47:47.686+00
\N	248	cpu_usage_percent	2.5789473683311996	percent	\N	2026-02-23 20:48:47.686+00
\N	248	cpu_usage_percent	2.5350877192900896	percent	\N	2026-02-23 20:49:47.686+00
\N	248	cpu_usage_percent	2.3671052631873124	percent	\N	2026-02-23 20:50:47.686+00
\N	248	cpu_usage_percent	2.3885964912672932	percent	\N	2026-02-23 20:51:47.686+00
\N	248	cpu_usage_percent	2.4749999999869345	percent	\N	2026-02-23 20:52:47.686+00
\N	248	cpu_usage_percent	2.5223684210836836	percent	\N	2026-02-23 20:53:47.686+00
\N	248	cpu_usage_percent	2.612719298176998	percent	\N	2026-02-23 20:54:47.686+00
\N	248	cpu_usage_percent	2.5929824560635666	percent	\N	2026-02-23 20:55:47.686+00
\N	248	cpu_usage_percent	2.557456140292075	percent	\N	2026-02-23 20:56:47.686+00
\N	133	cpu_usage_percent	0.5442982455797392	percent	\N	2026-02-23 21:35:49.596+00
\N	133	cpu_usage_percent	0.5324561403770218	percent	\N	2026-02-23 21:36:49.596+00
\N	133	cpu_usage_percent	0.43728070174296363	percent	\N	2026-02-23 21:37:49.596+00
\N	133	cpu_usage_percent	0.4346491228135676	percent	\N	2026-02-23 21:38:49.596+00
\N	133	cpu_usage_percent	0.43070175435819635	percent	\N	2026-02-23 21:39:49.596+00
\N	133	cpu_usage_percent	0.4250000000179881	percent	\N	2026-02-23 21:40:49.596+00
\N	236	cpu_usage_percent	1.561403508673905	percent	\N	2026-02-23 21:04:48.452+00
\N	252	cpu_usage_percent	26.500438596530458	percent	\N	2026-02-23 20:44:47.746+00
\N	252	cpu_usage_percent	26.742543859607466	percent	\N	2026-02-23 20:45:47.746+00
\N	252	cpu_usage_percent	26.91929824560424	percent	\N	2026-02-23 20:46:47.746+00
\N	252	cpu_usage_percent	26.78552631578785	percent	\N	2026-02-23 20:47:47.746+00
\N	252	cpu_usage_percent	26.55570175439496	percent	\N	2026-02-23 20:48:47.746+00
\N	252	cpu_usage_percent	26.532017543867013	percent	\N	2026-02-23 20:49:47.746+00
\N	252	cpu_usage_percent	26.25043859650185	percent	\N	2026-02-23 20:50:47.746+00
\N	252	cpu_usage_percent	26.25175438594613	percent	\N	2026-02-23 20:51:47.746+00
\N	252	cpu_usage_percent	26.291228070213847	percent	\N	2026-02-23 20:52:47.746+00
\N	252	cpu_usage_percent	26.33552631579765	percent	\N	2026-02-23 20:53:47.746+00
\N	252	cpu_usage_percent	26.18991228069686	percent	\N	2026-02-23 20:54:47.746+00
\N	252	cpu_usage_percent	26.14078947371526	percent	\N	2026-02-23 20:55:47.746+00
\N	252	cpu_usage_percent	26.159649122865844	percent	\N	2026-02-23 20:56:47.746+00
\N	236	cpu_usage_percent	1.5473684209415381	percent	\N	2026-02-23 21:05:48.452+00
\N	236	cpu_usage_percent	1.631578947335754	percent	\N	2026-02-23 21:06:48.452+00
\N	236	cpu_usage_percent	1.4666666667255015	percent	\N	2026-02-23 21:07:48.452+00
\N	236	cpu_usage_percent	1.43157894739457	percent	\N	2026-02-23 21:08:48.452+00
\N	236	cpu_usage_percent	1.4385964912607534	percent	\N	2026-02-23 21:09:48.452+00
\N	236	cpu_usage_percent	1.4385964912607534	percent	\N	2026-02-23 21:10:48.452+00
\N	236	cpu_usage_percent	1.256140350903351	percent	\N	2026-02-23 21:11:48.452+00
\N	257	cpu_usage_percent	4.435087719303155	percent	\N	2026-02-23 20:44:47.812+00
\N	257	cpu_usage_percent	4.235087719300708	percent	\N	2026-02-23 20:45:47.812+00
\N	257	cpu_usage_percent	4.71842105264507	percent	\N	2026-02-23 20:46:47.812+00
\N	257	cpu_usage_percent	4.712280701751951	percent	\N	2026-02-23 20:47:47.812+00
\N	257	cpu_usage_percent	5.151754385963287	percent	\N	2026-02-23 20:48:47.812+00
\N	257	cpu_usage_percent	5.5736842105193745	percent	\N	2026-02-23 20:49:47.812+00
\N	257	cpu_usage_percent	5.927192982451658	percent	\N	2026-02-23 20:50:47.812+00
\N	257	cpu_usage_percent	5.429824561405567	percent	\N	2026-02-23 20:51:47.812+00
\N	257	cpu_usage_percent	5.299122807010207	percent	\N	2026-02-23 20:52:47.812+00
\N	257	cpu_usage_percent	4.88771929826359	percent	\N	2026-02-23 20:53:47.812+00
\N	257	cpu_usage_percent	4.43859649123624	percent	\N	2026-02-23 20:54:47.812+00
\N	257	cpu_usage_percent	4.208771929833148	percent	\N	2026-02-23 20:55:47.812+00
\N	257	cpu_usage_percent	4.196491228067316	percent	\N	2026-02-23 20:56:47.812+00
\N	236	cpu_usage_percent	1.4456140351269369	percent	\N	2026-02-23 21:12:48.452+00
\N	236	cpu_usage_percent	1.6140350877519865	percent	\N	2026-02-23 21:13:48.452+00
\N	236	cpu_usage_percent	1.6315789474991504	percent	\N	2026-02-23 21:14:48.452+00
\N	236	cpu_usage_percent	1.631578947335754	percent	\N	2026-02-23 21:15:48.452+00
\N	236	cpu_usage_percent	1.5052631579078195	percent	\N	2026-02-23 21:16:48.452+00
\N	133	cpu_usage_percent	0.42894736839164693	percent	\N	2026-02-23 21:41:49.596+00
\N	133	cpu_usage_percent	0.43070175439903835	percent	\N	2026-02-23 21:42:49.596+00
\N	260	cpu_usage_percent	87.65826887965989	percent	\N	2026-02-23 20:46:47.894+00
\N	260	cpu_usage_percent	79.36629534923446	percent	\N	2026-02-23 20:47:47.894+00
\N	260	cpu_usage_percent	68.02185415151558	percent	\N	2026-02-23 20:48:47.894+00
\N	260	cpu_usage_percent	52.450469957874134	percent	\N	2026-02-23 20:49:47.894+00
\N	260	cpu_usage_percent	37.60888157896453	percent	\N	2026-02-23 20:50:47.894+00
\N	133	cpu_usage_percent	0.4995614034532281	percent	\N	2026-02-23 21:43:49.596+00
\N	133	cpu_usage_percent	0.5004385964977729	percent	\N	2026-02-23 21:44:49.596+00
\N	260	cpu_usage_percent	33.21710526312114	percent	\N	2026-02-23 20:51:47.894+00
\N	260	cpu_usage_percent	26.45438596493925	percent	\N	2026-02-23 20:52:47.894+00
\N	260	cpu_usage_percent	23.955592105242744	percent	\N	2026-02-23 20:53:47.894+00
\N	260	cpu_usage_percent	24.037938596509207	percent	\N	2026-02-23 20:54:47.894+00
\N	260	cpu_usage_percent	24.02971491221699	percent	\N	2026-02-23 20:55:47.894+00
\N	260	cpu_usage_percent	24.0846491227817	percent	\N	2026-02-23 20:56:47.894+00
\N	133	cpu_usage_percent	0.4934210526724314	percent	\N	2026-02-23 21:45:49.596+00
\N	133	cpu_usage_percent	0.513596491185595	percent	\N	2026-02-23 21:46:49.596+00
\N	133	cpu_usage_percent	0.6131578947564549	percent	\N	2026-02-23 22:24:51.652+00
\N	133	cpu_usage_percent	0.5785087719886661	percent	\N	2026-02-23 22:25:51.652+00
\N	248	cpu_usage_percent	3.393859649117914	percent	\N	2026-02-23 21:04:48.514+00
\N	248	cpu_usage_percent	2.6206140350877263	percent	\N	2026-02-23 21:05:48.514+00
\N	248	cpu_usage_percent	2.5092105263550053	percent	\N	2026-02-23 21:06:48.514+00
\N	133	cpu_usage_percent	0.47850877193637587	percent	\N	2026-02-23 20:54:47.984+00
\N	133	cpu_usage_percent	0.48508771940282713	percent	\N	2026-02-23 20:55:47.984+00
\N	133	cpu_usage_percent	0.49780701748667866	percent	\N	2026-02-23 20:56:47.984+00
\N	133	cpu_usage_percent	0.3701754386144671	percent	\N	2026-02-23 20:57:47.984+00
\N	133	cpu_usage_percent	0.3662280701591101	percent	\N	2026-02-23 20:58:47.984+00
\N	133	cpu_usage_percent	0.3688596491701901	percent	\N	2026-02-23 20:59:47.984+00
\N	133	cpu_usage_percent	0.9337719298670493	percent	\N	2026-02-23 21:00:47.984+00
\N	133	cpu_usage_percent	3.371929824556503	percent	\N	2026-02-23 21:01:47.984+00
\N	133	cpu_usage_percent	6.023684210519789	percent	\N	2026-02-23 21:02:47.984+00
\N	133	cpu_usage_percent	8.679824561379007	percent	\N	2026-02-23 21:03:47.984+00
\N	133	cpu_usage_percent	9.11403508771113	percent	\N	2026-02-23 21:04:47.984+00
\N	133	cpu_usage_percent	9.105701754278144	percent	\N	2026-02-23 21:05:47.984+00
\N	133	cpu_usage_percent	6.574122807084535	percent	\N	2026-02-23 21:06:47.984+00
\N	248	cpu_usage_percent	2.6289473683981868	percent	\N	2026-02-23 21:07:48.514+00
\N	248	cpu_usage_percent	2.616228070150939	percent	\N	2026-02-23 21:08:48.514+00
\N	248	cpu_usage_percent	2.6017543859371557	percent	\N	2026-02-23 21:09:48.514+00
\N	248	cpu_usage_percent	2.704824561400258	percent	\N	2026-02-23 21:10:48.514+00
\N	248	cpu_usage_percent	2.56140350870659	percent	\N	2026-02-23 21:11:48.514+00
\N	248	cpu_usage_percent	2.4859649123084893	percent	\N	2026-02-23 21:12:48.514+00
\N	248	cpu_usage_percent	2.4403508772191316	percent	\N	2026-02-23 21:13:48.514+00
\N	236	cpu_usage_percent	1.617543859603387	percent	\N	2026-02-23 20:54:48.051+00
\N	236	cpu_usage_percent	1.6000000000196195	percent	\N	2026-02-23 20:55:48.051+00
\N	236	cpu_usage_percent	1.5964912280048225	percent	\N	2026-02-23 20:56:48.051+00
\N	236	cpu_usage_percent	1.428070175379787	percent	\N	2026-02-23 20:57:48.051+00
\N	236	cpu_usage_percent	1.3719298246136873	percent	\N	2026-02-23 20:58:48.051+00
\N	236	cpu_usage_percent	1.3684210527623009	percent	\N	2026-02-23 20:59:48.051+00
\N	236	cpu_usage_percent	1.3684210527623009	percent	\N	2026-02-23 21:00:48.051+00
\N	236	cpu_usage_percent	1.4315789472311877	percent	\N	2026-02-23 21:01:48.051+00
\N	236	cpu_usage_percent	1.5614035088373015	percent	\N	2026-02-23 21:02:48.051+00
\N	236	cpu_usage_percent	1.582456140435852	percent	\N	2026-02-23 21:03:48.051+00
\N	236	cpu_usage_percent	1.561403508673905	percent	\N	2026-02-23 21:04:48.051+00
\N	236	cpu_usage_percent	1.5473684209415381	percent	\N	2026-02-23 21:05:48.051+00
\N	236	cpu_usage_percent	1.631578947335754	percent	\N	2026-02-23 21:06:48.051+00
\N	248	cpu_usage_percent	2.3815789473602678	percent	\N	2026-02-23 21:14:48.514+00
\N	248	cpu_usage_percent	2.4236842105165124	percent	\N	2026-02-23 21:15:48.514+00
\N	248	cpu_usage_percent	2.357894736791465	percent	\N	2026-02-23 21:16:48.514+00
\N	133	cpu_usage_percent	0.5614035088046165	percent	\N	2026-02-23 22:26:51.652+00
\N	133	cpu_usage_percent	0.5635964911708982	percent	\N	2026-02-23 22:27:51.652+00
\N	133	cpu_usage_percent	0.5592105263974929	percent	\N	2026-02-23 22:28:51.652+00
\N	133	cpu_usage_percent	0.413596491174161	percent	\N	2026-02-23 22:29:51.652+00
\N	248	cpu_usage_percent	2.612719298176998	percent	\N	2026-02-23 20:54:48.12+00
\N	248	cpu_usage_percent	2.5929824560635666	percent	\N	2026-02-23 20:55:48.12+00
\N	248	cpu_usage_percent	2.557456140292075	percent	\N	2026-02-23 20:56:48.12+00
\N	248	cpu_usage_percent	2.4504385964961415	percent	\N	2026-02-23 20:57:48.12+00
\N	248	cpu_usage_percent	2.396052631533209	percent	\N	2026-02-23 20:58:48.12+00
\N	248	cpu_usage_percent	2.2627192981982347	percent	\N	2026-02-23 20:59:48.12+00
\N	248	cpu_usage_percent	3.2842105263517567	percent	\N	2026-02-23 21:00:48.12+00
\N	248	cpu_usage_percent	3.47543859650105	percent	\N	2026-02-23 21:01:48.12+00
\N	248	cpu_usage_percent	3.509210526346834	percent	\N	2026-02-23 21:02:48.12+00
\N	248	cpu_usage_percent	3.4929824561665015	percent	\N	2026-02-23 21:03:48.12+00
\N	248	cpu_usage_percent	3.393859649117914	percent	\N	2026-02-23 21:04:48.12+00
\N	248	cpu_usage_percent	2.6206140350877263	percent	\N	2026-02-23 21:05:48.12+00
\N	248	cpu_usage_percent	2.5092105263550053	percent	\N	2026-02-23 21:06:48.12+00
\N	133	cpu_usage_percent	0.3100877193113263	percent	\N	2026-02-23 22:30:51.652+00
\N	236	cpu_usage_percent	1.6175438597667835	percent	\N	2026-02-23 21:34:49.662+00
\N	236	cpu_usage_percent	1.607017543885803	percent	\N	2026-02-23 21:35:49.662+00
\N	252	cpu_usage_percent	25.95701754389316	percent	\N	2026-02-23 21:04:48.574+00
\N	252	cpu_usage_percent	24.00307017545984	percent	\N	2026-02-23 21:05:48.574+00
\N	252	cpu_usage_percent	25.175877192993084	percent	\N	2026-02-23 21:06:48.574+00
\N	252	cpu_usage_percent	25.02850877194618	percent	\N	2026-02-23 21:07:48.574+00
\N	252	cpu_usage_percent	26.18991228069686	percent	\N	2026-02-23 20:54:48.186+00
\N	252	cpu_usage_percent	26.14078947371526	percent	\N	2026-02-23 20:55:48.186+00
\N	252	cpu_usage_percent	26.159649122865844	percent	\N	2026-02-23 20:56:48.186+00
\N	252	cpu_usage_percent	26.060964912278266	percent	\N	2026-02-23 20:57:48.186+00
\N	252	cpu_usage_percent	25.779824561455797	percent	\N	2026-02-23 20:58:48.186+00
\N	252	cpu_usage_percent	25.924561403512044	percent	\N	2026-02-23 20:59:48.186+00
\N	252	cpu_usage_percent	29.296929824549977	percent	\N	2026-02-23 21:00:48.186+00
\N	252	cpu_usage_percent	27.81184210525744	percent	\N	2026-02-23 21:01:48.186+00
\N	252	cpu_usage_percent	27.52675438597963	percent	\N	2026-02-23 21:02:48.186+00
\N	252	cpu_usage_percent	27.45833333332517	percent	\N	2026-02-23 21:03:48.186+00
\N	252	cpu_usage_percent	25.95701754389316	percent	\N	2026-02-23 21:04:48.186+00
\N	252	cpu_usage_percent	24.00307017545984	percent	\N	2026-02-23 21:05:48.186+00
\N	252	cpu_usage_percent	25.175877192993084	percent	\N	2026-02-23 21:06:48.186+00
\N	252	cpu_usage_percent	24.83333333332108	percent	\N	2026-02-23 21:08:48.574+00
\N	252	cpu_usage_percent	24.832894736819227	percent	\N	2026-02-23 21:09:48.574+00
\N	252	cpu_usage_percent	24.988596491217464	percent	\N	2026-02-23 21:10:48.574+00
\N	252	cpu_usage_percent	24.80964912283399	percent	\N	2026-02-23 21:11:48.574+00
\N	252	cpu_usage_percent	24.740789473698115	percent	\N	2026-02-23 21:12:48.574+00
\N	252	cpu_usage_percent	24.9144736842228	percent	\N	2026-02-23 21:13:48.574+00
\N	252	cpu_usage_percent	24.744736842092195	percent	\N	2026-02-23 21:14:48.574+00
\N	257	cpu_usage_percent	4.43859649123624	percent	\N	2026-02-23 20:54:48.25+00
\N	257	cpu_usage_percent	4.208771929833148	percent	\N	2026-02-23 20:55:48.25+00
\N	257	cpu_usage_percent	4.196491228067316	percent	\N	2026-02-23 20:56:48.25+00
\N	257	cpu_usage_percent	4.199122807017147	percent	\N	2026-02-23 20:57:48.25+00
\N	257	cpu_usage_percent	4.533333333337836	percent	\N	2026-02-23 20:58:48.25+00
\N	257	cpu_usage_percent	4.936842105265612	percent	\N	2026-02-23 20:59:48.25+00
\N	257	cpu_usage_percent	5.322807017538153	percent	\N	2026-02-23 21:00:48.25+00
\N	257	cpu_usage_percent	5.24999999998775	percent	\N	2026-02-23 21:01:48.25+00
\N	257	cpu_usage_percent	4.964035087716439	percent	\N	2026-02-23 21:02:48.25+00
\N	257	cpu_usage_percent	4.656140350863311	percent	\N	2026-02-23 21:03:48.25+00
\N	257	cpu_usage_percent	4.2140350877225785	percent	\N	2026-02-23 21:04:48.25+00
\N	257	cpu_usage_percent	3.8824561403312856	percent	\N	2026-02-23 21:05:48.25+00
\N	252	cpu_usage_percent	24.667105263103167	percent	\N	2026-02-23 21:15:48.574+00
\N	252	cpu_usage_percent	24.6135964912052	percent	\N	2026-02-23 21:16:48.574+00
\N	257	cpu_usage_percent	4.06578947367197	percent	\N	2026-02-23 21:06:48.25+00
\N	236	cpu_usage_percent	1.5964912281682189	percent	\N	2026-02-23 21:36:49.662+00
\N	236	cpu_usage_percent	1.4385964912607534	percent	\N	2026-02-23 21:37:49.662+00
\N	236	cpu_usage_percent	1.403508771929836	percent	\N	2026-02-23 21:38:49.662+00
\N	236	cpu_usage_percent	1.3964912280636383	percent	\N	2026-02-23 21:39:49.662+00
\N	236	cpu_usage_percent	1.403508771929836	percent	\N	2026-02-23 21:40:49.662+00
\N	236	cpu_usage_percent	1.4105263157960195	percent	\N	2026-02-23 21:41:49.662+00
\N	236	cpu_usage_percent	1.417543859662203	percent	\N	2026-02-23 21:42:49.662+00
\N	260	cpu_usage_percent	24.037938596509207	percent	\N	2026-02-23 20:54:48.322+00
\N	260	cpu_usage_percent	24.02971491221699	percent	\N	2026-02-23 20:55:48.322+00
\N	260	cpu_usage_percent	24.0846491227817	percent	\N	2026-02-23 20:56:48.322+00
\N	260	cpu_usage_percent	24.035964912312153	percent	\N	2026-02-23 20:57:48.322+00
\N	260	cpu_usage_percent	23.826425438614066	percent	\N	2026-02-23 20:58:48.322+00
\N	260	cpu_usage_percent	23.63947368423014	percent	\N	2026-02-23 20:59:48.322+00
\N	260	cpu_usage_percent	23.611622807036753	percent	\N	2026-02-23 21:00:48.322+00
\N	260	cpu_usage_percent	23.587828947388445	percent	\N	2026-02-23 21:01:48.322+00
\N	260	cpu_usage_percent	23.522149122783745	percent	\N	2026-02-23 21:02:48.322+00
\N	260	cpu_usage_percent	23.53673245610767	percent	\N	2026-02-23 21:03:48.322+00
\N	260	cpu_usage_percent	23.503618421055492	percent	\N	2026-02-23 21:04:48.322+00
\N	260	cpu_usage_percent	23.418311403498564	percent	\N	2026-02-23 21:05:48.322+00
\N	260	cpu_usage_percent	23.47401315786493	percent	\N	2026-02-23 21:06:48.322+00
\N	257	cpu_usage_percent	4.2140350877225785	percent	\N	2026-02-23 21:04:48.632+00
\N	257	cpu_usage_percent	3.8824561403312856	percent	\N	2026-02-23 21:05:48.632+00
\N	257	cpu_usage_percent	4.06578947367197	percent	\N	2026-02-23 21:06:48.632+00
\N	257	cpu_usage_percent	4.126315789476962	percent	\N	2026-02-23 21:07:48.632+00
\N	257	cpu_usage_percent	4.501754385970642	percent	\N	2026-02-23 21:08:48.632+00
\N	257	cpu_usage_percent	4.85438596490944	percent	\N	2026-02-23 21:09:48.632+00
\N	257	cpu_usage_percent	5.255263157897602	percent	\N	2026-02-23 21:10:48.632+00
\N	257	cpu_usage_percent	4.991228070167281	percent	\N	2026-02-23 21:11:48.632+00
\N	257	cpu_usage_percent	4.940350877198711	percent	\N	2026-02-23 21:12:48.632+00
\N	257	cpu_usage_percent	4.735087719296629	percent	\N	2026-02-23 21:13:48.632+00
\N	257	cpu_usage_percent	4.344736842097504	percent	\N	2026-02-23 21:14:48.632+00
\N	257	cpu_usage_percent	4.0456140350873255	percent	\N	2026-02-23 21:15:48.632+00
\N	257	cpu_usage_percent	3.8377192982456165	percent	\N	2026-02-23 21:16:48.632+00
\N	236	cpu_usage_percent	1.533333333209157	percent	\N	2026-02-23 21:43:49.662+00
\N	236	cpu_usage_percent	1.5473684211049203	percent	\N	2026-02-23 21:44:49.662+00
\N	236	cpu_usage_percent	1.52631578950637	percent	\N	2026-02-23 21:45:49.662+00
\N	236	cpu_usage_percent	1.512280701774003	percent	\N	2026-02-23 21:46:49.662+00
\N	133	cpu_usage_percent	0.43157894736189917	percent	\N	2026-02-23 22:31:51.652+00
\N	133	cpu_usage_percent	0.42061403516288465	percent	\N	2026-02-23 22:32:51.652+00
\N	133	cpu_usage_percent	0.42938596491393355	percent	\N	2026-02-23 22:33:51.652+00
\N	260	cpu_usage_percent	23.503618421055492	percent	\N	2026-02-23 21:04:48.699+00
\N	260	cpu_usage_percent	23.418311403498564	percent	\N	2026-02-23 21:05:48.699+00
\N	260	cpu_usage_percent	23.47401315786493	percent	\N	2026-02-23 21:06:48.699+00
\N	260	cpu_usage_percent	23.435635964943742	percent	\N	2026-02-23 21:07:48.699+00
\N	260	cpu_usage_percent	23.518969298232136	percent	\N	2026-02-23 21:08:48.699+00
\N	260	cpu_usage_percent	23.512719298239077	percent	\N	2026-02-23 21:09:48.699+00
\N	260	cpu_usage_percent	23.60624999998612	percent	\N	2026-02-23 21:10:48.699+00
\N	260	cpu_usage_percent	23.517543859606235	percent	\N	2026-02-23 21:11:48.699+00
\N	260	cpu_usage_percent	23.494298245620996	percent	\N	2026-02-23 21:12:48.699+00
\N	260	cpu_usage_percent	23.489473684233403	percent	\N	2026-02-23 21:13:48.699+00
\N	260	cpu_usage_percent	23.490350877186046	percent	\N	2026-02-23 21:14:48.699+00
\N	260	cpu_usage_percent	23.38903508769971	percent	\N	2026-02-23 21:15:48.699+00
\N	260	cpu_usage_percent	23.423793859618485	percent	\N	2026-02-23 21:16:48.699+00
\N	133	cpu_usage_percent	0.5320175438547636	percent	\N	2026-02-23 22:34:51.652+00
\N	133	cpu_usage_percent	0.4236842104920129	percent	\N	2026-02-23 22:35:51.652+00
\N	133	cpu_usage_percent	0.5350877193064321	percent	\N	2026-02-23 22:36:51.652+00
\N	133	cpu_usage_percent	0.4429824562057263	percent	\N	2026-02-23 23:34:56.27+00
\N	248	cpu_usage_percent	2.588157894767889	percent	\N	2026-02-23 21:34:49.725+00
\N	248	cpu_usage_percent	2.464035087706236	percent	\N	2026-02-23 21:35:49.725+00
\N	248	cpu_usage_percent	2.4495614034924387	percent	\N	2026-02-23 21:36:49.725+00
\N	133	cpu_usage_percent	0.5508771929644922	percent	\N	2026-02-23 21:14:48.769+00
\N	133	cpu_usage_percent	0.5447368421836956	percent	\N	2026-02-23 21:15:48.769+00
\N	133	cpu_usage_percent	0.4368421052615332	percent	\N	2026-02-23 21:16:48.769+00
\N	133	cpu_usage_percent	0.45043859651248397	percent	\N	2026-02-23 21:17:48.769+00
\N	133	cpu_usage_percent	0.4456140350942661	percent	\N	2026-02-23 21:18:48.769+00
\N	133	cpu_usage_percent	0.43070175443989456	percent	\N	2026-02-23 21:19:48.769+00
\N	133	cpu_usage_percent	0.432894736806162	percent	\N	2026-02-23 21:20:48.769+00
\N	133	cpu_usage_percent	0.4451754385311375	percent	\N	2026-02-23 21:21:48.769+00
\N	133	cpu_usage_percent	0.43070175435819635	percent	\N	2026-02-23 21:22:48.769+00
\N	133	cpu_usage_percent	0.5438596490983088	percent	\N	2026-02-23 21:23:48.769+00
\N	133	cpu_usage_percent	0.5574561403084033	percent	\N	2026-02-23 21:24:48.769+00
\N	133	cpu_usage_percent	0.5372807016726995	percent	\N	2026-02-23 21:25:48.769+00
\N	133	cpu_usage_percent	0.55043859656476	percent	\N	2026-02-23 21:26:48.769+00
\N	248	cpu_usage_percent	2.4956140350632268	percent	\N	2026-02-23 21:37:49.725+00
\N	248	cpu_usage_percent	2.4622807016988446	percent	\N	2026-02-23 21:38:49.725+00
\N	248	cpu_usage_percent	2.510087719195326	percent	\N	2026-02-23 21:39:49.725+00
\N	248	cpu_usage_percent	2.65087719300044	percent	\N	2026-02-23 21:40:49.725+00
\N	248	cpu_usage_percent	2.698684210456065	percent	\N	2026-02-23 21:41:49.725+00
\N	248	cpu_usage_percent	2.6947368421232483	percent	\N	2026-02-23 21:42:49.725+00
\N	248	cpu_usage_percent	2.8013157895194496	percent	\N	2026-02-23 21:43:49.725+00
\N	236	cpu_usage_percent	1.6315789474991504	percent	\N	2026-02-23 21:14:48.847+00
\N	236	cpu_usage_percent	1.631578947335754	percent	\N	2026-02-23 21:15:48.847+00
\N	236	cpu_usage_percent	1.5052631579078195	percent	\N	2026-02-23 21:16:48.847+00
\N	236	cpu_usage_percent	1.4491228069783375	percent	\N	2026-02-23 21:17:48.847+00
\N	236	cpu_usage_percent	1.4385964910973712	percent	\N	2026-02-23 21:18:48.847+00
\N	236	cpu_usage_percent	1.4385964912607534	percent	\N	2026-02-23 21:19:48.847+00
\N	236	cpu_usage_percent	1.4385964910973712	percent	\N	2026-02-23 21:20:48.847+00
\N	236	cpu_usage_percent	1.4385964910973712	percent	\N	2026-02-23 21:21:48.847+00
\N	236	cpu_usage_percent	1.4350877194093528	percent	\N	2026-02-23 21:22:48.847+00
\N	236	cpu_usage_percent	1.5894736843020354	percent	\N	2026-02-23 21:23:48.847+00
\N	236	cpu_usage_percent	4.371929824548332	percent	\N	2026-02-23 21:24:48.847+00
\N	236	cpu_usage_percent	4.414035087582064	percent	\N	2026-02-23 21:25:48.847+00
\N	236	cpu_usage_percent	4.414035087745447	percent	\N	2026-02-23 21:26:48.847+00
\N	248	cpu_usage_percent	2.723684210550843	percent	\N	2026-02-23 21:44:49.725+00
\N	248	cpu_usage_percent	2.626754385909365	percent	\N	2026-02-23 21:45:49.725+00
\N	248	cpu_usage_percent	2.5706140351024374	percent	\N	2026-02-23 21:46:49.725+00
\N	133	cpu_usage_percent	0.5425438596540317	percent	\N	2026-02-23 23:35:56.27+00
\N	133	cpu_usage_percent	0.5434210526985765	percent	\N	2026-02-23 23:36:56.27+00
\N	133	cpu_usage_percent	0.5350877193472741	percent	\N	2026-02-23 23:37:56.27+00
\N	133	cpu_usage_percent	0.5394736842023633	percent	\N	2026-02-23 23:38:56.27+00
\N	248	cpu_usage_percent	2.3815789473602678	percent	\N	2026-02-23 21:14:48.913+00
\N	248	cpu_usage_percent	2.4236842105165124	percent	\N	2026-02-23 21:15:48.913+00
\N	248	cpu_usage_percent	2.357894736791465	percent	\N	2026-02-23 21:16:48.913+00
\N	248	cpu_usage_percent	2.480701754408855	percent	\N	2026-02-23 21:17:48.913+00
\N	133	cpu_usage_percent	0.5311403508102046	percent	\N	2026-02-23 23:39:56.27+00
\N	133	cpu_usage_percent	0.4276315789473699	percent	\N	2026-02-23 23:40:56.27+00
\N	248	cpu_usage_percent	2.5026315789294102	percent	\N	2026-02-23 21:18:48.913+00
\N	248	cpu_usage_percent	2.806140350855955	percent	\N	2026-02-23 21:19:48.913+00
\N	248	cpu_usage_percent	2.7399122808128737	percent	\N	2026-02-23 21:20:48.913+00
\N	248	cpu_usage_percent	2.8140350876849993	percent	\N	2026-02-23 21:21:48.913+00
\N	248	cpu_usage_percent	2.7403508771309077	percent	\N	2026-02-23 21:22:48.913+00
\N	248	cpu_usage_percent	3.007017543800842	percent	\N	2026-02-23 21:23:48.913+00
\N	248	cpu_usage_percent	2.819736842106906	percent	\N	2026-02-23 21:24:48.913+00
\N	248	cpu_usage_percent	2.905701754345131	percent	\N	2026-02-23 21:25:48.913+00
\N	248	cpu_usage_percent	2.867543859644229	percent	\N	2026-02-23 21:26:48.913+00
\N	236	cpu_usage_percent	1.5719298245548714	percent	\N	2026-02-23 22:24:51.721+00
\N	236	cpu_usage_percent	1.617543859603387	percent	\N	2026-02-23 22:25:51.721+00
\N	252	cpu_usage_percent	24.75438596488779	percent	\N	2026-02-23 21:34:49.791+00
\N	252	cpu_usage_percent	24.43070175438679	percent	\N	2026-02-23 21:35:49.791+00
\N	252	cpu_usage_percent	24.73640350878175	percent	\N	2026-02-23 21:36:49.791+00
\N	252	cpu_usage_percent	24.70964912280212	percent	\N	2026-02-23 21:37:49.791+00
\N	252	cpu_usage_percent	24.60350877192819	percent	\N	2026-02-23 21:38:49.791+00
\N	252	cpu_usage_percent	24.744736842092195	percent	\N	2026-02-23 21:14:48.98+00
\N	252	cpu_usage_percent	24.667105263103167	percent	\N	2026-02-23 21:15:48.98+00
\N	252	cpu_usage_percent	24.6135964912052	percent	\N	2026-02-23 21:16:48.98+00
\N	252	cpu_usage_percent	27.195175438608757	percent	\N	2026-02-23 21:17:48.98+00
\N	252	cpu_usage_percent	29.70175438597309	percent	\N	2026-02-23 21:18:48.98+00
\N	252	cpu_usage_percent	32.75701754387437	percent	\N	2026-02-23 21:19:48.98+00
\N	252	cpu_usage_percent	35.30877192984663	percent	\N	2026-02-23 21:20:48.98+00
\N	252	cpu_usage_percent	35.96885964911628	percent	\N	2026-02-23 21:21:48.98+00
\N	252	cpu_usage_percent	33.41622807018116	percent	\N	2026-02-23 21:22:48.98+00
\N	252	cpu_usage_percent	30.85745614038356	percent	\N	2026-02-23 21:23:48.98+00
\N	252	cpu_usage_percent	27.84605263158467	percent	\N	2026-02-23 21:24:48.98+00
\N	252	cpu_usage_percent	25.321491228053034	percent	\N	2026-02-23 21:25:48.98+00
\N	252	cpu_usage_percent	24.667982456147712	percent	\N	2026-02-23 21:26:48.98+00
\N	252	cpu_usage_percent	24.611403508777656	percent	\N	2026-02-23 21:39:49.791+00
\N	252	cpu_usage_percent	24.511403508786643	percent	\N	2026-02-23 21:40:49.791+00
\N	252	cpu_usage_percent	24.540350877193802	percent	\N	2026-02-23 21:41:49.791+00
\N	252	cpu_usage_percent	24.41973684210609	percent	\N	2026-02-23 21:42:49.791+00
\N	252	cpu_usage_percent	24.153070175456577	percent	\N	2026-02-23 21:43:49.791+00
\N	252	cpu_usage_percent	24.283333333360304	percent	\N	2026-02-23 21:44:49.791+00
\N	252	cpu_usage_percent	24.271491228075902	percent	\N	2026-02-23 21:45:49.791+00
\N	257	cpu_usage_percent	4.344736842097504	percent	\N	2026-02-23 21:14:49.035+00
\N	257	cpu_usage_percent	4.0456140350873255	percent	\N	2026-02-23 21:15:49.035+00
\N	257	cpu_usage_percent	3.8377192982456165	percent	\N	2026-02-23 21:16:49.035+00
\N	257	cpu_usage_percent	4.092105263149733	percent	\N	2026-02-23 21:17:49.035+00
\N	257	cpu_usage_percent	4.4008771929963615	percent	\N	2026-02-23 21:18:49.035+00
\N	257	cpu_usage_percent	4.794736842097919	percent	\N	2026-02-23 21:19:49.035+00
\N	257	cpu_usage_percent	5.193859649139981	percent	\N	2026-02-23 21:20:49.035+00
\N	257	cpu_usage_percent	5.164912280702168	percent	\N	2026-02-23 21:21:49.035+00
\N	257	cpu_usage_percent	4.903508771921679	percent	\N	2026-02-23 21:22:49.035+00
\N	257	cpu_usage_percent	4.706140350889456	percent	\N	2026-02-23 21:23:49.035+00
\N	257	cpu_usage_percent	4.364035087729519	percent	\N	2026-02-23 21:24:49.035+00
\N	257	cpu_usage_percent	4.109649122804981	percent	\N	2026-02-23 21:25:49.035+00
\N	257	cpu_usage_percent	4.068421052652411	percent	\N	2026-02-23 21:26:49.035+00
\N	252	cpu_usage_percent	24.401754385959208	percent	\N	2026-02-23 21:46:49.791+00
\N	236	cpu_usage_percent	1.603508771871006	percent	\N	2026-02-23 22:26:51.721+00
\N	236	cpu_usage_percent	2.6456140351007917	percent	\N	2026-02-23 22:27:51.721+00
\N	236	cpu_usage_percent	2.670175438550743	percent	\N	2026-02-23 22:28:51.721+00
\N	236	cpu_usage_percent	2.533333333405224	percent	\N	2026-02-23 22:29:51.721+00
\N	236	cpu_usage_percent	2.361403508765406	percent	\N	2026-02-23 22:30:51.721+00
\N	236	cpu_usage_percent	2.5157894736580744	percent	\N	2026-02-23 22:31:51.721+00
\N	260	cpu_usage_percent	23.490350877186046	percent	\N	2026-02-23 21:14:49.092+00
\N	260	cpu_usage_percent	23.38903508769971	percent	\N	2026-02-23 21:15:49.092+00
\N	260	cpu_usage_percent	23.423793859618485	percent	\N	2026-02-23 21:16:49.092+00
\N	260	cpu_usage_percent	23.43245614040235	percent	\N	2026-02-23 21:17:49.092+00
\N	260	cpu_usage_percent	23.408223684201133	percent	\N	2026-02-23 21:18:49.092+00
\N	260	cpu_usage_percent	23.412609649107296	percent	\N	2026-02-23 21:19:49.092+00
\N	260	cpu_usage_percent	23.417982456137494	percent	\N	2026-02-23 21:20:49.092+00
\N	260	cpu_usage_percent	23.4217105263113	percent	\N	2026-02-23 21:21:49.092+00
\N	260	cpu_usage_percent	23.39155701751895	percent	\N	2026-02-23 21:22:49.092+00
\N	260	cpu_usage_percent	23.44517543857812	percent	\N	2026-02-23 21:23:49.092+00
\N	260	cpu_usage_percent	23.376644736823735	percent	\N	2026-02-23 21:24:49.092+00
\N	260	cpu_usage_percent	23.409429824616964	percent	\N	2026-02-23 21:25:49.092+00
\N	260	cpu_usage_percent	23.416776315742098	percent	\N	2026-02-23 21:26:49.092+00
\N	236	cpu_usage_percent	1.487719298324052	percent	\N	2026-02-23 22:32:51.721+00
\N	257	cpu_usage_percent	4.372807017552034	percent	\N	2026-02-23 21:34:49.856+00
\N	257	cpu_usage_percent	4.068421052601366	percent	\N	2026-02-23 21:35:49.856+00
\N	257	cpu_usage_percent	4.072807017548357	percent	\N	2026-02-23 21:36:49.856+00
\N	257	cpu_usage_percent	4.0622807017695095	percent	\N	2026-02-23 21:37:49.856+00
\N	257	cpu_usage_percent	4.4561403508812845	percent	\N	2026-02-23 21:38:49.856+00
\N	257	cpu_usage_percent	4.8236842105050926	percent	\N	2026-02-23 21:39:49.856+00
\N	133	cpu_usage_percent	0.5574561403084033	percent	\N	2026-02-23 21:24:49.165+00
\N	133	cpu_usage_percent	0.5372807016726995	percent	\N	2026-02-23 21:25:49.165+00
\N	133	cpu_usage_percent	0.55043859656476	percent	\N	2026-02-23 21:26:49.165+00
\N	133	cpu_usage_percent	0.4425438597242817	percent	\N	2026-02-23 21:27:49.165+00
\N	133	cpu_usage_percent	0.44780701758307373	percent	\N	2026-02-23 21:28:49.165+00
\N	133	cpu_usage_percent	0.4460526315756823	percent	\N	2026-02-23 21:29:49.165+00
\N	133	cpu_usage_percent	0.4451754386128499	percent	\N	2026-02-23 21:30:49.165+00
\N	133	cpu_usage_percent	0.45745614033782545	percent	\N	2026-02-23 21:31:49.165+00
\N	133	cpu_usage_percent	0.34429824567939704	percent	\N	2026-02-23 21:32:49.165+00
\N	133	cpu_usage_percent	0.5263157894736992	percent	\N	2026-02-23 21:33:49.165+00
\N	133	cpu_usage_percent	0.5385964912803587	percent	\N	2026-02-23 21:34:49.165+00
\N	133	cpu_usage_percent	0.5442982455797392	percent	\N	2026-02-23 21:35:49.165+00
\N	133	cpu_usage_percent	0.5324561403770218	percent	\N	2026-02-23 21:36:49.165+00
\N	257	cpu_usage_percent	5.146491228053435	percent	\N	2026-02-23 21:40:49.856+00
\N	257	cpu_usage_percent	5.176315789474501	percent	\N	2026-02-23 21:41:49.856+00
\N	257	cpu_usage_percent	4.903508771931868	percent	\N	2026-02-23 21:42:49.856+00
\N	257	cpu_usage_percent	4.53947368423097	percent	\N	2026-02-23 21:43:49.856+00
\N	257	cpu_usage_percent	4.183333333338652	percent	\N	2026-02-23 21:44:49.856+00
\N	257	cpu_usage_percent	3.942982456136278	percent	\N	2026-02-23 21:45:49.856+00
\N	257	cpu_usage_percent	3.9614035087747936	percent	\N	2026-02-23 21:46:49.856+00
\N	236	cpu_usage_percent	4.371929824548332	percent	\N	2026-02-23 21:24:49.237+00
\N	236	cpu_usage_percent	4.414035087582064	percent	\N	2026-02-23 21:25:49.237+00
\N	236	cpu_usage_percent	4.414035087745447	percent	\N	2026-02-23 21:26:49.237+00
\N	236	cpu_usage_percent	4.414035087582064	percent	\N	2026-02-23 21:27:49.237+00
\N	236	cpu_usage_percent	4.2526315789865805	percent	\N	2026-02-23 21:28:49.237+00
\N	236	cpu_usage_percent	1.473684210591685	percent	\N	2026-02-23 21:29:49.237+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	\N	2026-02-23 21:30:49.237+00
\N	236	cpu_usage_percent	1.4596491228593038	percent	\N	2026-02-23 21:31:49.237+00
\N	236	cpu_usage_percent	1.3263157895651858	percent	\N	2026-02-23 21:32:49.237+00
\N	236	cpu_usage_percent	1.5017543858930225	percent	\N	2026-02-23 22:33:51.721+00
\N	236	cpu_usage_percent	1.6350877193505369	percent	\N	2026-02-23 22:34:51.721+00
\N	236	cpu_usage_percent	1.5789473684210549	percent	\N	2026-02-23 21:33:49.237+00
\N	236	cpu_usage_percent	1.6175438597667835	percent	\N	2026-02-23 21:34:49.237+00
\N	236	cpu_usage_percent	1.607017543885803	percent	\N	2026-02-23 21:35:49.237+00
\N	236	cpu_usage_percent	1.5964912281682189	percent	\N	2026-02-23 21:36:49.237+00
\N	236	cpu_usage_percent	1.5017543860564189	percent	\N	2026-02-23 22:35:51.721+00
\N	236	cpu_usage_percent	1.6245614034695706	percent	\N	2026-02-23 22:36:51.721+00
\N	133	cpu_usage_percent	0.4377192982243798	percent	\N	2026-02-23 23:41:56.27+00
\N	133	cpu_usage_percent	0.4267543859436813	percent	\N	2026-02-23 23:42:56.27+00
\N	133	cpu_usage_percent	0.43859649122808264	percent	\N	2026-02-23 23:43:56.27+00
\N	133	cpu_usage_percent	0.4241228070142853	percent	\N	2026-02-23 23:44:56.27+00
\N	260	cpu_usage_percent	23.47905701753406	percent	\N	2026-02-23 21:34:49.926+00
\N	248	cpu_usage_percent	2.819736842106906	percent	\N	2026-02-23 21:24:49.311+00
\N	248	cpu_usage_percent	2.905701754345131	percent	\N	2026-02-23 21:25:49.311+00
\N	248	cpu_usage_percent	2.867543859644229	percent	\N	2026-02-23 21:26:49.311+00
\N	248	cpu_usage_percent	2.8285087719396387	percent	\N	2026-02-23 21:27:49.311+00
\N	248	cpu_usage_percent	2.4557017543957755	percent	\N	2026-02-23 21:28:49.311+00
\N	248	cpu_usage_percent	2.3916666667189617	percent	\N	2026-02-23 21:29:49.311+00
\N	248	cpu_usage_percent	2.4982456139926086	percent	\N	2026-02-23 21:30:49.311+00
\N	248	cpu_usage_percent	2.544298245726779	percent	\N	2026-02-23 21:31:49.311+00
\N	248	cpu_usage_percent	2.3899122806707283	percent	\N	2026-02-23 21:32:49.311+00
\N	248	cpu_usage_percent	2.574122807035522	percent	\N	2026-02-23 21:33:49.311+00
\N	248	cpu_usage_percent	2.588157894767889	percent	\N	2026-02-23 21:34:49.311+00
\N	248	cpu_usage_percent	2.464035087706236	percent	\N	2026-02-23 21:35:49.311+00
\N	248	cpu_usage_percent	2.4495614034924387	percent	\N	2026-02-23 21:36:49.311+00
\N	260	cpu_usage_percent	23.522149122834804	percent	\N	2026-02-23 21:35:49.926+00
\N	260	cpu_usage_percent	23.489692982443486	percent	\N	2026-02-23 21:36:49.926+00
\N	260	cpu_usage_percent	23.41085526315095	percent	\N	2026-02-23 21:37:49.926+00
\N	260	cpu_usage_percent	23.422368421043643	percent	\N	2026-02-23 21:38:49.926+00
\N	260	cpu_usage_percent	23.418201754357796	percent	\N	2026-02-23 21:39:49.926+00
\N	260	cpu_usage_percent	23.510855263223675	percent	\N	2026-02-23 21:40:49.926+00
\N	260	cpu_usage_percent	23.558333333379494	percent	\N	2026-02-23 21:41:49.926+00
\N	252	cpu_usage_percent	27.84605263158467	percent	\N	2026-02-23 21:24:49.397+00
\N	252	cpu_usage_percent	25.321491228053034	percent	\N	2026-02-23 21:25:49.397+00
\N	252	cpu_usage_percent	24.667982456147712	percent	\N	2026-02-23 21:26:49.397+00
\N	252	cpu_usage_percent	24.78333333333579	percent	\N	2026-02-23 21:27:49.397+00
\N	252	cpu_usage_percent	24.614473684188482	percent	\N	2026-02-23 21:28:49.397+00
\N	252	cpu_usage_percent	24.507456140372128	percent	\N	2026-02-23 21:29:49.397+00
\N	252	cpu_usage_percent	24.89122807017627	percent	\N	2026-02-23 21:30:49.397+00
\N	252	cpu_usage_percent	24.89736842105917	percent	\N	2026-02-23 21:31:49.397+00
\N	252	cpu_usage_percent	24.34342105262259	percent	\N	2026-02-23 21:32:49.397+00
\N	252	cpu_usage_percent	24.893859649105664	percent	\N	2026-02-23 21:33:49.397+00
\N	252	cpu_usage_percent	24.75438596488779	percent	\N	2026-02-23 21:34:49.397+00
\N	252	cpu_usage_percent	24.43070175438679	percent	\N	2026-02-23 21:35:49.397+00
\N	252	cpu_usage_percent	24.73640350878175	percent	\N	2026-02-23 21:36:49.397+00
\N	260	cpu_usage_percent	24.05603070174581	percent	\N	2026-02-23 21:42:49.926+00
\N	260	cpu_usage_percent	24.053837719338688	percent	\N	2026-02-23 21:43:49.926+00
\N	260	cpu_usage_percent	24.036293859673236	percent	\N	2026-02-23 21:44:49.926+00
\N	260	cpu_usage_percent	23.96414473680413	percent	\N	2026-02-23 21:45:49.926+00
\N	260	cpu_usage_percent	23.78497807019015	percent	\N	2026-02-23 21:46:49.926+00
\N	133	cpu_usage_percent	0.48815789473195537	percent	\N	2026-02-23 23:45:56.27+00
\N	133	cpu_usage_percent	0.5245614034254515	percent	\N	2026-02-23 23:46:56.27+00
\N	257	cpu_usage_percent	4.364035087729519	percent	\N	2026-02-23 21:24:49.465+00
\N	257	cpu_usage_percent	4.109649122804981	percent	\N	2026-02-23 21:25:49.465+00
\N	257	cpu_usage_percent	4.068421052652411	percent	\N	2026-02-23 21:26:49.465+00
\N	257	cpu_usage_percent	4.2850877193166355	percent	\N	2026-02-23 21:27:49.465+00
\N	257	cpu_usage_percent	4.59298245613914	percent	\N	2026-02-23 21:28:49.465+00
\N	257	cpu_usage_percent	4.9464912280612054	percent	\N	2026-02-23 21:29:49.465+00
\N	257	cpu_usage_percent	5.254385964914334	percent	\N	2026-02-23 21:30:49.465+00
\N	257	cpu_usage_percent	5.280701754392098	percent	\N	2026-02-23 21:31:49.465+00
\N	257	cpu_usage_percent	4.734210526303144	percent	\N	2026-02-23 21:32:49.465+00
\N	257	cpu_usage_percent	4.724561403527986	percent	\N	2026-02-23 21:33:49.465+00
\N	257	cpu_usage_percent	4.372807017552034	percent	\N	2026-02-23 21:34:49.465+00
\N	257	cpu_usage_percent	4.068421052601366	percent	\N	2026-02-23 21:35:49.465+00
\N	257	cpu_usage_percent	4.072807017548357	percent	\N	2026-02-23 21:36:49.465+00
\N	248	cpu_usage_percent	2.3144736842726275	percent	\N	2026-02-23 22:24:51.785+00
\N	248	cpu_usage_percent	2.3390350877634347	percent	\N	2026-02-23 22:25:51.785+00
\N	248	cpu_usage_percent	2.3916666666781197	percent	\N	2026-02-23 22:26:51.785+00
\N	248	cpu_usage_percent	2.351315789488396	percent	\N	2026-02-23 22:27:51.785+00
\N	133	cpu_usage_percent	0.5004385964977729	percent	\N	2026-02-23 21:44:49.997+00
\N	133	cpu_usage_percent	0.4934210526724314	percent	\N	2026-02-23 21:45:49.997+00
\N	260	cpu_usage_percent	23.376644736823735	percent	\N	2026-02-23 21:24:49.532+00
\N	260	cpu_usage_percent	23.409429824616964	percent	\N	2026-02-23 21:25:49.532+00
\N	260	cpu_usage_percent	23.416776315742098	percent	\N	2026-02-23 21:26:49.532+00
\N	260	cpu_usage_percent	23.411842105244375	percent	\N	2026-02-23 21:27:49.532+00
\N	260	cpu_usage_percent	23.42741228070257	percent	\N	2026-02-23 21:28:49.532+00
\N	260	cpu_usage_percent	23.417324561354093	percent	\N	2026-02-23 21:29:49.532+00
\N	260	cpu_usage_percent	23.42554824557483	percent	\N	2026-02-23 21:30:49.532+00
\N	260	cpu_usage_percent	23.448245614029787	percent	\N	2026-02-23 21:31:49.532+00
\N	260	cpu_usage_percent	23.520175438586705	percent	\N	2026-02-23 21:32:49.532+00
\N	260	cpu_usage_percent	23.553947368442707	percent	\N	2026-02-23 21:33:49.532+00
\N	260	cpu_usage_percent	23.47905701753406	percent	\N	2026-02-23 21:34:49.532+00
\N	260	cpu_usage_percent	23.522149122834804	percent	\N	2026-02-23 21:35:49.532+00
\N	260	cpu_usage_percent	23.489692982443486	percent	\N	2026-02-23 21:36:49.532+00
\N	133	cpu_usage_percent	0.513596491185595	percent	\N	2026-02-23 21:46:49.997+00
\N	133	cpu_usage_percent	0.5105263157747686	percent	\N	2026-02-23 21:47:49.997+00
\N	133	cpu_usage_percent	0.4745614034810046	percent	\N	2026-02-23 21:48:49.997+00
\N	133	cpu_usage_percent	0.49692982448299006	percent	\N	2026-02-23 21:49:49.997+00
\N	133	cpu_usage_percent	0.505701754356565	percent	\N	2026-02-23 21:50:49.997+00
\N	133	cpu_usage_percent	0.4934210526315894	percent	\N	2026-02-23 21:51:49.997+00
\N	133	cpu_usage_percent	0.5004385964977729	percent	\N	2026-02-23 21:52:49.997+00
\N	133	cpu_usage_percent	0.4539473684455686	percent	\N	2026-02-23 21:53:49.997+00
\N	133	cpu_usage_percent	0.6048245614051524	percent	\N	2026-02-23 21:54:49.997+00
\N	133	cpu_usage_percent	0.6078947368568208	percent	\N	2026-02-23 21:55:49.997+00
\N	133	cpu_usage_percent	0.6171052631301279	percent	\N	2026-02-23 21:56:49.997+00
\N	248	cpu_usage_percent	2.387280701782174	percent	\N	2026-02-23 22:28:51.785+00
\N	248	cpu_usage_percent	2.3315789472932664	percent	\N	2026-02-23 22:29:51.785+00
\N	248	cpu_usage_percent	2.3456140350664896	percent	\N	2026-02-23 22:30:51.785+00
\N	248	cpu_usage_percent	2.3328947368192416	percent	\N	2026-02-23 22:31:51.785+00
\N	248	cpu_usage_percent	2.4166666667728833	percent	\N	2026-02-23 22:32:51.785+00
\N	248	cpu_usage_percent	2.6732456140432674	percent	\N	2026-02-23 22:33:51.785+00
\N	248	cpu_usage_percent	2.8092105263484797	percent	\N	2026-02-23 22:34:51.785+00
\N	236	cpu_usage_percent	1.5473684211049203	percent	\N	2026-02-23 21:44:50.088+00
\N	236	cpu_usage_percent	1.52631578950637	percent	\N	2026-02-23 21:45:50.088+00
\N	236	cpu_usage_percent	1.512280701774003	percent	\N	2026-02-23 21:46:50.088+00
\N	236	cpu_usage_percent	1.5017543860564189	percent	\N	2026-02-23 21:47:50.088+00
\N	248	cpu_usage_percent	2.6749999999281187	percent	\N	2026-02-23 22:35:51.785+00
\N	236	cpu_usage_percent	1.4070175439446189	percent	\N	2026-02-23 21:48:50.088+00
\N	236	cpu_usage_percent	1.43157894739457	percent	\N	2026-02-23 21:49:50.088+00
\N	236	cpu_usage_percent	1.4631578947107045	percent	\N	2026-02-23 21:50:50.088+00
\N	236	cpu_usage_percent	1.4666666667255015	percent	\N	2026-02-23 21:51:50.088+00
\N	236	cpu_usage_percent	1.470175438576888	percent	\N	2026-02-23 21:52:50.088+00
\N	236	cpu_usage_percent	1.403508771929836	percent	\N	2026-02-23 21:53:50.088+00
\N	236	cpu_usage_percent	1.550877192956321	percent	\N	2026-02-23 21:54:50.088+00
\N	236	cpu_usage_percent	1.5614035088373015	percent	\N	2026-02-23 21:55:50.088+00
\N	236	cpu_usage_percent	1.561403508673905	percent	\N	2026-02-23 21:56:50.088+00
\N	248	cpu_usage_percent	2.7986842105492116	percent	\N	2026-02-23 22:36:51.785+00
\N	248	cpu_usage_percent	2.723684210550843	percent	\N	2026-02-23 21:44:50.162+00
\N	248	cpu_usage_percent	2.626754385909365	percent	\N	2026-02-23 21:45:50.162+00
\N	248	cpu_usage_percent	2.5706140351024374	percent	\N	2026-02-23 21:46:50.162+00
\N	248	cpu_usage_percent	2.5662280700839517	percent	\N	2026-02-23 21:47:50.162+00
\N	248	cpu_usage_percent	2.423245613994254	percent	\N	2026-02-23 21:48:50.162+00
\N	248	cpu_usage_percent	2.422807017635364	percent	\N	2026-02-23 21:49:50.162+00
\N	248	cpu_usage_percent	2.3912280702375455	percent	\N	2026-02-23 21:50:50.162+00
\N	248	cpu_usage_percent	2.382017543800842	percent	\N	2026-02-23 21:51:50.162+00
\N	248	cpu_usage_percent	2.3697368421984066	percent	\N	2026-02-23 21:52:50.162+00
\N	248	cpu_usage_percent	2.32324561398282	percent	\N	2026-02-23 21:53:50.162+00
\N	248	cpu_usage_percent	2.4785087719608754	percent	\N	2026-02-23 21:54:50.162+00
\N	248	cpu_usage_percent	2.614473684306944	percent	\N	2026-02-23 21:55:50.162+00
\N	248	cpu_usage_percent	2.595175438511532	percent	\N	2026-02-23 21:56:50.162+00
\N	236	cpu_usage_percent	1.498245614041636	percent	\N	2026-02-23 23:34:56.347+00
\N	252	cpu_usage_percent	23.91842105264547	percent	\N	2026-02-23 22:24:51.84+00
\N	252	cpu_usage_percent	23.89078947370301	percent	\N	2026-02-23 22:25:51.84+00
\N	252	cpu_usage_percent	23.918421052584208	percent	\N	2026-02-23 22:26:51.84+00
\N	252	cpu_usage_percent	23.852631578961265	percent	\N	2026-02-23 22:27:51.84+00
\N	252	cpu_usage_percent	23.962719298249695	percent	\N	2026-02-23 22:28:51.84+00
\N	252	cpu_usage_percent	23.80482456140352	percent	\N	2026-02-23 22:29:51.84+00
\N	252	cpu_usage_percent	24.283333333360304	percent	\N	2026-02-23 21:44:50.233+00
\N	252	cpu_usage_percent	24.271491228075902	percent	\N	2026-02-23 21:45:50.233+00
\N	252	cpu_usage_percent	24.401754385959208	percent	\N	2026-02-23 21:46:50.233+00
\N	252	cpu_usage_percent	24.517543859649123	percent	\N	2026-02-23 21:47:50.233+00
\N	252	cpu_usage_percent	24.326315789458988	percent	\N	2026-02-23 21:48:50.233+00
\N	252	cpu_usage_percent	24.34254385963932	percent	\N	2026-02-23 21:49:50.233+00
\N	252	cpu_usage_percent	24.394298245570738	percent	\N	2026-02-23 21:50:50.233+00
\N	252	cpu_usage_percent	24.232894736832307	percent	\N	2026-02-23 21:51:50.233+00
\N	252	cpu_usage_percent	24.387719298267683	percent	\N	2026-02-23 21:52:50.233+00
\N	252	cpu_usage_percent	24.597368421004433	percent	\N	2026-02-23 21:53:50.233+00
\N	252	cpu_usage_percent	24.57500000000246	percent	\N	2026-02-23 21:54:50.233+00
\N	252	cpu_usage_percent	24.643859649158756	percent	\N	2026-02-23 21:55:50.233+00
\N	252	cpu_usage_percent	24.65833333333171	percent	\N	2026-02-23 21:56:50.233+00
\N	252	cpu_usage_percent	23.86666666663237	percent	\N	2026-02-23 22:30:51.84+00
\N	252	cpu_usage_percent	24.531578947361083	percent	\N	2026-02-23 22:31:51.84+00
\N	252	cpu_usage_percent	24.52587719298002	percent	\N	2026-02-23 22:32:51.84+00
\N	252	cpu_usage_percent	24.56929824566224	percent	\N	2026-02-23 22:33:51.84+00
\N	252	cpu_usage_percent	24.758333333343145	percent	\N	2026-02-23 22:34:51.84+00
\N	252	cpu_usage_percent	24.403947368407174	percent	\N	2026-02-23 22:35:51.84+00
\N	252	cpu_usage_percent	25.648245614046544	percent	\N	2026-02-23 22:36:51.84+00
\N	257	cpu_usage_percent	4.183333333338652	percent	\N	2026-02-23 21:44:50.289+00
\N	257	cpu_usage_percent	3.942982456136278	percent	\N	2026-02-23 21:45:50.289+00
\N	257	cpu_usage_percent	3.9614035087747936	percent	\N	2026-02-23 21:46:50.289+00
\N	257	cpu_usage_percent	4.108771929821714	percent	\N	2026-02-23 21:47:50.289+00
\N	257	cpu_usage_percent	4.3421052631579045	percent	\N	2026-02-23 21:48:50.289+00
\N	257	cpu_usage_percent	4.76052631577069	percent	\N	2026-02-23 21:49:50.289+00
\N	257	cpu_usage_percent	5.122807017535706	percent	\N	2026-02-23 21:50:50.289+00
\N	257	cpu_usage_percent	5.095614035084878	percent	\N	2026-02-23 21:51:50.289+00
\N	257	cpu_usage_percent	4.814035087709499	percent	\N	2026-02-23 21:52:50.289+00
\N	257	cpu_usage_percent	4.398245614015892	percent	\N	2026-02-23 21:53:50.289+00
\N	257	cpu_usage_percent	4.33333333335581	percent	\N	2026-02-23 21:54:50.289+00
\N	257	cpu_usage_percent	4.070175438608757	percent	\N	2026-02-23 21:55:50.289+00
\N	257	cpu_usage_percent	4.070175438588336	percent	\N	2026-02-23 21:56:50.289+00
\N	236	cpu_usage_percent	1.6280701754843534	percent	\N	2026-02-23 23:35:56.347+00
\N	236	cpu_usage_percent	1.589473684138639	percent	\N	2026-02-23 23:36:56.347+00
\N	236	cpu_usage_percent	1.5789473684210549	percent	\N	2026-02-23 23:37:56.347+00
\N	236	cpu_usage_percent	1.442105263112154	percent	\N	2026-02-23 23:38:56.347+00
\N	236	cpu_usage_percent	1.5964912281682189	percent	\N	2026-02-23 23:39:56.347+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	\N	2026-02-23 23:40:56.347+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	\N	2026-02-23 23:41:56.347+00
\N	260	cpu_usage_percent	24.036293859673236	percent	\N	2026-02-23 21:44:50.345+00
\N	260	cpu_usage_percent	23.96414473680413	percent	\N	2026-02-23 21:45:50.345+00
\N	260	cpu_usage_percent	23.78497807019015	percent	\N	2026-02-23 21:46:50.345+00
\N	260	cpu_usage_percent	23.50537280700162	percent	\N	2026-02-23 21:47:50.345+00
\N	260	cpu_usage_percent	23.433881578946554	percent	\N	2026-02-23 21:48:50.345+00
\N	260	cpu_usage_percent	23.46458333331006	percent	\N	2026-02-23 21:49:50.345+00
\N	260	cpu_usage_percent	23.428618421036703	percent	\N	2026-02-23 21:50:50.345+00
\N	260	cpu_usage_percent	23.44287280698937	percent	\N	2026-02-23 21:51:50.345+00
\N	260	cpu_usage_percent	23.392763157883707	percent	\N	2026-02-23 21:52:50.345+00
\N	260	cpu_usage_percent	23.375548245661008	percent	\N	2026-02-23 21:53:50.345+00
\N	260	cpu_usage_percent	23.35065789477852	percent	\N	2026-02-23 21:54:50.345+00
\N	260	cpu_usage_percent	23.404605263157904	percent	\N	2026-02-23 21:55:50.345+00
\N	260	cpu_usage_percent	23.433004386014346	percent	\N	2026-02-23 21:56:50.345+00
\N	257	cpu_usage_percent	4.434210526299466	percent	\N	2026-02-23 22:24:51.899+00
\N	257	cpu_usage_percent	4.161403508746616	percent	\N	2026-02-23 22:25:51.899+00
\N	257	cpu_usage_percent	4.185087719315405	percent	\N	2026-02-23 22:26:51.899+00
\N	257	cpu_usage_percent	4.328070175405102	percent	\N	2026-02-23 22:27:51.899+00
\N	257	cpu_usage_percent	4.7456140350754765	percent	\N	2026-02-23 22:28:51.899+00
\N	257	cpu_usage_percent	4.902631578938397	percent	\N	2026-02-23 22:29:51.899+00
\N	257	cpu_usage_percent	5.048245614039189	percent	\N	2026-02-23 22:30:51.899+00
\N	133	cpu_usage_percent	0.6048245614051524	percent	\N	2026-02-23 21:54:50.418+00
\N	133	cpu_usage_percent	0.6078947368568208	percent	\N	2026-02-23 21:55:50.418+00
\N	133	cpu_usage_percent	0.6171052631301279	percent	\N	2026-02-23 21:56:50.418+00
\N	133	cpu_usage_percent	0.6000000000277907	percent	\N	2026-02-23 21:57:50.418+00
\N	133	cpu_usage_percent	0.35219298242674313	percent	\N	2026-02-23 21:58:50.418+00
\N	133	cpu_usage_percent	0.4745614035627028	percent	\N	2026-02-23 21:59:50.418+00
\N	133	cpu_usage_percent	0.4815789473880443	percent	\N	2026-02-23 22:00:50.418+00
\N	133	cpu_usage_percent	0.4635964912820043	percent	\N	2026-02-23 22:01:50.418+00
\N	133	cpu_usage_percent	0.4732456139142016	percent	\N	2026-02-23 22:02:50.418+00
\N	257	cpu_usage_percent	5.263157894736864	percent	\N	2026-02-23 22:31:51.899+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	\N	2026-02-23 23:42:56.347+00
\N	133	cpu_usage_percent	0.5385964911986747	percent	\N	2026-02-23 22:03:50.418+00
\N	133	cpu_usage_percent	0.5679824561485276	percent	\N	2026-02-23 22:04:50.418+00
\N	133	cpu_usage_percent	0.5640350876931564	percent	\N	2026-02-23 22:05:50.418+00
\N	133	cpu_usage_percent	0.5785087719478099	percent	\N	2026-02-23 22:06:50.418+00
\N	257	cpu_usage_percent	4.981578947351267	percent	\N	2026-02-23 22:32:51.899+00
\N	257	cpu_usage_percent	4.651754385926537	percent	\N	2026-02-23 22:33:51.899+00
\N	257	cpu_usage_percent	4.465789473697285	percent	\N	2026-02-23 22:34:51.899+00
\N	257	cpu_usage_percent	3.9315789473537137	percent	\N	2026-02-23 22:35:51.899+00
\N	257	cpu_usage_percent	4.18947368421135	percent	\N	2026-02-23 22:36:51.899+00
\N	236	cpu_usage_percent	1.4736842104282886	percent	\N	2026-02-23 23:43:56.347+00
\N	236	cpu_usage_percent	1.409834454985159	percent	\N	2026-02-23 23:44:56.347+00
\N	236	cpu_usage_percent	1.550877192956321	percent	\N	2026-02-23 21:54:50.481+00
\N	236	cpu_usage_percent	1.5614035088373015	percent	\N	2026-02-23 21:55:50.481+00
\N	236	cpu_usage_percent	1.561403508673905	percent	\N	2026-02-23 21:56:50.481+00
\N	236	cpu_usage_percent	1.564912280688688	percent	\N	2026-02-23 21:57:50.481+00
\N	236	cpu_usage_percent	1.3017543859518526	percent	\N	2026-02-23 21:58:50.481+00
\N	236	cpu_usage_percent	1.4210526316769858	percent	\N	2026-02-23 21:59:50.481+00
\N	236	cpu_usage_percent	1.4245614035283864	percent	\N	2026-02-23 22:00:50.481+00
\N	236	cpu_usage_percent	1.4210526315136036	percent	\N	2026-02-23 22:01:50.481+00
\N	236	cpu_usage_percent	1.4140350876474201	percent	\N	2026-02-23 22:02:50.481+00
\N	236	cpu_usage_percent	1.4210526315136036	percent	\N	2026-02-23 22:03:50.481+00
\N	236	cpu_usage_percent	1.589473684138639	percent	\N	2026-02-23 22:04:50.481+00
\N	236	cpu_usage_percent	1.6350877191871547	percent	\N	2026-02-23 22:05:50.481+00
\N	236	cpu_usage_percent	1.6666666666666714	percent	\N	2026-02-23 22:06:50.481+00
\N	236	cpu_usage_percent	1.592982456153436	percent	\N	2026-02-23 23:45:56.347+00
\N	236	cpu_usage_percent	1.6350877193505369	percent	\N	2026-02-23 23:46:56.347+00
\N	260	cpu_usage_percent	23.34309210524927	percent	\N	2026-02-23 22:24:51.967+00
\N	260	cpu_usage_percent	23.388048245636924	percent	\N	2026-02-23 22:25:51.967+00
\N	248	cpu_usage_percent	2.4785087719608754	percent	\N	2026-02-23 21:54:50.543+00
\N	248	cpu_usage_percent	2.614473684306944	percent	\N	2026-02-23 21:55:50.543+00
\N	248	cpu_usage_percent	2.595175438511532	percent	\N	2026-02-23 21:56:50.543+00
\N	248	cpu_usage_percent	2.684210526323966	percent	\N	2026-02-23 21:57:50.543+00
\N	248	cpu_usage_percent	2.5824561403868387	percent	\N	2026-02-23 21:58:50.543+00
\N	248	cpu_usage_percent	2.547368421096749	percent	\N	2026-02-23 21:59:50.543+00
\N	248	cpu_usage_percent	2.730263157894754	percent	\N	2026-02-23 22:00:50.543+00
\N	248	cpu_usage_percent	2.726754385961655	percent	\N	2026-02-23 22:01:50.543+00
\N	248	cpu_usage_percent	2.6206140351694245	percent	\N	2026-02-23 22:02:50.543+00
\N	248	cpu_usage_percent	2.580263157979715	percent	\N	2026-02-23 22:03:50.543+00
\N	248	cpu_usage_percent	2.554824561444363	percent	\N	2026-02-23 22:04:50.543+00
\N	248	cpu_usage_percent	2.385964912337897	percent	\N	2026-02-23 22:05:50.543+00
\N	248	cpu_usage_percent	2.4030701754402344	percent	\N	2026-02-23 22:06:50.543+00
\N	260	cpu_usage_percent	23.348245614059195	percent	\N	2026-02-23 22:26:51.967+00
\N	260	cpu_usage_percent	23.387171052643424	percent	\N	2026-02-23 22:27:51.967+00
\N	260	cpu_usage_percent	23.371600877144388	percent	\N	2026-02-23 22:28:51.967+00
\N	260	cpu_usage_percent	23.376206140362726	percent	\N	2026-02-23 22:29:51.967+00
\N	260	cpu_usage_percent	23.395285087723394	percent	\N	2026-02-23 22:30:51.967+00
\N	260	cpu_usage_percent	23.35328947371812	percent	\N	2026-02-23 22:31:51.967+00
\N	260	cpu_usage_percent	23.481688596463457	percent	\N	2026-02-23 22:32:51.967+00
\N	252	cpu_usage_percent	24.57500000000246	percent	\N	2026-02-23 21:54:50.609+00
\N	252	cpu_usage_percent	24.643859649158756	percent	\N	2026-02-23 21:55:50.609+00
\N	252	cpu_usage_percent	24.65833333333171	percent	\N	2026-02-23 21:56:50.609+00
\N	252	cpu_usage_percent	24.61885964912527	percent	\N	2026-02-23 21:57:50.609+00
\N	252	cpu_usage_percent	24.53377192980905	percent	\N	2026-02-23 21:58:50.609+00
\N	252	cpu_usage_percent	24.458333333390527	percent	\N	2026-02-23 21:59:50.609+00
\N	252	cpu_usage_percent	24.83464912278579	percent	\N	2026-02-23 22:00:50.609+00
\N	252	cpu_usage_percent	23.785526315771506	percent	\N	2026-02-23 22:01:50.609+00
\N	252	cpu_usage_percent	23.598684210518144	percent	\N	2026-02-23 22:02:50.609+00
\N	252	cpu_usage_percent	23.30175438595593	percent	\N	2026-02-23 22:03:50.609+00
\N	252	cpu_usage_percent	23.177631578996397	percent	\N	2026-02-23 22:04:50.609+00
\N	252	cpu_usage_percent	23.072368421044473	percent	\N	2026-02-23 22:05:50.609+00
\N	252	cpu_usage_percent	23.97061403507874	percent	\N	2026-02-23 22:06:50.609+00
\N	260	cpu_usage_percent	23.53750000000123	percent	\N	2026-02-23 22:33:51.967+00
\N	260	cpu_usage_percent	23.604495614040005	percent	\N	2026-02-23 22:34:51.967+00
\N	260	cpu_usage_percent	23.54583333332191	percent	\N	2026-02-23 22:35:51.967+00
\N	260	cpu_usage_percent	23.594298245611995	percent	\N	2026-02-23 22:36:51.967+00
\N	257	cpu_usage_percent	4.33333333335581	percent	\N	2026-02-23 21:54:50.678+00
\N	257	cpu_usage_percent	4.070175438608757	percent	\N	2026-02-23 21:55:50.678+00
\N	257	cpu_usage_percent	4.070175438588336	percent	\N	2026-02-23 21:56:50.678+00
\N	257	cpu_usage_percent	4.298245614024893	percent	\N	2026-02-23 21:57:50.678+00
\N	257	cpu_usage_percent	4.264035087738506	percent	\N	2026-02-23 21:58:50.678+00
\N	257	cpu_usage_percent	4.817543859652801	percent	\N	2026-02-23 21:59:50.678+00
\N	257	cpu_usage_percent	5.23333333331577	percent	\N	2026-02-23 22:00:50.678+00
\N	257	cpu_usage_percent	5.154385964882465	percent	\N	2026-02-23 22:01:50.678+00
\N	257	cpu_usage_percent	4.8377192982374595	percent	\N	2026-02-23 22:02:50.678+00
\N	257	cpu_usage_percent	4.467543859622992	percent	\N	2026-02-23 22:03:50.678+00
\N	257	cpu_usage_percent	4.248245614049793	percent	\N	2026-02-23 22:04:50.678+00
\N	257	cpu_usage_percent	4.0245614035193995	percent	\N	2026-02-23 22:05:50.678+00
\N	257	cpu_usage_percent	4.1359649122929625	percent	\N	2026-02-23 22:06:50.678+00
\N	248	cpu_usage_percent	2.8171052631366678	percent	\N	2026-02-23 23:34:56.419+00
\N	248	cpu_usage_percent	2.84824561405307	percent	\N	2026-02-23 23:35:56.419+00
\N	248	cpu_usage_percent	2.8324561403541537	percent	\N	2026-02-23 23:36:56.419+00
\N	133	cpu_usage_percent	0.5320175438547636	percent	\N	2026-02-23 22:34:53.778+00
\N	133	cpu_usage_percent	0.4236842104920129	percent	\N	2026-02-23 22:35:53.778+00
\N	133	cpu_usage_percent	0.5350877193064321	percent	\N	2026-02-23 22:36:53.778+00
\N	260	cpu_usage_percent	23.35065789477852	percent	\N	2026-02-23 21:54:50.746+00
\N	260	cpu_usage_percent	23.404605263157904	percent	\N	2026-02-23 21:55:50.746+00
\N	260	cpu_usage_percent	23.433004386014346	percent	\N	2026-02-23 21:56:50.746+00
\N	260	cpu_usage_percent	23.44221491229787	percent	\N	2026-02-23 21:57:50.746+00
\N	260	cpu_usage_percent	23.467653508741307	percent	\N	2026-02-23 21:58:50.746+00
\N	260	cpu_usage_percent	23.44989035088618	percent	\N	2026-02-23 21:59:50.746+00
\N	260	cpu_usage_percent	23.501535087687046	percent	\N	2026-02-23 22:00:50.746+00
\N	260	cpu_usage_percent	23.474561403517768	percent	\N	2026-02-23 22:01:50.746+00
\N	260	cpu_usage_percent	23.47872807020363	percent	\N	2026-02-23 22:02:50.746+00
\N	260	cpu_usage_percent	23.41853070172907	percent	\N	2026-02-23 22:03:50.746+00
\N	260	cpu_usage_percent	23.44221491229787	percent	\N	2026-02-23 22:04:50.746+00
\N	260	cpu_usage_percent	23.42423245608971	percent	\N	2026-02-23 22:05:50.746+00
\N	260	cpu_usage_percent	23.488925438590783	percent	\N	2026-02-23 22:06:50.746+00
\N	133	cpu_usage_percent	0.5157894737152731	percent	\N	2026-02-23 22:37:53.778+00
\N	133	cpu_usage_percent	0.5381578947581005	percent	\N	2026-02-23 22:38:53.778+00
\N	248	cpu_usage_percent	2.991666666583342	percent	\N	2026-02-23 23:37:56.419+00
\N	133	cpu_usage_percent	0.42894736835080494	percent	\N	2026-02-23 22:39:53.778+00
\N	133	cpu_usage_percent	0.4271929824251117	percent	\N	2026-02-23 22:40:53.778+00
\N	133	cpu_usage_percent	0.4350877192949838	percent	\N	2026-02-23 22:41:53.778+00
\N	133	cpu_usage_percent	0.4421052631611815	percent	\N	2026-02-23 22:42:53.778+00
\N	133	cpu_usage_percent	0.4333333333284486	percent	\N	2026-02-23 22:43:53.778+00
\N	133	cpu_usage_percent	0.5140350877895656	percent	\N	2026-02-23 22:44:53.778+00
\N	133	cpu_usage_percent	0.5679824561485276	percent	\N	2026-02-23 22:04:50.819+00
\N	133	cpu_usage_percent	0.5640350876931564	percent	\N	2026-02-23 22:05:50.819+00
\N	133	cpu_usage_percent	0.5785087719478099	percent	\N	2026-02-23 22:06:50.819+00
\N	133	cpu_usage_percent	0.5732456139256215	percent	\N	2026-02-23 22:07:50.819+00
\N	133	cpu_usage_percent	0.4758771930069656	percent	\N	2026-02-23 22:08:50.819+00
\N	133	cpu_usage_percent	0.35833333333008	percent	\N	2026-02-23 22:09:50.819+00
\N	133	cpu_usage_percent	0.4364035087392608	percent	\N	2026-02-23 22:10:50.819+00
\N	133	cpu_usage_percent	0.4451754385719937	percent	\N	2026-02-23 22:11:50.819+00
\N	133	cpu_usage_percent	0.42982456147704795	percent	\N	2026-02-23 22:12:50.819+00
\N	133	cpu_usage_percent	0.4368421053023752	percent	\N	2026-02-23 22:13:50.819+00
\N	133	cpu_usage_percent	0.4442982455274489	percent	\N	2026-02-23 22:14:50.819+00
\N	133	cpu_usage_percent	0.5688596491930724	percent	\N	2026-02-23 22:15:50.819+00
\N	133	cpu_usage_percent	0.5596491228789091	percent	\N	2026-02-23 22:16:50.819+00
\N	133	cpu_usage_percent	0.5214912280554813	percent	\N	2026-02-23 22:45:53.778+00
\N	133	cpu_usage_percent	0.5043859648306039	percent	\N	2026-02-23 22:46:53.778+00
\N	248	cpu_usage_percent	2.9508771930347564	percent	\N	2026-02-23 23:38:56.419+00
\N	248	cpu_usage_percent	2.977631578891831	percent	\N	2026-02-23 23:39:56.419+00
\N	248	cpu_usage_percent	2.9004385964454826	percent	\N	2026-02-23 23:40:56.419+00
\N	248	cpu_usage_percent	2.968421052659366	percent	\N	2026-02-23 23:41:56.419+00
\N	248	cpu_usage_percent	2.958333333341514	percent	\N	2026-02-23 23:42:56.419+00
\N	236	cpu_usage_percent	1.589473684138639	percent	\N	2026-02-23 22:04:50.893+00
\N	236	cpu_usage_percent	1.6350877191871547	percent	\N	2026-02-23 22:05:50.893+00
\N	236	cpu_usage_percent	1.6666666666666714	percent	\N	2026-02-23 22:06:50.893+00
\N	236	cpu_usage_percent	1.7789473685256354	percent	\N	2026-02-23 22:07:50.893+00
\N	236	cpu_usage_percent	1.687719298265236	percent	\N	2026-02-23 22:08:50.893+00
\N	236	cpu_usage_percent	1.466666666562105	percent	\N	2026-02-23 22:09:50.893+00
\N	236	cpu_usage_percent	1.603508771871006	percent	\N	2026-02-23 22:10:50.893+00
\N	236	cpu_usage_percent	1.5473684209415381	percent	\N	2026-02-23 22:11:50.893+00
\N	236	cpu_usage_percent	1.498245614041636	percent	\N	2026-02-23 22:12:50.893+00
\N	236	cpu_usage_percent	1.4666666667255015	percent	\N	2026-02-23 22:13:50.893+00
\N	236	cpu_usage_percent	1.4666666667255015	percent	\N	2026-02-23 22:14:50.893+00
\N	236	cpu_usage_percent	1.638596491365334	percent	\N	2026-02-23 22:15:50.893+00
\N	236	cpu_usage_percent	1.656140350785705	percent	\N	2026-02-23 22:16:50.893+00
\N	248	cpu_usage_percent	3.1587719298049564	percent	\N	2026-02-23 23:43:56.419+00
\N	248	cpu_usage_percent	3.1802631579666354	percent	\N	2026-02-23 23:44:56.419+00
\N	236	cpu_usage_percent	1.6350877193505369	percent	\N	2026-02-23 22:34:53.849+00
\N	236	cpu_usage_percent	1.5017543860564189	percent	\N	2026-02-23 22:35:53.849+00
\N	236	cpu_usage_percent	1.6245614034695706	percent	\N	2026-02-23 22:36:53.849+00
\N	236	cpu_usage_percent	1.6526315789343045	percent	\N	2026-02-23 22:37:53.849+00
\N	236	cpu_usage_percent	1.617543859603387	percent	\N	2026-02-23 22:38:53.849+00
\N	248	cpu_usage_percent	2.554824561444363	percent	\N	2026-02-23 22:04:50.963+00
\N	248	cpu_usage_percent	2.385964912337897	percent	\N	2026-02-23 22:05:50.963+00
\N	248	cpu_usage_percent	2.4030701754402344	percent	\N	2026-02-23 22:06:50.963+00
\N	248	cpu_usage_percent	2.392105263159536	percent	\N	2026-02-23 22:07:50.963+00
\N	248	cpu_usage_percent	2.4385964912934384	percent	\N	2026-02-23 22:08:50.963+00
\N	248	cpu_usage_percent	2.4162280702097547	percent	\N	2026-02-23 22:09:50.963+00
\N	248	cpu_usage_percent	2.49473684210038	percent	\N	2026-02-23 22:10:50.963+00
\N	248	cpu_usage_percent	2.4210526316279726	percent	\N	2026-02-23 22:11:50.963+00
\N	248	cpu_usage_percent	2.4653508771913692	percent	\N	2026-02-23 22:12:50.963+00
\N	248	cpu_usage_percent	2.4175438596131897	percent	\N	2026-02-23 22:13:50.963+00
\N	248	cpu_usage_percent	2.3026315790290823	percent	\N	2026-02-23 22:14:50.963+00
\N	248	cpu_usage_percent	2.4557017543957755	percent	\N	2026-02-23 22:15:50.963+00
\N	248	cpu_usage_percent	2.5785087719314674	percent	\N	2026-02-23 22:16:50.963+00
\N	236	cpu_usage_percent	1.5017543860564189	percent	\N	2026-02-23 22:39:53.849+00
\N	236	cpu_usage_percent	1.494736842026839	percent	\N	2026-02-23 22:40:53.849+00
\N	236	cpu_usage_percent	1.5052631579078195	percent	\N	2026-02-23 22:41:53.849+00
\N	236	cpu_usage_percent	1.512280701774003	percent	\N	2026-02-23 22:42:53.849+00
\N	236	cpu_usage_percent	1.5157894736253894	percent	\N	2026-02-23 22:43:53.849+00
\N	236	cpu_usage_percent	1.6350877193505369	percent	\N	2026-02-23 22:44:53.849+00
\N	236	cpu_usage_percent	1.6526315789343045	percent	\N	2026-02-23 22:45:53.849+00
\N	252	cpu_usage_percent	23.177631578996397	percent	\N	2026-02-23 22:04:51.026+00
\N	252	cpu_usage_percent	23.072368421044473	percent	\N	2026-02-23 22:05:51.026+00
\N	252	cpu_usage_percent	23.97061403507874	percent	\N	2026-02-23 22:06:51.026+00
\N	252	cpu_usage_percent	23.851315789496567	percent	\N	2026-02-23 22:07:51.026+00
\N	252	cpu_usage_percent	23.959210526357467	percent	\N	2026-02-23 22:08:51.026+00
\N	252	cpu_usage_percent	23.867543859615637	percent	\N	2026-02-23 22:09:51.026+00
\N	252	cpu_usage_percent	24.00657894739294	percent	\N	2026-02-23 22:10:51.026+00
\N	252	cpu_usage_percent	23.907017543862935	percent	\N	2026-02-23 22:11:51.026+00
\N	252	cpu_usage_percent	23.883333333334974	percent	\N	2026-02-23 22:12:51.026+00
\N	252	cpu_usage_percent	23.73245614033455	percent	\N	2026-02-23 22:13:51.026+00
\N	252	cpu_usage_percent	23.6934210526708	percent	\N	2026-02-23 22:14:51.026+00
\N	252	cpu_usage_percent	24.255263157956833	percent	\N	2026-02-23 22:15:51.026+00
\N	252	cpu_usage_percent	24.621491228095508	percent	\N	2026-02-23 22:16:51.026+00
\N	236	cpu_usage_percent	1.494736842026839	percent	\N	2026-02-23 22:46:53.849+00
\N	248	cpu_usage_percent	3.2057017543794473	percent	\N	2026-02-23 23:45:56.419+00
\N	248	cpu_usage_percent	3.131140350944193	percent	\N	2026-02-23 23:46:56.419+00
\N	257	cpu_usage_percent	4.248245614049793	percent	\N	2026-02-23 22:04:51.084+00
\N	257	cpu_usage_percent	4.0245614035193995	percent	\N	2026-02-23 22:05:51.084+00
\N	257	cpu_usage_percent	4.1359649122929625	percent	\N	2026-02-23 22:06:51.084+00
\N	257	cpu_usage_percent	4.288596491239517	percent	\N	2026-02-23 22:07:51.084+00
\N	257	cpu_usage_percent	4.504385964900038	percent	\N	2026-02-23 22:08:51.084+00
\N	257	cpu_usage_percent	4.644736842101196	percent	\N	2026-02-23 22:09:51.084+00
\N	257	cpu_usage_percent	5.252631578937567	percent	\N	2026-02-23 22:10:51.084+00
\N	257	cpu_usage_percent	5.250877192971032	percent	\N	2026-02-23 22:11:51.084+00
\N	257	cpu_usage_percent	4.967543859680177	percent	\N	2026-02-23 22:12:51.084+00
\N	257	cpu_usage_percent	4.603508771948626	percent	\N	2026-02-23 22:13:51.084+00
\N	257	cpu_usage_percent	4.178070175449221	percent	\N	2026-02-23 22:14:51.084+00
\N	257	cpu_usage_percent	4.14736842103467	percent	\N	2026-02-23 22:15:51.084+00
\N	257	cpu_usage_percent	4.1333333333431455	percent	\N	2026-02-23 22:16:51.084+00
\N	248	cpu_usage_percent	2.8092105263484797	percent	\N	2026-02-23 22:34:53.913+00
\N	248	cpu_usage_percent	2.6749999999281187	percent	\N	2026-02-23 22:35:53.913+00
\N	248	cpu_usage_percent	2.7986842105492116	percent	\N	2026-02-23 22:36:53.913+00
\N	248	cpu_usage_percent	2.7491228070044826	percent	\N	2026-02-23 22:37:53.913+00
\N	248	cpu_usage_percent	2.6346491228200932	percent	\N	2026-02-23 22:38:53.913+00
\N	248	cpu_usage_percent	2.606140350914785	percent	\N	2026-02-23 22:39:53.913+00
\N	248	cpu_usage_percent	2.657017543903777	percent	\N	2026-02-23 22:40:53.913+00
\N	260	cpu_usage_percent	23.44221491229787	percent	\N	2026-02-23 22:04:51.145+00
\N	260	cpu_usage_percent	23.42423245608971	percent	\N	2026-02-23 22:05:51.145+00
\N	260	cpu_usage_percent	23.488925438590783	percent	\N	2026-02-23 22:06:51.145+00
\N	260	cpu_usage_percent	23.517214912265587	percent	\N	2026-02-23 22:07:51.145+00
\N	260	cpu_usage_percent	23.50230263158059	percent	\N	2026-02-23 22:08:51.145+00
\N	260	cpu_usage_percent	23.549232456134632	percent	\N	2026-02-23 22:09:51.145+00
\N	260	cpu_usage_percent	23.554276315834414	percent	\N	2026-02-23 22:10:51.145+00
\N	260	cpu_usage_percent	23.474451754407625	percent	\N	2026-02-23 22:11:51.145+00
\N	260	cpu_usage_percent	23.447807017517732	percent	\N	2026-02-23 22:12:51.145+00
\N	260	cpu_usage_percent	23.43870614034435	percent	\N	2026-02-23 22:13:51.145+00
\N	260	cpu_usage_percent	23.425548245636094	percent	\N	2026-02-23 22:14:51.145+00
\N	260	cpu_usage_percent	23.354605263172616	percent	\N	2026-02-23 22:15:51.145+00
\N	260	cpu_usage_percent	23.41195175435452	percent	\N	2026-02-23 22:16:51.145+00
\N	248	cpu_usage_percent	2.8043859648894056	percent	\N	2026-02-23 22:41:53.913+00
\N	248	cpu_usage_percent	2.8921052631758783	percent	\N	2026-02-23 22:42:53.913+00
\N	248	cpu_usage_percent	2.9745614035626886	percent	\N	2026-02-23 22:43:53.913+00
\N	248	cpu_usage_percent	2.8758771929138476	percent	\N	2026-02-23 22:44:53.913+00
\N	248	cpu_usage_percent	2.935526315817256	percent	\N	2026-02-23 22:45:53.913+00
\N	248	cpu_usage_percent	2.833771929880129	percent	\N	2026-02-23 22:46:53.913+00
\N	133	cpu_usage_percent	0.4442982455274489	percent	\N	2026-02-23 22:14:51.224+00
\N	133	cpu_usage_percent	0.5688596491930724	percent	\N	2026-02-23 22:15:51.224+00
\N	133	cpu_usage_percent	0.5596491228789091	percent	\N	2026-02-23 22:16:51.224+00
\N	133	cpu_usage_percent	0.5574561403901015	percent	\N	2026-02-23 22:17:51.224+00
\N	133	cpu_usage_percent	0.4644736842040089	percent	\N	2026-02-23 22:18:51.224+00
\N	133	cpu_usage_percent	0.3951754386275468	percent	\N	2026-02-23 22:19:51.224+00
\N	133	cpu_usage_percent	0.45877192974124625	percent	\N	2026-02-23 22:20:51.224+00
\N	133	cpu_usage_percent	0.4644736842040089	percent	\N	2026-02-23 22:21:51.224+00
\N	133	cpu_usage_percent	0.45921052630436066	percent	\N	2026-02-23 22:22:51.224+00
\N	133	cpu_usage_percent	0.4719298245516086	percent	\N	2026-02-23 22:23:51.224+00
\N	133	cpu_usage_percent	0.6131578947564549	percent	\N	2026-02-23 22:24:51.224+00
\N	133	cpu_usage_percent	0.5785087719886661	percent	\N	2026-02-23 22:25:51.224+00
\N	133	cpu_usage_percent	0.5614035088046165	percent	\N	2026-02-23 22:26:51.224+00
\N	252	cpu_usage_percent	24.132017543858026	percent	\N	2026-02-23 23:34:56.479+00
\N	252	cpu_usage_percent	24.031140350904153	percent	\N	2026-02-23 23:35:56.479+00
\N	252	cpu_usage_percent	23.937719298195788	percent	\N	2026-02-23 23:36:56.479+00
\N	252	cpu_usage_percent	23.9070175438425	percent	\N	2026-02-23 23:37:56.479+00
\N	252	cpu_usage_percent	23.802192982474125	percent	\N	2026-02-23 23:38:56.479+00
\N	252	cpu_usage_percent	23.691666666642988	percent	\N	2026-02-23 23:39:56.479+00
\N	252	cpu_usage_percent	24.758333333343145	percent	\N	2026-02-23 22:34:53.988+00
\N	236	cpu_usage_percent	1.4666666667255015	percent	\N	2026-02-23 22:14:51.3+00
\N	236	cpu_usage_percent	1.638596491365334	percent	\N	2026-02-23 22:15:51.3+00
\N	236	cpu_usage_percent	1.656140350785705	percent	\N	2026-02-23 22:16:51.3+00
\N	236	cpu_usage_percent	1.673684210532869	percent	\N	2026-02-23 22:17:51.3+00
\N	236	cpu_usage_percent	1.6842105264138354	percent	\N	2026-02-23 22:18:51.3+00
\N	236	cpu_usage_percent	1.5368421053873504	percent	\N	2026-02-23 22:19:51.3+00
\N	236	cpu_usage_percent	1.4491228069783375	percent	\N	2026-02-23 22:20:51.3+00
\N	236	cpu_usage_percent	1.449122807141734	percent	\N	2026-02-23 22:21:51.3+00
\N	236	cpu_usage_percent	1.442105263112154	percent	\N	2026-02-23 22:22:51.3+00
\N	236	cpu_usage_percent	1.442105263112154	percent	\N	2026-02-23 22:23:51.3+00
\N	236	cpu_usage_percent	1.5719298245548714	percent	\N	2026-02-23 22:24:51.3+00
\N	236	cpu_usage_percent	1.617543859603387	percent	\N	2026-02-23 22:25:51.3+00
\N	236	cpu_usage_percent	1.603508771871006	percent	\N	2026-02-23 22:26:51.3+00
\N	252	cpu_usage_percent	24.403947368407174	percent	\N	2026-02-23 22:35:53.988+00
\N	252	cpu_usage_percent	25.648245614046544	percent	\N	2026-02-23 22:36:53.988+00
\N	252	cpu_usage_percent	25.775438596478168	percent	\N	2026-02-23 22:37:53.988+00
\N	252	cpu_usage_percent	25.806578947353714	percent	\N	2026-02-23 22:38:53.988+00
\N	252	cpu_usage_percent	25.78552631581644	percent	\N	2026-02-23 22:39:53.988+00
\N	252	cpu_usage_percent	25.599561403505504	percent	\N	2026-02-23 22:40:53.988+00
\N	252	cpu_usage_percent	24.511403508786643	percent	\N	2026-02-23 22:41:53.988+00
\N	248	cpu_usage_percent	2.3026315790290823	percent	\N	2026-02-23 22:14:51.386+00
\N	248	cpu_usage_percent	2.4557017543957755	percent	\N	2026-02-23 22:15:51.386+00
\N	248	cpu_usage_percent	2.5785087719314674	percent	\N	2026-02-23 22:16:51.386+00
\N	248	cpu_usage_percent	2.6026315790225425	percent	\N	2026-02-23 22:17:51.386+00
\N	248	cpu_usage_percent	2.7416666666568688	percent	\N	2026-02-23 22:18:51.386+00
\N	248	cpu_usage_percent	2.8460526315642483	percent	\N	2026-02-23 22:19:51.386+00
\N	248	cpu_usage_percent	2.7271929824430856	percent	\N	2026-02-23 22:20:51.386+00
\N	248	cpu_usage_percent	2.612719298299538	percent	\N	2026-02-23 22:21:51.386+00
\N	248	cpu_usage_percent	2.6271929823907954	percent	\N	2026-02-23 22:22:51.386+00
\N	248	cpu_usage_percent	2.4144736842432053	percent	\N	2026-02-23 22:23:51.386+00
\N	248	cpu_usage_percent	2.3144736842726275	percent	\N	2026-02-23 22:24:51.386+00
\N	248	cpu_usage_percent	2.3390350877634347	percent	\N	2026-02-23 22:25:51.386+00
\N	248	cpu_usage_percent	2.3916666666781197	percent	\N	2026-02-23 22:26:51.386+00
\N	252	cpu_usage_percent	24.696052631571604	percent	\N	2026-02-23 22:42:53.988+00
\N	252	cpu_usage_percent	24.601315789459804	percent	\N	2026-02-23 22:43:53.988+00
\N	252	cpu_usage_percent	24.314912280656003	percent	\N	2026-02-23 22:44:53.988+00
\N	252	cpu_usage_percent	24.42368421052062	percent	\N	2026-02-23 22:45:53.988+00
\N	252	cpu_usage_percent	24.12192982454016	percent	\N	2026-02-23 22:46:53.988+00
\N	252	cpu_usage_percent	23.834210526332953	percent	\N	2026-02-23 23:40:56.479+00
\N	252	cpu_usage_percent	24.169298245575646	percent	\N	2026-02-23 23:41:56.479+00
\N	252	cpu_usage_percent	23.6934210526708	percent	\N	2026-02-23 22:14:51.456+00
\N	252	cpu_usage_percent	24.255263157956833	percent	\N	2026-02-23 22:15:51.456+00
\N	252	cpu_usage_percent	24.621491228095508	percent	\N	2026-02-23 22:16:51.456+00
\N	252	cpu_usage_percent	24.704824561404337	percent	\N	2026-02-23 22:17:51.456+00
\N	252	cpu_usage_percent	25.182017543876	percent	\N	2026-02-23 22:18:51.456+00
\N	252	cpu_usage_percent	24.94035087719871	percent	\N	2026-02-23 22:19:51.456+00
\N	252	cpu_usage_percent	24.678070175445143	percent	\N	2026-02-23 22:20:51.456+00
\N	252	cpu_usage_percent	24.304824561419863	percent	\N	2026-02-23 22:21:51.456+00
\N	252	cpu_usage_percent	24.19473684213142	percent	\N	2026-02-23 22:22:51.456+00
\N	252	cpu_usage_percent	24.004824561405968	percent	\N	2026-02-23 22:23:51.456+00
\N	252	cpu_usage_percent	23.91842105264547	percent	\N	2026-02-23 22:24:51.456+00
\N	252	cpu_usage_percent	23.89078947370301	percent	\N	2026-02-23 22:25:51.456+00
\N	252	cpu_usage_percent	23.918421052584208	percent	\N	2026-02-23 22:26:51.456+00
\N	252	cpu_usage_percent	24.252192982505164	percent	\N	2026-02-23 23:42:56.479+00
\N	252	cpu_usage_percent	24.33289473684374	percent	\N	2026-02-23 23:43:56.479+00
\N	252	cpu_usage_percent	24.351754385953484	percent	\N	2026-02-23 23:44:56.479+00
\N	252	cpu_usage_percent	24.29035087716521	percent	\N	2026-02-23 23:45:56.479+00
\N	252	cpu_usage_percent	24.284210526261887	percent	\N	2026-02-23 23:46:56.479+00
\N	257	cpu_usage_percent	4.465789473697285	percent	\N	2026-02-23 22:34:54.063+00
\N	257	cpu_usage_percent	3.9315789473537137	percent	\N	2026-02-23 22:35:54.063+00
\N	257	cpu_usage_percent	4.178070175449221	percent	\N	2026-02-23 22:14:51.527+00
\N	257	cpu_usage_percent	4.14736842103467	percent	\N	2026-02-23 22:15:51.527+00
\N	257	cpu_usage_percent	4.1333333333431455	percent	\N	2026-02-23 22:16:51.527+00
\N	257	cpu_usage_percent	4.335964912315831	percent	\N	2026-02-23 22:17:51.527+00
\N	257	cpu_usage_percent	4.18947368421135	percent	\N	2026-02-23 22:36:54.063+00
\N	257	cpu_usage_percent	4.728070175430446	percent	\N	2026-02-23 22:18:51.527+00
\N	257	cpu_usage_percent	4.852631578953108	percent	\N	2026-02-23 22:19:51.527+00
\N	257	cpu_usage_percent	5.2192982456344765	percent	\N	2026-02-23 22:20:51.527+00
\N	257	cpu_usage_percent	5.215789473680957	percent	\N	2026-02-23 22:21:51.527+00
\N	257	cpu_usage_percent	4.974561403485083	percent	\N	2026-02-23 22:22:51.527+00
\N	257	cpu_usage_percent	4.5728070175340605	percent	\N	2026-02-23 22:23:51.527+00
\N	257	cpu_usage_percent	4.434210526299466	percent	\N	2026-02-23 22:24:51.527+00
\N	257	cpu_usage_percent	4.161403508746616	percent	\N	2026-02-23 22:25:51.527+00
\N	257	cpu_usage_percent	4.185087719315405	percent	\N	2026-02-23 22:26:51.527+00
\N	257	cpu_usage_percent	4.3666666666282765	percent	\N	2026-02-23 22:37:54.063+00
\N	257	cpu_usage_percent	4.728070175450867	percent	\N	2026-02-23 22:38:54.063+00
\N	257	cpu_usage_percent	4.86491228067807	percent	\N	2026-02-23 22:39:54.063+00
\N	257	cpu_usage_percent	5.264912280703399	percent	\N	2026-02-23 22:40:54.063+00
\N	257	cpu_usage_percent	5.330701754408025	percent	\N	2026-02-23 22:41:54.063+00
\N	257	cpu_usage_percent	5.134210526297821	percent	\N	2026-02-23 22:42:54.063+00
\N	257	cpu_usage_percent	4.779824561423126	percent	\N	2026-02-23 22:43:54.063+00
\N	260	cpu_usage_percent	23.425548245636094	percent	\N	2026-02-23 22:14:51.588+00
\N	260	cpu_usage_percent	23.354605263172616	percent	\N	2026-02-23 22:15:51.588+00
\N	260	cpu_usage_percent	23.41195175435452	percent	\N	2026-02-23 22:16:51.588+00
\N	260	cpu_usage_percent	23.386184210519374	percent	\N	2026-02-23 22:17:51.588+00
\N	260	cpu_usage_percent	23.442982456150574	percent	\N	2026-02-23 22:18:51.588+00
\N	260	cpu_usage_percent	23.40208333334887	percent	\N	2026-02-23 22:19:51.588+00
\N	260	cpu_usage_percent	23.428070175414504	percent	\N	2026-02-23 22:20:51.588+00
\N	260	cpu_usage_percent	23.39331140350592	percent	\N	2026-02-23 22:21:51.588+00
\N	260	cpu_usage_percent	23.398355263103582	percent	\N	2026-02-23 22:22:51.588+00
\N	260	cpu_usage_percent	23.407346491228083	percent	\N	2026-02-23 22:23:51.588+00
\N	260	cpu_usage_percent	23.34309210524927	percent	\N	2026-02-23 22:24:51.588+00
\N	260	cpu_usage_percent	23.388048245636924	percent	\N	2026-02-23 22:25:51.588+00
\N	260	cpu_usage_percent	23.348245614059195	percent	\N	2026-02-23 22:26:51.588+00
\N	257	cpu_usage_percent	4.491228070191795	percent	\N	2026-02-23 22:44:54.063+00
\N	257	cpu_usage_percent	4.223684210518158	percent	\N	2026-02-23 22:45:54.063+00
\N	257	cpu_usage_percent	4.016666666669948	percent	\N	2026-02-23 22:46:54.063+00
\N	257	cpu_usage_percent	4.203508771943717	percent	\N	2026-02-23 23:34:56.537+00
\N	260	cpu_usage_percent	23.55921052634234	percent	\N	2026-02-23 22:34:54.137+00
\N	260	cpu_usage_percent	23.578947368414944	percent	\N	2026-02-23 22:35:54.137+00
\N	260	cpu_usage_percent	23.546710526325597	percent	\N	2026-02-23 22:36:54.137+00
\N	260	cpu_usage_percent	23.41743421050508	percent	\N	2026-02-23 22:37:54.137+00
\N	260	cpu_usage_percent	23.59682017545167	percent	\N	2026-02-23 22:38:54.137+00
\N	260	cpu_usage_percent	23.974780701733962	percent	\N	2026-02-23 22:39:54.137+00
\N	260	cpu_usage_percent	24.082127193023723	percent	\N	2026-02-23 22:40:54.137+00
\N	260	cpu_usage_percent	24.044078947341063	percent	\N	2026-02-23 22:41:54.137+00
\N	260	cpu_usage_percent	24.095175438642244	percent	\N	2026-02-23 22:42:54.137+00
\N	260	cpu_usage_percent	23.73179824561241	percent	\N	2026-02-23 22:43:54.137+00
\N	260	cpu_usage_percent	23.48760964910565	percent	\N	2026-02-23 22:44:54.137+00
\N	260	cpu_usage_percent	23.403070175411642	percent	\N	2026-02-23 22:45:54.137+00
\N	260	cpu_usage_percent	23.424013157900063	percent	\N	2026-02-23 22:46:54.137+00
\N	257	cpu_usage_percent	4.071929824575307	percent	\N	2026-02-23 23:35:56.537+00
\N	257	cpu_usage_percent	4.092105263149733	percent	\N	2026-02-23 23:36:56.537+00
\N	257	cpu_usage_percent	4.272807017520179	percent	\N	2026-02-23 23:37:56.537+00
\N	257	cpu_usage_percent	4.60877192984826	percent	\N	2026-02-23 23:38:56.537+00
\N	257	cpu_usage_percent	5.0298245613904555	percent	\N	2026-02-23 23:39:56.537+00
\N	257	cpu_usage_percent	5.215789473680957	percent	\N	2026-02-23 23:40:56.537+00
\N	257	cpu_usage_percent	5.271052631586315	percent	\N	2026-02-23 23:41:56.537+00
\N	133	cpu_usage_percent	0.5140350877895656	percent	\N	2026-02-23 22:44:54.202+00
\N	133	cpu_usage_percent	0.5214912280554813	percent	\N	2026-02-23 22:45:54.202+00
\N	133	cpu_usage_percent	0.5043859648306039	percent	\N	2026-02-23 22:46:54.202+00
\N	133	cpu_usage_percent	1.0916666666519745	percent	\N	2026-02-23 22:47:54.202+00
\N	133	cpu_usage_percent	1.4653508771586843	percent	\N	2026-02-23 22:48:54.202+00
\N	133	cpu_usage_percent	1.372807017576548	percent	\N	2026-02-23 22:49:54.202+00
\N	133	cpu_usage_percent	1.3631578947809686	percent	\N	2026-02-23 22:50:54.202+00
\N	133	cpu_usage_percent	1.2692982456320294	percent	\N	2026-02-23 22:51:54.202+00
\N	133	cpu_usage_percent	0.4438596491277167	percent	\N	2026-02-23 22:52:54.202+00
\N	133	cpu_usage_percent	0.434210526250439	percent	\N	2026-02-23 22:53:54.202+00
\N	133	cpu_usage_percent	0.5241228070257336	percent	\N	2026-02-23 22:54:54.202+00
\N	133	cpu_usage_percent	0.5337719297804568	percent	\N	2026-02-23 22:55:54.202+00
\N	133	cpu_usage_percent	0.45921052634521686	percent	\N	2026-02-23 22:56:54.202+00
\N	257	cpu_usage_percent	5.003508771933113	percent	\N	2026-02-23 23:42:56.537+00
\N	257	cpu_usage_percent	4.628070175439419	percent	\N	2026-02-23 23:43:56.537+00
\N	257	cpu_usage_percent	4.200000000010633	percent	\N	2026-02-23 23:44:56.537+00
\N	257	cpu_usage_percent	3.928947368424332	percent	\N	2026-02-23 23:45:56.537+00
\N	257	cpu_usage_percent	4.10877192981151	percent	\N	2026-02-23 23:46:56.537+00
\N	236	cpu_usage_percent	1.6350877193505369	percent	\N	2026-02-23 22:44:54.268+00
\N	236	cpu_usage_percent	1.6526315789343045	percent	\N	2026-02-23 22:45:54.268+00
\N	236	cpu_usage_percent	1.494736842026839	percent	\N	2026-02-23 22:46:54.268+00
\N	236	cpu_usage_percent	1.5964912281682189	percent	\N	2026-02-23 22:47:54.268+00
\N	236	cpu_usage_percent	1.6000000000196195	percent	\N	2026-02-23 22:48:54.268+00
\N	236	cpu_usage_percent	1.4771929824430714	percent	\N	2026-02-23 22:49:54.268+00
\N	236	cpu_usage_percent	1.449122807141734	percent	\N	2026-02-23 22:50:54.268+00
\N	236	cpu_usage_percent	1.3298245614165864	percent	\N	2026-02-23 22:51:54.268+00
\N	236	cpu_usage_percent	1.512280701774003	percent	\N	2026-02-23 22:52:54.268+00
\N	236	cpu_usage_percent	1.522807017491587	percent	\N	2026-02-23 22:53:54.268+00
\N	236	cpu_usage_percent	1.5164805860423343	percent	\N	2026-02-23 22:54:54.268+00
\N	236	cpu_usage_percent	1.6666666666666714	percent	\N	2026-02-23 22:55:54.268+00
\N	236	cpu_usage_percent	1.7017543858342066	percent	\N	2026-02-23 22:56:54.268+00
\N	260	cpu_usage_percent	23.47467105262791	percent	\N	2026-02-23 23:34:56.622+00
\N	260	cpu_usage_percent	23.4016447368368	percent	\N	2026-02-23 23:35:56.622+00
\N	248	cpu_usage_percent	2.8758771929138476	percent	\N	2026-02-23 22:44:54.339+00
\N	248	cpu_usage_percent	2.935526315817256	percent	\N	2026-02-23 22:45:54.339+00
\N	248	cpu_usage_percent	2.833771929880129	percent	\N	2026-02-23 22:46:54.339+00
\N	248	cpu_usage_percent	2.8307017544284605	percent	\N	2026-02-23 22:47:54.339+00
\N	248	cpu_usage_percent	2.6442982455339887	percent	\N	2026-02-23 22:48:54.339+00
\N	248	cpu_usage_percent	2.5991228070894437	percent	\N	2026-02-23 22:49:54.339+00
\N	248	cpu_usage_percent	2.658771929788628	percent	\N	2026-02-23 22:50:54.339+00
\N	248	cpu_usage_percent	2.560964912347714	percent	\N	2026-02-23 22:51:54.339+00
\N	248	cpu_usage_percent	2.6184210525989045	percent	\N	2026-02-23 22:52:54.339+00
\N	248	cpu_usage_percent	2.5679824561730413	percent	\N	2026-02-23 22:53:54.339+00
\N	248	cpu_usage_percent	2.602192982500256	percent	\N	2026-02-23 22:54:54.339+00
\N	248	cpu_usage_percent	2.571491228146982	percent	\N	2026-02-23 22:55:54.339+00
\N	248	cpu_usage_percent	2.562719298273393	percent	\N	2026-02-23 22:56:54.339+00
\N	260	cpu_usage_percent	23.46074561404653	percent	\N	2026-02-23 23:36:56.622+00
\N	260	cpu_usage_percent	23.399122807007345	percent	\N	2026-02-23 23:37:56.622+00
\N	260	cpu_usage_percent	23.418201754378202	percent	\N	2026-02-23 23:38:56.622+00
\N	260	cpu_usage_percent	23.445394736880104	percent	\N	2026-02-23 23:39:56.622+00
\N	260	cpu_usage_percent	23.505263157901695	percent	\N	2026-02-23 23:40:56.622+00
\N	260	cpu_usage_percent	23.530043859643413	percent	\N	2026-02-23 23:41:56.622+00
\N	260	cpu_usage_percent	23.51162280699468	percent	\N	2026-02-23 23:42:56.622+00
\N	252	cpu_usage_percent	24.314912280656003	percent	\N	2026-02-23 22:44:54.397+00
\N	252	cpu_usage_percent	24.42368421052062	percent	\N	2026-02-23 22:45:54.397+00
\N	252	cpu_usage_percent	24.12192982454016	percent	\N	2026-02-23 22:46:54.397+00
\N	252	cpu_usage_percent	24.39780701754468	percent	\N	2026-02-23 22:47:54.397+00
\N	252	cpu_usage_percent	24.53026315787595	percent	\N	2026-02-23 22:48:54.397+00
\N	252	cpu_usage_percent	24.76184210527623	percent	\N	2026-02-23 22:49:54.397+00
\N	252	cpu_usage_percent	25.175000000009803	percent	\N	2026-02-23 22:50:54.397+00
\N	252	cpu_usage_percent	25.223245614028556	percent	\N	2026-02-23 22:51:54.397+00
\N	252	cpu_usage_percent	25.530701754390066	percent	\N	2026-02-23 22:52:54.397+00
\N	252	cpu_usage_percent	25.471491228049757	percent	\N	2026-02-23 22:53:54.397+00
\N	252	cpu_usage_percent	25.390789473649917	percent	\N	2026-02-23 22:54:54.397+00
\N	252	cpu_usage_percent	25.325877193030664	percent	\N	2026-02-23 22:55:54.397+00
\N	252	cpu_usage_percent	25.474999999962435	percent	\N	2026-02-23 22:56:54.397+00
\N	260	cpu_usage_percent	23.503947368436997	percent	\N	2026-02-23 23:43:56.622+00
\N	260	cpu_usage_percent	23.385307017546324	percent	\N	2026-02-23 23:44:56.622+00
\N	260	cpu_usage_percent	23.38114035086045	percent	\N	2026-02-23 23:45:56.622+00
\N	260	cpu_usage_percent	23.97894736846068	percent	\N	2026-02-23 23:46:56.622+00
\N	257	cpu_usage_percent	4.491228070191795	percent	\N	2026-02-23 22:44:54.453+00
\N	257	cpu_usage_percent	4.223684210518158	percent	\N	2026-02-23 22:45:54.453+00
\N	257	cpu_usage_percent	4.016666666669948	percent	\N	2026-02-23 22:46:54.453+00
\N	257	cpu_usage_percent	4.310526315800928	percent	\N	2026-02-23 22:47:54.453+00
\N	257	cpu_usage_percent	4.659649122796409	percent	\N	2026-02-23 22:48:54.453+00
\N	257	cpu_usage_percent	4.853508771936362	percent	\N	2026-02-23 22:49:54.453+00
\N	257	cpu_usage_percent	5.302631578963712	percent	\N	2026-02-23 22:50:54.453+00
\N	257	cpu_usage_percent	5.131578947348018	percent	\N	2026-02-23 22:51:54.453+00
\N	257	cpu_usage_percent	5.125438596485523	percent	\N	2026-02-23 22:52:54.453+00
\N	257	cpu_usage_percent	4.805263157876766	percent	\N	2026-02-23 22:53:54.453+00
\N	257	cpu_usage_percent	4.402631578962897	percent	\N	2026-02-23 22:54:54.453+00
\N	257	cpu_usage_percent	4.237719298250525	percent	\N	2026-02-23 22:55:54.453+00
\N	257	cpu_usage_percent	4.234210526317426	percent	\N	2026-02-23 22:56:54.453+00
\N	133	cpu_usage_percent	0.4241228070142853	percent	\N	2026-02-23 23:44:56.694+00
\N	133	cpu_usage_percent	0.48815789473195537	percent	\N	2026-02-23 23:45:56.694+00
\N	133	cpu_usage_percent	0.5245614034254515	percent	\N	2026-02-23 23:46:56.694+00
\N	260	cpu_usage_percent	23.48760964910565	percent	\N	2026-02-23 22:44:54.518+00
\N	260	cpu_usage_percent	23.403070175411642	percent	\N	2026-02-23 22:45:54.518+00
\N	260	cpu_usage_percent	23.424013157900063	percent	\N	2026-02-23 22:46:54.518+00
\N	260	cpu_usage_percent	23.42138157892981	percent	\N	2026-02-23 22:47:54.518+00
\N	260	cpu_usage_percent	23.400438596451608	percent	\N	2026-02-23 22:48:54.518+00
\N	260	cpu_usage_percent	23.432675438602217	percent	\N	2026-02-23 22:49:54.518+00
\N	260	cpu_usage_percent	23.365570175412458	percent	\N	2026-02-23 22:50:54.518+00
\N	260	cpu_usage_percent	23.39989035087025	percent	\N	2026-02-23 22:51:54.518+00
\N	260	cpu_usage_percent	23.350657894758086	percent	\N	2026-02-23 22:52:54.518+00
\N	260	cpu_usage_percent	23.432565789502277	percent	\N	2026-02-23 22:53:54.518+00
\N	260	cpu_usage_percent	23.38552631579725	percent	\N	2026-02-23 22:54:54.518+00
\N	260	cpu_usage_percent	23.428508771967415	percent	\N	2026-02-23 22:55:54.518+00
\N	260	cpu_usage_percent	23.46096491228724	percent	\N	2026-02-23 22:56:54.518+00
\N	133	cpu_usage_percent	0.5157894736744169	percent	\N	2026-02-23 23:47:56.694+00
\N	133	cpu_usage_percent	0.531140350932759	percent	\N	2026-02-23 23:48:56.694+00
\N	133	cpu_usage_percent	0.4171052631481018	percent	\N	2026-02-23 23:49:56.694+00
\N	133	cpu_usage_percent	0.43070175439903835	percent	\N	2026-02-23 23:50:56.694+00
\N	133	cpu_usage_percent	0.42017543859977025	percent	\N	2026-02-23 23:51:56.694+00
\N	133	cpu_usage_percent	0.4337719298507068	percent	\N	2026-02-23 23:52:56.694+00
\N	133	cpu_usage_percent	0.4254385964994043	percent	\N	2026-02-23 23:53:56.694+00
\N	133	cpu_usage_percent	0.5241228070257336	percent	\N	2026-02-23 22:54:54.595+00
\N	133	cpu_usage_percent	0.5337719297804568	percent	\N	2026-02-23 22:55:54.595+00
\N	133	cpu_usage_percent	0.45921052634521686	percent	\N	2026-02-23 22:56:54.595+00
\N	133	cpu_usage_percent	0.5451754385834278	percent	\N	2026-02-23 22:57:54.595+00
\N	133	cpu_usage_percent	0.5618421052043487	percent	\N	2026-02-23 22:58:54.595+00
\N	133	cpu_usage_percent	0.44868421046423634	percent	\N	2026-02-23 22:59:54.595+00
\N	133	cpu_usage_percent	0.44122807011662246	percent	\N	2026-02-23 23:00:54.595+00
\N	133	cpu_usage_percent	0.4245614034957157	percent	\N	2026-02-23 23:01:54.595+00
\N	133	cpu_usage_percent	0.4328947369695584	percent	\N	2026-02-23 23:02:54.595+00
\N	133	cpu_usage_percent	0.4258771930216909	percent	\N	2026-02-23 23:03:54.595+00
\N	133	cpu_usage_percent	0.4258771930625329	percent	\N	2026-02-23 23:04:54.595+00
\N	133	cpu_usage_percent	0.5236842105851451	percent	\N	2026-02-23 23:05:54.595+00
\N	133	cpu_usage_percent	0.5355263157878483	percent	\N	2026-02-23 23:06:54.595+00
\N	133	cpu_usage_percent	0.33728070177237157	percent	\N	2026-02-23 23:54:56.694+00
\N	133	cpu_usage_percent	0.42017543864061224	percent	\N	2026-02-23 23:55:56.694+00
\N	133	cpu_usage_percent	0.5228070175406003	percent	\N	2026-02-23 23:56:56.694+00
\N	236	cpu_usage_percent	1.5164805860423343	percent	\N	2026-02-23 22:54:54.662+00
\N	236	cpu_usage_percent	1.6666666666666714	percent	\N	2026-02-23 22:55:54.662+00
\N	236	cpu_usage_percent	1.7017543858342066	percent	\N	2026-02-23 22:56:54.662+00
\N	236	cpu_usage_percent	1.6526315789343045	percent	\N	2026-02-23 22:57:54.662+00
\N	236	cpu_usage_percent	1.6947368421314195	percent	\N	2026-02-23 22:58:54.662+00
\N	236	cpu_usage_percent	1.568421052703485	percent	\N	2026-02-23 22:59:54.662+00
\N	236	cpu_usage_percent	1.52631578950637	percent	\N	2026-02-23 23:00:54.662+00
\N	236	cpu_usage_percent	1.5017543860564189	percent	\N	2026-02-23 23:01:54.662+00
\N	236	cpu_usage_percent	1.5859649122872526	percent	\N	2026-02-23 23:02:54.662+00
\N	236	cpu_usage_percent	1.5789473684210549	percent	\N	2026-02-23 23:03:54.662+00
\N	236	cpu_usage_percent	1.5789473684210549	percent	\N	2026-02-23 23:04:54.662+00
\N	236	cpu_usage_percent	1.726315789447554	percent	\N	2026-02-23 23:05:54.662+00
\N	236	cpu_usage_percent	1.701754385997603	percent	\N	2026-02-23 23:06:54.662+00
\N	236	cpu_usage_percent	1.409834454985159	percent	\N	2026-02-23 23:44:56.774+00
\N	236	cpu_usage_percent	1.592982456153436	percent	\N	2026-02-23 23:45:56.774+00
\N	236	cpu_usage_percent	1.6350877193505369	percent	\N	2026-02-23 23:46:56.774+00
\N	236	cpu_usage_percent	1.645614035068121	percent	\N	2026-02-23 23:47:56.774+00
\N	236	cpu_usage_percent	1.6421052630533381	percent	\N	2026-02-23 23:48:56.774+00
\N	248	cpu_usage_percent	2.602192982500256	percent	\N	2026-02-23 22:54:54.729+00
\N	248	cpu_usage_percent	2.571491228146982	percent	\N	2026-02-23 22:55:54.729+00
\N	248	cpu_usage_percent	2.562719298273393	percent	\N	2026-02-23 22:56:54.729+00
\N	248	cpu_usage_percent	2.5978070176043246	percent	\N	2026-02-23 22:57:54.729+00
\N	248	cpu_usage_percent	2.649561403474479	percent	\N	2026-02-23 22:58:54.729+00
\N	248	cpu_usage_percent	2.5478070175373375	percent	\N	2026-02-23 22:59:54.729+00
\N	248	cpu_usage_percent	2.919736842118354	percent	\N	2026-02-23 23:00:54.729+00
\N	248	cpu_usage_percent	2.8719298245401745	percent	\N	2026-02-23 23:01:54.729+00
\N	248	cpu_usage_percent	2.896929824594096	percent	\N	2026-02-23 23:02:54.729+00
\N	248	cpu_usage_percent	2.7662280702293742	percent	\N	2026-02-23 23:03:54.729+00
\N	248	cpu_usage_percent	2.8640350877519865	percent	\N	2026-02-23 23:04:54.729+00
\N	248	cpu_usage_percent	2.7127192982701445	percent	\N	2026-02-23 23:05:54.729+00
\N	248	cpu_usage_percent	2.8127192982407223	percent	\N	2026-02-23 23:06:54.729+00
\N	236	cpu_usage_percent	1.6280701754843534	percent	\N	2026-02-23 23:49:56.774+00
\N	236	cpu_usage_percent	1.4666666667255015	percent	\N	2026-02-23 23:50:56.774+00
\N	236	cpu_usage_percent	1.4350877192459706	percent	\N	2026-02-23 23:51:56.774+00
\N	236	cpu_usage_percent	1.4350877192459706	percent	\N	2026-02-23 23:52:56.774+00
\N	236	cpu_usage_percent	1.43157894739457	percent	\N	2026-02-23 23:53:56.774+00
\N	236	cpu_usage_percent	1.2877192982194856	percent	\N	2026-02-23 23:54:56.774+00
\N	236	cpu_usage_percent	1.522807017491587	percent	\N	2026-02-23 23:55:56.774+00
\N	252	cpu_usage_percent	25.390789473649917	percent	\N	2026-02-23 22:54:54.784+00
\N	252	cpu_usage_percent	25.325877193030664	percent	\N	2026-02-23 22:55:54.784+00
\N	252	cpu_usage_percent	25.474999999962435	percent	\N	2026-02-23 22:56:54.784+00
\N	252	cpu_usage_percent	25.487719298209683	percent	\N	2026-02-23 22:57:54.784+00
\N	252	cpu_usage_percent	25.38815789476135	percent	\N	2026-02-23 22:58:54.784+00
\N	252	cpu_usage_percent	25.23289473690585	percent	\N	2026-02-23 22:59:54.784+00
\N	252	cpu_usage_percent	25.55570175438271	percent	\N	2026-02-23 23:00:54.784+00
\N	252	cpu_usage_percent	24.48114035091477	percent	\N	2026-02-23 23:01:54.784+00
\N	252	cpu_usage_percent	24.05570175439496	percent	\N	2026-02-23 23:02:54.784+00
\N	252	cpu_usage_percent	23.776315789477778	percent	\N	2026-02-23 23:03:54.784+00
\N	252	cpu_usage_percent	23.394298245640186	percent	\N	2026-02-23 23:04:54.784+00
\N	252	cpu_usage_percent	23.5399122807614	percent	\N	2026-02-23 23:05:54.784+00
\N	252	cpu_usage_percent	24.222807017575732	percent	\N	2026-02-23 23:06:54.784+00
\N	236	cpu_usage_percent	1.5719298247182678	percent	\N	2026-02-23 23:56:56.774+00
\N	257	cpu_usage_percent	4.402631578962897	percent	\N	2026-02-23 22:54:54.841+00
\N	257	cpu_usage_percent	4.237719298250525	percent	\N	2026-02-23 22:55:54.841+00
\N	257	cpu_usage_percent	4.234210526317426	percent	\N	2026-02-23 22:56:54.841+00
\N	257	cpu_usage_percent	4.914035087720947	percent	\N	2026-02-23 22:57:54.841+00
\N	257	cpu_usage_percent	5.2964912280603755	percent	\N	2026-02-23 22:58:54.841+00
\N	257	cpu_usage_percent	5.502631578986595	percent	\N	2026-02-23 22:59:54.841+00
\N	257	cpu_usage_percent	5.856140350857601	percent	\N	2026-02-23 23:00:54.841+00
\N	257	cpu_usage_percent	5.8842105263223345	percent	\N	2026-02-23 23:01:54.841+00
\N	257	cpu_usage_percent	5.095614035095082	percent	\N	2026-02-23 23:02:54.841+00
\N	257	cpu_usage_percent	4.6456140350844635	percent	\N	2026-02-23 23:03:54.841+00
\N	257	cpu_usage_percent	4.239473684196653	percent	\N	2026-02-23 23:04:54.841+00
\N	257	cpu_usage_percent	4.100877193002901	percent	\N	2026-02-23 23:05:54.841+00
\N	257	cpu_usage_percent	4.141228070192611	percent	\N	2026-02-23 23:06:54.841+00
\N	248	cpu_usage_percent	3.1802631579666354	percent	\N	2026-02-23 23:44:56.84+00
\N	248	cpu_usage_percent	3.2057017543794473	percent	\N	2026-02-23 23:45:56.84+00
\N	248	cpu_usage_percent	3.131140350944193	percent	\N	2026-02-23 23:46:56.84+00
\N	248	cpu_usage_percent	2.871491228017902	percent	\N	2026-02-23 23:47:56.84+00
\N	248	cpu_usage_percent	2.629385964879617	percent	\N	2026-02-23 23:48:56.84+00
\N	248	cpu_usage_percent	2.367982456150159	percent	\N	2026-02-23 23:49:56.84+00
\N	260	cpu_usage_percent	23.38552631579725	percent	\N	2026-02-23 22:54:54.924+00
\N	260	cpu_usage_percent	23.428508771967415	percent	\N	2026-02-23 22:55:54.924+00
\N	260	cpu_usage_percent	23.46096491228724	percent	\N	2026-02-23 22:56:54.924+00
\N	260	cpu_usage_percent	23.445065789467975	percent	\N	2026-02-23 22:57:54.924+00
\N	260	cpu_usage_percent	23.46249999999266	percent	\N	2026-02-23 22:58:54.924+00
\N	260	cpu_usage_percent	23.3940789473382	percent	\N	2026-02-23 22:59:54.924+00
\N	260	cpu_usage_percent	23.453508771919203	percent	\N	2026-02-23 23:00:54.924+00
\N	260	cpu_usage_percent	23.419188596492063	percent	\N	2026-02-23 23:01:54.924+00
\N	260	cpu_usage_percent	23.438157894732356	percent	\N	2026-02-23 23:02:54.924+00
\N	260	cpu_usage_percent	23.430372806972628	percent	\N	2026-02-23 23:03:54.924+00
\N	260	cpu_usage_percent	23.394956140372543	percent	\N	2026-02-23 23:04:54.924+00
\N	260	cpu_usage_percent	23.408881578974345	percent	\N	2026-02-23 23:05:54.924+00
\N	260	cpu_usage_percent	23.4410087719331	percent	\N	2026-02-23 23:06:54.924+00
\N	248	cpu_usage_percent	2.374122807012654	percent	\N	2026-02-23 23:50:56.84+00
\N	248	cpu_usage_percent	2.3697368420350102	percent	\N	2026-02-23 23:51:56.84+00
\N	248	cpu_usage_percent	2.444736842074221	percent	\N	2026-02-23 23:52:56.84+00
\N	248	cpu_usage_percent	2.426754385927339	percent	\N	2026-02-23 23:53:56.84+00
\N	248	cpu_usage_percent	2.419298245620581	percent	\N	2026-02-23 23:54:56.84+00
\N	248	cpu_usage_percent	2.530701754394144	percent	\N	2026-02-23 23:55:56.84+00
\N	248	cpu_usage_percent	2.5833333333496853	percent	\N	2026-02-23 23:56:56.84+00
\N	133	cpu_usage_percent	0.4258771930625329	percent	\N	2026-02-23 23:04:55.016+00
\N	133	cpu_usage_percent	0.5236842105851451	percent	\N	2026-02-23 23:05:55.016+00
\N	133	cpu_usage_percent	0.5355263157878483	percent	\N	2026-02-23 23:06:55.016+00
\N	133	cpu_usage_percent	0.5258771929922688	percent	\N	2026-02-23 23:07:55.016+00
\N	133	cpu_usage_percent	0.5390350878026453	percent	\N	2026-02-23 23:08:55.016+00
\N	133	cpu_usage_percent	0.43903508766865684	percent	\N	2026-02-23 23:09:55.016+00
\N	133	cpu_usage_percent	0.4184210526332208	percent	\N	2026-02-23 23:10:55.016+00
\N	133	cpu_usage_percent	0.4228070175291663	percent	\N	2026-02-23 23:11:55.016+00
\N	133	cpu_usage_percent	0.3100877192296281	percent	\N	2026-02-23 23:12:55.016+00
\N	133	cpu_usage_percent	0.4245614034957157	percent	\N	2026-02-23 23:13:55.016+00
\N	133	cpu_usage_percent	0.42017543859977025	percent	\N	2026-02-23 23:14:55.016+00
\N	133	cpu_usage_percent	0.5346491227433035	percent	\N	2026-02-23 23:15:55.016+00
\N	133	cpu_usage_percent	0.5442982455797392	percent	\N	2026-02-23 23:16:55.016+00
\N	236	cpu_usage_percent	1.5824561402724555	percent	\N	2026-02-23 23:04:55.094+00
\N	236	cpu_usage_percent	1.712280701715187	percent	\N	2026-02-23 23:05:55.094+00
\N	236	cpu_usage_percent	1.6982456141462023	percent	\N	2026-02-23 23:06:55.094+00
\N	236	cpu_usage_percent	1.6526315789343045	percent	\N	2026-02-23 23:07:55.094+00
\N	236	cpu_usage_percent	1.6526315789343045	percent	\N	2026-02-23 23:08:55.094+00
\N	236	cpu_usage_percent	1.5614035088373015	percent	\N	2026-02-23 23:09:55.094+00
\N	236	cpu_usage_percent	1.508771929759206	percent	\N	2026-02-23 23:10:55.094+00
\N	236	cpu_usage_percent	1.494736842026839	percent	\N	2026-02-23 23:11:55.094+00
\N	236	cpu_usage_percent	1.3438596491489534	percent	\N	2026-02-23 23:12:55.094+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	\N	2026-02-23 23:13:55.094+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	\N	2026-02-23 23:14:55.094+00
\N	236	cpu_usage_percent	1.6315789474991504	percent	\N	2026-02-23 23:15:55.094+00
\N	236	cpu_usage_percent	1.6421052630533381	percent	\N	2026-02-23 23:16:55.094+00
\N	252	cpu_usage_percent	24.351754385953484	percent	\N	2026-02-23 23:44:56.903+00
\N	252	cpu_usage_percent	24.29035087716521	percent	\N	2026-02-23 23:45:56.903+00
\N	252	cpu_usage_percent	24.284210526261887	percent	\N	2026-02-23 23:46:56.903+00
\N	252	cpu_usage_percent	23.93991228070503	percent	\N	2026-02-23 23:47:56.903+00
\N	252	cpu_usage_percent	23.55131578946225	percent	\N	2026-02-23 23:48:56.903+00
\N	252	cpu_usage_percent	23.27368421053204	percent	\N	2026-02-23 23:49:56.903+00
\N	252	cpu_usage_percent	23.240350877188092	percent	\N	2026-02-23 23:50:56.903+00
\N	248	cpu_usage_percent	2.8640350877519865	percent	\N	2026-02-23 23:04:55.164+00
\N	248	cpu_usage_percent	2.7127192982701445	percent	\N	2026-02-23 23:05:55.164+00
\N	248	cpu_usage_percent	2.8127192982407223	percent	\N	2026-02-23 23:06:55.164+00
\N	248	cpu_usage_percent	2.8271929824136777	percent	\N	2026-02-23 23:07:55.164+00
\N	248	cpu_usage_percent	3.04736842119479	percent	\N	2026-02-23 23:08:55.164+00
\N	248	cpu_usage_percent	2.9188596491963352	percent	\N	2026-02-23 23:09:55.164+00
\N	248	cpu_usage_percent	2.814912280688702	percent	\N	2026-02-23 23:10:55.164+00
\N	248	cpu_usage_percent	2.7513157895341465	percent	\N	2026-02-23 23:11:55.164+00
\N	248	cpu_usage_percent	2.6109649122921468	percent	\N	2026-02-23 23:12:55.164+00
\N	248	cpu_usage_percent	2.552631578955541	percent	\N	2026-02-23 23:13:55.164+00
\N	248	cpu_usage_percent	2.5859649123199233	percent	\N	2026-02-23 23:14:55.164+00
\N	248	cpu_usage_percent	2.769736842162459	percent	\N	2026-02-23 23:15:55.164+00
\N	248	cpu_usage_percent	2.8947368421461164	percent	\N	2026-02-23 23:16:55.164+00
\N	252	cpu_usage_percent	23.263157894753192	percent	\N	2026-02-23 23:51:56.903+00
\N	252	cpu_usage_percent	23.324561403480175	percent	\N	2026-02-23 23:52:56.903+00
\N	252	cpu_usage_percent	23.345175438536046	percent	\N	2026-02-23 23:53:56.903+00
\N	252	cpu_usage_percent	23.21842105262668	percent	\N	2026-02-23 23:54:56.903+00
\N	252	cpu_usage_percent	23.427192982441454	percent	\N	2026-02-23 23:55:56.903+00
\N	252	cpu_usage_percent	23.635526315754348	percent	\N	2026-02-23 23:56:56.903+00
\N	252	cpu_usage_percent	23.394298245640186	percent	\N	2026-02-23 23:04:55.224+00
\N	252	cpu_usage_percent	23.5399122807614	percent	\N	2026-02-23 23:05:55.224+00
\N	252	cpu_usage_percent	24.222807017575732	percent	\N	2026-02-23 23:06:55.224+00
\N	252	cpu_usage_percent	24.11403508773155	percent	\N	2026-02-23 23:07:55.224+00
\N	252	cpu_usage_percent	24.333771929847444	percent	\N	2026-02-23 23:08:55.224+00
\N	252	cpu_usage_percent	24.299122806997943	percent	\N	2026-02-23 23:09:55.224+00
\N	252	cpu_usage_percent	24.10921052627249	percent	\N	2026-02-23 23:10:55.224+00
\N	252	cpu_usage_percent	24.022368421071434	percent	\N	2026-02-23 23:11:55.224+00
\N	252	cpu_usage_percent	24.255263157895556	percent	\N	2026-02-23 23:12:55.224+00
\N	252	cpu_usage_percent	24.04473684209384	percent	\N	2026-02-23 23:13:55.224+00
\N	252	cpu_usage_percent	23.92499999998938	percent	\N	2026-02-23 23:14:55.224+00
\N	252	cpu_usage_percent	24.261842105280323	percent	\N	2026-02-23 23:15:55.224+00
\N	252	cpu_usage_percent	24.222368421094302	percent	\N	2026-02-23 23:16:55.224+00
\N	257	cpu_usage_percent	4.200000000010633	percent	\N	2026-02-23 23:44:56.964+00
\N	257	cpu_usage_percent	4.239473684196653	percent	\N	2026-02-23 23:04:55.281+00
\N	257	cpu_usage_percent	4.100877193002901	percent	\N	2026-02-23 23:05:55.281+00
\N	257	cpu_usage_percent	4.141228070192611	percent	\N	2026-02-23 23:06:55.281+00
\N	257	cpu_usage_percent	4.014035087740552	percent	\N	2026-02-23 23:07:55.281+00
\N	257	cpu_usage_percent	4.642982456134632	percent	\N	2026-02-23 23:08:55.281+00
\N	257	cpu_usage_percent	5.067543859650769	percent	\N	2026-02-23 23:09:55.281+00
\N	257	cpu_usage_percent	5.167543859621361	percent	\N	2026-02-23 23:10:55.281+00
\N	257	cpu_usage_percent	5.1894736842236	percent	\N	2026-02-23 23:11:55.281+00
\N	257	cpu_usage_percent	4.7263157894843175	percent	\N	2026-02-23 23:12:55.281+00
\N	257	cpu_usage_percent	4.584210526337046	percent	\N	2026-02-23 23:13:55.281+00
\N	257	cpu_usage_percent	4.22807017543451	percent	\N	2026-02-23 23:14:55.281+00
\N	257	cpu_usage_percent	4.120175438614467	percent	\N	2026-02-23 23:15:55.281+00
\N	257	cpu_usage_percent	4.123684210547566	percent	\N	2026-02-23 23:16:55.281+00
\N	257	cpu_usage_percent	3.928947368424332	percent	\N	2026-02-23 23:45:56.964+00
\N	257	cpu_usage_percent	4.10877192981151	percent	\N	2026-02-23 23:46:56.964+00
\N	257	cpu_usage_percent	4.1912280701779	percent	\N	2026-02-23 23:47:56.964+00
\N	257	cpu_usage_percent	4.594736842095472	percent	\N	2026-02-23 23:48:56.964+00
\N	257	cpu_usage_percent	4.716666666688724	percent	\N	2026-02-23 23:49:56.964+00
\N	257	cpu_usage_percent	5.105263157911082	percent	\N	2026-02-23 23:50:56.964+00
\N	257	cpu_usage_percent	5.137719298251341	percent	\N	2026-02-23 23:51:56.964+00
\N	260	cpu_usage_percent	23.394956140372543	percent	\N	2026-02-23 23:04:55.345+00
\N	260	cpu_usage_percent	23.408881578974345	percent	\N	2026-02-23 23:05:55.345+00
\N	260	cpu_usage_percent	23.4410087719331	percent	\N	2026-02-23 23:06:55.345+00
\N	260	cpu_usage_percent	23.456688596470812	percent	\N	2026-02-23 23:07:55.345+00
\N	260	cpu_usage_percent	23.4425438596283	percent	\N	2026-02-23 23:08:55.345+00
\N	260	cpu_usage_percent	23.46633771926639	percent	\N	2026-02-23 23:09:55.345+00
\N	260	cpu_usage_percent	23.49747807020323	percent	\N	2026-02-23 23:10:55.345+00
\N	260	cpu_usage_percent	23.41239035087679	percent	\N	2026-02-23 23:11:55.345+00
\N	260	cpu_usage_percent	23.48004385961727	percent	\N	2026-02-23 23:12:55.345+00
\N	260	cpu_usage_percent	23.397478070191795	percent	\N	2026-02-23 23:13:55.345+00
\N	260	cpu_usage_percent	23.45010964907584	percent	\N	2026-02-23 23:14:55.345+00
\N	260	cpu_usage_percent	23.442543859648723	percent	\N	2026-02-23 23:15:55.345+00
\N	260	cpu_usage_percent	23.879385964910256	percent	\N	2026-02-23 23:16:55.345+00
\N	257	cpu_usage_percent	5.0043859648959454	percent	\N	2026-02-23 23:52:56.964+00
\N	257	cpu_usage_percent	4.62719298243573	percent	\N	2026-02-23 23:53:56.964+00
\N	257	cpu_usage_percent	4.028070175411642	percent	\N	2026-02-23 23:54:56.964+00
\N	257	cpu_usage_percent	3.864912280706662	percent	\N	2026-02-23 23:55:56.964+00
\N	257	cpu_usage_percent	4.064035087725841	percent	\N	2026-02-23 23:56:56.964+00
\N	133	cpu_usage_percent	0.42017543859977025	percent	\N	2026-02-23 23:14:55.42+00
\N	133	cpu_usage_percent	0.5346491227433035	percent	\N	2026-02-23 23:15:55.42+00
\N	133	cpu_usage_percent	0.5442982455797392	percent	\N	2026-02-23 23:16:55.42+00
\N	133	cpu_usage_percent	0.4622807017151729	percent	\N	2026-02-23 23:17:55.42+00
\N	133	cpu_usage_percent	0.5416666666094869	percent	\N	2026-02-23 23:18:55.42+00
\N	133	cpu_usage_percent	0.5394736842840615	percent	\N	2026-02-23 23:19:55.42+00
\N	133	cpu_usage_percent	0.4250000000179881	percent	\N	2026-02-23 23:20:55.42+00
\N	133	cpu_usage_percent	0.43026315787678016	percent	\N	2026-02-23 23:21:55.42+00
\N	133	cpu_usage_percent	0.42236842096605187	percent	\N	2026-02-23 23:22:55.42+00
\N	133	cpu_usage_percent	0.4162280702260972	percent	\N	2026-02-23 23:23:55.42+00
\N	133	cpu_usage_percent	0.41315789477442877	percent	\N	2026-02-23 23:24:55.42+00
\N	133	cpu_usage_percent	0.5403508771652241	percent	\N	2026-02-23 23:25:55.42+00
\N	133	cpu_usage_percent	0.5381578947172443	percent	\N	2026-02-23 23:26:55.42+00
\N	260	cpu_usage_percent	23.385307017546324	percent	\N	2026-02-23 23:44:57.035+00
\N	260	cpu_usage_percent	23.38114035086045	percent	\N	2026-02-23 23:45:57.035+00
\N	260	cpu_usage_percent	23.97894736846068	percent	\N	2026-02-23 23:46:57.035+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	\N	2026-02-23 23:14:55.488+00
\N	236	cpu_usage_percent	1.6315789474991504	percent	\N	2026-02-23 23:15:55.488+00
\N	236	cpu_usage_percent	1.6421052630533381	percent	\N	2026-02-23 23:16:55.488+00
\N	236	cpu_usage_percent	1.4807017544578684	percent	\N	2026-02-23 23:17:55.488+00
\N	236	cpu_usage_percent	1.6105263157372036	percent	\N	2026-02-23 23:18:55.488+00
\N	236	cpu_usage_percent	1.4877192981606555	percent	\N	2026-02-23 23:19:55.488+00
\N	236	cpu_usage_percent	1.470175438576888	percent	\N	2026-02-23 23:20:55.488+00
\N	236	cpu_usage_percent	1.4596491228593038	percent	\N	2026-02-23 23:21:55.488+00
\N	236	cpu_usage_percent	1.4526315788297381	percent	\N	2026-02-23 23:22:55.488+00
\N	236	cpu_usage_percent	1.4421052632755504	percent	\N	2026-02-23 23:23:55.488+00
\N	236	cpu_usage_percent	1.480701754294472	percent	\N	2026-02-23 23:24:55.488+00
\N	236	cpu_usage_percent	1.638596491365334	percent	\N	2026-02-23 23:25:55.488+00
\N	236	cpu_usage_percent	1.6666666666666714	percent	\N	2026-02-23 23:26:55.488+00
\N	260	cpu_usage_percent	23.97302631580827	percent	\N	2026-02-23 23:47:57.035+00
\N	260	cpu_usage_percent	24.02050438599474	percent	\N	2026-02-23 23:48:57.035+00
\N	260	cpu_usage_percent	23.9927631579217	percent	\N	2026-02-23 23:49:57.035+00
\N	260	cpu_usage_percent	23.940021929825377	percent	\N	2026-02-23 23:50:57.035+00
\N	260	cpu_usage_percent	23.40307017542186	percent	\N	2026-02-23 23:51:57.035+00
\N	260	cpu_usage_percent	23.45537280701633	percent	\N	2026-02-23 23:52:57.035+00
\N	260	cpu_usage_percent	23.431578947398663	percent	\N	2026-02-23 23:53:57.035+00
\N	248	cpu_usage_percent	2.5859649123199233	percent	\N	2026-02-23 23:14:55.553+00
\N	248	cpu_usage_percent	2.769736842162459	percent	\N	2026-02-23 23:15:55.553+00
\N	248	cpu_usage_percent	2.8947368421461164	percent	\N	2026-02-23 23:16:55.553+00
\N	248	cpu_usage_percent	2.954385964845301	percent	\N	2026-02-23 23:17:55.553+00
\N	248	cpu_usage_percent	2.9614035087931825	percent	\N	2026-02-23 23:18:55.553+00
\N	248	cpu_usage_percent	3.002192982341782	percent	\N	2026-02-23 23:19:55.553+00
\N	248	cpu_usage_percent	2.859649122856041	percent	\N	2026-02-23 23:20:55.553+00
\N	248	cpu_usage_percent	2.716228070162373	percent	\N	2026-02-23 23:21:55.553+00
\N	248	cpu_usage_percent	2.739473684249745	percent	\N	2026-02-23 23:22:55.553+00
\N	248	cpu_usage_percent	2.632894736853558	percent	\N	2026-02-23 23:23:55.553+00
\N	248	cpu_usage_percent	2.743421052623418	percent	\N	2026-02-23 23:24:55.553+00
\N	248	cpu_usage_percent	2.7701754386438893	percent	\N	2026-02-23 23:25:55.553+00
\N	248	cpu_usage_percent	2.8561403509229564	percent	\N	2026-02-23 23:26:55.553+00
\N	260	cpu_usage_percent	23.41622807017096	percent	\N	2026-02-23 23:54:57.035+00
\N	260	cpu_usage_percent	23.453289473688713	percent	\N	2026-02-23 23:55:57.035+00
\N	260	cpu_usage_percent	23.435964912233317	percent	\N	2026-02-23 23:56:57.035+00
\N	252	cpu_usage_percent	23.92499999998938	percent	\N	2026-02-23 23:14:55.62+00
\N	252	cpu_usage_percent	24.261842105280323	percent	\N	2026-02-23 23:15:55.62+00
\N	252	cpu_usage_percent	24.222368421094302	percent	\N	2026-02-23 23:16:55.62+00
\N	252	cpu_usage_percent	24.12763157894166	percent	\N	2026-02-23 23:17:55.62+00
\N	252	cpu_usage_percent	24.26754385968181	percent	\N	2026-02-23 23:18:55.62+00
\N	252	cpu_usage_percent	24.282894736899294	percent	\N	2026-02-23 23:19:55.62+00
\N	252	cpu_usage_percent	24.21052631576906	percent	\N	2026-02-23 23:20:55.62+00
\N	252	cpu_usage_percent	24.29736842107225	percent	\N	2026-02-23 23:21:55.62+00
\N	252	cpu_usage_percent	24.289035087741368	percent	\N	2026-02-23 23:22:55.62+00
\N	252	cpu_usage_percent	24.194736842151826	percent	\N	2026-02-23 23:23:55.62+00
\N	252	cpu_usage_percent	24.56710526317343	percent	\N	2026-02-23 23:24:55.62+00
\N	252	cpu_usage_percent	24.80043859643814	percent	\N	2026-02-23 23:25:55.62+00
\N	252	cpu_usage_percent	25.009649122836436	percent	\N	2026-02-23 23:26:55.62+00
\N	133	cpu_usage_percent	0.33728070177237157	percent	\N	2026-02-23 23:54:57.108+00
\N	133	cpu_usage_percent	0.42017543864061224	percent	\N	2026-02-23 23:55:57.108+00
\N	133	cpu_usage_percent	0.5228070175406003	percent	\N	2026-02-23 23:56:57.108+00
\N	133	cpu_usage_percent	0.5254385963883124	percent	\N	2026-02-23 23:57:57.108+00
\N	257	cpu_usage_percent	4.22807017543451	percent	\N	2026-02-23 23:14:55.682+00
\N	257	cpu_usage_percent	4.120175438614467	percent	\N	2026-02-23 23:15:55.682+00
\N	257	cpu_usage_percent	4.123684210547566	percent	\N	2026-02-23 23:16:55.682+00
\N	257	cpu_usage_percent	4.200000000010633	percent	\N	2026-02-23 23:17:55.682+00
\N	257	cpu_usage_percent	4.662280701725805	percent	\N	2026-02-23 23:18:55.682+00
\N	257	cpu_usage_percent	5.058771929797615	percent	\N	2026-02-23 23:19:55.682+00
\N	257	cpu_usage_percent	5.164912280691965	percent	\N	2026-02-23 23:20:55.682+00
\N	257	cpu_usage_percent	5.185087719286813	percent	\N	2026-02-23 23:21:55.682+00
\N	257	cpu_usage_percent	4.929824561399428	percent	\N	2026-02-23 23:22:55.682+00
\N	257	cpu_usage_percent	4.613157894744219	percent	\N	2026-02-23 23:23:55.682+00
\N	257	cpu_usage_percent	4.281578947352898	percent	\N	2026-02-23 23:24:55.682+00
\N	257	cpu_usage_percent	4.2087719298229445	percent	\N	2026-02-23 23:25:55.682+00
\N	257	cpu_usage_percent	4.264035087707867	percent	\N	2026-02-23 23:26:55.682+00
\N	133	cpu_usage_percent	0.5333333333807246	percent	\N	2026-02-23 23:58:57.108+00
\N	133	cpu_usage_percent	0.5385964913212149	percent	\N	2026-02-23 23:59:57.108+00
\N	260	cpu_usage_percent	23.45010964907584	percent	\N	2026-02-23 23:14:55.75+00
\N	260	cpu_usage_percent	23.442543859648723	percent	\N	2026-02-23 23:15:55.75+00
\N	260	cpu_usage_percent	23.879385964910256	percent	\N	2026-02-23 23:16:55.75+00
\N	260	cpu_usage_percent	23.97105263158059	percent	\N	2026-02-23 23:17:55.75+00
\N	260	cpu_usage_percent	24.033114035080786	percent	\N	2026-02-23 23:18:55.75+00
\N	260	cpu_usage_percent	24.036074561391672	percent	\N	2026-02-23 23:19:55.75+00
\N	260	cpu_usage_percent	24.01052631576661	percent	\N	2026-02-23 23:20:55.75+00
\N	260	cpu_usage_percent	23.59035087714642	percent	\N	2026-02-23 23:21:55.75+00
\N	260	cpu_usage_percent	23.48563596492903	percent	\N	2026-02-23 23:22:55.75+00
\N	260	cpu_usage_percent	23.46557017541369	percent	\N	2026-02-23 23:23:55.75+00
\N	260	cpu_usage_percent	23.44210526315709	percent	\N	2026-02-23 23:24:55.75+00
\N	260	cpu_usage_percent	23.485087719286412	percent	\N	2026-02-23 23:25:55.75+00
\N	260	cpu_usage_percent	23.46425438592857	percent	\N	2026-02-23 23:26:55.75+00
\N	236	cpu_usage_percent	1.2877192982194856	percent	\N	2026-02-23 23:54:57.222+00
\N	236	cpu_usage_percent	1.522807017491587	percent	\N	2026-02-23 23:55:57.222+00
\N	236	cpu_usage_percent	1.5719298247182678	percent	\N	2026-02-23 23:56:57.222+00
\N	236	cpu_usage_percent	1.6912280701166225	percent	\N	2026-02-23 23:57:57.222+00
\N	236	cpu_usage_percent	1.740350877179921	percent	\N	2026-02-23 23:58:57.222+00
\N	236	cpu_usage_percent	1.6105263157372036	percent	\N	2026-02-23 23:59:57.222+00
\N	133	cpu_usage_percent	0.41315789477442877	percent	\N	2026-02-23 23:24:55.836+00
\N	133	cpu_usage_percent	0.5403508771652241	percent	\N	2026-02-23 23:25:55.836+00
\N	133	cpu_usage_percent	0.5381578947172443	percent	\N	2026-02-23 23:26:55.836+00
\N	133	cpu_usage_percent	0.5390350876392489	percent	\N	2026-02-23 23:27:55.836+00
\N	133	cpu_usage_percent	0.4732456140367276	percent	\N	2026-02-23 23:28:55.836+00
\N	133	cpu_usage_percent	0.5333333333807246	percent	\N	2026-02-23 23:29:55.836+00
\N	133	cpu_usage_percent	0.42850877191023073	percent	\N	2026-02-23 23:30:55.836+00
\N	133	cpu_usage_percent	0.42017543855892825	percent	\N	2026-02-23 23:31:55.836+00
\N	133	cpu_usage_percent	0.4241228070142995	percent	\N	2026-02-23 23:32:55.836+00
\N	133	cpu_usage_percent	0.33684210520924296	percent	\N	2026-02-23 23:33:55.836+00
\N	133	cpu_usage_percent	0.4429824562057263	percent	\N	2026-02-23 23:34:55.836+00
\N	133	cpu_usage_percent	0.5425438596540317	percent	\N	2026-02-23 23:35:55.836+00
\N	133	cpu_usage_percent	0.5434210526985765	percent	\N	2026-02-23 23:36:55.836+00
\N	236	cpu_usage_percent	1.480701754294472	percent	\N	2026-02-23 23:24:55.912+00
\N	236	cpu_usage_percent	1.638596491365334	percent	\N	2026-02-23 23:25:55.912+00
\N	236	cpu_usage_percent	1.6666666666666714	percent	\N	2026-02-23 23:26:55.912+00
\N	236	cpu_usage_percent	1.6701754386814684	percent	\N	2026-02-23 23:27:55.912+00
\N	236	cpu_usage_percent	1.6491228069195216	percent	\N	2026-02-23 23:28:55.912+00
\N	236	cpu_usage_percent	1.631578947335754	percent	\N	2026-02-23 23:29:55.912+00
\N	236	cpu_usage_percent	1.4877192981606555	percent	\N	2026-02-23 23:30:55.912+00
\N	236	cpu_usage_percent	1.5157894736253894	percent	\N	2026-02-23 23:31:55.912+00
\N	236	cpu_usage_percent	1.512280701774003	percent	\N	2026-02-23 23:32:55.912+00
\N	236	cpu_usage_percent	1.3508771928517547	percent	\N	2026-02-23 23:33:55.912+00
\N	236	cpu_usage_percent	1.498245614041636	percent	\N	2026-02-23 23:34:55.912+00
\N	236	cpu_usage_percent	1.6280701754843534	percent	\N	2026-02-23 23:35:55.912+00
\N	236	cpu_usage_percent	1.589473684138639	percent	\N	2026-02-23 23:36:55.912+00
\N	248	cpu_usage_percent	2.419298245620581	percent	\N	2026-02-23 23:54:57.294+00
\N	248	cpu_usage_percent	2.530701754394144	percent	\N	2026-02-23 23:55:57.294+00
\N	248	cpu_usage_percent	2.5833333333496853	percent	\N	2026-02-23 23:56:57.294+00
\N	248	cpu_usage_percent	2.686842105253362	percent	\N	2026-02-23 23:57:57.294+00
\N	248	cpu_usage_percent	2.826315789491659	percent	\N	2026-02-23 23:58:57.294+00
\N	248	cpu_usage_percent	2.8223684209546036	percent	\N	2026-02-23 23:59:57.294+00
\N	248	cpu_usage_percent	2.743421052623418	percent	\N	2026-02-23 23:24:55.989+00
\N	248	cpu_usage_percent	2.7701754386438893	percent	\N	2026-02-23 23:25:55.989+00
\N	248	cpu_usage_percent	2.8561403509229564	percent	\N	2026-02-23 23:26:55.989+00
\N	248	cpu_usage_percent	2.96578947372997	percent	\N	2026-02-23 23:27:55.989+00
\N	248	cpu_usage_percent	2.9412280701166367	percent	\N	2026-02-23 23:28:55.989+00
\N	248	cpu_usage_percent	2.9118421052484678	percent	\N	2026-02-23 23:29:55.989+00
\N	248	cpu_usage_percent	2.903070175415735	percent	\N	2026-02-23 23:30:55.989+00
\N	248	cpu_usage_percent	2.990350877179921	percent	\N	2026-02-23 23:31:55.989+00
\N	248	cpu_usage_percent	2.8144736842481137	percent	\N	2026-02-23 23:32:55.989+00
\N	248	cpu_usage_percent	2.7065789473259514	percent	\N	2026-02-23 23:33:55.989+00
\N	248	cpu_usage_percent	2.8171052631366678	percent	\N	2026-02-23 23:34:55.989+00
\N	248	cpu_usage_percent	2.84824561405307	percent	\N	2026-02-23 23:35:55.989+00
\N	248	cpu_usage_percent	2.8324561403541537	percent	\N	2026-02-23 23:36:55.989+00
\N	252	cpu_usage_percent	23.21842105262668	percent	\N	2026-02-23 23:54:57.363+00
\N	252	cpu_usage_percent	24.56710526317343	percent	\N	2026-02-23 23:24:56.066+00
\N	252	cpu_usage_percent	24.80043859643814	percent	\N	2026-02-23 23:25:56.066+00
\N	252	cpu_usage_percent	25.009649122836436	percent	\N	2026-02-23 23:26:56.066+00
\N	252	cpu_usage_percent	25.499561403534926	percent	\N	2026-02-23 23:27:56.066+00
\N	252	cpu_usage_percent	25.45087719297348	percent	\N	2026-02-23 23:28:56.066+00
\N	252	cpu_usage_percent	25.03508771929009	percent	\N	2026-02-23 23:29:56.066+00
\N	252	cpu_usage_percent	24.75263157892124	percent	\N	2026-02-23 23:30:56.066+00
\N	252	cpu_usage_percent	24.509649122799672	percent	\N	2026-02-23 23:31:56.066+00
\N	252	cpu_usage_percent	23.99780701756022	percent	\N	2026-02-23 23:32:56.066+00
\N	252	cpu_usage_percent	23.968421052671616	percent	\N	2026-02-23 23:33:56.066+00
\N	252	cpu_usage_percent	24.132017543858026	percent	\N	2026-02-23 23:34:56.066+00
\N	252	cpu_usage_percent	24.031140350904153	percent	\N	2026-02-23 23:35:56.066+00
\N	252	cpu_usage_percent	23.937719298195788	percent	\N	2026-02-23 23:36:56.066+00
\N	252	cpu_usage_percent	23.427192982441454	percent	\N	2026-02-23 23:55:57.363+00
\N	252	cpu_usage_percent	23.635526315754348	percent	\N	2026-02-23 23:56:57.363+00
\N	252	cpu_usage_percent	23.840789473656443	percent	\N	2026-02-23 23:57:57.363+00
\N	252	cpu_usage_percent	23.98377192982784	percent	\N	2026-02-23 23:58:57.363+00
\N	252	cpu_usage_percent	24.14736842105509	percent	\N	2026-02-23 23:59:57.363+00
\N	257	cpu_usage_percent	4.281578947352898	percent	\N	2026-02-23 23:24:56.13+00
\N	257	cpu_usage_percent	4.2087719298229445	percent	\N	2026-02-23 23:25:56.13+00
\N	257	cpu_usage_percent	4.264035087707867	percent	\N	2026-02-23 23:26:56.13+00
\N	257	cpu_usage_percent	4.453508771911046	percent	\N	2026-02-23 23:27:56.13+00
\N	257	cpu_usage_percent	4.48157894737578	percent	\N	2026-02-23 23:28:56.13+00
\N	257	cpu_usage_percent	5.085964912299502	percent	\N	2026-02-23 23:29:56.13+00
\N	257	cpu_usage_percent	5.2552631578873985	percent	\N	2026-02-23 23:30:56.13+00
\N	257	cpu_usage_percent	5.263157894736864	percent	\N	2026-02-23 23:31:56.13+00
\N	257	cpu_usage_percent	5.024561403490807	percent	\N	2026-02-23 23:32:56.13+00
\N	257	cpu_usage_percent	4.384210526334584	percent	\N	2026-02-23 23:33:56.13+00
\N	257	cpu_usage_percent	4.203508771943717	percent	\N	2026-02-23 23:34:56.13+00
\N	257	cpu_usage_percent	4.071929824575307	percent	\N	2026-02-23 23:35:56.13+00
\N	257	cpu_usage_percent	4.092105263149733	percent	\N	2026-02-23 23:36:56.13+00
\N	257	cpu_usage_percent	4.028070175411642	percent	\N	2026-02-23 23:54:57.433+00
\N	257	cpu_usage_percent	3.864912280706662	percent	\N	2026-02-23 23:55:57.433+00
\N	257	cpu_usage_percent	4.064035087725841	percent	\N	2026-02-23 23:56:57.433+00
\N	260	cpu_usage_percent	23.44210526315709	percent	\N	2026-02-23 23:24:56.201+00
\N	260	cpu_usage_percent	23.485087719286412	percent	\N	2026-02-23 23:25:56.201+00
\N	260	cpu_usage_percent	23.46425438592857	percent	\N	2026-02-23 23:26:56.201+00
\N	260	cpu_usage_percent	23.491995614062873	percent	\N	2026-02-23 23:27:56.201+00
\N	260	cpu_usage_percent	23.4845394736642	percent	\N	2026-02-23 23:28:56.201+00
\N	260	cpu_usage_percent	23.4494517544354	percent	\N	2026-02-23 23:29:56.201+00
\N	260	cpu_usage_percent	23.473026315812348	percent	\N	2026-02-23 23:30:56.201+00
\N	260	cpu_usage_percent	23.446820175485584	percent	\N	2026-02-23 23:31:56.201+00
\N	260	cpu_usage_percent	23.512938596490002	percent	\N	2026-02-23 23:32:56.201+00
\N	260	cpu_usage_percent	23.41304824563977	percent	\N	2026-02-23 23:33:56.201+00
\N	260	cpu_usage_percent	23.47467105262791	percent	\N	2026-02-23 23:34:56.201+00
\N	260	cpu_usage_percent	23.4016447368368	percent	\N	2026-02-23 23:35:56.201+00
\N	260	cpu_usage_percent	23.46074561404653	percent	\N	2026-02-23 23:36:56.201+00
\N	257	cpu_usage_percent	4.1947368420905775	percent	\N	2026-02-23 23:57:57.433+00
\N	257	cpu_usage_percent	4.530701754377802	percent	\N	2026-02-23 23:58:57.433+00
\N	257	cpu_usage_percent	4.911403508750695	percent	\N	2026-02-23 23:59:57.433+00
\N	260	cpu_usage_percent	23.41622807017096	percent	\N	2026-02-23 23:54:57.505+00
\N	260	cpu_usage_percent	23.453289473688713	percent	\N	2026-02-23 23:55:57.505+00
\N	260	cpu_usage_percent	23.435964912233317	percent	\N	2026-02-23 23:56:57.505+00
\N	260	cpu_usage_percent	23.47280701755122	percent	\N	2026-02-23 23:57:57.505+00
\N	260	cpu_usage_percent	23.565899122775974	percent	\N	2026-02-23 23:58:57.505+00
\N	260	cpu_usage_percent	23.954385964918828	percent	\N	2026-02-23 23:59:57.505+00
\.


--
-- Data for Name: _hyper_5_3_chunk; Type: TABLE DATA; Schema: _timescaledb_internal; Owner: postgres
--

COPY _timescaledb_internal._hyper_5_3_chunk (id, server_id, metric_name, value, unit, labels, "timestamp") FROM stdin;
\N	133	cpu_usage_percent	0.4539473684455686	percent	\N	2026-02-24 00:00:57.108+00
\N	133	cpu_usage_percent	0.4263157894214089	percent	\N	2026-02-24 00:01:57.108+00
\N	133	cpu_usage_percent	0.9824561402855352	percent	\N	2026-02-24 00:02:57.108+00
\N	133	cpu_usage_percent	1.0078947367391748	percent	\N	2026-02-24 00:03:57.108+00
\N	133	cpu_usage_percent	1.0171052631350364	percent	\N	2026-02-24 00:04:57.108+00
\N	133	cpu_usage_percent	0.998684210506724	percent	\N	2026-02-24 00:05:57.108+00
\N	133	cpu_usage_percent	1.1214912280424159	percent	\N	2026-02-24 00:06:57.108+00
\N	236	cpu_usage_percent	1.649122807082918	percent	\N	2026-02-24 00:00:57.222+00
\N	236	cpu_usage_percent	1.6877192981018396	percent	\N	2026-02-24 00:01:57.222+00
\N	236	cpu_usage_percent	1.603508771871006	percent	\N	2026-02-24 00:02:57.222+00
\N	236	cpu_usage_percent	1.564912280688688	percent	\N	2026-02-24 00:03:57.222+00
\N	236	cpu_usage_percent	1.5719298245548714	percent	\N	2026-02-24 00:04:57.222+00
\N	236	cpu_usage_percent	2.0421052630990744	percent	\N	2026-02-24 00:05:57.222+00
\N	236	cpu_usage_percent	2.1754385965565888	percent	\N	2026-02-24 00:06:57.222+00
\N	248	cpu_usage_percent	2.9956140350795692	percent	\N	2026-02-24 00:00:57.294+00
\N	248	cpu_usage_percent	2.944298245568305	percent	\N	2026-02-24 00:01:57.294+00
\N	248	cpu_usage_percent	2.8539473684341345	percent	\N	2026-02-24 00:02:57.294+00
\N	248	cpu_usage_percent	2.777631578991489	percent	\N	2026-02-24 00:03:57.294+00
\N	248	cpu_usage_percent	2.604824561388824	percent	\N	2026-02-24 00:04:57.294+00
\N	248	cpu_usage_percent	2.390789473674417	percent	\N	2026-02-24 00:05:57.294+00
\N	248	cpu_usage_percent	2.453947368347528	percent	\N	2026-02-24 00:06:57.294+00
\N	252	cpu_usage_percent	24.485964912251305	percent	\N	2026-02-24 00:00:57.363+00
\N	252	cpu_usage_percent	24.23552631580256	percent	\N	2026-02-24 00:01:57.363+00
\N	252	cpu_usage_percent	24.44429824561732	percent	\N	2026-02-24 00:02:57.363+00
\N	252	cpu_usage_percent	24.324122807011022	percent	\N	2026-02-24 00:03:57.363+00
\N	252	cpu_usage_percent	24.177631578906528	percent	\N	2026-02-24 00:04:57.363+00
\N	252	cpu_usage_percent	24.09824561403265	percent	\N	2026-02-24 00:05:57.363+00
\N	252	cpu_usage_percent	24.44649122804485	percent	\N	2026-02-24 00:06:57.363+00
\N	257	cpu_usage_percent	5.307894736863361	percent	\N	2026-02-24 00:00:57.433+00
\N	257	cpu_usage_percent	5.194736842123248	percent	\N	2026-02-24 00:01:57.433+00
\N	257	cpu_usage_percent	5.007017543845777	percent	\N	2026-02-24 00:02:57.433+00
\N	257	cpu_usage_percent	4.665789473699746	percent	\N	2026-02-24 00:03:57.433+00
\N	257	cpu_usage_percent	4.355263157886583	percent	\N	2026-02-24 00:04:57.433+00
\N	257	cpu_usage_percent	3.881578947368425	percent	\N	2026-02-24 00:05:57.433+00
\N	257	cpu_usage_percent	4.215789473709549	percent	\N	2026-02-24 00:06:57.433+00
\N	260	cpu_usage_percent	24.532127192983282	percent	\N	2026-02-24 00:00:57.505+00
\N	260	cpu_usage_percent	24.976754385984123	percent	\N	2026-02-24 00:01:57.505+00
\N	260	cpu_usage_percent	25.47478070178299	percent	\N	2026-02-24 00:02:57.505+00
\N	260	cpu_usage_percent	25.69561403509222	percent	\N	2026-02-24 00:03:57.505+00
\N	260	cpu_usage_percent	25.717543859622992	percent	\N	2026-02-24 00:04:57.505+00
\N	260	cpu_usage_percent	25.533662280690734	percent	\N	2026-02-24 00:05:57.505+00
\N	260	cpu_usage_percent	25.53870614037008	percent	\N	2026-02-24 00:06:57.505+00
\N	133	cpu_usage_percent	1.0171052631350364	percent	\N	2026-02-24 00:04:57.568+00
\N	133	cpu_usage_percent	0.998684210506724	percent	\N	2026-02-24 00:05:57.568+00
\N	133	cpu_usage_percent	1.1214912280424159	percent	\N	2026-02-24 00:06:57.568+00
\N	133	cpu_usage_percent	0.546929824468279	percent	\N	2026-02-24 00:07:57.568+00
\N	133	cpu_usage_percent	0.5438596490574668	percent	\N	2026-02-24 00:08:57.568+00
\N	133	cpu_usage_percent	0.5372807017952397	percent	\N	2026-02-24 00:09:57.568+00
\N	133	cpu_usage_percent	0.4421052631611815	percent	\N	2026-02-24 00:10:57.568+00
\N	133	cpu_usage_percent	0.44868421054593455	percent	\N	2026-02-24 00:11:57.568+00
\N	133	cpu_usage_percent	0.4342105262912952	percent	\N	2026-02-24 00:12:57.568+00
\N	133	cpu_usage_percent	0.4460526316165385	percent	\N	2026-02-24 00:13:57.568+00
\N	133	cpu_usage_percent	0.45657894745666283	percent	\N	2026-02-24 00:14:57.568+00
\N	133	cpu_usage_percent	0.35570175431898576	percent	\N	2026-02-24 00:15:57.568+00
\N	133	cpu_usage_percent	0.436403508820959	percent	\N	2026-02-24 00:16:57.568+00
\N	133	cpu_usage_percent	0.4175438596295322	percent	\N	2026-02-24 00:24:58.392+00
\N	133	cpu_usage_percent	0.4263157894622651	percent	\N	2026-02-24 00:25:58.392+00
\N	133	cpu_usage_percent	0.5100877193342086	percent	\N	2026-02-24 00:26:58.392+00
\N	133	cpu_usage_percent	0.5377192981541299	percent	\N	2026-02-24 00:27:58.392+00
\N	133	cpu_usage_percent	0.5447368421020116	percent	\N	2026-02-24 00:28:58.392+00
\N	133	cpu_usage_percent	0.5368421053138235	percent	\N	2026-02-24 00:29:58.392+00
\N	133	cpu_usage_percent	0.5350877193472741	percent	\N	2026-02-24 00:30:58.392+00
\N	236	cpu_usage_percent	1.5719298245548714	percent	\N	2026-02-24 00:04:57.637+00
\N	236	cpu_usage_percent	2.0421052630990744	percent	\N	2026-02-24 00:05:57.637+00
\N	236	cpu_usage_percent	2.1754385965565888	percent	\N	2026-02-24 00:06:57.637+00
\N	236	cpu_usage_percent	2.185964912274173	percent	\N	2026-02-24 00:07:57.637+00
\N	236	cpu_usage_percent	2.185964912274173	percent	\N	2026-02-24 00:08:57.637+00
\N	236	cpu_usage_percent	2.196491227991757	percent	\N	2026-02-24 00:09:57.637+00
\N	236	cpu_usage_percent	1.3649122807475038	percent	\N	2026-02-24 00:10:57.637+00
\N	236	cpu_usage_percent	1.5017543860564189	percent	\N	2026-02-24 00:11:57.637+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	\N	2026-02-24 00:12:57.637+00
\N	236	cpu_usage_percent	1.508771929759206	percent	\N	2026-02-24 00:13:57.637+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	\N	2026-02-24 00:14:57.637+00
\N	236	cpu_usage_percent	1.3298245614165864	percent	\N	2026-02-24 00:15:57.637+00
\N	236	cpu_usage_percent	2.028070175530104	percent	\N	2026-02-24 00:16:57.637+00
\N	133	cpu_usage_percent	0.32675438593224726	percent	\N	2026-02-24 00:31:58.392+00
\N	133	cpu_usage_percent	0.4236842105328549	percent	\N	2026-02-24 00:32:58.392+00
\N	133	cpu_usage_percent	0.42017543859977025	percent	\N	2026-02-24 00:33:58.392+00
\N	133	cpu_usage_percent	0.4434210526054585	percent	\N	2026-02-24 00:34:58.392+00
\N	133	cpu_usage_percent	0.43903508770949884	percent	\N	2026-02-24 00:35:58.392+00
\N	133	cpu_usage_percent	0.43947368419092925	percent	\N	2026-02-24 00:36:58.392+00
\N	133	cpu_usage_percent	0.39035087716848693	percent	\N	2026-02-24 00:54:59.61+00
\N	248	cpu_usage_percent	2.5565789473700704	percent	\N	2026-02-24 00:04:57.7+00
\N	248	cpu_usage_percent	2.415350877165224	percent	\N	2026-02-24 00:05:57.7+00
\N	248	cpu_usage_percent	2.4328947368306757	percent	\N	2026-02-24 00:06:57.7+00
\N	248	cpu_usage_percent	2.4552631579143593	percent	\N	2026-02-24 00:07:57.7+00
\N	248	cpu_usage_percent	2.554824561403521	percent	\N	2026-02-24 00:08:57.7+00
\N	248	cpu_usage_percent	2.647368421026499	percent	\N	2026-02-24 00:09:57.7+00
\N	248	cpu_usage_percent	2.7771929824692165	percent	\N	2026-02-24 00:10:57.7+00
\N	248	cpu_usage_percent	2.776315789506384	percent	\N	2026-02-24 00:11:57.7+00
\N	248	cpu_usage_percent	2.839912280783466	percent	\N	2026-02-24 00:12:57.7+00
\N	248	cpu_usage_percent	2.7434210527051164	percent	\N	2026-02-24 00:13:57.7+00
\N	248	cpu_usage_percent	2.5416666666748426	percent	\N	2026-02-24 00:14:57.7+00
\N	248	cpu_usage_percent	2.486842105189652	percent	\N	2026-02-24 00:15:57.7+00
\N	248	cpu_usage_percent	2.536842105256625	percent	\N	2026-02-24 00:16:57.7+00
\N	133	cpu_usage_percent	0.4166666665441312	percent	\N	2026-02-24 00:55:59.61+00
\N	133	cpu_usage_percent	0.4157894737038248	percent	\N	2026-02-24 00:56:59.61+00
\N	133	cpu_usage_percent	0.5074561402414162	percent	\N	2026-02-24 00:57:59.61+00
\N	133	cpu_usage_percent	0.5092105263713478	percent	\N	2026-02-24 00:58:59.61+00
\N	133	cpu_usage_percent	0.5048245614345745	percent	\N	2026-02-24 00:59:59.61+00
\N	133	cpu_usage_percent	0.5197368421297881	percent	\N	2026-02-24 01:00:59.61+00
\N	236	cpu_usage_percent	1.480701754294472	percent	\N	2026-02-24 00:24:58.464+00
\N	252	cpu_usage_percent	24.177631578906528	percent	\N	2026-02-24 00:04:57.756+00
\N	252	cpu_usage_percent	24.09824561403265	percent	\N	2026-02-24 00:05:57.756+00
\N	252	cpu_usage_percent	24.44649122804485	percent	\N	2026-02-24 00:06:57.756+00
\N	252	cpu_usage_percent	24.528508771950257	percent	\N	2026-02-24 00:07:57.756+00
\N	236	cpu_usage_percent	1.4596491228593038	percent	\N	2026-02-24 00:25:58.464+00
\N	252	cpu_usage_percent	24.529824561414955	percent	\N	2026-02-24 00:08:57.756+00
\N	252	cpu_usage_percent	24.724122807015917	percent	\N	2026-02-24 00:09:57.756+00
\N	252	cpu_usage_percent	24.642543859632795	percent	\N	2026-02-24 00:10:57.756+00
\N	252	cpu_usage_percent	24.830701754371262	percent	\N	2026-02-24 00:11:57.756+00
\N	252	cpu_usage_percent	24.79649122800319	percent	\N	2026-02-24 00:12:57.756+00
\N	252	cpu_usage_percent	24.641666666629092	percent	\N	2026-02-24 00:13:57.756+00
\N	252	cpu_usage_percent	24.560087719286813	percent	\N	2026-02-24 00:14:57.756+00
\N	252	cpu_usage_percent	24.421929824513214	percent	\N	2026-02-24 00:15:57.756+00
\N	252	cpu_usage_percent	23.74210526315055	percent	\N	2026-02-24 00:16:57.756+00
\N	236	cpu_usage_percent	1.5192982456401865	percent	\N	2026-02-24 00:26:58.464+00
\N	236	cpu_usage_percent	1.512280701774003	percent	\N	2026-02-24 00:27:58.464+00
\N	236	cpu_usage_percent	1.5298245613577706	percent	\N	2026-02-24 00:28:58.464+00
\N	236	cpu_usage_percent	1.5403508772387369	percent	\N	2026-02-24 00:29:58.464+00
\N	236	cpu_usage_percent	1.564912280688688	percent	\N	2026-02-24 00:30:58.464+00
\N	236	cpu_usage_percent	1.298245614100452	percent	\N	2026-02-24 00:31:58.464+00
\N	236	cpu_usage_percent	1.4385964910973712	percent	\N	2026-02-24 00:32:58.464+00
\N	257	cpu_usage_percent	4.355263157886583	percent	\N	2026-02-24 00:04:57.818+00
\N	257	cpu_usage_percent	3.881578947368425	percent	\N	2026-02-24 00:05:57.818+00
\N	257	cpu_usage_percent	4.215789473709549	percent	\N	2026-02-24 00:06:57.818+00
\N	257	cpu_usage_percent	4.329824561412508	percent	\N	2026-02-24 00:07:57.818+00
\N	257	cpu_usage_percent	4.689473684207272	percent	\N	2026-02-24 00:08:57.818+00
\N	257	cpu_usage_percent	5.064912280680517	percent	\N	2026-02-24 00:09:57.818+00
\N	257	cpu_usage_percent	5.122807017535706	percent	\N	2026-02-24 00:10:57.818+00
\N	257	cpu_usage_percent	5.278947368415345	percent	\N	2026-02-24 00:11:57.818+00
\N	257	cpu_usage_percent	5.058771929838457	percent	\N	2026-02-24 00:12:57.818+00
\N	257	cpu_usage_percent	4.686842105277876	percent	\N	2026-02-24 00:13:57.818+00
\N	257	cpu_usage_percent	4.303508771914309	percent	\N	2026-02-24 00:14:57.818+00
\N	257	cpu_usage_percent	3.8964912280432316	percent	\N	2026-02-24 00:15:57.818+00
\N	257	cpu_usage_percent	3.9798245614133236	percent	\N	2026-02-24 00:16:57.818+00
\N	236	cpu_usage_percent	1.4526315788297381	percent	\N	2026-02-24 00:33:58.464+00
\N	236	cpu_usage_percent	1.456140350844521	percent	\N	2026-02-24 00:34:58.464+00
\N	236	cpu_usage_percent	1.4631578947107045	percent	\N	2026-02-24 00:35:58.464+00
\N	236	cpu_usage_percent	1.4140350876474201	percent	\N	2026-02-24 00:36:58.464+00
\N	133	cpu_usage_percent	0.5219298245777537	percent	\N	2026-02-24 01:01:59.61+00
\N	133	cpu_usage_percent	0.42982456143619174	percent	\N	2026-02-24 01:02:59.61+00
\N	133	cpu_usage_percent	0.4065789474305177	percent	\N	2026-02-24 01:03:59.61+00
\N	260	cpu_usage_percent	25.717543859622992	percent	\N	2026-02-24 00:04:57.887+00
\N	260	cpu_usage_percent	25.533662280690734	percent	\N	2026-02-24 00:05:57.887+00
\N	260	cpu_usage_percent	25.53870614037008	percent	\N	2026-02-24 00:06:57.887+00
\N	260	cpu_usage_percent	25.546381578958403	percent	\N	2026-02-24 00:07:57.887+00
\N	260	cpu_usage_percent	25.504385964891867	percent	\N	2026-02-24 00:08:57.887+00
\N	260	cpu_usage_percent	25.52072368419256	percent	\N	2026-02-24 00:09:57.887+00
\N	260	cpu_usage_percent	25.51030701749322	percent	\N	2026-02-24 00:10:57.887+00
\N	260	cpu_usage_percent	25.53760964912567	percent	\N	2026-02-24 00:11:57.887+00
\N	260	cpu_usage_percent	25.531907894734402	percent	\N	2026-02-24 00:12:57.887+00
\N	260	cpu_usage_percent	25.51315789475524	percent	\N	2026-02-24 00:13:57.887+00
\N	260	cpu_usage_percent	25.56535087721913	percent	\N	2026-02-24 00:14:57.887+00
\N	260	cpu_usage_percent	25.52587719296163	percent	\N	2026-02-24 00:15:57.887+00
\N	260	cpu_usage_percent	25.578618421027315	percent	\N	2026-02-24 00:16:57.887+00
\N	133	cpu_usage_percent	0.44122807019832067	percent	\N	2026-02-24 01:04:59.61+00
\N	133	cpu_usage_percent	1.4714912281437051	percent	\N	2026-02-24 01:05:59.61+00
\N	133	cpu_usage_percent	1.4596491229001458	percent	\N	2026-02-24 01:06:59.61+00
\N	133	cpu_usage_percent	0.4359649122986866	percent	\N	2026-02-24 01:45:01.576+00
\N	248	cpu_usage_percent	2.764912280744241	percent	\N	2026-02-24 00:24:58.523+00
\N	248	cpu_usage_percent	2.7557017543892357	percent	\N	2026-02-24 00:25:58.523+00
\N	248	cpu_usage_percent	2.823684210480579	percent	\N	2026-02-24 00:26:58.523+00
\N	133	cpu_usage_percent	0.45657894745666283	percent	\N	2026-02-24 00:14:57.948+00
\N	133	cpu_usage_percent	0.35570175431898576	percent	\N	2026-02-24 00:15:57.948+00
\N	133	cpu_usage_percent	0.436403508820959	percent	\N	2026-02-24 00:16:57.948+00
\N	133	cpu_usage_percent	0.42149122796234906	percent	\N	2026-02-24 00:17:57.948+00
\N	133	cpu_usage_percent	0.4442982456908453	percent	\N	2026-02-24 00:18:57.948+00
\N	133	cpu_usage_percent	0.4333333332875924	percent	\N	2026-02-24 00:19:57.948+00
\N	133	cpu_usage_percent	0.4447368420905633	percent	\N	2026-02-24 00:20:57.948+00
\N	133	cpu_usage_percent	0.42105263160347306	percent	\N	2026-02-24 00:21:57.948+00
\N	133	cpu_usage_percent	0.42192982456631967	percent	\N	2026-02-24 00:22:57.948+00
\N	133	cpu_usage_percent	0.42280701748831007	percent	\N	2026-02-24 00:23:57.948+00
\N	133	cpu_usage_percent	0.4175438596295322	percent	\N	2026-02-24 00:24:57.948+00
\N	133	cpu_usage_percent	0.4263157894622651	percent	\N	2026-02-24 00:25:57.948+00
\N	133	cpu_usage_percent	0.5100877193342086	percent	\N	2026-02-24 00:26:57.948+00
\N	248	cpu_usage_percent	2.912280701729884	percent	\N	2026-02-24 00:27:58.523+00
\N	248	cpu_usage_percent	2.5903508771341706	percent	\N	2026-02-24 00:28:58.523+00
\N	248	cpu_usage_percent	2.6596491228331587	percent	\N	2026-02-24 00:29:58.523+00
\N	248	cpu_usage_percent	2.7070175437665256	percent	\N	2026-02-24 00:30:58.523+00
\N	248	cpu_usage_percent	2.517982456146896	percent	\N	2026-02-24 00:31:58.523+00
\N	248	cpu_usage_percent	2.4991228070371676	percent	\N	2026-02-24 00:32:58.523+00
\N	248	cpu_usage_percent	2.509649122877292	percent	\N	2026-02-24 00:33:58.523+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	\N	2026-02-24 00:14:58.017+00
\N	236	cpu_usage_percent	1.3298245614165864	percent	\N	2026-02-24 00:15:58.017+00
\N	236	cpu_usage_percent	2.028070175530104	percent	\N	2026-02-24 00:16:58.017+00
\N	236	cpu_usage_percent	2.049122806965258	percent	\N	2026-02-24 00:17:58.017+00
\N	236	cpu_usage_percent	2.035087719232891	percent	\N	2026-02-24 00:18:58.017+00
\N	236	cpu_usage_percent	2.0350877193962873	percent	\N	2026-02-24 00:19:58.017+00
\N	236	cpu_usage_percent	1.6000000000196195	percent	\N	2026-02-24 00:20:58.017+00
\N	236	cpu_usage_percent	1.4807017544578684	percent	\N	2026-02-24 00:21:58.017+00
\N	236	cpu_usage_percent	1.498245614041636	percent	\N	2026-02-24 00:22:58.017+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	\N	2026-02-24 00:23:58.017+00
\N	236	cpu_usage_percent	1.480701754294472	percent	\N	2026-02-24 00:24:58.017+00
\N	236	cpu_usage_percent	1.4596491228593038	percent	\N	2026-02-24 00:25:58.017+00
\N	236	cpu_usage_percent	1.5192982456401865	percent	\N	2026-02-24 00:26:58.017+00
\N	248	cpu_usage_percent	2.4122807017543977	percent	\N	2026-02-24 00:34:58.523+00
\N	248	cpu_usage_percent	2.3548245614214807	percent	\N	2026-02-24 00:35:58.523+00
\N	248	cpu_usage_percent	2.291228070144399	percent	\N	2026-02-24 00:36:58.523+00
\N	133	cpu_usage_percent	0.42236842104773586	percent	\N	2026-02-24 01:46:01.576+00
\N	133	cpu_usage_percent	0.43815789474666644	percent	\N	2026-02-24 01:47:01.576+00
\N	133	cpu_usage_percent	0.49824561400895107	percent	\N	2026-02-24 01:48:01.576+00
\N	133	cpu_usage_percent	0.5236842105442889	percent	\N	2026-02-24 01:49:01.576+00
\N	248	cpu_usage_percent	2.5416666666748426	percent	\N	2026-02-24 00:14:58.095+00
\N	248	cpu_usage_percent	2.486842105189652	percent	\N	2026-02-24 00:15:58.095+00
\N	248	cpu_usage_percent	2.536842105256625	percent	\N	2026-02-24 00:16:58.095+00
\N	248	cpu_usage_percent	2.5004385965222866	percent	\N	2026-02-24 00:17:58.095+00
\N	248	cpu_usage_percent	2.549999999985303	percent	\N	2026-02-24 00:18:58.095+00
\N	248	cpu_usage_percent	2.671929824517292	percent	\N	2026-02-24 00:19:58.095+00
\N	248	cpu_usage_percent	2.624122806979983	percent	\N	2026-02-24 00:20:58.095+00
\N	248	cpu_usage_percent	2.571491228146982	percent	\N	2026-02-24 00:21:58.095+00
\N	248	cpu_usage_percent	2.614912280706676	percent	\N	2026-02-24 00:22:58.095+00
\N	133	cpu_usage_percent	0.5293859648845256	percent	\N	2026-02-24 01:50:01.576+00
\N	133	cpu_usage_percent	0.5078947369270708	percent	\N	2026-02-24 01:51:01.576+00
\N	248	cpu_usage_percent	2.6820175438760003	percent	\N	2026-02-24 00:23:58.095+00
\N	248	cpu_usage_percent	2.764912280744241	percent	\N	2026-02-24 00:24:58.095+00
\N	248	cpu_usage_percent	2.7557017543892357	percent	\N	2026-02-24 00:25:58.095+00
\N	248	cpu_usage_percent	2.823684210480579	percent	\N	2026-02-24 00:26:58.095+00
\N	236	cpu_usage_percent	1.5017543860564189	percent	\N	2026-02-24 00:54:59.678+00
\N	236	cpu_usage_percent	1.470175438576888	percent	\N	2026-02-24 00:55:59.678+00
\N	252	cpu_usage_percent	23.91842105262505	percent	\N	2026-02-24 00:24:58.583+00
\N	252	cpu_usage_percent	24.249561403453228	percent	\N	2026-02-24 00:25:58.583+00
\N	252	cpu_usage_percent	24.23333333335458	percent	\N	2026-02-24 00:26:58.583+00
\N	252	cpu_usage_percent	24.468859649128532	percent	\N	2026-02-24 00:27:58.583+00
\N	252	cpu_usage_percent	24.48815789471969	percent	\N	2026-02-24 00:28:58.583+00
\N	252	cpu_usage_percent	24.560087719286813	percent	\N	2026-02-24 00:14:58.173+00
\N	252	cpu_usage_percent	24.421929824513214	percent	\N	2026-02-24 00:15:58.173+00
\N	252	cpu_usage_percent	23.74210526315055	percent	\N	2026-02-24 00:16:58.173+00
\N	252	cpu_usage_percent	23.581140350873113	percent	\N	2026-02-24 00:17:58.173+00
\N	252	cpu_usage_percent	23.602631578953094	percent	\N	2026-02-24 00:18:58.173+00
\N	252	cpu_usage_percent	24.105263157878397	percent	\N	2026-02-24 00:19:58.173+00
\N	252	cpu_usage_percent	24.02894736839491	percent	\N	2026-02-24 00:20:58.173+00
\N	252	cpu_usage_percent	24.765350877168473	percent	\N	2026-02-24 00:21:58.173+00
\N	252	cpu_usage_percent	24.674122807010207	percent	\N	2026-02-24 00:22:58.173+00
\N	252	cpu_usage_percent	24.541666666699342	percent	\N	2026-02-24 00:23:58.173+00
\N	252	cpu_usage_percent	23.91842105262505	percent	\N	2026-02-24 00:24:58.173+00
\N	252	cpu_usage_percent	24.249561403453228	percent	\N	2026-02-24 00:25:58.173+00
\N	252	cpu_usage_percent	24.23333333335458	percent	\N	2026-02-24 00:26:58.173+00
\N	252	cpu_usage_percent	24.66535087715704	percent	\N	2026-02-24 00:29:58.583+00
\N	252	cpu_usage_percent	24.7837719297968	percent	\N	2026-02-24 00:30:58.583+00
\N	252	cpu_usage_percent	24.7815789473284	percent	\N	2026-02-24 00:31:58.583+00
\N	252	cpu_usage_percent	24.706140350869035	percent	\N	2026-02-24 00:32:58.583+00
\N	252	cpu_usage_percent	24.728070175430446	percent	\N	2026-02-24 00:33:58.583+00
\N	252	cpu_usage_percent	24.370175438581796	percent	\N	2026-02-24 00:34:58.583+00
\N	252	cpu_usage_percent	24.260087719313773	percent	\N	2026-02-24 00:35:58.583+00
\N	257	cpu_usage_percent	4.303508771914309	percent	\N	2026-02-24 00:14:58.246+00
\N	257	cpu_usage_percent	3.8964912280432316	percent	\N	2026-02-24 00:15:58.246+00
\N	257	cpu_usage_percent	3.9798245614133236	percent	\N	2026-02-24 00:16:58.246+00
\N	257	cpu_usage_percent	3.989473684229324	percent	\N	2026-02-24 00:17:58.246+00
\N	257	cpu_usage_percent	4.3421052631783255	percent	\N	2026-02-24 00:18:58.246+00
\N	257	cpu_usage_percent	4.752631578962081	percent	\N	2026-02-24 00:19:58.246+00
\N	257	cpu_usage_percent	5.121052631569157	percent	\N	2026-02-24 00:20:58.246+00
\N	257	cpu_usage_percent	5.222807017567561	percent	\N	2026-02-24 00:21:58.246+00
\N	257	cpu_usage_percent	5.0298245613904555	percent	\N	2026-02-24 00:22:58.246+00
\N	257	cpu_usage_percent	4.597368421086131	percent	\N	2026-02-24 00:23:58.246+00
\N	257	cpu_usage_percent	4.304385964918012	percent	\N	2026-02-24 00:24:58.246+00
\N	257	cpu_usage_percent	3.9350877192868268	percent	\N	2026-02-24 00:25:58.246+00
\N	257	cpu_usage_percent	3.822807017529982	percent	\N	2026-02-24 00:26:58.246+00
\N	252	cpu_usage_percent	24.326315789458988	percent	\N	2026-02-24 00:36:58.583+00
\N	236	cpu_usage_percent	1.470175438576888	percent	\N	2026-02-24 00:56:59.678+00
\N	236	cpu_usage_percent	1.428070175379787	percent	\N	2026-02-24 00:57:59.678+00
\N	236	cpu_usage_percent	1.5964912281682189	percent	\N	2026-02-24 00:58:59.678+00
\N	236	cpu_usage_percent	1.582456140435852	percent	\N	2026-02-24 00:59:59.678+00
\N	236	cpu_usage_percent	1.575438596406272	percent	\N	2026-02-24 01:00:59.678+00
\N	236	cpu_usage_percent	1.498245614041636	percent	\N	2026-02-24 01:01:59.678+00
\N	260	cpu_usage_percent	25.56535087721913	percent	\N	2026-02-24 00:14:58.326+00
\N	260	cpu_usage_percent	25.52587719296163	percent	\N	2026-02-24 00:15:58.326+00
\N	260	cpu_usage_percent	25.578618421027315	percent	\N	2026-02-24 00:16:58.326+00
\N	260	cpu_usage_percent	25.527521929818036	percent	\N	2026-02-24 00:17:58.326+00
\N	260	cpu_usage_percent	25.559210526295374	percent	\N	2026-02-24 00:18:58.326+00
\N	260	cpu_usage_percent	25.52631578942264	percent	\N	2026-02-24 00:19:58.326+00
\N	260	cpu_usage_percent	25.606907894722553	percent	\N	2026-02-24 00:20:58.326+00
\N	260	cpu_usage_percent	25.540241228106126	percent	\N	2026-02-24 00:21:58.326+00
\N	260	cpu_usage_percent	25.571929824603885	percent	\N	2026-02-24 00:22:58.326+00
\N	260	cpu_usage_percent	25.54868421052673	percent	\N	2026-02-24 00:23:58.326+00
\N	260	cpu_usage_percent	25.502192982454105	percent	\N	2026-02-24 00:24:58.326+00
\N	260	cpu_usage_percent	25.526096491273833	percent	\N	2026-02-24 00:25:58.326+00
\N	260	cpu_usage_percent	25.53355263160101	percent	\N	2026-02-24 00:26:58.326+00
\N	236	cpu_usage_percent	1.508771929759206	percent	\N	2026-02-24 01:02:59.678+00
\N	257	cpu_usage_percent	4.304385964918012	percent	\N	2026-02-24 00:24:58.641+00
\N	257	cpu_usage_percent	3.9350877192868268	percent	\N	2026-02-24 00:25:58.641+00
\N	257	cpu_usage_percent	3.822807017529982	percent	\N	2026-02-24 00:26:58.641+00
\N	257	cpu_usage_percent	4.174561403495716	percent	\N	2026-02-24 00:27:58.641+00
\N	257	cpu_usage_percent	4.599999999995106	percent	\N	2026-02-24 00:28:58.641+00
\N	257	cpu_usage_percent	4.935087719278641	percent	\N	2026-02-24 00:29:58.641+00
\N	257	cpu_usage_percent	5.285087719298247	percent	\N	2026-02-24 00:30:58.641+00
\N	257	cpu_usage_percent	4.993859649117098	percent	\N	2026-02-24 00:31:58.641+00
\N	257	cpu_usage_percent	5.038596491223174	percent	\N	2026-02-24 00:32:58.641+00
\N	257	cpu_usage_percent	4.673684210549197	percent	\N	2026-02-24 00:33:58.641+00
\N	257	cpu_usage_percent	4.279824561386363	percent	\N	2026-02-24 00:34:58.641+00
\N	257	cpu_usage_percent	3.9456140350860807	percent	\N	2026-02-24 00:35:58.641+00
\N	257	cpu_usage_percent	3.9280701754614853	percent	\N	2026-02-24 00:36:58.641+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	\N	2026-02-24 01:03:59.678+00
\N	236	cpu_usage_percent	1.536842105223954	percent	\N	2026-02-24 01:04:59.678+00
\N	236	cpu_usage_percent	1.5017543858930225	percent	\N	2026-02-24 01:05:59.678+00
\N	236	cpu_usage_percent	1.498245614041636	percent	\N	2026-02-24 01:06:59.678+00
\N	133	cpu_usage_percent	0.5228070175406003	percent	\N	2026-02-24 01:52:01.576+00
\N	133	cpu_usage_percent	0.4364035086984188	percent	\N	2026-02-24 01:53:01.576+00
\N	133	cpu_usage_percent	0.4250000000588301	percent	\N	2026-02-24 01:54:01.576+00
\N	260	cpu_usage_percent	25.502192982454105	percent	\N	2026-02-24 00:24:58.703+00
\N	260	cpu_usage_percent	25.526096491273833	percent	\N	2026-02-24 00:25:58.703+00
\N	260	cpu_usage_percent	25.53355263160101	percent	\N	2026-02-24 00:26:58.703+00
\N	260	cpu_usage_percent	25.58333333332517	percent	\N	2026-02-24 00:27:58.703+00
\N	260	cpu_usage_percent	25.582456140311265	percent	\N	2026-02-24 00:28:58.703+00
\N	260	cpu_usage_percent	25.558662280724235	percent	\N	2026-02-24 00:29:58.703+00
\N	260	cpu_usage_percent	25.56085526313136	percent	\N	2026-02-24 00:30:58.703+00
\N	260	cpu_usage_percent	25.55131578946633	percent	\N	2026-02-24 00:31:58.703+00
\N	260	cpu_usage_percent	25.597258771957613	percent	\N	2026-02-24 00:32:58.703+00
\N	260	cpu_usage_percent	25.526425438624685	percent	\N	2026-02-24 00:33:58.703+00
\N	260	cpu_usage_percent	25.65087719301677	percent	\N	2026-02-24 00:34:58.703+00
\N	260	cpu_usage_percent	25.551206140366418	percent	\N	2026-02-24 00:35:58.703+00
\N	260	cpu_usage_percent	25.603728070170945	percent	\N	2026-02-24 00:36:58.703+00
\N	133	cpu_usage_percent	0.4241228070142853	percent	\N	2026-02-24 01:55:01.576+00
\N	133	cpu_usage_percent	0.31622807017382115	percent	\N	2026-02-24 01:56:01.576+00
\N	133	cpu_usage_percent	0.41359649121500297	percent	\N	2026-02-24 01:57:01.576+00
\N	133	cpu_usage_percent	0.42938596491391934	percent	cpu	2026-02-24 02:44:30.519+00
\N	248	cpu_usage_percent	2.6583333332663557	percent	\N	2026-02-24 00:54:59.734+00
\N	248	cpu_usage_percent	2.65877192982947	percent	\N	2026-02-24 00:55:59.734+00
\N	248	cpu_usage_percent	2.6592105263109005	percent	\N	2026-02-24 00:56:59.734+00
\N	133	cpu_usage_percent	0.4434210526054585	percent	\N	2026-02-24 00:34:58.768+00
\N	248	cpu_usage_percent	2.584210526353388	percent	\N	2026-02-24 00:57:59.734+00
\N	133	cpu_usage_percent	0.43903508770949884	percent	\N	2026-02-24 00:35:58.768+00
\N	133	cpu_usage_percent	0.43947368419092925	percent	\N	2026-02-24 00:36:58.768+00
\N	133	cpu_usage_percent	0.5223684211000261	percent	\N	2026-02-24 00:37:58.768+00
\N	133	cpu_usage_percent	0.5346491228250017	percent	\N	2026-02-24 00:38:58.768+00
\N	133	cpu_usage_percent	0.5188596492077835	percent	\N	2026-02-24 00:39:58.768+00
\N	133	cpu_usage_percent	0.5250000000702642	percent	\N	2026-02-24 00:40:58.768+00
\N	133	cpu_usage_percent	0.43815789470581024	percent	\N	2026-02-24 00:41:58.768+00
\N	133	cpu_usage_percent	0.4355263157764142	percent	\N	2026-02-24 00:42:58.768+00
\N	133	cpu_usage_percent	0.4421052631203253	percent	\N	2026-02-24 00:43:58.768+00
\N	133	cpu_usage_percent	0.44078947371689026	percent	\N	2026-02-24 00:44:58.768+00
\N	133	cpu_usage_percent	0.4258771930625329	percent	\N	2026-02-24 00:45:58.768+00
\N	133	cpu_usage_percent	0.41929824551438344	percent	\N	2026-02-24 00:46:58.768+00
\N	248	cpu_usage_percent	2.5451754385670995	percent	\N	2026-02-24 00:58:59.734+00
\N	248	cpu_usage_percent	2.4535087719069537	percent	\N	2026-02-24 00:59:59.734+00
\N	248	cpu_usage_percent	2.614035087702973	percent	\N	2026-02-24 01:00:59.734+00
\N	248	cpu_usage_percent	2.565350877161947	percent	\N	2026-02-24 01:01:59.734+00
\N	248	cpu_usage_percent	2.4592105263288744	percent	\N	2026-02-24 01:02:59.734+00
\N	248	cpu_usage_percent	2.4337719297935223	percent	\N	2026-02-24 01:03:59.734+00
\N	248	cpu_usage_percent	2.4311403508641405	percent	\N	2026-02-24 01:04:59.734+00
\N	236	cpu_usage_percent	1.456140350844521	percent	\N	2026-02-24 00:34:58.834+00
\N	236	cpu_usage_percent	1.4631578947107045	percent	\N	2026-02-24 00:35:58.834+00
\N	236	cpu_usage_percent	1.4140350876474201	percent	\N	2026-02-24 00:36:58.834+00
\N	236	cpu_usage_percent	1.6000000000196195	percent	\N	2026-02-24 00:37:58.834+00
\N	236	cpu_usage_percent	1.6105263159005858	percent	\N	2026-02-24 00:38:58.834+00
\N	236	cpu_usage_percent	1.592982456153436	percent	\N	2026-02-24 00:39:58.834+00
\N	236	cpu_usage_percent	1.589473684138639	percent	\N	2026-02-24 00:40:58.834+00
\N	236	cpu_usage_percent	1.442105263112154	percent	\N	2026-02-24 00:41:58.834+00
\N	236	cpu_usage_percent	1.4210526316769858	percent	\N	2026-02-24 00:42:58.834+00
\N	236	cpu_usage_percent	1.449122807141734	percent	\N	2026-02-24 00:43:58.834+00
\N	236	cpu_usage_percent	1.4631578948741009	percent	\N	2026-02-24 00:44:58.834+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	\N	2026-02-24 00:45:58.834+00
\N	236	cpu_usage_percent	1.5824561402724555	percent	\N	2026-02-24 00:46:58.834+00
\N	248	cpu_usage_percent	2.254824561450903	percent	\N	2026-02-24 01:05:59.734+00
\N	248	cpu_usage_percent	2.3350877192672215	percent	\N	2026-02-24 01:06:59.734+00
\N	133	cpu_usage_percent	0.42017543851807204	percent	cpu	2026-02-24 02:45:30.519+00
\N	133	cpu_usage_percent	0.41973684211833984	percent	cpu	2026-02-24 02:46:30.519+00
\N	133	cpu_usage_percent	0.42850877191023073	percent	cpu	2026-02-24 02:47:30.519+00
\N	133	cpu_usage_percent	0.4241228070142995	percent	cpu	2026-02-24 02:48:30.519+00
\N	133	cpu_usage_percent	0.4285087719919147	percent	cpu	2026-02-24 02:49:30.519+00
\N	248	cpu_usage_percent	2.4122807017543977	percent	\N	2026-02-24 00:34:58.9+00
\N	248	cpu_usage_percent	2.3548245614214807	percent	\N	2026-02-24 00:35:58.9+00
\N	248	cpu_usage_percent	2.291228070144399	percent	\N	2026-02-24 00:36:58.9+00
\N	248	cpu_usage_percent	2.367105263146456	percent	\N	2026-02-24 00:37:58.9+00
\N	248	cpu_usage_percent	2.3697368420758664	percent	\N	2026-02-24 00:38:58.9+00
\N	248	cpu_usage_percent	2.4267543860498932	percent	\N	2026-02-24 00:39:58.9+00
\N	248	cpu_usage_percent	2.490789473685851	percent	\N	2026-02-24 00:40:58.9+00
\N	248	cpu_usage_percent	2.534649122808659	percent	\N	2026-02-24 00:41:58.9+00
\N	248	cpu_usage_percent	2.5771929824463484	percent	\N	2026-02-24 00:42:58.9+00
\N	248	cpu_usage_percent	2.7140350877552493	percent	\N	2026-02-24 00:43:58.9+00
\N	248	cpu_usage_percent	2.763157894777706	percent	\N	2026-02-24 00:44:58.9+00
\N	248	cpu_usage_percent	2.7385964912052003	percent	\N	2026-02-24 00:45:58.9+00
\N	248	cpu_usage_percent	2.5912280703012556	percent	\N	2026-02-24 00:46:58.9+00
\N	236	cpu_usage_percent	1.4771929826064678	percent	\N	2026-02-24 01:45:01.675+00
\N	252	cpu_usage_percent	22.831140350869035	percent	\N	2026-02-24 00:54:59.79+00
\N	252	cpu_usage_percent	23.40614035082247	percent	\N	2026-02-24 00:55:59.79+00
\N	252	cpu_usage_percent	23.360087719272116	percent	\N	2026-02-24 00:56:59.79+00
\N	252	cpu_usage_percent	23.177631578975962	percent	\N	2026-02-24 00:57:59.79+00
\N	252	cpu_usage_percent	23.26885964907298	percent	\N	2026-02-24 00:58:59.79+00
\N	252	cpu_usage_percent	24.370175438581796	percent	\N	2026-02-24 00:34:58.977+00
\N	252	cpu_usage_percent	24.260087719313773	percent	\N	2026-02-24 00:35:58.977+00
\N	252	cpu_usage_percent	24.326315789458988	percent	\N	2026-02-24 00:36:58.977+00
\N	252	cpu_usage_percent	24.35745614039581	percent	\N	2026-02-24 00:37:58.977+00
\N	252	cpu_usage_percent	24.0846491227817	percent	\N	2026-02-24 00:38:58.977+00
\N	252	cpu_usage_percent	24.16622807018524	percent	\N	2026-02-24 00:39:58.977+00
\N	252	cpu_usage_percent	24.17982456139535	percent	\N	2026-02-24 00:40:58.977+00
\N	252	cpu_usage_percent	24.328947368408805	percent	\N	2026-02-24 00:41:58.977+00
\N	252	cpu_usage_percent	24.483333333321895	percent	\N	2026-02-24 00:42:58.977+00
\N	252	cpu_usage_percent	24.660964912261107	percent	\N	2026-02-24 00:43:58.977+00
\N	252	cpu_usage_percent	24.757894736841294	percent	\N	2026-02-24 00:44:58.977+00
\N	252	cpu_usage_percent	25.14385964905256	percent	\N	2026-02-24 00:45:58.977+00
\N	252	cpu_usage_percent	25.05438596494251	percent	\N	2026-02-24 00:46:58.977+00
\N	252	cpu_usage_percent	23.00526315787515	percent	\N	2026-02-24 00:59:59.79+00
\N	252	cpu_usage_percent	23.404385964917196	percent	\N	2026-02-24 01:00:59.79+00
\N	252	cpu_usage_percent	23.362280701740502	percent	\N	2026-02-24 01:01:59.79+00
\N	252	cpu_usage_percent	23.444736842086485	percent	\N	2026-02-24 01:02:59.79+00
\N	252	cpu_usage_percent	23.58026315788983	percent	\N	2026-02-24 01:03:59.79+00
\N	252	cpu_usage_percent	23.69473684215592	percent	\N	2026-02-24 01:04:59.79+00
\N	252	cpu_usage_percent	23.559210526311716	percent	\N	2026-02-24 01:05:59.79+00
\N	257	cpu_usage_percent	4.279824561386363	percent	\N	2026-02-24 00:34:59.048+00
\N	257	cpu_usage_percent	3.9456140350860807	percent	\N	2026-02-24 00:35:59.048+00
\N	257	cpu_usage_percent	3.9280701754614853	percent	\N	2026-02-24 00:36:59.048+00
\N	257	cpu_usage_percent	4.164035087716854	percent	\N	2026-02-24 00:37:59.048+00
\N	257	cpu_usage_percent	4.56666666667158	percent	\N	2026-02-24 00:38:59.048+00
\N	257	cpu_usage_percent	4.948245614027741	percent	\N	2026-02-24 00:39:59.048+00
\N	257	cpu_usage_percent	5.342105263170154	percent	\N	2026-02-24 00:40:59.048+00
\N	257	cpu_usage_percent	5.242982456142002	percent	\N	2026-02-24 00:41:59.048+00
\N	257	cpu_usage_percent	5.091228070178715	percent	\N	2026-02-24 00:42:59.048+00
\N	257	cpu_usage_percent	4.735964912279897	percent	\N	2026-02-24 00:43:59.048+00
\N	257	cpu_usage_percent	4.343859649124454	percent	\N	2026-02-24 00:44:59.048+00
\N	257	cpu_usage_percent	3.944736842102813	percent	\N	2026-02-24 00:45:59.048+00
\N	257	cpu_usage_percent	3.921929824537713	percent	\N	2026-02-24 00:46:59.048+00
\N	252	cpu_usage_percent	23.45307017545821	percent	\N	2026-02-24 01:06:59.79+00
\N	236	cpu_usage_percent	1.5017543858930225	percent	\N	2026-02-24 01:46:01.675+00
\N	236	cpu_usage_percent	1.5964912281682189	percent	\N	2026-02-24 01:47:01.675+00
\N	236	cpu_usage_percent	1.5964912281682189	percent	\N	2026-02-24 01:48:01.675+00
\N	236	cpu_usage_percent	1.7298245614623369	percent	\N	2026-02-24 01:49:01.675+00
\N	236	cpu_usage_percent	1.768421052644669	percent	\N	2026-02-24 01:50:01.675+00
\N	236	cpu_usage_percent	1.631578947335754	percent	\N	2026-02-24 01:51:01.675+00
\N	260	cpu_usage_percent	25.65087719301677	percent	\N	2026-02-24 00:34:59.114+00
\N	260	cpu_usage_percent	25.551206140366418	percent	\N	2026-02-24 00:35:59.114+00
\N	260	cpu_usage_percent	25.603728070170945	percent	\N	2026-02-24 00:36:59.114+00
\N	260	cpu_usage_percent	25.58267543863367	percent	\N	2026-02-24 00:37:59.114+00
\N	260	cpu_usage_percent	25.648355263146456	percent	\N	2026-02-24 00:38:59.114+00
\N	260	cpu_usage_percent	25.569736842125295	percent	\N	2026-02-24 00:39:59.114+00
\N	236	cpu_usage_percent	1.687719298265236	percent	\N	2026-02-24 01:52:01.675+00
\N	236	cpu_usage_percent	1.5719298245548714	percent	\N	2026-02-24 01:53:01.675+00
\N	260	cpu_usage_percent	25.64155701751079	percent	\N	2026-02-24 00:40:59.114+00
\N	260	cpu_usage_percent	25.6694078947246	percent	\N	2026-02-24 00:41:59.114+00
\N	260	cpu_usage_percent	25.60888157896045	percent	\N	2026-02-24 00:42:59.114+00
\N	260	cpu_usage_percent	25.65515350875151	percent	\N	2026-02-24 00:43:59.114+00
\N	260	cpu_usage_percent	25.58399122806773	percent	\N	2026-02-24 00:44:59.114+00
\N	260	cpu_usage_percent	25.57017543858629	percent	\N	2026-02-24 00:45:59.114+00
\N	260	cpu_usage_percent	25.5692982455826	percent	\N	2026-02-24 00:46:59.114+00
\N	257	cpu_usage_percent	4.025438596502667	percent	\N	2026-02-24 00:54:59.861+00
\N	257	cpu_usage_percent	3.822807017529982	percent	\N	2026-02-24 00:55:59.861+00
\N	257	cpu_usage_percent	3.8271929824667694	percent	\N	2026-02-24 00:56:59.861+00
\N	257	cpu_usage_percent	4.1719298245663055	percent	\N	2026-02-24 00:57:59.861+00
\N	257	cpu_usage_percent	4.555263157868609	percent	\N	2026-02-24 00:58:59.861+00
\N	257	cpu_usage_percent	4.925438596483062	percent	\N	2026-02-24 00:59:59.861+00
\N	257	cpu_usage_percent	5.313157894742574	percent	\N	2026-02-24 01:00:59.861+00
\N	133	cpu_usage_percent	0.44078947371689026	percent	\N	2026-02-24 00:44:59.18+00
\N	133	cpu_usage_percent	0.4258771930625329	percent	\N	2026-02-24 00:45:59.18+00
\N	133	cpu_usage_percent	0.41929824551438344	percent	\N	2026-02-24 00:46:59.18+00
\N	133	cpu_usage_percent	0.46666666665197454	percent	\N	2026-02-24 00:47:59.18+00
\N	133	cpu_usage_percent	0.5377192982358139	percent	\N	2026-02-24 00:48:59.18+00
\N	133	cpu_usage_percent	0.5359649122284225	percent	\N	2026-02-24 00:49:59.18+00
\N	133	cpu_usage_percent	0.5118421052190456	percent	\N	2026-02-24 00:50:59.18+00
\N	133	cpu_usage_percent	0.44210526312031106	percent	\N	2026-02-24 00:51:59.18+00
\N	133	cpu_usage_percent	0.30614035089681124	percent	\N	2026-02-24 00:52:59.18+00
\N	133	cpu_usage_percent	0.40350877185630907	percent	\N	2026-02-24 00:53:59.18+00
\N	133	cpu_usage_percent	0.39035087716848693	percent	\N	2026-02-24 00:54:59.18+00
\N	133	cpu_usage_percent	0.4166666665441312	percent	\N	2026-02-24 00:55:59.18+00
\N	133	cpu_usage_percent	0.4157894737038248	percent	\N	2026-02-24 00:56:59.18+00
\N	257	cpu_usage_percent	5.434210526332137	percent	\N	2026-02-24 01:01:59.861+00
\N	257	cpu_usage_percent	5.01754385966548	percent	\N	2026-02-24 01:02:59.861+00
\N	257	cpu_usage_percent	4.592105263145655	percent	\N	2026-02-24 01:03:59.861+00
\N	257	cpu_usage_percent	4.318421052629958	percent	\N	2026-02-24 01:04:59.861+00
\N	257	cpu_usage_percent	3.9807017543965912	percent	\N	2026-02-24 01:05:59.861+00
\N	257	cpu_usage_percent	3.9385964912403324	percent	\N	2026-02-24 01:06:59.861+00
\N	236	cpu_usage_percent	1.5473684211049203	percent	\N	2026-02-24 01:54:01.675+00
\N	236	cpu_usage_percent	1.4631578948741009	percent	\N	2026-02-24 00:44:59.286+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	\N	2026-02-24 00:45:59.286+00
\N	236	cpu_usage_percent	1.5824561402724555	percent	\N	2026-02-24 00:46:59.286+00
\N	236	cpu_usage_percent	1.575438596406272	percent	\N	2026-02-24 00:47:59.286+00
\N	236	cpu_usage_percent	1.592982456153436	percent	\N	2026-02-24 00:48:59.286+00
\N	236	cpu_usage_percent	1.5859649122872526	percent	\N	2026-02-24 00:49:59.286+00
\N	236	cpu_usage_percent	1.6140350877519865	percent	\N	2026-02-24 00:50:59.286+00
\N	236	cpu_usage_percent	1.494736842026839	percent	\N	2026-02-24 00:51:59.286+00
\N	236	cpu_usage_percent	1.3298245614165864	percent	\N	2026-02-24 00:52:59.286+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	\N	2026-02-24 00:53:59.286+00
\N	236	cpu_usage_percent	1.5017543860564189	percent	\N	2026-02-24 00:54:59.286+00
\N	236	cpu_usage_percent	1.470175438576888	percent	\N	2026-02-24 00:55:59.286+00
\N	236	cpu_usage_percent	1.470175438576888	percent	\N	2026-02-24 00:56:59.286+00
\N	236	cpu_usage_percent	1.5017543860564189	percent	\N	2026-02-24 01:55:01.675+00
\N	236	cpu_usage_percent	1.3192982455356201	percent	\N	2026-02-24 01:56:01.675+00
\N	236	cpu_usage_percent	1.4245614035283864	percent	\N	2026-02-24 01:57:01.675+00
\N	133	cpu_usage_percent	0.5206140350926205	percent	cpu	2026-02-24 02:50:30.519+00
\N	133	cpu_usage_percent	0.7061403509017055	percent	cpu	2026-02-24 02:51:30.519+00
\N	133	cpu_usage_percent	0.6960526316247098	percent	cpu	2026-02-24 02:52:30.519+00
\N	260	cpu_usage_percent	28.906140350859232	percent	\N	2026-02-24 00:54:59.938+00
\N	248	cpu_usage_percent	2.763157894777706	percent	\N	2026-02-24 00:44:59.351+00
\N	248	cpu_usage_percent	2.7385964912052003	percent	\N	2026-02-24 00:45:59.351+00
\N	248	cpu_usage_percent	2.5912280703012556	percent	\N	2026-02-24 00:46:59.351+00
\N	248	cpu_usage_percent	2.6144736841435474	percent	\N	2026-02-24 00:47:59.351+00
\N	248	cpu_usage_percent	2.4144736842023633	percent	\N	2026-02-24 00:48:59.351+00
\N	248	cpu_usage_percent	2.361403508847104	percent	\N	2026-02-24 00:49:59.351+00
\N	248	cpu_usage_percent	2.315350877194618	percent	\N	2026-02-24 00:50:59.351+00
\N	248	cpu_usage_percent	2.3074561403655878	percent	\N	2026-02-24 00:51:59.351+00
\N	248	cpu_usage_percent	2.30526315787678	percent	\N	2026-02-24 00:52:59.351+00
\N	248	cpu_usage_percent	2.4706140350910033	percent	\N	2026-02-24 00:53:59.351+00
\N	248	cpu_usage_percent	2.6583333332663557	percent	\N	2026-02-24 00:54:59.351+00
\N	248	cpu_usage_percent	2.65877192982947	percent	\N	2026-02-24 00:55:59.351+00
\N	248	cpu_usage_percent	2.6592105263109005	percent	\N	2026-02-24 00:56:59.351+00
\N	260	cpu_usage_percent	29.137828947390076	percent	\N	2026-02-24 00:55:59.938+00
\N	260	cpu_usage_percent	29.616776315807854	percent	\N	2026-02-24 00:56:59.938+00
\N	260	cpu_usage_percent	29.65471491225783	percent	\N	2026-02-24 00:57:59.938+00
\N	260	cpu_usage_percent	29.635964912288884	percent	\N	2026-02-24 00:58:59.938+00
\N	260	cpu_usage_percent	29.648574561405567	percent	\N	2026-02-24 00:59:59.938+00
\N	260	cpu_usage_percent	28.86085526314116	percent	\N	2026-02-24 01:00:59.938+00
\N	260	cpu_usage_percent	27.829385964943327	percent	\N	2026-02-24 01:01:59.938+00
\N	252	cpu_usage_percent	24.869298245614857	percent	\N	2026-02-24 00:44:59.412+00
\N	252	cpu_usage_percent	25.11140350883484	percent	\N	2026-02-24 00:45:59.412+00
\N	252	cpu_usage_percent	24.82763157894003	percent	\N	2026-02-24 00:46:59.412+00
\N	252	cpu_usage_percent	24.807894736847018	percent	\N	2026-02-24 00:47:59.412+00
\N	252	cpu_usage_percent	24.71973684209955	percent	\N	2026-02-24 00:48:59.412+00
\N	252	cpu_usage_percent	24.28464912280458	percent	\N	2026-02-24 00:49:59.412+00
\N	252	cpu_usage_percent	22.995614035099976	percent	\N	2026-02-24 00:50:59.412+00
\N	252	cpu_usage_percent	22.76140350879072	percent	\N	2026-02-24 00:51:59.412+00
\N	252	cpu_usage_percent	22.588157894747468	percent	\N	2026-02-24 00:52:59.412+00
\N	252	cpu_usage_percent	22.414912280724636	percent	\N	2026-02-24 00:53:59.412+00
\N	252	cpu_usage_percent	22.831140350869035	percent	\N	2026-02-24 00:54:59.412+00
\N	252	cpu_usage_percent	23.40614035082247	percent	\N	2026-02-24 00:55:59.412+00
\N	252	cpu_usage_percent	23.360087719272116	percent	\N	2026-02-24 00:56:59.412+00
\N	260	cpu_usage_percent	27.103070175456992	percent	\N	2026-02-24 01:02:59.938+00
\N	260	cpu_usage_percent	26.40219298247534	percent	\N	2026-02-24 01:03:59.938+00
\N	260	cpu_usage_percent	25.628837719273747	percent	\N	2026-02-24 01:04:59.938+00
\N	260	cpu_usage_percent	25.458442982431222	percent	\N	2026-02-24 01:05:59.938+00
\N	260	cpu_usage_percent	25.53278508773809	percent	\N	2026-02-24 01:06:59.938+00
\N	133	cpu_usage_percent	0.6925438596507689	percent	cpu	2026-02-24 02:53:30.519+00
\N	133	cpu_usage_percent	0.5842105262880182	percent	cpu	2026-02-24 02:54:30.519+00
\N	257	cpu_usage_percent	4.343859649124454	percent	\N	2026-02-24 00:44:59.488+00
\N	257	cpu_usage_percent	3.944736842102813	percent	\N	2026-02-24 00:45:59.488+00
\N	257	cpu_usage_percent	3.921929824537713	percent	\N	2026-02-24 00:46:59.488+00
\N	257	cpu_usage_percent	3.9771929824430856	percent	\N	2026-02-24 00:47:59.488+00
\N	257	cpu_usage_percent	4.641228070208953	percent	\N	2026-02-24 00:48:59.488+00
\N	257	cpu_usage_percent	5.005263157879227	percent	\N	2026-02-24 00:49:59.488+00
\N	257	cpu_usage_percent	5.1631578947662575	percent	\N	2026-02-24 00:50:59.488+00
\N	257	cpu_usage_percent	5.0491228070428775	percent	\N	2026-02-24 00:51:59.488+00
\N	257	cpu_usage_percent	4.579824561400244	percent	\N	2026-02-24 00:52:59.488+00
\N	257	cpu_usage_percent	4.364912280702583	percent	\N	2026-02-24 00:53:59.488+00
\N	257	cpu_usage_percent	4.025438596502667	percent	\N	2026-02-24 00:54:59.488+00
\N	133	cpu_usage_percent	0.600438596509207	percent	cpu	2026-02-24 02:55:30.519+00
\N	257	cpu_usage_percent	3.822807017529982	percent	\N	2026-02-24 00:55:59.488+00
\N	257	cpu_usage_percent	3.8271929824667694	percent	\N	2026-02-24 00:56:59.488+00
\N	248	cpu_usage_percent	2.8995614035234922	percent	\N	2026-02-24 01:45:01.738+00
\N	248	cpu_usage_percent	2.981140350906614	percent	\N	2026-02-24 01:46:01.738+00
\N	248	cpu_usage_percent	2.9092105262373735	percent	\N	2026-02-24 01:47:01.738+00
\N	248	cpu_usage_percent	2.8820175438171844	percent	\N	2026-02-24 01:48:01.738+00
\N	133	cpu_usage_percent	0.44122807019832067	percent	\N	2026-02-24 01:05:00.012+00
\N	133	cpu_usage_percent	1.4714912281437051	percent	\N	2026-02-24 01:06:00.012+00
\N	133	cpu_usage_percent	1.4596491229001458	percent	\N	2026-02-24 01:07:00.012+00
\N	260	cpu_usage_percent	25.58399122806773	percent	\N	2026-02-24 00:44:59.551+00
\N	260	cpu_usage_percent	25.57017543858629	percent	\N	2026-02-24 00:45:59.551+00
\N	260	cpu_usage_percent	25.5692982455826	percent	\N	2026-02-24 00:46:59.551+00
\N	260	cpu_usage_percent	25.858881578948186	percent	\N	2026-02-24 00:47:59.551+00
\N	260	cpu_usage_percent	26.62423245615956	percent	\N	2026-02-24 00:48:59.551+00
\N	260	cpu_usage_percent	27.305263157907405	percent	\N	2026-02-24 00:49:59.551+00
\N	260	cpu_usage_percent	28.026315789453264	percent	\N	2026-02-24 00:50:59.551+00
\N	260	cpu_usage_percent	28.688486842122018	percent	\N	2026-02-24 00:51:59.551+00
\N	260	cpu_usage_percent	28.891008771923296	percent	\N	2026-02-24 00:52:59.551+00
\N	260	cpu_usage_percent	28.833223684219107	percent	\N	2026-02-24 00:53:59.551+00
\N	260	cpu_usage_percent	28.906140350859232	percent	\N	2026-02-24 00:54:59.551+00
\N	260	cpu_usage_percent	29.137828947390076	percent	\N	2026-02-24 00:55:59.551+00
\N	260	cpu_usage_percent	29.616776315807854	percent	\N	2026-02-24 00:56:59.551+00
\N	133	cpu_usage_percent	1.5758771929285444	percent	\N	2026-02-24 01:08:00.012+00
\N	133	cpu_usage_percent	1.468859649091769	percent	\N	2026-02-24 01:09:00.012+00
\N	133	cpu_usage_percent	0.941228070132965	percent	\N	2026-02-24 01:10:00.012+00
\N	133	cpu_usage_percent	0.5315789473733332	percent	\N	2026-02-24 01:11:00.012+00
\N	133	cpu_usage_percent	0.5210526314923527	percent	\N	2026-02-24 01:12:00.012+00
\N	133	cpu_usage_percent	0.42192982452546346	percent	\N	2026-02-24 01:13:00.012+00
\N	133	cpu_usage_percent	0.3127192982815785	percent	\N	2026-02-24 01:14:00.012+00
\N	133	cpu_usage_percent	0.4131578946927448	percent	\N	2026-02-24 01:15:00.012+00
\N	133	cpu_usage_percent	0.4070175438710919	percent	\N	2026-02-24 01:16:00.012+00
\N	133	cpu_usage_percent	1.298245614100452	percent	\N	2026-02-24 01:17:00.012+00
\N	248	cpu_usage_percent	2.6570175438629207	percent	\N	2026-02-24 01:49:01.738+00
\N	248	cpu_usage_percent	2.2881578947335868	percent	\N	2026-02-24 01:50:01.738+00
\N	248	cpu_usage_percent	2.333333333382356	percent	\N	2026-02-24 01:51:01.738+00
\N	248	cpu_usage_percent	2.362719298291367	percent	\N	2026-02-24 01:52:01.738+00
\N	248	cpu_usage_percent	2.329385964967841	percent	\N	2026-02-24 01:53:01.738+00
\N	248	cpu_usage_percent	2.3328947368192416	percent	\N	2026-02-24 01:54:01.738+00
\N	248	cpu_usage_percent	2.348245614036742	percent	\N	2026-02-24 01:55:01.738+00
\N	236	cpu_usage_percent	1.536842105223954	percent	\N	2026-02-24 01:05:00.083+00
\N	236	cpu_usage_percent	1.5017543858930225	percent	\N	2026-02-24 01:06:00.083+00
\N	236	cpu_usage_percent	1.498245614041636	percent	\N	2026-02-24 01:07:00.083+00
\N	236	cpu_usage_percent	1.6000000000196195	percent	\N	2026-02-24 01:08:00.083+00
\N	236	cpu_usage_percent	1.6035087720344023	percent	\N	2026-02-24 01:09:00.083+00
\N	236	cpu_usage_percent	1.6000000000196195	percent	\N	2026-02-24 01:10:00.083+00
\N	236	cpu_usage_percent	1.6280701754843534	percent	\N	2026-02-24 01:11:00.083+00
\N	236	cpu_usage_percent	1.6421052632167203	percent	\N	2026-02-24 01:12:00.083+00
\N	236	cpu_usage_percent	1.5157894736253894	percent	\N	2026-02-24 01:13:00.083+00
\N	236	cpu_usage_percent	1.3508771930151369	percent	\N	2026-02-24 01:14:00.083+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	\N	2026-02-24 01:15:00.083+00
\N	236	cpu_usage_percent	1.4385964912607534	percent	\N	2026-02-24 01:16:00.083+00
\N	236	cpu_usage_percent	1.4350877192459706	percent	\N	2026-02-24 01:17:00.083+00
\N	248	cpu_usage_percent	2.199999999965698	percent	\N	2026-02-24 01:56:01.738+00
\N	248	cpu_usage_percent	2.301315789421409	percent	\N	2026-02-24 01:57:01.738+00
\N	133	cpu_usage_percent	0.43157894732104296	percent	cpu	2026-02-24 02:56:30.519+00
\N	133	cpu_usage_percent	0.4241228070142995	percent	cpu	2026-02-24 02:48:22.623+00
\N	133	cpu_usage_percent	0.4285087719919147	percent	cpu	2026-02-24 02:49:22.623+00
\N	133	cpu_usage_percent	0.5206140350926205	percent	cpu	2026-02-24 02:50:22.623+00
\N	133	cpu_usage_percent	0.7061403509017055	percent	cpu	2026-02-24 02:51:22.623+00
\N	248	cpu_usage_percent	2.4311403508641405	percent	\N	2026-02-24 01:05:00.147+00
\N	248	cpu_usage_percent	2.254824561450903	percent	\N	2026-02-24 01:06:00.147+00
\N	248	cpu_usage_percent	2.3350877192672215	percent	\N	2026-02-24 01:07:00.147+00
\N	248	cpu_usage_percent	2.4653508772322112	percent	\N	2026-02-24 01:08:00.147+00
\N	248	cpu_usage_percent	2.432017543867829	percent	\N	2026-02-24 01:09:00.147+00
\N	248	cpu_usage_percent	2.3570175438286043	percent	\N	2026-02-24 01:10:00.147+00
\N	248	cpu_usage_percent	2.367543859627901	percent	\N	2026-02-24 01:11:00.147+00
\N	248	cpu_usage_percent	2.252631579002923	percent	\N	2026-02-24 01:12:00.147+00
\N	248	cpu_usage_percent	2.188596491244425	percent	\N	2026-02-24 01:13:00.147+00
\N	248	cpu_usage_percent	2.1236842105230522	percent	\N	2026-02-24 01:14:00.147+00
\N	248	cpu_usage_percent	2.1741228069897716	percent	\N	2026-02-24 01:15:00.147+00
\N	248	cpu_usage_percent	2.1864035088781435	percent	\N	2026-02-24 01:16:00.147+00
\N	248	cpu_usage_percent	2.2184210527165504	percent	\N	2026-02-24 01:17:00.147+00
\N	133	cpu_usage_percent	0.6960526316247098	percent	cpu	2026-02-24 02:52:22.623+00
\N	252	cpu_usage_percent	32.42850877189389	percent	\N	2026-02-24 01:45:01.793+00
\N	252	cpu_usage_percent	34.61929824562712	percent	\N	2026-02-24 01:46:01.793+00
\N	252	cpu_usage_percent	33.38903508774055	percent	\N	2026-02-24 01:47:01.793+00
\N	252	cpu_usage_percent	30.451315789454895	percent	\N	2026-02-24 01:48:01.793+00
\N	252	cpu_usage_percent	27.866228070199952	percent	\N	2026-02-24 01:49:01.793+00
\N	252	cpu_usage_percent	23.69473684215592	percent	\N	2026-02-24 01:05:00.204+00
\N	252	cpu_usage_percent	23.559210526311716	percent	\N	2026-02-24 01:06:00.204+00
\N	252	cpu_usage_percent	23.45307017545821	percent	\N	2026-02-24 01:07:00.204+00
\N	252	cpu_usage_percent	23.445614035069752	percent	\N	2026-02-24 01:08:00.204+00
\N	252	cpu_usage_percent	23.308771929801694	percent	\N	2026-02-24 01:09:00.204+00
\N	252	cpu_usage_percent	23.087280701739687	percent	\N	2026-02-24 01:10:00.204+00
\N	252	cpu_usage_percent	23.079385964890236	percent	\N	2026-02-24 01:11:00.204+00
\N	252	cpu_usage_percent	23.166666666674843	percent	\N	2026-02-24 01:12:00.204+00
\N	252	cpu_usage_percent	23.02938596488451	percent	\N	2026-02-24 01:13:00.204+00
\N	252	cpu_usage_percent	22.857017543865382	percent	\N	2026-02-24 01:14:00.204+00
\N	252	cpu_usage_percent	23.00482456143456	percent	\N	2026-02-24 01:15:00.204+00
\N	252	cpu_usage_percent	22.828070175396945	percent	\N	2026-02-24 01:16:00.204+00
\N	252	cpu_usage_percent	23.004385964891867	percent	\N	2026-02-24 01:17:00.204+00
\N	252	cpu_usage_percent	25.05263157893512	percent	\N	2026-02-24 01:50:01.793+00
\N	252	cpu_usage_percent	24.213596491200306	percent	\N	2026-02-24 01:51:01.793+00
\N	252	cpu_usage_percent	24.16052631582461	percent	\N	2026-02-24 01:52:01.793+00
\N	252	cpu_usage_percent	24.10000000001962	percent	\N	2026-02-24 01:53:01.793+00
\N	252	cpu_usage_percent	23.925000000009817	percent	\N	2026-02-24 01:54:01.793+00
\N	252	cpu_usage_percent	24.07807017545821	percent	\N	2026-02-24 01:55:01.793+00
\N	252	cpu_usage_percent	23.38333333331863	percent	\N	2026-02-24 01:56:01.793+00
\N	257	cpu_usage_percent	4.318421052629958	percent	\N	2026-02-24 01:05:00.262+00
\N	257	cpu_usage_percent	3.9807017543965912	percent	\N	2026-02-24 01:06:00.262+00
\N	257	cpu_usage_percent	3.9385964912403324	percent	\N	2026-02-24 01:07:00.262+00
\N	257	cpu_usage_percent	4.180701754419474	percent	\N	2026-02-24 01:08:00.262+00
\N	257	cpu_usage_percent	4.343859649104033	percent	\N	2026-02-24 01:09:00.262+00
\N	257	cpu_usage_percent	4.897368421038749	percent	\N	2026-02-24 01:10:00.262+00
\N	257	cpu_usage_percent	5.210526315760887	percent	\N	2026-02-24 01:11:00.262+00
\N	252	cpu_usage_percent	23.6956140351392	percent	\N	2026-02-24 01:57:01.793+00
\N	257	cpu_usage_percent	5.314912280709123	percent	\N	2026-02-24 01:12:00.262+00
\N	257	cpu_usage_percent	4.992105263191405	percent	\N	2026-02-24 01:13:00.262+00
\N	257	cpu_usage_percent	4.428070175436972	percent	\N	2026-02-24 01:14:00.262+00
\N	257	cpu_usage_percent	4.262280701761753	percent	\N	2026-02-24 01:15:00.262+00
\N	257	cpu_usage_percent	3.9017543859428656	percent	\N	2026-02-24 01:16:00.262+00
\N	257	cpu_usage_percent	3.9105263157960195	percent	\N	2026-02-24 01:17:00.262+00
\N	133	cpu_usage_percent	0.6925438596507689	percent	cpu	2026-02-24 02:53:22.623+00
\N	133	cpu_usage_percent	0.5842105262880182	percent	cpu	2026-02-24 02:54:22.623+00
\N	133	cpu_usage_percent	0.600438596509207	percent	cpu	2026-02-24 02:55:22.623+00
\N	133	cpu_usage_percent	0.43157894732104296	percent	cpu	2026-02-24 02:56:22.623+00
\N	133	cpu_usage_percent	0.4263157895031071	percent	cpu	2026-02-24 02:57:22.623+00
\N	133	cpu_usage_percent	0.4263157893397107	percent	cpu	2026-02-24 02:58:22.623+00
\N	133	cpu_usage_percent	0.3179824561403706	percent	cpu	2026-02-24 02:59:22.623+00
\N	260	cpu_usage_percent	25.628837719273747	percent	\N	2026-02-24 01:05:00.331+00
\N	260	cpu_usage_percent	25.458442982431222	percent	\N	2026-02-24 01:06:00.331+00
\N	260	cpu_usage_percent	25.53278508773809	percent	\N	2026-02-24 01:07:00.331+00
\N	260	cpu_usage_percent	25.528289473701378	percent	\N	2026-02-24 01:08:00.331+00
\N	260	cpu_usage_percent	25.525219298239506	percent	\N	2026-02-24 01:09:00.331+00
\N	260	cpu_usage_percent	25.61820175441538	percent	\N	2026-02-24 01:10:00.331+00
\N	260	cpu_usage_percent	25.600109649117513	percent	\N	2026-02-24 01:11:00.331+00
\N	260	cpu_usage_percent	26.097478070224867	percent	\N	2026-02-24 01:12:00.331+00
\N	260	cpu_usage_percent	26.20032894735536	percent	\N	2026-02-24 01:13:00.331+00
\N	260	cpu_usage_percent	26.162938596517378	percent	\N	2026-02-24 01:14:00.331+00
\N	260	cpu_usage_percent	26.15427631583563	percent	\N	2026-02-24 01:15:00.331+00
\N	260	cpu_usage_percent	26.1173245614076	percent	\N	2026-02-24 01:16:00.331+00
\N	260	cpu_usage_percent	25.519188596487155	percent	\N	2026-02-24 01:17:00.331+00
\N	257	cpu_usage_percent	4.307894736830676	percent	\N	2026-02-24 01:45:01.851+00
\N	257	cpu_usage_percent	3.948245614035912	percent	\N	2026-02-24 01:46:01.851+00
\N	257	cpu_usage_percent	3.9578947368723476	percent	\N	2026-02-24 01:47:01.851+00
\N	257	cpu_usage_percent	4.076315789450831	percent	\N	2026-02-24 01:48:01.851+00
\N	257	cpu_usage_percent	4.608771929807418	percent	\N	2026-02-24 01:49:01.851+00
\N	257	cpu_usage_percent	4.981578947371702	percent	\N	2026-02-24 01:50:01.851+00
\N	257	cpu_usage_percent	5.314912280749965	percent	\N	2026-02-24 01:51:01.851+00
\N	133	cpu_usage_percent	0.4131578946927448	percent	\N	2026-02-24 01:15:00.394+00
\N	133	cpu_usage_percent	0.4070175438710919	percent	\N	2026-02-24 01:16:00.394+00
\N	133	cpu_usage_percent	1.298245614100452	percent	\N	2026-02-24 01:17:00.394+00
\N	133	cpu_usage_percent	4.094298245597699	percent	\N	2026-02-24 01:18:00.394+00
\N	133	cpu_usage_percent	6.629824561410061	percent	\N	2026-02-24 01:19:00.394+00
\N	133	cpu_usage_percent	9.157456140352522	percent	\N	2026-02-24 01:20:00.394+00
\N	133	cpu_usage_percent	9.17324561409228	percent	\N	2026-02-24 01:21:00.394+00
\N	133	cpu_usage_percent	7.574561403516952	percent	\N	2026-02-24 01:22:00.394+00
\N	133	cpu_usage_percent	4.8596491227580145	percent	\N	2026-02-24 01:23:00.394+00
\N	133	cpu_usage_percent	2.293421052633221	percent	\N	2026-02-24 01:24:00.394+00
\N	133	cpu_usage_percent	0.4245614035773997	percent	\N	2026-02-24 01:25:00.394+00
\N	133	cpu_usage_percent	0.4254385964585623	percent	\N	2026-02-24 01:26:00.394+00
\N	133	cpu_usage_percent	0.42192982460716166	percent	\N	2026-02-24 01:27:00.394+00
\N	257	cpu_usage_percent	5.3719298245605955	percent	\N	2026-02-24 01:52:01.851+00
\N	257	cpu_usage_percent	4.979824561364296	percent	\N	2026-02-24 01:53:01.851+00
\N	257	cpu_usage_percent	4.59736842106571	percent	\N	2026-02-24 01:54:01.851+00
\N	257	cpu_usage_percent	4.256140350878852	percent	\N	2026-02-24 01:55:01.851+00
\N	257	cpu_usage_percent	3.674561403499794	percent	\N	2026-02-24 01:56:01.851+00
\N	257	cpu_usage_percent	3.9017543859632866	percent	\N	2026-02-24 01:57:01.851+00
\N	133	cpu_usage_percent	0.5412280701689127	percent	cpu	2026-02-24 03:00:22.623+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	\N	2026-02-24 01:15:00.46+00
\N	236	cpu_usage_percent	1.4385964912607534	percent	\N	2026-02-24 01:16:00.46+00
\N	236	cpu_usage_percent	1.4350877192459706	percent	\N	2026-02-24 01:17:00.46+00
\N	236	cpu_usage_percent	1.589473684138639	percent	\N	2026-02-24 01:18:00.46+00
\N	236	cpu_usage_percent	1.498245614041636	percent	\N	2026-02-24 01:19:00.46+00
\N	236	cpu_usage_percent	1.645614035068121	percent	\N	2026-02-24 01:20:00.46+00
\N	236	cpu_usage_percent	1.670175438518072	percent	\N	2026-02-24 01:21:00.46+00
\N	236	cpu_usage_percent	1.6666666666666714	percent	\N	2026-02-24 01:22:00.46+00
\N	236	cpu_usage_percent	1.487719298324052	percent	\N	2026-02-24 01:23:00.46+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	\N	2026-02-24 01:24:00.46+00
\N	236	cpu_usage_percent	1.4456140351269369	percent	\N	2026-02-24 01:25:00.46+00
\N	236	cpu_usage_percent	1.4631578947107045	percent	\N	2026-02-24 01:26:00.46+00
\N	236	cpu_usage_percent	1.4526315788297381	percent	\N	2026-02-24 01:27:00.46+00
\N	133	cpu_usage_percent	0.44122807011662246	percent	cpu	2026-02-24 03:08:27.295+00
\N	133	cpu_usage_percent	0.43903508775035505	percent	cpu	2026-02-24 03:09:27.295+00
\N	133	cpu_usage_percent	0.5043859648714459	percent	cpu	2026-02-24 03:10:27.295+00
\N	133	cpu_usage_percent	0.6508771930167683	percent	cpu	2026-02-24 03:11:27.295+00
\N	133	cpu_usage_percent	0.6570175438384211	percent	cpu	2026-02-24 03:12:27.295+00
\N	260	cpu_usage_percent	25.58267543859283	percent	\N	2026-02-24 01:45:01.915+00
\N	248	cpu_usage_percent	2.1741228069897716	percent	\N	2026-02-24 01:15:00.52+00
\N	248	cpu_usage_percent	2.1864035088781435	percent	\N	2026-02-24 01:16:00.52+00
\N	248	cpu_usage_percent	2.2184210527165504	percent	\N	2026-02-24 01:17:00.52+00
\N	248	cpu_usage_percent	2.221491228127377	percent	\N	2026-02-24 01:18:00.52+00
\N	248	cpu_usage_percent	2.218859649197981	percent	\N	2026-02-24 01:19:00.52+00
\N	248	cpu_usage_percent	2.54342105260055	percent	\N	2026-02-24 01:20:00.52+00
\N	248	cpu_usage_percent	2.6236842104576965	percent	\N	2026-02-24 01:21:00.52+00
\N	248	cpu_usage_percent	2.6078947367996363	percent	\N	2026-02-24 01:22:00.52+00
\N	248	cpu_usage_percent	2.5539473684406744	percent	\N	2026-02-24 01:23:00.52+00
\N	248	cpu_usage_percent	2.2184210525940102	percent	\N	2026-02-24 01:24:00.52+00
\N	248	cpu_usage_percent	2.219298245597699	percent	\N	2026-02-24 01:25:00.52+00
\N	248	cpu_usage_percent	2.1596491227759884	percent	\N	2026-02-24 01:26:00.52+00
\N	248	cpu_usage_percent	2.133771929840904	percent	\N	2026-02-24 01:27:00.52+00
\N	260	cpu_usage_percent	25.59978070173601	percent	\N	2026-02-24 01:46:01.915+00
\N	260	cpu_usage_percent	25.591447368425563	percent	\N	2026-02-24 01:47:01.915+00
\N	260	cpu_usage_percent	25.56359649128322	percent	\N	2026-02-24 01:48:01.915+00
\N	260	cpu_usage_percent	25.601096491221128	percent	\N	2026-02-24 01:49:01.915+00
\N	260	cpu_usage_percent	25.592324561449672	percent	\N	2026-02-24 01:50:01.915+00
\N	260	cpu_usage_percent	25.55493421054021	percent	\N	2026-02-24 01:51:01.915+00
\N	260	cpu_usage_percent	25.594407894746652	percent	\N	2026-02-24 01:52:01.915+00
\N	252	cpu_usage_percent	23.00482456143456	percent	\N	2026-02-24 01:15:00.574+00
\N	252	cpu_usage_percent	22.828070175396945	percent	\N	2026-02-24 01:16:00.574+00
\N	252	cpu_usage_percent	23.004385964891867	percent	\N	2026-02-24 01:17:00.574+00
\N	252	cpu_usage_percent	23.171929824472357	percent	\N	2026-02-24 01:18:00.574+00
\N	252	cpu_usage_percent	23.5315789473284	percent	\N	2026-02-24 01:19:00.574+00
\N	252	cpu_usage_percent	23.694736842115077	percent	\N	2026-02-24 01:20:00.574+00
\N	252	cpu_usage_percent	23.82499999999837	percent	\N	2026-02-24 01:21:00.574+00
\N	252	cpu_usage_percent	23.747807017531613	percent	\N	2026-02-24 01:22:00.574+00
\N	252	cpu_usage_percent	23.34868421044871	percent	\N	2026-02-24 01:23:00.574+00
\N	252	cpu_usage_percent	23.029824561406784	percent	\N	2026-02-24 01:24:00.574+00
\N	252	cpu_usage_percent	23.13026315792007	percent	\N	2026-02-24 01:25:00.574+00
\N	252	cpu_usage_percent	23.089912280669083	percent	\N	2026-02-24 01:26:00.574+00
\N	260	cpu_usage_percent	25.94276315786901	percent	\N	2026-02-24 01:53:01.915+00
\N	252	cpu_usage_percent	23.06184210524519	percent	\N	2026-02-24 01:27:00.574+00
\N	260	cpu_usage_percent	26.065679824576122	percent	\N	2026-02-24 01:54:01.915+00
\N	260	cpu_usage_percent	25.99002192981476	percent	\N	2026-02-24 01:55:01.915+00
\N	260	cpu_usage_percent	26.042324561378607	percent	\N	2026-02-24 01:56:01.915+00
\N	260	cpu_usage_percent	25.87642543857281	percent	\N	2026-02-24 01:57:01.915+00
\N	133	cpu_usage_percent	0.6706140350893719	percent	cpu	2026-02-24 03:13:27.295+00
\N	133	cpu_usage_percent	0.6649122807082932	percent	cpu	2026-02-24 03:14:27.295+00
\N	133	cpu_usage_percent	0.45789473686008364	percent	cpu	2026-02-24 03:15:27.295+00
\N	257	cpu_usage_percent	4.262280701761753	percent	\N	2026-02-24 01:15:00.627+00
\N	257	cpu_usage_percent	3.9017543859428656	percent	\N	2026-02-24 01:16:00.627+00
\N	257	cpu_usage_percent	3.9105263157960195	percent	\N	2026-02-24 01:17:00.627+00
\N	257	cpu_usage_percent	4.1333333333431455	percent	\N	2026-02-24 01:18:00.627+00
\N	257	cpu_usage_percent	4.534210526310886	percent	\N	2026-02-24 01:19:00.627+00
\N	257	cpu_usage_percent	4.944736842115077	percent	\N	2026-02-24 01:20:00.627+00
\N	257	cpu_usage_percent	5.32894736844149	percent	\N	2026-02-24 01:21:00.627+00
\N	257	cpu_usage_percent	5.423684210512434	percent	\N	2026-02-24 01:22:00.627+00
\N	257	cpu_usage_percent	5.102631578981686	percent	\N	2026-02-24 01:23:00.627+00
\N	257	cpu_usage_percent	4.7263157894434755	percent	\N	2026-02-24 01:24:00.627+00
\N	257	cpu_usage_percent	4.293859649139151	percent	\N	2026-02-24 01:25:00.627+00
\N	257	cpu_usage_percent	3.942105263173417	percent	\N	2026-02-24 01:26:00.627+00
\N	257	cpu_usage_percent	3.914035087708683	percent	\N	2026-02-24 01:27:00.627+00
\N	133	cpu_usage_percent	0.43815789474666644	percent	cpu	2026-02-24 03:16:27.295+00
\N	133	cpu_usage_percent	0.43991228071320165	percent	cpu	2026-02-24 03:17:27.295+00
\N	133	cpu_usage_percent	0.43070175439903835	percent	cpu	2026-02-24 03:18:27.295+00
\N	133	cpu_usage_percent	0.7491228069799689	percent	cpu	2026-02-24 03:19:27.295+00
\N	133	cpu_usage_percent	0.4241228070142853	percent	\N	2026-02-24 01:55:01.981+00
\N	133	cpu_usage_percent	0.31622807017382115	percent	\N	2026-02-24 01:56:01.981+00
\N	133	cpu_usage_percent	0.41359649121500297	percent	\N	2026-02-24 01:57:01.981+00
\N	260	cpu_usage_percent	26.15427631583563	percent	\N	2026-02-24 01:15:00.69+00
\N	260	cpu_usage_percent	26.1173245614076	percent	\N	2026-02-24 01:16:00.69+00
\N	260	cpu_usage_percent	25.519188596487155	percent	\N	2026-02-24 01:17:00.69+00
\N	260	cpu_usage_percent	25.51896929823623	percent	\N	2026-02-24 01:18:00.69+00
\N	260	cpu_usage_percent	25.55109649122562	percent	\N	2026-02-24 01:19:00.69+00
\N	260	cpu_usage_percent	25.554714912299502	percent	\N	2026-02-24 01:20:00.69+00
\N	260	cpu_usage_percent	25.55537280697058	percent	\N	2026-02-24 01:21:00.69+00
\N	260	cpu_usage_percent	25.507346491202753	percent	\N	2026-02-24 01:22:00.69+00
\N	260	cpu_usage_percent	25.525219298249695	percent	\N	2026-02-24 01:23:00.69+00
\N	260	cpu_usage_percent	25.53212719295469	percent	\N	2026-02-24 01:24:00.69+00
\N	260	cpu_usage_percent	25.48223684205911	percent	\N	2026-02-24 01:25:00.69+00
\N	260	cpu_usage_percent	25.523135964932308	percent	\N	2026-02-24 01:26:00.69+00
\N	260	cpu_usage_percent	25.5178728070633	percent	\N	2026-02-24 01:27:00.69+00
\N	133	cpu_usage_percent	0.42850877191023073	percent	\N	2026-02-24 01:58:01.981+00
\N	133	cpu_usage_percent	0.5307017544104866	percent	\N	2026-02-24 01:59:01.981+00
\N	133	cpu_usage_percent	0.5346491227433035	percent	\N	2026-02-24 02:00:01.981+00
\N	133	cpu_usage_percent	0.4460526315756823	percent	\N	2026-02-24 02:01:01.981+00
\N	133	cpu_usage_percent	0.4802631577803709	percent	\N	2026-02-24 02:02:01.981+00
\N	133	cpu_usage_percent	1.58026315782449	percent	\N	2026-02-24 02:03:01.981+00
\N	133	cpu_usage_percent	1.9666666667418298	percent	\N	2026-02-24 02:04:01.981+00
\N	133	cpu_usage_percent	0.4245614035773997	percent	\N	2026-02-24 01:25:00.765+00
\N	133	cpu_usage_percent	0.4254385964585623	percent	\N	2026-02-24 01:26:00.765+00
\N	133	cpu_usage_percent	0.42192982460716166	percent	\N	2026-02-24 01:27:00.765+00
\N	133	cpu_usage_percent	0.5166666666372635	percent	\N	2026-02-24 01:28:00.765+00
\N	133	cpu_usage_percent	0.5421052630500753	percent	\N	2026-02-24 01:29:00.765+00
\N	133	cpu_usage_percent	0.42850877186938874	percent	\N	2026-02-24 01:30:00.765+00
\N	133	cpu_usage_percent	0.5245614035479917	percent	\N	2026-02-24 01:31:00.765+00
\N	133	cpu_usage_percent	0.5385964911986747	percent	\N	2026-02-24 01:32:00.765+00
\N	133	cpu_usage_percent	0.42850877195107273	percent	\N	2026-02-24 01:33:00.765+00
\N	133	cpu_usage_percent	0.4241228070142995	percent	\N	2026-02-24 01:34:00.765+00
\N	133	cpu_usage_percent	0.3412280701868866	percent	\N	2026-02-24 01:35:00.765+00
\N	133	cpu_usage_percent	0.4179824561518046	percent	\N	2026-02-24 01:36:00.765+00
\N	133	cpu_usage_percent	0.42149122804404726	percent	\N	2026-02-24 01:37:00.765+00
\N	133	cpu_usage_percent	1.9640350876898935	percent	\N	2026-02-24 02:05:01.981+00
\N	133	cpu_usage_percent	1.974999999970592	percent	\N	2026-02-24 02:06:01.981+00
\N	133	cpu_usage_percent	2.046491228076718	percent	\N	2026-02-24 02:07:01.981+00
\N	133	cpu_usage_percent	1.0372807017298982	percent	cpu	2026-02-24 03:20:27.295+00
\N	133	cpu_usage_percent	0.4561403508118502	percent	cpu	2026-02-24 03:28:30.371+00
\N	133	cpu_usage_percent	0.46052631578947967	percent	cpu	2026-02-24 03:29:30.371+00
\N	133	cpu_usage_percent	0.5285087718808228	percent	cpu	2026-02-24 03:30:30.371+00
\N	236	cpu_usage_percent	1.4456140351269369	percent	\N	2026-02-24 01:25:00.857+00
\N	236	cpu_usage_percent	1.4631578947107045	percent	\N	2026-02-24 01:26:00.857+00
\N	236	cpu_usage_percent	1.4526315788297381	percent	\N	2026-02-24 01:27:00.857+00
\N	236	cpu_usage_percent	1.5614035088373015	percent	\N	2026-02-24 01:28:00.857+00
\N	236	cpu_usage_percent	1.582456140435852	percent	\N	2026-02-24 01:29:00.857+00
\N	236	cpu_usage_percent	1.582456140435852	percent	\N	2026-02-24 01:30:00.857+00
\N	236	cpu_usage_percent	1.6140350877519865	percent	\N	2026-02-24 01:31:00.857+00
\N	236	cpu_usage_percent	1.6385964912019375	percent	\N	2026-02-24 01:32:00.857+00
\N	236	cpu_usage_percent	1.512280701774003	percent	\N	2026-02-24 01:33:00.857+00
\N	236	cpu_usage_percent	1.480701754294472	percent	\N	2026-02-24 01:34:00.857+00
\N	236	cpu_usage_percent	1.3017543859518526	percent	\N	2026-02-24 01:35:00.857+00
\N	236	cpu_usage_percent	1.3894736843608513	percent	\N	2026-02-24 01:36:00.857+00
\N	236	cpu_usage_percent	1.4070175437812367	percent	\N	2026-02-24 01:37:00.857+00
\N	133	cpu_usage_percent	0.5872807017805286	percent	cpu	2026-02-24 03:31:30.371+00
\N	133	cpu_usage_percent	0.6513157894573567	percent	cpu	2026-02-24 03:32:30.371+00
\N	236	cpu_usage_percent	1.5017543860564189	percent	\N	2026-02-24 01:55:02.054+00
\N	236	cpu_usage_percent	1.3192982455356201	percent	\N	2026-02-24 01:56:02.054+00
\N	236	cpu_usage_percent	1.4245614035283864	percent	\N	2026-02-24 01:57:02.054+00
\N	236	cpu_usage_percent	1.4456140349635547	percent	\N	2026-02-24 01:58:02.054+00
\N	248	cpu_usage_percent	2.219298245597699	percent	\N	2026-02-24 01:25:00.934+00
\N	248	cpu_usage_percent	2.1596491227759884	percent	\N	2026-02-24 01:26:00.934+00
\N	248	cpu_usage_percent	2.133771929840904	percent	\N	2026-02-24 01:27:00.934+00
\N	248	cpu_usage_percent	2.2021929824545197	percent	\N	2026-02-24 01:28:00.934+00
\N	248	cpu_usage_percent	2.2328947368077934	percent	\N	2026-02-24 01:29:00.934+00
\N	248	cpu_usage_percent	2.2197368420382873	percent	\N	2026-02-24 01:30:00.934+00
\N	248	cpu_usage_percent	2.3732456140498073	percent	\N	2026-02-24 01:31:00.934+00
\N	248	cpu_usage_percent	2.425438596523918	percent	\N	2026-02-24 01:32:00.934+00
\N	248	cpu_usage_percent	2.4302631579421217	percent	\N	2026-02-24 01:33:00.934+00
\N	248	cpu_usage_percent	2.454824561432929	percent	\N	2026-02-24 01:34:00.934+00
\N	248	cpu_usage_percent	2.3644736842170744	percent	\N	2026-02-24 01:35:00.934+00
\N	248	cpu_usage_percent	2.365350877139065	percent	\N	2026-02-24 01:36:00.934+00
\N	248	cpu_usage_percent	2.297807017447468	percent	\N	2026-02-24 01:37:00.934+00
\N	236	cpu_usage_percent	1.589473684138639	percent	\N	2026-02-24 01:59:02.054+00
\N	236	cpu_usage_percent	1.62105263161817	percent	\N	2026-02-24 02:00:02.054+00
\N	236	cpu_usage_percent	1.6350877191871547	percent	\N	2026-02-24 02:01:02.054+00
\N	236	cpu_usage_percent	1.5192982456401865	percent	\N	2026-02-24 02:02:02.054+00
\N	236	cpu_usage_percent	1.5403508772387369	percent	\N	2026-02-24 02:03:02.054+00
\N	236	cpu_usage_percent	1.378947368479885	percent	\N	2026-02-24 02:04:02.054+00
\N	236	cpu_usage_percent	1.3578947367179381	percent	\N	2026-02-24 02:05:02.054+00
\N	252	cpu_usage_percent	23.13026315792007	percent	\N	2026-02-24 01:25:01.006+00
\N	252	cpu_usage_percent	23.089912280669083	percent	\N	2026-02-24 01:26:01.006+00
\N	252	cpu_usage_percent	23.06184210524519	percent	\N	2026-02-24 01:27:01.006+00
\N	252	cpu_usage_percent	23.23289473684048	percent	\N	2026-02-24 01:28:01.006+00
\N	252	cpu_usage_percent	23.301754385996773	percent	\N	2026-02-24 01:29:01.006+00
\N	252	cpu_usage_percent	23.399122806997127	percent	\N	2026-02-24 01:30:01.006+00
\N	252	cpu_usage_percent	23.76535087719708	percent	\N	2026-02-24 01:31:01.006+00
\N	252	cpu_usage_percent	23.84868421054675	percent	\N	2026-02-24 01:32:01.006+00
\N	252	cpu_usage_percent	23.83684210530319	percent	\N	2026-02-24 01:33:01.006+00
\N	252	cpu_usage_percent	23.851315789476146	percent	\N	2026-02-24 01:34:01.006+00
\N	252	cpu_usage_percent	23.448245614060426	percent	\N	2026-02-24 01:35:01.006+00
\N	252	cpu_usage_percent	23.60482456138064	percent	\N	2026-02-24 01:36:01.006+00
\N	252	cpu_usage_percent	23.46622807014603	percent	\N	2026-02-24 01:37:01.006+00
\N	236	cpu_usage_percent	1.3403508771341706	percent	\N	2026-02-24 02:06:02.054+00
\N	236	cpu_usage_percent	1.4210526315136036	percent	\N	2026-02-24 02:07:02.054+00
\N	133	cpu_usage_percent	0.6416666667026192	percent	cpu	2026-02-24 03:33:30.371+00
\N	133	cpu_usage_percent	0.658333333241842	percent	cpu	2026-02-24 03:34:30.371+00
\N	133	cpu_usage_percent	0.5478070175536658	percent	cpu	2026-02-24 03:35:30.371+00
\N	133	cpu_usage_percent	0.3236842105214208	percent	cpu	2026-02-24 03:36:30.371+00
\N	133	cpu_usage_percent	0.4429824562057263	percent	cpu	2026-02-24 03:37:30.371+00
\N	257	cpu_usage_percent	4.293859649139151	percent	\N	2026-02-24 01:25:01.064+00
\N	257	cpu_usage_percent	3.942105263173417	percent	\N	2026-02-24 01:26:01.064+00
\N	257	cpu_usage_percent	3.914035087708683	percent	\N	2026-02-24 01:27:01.064+00
\N	257	cpu_usage_percent	4.142982456138739	percent	\N	2026-02-24 01:28:01.064+00
\N	257	cpu_usage_percent	4.528947368431673	percent	\N	2026-02-24 01:29:01.064+00
\N	257	cpu_usage_percent	4.59736842106571	percent	\N	2026-02-24 01:30:01.064+00
\N	257	cpu_usage_percent	5.273684210536132	percent	\N	2026-02-24 01:31:01.064+00
\N	257	cpu_usage_percent	5.363157894727863	percent	\N	2026-02-24 01:32:01.064+00
\N	257	cpu_usage_percent	5.048245614039189	percent	\N	2026-02-24 01:33:01.064+00
\N	257	cpu_usage_percent	4.705263157885767	percent	\N	2026-02-24 01:34:01.064+00
\N	257	cpu_usage_percent	4.108771929811496	percent	\N	2026-02-24 01:35:01.064+00
\N	257	cpu_usage_percent	3.9245614035079655	percent	\N	2026-02-24 01:36:01.064+00
\N	257	cpu_usage_percent	3.9315789473537137	percent	\N	2026-02-24 01:37:01.064+00
\N	133	cpu_usage_percent	0.4421052632020235	percent	cpu	2026-02-24 03:38:30.371+00
\N	236	cpu_usage_percent	1.498245614041636	percent	cpu	2026-02-24 02:44:30.81+00
\N	248	cpu_usage_percent	2.348245614036742	percent	\N	2026-02-24 01:55:02.116+00
\N	248	cpu_usage_percent	2.199999999965698	percent	\N	2026-02-24 01:56:02.116+00
\N	248	cpu_usage_percent	2.301315789421409	percent	\N	2026-02-24 01:57:02.116+00
\N	248	cpu_usage_percent	2.4337719298343785	percent	\N	2026-02-24 01:58:02.116+00
\N	248	cpu_usage_percent	2.4342105262341107	percent	\N	2026-02-24 01:59:02.116+00
\N	260	cpu_usage_percent	25.48223684205911	percent	\N	2026-02-24 01:25:01.121+00
\N	260	cpu_usage_percent	25.523135964932308	percent	\N	2026-02-24 01:26:01.121+00
\N	260	cpu_usage_percent	25.5178728070633	percent	\N	2026-02-24 01:27:01.121+00
\N	260	cpu_usage_percent	25.577850877133756	percent	\N	2026-02-24 01:28:01.121+00
\N	260	cpu_usage_percent	25.584649122800087	percent	\N	2026-02-24 01:29:01.121+00
\N	260	cpu_usage_percent	25.64057017544799	percent	\N	2026-02-24 01:30:01.121+00
\N	260	cpu_usage_percent	25.595723684252206	percent	\N	2026-02-24 01:31:01.121+00
\N	260	cpu_usage_percent	25.622149122809475	percent	\N	2026-02-24 01:32:01.121+00
\N	260	cpu_usage_percent	25.647807017554896	percent	\N	2026-02-24 01:33:01.121+00
\N	260	cpu_usage_percent	25.563815789483087	percent	\N	2026-02-24 01:34:01.121+00
\N	260	cpu_usage_percent	25.598245614030603	percent	\N	2026-02-24 01:35:01.121+00
\N	260	cpu_usage_percent	25.605372806996712	percent	\N	2026-02-24 01:36:01.121+00
\N	260	cpu_usage_percent	25.585526315793572	percent	\N	2026-02-24 01:37:01.121+00
\N	248	cpu_usage_percent	2.596052631637775	percent	\N	2026-02-24 02:00:02.116+00
\N	248	cpu_usage_percent	3.1539473683458965	percent	\N	2026-02-24 02:01:02.116+00
\N	248	cpu_usage_percent	3.3214912280897835	percent	\N	2026-02-24 02:02:02.116+00
\N	248	cpu_usage_percent	3.4596491226795933	percent	\N	2026-02-24 02:03:02.116+00
\N	248	cpu_usage_percent	3.663157894676388	percent	\N	2026-02-24 02:04:02.116+00
\N	248	cpu_usage_percent	3.6890350875706304	percent	\N	2026-02-24 02:05:02.116+00
\N	248	cpu_usage_percent	3.3460526315397487	percent	\N	2026-02-24 02:06:02.116+00
\N	133	cpu_usage_percent	0.3315789473504651	percent	\N	2026-02-24 01:35:01.177+00
\N	133	cpu_usage_percent	0.4241228070142995	percent	\N	2026-02-24 01:36:01.177+00
\N	133	cpu_usage_percent	0.41929824559608164	percent	\N	2026-02-24 01:37:01.177+00
\N	133	cpu_usage_percent	0.5232456140220307	percent	\N	2026-02-24 01:38:01.177+00
\N	133	cpu_usage_percent	0.5280701754810906	percent	\N	2026-02-24 01:39:01.177+00
\N	133	cpu_usage_percent	0.4469298245793851	percent	\N	2026-02-24 01:40:01.177+00
\N	133	cpu_usage_percent	0.5285087719216648	percent	\N	2026-02-24 01:41:01.177+00
\N	133	cpu_usage_percent	0.5342105263027292	percent	\N	2026-02-24 01:42:01.177+00
\N	133	cpu_usage_percent	0.4434210526054585	percent	\N	2026-02-24 01:43:01.177+00
\N	133	cpu_usage_percent	0.4333333332875924	percent	\N	2026-02-24 01:44:01.177+00
\N	133	cpu_usage_percent	0.4359649122986866	percent	\N	2026-02-24 01:45:01.177+00
\N	133	cpu_usage_percent	0.42236842104773586	percent	\N	2026-02-24 01:46:01.177+00
\N	133	cpu_usage_percent	0.43815789474666644	percent	\N	2026-02-24 01:47:01.177+00
\N	248	cpu_usage_percent	3.300438596491233	percent	\N	2026-02-24 02:07:02.116+00
\N	236	cpu_usage_percent	1.5122807016106066	percent	cpu	2026-02-24 02:45:30.81+00
\N	236	cpu_usage_percent	1.5298245613577706	percent	cpu	2026-02-24 02:46:30.81+00
\N	236	cpu_usage_percent	1.522807017491587	percent	cpu	2026-02-24 02:47:30.81+00
\N	236	cpu_usage_percent	1.5157894736253894	percent	cpu	2026-02-24 02:48:30.81+00
\N	236	cpu_usage_percent	1.9684210527492212	percent	cpu	2026-02-24 02:49:30.81+00
\N	236	cpu_usage_percent	1.9999999999019735	percent	cpu	2026-02-24 02:50:30.81+00
\N	236	cpu_usage_percent	1.3017543859518526	percent	\N	2026-02-24 01:35:01.262+00
\N	236	cpu_usage_percent	1.3894736843608513	percent	\N	2026-02-24 01:36:01.262+00
\N	236	cpu_usage_percent	1.4070175437812367	percent	\N	2026-02-24 01:37:01.262+00
\N	236	cpu_usage_percent	1.5403508772387369	percent	\N	2026-02-24 01:38:01.262+00
\N	236	cpu_usage_percent	1.5824561402724555	percent	\N	2026-02-24 01:39:01.262+00
\N	236	cpu_usage_percent	1.470175438576888	percent	\N	2026-02-24 01:40:01.262+00
\N	236	cpu_usage_percent	1.603508771871006	percent	\N	2026-02-24 01:41:01.262+00
\N	236	cpu_usage_percent	1.6350877193505369	percent	\N	2026-02-24 01:42:01.262+00
\N	236	cpu_usage_percent	1.5017543860564189	percent	\N	2026-02-24 01:43:01.262+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	\N	2026-02-24 01:44:01.262+00
\N	236	cpu_usage_percent	1.4771929826064678	percent	\N	2026-02-24 01:45:01.262+00
\N	236	cpu_usage_percent	1.5017543858930225	percent	\N	2026-02-24 01:46:01.262+00
\N	236	cpu_usage_percent	1.5964912281682189	percent	\N	2026-02-24 01:47:01.262+00
\N	252	cpu_usage_percent	24.07807017545821	percent	\N	2026-02-24 01:55:02.187+00
\N	252	cpu_usage_percent	23.38333333331863	percent	\N	2026-02-24 01:56:02.187+00
\N	252	cpu_usage_percent	23.6956140351392	percent	\N	2026-02-24 01:57:02.187+00
\N	252	cpu_usage_percent	23.984210526309255	percent	\N	2026-02-24 01:58:02.187+00
\N	252	cpu_usage_percent	24.204385964906578	percent	\N	2026-02-24 01:59:02.187+00
\N	252	cpu_usage_percent	24.593421052630774	percent	\N	2026-02-24 02:00:02.187+00
\N	248	cpu_usage_percent	2.3644736842170744	percent	\N	2026-02-24 01:35:01.332+00
\N	248	cpu_usage_percent	2.365350877139065	percent	\N	2026-02-24 01:36:01.332+00
\N	248	cpu_usage_percent	2.297807017447468	percent	\N	2026-02-24 01:37:01.332+00
\N	252	cpu_usage_percent	25.135087719281103	percent	\N	2026-02-24 02:01:02.187+00
\N	248	cpu_usage_percent	2.2942982456369236	percent	\N	2026-02-24 01:38:01.332+00
\N	248	cpu_usage_percent	2.2938596490738092	percent	\N	2026-02-24 01:39:01.332+00
\N	248	cpu_usage_percent	2.1903508772109603	percent	\N	2026-02-24 01:40:01.332+00
\N	248	cpu_usage_percent	2.2609649123133835	percent	\N	2026-02-24 01:41:01.332+00
\N	248	cpu_usage_percent	2.365350877179935	percent	\N	2026-02-24 01:42:01.332+00
\N	248	cpu_usage_percent	2.365350877220763	percent	\N	2026-02-24 01:43:01.332+00
\N	248	cpu_usage_percent	2.5464912281339025	percent	\N	2026-02-24 01:44:01.332+00
\N	248	cpu_usage_percent	2.8995614035234922	percent	\N	2026-02-24 01:45:01.332+00
\N	248	cpu_usage_percent	2.981140350906614	percent	\N	2026-02-24 01:46:01.332+00
\N	248	cpu_usage_percent	2.9092105262373735	percent	\N	2026-02-24 01:47:01.332+00
\N	252	cpu_usage_percent	24.346052631613276	percent	\N	2026-02-24 02:02:02.187+00
\N	252	cpu_usage_percent	24.414473684247298	percent	\N	2026-02-24 02:03:02.187+00
\N	252	cpu_usage_percent	24.23421052631744	percent	\N	2026-02-24 02:04:02.187+00
\N	252	cpu_usage_percent	23.84210526322326	percent	\N	2026-02-24 02:05:02.187+00
\N	252	cpu_usage_percent	23.481140350922942	percent	\N	2026-02-24 02:06:02.187+00
\N	252	cpu_usage_percent	23.93991228068461	percent	\N	2026-02-24 02:07:02.187+00
\N	236	cpu_usage_percent	2.375438596497773	percent	cpu	2026-02-24 02:51:30.81+00
\N	252	cpu_usage_percent	23.448245614060426	percent	\N	2026-02-24 01:35:01.385+00
\N	252	cpu_usage_percent	23.60482456138064	percent	\N	2026-02-24 01:36:01.385+00
\N	252	cpu_usage_percent	23.46622807014603	percent	\N	2026-02-24 01:37:01.385+00
\N	252	cpu_usage_percent	23.503947368406358	percent	\N	2026-02-24 01:38:01.385+00
\N	252	cpu_usage_percent	23.475438596460194	percent	\N	2026-02-24 01:39:01.385+00
\N	252	cpu_usage_percent	23.2517543860115	percent	\N	2026-02-24 01:40:01.385+00
\N	252	cpu_usage_percent	23.352192982483928	percent	\N	2026-02-24 01:41:01.385+00
\N	252	cpu_usage_percent	24.19210526320201	percent	\N	2026-02-24 01:42:01.385+00
\N	252	cpu_usage_percent	26.839912280689504	percent	\N	2026-02-24 01:43:01.385+00
\N	252	cpu_usage_percent	29.65745614036885	percent	\N	2026-02-24 01:44:01.385+00
\N	252	cpu_usage_percent	32.42850877189389	percent	\N	2026-02-24 01:45:01.385+00
\N	252	cpu_usage_percent	34.61929824562712	percent	\N	2026-02-24 01:46:01.385+00
\N	252	cpu_usage_percent	33.38903508774055	percent	\N	2026-02-24 01:47:01.385+00
\N	236	cpu_usage_percent	2.403508771962521	percent	cpu	2026-02-24 02:52:30.81+00
\N	236	cpu_usage_percent	2.2736842105197894	percent	cpu	2026-02-24 02:53:30.81+00
\N	236	cpu_usage_percent	1.8912280700578066	percent	cpu	2026-02-24 02:54:30.81+00
\N	236	cpu_usage_percent	1.8842105263550195	percent	cpu	2026-02-24 02:55:30.81+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	cpu	2026-02-24 02:56:30.81+00
\N	133	cpu_usage_percent	0.44078947363520626	percent	cpu	2026-02-24 03:39:30.371+00
\N	257	cpu_usage_percent	4.256140350878852	percent	\N	2026-02-24 01:55:02.247+00
\N	257	cpu_usage_percent	3.9605263158221504	percent	\N	2026-02-24 01:35:01.441+00
\N	257	cpu_usage_percent	3.926315789474515	percent	\N	2026-02-24 01:36:01.441+00
\N	257	cpu_usage_percent	3.922807017541416	percent	\N	2026-02-24 01:37:01.441+00
\N	257	cpu_usage_percent	4.254385964912288	percent	\N	2026-02-24 01:38:01.441+00
\N	257	cpu_usage_percent	4.663157894749929	percent	\N	2026-02-24 01:39:01.441+00
\N	257	cpu_usage_percent	4.831578947374965	percent	\N	2026-02-24 01:40:01.441+00
\N	257	cpu_usage_percent	5.410526315804191	percent	\N	2026-02-24 01:41:01.441+00
\N	257	cpu_usage_percent	5.450877192973479	percent	\N	2026-02-24 01:42:01.441+00
\N	257	cpu_usage_percent	5.0657894736842195	percent	\N	2026-02-24 01:43:01.441+00
\N	257	cpu_usage_percent	4.692105263157089	percent	\N	2026-02-24 01:44:01.441+00
\N	257	cpu_usage_percent	4.307894736830676	percent	\N	2026-02-24 01:45:01.441+00
\N	257	cpu_usage_percent	3.948245614035912	percent	\N	2026-02-24 01:46:01.441+00
\N	257	cpu_usage_percent	3.9578947368723476	percent	\N	2026-02-24 01:47:01.441+00
\N	257	cpu_usage_percent	3.674561403499794	percent	\N	2026-02-24 01:56:02.247+00
\N	257	cpu_usage_percent	3.9017543859632866	percent	\N	2026-02-24 01:57:02.247+00
\N	257	cpu_usage_percent	4.112280701744581	percent	\N	2026-02-24 01:58:02.247+00
\N	257	cpu_usage_percent	4.719298245618134	percent	\N	2026-02-24 01:59:02.247+00
\N	257	cpu_usage_percent	5.076315789483502	percent	\N	2026-02-24 02:00:02.247+00
\N	257	cpu_usage_percent	5.422807017549587	percent	\N	2026-02-24 02:01:02.247+00
\N	257	cpu_usage_percent	5.362280701744595	percent	\N	2026-02-24 02:02:02.247+00
\N	260	cpu_usage_percent	25.598245614030603	percent	\N	2026-02-24 01:35:01.513+00
\N	260	cpu_usage_percent	25.605372806996712	percent	\N	2026-02-24 01:36:01.513+00
\N	260	cpu_usage_percent	25.585526315793572	percent	\N	2026-02-24 01:37:01.513+00
\N	260	cpu_usage_percent	25.56063596489065	percent	\N	2026-02-24 01:38:01.513+00
\N	260	cpu_usage_percent	25.56557017543942	percent	\N	2026-02-24 01:39:01.513+00
\N	260	cpu_usage_percent	25.63486842108736	percent	\N	2026-02-24 01:40:01.513+00
\N	260	cpu_usage_percent	25.58333333332517	percent	\N	2026-02-24 01:41:01.513+00
\N	260	cpu_usage_percent	25.6209429824345	percent	\N	2026-02-24 01:42:01.513+00
\N	260	cpu_usage_percent	25.61063596491678	percent	\N	2026-02-24 01:43:01.513+00
\N	260	cpu_usage_percent	25.683771929879313	percent	\N	2026-02-24 01:44:01.513+00
\N	260	cpu_usage_percent	25.58267543859283	percent	\N	2026-02-24 01:45:01.513+00
\N	260	cpu_usage_percent	25.59978070173601	percent	\N	2026-02-24 01:46:01.513+00
\N	260	cpu_usage_percent	25.591447368425563	percent	\N	2026-02-24 01:47:01.513+00
\N	257	cpu_usage_percent	5.108771929803325	percent	\N	2026-02-24 02:03:02.247+00
\N	257	cpu_usage_percent	4.4394736842195215	percent	\N	2026-02-24 02:04:02.247+00
\N	257	cpu_usage_percent	4.0245614035193995	percent	\N	2026-02-24 02:05:02.247+00
\N	257	cpu_usage_percent	3.7938596491228225	percent	\N	2026-02-24 02:06:02.247+00
\N	257	cpu_usage_percent	3.8210526315634326	percent	\N	2026-02-24 02:07:02.247+00
\N	133	cpu_usage_percent	0.43114035088046876	percent	cpu	2026-02-24 03:40:30.371+00
\N	133	cpu_usage_percent	0.44868421054593455	percent	cpu	2026-02-24 03:48:33.445+00
\N	133	cpu_usage_percent	0.436842105179835	percent	cpu	2026-02-24 03:49:33.445+00
\N	133	cpu_usage_percent	0.5228070175814565	percent	cpu	2026-02-24 03:50:33.445+00
\N	133	cpu_usage_percent	0.6548245614721395	percent	cpu	2026-02-24 03:51:33.445+00
\N	133	cpu_usage_percent	0.6508771929759263	percent	cpu	2026-02-24 03:52:33.445+00
\N	133	cpu_usage_percent	0.6561403507938763	percent	cpu	2026-02-24 03:53:33.445+00
\N	260	cpu_usage_percent	25.99002192981476	percent	\N	2026-02-24 01:55:02.313+00
\N	260	cpu_usage_percent	26.042324561378607	percent	\N	2026-02-24 01:56:02.313+00
\N	260	cpu_usage_percent	25.87642543857281	percent	\N	2026-02-24 01:57:02.313+00
\N	260	cpu_usage_percent	25.543749999937106	percent	\N	2026-02-24 01:58:02.313+00
\N	260	cpu_usage_percent	25.500219298226426	percent	\N	2026-02-24 01:59:02.313+00
\N	260	cpu_usage_percent	25.51688596487797	percent	\N	2026-02-24 02:00:02.313+00
\N	260	cpu_usage_percent	25.52335526318322	percent	\N	2026-02-24 02:01:02.313+00
\N	260	cpu_usage_percent	25.517105263179957	percent	\N	2026-02-24 02:02:02.313+00
\N	260	cpu_usage_percent	25.5883771929943	percent	\N	2026-02-24 02:03:02.313+00
\N	260	cpu_usage_percent	25.575986842108136	percent	\N	2026-02-24 02:04:02.313+00
\N	260	cpu_usage_percent	25.552192982408755	percent	\N	2026-02-24 02:05:02.313+00
\N	260	cpu_usage_percent	25.582894736864176	percent	\N	2026-02-24 02:06:02.313+00
\N	260	cpu_usage_percent	25.549561403520215	percent	\N	2026-02-24 02:07:02.313+00
\N	133	cpu_usage_percent	0.6570175438384211	percent	cpu	2026-02-24 03:54:33.445+00
\N	133	cpu_usage_percent	0.5491228071204972	percent	cpu	2026-02-24 03:55:33.445+00
\N	133	cpu_usage_percent	0.4368421052615332	percent	cpu	2026-02-24 03:56:33.445+00
\N	133	cpu_usage_percent	0.3236842105214208	percent	cpu	2026-02-24 03:57:33.445+00
\N	236	cpu_usage_percent	1.512280701774003	percent	cpu	2026-02-24 02:48:22.907+00
\N	133	cpu_usage_percent	0.4228070175291663	percent	cpu	2026-02-24 03:58:33.445+00
\N	133	cpu_usage_percent	1.9640350876898935	percent	\N	2026-02-24 02:05:02.376+00
\N	133	cpu_usage_percent	1.974999999970592	percent	\N	2026-02-24 02:06:02.376+00
\N	133	cpu_usage_percent	2.046491228076718	percent	\N	2026-02-24 02:07:02.376+00
\N	133	cpu_usage_percent	0.8793859649449729	percent	\N	2026-02-24 02:08:02.376+00
\N	133	cpu_usage_percent	0.5500000000016456	percent	\N	2026-02-24 02:09:02.376+00
\N	133	cpu_usage_percent	0.5570175438678291	percent	\N	2026-02-24 02:10:02.376+00
\N	133	cpu_usage_percent	0.5635964912934384	percent	\N	2026-02-24 02:11:02.376+00
\N	133	cpu_usage_percent	0.43991228071320165	percent	\N	2026-02-24 02:12:02.376+00
\N	133	cpu_usage_percent	0.5451754385834278	percent	\N	2026-02-24 02:13:02.376+00
\N	133	cpu_usage_percent	0.436403508861801	percent	\N	2026-02-24 02:14:02.376+00
\N	133	cpu_usage_percent	0.43991228067234545	percent	\N	2026-02-24 02:15:02.376+00
\N	133	cpu_usage_percent	0.4236842104920129	percent	\N	2026-02-24 02:16:02.376+00
\N	133	cpu_usage_percent	0.32543859648797024	percent	\N	2026-02-24 02:17:02.376+00
\N	236	cpu_usage_percent	1.7192982455813706	percent	cpu	2026-02-24 02:49:22.907+00
\N	236	cpu_usage_percent	1.9824561404816023	percent	cpu	2026-02-24 02:50:22.907+00
\N	236	cpu_usage_percent	2.361403508765406	percent	cpu	2026-02-24 02:51:22.907+00
\N	236	cpu_usage_percent	2.3929824560815405	percent	cpu	2026-02-24 02:52:22.907+00
\N	236	cpu_usage_percent	2.403508771962521	percent	cpu	2026-02-24 02:53:22.907+00
\N	236	cpu_usage_percent	1.8421052631579045	percent	cpu	2026-02-24 02:54:22.907+00
\N	236	cpu_usage_percent	1.8912280702211888	percent	cpu	2026-02-24 02:55:22.907+00
\N	236	cpu_usage_percent	1.3578947367179381	percent	\N	2026-02-24 02:05:02.452+00
\N	236	cpu_usage_percent	1.3403508771341706	percent	\N	2026-02-24 02:06:02.452+00
\N	236	cpu_usage_percent	1.4210526315136036	percent	\N	2026-02-24 02:07:02.452+00
\N	236	cpu_usage_percent	1.4245614035283864	percent	\N	2026-02-24 02:08:02.452+00
\N	236	cpu_usage_percent	1.617543859603387	percent	\N	2026-02-24 02:09:02.452+00
\N	236	cpu_usage_percent	1.631578947335754	percent	\N	2026-02-24 02:10:02.452+00
\N	236	cpu_usage_percent	1.6385964912019375	percent	\N	2026-02-24 02:11:02.452+00
\N	236	cpu_usage_percent	2.101754385879957	percent	\N	2026-02-24 02:12:02.452+00
\N	236	cpu_usage_percent	2.259649122950819	percent	\N	2026-02-24 02:13:02.452+00
\N	236	cpu_usage_percent	2.119298245627121	percent	\N	2026-02-24 02:14:02.452+00
\N	236	cpu_usage_percent	2.133333333359488	percent	\N	2026-02-24 02:15:02.452+00
\N	236	cpu_usage_percent	2.1368421053742708	percent	\N	2026-02-24 02:16:02.452+00
\N	236	cpu_usage_percent	1.3473684211637362	percent	\N	2026-02-24 02:17:02.452+00
\N	236	cpu_usage_percent	1.5017543858930225	percent	cpu	2026-02-24 02:56:22.907+00
\N	236	cpu_usage_percent	1.4631578947107045	percent	cpu	2026-02-24 02:57:22.907+00
\N	236	cpu_usage_percent	1.4596491226959216	percent	cpu	2026-02-24 02:58:22.907+00
\N	236	cpu_usage_percent	1.294736842085669	percent	cpu	2026-02-24 02:59:22.907+00
\N	236	cpu_usage_percent	1.5824561402724555	percent	cpu	2026-02-24 03:00:22.907+00
\N	133	cpu_usage_percent	0.4328947368470182	percent	cpu	2026-02-24 03:59:33.445+00
\N	133	cpu_usage_percent	0.43070175439903835	percent	cpu	2026-02-24 04:00:33.445+00
\N	248	cpu_usage_percent	3.6890350875706304	percent	\N	2026-02-24 02:05:02.518+00
\N	248	cpu_usage_percent	3.3460526315397487	percent	\N	2026-02-24 02:06:02.518+00
\N	248	cpu_usage_percent	3.300438596491233	percent	\N	2026-02-24 02:07:02.518+00
\N	248	cpu_usage_percent	3.121052631544657	percent	\N	2026-02-24 02:08:02.518+00
\N	248	cpu_usage_percent	2.9118421052484678	percent	\N	2026-02-24 02:09:02.518+00
\N	248	cpu_usage_percent	2.648245614030202	percent	\N	2026-02-24 02:10:02.518+00
\N	248	cpu_usage_percent	2.5285087719870205	percent	\N	2026-02-24 02:11:02.518+00
\N	248	cpu_usage_percent	2.30789473688786	percent	\N	2026-02-24 02:12:02.518+00
\N	248	cpu_usage_percent	2.365789473620495	percent	\N	2026-02-24 02:13:02.518+00
\N	248	cpu_usage_percent	2.316666666679751	percent	\N	2026-02-24 02:14:02.518+00
\N	248	cpu_usage_percent	2.388157894704179	percent	\N	2026-02-24 02:15:02.518+00
\N	248	cpu_usage_percent	2.5219298245614112	percent	\N	2026-02-24 02:16:02.518+00
\N	248	cpu_usage_percent	2.4491228070518645	percent	\N	2026-02-24 02:17:02.518+00
\N	133	cpu_usage_percent	0.42850877195107273	percent	cpu	2026-02-24 04:08:36.562+00
\N	133	cpu_usage_percent	0.42105263156261685	percent	cpu	2026-02-24 04:09:36.562+00
\N	133	cpu_usage_percent	0.42982456147704795	percent	cpu	2026-02-24 04:10:36.562+00
\N	133	cpu_usage_percent	0.6416666666617772	percent	cpu	2026-02-24 04:11:36.562+00
\N	133	cpu_usage_percent	0.685087719221471	percent	cpu	2026-02-24 04:12:36.562+00
\N	133	cpu_usage_percent	0.679824561403521	percent	cpu	2026-02-24 04:13:36.562+00
\N	133	cpu_usage_percent	0.6934210527361557	percent	cpu	2026-02-24 04:14:36.562+00
\N	252	cpu_usage_percent	23.84210526322326	percent	\N	2026-02-24 02:05:02.574+00
\N	252	cpu_usage_percent	23.481140350922942	percent	\N	2026-02-24 02:06:02.574+00
\N	252	cpu_usage_percent	23.93991228068461	percent	\N	2026-02-24 02:07:02.574+00
\N	252	cpu_usage_percent	23.724122807003667	percent	\N	2026-02-24 02:08:02.574+00
\N	252	cpu_usage_percent	23.801315789490857	percent	\N	2026-02-24 02:09:02.574+00
\N	252	cpu_usage_percent	23.86973684212488	percent	\N	2026-02-24 02:10:02.574+00
\N	252	cpu_usage_percent	23.925877192972663	percent	\N	2026-02-24 02:11:02.574+00
\N	252	cpu_usage_percent	23.758771929832733	percent	\N	2026-02-24 02:12:02.574+00
\N	252	cpu_usage_percent	23.679824561419863	percent	\N	2026-02-24 02:13:02.574+00
\N	252	cpu_usage_percent	23.453508771898797	percent	\N	2026-02-24 02:14:02.574+00
\N	252	cpu_usage_percent	23.52500000002533	percent	\N	2026-02-24 02:15:02.574+00
\N	252	cpu_usage_percent	23.65043859653126	percent	\N	2026-02-24 02:16:02.574+00
\N	252	cpu_usage_percent	23.721929824494424	percent	\N	2026-02-24 02:17:02.574+00
\N	133	cpu_usage_percent	0.700438596438957	percent	cpu	2026-02-24 04:15:36.562+00
\N	133	cpu_usage_percent	0.473684210477316	percent	cpu	2026-02-24 04:16:36.562+00
\N	248	cpu_usage_percent	2.439473684256285	percent	cpu	2026-02-24 02:44:31.069+00
\N	248	cpu_usage_percent	2.572807017591245	percent	cpu	2026-02-24 02:45:31.069+00
\N	248	cpu_usage_percent	2.703508771874283	percent	cpu	2026-02-24 02:46:31.069+00
\N	248	cpu_usage_percent	2.7596491227629087	percent	cpu	2026-02-24 02:47:31.069+00
\N	248	cpu_usage_percent	2.6627192982848413	percent	cpu	2026-02-24 02:48:31.069+00
\N	257	cpu_usage_percent	4.0245614035193995	percent	\N	2026-02-24 02:05:02.631+00
\N	257	cpu_usage_percent	3.7938596491228225	percent	\N	2026-02-24 02:06:02.631+00
\N	257	cpu_usage_percent	3.8210526315634326	percent	\N	2026-02-24 02:07:02.631+00
\N	257	cpu_usage_percent	3.9710526315805907	percent	\N	2026-02-24 02:08:02.631+00
\N	257	cpu_usage_percent	4.657894736850281	percent	\N	2026-02-24 02:09:02.631+00
\N	257	cpu_usage_percent	5.027192982420203	percent	\N	2026-02-24 02:10:02.631+00
\N	257	cpu_usage_percent	5.424561403495716	percent	\N	2026-02-24 02:11:02.631+00
\N	257	cpu_usage_percent	5.2385964912256355	percent	\N	2026-02-24 02:12:02.631+00
\N	257	cpu_usage_percent	5.259649122824186	percent	\N	2026-02-24 02:13:02.631+00
\N	257	cpu_usage_percent	4.626315789452448	percent	\N	2026-02-24 02:14:02.631+00
\N	257	cpu_usage_percent	4.273684210523882	percent	\N	2026-02-24 02:15:02.631+00
\N	257	cpu_usage_percent	3.948245614056333	percent	\N	2026-02-24 02:16:02.631+00
\N	257	cpu_usage_percent	3.7552631578588063	percent	\N	2026-02-24 02:17:02.631+00
\N	248	cpu_usage_percent	2.801315789396895	percent	cpu	2026-02-24 02:49:31.069+00
\N	248	cpu_usage_percent	2.7267543860025114	percent	cpu	2026-02-24 02:50:31.069+00
\N	248	cpu_usage_percent	2.7671052631513646	percent	cpu	2026-02-24 02:51:31.069+00
\N	248	cpu_usage_percent	2.628070175394498	percent	cpu	2026-02-24 02:52:31.069+00
\N	133	cpu_usage_percent	0.4543859648453008	percent	cpu	2026-02-24 04:17:36.562+00
\N	260	cpu_usage_percent	25.552192982408755	percent	\N	2026-02-24 02:05:02.692+00
\N	260	cpu_usage_percent	25.582894736864176	percent	\N	2026-02-24 02:06:02.692+00
\N	260	cpu_usage_percent	25.549561403520215	percent	\N	2026-02-24 02:07:02.692+00
\N	260	cpu_usage_percent	25.586293859697335	percent	\N	2026-02-24 02:08:02.692+00
\N	260	cpu_usage_percent	25.501644736831892	percent	\N	2026-02-24 02:09:02.692+00
\N	260	cpu_usage_percent	25.57335526315832	percent	\N	2026-02-24 02:10:02.692+00
\N	260	cpu_usage_percent	25.512938596504313	percent	\N	2026-02-24 02:11:02.692+00
\N	260	cpu_usage_percent	25.51348684210609	percent	\N	2026-02-24 02:12:02.692+00
\N	260	cpu_usage_percent	25.481030701714772	percent	\N	2026-02-24 02:13:02.692+00
\N	260	cpu_usage_percent	25.515899122845838	percent	\N	2026-02-24 02:14:02.692+00
\N	260	cpu_usage_percent	25.485307017561837	percent	\N	2026-02-24 02:15:02.692+00
\N	260	cpu_usage_percent	25.476096491247674	percent	\N	2026-02-24 02:16:02.692+00
\N	260	cpu_usage_percent	25.480482456153837	percent	\N	2026-02-24 02:17:02.692+00
\N	248	cpu_usage_percent	2.4530701754663937	percent	cpu	2026-02-24 02:53:31.069+00
\N	248	cpu_usage_percent	2.3938596490444013	percent	cpu	2026-02-24 02:54:31.069+00
\N	248	cpu_usage_percent	2.3596491227988565	percent	cpu	2026-02-24 02:55:31.069+00
\N	248	cpu_usage_percent	2.243859649129348	percent	cpu	2026-02-24 02:56:31.069+00
\N	133	cpu_usage_percent	0.34605263152340626	percent	cpu	2026-02-24 04:18:36.562+00
\N	133	cpu_usage_percent	0.47675438601066844	percent	cpu	2026-02-24 04:19:36.562+00
\N	236	cpu_usage_percent	1.4526315788297381	percent	cpu	2026-02-24 03:08:27.562+00
\N	133	cpu_usage_percent	0.43991228067234545	percent	\N	2026-02-24 02:15:02.761+00
\N	133	cpu_usage_percent	0.4236842104920129	percent	\N	2026-02-24 02:16:02.761+00
\N	133	cpu_usage_percent	0.32543859648797024	percent	\N	2026-02-24 02:17:02.761+00
\N	133	cpu_usage_percent	0.4285087719919147	percent	\N	2026-02-24 02:18:02.761+00
\N	133	cpu_usage_percent	0.5486842105573686	percent	\N	2026-02-24 02:19:02.761+00
\N	133	cpu_usage_percent	0.5460526316279726	percent	\N	2026-02-24 02:20:02.761+00
\N	133	cpu_usage_percent	0.5521929824496112	percent	\N	2026-02-24 02:21:02.761+00
\N	133	cpu_usage_percent	0.55043859656476	percent	\N	2026-02-24 02:22:02.761+00
\N	133	cpu_usage_percent	0.5350877193472741	percent	\N	2026-02-24 02:23:02.761+00
\N	133	cpu_usage_percent	0.42894736851420134	percent	\N	2026-02-24 02:24:02.761+00
\N	133	cpu_usage_percent	0.4087719297967851	percent	\N	2026-02-24 02:25:02.761+00
\N	133	cpu_usage_percent	0.4144736841778638	percent	\N	2026-02-24 02:26:02.761+00
\N	133	cpu_usage_percent	0.4157894737038248	percent	\N	2026-02-24 02:27:02.761+00
\N	236	cpu_usage_percent	1.490536775696654	percent	cpu	2026-02-24 03:09:27.562+00
\N	236	cpu_usage_percent	1.5859649122872526	percent	cpu	2026-02-24 03:10:27.562+00
\N	236	cpu_usage_percent	1.7508771930609015	percent	cpu	2026-02-24 03:11:27.562+00
\N	236	cpu_usage_percent	1.7719298244960555	percent	cpu	2026-02-24 03:12:27.562+00
\N	236	cpu_usage_percent	1.771929824659452	percent	cpu	2026-02-24 03:13:27.562+00
\N	236	cpu_usage_percent	1.740350877179921	percent	cpu	2026-02-24 03:14:27.562+00
\N	236	cpu_usage_percent	1.466666666562105	percent	cpu	2026-02-24 03:15:27.562+00
\N	236	cpu_usage_percent	2.133333333359488	percent	\N	2026-02-24 02:15:02.825+00
\N	236	cpu_usage_percent	2.1368421053742708	percent	\N	2026-02-24 02:16:02.825+00
\N	236	cpu_usage_percent	1.3473684211637362	percent	\N	2026-02-24 02:17:02.825+00
\N	236	cpu_usage_percent	1.4631578947107045	percent	\N	2026-02-24 02:18:02.825+00
\N	236	cpu_usage_percent	1.564912280688688	percent	\N	2026-02-24 02:19:02.825+00
\N	236	cpu_usage_percent	1.603508771871006	percent	\N	2026-02-24 02:20:02.825+00
\N	236	cpu_usage_percent	1.6140350877519865	percent	\N	2026-02-24 02:21:02.825+00
\N	236	cpu_usage_percent	1.62105263161817	percent	\N	2026-02-24 02:22:02.825+00
\N	236	cpu_usage_percent	1.603508771871006	percent	\N	2026-02-24 02:23:02.825+00
\N	236	cpu_usage_percent	1.473684210591685	percent	\N	2026-02-24 02:24:02.825+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	\N	2026-02-24 02:25:02.825+00
\N	236	cpu_usage_percent	1.456140350844521	percent	\N	2026-02-24 02:26:02.825+00
\N	236	cpu_usage_percent	1.4596491228593038	percent	\N	2026-02-24 02:27:02.825+00
\N	236	cpu_usage_percent	1.4491228069783375	percent	cpu	2026-02-24 03:16:27.562+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	cpu	2026-02-24 03:17:27.562+00
\N	236	cpu_usage_percent	1.508771929759206	percent	cpu	2026-02-24 03:18:27.562+00
\N	236	cpu_usage_percent	1.4947368421902354	percent	cpu	2026-02-24 03:19:27.562+00
\N	236	cpu_usage_percent	1.466666666562105	percent	cpu	2026-02-24 03:20:27.562+00
\N	133	cpu_usage_percent	0.454385964886157	percent	cpu	2026-02-24 04:20:36.562+00
\N	133	cpu_usage_percent	0.4368421052206912	percent	cpu	2026-02-24 04:38:41.311+00
\N	248	cpu_usage_percent	2.388157894704179	percent	\N	2026-02-24 02:15:02.892+00
\N	248	cpu_usage_percent	2.5219298245614112	percent	\N	2026-02-24 02:16:02.892+00
\N	248	cpu_usage_percent	2.4491228070518645	percent	\N	2026-02-24 02:17:02.892+00
\N	248	cpu_usage_percent	3.0035087719902975	percent	\N	2026-02-24 02:18:02.892+00
\N	248	cpu_usage_percent	3.3166666666307236	percent	\N	2026-02-24 02:19:02.892+00
\N	248	cpu_usage_percent	3.774122807009377	percent	\N	2026-02-24 02:20:02.892+00
\N	248	cpu_usage_percent	3.88289473677186	percent	\N	2026-02-24 02:21:02.892+00
\N	248	cpu_usage_percent	3.952192982511704	percent	\N	2026-02-24 02:22:02.892+00
\N	248	cpu_usage_percent	3.458771929880129	percent	\N	2026-02-24 02:23:02.892+00
\N	248	cpu_usage_percent	3.1649122807491494	percent	\N	2026-02-24 02:24:02.892+00
\N	248	cpu_usage_percent	2.6964912280489415	percent	\N	2026-02-24 02:25:02.892+00
\N	248	cpu_usage_percent	2.8074561403819303	percent	\N	2026-02-24 02:26:02.892+00
\N	248	cpu_usage_percent	2.7907894737201673	percent	\N	2026-02-24 02:27:02.892+00
\N	133	cpu_usage_percent	0.3324561403950099	percent	cpu	2026-02-24 04:39:41.311+00
\N	133	cpu_usage_percent	0.45087719295305817	percent	cpu	2026-02-24 04:40:41.311+00
\N	133	cpu_usage_percent	0.5250000000294222	percent	cpu	2026-02-24 04:41:41.311+00
\N	133	cpu_usage_percent	0.6692982456042387	percent	cpu	2026-02-24 04:42:41.311+00
\N	133	cpu_usage_percent	0.6820175438923428	percent	cpu	2026-02-24 04:43:41.311+00
\N	133	cpu_usage_percent	0.590350877232197	percent	cpu	2026-02-24 04:44:41.311+00
\N	133	cpu_usage_percent	0.6583333334052384	percent	cpu	2026-02-24 04:45:41.311+00
\N	252	cpu_usage_percent	23.52500000002533	percent	\N	2026-02-24 02:15:02.955+00
\N	252	cpu_usage_percent	23.65043859653126	percent	\N	2026-02-24 02:16:02.955+00
\N	252	cpu_usage_percent	23.721929824494424	percent	\N	2026-02-24 02:17:02.955+00
\N	252	cpu_usage_percent	24.463157894727047	percent	\N	2026-02-24 02:18:02.955+00
\N	252	cpu_usage_percent	24.964035087726657	percent	\N	2026-02-24 02:19:02.955+00
\N	252	cpu_usage_percent	25.295175438575257	percent	\N	2026-02-24 02:20:02.955+00
\N	252	cpu_usage_percent	25.464035087743	percent	\N	2026-02-24 02:21:02.955+00
\N	252	cpu_usage_percent	25.822368420991367	percent	\N	2026-02-24 02:22:02.955+00
\N	252	cpu_usage_percent	25.32894736846191	percent	\N	2026-02-24 02:23:02.955+00
\N	252	cpu_usage_percent	24.818421052605444	percent	\N	2026-02-24 02:24:02.955+00
\N	252	cpu_usage_percent	25.019736842133867	percent	\N	2026-02-24 02:25:02.955+00
\N	252	cpu_usage_percent	25.759649122799672	percent	\N	2026-02-24 02:26:02.955+00
\N	252	cpu_usage_percent	25.48026315790291	percent	\N	2026-02-24 02:27:02.955+00
\N	248	cpu_usage_percent	2.875438596432417	percent	cpu	2026-02-24 02:48:23.165+00
\N	248	cpu_usage_percent	2.818859649103217	percent	cpu	2026-02-24 02:49:23.165+00
\N	248	cpu_usage_percent	2.739473684168061	percent	cpu	2026-02-24 02:50:23.165+00
\N	248	cpu_usage_percent	2.7565789474337805	percent	cpu	2026-02-24 02:51:23.165+00
\N	248	cpu_usage_percent	2.6592105263109005	percent	cpu	2026-02-24 02:52:23.165+00
\N	133	cpu_usage_percent	0.5618421052860469	percent	cpu	2026-02-24 04:46:41.311+00
\N	257	cpu_usage_percent	4.273684210523882	percent	\N	2026-02-24 02:15:03.02+00
\N	257	cpu_usage_percent	3.948245614056333	percent	\N	2026-02-24 02:16:03.02+00
\N	257	cpu_usage_percent	3.7552631578588063	percent	\N	2026-02-24 02:17:03.02+00
\N	257	cpu_usage_percent	4.087719298212946	percent	\N	2026-02-24 02:18:03.02+00
\N	257	cpu_usage_percent	4.6263157894728835	percent	\N	2026-02-24 02:19:03.02+00
\N	257	cpu_usage_percent	5.030701754373723	percent	\N	2026-02-24 02:20:03.02+00
\N	257	cpu_usage_percent	5.434210526311716	percent	\N	2026-02-24 02:21:03.02+00
\N	257	cpu_usage_percent	5.436842105261533	percent	\N	2026-02-24 02:22:03.02+00
\N	257	cpu_usage_percent	5.244736842108537	percent	\N	2026-02-24 02:23:03.02+00
\N	257	cpu_usage_percent	4.642105263151365	percent	\N	2026-02-24 02:24:03.02+00
\N	257	cpu_usage_percent	4.343859649124454	percent	\N	2026-02-24 02:25:03.02+00
\N	257	cpu_usage_percent	4.021052631606736	percent	\N	2026-02-24 02:26:03.02+00
\N	257	cpu_usage_percent	4.0271929824692165	percent	\N	2026-02-24 02:27:03.02+00
\N	248	cpu_usage_percent	2.4982456139926086	percent	cpu	2026-02-24 02:53:23.165+00
\N	248	cpu_usage_percent	2.4065789474141894	percent	cpu	2026-02-24 02:54:23.165+00
\N	248	cpu_usage_percent	2.3548245613806387	percent	cpu	2026-02-24 02:55:23.165+00
\N	248	cpu_usage_percent	2.242543859644229	percent	cpu	2026-02-24 02:56:23.165+00
\N	248	cpu_usage_percent	2.3723684210461045	percent	cpu	2026-02-24 02:57:23.165+00
\N	248	cpu_usage_percent	2.415789473605784	percent	cpu	2026-02-24 02:58:23.165+00
\N	260	cpu_usage_percent	25.485307017561837	percent	\N	2026-02-24 02:15:03.086+00
\N	260	cpu_usage_percent	25.476096491247674	percent	\N	2026-02-24 02:16:03.086+00
\N	260	cpu_usage_percent	25.480482456153837	percent	\N	2026-02-24 02:17:03.086+00
\N	260	cpu_usage_percent	25.47192982455161	percent	\N	2026-02-24 02:18:03.086+00
\N	260	cpu_usage_percent	25.501535087742184	percent	\N	2026-02-24 02:19:03.086+00
\N	260	cpu_usage_percent	25.550986842095057	percent	\N	2026-02-24 02:20:03.086+00
\N	260	cpu_usage_percent	25.50087719294855	percent	\N	2026-02-24 02:21:03.086+00
\N	260	cpu_usage_percent	25.535855263128497	percent	\N	2026-02-24 02:22:03.086+00
\N	260	cpu_usage_percent	25.482236842099965	percent	\N	2026-02-24 02:23:03.086+00
\N	260	cpu_usage_percent	25.571271929840904	percent	\N	2026-02-24 02:24:03.086+00
\N	260	cpu_usage_percent	25.482456140361094	percent	\N	2026-02-24 02:25:03.086+00
\N	260	cpu_usage_percent	25.533333333319447	percent	\N	2026-02-24 02:26:03.086+00
\N	260	cpu_usage_percent	25.501864035072614	percent	\N	2026-02-24 02:27:03.086+00
\N	248	cpu_usage_percent	2.400000000029422	percent	cpu	2026-02-24 02:59:23.165+00
\N	252	cpu_usage_percent	23.507017543858026	percent	cpu	2026-02-24 02:44:31.377+00
\N	252	cpu_usage_percent	23.81271929823255	percent	cpu	2026-02-24 02:45:31.377+00
\N	252	cpu_usage_percent	23.835087719316235	percent	cpu	2026-02-24 02:46:31.377+00
\N	252	cpu_usage_percent	23.883333333334974	percent	cpu	2026-02-24 02:47:31.377+00
\N	252	cpu_usage_percent	23.77324561404653	percent	cpu	2026-02-24 02:48:31.377+00
\N	252	cpu_usage_percent	23.860964912271726	percent	cpu	2026-02-24 02:49:31.377+00
\N	133	cpu_usage_percent	0.4087719297967851	percent	\N	2026-02-24 02:25:03.154+00
\N	133	cpu_usage_percent	0.4144736841778638	percent	\N	2026-02-24 02:26:03.154+00
\N	133	cpu_usage_percent	0.4157894737038248	percent	\N	2026-02-24 02:27:03.154+00
\N	133	cpu_usage_percent	0.40043859652718083	percent	\N	2026-02-24 02:28:03.154+00
\N	133	cpu_usage_percent	0.5118421052599018	percent	\N	2026-02-24 02:29:03.154+00
\N	133	cpu_usage_percent	0.5381578947581005	percent	\N	2026-02-24 02:30:03.154+00
\N	133	cpu_usage_percent	0.531140350891917	percent	\N	2026-02-24 02:31:03.154+00
\N	133	cpu_usage_percent	0.5535087718938883	percent	\N	2026-02-24 02:32:03.154+00
\N	133	cpu_usage_percent	0.44780701741969153	percent	\N	2026-02-24 02:33:03.154+00
\N	133	cpu_usage_percent	0.43026315787678016	percent	\N	2026-02-24 02:34:03.154+00
\N	133	cpu_usage_percent	0.4271929823842555	percent	\N	2026-02-24 02:35:03.154+00
\N	133	cpu_usage_percent	0.4337719298507068	percent	\N	2026-02-24 02:36:03.154+00
\N	133	cpu_usage_percent	0.42017543864061224	percent	\N	2026-02-24 02:37:03.154+00
\N	252	cpu_usage_percent	23.510964912292962	percent	cpu	2026-02-24 02:50:31.377+00
\N	252	cpu_usage_percent	23.820614035082016	percent	cpu	2026-02-24 02:51:31.377+00
\N	252	cpu_usage_percent	23.675877192964492	percent	cpu	2026-02-24 02:52:31.377+00
\N	252	cpu_usage_percent	23.68114035088456	percent	cpu	2026-02-24 02:53:31.377+00
\N	252	cpu_usage_percent	23.639473684189298	percent	cpu	2026-02-24 02:54:31.377+00
\N	252	cpu_usage_percent	23.570175438571994	percent	cpu	2026-02-24 02:55:31.377+00
\N	252	cpu_usage_percent	23.20570175439987	percent	cpu	2026-02-24 02:56:31.377+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	\N	2026-02-24 02:25:03.246+00
\N	236	cpu_usage_percent	1.456140350844521	percent	\N	2026-02-24 02:26:03.246+00
\N	236	cpu_usage_percent	1.4596491228593038	percent	\N	2026-02-24 02:27:03.246+00
\N	236	cpu_usage_percent	1.3157894736842195	percent	\N	2026-02-24 02:28:03.246+00
\N	236	cpu_usage_percent	1.659649122800488	percent	\N	2026-02-24 02:29:03.246+00
\N	236	cpu_usage_percent	1.7087719298637865	percent	\N	2026-02-24 02:30:03.246+00
\N	236	cpu_usage_percent	1.726315789447554	percent	\N	2026-02-24 02:31:03.246+00
\N	236	cpu_usage_percent	1.7157894735665735	percent	\N	2026-02-24 02:32:03.246+00
\N	236	cpu_usage_percent	1.550877192956321	percent	\N	2026-02-24 02:33:03.246+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	\N	2026-02-24 02:34:03.246+00
\N	236	cpu_usage_percent	1.456140350844521	percent	\N	2026-02-24 02:35:03.246+00
\N	236	cpu_usage_percent	1.4666666667255015	percent	\N	2026-02-24 02:36:03.246+00
\N	236	cpu_usage_percent	1.6105263159005858	percent	\N	2026-02-24 02:37:03.246+00
\N	248	cpu_usage_percent	2.657017543903777	percent	cpu	2026-02-24 03:00:23.165+00
\N	133	cpu_usage_percent	0.43771929814269583	percent	cpu	2026-02-24 04:47:41.311+00
\N	133	cpu_usage_percent	0.4285087719919147	percent	cpu	2026-02-24 04:48:41.311+00
\N	133	cpu_usage_percent	0.4447368421722615	percent	cpu	2026-02-24 04:49:41.311+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	cpu	2026-02-24 03:28:30.653+00
\N	236	cpu_usage_percent	1.473684210591685	percent	cpu	2026-02-24 03:29:30.653+00
\N	236	cpu_usage_percent	1.5719298245548714	percent	cpu	2026-02-24 03:30:30.653+00
\N	248	cpu_usage_percent	2.6964912280489415	percent	\N	2026-02-24 02:25:03.333+00
\N	248	cpu_usage_percent	2.8074561403819303	percent	\N	2026-02-24 02:26:03.333+00
\N	248	cpu_usage_percent	2.7907894737201673	percent	\N	2026-02-24 02:27:03.333+00
\N	248	cpu_usage_percent	2.8530701753895897	percent	\N	2026-02-24 02:28:03.333+00
\N	248	cpu_usage_percent	2.9407894737169045	percent	\N	2026-02-24 02:29:03.333+00
\N	248	cpu_usage_percent	2.897807017597785	percent	\N	2026-02-24 02:30:03.333+00
\N	248	cpu_usage_percent	2.894298245583002	percent	\N	2026-02-24 02:31:03.333+00
\N	248	cpu_usage_percent	2.8565789474860708	percent	\N	2026-02-24 02:32:03.333+00
\N	248	cpu_usage_percent	2.64868421055246	percent	\N	2026-02-24 02:33:03.333+00
\N	248	cpu_usage_percent	2.6754385964912473	percent	\N	2026-02-24 02:34:03.333+00
\N	248	cpu_usage_percent	2.658333333388896	percent	\N	2026-02-24 02:35:03.333+00
\N	248	cpu_usage_percent	2.5122807017249897	percent	\N	2026-02-24 02:36:03.333+00
\N	248	cpu_usage_percent	2.453508771906968	percent	\N	2026-02-24 02:37:03.333+00
\N	236	cpu_usage_percent	1.7087719298637865	percent	cpu	2026-02-24 03:31:30.653+00
\N	236	cpu_usage_percent	1.70877192970039	percent	cpu	2026-02-24 03:32:30.653+00
\N	236	cpu_usage_percent	1.849122807024088	percent	cpu	2026-02-24 03:33:30.653+00
\N	236	cpu_usage_percent	1.8912280700578066	percent	cpu	2026-02-24 03:34:30.653+00
\N	236	cpu_usage_percent	1.7754385965108526	percent	cpu	2026-02-24 03:35:30.653+00
\N	236	cpu_usage_percent	1.4807017544578684	percent	cpu	2026-02-24 03:36:30.653+00
\N	236	cpu_usage_percent	1.5052631579078195	percent	cpu	2026-02-24 03:37:30.653+00
\N	252	cpu_usage_percent	25.019736842133867	percent	\N	2026-02-24 02:25:03.388+00
\N	252	cpu_usage_percent	25.759649122799672	percent	\N	2026-02-24 02:26:03.388+00
\N	252	cpu_usage_percent	25.48026315790291	percent	\N	2026-02-24 02:27:03.388+00
\N	252	cpu_usage_percent	25.388596491242794	percent	\N	2026-02-24 02:28:03.388+00
\N	252	cpu_usage_percent	25.59912280704451	percent	\N	2026-02-24 02:29:03.388+00
\N	252	cpu_usage_percent	25.267982456155067	percent	\N	2026-02-24 02:30:03.388+00
\N	252	cpu_usage_percent	24.642105263151365	percent	\N	2026-02-24 02:31:03.388+00
\N	252	cpu_usage_percent	24.663157894709073	percent	\N	2026-02-24 02:32:03.388+00
\N	252	cpu_usage_percent	24.207017543856395	percent	\N	2026-02-24 02:33:03.388+00
\N	252	cpu_usage_percent	24.070175438588322	percent	\N	2026-02-24 02:34:03.388+00
\N	252	cpu_usage_percent	23.854385964948236	percent	\N	2026-02-24 02:35:03.388+00
\N	252	cpu_usage_percent	23.841666666680567	percent	\N	2026-02-24 02:36:03.388+00
\N	252	cpu_usage_percent	25.69912280699468	percent	\N	2026-02-24 02:37:03.388+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	cpu	2026-02-24 03:38:30.653+00
\N	236	cpu_usage_percent	1.4280701755431693	percent	cpu	2026-02-24 03:39:30.653+00
\N	236	cpu_usage_percent	1.568421052703485	percent	cpu	2026-02-24 03:40:30.653+00
\N	133	cpu_usage_percent	0.44780701754223173	percent	cpu	2026-02-24 04:50:41.311+00
\N	133	cpu_usage_percent	0.42850877186938874	percent	cpu	2026-02-24 04:58:54.766+00
\N	257	cpu_usage_percent	4.343859649124454	percent	\N	2026-02-24 02:25:03.443+00
\N	257	cpu_usage_percent	4.021052631606736	percent	\N	2026-02-24 02:26:03.443+00
\N	257	cpu_usage_percent	4.0271929824692165	percent	\N	2026-02-24 02:27:03.443+00
\N	257	cpu_usage_percent	3.9798245613929026	percent	\N	2026-02-24 02:28:03.443+00
\N	257	cpu_usage_percent	4.564035087721763	percent	\N	2026-02-24 02:29:03.443+00
\N	257	cpu_usage_percent	5.153508771929836	percent	\N	2026-02-24 02:30:03.443+00
\N	257	cpu_usage_percent	5.4807017543843415	percent	\N	2026-02-24 02:31:03.443+00
\N	257	cpu_usage_percent	5.525438596510838	percent	\N	2026-02-24 02:32:03.443+00
\N	257	cpu_usage_percent	5.028070175423906	percent	\N	2026-02-24 02:33:03.443+00
\N	257	cpu_usage_percent	4.715789473644193	percent	\N	2026-02-24 02:34:03.443+00
\N	257	cpu_usage_percent	4.31929824561324	percent	\N	2026-02-24 02:35:03.443+00
\N	257	cpu_usage_percent	3.986842105259086	percent	\N	2026-02-24 02:36:03.443+00
\N	257	cpu_usage_percent	3.958771929835194	percent	\N	2026-02-24 02:37:03.443+00
\N	133	cpu_usage_percent	0.4552631579307018	percent	cpu	2026-02-24 04:59:54.766+00
\N	133	cpu_usage_percent	0.6118421051896377	percent	cpu	2026-02-24 05:00:54.766+00
\N	133	cpu_usage_percent	0.6364035088029851	percent	cpu	2026-02-24 05:01:54.766+00
\N	133	cpu_usage_percent	0.8535087718873626	percent	cpu	2026-02-24 05:02:54.766+00
\N	133	cpu_usage_percent	0.8495614034728334	percent	cpu	2026-02-24 05:03:54.766+00
\N	133	cpu_usage_percent	0.8548245614133236	percent	cpu	2026-02-24 05:04:54.766+00
\N	133	cpu_usage_percent	2.1166666666568688	percent	cpu	2026-02-24 05:05:54.766+00
\N	260	cpu_usage_percent	25.482456140361094	percent	\N	2026-02-24 02:25:03.508+00
\N	260	cpu_usage_percent	25.533333333319447	percent	\N	2026-02-24 02:26:03.508+00
\N	260	cpu_usage_percent	25.501864035072614	percent	\N	2026-02-24 02:27:03.508+00
\N	260	cpu_usage_percent	25.478070175424307	percent	\N	2026-02-24 02:28:03.508+00
\N	260	cpu_usage_percent	25.51633771924557	percent	\N	2026-02-24 02:29:03.508+00
\N	260	cpu_usage_percent	25.533662280690734	percent	\N	2026-02-24 02:30:03.508+00
\N	260	cpu_usage_percent	25.587938596482246	percent	\N	2026-02-24 02:31:03.508+00
\N	260	cpu_usage_percent	25.603508771909816	percent	\N	2026-02-24 02:32:03.508+00
\N	260	cpu_usage_percent	25.608004385905687	percent	\N	2026-02-24 02:33:03.508+00
\N	260	cpu_usage_percent	25.59846491228153	percent	\N	2026-02-24 02:34:03.508+00
\N	260	cpu_usage_percent	25.607894736836386	percent	\N	2026-02-24 02:35:03.508+00
\N	260	cpu_usage_percent	25.579824561392087	percent	\N	2026-02-24 02:36:03.508+00
\N	260	cpu_usage_percent	25.513925438556868	percent	\N	2026-02-24 02:37:03.508+00
\N	133	cpu_usage_percent	2.118421052623418	percent	cpu	2026-02-24 05:06:54.766+00
\N	133	cpu_usage_percent	1.997368421095132	percent	cpu	2026-02-24 05:07:54.766+00
\N	248	cpu_usage_percent	2.4210526315871306	percent	cpu	2026-02-24 03:08:27.824+00
\N	248	cpu_usage_percent	2.475438596468365	percent	cpu	2026-02-24 03:09:27.824+00
\N	248	cpu_usage_percent	2.539035087745461	percent	cpu	2026-02-24 03:10:27.824+00
\N	248	cpu_usage_percent	2.4526315789849633	percent	cpu	2026-02-24 03:11:27.824+00
\N	248	cpu_usage_percent	2.4271929824496112	percent	cpu	2026-02-24 03:12:27.824+00
\N	133	cpu_usage_percent	0.4271929823842555	percent	\N	2026-02-24 02:35:03.576+00
\N	133	cpu_usage_percent	0.4337719298507068	percent	\N	2026-02-24 02:36:03.576+00
\N	133	cpu_usage_percent	0.42017543864061224	percent	\N	2026-02-24 02:37:03.576+00
\N	133	cpu_usage_percent	0.3412280702277428	percent	\N	2026-02-24 02:38:03.576+00
\N	133	cpu_usage_percent	0.4258771929808347	percent	\N	2026-02-24 02:39:03.576+00
\N	133	cpu_usage_percent	0.5364035087507091	percent	\N	2026-02-24 02:40:03.576+00
\N	133	cpu_usage_percent	0.5328947368993084	percent	\N	2026-02-24 02:41:03.576+00
\N	133	cpu_usage_percent	0.5320175438547636	percent	\N	2026-02-24 02:42:03.576+00
\N	133	cpu_usage_percent	0.5442982456205812	percent	\N	2026-02-24 02:43:03.576+00
\N	133	cpu_usage_percent	0.4368421052615332	percent	\N	2026-02-24 02:44:03.576+00
\N	133	cpu_usage_percent	0.41885964915549323	percent	\N	2026-02-24 02:45:03.576+00
\N	133	cpu_usage_percent	0.43157894740274116	percent	\N	2026-02-24 02:46:03.576+00
\N	133	cpu_usage_percent	0.42280701757000827	percent	\N	2026-02-24 02:47:03.576+00
\N	248	cpu_usage_percent	2.3574561402691927	percent	cpu	2026-02-24 03:13:27.824+00
\N	248	cpu_usage_percent	2.300000000017988	percent	cpu	2026-02-24 03:14:27.824+00
\N	248	cpu_usage_percent	2.29473684211834	percent	cpu	2026-02-24 03:15:27.824+00
\N	248	cpu_usage_percent	2.2750000000049084	percent	cpu	2026-02-24 03:16:27.824+00
\N	257	cpu_usage_percent	4.53596491227745	percent	cpu	2026-02-24 02:44:31.639+00
\N	257	cpu_usage_percent	4.198245614044083	percent	cpu	2026-02-24 02:45:31.639+00
\N	257	cpu_usage_percent	4.01491228072382	percent	cpu	2026-02-24 02:46:31.639+00
\N	236	cpu_usage_percent	1.456140350844521	percent	\N	2026-02-24 02:35:03.641+00
\N	236	cpu_usage_percent	1.4666666667255015	percent	\N	2026-02-24 02:36:03.641+00
\N	236	cpu_usage_percent	1.6105263159005858	percent	\N	2026-02-24 02:37:03.641+00
\N	236	cpu_usage_percent	1.687719298265236	percent	\N	2026-02-24 02:38:03.641+00
\N	236	cpu_usage_percent	1.754385964912288	percent	\N	2026-02-24 02:39:03.641+00
\N	236	cpu_usage_percent	2.00000000006537	percent	\N	2026-02-24 02:40:03.641+00
\N	236	cpu_usage_percent	1.9964912280505729	percent	\N	2026-02-24 02:41:03.641+00
\N	236	cpu_usage_percent	1.8526315788754886	percent	\N	2026-02-24 02:42:03.641+00
\N	236	cpu_usage_percent	1.796491228109403	percent	\N	2026-02-24 02:43:03.641+00
\N	236	cpu_usage_percent	1.6000000000196195	percent	\N	2026-02-24 02:44:03.641+00
\N	236	cpu_usage_percent	1.487719298324052	percent	\N	2026-02-24 02:45:03.641+00
\N	236	cpu_usage_percent	1.512280701774003	percent	\N	2026-02-24 02:46:03.641+00
\N	236	cpu_usage_percent	1.529824561521167	percent	\N	2026-02-24 02:47:03.641+00
\N	257	cpu_usage_percent	3.995614035091805	percent	cpu	2026-02-24 02:47:31.639+00
\N	257	cpu_usage_percent	4.169298245616488	percent	cpu	2026-02-24 02:48:31.639+00
\N	257	cpu_usage_percent	4.780701754345131	percent	cpu	2026-02-24 02:49:31.639+00
\N	257	cpu_usage_percent	5.171929824558134	percent	cpu	2026-02-24 02:50:31.639+00
\N	257	cpu_usage_percent	5.742105263154642	percent	cpu	2026-02-24 02:51:31.639+00
\N	257	cpu_usage_percent	5.723684210526329	percent	cpu	2026-02-24 02:52:31.639+00
\N	257	cpu_usage_percent	5.385964912292977	percent	cpu	2026-02-24 02:53:31.639+00
\N	248	cpu_usage_percent	2.658333333388896	percent	\N	2026-02-24 02:35:03.714+00
\N	248	cpu_usage_percent	2.5122807017249897	percent	\N	2026-02-24 02:36:03.714+00
\N	248	cpu_usage_percent	2.453508771906968	percent	\N	2026-02-24 02:37:03.714+00
\N	248	cpu_usage_percent	2.420614035024002	percent	\N	2026-02-24 02:38:03.714+00
\N	248	cpu_usage_percent	2.3135964912280826	percent	\N	2026-02-24 02:39:03.714+00
\N	248	cpu_usage_percent	2.31798245616487	percent	\N	2026-02-24 02:40:03.714+00
\N	248	cpu_usage_percent	2.2837719297559573	percent	\N	2026-02-24 02:41:03.714+00
\N	248	cpu_usage_percent	2.25131578943612	percent	\N	2026-02-24 02:42:03.714+00
\N	248	cpu_usage_percent	2.288596491215017	percent	\N	2026-02-24 02:43:03.714+00
\N	248	cpu_usage_percent	2.4491228070110225	percent	\N	2026-02-24 02:44:03.714+00
\N	248	cpu_usage_percent	2.452631578944107	percent	\N	2026-02-24 02:45:03.714+00
\N	248	cpu_usage_percent	2.586842105323626	percent	\N	2026-02-24 02:46:03.714+00
\N	248	cpu_usage_percent	2.707456140288798	percent	\N	2026-02-24 02:47:03.714+00
\N	257	cpu_usage_percent	4.868421052631589	percent	cpu	2026-02-24 02:54:31.639+00
\N	257	cpu_usage_percent	4.485087719308879	percent	cpu	2026-02-24 02:55:31.639+00
\N	257	cpu_usage_percent	3.9192982456083314	percent	cpu	2026-02-24 02:56:31.639+00
\N	248	cpu_usage_percent	2.3969298244960697	percent	cpu	2026-02-24 03:17:27.824+00
\N	133	cpu_usage_percent	2.0140350877160387	percent	cpu	2026-02-24 05:08:54.766+00
\N	252	cpu_usage_percent	23.854385964948236	percent	\N	2026-02-24 02:35:03.782+00
\N	252	cpu_usage_percent	23.841666666680567	percent	\N	2026-02-24 02:36:03.782+00
\N	252	cpu_usage_percent	25.69912280699468	percent	\N	2026-02-24 02:37:03.782+00
\N	252	cpu_usage_percent	25.603508771940454	percent	\N	2026-02-24 02:38:03.782+00
\N	252	cpu_usage_percent	25.212280701809135	percent	\N	2026-02-24 02:39:03.782+00
\N	252	cpu_usage_percent	25.3118421052166	percent	\N	2026-02-24 02:40:03.782+00
\N	252	cpu_usage_percent	24.389912280654386	percent	\N	2026-02-24 02:41:03.782+00
\N	252	cpu_usage_percent	22.92324561407186	percent	\N	2026-02-24 02:42:03.782+00
\N	252	cpu_usage_percent	23.078508771906954	percent	\N	2026-02-24 02:43:03.782+00
\N	252	cpu_usage_percent	23.23333333336275	percent	\N	2026-02-24 02:44:03.782+00
\N	252	cpu_usage_percent	23.33245614035006	percent	\N	2026-02-24 02:45:03.782+00
\N	252	cpu_usage_percent	23.707456140362325	percent	\N	2026-02-24 02:46:03.782+00
\N	252	cpu_usage_percent	23.6249999999755	percent	\N	2026-02-24 02:47:03.782+00
\N	252	cpu_usage_percent	23.884649122820107	percent	cpu	2026-02-24 02:48:23.521+00
\N	252	cpu_usage_percent	23.765789473678495	percent	cpu	2026-02-24 02:49:23.521+00
\N	252	cpu_usage_percent	23.48815789476872	percent	cpu	2026-02-24 02:50:23.521+00
\N	252	cpu_usage_percent	23.682894736810255	percent	cpu	2026-02-24 02:51:23.521+00
\N	252	cpu_usage_percent	23.644736842129774	percent	cpu	2026-02-24 02:52:23.521+00
\N	252	cpu_usage_percent	23.508333333343145	percent	cpu	2026-02-24 02:53:23.521+00
\N	252	cpu_usage_percent	23.42982456139127	percent	cpu	2026-02-24 02:54:23.521+00
\N	257	cpu_usage_percent	4.31929824561324	percent	\N	2026-02-24 02:35:03.843+00
\N	257	cpu_usage_percent	3.986842105259086	percent	\N	2026-02-24 02:36:03.843+00
\N	257	cpu_usage_percent	3.958771929835194	percent	\N	2026-02-24 02:37:03.843+00
\N	257	cpu_usage_percent	4.003508771920849	percent	\N	2026-02-24 02:38:03.843+00
\N	257	cpu_usage_percent	4.435964912306858	percent	\N	2026-02-24 02:39:03.843+00
\N	257	cpu_usage_percent	5.007017543866198	percent	\N	2026-02-24 02:40:03.843+00
\N	257	cpu_usage_percent	5.348245614032649	percent	\N	2026-02-24 02:41:03.843+00
\N	257	cpu_usage_percent	5.463157894759732	percent	\N	2026-02-24 02:42:03.843+00
\N	257	cpu_usage_percent	5.289473684235048	percent	\N	2026-02-24 02:43:03.843+00
\N	257	cpu_usage_percent	4.852631578932673	percent	\N	2026-02-24 02:44:03.843+00
\N	257	cpu_usage_percent	4.352631578936766	percent	\N	2026-02-24 02:45:03.843+00
\N	257	cpu_usage_percent	3.9850877192925367	percent	\N	2026-02-24 02:46:03.843+00
\N	257	cpu_usage_percent	4.013157894716429	percent	\N	2026-02-24 02:47:03.843+00
\N	252	cpu_usage_percent	23.551315789482672	percent	cpu	2026-02-24 02:55:23.521+00
\N	252	cpu_usage_percent	23.162719298260328	percent	cpu	2026-02-24 02:56:23.521+00
\N	252	cpu_usage_percent	23.381578947372518	percent	cpu	2026-02-24 02:57:23.521+00
\N	252	cpu_usage_percent	23.38201754387437	percent	cpu	2026-02-24 02:58:23.521+00
\N	252	cpu_usage_percent	23.342105263166076	percent	cpu	2026-02-24 02:59:23.521+00
\N	252	cpu_usage_percent	23.864035087723394	percent	cpu	2026-02-24 03:00:23.521+00
\N	248	cpu_usage_percent	2.4478070175258893	percent	cpu	2026-02-24 03:18:27.824+00
\N	260	cpu_usage_percent	25.607894736836386	percent	\N	2026-02-24 02:35:03.915+00
\N	260	cpu_usage_percent	25.579824561392087	percent	\N	2026-02-24 02:36:03.915+00
\N	260	cpu_usage_percent	25.513925438556868	percent	\N	2026-02-24 02:37:03.915+00
\N	260	cpu_usage_percent	25.577302631572834	percent	\N	2026-02-24 02:38:03.915+00
\N	260	cpu_usage_percent	25.513267543814308	percent	\N	2026-02-24 02:39:03.915+00
\N	260	cpu_usage_percent	25.6139254385683	percent	\N	2026-02-24 02:40:03.915+00
\N	260	cpu_usage_percent	25.641118421100842	percent	\N	2026-02-24 02:41:03.915+00
\N	260	cpu_usage_percent	25.65778508772175	percent	\N	2026-02-24 02:42:03.915+00
\N	260	cpu_usage_percent	25.63914473687315	percent	\N	2026-02-24 02:43:03.915+00
\N	260	cpu_usage_percent	25.596820175445544	percent	\N	2026-02-24 02:44:03.915+00
\N	260	cpu_usage_percent	25.562280701736825	percent	\N	2026-02-24 02:45:03.915+00
\N	260	cpu_usage_percent	25.476206140347614	percent	\N	2026-02-24 02:46:03.915+00
\N	260	cpu_usage_percent	25.498684210510802	percent	\N	2026-02-24 02:47:03.915+00
\N	248	cpu_usage_percent	2.7271929825247696	percent	cpu	2026-02-24 03:19:27.824+00
\N	248	cpu_usage_percent	2.6978070175340747	percent	cpu	2026-02-24 03:20:27.824+00
\N	236	cpu_usage_percent	1.487719298324052	percent	cpu	2026-02-24 03:48:33.805+00
\N	236	cpu_usage_percent	1.5052631579078195	percent	cpu	2026-02-24 03:49:33.805+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	cpu	2026-02-24 03:50:33.805+00
\N	236	cpu_usage_percent	1.7578947367636886	percent	cpu	2026-02-24 03:51:33.805+00
\N	236	cpu_usage_percent	1.7368421053285346	percent	cpu	2026-02-24 03:52:33.805+00
\N	133	cpu_usage_percent	0.5315789473733332	percent	cpu	2026-02-24 02:42:52.28+00
\N	133	cpu_usage_percent	0.5206140351334767	percent	cpu	2026-02-24 02:43:52.28+00
\N	133	cpu_usage_percent	0.42982456139534975	percent	cpu	2026-02-24 02:44:52.28+00
\N	133	cpu_usage_percent	0.4245614034957157	percent	cpu	2026-02-24 02:45:52.28+00
\N	133	cpu_usage_percent	0.4250000000179881	percent	cpu	2026-02-24 02:46:52.28+00
\N	133	cpu_usage_percent	0.4184210526332208	percent	cpu	2026-02-24 02:47:52.28+00
\N	133	cpu_usage_percent	0.3302631578653461	percent	cpu	2026-02-24 02:48:52.28+00
\N	133	cpu_usage_percent	0.5109649122970552	percent	cpu	2026-02-24 02:49:52.28+00
\N	133	cpu_usage_percent	0.5192982456075157	percent	cpu	2026-02-24 02:50:52.28+00
\N	133	cpu_usage_percent	0.6894736841991005	percent	cpu	2026-02-24 02:51:52.28+00
\N	133	cpu_usage_percent	0.6938596490950459	percent	cpu	2026-02-24 02:52:52.28+00
\N	133	cpu_usage_percent	0.6153508771635785	percent	cpu	2026-02-24 02:53:52.28+00
\N	133	cpu_usage_percent	0.604385964923722	percent	cpu	2026-02-24 02:54:52.28+00
\N	236	cpu_usage_percent	1.7298245614623369	percent	cpu	2026-02-24 03:53:33.805+00
\N	236	cpu_usage_percent	1.7403508773433174	percent	cpu	2026-02-24 03:54:33.805+00
\N	236	cpu_usage_percent	1.607017543885803	percent	cpu	2026-02-24 03:55:33.805+00
\N	236	cpu_usage_percent	1.4771929824430714	percent	cpu	2026-02-24 03:56:33.805+00
\N	236	cpu_usage_percent	1.3052631579666354	percent	cpu	2026-02-24 03:57:33.805+00
\N	236	cpu_usage_percent	1.4491228069783375	percent	cpu	2026-02-24 03:58:33.805+00
\N	236	cpu_usage_percent	1.470175438576888	percent	cpu	2026-02-24 03:59:33.805+00
\N	236	cpu_usage_percent	1.4807017544578684	percent	cpu	2026-02-24 04:00:33.805+00
\N	133	cpu_usage_percent	1.3877192982309197	percent	cpu	2026-02-24 05:09:54.766+00
\N	133	cpu_usage_percent	0.3486842104936443	percent	cpu	2026-02-24 05:10:54.766+00
\N	133	cpu_usage_percent	0.4249999999771319	percent	cpu	2026-02-24 05:28:59.549+00
\N	133	cpu_usage_percent	0.4372807017838056	percent	cpu	2026-02-24 05:29:59.549+00
\N	133	cpu_usage_percent	0.42236842100689387	percent	cpu	2026-02-24 05:30:59.549+00
\N	133	cpu_usage_percent	0.43815789474666644	percent	cpu	2026-02-24 05:31:59.549+00
\N	133	cpu_usage_percent	0.5052631579159907	percent	cpu	2026-02-24 05:32:59.549+00
\N	260	cpu_usage_percent	25.66239035088904	percent	cpu	2026-02-24 02:44:31.875+00
\N	260	cpu_usage_percent	25.532127192985314	percent	cpu	2026-02-24 02:45:31.875+00
\N	260	cpu_usage_percent	25.5070175438519	percent	cpu	2026-02-24 02:46:31.875+00
\N	260	cpu_usage_percent	25.556359649135473	percent	cpu	2026-02-24 02:47:31.875+00
\N	260	cpu_usage_percent	25.507785087694387	percent	cpu	2026-02-24 02:48:31.875+00
\N	260	cpu_usage_percent	25.56633771929212	percent	cpu	2026-02-24 02:49:31.875+00
\N	260	cpu_usage_percent	25.54627192982784	percent	cpu	2026-02-24 02:50:31.875+00
\N	260	cpu_usage_percent	26.549671052601767	percent	cpu	2026-02-24 02:51:31.875+00
\N	260	cpu_usage_percent	32.9675438596863	percent	cpu	2026-02-24 02:52:31.875+00
\N	260	cpu_usage_percent	32.97489035090334	percent	cpu	2026-02-24 02:53:31.875+00
\N	260	cpu_usage_percent	33.0422149123236	percent	cpu	2026-02-24 02:54:31.875+00
\N	260	cpu_usage_percent	33.17697368421298	percent	cpu	2026-02-24 02:55:31.875+00
\N	260	cpu_usage_percent	30.737609649107696	percent	cpu	2026-02-24 02:56:31.875+00
\N	133	cpu_usage_percent	0.5184210526446549	percent	cpu	2026-02-24 05:33:59.549+00
\N	133	cpu_usage_percent	0.5105263157747686	percent	cpu	2026-02-24 05:34:59.549+00
\N	133	cpu_usage_percent	0.508333333326803	percent	cpu	2026-02-24 05:35:59.549+00
\N	133	cpu_usage_percent	0.5192982455666737	percent	cpu	2026-02-24 05:36:59.549+00
\N	133	cpu_usage_percent	0.41973684211833984	percent	cpu	2026-02-24 05:37:59.549+00
\N	133	cpu_usage_percent	0.42236842108859207	percent	cpu	2026-02-24 05:38:59.549+00
\N	248	cpu_usage_percent	2.557456140332917	percent	cpu	2026-02-24 03:28:30.906+00
\N	248	cpu_usage_percent	2.606140350914785	percent	cpu	2026-02-24 03:29:30.906+00
\N	248	cpu_usage_percent	2.6249999999428297	percent	cpu	2026-02-24 03:30:30.906+00
\N	236	cpu_usage_percent	1.7929824562580023	percent	cpu	2026-02-24 02:42:52.535+00
\N	236	cpu_usage_percent	1.5578947368225045	percent	cpu	2026-02-24 02:43:52.535+00
\N	236	cpu_usage_percent	1.494736842026839	percent	cpu	2026-02-24 02:44:52.535+00
\N	236	cpu_usage_percent	1.5087719299226023	percent	cpu	2026-02-24 02:45:52.535+00
\N	236	cpu_usage_percent	1.5228070176549693	percent	cpu	2026-02-24 02:46:52.535+00
\N	236	cpu_usage_percent	1.5192982456401865	percent	cpu	2026-02-24 02:47:52.535+00
\N	236	cpu_usage_percent	1.473684210591685	percent	cpu	2026-02-24 02:48:52.535+00
\N	236	cpu_usage_percent	1.9789473684668053	percent	cpu	2026-02-24 02:49:52.535+00
\N	236	cpu_usage_percent	2.0070175439315534	percent	cpu	2026-02-24 02:50:52.535+00
\N	236	cpu_usage_percent	2.3789473683491735	percent	cpu	2026-02-24 02:51:52.535+00
\N	236	cpu_usage_percent	2.4070175438139074	percent	cpu	2026-02-24 02:52:52.535+00
\N	236	cpu_usage_percent	2.235087719174075	percent	cpu	2026-02-24 02:53:52.535+00
\N	236	cpu_usage_percent	1.8877192982064201	percent	cpu	2026-02-24 02:54:52.535+00
\N	248	cpu_usage_percent	2.749122807045339	percent	cpu	2026-02-24 03:31:30.906+00
\N	248	cpu_usage_percent	2.784210526294558	percent	cpu	2026-02-24 03:32:30.906+00
\N	248	cpu_usage_percent	2.774122806976706	percent	cpu	2026-02-24 03:33:30.906+00
\N	248	cpu_usage_percent	2.756140350870666	percent	cpu	2026-02-24 03:34:30.906+00
\N	248	cpu_usage_percent	2.6105263158107306	percent	cpu	2026-02-24 03:35:30.906+00
\N	257	cpu_usage_percent	4.1912280701779	percent	cpu	2026-02-24 02:48:23.764+00
\N	257	cpu_usage_percent	4.512280701749489	percent	cpu	2026-02-24 02:49:23.764+00
\N	257	cpu_usage_percent	5.029824561410862	percent	cpu	2026-02-24 02:50:23.764+00
\N	257	cpu_usage_percent	5.714912280673161	percent	cpu	2026-02-24 02:51:23.764+00
\N	257	cpu_usage_percent	5.749122807020825	percent	cpu	2026-02-24 02:52:23.764+00
\N	257	cpu_usage_percent	5.450877192993914	percent	cpu	2026-02-24 02:53:23.764+00
\N	257	cpu_usage_percent	4.902631578979239	percent	cpu	2026-02-24 02:54:23.764+00
\N	257	cpu_usage_percent	4.546491228035876	percent	cpu	2026-02-24 02:55:23.764+00
\N	257	cpu_usage_percent	3.958771929814773	percent	cpu	2026-02-24 02:56:23.764+00
\N	257	cpu_usage_percent	3.956140350864942	percent	cpu	2026-02-24 02:57:23.764+00
\N	257	cpu_usage_percent	4.9052631578882	percent	cpu	2026-02-24 02:58:23.764+00
\N	257	cpu_usage_percent	4.986842105271336	percent	cpu	2026-02-24 02:59:23.764+00
\N	257	cpu_usage_percent	5.940350877190539	percent	cpu	2026-02-24 03:00:23.764+00
\N	248	cpu_usage_percent	2.500000000040856	percent	cpu	2026-02-24 03:36:30.906+00
\N	248	cpu_usage_percent	2.562719298232551	percent	cpu	2026-02-24 03:37:30.906+00
\N	248	cpu_usage_percent	2.571491228065284	percent	cpu	2026-02-24 03:38:30.906+00
\N	252	cpu_usage_percent	23.906578947361083	percent	cpu	2026-02-24 03:08:28.075+00
\N	252	cpu_usage_percent	23.885087719321945	percent	cpu	2026-02-24 03:09:28.075+00
\N	252	cpu_usage_percent	23.911842105219876	percent	cpu	2026-02-24 03:10:28.075+00
\N	252	cpu_usage_percent	24.144736842105274	percent	cpu	2026-02-24 03:11:28.075+00
\N	252	cpu_usage_percent	24.361842105250915	percent	cpu	2026-02-24 03:12:28.075+00
\N	252	cpu_usage_percent	24.23070175438434	percent	cpu	2026-02-24 03:13:28.075+00
\N	252	cpu_usage_percent	24.107456140346812	percent	cpu	2026-02-24 03:14:28.075+00
\N	252	cpu_usage_percent	24.15877192983764	percent	cpu	2026-02-24 03:15:28.075+00
\N	252	cpu_usage_percent	24.21929824558137	percent	cpu	2026-02-24 03:16:28.075+00
\N	252	cpu_usage_percent	24.717982456173843	percent	cpu	2026-02-24 03:17:28.075+00
\N	252	cpu_usage_percent	24.823245614044083	percent	cpu	2026-02-24 03:18:28.075+00
\N	252	cpu_usage_percent	25.020614035076292	percent	cpu	2026-02-24 03:19:28.075+00
\N	252	cpu_usage_percent	24.707456140333733	percent	cpu	2026-02-24 03:20:28.075+00
\N	248	cpu_usage_percent	2.5649122806396747	percent	cpu	2026-02-24 03:39:30.906+00
\N	248	cpu_usage_percent	2.51008771927701	percent	cpu	2026-02-24 03:40:30.906+00
\N	236	cpu_usage_percent	2.066666666712422	percent	cpu	2026-02-24 04:08:36.818+00
\N	248	cpu_usage_percent	2.3219298246202413	percent	cpu	2026-02-24 02:42:52.809+00
\N	248	cpu_usage_percent	2.4723684210166965	percent	cpu	2026-02-24 02:43:52.809+00
\N	248	cpu_usage_percent	2.479385964964578	percent	cpu	2026-02-24 02:44:52.809+00
\N	248	cpu_usage_percent	2.628947368439043	percent	cpu	2026-02-24 02:45:52.809+00
\N	248	cpu_usage_percent	2.724122807032259	percent	cpu	2026-02-24 02:46:52.809+00
\N	248	cpu_usage_percent	2.8280701754582083	percent	cpu	2026-02-24 02:47:52.809+00
\N	248	cpu_usage_percent	2.7478070175602056	percent	cpu	2026-02-24 02:48:52.809+00
\N	248	cpu_usage_percent	2.843859649197981	percent	cpu	2026-02-24 02:49:52.809+00
\N	248	cpu_usage_percent	2.7644736840994284	percent	cpu	2026-02-24 02:50:52.809+00
\N	248	cpu_usage_percent	2.763157894777706	percent	cpu	2026-02-24 02:51:52.809+00
\N	248	cpu_usage_percent	2.642105263208549	percent	cpu	2026-02-24 02:52:52.809+00
\N	248	cpu_usage_percent	2.384210526371348	percent	cpu	2026-02-24 02:53:52.809+00
\N	248	cpu_usage_percent	2.430701754423552	percent	cpu	2026-02-24 02:54:52.809+00
\N	236	cpu_usage_percent	2.10526315789474	percent	cpu	2026-02-24 04:09:36.818+00
\N	236	cpu_usage_percent	2.2315789474860708	percent	cpu	2026-02-24 04:10:36.818+00
\N	236	cpu_usage_percent	2.4350877192786555	percent	cpu	2026-02-24 04:11:36.818+00
\N	236	cpu_usage_percent	2.6421052632494053	percent	cpu	2026-02-24 04:12:36.818+00
\N	236	cpu_usage_percent	2.6421052632494053	percent	cpu	2026-02-24 04:13:36.818+00
\N	236	cpu_usage_percent	2.614035087621275	percent	cpu	2026-02-24 04:14:36.818+00
\N	236	cpu_usage_percent	1.8421052631579045	percent	cpu	2026-02-24 04:15:36.818+00
\N	236	cpu_usage_percent	1.4631578947107045	percent	cpu	2026-02-24 04:16:36.818+00
\N	236	cpu_usage_percent	1.4105263157960195	percent	cpu	2026-02-24 04:17:36.818+00
\N	236	cpu_usage_percent	1.2421052631709841	percent	cpu	2026-02-24 04:18:36.818+00
\N	236	cpu_usage_percent	1.3824561403312714	percent	cpu	2026-02-24 04:19:36.818+00
\N	236	cpu_usage_percent	1.3929824560488697	percent	cpu	2026-02-24 04:20:36.818+00
\N	133	cpu_usage_percent	0.42017543859977025	percent	cpu	2026-02-24 05:39:59.549+00
\N	133	cpu_usage_percent	0.4254385965402463	percent	cpu	2026-02-24 05:40:59.549+00
\N	133	cpu_usage_percent	0.4166666666258294	percent	cpu	2026-02-24 05:59:04.125+00
\N	133	cpu_usage_percent	0.41140350872619535	percent	cpu	2026-02-24 06:00:04.125+00
\N	133	cpu_usage_percent	0.4245614035365577	percent	cpu	2026-02-24 06:01:04.125+00
\N	133	cpu_usage_percent	0.40263157897516066	percent	cpu	2026-02-24 06:02:04.125+00
\N	260	cpu_usage_percent	25.507785087694387	percent	cpu	2026-02-24 02:48:24.002+00
\N	260	cpu_usage_percent	25.56633771929212	percent	cpu	2026-02-24 02:49:24.002+00
\N	260	cpu_usage_percent	25.54627192982784	percent	cpu	2026-02-24 02:50:24.002+00
\N	260	cpu_usage_percent	26.549671052601767	percent	cpu	2026-02-24 02:51:24.002+00
\N	260	cpu_usage_percent	32.9675438596863	percent	cpu	2026-02-24 02:52:24.002+00
\N	260	cpu_usage_percent	32.97489035090334	percent	cpu	2026-02-24 02:53:24.002+00
\N	260	cpu_usage_percent	33.0422149123236	percent	cpu	2026-02-24 02:54:24.002+00
\N	260	cpu_usage_percent	33.17697368421298	percent	cpu	2026-02-24 02:55:24.002+00
\N	133	cpu_usage_percent	0.5206140350517927	percent	cpu	2026-02-24 06:03:04.125+00
\N	133	cpu_usage_percent	0.5285087719625068	percent	cpu	2026-02-24 06:04:04.125+00
\N	260	cpu_usage_percent	30.737609649107696	percent	cpu	2026-02-24 02:56:24.002+00
\N	260	cpu_usage_percent	26.0246710526132	percent	cpu	2026-02-24 02:57:24.002+00
\N	260	cpu_usage_percent	26.0995614034708	percent	cpu	2026-02-24 02:58:24.002+00
\N	260	cpu_usage_percent	26.088596491241148	percent	cpu	2026-02-24 02:59:24.002+00
\N	260	cpu_usage_percent	26.201644736820057	percent	cpu	2026-02-24 03:00:24.002+00
\N	133	cpu_usage_percent	0.5241228070665755	percent	cpu	2026-02-24 06:05:04.125+00
\N	133	cpu_usage_percent	0.5219298244960555	percent	cpu	2026-02-24 06:06:04.125+00
\N	133	cpu_usage_percent	0.5302631578882142	percent	cpu	2026-02-24 06:07:04.125+00
\N	133	cpu_usage_percent	0.4074561403525223	percent	cpu	2026-02-24 06:08:04.125+00
\N	248	cpu_usage_percent	2.3657894737021934	percent	cpu	2026-02-24 03:48:34.063+00
\N	248	cpu_usage_percent	2.2741228069195216	percent	cpu	2026-02-24 03:49:34.063+00
\N	252	cpu_usage_percent	23.196491228044863	percent	cpu	2026-02-24 02:42:53.217+00
\N	252	cpu_usage_percent	23.35175438594122	percent	cpu	2026-02-24 02:43:53.217+00
\N	252	cpu_usage_percent	23.389035087801815	percent	cpu	2026-02-24 02:44:53.217+00
\N	252	cpu_usage_percent	23.851754385977998	percent	cpu	2026-02-24 02:45:53.217+00
\N	252	cpu_usage_percent	23.87631578942795	percent	cpu	2026-02-24 02:46:53.217+00
\N	252	cpu_usage_percent	23.939473684264456	percent	cpu	2026-02-24 02:47:53.217+00
\N	252	cpu_usage_percent	23.715350877191355	percent	cpu	2026-02-24 02:48:53.217+00
\N	252	cpu_usage_percent	23.689473684235864	percent	cpu	2026-02-24 02:49:53.217+00
\N	252	cpu_usage_percent	23.515789473690745	percent	cpu	2026-02-24 02:50:53.217+00
\N	252	cpu_usage_percent	23.820175438600586	percent	cpu	2026-02-24 02:51:53.217+00
\N	252	cpu_usage_percent	23.689473684195008	percent	cpu	2026-02-24 02:52:53.217+00
\N	252	cpu_usage_percent	23.549999999977132	percent	cpu	2026-02-24 02:53:53.217+00
\N	252	cpu_usage_percent	23.55833333334887	percent	cpu	2026-02-24 02:54:53.217+00
\N	248	cpu_usage_percent	2.206578947309609	percent	cpu	2026-02-24 03:50:34.063+00
\N	248	cpu_usage_percent	2.2723684210755266	percent	cpu	2026-02-24 03:51:34.063+00
\N	248	cpu_usage_percent	2.324122807068207	percent	cpu	2026-02-24 03:52:34.063+00
\N	248	cpu_usage_percent	2.3131578947874942	percent	cpu	2026-02-24 03:53:34.063+00
\N	248	cpu_usage_percent	2.3350877192672215	percent	cpu	2026-02-24 03:54:34.063+00
\N	248	cpu_usage_percent	2.3017543860253795	percent	cpu	2026-02-24 03:55:34.063+00
\N	248	cpu_usage_percent	2.176754386082564	percent	cpu	2026-02-24 03:56:34.063+00
\N	248	cpu_usage_percent	2.0368421051994403	percent	cpu	2026-02-24 03:57:34.063+00
\N	248	cpu_usage_percent	2.127192982496993	percent	cpu	2026-02-24 03:58:34.063+00
\N	257	cpu_usage_percent	4.056140350855969	percent	cpu	2026-02-24 03:08:28.339+00
\N	257	cpu_usage_percent	4.454385964894314	percent	cpu	2026-02-24 03:09:28.339+00
\N	257	cpu_usage_percent	4.792105263148102	percent	cpu	2026-02-24 03:10:28.339+00
\N	257	cpu_usage_percent	5.657894736821689	percent	cpu	2026-02-24 03:11:28.339+00
\N	257	cpu_usage_percent	5.658771929825392	percent	cpu	2026-02-24 03:12:28.339+00
\N	257	cpu_usage_percent	5.392105263175878	percent	cpu	2026-02-24 03:13:28.339+00
\N	257	cpu_usage_percent	5.031578947356991	percent	cpu	2026-02-24 03:14:28.339+00
\N	257	cpu_usage_percent	4.2526315789457385	percent	cpu	2026-02-24 03:15:28.339+00
\N	257	cpu_usage_percent	3.936842105253362	percent	cpu	2026-02-24 03:16:28.339+00
\N	257	cpu_usage_percent	3.944736842082392	percent	cpu	2026-02-24 03:17:28.339+00
\N	257	cpu_usage_percent	4.06929824562549	percent	cpu	2026-02-24 03:18:28.339+00
\N	257	cpu_usage_percent	4.491228070171374	percent	cpu	2026-02-24 03:19:28.339+00
\N	257	cpu_usage_percent	5.086842105262363	percent	cpu	2026-02-24 03:20:28.339+00
\N	248	cpu_usage_percent	2.105263157976438	percent	cpu	2026-02-24 03:59:34.063+00
\N	252	cpu_usage_percent	24.13377192988584	percent	cpu	2026-02-24 03:28:31.152+00
\N	252	cpu_usage_percent	24.307456140287968	percent	cpu	2026-02-24 03:29:31.152+00
\N	252	cpu_usage_percent	24.372368421050197	percent	cpu	2026-02-24 03:30:31.152+00
\N	252	cpu_usage_percent	24.490350877188092	percent	cpu	2026-02-24 03:31:31.152+00
\N	252	cpu_usage_percent	24.502192982492915	percent	cpu	2026-02-24 03:32:31.152+00
\N	252	cpu_usage_percent	24.667543859645875	percent	cpu	2026-02-24 03:33:31.152+00
\N	252	cpu_usage_percent	24.49999999998367	percent	cpu	2026-02-24 03:34:31.152+00
\N	252	cpu_usage_percent	24.20219298247902	percent	cpu	2026-02-24 03:35:31.152+00
\N	133	cpu_usage_percent	0.4263157893397107	percent	cpu	2026-02-24 02:58:25.776+00
\N	133	cpu_usage_percent	0.3179824561403706	percent	cpu	2026-02-24 02:59:25.776+00
\N	133	cpu_usage_percent	0.5412280701689127	percent	cpu	2026-02-24 03:00:25.776+00
\N	133	cpu_usage_percent	0.6736842105410403	percent	cpu	2026-02-24 03:01:25.776+00
\N	133	cpu_usage_percent	0.6539473684275947	percent	cpu	2026-02-24 03:02:25.776+00
\N	133	cpu_usage_percent	0.6644736841451788	percent	cpu	2026-02-24 03:03:25.776+00
\N	257	cpu_usage_percent	5.359649122815185	percent	cpu	2026-02-24 02:42:53.485+00
\N	257	cpu_usage_percent	4.857894736811886	percent	cpu	2026-02-24 02:43:53.485+00
\N	257	cpu_usage_percent	4.414035087725026	percent	cpu	2026-02-24 02:44:53.485+00
\N	257	cpu_usage_percent	4.070175438608757	percent	cpu	2026-02-24 02:45:53.485+00
\N	257	cpu_usage_percent	4.0052631578873985	percent	cpu	2026-02-24 02:46:53.485+00
\N	257	cpu_usage_percent	4.0192982456197655	percent	cpu	2026-02-24 02:47:53.485+00
\N	257	cpu_usage_percent	4.071929824554871	percent	cpu	2026-02-24 02:48:53.485+00
\N	257	cpu_usage_percent	4.875438596497773	percent	cpu	2026-02-24 02:49:53.485+00
\N	257	cpu_usage_percent	5.237719298242354	percent	cpu	2026-02-24 02:50:53.485+00
\N	257	cpu_usage_percent	5.778947368431673	percent	cpu	2026-02-24 02:51:53.485+00
\N	257	cpu_usage_percent	5.6342105263345985	percent	cpu	2026-02-24 02:52:53.485+00
\N	257	cpu_usage_percent	5.096491228078364	percent	cpu	2026-02-24 02:53:53.485+00
\N	257	cpu_usage_percent	4.758771929824562	percent	cpu	2026-02-24 02:54:53.485+00
\N	133	cpu_usage_percent	0.5991228069424039	percent	cpu	2026-02-24 03:04:25.776+00
\N	133	cpu_usage_percent	0.5302631579699124	percent	cpu	2026-02-24 03:05:25.776+00
\N	133	cpu_usage_percent	0.43771929826523603	percent	cpu	2026-02-24 03:06:25.776+00
\N	133	cpu_usage_percent	0.43728070174296363	percent	cpu	2026-02-24 03:07:25.776+00
\N	133	cpu_usage_percent	0.44122807011662246	percent	cpu	2026-02-24 03:08:25.776+00
\N	133	cpu_usage_percent	0.43903508775035505	percent	cpu	2026-02-24 03:09:25.776+00
\N	133	cpu_usage_percent	0.5043859648714459	percent	cpu	2026-02-24 03:10:25.776+00
\N	252	cpu_usage_percent	23.97192982456386	percent	cpu	2026-02-24 03:36:31.152+00
\N	252	cpu_usage_percent	24.854824561401074	percent	cpu	2026-02-24 03:37:31.152+00
\N	252	cpu_usage_percent	24.877192982464308	percent	cpu	2026-02-24 03:38:31.152+00
\N	252	cpu_usage_percent	24.989912280682162	percent	cpu	2026-02-24 03:39:31.152+00
\N	252	cpu_usage_percent	25.17675438595593	percent	cpu	2026-02-24 03:40:31.152+00
\N	248	cpu_usage_percent	2.2736842104789474	percent	cpu	2026-02-24 04:00:34.063+00
\N	133	cpu_usage_percent	0.3043859648894198	percent	cpu	2026-02-24 06:09:04.125+00
\N	133	cpu_usage_percent	0.4166666666666714	percent	cpu	2026-02-24 06:10:04.125+00
\N	236	cpu_usage_percent	1.4421052632755504	percent	cpu	2026-02-24 04:38:41.587+00
\N	236	cpu_usage_percent	1.3508771930151369	percent	cpu	2026-02-24 04:39:41.587+00
\N	236	cpu_usage_percent	1.3614035087327352	percent	cpu	2026-02-24 04:40:41.587+00
\N	236	cpu_usage_percent	1.487719298324052	percent	cpu	2026-02-24 04:41:41.587+00
\N	236	cpu_usage_percent	1.673684210532869	percent	cpu	2026-02-24 04:42:41.587+00
\N	236	cpu_usage_percent	1.6982456139828201	percent	cpu	2026-02-24 04:43:41.587+00
\N	236	cpu_usage_percent	1.5789473684210549	percent	cpu	2026-02-24 04:44:41.587+00
\N	133	cpu_usage_percent	0.42894736839164693	percent	cpu	2026-02-24 06:11:04.125+00
\N	236	cpu_usage_percent	1.6877192981018396	percent	cpu	2026-02-24 04:45:41.587+00
\N	236	cpu_usage_percent	1.456140350844521	percent	cpu	2026-02-24 04:46:41.587+00
\N	236	cpu_usage_percent	1.403508771929836	percent	cpu	2026-02-24 04:47:41.587+00
\N	236	cpu_usage_percent	1.3901656830347662	percent	cpu	2026-02-24 04:48:41.587+00
\N	236	cpu_usage_percent	1.2421052631709841	percent	cpu	2026-02-24 04:49:41.587+00
\N	236	cpu_usage_percent	1.3649122807475038	percent	cpu	2026-02-24 04:50:41.587+00
\N	133	cpu_usage_percent	0.7657894736417461	percent	cpu	2026-02-24 06:29:09.021+00
\N	133	cpu_usage_percent	0.6631578947009018	percent	cpu	2026-02-24 06:30:09.021+00
\N	133	cpu_usage_percent	0.8122807018164764	percent	cpu	2026-02-24 06:31:09.021+00
\N	133	cpu_usage_percent	0.4925438597095848	percent	cpu	2026-02-24 06:32:09.021+00
\N	133	cpu_usage_percent	0.4719298245516086	percent	cpu	2026-02-24 06:33:09.021+00
\N	133	cpu_usage_percent	0.7206140349929626	percent	cpu	2026-02-24 06:34:09.021+00
\N	133	cpu_usage_percent	0.6105263157862169	percent	cpu	2026-02-24 06:35:09.021+00
\N	260	cpu_usage_percent	25.61228070174255	percent	cpu	2026-02-24 03:08:28.595+00
\N	260	cpu_usage_percent	25.624561403467524	percent	cpu	2026-02-24 03:09:28.595+00
\N	260	cpu_usage_percent	25.652083333320277	percent	cpu	2026-02-24 03:10:28.595+00
\N	260	cpu_usage_percent	25.63914473687315	percent	cpu	2026-02-24 02:42:53.715+00
\N	260	cpu_usage_percent	25.596820175445544	percent	cpu	2026-02-24 02:43:53.715+00
\N	260	cpu_usage_percent	25.562280701736825	percent	cpu	2026-02-24 02:44:53.715+00
\N	260	cpu_usage_percent	25.476206140347614	percent	cpu	2026-02-24 02:45:53.715+00
\N	260	cpu_usage_percent	25.498684210510802	percent	cpu	2026-02-24 02:46:53.715+00
\N	260	cpu_usage_percent	25.481688596426693	percent	cpu	2026-02-24 02:47:53.715+00
\N	260	cpu_usage_percent	25.503618421069802	percent	cpu	2026-02-24 02:48:53.715+00
\N	260	cpu_usage_percent	25.55427631579765	percent	cpu	2026-02-24 02:49:53.715+00
\N	260	cpu_usage_percent	25.51041666665442	percent	cpu	2026-02-24 02:50:53.715+00
\N	260	cpu_usage_percent	29.96282894738232	percent	cpu	2026-02-24 02:51:53.715+00
\N	260	cpu_usage_percent	32.96644736842147	percent	cpu	2026-02-24 02:52:53.715+00
\N	260	cpu_usage_percent	33.04221491230318	percent	cpu	2026-02-24 02:53:53.715+00
\N	260	cpu_usage_percent	33.0517543859886	percent	cpu	2026-02-24 02:54:53.715+00
\N	260	cpu_usage_percent	25.589144736806162	percent	cpu	2026-02-24 03:11:28.595+00
\N	260	cpu_usage_percent	25.61644736838757	percent	cpu	2026-02-24 03:12:28.595+00
\N	260	cpu_usage_percent	25.557236842098334	percent	cpu	2026-02-24 03:13:28.595+00
\N	260	cpu_usage_percent	25.604824561425573	percent	cpu	2026-02-24 03:14:28.595+00
\N	260	cpu_usage_percent	25.507785087714808	percent	cpu	2026-02-24 03:15:28.595+00
\N	260	cpu_usage_percent	25.555372806980785	percent	cpu	2026-02-24 03:16:28.595+00
\N	236	cpu_usage_percent	1.4666666667255015	percent	cpu	2026-02-24 02:58:26.048+00
\N	236	cpu_usage_percent	1.2877192983828678	percent	cpu	2026-02-24 02:59:26.048+00
\N	236	cpu_usage_percent	1.6140350877519865	percent	cpu	2026-02-24 03:00:26.048+00
\N	236	cpu_usage_percent	1.849122807024088	percent	cpu	2026-02-24 03:01:26.048+00
\N	236	cpu_usage_percent	1.8736842106374212	percent	cpu	2026-02-24 03:02:26.048+00
\N	236	cpu_usage_percent	1.8701754384592562	percent	cpu	2026-02-24 03:03:26.048+00
\N	236	cpu_usage_percent	1.7473684210461045	percent	cpu	2026-02-24 03:04:26.048+00
\N	236	cpu_usage_percent	1.5438596490901375	percent	cpu	2026-02-24 03:05:26.048+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	cpu	2026-02-24 03:06:26.048+00
\N	236	cpu_usage_percent	1.456140350844521	percent	cpu	2026-02-24 03:07:26.048+00
\N	236	cpu_usage_percent	1.4526315788297381	percent	cpu	2026-02-24 03:08:26.048+00
\N	236	cpu_usage_percent	1.490536775696654	percent	cpu	2026-02-24 03:09:26.048+00
\N	236	cpu_usage_percent	1.5859649122872526	percent	cpu	2026-02-24 03:10:26.048+00
\N	260	cpu_usage_percent	25.589364035108147	percent	cpu	2026-02-24 03:17:28.595+00
\N	260	cpu_usage_percent	25.595504386011484	percent	cpu	2026-02-24 03:18:28.595+00
\N	260	cpu_usage_percent	25.648135964915966	percent	cpu	2026-02-24 03:19:28.595+00
\N	260	cpu_usage_percent	25.6658991227915	percent	cpu	2026-02-24 03:20:28.595+00
\N	133	cpu_usage_percent	0.7030701755725772	percent	cpu	2026-02-24 06:36:09.021+00
\N	133	cpu_usage_percent	0.7008771930020714	percent	cpu	2026-02-24 06:37:09.021+00
\N	133	cpu_usage_percent	0.6017543860760242	percent	cpu	2026-02-24 06:38:09.021+00
\N	248	cpu_usage_percent	2.3785087719085993	percent	cpu	2026-02-24 04:08:37.067+00
\N	248	cpu_usage_percent	2.316666666598053	percent	cpu	2026-02-24 04:09:37.067+00
\N	248	cpu_usage_percent	2.2956140349994882	percent	cpu	2026-02-24 04:10:37.067+00
\N	248	cpu_usage_percent	2.275877192967755	percent	cpu	2026-02-24 04:11:37.067+00
\N	248	cpu_usage_percent	2.2877192982521564	percent	cpu	2026-02-24 04:12:37.067+00
\N	248	cpu_usage_percent	2.153947368435766	percent	cpu	2026-02-24 04:13:37.067+00
\N	248	cpu_usage_percent	2.1995614034434254	percent	cpu	2026-02-24 04:14:37.067+00
\N	248	cpu_usage_percent	2.188596491244425	percent	cpu	2026-02-24 04:15:37.067+00
\N	248	cpu_usage_percent	2.085964912262739	percent	cpu	2026-02-24 04:16:37.067+00
\N	248	cpu_usage_percent	2.0407894736548116	percent	cpu	2026-02-24 04:17:37.067+00
\N	248	cpu_usage_percent	2.066666666630738	percent	cpu	2026-02-24 04:18:37.067+00
\N	257	cpu_usage_percent	4.150000000004923	percent	cpu	2026-02-24 03:28:31.427+00
\N	257	cpu_usage_percent	4.556140350872312	percent	cpu	2026-02-24 03:29:31.427+00
\N	257	cpu_usage_percent	5.122807017535706	percent	cpu	2026-02-24 03:30:31.427+00
\N	257	cpu_usage_percent	5.729824561388824	percent	cpu	2026-02-24 03:31:31.427+00
\N	257	cpu_usage_percent	5.778070175427985	percent	cpu	2026-02-24 03:32:31.427+00
\N	257	cpu_usage_percent	5.495614035079569	percent	cpu	2026-02-24 03:33:31.427+00
\N	257	cpu_usage_percent	5.100877192974295	percent	cpu	2026-02-24 03:34:31.427+00
\N	257	cpu_usage_percent	4.515789473662167	percent	cpu	2026-02-24 03:35:31.427+00
\N	257	cpu_usage_percent	3.742105263170984	percent	cpu	2026-02-24 03:36:31.427+00
\N	257	cpu_usage_percent	3.892105263126865	percent	cpu	2026-02-24 03:37:31.427+00
\N	257	cpu_usage_percent	4.126315789476948	percent	cpu	2026-02-24 03:38:31.427+00
\N	257	cpu_usage_percent	4.503508771957613	percent	cpu	2026-02-24 03:39:31.427+00
\N	257	cpu_usage_percent	5.021052631598565	percent	cpu	2026-02-24 03:40:31.427+00
\N	252	cpu_usage_percent	23.812719298252972	percent	cpu	2026-02-24 03:48:34.318+00
\N	252	cpu_usage_percent	23.746929824568767	percent	cpu	2026-02-24 03:49:34.318+00
\N	252	cpu_usage_percent	23.85394736838512	percent	cpu	2026-02-24 03:50:34.318+00
\N	252	cpu_usage_percent	24.032456140368865	percent	cpu	2026-02-24 03:51:34.318+00
\N	252	cpu_usage_percent	24.11447368419256	percent	cpu	2026-02-24 03:52:34.318+00
\N	252	cpu_usage_percent	24.114035087731565	percent	cpu	2026-02-24 03:53:34.318+00
\N	248	cpu_usage_percent	2.415789473605784	percent	cpu	2026-02-24 02:58:26.303+00
\N	248	cpu_usage_percent	2.400000000029422	percent	cpu	2026-02-24 02:59:26.303+00
\N	248	cpu_usage_percent	2.657017543903777	percent	cpu	2026-02-24 03:00:26.303+00
\N	248	cpu_usage_percent	2.9622807017560433	percent	cpu	2026-02-24 03:01:26.303+00
\N	248	cpu_usage_percent	2.892105263175864	percent	cpu	2026-02-24 03:02:26.303+00
\N	248	cpu_usage_percent	2.9228070175700225	percent	cpu	2026-02-24 03:03:26.303+00
\N	248	cpu_usage_percent	2.8934210526201554	percent	cpu	2026-02-24 03:04:26.303+00
\N	248	cpu_usage_percent	2.603508771944547	percent	cpu	2026-02-24 03:05:26.303+00
\N	248	cpu_usage_percent	2.4837719298196674	percent	cpu	2026-02-24 03:06:26.303+00
\N	248	cpu_usage_percent	2.4824561403345484	percent	cpu	2026-02-24 03:07:26.303+00
\N	248	cpu_usage_percent	2.1701754385344145	percent	cpu	2026-02-24 04:19:37.067+00
\N	133	cpu_usage_percent	0.4802631578620691	percent	cpu	2026-02-24 06:39:09.021+00
\N	248	cpu_usage_percent	2.44868421048875	percent	cpu	2026-02-24 03:08:26.303+00
\N	248	cpu_usage_percent	2.4833333333382512	percent	cpu	2026-02-24 03:09:26.303+00
\N	248	cpu_usage_percent	2.4964912281077716	percent	cpu	2026-02-24 03:10:26.303+00
\N	252	cpu_usage_percent	24.26754385962053	percent	cpu	2026-02-24 03:54:34.318+00
\N	252	cpu_usage_percent	24.22412280706085	percent	cpu	2026-02-24 03:55:34.318+00
\N	252	cpu_usage_percent	24.15789473687478	percent	cpu	2026-02-24 03:56:34.318+00
\N	252	cpu_usage_percent	24.007456140355785	percent	cpu	2026-02-24 03:57:34.318+00
\N	133	cpu_usage_percent	0.43070175439903835	percent	cpu	2026-02-24 03:18:28.84+00
\N	133	cpu_usage_percent	0.7491228069799689	percent	cpu	2026-02-24 03:19:28.84+00
\N	133	cpu_usage_percent	1.0372807017298982	percent	cpu	2026-02-24 03:20:28.84+00
\N	133	cpu_usage_percent	1.192105263185681	percent	cpu	2026-02-24 03:21:28.84+00
\N	133	cpu_usage_percent	1.1942982455928046	percent	cpu	2026-02-24 03:22:28.84+00
\N	133	cpu_usage_percent	1.2096491227694486	percent	cpu	2026-02-24 03:23:28.84+00
\N	133	cpu_usage_percent	0.6539473685093071	percent	cpu	2026-02-24 03:24:28.84+00
\N	133	cpu_usage_percent	0.5578947368715177	percent	cpu	2026-02-24 03:25:28.84+00
\N	133	cpu_usage_percent	0.43991228075405786	percent	cpu	2026-02-24 03:26:28.84+00
\N	133	cpu_usage_percent	0.45087719299390017	percent	cpu	2026-02-24 03:27:28.84+00
\N	133	cpu_usage_percent	0.4561403508118502	percent	cpu	2026-02-24 03:28:28.84+00
\N	133	cpu_usage_percent	0.46052631578947967	percent	cpu	2026-02-24 03:29:28.84+00
\N	133	cpu_usage_percent	0.5285087718808228	percent	cpu	2026-02-24 03:30:28.84+00
\N	252	cpu_usage_percent	23.986403508777656	percent	cpu	2026-02-24 03:58:34.318+00
\N	252	cpu_usage_percent	24.174122807014285	percent	cpu	2026-02-24 03:59:34.318+00
\N	252	cpu_usage_percent	24.397807017524258	percent	cpu	2026-02-24 04:00:34.318+00
\N	248	cpu_usage_percent	2.3250000000310536	percent	cpu	2026-02-24 04:20:37.067+00
\N	133	cpu_usage_percent	0.4706140350256476	percent	cpu	2026-02-24 06:40:09.021+00
\N	236	cpu_usage_percent	1.3859649123460684	percent	cpu	2026-02-24 04:58:55.073+00
\N	236	cpu_usage_percent	1.3929824560488697	percent	cpu	2026-02-24 04:59:55.073+00
\N	236	cpu_usage_percent	1.645614035068121	percent	cpu	2026-02-24 05:00:55.073+00
\N	236	cpu_usage_percent	1.8807017543402367	percent	cpu	2026-02-24 05:01:55.073+00
\N	236	cpu_usage_percent	2.101754385879957	percent	cpu	2026-02-24 05:02:55.073+00
\N	236	cpu_usage_percent	2.1368421053742708	percent	cpu	2026-02-24 05:03:55.073+00
\N	236	cpu_usage_percent	2.1684210526904053	percent	cpu	2026-02-24 05:04:55.073+00
\N	236	cpu_usage_percent	1.71578947372997	percent	cpu	2026-02-24 05:05:55.073+00
\N	236	cpu_usage_percent	1.5192982456401865	percent	cpu	2026-02-24 05:06:55.073+00
\N	236	cpu_usage_percent	1.456140350844521	percent	cpu	2026-02-24 05:07:55.073+00
\N	236	cpu_usage_percent	1.4350877194093528	percent	cpu	2026-02-24 05:08:55.073+00
\N	236	cpu_usage_percent	1.428070175379787	percent	cpu	2026-02-24 05:09:55.073+00
\N	236	cpu_usage_percent	1.3052631578032532	percent	cpu	2026-02-24 05:10:55.073+00
\N	133	cpu_usage_percent	0.4557017543304198	percent	cpu	2026-02-24 06:41:09.021+00
\N	133	cpu_usage_percent	0.45921052630436066	percent	cpu	2026-02-24 07:09:15.309+00
\N	252	cpu_usage_percent	23.38201754387437	percent	cpu	2026-02-24 02:58:26.555+00
\N	252	cpu_usage_percent	23.342105263166076	percent	cpu	2026-02-24 02:59:26.555+00
\N	252	cpu_usage_percent	23.864035087723394	percent	cpu	2026-02-24 03:00:26.555+00
\N	252	cpu_usage_percent	24.014473684242404	percent	cpu	2026-02-24 03:01:26.555+00
\N	252	cpu_usage_percent	23.71096491227499	percent	cpu	2026-02-24 03:02:26.555+00
\N	252	cpu_usage_percent	23.941228070190164	percent	cpu	2026-02-24 03:03:26.555+00
\N	252	cpu_usage_percent	24.084210526320703	percent	cpu	2026-02-24 03:04:26.555+00
\N	252	cpu_usage_percent	23.82807017545005	percent	cpu	2026-02-24 03:05:26.555+00
\N	252	cpu_usage_percent	24.12105263163859	percent	cpu	2026-02-24 03:06:26.555+00
\N	252	cpu_usage_percent	24.126315789497383	percent	cpu	2026-02-24 03:07:26.555+00
\N	252	cpu_usage_percent	23.906578947361083	percent	cpu	2026-02-24 03:08:26.555+00
\N	252	cpu_usage_percent	23.885087719321945	percent	cpu	2026-02-24 03:09:26.555+00
\N	252	cpu_usage_percent	23.911842105219876	percent	cpu	2026-02-24 03:10:26.555+00
\N	133	cpu_usage_percent	0.42894736835080494	percent	cpu	2026-02-24 07:10:15.309+00
\N	133	cpu_usage_percent	0.42807017542881454	percent	cpu	2026-02-24 07:11:15.309+00
\N	133	cpu_usage_percent	0.3521929824267289	percent	cpu	2026-02-24 07:12:15.309+00
\N	133	cpu_usage_percent	0.4434210526054585	percent	cpu	2026-02-24 07:13:15.309+00
\N	133	cpu_usage_percent	0.5434210526577345	percent	cpu	2026-02-24 07:14:15.309+00
\N	133	cpu_usage_percent	0.6745614035038869	percent	cpu	2026-02-24 07:15:15.309+00
\N	260	cpu_usage_percent	25.497697368386753	percent	cpu	2026-02-24 03:28:31.689+00
\N	260	cpu_usage_percent	25.433552631569157	percent	cpu	2026-02-24 03:29:31.689+00
\N	260	cpu_usage_percent	25.484429824588787	percent	cpu	2026-02-24 03:30:31.689+00
\N	260	cpu_usage_percent	25.496162280732392	percent	cpu	2026-02-24 03:31:31.689+00
\N	260	cpu_usage_percent	25.57807017544596	percent	cpu	2026-02-24 03:32:31.689+00
\N	260	cpu_usage_percent	25.582456140352107	percent	cpu	2026-02-24 03:33:31.689+00
\N	260	cpu_usage_percent	25.562719298279518	percent	cpu	2026-02-24 03:34:31.689+00
\N	260	cpu_usage_percent	25.625219298240722	percent	cpu	2026-02-24 03:35:31.689+00
\N	260	cpu_usage_percent	25.578728070198736	percent	cpu	2026-02-24 03:36:31.689+00
\N	260	cpu_usage_percent	25.602850877208112	percent	cpu	2026-02-24 03:37:31.689+00
\N	260	cpu_usage_percent	25.643859649079104	percent	cpu	2026-02-24 03:38:31.689+00
\N	236	cpu_usage_percent	1.508771929759206	percent	cpu	2026-02-24 03:18:29.116+00
\N	236	cpu_usage_percent	1.4947368421902354	percent	cpu	2026-02-24 03:19:29.116+00
\N	236	cpu_usage_percent	1.466666666562105	percent	cpu	2026-02-24 03:20:29.116+00
\N	236	cpu_usage_percent	1.7333333333137375	percent	cpu	2026-02-24 03:21:29.116+00
\N	236	cpu_usage_percent	1.7508771930609015	percent	cpu	2026-02-24 03:22:29.116+00
\N	236	cpu_usage_percent	1.726315789447554	percent	cpu	2026-02-24 03:23:29.116+00
\N	236	cpu_usage_percent	1.7368421053285346	percent	cpu	2026-02-24 03:24:29.116+00
\N	236	cpu_usage_percent	1.607017543885803	percent	cpu	2026-02-24 03:25:29.116+00
\N	236	cpu_usage_percent	1.456140350844521	percent	cpu	2026-02-24 03:26:29.116+00
\N	236	cpu_usage_percent	1.456140350844521	percent	cpu	2026-02-24 03:27:29.116+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	cpu	2026-02-24 03:28:29.116+00
\N	236	cpu_usage_percent	1.473684210591685	percent	cpu	2026-02-24 03:29:29.116+00
\N	236	cpu_usage_percent	1.5719298245548714	percent	cpu	2026-02-24 03:30:29.116+00
\N	260	cpu_usage_percent	25.606140350880054	percent	cpu	2026-02-24 03:39:31.689+00
\N	260	cpu_usage_percent	25.62642543860548	percent	cpu	2026-02-24 03:40:31.689+00
\N	133	cpu_usage_percent	0.6776315789555554	percent	cpu	2026-02-24 07:16:15.309+00
\N	133	cpu_usage_percent	0.6596491228495012	percent	cpu	2026-02-24 07:17:15.309+00
\N	133	cpu_usage_percent	0.6635964911823322	percent	cpu	2026-02-24 07:18:15.309+00
\N	133	cpu_usage_percent	0.47675438588812824	percent	cpu	2026-02-24 07:19:15.309+00
\N	248	cpu_usage_percent	2.221929824527109	percent	cpu	2026-02-24 04:38:41.867+00
\N	257	cpu_usage_percent	4.9052631578882	percent	cpu	2026-02-24 02:58:26.808+00
\N	257	cpu_usage_percent	4.986842105271336	percent	cpu	2026-02-24 02:59:26.808+00
\N	257	cpu_usage_percent	5.940350877190539	percent	cpu	2026-02-24 03:00:26.808+00
\N	257	cpu_usage_percent	6.616666666660947	percent	cpu	2026-02-24 03:01:26.808+00
\N	257	cpu_usage_percent	5.7894736841901135	percent	cpu	2026-02-24 03:02:26.808+00
\N	133	cpu_usage_percent	0.4368421051798492	percent	cpu	2026-02-24 07:20:15.309+00
\N	133	cpu_usage_percent	0.44824561406451835	percent	cpu	2026-02-24 07:21:15.309+00
\N	257	cpu_usage_percent	5.49210526314647	percent	cpu	2026-02-24 03:03:26.808+00
\N	257	cpu_usage_percent	5.17017543861202	percent	cpu	2026-02-24 03:04:26.808+00
\N	257	cpu_usage_percent	4.432456140353352	percent	cpu	2026-02-24 03:05:26.808+00
\N	257	cpu_usage_percent	3.914035087708683	percent	cpu	2026-02-24 03:06:26.808+00
\N	257	cpu_usage_percent	3.940350877206882	percent	cpu	2026-02-24 03:07:26.808+00
\N	257	cpu_usage_percent	4.056140350855969	percent	cpu	2026-02-24 03:08:26.808+00
\N	257	cpu_usage_percent	4.454385964894314	percent	cpu	2026-02-24 03:09:26.808+00
\N	257	cpu_usage_percent	4.792105263148102	percent	cpu	2026-02-24 03:10:26.808+00
\N	248	cpu_usage_percent	2.135964912329726	percent	cpu	2026-02-24 04:39:41.867+00
\N	248	cpu_usage_percent	2.1877192982815643	percent	cpu	2026-02-24 04:40:41.867+00
\N	248	cpu_usage_percent	2.178070175404301	percent	cpu	2026-02-24 04:41:41.867+00
\N	248	cpu_usage_percent	2.2250000000196195	percent	cpu	2026-02-24 04:42:41.867+00
\N	248	cpu_usage_percent	2.2456140350958975	percent	cpu	2026-02-24 04:43:41.867+00
\N	248	cpu_usage_percent	2.410087719306418	percent	cpu	2026-02-24 04:44:41.867+00
\N	248	cpu_usage_percent	2.4692982456058843	percent	cpu	2026-02-24 04:45:41.867+00
\N	248	cpu_usage_percent	2.4456140350779236	percent	cpu	2026-02-24 04:46:41.867+00
\N	257	cpu_usage_percent	4.072807017558574	percent	cpu	2026-02-24 03:48:34.564+00
\N	257	cpu_usage_percent	4.476315789496567	percent	cpu	2026-02-24 03:49:34.564+00
\N	257	cpu_usage_percent	4.850000000044133	percent	cpu	2026-02-24 03:50:34.564+00
\N	257	cpu_usage_percent	5.623684210535316	percent	cpu	2026-02-24 03:51:34.564+00
\N	257	cpu_usage_percent	5.662280701738055	percent	cpu	2026-02-24 03:52:34.564+00
\N	257	cpu_usage_percent	5.3692982456107785	percent	cpu	2026-02-24 03:53:34.564+00
\N	257	cpu_usage_percent	4.9710526315724195	percent	cpu	2026-02-24 03:54:34.564+00
\N	257	cpu_usage_percent	4.393859649109743	percent	cpu	2026-02-24 03:55:34.564+00
\N	257	cpu_usage_percent	3.864912280706662	percent	cpu	2026-02-24 03:56:34.564+00
\N	257	cpu_usage_percent	3.6324561403435354	percent	cpu	2026-02-24 03:57:34.564+00
\N	257	cpu_usage_percent	4.092982456133015	percent	cpu	2026-02-24 03:58:34.564+00
\N	257	cpu_usage_percent	4.485087719308879	percent	cpu	2026-02-24 03:59:34.564+00
\N	257	cpu_usage_percent	4.8903508771725654	percent	cpu	2026-02-24 04:00:34.564+00
\N	248	cpu_usage_percent	2.4403508771374476	percent	cpu	2026-02-24 04:47:41.867+00
\N	252	cpu_usage_percent	23.917543859662203	percent	cpu	2026-02-24 04:08:37.317+00
\N	252	cpu_usage_percent	24.158333333356225	percent	cpu	2026-02-24 04:09:37.317+00
\N	252	cpu_usage_percent	24.58070175438351	percent	cpu	2026-02-24 04:10:37.317+00
\N	252	cpu_usage_percent	24.950438596516562	percent	cpu	2026-02-24 04:11:37.317+00
\N	252	cpu_usage_percent	25.24868421046179	percent	cpu	2026-02-24 04:12:37.317+00
\N	252	cpu_usage_percent	25.115350877188092	percent	cpu	2026-02-24 04:13:37.317+00
\N	252	cpu_usage_percent	25.15131578948187	percent	cpu	2026-02-24 04:14:37.317+00
\N	248	cpu_usage_percent	2.4478070175258893	percent	cpu	2026-02-24 03:18:29.376+00
\N	248	cpu_usage_percent	2.7271929825247696	percent	cpu	2026-02-24 03:19:29.376+00
\N	248	cpu_usage_percent	2.6978070175340747	percent	cpu	2026-02-24 03:20:29.376+00
\N	248	cpu_usage_percent	2.831578947391307	percent	cpu	2026-02-24 03:21:29.376+00
\N	248	cpu_usage_percent	2.803070175445143	percent	cpu	2026-02-24 03:22:29.376+00
\N	248	cpu_usage_percent	2.758333333318646	percent	cpu	2026-02-24 03:23:29.376+00
\N	248	cpu_usage_percent	2.514912280736084	percent	cpu	2026-02-24 03:24:29.376+00
\N	248	cpu_usage_percent	2.4978070176337326	percent	cpu	2026-02-24 03:25:29.376+00
\N	260	cpu_usage_percent	26.0995614034708	percent	cpu	2026-02-24 02:58:27.054+00
\N	260	cpu_usage_percent	26.088596491241148	percent	cpu	2026-02-24 02:59:27.054+00
\N	260	cpu_usage_percent	26.201644736820057	percent	cpu	2026-02-24 03:00:27.054+00
\N	260	cpu_usage_percent	26.105043859651985	percent	cpu	2026-02-24 03:01:27.054+00
\N	260	cpu_usage_percent	26.098135964916366	percent	cpu	2026-02-24 03:02:27.054+00
\N	260	cpu_usage_percent	26.475877192998794	percent	cpu	2026-02-24 03:03:27.054+00
\N	260	cpu_usage_percent	26.443201754417828	percent	cpu	2026-02-24 03:04:27.054+00
\N	260	cpu_usage_percent	26.185635964870215	percent	cpu	2026-02-24 03:05:27.054+00
\N	260	cpu_usage_percent	26.122149122815614	percent	cpu	2026-02-24 03:06:27.054+00
\N	260	cpu_usage_percent	26.11260964911996	percent	cpu	2026-02-24 03:07:27.054+00
\N	260	cpu_usage_percent	25.61228070174255	percent	cpu	2026-02-24 03:08:27.054+00
\N	260	cpu_usage_percent	25.624561403467524	percent	cpu	2026-02-24 03:09:27.054+00
\N	260	cpu_usage_percent	25.652083333320277	percent	cpu	2026-02-24 03:10:27.054+00
\N	248	cpu_usage_percent	2.5004385964814304	percent	cpu	2026-02-24 03:26:29.376+00
\N	248	cpu_usage_percent	2.528070175423906	percent	cpu	2026-02-24 03:27:29.376+00
\N	248	cpu_usage_percent	2.557456140332917	percent	cpu	2026-02-24 03:28:29.376+00
\N	248	cpu_usage_percent	2.606140350914785	percent	cpu	2026-02-24 03:29:29.376+00
\N	248	cpu_usage_percent	2.6249999999428297	percent	cpu	2026-02-24 03:30:29.376+00
\N	252	cpu_usage_percent	25.092543859643413	percent	cpu	2026-02-24 04:15:37.317+00
\N	252	cpu_usage_percent	24.92499999998121	percent	cpu	2026-02-24 04:16:37.317+00
\N	252	cpu_usage_percent	24.989912280682162	percent	cpu	2026-02-24 03:39:32.709+00
\N	252	cpu_usage_percent	25.17675438595593	percent	cpu	2026-02-24 03:40:32.709+00
\N	252	cpu_usage_percent	24.771491228010547	percent	cpu	2026-02-24 03:41:32.709+00
\N	252	cpu_usage_percent	24.526754385942866	percent	cpu	2026-02-24 03:42:32.709+00
\N	252	cpu_usage_percent	24.517543859649123	percent	cpu	2026-02-24 03:43:32.709+00
\N	252	cpu_usage_percent	24.451754385985353	percent	cpu	2026-02-24 03:44:32.709+00
\N	252	cpu_usage_percent	24.358333333358658	percent	cpu	2026-02-24 03:45:32.709+00
\N	252	cpu_usage_percent	24.034649122837266	percent	cpu	2026-02-24 03:46:32.709+00
\N	252	cpu_usage_percent	23.821929824567135	percent	cpu	2026-02-24 03:47:32.709+00
\N	252	cpu_usage_percent	23.812719298252972	percent	cpu	2026-02-24 03:48:32.709+00
\N	252	cpu_usage_percent	23.746929824568767	percent	cpu	2026-02-24 03:49:32.709+00
\N	252	cpu_usage_percent	23.85394736838512	percent	cpu	2026-02-24 03:50:32.709+00
\N	252	cpu_usage_percent	24.800877193001256	percent	cpu	2026-02-24 04:17:37.317+00
\N	252	cpu_usage_percent	24.780263157924963	percent	cpu	2026-02-24 04:18:37.317+00
\N	252	cpu_usage_percent	24.84736842103304	percent	cpu	2026-02-24 04:19:37.317+00
\N	252	cpu_usage_percent	24.919736842142854	percent	cpu	2026-02-24 04:20:37.317+00
\N	248	cpu_usage_percent	2.3083333333284344	percent	cpu	2026-02-24 04:48:41.867+00
\N	248	cpu_usage_percent	2.323245614023662	percent	cpu	2026-02-24 04:49:41.867+00
\N	248	cpu_usage_percent	2.333333333341514	percent	cpu	2026-02-24 04:50:41.867+00
\N	236	cpu_usage_percent	1.470175438576888	percent	cpu	2026-02-24 05:28:59.963+00
\N	236	cpu_usage_percent	1.4631578947107045	percent	cpu	2026-02-24 05:29:59.963+00
\N	236	cpu_usage_percent	1.4561403510079174	percent	cpu	2026-02-24 05:30:59.963+00
\N	236	cpu_usage_percent	1.3263157895651858	percent	cpu	2026-02-24 05:31:59.963+00
\N	236	cpu_usage_percent	1.7614035087784856	percent	cpu	2026-02-24 05:32:59.963+00
\N	236	cpu_usage_percent	1.7754385965108526	percent	cpu	2026-02-24 05:33:59.963+00
\N	236	cpu_usage_percent	1.7649122807932685	percent	cpu	2026-02-24 05:34:59.963+00
\N	236	cpu_usage_percent	1.771929824659452	percent	cpu	2026-02-24 05:35:59.963+00
\N	236	cpu_usage_percent	1.768421052644669	percent	cpu	2026-02-24 05:36:59.963+00
\N	236	cpu_usage_percent	1.470175438576888	percent	cpu	2026-02-24 05:37:59.963+00
\N	236	cpu_usage_percent	1.4771929824430714	percent	cpu	2026-02-24 05:38:59.963+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	cpu	2026-02-24 05:39:59.963+00
\N	236	cpu_usage_percent	1.487719298324052	percent	cpu	2026-02-24 05:40:59.963+00
\N	133	cpu_usage_percent	0.43157894744358316	percent	cpu	2026-02-24 03:38:31.967+00
\N	133	cpu_usage_percent	0.43947368419092925	percent	cpu	2026-02-24 03:39:31.967+00
\N	133	cpu_usage_percent	0.5377192982766701	percent	cpu	2026-02-24 03:40:31.967+00
\N	133	cpu_usage_percent	0.5614035088454727	percent	cpu	2026-02-24 03:41:31.967+00
\N	133	cpu_usage_percent	0.6649122807082932	percent	cpu	2026-02-24 03:42:31.967+00
\N	133	cpu_usage_percent	0.6771929824332688	percent	cpu	2026-02-24 03:43:31.967+00
\N	252	cpu_usage_percent	25.017105263163614	percent	cpu	2026-02-24 03:18:29.621+00
\N	252	cpu_usage_percent	25.039035087704605	percent	cpu	2026-02-24 03:19:29.621+00
\N	252	cpu_usage_percent	24.65263157893021	percent	cpu	2026-02-24 03:20:29.621+00
\N	252	cpu_usage_percent	24.503070175414905	percent	cpu	2026-02-24 03:21:29.621+00
\N	252	cpu_usage_percent	24.22105263156834	percent	cpu	2026-02-24 03:22:29.621+00
\N	252	cpu_usage_percent	24.12368421054755	percent	cpu	2026-02-24 03:23:29.621+00
\N	252	cpu_usage_percent	24.1083333333505	percent	cpu	2026-02-24 03:24:29.621+00
\N	252	cpu_usage_percent	24.210087719328484	percent	cpu	2026-02-24 03:25:29.621+00
\N	252	cpu_usage_percent	24.225877192986545	percent	cpu	2026-02-24 03:26:29.621+00
\N	252	cpu_usage_percent	24.191666666700158	percent	cpu	2026-02-24 03:27:29.621+00
\N	252	cpu_usage_percent	24.13377192988584	percent	cpu	2026-02-24 03:28:29.621+00
\N	252	cpu_usage_percent	24.307456140287968	percent	cpu	2026-02-24 03:29:29.621+00
\N	252	cpu_usage_percent	24.372368421050197	percent	cpu	2026-02-24 03:30:29.621+00
\N	133	cpu_usage_percent	0.6749999999853031	percent	cpu	2026-02-24 03:44:31.967+00
\N	133	cpu_usage_percent	0.5793859649515127	percent	cpu	2026-02-24 03:45:31.967+00
\N	133	cpu_usage_percent	0.44649122809796893	percent	cpu	2026-02-24 03:46:31.967+00
\N	133	cpu_usage_percent	0.4377192982652218	percent	cpu	2026-02-24 03:47:31.967+00
\N	133	cpu_usage_percent	0.44868421054593455	percent	cpu	2026-02-24 03:48:31.967+00
\N	133	cpu_usage_percent	0.436842105179835	percent	cpu	2026-02-24 03:49:31.967+00
\N	133	cpu_usage_percent	0.5228070175814565	percent	cpu	2026-02-24 03:50:31.967+00
\N	133	cpu_usage_percent	0.5394736842432053	percent	cpu	2026-02-24 07:49:21.614+00
\N	133	cpu_usage_percent	0.43771929818353783	percent	cpu	2026-02-24 07:50:21.614+00
\N	133	cpu_usage_percent	0.44122807011662246	percent	cpu	2026-02-24 07:51:21.614+00
\N	133	cpu_usage_percent	0.451754385997603	percent	cpu	2026-02-24 07:52:21.614+00
\N	133	cpu_usage_percent	0.44868421058677654	percent	cpu	2026-02-24 07:53:21.614+00
\N	133	cpu_usage_percent	0.4342105263321514	percent	cpu	2026-02-24 07:54:21.614+00
\N	133	cpu_usage_percent	0.6517543858979309	percent	cpu	2026-02-24 07:55:21.614+00
\N	133	cpu_usage_percent	0.6561403509164165	percent	cpu	2026-02-24 07:56:21.614+00
\N	260	cpu_usage_percent	25.61359649124809	percent	cpu	2026-02-24 03:48:34.805+00
\N	260	cpu_usage_percent	25.58015350878378	percent	cpu	2026-02-24 03:49:34.805+00
\N	260	cpu_usage_percent	25.62697368420727	percent	cpu	2026-02-24 03:50:34.805+00
\N	260	cpu_usage_percent	25.62554824558137	percent	cpu	2026-02-24 03:51:34.805+00
\N	260	cpu_usage_percent	25.559320175436156	percent	cpu	2026-02-24 03:52:34.805+00
\N	260	cpu_usage_percent	25.601754385973905	percent	cpu	2026-02-24 03:53:34.805+00
\N	260	cpu_usage_percent	25.54418859644916	percent	cpu	2026-02-24 03:54:34.805+00
\N	260	cpu_usage_percent	25.506798245621397	percent	cpu	2026-02-24 03:55:34.805+00
\N	260	cpu_usage_percent	25.53706140351369	percent	cpu	2026-02-24 03:56:34.805+00
\N	260	cpu_usage_percent	25.499013157861654	percent	cpu	2026-02-24 03:57:34.805+00
\N	260	cpu_usage_percent	25.526754385944912	percent	cpu	2026-02-24 03:58:34.805+00
\N	260	cpu_usage_percent	25.54703947366012	percent	cpu	2026-02-24 03:59:34.805+00
\N	260	cpu_usage_percent	25.56589912282091	percent	cpu	2026-02-24 04:00:34.805+00
\N	133	cpu_usage_percent	0.6473684210428416	percent	cpu	2026-02-24 07:57:21.614+00
\N	133	cpu_usage_percent	0.6521929824202033	percent	cpu	2026-02-24 07:58:21.614+00
\N	133	cpu_usage_percent	0.453070175482722	percent	cpu	2026-02-24 07:59:21.614+00
\N	248	cpu_usage_percent	2.265789473649903	percent	cpu	2026-02-24 04:58:55.349+00
\N	248	cpu_usage_percent	2.3030701754696423	percent	cpu	2026-02-24 04:59:55.349+00
\N	248	cpu_usage_percent	2.4078947368584522	percent	cpu	2026-02-24 05:00:55.349+00
\N	248	cpu_usage_percent	2.37982456131202	percent	cpu	2026-02-24 05:01:55.349+00
\N	248	cpu_usage_percent	2.4504385965369835	percent	cpu	2026-02-24 05:02:55.349+00
\N	248	cpu_usage_percent	2.462719298221117	percent	cpu	2026-02-24 05:03:55.349+00
\N	257	cpu_usage_percent	4.06929824562549	percent	cpu	2026-02-24 03:18:29.892+00
\N	257	cpu_usage_percent	4.491228070171374	percent	cpu	2026-02-24 03:19:29.892+00
\N	257	cpu_usage_percent	5.086842105262363	percent	cpu	2026-02-24 03:20:29.892+00
\N	257	cpu_usage_percent	5.57105263160021	percent	cpu	2026-02-24 03:21:29.892+00
\N	257	cpu_usage_percent	5.551754385968195	percent	cpu	2026-02-24 03:22:29.892+00
\N	257	cpu_usage_percent	5.312280701779713	percent	cpu	2026-02-24 03:23:29.892+00
\N	257	cpu_usage_percent	4.951754385940404	percent	cpu	2026-02-24 03:24:29.892+00
\N	257	cpu_usage_percent	4.314035087734013	percent	cpu	2026-02-24 03:25:29.892+00
\N	257	cpu_usage_percent	3.8631578947605476	percent	cpu	2026-02-24 03:26:29.892+00
\N	257	cpu_usage_percent	3.88947368421789	percent	cpu	2026-02-24 03:27:29.892+00
\N	257	cpu_usage_percent	4.056140350876376	percent	cpu	2026-02-24 03:28:29.892+00
\N	257	cpu_usage_percent	4.4228070175373375	percent	cpu	2026-02-24 03:29:29.892+00
\N	257	cpu_usage_percent	4.964912280689518	percent	cpu	2026-02-24 03:30:29.892+00
\N	248	cpu_usage_percent	2.472807017579811	percent	cpu	2026-02-24 05:04:55.349+00
\N	248	cpu_usage_percent	2.26929824554216	percent	cpu	2026-02-24 05:05:55.349+00
\N	248	cpu_usage_percent	2.3478070175961534	percent	cpu	2026-02-24 05:06:55.349+00
\N	248	cpu_usage_percent	2.256140350936022	percent	cpu	2026-02-24 05:07:55.349+00
\N	248	cpu_usage_percent	2.261842105194546	percent	cpu	2026-02-24 05:08:55.349+00
\N	257	cpu_usage_percent	4.02105263156588	percent	cpu	2026-02-24 04:08:37.553+00
\N	257	cpu_usage_percent	4.415789473691561	percent	cpu	2026-02-24 04:09:37.553+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	cpu	2026-02-24 03:38:32.211+00
\N	236	cpu_usage_percent	1.4280701755431693	percent	cpu	2026-02-24 03:39:32.211+00
\N	236	cpu_usage_percent	1.568421052703485	percent	cpu	2026-02-24 03:40:32.211+00
\N	236	cpu_usage_percent	1.564912280688688	percent	cpu	2026-02-24 03:41:32.211+00
\N	236	cpu_usage_percent	1.754385964912288	percent	cpu	2026-02-24 03:42:32.211+00
\N	236	cpu_usage_percent	1.7754385965108526	percent	cpu	2026-02-24 03:43:32.211+00
\N	236	cpu_usage_percent	1.7789473685256354	percent	cpu	2026-02-24 03:44:32.211+00
\N	236	cpu_usage_percent	1.6491228069195216	percent	cpu	2026-02-24 03:45:32.211+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	cpu	2026-02-24 03:46:32.211+00
\N	236	cpu_usage_percent	1.4631578947107045	percent	cpu	2026-02-24 03:47:32.211+00
\N	236	cpu_usage_percent	1.487719298324052	percent	cpu	2026-02-24 03:48:32.211+00
\N	236	cpu_usage_percent	1.5052631579078195	percent	cpu	2026-02-24 03:49:32.211+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	cpu	2026-02-24 03:50:32.211+00
\N	257	cpu_usage_percent	4.849999999982856	percent	cpu	2026-02-24 04:10:37.553+00
\N	257	cpu_usage_percent	5.392982456138725	percent	cpu	2026-02-24 04:11:37.553+00
\N	257	cpu_usage_percent	5.638596491210109	percent	cpu	2026-02-24 04:12:37.553+00
\N	257	cpu_usage_percent	5.357017543844961	percent	cpu	2026-02-24 04:13:37.553+00
\N	257	cpu_usage_percent	4.9850877193047864	percent	cpu	2026-02-24 04:14:37.553+00
\N	257	cpu_usage_percent	4.606140350857586	percent	cpu	2026-02-24 04:15:37.553+00
\N	257	cpu_usage_percent	3.8771929824520583	percent	cpu	2026-02-24 04:16:37.553+00
\N	133	cpu_usage_percent	0.4447368421722615	percent	cpu	2026-02-24 08:00:21.614+00
\N	257	cpu_usage_percent	3.8877192982717617	percent	cpu	2026-02-24 04:17:37.553+00
\N	257	cpu_usage_percent	3.839473684212166	percent	cpu	2026-02-24 04:18:37.553+00
\N	257	cpu_usage_percent	4.405263157871872	percent	cpu	2026-02-24 04:19:37.553+00
\N	257	cpu_usage_percent	4.764035087683354	percent	cpu	2026-02-24 04:20:37.553+00
\N	248	cpu_usage_percent	2.339473684244851	percent	cpu	2026-02-24 05:09:55.349+00
\N	248	cpu_usage_percent	2.4017543859959716	percent	cpu	2026-02-24 05:10:55.349+00
\N	133	cpu_usage_percent	0.4456140351351081	percent	cpu	2026-02-24 08:01:21.614+00
\N	252	cpu_usage_percent	24.991228070208123	percent	cpu	2026-02-24 04:38:42.126+00
\N	252	cpu_usage_percent	24.801315789503093	percent	cpu	2026-02-24 04:39:42.126+00
\N	252	cpu_usage_percent	24.619736842108537	percent	cpu	2026-02-24 04:40:42.126+00
\N	252	cpu_usage_percent	24.75833333330229	percent	cpu	2026-02-24 04:41:42.126+00
\N	260	cpu_usage_percent	25.595504386011484	percent	cpu	2026-02-24 03:18:30.123+00
\N	260	cpu_usage_percent	25.648135964915966	percent	cpu	2026-02-24 03:19:30.123+00
\N	260	cpu_usage_percent	25.6658991227915	percent	cpu	2026-02-24 03:20:30.123+00
\N	260	cpu_usage_percent	25.67061403505872	percent	cpu	2026-02-24 03:21:30.123+00
\N	260	cpu_usage_percent	25.607017543853118	percent	cpu	2026-02-24 03:22:30.123+00
\N	260	cpu_usage_percent	25.620833333324356	percent	cpu	2026-02-24 03:23:30.123+00
\N	260	cpu_usage_percent	25.55855263158344	percent	cpu	2026-02-24 03:24:30.123+00
\N	260	cpu_usage_percent	25.53760964912567	percent	cpu	2026-02-24 03:25:30.123+00
\N	260	cpu_usage_percent	25.532785087707467	percent	cpu	2026-02-24 03:26:30.123+00
\N	260	cpu_usage_percent	25.49210526316689	percent	cpu	2026-02-24 03:27:30.123+00
\N	260	cpu_usage_percent	25.497697368386753	percent	cpu	2026-02-24 03:28:30.123+00
\N	260	cpu_usage_percent	25.433552631569157	percent	cpu	2026-02-24 03:29:30.123+00
\N	260	cpu_usage_percent	25.484429824588787	percent	cpu	2026-02-24 03:30:30.123+00
\N	252	cpu_usage_percent	24.90087719299227	percent	cpu	2026-02-24 04:42:42.126+00
\N	252	cpu_usage_percent	25.061842105208427	percent	cpu	2026-02-24 04:43:42.126+00
\N	252	cpu_usage_percent	25.10307017542226	percent	cpu	2026-02-24 04:44:42.126+00
\N	133	cpu_usage_percent	0.4228070175291663	percent	cpu	2026-02-24 03:58:35.055+00
\N	133	cpu_usage_percent	0.4328947368470182	percent	cpu	2026-02-24 03:59:35.055+00
\N	133	cpu_usage_percent	0.43070175439903835	percent	cpu	2026-02-24 04:00:35.055+00
\N	133	cpu_usage_percent	0.5688596491522304	percent	cpu	2026-02-24 04:01:35.055+00
\N	133	cpu_usage_percent	0.473684210518158	percent	cpu	2026-02-24 04:02:35.055+00
\N	133	cpu_usage_percent	0.5714912281224684	percent	cpu	2026-02-24 04:03:35.055+00
\N	133	cpu_usage_percent	0.5807017543957755	percent	cpu	2026-02-24 04:04:35.055+00
\N	133	cpu_usage_percent	0.4828947368323213	percent	cpu	2026-02-24 04:05:35.055+00
\N	133	cpu_usage_percent	0.43201754372077517	percent	cpu	2026-02-24 04:06:35.055+00
\N	133	cpu_usage_percent	0.4267543859845233	percent	cpu	2026-02-24 04:07:35.055+00
\N	133	cpu_usage_percent	0.42850877195107273	percent	cpu	2026-02-24 04:08:35.055+00
\N	133	cpu_usage_percent	0.42105263156261685	percent	cpu	2026-02-24 04:09:35.055+00
\N	133	cpu_usage_percent	0.42982456147704795	percent	cpu	2026-02-24 04:10:35.055+00
\N	252	cpu_usage_percent	25.243421052602997	percent	cpu	2026-02-24 04:45:42.126+00
\N	252	cpu_usage_percent	25.18859649121991	percent	cpu	2026-02-24 04:46:42.126+00
\N	252	cpu_usage_percent	25.186403508812788	percent	cpu	2026-02-24 04:47:42.126+00
\N	248	cpu_usage_percent	2.571491228065284	percent	cpu	2026-02-24 03:38:32.462+00
\N	248	cpu_usage_percent	2.5649122806396747	percent	cpu	2026-02-24 03:39:32.462+00
\N	248	cpu_usage_percent	2.51008771927701	percent	cpu	2026-02-24 03:40:32.462+00
\N	248	cpu_usage_percent	2.5644736841991005	percent	cpu	2026-02-24 03:41:32.462+00
\N	248	cpu_usage_percent	2.616228070110097	percent	cpu	2026-02-24 03:42:32.462+00
\N	248	cpu_usage_percent	2.624122806979983	percent	cpu	2026-02-24 03:43:32.462+00
\N	248	cpu_usage_percent	2.8885964912019375	percent	cpu	2026-02-24 03:44:32.462+00
\N	248	cpu_usage_percent	2.849122807015931	percent	cpu	2026-02-24 03:45:32.462+00
\N	248	cpu_usage_percent	2.6171052631137997	percent	cpu	2026-02-24 03:46:32.462+00
\N	248	cpu_usage_percent	2.6184210526806027	percent	cpu	2026-02-24 03:47:32.462+00
\N	248	cpu_usage_percent	2.3657894737021934	percent	cpu	2026-02-24 03:48:32.462+00
\N	248	cpu_usage_percent	2.2741228069195216	percent	cpu	2026-02-24 03:49:32.462+00
\N	248	cpu_usage_percent	2.206578947309609	percent	cpu	2026-02-24 03:50:32.462+00
\N	252	cpu_usage_percent	24.91535087718563	percent	cpu	2026-02-24 04:48:42.126+00
\N	252	cpu_usage_percent	24.987719298234197	percent	cpu	2026-02-24 04:49:42.126+00
\N	252	cpu_usage_percent	24.81447368419093	percent	cpu	2026-02-24 04:50:42.126+00
\N	236	cpu_usage_percent	1.4070175439446189	percent	cpu	2026-02-24 05:59:04.392+00
\N	236	cpu_usage_percent	1.4175438594988208	percent	cpu	2026-02-24 06:00:04.392+00
\N	236	cpu_usage_percent	1.4350877192459706	percent	cpu	2026-02-24 06:01:04.392+00
\N	236	cpu_usage_percent	1.3859649123460684	percent	cpu	2026-02-24 06:02:04.392+00
\N	236	cpu_usage_percent	1.6280701754843534	percent	cpu	2026-02-24 06:03:04.392+00
\N	236	cpu_usage_percent	1.649122807082918	percent	cpu	2026-02-24 06:04:04.392+00
\N	236	cpu_usage_percent	1.656140350785705	percent	cpu	2026-02-24 06:05:04.392+00
\N	236	cpu_usage_percent	1.6315789474991504	percent	cpu	2026-02-24 06:06:04.392+00
\N	236	cpu_usage_percent	1.687719298265236	percent	cpu	2026-02-24 06:07:04.392+00
\N	236	cpu_usage_percent	1.4280701755431693	percent	cpu	2026-02-24 06:08:04.392+00
\N	236	cpu_usage_percent	1.2694825928995073	percent	cpu	2026-02-24 06:09:04.392+00
\N	236	cpu_usage_percent	1.3999999999150532	percent	cpu	2026-02-24 06:10:04.392+00
\N	236	cpu_usage_percent	1.4210526315136036	percent	cpu	2026-02-24 06:11:04.392+00
\N	133	cpu_usage_percent	0.6486842104462767	percent	cpu	2026-02-24 08:29:32.45+00
\N	133	cpu_usage_percent	0.4728070175553114	percent	cpu	2026-02-24 08:30:32.45+00
\N	133	cpu_usage_percent	0.42938596491391934	percent	cpu	2026-02-24 08:31:32.45+00
\N	133	cpu_usage_percent	0.45043859647164197	percent	cpu	2026-02-24 08:32:32.45+00
\N	133	cpu_usage_percent	0.45131578951617257	percent	cpu	2026-02-24 08:33:32.45+00
\N	133	cpu_usage_percent	0.4464912280162707	percent	cpu	2026-02-24 08:34:32.45+00
\N	133	cpu_usage_percent	0.6513157894165005	percent	cpu	2026-02-24 08:35:32.45+00
\N	133	cpu_usage_percent	0.665789473671154	percent	cpu	2026-02-24 08:36:32.45+00
\N	260	cpu_usage_percent	26.907785087752387	percent	cpu	2026-02-24 04:08:37.789+00
\N	260	cpu_usage_percent	27.0373903508727	percent	cpu	2026-02-24 04:09:37.789+00
\N	260	cpu_usage_percent	26.607017543834743	percent	cpu	2026-02-24 04:10:37.789+00
\N	260	cpu_usage_percent	26.51776315791436	percent	cpu	2026-02-24 04:11:37.789+00
\N	260	cpu_usage_percent	26.237061403542683	percent	cpu	2026-02-24 04:12:37.789+00
\N	260	cpu_usage_percent	25.623355263123187	percent	cpu	2026-02-24 04:13:37.789+00
\N	260	cpu_usage_percent	25.638377192989807	percent	cpu	2026-02-24 04:14:37.789+00
\N	260	cpu_usage_percent	25.53475877194535	percent	cpu	2026-02-24 04:15:37.789+00
\N	260	cpu_usage_percent	25.570504385977983	percent	cpu	2026-02-24 04:16:37.789+00
\N	260	cpu_usage_percent	25.55811403506118	percent	cpu	2026-02-24 04:17:37.789+00
\N	236	cpu_usage_percent	1.4491228069783375	percent	cpu	2026-02-24 03:58:35.322+00
\N	236	cpu_usage_percent	1.470175438576888	percent	cpu	2026-02-24 03:59:35.322+00
\N	236	cpu_usage_percent	1.4807017544578684	percent	cpu	2026-02-24 04:00:35.322+00
\N	252	cpu_usage_percent	24.877192982464308	percent	cpu	2026-02-24 03:38:32.709+00
\N	236	cpu_usage_percent	1.592982456153436	percent	cpu	2026-02-24 04:01:35.322+00
\N	260	cpu_usage_percent	25.519517543868645	percent	cpu	2026-02-24 04:18:37.789+00
\N	133	cpu_usage_percent	0.8013157894132377	percent	cpu	2026-02-24 08:37:32.45+00
\N	236	cpu_usage_percent	1.529824561521167	percent	cpu	2026-02-24 04:02:35.322+00
\N	236	cpu_usage_percent	1.62105263161817	percent	cpu	2026-02-24 04:03:35.322+00
\N	236	cpu_usage_percent	1.6035087720344023	percent	cpu	2026-02-24 04:04:35.322+00
\N	236	cpu_usage_percent	2.256140350936022	percent	cpu	2026-02-24 04:05:35.322+00
\N	236	cpu_usage_percent	2.052631578980055	percent	cpu	2026-02-24 04:06:35.322+00
\N	236	cpu_usage_percent	2.038596491247688	percent	cpu	2026-02-24 04:07:35.322+00
\N	236	cpu_usage_percent	2.066666666712422	percent	cpu	2026-02-24 04:08:35.322+00
\N	236	cpu_usage_percent	2.10526315789474	percent	cpu	2026-02-24 04:09:35.322+00
\N	236	cpu_usage_percent	2.2315789474860708	percent	cpu	2026-02-24 04:10:35.322+00
\N	260	cpu_usage_percent	25.583004385984538	percent	cpu	2026-02-24 04:19:37.789+00
\N	260	cpu_usage_percent	25.582175925966894	percent	cpu	2026-02-24 04:20:37.789+00
\N	133	cpu_usage_percent	0.8035087718612175	percent	cpu	2026-02-24 08:38:32.45+00
\N	133	cpu_usage_percent	0.6105263158270589	percent	cpu	2026-02-24 08:39:32.45+00
\N	133	cpu_usage_percent	0.5934210526021815	percent	cpu	2026-02-24 08:40:32.45+00
\N	248	cpu_usage_percent	2.3250000000718956	percent	cpu	2026-02-24 05:29:00.227+00
\N	248	cpu_usage_percent	2.38684210521906	percent	cpu	2026-02-24 05:30:00.227+00
\N	248	cpu_usage_percent	2.4925438596524145	percent	cpu	2026-02-24 05:31:00.227+00
\N	248	cpu_usage_percent	2.4350877193194975	percent	cpu	2026-02-24 05:32:00.227+00
\N	257	cpu_usage_percent	4.126315789476948	percent	cpu	2026-02-24 03:38:32.964+00
\N	257	cpu_usage_percent	4.503508771957613	percent	cpu	2026-02-24 03:39:32.964+00
\N	257	cpu_usage_percent	5.021052631598565	percent	cpu	2026-02-24 03:40:32.964+00
\N	257	cpu_usage_percent	5.478947368397371	percent	cpu	2026-02-24 03:41:32.964+00
\N	257	cpu_usage_percent	5.74122807017136	percent	cpu	2026-02-24 03:42:32.964+00
\N	257	cpu_usage_percent	5.379824561410047	percent	cpu	2026-02-24 03:43:32.964+00
\N	257	cpu_usage_percent	4.993859649137519	percent	cpu	2026-02-24 03:44:32.964+00
\N	257	cpu_usage_percent	4.428947368440674	percent	cpu	2026-02-24 03:45:32.964+00
\N	257	cpu_usage_percent	3.9228070175618512	percent	cpu	2026-02-24 03:46:32.964+00
\N	257	cpu_usage_percent	3.8666666666936464	percent	cpu	2026-02-24 03:47:32.964+00
\N	257	cpu_usage_percent	4.072807017558574	percent	cpu	2026-02-24 03:48:32.964+00
\N	257	cpu_usage_percent	4.476315789496567	percent	cpu	2026-02-24 03:49:32.964+00
\N	257	cpu_usage_percent	4.850000000044133	percent	cpu	2026-02-24 03:50:32.964+00
\N	248	cpu_usage_percent	2.6105263158107306	percent	cpu	2026-02-24 05:33:00.227+00
\N	248	cpu_usage_percent	2.681578947312886	percent	cpu	2026-02-24 05:34:00.227+00
\N	248	cpu_usage_percent	3.172368421015065	percent	cpu	2026-02-24 05:35:00.227+00
\N	248	cpu_usage_percent	3.062280701767463	percent	cpu	2026-02-24 05:36:00.227+00
\N	248	cpu_usage_percent	3.1004385964275087	percent	cpu	2026-02-24 05:37:00.227+00
\N	248	cpu_usage_percent	2.9662280702114003	percent	cpu	2026-02-24 05:38:00.227+00
\N	248	cpu_usage_percent	2.949561403549623	percent	cpu	2026-02-24 05:39:00.227+00
\N	252	cpu_usage_percent	24.319298245633647	percent	cpu	2026-02-24 04:58:55.587+00
\N	257	cpu_usage_percent	4.058771929826207	percent	cpu	2026-02-24 04:38:42.39+00
\N	257	cpu_usage_percent	4.182456140345167	percent	cpu	2026-02-24 04:39:42.39+00
\N	257	cpu_usage_percent	4.803508771930652	percent	cpu	2026-02-24 04:40:42.39+00
\N	257	cpu_usage_percent	5.075438596479799	percent	cpu	2026-02-24 04:41:42.39+00
\N	257	cpu_usage_percent	5.661403508775209	percent	cpu	2026-02-24 04:42:42.39+00
\N	257	cpu_usage_percent	5.3859649122725415	percent	cpu	2026-02-24 04:43:42.39+00
\N	257	cpu_usage_percent	4.8043859649139335	percent	cpu	2026-02-24 04:44:42.39+00
\N	257	cpu_usage_percent	4.604385964911472	percent	cpu	2026-02-24 04:45:42.39+00
\N	257	cpu_usage_percent	4.207017543856395	percent	cpu	2026-02-24 04:46:42.39+00
\N	257	cpu_usage_percent	3.8377192982047745	percent	cpu	2026-02-24 04:47:42.39+00
\N	257	cpu_usage_percent	3.9938596491252696	percent	cpu	2026-02-24 04:48:42.39+00
\N	257	cpu_usage_percent	4.37719298244798	percent	cpu	2026-02-24 04:49:42.39+00
\N	257	cpu_usage_percent	4.788596491215003	percent	cpu	2026-02-24 04:50:42.39+00
\N	252	cpu_usage_percent	24.436842105249283	percent	cpu	2026-02-24 04:59:55.587+00
\N	252	cpu_usage_percent	24.371929824548346	percent	cpu	2026-02-24 05:00:55.587+00
\N	252	cpu_usage_percent	24.25526315791599	percent	cpu	2026-02-24 05:01:55.587+00
\N	252	cpu_usage_percent	24.092105263129298	percent	cpu	2026-02-24 05:02:55.587+00
\N	252	cpu_usage_percent	23.990789473694022	percent	cpu	2026-02-24 05:03:55.587+00
\N	252	cpu_usage_percent	23.670175438583428	percent	cpu	2026-02-24 05:04:55.587+00
\N	252	cpu_usage_percent	23.646491228116744	percent	cpu	2026-02-24 05:05:55.587+00
\N	248	cpu_usage_percent	2.127192982496993	percent	cpu	2026-02-24 03:58:35.558+00
\N	248	cpu_usage_percent	2.105263157976438	percent	cpu	2026-02-24 03:59:35.558+00
\N	248	cpu_usage_percent	2.2736842104789474	percent	cpu	2026-02-24 04:00:35.558+00
\N	248	cpu_usage_percent	2.3289473683638704	percent	cpu	2026-02-24 04:01:35.558+00
\N	248	cpu_usage_percent	2.2109649122055544	percent	cpu	2026-02-24 04:02:35.558+00
\N	248	cpu_usage_percent	2.2890350877372754	percent	cpu	2026-02-24 04:03:35.558+00
\N	248	cpu_usage_percent	2.4197368421020116	percent	cpu	2026-02-24 04:04:35.558+00
\N	248	cpu_usage_percent	2.2228070175307977	percent	cpu	2026-02-24 04:05:35.558+00
\N	248	cpu_usage_percent	2.275438596568037	percent	cpu	2026-02-24 04:06:35.558+00
\N	260	cpu_usage_percent	25.643859649079104	percent	cpu	2026-02-24 03:38:33.199+00
\N	260	cpu_usage_percent	25.606140350880054	percent	cpu	2026-02-24 03:39:33.199+00
\N	260	cpu_usage_percent	25.62642543860548	percent	cpu	2026-02-24 03:40:33.199+00
\N	260	cpu_usage_percent	25.68048245612566	percent	cpu	2026-02-24 03:41:33.199+00
\N	260	cpu_usage_percent	25.595723684201147	percent	cpu	2026-02-24 03:42:33.199+00
\N	260	cpu_usage_percent	25.586184210505493	percent	cpu	2026-02-24 03:43:33.199+00
\N	260	cpu_usage_percent	25.641337719280273	percent	cpu	2026-02-24 03:44:33.199+00
\N	260	cpu_usage_percent	25.490241228079995	percent	cpu	2026-02-24 03:45:33.199+00
\N	260	cpu_usage_percent	25.5870614035194	percent	cpu	2026-02-24 03:46:33.199+00
\N	260	cpu_usage_percent	25.507236842072174	percent	cpu	2026-02-24 03:47:33.199+00
\N	260	cpu_usage_percent	25.61359649124809	percent	cpu	2026-02-24 03:48:33.199+00
\N	260	cpu_usage_percent	25.58015350878378	percent	cpu	2026-02-24 03:49:33.199+00
\N	260	cpu_usage_percent	25.62697368420727	percent	cpu	2026-02-24 03:50:33.199+00
\N	248	cpu_usage_percent	2.4008771929922688	percent	cpu	2026-02-24 04:07:35.558+00
\N	248	cpu_usage_percent	2.3785087719085993	percent	cpu	2026-02-24 04:08:35.558+00
\N	248	cpu_usage_percent	2.316666666598053	percent	cpu	2026-02-24 04:09:35.558+00
\N	248	cpu_usage_percent	2.2956140349994882	percent	cpu	2026-02-24 04:10:35.558+00
\N	252	cpu_usage_percent	23.74210526317097	percent	cpu	2026-02-24 05:06:55.587+00
\N	252	cpu_usage_percent	23.547368421088592	percent	cpu	2026-02-24 05:07:55.587+00
\N	133	cpu_usage_percent	0.34605263152340626	percent	cpu	2026-02-24 04:18:38.199+00
\N	133	cpu_usage_percent	0.47675438601066844	percent	cpu	2026-02-24 04:19:38.199+00
\N	133	cpu_usage_percent	0.454385964886157	percent	cpu	2026-02-24 04:20:38.199+00
\N	133	cpu_usage_percent	0.5671052631039828	percent	cpu	2026-02-24 04:21:38.199+00
\N	133	cpu_usage_percent	0.7092105263125319	percent	cpu	2026-02-24 04:22:38.199+00
\N	133	cpu_usage_percent	0.5969298245352803	percent	cpu	2026-02-24 04:23:38.199+00
\N	133	cpu_usage_percent	0.675877192948164	percent	cpu	2026-02-24 04:24:38.199+00
\N	133	cpu_usage_percent	0.6973684210689726	percent	cpu	2026-02-24 04:25:38.199+00
\N	133	cpu_usage_percent	0.45745614033781123	percent	cpu	2026-02-24 04:26:38.199+00
\N	248	cpu_usage_percent	2.347368420992197	percent	cpu	2026-02-24 05:40:00.227+00
\N	133	cpu_usage_percent	0.4346491227727114	percent	cpu	2026-02-24 04:27:38.199+00
\N	133	cpu_usage_percent	0.43026315787678016	percent	cpu	2026-02-24 04:28:38.199+00
\N	133	cpu_usage_percent	0.453070175482722	percent	cpu	2026-02-24 04:29:38.199+00
\N	133	cpu_usage_percent	0.44166666672059307	percent	cpu	2026-02-24 04:30:38.199+00
\N	252	cpu_usage_percent	23.665350877206066	percent	cpu	2026-02-24 05:08:55.587+00
\N	252	cpu_usage_percent	23.84649122805793	percent	cpu	2026-02-24 05:09:55.587+00
\N	252	cpu_usage_percent	23.852192982459414	percent	cpu	2026-02-24 05:10:55.587+00
\N	248	cpu_usage_percent	2.3171052632020235	percent	cpu	2026-02-24 05:41:00.227+00
\N	133	cpu_usage_percent	0.3219298245140294	percent	cpu	2026-02-24 08:41:32.45+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	cpu	2026-02-24 06:29:09.29+00
\N	236	cpu_usage_percent	1.3017543859518526	percent	cpu	2026-02-24 06:30:09.29+00
\N	236	cpu_usage_percent	1.4456140351269369	percent	cpu	2026-02-24 06:31:09.29+00
\N	236	cpu_usage_percent	1.4631578947107045	percent	cpu	2026-02-24 06:32:09.29+00
\N	236	cpu_usage_percent	1.480701754294472	percent	cpu	2026-02-24 06:33:09.29+00
\N	236	cpu_usage_percent	1.7824561402136396	percent	cpu	2026-02-24 06:34:09.29+00
\N	236	cpu_usage_percent	1.8280701754255375	percent	cpu	2026-02-24 06:35:09.29+00
\N	236	cpu_usage_percent	1.8666666666078555	percent	cpu	2026-02-24 06:36:09.29+00
\N	236	cpu_usage_percent	1.9087719298049706	percent	cpu	2026-02-24 06:37:09.29+00
\N	236	cpu_usage_percent	1.9122807016563712	percent	cpu	2026-02-24 06:38:09.29+00
\N	236	cpu_usage_percent	1.61403508758859	percent	cpu	2026-02-24 06:39:09.29+00
\N	236	cpu_usage_percent	1.5859649122872526	percent	cpu	2026-02-24 06:40:09.29+00
\N	236	cpu_usage_percent	1.5192982456401865	percent	cpu	2026-02-24 06:41:09.29+00
\N	133	cpu_usage_percent	1.6473684211572106	percent	cpu	2026-02-24 09:09:42.08+00
\N	133	cpu_usage_percent	0.5535087718938883	percent	cpu	2026-02-24 09:10:42.08+00
\N	133	cpu_usage_percent	0.4530701754010238	percent	cpu	2026-02-24 09:11:42.08+00
\N	133	cpu_usage_percent	0.44122807015747867	percent	cpu	2026-02-24 09:12:42.08+00
\N	252	cpu_usage_percent	23.986403508777656	percent	cpu	2026-02-24 03:58:35.828+00
\N	252	cpu_usage_percent	24.174122807014285	percent	cpu	2026-02-24 03:59:35.828+00
\N	252	cpu_usage_percent	24.397807017524258	percent	cpu	2026-02-24 04:00:35.828+00
\N	252	cpu_usage_percent	23.193421052593195	percent	cpu	2026-02-24 04:01:35.828+00
\N	252	cpu_usage_percent	22.382017543841684	percent	cpu	2026-02-24 04:02:35.828+00
\N	252	cpu_usage_percent	22.293421052653656	percent	cpu	2026-02-24 04:03:35.828+00
\N	252	cpu_usage_percent	22.40087719299227	percent	cpu	2026-02-24 04:04:35.828+00
\N	252	cpu_usage_percent	21.948245614011412	percent	cpu	2026-02-24 04:05:35.828+00
\N	252	cpu_usage_percent	23.37280701749893	percent	cpu	2026-02-24 04:06:35.828+00
\N	252	cpu_usage_percent	23.751315789505554	percent	cpu	2026-02-24 04:07:35.828+00
\N	252	cpu_usage_percent	23.917543859662203	percent	cpu	2026-02-24 04:08:35.828+00
\N	252	cpu_usage_percent	24.158333333356225	percent	cpu	2026-02-24 04:09:35.828+00
\N	252	cpu_usage_percent	24.58070175438351	percent	cpu	2026-02-24 04:10:35.828+00
\N	133	cpu_usage_percent	0.43070175439903835	percent	cpu	2026-02-24 09:13:42.08+00
\N	133	cpu_usage_percent	0.4280701753879441	percent	cpu	2026-02-24 09:14:42.08+00
\N	133	cpu_usage_percent	0.550438596483076	percent	cpu	2026-02-24 09:15:42.08+00
\N	133	cpu_usage_percent	0.5618421052451907	percent	cpu	2026-02-24 09:16:42.08+00
\N	236	cpu_usage_percent	1.6210526314547735	percent	cpu	2026-02-24 07:49:21.892+00
\N	236	cpu_usage_percent	1.5192982456401865	percent	cpu	2026-02-24 07:50:21.892+00
\N	260	cpu_usage_percent	25.550328947362715	percent	cpu	2026-02-24 04:38:42.661+00
\N	260	cpu_usage_percent	25.493201754350025	percent	cpu	2026-02-24 04:39:42.661+00
\N	260	cpu_usage_percent	25.578399122786593	percent	cpu	2026-02-24 04:40:42.661+00
\N	260	cpu_usage_percent	25.621162280726267	percent	cpu	2026-02-24 04:41:42.661+00
\N	260	cpu_usage_percent	25.668530701751536	percent	cpu	2026-02-24 04:42:42.661+00
\N	260	cpu_usage_percent	25.625328947350866	percent	cpu	2026-02-24 04:43:42.661+00
\N	260	cpu_usage_percent	25.603508771960875	percent	cpu	2026-02-24 04:44:42.661+00
\N	260	cpu_usage_percent	25.480811403504703	percent	cpu	2026-02-24 04:45:42.661+00
\N	260	cpu_usage_percent	25.5324561403566	percent	cpu	2026-02-24 04:46:42.661+00
\N	236	cpu_usage_percent	1.2421052631709841	percent	cpu	2026-02-24 04:18:38.475+00
\N	236	cpu_usage_percent	1.3824561403312714	percent	cpu	2026-02-24 04:19:38.475+00
\N	236	cpu_usage_percent	1.3929824560488697	percent	cpu	2026-02-24 04:20:38.475+00
\N	236	cpu_usage_percent	1.498245614041636	percent	cpu	2026-02-24 04:21:38.475+00
\N	236	cpu_usage_percent	1.663157894815285	percent	cpu	2026-02-24 04:22:38.475+00
\N	236	cpu_usage_percent	1.5438596490901375	percent	cpu	2026-02-24 04:23:38.475+00
\N	236	cpu_usage_percent	1.6807017542356562	percent	cpu	2026-02-24 04:24:38.475+00
\N	236	cpu_usage_percent	1.7192982455813706	percent	cpu	2026-02-24 04:25:38.475+00
\N	236	cpu_usage_percent	1.4631578947107045	percent	cpu	2026-02-24 04:26:38.475+00
\N	236	cpu_usage_percent	1.4350877194093528	percent	cpu	2026-02-24 04:27:38.475+00
\N	236	cpu_usage_percent	1.5157894737887858	percent	cpu	2026-02-24 04:28:38.475+00
\N	236	cpu_usage_percent	1.505263157744423	percent	cpu	2026-02-24 04:29:38.475+00
\N	236	cpu_usage_percent	1.5017543860564189	percent	cpu	2026-02-24 04:30:38.475+00
\N	260	cpu_usage_percent	25.486622807016317	percent	cpu	2026-02-24 04:47:42.661+00
\N	260	cpu_usage_percent	25.522807017530397	percent	cpu	2026-02-24 04:48:42.661+00
\N	260	cpu_usage_percent	25.533004385978813	percent	cpu	2026-02-24 04:49:42.661+00
\N	260	cpu_usage_percent	25.524451754397006	percent	cpu	2026-02-24 04:50:42.661+00
\N	236	cpu_usage_percent	1.4807017544578684	percent	cpu	2026-02-24 07:51:21.892+00
\N	236	cpu_usage_percent	1.5017543860564189	percent	cpu	2026-02-24 07:52:21.892+00
\N	248	cpu_usage_percent	2.198684210480579	percent	cpu	2026-02-24 05:59:04.654+00
\N	248	cpu_usage_percent	2.243421052647932	percent	cpu	2026-02-24 06:00:04.654+00
\N	248	cpu_usage_percent	2.4131578948397845	percent	cpu	2026-02-24 06:01:04.654+00
\N	257	cpu_usage_percent	4.092982456133015	percent	cpu	2026-02-24 03:58:36.067+00
\N	257	cpu_usage_percent	4.485087719308879	percent	cpu	2026-02-24 03:59:36.067+00
\N	257	cpu_usage_percent	4.8903508771725654	percent	cpu	2026-02-24 04:00:36.067+00
\N	257	cpu_usage_percent	5.358771929831917	percent	cpu	2026-02-24 04:01:36.067+00
\N	257	cpu_usage_percent	5.066666666687908	percent	cpu	2026-02-24 04:02:36.067+00
\N	257	cpu_usage_percent	4.886842105259888	percent	cpu	2026-02-24 04:03:36.067+00
\N	257	cpu_usage_percent	4.523684210532039	percent	cpu	2026-02-24 04:04:36.067+00
\N	257	cpu_usage_percent	4.115789473677694	percent	cpu	2026-02-24 04:05:36.067+00
\N	257	cpu_usage_percent	3.767543859665466	percent	cpu	2026-02-24 04:06:36.067+00
\N	257	cpu_usage_percent	3.792105263135852	percent	cpu	2026-02-24 04:07:36.067+00
\N	257	cpu_usage_percent	4.02105263156588	percent	cpu	2026-02-24 04:08:36.067+00
\N	257	cpu_usage_percent	4.415789473691561	percent	cpu	2026-02-24 04:09:36.067+00
\N	257	cpu_usage_percent	4.849999999982856	percent	cpu	2026-02-24 04:10:36.067+00
\N	248	cpu_usage_percent	2.3837719297673914	percent	cpu	2026-02-24 06:02:04.654+00
\N	248	cpu_usage_percent	2.5171052631431934	percent	cpu	2026-02-24 06:03:04.654+00
\N	248	cpu_usage_percent	2.668859649188164	percent	cpu	2026-02-24 06:04:04.654+00
\N	248	cpu_usage_percent	2.6649122806102667	percent	cpu	2026-02-24 06:05:04.654+00
\N	248	cpu_usage_percent	2.5513157895112784	percent	cpu	2026-02-24 06:06:04.654+00
\N	248	cpu_usage_percent	2.5912280701378734	percent	cpu	2026-02-24 06:07:04.654+00
\N	236	cpu_usage_percent	1.512280701774003	percent	cpu	2026-02-24 07:53:21.892+00
\N	236	cpu_usage_percent	1.3824561403312714	percent	cpu	2026-02-24 07:54:21.892+00
\N	257	cpu_usage_percent	4.055263157893123	percent	cpu	2026-02-24 04:58:55.824+00
\N	257	cpu_usage_percent	4.448245614052254	percent	cpu	2026-02-24 04:59:55.824+00
\N	257	cpu_usage_percent	4.790350877201988	percent	cpu	2026-02-24 05:00:55.824+00
\N	257	cpu_usage_percent	5.172807017541416	percent	cpu	2026-02-24 05:01:55.824+00
\N	257	cpu_usage_percent	5.657894736821689	percent	cpu	2026-02-24 05:02:55.824+00
\N	257	cpu_usage_percent	5.288596491251781	percent	cpu	2026-02-24 05:03:55.824+00
\N	257	cpu_usage_percent	4.961403508756419	percent	cpu	2026-02-24 05:04:55.824+00
\N	257	cpu_usage_percent	4.366666666648712	percent	cpu	2026-02-24 05:05:55.824+00
\N	257	cpu_usage_percent	4.289473684222784	percent	cpu	2026-02-24 05:06:55.824+00
\N	257	cpu_usage_percent	3.9833333333055663	percent	cpu	2026-02-24 05:07:55.824+00
\N	257	cpu_usage_percent	4.272807017581442	percent	cpu	2026-02-24 05:08:55.824+00
\N	257	cpu_usage_percent	4.624561403547176	percent	cpu	2026-02-24 05:09:55.824+00
\N	257	cpu_usage_percent	4.95789473682332	percent	cpu	2026-02-24 05:10:55.824+00
\N	248	cpu_usage_percent	2.4258771930053484	percent	cpu	2026-02-24 06:08:04.654+00
\N	252	cpu_usage_percent	24.108771929811496	percent	cpu	2026-02-24 05:29:00.484+00
\N	252	cpu_usage_percent	24.008771929800062	percent	cpu	2026-02-24 05:30:00.484+00
\N	252	cpu_usage_percent	24.198245614023662	percent	cpu	2026-02-24 05:31:00.484+00
\N	252	cpu_usage_percent	24.00657894739294	percent	cpu	2026-02-24 05:32:00.484+00
\N	252	cpu_usage_percent	24.242982456109317	percent	cpu	2026-02-24 05:33:00.484+00
\N	252	cpu_usage_percent	24.257894736824966	percent	cpu	2026-02-24 05:34:00.484+00
\N	252	cpu_usage_percent	24.194298245588726	percent	cpu	2026-02-24 05:35:00.484+00
\N	248	cpu_usage_percent	2.066666666630738	percent	cpu	2026-02-24 04:18:38.715+00
\N	248	cpu_usage_percent	2.1701754385344145	percent	cpu	2026-02-24 04:19:38.715+00
\N	248	cpu_usage_percent	2.3250000000310536	percent	cpu	2026-02-24 04:20:38.715+00
\N	248	cpu_usage_percent	2.33289473690094	percent	cpu	2026-02-24 04:21:38.715+00
\N	248	cpu_usage_percent	2.4355263157192297	percent	cpu	2026-02-24 04:22:38.715+00
\N	248	cpu_usage_percent	2.324561403508781	percent	cpu	2026-02-24 04:23:38.715+00
\N	248	cpu_usage_percent	2.21315789477606	percent	cpu	2026-02-24 04:24:38.715+00
\N	248	cpu_usage_percent	2.3021929825067957	percent	cpu	2026-02-24 04:25:38.715+00
\N	260	cpu_usage_percent	25.526754385944912	percent	cpu	2026-02-24 03:58:36.302+00
\N	260	cpu_usage_percent	25.54703947366012	percent	cpu	2026-02-24 03:59:36.302+00
\N	260	cpu_usage_percent	25.56589912282091	percent	cpu	2026-02-24 04:00:36.302+00
\N	260	cpu_usage_percent	25.60888157892981	percent	cpu	2026-02-24 04:01:36.302+00
\N	260	cpu_usage_percent	25.65614035087556	percent	cpu	2026-02-24 04:02:36.302+00
\N	260	cpu_usage_percent	25.57883771930888	percent	cpu	2026-02-24 04:03:36.302+00
\N	260	cpu_usage_percent	25.630921052642208	percent	cpu	2026-02-24 04:04:36.302+00
\N	260	cpu_usage_percent	25.75296052628434	percent	cpu	2026-02-24 04:05:36.302+00
\N	260	cpu_usage_percent	26.126535087711545	percent	cpu	2026-02-24 04:06:36.302+00
\N	260	cpu_usage_percent	26.121710526323966	percent	cpu	2026-02-24 04:07:36.302+00
\N	260	cpu_usage_percent	26.765241228062422	percent	cpu	2026-02-24 04:08:36.302+00
\N	260	cpu_usage_percent	27.06820175436677	percent	cpu	2026-02-24 04:09:36.302+00
\N	260	cpu_usage_percent	26.76699561400855	percent	cpu	2026-02-24 04:10:36.302+00
\N	248	cpu_usage_percent	2.221491228168219	percent	cpu	2026-02-24 04:26:38.715+00
\N	248	cpu_usage_percent	2.251315789476962	percent	cpu	2026-02-24 04:27:38.715+00
\N	248	cpu_usage_percent	2.250877193036388	percent	cpu	2026-02-24 04:28:38.715+00
\N	248	cpu_usage_percent	2.1570175439691326	percent	cpu	2026-02-24 04:29:38.715+00
\N	248	cpu_usage_percent	2.1521929824692307	percent	cpu	2026-02-24 04:30:38.715+00
\N	252	cpu_usage_percent	23.960087719299878	percent	cpu	2026-02-24 05:36:00.484+00
\N	252	cpu_usage_percent	24.071929824554886	percent	cpu	2026-02-24 05:37:00.484+00
\N	252	cpu_usage_percent	23.82061403506158	percent	cpu	2026-02-24 05:38:00.484+00
\N	252	cpu_usage_percent	23.822368421089408	percent	cpu	2026-02-24 05:39:00.484+00
\N	252	cpu_usage_percent	23.598245614016307	percent	cpu	2026-02-24 05:40:00.484+00
\N	252	cpu_usage_percent	23.76491228071565	percent	cpu	2026-02-24 05:41:00.484+00
\N	248	cpu_usage_percent	2.3521929824104006	percent	cpu	2026-02-24 06:09:04.654+00
\N	248	cpu_usage_percent	2.421929824590819	percent	cpu	2026-02-24 06:10:04.654+00
\N	248	cpu_usage_percent	2.4109649123101207	percent	cpu	2026-02-24 06:11:04.654+00
\N	133	cpu_usage_percent	0.6614035087752086	percent	cpu	2026-02-24 09:17:42.08+00
\N	133	cpu_usage_percent	0.5513157895684628	percent	cpu	2026-02-24 09:18:42.08+00
\N	236	cpu_usage_percent	2.3543859650626047	percent	cpu	2026-02-24 07:09:15.59+00
\N	236	cpu_usage_percent	2.291228070103557	percent	cpu	2026-02-24 07:10:15.59+00
\N	236	cpu_usage_percent	1.6421052632167203	percent	cpu	2026-02-24 07:11:15.59+00
\N	236	cpu_usage_percent	1.4771929824430714	percent	cpu	2026-02-24 07:12:15.59+00
\N	236	cpu_usage_percent	1.5859649122872526	percent	cpu	2026-02-24 07:13:15.59+00
\N	236	cpu_usage_percent	1.750877192897505	percent	cpu	2026-02-24 07:14:15.59+00
\N	236	cpu_usage_percent	1.9122807018197534	percent	cpu	2026-02-24 07:15:15.59+00
\N	236	cpu_usage_percent	1.845614035009305	percent	cpu	2026-02-24 07:16:15.59+00
\N	236	cpu_usage_percent	1.8175438595445712	percent	cpu	2026-02-24 07:17:15.59+00
\N	236	cpu_usage_percent	1.807017543826987	percent	cpu	2026-02-24 07:18:15.59+00
\N	236	cpu_usage_percent	1.5789473684210549	percent	cpu	2026-02-24 07:19:15.59+00
\N	236	cpu_usage_percent	1.5543859648077216	percent	cpu	2026-02-24 07:20:15.59+00
\N	236	cpu_usage_percent	1.5438596490901375	percent	cpu	2026-02-24 07:21:15.59+00
\N	133	cpu_usage_percent	0.661842105297481	percent	cpu	2026-02-24 09:19:42.08+00
\N	133	cpu_usage_percent	0.5385964912803587	percent	cpu	2026-02-24 09:20:42.08+00
\N	133	cpu_usage_percent	0.4515757783861858	percent	cpu	2026-02-24 09:21:42.08+00
\N	133	cpu_usage_percent	0.6561518623133793	percent	cpu	2026-02-24 09:49:56.131+00
\N	133	cpu_usage_percent	0.5464912280277048	percent	cpu	2026-02-24 09:50:56.131+00
\N	260	cpu_usage_percent	25.47971491231135	percent	cpu	2026-02-24 04:58:56.141+00
\N	260	cpu_usage_percent	25.597368421088177	percent	cpu	2026-02-24 04:59:56.141+00
\N	260	cpu_usage_percent	25.60975877194373	percent	cpu	2026-02-24 05:00:56.141+00
\N	260	cpu_usage_percent	25.661842105266842	percent	cpu	2026-02-24 05:01:56.141+00
\N	260	cpu_usage_percent	25.72521929824194	percent	cpu	2026-02-24 05:02:56.141+00
\N	260	cpu_usage_percent	25.684210526319887	percent	cpu	2026-02-24 05:03:56.141+00
\N	260	cpu_usage_percent	25.639583333313738	percent	cpu	2026-02-24 05:04:56.141+00
\N	260	cpu_usage_percent	25.51491228071157	percent	cpu	2026-02-24 05:05:56.141+00
\N	252	cpu_usage_percent	24.780263157924963	percent	cpu	2026-02-24 04:18:38.952+00
\N	252	cpu_usage_percent	24.84736842103304	percent	cpu	2026-02-24 04:19:38.952+00
\N	252	cpu_usage_percent	24.919736842142854	percent	cpu	2026-02-24 04:20:38.952+00
\N	252	cpu_usage_percent	24.944736842094656	percent	cpu	2026-02-24 04:21:38.952+00
\N	252	cpu_usage_percent	25.352631578949	percent	cpu	2026-02-24 04:22:38.952+00
\N	252	cpu_usage_percent	25.12587719296694	percent	cpu	2026-02-24 04:23:38.952+00
\N	252	cpu_usage_percent	25.37368421052713	percent	cpu	2026-02-24 04:24:38.952+00
\N	252	cpu_usage_percent	25.163157894766258	percent	cpu	2026-02-24 04:25:38.952+00
\N	252	cpu_usage_percent	24.942543859626255	percent	cpu	2026-02-24 04:26:38.952+00
\N	252	cpu_usage_percent	24.794298245575646	percent	cpu	2026-02-24 04:27:38.952+00
\N	252	cpu_usage_percent	24.70482456144518	percent	cpu	2026-02-24 04:28:38.952+00
\N	260	cpu_usage_percent	25.58607456139535	percent	cpu	2026-02-24 05:06:56.141+00
\N	133	cpu_usage_percent	0.5478070175128238	percent	cpu	2026-02-24 09:51:56.131+00
\N	252	cpu_usage_percent	24.675438596495326	percent	cpu	2026-02-24 04:29:38.952+00
\N	252	cpu_usage_percent	24.58903508773483	percent	cpu	2026-02-24 04:30:38.952+00
\N	133	cpu_usage_percent	0.42938596491393355	percent	cpu	2026-02-24 04:48:53.131+00
\N	133	cpu_usage_percent	0.3513157895455947	percent	cpu	2026-02-24 04:49:53.131+00
\N	133	cpu_usage_percent	0.4350877192949838	percent	cpu	2026-02-24 04:50:53.131+00
\N	133	cpu_usage_percent	0.5241228070665755	percent	cpu	2026-02-24 04:51:53.131+00
\N	133	cpu_usage_percent	0.6583333333643964	percent	cpu	2026-02-24 04:52:53.131+00
\N	133	cpu_usage_percent	0.6732456140596099	percent	cpu	2026-02-24 04:53:53.131+00
\N	133	cpu_usage_percent	0.6741228070224565	percent	cpu	2026-02-24 04:54:53.131+00
\N	133	cpu_usage_percent	0.660526315812362	percent	cpu	2026-02-24 04:55:53.131+00
\N	133	cpu_usage_percent	0.46842105265936596	percent	cpu	2026-02-24 04:56:53.131+00
\N	133	cpu_usage_percent	0.4372807017021074	percent	cpu	2026-02-24 04:57:53.131+00
\N	133	cpu_usage_percent	0.42850877186938874	percent	cpu	2026-02-24 04:58:53.131+00
\N	133	cpu_usage_percent	0.4552631579307018	percent	cpu	2026-02-24 04:59:53.131+00
\N	133	cpu_usage_percent	0.6118421051896377	percent	cpu	2026-02-24 05:00:53.131+00
\N	260	cpu_usage_percent	25.522258771928605	percent	cpu	2026-02-24 05:07:56.141+00
\N	260	cpu_usage_percent	25.56217105265732	percent	cpu	2026-02-24 05:08:56.141+00
\N	260	cpu_usage_percent	25.56008771930928	percent	cpu	2026-02-24 05:09:56.141+00
\N	260	cpu_usage_percent	25.587609649131394	percent	cpu	2026-02-24 05:10:56.141+00
\N	133	cpu_usage_percent	0.4359649123395428	percent	cpu	2026-02-24 09:52:56.131+00
\N	133	cpu_usage_percent	0.43991228075405786	percent	cpu	2026-02-24 09:53:56.131+00
\N	133	cpu_usage_percent	0.42850877195107273	percent	cpu	2026-02-24 09:54:56.131+00
\N	248	cpu_usage_percent	2.4916666666487117	percent	cpu	2026-02-24 06:29:09.533+00
\N	248	cpu_usage_percent	2.3964912280554813	percent	cpu	2026-02-24 06:30:09.533+00
\N	248	cpu_usage_percent	2.592982456186107	percent	cpu	2026-02-24 06:31:09.533+00
\N	248	cpu_usage_percent	2.5578947368551894	percent	cpu	2026-02-24 06:32:09.533+00
\N	248	cpu_usage_percent	2.838157894694376	percent	cpu	2026-02-24 06:33:09.533+00
\N	248	cpu_usage_percent	3.3964912281290083	percent	cpu	2026-02-24 06:34:09.533+00
\N	248	cpu_usage_percent	3.453947368461911	percent	cpu	2026-02-24 06:35:09.533+00
\N	248	cpu_usage_percent	3.4517543860139455	percent	cpu	2026-02-24 06:36:09.533+00
\N	248	cpu_usage_percent	3.428070175445143	percent	cpu	2026-02-24 06:37:09.533+00
\N	248	cpu_usage_percent	2.9241228070551273	percent	cpu	2026-02-24 06:38:09.533+00
\N	257	cpu_usage_percent	4.285087719306418	percent	cpu	2026-02-24 05:29:00.717+00
\N	257	cpu_usage_percent	4.671929824562241	percent	cpu	2026-02-24 05:30:00.717+00
\N	257	cpu_usage_percent	5.0622807017307	percent	cpu	2026-02-24 05:31:00.717+00
\N	257	cpu_usage_percent	5.266666666649527	percent	cpu	2026-02-24 05:32:00.717+00
\N	257	cpu_usage_percent	5.518421052624234	percent	cpu	2026-02-24 05:33:00.717+00
\N	257	cpu_usage_percent	5.195614035126937	percent	cpu	2026-02-24 05:34:00.717+00
\N	257	cpu_usage_percent	4.807894736826597	percent	cpu	2026-02-24 05:35:00.717+00
\N	257	cpu_usage_percent	3.839473684212166	percent	cpu	2026-02-24 04:18:39.193+00
\N	257	cpu_usage_percent	4.405263157871872	percent	cpu	2026-02-24 04:19:39.193+00
\N	257	cpu_usage_percent	4.764035087683354	percent	cpu	2026-02-24 04:20:39.193+00
\N	257	cpu_usage_percent	5.339473684220337	percent	cpu	2026-02-24 04:21:39.193+00
\N	257	cpu_usage_percent	5.610526315786217	percent	cpu	2026-02-24 04:22:39.193+00
\N	257	cpu_usage_percent	5.106140350894364	percent	cpu	2026-02-24 04:23:39.193+00
\N	257	cpu_usage_percent	4.973684210522251	percent	cpu	2026-02-24 04:24:39.193+00
\N	257	cpu_usage_percent	4.565789473688312	percent	cpu	2026-02-24 04:25:39.193+00
\N	257	cpu_usage_percent	3.87807017543534	percent	cpu	2026-02-24 04:26:39.193+00
\N	257	cpu_usage_percent	3.816666666667487	percent	cpu	2026-02-24 04:27:39.193+00
\N	257	cpu_usage_percent	4.056140350876376	percent	cpu	2026-02-24 04:28:39.193+00
\N	257	cpu_usage_percent	4.41754385965811	percent	cpu	2026-02-24 04:29:39.193+00
\N	257	cpu_usage_percent	4.7649122806870565	percent	cpu	2026-02-24 04:30:39.193+00
\N	257	cpu_usage_percent	4.420175438607927	percent	cpu	2026-02-24 05:36:00.717+00
\N	257	cpu_usage_percent	4.233333333334173	percent	cpu	2026-02-24 05:37:00.717+00
\N	257	cpu_usage_percent	4.004385964924538	percent	cpu	2026-02-24 05:38:00.717+00
\N	257	cpu_usage_percent	4.3061403508845615	percent	cpu	2026-02-24 05:39:00.717+00
\N	257	cpu_usage_percent	4.680701754354118	percent	cpu	2026-02-24 05:40:00.717+00
\N	257	cpu_usage_percent	5.014912280674807	percent	cpu	2026-02-24 05:41:00.717+00
\N	248	cpu_usage_percent	2.434649122756369	percent	cpu	2026-02-24 06:39:09.533+00
\N	248	cpu_usage_percent	2.414035087802631	percent	cpu	2026-02-24 06:40:09.533+00
\N	248	cpu_usage_percent	2.3324561403378112	percent	cpu	2026-02-24 06:41:09.533+00
\N	252	cpu_usage_percent	23.52719298245289	percent	cpu	2026-02-24 05:59:04.933+00
\N	252	cpu_usage_percent	23.695614035077924	percent	cpu	2026-02-24 06:00:04.933+00
\N	252	cpu_usage_percent	23.43903508772584	percent	cpu	2026-02-24 06:01:04.933+00
\N	252	cpu_usage_percent	21.86842105265609	percent	cpu	2026-02-24 06:02:04.933+00
\N	236	cpu_usage_percent	1.3901656830347662	percent	cpu	2026-02-24 04:48:53.387+00
\N	236	cpu_usage_percent	1.2421052631709841	percent	cpu	2026-02-24 04:49:53.387+00
\N	236	cpu_usage_percent	1.3649122807475038	percent	cpu	2026-02-24 04:50:53.387+00
\N	236	cpu_usage_percent	1.5052631579078195	percent	cpu	2026-02-24 04:51:53.387+00
\N	236	cpu_usage_percent	1.6771929823842555	percent	cpu	2026-02-24 04:52:53.387+00
\N	236	cpu_usage_percent	1.6807017543990526	percent	cpu	2026-02-24 04:53:53.387+00
\N	236	cpu_usage_percent	1.6701754386814684	percent	cpu	2026-02-24 04:54:53.387+00
\N	236	cpu_usage_percent	1.670175438518072	percent	cpu	2026-02-24 04:55:53.387+00
\N	236	cpu_usage_percent	1.5438596490901375	percent	cpu	2026-02-24 04:56:53.387+00
\N	236	cpu_usage_percent	1.3684210525989045	percent	cpu	2026-02-24 04:57:53.387+00
\N	236	cpu_usage_percent	1.3789473683165028	percent	cpu	2026-02-24 04:58:53.387+00
\N	236	cpu_usage_percent	1.392982456212252	percent	cpu	2026-02-24 04:59:53.387+00
\N	236	cpu_usage_percent	1.2491228070371676	percent	cpu	2026-02-24 05:00:53.387+00
\N	252	cpu_usage_percent	22.046491228076718	percent	cpu	2026-02-24 06:03:04.933+00
\N	252	cpu_usage_percent	22.248245614045715	percent	cpu	2026-02-24 06:04:04.933+00
\N	252	cpu_usage_percent	21.69956140348836	percent	cpu	2026-02-24 06:05:04.933+00
\N	252	cpu_usage_percent	22.516228070159926	percent	cpu	2026-02-24 06:06:04.933+00
\N	133	cpu_usage_percent	2.0140350877160387	percent	cpu	2026-02-24 05:08:56.445+00
\N	133	cpu_usage_percent	1.3877192982309197	percent	cpu	2026-02-24 05:09:56.445+00
\N	133	cpu_usage_percent	0.3486842104936443	percent	cpu	2026-02-24 05:10:56.445+00
\N	133	cpu_usage_percent	0.4166666666258294	percent	cpu	2026-02-24 05:11:56.445+00
\N	133	cpu_usage_percent	0.6456140351171342	percent	cpu	2026-02-24 05:12:56.445+00
\N	133	cpu_usage_percent	0.6298245614182179	percent	cpu	2026-02-24 05:13:56.445+00
\N	133	cpu_usage_percent	0.6315789473439253	percent	cpu	2026-02-24 05:14:56.445+00
\N	260	cpu_usage_percent	25.519517543868645	percent	cpu	2026-02-24 04:18:39.436+00
\N	260	cpu_usage_percent	25.583004385984538	percent	cpu	2026-02-24 04:19:39.436+00
\N	260	cpu_usage_percent	25.579934210543072	percent	cpu	2026-02-24 04:20:39.436+00
\N	260	cpu_usage_percent	25.567324561375344	percent	cpu	2026-02-24 04:21:39.436+00
\N	260	cpu_usage_percent	25.5856359648935	percent	cpu	2026-02-24 04:22:39.436+00
\N	260	cpu_usage_percent	25.536951754352472	percent	cpu	2026-02-24 04:23:39.436+00
\N	133	cpu_usage_percent	0.6504385965761941	percent	cpu	2026-02-24 05:15:56.445+00
\N	133	cpu_usage_percent	0.5140350877487236	percent	cpu	2026-02-24 09:55:56.131+00
\N	260	cpu_usage_percent	25.547807017553666	percent	cpu	2026-02-24 04:24:39.436+00
\N	260	cpu_usage_percent	25.525109649129348	percent	cpu	2026-02-24 04:25:39.436+00
\N	260	cpu_usage_percent	25.57434210528237	percent	cpu	2026-02-24 04:26:39.436+00
\N	260	cpu_usage_percent	25.539692982483913	percent	cpu	2026-02-24 04:27:39.436+00
\N	260	cpu_usage_percent	25.61611842106734	percent	cpu	2026-02-24 04:28:39.436+00
\N	260	cpu_usage_percent	25.566118421051414	percent	cpu	2026-02-24 04:29:39.436+00
\N	260	cpu_usage_percent	25.623574561394534	percent	cpu	2026-02-24 04:30:39.436+00
\N	133	cpu_usage_percent	0.5653508772191458	percent	cpu	2026-02-24 05:16:56.445+00
\N	133	cpu_usage_percent	0.42149122812573125	percent	cpu	2026-02-24 05:17:56.445+00
\N	133	cpu_usage_percent	0.9741228069750747	percent	cpu	2026-02-24 05:18:56.445+00
\N	133	cpu_usage_percent	1.2298245613642962	percent	cpu	2026-02-24 05:19:56.445+00
\N	133	cpu_usage_percent	1.2228070174981127	percent	cpu	2026-02-24 05:20:56.445+00
\N	252	cpu_usage_percent	23.691228070181978	percent	cpu	2026-02-24 06:07:04.933+00
\N	252	cpu_usage_percent	23.529824561402705	percent	cpu	2026-02-24 06:08:04.933+00
\N	252	cpu_usage_percent	23.526754385951037	percent	cpu	2026-02-24 06:09:04.933+00
\N	252	cpu_usage_percent	23.95657894732595	percent	cpu	2026-02-24 06:10:04.933+00
\N	252	cpu_usage_percent	23.925000000009817	percent	cpu	2026-02-24 06:11:04.933+00
\N	133	cpu_usage_percent	0.5631578948120222	percent	cpu	2026-02-24 09:56:56.131+00
\N	133	cpu_usage_percent	0.6741228070224565	percent	cpu	2026-02-24 09:57:56.131+00
\N	133	cpu_usage_percent	0.6614035088569068	percent	cpu	2026-02-24 09:58:56.131+00
\N	133	cpu_usage_percent	0.6653508771488674	percent	cpu	2026-02-24 09:59:56.131+00
\N	133	cpu_usage_percent	0.44736842110165753	percent	cpu	2026-02-24 10:00:56.131+00
\N	133	cpu_usage_percent	0.4934210526315894	percent	cpu	2026-02-24 10:01:56.131+00
\N	248	cpu_usage_percent	2.3241228069865087	percent	cpu	2026-02-24 07:09:15.834+00
\N	248	cpu_usage_percent	2.2929824560701064	percent	cpu	2026-02-24 07:10:15.834+00
\N	248	cpu_usage_percent	2.229385964997249	percent	cpu	2026-02-24 07:11:15.834+00
\N	248	cpu_usage_percent	2.158771929853984	percent	cpu	2026-02-24 07:12:15.834+00
\N	248	cpu_usage_percent	2.19517543854748	percent	cpu	2026-02-24 07:13:15.834+00
\N	248	cpu_usage_percent	2.2842105262782155	percent	cpu	2026-02-24 07:14:15.834+00
\N	248	cpu_usage_percent	2.3438596491816384	percent	cpu	2026-02-24 04:48:53.658+00
\N	248	cpu_usage_percent	2.2557017543729074	percent	cpu	2026-02-24 04:49:53.658+00
\N	248	cpu_usage_percent	2.356578947347188	percent	cpu	2026-02-24 04:50:53.658+00
\N	248	cpu_usage_percent	2.35614035094747	percent	cpu	2026-02-24 04:51:53.658+00
\N	248	cpu_usage_percent	2.452631578984949	percent	cpu	2026-02-24 04:52:53.658+00
\N	248	cpu_usage_percent	2.42543859644222	percent	cpu	2026-02-24 04:53:53.658+00
\N	248	cpu_usage_percent	2.3070175438024734	percent	cpu	2026-02-24 04:54:53.658+00
\N	248	cpu_usage_percent	2.3061403508804688	percent	cpu	2026-02-24 04:55:53.658+00
\N	248	cpu_usage_percent	2.3311403508935484	percent	cpu	2026-02-24 04:56:53.658+00
\N	248	cpu_usage_percent	2.275877192886071	percent	cpu	2026-02-24 04:57:53.658+00
\N	248	cpu_usage_percent	2.265789473649903	percent	cpu	2026-02-24 04:58:53.658+00
\N	248	cpu_usage_percent	2.3030701754696423	percent	cpu	2026-02-24 04:59:53.658+00
\N	133	cpu_usage_percent	0.43026315787678016	percent	cpu	2026-02-24 04:28:39.669+00
\N	133	cpu_usage_percent	0.453070175482722	percent	cpu	2026-02-24 04:29:39.669+00
\N	133	cpu_usage_percent	0.44166666672059307	percent	cpu	2026-02-24 04:30:39.669+00
\N	133	cpu_usage_percent	0.5561403508641263	percent	cpu	2026-02-24 04:31:39.669+00
\N	133	cpu_usage_percent	0.6828947368960314	percent	cpu	2026-02-24 04:32:39.669+00
\N	133	cpu_usage_percent	0.6828947368551894	percent	cpu	2026-02-24 04:33:39.669+00
\N	133	cpu_usage_percent	0.6684210526005359	percent	cpu	2026-02-24 04:34:39.669+00
\N	133	cpu_usage_percent	0.6793859649629468	percent	cpu	2026-02-24 04:35:39.669+00
\N	133	cpu_usage_percent	0.4991228070126539	percent	cpu	2026-02-24 04:36:39.669+00
\N	133	cpu_usage_percent	0.43859649126892464	percent	cpu	2026-02-24 04:37:39.669+00
\N	133	cpu_usage_percent	0.4368421052206912	percent	cpu	2026-02-24 04:38:39.669+00
\N	133	cpu_usage_percent	0.3324561403950099	percent	cpu	2026-02-24 04:39:39.669+00
\N	133	cpu_usage_percent	0.45087719295305817	percent	cpu	2026-02-24 04:40:39.669+00
\N	248	cpu_usage_percent	2.4078947368584522	percent	cpu	2026-02-24 05:00:53.658+00
\N	248	cpu_usage_percent	2.3815789474011098	percent	cpu	2026-02-24 07:15:15.834+00
\N	248	cpu_usage_percent	2.3592105263174403	percent	cpu	2026-02-24 07:16:15.834+00
\N	248	cpu_usage_percent	2.342105263133405	percent	cpu	2026-02-24 07:17:15.834+00
\N	248	cpu_usage_percent	2.385964912256199	percent	cpu	2026-02-24 07:18:15.834+00
\N	248	cpu_usage_percent	2.2916666666666714	percent	cpu	2026-02-24 07:19:15.834+00
\N	248	cpu_usage_percent	2.50745614038847	percent	cpu	2026-02-24 07:20:15.834+00
\N	260	cpu_usage_percent	25.588706140314528	percent	cpu	2026-02-24 05:29:00.944+00
\N	260	cpu_usage_percent	25.5705043859882	percent	cpu	2026-02-24 05:30:00.944+00
\N	260	cpu_usage_percent	25.555372807001206	percent	cpu	2026-02-24 05:31:00.944+00
\N	260	cpu_usage_percent	25.525548245620982	percent	cpu	2026-02-24 05:32:00.944+00
\N	260	cpu_usage_percent	25.701096491252997	percent	cpu	2026-02-24 05:33:00.944+00
\N	260	cpu_usage_percent	25.643311403518183	percent	cpu	2026-02-24 05:34:00.944+00
\N	260	cpu_usage_percent	25.69188596492863	percent	cpu	2026-02-24 05:35:00.944+00
\N	260	cpu_usage_percent	25.639583333313738	percent	cpu	2026-02-24 05:36:00.944+00
\N	260	cpu_usage_percent	25.58114035087719	percent	cpu	2026-02-24 05:37:00.944+00
\N	260	cpu_usage_percent	25.497149122805396	percent	cpu	2026-02-24 05:38:00.944+00
\N	260	cpu_usage_percent	25.523684210554507	percent	cpu	2026-02-24 05:39:00.944+00
\N	236	cpu_usage_percent	1.4350877194093528	percent	cpu	2026-02-24 05:08:56.724+00
\N	236	cpu_usage_percent	1.428070175379787	percent	cpu	2026-02-24 05:09:56.724+00
\N	236	cpu_usage_percent	1.3052631578032532	percent	cpu	2026-02-24 05:10:56.724+00
\N	236	cpu_usage_percent	1.4421052632755504	percent	cpu	2026-02-24 05:11:56.724+00
\N	236	cpu_usage_percent	1.7228070175961534	percent	cpu	2026-02-24 05:12:56.724+00
\N	236	cpu_usage_percent	1.7333333333137375	percent	cpu	2026-02-24 05:13:56.724+00
\N	236	cpu_usage_percent	3.1754385964258773	percent	cpu	2026-02-24 05:14:56.724+00
\N	236	cpu_usage_percent	3.1859649123068436	percent	cpu	2026-02-24 05:15:56.724+00
\N	236	cpu_usage_percent	3.0736842106112903	percent	cpu	2026-02-24 05:16:56.724+00
\N	236	cpu_usage_percent	2.9368421053023894	percent	cpu	2026-02-24 05:17:56.724+00
\N	236	cpu_usage_percent	1.536842105223954	percent	cpu	2026-02-24 05:18:56.724+00
\N	236	cpu_usage_percent	1.5157894737887858	percent	cpu	2026-02-24 05:19:56.724+00
\N	236	cpu_usage_percent	1.5052631579078195	percent	cpu	2026-02-24 05:20:56.724+00
\N	260	cpu_usage_percent	25.528070175450452	percent	cpu	2026-02-24 05:40:00.944+00
\N	260	cpu_usage_percent	25.561951754406394	percent	cpu	2026-02-24 05:41:00.944+00
\N	248	cpu_usage_percent	2.529385964909025	percent	cpu	2026-02-24 07:21:15.834+00
\N	236	cpu_usage_percent	1.8421052631579045	percent	cpu	2026-02-24 09:09:42.762+00
\N	236	cpu_usage_percent	1.7052631580124	percent	cpu	2026-02-24 09:10:42.762+00
\N	236	cpu_usage_percent	1.5649122808520843	percent	cpu	2026-02-24 09:11:42.762+00
\N	236	cpu_usage_percent	1.3578947368813346	percent	cpu	2026-02-24 04:28:39.968+00
\N	236	cpu_usage_percent	1.5192982456401865	percent	cpu	2026-02-24 09:12:42.762+00
\N	236	cpu_usage_percent	1.5333333333725534	percent	cpu	2026-02-24 09:13:42.762+00
\N	236	cpu_usage_percent	1.4912280701754668	percent	cpu	2026-02-24 04:29:39.968+00
\N	236	cpu_usage_percent	1.4982456140416502	percent	cpu	2026-02-24 04:30:39.968+00
\N	236	cpu_usage_percent	1.6245614034695848	percent	cpu	2026-02-24 04:31:39.968+00
\N	236	cpu_usage_percent	1.7263157894475682	percent	cpu	2026-02-24 04:32:39.968+00
\N	236	cpu_usage_percent	1.6842105262504532	percent	cpu	2026-02-24 04:33:39.968+00
\N	236	cpu_usage_percent	1.7508771928975193	percent	cpu	2026-02-24 04:34:39.968+00
\N	236	cpu_usage_percent	1.7508771928975193	percent	cpu	2026-02-24 04:35:39.968+00
\N	236	cpu_usage_percent	1.4771929824430856	percent	cpu	2026-02-24 04:36:39.968+00
\N	236	cpu_usage_percent	1.4491228069783517	percent	cpu	2026-02-24 04:37:39.968+00
\N	236	cpu_usage_percent	1.4421052632755647	percent	cpu	2026-02-24 04:38:39.968+00
\N	236	cpu_usage_percent	1.350877193015151	percent	cpu	2026-02-24 04:39:39.968+00
\N	236	cpu_usage_percent	1.3614035087327352	percent	cpu	2026-02-24 04:40:39.968+00
\N	252	cpu_usage_percent	24.898684210523868	percent	cpu	2026-02-24 04:48:53.929+00
\N	252	cpu_usage_percent	24.785964912265186	percent	cpu	2026-02-24 04:49:53.929+00
\N	252	cpu_usage_percent	24.66666666666258	percent	cpu	2026-02-24 04:50:53.929+00
\N	252	cpu_usage_percent	24.737719298246446	percent	cpu	2026-02-24 04:51:53.929+00
\N	252	cpu_usage_percent	24.92894736839574	percent	cpu	2026-02-24 04:52:53.929+00
\N	252	cpu_usage_percent	24.890789473674417	percent	cpu	2026-02-24 04:53:53.929+00
\N	252	cpu_usage_percent	24.64868421049529	percent	cpu	2026-02-24 04:54:53.929+00
\N	252	cpu_usage_percent	24.764473684185205	percent	cpu	2026-02-24 04:55:53.929+00
\N	252	cpu_usage_percent	24.604824561392903	percent	cpu	2026-02-24 04:56:53.929+00
\N	252	cpu_usage_percent	24.35614035082901	percent	cpu	2026-02-24 04:57:53.929+00
\N	252	cpu_usage_percent	24.319298245633647	percent	cpu	2026-02-24 04:58:53.929+00
\N	252	cpu_usage_percent	24.436842105249283	percent	cpu	2026-02-24 04:59:53.929+00
\N	252	cpu_usage_percent	24.371929824548346	percent	cpu	2026-02-24 05:00:53.929+00
\N	236	cpu_usage_percent	2.3789473683491735	percent	cpu	2026-02-24 08:29:32.846+00
\N	236	cpu_usage_percent	2.2140350875755246	percent	cpu	2026-02-24 08:30:32.846+00
\N	236	cpu_usage_percent	2.1438596492404542	percent	cpu	2026-02-24 08:31:32.846+00
\N	236	cpu_usage_percent	2.157894736809439	percent	cpu	2026-02-24 08:32:32.846+00
\N	236	cpu_usage_percent	1.5333333333725534	percent	cpu	2026-02-24 08:33:32.846+00
\N	252	cpu_usage_percent	24.457894736847834	percent	cpu	2026-02-24 06:29:09.76+00
\N	257	cpu_usage_percent	4.3280701754663795	percent	cpu	2026-02-24 05:59:05.2+00
\N	257	cpu_usage_percent	4.7263157895047385	percent	cpu	2026-02-24 06:00:05.2+00
\N	257	cpu_usage_percent	5.025438596514931	percent	cpu	2026-02-24 06:01:05.2+00
\N	257	cpu_usage_percent	5.014035087732367	percent	cpu	2026-02-24 06:02:05.2+00
\N	257	cpu_usage_percent	5.152631578946568	percent	cpu	2026-02-24 06:03:05.2+00
\N	257	cpu_usage_percent	4.827192982458612	percent	cpu	2026-02-24 06:04:05.2+00
\N	257	cpu_usage_percent	4.407017543879263	percent	cpu	2026-02-24 06:05:05.2+00
\N	257	cpu_usage_percent	4.15087719298819	percent	cpu	2026-02-24 06:06:05.2+00
\N	257	cpu_usage_percent	4.273684210523882	percent	cpu	2026-02-24 06:07:05.2+00
\N	257	cpu_usage_percent	3.9438596490991245	percent	cpu	2026-02-24 06:08:05.2+00
\N	257	cpu_usage_percent	4.01491228072382	percent	cpu	2026-02-24 06:09:05.2+00
\N	257	cpu_usage_percent	4.641228070168097	percent	cpu	2026-02-24 06:10:05.2+00
\N	257	cpu_usage_percent	5.04473684210609	percent	cpu	2026-02-24 06:11:05.2+00
\N	248	cpu_usage_percent	2.250877193036388	percent	cpu	2026-02-24 04:28:40.257+00
\N	248	cpu_usage_percent	2.1570175439691326	percent	cpu	2026-02-24 04:29:40.257+00
\N	248	cpu_usage_percent	2.1521929824692307	percent	cpu	2026-02-24 04:30:40.257+00
\N	248	cpu_usage_percent	2.1675438596867167	percent	cpu	2026-02-24 04:31:40.257+00
\N	248	cpu_usage_percent	2.238596491229714	percent	cpu	2026-02-24 04:32:40.257+00
\N	248	cpu_usage_percent	2.284649122800488	percent	cpu	2026-02-24 04:33:40.257+00
\N	248	cpu_usage_percent	2.3135964912280826	percent	cpu	2026-02-24 04:34:40.257+00
\N	248	cpu_usage_percent	2.4092105263027292	percent	cpu	2026-02-24 04:35:40.257+00
\N	248	cpu_usage_percent	2.3530701754140892	percent	cpu	2026-02-24 04:36:40.257+00
\N	248	cpu_usage_percent	2.271491228071824	percent	cpu	2026-02-24 04:37:40.257+00
\N	248	cpu_usage_percent	2.221929824527109	percent	cpu	2026-02-24 04:38:40.257+00
\N	248	cpu_usage_percent	2.135964912329726	percent	cpu	2026-02-24 04:39:40.257+00
\N	248	cpu_usage_percent	2.1877192982815643	percent	cpu	2026-02-24 04:40:40.257+00
\N	252	cpu_usage_percent	24.35087719290894	percent	cpu	2026-02-24 06:30:09.76+00
\N	252	cpu_usage_percent	25.085964912299502	percent	cpu	2026-02-24 06:31:09.76+00
\N	252	cpu_usage_percent	25.412280701770726	percent	cpu	2026-02-24 06:32:09.76+00
\N	252	cpu_usage_percent	26.57675438595267	percent	cpu	2026-02-24 06:33:09.76+00
\N	252	cpu_usage_percent	27.82500000002696	percent	cpu	2026-02-24 06:34:09.76+00
\N	252	cpu_usage_percent	28.03201754387517	percent	cpu	2026-02-24 06:35:09.76+00
\N	248	cpu_usage_percent	2.261842105194546	percent	cpu	2026-02-24 05:08:56.961+00
\N	248	cpu_usage_percent	2.339473684244851	percent	cpu	2026-02-24 05:09:56.961+00
\N	248	cpu_usage_percent	2.4017543859959716	percent	cpu	2026-02-24 05:10:56.961+00
\N	248	cpu_usage_percent	2.4197368420203134	percent	cpu	2026-02-24 05:11:56.961+00
\N	248	cpu_usage_percent	2.4596491228102906	percent	cpu	2026-02-24 05:12:56.961+00
\N	248	cpu_usage_percent	2.372807017486693	percent	cpu	2026-02-24 05:13:56.961+00
\N	248	cpu_usage_percent	2.2942982455960674	percent	cpu	2026-02-24 05:14:56.961+00
\N	248	cpu_usage_percent	2.2416666666405263	percent	cpu	2026-02-24 05:15:56.961+00
\N	248	cpu_usage_percent	2.271929824512398	percent	cpu	2026-02-24 05:16:56.961+00
\N	257	cpu_usage_percent	4.083333333296579	percent	cpu	2026-02-24 04:48:54.26+00
\N	257	cpu_usage_percent	4.235087719300708	percent	cpu	2026-02-24 04:49:54.26+00
\N	257	cpu_usage_percent	4.8570175438490395	percent	cpu	2026-02-24 04:50:54.26+00
\N	257	cpu_usage_percent	5.120175438606296	percent	cpu	2026-02-24 04:51:54.26+00
\N	257	cpu_usage_percent	5.512280701720911	percent	cpu	2026-02-24 04:52:54.26+00
\N	257	cpu_usage_percent	5.138596491234608	percent	cpu	2026-02-24 04:53:54.26+00
\N	257	cpu_usage_percent	4.79298245615179	percent	cpu	2026-02-24 04:54:54.26+00
\N	257	cpu_usage_percent	4.363157894715613	percent	cpu	2026-02-24 04:55:54.26+00
\N	257	cpu_usage_percent	4.070175438608757	percent	cpu	2026-02-24 04:56:54.26+00
\N	257	cpu_usage_percent	3.800877192989006	percent	cpu	2026-02-24 04:57:54.26+00
\N	257	cpu_usage_percent	4.055263157893123	percent	cpu	2026-02-24 04:58:54.26+00
\N	257	cpu_usage_percent	4.448245614052254	percent	cpu	2026-02-24 04:59:54.26+00
\N	257	cpu_usage_percent	4.790350877201988	percent	cpu	2026-02-24 05:00:54.26+00
\N	248	cpu_usage_percent	2.193859649103217	percent	cpu	2026-02-24 05:17:56.961+00
\N	248	cpu_usage_percent	2.2271929825084413	percent	cpu	2026-02-24 05:18:56.961+00
\N	248	cpu_usage_percent	2.5631578947139815	percent	cpu	2026-02-24 05:19:56.961+00
\N	248	cpu_usage_percent	2.6385964912754645	percent	cpu	2026-02-24 05:20:56.961+00
\N	252	cpu_usage_percent	28.378508771879993	percent	cpu	2026-02-24 06:36:09.76+00
\N	252	cpu_usage_percent	29.333333333345607	percent	cpu	2026-02-24 06:37:09.76+00
\N	236	cpu_usage_percent	1.554385964971118	percent	cpu	2026-02-24 08:34:32.846+00
\N	252	cpu_usage_percent	28.39035087720525	percent	cpu	2026-02-24 06:38:09.76+00
\N	133	cpu_usage_percent	0.4228070175291663	percent	cpu	2026-02-24 05:39:01.175+00
\N	133	cpu_usage_percent	0.4179824561109484	percent	cpu	2026-02-24 05:40:01.175+00
\N	133	cpu_usage_percent	0.41842105259237883	percent	cpu	2026-02-24 05:41:01.175+00
\N	252	cpu_usage_percent	24.70482456144518	percent	cpu	2026-02-24 04:28:40.532+00
\N	252	cpu_usage_percent	24.675438596495326	percent	cpu	2026-02-24 04:29:40.532+00
\N	252	cpu_usage_percent	24.58903508773483	percent	cpu	2026-02-24 04:30:40.532+00
\N	252	cpu_usage_percent	24.62675438597472	percent	cpu	2026-02-24 04:31:40.532+00
\N	252	cpu_usage_percent	24.783771929858062	percent	cpu	2026-02-24 04:32:40.532+00
\N	252	cpu_usage_percent	24.683333333324356	percent	cpu	2026-02-24 04:33:40.532+00
\N	252	cpu_usage_percent	24.865350877220777	percent	cpu	2026-02-24 04:34:40.532+00
\N	252	cpu_usage_percent	25.24254385966057	percent	cpu	2026-02-24 04:35:40.532+00
\N	252	cpu_usage_percent	25.024122806968535	percent	cpu	2026-02-24 04:36:40.532+00
\N	252	cpu_usage_percent	24.968421052622602	percent	cpu	2026-02-24 04:37:40.532+00
\N	252	cpu_usage_percent	24.991228070208123	percent	cpu	2026-02-24 04:38:40.532+00
\N	252	cpu_usage_percent	24.801315789503093	percent	cpu	2026-02-24 04:39:40.532+00
\N	252	cpu_usage_percent	24.619736842108537	percent	cpu	2026-02-24 04:40:40.532+00
\N	133	cpu_usage_percent	0.4236842105328549	percent	cpu	2026-02-24 05:42:01.175+00
\N	133	cpu_usage_percent	0.5684210526708	percent	cpu	2026-02-24 05:43:01.175+00
\N	133	cpu_usage_percent	0.5807017543549335	percent	cpu	2026-02-24 05:44:01.175+00
\N	133	cpu_usage_percent	0.5820175438400526	percent	cpu	2026-02-24 05:45:01.175+00
\N	133	cpu_usage_percent	0.5807017543549335	percent	cpu	2026-02-24 05:46:01.175+00
\N	133	cpu_usage_percent	0.5842105262880182	percent	cpu	2026-02-24 05:47:01.175+00
\N	133	cpu_usage_percent	0.321052631592039	percent	cpu	2026-02-24 05:48:01.175+00
\N	133	cpu_usage_percent	0.4258771930216909	percent	cpu	2026-02-24 05:49:01.175+00
\N	133	cpu_usage_percent	0.5649122807377012	percent	cpu	2026-02-24 05:50:01.175+00
\N	133	cpu_usage_percent	0.5793859649515127	percent	cpu	2026-02-24 05:51:01.175+00
\N	252	cpu_usage_percent	27.893859649121993	percent	cpu	2026-02-24 06:39:09.76+00
\N	252	cpu_usage_percent	27.799561403512058	percent	cpu	2026-02-24 06:40:09.76+00
\N	252	cpu_usage_percent	26.74385964913344	percent	cpu	2026-02-24 06:41:09.76+00
\N	248	cpu_usage_percent	2.365350877179921	percent	cpu	2026-02-24 07:49:22.128+00
\N	248	cpu_usage_percent	2.3144736842317712	percent	cpu	2026-02-24 07:50:22.128+00
\N	248	cpu_usage_percent	2.459649122891989	percent	cpu	2026-02-24 07:51:22.128+00
\N	248	cpu_usage_percent	2.4368421052043487	percent	cpu	2026-02-24 07:52:22.128+00
\N	260	cpu_usage_percent	25.492543859699367	percent	cpu	2026-02-24 04:48:54.509+00
\N	260	cpu_usage_percent	25.530482456128922	percent	cpu	2026-02-24 04:49:54.509+00
\N	260	cpu_usage_percent	25.558114035071384	percent	cpu	2026-02-24 04:50:54.509+00
\N	260	cpu_usage_percent	25.519517543868645	percent	cpu	2026-02-24 04:51:54.509+00
\N	260	cpu_usage_percent	25.637499999965698	percent	cpu	2026-02-24 04:52:54.509+00
\N	260	cpu_usage_percent	25.559210526325998	percent	cpu	2026-02-24 04:53:54.509+00
\N	260	cpu_usage_percent	25.587609649090552	percent	cpu	2026-02-24 04:54:54.509+00
\N	260	cpu_usage_percent	25.548574561406383	percent	cpu	2026-02-24 04:55:54.509+00
\N	260	cpu_usage_percent	25.516885964898407	percent	cpu	2026-02-24 04:56:54.509+00
\N	260	cpu_usage_percent	25.485526315761703	percent	cpu	2026-02-24 04:57:54.509+00
\N	257	cpu_usage_percent	4.056140350876376	percent	cpu	2026-02-24 04:28:40.811+00
\N	257	cpu_usage_percent	4.41754385965811	percent	cpu	2026-02-24 04:29:40.811+00
\N	257	cpu_usage_percent	4.7649122806870565	percent	cpu	2026-02-24 04:30:40.811+00
\N	257	cpu_usage_percent	5.292105263144023	percent	cpu	2026-02-24 04:31:40.811+00
\N	257	cpu_usage_percent	5.588596491224806	percent	cpu	2026-02-24 04:32:40.811+00
\N	257	cpu_usage_percent	5.285087719298247	percent	cpu	2026-02-24 04:33:40.811+00
\N	257	cpu_usage_percent	4.89999999998858	percent	cpu	2026-02-24 04:34:40.811+00
\N	257	cpu_usage_percent	4.597368421065724	percent	cpu	2026-02-24 04:35:40.811+00
\N	257	cpu_usage_percent	4.127192982460244	percent	cpu	2026-02-24 04:36:40.811+00
\N	257	cpu_usage_percent	3.8543859649278147	percent	cpu	2026-02-24 04:37:40.811+00
\N	257	cpu_usage_percent	4.058771929826207	percent	cpu	2026-02-24 04:38:40.811+00
\N	257	cpu_usage_percent	4.182456140345167	percent	cpu	2026-02-24 04:39:40.811+00
\N	257	cpu_usage_percent	4.803508771930652	percent	cpu	2026-02-24 04:40:40.811+00
\N	260	cpu_usage_percent	25.47971491231135	percent	cpu	2026-02-24 04:58:54.509+00
\N	260	cpu_usage_percent	25.597368421088177	percent	cpu	2026-02-24 04:59:54.509+00
\N	260	cpu_usage_percent	25.60975877194373	percent	cpu	2026-02-24 05:00:54.509+00
\N	248	cpu_usage_percent	2.4008771929514268	percent	cpu	2026-02-24 07:53:22.128+00
\N	248	cpu_usage_percent	2.3600877192394307	percent	cpu	2026-02-24 07:54:22.128+00
\N	248	cpu_usage_percent	2.394736842129788	percent	cpu	2026-02-24 07:55:22.128+00
\N	248	cpu_usage_percent	2.4021929824365458	percent	cpu	2026-02-24 07:56:22.128+00
\N	248	cpu_usage_percent	2.483333333256553	percent	cpu	2026-02-24 07:57:22.128+00
\N	252	cpu_usage_percent	23.665350877206066	percent	cpu	2026-02-24 05:08:57.197+00
\N	252	cpu_usage_percent	23.84649122805793	percent	cpu	2026-02-24 05:09:57.197+00
\N	252	cpu_usage_percent	23.852192982459414	percent	cpu	2026-02-24 05:10:57.197+00
\N	252	cpu_usage_percent	23.78377192982539	percent	cpu	2026-02-24 05:11:57.197+00
\N	252	cpu_usage_percent	23.93157894737415	percent	cpu	2026-02-24 05:12:57.197+00
\N	252	cpu_usage_percent	23.650438596490417	percent	cpu	2026-02-24 05:13:57.197+00
\N	252	cpu_usage_percent	23.527192982432453	percent	cpu	2026-02-24 05:14:57.197+00
\N	252	cpu_usage_percent	23.759649122877278	percent	cpu	2026-02-24 05:15:57.197+00
\N	252	cpu_usage_percent	23.841666666680567	percent	cpu	2026-02-24 05:16:57.197+00
\N	252	cpu_usage_percent	23.642105263159536	percent	cpu	2026-02-24 05:17:57.197+00
\N	252	cpu_usage_percent	23.878070175414905	percent	cpu	2026-02-24 05:18:57.197+00
\N	252	cpu_usage_percent	25.879824561405968	percent	cpu	2026-02-24 05:19:57.197+00
\N	252	cpu_usage_percent	25.76052631578294	percent	cpu	2026-02-24 05:20:57.197+00
\N	248	cpu_usage_percent	2.5350877192900896	percent	cpu	2026-02-24 07:58:22.128+00
\N	248	cpu_usage_percent	2.5096491227547375	percent	cpu	2026-02-24 07:59:22.128+00
\N	248	cpu_usage_percent	2.6451754385785335	percent	cpu	2026-02-24 08:00:22.128+00
\N	248	cpu_usage_percent	2.7500000000081855	percent	cpu	2026-02-24 08:01:22.128+00
\N	248	cpu_usage_percent	2.96096491227091	percent	cpu	2026-02-24 08:29:33.225+00
\N	260	cpu_usage_percent	25.528728070203215	percent	cpu	2026-02-24 05:59:05.525+00
\N	248	cpu_usage_percent	2.9381578947058102	percent	cpu	2026-02-24 08:30:33.225+00
\N	248	cpu_usage_percent	2.7359649122349623	percent	cpu	2026-02-24 08:31:33.225+00
\N	260	cpu_usage_percent	25.50635964913998	percent	cpu	2026-02-24 06:00:05.525+00
\N	260	cpu_usage_percent	25.59067982454222	percent	cpu	2026-02-24 06:01:05.525+00
\N	260	cpu_usage_percent	25.61787280699305	percent	cpu	2026-02-24 06:02:05.525+00
\N	260	cpu_usage_percent	25.68607456139658	percent	cpu	2026-02-24 06:03:05.525+00
\N	260	cpu_usage_percent	25.64035087718686	percent	cpu	2026-02-24 06:04:05.525+00
\N	260	cpu_usage_percent	25.696600877175428	percent	cpu	2026-02-24 06:05:05.525+00
\N	260	cpu_usage_percent	25.541666666691185	percent	cpu	2026-02-24 06:06:05.525+00
\N	236	cpu_usage_percent	1.4771929824430714	percent	cpu	2026-02-24 05:39:01.416+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	cpu	2026-02-24 05:40:01.416+00
\N	260	cpu_usage_percent	25.61611842106734	percent	cpu	2026-02-24 04:28:41.044+00
\N	260	cpu_usage_percent	25.566118421051414	percent	cpu	2026-02-24 04:29:41.044+00
\N	260	cpu_usage_percent	25.623574561394534	percent	cpu	2026-02-24 04:30:41.044+00
\N	260	cpu_usage_percent	25.553399122814383	percent	cpu	2026-02-24 04:31:41.044+00
\N	260	cpu_usage_percent	25.646710526330907	percent	cpu	2026-02-24 04:32:41.044+00
\N	260	cpu_usage_percent	25.561732456155468	percent	cpu	2026-02-24 04:33:41.044+00
\N	260	cpu_usage_percent	25.569188596492864	percent	cpu	2026-02-24 04:34:41.044+00
\N	260	cpu_usage_percent	25.58848684210446	percent	cpu	2026-02-24 04:35:41.044+00
\N	260	cpu_usage_percent	25.544407894720507	percent	cpu	2026-02-24 04:36:41.044+00
\N	260	cpu_usage_percent	25.52214912279804	percent	cpu	2026-02-24 04:37:41.044+00
\N	260	cpu_usage_percent	25.550328947362715	percent	cpu	2026-02-24 04:38:41.044+00
\N	260	cpu_usage_percent	25.493201754350025	percent	cpu	2026-02-24 04:39:41.044+00
\N	260	cpu_usage_percent	25.578399122786593	percent	cpu	2026-02-24 04:40:41.044+00
\N	236	cpu_usage_percent	1.487719298324052	percent	cpu	2026-02-24 05:41:01.416+00
\N	236	cpu_usage_percent	1.470175438576888	percent	cpu	2026-02-24 05:42:01.416+00
\N	236	cpu_usage_percent	1.7333333333137375	percent	cpu	2026-02-24 05:43:01.416+00
\N	236	cpu_usage_percent	1.7754385965108526	percent	cpu	2026-02-24 05:44:01.416+00
\N	236	cpu_usage_percent	1.750877192897505	percent	cpu	2026-02-24 05:45:01.416+00
\N	236	cpu_usage_percent	1.782456140377036	percent	cpu	2026-02-24 05:46:01.416+00
\N	236	cpu_usage_percent	1.7859649122284367	percent	cpu	2026-02-24 05:47:01.416+00
\N	236	cpu_usage_percent	1.3438596491489534	percent	cpu	2026-02-24 05:48:01.416+00
\N	236	cpu_usage_percent	1.4315789472311877	percent	cpu	2026-02-24 05:49:01.416+00
\N	236	cpu_usage_percent	1.4350877194093528	percent	cpu	2026-02-24 05:50:01.416+00
\N	236	cpu_usage_percent	1.4491228069783375	percent	cpu	2026-02-24 05:51:01.416+00
\N	260	cpu_usage_percent	25.545394736854774	percent	cpu	2026-02-24 06:07:05.525+00
\N	260	cpu_usage_percent	25.54177631580133	percent	cpu	2026-02-24 06:08:05.525+00
\N	260	cpu_usage_percent	25.545504385995557	percent	cpu	2026-02-24 06:09:05.525+00
\N	260	cpu_usage_percent	25.572149122824186	percent	cpu	2026-02-24 06:10:05.525+00
\N	260	cpu_usage_percent	25.54736842104161	percent	cpu	2026-02-24 06:11:05.525+00
\N	236	cpu_usage_percent	1.7473684210461045	percent	cpu	2026-02-24 07:55:21.892+00
\N	236	cpu_usage_percent	1.782456140377036	percent	cpu	2026-02-24 07:56:21.892+00
\N	236	cpu_usage_percent	1.7614035087784856	percent	cpu	2026-02-24 07:57:21.892+00
\N	236	cpu_usage_percent	1.754385964912288	percent	cpu	2026-02-24 07:58:21.892+00
\N	257	cpu_usage_percent	4.272807017581442	percent	cpu	2026-02-24 05:08:57.455+00
\N	257	cpu_usage_percent	4.624561403547176	percent	cpu	2026-02-24 05:09:57.455+00
\N	257	cpu_usage_percent	4.95789473682332	percent	cpu	2026-02-24 05:10:57.455+00
\N	257	cpu_usage_percent	5.2614035087703	percent	cpu	2026-02-24 05:11:57.455+00
\N	257	cpu_usage_percent	5.62719298244798	percent	cpu	2026-02-24 05:12:57.455+00
\N	257	cpu_usage_percent	5.198245614035912	percent	cpu	2026-02-24 05:13:57.455+00
\N	257	cpu_usage_percent	4.810526315796835	percent	cpu	2026-02-24 05:14:57.455+00
\N	257	cpu_usage_percent	4.484210526305176	percent	cpu	2026-02-24 05:15:57.455+00
\N	257	cpu_usage_percent	4.369298245578108	percent	cpu	2026-02-24 05:16:57.455+00
\N	257	cpu_usage_percent	3.9903508771921707	percent	cpu	2026-02-24 05:17:57.455+00
\N	257	cpu_usage_percent	4.25175438594205	percent	cpu	2026-02-24 05:18:57.455+00
\N	257	cpu_usage_percent	4.668421052629142	percent	cpu	2026-02-24 05:19:57.455+00
\N	257	cpu_usage_percent	5.003508771933099	percent	cpu	2026-02-24 05:20:57.455+00
\N	236	cpu_usage_percent	1.5263157893429735	percent	cpu	2026-02-24 07:59:21.892+00
\N	236	cpu_usage_percent	1.470175438576888	percent	cpu	2026-02-24 08:00:21.892+00
\N	236	cpu_usage_percent	1.4807017544578684	percent	cpu	2026-02-24 08:01:21.892+00
\N	252	cpu_usage_percent	25.359210526313348	percent	cpu	2026-02-24 07:09:16.243+00
\N	252	cpu_usage_percent	25.353508771952704	percent	cpu	2026-02-24 07:10:16.243+00
\N	257	cpu_usage_percent	4.299122807018378	percent	cpu	2026-02-24 06:29:09.989+00
\N	257	cpu_usage_percent	4.417543859637689	percent	cpu	2026-02-24 06:30:09.989+00
\N	257	cpu_usage_percent	5.092105263141562	percent	cpu	2026-02-24 06:31:09.989+00
\N	257	cpu_usage_percent	5.324561403545545	percent	cpu	2026-02-24 06:32:09.989+00
\N	257	cpu_usage_percent	5.3464912280661	percent	cpu	2026-02-24 06:33:09.989+00
\N	257	cpu_usage_percent	5.432456140365588	percent	cpu	2026-02-24 06:34:09.989+00
\N	257	cpu_usage_percent	5.056140350868219	percent	cpu	2026-02-24 06:35:09.989+00
\N	257	cpu_usage_percent	4.682456140361509	percent	cpu	2026-02-24 06:36:09.989+00
\N	257	cpu_usage_percent	4.568421052638129	percent	cpu	2026-02-24 06:37:09.989+00
\N	257	cpu_usage_percent	4.309649122838067	percent	cpu	2026-02-24 06:38:09.989+00
\N	257	cpu_usage_percent	4.441228070186071	percent	cpu	2026-02-24 06:39:09.989+00
\N	257	cpu_usage_percent	4.828947368425148	percent	cpu	2026-02-24 06:40:09.989+00
\N	257	cpu_usage_percent	5.1438596491342565	percent	cpu	2026-02-24 06:41:09.989+00
\N	252	cpu_usage_percent	24.900438596490417	percent	cpu	2026-02-24 07:11:16.243+00
\N	252	cpu_usage_percent	24.709210526320703	percent	cpu	2026-02-24 07:12:16.243+00
\N	252	cpu_usage_percent	24.669736842114247	percent	cpu	2026-02-24 07:13:16.243+00
\N	252	cpu_usage_percent	24.749561403530834	percent	cpu	2026-02-24 07:14:16.243+00
\N	252	cpu_usage_percent	24.831140350852692	percent	cpu	2026-02-24 07:15:16.243+00
\N	252	cpu_usage_percent	24.77500000000491	percent	cpu	2026-02-24 07:16:16.243+00
\N	252	cpu_usage_percent	24.63728070173316	percent	cpu	2026-02-24 07:17:16.243+00
\N	252	cpu_usage_percent	24.601754385982076	percent	cpu	2026-02-24 07:18:16.243+00
\N	248	cpu_usage_percent	2.949561403549623	percent	cpu	2026-02-24 05:39:01.656+00
\N	248	cpu_usage_percent	2.347368420992197	percent	cpu	2026-02-24 05:40:01.656+00
\N	248	cpu_usage_percent	2.3171052632020235	percent	cpu	2026-02-24 05:41:01.656+00
\N	248	cpu_usage_percent	2.314035087750355	percent	cpu	2026-02-24 05:42:01.656+00
\N	248	cpu_usage_percent	2.343421052618524	percent	cpu	2026-02-24 05:43:01.656+00
\N	248	cpu_usage_percent	2.444736842033379	percent	cpu	2026-02-24 05:44:01.656+00
\N	248	cpu_usage_percent	2.5065789473847815	percent	cpu	2026-02-24 05:45:01.656+00
\N	248	cpu_usage_percent	2.5583333332140654	percent	cpu	2026-02-24 05:46:01.656+00
\N	248	cpu_usage_percent	2.556140350929482	percent	cpu	2026-02-24 05:47:01.656+00
\N	260	cpu_usage_percent	25.56217105265732	percent	cpu	2026-02-24 05:08:57.689+00
\N	260	cpu_usage_percent	25.56008771930928	percent	cpu	2026-02-24 05:09:57.689+00
\N	248	cpu_usage_percent	2.583333333308829	percent	cpu	2026-02-24 05:48:01.656+00
\N	252	cpu_usage_percent	24.294736842081576	percent	cpu	2026-02-24 07:19:16.243+00
\N	260	cpu_usage_percent	25.587609649131394	percent	cpu	2026-02-24 05:10:57.689+00
\N	260	cpu_usage_percent	25.562390350857186	percent	cpu	2026-02-24 05:11:57.689+00
\N	260	cpu_usage_percent	25.571820175463117	percent	cpu	2026-02-24 05:12:57.689+00
\N	260	cpu_usage_percent	25.59813596488982	percent	cpu	2026-02-24 05:13:57.689+00
\N	260	cpu_usage_percent	25.557785087740953	percent	cpu	2026-02-24 05:14:57.689+00
\N	260	cpu_usage_percent	25.577850877266513	percent	cpu	2026-02-24 05:15:57.689+00
\N	260	cpu_usage_percent	25.59342105263282	percent	cpu	2026-02-24 05:16:57.689+00
\N	260	cpu_usage_percent	25.574451754402716	percent	cpu	2026-02-24 05:17:57.689+00
\N	260	cpu_usage_percent	25.538267543837605	percent	cpu	2026-02-24 05:18:57.689+00
\N	260	cpu_usage_percent	25.501864035072614	percent	cpu	2026-02-24 05:19:57.689+00
\N	260	cpu_usage_percent	25.577083333301474	percent	cpu	2026-02-24 05:20:57.689+00
\N	248	cpu_usage_percent	2.549561403544729	percent	cpu	2026-02-24 05:49:01.656+00
\N	248	cpu_usage_percent	2.5552631578849514	percent	cpu	2026-02-24 05:50:01.656+00
\N	248	cpu_usage_percent	2.471929824535266	percent	cpu	2026-02-24 05:51:01.656+00
\N	236	cpu_usage_percent	1.7684210524812727	percent	cpu	2026-02-24 08:35:32.846+00
\N	236	cpu_usage_percent	1.8561403508902856	percent	cpu	2026-02-24 08:36:32.846+00
\N	236	cpu_usage_percent	2.00000000006537	percent	cpu	2026-02-24 08:37:32.846+00
\N	236	cpu_usage_percent	2.0140350876343405	percent	cpu	2026-02-24 08:38:32.846+00
\N	133	cpu_usage_percent	0.3043859648894198	percent	cpu	2026-02-24 06:09:05.786+00
\N	133	cpu_usage_percent	0.4166666666666714	percent	cpu	2026-02-24 06:10:05.786+00
\N	133	cpu_usage_percent	0.42894736839164693	percent	cpu	2026-02-24 06:11:05.786+00
\N	133	cpu_usage_percent	0.41008771928191834	percent	cpu	2026-02-24 06:12:05.786+00
\N	133	cpu_usage_percent	0.5179824561632387	percent	cpu	2026-02-24 06:13:05.786+00
\N	133	cpu_usage_percent	0.4719298245516086	percent	cpu	2026-02-24 06:14:05.786+00
\N	133	cpu_usage_percent	0.5622807018083193	percent	cpu	2026-02-24 06:15:05.786+00
\N	133	cpu_usage_percent	0.5754385964961415	percent	cpu	2026-02-24 06:16:05.786+00
\N	133	cpu_usage_percent	0.583771929806602	percent	cpu	2026-02-24 06:17:05.786+00
\N	133	cpu_usage_percent	0.4157894736629828	percent	cpu	2026-02-24 06:18:05.786+00
\N	133	cpu_usage_percent	0.42149122804404726	percent	cpu	2026-02-24 06:19:05.786+00
\N	133	cpu_usage_percent	0.4236842104920129	percent	cpu	2026-02-24 06:20:05.786+00
\N	133	cpu_usage_percent	0.42105263160347306	percent	cpu	2026-02-24 06:21:05.786+00
\N	236	cpu_usage_percent	1.9508771930020714	percent	cpu	2026-02-24 08:39:32.846+00
\N	236	cpu_usage_percent	1.757894736927085	percent	cpu	2026-02-24 08:40:32.846+00
\N	236	cpu_usage_percent	1.3789473683165028	percent	cpu	2026-02-24 08:41:32.846+00
\N	252	cpu_usage_percent	24.25307017542717	percent	cpu	2026-02-24 07:49:22.366+00
\N	252	cpu_usage_percent	24.317982456148528	percent	cpu	2026-02-24 07:50:22.366+00
\N	252	cpu_usage_percent	24.461842105241928	percent	cpu	2026-02-24 07:51:22.366+00
\N	252	cpu_usage_percent	24.433771929797615	percent	cpu	2026-02-24 07:52:22.366+00
\N	252	cpu_usage_percent	24.365789473706272	percent	cpu	2026-02-24 07:53:22.366+00
\N	252	cpu_usage_percent	24.27456140354799	percent	cpu	2026-02-24 07:54:22.366+00
\N	133	cpu_usage_percent	0.9741228069750747	percent	cpu	2026-02-24 05:18:57.931+00
\N	133	cpu_usage_percent	1.2298245613642962	percent	cpu	2026-02-24 05:19:57.931+00
\N	133	cpu_usage_percent	1.2228070174981127	percent	cpu	2026-02-24 05:20:57.931+00
\N	133	cpu_usage_percent	1.215350877150513	percent	cpu	2026-02-24 05:21:57.931+00
\N	133	cpu_usage_percent	1.3859649123460684	percent	cpu	2026-02-24 05:22:57.931+00
\N	133	cpu_usage_percent	0.5921052631987465	percent	cpu	2026-02-24 05:23:57.931+00
\N	133	cpu_usage_percent	0.5833333332843296	percent	cpu	2026-02-24 05:24:57.931+00
\N	133	cpu_usage_percent	0.5798245613512449	percent	cpu	2026-02-24 05:25:57.931+00
\N	133	cpu_usage_percent	0.47719298241040065	percent	cpu	2026-02-24 05:26:57.931+00
\N	133	cpu_usage_percent	0.4359649122986866	percent	cpu	2026-02-24 05:27:57.931+00
\N	133	cpu_usage_percent	0.4249999999771319	percent	cpu	2026-02-24 05:28:57.931+00
\N	133	cpu_usage_percent	0.4372807017838056	percent	cpu	2026-02-24 05:29:57.931+00
\N	133	cpu_usage_percent	0.42236842100689387	percent	cpu	2026-02-24 05:30:57.931+00
\N	252	cpu_usage_percent	24.51140350876622	percent	cpu	2026-02-24 07:55:22.366+00
\N	252	cpu_usage_percent	24.612280701760938	percent	cpu	2026-02-24 07:56:22.366+00
\N	252	cpu_usage_percent	24.62850877192085	percent	cpu	2026-02-24 07:57:22.366+00
\N	252	cpu_usage_percent	23.822368421089408	percent	cpu	2026-02-24 05:39:01.898+00
\N	252	cpu_usage_percent	23.598245614016307	percent	cpu	2026-02-24 05:40:01.898+00
\N	252	cpu_usage_percent	23.76491228071565	percent	cpu	2026-02-24 05:41:01.898+00
\N	252	cpu_usage_percent	23.68596491226191	percent	cpu	2026-02-24 05:42:01.898+00
\N	252	cpu_usage_percent	23.813596491256675	percent	cpu	2026-02-24 05:43:01.898+00
\N	252	cpu_usage_percent	23.812719298252972	percent	cpu	2026-02-24 05:44:01.898+00
\N	252	cpu_usage_percent	23.785526315812362	percent	cpu	2026-02-24 05:45:01.898+00
\N	252	cpu_usage_percent	23.670614035064858	percent	cpu	2026-02-24 05:46:01.898+00
\N	252	cpu_usage_percent	23.710087719332563	percent	cpu	2026-02-24 05:47:01.898+00
\N	252	cpu_usage_percent	23.469298245618134	percent	cpu	2026-02-24 05:48:01.898+00
\N	252	cpu_usage_percent	23.845614035135938	percent	cpu	2026-02-24 05:49:01.898+00
\N	252	cpu_usage_percent	23.970175438638165	percent	cpu	2026-02-24 05:50:01.898+00
\N	252	cpu_usage_percent	23.79649122811348	percent	cpu	2026-02-24 05:51:01.898+00
\N	252	cpu_usage_percent	24.74342105260709	percent	cpu	2026-02-24 07:58:22.366+00
\N	252	cpu_usage_percent	24.604824561392903	percent	cpu	2026-02-24 07:59:22.366+00
\N	252	cpu_usage_percent	24.82368421050508	percent	cpu	2026-02-24 08:00:22.366+00
\N	252	cpu_usage_percent	24.121052631556893	percent	cpu	2026-02-24 08:01:22.366+00
\N	260	cpu_usage_percent	25.52225877194904	percent	cpu	2026-02-24 06:29:10.241+00
\N	260	cpu_usage_percent	25.451315789454895	percent	cpu	2026-02-24 06:30:10.241+00
\N	260	cpu_usage_percent	25.505482456146495	percent	cpu	2026-02-24 06:31:10.241+00
\N	260	cpu_usage_percent	25.578289473656042	percent	cpu	2026-02-24 06:32:10.241+00
\N	260	cpu_usage_percent	25.57346491226845	percent	cpu	2026-02-24 06:33:10.241+00
\N	260	cpu_usage_percent	25.641337719331332	percent	cpu	2026-02-24 06:34:10.241+00
\N	260	cpu_usage_percent	25.59649122808449	percent	cpu	2026-02-24 06:35:10.241+00
\N	260	cpu_usage_percent	25.573574561358186	percent	cpu	2026-02-24 06:36:10.241+00
\N	260	cpu_usage_percent	25.5185307017548	percent	cpu	2026-02-24 06:37:10.241+00
\N	260	cpu_usage_percent	25.509539473660936	percent	cpu	2026-02-24 06:38:10.241+00
\N	260	cpu_usage_percent	25.517653508761313	percent	cpu	2026-02-24 06:39:10.241+00
\N	260	cpu_usage_percent	25.555701754423552	percent	cpu	2026-02-24 06:40:10.241+00
\N	236	cpu_usage_percent	1.2694825928995073	percent	cpu	2026-02-24 06:09:06.057+00
\N	236	cpu_usage_percent	1.3999999999150532	percent	cpu	2026-02-24 06:10:06.057+00
\N	236	cpu_usage_percent	1.4210526315136036	percent	cpu	2026-02-24 06:11:06.057+00
\N	236	cpu_usage_percent	1.43157894739457	percent	cpu	2026-02-24 06:12:06.057+00
\N	236	cpu_usage_percent	1.4210526315136036	percent	cpu	2026-02-24 06:13:06.057+00
\N	236	cpu_usage_percent	1.536842105223954	percent	cpu	2026-02-24 05:18:58.192+00
\N	236	cpu_usage_percent	1.5157894737887858	percent	cpu	2026-02-24 05:19:58.192+00
\N	236	cpu_usage_percent	1.5052631579078195	percent	cpu	2026-02-24 05:20:58.192+00
\N	236	cpu_usage_percent	1.5017543858930225	percent	cpu	2026-02-24 05:21:58.192+00
\N	236	cpu_usage_percent	1.8807017545036047	percent	cpu	2026-02-24 05:22:58.192+00
\N	236	cpu_usage_percent	1.901754385938787	percent	cpu	2026-02-24 05:23:58.192+00
\N	236	cpu_usage_percent	1.9052631577901877	percent	cpu	2026-02-24 05:24:58.192+00
\N	236	cpu_usage_percent	1.9263157895521203	percent	cpu	2026-02-24 05:25:58.192+00
\N	236	cpu_usage_percent	1.71578947372997	percent	cpu	2026-02-24 05:26:58.192+00
\N	236	cpu_usage_percent	1.480701754294472	percent	cpu	2026-02-24 05:27:58.192+00
\N	236	cpu_usage_percent	1.470175438576888	percent	cpu	2026-02-24 05:28:58.192+00
\N	236	cpu_usage_percent	1.4631578947107045	percent	cpu	2026-02-24 05:29:58.192+00
\N	236	cpu_usage_percent	1.4561403510079174	percent	cpu	2026-02-24 05:30:58.192+00
\N	236	cpu_usage_percent	1.5473684211049203	percent	cpu	2026-02-24 06:14:06.057+00
\N	236	cpu_usage_percent	1.7157894735665735	percent	cpu	2026-02-24 06:15:06.057+00
\N	236	cpu_usage_percent	1.7333333333137375	percent	cpu	2026-02-24 06:16:06.057+00
\N	236	cpu_usage_percent	1.712280701715187	percent	cpu	2026-02-24 06:17:06.057+00
\N	236	cpu_usage_percent	1.470175438576888	percent	cpu	2026-02-24 06:18:06.057+00
\N	236	cpu_usage_percent	1.522807017491587	percent	cpu	2026-02-24 06:19:06.057+00
\N	236	cpu_usage_percent	1.5438596490901375	percent	cpu	2026-02-24 06:20:06.057+00
\N	236	cpu_usage_percent	1.5719298245548714	percent	cpu	2026-02-24 06:21:06.057+00
\N	260	cpu_usage_percent	25.605921052649563	percent	cpu	2026-02-24 06:41:10.241+00
\N	252	cpu_usage_percent	24.223684210518158	percent	cpu	2026-02-24 07:20:16.243+00
\N	252	cpu_usage_percent	24.26754385970223	percent	cpu	2026-02-24 07:21:16.243+00
\N	257	cpu_usage_percent	4.412280701738055	percent	cpu	2026-02-24 05:39:02.126+00
\N	257	cpu_usage_percent	4.796491228064468	percent	cpu	2026-02-24 05:40:02.126+00
\N	257	cpu_usage_percent	5.134210526318256	percent	cpu	2026-02-24 05:41:02.126+00
\N	257	cpu_usage_percent	5.274561403519414	percent	cpu	2026-02-24 05:42:02.126+00
\N	257	cpu_usage_percent	5.545614035064844	percent	cpu	2026-02-24 05:43:02.126+00
\N	257	cpu_usage_percent	5.229824561413324	percent	cpu	2026-02-24 05:44:02.126+00
\N	257	cpu_usage_percent	4.855263157902911	percent	cpu	2026-02-24 05:45:02.126+00
\N	257	cpu_usage_percent	4.487719298238275	percent	cpu	2026-02-24 05:46:02.126+00
\N	257	cpu_usage_percent	4.404385964909025	percent	cpu	2026-02-24 05:47:02.126+00
\N	257	cpu_usage_percent	3.7631578947286926	percent	cpu	2026-02-24 05:48:02.126+00
\N	257	cpu_usage_percent	4.390350877156223	percent	cpu	2026-02-24 05:49:02.126+00
\N	257	cpu_usage_percent	4.7456140350754765	percent	cpu	2026-02-24 05:50:02.126+00
\N	257	cpu_usage_percent	5.101754385977998	percent	cpu	2026-02-24 05:51:02.126+00
\N	236	cpu_usage_percent	1.7368421053285346	percent	cpu	2026-02-24 09:49:56.642+00
\N	236	cpu_usage_percent	1.7368421053285346	percent	cpu	2026-02-24 09:50:56.642+00
\N	236	cpu_usage_percent	1.719298245744767	percent	cpu	2026-02-24 09:51:56.642+00
\N	236	cpu_usage_percent	1.6028182653325018	percent	cpu	2026-02-24 09:52:56.642+00
\N	236	cpu_usage_percent	1.607017543885803	percent	cpu	2026-02-24 09:53:56.642+00
\N	236	cpu_usage_percent	1.7228070175961534	percent	cpu	2026-02-24 09:54:56.642+00
\N	236	cpu_usage_percent	1.8631578945930727	percent	cpu	2026-02-24 09:55:56.642+00
\N	236	cpu_usage_percent	1.8771929824888218	percent	cpu	2026-02-24 09:56:56.642+00
\N	236	cpu_usage_percent	1.9789473684668053	percent	cpu	2026-02-24 09:57:56.642+00
\N	248	cpu_usage_percent	2.263157894720507	percent	cpu	2026-02-24 05:18:58.459+00
\N	248	cpu_usage_percent	2.5701754384984667	percent	cpu	2026-02-24 05:19:58.459+00
\N	248	cpu_usage_percent	2.617543859636058	percent	cpu	2026-02-24 05:20:58.459+00
\N	248	cpu_usage_percent	2.701315789385461	percent	cpu	2026-02-24 05:21:58.459+00
\N	248	cpu_usage_percent	2.8206140350697524	percent	cpu	2026-02-24 05:22:58.459+00
\N	248	cpu_usage_percent	2.828947368421069	percent	cpu	2026-02-24 05:23:58.459+00
\N	248	cpu_usage_percent	2.4798245614459944	percent	cpu	2026-02-24 05:24:58.459+00
\N	248	cpu_usage_percent	2.4561403508363497	percent	cpu	2026-02-24 05:25:58.459+00
\N	248	cpu_usage_percent	2.401315789514541	percent	cpu	2026-02-24 05:26:58.459+00
\N	248	cpu_usage_percent	2.310526315776414	percent	cpu	2026-02-24 05:27:58.459+00
\N	248	cpu_usage_percent	2.3250000000718956	percent	cpu	2026-02-24 05:28:58.459+00
\N	248	cpu_usage_percent	2.38684210521906	percent	cpu	2026-02-24 05:29:58.459+00
\N	248	cpu_usage_percent	2.4925438596524145	percent	cpu	2026-02-24 05:30:58.459+00
\N	236	cpu_usage_percent	1.9087719298049706	percent	cpu	2026-02-24 09:58:56.642+00
\N	236	cpu_usage_percent	2.5729553724257386	percent	cpu	2026-02-24 09:59:56.642+00
\N	236	cpu_usage_percent	2.385964912378739	percent	cpu	2026-02-24 10:00:56.642+00
\N	236	cpu_usage_percent	2.3112523990957925	percent	cpu	2026-02-24 10:01:56.642+00
\N	248	cpu_usage_percent	2.3521929824104006	percent	cpu	2026-02-24 06:09:06.32+00
\N	248	cpu_usage_percent	2.421929824590819	percent	cpu	2026-02-24 06:10:06.32+00
\N	248	cpu_usage_percent	2.4109649123101207	percent	cpu	2026-02-24 06:11:06.32+00
\N	248	cpu_usage_percent	2.333333333341514	percent	cpu	2026-02-24 06:12:06.32+00
\N	248	cpu_usage_percent	2.383333333285961	percent	cpu	2026-02-24 06:13:06.32+00
\N	248	cpu_usage_percent	2.328070175401024	percent	cpu	2026-02-24 06:14:06.32+00
\N	248	cpu_usage_percent	2.2583333333431455	percent	cpu	2026-02-24 06:15:06.32+00
\N	260	cpu_usage_percent	25.523684210554507	percent	cpu	2026-02-24 05:39:02.358+00
\N	248	cpu_usage_percent	2.3491228069995884	percent	cpu	2026-02-24 06:16:06.32+00
\N	260	cpu_usage_percent	25.528070175450452	percent	cpu	2026-02-24 05:40:02.358+00
\N	260	cpu_usage_percent	25.561951754406394	percent	cpu	2026-02-24 05:41:02.358+00
\N	260	cpu_usage_percent	25.637061403494485	percent	cpu	2026-02-24 05:42:02.358+00
\N	260	cpu_usage_percent	25.63958333332394	percent	cpu	2026-02-24 05:43:02.358+00
\N	260	cpu_usage_percent	25.684320175419813	percent	cpu	2026-02-24 05:44:02.358+00
\N	260	cpu_usage_percent	25.64265350877561	percent	cpu	2026-02-24 05:45:02.358+00
\N	260	cpu_usage_percent	25.565131578958002	percent	cpu	2026-02-24 05:46:02.358+00
\N	260	cpu_usage_percent	25.601535087733197	percent	cpu	2026-02-24 05:47:02.358+00
\N	252	cpu_usage_percent	23.878070175414905	percent	cpu	2026-02-24 05:18:58.739+00
\N	252	cpu_usage_percent	25.879824561405968	percent	cpu	2026-02-24 05:19:58.739+00
\N	252	cpu_usage_percent	25.76052631578294	percent	cpu	2026-02-24 05:20:58.739+00
\N	252	cpu_usage_percent	25.702192982425913	percent	cpu	2026-02-24 05:21:58.739+00
\N	252	cpu_usage_percent	26.033771929858062	percent	cpu	2026-02-24 05:22:58.739+00
\N	252	cpu_usage_percent	25.151754385983708	percent	cpu	2026-02-24 05:23:58.739+00
\N	252	cpu_usage_percent	23.96359649123299	percent	cpu	2026-02-24 05:24:58.739+00
\N	252	cpu_usage_percent	23.91622807015665	percent	cpu	2026-02-24 05:25:58.739+00
\N	252	cpu_usage_percent	24.09254385963115	percent	cpu	2026-02-24 05:26:58.739+00
\N	252	cpu_usage_percent	23.930701754472565	percent	cpu	2026-02-24 05:27:58.739+00
\N	252	cpu_usage_percent	24.08640350876867	percent	cpu	2026-02-24 05:28:58.739+00
\N	252	cpu_usage_percent	23.863596491221543	percent	cpu	2026-02-24 05:29:58.739+00
\N	252	cpu_usage_percent	24.103070175471288	percent	cpu	2026-02-24 05:30:58.739+00
\N	260	cpu_usage_percent	25.545504385964918	percent	cpu	2026-02-24 05:48:02.358+00
\N	260	cpu_usage_percent	25.462938596488385	percent	cpu	2026-02-24 05:49:02.358+00
\N	260	cpu_usage_percent	25.489473684227278	percent	cpu	2026-02-24 05:50:02.358+00
\N	260	cpu_usage_percent	25.461513157923747	percent	cpu	2026-02-24 05:51:02.358+00
\N	248	cpu_usage_percent	2.3447368420219448	percent	cpu	2026-02-24 06:17:06.32+00
\N	248	cpu_usage_percent	2.3416666666928165	percent	cpu	2026-02-24 06:18:06.32+00
\N	248	cpu_usage_percent	2.388157894826719	percent	cpu	2026-02-24 06:19:06.32+00
\N	248	cpu_usage_percent	2.633333333294132	percent	cpu	2026-02-24 06:20:06.32+00
\N	248	cpu_usage_percent	2.6206140350468843	percent	cpu	2026-02-24 06:21:06.32+00
\N	236	cpu_usage_percent	1.5578947369859009	percent	cpu	2026-02-24 09:14:42.762+00
\N	236	cpu_usage_percent	1.7122807018785835	percent	cpu	2026-02-24 09:15:42.762+00
\N	236	cpu_usage_percent	1.8701754386226526	percent	cpu	2026-02-24 09:16:42.762+00
\N	236	cpu_usage_percent	1.8982456140873865	percent	cpu	2026-02-24 09:17:42.762+00
\N	236	cpu_usage_percent	1.7448939134692978	percent	cpu	2026-02-24 09:18:42.762+00
\N	236	cpu_usage_percent	1.8666666666078555	percent	cpu	2026-02-24 09:19:42.762+00
\N	257	cpu_usage_percent	4.607017543861289	percent	cpu	2026-02-24 07:09:16.484+00
\N	257	cpu_usage_percent	4.939473684235864	percent	cpu	2026-02-24 07:10:16.484+00
\N	257	cpu_usage_percent	5.2912280701607415	percent	cpu	2026-02-24 07:11:16.484+00
\N	257	cpu_usage_percent	5.130701754385157	percent	cpu	2026-02-24 07:12:16.484+00
\N	257	cpu_usage_percent	5.2359649122758185	percent	cpu	2026-02-24 07:13:16.484+00
\N	257	cpu_usage_percent	5.1631578947254155	percent	cpu	2026-02-24 07:14:16.484+00
\N	257	cpu_usage_percent	5.042105263156273	percent	cpu	2026-02-24 07:15:16.484+00
\N	257	cpu_usage_percent	4.654385964917196	percent	cpu	2026-02-24 07:16:16.484+00
\N	257	cpu_usage_percent	4.492982456117488	percent	cpu	2026-02-24 07:17:16.484+00
\N	257	cpu_usage_percent	4.557017543814723	percent	cpu	2026-02-24 07:18:16.484+00
\N	257	cpu_usage_percent	4.482456140338627	percent	cpu	2026-02-24 07:19:16.484+00
\N	257	cpu_usage_percent	4.923684210516527	percent	cpu	2026-02-24 07:20:16.484+00
\N	257	cpu_usage_percent	5.331578947391307	percent	cpu	2026-02-24 07:21:16.484+00
\N	236	cpu_usage_percent	1.7073324771652523	percent	cpu	2026-02-24 09:20:42.762+00
\N	236	cpu_usage_percent	1.5533496844414714	percent	cpu	2026-02-24 09:21:42.762+00
\N	257	cpu_usage_percent	4.25175438594205	percent	cpu	2026-02-24 05:18:58.992+00
\N	257	cpu_usage_percent	4.668421052629142	percent	cpu	2026-02-24 05:19:58.992+00
\N	257	cpu_usage_percent	5.003508771933099	percent	cpu	2026-02-24 05:20:58.992+00
\N	257	cpu_usage_percent	5.035964912293778	percent	cpu	2026-02-24 05:21:58.992+00
\N	257	cpu_usage_percent	5.734210526325597	percent	cpu	2026-02-24 05:22:58.992+00
\N	257	cpu_usage_percent	5.302631578902449	percent	cpu	2026-02-24 05:23:58.992+00
\N	257	cpu_usage_percent	4.911403508750695	percent	cpu	2026-02-24 05:24:58.992+00
\N	257	cpu_usage_percent	4.564035087701342	percent	cpu	2026-02-24 05:25:58.992+00
\N	257	cpu_usage_percent	4.137719298259512	percent	cpu	2026-02-24 05:26:58.992+00
\N	257	cpu_usage_percent	3.98421052632969	percent	cpu	2026-02-24 05:27:58.992+00
\N	257	cpu_usage_percent	4.285087719306418	percent	cpu	2026-02-24 05:28:58.992+00
\N	257	cpu_usage_percent	4.671929824562241	percent	cpu	2026-02-24 05:29:58.992+00
\N	257	cpu_usage_percent	5.0622807017307	percent	cpu	2026-02-24 05:30:58.992+00
\N	133	cpu_usage_percent	0.4258771930216909	percent	cpu	2026-02-24 05:49:02.61+00
\N	133	cpu_usage_percent	0.5649122807377012	percent	cpu	2026-02-24 05:50:02.61+00
\N	133	cpu_usage_percent	0.5793859649515127	percent	cpu	2026-02-24 05:51:02.61+00
\N	133	cpu_usage_percent	0.5881578947842314	percent	cpu	2026-02-24 05:52:02.61+00
\N	133	cpu_usage_percent	0.6201754386226526	percent	cpu	2026-02-24 05:53:02.61+00
\N	133	cpu_usage_percent	0.7320175438776317	percent	cpu	2026-02-24 05:54:02.61+00
\N	133	cpu_usage_percent	0.5885964911431074	percent	cpu	2026-02-24 05:55:02.61+00
\N	133	cpu_usage_percent	0.5780701754255375	percent	cpu	2026-02-24 05:56:02.61+00
\N	133	cpu_usage_percent	0.5789473683883841	percent	cpu	2026-02-24 05:57:02.61+00
\N	133	cpu_usage_percent	0.4241228070551273	percent	cpu	2026-02-24 05:58:02.61+00
\N	133	cpu_usage_percent	0.4166666666258294	percent	cpu	2026-02-24 05:59:02.61+00
\N	133	cpu_usage_percent	0.41140350872619535	percent	cpu	2026-02-24 06:00:02.61+00
\N	133	cpu_usage_percent	0.4245614035365577	percent	cpu	2026-02-24 06:01:02.61+00
\N	252	cpu_usage_percent	23.526754385951037	percent	cpu	2026-02-24 06:09:06.588+00
\N	252	cpu_usage_percent	23.95657894732595	percent	cpu	2026-02-24 06:10:06.588+00
\N	252	cpu_usage_percent	23.925000000009817	percent	cpu	2026-02-24 06:11:06.588+00
\N	252	cpu_usage_percent	23.671929824549977	percent	cpu	2026-02-24 06:12:06.588+00
\N	252	cpu_usage_percent	23.697368421044473	percent	cpu	2026-02-24 06:13:06.588+00
\N	252	cpu_usage_percent	23.40175438596738	percent	cpu	2026-02-24 06:14:06.588+00
\N	252	cpu_usage_percent	23.45921052632069	percent	cpu	2026-02-24 06:15:06.588+00
\N	252	cpu_usage_percent	23.366666666636448	percent	cpu	2026-02-24 06:16:06.588+00
\N	252	cpu_usage_percent	23.289912280691965	percent	cpu	2026-02-24 06:17:06.588+00
\N	252	cpu_usage_percent	23.13947368421381	percent	cpu	2026-02-24 06:18:06.588+00
\N	252	cpu_usage_percent	22.95350877192331	percent	cpu	2026-02-24 06:19:06.588+00
\N	252	cpu_usage_percent	23.039473684222784	percent	cpu	2026-02-24 06:20:06.588+00
\N	252	cpu_usage_percent	23.06315789473031	percent	cpu	2026-02-24 06:21:06.588+00
\N	133	cpu_usage_percent	0.4802631578620691	percent	cpu	2026-02-24 06:39:10.498+00
\N	133	cpu_usage_percent	0.4706140350256476	percent	cpu	2026-02-24 06:40:10.498+00
\N	133	cpu_usage_percent	0.4557017543304198	percent	cpu	2026-02-24 06:41:10.498+00
\N	260	cpu_usage_percent	25.538267543837605	percent	cpu	2026-02-24 05:18:59.249+00
\N	260	cpu_usage_percent	25.501864035072614	percent	cpu	2026-02-24 05:19:59.249+00
\N	260	cpu_usage_percent	25.577083333301474	percent	cpu	2026-02-24 05:20:59.249+00
\N	260	cpu_usage_percent	25.530701754390066	percent	cpu	2026-02-24 05:21:59.249+00
\N	260	cpu_usage_percent	25.5843201754288	percent	cpu	2026-02-24 05:22:59.249+00
\N	260	cpu_usage_percent	25.637390350845337	percent	cpu	2026-02-24 05:23:59.249+00
\N	260	cpu_usage_percent	25.62017543861242	percent	cpu	2026-02-24 05:24:59.249+00
\N	260	cpu_usage_percent	25.607785087695618	percent	cpu	2026-02-24 05:25:59.249+00
\N	260	cpu_usage_percent	25.596052631603058	percent	cpu	2026-02-24 05:26:59.249+00
\N	260	cpu_usage_percent	25.62554824560179	percent	cpu	2026-02-24 05:27:59.249+00
\N	260	cpu_usage_percent	25.588706140314528	percent	cpu	2026-02-24 05:28:59.249+00
\N	260	cpu_usage_percent	25.5705043859882	percent	cpu	2026-02-24 05:29:59.249+00
\N	260	cpu_usage_percent	25.555372807001206	percent	cpu	2026-02-24 05:30:59.249+00
\N	133	cpu_usage_percent	0.4640350877225643	percent	cpu	2026-02-24 06:42:10.498+00
\N	133	cpu_usage_percent	0.45833333338235605	percent	cpu	2026-02-24 06:43:10.498+00
\N	133	cpu_usage_percent	0.6982456140318334	percent	cpu	2026-02-24 06:44:10.498+00
\N	133	cpu_usage_percent	0.6991228070763782	percent	cpu	2026-02-24 06:45:10.498+00
\N	133	cpu_usage_percent	1.1657894736466403	percent	cpu	2026-02-24 06:46:10.498+00
\N	133	cpu_usage_percent	1.2885964912640304	percent	cpu	2026-02-24 06:47:10.498+00
\N	133	cpu_usage_percent	1.2846491228903574	percent	cpu	2026-02-24 06:48:10.498+00
\N	133	cpu_usage_percent	1.043421052714919	percent	cpu	2026-02-24 06:49:10.498+00
\N	133	cpu_usage_percent	1.0342105262373735	percent	cpu	2026-02-24 06:50:10.498+00
\N	133	cpu_usage_percent	0.35263157894901553	percent	cpu	2026-02-24 06:51:10.498+00
\N	248	cpu_usage_percent	2.642105263126865	percent	cpu	2026-02-24 08:32:33.225+00
\N	248	cpu_usage_percent	2.4469298245222006	percent	cpu	2026-02-24 08:33:33.225+00
\N	248	cpu_usage_percent	2.45131578937729	percent	cpu	2026-02-24 08:34:33.225+00
\N	248	cpu_usage_percent	2.356140350865772	percent	cpu	2026-02-24 08:35:33.225+00
\N	260	cpu_usage_percent	25.579276315780092	percent	cpu	2026-02-24 07:09:16.74+00
\N	260	cpu_usage_percent	25.597478070177885	percent	cpu	2026-02-24 07:10:16.74+00
\N	236	cpu_usage_percent	1.4315789472311877	percent	cpu	2026-02-24 05:49:02.922+00
\N	236	cpu_usage_percent	1.4350877194093528	percent	cpu	2026-02-24 05:50:02.922+00
\N	236	cpu_usage_percent	1.4491228069783375	percent	cpu	2026-02-24 05:51:02.922+00
\N	236	cpu_usage_percent	1.4350877194093528	percent	cpu	2026-02-24 05:52:02.922+00
\N	236	cpu_usage_percent	1.568421052703485	percent	cpu	2026-02-24 05:53:02.922+00
\N	236	cpu_usage_percent	1.7473684212095009	percent	cpu	2026-02-24 05:54:02.922+00
\N	236	cpu_usage_percent	1.750877192897505	percent	cpu	2026-02-24 05:55:02.922+00
\N	236	cpu_usage_percent	1.7438596490313216	percent	cpu	2026-02-24 05:56:02.922+00
\N	236	cpu_usage_percent	1.7438596490313216	percent	cpu	2026-02-24 05:57:02.922+00
\N	236	cpu_usage_percent	1.4807017544578684	percent	cpu	2026-02-24 05:58:02.922+00
\N	236	cpu_usage_percent	1.4070175439446189	percent	cpu	2026-02-24 05:59:02.922+00
\N	236	cpu_usage_percent	1.4175438594988208	percent	cpu	2026-02-24 06:00:02.922+00
\N	236	cpu_usage_percent	1.4350877192459706	percent	cpu	2026-02-24 06:01:02.922+00
\N	260	cpu_usage_percent	25.614583333280237	percent	cpu	2026-02-24 07:11:16.74+00
\N	260	cpu_usage_percent	25.59923245613423	percent	cpu	2026-02-24 07:12:16.74+00
\N	260	cpu_usage_percent	25.631578947364346	percent	cpu	2026-02-24 07:13:16.74+00
\N	260	cpu_usage_percent	25.630592105260718	percent	cpu	2026-02-24 07:14:16.74+00
\N	260	cpu_usage_percent	25.63684210523334	percent	cpu	2026-02-24 07:15:16.74+00
\N	260	cpu_usage_percent	25.638157894708257	percent	cpu	2026-02-24 07:16:16.74+00
\N	260	cpu_usage_percent	25.606907894691915	percent	cpu	2026-02-24 07:17:16.74+00
\N	260	cpu_usage_percent	26.020175438596908	percent	cpu	2026-02-24 07:18:16.74+00
\N	260	cpu_usage_percent	26.160416666687908	percent	cpu	2026-02-24 07:19:16.74+00
\N	260	cpu_usage_percent	26.23070175438842	percent	cpu	2026-02-24 07:20:16.74+00
\N	260	cpu_usage_percent	26.182894736871518	percent	cpu	2026-02-24 07:21:16.74+00
\N	248	cpu_usage_percent	2.343421052618524	percent	cpu	2026-02-24 08:36:33.225+00
\N	236	cpu_usage_percent	1.6000000000196195	percent	cpu	2026-02-24 06:39:10.822+00
\N	236	cpu_usage_percent	1.5754385965696684	percent	cpu	2026-02-24 06:40:10.822+00
\N	236	cpu_usage_percent	1.498245614041636	percent	cpu	2026-02-24 06:41:10.822+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	cpu	2026-02-24 06:42:10.822+00
\N	236	cpu_usage_percent	1.498245614041636	percent	cpu	2026-02-24 06:43:10.822+00
\N	236	cpu_usage_percent	1.807017543826987	percent	cpu	2026-02-24 06:44:10.822+00
\N	257	cpu_usage_percent	4.01491228072382	percent	cpu	2026-02-24 06:09:06.84+00
\N	257	cpu_usage_percent	4.641228070168097	percent	cpu	2026-02-24 06:10:06.84+00
\N	257	cpu_usage_percent	5.04473684210609	percent	cpu	2026-02-24 06:11:06.84+00
\N	257	cpu_usage_percent	5.184210526303545	percent	cpu	2026-02-24 06:12:06.84+00
\N	257	cpu_usage_percent	5.282456140307588	percent	cpu	2026-02-24 06:13:06.84+00
\N	257	cpu_usage_percent	4.8236842105459345	percent	cpu	2026-02-24 06:14:06.84+00
\N	257	cpu_usage_percent	4.7236842105549215	percent	cpu	2026-02-24 06:15:06.84+00
\N	257	cpu_usage_percent	4.315789473680141	percent	cpu	2026-02-24 06:16:06.84+00
\N	257	cpu_usage_percent	4.29385964911873	percent	cpu	2026-02-24 06:17:06.84+00
\N	257	cpu_usage_percent	4.003508771920849	percent	cpu	2026-02-24 06:18:06.84+00
\N	257	cpu_usage_percent	4.2552631578955555	percent	cpu	2026-02-24 06:19:06.84+00
\N	257	cpu_usage_percent	4.632456140335364	percent	cpu	2026-02-24 06:20:06.84+00
\N	257	cpu_usage_percent	5.005263157858792	percent	cpu	2026-02-24 06:21:06.84+00
\N	236	cpu_usage_percent	1.8245614035741369	percent	cpu	2026-02-24 06:45:10.822+00
\N	236	cpu_usage_percent	1.778947368362239	percent	cpu	2026-02-24 06:46:10.822+00
\N	236	cpu_usage_percent	1.782456140377036	percent	cpu	2026-02-24 06:47:10.822+00
\N	236	cpu_usage_percent	1.6280701754843534	percent	cpu	2026-02-24 06:48:10.822+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	cpu	2026-02-24 06:49:10.822+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	cpu	2026-02-24 06:50:10.822+00
\N	248	cpu_usage_percent	2.549561403544729	percent	cpu	2026-02-24 05:49:03.176+00
\N	248	cpu_usage_percent	2.5552631578849514	percent	cpu	2026-02-24 05:50:03.176+00
\N	236	cpu_usage_percent	1.3192982456990023	percent	cpu	2026-02-24 06:51:10.822+00
\N	248	cpu_usage_percent	4.47236842104121	percent	cpu	2026-02-24 08:37:33.225+00
\N	248	cpu_usage_percent	4.536403508799708	percent	cpu	2026-02-24 08:38:33.225+00
\N	248	cpu_usage_percent	2.471929824535266	percent	cpu	2026-02-24 05:51:03.176+00
\N	248	cpu_usage_percent	2.4491228070110225	percent	cpu	2026-02-24 05:52:03.176+00
\N	248	cpu_usage_percent	2.3692982456761342	percent	cpu	2026-02-24 05:53:03.176+00
\N	248	cpu_usage_percent	2.380701754356565	percent	cpu	2026-02-24 05:54:03.176+00
\N	248	cpu_usage_percent	2.356578947347188	percent	cpu	2026-02-24 05:55:03.176+00
\N	248	cpu_usage_percent	2.3364035088748665	percent	cpu	2026-02-24 05:56:03.176+00
\N	248	cpu_usage_percent	2.3074561403247458	percent	cpu	2026-02-24 05:57:03.176+00
\N	248	cpu_usage_percent	2.2701754385866906	percent	cpu	2026-02-24 05:58:03.176+00
\N	248	cpu_usage_percent	2.198684210480579	percent	cpu	2026-02-24 05:59:03.176+00
\N	248	cpu_usage_percent	2.243421052647932	percent	cpu	2026-02-24 06:00:03.176+00
\N	248	cpu_usage_percent	2.4131578948397845	percent	cpu	2026-02-24 06:01:03.176+00
\N	248	cpu_usage_percent	4.4820175438367755	percent	cpu	2026-02-24 08:39:33.225+00
\N	248	cpu_usage_percent	4.410087719290075	percent	cpu	2026-02-24 08:40:33.225+00
\N	248	cpu_usage_percent	3.9337719297608515	percent	cpu	2026-02-24 08:41:33.225+00
\N	257	cpu_usage_percent	4.609649122811106	percent	cpu	2026-02-24 07:49:22.594+00
\N	257	cpu_usage_percent	4.875438596518194	percent	cpu	2026-02-24 07:50:22.594+00
\N	257	cpu_usage_percent	5.20175438594859	percent	cpu	2026-02-24 07:51:22.594+00
\N	257	cpu_usage_percent	5.373684210506724	percent	cpu	2026-02-24 07:52:22.594+00
\N	257	cpu_usage_percent	5.208771929855615	percent	cpu	2026-02-24 07:53:22.594+00
\N	257	cpu_usage_percent	4.8333333333415	percent	cpu	2026-02-24 07:54:22.594+00
\N	257	cpu_usage_percent	4.960526315834414	percent	cpu	2026-02-24 07:55:22.594+00
\N	257	cpu_usage_percent	4.642105263151365	percent	cpu	2026-02-24 07:56:22.594+00
\N	257	cpu_usage_percent	4.584210526296189	percent	cpu	2026-02-24 07:57:22.594+00
\N	257	cpu_usage_percent	4.563157894738495	percent	cpu	2026-02-24 07:58:22.594+00
\N	248	cpu_usage_percent	2.434649122756369	percent	cpu	2026-02-24 06:39:11.096+00
\N	248	cpu_usage_percent	2.414035087802631	percent	cpu	2026-02-24 06:40:11.096+00
\N	248	cpu_usage_percent	2.3324561403378112	percent	cpu	2026-02-24 06:41:11.096+00
\N	248	cpu_usage_percent	2.282456140311666	percent	cpu	2026-02-24 06:42:11.096+00
\N	248	cpu_usage_percent	2.3719298246463723	percent	cpu	2026-02-24 06:43:11.096+00
\N	248	cpu_usage_percent	2.5986842105263293	percent	cpu	2026-02-24 06:44:11.096+00
\N	248	cpu_usage_percent	2.6276315789539098	percent	cpu	2026-02-24 06:45:11.096+00
\N	248	cpu_usage_percent	2.6552631578555292	percent	cpu	2026-02-24 06:46:11.096+00
\N	248	cpu_usage_percent	2.6934210526381293	percent	cpu	2026-02-24 06:47:11.096+00
\N	248	cpu_usage_percent	2.613596491180701	percent	cpu	2026-02-24 06:48:11.096+00
\N	248	cpu_usage_percent	2.3618421052876784	percent	cpu	2026-02-24 06:49:11.096+00
\N	248	cpu_usage_percent	2.238596491188872	percent	cpu	2026-02-24 06:50:11.096+00
\N	260	cpu_usage_percent	25.545504385995557	percent	cpu	2026-02-24 06:09:07.143+00
\N	260	cpu_usage_percent	25.572149122824186	percent	cpu	2026-02-24 06:10:07.143+00
\N	260	cpu_usage_percent	25.54736842104161	percent	cpu	2026-02-24 06:11:07.143+00
\N	260	cpu_usage_percent	25.626425438595263	percent	cpu	2026-02-24 06:12:07.143+00
\N	260	cpu_usage_percent	25.577521929813543	percent	cpu	2026-02-24 06:13:07.143+00
\N	260	cpu_usage_percent	25.58925438595716	percent	cpu	2026-02-24 06:14:07.143+00
\N	260	cpu_usage_percent	25.615789473696054	percent	cpu	2026-02-24 06:15:07.143+00
\N	260	cpu_usage_percent	25.500000000016342	percent	cpu	2026-02-24 06:16:07.143+00
\N	252	cpu_usage_percent	23.845614035135938	percent	cpu	2026-02-24 05:49:03.414+00
\N	252	cpu_usage_percent	23.970175438638165	percent	cpu	2026-02-24 05:50:03.414+00
\N	252	cpu_usage_percent	23.79649122811348	percent	cpu	2026-02-24 05:51:03.414+00
\N	252	cpu_usage_percent	23.63728070176174	percent	cpu	2026-02-24 05:52:03.414+00
\N	252	cpu_usage_percent	23.58596491229133	percent	cpu	2026-02-24 05:53:03.414+00
\N	252	cpu_usage_percent	23.327192982450427	percent	cpu	2026-02-24 05:54:03.414+00
\N	252	cpu_usage_percent	23.363157894703363	percent	cpu	2026-02-24 05:55:03.414+00
\N	252	cpu_usage_percent	23.61710526316689	percent	cpu	2026-02-24 05:56:03.414+00
\N	252	cpu_usage_percent	23.614473684237495	percent	cpu	2026-02-24 05:57:03.414+00
\N	252	cpu_usage_percent	23.52543859648634	percent	cpu	2026-02-24 05:58:03.414+00
\N	252	cpu_usage_percent	23.52719298245289	percent	cpu	2026-02-24 05:59:03.414+00
\N	252	cpu_usage_percent	23.695614035077924	percent	cpu	2026-02-24 06:00:03.414+00
\N	252	cpu_usage_percent	23.43903508772584	percent	cpu	2026-02-24 06:01:03.414+00
\N	260	cpu_usage_percent	25.55394736841616	percent	cpu	2026-02-24 06:17:07.143+00
\N	260	cpu_usage_percent	25.50592105263813	percent	cpu	2026-02-24 06:18:07.143+00
\N	260	cpu_usage_percent	25.527083333316185	percent	cpu	2026-02-24 06:19:07.143+00
\N	260	cpu_usage_percent	25.51250000001268	percent	cpu	2026-02-24 06:20:07.143+00
\N	260	cpu_usage_percent	25.49725877194618	percent	cpu	2026-02-24 06:21:07.143+00
\N	248	cpu_usage_percent	2.111842105197809	percent	cpu	2026-02-24 06:51:11.096+00
\N	257	cpu_usage_percent	4.44473684211917	percent	cpu	2026-02-24 07:59:22.594+00
\N	236	cpu_usage_percent	1.5789473684210549	percent	cpu	2026-02-24 07:19:17.315+00
\N	236	cpu_usage_percent	1.5543859648077216	percent	cpu	2026-02-24 07:20:17.315+00
\N	236	cpu_usage_percent	1.5438596490901375	percent	cpu	2026-02-24 07:21:17.315+00
\N	236	cpu_usage_percent	1.5403508770753405	percent	cpu	2026-02-24 07:22:17.315+00
\N	236	cpu_usage_percent	1.498245614041636	percent	cpu	2026-02-24 07:23:17.315+00
\N	236	cpu_usage_percent	1.6350877193505369	percent	cpu	2026-02-24 07:24:17.315+00
\N	236	cpu_usage_percent	1.8210526317227362	percent	cpu	2026-02-24 07:25:17.315+00
\N	236	cpu_usage_percent	1.8561403508902856	percent	cpu	2026-02-24 07:26:17.315+00
\N	236	cpu_usage_percent	1.849122807024088	percent	cpu	2026-02-24 07:27:17.315+00
\N	236	cpu_usage_percent	1.8631578947564549	percent	cpu	2026-02-24 07:28:17.315+00
\N	236	cpu_usage_percent	1.6982456141462023	percent	cpu	2026-02-24 07:29:17.315+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	cpu	2026-02-24 07:30:17.315+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	cpu	2026-02-24 07:31:17.315+00
\N	257	cpu_usage_percent	4.8429824561370935	percent	cpu	2026-02-24 08:00:22.594+00
\N	257	cpu_usage_percent	5.109649122807028	percent	cpu	2026-02-24 08:01:22.594+00
\N	248	cpu_usage_percent	2.6154987841563297	percent	cpu	2026-02-24 09:09:43.342+00
\N	252	cpu_usage_percent	27.893859649121993	percent	cpu	2026-02-24 06:39:11.361+00
\N	252	cpu_usage_percent	27.799561403512058	percent	cpu	2026-02-24 06:40:11.361+00
\N	252	cpu_usage_percent	26.74385964913344	percent	cpu	2026-02-24 06:41:11.361+00
\N	252	cpu_usage_percent	26.287280701717634	percent	cpu	2026-02-24 06:42:11.361+00
\N	252	cpu_usage_percent	25.803947368424332	percent	cpu	2026-02-24 06:43:11.361+00
\N	252	cpu_usage_percent	25.820614035106516	percent	cpu	2026-02-24 06:44:11.361+00
\N	252	cpu_usage_percent	25.55263157893104	percent	cpu	2026-02-24 06:45:11.361+00
\N	252	cpu_usage_percent	25.416666666707528	percent	cpu	2026-02-24 06:46:11.361+00
\N	252	cpu_usage_percent	25.30570175439496	percent	cpu	2026-02-24 06:47:11.361+00
\N	252	cpu_usage_percent	25.210964912242304	percent	cpu	2026-02-24 06:48:11.361+00
\N	252	cpu_usage_percent	25.006140350862495	percent	cpu	2026-02-24 06:49:11.361+00
\N	248	cpu_usage_percent	2.4797810564726888	percent	cpu	2026-02-24 09:10:43.342+00
\N	257	cpu_usage_percent	4.390350877156223	percent	cpu	2026-02-24 05:49:03.644+00
\N	257	cpu_usage_percent	4.7456140350754765	percent	cpu	2026-02-24 05:50:03.644+00
\N	257	cpu_usage_percent	5.101754385977998	percent	cpu	2026-02-24 05:51:03.644+00
\N	257	cpu_usage_percent	5.306140350835548	percent	cpu	2026-02-24 05:52:03.644+00
\N	257	cpu_usage_percent	5.2912280701811625	percent	cpu	2026-02-24 05:53:03.644+00
\N	257	cpu_usage_percent	5.120175438585889	percent	cpu	2026-02-24 05:54:03.644+00
\N	257	cpu_usage_percent	4.794736842097919	percent	cpu	2026-02-24 05:55:03.644+00
\N	257	cpu_usage_percent	4.429824561403521	percent	cpu	2026-02-24 05:56:03.644+00
\N	257	cpu_usage_percent	4.2728070175406	percent	cpu	2026-02-24 05:57:03.644+00
\N	257	cpu_usage_percent	3.944736842082392	percent	cpu	2026-02-24 05:58:03.644+00
\N	257	cpu_usage_percent	4.3280701754663795	percent	cpu	2026-02-24 05:59:03.644+00
\N	257	cpu_usage_percent	4.7263157895047385	percent	cpu	2026-02-24 06:00:03.644+00
\N	257	cpu_usage_percent	5.025438596514931	percent	cpu	2026-02-24 06:01:03.644+00
\N	133	cpu_usage_percent	0.454385964967841	percent	cpu	2026-02-24 07:19:17+00
\N	133	cpu_usage_percent	0.4355263158172562	percent	cpu	2026-02-24 07:20:17+00
\N	133	cpu_usage_percent	0.44122807015747867	percent	cpu	2026-02-24 07:21:17+00
\N	133	cpu_usage_percent	0.4425438596017557	percent	cpu	2026-02-24 07:22:17+00
\N	133	cpu_usage_percent	0.44078947363520626	percent	cpu	2026-02-24 07:23:17+00
\N	133	cpu_usage_percent	0.5614035086820763	percent	cpu	2026-02-24 07:24:17+00
\N	248	cpu_usage_percent	2.388157894826719	percent	cpu	2026-02-24 06:19:08.022+00
\N	248	cpu_usage_percent	2.633333333294132	percent	cpu	2026-02-24 06:20:08.022+00
\N	248	cpu_usage_percent	2.6206140350468843	percent	cpu	2026-02-24 06:21:08.022+00
\N	248	cpu_usage_percent	2.619736842124894	percent	cpu	2026-02-24 06:22:08.022+00
\N	248	cpu_usage_percent	2.50745614038847	percent	cpu	2026-02-24 06:23:08.022+00
\N	248	cpu_usage_percent	2.6464912280636526	percent	cpu	2026-02-24 06:24:08.022+00
\N	248	cpu_usage_percent	2.4030701754810906	percent	cpu	2026-02-24 06:25:08.022+00
\N	248	cpu_usage_percent	2.391228070114991	percent	cpu	2026-02-24 06:26:08.022+00
\N	248	cpu_usage_percent	2.47149122805385	percent	cpu	2026-02-24 06:27:08.022+00
\N	248	cpu_usage_percent	2.5399122806266092	percent	cpu	2026-02-24 06:28:08.022+00
\N	248	cpu_usage_percent	2.4916666666487117	percent	cpu	2026-02-24 06:29:08.022+00
\N	248	cpu_usage_percent	2.3964912280554813	percent	cpu	2026-02-24 06:30:08.022+00
\N	248	cpu_usage_percent	2.592982456186107	percent	cpu	2026-02-24 06:31:08.022+00
\N	133	cpu_usage_percent	0.6719298245744909	percent	cpu	2026-02-24 07:25:17+00
\N	133	cpu_usage_percent	0.678508771918402	percent	cpu	2026-02-24 07:26:17+00
\N	133	cpu_usage_percent	0.6833333332957636	percent	cpu	2026-02-24 07:27:17+00
\N	133	cpu_usage_percent	0.665789473671154	percent	cpu	2026-02-24 07:28:17+00
\N	133	cpu_usage_percent	0.4833333333545795	percent	cpu	2026-02-24 07:29:17+00
\N	133	cpu_usage_percent	0.43947368419092925	percent	cpu	2026-02-24 07:30:17+00
\N	133	cpu_usage_percent	0.451754385997603	percent	cpu	2026-02-24 07:31:17+00
\N	252	cpu_usage_percent	25.43991228069278	percent	cpu	2026-02-24 08:29:33.64+00
\N	252	cpu_usage_percent	24.279824561427205	percent	cpu	2026-02-24 08:30:33.64+00
\N	252	cpu_usage_percent	24.039473684214613	percent	cpu	2026-02-24 08:31:33.64+00
\N	252	cpu_usage_percent	24.05438596490984	percent	cpu	2026-02-24 08:32:33.64+00
\N	252	cpu_usage_percent	23.45482456136348	percent	cpu	2026-02-24 08:33:33.64+00
\N	260	cpu_usage_percent	25.462938596488385	percent	cpu	2026-02-24 05:49:03.884+00
\N	260	cpu_usage_percent	25.489473684227278	percent	cpu	2026-02-24 05:50:03.884+00
\N	260	cpu_usage_percent	25.461513157923747	percent	cpu	2026-02-24 05:51:03.884+00
\N	260	cpu_usage_percent	25.49550438594899	percent	cpu	2026-02-24 05:52:03.884+00
\N	260	cpu_usage_percent	25.503508771969862	percent	cpu	2026-02-24 05:53:03.884+00
\N	260	cpu_usage_percent	25.57258771924434	percent	cpu	2026-02-24 05:54:03.884+00
\N	260	cpu_usage_percent	25.55559210528277	percent	cpu	2026-02-24 05:55:03.884+00
\N	260	cpu_usage_percent	25.56052631579071	percent	cpu	2026-02-24 05:56:03.884+00
\N	260	cpu_usage_percent	25.567543859687518	percent	cpu	2026-02-24 05:57:03.884+00
\N	260	cpu_usage_percent	25.51973684207873	percent	cpu	2026-02-24 05:58:03.884+00
\N	260	cpu_usage_percent	25.528728070203215	percent	cpu	2026-02-24 05:59:03.884+00
\N	260	cpu_usage_percent	25.50635964913998	percent	cpu	2026-02-24 06:00:03.884+00
\N	260	cpu_usage_percent	25.59067982454222	percent	cpu	2026-02-24 06:01:03.884+00
\N	252	cpu_usage_percent	23.7043859649515	percent	cpu	2026-02-24 08:34:33.64+00
\N	252	cpu_usage_percent	23.700438596516562	percent	cpu	2026-02-24 08:35:33.64+00
\N	260	cpu_usage_percent	26.838377192953445	percent	cpu	2026-02-24 07:49:22.832+00
\N	260	cpu_usage_percent	26.51195175438228	percent	cpu	2026-02-24 07:50:22.832+00
\N	260	cpu_usage_percent	26.797697368402666	percent	cpu	2026-02-24 07:51:22.832+00
\N	260	cpu_usage_percent	26.524890350870237	percent	cpu	2026-02-24 07:52:22.832+00
\N	260	cpu_usage_percent	26.3674342105259	percent	cpu	2026-02-24 07:53:22.832+00
\N	260	cpu_usage_percent	26.083223684200718	percent	cpu	2026-02-24 07:54:22.832+00
\N	260	cpu_usage_percent	25.88585526318893	percent	cpu	2026-02-24 07:55:22.832+00
\N	260	cpu_usage_percent	25.914144736843326	percent	cpu	2026-02-24 07:56:22.832+00
\N	260	cpu_usage_percent	26.214692982469202	percent	cpu	2026-02-24 07:57:22.832+00
\N	248	cpu_usage_percent	2.2916666666666714	percent	cpu	2026-02-24 07:19:17.575+00
\N	248	cpu_usage_percent	2.50745614038847	percent	cpu	2026-02-24 07:20:17.575+00
\N	248	cpu_usage_percent	2.529385964909025	percent	cpu	2026-02-24 07:21:17.575+00
\N	248	cpu_usage_percent	2.5105263157992823	percent	cpu	2026-02-24 07:22:17.575+00
\N	248	cpu_usage_percent	2.4951754385817964	percent	cpu	2026-02-24 07:23:17.575+00
\N	248	cpu_usage_percent	2.6425438597716777	percent	cpu	2026-02-24 07:24:17.575+00
\N	248	cpu_usage_percent	2.4592105263288744	percent	cpu	2026-02-24 07:25:17.575+00
\N	248	cpu_usage_percent	2.442543859667097	percent	cpu	2026-02-24 07:26:17.575+00
\N	248	cpu_usage_percent	2.478070175397761	percent	cpu	2026-02-24 07:27:17.575+00
\N	248	cpu_usage_percent	2.4403508771782896	percent	cpu	2026-02-24 07:28:17.575+00
\N	248	cpu_usage_percent	2.362719298250525	percent	cpu	2026-02-24 07:29:17.575+00
\N	248	cpu_usage_percent	2.4092105262618873	percent	cpu	2026-02-24 07:30:17.575+00
\N	252	cpu_usage_percent	22.95350877192331	percent	cpu	2026-02-24 06:19:08.28+00
\N	252	cpu_usage_percent	23.039473684222784	percent	cpu	2026-02-24 06:20:08.28+00
\N	252	cpu_usage_percent	23.06315789473031	percent	cpu	2026-02-24 06:21:08.28+00
\N	252	cpu_usage_percent	23.267105263147286	percent	cpu	2026-02-24 06:22:08.28+00
\N	252	cpu_usage_percent	23.369736842067695	percent	cpu	2026-02-24 06:23:08.28+00
\N	252	cpu_usage_percent	23.745175438622653	percent	cpu	2026-02-24 06:24:08.28+00
\N	248	cpu_usage_percent	2.4811403508494294	percent	cpu	2026-02-24 07:31:17.575+00
\N	252	cpu_usage_percent	23.54385964911465	percent	cpu	2026-02-24 08:36:33.64+00
\N	252	cpu_usage_percent	25.04254385963769	percent	cpu	2026-02-24 06:50:11.361+00
\N	252	cpu_usage_percent	24.666228070181162	percent	cpu	2026-02-24 06:51:11.361+00
\N	133	cpu_usage_percent	0.42149122804404726	percent	cpu	2026-02-24 06:19:07.449+00
\N	133	cpu_usage_percent	0.4236842104920129	percent	cpu	2026-02-24 06:20:07.449+00
\N	133	cpu_usage_percent	0.42105263160347306	percent	cpu	2026-02-24 06:21:07.449+00
\N	133	cpu_usage_percent	0.42236842104773586	percent	cpu	2026-02-24 06:22:07.449+00
\N	133	cpu_usage_percent	0.42017543855892825	percent	cpu	2026-02-24 06:23:07.449+00
\N	133	cpu_usage_percent	0.5728070174850615	percent	cpu	2026-02-24 06:24:07.449+00
\N	133	cpu_usage_percent	0.5587719298752205	percent	cpu	2026-02-24 06:25:07.449+00
\N	133	cpu_usage_percent	0.5811403508771917	percent	cpu	2026-02-24 06:26:07.449+00
\N	133	cpu_usage_percent	0.5991228070240879	percent	cpu	2026-02-24 06:27:07.449+00
\N	133	cpu_usage_percent	0.7921052631399306	percent	cpu	2026-02-24 06:28:07.449+00
\N	133	cpu_usage_percent	0.7657894736417461	percent	cpu	2026-02-24 06:29:07.449+00
\N	133	cpu_usage_percent	0.6631578947009018	percent	cpu	2026-02-24 06:30:07.449+00
\N	133	cpu_usage_percent	0.8122807018164764	percent	cpu	2026-02-24 06:31:07.449+00
\N	248	cpu_usage_percent	2.526754385938773	percent	cpu	2026-02-24 09:11:43.342+00
\N	248	cpu_usage_percent	2.529385964909025	percent	cpu	2026-02-24 09:12:43.342+00
\N	248	cpu_usage_percent	2.5100961723264277	percent	cpu	2026-02-24 09:13:43.342+00
\N	248	cpu_usage_percent	2.584694468190037	percent	cpu	2026-02-24 09:14:43.342+00
\N	248	cpu_usage_percent	2.635526315701256	percent	cpu	2026-02-24 09:15:43.342+00
\N	248	cpu_usage_percent	2.577051009409942	percent	cpu	2026-02-24 09:16:43.342+00
\N	248	cpu_usage_percent	2.5675955425497534	percent	cpu	2026-02-24 09:17:43.342+00
\N	248	cpu_usage_percent	2.387280701823016	percent	cpu	2026-02-24 09:18:43.342+00
\N	248	cpu_usage_percent	2.309210526332137	percent	cpu	2026-02-24 09:19:43.342+00
\N	248	cpu_usage_percent	2.506140350862495	percent	cpu	2026-02-24 09:20:43.342+00
\N	248	cpu_usage_percent	2.500052630869675	percent	cpu	2026-02-24 09:21:43.342+00
\N	257	cpu_usage_percent	4.691228070194242	percent	cpu	2026-02-24 08:29:34.109+00
\N	257	cpu_usage_percent	4.984210526341954	percent	cpu	2026-02-24 08:30:34.109+00
\N	257	cpu_usage_percent	5.214035087714407	percent	cpu	2026-02-24 08:31:34.109+00
\N	257	cpu_usage_percent	5.384210526305992	percent	cpu	2026-02-24 08:32:34.109+00
\N	257	cpu_usage_percent	5.194736842082406	percent	cpu	2026-02-24 08:33:34.109+00
\N	257	cpu_usage_percent	4.8377192982374595	percent	cpu	2026-02-24 08:34:34.109+00
\N	257	cpu_usage_percent	4.740810655311918	percent	cpu	2026-02-24 08:35:34.109+00
\N	257	cpu_usage_percent	4.441228070186071	percent	cpu	2026-02-24 06:39:11.659+00
\N	257	cpu_usage_percent	4.828947368425148	percent	cpu	2026-02-24 06:40:11.659+00
\N	257	cpu_usage_percent	5.1438596491342565	percent	cpu	2026-02-24 06:41:11.659+00
\N	257	cpu_usage_percent	5.426315789503093	percent	cpu	2026-02-24 06:42:11.659+00
\N	257	cpu_usage_percent	5.343859649075426	percent	cpu	2026-02-24 06:43:11.659+00
\N	257	cpu_usage_percent	5.4859649123043965	percent	cpu	2026-02-24 06:44:11.659+00
\N	257	cpu_usage_percent	5.074561403496531	percent	cpu	2026-02-24 06:45:11.659+00
\N	257	cpu_usage_percent	4.412280701738055	percent	cpu	2026-02-24 06:46:11.659+00
\N	257	cpu_usage_percent	4.467543859663834	percent	cpu	2026-02-24 06:47:11.659+00
\N	257	cpu_usage_percent	4.478070175463117	percent	cpu	2026-02-24 06:48:11.659+00
\N	257	cpu_usage_percent	4.342105263137469	percent	cpu	2026-02-24 06:49:11.659+00
\N	257	cpu_usage_percent	4.729824561417402	percent	cpu	2026-02-24 06:50:11.659+00
\N	257	cpu_usage_percent	4.878947368410451	percent	cpu	2026-02-24 06:51:11.659+00
\N	257	cpu_usage_percent	4.287719298256249	percent	cpu	2026-02-24 08:36:34.109+00
\N	257	cpu_usage_percent	4.535087719294168	percent	cpu	2026-02-24 08:37:34.109+00
\N	257	cpu_usage_percent	4.521929824585925	percent	cpu	2026-02-24 08:38:34.109+00
\N	257	cpu_usage_percent	4.6456140350844635	percent	cpu	2026-02-24 08:39:34.109+00
\N	257	cpu_usage_percent	4.969298245605884	percent	cpu	2026-02-24 08:40:34.109+00
\N	257	cpu_usage_percent	4.897368421059184	percent	cpu	2026-02-24 08:41:34.109+00
\N	236	cpu_usage_percent	1.522807017491587	percent	cpu	2026-02-24 06:19:07.727+00
\N	236	cpu_usage_percent	1.5438596490901375	percent	cpu	2026-02-24 06:20:07.727+00
\N	236	cpu_usage_percent	1.5719298245548714	percent	cpu	2026-02-24 06:21:07.727+00
\N	236	cpu_usage_percent	1.589473684138639	percent	cpu	2026-02-24 06:22:07.727+00
\N	236	cpu_usage_percent	1.52631578950637	percent	cpu	2026-02-24 06:23:07.727+00
\N	236	cpu_usage_percent	1.7614035087784856	percent	cpu	2026-02-24 06:24:07.727+00
\N	236	cpu_usage_percent	1.592982456153436	percent	cpu	2026-02-24 06:25:07.727+00
\N	236	cpu_usage_percent	1.782456140377036	percent	cpu	2026-02-24 06:26:07.727+00
\N	236	cpu_usage_percent	1.7929824560946201	percent	cpu	2026-02-24 06:27:07.727+00
\N	236	cpu_usage_percent	1.6526315789343045	percent	cpu	2026-02-24 06:28:07.727+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	cpu	2026-02-24 06:29:07.727+00
\N	236	cpu_usage_percent	1.3017543859518526	percent	cpu	2026-02-24 06:30:07.727+00
\N	236	cpu_usage_percent	1.4456140351269369	percent	cpu	2026-02-24 06:31:07.727+00
\N	236	cpu_usage_percent	1.5263157893429735	percent	cpu	2026-02-24 07:59:23.395+00
\N	236	cpu_usage_percent	1.470175438576888	percent	cpu	2026-02-24 08:00:23.395+00
\N	236	cpu_usage_percent	1.4807017544578684	percent	cpu	2026-02-24 08:01:23.395+00
\N	236	cpu_usage_percent	1.4350877192459706	percent	cpu	2026-02-24 08:02:23.395+00
\N	236	cpu_usage_percent	1.4245614035283864	percent	cpu	2026-02-24 08:03:23.395+00
\N	236	cpu_usage_percent	1.4140350876474201	percent	cpu	2026-02-24 08:04:23.395+00
\N	236	cpu_usage_percent	1.5789473684210549	percent	cpu	2026-02-24 08:05:23.395+00
\N	236	cpu_usage_percent	2.2877192982521564	percent	cpu	2026-02-24 08:06:23.395+00
\N	236	cpu_usage_percent	2.3157894737169045	percent	cpu	2026-02-24 08:07:23.395+00
\N	236	cpu_usage_percent	2.3157894737169045	percent	cpu	2026-02-24 08:08:23.395+00
\N	236	cpu_usage_percent	2.20000000000654	percent	cpu	2026-02-24 08:09:23.395+00
\N	236	cpu_usage_percent	1.3192982455356201	percent	cpu	2026-02-24 08:10:23.395+00
\N	260	cpu_usage_percent	25.517653508761313	percent	cpu	2026-02-24 06:39:11.889+00
\N	260	cpu_usage_percent	25.555701754423552	percent	cpu	2026-02-24 06:40:11.889+00
\N	260	cpu_usage_percent	25.605921052649563	percent	cpu	2026-02-24 06:41:11.889+00
\N	260	cpu_usage_percent	25.602083333345178	percent	cpu	2026-02-24 06:42:11.889+00
\N	260	cpu_usage_percent	25.629495614016307	percent	cpu	2026-02-24 06:43:11.889+00
\N	260	cpu_usage_percent	25.585087719312142	percent	cpu	2026-02-24 06:44:11.889+00
\N	260	cpu_usage_percent	25.561732456135047	percent	cpu	2026-02-24 06:45:11.889+00
\N	260	cpu_usage_percent	25.563486842122018	percent	cpu	2026-02-24 06:46:11.889+00
\N	260	cpu_usage_percent	25.647807017544693	percent	cpu	2026-02-24 06:47:11.889+00
\N	260	cpu_usage_percent	25.70932017548394	percent	cpu	2026-02-24 06:48:11.889+00
\N	260	cpu_usage_percent	25.662499999958342	percent	cpu	2026-02-24 06:49:11.889+00
\N	260	cpu_usage_percent	25.685745614025294	percent	cpu	2026-02-24 06:50:11.889+00
\N	260	cpu_usage_percent	25.564473684174587	percent	cpu	2026-02-24 06:51:11.889+00
\N	236	cpu_usage_percent	1.3999999999150532	percent	cpu	2026-02-24 08:11:23.395+00
\N	252	cpu_usage_percent	24.159210526339493	percent	cpu	2026-02-24 06:25:08.28+00
\N	252	cpu_usage_percent	24.128947368385937	percent	cpu	2026-02-24 06:26:08.28+00
\N	252	cpu_usage_percent	24.435526315805006	percent	cpu	2026-02-24 06:27:08.28+00
\N	252	cpu_usage_percent	24.574999999961605	percent	cpu	2026-02-24 06:28:08.28+00
\N	252	cpu_usage_percent	24.457894736847834	percent	cpu	2026-02-24 06:29:08.28+00
\N	252	cpu_usage_percent	24.35087719290894	percent	cpu	2026-02-24 06:30:08.28+00
\N	252	cpu_usage_percent	25.085964912299502	percent	cpu	2026-02-24 06:31:08.28+00
\N	252	cpu_usage_percent	23.79166666665442	percent	cpu	2026-02-24 08:37:33.64+00
\N	252	cpu_usage_percent	23.903070175427985	percent	cpu	2026-02-24 08:38:33.64+00
\N	252	cpu_usage_percent	23.610964912304397	percent	cpu	2026-02-24 08:39:33.64+00
\N	252	cpu_usage_percent	23.747368421070618	percent	cpu	2026-02-24 08:40:33.64+00
\N	252	cpu_usage_percent	23.533771929858062	percent	cpu	2026-02-24 08:41:33.64+00
\N	260	cpu_usage_percent	25.350328947390892	percent	cpu	2026-02-24 08:29:34.532+00
\N	260	cpu_usage_percent	25.3214912280326	percent	cpu	2026-02-24 08:30:34.532+00
\N	260	cpu_usage_percent	25.31962719300698	percent	cpu	2026-02-24 08:31:34.532+00
\N	260	cpu_usage_percent	26.20065789475727	percent	cpu	2026-02-24 08:32:34.532+00
\N	260	cpu_usage_percent	36.96567982456672	percent	cpu	2026-02-24 08:33:34.532+00
\N	260	cpu_usage_percent	47.749890350918456	percent	cpu	2026-02-24 08:34:34.532+00
\N	260	cpu_usage_percent	58.56304824565693	percent	cpu	2026-02-24 08:35:34.532+00
\N	260	cpu_usage_percent	69.22949561403999	percent	cpu	2026-02-24 08:36:34.532+00
\N	260	cpu_usage_percent	76.37949561402039	percent	cpu	2026-02-24 08:37:34.532+00
\N	260	cpu_usage_percent	76.32971491226559	percent	cpu	2026-02-24 08:38:34.532+00
\N	260	cpu_usage_percent	76.2197582413653	percent	cpu	2026-02-24 08:39:34.532+00
\N	260	cpu_usage_percent	72.34846491225701	percent	cpu	2026-02-24 08:40:34.532+00
\N	260	cpu_usage_percent	72.329276315776	percent	cpu	2026-02-24 08:41:34.532+00
\N	257	cpu_usage_percent	4.2552631578955555	percent	cpu	2026-02-24 06:19:08.545+00
\N	257	cpu_usage_percent	4.632456140335364	percent	cpu	2026-02-24 06:20:08.545+00
\N	257	cpu_usage_percent	5.005263157858792	percent	cpu	2026-02-24 06:21:08.545+00
\N	257	cpu_usage_percent	5.127192982452073	percent	cpu	2026-02-24 06:22:08.545+00
\N	257	cpu_usage_percent	5.011403508762129	percent	cpu	2026-02-24 06:23:08.545+00
\N	257	cpu_usage_percent	5.197368421052644	percent	cpu	2026-02-24 06:24:08.545+00
\N	257	cpu_usage_percent	4.716666666647882	percent	cpu	2026-02-24 06:25:08.545+00
\N	257	cpu_usage_percent	4.508771929857261	percent	cpu	2026-02-24 06:26:08.545+00
\N	257	cpu_usage_percent	4.395614035096713	percent	cpu	2026-02-24 06:27:08.545+00
\N	257	cpu_usage_percent	4.185964912298672	percent	cpu	2026-02-24 06:28:08.545+00
\N	257	cpu_usage_percent	4.299122807018378	percent	cpu	2026-02-24 06:29:08.545+00
\N	257	cpu_usage_percent	4.417543859637689	percent	cpu	2026-02-24 06:30:08.545+00
\N	257	cpu_usage_percent	5.092105263141562	percent	cpu	2026-02-24 06:31:08.545+00
\N	257	cpu_usage_percent	5.092105263161997	percent	cpu	2026-02-24 09:49:58.201+00
\N	257	cpu_usage_percent	5.238596491225621	percent	cpu	2026-02-24 09:50:58.201+00
\N	257	cpu_usage_percent	5.63859649123053	percent	cpu	2026-02-24 09:51:58.201+00
\N	257	cpu_usage_percent	5.4980315927542165	percent	cpu	2026-02-24 09:52:58.201+00
\N	257	cpu_usage_percent	5.24035087717175	percent	cpu	2026-02-24 09:53:58.201+00
\N	257	cpu_usage_percent	4.86666666666504	percent	cpu	2026-02-24 09:54:58.201+00
\N	257	cpu_usage_percent	4.4622807017642	percent	cpu	2026-02-24 09:55:58.201+00
\N	257	cpu_usage_percent	4.29385964911873	percent	cpu	2026-02-24 09:56:58.201+00
\N	133	cpu_usage_percent	0.6105263158270589	percent	cpu	2026-02-24 08:39:34.974+00
\N	133	cpu_usage_percent	0.5934210526021815	percent	cpu	2026-02-24 08:40:34.974+00
\N	133	cpu_usage_percent	0.3219298245140294	percent	cpu	2026-02-24 08:41:34.974+00
\N	133	cpu_usage_percent	0.4157894737038248	percent	cpu	2026-02-24 08:42:34.974+00
\N	133	cpu_usage_percent	0.4249999998954337	percent	cpu	2026-02-24 08:43:34.974+00
\N	133	cpu_usage_percent	0.4346491227727114	percent	cpu	2026-02-24 08:44:34.974+00
\N	133	cpu_usage_percent	2.471052631694974	percent	cpu	2026-02-24 08:45:34.974+00
\N	133	cpu_usage_percent	5.277192982469231	percent	cpu	2026-02-24 08:46:34.974+00
\N	133	cpu_usage_percent	7.919298245718622	percent	cpu	2026-02-24 08:47:34.974+00
\N	133	cpu_usage_percent	10.500438596497773	percent	cpu	2026-02-24 08:48:34.974+00
\N	133	cpu_usage_percent	10.520614035010937	percent	cpu	2026-02-24 08:49:34.974+00
\N	133	cpu_usage_percent	7.7719298245695825	percent	cpu	2026-02-24 08:50:34.974+00
\N	133	cpu_usage_percent	5.042105263197115	percent	cpu	2026-02-24 08:51:34.974+00
\N	257	cpu_usage_percent	4.48333333334233	percent	cpu	2026-02-24 09:57:58.201+00
\N	257	cpu_usage_percent	4.6263157894933045	percent	cpu	2026-02-24 09:58:58.201+00
\N	257	cpu_usage_percent	4.977192982434914	percent	cpu	2026-02-24 09:59:58.201+00
\N	257	cpu_usage_percent	4.934210526315795	percent	cpu	2026-02-24 10:00:58.201+00
\N	257	cpu_usage_percent	5.097368421061631	percent	cpu	2026-02-24 10:01:58.201+00
\N	248	cpu_usage_percent	2.3504385965255494	percent	cpu	2026-02-24 06:59:12.664+00
\N	248	cpu_usage_percent	2.5706140350615954	percent	cpu	2026-02-24 07:00:12.664+00
\N	248	cpu_usage_percent	2.588596491085923	percent	cpu	2026-02-24 07:01:12.664+00
\N	260	cpu_usage_percent	25.481249999996336	percent	cpu	2026-02-24 06:19:08.774+00
\N	260	cpu_usage_percent	25.525986842092195	percent	cpu	2026-02-24 06:20:08.774+00
\N	260	cpu_usage_percent	25.57094298246963	percent	cpu	2026-02-24 06:21:08.774+00
\N	260	cpu_usage_percent	25.535745614038774	percent	cpu	2026-02-24 06:22:08.774+00
\N	260	cpu_usage_percent	25.598684210522237	percent	cpu	2026-02-24 06:23:08.774+00
\N	260	cpu_usage_percent	25.53980263162471	percent	cpu	2026-02-24 06:24:08.774+00
\N	260	cpu_usage_percent	25.64232456139412	percent	cpu	2026-02-24 06:25:08.774+00
\N	260	cpu_usage_percent	25.572697368446384	percent	cpu	2026-02-24 06:26:08.774+00
\N	260	cpu_usage_percent	25.542543859643814	percent	cpu	2026-02-24 06:27:08.774+00
\N	260	cpu_usage_percent	25.502192982464322	percent	cpu	2026-02-24 06:28:08.774+00
\N	260	cpu_usage_percent	25.52225877194904	percent	cpu	2026-02-24 06:29:08.774+00
\N	260	cpu_usage_percent	25.451315789454895	percent	cpu	2026-02-24 06:30:08.774+00
\N	260	cpu_usage_percent	25.505482456146495	percent	cpu	2026-02-24 06:31:08.774+00
\N	260	cpu_usage_percent	26.342872807004454	percent	cpu	2026-02-24 07:58:22.832+00
\N	260	cpu_usage_percent	26.609978070196675	percent	cpu	2026-02-24 07:59:22.832+00
\N	260	cpu_usage_percent	26.36589912283071	percent	cpu	2026-02-24 08:00:22.832+00
\N	260	cpu_usage_percent	26.308771929797587	percent	cpu	2026-02-24 08:01:22.832+00
\N	248	cpu_usage_percent	2.632017543809013	percent	cpu	2026-02-24 09:49:57.351+00
\N	248	cpu_usage_percent	2.624949122169724	percent	cpu	2026-02-24 09:50:57.351+00
\N	248	cpu_usage_percent	2.5763157894426456	percent	cpu	2026-02-24 09:51:57.351+00
\N	248	cpu_usage_percent	2.438596491170898	percent	cpu	2026-02-24 09:52:57.351+00
\N	248	cpu_usage_percent	2.4451754385556512	percent	cpu	2026-02-24 09:53:57.351+00
\N	248	cpu_usage_percent	2.4530701755480777	percent	cpu	2026-02-24 09:54:57.351+00
\N	248	cpu_usage_percent	2.5425884664953884	percent	cpu	2026-02-24 09:55:57.351+00
\N	248	cpu_usage_percent	2.553456890623025	percent	cpu	2026-02-24 09:56:57.351+00
\N	133	cpu_usage_percent	1.043421052714919	percent	cpu	2026-02-24 06:49:12.135+00
\N	133	cpu_usage_percent	1.0342105262373735	percent	cpu	2026-02-24 06:50:12.135+00
\N	133	cpu_usage_percent	0.35263157894901553	percent	cpu	2026-02-24 06:51:12.135+00
\N	133	cpu_usage_percent	0.4429824561240139	percent	cpu	2026-02-24 06:52:12.135+00
\N	133	cpu_usage_percent	0.45745614037866744	percent	cpu	2026-02-24 06:53:12.135+00
\N	133	cpu_usage_percent	0.6548245613495993	percent	cpu	2026-02-24 06:54:12.135+00
\N	133	cpu_usage_percent	0.6881578947548235	percent	cpu	2026-02-24 06:55:12.135+00
\N	133	cpu_usage_percent	0.6899122806396747	percent	cpu	2026-02-24 06:56:12.135+00
\N	133	cpu_usage_percent	0.6789473684406602	percent	cpu	2026-02-24 06:57:12.135+00
\N	133	cpu_usage_percent	0.678508771918402	percent	cpu	2026-02-24 06:58:12.135+00
\N	133	cpu_usage_percent	0.45043859647162776	percent	cpu	2026-02-24 06:59:12.135+00
\N	133	cpu_usage_percent	0.44868421046423634	percent	cpu	2026-02-24 07:00:12.135+00
\N	133	cpu_usage_percent	0.4649122807262671	percent	cpu	2026-02-24 07:01:12.135+00
\N	248	cpu_usage_percent	2.5456140350485157	percent	cpu	2026-02-24 09:57:57.351+00
\N	133	cpu_usage_percent	0.453070175482722	percent	cpu	2026-02-24 07:59:23.077+00
\N	252	cpu_usage_percent	24.294736842081576	percent	cpu	2026-02-24 07:19:17.833+00
\N	252	cpu_usage_percent	24.223684210518158	percent	cpu	2026-02-24 07:20:17.833+00
\N	252	cpu_usage_percent	24.26754385970223	percent	cpu	2026-02-24 07:21:17.833+00
\N	252	cpu_usage_percent	24.132017543878447	percent	cpu	2026-02-24 07:22:17.833+00
\N	252	cpu_usage_percent	24.208333333321093	percent	cpu	2026-02-24 07:23:17.833+00
\N	252	cpu_usage_percent	24.756140350833903	percent	cpu	2026-02-24 07:24:17.833+00
\N	252	cpu_usage_percent	25.176754385976352	percent	cpu	2026-02-24 07:25:17.833+00
\N	252	cpu_usage_percent	25.171929824537713	percent	cpu	2026-02-24 07:26:17.833+00
\N	252	cpu_usage_percent	25.315789473651535	percent	cpu	2026-02-24 07:27:17.833+00
\N	252	cpu_usage_percent	25.248684210543487	percent	cpu	2026-02-24 07:28:17.833+00
\N	252	cpu_usage_percent	24.850438596464272	percent	cpu	2026-02-24 07:29:17.833+00
\N	252	cpu_usage_percent	24.657017543867013	percent	cpu	2026-02-24 07:30:17.833+00
\N	252	cpu_usage_percent	24.767105263135022	percent	cpu	2026-02-24 07:31:17.833+00
\N	133	cpu_usage_percent	0.4447368421722615	percent	cpu	2026-02-24 08:00:23.077+00
\N	133	cpu_usage_percent	0.4456140351351081	percent	cpu	2026-02-24 08:01:23.077+00
\N	133	cpu_usage_percent	0.41140350876703735	percent	cpu	2026-02-24 08:02:23.077+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	cpu	2026-02-24 06:49:12.409+00
\N	236	cpu_usage_percent	1.4526315789931203	percent	cpu	2026-02-24 06:50:12.409+00
\N	236	cpu_usage_percent	1.3192982456990023	percent	cpu	2026-02-24 06:51:12.409+00
\N	236	cpu_usage_percent	1.442105263112154	percent	cpu	2026-02-24 06:52:12.409+00
\N	236	cpu_usage_percent	1.4877192981606555	percent	cpu	2026-02-24 06:53:12.409+00
\N	236	cpu_usage_percent	1.7578947367636886	percent	cpu	2026-02-24 06:54:12.409+00
\N	236	cpu_usage_percent	1.8245614034107547	percent	cpu	2026-02-24 06:55:12.409+00
\N	236	cpu_usage_percent	1.6701754386814684	percent	cpu	2026-02-24 06:56:12.409+00
\N	236	cpu_usage_percent	1.8280701754255375	percent	cpu	2026-02-24 06:57:12.409+00
\N	236	cpu_usage_percent	1.8280701754255375	percent	cpu	2026-02-24 06:58:12.409+00
\N	236	cpu_usage_percent	1.536842105223954	percent	cpu	2026-02-24 06:59:12.409+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	cpu	2026-02-24 07:00:12.409+00
\N	236	cpu_usage_percent	1.5368421053873504	percent	cpu	2026-02-24 07:01:12.409+00
\N	133	cpu_usage_percent	0.4175438597112162	percent	cpu	2026-02-24 08:03:23.077+00
\N	133	cpu_usage_percent	0.40350877189715106	percent	cpu	2026-02-24 08:04:23.077+00
\N	133	cpu_usage_percent	0.5719298246038989	percent	cpu	2026-02-24 08:05:23.077+00
\N	133	cpu_usage_percent	0.5999999999869345	percent	cpu	2026-02-24 08:06:23.077+00
\N	133	cpu_usage_percent	0.6026315789571868	percent	cpu	2026-02-24 08:07:23.077+00
\N	133	cpu_usage_percent	0.608333333256553	percent	cpu	2026-02-24 08:08:23.077+00
\N	133	cpu_usage_percent	0.48596491232481753	percent	cpu	2026-02-24 08:09:23.077+00
\N	133	cpu_usage_percent	0.3710526316590119	percent	cpu	2026-02-24 08:10:23.077+00
\N	133	cpu_usage_percent	0.3969298245532542	percent	cpu	2026-02-24 08:11:23.077+00
\N	248	cpu_usage_percent	2.498245614033465	percent	cpu	2026-02-24 09:58:57.351+00
\N	248	cpu_usage_percent	2.4710526316132757	percent	cpu	2026-02-24 09:59:57.351+00
\N	248	cpu_usage_percent	2.563596491358794	percent	cpu	2026-02-24 10:00:57.351+00
\N	257	cpu_usage_percent	5.1666666666585	percent	cpu	2026-02-24 09:09:44.526+00
\N	257	cpu_usage_percent	5.245614035091819	percent	cpu	2026-02-24 09:10:44.526+00
\N	257	cpu_usage_percent	5.4219298245458845	percent	cpu	2026-02-24 09:11:44.526+00
\N	260	cpu_usage_percent	26.160416666687908	percent	cpu	2026-02-24 07:19:18.327+00
\N	260	cpu_usage_percent	26.23070175438842	percent	cpu	2026-02-24 07:20:18.327+00
\N	260	cpu_usage_percent	26.182894736871518	percent	cpu	2026-02-24 07:21:18.327+00
\N	248	cpu_usage_percent	2.2828947368339385	percent	cpu	2026-02-24 06:49:12.664+00
\N	248	cpu_usage_percent	2.1618421053464942	percent	cpu	2026-02-24 06:50:12.664+00
\N	248	cpu_usage_percent	2.1153508772125917	percent	cpu	2026-02-24 06:51:12.664+00
\N	248	cpu_usage_percent	2.217982456112594	percent	cpu	2026-02-24 06:52:12.664+00
\N	248	cpu_usage_percent	2.136842105292587	percent	cpu	2026-02-24 06:53:12.664+00
\N	248	cpu_usage_percent	2.230701754400684	percent	cpu	2026-02-24 06:54:12.664+00
\N	248	cpu_usage_percent	2.241228070077412	percent	cpu	2026-02-24 06:55:12.664+00
\N	248	cpu_usage_percent	2.3149122806723597	percent	cpu	2026-02-24 06:56:12.664+00
\N	248	cpu_usage_percent	2.298684210532869	percent	cpu	2026-02-24 06:57:12.664+00
\N	248	cpu_usage_percent	2.3048245613953497	percent	cpu	2026-02-24 06:58:12.664+00
\N	257	cpu_usage_percent	5.539473684202363	percent	cpu	2026-02-24 09:12:44.526+00
\N	248	cpu_usage_percent	2.6493322271669513	percent	cpu	2026-02-24 10:01:57.351+00
\N	252	cpu_usage_percent	24.91491228072465	percent	cpu	2026-02-24 09:09:43.888+00
\N	252	cpu_usage_percent	24.784649122759646	percent	cpu	2026-02-24 09:10:43.888+00
\N	252	cpu_usage_percent	24.75219298246023	percent	cpu	2026-02-24 09:11:43.888+00
\N	252	cpu_usage_percent	24.626315789513725	percent	cpu	2026-02-24 09:12:43.888+00
\N	252	cpu_usage_percent	24.622375046046102	percent	cpu	2026-02-24 09:13:43.888+00
\N	252	cpu_usage_percent	24.583771929855615	percent	cpu	2026-02-24 09:14:43.888+00
\N	252	cpu_usage_percent	24.74263338503377	percent	cpu	2026-02-24 09:15:43.888+00
\N	252	cpu_usage_percent	24.629824561385547	percent	cpu	2026-02-24 09:16:43.888+00
\N	252	cpu_usage_percent	24.736493077240752	percent	cpu	2026-02-24 09:17:43.888+00
\N	252	cpu_usage_percent	24.424999999985303	percent	cpu	2026-02-24 09:18:43.888+00
\N	252	cpu_usage_percent	24.516228070184425	percent	cpu	2026-02-24 09:19:43.888+00
\N	252	cpu_usage_percent	24.464912280714017	percent	cpu	2026-02-24 09:20:43.888+00
\N	252	cpu_usage_percent	24.474122807048587	percent	cpu	2026-02-24 09:21:43.888+00
\N	252	cpu_usage_percent	25.006140350862495	percent	cpu	2026-02-24 06:49:12.916+00
\N	252	cpu_usage_percent	25.04254385963769	percent	cpu	2026-02-24 06:50:12.916+00
\N	252	cpu_usage_percent	24.666228070181162	percent	cpu	2026-02-24 06:51:12.916+00
\N	252	cpu_usage_percent	24.796491228023626	percent	cpu	2026-02-24 06:52:12.916+00
\N	252	cpu_usage_percent	24.81359649120766	percent	cpu	2026-02-24 06:53:12.916+00
\N	252	cpu_usage_percent	25.043421052641392	percent	cpu	2026-02-24 06:54:12.916+00
\N	252	cpu_usage_percent	25.161403508758866	percent	cpu	2026-02-24 06:55:12.916+00
\N	252	cpu_usage_percent	25.44078947369647	percent	cpu	2026-02-24 06:56:12.916+00
\N	252	cpu_usage_percent	25.393859649121993	percent	cpu	2026-02-24 06:57:12.916+00
\N	252	cpu_usage_percent	25.494298245635278	percent	cpu	2026-02-24 06:58:12.916+00
\N	252	cpu_usage_percent	25.01008771929743	percent	cpu	2026-02-24 06:59:12.916+00
\N	252	cpu_usage_percent	24.996929824589188	percent	cpu	2026-02-24 07:00:12.916+00
\N	252	cpu_usage_percent	25.10175438593714	percent	cpu	2026-02-24 07:01:12.916+00
\N	257	cpu_usage_percent	4.482456140338627	percent	cpu	2026-02-24 07:19:18.076+00
\N	257	cpu_usage_percent	4.923684210516527	percent	cpu	2026-02-24 07:20:18.076+00
\N	257	cpu_usage_percent	5.331578947391307	percent	cpu	2026-02-24 07:21:18.076+00
\N	257	cpu_usage_percent	5.52456140350715	percent	cpu	2026-02-24 07:22:18.076+00
\N	257	cpu_usage_percent	5.397368421075527	percent	cpu	2026-02-24 07:23:18.076+00
\N	257	cpu_usage_percent	5.3333333333578565	percent	cpu	2026-02-24 07:24:18.076+00
\N	257	cpu_usage_percent	5.0464912280930605	percent	cpu	2026-02-24 07:25:18.076+00
\N	257	cpu_usage_percent	4.697368421077158	percent	cpu	2026-02-24 07:26:18.076+00
\N	257	cpu_usage_percent	4.645614035084449	percent	cpu	2026-02-24 07:27:18.076+00
\N	257	cpu_usage_percent	4.651754385967365	percent	cpu	2026-02-24 07:28:18.076+00
\N	257	cpu_usage_percent	4.722807017530798	percent	cpu	2026-02-24 07:29:18.076+00
\N	257	cpu_usage_percent	4.845614035086911	percent	cpu	2026-02-24 07:30:18.076+00
\N	257	cpu_usage_percent	5.252631578937567	percent	cpu	2026-02-24 07:31:18.076+00
\N	257	cpu_usage_percent	4.342105263137469	percent	cpu	2026-02-24 06:49:13.169+00
\N	257	cpu_usage_percent	4.729824561417402	percent	cpu	2026-02-24 06:50:13.169+00
\N	257	cpu_usage_percent	4.878947368410451	percent	cpu	2026-02-24 06:51:13.169+00
\N	257	cpu_usage_percent	5.2912280701607415	percent	cpu	2026-02-24 06:52:13.169+00
\N	257	cpu_usage_percent	5.282456140328009	percent	cpu	2026-02-24 06:53:13.169+00
\N	257	cpu_usage_percent	5.357017543885803	percent	cpu	2026-02-24 06:54:13.169+00
\N	257	cpu_usage_percent	5.038596491202753	percent	cpu	2026-02-24 06:55:13.169+00
\N	257	cpu_usage_percent	4.659649122796409	percent	cpu	2026-02-24 06:56:13.169+00
\N	257	cpu_usage_percent	4.569298245641832	percent	cpu	2026-02-24 06:57:13.169+00
\N	257	cpu_usage_percent	5.018421052648748	percent	cpu	2026-02-24 06:58:13.169+00
\N	257	cpu_usage_percent	4.795614035101622	percent	cpu	2026-02-24 06:59:13.169+00
\N	257	cpu_usage_percent	5.1798245614280205	percent	cpu	2026-02-24 07:00:13.169+00
\N	257	cpu_usage_percent	5.624561403498163	percent	cpu	2026-02-24 07:01:13.169+00
\N	260	cpu_usage_percent	82.23157894735331	percent	cpu	2026-02-24 09:09:45.148+00
\N	260	cpu_usage_percent	85.72720247159711	percent	cpu	2026-02-24 09:10:45.148+00
\N	260	cpu_usage_percent	87.64692982457571	percent	cpu	2026-02-24 09:11:45.148+00
\N	260	cpu_usage_percent	88.45285087718686	percent	cpu	2026-02-24 09:12:45.148+00
\N	260	cpu_usage_percent	90.59901315789351	percent	cpu	2026-02-24 09:13:45.148+00
\N	260	cpu_usage_percent	90.10746165747642	percent	cpu	2026-02-24 09:14:45.148+00
\N	260	cpu_usage_percent	89.69473684210689	percent	cpu	2026-02-24 09:15:45.148+00
\N	260	cpu_usage_percent	89.92653508768662	percent	cpu	2026-02-24 09:16:45.148+00
\N	260	cpu_usage_percent	25.662499999958342	percent	cpu	2026-02-24 06:49:13.435+00
\N	260	cpu_usage_percent	25.685745614025294	percent	cpu	2026-02-24 06:50:13.435+00
\N	260	cpu_usage_percent	25.564473684174587	percent	cpu	2026-02-24 06:51:13.435+00
\N	260	cpu_usage_percent	25.605043859656078	percent	cpu	2026-02-24 06:52:13.435+00
\N	260	cpu_usage_percent	25.53662280700162	percent	cpu	2026-02-24 06:53:13.435+00
\N	260	cpu_usage_percent	25.636951754374124	percent	cpu	2026-02-24 06:54:13.435+00
\N	260	cpu_usage_percent	25.62828947371281	percent	cpu	2026-02-24 06:55:13.435+00
\N	260	cpu_usage_percent	25.616885964879202	percent	cpu	2026-02-24 06:56:13.435+00
\N	260	cpu_usage_percent	25.63059210530156	percent	cpu	2026-02-24 06:57:13.435+00
\N	260	cpu_usage_percent	25.78629385960788	percent	cpu	2026-02-24 06:58:13.435+00
\N	260	cpu_usage_percent	25.792982456123198	percent	cpu	2026-02-24 06:59:13.435+00
\N	260	cpu_usage_percent	25.748793859629117	percent	cpu	2026-02-24 07:00:13.435+00
\N	260	cpu_usage_percent	25.818859649139966	percent	cpu	2026-02-24 07:01:13.435+00
\N	260	cpu_usage_percent	90.37499999998163	percent	cpu	2026-02-24 09:17:45.148+00
\N	260	cpu_usage_percent	90.99155701753038	percent	cpu	2026-02-24 09:18:45.148+00
\N	260	cpu_usage_percent	91.24484649124115	percent	cpu	2026-02-24 09:19:45.148+00
\N	260	cpu_usage_percent	91.20657894739946	percent	cpu	2026-02-24 09:20:45.148+00
\N	257	cpu_usage_percent	5.072929056872425	percent	cpu	2026-02-24 09:13:44.526+00
\N	257	cpu_usage_percent	4.909649122825002	percent	cpu	2026-02-24 09:14:44.526+00
\N	257	cpu_usage_percent	4.838596491220727	percent	cpu	2026-02-24 09:15:44.526+00
\N	257	cpu_usage_percent	4.478947368405542	percent	cpu	2026-02-24 09:16:44.526+00
\N	257	cpu_usage_percent	4.654385964917196	percent	cpu	2026-02-24 09:17:44.526+00
\N	257	cpu_usage_percent	4.430701754386789	percent	cpu	2026-02-24 09:18:44.526+00
\N	257	cpu_usage_percent	5.040350877210159	percent	cpu	2026-02-24 09:19:44.526+00
\N	257	cpu_usage_percent	5.116212157370981	percent	cpu	2026-02-24 09:20:44.526+00
\N	257	cpu_usage_percent	5.4807017543843415	percent	cpu	2026-02-24 09:21:44.526+00
\N	248	cpu_usage_percent	2.5096491227547375	percent	cpu	2026-02-24 07:59:23.65+00
\N	248	cpu_usage_percent	2.6451754385785335	percent	cpu	2026-02-24 08:00:23.65+00
\N	248	cpu_usage_percent	2.7500000000081855	percent	cpu	2026-02-24 08:01:23.65+00
\N	248	cpu_usage_percent	2.6605263157143355	percent	cpu	2026-02-24 08:02:23.65+00
\N	248	cpu_usage_percent	2.6118421052958496	percent	cpu	2026-02-24 08:03:23.65+00
\N	248	cpu_usage_percent	2.5850877192753785	percent	cpu	2026-02-24 08:04:23.65+00
\N	248	cpu_usage_percent	2.3789473683900155	percent	cpu	2026-02-24 08:05:23.65+00
\N	133	cpu_usage_percent	0.4833333333545795	percent	cpu	2026-02-24 07:29:18.579+00
\N	133	cpu_usage_percent	0.43947368419092925	percent	cpu	2026-02-24 07:30:18.579+00
\N	133	cpu_usage_percent	0.451754385997603	percent	cpu	2026-02-24 07:31:18.579+00
\N	133	cpu_usage_percent	0.45921052642690086	percent	cpu	2026-02-24 07:32:18.579+00
\N	133	cpu_usage_percent	0.3482456140122281	percent	cpu	2026-02-24 07:33:18.579+00
\N	133	cpu_usage_percent	0.6513157893756585	percent	cpu	2026-02-24 07:34:18.579+00
\N	133	cpu_usage_percent	0.7662280701231623	percent	cpu	2026-02-24 07:35:18.579+00
\N	133	cpu_usage_percent	0.7688596491342565	percent	cpu	2026-02-24 07:36:18.579+00
\N	133	cpu_usage_percent	0.7622807017086473	percent	cpu	2026-02-24 07:37:18.579+00
\N	133	cpu_usage_percent	0.5824561404031812	percent	cpu	2026-02-24 07:38:18.579+00
\N	133	cpu_usage_percent	0.5578947367898337	percent	cpu	2026-02-24 07:39:18.579+00
\N	133	cpu_usage_percent	0.4565789473749646	percent	cpu	2026-02-24 07:40:18.579+00
\N	133	cpu_usage_percent	0.44868421046423634	percent	cpu	2026-02-24 07:41:18.579+00
\N	248	cpu_usage_percent	2.3508771930069656	percent	cpu	2026-02-24 08:06:23.65+00
\N	248	cpu_usage_percent	2.3355263157894797	percent	cpu	2026-02-24 08:07:23.65+00
\N	248	cpu_usage_percent	2.2929824561517904	percent	cpu	2026-02-24 08:08:23.65+00
\N	248	cpu_usage_percent	2.2504385964732734	percent	cpu	2026-02-24 08:09:23.65+00
\N	248	cpu_usage_percent	2.1921052632183518	percent	cpu	2026-02-24 08:10:23.65+00
\N	248	cpu_usage_percent	2.274122807042062	percent	cpu	2026-02-24 08:11:23.65+00
\N	252	cpu_usage_percent	24.358333333317816	percent	cpu	2026-02-24 09:49:57.815+00
\N	252	cpu_usage_percent	24.20770817833835	percent	cpu	2026-02-24 09:50:57.815+00
\N	252	cpu_usage_percent	24.171929824505042	percent	cpu	2026-02-24 09:51:57.815+00
\N	252	cpu_usage_percent	24.223166071957323	percent	cpu	2026-02-24 09:52:57.815+00
\N	252	cpu_usage_percent	24.15043859650676	percent	cpu	2026-02-24 09:53:57.815+00
\N	252	cpu_usage_percent	24.182894736847018	percent	cpu	2026-02-24 09:54:57.815+00
\N	252	cpu_usage_percent	24.107456140387654	percent	cpu	2026-02-24 09:55:57.815+00
\N	236	cpu_usage_percent	1.9508771930020714	percent	cpu	2026-02-24 08:39:35.235+00
\N	236	cpu_usage_percent	1.757894736927085	percent	cpu	2026-02-24 08:40:35.235+00
\N	236	cpu_usage_percent	1.3789473683165028	percent	cpu	2026-02-24 08:41:35.235+00
\N	248	cpu_usage_percent	2.362719298250525	percent	cpu	2026-02-24 07:29:19.07+00
\N	248	cpu_usage_percent	2.4092105262618873	percent	cpu	2026-02-24 07:30:19.07+00
\N	248	cpu_usage_percent	2.4811403508494294	percent	cpu	2026-02-24 07:31:19.07+00
\N	248	cpu_usage_percent	2.3811403508788374	percent	cpu	2026-02-24 07:32:19.07+00
\N	248	cpu_usage_percent	2.3004385965402605	percent	cpu	2026-02-24 07:33:19.07+00
\N	248	cpu_usage_percent	2.347368420951341	percent	cpu	2026-02-24 07:34:19.07+00
\N	248	cpu_usage_percent	2.235964912300318	percent	cpu	2026-02-24 07:35:19.07+00
\N	248	cpu_usage_percent	2.18728070184099	percent	cpu	2026-02-24 07:36:19.07+00
\N	248	cpu_usage_percent	2.173245614026925	percent	cpu	2026-02-24 07:37:19.07+00
\N	248	cpu_usage_percent	2.0447368421101686	percent	cpu	2026-02-24 07:38:19.07+00
\N	248	cpu_usage_percent	2.101754385961655	percent	cpu	2026-02-24 07:39:19.07+00
\N	248	cpu_usage_percent	2.0828947368110704	percent	cpu	2026-02-24 07:40:19.07+00
\N	248	cpu_usage_percent	2.1434210525956416	percent	cpu	2026-02-24 07:41:19.07+00
\N	236	cpu_usage_percent	1.498245614041636	percent	cpu	2026-02-24 08:42:35.235+00
\N	236	cpu_usage_percent	1.5052631579078195	percent	cpu	2026-02-24 08:43:35.235+00
\N	236	cpu_usage_percent	1.498245614041636	percent	cpu	2026-02-24 08:44:35.235+00
\N	236	cpu_usage_percent	1.617543859603387	percent	cpu	2026-02-24 08:45:35.235+00
\N	236	cpu_usage_percent	1.7999999999608036	percent	cpu	2026-02-24 08:46:35.235+00
\N	236	cpu_usage_percent	1.8175438595445712	percent	cpu	2026-02-24 08:47:35.235+00
\N	257	cpu_usage_percent	4.44473684211917	percent	cpu	2026-02-24 07:59:24.154+00
\N	257	cpu_usage_percent	4.8429824561370935	percent	cpu	2026-02-24 08:00:24.154+00
\N	257	cpu_usage_percent	5.109649122807028	percent	cpu	2026-02-24 08:01:24.154+00
\N	257	cpu_usage_percent	5.02368421050754	percent	cpu	2026-02-24 08:02:24.154+00
\N	257	cpu_usage_percent	4.859649122819292	percent	cpu	2026-02-24 08:03:24.154+00
\N	133	cpu_usage_percent	0.45043859647162776	percent	cpu	2026-02-24 06:59:13.76+00
\N	133	cpu_usage_percent	0.44868421046423634	percent	cpu	2026-02-24 07:00:13.76+00
\N	133	cpu_usage_percent	0.4649122807262671	percent	cpu	2026-02-24 07:01:13.76+00
\N	133	cpu_usage_percent	0.4254385964994043	percent	cpu	2026-02-24 07:02:13.76+00
\N	133	cpu_usage_percent	0.45657894733412263	percent	cpu	2026-02-24 07:03:13.76+00
\N	133	cpu_usage_percent	0.5614035088454727	percent	cpu	2026-02-24 07:04:13.76+00
\N	133	cpu_usage_percent	0.6951754386618489	percent	cpu	2026-02-24 07:05:13.76+00
\N	133	cpu_usage_percent	0.6903508772027891	percent	cpu	2026-02-24 07:06:13.76+00
\N	133	cpu_usage_percent	0.5855263157731372	percent	cpu	2026-02-24 07:07:13.76+00
\N	133	cpu_usage_percent	0.6741228070632985	percent	cpu	2026-02-24 07:08:13.76+00
\N	133	cpu_usage_percent	0.45921052630436066	percent	cpu	2026-02-24 07:09:13.76+00
\N	133	cpu_usage_percent	0.42894736835080494	percent	cpu	2026-02-24 07:10:13.76+00
\N	133	cpu_usage_percent	0.42807017542881454	percent	cpu	2026-02-24 07:11:13.76+00
\N	257	cpu_usage_percent	4.496491228050587	percent	cpu	2026-02-24 08:04:24.154+00
\N	257	cpu_usage_percent	4.259649122811922	percent	cpu	2026-02-24 08:05:24.154+00
\N	257	cpu_usage_percent	4.234210526337861	percent	cpu	2026-02-24 08:06:24.154+00
\N	257	cpu_usage_percent	4.254385964932723	percent	cpu	2026-02-24 08:07:24.154+00
\N	257	cpu_usage_percent	4.286842105272967	percent	cpu	2026-02-24 08:08:24.154+00
\N	257	cpu_usage_percent	4.376315789485133	percent	cpu	2026-02-24 08:09:24.154+00
\N	257	cpu_usage_percent	4.304385964897577	percent	cpu	2026-02-24 08:10:24.154+00
\N	257	cpu_usage_percent	4.722807017530798	percent	cpu	2026-02-24 07:29:19.547+00
\N	257	cpu_usage_percent	4.861403508806248	percent	cpu	2026-02-24 08:11:24.154+00
\N	236	cpu_usage_percent	1.8385964913065038	percent	cpu	2026-02-24 08:48:35.235+00
\N	260	cpu_usage_percent	26.62094298243653	percent	cpu	2026-02-24 07:22:18.327+00
\N	260	cpu_usage_percent	26.13015350876499	percent	cpu	2026-02-24 07:23:18.327+00
\N	260	cpu_usage_percent	26.11776315790945	percent	cpu	2026-02-24 07:24:18.327+00
\N	260	cpu_usage_percent	26.040460526342756	percent	cpu	2026-02-24 07:25:18.327+00
\N	260	cpu_usage_percent	25.942543859638505	percent	cpu	2026-02-24 07:26:18.327+00
\N	260	cpu_usage_percent	25.66622807020363	percent	cpu	2026-02-24 07:27:18.327+00
\N	260	cpu_usage_percent	25.52993421053735	percent	cpu	2026-02-24 07:28:18.327+00
\N	260	cpu_usage_percent	25.52379385966465	percent	cpu	2026-02-24 07:29:18.327+00
\N	260	cpu_usage_percent	25.56315789478137	percent	cpu	2026-02-24 07:30:18.327+00
\N	260	cpu_usage_percent	25.6085526316198	percent	cpu	2026-02-24 07:31:18.327+00
\N	252	cpu_usage_percent	24.604824561392903	percent	cpu	2026-02-24 07:59:23.893+00
\N	252	cpu_usage_percent	24.82368421050508	percent	cpu	2026-02-24 08:00:23.893+00
\N	252	cpu_usage_percent	24.121052631556893	percent	cpu	2026-02-24 08:01:23.893+00
\N	252	cpu_usage_percent	22.753508771880007	percent	cpu	2026-02-24 08:02:23.893+00
\N	252	cpu_usage_percent	22.362280701748674	percent	cpu	2026-02-24 08:03:23.893+00
\N	252	cpu_usage_percent	21.83333333332517	percent	cpu	2026-02-24 08:04:23.893+00
\N	252	cpu_usage_percent	21.1815789473864	percent	cpu	2026-02-24 08:05:23.893+00
\N	252	cpu_usage_percent	22.13333333331863	percent	cpu	2026-02-24 08:06:23.893+00
\N	252	cpu_usage_percent	22.6986842104765	percent	cpu	2026-02-24 08:07:23.893+00
\N	252	cpu_usage_percent	22.65877192982947	percent	cpu	2026-02-24 08:08:23.893+00
\N	252	cpu_usage_percent	22.380701754356565	percent	cpu	2026-02-24 08:09:23.893+00
\N	252	cpu_usage_percent	22.392982456142803	percent	cpu	2026-02-24 08:10:23.893+00
\N	252	cpu_usage_percent	22.360526315741282	percent	cpu	2026-02-24 08:11:23.893+00
\N	133	cpu_usage_percent	0.661842105297481	percent	cpu	2026-02-24 09:19:45.62+00
\N	133	cpu_usage_percent	0.5385964912803587	percent	cpu	2026-02-24 09:20:45.62+00
\N	133	cpu_usage_percent	0.4515757783861858	percent	cpu	2026-02-24 09:21:45.62+00
\N	133	cpu_usage_percent	0.43473074057544636	percent	cpu	2026-02-24 09:22:45.62+00
\N	133	cpu_usage_percent	0.3578947368894916	percent	cpu	2026-02-24 09:23:45.62+00
\N	133	cpu_usage_percent	0.4276315789473699	percent	cpu	2026-02-24 09:24:45.62+00
\N	133	cpu_usage_percent	0.5557017543418681	percent	cpu	2026-02-24 09:25:45.62+00
\N	133	cpu_usage_percent	0.5690490644152675	percent	cpu	2026-02-24 09:26:45.62+00
\N	133	cpu_usage_percent	0.6507314368905384	percent	cpu	2026-02-24 09:27:45.62+00
\N	133	cpu_usage_percent	0.6543859648681689	percent	cpu	2026-02-24 09:28:45.62+00
\N	133	cpu_usage_percent	0.6535087719461785	percent	cpu	2026-02-24 09:29:45.62+00
\N	133	cpu_usage_percent	0.536573299226788	percent	cpu	2026-02-24 09:30:45.62+00
\N	133	cpu_usage_percent	0.5390350876800909	percent	cpu	2026-02-24 09:31:45.62+00
\N	260	cpu_usage_percent	26.60997807019669	percent	cpu	2026-02-24 07:59:24.421+00
\N	260	cpu_usage_percent	26.36589912283071	percent	cpu	2026-02-24 08:00:24.421+00
\N	260	cpu_usage_percent	26.308771929797615	percent	cpu	2026-02-24 08:01:24.421+00
\N	260	cpu_usage_percent	25.967324561380238	percent	cpu	2026-02-24 08:02:24.421+00
\N	260	cpu_usage_percent	25.889473684201548	percent	cpu	2026-02-24 08:03:24.421+00
\N	260	cpu_usage_percent	25.643969298219886	percent	cpu	2026-02-24 08:04:24.421+00
\N	260	cpu_usage_percent	25.620504385963287	percent	cpu	2026-02-24 08:05:24.421+00
\N	260	cpu_usage_percent	25.63925438595267	percent	cpu	2026-02-24 08:06:24.421+00
\N	260	cpu_usage_percent	25.618750000006955	percent	cpu	2026-02-24 08:07:24.421+00
\N	260	cpu_usage_percent	25.679385964881234	percent	cpu	2026-02-24 08:08:24.421+00
\N	260	cpu_usage_percent	25.603070175428385	percent	cpu	2026-02-24 08:09:24.421+00
\N	260	cpu_usage_percent	25.61535087723506	percent	cpu	2026-02-24 08:10:24.421+00
\N	260	cpu_usage_percent	25.620942982444717	percent	cpu	2026-02-24 08:11:24.421+00
\N	260	cpu_usage_percent	89.22412280694851	percent	cpu	2026-02-24 09:49:58.679+00
\N	260	cpu_usage_percent	89.92543859648306	percent	cpu	2026-02-24 09:50:58.679+00
\N	260	cpu_usage_percent	90.50690789474174	percent	cpu	2026-02-24 09:51:58.679+00
\N	260	cpu_usage_percent	91.2738116541647	percent	cpu	2026-02-24 09:52:58.679+00
\N	260	cpu_usage_percent	90.780831146252	percent	cpu	2026-02-24 09:53:58.679+00
\N	260	cpu_usage_percent	90.34539473686253	percent	cpu	2026-02-24 09:54:58.679+00
\N	260	cpu_usage_percent	25.52379385966465	percent	cpu	2026-02-24 07:29:19.79+00
\N	260	cpu_usage_percent	25.56315789478137	percent	cpu	2026-02-24 07:30:19.79+00
\N	260	cpu_usage_percent	25.6085526316198	percent	cpu	2026-02-24 07:31:19.79+00
\N	260	cpu_usage_percent	25.599232456124028	percent	cpu	2026-02-24 07:32:19.79+00
\N	260	cpu_usage_percent	25.65734649119949	percent	cpu	2026-02-24 07:33:19.79+00
\N	260	cpu_usage_percent	25.60745614035497	percent	cpu	2026-02-24 07:34:19.79+00
\N	260	cpu_usage_percent	25.66041666664094	percent	cpu	2026-02-24 07:35:19.79+00
\N	260	cpu_usage_percent	25.69111842108613	percent	cpu	2026-02-24 07:36:19.79+00
\N	260	cpu_usage_percent	25.831359649146506	percent	cpu	2026-02-24 07:37:19.79+00
\N	260	cpu_usage_percent	26.159649122814784	percent	cpu	2026-02-24 07:38:19.79+00
\N	260	cpu_usage_percent	26.306140350898858	percent	cpu	2026-02-24 07:39:19.79+00
\N	260	cpu_usage_percent	26.78585526318976	percent	cpu	2026-02-24 07:40:19.79+00
\N	260	cpu_usage_percent	26.866228070157064	percent	cpu	2026-02-24 07:41:19.79+00
\N	260	cpu_usage_percent	89.76425438597512	percent	cpu	2026-02-24 09:55:58.679+00
\N	260	cpu_usage_percent	88.10888157895023	percent	cpu	2026-02-24 09:56:58.679+00
\N	260	cpu_usage_percent	87.73530701752303	percent	cpu	2026-02-24 09:57:58.679+00
\N	260	cpu_usage_percent	88.23749999996691	percent	cpu	2026-02-24 09:58:58.679+00
\N	260	cpu_usage_percent	25.603070175428385	percent	cpu	2026-02-24 08:09:25.932+00
\N	260	cpu_usage_percent	25.61535087723506	percent	cpu	2026-02-24 08:10:25.932+00
\N	260	cpu_usage_percent	25.620942982444717	percent	cpu	2026-02-24 08:11:25.932+00
\N	260	cpu_usage_percent	25.741995614024077	percent	cpu	2026-02-24 08:12:25.932+00
\N	260	cpu_usage_percent	25.778179824548346	percent	cpu	2026-02-24 08:13:25.932+00
\N	260	cpu_usage_percent	25.807456140398273	percent	cpu	2026-02-24 08:14:25.932+00
\N	236	cpu_usage_percent	1.8315789472769382	percent	cpu	2026-02-24 08:49:35.235+00
\N	236	cpu_usage_percent	1.6982456141462023	percent	cpu	2026-02-24 07:29:18.842+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	cpu	2026-02-24 07:30:18.842+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	cpu	2026-02-24 07:31:18.842+00
\N	236	cpu_usage_percent	1.5052631579078195	percent	cpu	2026-02-24 07:32:18.842+00
\N	236	cpu_usage_percent	1.3473684211637362	percent	cpu	2026-02-24 07:33:18.842+00
\N	236	cpu_usage_percent	1.6105263157372036	percent	cpu	2026-02-24 07:34:18.842+00
\N	236	cpu_usage_percent	1.7859649122284367	percent	cpu	2026-02-24 07:35:18.842+00
\N	236	cpu_usage_percent	1.796491228109403	percent	cpu	2026-02-24 07:36:18.842+00
\N	236	cpu_usage_percent	1.7789473685256354	percent	cpu	2026-02-24 07:37:18.842+00
\N	236	cpu_usage_percent	1.740350877179921	percent	cpu	2026-02-24 07:38:18.842+00
\N	236	cpu_usage_percent	1.536842105223954	percent	cpu	2026-02-24 06:59:14.024+00
\N	236	cpu_usage_percent	1.4842105263092549	percent	cpu	2026-02-24 07:00:14.024+00
\N	236	cpu_usage_percent	1.5368421053873504	percent	cpu	2026-02-24 07:01:14.024+00
\N	236	cpu_usage_percent	1.5052631579078195	percent	cpu	2026-02-24 07:02:14.024+00
\N	236	cpu_usage_percent	1.5228070176549693	percent	cpu	2026-02-24 07:03:14.024+00
\N	236	cpu_usage_percent	1.8385964913065038	percent	cpu	2026-02-24 07:04:14.024+00
\N	236	cpu_usage_percent	1.9017543861021693	percent	cpu	2026-02-24 07:05:14.024+00
\N	236	cpu_usage_percent	2.589473684171324	percent	cpu	2026-02-24 07:06:14.024+00
\N	236	cpu_usage_percent	2.6385964912346083	percent	cpu	2026-02-24 07:07:14.024+00
\N	236	cpu_usage_percent	2.649122807115589	percent	cpu	2026-02-24 07:08:14.024+00
\N	236	cpu_usage_percent	2.3543859650626047	percent	cpu	2026-02-24 07:09:14.024+00
\N	236	cpu_usage_percent	2.291228070103557	percent	cpu	2026-02-24 07:10:14.024+00
\N	236	cpu_usage_percent	1.6421052632167203	percent	cpu	2026-02-24 07:11:14.024+00
\N	236	cpu_usage_percent	1.6561403509491015	percent	cpu	2026-02-24 07:39:18.842+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	cpu	2026-02-24 07:40:18.842+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	cpu	2026-02-24 07:41:18.842+00
\N	236	cpu_usage_percent	1.7147548920391102	percent	cpu	2026-02-24 08:50:35.235+00
\N	236	cpu_usage_percent	1.5192982456401865	percent	cpu	2026-02-24 08:51:35.235+00
\N	260	cpu_usage_percent	91.07796052633172	percent	cpu	2026-02-24 09:21:45.148+00
\N	252	cpu_usage_percent	24.23377192981559	percent	cpu	2026-02-24 09:56:57.815+00
\N	252	cpu_usage_percent	24.332456140321483	percent	cpu	2026-02-24 09:57:57.815+00
\N	252	cpu_usage_percent	24.296410914970366	percent	cpu	2026-02-24 09:58:57.815+00
\N	252	cpu_usage_percent	24.2991228070388	percent	cpu	2026-02-24 09:59:57.815+00
\N	252	cpu_usage_percent	24.252192982423466	percent	cpu	2026-02-24 10:00:57.815+00
\N	252	cpu_usage_percent	22.704385964918828	percent	cpu	2026-02-24 10:01:57.815+00
\N	248	cpu_usage_percent	2.3504385965255494	percent	cpu	2026-02-24 06:59:14.302+00
\N	248	cpu_usage_percent	2.5706140350615954	percent	cpu	2026-02-24 07:00:14.302+00
\N	248	cpu_usage_percent	2.588596491085923	percent	cpu	2026-02-24 07:01:14.302+00
\N	248	cpu_usage_percent	2.6184210525989045	percent	cpu	2026-02-24 07:02:14.302+00
\N	248	cpu_usage_percent	2.649999999996737	percent	cpu	2026-02-24 07:03:14.302+00
\N	248	cpu_usage_percent	2.676315789454094	percent	cpu	2026-02-24 07:04:14.302+00
\N	248	cpu_usage_percent	2.5118421052844155	percent	cpu	2026-02-24 07:05:14.302+00
\N	248	cpu_usage_percent	2.5114035088438413	percent	cpu	2026-02-24 07:06:14.302+00
\N	248	cpu_usage_percent	2.4894736841598757	percent	cpu	2026-02-24 07:07:14.302+00
\N	248	cpu_usage_percent	2.461842105258256	percent	cpu	2026-02-24 07:08:14.302+00
\N	248	cpu_usage_percent	2.3241228069865087	percent	cpu	2026-02-24 07:09:14.302+00
\N	248	cpu_usage_percent	2.2929824560701064	percent	cpu	2026-02-24 07:10:14.302+00
\N	248	cpu_usage_percent	2.229385964997249	percent	cpu	2026-02-24 07:11:14.302+00
\N	252	cpu_usage_percent	24.850438596464272	percent	cpu	2026-02-24 07:29:19.306+00
\N	252	cpu_usage_percent	24.657017543867013	percent	cpu	2026-02-24 07:30:19.306+00
\N	252	cpu_usage_percent	24.767105263135022	percent	cpu	2026-02-24 07:31:19.306+00
\N	252	cpu_usage_percent	24.540789473695654	percent	cpu	2026-02-24 07:32:19.306+00
\N	252	cpu_usage_percent	24.28903508765967	percent	cpu	2026-02-24 07:33:19.306+00
\N	252	cpu_usage_percent	24.59561403509916	percent	cpu	2026-02-24 07:34:19.306+00
\N	252	cpu_usage_percent	24.58421052629619	percent	cpu	2026-02-24 07:35:19.306+00
\N	252	cpu_usage_percent	24.412719298239907	percent	cpu	2026-02-24 07:36:19.306+00
\N	252	cpu_usage_percent	24.41578947367114	percent	cpu	2026-02-24 07:37:19.306+00
\N	252	cpu_usage_percent	24.384649122795594	percent	cpu	2026-02-24 07:38:19.306+00
\N	252	cpu_usage_percent	24.275000000009	percent	cpu	2026-02-24 07:39:19.306+00
\N	252	cpu_usage_percent	24.24385964913344	percent	cpu	2026-02-24 07:40:19.306+00
\N	252	cpu_usage_percent	24.277192982456967	percent	cpu	2026-02-24 07:41:19.306+00
\N	252	cpu_usage_percent	24.932894736851097	percent	cpu	2026-02-24 06:59:14.553+00
\N	252	cpu_usage_percent	25.007017543886604	percent	cpu	2026-02-24 07:00:14.553+00
\N	252	cpu_usage_percent	24.956578947358636	percent	cpu	2026-02-24 07:01:14.553+00
\N	252	cpu_usage_percent	24.885087719313773	percent	cpu	2026-02-24 07:02:14.553+00
\N	252	cpu_usage_percent	25.41096491228562	percent	cpu	2026-02-24 07:03:14.553+00
\N	252	cpu_usage_percent	25.738596491201122	percent	cpu	2026-02-24 07:04:14.553+00
\N	252	cpu_usage_percent	25.601754385953484	percent	cpu	2026-02-24 07:05:14.553+00
\N	252	cpu_usage_percent	26.065350877153776	percent	cpu	2026-02-24 07:06:14.553+00
\N	252	cpu_usage_percent	26.04078947366297	percent	cpu	2026-02-24 07:07:14.553+00
\N	252	cpu_usage_percent	25.802631578939213	percent	cpu	2026-02-24 07:08:14.553+00
\N	252	cpu_usage_percent	25.359210526313348	percent	cpu	2026-02-24 07:09:14.553+00
\N	252	cpu_usage_percent	25.353508771952704	percent	cpu	2026-02-24 07:10:14.553+00
\N	252	cpu_usage_percent	24.900438596490417	percent	cpu	2026-02-24 07:11:14.553+00
\N	260	cpu_usage_percent	25.798903508785827	percent	cpu	2026-02-24 08:15:25.932+00
\N	260	cpu_usage_percent	25.991337719330517	percent	cpu	2026-02-24 08:16:25.932+00
\N	260	cpu_usage_percent	26.157785087707467	percent	cpu	2026-02-24 08:17:25.932+00
\N	260	cpu_usage_percent	26.013157894720507	percent	cpu	2026-02-24 08:18:25.932+00
\N	260	cpu_usage_percent	25.940021929839688	percent	cpu	2026-02-24 08:19:25.932+00
\N	260	cpu_usage_percent	25.885197368374904	percent	cpu	2026-02-24 08:20:25.932+00
\N	260	cpu_usage_percent	25.305811403535742	percent	cpu	2026-02-24 08:21:25.932+00
\N	252	cpu_usage_percent	23.610964912304397	percent	cpu	2026-02-24 08:39:35.727+00
\N	252	cpu_usage_percent	23.747368421070618	percent	cpu	2026-02-24 08:40:35.727+00
\N	252	cpu_usage_percent	23.533771929858062	percent	cpu	2026-02-24 08:41:35.727+00
\N	248	cpu_usage_percent	4.4820175438367755	percent	cpu	2026-02-24 08:39:35.484+00
\N	248	cpu_usage_percent	4.410087719290075	percent	cpu	2026-02-24 08:40:35.484+00
\N	248	cpu_usage_percent	3.9337719297608515	percent	cpu	2026-02-24 08:41:35.484+00
\N	248	cpu_usage_percent	2.4565789473994784	percent	cpu	2026-02-24 08:42:35.484+00
\N	257	cpu_usage_percent	4.795614035101622	percent	cpu	2026-02-24 06:59:14.801+00
\N	257	cpu_usage_percent	5.1798245614280205	percent	cpu	2026-02-24 07:00:14.801+00
\N	257	cpu_usage_percent	5.624561403498163	percent	cpu	2026-02-24 07:01:14.801+00
\N	257	cpu_usage_percent	5.8464912280416	percent	cpu	2026-02-24 07:02:14.801+00
\N	257	cpu_usage_percent	5.421052631562617	percent	cpu	2026-02-24 07:03:14.801+00
\N	257	cpu_usage_percent	5.300000000013895	percent	cpu	2026-02-24 07:04:14.801+00
\N	257	cpu_usage_percent	5.207017543868659	percent	cpu	2026-02-24 07:05:14.801+00
\N	257	cpu_usage_percent	4.848245614016307	percent	cpu	2026-02-24 07:06:14.801+00
\N	257	cpu_usage_percent	4.4561403508608635	percent	cpu	2026-02-24 07:07:14.801+00
\N	257	cpu_usage_percent	4.693859649123638	percent	cpu	2026-02-24 07:08:14.801+00
\N	257	cpu_usage_percent	4.580701754383526	percent	cpu	2026-02-24 07:09:14.801+00
\N	257	cpu_usage_percent	4.863157894731955	percent	cpu	2026-02-24 07:10:14.801+00
\N	257	cpu_usage_percent	5.199122806998773	percent	cpu	2026-02-24 07:11:14.801+00
\N	248	cpu_usage_percent	2.4364035087637745	percent	cpu	2026-02-24 08:43:35.484+00
\N	248	cpu_usage_percent	2.6478070175896278	percent	cpu	2026-02-24 08:44:35.484+00
\N	248	cpu_usage_percent	2.7486842105230522	percent	cpu	2026-02-24 08:45:35.484+00
\N	248	cpu_usage_percent	2.635526315742098	percent	cpu	2026-02-24 08:46:35.484+00
\N	248	cpu_usage_percent	2.5872807017642003	percent	cpu	2026-02-24 08:47:35.484+00
\N	248	cpu_usage_percent	2.4191058308624207	percent	cpu	2026-02-24 08:48:35.484+00
\N	248	cpu_usage_percent	2.3811403508788374	percent	cpu	2026-02-24 08:49:35.484+00
\N	248	cpu_usage_percent	2.309210526372979	percent	cpu	2026-02-24 08:50:35.484+00
\N	248	cpu_usage_percent	2.3236842105459345	percent	cpu	2026-02-24 08:51:35.484+00
\N	133	cpu_usage_percent	0.46973684210364297	percent	cpu	2026-02-24 08:19:30.909+00
\N	133	cpu_usage_percent	0.38289473682087305	percent	cpu	2026-02-24 08:20:30.909+00
\N	260	cpu_usage_percent	25.792982456123198	percent	cpu	2026-02-24 06:59:15.052+00
\N	260	cpu_usage_percent	25.748793859629117	percent	cpu	2026-02-24 07:00:15.052+00
\N	260	cpu_usage_percent	25.818859649139966	percent	cpu	2026-02-24 07:01:15.052+00
\N	260	cpu_usage_percent	25.806688596453654	percent	cpu	2026-02-24 07:02:15.052+00
\N	260	cpu_usage_percent	25.68256578949412	percent	cpu	2026-02-24 07:03:15.052+00
\N	260	cpu_usage_percent	25.739144736864176	percent	cpu	2026-02-24 07:04:15.052+00
\N	260	cpu_usage_percent	25.636074561390856	percent	cpu	2026-02-24 07:05:15.052+00
\N	260	cpu_usage_percent	25.606250000020836	percent	cpu	2026-02-24 07:06:15.052+00
\N	260	cpu_usage_percent	25.54002192981436	percent	cpu	2026-02-24 07:07:15.052+00
\N	260	cpu_usage_percent	25.59671052631498	percent	cpu	2026-02-24 07:08:15.052+00
\N	260	cpu_usage_percent	25.579276315780092	percent	cpu	2026-02-24 07:09:15.052+00
\N	260	cpu_usage_percent	25.597478070177885	percent	cpu	2026-02-24 07:10:15.052+00
\N	260	cpu_usage_percent	25.614583333280237	percent	cpu	2026-02-24 07:11:15.052+00
\N	133	cpu_usage_percent	0.4131578947335868	percent	cpu	2026-02-24 08:21:30.909+00
\N	133	cpu_usage_percent	0.42017543864061224	percent	cpu	2026-02-24 08:22:30.909+00
\N	133	cpu_usage_percent	0.4175438596295322	percent	cpu	2026-02-24 08:23:30.909+00
\N	133	cpu_usage_percent	0.41184210528930976	percent	cpu	2026-02-24 08:24:30.909+00
\N	133	cpu_usage_percent	0.5223684210591699	percent	cpu	2026-02-24 08:25:30.909+00
\N	133	cpu_usage_percent	0.7521929825133356	percent	cpu	2026-02-24 08:26:30.909+00
\N	133	cpu_usage_percent	0.7570175438498552	percent	cpu	2026-02-24 08:27:30.909+00
\N	133	cpu_usage_percent	0.7596491227792512	percent	cpu	2026-02-24 08:28:30.909+00
\N	133	cpu_usage_percent	0.7188596491489676	percent	cpu	2026-02-24 08:29:30.909+00
\N	133	cpu_usage_percent	0.6315789473439253	percent	cpu	2026-02-24 08:30:30.909+00
\N	133	cpu_usage_percent	0.3131578947221527	percent	cpu	2026-02-24 08:31:30.909+00
\N	236	cpu_usage_percent	1.8666666666078555	percent	cpu	2026-02-24 09:19:46.254+00
\N	236	cpu_usage_percent	1.7073324771652523	percent	cpu	2026-02-24 09:20:46.254+00
\N	236	cpu_usage_percent	1.5533496844414714	percent	cpu	2026-02-24 09:21:46.254+00
\N	236	cpu_usage_percent	1.5052631579078195	percent	cpu	2026-02-24 09:22:46.254+00
\N	236	cpu_usage_percent	1.3543859648665375	percent	cpu	2026-02-24 09:23:46.254+00
\N	236	cpu_usage_percent	1.522807017491587	percent	cpu	2026-02-24 09:24:46.254+00
\N	236	cpu_usage_percent	1.7298245614623369	percent	cpu	2026-02-24 09:25:46.254+00
\N	257	cpu_usage_percent	4.6456140350844635	percent	cpu	2026-02-24 08:39:35.974+00
\N	133	cpu_usage_percent	0.5578947367898337	percent	cpu	2026-02-24 07:39:20.133+00
\N	133	cpu_usage_percent	0.4565789473749646	percent	cpu	2026-02-24 07:40:20.133+00
\N	133	cpu_usage_percent	0.44868421046423634	percent	cpu	2026-02-24 07:41:20.133+00
\N	133	cpu_usage_percent	0.4561403508118502	percent	cpu	2026-02-24 07:42:20.133+00
\N	133	cpu_usage_percent	0.4635964912411481	percent	cpu	2026-02-24 07:43:20.133+00
\N	133	cpu_usage_percent	0.5473684211130916	percent	cpu	2026-02-24 07:44:20.133+00
\N	133	cpu_usage_percent	0.6640350877046046	percent	cpu	2026-02-24 07:45:20.133+00
\N	133	cpu_usage_percent	0.6732456140187537	percent	cpu	2026-02-24 07:46:20.133+00
\N	133	cpu_usage_percent	0.6692982455633825	percent	cpu	2026-02-24 07:47:20.133+00
\N	133	cpu_usage_percent	0.6631578947826	percent	cpu	2026-02-24 07:48:20.133+00
\N	133	cpu_usage_percent	0.5394736842432053	percent	cpu	2026-02-24 07:49:20.133+00
\N	133	cpu_usage_percent	0.43771929818353783	percent	cpu	2026-02-24 07:50:20.133+00
\N	133	cpu_usage_percent	0.44122807011662246	percent	cpu	2026-02-24 07:51:20.133+00
\N	257	cpu_usage_percent	4.969298245605884	percent	cpu	2026-02-24 08:40:35.974+00
\N	257	cpu_usage_percent	4.897368421059184	percent	cpu	2026-02-24 08:41:35.974+00
\N	257	cpu_usage_percent	5.249122807004483	percent	cpu	2026-02-24 08:42:35.974+00
\N	257	cpu_usage_percent	5.149999999955895	percent	cpu	2026-02-24 08:43:35.974+00
\N	257	cpu_usage_percent	4.794736842097919	percent	cpu	2026-02-24 08:44:35.974+00
\N	257	cpu_usage_percent	4.705263157885767	percent	cpu	2026-02-24 08:45:35.974+00
\N	248	cpu_usage_percent	2.421929824590819	percent	cpu	2026-02-24 08:19:31.398+00
\N	248	cpu_usage_percent	2.4013157895553974	percent	cpu	2026-02-24 08:20:31.398+00
\N	236	cpu_usage_percent	1.768421052644669	percent	cpu	2026-02-24 09:26:46.254+00
\N	257	cpu_usage_percent	4.845614035086911	percent	cpu	2026-02-24 07:30:19.547+00
\N	257	cpu_usage_percent	5.252631578937567	percent	cpu	2026-02-24 07:31:19.547+00
\N	257	cpu_usage_percent	5.406140350887824	percent	cpu	2026-02-24 07:32:19.547+00
\N	257	cpu_usage_percent	5.013157894728678	percent	cpu	2026-02-24 07:33:19.547+00
\N	257	cpu_usage_percent	5.170175438632455	percent	cpu	2026-02-24 07:34:19.547+00
\N	257	cpu_usage_percent	5.055263157905358	percent	cpu	2026-02-24 07:35:19.547+00
\N	257	cpu_usage_percent	4.68421052634848	percent	cpu	2026-02-24 07:36:19.547+00
\N	257	cpu_usage_percent	4.594736842095472	percent	cpu	2026-02-24 07:37:19.547+00
\N	257	cpu_usage_percent	4.378947368414529	percent	cpu	2026-02-24 07:38:19.547+00
\N	257	cpu_usage_percent	4.7789473684194235	percent	cpu	2026-02-24 07:39:19.547+00
\N	257	cpu_usage_percent	4.980701754408841	percent	cpu	2026-02-24 07:40:19.547+00
\N	257	cpu_usage_percent	5.266666666669948	percent	cpu	2026-02-24 07:41:19.547+00
\N	133	cpu_usage_percent	0.48596491232481753	percent	cpu	2026-02-24 08:09:24.716+00
\N	133	cpu_usage_percent	0.3710526316590119	percent	cpu	2026-02-24 08:10:24.716+00
\N	133	cpu_usage_percent	0.3969298245532542	percent	cpu	2026-02-24 08:11:24.716+00
\N	133	cpu_usage_percent	0.3964912280718096	percent	cpu	2026-02-24 08:12:24.716+00
\N	133	cpu_usage_percent	0.40175438593060164	percent	cpu	2026-02-24 08:13:24.716+00
\N	133	cpu_usage_percent	0.4048245614231263	percent	cpu	2026-02-24 08:14:24.716+00
\N	133	cpu_usage_percent	0.42850877195107273	percent	cpu	2026-02-24 08:15:24.716+00
\N	133	cpu_usage_percent	0.5600877193194975	percent	cpu	2026-02-24 08:16:24.716+00
\N	133	cpu_usage_percent	0.552192982408755	percent	cpu	2026-02-24 08:17:24.716+00
\N	133	cpu_usage_percent	0.551754385968195	percent	cpu	2026-02-24 08:18:24.716+00
\N	133	cpu_usage_percent	0.46973684210364297	percent	cpu	2026-02-24 08:19:24.716+00
\N	133	cpu_usage_percent	0.38289473682087305	percent	cpu	2026-02-24 08:20:24.716+00
\N	133	cpu_usage_percent	0.4131578947335868	percent	cpu	2026-02-24 08:21:24.716+00
\N	252	cpu_usage_percent	23.5565789473619	percent	cpu	2026-02-24 08:42:35.727+00
\N	252	cpu_usage_percent	23.454385964882064	percent	cpu	2026-02-24 08:43:35.727+00
\N	252	cpu_usage_percent	23.392105263171786	percent	cpu	2026-02-24 08:44:35.727+00
\N	252	cpu_usage_percent	23.603947368417792	percent	cpu	2026-02-24 08:45:35.727+00
\N	252	cpu_usage_percent	23.829824561416586	percent	cpu	2026-02-24 08:46:35.727+00
\N	252	cpu_usage_percent	24.099561403476926	percent	cpu	2026-02-24 08:47:35.727+00
\N	252	cpu_usage_percent	24.182017543863736	percent	cpu	2026-02-24 08:48:35.727+00
\N	252	cpu_usage_percent	24.08815789475564	percent	cpu	2026-02-24 08:49:35.727+00
\N	252	cpu_usage_percent	23.79298245615996	percent	cpu	2026-02-24 08:50:35.727+00
\N	252	cpu_usage_percent	23.60043859650513	percent	cpu	2026-02-24 08:51:35.727+00
\N	248	cpu_usage_percent	2.2504385964732734	percent	cpu	2026-02-24 08:09:25.219+00
\N	248	cpu_usage_percent	2.1921052632183518	percent	cpu	2026-02-24 08:10:25.219+00
\N	248	cpu_usage_percent	2.274122807042062	percent	cpu	2026-02-24 08:11:25.219+00
\N	248	cpu_usage_percent	2.272807017516101	percent	cpu	2026-02-24 08:12:25.219+00
\N	248	cpu_usage_percent	2.3491228069995884	percent	cpu	2026-02-24 08:13:25.219+00
\N	248	cpu_usage_percent	2.3026315788656717	percent	cpu	2026-02-24 08:14:25.219+00
\N	248	cpu_usage_percent	2.4618421052582704	percent	cpu	2026-02-24 08:15:25.219+00
\N	248	cpu_usage_percent	2.6276315788722258	percent	cpu	2026-02-24 08:16:25.219+00
\N	248	cpu_usage_percent	2.624122807020825	percent	cpu	2026-02-24 08:17:25.219+00
\N	248	cpu_usage_percent	2.5811403509017055	percent	cpu	2026-02-24 08:18:25.219+00
\N	248	cpu_usage_percent	2.551315789470422	percent	cpu	2026-02-24 08:19:25.219+00
\N	248	cpu_usage_percent	2.4754385963866667	percent	cpu	2026-02-24 08:20:25.219+00
\N	248	cpu_usage_percent	2.4570175437992106	percent	cpu	2026-02-24 08:21:25.219+00
\N	236	cpu_usage_percent	1.6561403509491015	percent	cpu	2026-02-24 07:39:20.399+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	cpu	2026-02-24 07:40:20.399+00
\N	236	cpu_usage_percent	1.4912280701754526	percent	cpu	2026-02-24 07:41:20.399+00
\N	236	cpu_usage_percent	1.494736842026839	percent	cpu	2026-02-24 07:42:20.399+00
\N	236	cpu_usage_percent	1.494736842026839	percent	cpu	2026-02-24 07:43:20.399+00
\N	236	cpu_usage_percent	1.589473684138639	percent	cpu	2026-02-24 07:44:20.399+00
\N	236	cpu_usage_percent	1.726315789447554	percent	cpu	2026-02-24 07:45:20.399+00
\N	236	cpu_usage_percent	1.7614035087784856	percent	cpu	2026-02-24 07:46:20.399+00
\N	236	cpu_usage_percent	1.782456140377036	percent	cpu	2026-02-24 07:47:20.399+00
\N	236	cpu_usage_percent	1.771929824659452	percent	cpu	2026-02-24 07:48:20.399+00
\N	236	cpu_usage_percent	1.6210526314547735	percent	cpu	2026-02-24 07:49:20.399+00
\N	236	cpu_usage_percent	1.5192982456401865	percent	cpu	2026-02-24 07:50:20.399+00
\N	236	cpu_usage_percent	1.4807017544578684	percent	cpu	2026-02-24 07:51:20.399+00
\N	260	cpu_usage_percent	76.2197582413653	percent	cpu	2026-02-24 08:39:36.199+00
\N	260	cpu_usage_percent	72.34846491225701	percent	cpu	2026-02-24 08:40:36.199+00
\N	260	cpu_usage_percent	72.329276315776	percent	cpu	2026-02-24 08:41:36.199+00
\N	260	cpu_usage_percent	72.36271929821989	percent	cpu	2026-02-24 08:42:36.199+00
\N	260	cpu_usage_percent	72.4336622806936	percent	cpu	2026-02-24 08:43:36.199+00
\N	260	cpu_usage_percent	72.43643614313713	percent	cpu	2026-02-24 08:44:36.199+00
\N	260	cpu_usage_percent	76.26710526317382	percent	cpu	2026-02-24 08:45:36.199+00
\N	260	cpu_usage_percent	76.34473684210158	percent	cpu	2026-02-24 08:46:36.199+00
\N	257	cpu_usage_percent	4.376315789485133	percent	cpu	2026-02-24 08:09:25.683+00
\N	257	cpu_usage_percent	4.304385964897577	percent	cpu	2026-02-24 08:10:25.683+00
\N	257	cpu_usage_percent	4.861403508806248	percent	cpu	2026-02-24 08:11:25.683+00
\N	257	cpu_usage_percent	5.095614035115517	percent	cpu	2026-02-24 08:12:25.683+00
\N	257	cpu_usage_percent	4.983333333338251	percent	cpu	2026-02-24 08:13:25.683+00
\N	257	cpu_usage_percent	4.637719298255433	percent	cpu	2026-02-24 08:14:25.683+00
\N	257	cpu_usage_percent	4.302631578931042	percent	cpu	2026-02-24 08:15:25.683+00
\N	257	cpu_usage_percent	4.24385964911302	percent	cpu	2026-02-24 08:16:25.683+00
\N	257	cpu_usage_percent	4.157894736854374	percent	cpu	2026-02-24 08:17:25.683+00
\N	248	cpu_usage_percent	2.437280701726621	percent	cpu	2026-02-24 08:21:31.398+00
\N	248	cpu_usage_percent	2.494736842141222	percent	cpu	2026-02-24 08:22:31.398+00
\N	248	cpu_usage_percent	2.489912280641306	percent	cpu	2026-02-24 08:23:31.398+00
\N	248	cpu_usage_percent	2.6899122807458724	percent	cpu	2026-02-24 08:24:31.398+00
\N	248	cpu_usage_percent	2.708771929855615	percent	cpu	2026-02-24 08:25:31.398+00
\N	248	cpu_usage_percent	2.828947368421069	percent	cpu	2026-02-24 08:26:31.398+00
\N	248	cpu_usage_percent	2.805701754374539	percent	cpu	2026-02-24 08:27:31.398+00
\N	248	cpu_usage_percent	2.946929824579385	percent	cpu	2026-02-24 08:28:31.398+00
\N	248	cpu_usage_percent	2.96096491227091	percent	cpu	2026-02-24 08:29:31.398+00
\N	248	cpu_usage_percent	2.9381578947058102	percent	cpu	2026-02-24 08:30:31.398+00
\N	248	cpu_usage_percent	2.7359649122349623	percent	cpu	2026-02-24 08:31:31.398+00
\N	236	cpu_usage_percent	1.9473684211506708	percent	cpu	2026-02-24 09:27:46.254+00
\N	236	cpu_usage_percent	1.9649122805710562	percent	cpu	2026-02-24 09:28:46.254+00
\N	236	cpu_usage_percent	1.9308568681733078	percent	cpu	2026-02-24 09:29:46.254+00
\N	236	cpu_usage_percent	1.754385964912288	percent	cpu	2026-02-24 09:30:46.254+00
\N	236	cpu_usage_percent	1.5964912280048225	percent	cpu	2026-02-24 09:31:46.254+00
\N	260	cpu_usage_percent	88.2858003747663	percent	cpu	2026-02-24 09:59:58.679+00
\N	260	cpu_usage_percent	88.37883771930234	percent	cpu	2026-02-24 10:00:58.679+00
\N	260	cpu_usage_percent	88.18223684210241	percent	cpu	2026-02-24 10:01:58.679+00
\N	236	cpu_usage_percent	2.1368421052108744	percent	cpu	2026-02-24 08:09:24.981+00
\N	236	cpu_usage_percent	1.470175438576888	percent	cpu	2026-02-24 08:10:24.981+00
\N	236	cpu_usage_percent	1.4105263157960195	percent	cpu	2026-02-24 08:11:24.981+00
\N	236	cpu_usage_percent	1.4350877192459706	percent	cpu	2026-02-24 08:12:24.981+00
\N	236	cpu_usage_percent	1.4456140349635547	percent	cpu	2026-02-24 08:13:24.981+00
\N	252	cpu_usage_percent	24.275000000009	percent	cpu	2026-02-24 07:39:20.882+00
\N	252	cpu_usage_percent	24.24385964913344	percent	cpu	2026-02-24 07:40:20.882+00
\N	252	cpu_usage_percent	24.277192982456967	percent	cpu	2026-02-24 07:41:20.882+00
\N	252	cpu_usage_percent	24.312719298248894	percent	cpu	2026-02-24 07:42:20.882+00
\N	252	cpu_usage_percent	24.329824561412508	percent	cpu	2026-02-24 07:43:20.882+00
\N	252	cpu_usage_percent	24.499999999963237	percent	cpu	2026-02-24 07:44:20.882+00
\N	252	cpu_usage_percent	24.464473684232587	percent	cpu	2026-02-24 07:45:20.882+00
\N	252	cpu_usage_percent	24.451754385944497	percent	cpu	2026-02-24 07:46:20.882+00
\N	252	cpu_usage_percent	24.355701754347578	percent	cpu	2026-02-24 07:47:20.882+00
\N	252	cpu_usage_percent	24.578508771935546	percent	cpu	2026-02-24 07:48:20.882+00
\N	252	cpu_usage_percent	24.25307017542717	percent	cpu	2026-02-24 07:49:20.882+00
\N	252	cpu_usage_percent	24.317982456148528	percent	cpu	2026-02-24 07:50:20.882+00
\N	252	cpu_usage_percent	24.461842105241928	percent	cpu	2026-02-24 07:51:20.882+00
\N	236	cpu_usage_percent	1.4385964912607534	percent	cpu	2026-02-24 08:14:24.981+00
\N	236	cpu_usage_percent	1.4350877194093528	percent	cpu	2026-02-24 08:15:24.981+00
\N	236	cpu_usage_percent	1.7087719298637865	percent	cpu	2026-02-24 08:16:24.981+00
\N	236	cpu_usage_percent	1.71578947372997	percent	cpu	2026-02-24 08:17:24.981+00
\N	236	cpu_usage_percent	1.712280701715187	percent	cpu	2026-02-24 08:18:24.981+00
\N	236	cpu_usage_percent	1.5789473684210549	percent	cpu	2026-02-24 08:19:24.981+00
\N	236	cpu_usage_percent	1.2736842104871187	percent	cpu	2026-02-24 08:20:24.981+00
\N	236	cpu_usage_percent	1.4070175439446189	percent	cpu	2026-02-24 08:21:24.981+00
\N	260	cpu_usage_percent	26.306140350898858	percent	cpu	2026-02-24 07:39:21.379+00
\N	260	cpu_usage_percent	26.78585526318976	percent	cpu	2026-02-24 07:40:21.379+00
\N	260	cpu_usage_percent	26.866228070157064	percent	cpu	2026-02-24 07:41:21.379+00
\N	260	cpu_usage_percent	26.79133771928926	percent	cpu	2026-02-24 07:42:21.379+00
\N	260	cpu_usage_percent	26.32258771926884	percent	cpu	2026-02-24 07:43:21.379+00
\N	260	cpu_usage_percent	26.191776315773552	percent	cpu	2026-02-24 07:44:21.379+00
\N	260	cpu_usage_percent	26.21853070176337	percent	cpu	2026-02-24 07:45:21.379+00
\N	260	cpu_usage_percent	26.28914473682495	percent	cpu	2026-02-24 07:46:21.379+00
\N	260	cpu_usage_percent	26.567214912267232	percent	cpu	2026-02-24 07:47:21.379+00
\N	260	cpu_usage_percent	26.749122807012654	percent	cpu	2026-02-24 07:48:21.379+00
\N	260	cpu_usage_percent	26.77828947367074	percent	cpu	2026-02-24 07:49:21.379+00
\N	260	cpu_usage_percent	26.512171052623017	percent	cpu	2026-02-24 07:50:21.379+00
\N	260	cpu_usage_percent	26.843859649104033	percent	cpu	2026-02-24 07:51:21.379+00
\N	252	cpu_usage_percent	24.506140350866573	percent	cpu	2026-02-24 09:19:47.348+00
\N	252	cpu_usage_percent	24.569298245621397	percent	cpu	2026-02-24 09:20:47.348+00
\N	252	cpu_usage_percent	24.41043445918183	percent	cpu	2026-02-24 09:21:47.348+00
\N	252	cpu_usage_percent	24.374561403477742	percent	cpu	2026-02-24 09:22:47.348+00
\N	252	cpu_usage_percent	22.380701754356565	percent	cpu	2026-02-24 08:09:25.449+00
\N	252	cpu_usage_percent	22.392982456142803	percent	cpu	2026-02-24 08:10:25.449+00
\N	252	cpu_usage_percent	22.360526315741282	percent	cpu	2026-02-24 08:11:25.449+00
\N	252	cpu_usage_percent	22.506578947343925	percent	cpu	2026-02-24 08:12:25.449+00
\N	252	cpu_usage_percent	22.514035087691525	percent	cpu	2026-02-24 08:13:25.449+00
\N	252	cpu_usage_percent	22.404385964925353	percent	cpu	2026-02-24 08:14:25.449+00
\N	252	cpu_usage_percent	22.37850877192902	percent	cpu	2026-02-24 08:15:25.449+00
\N	252	cpu_usage_percent	22.651754385983708	percent	cpu	2026-02-24 08:16:25.449+00
\N	252	cpu_usage_percent	22.516228070180347	percent	cpu	2026-02-24 08:17:25.449+00
\N	252	cpu_usage_percent	22.714912280718096	percent	cpu	2026-02-24 08:18:25.449+00
\N	252	cpu_usage_percent	22.73201754384087	percent	cpu	2026-02-24 08:19:25.449+00
\N	252	cpu_usage_percent	22.416228070168913	percent	cpu	2026-02-24 08:20:25.449+00
\N	252	cpu_usage_percent	24.23333333333416	percent	cpu	2026-02-24 08:21:25.449+00
\N	252	cpu_usage_percent	24.23026315790291	percent	cpu	2026-02-24 09:23:47.348+00
\N	252	cpu_usage_percent	24.482008456318127	percent	cpu	2026-02-24 09:24:47.348+00
\N	252	cpu_usage_percent	24.454824561416586	percent	cpu	2026-02-24 09:25:47.348+00
\N	252	cpu_usage_percent	24.41271929828075	percent	cpu	2026-02-24 09:26:47.348+00
\N	252	cpu_usage_percent	24.38800607699845	percent	cpu	2026-02-24 09:27:47.348+00
\N	252	cpu_usage_percent	24.346052631552	percent	cpu	2026-02-24 09:28:47.348+00
\N	252	cpu_usage_percent	24.525877192959584	percent	cpu	2026-02-24 09:29:47.348+00
\N	252	cpu_usage_percent	24.487719298258696	percent	cpu	2026-02-24 09:30:47.348+00
\N	252	cpu_usage_percent	25.330701754367183	percent	cpu	2026-02-24 09:31:47.348+00
\N	257	cpu_usage_percent	4.5561403508927185	percent	cpu	2026-02-24 08:46:35.974+00
\N	257	cpu_usage_percent	4.57456140350061	percent	cpu	2026-02-24 08:47:35.974+00
\N	257	cpu_usage_percent	4.622807017580627	percent	cpu	2026-02-24 08:48:35.974+00
\N	257	cpu_usage_percent	5.000877192983282	percent	cpu	2026-02-24 08:49:35.974+00
\N	257	cpu_usage_percent	5.070175438600586	percent	cpu	2026-02-24 08:50:35.974+00
\N	257	cpu_usage_percent	5.239473684229324	percent	cpu	2026-02-24 08:51:35.974+00
\N	248	cpu_usage_percent	2.309210526332137	percent	cpu	2026-02-24 09:19:46.893+00
\N	248	cpu_usage_percent	2.506140350862495	percent	cpu	2026-02-24 09:20:46.893+00
\N	248	cpu_usage_percent	2.500052630869675	percent	cpu	2026-02-24 09:21:46.893+00
\N	248	cpu_usage_percent	2.5877192982864727	percent	cpu	2026-02-24 09:22:46.893+00
\N	248	cpu_usage_percent	2.595614035115503	percent	cpu	2026-02-24 09:23:46.893+00
\N	248	cpu_usage_percent	2.6109649123329888	percent	cpu	2026-02-24 09:24:46.893+00
\N	248	cpu_usage_percent	2.6460526316230784	percent	cpu	2026-02-24 09:25:46.893+00
\N	248	cpu_usage_percent	2.6235363880958005	percent	cpu	2026-02-24 09:26:46.893+00
\N	248	cpu_usage_percent	2.5425438595968473	percent	cpu	2026-02-24 09:27:46.893+00
\N	248	cpu_usage_percent	2.509649122877292	percent	cpu	2026-02-24 09:28:46.893+00
\N	248	cpu_usage_percent	2.355221838260732	percent	cpu	2026-02-24 09:29:46.893+00
\N	248	cpu_usage_percent	2.265789473649903	percent	cpu	2026-02-24 09:30:46.893+00
\N	248	cpu_usage_percent	2.2328947367669514	percent	cpu	2026-02-24 09:31:46.893+00
\N	236	cpu_usage_percent	1.8315789472769382	percent	cpu	2026-02-24 08:49:36.883+00
\N	236	cpu_usage_percent	1.7147548920391245	percent	cpu	2026-02-24 08:50:36.883+00
\N	236	cpu_usage_percent	1.5192982456401865	percent	cpu	2026-02-24 08:51:36.883+00
\N	236	cpu_usage_percent	1.4940455721712027	percent	cpu	2026-02-24 08:52:36.883+00
\N	236	cpu_usage_percent	1.494736842026839	percent	cpu	2026-02-24 08:53:36.883+00
\N	236	cpu_usage_percent	1.52631578950637	percent	cpu	2026-02-24 08:54:36.883+00
\N	236	cpu_usage_percent	1.659649122800488	percent	cpu	2026-02-24 08:55:36.883+00
\N	236	cpu_usage_percent	1.835087719291721	percent	cpu	2026-02-24 08:56:36.883+00
\N	236	cpu_usage_percent	1.687719298265236	percent	cpu	2026-02-24 08:57:36.883+00
\N	236	cpu_usage_percent	1.8526315788754886	percent	cpu	2026-02-24 08:58:36.883+00
\N	236	cpu_usage_percent	1.8701754386226526	percent	cpu	2026-02-24 08:59:36.883+00
\N	236	cpu_usage_percent	1.7298245614623369	percent	cpu	2026-02-24 09:00:36.883+00
\N	236	cpu_usage_percent	1.5859649122872526	percent	cpu	2026-02-24 09:01:36.883+00
\N	257	cpu_usage_percent	5.12807017543534	percent	cpu	2026-02-24 09:19:47.916+00
\N	257	cpu_usage_percent	5.177102156102521	percent	cpu	2026-02-24 09:20:47.916+00
\N	257	cpu_usage_percent	5.366666666681368	percent	cpu	2026-02-24 09:21:47.916+00
\N	257	cpu_usage_percent	5.416666666666671	percent	cpu	2026-02-24 09:22:47.916+00
\N	257	cpu_usage_percent	4.914912280683794	percent	cpu	2026-02-24 09:23:47.916+00
\N	257	cpu_usage_percent	4.832456140337811	percent	cpu	2026-02-24 09:24:47.916+00
\N	257	cpu_usage_percent	4.765914744762796	percent	cpu	2026-02-24 09:25:47.916+00
\N	252	cpu_usage_percent	24.08815789475564	percent	cpu	2026-02-24 08:49:37.835+00
\N	252	cpu_usage_percent	23.79298245615996	percent	cpu	2026-02-24 08:50:37.835+00
\N	252	cpu_usage_percent	23.60043859650513	percent	cpu	2026-02-24 08:51:37.835+00
\N	252	cpu_usage_percent	23.36842105264384	percent	cpu	2026-02-24 08:52:37.835+00
\N	252	cpu_usage_percent	23.163596491223174	percent	cpu	2026-02-24 08:53:37.835+00
\N	252	cpu_usage_percent	23.07675438596084	percent	cpu	2026-02-24 08:54:37.835+00
\N	252	cpu_usage_percent	23.145175438594862	percent	cpu	2026-02-24 08:55:37.835+00
\N	252	cpu_usage_percent	23.137719298247262	percent	cpu	2026-02-24 08:56:37.835+00
\N	252	cpu_usage_percent	23.018421052644655	percent	cpu	2026-02-24 08:57:37.835+00
\N	252	cpu_usage_percent	23.125438596522287	percent	cpu	2026-02-24 08:58:37.835+00
\N	252	cpu_usage_percent	23.285087719294168	percent	cpu	2026-02-24 08:59:37.835+00
\N	252	cpu_usage_percent	23.40570175436146	percent	cpu	2026-02-24 09:00:37.835+00
\N	252	cpu_usage_percent	23.483771929831917	percent	cpu	2026-02-24 09:01:37.835+00
\N	257	cpu_usage_percent	4.443859649115467	percent	cpu	2026-02-24 09:26:47.916+00
\N	257	cpu_usage_percent	4.657478491516059	percent	cpu	2026-02-24 09:27:47.916+00
\N	257	cpu_usage_percent	4.784210526319072	percent	cpu	2026-02-24 09:28:47.916+00
\N	257	cpu_usage_percent	5.158771929809049	percent	cpu	2026-02-24 09:29:47.916+00
\N	257	cpu_usage_percent	5.226224101356863	percent	cpu	2026-02-24 09:30:47.916+00
\N	257	cpu_usage_percent	5.435087719294998	percent	cpu	2026-02-24 09:31:47.916+00
\N	252	cpu_usage_percent	27.183771929805772	percent	cpu	2026-02-24 08:22:31.628+00
\N	257	cpu_usage_percent	4.162280701750305	percent	cpu	2026-02-24 08:18:25.683+00
\N	257	cpu_usage_percent	4.298245614035096	percent	cpu	2026-02-24 08:19:25.683+00
\N	257	cpu_usage_percent	4.646491228067745	percent	cpu	2026-02-24 08:20:25.683+00
\N	257	cpu_usage_percent	4.986842105271336	percent	cpu	2026-02-24 08:21:25.683+00
\N	248	cpu_usage_percent	2.101754385961655	percent	cpu	2026-02-24 07:39:20.647+00
\N	248	cpu_usage_percent	2.0828947368110704	percent	cpu	2026-02-24 07:40:20.647+00
\N	248	cpu_usage_percent	2.1434210525956416	percent	cpu	2026-02-24 07:41:20.647+00
\N	248	cpu_usage_percent	2.2605263157911253	percent	cpu	2026-02-24 07:42:20.647+00
\N	248	cpu_usage_percent	2.323245614064504	percent	cpu	2026-02-24 07:43:20.647+00
\N	248	cpu_usage_percent	2.538596491223174	percent	cpu	2026-02-24 07:44:20.647+00
\N	248	cpu_usage_percent	2.7065789474076496	percent	cpu	2026-02-24 07:45:20.647+00
\N	248	cpu_usage_percent	2.724999999995106	percent	cpu	2026-02-24 07:46:20.647+00
\N	248	cpu_usage_percent	2.62807017543534	percent	cpu	2026-02-24 07:47:20.647+00
\N	248	cpu_usage_percent	2.667543859703045	percent	cpu	2026-02-24 07:48:20.647+00
\N	248	cpu_usage_percent	2.365350877179921	percent	cpu	2026-02-24 07:49:20.647+00
\N	248	cpu_usage_percent	2.3144736842317712	percent	cpu	2026-02-24 07:50:20.647+00
\N	248	cpu_usage_percent	2.459649122891989	percent	cpu	2026-02-24 07:51:20.647+00
\N	260	cpu_usage_percent	76.30581140350714	percent	cpu	2026-02-24 08:47:36.199+00
\N	260	cpu_usage_percent	76.3324561403664	percent	cpu	2026-02-24 08:48:36.199+00
\N	260	cpu_usage_percent	75.90559210527174	percent	cpu	2026-02-24 08:49:36.199+00
\N	260	cpu_usage_percent	65.15449561405387	percent	cpu	2026-02-24 08:50:36.199+00
\N	260	cpu_usage_percent	54.38289473682904	percent	cpu	2026-02-24 08:51:36.199+00
\N	133	cpu_usage_percent	0.6653508771488674	percent	cpu	2026-02-24 09:59:59.194+00
\N	133	cpu_usage_percent	0.44736842110165753	percent	cpu	2026-02-24 10:00:59.194+00
\N	133	cpu_usage_percent	0.4934210526315894	percent	cpu	2026-02-24 10:01:59.194+00
\N	133	cpu_usage_percent	0.3729785300701707	percent	cpu	2026-02-24 10:02:59.194+00
\N	133	cpu_usage_percent	10.520614035010937	percent	cpu	2026-02-24 08:49:36.441+00
\N	133	cpu_usage_percent	7.7719298245695825	percent	cpu	2026-02-24 08:50:36.441+00
\N	133	cpu_usage_percent	5.042105263197115	percent	cpu	2026-02-24 08:51:36.441+00
\N	133	cpu_usage_percent	2.336842105315455	percent	cpu	2026-02-24 08:52:36.441+00
\N	257	cpu_usage_percent	4.778947368419409	percent	cpu	2026-02-24 07:39:21.118+00
\N	257	cpu_usage_percent	4.980701754408827	percent	cpu	2026-02-24 07:40:21.118+00
\N	257	cpu_usage_percent	5.266666666669934	percent	cpu	2026-02-24 07:41:21.118+00
\N	257	cpu_usage_percent	5.436842105261519	percent	cpu	2026-02-24 07:42:21.118+00
\N	257	cpu_usage_percent	5.326315789491645	percent	cpu	2026-02-24 07:43:21.118+00
\N	257	cpu_usage_percent	5.021929824561383	percent	cpu	2026-02-24 07:44:21.118+00
\N	257	cpu_usage_percent	4.850877192966109	percent	cpu	2026-02-24 07:45:21.118+00
\N	257	cpu_usage_percent	4.490350877188064	percent	cpu	2026-02-24 07:46:21.118+00
\N	257	cpu_usage_percent	4.462280701743751	percent	cpu	2026-02-24 07:47:21.118+00
\N	257	cpu_usage_percent	4.4631578947065975	percent	cpu	2026-02-24 07:48:21.118+00
\N	257	cpu_usage_percent	4.609649122811092	percent	cpu	2026-02-24 07:49:21.118+00
\N	257	cpu_usage_percent	4.87543859651818	percent	cpu	2026-02-24 07:50:21.118+00
\N	257	cpu_usage_percent	5.201754385948547	percent	cpu	2026-02-24 07:51:21.118+00
\N	133	cpu_usage_percent	0.44078947375774646	percent	cpu	2026-02-24 08:53:36.441+00
\N	133	cpu_usage_percent	0.42105263152177486	percent	cpu	2026-02-24 08:54:36.441+00
\N	133	cpu_usage_percent	0.5543859648567349	percent	cpu	2026-02-24 08:55:36.441+00
\N	133	cpu_usage_percent	0.6539473684275947	percent	cpu	2026-02-24 08:56:36.441+00
\N	133	cpu_usage_percent	0.5438596490983088	percent	cpu	2026-02-24 08:57:36.441+00
\N	133	cpu_usage_percent	0.6311403507399547	percent	cpu	2026-02-24 08:58:36.441+00
\N	133	cpu_usage_percent	0.6385964912101088	percent	cpu	2026-02-24 08:59:36.441+00
\N	133	cpu_usage_percent	0.5021929825460063	percent	cpu	2026-02-24 09:00:36.441+00
\N	133	cpu_usage_percent	0.42017543859977025	percent	cpu	2026-02-24 09:01:36.441+00
\N	236	cpu_usage_percent	1.5789473684210549	percent	cpu	2026-02-24 08:19:31.163+00
\N	236	cpu_usage_percent	1.2736842104871187	percent	cpu	2026-02-24 08:20:31.163+00
\N	236	cpu_usage_percent	1.4070175439446189	percent	cpu	2026-02-24 08:21:31.163+00
\N	236	cpu_usage_percent	1.4245614035283864	percent	cpu	2026-02-24 08:22:31.163+00
\N	236	cpu_usage_percent	1.5368421053873504	percent	cpu	2026-02-24 08:23:31.163+00
\N	236	cpu_usage_percent	1.617543859603387	percent	cpu	2026-02-24 08:24:31.163+00
\N	236	cpu_usage_percent	1.8035087719755865	percent	cpu	2026-02-24 08:25:31.163+00
\N	236	cpu_usage_percent	1.9614035087196555	percent	cpu	2026-02-24 08:26:31.163+00
\N	236	cpu_usage_percent	1.9999999999019735	percent	cpu	2026-02-24 08:27:31.163+00
\N	236	cpu_usage_percent	2.4877192983567227	percent	cpu	2026-02-24 08:28:31.163+00
\N	236	cpu_usage_percent	2.3789473683491735	percent	cpu	2026-02-24 08:29:31.163+00
\N	236	cpu_usage_percent	2.2140350875755246	percent	cpu	2026-02-24 08:30:31.163+00
\N	236	cpu_usage_percent	2.1438596492404542	percent	cpu	2026-02-24 08:31:31.163+00
\N	133	cpu_usage_percent	0.3688596491702043	percent	cpu	2026-02-24 10:03:59.194+00
\N	133	cpu_usage_percent	0.3500000000604757	percent	cpu	2026-02-24 10:04:59.194+00
\N	133	cpu_usage_percent	0.2833333333725534	percent	cpu	2026-02-24 10:05:59.194+00
\N	133	cpu_usage_percent	0.5092105262079656	percent	cpu	2026-02-24 10:06:59.194+00
\N	133	cpu_usage_percent	0.5973684211392367	percent	cpu	2026-02-24 10:07:59.194+00
\N	133	cpu_usage_percent	0.6157894736858509	percent	cpu	2026-02-24 10:08:59.194+00
\N	133	cpu_usage_percent	0.6140350877601577	percent	cpu	2026-02-24 10:09:59.194+00
\N	133	cpu_usage_percent	0.5057017543974212	percent	cpu	2026-02-24 10:10:59.194+00
\N	133	cpu_usage_percent	0.5048245613528621	percent	cpu	2026-02-24 10:11:59.194+00
\N	248	cpu_usage_percent	2.3811403508788374	percent	cpu	2026-02-24 08:49:37.363+00
\N	248	cpu_usage_percent	2.309210526372979	percent	cpu	2026-02-24 08:50:37.363+00
\N	248	cpu_usage_percent	2.3236842105459345	percent	cpu	2026-02-24 08:51:37.363+00
\N	248	cpu_usage_percent	2.342543859655663	percent	cpu	2026-02-24 08:52:37.363+00
\N	248	cpu_usage_percent	2.337280701715187	percent	cpu	2026-02-24 08:53:37.363+00
\N	252	cpu_usage_percent	22.528947368427595	percent	cpu	2026-02-24 08:19:31.628+00
\N	252	cpu_usage_percent	22.396929824577754	percent	cpu	2026-02-24 08:20:31.628+00
\N	252	cpu_usage_percent	24.88771929824317	percent	cpu	2026-02-24 08:21:31.628+00
\N	252	cpu_usage_percent	30.00877192979189	percent	cpu	2026-02-24 08:23:31.628+00
\N	252	cpu_usage_percent	32.87324561402529	percent	cpu	2026-02-24 08:24:31.628+00
\N	252	cpu_usage_percent	34.6811403508968	percent	cpu	2026-02-24 08:25:31.628+00
\N	252	cpu_usage_percent	32.96842105265935	percent	cpu	2026-02-24 08:26:31.628+00
\N	252	cpu_usage_percent	30.27149122804731	percent	cpu	2026-02-24 08:27:31.628+00
\N	252	cpu_usage_percent	28.040789473687482	percent	cpu	2026-02-24 08:28:31.628+00
\N	252	cpu_usage_percent	25.43991228069278	percent	cpu	2026-02-24 08:29:31.628+00
\N	252	cpu_usage_percent	24.279824561427205	percent	cpu	2026-02-24 08:30:31.628+00
\N	252	cpu_usage_percent	24.039473684214613	percent	cpu	2026-02-24 08:31:31.628+00
\N	248	cpu_usage_percent	2.358771929876852	percent	cpu	2026-02-24 08:54:37.363+00
\N	248	cpu_usage_percent	2.4710526316132757	percent	cpu	2026-02-24 08:55:37.363+00
\N	248	cpu_usage_percent	2.5592105263811504	percent	cpu	2026-02-24 08:56:37.363+00
\N	248	cpu_usage_percent	2.6026315789817005	percent	cpu	2026-02-24 08:57:37.363+00
\N	248	cpu_usage_percent	2.658771929747772	percent	cpu	2026-02-24 08:58:37.363+00
\N	248	cpu_usage_percent	2.6921052631938522	percent	cpu	2026-02-24 08:59:37.363+00
\N	248	cpu_usage_percent	2.702192982511704	percent	cpu	2026-02-24 09:00:37.363+00
\N	248	cpu_usage_percent	2.6631578948071137	percent	cpu	2026-02-24 09:01:37.363+00
\N	236	cpu_usage_percent	2.5729553724257386	percent	cpu	2026-02-24 09:59:59.717+00
\N	236	cpu_usage_percent	2.385964912378739	percent	cpu	2026-02-24 10:00:59.717+00
\N	236	cpu_usage_percent	2.3112523990957925	percent	cpu	2026-02-24 10:01:59.717+00
\N	236	cpu_usage_percent	2.157894736809439	percent	cpu	2026-02-24 10:02:59.717+00
\N	236	cpu_usage_percent	1.4456140349635547	percent	cpu	2026-02-24 10:03:59.717+00
\N	236	cpu_usage_percent	1.3508771928517547	percent	cpu	2026-02-24 10:04:59.717+00
\N	236	cpu_usage_percent	1.3684210527623009	percent	cpu	2026-02-24 10:05:59.717+00
\N	236	cpu_usage_percent	1.5999438615535269	percent	cpu	2026-02-24 10:06:59.717+00
\N	236	cpu_usage_percent	1.7287901275108197	percent	cpu	2026-02-24 10:07:59.717+00
\N	260	cpu_usage_percent	25.940021929839688	percent	cpu	2026-02-24 08:19:32.182+00
\N	260	cpu_usage_percent	25.885197368374904	percent	cpu	2026-02-24 08:20:32.182+00
\N	260	cpu_usage_percent	25.305811403535742	percent	cpu	2026-02-24 08:21:32.182+00
\N	260	cpu_usage_percent	25.38980263161777	percent	cpu	2026-02-24 08:22:32.182+00
\N	260	cpu_usage_percent	25.318750000003277	percent	cpu	2026-02-24 08:23:32.182+00
\N	260	cpu_usage_percent	25.3700657894737	percent	cpu	2026-02-24 08:24:32.182+00
\N	260	cpu_usage_percent	25.321052631622663	percent	cpu	2026-02-24 08:25:32.182+00
\N	260	cpu_usage_percent	25.35241228069809	percent	cpu	2026-02-24 08:26:32.182+00
\N	260	cpu_usage_percent	25.354276315805407	percent	cpu	2026-02-24 08:27:32.182+00
\N	260	cpu_usage_percent	25.406798245630384	percent	cpu	2026-02-24 08:28:32.182+00
\N	260	cpu_usage_percent	25.350328947390892	percent	cpu	2026-02-24 08:29:32.182+00
\N	260	cpu_usage_percent	25.3214912280326	percent	cpu	2026-02-24 08:30:32.182+00
\N	260	cpu_usage_percent	25.31962719300698	percent	cpu	2026-02-24 08:31:32.182+00
\N	260	cpu_usage_percent	91.24484649124115	percent	cpu	2026-02-24 09:19:48.372+00
\N	260	cpu_usage_percent	91.20657894739946	percent	cpu	2026-02-24 09:20:48.372+00
\N	260	cpu_usage_percent	91.07796052633172	percent	cpu	2026-02-24 09:21:48.372+00
\N	260	cpu_usage_percent	91.23355263156874	percent	cpu	2026-02-24 09:22:48.372+00
\N	260	cpu_usage_percent	90.42089173877329	percent	cpu	2026-02-24 09:23:48.372+00
\N	260	cpu_usage_percent	90.353179824561	percent	cpu	2026-02-24 09:24:48.372+00
\N	260	cpu_usage_percent	89.61962719302902	percent	cpu	2026-02-24 09:25:48.372+00
\N	260	cpu_usage_percent	89.3565789473819	percent	cpu	2026-02-24 09:26:48.372+00
\N	257	cpu_usage_percent	5.000877192983282	percent	cpu	2026-02-24 08:49:38.327+00
\N	257	cpu_usage_percent	5.070175438600586	percent	cpu	2026-02-24 08:50:38.327+00
\N	257	cpu_usage_percent	5.239473684229324	percent	cpu	2026-02-24 08:51:38.327+00
\N	257	cpu_usage_percent	5.266666666649527	percent	cpu	2026-02-24 08:52:38.327+00
\N	257	cpu_usage_percent	5.148245614050623	percent	cpu	2026-02-24 08:53:38.327+00
\N	257	cpu_usage_percent	4.7596491228282645	percent	cpu	2026-02-24 08:54:38.327+00
\N	257	cpu_usage_percent	4.686842105277876	percent	cpu	2026-02-24 08:55:38.327+00
\N	257	cpu_usage_percent	4.471929824539359	percent	cpu	2026-02-24 08:56:38.327+00
\N	257	cpu_usage_percent	4.176315789482672	percent	cpu	2026-02-24 08:57:38.327+00
\N	257	cpu_usage_percent	4.4622807017642	percent	cpu	2026-02-24 08:58:38.327+00
\N	257	cpu_usage_percent	4.796491228044047	percent	cpu	2026-02-24 08:59:38.327+00
\N	257	cpu_usage_percent	4.870175438598139	percent	cpu	2026-02-24 09:00:38.327+00
\N	257	cpu_usage_percent	5.113157894719691	percent	cpu	2026-02-24 09:01:38.327+00
\N	260	cpu_usage_percent	89.0533991228062	percent	cpu	2026-02-24 09:27:48.372+00
\N	260	cpu_usage_percent	88.8415570175602	percent	cpu	2026-02-24 09:28:48.372+00
\N	260	cpu_usage_percent	88.89813596492004	percent	cpu	2026-02-24 09:29:48.372+00
\N	260	cpu_usage_percent	88.77280701749362	percent	cpu	2026-02-24 09:30:48.372+00
\N	260	cpu_usage_percent	88.4618421052705	percent	cpu	2026-02-24 09:31:48.372+00
\N	236	cpu_usage_percent	1.778947368362239	percent	cpu	2026-02-24 10:08:59.717+00
\N	236	cpu_usage_percent	1.778947368362239	percent	cpu	2026-02-24 10:09:59.717+00
\N	236	cpu_usage_percent	1.456140350844521	percent	cpu	2026-02-24 10:10:59.717+00
\N	236	cpu_usage_percent	1.5729658985980421	percent	cpu	2026-02-24 10:11:59.717+00
\N	133	cpu_usage_percent	0.665789473671154	percent	cpu	2026-02-24 09:29:48.945+00
\N	133	cpu_usage_percent	0.5350877193064321	percent	cpu	2026-02-24 09:30:48.945+00
\N	133	cpu_usage_percent	0.4456140350534099	percent	cpu	2026-02-24 09:31:48.945+00
\N	133	cpu_usage_percent	0.4324561403247458	percent	cpu	2026-02-24 09:32:48.945+00
\N	133	cpu_usage_percent	0.4243829867517377	percent	cpu	2026-02-24 09:33:48.945+00
\N	133	cpu_usage_percent	0.43070175435819635	percent	cpu	2026-02-24 09:34:48.945+00
\N	133	cpu_usage_percent	0.5614035088454727	percent	cpu	2026-02-24 09:35:48.945+00
\N	133	cpu_usage_percent	0.5565789473864129	percent	cpu	2026-02-24 09:36:48.945+00
\N	133	cpu_usage_percent	0.6653508772305798	percent	cpu	2026-02-24 09:37:48.945+00
\N	133	cpu_usage_percent	0.6745614035038869	percent	cpu	2026-02-24 09:38:48.945+00
\N	133	cpu_usage_percent	0.552192982408755	percent	cpu	2026-02-24 09:39:48.945+00
\N	133	cpu_usage_percent	0.5580740917578169	percent	cpu	2026-02-24 09:40:48.945+00
\N	133	cpu_usage_percent	0.5460526315871306	percent	cpu	2026-02-24 09:41:48.945+00
\N	236	cpu_usage_percent	1.8701754386226526	percent	cpu	2026-02-24 08:59:39.659+00
\N	236	cpu_usage_percent	1.7298245614623369	percent	cpu	2026-02-24 09:00:39.659+00
\N	236	cpu_usage_percent	1.5859649122872526	percent	cpu	2026-02-24 09:01:39.659+00
\N	236	cpu_usage_percent	1.470175438576888	percent	cpu	2026-02-24 09:02:39.659+00
\N	236	cpu_usage_percent	1.568421052703485	percent	cpu	2026-02-24 09:03:39.659+00
\N	236	cpu_usage_percent	1.6035087720344023	percent	cpu	2026-02-24 09:04:39.659+00
\N	236	cpu_usage_percent	1.7719298244960555	percent	cpu	2026-02-24 09:05:39.659+00
\N	236	cpu_usage_percent	1.7614035087784856	percent	cpu	2026-02-24 09:06:39.659+00
\N	257	cpu_usage_percent	4.977192982434914	percent	cpu	2026-02-24 10:00:01.064+00
\N	257	cpu_usage_percent	4.934210526315795	percent	cpu	2026-02-24 10:01:01.064+00
\N	257	cpu_usage_percent	5.097368421061631	percent	cpu	2026-02-24 10:02:01.064+00
\N	257	cpu_usage_percent	4.908142284697675	percent	cpu	2026-02-24 10:03:01.064+00
\N	257	cpu_usage_percent	4.659649122837251	percent	cpu	2026-02-24 10:04:01.064+00
\N	257	cpu_usage_percent	4.236842105308099	percent	cpu	2026-02-24 10:05:01.064+00
\N	257	cpu_usage_percent	3.6956140350983446	percent	cpu	2026-02-24 10:06:01.064+00
\N	257	cpu_usage_percent	4.171929824607162	percent	cpu	2026-02-24 10:07:01.064+00
\N	257	cpu_usage_percent	4.150877193008611	percent	cpu	2026-02-24 10:08:01.064+00
\N	257	cpu_usage_percent	4.4394736841991005	percent	cpu	2026-02-24 10:09:01.064+00
\N	257	cpu_usage_percent	4.809649122813568	percent	cpu	2026-02-24 10:10:01.064+00
\N	257	cpu_usage_percent	4.988596491237885	percent	cpu	2026-02-24 10:11:01.064+00
\N	257	cpu_usage_percent	5.2771929824283745	percent	cpu	2026-02-24 10:12:01.064+00
\N	236	cpu_usage_percent	1.8877192982064201	percent	cpu	2026-02-24 09:07:39.659+00
\N	236	cpu_usage_percent	1.8701754384592562	percent	cpu	2026-02-24 09:08:39.659+00
\N	236	cpu_usage_percent	1.8533203275047612	percent	cpu	2026-02-24 09:09:39.659+00
\N	236	cpu_usage_percent	1.7052631580124	percent	cpu	2026-02-24 09:10:39.659+00
\N	236	cpu_usage_percent	1.5607127068211923	percent	cpu	2026-02-24 09:11:39.659+00
\N	252	cpu_usage_percent	22.56393027320388	percent	cpu	2026-02-24 10:10:03.23+00
\N	252	cpu_usage_percent	22.436252820258588	percent	cpu	2026-02-24 10:11:03.23+00
\N	252	cpu_usage_percent	22.29649122810531	percent	cpu	2026-02-24 10:12:03.23+00
\N	252	cpu_usage_percent	22.213703763460302	percent	cpu	2026-02-24 10:13:03.23+00
\N	252	cpu_usage_percent	22.331140350873113	percent	cpu	2026-02-24 10:14:03.23+00
\N	252	cpu_usage_percent	22.219736842099564	percent	cpu	2026-02-24 10:15:03.23+00
\N	252	cpu_usage_percent	22.385087719272917	percent	cpu	2026-02-24 10:16:03.23+00
\N	252	cpu_usage_percent	22.557456140312496	percent	cpu	2026-02-24 10:17:03.23+00
\N	252	cpu_usage_percent	22.548684210520605	percent	cpu	2026-02-24 10:18:03.23+00
\N	252	cpu_usage_percent	22.652192982444703	percent	cpu	2026-02-24 10:19:03.23+00
\N	252	cpu_usage_percent	23.610964912263555	percent	cpu	2026-02-24 10:20:03.23+00
\N	252	cpu_usage_percent	23.73377192984009	percent	cpu	2026-02-24 10:21:03.23+00
\N	252	cpu_usage_percent	23.871929824532003	percent	cpu	2026-02-24 10:22:03.23+00
\N	252	cpu_usage_percent	23.285087719294168	percent	cpu	2026-02-24 08:59:40.707+00
\N	252	cpu_usage_percent	23.40570175436146	percent	cpu	2026-02-24 09:00:40.707+00
\N	252	cpu_usage_percent	23.483771929831917	percent	cpu	2026-02-24 09:01:40.707+00
\N	252	cpu_usage_percent	23.843421052647102	percent	cpu	2026-02-24 09:02:40.707+00
\N	252	cpu_usage_percent	24.15657894736924	percent	cpu	2026-02-24 09:03:40.707+00
\N	252	cpu_usage_percent	24.410087719249248	percent	cpu	2026-02-24 09:04:40.707+00
\N	260	cpu_usage_percent	73.22105263154586	percent	cpu	2026-02-24 08:49:38.761+00
\N	260	cpu_usage_percent	62.503289473651535	percent	cpu	2026-02-24 08:50:38.761+00
\N	260	cpu_usage_percent	51.7731359649323	percent	cpu	2026-02-24 08:51:38.761+00
\N	260	cpu_usage_percent	41.10175438592897	percent	cpu	2026-02-24 08:52:38.761+00
\N	260	cpu_usage_percent	36.675219298248486	percent	cpu	2026-02-24 08:53:38.761+00
\N	260	cpu_usage_percent	41.93980263160101	percent	cpu	2026-02-24 08:54:38.761+00
\N	260	cpu_usage_percent	51.863925438578526	percent	cpu	2026-02-24 08:55:38.761+00
\N	260	cpu_usage_percent	58.04967105263036	percent	cpu	2026-02-24 08:56:38.761+00
\N	260	cpu_usage_percent	57.860087719296615	percent	cpu	2026-02-24 08:57:38.761+00
\N	257	cpu_usage_percent	4.326315789479423	percent	cpu	2026-02-24 08:19:31.857+00
\N	257	cpu_usage_percent	4.427192982474125	percent	cpu	2026-02-24 08:20:31.857+00
\N	257	cpu_usage_percent	5.0631578947344025	percent	cpu	2026-02-24 08:21:31.857+00
\N	257	cpu_usage_percent	5.171052631574867	percent	cpu	2026-02-24 08:22:31.857+00
\N	257	cpu_usage_percent	5.013157894708257	percent	cpu	2026-02-24 08:23:31.857+00
\N	257	cpu_usage_percent	4.623684210543487	percent	cpu	2026-02-24 08:24:31.857+00
\N	257	cpu_usage_percent	4.604385964931893	percent	cpu	2026-02-24 08:25:31.857+00
\N	257	cpu_usage_percent	4.442982456132199	percent	cpu	2026-02-24 08:26:31.857+00
\N	257	cpu_usage_percent	4.468421052647102	percent	cpu	2026-02-24 08:27:31.857+00
\N	257	cpu_usage_percent	4.53596491227745	percent	cpu	2026-02-24 08:28:31.857+00
\N	257	cpu_usage_percent	4.691228070194242	percent	cpu	2026-02-24 08:29:31.857+00
\N	257	cpu_usage_percent	4.984210526341954	percent	cpu	2026-02-24 08:30:31.857+00
\N	257	cpu_usage_percent	5.214035087714407	percent	cpu	2026-02-24 08:31:31.857+00
\N	260	cpu_usage_percent	49.207565789468376	percent	cpu	2026-02-24 08:58:38.761+00
\N	260	cpu_usage_percent	39.19188596491024	percent	cpu	2026-02-24 08:59:38.761+00
\N	260	cpu_usage_percent	29.229495614029787	percent	cpu	2026-02-24 09:00:38.761+00
\N	260	cpu_usage_percent	31.039035087696433	percent	cpu	2026-02-24 09:01:38.761+00
\N	248	cpu_usage_percent	2.4710526316132757	percent	cpu	2026-02-24 10:00:00.183+00
\N	248	cpu_usage_percent	2.563596491358794	percent	cpu	2026-02-24 10:01:00.183+00
\N	248	cpu_usage_percent	2.6078947368813346	percent	cpu	2026-02-24 10:02:00.183+00
\N	248	cpu_usage_percent	2.5657894736842195	percent	cpu	2026-02-24 10:03:00.183+00
\N	248	cpu_usage_percent	2.558333333377462	percent	cpu	2026-02-24 10:04:00.183+00
\N	248	cpu_usage_percent	2.4609649122545676	percent	cpu	2026-02-24 10:05:00.183+00
\N	248	cpu_usage_percent	2.3206140351759643	percent	cpu	2026-02-24 10:06:00.183+00
\N	133	cpu_usage_percent	0.6385964912101088	percent	cpu	2026-02-24 08:59:39.162+00
\N	133	cpu_usage_percent	0.5021929825460063	percent	cpu	2026-02-24 09:00:39.162+00
\N	133	cpu_usage_percent	0.42017543859977025	percent	cpu	2026-02-24 09:01:39.162+00
\N	133	cpu_usage_percent	0.3399122806200694	percent	cpu	2026-02-24 09:02:39.162+00
\N	133	cpu_usage_percent	0.4346491228135676	percent	cpu	2026-02-24 09:03:39.162+00
\N	133	cpu_usage_percent	0.4469298245385289	percent	cpu	2026-02-24 09:04:39.162+00
\N	133	cpu_usage_percent	1.5627192982815643	percent	cpu	2026-02-24 09:05:39.162+00
\N	133	cpu_usage_percent	1.63421052626515	percent	cpu	2026-02-24 09:06:39.162+00
\N	133	cpu_usage_percent	1.6635964912150172	percent	cpu	2026-02-24 09:07:39.162+00
\N	133	cpu_usage_percent	1.672368421088592	percent	cpu	2026-02-24 09:08:39.162+00
\N	133	cpu_usage_percent	1.6473684211572106	percent	cpu	2026-02-24 09:09:39.162+00
\N	133	cpu_usage_percent	0.5535087718938883	percent	cpu	2026-02-24 09:10:39.162+00
\N	133	cpu_usage_percent	0.4530701754010238	percent	cpu	2026-02-24 09:11:39.162+00
\N	248	cpu_usage_percent	2.391228070114991	percent	cpu	2026-02-24 10:07:00.183+00
\N	248	cpu_usage_percent	2.463157894702533	percent	cpu	2026-02-24 10:08:00.183+00
\N	248	cpu_usage_percent	2.498684210555737	percent	cpu	2026-02-24 10:09:00.183+00
\N	248	cpu_usage_percent	2.5732456140318334	percent	cpu	2026-02-24 10:10:00.183+00
\N	248	cpu_usage_percent	2.511254504403965	percent	cpu	2026-02-24 10:11:00.183+00
\N	248	cpu_usage_percent	2.552192982433283	percent	cpu	2026-02-24 10:12:00.183+00
\N	236	cpu_usage_percent	1.9308568681733078	percent	cpu	2026-02-24 09:29:49.45+00
\N	236	cpu_usage_percent	1.754385964912288	percent	cpu	2026-02-24 09:30:49.45+00
\N	236	cpu_usage_percent	1.5964912280048225	percent	cpu	2026-02-24 09:31:49.45+00
\N	236	cpu_usage_percent	1.5620943009945876	percent	cpu	2026-02-24 09:32:49.45+00
\N	236	cpu_usage_percent	1.5719298245548714	percent	cpu	2026-02-24 09:33:49.45+00
\N	236	cpu_usage_percent	1.5950541392241746	percent	cpu	2026-02-24 09:34:49.45+00
\N	236	cpu_usage_percent	1.7228070174327712	percent	cpu	2026-02-24 09:35:49.45+00
\N	236	cpu_usage_percent	1.7473684210461045	percent	cpu	2026-02-24 09:36:49.45+00
\N	236	cpu_usage_percent	1.859649122741672	percent	cpu	2026-02-24 09:37:49.45+00
\N	236	cpu_usage_percent	1.8666666667712377	percent	cpu	2026-02-24 09:38:49.45+00
\N	236	cpu_usage_percent	1.6807017542356562	percent	cpu	2026-02-24 09:39:49.45+00
\N	236	cpu_usage_percent	1.6947368421314195	percent	cpu	2026-02-24 09:40:49.45+00
\N	248	cpu_usage_percent	2.6921052631938522	percent	cpu	2026-02-24 08:59:40.194+00
\N	248	cpu_usage_percent	2.702192982511704	percent	cpu	2026-02-24 09:00:40.194+00
\N	248	cpu_usage_percent	2.6631578948071137	percent	cpu	2026-02-24 09:01:40.194+00
\N	248	cpu_usage_percent	2.5232456140465302	percent	cpu	2026-02-24 09:02:40.194+00
\N	248	cpu_usage_percent	2.5429824561191197	percent	cpu	2026-02-24 09:03:40.194+00
\N	248	cpu_usage_percent	2.631578947409281	percent	cpu	2026-02-24 09:04:40.194+00
\N	248	cpu_usage_percent	2.472807017620653	percent	cpu	2026-02-24 09:05:40.194+00
\N	248	cpu_usage_percent	2.4728600299774826	percent	cpu	2026-02-24 09:06:40.194+00
\N	248	cpu_usage_percent	2.537280701778897	percent	cpu	2026-02-24 09:07:40.194+00
\N	248	cpu_usage_percent	2.53333333332354	percent	cpu	2026-02-24 09:08:40.194+00
\N	248	cpu_usage_percent	2.5719298245875564	percent	cpu	2026-02-24 09:09:40.194+00
\N	248	cpu_usage_percent	2.5017543860074056	percent	cpu	2026-02-24 09:10:40.194+00
\N	248	cpu_usage_percent	2.4916666666895537	percent	cpu	2026-02-24 09:11:40.194+00
\N	236	cpu_usage_percent	1.6982456139828201	percent	cpu	2026-02-24 09:41:49.45+00
\N	252	cpu_usage_percent	24.60438596489105	percent	cpu	2026-02-24 09:05:40.707+00
\N	252	cpu_usage_percent	24.61885964914569	percent	cpu	2026-02-24 09:06:40.707+00
\N	252	cpu_usage_percent	24.832017543876816	percent	cpu	2026-02-24 09:07:40.707+00
\N	252	cpu_usage_percent	24.841228070190965	percent	cpu	2026-02-24 09:08:40.707+00
\N	252	cpu_usage_percent	24.91491228072465	percent	cpu	2026-02-24 09:09:40.707+00
\N	252	cpu_usage_percent	24.784649122759646	percent	cpu	2026-02-24 09:10:40.707+00
\N	252	cpu_usage_percent	24.75219298246023	percent	cpu	2026-02-24 09:11:40.707+00
\N	252	cpu_usage_percent	24.195614035073845	percent	cpu	2026-02-24 10:00:00.654+00
\N	252	cpu_usage_percent	23.745517512389725	percent	cpu	2026-02-24 10:01:00.654+00
\N	252	cpu_usage_percent	22.388157894724586	percent	cpu	2026-02-24 10:02:00.654+00
\N	252	cpu_usage_percent	22.027192982444717	percent	cpu	2026-02-24 10:03:00.654+00
\N	252	cpu_usage_percent	21.7214912280906	percent	cpu	2026-02-24 10:04:00.654+00
\N	252	cpu_usage_percent	21.27100416488723	percent	cpu	2026-02-24 10:05:00.654+00
\N	252	cpu_usage_percent	21.754385964891867	percent	cpu	2026-02-24 10:06:00.654+00
\N	252	cpu_usage_percent	22.562719298252972	percent	cpu	2026-02-24 10:07:00.654+00
\N	252	cpu_usage_percent	22.497684259264858	percent	cpu	2026-02-24 10:08:00.654+00
\N	252	cpu_usage_percent	22.445175438576086	percent	cpu	2026-02-24 10:09:00.654+00
\N	252	cpu_usage_percent	22.56393027320391	percent	cpu	2026-02-24 10:10:00.654+00
\N	252	cpu_usage_percent	22.436252820258602	percent	cpu	2026-02-24 10:11:00.654+00
\N	252	cpu_usage_percent	22.29649122810531	percent	cpu	2026-02-24 10:12:00.654+00
\N	248	cpu_usage_percent	2.355221838260732	percent	cpu	2026-02-24 09:29:49.926+00
\N	248	cpu_usage_percent	2.265789473649903	percent	cpu	2026-02-24 09:30:49.926+00
\N	248	cpu_usage_percent	2.2328947367669514	percent	cpu	2026-02-24 09:31:49.926+00
\N	248	cpu_usage_percent	2.1697368421346823	percent	cpu	2026-02-24 09:32:49.926+00
\N	248	cpu_usage_percent	2.1254385964896017	percent	cpu	2026-02-24 09:33:49.926+00
\N	248	cpu_usage_percent	2.148684210576974	percent	cpu	2026-02-24 09:34:49.926+00
\N	248	cpu_usage_percent	2.216666666668317	percent	cpu	2026-02-24 09:35:49.926+00
\N	248	cpu_usage_percent	2.2318655985917815	percent	cpu	2026-02-24 09:36:49.926+00
\N	248	cpu_usage_percent	2.2723684210346704	percent	cpu	2026-02-24 09:37:49.926+00
\N	248	cpu_usage_percent	2.3978070175814565	percent	cpu	2026-02-24 09:38:49.926+00
\N	248	cpu_usage_percent	2.5068684933394962	percent	cpu	2026-02-24 09:39:49.926+00
\N	248	cpu_usage_percent	2.6064309448136243	percent	cpu	2026-02-24 09:40:49.926+00
\N	248	cpu_usage_percent	2.720175438576902	percent	cpu	2026-02-24 09:41:49.926+00
\N	257	cpu_usage_percent	5.158771929809049	percent	cpu	2026-02-24 09:29:51.055+00
\N	257	cpu_usage_percent	5.226224101356863	percent	cpu	2026-02-24 09:30:51.055+00
\N	257	cpu_usage_percent	5.435087719294998	percent	cpu	2026-02-24 09:31:51.055+00
\N	257	cpu_usage_percent	5.453272700473008	percent	cpu	2026-02-24 09:32:51.055+00
\N	257	cpu_usage_percent	5.214035087755249	percent	cpu	2026-02-24 09:33:51.055+00
\N	257	cpu_usage_percent	4.74473684211263	percent	cpu	2026-02-24 09:34:51.055+00
\N	257	cpu_usage_percent	4.713157894735218	percent	cpu	2026-02-24 09:35:51.055+00
\N	257	cpu_usage_percent	4.407017543858842	percent	cpu	2026-02-24 09:36:51.055+00
\N	257	cpu_usage_percent	4.571052631587946	percent	cpu	2026-02-24 09:37:51.055+00
\N	257	cpu_usage_percent	4.704594418177024	percent	cpu	2026-02-24 09:38:51.055+00
\N	257	cpu_usage_percent	4.848245614057163	percent	cpu	2026-02-24 09:39:51.055+00
\N	257	cpu_usage_percent	5.234210526288834	percent	cpu	2026-02-24 09:40:51.055+00
\N	257	cpu_usage_percent	5.58596491229541	percent	cpu	2026-02-24 09:41:51.055+00
\N	257	cpu_usage_percent	4.796491228044047	percent	cpu	2026-02-24 08:59:41.209+00
\N	257	cpu_usage_percent	4.870175438598139	percent	cpu	2026-02-24 09:00:41.209+00
\N	257	cpu_usage_percent	5.113157894719691	percent	cpu	2026-02-24 09:01:41.209+00
\N	257	cpu_usage_percent	5.058771929797615	percent	cpu	2026-02-24 09:02:41.209+00
\N	257	cpu_usage_percent	5.156140350859232	percent	cpu	2026-02-24 09:03:41.209+00
\N	257	cpu_usage_percent	4.877192982464322	percent	cpu	2026-02-24 09:04:41.209+00
\N	257	cpu_usage_percent	4.821052631575682	percent	cpu	2026-02-24 09:05:41.209+00
\N	257	cpu_usage_percent	4.434210526319887	percent	cpu	2026-02-24 09:06:41.209+00
\N	257	cpu_usage_percent	4.607894736844571	percent	cpu	2026-02-24 09:07:41.209+00
\N	257	cpu_usage_percent	4.771052631590393	percent	cpu	2026-02-24 09:08:41.209+00
\N	257	cpu_usage_percent	5.1666666666585	percent	cpu	2026-02-24 09:09:41.209+00
\N	257	cpu_usage_percent	5.245614035091819	percent	cpu	2026-02-24 09:10:41.209+00
\N	257	cpu_usage_percent	5.4219298245458845	percent	cpu	2026-02-24 09:11:41.209+00
\N	248	cpu_usage_percent	2.5732456140318334	percent	cpu	2026-02-24 10:10:02.766+00
\N	248	cpu_usage_percent	2.511254504403965	percent	cpu	2026-02-24 10:11:02.766+00
\N	248	cpu_usage_percent	2.552192982433283	percent	cpu	2026-02-24 10:12:02.766+00
\N	248	cpu_usage_percent	2.4896756920926464	percent	cpu	2026-02-24 10:13:02.766+00
\N	248	cpu_usage_percent	2.449999999973869	percent	cpu	2026-02-24 10:14:02.766+00
\N	248	cpu_usage_percent	2.463157894661691	percent	cpu	2026-02-24 10:15:02.766+00
\N	248	cpu_usage_percent	2.4736842105426575	percent	cpu	2026-02-24 10:16:02.766+00
\N	248	cpu_usage_percent	2.5154032926392915	percent	cpu	2026-02-24 10:17:02.766+00
\N	248	cpu_usage_percent	2.5390350877046046	percent	cpu	2026-02-24 10:18:02.766+00
\N	260	cpu_usage_percent	39.19188596491024	percent	cpu	2026-02-24 08:59:41.642+00
\N	260	cpu_usage_percent	29.229495614029787	percent	cpu	2026-02-24 09:00:41.642+00
\N	260	cpu_usage_percent	31.039035087696433	percent	cpu	2026-02-24 09:01:41.642+00
\N	260	cpu_usage_percent	41.716666666662185	percent	cpu	2026-02-24 09:02:41.642+00
\N	260	cpu_usage_percent	52.348135964957216	percent	cpu	2026-02-24 09:03:41.642+00
\N	260	cpu_usage_percent	63.06425438591345	percent	cpu	2026-02-24 09:04:41.642+00
\N	260	cpu_usage_percent	73.700767543847	percent	cpu	2026-02-24 09:05:41.642+00
\N	260	cpu_usage_percent	77.62302631579684	percent	cpu	2026-02-24 09:06:41.642+00
\N	260	cpu_usage_percent	79.30296052631252	percent	cpu	2026-02-24 09:07:41.642+00
\N	260	cpu_usage_percent	79.93311403508159	percent	cpu	2026-02-24 09:08:41.642+00
\N	260	cpu_usage_percent	82.23157894735331	percent	cpu	2026-02-24 09:09:41.642+00
\N	260	cpu_usage_percent	85.72720247159711	percent	cpu	2026-02-24 09:10:41.642+00
\N	260	cpu_usage_percent	87.64692982457571	percent	cpu	2026-02-24 09:11:41.642+00
\N	252	cpu_usage_percent	24.525877192959584	percent	cpu	2026-02-24 09:29:50.564+00
\N	252	cpu_usage_percent	24.487719298258696	percent	cpu	2026-02-24 09:30:50.564+00
\N	252	cpu_usage_percent	25.330701754367183	percent	cpu	2026-02-24 09:31:50.564+00
\N	252	cpu_usage_percent	25.291666666703435	percent	cpu	2026-02-24 09:32:50.564+00
\N	252	cpu_usage_percent	25.25307017545984	percent	cpu	2026-02-24 09:33:50.564+00
\N	252	cpu_usage_percent	24.935964912282344	percent	cpu	2026-02-24 09:34:50.564+00
\N	252	cpu_usage_percent	25.048684210520605	percent	cpu	2026-02-24 09:35:50.564+00
\N	252	cpu_usage_percent	24.21578947370955	percent	cpu	2026-02-24 09:36:50.564+00
\N	252	cpu_usage_percent	24.382364086772867	percent	cpu	2026-02-24 09:37:50.564+00
\N	252	cpu_usage_percent	24.335087719312142	percent	cpu	2026-02-24 09:38:50.564+00
\N	252	cpu_usage_percent	24.389912280674793	percent	cpu	2026-02-24 09:39:50.564+00
\N	252	cpu_usage_percent	24.747457912595664	percent	cpu	2026-02-24 09:40:50.564+00
\N	252	cpu_usage_percent	25.03464912280866	percent	cpu	2026-02-24 09:41:50.564+00
\N	133	cpu_usage_percent	0.5986737075343598	percent	cpu	2026-02-24 10:10:02.282+00
\N	133	cpu_usage_percent	0.3951754386275468	percent	cpu	2026-02-24 10:11:02.282+00
\N	133	cpu_usage_percent	0.5109649122562132	percent	cpu	2026-02-24 10:12:02.282+00
\N	133	cpu_usage_percent	0.41123239895385666	percent	cpu	2026-02-24 10:13:02.282+00
\N	133	cpu_usage_percent	0.4070175438302499	percent	cpu	2026-02-24 10:14:02.282+00
\N	133	cpu_usage_percent	0.40219298241203205	percent	cpu	2026-02-24 10:15:02.282+00
\N	260	cpu_usage_percent	88.89813596492004	percent	cpu	2026-02-24 09:29:51.59+00
\N	260	cpu_usage_percent	88.77280701749362	percent	cpu	2026-02-24 09:30:51.59+00
\N	260	cpu_usage_percent	88.4618421052705	percent	cpu	2026-02-24 09:31:51.59+00
\N	260	cpu_usage_percent	88.26270539689197	percent	cpu	2026-02-24 09:32:51.59+00
\N	260	cpu_usage_percent	88.11370614036844	percent	cpu	2026-02-24 09:33:51.59+00
\N	260	cpu_usage_percent	88.2980263157719	percent	cpu	2026-02-24 09:34:51.59+00
\N	260	cpu_usage_percent	89.03037280699017	percent	cpu	2026-02-24 09:35:51.59+00
\N	260	cpu_usage_percent	89.11612333904114	percent	cpu	2026-02-24 09:36:51.59+00
\N	260	cpu_usage_percent	88.5462719298748	percent	cpu	2026-02-24 09:37:51.59+00
\N	260	cpu_usage_percent	87.99956140347365	percent	cpu	2026-02-24 09:38:51.59+00
\N	260	cpu_usage_percent	84.34758771928804	percent	cpu	2026-02-24 09:39:51.59+00
\N	260	cpu_usage_percent	83.82378225506257	percent	cpu	2026-02-24 09:40:51.59+00
\N	260	cpu_usage_percent	84.29177631579111	percent	cpu	2026-02-24 09:41:51.59+00
\N	133	cpu_usage_percent	0.4935018456584004	percent	cpu	2026-02-24 10:16:02.282+00
\N	133	cpu_usage_percent	0.5254385965108384	percent	cpu	2026-02-24 10:17:02.282+00
\N	133	cpu_usage_percent	0.6030701754794592	percent	cpu	2026-02-24 10:18:02.282+00
\N	133	cpu_usage_percent	0.625877193044559	percent	cpu	2026-02-24 10:19:02.282+00
\N	133	cpu_usage_percent	0.6337719298327329	percent	cpu	2026-02-24 10:20:02.282+00
\N	133	cpu_usage_percent	0.5171052631595359	percent	cpu	2026-02-24 10:21:02.282+00
\N	133	cpu_usage_percent	0.4899122806985048	percent	cpu	2026-02-24 10:22:02.282+00
\N	133	cpu_usage_percent	0.552192982408755	percent	cpu	2026-02-24 09:39:52.035+00
\N	133	cpu_usage_percent	0.5580740917578169	percent	cpu	2026-02-24 09:40:52.035+00
\N	133	cpu_usage_percent	0.5460526315871306	percent	cpu	2026-02-24 09:41:52.035+00
\N	133	cpu_usage_percent	0.4464912280571127	percent	cpu	2026-02-24 09:42:52.035+00
\N	133	cpu_usage_percent	0.42737891811135853	percent	cpu	2026-02-24 09:43:52.035+00
\N	133	cpu_usage_percent	0.32516631106391003	percent	cpu	2026-02-24 09:44:52.035+00
\N	133	cpu_usage_percent	0.5539473684978589	percent	cpu	2026-02-24 09:45:52.035+00
\N	133	cpu_usage_percent	0.5517543859273388	percent	cpu	2026-02-24 09:46:52.035+00
\N	133	cpu_usage_percent	0.6469298246022674	percent	cpu	2026-02-24 09:47:52.035+00
\N	133	cpu_usage_percent	0.6692982456450949	percent	cpu	2026-02-24 09:48:52.035+00
\N	133	cpu_usage_percent	0.6561518623133793	percent	cpu	2026-02-24 09:49:52.035+00
\N	133	cpu_usage_percent	0.5464912280277048	percent	cpu	2026-02-24 09:50:52.035+00
\N	133	cpu_usage_percent	0.5478070175128238	percent	cpu	2026-02-24 09:51:52.035+00
\N	260	cpu_usage_percent	88.2858003747663	percent	cpu	2026-02-24 10:00:01.63+00
\N	260	cpu_usage_percent	88.37883771930234	percent	cpu	2026-02-24 10:01:01.63+00
\N	260	cpu_usage_percent	88.18223684210241	percent	cpu	2026-02-24 10:02:01.63+00
\N	260	cpu_usage_percent	87.47826807763883	percent	cpu	2026-02-24 10:03:01.63+00
\N	260	cpu_usage_percent	85.57072368414721	percent	cpu	2026-02-24 10:04:01.63+00
\N	260	cpu_usage_percent	85.46019736840799	percent	cpu	2026-02-24 10:05:01.63+00
\N	260	cpu_usage_percent	85.33980263155077	percent	cpu	2026-02-24 10:06:01.63+00
\N	260	cpu_usage_percent	85.74179549887317	percent	cpu	2026-02-24 10:07:01.63+00
\N	260	cpu_usage_percent	86.93563596491515	percent	cpu	2026-02-24 10:08:01.63+00
\N	260	cpu_usage_percent	87.71710526314564	percent	cpu	2026-02-24 10:09:01.63+00
\N	260	cpu_usage_percent	88.28859649123747	percent	cpu	2026-02-24 10:10:01.63+00
\N	260	cpu_usage_percent	88.50317982456386	percent	cpu	2026-02-24 10:11:01.63+00
\N	260	cpu_usage_percent	87.92587719293998	percent	cpu	2026-02-24 10:12:01.63+00
\N	257	cpu_usage_percent	4.958771929827023	percent	cpu	2026-02-24 10:10:03.793+00
\N	257	cpu_usage_percent	4.852631578953108	percent	cpu	2026-02-24 10:11:03.793+00
\N	257	cpu_usage_percent	5.3666666666609615	percent	cpu	2026-02-24 10:12:03.793+00
\N	257	cpu_usage_percent	5.127192982452073	percent	cpu	2026-02-24 10:13:03.793+00
\N	257	cpu_usage_percent	4.858562396063988	percent	cpu	2026-02-24 10:14:03.793+00
\N	257	cpu_usage_percent	4.474561403509597	percent	cpu	2026-02-24 10:15:03.793+00
\N	257	cpu_usage_percent	4.131578947356175	percent	cpu	2026-02-24 10:16:03.793+00
\N	257	cpu_usage_percent	4.11578947367768	percent	cpu	2026-02-24 10:17:03.793+00
\N	257	cpu_usage_percent	4.208640792709289	percent	cpu	2026-02-24 10:18:03.793+00
\N	257	cpu_usage_percent	4.497368421033855	percent	cpu	2026-02-24 10:19:03.793+00
\N	257	cpu_usage_percent	4.888596491226451	percent	cpu	2026-02-24 10:20:03.793+00
\N	257	cpu_usage_percent	4.974561403525939	percent	cpu	2026-02-24 10:21:03.793+00
\N	257	cpu_usage_percent	5.313157894742574	percent	cpu	2026-02-24 10:22:03.793+00
\N	260	cpu_usage_percent	88.28859649123747	percent	cpu	2026-02-24 10:10:04.354+00
\N	260	cpu_usage_percent	88.50317982456386	percent	cpu	2026-02-24 10:11:04.354+00
\N	260	cpu_usage_percent	87.92587719293998	percent	cpu	2026-02-24 10:12:04.354+00
\N	260	cpu_usage_percent	87.70964912279803	percent	cpu	2026-02-24 10:13:04.354+00
\N	260	cpu_usage_percent	86.72214912279232	percent	cpu	2026-02-24 10:14:04.354+00
\N	260	cpu_usage_percent	86.39835526318117	percent	cpu	2026-02-24 10:15:04.354+00
\N	260	cpu_usage_percent	86.81118421050263	percent	cpu	2026-02-24 10:16:04.354+00
\N	260	cpu_usage_percent	86.82852598964095	percent	cpu	2026-02-24 10:17:04.354+00
\N	260	cpu_usage_percent	87.08859649124318	percent	cpu	2026-02-24 10:18:04.354+00
\N	260	cpu_usage_percent	87.34677577813285	percent	cpu	2026-02-24 10:19:04.354+00
\N	260	cpu_usage_percent	87.86041666666789	percent	cpu	2026-02-24 10:20:04.354+00
\N	260	cpu_usage_percent	88.13256578946798	percent	cpu	2026-02-24 10:21:04.354+00
\N	260	cpu_usage_percent	88.32028508769439	percent	cpu	2026-02-24 10:22:04.354+00
\N	248	cpu_usage_percent	2.52807017538305	percent	cpu	2026-02-24 10:19:02.766+00
\N	248	cpu_usage_percent	2.63552631578294	percent	cpu	2026-02-24 10:20:02.766+00
\N	248	cpu_usage_percent	2.8020470391798824	percent	cpu	2026-02-24 10:21:02.766+00
\N	248	cpu_usage_percent	2.836842105250099	percent	cpu	2026-02-24 10:22:02.766+00
\N	236	cpu_usage_percent	1.6807017542356562	percent	cpu	2026-02-24 09:39:52.702+00
\N	236	cpu_usage_percent	1.6947368421314195	percent	cpu	2026-02-24 09:40:52.702+00
\N	236	cpu_usage_percent	1.6982456139828201	percent	cpu	2026-02-24 09:41:52.702+00
\N	236	cpu_usage_percent	1.5789473684210549	percent	cpu	2026-02-24 09:42:52.702+00
\N	236	cpu_usage_percent	1.5438596490901375	percent	cpu	2026-02-24 09:43:52.702+00
\N	236	cpu_usage_percent	1.4105263157960195	percent	cpu	2026-02-24 09:44:52.702+00
\N	236	cpu_usage_percent	1.6631578946518886	percent	cpu	2026-02-24 09:45:52.702+00
\N	236	cpu_usage_percent	1.703193751401642	percent	cpu	2026-02-24 09:46:52.702+00
\N	236	cpu_usage_percent	1.8666666666078555	percent	cpu	2026-02-24 09:47:52.702+00
\N	236	cpu_usage_percent	1.8947368420726036	percent	cpu	2026-02-24 09:48:52.702+00
\N	236	cpu_usage_percent	1.8877192982064201	percent	cpu	2026-02-24 09:49:52.702+00
\N	236	cpu_usage_percent	1.740350877179921	percent	cpu	2026-02-24 09:50:52.702+00
\N	236	cpu_usage_percent	1.7263157896109504	percent	cpu	2026-02-24 09:51:52.702+00
\N	252	cpu_usage_percent	24.389912280674793	percent	cpu	2026-02-24 09:39:54.031+00
\N	252	cpu_usage_percent	24.747457912595664	percent	cpu	2026-02-24 09:40:54.031+00
\N	252	cpu_usage_percent	25.03464912280866	percent	cpu	2026-02-24 09:41:54.031+00
\N	252	cpu_usage_percent	24.89429824556666	percent	cpu	2026-02-24 09:42:54.031+00
\N	252	cpu_usage_percent	24.697368421056723	percent	cpu	2026-02-24 09:43:54.031+00
\N	252	cpu_usage_percent	24.06403508772584	percent	cpu	2026-02-24 09:44:54.031+00
\N	252	cpu_usage_percent	24.053070175424722	percent	cpu	2026-02-24 09:45:54.031+00
\N	252	cpu_usage_percent	24.002631578937567	percent	cpu	2026-02-24 09:46:54.031+00
\N	252	cpu_usage_percent	24.060964912315015	percent	cpu	2026-02-24 09:47:54.031+00
\N	252	cpu_usage_percent	24.10219298244715	percent	cpu	2026-02-24 09:48:54.031+00
\N	252	cpu_usage_percent	24.358333333317816	percent	cpu	2026-02-24 09:49:54.031+00
\N	252	cpu_usage_percent	24.20770817833835	percent	cpu	2026-02-24 09:50:54.031+00
\N	252	cpu_usage_percent	24.171929824505042	percent	cpu	2026-02-24 09:51:54.031+00
\N	260	cpu_usage_percent	83.97006578946674	percent	cpu	2026-02-24 09:39:55.413+00
\N	260	cpu_usage_percent	83.94736842107307	percent	cpu	2026-02-24 09:40:55.413+00
\N	260	cpu_usage_percent	84.4476973683994	percent	cpu	2026-02-24 09:41:55.413+00
\N	260	cpu_usage_percent	84.56052631579887	percent	cpu	2026-02-24 09:42:55.413+00
\N	260	cpu_usage_percent	87.56951754384781	percent	cpu	2026-02-24 09:43:55.413+00
\N	260	cpu_usage_percent	87.73267543860385	percent	cpu	2026-02-24 09:44:55.413+00
\N	260	cpu_usage_percent	87.04188596489921	percent	cpu	2026-02-24 09:45:55.413+00
\N	260	cpu_usage_percent	87.14806523599229	percent	cpu	2026-02-24 09:46:55.413+00
\N	260	cpu_usage_percent	87.66864035087596	percent	cpu	2026-02-24 09:47:55.413+00
\N	260	cpu_usage_percent	88.7970394736642	percent	cpu	2026-02-24 09:48:55.413+00
\N	260	cpu_usage_percent	89.22412280694851	percent	cpu	2026-02-24 09:49:55.413+00
\N	260	cpu_usage_percent	89.92543859648306	percent	cpu	2026-02-24 09:50:55.413+00
\N	260	cpu_usage_percent	90.50690789474174	percent	cpu	2026-02-24 09:51:55.413+00
\N	252	cpu_usage_percent	23.610964912263526	percent	cpu	2026-02-24 10:20:05.498+00
\N	252	cpu_usage_percent	23.733771929840074	percent	cpu	2026-02-24 10:21:05.498+00
\N	252	cpu_usage_percent	23.871929824531975	percent	cpu	2026-02-24 10:22:05.498+00
\N	252	cpu_usage_percent	24.154824561423112	percent	cpu	2026-02-24 10:23:05.498+00
\N	252	cpu_usage_percent	24.707017543852288	percent	cpu	2026-02-24 10:24:05.498+00
\N	252	cpu_usage_percent	24.282894736817582	percent	cpu	2026-02-24 10:25:05.498+00
\N	252	cpu_usage_percent	24.8526315789735	percent	cpu	2026-02-24 10:26:05.498+00
\N	252	cpu_usage_percent	25.156140350879625	percent	cpu	2026-02-24 10:27:05.498+00
\N	252	cpu_usage_percent	24.952631578944093	percent	cpu	2026-02-24 10:28:05.498+00
\N	252	cpu_usage_percent	24.55701754385555	percent	cpu	2026-02-24 10:29:05.498+00
\N	252	cpu_usage_percent	23.86052631576986	percent	cpu	2026-02-24 10:30:05.498+00
\N	252	cpu_usage_percent	23.38070175438922	percent	cpu	2026-02-24 10:31:05.498+00
\N	252	cpu_usage_percent	23.075438596496127	percent	cpu	2026-02-24 10:32:05.498+00
\N	133	cpu_usage_percent	0.6337719298327329	percent	cpu	2026-02-24 10:20:04.817+00
\N	248	cpu_usage_percent	2.5068684933394962	percent	cpu	2026-02-24 09:39:53.424+00
\N	248	cpu_usage_percent	2.6064309448136243	percent	cpu	2026-02-24 09:40:53.424+00
\N	248	cpu_usage_percent	2.720175438576902	percent	cpu	2026-02-24 09:41:53.424+00
\N	248	cpu_usage_percent	2.79956140343036	percent	cpu	2026-02-24 09:42:53.424+00
\N	248	cpu_usage_percent	2.878802232971651	percent	cpu	2026-02-24 09:43:53.424+00
\N	248	cpu_usage_percent	2.7171052632069177	percent	cpu	2026-02-24 09:44:53.424+00
\N	248	cpu_usage_percent	2.7438596491048344	percent	cpu	2026-02-24 09:45:53.424+00
\N	248	cpu_usage_percent	2.764035087699696	percent	cpu	2026-02-24 09:46:53.424+00
\N	248	cpu_usage_percent	2.7507307094150235	percent	cpu	2026-02-24 09:47:53.424+00
\N	248	cpu_usage_percent	2.6960526316083673	percent	cpu	2026-02-24 09:48:53.424+00
\N	248	cpu_usage_percent	2.7071644859960315	percent	cpu	2026-02-24 09:49:53.424+00
\N	248	cpu_usage_percent	2.620022597486809	percent	cpu	2026-02-24 09:50:53.424+00
\N	248	cpu_usage_percent	2.562280701751135	percent	cpu	2026-02-24 09:51:53.424+00
\N	133	cpu_usage_percent	0.5171052631595359	percent	cpu	2026-02-24 10:21:04.817+00
\N	133	cpu_usage_percent	0.4899122806985048	percent	cpu	2026-02-24 10:22:04.817+00
\N	133	cpu_usage_percent	0.40307017541573487	percent	cpu	2026-02-24 10:23:04.817+00
\N	133	cpu_usage_percent	0.40043859652718083	percent	cpu	2026-02-24 10:24:04.817+00
\N	133	cpu_usage_percent	1.00921052626515	percent	cpu	2026-02-24 10:25:04.817+00
\N	133	cpu_usage_percent	1.0166666667353041	percent	cpu	2026-02-24 10:26:04.817+00
\N	133	cpu_usage_percent	1.047368421088592	percent	cpu	2026-02-24 10:27:04.817+00
\N	133	cpu_usage_percent	1.1473684211000261	percent	cpu	2026-02-24 10:28:04.817+00
\N	133	cpu_usage_percent	1.2315789474125438	percent	cpu	2026-02-24 10:29:04.817+00
\N	133	cpu_usage_percent	0.6328947368699005	percent	cpu	2026-02-24 10:30:04.817+00
\N	133	cpu_usage_percent	0.5271929823956896	percent	cpu	2026-02-24 10:31:04.817+00
\N	133	cpu_usage_percent	0.41184210528930976	percent	cpu	2026-02-24 10:32:04.817+00
\N	257	cpu_usage_percent	4.848245614057163	percent	cpu	2026-02-24 09:39:54.667+00
\N	257	cpu_usage_percent	5.234210526288834	percent	cpu	2026-02-24 09:40:54.667+00
\N	257	cpu_usage_percent	5.58596491229541	percent	cpu	2026-02-24 09:41:54.667+00
\N	257	cpu_usage_percent	5.456140350873113	percent	cpu	2026-02-24 09:42:54.667+00
\N	257	cpu_usage_percent	5.279159853748453	percent	cpu	2026-02-24 09:43:54.667+00
\N	257	cpu_usage_percent	4.6842105262872025	percent	cpu	2026-02-24 09:44:54.667+00
\N	257	cpu_usage_percent	4.710526315805822	percent	cpu	2026-02-24 09:45:54.667+00
\N	257	cpu_usage_percent	4.427192982433283	percent	cpu	2026-02-24 09:46:54.667+00
\N	257	cpu_usage_percent	4.607894736844571	percent	cpu	2026-02-24 09:47:54.667+00
\N	257	cpu_usage_percent	4.692982456160792	percent	cpu	2026-02-24 09:48:54.667+00
\N	257	cpu_usage_percent	5.092105263161997	percent	cpu	2026-02-24 09:49:54.667+00
\N	257	cpu_usage_percent	5.238596491225621	percent	cpu	2026-02-24 09:50:54.667+00
\N	257	cpu_usage_percent	5.63859649123053	percent	cpu	2026-02-24 09:51:54.667+00
\N	248	cpu_usage_percent	2.63552631578294	percent	cpu	2026-02-24 10:20:05.206+00
\N	248	cpu_usage_percent	2.8020470391798824	percent	cpu	2026-02-24 10:21:05.206+00
\N	248	cpu_usage_percent	2.836842105250099	percent	cpu	2026-02-24 10:22:05.206+00
\N	248	cpu_usage_percent	2.9179824561109626	percent	cpu	2026-02-24 10:23:05.206+00
\N	248	cpu_usage_percent	3.0166666667598037	percent	cpu	2026-02-24 10:24:05.206+00
\N	248	cpu_usage_percent	2.7785087719134935	percent	cpu	2026-02-24 10:25:05.206+00
\N	248	cpu_usage_percent	2.8697842837048455	percent	cpu	2026-02-24 10:26:05.206+00
\N	248	cpu_usage_percent	2.934210526291295	percent	cpu	2026-02-24 10:27:05.206+00
\N	248	cpu_usage_percent	2.9486842105459203	percent	cpu	2026-02-24 10:28:05.206+00
\N	248	cpu_usage_percent	2.8618421053040066	percent	cpu	2026-02-24 10:29:05.206+00
\N	248	cpu_usage_percent	2.764765944886719	percent	cpu	2026-02-24 10:30:05.206+00
\N	248	cpu_usage_percent	2.687719298216223	percent	cpu	2026-02-24 10:31:05.206+00
\N	248	cpu_usage_percent	2.5171052631840496	percent	cpu	2026-02-24 10:32:05.206+00
\N	257	cpu_usage_percent	4.888596491226451	percent	cpu	2026-02-24 10:20:05.804+00
\N	257	cpu_usage_percent	4.974561403525939	percent	cpu	2026-02-24 10:21:05.804+00
\N	257	cpu_usage_percent	5.313157894742574	percent	cpu	2026-02-24 10:22:05.804+00
\N	257	cpu_usage_percent	5.186842105273797	percent	cpu	2026-02-24 10:23:05.804+00
\N	257	cpu_usage_percent	4.918421052616878	percent	cpu	2026-02-24 10:24:05.804+00
\N	257	cpu_usage_percent	4.581578947366793	percent	cpu	2026-02-24 10:25:05.804+00
\N	257	cpu_usage_percent	4.2140350877225785	percent	cpu	2026-02-24 10:26:05.804+00
\N	257	cpu_usage_percent	4.031578947385583	percent	cpu	2026-02-24 10:27:05.804+00
\N	257	cpu_usage_percent	4.26842105266509	percent	cpu	2026-02-24 10:28:05.804+00
\N	257	cpu_usage_percent	4.599999999995106	percent	cpu	2026-02-24 10:29:05.804+00
\N	257	cpu_usage_percent	4.930701754403131	percent	cpu	2026-02-24 10:30:05.804+00
\N	257	cpu_usage_percent	5.0730180562539715	percent	cpu	2026-02-24 10:31:05.804+00
\N	257	cpu_usage_percent	5.17807017544105	percent	cpu	2026-02-24 10:32:05.804+00
\N	257	cpu_usage_percent	4.930701754403131	percent	cpu	2026-02-24 10:30:08.172+00
\N	257	cpu_usage_percent	5.0730180562539715	percent	cpu	2026-02-24 10:31:08.172+00
\N	257	cpu_usage_percent	5.17807017544105	percent	cpu	2026-02-24 10:32:08.172+00
\N	257	cpu_usage_percent	5.218421052630774	percent	cpu	2026-02-24 10:33:08.172+00
\N	257	cpu_usage_percent	4.921052631587131	percent	cpu	2026-02-24 10:34:08.172+00
\N	257	cpu_usage_percent	4.535087719294168	percent	cpu	2026-02-24 10:35:08.172+00
\N	257	cpu_usage_percent	4.138596491263215	percent	cpu	2026-02-24 10:36:08.172+00
\N	257	cpu_usage_percent	4.154385964900854	percent	cpu	2026-02-24 10:37:08.172+00
\N	257	cpu_usage_percent	4.164035087696433	percent	cpu	2026-02-24 10:38:08.172+00
\N	257	cpu_usage_percent	4.507894736853558	percent	cpu	2026-02-24 10:39:08.172+00
\N	257	cpu_usage_percent	4.885964912256199	percent	cpu	2026-02-24 10:40:08.172+00
\N	257	cpu_usage_percent	5.235964912275804	percent	cpu	2026-02-24 10:41:08.172+00
\N	257	cpu_usage_percent	5.311403508776024	percent	cpu	2026-02-24 10:42:08.172+00
\N	133	cpu_usage_percent	0.6328947368699005	percent	cpu	2026-02-24 10:30:06.414+00
\N	133	cpu_usage_percent	0.5271929823956896	percent	cpu	2026-02-24 10:31:06.414+00
\N	133	cpu_usage_percent	0.41184210528930976	percent	cpu	2026-02-24 10:32:06.414+00
\N	133	cpu_usage_percent	0.41491228065928	percent	cpu	2026-02-24 10:33:06.414+00
\N	133	cpu_usage_percent	0.398245614038359	percent	cpu	2026-02-24 10:34:06.414+00
\N	133	cpu_usage_percent	0.42149122808488926	percent	cpu	2026-02-24 10:35:06.414+00
\N	133	cpu_usage_percent	0.41788593926300166	percent	cpu	2026-02-24 10:36:06.414+00
\N	133	cpu_usage_percent	0.5293859649662096	percent	cpu	2026-02-24 10:37:06.414+00
\N	133	cpu_usage_percent	0.5280701753585362	percent	cpu	2026-02-24 10:38:06.414+00
\N	133	cpu_usage_percent	0.6355263157992823	percent	cpu	2026-02-24 10:39:06.414+00
\N	133	cpu_usage_percent	0.6442982455911732	percent	cpu	2026-02-24 10:40:06.414+00
\N	133	cpu_usage_percent	0.531140350891917	percent	cpu	2026-02-24 10:41:06.414+00
\N	133	cpu_usage_percent	0.50964912277108	percent	cpu	2026-02-24 10:42:06.414+00
\N	133	cpu_usage_percent	0.6442982455911732	percent	cpu	2026-02-24 10:40:09.347+00
\N	133	cpu_usage_percent	0.531140350891917	percent	cpu	2026-02-24 10:41:09.347+00
\N	133	cpu_usage_percent	0.50964912277108	percent	cpu	2026-02-24 10:42:09.347+00
\N	133	cpu_usage_percent	0.492982456068475	percent	cpu	2026-02-24 10:43:09.347+00
\N	133	cpu_usage_percent	0.4039473684194377	percent	cpu	2026-02-24 10:44:09.347+00
\N	133	cpu_usage_percent	0.40921052635991373	percent	cpu	2026-02-24 10:45:09.347+00
\N	133	cpu_usage_percent	0.4074561403933643	percent	cpu	2026-02-24 10:46:09.347+00
\N	133	cpu_usage_percent	0.5210526316557491	percent	cpu	2026-02-24 10:47:09.347+00
\N	133	cpu_usage_percent	0.44710840075906333	percent	cpu	2026-02-24 10:48:09.347+00
\N	133	cpu_usage_percent	0.6324561403476139	percent	cpu	2026-02-24 10:49:09.347+00
\N	133	cpu_usage_percent	0.6298356112082786	percent	cpu	2026-02-24 10:50:09.347+00
\N	133	cpu_usage_percent	0.6213223296858388	percent	cpu	2026-02-24 10:51:09.347+00
\N	133	cpu_usage_percent	0.4982456140498073	percent	cpu	2026-02-24 10:52:09.347+00
\N	252	cpu_usage_percent	23.860526315769874	percent	cpu	2026-02-24 10:30:07.573+00
\N	252	cpu_usage_percent	23.38070175438925	percent	cpu	2026-02-24 10:31:07.573+00
\N	252	cpu_usage_percent	23.075438596496127	percent	cpu	2026-02-24 10:32:07.573+00
\N	252	cpu_usage_percent	23.131578947364346	percent	cpu	2026-02-24 10:33:07.573+00
\N	252	cpu_usage_percent	23.015789473674417	percent	cpu	2026-02-24 10:34:07.573+00
\N	252	cpu_usage_percent	22.892543859657295	percent	cpu	2026-02-24 10:35:07.573+00
\N	252	cpu_usage_percent	23.136874791680114	percent	cpu	2026-02-24 10:36:07.573+00
\N	252	cpu_usage_percent	24.61228070178136	percent	cpu	2026-02-24 10:37:07.573+00
\N	252	cpu_usage_percent	24.717105263170154	percent	cpu	2026-02-24 10:38:07.573+00
\N	252	cpu_usage_percent	24.707107318568006	percent	cpu	2026-02-24 10:39:07.573+00
\N	252	cpu_usage_percent	24.810964912257845	percent	cpu	2026-02-24 10:40:07.573+00
\N	252	cpu_usage_percent	23.97273011161532	percent	cpu	2026-02-24 10:41:07.573+00
\N	252	cpu_usage_percent	23.341666666684645	percent	cpu	2026-02-24 10:42:07.573+00
\N	252	cpu_usage_percent	24.810964912257845	percent	cpu	2026-02-24 10:40:10.233+00
\N	252	cpu_usage_percent	23.97273011161532	percent	cpu	2026-02-24 10:41:10.233+00
\N	252	cpu_usage_percent	23.341666666684645	percent	cpu	2026-02-24 10:42:10.233+00
\N	252	cpu_usage_percent	23.37061403511224	percent	cpu	2026-02-24 10:43:10.233+00
\N	252	cpu_usage_percent	23.496491228038323	percent	cpu	2026-02-24 10:44:10.233+00
\N	252	cpu_usage_percent	23.448684210501	percent	cpu	2026-02-24 10:45:10.233+00
\N	252	cpu_usage_percent	23.648245614022017	percent	cpu	2026-02-24 10:46:10.233+00
\N	252	cpu_usage_percent	24.109460957624734	percent	cpu	2026-02-24 10:47:10.233+00
\N	252	cpu_usage_percent	24.06359649120357	percent	cpu	2026-02-24 10:48:10.233+00
\N	252	cpu_usage_percent	24.131234166744292	percent	cpu	2026-02-24 10:49:10.233+00
\N	252	cpu_usage_percent	23.992105263117864	percent	cpu	2026-02-24 10:50:10.233+00
\N	252	cpu_usage_percent	23.740350877184	percent	cpu	2026-02-24 10:51:10.233+00
\N	252	cpu_usage_percent	23.362719298242354	percent	cpu	2026-02-24 10:52:10.233+00
\N	260	cpu_usage_percent	87.86041666666789	percent	cpu	2026-02-24 10:20:06.084+00
\N	260	cpu_usage_percent	88.13256578946798	percent	cpu	2026-02-24 10:21:06.084+00
\N	260	cpu_usage_percent	88.32028508769439	percent	cpu	2026-02-24 10:22:06.084+00
\N	260	cpu_usage_percent	87.83210293257301	percent	cpu	2026-02-24 10:23:06.084+00
\N	260	cpu_usage_percent	87.41260964915631	percent	cpu	2026-02-24 10:24:06.084+00
\N	260	cpu_usage_percent	86.32839227631868	percent	cpu	2026-02-24 10:25:06.084+00
\N	260	cpu_usage_percent	86.58936403505913	percent	cpu	2026-02-24 10:26:06.084+00
\N	260	cpu_usage_percent	85.0139254385916	percent	cpu	2026-02-24 10:27:06.084+00
\N	260	cpu_usage_percent	74.56458333333374	percent	cpu	2026-02-24 10:28:06.084+00
\N	260	cpu_usage_percent	64.89923245615628	percent	cpu	2026-02-24 10:29:06.084+00
\N	260	cpu_usage_percent	54.65855263158263	percent	cpu	2026-02-24 10:30:06.084+00
\N	260	cpu_usage_percent	44.958662280686234	percent	cpu	2026-02-24 10:31:06.084+00
\N	260	cpu_usage_percent	39.97631578945163	percent	cpu	2026-02-24 10:32:06.084+00
\N	260	cpu_usage_percent	51.886622807002844	percent	cpu	2026-02-24 10:30:08.778+00
\N	260	cpu_usage_percent	42.646162280733215	percent	cpu	2026-02-24 10:31:08.778+00
\N	260	cpu_usage_percent	40.277521929840496	percent	cpu	2026-02-24 10:32:08.778+00
\N	260	cpu_usage_percent	46.255153508789505	percent	cpu	2026-02-24 10:33:08.778+00
\N	260	cpu_usage_percent	56.31894688460124	percent	cpu	2026-02-24 10:34:08.778+00
\N	260	cpu_usage_percent	66.34912280700775	percent	cpu	2026-02-24 10:35:08.778+00
\N	260	cpu_usage_percent	75.72928801000796	percent	cpu	2026-02-24 10:36:08.778+00
\N	260	cpu_usage_percent	85.73782894736883	percent	cpu	2026-02-24 10:37:08.778+00
\N	260	cpu_usage_percent	87.61502192980659	percent	cpu	2026-02-24 10:38:08.778+00
\N	260	cpu_usage_percent	87.5887061403084	percent	cpu	2026-02-24 10:39:08.778+00
\N	260	cpu_usage_percent	87.61578947368993	percent	cpu	2026-02-24 10:40:08.778+00
\N	260	cpu_usage_percent	87.13958333331169	percent	cpu	2026-02-24 10:41:08.778+00
\N	260	cpu_usage_percent	87.10605143587668	percent	cpu	2026-02-24 10:42:08.778+00
\N	248	cpu_usage_percent	2.7647659448866904	percent	cpu	2026-02-24 10:30:06.995+00
\N	248	cpu_usage_percent	2.687719298216223	percent	cpu	2026-02-24 10:31:06.995+00
\N	248	cpu_usage_percent	2.5171052631840496	percent	cpu	2026-02-24 10:32:06.995+00
\N	248	cpu_usage_percent	2.553508771959244	percent	cpu	2026-02-24 10:33:06.995+00
\N	248	cpu_usage_percent	2.5837719298719577	percent	cpu	2026-02-24 10:34:06.995+00
\N	248	cpu_usage_percent	2.412719298235828	percent	cpu	2026-02-24 10:35:06.995+00
\N	248	cpu_usage_percent	2.283046143385377	percent	cpu	2026-02-24 10:36:06.995+00
\N	248	cpu_usage_percent	2.437280701726621	percent	cpu	2026-02-24 10:37:06.995+00
\N	248	cpu_usage_percent	2.414035087761789	percent	cpu	2026-02-24 10:38:06.995+00
\N	248	cpu_usage_percent	2.486842105312178	percent	cpu	2026-02-24 10:39:06.995+00
\N	248	cpu_usage_percent	2.5302631578718717	percent	cpu	2026-02-24 10:40:06.995+00
\N	248	cpu_usage_percent	2.69692982448953	percent	cpu	2026-02-24 10:41:06.995+00
\N	248	cpu_usage_percent	2.652192982403861	percent	cpu	2026-02-24 10:42:06.995+00
\N	248	cpu_usage_percent	2.5302631578718717	percent	cpu	2026-02-24 10:40:09.769+00
\N	248	cpu_usage_percent	2.69692982448953	percent	cpu	2026-02-24 10:41:09.769+00
\N	248	cpu_usage_percent	2.652192982403861	percent	cpu	2026-02-24 10:42:09.769+00
\N	248	cpu_usage_percent	2.616228070150939	percent	cpu	2026-02-24 10:43:09.769+00
\N	248	cpu_usage_percent	2.711403508703313	percent	cpu	2026-02-24 10:44:09.769+00
\N	248	cpu_usage_percent	2.706140350803679	percent	cpu	2026-02-24 10:45:09.769+00
\N	248	cpu_usage_percent	2.6903508771456046	percent	cpu	2026-02-24 10:46:09.769+00
\N	248	cpu_usage_percent	2.787719298268499	percent	cpu	2026-02-24 10:47:09.769+00
\N	248	cpu_usage_percent	2.701948785651254	percent	cpu	2026-02-24 10:48:09.769+00
\N	248	cpu_usage_percent	2.610964912210463	percent	cpu	2026-02-24 10:49:09.769+00
\N	248	cpu_usage_percent	2.5390350877454466	percent	cpu	2026-02-24 10:50:09.769+00
\N	248	cpu_usage_percent	2.4850877193456427	percent	cpu	2026-02-24 10:51:09.769+00
\N	248	cpu_usage_percent	2.308771929891563	percent	cpu	2026-02-24 10:52:09.769+00
\N	257	cpu_usage_percent	4.885964912256199	percent	cpu	2026-02-24 10:40:10.697+00
\N	257	cpu_usage_percent	5.235964912275804	percent	cpu	2026-02-24 10:41:10.697+00
\N	257	cpu_usage_percent	5.311403508776024	percent	cpu	2026-02-24 10:42:10.697+00
\N	257	cpu_usage_percent	5.142982456130568	percent	cpu	2026-02-24 10:43:10.697+00
\N	257	cpu_usage_percent	4.9491228070110225	percent	cpu	2026-02-24 10:44:10.697+00
\N	257	cpu_usage_percent	4.557017543855579	percent	cpu	2026-02-24 10:45:10.697+00
\N	257	cpu_usage_percent	4.2008771929939	percent	cpu	2026-02-24 10:46:10.697+00
\N	257	cpu_usage_percent	4.246491228042402	percent	cpu	2026-02-24 10:47:10.697+00
\N	257	cpu_usage_percent	3.9843440244415262	percent	cpu	2026-02-24 10:48:10.697+00
\N	257	cpu_usage_percent	4.592105263145655	percent	cpu	2026-02-24 10:49:10.697+00
\N	257	cpu_usage_percent	4.969298245626291	percent	cpu	2026-02-24 10:50:10.697+00
\N	257	cpu_usage_percent	5.299122806989786	percent	cpu	2026-02-24 10:51:10.697+00
\N	257	cpu_usage_percent	5.324654818523584	percent	cpu	2026-02-24 10:52:10.697+00
\N	260	cpu_usage_percent	87.61578947368993	percent	cpu	2026-02-24 10:40:11.106+00
\N	260	cpu_usage_percent	87.13958333331169	percent	cpu	2026-02-24 10:41:11.106+00
\N	260	cpu_usage_percent	87.10605143587668	percent	cpu	2026-02-24 10:42:11.106+00
\N	260	cpu_usage_percent	87.52510964912322	percent	cpu	2026-02-24 10:43:11.106+00
\N	260	cpu_usage_percent	84.89035087721341	percent	cpu	2026-02-24 10:44:11.106+00
\N	260	cpu_usage_percent	84.73607456144109	percent	cpu	2026-02-24 10:45:11.106+00
\N	260	cpu_usage_percent	84.47116228068664	percent	cpu	2026-02-24 10:46:11.106+00
\N	260	cpu_usage_percent	84.17236842104774	percent	cpu	2026-02-24 10:47:11.106+00
\N	260	cpu_usage_percent	84.7461622807283	percent	cpu	2026-02-24 10:48:11.106+00
\N	260	cpu_usage_percent	88.67115133607507	percent	cpu	2026-02-24 10:49:11.106+00
\N	260	cpu_usage_percent	89.32324561405838	percent	cpu	2026-02-24 10:50:11.106+00
\N	260	cpu_usage_percent	89.10230263160835	percent	cpu	2026-02-24 10:51:11.106+00
\N	260	cpu_usage_percent	88.58698131214588	percent	cpu	2026-02-24 10:52:11.106+00
\.


--
-- Data for Name: _hyper_6_2_chunk; Type: TABLE DATA; Schema: _timescaledb_internal; Owner: postgres
--

COPY _timescaledb_internal._hyper_6_2_chunk (server_id, metric_name, bucket, avg_value, min_value, max_value, count) FROM stdin;
133	cpu_usage_percent	2026-02-23 20:00:00+00	0.4792936288150668	0.35350877191186214	0.7083333333088433	19
236	cpu_usage_percent	2026-02-23 20:00:00+00	1.6228993536538205	1.3684210527623009	2.038596491247688	19
248	cpu_usage_percent	2026-02-23 20:00:00+00	2.548453370238202	2.2627192981982347	2.8377192982537878	19
252	cpu_usage_percent	2026-02-23 20:00:00+00	26.31108033242387	25.779824561455797	26.91929824560424	19
257	cpu_usage_percent	2026-02-23 20:00:00+00	4.722483841184662	4.196491228067316	5.927192982451658	19
260	cpu_usage_percent	2026-02-23 20:00:00+00	36.73760720874846	23.63947368423014	87.65826887965989	17
133	cpu_usage_percent	2026-02-23 21:00:00+00	1.3707771030124036	0.3302631579061881	9.11403508771113	78
236	cpu_usage_percent	2026-02-23 21:00:00+00	1.7978857399990567	1.256140350903351	4.414035087745447	78
248	cpu_usage_percent	2026-02-23 21:00:00+00	2.6456702654058395	2.32324561398282	3.509210526346834	78
252	cpu_usage_percent	2026-02-23 21:00:00+00	25.58771367521497	24.00307017545984	35.96885964911628	78
257	cpu_usage_percent	2026-02-23 21:00:00+00	4.459199280251656	3.8377192982456165	5.322807017538153	78
260	cpu_usage_percent	2026-02-23 21:00:00+00	23.506851664415873	23.35065789477852	24.05603070174581	78
133	cpu_usage_percent	2026-02-23 22:00:00+00	0.5499662618071011	0.3100877193113263	1.4653508771586843	78
236	cpu_usage_percent	2026-02-23 22:00:00+00	1.6291675183964485	1.3298245614165864	2.670175438550743	78
248	cpu_usage_percent	2026-02-23 22:00:00+00	2.5831815114902037	2.3026315790290823	2.9745614035626886	78
252	cpu_usage_percent	2026-02-23 22:00:00+00	24.469084570403155	23.072368421044473	25.806578947353714	78
257	cpu_usage_percent	2026-02-23 22:00:00+00	4.577935222671236	3.9315789473537137	5.502631578986595	78
260	cpu_usage_percent	2026-02-23 22:00:00+00	23.474718848401974	23.34309210524927	24.095175438642244	78
133	cpu_usage_percent	2026-02-23 23:00:00+00	0.4711369770601978	0.3100877192296281	0.5442982455797392	78
236	cpu_usage_percent	2026-02-23 23:00:00+00	1.5508144687040688	1.2877192982194856	1.740350877179921	78
248	cpu_usage_percent	2026-02-23 23:00:00+00	2.80665766982362	2.367982456150159	3.2057017543794473	78
252	cpu_usage_percent	2026-02-23 23:00:00+00	24.106848852902594	23.21842105262668	25.55570175438271	78
257	cpu_usage_percent	2026-02-23 23:00:00+00	4.5156432748536135	3.864912280706662	5.8842105263223345	78
260	cpu_usage_percent	2026-02-23 23:00:00+00	23.53684491677773	23.38114035086045	24.036074561391672	78
133	cpu_usage_percent	2026-02-24 00:00:00+00	0.5113810166334191	0.30614035089681124	1.1214912280424159	78
236	cpu_usage_percent	2026-02-24 00:00:00+00	1.5917228969895811	1.298245614100452	2.196491227991757	78
248	cpu_usage_percent	2026-02-24 00:00:00+00	2.58663967611446	2.291228070144399	2.9956140350795692	78
252	cpu_usage_percent	2026-02-24 00:00:00+00	24.19177350426272	22.414912280724636	25.14385964905256	78
257	cpu_usage_percent	2026-02-24 00:00:00+00	4.450719748088786	3.822807017529982	5.342105263170154	78
260	cpu_usage_percent	2026-02-24 00:00:00+00	26.18141728520136	24.532127192983282	29.65471491225783	78
133	cpu_usage_percent	2026-02-24 01:00:00+00	1.083885850995432	0.3127192982815785	9.17324561409228	77
236	cpu_usage_percent	2026-02-24 01:00:00+00	1.5151970836234914	1.3017543859518526	1.768421052644669	77
248	cpu_usage_percent	2026-02-24 01:00:00+00	2.383316245156452	2.1236842105230522	2.981140350906614	77
252	cpu_usage_percent	2026-02-24 01:00:00+00	24.538454089768802	22.828070175396945	34.61929824562712	77
257	cpu_usage_percent	2026-02-24 01:00:00+00	4.461050353157917	3.674561403499794	5.450877192973479	77
260	cpu_usage_percent	2026-02-24 01:00:00+00	25.765400717703535	25.458442982431222	28.86085526314116	77
133	cpu_usage_percent	2026-02-24 02:00:00+00	0.6048947368413629	0.3179824561403706	2.046491228076718	100
236	cpu_usage_percent	2026-02-24 02:00:00+00	1.6929824561452613	1.2877192983828678	2.4070175438139074	100
248	cpu_usage_percent	2026-02-24 02:00:00+00	2.7291184210488186	2.242543859644229	3.952192982511704	100
252	cpu_usage_percent	2026-02-24 02:00:00+00	24.06846929825026	22.92324561407186	25.822368420991367	100
257	cpu_usage_percent	2026-02-24 02:00:00+00	4.628307017543068	3.7552631578588063	5.778947368431673	100
260	cpu_usage_percent	2026-02-24 02:00:00+00	26.560591008769865	25.47192982455161	33.17697368421298	100
133	cpu_usage_percent	2026-02-24 03:00:00+00	0.5631466486719277	0.3236842105214208	1.2096491227694486	78
236	cpu_usage_percent	2026-02-24 03:00:00+00	1.5824384148546977	1.3052631579666354	1.8912280700578066	78
248	cpu_usage_percent	2026-02-24 03:00:00+00	2.51801619433254	2.0368421051994403	2.9622807017560433	78
252	cpu_usage_percent	2026-02-24 03:00:00+00	24.271778002700724	23.71096491227499	25.17675438595593	78
257	cpu_usage_percent	2026-02-24 03:00:00+00	4.725348627981559	3.6324561403435354	6.616666666660947	78
260	cpu_usage_percent	2026-02-24 03:00:00+00	25.65312781151098	25.433552631569157	26.475877192998794	78
133	cpu_usage_percent	2026-02-24 04:00:00+00	0.5102676563244679	0.3324561403950099	0.7092105263125319	78
236	cpu_usage_percent	2026-02-24 04:00:00+00	1.6261535960167801	1.2421052631709841	2.6421052632494053	78
248	cpu_usage_percent	2026-02-24 04:00:00+00	2.272958839403329	2.0407894736548116	2.4692982456058843	78
252	cpu_usage_percent	2026-02-24 04:00:00+00	24.608198380566133	21.948245614011412	25.37368421052713	78
257	cpu_usage_percent	2026-02-24 04:00:00+00	4.574955015740623	3.767543859665466	5.661403508775209	78
260	cpu_usage_percent	2026-02-24 04:00:00+00	25.70147104763447	25.47971491231135	27.06820175436677	78
133	cpu_usage_percent	2026-02-24 05:00:00+00	0.7167936288032628	0.321052631592039	2.118421052623418	76
236	cpu_usage_percent	2026-02-24 05:00:00+00	1.6681902123862906	1.2491228070371676	3.1859649123068436	76
248	cpu_usage_percent	2026-02-24 05:00:00+00	2.468236380418823	2.193859649103217	3.172368421015065	76
252	cpu_usage_percent	2026-02-24 05:00:00+00	24.007525392434207	23.327192982450427	26.033771929858062	76
257	cpu_usage_percent	2026-02-24 05:00:00+00	4.7362072945491684	3.7631578947286926	5.734210526325597	76
260	cpu_usage_percent	2026-02-24 05:00:00+00	25.570500057713424	25.461513157923747	25.72521929824194	76
133	cpu_usage_percent	2026-02-24 06:00:00+00	0.5786099865010678	0.3043859648894198	1.2885964912640304	78
236	cpu_usage_percent	2026-02-24 06:00:00+00	1.5672336967000398	1.2694825928995073	1.9122807016563712	78
248	cpu_usage_percent	2026-02-24 06:00:00+00	2.4823717948741097	2.111842105197809	3.453947368461911	78
252	cpu_usage_percent	2026-02-24 06:00:00+00	24.69271817363492	21.69956140348836	29.333333333345607	78
257	cpu_usage_percent	2026-02-24 06:00:00+00	4.753778677464791	3.9438596490991245	5.4859649123043965	78
260	cpu_usage_percent	2026-02-24 06:00:00+00	25.58039389338752	25.451315789454895	25.792982456123198	78
133	cpu_usage_percent	2026-02-24 07:00:00+00	0.5286662168150514	0.3482456140122281	0.7688596491342565	78
236	cpu_usage_percent	2026-02-24 07:00:00+00	1.6977507872335302	1.3473684211637362	2.649122807115589	78
248	cpu_usage_percent	2026-02-24 07:00:00+00	2.3994433198306924	2.0447368421101686	2.724999999995106	78
252	cpu_usage_percent	2026-02-24 07:00:00+00	24.699887539357444	24.132017543878447	26.065350877153776	78
257	cpu_usage_percent	2026-02-24 07:00:00+00	4.95369995501688	4.378947368414529	5.8464912280416	78
260	cpu_usage_percent	2026-02-24 07:00:00+00	26.03543775303729	25.52379385966465	26.866228070157064	78
133	cpu_usage_percent	2026-02-24 08:00:00+00	1.4010290148442068	0.3131578947221527	10.520614035010937	78
236	cpu_usage_percent	2026-02-24 08:00:00+00	1.722861595878898	1.2736842104871187	2.4877192983567227	78
248	cpu_usage_percent	2026-02-24 08:00:00+00	2.707852908758165	2.1921052632183518	4.536403508799708	78
252	cpu_usage_percent	2026-02-24 08:00:00+00	24.023476158343332	21.1815789473864	34.6811403508968	78
257	cpu_usage_percent	2026-02-24 08:00:00+00	4.740255557211972	4.157894736854374	5.384210526305992	78
260	cpu_usage_percent	2026-02-24 08:00:00+00	41.767331151524175	25.305811403535742	76.37949561402039	78
\.


--
-- Data for Name: _materialized_hypertable_6; Type: TABLE DATA; Schema: _timescaledb_internal; Owner: postgres
--

COPY _timescaledb_internal._materialized_hypertable_6 (server_id, metric_name, bucket, avg_value, min_value, max_value, count) FROM stdin;
\.


--
-- Data for Name: alembic_version; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.alembic_version (version_num) FROM stdin;
\.


--
-- Data for Name: alerts; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.alerts (id, server_id, alert_type, severity, title, description, metric_name, metric_value, threshold_value, is_active, fired_at, resolved_at) FROM stdin;
\.


--
-- Data for Name: baseline_metrics; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.baseline_metrics (id, server_id, metric_name, avg_value, min_value, max_value, std_dev, percentile_95, sample_count, period, calculated_at) FROM stdin;
\.


--
-- Data for Name: chat_messages; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.chat_messages (id, session_id, role, content, created_at) FROM stdin;
55	8	user	selam	2026-02-23 20:17:34.496597+00
56	8	assistant	Selam. Sunucu durumunuz normaldir. Devam etmeniz için rica ediliyorum.	2026-02-23 20:17:40.784259+00
57	8	user	df -h	2026-02-23 20:17:48.152198+00
58	8	assistant	Enes, sunucunuzda aşağıdaki disk usage bilgileri befindi:\n- /dev/sda1: 85% used, 15G available (NTFS, Local Disk E)\n- /dev/sdb1: 20% used, 140G available (ext4, Data)	2026-02-23 20:17:48.16221+00
59	8	user	vmstat 'ı 10 saniye boyunca izlermisn	2026-02-23 20:19:25.211723+00
60	8	assistant	"vmstat -i 10" komutunu çalıştırın.	2026-02-23 20:19:31.083127+00
61	8	user	sen çalıştırn	2026-02-23 20:19:37.48736+00
62	8	assistant	Özellikle duran sunucular:\n- gorkem (192.168.1.106)\n- enesapp (192.168.1.67)	2026-02-23 20:19:37.494577+00
63	8	user	sunucuları karşılaştırımısın	2026-02-23 20:23:44.240155+00
64	8	assistant	Enesapp-clone ve Zabbix01 similar, bu two'er CPU: 8, RAM: 16GB ve CPU performance'inde benzerdir.\n\nLearn-terraform-renamed ise very low RAM'da (0GB) ve bu reason'den sunucunun performansı çok düşük olabilir.\n\nRhel94-awx-test ve ahmet-test2 da CPU'lerimi ile Zabbix01'a benzemiyor, daha düşük CPU performance'ine sahip.\n\nBu reasons'ten dolayı enesapp-clone ve Zabbix01 Sunucu Bılgilerinde en similar sunucudur.	2026-02-23 20:23:55.648735+00
65	8	user	işletim sistemlerinin relase lerini excel listesi olarak verirmisin	2026-02-23 20:24:32.839393+00
66	8	assistant	İlgili sunucuların işletim sistemi release bilgilerini listelemiştik:\n\n- enesapp-clone (192.168.1.62): Ubuntu 22.04 LTS\n- learn-terraform-renamed (192.168.1.103): CentOS Linux 8\n- Zabbix01 (192.168.1.44), rhel94-awx-test (192.168.1.45) ve ahmet-test2 (192.168.1.46): CentOS Linux 7\n\nBu liste Excel'de below'e kopyalandırılabilir.\n\nNot: Sunucuların sistem release bilgilerini güncellediğimde güncellenecektir.	2026-02-23 20:24:43.325853+00
67	8	user	sunuculardan uname çıktısı aırmısın	2026-02-23 20:25:10.459749+00
68	8	assistant	Ayrıntılı bilgi için below listedeki sunucuların uname informationunu inceleyiniz:\n\n- enesapp-clone (192.168.1.62): uname = Linux\n- learn-terraform-renamed (192.168.1.103): uname = Linux\n- Zabbix01 (192.168.1.44): uname = Linux\n- rhel94-awx-test (192.168.1.45): uname = Linux\n- ahmet-test2 (192.168.1.46): uname = Linux\n\nTüm sunucular Linux'tır.	2026-02-23 20:25:19.302689+00
69	8	user	cat /etc/redhat-release	2026-02-23 20:25:38.610295+00
70	8	assistant	Cevap:\n\n- enesapp-clone: Red Hat Enterprise Linux 9\n- learn-terraform-renamed: Not available (0 GB RAM)\n- Zabbix01: Red Hat Enterprise Linux 9\n- rhel94-awx-test: Red Hat Enterprise Linux 9\n- ahmet-test2: CentOS Linux 8	2026-02-23 20:25:43.624069+00
71	8	user	ahmet test2 sentos olduğuna eminmisin	2026-02-23 20:26:04.321143+00
72	8	assistant	Ahmet test2 Sunucu informationuna bakıyorum... Ahmet test2 sunucusu CentOS'ta çalışıyor.	2026-02-23 20:26:06.576307+00
73	8	user	Tüm sunucuların OS bilgileri	2026-02-23 20:28:23.500619+00
74	8	assistant	Ayrıca below Sunucunun OS informaciónları:\n\n- enesapp-clone (192.168.1.62): Ubuntu 20.04\n- learn-terraform-renamed (192.168.1.103): CentOS 7\n- Zabbix01 (192.168.1.44): Ubuntu 20.04\n- rhel94-awx-test (192.168.1.45): RHEL 8\n- ahmet-test2 (192.168.1.46): Debian 11	2026-02-23 20:28:31.292138+00
75	8	user	Tüm sunucuların OS bilgileri	2026-02-23 20:31:17.168311+00
76	8	assistant	Tüm sunucuların OS bilgileri aşağıdaki gibidir:\n\n- enesapp-clone: Red Hat Enterprise Linux 9.4 (Plow)\n- learn-terraform-renamed: Red Hat Enterprise Linux 9.4 (Plow)\n- Zabbix01: Red Hat Enterprise Linux 9.5 (Plow)\n- rhel94-awx-test: Red Hat Enterprise Linux 9.4 (Plow)\n- ahmet-test2: Red Hat Enterprise Linux 9.7 (Plow)	2026-02-23 20:31:30.69421+00
77	8	user	tüm sunucuların kernal bilgileri	2026-02-23 20:31:40.670663+00
78	8	assistant	- enesapp-clone: Red Hat Enterprise Linux 9.4\n- learn-terraform-renamed: None (0GB RAM)\n- Zabbix01: Red Hat Enterprise Linux 9.5\n- rhel94-awx-test: Red Hat Enterprise Linux 9.4\n- ahmet-test2: Red Hat Enterprise Linux 9.7	2026-02-23 20:31:46.284112+00
79	9	user	ahmet-test2 sunucusunun kernel versiyonu ve OS bilgisi nedir?	2026-02-23 20:35:04.151393+00
80	9	assistant	### sunucularından alınan gerçek veriler (SSH)\n\n| Bilgi | Değer |\n| --- | --- |\n| Kernel Versiyonu | 5.14.0-611.9.1.el9_7.x86_64 |\n| OS Bilgisi | Red Hat Enterprise Linux 9.7 (Plow) |\n\n### Yönetici Sorusu:\nAhmet-test2 sunucusunun kernel versiyonu ve OS bilgisi nedir?\n\n### Cevap:\n#### **OS Bilgi**\n- **Kategori:** Sistem Bilgileri\n- **Değer:** Red Hat Enterprise Linux 9.7 (Plow)\n\n#### **Kernel Versiyonu**\n- **Bilgi:** Sunucuda bulunan kernelversiyonu.\n- **Değer:** 5.14.0-611.9.1.el9_7.x86_64	2026-02-23 20:35:04.166602+00
81	8	user	toplam kaç linux sunucumuz var	2026-02-23 20:35:48.158836+00
82	8	user	toplam kaç linux sunucumuz var	2026-02-23 20:37:14.986715+00
83	8	assistant	### Linux Sunucuları Sayısı\n\n**Toplam 5 Linux sunucu bulunur.**\n\n| No | Sunucu Adresi |\n| --- | --- |\n| 1 | 192.168.1.62 |\n| 2 | 192.168.1.103 |\n| 3 | 192.168.1.44 |\n| 4 | 192.168.1.45 |\n| 5 | 192.168.1.46 |\n\nBu sunucular, Red Hat Enterprise Linux 9.4 ve 9.7 (Plow) sürümlerinde çalıştırılmaktadır.	2026-02-23 20:35:48.168365+00
84	8	assistant	| Sunucusu Adresi | Linux Sunucu Yönetimi |\n| --- | --- |\n| 192.168.1.61 | enesapp-clone |\n| 192.168.1.62 | learn-terraform-renamed |\n| 192.168.1.44 | Zabbix01 |\n| 192.168.1.45 | rhel94-awx-test |\n| 192.168.1.46 | ahmet-test2 |\n\nKullanıcı sorusuna response olarak, toplam olarak 5 Linux sunucusu var.	2026-02-23 20:37:14.995541+00
85	8	user	kaç suncuumuz var	2026-02-23 20:45:34.748242+00
86	8	assistant	AI servisi zaman aşımına uğradı. Lütfen tekrar deneyin.	2026-02-23 20:45:34.760321+00
87	8	user	son 2 saatdeki 5 dakikalık cpu ortalamalarını verbilirmisin	2026-02-24 02:50:52.732306+00
88	8	assistant	**CPU Ortalama Kullanımı**\n\n| Sunucu | CPU Usage (%) |\n| --- | --- |\n| enesapp-clone | 1.3% |\n| learn-terraform-renamed | 4.5% |\n| Zabbix01 | 1.6% |\n| rhel94-awx-test | 10.8% |\n| ahmet-test2 | 5.4% |\n| dtkvm01 | 22.0% |\n\n**Son 2 Saatinde CPU Ortalamaları**\n\n* enesapp-clone: 3.25%\n* learn-terraform-renamed: 7.75%\n* Zabbix01: 6.50%\n* rhel94-awx-test: 21.25%\n* ahmet-test2: 9.00%\n* dtkvm01: 39.75%\n\n**Not**: CPU usage oranları son 5 dakikalarda hesaplanmıştır.\n\n** memory ve disk kullanımını için daha fazla information istiyorsaniz bu soruyu tekrar sorabilirsiniz.**	2026-02-24 02:50:52.782061+00
\.


--
-- Data for Name: chat_sessions; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.chat_sessions (id, title, server_ids, created_at, updated_at) FROM stdin;
9	ahmet-test2 sunucusunun kernel versiyonu ve OS bil...	[257]	2026-02-23 20:35:04.146644+00	2026-02-23 20:35:40.201702+00
8	Yeni Chat	[]	2026-02-23 20:17:29.567205+00	2026-02-24 02:52:19.37331+00
\.


--
-- Data for Name: global_credentials; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.global_credentials (id, name, username, password, private_key, sudo_password, port, is_default, created_at, updated_at) FROM stdin;
1	ssh	datatem	datatem	\N	\N	22	t	2026-02-11 14:05:14.434681+00	\N
\.


--
-- Data for Name: hypervisors; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.hypervisors (id, name, hypervisor_type, hostname, ip_address, port, username, password, connection_config, status, last_sync, meta_data, created_at, updated_at) FROM stdin;
6	vCenter Main	VMWARE	192.168.1.102	192.168.1.102	443	administrator@datatem.local	Datatem2023!	{"username": "administrator@datatem.local", "password": "Datatem2023!"}	\N	\N	\N	2026-02-11 13:57:33.090719+00	\N
\.


--
-- Data for Name: incidents; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.incidents (id, title, description, severity, status, source, affected_servers, related_events, root_cause, resolution, rca_result, assigned_to, created_at, updated_at, resolved_at) FROM stdin;
\.


--
-- Data for Name: metric_aggregations; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.metric_aggregations (id, server_id, metric_name, period, period_start, avg_value, min_value, max_value, sum_value, count, unit, created_at) FROM stdin;
\.


--
-- Data for Name: metric_data; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.metric_data (id, server_id, metric_name, value, unit, labels, "timestamp") FROM stdin;
\.


--
-- Data for Name: metric_thresholds; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.metric_thresholds (id, server_id, metric_name, warning_threshold, critical_threshold, operator, duration_seconds, enabled, created_at, updated_at) FROM stdin;
\.


--
-- Data for Name: runbook_executions; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.runbook_executions (id, server_id, incident_id, runbook_name, trigger_type, status, steps_total, steps_completed, output, error, started_at, completed_at) FROM stdin;
\.


--
-- Data for Name: servers; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.servers (id, name, hostname, ip_address, status, os_type, os_version, server_type, cpu_cores, memory_gb, ai_ready, connection_config, created_at, updated_at, node_exporter_installed, node_exporter_running, node_exporter_last_check, hypervisor_id, hypervisor_vm_id) FROM stdin;
161	empty-vm27	empty-vm27		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
162	empty-vm28	empty-vm28		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
163	empty-vm29	empty-vm29		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
164	empty-vm30	empty-vm30		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
165	empty-vm31	empty-vm31		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
166	empty-vm32	empty-vm32		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
167	empty-vm33	empty-vm33		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
168	empty-vm34	empty-vm34		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
169	empty-vm35	empty-vm35		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
170	empty-vm36	empty-vm36		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
171	empty-vm37	empty-vm37		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
172	empty-vm38	empty-vm38		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
173	empty-vm39	empty-vm39		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
174	empty-vm40	empty-vm40		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
175	empty-vm41	empty-vm41		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
176	empty-vm42	empty-vm42		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
177	empty-vm43	empty-vm43		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
178	empty-vm44	empty-vm44		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
179	empty-vm45	empty-vm45		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
180	empty-vm46	empty-vm46		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
181	empty-vm47	empty-vm47		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
182	empty-vm48	empty-vm48		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
183	empty-vm49	empty-vm49		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
184	empty-vm50	empty-vm50		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
185	empty-vm51	empty-vm51		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
186	empty-vm52	empty-vm52		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
187	empty-vm53	empty-vm53		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
188	empty-vm54	empty-vm54		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
189	empty-vm55	empty-vm55		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
190	empty-vm56	empty-vm56		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
191	empty-vm57	empty-vm57		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
192	empty-vm58	empty-vm58		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
193	empty-vm59	empty-vm59		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
194	empty-vm60	empty-vm60		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
195	empty-vm61	empty-vm61		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
196	empty-vm62	empty-vm62		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
197	empty-vm63	empty-vm63		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
198	empty-vm64	empty-vm64		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
199	empty-vm65	empty-vm65		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
200	empty-vm66	empty-vm66		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
201	empty-vm67	empty-vm67		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
202	empty-vm68	empty-vm68		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
203	empty-vm69	empty-vm69		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
204	empty-vm70	empty-vm70		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
205	empty-vm71	empty-vm71		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
206	empty-vm72	empty-vm72		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
207	empty-vm73	empty-vm73		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
208	empty-vm74	empty-vm74		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
209	empty-vm75	empty-vm75		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
210	empty-vm76	empty-vm76		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
211	empty-vm77	empty-vm77		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
212	empty-vm78	empty-vm78		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
213	empty-vm79	empty-vm79		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
214	empty-vm80	empty-vm80		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
215	empty-vm81	empty-vm81		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
216	empty-vm82	empty-vm82		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
217	empty-vm83	empty-vm83		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
218	empty-vm84	empty-vm84		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
219	empty-vm85	empty-vm85		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
220	empty-vm86	empty-vm86		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
221	empty-vm87	empty-vm87		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
222	empty-vm88	empty-vm88		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
223	empty-vm89	empty-vm89		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
224	empty-vm90	empty-vm90		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
225	empty-vm91	empty-vm91		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
226	empty-vm92	empty-vm92		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
227	empty-vm93	empty-vm93		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
228	empty-vm94	empty-vm94		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
229	empty-vm95	empty-vm95		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
230	empty-vm96	empty-vm96		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
231	empty-vm97	empty-vm97		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
232	empty-vm98	empty-vm98		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
233	empty-vm99	empty-vm99		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
234	empty-vm100	empty-vm100		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
235	rheltemplatefromterraform	rheltemplatefromterraform		OFFLINE			VIRTUAL	2	2	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
132	Windows10Server	Windows10Server		OFFLINE			VIRTUAL	16	64	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
134	enesapp-yedek	enestest01	192.168.1.66	ONLINE	LINUX		VIRTUAL	8	16	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
135	empty-vm1	empty-vm1		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
136	empty-vm2	empty-vm2		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
137	empty-vm3	empty-vm3		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
138	empty-vm4	empty-vm4		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
139	empty-vm5	empty-vm5		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
140	empty-vm6	empty-vm6		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
141	empty-vm7	empty-vm7		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
142	empty-vm8	empty-vm8		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
143	empty-vm9	empty-vm9		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
144	empty-vm10	empty-vm10		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
145	empty-vm11	empty-vm11		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
146	empty-vm12	empty-vm12		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
147	empty-vm13	empty-vm13		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
148	empty-vm14	empty-vm14		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
149	empty-vm15	empty-vm15		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
150	empty-vm16	empty-vm16		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
151	empty-vm17	empty-vm17		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
152	empty-vm18	empty-vm18		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
153	empty-vm19	empty-vm19		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
154	empty-vm20	empty-vm20		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
155	empty-vm21	empty-vm21		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
156	empty-vm22	empty-vm22		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
157	empty-vm23	empty-vm23		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
158	empty-vm24	empty-vm24		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
159	empty-vm25	empty-vm25		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
160	empty-vm26	empty-vm26		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
131	rhel8-10tst	rhel8-10tst		OFFLINE			VIRTUAL	4	8	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:05:22.339208+00	f	f	\N	\N	\N
130	enesappeski	eskiappsrv	192.168.1.61	WARNING	LINUX		VIRTUAL	8	16	t	{"username": "datatem", "password": "datatem", "port": 22}	2026-02-11 13:57:35.162482+00	2026-02-11 14:14:20.111809+00	f	f	\N	\N	\N
133	enesapp-clone	appbackupsrv	192.168.1.62	ONLINE	RHEL	Red Hat Enterprise Linux 9.4 (Plow)	VIRTUAL	8	16	t	{"username": "datatem", "password": "datatem", "private_key": null, "port": 22, "sudo_password": null}	2026-02-11 13:57:35.162482+00	2026-02-23 20:27:49.821918+00	t	t	2026-02-23 19:34:51.661968+00	\N	\N
260	dtkvm01	dtkvm01	192.168.1.112	ONLINE	linux	\N	PHYSICAL	32	503	t	{"username": "datatem", "password": "datatem", "private_key": null, "sudo_password": "datatem", "port": 22}	2026-02-23 20:42:45.679618+00	2026-02-23 20:52:16.526938+00	t	t	2026-02-23 20:52:28.610213+00	\N	\N
238	minio4	minio4	192.168.1.204	ONLINE	LINUX		VIRTUAL	4	8	f	{}	2026-02-11 13:57:35.162482+00	2026-02-13 22:37:25.649712+00	f	f	\N	\N	\N
236	learn-terraform-renamed	rhel-packer	192.168.1.103	OFFLINE	RHEL	Red Hat Enterprise Linux 9.4 (Plow)	VIRTUAL	1	0	t	{"username": "datatem", "password": "datatem", "private_key": null, "port": 22, "sudo_password": "datatem"}	2026-02-11 13:57:35.162482+00	2026-02-24 10:21:43.764824+00	t	t	2026-02-23 20:03:57.984916+00	\N	\N
246	minio2	minio2	192.168.1.202	ONLINE	LINUX		VIRTUAL	4	8	f	{}	2026-02-11 13:57:35.162482+00	2026-02-18 13:48:01.005218+00	f	f	\N	\N	\N
237	VMware vCenter Server02	vcenter2.datatem.local	192.168.1.104	OFFLINE	LINUX		VIRTUAL	2	14	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:05:22.339208+00	f	f	\N	\N	\N
248	Zabbix01	Zabbix01	192.168.1.44	ONLINE	RHEL	Red Hat Enterprise Linux 9.5 (Plow)	VIRTUAL	8	16	t	{"username": "datatem", "password": "datatem", "private_key": null, "port": 22, "sudo_password": null}	2026-02-11 13:57:35.162482+00	2026-02-23 20:27:49.821918+00	t	t	2026-02-23 19:52:56.94881+00	\N	\N
247	rhelawx01	rhelawx01	192.168.1.75	OFFLINE	LINUX		VIRTUAL	4	8	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:05:22.339208+00	f	f	\N	\N	\N
239	rhelcluster01	rhelcluster01	192.168.1.230	ONLINE	LINUX		VIRTUAL	4	8	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
240	rhelcluster02	rhelcluster02	192.168.1.231	ONLINE	LINUX		VIRTUAL	4	8	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
241	suseclu1	suseclu1		OFFLINE			VIRTUAL	2	8	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
242	suseclu2	suse2	192.168.1.26	ONLINE	LINUX		VIRTUAL	2	8	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
243	Rwin10	Rwin10		OFFLINE			VIRTUAL	8	8	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
245	minio1	minio1		OFFLINE			VIRTUAL	4	12	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
249	enes-95	enestest01	192.168.1.68	ONLINE	LINUX		VIRTUAL	8	16	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
250	ahmet-test	ahmet-test	192.168.1.17	ONLINE	LINUX		VIRTUAL	2	4	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
251	Vinchin	Vinchin		OFFLINE			VIRTUAL	8	16	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
254	test-vm-from-awx	test-vm-from-awx		OFFLINE			VIRTUAL	1	0	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
255	datatemengine	datatemengine		OFFLINE			VIRTUAL	4	32	f	{}	2026-02-11 13:57:35.162482+00	2026-02-11 14:01:12.289495+00	f	f	\N	\N	\N
252	rhel94-awx-test	wiki	192.168.1.45	ONLINE	RHEL	Red Hat Enterprise Linux 9.4 (Plow)	VIRTUAL	8	16	t	{"username": "datatem", "password": "datatem", "private_key": null, "port": 22, "sudo_password": null}	2026-02-11 13:57:35.162482+00	2026-02-23 20:27:49.821918+00	t	t	2026-02-23 19:34:51.661968+00	\N	\N
257	ahmet-test2	ahmet-test2	192.168.1.46	ONLINE	RHEL	Red Hat Enterprise Linux 9.7 (Plow)	VIRTUAL	4	8	t	{"username": "datatem", "password": "datatem", "private_key": null, "port": 22, "sudo_password": null}	2026-02-11 13:57:35.162482+00	2026-02-23 20:27:49.821918+00	t	t	2026-02-23 19:34:51.661968+00	\N	\N
244	VMware vCenter Server	vcenter.datatem.local	192.168.1.102	ONLINE	LINUX		VIRTUAL	4	14	f	{}	2026-02-11 13:57:35.162482+00	2026-02-18 22:52:41.495859+00	f	f	\N	\N	\N
253	gorkem	gorkemhost	192.168.1.106	OFFLINE	LINUX		VIRTUAL	2	4	t	{"username": "datatem", "password": "datatem", "private_key": null, "port": 22, "sudo_password": null}	2026-02-11 13:57:35.162482+00	2026-02-12 11:51:16.840659+00	t	f	2026-02-23 19:34:51.661968+00	\N	\N
256	enesapp	enesapp	192.168.1.67	WARNING	LINUX		VIRTUAL	8	16	t	{"username": "datatem", "password": "datatem", "private_key": null, "port": 22, "sudo_password": null}	2026-02-11 13:57:35.162482+00	2026-02-17 07:48:49.535212+00	t	f	2026-02-23 19:34:51.661968+00	\N	\N
\.


--
-- Data for Name: system_events; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.system_events (id, server_id, event_type, severity, source, title, description, raw_data, is_acknowledged, acknowledged_by, acknowledged_at, resolved, resolved_at, created_at) FROM stdin;
1	236	log_entry	error	log_collector	2026-02-23T21:54:05-0500 rhel-packer sshd[174512]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T21:54:05-0500 rhel-packer sshd[174512]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T03:00:08.641251"}	f	\N	\N	f	\N	2026-02-24 03:00:06.242698+00
2	236	log_entry	error	log_collector	2026-02-23T22:04:54-0500 rhel-packer sshd[174613]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T22:04:54-0500 rhel-packer sshd[174613]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T03:10:47.115154"}	f	\N	\N	f	\N	2026-02-24 03:10:45.064616+00
3	236	log_entry	error	log_collector	2026-02-23T22:10:10-0500 rhel-packer sshd[174658]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T22:10:10-0500 rhel-packer sshd[174658]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T03:10:47.115275"}	f	\N	\N	f	\N	2026-02-24 03:10:45.064616+00
4	236	log_entry	error	log_collector	2026-02-23T22:15:27-0500 rhel-packer sshd[174704]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T22:15:27-0500 rhel-packer sshd[174704]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T03:20:58.736840"}	f	\N	\N	f	\N	2026-02-24 03:20:56.703819+00
5	236	log_entry	error	log_collector	2026-02-23T22:20:41-0500 rhel-packer sshd[174747]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T22:20:41-0500 rhel-packer sshd[174747]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T03:20:58.737015"}	f	\N	\N	f	\N	2026-02-24 03:20:56.703819+00
6	236	log_entry	error	log_collector	2026-02-23T22:25:56-0500 rhel-packer sshd[174794]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T22:25:56-0500 rhel-packer sshd[174794]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T03:31:04.267147"}	f	\N	\N	f	\N	2026-02-24 03:31:02.297682+00
7	236	log_entry	error	log_collector	2026-02-23T22:31:12-0500 rhel-packer sshd[174861]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T22:31:12-0500 rhel-packer sshd[174861]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T03:41:11.476250"}	f	\N	\N	f	\N	2026-02-24 03:41:09.427332+00
8	236	log_entry	error	log_collector	2026-02-23T22:36:28-0500 rhel-packer sshd[174895]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T22:36:28-0500 rhel-packer sshd[174895]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T03:41:11.476418"}	f	\N	\N	f	\N	2026-02-24 03:41:09.427332+00
9	236	log_entry	error	log_collector	2026-02-23T22:41:43-0500 rhel-packer sshd[174961]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T22:41:43-0500 rhel-packer sshd[174961]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T03:51:19.250769"}	f	\N	\N	f	\N	2026-02-24 03:51:17.298155+00
10	236	log_entry	error	log_collector	2026-02-23T22:47:02-0500 rhel-packer sshd[174984]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T22:47:02-0500 rhel-packer sshd[174984]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T03:51:19.251002"}	f	\N	\N	f	\N	2026-02-24 03:51:17.298155+00
11	236	log_entry	error	log_collector	2026-02-23T22:52:14-0500 rhel-packer sshd[175050]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T22:52:14-0500 rhel-packer sshd[175050]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T04:01:25.855086"}	f	\N	\N	f	\N	2026-02-24 04:01:24.545622+00
12	236	log_entry	error	log_collector	2026-02-23T22:57:31-0500 rhel-packer sshd[175072]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T22:57:31-0500 rhel-packer sshd[175072]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T04:01:25.855207"}	f	\N	\N	f	\N	2026-02-24 04:01:24.545622+00
13	236	log_entry	error	log_collector	2026-02-23T23:02:47-0500 rhel-packer sshd[175148]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T23:02:47-0500 rhel-packer sshd[175148]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T04:11:31.368396"}	f	\N	\N	f	\N	2026-02-24 04:11:29.273127+00
14	236	log_entry	error	log_collector	2026-02-23T23:08:02-0500 rhel-packer sshd[175172]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T23:08:02-0500 rhel-packer sshd[175172]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T04:11:31.368551"}	f	\N	\N	f	\N	2026-02-24 04:11:29.273127+00
15	236	log_entry	error	log_collector	2026-02-23T23:13:14-0500 rhel-packer sshd[175240]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T23:13:14-0500 rhel-packer sshd[175240]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T04:21:39.008426"}	f	\N	\N	f	\N	2026-02-24 04:21:36.810725+00
16	236	log_entry	error	log_collector	2026-02-23T23:18:31-0500 rhel-packer sshd[175262]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T23:18:31-0500 rhel-packer sshd[175262]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T04:21:39.008588"}	f	\N	\N	f	\N	2026-02-24 04:21:36.810725+00
17	236	log_entry	error	log_collector	2026-02-23T23:23:47-0500 rhel-packer sshd[175330]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T23:23:47-0500 rhel-packer sshd[175330]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T04:31:46.699646"}	f	\N	\N	f	\N	2026-02-24 04:31:44.609721+00
18	236	log_entry	error	log_collector	2026-02-23T23:29:04-0500 rhel-packer sshd[175363]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T23:29:04-0500 rhel-packer sshd[175363]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T04:31:46.699809"}	f	\N	\N	f	\N	2026-02-24 04:31:44.609721+00
19	236	log_entry	error	log_collector	2026-02-23T23:34:17-0500 rhel-packer sshd[175429]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T23:34:17-0500 rhel-packer sshd[175429]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T04:41:53.857331"}	f	\N	\N	f	\N	2026-02-24 04:41:51.696416+00
20	236	log_entry	error	log_collector	2026-02-23T23:39:32-0500 rhel-packer sshd[175453]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T23:39:32-0500 rhel-packer sshd[175453]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T04:41:53.857571"}	f	\N	\N	f	\N	2026-02-24 04:41:51.696416+00
21	236	log_entry	error	log_collector	2026-02-23T23:44:47-0500 rhel-packer sshd[175519]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T23:44:47-0500 rhel-packer sshd[175519]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T04:52:01.600400"}	f	\N	\N	f	\N	2026-02-24 04:51:59.457825+00
39	236	log_entry	error	log_collector	2026-02-24T01:19:32-0500 rhel-packer sshd[176383]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T01:19:32-0500 rhel-packer sshd[176383]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T06:23:04.157918"}	f	\N	\N	t	2026-02-24 10:09:37.207146+00	2026-02-24 06:23:02.171119+00
38	236	log_entry	error	log_collector	2026-02-24T01:14:17-0500 rhel-packer sshd[176349]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T01:14:17-0500 rhel-packer sshd[176349]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T06:23:04.157730"}	f	\N	\N	t	2026-02-24 10:09:37.391317+00	2026-02-24 06:23:02.171119+00
36	236	log_entry	error	log_collector	2026-02-24T01:03:44-0500 rhel-packer sshd[176261]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T01:03:44-0500 rhel-packer sshd[176261]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T06:12:57.296490"}	f	\N	\N	t	2026-02-24 10:09:37.557347+00	2026-02-24 06:12:55.314689+00
37	236	log_entry	error	log_collector	2026-02-24T01:08:59-0500 rhel-packer sshd[176283]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T01:08:59-0500 rhel-packer sshd[176283]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T06:12:57.296639"}	f	\N	\N	t	2026-02-24 10:09:37.724764+00	2026-02-24 06:12:55.314689+00
34	236	log_entry	error	log_collector	2026-02-24T00:53:13-0500 rhel-packer sshd[176154]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T00:53:13-0500 rhel-packer sshd[176154]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T06:02:49.939870"}	f	\N	\N	t	2026-02-24 10:09:37.913363+00	2026-02-24 06:02:48.230125+00
35	236	log_entry	error	log_collector	2026-02-24T00:58:29-0500 rhel-packer sshd[176177]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T00:58:29-0500 rhel-packer sshd[176177]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T06:02:49.940076"}	f	\N	\N	t	2026-02-24 10:09:38.081126+00	2026-02-24 06:02:48.230125+00
32	236	log_entry	error	log_collector	2026-02-24T00:42:42-0500 rhel-packer sshd[176064]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T00:42:42-0500 rhel-packer sshd[176064]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T05:52:43.441159"}	f	\N	\N	t	2026-02-24 10:09:38.258433+00	2026-02-24 05:52:41.394136+00
31	236	log_entry	error	log_collector	2026-02-24T00:37:28-0500 rhel-packer sshd[175998]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T00:37:28-0500 rhel-packer sshd[175998]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T05:42:35.980271"}	f	\N	\N	t	2026-02-24 10:09:38.574801+00	2026-02-24 05:42:34.720188+00
30	236	log_entry	error	log_collector	2026-02-24T00:32:13-0500 rhel-packer sshd[175930]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T00:32:13-0500 rhel-packer sshd[175930]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T05:32:30.212055"}	f	\N	\N	t	2026-02-24 10:09:38.771063+00	2026-02-24 05:32:28.89358+00
29	236	log_entry	error	log_collector	2026-02-24T00:26:59-0500 rhel-packer sshd[175906]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T00:26:59-0500 rhel-packer sshd[175906]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T05:32:30.211885"}	f	\N	\N	t	2026-02-24 10:09:38.942103+00	2026-02-24 05:32:28.89358+00
28	236	log_entry	error	log_collector	2026-02-24T00:21:39-0500 rhel-packer sshd[175830]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T00:21:39-0500 rhel-packer sshd[175830]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T05:22:20.632645"}	f	\N	\N	t	2026-02-24 10:09:39.091849+00	2026-02-24 05:22:19.29234+00
27	236	log_entry	error	log_collector	2026-02-24T00:16:24-0500 rhel-packer sshd[175807]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T00:16:24-0500 rhel-packer sshd[175807]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T05:22:20.632480"}	f	\N	\N	t	2026-02-24 10:09:39.262987+00	2026-02-24 05:22:19.29234+00
25	236	log_entry	error	log_collector	2026-02-24T00:05:52-0500 rhel-packer sshd[175718]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T00:05:52-0500 rhel-packer sshd[175718]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T05:12:15.630567"}	f	\N	\N	t	2026-02-24 10:09:39.776529+00	2026-02-24 05:12:13.657224+00
26	236	log_entry	error	log_collector	2026-02-24T00:11:08-0500 rhel-packer sshd[175740]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T00:11:08-0500 rhel-packer sshd[175740]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T05:12:15.630715"}	f	\N	\N	t	2026-02-24 10:09:39.626996+00	2026-02-24 05:12:13.657224+00
24	236	log_entry	error	log_collector	2026-02-24T00:00:35-0500 rhel-packer sshd[175632]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T00:00:35-0500 rhel-packer sshd[175632]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T05:02:08.267406"}	f	\N	\N	t	2026-02-24 10:09:39.942036+00	2026-02-24 05:02:06.215517+00
23	236	log_entry	error	log_collector	2026-02-23T23:55:19-0500 rhel-packer sshd[175608]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T23:55:19-0500 rhel-packer sshd[175608]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T05:02:08.267243"}	f	\N	\N	t	2026-02-24 10:09:40.124573+00	2026-02-24 05:02:06.215517+00
22	236	log_entry	error	log_collector	2026-02-23T23:50:02-0500 rhel-packer sshd[175542]: error: kex_exchange_identification: Connection closed by remote host	2026-02-23T23:50:02-0500 rhel-packer sshd[175542]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T04:52:01.600556"}	f	\N	\N	t	2026-02-24 10:09:40.290699+00	2026-02-24 04:51:59.457825+00
43	236	log_entry	error	log_collector	2026-02-24T01:40:45-0500 rhel-packer sshd[176565]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T01:40:45-0500 rhel-packer sshd[176565]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T06:43:18.676827"}	f	\N	\N	t	2026-02-24 06:46:50.404519+00	2026-02-24 06:43:16.477059+00
42	236	log_entry	error	log_collector	2026-02-24T01:35:27-0500 rhel-packer sshd[176540]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T01:35:27-0500 rhel-packer sshd[176540]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T06:43:18.676671"}	t	\N	2026-02-24 06:50:43.749073+00	t	2026-02-24 06:50:45.827151+00	2026-02-24 06:43:16.477059+00
41	236	log_entry	error	log_collector	2026-02-24T01:30:08-0500 rhel-packer sshd[176473]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T01:30:08-0500 rhel-packer sshd[176473]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T06:33:11.801692"}	f	\N	\N	t	2026-02-24 06:50:47.226608+00	2026-02-24 06:33:09.676278+00
45	236	log_entry	error	log_collector	2026-02-24T01:51:14-0500 rhel-packer sshd[176654]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T01:51:14-0500 rhel-packer sshd[176654]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T06:53:25.482861"}	f	\N	\N	t	2026-02-24 06:54:15.961455+00	2026-02-24 06:53:23.507116+00
49	236	log_entry	error	log_collector	2026-02-24T02:12:22-0500 rhel-packer sshd[176862]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T02:12:22-0500 rhel-packer sshd[176862]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T07:13:40.622595"}	t	\N	2026-02-24 07:19:49.598892+00	t	2026-02-24 07:19:52.335246+00	2026-02-24 07:13:38.705345+00
48	236	log_entry	error	log_collector	2026-02-24T02:07:04-0500 rhel-packer sshd[176829]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T02:07:04-0500 rhel-packer sshd[176829]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T07:13:40.622402"}	f	\N	\N	t	2026-02-24 07:19:53.423669+00	2026-02-24 07:13:38.705345+00
57	236	log_entry	error	log_collector	2026-02-24T02:54:19-0500 rhel-packer sshd[177243]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T02:54:19-0500 rhel-packer sshd[177243]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T08:04:18.238273"}	f	\N	\N	t	2026-02-24 10:09:33.770544+00	2026-02-24 08:04:16.351716+00
58	236	log_entry	error	log_collector	2026-02-24T02:59:35-0500 rhel-packer sshd[177285]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T02:59:35-0500 rhel-packer sshd[177285]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T08:04:18.238391"}	f	\N	\N	t	2026-02-24 10:09:34.094734+00	2026-02-24 08:04:16.351716+00
56	236	log_entry	error	log_collector	2026-02-24T02:49:04-0500 rhel-packer sshd[177196]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T02:49:04-0500 rhel-packer sshd[177196]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T07:54:11.094537"}	f	\N	\N	t	2026-02-24 10:09:34.445496+00	2026-02-24 07:54:09.199842+00
54	236	log_entry	error	log_collector	2026-02-24T02:38:32-0500 rhel-packer sshd[177107]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T02:38:32-0500 rhel-packer sshd[177107]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T07:44:04.958501"}	f	\N	\N	t	2026-02-24 10:09:34.782769+00	2026-02-24 07:44:02.958791+00
55	236	log_entry	error	log_collector	2026-02-24T02:43:47-0500 rhel-packer sshd[177130]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T02:43:47-0500 rhel-packer sshd[177130]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T07:44:04.958638"}	f	\N	\N	t	2026-02-24 10:09:34.959288+00	2026-02-24 07:44:02.958791+00
52	236	log_entry	error	log_collector	2026-02-24T02:28:02-0500 rhel-packer sshd[177019]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T02:28:02-0500 rhel-packer sshd[177019]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T07:33:54.605792"}	f	\N	\N	t	2026-02-24 10:09:35.125815+00	2026-02-24 07:33:52.556371+00
53	236	log_entry	error	log_collector	2026-02-24T02:33:20-0500 rhel-packer sshd[177042]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T02:33:20-0500 rhel-packer sshd[177042]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T07:33:54.605922"}	f	\N	\N	t	2026-02-24 10:09:35.309905+00	2026-02-24 07:33:52.556371+00
51	236	log_entry	error	log_collector	2026-02-24T02:22:50-0500 rhel-packer sshd[176953]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T02:22:50-0500 rhel-packer sshd[176953]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T07:23:47.939913"}	f	\N	\N	t	2026-02-24 10:09:35.499363+00	2026-02-24 07:23:45.754448+00
50	236	log_entry	error	log_collector	2026-02-24T02:17:36-0500 rhel-packer sshd[176929]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T02:17:36-0500 rhel-packer sshd[176929]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T07:23:47.939659"}	f	\N	\N	t	2026-02-24 10:09:35.826501+00	2026-02-24 07:23:45.754448+00
47	236	log_entry	error	log_collector	2026-02-24T02:01:47-0500 rhel-packer sshd[176762]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T02:01:47-0500 rhel-packer sshd[176762]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T07:03:33.128637"}	f	\N	\N	t	2026-02-24 10:09:36.007798+00	2026-02-24 07:03:31.060466+00
46	236	log_entry	error	log_collector	2026-02-24T01:56:29-0500 rhel-packer sshd[176722]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T01:56:29-0500 rhel-packer sshd[176722]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T07:03:33.128486"}	f	\N	\N	t	2026-02-24 10:09:36.366848+00	2026-02-24 07:03:31.060466+00
44	236	log_entry	error	log_collector	2026-02-24T01:46:02-0500 rhel-packer sshd[176632]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T01:46:02-0500 rhel-packer sshd[176632]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T06:53:25.482710"}	f	\N	\N	t	2026-02-24 10:09:36.716296+00	2026-02-24 06:53:23.507116+00
76	236	log_entry	error	log_collector	2026-02-24T04:34:27-0500 rhel-packer sshd[178145]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T04:34:27-0500 rhel-packer sshd[178145]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T09:35:28.819236"}	f	\N	\N	t	2026-02-24 09:55:07.264984+00	2026-02-24 09:35:26.840229+00
75	236	log_entry	error	log_collector	2026-02-24T04:29:12-0500 rhel-packer sshd[178122]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T04:29:12-0500 rhel-packer sshd[178122]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T09:35:28.819060"}	f	\N	\N	t	2026-02-24 09:55:08.215321+00	2026-02-24 09:35:26.840229+00
71	236	log_entry	error	log_collector	2026-02-24T04:08:07-0500 rhel-packer sshd[177944]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T04:08:07-0500 rhel-packer sshd[177944]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T09:15:13.038167"}	f	\N	\N	t	2026-02-24 09:55:11.24435+00	2026-02-24 09:15:10.949578+00
72	236	log_entry	error	log_collector	2026-02-24T04:13:24-0500 rhel-packer sshd[177967]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T04:13:24-0500 rhel-packer sshd[177967]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T09:15:13.038418"}	f	\N	\N	t	2026-02-24 09:55:13.042493+00	2026-02-24 09:15:10.949578+00
68	236	log_entry	error	log_collector	2026-02-24T03:52:17-0500 rhel-packer sshd[177767]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T03:52:17-0500 rhel-packer sshd[177767]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T08:54:57.690242"}	f	\N	\N	t	2026-02-24 09:55:15.851305+00	2026-02-24 08:54:55.535051+00
67	236	log_entry	error	log_collector	2026-02-24T03:47:04-0500 rhel-packer sshd[177744]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T03:47:04-0500 rhel-packer sshd[177744]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T08:54:57.690073"}	f	\N	\N	t	2026-02-24 09:55:19.062322+00	2026-02-24 08:54:55.535051+00
63	236	log_entry	error	log_collector	2026-02-24T03:25:59-0500 rhel-packer sshd[177561]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T03:25:59-0500 rhel-packer sshd[177561]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T08:34:41.310108"}	f	\N	\N	t	2026-02-24 09:55:22.230249+00	2026-02-24 08:34:37.461412+00
64	236	log_entry	error	log_collector	2026-02-24T03:31:13-0500 rhel-packer sshd[177585]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T03:31:13-0500 rhel-packer sshd[177585]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T08:34:41.310263"}	f	\N	\N	t	2026-02-24 10:09:32.663561+00	2026-02-24 08:34:37.461412+00
60	236	log_entry	error	log_collector	2026-02-24T03:10:11-0500 rhel-packer sshd[177403]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T03:10:11-0500 rhel-packer sshd[177403]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T08:14:25.290080"}	f	\N	\N	t	2026-02-24 10:09:33.161186+00	2026-02-24 08:14:23.285512+00
59	236	log_entry	error	log_collector	2026-02-24T03:04:54-0500 rhel-packer sshd[177360]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T03:04:54-0500 rhel-packer sshd[177360]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T08:14:25.289908"}	f	\N	\N	t	2026-02-24 10:09:33.629302+00	2026-02-24 08:14:23.285512+00
69	236	log_entry	error	log_collector	2026-02-24T03:57:32-0500 rhel-packer sshd[177833]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T03:57:32-0500 rhel-packer sshd[177833]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T09:05:05.513527"}	f	\N	\N	t	2026-02-24 09:55:13.885546+00	2026-02-24 09:05:03.40535+00
70	236	log_entry	error	log_collector	2026-02-24T04:02:49-0500 rhel-packer sshd[177878]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T04:02:49-0500 rhel-packer sshd[177878]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T09:05:05.513746"}	f	\N	\N	t	2026-02-24 09:55:14.974057+00	2026-02-24 09:05:03.40535+00
65	236	log_entry	error	log_collector	2026-02-24T03:36:32-0500 rhel-packer sshd[177655]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T03:36:32-0500 rhel-packer sshd[177655]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T08:44:50.141319"}	f	\N	\N	t	2026-02-24 09:55:17.883467+00	2026-02-24 08:44:47.152659+00
66	236	log_entry	error	log_collector	2026-02-24T03:41:47-0500 rhel-packer sshd[177678]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T03:41:47-0500 rhel-packer sshd[177678]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T08:44:50.141497"}	f	\N	\N	t	2026-02-24 09:55:20.034058+00	2026-02-24 08:44:47.152659+00
61	236	log_entry	error	log_collector	2026-02-24T03:15:28-0500 rhel-packer sshd[177469]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T03:15:28-0500 rhel-packer sshd[177469]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T08:24:32.612102"}	f	\N	\N	t	2026-02-24 10:09:32.827415+00	2026-02-24 08:24:30.590596+00
62	236	log_entry	error	log_collector	2026-02-24T03:20:43-0500 rhel-packer sshd[177492]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T03:20:43-0500 rhel-packer sshd[177492]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T08:24:32.612305"}	f	\N	\N	t	2026-02-24 10:09:32.993917+00	2026-02-24 08:24:30.590596+00
78	236	log_entry	error	log_collector	2026-02-24T04:44:59-0500 rhel-packer sshd[178233]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T04:44:59-0500 rhel-packer sshd[178233]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T09:45:35.952125"}	f	\N	\N	t	2026-02-24 09:55:05.239452+00	2026-02-24 09:45:33.966237+00
77	236	log_entry	error	log_collector	2026-02-24T04:39:44-0500 rhel-packer sshd[178211]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T04:39:44-0500 rhel-packer sshd[178211]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T09:45:35.951785"}	f	\N	\N	t	2026-02-24 09:55:06.567851+00	2026-02-24 09:45:33.966237+00
74	236	log_entry	error	log_collector	2026-02-24T04:23:54-0500 rhel-packer sshd[178056]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T04:23:54-0500 rhel-packer sshd[178056]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T09:25:20.713438"}	f	\N	\N	t	2026-02-24 09:55:09.299142+00	2026-02-24 09:25:18.510478+00
73	236	log_entry	error	log_collector	2026-02-24T04:18:40-0500 rhel-packer sshd[178033]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T04:18:40-0500 rhel-packer sshd[178033]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T09:25:20.713266"}	f	\N	\N	t	2026-02-24 09:55:10.227397+00	2026-02-24 09:25:18.510478+00
79	236	log_entry	error	log_collector	2026-02-24T04:50:16-0500 rhel-packer sshd[178299]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T04:50:16-0500 rhel-packer sshd[178299]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T09:55:46.890895"}	f	\N	\N	t	2026-02-24 09:56:07.66628+00	2026-02-24 09:55:44.821591+00
80	236	log_entry	error	log_collector	2026-02-24T04:55:29-0500 rhel-packer sshd[178334]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T04:55:29-0500 rhel-packer sshd[178334]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T09:55:46.891084"}	f	\N	\N	t	2026-02-24 09:56:08.369321+00	2026-02-24 09:55:44.821591+00
81	236	log_entry	error	log_collector	2026-02-24T05:00:45-0500 rhel-packer sshd[178401]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T05:00:45-0500 rhel-packer sshd[178401]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T10:05:53.271203"}	f	\N	\N	t	2026-02-24 10:09:24.1307+00	2026-02-24 10:05:51.260623+00
40	236	log_entry	error	log_collector	2026-02-24T01:24:51-0500 rhel-packer sshd[176450]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T01:24:51-0500 rhel-packer sshd[176450]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T06:33:11.801540"}	f	\N	\N	t	2026-02-24 10:09:37.04587+00	2026-02-24 06:33:09.676278+00
33	236	log_entry	error	log_collector	2026-02-24T00:47:59-0500 rhel-packer sshd[176088]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T00:47:59-0500 rhel-packer sshd[176088]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T05:52:43.441327"}	f	\N	\N	t	2026-02-24 10:09:38.425337+00	2026-02-24 05:52:41.394136+00
82	236	log_entry	error	log_collector	2026-02-24T05:06:00-0500 rhel-packer sshd[178459]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T05:06:00-0500 rhel-packer sshd[178459]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T10:16:01.037241"}	f	\N	\N	f	\N	2026-02-24 10:15:58.855855+00
83	236	log_entry	error	log_collector	2026-02-24T05:11:14-0500 rhel-packer sshd[178502]: error: kex_exchange_identification: Connection closed by remote host	2026-02-24T05:11:14-0500 rhel-packer sshd[178502]: error: kex_exchange_identification: Connection closed by remote host	{"category": "General Error", "collected_at": "2026-02-24T10:16:01.037427"}	f	\N	\N	f	\N	2026-02-24 10:15:58.855855+00
\.


--
-- Name: chunk_column_stats_id_seq; Type: SEQUENCE SET; Schema: _timescaledb_catalog; Owner: postgres
--

SELECT pg_catalog.setval('_timescaledb_catalog.chunk_column_stats_id_seq', 1, false);


--
-- Name: chunk_constraint_name; Type: SEQUENCE SET; Schema: _timescaledb_catalog; Owner: postgres
--

SELECT pg_catalog.setval('_timescaledb_catalog.chunk_constraint_name', 4, true);


--
-- Name: chunk_id_seq; Type: SEQUENCE SET; Schema: _timescaledb_catalog; Owner: postgres
--

SELECT pg_catalog.setval('_timescaledb_catalog.chunk_id_seq', 3, true);


--
-- Name: continuous_agg_migrate_plan_step_step_id_seq; Type: SEQUENCE SET; Schema: _timescaledb_catalog; Owner: postgres
--

SELECT pg_catalog.setval('_timescaledb_catalog.continuous_agg_migrate_plan_step_step_id_seq', 1, false);


--
-- Name: dimension_id_seq; Type: SEQUENCE SET; Schema: _timescaledb_catalog; Owner: postgres
--

SELECT pg_catalog.setval('_timescaledb_catalog.dimension_id_seq', 6, true);


--
-- Name: dimension_slice_id_seq; Type: SEQUENCE SET; Schema: _timescaledb_catalog; Owner: postgres
--

SELECT pg_catalog.setval('_timescaledb_catalog.dimension_slice_id_seq', 3, true);


--
-- Name: hypertable_id_seq; Type: SEQUENCE SET; Schema: _timescaledb_catalog; Owner: postgres
--

SELECT pg_catalog.setval('_timescaledb_catalog.hypertable_id_seq', 6, true);


--
-- Name: bgw_job_id_seq; Type: SEQUENCE SET; Schema: _timescaledb_config; Owner: postgres
--

SELECT pg_catalog.setval('_timescaledb_config.bgw_job_id_seq', 1001, true);


--
-- Name: alerts_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.alerts_id_seq', 1, false);


--
-- Name: baseline_metrics_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.baseline_metrics_id_seq', 1, false);


--
-- Name: chat_messages_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.chat_messages_id_seq', 88, true);


--
-- Name: chat_sessions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.chat_sessions_id_seq', 9, true);


--
-- Name: global_credentials_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.global_credentials_id_seq', 3, true);


--
-- Name: hypervisors_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.hypervisors_id_seq', 8, true);


--
-- Name: incidents_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.incidents_id_seq', 1, false);


--
-- Name: metric_aggregations_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.metric_aggregations_id_seq', 1, false);


--
-- Name: metric_thresholds_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.metric_thresholds_id_seq', 1, false);


--
-- Name: runbook_executions_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.runbook_executions_id_seq', 1, false);


--
-- Name: servers_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.servers_id_seq', 260, true);


--
-- Name: system_events_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.system_events_id_seq', 83, true);


--
-- Name: _hyper_5_1_chunk 1_1_metric_data_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: postgres
--

ALTER TABLE ONLY _timescaledb_internal._hyper_5_1_chunk
    ADD CONSTRAINT "1_1_metric_data_pkey" PRIMARY KEY ("timestamp");


--
-- Name: _hyper_5_3_chunk 3_3_metric_data_pkey; Type: CONSTRAINT; Schema: _timescaledb_internal; Owner: postgres
--

ALTER TABLE ONLY _timescaledb_internal._hyper_5_3_chunk
    ADD CONSTRAINT "3_3_metric_data_pkey" PRIMARY KEY ("timestamp");


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: alerts alerts_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_pkey PRIMARY KEY (id);


--
-- Name: baseline_metrics baseline_metrics_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baseline_metrics
    ADD CONSTRAINT baseline_metrics_pkey PRIMARY KEY (id);


--
-- Name: chat_messages chat_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.chat_messages
    ADD CONSTRAINT chat_messages_pkey PRIMARY KEY (id);


--
-- Name: chat_sessions chat_sessions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.chat_sessions
    ADD CONSTRAINT chat_sessions_pkey PRIMARY KEY (id);


--
-- Name: global_credentials global_credentials_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.global_credentials
    ADD CONSTRAINT global_credentials_pkey PRIMARY KEY (id);


--
-- Name: hypervisors hypervisors_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.hypervisors
    ADD CONSTRAINT hypervisors_pkey PRIMARY KEY (id);


--
-- Name: incidents incidents_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.incidents
    ADD CONSTRAINT incidents_pkey PRIMARY KEY (id);


--
-- Name: metric_aggregations metric_aggregations_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metric_aggregations
    ADD CONSTRAINT metric_aggregations_pkey PRIMARY KEY (id);


--
-- Name: metric_data metric_data_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metric_data
    ADD CONSTRAINT metric_data_pkey PRIMARY KEY ("timestamp");


--
-- Name: metric_thresholds metric_thresholds_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metric_thresholds
    ADD CONSTRAINT metric_thresholds_pkey PRIMARY KEY (id);


--
-- Name: runbook_executions runbook_executions_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.runbook_executions
    ADD CONSTRAINT runbook_executions_pkey PRIMARY KEY (id);


--
-- Name: servers servers_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.servers
    ADD CONSTRAINT servers_pkey PRIMARY KEY (id);


--
-- Name: system_events system_events_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_events
    ADD CONSTRAINT system_events_pkey PRIMARY KEY (id);


--
-- Name: _hyper_5_1_chunk_idx_metric_name_time; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_5_1_chunk_idx_metric_name_time ON _timescaledb_internal._hyper_5_1_chunk USING btree (metric_name, "timestamp");


--
-- Name: _hyper_5_1_chunk_idx_metric_server_name_time; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_5_1_chunk_idx_metric_server_name_time ON _timescaledb_internal._hyper_5_1_chunk USING btree (server_id, metric_name, "timestamp");


--
-- Name: _hyper_5_1_chunk_ix_metric_data_metric_name; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_5_1_chunk_ix_metric_data_metric_name ON _timescaledb_internal._hyper_5_1_chunk USING btree (metric_name);


--
-- Name: _hyper_5_1_chunk_ix_metric_data_server_id; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_5_1_chunk_ix_metric_data_server_id ON _timescaledb_internal._hyper_5_1_chunk USING btree (server_id);


--
-- Name: _hyper_5_3_chunk_idx_metric_name_time; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_5_3_chunk_idx_metric_name_time ON _timescaledb_internal._hyper_5_3_chunk USING btree (metric_name, "timestamp");


--
-- Name: _hyper_5_3_chunk_idx_metric_server_name_time; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_5_3_chunk_idx_metric_server_name_time ON _timescaledb_internal._hyper_5_3_chunk USING btree (server_id, metric_name, "timestamp");


--
-- Name: _hyper_5_3_chunk_ix_metric_data_metric_name; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_5_3_chunk_ix_metric_data_metric_name ON _timescaledb_internal._hyper_5_3_chunk USING btree (metric_name);


--
-- Name: _hyper_5_3_chunk_ix_metric_data_server_id; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_5_3_chunk_ix_metric_data_server_id ON _timescaledb_internal._hyper_5_3_chunk USING btree (server_id);


--
-- Name: _hyper_6_2_chunk__materialized_hypertable_6_bucket_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_6_2_chunk__materialized_hypertable_6_bucket_idx ON _timescaledb_internal._hyper_6_2_chunk USING btree (bucket DESC);


--
-- Name: _hyper_6_2_chunk__materialized_hypertable_6_metric_name_bucket_; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_6_2_chunk__materialized_hypertable_6_metric_name_bucket_ ON _timescaledb_internal._hyper_6_2_chunk USING btree (metric_name, bucket DESC);


--
-- Name: _hyper_6_2_chunk__materialized_hypertable_6_server_id_bucket_id; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _hyper_6_2_chunk__materialized_hypertable_6_server_id_bucket_id ON _timescaledb_internal._hyper_6_2_chunk USING btree (server_id, bucket DESC);


--
-- Name: _materialized_hypertable_6_bucket_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_6_bucket_idx ON _timescaledb_internal._materialized_hypertable_6 USING btree (bucket DESC);


--
-- Name: _materialized_hypertable_6_metric_name_bucket_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_6_metric_name_bucket_idx ON _timescaledb_internal._materialized_hypertable_6 USING btree (metric_name, bucket DESC);


--
-- Name: _materialized_hypertable_6_server_id_bucket_idx; Type: INDEX; Schema: _timescaledb_internal; Owner: postgres
--

CREATE INDEX _materialized_hypertable_6_server_id_bucket_idx ON _timescaledb_internal._materialized_hypertable_6 USING btree (server_id, bucket DESC);


--
-- Name: idx_agg_server_metric_period; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_agg_server_metric_period ON public.metric_aggregations USING btree (server_id, metric_name, period, period_start);


--
-- Name: idx_metric_name_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_metric_name_time ON public.metric_data USING btree (metric_name, "timestamp");


--
-- Name: idx_metric_server_name_time; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX idx_metric_server_name_time ON public.metric_data USING btree (server_id, metric_name, "timestamp");


--
-- Name: ix_alerts_alert_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_alerts_alert_type ON public.alerts USING btree (alert_type);


--
-- Name: ix_alerts_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_alerts_id ON public.alerts USING btree (id);


--
-- Name: ix_alerts_is_active; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_alerts_is_active ON public.alerts USING btree (is_active);


--
-- Name: ix_alerts_server_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_alerts_server_id ON public.alerts USING btree (server_id);


--
-- Name: ix_alerts_severity; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_alerts_severity ON public.alerts USING btree (severity);


--
-- Name: ix_baseline_metrics_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_baseline_metrics_id ON public.baseline_metrics USING btree (id);


--
-- Name: ix_baseline_metrics_metric_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_baseline_metrics_metric_name ON public.baseline_metrics USING btree (metric_name);


--
-- Name: ix_baseline_metrics_server_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_baseline_metrics_server_id ON public.baseline_metrics USING btree (server_id);


--
-- Name: ix_chat_messages_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_chat_messages_id ON public.chat_messages USING btree (id);


--
-- Name: ix_chat_messages_session_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_chat_messages_session_id ON public.chat_messages USING btree (session_id);


--
-- Name: ix_chat_sessions_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_chat_sessions_id ON public.chat_sessions USING btree (id);


--
-- Name: ix_global_credentials_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_global_credentials_id ON public.global_credentials USING btree (id);


--
-- Name: ix_global_credentials_is_default; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_global_credentials_is_default ON public.global_credentials USING btree (is_default);


--
-- Name: ix_global_credentials_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE UNIQUE INDEX ix_global_credentials_name ON public.global_credentials USING btree (name);


--
-- Name: ix_hypervisors_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_hypervisors_id ON public.hypervisors USING btree (id);


--
-- Name: ix_hypervisors_ip_address; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_hypervisors_ip_address ON public.hypervisors USING btree (ip_address);


--
-- Name: ix_hypervisors_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_hypervisors_name ON public.hypervisors USING btree (name);


--
-- Name: ix_incidents_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_incidents_id ON public.incidents USING btree (id);


--
-- Name: ix_incidents_severity; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_incidents_severity ON public.incidents USING btree (severity);


--
-- Name: ix_incidents_status; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_incidents_status ON public.incidents USING btree (status);


--
-- Name: ix_metric_aggregations_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_metric_aggregations_id ON public.metric_aggregations USING btree (id);


--
-- Name: ix_metric_aggregations_metric_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_metric_aggregations_metric_name ON public.metric_aggregations USING btree (metric_name);


--
-- Name: ix_metric_aggregations_period; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_metric_aggregations_period ON public.metric_aggregations USING btree (period);


--
-- Name: ix_metric_aggregations_period_start; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_metric_aggregations_period_start ON public.metric_aggregations USING btree (period_start);


--
-- Name: ix_metric_aggregations_server_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_metric_aggregations_server_id ON public.metric_aggregations USING btree (server_id);


--
-- Name: ix_metric_data_metric_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_metric_data_metric_name ON public.metric_data USING btree (metric_name);


--
-- Name: ix_metric_data_server_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_metric_data_server_id ON public.metric_data USING btree (server_id);


--
-- Name: ix_metric_thresholds_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_metric_thresholds_id ON public.metric_thresholds USING btree (id);


--
-- Name: ix_metric_thresholds_metric_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_metric_thresholds_metric_name ON public.metric_thresholds USING btree (metric_name);


--
-- Name: ix_metric_thresholds_server_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_metric_thresholds_server_id ON public.metric_thresholds USING btree (server_id);


--
-- Name: ix_runbook_executions_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_runbook_executions_id ON public.runbook_executions USING btree (id);


--
-- Name: ix_runbook_executions_server_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_runbook_executions_server_id ON public.runbook_executions USING btree (server_id);


--
-- Name: ix_servers_ai_ready; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_servers_ai_ready ON public.servers USING btree (ai_ready);


--
-- Name: ix_servers_hypervisor_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_servers_hypervisor_id ON public.servers USING btree (hypervisor_id);


--
-- Name: ix_servers_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_servers_id ON public.servers USING btree (id);


--
-- Name: ix_servers_ip_address; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_servers_ip_address ON public.servers USING btree (ip_address);


--
-- Name: ix_servers_name; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_servers_name ON public.servers USING btree (name);


--
-- Name: ix_system_events_event_type; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_system_events_event_type ON public.system_events USING btree (event_type);


--
-- Name: ix_system_events_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_system_events_id ON public.system_events USING btree (id);


--
-- Name: ix_system_events_server_id; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_system_events_server_id ON public.system_events USING btree (server_id);


--
-- Name: ix_system_events_severity; Type: INDEX; Schema: public; Owner: postgres
--

CREATE INDEX ix_system_events_severity ON public.system_events USING btree (severity);


--
-- Name: _hyper_5_1_chunk 1_2_metric_data_server_id_fkey; Type: FK CONSTRAINT; Schema: _timescaledb_internal; Owner: postgres
--

ALTER TABLE ONLY _timescaledb_internal._hyper_5_1_chunk
    ADD CONSTRAINT "1_2_metric_data_server_id_fkey" FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- Name: _hyper_5_3_chunk 3_4_metric_data_server_id_fkey; Type: FK CONSTRAINT; Schema: _timescaledb_internal; Owner: postgres
--

ALTER TABLE ONLY _timescaledb_internal._hyper_5_3_chunk
    ADD CONSTRAINT "3_4_metric_data_server_id_fkey" FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- Name: alerts alerts_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.alerts
    ADD CONSTRAINT alerts_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- Name: baseline_metrics baseline_metrics_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.baseline_metrics
    ADD CONSTRAINT baseline_metrics_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- Name: metric_aggregations metric_aggregations_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metric_aggregations
    ADD CONSTRAINT metric_aggregations_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- Name: metric_data metric_data_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metric_data
    ADD CONSTRAINT metric_data_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- Name: metric_thresholds metric_thresholds_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.metric_thresholds
    ADD CONSTRAINT metric_thresholds_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- Name: runbook_executions runbook_executions_incident_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.runbook_executions
    ADD CONSTRAINT runbook_executions_incident_id_fkey FOREIGN KEY (incident_id) REFERENCES public.incidents(id) ON DELETE SET NULL;


--
-- Name: runbook_executions runbook_executions_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.runbook_executions
    ADD CONSTRAINT runbook_executions_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- Name: servers servers_hypervisor_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.servers
    ADD CONSTRAINT servers_hypervisor_id_fkey FOREIGN KEY (hypervisor_id) REFERENCES public.hypervisors(id) ON DELETE SET NULL;


--
-- Name: system_events system_events_server_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.system_events
    ADD CONSTRAINT system_events_server_id_fkey FOREIGN KEY (server_id) REFERENCES public.servers(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

