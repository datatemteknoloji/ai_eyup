import { useState } from 'react'
import { Bar, BarChart, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import type { View } from './types'
import { AXIS_TICK, BAR_RADIUS, MUTED, TOOLTIP_STYLE, cardStyle, linkButton, parseTr } from './shared'

const AREAS = ['OpenShift', 'Sanallaştırma', 'Linux', 'Windows'] as const
// Dashboard sayfalarındaki neon palet (ResourceCharts ile aynı renk ailesi).
const AREA_COLOR: Record<string, string> = {
  OpenShift: '#f97316',
  Sanallaştırma: '#06b6d4',
  Linux: '#22c55e',
  Windows: '#a78bfa',
}

/** Atıl kaynak, olay/operasyon ve veri kapsamı. */
export function OperationsSection({ view, onIdle }: { view: View; onIdle: () => void }) {
  const [idleTab, setIdleTab] = useState<'vcpu' | 'ram' | 'disk'>('vcpu')
  const [coverageOpen, setCoverageOpen] = useState(false)
  const eventDays = Object.values((view.events || []).reduce<Record<string, { gun: string } & Record<string, number>>>((acc, row) => {
    acc[row.day] = acc[row.day] || { gun: row.day.slice(5), OpenShift: 0, Sanallaştırma: 0, Linux: 0, Windows: 0 }
    acc[row.day][row.area] = (acc[row.day][row.area] || 0) + row.count
    return acc
  }, {}))
  return (
    <>
      <section id="atil" style={cardStyle}>
        <div className="flex items-center justify-between gap-2">
          <h2 className="font-semibold">Atıl kaynak</h2>
          <button type="button" onClick={onIdle} style={linkButton}>İlk 10</button>
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
                <XAxis dataKey="ad" tick={AXIS_TICK} axisLine={false} tickLine={false} />
                <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} />
                <Tooltip contentStyle={TOOLTIP_STYLE} />
                <Bar dataKey="miktar" name={idleTab === 'vcpu' ? 'vCPU' : idleTab === 'ram' ? 'RAM' : 'Disk'} fill="#06b6d4" radius={BAR_RADIUS} barSize={28} />
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
              <XAxis dataKey="gun" tick={AXIS_TICK} axisLine={false} tickLine={false} />
              <YAxis tick={AXIS_TICK} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip contentStyle={TOOLTIP_STYLE} />
              <Legend wrapperStyle={{ fontSize: 11 }} />
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
              <tr style={{ color: MUTED }}>
                <th className="text-left">Bölüm</th><th className="text-left">Durum</th><th className="text-left">Eksik olan</th><th className="text-left">Nasıl tamamlanır</th>
              </tr>
            </thead>
            <tbody>
              {view.coverage.rows.map((row) => (
                <tr key={row.section}><td>{row.section}</td><td>{row.status}</td><td>{row.missing}</td><td>{row.how}</td></tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </>
  )
}
