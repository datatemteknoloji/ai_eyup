# ainew — AI-Powered Infrastructure Management

**ainew** is a self-hosted platform for managing Linux servers and VMware hypervisors at scale. It combines SSH-based automation, real-time monitoring, and local AI (Ollama) to give operations teams a single control plane — without sending data to external cloud services.

**Customer download (version in the filename):** [Releases](https://github.com/datatemteknoloji/ai_eyup/releases) → `ainew-<version>-linux-amd64.tar.gz`  
Do not use **Code → Download ZIP** (`ai_eyup-main.zip` has no version in the name).

[![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/frontend-React%2FTypeScript-61DAFB)](https://react.dev)
[![License](https://img.shields.io/badge/license-MIT-blue)](#)
[![Release](https://img.shields.io/github/v/release/datatemteknoloji/ai_eyup)](https://github.com/datatemteknoloji/ai_eyup/releases)

---

## What it does

| Capability | Description |
|---|---|
| **Server Inventory** | SSH-based server discovery, status monitoring, remote command execution |
| **Hypervisor Management** | VMware ESXi VM sync, snapshot management, resource tracking |
| **AIOps Pipeline** | Anomaly detection → Events → Incidents → AI Root Cause Analysis |
| **AI Chat** | RAG-powered chat using local Ollama LLM with server context |
| **Agentic AI** | Tool-calling AI agent with human-in-the-loop approval gate |
| **Ansible / AWX** | Ad-hoc commands and playbook execution across server groups |
| **Package Management** | RPM/DEB package deployment with AI error analysis |
| **Repository Management** | Local Yum/APT repository creation and client config push |
| **System Updates** | AI-guided update planning with pre/post VM snapshot support |
| **Web Terminal** | WebSocket SSH terminal directly in the browser |
| **MCP Tools** | Model Context Protocol server integration |
| **Audit Log** | Full audit trail for all operations |

---

## Quick start

There are two install paths depending on what you're doing:

### Development (this repo, live-reloading source)

```bash
# 1. Clone and configure
git clone <repo-url> ainew && cd ainew
cp .env.example .env          # edit SECRET_KEY, POSTGRES_PASSWORD, OLLAMA_URL

# 2. Start all services
docker compose up -d

# 3. Open the UI
open http://localhost:3000     # default login: admin / admin123 — CHANGE THIS IMMEDIATELY, dev only
```

⚠️ This path uses the root `docker-compose.yml`, live-mounts backend source, and ships with a well-known
default admin password. **Do not use it for a customer or production install.**

### Customer / production install

```bash
# 1. Build a reproducible release bundle from tracked source
./scripts/build-distribution.sh

# 2. Copy dist/ainew-<version>-linux-amd64/ to the target host, then run the installer
cd dist/ainew-<version>-linux-amd64
sudo ./install-rhel.sh
```

`install-rhel.sh` pins image versions, binds Postgres/Redis to `localhost` only, generates a random
`SECRET_KEY` / `POSTGRES_PASSWORD` / admin password (printed once at the end — save it), and configures
TLS. See [deploy/README.md](deploy/README.md) for details, and [docs/deployment.md](docs/deployment.md)
for the full production checklist including offline Ollama model transfer for air-gapped hosts.

Full setup guide: [docs/getting-started.md](docs/getting-started.md)

---

## Architecture

```
Browser ──► Nginx (port 3000) ──► React SPA
                │
                └──► FastAPI (port 8000, network_mode=host)
                          │
                          ├──► PostgreSQL / TimescaleDB  (metrics + data)
                          ├──► Redis                     (task queue / cache)
                          ├──► Ollama                    (local LLM inference)
                          ├──► ChromaDB                  (vector search / RAG)
                          ├──► Prometheus / Pushgateway  (metrics scraping)
                          └──► SSH                       (server management)
```

Full architecture: [docs/architecture.md](docs/architecture.md)

---

## Documentation

| Document | Content |
|---|---|
| [Getting Started](docs/getting-started.md) | Install, configure, first login |
| [Architecture](docs/architecture.md) | System design, data flow, component overview |
| [Deployment](docs/deployment.md) | Docker Compose config, env vars, production tips |
| [API Reference](docs/api-reference.md) | All REST endpoints with parameters and responses |
| [AIOps Pipeline](docs/features/aiops.md) | Anomaly detection → Incidents → RCA explanation |
| [AI Chat & RAG](docs/features/ai-chat.md) | Chat setup, RAG ingestion, model selection |
| [Agentic AI](docs/features/agent.md) | Tool-calling agent, approval flow, guard rails |
| [Server Management](docs/features/server-management.md) | Adding servers, SSH credentials, metrics |
| [Package & Repo Management](docs/features/package-management.md) | RPM/DEB deployment, local repos |

---

## Tech stack

**Backend:** Python 3.11, FastAPI 0.104, SQLAlchemy, Alembic, Paramiko (SSH), LangGraph (agent), ChromaDB (RAG)

**Frontend:** React 18, TypeScript, Tailwind CSS, Vite, TanStack Query, Recharts

**Infrastructure:** PostgreSQL 15 + TimescaleDB, Redis 7, Ollama, Prometheus, Docker Compose

---

## Requirements

- Docker + Docker Compose v2
- Ollama running locally or on a reachable host (for AI features)
- Linux host with SSH access to managed servers
- VMware ESXi with API access (for hypervisor features, optional)
