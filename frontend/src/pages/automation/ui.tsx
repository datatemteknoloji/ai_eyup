import React from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ResponsiveContainer, LineChart, Line, BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, Legend,
} from 'recharts'
import { AlertTriangle, ArrowDown, ArrowUp, ArrowUpDown, CheckCircle2, Info, XCircle, ChevronRight, GitBranch } from 'lucide-react'
import { apiGet, executionPath, objectPath, qs, type AutomicSystem, type Execution } from './api'

export type SortDir = 'asc' | 'desc'

/** Kolon başlığı — tıklanınca sıralama; aktif kolon ok ile işaretlenir. */
export function SortTh({
  label, col, active, dir, onSort, className = '', title,
}: {
  label: string
  col: string
  active: string
  dir: SortDir
  onSort: (col: string) => void
  className?: string
  title?: string
}) {
  const is = active === col
  const Icon = !is ? ArrowUpDown : dir === 'asc' ? ArrowUp : ArrowDown
  return (
    <th className={`px-2 py-2 font-medium ${className}`} title={title}>
      <button type="button" onClick={() => onSort(col)}
        className={`inline-flex items-center gap-1 hover:text-white ${is ? 'text-slate-100' : 'text-slate-400'}`}>
        {label}
        <Icon size={11} className={is ? 'opacity-90' : 'opacity-40'} />
      </button>
    </th>
  )
}

export function toggleSort(prevCol: string, prevDir: SortDir, col: string): { col: string; dir: SortDir } {
  if (prevCol === col) return { col, dir: prevDir === 'asc' ? 'desc' : 'asc' }
  return { col, dir: 'asc' }
}

export function sortBy<T>(
  rows: T[],
  col: string,
  dir: SortDir,
  getters: Record<string, (r: T) => string | number | null | undefined>,
): T[] {
  const get = getters[col]
  if (!get) return rows
  const mul = dir === 'asc' ? 1 : -1
  return [...rows].sort((a, b) => {
    const va = get(a)
    const vb = get(b)
    if (va == null && vb == null) return 0
    if (va == null) return 1
    if (vb == null) return -1
    if (typeof va === 'number' && typeof vb === 'number') return (va - vb) * mul
    return String(va).localeCompare(String(vb), 'tr', { sensitivity: 'base', numeric: true }) * mul
  })
}

export const CLASS_COLORS: Record<string, string> = {
  ok: '#22c55e',
  failed: '#ef4444',
  cancelled: '#f59e0b',
  other: '#64748b',
}

export const CLASS_LABELS: Record<string, string> = {
  ok: 'Başarılı',
  failed: 'Hatalı',
  cancelled: 'İptal',
  other: 'Diğer',
}

export const chartTooltipStyle = {
  backgroundColor: '#131c2f', border: '1px solid rgba(255,255,255,0.1)', borderRadius: 8, fontSize: 12,
}

export function fmtDuration(sec: number | null | undefined): string {
  if (sec === null || sec === undefined || Number.isNaN(Number(sec))) return '—'
  const s = Math.round(Number(sec))
  if (s < 60) return `${s} sn`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m} dk ${s % 60} sn`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} sa ${m % 60} dk`
  return `${Math.floor(h / 24)} g ${h % 24} sa`
}

export function fmtDateTime(iso: string | null | undefined, withSeconds = false): string {
  if (!iso) return '—'
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return String(iso)
  return d.toLocaleString('tr-TR', {
    day: '2-digit', month: '2-digit', year: 'numeric', hour: '2-digit', minute: '2-digit',
    ...(withSeconds ? { second: '2-digit' } : {}),
  })
}

export function fmtAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  const d = new Date(iso).getTime()
  if (Number.isNaN(d)) return '—'
  const diff = Math.round((Date.now() - d) / 1000)
  if (diff < 0) return `${fmtDuration(-diff)} sonra`
  if (diff < 60) return 'az önce'
  return `${fmtDuration(diff)} önce`
}

export function fmtNumber(n: number | null | undefined): string {
  if (n === null || n === undefined) return '—'
  return Number(n).toLocaleString('tr-TR')
}

export function StatusBadge({ cls, code }: { cls: string | null | undefined; code?: number | null }) {
  const c = (cls || 'other').toString()
  const tone = c === 'ok' ? 'bg-green-500/15 text-green-300 border-green-500/30'
    : c === 'failed' ? 'bg-red-500/15 text-red-300 border-red-500/30'
      : c === 'cancelled' ? 'bg-amber-500/15 text-amber-300 border-amber-500/30'
        : 'bg-slate-500/15 text-slate-300 border-slate-500/30'
  const label = CLASS_LABELS[c] ?? (/^\d+$/.test(c) ? null : c)
  // Kod hem cls hem code ise bir kez göster (eski "1800 1800" tekrarı)
  const showCode = code != null && String(code) !== c
  return (
    <span className={`inline-flex items-center gap-1 rounded-md border px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap ${tone}`}>
      {label ? <span>{label}</span> : null}
      {(showCode || (!label && code != null)) ? (
        <span className="font-mono opacity-80">{code ?? c}</span>
      ) : null}
    </span>
  )
}

