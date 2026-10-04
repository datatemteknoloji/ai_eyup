/**
 * Virtualization Prometheus mode — vmware_exporter katalog / seri.
 */
import React, { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#06b6d4', '#a3e635', '#f97316', '#38bdf8']
const RANGES = [
  { id: '15m', sec: 900 },
  { id: '1h', sec: 3600 },
  { id: '8h', sec: 28800 },
  { id: '24h', sec: 86400 },
]

type CatItem = { id: string; title: string; unit?: string; query?: string }

export const VirtPromView: React.FC<{ sourceId?: string }> = ({ sourceId }) => {
  const t = useT()
  const [metricId, setMetricId] = useState('vm_cpu')
  const [rangeSec, setRangeSec] = useState(3600)

  const overview = useQuery({
    queryKey: ['virt-prom-overview', sourceId],
    queryFn: async () => {
      const q = sourceId ? `?source_id=${encodeURIComponent(sourceId)}` : ''
      const r = await fetch(`${API_BASE_URL}/hypervisors/monitoring/prom/overview${q}`)
      if (!r.ok) throw new Error('overview')
      return r.json() as Promise<{ configured?: boolean; note?: string; catalog?: CatItem[]; metric_count?: number }>
    },
  })

  const catalog = useMemo(() => overview.data?.catalog || [], [overview.data])

  React.useEffect(() => {
    if (catalog.length && !catalog.find((c) => c.id === metricId)) {
      setMetricId(catalog[0].id)
    }
  }, [catalog, metricId])

  const series = useQuery({
    queryKey: ['virt-prom-series', sourceId, metricId, rangeSec],
    enabled: !!metricId && overview.data?.configured !== false,
    queryFn: async () => {
      const params = new URLSearchParams({
        metric: metricId,
        range_sec: String(rangeSec),
        top_n: '8',
      })
      if (sourceId) params.set('source_id', sourceId)
      const r = await fetch(`${API_BASE_URL}/hypervisors/monitoring/prom/series?${params}`)
      if (!r.ok) throw new Error('series')
      return r.json() as Promise<{
        ok?: boolean
        error?: string
        unit?: string
        series?: { name: string; points: { t: number | string; v: number | null }[] }[]
      }>
    },
    refetchInterval: 60_000,
  })

  const chartData = useMemo(() => {
    const byT: Record<string, Record<string, number | string>> = {}
    for (const [i, s] of (series.data?.series || []).entries()) {
      for (const p of s.points || []) {
        const key = String(p.t)
        if (!byT[key]) byT[key] = { t: p.t }
        if (p.v != null) byT[key][`s${i}`] = p.v
      }
    }
    return Object.values(byT).sort((a, b) => Number(a.t) - Number(b.t))
  }, [series.data])

  if (overview.isLoading) {
    return <div className="text-sm text-slate-400 py-8 text-center">{t('loading')}</div>
  }

  if (overview.data?.configured === false) {
    return (
      <div className="rounded-xl border border-amber-500/20 bg-cyber-card p-6 text-sm text-slate-400 space-y-2">
        <p>{overview.data?.note || t('mon_prom_not_configured')}</p>
        <p className="text-xs text-slate-500">{t('set_mon_sources_hint')}</p>
      </div>
    )
  }

  const active = catalog.find((c) => c.id === metricId)

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2 text-xs">
        <label className="flex items-center gap-1.5 text-slate-400">
          <span className="text-[10px] uppercase tracking-wider text-slate-500">Metric</span>
          <select
            value={metricId}
            onChange={(e) => setMetricId(e.target.value)}
            className="bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1 text-xs text-slate-200"
          >
            {catalog.map((c) => (
              <option key={c.id} value={c.id}>{c.title}</option>
            ))}
          </select>
        </label>
        <label className="flex items-center gap-1.5 text-slate-400">
          <span className="text-[10px] uppercase tracking-wider text-slate-500">Range</span>
          <select
            value={rangeSec}
            onChange={(e) => setRangeSec(Number(e.target.value))}
            className="bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1 text-xs text-slate-200"
          >
            {RANGES.map((r) => (
              <option key={r.id} value={r.sec}>{r.id}</option>
            ))}
          </select>
        </label>
        {overview.data?.metric_count != null && (
          <span className="text-slate-500 ml-auto">
            {overview.data.metric_count} series · {overview.data.note || 'vmware_exporter'}
          </span>
        )}
      </div>

      <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-3">
        <div className="text-sm text-white mb-2">
          {active?.title || metricId}
          {active?.unit ? <span className="text-slate-500 text-xs ml-2">{active.unit}</span> : null}
        </div>
        {series.isFetching && !chartData.length ? (
          <div className="h-64 flex items-center justify-center text-slate-500 text-sm">{t('loading')}</div>
        ) : series.data?.error ? (
          <div className="h-64 flex items-center justify-center text-amber-400 text-sm">{series.data.error}</div>
        ) : chartData.length === 0 ? (
          <div className="h-64 flex items-center justify-center text-slate-500 text-sm">{t('lm_not_found')}</div>
        ) : (
          <ResponsiveContainer width="100%" height={280}>
            <AreaChart data={chartData}>
              <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
              <XAxis
                dataKey="t"
                tick={{ fill: '#64748b', fontSize: 10 }}
                tickFormatter={(v) => {
                  const d = new Date(typeof v === 'number' && v < 1e12 ? v * 1000 : v)
                  return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
                }}
              />
              <YAxis tick={{ fill: '#64748b', fontSize: 10 }} width={48} />
              <Tooltip
                contentStyle={{ background: '#0d1422', border: '1px solid #334155', fontSize: 12 }}
                labelFormatter={(v) => {
                  const d = new Date(typeof v === 'number' && v < 1e12 ? v * 1000 : v)
                  return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString('tr-TR')
                }}
              />
              <Legend wrapperStyle={{ fontSize: 11 }} />
              {(series.data?.series || []).map((s, i) => (
                <Area
                  key={s.name}
                  type="monotone"
                  dataKey={`s${i}`}
                  name={s.name}
                  stroke={COLORS[i % COLORS.length]}
                  fill={COLORS[i % COLORS.length]}
                  fillOpacity={0.15}
                  strokeWidth={1.5}
                  dot={false}
                  connectNulls
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
