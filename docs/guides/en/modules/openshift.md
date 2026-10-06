# ainew — OpenShift and oVirt GUIDE

Everything about **OpenShift Container Platform** and **oVirt / OLVM** (including OpenShift Virtualization / KubeVirt): connections, menus, chat, data flow.

**RBAC:** `openshift`, `virtualization` (OLVM results), `integrations` (connect).

```diagram
                    ainew
                      │
         ┌────────────┼────────────┐
         ▼                         ▼
   OpenShift API              oVirt / OLVM
   (kube API + token)         (REST :443, type=kvm)
         │                         │
         ▼                         ▼
  /openshift/*                hypervisor sync
  ops, inventory,             → servers + virt_*
  vms, events, chat                │
                              /hypervisors
                              /virt/chat
                              /infra-reports
```

## OpenShift menus

| Menu | Path | Actions |
|------|------|---------|
| Command centre | `/openshift/ops` | Critical summary |
| Inventory | `/openshift` | Cluster / node / project |
| Virtual Machines | `/openshift/vms` | KubeVirt / OCP VMs |
| Monitoring | `/openshift/monitoring` | API: Node/Pod/VM + `metrics.k8s.io` → Timescale. Prometheus: DCGM + kubevirt (Settings binding). Hub `/monitoring` |
| Events / incidents | `/openshift/events`, `/incidents` | Cluster ops |
| Assistant | `/openshift/chat` | Pods, nodes, PVC, CrashLoop |
| Planning & Audit (subgroup) | — | The 4 screens below are grouped in this sidebar subgroup (same name under Virtualization) |
| Capacity | `/openshift/capacity` | Worker allocatable vs requests, request %, N+1 (largest worker fails); **scenario**: do selected drained nodes / new pods still fit (from the last scan summary) |
| Reclaim | `/openshift/reclaim` | Unbound / unused PVCs, pods requesting far above usage (VM/DataVolume PVCs excluded) |
| Incidents (timeline) | `/openshift/incidents` | Incident detail shows events + findings + pod status / K8s events / log error lines and root-cause candidates (OOMKilled, image pull, scheduling, volume, probe, CrashLoop, node, operator) |
| Health | `/openshift/health` | ClusterOperators, MachineConfigPools, Compliance Operator results, version / updates; exceptions (admin); **node risk card** (counts of NotReady / pressure / reboot / connectivity events in recent days, no prediction) |
| Changes | `/openshift/changes` | History + diff of nodes, MachineConfigPools (rendered config + source MachineConfigs), operator versions, cluster config (proxy, OAuth, APIServer, Scheduler, Ingress); mark baseline (operator) and baseline-deviation findings |

Connect at Integrations → OpenShift (`/integrations/openshift`). Put internal API names in the **host** `/etc/hosts`.

## oVirt / OLVM

There is **no** separate sidebar group.

1. Integrations → vCenter/OLVM (`/integrations/hypervisors`)
2. Type **oVirt / KVM** (`kvm`), engine FQDN/IP, user/password, 443
3. Test → save → sync VMs
4. Results: Virtualization dashboard `/hypervisors`, infra reports, `/virt/chat`, monitoring `/virt/monitoring`

Periodic jobs write the same tables as vCenter: hosts, storage domains, clusters, VM statistics, engine events (`ovirt_event`). VM sync is paginated and prunes VMs removed from the engine. Linux/Windows server lists can filter by hypervisor (e.g. OLVM only).

```diagram
  OLVM Engine (REST)
        │
        ▼
  type = kvm
        │
        ▼
  sync-vms / host / storage domain
        │
        ▼
  /hypervisors   /infra-reports   /virt/chat
```

## OpenShift Virtualization

KubeVirt VMs appear in two places:

1. **OpenShift → Virtual Machines** (`/openshift/vms`) — live API list  
2. **Linux Servers / virt inventory** (`/servers`, hypervisor sync) — `servers` table  

OpenShift cluster sync (`/integrations/openshift` → Sync) auto-creates/updates a managed `openshift_virt` hypervisor and writes KubeVirt VMs into `servers`. A separate manual hypervisor entry is **not required**. Linux guests show under **Linux → Linux Servers**. VM name vs OS hostname mismatch uses the same filter as VMware (guest agent or SSH OS refresh).

ainew is not installed as an OpenShift Operator; it **manages** OpenShift. OCP chat does not replace Linux SSH. If the OLVM engine is unreachable, virt pages stay empty. Monitoring **API mode** uses `metrics.k8s.io`; **Prometheus mode** reads DCGM/kubevirt from the OpenShift-bound registry source. Other sources appear on the hub by label; Unified chat requires the full label.
