/**
 * Yönetici raporu. Yalnız kilitli paketin sayfa modelini okur.
 * Başka modül sayfasına bağlantı yok. Renkler tema değişkenlerinden gelir.
 */
import { useState, type CSSProperties } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Bar, BarChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
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
type DemoCard = { title: string; demo: boolean; status?: string; lines: Array<{ label: string; value: string }> }
type View = {
  summary?: { text: string; source: string }
  kpis: Array<{ label: string; value: string; hint: string }>
  areas: Area[]
  capacity: Capacity[]
  investment: { value: string; sentence: string }
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
  summary?: string | null
  summary_source?: string | null
  view?: View | null
  demo_cards?: DemoCard[]
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

function Info({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <span style={{ position: 'relative', display: 'inline-block' }}>
      <button type="button" aria-label="Yöntem bilgisi" onClick={() => setOpen((v) => !v)} style={{ color: 'var(--theme-link)', background: 'transparent', border: 0, cursor: 'pointer' }}>i</button>
      {open && (
        <span style={{ position: 'absolute', zIndex: 5, right: 0, width: 280, padding: 8, background: 'var(--theme-popover)', color: 'var(--theme-popover-foreground)', border: '1px solid var(--theme-border)', borderRadius: 8, fontSize: 12 }}>
          {text}
        </span>
      )}
    </span>
  )
}

export function ExecutiveReportView({ bundle }: { bundle: Bundle }) {
  const view = bundle.view
  const [drawer, setDrawer] = useState<Area | Risk | null>(null)
  const [coverageOpen, setCoverageOpen] = useState(false)
  const summary = view?.summary?.text || bundle.summary || 'Kilitli özet yok.'
  const source = view?.summary?.source || bundle.summary_source

  function csv() {
    const lines = ['bolum,etiket,deger']
    for (const kpi of view?.kpis || []) lines.push(['gosterge', kpi.label, kpi.value].join(','))
    for (const area of view?.areas || []) lines.push(['alan', area.name, area.status].join(','))
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'yonetici-raporu.csv'
    a.click()
  }

  return (
    <div className="p-4 md:p-6 space-y-4" style={{ color: 'var(--theme-foreground)' }}>
      <header className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-xl font-semibold">Yönetici Raporu</h1>
          <p className="text-sm" style={{ color: 'var(--theme-muted-foreground)' }}>
            {bundle.generated_at ? `Üretim ${new Date(bundle.generated_at).toLocaleString('tr-TR')}` : 'Kilitli rapor yok'}
            {bundle.period?.start ? ` · ${bundle.period.start.slice(0, 7)}` : ''}
          </p>
        </div>
        <div className="flex flex-wrap gap-2 items-center">
          <a href="#veri-kapsami" className="text-sm" style={{ color: 'var(--theme-link)' }}>
            {view ? `${view.coverage.measured} / ${view.coverage.total} bölüm ölçülebildi` : 'Veri kapsamı'}
          </a>
          <button type="button" onClick={() => window.print()} style={cardStyle}>PDF</button>
          <button type="button" onClick={csv} style={cardStyle}>CSV</button>
        </div>
      </header>

      {!view && <p style={{ color: 'var(--theme-muted-foreground)' }}>Kilitli raporun sayfa modeli yok. Şimdi yenile ile üretilir. Açılışta hesaplama yapılmaz.</p>}

      {view && (
        <>
          <section className="grid grid-cols-1 2xl:grid-cols-[1.4fr_1fr] gap-3">
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

          <section className="grid grid-cols-1 2xl:grid-cols-4 gap-3">
            {view.areas.map((area) => (
              <article key={area.name} style={cardStyle}>
                <div className="flex items-center justify-between gap-2">
                  <h2 className="font-semibold">{area.name}</h2>
                  <Info text={area.formula} />
                </div>
                <p style={{ color: statusColor(area.status) }}>{area.status}</p>
                <p className="text-sm">{area.reason}</p>
                <ul className="text-sm mt-2 space-y-1">
                  {area.metrics.map((metric) => (
                    <li key={metric.label}>{metric.label}: {metric.value}</li>
                  ))}
                </ul>
                <p className="text-xs mt-2" style={{ color: 'var(--theme-muted-foreground)' }}>{area.change}</p>
                <button type="button" onClick={() => setDrawer(area)} style={{ color: 'var(--theme-link)', background: 'transparent', border: 0, marginTop: 8 }}>Detay</button>
              </article>
            ))}
          </section>

          <section style={cardStyle}>
            <h2 className="font-semibold mb-2">Eşiğe kalan süre</h2>
            {view.capacity.length === 0 && <p>Küme tahmini için veri yok.</p>}
            {view.capacity.map((row) => (
              <div key={row.name} className="mb-2" style={{ opacity: row.low ? 0.55 : 1 }}>
                <div className="flex justify-between text-sm">
                  <span>{row.name} · {row.resource}</span>
                  <span>{row.early ? `${row.early}–${row.late || row.early} ay` : '—'}</span>
                </div>
                <div style={{ height: 8, background: 'var(--theme-muted)', borderRadius: 99, position: 'relative' }}>
                  {row.early && (
                    <span style={{ position: 'absolute', left: `${Math.min(100, Number(row.early) / 12 * 100)}%`, width: 8, height: 8, borderRadius: 99, background: 'var(--theme-primary)' }} />
                  )}
                </div>
                {row.low && <p className="text-xs" style={{ color: 'var(--theme-muted-foreground)' }}>düşük güven</p>}
              </div>
            ))}
            <h2 className="font-semibold mt-4 mb-2">Şu anki doluluk</h2>
            <div style={{ width: '100%', height: 180 }}>
              <ResponsiveContainer>
                <BarChart data={view.capacity.map((row) => ({ ad: row.name, bellek: parseFloat(row.now.replace('%', '')) || 0 }))}>
                  <XAxis dataKey="ad" stroke="var(--theme-muted-foreground)" />
                  <YAxis stroke="var(--theme-muted-foreground)" />
                  <Tooltip />
                  <Bar dataKey="bellek" fill="var(--theme-primary)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
            <p className="text-sm mt-2">{view.investment.sentence} {view.investment.value !== '—' ? `(${view.investment.value})` : ''}</p>
            <a href="#veri-kapsami" className="text-sm" style={{ color: 'var(--theme-link)' }}>OpenShift node ve Linux disk tahmini için veri yok</a>
          </section>

          <section style={cardStyle}>
            <div className="flex items-center justify-between">
              <h2 className="font-semibold">Öncelikli riskler</h2>
              <Info text={view.risk_rule} />
            </div>
            {view.risks.length === 0 && <p className="text-sm">Açık bulgu yok.</p>}
            <table className="w-full text-sm mt-2">
              <thead>
                <tr style={{ color: 'var(--theme-muted-foreground)' }}>
                  <th className="text-left">Alan</th>
                  <th className="text-left">Risk</th>
                  <th className="text-left">Kaç gündür</th>
                  <th className="text-left">Aksiyon</th>
                </tr>
              </thead>
              <tbody>
                {view.risks.map((risk) => (
                  <tr key={`${risk.area}-${risk.sentence}`} onClick={() => setDrawer(risk)} style={{ cursor: 'pointer' }}>
                    <td>{risk.area}</td>
                    <td>{risk.sentence}</td>
                    <td style={{ color: risk.age_days >= 90 ? 'var(--theme-destructive)' : risk.age_days >= 30 ? 'var(--warning)' : 'var(--theme-foreground)' }}>{risk.age} gün</td>
                    <td>{risk.action}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>

          <section style={cardStyle}>
            <h2 className="font-semibold mb-2">Olay ve operasyon</h2>
            <div style={{ width: '100%', height: 180 }}>
              <ResponsiveContainer>
                <BarChart data={Object.values(view.events.reduce<Record<string, { gun: string; adet: number }>>((acc, row) => {
                  const key = row.day
                  acc[key] = acc[key] || { gun: key.slice(5), adet: 0 }
                  acc[key].adet += row.count
                  return acc
                }, {}))}>
                  <XAxis dataKey="gun" stroke="var(--theme-muted-foreground)" />
                  <YAxis stroke="var(--theme-muted-foreground)" />
                  <Tooltip />
                  <Bar dataKey="adet" fill="var(--theme-primary)" />
                </BarChart>
              </ResponsiveContainer>
            </div>
          </section>

          <section id="veri-kapsami" style={cardStyle}>
            <button type="button" onClick={() => setCoverageOpen((v) => !v)} style={{ background: 'transparent', border: 0, color: 'var(--theme-foreground)', fontWeight: 600 }}>
              Veri kapsamı
            </button>
            {coverageOpen && (
              <table className="w-full text-sm mt-2">
                <tbody>
                  {view.coverage.rows.map((row) => (
                    <tr key={row.section}>
                      <td>{row.status}</td>
                      <td>{row.missing}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </section>
        </>
      )}

      <section className="grid grid-cols-1 md:grid-cols-2 gap-3">
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
        <aside style={{ position: 'fixed', top: 0, right: 0, height: '100%', width: 360, background: 'var(--theme-card)', color: 'var(--theme-card-foreground)', borderLeft: '1px solid var(--theme-border)', padding: 16, zIndex: 20 }}>
          <button type="button" onClick={() => setDrawer(null)} style={{ color: 'var(--theme-link)', background: 'transparent', border: 0 }}>Kapat</button>
          {'metrics' in drawer ? (
            <>
              <h2 className="font-semibold mt-2">{drawer.name}</h2>
              <p>{drawer.status}{drawer.score != null ? ` · skor ${drawer.score}` : ''}</p>
              <p className="text-sm">{drawer.reason}</p>
            </>
          ) : (
            <>
              <h2 className="font-semibold mt-2">{drawer.area}</h2>
              <p>{drawer.sentence}</p>
              {drawer.entity && <p>{drawer.entity}</p>}
              <p>{drawer.action}</p>
            </>
          )}
        </aside>
      )}
    </div>
  )
}

export default function ExecutiveReports() {
  const q = useQuery<Bundle>({
    queryKey: ['executive-facts'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/ops/executive-facts`, { headers: authHeaders() })
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
      <div className="px-6 pt-4 flex justify-end">
        <button type="button" onClick={refreshNow} style={cardStyle}>Şimdi yenile</button>
      </div>
      {refreshError && <p className="px-6" style={{ color: 'var(--theme-destructive)' }}>{refreshError}</p>}
      {q.isLoading && <p className="p-6">Yükleniyor…</p>}
      {q.isError && <p className="p-6" style={{ color: 'var(--theme-destructive)' }}>Rapor alınamadı.</p>}
      {q.data && <ExecutiveReportView bundle={q.data} />}
    </div>
  )
}
