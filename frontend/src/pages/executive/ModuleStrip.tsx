import type { Area, DemoCard } from './types'
import { Info, MUTED, cardStyle, linkButton, statusColor } from './shared'

/** Modül durumu: yalnız durum, tek cümle neden ve ilk iki sorun. Sayılar ortam kartlarında, ayrıntı çekmecede. */
export function ModuleStrip({ areas, demoCards, onOpen }: { areas: Area[]; demoCards: DemoCard[]; onOpen: (area: Area) => void }) {
  return (
    <section id="alanlar" className="grid grid-cols-1 md:grid-cols-2 2xl:grid-cols-4 gap-3">
      {areas.map((area) => (
        <article key={area.name} style={cardStyle} className="min-w-0">
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold">{area.name}</h2>
            <Info text={area.formula} />
          </div>
          <p className="inline-block text-sm font-semibold mt-1 px-2 py-0.5 rounded-full" style={{ color: statusColor(area.status), background: `color-mix(in srgb, ${statusColor(area.status)} 16%, transparent)` }}>{area.status}</p>
          <p className="text-sm mt-2">{area.reason}</p>
          {(area.issues || []).slice(0, 2).map((issue) => (
            <div key={issue.problem} className="text-sm mt-2">
              <p>{issue.problem}</p>
              <p style={{ color: MUTED }}>Olası çözüm: {issue.action}</p>
            </div>
          ))}
          <p className="text-xs mt-2" style={{ color: MUTED }}>{area.change}</p>
          <button type="button" onClick={() => onOpen(area)} style={{ ...linkButton, marginTop: 8 }}>Detay</button>
        </article>
      ))}
      {demoCards.filter((card) => card.title === 'UC4' && card.demo).map((card) => (
        <article key={card.title} style={{ ...cardStyle, borderStyle: 'dashed', outline: '1px dashed var(--warning)' }}>
          <div className="flex items-center justify-between gap-2">
            <h2 className="font-semibold">{card.title}</h2>
            <span style={{ color: 'var(--warning)' }}>DEMO · Örnek veri</span>
          </div>
          {card.lines.map((line) => (
            <p key={line.label} className="text-sm mt-2 flex justify-between gap-2"><span style={{ color: MUTED }}>{line.label}</span><span>{line.value}</span></p>
          ))}
        </article>
      ))}
    </section>
  )
}
