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
| Automic (UC4) | `/integrations/automic` | Read-only Automic source DB (Oracle) wizard, test, discovery, collection — see Automation GUIDE (`modules/automation.md`); DBA grants: `automic-source-dba-grants.md` |

Add → test → save → sync. Writing integrations needs `integrations`; viewing virt dashboards needs `virtualization`. Automic system management needs `integrations`; viewing/assistant needs `automation`.
