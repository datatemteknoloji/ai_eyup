# Agentic AI

The AI Agent page gives the LLM the ability to take actions — run SSH commands, check metrics, list servers — while keeping humans in control of anything destructive.

---

## What it does

Unlike the Chat page (read-only Q&A), the Agent can:

- Run shell commands on servers (via SSH)
- Check server health and metrics
- List and filter servers
- Trigger Ansible playbooks
- Create incidents or events

Every action goes through a guard layer. Low-risk actions (reading metrics, running `ls`) execute automatically. High-risk actions (running as root, modifying system files) require you to click **Approve** before the agent proceeds.

---

## Architecture: LangGraph + guard layer

```
User message
    │
    ▼
LangGraph graph (services/agent/graph.py)
    │
    ├── Planner node: LLM decides which tool to call
    │
    ├── Guard node (services/agent/guard.py):
    │   ├── LOW risk → execute immediately
    │   └── HIGH risk → create AgentAction (status: pending_approval)
    │         │
    │         └── Frontend: "Approve / Reject" buttons appear
    │               │ (user clicks Approve)
    │               ▼
    ├── Executor node (services/agent/executor.py):
    │   ├── run_command → paramiko SSH
    │   ├── get_server_metrics → TimescaleDB query
    │   ├── list_servers → DB query
    │   └── ... (more tools in services/agent/tools.py)
    │
    └── Responder node: LLM summarizes results → user
```

The graph runs one full iteration per message. Multi-step tasks (e.g. "check disk on all servers and list the top 3") run multiple tool calls in a single response.

---

## Available tools

| Tool | Risk level | Description |
|---|---|---|
| `list_servers` | Low | List servers with health status |
| `get_server_metrics` | Low | Fetch CPU/mem/disk for a server |
| `run_command` | Low | Run a non-root shell command |
| `run_command_as_root` | **High** | Run a command with sudo/root |
| `install_package` | **High** | Install a package via SSH |
| `restart_service` | **High** | Restart a systemd service |
| `get_logs` | Low | Fetch last N lines of a log file |
| `trigger_health_check` | Low | Ping a server's health |
| `create_incident` | Low | Open a new incident |

High-risk tools pause execution and wait for human approval.

---

## Human-in-the-loop approval flow

1. You send: "Install nginx on web-01"
2. Agent plans: call `install_package` on server 1
3. Guard classifies: `install_package` = HIGH risk
4. Agent stops and shows: **"Onay Bekleniyor: install nginx on 192.168.1.10 as root"**
5. You click **Onayla** (Approve) or **Reddet** (Reject)
6. If approved: command executes, result returned to LLM for summary
7. If rejected: agent is notified and reports "action rejected by user"

Pending approvals are also shown in the top-right notification badge.

---

## How-to: Run your first agent task

1. Open **Agent** in the sidebar
2. Select target servers from the server selector
3. Type: "Show disk usage on all selected servers"
4. The agent runs `df -h` via SSH and returns a table of results

For a task requiring approval:
1. Type: "Restart the nginx service on web-01"
2. The agent pauses with an approval card
3. Click **Onayla** — nginx restarts, agent confirms

---

## How-to: Review pending approvals

Pending approvals are listed at the top of the Agent page and in the notification badge.

You can also fetch them via API:
```bash
curl http://localhost:8000/api/v1/agent/actions/pending \
  -H "Authorization: Bearer <token>"
```

Response:
```json
[
  {
    "id": 42,
    "action_type": "run_command_as_root",
    "description": "systemctl restart nginx",
    "server_id": 1,
    "requires_root": true,
    "status": "pending_approval"
  }
]
```

Approve:
```bash
curl -X POST http://localhost:8000/api/v1/agent/actions/42/approve \
  -H "Authorization: Bearer <token>"
```

---

## Explanation: Why human-in-the-loop?

AI models make mistakes. An LLM asked to "clean up old logs" might decide to run `rm -rf /var/log/*` — technically correct but likely catastrophic.

The guard layer prevents this by:
1. Classifying tool calls by risk at call time (not prompt time)
2. Blocking high-risk actions unconditionally until a human approves
3. Logging every action to the audit trail for accountability

**Trade-off:** Approval friction slows down multi-step automation. For fully automated workflows, consider Ansible (which has its own approval and dry-run mechanisms) rather than the AI agent.

---

## Guard policy reference (`services/agent/policy.py`)

| Action pattern | Risk level | Trigger |
|---|---|---|
| Read-only commands (`ls`, `df`, `ps`, `cat`) | Low | Auto-execute |
| Service restart | High | Requires approval |
| Package install/remove | High | Requires approval |
| File write / `rm` | High | Requires approval |
| `sudo` / `su` | High | Requires approval |
| Network config changes | High | Requires approval |

Policy is implemented as pattern matching on tool name + arguments, not LLM classification. The LLM cannot override the guard layer.

---

## Related

- [AI Chat](ai-chat.md) — read-only Q&A mode
- [Agent API reference](../api-reference.md#agentic-ai)
- [Audit Log](../api-reference.md#audit-log)
