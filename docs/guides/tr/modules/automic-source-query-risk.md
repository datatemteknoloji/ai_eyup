# Automic kaynak sorgu şablonları — risk raporu (30–40 TB)

Kaynak: `ae-24.yaml` **rev 5** + `OracleSource`. İndeks gerçeği canlı DBA listesi gelene kadar bilinmiyor.
Temel kural: her kaynak sorgusu PK/indeks + satır sınırı; tam tablo taraması yok.

## Adım 2b sonrası (rev 4)

| Şablon | Tablo | WHERE koşulu | Filtre kolonları | Bu kolonlar PK mi? | Satır sınırı | Risk |
|---|---|---|---|---|---|---|
| ended_executions | AH | client + **AH_Idnr BETWEEN** | AH_Idnr | **Evet** | FETCH FIRST | düşük — zaman app’te; RunID eşlemesi + slack |
| ended_by_runid_range | AH | AH_Idnr aralığı | AH_Idnr | **Evet** | FETCH FIRST | düşük — backfill |
| min_run_id | AH | **yok** (tüm tablo MIN) | AH_Idnr | **Evet** (PK) | FETCH 1 | düşük — **client filtresi yok**; beklenen plan: `INDEX FULL SCAN (MIN/MAX)`; client WHERE indeks MIN optimizasyonunu bozar |
| count_ended_by_id_range | AH | client + AH_Idnr aralığı | AH_Idnr | **Evet** | FETCH 1 | düşük — mutabakat sayımı |
| children | AH | client + ParentAct + **AH_Idnr BETWEEN** | ParentAct + Idnr | **Evet** (Idnr aralığı) | FETCH FIRST | düşük — alt=üst Idnr…bitiş+pay / güncel max |
| restarts | AH | client + RefNr + **AH_Idnr BETWEEN** | RefNr + Idnr | **Evet** (Idnr aralığı) | FETCH FIRST | düşük — aynı sınır mantığı |
| active_executions | EH | client IN | EH_CLIENT | Hayır | FETCH FIRST | orta — olduğu gibi; temkinli modda süre+satır ayrıca loglanır; DBA indeks listesi bekleniyor |
| execution_by_id | AH | client + AH_Idnr | AH_Idnr | **Evet** | FETCH 1 | düşük |
| report_types_rh / rt | RH/RT | run_id | RH/RT_AH_Idnr | Evet / kısmi | FETCH FIRST | düşük / orta |
| report_count / report_range | RT | RunID+Type(+LNR) | PK | **Evet** | head/tail | düşük |
| object_header_by_name | OH | client + exact name | OH_NAME | Muhtemel unique | FETCH 1 | orta — DBA indeks listesi bekleniyor |
| object_headers_by_id_range | OH | client + OH_Idnr aralığı | OH_Idnr | **Evet** | FETCH FIRST | düşük |
| object_names_by_ids | OH | OH_Idnr IN | OH_Idnr | **Evet** | chunk ≤500 | düşük |
| folder_links_by_objects | OFS | LINK=0 + object IN | OFS keys | Kısmi | chunk | orta — DBA indeks listesi bekleniyor |
| object_script_lines | OT | OH_Idnr | OT_OH_Idnr | **Evet** | cursor max_rows | düşük |
| usage_children | JPP | parent_id | JPP_OH_Idnr | **Evet** | FETCH 200 | düşük — senkron / tekil ebeveyn |
| usage_by_parent_id_range | JPP | **parent_id BETWEEN** | JPP_OH_Idnr | **Evet** | FETCH FIRST | düşük — gecelik ağır pencere collector |
| ~~usage_parents~~ | JPP | child_name = | isim | Hayır | — | **kaldırıldı** — kullanım sorgusu modül DB |

## Kaldırılan yüksek riskli şablonlar (rev 3–4)

| Eski şablon | Neden |
|---|---|
| ended_executions (zaman WHERE) | TIMESTAMP taraması → AH_Idnr BETWEEN |
| ended_by_users / user_objects_by_name | USR_Idnr / LIKE |
| daily_profile / latest_activation | zaman agregasyonu |
| object_headers_since | OH_MODDATE |
| usage_parents | JPP_Object isim araması → modül DB + OH_Idnr senkron |

## Koruma katmanları

1. **Zaman→RunID:** `automic_runid_hour_map`; sorgular `AH_Idnr BETWEEN`; slack (24s) + app zaman filtresi.
2. **children/restarts:** `id_min` = üst AH_Idnr; `id_max` = bitiş+pay eşlemesi veya (hâlâ aktifse) eşlemedeki max AH_Idnr.
3. **Kullanıcı / usage:** canlı kaynak yok; modül DB (`automic_object_usage`, `synced_at`).
4. **JPP senkron:** ağır iş penceresinde OH_Idnr parçaları; `jpp_oh_id_cursor` / `jpp_synced_at`.
5. **RT:** RunID + Type + head/tail.
6. **Temkinli mod:** küçük dilim; yavaş şablon disable; **active_executions** süre+satır ayrı log.
7. **EXPLAIN PLAN:** `TABLE ACCESS FULL` / `INDEX FAST FULL SCAN` → riskli. `min_run_id` için beklenen iyi plan: `INDEX FULL SCAN (MIN/MAX)` (FAST FULL değil).
8. **FETCH FIRST:** `templates.render` zorunlu.
9. **Plan aracı:** `python -m app.services.automic.explain_plans --system-id N` — `_SAMPLE` içinde `min_run_id` (binds boş) ve diğer şablonlar.

Plan kontrolü gerçek kaynakta yapılana kadar: **DBA indeks listesi bekleniyor** (özellikle EH client filtresi).

## Canlı okuma (collector dışı)

Merkezi politika: `source_guard.live_read_mode` (`off` | `windows_only` | `always`) — bkz. `live_read.py` ve `automic-live-read-paths.md`.
Canlıda yalnız bu tabloda **düşük** riskli şablonlar; orta/yüksek (EH, OH isim, RT DISTINCT, …) asla.
