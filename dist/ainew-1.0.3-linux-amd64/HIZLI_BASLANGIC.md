# 🚀 Hızlı Başlangıç Rehberi

## ⚡ 3 Adımda Çalıştır

### 1️⃣ .env Dosyası Oluştur
```bash
# .env.example'dan kopyala
cp .env.example .env

# SECRET_KEY üret
openssl rand -hex 32

# .env dosyasını düzenle
nano .env
```

**Zorunlu Ayarlar:**
```bash
SECRET_KEY=<yukarıda-ürettiğin-key>
POSTGRES_PASSWORD=güçlü_şifre_123
CORS_ORIGINS=http://localhost:3000
```

### 2️⃣ Docker'ı Başlat
```bash
# Tüm servisleri başlat
docker compose up -d

# Logları izle (opsiyonel)
docker logs -f server_management_backend
```

### 3️⃣ Tarayıcıda Aç
```bash
# Frontend
http://localhost:3000

# Backend API Docs
http://localhost:8000/docs
```

---

## ✅ Kontrol Listesi

- [ ] .env dosyası oluşturuldu
- [ ] SECRET_KEY set edildi
- [ ] POSTGRES_PASSWORD değiştirildi
- [ ] Docker container'ları çalışıyor
- [ ] Frontend açıldı (localhost:3000)
- [ ] Backend health check OK (/health)

---

## 🔧 Sorun Giderme

### Backend başlamıyor
```bash
# Hata: SECRET_KEY environment variable is required
# Çözüm: .env dosyasında SECRET_KEY set et
```

### Frontend 502 hatası
```bash
# Backend'in başlamasını bekle (30 saniye)
docker logs server_management_backend --tail 50
```

### Database bağlantı hatası
```bash
# DB container'ı çalışıyor mu?
docker ps | grep server_management_db

# Restart dene
docker compose restart db backend
```

---

## 📚 Detaylı Dokümantasyon

- **Proje Audit:** `DETAYLI_AUDIT_RAPORU.md`
- **Yapılan Düzeltmeler:** `DUZELTMELER_OZET.md`
- **API Kullanımı:** http://localhost:8000/docs

---

**Not:** İlk çalıştırmada Ollama model'leri indirilecektir, bu 5-10 dakika sürebilir.
