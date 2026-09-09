# ainew — Linux GUIDE

Linux module and Linux-related pages: servers, metrics, packages/patch, repo, Ansible, Linux AIOps, SSH identities, physical-host onboarding, and Level 1 for day-2.

Virtualization, Windows and OpenShift menus are not in this pack.

**RBAC:** `linux`. Physical add: `integrations`. SSH: Settings (admin). Level 1: `level1`.

```diagram
  Settings → Linux SSH          Integrations → Physical hosts
              │                              │
              └──────────┬───────────────────┘
                         ▼
                   /servers
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
           SSH 22    node_exporter  Level 1 Dropt
                      Prometheus
                         ▼
                    metric_data
                         │
              /linux/dashboard  /metrics  /linux/chat
```

| Menu | Path | Actions |
|------|------|---------|
| Dashboard | `/linux/dashboard` | Fleet summary |
| Linux servers | `/servers` | Inventory, identity, AI-ready, terminal |
| Live metrics | `/metrics` | CPU / memory / disk |
| Packages / System update / Local repo | `/packages`, `/system-update`, `/repositories` | Patch and repos |
| Ansible/AWX | `/ansible` | Automation |
| Reports | `/linux/reports` | Reports |
| AIOps | `/linux/chat`, `/ops`, `/events`, `/incidents`, `/analysis` | Assistant and ops |

Related: Settings → Linux SSH, Integrations → Physical hosts, Level 1 (`/level1`, Request → Preview → Apply). Level 1 is not the same engine as `/packages`.

ainew itself is installed with Docker Compose (`install-rhel.sh`). Target Linux hosts only need SSH. Fleet scans are capped. Chat does not edit Prometheus scrape config.
