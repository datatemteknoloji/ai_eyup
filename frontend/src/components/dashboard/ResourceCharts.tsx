import React, { useMemo, useState } from 'react'
import { Power, PowerOff } from 'lucide-react'
import { PieChart, Pie, Cell, ResponsiveContainer, Tooltip, BarChart, Bar, XAxis, YAxis, ReferenceLine } from 'recharts'
import { useT } from '../../i18n/LocaleProvider'
import { virtHostTitle, type VirtHostNameFields } from '../../lib/virtHostLabel'

/** Sanallaştırma panosundaki grafik renkleri — OpenShift aynı bileşeni kullanır. */
const NEON = {
  green: '#22c55e', red: '#ef4444', orange: '#f97316',
  cyan: '#06b6d4', info: '#38bdf8',
}

const fmtMem = (mb: number | null | undefined) => {
  if (mb == null || Number.isNaN(Number(mb))) return '—'
  const n = Number(mb)
  return n >= 1024 ? `${(n / 1024).toFixed(0)} GB` : `${Math.round(n)} MB`
}
const fmtDisk = (gb: number | null | undefined) => {
  if (gb == null || Number.isNaN(Number(gb))) return '—'
  const n = Number(gb)
  return n >= 1024 ? `${(n / 1024).toFixed(1)} TB` : `${n.toFixed(0)} GB`
}
const fmtCpu = (mhz: number | null | undefined) => {
  if (mhz == null || Number.isNaN(Number(mhz))) return '—'
  const n = Number(mhz)
  if (n >= 1000) return `${(n / 1000).toFixed(1)} GHz`
  return `${Math.round(n)} MHz`
}

