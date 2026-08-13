# Architecture

ainew follows a monolithic-backend + SPA-frontend pattern deployed via Docker Compose. All AI inference runs locally through Ollama — no data leaves the network.

---

## System overview

```
┌─────────────────────────────────────────────────────────────────┐
│                         Client Browser                          │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP / WebSocket
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│                    Nginx (port 3000)                            │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  React SPA (TypeScript + Tailwind CSS)                  │   │
│  │  19 pages · TanStack Query · Recharts · react-markdown  │   │
│  └─────────────────────────────────────────────────────────┘   │
│  Proxy: /api/v1/* → localhost:8000                              │
└────────────────────────────┬────────────────────────────────────┘
                             │ HTTP (proxied)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│          FastAPI (port 8000, network_mode: host)                │
│                                                                 │
│  Auth middleware ──► JWT validation on all /api/v1/* routes     │
│                                                                 │
│  API modules (20):                                              │
│  auth · servers · hypervisors · chat · events · incidents       │
│  anomalies · agent · ansible · packages · repositories         │
│  system_updates · mcp · rag · audit · monitoring · settings    │
│  tasks · terminal · snapshots · alerts                         │
│                                                                 │
│  Background tasks (5-min tick):                                │
│  ┌──────────────┐  ┌─────────────────┐  ┌──────────────────┐  │
│  │ Health check │  │ Metric collector│  │ Anomaly detector │  │
│  │  (SSH ping)  │  │ (Node Exporter) │  │ (Z-score / IQR)  │  │
│  └──────────────┘  └─────────────────┘  └──────────────────┘  │
└──┬──────────┬──────────────┬───────────────────┬───────────────┘
   │          │              │                   │
   ▼          ▼              ▼                   ▼
┌──────┐  ┌───────┐  ┌──────────────┐  ┌──────────────────────┐
│ PG15 │  │ Redis │  │    Ollama    │  │  Prometheus +         │
│ Time │  │  7    │  │ (local LLM)  │  │  Pushgateway          │
│ Scale│  │       │  │              │  │  Node Exporter        │
│  DB  │  │       │  │ ChromaDB     │  │  (on managed servers) │
└──────┘  └───────┘  │ (RAG store)  │  └──────────────────────┘
                     └──────────────┘
```

---

## Key design decisions

### `network_mode: host` for the backend

The backend container runs with `network_mode: host` so it can reach managed servers directly over SSH. This avoids NAT complexity but means the host network is shared — the backend binds to all host interfaces on port 8000.

**Trade-off:** Simpler SSH routing, but no container network isolation for the backend process.

### Local LLM (Ollama)

All AI inference (chat, RCA, agent, embeddings) uses Ollama running on the same host or a reachable server. No data is sent to OpenAI, Anthropic, or any external API.

**Trade-off:** Full data privacy + no per-token costs, but requires local GPU/CPU resources and model management.

### PostgreSQL + TimescaleDB

Metrics are stored as time-series data in TimescaleDB hypertables. This gives efficient range queries (`WHERE time > now() - interval '1 hour'`) without a separate TSDB.

**Trade-off:** One DB for everything (simpler ops), but TimescaleDB adds operational complexity vs. plain Postgres.

### JWT authentication (stateless)

All API routes are protected by Bearer token JWT authentication via a global middleware in `main.py`. The middleware exempts `/api/v1/auth/*`, `/health`, `/docs`, and WebSocket terminal routes.

Tokens are signed with `SECRET_KEY` (from env), expire after 24 hours (configurable), and carry `username` + `role` claims.

### Human-in-the-loop AI agent

The agentic AI (`/api/v1/agent`) uses LangGraph to orchestrate tool-calling. Destructive or privileged actions (e.g. `run_command_as_root`) require explicit human approval before execution. The guard layer (`services/agent/guard.py`) classifies each tool call and blocks unapproved high-risk actions.

---

## Data flow: AIOps pipeline

```
Prometheus / Node Exporter
    │  scrape every 1 min
    ▼
metric_collector (background task)
    │  stores MetricRecord in TimescaleDB
    ▼
anomaly_detector (background task, 5-min tick)
    │  Z-score + IQR per metric per server
    │  creates AnomalyEvent if threshold exceeded
    ▼
event_auto_router
    │  groups anomalies into Events
    │  escalates severity-3+ to Incidents
    ▼
incident_auto (LangGraph)
    │  calls Ollama for Root Cause Analysis
    │  attaches RCA text to Incident
    ▼
UI: AnomalyDetection → Events → Incidents
```

---

## Data flow: AI Chat with RAG

```
User message
    │
    ▼
/api/v1/chat/stream (SSE)
    │
    ├──► ChromaDB similarity search (top-k chunks)
    │    (runbooks, metric descriptions, incident history)
    │
    ├──► Server context fetch (selected servers' live metrics)
    │
    └──► Ollama chat completion (streaming)
         model + system prompt + RAG context + server context
              │
              ▼
         SSE stream → browser (react-markdown render)
```

---

## Data flow: SSH server management

```
Frontend action (e.g. "Run command")
    │
    ▼
FastAPI endpoint
    │
    ├──► Lookup Server.credential_id → SSH username/password/key
    │
    └──► paramiko.SSHClient.connect(server.ip_address, port=22)
              │
              ├── Timeout: 10s connect, 60s exec
              ├── Thread pool: max 50 concurrent SSH connections
              └── Result stored in Task → polled by frontend
```

---

## Directory structure

```
ainew/
├── backend/
│   ├── app/
│   │   ├── api/           # FastAPI routers (20 modules)
│   │   ├── core/          # Config, database, auth, security
│   │   ├── models/        # SQLAlchemy ORM models
│   │   ├── schemas/       # Pydantic request/response schemas
│   │   ├── services/      # Business logic
│   │   │   ├── agent/     # LangGraph agentic AI
│   │   │   ├── monitoring/# Prometheus + Node Exporter
│   │   │   └── ...
│   │   ├── data/          # Static seed data (metric descriptions)
│   │   └── main.py        # FastAPI app + startup tasks
│   ├── alembic/           # DB migrations
│   └── requirements.txt
├── frontend/
│   ├── src/
│   │   ├── pages/         # 19 React page components
│   │   ├── components/    # Shared UI components
│   │   ├── config/        # API base URL config
│   │   └── main.tsx       # React entry point
│   ├── tailwind.config.js # Design tokens (cyber-* palette)
│   └── vite.config.ts
├── docs/                  # This documentation
├── docker-compose.yml
└── README.md
```

---

## Component responsibilities

| Component | Responsibility |
|---|---|
| `app/api/` | HTTP request handling, input validation, auth checks |
| `app/services/` | Business logic, external integrations (SSH, Ollama, Ansible) |
| `app/models/` | Database schema (SQLAlchemy), relationships |
| `app/core/config.py` | Central settings from env vars |
| `app/core/database.py` | SQLAlchemy engine + session factory |
| `app/background_tasks.py` | Periyodik scheduler (çoğu tick → Celery enqueue) |
| `app/worker.py` / `app/services/fleet_jobs.py` | Celery filo görevleri (onboarding, metric, log, …) |
| `app/services/agent/` | LangGraph graph + tool executor + guard layer |
| `app/services/aiops_engine.py` | Metric anomaly detection (Z-score, IQR) |
| `app/services/mcp_client.py` | MCP server connection + tool proxy |
