# API Reference

Base URL: `http://localhost:8000/api/v1`

All endpoints except `/auth/*` require a Bearer token in the `Authorization` header:

```
Authorization: Bearer <token>
```

Get a token:

```bash
curl -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "admin", "password": "Kim13Sun"}'
# → {"access_token": "eyJ...", "token_type": "bearer"}
```

---

## Auth

### `POST /auth/login`

Authenticate and get a JWT token.

**Request:**
```json
{ "username": "admin", "password": "Kim13Sun" }
```

**Response:**
```json
{
  "access_token": "eyJhbGci...",
  "token_type": "bearer",
  "username": "admin",
  "role": "admin"
}
```

### `GET /auth/me`

Returns the authenticated user's profile.

### `GET /auth/users`

List all users (admin only).

### `POST /auth/users`

Create a new user (admin only).

### `PUT /auth/users/{user_id}/password`

Change a user's password.

---

## Servers

### `GET /servers/`

List all servers with their current health status.

**Response:** Array of server objects:
```json
[
  {
    "id": 1,
    "name": "web-01",
    "ip_address": "192.168.1.10",
    "ssh_port": 22,
    "is_healthy": true,
    "last_seen": "2026-06-06T10:00:00Z",
    "os_info": { "os": "Ubuntu 22.04", "kernel": "5.15.0" },
    "is_ai_ready": true,
    "credential_id": 2
  }
]
```

### `POST /servers/`

Add a new server.

**Request:**
```json
{
  "name": "web-01",
  "ip_address": "192.168.1.10",
  "ssh_port": 22,
  "credential_id": 1
}
```

### `PUT /servers/{server_id}`

Update server metadata (name, IP, port, credential).

### `DELETE /servers/{server_id}`

Remove a server from the inventory.

### `POST /servers/check-health`

Run health check on all servers simultaneously.

### `POST /servers/{server_id}/check-health`

Run health check on a single server.

### `GET /servers/{server_id}/metrics-summary`

Returns latest CPU, memory, disk metrics for a server.

**Query params:** `interval` (e.g. `1h`, `6h`, `24h`)

### `POST /servers/{server_id}/credentials`

Assign SSH credentials to a server.

### `POST /servers/update-ai-ready`

Bulk update the `is_ai_ready` flag on multiple servers.

### `POST /servers/refresh-os-info`

SSH into servers and refresh OS version, hostname, kernel info.

---

## Hypervisors

### `GET /hypervisors/`

List all hypervisors.

### `POST /hypervisors/`

Add a VMware ESXi hypervisor.

**Request:**
```json
{
  "name": "esxi-01",
  "host": "192.168.1.200",
  "username": "root",
  "password": "secret",
  "port": 443
}
```

### `POST /hypervisors/{id}/sync-vms`

SSH into the hypervisor and sync VM list to the servers table.

### `POST /hypervisors/{id}/test-connection`

Test connectivity to the hypervisor API.

### `GET /hypervisors/{id}/vms`

List VMs on a hypervisor.

---

## AI Chat

### `GET /chat/models`

List available Ollama models.

**Response:**
```json
{ "models": [{ "name": "mistral:latest", "parameter_size": "7B" }] }
```

### `GET /chat/sessions`

List all chat sessions for the authenticated user.

### `POST /chat/sessions`

Create a new chat session.

### `GET /chat/sessions/{session_id}/messages`

Get all messages in a session.

### `POST /chat/stream`

Send a message and stream the AI response (Server-Sent Events).

**Request:**
```json
{
  "session_id": 1,
  "message": "What is the CPU usage on web-01?",
  "model": "mistral:latest",
  "server_ids": [1, 2],
  "use_rag": true
}
```

**Response:** `text/event-stream` — each chunk is a JSON object:
```
data: {"type": "content", "text": "The CPU usage on web-01 is "}
data: {"type": "content", "text": "34%..."}
data: {"type": "done"}
```

