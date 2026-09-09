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
| Events / incidents | `/openshift/events`, `/incidents` | Cluster ops |
| Assistant | `/openshift/chat` | Pods, nodes, PVC, CrashLoop |

Connect at Integrations → OpenShift (`/integrations/openshift`). Put internal API names in the **host** `/etc/hosts`.

## oVirt / OLVM

There is **no** separate sidebar group.

1. Integrations → vCenter/OLVM (`/integrations/hypervisors`)
2. Type **oVirt / KVM** (`kvm`), engine FQDN/IP, user/password, 443
3. Test → save → sync VMs
4. Results: Virtualization dashboard `/hypervisors`, infra reports, `/virt/chat`

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

Type `openshift_virt`. VMs appear in virt sync and `/openshift/vms`. Project/pod questions → OCP chat; host/datastore capacity → virt reports/chat.

ainew is not installed as an OpenShift Operator; it **manages** OpenShift. OCP chat does not replace Linux SSH. If the OLVM engine is unreachable, virt pages stay empty.
