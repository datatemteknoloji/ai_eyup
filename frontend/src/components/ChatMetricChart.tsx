import React, { useMemo } from 'react'
import {
  AreaChart,
  Area,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  Legend,
  ResponsiveContainer,
} from 'recharts'
import { useTheme } from '../theme/ThemeProvider'

export interface ChatChartSeries {
  metric_name: string
  label: string
  points: { t: string; v: number }[]
}

export interface ChatChartPayload {
  type: string
  title: string
  unit: string
  server_id?: number
  server_name?: string
  series: ChatChartSeries[]
}

const CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#06b6d4']


function formatBytesPerSec(v: number): string {
  const units = ['B/s', 'KB/s', 'MB/s', 'GB/s', 'TB/s']
  let val = v
  let i = 0
  while (Math.abs(val) >= 1024 && i < units.length - 1) {
    val /= 1024
    i++
  }
  return `${val.toFixed(val < 10 ? 2 : 1)} ${units[i]}`
}

function formatValue(v: number, unit: string): string {
  if (unit === 'B/s') return formatBytesPerSec(v)
  if (unit === '%') return `${v.toFixed(1)}%`
  return v.toFixed(2)
}

/** Pencere uzunluğuna göre eksen: saatlik / gün+saat / gün+ay. */
export function formatChartTick(ts: string, spanMs: number): string {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  const loc = 'tr-TR'
  if (spanMs <= 36 * 3600 * 1000) {
    return d.toLocaleTimeString(loc, { hour: '2-digit', minute: '2-digit' })
  }
  if (spanMs <= 14 * 24 * 3600 * 1000) {
    return d.toLocaleString(loc, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  }
  if (spanMs <= 400 * 24 * 3600 * 1000) {
    return d.toLocaleDateString(loc, { day: 'numeric', month: 'short' })
  }
  return d.toLocaleDateString(loc, { month: 'short', year: 'numeric' })
}

function formatChartTooltipLabel(ts: string, spanMs: number): string {
  const d = new Date(ts)
  if (Number.isNaN(d.getTime())) return ts
  if (spanMs <= 36 * 3600 * 1000) {
    return d.toLocaleString('tr-TR', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' })
  }
  return d.toLocaleString('tr-TR', { day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' })
}

/** AI chat mesajı içine gömülü zaman serisi grafiği (Recharts). */
const ChatMetricChart: React.FC<{ chart: ChatChartPayload; chartId?: string }> = ({ chart, chartId = 'chat-chart' }) => {
  const { theme } = useTheme()
  const light = theme === 'light'
  const axis = light ? '#475569' : '#64748b'
  const grid = light ? '#cbd5e1' : '#334155'
  const titleColor = light ? '#0f172a' : '#e2e8f0'
  const tip = light
    ? { bg: '#ffffff', border: '#cbd5e1', label: '#334155', item: '#0f172a' }
    : { bg: '#1e293b', border: '#334155', label: '#cbd5e1', item: '#f8fafc' }

  const { chartData, spanMs } = useMemo(() => {
    const allTimestamps = new Set<string>()
    chart.series.forEach(s => s.points.forEach(p => allTimestamps.add(p.t)))
    const timestamps = Array.from(allTimestamps).sort()
    const first = timestamps[0] ? new Date(timestamps[0]).getTime() : 0
    const last = timestamps.length ? new Date(timestamps[timestamps.length - 1]).getTime() : 0
    const span = Math.max(0, last - first)
    const rows = timestamps.map(ts => {
      const point: Record<string, number | string> = { ts }
      chart.series.forEach(s => {
        const match = s.points.find(p => p.t === ts)
        if (match) point[s.label] = match.v
      })
      return point
    })
    return { chartData: rows, spanMs: span }
  }, [chart])

  if (!chartData.length) {
    return (
      <div className="rounded-xl border border-cyber-border bg-cyber-card p-4 text-xs text-slate-500 text-center">
        {chart.title}: veri yok
      </div>
    )
  }

  return (
    <div className="mt-2 overflow-hidden rounded-xl border border-cyber-border bg-cyber-card">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-2.5 dark:border-white/10">
        <span className="text-xs font-semibold text-slate-100">{chart.title}</span>
        {chart.unit && <span className="text-[10px] text-slate-500">{chart.unit}</span>}
      </div>
      <div className="p-3" style={{ height: 240 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 8 }}>
            <defs>
              {chart.series.map((_, i) => (
                <linearGradient key={i} id={`${chartId}-fill-${i}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={CHART_COLORS[i % CHART_COLORS.length]} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={CHART_COLORS[i % CHART_COLORS.length]} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke={grid} opacity={0.55} />
            <XAxis
              dataKey="ts"
              stroke={axis}
              fontSize={10}
              tickLine={false}
              interval="preserveStartEnd"
              minTickGap={28}
              tickFormatter={(v) => formatChartTick(String(v), spanMs)}
              angle={spanMs > 36 * 3600 * 1000 ? -28 : 0}
              textAnchor={spanMs > 36 * 3600 * 1000 ? 'end' : 'middle'}
              height={spanMs > 36 * 3600 * 1000 ? 48 : 28}
            />
            <YAxis
              stroke={axis}
              fontSize={10}
              tickLine={false}
              tickFormatter={(v) => (chart.unit === 'B/s' ? formatBytesPerSec(Number(v)) : String(v))}
              width={chart.unit === 'B/s' ? 56 : 36}
            />
            <Tooltip
              contentStyle={{
                backgroundColor: tip.bg,
                border: `1px solid ${tip.border}`,
                borderRadius: 8,
                fontSize: 12,
                color: tip.item,
              }}
              labelStyle={{ color: tip.label }}
              itemStyle={{ color: tip.item }}
              formatter={(value: number, name: string) => [formatValue(Number(value), chart.unit), name]}
              labelFormatter={(label) => formatChartTooltipLabel(String(label), spanMs)}
            />
            {chart.series.length > 1 && (
              <Legend wrapperStyle={{ fontSize: 11, color: titleColor }} />
            )}
            {chart.series.map((s, i) => (
              <Area
                key={s.metric_name}
                type="monotone"
                dataKey={s.label}
                stroke={CHART_COLORS[i % CHART_COLORS.length]}
                strokeWidth={2}
                fill={`url(#${chartId}-fill-${i})`}
                connectNulls
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default ChatMetricChart
