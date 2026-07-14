# Getting Started

You'll install ainew, connect it to a local Ollama instance, and add your first server — all in under 10 minutes.

By the end you'll have:
- The full stack running via Docker Compose
- A working login
- At least one managed server with live health status

---

## What you'll need

| Requirement | Notes |
|---|---|
| Docker + Docker Compose v2 | `docker compose version` should return v2.x |
| Linux host | Ubuntu 22.04, RHEL 9, or Debian 12 recommended |
| [Ollama](https://ollama.ai) | Running on the host or a reachable server (for AI features) |
| SSH access | To the servers you want to manage |
| Git | To clone the repo |

Minimum hardware for the management host: 4 CPU cores, 8 GB RAM, 50 GB disk.
With GPU-accelerated Ollama: 8+ GB VRAM recommended for `mistral` or `llama3`.

---

## Step 1: Clone and configure

```bash
git clone <repo-url> ainew
cd ainew
```

Copy the example env file and edit it:

```bash
cp .env.example .env
```

Open `.env` and set at minimum:

```bash
# Required
SECRET_KEY=<generate with: openssl rand -hex 32>
POSTGRES_PASSWORD=<your-db-password>

# Ollama — where your local LLM runs
OLLAMA_URL=http://127.0.0.1:11434

# CORS — frontend origin (default is fine for local dev)
CORS_ORIGINS=http://localhost:3000
```

If Ollama is on a different host:
```bash
OLLAMA_URL=http://192.168.1.100:11434
```

---

## Step 2: Pull an Ollama model

ainew uses Ollama for chat, anomaly RCA, and the AI agent. Pull a model before starting:

```bash
ollama pull mistral          # ~4 GB, good balance of speed and quality
# or
ollama pull llama3:8b        # ~5 GB, strong reasoning
# or
ollama pull qwen2.5:7b       # ~4 GB, multilingual
```

Verify it works:
```bash
ollama run mistral "Hello"
```

---

## Step 3: Start the stack

```bash
docker compose up -d
```

This starts:
- `db` — PostgreSQL 15 with TimescaleDB
- `redis` — Redis 7
- `backend` — FastAPI on port 8000
- `frontend` — React app via Nginx on port 3000

Check all containers are healthy:
```bash
docker compose ps
```

Expected output:
```
NAME                         STATUS
server_management_db         running (healthy)
server_management_redis      running (healthy)
server_management_backend    running
server_management_frontend   running
```

---

## Step 4: Log in

Open [http://localhost:3000](http://localhost:3000) in your browser.

Default credentials:
- **Username:** `admin`
- **Password:** `admin123`

**Change the default password immediately** — go to Settings → Users after login.

You'll land on the Dashboard. It will show empty KPI cards until you add servers.

---

## Step 5: Add your first server

1. Go to **Servers** in the sidebar
2. Click **+ Yeni Sunucu** (New Server)
3. Fill in:
   - **Name:** any label, e.g. `web-01`
   - **IP Address:** the server's IP
   - **SSH Port:** default 22
4. Click **Save**

ainew will attempt an SSH ping. The status indicator shows:
- Green dot — reachable and responding
- Red dot — unreachable (check IP, port, firewall)
- Gray dot — not yet checked

---

## Step 6: Configure SSH credentials

By default, ainew tries passwordless SSH (key from the management host). For password-based auth:

1. Go to **Settings** → **Credentials**
2. Create a new credential with SSH username and password (or paste an SSH private key)
3. Back in **Servers**, open the server drawer and assign the credential

After assigning, click **Test Bağlantısı** (Test Connection) to verify.

---

## Step 7: Enable metrics collection

For a server to show CPU/memory/disk graphs:

1. In the server drawer, go to **Monitoring** tab
2. Click **Node Exporter Kur** (Install Node Exporter)

ainew SSH's into the server, installs Node Exporter as a systemd service, and registers it with Prometheus. Metrics appear in Live Metrics within 2 minutes.

---

## Verification

You should now see:

- Dashboard: at least 1 server, health percentage > 0%
- Servers: your server with green health status
- Live Metrics: CPU/memory graphs populating in real time

If anything is wrong, check backend logs:

```bash
docker compose logs backend --tail=50
```

---

## Troubleshooting

| Problem | Check |
|---|---|
| Frontend shows blank page | `docker compose logs frontend` — check Nginx config |
| Login fails | `docker compose logs backend` — look for auth or DB errors |
| Server shows gray dot | Backend can't reach the server. Check IP and port 22 is open |
| AI Chat returns no response | Is Ollama running? `curl $OLLAMA_URL/api/tags` should return JSON |
| Metrics not appearing | Node Exporter not installed, or Prometheus can't reach port 9100 on the server |

---

## Next steps

- [Add more servers and group by credential](features/server-management.md)
- [Configure AIOps anomaly detection thresholds](features/aiops.md)
- [Set up AI Chat with runbook RAG](features/ai-chat.md)
- [Run your first Ansible playbook](features/server-management.md#ansible)
- [Full deployment reference](deployment.md)
