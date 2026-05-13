# datatem AI — Proje Bağlamı

## Proje: Server Management & AIOps Platform
**Konum:** `/home/datatem/ainew`
**Stack:** FastAPI + React + PostgreSQL/TimescaleDB + Redis + Prometheus + Ollama

## Servisler (Docker Compose)
| Servis | Port |
|--------|------|
| Backend (FastAPI) | :8000 (host network) |
| Frontend (React/Nginx) | :3000 |
| PostgreSQL + TimescaleDB | :5432 |
| Redis | :6379 |
| Prometheus | :9090 |
| Pushgateway | :9091 |

## Frontend Deployment Kuralı
**ÖNEMLİ:** `docker compose restart frontend` JS'yi yeniden derlemez!
```bash
docker compose build --no-cache frontend && docker compose up -d frontend
# Sonra tarayıcıda Ctrl+Shift+R (hard refresh)
```

## Mevcut Özellikler
- **Sunucu Yönetimi** — SSH, Node Exporter, metrik toplama
- **Hypervisor/ESX İzleme** — vCenter SOAP API, CPU/RAM/Disk
- **AIOps** — Events, Incidents, Anomaly Detection (ısı haritası)
- **AI Chat** — Ollama (http://192.168.1.222:11434), Linux/Virt uzman persona
- **RAG** — ChromaDB, döküman tabanlı soru-cevap
- **Ansible/AWX** — Ad-hoc komut, playbook
- **Paket & Yama** — .deb/.rpm deploy, apt/yum upgrade, SSH tabanlı
- **Local Repo** — Satellite benzeri RPM mirror (RHEL/OEL/Rocky/Ubuntu)

## Local Repo Önemli Bilgiler
- Repolar: `/var/lib/server_management/repos/` (bind mount → `/app/repos/`)
- HTTP serve: `http://host:8000/repos/{repo-slug}/`
- RHEL SCA modu: `consumers/{uuid}/certificates` endpoint'i kullanılır
- Backend restart → yarım kalan sync'ler otomatik devam eder

## Key Dosyalar
```
backend/
  app/
    api/         — router.py, servers.py, chat.py, repositories.py, packages.py
    models/      — server.py, repository.py, package_job.py, hypervisor_metric.py
    services/    — repo_sync_service.py, rhsm_sync_service.py, package_service.py
                   vcenter_client.py, esx_metric_sync.py, ssh_manager.py
    main.py      — startup: yarım sync'leri devam ettirir
    core/        — config.py, database.py, init_timescale.py
frontend/
  src/
    pages/       — Dashboard, Servers, Repositories, PackageManager, Chat...
    components/  — Layout.tsx (sidebar grubu: AIOps altında Events/Incidents/Anomaly)
docker-compose.yml
```

## Önemli Notlar
- vCenter: 192.168.1.102, `vim25/2.5u2` eski API → `RetrieveProperties` kullan
- Datastore stale NFS filtresi: `accessible=false` veya `freeSpace >= capacity`
- RHEL SCA: attach yerine `GET /consumers/{uuid}/certificates` (225KB cert)
- DB: `repo_sources` tablosunda `sync_method`, `rhsm_repo_id`, `mirror_*` kolonları
- Chat timeout: 20-40sn, SSH paralel, vmstat/iostat 1 5 (10 değil)
