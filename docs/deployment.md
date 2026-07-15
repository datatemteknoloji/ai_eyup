# Deployment

ainew is deployed via Docker Compose. All services run as containers except Ollama, which runs on the host or a dedicated GPU server.

---

## Environment variables reference

Create a `.env` file in the project root. All variables have defaults except `SECRET_KEY` and `POSTGRES_PASSWORD`.

| Variable | Default | Description |
|---|---|---|
| `SECRET_KEY` | **required** | JWT signing key. Generate with `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | `postgres` | PostgreSQL password. Change in production |
| `OLLAMA_URL` | `http://127.0.0.1:11434` | Ollama API base URL |
| `OLLAMA_TIMEOUT_SECONDS` | `60` | Seconds before an Ollama request times out |
| `PROMETHEUS_URL` | `http://localhost:9090` | Prometheus API URL (for metric queries) |
| `PUSHGATEWAY_URL` | `http://localhost:9091` | Prometheus Pushgateway URL |
| `CORS_ORIGINS` | `http://localhost:3000` | Comma-separated list of allowed frontend origins |
| `ADMIN_DEFAULT_PASSWORD` | `admin123` | Initial admin password (only used if no users exist) |
| `AGENT_MODEL` | `llama3.2:3b` | Model used by the tool-calling AI Agent. Must already be pulled in Ollama |
| `AGENT_GUARD_ENABLED` | `false` | Whether a separate safety-classifier model screens Agent tool calls |
| `AGENT_GUARD_MODEL` | `llama3.2:3b` | Guard/safety-classifier model (only used if `AGENT_GUARD_ENABLED=true`) |
| `REMOTE_LLM_ENABLED` | `false` | Route all chat/agent calls to an OpenAI-compatible gateway (e.g. Bifrost) instead of local Ollama |
| `REMOTE_LLM_URL` | _(empty)_ | Gateway base URL (no `/v1/chat/completions` suffix) |
| `REMOTE_LLM_API_KEY` | _(empty)_ | Sent as-is in the `Authorization` header (no `Bearer ` prefix) |
| `REMOTE_LLM_MODEL` | _(empty)_ | Fixed model name to send to the gateway; falls back to the caller's requested model if empty |
| `REMOTE_LLM_VERIFY_SSL` | `true` | Set `false` only if the gateway uses a self-signed cert you trust and you have no CA bundle to give it |
| `REMOTE_LLM_CA_BUNDLE` | _(empty)_ | Path (inside the backend container) to a PEM file for the gateway's self-signed/internal CA cert — keeps verification **on** while trusting that one extra cert. Takes precedence over `REMOTE_LLM_VERIFY_SSL`. Drop the PEM in `${DATA_DIR}/certs/` on the host (already bind-mounted to `/app/certs` in `docker-compose.prod.yml`) and point this at e.g. `/app/certs/remote-llm-ca.pem` |

> `docker-compose.prod.yml` and `docker-compose.yml` load the backend's environment via `env_file: .env` —
> any variable in `.env` reaches the container automatically, so new settings never require a compose file change.

### Example `.env`

```bash
SECRET_KEY=a3f9e2b1c8d7...  # 64 hex chars from openssl rand -hex 32
POSTGRES_PASSWORD=secure-db-password
OLLAMA_URL=http://127.0.0.1:11434
OLLAMA_TIMEOUT_SECONDS=120
CORS_ORIGINS=https://infra.example.com
```

---

## Services

### Database (`db`)

- Image: `timescale/timescaledb:latest-pg15`
- Port: `5432` (host-mapped)
- Data: `/data/data/postgres` (prod varsayılan; `DATA_DIR`)

TimescaleDB is used for time-series metric storage. The backend auto-creates hypertables on startup via `init_timescaledb()`.

### Redis (`redis`)

- Image: `redis:7-alpine`
- Port: `6379` (host-mapped)
- Data: `/data/data/redis`

Used as a task queue backend (Celery) and for ephemeral caching.

### Backend (`backend`)

- Build context: `./backend/`
- Port: `8000` (host network)
- `network_mode: host` — required for direct SSH access to managed servers

**Volumes mounted:**
| Container path | Host path | Purpose |
|---|---|---|
| `/app/app` | `./backend/app` | Live-reload in dev |
| `/app/static` | `./backend/static` | Static file serving |
| `/prometheus/targets` | `./prometheus/targets` | Prometheus target files |
| `/app/chroma` | `/data/data/chroma` | ChromaDB vector store |
| `/app/repos` | `/data/data/repos` | Local RPM/DEB repo files |
| `/app/uploads` | `/data/data/uploads` | Uploaded package files |
| `/app/updates` | `/data/data/updates` | Platform self-update packages (prod) |

### Frontend (`frontend`)

- Build context: `./frontend/`
- Port: `3000 → 80` (container port 80, host port 3000)
- Nginx config: `./frontend/nginx.conf`

Nginx serves the React SPA and proxies `/api/` requests to the backend at `localhost:8000`.

---

## Data persistence

**Tek disk politikası:** sunucuda uygulama ve kalıcı veri `/data` altındadır (`/opt`, `/var/lib/server_management` kullanılmaz).

```
/data/                          # INSTALL_DIR — paket, compose, .env, images/
├── docker-compose.prod.yml
├── .env
├── VERSION
├── images/
└── data/                       # DATA_DIR (= /data/data)
    ├── postgres/
    ├── redis/
    ├── chroma/
    ├── repos/
    ├── uploads/
    ├── updates/                # GUI / SCP platform paketleri
    ├── prometheus/
    ├── certs/
    └── ollama/
/data/docker/                   # Docker data-root (imaj + volume; yeni kurulumda)
```

