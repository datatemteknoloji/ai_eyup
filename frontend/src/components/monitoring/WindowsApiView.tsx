/**
 * Windows Monitoring — API mode (Timescale metric_data / windows_exporter sync).
 * Virt/OCP API ekranının Windows karşılığı.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  Activity, Maximize2, Search, X,
} from 'lucide-react'
import {
  Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'
import WindowsLiveMetrics from '../../pages/WindowsLiveMetrics'

const RANGES = ['15m', '30m', '1h', '2h', '8h', '24h', '7d', '30d'] as const
const MAX_SEL = 8
const COLORS = [
  '#3b82f6', '#10b981', '#f59e0b', '#ec4899',
  '#06b6d4', '#a3e635', '#f97316', '#38bdf8',
]
const DEFAULT_SLOTS = ['cpu_pct', 'memory_pct', 'disk_pct', 'net_rx']

const METRIC_LABEL: Record<string, string> = {
  cpu_pct: 'CPU %',
  memory_pct: 'Bellek %',
  disk_pct: 'Disk C: %',
  cpu_user_pct: 'CPU user %',
  cpu_system_pct: 'CPU privileged %',
  mem_total: 'Bellek toplam',
  mem_avail: 'Bellek boş',
  disk_avail: 'Disk C: boş',
  net_rx: 'Net Rx',
  net_tx: 'Net Tx',
}

const healthCls: Record<string, string> = {
  healthy: 'text-emerald-400',
  warning: 'text-amber-400',
  critical: 'text-red-400',
  unknown: 'text-slate-400',
  connected: 'text-emerald-400',
  missing: 'text-slate-400',
  empty: 'text-slate-500',
}

function tone(v?: string | null) {
  return healthCls[(v || '').toLowerCase()] || 'text-slate-300'
}

function Panel({ children, className = '' }: { children: React.ReactNode; className?: string }) {
  return (
    <div className={`bg-cyber-card border border-white/[0.06] rounded-lg px-3 py-2 ${className}`}>{children}</div>
  )
}

function WinChart({
  title, unit, series, colorMap, height = 220, empty,
}: {
  title: string
  unit?: string
  series: { name: string; points: { t: string; v: number | null }[] }[]
  colorMap: Record<string, string>
  height?: number
  empty: string
}) {
  const data = useMemo(() => {
    const byT: Record<string, Record<string, number | string>> = {}
    series.forEach((s, i) => {
      s.points.forEach((p) => {
        if (!byT[p.t]) byT[p.t] = { t: p.t }
        if (p.v != null) byT[p.t][`s${i}`] = p.v
      })
    })
    return Object.values(byT).sort((a, b) => String(a.t).localeCompare(String(b.t)))
  }, [series])

  if (!series.length || !data.length) {
    return (
      <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 p-3" style={{ height }}>
        <div className="text-xs text-slate-400 mb-2">{title}{unit ? ` (${unit})` : ''}</div>
        <div className="h-[calc(100%-1.5rem)] flex items-center justify-center text-slate-600 text-sm">{empty}</div>
      </div>
    )
  }

  return (
    <div className="rounded-lg border border-white/[0.06] bg-cyber-deep/40 p-3">
      <div className="text-xs text-slate-300 mb-2 font-medium">{title}{unit ? ` (${unit})` : ''}</div>
      <ResponsiveContainer width="100%" height={height - 36}>
        <AreaChart data={data}>
          <CartesianGrid strokeDasharray="3 3" stroke="#1e293b" />
          <XAxis
            dataKey="t"
            tick={{ fill: '#64748b', fontSize: 10 }}
            tickFormatter={(v) => {
              const d = new Date(v)
              return Number.isNaN(d.getTime()) ? '' : d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
            }}
          />
          <YAxis tick={{ fill: '#64748b', fontSize: 10 }} width={44} />
          <Tooltip
            contentStyle={{ background: '#0d1422', border: '1px solid #334155', fontSize: 12 }}
            labelFormatter={(v) => {
              const d = new Date(v)
              return Number.isNaN(d.getTime()) ? String(v) : d.toLocaleString('tr-TR')
            }}
          />
          <Legend wrapperStyle={{ fontSize: 11 }} />
          {series.map((s, i) => (
            <Area
              key={s.name}
              type="monotone"
              dataKey={`s${i}`}
              name={s.name}
              stroke={colorMap[s.name] || COLORS[i % COLORS.length]}
              fill={colorMap[s.name] || COLORS[i % COLORS.length]}
              fillOpacity={0.12}
              strokeWidth={1.5}
              dot={false}
              connectNulls
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

export const WindowsApiView: React.FC = () => {
  const t = useT()
  const [selected, setSelected] = useState<string[]>([])
  const [range, setRange] = useState('24h')
  const [slots, setSlots] = useState<string[]>([...DEFAULT_SLOTS])
  const [search, setSearch] = useState('')
  const [pickerOpen, setPickerOpen] = useState(false)
  const [labels, setLabels] = useState<Record<string, string>>({})
  const [fullscreen, setFullscreen] = useState<number | null>(null)
  const [showWinrm, setShowWinrm] = useState(false)
  const pickerRef = useRef<HTMLDivElement>(null)

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
    queryKey: ['windows-monitoring-overview'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/windows/monitoring/overview`)
      if (!r.ok) throw new Error(t('wmn_overview_fail'))
      return r.json()
    },
    refetchInterval: 60_000,
  })

  const metrics = useQuery({
    queryKey: ['windows-monitoring-metrics'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/windows/monitoring/metrics`)
      if (!r.ok) throw new Error('metrics')
      return r.json() as Promise<{ metrics: { id: string; unit: string }[]; default_slots?: string[] }>
    },
    staleTime: 300_000,
  })

  useEffect(() => {
    const ds = metrics.data?.default_slots
    if (ds?.length) setSlots([...ds].slice(0, 4))
  }, [metrics.data])

  const objects = overview.data?.objects || []
  const filtered = useMemo(() => {
    const ql = search.trim().toLowerCase()
    if (!ql) return objects
    return objects.filter((o: any) =>
      `${o.name} ${o.hostname || ''} ${o.ip_address || ''}`.toLowerCase().includes(ql),
    )
  }, [objects, search])

  const colorMap = useMemo(() => {
    const m: Record<string, string> = {}
    selected.forEach((id, i) => {
      m[labels[id] || id] = COLORS[i % COLORS.length]
    })
    return m
  }, [selected, labels])

  const toggle = (id: string, label?: string) => {
    if (label) setLabels((prev) => ({ ...prev, [id]: label }))
    setSelected((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= MAX_SEL) return prev
      return [...prev, id]
    })
  }

  const series0 = useQuery({
    queryKey: ['windows-monitoring-series', selected.join(','), slots[0], range],
    enabled: selected.length > 0 && !!slots[0],
    queryFn: async () => {
      const params = new URLSearchParams({ ids: selected.join(','), metric: slots[0], range })
      const r = await fetch(`${API_BASE_URL}/windows/monitoring/series?${params}`)
      if (!r.ok) throw new Error('series')
      return r.json() as Promise<{ series: { name: string; points: { t: string; v: number | null }[] }[]; unit?: string }>
    },
    refetchInterval: 60_000,
  })
  const series1 = useQuery({
    queryKey: ['windows-monitoring-series', selected.join(','), slots[1], range],
    enabled: selected.length > 0 && !!slots[1],
    queryFn: async () => {
      const params = new URLSearchParams({ ids: selected.join(','), metric: slots[1], range })
      const r = await fetch(`${API_BASE_URL}/windows/monitoring/series?${params}`)
      if (!r.ok) throw new Error('series')
      return r.json() as Promise<{ series: { name: string; points: { t: string; v: number | null }[] }[]; unit?: string }>
    },
    refetchInterval: 60_000,
  })
  const series2 = useQuery({
    queryKey: ['windows-monitoring-series', selected.join(','), slots[2], range],
    enabled: selected.length > 0 && !!slots[2],
    queryFn: async () => {
      const params = new URLSearchParams({ ids: selected.join(','), metric: slots[2], range })
      const r = await fetch(`${API_BASE_URL}/windows/monitoring/series?${params}`)
      if (!r.ok) throw new Error('series')
      return r.json() as Promise<{ series: { name: string; points: { t: string; v: number | null }[] }[]; unit?: string }>
    },
    refetchInterval: 60_000,
  })
  const series3 = useQuery({
    queryKey: ['windows-monitoring-series', selected.join(','), slots[3], range],
    enabled: selected.length > 0 && !!slots[3],
    queryFn: async () => {
      const params = new URLSearchParams({ ids: selected.join(','), metric: slots[3], range })
      const r = await fetch(`${API_BASE_URL}/windows/monitoring/series?${params}`)
      if (!r.ok) throw new Error('series')
      return r.json() as Promise<{ series: { name: string; points: { t: string; v: number | null }[] }[]; unit?: string }>
    },
    refetchInterval: 60_000,
  })
  const seriesQueries = [series0, series1, series2, series3]

  const ov = overview.data
  const health = ov?.health
  const src = ov?.data_source
  const inv = ov?.inventory
  const avg = ov?.averages
  const catalog = metrics.data?.metrics || ov?.catalog || []
  const unitOf = (mid: string) =>
    catalog.find((m: { id: string }) => m.id === mid)?.unit
    || (METRIC_LABEL[mid]?.includes('%') ? '%' : undefined)

  const hasSel = selected.length > 0

  return (
    <div className="space-y-3">
      {overview.isError && (
        <div className="text-sm text-red-400">{t('wmn_overview_fail')}</div>
      )}

      {!overview.isLoading && (inv?.servers ?? 0) === 0 && (
        <Panel className="text-center py-8">
          <p className="text-sm text-slate-300">{t('wmn_no_servers')}</p>
          <Link to="/windows" className="inline-flex mt-3 text-xs px-4 py-2 rounded-lg bg-blue-600 text-white">
            {t('win_title')}
          </Link>
        </Panel>
      )}

      {(inv?.servers ?? 0) > 0 && (
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-slate-400">
            <span className={`font-medium ${tone(src?.state)}`}>
              Timescale · {src?.state || '—'}
            </span>
            <span className="text-slate-500 hidden md:inline">
              {src?.last_sample
                ? `${t('wmn_last_sample')}: ${new Date(src.last_sample).toLocaleString('tr-TR')}`
                : ''}
              {src?.age_min != null ? ` · ${src.age_min} dk` : ''}
            </span>
            {src?.stale && <span className="text-amber-400">{t('wmn_stale')}</span>}
            {!src?.metrics_available && (
              <span className="text-amber-400">{t('wmn_metrics_off')}</span>
            )}
            <span className="text-slate-600 hidden sm:inline">|</span>
            <span>
              {t('wmn_inv_line', {
                n: inv?.servers ?? 0,
                online: inv?.online ?? 0,
                exp: inv?.exporter_running ?? 0,
                ready: inv?.ai_ready ?? 0,
              })}
            </span>
            <Link to="/windows" className="text-blue-400 hover:underline ml-auto">{t('nav_inventory')}</Link>
          </div>

          <div className="grid grid-cols-3 md:grid-cols-6 gap-2">
            {[
              { label: t('wmn_health'), value: health?.label, cls: tone(health?.grade) },
              { label: t('wmn_healthy'), value: health?.hosts?.healthy ?? '—', cls: 'text-emerald-400' },
              { label: t('wmn_warning'), value: health?.hosts?.warning ?? '—', cls: 'text-amber-400' },
              { label: t('wmn_critical'), value: health?.hosts?.critical ?? '—', cls: 'text-red-400' },
              { label: t('wmn_avg_cpu'), value: avg?.cpu_pct != null ? `%${avg.cpu_pct}` : '—' },
              { label: t('wmn_avg_mem'), value: avg?.memory_pct != null ? `%${avg.memory_pct}` : '—' },
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
              <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">{t('wmn_charts')}</div>
              <div className="relative" ref={pickerRef}>
                <button
                  type="button"
                  onClick={() => setPickerOpen((v) => !v)}
                  className="min-w-[200px] bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-1.5 text-sm text-left text-white"
                >
                  {selected.length === 0 ? t('wmn_pick') : t('wmn_selected', { n: selected.length })}
                </button>
                {pickerOpen && (
                  <div className="absolute z-40 top-full mt-1 w-96 bg-[#0d1422] border border-white/[0.1] rounded-xl shadow-xl overflow-hidden">
                    <div className="p-2 border-b border-white/[0.06] flex items-center gap-2">
                      <Search size={14} className="text-slate-500" />
                      <input
                        autoFocus
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        placeholder={t('wmn_search')}
                        className="flex-1 bg-transparent text-sm text-white outline-none"
                      />
                    </div>
                    <div className="max-h-72 overflow-y-auto p-1">
                      {filtered.map((o: any) => {
                        const on = selected.includes(o.id)
                        const idx = selected.indexOf(o.id)
                        return (
                          <label key={o.id} className="flex items-start gap-2 px-2 py-1.5 rounded hover:bg-white/[0.04] cursor-pointer">
                            <input
                              type="checkbox"
                              checked={on}
                              onChange={() => toggle(o.id, o.name)}
                            />
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
                      {!filtered.length && (
                        <div className="text-xs text-slate-500 p-3 text-center">{t('wmn_filter_empty')}</div>
                      )}
                    </div>
                  </div>
                )}
              </div>
              <select
                value={range}
                onChange={(e) => setRange(e.target.value)}
                className="bg-[#0d1422] border border-white/[0.06] rounded-md px-2 py-1 text-xs text-white"
              >
                {RANGES.map((r) => (
                  <option key={r} value={r}>{r}</option>
                ))}
              </select>
              {[0, 1, 2, 3].map((i) => (
                <select
                  key={i}
                  value={slots[i] || DEFAULT_SLOTS[i]}
                  onChange={(e) => setSlots((prev) => {
                    const next = [...prev]
                    next[i] = e.target.value
                    return next
                  })}
                  className="bg-[#0d1422] border border-white/[0.06] rounded-md px-2 py-1 text-xs text-white max-w-[9rem]"
                >
                  {(catalog.length ? catalog : DEFAULT_SLOTS.map((id) => ({ id, unit: '%' }))).map((m: any) => (
                    <option key={m.id || m} value={m.id || m}>
                      {METRIC_LABEL[m.id || m] || m.id || m}
                    </option>
                  ))}
                </select>
              ))}
            </div>

            <div className="grid md:grid-cols-2 gap-3">
              {[0, 1, 2, 3].map((i) => (
                <div key={i} className="relative">
                  <button
                    type="button"
                    className="absolute top-2 right-2 z-10 p-1 rounded text-slate-500 hover:text-white"
                    onClick={() => setFullscreen(i)}
                    title="Fullscreen"
                  >
                    <Maximize2 size={14} />
                  </button>
                  <WinChart
                    title={METRIC_LABEL[slots[i]] || slots[i]}
                    unit={unitOf(slots[i])}
                    series={seriesQueries[i].data?.series || []}
                    colorMap={colorMap}
                    empty={hasSel ? t('wmn_empty_data') : t('wmn_no_selection')}
                  />
                </div>
              ))}
            </div>
          </Panel>

          <Panel>
            <div className="text-[10px] uppercase tracking-wider text-slate-500 font-bold mb-2">{t('wmn_servers')}</div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="text-[10px] uppercase tracking-wider text-slate-500 border-b border-white/[0.06]">
                  <tr>
                    <th className="text-left py-2 px-2">{t('col_server')}</th>
                    <th className="text-left py-2 px-2">IP</th>
                    <th className="text-left py-2 px-2">CPU</th>
                    <th className="text-left py-2 px-2">{t('memory')}</th>
                    <th className="text-left py-2 px-2">Disk</th>
                    <th className="text-left py-2 px-2">{t('col_status')}</th>
                    <th className="text-left py-2 px-2">Exporter</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-white/[0.04]">
                  {objects.map((o: any) => {
                    const on = selected.includes(o.id)
                    return (
                      <tr
                        key={o.id}
                        className={`hover:bg-white/[0.03] cursor-pointer ${on ? 'bg-blue-500/5' : ''}`}
                        onClick={() => toggle(o.id, o.name)}
                      >
                        <td className="py-2 px-2 text-white font-medium">{o.name}</td>
                        <td className="py-2 px-2 text-slate-400 font-mono text-xs">{o.ip_address || '—'}</td>
                        <td className="py-2 px-2 tabular-nums text-slate-300">
                          {o.cpu_pct != null ? `%${o.cpu_pct}` : '—'}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-slate-300">
                          {o.memory_pct != null ? `%${o.memory_pct}` : '—'}
                        </td>
                        <td className="py-2 px-2 tabular-nums text-slate-300">
                          {o.disk_pct != null ? `%${o.disk_pct}` : '—'}
                        </td>
                        <td className={`py-2 px-2 ${tone(o.grade)}`}>{o.status || '—'}</td>
                        <td className="py-2 px-2 text-xs text-slate-400">
                          {o.windows_exporter_running ? (
                            <span className="text-emerald-400">up</span>
                          ) : o.windows_exporter_installed ? (
                            <span className="text-amber-400">installed</span>
                          ) : (
                            <span className="text-slate-600">—</span>
                          )}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
            {!src?.metrics_available && (
              <p className="text-xs text-amber-400/90 mt-3">{t('wmn_need_exporter')}</p>
            )}
          </Panel>

          <div className="rounded-xl border border-white/[0.06] bg-cyber-card">
            <button
              type="button"
              onClick={() => setShowWinrm((v) => !v)}
              className="w-full flex items-center justify-between px-4 py-3 text-left text-sm text-slate-300 hover:bg-white/[0.03]"
            >
              <span>{t('wmn_winrm_toggle')}</span>
              <span className="text-xs text-slate-500">{showWinrm ? '▲' : '▼'}</span>
            </button>
            {showWinrm && (
              <div className="px-2 pb-3 border-t border-white/[0.04]">
                <WindowsLiveMetrics embedded />
              </div>
            )}
          </div>
        </>
      )}

      {fullscreen != null && (
        <div className="fixed inset-0 z-50 bg-black/70 flex items-center justify-center p-6" onClick={() => setFullscreen(null)}>
          <div className="bg-[#0d1422] border border-white/[0.1] rounded-2xl w-full max-w-6xl p-4" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between mb-3">
              <div className="text-sm font-semibold text-white">
                {METRIC_LABEL[slots[fullscreen]] || slots[fullscreen]}
              </div>
              <button type="button" onClick={() => setFullscreen(null)} className="text-slate-400 hover:text-white">
                <X size={18} />
              </button>
            </div>
            <WinChart
              title={METRIC_LABEL[slots[fullscreen]] || slots[fullscreen]}
              unit={unitOf(slots[fullscreen])}
              series={seriesQueries[fullscreen].data?.series || []}
              colorMap={colorMap}
              height={520}
              empty={hasSel ? t('wmn_empty_data') : t('wmn_no_selection')}
            />
          </div>
        </div>
      )}
    </div>
  )
}

export default WindowsApiView
