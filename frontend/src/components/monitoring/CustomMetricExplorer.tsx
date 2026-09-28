/**
 * Other / custom monitoring — PromQL metric explorer (prometheus / telegraf / otel→Prom).
 */
import React, { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#06b6d4', '#a3e635', '#f97316', '#38bdf8']

type Source = { id: string; label: string; url: string; binding: string; collector_type?: string }

export const CustomMetricExplorer: React.FC<{
  sourceId?: string
  onSourceIdChange?: (id: string) => void
  hideSourcePicker?: boolean
  titleLabel?: string
  collectorType?: string
}> = ({
  sourceId: controlledId,
  onSourceIdChange,
  hideSourcePicker = false,
  titleLabel,
  collectorType,
}) => {
  const t = useT()
  const [localId, setLocalId] = useState('')
  const sourceId = controlledId ?? localId
  const setSourceId = (id: string) => {
    if (onSourceIdChange) onSourceIdChange(id)
    else setLocalId(id)
  }
  const [q, setQ] = useState('')
  const [metric, setMetric] = useState('')
  const [rangeSec, setRangeSec] = useState(900)

  const { data: sourcesData } = useQuery({
    queryKey: ['mon-custom-sources'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/monitoring/custom/sources`)
      if (!r.ok) throw new Error('sources')
      return r.json() as Promise<{ sources: Source[] }>
    },
  })
  const sources = sourcesData?.sources || []

  React.useEffect(() => {
    if (!sourceId && sources.length) setSourceId(sources[0].id)
  }, [sources, sourceId])

  const active = sources.find((s) => s.id === sourceId)
  const displayLabel = titleLabel || active?.label
  const displayType = collectorType || active?.collector_type || 'prometheus'

  const { data: metricsData, isFetching: metricsLoading } = useQuery({
    queryKey: ['mon-custom-metrics', sourceId, q],
    enabled: !!sourceId,
    queryFn: async () => {
      const r = await fetch(
        `${API_BASE_URL}/monitoring/custom/metrics?source_id=${encodeURIComponent(sourceId)}&q=${encodeURIComponent(q)}`,
      )
      if (!r.ok) throw new Error('metrics')
      return r.json() as Promise<{ ok: boolean; names: string[]; error?: string }>
    },
  })

  const { data: seriesData, isFetching: seriesLoading } = useQuery({
    queryKey: ['mon-custom-series', sourceId, metric, rangeSec],
    enabled: !!sourceId && !!metric,
    queryFn: async () => {
      const r = await fetch(
        `${API_BASE_URL}/monitoring/custom/series?source_id=${encodeURIComponent(sourceId)}&metric=${encodeURIComponent(metric)}&range_sec=${rangeSec}&top_n=8`,
      )
      if (!r.ok) throw new Error('series')
      return r.json() as Promise<{
        ok: boolean
        series: { name: string; points: { t: number; v: number }[] }[]
        error?: string
      }>
    },
  })

  const chartData = useMemo(() => {
    const series = seriesData?.series || []
    if (!series.length) return []
    const byT: Record<number, Record<string, number | string>> = {}
    series.forEach((s, i) => {
      const key = `s${i}`
      s.points.forEach((p) => {
        if (!byT[p.t]) byT[p.t] = { t: p.t }
        byT[p.t][key] = p.v
      })
    })
    return Object.values(byT).sort((a, b) => Number(a.t) - Number(b.t))
  }, [seriesData])

  if (!hideSourcePicker && !sources.length) {
    return (
      <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-6 text-sm text-slate-400">
        {t('mon_other_empty')}
      </div>
    )
  }

  return (
    <div className="space-y-4">
      {(displayLabel || !hideSourcePicker) && (
        <div className="flex flex-wrap items-baseline gap-2">
          {displayLabel && (
            <h2 className="text-sm font-medium text-white">
              {displayLabel}
              <span className="ml-2 text-[10px] uppercase tracking-wide text-slate-500 font-normal">
                {displayType}
              </span>
            </h2>
          )}
        </div>
      )}
      <div className="flex flex-wrap gap-3 items-end">
        {!hideSourcePicker && (
          <div>
            <label className="block text-[10px] uppercase tracking-wide text-slate-500 mb-1">{t('mon_source_label')}</label>
            <select
              value={sourceId}
              onChange={(e) => setSourceId(e.target.value)}
              className="bg-cyber-deep border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-slate-200"
            >
              {sources.map((s) => (
                <option key={s.id} value={s.id}>{s.label}</option>
              ))}
            </select>
          </div>
        )}
        <div>
          <label className="block text-[10px] uppercase tracking-wide text-slate-500 mb-1">{t('mon_range')}</label>
          <select
            value={rangeSec}
            onChange={(e) => setRangeSec(Number(e.target.value))}
            className="bg-cyber-deep border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-slate-200"
          >
            <option value={900}>15m</option>
            <option value={3600}>1h</option>
            <option value={21600}>6h</option>
            <option value={86400}>24h</option>
          </select>
        </div>
        <div className="flex-1 min-w-[180px]">
          <label className="block text-[10px] uppercase tracking-wide text-slate-500 mb-1">{t('mon_metric_search')}</label>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="cpu, dcgm, kube…"
            className="w-full bg-cyber-deep border border-white/[0.08] rounded-lg px-3 py-2 text-sm text-slate-200 font-mono"
          />
        </div>
      </div>

      <div className="grid md:grid-cols-[280px_1fr] gap-4">
        <div className="rounded-xl border border-white/[0.06] bg-cyber-card max-h-[420px] overflow-y-auto">
          <div className="px-3 py-2 text-[10px] uppercase text-slate-500 border-b border-white/[0.04]">
            {metricsLoading ? '…' : `${(metricsData?.names || []).length} metrics`}
          </div>
          {(metricsData?.names || []).slice(0, 200).map((name) => (
            <button
              key={name}
              type="button"
              onClick={() => setMetric(name)}
              className={`w-full text-left px-3 py-1.5 text-xs font-mono truncate border-b border-white/[0.03] ${
                metric === name ? 'bg-blue-600/20 text-blue-200' : 'text-slate-400 hover:bg-white/[0.03]'
              }`}
            >
              {name}
            </button>
          ))}
        </div>

        <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 min-h-[320px]">
          {!metric && (
            <p className="text-sm text-slate-500">{t('mon_pick_metric')}</p>
          )}
          {metric && seriesLoading && (
            <p className="text-sm text-slate-500">{t('mon_loading')}</p>
          )}
          {metric && seriesData && !seriesData.ok && (
            <p className="text-sm text-amber-400">{seriesData.error}</p>
          )}
          {metric && chartData.length > 0 && (
            <>
              <div className="text-xs text-slate-400 mb-2 font-mono truncate">{metric}</div>
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
                  <Tooltip
                    contentStyle={{ background: '#0d1422', border: '1px solid rgba(255,255,255,0.1)' }}
                    labelFormatter={(v) => new Date(Number(v) * 1000).toLocaleString()}
                  />
                  <Legend />
                  {(seriesData?.series || []).map((s, i) => (
                    <Area
                      key={s.name}
                      type="monotone"
                      dataKey={`s${i}`}
                      name={s.name}
                      stroke={COLORS[i % COLORS.length]}
                      fill={COLORS[i % COLORS.length]}
                      fillOpacity={0.12}
                      strokeWidth={1.5}
                      dot={false}
                    />
                  ))}
                </AreaChart>
              </ResponsiveContainer>
            </>
          )}
        </div>
      </div>
    </div>
  )
}

export default CustomMetricExplorer
