# ainew — Master GUIDE

This document covers **ainew** end to end: purpose, users, system requirements, installation, the container stack, backend / frontend / data, how the AI model works, and every sidebar action.

It is not a live inventory dump. Menu paths match `Layout.tsx`.

---

## 1. Executive Summary

### 1.1 System Purpose

ainew is a **self-hosted** infrastructure operations platform. One session covers:

- Linux (SSH) and Windows (WinRM)
- VMware vCenter, oVirt / OLVM, Proxmox, Hyper-V, OpenShift Virtualization
- OpenShift Container Platform (cluster, node, project, pod, KubeVirt VM)
- Oracle Exadata
- Level 1 day-2 operations (Dropt: Request → Preview → Apply)
- Metrics, events, incidents, assistants, audit

Inference is **local Ollama** or an admin **remote LLM** (`REMOTE_LLM_*`). Remote failure is **explicit** — no silent local fallback.

### 1.2 Target Users

Admins (RBAC, Settings, backup) · Linux / Windows / virt / OpenShift operators · Level 1 · executives. Admin sees every module; others see assignments only.

### 1.3–1.4 Problems and capabilities

Unify scattered consoles; answer placement/capacity in chat and reports; auditable Level 1 jobs; data stays on-prem.

**RBAC:** `executive`, `linux`, `windows`, `virtualization`, `exadata`, `openshift`, `ai_automation`, `integrations`, `level1`, `applications`, `knowledge`, `custom_reports`.

---

## 2. System Overview

### 2.1 High-Level Architecture

```diagram
                         ┌──────────────────────┐
                         │   Operator browser   │
                         └──────────┬───────────┘
                                    │  HTTP / HTTPS
                                    ▼
                         ┌──────────────────────┐
                         │  Frontend (Nginx)    │
                         │  React SPA  :3000    │
                         │  /api/v1 → :8000     │
                         └──────────┬───────────┘
                                    ▼
                         ┌──────────────────────┐
                         │  Backend (FastAPI)   │
                         │  host network :8000  │
                         └──────────┬───────────┘
              ┌─────────────┬───────┼────────┬──────────────┐
              ▼             ▼       ▼        ▼              ▼
        TimescaleDB      Redis   Prometheus  LLM        Externals
        PG15 :5432       :6379   + Pushgateway Ollama     vCenter / OLVM
        pgvector                 Celery       or remote   SSH / WinRM / OCP
                                    │
                                    ▼
                         ┌──────────────────────┐
                         │  Level 1 Dropt       │
                         │  API :8001           │
                         │  separate Postgres   │
                         └──────────────────────┘
```

Do **not** mix the ainew database with Dropt Postgres.

### 2.2 Principles

Self-hosted · module RBAC · tool-first chat · PromQL-only Prometheus chat · Level 1 Preview/Apply · fail-fast LLM · **Docker Compose** runtime (images may be `docker load` or `podman load`).

### 2.3 Technology Stack

Frontend: React 18 + nginx. Backend: Python 3.11 FastAPI. Data: TimescaleDB PG15 + pgvector. Queue: Redis 7 + Celery. Monitoring: Prometheus / Pushgateway. AI: Ollama and/or `REMOTE_LLM_*`. Level 1: Dropt sidecar.

### 2.4 Runtime — containers and ports

Supported product runtime is **Docker Engine + Compose v2**. `install-rhel.sh` installs Docker CE if missing. Offline tarballs can be loaded with `docker load` or **podman load**. ainew is not shipped as an OpenShift Operator.

```diagram
  MANAGEMENT HOST (RHEL 9 / Rocky / Alma — x86_64)
  =====================================================================
  :3000   frontend     nginx + React SPA
  :8000   backend      FastAPI (network_mode: host)
          worker       Celery (same image)
  :5432   db           TimescaleDB PG15
  :6379   redis        Redis 7
  :9090   prometheus   (when deployed)
  :9091   pushgateway
  :8001   dropt-api    Level 1
  :5433   dropt-db     Postgres 16 (localhost)
  :6380   dropt-redis
  :11434  ollama       optional profile
  =====================================================================
```

Python changes: restart backend (`UVICORN_WORKERS=2`, no reload). UI changes: rebuild frontend image.

### 2.5 System requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| OS | RHEL 9.x x86_64 (Rocky/Alma 9) | Current 9.x |
| CPU | 4 cores | 8+ |
| RAM | 8 GB | 16 GB+ with local Ollama |
| Disk | 50 GB free under `INSTALL_DIR` (default `/data`) | 100 GB+ |
| GPU | Optional | For local LLM |
| Network | 80/443 UI; 9090/9091; Dropt :8001 host-local | Egress to vCenter/SSH/OCP |
| Privilege | root / sudo | — |
| Containers | Docker CE + Compose v2 | Offline image tarball |

Air-gap: `scripts/build-distribution.sh` → `ainew-<version>-linux-amd64.tar.gz`.

### 2.6 How to install

**Production (RHEL):** copy the release tarball → `sudo ./install-rhel.sh` (Docker, install dir `/data`, `.env`, image load, `docker compose -f docker-compose.prod.yml up -d`) → open UI → change admin password. Script is idempotent.

**Development:** `./scripts/dev-setup.sh` then `docker compose up -d` (UI `:3000`, API `:8000`).

**Docker vs Podman:** runtime is Docker Compose. Image load may use podman. No official podman-compose or OCP-operator install.

### 2.7 Persistent data

`DATA_DIR="$INSTALL_DIR/data"` (default `/data/data`): postgres, redis, repos, uploads, prometheus, certs, ollama, dropt. Do not delete application data without approval.
