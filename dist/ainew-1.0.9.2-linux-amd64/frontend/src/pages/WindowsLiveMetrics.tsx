import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Cpu, MemoryStick, Clock, RefreshCw, AlertTriangle, Activity } from 'lucide-react'
import { API_BASE_URL } from '../config/api'

const WIN_API = `${API_BASE_URL}/windows`

interface LiveServer {
  id: number
  name: string
  ip_address: string
  status: string
  ai_ready: boolean
  cpu_pct: number | null
  mem_used_pct: number | null
  mem_total_gb: number | null
  mem_free_gb: number | null
  disks: { Name: string; UsedGB: number; FreeGB: number; TotalGB: number }[]
  uptime_days: number | null
  last_boot: string | null
  error: string | null
}

interface LiveMetricsResponse {
  servers: LiveServer[]
  total: number
  online: number
  avg_cpu_pct: number | null
  avg_mem_pct: number | null
}

const REFRESH_OPTIONS = [
  { label: '10 sn', value: 10_000 },
  { label: '30 sn', value: 30_000 },
  { label: '1 dk', value: 60_000 },
]

const barColor = (pct: number) => (pct >= 90 ? '#ef4444' : pct >= 75 ? '#f59e0b' : '#3b82f6')

const MetricBar: React.FC<{ value: number | null }> = ({ value }) => {
  const pct = Math.max(0, Math.min(100, value ?? 0))
  return (
    <div className="flex items-center gap-2 min-w-[140px]">
      <div className="flex-1 bg-slate-700 rounded-full h-2">
        <div className="h-2 rounded-full transition-all" style={{ width: `${pct}%`, backgroundColor: value === null ? '#475569' : barColor(pct) }} />
      </div>
      <span className="text-xs text-slate-300 font-mono w-11 text-right">{value === null ? '—' : `${value.toFixed(1)}%`}</span>
    </div>
  )
}

const SummaryCard: React.FC<{ icon: React.ReactNode; label: string; value: string | number; accent: string }> = ({ icon, label, value, accent }) => (
  <div className="bg-slate-800 border border-slate-700 rounded-xl p-4 flex items-center gap-3">
    <div className="w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0" style={{ backgroundColor: `${accent}20`, color: accent }}>
      {icon}
    </div>
    <div>
      <div className="text-2xl font-bold text-white">{value}</div>
      <div className="text-slate-400 text-xs">{label}</div>
    </div>
  </div>
)

