import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Activity, Maximize2, Search, X,
} from 'lucide-react'
import {
  Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { API_BASE_URL } from '../config/api'
import { useT } from '../i18n/LocaleProvider'

const RANGES = ['15m', '30m', '1h', '2h', '8h', '24h', '7d', '30d', '60d'] as const
const MAX_SEL = 8
const COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ec4899',
  '#06b6d4', '#a3e635', '#f97316', '#38bdf8',
]
const DEFAULT_METRICS: Record<string, string[]> = {
  host: ['cpu_pct', 'mem_pct', 'cpu_ready_pct', 'disk_latency_ms'],
  vm: ['cpu_pct', 'mem_pct', 'cpu_ready_pct', 'disk_latency_ms'],
  datastore: ['usage_pct', 'free_gb', 'read_latency_ms', 'write_iops'],
}

type Kind = 'host' | 'vm' | 'datastore'

type SeriesPoint = { t: string | null; v: number | null }
type SeriesResp = {
  ok: boolean
  unit?: string
  metric?: string
  as_of?: string | null
  native_interval_min?: number
  series: { name: string; points: SeriesPoint[] }[]
  note?: string
}

const healthCls: Record<string, string> = {
  healthy: 'text-emerald-400',
  warning: 'text-amber-400',
  critical: 'text-red-400',
  unknown: 'text-slate-400',
  connected: 'text-emerald-400',
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
  mem_pct: 'Bellek %',
  cpu_ready_pct: 'CPU ready %',
  disk_latency_ms: 'Disk latency ms',
  usage_pct: 'Doluluk %',
  free_gb: 'Boş GB',
  read_latency_ms: 'Okuma latency ms',
  write_iops: 'Yazma IOPS',
}

