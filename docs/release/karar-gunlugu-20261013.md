# Karar günlüğü — 2026-10-13 (sürüm hazırlığı)

## Aşama 0 — Yedek
- `git fetch ai_eyup`: uzak main = yerel main = `ff9d04a9` (ilerleme yok).
- Çalışma ağacı tam tar'ı 1,3 GB çıktı ve disk %92 doluydu; silindi. Yerine yalnız commit'siz dosyaların tar'ı alındı:
  `/data/backup/ainew-uncommitted-20261013.tar.gz` (278 dosya, 1,3 MB).
- Push (force yok): `backup/feat-dilim-b-20261013` (branch), etiketler `backup/main-before-merge-20261013` (`ff9d04a9`),
  `backup/feat-dilim-b-pre-20261013` (`396422f0`).
- Disk notu: `/` %86 dolu (3,0 GB boş); paket üretimi için yer gerekecek (aşama 8).

## Aşama 1 — Acil koruma (G2)
- `test_capacity_policy.py` ve `test_reclaim_dynamic.py` `isolated_db` fixture'ına taşındı (canlı `capacity_policies` silinmiyor).
- Tüm testler "canlı DB engelli" modunda koşuldu (`DATABASE_URL` var olmayan bir DB adına yönlendirildi, yalnız konteyner env'i; canlı veriye dokunulmadı):
  canlı DB'ye giden 4 test daha bulundu: `test_prom_monitoring_catalogs.py` (3 test, canlı ayar okuyordu) ve `test_rag_pgvector.py` (canlı `rag_embeddings`'e test satırı yazıp siliyordu). Hepsi izole DB'ye taşındı
  (`rag_store.engine`/global durum/marker yolu monkeypatch ile yönlendirildi). Automic testlerine (`test_automic_masking_policy`: `SessionLocal` patch'li) dokunulmadı.
- Yan etki ve düzeltmesi: engelli-DB koşusunda `rag_store.ensure_schema` canlı `/app/uploads/.pgvector_unsupported` marker'ını yazdı (13:01); marker benim koşumdan
  kaynaklandığı için silindi (varsa sonraki başlangıçta zaten extension yüklü olduğundan temizlenirdi).
- Taşıma sonrası: canlı DB engelliyken tüm paket koşulacak (aşağıda).
- Canlı `capacity_policies`: 0 satır (varsayılanlar geçerli). Audit'te yalnız 2 kayıt var (2026-10-12 22:42, 1 sn arayla: `memory 70/datastore 60`, sonra `85/85` = varsayılan → satırlar kalkar).
  Son durum varsayılan olduğundan kaybolmuş özelleştirme YOK; geri yazılacak değer yok, tablo boş bırakıldı, varsayılan değer yazılmadı.
- Doğrulama: canlı DB engelliyken tüm backend paketi: **1759 passed, 11 skipped, 0 failed** (artık hiçbir test canlı DB'ye gitmiyor; skip'ler değiştirilmedi).
