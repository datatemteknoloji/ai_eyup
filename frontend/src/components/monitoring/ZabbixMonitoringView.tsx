/**
 * Zabbix monitoring UI — KPI overview + multi-host charts with full metric catalog,
 * fullscreen enlarge, severity problems, match coverage.
 */
import React, { useEffect, useMemo, useState } from 'react'
import { useQueries, useQuery } from '@tanstack/react-query'
import {
  Area, AreaChart, CartesianGrid, Legend, ReferenceLine,
  ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import {
  Activity, AlertTriangle, CheckCircle2, Cpu, HardDrive, Maximize2, MemoryStick,
  Network, Plus, RefreshCw, Search, Server, ShieldAlert, X, type LucideIcon,
} from 'lucide-react'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'
import {
  CHART_COLORS, CatMetric, RANGE_OPTS, ZbxHost, ZbxProblem, ZbxSeries, ZbxTab,
  chartRows, fmtNum, fmtUnit, qs, severityMeta,
} from './zabbix/zbxUi'

const REFRESH_MS = 30_000
const MAX_HOSTS = 8
const DEFAULT_SLOTS = ['cpu_util', 'mem_used_pct', 'fs_used_pct', 'cpu_load1']
const LS_TAB = 'ainew.zabbix.monitoring.tab'
const LS_RANGE = 'ainew.zabbix.monitoring.rangeSec'
const LS_SLOTS = 'ainew.zabbix.monitoring.slots'
const LS_OV_METRIC = 'ainew.zabbix.monitoring.overviewMetric'
const LS_AUTO = 'ainew.zabbix.monitoring.autoRefresh'
const hostLsKey = (sid: string) => `ainew.zabbix.monitoring.hosts.${sid}`

const VALID_TABS: ZbxTab[] = ['overview', 'hosts', 'charts', 'problems', 'coverage']

function loadTab(): ZbxTab {
  const raw = localStorage.getItem(LS_TAB) as ZbxTab | null
  return raw && VALID_TABS.includes(raw) ? raw : 'overview'
}

function loadRange(): number {
  const n = Number(localStorage.getItem(LS_RANGE))
  return RANGE_OPTS.some((r) => r.sec === n) ? n : 3600
}

function loadSlots(): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(LS_SLOTS) || 'null')
    if (Array.isArray(raw) && raw.every((x) => typeof x === 'string') && raw.length) return raw
  } catch { /* ignore */ }
  return [...DEFAULT_SLOTS]
}

