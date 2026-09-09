# ainew — Integrations GUIDE

Module `integrations` attaches external sources. Domain menus fill **after** a successful connection.

| Menu | Path | Actions |
|------|------|---------|
| Inventory hub | `/integrations` | Source overview |
| UCMDB | `/integrations/ucmdb` | CMDB import |
| vCenter / OLVM | `/integrations/hypervisors` | VMware, oVirt, Proxmox, Hyper-V, OCP virt |
| Physical hosts | `/integrations/physical-hosts` | SSH/WinRM targets |
| Exadata | `/integrations/exadata` | Racks |
| OpenShift | `/integrations/openshift` | Cluster API |

Add → test → save → sync. Writing integrations needs `integrations`; viewing virt dashboards needs `virtualization`.
