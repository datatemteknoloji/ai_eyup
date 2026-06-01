# Server Management System - Proje Özeti

## 🎯 Proje Amacı
VMware, Hyper-V, KVM gibi hypervisor'lar ve fiziksel sunucuları tek bir merkezi arayüzden yönetmek, izlemek ve AI asistanı ile etkileşimli şekilde yönetmek.

## 📦 Mimari

### Backend (FastAPI + Python)
- **API Endpoints**: REST API sunucusu
- **Database**: PostgreSQL (TimescaleDB) - sunucu ve chat verileri
- **AI Integration**: Ollama (llama3.2:3b model)
- **Monitoring**: Prometheus + Node Exporter entegrasyonu
- **SSH Management**: Paramiko ile uzak sunucu yönetimi
- **Background Tasks**: Otomatik sunucu health check (5 dakikada bir)

### Frontend (React + TypeScript + Vite)
- **UI Framework**: React 18 + TypeScript
- **Styling**: TailwindCSS
- **State Management**: TanStack React Query
- **Routing**: React Router v6
- **Build Tool**: Vite

### Infrastructure
- **Docker Compose**: Tüm servisler containerized
- **Services**:
  - PostgreSQL (TimescaleDB)
  - Redis
  - Prometheus
  - Pushgateway
  - Backend (FastAPI)
  - Frontend (React)

## 🚀 Ana Özellikler

### 1. Sunucu Yönetimi
- ✅ Sunucu listesi (filtreleme, sıralama, arama)
- ✅ Sunucu ekleme/güncelleme/silme
- ✅ Durum takibi: ONLINE, OFFLINE, WARNING, CRITICAL
- ✅ Otomatik health check (TCP ping + SSH test)
- ✅ AI Ready sunucu işaretleme
- ✅ SSH credential yönetimi

### 2. Node Exporter Yönetimi
- ✅ Otomatik Node Exporter kurulumu (SSH üzerinden)
- ✅ Binary dağıtım (SCP, HTTP, base64)
- ✅ Systemd servis yapılandırması
- ✅ Prometheus target otomatik ekleme
- ✅ Kurulum adımları görsel takibi
- ✅ Kurulum iptal etme (timeout: 120s)
- ✅ Kurulu Node Exporter'ların listesi

### 3. AI Chat Asistanı
- ✅ Ollama tabanlı AI asistan (llama3.2:3b)
- ✅ Session tabanlı chat (kalıcı)
- ✅ Sunucu context'i ile akıllı yanıtlar
- ✅ Prometheus metrik entegrasyonu
- ✅ Performans analizi (CPU, RAM, disk sorguları)
- ✅ Session başlık düzenleme
- ✅ Session silme
- ✅ Mesaj geçmişi

### 4. Monitoring & Metrics
- ✅ Prometheus entegrasyonu
- ✅ Node Exporter metrik toplama
- ✅ Pushgateway desteği
- ✅ Gerçek zamanlı metrik sorgulama
- ⚠️ Live Metrics dashboard (planlı)

### 5. Hypervisor Entegrasyonu
- ⚠️ VMware vCenter entegrasyonu (kısmen)
- ⚠️ Hyper-V desteği (planlı)
- ⚠️ KVM/Proxmox desteği (planlı)

## 🔧 Teknik Detaylar

### Backend Yapısı
```
backend/
├── app/
│   ├── api/                    # API endpoints
│   │   ├── chat.py            # AI Chat endpoints
│   │   ├── servers.py         # Sunucu CRUD + health check
│   │   ├── monitoring.py      # Node Exporter yönetimi
│   │   └── hypervisors.py     # Hypervisor yönetimi
│   ├── core/
│   │   ├── config.py          # Uygulama ayarları
│   │   └── database.py        # SQLAlchemy setup
│   ├── models/                # Database models
│   │   ├── server.py
│   │   ├── chat_session.py
│   │   └── hypervisor.py
│   ├── services/
│   │   └── monitoring/
│   │       ├── node_exporter_installer.py    # SSH ile kurulum
│   │       ├── server_connector.py           # SSH helper
│   │       ├── prometheus_metrics.py         # Prometheus API
│   │       ├── prometheus_target_manager.py  # Target yönetimi
│   │       └── server_health_checker.py      # Durum kontrolü
│   ├── background_tasks.py    # Otomatik görevler
│   └── main.py               # FastAPI app
```

### Frontend Yapısı
```
frontend/src/
├── pages/
│   ├── Servers.tsx           # Ana sunucu yönetim sayfası
│   ├── Chat.tsx              # AI Chat arayüzü
│   ├── LiveMetrics.tsx       # Prometheus metrikleri (WIP)
│   └── Hypervisors.tsx       # Hypervisor yönetimi
├── config/
│   └── api.ts               # API base URL
└── main.tsx                 # React app entry
```

### Database Schema

**servers**
- id, name, hostname, ip_address, status
- os_type, os_version, server_type
- cpu_cores, memory_gb, ai_ready
- connection_config (JSON: SSH credentials)
- created_at, updated_at

**chat_sessions**
- id, title, server_ids (array)
- created_at, updated_at

**chat_messages**
- id, session_id, role (user/assistant), content
- created_at

**hypervisors**
- id, name, type, connection_info
- created_at, updated_at

