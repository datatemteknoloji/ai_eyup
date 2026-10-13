# Automic operasyon kalıpları (ainew)

## Hata analizi sırası
1. `automic_search_executions` status_class=failed + zaman aralığı.
2. RunID `automic_execution` detail → restart zinciri → children (JOBP).
3. `reports` / `report` (önce DB kırpıntısı; gerekirse kaynak).
4. `automic_history` error_signatures + top_failed_objects.

## Süre sapması
- p95: son 14 gün başarılı çalışmalar.
- Aktif aşım: running_sec > p95 × 1.2 (`over_p95`).
- AE'nin kendi tahmini: running_sec > `ert_sec` (EH_Ert) ise `over_ert`; `signals` MRT_EXCEEDED/TCP_EXCEEDED AE'nin kendi süre denetimidir (EH_Signal). Tahmini bitiş `ert_end_time` (EH_ERTEnd). "Tahmini bitişi geçen / uzayan iş" sorusunda önce bunları kullan; ERT yoksa p95'e düş ve söyle.
- Biten sapma: duration > p95 × 1.5 (`duration_outliers`).

## Gece yükü
- `expected_tonight`: aynı isodow + 20:00–06:00 geçmişi; **forecast değil**.
- Widget 16 / `automic_history` template_id=expected_tonight.

## Script / usage
- Script OT’den maskeli okunur (OT_Type 0 process; 1 pre-process, 2 post-process, 3 inherit post-process bölümleri `! =====` yorum satırıyla ayrılır); ainew hash ile kendi anlık görüntü sürümlerini tutar (AE'nin OH_DeleteFlag = 2 sürümleri değildir).
- Usage JPP’den gelir; `usage_graph` yeteneği yoksa “kapsam dışı” de, uydurma graf çizme.

## Entegrasyon sağlığı
- Kaynak gecikmesi (Data Guard / max timestamp), collector hatası, circuit, kota.
- Kota kritikte rapor alıntısı durabilir; meta veri devam eder.

## Yanıtta kaçın
- AWI aksiyonu varmış gibi davranma.
- Maskeli değeri geri çözme.
- “Bu gece X job çalışacak” kesinliği — “geçmişte bu saatte sık görülen” de.


## Kullanıcı ADI ile çalışma bulma
- AE'de çalışma kaydında (AH/EH) **kullanıcı adı kolonu yoktur**; yalnız `AH_USR_Idnr` / `EH_USR_Idnr` (kullanıcı nesnesinin `OH_Idnr`'i) vardır. Ad = `OH_Name` (nesne tipi `USER`, genelde `KULLANICI/DEPARTMAN` biçimi).
- ainew toplama sırasında bu id'yi adına çevirip modül DB'ye `user` olarak yazar. `automic_search_executions user=<ad>` kısmi ad ve joker (`*`, `?`) kabul eder, büyük/küçük harf duyarsızdır.
- Modül DB'de sonuç yoksa ya da kullanıcısı çözülmemiş (eski) kayıtlar varsa araç kaynakta canlı arar: `OH (OH_OType='USER', OH_Name LIKE ad)` → `OH_Idnr` → `AH_USR_Idnr IN (...)`. Yanıtta `data_source=source_live` ve `source_users` görünür. Ad bulunamazsa `hint.known_users` ile bilinen kullanıcılar önerilir.
- Şu an çalışanlar: `automic_active user=<ad>`. Kullanıcı bazında özet (çalışma/hata/iptal/aktif): `automic_history template_id=user_activity`.
- Kullanıcı id'si (sayı) ile sorgu yapma; kullanıcıdan da id isteme.
