import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Database, Cloud, Server, Layers, FileUp, RefreshCw,
  AlertTriangle, CheckCircle2, Merge, ChevronRight, Boxes,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'

const SOURCE_ICONS: Record<string, React.ReactNode> = {
  ucmdb: <FileUp size={22} />,
  hypervisor: <Cloud size={22} />,
  physical: <Server size={22} />,
  exadata: <Layers size={22} />,
  openshift: <Boxes size={22} />,
}

export default function IntegrationsHub() {
  const t = useT()
  const qc = useQueryClient()

  const { data, isLoading, refetch } = useQuery({
    queryKey: ['integrations-summary'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/integrations/summary`)
      if (!r.ok) throw new Error('summary failed')
      return r.json()
    },
    refetchInterval: 60_000,
  })

  const { data: dupData } = useQuery({
    queryKey: ['integrations-duplicates'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/integrations/duplicates`)
      if (!r.ok) return { groups: [] }
      return r.json()
    },
  })

  const dedupMut = useMutation({
    mutationFn: async (dryRun: boolean) => {
      const r = await fetch(`${API_BASE_URL}/integrations/deduplicate?dry_run=${dryRun}`, { method: 'POST' })
      if (!r.ok) throw new Error('dedup failed')
      return r.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['integrations-summary'] })
      qc.invalidateQueries({ queryKey: ['integrations-duplicates'] })
    },
  })

  const inv = data?.inventory
  const sources = data?.sources ?? []
  const dupGroups = dupData?.groups ?? []

  return (
    <div className="p-6 space-y-6 max-w-6xl">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-2xl font-bold text-white">{t('int_title')}</h1>
          <p className="text-slate-400 text-sm mt-1">{t('int_sub')}</p>
        </div>
        <button
          onClick={() => refetch()}
          className="flex items-center gap-2 text-xs px-3 py-2 rounded-lg border border-slate-700 text-slate-400 hover:text-white"
        >
          <RefreshCw size={14} /> {t('refresh_action')}
        </button>
      </div>

      {/* Özet KPI */}
      {!isLoading && inv && (
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
          {[
            { label: t('int_kpi_total'), value: inv.total_servers, color: 'text-blue-400' },
            { label: t('int_kpi_vm'), value: inv.virtual_machines, color: 'text-sky-400' },
            { label: t('int_kpi_phys'), value: inv.physical_hosts, color: 'text-green-400' },
            { label: t('int_kpi_dups'), value: inv.duplicate_groups, color: inv.duplicate_groups > 0 ? 'text-amber-400' : 'text-slate-500' },
          ].map(k => (
            <div key={k.label} className="bg-slate-800/50 border border-slate-700/50 rounded-xl p-4">
              <div className={`text-2xl font-bold ${k.color}`}>{k.value}</div>
              <div className="text-xs text-slate-500 mt-1">{k.label}</div>
            </div>
          ))}
        </div>
      )}

      {/* Kaynak kartları */}
      <div>
        <h2 className="text-sm font-semibold text-slate-300 mb-3">{t('int_sources')}</h2>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {sources.map((src: any) => (
            <Link
              key={src.id}
              to={src.path}
              className="group flex items-start gap-4 p-5 rounded-xl border border-slate-700/60 bg-slate-800/40 hover:border-blue-500/40 hover:bg-slate-800/70 transition-all"
            >
              <div className="w-11 h-11 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
                {SOURCE_ICONS[src.id] ?? <Database size={22} />}
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <span className="font-semibold text-white group-hover:text-blue-300">{src.name}</span>
                  <ChevronRight size={16} className="text-slate-600 group-hover:text-blue-400" />
                </div>
                <p className="text-xs text-slate-500 mt-1">{src.description}</p>
                <div className="flex gap-3 mt-2 text-xs">
                  <span className="text-slate-400">{t('int_records')} <strong className="text-white">{src.count ?? 0}</strong></span>
                  {src.vm_count != null && <span className="text-slate-400">VM: <strong className="text-white">{src.vm_count}</strong></span>}
                  {src.rack_count != null && <span className="text-slate-400">Rack: <strong className="text-white">{src.rack_count}</strong></span>}
                  {src.node_count != null && <span className="text-slate-400">Node: <strong className="text-white">{src.node_count}</strong></span>}
                  {src.project_count != null && <span className="text-slate-400">{t('int_project')} <strong className="text-white">{src.project_count}</strong></span>}
                </div>
              </div>
            </Link>
          ))}
        </div>
      </div>

      {/* Tekilleştirme */}
      <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl p-5">
        <div className="flex items-center gap-2 mb-3">
          <Merge size={18} className="text-amber-400" />
          <h2 className="text-sm font-semibold text-white">{t('int_dedup_title')}</h2>
        </div>
        <p className="text-xs text-slate-500 mb-4">{t('int_dedup_hint')}</p>

        {dupGroups.length === 0 ? (
          <div className="flex items-center gap-2 text-sm text-green-400">
            <CheckCircle2 size={16} /> {t('int_no_dups')}
          </div>
        ) : (
          <>
            <div className="flex items-center gap-2 text-sm text-amber-300 mb-3">
              <AlertTriangle size={16} />
              {t('int_dup_groups', { n: dupGroups.length, r: inv?.duplicate_records ?? 0 })}
            </div>
            <div className="space-y-2 max-h-48 overflow-y-auto mb-4">
              {dupGroups.slice(0, 8).map((g: any) => (
                <div key={`${g.match_type}-${g.match_key}`} className="text-xs px-3 py-2 rounded-lg bg-slate-900/60 border border-slate-700/40">
                  <span className="text-slate-400 uppercase">{g.match_type}:</span>{' '}
                  <span className="text-white font-mono">{g.match_key}</span>
                  <span className="text-slate-500 ml-2">{t('int_n_records', { n: g.count })}</span>
                  <div className="text-slate-500 mt-1 truncate">
                    {g.servers.map((s: any) => s.name).join(' · ')}
                  </div>
                </div>
              ))}
            </div>
            <div className="flex gap-2 flex-wrap">
              <button
                onClick={() => dedupMut.mutate(true)}
                disabled={dedupMut.isPending}
                className="text-xs px-4 py-2 rounded-lg border border-slate-600 text-slate-300 hover:bg-slate-700 disabled:opacity-50"
              >
                {t('int_preview_dry')}
              </button>
              <button
                onClick={() => {
                  if (window.confirm(t('int_dedup_confirm', { n: dupGroups.length }))) {
                    dedupMut.mutate(false)
                  }
                }}
                disabled={dedupMut.isPending}
                className="text-xs px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 text-white disabled:opacity-50"
              >
                {t('int_dedup')}
              </button>
            </div>
            {dedupMut.data && (
              <pre className="mt-3 text-xs text-slate-400 bg-slate-900/80 p-3 rounded-lg overflow-x-auto">
                {JSON.stringify(dedupMut.data, null, 2)}
              </pre>
            )}
          </>
        )}
      </div>
    </div>
  )
}
