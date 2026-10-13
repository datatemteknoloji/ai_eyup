-- Bulgular sayfası AI yorumu (Yapılandırma + Donanım) — OLAY tabanlı yorum + geri bildirim tabloları
-- DURUM: Tablolar `app/models/__init__.py` kaydı sayesinde backend açılışında `Base.metadata.create_all` ile OTOMATİK
-- oluşur; bu dosya REFERANS'tır (model ile birebir tutarlı) ve elle çalıştırılabilir. Yalnız YENİ tablo ekler;
-- mevcut tablo/veri değiştirilmez. Tekrar çalıştırılabilir (IF NOT EXISTS).
-- Çalıştırma: psql -U postgres -d server_management -f migrations/add_finding_ai_comments.sql
-- Geri alma:  psql -U postgres -d server_management -f migrations/rollback_finding_ai_comments.sql
--
-- Tekillik/indeks: (event_key, version) UNIQUE (aynı olayın sürüm numarası tekrarlanamaz), (comment_id, username) UNIQUE
-- (kullanıcı başına yorum sürümü başına tek oy). Saklama: eski sürümler VIRT_AI_COMMENT_RETENTION_DAYS (varsayılan 90 gün)
-- sonra silinir; her olayın en son sürümü kalır.

BEGIN;

CREATE TABLE IF NOT EXISTS finding_ai_comments (
    id            SERIAL PRIMARY KEY,
    finding_id    INTEGER REFERENCES infra_findings(id) ON DELETE SET NULL,
    event_key     VARCHAR(300) NOT NULL,
    version       INTEGER NOT NULL,
    model         VARCHAR(120),
    locale        VARCHAR(5) NOT NULL,
    content       JSON NOT NULL,
    confidence    JSON NOT NULL,
    input_hash    VARCHAR(64) NOT NULL,
    facts         JSON NOT NULL,
    validation    JSON,
    generated_by  VARCHAR(100),
    generated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    duration_ms   INTEGER,
    CONSTRAINT uq_finding_ai_comment_event_version UNIQUE (event_key, version)
);
CREATE INDEX IF NOT EXISTS ix_finding_ai_comments_id ON finding_ai_comments (id);
CREATE INDEX IF NOT EXISTS ix_finding_ai_comments_finding_id ON finding_ai_comments (finding_id);
CREATE INDEX IF NOT EXISTS ix_finding_ai_comments_event_key ON finding_ai_comments (event_key);

CREATE TABLE IF NOT EXISTS finding_ai_feedback (
    id          SERIAL PRIMARY KEY,
    comment_id  INTEGER NOT NULL REFERENCES finding_ai_comments(id) ON DELETE CASCADE,
    username    VARCHAR(100) NOT NULL,
    helpful     BOOLEAN NOT NULL,
    note        VARCHAR(500),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_finding_ai_feedback_user UNIQUE (comment_id, username)
);
CREATE INDEX IF NOT EXISTS ix_finding_ai_feedback_id ON finding_ai_feedback (id);
CREATE INDEX IF NOT EXISTS ix_finding_ai_feedback_comment_id ON finding_ai_feedback (comment_id);
CREATE INDEX IF NOT EXISTS ix_finding_ai_feedback_comment_helpful ON finding_ai_feedback (comment_id, helpful);

COMMIT;
