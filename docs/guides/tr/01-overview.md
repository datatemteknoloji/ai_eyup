# ainew — Ana GUIDE

Bu belge **ainew** ürününün tamamını anlatır: amaç, kimler kullanır, sistem gereksinimleri, kurulum, konteyner yığını, backend / frontend / veri katmanı, AI modelinin nasıl çalıştığı ve sol menüdeki her işlem.

Canlı envanter dökümü değildir. Menü yolları `Layout.tsx` ile uyumludur.

---

## 1. Executive Summary

### 1.1 System Purpose

ainew, veri merkezinde **kendi sunucunuzda** çalışan altyapı operasyon platformudur. Tek oturumda:

- Linux (SSH) ve Windows (WinRM) sunucu yönetimi
- VMware vCenter, oVirt / OLVM, Proxmox, Hyper-V, OpenShift Virtualization envanteri
- OpenShift Container Platform (cluster, node, proje, pod, KubeVirt VM)
- Oracle Exadata rack / compute / cell
- Level 1 day-2 işletim (Dropt: Talep → Preview → Apply)
- Metrik, olay, incident, doğal dil asistanı ve denetim

Çıkarım **yerel Ollama** veya yöneticinin tanımladığı **uzak LLM** (`REMOTE_LLM_*`) ile yürür. Uzak model cevap vermezse sohbet **açık hata** verir; sessizce yerel modele düşülmez.

### 1.2 Target Users

| Rol | Ne için |
|-----|---------|
| Platform yöneticisi | Kullanıcı, RBAC, Ayarlar, entegrasyon, yedek, güncelleme |
| Linux operatörü | Sunucu, metrik, paket/yama, repo, Ansible, Linux sohbet, Level 1 |
| Windows operatörü | WinRM, Event Log, Update, Windows sohbet |
| Sanallaştırma operatörü | Dashboard, kapasite raporları, virt AIOps |
| OpenShift / oVirt operatörü | OCP komuta merkezi, OLVM/oVirt, KubeVirt |
| Yönetici | Executive özet ve tüm altyapı sohbeti |

Admin tüm RBAC modüllerini görür. Diğer kullanıcılar yalnızca atanan modülleri görür.

### 1.3 Problems Solved

Dağınık vCenter, OLVM, SSH, WinRM ve OCP konsollarını tek üründe toplamak; “hangi VM, hangi datastore, host CPU?” sorularını sohbet ve raporla yanıtlamak; Level 1 değişikliğini auditable iş yapmak; veriyi müşteri ağında tutmak.

### 1.4 Major Capabilities

Envanter hub (UCMDB, hypervisor, fiziksel host, Exadata, OCP) · Prometheus metrikleri · paket/yama/repo/Ansible · platform AIOps · Level 1 Dropt · birleşik sohbet ve onaylı ajan · bilgi bankası · özel raporlar.

**RBAC:** `executive`, `linux`, `windows`, `virtualization`, `exadata`, `openshift`, `ai_automation`, `integrations`, `level1`, `applications`, `knowledge`, `custom_reports`.

---

## 2. System Overview

### 2.1 High-Level Architecture

```diagram
                         ┌──────────────────────┐
                         │   Operatör tarayıcı  │
                         │   (Chrome / Edge)    │
                         └──────────┬───────────┘
                                    │  HTTP / HTTPS
                                    ▼
                         ┌──────────────────────┐
                         │  Frontend (Nginx)    │
                         │  React SPA  :3000    │
                         │  /api/v1 → :8000     │
                         └──────────┬───────────┘
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │  Backend (FastAPI)   │
                         │  host network :8000  │
                         └──────────┬───────────┘
              ┌─────────────┬───────┼────────┬──────────────┐
              ▼             ▼       ▼        ▼              ▼
        TimescaleDB      Redis   Prometheus  LLM        Dış sistemler
        PG15 :5432       :6379   + Pushgateway  Ollama     vCenter / OLVM
        pgvector                 :9090/:9091  veya uzak    SSH / WinRM
        (ainew DB)               Celery worker             OCP / Exadata
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │  Level 1 Dropt       │
                         │  API :8001           │
                         │  ayrı Postgres :5433 │
                         │  ayrı Redis :6380    │
                         └──────────────────────┘
```

Tarayıcı yalnızca SPA ve API’yi görür. SSH, WinRM ve hypervisor çağrıları **backend’den** çıkar. Level 1 yazma işleri Dropt’a gider. **ainew veritabanı ile Dropt veritabanı karıştırılmaz.**

### 2.2 Architecture Principles

- Self-hosted; varsayılan harici cloud LLM yoktur
- Modül RBAC menü ve sohbet kapsamını keser
- Sohbet tool-first: envanter/metrik DB ve bağlayıcılardan gelir
- Prometheus sohbeti **yalnızca PromQL** — scrape / `prometheus.yml` / target JSON yazılmaz
- Level 1: Talep ID → Preview → Apply
- LLM fail-fast (sessiz local fallback yok)
- Üretim yığını **konteyner** (Docker Compose; imaj yükleme docker veya podman)

### 2.3 Technology Stack

| Katman | Ne |
|--------|-----|
| Frontend | React 18, TypeScript, Vite, Tailwind, TanStack Query, Recharts — **nginx** ile servis |
| Backend | Python 3.11, FastAPI, SQLAlchemy 2, Alembic, Paramiko, LangGraph |
| Veri | TimescaleDB (PostgreSQL 15), pgvector |
| Kuyruk | Redis 7, Celery worker |
| İzleme | Prometheus, Pushgateway; host’larda node_exporter / windows_exporter |
| AI | Ollama (yerel) ve/veya `REMOTE_LLM_*`; gömme: `nomic-embed-text` |
| Level 1 | Dropt sidecar (ayrı FastAPI, ayrı Postgres 16, ayrı Redis) |
| Çalıştırma | **Docker Compose** (desteklenen kurulum yolu). Imaj yükleme: `docker load` veya `podman load` |

