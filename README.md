# Server Management System

Sunucu yönetim sistemi - VMware, Hyper-V, KVM ve fiziksel sunucuları tek bir arayüzden yönetin.

## Özellikler

- 🖥️ **Sunucu Yönetimi**: Tüm sunucularınızı tek bir arayüzden görüntüleyin ve yönetin
- ☁️ **Hypervisor Entegrasyonu**: VMware vCenter, Hyper-V, KVM, Proxmox desteği
- 🤖 **AI Asistan**: Ollama tabanlı akıllı sunucu yönetim asistanı
- 📊 **Monitoring**: Prometheus ve Node Exporter ile metrik toplama
- 🔧 **Uzaktan Yönetim**: SSH üzerinden komut çalıştırma
- 🚀 **Node Exporter Kurulumu**: Otomatik Node Exporter dağıtımı

## Kurulum

### Gereksinimler

- Docker & Docker Compose
- Podman (opsiyonel)
- Ollama (AI asistan için)

### Başlatma

```bash
# Servisleri başlat
docker-compose up -d

# Logları izle
docker-compose logs -f
```

### Erişim

- Frontend: http://localhost:3000
- Backend API: http://localhost:8000
- API Docs: http://localhost:8000/docs
- Prometheus: http://localhost:9090

## Yapı

```
├── backend/
│   ├── app/
│   │   ├── api/          # API endpoints
│   │   ├── core/         # Config, database
│   │   ├── models/       # SQLAlchemy models
│   │   ├── schemas/      # Pydantic schemas
│   │   ├── services/     # Business logic
│   │   └── tasks/        # Background tasks
│   ├── alembic/          # Database migrations
│   └── Dockerfile
├── frontend/
│   ├── src/
│   │   ├── components/   # React components
│   │   ├── pages/        # Page components
│   │   └── api/          # API client
│   └── Dockerfile
├── prometheus/
│   ├── prometheus.yml
│   └── targets/
└── docker-compose.yml
```

## API Endpoints

### Sunucular
- `GET /api/v1/servers/` - Tüm sunucuları listele
- `POST /api/v1/servers/` - Yeni sunucu ekle
- `PUT /api/v1/servers/{id}` - Sunucu güncelle
- `DELETE /api/v1/servers/{id}` - Sunucu sil

### Hypervisor'lar
- `GET /api/v1/hypervisors/` - Tüm hypervisor'ları listele
- `POST /api/v1/hypervisors/` - Yeni hypervisor ekle
- `PUT /api/v1/hypervisors/{id}` - Hypervisor güncelle
- `DELETE /api/v1/hypervisors/{id}` - Hypervisor sil

### AI Chat
- `POST /api/v1/chat/` - AI asistanla sohbet

### Monitoring
- `POST /api/v1/monitoring/node-exporter/install/{server_id}` - Node Exporter kur
- `POST /api/v1/monitoring/node-exporter/uninstall/{server_id}` - Node Exporter kaldır
- `GET /api/v1/monitoring/node-exporter/status/{server_id}` - Node Exporter durumu

## Geliştirme

```bash
# Backend geliştirme
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload

# Frontend geliştirme
cd frontend
npm install
npm run dev
```

## Lisans

MIT
