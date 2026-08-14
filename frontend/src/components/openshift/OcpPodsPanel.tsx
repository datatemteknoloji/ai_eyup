/** Pod & Log — genişleyen satır: durum, container, events, log. */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Stethoscope, RefreshCw, Search, ChevronRight, ChevronDown, FileText, X, RotateCcw,
} from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useAuth } from '../../auth/AuthContext'
import { useT } from '../../i18n/LocaleProvider'

export default function OcpPodsPanel({
  clusterId,
  project,
  onPickProject,
}: {
  clusterId: number
  project: string
  onPickProject?: () => void
}) {
  const t = useT()
  const { user } = useAuth()
  const canWrite = Boolean(user?.is_admin || user?.role === 'admin')
  const [q, setQ] = useState('')
  const [onlyBad, setOnlyBad] = useState(false)
  const [open, setOpen] = useState<string | null>(null)
  const [detail, setDetail] = useState<any>(null)
  const [logView, setLogView] = useState<{ name: string; text: string } | null>(null)
  const [acting, setActing] = useState<string | null>(null)

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['ocp-pods', clusterId, project],
    queryFn: async () => {
      const params = new URLSearchParams({ kind: 'pods', namespace: project })
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/resources?${params}`)
      if (!r.ok) throw new Error('pods')
      return r.json() as Promise<{ items: { name: string; namespace?: string; age?: string; info?: string }[] }>
    },
    enabled: !!clusterId && !!project,
  })

  const pods = (data?.items || []).map((p) => {
    const phase = (p.info || '').toLowerCase()
    const healthy = phase === 'running' || phase === 'succeeded'
    return { ...p, phase: p.info || '?', healthy }
  })

  const shown = pods.filter(
    (p) =>
      (!onlyBad || !p.healthy) &&
      (!q.trim() || p.name.toLowerCase().includes(q.toLowerCase())),
  )

  const toggle = async (p: any) => {
    if (open === p.name) {
      setOpen(null)
      setDetail(null)
      return
    }
    setOpen(p.name)
    setDetail(null)
    const r = await fetch(
      `${API_BASE_URL}/openshift/clusters/${clusterId}/pods/${encodeURIComponent(project)}/${encodeURIComponent(p.name)}`,
    )
    if (r.ok) setDetail(await r.json())
  }

  const loadLogs = async (p: any, container?: string) => {
    setLogView({ name: p.name, text: '…' })
    const params = new URLSearchParams({ tail: '400' })
    if (container) params.set('container', container)
    const r = await fetch(
      `${API_BASE_URL}/openshift/clusters/${clusterId}/pods/${encodeURIComponent(project)}/${encodeURIComponent(p.name)}/logs?${params}`,
    )
    const d = await r.json()
    setLogView({ name: p.name, text: d.logs || d.error || '—' })
  }

  const restartPod = async (p: any) => {
    if (!window.confirm(t('ocp_pod_delete_confirm', { name: p.name }))) return
    setActing(p.name)
    try {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/pod/delete`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ kind: 'pods', namespace: project, name: p.name }),
      })
      const d = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(d.detail || t('ocp_delete_failed'))
      setTimeout(() => refetch(), 1500)
    } catch (e: any) {
      window.alert(e.message || t('error_generic'))
    } finally {
      setActing(null)
    }
  }

  if (!project) {
    return (
      <div className="rounded-xl border border-amber-500/25 bg-amber-500/10 px-4 py-8 text-center text-sm text-amber-100/90">
        {t('ocp_need_project_pods')}
        {onPickProject && (
          <>
            {' '}· <button type="button" onClick={onPickProject} className="underline">{t('ocp_projects')}</button>
          </>
        )}
      </div>
    )
  }

  return (
    <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-5 space-y-4">
      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <Stethoscope size={16} className="text-emerald-400" />
          <h2 className="text-sm font-medium text-white">{t('ocp_nav_pod_log')}</h2>
          <span className="text-xs text-slate-500 font-mono">{project}</span>
          <span className="text-xs text-slate-600">{shown.length}/{pods.length}</span>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="text-xs px-2.5 py-1.5 rounded-lg border border-white/[0.08] text-slate-300 hover:bg-white/[0.04] inline-flex items-center gap-1.5"
        >
          <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} /> {t('refresh_action')}
        </button>
      </div>

      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[180px] max-w-xs">
          <Search size={14} className="absolute left-2.5 top-2.5 text-slate-500" />
          <input
            className="w-full rounded-lg border border-white/[0.08] bg-cyber-deep/60 pl-8 pr-3 py-2 text-sm text-slate-200"
            placeholder={t('ocp_search_pod')}
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        {pods.some((p) => !p.healthy) && (
          <button
            type="button"
            onClick={() => setOnlyBad(!onlyBad)}
            className={`text-[11px] px-2 py-1 rounded-lg border ${
              onlyBad
                ? 'border-amber-500/40 bg-amber-500/15 text-amber-300'
                : 'border-white/[0.08] text-amber-400/80'
            }`}
          >
            {t('ocp_n_bad', { n: pods.filter((p) => !p.healthy).length })}
          </button>
        )}
      </div>

      {isLoading && <div className="text-sm text-slate-500">{t('loading')}</div>}

      <div className="space-y-1.5 max-h-[32rem] overflow-y-auto pr-1">
        {shown.map((p) => (
          <div
            key={p.name}
            className={`rounded-lg border transition-colors ${
              p.healthy
                ? 'bg-cyber-deep/40 border-white/[0.05] hover:border-white/[0.1]'
                : 'bg-red-950/20 border-red-500/30'
            }`}
          >
            <div className="flex items-center gap-2.5 px-3 py-2.5">
              <button type="button" onClick={() => toggle(p)} className="text-slate-500 hover:text-slate-300 flex-shrink-0">
                {open === p.name ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
              </button>
              <span className={`w-2 h-2 rounded-full flex-shrink-0 ${p.healthy ? 'bg-emerald-400' : 'bg-red-400'}`} />
              <div className="min-w-0 flex-1">
                <p className="text-sm text-slate-100 font-mono truncate">{p.name}</p>
                <p className="text-[11px] text-slate-500">{p.phase} · {p.age || '—'}</p>
              </div>
              <button
                type="button"
                title="Log"
                onClick={() => loadLogs(p)}
                className="p-1.5 rounded-md text-slate-500 hover:text-cyan-300 hover:bg-cyan-500/10"
              >
                <FileText size={14} />
              </button>
              {canWrite && (
                <button
                  type="button"
                  title={t('ocp_pod_restart_title')}
                  disabled={acting === p.name}
                  onClick={() => restartPod(p)}
                  className="p-1.5 rounded-md text-slate-500 hover:text-amber-300 hover:bg-amber-500/10 disabled:opacity-40"
                >
                  <RotateCcw size={14} />
                </button>
              )}
            </div>

            {open === p.name && (
              <div className="border-t border-white/[0.06] px-3 py-3 space-y-3 text-xs">
                {!detail && <div className="text-slate-500">{t('ocp_detail_loading')}</div>}
                {detail && (
                  <>
                    <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
                      {[
                        ['Phase', detail.phase],
                        ['Node', detail.node],
                        ['IP', detail.pod_ip],
                        ['Age', detail.age],
                      ].map(([l, v]) => (
                        <div key={l} className="rounded-lg bg-cyber-deep/60 border border-white/[0.04] px-2 py-1.5">
                          <div className="text-slate-500">{l}</div>
                          <div className="text-slate-200 truncate">{v || '—'}</div>
                        </div>
                      ))}
                    </div>
                    <div>
                      <div className="text-[11px] uppercase text-slate-500 mb-1">Containers</div>
                      <div className="space-y-1">
                        {(detail.containers || []).map((c: any) => (
                          <div key={c.name} className="flex items-center gap-2 rounded-lg border border-white/[0.05] px-2 py-1.5">
                            <span className="text-slate-200 font-mono">{c.name}</span>
                            <span className={c.ready ? 'text-emerald-400' : 'text-amber-400'}>{c.state}{c.reason ? ` (${c.reason})` : ''}</span>
                            <span className="text-slate-600 ml-auto">rst {c.restart_count}</span>
                            <button type="button" className="text-cyan-400 hover:underline" onClick={() => loadLogs(p, c.name)}>
                              log
                            </button>
                          </div>
                        ))}
                      </div>
                    </div>
                    {(detail.events || []).length > 0 && (
                      <div>
                        <div className="text-[11px] uppercase text-slate-500 mb-1">Events</div>
                        <div className="max-h-36 overflow-y-auto space-y-1">
                          {detail.events.map((e: any, i: number) => (
                            <div key={i} className="text-[11px] text-slate-400 border-b border-white/[0.04] py-1">
                              <span className={e.type === 'Warning' ? 'text-amber-400' : 'text-slate-500'}>{e.reason}</span>
                              {' — '}{e.message}
                            </div>
                          ))}
                        </div>
                      </div>
                    )}
                  </>
                )}
              </div>
            )}
          </div>
        ))}
        {!isLoading && shown.length === 0 && (
          <div className="text-sm text-slate-500 py-8 text-center">{t('ocp_no_pods')}</div>
        )}
      </div>

      {logView && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 p-4" onClick={() => setLogView(null)}>
          <div
            className="w-full max-w-4xl max-h-[80vh] flex flex-col rounded-xl border border-white/[0.1] bg-cyber-deep shadow-xl"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-4 py-3 border-b border-white/[0.06]">
              <div className="text-sm text-white font-mono truncate">{logView.name} · {t('ocp_logs')}</div>
              <button type="button" onClick={() => setLogView(null)} className="p-1.5 text-slate-400 hover:bg-white/[0.06] rounded-lg">
                <X size={16} />
              </button>
            </div>
            <pre className="flex-1 overflow-auto p-4 text-[10px] font-mono text-cyan-100/90 whitespace-pre-wrap">
              {logView.text}
            </pre>
          </div>
        </div>
      )}
    </div>
  )
}