## ⚙️ Konfigürasyon

### Environment Variables
```bash
# Database
DATABASE_URL=postgresql://postgres:postgres@postgres:5432/server_management

# Ollama
OLLAMA_URL=http://192.168.1.166:11434
OLLAMA_DEFAULT_MODEL=llama3.2:3b
OLLAMA_TIMEOUT_SECONDS=120

# Prometheus
PROMETHEUS_URL=http://prometheus:9090
PUSHGATEWAY_URL=http://pushgateway:9091

# Node Exporter
NODE_EXPORTER_STORAGE_PATH=/app/static/node_exporter
NODE_EXPORTER_DISTRIBUTION_METHOD=scp
```

### Ports
- Frontend: 3000
- Backend: 8000
- Prometheus: 9090
- Pushgateway: 9091
- PostgreSQL: 5432 (internal)
- Redis: 6379 (internal)
- Ollama: 11434 (external host)

## 🔄 Background Tasks

### Health Check (5 dakika interval)
1. Tüm sunucuları tara
2. TCP ping (SSH portuna)
3. SSH bağlantı testi (credential varsa)
4. Durum güncelle:
   - TCP fail → OFFLINE
   - TCP OK + SSH OK → ONLINE
   - TCP OK + SSH fail → WARNING
5. Database'e kaydet

## 📊 AI Chat İş Akışı

### Message Flow
1. Kullanıcı mesaj gönderir
2. Session kontrol/oluşturma
3. Seçili sunucu context'i hazırla
4. **Performans sorularında**: Prometheus metrik context'i ekle
5. Ollama'ya prompt gönder (120s timeout)
6. Yanıtı DB'ye kaydet ve frontend'e döndür

### AI Prompt Yapısı
```
Sen bir sunucu yönetim asistanısın. Türkçe yanıt ver.

Seçili sunucular:
- sunucu1 (192.168.1.100): ONLINE, CPU: 8, RAM: 16GB
- sunucu2 (192.168.1.101): ONLINE, CPU: 4, RAM: 8GB

[Metrik sorularında]
📋 Mevcut Prometheus Metrikleri:
  - node_cpu_seconds_total
  - node_memory_MemAvailable_bytes
  ...

Kullanıcı sorusu: {message}

ÖNEMLİ: Yukarıdaki metrikleri kullanarak cevapla...
```

## 🐛 Bilinen Sorunlar ve Çözümler

### 1. ✅ ÇÖZÜLDÜ: Health Check Performansı
**Sorun**: Her dakika 134 sunucuya TCP ping = API yavaşlaması
**Çözüm**: Interval 60s → 300s (5 dakika)

### 2. ✅ ÇÖZÜLDÜ: Prometheus Context Performansı
**Sorun**: Her chat mesajında Prometheus'tan metrik çekme
**Çözüm**: Sadece performans sorularında metrik çek (keyword kontrolü)

### 3. ✅ ÇÖZÜLDÜ: Ping Problemi (Rootless Container)
**Sorun**: ICMP ping rootless container'da çalışmıyor
**Çözüm**: TCP ping kullan (SSH portuna socket bağlantısı)

### 4. ✅ ÇÖZÜLDÜ: Ollama Timeout
**Sorun**: 60s timeout yeterli değil
**Çözüm**: Timeout 120s'ye çıkarıldı

### 5. ⚠️ KISMİ: Frontend Port Değişimi
**Sorun**: Vite otomatik port değiştiriyor
**Çözüm**: `strictPort: true` eklendi (3000 kullanılamıyorsa fail)

## 📝 TODO / Planlanan Özellikler

### Kısa Vadeli
- [ ] AI Chat frontend hızlandırma (loading states)
- [ ] Live Metrics dashboard tamamlama
- [ ] Toplu sunucu işlemleri
- [ ] Export/Import (CSV, JSON)

### Orta Vadeli
- [ ] VMware vCenter otomatik VM keşfi
- [ ] Hyper-V entegrasyonu
- [ ] Alert sistemi (email, webhook)
- [ ] Kullanıcı/rol yönetimi
- [ ] Audit log

### Uzun Vadeli
- [ ] Kubernetes entegrasyonu
- [ ] Multi-tenant desteği
- [ ] Advanced dashboard (Grafana benzeri)
- [ ] Ansible playbook entegrasyonu

## 🚦 Durum: Aktif Geliştirme

**Son Güncelleme**: 4 Şubat 2026
**Versiyon**: 1.0.0 (Alpha)
**Geliştirici**: DataTem Team

---

## 🛠️ Geliştirme Notları

### Backend Restart
```bash
docker restart server_management_backend
docker logs -f server_management_backend
```

### Frontend Rebuild
```bash
cd frontend
npm run build
docker restart server_management_frontend
```

### Database Reset
```bash
docker exec -it server_management_db psql -U postgres -d server_management -c "DROP SCHEMA public CASCADE; CREATE SCHEMA public;"
```

### Health Check Trigger
```bash
curl -X POST http://localhost:8000/api/v1/servers/check-health
```

### Test Ollama
```bash
curl -X POST http://192.168.1.166:11434/api/generate \
  -d '{"model":"llama3.2:3b","prompt":"Test","stream":false}'
```
