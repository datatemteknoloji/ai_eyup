# ainew — Windows GUIDE

Only the **Windows** module. Linux SSH, virtualization and OpenShift are out of scope.

**RBAC:** `windows`. Identities: Settings → WinRM.

```diagram
  Settings → WinRM
        │
        ▼
  /windows
        │
   ┌────┼────────────┐
   ▼    ▼            ▼
 WinRM  windows_     Event Log
        exporter
        │
        ▼
   Prometheus → metric_data
        │
  /windows/dashboard  /live-metrics  /aiops/chat
```

| Menu | Path | Actions |
|------|------|---------|
| Dashboard | `/windows/dashboard` | Summary |
| Windows servers | `/windows` | Inventory |
| Live metrics | `/windows/live-metrics` | Exporter series |
| Event Log | `/windows/events` | Event log |
| Windows Update | `/windows/updates` | Patching |
| Ansible/AWX | `/windows/ansible` | Automation |
| Reports | `/windows/reports` | Reports |
| AIOps | `/windows/aiops/chat` … `/analysis` | Assistant and ops |

WinRM/firewall 5985/5986 required. Linux `/servers` does not manage Windows. Level 1 wizards are Linux day-2.