/** Altyapı üç değerli durum: bağlı / kopuk / bilinmiyor / missing (kaynaktan kayboldu). */
export function InfraStatusBadge({ status, label }: { status?: string | null; label?: string | null }) {
  const s = status || 'unknown'
  const tone = s === 'connected' ? 'bg-green-500/15 text-green-300 border-green-500/30'
    : s === 'disconnected' ? 'bg-red-500/15 text-red-300 border-red-500/30'
      : s === 'missing' ? 'bg-red-950/40 text-red-400/80 border-red-900/50'
        : 'bg-amber-500/15 text-amber-300 border-amber-500/30'
  return (
    <span className={`inline-flex items-center rounded-md border px-1.5 py-0.5 text-[11px] font-medium whitespace-nowrap ${tone}`}>
      {label || s}
    </span>
  )
}

/** Kart/KPI başlığı yanında (i) — tıklanınca bu verinin ne anlama geldiğini gösterir. */
export function HintInfo({ text, title }: { text: string; title?: string }) {
  const [open, setOpen] = React.useState(false)
  const ref = React.useRef<HTMLSpanElement>(null)
  React.useEffect(() => {
    if (!open) return
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    document.addEventListener('mousedown', onDoc)
    return () => document.removeEventListener('mousedown', onDoc)
  }, [open])
  return (
    <span ref={ref} className="relative inline-flex shrink-0 align-middle">
      <button type="button" onClick={e => { e.preventDefault(); e.stopPropagation(); setOpen(o => !o) }}
        title={title || 'Bu veri neyi gösterir?'}
        className="rounded p-0.5 text-slate-500 hover:bg-slate-700/60 hover:text-blue-300"
        aria-label="Açıklama">
        <Info size={13} />
      </button>
      {open && (
        <div className="absolute left-0 top-full z-40 mt-1 w-72 max-w-[min(18rem,calc(100vw-2rem))] rounded-xl border border-slate-600 bg-slate-900 p-3 text-[12px] font-normal leading-relaxed text-slate-300 shadow-xl"
          onClick={e => e.stopPropagation()}>
          {title && <div className="mb-1 text-[11px] font-semibold text-white">{title}</div>}
          <p className="whitespace-pre-wrap">{text}</p>
        </div>
      )}
    </span>
  )
}

export function Card({ title, actions, children, className = '', hint }: {
  title?: React.ReactNode
  actions?: React.ReactNode
  children: React.ReactNode
  className?: string
  /** Bu kartın verisinin ne anlama geldiği — başlık yanında (i) */
  hint?: string
}) {
  return (
    <div className={`rounded-2xl border border-slate-700/50 bg-slate-800/40 p-4 min-w-0 ${className}`}>
      {(title || actions || hint) && (
        <div className="mb-3 flex items-center justify-between gap-2">
          <h3 className="inline-flex min-w-0 items-center gap-1.5 text-sm font-semibold text-slate-200">
            <span className="min-w-0 truncate">{title}</span>
            {hint && <HintInfo text={hint} />}
          </h3>
          {actions}
        </div>
      )}
      {children}
    </div>
  )
}

export function EmptyNote({ children }: { children: React.ReactNode }) {
  return <p className="py-6 text-center text-xs text-slate-500">{children}</p>
}

export function ErrorNote({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error)
  return (
    <div className="rounded-xl border border-red-500/30 bg-red-500/10 px-4 py-3 text-sm text-red-200 flex items-start gap-2">
      <XCircle size={16} className="mt-0.5 flex-shrink-0" /> <span>{msg}</span>
    </div>
  )
}

export function useAutomicSystems() {
  return useQuery({
    queryKey: ['automic-systems'],
    queryFn: () => apiGet<AutomicSystem[]>('/systems'),
    staleTime: 60_000,
  })
}

/** Seçili sistem URL'de `?system=` olarak tutulur; yoksa varsayılan sistem. */
export function useSelectedSystem() {
  const [params, setParams] = useSearchParams()
  const systems = useAutomicSystems()
  const raw = params.get('system')
  const list = systems.data ?? []
  const selected = list.find(s => String(s.id) === raw) ?? list.find(s => s.is_default) ?? list[0] ?? null
  const setSystem = (id: number) => {
    const next = new URLSearchParams(params)
    next.set('system', String(id))
    setParams(next, { replace: true })
  }
  return { systems, selected, setSystem }
}