---

## Agentic AI

The agent uses tool-calling to execute actions on servers. Destructive actions require explicit approval.

### `POST /agent/chat`

Send a message to the AI agent.

**Request:**
```json
{
  "message": "Check disk usage on all servers",
  "server_ids": [1, 2, 3]
}
```

**Response:** Streams JSON events:
```json
{"type": "thinking", "text": "Checking disk usage..."}
{"type": "tool_call", "tool": "run_command", "args": {"command": "df -h"}}
{"type": "tool_result", "result": "..."}
{"type": "response", "text": "Server web-01 has 45% disk used..."}
```

### `GET /agent/actions/pending`

Get actions waiting for human approval.

### `POST /agent/actions/{action_id}/approve`

Approve a pending action. The agent proceeds with execution.

### `POST /agent/actions/{action_id}/reject`

Reject a pending action. The agent is notified and stops.

### `POST /agent/actions/{action_id}/answer`

Provide a text answer when the agent asks a question.

---

## Events (AIOps)

### `GET /events/`

List events. Supports filtering:
- `?status=open` — only open events
- `?severity=3` — severity 3+ events
- `?server_id=1` — events for a specific server
- `?limit=50&offset=0` — pagination

### `POST /events/`

Create an event manually.

### `POST /events/scan`

Trigger immediate anomaly scan (normally runs on 5-min tick).

### `POST /events/{id}/resolve`

Mark an event as resolved.

### `POST /events/{id}/known`

Mark an event as a known/expected condition (suppresses future alerts).

### `POST /events/analyze-group`

Run AI analysis on a group of related events.

---

## Incidents

### `GET /incidents/`

List incidents.

### `POST /incidents/`

Create an incident manually.

### `PUT /incidents/{id}`

Update incident (status, severity, notes).

### `GET /incidents/{id}/rca`

Get AI-generated Root Cause Analysis for an incident.

---

## Anomaly Detection

### `GET /anomalies/status`

Current AIOps pipeline status (anomaly counts, incident counts).

### `GET /anomalies/`

List detected anomalies with scores.

---

## Ansible / AWX

### `POST /ansible/adhoc`

Run an Ansible ad-hoc command on a list of servers.

**Request:**
```json
{
  "server_ids": [1, 2, 3],
  "module": "shell",
  "args": "uptime",
  "become": false
}
```

### `POST /ansible/playbook`

Run an Ansible playbook (YAML provided inline).

**Request:**
```json
{
  "server_ids": [1, 2],
  "playbook_yaml": "---\n- name: Update\n  hosts: all\n  tasks: ...",
  "become": true
}
```

### `GET /ansible/awx/templates`

List AWX job templates (requires AWX configured in Settings).

### `POST /ansible/awx/launch`

Launch an AWX job template.

**Request:**
```json
{ "template_id": 5, "extra_vars": {"env": "prod"} }
```

### `GET /ansible/awx/job/{job_id}`

Get AWX job status and metadata.

### `GET /ansible/awx/job/{job_id}/stdout`

Get AWX job stdout output.

---

## Package Management

### `GET /packages/files`

List uploaded package files (RPM/DEB).

### `POST /packages/files/upload`

Upload a package file. `multipart/form-data` with `file` field.

### `DELETE /packages/files/{file_id}`

Delete an uploaded file.

### `GET /packages/jobs`

List deployment jobs.

### `POST /packages/jobs/deploy`

Deploy a package to a list of servers.

**Request:**
```json
{
  "file_id": 3,
  "server_ids": [1, 2],
  "install_args": "--nogpgcheck"
}
```

### `POST /packages/jobs/upgrade`

Upgrade all packages on selected servers (`yum upgrade -y` / `apt upgrade -y`).

### `POST /packages/jobs/check-updates`

Check for available updates on selected servers.

### `POST /packages/jobs/{job_id}/analyze-error`