### 2.4 Runtime — konteynerler ve portlar

Desteklenen ürün dağıtımı **Docker Engine + Docker Compose v2** ile çalışır. `install-rhel.sh` yoksa Docker CE kurar. Offline paket imajları `docker load` veya **podman load** ile içeri alınabilir (güncelleme betikleri her iki motoru da tanır). **Çalışan yığın Compose’dur**; ainew’i OpenShift/Kubernetes Operator olarak dağıtmak bu ürünün kurulum modeli değildir.

```diagram
  YÖNETİM HOSTU (RHEL 9 / Rocky / Alma — x86_64)
  =====================================================================
  :3000   frontend          nginx + React SPA
  :8000   backend           FastAPI  (network_mode: host)
          worker            Celery   (aynı backend imajı)
  :5432   db                TimescaleDB PG15     → DATA_DIR/postgres
  :6379   redis             Redis 7              → DATA_DIR/redis
  :9090   prometheus        (compose’ta varsa)
  :9091   pushgateway
  :8001   dropt-api         Level 1              → ayrı ağ
  :5433   dropt-db          Postgres 16          → DATA_DIR/dropt/postgres
  :6380   dropt-redis       Redis 7              → DATA_DIR/dropt/redis
  :11434  ollama            isteğe bağlı profil  → DATA_DIR/ollama
  =====================================================================
```

| Servis | Konteyner adı (tipik) | Port | Not |
|--------|----------------------|------|-----|
| UI | `server_management_frontend` | 3000 | Baked nginx; kaynak mount yok |
| API | `server_management_backend` | 8000 | Host network — SSH için |
| Worker | `server_management_worker` | — | Filo işleri |
| DB | `server_management_db` | 5432 | ainew + Timescale + pgvector |
| Redis | `server_management_redis` | 6379 | Kuyruk / cache |
| Dropt API | `dropt_api` | 8001 | Level 1 |
| Dropt DB | `dropt_db` | 127.0.0.1:5433 | **Ayrı** Postgres |
| Ollama | `ollama` (profil) | 11434 | Yerel LLM |

`UVICORN_WORKERS=2` iken Python değişince reload yoktur: `docker restart server_management_backend`. UI değişince `docker compose build frontend && docker compose up -d frontend`.

### 2.5 Sistem gereksinimleri

| Kaynak | Minimum | Önerilen |
|--------|---------|----------|
| İşletim sistemi | RHEL 9.x x86_64 (Rocky / AlmaLinux 9 uyumlu) | Aynı, güncel 9.x |
| CPU | 4 çekirdek | 8+ |
| RAM | 8 GB | 16 GB+ (yerel Ollama ile) |
| Disk | 50 GB boş (`INSTALL_DIR`, varsayılan `/data`) | 100 GB+ (metrik, imaj, repo) |
| GPU | Zorunlu değil | Yerel LLM için önerilir |
| Ağ | 80/443 UI; dahili 9090/9091; Dropt host-local 8001 | Hedef vCenter/SSH/OCP’ye çıkış |
| Yetki | root / sudo | — |
| Konteyner | Docker CE + Compose v2 | Offline imaj tar.gz |

Air-gap desteklenir: `scripts/build-distribution.sh` → `ainew-<sürüm>-linux-amd64.tar.gz` (Ollama imajı pakette yoktur; `with-ollama` / profil ayrıdır).

### 2.6 Nasıl kurulur

**A. Üretim (RHEL, önerilen)**

1. Release asset veya USB: `ainew-<sürüm>-linux-amd64.tar.gz`  
2. `tar xzf … && cd ainew-<sürüm>-linux-amd64`  
3. `sudo ./install-rhel.sh`  
   - Docker CE + Compose (yoksa)  
   - Kurulum dizini (varsayılan `/data`)  
   - `.env` (SECRET_KEY, parolalar)  
   - Imaj yükleme (`docker load` / ortamda podman varsa `podman load`)  
   - `docker compose -f docker-compose.prod.yml up -d`  
4. Tarayıcı: `https://<host>` veya `:3000`  
5. İlk admin parolası `.env` / kurulum çıktısı — hemen değiştirin  

Betik **idempotent**’tir; tekrar çalışınca mevcut `.env` ve sertifikayı bozmaz.

**B. Geliştirme hostu**

```
./scripts/dev-setup.sh
docker compose up -d
```

UI `:3000`, API `:8000`.

**C. Git clone** (registry yok, GitHub var): repodaki `dist/ainew-…` veya Release tar.

**Kurulmayanlar:** ham `podman play kube` / OpenShift Operator ile resmi paket yok. Podman yalnızca **imaj yükleme** ve bazı müşteri hostlarında motor tespiti içindir. Ürün Compose dosyası Docker Compose semantiği ile doğrulanır.

### 2.7 Kalıcı veri

`DATA_DIR="$INSTALL_DIR/data"` — varsayılan `/data/data`.

```diagram
INSTALL_DIR  (ör. /data)
├── docker-compose.yml / docker-compose.prod.yml
├── .env
├── VERSION
├── images/                  ← offline tar
└── data/                    ← DATA_DIR
    ├── postgres/            ainew Timescale
    ├── redis/
    ├── chroma/              eski vektör (migrate)
    ├── repos/  uploads/  updates/
    ├── prometheus/
    ├── certs/
    ├── ollama/
    └── dropt/               Level 1 DB + redis
```

Uygulama verisini izinsiz silmeyin.
