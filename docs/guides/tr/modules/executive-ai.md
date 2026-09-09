# ainew — Yönetici ve AI GUIDE

Modüller: `executive`, `ai_automation`.

## Menüler

| Menü | Yol | İşlem |
|------|-----|--------|
| Yönetici özeti | `/executive` | Çok platformlu özet |
| Tüm altyapı asistanı | `/chat` | Çapraz tool (Linux, Windows, virt, PromQL, …) |
| Ajan | `/agent` | LangGraph araçları; mutasyon onaylı |

Platform sohbetleri kendi modül menülerindedir (`/linux/chat`, `/virt/chat`, …).

## AI kuralları

- Yerel Ollama veya Ayarlar’daki uzak LLM; fail-fast  
- Prometheus: yalnızca PromQL  
- Kapsam ve RBAC tool sonuçlarını keser  
- RAG: Ayarlar → RAG (bu GUIDE değil)  
- Sohbet PDF: sayfa veya seçili soru-cevap  

## Limitler

Yönetici özeti, Level 1 Preview/Apply yerine geçmez. Ajan onaysız root komut çalıştırmaz.
