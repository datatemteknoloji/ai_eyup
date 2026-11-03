import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { AlertTriangle, ChevronRight } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'
import { OcpClusterTree } from '../components/openshift/OcpClusterTree'
import OcpInsightsStrip from '../components/insights/OcpInsightsStrip'
import OcpResourceDetailDrawer from '../components/openshift/OcpResourceDetailDrawer'
import { ColumnTable, type TableColumn } from '../components/ColumnTable'
import UsageBar from '../components/openshift/UsageBar'
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
  reason?: string | null
  node_name?: string | null
  restart_count?: number
  ready?: string | null
  owner_kind?: string | null
  owner_name?: string | null
  risk_severity?: string | null
}

const SEV_ORDER: Record<string, number> = { critical: 0, high: 1, warning: 2 }
const SEV_TONE: Record<string, string> = {
  critical: 'bg-red-500/15 text-red-300 border-red-500/30',
  high: 'bg-orange-500/15 text-orange-300 border-orange-500/30',
  warning: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
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

function nodeTip(label: string, p: number | null | undefined, total: number | null | undefined, unit: string): string | undefined {
  if (p == null) return undefined
  if (!total) return `${label} ${pct(p)}`
  const used = (total * p) / 100
  return `${label} ${pct(p)} · ${used.toFixed(1)} / ${total} ${unit}`
}

/** OpenShift modülünün Dashboard'u: isimli küme özeti + küme altyapısı ağacı. */
export default function OpenShiftHome() {
  const t = useT()
  const [sevFilter, setSevFilter] = useState<'all' | 'critical' | 'high' | 'warning'>('all')
  const [detail, setDetail] = useState<RiskPod | null>(null)
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
      const r = await fetch(`${API_BASE_URL}/openshift/risks?limit=200`)
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
  const risks = useMemo(() => risksQ.data?.risks ?? [], [risksQ.data])
  // Backend `total` = limit'ten önceki gerçek risk sayısı (eski sürüm yanıtında yoksa satır sayısına düş).
  const riskTotal = Math.max(risksQ.data?.total ?? 0, risks.length)
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
  const nrCount = sum('nodes_not_ready')
  const topRiskNames = risks.slice(0, 3).map(r => r.name).join(', ')

  const sevCounts = useMemo(() => {
    const c: Record<string, number> = { critical: 0, high: 0, warning: 0 }
    for (const r of risks) c[r.risk_severity || 'warning'] = (c[r.risk_severity || 'warning'] || 0) + 1
    return c
  }, [risks])
  const riskRows = useMemo(
    () => (sevFilter === 'all' ? risks : risks.filter(r => (r.risk_severity || 'warning') === sevFilter)),
    [risks, sevFilter],
  )

  const sevLabel = (s: string) => (
    s === 'critical' ? t('ocp_dash_sev_critical') : s === 'high' ? t('ocp_dash_sev_high') : t('ocp_dash_sev_warning'))
  const riskColumns: TableColumn<RiskPod>[] = [
    {
      id: 'pod', label: t('ocp_dash_col_pod'),
      text: r => `${r.project}/${r.name}`,
      render: r => (
        <div className="min-w-0 max-w-[280px]">
          <div className="text-white truncate" title={r.name}>{r.name}</div>
          <div className="text-slate-500 truncate" title={r.project}>{r.project}</div>
        </div>
      ),
    },
    { id: 'cluster', label: t('ocp_dash_col_cluster'), text: r => nameOf(r.cluster_id) },
    { id: 'node', label: t('ocp_dash_col_node'), text: r => r.node_name || '' },
    {
      id: 'reason', label: t('ocp_dash_col_reason'),
      text: r => [r.status, r.reason].filter(Boolean).join(' '),
      render: r => (
        <div className="min-w-0">
          <div className="text-slate-200">{r.status || '—'}</div>
          {r.reason && r.reason !== r.status ? <div className="text-slate-500 truncate max-w-[180px]" title={r.reason}>{r.reason}</div> : null}
        </div>
      ),
    },
    {
      id: 'restarts', label: t('ocp_dash_col_restarts'),
      text: r => String(r.restart_count ?? 0), num: r => r.restart_count ?? 0,
      render: r => <span className={(r.restart_count || 0) >= 10 ? 'text-red-300 font-semibold' : (r.restart_count || 0) >= 5 ? 'text-amber-300' : ''}>{r.restart_count ?? 0}</span>,
    },
    { id: 'ready', label: t('ocp_dash_col_ready'), text: r => r.ready || '' },
    {
      id: 'owner', label: t('ocp_dash_col_owner'),
      text: r => [r.owner_kind, r.owner_name].filter(Boolean).join('/'),
      render: r => (r.owner_name
        ? <span className="text-slate-300 truncate inline-block max-w-[200px] align-bottom" title={`${r.owner_kind || ''}/${r.owner_name}`}>
          <span className="text-slate-500">{r.owner_kind}/</span>{r.owner_name}
        </span>
        : <span className="text-slate-500">—</span>),
    },
    {
      id: 'severity', label: t('ocp_dash_col_severity'),
      text: r => r.risk_severity || 'warning',
      num: r => 3 - (SEV_ORDER[r.risk_severity || 'warning'] ?? 2),
      render: r => {
        const s = r.risk_severity || 'warning'
        return <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold uppercase ${SEV_TONE[s] || SEV_TONE.warning}`}>{sevLabel(s)}</span>
      },
    },
  ]

  const nodeColumns = (): TableColumn<OcpNode>[] => [
    {
      id: 'name', label: 'Node',
      text: n => `${n.name} ${n.role || ''}`,
      render: n => (
        <span className="text-white">
          {n.name}
          {n.role ? <span className="text-slate-500"> · {n.role}</span> : null}
        </span>
      ),
    },
    {
      id: 'status', label: t('col_status'), text: n => n.status || '',
      render: n => {
        const ready = (n.status || '').toLowerCase() === 'ready'
        return <span className={ready ? 'text-emerald-300' : 'text-red-300'}>{n.status || '—'}</span>
      },
    },
    {
      id: 'cpu', label: 'CPU', hint: t('ocp_dash_load_legend'),
      text: n => pct(n.cpu_pct), num: n => n.cpu_pct,
      render: n => <UsageBar value={n.cpu_pct} title={nodeTip('CPU', n.cpu_pct, n.cpu_cores, 'cores')} />,
    },
    {
      id: 'mem', label: 'Memory', hint: t('ocp_dash_load_legend'),
      text: n => pct(n.mem_pct), num: n => n.mem_pct,
      render: n => <UsageBar value={n.mem_pct} title={nodeTip('Memory', n.mem_pct, n.memory_gb, 'GB')} />,
    },
    {
      id: 'pods', label: 'Pod', text: n => String(n.pods_total), num: n => n.pods_total,
      render: n => <span>{n.pods_total}{n.pods_bad ? <span className="text-amber-300"> ({n.pods_bad})</span> : null}</span>,
    },
    {
      id: 'vms', label: 'VM', text: n => `${n.vms_running ?? 0}/${n.vms_total}`, num: n => n.vms_running ?? 0,
      render: n => <span>{n.vms_running ?? 0}/{n.vms_total}</span>,
    },
  ]

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

      <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-5 gap-2">
        {[
          ['Cluster', clusters.length, clusterNames || '—', false],
          ['Node', sum('node_count'), nrCount ? t('ocp_dash_nodes_nr', { n: nrCount }) : t('ocp_dash_all_ready'), nrCount > 0],
          ['Pod', sum('pod_count'), `${sum('pods_bad')} ${t('ocp_problem')}`, false],
          [t('ocp_dash_card_risk'), riskTotal, topRiskNames || t('ocp_dash_no_risks'), riskTotal > 0],
          ['VM', sum('vm_count'), `${vmRunning} ${t('hv_running')} · ${vmOff} ${t('power_off')}`, false],
        ].map(([label, val, sub, warn]) => (
          <div key={String(label)} className="rounded-xl border border-white/[0.06] bg-cyber-card p-3 min-w-0" title={String(sub)}>
            <div className="text-[10px] uppercase tracking-wide text-slate-500">{label}</div>
            <div className="text-xl font-bold text-white">{q.isLoading ? '…' : val}</div>
            <div className={`text-[11px] truncate mt-1 ${warn ? 'text-amber-300' : 'text-slate-400'}`}>{q.isLoading ? '' : sub}</div>
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

      {notReady.length > 0 && (
        <section className="rounded-xl border border-red-500/30 bg-red-500/5 p-3" data-testid="ocp-not-ready">
          <div className="flex items-center gap-2 mb-1.5">
            <AlertTriangle size={14} className="text-red-300" />
            <h2 className="text-sm font-semibold text-white">{t('ocp_dash_not_ready_title')} ({notReady.length})</h2>
          </div>
          <ul className="max-h-28 overflow-y-auto space-y-1">
            {notReady.map(n => (
              <li key={`${n.cluster}-${n.node}`} className="text-xs text-slate-300">
                <span className="text-white">{n.node}</span>
                <span className="text-slate-500"> · {n.cluster} · {n.status || '—'}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

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
            <section key={c.cluster_id} className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 space-y-3" data-testid={`ocp-cluster-${c.cluster_id}`}>
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

              <ColumnTable
                bare
                testId={`ocp-nodes-${c.cluster_id}`}
                rows={c.nodes}
                columns={nodeColumns()}
                rowKey={n => n.name}
                searchPlaceholder={t('ocp_dash_node_search')}
                empty={t('ocp_add_cluster_first')}
                hideSearch={c.nodes.length <= 6}
                maxHeightClass="max-h-80"
                rowClass={n => ((n.status || '').toLowerCase() === 'ready' ? '' : 'bg-red-500/5')}
              />
              <p className="text-[10px] text-slate-500">{t('ocp_dash_load_legend')}</p>

              {vmHere.length > 0 && (
                <div>
                  <div className="text-[11px] uppercase tracking-wide text-slate-500 mb-1">{t('ocp_dash_vm_ns')}</div>
                  <div className="flex flex-wrap gap-1.5 max-h-20 overflow-y-auto">
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

      <section className="rounded-xl border border-white/[0.06] bg-cyber-card p-4" data-testid="ocp-risk-section">
        <div className="flex items-center justify-between gap-2 mb-2">
          <h2 className="text-sm font-semibold text-white">{t('ocp_dash_risk_title')} ({riskTotal})</h2>
          <Link to="/openshift?section=riskler" className="text-[11px] text-rose-300 hover:text-rose-200 inline-flex items-center gap-1">
            {t('ocp_nav_risks')} <ChevronRight size={12} />
          </Link>
        </div>
        {risksQ.isLoading && <p className="text-sm text-slate-500">{t('loading')}</p>}
        {!risksQ.isLoading && risks.length === 0 && (
          <p className="text-sm text-slate-500">{t('ocp_dash_no_risks')}</p>
        )}
        {risks.length > 0 && (
          <>
            <ColumnTable
              bare
              testId="ocp-risks"
              rows={riskRows}
              columns={riskColumns}
              rowKey={r => r.id}
              searchPlaceholder={t('ocp_dash_risk_search')}
              empty={t('ocp_dash_no_match')}
              maxHeightClass="max-h-96"
              defaultSort={{ id: 'severity', dir: 'desc' }}
              onRowClick={r => setDetail(r)}
              rowTestId="ocp-risk-row"
              countLabel={shown => t('ocp_dash_risk_count', { shown, total: riskTotal })}
              toolbar={(
                <div className="flex items-center gap-1" role="group">
                  {(['all', 'critical', 'high', 'warning'] as const).map(s => {
                    const n = s === 'all' ? risks.length : sevCounts[s] || 0
                    if (s !== 'all' && n === 0) return null
                    const on = sevFilter === s
                    return (
                      <button
                        key={s}
                        type="button"
                        data-testid={`ocp-risk-filter-${s}`}
                        aria-pressed={on}
                        onClick={() => setSevFilter(s)}
                        className={`text-[11px] px-2 py-1 rounded-lg border ${on ? 'border-sky-500/50 text-sky-300 bg-sky-500/10' : 'border-white/[0.08] text-slate-400 hover:text-slate-200'}`}
                      >
                        {s === 'all' ? t('ocp_dash_sev_all') : sevLabel(s)} ({n})
                      </button>
                    )
                  })}
                </div>
              )}
            />
            <p className="text-[10px] text-slate-500 mt-2">
              {t('ocp_dash_risk_hint')}
              {riskTotal > risks.length ? ` ${t('ocp_dash_risk_more', { n: riskTotal - risks.length })}` : ''}
            </p>
          </>
        )}
      </section>

      {detail && (
        <OcpResourceDetailDrawer
          clusterId={detail.cluster_id}
          kind="pods"
          name={detail.name}
          namespace={detail.project}
          onClose={() => setDetail(null)}
          onOpenPod={(_ns, pName) => setDetail(d => (d ? { ...d, name: pName } : d))}
        />
      )}
    </div>
  )
}
