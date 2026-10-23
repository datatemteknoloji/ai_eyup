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
| Backup (Veeam VBR) | `/integrations/backup` | Read-only Veeam REST connection (admin only): endpoint, user (recommended role Backup Viewer), REST API revision, CA/SSL. Without it the Backup & DR menu stays hidden. Revisions other than 1.3-rev1 are selectable with a "fields not verified" warning. A warning is shown when an external LLM is enabled because backup data (VM/job/repository names) reaches the model |
| Hardware management (Dell OME / HPE OneView–OVGD) | `/integrations/hardware` | Optional, read-only REST (admin only): OME 4.x or OneView appliance(s) / Global Dashboard; iLO/iDRAC are never contacted directly. Authentication is attempted ONCE; if rejected, sync halts (so the account is not locked) and only a successful “Test connection” resumes it. Data appears on the “Hardware” page (`/hardware`, `hardware` module) and in the “Hardware” card of the physical-server drawer. Menu/card are hidden without a connection. |
| Automic (UC4) | `/integrations/automic` | Read-only Automic source DB (Oracle) wizard, test, discovery, collection — see Automation GUIDE (`modules/automation.md`); DBA grants: `automic-source-dba-grants.md` |

Add → test → save → sync. Writing integrations needs `integrations`; viewing virt dashboards needs `virtualization`. Automic system management needs `integrations`; viewing/assistant needs `automation`. Only admins manage the backup (Veeam) connection; Backup & DR pages need `virtualization`. The hardware-management connection is admin-only; the Hardware page and card (which show BMC IP and serial/service tag) need the separate `hardware` module (default admin only; BMC data is never added to `/servers` APIs).
