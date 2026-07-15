-- Linux NL Inventory Query schema (dokümantasyon + offline kurulum)
-- Runtime: SQLAlchemy create_all + main.py idempotent ALTER/INDEX

CREATE TABLE IF NOT EXISTS linux_inventory (
    id SERIAL PRIMARY KEY,
    server_id INTEGER NOT NULL UNIQUE REFERENCES servers(id) ON DELETE CASCADE,
    fqdn VARCHAR(500),
    datacenter VARCHAR(100),
    application VARCHAR(255),
    application_owner VARCHAR(255),
    uptime_seconds BIGINT,
    boot_time TIMESTAMPTZ,
    cpu_usage_percent NUMERIC(5,2),
    memory_usage_percent NUMERIC(5,2),
    disk_usage_percent NUMERIC(5,2),
    load_average_1m NUMERIC(10,2),
    load_average_5m NUMERIC(10,2),
    load_average_15m NUMERIC(10,2),
    last_patch_date TIMESTAMPTZ,
    last_reboot_date TIMESTAMPTZ,
    collection_time TIMESTAMPTZ NOT NULL,
    collection_status VARCHAR(30),
    collection_error TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS filesystem_metrics (
    id SERIAL PRIMARY KEY,
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    device VARCHAR(255),
    mount_point VARCHAR(500),
    filesystem_type VARCHAR(100),
    total_bytes BIGINT,
    used_bytes BIGINT,
    available_bytes BIGINT,
    usage_percent NUMERIC(5,2),
    collection_time TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS service_status (
    id SERIAL PRIMARY KEY,
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    service_name VARCHAR(255) NOT NULL,
    active_state VARCHAR(50),
    sub_state VARCHAR(50),
    enabled BOOLEAN,
    collection_time TIMESTAMPTZ NOT NULL,
    UNIQUE (server_id, service_name)
);

CREATE TABLE IF NOT EXISTS package_inventory (
    id SERIAL PRIMARY KEY,
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    package_name VARCHAR(255) NOT NULL,
    package_version VARCHAR(255),
    package_release VARCHAR(100),
    architecture VARCHAR(50),
    collection_time TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS open_ports (
    id SERIAL PRIMARY KEY,
    server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
    protocol VARCHAR(20),
    local_address VARCHAR(255),
    port INTEGER,
    process_name VARCHAR(255),
    pid INTEGER,
    collection_time TIMESTAMPTZ NOT NULL
);

CREATE TABLE IF NOT EXISTS nlq_query_audit (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    username VARCHAR(64),
    original_question TEXT NOT NULL,
    generated_query_json JSONB,
    executed_sql_template TEXT,
    query_parameters JSONB,
    result_count INTEGER,
    execution_duration_ms INTEGER,
    live_check_requested BOOLEAN DEFAULT FALSE,
    status VARCHAR(40) NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE users ADD COLUMN IF NOT EXISTS allowed_tiers JSONB;

CREATE INDEX IF NOT EXISTS ix_linux_inventory_uptime ON linux_inventory (uptime_seconds);
CREATE INDEX IF NOT EXISTS ix_linux_inventory_boot ON linux_inventory (boot_time);
CREATE INDEX IF NOT EXISTS ix_linux_inventory_coll_time ON linux_inventory (collection_time);
CREATE INDEX IF NOT EXISTS ix_linux_inventory_coll_status ON linux_inventory (collection_status);
CREATE INDEX IF NOT EXISTS ix_linux_inventory_cpu ON linux_inventory (cpu_usage_percent);
CREATE INDEX IF NOT EXISTS ix_linux_inventory_mem ON linux_inventory (memory_usage_percent);
CREATE INDEX IF NOT EXISTS ix_fs_metrics_usage ON filesystem_metrics (usage_percent);
CREATE INDEX IF NOT EXISTS ix_service_status_name ON service_status (service_name);
CREATE INDEX IF NOT EXISTS ix_service_status_active ON service_status (active_state);
