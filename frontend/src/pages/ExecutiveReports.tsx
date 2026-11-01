/**
 * Yönetici raporu. Yalnız kilitli paketin sayfa modelini okur; açılışta hesaplama yapmaz.
 * Başka modül sayfasına bağlantı yok. Renkler tema değişkenlerinden gelir.
 * Bileşenler `pages/executive/` altındadır: tek Ortam → Küme → Host modeli (EnvironmentCard),
 * tek «Dikkat gerektirenler» listesi (AttentionList), modül şeridi, kaynak grafikleri, kapasite, operasyon.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import { AiBlock } from '../components/insights/MethodBadge'
import { AttentionList } from './executive/AttentionList'
import { CapacitySection } from './executive/CapacitySection'
import { Drawer, type DrawerTarget } from './executive/Drawer'
import { EnvironmentCard } from './executive/EnvironmentCard'
import { ModuleStrip } from './executive/ModuleStrip'
import { OperationsSection } from './executive/OperationsSection'
import { ResourceCharts } from './executive/ResourceCharts'
import { MUTED, ageText, cardStyle } from './executive/shared'
import type { Bundle } from './executive/types'

function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('auth_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export function ExecutiveReportView({
  bundle,
  onRefresh,
  onMonth,
  busy,
}: {
  bundle: Bundle
  onRefresh?: () => void
  onMonth?: (month: string) => void
  busy?: boolean
}) {
  const view = bundle.view
  const [drawer, setDrawer] = useState<DrawerTarget | null>(null)
  const closeDrawer = useCallback(() => setDrawer(null), [])
  const summary = view?.summary?.text || bundle.summary || 'Kilitli özet yok.'
  const source = view?.summary?.source || bundle.summary_source
  const months = bundle.months || []
  const currentMonth = bundle.period?.start?.slice(0, 7) || ''
  const age = ageText(bundle.generated_at)
  const land = view?.landscape
  const attention = view?.attention || []

  function csv() {
    const lines = ['Bölüm;Etiket;Değer']
    for (const kpi of view?.kpis || []) lines.push(['Gösterge', kpi.label, kpi.value].join(';'))
    for (const area of view?.areas || []) lines.push(['Alan', area.name, area.status].join(';'))
    for (const item of attention) lines.push(['Dikkat', item.title, `${item.environment};${item.problem}`].join(';'))
    for (const env of land?.environments || []) lines.push(['Ortam', env.name, `${env.kind};${env.clusters};${env.hosts};${env.vms}`].join(';'))
    const blob = new Blob([lines.join('\n')], { type: 'text/csv;charset=utf-8' })
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = 'yonetici-raporu.csv'
    a.click()
  }

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
          <h1 className="text-xl font-semibold">Yönetici Özeti</h1>
          <p className="text-sm" style={{ color: age.stale ? 'var(--warning)' : MUTED }} data-testid="veri-yasi">
            {bundle.generated_at
              ? `Veri yaşı: ${age.text} · ${new Date(bundle.generated_at).toLocaleString('tr-TR')}${age.stale ? ' · güncellemek için Şimdi yenile' : ''}`
              : 'Kilitli rapor yok'}
          </p>
          {busy && <p className="text-sm" style={{ color: 'var(--theme-primary)' }}>Rapor yenileniyor. Bitince özet güncellenir.</p>}
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
            {view ? `${view.coverage.total} bölümden ${view.coverage.measured} bölüm ölçülebildi` : 'Veri kapsamı'}
          </a>
          <button type="button" className="no-print" onClick={onRefresh} disabled={busy} aria-busy={busy || undefined} style={{ ...cardStyle, opacity: busy ? 0.75 : 1, cursor: busy ? 'wait' : 'pointer' }}>{busy ? 'Yenileniyor…' : 'Şimdi yenile'}</button>
          <button type="button" className="no-print" onClick={() => window.print()} style={cardStyle}>PDF</button>
          <button type="button" className="no-print" onClick={csv} style={cardStyle}>CSV</button>
        </div>
      </header>

      {!view && <p style={{ color: MUTED }}>Kilitli raporun sayfa modeli yok. Şimdi yenile ile üretilir. Açılışta hesaplama yapılmaz.</p>}

      {view && (
        <>
          <section id="ozet" className="grid grid-cols-1 2xl:grid-cols-[1.4fr_1fr] gap-3">
            {source === 'ai' ? (
              <AiBlock method="exec.ops.duration" title="Özet">
                <p>{summary}</p>
              </AiBlock>
            ) : (
              <article style={cardStyle}>
                <h2 className="font-semibold">Özet</h2>
                <p className="mt-2">{summary}</p>
                <p className="text-xs mt-2" style={{ color: MUTED }}>Bu özet kurallarla otomatik yazıldı.</p>
              </article>
            )}
            <div className="grid grid-cols-2 gap-3">
              {view.kpis.map((kpi) => (
                <article key={kpi.label} style={cardStyle}>
                  <p className="text-xs" style={{ color: MUTED }}>{kpi.label}</p>
                  <p className="text-lg font-semibold">{kpi.value}</p>
                  {kpi.hint && <p className="text-xs" style={{ color: MUTED }}>{kpi.hint}</p>}
                </article>
              ))}
            </div>
          </section>

          {!!land?.environments.length && (
            <section id="ortamlar" className="space-y-2">
              <p className="text-sm" style={{ color: MUTED }}>
                Fiziksel sunucu <strong style={{ color: 'var(--theme-foreground)' }}>{land.physical}</strong>
                {' · '}Sanal sunucu <strong style={{ color: 'var(--theme-foreground)' }}>{land.virtual}</strong>
              </p>
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
                {land.environments.map((env) => (
                  <EnvironmentCard
                    key={`${env.kind}-${env.name}`}
                    env={env}
                    attentionCount={attention.filter((item) => item.environment === env.name).length}
                  />
                ))}
              </div>
            </section>
          )}

          <ModuleStrip areas={view.areas} demoCards={bundle.demo_cards || []} onOpen={setDrawer} />

          <AttentionList items={attention} rule={view.risk_rule} onOpen={setDrawer} />

          {land && <ResourceCharts land={land} />}

          <CapacitySection view={view} />

          <OperationsSection view={view} onIdle={() => setDrawer('idle')} />
        </>
      )}

      {drawer && <Drawer target={drawer} view={view} onClose={closeDrawer} />}
    </div>
  )
}

export default function ExecutiveReports() {
  const [month, setMonth] = useState<string | undefined>(undefined)
  const [pending, setPending] = useState(false)
  const clickedAt = useRef(0)
  const q = useQuery<Bundle>({
    queryKey: ['executive-facts', month],
    queryFn: async () => {
      const url = new URL(`${API_BASE_URL}/ops/executive-facts`, window.location.origin)
      if (month) url.searchParams.set('month', month)
      const res = await fetch(url.toString(), { headers: authHeaders() })
      if (!res.ok) throw new Error('Rapor alınamadı')
      return res.json()
    },
    refetchInterval: (query) => (pending || query.state.data?.refreshing ? 3000 : false),
  })
  const [refreshError, setRefreshError] = useState('')

  useEffect(() => {
    if (!pending || !q.data || q.data.refreshing) return
    if (q.dataUpdatedAt > clickedAt.current) setPending(false)
  }, [pending, q.data, q.dataUpdatedAt])

  async function refreshNow() {
    setRefreshError('')
    clickedAt.current = Date.now()
    setPending(true)
    try {
      const res = await fetch(`${API_BASE_URL}/ops/executive-facts/refresh`, { method: 'POST', headers: authHeaders() })
      if (!res.ok) {
        setRefreshError('Yenileme başlatılamadı')
        setPending(false)
        return
      }
      await q.refetch()
    } catch {
      setRefreshError('Yenileme başlatılamadı')
      setPending(false)
    }
  }

  return (
    <div>
      {refreshError && <p className="px-6" style={{ color: 'var(--theme-destructive)' }}>{refreshError}</p>}
      {q.isLoading && <p className="p-6">Yükleniyor…</p>}
      {q.isError && <p className="p-6" style={{ color: 'var(--theme-destructive)' }}>Rapor alınamadı.</p>}
      {q.data && <ExecutiveReportView bundle={q.data} onRefresh={refreshNow} onMonth={setMonth} busy={pending || q.data.refreshing} />}
    </div>
  )
}
