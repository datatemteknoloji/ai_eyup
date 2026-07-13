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

/** AI chat mesajı içine gömülü, node_exporter zaman serisi grafiği (Recharts). */
const ChatMetricChart: React.FC<{ chart: ChatChartPayload; chartId?: string }> = ({ chart, chartId = 'chat-chart' }) => {
  const chartData = useMemo(() => {
    const allTimestamps = new Set<string>()
    chart.series.forEach(s => s.points.forEach(p => allTimestamps.add(p.t)))
    const timestamps = Array.from(allTimestamps).sort()
    return timestamps.map(ts => {
      const point: Record<string, number | string> = {
        time: new Date(ts).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' }),
        _ts: ts,
      }
      chart.series.forEach(s => {
        const match = s.points.find(p => p.t === ts)
        if (match) point[s.label] = match.v
      })
      return point
    })
  }, [chart])

  if (!chartData.length) {
    return (
      <div className="bg-cyber-deep/60 border border-white/[0.08] rounded-xl p-4 text-xs text-slate-500 text-center">
        {chart.title}: veri yok
      </div>
    )
  }

  return (
    <div className="bg-cyber-deep/60 border border-white/[0.08] rounded-xl overflow-hidden mt-2">
      <div className="px-4 py-2.5 border-b border-white/[0.06] flex items-center justify-between">
        <span className="text-xs font-semibold text-slate-200">{chart.title}</span>
        {chart.unit && <span className="text-[10px] text-slate-500">{chart.unit}</span>}
      </div>
      <div className="p-3" style={{ height: 220 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
            <defs>
              {chart.series.map((_, i) => (
                <linearGradient key={i} id={`${chartId}-fill-${i}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={CHART_COLORS[i % CHART_COLORS.length]} stopOpacity={0.35} />
                  <stop offset="100%" stopColor={CHART_COLORS[i % CHART_COLORS.length]} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.4} />
            <XAxis dataKey="time" stroke="#64748b" fontSize={10} tickLine={false} />
            <YAxis
              stroke="#64748b"
              fontSize={10}
              tickLine={false}
              tickFormatter={(v) => (chart.unit === 'B/s' ? formatBytesPerSec(Number(v)) : String(v))}
              width={chart.unit === 'B/s' ? 56 : 32}
            />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px', fontSize: 12 }}
              labelStyle={{ color: '#94a3b8' }}
              formatter={(value: number, name: string) => [formatValue(Number(value), chart.unit), name]}
              labelFormatter={(label) => `Saat: ${label}`}
            />
            {chart.series.length > 1 && (
              <Legend wrapperStyle={{ fontSize: 11 }} formatter={(value) => <span className="text-slate-400">{value}</span>} />
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