Create these directories before first run if they don't exist:

```bash
sudo mkdir -p /data/data/{postgres,redis,chroma,repos,uploads,updates,prometheus,certs,ollama}
sudo mkdir -p /data/docker/tmp
# Backend container appuser (uid 100 / gid 102) ile yazar
sudo chown -R 100:102 /data/data/chroma /data/data/uploads /data/data/repos /data/data/updates
```

Eski kurulumlarda chroma `root` sahipliğinde kaldıysa:

```bash
sudo chown -R 100:102 /data/data/chroma
# veya Docker ile:
docker run --rm -v /data/data/chroma:/chroma alpine chown -R 100:102 /chroma
```

---

## Production checklist

- [ ] `SECRET_KEY` set to a random 64-char hex string
- [ ] `POSTGRES_PASSWORD` changed from default
- [ ] `ADMIN_DEFAULT_PASSWORD` changed and default password updated in UI
- [ ] `CORS_ORIGINS` set to your actual frontend URL (not `localhost`)
- [ ] `/data` (kurulum + veri + docker data-root) ayrı disk veya yeterli alan
- [ ] Firewall: port 3000 open to users, port 8000 restricted to localhost only
- [ ] Ollama running with an appropriate model pulled
- [ ] Reverse proxy (Nginx/Caddy) with TLS in front of port 3000
- [ ] Log rotation configured for Docker container logs

---

## Upgrading

### Development stack (`docker-compose.yml`)

```bash
# Pull latest code
git pull

# Rebuild images (only backend/frontend if changed)
docker compose build backend frontend

# Restart with new images
docker compose up -d

# Check for startup errors
docker compose logs backend --tail=30
```

Database schema changes are applied automatically on startup via SQLAlchemy `create_all()` and the idempotent `ALTER TABLE IF NOT EXISTS` blocks in `main.py`.

### Production package (CLI)

```bash
tar xzf ainew-<version>-linux-amd64.tar.gz
cd ainew-<version>-linux-amd64
sudo ./update-rhel.sh --install-dir /data
# Geri alma:
#   cd /data && sudo ./rollback-rhel.sh
```

### Production package (GUI)

Admin → **Ayarlar → Platform Güncelleme**:

1. Paketi yükleyin **veya** sunucuya bırakın:
   ```bash
   scp ainew-<version>-linux-amd64.tar.gz root@host:/data/data/updates/
   ```
2. **Hazırla** → hedef sürümü onay kutusuna yazın → **Güncellemeyi Uygula**.
3. Overlay, `/api/v1/public/version` ile yeni sürümü bekler; ardından sayfa yenilenir.
4. **Son yedekten geri al** imaj etiketlerini son `pre-update-*` yedeğine döndürür (DB dump restore etmez).

Gereksinimler (prod compose’da varsayılan):

- `PLATFORM_UPDATE_ENABLED=true`
- `/var/run/docker.sock` backend’e mount
- `AINEW_INSTALL_DIR` (ör. `/data`) + `DATA_DIR/updates` (ör. `/data/data/updates`)
- Updater için host’ta `alpine:3.20` (veya `PLATFORM_UPDATER_IMAGE`) yüklü olmalı — air-gap’te pakete ekleyin veya önceden `docker load` edin

İşlem logları: `$DATA_DIR/updates/apply.log` ve `status.json`.

---

## Backup

```bash
# Backup PostgreSQL
docker exec server_management_db pg_dump -U postgres server_management > backup.sql

# Backup ChromaDB (vector store)
tar czf chroma-backup.tar.gz /data/data/chroma

# Backup repos
tar czf repos-backup.tar.gz /data/data/repos
```

---

## Production / customer install

The steps above describe the root `docker-compose.yml` — a **development** stack (live-mounted
backend source, HTTP only, no pinned image versions). For a customer or production install, use
the dedicated production path instead:

```bash
./scripts/build-distribution.sh          # assembles dist/ainew-<version>-linux-amd64/
cd dist/ainew-<version>-linux-amd64
sudo ./install-rhel.sh                   # RHEL/Rocky/AlmaLinux 9
```

This uses [`deploy/docker-compose.prod.yml`](../deploy/docker-compose.prod.yml) (pinned image
versions, immutable backend image, HTTPS, `localhost`-only DB/Redis) and
[`deploy/install-rhel.sh`](../deploy/install-rhel.sh) (Docker install, random secret generation,
self-signed TLS, firewalld rules). Full walkthrough: [INSTALL_RHEL.md](INSTALL_RHEL.md).

### Air-gapped / offline Ollama models

Don't bake LLM weights into the application image — they're multi-GB and already live in a
separate volume. Instead, pull models once on a connected machine and transfer the Ollama volume:

```bash
# On a machine with internet + models already pulled
./scripts/export-ollama-models.sh                # -> ollama-models.tar.gz

# On the air-gapped target, before starting the ollama service
./scripts/import-ollama-models.sh ollama-models.tar.gz
```

---

## Scaling considerations

The current architecture is single-node. For multi-host management at scale:

- Move PostgreSQL to a managed service (RDS, Supabase) or a dedicated server
- Move Redis to Redis Cluster or a managed service
- Consider a dedicated Prometheus instance with longer retention
- Ollama can be on a dedicated GPU server — update `OLLAMA_URL` in `.env`
- The backend is stateless (JWT auth) — you can run multiple instances behind a load balancer, but the WebSocket terminal needs sticky sessions
