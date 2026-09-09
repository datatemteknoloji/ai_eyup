# ainew — Virtualization GUIDE

Only the **Virtualization** sidebar group: dashboard, infra reports, virt AIOps.

OpenShift command centre and full oVirt attach steps are in the **OpenShift / oVirt GUIDE**. Linux package pages are not here.

**RBAC:** `virtualization`. Adding a hypervisor also needs `integrations`.

| Menu | Path | Actions |
|------|------|---------|
| Dashboard | `/hypervisors` | Clusters, hosts, VMs, datastores |
| Infra reports | `/infra-reports` | Capacity, trends, Theil–Sen forecast |
| Assistant | `/virt/chat` | Placement, host CPU, Tools, snapshots |
| Command centre / events / incidents / analysis | `/virt/ops` … `/analysis` | Virt AIOps |

```diagram
  Integrations → vCenter/OLVM     (connection lives there)
                    │
                    ▼
              hypervisor sync
                    │
                    ▼
           servers + virt_*
                    │
         ┌──────────┼──────────┐
         ▼          ▼          ▼
   /hypervisors  /infra-reports  /virt/chat
```

Guest SSH is not required. Empty pages mean no hypervisor is connected (`/integrations/hypervisors`). Use a resolvable IP/FQDN.

```diagram
  Question (/virt/chat)
        │
        ▼
  Scope (VM / host / datastore name)
        │
        ▼
  Tools → virt tables / rare live API
        │
        ▼
  LLM → SSE
```

oVirt is not a separate menu; its VMs appear here. OCP projects/pods belong to the OpenShift menu.
