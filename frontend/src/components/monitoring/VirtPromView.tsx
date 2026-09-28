/**
 * Virtualization Prometheus mode — vmware_exporter charts.
 */
import React, { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#06b6d4', '#a3e635', '#f97316', '#38bdf8']

export const VirtPromView: React.FC<{ sourceId?: string }> = ({ sourceId }) => {
  const t = useT()
  const [metric, setMetric] = useState('vm_cpu')
  const [rangeSec, setRangeSec] = useState(900)
  const qs = sourceId ? `source_id=${encodeURIComponent(sourceId)}` : ''

  const { data: overview } = useQuery({
    queryKey: ['virt-prom-overview', sourceId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/monitoring/prom/overview?${qs}`)
      return r.json()
    },
  })

  const { data: catalog } = useQuery({
    queryKey: ['virt-prom-catalog'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/monitoring/prom/catalog`)
      return r.json() as Promise<{ metrics: { id: string; title: string }[] }>
    },
  })

  const { data: seriesData, isFetching } = useQuery({
    queryKey: ['virt-prom-series', metric, rangeSec, sourceId],
    queryFn: async () => {
      const r = await fetch(
        `${API_BASE_URL}/hypervisors/monitoring/prom/series?metric=${metric}&range_sec=${rangeSec}&top_n=8&${qs}`,
      )
      return r.json()
    },
  })

  const chartData = useMemo(() => {
    const series = seriesData?.series || []
    const byT: Record<number, Record<string, number | string>> = {}
    series.forEach((s: { name: string; points: { t: number; v: number }[] }, i: number) => {
      s.points.forEach((p) => {
        if (!byT[p.t]) byT[p.t] = { t: p.t }
        byT[p.t][`s${i}`] = p.v
      })
    })
    return Object.values(byT).sort((a, b) => Number(a.t) - Number(b.t))
  }, [seriesData])

  if (overview && overview.configured === false) {
    return (
      <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-6 text-sm text-slate-400">
        {t('mon_virt_prom_missing')}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-2 md:grid-cols-3 gap-3">
        <div className="rounded-xl border border-white/[0.06] bg-cyber-card px-3 py-2">
          <div className="text-[10px] uppercase text-slate-500">{t('mon_discovered')}</div>
          <div className="text-lg font-semibold text-slate-100">{overview?.metric_count ?? '—'}</div>
        </div>
        <div className="rounded-xl border border-white/[0.06] bg-cyber-card px-3 py-2 col-span-2">
          <div className="text-[10px] uppercase text-slate-500">Source</div>
          <div className="text-sm font-mono text-slate-200 truncate">{overview?.source?.label || '—'}</div>
        </div>
      </div>

      <div className="flex flex-wrap gap-2">
        <select
          value={metric}
          onChange={(e) => setMetric(e.target.value)}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2 py-1.5 text-xs text-slate-200"
        >
          {(catalog?.metrics || []).map((m) => (
            <option key={m.id} value={m.id}>{m.title}</option>
          ))}
        </select>
        <select
          value={rangeSec}
          onChange={(e) => setRangeSec(Number(e.target.value))}
          className="bg-cyber-deep border border-white/[0.08] rounded-lg px-2 py-1.5 text-xs text-slate-200"
        >
          <option value={900}>15m</option>
          <option value={3600}>1h</option>
          <option value={21600}>6h</option>
        </select>
      </div>

      <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 min-h-[280px]">
        {isFetching && <p className="text-xs text-slate-500">{t('mon_loading')}</p>}
        {seriesData && !seriesData.ok && (
          <p className="text-xs text-amber-400">{seriesData.error}</p>
        )}
        {chartData.length > 0 && (
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
              <XAxis
                dataKey="t"
                tickFormatter={(v) => new Date(Number(v) * 1000).toLocaleTimeString()}
                stroke="#64748b"
                fontSize={10}
              />
              <YAxis stroke="#64748b" fontSize={10} width={48} />
              <Tooltip contentStyle={{ background: '#0d1422', border: '1px solid rgba(255,255,255,0.1)' }} />
              <Legend />
              {(seriesData?.series || []).map((s: { name: string }, i: number) => (
                <Area
                  key={s.name}
                  type="monotone"
                  dataKey={`s${i}`}
                  name={s.name}
                  stroke={COLORS[i % COLORS.length]}
                  fill={COLORS[i % COLORS.length]}
                  fillOpacity={0.1}
                  strokeWidth={1.5}
                  dot={false}
                />
              ))}
            </AreaChart>
          </ResponsiveContainer>
        )}
      </div>
    </div>
  )
}

export default VirtPromView
