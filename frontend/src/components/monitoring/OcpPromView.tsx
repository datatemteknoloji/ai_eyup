/**
 * OpenShift Prometheus mode.
 * Varsayılan: Kubernetes Views — seri seçimi zorunlu (otomatik Top-N yok).
 * Kenarda: GPU/DCGM + KubeVirt VMI.
 */
import React, { useEffect, useMemo, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Maximize2, X, ChevronDown, Info } from 'lucide-react'
import {
  Area, AreaChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from 'recharts'
import { API_BASE_URL } from '../../config/api'
import { useT } from '../../i18n/LocaleProvider'

const COLORS = ['#3b82f6', '#10b981', '#f59e0b', '#ec4899', '#06b6d4', '#a3e635', '#f97316', '#38bdf8']

type TemplateId = 'views' | 'gpu' | 'kubevirt'
type ViewId = 'global' | 'namespaces' | 'nodes' | 'pods'

type ChartSeries = { name: string; points: { t: number; v: number }[] }
type TableColumn = { key: string; label: string }
type TableRow = Record<string, string | number | null | undefined>
type ViewChart = {
  id: string
  title: string
  unit?: string
  pick?: string | null
  help?: string
  ok?: boolean
  error?: string
  hint?: string
  need_selection?: string
  kind?: 'chart' | 'table'
  display?: string
  series: ChartSeries[]
  rows?: TableRow[]
  columns?: TableColumn[]
  total_series?: number
  truncated?: boolean
  series_cap?: number
}

const LEGEND_INLINE_MAX = 6

function InfoTip({ text }: { text?: string }) {
  if (!text) return null
  return (
    <span className="relative group inline-flex shrink-0 align-middle">
      <button
        type="button"
        className="p-0.5 rounded text-slate-500 hover:text-blue-300"
        aria-label="Bilgi"
        tabIndex={0}
      >
        <Info size={13} strokeWidth={2} />
      </button>
      <span
        role="tooltip"
        className="pointer-events-none absolute z-50 left-1/2 -translate-x-1/2 bottom-full mb-1.5 w-64 max-w-[70vw] rounded-md border border-white/[0.1] bg-[#0d1422] px-2.5 py-2 text-[11px] leading-snug text-slate-200 shadow-xl opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 transition-opacity"
      >
        {text}
      </span>
    </span>
  )
}

function chartRows(series: ChartSeries[]) {
  const byT: Record<number, Record<string, number | string>> = {}
  series.forEach((s, i) => {
    s.points.forEach((p) => {
      if (!byT[p.t]) byT[p.t] = { t: p.t }
      byT[p.t][`s${i}`] = p.v
    })
  })
  return Object.values(byT).sort((a, b) => Number(a.t) - Number(b.t))
}

function toggleIn(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((x) => x !== value) : [...list, value]
}

/** Çoklu seçim açılır menü — varsayılan boş; Tümü / Temizle. */
function MultiPick({
  label,
  options,
  selected,
  onChange,
  placeholder = 'Seçin…',
  disabled,
}: {
  label: string
  options: string[]
  selected: string[]
  onChange: (next: string[]) => void
  placeholder?: string
  disabled?: boolean
}) {
  const [open, setOpen] = useState(false)
  const [q, setQ] = useState('')
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    window.addEventListener('mousedown', onDown)
    return () => window.removeEventListener('mousedown', onDown)
  }, [open])
  const filtered = useMemo(() => {
    const qq = q.trim().toLowerCase()
    if (!qq) return options
    return options.filter((o) => o.toLowerCase().includes(qq))
  }, [options, q])
  const allFilteredSelected = filtered.length > 0 && filtered.every((o) => selected.includes(o))
  const summary = selected.length === 0
    ? placeholder
    : selected.length <= 2
      ? selected.join(', ')
      : `${selected.length} seçili`

  const toggleAllFiltered = () => {
    if (allFilteredSelected) {
      const drop = new Set(filtered)
      onChange(selected.filter((s) => !drop.has(s)))
    } else {
      onChange([...new Set([...selected, ...filtered])])
    }
  }

  return (
    <div className="relative" ref={ref}>
      <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold mb-0.5">{label}</div>
      <button
        type="button"
        disabled={disabled}
        onClick={() => setOpen((v) => !v)}
        className="min-w-[160px] max-w-[220px] h-[30px] flex items-center justify-between gap-2 bg-cyber-deep border border-white/[0.08] rounded-md px-2 text-xs text-left text-slate-200 disabled:opacity-40"
      >
        <span className="truncate">{summary}</span>
        <ChevronDown size={12} className="text-slate-500 shrink-0" />
      </button>
      {open && (
        <div className="absolute z-40 top-full mt-1 w-72 max-h-72 overflow-hidden rounded-lg border border-white/[0.1] bg-[#0d1422] shadow-xl">
          <div className="p-2 border-b border-white/[0.06] flex gap-2">
            <input
              autoFocus
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="Ara…"
              className="flex-1 bg-transparent text-xs text-white outline-none"
            />
            <button type="button" className="text-[10px] text-blue-400 hover:text-blue-300" onClick={toggleAllFiltered}>
              {allFilteredSelected ? 'Hiçbiri' : 'Tümü'}
            </button>
            <button type="button" className="text-[10px] text-slate-400" onClick={() => onChange([])}>Temizle</button>
          </div>
          <div className="max-h-56 overflow-y-auto p-1">
            {filtered.length > 0 && (
              <label className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-white/[0.04] cursor-pointer text-xs text-slate-300 border-b border-white/[0.06] mb-0.5">
                <input type="checkbox" checked={allFilteredSelected} onChange={toggleAllFiltered} />
                <span className="font-semibold">Tümü</span>
                <span className="text-slate-500 ml-auto">{filtered.length}</span>
              </label>
            )}
            {filtered.map((o) => {
              const on = selected.includes(o)
              return (
                <label key={o} className="flex items-center gap-2 px-2 py-1.5 rounded hover:bg-white/[0.04] cursor-pointer text-xs text-slate-200">
                  <input type="checkbox" checked={on} onChange={() => onChange(toggleIn(selected, o))} />
                  <span className="truncate font-mono">{o}</span>
                </label>
              )
            })}
            {!filtered.length && <div className="text-[11px] text-slate-500 p-2">Sonuç yok</div>}
          </div>
        </div>
      )}
    </div>
  )
}

