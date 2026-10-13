# Automic kullanıcı eşlemesi

## Önce (uygulama öncesi durum)

| Soru | Cevap |
|---|---|
| ID→ad nerede? | **Toplama sırasında** (`OracleSource._enrich_runs`): `AH_USR_Idnr` / `EH_USR_Idnr` → `object_names_by_ids` ile OH; sonuç string `user` olarak yazılırdı. Sorgu anında yeniden çözülmezdi. |
| Ne saklanıyordu? | `automic_executions."user"` / `automic_active."user"` — yalnız **ad**. `user_idnr`, departman, delete_flag yoktu. |
| Join'de client? | **Hayır.** `_lookup_names` yalnız `OH_Idnr IN (...)`. |
| Silinmiş / ad değişmiş? | Ad değişince eski çalışmalarda eski ad kalırdı. Silinmiş kullanıcı için tutarlı etiket yoktu. |
| AH_USR_Idnr = OH_Idnr? | Kod/yaml varsayımı. 24.4 AH yalnız *“IDNR of the user that executed this activity”* der — **gerçek veriyle doğrulanacak**. |

## Sonra (uygulama)

| Parça | Konum |
|---|---|
| Tablo | `automic_users` — PK `(system_id, client, user_idnr)`; OH `OType=USER` (USR yok) |
| Senkron | `users.sync_users_chunk` + collector `_users_sync_step` — OH_Idnr min..max, ModDate ile değişmeyen atlanır |
| Çalışma | `user_idnr`, `user_name_at_run`; görüntüleme `users.attach_user_displays` (client zorunlu) |
| Silinmiş / bilinmeyen | `(silinmiş)` / `bilinmeyen kullanıcı (ID: x)` — kayıt kaybolmaz |
| Arama | Modül DB, ILIKE, `*`/`?`, `*/FIN` (ad/departman) |
| Uyarı | `mismatch_warning` — eşik `source_guard.user_id_mismatch_warn_ratio` (varsayılan %5) |
