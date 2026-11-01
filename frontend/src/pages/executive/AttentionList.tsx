import { AlertOctagon, AlertTriangle, ChevronRight, Clock, Lightbulb } from 'lucide-react'
import { LOAD_COLORS, RESOURCE_ACCENT } from '../../components/dashboard/ResourceCharts'
import type { AttentionItem } from './types'
import { Info, MUTED, cardStyle } from './shared'

/** Önem rengi: donanım sorunu kırmızı, 30 günü aşan turuncu, diğerleri mavi. */
function tone(item: AttentionItem): string {
  if (item.hardware) return LOAD_COLORS.crit
  if (item.age_days >= 30) return LOAD_COLORS.warn
  return RESOURCE_ACCENT.cpu
}

function Pill({ children, color }: { children: React.ReactNode; color?: string }) {
  return (
    <span
      className="text-xs px-2 py-0.5 rounded-full whitespace-nowrap"
      style={color
        ? { color, background: `color-mix(in srgb, ${color} 14%, transparent)` }
        : { color: MUTED, background: 'var(--theme-muted)' }}
    >
      {children}
    </span>
  )
}

/** Tek «Dikkat gerektirenler» listesi: host sorunları ve öncelikli riskler varlık başına bir satır. */
export function AttentionList({ items, rule, onOpen }: { items: AttentionItem[]; rule?: string; onOpen: (item: AttentionItem) => void }) {
  return (
    <section id="dikkat" style={cardStyle}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex items-center gap-2">
          <h2 className="font-semibold">Dikkat gerektirenler</h2>
          {items.length > 0 && <Pill color={LOAD_COLORS.warn}>{items.length}</Pill>}
        </div>
        {rule && <Info text={rule} />}
      </div>
      <p className="text-sm mt-1" style={{ color: MUTED }}>Donanım sorunları önce, sonra en uzun süredir açık olanlar. Ayrıntı için satıra tıklayın.</p>
      {items.length === 0 && <p className="text-sm mt-3">Açık sorun yok.</p>}
      <ul className="mt-3 grid grid-cols-1 2xl:grid-cols-2 gap-2">
        {items.map((item) => {
          const color = tone(item)
          const Icon = item.hardware ? AlertOctagon : AlertTriangle
          const where = item.kind && item.environment ? `${item.kind} · ${item.environment}` : item.environment || ''
          return (
            <li key={`${item.title}-${item.problem}`}>
              <button
                type="button"
                onClick={() => onOpen(item)}
                className="w-full text-left flex gap-3 items-start rounded-lg p-3 transition-colors hover:brightness-95"
                style={{ background: 'var(--theme-background)', border: '1px solid var(--theme-border)', borderLeft: `4px solid ${color}`, color: 'inherit', cursor: 'pointer' }}
              >
                <span
                  className="mt-0.5 shrink-0 inline-flex items-center justify-center rounded-full"
                  style={{ width: 28, height: 28, color, background: `color-mix(in srgb, ${color} 16%, transparent)` }}
                >
                  <Icon size={16} aria-hidden />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                    <span className="font-semibold truncate" title={item.title}>{item.title}</span>
                    {item.hardware && <Pill color={LOAD_COLORS.crit}>Donanım</Pill>}
                    {where && <Pill>{where}</Pill>}
                    {!where && item.area && item.area !== item.title && <Pill>{item.area}</Pill>}
                  </span>
                  <span className="block text-sm mt-1">
                    {item.problem}
                    {item.extra > 0 && <span className="ml-2"><Pill color={color}>+{item.extra} bulgu daha</Pill></span>}
                  </span>
                  <span className="flex items-start gap-1.5 text-sm mt-1" style={{ color: MUTED }}>
                    <Lightbulb size={14} className="mt-0.5 shrink-0" aria-hidden />
                    <span>Olası çözüm: {item.action}</span>
                  </span>
                </span>
                <span className="shrink-0 flex flex-col items-end gap-1">
                  {item.age_days > 0 && (
                    <span className="inline-flex items-center gap-1 text-xs whitespace-nowrap" style={{ color }}>
                      <Clock size={12} aria-hidden />{item.age_days} gün
                    </span>
                  )}
                  <ChevronRight size={16} style={{ color: MUTED }} aria-hidden />
                </span>
              </button>
            </li>
          )
        })}
      </ul>
    </section>
  )
}
