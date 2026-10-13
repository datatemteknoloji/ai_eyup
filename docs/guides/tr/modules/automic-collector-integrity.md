# Collector veri doğruluğu

## Partition

`automic_executions` Timescale hypertable; zaman kolonu **`activation_time`** (önceden `end_time` idi).  
PK: `(system_id, client, run_id, activation_time)`. Aktivasyon değişmediği için durum güncellemesi düz upsert’tır (sil+ekle yok). Saklama / `drop_chunks` `activation_time` üzerinden.

Migration: `database._migrate_executions_to_activation_time` (idempotent, `ensure_schema` içinde).

## Kayıp veri

RunID’ler ardışık değildir; dizideki boşluklar kayıp **değildir**. Kaynak MIN’in yükselmesi tek başına normal reorg’dur (silinenler çoğunlukla zaten toplanmıştır).

Tespit:
1. Kaynak: `SELECT MIN(AH_Idnr) FROM AH` — **client filtresi yok** (PK `INDEX FULL SCAN (MIN/MAX)`).
2. Watermark: tüm client’ların son okunan max AH_Idnr değerlerinin **en küçüğü** (`run_id_watermark_by_client` / modül `MAX(run_id)`).
3. `kaynak_min > watermark` → kayıp aralık `(watermark, kaynak_min)` → `automic_data_gaps` + **kritik** uyarı.
4. Aksi halde → bilgi logu (`kaynak_min`, watermark, zaman); alarm yok.

## AE sürümü

Kurulum sihirbazında **Automic AE sürümü** (varsayılan `24.4`). 24.4 dışı → uyarı (“Şema doğrulaması 24.4'e göre yapıldı”). Kaynak tablodan otomatik okuma yok.

## Diğer

- Yeniden okuma: `refresh_hours` (24) AH PK aralığı  
- İdempotent upsert: `(system_id, client, run_id, activation_time)`  
- Stale: `stale_warn_hours` (6)  
- Mutabakat: ağır pencerede saatlik PK COUNT  
- Eski kayıt: `eski kayıt — kullanıcı ID'si yok`  
