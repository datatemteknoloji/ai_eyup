# AI Model Seçimi - Kullanım Kılavuzu

## 🎯 Yeni Özellik: Model Seçimi

Artık Chat sayfasında farklı AI modelleri arasında seçim yapabilirsiniz!

## 🚀 Kullanım

### Frontend (Chat Sayfası)
1. **Chat** sayfasına gidin
2. Sol üstte **mor renkli dropdown** göreceksiniz
3. Model seçin:
   - `llama3.2:3b (3.2B)` - Varsayılan, hızlı
   - Diğer kurulu modeller otomatik görünür

### Backend API
```bash
# Model ile chat mesajı
curl -X POST http://localhost:8000/api/v1/chat/ \
  -H "Content-Type: application/json" \
  -d '{
    "message": "Merhaba",
    "session_id": 60,
    "model": "llama3.2:3b"
  }'

# Mevcut modelleri listele
curl http://localhost:8000/api/v1/chat/models
```

## 📊 Model Karşılaştırması

### llama3.2:3b (Varsayılan)
```
✅ Hız: Çok hızlı (2-5s)
✅ RAM: Düşük (~4GB)
⚠️ Türkçe: Orta
⚠️ Akıllık: Basit
```

### llama3.1:8b (Önerilen Upgrade)
```
✅ Hız: Hızlı (5-10s)
✅ RAM: Orta (~8GB)
✅ Türkçe: İyi
✅ Akıllık: İyi
```

### llama3.1:70b (En İyi)
```
⚠️ Hız: Yavaş (30-60s)
⚠️ RAM: Yüksek (~48GB)
✅ Türkçe: Çok iyi
✅ Akıllık: Çok iyi
```

## 🔧 Yeni Model Kurulumu

### Ollama'ya Model Ekleme
```bash
# Host makinesinde
ollama pull llama3.1:8b      # 8B model (önerilen)
ollama pull llama3.1:70b     # 70B model (çok güçlü)
ollama pull mistral:7b       # Alternatif
ollama pull codellama:13b    # Kod için özel

# Kurulu modelleri listele
ollama list
```

### Sistem Gereksinimleri
| Model | RAM | Disk | Hız |
|-------|-----|------|-----|
| 3b | 4GB | 2GB | ⚡⚡⚡ |
| 8b | 8GB | 5GB | ⚡⚡ |
| 13b | 16GB | 8GB | ⚡ |
| 70b | 48GB+ | 40GB | 🐌 |

## 💡 Model Seçim Tavsiyeleri

### Genel Sorular
```
🎯 llama3.2:3b veya llama3.1:8b
- "Merhaba"
- "Sunucu durumu?"
- "Yardım et"
```

### Teknik Analiz
```
🎯 llama3.1:8b veya llama3.1:70b
- "Bu sunucuda performans sorunu var, analiz et"
- "Log'lara göre ne yapmalıyım?"
- "En iyi çözüm ne?"
```

### Türkçe Doğal Dil
```
🎯 llama3.1:8b veya llama3.1:70b
- "Kaç tane online sunucumuz var?"
- "Geçen hafta hangi sunucular sorun çıkardı?"
- "Bu ayın raporu nasıl?"
```

### Kod/Script Üretme
```
🎯 codellama:13b
- "Python script yaz..."
- "Bash komut satırı ver..."
- "SQL sorgusu oluştur..."
```

## 🔄 Model Değiştirme

### Otomatik
- Model seçimi **session bazında** kaydedilmez
- Her mesajda seçili modeli kullanır
- Session değiştirince model seçimi korunur

### Manuel Test
```bash
# Model 1 ile test
curl -X POST http://localhost:8000/api/v1/chat/ \
  -d '{"message":"Test","session_id":60,"model":"llama3.2:3b"}'

# Model 2 ile test
curl -X POST http://localhost:8000/api/v1/chat/ \
  -d '{"message":"Test","session_id":60,"model":"llama3.1:8b"}'

# Yanıtları karşılaştır
```

## 📈 Performans İzleme

### Backend Logları
```bash
docker logs -f server_management_backend | grep -i "model\|ollama"
```

### Model Response Time
```
llama3.2:3b  → 2-5s   ⚡⚡⚡
llama3.1:8b  → 5-10s  ⚡⚡
llama3.1:13b → 10-20s ⚡
llama3.1:70b → 30-60s 🐌
```

## ⚠️ Troubleshooting

### Model Listesi Boş
```bash
# Backend'i kontrol et
curl http://localhost:8000/api/v1/chat/models

# Ollama'yı kontrol et
curl http://192.168.1.166:11434/api/tags

# Ollama çalışmıyorsa
systemctl status ollama
systemctl restart ollama
```

### Model Yavaş
```bash
# GPU kullanımı kontrol et
nvidia-smi  # NVIDIA GPU varsa

# CPU kullanımı kontrol et
top | grep ollama

# Model yükünü azalt
ollama pull llama3.2:3b  # Daha küçük model
```

### Timeout
```bash
# Backend timeout artır (şu an 120s)
# backend/app/core/config.py
OLLAMA_TIMEOUT_SECONDS = 180  # 3 dakika
```

## 🎨 Frontend Görünüm

```
┌─────────────────────────────────────────┐
│ [llama3.2:3b (3.2B) ▼] [Sunucu seç ▼] │
│                                         │
│ ┌─────────────────────────────────────┐ │
│ │ User: Merhaba                       │ │
│ │ AI: Merhaba! Nasıl yardımcı...     │ │
│ └─────────────────────────────────────┘ │
│                                         │
│ [Mesajınız...]              [Gönder]   │
└─────────────────────────────────────────┘
```

**Mor Dropdown**: Model seçimi
**Gri Dropdown**: Sunucu seçimi

## 🚀 İleri Seviye

### Custom Model Training
```bash
# Kendi modelinizi eğitin
ollama create my-turkish-model -f Modelfile

# Modelfile örneği:
FROM llama3.1:8b
PARAMETER temperature 0.8
SYSTEM "Sen bir Türkçe sunucu yönetim asistanısın..."
```

### Model Ensemble (Gelecek)
```python
# Birden fazla model kullan, en iyi yanıtı seç
models = ["llama3.2:3b", "llama3.1:8b"]
responses = [get_response(msg, model) for model in models]
best = select_best(responses)
```

## 📚 Kaynaklar

- Ollama Docs: https://ollama.ai/library
- Model Karşılaştırma: https://ollama.ai/blog/model-comparison
- Türkçe Modeller: (Custom training gerekiyor)

---

**Güncelleme**: 4 Şubat 2026
**Versiyon**: 1.1.0