const WindowsLiveMetrics: React.FC = () => {
  const [refreshMs, setRefreshMs] = useState(30_000)

  const { data, isLoading, isFetching, dataUpdatedAt, refetch } = useQuery<LiveMetricsResponse>({
    queryKey: ['windows-live-metrics'],
    queryFn: async () => {
      const r = await fetch(`${WIN_API}/live-metrics`)
      if (!r.ok) throw new Error('Canlı metrikler alınamadı')
      return r.json()
    },
    refetchInterval: refreshMs,
  })

  const servers = data?.servers || []
  const lastUpdated = dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString('tr-TR') : '—'

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold text-white">Windows Canlı Metrikler</h1>
          <p className="text-slate-400 text-sm mt-0.5">
            WinRM üzerinden AI Ready sunuculardan gerçek zamanlı CPU / RAM / Disk kullanımı
          </p>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1 bg-slate-800 border border-slate-700 rounded-lg p-1">
            {REFRESH_OPTIONS.map(opt => (
              <button
                key={opt.value}
                onClick={() => setRefreshMs(opt.value)}
                className={`px-2.5 py-1 rounded-md text-xs font-medium transition-colors ${refreshMs === opt.value ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}
              >
                {opt.label}
              </button>
            ))}
          </div>
          <button onClick={() => refetch()}
            className="flex items-center gap-2 px-4 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded-lg transition-colors">
            <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} /> Yenile
          </button>
        </div>
      </div>

      {/* Summary */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <SummaryCard icon={<Activity size={18} />} label="Canlı Sunucu" value={`${data?.online ?? 0} / ${data?.total ?? 0}`} accent="#22d3ee" />
        <SummaryCard icon={<Cpu size={18} />} label="Ortalama CPU" value={data?.avg_cpu_pct != null ? `%${data.avg_cpu_pct}` : '—'} accent="#3b82f6" />
        <SummaryCard icon={<MemoryStick size={18} />} label="Ortalama RAM" value={data?.avg_mem_pct != null ? `%${data.avg_mem_pct}` : '—'} accent="#a855f7" />
        <SummaryCard icon={<Clock size={18} />} label="Son Güncelleme" value={lastUpdated} accent="#94a3b8" />
      </div>

      {/* Table */}
      {isLoading ? (
        <div className="flex items-center justify-center h-40 gap-3 text-slate-400">
          <div className="w-5 h-5 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
          Yükleniyor...
        </div>
      ) : servers.length === 0 ? (
        <div className="flex flex-col items-center justify-center h-52 bg-slate-800 border border-slate-700 rounded-xl gap-3">
          <AlertTriangle size={40} className="text-slate-600" />
          <p className="text-slate-400 font-medium">AI Ready Windows sunucu bulunamadı</p>
          <p className="text-slate-500 text-sm text-center max-w-sm">
            Canlı metrik görebilmek için önce{' '}
            <Link to="/windows" className="text-blue-400 hover:underline">Windows Sunucular</Link> sayfasından
            "AI Ready Güncelle" ile WinRM bağlantısını doğrulayın.
          </p>
        </div>
      ) : (
        <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700 bg-slate-800/80">
                {['Sunucu', 'CPU', 'RAM', 'Disk (en dolu)', 'Uptime', ''].map(h => (
                  <th key={h} className="px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wide">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700/50">
              {servers.map(srv => {
                const worstDisk = [...(srv.disks || [])].sort((a, b) => {
                  const pctA = a.TotalGB > 0 ? a.UsedGB / a.TotalGB : 0
                  const pctB = b.TotalGB > 0 ? b.UsedGB / b.TotalGB : 0
                  return pctB - pctA
                })[0]
                const diskPct = worstDisk && worstDisk.TotalGB > 0 ? Math.round((worstDisk.UsedGB / worstDisk.TotalGB) * 100) : null
                const hasData = srv.ai_ready && srv.cpu_pct !== null
                return (
                  <tr key={srv.id} className="hover:bg-slate-700/30 transition-colors">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className={`w-2 h-2 rounded-full flex-shrink-0 ${hasData ? 'bg-green-400 animate-pulse' : 'bg-slate-600'}`} />
                        <div>
                          <div className="text-sm font-semibold text-white">{srv.name}</div>
                          <div className="text-xs text-slate-500 font-mono">{srv.ip_address || '—'}</div>
                        </div>
                      </div>
                    </td>
                    <td className="px-4 py-3"><MetricBar value={srv.cpu_pct} /></td>
                    <td className="px-4 py-3">
                      <MetricBar value={srv.mem_used_pct} />
                      {srv.mem_total_gb != null && (
                        <div className="text-[10px] text-slate-500 mt-0.5">{srv.mem_total_gb - (srv.mem_free_gb ?? 0)} / {srv.mem_total_gb} GB</div>
                      )}
                    </td>
                    <td className="px-4 py-3">
                      {worstDisk ? (
                        <>
                          <MetricBar value={diskPct} />
                          <div className="text-[10px] text-slate-500 mt-0.5">{worstDisk.Name}: {worstDisk.UsedGB} / {worstDisk.TotalGB} GB</div>
                        </>
                      ) : (
                        <span className="text-slate-600 text-xs">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-sm text-slate-300">
                      {srv.uptime_days != null ? `${srv.uptime_days} gün` : '—'}
                    </td>
                    <td className="px-4 py-3">
                      {srv.error && (
                        <span className="inline-flex items-center gap-1 text-[10px] text-amber-400" title={srv.error}>
                          <AlertTriangle size={10} /> {srv.ai_ready ? 'Sorgu hatası' : 'AI Ready değil'}
                        </span>
                      )}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default WindowsLiveMetrics