function loadHosts(sid: string): string[] {
  try {
    const raw = JSON.parse(localStorage.getItem(hostLsKey(sid)) || 'null')
    if (Array.isArray(raw) && raw.every((x) => typeof x === 'string')) return raw.slice(0, MAX_HOSTS)
  } catch { /* ignore */ }
  return []
}

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded-lg bg-white/[0.04] border border-white/[0.04] ${className}`} />
}

function KpiCard({
  label, value, hint, icon: Icon, tone = 'neutral',
}: {
  label: string
  value: React.ReactNode
  hint?: string
  icon: LucideIcon
  tone?: 'neutral' | 'ok' | 'warn' | 'crit' | 'info'
}) {
  const toneCls = {
    neutral: 'text-blue-400 bg-blue-500/10',
    ok: 'text-emerald-400 bg-emerald-500/10',
    warn: 'text-amber-400 bg-amber-500/10',
    crit: 'text-red-400 bg-red-500/10',
    info: 'text-sky-400 bg-sky-500/10',
  }[tone]
  return (
    <div className="rounded-xl border border-white/[0.06] bg-[var(--bg-surface)] p-3 min-h-[88px] flex flex-col justify-between">
      <div className="flex items-start justify-between gap-2">
        <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">{label}</span>
        <span className={`rounded-md p-1.5 ${toneCls}`}><Icon size={14} /></span>
      </div>
      <div className="mt-2">
        <div className="text-xl font-semibold text-[var(--text-primary)] tabular-nums tracking-tight">{value}</div>
        {hint && <div className="text-[11px] text-[var(--text-muted)] mt-0.5 truncate">{hint}</div>}
      </div>
    </div>
  )
}

function SeverityBadge({ severity }: { severity?: string | number }) {
  const m = severityMeta(severity)
  return (
    <span className={`inline-flex items-center gap-1.5 text-[10px] font-bold uppercase tracking-wide px-1.5 py-0.5 rounded border ${m.className}`}>
      <span className={`w-1.5 h-1.5 rounded-full ${m.bar}`} aria-hidden />
      {m.label}
    </span>
  )
}

function EmptyState({ title, body }: { title: string; body?: string }) {
  return (
    <div className="rounded-xl border border-dashed border-white/[0.08] bg-[var(--bg-surface)]/50 px-4 py-10 text-center">
      <p className="text-sm text-[var(--text-secondary)]">{title}</p>
      {body && <p className="text-[11px] text-[var(--text-muted)] mt-1">{body}</p>}
    </div>
  )
}

function ErrorBanner({ message, hint }: { message: string; hint?: string }) {
  return (
    <div className="rounded-xl border border-red-500/25 bg-red-500/[0.06] p-4 flex gap-3">
      <ShieldAlert className="text-red-400 shrink-0 mt-0.5" size={18} />
      <div>
        <p className="text-sm text-red-300">{message}</p>
        {hint && <p className="text-[11px] text-[var(--text-muted)] mt-1">{hint}</p>}
      </div>
    </div>
  )
}

function SeriesChart({
  series, unit, loading, height = 260, threshold,
}: {
  series: ZbxSeries[]
  unit?: string
  loading?: boolean
  height?: number
  threshold?: number
}) {
  const data = useMemo(() => chartRows(series), [series])
  if (loading) {
    return <div className="animate-pulse rounded-lg bg-white/[0.04] border border-white/[0.04] w-full" style={{ height }} />
  }
  if (!data.length) {
    return <EmptyState title="Seri yok" body="Bu aralıkta nokta yok veya item eşleşmedi (Match map)." />
  }
  const isPct = unit === '%'
  return (
    <div style={{ height }} className="w-full">
      <ResponsiveContainer width="100%" height="100%">
        <AreaChart data={data} margin={{ top: 8, right: 12, left: 0, bottom: 0 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" vertical={false} />
          <XAxis
            dataKey="t"
            tickFormatter={(v) => new Date(Number(v) * 1000).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
            stroke="#64748b"
            tick={{ fontSize: 10, fill: '#9aabcb' }}
            axisLine={false}
            tickLine={false}
            minTickGap={28}
          />
          <YAxis
            stroke="#64748b"
            tick={{ fontSize: 10, fill: '#9aabcb' }}
            width={48}
            axisLine={false}
            tickLine={false}
            domain={isPct ? [0, 100] : ['auto', 'auto']}
            tickFormatter={(v) => fmtNum(Number(v), 0)}
          />
          <Tooltip
            contentStyle={{
              background: '#0d1422', border: '1px solid rgba(255,255,255,0.11)',
              borderRadius: 8, fontSize: 11, color: '#e8edf5',
            }}
            labelFormatter={(v) => new Date(Number(v) * 1000).toLocaleString()}
            formatter={(val: number, name: string) => [fmtUnit(val, unit), name]}
          />
          <Legend wrapperStyle={{ fontSize: 11, paddingTop: 4 }} />
          {threshold != null && (
            <ReferenceLine
              y={threshold}
              stroke="#f59e0b"
              strokeDasharray="4 4"
              label={{ value: `eşik ${threshold}`, fill: '#f59e0b', fontSize: 10 }}
            />
          )}
          {series.map((s, i) => (
            <Area
              key={s.itemid || s.hostid || i}
              type="monotone"
              dataKey={`s${i}`}
              name={s.name}
              stroke={CHART_COLORS[i % CHART_COLORS.length]}
              fill={CHART_COLORS[i % CHART_COLORS.length]}
              fillOpacity={0.12}
              strokeWidth={2}
              dot={false}
              connectNulls
              isAnimationActive={false}
            />
          ))}
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

function TopList({
  title, rows, unit, onSelect,
}: {
  title: string
  rows: { hostid: string; host: string; value: number }[]
  unit: string
  onSelect?: (hostid: string) => void
}) {
  const max = Math.max(...rows.map((r) => r.value), 1)
  return (
    <div className="rounded-xl border border-white/[0.06] bg-[var(--bg-surface)] p-3 h-full">
      <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] mb-3">{title}</div>
      {!rows.length ? (
        <p className="text-xs text-[var(--text-muted)]">Veri yok</p>
      ) : (
        <ul className="space-y-2">
          {rows.map((r) => (
            <li key={r.hostid}>
              <button type="button" onClick={() => onSelect?.(r.hostid)} className="w-full text-left group">
                <div className="flex justify-between text-xs mb-1 gap-2">
                  <span className="text-[var(--text-secondary)] truncate group-hover:text-blue-300">{r.host}</span>
                  <span className="font-mono text-[var(--text-muted)] shrink-0">{fmtUnit(r.value, unit)}</span>
                </div>
                <div className="h-1 rounded-full bg-white/[0.04] overflow-hidden">
                  <div className="h-full rounded-full bg-blue-500/70" style={{ width: `${Math.min(100, (r.value / max) * 100)}%` }} />
                </div>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function MetricSelect({
  value, onChange, metrics, className = '',
}: {
  value: string
  onChange: (id: string) => void
  metrics: CatMetric[]
  className?: string
}) {
  const byFam = useMemo(() => {
    const m = new Map<string, CatMetric[]>()
    for (const row of metrics) {
      const list = m.get(row.family) || []
      list.push(row)
      m.set(row.family, list)
    }
    return [...m.entries()]
  }, [metrics])
  return (
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className={className || 'bg-[var(--bg-elevated)] border border-white/[0.08] rounded-md px-2 py-1 text-xs text-[var(--text-primary)]'}
    >
      {byFam.map(([fam, rows]) => (
        <optgroup key={fam} label={fam}>
          {rows.map((m) => (
            <option key={m.id} value={m.id}>{m.title} ({m.id}){m.unit ? ` · ${m.unit}` : ''}</option>
          ))}
        </optgroup>
      ))}
    </select>
  )
}

export const ZabbixMonitoringView: React.FC<{
  sourceId: string
  titleLabel?: string
}> = ({ sourceId, titleLabel }) => {
  const t = useT()
  const [tab, setTab] = useState<ZbxTab>(() => loadTab())
  const [search, setSearch] = useState('')
  const [groupid, setGroupid] = useState('')
  const [selectedHosts, setSelectedHosts] = useState<string[]>(() => loadHosts(sourceId))
  const [slots, setSlots] = useState<string[]>(() => loadSlots())
  const [overviewMetric, setOverviewMetric] = useState(
    () => localStorage.getItem(LS_OV_METRIC) || 'cpu_util',
  )
  const [rangeSec, setRangeSec] = useState(() => loadRange())
  const [sevFilter, setSevFilter] = useState<number | 'all'>('all')
  const [autoRefresh, setAutoRefresh] = useState(
    () => localStorage.getItem(LS_AUTO) !== '0',
  )
  const [fullscreen, setFullscreen] = useState<number | 'overview' | null>(null)
  const [metricPickerOpen, setMetricPickerOpen] = useState(false)
  const refreshMs = autoRefresh ? REFRESH_MS : false
  const sid = sourceId

  useEffect(() => {
    localStorage.setItem(LS_TAB, tab)
  }, [tab])
  useEffect(() => {
    localStorage.setItem(LS_RANGE, String(rangeSec))
  }, [rangeSec])
  useEffect(() => {
    localStorage.setItem(LS_SLOTS, JSON.stringify(slots))
  }, [slots])
  useEffect(() => {
    localStorage.setItem(LS_OV_METRIC, overviewMetric)
  }, [overviewMetric])
  useEffect(() => {
    localStorage.setItem(LS_AUTO, autoRefresh ? '1' : '0')
  }, [autoRefresh])
  useEffect(() => {
    localStorage.setItem(hostLsKey(sid), JSON.stringify(selectedHosts))
  }, [sid, selectedHosts])
  useEffect(() => {
    // kaynak değişince o kaynağın host seçimini yükle
    setSelectedHosts(loadHosts(sourceId))
  }, [sourceId])

  const overview = useQuery({
    queryKey: ['zbx-overview', sid],
    enabled: !!sid,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/monitoring/zabbix/overview?${qs({ source_id: sid })}`)
      return r.json()
    },
    refetchInterval: refreshMs,
  })

  const catalog = useQuery({
    queryKey: ['zbx-catalog'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/monitoring/zabbix/catalog`)
      return r.json() as Promise<{ catalog: CatMetric[] }>
    },
    staleTime: 300_000,
  })

  const hosts = useQuery({
    queryKey: ['zbx-hosts', sid, search, groupid],
    enabled: !!sid && (tab === 'hosts' || tab === 'charts' || tab === 'overview'),
    queryFn: async () => {
      const r = await fetch(
        `${API_BASE_URL}/monitoring/zabbix/hosts?${qs({ source_id: sid, search, groupid, limit: 200 })}`,
      )
      return r.json() as Promise<{ ok: boolean; hosts: ZbxHost[]; groups: { groupid: string; name: string }[]; error?: string }>
    },
    refetchInterval: refreshMs,
  })

  const problems = useQuery({
    queryKey: ['zbx-problems', sid],
    enabled: !!sid && (tab === 'problems' || tab === 'overview'),
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/monitoring/zabbix/problems?${qs({ source_id: sid, limit: 80 })}`)
      return r.json() as Promise<{ ok: boolean; problems: ZbxProblem[]; error?: string }>
    },
    refetchInterval: refreshMs,
  })

  const coverage = useQuery({
    queryKey: ['zbx-coverage', sid],
    enabled: !!sid && tab === 'coverage',
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/monitoring/zabbix/coverage?${qs({ source_id: sid })}`)
      return r.json()
    },
  })

  const hostidsParam = selectedHosts.join(',')
  const hasHostSel = selectedHosts.length > 0

  const overviewSeries = useQuery({
    queryKey: ['zbx-series-ov', sid, overviewMetric, rangeSec],
    enabled: !!sid && tab === 'overview' && !!overviewMetric,
    queryFn: async () => {
      const r = await fetch(
        `${API_BASE_URL}/monitoring/zabbix/series?${qs({
          source_id: sid, metric: overviewMetric, range_sec: rangeSec, top_n: 5,
        })}`,
      )
      return r.json() as Promise<{ ok: boolean; series: ZbxSeries[]; unit?: string; title?: string }>
    },
    refetchInterval: refreshMs,
  })

  const slotQueries = useQueries({
    queries: slots.map((metric) => ({
      queryKey: ['zbx-series-slot', sid, metric, rangeSec, hostidsParam],
      enabled: !!sid && tab === 'charts' && !!metric && hasHostSel,
      queryFn: async () => {
        const r = await fetch(
          `${API_BASE_URL}/monitoring/zabbix/series?${qs({
            source_id: sid,
            metric,
            range_sec: rangeSec,
            top_n: MAX_HOSTS,
            hostids: hostidsParam,
          })}`,
        )
        return r.json() as Promise<{ ok: boolean; series: ZbxSeries[]; unit?: string; title?: string; error?: string }>
      },
      refetchInterval: refreshMs,
    })),
  })

  const metrics: CatMetric[] = catalog.data?.catalog || []
  const ov = overview.data
  const hostList = hosts.data?.hosts || []

  const toggleHost = (id: string) => {
    setSelectedHosts((prev) => {
      if (prev.includes(id)) return prev.filter((x) => x !== id)
      if (prev.length >= MAX_HOSTS) return prev
      return [...prev, id]
    })
  }

  const openHostsInCharts = (ids: string[]) => {
    setSelectedHosts(ids.slice(0, MAX_HOSTS))
    setTab('charts')
  }

  useEffect(() => {
    if (tab === 'charts' && !selectedHosts.length && hostList.length) {
      setSelectedHosts(hostList.slice(0, Math.min(3, hostList.length)).map((h) => h.hostid))
    }
  }, [tab, selectedHosts.length, hostList])

  const filteredProblems = useMemo(() => {
    const list = problems.data?.problems || []
    if (sevFilter === 'all') return list
    return list.filter((p) => Number(p.severity) === sevFilter)
  }, [problems.data, sevFilter])

  const tabs: { id: ZbxTab; label: string }[] = [
    { id: 'overview', label: t('mon_zbx_tab_overview') },
    { id: 'hosts', label: t('mon_zbx_tab_hosts') },
    { id: 'charts', label: t('mon_zbx_tab_charts') },
    { id: 'problems', label: t('mon_zbx_tab_problems') },
    { id: 'coverage', label: t('mon_zbx_tab_coverage') },
  ]

  const unitOf = (id: string) => metrics.find((m) => m.id === id)?.unit
  const titleOf = (id: string) => metrics.find((m) => m.id === id)?.title || id

  if (overview.isLoading && !ov) {
    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2">
          {Array.from({ length: 6 }).map((_, i) => <Skeleton key={i} className="h-[88px]" />)}
        </div>
        <Skeleton className="h-64" />
      </div>
    )
  }

  if (ov && ov.configured === false) {
    return <EmptyState title={ov.error || t('mon_zabbix_missing')} />
  }
  if (ov && ov.ok === false && ov.error) {
    return <ErrorBanner message={ov.error} hint={t('mon_zabbix_auth_hint')} />
  }

  const fsSlot = typeof fullscreen === 'number' ? fullscreen : null
  const fsSeries = fsSlot != null
    ? (slotQueries[fsSlot]?.data?.series || [])
    : (overviewSeries.data?.series || [])
  const fsMetric = fsSlot != null ? slots[fsSlot] : overviewMetric
  const fsUnit = fsSlot != null ? (slotQueries[fsSlot]?.data?.unit || unitOf(fsMetric)) : (overviewSeries.data?.unit || unitOf(overviewMetric))

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Activity size={16} className="text-blue-400 shrink-0" />
          <h3 className="text-[15px] font-semibold text-[var(--text-primary)] truncate">
            {titleLabel || ov?.source?.label || 'Zabbix'}
          </h3>
          <span className="text-[10px] font-mono text-[var(--text-muted)] px-1.5 py-0.5 rounded border border-white/[0.06]">
            v{ov?.zabbix_version || '—'}
          </span>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <div className="inline-flex rounded-md border border-white/[0.08] overflow-hidden">
            {RANGE_OPTS.map((r) => (
              <button
                key={r.sec}
                type="button"
                onClick={() => setRangeSec(r.sec)}
                className={`px-2 py-1 text-[11px] font-medium ${
                  rangeSec === r.sec ? 'bg-blue-600 text-white' : 'text-[var(--text-secondary)] hover:text-white'
                }`}
              >
                {r.label}
              </button>
            ))}
          </div>
          <button
            type="button"
            onClick={() => setAutoRefresh((v) => !v)}
            className={`inline-flex items-center gap-1 px-2 py-1 rounded-md border text-[11px] ${
              autoRefresh ? 'border-emerald-500/30 text-emerald-400 bg-emerald-500/10' : 'border-white/[0.08] text-[var(--text-muted)]'
            }`}
          >
            <RefreshCw size={12} />
            30s
          </button>
          <div className="inline-flex rounded-md border border-white/[0.08] overflow-hidden">
            {tabs.map((tb) => (
              <button
                key={tb.id}
                type="button"
                onClick={() => setTab(tb.id)}
                className={`px-2.5 py-1 text-[11px] font-medium ${
                  tab === tb.id ? 'bg-blue-600 text-white' : 'text-[var(--text-secondary)] hover:text-white'
                }`}
              >
                {tb.label}
              </button>
            ))}
          </div>
        </div>
      </div>

      {tab === 'overview' && (
        <div className="space-y-3">
          <div className="grid grid-cols-2 md:grid-cols-3 xl:grid-cols-6 gap-2">
            <KpiCard label="Hosts" value={ov?.hosts_enabled ?? '—'} hint={`toplam ${ov?.hosts_total ?? '—'}`} icon={Server} tone="info" />
            <KpiCard
              label="Problems"
              value={ov?.problems_count ?? '—'}
              hint={`${ov?.critical_count ?? 0} kritik/yüksek`}
              icon={AlertTriangle}
              tone={(ov?.critical_count || 0) > 0 ? 'crit' : (ov?.problems_count || 0) > 0 ? 'warn' : 'ok'}
            />
            <KpiCard label="Avg CPU" value={ov?.avg_cpu != null ? `${fmtNum(ov.avg_cpu)}%` : '—'} hint="örnek host’lar" icon={Cpu} tone="neutral" />
            <KpiCard label="Avg Memory" value={ov?.avg_mem != null ? `${fmtNum(ov.avg_mem)}%` : '—'} hint="örnek host’lar" icon={MemoryStick} tone="neutral" />
            <KpiCard label="Match map" value={ov?.catalog_size ?? metrics.length} hint="kanonik metrik" icon={CheckCircle2} tone="ok" />
            <KpiCard label="Source" value={<span className="text-sm font-mono">Zabbix</span>} hint={ov?.source?.url} icon={Network} tone="neutral" />
          </div>

          <div className="grid lg:grid-cols-5 gap-3">
            <div className="lg:col-span-3 rounded-xl border border-white/[0.06] bg-[var(--bg-surface)] p-3">
              <div className="flex items-center gap-2 mb-2">
                <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] shrink-0">
                  Top 5 · {t('mon_zbx_all_metrics')}
                </div>
                <MetricSelect
                  value={overviewMetric}
                  onChange={setOverviewMetric}
                  metrics={metrics}
                  className="flex-1 min-w-0 bg-[var(--bg-elevated)] border border-white/[0.08] rounded-md px-2 py-1 text-xs text-[var(--text-primary)]"
                />
                <button
                  type="button"
                  onClick={() => setFullscreen('overview')}
                  className="text-[var(--text-muted)] hover:text-white p-1"
                  title={t('mon_zbx_fullscreen')}
                >
                  <Maximize2 size={14} />
                </button>
              </div>
              <p className="text-[10px] text-[var(--text-muted)] mb-2">
                Seçili metrik için son değere göre en yüksek 5 host. Tüm host’lar için Grafikler sekmesinde çoklu seçim kullanın.
              </p>
              <SeriesChart
                series={overviewSeries.data?.series || []}
                unit={overviewSeries.data?.unit || unitOf(overviewMetric)}
                loading={overviewSeries.isFetching && !overviewSeries.data}
                threshold={overviewMetric.includes('pct') || overviewMetric.includes('util') ? 80 : undefined}
              />
            </div>
            <div className="lg:col-span-2 grid gap-3">
              <TopList
                title="Top CPU"
                unit="%"
                rows={(ov?.top_cpu || []).map((r: { hostid: string; host: string; value: number }) => r)}
                onSelect={(id) => openHostsInCharts([id])}
              />
              <TopList
                title="Top Memory"
                unit="%"
                rows={(ov?.top_mem || []).map((r: { hostid: string; host: string; value: number }) => r)}
                onSelect={(id) => openHostsInCharts([id])}
              />
            </div>
          </div>
        </div>
      )}

      {tab === 'hosts' && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative">
              <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={t('mon_zbx_host_search')}
                className="bg-[var(--bg-elevated)] border border-white/[0.08] rounded-md pl-7 pr-2 py-1.5 text-xs text-[var(--text-primary)] w-56"
              />
            </div>
            <select
              value={groupid}
              onChange={(e) => setGroupid(e.target.value)}
              className="bg-[var(--bg-elevated)] border border-white/[0.08] rounded-md px-2 py-1.5 text-xs text-[var(--text-secondary)] max-w-[14rem]"
            >
              <option value="">{t('mon_zbx_all_groups')}</option>
              {(hosts.data?.groups || []).map((g) => (
                <option key={g.groupid} value={g.groupid}>{g.name}</option>
              ))}
            </select>
            <span className="text-[11px] text-[var(--text-muted)]">
              {t('mon_zbx_selected_n', { n: selectedHosts.length })} · {t('mon_zbx_max_hosts')}
            </span>
            <button
              type="button"
              disabled={!selectedHosts.length}
              onClick={() => setTab('charts')}
              className="ml-auto text-[11px] px-2.5 py-1.5 rounded-md bg-blue-600 text-white disabled:opacity-40"
            >
              {t('mon_zbx_show_charts')}
            </button>
          </div>
          <div className="rounded-xl border border-white/[0.06] bg-[var(--bg-surface)] overflow-hidden">
            <table className="w-full text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] border-b border-white/[0.06] bg-black/20">
                <tr>
                  <th className="w-8 px-3 py-2.5">
                    <input
                      type="checkbox"
                      checked={hostList.length > 0 && hostList.slice(0, MAX_HOSTS).every((h) => selectedHosts.includes(h.hostid))}
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedHosts(hostList.slice(0, MAX_HOSTS).map((h) => h.hostid))
                        } else {
                          setSelectedHosts([])
                        }
                      }}
                    />
                  </th>
                  <th className="text-left px-3 py-2.5 font-bold">Name</th>
                  <th className="text-left px-3 py-2.5 font-bold">Host</th>
                  <th className="text-left px-3 py-2.5 font-bold">IP</th>
                  <th className="text-left px-3 py-2.5 font-bold">Groups</th>
                </tr>
              </thead>
              <tbody>
                {hostList.map((h) => {
                  const on = selectedHosts.includes(h.hostid)
                  const blocked = !on && selectedHosts.length >= MAX_HOSTS
                  return (
                    <tr
                      key={h.hostid}
                      className={`border-b border-white/[0.03] hover:bg-white/[0.03] ${on ? 'bg-blue-500/[0.06]' : ''}`}
                    >
                      <td className="px-3 py-2">
                        <input
                          type="checkbox"
                          checked={on}
                          disabled={blocked}
                          onChange={() => toggleHost(h.hostid)}
                        />
                      </td>
                      <td className="px-3 py-2 text-[var(--text-primary)] font-medium">{h.name}</td>
                      <td className="px-3 py-2 font-mono text-[var(--text-muted)]">{h.host}</td>
                      <td className="px-3 py-2 font-mono text-[var(--text-muted)]">{h.ip || '—'}</td>
                      <td className="px-3 py-2 text-[var(--text-muted)] truncate max-w-[14rem]">
                        {(h.groups || []).map((g) => g.name).join(', ')}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
            {hosts.data?.error && <p className="text-xs text-amber-400 p-3">{hosts.data.error}</p>}
          </div>
        </div>
      )}

      {tab === 'charts' && (
        <div className="space-y-3">
          <div className="grid lg:grid-cols-[240px_1fr] gap-3">
            {/* Host multi-select panel */}
            <div className="rounded-xl border border-white/[0.06] bg-[var(--bg-surface)] p-3 max-h-[70vh] overflow-hidden flex flex-col">
              <div className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)] mb-2">
                {t('mon_zbx_pick_hosts')}
              </div>
              <div className="relative mb-2">
                <Search size={12} className="absolute left-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
                <input
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  placeholder={t('mon_zbx_host_search')}
                  className="w-full bg-[var(--bg-elevated)] border border-white/[0.08] rounded-md pl-7 pr-2 py-1.5 text-xs text-[var(--text-primary)]"
                />
              </div>
              <div className="text-[10px] text-[var(--text-muted)] mb-1">
                {t('mon_zbx_selected_n', { n: selectedHosts.length })}
              </div>
              <ul className="flex-1 overflow-y-auto space-y-0.5 pr-1">
                {hostList.map((h) => {
                  const on = selectedHosts.includes(h.hostid)
                  const blocked = !on && selectedHosts.length >= MAX_HOSTS
                  return (
                    <li key={h.hostid}>
                      <label className={`flex items-center gap-2 px-1.5 py-1 rounded text-xs cursor-pointer ${
                        on ? 'bg-blue-500/15 text-blue-200' : 'text-[var(--text-secondary)] hover:bg-white/[0.03]'
                      } ${blocked ? 'opacity-40 cursor-not-allowed' : ''}`}>
                        <input
                          type="checkbox"
                          checked={on}
                          disabled={blocked}
                          onChange={() => toggleHost(h.hostid)}
                        />
                        <span className="truncate flex-1">{h.name}</span>
                      </label>
                    </li>
                  )
                })}
              </ul>
            </div>

            {/* Metric slots + charts */}
            <div className="space-y-3 min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-[10px] font-bold uppercase tracking-wider text-[var(--text-muted)]">
                  {t('mon_zbx_pick_metrics')}
                </span>
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setMetricPickerOpen((v) => !v)}
                    className="inline-flex items-center gap-1 text-[11px] px-2 py-1 rounded-md border border-white/[0.08] text-blue-300 hover:bg-blue-500/10"
                  >
                    <Plus size={12} />
                    {t('mon_zbx_add_metric')}
                  </button>
                  {metricPickerOpen && (
                    <div className="absolute z-20 mt-1 w-72 max-h-64 overflow-y-auto rounded-lg border border-white/[0.1] bg-[var(--bg-elevated)] shadow-xl p-1">
                      {metrics.map((m) => (
                        <button
                          key={m.id}
                          type="button"
                          className="w-full text-left px-2 py-1.5 text-xs text-[var(--text-secondary)] hover:bg-white/[0.05] rounded"
                          onClick={() => {
                            if (!slots.includes(m.id)) setSlots((s) => [...s, m.id])
                            setMetricPickerOpen(false)
                          }}
                        >
                          <span className="text-[var(--text-primary)]">{m.title}</span>
                          <span className="text-[var(--text-muted)] font-mono ml-1">{m.id}</span>
                          {m.unit && <span className="text-[var(--text-muted)] ml-1">· {m.unit}</span>}
                        </button>
                      ))}
                    </div>
                  )}
                </div>
                {!hasHostSel && (
                  <span className="text-[11px] text-amber-400">{t('mon_zbx_no_host_sel')}</span>
                )}
              </div>

              <div className="grid md:grid-cols-2 gap-3">
                {slots.map((metric, i) => {
                  const q = slotQueries[i]
                  return (
                    <div key={`${metric}-${i}`} className="rounded-xl border border-white/[0.06] bg-[var(--bg-surface)] overflow-hidden">
                      <div className="flex items-center gap-2 px-2 py-1.5 border-b border-white/[0.06]">
                        <HardDrive size={12} className="text-blue-400 shrink-0" />
                        <MetricSelect
                          value={metric}
                          onChange={(id) => {
                            setSlots((prev) => {
                              const next = [...prev]
                              next[i] = id
                              return next
                            })
                          }}
                          metrics={metrics}
                          className="flex-1 min-w-0 bg-transparent text-xs text-[var(--text-primary)] outline-none"
                        />
                        <button
                          type="button"
                          onClick={() => setFullscreen(i)}
                          className="text-[var(--text-muted)] hover:text-white p-1"
                          title={t('mon_zbx_fullscreen')}
                        >
                          <Maximize2 size={14} />
                        </button>
                        {slots.length > 1 && (
                          <button
                            type="button"
                            onClick={() => setSlots((prev) => prev.filter((_, j) => j !== i))}
                            className="text-[var(--text-muted)] hover:text-red-300 p-1"
                          >
                            <X size={14} />
                          </button>
                        )}
                      </div>
                      <div className="p-2">
                        {!hasHostSel ? (
                          <EmptyState title={t('mon_zbx_no_host_sel')} />
                        ) : (
                          <SeriesChart
                            series={q?.data?.series || []}
                            unit={q?.data?.unit || unitOf(metric)}
                            loading={!!q?.isFetching && !q?.data}
                            height={220}
                            threshold={metric.includes('pct') || metric.includes('util') ? 80 : undefined}
                          />
                        )}
                      </div>
                    </div>
                  )
                })}
              </div>
            </div>
          </div>
        </div>
      )}

      {tab === 'problems' && (
        <div className="space-y-2">
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              onClick={() => setSevFilter('all')}
              className={`text-[10px] font-bold uppercase px-2 py-1 rounded border ${
                sevFilter === 'all' ? 'border-blue-500/40 bg-blue-500/15 text-blue-300' : 'border-white/[0.08] text-[var(--text-muted)]'
              }`}
            >
              All
            </button>
            {[5, 4, 3, 2, 1].map((s) => {
              const m = severityMeta(s)
              return (
                <button
                  key={s}
                  type="button"
                  onClick={() => setSevFilter(s)}
                  className={`text-[10px] font-bold uppercase px-2 py-1 rounded border ${
                    sevFilter === s ? m.className : 'border-white/[0.08] text-[var(--text-muted)]'
                  }`}
                >
                  {m.label}
                </button>
              )
            })}
          </div>
          <div className="rounded-xl border border-white/[0.06] bg-[var(--bg-surface)] overflow-hidden">
            <table className="w-full text-xs">
              <thead className="text-[10px] uppercase tracking-wider text-[var(--text-muted)] border-b border-white/[0.06] bg-black/20">
                <tr>
                  <th className="text-left px-3 py-2.5 font-bold">Severity</th>
                  <th className="text-left px-3 py-2.5 font-bold">Problem</th>
                  <th className="text-left px-3 py-2.5 font-bold">Hosts</th>
                  <th className="text-left px-3 py-2.5 font-bold">Time</th>
                </tr>
              </thead>
              <tbody>
                {filteredProblems.map((p) => (
                  <tr key={p.eventid} className="border-b border-white/[0.03]">
                    <td className="px-3 py-2"><SeverityBadge severity={p.severity} /></td>
                    <td className="px-3 py-2 text-[var(--text-primary)]">{p.name}</td>
                    <td className="px-3 py-2 text-[var(--text-muted)]">{(p.hosts || []).join(', ') || '—'}</td>
                    <td className="px-3 py-2 font-mono text-[var(--text-muted)] whitespace-nowrap">
                      {p.clock ? new Date(Number(p.clock) * 1000).toLocaleString() : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            {!problems.isFetching && !filteredProblems.length && (
              <div className="p-6"><EmptyState title={t('mon_zbx_no_problems')} /></div>
            )}
          </div>
        </div>
      )}

      {tab === 'coverage' && (
        <div className="space-y-3">
          <div className="grid grid-cols-3 gap-2">
            <KpiCard label="Catalog" value={coverage.data?.catalog_total ?? '—'} icon={CheckCircle2} tone="info" />
            <KpiCard label="Mapped" value={coverage.data?.mapped_count ?? '—'} icon={CheckCircle2} tone="ok" />
            <KpiCard label="Unmapped" value={coverage.data?.unmapped_count ?? '—'} icon={AlertTriangle} tone="warn" />
          </div>
          <div className="grid md:grid-cols-2 gap-3">
            <div className="rounded-xl border border-white/[0.06] bg-[var(--bg-surface)] p-3 max-h-80 overflow-y-auto">
              <div className="text-[10px] font-bold uppercase tracking-wider text-emerald-400/90 mb-2">Mapped</div>
              <ul className="space-y-1.5">
                {(coverage.data?.mapped || []).map((m: { metric_id: string; title: string; examples?: { key: string }[] }) => (
                  <li key={m.metric_id} className="text-xs">
                    <button
                      type="button"
                      className="font-mono text-emerald-400/90 hover:underline"
                      onClick={() => {
                        if (!slots.includes(m.metric_id)) setSlots((s) => [...s, m.metric_id])
                        setTab('charts')
                      }}
                    >
                      {m.metric_id}
                    </button>
                    <span className="text-[var(--text-muted)]"> — {m.title}</span>
                  </li>
                ))}
              </ul>
            </div>
            <div className="rounded-xl border border-white/[0.06] bg-[var(--bg-surface)] p-3 max-h-80 overflow-y-auto">
              <div className="text-[10px] font-bold uppercase tracking-wider text-amber-400/90 mb-2">Unmapped / orphans</div>
              <ul className="space-y-1">
                {(coverage.data?.unmapped || []).map((m: { metric_id: string; title: string }) => (
                  <li key={m.metric_id} className="text-xs text-[var(--text-muted)]">
                    <span className="font-mono">{m.metric_id}</span> — {m.title}
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}

      {fullscreen != null && (
        <div
          className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4 md:p-8"
          onClick={() => setFullscreen(null)}
        >
          <div
            className="w-full max-w-6xl rounded-xl border border-white/[0.1] bg-[var(--bg-surface)] p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-3 gap-2">
              <div className="text-sm font-semibold text-[var(--text-primary)] truncate">
                {titleOf(fsMetric)}{fsUnit ? ` (${fsUnit})` : ''}
                {hasHostSel && fullscreen !== 'overview' && (
                  <span className="text-[11px] font-normal text-[var(--text-muted)] ml-2">
                    {selectedHosts.length} host
                  </span>
                )}
              </div>
              <button type="button" onClick={() => setFullscreen(null)} className="text-[var(--text-muted)] hover:text-white">
                <X size={18} />
              </button>
            </div>
            <SeriesChart
              series={fsSeries}
              unit={fsUnit}
              height={480}
              threshold={fsMetric.includes('pct') || fsMetric.includes('util') ? 80 : undefined}
            />
          </div>
        </div>
      )}
    </div>
  )
}

export default ZabbixMonitoringView
