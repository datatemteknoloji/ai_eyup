/**
 * Yönetici raporu. Yalnız kilitli paketin sayfa modelini okur.
 * Başka modül sayfasına bağlantı yok. Renkler tema değişkenlerinden gelir.
 */
import { useState, type CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { API_BASE_URL } from '../config/api'
import { AiBlock } from '../components/insights/MethodBadge'

type Metric = { label: string; value: string }
type Area = {
  name: string
  status: string
  score: number | null
  reason: string
  metrics: Metric[]
  series: Array<{ day: string; area: string; severity: string; count: number }>
  formula: string
  change: string
  assets?: Array<{ name: string; status: string; critical: string; warning: string; usage: string }>
}
type Capacity = {
  name: string
  resource: string
  now: string
  cpu: string
  early: string | null
  typical: string | null
  late: string | null
  low: boolean
}
type Risk = { area: string; sentence: string; age: string; age_days: number; action: string; entity?: string | null }
type Idle = {
  categories: Array<{ name: string; count: string; vcpu: string; ram: string; disk: string }>
  top: Array<{ name: string; cluster: string; category: string; amount: string; age: string }>
  note: string
}
type Calendar = {
  bands: Array<{ label: string; early?: number; late?: number; missing?: boolean }>
  items: Array<{ when: string; area: string; event: string; impact: string }>
}
type DemoCard = { title: string; demo: boolean; status?: string; lines: Array<{ label: string; value: string }> }
type View = {
  summary?: { text: string; source: string }
  kpis: Array<{ label: string; value: string; hint: string }>
  areas: Area[]
  capacity: Capacity[]
  failover?: string
  investment: { value: string; sentence: string }
  calendar?: Calendar
  idle?: Idle
  operations?: string
  sources?: Array<{ label: string; count: string; trend: string }>
  risks: Risk[]
  risk_rule: string
  events: Array<{ day: string; area: string; severity: string; count: number }>
  coverage: { measured: number; total: number; rows: Array<{ section: string; status: string; missing: string; how: string }> }
  openshift_note: string
  formula: string
}
type Bundle = {
  status: 'empty' | 'ready'
  generated_at: string | null
  refreshing: boolean
  period: { start: string; end: string } | null
  months?: string[]
  summary?: string | null
  summary_source?: string | null
  view?: View | null
  demo_cards?: DemoCard[]
}

const AREAS = ['OpenShift', 'Sanallaştırma', 'Linux', 'Windows'] as const
const AREA_COLOR: Record<string, string> = {
  OpenShift: 'var(--theme-primary)',
  Sanallaştırma: 'var(--theme-link)',
  Linux: 'var(--theme-success-fg)',
  Windows: 'var(--warning)',
}

const cardStyle: CSSProperties = {
  background: 'var(--theme-card)',
  color: 'var(--theme-card-foreground)',
  border: '1px solid var(--theme-border)',
  borderRadius: 12,
  padding: 16,
}

function statusColor(status: string): string {
  if (status === 'Kritik') return 'var(--theme-destructive)'
  if (status === 'Dikkat') return 'var(--warning)'
  if (status === 'Normal') return 'var(--theme-success-fg)'
  return 'var(--theme-muted-foreground)'
}

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

function parseTr(value: string): number | null {
  if (!value || value === '—') return null
  const cleaned = value.replace(/\./g, '').replace(',', '.').replace(/[^\d.]/g, '')
  const num = Number.parseFloat(cleaned)
  return Number.isFinite(num) ? num : null
}

function Info({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <span className="text-xs" style={{ color: 'var(--theme-muted-foreground)' }}>Yöntem</span>
      <button type="button" aria-label="Yöntem bilgisi" onClick={() => setOpen((v) => !v)} style={{ color: 'var(--theme-link)', background: 'transparent', border: 0, cursor: 'pointer' }}>i</button>
      {open && (
        <span style={{ position: 'absolute', zIndex: 5, right: 0, top: '100%', width: 320, padding: 8, background: 'var(--theme-popover)', color: 'var(--theme-popover-foreground)', border: '1px solid var(--theme-border)', borderRadius: 8, fontSize: 12 }}>
          {text}
        </span>
      )}
    </span>
  )
}

function Spark({ series }: { series: Area['series'] }) {
  const data = Object.values(series.reduce<Record<string, { gun: string; adet: number }>>((acc, row) => {
    acc[row.day] = acc[row.day] || { gun: row.day.slice(8), adet: 0 }
    acc[row.day].adet += row.count
    return acc
  }, {}))
  if (!data.length) return <p className="text-xs mt-2" style={{ color: 'var(--theme-muted-foreground)' }}>Son 30 gün kaydı yok</p>
  return (
    <div style={{ width: '100%', height: 42, marginTop: 8 }}>
      <ResponsiveContainer>
        <BarChart data={data}>
          <Bar dataKey="adet" fill="var(--theme-primary)" />
        </BarChart>
      </ResponsiveContainer>
    </div>
  )
}

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

export function ExecutiveReportView({
  bundle,
  onRefresh,
  onMonth,
}: {
  bundle: Bundle
  onRefresh?: () => void
  onMonth?: (month: string) => void
}) {
  const view = bundle.view
  const [drawer, setDrawer] = useState<Area | Risk | 'idle' | null>(null)
  const [coverageOpen, setCoverageOpen] = useState(false)
  const [idleTab, setIdleTab] = useState<'vcpu' | 'ram' | 'disk'>('vcpu')
  const summary = view?.summary?.text || bundle.summary || 'Kilitli özet yok.'
  const source = view?.summary?.source || bundle.summary_source
  const months = bundle.months || []
  const currentMonth = bundle.period?.start?.slice(0, 7) || ''

  function csv() {
    const lines = ['Bölüm;Etiket;Değer']
    for (const kpi of view?.kpis || []) lines.push(['Gösterge', kpi.label, kpi.value].join(';'))
    for (const area of view?.areas || []) lines.push(['Alan', area.name, area.status].join(';'))
    for (const risk of view?.risks || []) lines.push(['Risk', risk.area, risk.sentence].join(';'))
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'yonetici-raporu.csv'
    a.click()
  }

  const fill = (view?.capacity || []).map((row) => ({
    ad: row.name,
    bellek: parseTr(row.now) || 0,
    islemci: parseTr(row.cpu) || 0,
  }))
  const eventDays = Object.values((view?.events || []).reduce<Record<string, { gun: string } & Record<string, number>>>((acc, row) => {
    acc[row.day] = acc[row.day] || { gun: row.day.slice(5), OpenShift: 0, Sanallaştırma: 0, Linux: 0, Windows: 0 }
    acc[row.day][row.area] = (acc[row.day][row.area] || 0) + row.count
    return acc
  }, {}))

  return (
    <div className="exec-report p-4 md:p-5 space-y-3 min-w-0" style={{ color: 'var(--theme-foreground)' }}>
      <style>{`
        .exec-report [data-ai-block] {
          background: color-mix(in srgb, var(--theme-primary) 10%, var(--theme-card));
          border-color: var(--theme-border);
          color: var(--theme-foreground);
        }
        .exec-report [data-ai-block] .text-slate-200,
        .exec-report [data-ai-block] .text-violet-300,
        .exec-report [data-ai-block] .text-violet-300\\/70 {
          color: var(--theme-card-foreground);
        }
        @media print {
          @page { size: A4 landscape; margin: 10mm; }
          .no-print { display: none !important; }
          .print-break { break-before: page; }
          .exec-report section { break-inside: avoid; }
        }
      `}</style>

      <header id="ust-bar" className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Yönetici Raporu</h1>
          <p className="text-sm" style={{ color: 'var(--theme-muted-foreground)' }}>
            {bundle.generated_at ? `Üretim ${new Date(bundle.generated_at).toLocaleString('tr-TR')}` : 'Kilitli rapor yok'}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          {months.length > 0 && (
            <select
              aria-label="Ay seçici"
              value={currentMonth}
              onChange={(event) => onMonth?.(event.target.value)}
              style={{ ...cardStyle, padding: '8px 12px' }}
            >
              {months.map((month) => <option key={month} value={month}>{month}</option>)}
            </select>
          )}
          <a href="#veri-kapsami" className="text-sm" style={{ color: 'var(--theme-link)' }}>
            {view ? `12 bölümden ${view.coverage.measured} bölüm ölçülebildi` : 'Veri kapsamı'}
          </a>
          <button type="button" className="no-print" onClick={onRefresh} style={cardStyle}>Şimdi yenile</button>
          <button type="button" className="no-print" onClick={() => window.print()} style={cardStyle}>PDF</button>
          <button type="button" className="no-print" onClick={csv} style={cardStyle}>CSV</button>
        </div>
      </header>

      {!view && <p style={{ color: 'var(--theme-muted-foreground)' }}>Kilitli raporun sayfa modeli yok. Şimdi yenile ile üretilir. Açılışta hesaplama yapılmaz.</p>}

      {view && (
        <>
          <section id="ozet" className="grid grid-cols-1 2xl:grid-cols-[1.4fr_1fr] gap-3">
            <AiBlock method="exec.ops.duration" title={source === 'template' ? 'Şablon özet' : 'Özet'}>
              <p>{summary}</p>
            </AiBlock>
            <div className="grid grid-cols-2 gap-3">
              {view.kpis.map((kpi) => (
                <article key={kpi.label} style={cardStyle}>
                  <p className="text-xs" style={{ color: 'var(--theme-muted-foreground)' }}>{kpi.label}</p>
                  <p className="text-lg font-semibold">{kpi.value}</p>
                  {kpi.hint && <p className="text-xs" style={{ color: 'var(--theme-muted-foreground)' }}>{kpi.hint}</p>}
                </article>
              ))}
            </div>
          </section>

          <section id="alanlar" className="grid grid-cols-1 2xl:grid-cols-4 gap-3">
            {view.areas.map((area) => (
              <article key={area.name} style={cardStyle} className="min-w-0">
                <div className="flex items-center justify-between gap-2">
                  <h2 className="font-semibold">{area.name}</h2>
                  <Info text={area.formula} />
                </div>
                <p className="inline-block text-sm font-semibold mt-1 px-2 py-0.5 rounded-full" style={{ color: statusColor(area.status), background: `color-mix(in srgb, ${statusColor(area.status)} 16%, transparent)` }}>{area.status}</p>
                <p className="text-sm mt-2">{area.reason}</p>
                <ul className="text-sm mt-2 space-y-1">
                  {area.metrics.map((metric) => (
                    <li key={metric.label} className="flex justify-between gap-2"><span style={{ color: 'var(--theme-muted-foreground)' }}>{metric.label}</span><span>{metric.value}</span></li>
                  ))}
                </ul>
                <Spark series={area.series} />
                <p className="text-xs mt-2" style={{ color: 'var(--theme-muted-foreground)' }}>{area.change}</p>
                <button type="button" onClick={() => setDrawer(area)} style={{ color: 'var(--theme-link)', background: 'transparent', border: 0, marginTop: 8 }}>Detay</button>
              </article>
            ))}
          </section>

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
                {row.low && <p className="text-xs" style={{ color: 'var(--theme-muted-foreground)' }}>düşük güven</p>}
              </div>
            ))}
            <h2 className="font-semibold mt-4 mb-2">Şu anki doluluk</h2>
            {fill.length > 0 && (
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-3">
                <FillChart title="Bellek" dataKey="bellek" threshold={85} data={fill} />
                <FillChart title="İşlemci" dataKey="islemci" threshold={80} data={fill} />
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
                <div style={{ position: 'relative', height: 10, background: band.missing ? 'var(--theme-muted)' : 'var(--theme-muted)', borderRadius: 99, opacity: band.missing ? 0.45 : 1 }}>
                  {!band.missing && band.early != null && (
                    <span style={{ position: 'absolute', left: `${(band.early / 12) * 100}%`, width: `${Math.max(((band.late || band.early) - band.early) / 12 * 100, 2)}%`, top: 1, height: 8, borderRadius: 99, background: 'var(--theme-primary)' }} />
                  )}
                </div>
              </div>
            ))}
            {!view.calendar && <p className="text-sm">Takvim ölçülemedi çünkü kilitli paket bu listeyi taşımıyor.</p>}
            <table className="w-full text-sm mt-3">
              <thead>
                <tr style={{ color: 'var(--theme-muted-foreground)' }}>
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

          <section id="riskler" style={cardStyle}>
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Öncelikli riskler</h2>
              <Info text={view.risk_rule} />
            </div>
            {view.risks.length === 0 && <p className="text-sm mt-2">Açık bulgu yok.</p>}
            <table className="w-full text-sm mt-2">
              <thead>
                <tr style={{ color: 'var(--theme-muted-foreground)' }}>
                  <th className="text-left">Alan</th>
                  <th className="text-left">Risk</th>
                  <th className="text-left">Etki</th>
                  <th className="text-left">Kaç gündür</th>
                  <th className="text-left">Aksiyon</th>
                </tr>
              </thead>
              <tbody>
                {view.risks.map((risk) => (
                  <tr key={`${risk.area}-${risk.sentence}`} onClick={() => setDrawer(risk)} style={{ cursor: 'pointer' }}>
                    <td>{risk.area}</td>
                    <td>{risk.sentence}</td>
                    <td>Açık bulgu</td>
                    <td style={{ color: risk.age_days >= 90 ? 'var(--theme-destructive)' : risk.age_days >= 30 ? 'var(--warning)' : 'var(--theme-foreground)' }}>{risk.age} gün</td>
                    <td>{risk.action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section id="atil" style={cardStyle}>
            <div className="flex items-center justify-between gap-2">
              <h2 className="font-semibold">Atıl kaynak</h2>
              <button type="button" onClick={() => setDrawer('idle')} style={{ color: 'var(--theme-link)', background: 'transparent', border: 0 }}>İlk 10</button>
            </div>
            <p className="text-sm mt-1">{view.idle?.note || 'Atıl kaynak ölçülemedi çünkü kilitli paket bu listeyi taşımıyor.'}</p>
            <div className="flex gap-2 mt-2">
              {(['vcpu', 'ram', 'disk'] as const).map((tab) => (
                <button key={tab} type="button" onClick={() => setIdleTab(tab)} style={{ ...cardStyle, padding: '4px 10px', borderColor: idleTab === tab ? 'var(--theme-primary)' : 'var(--theme-border)' }}>
                  {tab === 'vcpu' ? 'vCPU' : tab === 'ram' ? 'RAM' : 'Disk'}
                </button>
              ))}
            </div>
            {view.idle && (
              <div style={{ width: '100%', height: 180 }} className="mt-2">
                <ResponsiveContainer>
                  <BarChart data={view.idle.categories.map((row) => ({ ad: row.name, miktar: parseTr(row[idleTab]) || 0 }))}>
                    <XAxis dataKey="ad" stroke="var(--theme-muted-foreground)" />
                    <YAxis stroke="var(--theme-muted-foreground)" />
                    <Tooltip />
                    <Bar dataKey="miktar" fill="var(--theme-primary)" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
            )}
          </section>

          <section id="olay" style={cardStyle}>
            <h2 className="font-semibold mb-2">Olay ve operasyon</h2>
            <div style={{ width: '100%', height: 200 }}>
              <ResponsiveContainer>
                <BarChart data={eventDays}>
                  <XAxis dataKey="gun" stroke="var(--theme-muted-foreground)" />
                  <YAxis stroke="var(--theme-muted-foreground)" />
                  <Tooltip />
                  {AREAS.map((area) => <Bar key={area} dataKey={area} stackId="olay" fill={AREA_COLOR[area]} />)}
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="text-sm mt-2">{view.operations || 'Olaylar otomatik kapatılıyor; çözüm süresi ölçülemiyor.'}</p>
            <ul className="text-sm mt-2 space-y-1">
              {(view.sources || []).map((sourceRow) => (
                <li key={sourceRow.label}>{sourceRow.label}: {sourceRow.count} · {sourceRow.trend}</li>
              ))}
            </ul>
          </section>

          <section id="veri-kapsami" style={cardStyle}>
            <button type="button" onClick={() => setCoverageOpen((v) => !v)} style={{ background: 'transparent', border: 0, color: 'var(--theme-foreground)', fontWeight: 600 }}>
              Veri kapsamı
            </button>
            {coverageOpen && (
              <table className="w-full text-sm mt-2">
                <thead>
                  <tr style={{ color: 'var(--theme-muted-foreground)' }}>
                    <th className="text-left">Bölüm</th><th className="text-left">Durum</th><th className="text-left">Eksik olan</th><th className="text-left">Nasıl tamamlanır</th>
                  </tr>
                </thead>
                <tbody>
                  {view.coverage.rows.map((row) => (
                    <tr key={row.section}>
                      <td>{row.section}</td>
                      <td>{row.status}</td>
                      <td>{row.missing}</td>
                      <td>{row.how}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}

      <section id="demo" className="grid grid-cols-1 md:grid-cols-2 gap-3">
        {(bundle.demo_cards || []).map((card) => (
          <article key={card.title} style={{ ...cardStyle, borderStyle: card.demo ? 'dashed' : 'solid', outline: card.demo ? '1px dashed var(--warning)' : undefined }}>
            <div className="flex justify-between">
              <h2 className="font-semibold">{card.title}</h2>
              {card.demo && <span style={{ color: 'var(--warning)' }}>DEMO · Örnek veri</span>}
            </div>
            {card.demo ? card.lines.map((line) => (
              <p key={line.label}>{line.label}: {line.value}</p>
            )) : <p>Ölçülemedi</p>}
          </article>
        ))}
      </section>

      {drawer && (
        <aside style={{ position: 'fixed', top: 0, right: 0, height: '100%', width: 420, maxWidth: '100%', overflow: 'auto', background: 'var(--theme-card)', color: 'var(--theme-card-foreground)', borderLeft: '1px solid var(--theme-border)', padding: 16, zIndex: 20 }}>
          <button type="button" onClick={() => setDrawer(null)} style={{ color: 'var(--theme-link)', background: 'transparent', border: 0 }}>Kapat</button>
          {drawer === 'idle' ? (
            <>
              <h2 className="font-semibold mt-2">İlk 10 atıl kayıt</h2>
              <p className="text-sm">{view?.idle?.note}</p>
              <table className="w-full text-sm mt-2">
                <tbody>
                  {(view?.idle?.top || []).map((row) => (
                    <tr key={row.name}><td>{row.name}</td><td>{row.category}</td><td>{row.amount}</td><td>{row.age}</td></tr>
                  ))}
                </tbody>
              </table>
              {(view?.idle?.top || []).length === 0 && <p className="text-sm">Listelenecek kayıt yok.</p>}
            </>
          ) : 'metrics' in drawer ? (
            <>
              <h2 className="font-semibold mt-2">{drawer.name}</h2>
              <p style={{ color: statusColor(drawer.status) }}>{drawer.status}{drawer.score != null ? ` · skor ${drawer.score}` : ''}</p>
              <p className="text-sm mt-2">{drawer.reason}</p>
              <table className="w-full text-sm mt-3">
                <thead><tr style={{ color: 'var(--theme-muted-foreground)' }}><th className="text-left">Ad</th><th>Durum</th><th>Kritik</th><th>Uyarı</th><th>Kullanım</th></tr></thead>
                <tbody>
                  {(drawer.assets || []).map((asset) => (
                    <tr key={asset.name}><td>{asset.name}</td><td>{asset.status}</td><td>{asset.critical}</td><td>{asset.warning}</td><td>{asset.usage}</td></tr>
                  ))}
                </tbody>
              </table>
              {(drawer.assets || []).length === 0 && <p className="text-sm mt-2">Adlandırılmış varlık bu pakette yok.</p>}
            </>
          ) : (
            <>
              <h2 className="font-semibold mt-2">{drawer.area}</h2>
              <p>{drawer.sentence}</p>
              {drawer.entity && <p className="mt-2">{drawer.entity}</p>}
              <p className="text-sm mt-2">{drawer.action}</p>
              <p className="text-sm mt-2">{drawer.age} gündür açık</p>
            </>
          )}
        </aside>
      )}
    </div>
  )
}

function FillChart({ title, dataKey, threshold, data }: { title: string; dataKey: string; threshold: number; data: Array<Record<string, string | number>> }) {
  return (
    <div>
      <p className="text-sm mb-1">{title} · eşik %{threshold}</p>
      <div style={{ width: '100%', height: 180 }}>
        <ResponsiveContainer>
          <BarChart layout="vertical" data={data}>
            <XAxis type="number" domain={[0, 100]} stroke="var(--theme-muted-foreground)" />
            <YAxis type="category" dataKey="ad" width={90} stroke="var(--theme-muted-foreground)" />
            <Tooltip />
            <ReferenceLine x={threshold} stroke="var(--warning)" />
            <Bar dataKey={dataKey} fill="var(--theme-primary)" />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
  )
}

export default function ExecutiveReports() {
  const [month, setMonth] = useState<string | undefined>(undefined)
  const q = useQuery<Bundle>({
    queryKey: ['executive-facts', month],
    queryFn: async () => {
      const url = new URL(`${API_BASE_URL}/ops/executive-facts`, window.location.origin)
      if (month) url.searchParams.set('month', month)
      const res = await fetch(url.toString(), { headers: authHeaders() })
      if (!res.ok) throw new Error('Rapor alınamadı')
      return res.json()
    },
    refetchInterval: (query) => (query.state.data?.refreshing ? 3000 : false),
  })
  const [refreshError, setRefreshError] = useState('')

  async function refreshNow() {
    setRefreshError('')
    const res = await fetch(`${API_BASE_URL}/ops/executive-facts/refresh`, { method: 'POST', headers: authHeaders() })
    if (!res.ok) {
      setRefreshError('Yenileme başlatılamadı')
      return
    }
    await q.refetch()
  }

  return (
    <div>
      {refreshError && <p className="px-6" style={{ color: 'var(--theme-destructive)' }}>{refreshError}</p>}
      {q.isLoading && <p className="p-6">Yükleniyor…</p>}
      {q.isError && <p className="p-6" style={{ color: 'var(--theme-destructive)' }}>Rapor alınamadı.</p>}
      {q.data && <ExecutiveReportView bundle={q.data} onRefresh={refreshNow} onMonth={setMonth} />}
    </div>
  )
}
