/**
 * OpenShift Virtual Machines — Linux sunucu listesi tarzı, yalnız KubeVirt VM.
 * Explorer (pod/deploy/…) buraya gömülmez; aksiyonlar satır içi.
 */
import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Boxes, MonitorPlay, RefreshCw, Search } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import OcpVmsPanel from '../components/openshift/OcpVmsPanel'
import { useT } from '../i18n/LocaleProvider'

const LS_CLUSTER = 'ainew.ocp.vms.clusterId'

type OcpCluster = { id: number; name: string; status?: string; version?: string }

export default function OpenShiftVmsPage() {
  const t = useT()
  const [clusterId, setClusterId] = useState<number | null>(() => {
    try {
      const v = localStorage.getItem(LS_CLUSTER)
      return v ? Number(v) : null
    } catch {
      return null
    }
  })
  const [q, setQ] = useState('')
  const [status, setStatus] = useState<'all' | 'running' | 'stopped'>('all')

  const { data: clusters = [], isLoading } = useQuery<OcpCluster[]>({
    queryKey: ['openshift-clusters'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters`)
      if (!r.ok) return []
      const body = await r.json()
      return Array.isArray(body?.clusters) ? body.clusters : []
    },
    refetchInterval: 60_000,
  })

  useEffect(() => {
    if (!clusters.length) {
      setClusterId(null)
      return
    }
    if (!clusterId || !clusters.some((c) => c.id === clusterId)) {
      const next = clusters[0].id
      setClusterId(next)
      try { localStorage.setItem(LS_CLUSTER, String(next)) } catch { /* ignore */ }
    }
  }, [clusters, clusterId])

  const pickCluster = (id: number) => {
    setClusterId(id)
    try { localStorage.setItem(LS_CLUSTER, String(id)) } catch { /* ignore */ }
  }

  const current = clusters.find((c) => c.id === clusterId)

  return (
    <div className="flex flex-col h-full min-h-0">
      <div className="px-4 sm:px-5 pt-4 pb-3 border-b border-white/[0.06] bg-cyber-card/40">
        <div className="flex items-center gap-3 flex-wrap">
          <div className="flex items-center gap-2.5 min-w-0">
            <span className="grid place-items-center w-9 h-9 rounded-lg bg-violet-500/12 ring-1 ring-inset ring-violet-500/20">
              <MonitorPlay size={18} className="text-violet-300" />
            </span>
            <div className="min-w-0">
              <h1 className="text-base font-semibold text-slate-100 truncate">
                {t('nav_virtual_machines')}
              </h1>
              <p className="text-[11px] text-slate-500 truncate">{t('ocp_vms_page_sub')}</p>
            </div>
          </div>

          {clusters.length > 0 && (
            <select
              className="rounded-lg border border-white/[0.08] bg-cyber-deep text-sm text-slate-200 py-1.5 px-2.5"
              value={clusterId ?? ''}
              onChange={(e) => pickCluster(Number(e.target.value))}
            >
              {clusters.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}{c.version ? ` · ${c.version}` : ''}
                </option>
              ))}
            </select>
          )}

          <div className="relative flex-1 min-w-[140px] max-w-xs">
            <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
            <input
              type="search"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t('ocp_vms_search_ph')}
              className="w-full rounded-lg border border-white/[0.08] bg-cyber-deep text-sm text-slate-200 py-1.5 pl-8 pr-2.5 placeholder:text-slate-600"
            />
          </div>

          <div className="flex rounded-lg border border-white/[0.08] overflow-hidden text-xs">
            {([
              ['all', t('filter_all')],
              ['running', t('hv_running_now')],
              ['stopped', t('disabled')],
            ] as const).map(([id, label]) => (
              <button
                key={id}
                type="button"
                onClick={() => setStatus(id)}
                className={`px-2.5 py-1.5 transition-colors ${
                  status === id
                    ? 'bg-violet-500/20 text-violet-200'
                    : 'text-slate-400 hover:bg-white/[0.04]'
                }`}
              >
                {label}
              </button>
            ))}
          </div>

          {current && (
            <span className="text-[11px] text-slate-500 ml-auto hidden sm:inline">
              {current.name}
              {current.status ? ` · ${current.status}` : ''}
            </span>
          )}
        </div>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-4 sm:px-5">
        {isLoading && (
          <div className="text-sm text-slate-500 flex items-center gap-2 py-12 justify-center">
            <RefreshCw size={14} className="animate-spin" /> {t('loading')}
          </div>
        )}

        {!isLoading && clusters.length === 0 && (
          <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-10 text-center">
            <Boxes size={36} className="mx-auto mb-3 text-slate-600" />
            <p className="text-sm text-slate-300">{t('ocp_no_cluster')}</p>
            <p className="text-xs text-slate-500 mt-2 max-w-md mx-auto">{t('ocp_no_cluster_hint')}</p>
            <Link
              to="/integrations/openshift"
              className="inline-flex mt-4 text-xs px-4 py-2 rounded-lg bg-rose-600/90 text-white hover:bg-rose-500"
            >
              {t('ocp_go_integrations')}
            </Link>
          </div>
        )}

        {clusterId && (
          <OcpVmsPanel
            clusterId={clusterId}
            listOnly
            search={q}
            statusFilter={status}
          />
        )}
      </div>
    </div>
  )
}
