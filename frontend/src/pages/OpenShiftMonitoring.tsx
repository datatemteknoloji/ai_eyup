/**
 * OpenShift Monitoring — Virt Monitoring eşleniği.
 * Cluster seçici · Node/Pod/VM · overlay grafikler · Timescale serileri.
 * Prometheus modu: DCGM / kubevirt (ayrı UI).
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { Activity, Maximize2, Search, X } from 'lucide-react'
import {
  Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'
import { MonitoringShell, type MonitoringDataMode } from '../components/monitoring/MonitoringShell'
import { OcpPromView } from '../components/monitoring/OcpPromView'

const RANGES = ['15m', '30m', '1h', '2h', '8h', '24h', '7d', '30d'] as const
const MAX_SEL = 8
const LS_CLUSTER = 'ainew.ocp.monitoring.clusterId'
const COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ec4899',
  '#06b6d4', '#a3e635', '#f97316', '#38bdf8',
]
const DEFAULT_METRICS: Record<string, string[]> = {
  node: ['cpu_pct', 'memory_pct', 'cpu_used_cores', 'memory_used_gb'],
  pod: ['cpu_used_cores', 'memory_used_gb', 'restarts', 'cpu_pct'],
  vm: ['cpu_used_cores', 'memory_used_gb', 'cpu_pct', 'memory_pct'],
}

type Kind = 'node' | 'pod' | 'vm'
type SeriesPoint = { t: string | null; v: number | null }
type SeriesResp = {
  ok: boolean
  unit?: string
  metric?: string
  as_of?: string | null
  series: { name: string; ref?: string; points: SeriesPoint[]; outside_window?: boolean }[]
  note?: string
}

const healthCls: Record<string, string> = {
  healthy: 'text-emerald-400',
  warning: 'text-amber-400',
  critical: 'text-red-400',
  unknown: 'text-slate-400',
  connected: 'text-emerald-400',
  partial: 'text-amber-400',
  missing: 'text-slate-400',
}

function tone(v?: string | null) {
  return healthCls[(v || '').toLowerCase()] || 'text-slate-300'
}

function deltaTxt(v?: number | null) {
  if (v == null) return '—'
  const sign = v > 0 ? '+' : ''
  return `${sign}${v}`
}

function deltaCls(v?: number | null) {
  if (v == null) return 'text-slate-500'
  if (v > 0.3) return 'text-amber-400'
  if (v < -0.3) return 'text-emerald-400'
  return 'text-slate-400'
}

const METRIC_LABEL: Record<string, string> = {
  cpu_pct: 'CPU %',
  memory_pct: 'Memory %',
  cpu_used_cores: 'CPU (cores)',
  memory_used_gb: 'Memory (GB)',
  restarts: 'Restarts',
}

function Panel({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-cyber-card border border-white/[0.06] rounded-lg px-3 py-2 ${className}`}>{children}</div>
  )
}

function OcpChart({
  title, unit, series, colorMap, empty, height = 260,
}: {
  title: string
  unit: string
  series: { name: string; ref?: string; points: SeriesPoint[] }[]
  colorMap: Record<string, string>
  empty: string
  height?: number
}) {
  const data = useMemo(() => {
    const map = new Map<string, Record<string, number | string | null>>()
    for (const s of series) {
      const key = s.ref || s.name
      for (const p of s.points || []) {
        if (!p.t) continue
        const row = map.get(p.t) || { t: p.t }
        row[key] = p.v
        map.set(p.t, row)
      }
    }
    return Array.from(map.values()).sort((a, b) => String(a.t).localeCompare(String(b.t)))
  }, [series])

  if (!series.length || !data.length) {
    return (
      <div className="h-[260px] flex items-center justify-center text-slate-500 text-sm px-4 text-center">
        {empty}
      </div>
    )
  }

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis
            dataKey="t"
            tick={{ fill: '#64748b', fontSize: 10 }}
            tickFormatter={(v) => {
              try {
                const d = new Date(String(v))
                return `${d.getHours().toString().padStart(2, '0')}:${d.getMinutes().toString().padStart(2, '0')}`
              } catch {
                return String(v).slice(11, 16)
              }
            }}
          />
          <YAxis tick={{ fill: '#64748b', fontSize: 10 }} width={48} unit={unit ? ` ${unit}` : ''} />
          <Tooltip
            contentStyle={{ background: '#0d1422', border: '1px solid #1e293b', borderRadius: 8, fontSize: 12 }}
            labelFormatter={(v) => {
              try { return new Date(String(v)).toLocaleString('tr-TR') } catch { return String(v) }
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {series.map((s, i) => {
            const key = s.ref || s.name
            return (
              <Area
                key={key}
                type="monotone"
                dataKey={key}
                name={s.name}
                stroke={colorMap[key] || COLORS[i % COLORS.length]}
                fill={colorMap[key] || COLORS[i % COLORS.length]}
                fillOpacity={0.12}
                strokeWidth={2}
                dot={false}
                connectNulls
              />
            )
          })}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

const OpenShiftMonitoring: React.FC<{
  embedded?: boolean
  sourceId?: string
  hubLeading?: React.ReactNode
  onDataModeChange?: (mode: MonitoringDataMode) => void
}> = ({
  embedded = false,
  sourceId,
  hubLeading,
  onDataModeChange,
}) => {
  const t = useT()
  const [kind, setKind] = useState<Kind>('node')
  const [selected, setSelected] = useState<string[]>([])
  const [range, setRange] = useState('2h')
  const [slots, setSlots] = useState<string[]>(DEFAULT_METRICS.node)
  const [search, setSearch] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const [labels, setLabels] = useState<Record<string, string>>({})
  const [fullscreen, setFullscreen] = useState<number | null>(null)
  const pickerRef = useRef<HTMLDivElement>(null)
  const [clusterId, setClusterId] = useState<number | null>(() => {
    const raw = localStorage.getItem(LS_CLUSTER)
    const n = raw ? Number(raw) : NaN
    return Number.isFinite(n) ? n : null
  })
  const [dataMode, setDataMode] = useState<MonitoringDataMode>(() => {
    return (localStorage.getItem('ainew.ocp.monitoring.mode') as MonitoringDataMode) || 'api'
  })

  const { data: monSettings } = useQuery({
    queryKey: ['general-settings', 'ocp-mon'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/settings/`)
      if (!r.ok) return { monitoring_sources: [] as { binding: string }[] }
      return r.json()
    },
    staleTime: 60_000,
  })
  const promConfigured = (monSettings?.monitoring_sources || []).some(
    (s: { binding: string }) => s.binding === 'openshift',
  )
  useEffect(() => {
    if (promConfigured && dataMode === 'api' && !localStorage.getItem('ainew.ocp.monitoring.mode')) {
      setDataMode('prometheus')
    }
  }, [promConfigured, dataMode])
  useEffect(() => {
    localStorage.setItem('ainew.ocp.monitoring.mode', dataMode)
    onDataModeChange?.(dataMode)
  }, [dataMode, onDataModeChange])

  useEffect(() => {
    setSlots([...DEFAULT_METRICS[kind]])
    setSelected([])
    setSearch('')
    setLabels({})
  }, [kind, clusterId])

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setPickerOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const clusters = useQuery({
    queryKey: ['openshift-clusters'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters`)
      if (!r.ok) return []
      const body = await r.json()
      return Array.isArray(body?.clusters) ? body.clusters : []
    },
    staleTime: 30_000,
  })

  useEffect(() => {
    const list = clusters.data || []
    if (!list.length) {
      setClusterId(null)
      return
    }
    if (!clusterId || !list.some((c: { id: number }) => c.id === clusterId)) {
      const next = list[0].id
      setClusterId(next)
      localStorage.setItem(LS_CLUSTER, String(next))
    }
  }, [clusters.data, clusterId])

  const selectCluster = (id: number) => {
    setClusterId(id)
    localStorage.setItem(LS_CLUSTER, String(id))
  }

  const overview = useQuery({
    queryKey: ['ocp-monitoring-overview', clusterId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/monitoring/overview?cluster_id=${clusterId}`)
      if (!r.ok) throw new Error(t('ocpm_overview_fail'))
      return r.json()
    },
    enabled: !!clusterId,
    refetchInterval: 60_000,
  })

  const metrics = useQuery({
    queryKey: ['ocp-monitoring-metrics', kind],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/monitoring/metrics?kind=${kind}`)
      if (!r.ok) throw new Error('metrics')
      return r.json()
    },
    staleTime: 300_000,
  })

  const objects = useQuery({
    queryKey: ['ocp-monitoring-objects', kind, clusterId, search],
    queryFn: async () => {
      const p = new URLSearchParams({ kind, limit: '200', cluster_id: String(clusterId) })
      if (search.trim()) p.set('q', search.trim())
      const r = await fetch(`${API_BASE_URL}/openshift/monitoring/objects?${p}`)
      if (!r.ok) throw new Error('objects')
      return r.json()
    },
    enabled: pickerOpen && !!clusterId,
    staleTime: 30_000,
  })

  const filteredObjects = objects.data?.items || []
  const colorMap = useMemo(() => {
    const m: Record<string, string> = {}
    selected.forEach((n, i) => { m[n] = COLORS[i % COLORS.length] })
    return m
  }, [selected])

  const hasSel = selected.length > 0
  const metricList: { id: string; unit: string }[] = metrics.data?.metrics || []
  const unitOf = (id: string) => metricList.find((m) => m.id === id)?.unit || ''
  const namesKey = selected.join(',')

  const fetchSeries = async (metric: string): Promise<SeriesResp> => {
    const p = new URLSearchParams({
      cluster_id: String(clusterId),
      kind,
      names: namesKey,
      metric,
      range,
    })
    const r = await fetch(`${API_BASE_URL}/openshift/monitoring/series?${p}`)
    if (!r.ok) throw new Error('series')
    return r.json()
  }

  const series0 = useQuery({
    queryKey: ['ocp-mon-series', clusterId, kind, namesKey, slots[0], range, 0],
    queryFn: () => fetchSeries(slots[0]),
    enabled: hasSel && !!slots[0] && !!clusterId,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
  const series1 = useQuery({
    queryKey: ['ocp-mon-series', clusterId, kind, namesKey, slots[1], range, 1],
    queryFn: () => fetchSeries(slots[1]),
    enabled: hasSel && !!slots[1] && !!clusterId,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
  const series2 = useQuery({
    queryKey: ['ocp-mon-series', clusterId, kind, namesKey, slots[2], range, 2],
    queryFn: () => fetchSeries(slots[2]),
    enabled: hasSel && !!slots[2] && !!clusterId,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
  const series3 = useQuery({
    queryKey: ['ocp-mon-series', clusterId, kind, namesKey, slots[3], range, 3],
    queryFn: () => fetchSeries(slots[3]),
    enabled: hasSel && !!slots[3] && !!clusterId,
    staleTime: 30_000,
    refetchInterval: 60_000,
  })
  const seriesQueries = [series0, series1, series2, series3]

  const ov = overview.data
  const health = ov?.health
  const src = ov?.data_source
  const current = (clusters.data || []).find((c: { id: number }) => c.id === clusterId)

  const objectLabel = (o: { id?: string; name?: string; namespace?: string; role?: string }) => {
    if (o.namespace) return `${o.namespace}/${o.name}`
    if (o.role) return `${o.name} (${o.role})`
    return o.name || o.id || ''
  }

  const toggle = (id: string, label?: string) => {
    if (label) setLabels((prev) => ({ ...prev, [id]: label }))
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= MAX_SEL) return prev
      return [...prev, id]
    })
  }

  const seriesColorMap = useMemo(() => {
    const m: Record<string, string> = {}
    selected.forEach((id, i) => {
      m[id] = COLORS[i % COLORS.length]
      // chart dataKey may be ref
      m[labels[id] || id] = COLORS[i % COLORS.length]
    })
    // map by series ref from responses
    for (const q of seriesQueries) {
      for (const s of q.data?.series || []) {
        const key = s.ref || s.name
        const idx = selected.indexOf(s.ref || '')
        if (idx >= 0) m[key] = COLORS[idx % COLORS.length]
        else if (!m[key]) m[key] = COLORS[Object.keys(m).length % COLORS.length]
      }
    }
    return m
  }, [selected, labels, series0.data, series1.data, series2.data, series3.data])

  return (
    <MonitoringShell
      title={t('ocpm_title')}
      subtitle={dataMode === 'prometheus' ? t('ocpm_subtitle_prom') : t('ocpm_subtitle')}
      mode={dataMode}
      onModeChange={setDataMode}
      prometheusConfigured={promConfigured}
      embedded={embedded}
      hubLeading={hubLeading}
      extraHeader={
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 flex-1 min-w-0">
          <Link to="/openshift" className="text-blue-400 hover:underline whitespace-nowrap">{t('nav_inventory')}</Link>
          <Link to="/openshift/chat" className="text-blue-400 hover:underline whitespace-nowrap">{t('nav_assistant')}</Link>
          {dataMode === 'api' && (
            <>
              <span className="text-slate-600 hidden sm:inline">|</span>
              <span className={`font-medium whitespace-nowrap ${tone(src?.state)}`}>
                metrics.k8s.io · {src?.state || '—'}
              </span>
              <span className="text-slate-500 whitespace-nowrap hidden md:inline">
                {src?.last_sample
                  ? `${t('ocpm_last_sample')}: ${new Date(src.last_sample).toLocaleString('tr-TR')}`
                  : ''}
                {src?.age_min != null ? ` · ${src.age_min} dk` : ''}
              </span>
              {src?.stale && <span className="text-amber-400">{t('ocpm_stale')}</span>}
              {!src?.metrics_available && src && (
                <span className="text-amber-400">{t('ocpm_metrics_off')}</span>
              )}
              {(clusters.data || []).length > 0 && (
                <>
                  <span className="text-slate-600 hidden sm:inline">|</span>
                  <span className="text-[10px] text-slate-500 uppercase tracking-wider font-bold">Cluster</span>
                  <div className="flex flex-wrap gap-1">
                    {(clusters.data || []).map((c: { id: number; name: string; status?: string; version?: string }) => {
                      const on = c.id === clusterId
                      return (
                        <button
                          key={c.id}
                          type="button"
                          onClick={() => selectCluster(c.id)}
                          className={`rounded-md border px-2 py-0.5 text-left transition-colors ${
                            on ? 'border-blue-500/40 bg-blue-500/10' : 'border-white/[0.06] hover:border-white/[0.12]'
                          }`}
                        >
                          <span className="text-xs text-white font-medium">{c.name}</span>
                          <span className="text-[10px] text-slate-500 font-mono ml-1.5">
                            {c.version || '—'} · {c.status || '—'}
                          </span>
                        </button>
                      )
                    })}
                  </div>
                </>
              )}
            </>
          )}
        </div>
      }
    >
      {dataMode === 'prometheus' ? (
        <OcpPromView sourceId={sourceId} />
      ) : (
    <div className="space-y-3">
      {overview.isError && (
        <div className="text-sm text-red-400">{t('ocpm_overview_fail')}</div>
      )}

      {!clusters.isLoading && (clusters.data || []).length === 0 && (
        <Panel className="text-center py-8">
          <p className="text-sm text-slate-300">{t('ocp_no_cluster')}</p>
          <Link to="/integrations/openshift" className="inline-flex mt-3 text-xs px-4 py-2 rounded-lg bg-blue-600 text-white">
            {t('ocp_go_integrations')}
          </Link>
        </Panel>
      )}

      {clusterId && (
        <>
          <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
            {[
              { label: t('ocpm_health'), value: health?.label, cls: tone(health?.grade) },
              { label: t('ocpm_healthy'), value: health?.hosts?.healthy ?? '—', cls: 'text-emerald-400' },
              { label: t('ocpm_warning'), value: health?.hosts?.warning ?? '—', cls: 'text-amber-400' },
              { label: t('ocpm_critical'), value: health?.hosts?.critical ?? '—', cls: 'text-red-400' },
              { label: t('ocpm_unknown'), value: health?.hosts?.unknown ?? '—', cls: 'text-slate-400' },
              { label: t('ocpm_availability'), value: health?.availability_pct != null ? `${health.availability_pct}%` : '—' },
            ].map((k) => (
              <Panel key={k.label}>
                <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">{k.label}</div>
                <div className={`text-base font-semibold mt-0.5 ${k.cls || 'text-white'}`}>{k.value}</div>
              </Panel>
            ))}
          </div>

          <Panel>
            <div className="flex flex-wrap items-center gap-2 mb-3">
              <Activity size={14} className="text-blue-400" />
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">{t('ocpm_charts')}</div>
              {current?.name && (
                <span className="text-xs text-slate-400 font-mono">{current.name}</span>
              )}
              <div className="flex rounded-md border border-white/[0.06] overflow-hidden">
                {(['node', 'pod', 'vm'] as Kind[]).map((k) => (
                  <button
                    key={k}
                    type="button"
                    onClick={() => setKind(k)}
                    className={`px-2.5 py-1 text-xs ${kind === k ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}
                  >
                    {t(`ocpm_axis_${k}` as any)}
                  </button>
                ))}
              </div>
              <select
                value={range}
                onChange={(e) => setRange(e.target.value)}
                className="bg-[#0d1422] border border-white/[0.06] rounded-md px-2 py-1 text-xs text-white"
              >
                {RANGES.map((r) => (
                  <option key={r} value={r}>{t(`ocpm_range_${r}` as any)}</option>
                ))}
              </select>
              <div className="relative" ref={pickerRef}>
                <button
                  type="button"
                  onClick={() => setPickerOpen((v) => !v)}
                  className="min-w-[220px] bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-1.5 text-sm text-left text-white"
                >
                  {selected.length === 0 ? t('ocpm_pick') : t('ocpm_selected', { n: selected.length })}
                </button>
                {pickerOpen && (
                  <div className="absolute z-40 top-full mt-1 w-96 bg-[#0d1422] border border-white/[0.1] rounded-xl shadow-xl overflow-hidden">
                    <div className="p-2 border-b border-white/[0.06] flex items-center gap-2">
                      <Search size={14} className="text-slate-500" />
                      <input
                        autoFocus
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        onMouseDown={(e) => e.stopPropagation()}
                        placeholder={t('ocpm_search')}
                        className="flex-1 bg-transparent text-sm text-white outline-none"
                      />
                    </div>
                    <div className="flex gap-2 p-2 border-b border-white/[0.06]">
                      <button
                        type="button"
                        className="text-xs text-blue-400"
                        onClick={() => {
                          const ids = filteredObjects.map((x: any) => x.id).slice(0, MAX_SEL)
                          setSelected(ids)
                          const next: Record<string, string> = {}
                          filteredObjects.slice(0, MAX_SEL).forEach((x: any) => { next[x.id] = objectLabel(x) })
                          setLabels((prev) => ({ ...prev, ...next }))
                        }}
                      >
                        {t('ocpm_all')}
                      </button>
                      <button type="button" className="text-xs text-slate-400" onClick={() => setSelected([])}>{t('ocpm_clear')}</button>
                      <button
                        type="button"
                        className="text-xs text-slate-500"
                        onClick={() => {
                          setSelected(filteredObjects.map((x: any) => x.id).slice(0, MAX_SEL))
                          const next: Record<string, string> = {}
                          filteredObjects.slice(0, MAX_SEL).forEach((x: any) => { next[x.id] = objectLabel(x) })
                          setLabels((prev) => ({ ...prev, ...next }))
                        }}
                      >
                        {t('ocpm_select_filter', { n: MAX_SEL })}
                      </button>
                    </div>
                    <div className="max-h-72 overflow-y-auto p-1">
                      {filteredObjects.length > 0 && (
                        <label className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-white/[0.04] cursor-pointer border-b border-white/[0.06] mb-0.5">
                          <input
                            type="checkbox"
                            checked={
                              filteredObjects.length > 0
                              && filteredObjects.slice(0, MAX_SEL).every((x: any) => selected.includes(x.id))
                            }
                            onChange={() => {
                              const ids = filteredObjects.map((x: any) => x.id).slice(0, MAX_SEL)
                              const allOn = ids.every((id: string) => selected.includes(id))
                              if (allOn) {
                                setSelected((prev) => prev.filter((id) => !ids.includes(id)))
                              } else {
                                setSelected(ids)
                                const next: Record<string, string> = {}
                                filteredObjects.slice(0, MAX_SEL).forEach((x: any) => { next[x.id] = objectLabel(x) })
                                setLabels((prev) => ({ ...prev, ...next }))
                              }
                            }}
                          />
                          <span className="text-sm text-slate-300 font-semibold">{t('ocpm_all')}</span>
                        </label>
                      )}
                      {filteredObjects.map((o: any) => {
                        const on = selected.includes(o.id)
                        const idx = selected.indexOf(o.id)
                        return (
                          <label key={o.id} className="flex items-start gap-2 px-2 py-1.5 rounded hover:bg-white/[0.04] cursor-pointer">
                            <input type="checkbox" checked={on} onChange={() => toggle(o.id, objectLabel(o))} />
                            <span
                              className="mt-1 w-2 h-2 rounded-full shrink-0"
                              style={{ backgroundColor: on ? COLORS[idx % COLORS.length] : '#334155' }}
                            />
                            <span>
                              <span className="text-sm text-slate-200 block">{objectLabel(o)}</span>
                              <span className="text-[11px] text-slate-500">{o.hint}</span>
                            </span>
                          </label>
                        )
                      })}
                      {objects.isLoading && (
                        <div className="text-xs text-slate-500 p-2">{t('loading')}</div>
                      )}
                      {!objects.isLoading && filteredObjects.length === 0 && (
                        <div className="text-xs text-slate-500 p-2">{t('ocpm_empty')}</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {selected.map((n) => (
                  <span key={n} className="inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full bg-white/[0.06] text-slate-200">
                    <span className="w-2 h-2 rounded-full" style={{ backgroundColor: colorMap[n] }} />
                    {labels[n] || n}
                    <button type="button" onClick={() => toggle(n)} className="text-slate-500 hover:text-white">×</button>
                  </span>
                ))}
              </div>
            </div>
            <p className="text-[11px] text-slate-500 mb-3">
              {t('ocpm_chart_hint')}
              {series0.data?.as_of ? ` · ${t('ocpm_last_sample')}: ${new Date(series0.data.as_of).toLocaleString('tr-TR')}` : ''}
              {(series0.data?.series || []).some((s) => s.outside_window) ? ` · ${t('ocpm_outside_window')}` : ''}
            </p>
            <div className="grid md:grid-cols-2 gap-4">
              {[0, 1, 2, 3].map((i) => {
                const q = seriesQueries[i]
                const metric = slots[i]
                return (
                  <div key={i} className="border border-white/[0.06] rounded-xl overflow-hidden bg-black/20">
                    <div className="flex items-center gap-2 px-3 py-2 border-b border-white/[0.06]">
                      <select
                        value={metric}
                        onChange={(e) => setSlots((prev) => {
                          const next = [...prev]
                          next[i] = e.target.value
                          return next
                        })}
                        className="flex-1 bg-[#0d1422] text-sm text-white outline-none"
                      >
                        {metricList.map((m) => (
                          <option key={m.id} value={m.id}>{METRIC_LABEL[m.id] || m.id}</option>
                        ))}
                      </select>
                      <button type="button" onClick={() => setFullscreen(i)} className="text-slate-400 hover:text-white" title={t('ocpm_fullscreen')}>
                        <Maximize2 size={14} />
                      </button>
                    </div>
                    {q.isFetching && hasSel ? (
                      <div className="h-[260px] flex items-center justify-center text-slate-500 text-sm">{t('ocpm_fetching')}</div>
                    ) : (
                      <OcpChart
                        title={metric}
                        unit={unitOf(metric)}
                        series={(q.data?.series || []).map((s) => ({ ...s, ref: s.ref || s.name }))}
                        colorMap={seriesColorMap}
                        empty={hasSel ? t('ocpm_empty_data') : t('ocpm_no_selection')}
                      />
                    )}
                  </div>
                )
              })}
            </div>
          </Panel>

          <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-4">
            <Panel>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-3">{t('ocpm_inventory')}</div>
              <ul className="text-sm text-slate-300 space-y-1.5">
                <li>Node <span className="float-right font-mono">{ov?.inventory?.nodes ?? '—'}</span></li>
                <li>Master <span className="float-right font-mono">{ov?.inventory?.masters ?? '—'}</span></li>
                <li>Worker <span className="float-right font-mono">{ov?.inventory?.workers ?? '—'}</span></li>
                <li>Pod <span className="float-right font-mono">{ov?.inventory?.pods ?? '—'}</span></li>
                <li>VM <span className="float-right font-mono">{ov?.inventory?.vms ?? '—'}</span></li>
              </ul>
            </Panel>
            <Panel>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-1">{t('ocpm_comparison')}</div>
              <p className="text-[11px] text-slate-500 mb-3">{t('ocpm_comparison_hint')}</p>
              {(['cpu', 'memory'] as const).map((k) => {
                const c = ov?.comparison?.[k]
                const label = k === 'cpu' ? 'CPU' : t('memory')
                return (
                  <div key={k} className="flex items-center justify-between text-sm py-1 gap-2">
                    <span className="text-slate-400">{label}</span>
                    <span className="font-mono text-slate-200">{c?.current ?? '—'}%</span>
                    <span className={`text-xs ${deltaCls(c?.d24h)}`}>24s {deltaTxt(c?.d24h)}</span>
                    <span className={`text-xs ${deltaCls(c?.d7d)}`}>7g {deltaTxt(c?.d7d)}</span>
                  </div>
                )
              })}
            </Panel>
            <Panel>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-3">{t('ocpm_top_nodes')}</div>
              {(ov?.top_consumers?.node_cpu || []).slice(0, 5).map((x: any) => (
                <div key={`nc-${x.id}`} className="text-sm flex justify-between py-0.5 gap-2">
                  <span className="text-slate-300 truncate">{x.name}{x.role ? ` · ${x.role}` : ''}</span>
                  <span className="font-mono text-slate-400 shrink-0">CPU {x.value}%</span>
                </div>
              ))}
              {(ov?.top_consumers?.node_memory || []).slice(0, 3).map((x: any) => (
                <div key={`nm-${x.id}`} className="text-sm flex justify-between py-0.5 gap-2">
                  <span className="text-slate-300 truncate">{x.name}</span>
                  <span className="font-mono text-slate-400 shrink-0">RAM {x.value}%</span>
                </div>
              ))}
              {!ov?.top_consumers?.node_cpu?.length && (
                <div className="text-sm text-slate-500">{t('ocpm_empty_data')}</div>
              )}
            </Panel>
            <Panel>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-3">{t('ocpm_top_workloads')}</div>
              {(ov?.top_consumers?.pod_cpu || []).slice(0, 4).map((x: any) => (
                <div key={`pc-${x.id}`} className="text-sm flex justify-between py-0.5 gap-2">
                  <span className="text-slate-300 truncate">{x.name}</span>
                  <span className="font-mono text-slate-400 shrink-0">{x.value}c</span>
                </div>
              ))}
              {(ov?.top_consumers?.vm_cpu || []).slice(0, 3).map((x: any) => (
                <div key={`vc-${x.id}`} className="text-sm flex justify-between py-0.5 gap-2">
                  <span className="text-slate-300 truncate">VM {x.name}</span>
                  <span className="font-mono text-slate-400 shrink-0">{x.value}c</span>
                </div>
              ))}
              {!ov?.top_consumers?.pod_cpu?.length && !ov?.top_consumers?.vm_cpu?.length && (
                <div className="text-sm text-slate-500">{t('ocpm_empty_data')}</div>
              )}
            </Panel>
          </div>

          {ov?.summary && (
            <Panel>
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-2">{t('ocpm_summary')}</div>
              <p className="text-sm text-slate-300 leading-relaxed">{ov.summary}</p>
              {ov?.limits?.note && (
                <p className="text-[11px] text-slate-500 mt-2">{ov.limits.note}</p>
              )}
            </Panel>
          )}
        </>
      )}

      {fullscreen != null && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6" onClick={() => setFullscreen(null)}>
          <div className="bg-[#0d1422] border border-white/[0.1] rounded-2xl w-full max-w-6xl p-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <div className="text-sm font-semibold text-white">
                {METRIC_LABEL[slots[fullscreen]] || slots[fullscreen]}
                {unitOf(slots[fullscreen]) && ` (${unitOf(slots[fullscreen])})`}
              </div>
              <button type="button" onClick={() => setFullscreen(null)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <OcpChart
              title={slots[fullscreen]}
              unit={unitOf(slots[fullscreen])}
              series={(seriesQueries[fullscreen].data?.series || []).map((s) => ({ ...s, ref: s.ref || s.name }))}
              colorMap={seriesColorMap}
              height={520}
              empty={hasSel ? t('ocpm_empty_data') : t('ocpm_no_selection')}
            />
          </div>
        </div>
      )}
    </div>
      )}
    </MonitoringShell>
  )
}

export default OpenShiftMonitoring
