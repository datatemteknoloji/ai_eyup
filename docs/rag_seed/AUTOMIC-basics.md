# Automic / UC4 — ainew alan bilgisi (runbook)

Bu runbook genel Automic bilgisidir. Canlı sayılar, RunID ve raporlar için
`automic_*` araçlarını kullan; buradan uydurma. Tablo/kolon (24.4 resmi): `AUTOMIC-ae-db-schema`.
Durum kodu / RH_Type / nesne tipi listeleri: **DOĞRULANMADI** — `AUTOMIC-ae-status-metrics`.

## Nesne tipleri (sık) — DOĞRULANMADI
- **JOBS**: işletim sistemi / script job.
- **JOBP**: workflow (process flow); alt adımlar çocuk çalışmalardır.
- **JSCH**: schedule; zamanlanmış tetikleyici.
- **SCRI**: script nesnesi. **JOBF** dosya transferi, **EVNT** event, **JOBG** job group.
- Tam liste 24.4 guide'da bulunamadı; canlı `UC_OTYP` ile kontrol edilecek.

## Durum sınıfları (ainew varsayılanı) — DOĞRULANMADI
- **failed**: 1800–1899, iptaller hariç (1850/1851).
- **cancelled**: 1850, 1851.
- **ok**: 1900–1999.
- Aktif EH grupları ainew `classify.active_state` (24.4 Task Status sayfası bulunamadı).

## Tipik hata imzaları
- `ORA-00054` kaynak meşgul; `ORA-01653` tablespace; `ORA-12541` TNS.
- `Permission denied`, `No space left`, `return code 8`, timeout / OutOfMemory.
- Raporlarda `&…PASSWORD#`, JDBC şifreleri ve TCKN/IBAN maskelenmiş gelir (`***`, `[MASKED]`).

## Araç seçimi (ainew)
- Liste/filtre → `automic_search_executions`.
- RunID → `automic_execution` (detail → children → report).
- Şu an → `automic_active` (`over_p95` ainew yüzdeliği, `over_ert` AE'nin `EH_Ert` tahmini, `signals` EH_Signal).
- Nesne/script/usage → `automic_object`.
- Trend/gece örüntüsü → `automic_history` (`expected_tonight` ainew'in tarihsel örüntüsüdür, AE forecast'ı değildir).
- Agent → `automic_agent` (aktivite; bağlantı durumu yok). Sağlık/kota → `automic_status`.

## Kullanıcı ve klasör nereden gelir?
- **Kullanıcı** = `AH_USR_Idnr` → `OH_Name` (kullanıcı nesnesi; `USR_OH_Idnr = OH_Idnr`). Çözülemezse boş görünür; uydurma.
- **Klasör** = `OFS_Link = 0` (24.4: Home Folder) → klasör `OH_Name`.

## ERT (tahmini süre)
AE'nin kendi tahmini **vardır**: `AH_ERT` / `EH_Ert` / `OH_Ert`, tahmini bitiş `EH_ERTEnd`. ainew bunları `ert_sec` / `ert_end_time` olarak taşır; "ERT yok" **deme**. ERT hesaplanmamışsa (`ert_calc` ≠ 2 veya `ert_sec` boş) bunu belirt; yoksa p95 ile karşılaştır ve hangisi olduğunu söyle.

## Cevap kalıbı
Özet → Bulgular → Değerlendirme (güven) → Önerilen adımlar (AWI’da insan yapar) → Kapsam.
Automic’e yazma/başlatma yok. AE'nin forecast verisi ainew'de toplanmaz; ERT varsa kullan, geçmiş örüntüyü forecast diye sunma.
