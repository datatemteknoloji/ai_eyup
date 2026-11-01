import { RESOURCE_ACCENT, ResourceBarsChart } from '../../components/dashboard/ResourceCharts'
import type { Capacity, View } from './types'
import { Info, MUTED, cardStyle, parseTr } from './shared'

function Runway({ row }: { row: Capacity }) {
  const early = Number(row.early || 0)
  const late = Number(String(row.late || row.early || 0).replace('+', '')) || early
  const typical = Number(row.typical || early)
  const left = Math.min(100, (early / 12) * 100)
  const right = Math.min(100, (late / 12) * 100)
  return (
    <div style={{ position: 'relative', height: 16, background: 'var(--theme-muted)', borderRadius: 99, opacity: row.low ? 0.55 : 1 }}>
      {[3, 6, 12].map((month) => (
        <span key={month} style={{ position: 'absolute', left: `${(month / 12) * 100}%`, top: 0, bottom: 0, width: 1, background: 'var(--theme-border)' }} />
      ))}
      {row.early && (
        <span style={{ position: 'absolute', left: `${left}%`, width: `${Math.max(right - left, 1.5)}%`, top: 4, height: 8, borderRadius: 99, background: 'var(--theme-primary)' }} />
      )}
      {row.typical && (
        <span style={{ position: 'absolute', left: `calc(${Math.min(100, (typical / 12) * 100)}% - 4px)`, top: 4, width: 8, height: 8, borderRadius: 99, background: 'var(--theme-foreground)' }} />
      )}
    </div>
  )
}

/** Kapasite: eşiğe kalan süre, şu anki doluluk, yük devralma ve yatırım cümlesi; ardından takvim. */
export function CapacitySection({ view }: { view: View }) {
  const fill = (view.capacity || []).map((row) => ({ name: row.name, bellek: parseTr(row.now) || 0, islemci: parseTr(row.cpu) || 0 }))
  return (
    <>
      <section id="kapasite" style={cardStyle}>
        <div className="flex items-center justify-between">
          <h2 className="font-semibold">Eşiğe kalan süre</h2>
          <Info text="Tipik nokta koyu, erken ve geç uçlar çubuğun iki ucudur. 3, 6 ve 12. ay çizgileri referanstır. Soluk satır düşük güven demektir." />
        </div>
        {view.capacity.length === 0 && <p className="text-sm mt-2">Küme tahmini ölçülemedi çünkü 14 günlük bellek serisi yok.</p>}
        {view.capacity.map((row) => (
          <div key={row.name} className="mt-3">
            <div className="flex justify-between text-sm mb-1">
              <span>{row.name} · {row.resource}</span>
              <span>{row.early ? `${row.early}–${row.late || row.early} ay` : '—'}</span>
            </div>
            <Runway row={row} />
            {row.low && <p className="text-xs" style={{ color: MUTED }}>düşük güven</p>}
          </div>
        ))}
        <h2 className="font-semibold mt-4 mb-2">Şu anki doluluk</h2>
        {fill.length > 0 && (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
            <ResourceBarsChart title="Bellek" rows={fill} threshold={85} labelWidth={90} maxLabel={16} height={180} series={[{ key: 'bellek', label: 'Bellek', color: RESOURCE_ACCENT.memory }]} />
            <ResourceBarsChart title="İşlemci" rows={fill} threshold={80} labelWidth={90} maxLabel={16} height={180} series={[{ key: 'islemci', label: 'İşlemci', color: RESOURCE_ACCENT.cpu }]} />
          </div>
        )}
        <p className="text-sm mt-3">{view.failover || 'Bir sunucu arızalanırsa kalan kapasite bu pakette yok.'}</p>
        <p className="text-sm mt-1">{view.investment.sentence} {view.investment.value !== '—' ? `(${view.investment.value})` : ''}</p>
        <a href="#veri-kapsami" className="text-sm" style={{ color: 'var(--theme-link)' }}>OpenShift node ve Linux disk tahmini için veri yok</a>
      </section>

      <section id="takvim" className="print-break" style={cardStyle}>
        <h2 className="font-semibold mb-2">Yaklaşan takvim</h2>
        {(view.calendar?.bands || []).map((band) => (
          <div key={band.label} className="mb-2">
            <div className="flex justify-between text-sm"><span>{band.label}</span>{band.missing && <span>veri yok</span>}</div>
            <div style={{ position: 'relative', height: 10, background: 'var(--theme-muted)', borderRadius: 99, opacity: band.missing ? 0.45 : 1 }}>
              {!band.missing && band.early != null && (
                <span style={{ position: 'absolute', left: `${(band.early / 12) * 100}%`, width: `${Math.max(((band.late || band.early) - band.early) / 12 * 100, 2)}%`, top: 1, height: 8, borderRadius: 99, background: 'var(--theme-primary)' }} />
              )}
            </div>
          </div>
        ))}
        {!view.calendar && <p className="text-sm">Takvim ölçülemedi çünkü kilitli paket bu listeyi taşımıyor.</p>}
        <table className="w-full text-sm mt-3">
          <thead>
            <tr style={{ color: MUTED }}>
              <th className="text-left">Zaman</th><th className="text-left">Alan</th><th className="text-left">Olay</th><th className="text-left">Etki</th>
            </tr>
          </thead>
          <tbody>
            {(view.calendar?.items || []).map((item) => (
              <tr key={`${item.area}-${item.event}`}><td>{item.when}</td><td>{item.area}</td><td>{item.event}</td><td>{item.impact}</td></tr>
            ))}
          </tbody>
        </table>
      </section>
    </>
  )
}