function ChartCard({
  chart,
  height = 180,
  onExpand,
}: {
  chart: ViewChart
  height?: number
  onExpand?: () => void
}) {
  const kind = chart.kind || chart.display || 'chart'
  const isTable = kind === 'table'
  const series = chart.series || []
  const rows = chart.rows || []
  const columns = chart.columns?.length
    ? chart.columns
    : [
        { key: 'namespace', label: 'Namespace' },
        { key: 'pod', label: 'Pod' },
        { key: 'node', label: 'Node' },
      ]
  const data = useMemo(() => chartRows(series), [series])
  const emptyHint = chart.hint || chart.need_selection
    ? (chart.hint || `${chart.need_selection} seçin`)
    : 'Veri yok'
  const total = chart.total_series ?? (isTable ? rows.length : series.length)
  const truncated = !!chart.truncated || (isTable ? rows.length < total : series.length < total)
  const showInlineLegend = !isTable && series.length > 0 && series.length <= LEGEND_INLINE_MAX
  const showScrollLegend = !isTable && series.length > LEGEND_INLINE_MAX

  const hasContent = isTable ? rows.length > 0 : data.length > 0

  return (
    <div className="rounded-lg border border-white/[0.06] bg-cyber-card p-3 min-h-[220px] flex flex-col">
      <div className="flex items-start justify-between gap-2 mb-1">
        <div className="text-xs font-semibold text-slate-200 min-w-0 flex items-center gap-1.5 flex-wrap">
          <span className="truncate">{chart.title}</span>
          {chart.unit && !isTable ? (
            <span className="text-slate-500 font-normal shrink-0">({chart.unit})</span>
          ) : null}
          <InfoTip text={chart.help} />
          {truncated && total > 0 && (
            <span className="text-[10px] font-normal text-slate-500 tabular-nums">
              Top {isTable ? rows.length : series.length} / {total}
            </span>
          )}
          {isTable && !truncated && rows.length > 0 && (
            <span className="text-[10px] font-normal text-slate-500 tabular-nums">
              {rows.length} satır
            </span>
          )}
        </div>
        {onExpand && (
          <button
            type="button"
            onClick={onExpand}
            className="p-1 rounded text-slate-500 hover:text-white hover:bg-white/[0.06] shrink-0"
            title="Büyüt"
          >
            <Maximize2 size={14} />
          </button>
        )}
      </div>
      {chart.error && <p className="text-[11px] text-amber-400">{chart.error}</p>}
      {!chart.error && !hasContent && (
        <p className="text-[11px] text-slate-500 py-8 text-center">{emptyHint}</p>
      )}

      {isTable && rows.length > 0 && (
        <div
          className="flex-1 overflow-auto rounded border border-white/[0.04] mt-1"
          style={{ maxHeight: Math.max(height + 40, 200) }}
        >
          <table className="w-full text-left text-[11px]">
            <thead className="sticky top-0 bg-[#0d1422] z-10">
              <tr className="text-slate-500 border-b border-white/[0.06]">
                {columns.map((col) => (
                  <th key={col.key} className="px-2 py-1.5 font-medium whitespace-nowrap">
                    {col.label}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.map((row, i) => (
                <tr
                  key={i}
                  className="border-b border-white/[0.03] text-slate-300 hover:bg-white/[0.03]"
                >
                  {columns.map((col) => (
                    <td
                      key={col.key}
                      className="px-2 py-1 font-mono truncate max-w-[14rem]"
                      title={String(row[col.key] ?? '')}
                    >
                      {row[col.key] == null || row[col.key] === ''
                        ? '—'
                        : String(row[col.key])}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {!isTable && data.length > 0 && (
        <>
          <ResponsiveContainer width="100%" height={height}>
            <AreaChart data={data} margin={{ top: 4, right: 4, left: 0, bottom: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,0.06)" />
              <XAxis
                dataKey="t"
                tickFormatter={(v) => new Date(Number(v) * 1000).toLocaleTimeString()}
                stroke="#64748b"
                fontSize={9}
              />
              <YAxis stroke="#64748b" fontSize={9} width={44} />
              <Tooltip
                contentStyle={{
                  background: '#0d1422',
                  border: '1px solid rgba(255,255,255,0.1)',
                  fontSize: 11,
                  maxWidth: 320,
                }}
              />
              {showInlineLegend && (
                <Legend
                  wrapperStyle={{ fontSize: 10, paddingTop: 4 }}
                  iconSize={8}
                />
              )}
              {series.map((s, i) => (
                <Area
                  key={`${s.name}-${i}`}
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
          {showScrollLegend && (
            <ul className="mt-2 max-h-24 overflow-y-auto space-y-0.5 border-t border-white/[0.04] pt-1.5 pr-1">
              {series.map((s, i) => (
                <li
                  key={`${s.name}-${i}`}
                  className="flex items-center gap-1.5 text-[10px] text-slate-400 min-w-0"
                >
                  <span
                    className="w-2 h-2 rounded-sm shrink-0"
                    style={{ background: COLORS[i % COLORS.length] }}
                  />
                  <span className="truncate font-mono" title={s.name}>{s.name}</span>
                </li>
              ))}
            </ul>
          )}
        </>
      )}
    </div>
  )
}

function Stat({ label, value, mono }: { label: string; value: React.ReactNode; mono?: boolean }) {
  return (
    <div className="rounded-lg border border-white/[0.06] bg-cyber-card px-3 py-2">
      <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold">{label}</div>
      <div className={`text-base font-semibold text-slate-100 mt-0.5 ${mono ? 'font-mono text-sm' : ''}`}>{value}</div>
    </div>
  )
}

function fmtBytes(n?: number | null) {
  if (n == null || Number.isNaN(n)) return '—'
  const u = ['B', 'KiB', 'MiB', 'GiB', 'TiB']
  let v = n
  let i = 0
  while (v >= 1024 && i < u.length - 1) {
    v /= 1024
    i += 1
  }
  return `${v.toFixed(i > 1 ? 1 : 0)} ${u[i]}`
}

export const OcpPromView: React.FC<{ sourceId?: string }> = ({ sourceId }) => {
  const t = useT()
  const [template, setTemplate] = useState<TemplateId>('views')
  const [view, setView] = useState<ViewId>('global')
  const [metric, setMetric] = useState('gpu_util')
  const [rangeSec, setRangeSec] = useState(900)
  // Çoklu seçimler — varsayılan boş. Nodes tek seçici (instance ile aynı değerler).
  const [selNamespaces, setSelNamespaces] = useState<string[]>([])
  const [selNodes, setSelNodes] = useState<string[]>([])
  const [selPods, setSelPods] = useState<string[]>([])
  // Namespaces / Pods view için tek namespace bağlamı
  const [scopeNs, setScopeNs] = useState('')
  const [fullscreen, setFullscreen] = useState<ViewChart | null>(null)
  const qs = sourceId ? `&source_id=${encodeURIComponent(sourceId)}` : ''

  const { data: overview } = useQuery({
    queryKey: ['ocp-prom-overview', sourceId],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/monitoring/prom/overview?${qs.replace(/^&/, '')}`)
      return r.json()
    },
  })

  const catalogFamily = template === 'views' ? (view === 'namespaces' ? 'namespaces' : view) : template

  const { data: catalog } = useQuery({
    queryKey: ['ocp-prom-catalog', catalogFamily],
    enabled: template !== 'views',
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/monitoring/prom/catalog?family=${catalogFamily}`)
      return r.json() as Promise<{ metrics: { id: string; title: string; help?: string }[] }>
    },
  })

  useEffect(() => {
    if (template === 'gpu') setMetric('gpu_util')
    if (template === 'kubevirt') setMetric('vmi_cpu')
  }, [template])

  // View değişince seçimleri sıfırla (karışıklık olmasın)
  useEffect(() => {
    setSelNamespaces([])
    setSelNodes([])
    setSelPods([])
    setScopeNs('')
  }, [view])

  const needNsOpts = template === 'views' && (view === 'global' || view === 'namespaces' || view === 'pods')
  const needNodeOpts = template === 'views' && (view === 'global' || view === 'nodes')
  const needPodOpts = template === 'views' && (view === 'namespaces' || view === 'pods') && !!scopeNs

  const { data: nsOpts } = useQuery({
    queryKey: ['ocp-prom-labels-ns', sourceId],
    enabled: needNsOpts,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/monitoring/prom/labels?kind=namespace${qs}`)
      return r.json() as Promise<{ values: string[] }>
    },
  })
  const { data: nodeOpts } = useQuery({
    queryKey: ['ocp-prom-labels-node', sourceId],
    enabled: needNodeOpts,
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/monitoring/prom/labels?kind=node${qs}`)
      return r.json() as Promise<{ values: string[] }>
    },
  })
  const { data: podOpts } = useQuery({
    queryKey: ['ocp-prom-labels-pod', sourceId, scopeNs],
    enabled: needPodOpts,
    queryFn: async () => {
      const r = await fetch(
        `${API_BASE_URL}/openshift/monitoring/prom/labels?kind=pod&namespace=${encodeURIComponent(scopeNs)}${qs}`,
      )
      return r.json() as Promise<{ values: string[] }>
    },
  })

  // View’e göre API’ye gidecek seçimler — Nodes → hem node hem instance (aynı küme)
  const apiNamespace = useMemo(() => {
    if (view === 'global') return selNamespaces.join(',')
    if (view === 'namespaces' || view === 'pods') return scopeNs
    return ''
  }, [view, selNamespaces, scopeNs])
  const apiNode = useMemo(() => selNodes.join(','), [selNodes])
  const apiInstance = apiNode
  const apiPod = useMemo(() => selPods.join(','), [selPods])
  const viewsQs = [
    `view=${view}`,
    `range_sec=${rangeSec}`,
    `top_n=40`,
    apiNamespace ? `namespace=${encodeURIComponent(apiNamespace)}` : '',
    apiNode ? `node=${encodeURIComponent(apiNode)}` : '',
    apiInstance ? `instance=${encodeURIComponent(apiInstance)}` : '',
    apiPod ? `pod=${encodeURIComponent(apiPod)}` : '',
    qs.replace(/^&/, ''),
  ].filter(Boolean).join('&')

  const { data: viewsData, isFetching: viewsLoading } = useQuery({
    queryKey: ['ocp-prom-views', view, rangeSec, sourceId, apiNamespace, apiNode, apiInstance, apiPod],
    enabled: template === 'views',
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/monitoring/prom/views?${viewsQs}`)
      return r.json() as Promise<{ ok: boolean; charts: ViewChart[]; error?: string }>
    },
  })

  const { data: allocation } = useQuery({
    queryKey: ['ocp-prom-alloc', sourceId],
    enabled: template === 'gpu',
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/monitoring/prom/allocation?limit=80${qs}`)
      return r.json()
    },
  })

  const { data: seriesData, isFetching: seriesLoading } = useQuery({
    queryKey: ['ocp-prom-series', metric, rangeSec, sourceId],
    enabled: template === 'gpu' || template === 'kubevirt',
    queryFn: async () => {
      const r = await fetch(
        `${API_BASE_URL}/openshift/monitoring/prom/series?metric=${metric}&range_sec=${rangeSec}&top_n=8${qs}`,
      )
      return r.json()
    },
  })

  const chartData = useMemo(() => chartRows(seriesData?.series || []), [seriesData])

  if (overview && overview.configured === false) {
    return (
      <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-6 text-sm text-slate-400">
        {t('mon_ocp_prom_missing')}
      </div>
    )
  }

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7 gap-2">
        <Stat label="Nodes" value={overview?.nodes ?? '—'} />
        <Stat label="Namespaces" value={overview?.namespaces ?? '—'} />
        <Stat label="Running Pods" value={overview?.running_pods ?? '—'} />
        <Stat label="CPU" value={overview?.cpu_cores_used != null ? `${overview.cpu_cores_used}` : '—'} />
        <Stat label="Memory" value={fmtBytes(overview?.memory_used_bytes)} />
        <Stat label="VMI" value={overview?.vmi_count ?? 0} />
        <Stat label="GPU" value={overview?.gpu_count ?? 0} />
      </div>

      <div className="flex flex-wrap gap-2 items-center text-xs">
        <span className="text-[10px] uppercase tracking-wider text-slate-500 font-bold">Şablon</span>
        <div className="inline-flex rounded-md border border-white/[0.08] overflow-hidden">
          {([
            ['views', 'Kubernetes Views'],
            ['gpu', 'GPU / DCGM'],
            ['kubevirt', 'KubeVirt VMI'],
          ] as [TemplateId, string][]).map(([id, label]) => (
            <button
              key={id}
              type="button"
              onClick={() => setTemplate(id)}
              className={`px-2.5 py-1 ${template === id ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}
            >
              {label}
            </button>
          ))}
        </div>
        <select
          value={rangeSec}
          onChange={(e) => setRangeSec(Number(e.target.value))}
          className="bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1 text-xs text-slate-200 ml-auto"
        >
          <option value={900}>15m</option>
          <option value={3600}>1h</option>
          <option value={21600}>6h</option>
          <option value={86400}>24h</option>
        </select>
        {overview?.source?.label && (
          <span className="text-slate-500 font-mono truncate max-w-[12rem]">{overview.source.label}</span>
        )}
      </div>

      {template === 'views' && (
        <>
          <div className="flex flex-wrap gap-2 items-end">
            <div>
              <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold mb-0.5">Görünüm</div>
              <div className="inline-flex h-[30px] rounded-md border border-white/[0.08] overflow-hidden text-xs">
                {([
                  ['global', 'Global'],
                  ['namespaces', 'Namespaces'],
                  ['nodes', 'Nodes'],
                  ['pods', 'Pods'],
                ] as [ViewId, string][]).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    onClick={() => setView(id)}
                    className={`px-2.5 h-full ${view === id ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            </div>

            {view === 'global' && (
              <>
                <MultiPick
                  label="Namespaces"
                  options={nsOpts?.values || []}
                  selected={selNamespaces}
                  onChange={setSelNamespaces}
                  placeholder="Namespace seçin…"
                />
                <MultiPick
                  label="Nodes"
                  options={nodeOpts?.values || []}
                  selected={selNodes}
                  onChange={setSelNodes}
                  placeholder="Node seçin…"
                />
              </>
            )}
            {view === 'namespaces' && (
              <>
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold mb-0.5">Namespace</div>
                  <select
                    value={scopeNs}
                    onChange={(e) => { setScopeNs(e.target.value); setSelPods([]) }}
                    className="h-[30px] bg-cyber-deep border border-white/[0.08] rounded-md px-2 text-xs text-slate-200 max-w-[14rem]"
                  >
                    <option value="">Namespace seçin…</option>
                    {(nsOpts?.values || []).map((n) => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </select>
                </div>
                <MultiPick
                  label="Pods"
                  options={podOpts?.values || []}
                  selected={selPods}
                  onChange={setSelPods}
                  placeholder="Pod seçin…"
                  disabled={!scopeNs}
                />
              </>
            )}
            {view === 'nodes' && (
              <MultiPick
                label="Nodes"
                options={nodeOpts?.values || []}
                selected={selNodes}
                onChange={setSelNodes}
                placeholder="Node seçin…"
              />
            )}
            {view === 'pods' && (
              <>
                <div>
                  <div className="text-[9px] uppercase tracking-wider text-slate-500 font-bold mb-0.5">Namespace</div>
                  <select
                    value={scopeNs}
                    onChange={(e) => { setScopeNs(e.target.value); setSelPods([]) }}
                    className="h-[30px] bg-cyber-deep border border-white/[0.08] rounded-md px-2 text-xs text-slate-200 max-w-[14rem]"
                  >
                    <option value="">Namespace seçin…</option>
                    {(nsOpts?.values || []).map((n) => (
                      <option key={n} value={n}>{n}</option>
                    ))}
                  </select>
                </div>
                <MultiPick
                  label="Pods"
                  options={podOpts?.values || []}
                  selected={selPods}
                  onChange={setSelPods}
                  placeholder="Pod seçin…"
                  disabled={!scopeNs}
                />
              </>
            )}
          </div>

          <p className="text-[11px] text-slate-500">
            Grafana Kubernetes Views ile aynı panel seti. Global’de grafikler seçimsiz açılır;
            Namespace / Node seçimi isteğe bağlı daraltır. Namespaces / Nodes / Pods sekmelerinde gerekli bağlamı seçin (Tümü ile hepsini işaretleyebilirsiniz).
          </p>

          {viewsLoading && <p className="text-xs text-slate-500">{t('mon_loading')}</p>}
          {viewsData && !viewsData.ok && (
            <p className="text-xs text-amber-400">{viewsData.error}</p>
          )}
          <div className="grid md:grid-cols-2 gap-3">
            {(viewsData?.charts || []).map((c) => (
              <ChartCard key={c.id} chart={c} onExpand={() => setFullscreen(c)} />
            ))}
          </div>
        </>
      )}

      {(template === 'gpu' || template === 'kubevirt') && (
        <>
          {template === 'kubevirt' && (
            <p className="text-[11px] text-slate-500">
              KubeVirt / OpenShift Virtualization sanal makineleri (VMI): konuk VM’lerin CPU, bellek, disk ve ağ kullanımını Prometheus’taki <span className="font-mono text-slate-400">kubevirt_vmi_*</span> metriklerinden çizer. Kubernetes Views’tan bağımsızdır.
            </p>
          )}
          <div className="flex flex-wrap gap-2 items-center">
            <select
              value={metric}
              onChange={(e) => setMetric(e.target.value)}
              className="bg-cyber-deep border border-white/[0.08] rounded-md px-2 py-1 text-xs text-slate-200"
            >
              {(catalog?.metrics || []).map((m: { id: string; title: string; help?: string }) => (
                <option key={m.id} value={m.id}>{m.title}</option>
              ))}
            </select>
            <InfoTip
              text={(catalog?.metrics || []).find((m) => m.id === metric)?.help
                || (seriesData?.metric as { help?: string } | undefined)?.help}
            />
            {template === 'gpu' && overview?.gpu_count === 0 && (
              <span className="text-[11px] text-amber-400">Bu Prom’da DCGM metrikleri bulunamadı</span>
            )}
          </div>

          {template === 'gpu' && (
            <div className="rounded-xl border border-white/[0.06] bg-cyber-card overflow-x-auto">
              <div className="px-3 py-2 text-xs font-semibold text-slate-300 border-b border-white/[0.04]">
                {t('mon_gpu_allocation')}
              </div>
              <table className="w-full text-xs">
                <thead>
                  <tr className="text-slate-500 text-left">
                    <th className="px-3 py-2">Worker</th>
                    <th className="px-3 py-2">Namespace</th>
                    <th className="px-3 py-2">Pod</th>
                    <th className="px-3 py-2">GPU</th>
                    <th className="px-3 py-2">Util%</th>
                    <th className="px-3 py-2">Temp</th>
                    <th className="px-3 py-2">Power</th>
                    <th className="px-3 py-2">FB</th>
                  </tr>
                </thead>
                <tbody>
                  {(allocation?.rows || []).slice(0, 40).map((row: any, i: number) => (
                    <tr key={i} className="border-t border-white/[0.04] text-slate-300">
                      <td className="px-3 py-1.5 font-mono truncate max-w-[140px]">
                        {(row.hostname || '').split('.')[0]}
                      </td>
                      <td className="px-3 py-1.5">{row.namespace || '—'}</td>
                      <td className="px-3 py-1.5 truncate max-w-[160px]">{row.pod || '—'}</td>
                      <td className="px-3 py-1.5">{row.gpu ?? '—'}</td>
                      <td className={`px-3 py-1.5 font-mono ${(row.util ?? 0) > 90 ? 'text-amber-400' : ''}`}>
                        {row.util != null ? row.util.toFixed(0) : '—'}
                      </td>
                      <td className="px-3 py-1.5 font-mono">{row.temp != null ? row.temp.toFixed(0) : '—'}</td>
                      <td className="px-3 py-1.5 font-mono">{row.power != null ? row.power.toFixed(0) : '—'}</td>
                      <td className="px-3 py-1.5 font-mono">{row.fb_used != null ? row.fb_used.toFixed(0) : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              {!allocation?.ok && allocation?.error && (
                <p className="px-3 py-2 text-amber-400 text-xs">{allocation.error}</p>
              )}
              {allocation?.ok && !(allocation?.rows || []).length && (
                <p className="px-3 py-2 text-slate-500 text-xs">GPU satırı yok</p>
              )}
            </div>
          )}

          <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 min-h-[280px]">
            {seriesLoading && <p className="text-xs text-slate-500">{t('mon_loading')}</p>}
            {seriesData && !seriesData.ok && (
              <p className="text-xs text-amber-400">{seriesData.error}</p>
            )}
            {chartData.length > 0 && (
              <ResponsiveContainer width="100%" height={260}>
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
        </>
      )}

      {fullscreen && (
        <div
          className="fixed inset-0 z-50 bg-black/75 flex items-center justify-center p-4 md:p-8"
          onClick={() => setFullscreen(null)}
        >
          <div
            className="bg-[#0d1422] border border-white/[0.1] rounded-2xl w-full max-w-6xl p-4"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="flex items-center justify-between mb-3">
              <div className="text-sm font-semibold text-white">
                {fullscreen.title}
                {fullscreen.unit ? ` (${fullscreen.unit})` : ''}
              </div>
              <button type="button" onClick={() => setFullscreen(null)} className="text-slate-400 hover:text-white">
                <X size={18} />
              </button>
            </div>
            <ChartCard chart={fullscreen} height={480} />
          </div>
        </div>
      )}
    </div>
  )
}

export default OcpPromView
