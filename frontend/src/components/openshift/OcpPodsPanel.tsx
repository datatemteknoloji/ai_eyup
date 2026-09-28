/** Pod & Log — satıra tıklayınca Atlas tarzı sağ çekmece (Genel/Log/Terminal/…). */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Stethoscope, RefreshCw, Search, FileText, RotateCcw, Eye,
} from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useAuth } from '../../auth/AuthContext'
import { useT } from '../../i18n/LocaleProvider'
import OcpResourceDetailDrawer from './OcpResourceDetailDrawer'

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
  const [acting, setActing] = useState<string | null>(null)
  const [detailPod, setDetailPod] = useState<string | null>(null)

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

  const restartPod = async (p: { name: string }) => {
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
            role="button"
            tabIndex={0}
            onClick={() => setDetailPod(p.name)}
            onKeyDown={(e) => { if (e.key === 'Enter') setDetailPod(p.name) }}
            className={`flex items-center gap-2.5 px-3 py-2.5 rounded-lg border cursor-pointer transition-colors ${
              p.healthy
                ? 'bg-cyber-deep/40 border-white/[0.05] hover:border-rose-500/30'
                : 'bg-red-950/20 border-red-500/30 hover:border-red-400/50'
            }`}
          >
            <span className={`w-2 h-2 rounded-full flex-shrink-0 ${p.healthy ? 'bg-emerald-400' : 'bg-red-400'}`} />
            <div className="min-w-0 flex-1">
              <p className="text-sm text-slate-100 font-mono truncate">{p.name}</p>
              <p className="text-[11px] text-slate-500">{p.phase} · {p.age || '—'}</p>
            </div>
            <div className="flex items-center gap-0.5" onClick={(e) => e.stopPropagation()}>
              <button
                type="button"
                title={t('ocp_open_detail')}
                onClick={() => setDetailPod(p.name)}
                className="p-1.5 rounded-md text-slate-500 hover:text-rose-300 hover:bg-rose-500/10"
              >
                <Eye size={14} />
              </button>
              <button
                type="button"
                title={t('ocp_tab_logs')}
                onClick={() => setDetailPod(p.name)}
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
          </div>
        ))}
        {!isLoading && shown.length === 0 && (
          <div className="text-sm text-slate-500 py-8 text-center">{t('ocp_no_pods')}</div>
        )}
      </div>

      {detailPod && (
        <OcpResourceDetailDrawer
          clusterId={clusterId}
          kind="pods"
          name={detailPod}
          namespace={project}
          onClose={() => setDetailPod(null)}
          onOpenPod={(_ns, pName) => setDetailPod(pName)}
        />
      )}
    </div>
  )
}
