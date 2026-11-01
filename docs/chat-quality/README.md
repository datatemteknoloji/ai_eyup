# Sohbet kalite programı — dizin

Kalıcı kayıt: **[plan.md](plan.md)** (adım sırası, kapanış kriterleri, sonuçlar, kararlar). Bu dosya yalnız dizindir.

| Ne | Nerede |
|---|---|
| Plan / durum / sonuçlar | [plan.md](plan.md) (üstte «Sıra» tablosu; «Güncel durum» bölümü) |
| İlk ölçüm (69/121) | [baseline-2026-10-14.md](baseline-2026-10-14.md), `baseline/` |
| Bulgular | [findings-direct-cmd.md](findings-direct-cmd.md) |
| Koşu raporları | `reports/` |
| Bench araçları | `scripts/chat_bench/` — `run.py` (tam bench), `silence_eval.py` (ilk-token sessizliği, `--progress on|off`), `cache_eval.py`, `grounding_eval.py`, `rag_eval.py` |
| Ürün kodu | `backend/app/services/chat_orchestrator/` (tur yaşam döngüsü, AI kapısı, progress), `chat_quality/` (kapılar, doğrulayıcı, iz), `chat_cache_service.py`, `core/chat_executor.py`, `core/loop_watchdog.py`, `services/event_dedupe.py` |
| Mimari anlatım | `docs/guides/{tr,en}/modules/ai-architecture.md`, `.cursor/rules/ainew-ai-architecture.mdc` |
| Ayarlar / env | [../deployment.md](../deployment.md) «Sohbet kalitesi / RAG / LLM» tablosu |
| Performans notları | [../scale-and-performance.md](../scale-and-performance.md) «Sohbet SSE'si ve event döngüsü» |

## Çalışma kuralları
- Kapanış kriteri koddan ÖNCE plana yazılır; «Kapandı» insan testi (İH) olmadan yazılmaz.
- Automic (`services/automic/*`, `api/automation.py`) dokunulmaz.
- Uygulama verisi (DB, `.env`, volume) izinsiz değiştirilmez; her adımda `/root/backup-step<N>-*` yedeği.
- Sohbet/araç/RAG yaşam döngüsü değişince aynı turda: ai-architecture TR + EN + `.mdc`.
- Test: `docker exec -w /app server_management_backend python -m pytest app/tests -q -p no:cacheprovider`.
