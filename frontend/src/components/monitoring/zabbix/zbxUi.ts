/** Shared Zabbix monitoring UI types & helpers (ainew design tokens). */
export type ZbxTab = 'overview' | 'hosts' | 'charts' | 'problems' | 'coverage'

export type CatMetric = { id: string; title: string; unit: string; family: string }

export type ZbxHost = {
  hostid: string
  host: string
  name: string
  status?: string | number
  available?: string | number
  ip?: string
  groups?: { groupid: string; name: string }[]
}

export type ZbxProblem = {
  eventid: string
  name: string
  severity?: string | number
  clock?: string | number
  acknowledged?: string | number
  hosts?: string[]
}

export type ZbxSeries = {
  name: string
  hostid: string
  metric_id: string
  item_key?: string
  itemid?: string
  unit?: string
  points: { t: number; v: number }[]
}

export type RangeOpt = { sec: number; label: string }

export const RANGE_OPTS: RangeOpt[] = [
  { sec: 900, label: '15m' },
  { sec: 3600, label: '1h' },
  { sec: 21600, label: '6h' },
  { sec: 86400, label: '24h' },
  { sec: 604800, label: '7d' },
]

export const CHART_COLORS = [
  '#3b82f6', '#22c55e', '#f59e0b', '#06b6d4', '#a3e635', '#f97316', '#38bdf8', '#94a3b8',
]

/** Zabbix severity 0–5 */
export function severityMeta(sev: number | string | undefined | null): {
  level: number
  label: string
  className: string
  bar: string
} {
  const n = Number(sev)
  const level = Number.isFinite(n) ? n : 0
  switch (level) {
    case 5:
      return { level, label: 'Disaster', className: 'text-red-400 bg-red-500/10 border-red-500/30', bar: 'bg-red-500' }
    case 4:
      return { level, label: 'High', className: 'text-orange-400 bg-orange-500/10 border-orange-500/30', bar: 'bg-orange-500' }
    case 3:
      return { level, label: 'Average', className: 'text-amber-400 bg-amber-500/10 border-amber-500/30', bar: 'bg-amber-500' }
    case 2:
      return { level, label: 'Warning', className: 'text-yellow-300 bg-yellow-500/10 border-yellow-500/25', bar: 'bg-yellow-400' }
    case 1:
      return { level, label: 'Info', className: 'text-sky-400 bg-sky-500/10 border-sky-500/25', bar: 'bg-sky-400' }
    default:
      return { level: 0, label: 'N/C', className: 'text-slate-400 bg-white/[0.04] border-white/[0.08]', bar: 'bg-slate-500' }
  }
}

export function fmtNum(v: number | null | undefined, digits = 1): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const n = Math.abs(v)
  if (n >= 1_000_000_000) return `${(v / 1_000_000_000).toFixed(digits)}G`
  if (n >= 1_000_000) return `${(v / 1_000_000).toFixed(digits)}M`
  if (n >= 10_000) return `${(v / 1_000).toFixed(digits)}k`
  if (n >= 100) return v.toFixed(0)
  return v.toFixed(digits)
}

export function fmtUnit(v: number | null | undefined, unit?: string): string {
  if (v == null || !Number.isFinite(v)) return '—'
  const u = (unit || '').trim()
  if (u === '%' || u === 's' || u === '') return `${fmtNum(v)}${u ? u : ''}`
  if (u === 'B' || u === 'bytes') {
    const abs = Math.abs(v)
    if (abs >= 1e12) return `${(v / 1e12).toFixed(1)} TB`
    if (abs >= 1e9) return `${(v / 1e9).toFixed(1)} GB`
    if (abs >= 1e6) return `${(v / 1e6).toFixed(1)} MB`
    if (abs >= 1e3) return `${(v / 1e3).toFixed(1)} KB`
    return `${v.toFixed(0)} B`
  }
  if (u === 'b/s' || u === 'B/s') {
    const abs = Math.abs(v)
    const base = u === 'b/s' ? 1 : 8
    const bits = u === 'b/s' ? v : v * 8
    const a = Math.abs(bits)
    if (a >= 1e9) return `${(bits / 1e9).toFixed(1)} Gbps`
    if (a >= 1e6) return `${(bits / 1e6).toFixed(1)} Mbps`
    if (a >= 1e3) return `${(bits / 1e3).toFixed(1)} Kbps`
    return `${bits.toFixed(0)} bps`
    void base
  }
  return `${fmtNum(v)} ${u}`
}

export function qs(params: Record<string, string | number | undefined | null>) {
  const p = new URLSearchParams()
  Object.entries(params).forEach(([k, v]) => {
    if (v !== undefined && v !== null && String(v) !== '') p.set(k, String(v))
  })
  return p.toString()
}

export function chartRows(
  series: { name: string; points: { t: number; v: number }[] }[],
  bucketSec = 60,
) {
  const byT: Record<number, Record<string, number | string>> = {}
  series.forEach((s, i) => {
    const key = `s${i}`
    s.points.forEach((p) => {
      const t = bucketSec > 0 ? Math.floor(Number(p.t) / bucketSec) * bucketSec : Number(p.t)
      if (!byT[t]) byT[t] = { t }
      // aynı bucket’ta son değeri tut
      byT[t][key] = p.v
    })
  })
  const rows = Object.values(byT).sort((a, b) => Number(a.t) - Number(b.t))
  // İleri doldur — her seri için son bilinen değeri taşı (kesik çizgi olmasın)
  const last: Record<string, number> = {}
  const keys = series.map((_, i) => `s${i}`)
  for (const row of rows) {
    for (const k of keys) {
      if (typeof row[k] === 'number') last[k] = row[k] as number
      else if (last[k] != null) row[k] = last[k]
    }
  }
  return rows
}
