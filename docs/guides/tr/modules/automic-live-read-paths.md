# Automic — collector dışı kaynak okuma yolları (canlı okuma envanteri)

Collector / backfill / JPP senkron / günlük discovery **hariç**. Risk sınıfları: `automic-source-query-risk.md` (rev 4).

| Araç/fonksiyon | Tetikleyen soru tipi | Şablon | Risk | Politika kontrolü (önce) |
|---|---|---|---|---|
| `queries.execution_detail` → `fetch_execution` | RunID detayı (modül DB’de yok) | `execution_by_id` | düşük | Hayır — doğrudan `_source_call` |
| `queries.execution_children` (`live`/boş liste) | Workflow alt adımları | `children` | düşük | Hayır |
| `queries.list_reports` | Rapor tipleri listesi | `report_types_rh` / `report_types_rt` | düşük / **orta** | Hayır |
| `queries.get_report` (cache/excerpt yok veya `from_source`) | Rapor içeriği | `report_count` + `report_range` | düşük | Hayır |
| `objects.ensure_header` | Nesne başlığı (stale/yok) | `object_header_by_name` | **orta** | Hayır — `build_source` |
| `objects.fetch_and_store_script` | Script / OT metni | `object_script_lines` (+ header) | düşük (+ orta header) | Hayır |
| `objects.object_usage` | Usage grafiği | — (modül DB) | — | Kaynak yok (zaten kaldırıldı) |
| `queries.active_executions` | Şu an çalışan işler | — (modül `automic_active`) | EH canlı **orta** (collector) | Canlı EH yok; snapshot |
| `automic_execution` tool (`live` / `from_source`) | Sohbet RunID | yukarıdakiler | — | Hayır |
| `automic_object` tool (`force` script) | Sohbet nesne script | OT / OH | düşük/orta | Hayır |
| API `GET …/children?live=` | UI canlı children | `children` | düşük | Hayır |
| API `POST …/test`, `…/discover`, sihirbaz probe | Kurulum | `test_connection` / `discover` | n/a (admin) | Rate-limit var; live_read yok |
| `explain_plans` | Plan kontrol aracı | tüm şablonlar | n/a (admin) | Hayır |

**Sonuç (uygulama sonrası):** Tüm chat/API canlı okumalar `live_read.call` kapısından geçer.
Varsayılan `live_read_mode=off`. Orta/yüksek şablonlar canlıda reddedilir. Admin test/discover/explain bu politikanın dışındadır (kurulum).