function Panel({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-cyber-card border border-white/[0.06] rounded-xl p-4 ${className}`}>{children}</div>
  )
}

function minuteKey(iso: string) {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  d.setSeconds(0, 0)
  return d.toISOString()
}

function VirtChart({
  title, unit, series, colorMap, height = 260, empty,
}: {
  title: string
  unit?: string
  series: { name: string; points: SeriesPoint[] }[]
  colorMap: Record<string, string>
  height?: number
  empty: string
}) {
  const { chartData, keys } = useMemo(() => {
    const keys = series.map((s) => s.name)
    const byMin: Record<string, Record<string, number | null>> = {}
    series.forEach((s) => {
      s.points.forEach((p) => {
        if (!p.t) return
        const k = minuteKey(p.t)
        if (!byMin[k]) byMin[k] = {}
        byMin[k][s.name] = p.v
      })
    })
    const times = Object.keys(byMin).sort()
    const data = times.map((t) => ({
      time: new Date(t).toLocaleString('tr-TR', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }),
      ...byMin[t],
    }))
    return { chartData: data, keys }
  }, [series])

  if (!chartData.length || !keys.length) {
    return (
      <div className="h-full min-h-[200px] flex items-center justify-center text-sm text-slate-500 px-4 text-center">
        {empty}
      </div>
    )
  }

  return (
    <div style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={chartData} margin={{ top: 8, right: 8, left: 0, bottom: 0 }}>
          <defs>
            {keys.map((k) => (
              <linearGradient key={k} id={`vmn-${k.replace(/[^a-zA-Z0-9]/g, '')}`} x1="0" y1="0" x2="0" y2="1">
                <stop offset="0%" stopColor={colorMap[k] || COLORS[0]} stopOpacity={0.35} />
                <stop offset="100%" stopColor={colorMap[k] || COLORS[0]} stopOpacity={0} />
              </linearGradient>
            ))}
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="#334155" opacity={0.45} />
          <XAxis dataKey="time" stroke="#64748b" fontSize={10} tickLine={false} />
          <YAxis stroke="#64748b" fontSize={10} tickLine={false} width={44} />
          <Tooltip
            contentStyle={{ backgroundColor: '#131c2f', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8 }}
            labelStyle={{ color: '#c5d0e8' }}
            formatter={(value: number, name: string) => [
              `${Number(value).toFixed(2)}${unit ? ` ${unit}` : ''}`,
              name,
            ]}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {keys.map((k) => (
            <Area
              key={k}
              type="monotone"
              dataKey={k}
              stroke={colorMap[k] || COLORS[0]}
              strokeWidth={2}
              fill={`url(#vmn-${k.replace(/[^a-zA-Z0-9]/g, '')})`}
              connectNulls
              dot={{ r: 2, strokeWidth: 0 }}
              isAnimationActive={false}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

const VirtMonitoring: React.FC = () => {
  const t = useT()
  const [kind, setKind] = useState<Kind>('vm')
  const [selected, setSelected] = useState<string[]>([])
  const [range, setRange] = useState<string>('30m')
  const [slots, setSlots] = useState<string[]>(DEFAULT_METRICS.vm)
  const [search, setSearch] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const [fullscreen, setFullscreen] = useState<number | null>(null)
  const pickerRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setSlots([...DEFAULT_METRICS[kind]])
    setSelected([])
    setSearch('')
  }, [kind])

  useEffect(() => {
    const onDoc = (e: MouseEvent) => {
      if (pickerRef.current && !pickerRef.current.contains(e.target as Node)) {
        setPickerOpen(false)
      }
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [])

  const overview = useQuery({
    queryKey: ['virt-monitoring-overview'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/monitoring/overview`)
      if (!r.ok) throw new Error(t('vmn_overview_fail'))
      return r.json()
    },
    refetchInterval: 120_000,
  })

  const metrics = useQuery({
    queryKey: ['virt-monitoring-metrics', kind],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/monitoring/metrics?kind=${kind}`)
      if (!r.ok) throw new Error('metrics')
      return r.json()
    },
    staleTime: 300_000,
  })

  const objects = useQuery({
    queryKey: ['virt-monitoring-objects', kind],
    queryFn: async () => {
      const p = new URLSearchParams({ kind, limit: '200' })
      const r = await fetch(`${API_BASE_URL}/hypervisors/monitoring/objects?${p}`)
      if (!r.ok) throw new Error('objects')
      return r.json()
    },
    enabled: pickerOpen,
    staleTime: 60_000,
  })
  const filteredObjects = useMemo(() => {
    const items = objects.data?.items || []
    const q = search.trim().toLowerCase()
    if (!q) return items
    return items.filter((o: any) =>
      [o.name, o.hint, o.host, o.cluster, o.status].some((x) => String(x || '').toLowerCase().includes(q)),
    )
  }, [objects.data, search])

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
    const p = new URLSearchParams({ kind, names: namesKey, metric, range })
    const r = await fetch(`${API_BASE_URL}/hypervisors/monitoring/series?${p}`)
    if (!r.ok) throw new Error('series')
    return r.json()
  }

  const series0 = useQuery({
    queryKey: ['virt-monitoring-series', kind, namesKey, slots[0], range, 0],
    queryFn: () => fetchSeries(slots[0]),
    enabled: hasSel && !!slots[0],
    staleTime: 60_000,
  })
  const series1 = useQuery({
    queryKey: ['virt-monitoring-series', kind, namesKey, slots[1], range, 1],
    queryFn: () => fetchSeries(slots[1]),
    enabled: hasSel && !!slots[1],
    staleTime: 60_000,
  })
  const series2 = useQuery({
    queryKey: ['virt-monitoring-series', kind, namesKey, slots[2], range, 2],
    queryFn: () => fetchSeries(slots[2]),
    enabled: hasSel && !!slots[2],
    staleTime: 60_000,
  })
  const series3 = useQuery({
    queryKey: ['virt-monitoring-series', kind, namesKey, slots[3], range, 3],
    queryFn: () => fetchSeries(slots[3]),
    enabled: hasSel && !!slots[3],
    staleTime: 60_000,
  })
  const seriesQueries = [series0, series1, series2, series3]

  const ov = overview.data
  const health = ov?.health
  const src = ov?.data_source

  const toggle = (name: string) => {
    setSelected((prev) => {
      if (prev.includes(name)) return prev.filter((x) => x !== name)
      if (prev.length >= MAX_SEL) return prev
      return [...prev, name]
    })
  }

  return (
    <div className="p-6 space-y-5 max-w-[1600px]">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <h1 className="text-[26px] font-extrabold text-white tracking-tight">{t('vmn_title')}</h1>
          <p className="text-sm text-slate-400 mt-1">{t('vmn_subtitle')}</p>
        </div>
        <div className="flex flex-wrap items-center gap-3 text-xs">
          <span className={`font-semibold ${tone(src?.state)}`}>
            vCenter · {src?.state || '—'}
          </span>
          <span className="text-slate-500">
            {t('vmn_last_sync')}: {src?.last_host_sync ? new Date(src.last_host_sync).toLocaleString('tr-TR') : '—'}
            {src?.host_age_min != null ? ` · ${src.host_age_min} dk` : ''}
          </span>
          {src?.stale && <span className="text-amber-400">{t('vmn_stale')}</span>}
          <Link to="/virt/events" className="text-blue-400 hover:underline">{t('vmn_open_events')}</Link>
          <Link to="/virt/chat" className="text-blue-400 hover:underline">{t('vmn_open_chat')}</Link>
        </div>
      </div>

      {overview.isError && (
        <div className="text-sm text-red-400">{t('vmn_overview_fail')}</div>
      )}

      <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-3">
        {[
          { label: t('vmn_health'), value: health?.label, cls: tone(health?.grade) },
          { label: t('vmn_healthy'), value: health?.hosts?.healthy ?? '—', cls: 'text-emerald-400' },
          { label: t('vmn_warning'), value: health?.hosts?.warning ?? '—', cls: 'text-amber-400' },
          { label: t('vmn_critical'), value: health?.hosts?.critical ?? '—', cls: 'text-red-400' },
          { label: t('vmn_unknown'), value: health?.hosts?.unknown ?? '—', cls: 'text-slate-400' },
          { label: t('vmn_availability'), value: health?.availability_pct != null ? `${health.availability_pct}%` : '—' },
        ].map((k) => (
          <Panel key={k.label}>
            <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">{k.label}</div>
            <div className={`text-xl font-semibold mt-1 ${k.cls || 'text-white'}`}>{k.value}</div>
          </Panel>
        ))}
      </div>

      <Panel>
        <div className="flex flex-wrap items-center gap-3 mb-4">
          <Activity size={16} className="text-blue-400" />
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">{t('vmn_charts')}</div>
          <div className="flex rounded-lg border border-white/[0.06] overflow-hidden">
            {(['vm', 'host', 'datastore'] as Kind[]).map((k) => (
              <button
                key={k}
                type="button"
                onClick={() => setKind(k)}
                className={`px-3 py-1.5 text-xs ${kind === k ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}
              >
                {t(`vmn_axis_${k}` as any)}
              </button>
            ))}
          </div>
          <select
            value={range}
            onChange={(e) => setRange(e.target.value)}
            className="bg-[#0d1422] border border-white/[0.06] rounded-lg px-2 py-1.5 text-sm text-white"
          >
            {RANGES.map((r) => (
              <option key={r} value={r}>{t(`vmn_range_${r}` as any)}</option>
            ))}
          </select>
          <div className="relative" ref={pickerRef}>
            <button
              type="button"
              onClick={() => setPickerOpen((v) => !v)}
              className="min-w-[220px] bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-1.5 text-sm text-left text-white"
            >
              {selected.length === 0 ? t('vmn_pick') : t('vmn_selected', { n: selected.length })}
            </button>
            {pickerOpen && (
              <div className="absolute z-40 top-full mt-1 w-80 bg-[#0d1422] border border-white/[0.1] rounded-xl shadow-xl overflow-hidden">
                <div className="p-2 border-b border-white/[0.06] flex items-center gap-2">
                  <Search size={14} className="text-slate-500" />
                  <input
                    autoFocus
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    onMouseDown={(e) => e.stopPropagation()}
                    placeholder={t('vmn_search')}
                    className="flex-1 bg-transparent text-sm text-white outline-none"
                  />
                </div>
                <div className="flex gap-2 p-2 border-b border-white/[0.06]">
                  <button type="button" className="text-xs text-slate-400" onClick={() => setSelected([])}>{t('vmn_clear')}</button>
                  <button
                    type="button"
                    className="text-xs text-blue-400"
                    onClick={() => {
                      setSelected(filteredObjects.map((x: any) => x.name).slice(0, MAX_SEL))
                    }}
                  >
                    {t('vmn_select_filter', { n: MAX_SEL })}
                  </button>
                </div>
                <div className="max-h-64 overflow-y-auto p-1">
                  {filteredObjects.map((o: any) => {
                    const on = selected.includes(o.name)
                    const idx = selected.indexOf(o.name)
                    return (
                      <label key={o.id} className="flex items-start gap-2 px-2 py-1.5 rounded hover:bg-white/[0.04] cursor-pointer">
                        <input type="checkbox" checked={on} onChange={() => toggle(o.name)} />
                        <span
                          className="mt-1 w-2 h-2 rounded-full shrink-0"
                          style={{ backgroundColor: on ? COLORS[idx % COLORS.length] : '#334155' }}
                        />
                        <span>
                          <span className="text-sm text-slate-200 block">{o.name}</span>
                          <span className="text-[11px] text-slate-500">{o.hint}</span>
                        </span>
                      </label>
                    )
                  })}
                  {pickerOpen && objects.isLoading && (
                    <div className="text-xs text-slate-500 p-2">{t('loading')}</div>
                  )}
                </div>
              </div>
            )}
          </div>
          <div className="flex flex-wrap gap-2">
            {selected.map((n) => (
              <span key={n} className="inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded-full bg-white/[0.06] text-slate-200">
                <span className="w-2 h-2 rounded-full" style={{ backgroundColor: colorMap[n] }} />
                {n}
                <button type="button" onClick={() => toggle(n)} className="text-slate-500 hover:text-white">×</button>
              </span>
            ))}
          </div>
        </div>
        <p className="text-[11px] text-slate-500 mb-3">
          {t('vmn_chart_hint')} · {t('vmn_source_vcenter')}
          {series0.data?.as_of ? ` · ${t('vmn_last_sample')}: ${new Date(series0.data.as_of).toLocaleString('tr-TR')}` : ''}
          {(series0.data?.series || []).some((s: any) => s.outside_window) ? ` · ${t('vmn_outside_window')}` : ''}
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
                  <button type="button" onClick={() => setFullscreen(i)} className="text-slate-400 hover:text-white" title={t('vmn_fullscreen')}>
                    <Maximize2 size={14} />
                  </button>
                </div>
                {q.isFetching && hasSel ? (
                  <div className="h-[260px] flex items-center justify-center text-slate-500 text-sm">{t('vmn_fetching')}</div>
                ) : (
                  <VirtChart
                    title={metric}
                    unit={unitOf(metric)}
                    series={q.data?.series || []}
                    colorMap={colorMap}
                    empty={hasSel ? t('vmn_empty_data') : t('vmn_no_selection')}
                  />
                )}
              </div>
            )
          })}
        </div>
      </Panel>

      <div className="grid md:grid-cols-2 xl:grid-cols-4 gap-4">
        <Panel>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-3">{t('vmn_inventory')}</div>
          <ul className="text-sm text-slate-300 space-y-1.5">
            <li>vCenter <span className="float-right font-mono">{ov?.inventory?.vcenters ?? '—'}</span></li>
            <li>ESXi <span className="float-right font-mono">{ov?.inventory?.esxi_hosts ?? '—'}</span></li>
            <li>Cluster <span className="float-right font-mono">{ov?.inventory?.clusters ?? '—'}</span></li>
            <li>VM <span className="float-right font-mono">{ov?.inventory?.vms_running ?? 0}/{ov?.inventory?.vms ?? 0}</span></li>
            <li>Datastore <span className="float-right font-mono">{ov?.inventory?.datastores ?? '—'}</span></li>
          </ul>
        </Panel>
        <Panel>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-1">{t('vmn_comparison')}</div>
          <p className="text-[11px] text-slate-500 mb-3">{t('vmn_comparison_hint')}</p>
          {(['cpu', 'memory', 'storage'] as const).map((k) => {
            const c = ov?.comparison?.[k]
            const label = k === 'cpu' ? t('vmn_cmp_cpu') : k === 'memory' ? t('vmn_cmp_mem') : t('vmn_cmp_ds')
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
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-3">{t('vmn_capacity')}</div>
          {(ov?.capacity || []).length === 0 && <div className="text-sm text-slate-500">{t('vmn_empty_data')}</div>}
          {(ov?.capacity || []).slice(0, 5).map((c: any) => (
            <div key={c.name} className="mb-2">
              <div className="flex justify-between text-sm">
                <span className="text-slate-200 truncate mr-2">{c.name}</span>
                <span className={tone(c.risk)}>{c.current}%</span>
              </div>
              <div className="text-[11px] text-slate-500">
                30g {deltaTxt(c.trend_30d)} · {t('vmn_headroom')} {c.headroom ?? '—'}%
                {c.days_to_80 != null ? ` · ${t('vmn_days_to')} ${c.days_to_80}` : ''}
              </div>
            </div>
          ))}
        </Panel>
        <Panel>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-3">{t('vmn_top_consumers')}</div>
          {(ov?.top_consumers?.vm_cpu || []).slice(0, 3).map((x: any) => (
            <div key={`c-${x.name}`} className="text-sm flex justify-between py-0.5">
              <span className="text-slate-300 truncate mr-2">{x.name}</span>
              <span className="font-mono text-slate-400">CPU {x.value}%</span>
            </div>
          ))}
          {(ov?.top_consumers?.host_memory || []).slice(0, 2).map((x: any) => (
            <div key={`h-${x.name}`} className="text-sm flex justify-between py-0.5">
              <span className="text-slate-300 truncate mr-2">{x.name}</span>
              <span className="font-mono text-slate-400">RAM {x.value}%</span>
            </div>
          ))}
        </Panel>
      </div>

      <Panel>
        <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-1">{t('vmn_timeline')}</div>
        <p className="text-[11px] text-slate-500 mb-3">{t('vmn_timeline_hint')}</p>
        <div className="space-y-1.5 max-h-56 overflow-y-auto">
          {(ov?.timeline || []).map((e: any) => (
            <div key={e.id} className="flex gap-3 text-sm">
              <span className="font-mono text-[11px] text-slate-500 w-36 shrink-0">
                {e.time ? new Date(e.time).toLocaleString('tr-TR') : '—'}
              </span>
              <span className={`text-[11px] font-bold uppercase w-16 ${tone(e.severity)}`}>{e.severity}</span>
              <span className="text-slate-300">{e.title}</span>
            </div>
          ))}
          {(!ov?.timeline || ov.timeline.length === 0) && (
            <div className="text-sm text-slate-500">{t('vmn_empty_data')}</div>
          )}
        </div>
      </Panel>

      {ov?.summary && (
        <Panel>
          <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-2">{t('vmn_summary')}</div>
          <p className="text-sm text-slate-300 leading-relaxed">{ov.summary}</p>
        </Panel>
      )}

      {fullscreen != null && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6" onClick={() => setFullscreen(null)}>
          <div className="bg-[#0d1422] border border-white/[0.1] rounded-2xl w-full max-w-6xl p-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <div className="text-sm font-semibold text-white">{slots[fullscreen]} {unitOf(slots[fullscreen]) && `(${unitOf(slots[fullscreen])})`}</div>
              <button type="button" onClick={() => setFullscreen(null)} className="text-slate-400 hover:text-white"><X size={18} /></button>
            </div>
            <VirtChart
              title={slots[fullscreen]}
              unit={unitOf(slots[fullscreen])}
              series={seriesQueries[fullscreen].data?.series || []}
              colorMap={colorMap}
              height={520}
              empty={hasSel ? t('vmn_empty_data') : t('vmn_no_selection')}
            />
          </div>
        </div>
      )}
    </div>
  )
}

export default VirtMonitoring
