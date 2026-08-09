import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { FolderOpen, RefreshCw, Search, ArrowRight } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import type { OcpProject } from './ocpTypes'

export default function OcpProjectsPanel({
  clusterId,
  selected,
  onSelect,
}: {
  clusterId: number
  selected: string
  onSelect: (ns: string) => void
}) {
  const [q, setQ] = useState('')
  const [showSystem, setShowSystem] = useState(false)

  const { data, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['ocp-explorer-projects', clusterId],
    queryFn: async () => {
      const params = new URLSearchParams({
        cluster_id: String(clusterId),
        include_system: 'true',
        page: '1',
        page_size: '200',
      })
      const r = await fetch(`${API_BASE_URL}/openshift/projects?${params}`)
      if (!r.ok) return { projects: [] as OcpProject[], total: 0 }
      return r.json() as Promise<{ projects: OcpProject[]; total: number }>
    },
    enabled: !!clusterId,
  })

  const projects = data?.projects || []
  const userCount = projects.filter((p) => !p.is_system).length
  const shown = useMemo(() => {
    const qq = q.trim().toLowerCase()
    return projects.filter((p) => {
      if (!showSystem && p.is_system) return false
      if (!qq) return true
      return (
        p.name.toLowerCase().includes(qq) ||
        (p.display_name || '').toLowerCase().includes(qq)
      )
    })
  }, [projects, q, showSystem])

  return (
    <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-5 space-y-4">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <div className="flex items-center gap-2">
          <FolderOpen size={16} className="text-amber-400" />
          <h2 className="text-sm font-medium text-white">Projeler</h2>
          <span className="text-xs text-slate-500">
            {projects.length ? `${userCount} kullanıcı · ${projects.length} toplam` : ''}
          </span>
        </div>
        <button
          type="button"
          onClick={() => refetch()}
          className="text-xs px-2.5 py-1.5 rounded-lg border border-white/[0.08] text-slate-300 hover:bg-white/[0.04] inline-flex items-center gap-1.5"
        >
          <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} /> Yenile
        </button>
      </div>

      <div className="flex items-center gap-3 flex-wrap">
        <div className="relative flex-1 min-w-[220px] max-w-sm">
          <Search size={14} className="absolute left-2.5 top-2.5 text-slate-500" />
          <input
            className="w-full rounded-lg border border-white/[0.08] bg-cyber-deep/60 pl-8 pr-3 py-2 text-sm text-slate-200 placeholder:text-slate-600 focus:outline-none focus:border-rose-500/40"
            placeholder="proje ara…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
        </div>
        <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
          <input
            type="checkbox"
            checked={showSystem}
            onChange={(e) => setShowSystem(e.target.checked)}
            className="rounded border-white/20"
          />
          Sistem projelerini göster ({projects.length - userCount})
        </label>
      </div>

      {isLoading ? (
        <div className="text-sm text-slate-500 py-8 text-center">Yükleniyor…</div>
      ) : shown.length === 0 ? (
        <div className="text-sm text-slate-500 py-8 text-center">
          {q ? 'Eşleşen proje yok' : 'Proje bulunamadı — Entegrasyonlar’dan sync deneyin.'}
        </div>
      ) : (
        <div className="grid sm:grid-cols-2 lg:grid-cols-3 gap-2.5">
          {shown.map((p) => {
            const title = p.display_name || p.name
            const active = selected === p.name
            return (
              <button
                key={p.name}
                type="button"
                onClick={() => onSelect(p.name)}
                className={`text-left rounded-lg border p-3 transition-all group ${
                  active
                    ? 'border-amber-500/50 bg-amber-500/10'
                    : 'border-white/[0.06] bg-cyber-deep/40 hover:border-white/[0.12]'
                }`}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${
                      (p.status || '').toLowerCase() === 'active' ? 'bg-emerald-400' : 'bg-amber-400'
                    }`}
                  />
                  <span className="text-sm text-slate-100 truncate font-medium">{title}</span>
                  {p.is_system && (
                    <span className="text-[9px] px-1.5 py-0.5 rounded bg-white/[0.06] text-slate-500 flex-shrink-0">
                      sistem
                    </span>
                  )}
                  <ArrowRight
                    size={14}
                    className="text-slate-600 ml-auto flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                  />
                </div>
                {title !== p.name && (
                  <p className="text-[11px] text-slate-600 font-mono truncate mt-0.5">{p.name}</p>
                )}
                <p className="text-[10px] text-slate-600 mt-1.5">
                  {p.status || '—'}
                  {p.pod_count != null ? ` · ${p.pod_count} pod` : ''}
                  {p.deployment_count != null ? ` · ${p.deployment_count} deploy` : ''}
                  {p.requester ? ` · ${p.requester}` : ''}
                </p>
              </button>
            )
          })}
        </div>
      )}
    </div>
  )
}
