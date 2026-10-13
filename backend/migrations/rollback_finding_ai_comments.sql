-- add_finding_ai_comments.sql geri alma — Bulgular AI yorumu tablolarını SİLER (içerikleri kalıcı olarak kaybolur).
-- Çalıştırma: psql -U postgres -d server_management -f migrations/rollback_finding_ai_comments.sql
-- NOT: Model `app/models/__init__.py` içinde kayıtlıyken backend yeniden başlatılırsa tablolar yeniden oluşur;
-- kalıcı geri alma için önce kayıt/import kaldırılmalıdır.
BEGIN;
DROP TABLE IF EXISTS finding_ai_feedback;
DROP TABLE IF EXISTS finding_ai_comments;
COMMIT;
