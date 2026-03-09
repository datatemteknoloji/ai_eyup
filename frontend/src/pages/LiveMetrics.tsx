import React, { useMemo, useState, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
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

const PROMETHEUS_URL = 'http://192.168.1.166:9090'

/** Zaman aralığı seçenekleri: real-time (15dk) ile 8 saate kadar */
const TIME_RANGES = [
  { label: 'Son 15 dk', value: 900, step: 30 },
  { label: 'Son 30 dk', value: 1800, step: 30 },
  { label: 'Son 1 saat', value: 3600, step: 60 },
  { label: 'Son 2 saat', value: 7200, step: 120 },
  { label: 'Son 8 saat', value: 28800, step: 300 },
] as const

type PromResult = {
  metric: Record<string, string>
  value: [number, string]
}

type PromRangeResult = {
  metric: Record<string, string>
  values: [number, string][]
}

const fetchPrometheus = async (query: string): Promise<PromResult[]> => {
  const response = await fetch(`${PROMETHEUS_URL}/api/v1/query?query=${encodeURIComponent(query)}`)
  if (!response.ok) throw new Error('Failed to query Prometheus')
  const data = await response.json()
  return data?.data?.result || []
}

const fetchPrometheusRange = async (
  query: string,
  rangeSeconds: number,
  stepSeconds: number
): Promise<PromRangeResult[]> => {
  const end = Math.floor(Date.now() / 1000)
  const start = end - rangeSeconds
  const url = `${PROMETHEUS_URL}/api/v1/query_range?query=${encodeURIComponent(query)}&start=${start}&end=${end}&step=${stepSeconds}`
  const response = await fetch(url)
  if (!response.ok) throw new Error('Failed to query Prometheus range')
  const data = await response.json()
  return data?.data?.result || []
}

const fetchInstances = async (): Promise<string[]> => {
  // Sadece up=1 (veri gelen) instance'lari goster
  const response = await fetch(`${PROMETHEUS_URL}/api/v1/query?query=up{job="node-exporter"}`)
  if (!response.ok) throw new Error('Failed to fetch instances')
  const data = await response.json()
  const results = data?.data?.result || []
  return results
    .filter((r: any) => r.value?.[1] === '1')
    .map((r: any) => r.metric?.instance || '')
    .filter(Boolean)
}

// instance'in up durumunu tutan map
const fetchInstanceUpStatus = async (): Promise<Record<string, boolean>> => {
  const response = await fetch(`${PROMETHEUS_URL}/api/v1/query?query=up{job="node-exporter"}`)
  if (!response.ok) return {}
  const data = await response.json()
  const results = data?.data?.result || []
  const map: Record<string, boolean> = {}
  results.forEach((r: any) => {
    const inst = r.metric?.instance || ''
    if (inst) map[inst] = r.value?.[1] === '1'
  })
  return map
}

const fetchInstanceLabels = async (): Promise<Record<string, string>> => {
  const response = await fetch(`${PROMETHEUS_URL}/api/v1/query?query=up{job="node-exporter"}`)
  if (!response.ok) throw new Error('Failed to fetch instance labels')
  const data = await response.json()
  const results: PromResult[] = data?.data?.result || []
  const map: Record<string, string> = {}
  results.forEach((item) => {
    const instance = item.metric.instance || ''
    const serverName = item.metric.server_name || item.metric.hostname || ''
    if (instance) {
      map[instance] = serverName
    }
  })
  return map
}

const fetchNodeExporterMetricNames = async (): Promise<string[]> => {
  const response = await fetch(`${PROMETHEUS_URL}/api/v1/label/__name__/values`)
  if (!response.ok) return []
  const data = await response.json()
  const names: string[] = data?.data || []
  return names.filter((n) => typeof n === 'string' && n.startsWith('node_')).sort()
}

/** Kullanıcının grafikte seçebileceği preset metrikler + PromQL şablonu */
type MetricPreset = {
  id: string
  label: string
  unit: string
  buildRangeQuery: (selector: string, byInstance: boolean) => string
}
const METRIC_PRESETS: MetricPreset[] = [
  {
    id: 'cpu',
    label: 'CPU kullanımı (%)',
    unit: '%',
    buildRangeQuery: (selector, _byInstance) =>
      `100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle",${selector}}[5m])) * 100)`,
  },
  {
    id: 'memory',
    label: 'Bellek kullanımı (%)',
    unit: '%',
    buildRangeQuery: (selector, _byInstance) =>
      `(1 - (node_memory_MemAvailable_bytes{${selector}} / node_memory_MemTotal_bytes{${selector}})) * 100`,
  },
  {
    id: 'disk',
    label: 'Disk (/) kullanımı (%)',
    unit: '%',
    buildRangeQuery: (selector, _byInstance) =>
      `(1 - (node_filesystem_avail_bytes{mountpoint="/",${selector}} / node_filesystem_size_bytes{mountpoint="/",${selector}})) * 100`,
  },
  {
    id: 'load',
    label: 'Load average (1m)',
    unit: '',
    buildRangeQuery: (selector, _byInstance) => `node_load1{${selector}}`,
  },
  {
    id: 'net_rx',
    label: 'Network RX (B/s)',
    unit: 'B/s',
    buildRangeQuery: (selector, _byInstance) =>
      `sum by (instance) (rate(node_network_receive_bytes_total{device!~"lo",${selector}}[5m]))`,
  },
  {
    id: 'net_tx',
    label: 'Network TX (B/s)',
    unit: 'B/s',
    buildRangeQuery: (selector, _byInstance) =>
      `sum by (instance) (rate(node_network_transmit_bytes_total{device!~"lo",${selector}}[5m]))`,
  },
  {
    id: 'mem_available',
    label: 'Bellek kullanılabilir (bytes)',
    unit: 'B',
    buildRangeQuery: (selector, _byInstance) => `node_memory_MemAvailable_bytes{${selector}}`,
  },
  {
    id: 'disk_read',
    label: 'Disk okuma (B/s)',
    unit: 'B/s',
    buildRangeQuery: (selector, _byInstance) =>
      `sum by (instance) (rate(node_disk_read_bytes_total{${selector}}[5m]))`,
  },
  {
    id: 'disk_written',
    label: 'Disk yazma (B/s)',
    unit: 'B/s',
    buildRangeQuery: (selector, _byInstance) =>
      `sum by (instance) (rate(node_disk_written_bytes_total{${selector}}[5m]))`,
  },
]

function buildRawMetricQuery(metricName: string, selector: string, _byInstance: boolean): string {
  // Her zaman selector ile calis, instance label kaybolmasin
  if (metricName.includes('_total') || metricName.endsWith('_total')) {
    return `sum by (instance) (rate(${metricName}{${selector}}[5m]))`
  }
  return `${metricName}{${selector}}`
}

const mapByInstance = (results: PromResult[]) => {
  const map: Record<string, number> = {}
  results.forEach((item) => {
    const instance = item.metric.instance || 'unknown'
    const value = Number(item.value?.[1] || 0)
    map[instance] = value
  })
  return map
}

const averageOfMap = (map: Record<string, number>) => {
  const values = Object.values(map)
  if (values.length === 0) return 0
  return values.reduce((sum, v) => sum + v, 0) / values.length
}

const sparklinePoints = (values: number[], width = 120, height = 32) => {
  if (values.length === 0) return ''
  const min = Math.min(...values)
  const max = Math.max(...values)
  const range = max - min || 1
  return values
    .map((v, i) => {
      const x = (i / (values.length - 1)) * width
      const y = height - ((v - min) / range) * height
      return `${x.toFixed(2)},${y.toFixed(2)}`
    })
    .join(' ')
}

const Sparkline: React.FC<{ values: number[]; color: string }> = ({ values, color }) => {
  const points = sparklinePoints(values)
  return (
    <svg width="120" height="32" viewBox="0 0 120 32">
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="2"
        points={points}
      />
    </svg>
  )
}

const MetricBar: React.FC<{ value: number; color: string }> = ({ value, color }) => {
  const pct = Math.max(0, Math.min(100, value))
  return (
    <div className="w-28 bg-slate-700 rounded-full h-2">
      <div className="h-2 rounded-full" style={{ width: `${pct}%`, backgroundColor: color }} />
    </div>
  )
}

/** Zaman serisi grafiği: birden fazla seri (instance) tek grafikte */
const CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#06b6d4']
const _TimeSeriesChart: React.FC<{
  title: string
  results: PromRangeResult[]
  unit?: string
  height?: number
  instanceLabels?: Record<string, string>
}> = ({ title, results, unit = '%', height = 200, instanceLabels = {} }) => {
  const { pointsBySeries, minVal, maxVal } = useMemo(() => {
    if (results.length === 0) {
      return { pointsBySeries: [] as { key: string; label: string; values: number[] }[], minVal: 0, maxVal: 100 }
    }
    const bySeries: { key: string; label: string; values: number[] }[] = results.map((r, i) => {
      const instance = r.metric?.instance ?? r.metric?.job ?? `series-${i}`
      const label = instanceLabels[instance] || instance
      const values = (r.values || []).map(([, v]) => Number(v ?? 0))
      return { key: String(instance), label, values }
    })
    const allVals = results.flatMap((r) => (r.values || []).map(([, v]) => Number(v ?? 0)))
    const minVal = allVals.length ? Math.min(...allVals, 0) : 0
    const maxVal = allVals.length ? Math.max(...allVals, 100) || 100 : 100
    return { pointsBySeries: bySeries, minVal, maxVal }
  }, [results, instanceLabels])

  const padding = { top: 16, right: 16, bottom: 28, left: 44 }
  const width = 600
  const chartWidth = width - padding.left - padding.right
  const chartHeight = height - padding.top - padding.bottom
  const range = maxVal - minVal || 1

  return (
    <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
      <div className="text-sm font-medium text-slate-300 mb-2">{title}</div>
      <svg width={width} height={height} className="overflow-visible">
        <text x={padding.left - 8} y={padding.top + chartHeight / 2} textAnchor="end" fill="#94a3b8" fontSize="10">
          {unit}
        </text>
        {[0.25, 0.5, 0.75].map((p) => (
          <line
            key={p}
            x1={padding.left}
            y1={padding.top + chartHeight * (1 - p)}
            x2={padding.left + chartWidth}
            y2={padding.top + chartHeight * (1 - p)}
            stroke="rgba(148,163,184,0.2)"
            strokeWidth="1"
          />
        ))}
        {pointsBySeries.map((series, idx) => {
          const color = CHART_COLORS[idx % CHART_COLORS.length]
          const len = series.values.length
          const pts = series.values
            .map((v, i) => {
              const x = padding.left + (len > 1 ? (i / (len - 1)) * chartWidth : 0)
              const y = padding.top + chartHeight - ((v - minVal) / range) * chartHeight
              return `${x},${y}`
            })
            .join(' ')
          return (
            <polyline key={series.key} fill="none" stroke={color} strokeWidth="2" points={pts} />
          )
        })}
      </svg>
      <div className="flex flex-wrap gap-3 mt-2">
        {pointsBySeries.map((s, i) => (
          <span key={s.key} className="flex items-center gap-1.5 text-xs text-slate-400">
            <span className="w-2 h-2 rounded-full" style={{ backgroundColor: CHART_COLORS[i % CHART_COLORS.length] }} />
            {s.label}
          </span>
        ))}
      </div>
    </div>
  )
}
void _TimeSeriesChart

/** Recharts ile enterprise görünümlü zaman serisi grafiği */
const ENTERPRISE_CHART_COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#8b5cf6', '#06b6d4']
const EnterpriseMetricChart: React.FC<{
  chartId?: string
  title: string
  results: PromRangeResult[]
  unit?: string
  height?: number
  instanceLabels?: Record<string, string>
  loading?: boolean
}> = ({ chartId = 'chart', title, results, unit = '', height = 280, instanceLabels = {}, loading }) => {
  const { chartData, seriesKeys } = useMemo(() => {
    if (!results.length) return { chartData: [], seriesKeys: [] as string[] }
    const keys = results.map((r) => r.metric?.instance ?? r.metric?.job ?? 'value')
    const timestamps = results[0]?.values?.map(([t]) => t) ?? []
    const data = timestamps.map((ts, i) => {
      const point: Record<string, number | string> = {
        time: new Date(ts * 1000).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit', second: '2-digit' }),
        _ts: ts,
      }
      results.forEach((r, idx) => {
        const key = keys[idx]
        const label = instanceLabels[key] || key
        const val = r.values?.[i]?.[1]
        point[label] = val != null ? Number(val) : 0
      })
      return point
    })
    const seriesKeysRes = results.map((_r, idx) => instanceLabels[keys[idx]] || keys[idx])
    return { chartData: data, seriesKeys: seriesKeysRes }
  }, [results, instanceLabels])

  if (loading) {
    return (
      <div className="bg-slate-800/80 border border-slate-600 rounded-xl shadow-lg overflow-hidden" style={{ height }}>
        <div className="p-4 border-b border-slate-600/50 flex items-center justify-between">
          <span className="text-sm font-semibold text-slate-200">{title}</span>
          <span className="text-xs text-slate-500">Yükleniyor...</span>
        </div>
        <div className="flex items-center justify-center flex-1 h-48 text-slate-500">Veri çekiliyor</div>
      </div>
    )
  }

  if (!chartData.length || !seriesKeys.length) {
    return (
      <div className="bg-slate-800/80 border border-slate-600 rounded-xl shadow-lg overflow-hidden" style={{ minHeight: height }}>
        <div className="p-4 border-b border-slate-600/50 flex items-center justify-between">
          <span className="text-sm font-semibold text-slate-200">{title}</span>
          {unit && <span className="text-xs text-slate-400">{unit}</span>}
        </div>
        <div className="flex items-center justify-center h-48 text-slate-500">Veri yok</div>
      </div>
    )
  }

  return (
    <div className="bg-slate-800/80 border border-slate-600 rounded-xl shadow-lg overflow-hidden" style={{ minHeight: height }}>
      <div className="p-4 border-b border-slate-600/50 flex items-center justify-between">
        <span className="text-sm font-semibold text-slate-200">{title}</span>
        {unit && <span className="text-xs text-slate-400">{unit}</span>}
      </div>
      <div className="p-3" style={{ height: height - 56 }}>
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 8, bottom: 8 }}>
            <defs>
              {seriesKeys.map((_, i) => (
                <linearGradient key={i} id={`fill-${chartId}-${i}`} x1="0" y1="0" x2="0" y2="1">
                  <stop offset="0%" stopColor={ENTERPRISE_CHART_COLORS[i % ENTERPRISE_CHART_COLORS.length]} stopOpacity={0.4} />
                  <stop offset="100%" stopColor={ENTERPRISE_CHART_COLORS[i % ENTERPRISE_CHART_COLORS.length]} stopOpacity={0} />
                </linearGradient>
              ))}
            </defs>
            <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.5} />
            <XAxis dataKey="time" stroke="#64748b" fontSize={10} tickLine={false} />
            <YAxis stroke="#64748b" fontSize={10} tickLine={false} tickFormatter={(v) => (Number(v) % 1 === 0 ? String(v) : Number(v).toFixed(2))} />
            <Tooltip
              contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: '8px' }}
              labelStyle={{ color: '#94a3b8' }}
              formatter={(value: number) => [unit ? `${Number(value).toFixed(2)} ${unit}` : Number(value).toFixed(2), '']}
              labelFormatter={(label) => `Saat: ${label}`}
            />
            <Legend wrapperStyle={{ fontSize: 11 }} formatter={(value) => <span className="text-slate-400">{value}</span>} />
            {seriesKeys.map((key, i) => (
              <Area
                key={key}
                type="monotone"
                dataKey={key}
                stroke={ENTERPRISE_CHART_COLORS[i % ENTERPRISE_CHART_COLORS.length]}
                strokeWidth={2}
                fill={`url(#fill-${chartId}-${i})`}
              />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

/** Real time modunda tüm veriler bu aralıkla (ms) yenilenir - "veri akar" */
const REAL_TIME_REFETCH_OPTIONS = [
  { label: '2s', value: 2000 },
  { label: '4s', value: 4000 },
  { label: '10s', value: 10000 },
  { label: '30s', value: 30000 },
  { label: '1dk', value: 60000 },
]
const DEFAULT_realTimeRefetchMs = 4000

const DEFAULT_CHART_METRICS = ['cpu', 'memory', 'disk', 'load']

/** Prometheus regex'te özel karakterleri kaçır (instance=~ için) */
function escapePrometheusRegex(s: string): string {
  return s
}

const LiveMetrics: React.FC = () => {
  const [selectedInstances, setSelectedInstances] = useState<string[]>([])
  const [realTimeRefetchMs, setRealTimeRefetchMs] = useState(DEFAULT_realTimeRefetchMs)
  const [instanceDropdownOpen, setInstanceDropdownOpen] = useState(false)
  const [instanceSearch, setInstanceSearch] = useState('')
  const instanceDropdownRef = useRef<HTMLDivElement>(null)
  const [timeRangeIndex, setTimeRangeIndex] = useState(0)
  const [realTimeMode, setRealTimeMode] = useState(false)
  const [chartSlots, setChartSlots] = useState<string[]>(() => [...DEFAULT_CHART_METRICS])
  const [hostFilter, setHostFilter] = useState('')

  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (instanceDropdownRef.current && !instanceDropdownRef.current.contains(e.target as Node)) {
        setInstanceDropdownOpen(false)
      }
    }
    document.addEventListener('mousedown', handleClickOutside)
    return () => document.removeEventListener('mousedown', handleClickOutside)
  }, [])

  const [sortKey, setSortKey] = useState<string>('hostname')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')

  const refetchIntervalInstant = realTimeMode ? realTimeRefetchMs : 10000
  const refetchIntervalSlow = realTimeMode ? realTimeRefetchMs : 15000

  const { data: instances = [] } = useQuery({
    queryKey: ['prometheus-instances', realTimeMode],
    queryFn: fetchInstances,
    refetchInterval: refetchIntervalSlow
  })

  const { data: instanceLabels = {} } = useQuery({
    queryKey: ['prometheus-instance-labels', realTimeMode],
    queryFn: fetchInstanceLabels,
    refetchInterval: realTimeMode ? realTimeRefetchMs : 30000
  })

  const { data: instanceUpStatus = {} } = useQuery({
    queryKey: ['prometheus-instance-up', realTimeMode],
    queryFn: fetchInstanceUpStatus,
    refetchInterval: realTimeMode ? realTimeRefetchMs : 15000
  })

  const { data: nodeMetricNames = [] } = useQuery({
    queryKey: ['prometheus-node-metric-names'],
    queryFn: fetchNodeExporterMetricNames,
    staleTime: 60000
  })

  const selector =
    selectedInstances.length === 0
      ? 'job="node-exporter"'
      : selectedInstances.length === 1
        ? `job="node-exporter",instance="${selectedInstances[0]}"`
        : `job="node-exporter",instance=~"${selectedInstances.map(escapePrometheusRegex).join('|')}"`

  const byInstance = selectedInstances.length !== 1
  const instanceQueryKey = selectedInstances.length === 0 ? 'all' : selectedInstances.slice().sort().join(',')

  /* Her zaman "avg by (instance)" kullan ki sonuçta instance etiketi kalsın; tek sunucuda da veri doğru eşlensin */
  const cpuQuery = `100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle",${selector}}[5m])) * 100)`

  const memoryQuery = `(1 - (node_memory_MemAvailable_bytes{${selector}} / node_memory_MemTotal_bytes{${selector}})) * 100`

  const diskQuery = `(1 - (node_filesystem_avail_bytes{mountpoint="/",${selector}} / node_filesystem_size_bytes{mountpoint="/",${selector}})) * 100`

  const loadQuery = `node_load1{${selector}}`

  const netRxQuery = `sum by (instance) (rate(node_network_receive_bytes_total{device!~"lo",${selector}}[5m]))`
  const netTxQuery = `sum by (instance) (rate(node_network_transmit_bytes_total{device!~"lo",${selector}}[5m]))`

  const effectiveRangeIndex = realTimeMode ? 0 : timeRangeIndex
  const rangeSeconds = TIME_RANGES[effectiveRangeIndex].value
  const stepSeconds = TIME_RANGES[effectiveRangeIndex].step
  const timeRangeLabel = TIME_RANGES[effectiveRangeIndex].label

  const getRangeQueryForMetricKey = (metricKey: string): string => {
    if (metricKey.startsWith('raw:')) {
      const rawName = metricKey.slice(4)
      return buildRawMetricQuery(rawName, selector, byInstance)
    }
    const preset = METRIC_PRESETS.find((p) => p.id === metricKey)
    return preset ? preset.buildRangeQuery(selector, byInstance) : ''
  }
  const getLabelForMetricKey = (metricKey: string): string => {
    if (metricKey.startsWith('raw:')) return metricKey.slice(4)
    const preset = METRIC_PRESETS.find((p) => p.id === metricKey)
    return preset ? preset.label : metricKey
  }
  const getUnitForMetricKey = (metricKey: string): string => {
    if (metricKey.startsWith('raw:')) return ''
    const preset = METRIC_PRESETS.find((p) => p.id === metricKey)
    return preset ? preset.unit : ''
  }

  const cpuRangeQuery = selectedInstances.length === 0
    ? `100 - (avg(rate(node_cpu_seconds_total{mode="idle",job="node-exporter"}[5m])) * 100)`
    : `100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle",${selector}}[5m])) * 100)`
  const memoryRangeQuery = selectedInstances.length === 0
    ? `(1 - (avg(node_memory_MemAvailable_bytes{job="node-exporter"}) / avg(node_memory_MemTotal_bytes{job="node-exporter"}))) * 100`
    : `(1 - (node_memory_MemAvailable_bytes{${selector}} / node_memory_MemTotal_bytes{${selector}})) * 100`
  const diskRangeQuery = selectedInstances.length === 0
    ? `(1 - (avg(node_filesystem_avail_bytes{mountpoint="/",job="node-exporter"}) / avg(node_filesystem_size_bytes{mountpoint="/",job="node-exporter"}))) * 100`
    : `(1 - (node_filesystem_avail_bytes{mountpoint="/",${selector}} / node_filesystem_size_bytes{mountpoint="/",${selector}})) * 100`

  const cpuChartRangeQuery = `100 - (avg by (instance) (rate(node_cpu_seconds_total{mode="idle",${selector}}[5m])) * 100)`
  const memoryChartRangeQuery = `(1 - (node_memory_MemAvailable_bytes{${selector}} / node_memory_MemTotal_bytes{${selector}})) * 100`
  const diskChartRangeQuery = `(1 - (node_filesystem_avail_bytes{mountpoint="/",${selector}} / node_filesystem_size_bytes{mountpoint="/",${selector}})) * 100`

  const { data: cpuResults = [], isLoading: cpuLoading } = useQuery({
    queryKey: ['prometheus-cpu', instanceQueryKey, realTimeMode],
    queryFn: () => fetchPrometheus(cpuQuery),
    refetchInterval: refetchIntervalInstant
  })

  const { data: memoryResults = [], isLoading: memoryLoading } = useQuery({
    queryKey: ['prometheus-memory', instanceQueryKey, realTimeMode],
    queryFn: () => fetchPrometheus(memoryQuery),
    refetchInterval: refetchIntervalInstant
  })

  const { data: diskResults = [], isLoading: diskLoading } = useQuery({
    queryKey: ['prometheus-disk', instanceQueryKey, realTimeMode],
    queryFn: () => fetchPrometheus(diskQuery),
    refetchInterval: refetchIntervalSlow
  })

  const { data: loadResults = [], isLoading: loadLoading } = useQuery({
    queryKey: ['prometheus-load', instanceQueryKey, realTimeMode],
    queryFn: () => fetchPrometheus(loadQuery),
    refetchInterval: refetchIntervalInstant
  })

  const { data: netRxResults = [] } = useQuery({
    queryKey: ['prometheus-net-rx', instanceQueryKey, realTimeMode],
    queryFn: () => fetchPrometheus(netRxQuery),
    refetchInterval: refetchIntervalSlow
  })

  const { data: netTxResults = [] } = useQuery({
    queryKey: ['prometheus-net-tx', instanceQueryKey, realTimeMode],
    queryFn: () => fetchPrometheus(netTxQuery),
    refetchInterval: refetchIntervalSlow
  })

  const refetchIntervalRange = realTimeMode ? realTimeRefetchMs : (rangeSeconds <= 900 ? 10000 : 30000)

  const { data: cpuRangeResults = [] } = useQuery({
    queryKey: ['prometheus-cpu-range', cpuRangeQuery, rangeSeconds, stepSeconds, realTimeMode],
    queryFn: () => fetchPrometheusRange(cpuRangeQuery, rangeSeconds, stepSeconds),
    refetchInterval: refetchIntervalRange
  })

  const { data: memoryRangeResults = [] } = useQuery({
    queryKey: ['prometheus-memory-range', memoryRangeQuery, rangeSeconds, stepSeconds, realTimeMode],
    queryFn: () => fetchPrometheusRange(memoryRangeQuery, rangeSeconds, stepSeconds),
    refetchInterval: refetchIntervalRange
  })

  const { data: diskRangeResults = [] } = useQuery({
    queryKey: ['prometheus-disk-range', diskRangeQuery, rangeSeconds, stepSeconds, realTimeMode],
    queryFn: () => fetchPrometheusRange(diskRangeQuery, rangeSeconds, stepSeconds),
    refetchInterval: refetchIntervalRange
  })

  const { data: _cpuChartRangeResults = [] } = useQuery({
    queryKey: ['prometheus-cpu-chart', instanceQueryKey, effectiveRangeIndex, rangeSeconds, stepSeconds, realTimeMode],
    queryFn: () => fetchPrometheusRange(cpuChartRangeQuery, rangeSeconds, stepSeconds),
    refetchInterval: refetchIntervalRange
  })

  const { data: _memoryChartRangeResults = [] } = useQuery({
    queryKey: ['prometheus-memory-chart', instanceQueryKey, effectiveRangeIndex, rangeSeconds, stepSeconds, realTimeMode],
    queryFn: () => fetchPrometheusRange(memoryChartRangeQuery, rangeSeconds, stepSeconds),
    refetchInterval: refetchIntervalRange
  })

  const { data: _diskChartRangeResults = [] } = useQuery({
    queryKey: ['prometheus-disk-chart', instanceQueryKey, effectiveRangeIndex, rangeSeconds, stepSeconds, realTimeMode],
    queryFn: () => fetchPrometheusRange(diskChartRangeQuery, rangeSeconds, stepSeconds),
    refetchInterval: refetchIntervalRange
  })

  const customSlot0Query = getRangeQueryForMetricKey(chartSlots[0] ?? DEFAULT_CHART_METRICS[0])
  const customSlot1Query = getRangeQueryForMetricKey(chartSlots[1] ?? DEFAULT_CHART_METRICS[1])
  const customSlot2Query = getRangeQueryForMetricKey(chartSlots[2] ?? DEFAULT_CHART_METRICS[2])
  const customSlot3Query = getRangeQueryForMetricKey(chartSlots[3] ?? DEFAULT_CHART_METRICS[3])

  const customChart0 = useQuery({
    queryKey: ['prometheus-custom-chart', 0, customSlot0Query, rangeSeconds, stepSeconds, realTimeMode],
    queryFn: () => fetchPrometheusRange(customSlot0Query, rangeSeconds, stepSeconds),
    refetchInterval: refetchIntervalRange,
    enabled: !!customSlot0Query
  })
  const customChart1 = useQuery({
    queryKey: ['prometheus-custom-chart', 1, customSlot1Query, rangeSeconds, stepSeconds, realTimeMode],
    queryFn: () => fetchPrometheusRange(customSlot1Query, rangeSeconds, stepSeconds),
    refetchInterval: refetchIntervalRange,
    enabled: !!customSlot1Query
  })
  const customChart2 = useQuery({
    queryKey: ['prometheus-custom-chart', 2, customSlot2Query, rangeSeconds, stepSeconds, realTimeMode],
    queryFn: () => fetchPrometheusRange(customSlot2Query, rangeSeconds, stepSeconds),
    refetchInterval: refetchIntervalRange,
    enabled: !!customSlot2Query
  })
  const customChart3 = useQuery({
    queryKey: ['prometheus-custom-chart', 3, customSlot3Query, rangeSeconds, stepSeconds, realTimeMode],
    queryFn: () => fetchPrometheusRange(customSlot3Query, rangeSeconds, stepSeconds),
    refetchInterval: refetchIntervalRange,
    enabled: !!customSlot3Query
  })
  const customChartResults = [customChart0.data ?? [], customChart1.data ?? [], customChart2.data ?? [], customChart3.data ?? []]
  const customChartLoading = [customChart0.isLoading, customChart1.isLoading, customChart2.isLoading, customChart3.isLoading]

  const setChartSlot = (index: number, metricKey: string) => {
    setChartSlots((prev) => {
      const next = [...prev]
      next[index] = metricKey
      return next
    })
  }

  const cpuMap = useMemo(() => mapByInstance(cpuResults), [cpuResults])
  const memoryMap = useMemo(() => mapByInstance(memoryResults), [memoryResults])
  const diskMap = useMemo(() => mapByInstance(diskResults), [diskResults])
  const loadMap = useMemo(() => mapByInstance(loadResults), [loadResults])
  const netRxMap = useMemo(() => mapByInstance(netRxResults), [netRxResults])
  const netTxMap = useMemo(() => mapByInstance(netTxResults), [netTxResults])

  const cpuTrend = useMemo(() => {
    const values = cpuRangeResults[0]?.values || []
    return values.map(([, v]) => Number(v || 0))
  }, [cpuRangeResults])
  const memoryTrend = useMemo(() => {
    const values = memoryRangeResults[0]?.values || []
    return values.map(([, v]) => Number(v || 0))
  }, [memoryRangeResults])
  const diskTrend = useMemo(() => {
    const values = diskRangeResults[0]?.values || []
    return values.map(([, v]) => Number(v || 0))
  }, [diskRangeResults])

  const rows = useMemo(() => {
    const list = selectedInstances.length === 0 ? instances : selectedInstances
    return list.map((instance) => ({
      instance,
      hostname: instanceLabels[instance] || instance,
      cpu: cpuMap[instance],
      memory: memoryMap[instance],
      disk: diskMap[instance],
      load: loadMap[instance],
      netRx: netRxMap[instance],
      netTx: netTxMap[instance]
    }))
  }, [instances, selectedInstances, instanceLabels, cpuMap, memoryMap, diskMap, loadMap, netRxMap, netTxMap])

  const filteredRows = useMemo(() => {

    return rows.filter((row) => {
      const matchesHost = !hostFilter || row.hostname.toLowerCase().includes(hostFilter.toLowerCase())

      return matchesHost
    })
  }, [rows, hostFilter])

  const sortedRows = useMemo(() => {
    const copy = [...filteredRows]
    copy.sort((a, b) => {
      let aVal: number | string = ''
      let bVal: number | string = ''
      switch (sortKey) {
        case 'hostname':
          aVal = a.hostname
          bVal = b.hostname
          break
        case 'cpu':
          aVal = a.cpu ?? 0
          bVal = b.cpu ?? 0
          break
        case 'memory':
          aVal = a.memory ?? 0
          bVal = b.memory ?? 0
          break
        case 'disk':
          aVal = a.disk ?? 0
          bVal = b.disk ?? 0
          break
        case 'load':
          aVal = a.load ?? 0
          bVal = b.load ?? 0
          break
        case 'netRx':
          aVal = a.netRx ?? 0
          bVal = b.netRx ?? 0
          break
        case 'netTx':
          aVal = a.netTx ?? 0
          bVal = b.netTx ?? 0
          break
        default:
          aVal = a.hostname
          bVal = b.hostname
      }
      if (typeof aVal === 'number' && typeof bVal === 'number') {
        return sortDirection === 'asc' ? aVal - bVal : bVal - aVal
      }
      return sortDirection === 'asc'
        ? String(aVal).localeCompare(String(bVal))
        : String(bVal).localeCompare(String(aVal))
    })
    return copy
  }, [filteredRows, sortKey, sortDirection])

  const toggleSort = (key: string) => {
    if (sortKey === key) {
      setSortDirection((prev) => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDirection('asc')
    }
  }

  const getSortIcon = (key: string) => {
    if (sortKey !== key) return '↕'
    return sortDirection === 'asc' ? '▲' : '▼'
  }

  const isLoading = cpuLoading || memoryLoading || diskLoading || loadLoading

  return (
    <div className="space-y-6">
      <div className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4">
        <div>
          <h2 className="text-xl font-semibold text-white">Canlı Metrikler</h2>
          <p className="text-sm text-slate-400">Prometheus üzerinden gerçek zamanlı Node Exporter verileri</p>
        </div>
        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => setRealTimeMode((prev) => !prev)}
            className={`flex items-center gap-2 rounded-lg px-4 py-2.5 font-medium text-sm transition-all focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-offset-slate-900 ${
              realTimeMode
                ? 'bg-emerald-600 text-white shadow-lg shadow-emerald-500/25 focus:ring-emerald-500'
                : 'bg-slate-700 text-slate-300 hover:bg-slate-600 focus:ring-slate-500'
            }`}
          >
            {realTimeMode ? (
              <>
                <span className="relative flex h-2 w-2">
                  <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-white opacity-75" />
                  <span className="relative inline-flex h-2 w-2 rounded-full bg-white" />
                </span>
                Veri akıyor
              </>
            ) : (
              <>Real time</>
            )}
          </button>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-400 whitespace-nowrap">Zaman aralığı:</span>
            <select
              value={timeRangeIndex}
              onChange={(e) => setTimeRangeIndex(Number(e.target.value))}
              disabled={realTimeMode}
              className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:ring-2 focus:ring-blue-500 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {TIME_RANGES.map((r, i) => (
                <option key={r.value} value={i}>{r.label}</option>
              ))}
            </select>
            {realTimeMode && (
              <span className="text-xs text-emerald-400">(Son 15 dk)</span>
            )}
          </div>
          <div className="relative" ref={instanceDropdownRef}>
            <button
              type="button"
              onClick={() => setInstanceDropdownOpen((prev) => !prev)}
              className="flex items-center gap-2 min-w-[220px] bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white text-left hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <span className="truncate">
                {selectedInstances.length === 0
                  ? 'Tüm Sunucular'
                  : `${selectedInstances.length} sunucu seçili`}
              </span>
              <span className="ml-auto text-slate-500 shrink-0">{instanceDropdownOpen ? '▲' : '▼'}</span>
            </button>
            {instanceDropdownOpen && (
              <div className="absolute top-full left-0 mt-1 w-80 max-h-72 overflow-hidden bg-slate-800 border border-slate-600 rounded-xl shadow-xl z-50 flex flex-col">
                <div className="p-2 border-b border-slate-700">
                  <input
                    type="text"
                    value={instanceSearch}
                    onChange={(e) => setInstanceSearch(e.target.value)}
                    placeholder="Sunucu veya hostname ara..."
                    className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
                <div className="flex items-center gap-2 p-2 border-b border-slate-700">
                  <button
                    type="button"
                    onClick={() => setSelectedInstances([])}
                    className="text-xs text-slate-400 hover:text-slate-300 px-2 py-1 rounded"
                  >
                    Tümünü kaldır
                  </button>
                  <button
                    type="button"
                    onClick={() => {
                      const filtered = instances.filter((instance) => {
                        if (!instanceSearch.trim()) return true
                        const q = instanceSearch.toLowerCase()
                        const host = (instanceLabels[instance] || instance).toLowerCase()
                        return instance.toLowerCase().includes(q) || host.includes(q)
                      })
                      setSelectedInstances(filtered)
                    }}
                    className="text-xs text-blue-400 hover:text-blue-300 px-2 py-1 rounded"
                  >
                    Filtreyi seç
                  </button>
                  <span className="text-xs text-slate-500 ml-auto">
                    {instances.filter((instance) => {
                      if (!instanceSearch.trim()) return true
                      const q = instanceSearch.toLowerCase()
                      const host = (instanceLabels[instance] || instance).toLowerCase()
                      return instance.toLowerCase().includes(q) || host.includes(q)
                    }).length} sunucu
                  </span>
                </div>
                <div className="overflow-y-auto flex-1 p-2">
                  {instances
                    .filter((instance) => {
                      if (!instanceSearch.trim()) return true
                      const q = instanceSearch.toLowerCase()
                      const host = (instanceLabels[instance] || instance).toLowerCase()
                      return instance.toLowerCase().includes(q) || host.includes(q)
                    })
                    .map((instance) => (
                      <label
                        key={instance}
                        className="flex items-center gap-3 px-3 py-2 rounded-lg cursor-pointer hover:bg-slate-700/50"
                      >
                        <input
                          type="checkbox"
                          checked={selectedInstances.includes(instance)}
                          onChange={() => {
                            setSelectedInstances((prev) =>
                              prev.includes(instance)
                                ? prev.filter((i) => i !== instance)
                                : [...prev, instance]
                            )
                          }}
                          className="h-4 w-4 text-blue-500 rounded border-slate-600 bg-slate-800 focus:ring-blue-500"
                        />
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-1.5">
                            <span className={`w-1.5 h-1.5 rounded-full flex-shrink-0 ${instanceUpStatus[instance] ? 'bg-green-400' : 'bg-red-400'}`} />
                            <span className={`text-sm font-medium truncate ${instanceUpStatus[instance] ? 'text-white' : 'text-slate-400'}`}>
                              {instanceLabels[instance] || instance}
                            </span>
                            {!instanceUpStatus[instance] && (
                              <span className="text-xs text-red-400/70 flex-shrink-0">veri yok</span>
                            )}
                          </div>
                          {instanceLabels[instance] && (
                            <span className="text-xs text-slate-500 font-mono truncate block pl-3">{instance}</span>
                          )}
                        </div>
                      </label>
                    ))}
                </div>
              </div>
            )}
          </div>
          <input
            type="text"
            placeholder="Hostname filtre..."
            value={hostFilter}
            onChange={(e) => setHostFilter(e.target.value)}
            className="w-48 bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500"
          />

          {realTimeMode ? (
            <div className="flex items-center gap-2">
              <span className="text-xs text-slate-400 whitespace-nowrap">Yenileme:</span>
              <select
                value={realTimeRefetchMs}
                onChange={(e) => setRealTimeRefetchMs(Number(e.target.value))}
                className="bg-slate-800 border border-slate-700 rounded-lg px-2 py-1.5 text-white text-xs focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                {REAL_TIME_REFETCH_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value}>{opt.label}</option>
                ))}
              </select>
            </div>
          ) : (
            <span className="text-xs text-slate-400">
              {timeRangeIndex === 0
                ? 'Yenileme: 10s'
                : `Yenileme: 30s · ${timeRangeLabel}`}
            </span>
          )}
        </div>
      </div>

      {/* Down sunucu uyarısı */}
      {selectedInstances.length > 0 && selectedInstances.some(i => instanceUpStatus[i] === false) && (
        <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl px-4 py-3 flex items-start gap-3">
          <span className="text-amber-400 text-lg mt-0.5">⚠️</span>
          <div>
            <p className="text-amber-300 text-sm font-medium">Seçili sunucularda veri yok</p>
            <p className="text-amber-400/70 text-xs mt-0.5">
              {selectedInstances.filter(i => instanceUpStatus[i] === false).map(i => instanceLabels[i] || i).join(', ')} — Node Exporter çalışmıyor veya erişilemiyor. Sunucular sayfasından başlatabilirsiniz.
            </p>
          </div>
        </div>
      )}

      {/* Summary Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-5 gap-4">
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
          <div className="text-xs text-slate-400">CPU Ortalama ({timeRangeLabel})</div>
          <div className="flex items-center justify-between">
            <div className="text-2xl font-semibold text-white">
              {averageOfMap(cpuMap).toFixed(2)}%
            </div>
            <Sparkline values={cpuTrend} color="#60a5fa" />
          </div>
        </div>
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
          <div className="text-xs text-slate-400">Memory Ortalama ({timeRangeLabel})</div>
          <div className="flex items-center justify-between">
            <div className="text-2xl font-semibold text-white">
              {averageOfMap(memoryMap).toFixed(2)}%
            </div>
            <Sparkline values={memoryTrend} color="#34d399" />
          </div>
        </div>
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
          <div className="text-xs text-slate-400">Disk (/) ({timeRangeLabel})</div>
          <div className="flex items-center justify-between">
            <div className="text-2xl font-semibold text-white">
              {averageOfMap(diskMap).toFixed(2)}%
            </div>
            <Sparkline values={diskTrend} color="#fbbf24" />
          </div>
        </div>
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
          <div className="text-xs text-slate-400">Load Ortalama</div>
          <div className="text-2xl font-semibold text-white">
            {averageOfMap(loadMap).toFixed(2)}
          </div>
        </div>
        <div className="bg-slate-800 border border-slate-700 rounded-xl p-4">
          <div className="text-xs text-slate-400">Network Ortalama</div>
          <div className="text-sm text-slate-300">
            RX: {averageOfMap(netRxMap).toFixed(0)} B/s
          </div>
          <div className="text-sm text-slate-300">
            TX: {averageOfMap(netTxMap).toFixed(0)} B/s
          </div>
        </div>
      </div>

      {/* Özelleştirilebilir grafikler — kullanıcı Node Exporter metriklerini seçer */}
      <div className="space-y-4">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <h3 className="text-lg font-semibold text-white">
            Özelleştirilebilir grafikler
          </h3>
          <p className="text-sm text-slate-400">
            Her grafik için Node Exporter metriklerinden birini seçin. Preset veya ham metrik adı kullanabilirsiniz. — {timeRangeLabel}
          </p>
        </div>
        <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
          {[0, 1, 2, 3].map((slotIndex) => (
            <div key={slotIndex} className="space-y-2">
              <div className="flex items-center gap-2 flex-wrap">
                <label className="text-xs font-medium text-slate-400 whitespace-nowrap">
                  Grafik {slotIndex + 1} metrik:
                </label>
                <select
                  value={chartSlots[slotIndex] ?? DEFAULT_CHART_METRICS[slotIndex]}
                  onChange={(e) => setChartSlot(slotIndex, e.target.value)}
                  className="bg-slate-700 border border-slate-600 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:ring-2 focus:ring-blue-500 min-w-[220px]"
                >
                  <optgroup label="Preset metrikler">
                    {METRIC_PRESETS.map((p) => (
                      <option key={p.id} value={p.id}>{p.label}</option>
                    ))}
                  </optgroup>
                  {nodeMetricNames.length > 0 && (
                    <optgroup label="Node Exporter (ham metrik)">
                      {nodeMetricNames.map((name) => (
                        <option key={name} value={`raw:${name}`}>{name}</option>
                      ))}
                    </optgroup>
                  )}
                </select>
              </div>
              <EnterpriseMetricChart
                chartId={`slot-${slotIndex}`}
                title={getLabelForMetricKey(chartSlots[slotIndex] ?? DEFAULT_CHART_METRICS[slotIndex])}
                results={customChartResults[slotIndex]}
                unit={getUnitForMetricKey(chartSlots[slotIndex] ?? DEFAULT_CHART_METRICS[slotIndex])}
                height={280}
                instanceLabels={instanceLabels}
                loading={customChartLoading[slotIndex]}
              />
            </div>
          ))}
        </div>
      </div>

      {/* Table */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full">
            <thead>
              <tr className="bg-slate-900/50">
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <button onClick={() => toggleSort('hostname')} className="flex items-center gap-1">
                    Hostname <span className="text-[10px]">{getSortIcon('hostname')}</span>
                  </button>
                </th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <button onClick={() => toggleSort('cpu')} className="flex items-center gap-1">
                    CPU <span className="text-[10px]">{getSortIcon('cpu')}</span>
                  </button>
                </th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <button onClick={() => toggleSort('memory')} className="flex items-center gap-1">
                    Memory <span className="text-[10px]">{getSortIcon('memory')}</span>
                  </button>
                </th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <button onClick={() => toggleSort('disk')} className="flex items-center gap-1">
                    Disk (/) <span className="text-[10px]">{getSortIcon('disk')}</span>
                  </button>
                </th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <button onClick={() => toggleSort('load')} className="flex items-center gap-1">
                    Load <span className="text-[10px]">{getSortIcon('load')}</span>
                  </button>
                </th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <button onClick={() => toggleSort('netRx')} className="flex items-center gap-1">
                    Net RX <span className="text-[10px]">{getSortIcon('netRx')}</span>
                  </button>
                </th>
                <th className="px-6 py-4 text-left text-xs font-medium text-slate-400 uppercase tracking-wider">
                  <button onClick={() => toggleSort('netTx')} className="flex items-center gap-1">
                    Net TX <span className="text-[10px]">{getSortIcon('netTx')}</span>
                  </button>
                </th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {sortedRows.map((row) => (
                <tr key={row.instance} className="hover:bg-slate-700/30 transition-colors">
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-white">
                    <div className="font-medium">{row.hostname}</div>
                    <div className="text-xs text-slate-400 font-mono">{row.instance}</div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-3">
                      <MetricBar value={row.cpu ?? 0} color="#60a5fa" />
                      <span className="text-sm text-slate-200">{(row.cpu ?? 0).toFixed(2)}%</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-3">
                      <MetricBar value={row.memory ?? 0} color="#34d399" />
                      <span className="text-sm text-slate-200">{(row.memory ?? 0).toFixed(2)}%</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap">
                    <div className="flex items-center gap-3">
                      <MetricBar value={row.disk ?? 0} color="#fbbf24" />
                      <span className="text-sm text-slate-200">{(row.disk ?? 0).toFixed(2)}%</span>
                    </div>
                  </td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-200">{(row.load ?? 0).toFixed(2)}</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-200">{(row.netRx ?? 0).toFixed(0)} B/s</td>
                  <td className="px-6 py-4 whitespace-nowrap text-sm text-slate-200">{(row.netTx ?? 0).toFixed(0)} B/s</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        {sortedRows.length === 0 && (
          <div className="text-center py-12 text-slate-500">
            {isLoading ? 'Metrikler yükleniyor...' : 'Metrik bulunamadı'}
          </div>
        )}
      </div>
    </div>
  )
}

export default LiveMetrics
