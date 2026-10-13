# Canlı okuma `off` — soru tipi çalışabilirlik

Varsayılan `source_guard.live_read_mode = off`. Kaynağa canlı sorgu yok; collector + modül DB.

| Soru tipi | Mod off kaynağı | Not |
|---|---|---|
| Çalışma detayı (RunID) | `automic_executions` / `automic_active` | DB'de yoksa: canlı kapalı mesajı + `as_of` |
| Workflow alt görevleri | modül DB `parent_run_id` + aktif snapshot | Boşsa canlı children yok |
| Restart zinciri | modül DB `restart_ref_run_id` | Canlı restart yok |
| Hatalı çalışma raporu | `automic_report_excerpts` (maskeli) | Collector hatalılarda alır |
| Başarılı çalışma raporu | **Yok** | Açık mesaj: canlı kapalıyken saklanmaz |
| Script incelemesi | `automic_object_script_versions` | Collector ağır pencerede OT senkron (OH_ModDate + OH_Idnr) |
| Nesne başlığı | `automic_object_headers` | OH isim canlı yasak (orta risk) |
| Şu an çalışan işler | `automic_active` + `snapshot_at` / `as_of` | EH canlı yok |

LLM: `{{LIVE_READ_MODE}}`, `{{LAST_COLLECTION_TIME}}` + araç `freshness_note` ile kullanıcıya açıkça söyler.
