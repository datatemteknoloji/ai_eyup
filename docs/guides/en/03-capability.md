## 12. Capability Guide — menus and actions

Unauthorised modules are hidden.

### 12.1–12.2 Dashboard and Executive

`/dashboard` · `/executive` · `/chat` · `/agent` (approved tools).

### 12.3 Linux (`linux`)

`/linux/dashboard` · `/servers` · `/metrics` · `/packages` · `/system-update` · `/repositories` · `/ansible` · `/linux/reports` · AIOps `/linux/chat|ops|events|incidents|analysis`.

Related: Settings → Linux SSH, Integrations → Physical hosts, Level 1.

### 12.4 Windows (`windows`)

`/windows/dashboard` · `/windows` · `/windows/live-metrics` · `/windows/events` · `/windows/updates` · `/windows/ansible` · `/windows/reports` · `/windows/aiops/*`.

Related: Settings → WinRM.

### 12.5 Virtualization (`virtualization`)

`/hypervisors` · `/infra-reports` · `/virt/chat` · `/virt/ops|events|incidents|analysis`.

Connections are **not** added here — Integrations → vCenter/OLVM.

### 12.6 Exadata

`/exadata` · reports · AIOps. Connect at `/integrations/exadata`.

### 12.7 OpenShift and oVirt

OpenShift: `/openshift/ops` · `/openshift` · `/openshift/vms` · events · incidents · `/openshift/chat`.

oVirt/OLVM: Integrations → vCenter/OLVM (`kvm`) then virt dashboard and `/virt/chat`. KubeVirt: `/openshift/vms` plus virt inventory.

### 12.8 Level 1

`/level1` · `/level1/console/:id` · `/level1/ops/…` · `/level1/jobs` · admin audit/settings.

```diagram
  Ops centre ──► Console / wizard ──► Request ID ──► Preview ──► Apply ──► Jobs
```

Wizards: terminal, users, hostname, reboot, services, sudoers, filesystem/LVM, packages, paths, logs, limits, sysctl, network/VLAN, ASM, mail.

### 12.9–12.11 Integrations and other

Hub `/integrations`, UCMDB `/integrations/ucmdb`, hypervisors `/integrations/hypervisors`, physical hosts, Exadata, OpenShift inventory. Applications, knowledge, custom reports, audit, users, Settings (About = GUIDE download).
