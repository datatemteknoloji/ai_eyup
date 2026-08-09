/**
 * OpenShift Komuta Merkezi — küme özeti + Events'e yönlendirme (olay listesi Events'te).
 */
import { useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Boxes, Server, AlertTriangle, CheckCircle2, ChevronRight, ClipboardList } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { OpsRefreshCountdown, OpsShell } from '../components/ops/OpsShell'

interface ClusterSummary {
  id: number; name: string; api_url: string; status: string | null; version: string | null
  node_count: number; not_ready_nodes: string[]; project_count: number; last_sync: string | null
}

interface CommandCenterData {
  clusters: ClusterSummary[]
  critical_events: { id: number }[]
  warning_events: { id: number }[]
  total_events: number
  generated_at: string
}

function relTime(iso: string | null): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '—'
  const m = Math.floor((Date.now() - t) / 60000)
  if (m < 1) return 'şimdi'
  if (m < 60) return `${m}dk`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}s`
  return `${Math.floor(h / 24)}g`
}

function ClusterCard({ c }: { c: ClusterSummary }) {
  const healthy = c.status !== 'ERROR' && c.not_ready_nodes.length === 0
  return (
    <div className={`rounded-xl border bg-gradient-to-br p-4 w-[min(100%,320px)] min-w-[280px] flex-shrink-0 ${
      healthy ? 'from-rose-600/10 to-red-700/5 border-rose-500/25' : 'from-red-600/20 to-orange-600/10 border-red-500/40'
    }`}>
      <div className="flex items-start justify-between mb-3 gap-2">
        <div className="flex items-center gap-3 min-w-0">
          <div className="w-10 h-10 rounded-lg bg-slate-900/50 flex items-center justify-center flex-shrink-0">
            <Boxes size={18} className="text-white" />
          </div>
          <div className="min-w-0">
            <div className="text-white font-semibold truncate">{c.name}</div>
            <div className="text-xs text-slate-400 truncate">{c.version || 'sürüm bilinmiyor'} · {c.api_url}</div>
          </div>
        </div>
        <span className={`text-[10px] px-2 py-0.5 rounded-full border font-semibold uppercase flex-shrink-0 ${
          healthy ? 'bg-green-500/20 text-green-300 border-green-500/40' : 'bg-red-500/20 text-red-300 border-red-500/40'
        }`}>
          {healthy ? 'OK' : 'SORUNLU'}
        </span>
      </div>
      <div className="grid grid-cols-2 gap-2 text-xs text-slate-300 mb-2">
        <div className="flex items-center gap-1.5"><Server size={12} className="text-slate-500" /> {c.node_count} node</div>
        <div className="flex items-center gap-1.5"><Boxes size={12} className="text-slate-500" /> {c.project_count} proje</div>
      </div>
      {c.not_ready_nodes.length > 0 && (
        <div className="text-xs text-red-300 flex items-start gap-1.5">
          <AlertTriangle size={12} className="mt-0.5 flex-shrink-0" />
          <span className="truncate">NotReady: {c.not_ready_nodes.join(', ')}</span>
        </div>
      )}
      <div className="text-[11px] text-slate-500 mt-2">Son sync: {relTime(c.last_sync)}</div>
      <Link
        to="/openshift"
        className="inline-flex items-center gap-1 mt-3 text-xs text-rose-300 hover:text-rose-200"
      >
        Envanter <ChevronRight size={12} />
      </Link>
    </div>
  )
}

export default function OpenShiftOpsCenter() {
  const qc = useQueryClient()

  const { data, isLoading } = useQuery<CommandCenterData>({
    queryKey: ['openshift-command-center'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/ops/command-center`)
      if (!r.ok) throw new Error('openshift ops/command-center error')
      return r.json()
    },
    refetchInterval: 30_000,
  })

  const refresh = useCallback(() => {
    qc.invalidateQueries({ queryKey: ['openshift-command-center'] })
  }, [qc])

  const clusters = data?.clusters || []
  const criticalCount = data?.critical_events?.length || 0
  const warningCount = data?.warning_events?.length || 0
  const healthyClusters = clusters.filter(c => c.status !== 'ERROR' && c.not_ready_nodes.length === 0).length
  const actionable = criticalCount + warningCount

  return (
    <OpsShell
      platform="openshift"
      loading={isLoading}
      kpi={{
        critical: criticalCount,
        warning: warningCount,
        tertiaryValue: healthyClusters,
        tertiaryLabel: 'Sağlıklı Cluster',
      }}
      headerActions={<OpsRefreshCountdown onRefresh={refresh} />}
    >
      {clusters.length === 0 ? (
        <div className="text-center py-12 text-slate-500">
          <Boxes size={32} className="mx-auto mb-3 opacity-40" />
          <p className="text-sm">Henüz bir OpenShift cluster'ı bağlanmamış.</p>
          <Link to="/integrations/openshift" className="inline-flex items-center gap-1 mt-3 text-cyan-400 hover:text-cyan-300 text-sm">
            Cluster ekle <ChevronRight size={14} />
          </Link>
        </div>
      ) : (
        <div className="flex gap-3 overflow-x-auto pb-2">
          {clusters.map(c => <ClusterCard key={c.id} c={c} />)}
        </div>
      )}

      <div className="rounded-xl border border-white/[0.08] bg-cyber-card/60 p-4 flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-start gap-3 min-w-0">
          <div className="w-10 h-10 rounded-lg bg-slate-900/50 flex items-center justify-center flex-shrink-0">
            <ClipboardList size={18} className="text-amber-300" />
          </div>
          <div className="min-w-0">
            <div className="text-sm text-white font-medium">Olaylar</div>
            <div className="text-xs text-slate-400 mt-0.5">
              {actionable > 0
                ? `${criticalCount} kritik · ${warningCount} uyarı — detay Events ekranında`
                : 'Aktif kritik/uyarı yok — geçmiş ve heatmap Events’te'}
            </div>
          </div>
        </div>
        <Link
          to="/openshift/events"
          className="inline-flex items-center gap-1.5 px-3 py-2 rounded-lg text-sm font-medium bg-rose-600/20 text-rose-200 border border-rose-500/30 hover:bg-rose-600/30"
        >
          Events’e git <ChevronRight size={14} />
        </Link>
      </div>

      {clusters.length > 0 && actionable === 0 && (
        <div className="text-center py-6 text-slate-500">
          <CheckCircle2 size={28} className="mx-auto mb-2 text-green-500/60" />
          <p className="text-sm">Aktif kritik/uyarı olayı yok.</p>
        </div>
      )}
    </OpsShell>
  )
}
