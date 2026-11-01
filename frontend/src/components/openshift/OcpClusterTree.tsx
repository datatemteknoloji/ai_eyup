import type { CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'
import { ColumnTable } from '../ColumnTable'

interface OcpHierNode { name: string; role?: string | null; status?: string | null; cpu_pct?: number | null; mem_pct?: number | null; pods_total: number; pods_bad: number; vms_total: number }
interface OcpHierNs { name: string; display_name?: string | null; status?: string | null; system: boolean; pods_total: number; pods_bad: number; vms_total: number }
interface OcpHierCluster { cluster_id: number; name: string; version?: string | null; status?: string | null; node_count: number; nodes_not_ready: number; project_count: number; pod_count: number; pods_bad: number; vm_count: number; nodes: OcpHierNode[]; namespaces: OcpHierNs[] }

const pick = (on: boolean, accent: string): CSSProperties => ({
  background: on ? `${accent}14` : 'rgba(255,255,255,0.03)',
  border: `1px solid ${on ? accent : 'rgba(255,255,255,0.08)'}`,
})

/** Cluster kartı seçilince node ve namespace altta açılır; seçilen kartın pod'ları sıralanır ve aranır. */
export function OcpClusterTree({ lockTab }: { lockTab?: string }) {
  const t = useT()
  const [params, setParams] = useSearchParams()
  const clusterId = Number(params.get('cluster')) || null
  const nodeName = params.get('node')
  const nsName = params.get('ns')
  const setSel = (next: { cluster?: number | null; node?: string | null; ns?: string | null }) => {
    const p = new URLSearchParams(params)
    if (lockTab) p.set('tab', lockTab)
    const c = next.cluster === undefined ? clusterId : next.cluster
    const n = next.node === undefined ? nodeName : next.node
    const s = next.ns === undefined ? nsName : next.ns
    if (c) p.set('cluster', String(c)); else p.delete('cluster')
    if (n) p.set('node', n); else p.delete('node')
    if (s) p.set('ns', s); else p.delete('ns')
    p.delete('level'); p.delete('sel')
    setParams(p, { replace: true })
  }

  const q = useQuery<{ clusters: OcpHierCluster[] }>({
    queryKey: ['ocp-hierarchy'],
    staleTime: 60_000,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/hierarchy`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    },
  })
  const tree = q.data?.clusters ?? []
  const cluster = tree.find(c => c.cluster_id === clusterId) || null
  const leaf = nodeName ? 'node' : nsName ? 'ns' : null

  const podsQ = useQuery<any>({
    queryKey: ['ocp-hier-pods', cluster?.cluster_id, leaf, nodeName, nsName],
    enabled: !!cluster && !!leaf,
    queryFn: async () => {
      const qs = new URLSearchParams({ cluster_id: String(cluster!.cluster_id), kind: 'pod', page_size: '200' })
      if (nsName) qs.set('project', nsName)
      const r = await fetch(`${API_BASE_URL}/openshift/workloads?${qs}`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    },
  })
  const pods: any[] = ((podsQ.data?.workloads || []) as any[]).filter(w => !nodeName || w.node_name === nodeName)
  const userNs = (cluster?.namespaces || []).filter(n => !n.system)
  const systemNs = (cluster?.namespaces || []).filter(n => n.system)

  return (
    <div className="space-y-3" data-testid="ocp-hierarchy">
      {q.isLoading ? <p className="text-sm text-slate-500">{t('loading')}</p> : q.isError ? <p className="text-sm text-red-300">{t('dash_vm_error')}</p> : (
        <>
          <div className="grid grid-cols-2 lg:grid-cols-4 gap-2" data-testid="ocp-cluster-grid">
            {tree.map(c => {
              const on = clusterId === c.cluster_id
              return (
                <button key={c.cluster_id} type="button" data-testid="ocp-hier-cluster" aria-pressed={on}
                  onClick={() => setSel({ cluster: on ? null : c.cluster_id, node: null, ns: null })}
                  className="text-left rounded-lg p-2.5 min-w-0 hover:bg-white/[0.05]" style={pick(on, '#e11d48')}>
                  <span className="block text-xs font-semibold text-white truncate">{c.name}</span>
                  <span className="block text-[10px] text-slate-400 mt-1">
                    {t('dash_node_count', { n: c.node_count })} · {t('dash_pod_count', { n: c.pod_count })} · {t('dash_vm_count', { n: c.vm_count })}
                    {c.nodes_not_ready ? ` · ${c.nodes_not_ready} ${t('ocp_not_ready')}` : ''}
                  </span>
                </button>
              )
            })}
            {tree.length === 0 && <p className="text-sm text-slate-500">{t('ocp_add_cluster_first')}</p>}
          </div>

          {cluster && (
            <div className="rounded-lg p-3 space-y-3" data-testid="ocp-hier-detail" style={{ background: '#e11d480a', border: '1px solid #e11d4840' }}>
              <div>
                <h3 className="text-xs font-semibold text-slate-200 mb-2">{t('ocp_nodes_of', { name: cluster.name })}</h3>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
                  {cluster.nodes.map(n => {
                    const on = nodeName === n.name
                    return (
                      <button key={n.name} type="button" data-testid="ocp-hier-node" aria-pressed={on}
                        onClick={() => setSel({ node: on ? null : n.name, ns: null })}
                        className="text-left rounded-lg p-2.5 min-w-0 hover:bg-white/[0.05]" style={pick(on, '#22c55e')}>
                        <span className="block text-xs font-semibold text-white truncate">{n.name}</span>
                        <span className="block text-[10px] text-slate-400 mt-1">
                          {[n.role, n.cpu_pct == null ? null : `CPU ${Math.round(n.cpu_pct)}%`, t('dash_pod_count', { n: n.pods_total }), t('dash_vm_count', { n: n.vms_total })].filter(Boolean).join(' · ')}
                        </span>
                      </button>
                    )
                  })}
                </div>
              </div>
              <div>
                <h3 className="text-xs font-semibold text-slate-200 mb-2">{t('ocp_ns_of', { name: cluster.name })}</h3>
                <div className="grid grid-cols-2 lg:grid-cols-4 gap-2">
                  {userNs.map(n => {
                    const on = nsName === n.name
                    return (
                      <button key={n.name} type="button" data-testid="ocp-hier-ns" aria-pressed={on}
                        onClick={() => setSel({ ns: on ? null : n.name, node: null })}
                        className="text-left rounded-lg p-2.5 min-w-0 hover:bg-white/[0.05]" style={pick(on, '#38bdf8')}>
                        <span className="block text-xs font-semibold text-white truncate">{n.display_name || n.name}</span>
                        <span className="block text-[10px] text-slate-400 mt-1">
                          {t('dash_pod_count', { n: n.pods_total })}{n.pods_bad ? ` (${n.pods_bad} ${t('ocp_problem')})` : ''} · {t('dash_vm_count', { n: n.vms_total })}
                        </span>
                      </button>
                    )
                  })}
                </div>
                {systemNs.length > 0 && (
                  <details className="mt-2">
                    <summary className="text-xs text-slate-500 cursor-pointer">{t('ocp_system_ns', { n: systemNs.length })}</summary>
                    <div className="grid grid-cols-2 lg:grid-cols-4 gap-2 mt-2">
                      {systemNs.map(n => {
                        const on = nsName === n.name
                        return (
                          <button key={n.name} type="button" data-testid="ocp-hier-ns" aria-pressed={on}
                            onClick={() => setSel({ ns: on ? null : n.name, node: null })}
                            className="text-left rounded-lg p-2.5 min-w-0 hover:bg-white/[0.05]" style={pick(on, '#94a3b8')}>
                            <span className="block text-xs font-semibold text-white truncate">{n.name}</span>
                            <span className="block text-[10px] text-slate-400 mt-1">{t('dash_pod_count', { n: n.pods_total })}</span>
                          </button>
                        )
                      })}
                    </div>
                  </details>
                )}
              </div>
            </div>
          )}

          {cluster && leaf && (
            <ColumnTable
              testId="ocp-hier-pods"
              rows={pods}
              rowKey={(p: any) => p.id ?? `${p.project}/${p.name}`}
              searchPlaceholder={t('ocp_pod_search')}
              loading={podsQ.isLoading}
              error={podsQ.isError ? t('dash_vm_error') : null}
              empty={pods.length ? t('ocp_pod_no_match') : t('ocp_no_pods')}
              columns={[
                { id: 'name', label: 'Pod', text: (p: any) => p.name || '', render: (p: any) => <span className="text-white">{p.name}</span> },
                { id: 'ns', label: 'Namespace', text: (p: any) => p.project || '' },
                { id: 'node', label: 'Node', text: (p: any) => p.node_name || '' },
                { id: 'state', label: t('col_status'), text: (p: any) => p.status || '' },
              ]}
            />
          )}
        </>
      )}
    </div>
  )
}
