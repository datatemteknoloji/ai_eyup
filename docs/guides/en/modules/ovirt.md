# ainew — oVirt / OLVM GUIDE

oVirt and Oracle Linux Virtualization Manager are **not** a separate RBAC module. You need `virtualization` (views/chat) and `integrations` (connection).

```mermaid
flowchart LR
  UI[Integrations → vCenter/OLVM] --> API[hypervisor type=kvm]
  API --> OV[oVirt REST :443]
  OV --> SYNC[VM / host / datastore]
  SYNC --> MENU[Virtualization dashboard / reports / chat]
```

1. **Integrations → vCenter/OLVM** — type oVirt/KVM, test, save, sync VMs.  
2. **Virtualization → Dashboard** `/hypervisors`.  
3. **Infra reports** `/infra-reports`.  
4. **Assistant** `/virt/chat` with engine/cluster/VM names.

Same menus as vCenter; the record type is `kvm` (REST) vs `vmware` (SOAP). There is no separate “oVirt” sidebar group. Level 1 is not the oVirt API.