export const fmtResource = (value: number | null | undefined, unit: string) => {
  if (unit === 'GB') return fmtDisk(value)
  if (unit === 'MB') return fmtMem(value)
  if (unit === 'MHz') return fmtCpu(value)
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${Math.round(Number(value))} ${unit}`
}

/** `compact`: kart çerçevesi ve «kullanılan/boş» satırı yok — başka bir kartın içine gömülür (yönetici özeti ortam kartı). */
export function ResourceGauge({ label, used, total, unit, accent, compact = false, footer }: {
  label: string; used: number; total: number; unit: string; accent: string; compact?: boolean; footer?: React.ReactNode
}) {
  const t = useT()
  const pct = total > 0 ? Math.round((used / total) * 100) : 0
  const free = Math.max(0, total - used)
  const getColor = (p: number) => p >= 90 ? NEON.red : p >= 75 ? NEON.orange : accent
  const text = (v: number) => unit === 'cores'
    ? `${v >= 10 ? v.toFixed(0) : v.toFixed(1)} ${t('cores')}`
    : fmtResource(v, unit)

  return (
    <div className={compact ? '' : 'bg-cyber-card rounded-xl border border-white/[0.06] p-5'}>
      <div className={`flex items-center justify-between ${compact ? 'mb-1.5' : 'mb-4'}`}>
        <span className={`${compact ? 'text-xs text-slate-400' : 'text-sm font-medium text-white'}`}>{label}</span>
        <span className="text-xs px-2 py-1 rounded-full" style={{ background: `${getColor(pct)}20`, color: getColor(pct) }}>
          {pct}%
        </span>
      </div>
      <div className={`${compact ? 'h-2' : 'h-3'} bg-slate-800 rounded-full overflow-hidden ${compact ? '' : 'mb-3'}`}>
        <div
          className="h-full rounded-full transition-all duration-500"
          style={{ width: `${Math.min(100, pct)}%`, background: `linear-gradient(90deg, ${accent}, ${getColor(pct)})`, boxShadow: `0 0 10px ${accent}60` }}
        />
      </div>
      {!compact && <div className="flex justify-between text-xs">
        <span className="text-slate-400">{t('hv_used')}: <span className="text-white font-medium">{text(used)}</span></span>
        <span className="text-slate-400">{t('hv_free')}: <span className="text-green-400 font-medium">{text(free)}</span></span>
      </div>}
      {footer}
    </div>
  )
}

export function VMStatusPie({ poweredOn, poweredOff }: { poweredOn: number; poweredOff: number }) {
  const t = useT()
  const total = poweredOn + poweredOff
  if (total === 0) return null

  const data = [
    { name: t('hv_running'), value: poweredOn, color: NEON.green },
    { name: t('power_off'), value: poweredOff, color: '#475569' },
  ].filter(d => d.value > 0)

  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-5">
      <h3 className="text-sm font-medium text-white mb-4">{t('hv_vm_status_dist')}</h3>
      <div className="flex items-center gap-6">
        <div className="relative">
          <ResponsiveContainer width={100} height={100}>
            <PieChart>
              <Pie data={data} cx="50%" cy="50%" innerRadius={30} outerRadius={45} paddingAngle={3} dataKey="value">
                {data.map((entry, i) => <Cell key={i} fill={entry.color} />)}
              </Pie>
              <Tooltip formatter={(v) => [`${v} VM`, '']} contentStyle={{ background: 'var(--bg-overlay)', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 12, color: 'var(--text-primary)' }} />
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex items-center justify-center">
            <span className="text-lg font-bold text-white">{total}</span>
          </div>
        </div>
        <div className="flex-1 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Power className="w-4 h-4 text-green-400" />
              <span className="text-sm text-slate-300">{t('hv_running')}</span>
            </div>
            <span className="text-sm font-bold text-green-400">{poweredOn}</span>
          </div>
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <PowerOff className="w-4 h-4 text-slate-500" />
              <span className="text-sm text-slate-300">{t('power_off')}</span>
            </div>
            <span className="text-sm font-bold text-slate-400">{poweredOff}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

export type ResourceChartHost = VirtHostNameFields & {
  cpu_usage_pct?: number | null
  mem_usage_pct?: number | null
  ds_usage_pct?: number | null
}

export type ResourceSeries = { key: string; label: string; color: string }

/**
 * Yatay çubuk karşılaştırma grafiği (sanallaştırma/OpenShift host grafiği ile aynı görünüm).
 * Yönetici özeti de kullanır: kümeler, depolama alanları. `threshold` varsa dikey eşik çizgisi çizer.
 */
export function ResourceBarsChart({ title, rows, series, labelWidth = 80, maxLabel = 14, threshold, note, height, footer }: {
  title: string
  rows: Array<Record<string, string | number>>
  series: ResourceSeries[]
  labelWidth?: number
  maxLabel?: number
  threshold?: number
  note?: string
  height?: number
  footer?: React.ReactNode
}) {
  if (rows.length === 0) return null
  const data = rows.map(r => {
    const name = String(r.name)
    return { ...r, name: name.length > maxLabel ? name.slice(0, maxLabel) + '…' : name, full: name }
  })
  const h = height ?? (rows.length <= 6 ? 180 : Math.min(560, rows.length * 28 + 16))
  return (
    <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-5">
      <h3 className={`text-sm font-medium text-white ${note ? 'mb-1' : 'mb-4'}`}>{title}</h3>
      {note && <p className="text-xs text-slate-400 mb-3">{note}</p>}
      <ResponsiveContainer width="100%" height={h}>
        <BarChart data={data} layout="vertical" margin={{ left: 0, right: 10 }}>
          <XAxis type="number" domain={[0, 100]} allowDataOverflow tick={{ fill: '#94a3b8', fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis type="category" dataKey="name" tick={{ fill: '#94a3b8', fontSize: 10 }} width={labelWidth} axisLine={false} tickLine={false} />
          <Tooltip
            contentStyle={{ background: 'var(--bg-overlay)', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 12, color: 'var(--text-primary)' }}
            labelFormatter={(_l, payload) => (payload?.[0]?.payload as { full?: string } | undefined)?.full ?? String(_l)}
            formatter={(v) => [`${v}%`, '']}
          />
          {threshold != null && <ReferenceLine x={threshold} stroke={NEON.orange} strokeDasharray="4 3" />}
          {series.map(item => (
            <Bar key={item.key} dataKey={item.key} name={item.label} fill={item.color} radius={[0, 4, 4, 0]} barSize={8} />
          ))}
        </BarChart>
      </ResponsiveContainer>
      <div className="flex justify-center gap-4 mt-2">
        {series.map(item => (
          <div key={item.key} className="flex items-center gap-1.5">
            <div className="w-2 h-2 rounded-full" style={{ background: item.color }} />
            <span className="text-xs text-slate-400">{item.label}</span>
          </div>
        ))}
        {threshold != null && <span className="text-xs text-slate-500">eşik %{threshold}</span>}
      </div>
      {footer}
    </div>
  )
}

/** Host'un en yüksek kaynak kullanımı (CPU/Bellek/Disk'ten büyüğü) — «en çok yük taşıyan» sıralaması için. */
export const hostLoadScore = (h: ResourceChartHost) =>
  Math.max(h.cpu_usage_pct || 0, h.mem_usage_pct || 0, h.ds_usage_pct || 0)

/** En yüksek kullanımdan düşüğe; eşitlikte üç kaynağın toplamı. Girdi değişmez. */
export const rankHostsByLoad = (hosts: ResourceChartHost[]): ResourceChartHost[] => {
  const sum = (h: ResourceChartHost) => (h.cpu_usage_pct || 0) + (h.mem_usage_pct || 0) + (h.ds_usage_pct || 0)
  return [...hosts].sort((a, b) => hostLoadScore(b) - hostLoadScore(a) || sum(b) - sum(a))
}

/**
 * Host kaynak kullanımı grafiği. `topN` verilirse host'lar en yüksek kullanıma göre sıralanır, ilk `topN` gösterilir ve
 * kalanı «Daha fazla» ile açılır (OpenShift gibi `limit` kullananlar eski davranışta kalır).
 */
export function HostResourceChart({ hosts, limit = 6, topN }: { hosts: ResourceChartHost[]; limit?: number; topN?: number }) {
  const t = useT()
  const [all, setAll] = useState(false)
  const ranked = useMemo(() => (topN ? rankHostsByLoad(hosts) : hosts), [hosts, topN])
  if (hosts.length === 0) return null
  const cap = topN ? (all ? ranked.length : topN) : limit
  const shown = ranked.slice(0, cap)
  const rows = shown.map(h => ({
    name: virtHostTitle(h),
    CPU: h.cpu_usage_pct || 0,
    Memory: h.mem_usage_pct || 0,
    Disk: h.ds_usage_pct || 0,
  }))
  const more = topN ? ranked.length - topN : 0
  return (
    <ResourceBarsChart
      title={t('hv_host_resource')}
      note={topN ? t('hv_host_top_note', { n: shown.length, total: ranked.length }) : undefined}
      rows={rows}
      height={topN && shown.length > 6 ? Math.min(1200, shown.length * 28 + 16) : undefined}
      series={[
        { key: 'CPU', label: 'CPU', color: NEON.cyan },
        { key: 'Memory', label: 'Memory', color: NEON.info },
        { key: 'Disk', label: 'Disk', color: NEON.orange },
      ]}
      footer={more > 0 ? (
        <button type="button" data-testid="hv-host-more" aria-expanded={all} onClick={() => setAll(v => !v)}
          className="mt-3 w-full text-xs text-blue-300 hover:text-blue-200 border border-white/[0.08] rounded-lg py-1.5">
          {all ? t('hv_host_less') : t('hv_host_more', { n: more })}
        </button>
      ) : undefined}
    />
  )
}

export const RESOURCE_ACCENT = {
  cpu: NEON.cyan,
  memory: NEON.info,
  disk: NEON.orange,
}

/** Uyarı/kritik renkleri: ResourceGauge ile aynı eşikler (%75 turuncu, %90 kırmızı). */
export const LOAD_COLORS = { warn: NEON.orange, crit: NEON.red, ok: NEON.green }
