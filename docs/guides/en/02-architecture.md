## 3. Conceptual Architecture

Domains: Dashboard · Executive / AI · Linux · Windows · Virtualization · Exadata · OpenShift · Level 1 · Integrations · Applications · Knowledge · Custom reports · Audit · Users · Settings.

Externals: vCenter, oVirt/OLVM, Proxmox, Hyper-V, OpenShift API, SSH, WinRM, UCMDB, Ansible/AWX, Prometheus, optional AD/SSO, optional remote LLM.

---

## 4. Logical Architecture

```diagram
  ┌─────────────┐   JSON / SSE    ┌─────────────┐   SQL / Redis    ┌──────────┐
  │  Frontend   │ ──────────────► │  Backend    │ ───────────────► │  Store   │
  │  React+Nginx│ ◄────────────── │  FastAPI    │ ◄─────────────── │ Timescale│
  └─────────────┘   JWT           │  /api/v1    │                  │ Redis    │
                                  └──────┬──────┘                  └──────────┘
                                         │
                    ┌────────────────────┼────────────────────┐
                    ▼                    ▼                    ▼
              Integration           AI / LLM              Level 1
              SSH / WinRM           Ollama / remote       Dropt API
              vCenter / oVirt       LangGraph + RAG       separate DB
              OCP API               PromQL (read-only)
```

Frontend `:3000` baked nginx. Backend `:8000` host network. JWT + module RBAC. One ainew DB; Dropt is separate.

---

## 5. Components

`Layout.tsx` / pages · `app/api` · `app/services` · Celery · Dropt · Timescale / Redis / Prom / Ollama.

---

## 6. Data Architecture

```diagram
  exporters ──► Prometheus ──► metric_sync ──► metric_data ──► dashboard / OS chat
  vCenter / OLVM API ──► VM sync ──► servers + virt_* ──► virt UI / chat
```

---

## 7. Integrations

vCenter SOAP 443 · oVirt REST `kvm` 443 · Proxmox 8006 · Hyper-V WinRM · OCP kube API · SSH · WinRM · UCMDB · AWX · Prometheus PromQL · Dropt `:8001`. Use a resolvable IP/FQDN.

---

## 8. How the model works

```diagram
                    APPLICATION / INVENTORY / METRICS
                           │
                           ▼
                 Sync + connector layer
                           │
                 ┌─────────┴─────────┐
                 ▼                   ▼
          RAG Knowledge         Tool results
                 │                   │
                 └─────────┬─────────┘
                           ▼
                     Context Builder
                           │
  USER QUESTION ──────────►│
                           ▼
                    Intent / Routing
                           │
               ┌───────────┼───────────┐
               ▼           ▼           ▼
            RAG Docs    Tool Calls   Live Data
                           │
                    vCenter / OLVM /
                    SSH / WinRM / OCP / PromQL
                           │
                           ▼
                          LLM
                   Ollama or REMOTE_LLM
                           │
                           ▼
                        RESPONSE (SSE)
```

Local Ollama and/or remote gateway; embeddings still need `nomic-embed-text`. Fail-fast. Agent mutations require approval. Surfaces: `/chat`, `/linux/chat`, `/windows/aiops/chat`, `/virt/chat`, `/exadata/chat`, `/openshift/chat`, `/agent`.

---

## 9. Security

JWT, module RBAC, Fernet credentials, CORS, host-network `:8000`. Dropt bridge secret. This GUIDE never prints secrets.

---

## 10. Deployment

```diagram
                    ┌─ docker compose up -d ─┐
                    │                        │
                    ▼                        ▼
              ainew stack              Dropt stack
              DATA_DIR/                DATA_DIR/dropt/
```

Dev: `docker-compose.yml`. Prod: `docker-compose.prod.yml` + `install-rhel.sh`.

**Docker vs Podman:** supported **runtime** is Docker Compose. Images may be loaded with docker or podman. ainew is not installed as an OpenShift Operator; it **manages** OpenShift.

---

## 11. Operations

`GET /health`. Restart backend after Python changes; rebuild frontend after UI changes. Chat LLM → Settings → AI. Empty VMs → hypervisor FQDN/sync. Level 1 → Dropt `:8001`.
