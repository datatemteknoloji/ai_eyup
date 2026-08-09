/**
 * OpenShift AIOps — Analiz: Linux RCA/Baseline yerine OCP odaklı görünüm.
 * Mevcut envanter/API'yi kullanır (overview, operators-health, risks, health-board).
 */
import { useMemo, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Boxes, Activity, AlertTriangle, HardDrive, RefreshCw } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { PLATFORM_AIOPS_LABEL } from '../config/platformAiops'
import { PageHeader, Tabs } from '../components/aiops/ui'

type TabId = 'cluster' | 'operators' | 'risks'

function normalizeTab(raw: string | null): TabId {
  if (raw === 'operators' || raw === 'rca') return 'operators'
  if (raw === 'risks' || raw === 'baseline') return 'risks'
  return 'cluster'
}

function tone(status?: string) {
  const s = (status || '').toLowerCase()
  if (['healthy', 'ready', 'running', 'online'].includes(s)) return 'text-emerald-400'
  if (['warning', 'progressing', 'pending'].includes(s)) return 'text-amber-400'
  if (['critical', 'degraded', 'error', 'crashloopbackoff'].includes(s)) return 'text-red-400'
  return 'text-slate-400'
}

export default function OpenShiftAnalysisHub() {
  const [searchParams, setSearchParams] = useSearchParams()
  const tab = normalizeTab(searchParams.get('tab'))
  const setTab = (id: string) => setSearchParams({ tab: id }, { replace: true })
  const [selectedCluster, setSelectedCluster] = useState<number | null>(null)

  const { data: clusters = [] } = useQuery({
    queryKey: ['openshift-clusters'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters`)
      if (!r.ok) return []
      return (await r.json()).clusters || []
    },
  })

  const clusterId = selectedCluster ?? clusters[0]?.id

  const { data: healthBoard, refetch: refetchBoard, isFetching: boardLoading } = useQuery({
    queryKey: ['openshift-health-board'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/health-board`)
      if (!r.ok) throw new Error('health')
      return r.json()
    },
    refetchInterval: 45_000,
  })

  const { data: overview, isFetching: ovLoading } = useQuery({
    queryKey: ['openshift-overview-analysis', clusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/overview`)
      if (!r.ok) throw new Error('overview')
      return r.json()
    },
    enabled: !!clusterId && tab === 'cluster',
  })

  const { data: opHealth, isFetching: opLoading } = useQuery({
    queryKey: ['openshift-op-health-analysis', clusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/operators-health`)
      if (!r.ok) throw new Error('operators')
      return r.json()
    },
    enabled: !!clusterId && (tab === 'operators' || tab === 'cluster'),
  })

  const { data: risksData, isFetching: riskLoading } = useQuery({
    queryKey: ['openshift-risks-analysis', clusterId],
    queryFn: async () => {
      const params = clusterId ? `?cluster_id=${clusterId}&limit=100` : '?limit=100'
      const r = await fetch(`${API_BASE_URL}/openshift/risks${params}`)
      if (!r.ok) return { risks: [], total: 0 }
      return r.json()
    },
    enabled: tab === 'risks',
    refetchInterval: 30_000,
  })

  const boardCluster = useMemo(
    () => (healthBoard?.clusters || []).find((c: any) => c.id === clusterId) || (healthBoard?.clusters || [])[0],
    [healthBoard, clusterId],
  )

  const loading = boardLoading || ovLoading || opLoading || riskLoading

  return (
    <div className="space-y-4 animate-fade-in">
      <div className="mb-1 px-4 py-2 rounded-xl bg-slate-800/80 border border-slate-700/60 text-sm text-slate-300">
        <span className="text-slate-500">Platform:</span>{' '}
        <span className="font-medium text-white">{PLATFORM_AIOPS_LABEL.openshift}</span>
      </div>

      <PageHeader
        title="Küme Analizi"
        subtitle="Operator sağlığı, kapasite ve risk pod’ları — OpenShift’e özel"
        actions={(
          <button
            type="button"
            onClick={() => refetchBoard()}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-slate-300 border border-white/[0.08] hover:bg-white/[0.04]"
          >
            <RefreshCw size={12} className={loading ? 'animate-spin' : ''} /> Yenile
          </button>
        )}
      />

      {clusters.length > 1 && (
        <select
          value={clusterId || ''}
          onChange={e => setSelectedCluster(Number(e.target.value))}
          className="bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white max-w-xs"
        >
          {clusters.map((c: any) => (
            <option key={c.id} value={c.id}>{c.name}</option>
          ))}
        </select>
      )}

      {!clusterId && (
        <div className="text-center py-12 text-slate-500 text-sm">
          <Boxes size={28} className="mx-auto mb-2 opacity-40" />
          Cluster yok — önce <Link to="/openshift" className="text-rose-300 hover:underline">Envanter</Link>’e ekleyin.
        </div>
      )}

      {clusterId && (
        <>
          <Tabs
            active={tab}
            onChange={setTab}
            tabs={[
              { id: 'cluster', label: 'Kapasite / Özet' },
              { id: 'operators', label: 'Operator / MCP' },
              { id: 'risks', label: `Risk Pod’lar${risksData?.total ? ` (${risksData.total})` : ''}` },
            ]}
          />

          {tab === 'cluster' && (
            <div className="space-y-4">
              {boardCluster && (
                <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
                  <div className="flex flex-wrap items-center gap-2 mb-3">
                    <Activity size={16} className="text-rose-400" />
                    <span className="text-white font-medium">{boardCluster.name}</span>
                    <span className={`text-xs uppercase ${tone(boardCluster.health)}`}>{boardCluster.health}</span>
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                    {[
                      ['Node ready', `${boardCluster.nodes_ready}/${boardCluster.node_count}`],
                      ['Proje', boardCluster.project_count],
                      ['Pod', boardCluster.pod_count],
                      ['Risk', boardCluster.risk_pod_count],
                    ].map(([l, v]) => (
                      <div key={String(l)} className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
                        <div className="text-slate-500">{l}</div>
                        <div className="text-white text-lg font-semibold">{v}</div>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {overview && (
                <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 space-y-3">
                  <div className="text-sm text-white font-medium flex items-center gap-2">
                    <HardDrive size={14} className="text-slate-400" />
                    Canlı kapasite · {overview.version || '—'}
                  </div>
                  <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
                    <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
                      <div className="text-slate-500">CPU kullanım / kapasite</div>
                      <div className="text-white">{overview.capacity?.cpu_used_cores ?? '—'} / {overview.capacity?.cpu_cores}</div>
                    </div>
                    <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
                      <div className="text-slate-500">Mem kullanım / kapasite</div>
                      <div className="text-white">{overview.capacity?.memory_used_gb ?? '—'} / {overview.capacity?.memory_gb} GB</div>
                    </div>
                    <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
                      <div className="text-slate-500">Pods running</div>
                      <div className="text-white">{overview.capacity?.pods_running} / {overview.capacity?.pods_total}</div>
                    </div>
                    <div className="rounded-lg bg-cyber-deep/60 border border-white/[0.05] px-3 py-2">
                      <div className="text-slate-500">KubeVirt VM</div>
                      <div className="text-white">{overview.kubevirt_vms ?? '—'}</div>
                    </div>
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    {(overview.operators || []).map((o: any) => (
                      <span
                        key={o.group}
                        className={`text-[10px] px-2 py-0.5 rounded-full border ${
                          o.installed ? 'border-emerald-500/30 text-emerald-300' : 'border-white/[0.08] text-slate-500'
                        }`}
                      >
                        {o.label.split('(')[0].trim()}
                      </span>
                    ))}
                  </div>
                  <div className="text-[11px] text-slate-500">
                    Detaylı envanter / topology için{' '}
                    <Link to="/openshift" className="text-rose-300 hover:underline">OpenShift Envanter</Link>
                  </div>
                </div>
              )}
            </div>
          )}

          {tab === 'operators' && opHealth && (
            <div className="space-y-3">
              <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
                <div className="flex items-center justify-between gap-2 mb-2">
                  <span className="text-white font-medium">ClusterOperator / MCP</span>
                  <span className={`text-xs uppercase ${tone(opHealth.overall)}`}>{opHealth.overall}</span>
                </div>
                <div className="text-xs text-slate-400 mb-3">
                  Sürüm {opHealth.version || '—'}
                  {opHealth.updating ? ` · güncelleniyor: ${opHealth.update_message || ''}` : ''}
                </div>
                {(opHealth.operators?.degraded || []).length === 0 && (opHealth.operators?.unavailable || []).length === 0 && (
                  <div className="text-sm text-emerald-400/90">Degraded / unavailable operator yok.</div>
                )}
                {(opHealth.operators?.degraded || []).map((d: any) => (
                  <div key={d.name} className="text-xs text-red-300 border-b border-white/[0.04] py-1.5">
                    <span className="font-medium">{d.name}</span>: {d.reason || d.message}
                  </div>
                ))}
                {(opHealth.operators?.unavailable || []).map((d: any) => (
                  <div key={`u-${d.name}`} className="text-xs text-amber-300 border-b border-white/[0.04] py-1.5">
                    Unavailable · {d.name}: {d.reason || d.message}
                  </div>
                ))}
              </div>
              {(opHealth.machine_config_pools || []).length > 0 && (
                <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
                  <div className="text-sm text-white mb-2">MachineConfigPool</div>
                  <div className="flex flex-wrap gap-2">
                    {opHealth.machine_config_pools.map((m: any) => (
                      <span
                        key={m.name}
                        className={`text-[11px] px-2.5 py-1.5 rounded-lg border ${
                          m.degraded ? 'border-red-500/40 text-red-300' : m.updating ? 'border-amber-500/40 text-amber-300' : 'border-white/[0.08] text-slate-300'
                        }`}
                      >
                        {m.name}: {m.ready_count}/{m.machine_count}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              {(opHealth.nodes_not_ready || []).length > 0 && (
                <div className="text-xs text-red-300">NotReady: {opHealth.nodes_not_ready.join(', ')}</div>
              )}
            </div>
          )}

          {tab === 'risks' && (
            <div className="space-y-2">
              {(risksData?.risks || []).length === 0 && (
                <div className="text-center py-10 text-slate-500 text-sm">Riskli pod yok.</div>
              )}
              {(risksData?.risks || []).map((w: any) => (
                <div
                  key={w.id}
                  className={`rounded-xl border px-4 py-3 flex flex-wrap items-center justify-between gap-2 ${
                    w.risk_severity === 'critical' ? 'border-red-500/40 bg-red-500/10' : 'border-amber-500/30 bg-amber-500/5'
                  }`}
                >
                  <div className="min-w-0 flex items-start gap-2">
                    <AlertTriangle size={14} className="text-amber-400 mt-0.5 shrink-0" />
                    <div>
                      <div className="text-white text-sm truncate">{w.project} / {w.name}</div>
                      <div className="text-xs text-slate-500">{w.node_name || '—'} · restart {w.restart_count}</div>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className={`text-xs font-medium ${tone(w.status)}`}>{w.status}</span>
                    <Link to="/openshift" className="text-xs text-rose-300 hover:underline">Envanter</Link>
                    <Link to="/openshift/events" className="text-xs text-slate-400 hover:text-slate-200">Events</Link>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}
    </div>
  )
}
