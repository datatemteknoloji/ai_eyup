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

---

## Tüm Ortamlar Hazır Raporları (`/executive/infra-reports`)

Yönetici modülünde, `/executive` sayfasından ayrı bir kart ızgarası (11 rapor): Yönetici Özeti, Kapasite, Kapasite Tahmin, Risk, En Riskli Varlıklar, Operasyon, Erişilebilirlik (SLA), Yama ve Uyum, Geri Kazanım, İzleme Kapsamı, Migrasyon (VMware → OpenShift). Her rapor Sanallaştırma, OpenShift, Linux, Windows ve Exadata'yı kapsar, ama bir alan **yalnız o rapor için anlamlıysa** girer. Kapsam tablosu kodda sabittir (`services/exec_catalog_reports.py` → `MATRIX`); kapsam dışı alan **nedeniyle birlikte** rapora yazılır (örn. Tahmin: Windows ve Exadata kullanım serisi toplanmadığı için kapsam dışı). Veri eksikse bölüm «Ölçülemedi» olur; sayı uydurulmaz. Sentetik (ZZ-FAKE) kaynaklar dahil edilmez. Alan notu `exec_health` formülüdür (ekip raporu notundan farklı olabilir). Yedek (Veeam) bu raporlarda yoktur. LLM yok. Üretim 1–10 sn sürebilir.
