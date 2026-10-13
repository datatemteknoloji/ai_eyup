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
| Planning & Audit (subgroup) | — | Capacity, Reclaim, Health checks and Changes are grouped in this sidebar subgroup |
| Capacity | `/virt/capacity` | Tabs: Cluster, Datastore, What-if (does a new VM fit?), **If a host goes down (N+1)**, Reclaim simulation, Bulk placement, Placement, Thresholds |
| Reclaim | `/virt/reclaim` | Powered-off / idle / oversized VMs, snapshots, orphan disks, ISOs, unused datastores |
| Health checks | `/virt/health` | Health, compliance (ISO 27001), hardware, CVE/KB, upgrade findings; exceptions, command drafts, approved remediation |
| Changes | `/virt/changes` | Host/cluster config history (diff), baseline, drift findings |
| Backup & DR | `/virt/backup` | **Visible only when a backup provider (Veeam) is connected.** RPO/protection, jobs, repositories, unmatched objects, RPO targets, evidence |

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

## Decision layer (VMware · OLVM · OCP Virt)

One shared, deterministic engine collects findings periodically (fleet job `virt_insights`; admins can trigger **Run now**). Four dashboard cards (Capacity, Reclaim, Health, Changes) link to the pages.

- **Access:** vCenter, OLVM Manager and the OpenShift API only. No SSH or direct ESXi / KVM host connections; checks that need the host are marked **not measurable**.
- **Capacity:** effective Memory/CPU after the HA reserve, N+1 (largest host fails), days to threshold. What-if: enter vCPU / Memory / disk / count → which cluster fits. Placement: scored host candidates, rejected hosts with a reason.
- **Placement and HA (capacity):** What-if, Bulk placement, Host failure (N+1) and Placement share one core. With the vCenter *dedicated failover hosts* policy those hosts are closed to placement (their capacity counts as reserve; if the list cannot be read, 1 host is assumed and labelled). With the *slot policy* (host failures tolerated), when no free slot is left a VM **does not fit** even if memory does (limit: HA slots); the new VM's reservation is unknown so 1 slot/VM is assumed, and slot counts come from the last HA read.
- **If a host goes down (N+1):** once a cluster is selected, a **separate result per host** is calculated automatically (powered-on VMs on it are placed onto the remaining hosts). Memory is shown as *defined* (worst case; the verdict follows it) and *p95*, CPU as p95; rows are ordered by risk (Does not fit → Tight → Fits → No VMs). Click a row to see placed/unplaced VMs; to take several hosts down at once, pick hosts and press **Calculate for selected**. This screen is a **simulation, not a real failure**: real failures are in Health checks › Findings. From the *Impact* block of a hardware finding you can jump to that host's N+1 row. Affinity/DRS rules, VM reservations and HA restart priority are not evaluated.
- **Runway:** days to threshold for memory and datastores from the Theil–Sen slope of the daily mean (default thresholds Memory 85%, CPU 80%, datastore 85% — editable in Capacity › Thresholds). At least 14 days of data are required; otherwise "insufficient data" is shown and no estimate is invented.
- **Reclaim simulation:** if idle and oversized (by p95 CPU) VMs are reduced to the recommended size, the cluster's effective memory %, vCPU:core ratio and N+1 status are recomputed. Read-only: VMs are not resized; reducing vCPU does not free memory.
- **Bulk placement:** places several VM profiles (vCPU / memory / disk / count; optional anti-affinity group) per cluster independently; CSV export, the plan is not saved. Scope is **optionally** narrowed (instance → datacenter → cluster; selections appear as removable chips). The What-if screen has no host selector; host narrowing exists only in Bulk placement. Capacity is **never summed** across clusters; hosts without a cluster are computed independently.
- **What-if assumptions:** memory fully used, CPU computed with a per-vCPU assumption and — **not checked** — affinity/DRS rules, VM reservations and VLAN/portgroup access are listed on the result screen. For OpenShift Virtualization the virt-launcher memory overhead is not applied; the approximate Red Hat documentation value is shown labelled *documentation assumption*.
- **Method badges:** every number/card carries a class badge (Data, Calculation, Forecast, Rule, Matching, AI) and an (i) explaining how it was produced / which data / its limits. Single source: `GET /api/v1/methods`.
- **Backup & DR (Veeam VBR, optional):** Integrations › Backup provider (optional) (`/integrations/backup`, admin) sets up a read-only Veeam REST connection; without it the menu, tab, findings and chat tools **never appear** and Veeam-less behaviour is unchanged. Recommended VBR role is *Backup Viewer* (the VBR version `serverInfo` is Administrator-only). Only the fields verified in the `1.3-rev1` documentation are coded; other revisions (including 12.x) are selectable but flagged **fields not verified**. Immutability/encryption/CBT cannot be verified and are *not measurable*; RTO is never estimated. The DEMO/fixture provider is **off** by default (`BACKUP_DEMO_ENABLED`). With an external (remote) LLM enabled, chat tools send VM/job/repository **names** and status/RPO summaries to the model; credentials, endpoints and raw API responses are not sent (a warning is shown on the Backup provider page).
- **Scope note:** the feature plan has 14 items; **13 are implemented (item 6 — ServiceNow/Teams — excluded)**. Item 6 does not exist in this release.
- **Reclaim:** each item shows reclaimable vCPU / Memory / GB; snapshot and file scans come from the datastore browser (files attached to VMs and OLVM snapshot disks are never reported as orphans).
- **Health / compliance:** NTP, syslog, SSH, lockdown, HA/admission control, vMotion, uplink redundancy, multipath, OLVM fencing, OCP Virt eviction strategy. The compliance tab groups by ISO 27001 control; CSV/JSON export. **Audit evidence** and **Capacity plan (N+1)** reports live in `/infra-reports`.
- **Exceptions:** admins accept a finding with a reason and expiry; counted separately in scores.
- **Command drafts:** PowerCLI / `oc` draft plus rollback lines. ainew **does not run** drafts.
- **Reference packages** (Settings tab, admin): upload offline CVE/VMSA, KB and upgrade/HCL matrix JSON (sample schema downloadable). The KB package can optionally be added to RAG. Nothing is fetched from the internet.
- **Approved remediation (VMware only):** allowlisted actions — remove old snapshots, restart NTP, set NTP servers, stop SSH. First define a per-vCenter write account **different** from the read account in the Settings tab. A proposal becomes a **pending action** in Agent; it runs only after approval and the previous value is kept in the result.
- **Chat:** “is N+1 satisfied / how many hosts do I need”, “where does an 8 vCPU 32 GB VM fit”, “what can I reclaim”, “open health findings”, “what changed during the incident” are answered from engine output; the model does not compute numbers.
- **Incidents:** the virt incident screen shows a timeline (alarms, events, config changes, findings) and candidate causes.

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

`/virt/monitoring` and hub → Virtualization use **vCenter and OLVM/oVirt API → Timescale** (Prometheus is a separate binding). The metric listbox exposes all Timescale columns for the selected kind; chart series are locked to the selected objects. No scrape config writes.
