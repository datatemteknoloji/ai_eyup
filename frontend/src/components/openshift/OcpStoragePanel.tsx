/** Depolama & ağ — Atlas OpenShiftStorage tarzı. */
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { HardDrive, Network, RefreshCw, Database, ChevronRight, ChevronDown } from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'

const PHASE: Record<string, string> = {
  Bound: 'text-emerald-300 bg-emerald-500/10 border-emerald-500/30',
  Available: 'text-sky-300 bg-sky-500/10 border-sky-500/30',
  Pending: 'text-amber-300 bg-amber-500/10 border-amber-500/30',
  Released: 'text-slate-400 bg-white/[0.04] border-white/[0.08]',
  Failed: 'text-red-300 bg-red-500/10 border-red-500/30',
  Lost: 'text-red-300 bg-red-500/10 border-red-500/30',
}

export default function OcpStoragePanel({ clusterId }: { clusterId: number }) {
  const t = useT()
  const [openSc, setOpenSc] = useState<string | null>(null)

  const { data: st, isLoading, isFetching, refetch } = useQuery({
    queryKey: ['openshift-storage', clusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/storage`)
      if (!r.ok) throw new Error('storage')
      return r.json()
    },
    enabled: !!clusterId,
  })

  const { data: net } = useQuery({
    queryKey: ['openshift-network', clusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${clusterId}/network`)
      if (!r.ok) return null
      return r.json()
    },
    enabled: !!clusterId,
  })

  const badge = (phase: string) => (
    <span className={`text-[10px] px-1.5 py-0.5 rounded border flex-shrink-0 ${PHASE[phase] || 'text-slate-400 border-white/[0.08]'}`}>
      {phase || '—'}
    </span>
  )

  if (isLoading && !st) {
    return (
      <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-8 text-center text-slate-500 text-sm">
        {t('loading')}
      </div>
    )
  }

  if (!st) {
    return (
      <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-8 text-center text-slate-500 text-sm">
        {t('ocp_no_storage')}
      </div>
    )
  }

  const nads = net?.network_attachment_definitions

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button
          type="button"
          onClick={() => refetch()}
          className="text-xs px-2.5 py-1.5 rounded-lg border border-white/[0.08] text-slate-300 hover:bg-white/[0.04] inline-flex items-center gap-1.5"
        >
          <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} /> {t('refresh_action')}
        </button>
      </div>

      <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
        <h3 className="text-sm font-semibold text-slate-100 mb-2 flex items-center gap-2">
          <Database size={16} className="text-violet-400" /> {t('ocp_sc_list')}
          <span className="text-xs text-slate-500">({(st.storage_classes || []).length})</span>
        </h3>
        <div className="space-y-1">
          {(st.storage_classes || []).map((sc: any) => (
            <div key={sc.name} className="rounded-lg bg-cyber-deep/50">
              <button
                type="button"
                onClick={() => setOpenSc(openSc === sc.name ? null : sc.name)}
                className="w-full flex items-center gap-2 px-3 py-1.5 text-xs text-left"
              >
                {openSc === sc.name ? <ChevronDown size={14} className="text-slate-500" /> : <ChevronRight size={14} className="text-slate-500" />}
                <span className="text-slate-100 font-medium">{sc.name}</span>
                {sc.default && (
                  <span className="text-[9px] px-1.5 py-0.5 rounded bg-violet-500/15 text-violet-300">{t('ocp_sc_default')}</span>
                )}
                <span className="text-slate-500 ml-auto truncate">{sc.provisioner}</span>
              </button>
              {openSc === sc.name && (
                <div className="border-t border-white/[0.06] px-3 py-2 text-xs grid grid-cols-2 gap-x-6 gap-y-1 text-slate-400">
                  <span>{t('ocp_reclaim')}: <span className="text-slate-200">{sc.reclaim || '—'}</span></span>
                  <span>{t('ocp_binding')}: <span className="text-slate-200">{sc.binding || '—'}</span></span>
                </div>
              )}
            </div>
          ))}
        </div>
      </div>

      <div className="grid lg:grid-cols-2 gap-4">
        <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
          <h3 className="text-sm font-semibold text-slate-100 mb-2 flex items-center gap-2">
            <HardDrive size={16} className="text-sky-400" /> PVC
            <span className="text-xs text-slate-500">({(st.persistent_volume_claims || []).length})</span>
            {st.summary?.pvcs_pending > 0 && (
              <span className="text-[10px] text-amber-300">{t('ocp_pending_n', { n: st.summary.pvcs_pending })}</span>
            )}
          </h3>
          <div className="space-y-1 max-h-96 overflow-y-auto">
            {(st.persistent_volume_claims || []).map((p: any) => (
              <div key={`${p.namespace}/${p.name}`} className="rounded-lg bg-cyber-deep/50 px-3 py-1.5 text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-slate-100 font-mono truncate">{p.name}</span>
                  {badge(p.phase)}
                  <span className="text-slate-500 ml-auto flex-shrink-0">
                    {p.capacity_gb != null ? `${p.capacity_gb} GB` : '—'}
                  </span>
                </div>
                <div className="text-[10px] text-slate-600 mt-0.5 flex gap-2">
                  <span>{p.namespace}</span>
                  {p.storage_class && <span>· {p.storage_class}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
          <h3 className="text-sm font-semibold text-slate-100 mb-2 flex items-center gap-2">
            <HardDrive size={16} className="text-emerald-400" /> PersistentVolume
            <span className="text-xs text-slate-500">({(st.persistent_volumes || []).length})</span>
          </h3>
          <div className="space-y-1 max-h-96 overflow-y-auto">
            {(st.persistent_volumes || []).map((p: any) => (
              <div key={p.name} className="rounded-lg bg-cyber-deep/50 px-3 py-1.5 text-xs">
                <div className="flex items-center gap-2">
                  <span className="text-slate-100 font-mono truncate">{p.name}</span>
                  {badge(p.phase)}
                  <span className="text-slate-500 ml-auto flex-shrink-0">
                    {p.capacity_gb != null ? `${p.capacity_gb} GB` : '—'}
                  </span>
                </div>
                <div className="text-[10px] text-slate-600 mt-0.5">
                  {p.storage_class || '—'}{p.claim ? ` · ${t('ocp_claim', { name: p.claim })}` : ''}
                </div>
              </div>
            ))}
          </div>
        </div>
      </div>

      <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
        <h3 className="text-sm font-semibold text-slate-100 mb-2 flex items-center gap-2">
          <Network size={16} className="text-emerald-400" /> {t('ocp_multus_nads')}
        </h3>
        {nads == null ? (
          <p className="text-xs text-slate-600">{t('ocp_no_multus_perm')}</p>
        ) : nads.length === 0 ? (
          <p className="text-xs text-slate-600">{t('ocp_no_extra_nad')}</p>
        ) : (
          <div className="flex flex-wrap gap-1.5">
            {nads.map((n: any) => (
              <span key={n.name} className="text-[11px] px-2 py-0.5 rounded-lg border border-white/[0.08] text-slate-300">
                {n.name}
                {(n.namespaces || 0) > 1 && <span className="text-slate-600"> ×{n.namespaces}</span>}
              </span>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
