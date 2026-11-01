import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { ChevronRight, Server } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'
import { OcpClusterTree } from '../components/openshift/OcpClusterTree'
import OcpInsightsStrip from '../components/insights/OcpInsightsStrip'
import { HostResourceChart, RESOURCE_ACCENT, ResourceGauge, VMStatusPie } from '../components/dashboard/ResourceCharts'

type OcpNode = {
  name: string
  role?: string | null
  status?: string | null
  cpu_cores?: number | null
  memory_gb?: number | null
  cpu_pct?: number | null
  mem_pct?: number | null
  pods_total: number
  pods_bad: number
  vms_total: number
  vms_running?: number
}
type OcpNs = {
  name: string
  display_name?: string | null
  system: boolean
  pods_bad: number
  vms_total: number
  vms_running?: number
}
type OcpCluster = {
  cluster_id: number
  name: string
  version?: string | null
  status?: string | null
  node_count: number
  nodes_not_ready: number
  project_count: number
  pod_count: number
  pods_bad: number
  vm_count: number
  nodes: OcpNode[]
  namespaces: OcpNs[]
}
type RiskPod = {
  id: number
  cluster_id: number
  project: string
  name: string
  status?: string | null
  node_name?: string | null
  restart_count?: number
  risk_severity?: string | null
}

function pct(v: number | null | undefined): string {
  if (v == null || Number.isNaN(v)) return '—'
  return `${Math.round(v)}%`
}

function avg(nodes: OcpNode[], key: 'cpu_pct' | 'mem_pct'): number | null {
  const vals = nodes.map(n => n[key]).filter((v): v is number => v != null && !Number.isNaN(v))
  if (!vals.length) return null
  return vals.reduce((a, b) => a + b, 0) / vals.length
}