Ask the AI to analyze a failed deployment and suggest a fix.

---

## Repository Management

### `GET /repos`

List all local repositories.

### `POST /repos`

Create a new local repository (Yum or APT).

### `POST /repos/{id}/jobs`

Trigger a repository sync job.

### `GET /repos/{id}/progress`

Get real-time sync progress (stream).

### `GET /repos/{id}/packages`

List packages in a repository.

### `GET /repos/{id}/client-config`

Generate a `.repo` file (Yum) or `sources.list` entry (APT) for a client server.

### `POST /repos/{id}/push-config`

Push the repo client config to a list of servers via SSH.

### `GET /repos/aggregate-stats`

Aggregate package counts and disk usage across all repos.

---

## System Updates

### `GET /updates/servers`

List servers with their pending update counts.

### `POST /updates/check`

SSH into servers and check for pending updates.

### `POST /updates/suggest-repo`

Ask AI to suggest the best local repository for a set of updates.

### `GET /updates/plans`

List update plans.

### `POST /updates/plans`

Create an update plan for a set of servers.

**Request:**
```json
{
  "server_ids": [1, 2, 3],
  "snapshot_mode": "before",
  "snapshot_retention": "1w"
}
```

### `POST /updates/plans/{plan_id}/analyze`

Run AI analysis on a plan's jobs (summarize what will be updated, risk assessment).

---

## Monitoring

### `GET /monitoring/metrics/{server_id}`

Query time-series metrics for a server.

**Query params:**
- `metric` — metric name (e.g. `cpu_percent`, `mem_percent`, `disk_percent`)
- `interval` — `1h`, `6h`, `24h`, `7d`

### `POST /monitoring/install-node-exporter`

SSH into a server and install Node Exporter as a systemd service.

---

## Tasks

### `GET /tasks/`

List active/recent tasks (SSH commands, playbooks, scans).

### `GET /tasks/{task_id}`

Get task status and output.

---

## MCP Tools

### `GET /mcp/tools`

List available tools from connected MCP servers.

### `POST /mcp/call-tool`

Call an MCP tool by name.

**Request:**
```json
{
  "tool_name": "search_docs",
  "arguments": { "query": "kubernetes deployment" }
}
```

### `POST /mcp/analyze`

Ask the AI to select and call the appropriate MCP tool for a natural language request.

---

## Audit Log

### `GET /audit/`

List audit log entries. Filterable by:
- `?action=servers.update`
- `?username=admin`
- `?since=2026-01-01T00:00:00Z`

---

## Terminal (WebSocket)

### `WS /terminal/ws/{server_id}`

WebSocket SSH terminal session.

Connect with a JWT token as a query param:
```
ws://localhost:8000/api/v1/terminal/ws/1?token=eyJ...
```

Send: `{"type": "input", "data": "ls -la\n"}`
Receive: `{"type": "output", "data": "total 48\n..."}` or `{"type": "resize", "cols": 80, "rows": 24}`

---

## Settings

### `GET /settings/credentials`

List saved SSH credentials (passwords are masked).

### `POST /settings/credentials`

Create a credential (SSH username + password or private key).

### `PUT /settings/credentials/{id}`

Update a credential.

### `DELETE /settings/credentials/{id}`

Delete a credential.

### `POST /settings/credentials/{id}/apply`

Test a credential against its associated servers.

### `GET /settings/app`

Get application-level settings (management server IP, default Ollama model).

### `PUT /settings/app`

Update application settings.

---

## RAG

### `POST /rag/ingest`

Ingest a document into the vector store. Used for runbooks, SOPs, and incident notes.

**Request:**
```json
{
  "text": "...",
  "source": "runbook-nginx",
  "type": "runbook"
}
```

### `POST /rag/search`

Similarity search over the vector store.

### `DELETE /rag/clear`

Clear all RAG embeddings of a specific type (admin only).
