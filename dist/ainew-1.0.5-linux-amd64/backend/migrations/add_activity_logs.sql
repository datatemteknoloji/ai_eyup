-- activity_logs tablosu - kullanıcı işlem günlüğü
-- Çalıştırma: psql -U postgres -d server_management -f migrations/add_activity_logs.sql
CREATE TABLE IF NOT EXISTS activity_logs (
    id SERIAL PRIMARY KEY,
    action_type VARCHAR(80) NOT NULL,
    summary VARCHAR(500) NOT NULL,
    details JSONB DEFAULT '{}',
    status VARCHAR(20) DEFAULT 'success',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_activity_logs_action_type ON activity_logs(action_type);
CREATE INDEX IF NOT EXISTS ix_activity_logs_status ON activity_logs(status);
CREATE INDEX IF NOT EXISTS ix_activity_logs_created_at ON activity_logs(created_at DESC);
