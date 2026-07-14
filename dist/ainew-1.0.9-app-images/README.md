# ainew 1.0.9 — uygulama imajları

Bu paket **sadece** uygulama imajlarını içerir:

- `ainew-backend:1.0.9`
- `ainew-frontend:1.0.9`

TimescaleDB / Redis / Prometheus **yoktur** (mevcut sunucuda kalır veya Docker Hub'dan çekilir).

## Yükleme

```bash
cd ainew-1.0.9-app-images
sudo ./load.sh
```

## Mevcut kurulumda güncelleme

`/opt/ainew/.env` içinde:

```
APP_VERSION=1.0.9
BACKEND_IMAGE=ainew-backend:1.0.9
FRONTEND_IMAGE=ainew-frontend:1.0.9
```

```bash
cd /opt/ainew
docker compose -f docker-compose.prod.yml up -d backend frontend
```