/** OpenShift modülünün Dashboard'u: isimli küme özeti + küme altyapısı ağacı. */
export default function OpenShiftHome() {
  const t = useT()
  const q = useQuery<{ clusters: OcpCluster[] }>({
    queryKey: ['ocp-hierarchy'],
    staleTime: 60_000,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/hierarchy`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    },
  })
  const diskQ = useQuery<{ hosts?: { hypervisor_id: number; host: { host_name?: string; ds_used_gb?: number; ds_total_gb?: number; ds_usage_pct?: number } }[] }>({
    queryKey: ['hypervisor-host-metrics', 'ocp-dash'],
    staleTime: 60_000,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/host-metrics`)
      if (!r.ok) return { hosts: [] }
      return r.json()
    },
  })
  const risksQ = useQuery<{ risks: RiskPod[]; total: number }>({
    queryKey: ['openshift-risks', 'dashboard'],
    staleTime: 60_000,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/risks?limit=24`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    },
  })

  const clusters = q.data?.clusters ?? []
  const sum = (k: keyof OcpCluster) => clusters.reduce((n, c) => n + (Number(c[k]) || 0), 0)
  const nameOf = (id: number) => clusters.find(c => c.cluster_id === id)?.name || `#${id}`
  const notReady = clusters.flatMap(c =>
    c.nodes.filter(n => (n.status || '').toLowerCase() !== 'ready').map(n => ({ cluster: c.name, node: n.name, status: n.status })),
  )
  const vmNs = clusters.flatMap(c =>
    c.namespaces.filter(n => n.vms_total > 0).map(n => ({
      cluster: c.name,
      clusterId: c.cluster_id,
      ns: n.display_name || n.name,
      total: n.vms_total,
      running: n.vms_running ?? 0,
    })),
  )
  const risks = risksQ.data?.risks ?? []
  const nodes = clusters.flatMap(c => c.nodes)
  let cpuUsed = 0
  let cpuTotal = 0
  let memUsed = 0
  let memTotal = 0
  for (const n of nodes) {
    const cores = Number(n.cpu_cores) || 0
    const mem = Number(n.memory_gb) || 0
    if (cores > 0) {
      cpuTotal += cores
      if (n.cpu_pct != null) cpuUsed += cores * (Number(n.cpu_pct) / 100)
    }
    if (mem > 0) {
      memTotal += mem
      if (n.mem_pct != null) memUsed += mem * (Number(n.mem_pct) / 100)
    }
  }
  const diskByNode = new Map<string, number>()
  const diskByHv = new Map<number, { used: number; total: number }>()
  const nodeNames = new Set(nodes.map(n => n.name.toLowerCase()))
  for (const row of diskQ.data?.hosts || []) {
    const host = row.host || {}
    const key = (host.host_name || '').trim().toLowerCase()
    if (!key || !nodeNames.has(key)) continue
    if (host.ds_usage_pct != null) diskByNode.set(key, Number(host.ds_usage_pct) || 0)
    const total = Number(host.ds_total_gb) || 0
    const used = Number(host.ds_used_gb) || 0
    if (total <= 0) continue
    const cur = diskByHv.get(row.hypervisor_id)
    if (!cur || total > cur.total) diskByHv.set(row.hypervisor_id, { used, total })
  }
  let diskUsed = 0
  let diskTotal = 0
  diskByHv.forEach(v => { diskUsed += v.used; diskTotal += v.total })
  const vmRunning = nodes.reduce((n, node) => n + (node.vms_running || 0), 0)
  const vmTotal = sum('vm_count')
  const vmOff = Math.max(0, vmTotal - vmRunning)
  const chartHosts = [...nodes]
    .sort((a, b) => (Number(b.cpu_pct) || 0) - (Number(a.cpu_pct) || 0))
    .map(n => ({
      host_name: n.name,
      cpu_usage_pct: n.cpu_pct,
      mem_usage_pct: n.mem_pct,
      ds_usage_pct: diskByNode.get(n.name.toLowerCase()) ?? 0,
    }))
  const clusterNames = clusters.map(c => c.name).join(', ')
  const notReadyLabel = notReady.length
    ? notReady.map(n => n.node).join(', ')
    : t('ocp_dash_all_ready')

  return (
    <div className="space-y-5" data-testid="ocp-dashboard">
      <div className="flex items-start justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white">OpenShift — {t('nav_dashboard')}</h1>
          <p className="text-sm text-slate-400 mt-1">{t('ocp_dash_sub')}</p>
        </div>
        <Link to="/openshift" className="inline-flex items-center gap-1 text-xs text-rose-300 hover:text-rose-200">
          {t('nav_inventory')} <ChevronRight size={14} />
        </Link>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-6 gap-2">
        {[
          ['Cluster', clusters.length, clusterNames || '—'],
          ['Node', sum('node_count'), notReadyLabel],
          [t('ocp_not_ready'), sum('nodes_not_ready'), notReadyLabel],
          ['Pod', sum('pod_count'), `${sum('pods_bad')} ${t('ocp_problem')}`],
          [t('ocp_problem'), sum('pods_bad'), risks.slice(0, 3).map(r => r.name).join(', ') || t('ocp_dash_no_risks')],
          ['VM', sum('vm_count'), vmNs.map(v => v.ns).slice(0, 4).join(', ') || t('ocp_dash_no_vm_ns')],
        ].map(([label, val, sub]) => (
          <div key={String(label)} className="rounded-xl border border-white/[0.06] bg-cyber-card p-3 min-w-0" title={String(sub)}>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
            <div className="text-xl font-bold text-white">{q.isLoading ? '…' : val}</div>
            <div className="text-[11px] text-slate-400 truncate mt-1">{q.isLoading ? '' : sub}</div>
          </div>
        ))}
      </div>

      {(cpuTotal > 0 || memTotal > 0 || diskTotal > 0) && (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          {cpuTotal > 0 && (
            <ResourceGauge label={t('hv_cpu_usage')} used={cpuUsed} total={cpuTotal} unit="cores" accent={RESOURCE_ACCENT.cpu} />
          )}
          {memTotal > 0 && (
            <ResourceGauge label={t('hv_mem_usage')} used={memUsed} total={memTotal} unit="GB" accent={RESOURCE_ACCENT.memory} />
          )}
          {diskTotal > 0 && (
            <ResourceGauge label={t('hv_disk_usage')} used={diskUsed} total={diskTotal} unit="GB" accent={RESOURCE_ACCENT.disk} />
          )}
        </div>
      )}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        <VMStatusPie poweredOn={vmRunning} poweredOff={vmOff} />
        <HostResourceChart hosts={chartHosts} limit={Math.max(chartHosts.length, 1)} />
      </div>

      <OcpInsightsStrip />

      <div>
        <h2 className="text-sm font-semibold text-white mb-2">{t('ocp_infra_tab')}</h2>
        <OcpClusterTree />
      </div>

      <div className="space-y-3">
        <h2 className="text-sm font-semibold text-white">{t('ocp_tab_clusters')}</h2>
        {q.isLoading && <p className="text-sm text-slate-500">{t('loading')}</p>}
        {q.isError && <p className="text-sm text-red-300">{t('dash_vm_error')}</p>}
        {!q.isLoading && clusters.length === 0 && (
          <p className="text-sm text-slate-500">{t('ocp_add_cluster_first')}</p>
        )}
        {clusters.map(c => {
          const cpu = avg(c.nodes, 'cpu_pct')
          const mem = avg(c.nodes, 'mem_pct')
          const healthy = (c.status || '').toUpperCase() !== 'ERROR' && c.nodes_not_ready === 0
          const vmHere = c.namespaces.filter(n => n.vms_total > 0)
          return (
            <section key={c.cluster_id} className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 space-y-3">
              <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="min-w-0">
                  <div className="text-white font-semibold">{c.name}</div>
                  <div className="text-xs text-slate-400 mt-0.5">
                    {c.version || t('ocp_version_unknown')}
                    {' · '}{t('dash_node_count', { n: c.node_count })}
                    {' · '}{t('dash_ns_count', { n: c.project_count })}
                    {' · '}{t('dash_pod_count', { n: c.pod_count })}
                    {c.pods_bad ? ` · ${t('ocp_n_bad', { n: c.pods_bad })}` : ''}
                    {' · '}{t('dash_vm_count', { n: c.vm_count })}
                    {cpu != null ? ` · CPU ${pct(cpu)}` : ''}
                    {mem != null ? ` · Mem ${pct(mem)}` : ''}
                  </div>
                </div>
                <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold uppercase ${
                  healthy ? 'bg-green-500/20 text-green-300 border-green-500/40' : 'bg-red-500/20 text-red-300 border-red-500/40'
                }`}>
                  {healthy ? 'OK' : (c.status || t('ocp_unhealthy'))}
                </span>
              </div>

              <div className="overflow-x-auto">
                <table className="w-full text-xs">
                  <thead className="text-slate-500">
                    <tr className="text-left">
                      <th className="font-medium py-1 pr-3">Node</th>
                      <th className="font-medium py-1 pr-3">{t('col_status')}</th>
                      <th className="font-medium py-1 pr-3">CPU</th>
                      <th className="font-medium py-1 pr-3">Mem</th>
                      <th className="font-medium py-1 pr-3">Pod</th>
                      <th className="font-medium py-1">VM</th>
                    </tr>
                  </thead>
                  <tbody>
                    {c.nodes.map(n => {
                      const ready = (n.status || '').toLowerCase() === 'ready'
                      return (
                        <tr key={n.name} className="border-t border-white/[0.04] text-slate-300">
                          <td className="py-1.5 pr-3 text-white">
                            {n.name}
                            {n.role ? <span className="text-slate-500"> · {n.role}</span> : null}
                          </td>
                          <td className={`py-1.5 pr-3 ${ready ? 'text-emerald-300' : 'text-red-300'}`}>{n.status || '—'}</td>
                          <td className="py-1.5 pr-3">{pct(n.cpu_pct)}</td>
                          <td className="py-1.5 pr-3">{pct(n.mem_pct)}</td>
                          <td className="py-1.5 pr-3">
                            {n.pods_total}{n.pods_bad ? <span className="text-amber-300"> ({n.pods_bad})</span> : null}
                          </td>
                          <td className="py-1.5">{n.vms_running ?? 0}/{n.vms_total}</td>
                        </tr>
                      )
                    })}
                    {c.nodes.length === 0 && (
                      <tr><td colSpan={6} className="py-2 text-slate-500">{t('ocp_add_cluster_first')}</td></tr>
                    )}
                  </tbody>
                </table>
              </div>

              {vmHere.length > 0 && (
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">{t('ocp_dash_vm_ns')}</div>
                  <div className="flex flex-wrap gap-1.5">
                    {vmHere.map(n => (
                      <Link
                        key={n.name}
                        to={`/openshift/vms?cluster=${c.cluster_id}`}
                        className="text-[11px] px-2 py-1 rounded-lg border border-white/[0.08] text-slate-300 hover:text-white hover:border-rose-500/40"
                      >
                        {n.display_name || n.name}
                        <span className="text-slate-500"> · {n.vms_running ?? 0}/{n.vms_total}</span>
                      </Link>
                    ))}
                  </div>
                </div>
              )}
            </section>
          )
        })}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3">
        <section className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
          <div className="flex items-center justify-between gap-2 mb-2">
            <h2 className="text-sm font-semibold text-white">{t('ocp_dash_risk_title')}</h2>
            <Link to="/openshift?section=riskler" className="text-[11px] text-rose-300 hover:text-rose-200 inline-flex items-center gap-1">
              {t('ocp_nav_risks')} <ChevronRight size={12} />
            </Link>
          </div>
          {risksQ.isLoading && <p className="text-sm text-slate-500">{t('loading')}</p>}
          {!risksQ.isLoading && risks.length === 0 && (
            <p className="text-sm text-slate-500">{t('ocp_dash_no_risks')}</p>
          )}
          <ul className="space-y-1.5">
            {risks.map(r => (
              <li key={r.id} className="flex items-start justify-between gap-2 text-xs border-b border-white/[0.04] pb-1.5">
                <div className="min-w-0">
                  <div className="text-white truncate">{r.project}/{r.name}</div>
                  <div className="text-slate-500 truncate">
                    {nameOf(r.cluster_id)} · {r.node_name || '—'} · {r.status || '—'}
                    {r.restart_count ? ` · restart ${r.restart_count}` : ''}
                  </div>
                </div>
                <span className={r.risk_severity === 'critical' ? 'text-red-300' : 'text-amber-300'}>
                  {r.risk_severity || r.status || '—'}
                </span>
              </li>
            ))}
          </ul>
        </section>

        <section className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
          <div className="flex items-center gap-2 mb-2">
            <Server size={14} className="text-slate-400" />
            <h2 className="text-sm font-semibold text-white">{t('ocp_dash_not_ready_title')}</h2>
          </div>
          {notReady.length === 0 && <p className="text-sm text-slate-500">{t('ocp_dash_all_ready')}</p>}
          <ul className="space-y-1.5">
            {notReady.map(n => (
              <li key={`${n.cluster}-${n.node}`} className="text-xs text-slate-300">
                <span className="text-white">{n.node}</span>
                <span className="text-slate-500"> · {n.cluster} · {n.status || '—'}</span>
              </li>
            ))}
          </ul>
          {vmNs.length > 0 && (
            <div className="mt-4">
              <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">{t('ocp_dash_vm_ns')}</div>
              <ul className="space-y-1">
                {vmNs.map(v => (
                  <li key={`${v.cluster}-${v.ns}`}>
                    <Link to={`/openshift/vms?cluster=${v.clusterId}`} className="text-xs text-slate-300 hover:text-white">
                      {v.ns} <span className="text-slate-500">· {v.cluster} · {v.running}/{v.total}</span>
                    </Link>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </section>
      </div>
    </div>
  )
}
