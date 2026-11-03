import { LOAD_COLORS } from '../dashboard/ResourceCharts'

/** Eşik rengi: ResourceGauge ile aynı (%75 turuncu, %90 kırmızı) — sayfadaki tüm kullanım göstergeleri tutarlı. */
function loadColor(p: number): string {
  return p >= 90 ? LOAD_COLORS.crit : p >= 75 ? LOAD_COLORS.warn : LOAD_COLORS.ok
}

/** Küçük kullanım çubuğu; `title` ile kullanılan/toplam değeri tooltip'te gösterir. */
export default function UsageBar({ value, title }: { value: number | null | undefined; title?: string }) {
  if (value == null || Number.isNaN(value)) return <span className="text-slate-500">—</span>
  const v = Math.max(0, Math.min(100, value))
  const color = loadColor(v)
  return (
    <div className="flex items-center gap-2 min-w-[110px]" title={title} data-testid="usage-bar">
      <div className="h-1.5 flex-1 rounded-full bg-slate-800 overflow-hidden">
        <div className="h-full rounded-full" style={{ width: `${v}%`, background: color }} />
      </div>
      <span className="w-9 text-right tabular-nums" style={{ color }}>{Math.round(value)}%</span>
    </div>
  )
}

