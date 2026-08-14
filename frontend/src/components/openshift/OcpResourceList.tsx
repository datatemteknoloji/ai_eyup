import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FileCode, RefreshCw, Search, X, Minus, Plus, RotateCcw } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useAuth } from '../../auth/AuthContext'
import { useT } from '../../i18n/LocaleProvider'

type Item = { name: string; namespace?: string; age?: string; info?: string }

const SCALABLE = ['deployments', 'statefulsets']
const RESTARTABLE = ['deployments', 'statefulsets', 'daemonsets']

/**
 * Kaynak listesi — proje bağlamı + YAML; Deployment/STS için ölçek ± ve restart.
 */
export default function OcpResourceList({
  clusterId,
  kind,
  namespace,
  title,
  namespaced = true,
  onPickProject,
}: {
  clusterId: number
  kind: string
  namespace?: string
  title: string
  namespaced?: boolean
  onPickProject?: () => void
}) {
  const t = useT()
  const { user } = useAuth()
  const canWrite = Boolean(user?.is_admin || user?.role === 'admin')
  const [q, setQ] = useState('')
  const [yamlView, setYamlView] = useState<{ name: string; text: string } | null>(null)
  const [acting, setActing] = useState<string | null>(null)

  const ns = namespaced ? (namespace || '') : ''
  const needsProject = namespaced && !ns

  const { data, isLoading, isFetching, refetch, error } = useQuery({
    queryKey: ['ocp-resources', clusterId, kind, ns],
    queryFn: async () => {
      const params = new URLSearchParams({ kind })
      if (ns) params.set('namespace', ns)
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/resources?${params}`)
      if (!r.ok) throw new Error((await r.json()).detail || t('ocp_list_fail'))
      return r.json() as Promise<{ items: Item[]; error?: string | null; total?: number }>
    },
    enabled: !!clusterId && !needsProject,
  })

  const items = (data?.items || []).filter(
    (it) =>
      !q.trim() ||
      it.name.toLowerCase().includes(q.toLowerCase()) ||
      (it.info || '').toLowerCase().includes(q.toLowerCase()),
  )

  const loadYaml = async (it: Item) => {
    setYamlView({ name: it.name, text: '…' })
    const params = new URLSearchParams({ kind, name: it.name })
    if (it.namespace || ns) params.set('namespace', it.namespace || ns)
    const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/resource-yaml?${params}`)
    const d = await r.json()
    setYamlView({ name: it.name, text: d.yaml || d.error || '—' })
  }

  const parseReplicas = (info?: string) => {
    // "1/2" → desired 2
    const m = (info || '').match(/(\d+)\s*\/\s*(\d+)/)
    return m ? parseInt(m[2], 10) : 0
  }

  const scale = async (it: Item, delta: number) => {
    const cur = parseReplicas(it.info)
    const target = Math.max(0, cur + delta)
    setActing(it.name)
    try {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/workload/scale`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          kind,
          namespace: it.namespace || ns,
          name: it.name,
          replicas: target,
        }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : t('ocp_scale_fail'))
      setTimeout(() => refetch(), 1200)
    } catch (e: any) {
      window.alert(e.message || t('error_generic'))
    } finally {
      setActing(null)
    }
  }

  const restart = async (it: Item) => {
    if (!window.confirm(t('ocp_restart_confirm', { name: it.name }))) return
    setActing(it.name)
    try {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/workload/restart`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind, namespace: it.namespace || ns, name: it.name }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(typeof d.detail === 'string' ? d.detail : t('failed'))
      setTimeout(() => refetch(), 1500)
    } catch (e: any) {
      window.alert(e.message || t('error_generic'))
    } finally {
      setActing(null)
    }
  }

  return (
    <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-5 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <FileCode size={16} className="text-violet-400" />
          <h2 className="text-sm font-medium text-white">{title}</h2>
          {!needsProject && (
            <span className="text-xs text-slate-500">
              {ns ? <span className="font-mono text-slate-400">{ns}</span> : null}
              {' · '}{t('ocp_n_records', { n: data?.total ?? items.length })}
            </span>
          )}
        </div>
        <button
          type="button"
          disabled={needsProject}
          onClick={() => refetch()}
          className="text-xs px-2.5 py-1.5 rounded-lg border border-white/[0.08] text-slate-300 hover:bg-white/[0.04] inline-flex items-center gap-1.5 disabled:opacity-40"
        >
          <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} /> {t('refresh_action')}
        </button>
      </div>

      {needsProject ? (
        <div className="rounded-lg border border-amber-500/25 bg-amber-500/10 px-4 py-8 text-center space-y-2">
          <p className="text-sm text-amber-100/90">
            {t('ocp_needs_ns')}
          </p>
          <p className="text-xs text-amber-200/70">
            {t('ocp_pick_or')}
            {onPickProject && (
              <>
                {' '}{t('ocp_or')}{' '}
                <button type="button" onClick={onPickProject} className="underline font-medium">
                  {t('ocp_projects')}
                </button>
              </>
            )}
            .
          </p>
        </div>
      ) : (
        <>
          <div className="relative max-w-sm">
            <Search size={14} className="absolute left-2.5 top-2.5 text-slate-500" />
            <input
              className="w-full rounded-lg border border-white/[0.08] bg-cyber-deep/60 pl-8 pr-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-rose-500/40"
              placeholder={t('ocp_search_name')}
              value={q}
              onChange={(e) => setQ(e.target.value)}
            />
          </div>

          {isLoading && <div className="text-sm text-slate-500">{t('loading')}</div>}
          {error && (
            <div className="text-sm text-red-400">
              {error instanceof Error ? error.message : t('error_generic')}
            </div>
          )}
          {data?.error && <div className="text-sm text-amber-400">{data.error}</div>}

          {!isLoading && items.length === 0 && !data?.error && (
            <div className="text-sm text-slate-500 py-6 text-center">{t('ocp_empty_ns')}</div>
          )}

          {items.length > 0 && (
            <div className="space-y-1.5 max-h-[30rem] overflow-y-auto pr-1">
              {items.map((it) => (
                <div
                  key={`${it.namespace}/${it.name}`}
                  className="group flex items-center gap-3 rounded-lg border border-white/[0.05] bg-cyber-deep/40 hover:border-white/[0.1] px-3 py-2.5"
                >
                  <div className="min-w-0 flex-1">
                    <p className="text-sm text-slate-100 font-mono truncate">{it.name}</p>
                    {it.info && <p className="text-[11px] text-slate-500 mt-0.5 truncate">{it.info}</p>}
                  </div>
                  <span className="text-[11px] text-slate-600 flex-shrink-0 tabular-nums">{it.age}</span>
                  <div className="flex items-center gap-0.5 flex-shrink-0">
                    {canWrite && RESTARTABLE.includes(kind) && (
                      acting === it.name ? (
                        <RefreshCw size={14} className="animate-spin text-slate-500 mx-1" />
                      ) : (
                        <>
                          {SCALABLE.includes(kind) && (
                            <>
                              <button type="button" title={t('ocp_scale_minus')} onClick={() => scale(it, -1)}
                                className="p-1.5 rounded-md text-slate-500 hover:text-slate-100 hover:bg-white/[0.06]">
                                <Minus size={14} />
                              </button>
                              <button type="button" title={t('ocp_scale_plus')} onClick={() => scale(it, +1)}
                                className="p-1.5 rounded-md text-slate-500 hover:text-slate-100 hover:bg-white/[0.06]">
                                <Plus size={14} />
                              </button>
                            </>
                          )}
                          <button type="button" title={t('restart')} onClick={() => restart(it)}
                            className="p-1.5 rounded-md text-slate-500 hover:text-amber-300 hover:bg-amber-500/10">
                            <RotateCcw size={14} />
                          </button>
                        </>
                      )
                    )}
                    <button type="button" title="YAML" onClick={() => loadYaml(it)}
                      className="p-1.5 rounded-md text-slate-500 hover:text-violet-300 hover:bg-violet-500/10">
                      <FileCode size={14} />
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </>
      )}

      {yamlView && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setYamlView(null)}>
          <div
            className="w-full max-w-3xl max-h-[80vh] flex flex-col rounded-xl border border-white/[0.1] bg-cyber-deep shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
              <div className="text-sm text-white font-medium truncate">{yamlView.name}</div>
              <button type="button" onClick={() => setYamlView(null)} className="p-1.5 rounded-lg text-slate-400 hover:bg-white/[0.06]">
                <X size={16} />
              </button>
            </div>
            <pre className="flex-1 overflow-auto p-4 text-[11px] font-mono text-cyan-100/90 whitespace-pre">
              {yamlView.text}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}