export function SystemPicker({ systems, value, onChange }: {
  systems: AutomicSystem[]
  value: number | null
  onChange: (id: number) => void
}) {
  if (systems.length <= 1) {
    return systems[0] ? <span className="text-xs text-slate-400">Sistem: <strong className="text-slate-200">{systems[0].name}</strong></span> : null
  }
  return (
    <select
      value={value ?? ''}
      onChange={e => onChange(Number(e.target.value))}
      className="rounded-lg border border-slate-600 bg-slate-800 px-3 py-1.5 text-sm text-white"
      style={{ colorScheme: 'dark' }}
    >
      {systems.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
    </select>
  )
}

export const RANGE_OPTIONS = ['1h', '6h', '24h', '7d', '30d', '90d']

export function RangePicker({ value, onChange, options = RANGE_OPTIONS }: {
  value: string
  onChange: (v: string) => void
  options?: string[]
}) {
  return (
    <div className="inline-flex rounded-lg border border-slate-700 bg-slate-800/60 p-0.5">
      {options.map(o => (
        <button
          key={o}
          type="button"
          onClick={() => onChange(o)}
          className={`px-2.5 py-1 text-xs rounded-md transition-colors ${value === o ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'}`}
        >
          {o}
        </button>
      ))}
    </div>
  )
}

export function ClientPicker({ clients, value, onChange }: {
  clients: number[]
  value: number[]
  onChange: (v: number[]) => void
}) {
  if (clients.length <= 1) return null
  const toggle = (c: number) => onChange(value.includes(c) ? value.filter(x => x !== c) : [...value, c].sort((a, b) => a - b))
  return (
    <div className="flex flex-wrap items-center gap-1">
      <span className="text-xs text-slate-500 mr-1">Client:</span>
      {clients.map(c => (
        <button
          key={c}
          type="button"
          onClick={() => toggle(c)}
          className={`rounded-md border px-2 py-0.5 text-xs font-mono ${value.length === 0 || value.includes(c)
            ? 'border-blue-500/50 bg-blue-500/15 text-blue-200' : 'border-slate-700 text-slate-500'}`}
        >
          {c}
        </button>
      ))}
      {value.length > 0 && (
        <button type="button" onClick={() => onChange([])} className="ml-1 text-[11px] text-slate-400 hover:text-white">tümü</button>
      )}
    </div>
  )
}

export function ExecLink({ systemId, e, children }: { systemId: number; e: Pick<Execution, 'client' | 'run_id'>; children?: React.ReactNode }) {
  return (
    <Link to={executionPath(systemId, e.client, e.run_id)} className="font-mono text-blue-300 hover:text-blue-200 hover:underline">
      {children ?? e.run_id}
    </Link>
  )
}

export function ObjectLink({ systemId, name }: { systemId: number; name: string }) {
  return (
    <Link to={objectPath(systemId, name)} className="text-slate-100 hover:text-blue-300 hover:underline break-all">
      {name}
    </Link>
  )
}

/** API sort anahtarları: end_desc|end_asc|duration_desc|duration_asc */
export function ExecutionTable({ systemId, rows, showClient = true, compact = false,
  sort, onSort,
}: {
  systemId: number
  rows: Execution[]
  showClient?: boolean
  compact?: boolean
  sort?: string
  onSort?: (apiSort: string) => void
}) {
  if (!rows.length) return <EmptyNote>Kayıt yok</EmptyNote>
  const active = sort?.startsWith('duration') ? 'duration' : sort?.startsWith('end') ? 'end' : ''
  const dir: SortDir = sort?.endsWith('_asc') ? 'asc' : 'desc'
  const click = (col: 'end' | 'duration') => {
    if (!onSort) return
    if (active === col) onSort(`${col}_${dir === 'asc' ? 'desc' : 'asc'}`)
    else onSort(col === 'end' ? 'end_desc' : 'duration_desc')
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-left text-xs">
        <thead className="text-slate-400 border-b border-slate-700/60">
          <tr>
            {onSort
              ? <SortTh label="Bitiş" col="end" active={active} dir={dir} onSort={() => click('end')} />
              : <th className="px-2 py-2 font-medium">Bitiş</th>}
            <th className="px-2 py-2 font-medium">Nesne</th>
            {!compact && <th className="px-2 py-2 font-medium">Tip</th>}
            <th className="px-2 py-2 font-medium">Durum</th>
            {onSort
              ? <SortTh label="Süre" col="duration" active={active} dir={dir} onSort={() => click('duration')} />
              : <th className="px-2 py-2 font-medium">Süre</th>}
            {!compact && <th className="px-2 py-2 font-medium">Agent</th>}
            {showClient && <th className="px-2 py-2 font-medium">Client</th>}
            <th className="px-2 py-2 font-medium">RunID</th>
          </tr>
        </thead>
        <tbody>
          {rows.map(r => (
            <tr key={`${r.client}-${r.run_id}`} className="border-b border-white/[0.04] hover:bg-white/[0.03]">
              <td className="px-2 py-1.5 whitespace-nowrap text-slate-400">{fmtDateTime(r.end_time)}</td>
              <td className="px-2 py-1.5">
                <ObjectLink systemId={systemId} name={r.object_name} />
                {r.error_signature && <div className="mt-0.5 text-[11px] text-red-300/80 font-mono truncate max-w-[28rem]" title={r.error_signature}>{r.error_signature}</div>}
              </td>
              {!compact && <td className="px-2 py-1.5 text-slate-400">{r.object_type ?? '—'}</td>}
              <td className="px-2 py-1.5"><StatusBadge cls={r.status_class} code={r.status_code} /></td>
              <td className="px-2 py-1.5 whitespace-nowrap text-slate-300">{fmtDuration(r.duration_sec)}</td>
              {!compact && <td className="px-2 py-1.5 text-slate-400">{r.agent ?? '—'}</td>}
              {showClient && <td className="px-2 py-1.5 font-mono text-slate-400">{r.client}</td>}
              <td className="px-2 py-1.5"><ExecLink systemId={systemId} e={r} /></td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function LogView({ content, maxHeight = '32rem' }: { content: string; maxHeight?: string }) {
  return (
    <pre
      className="overflow-auto rounded-lg border border-white/[0.08] bg-black/40 p-3 font-mono text-[11px] leading-relaxed text-slate-200 whitespace-pre"
      style={{ maxHeight }}
    >
      {content.split('\n').map((line, i) => {
        const bad = /\b(ORA-\d{4,5}|ERROR|FATAL|Exception|ABEND)\b/i.test(line)
        return <div key={i} className={bad ? 'bg-red-500/10 text-red-200' : undefined}>{line || ' '}</div>
      })}
    </pre>
  )
}

// ── Sohbet bileşenleri (backend `components` olayı) ────────────────────────

type Column = { key: string; label: string; type?: string }
export type AutomicComponent =
  | { type: 'kpi_row'; items: { label: string; value: any; tone?: string; format?: string }[] }
  | { type: 'table'; title?: string; system_id?: number; columns: Column[]; rows: Record<string, any>[]; total?: number }
  | { type: 'chart'; kind: 'line' | 'hbar' | 'stacked_bar'; title?: string; x: string; series: { key: string; label: string }[]; data: Record<string, any>[] }
  | { type: 'workflow_tree'; system_id?: number; parent_run_id?: number; nodes: Record<string, any>[] }
  | { type: 'log_excerpt'; title?: string; source?: string; truncated?: boolean; total_lines?: number; content: string }
  | { type: 'notice'; tone?: string; text: string }
  | { type: 'dependency_graph'; title?: string; system_id?: number; nodes: { id: string; label?: string; kind?: string; object_type?: string }[]; edges: { from: string; to: string; relation?: string }[] }

const SERIES_COLORS = ['#3b82f6', '#ef4444', '#f59e0b', '#22c55e', '#a855f7']

function kpiValue(v: any, format?: string) {
  if (v === null || v === undefined || v === '') return '—'
  if (format === 'duration') return fmtDuration(Number(v))
  if (format === 'pct') return `%${v}`
  return typeof v === 'number' ? fmtNumber(v) : String(v)
}

function cell(col: Column, row: Record<string, any>, systemId?: number) {
  const v = row[col.key]
  if (v === null || v === undefined || v === '') return <span className="text-slate-600">—</span>
  switch (col.type) {
    case 'datetime': return <span className="whitespace-nowrap">{fmtDateTime(String(v))}</span>
    case 'duration': return <span className="whitespace-nowrap">{fmtDuration(Number(v))}</span>
    case 'status': return <StatusBadge cls={String(v)} code={row.status_code} />
    case 'object': return systemId ? <ObjectLink systemId={systemId} name={String(v)} /> : String(v)
    case 'run':
      return systemId && row.client != null
        ? <ExecLink systemId={systemId} e={{ client: Number(row.client), run_id: Number(v) }} />
        : <span className="font-mono">{String(v)}</span>
    default:
      if (Array.isArray(v)) return v.join(', ')
      if (typeof v === 'object') return JSON.stringify(v)
      return String(v)
  }
}

export function ComponentTable({ c }: { c: Extract<AutomicComponent, { type: 'table' }> }) {
  return (
    <div className="overflow-x-auto rounded-lg border border-slate-700/60">
      <table className="w-full text-left text-xs">
        <thead className="bg-white/[0.04] text-slate-300">
          <tr>{c.columns.map(col => <th key={col.key} className="px-2.5 py-2 font-medium whitespace-nowrap">{col.label}</th>)}</tr>
        </thead>
        <tbody>
          {c.rows.slice(0, 200).map((r, i) => (
            <tr key={i} className="border-t border-white/[0.05] hover:bg-white/[0.03]">
              {c.columns.map(col => <td key={col.key} className="px-2.5 py-1.5 text-slate-200 align-top">{cell(col, r, c.system_id)}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {c.total != null && c.total > c.rows.length && (
        <p className="px-2.5 py-1.5 text-[11px] text-slate-500">{c.rows.length} / {c.total} satır gösteriliyor</p>
      )}
    </div>
  )
}

export function ComponentChart({ c, height = 240 }: { c: Extract<AutomicComponent, { type: 'chart' }>; height?: number }) {
  const data = c.data.map(d => ({ ...d, [c.x]: shortLabel(d[c.x]) }))
  if (c.kind === 'line') {
    const few = data.length <= 2
    const sparse = data.length > 2 && data.filter(d => c.series.some(s => Number(d[s.key]) > 0)).length <= 1
    return (
      <div>
        <ResponsiveContainer width="100%" height={height}>
          <LineChart data={data}>
            <CartesianGrid stroke="rgba(255,255,255,0.06)" />
            <XAxis dataKey={c.x} tick={{ fill: '#94a3b8', fontSize: 11 }} interval="preserveStartEnd" minTickGap={28} />
            <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
            <Tooltip contentStyle={chartTooltipStyle} />
            <Legend wrapperStyle={{ fontSize: 11 }} />
            {c.series.map((s, i) => (
              <Line key={s.key} type="monotone" dataKey={s.key} name={s.label}
                stroke={SERIES_COLORS[i % SERIES_COLORS.length]}
                dot={few ? { r: 3 } : false} strokeWidth={2} connectNulls={false} />
            ))}
          </LineChart>
        </ResponsiveContainer>
        {(few || sparse) && (
          <p className="mt-1 text-[11px] text-slate-500">
            {few
              ? `Bu aralıkta yalnızca ${data.length} veri noktası var; çizgi trendi için daha uzun geçmiş gerekir.`
              : 'Toplanmış veri henüz kısa; sıfır kovalar dolduruldu — gerçek aktivite tek güne yakın.'}
          </p>
        )}
      </div>
    )
  }
  if (c.kind === 'hbar') {
    return (
      <ResponsiveContainer width="100%" height={Math.max(height, data.length * 26 + 40)}>
        <BarChart data={data} layout="vertical" margin={{ left: 8 }}>
          <CartesianGrid stroke="rgba(255,255,255,0.06)" horizontal={false} />
          <XAxis type="number" tick={{ fill: '#94a3b8', fontSize: 11 }} />
          <YAxis type="category" dataKey={c.x} width={190} tick={{ fill: '#94a3b8', fontSize: 11 }} />
          <Tooltip contentStyle={chartTooltipStyle} />
          {c.series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.label} fill={SERIES_COLORS[(i + 1) % SERIES_COLORS.length]} radius={[0, 4, 4, 0]} />)}
        </BarChart>
      </ResponsiveContainer>
    )
  }
  const stackColors: Record<string, string> = { ok: CLASS_COLORS.ok, failed: CLASS_COLORS.failed, cancelled: CLASS_COLORS.cancelled }
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data}>
        <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
        <XAxis dataKey={c.x} tick={{ fill: '#94a3b8', fontSize: 11 }} />
        <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
        <Tooltip contentStyle={chartTooltipStyle} />
        <Legend wrapperStyle={{ fontSize: 11 }} />
        {c.series.map((s, i) => <Bar key={s.key} dataKey={s.key} name={s.label} stackId="a" fill={stackColors[s.key] ?? SERIES_COLORS[i % SERIES_COLORS.length]} />)}
      </BarChart>
    </ResponsiveContainer>
  )
}

function shortLabel(v: any): any {
  if (typeof v !== 'string') return v
  const m = v.match(/^(\d{4})-(\d{2})-(\d{2})(?:T(\d{2}):(\d{2}))?/)
  if (!m) return v
  return m[4] ? `${m[3]}.${m[2]} ${m[4]}:${m[5]}` : `${m[3]}.${m[2]}`
}

export function WorkflowTree({ nodes, systemId }: { nodes: Record<string, any>[]; systemId?: number }) {
  if (!nodes.length) return <EmptyNote>Alt adım yok</EmptyNote>
  return (
    <div className="space-y-1">
      {nodes.map(n => (
        <div key={`${n.client}-${n.run_id}`} className="flex items-center gap-2 rounded-lg border border-slate-700/50 bg-slate-900/40 px-2.5 py-1.5 text-xs">
          <GitBranch size={12} className="text-slate-500 flex-shrink-0" />
          <span className="min-w-0 flex-1 truncate">
            {systemId ? <ObjectLink systemId={systemId} name={n.object_name} /> : n.object_name}
            <span className="ml-1.5 text-slate-500">{n.object_type}</span>
          </span>
          <StatusBadge cls={n.status_class} code={n.status_code} />
          <span className="w-24 text-right text-slate-400">{fmtDuration(n.duration_sec)}</span>
          {systemId && n.client != null
            ? <ExecLink systemId={systemId} e={{ client: Number(n.client), run_id: Number(n.run_id) }}><ChevronRight size={14} /></ExecLink>
            : null}
        </div>
      ))}
    </div>
  )
}

export function NoticeBox({ tone, text }: { tone?: string; text: string }) {
  const cls = tone === 'critical' ? 'border-red-500/30 bg-red-500/10 text-red-200'
    : tone === 'warning' ? 'border-amber-500/30 bg-amber-500/10 text-amber-100'
      : tone === 'ok' ? 'border-green-500/30 bg-green-500/10 text-green-200'
        : 'border-blue-500/30 bg-blue-500/10 text-blue-100'
  const Icon = tone === 'critical' ? XCircle : tone === 'warning' ? AlertTriangle : tone === 'ok' ? CheckCircle2 : Info
  return (
    <div className={`flex items-start gap-2 rounded-lg border px-3 py-2 text-xs ${cls}`}>
      <Icon size={14} className="mt-0.5 flex-shrink-0" /><span className="font-mono break-all">{text}</span>
    </div>
  )
}

export function KpiTile({ label, value, tone, sub, hint }: {
  label: string; value: React.ReactNode; tone?: string; sub?: React.ReactNode; hint?: string
}) {
  const color = tone === 'critical' ? 'text-red-300' : tone === 'warning' ? 'text-amber-300' : tone === 'ok' ? 'text-green-300' : 'text-white'
  return (
    <div className="rounded-xl border border-slate-700/50 bg-slate-900/40 px-3 py-2.5 min-w-0">
      <div className="flex items-center gap-1 text-[11px] text-slate-400">
        <span className="truncate">{label}</span>
        {hint && <HintInfo text={hint} title={label} />}
      </div>
      <div className={`mt-0.5 text-lg font-semibold font-mono ${color}`}>{value}</div>
      {sub && <div className="text-[11px] text-slate-500">{sub}</div>}
    </div>
  )
}

export function AutomicComponents({ components }: { components: AutomicComponent[] }) {
  if (!components?.length) return null
  return (
    <div className="space-y-3">
      {components.map((c, i) => {
        switch (c.type) {
          case 'kpi_row':
            return (
              <div key={i} className="grid grid-cols-2 gap-2 sm:grid-cols-4">
                {c.items.map(it => <KpiTile key={it.label} label={it.label} value={kpiValue(it.value, it.format)} tone={it.tone} />)}
              </div>
            )
          case 'table':
            return (
              <div key={i}>
                {c.title && <div className="mb-1 text-xs font-medium text-slate-300">{c.title}</div>}
                <ComponentTable c={c} />
              </div>
            )
          case 'chart':
            return (
              <div key={i} className="rounded-lg border border-slate-700/60 p-2">
                {c.title && <div className="mb-1 text-xs font-medium text-slate-300">{c.title}</div>}
                <ComponentChart c={c} />
              </div>
            )
          case 'workflow_tree':
            return <WorkflowTree key={i} nodes={c.nodes} systemId={c.system_id} />
          case 'log_excerpt':
            return (
              <div key={i}>
                <div className="mb-1 flex items-center gap-2 text-xs text-slate-300">
                  <span className="font-medium">{c.title}</span>
                  {c.source && <span className="text-slate-500">kaynak: {c.source}</span>}
                  {c.truncated && <span className="text-amber-300">kırpıldı ({c.total_lines} satır)</span>}
                </div>
                <LogView content={c.content} maxHeight="20rem" />
              </div>
            )
          case 'notice':
            return <NoticeBox key={i} tone={c.tone} text={c.text} />
          case 'dependency_graph':
            return <DependencyGraph key={i} title={c.title} nodes={c.nodes || []} edges={c.edges || []} systemId={c.system_id} />
          default:
            return null
        }
      })}
    </div>
  )
}

export function DependencyGraph({ title, nodes, edges, systemId }: {
  title?: string
  nodes: { id: string; label?: string; kind?: string; object_type?: string }[]
  edges: { from: string; to: string; relation?: string }[]
  systemId?: number
}) {
  return (
    <div className="rounded-lg border border-slate-700/60 p-3">
      {title && <div className="mb-2 text-xs font-medium text-slate-300">{title}</div>}
      <div className="flex flex-wrap gap-2 mb-3">
        {nodes.map(n => (
          systemId ? (
            <Link key={n.id} to={objectPath(systemId, n.id)}
              className={`rounded-lg px-2 py-1 text-[11px] border ${n.kind === 'parent' ? 'border-violet-500/40 text-violet-200' : n.kind === 'child' ? 'border-blue-500/40 text-blue-200' : 'border-slate-600 text-slate-200'}`}>
              {n.label || n.id}{n.object_type ? ` · ${n.object_type}` : ''}
            </Link>
          ) : (
            <span key={n.id} className="rounded-lg border border-slate-600 px-2 py-1 text-[11px] text-slate-200">{n.label || n.id}</span>
          )
        ))}
      </div>
      {edges.length > 0 && (
        <ul className="space-y-1 font-mono text-[11px] text-slate-400">
          {edges.slice(0, 40).map((e, i) => (
            <li key={i}>{e.from} —{e.relation || '→'}→ {e.to}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

export function NoSystemNotice({ canManage }: { canManage?: boolean }) {
  return (
    <div className="mx-auto mt-10 max-w-xl rounded-2xl border border-slate-700/50 bg-slate-800/40 p-6 text-center">
      <h2 className="text-base font-semibold text-white">Tanımlı Automic sistemi yok</h2>
      <p className="mt-2 text-sm text-slate-400">
        Veri toplamak için önce Entegrasyonlar → UC4 Automic sayfasından bir sistem bağlantısı ekleyin.
      </p>
      {canManage !== false && (
        <Link to="/integrations/automic" className="mt-4 inline-block rounded-lg bg-blue-600 px-4 py-2 text-sm text-white hover:bg-blue-500">
          Automic entegrasyonuna git
        </Link>
      )}
    </div>
  )
}

type InfoRequirementGroup = { title: string; items: { must: boolean; text: string }[] }

type InfoData = {
  system: string | null; source_label?: string | null; source_type?: string | null
  clients: number[]; collection_windows: string; collection_interval_min: number
  source_lag_sec: number | null; max_staleness_min: number | null
  last_collection_at: string | null; last_new_record_at?: string | null
  last_ingest_rows?: number; zero_ingest_streak?: number
  ingest_stall_warning?: string | null
  next_collection_at: string | null
  circuit_open_sec: number; ingest_paused_reason: string | null
  retention: Record<string, number | undefined>
  quota: { usage_pct: number; quota_gb: number; level: string; used_bytes: number }
  fake?: boolean
  no_system?: boolean
  requirements?: InfoRequirementGroup[]
  module_db?: { host: string; port: string; name: string; user: string }
  ainew_ports?: { ui: number; api: number }
  connection_summary?: {
    host?: string | null; port?: number | null; service_name?: string | null
    user?: string | null; tcps?: boolean; source_type?: string
  } | null
  data_gaps?: {
    id: number; client?: number | null; id_min: number; id_max: number
    reason: string; detail?: string | null; detected_at?: string | null; label?: string
  }[]
  reconcile?: { items: { hour_utc?: string; source_count: number; module_count: number; diff_pct: number }[]; max_diff_pct: number }
  ae_version_note?: string
}

/** Her UC4 Automic sayfasında (i) bilgi paneli — davranış + kurulum gereksinimleri */
export function AutomicInfoButton({ systemId }: { systemId?: number }) {
  const [open, setOpen] = React.useState(false)
  const q = useQuery({
    queryKey: ['automic-info', systemId ?? 'default'],
    queryFn: () => apiGet<InfoData>(`/info${qs({ system_id: systemId })}`),
    enabled: open,
  })
  const d = q.data
  const r = d?.retention
  return (
    <>
      <button type="button" onClick={() => setOpen(true)} title="UC4 Automic — nasıl çalışır ve gereksinimler"
        className="rounded-lg border border-slate-700 p-1.5 text-slate-400 hover:text-white">
        <Info size={14} />
      </button>
      {open && (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/50" onClick={() => setOpen(false)}>
          <aside className="h-full w-full max-w-lg overflow-y-auto border-l border-slate-700 bg-slate-900 p-5 shadow-xl"
            onClick={e => e.stopPropagation()}>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="text-base font-semibold text-white">UC4 Automic — nasıl çalışır?</h2>
              <button type="button" onClick={() => setOpen(false)} className="text-slate-400 hover:text-white"><XCircle size={18} /></button>
            </div>
            {q.isLoading && <p className="text-sm text-slate-400">Yükleniyor…</p>}
            {q.error && <ErrorNote error={q.error} />}
            {d && (
              <div className="space-y-5 text-[15px] leading-relaxed text-slate-300" style={{ maxWidth: '75ch' }}>
                <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-3 font-mono text-[11px] text-slate-400">
                  AE Oracle (SELECT) → Collector → automic_db :{d.module_db?.port || '5435'} → API :{d.ainew_ports?.api || 8000} / UI :{d.ainew_ports?.ui || 3000}
                </div>

                <ul className="list-disc space-y-2 pl-5">
                  <li>UC4 Automic ortamına <strong className="text-white">yalnızca okuma</strong> amacıyla bağlanır. Hiçbir job&apos;ı başlatmaz, durdurmaz veya değiştirmez.</li>
                  {!d.no_system && (
                    <li>
                      Veriler <strong className="text-white">{d.source_label || d.source_type || '—'}</strong> kaynağından,
                      <strong className="text-white"> {d.collection_windows}</strong> saatleri arasında
                      <strong className="text-white"> {d.collection_interval_min}</strong> dakikada bir alınır.
                      Kaynağın kendi gecikmesi şu an <strong className="text-white">{d.source_lag_sec != null ? fmtDuration(d.source_lag_sec) : '—'}</strong>;
                      gösterilen veriler en fazla <strong className="text-white">{d.max_staleness_min != null ? `${d.max_staleness_min} dk` : '—'}</strong> gecikmeli olabilir.
                      Son toplama: <strong className="text-white">{fmtDateTime(d.last_collection_at)}</strong>
                      {d.last_new_record_at != null && (
                        <>; son yeni kayıt: <strong className="text-white">{fmtDateTime(d.last_new_record_at)}</strong></>
                      )}
                      {d.last_ingest_rows != null && (
                        <>; son turda yazılan: <strong className="text-white">{d.last_ingest_rows}</strong></>
                      )}.
                    </li>
                  )}
                  {d.ingest_stall_warning && (
                    <li className="list-none -ml-5 rounded-lg border border-red-500/40 bg-red-500/10 px-3 py-2 text-red-100">
                      {d.ingest_stall_warning}
                      {d.zero_ingest_streak != null && d.zero_ingest_streak > 0 && (
                        <> (sıfır yazım serisi: {d.zero_ingest_streak} tur)</>
                      )}
                    </li>
                  )}
                  <li>
                    Tüm çalışma kayıtları <strong className="text-white">{r?.executions_days ?? '—'} gün</strong>,
                    hata raporları <strong className="text-white">{r?.failed_report_excerpts_days ?? '—'} gün</strong> saklanır.
                    Daha eski dönemler için yalnızca hata özeti (<strong className="text-white">{r?.failed_index_days ?? '—'} gün</strong>)
                    ve günlük istatistikler (<strong className="text-white">{r?.daily_aggregates_days ?? '—'} gün</strong>) bulunur.
                  </li>
                  <li>
                    Depolama kotası <strong className="text-white">{d.quota?.quota_gb ?? '—'} GB</strong>
                    {d.quota ? <> (kullanım %{d.quota.usage_pct})</> : null}.
                    Kota dolmaya yaklaştığında en eski detay veriler önce silinir.
                  </li>
                  <li>Sorularınız yapay zekâ tarafından cevaplanır; her cevapta zaman aralığı ve güncellik belirtilir.</li>
                  <li>Raporlardaki şifre, IP ve kişisel veriler saklanmadan ve yapay zekâya gönderilmeden önce maskelenir.</li>
                </ul>

                {d.data_gaps && d.data_gaps.length > 0 && (
                  <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 p-3">
                    <div className="mb-2 text-xs font-medium text-amber-200">Kayıp veri (kaynakta bulunamayan RunID)</div>
                    <ul className="space-y-1 font-mono text-[11px] text-amber-100/90">
                      {d.data_gaps.slice(0, 8).map(g => (
                        <li key={g.id}>
                          [{g.id_min}–{g.id_max}) {g.client != null ? `client ${g.client}` : ''} — {g.reason}
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
                {d.reconcile && d.reconcile.items?.length > 0 && (
                  <div className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-3 text-xs">
                    <div className="mb-1 font-medium text-slate-200">
                      Mutabakat (max fark %{d.reconcile.max_diff_pct?.toFixed?.(1) ?? d.reconcile.max_diff_pct})
                    </div>
                    <ul className="space-y-0.5 font-mono text-[11px] text-slate-400">
                      {d.reconcile.items.slice(0, 5).map((r, i) => (
                        <li key={i}>{r.hour_utc?.slice(0, 16)} kaynak={r.source_count} modül={r.module_count} %{r.diff_pct}</li>
                      ))}
                    </ul>
                  </div>
                )}
                {d.ae_version_note && (
                  <p className="text-[11px] text-slate-500">{d.ae_version_note}</p>
                )}

                {d.requirements && d.requirements.length > 0 && (
                  <div className="space-y-3">
                    <h3 className="text-sm font-semibold text-white">Kurulum gereksinimleri</h3>
                    <p className="text-xs text-slate-500">Zorunlu maddeler yeşil etiketli; isteğe bağlı / sonraki sürüm sarı.</p>
                    {d.requirements.map(g => (
                      <div key={g.title} className="rounded-xl border border-slate-700/60 bg-slate-800/40 p-3">
                        <div className="mb-2 text-xs font-medium text-slate-200">{g.title}</div>
                        <ul className="space-y-2">
                          {g.items.map((it, i) => (
                            <li key={i} className="flex gap-2 text-[13px] leading-snug">
                              <span className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium ${it.must ? 'bg-emerald-500/15 text-emerald-300' : 'bg-amber-500/10 text-amber-200'}`}>
                                {it.must ? 'zorunlu' : 'öneri'}
                              </span>
                              <span className="text-slate-300">{it.text}</span>
                            </li>
                          ))}
                        </ul>
                      </div>
                    ))}
                  </div>
                )}

                <div className="rounded-xl border border-slate-700/60 bg-slate-800/50 p-3 text-xs">
                  <div className="mb-2 font-medium text-slate-200">Anlık durum</div>
                  <dl className="space-y-1">
                    <div className="flex justify-between gap-2"><dt className="text-slate-500">Sistem</dt><dd>{d.system || '—'}{d.fake ? ' (fake)' : ''}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-slate-500">Modül DB</dt><dd className="font-mono">{d.module_db ? `${d.module_db.host}:${d.module_db.port}/${d.module_db.name}` : '—'}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-slate-500">Ainew UI / API</dt><dd className="font-mono">:{d.ainew_ports?.ui ?? 3000} / :{d.ainew_ports?.api ?? 8000}</dd></div>
                    {d.connection_summary && (
                      <div className="flex justify-between gap-2">
                        <dt className="text-slate-500">AE kaynak</dt>
                        <dd className="font-mono text-right">
                          {d.connection_summary.source_type === 'fake'
                            ? 'fake'
                            : `${d.connection_summary.host || '—'}:${d.connection_summary.port ?? '—'} / ${d.connection_summary.service_name || '—'}${d.connection_summary.tcps ? ' (TCPS)' : ''}`}
                        </dd>
                      </div>
                    )}
                    <div className="flex justify-between gap-2"><dt className="text-slate-500">Client&apos;lar</dt><dd>{d.clients?.join(', ') || '—'}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-slate-500">Sonraki toplama</dt><dd>{fmtDateTime(d.next_collection_at)}</dd></div>
                    <div className="flex justify-between gap-2"><dt className="text-slate-500">Devre</dt><dd>{d.circuit_open_sec > 0 ? `açık (${fmtDuration(d.circuit_open_sec)})` : 'kapalı'}</dd></div>
                    {d.ingest_paused_reason && <div className="text-amber-300">Duraklatma: {d.ingest_paused_reason}</div>}
                    {d.quota && (
                      <div className="pt-2">
                        <div className="mb-1 flex justify-between text-slate-400"><span>Kota</span><span>%{d.quota.usage_pct}</span></div>
                        <div className="h-2 overflow-hidden rounded-full bg-slate-700">
                          <div className={`h-full ${d.quota.level === 'critical' ? 'bg-red-500' : d.quota.level === 'prune' || d.quota.level === 'warn' ? 'bg-amber-500' : 'bg-blue-500'}`}
                            style={{ width: `${Math.min(100, d.quota.usage_pct)}%` }} />
                        </div>
                      </div>
                    )}
                  </dl>
                </div>
              </div>
            )}
          </aside>
        </div>
      )}
    </>
  )
}
