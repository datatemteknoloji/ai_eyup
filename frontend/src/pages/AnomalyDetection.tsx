import React, { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

type LogListResponse = {
  anomalies: Array<{
    id: number
    source: 'log' | string
    server_id?: number
    server_name?: string
    ip_address?: string
    severity: 'warning' | 'error' | 'critical' | 'emergency' | string
    score: number
    title?: string
    message?: string
    created_at?: string
    date?: string
  }>
  total: number
  critical_count: number
  warning_count: number
  days: number
  generated_at?: string
}

type HeatmapCell = { date: string; count: number; score: number }
type HeatmapRow = { server_id: number; server_name: string; ip_address?: string; total_count: number; total_score: number; cells: HeatmapCell[] }
type LogHeatmapResponse = { dates: string[]; rows: HeatmapRow[]; max_cell_score: number; generated_at: string }

type AnomalyLabel = 'anomaly' | 'not_anomaly'
const LABEL_STORAGE_KEY = 'anomaly_detection_labels_v1'

function getAnomalyKey(a: LogListResponse['anomalies'][number]) {
  return [a.source || '', a.server_name || '', a.title || '', a.message || '', a.created_at || '', String(a.id ?? '')].join('|')
}

function heatColor(score: number, maxScore: number) {
  if (!score || maxScore <= 0) return 'bg-slate-800'
  const ratio = score / maxScore
  if (ratio >= 0.75) return 'bg-red-600/80'
  if (ratio >= 0.5) return 'bg-orange-500/75'
  if (ratio >= 0.25) return 'bg-amber-500/65'
  return 'bg-yellow-500/45'
}

function formatDayLabel(isoDate: string) {
  // Use raw YYYY-MM-DD to avoid timezone day shifts.
  const [y, m, d] = isoDate.split('-')
  if (!y || !m || !d) return isoDate
  return `${d}.${m}`
}

const AnomalyDetection: React.FC = () => {
  const [serverSearch, setServerSearch] = useState('')
  const [backfillDays, setBackfillDays] = useState(7)
  const [backfillMsg, setBackfillMsg] = useState<string | null>(null)
  const queryClient = useQueryClient()
  const [labels, setLabels] = useState<Record<string, AnomalyLabel>>(() => {
    try {
      const raw = localStorage.getItem(LABEL_STORAGE_KEY)
      return raw ? JSON.parse(raw) : {}
    } catch {
      return {}
    }
  })

  const { data, isLoading, isFetching, error, refetch } = useQuery<LogListResponse>({
    queryKey: ['anomaly-log-list-30d'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/anomalies/logs/list?days=30`)
      if (!res.ok) throw new Error('Anomaly log list alınamadı')
      return res.json()
    },
    refetchInterval: 60000,
  })

  const { data: heatmapData, isLoading: heatmapLoading, error: heatmapError } = useQuery<LogHeatmapResponse>({
    queryKey: ['anomaly-log-heatmap-30d'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/anomalies/logs/heatmap?days=30`)
      if (!res.ok) throw new Error('Heatmap alınamadı')
      return res.json()
    },
    refetchInterval: 60000,
  })

  const backfillMutation = useMutation({
    mutationFn: async (days: number) => {
      const res = await fetch(`${API_BASE_URL}/anomalies/logs/backfill?days=${days}`, { method: 'POST' })
      if (!res.ok) throw new Error('Backfill başarısız')
      return res.json()
    },
    onSuccess: (result) => {
      setBackfillMsg(`✅ ${result.backfill_days} gün backfill tamamlandı: ${result.total_saved ?? 0} yeni log kaydedildi (${result.servers_with_logs ?? 0} sunucu)`)
      queryClient.invalidateQueries({ queryKey: ['anomaly-log-heatmap-30d'] })
      queryClient.invalidateQueries({ queryKey: ['anomaly-log-list-30d'] })
    },
    onError: () => setBackfillMsg('❌ Backfill sırasında hata oluştu.'),
  })

  const anomalies = data?.anomalies || []
  const filteredAnomalies = useMemo(() => {
    const q = serverSearch.trim().toLowerCase()
    if (!q) return anomalies
    return anomalies.filter(a => (a.server_name || '').toLowerCase().includes(q))
  }, [anomalies, serverSearch])

  const filteredHeatmapRows = useMemo(() => {
    const rows = heatmapData?.rows || []
    const q = serverSearch.trim().toLowerCase()
    const filtered = !q ? rows : rows.filter(r => r.server_name.toLowerCase().includes(q) || (r.ip_address || '').toLowerCase().includes(q))
    return [...filtered].sort((a, b) => b.total_score - a.total_score)
  }, [heatmapData, serverSearch])

  const markLabel = (a: LogListResponse['anomalies'][number], label: AnomalyLabel) => {
    const key = getAnomalyKey(a)
    setLabels(prev => {
      const next = { ...prev, [key]: label }
      localStorage.setItem(LABEL_STORAGE_KEY, JSON.stringify(next))
      return next
    })
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold text-white">AIOps - Anomaly Detection</h2>
          <p className="text-slate-400 text-sm mt-1">Son 30 günlük log anomali yoğunluğu ve aynı kaynaktan detay listesi.</p>
        </div>
        <div className="flex items-center gap-2">
          <select
            value={backfillDays}
            onChange={e => setBackfillDays(Number(e.target.value))}
            className="bg-slate-800 border border-slate-600 text-white text-sm rounded-lg px-2 py-2 focus:outline-none focus:ring-2 focus:ring-amber-500"
          >
            <option value={1}>1 gün</option>
            <option value={3}>3 gün</option>
            <option value={7}>7 gün</option>
            <option value={14}>14 gün</option>
            <option value={30}>30 gün</option>
          </select>
          <button
            type="button"
            onClick={() => { setBackfillMsg(null); backfillMutation.mutate(backfillDays) }}
            disabled={backfillMutation.isPending}
            className="px-4 py-2 rounded-lg bg-amber-600 hover:bg-amber-500 disabled:opacity-60 text-white text-sm font-medium"
            title="Seçilen süre kadar geçmiş log verilerini tüm sunuculardan toplar"
          >
            {backfillMutation.isPending ? 'Yükleniyor...' : '📥 Geçmiş Veri Yükle'}
          </button>
          <button type="button" onClick={() => refetch()} className="px-4 py-2 rounded-lg bg-blue-600 hover:bg-blue-500 text-white text-sm font-medium">
            {isFetching ? 'Yenileniyor...' : 'Yenile'}
          </button>
        </div>
      </div>

      {backfillMsg && (
        <div className={`px-4 py-3 rounded-xl text-sm font-medium ${backfillMsg.startsWith('✅') ? 'bg-green-900/40 border border-green-500/40 text-green-300' : 'bg-red-900/40 border border-red-500/40 text-red-300'}`}>
          {backfillMsg}
          <button onClick={() => setBackfillMsg(null)} className="ml-3 text-xs opacity-60 hover:opacity-100">✕</button>
        </div>
      )}

      <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
        <label className="block text-xs text-slate-400 mb-2">Sunucu Ara</label>
        <input
          type="text"
          value={serverSearch}
          onChange={e => setServerSearch(e.target.value)}
          placeholder="Sunucu adı veya IP yazın..."
          className="w-full md:w-96 bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
        />
      </div>

      <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4"><div className="text-slate-400 text-xs">Toplam</div><div className="text-2xl text-white font-semibold mt-1">{data?.total ?? 0}</div></div>
        <div className="bg-slate-800 border border-red-500/30 rounded-xl p-4"><div className="text-red-300 text-xs">Critical</div><div className="text-2xl text-red-200 font-semibold mt-1">{data?.critical_count ?? 0}</div></div>
        <div className="bg-slate-800 border border-amber-500/30 rounded-xl p-4"><div className="text-amber-300 text-xs">Warning</div><div className="text-2xl text-amber-200 font-semibold mt-1">{data?.warning_count ?? 0}</div></div>
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4"><div className="text-slate-400 text-xs">Gösterilen</div><div className="text-2xl text-white font-semibold mt-1">{filteredAnomalies.length}</div></div>
      </div>

      <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-700">
          <h3 className="text-white font-medium">Son 1 Aylık Log Anomali Isı Haritası</h3>
          <p className="text-xs text-slate-400 mt-1">Sunucular risk skoruna göre sıralı. Hücre üstüne gelerek detay görebilirsiniz.</p>
          <div className="mt-3 flex flex-wrap items-center gap-3 text-xs">
            <span className="text-slate-400">Skala:</span>
            <span className="inline-flex items-center gap-1 text-slate-300"><span className="w-3 h-3 rounded bg-slate-800 border border-slate-600" />0 (Normal)</span>
            <span className="inline-flex items-center gap-1 text-slate-300"><span className="w-3 h-3 rounded bg-yellow-500/45 border border-yellow-600/40" />Düşük</span>
            <span className="inline-flex items-center gap-1 text-slate-300"><span className="w-3 h-3 rounded bg-amber-500/65 border border-amber-600/40" />Orta</span>
            <span className="inline-flex items-center gap-1 text-slate-300"><span className="w-3 h-3 rounded bg-orange-500/75 border border-orange-600/40" />Yüksek</span>
            <span className="inline-flex items-center gap-1 text-slate-300"><span className="w-3 h-3 rounded bg-red-600/80 border border-red-600/40" />Kritik</span>
          </div>
        </div>
        {heatmapLoading ? (
          <div className="p-6 text-slate-400 text-sm">Harita yükleniyor...</div>
        ) : heatmapError ? (
          <div className="p-6 text-red-300 text-sm">Harita verisi alınamadı.</div>
        ) : (
          <div className="overflow-x-auto max-h-[520px]">
            <table className="min-w-full text-xs">
              <thead className="bg-slate-900/90 text-slate-300 sticky top-0 z-20">
                <tr>
                  <th className="sticky left-0 z-30 bg-slate-900 text-left px-3 py-2 min-w-[220px]">Sunucu</th>
                  {(heatmapData?.dates || []).map(d => (
                    <th key={d} className="px-1 py-2 whitespace-nowrap">{formatDayLabel(d)}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {filteredHeatmapRows.length === 0 && (
                  <tr>
                    <td
                      colSpan={(heatmapData?.dates?.length || 0) + 1}
                      className="px-4 py-6 text-center text-slate-400"
                    >
                      Isı haritası için veri bulunamadı. Sunucu filtresini temizleyin veya geçmiş veri yüklemeyi deneyin.
                    </td>
                  </tr>
                )}
                {filteredHeatmapRows.map(row => (
                  <tr key={row.server_id} className="border-t border-slate-700/70">
                    <td className="sticky left-0 z-10 bg-slate-800 text-slate-200 px-3 py-2 whitespace-nowrap">
                      <div className="font-medium">{row.server_name}</div>
                      <div className="text-[10px] text-slate-400">{row.ip_address || '-'}</div>
                      <div className="text-[10px] text-slate-400 mt-0.5">Skor: {row.total_score} · Kayıt: {row.total_count}</div>
                      {row.total_score === 0 && <div className="text-[10px] text-emerald-300 mt-0.5">Normal (anomali yok)</div>}
                    </td>
                    {row.cells.map(cell => (
                      <td key={`${row.server_id}-${cell.date}`} className="px-1 py-1">
                        <div
                          title={cell.score > 0
                            ? `${row.server_name} | ${cell.date} | kayıt: ${cell.count}, skor: ${cell.score}`
                            : `${row.server_name} | ${cell.date} | anomali yok (normal)`}
                          className={`w-6 h-6 rounded-md ${heatColor(cell.score, heatmapData?.max_cell_score || 0)} border border-slate-700 mx-auto transition-transform hover:scale-110 flex items-center justify-center`}
                        >
                          {cell.score === 0 && <span className="text-[10px] text-slate-500">·</span>}
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="bg-slate-800 border border-slate-700 rounded-xl overflow-hidden">
        <div className="px-4 py-3 border-b border-slate-700 flex items-center justify-between">
          <h3 className="text-white font-medium">Anomali Listesi</h3>
          <span className="text-xs text-slate-400">Son üretim: {data?.generated_at ? new Date(data.generated_at).toLocaleString('tr-TR') : '-'}</span>
        </div>

        {isLoading ? <div className="p-6 text-slate-400 text-sm">Yükleniyor...</div> : error ? <div className="p-6 text-red-300 text-sm">Veri alınamadı. API kontrolü yapın.</div> : filteredAnomalies.length === 0 ? <div className="p-6 text-slate-400 text-sm">Filtreye uyan anomali bulunamadı.</div> : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-sm">
              <thead className="bg-slate-900/60 text-slate-300"><tr><th className="text-left px-4 py-3">Tarih</th><th className="text-left px-4 py-3">Severity</th><th className="text-left px-4 py-3">Kaynak</th><th className="text-left px-4 py-3">Sunucu</th><th className="text-left px-4 py-3">Detay</th><th className="text-left px-4 py-3">Değerlendirme</th></tr></thead>
              <tbody>
                {filteredAnomalies.map((a, idx) => {
                  const key = getAnomalyKey(a)
                  const label = labels[key]
                  return (
                    <tr key={idx} className="border-t border-slate-700/70 text-slate-200">
                      <td className="px-4 py-3 text-slate-300">{a.created_at ? new Date(a.created_at).toLocaleString('tr-TR') : '-'}</td>
                      <td className="px-4 py-3"><span className={`px-2 py-1 rounded text-xs font-medium ${(a.severity === 'critical' || a.severity === 'emergency') ? 'bg-red-500/20 text-red-200 border border-red-500/40' : (a.severity === 'error' ? 'bg-orange-500/20 text-orange-200 border border-orange-500/40' : 'bg-amber-500/20 text-amber-200 border border-amber-500/40')}`}>{a.severity}</span></td>
                      <td className="px-4 py-3">{a.source || '-'}</td>
                      <td className="px-4 py-3">{a.server_name || '-'}</td>
                      <td className="px-4 py-3">{a.title || a.message || 'Detay yok'}</td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2 flex-wrap">
                          <button type="button" onClick={() => markLabel(a, 'anomaly')} className={`px-2 py-1 rounded text-xs border ${label === 'anomaly' ? 'bg-green-600/30 text-green-200 border-green-500/50' : 'bg-slate-700 text-slate-200 border-slate-600 hover:bg-slate-600'}`}>Bu anomalidir</button>
                          <button type="button" onClick={() => markLabel(a, 'not_anomaly')} className={`px-2 py-1 rounded text-xs border ${label === 'not_anomaly' ? 'bg-purple-600/30 text-purple-200 border-purple-500/50' : 'bg-slate-700 text-slate-200 border-slate-600 hover:bg-slate-600'}`}>Anomali değildir</button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

export default AnomalyDetection
