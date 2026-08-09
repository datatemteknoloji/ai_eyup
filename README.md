# ainew — AI-Powered Infrastructure Management

**ainew** is a self-hosted platform for managing Linux, Windows, virtualization, Exadata, and OpenShift estates at scale. It combines SSH/WinRM automation, real-time monitoring, Level‑1 runbooks (Dropt), and local AI (Ollama) in a single control plane — without sending operational data to external cloud LLM services by default.

**Current release:** see [Releases](https://github.com/datatemteknoloji/ai_eyup/releases) (badge below).  
**Customer download (version in the filename):** `ainew-<version>-linux-amd64.tar.gz`  
Do **not** use **Code → Download ZIP** (`ai_eyup-main.zip`) for production — it has no versioned offline images.

[![FastAPI](https://img.shields.io/badge/backend-FastAPI-009688)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/frontend-React%2FTypeScript-61DAFB)](https://react.dev)
[![License](https://img.shields.io/badge/license-MIT-blue)](#)
[![Release](https://img.shields.io/github/v/release/datatemteknoloji/ai_eyup)](https://github.com/datatemteknoloji/ai_eyup/releases)

---

## What it does

| Capability | Description |
|---|---|
| **RBAC modules** | `executive`, `linux`, `windows`, `virtualization`, `exadata`, `openshift`, `ai_automation`, `integrations`, `level1`, `applications`, `knowledge` |
| **Server inventory** | SSH discovery, health, remote commands, package/repo/system updates |
| **Windows platform** | WinRM, event logs, Windows Update, Windows AIOps |
| **Virtualization** | VMware vCenter/ESXi, Proxmox, Hyper-V, OpenShift Virt (KubeVirt) |
| **Exadata / OpenShift** | Rack/cell inventory, OCP cluster & workload views |
| **Level 1 (Dropt)** | Guided disk/ASM/LVM/service/user runbooks via Dropt API sidecar |
| **AIOps** | Anomaly → events → incidents → AI root-cause assistance |
| **AI chat & agent** | RAG + tool-calling agent with human-in-the-loop approval (local Ollama / optional remote LLM) |
| **Ansible / AWX** | Ad-hoc and playbook execution across groups |
| **Web terminal** | Browser SSH terminal (WebSocket) |
| **Integrations** | UCMDB import and external sources |
| **Audit log** | Full audit trail for operations |

---

## Quick start

### A) Customer / production (offline package)

1. Download the release asset from [Releases](https://github.com/datatemteknoloji/ai_eyup/releases):
   - Default (no Ollama image inside): `ainew-<version>-linux-amd64.tar.gz`
   - Optional AI runtime variants: `*-with-ollama.tar.gz` (see [deploy/README.md](deploy/README.md))
2. On the target host (Docker already installed):

```bash
tar xzf ainew-<version>-linux-amd64.tar.gz
cd ainew-<version>-linux-amd64
sudo ./install-rhel.sh
```

The package root includes a standard **`docker-compose.yml`** (offline stack: pinned images, `pull_policy: never`, Dropt), plus `install-rhel.sh` / `update-rhel.sh` / `rollback-rhel.sh` and prebuilt `images/*.tar.gz`.

Upgrade:

```bash
tar xzf ainew-<version>-linux-amd64.tar.gz
cd ainew-<version>-linux-amd64
sudo ./update-rhel.sh --install-dir /data
```

Details: [deploy/README.md](deploy/README.md), [docs/INSTALL_RHEL.md](docs/INSTALL_RHEL.md), [docs/deployment.md](docs/deployment.md).

### B) Development (this repo, live-reload)

```bash
git clone https://github.com/datatemteknoloji/ai_eyup.git ainew && cd ainew
./scripts/dev-setup.sh        # .env with random SECRET_KEY / POSTGRES_PASSWORD
docker compose up -d          # root docker-compose.yml (dev; network_mode: host)
# UI: http://localhost:3000
```

⚠️ Dev compose live-mounts backend source and may ship a well-known admin password. **Not for customer installs.**

---

## Building & publishing a release (maintainers)

```bash
# 1) Build offline bundle (linux/amd64 via buildx; Dropt + app images)
./scripts/build-distribution.sh
# Optional AI packaging:
#   --with-ollama     marker; runtime may download once at install
#   --bundle-ollama   embed Ollama image + nomic-embed-text (~+3.5GB, fully air-gapped)

# 2) Commit + tag + push + upload Release assets (no rebuild)
./scripts/publish-github-release.sh
# Or bump VERSION + CHANGELOG + build + publish in one go:
# ./scripts/release.sh <version> "Short summary"
```

Release assets stay on GitHub Releases (`dist/*.tar.gz` is gitignored). CI does **not** pack `dist/` from the git tree.

---

## Architecture

```
Browser ──► Nginx (port 3000) ──► React SPA
                │
                └──► FastAPI (port 8000)
                          │
                          ├──► PostgreSQL / TimescaleDB  (metrics + data)
                          ├──► Redis                     (queue / cache)
                          ├──► Dropt API + Postgres 16   (Level 1 sidecar)
                          ├──► Ollama (optional)         (local LLM / embeddings)
                          ├──► ChromaDB                  (vector search / RAG)
                          ├──► Prometheus / Pushgateway  (metrics)
                          └──► SSH / WinRM               (managed hosts)
```

Full architecture: [docs/architecture.md](docs/architecture.md)

---

## Documentation

| Document | Content |
|---|---|
| [Getting Started](docs/getting-started.md) | Dev install, first login |
| [RHEL install](docs/INSTALL_RHEL.md) | Offline install, update, Ollama, air-gap |
| [Architecture](docs/architecture.md) | System design, data flow |
| [Deployment](docs/deployment.md) | Compose, env vars, production checklist |
| [API Reference](docs/api-reference.md) | REST endpoints |
| [AIOps](docs/features/aiops.md) | Anomaly → incidents → RCA |
| [AI Chat & RAG](docs/features/ai-chat.md) | Chat, RAG, models |
| [Agentic AI](docs/features/agent.md) | Tools, approval, guards |
| [Server management](docs/features/server-management.md) | SSH, credentials, metrics |
| [Packages & repos](docs/features/package-management.md) | RPM/DEB, local repos |
| [Virtualization](docs/features/virtualization.md) | vCenter, oVirt, Proxmox, Hyper-V, OCP Virt |
| [Windows](docs/features/windows-platform.md) | WinRM, metrics, event logs |
| [Metrics architecture](docs/explanation-metrics-architecture.md) | VM vs physical metrics |
| [Scale (10k+)](docs/scale-and-performance.md) | Pool, workers, retention |
| [deploy/](deploy/README.md) | Production templates consumed by the build |

---

## Tech stack

**Backend:** Python 3.11, FastAPI, SQLAlchemy 2, Alembic, Paramiko, LangGraph, ChromaDB  

**Frontend:** React 18, TypeScript, Vite, Tailwind, TanStack Query, Recharts  

**Infrastructure:** TimescaleDB (PG15), Redis 7, Prometheus, Pushgateway, optional Ollama; Level‑1 Dropt API (+ Postgres 16)  

**Delivery:** Docker Compose; offline image tarballs via `scripts/build-distribution.sh`

---

## Requirements

| Path | Needs |
|---|---|
| **Customer host** | Docker / Compose v2, Linux amd64; package from Releases |
| **AI features** | Ollama reachable (`OLLAMA_URL`) or bundled/with-ollama flow; models pulled separately unless bundled |
| **Managed Linux** | SSH |
| **Managed Windows** | WinRM |
| **Virtualization** | API access to the chosen hypervisor (optional) |
