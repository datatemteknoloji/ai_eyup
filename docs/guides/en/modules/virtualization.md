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
| Capacity | `/virt/capacity` | Effective capacity, N+1, runway, what-if (does a new VM fit?), placement |
| Reclaim | `/virt/reclaim` | Powered-off / idle / oversized VMs, snapshots, orphan disks, ISOs, unused datastores |
| Health checks | `/virt/health` | Health, compliance (ISO 27001), hardware, CVE/KB, upgrade findings; exceptions, command drafts, approved remediation |
| Changes | `/virt/changes` | Host/cluster config history (diff), baseline, drift findings |

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
