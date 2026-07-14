# Server Management

ainew manages Linux servers over SSH. The Servers page is the central inventory: add servers, assign credentials, view live status, run commands, and access a browser terminal.

---

## Adding a server

1. Open **Servers** in the sidebar
2. Click **+ Yeni Sunucu** (New Server)
3. Enter:
   - **Name:** display label (e.g. `db-primary`)
   - **IP Address:** reachable from the management host
   - **SSH Port:** default 22
4. Save — ainew runs an immediate SSH ping to set initial health status

---

## SSH credentials

ainew stores SSH credentials separately so one credential can serve multiple servers.

**Credential types:**
- **Password** — username + password
- **SSH Key** — username + PEM private key (paste the full key)

Create a credential in **Settings → Credentials**, then assign it to a server from the server detail drawer.

**Test connection:** In the server drawer, click **Bağlantıyı Test Et** — ainew SSH's in with the credential and returns the exit code.

---

## Health monitoring

ainew pings all servers every 5 minutes via SSH (`echo "ping"`). Status:

| Indicator | Meaning |
|---|---|
| Green dot | SSH reachable, responded within timeout |
| Red dot | SSH failed or timed out |
| Gray dot | Never checked, or server added but not yet pinged |

The ping uses the assigned credential. If no credential is assigned, it tries the management host's default SSH key.

---

## Live metrics

Metrics (CPU%, memory%, disk%) appear in the server drawer after Node Exporter is installed.

**Install Node Exporter:**

1. Open the server drawer
2. Go to **Monitoring** tab
3. Click **Node Exporter Kur**

ainew SSH's in and runs:
```bash
# Downloads Node Exporter, creates systemd service, starts it
# Registers server IP in Prometheus targets at /prometheus/targets/{server_id}.json
```

Metrics appear in Prometheus within 2 minutes and in ainew's **Live Metrics** page within the next collection tick.

**Metric types collected:**
- `cpu_percent` — CPU utilization %
- `mem_percent` — RAM utilization %
- `disk_percent` — root disk utilization %
- `disk_read_bytes`, `disk_write_bytes` — disk I/O
- `network_bytes_sent`, `network_bytes_recv` — network I/O

---

## Server drawer

Click any server row to open the detail drawer on the right. Tabs:

| Tab | Content |
|---|---|
| **Bilgi** (Info) | IP, port, OS info, VM details (if synced from hypervisor) |
| **Performans** | CPU/memory/disk graphs, last 1h/6h/24h |
| **Eventler** | Recent AIOps events for this server |

From the drawer you can also:
- Run a health check
- Open a web terminal
- Edit server metadata
- Delete the server

---

## Web Terminal

Click **Terminal** in the server drawer to open a browser-based SSH terminal.

The terminal uses WebSocket (`/api/v1/terminal/ws/{server_id}`). The backend creates a paramiko SSH session and relays I/O via WebSocket. The terminal supports full ANSI color codes, arrow keys, and tab completion.

**Resize:** the terminal auto-resizes when the browser window changes.

**Session lifetime:** the WebSocket closes when you navigate away or close the tab.

---

## VM sync (hypervisor integration)

If you've added a VMware ESXi hypervisor in the **Hypervisors** page, you can sync VMs to the server inventory:

1. Open **Hypervisors**
2. Click **VM'leri Senkronize Et** on a hypervisor
3. ainew queries the ESXi API and creates/updates server records for each VM

VM-synced servers have additional fields: `vm_name`, `vm_cpu_count`, `vm_memory_mb`, `vm_power_state`, `vm_cluster`, `vm_datastore`.

---

## AI-Ready flag

The **AI-Ready** flag marks servers the AI agent is allowed to operate on. This is a safety gate — the agent will not run commands on servers not marked AI-Ready.

Set bulk AI-Ready status: **Servers → Seçili Sunucuları AI-Ready Yap**.

Per-server: toggle in the server drawer.

---

## Remote commands

The **Ansible** page allows running ad-hoc commands on server groups. For single-server commands, use the web terminal or the AI agent.

**Via API (for scripting):**
```bash
curl -X POST http://localhost:8000/api/v1/ansible/adhoc \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{
    "server_ids": [1, 2, 3],
    "module": "shell",
    "args": "df -h",
    "become": false
  }'
```

---

## OS info refresh

ainew stores OS type, kernel version, and hostname. To refresh:

```bash
POST /api/v1/servers/refresh-os-info
{ "server_ids": [1, 2, 3] }
```

Or click **OS Bilgisini Yenile** in the Servers page toolbar.

---

## Related

- [Hypervisor Management](../api-reference.md#hypervisors)
- [Live Metrics API](../api-reference.md#monitoring)
- [Terminal WebSocket](../api-reference.md#terminal-websocket)
- [Ansible / AWX](../api-reference.md#ansible--awx)
