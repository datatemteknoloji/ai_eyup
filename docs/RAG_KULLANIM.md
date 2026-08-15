# RAG (Bilgi Tabanı) Kullanımı

Projede üç tür RAG kullanılıyor; hepsi AI Chat yanıtlarına ek context sağlar.

## Gereksinim

- **Ollama embedding modeli:** Chat ve RAG'ın çalışması için Ollama'da `nomic-embed-text` yüklü olmalı.
  ```bash
  ollama pull nomic-embed-text
  ```

## 1. Runbook RAG

- **Amaç:** Dokümantasyon / runbook parçalarını saklayıp "bu hatada ne yapılır?" gibi sorularda ilgili bölümleri modele vermek.
- **Veri:** Serbest metin (başlık + içerik) veya **PDF dosyası**. İçerik ~800 karakterlik chunk’lara bölünüp embed’lenir.

### Metin ile ekleme
- **API:**
  ```bash
  curl -X POST http://localhost:8000/api/v1/rag/runbook/ingest \
    -H "Content-Type: application/json" \
    -d '{"title": "Disk dolu hatası", "content": "Disk doluluk %90 üzerine çıktığında:\n1. df -h ile hangi partition dolu kontrol et.\n2. Büyük logları rotate et veya arşivle.\n3. Gerekirse eski backup'\''ları sil."}'
  ```

### PDF ile ekleme
- **UI:** Ayarlar → RAG (Bilgi Tabanı) → "Runbook PDF yükle" alanından PDF seçip "PDF'i RAG'e Ekle" butonuna tıklayın. İsterseniz başlık girebilirsiniz (boşsa dosya adı kullanılır).
- **API:**
  ```bash
  curl -X POST http://localhost:8000/api/v1/rag/runbook/ingest-pdf \
    -F "file=@/path/to/dokuman.pdf" \
    -F "title=Opsiyonel Başlık"
  ```
  - Dosya boyutu en fazla 50 MB. Sadece `.pdf` kabul edilir.
  - PDF’den metin çıkarılır (pypdf); korumalı veya görsel-only PDF’lerde metin boş olabilir.

- **Chat:** Kullanıcı sorusu embed’lenir, runbook collection’da benzer chunk’lar aranır, bulunan metinler prompt’a eklenir.

## 2. Incident / Event RAG

- **Amaç:** Geçmiş incident ve event kayıtlarını vektörleyip benzer durumları bulup modele vermek.
- **Veri:** Veritabanındaki `Incident` ve `SystemEvent` tabloları.
- **API:**
  - Incident’ları indexle (mevcut RAG içeriği silinir, sadece incident’lar yazılır):
    ```bash
    curl -X POST http://localhost:8000/api/v1/rag/incidents/reindex
    ```
  - Event’leri aynı collection’a ekle (silme yapılmaz):
    ```bash
    curl -X POST http://localhost:8000/api/v1/rag/events/reindex
    ```
- **UI:** Ayarlar → RAG (Bilgi Tabanı) → "Incident'ları RAG'e Ekle" / "Event'leri RAG'e Ekle".

## 3. Metrik Açıklamaları RAG

- **Amaç:** "Bu metrik ne anlama geliyor?" gibi sorularda ilgili metrik açıklamalarını modele vermek.
- **Veri:** Varsayılan liste (Node Exporter metrikleri) backend’de tanımlı; isteğe göre özel liste de gönderilebilir.
- **API:**
  - Varsayılan metrik listesini yükle:
    ```bash
    curl -X POST http://localhost:8000/api/v1/rag/metrics/seed \
      -H "Content-Type: application/json" \
      -d '{}'
    ```
  - Özel liste (opsiyonel):
    ```bash
    curl -X POST http://localhost:8000/api/v1/rag/metrics/seed \
      -H "Content-Type: application/json" \
      -d '{"items": [{"name": "node_cpu_seconds_total", "description": "CPU saniye cinsinden..."}]}'
    ```
- **UI:** Ayarlar → RAG → "Metrik Açıklamalarını Yükle (varsayılan)".
- **Startup:** Backend açılışında varsayılan metrik listesi arka planda bir kez seed edilir (Ollama/Chroma hazır değilse sessizce atlanır).

## Durum ve Test

- **Collection sayıları:**
  ```bash
  curl http://localhost:8000/api/v1/rag/status
  ```
  Örnek: `{"runbook": 0, "incidents": 5, "metrics": 25}`

- **RAG context önizleme (test):**
  ```bash
  curl "http://localhost:8000/api/v1/rag/preview?message=CPU%20kullanimi%20nedir"
  ```

## Chat’e Entegrasyon

Her chat mesajında:

1. Kullanıcı mesajı embed’lenir.
2. Üç collection’da (runbook, incidents, metric_descriptions) benzerlik aranır.
3. Bulunan metinler prompt’a şu başlıklarla eklenir:
   - RUNBOOK / DOKÜMANTASYON
   - BENZER GEÇMİŞ OLAYLAR / INCIDENT'LAR
   - METRİK AÇIKLAMALARI

Config (opsiyonel):

- `RAG_CHROMA_PATH`: Chroma veri dizini (varsayılan: `/app/chroma`)
- `RAG_SEED_PATH`: Kurulumla gelen runbook PDF/metin dizini (varsayılan: `/app/docs/rag_seed`; host’ta `{kurulum}/docs/rag_seed`)
- `RAG_RUNBOOK_TOP_K`, `RAG_INCIDENTS_TOP_K`, `RAG_METRICS_TOP_K`: Her collection’dan kaç chunk alınacağı (varsayılan 3, 3, 5)
- `OLLAMA_EMBED_MODEL`: Embedding modeli (varsayılan: `nomic-embed-text`)

## Seed dizini (`docs/rag_seed`)

Paket `docs/rag_seed` içeriğini taşır; backend ilk açılışta (Ollama `nomic-embed-text` hazırsa)
Chroma runbook koleksiyonuna chunk'lar. Ek PDF aynı dizine konur. Ayrıntı: [docs/rag_seed/README.md](rag_seed/README.md).

## Docker

Chroma kalıcılığı için backend volume’da dizin kullanılıyor:

```yaml
volumes:
  - /app/chroma:/app/chroma
```

Bu dizinin yazılabilir olduğundan emin olun.
