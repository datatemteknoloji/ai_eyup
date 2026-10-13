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
- Kalan risk (kayıt): bazı RAG testleri `rag_store.ensure_schema()`'yı (idempotent `CREATE ... IF NOT EXISTS`) canlı motor üzerinden tetikleyebilir; veri yazmaz/silmez. Canlı-DB-engelli koşuda
  bu yolun `/app/uploads/.pgvector_unsupported` marker'ı yazdığı görüldü (marker iki kez silindi; normal koşuda yazılmaz). Sonraki sürümde `ensure_schema` testlerde izole motora yönlendirilmeli.

## Aşama 2 — Commit'ler (dosya yolu gruplarına göre, hunk bölme yok)
Sıra: test izolasyonu `6b09231a` · LLM `83bcc203` · Zaman `40e8e9df` · RAG `abe29c5b` · What-if v2 `c4f3e932` · Bulgular `73b34b82` · Automic `8848de79` · docs `c9690e75`.
Ortak dosyaların atandığı commit (ilk bağımlı konu):
- `messages.ts` (virt + Automic anahtarları karışık) → What-if v2 (`c4f3e932`).
- `models/__init__.py` (FindingAi*) → Bulgular; `router.py`, `module_policy.py`, `agent/tools.py`, `background_tasks.py`, `models/module.py`, `module_orchestrator.py`, `api/integrations.py`,
  `product_guide.py`, `Layout.tsx`, `App.tsx`, `index.css`, `docker-compose.yml`, `deploy/docker-compose.prod.yml`, `requirements.txt` (oracledb), `integrations.md` (TR/EN), `test_module_policy.py` → Automic (`8848de79`).
- `main.py` (agent_active_model), `api/settings.py`, `Settings.tsx`, `platform_status.py` → LLM; `api/unified_chat.py` (1 satır automic eşlemesi) → LLM.
- Ara commit'ler tek başına yeşil olmayabilir (ör. LLM commit'i Automic ortak dosyalarına bağımlı değil ama messages.ts ters yönde olabilir); doğrulama yalnız SON commit'te yapılır.
- `backend/app/tools/` (debug/tanı scratch: `_debug_hybrid*.py`, `rag_timing_small.py` vb.) commit'lenmedi; `.gitignore`'a eklendi.

## Aşama 3 — Eksiklerin tamamlanması
- **A3:** "bulgu üretme" davranışı korundu (UI/skor ve A4 "Veeam'siz birebir aynı" ilkesiyle tutarlı); ölü `check_capabilities_met` silindi, `requires_capability` yalnız bilgilendirme. `not_applicable` satırı üretilmedi.
- **A2:** `RESULT_*` sabitleri; AST testi yalnız `FindingDraft(result=…)` değer dallarına bakar (`st in ("fail","warn")` gibi karşılaştırmalar yanlış alarm vermesin diye).
- **B2/B9:** 12.x ve 1.3-rev2 seçilebilir + "alanları doğrulanmadı". B9 yorumu: Automic'in `llm_deployment` mantığına dokunulmadı; yedek verisi için `services/backup/egress.py` kapsamı + Yedekleme sağlayıcısı sayfasında harici LLM uyarısı. `ai-architecture.md` (TR/EN) ve `.cursor` kuralındaki "ham yedek verisi uzak LLM'e gitmez" cümlesi gerçeğe uygun düzeltildi (VM/iş/depo adları + durum/RPO özeti gider).
- **F3/F2:** N+1 sekmesi, riske göre backend sırası, `cap.sim.host_failure_matrix`; kapsam çipleri; What-if'te host seçici kaldırıldı. Backend hâlâ "(cluster yok) · ad" üretir; UI etiketi "Cluster'sız host'lar".
- **E4/E5:** E5 yorumu — ek bellek hesaba katılmıyor, bu yüzden etiket "doküman varsayımı, ölçülmedi" varsayım satırıdır (sonuca yansıtılmaz).
- **C1/A6/G4/E8-doküman:** yapıldı. `.env.example` varsayılan yönetici parolası notu değiştirilmedi (kapsam dışı).
- **E7 (eşik override arayüzü) ve E9 (sohbet PDF Yöntem notları): kullanıcı kararıyla sonraki sürüme bırakıldı** (CHANGELOG "Bilinen sınırlamalar").
- E2/E3/E6: plan gereği bu sürümde yok (kullanıcıya görünen sayıları değiştirir).

## Aşama 4–6 — Test, birleştirme
- Backend tam paket (izole DB): exit 0; vitest 23 dosya / 120 test geçti; `tsc --noEmit` temiz; frontend imajı yeniden derlendi (`VirtCapacity` bundle'ında yeni UI doğrulandı).
- Canlı doğrulama: `/health` 200, frontend 443 200, DB ready. **Automic smoke ve kimlik doğrulamalı canlı kontroller koşulmadı:** `.env`'deki `ADMIN_DEFAULT_PASSWORD` ile giriş 401 (parola değiştirilmiş); parola/kimlik doğrulama atlatılmadı, `.env` değiştirilmedi → "ertelendi".
- Restart sonrası log: tek `vcenter_event_collector` hatası (SQLAlchemy "identity map no longer valid", `office` vCenter olay senkronu); dosya bu dalda değişmedi → önceden var olan, bu sürümle ilgisiz. Geliştirme `.env` `APP_VERSION=1.0.9.39` sabitli, `/health` 1.0.9.39 gösteriyor (`.env` dokunulmadı; paket imajı 1.0.9.41 raporluyor).
- Birleştirme: `ai_eyup/main` değişmemişti (ff9d04a9) → fast-forward, force yok; yerel `feat/dilim-b-backup-framework` silindi; uzak `backup/feat-dilim-b-20261013` ve yedek etiketleri duruyor.

## Aşama 7–8 — CHANGELOG ve paket
- CHANGELOG'daki 7 yayınlanmamış satır (v1.0.9.40 etiketinde olmayanlar) `[Unreleased]`'a taşındı; release.sh bunu `[1.0.9.41]` başlığına çevirdi.
- Paket hariçleri: `backend/app/tests`, `backend/tests`, `backend/app/tools`, `winrm_adapter_fake.py`, Automic benchmark/kalite betikleri, `test_*_1000.py`, karar günlüğü, `*.log/*.tmp`. **Tutuldu:** `demo_gate.py`, `centrify/demo_seed.py` (`/centrify/demo/seed` endpoint'i içe aktarıyor), Veeam fixture kodu (fixture dizini yoksa tüm endpoint "sahada doğrulanmadı" olarak kalır).
- **Sorun:** ilk paketleme imajı `./backend` dizininden (tests + tools dahil) derledi; tar temizdi ama imaj değildi. `backend/.dockerignore` eklendi ve yalnız `build-distribution.sh` ile yeniden derlendi (release.sh ikinci kez ÇALIŞTIRILMADI). Etiket `v1.0.9.41` yayından önce (yerel) son commit'e taşındı; `backend/VERSION` release commit'ine dahil edildi.
- Disk: `/` 3.0 GB boş (docker deposu burada); `dist/` ayrı birimde (19 GB) olduğundan eski `ainew-1.0.9.40` tar'ı silinmedi başka amaçla değil, yer açmak için kaldırıldı (GitHub release'te asset mevcut, boyut aynı).
- Not: `dropt/compose.env` git'te takipli ve dropt/bridge varsayılan sırları içeriyor; önceki sürümlerde de paketteydi, değiştirilmedi (kurulumda rotasyon önerilir).
