-- Envanter sync ayarları için app_settings tablosu
-- Backend ilk çalıştığında Base.metadata.create_all ile de oluşturulur
CREATE TABLE IF NOT EXISTS app_settings (
    id SERIAL PRIMARY KEY,
    key VARCHAR(128) NOT NULL UNIQUE,
    value TEXT
);
CREATE INDEX IF NOT EXISTS ix_app_settings_key ON app_settings(key);
