# Dropt → ainew Level 1 cutover notes

## Bu host (ainew)

- Prod: `COMPOSE_PROJECT_NAME=ainew docker compose -f docker-compose.prod.yml up -d`
  (`.env` içinde `COMPOSE_PROJECT_NAME=ainew` önerilir; UI `https://<ip>`)
- Dev: `docker compose -f docker-compose.yml up -d` (UI `:3000`)
- Dropt sidecar her iki compose’ta include edilir
- Servisler: `dropt_api` (:8001), `dropt_worker`, `dropt_db` (:5433), `dropt_redis` (:6380)
- Frontend yok (Dropt UI ainew Level 1 altında)
- Proxy: nginx `/api/dropt/*` → `127.0.0.1:8001/api/*` (+ WS jobs/terminal)
- Auth: `POST /api/v1/level1/dropt-session` (AINEW_BRIDGE_SECRET)
- Sunucu map: Linux Sunucular → `POST /api/v1/level1/servers/{id}/ensure`
- Otomasyon credential: Level 1 → Ayarlar → Otomasyon (root | local/sudo | ad/dzdo)

## 192.168.1.133

Taşıma sonrası Dropt portal bağımlılığı kapatılabilir:

1. Bu hostta sidecar health + Level 1 console smoke doğrulandıktan sonra
2. 133 üzerinde `app-api-1` / `app-worker-1` / `app-frontend-1` durdurulabilir
3. DB dump yedek: `$DATA_DIR/dropt/dttportal.dump` (örn. varsayılan kurulumda `/data/data/dropt/…`)
4. Geri dönüş: dump’ı yeniden yükle + `docker compose -f docker-compose.dropt.yml up -d`

## Bilinçli ertelenenler

- Sistem log sayfası (sonraya)
- Dropt asistan / portal kullanıcıları UI
