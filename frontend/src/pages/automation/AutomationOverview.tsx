import React, { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  ResponsiveContainer, PieChart, Pie, Cell, Tooltip, BarChart, Bar, XAxis, YAxis, CartesianGrid, Legend,
  LineChart, Line,
} from 'recharts'
import { Workflow, RefreshCw, Bot, ListChecks, PlayCircle, AlertTriangle, Database } from 'lucide-react'
import { agentPath, apiGet, apiSend, executionPath, objectPath, qs, type DashboardInsight, type Overview } from './api'
import {
  AutomicInfoButton, Card, ClientPicker, CLASS_COLORS, CLASS_LABELS, chartTooltipStyle, EmptyNote, ErrorNote, fmtAgo, fmtDateTime,
  fmtDuration, fmtNumber, HintInfo, KpiTile, NoSystemNotice, NoticeBox, RangePicker, StatusBadge, SystemPicker, useSelectedSystem,
} from './ui'

const DOW = ['Pzt', 'Sal', 'Çar', 'Per', 'Cum', 'Cmt', 'Paz']

/** Genel bakış KPI / kart açıklamaları — (i) içeriği */
const H = {
  total: 'Seçili zaman aralığında biten Automic çalışmaları (RunID) sayısı. Önceki aynı uzunluktaki dönemle yüzde farkı alt satırda gösterilir.',
  ok: 'Başarılı biten çalışmalar. Varsayılan kural: durum kodu 1900–1999 (ENDED_OK vb.). Entegrasyon ayarından değiştirilebilir.',
  failed: 'Hatalı / abend biten çalışmalar. Varsayılan: ANY_ABEND — durum kodu 1800–1899 (1850/1851 iptal sayılır, hariç). Gerçek AE kodu satırda görünür.',
  cancelled: 'İptal edilen çalışmalar. Varsayılan: durum kodu 1850 ve 1851 (kullanıcı/sistem iptali). Hata değildir; ayrı sayılır.',
  success: 'Başarı oranı = Başarılı / (Başarılı + Hatalı) × 100. İptal ve “diğer” bu orana dahil edilmez.',
  running: 'Şu an AE’de aktif görünen iş sayısı (son EH anlık görüntüsü). Biten aralık KPI’sı değildir; canlı snapshot’tır.',
  statusDist: 'Seçili aralıktaki biten çalışmaların sınıflara göre payı: Başarılı / Hatalı / İptal / Diğer. Altta en sık AE durum kodları (ham kod) listelenir.',
  volume: 'Zaman dilimine göre (saatlik veya günlük) biten çalışma hacmi. Yığınlar: başarılı (yeşil) + hatalı (kırmızı) + iptal (turuncu).',
  topFailed: 'Aralıkta en çok hatalı biten 10 nesne (JOBS/JOBP…). Çubuk = hata sayısı; üzerine gelince toplam çalışma da görülür. Tıklayınca nesne sayfasına gider.',
  failTrend: 'Günlük hatalı çalışma sayısı (sol eksen) ve hata oranı % (sağ eksen). Eksik günler 0 ile doldurulur. Kısa geçmişte tek sivri uç normaldir.',
  recentFail: 'En son hatalı biten çalışmalar. İmza (ORA-… vb.) rapordan türetilmiş özet satırdır. Tıklayınca çalışma detayı / rapor açılır.',
  health: 'ainew ↔ AE kaynağı toplama sağlığı: kaynak gecikmesi (Data Guard / MAX zaman), son/sonraki toplama, aralık, hata kuralı, devre kesici, yetenek rozetleri. Automic job sonucu değildir.',
  insight: 'Seçili aralık metriklerinden kısa özet. Sayfa açılışında 15 dk Redis önbelleği veya anında metrik özeti gösterilir; LLM arka planda üretilir (kullanıcı bekletilmez). “AI ile yenile” senkron LLM çağrısı yapar.',
  tonight: 'Bu gece penceresinde (ör. 20:00–06:00) geçmişte aynı hafta günü sık çalışan nesneler. Forecast değildir; tarihsel örüntüdür.',
  analysis: 'Asenkron uzun analiz sonucu (hata paketi / gece özeti / etki). Arka planda hesaplanır; durum ve yüzde burada güncellenir.',
  outliers: 'Süre sapması: nesnenin son 30 gündeki başarılı çalışmalara göre p95 süresinin 1,5 katını aşan bitişler. “Oran” = son süre / p95. Tıklayınca ilgili RunID detayı.',
  durTrend: 'Odak nesnenin (genelde en çok hata veren) günlük ortalama / p95 / maksimum süresi (saniye). Yavaşlama veya ani zirveleri görmek için.',
  heatmap: 'Haftanın günü × saat diliminde toplam çalışma yoğunluğu (ve hata payı). Hangi saatlerde yük / hata biriktiğini gösterir.',
  storage: 'ainew Automic modül veritabanı (automic_db) kota kullanımı. AE disk kotası değildir. Eşikler: uyarı / budama / kritik.',
  monthEnd: 'Her ayın son 3 günündeki çalışma ve hata toplamları (aylar arası karşılaştırma). Ay sonu batch yükünü izlemek için.',
  activeWf: 'Şu an aktif (EH) workflow / job’lar; özellikle waiting/blocked. Durum kodu AE’den gelir. Tıklayınca çalışma detayı.',
  agents: 'Agent adına göre seçili aralıktaki çalışma / hata / şu an aktif / benzersiz nesne sayıları. Tıklayınca agent detay sayfası.',
} as const

function delta(cur: number, prev: number | null | undefined) {
  if (!prev) return null
  const pct = Math.round(((cur - prev) / prev) * 1000) / 10
  return `${pct >= 0 ? '+' : ''}${pct}% önceki döneme göre`
}

function bucketLabel(iso: string, bucket: 'hour' | 'day') {
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return iso
  return bucket === 'hour'
    ? d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
    : d.toLocaleDateString('tr-TR', { day: '2-digit', month: '2-digit' })
}

function insightStorageKey(systemId: number, range: string, clientsKey: string) {
  return `ainew:automic:insight:${systemId}:${range}:${clientsKey || 'all'}`
}

function readInsightPlaceholder(systemId: number, range: string, clientsKey: string): DashboardInsight | undefined {
  try {
    const raw = sessionStorage.getItem(insightStorageKey(systemId, range, clientsKey))
    if (!raw) return undefined
    const parsed = JSON.parse(raw) as DashboardInsight
    return parsed?.markdown ? parsed : undefined
  } catch {
    return undefined
  }
}

export default function AutomationOverview() {
  const navigate = useNavigate()
  const qc = useQueryClient()
  const { systems, selected, setSystem } = useSelectedSystem()
  const [range, setRange] = useState('24h')
  const [clients, setClients] = useState<number[]>([])
  const [insightForceBusy, setInsightForceBusy] = useState(false)
  const clientsKey = clients.join(',')

  const ov = useQuery({
    queryKey: ['automic-overview', selected?.id, range, clientsKey],
    queryFn: () => apiGet<Overview>(`/overview${qs({ system_id: selected!.id, range, clients: clientsKey })}`),
    enabled: !!selected,
    refetchInterval: 60_000,
  })
  const insightKey = useMemo(
    () => ['automic-insight', selected?.id, range, clientsKey] as const,
    [selected?.id, range, clientsKey],
  )
  const insight = useQuery({
    queryKey: insightKey,
    queryFn: () => apiGet<DashboardInsight>(`/overview/insight${qs({ system_id: selected!.id, range, clients: clientsKey })}`),
    enabled: !!selected,
    staleTime: 14 * 60_000,
    placeholderData: () => (selected ? readInsightPlaceholder(selected.id, range, clientsKey) : undefined),
    refetchInterval: (q) => (q.state.data?.regenerating ? 3000 : false),
  })
  useEffect(() => {
    if (!selected || !insight.data?.markdown) return
    try {
      sessionStorage.setItem(insightStorageKey(selected.id, range, clientsKey), JSON.stringify(insight.data))
    } catch { /* ignore quota */ }
  }, [selected, range, clientsKey, insight.data])

  async function refreshInsightAi() {
    if (!selected) return
    setInsightForceBusy(true)
    try {
      const d = await apiGet<DashboardInsight>(
        `/overview/insight${qs({ system_id: selected.id, range, clients: clientsKey, force: true })}`,
      )
      qc.setQueryData(insightKey, d)
    } finally {
      setInsightForceBusy(false)
    }
  }

  const [analysisId, setAnalysisId] = useState<string | null>(null)
  const analysis = useQuery({
    queryKey: ['automic-analysis', analysisId],
    queryFn: () => apiGet<any>(`/analyses/${analysisId}`),
    enabled: !!analysisId,
    refetchInterval: (q) => {
      const st = (q.state.data as any)?.status
      return st === 'running' ? 2000 : false
    },
  })

  if (systems.isLoading) return <div className="p-6 text-sm text-slate-400">Yükleniyor…</div>
  if (systems.error) return <div className="p-6"><ErrorNote error={systems.error} /></div>
  if (!selected) return <NoSystemNotice />

  const d = ov.data
  const pie = d ? Object.entries(d.status_distribution.by_class).filter(([, v]) => v > 0).map(([k, v]) => ({ name: CLASS_LABELS[k] ?? k, key: k, value: v })) : []
  const volume = d ? d.volume.map(v => ({ ...v, label: bucketLabel(v.bucket, d.bucket) })) : []
  const trend = d ? d.failure_trend.map(t => ({
    ...t, label: bucketLabel(t.day, 'day'), rate: t.total ? Math.round((t.failed / t.total) * 1000) / 10 : 0,
  })) : []
  const h = d?.health

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <div className="flex items-center gap-2">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-amber-500/15 text-amber-300"><Workflow size={18} /></div>
          <div>
            <h1 className="inline-flex items-center gap-1.5 text-lg font-semibold text-white">
              UC4 Automic · Genel Bakış
              <HintInfo title="Genel bakış" text="Seçili Automic sistemi ve zaman aralığı için biten çalışmaların özeti, trendler ve entegrasyon sağlığı. Veri ainew modül DB’sinden (toplama) gelir; Automic’e yazılmaz. Üstteki aralık/client seçicileri tüm kartları filtreler." />
            </h1>
            <p className="text-xs text-slate-500">
              {d ? `${fmtDateTime(d.from)} – ${fmtDateTime(d.to)}` : '…'}
              {h?.source_lag_sec != null && <> · kaynak gecikmesi {fmtDuration(h.source_lag_sec)}</>}
            </p>
          </div>
        </div>
        <div className="ml-auto flex flex-wrap items-center gap-2">
          <SystemPicker systems={systems.data ?? []} value={selected.id} onChange={setSystem} />
          <RangePicker value={range} onChange={setRange} />
          <button type="button"
            onClick={async () => {
              try {
                const r = await apiSend<{ ok: boolean; job_id: string }>('/analyses', 'POST', {
                  system_id: selected.id, kind: 'failure_pack', range, clients,
                })
                if (r.job_id) setAnalysisId(r.job_id)
              } catch { /* ErrorNote via ov */ }
            }}
            className="rounded-lg border border-slate-700 px-2.5 py-1 text-xs text-slate-300 hover:text-white">
            Uzun analiz
          </button>
          <AutomicInfoButton systemId={selected.id} />
          <button type="button" onClick={() => { ov.refetch(); insight.refetch() }} className="rounded-lg border border-slate-700 p-1.5 text-slate-400 hover:text-white" title="Yenile">
            <RefreshCw size={14} className={ov.isFetching ? 'animate-spin' : ''} />
          </button>
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        <ClientPicker clients={selected.clients} value={clients} onChange={setClients} />
        <div className="ml-auto flex gap-2 text-xs">
          <Link to={`/automation/executions?system=${selected.id}`} className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-2.5 py-1 text-slate-300 hover:text-white"><ListChecks size={13} /> Çalışmalar</Link>
          <Link to={`/automation/active?system=${selected.id}`} className="inline-flex items-center gap-1 rounded-lg border border-slate-700 px-2.5 py-1 text-slate-300 hover:text-white"><PlayCircle size={13} /> Aktif işler</Link>
          <Link to={`/automation/chat?system=${selected.id}`} className="inline-flex items-center gap-1 rounded-lg bg-blue-600 px-2.5 py-1 text-white hover:bg-blue-500"><Bot size={13} /> Asistana sor</Link>
        </div>
      </div>

      {ov.error ? <ErrorNote error={ov.error} /> : null}
      {h?.fake && (
        <div className="rounded-xl border border-amber-500/30 bg-amber-500/10 px-4 py-2 text-xs text-amber-100">
          Bu sistem sahte (fake) kaynak kullanıyor — gösterilen veriler gerçek AE verisi değildir.
        </div>
      )}

      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <KpiTile label="Toplam çalışma" value={fmtNumber(d?.kpi.total)} sub={d ? delta(d.kpi.total, d.kpi.previous.total) : null} hint={H.total} />
        <KpiTile label="Başarılı" value={fmtNumber(d?.kpi.ok)} tone="ok" hint={H.ok} />
        <KpiTile label="Hatalı" value={fmtNumber(d?.kpi.failed)} tone={d && d.kpi.failed > 0 ? 'critical' : undefined} sub={d ? delta(d.kpi.failed, d.kpi.previous.failed) : null} hint={H.failed} />
        <KpiTile label="İptal" value={fmtNumber(d?.kpi.cancelled)} tone={d && d.kpi.cancelled > 0 ? 'warning' : undefined} hint={H.cancelled} />
        <KpiTile label="Başarı oranı" value={d?.kpi.success_rate_pct != null ? `%${d.kpi.success_rate_pct}` : '—'} hint={H.success} />
        <KpiTile label="Şu an çalışan" value={fmtNumber(d?.kpi.running)} sub={h?.active_snapshot_at ? `anlık görüntü ${fmtAgo(h.active_snapshot_at)}` : null} hint={H.running} />
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="Durum dağılımı" hint={H.statusDist}>
          {pie.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <PieChart>
                <Pie data={pie} dataKey="value" nameKey="name" innerRadius={55} outerRadius={85} paddingAngle={2}>
                  {pie.map(p => <Cell key={p.key} fill={CLASS_COLORS[p.key] ?? CLASS_COLORS.other} />)}
                </Pie>
                <Tooltip contentStyle={chartTooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </PieChart>
            </ResponsiveContainer>
          ) : <EmptyNote>Veri yok</EmptyNote>}
          {d && d.status_distribution.by_code.length > 0 && (
            <div className="mt-2 flex flex-wrap gap-1">
              {d.status_distribution.by_code.slice(0, 8).map(c => (
                <span key={c.status_code} className="rounded bg-slate-900/60 px-1.5 py-0.5 font-mono text-[10px] text-slate-400">
                  {c.status_code}: {fmtNumber(c.count)}
                </span>
              ))}
            </div>
          )}
        </Card>
        <Card title={d?.bucket === 'day' ? 'Günlük yük' : 'Saatlik yük'} className="lg:col-span-2" hint={H.volume}>
          {volume.length ? (
            <ResponsiveContainer width="100%" height={250}>
              <BarChart data={volume}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <Tooltip contentStyle={chartTooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="ok" name="Başarılı" stackId="a" fill={CLASS_COLORS.ok} />
                <Bar dataKey="failed" name="Hatalı" stackId="a" fill={CLASS_COLORS.failed} />
                <Bar dataKey="cancelled" name="İptal" stackId="a" fill={CLASS_COLORS.cancelled} />
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyNote>Veri yok</EmptyNote>}
        </Card>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="En çok hata veren 10 nesne" hint={H.topFailed}>
          {d?.top_failed.length ? (
            <ResponsiveContainer width="100%" height={Math.max(200, d.top_failed.length * 28 + 30)}>
              <BarChart data={d.top_failed} layout="vertical" margin={{ left: 8 }}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" horizontal={false} />
                <XAxis type="number" allowDecimals={false} tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <YAxis type="category" dataKey="object_name" width={200} tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <Tooltip contentStyle={chartTooltipStyle} formatter={(v: any, _n: any, p: any) => [`${v} / ${p?.payload?.runs} çalışma`, 'Hatalı']} />
                <Bar dataKey="failed" fill={CLASS_COLORS.failed} radius={[0, 4, 4, 0]} cursor="pointer"
                  onClick={(e: any) => e?.object_name && navigate(objectPath(selected.id, e.object_name))} />
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyNote>Bu aralıkta hata yok</EmptyNote>}
        </Card>
        <Card title="Hata trendi (günlük)" hint={H.failTrend}>
          {trend.length ? (
            <ResponsiveContainer width="100%" height={240}>
              <LineChart data={trend}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <YAxis yAxisId="l" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <YAxis yAxisId="r" orientation="right" unit="%" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <Tooltip contentStyle={chartTooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line yAxisId="l" type="monotone" dataKey="failed" name="Hatalı" stroke={CLASS_COLORS.failed} strokeWidth={2} dot />
                <Line yAxisId="r" type="monotone" dataKey="rate" name="Hata oranı %" stroke="#3b82f6" strokeWidth={2} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : <EmptyNote>Veri yok</EmptyNote>}
          {trend.length === 1 && <p className="text-[11px] text-slate-500">Trend için 7 gün veya daha uzun aralık seçin.</p>}
        </Card>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="Son hatalar" className="lg:col-span-2" hint={H.recentFail}
          actions={<Link to={`/automation/executions?system=${selected.id}&status_class=failed&range=${range}`} className="text-xs text-blue-300 hover:text-blue-200">tümü</Link>}>
          {d?.recent_failures.length ? (
            <div className="divide-y divide-white/[0.05]">
              {d.recent_failures.slice(0, 12).map(f => (
                <Link key={`${f.client}-${f.run_id}`} to={executionPath(selected.id, f.client, f.run_id)}
                  className="flex items-start gap-3 px-1 py-2 hover:bg-white/[0.03] rounded-lg">
                  <AlertTriangle size={14} className="mt-0.5 flex-shrink-0 text-red-400" />
                  <div className="min-w-0 flex-1">
                    <div className="flex flex-wrap items-center gap-2 text-xs">
                      <span className="font-medium text-slate-100 break-all">{f.object_name}</span>
                      <StatusBadge cls={f.status_class} code={f.status_code} />
                      <span className="text-slate-500">client {f.client}</span>
                    </div>
                    {f.error_signature && <div className="mt-0.5 truncate font-mono text-[11px] text-red-300/80" title={f.error_signature}>{f.error_signature}</div>}
                  </div>
                  <div className="text-right text-[11px] text-slate-500 whitespace-nowrap">
                    <div>{fmtAgo(f.end_time)}</div>
                    <div>{f.agent ?? ''}</div>
                  </div>
                </Link>
              ))}
            </div>
          ) : <EmptyNote>Hata yok</EmptyNote>}
        </Card>
        <Card title={<span className="inline-flex items-center gap-1.5"><Database size={14} /> Entegrasyon sağlığı</span>} hint={H.health}>
          {h ? (
            <dl className="space-y-1.5 text-xs">
              <Row k="Kaynak" v={h.source_label} />
              <Row k="Kaynak gecikmesi" v={h.source_lag_sec != null ? `${fmtDuration(h.source_lag_sec)} (${h.source_lag_method ?? '—'})` : '—'}
                tone={h.source_lag_sec != null && h.source_lag_sec > 1800 ? 'warning' : undefined} />
              <Row k="Canlı okuma" v={(() => {
                const m = (h as any).live_read_metrics
                const mode = (h as any).live_read_mode ?? 'off'
                if (!m) return mode
                const p95 = m.live_duration_p95_sec != null ? ` · p95 ${m.live_duration_p95_sec}s` : ''
                return `${mode} · ok ${m.live_reads_ok_60m ?? 0}/60dk · red ${m.live_reads_denied_60m ?? 0} · bütçe aşım ${m.live_budget_exceed_60m ?? 0}${p95}`
              })()} />
              <Row k="Son toplama" v={h.last_success_at ? `${fmtAgo(h.last_success_at)} · ${fmtNumber(h.last_rows)} satır · ${fmtDuration(h.last_duration_sec)}` : '—'} />
              <Row k="Son yeni kayıt" v={(h as any).last_new_record_at ? fmtDateTime((h as any).last_new_record_at) : '—'}
                tone={(h as any).ingest_stall_warning ? 'critical' : undefined} />
              {(h as any).ingest_stall_warning && (
                <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-1.5 text-[11px] text-red-200">
                  {(h as any).ingest_stall_warning}
                </div>
              )}
              <Row k="Sonraki toplama" v={fmtDateTime(h.next_run_at)} />
              <Row k="Aralık" v={`${h.interval_min} dk`} />
              <Row k="Hata kuralı" v={h.failed_rule} />
              {h.runs_24h && <Row k="Son 24 saat" v={`${h.runs_24h.runs} toplama · ${h.runs_24h.errors} hata`} tone={h.runs_24h.errors ? 'warning' : undefined} />}
              {h.circuit_open_sec > 0 && <Row k="Devre kesici" v={`açık (${fmtDuration(h.circuit_open_sec)})`} tone="critical" />}
              {h.ingest_paused_reason && <Row k="Duraklatma" v={h.ingest_paused_reason} tone="critical" />}
              {h.last_error && <div className="rounded-lg border border-red-500/30 bg-red-500/10 px-2 py-1.5 text-[11px] text-red-200">{h.last_error}</div>}
              <div className="flex flex-wrap gap-1 pt-1">
                {Object.entries(h.features || {}).map(([k, v]) => (
                  <span key={k} className={`rounded px-1.5 py-0.5 text-[10px] ${v === true || (typeof v === 'string' && v !== 'unavailable')
                    ? 'bg-green-500/10 text-green-300' : 'bg-slate-700/50 text-slate-500'}`}>{k}</span>
                ))}
              </div>
            </dl>
          ) : <EmptyNote>—</EmptyNote>}
        </Card>
      </div>

      {/* Faz 3 widget 15–16 */}
      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="AI özeti — öne çıkanlar" hint={H.insight}
          actions={
            <div className="flex items-center gap-2">
              {insight.data?.regenerating && (
                <span className="text-[10px] text-amber-300/80">AI güncelleniyor…</span>
              )}
              <button
                type="button"
                className="text-xs text-blue-300 disabled:opacity-50"
                disabled={insightForceBusy}
                onClick={() => { void refreshInsightAi() }}
                title="Senkron LLM ile yeniden üret (bekletebilir)"
              >
                {insightForceBusy ? 'üretiliyor…' : insight.data?.cached ? 'önbellek · AI ile yenile' : 'AI ile yenile'}
              </button>
            </div>
          }>
          {!insight.data?.markdown && insight.isLoading && <EmptyNote>Özet hazırlanıyor…</EmptyNote>}
          {insight.error && !insight.data?.markdown && <ErrorNote error={insight.error} />}
          {insight.data?.markdown && (
            <div className="prose prose-invert prose-sm max-w-none text-slate-300 whitespace-pre-wrap text-[13px] leading-relaxed">
              {insight.data.markdown}
            </div>
          )}
          {insight.data?.source === 'deterministic' && !insight.data?.regenerating && (
            <p className="mt-2 text-[11px] text-slate-500">Metrik özeti (LLM kullanılmadı veya yanıt vermedi).</p>
          )}
          {insight.data?.llm_error && <p className="mt-2 text-[11px] text-amber-300/80">LLM: {insight.data.llm_error}</p>}
        </Card>
        <Card title="Bu gece beklenenler (geçmiş örüntü)" hint={H.tonight}>
          {d?.expected_tonight?.note && <p className="mb-2 text-[11px] text-slate-500">{d.expected_tonight.note}</p>}
          {d?.expected_tonight?.items?.length ? (
            <div className="max-h-64 overflow-y-auto divide-y divide-white/[0.04]">
              {d.expected_tonight.items.map(it => (
                <Link key={it.object_name} to={objectPath(selected.id, it.object_name)}
                  className="flex justify-between gap-2 px-1 py-1.5 text-xs hover:bg-white/[0.03]">
                  <span className="text-slate-200 break-all">{it.object_name}</span>
                  <span className="text-slate-500 whitespace-nowrap">
                    {it.expected_at ? fmtDateTime(it.expected_at) : `~${it.typical_hour}:00`} · {it.historical_runs}×
                  </span>
                </Link>
              ))}
            </div>
          ) : <EmptyNote>Bu gece için yeterli geçmiş örüntü yok</EmptyNote>}
        </Card>
      </div>

      {analysisId && analysis.data && (
        <Card title={`Analiz · ${analysis.data.title || analysisId}`} hint={H.analysis}>
          <div className="mb-2 text-xs text-slate-400">
            {analysis.data.status} · %{analysis.data.percent} · {analysis.data.message}
          </div>
          {analysis.data.status === 'done' && analysis.data.result?.insight_markdown && (
            <div className="whitespace-pre-wrap text-[13px] text-slate-300">{analysis.data.result.insight_markdown}</div>
          )}
          {analysis.data.error && <NoticeBox tone="warning" text={analysis.data.error} />}
        </Card>
      )}

      {/* Faz 2 widget 8–14 */}
      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Süre sapması (son / p95)" hint={H.outliers}>
          {d?.duration_outliers?.length ? (
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead className="text-slate-500"><tr><th className="py-1 text-left">Nesne</th><th>Süre</th><th>p95</th><th>Oran</th></tr></thead>
                <tbody>
                  {d.duration_outliers.map(o => (
                    <tr key={`${o.client}-${o.run_id}`} className="border-t border-white/[0.04] cursor-pointer hover:bg-white/[0.03]"
                      onClick={() => navigate(executionPath(selected.id, o.client, o.run_id))}>
                      <td className="py-1.5 pr-2 text-slate-200 break-all">{o.object_name}</td>
                      <td className="text-center text-slate-300">{fmtDuration(o.duration_sec)}</td>
                      <td className="text-center text-slate-500">{fmtDuration(o.p95_sec)}</td>
                      <td className="text-center"><span className="rounded bg-amber-500/15 px-1.5 text-amber-200">×{o.ratio}</span></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <EmptyNote>Sapma yok</EmptyNote>}
        </Card>
        <Card title={d?.duration_trend?.object_name ? `Süre trendi · ${d.duration_trend.object_name}` : 'Süre trendi (odak nesne)'} hint={H.durTrend}>
          {d?.duration_trend?.rows?.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <LineChart data={d.duration_trend.rows.map(r => ({ ...r, label: bucketLabel(r.bucket, 'day') }))}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" />
                <XAxis dataKey="label" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <Tooltip contentStyle={chartTooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Line type="monotone" dataKey="avg_sec" name="Ort." stroke="#3b82f6" strokeWidth={2} dot={false} />
                <Line type="monotone" dataKey="p95_sec" name="p95" stroke="#f59e0b" strokeWidth={2} strokeDasharray="4 3" dot={false} />
                <Line type="monotone" dataKey="max_sec" name="Maks" stroke="#ef4444" strokeWidth={1} dot={false} />
              </LineChart>
            </ResponsiveContainer>
          ) : <EmptyNote>Odak nesne yok</EmptyNote>}
        </Card>
      </div>

      <div className="grid gap-3 lg:grid-cols-3">
        <Card title="Yük ısı haritası (gün × saat)" className="lg:col-span-2" hint={H.heatmap}>
          {d?.hourly_heatmap?.length ? (
            <Heatmap rows={d.hourly_heatmap} />
          ) : <EmptyNote>Veri yok</EmptyNote>}
        </Card>
        <Card title="Depolama kotası" hint={H.storage}>
          {d?.storage ? (
            <div className="space-y-3 text-xs">
              <div className="text-center">
                <div className="text-2xl font-semibold text-white">%{d.storage.usage_pct}</div>
                <div className="text-slate-500">{fmtBytes(d.storage.used_bytes)} / {d.storage.quota_gb} GB · {d.storage.level}</div>
              </div>
              <div className="h-3 overflow-hidden rounded-full bg-slate-700">
                <div className={`h-full ${d.storage.level === 'critical' ? 'bg-red-500' : d.storage.level === 'ok' ? 'bg-blue-500' : 'bg-amber-500'}`}
                  style={{ width: `${Math.min(100, d.storage.usage_pct)}%` }} />
              </div>
              <ul className="space-y-1 max-h-40 overflow-y-auto">
                {Object.entries(d.storage.layers || {}).filter(([, v]) => v > 0).sort((a, b) => b[1] - a[1]).map(([k, v]) => (
                  <li key={k} className="flex justify-between text-slate-400"><span className="truncate">{k.replace('automic_', '')}</span><span>{fmtBytes(v)}</span></li>
                ))}
              </ul>
            </div>
          ) : <EmptyNote>—</EmptyNote>}
        </Card>
      </div>

      <div className="grid gap-3 lg:grid-cols-2">
        <Card title="Ay sonu karşılaştırması" hint={H.monthEnd}>
          {d?.month_end_compare?.length ? (
            <ResponsiveContainer width="100%" height={220}>
              <BarChart data={d.month_end_compare}>
                <CartesianGrid stroke="rgba(255,255,255,0.06)" vertical={false} />
                <XAxis dataKey="month" tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} />
                <Tooltip contentStyle={chartTooltipStyle} />
                <Legend wrapperStyle={{ fontSize: 11 }} />
                <Bar dataKey="runs_last3days" name="Son 3 gün çalışma" fill="#3b82f6" />
                <Bar dataKey="failed" name="Hatalı" fill={CLASS_COLORS.failed} />
              </BarChart>
            </ResponsiveContainer>
          ) : <EmptyNote>Özet veri yok (birkaç gün sonra dolacak)</EmptyNote>}
        </Card>
        <Card title="Aktif / bloke workflow'lar" hint={H.activeWf}>
          {d?.active_workflows ? (
            <div className="space-y-2 text-xs">
              <div className="flex flex-wrap gap-2">
                {Object.entries(d.active_workflows.by_state).map(([k, v]) => (
                  <span key={k} className="rounded bg-slate-800 px-2 py-0.5 text-slate-300">{k}: {v}</span>
                ))}
              </div>
              {(d.active_workflows.blocked.length ? d.active_workflows.blocked : d.active_workflows.workflows).slice(0, 8).map((w: any) => (
                <Link key={`${w.client}-${w.run_id}`} to={executionPath(selected.id, w.client, w.run_id)}
                  className="flex justify-between gap-2 rounded-lg px-1 py-1 hover:bg-white/[0.03]">
                  <span className="text-slate-200 break-all">{w.object_name}</span>
                  <span className="text-slate-500 whitespace-nowrap">{w.state} · {w.status_code}</span>
                </Link>
              ))}
              {!d.active_workflows.blocked.length && !d.active_workflows.workflows.length && <EmptyNote>Aktif workflow yok</EmptyNote>}
            </div>
          ) : <EmptyNote>—</EmptyNote>}
        </Card>
      </div>

      <Card title="Agent aktivitesi" hint={H.agents}
        actions={<Link to={`/automation/active?system=${selected.id}`} className="text-xs text-blue-300">aktif işler</Link>}>
        {d?.agent_activity?.length ? (
          <div className="overflow-x-auto">
            <table className="w-full text-xs">
              <thead className="text-slate-500"><tr><th className="text-left py-1">Agent</th><th>Çalışma</th><th>Hata</th><th>Aktif</th><th>Nesne</th></tr></thead>
              <tbody>
                {d.agent_activity.map(a => (
                  <tr key={a.agent} className="border-t border-white/[0.04] cursor-pointer hover:bg-white/[0.03]"
                    onClick={() => navigate(agentPath(selected.id, a.agent))}>
                    <td className="py-1.5 text-slate-200">{a.agent}</td>
                    <td className="text-center">{fmtNumber(a.runs)}</td>
                    <td className="text-center text-red-300">{fmtNumber(a.failed)}</td>
                    <td className="text-center">{a.active_now}</td>
                    <td className="text-center text-slate-500">{a.objects}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <EmptyNote>Veri yok</EmptyNote>}
      </Card>
    </div>
  )
}

function fmtBytes(n: number) {
  if (n < 1024) return `${n} B`
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`
  if (n < 1024 ** 3) return `${(n / 1024 ** 2).toFixed(1)} MB`
  return `${(n / 1024 ** 3).toFixed(2)} GB`
}

function Heatmap({ rows }: { rows: { dow: number; hour: number; total: number; failed: number }[] }) {
  // dow = ISO (1=Pzt … 7=Paz)
  const max = Math.max(1, ...rows.map(r => r.total))
  const grid: Record<string, number> = {}
  rows.forEach(r => { grid[`${r.dow}-${r.hour}`] = r.total })
  return (
    <div className="overflow-x-auto">
      <div className="inline-grid gap-0.5" style={{ gridTemplateColumns: `32px repeat(24, 14px)` }}>
        <div />
        {Array.from({ length: 24 }, (_, h) => <div key={h} className="text-center text-[9px] text-slate-500">{h}</div>)}
        {Array.from({ length: 7 }, (_, ui) => {
          const iso = ui + 1
          return (
            <React.Fragment key={ui}>
              <div className="text-[10px] text-slate-500 self-center">{DOW[ui]}</div>
              {Array.from({ length: 24 }, (_, h) => {
                const v = grid[`${iso}-${h}`] ?? 0
                const a = v / max
                return <div key={h} title={`${DOW[ui]} ${h}:00 — ${v}`}
                  className="h-3.5 w-3.5 rounded-sm" style={{ background: `rgba(59,130,246,${0.08 + a * 0.85})` }} />
              })}
            </React.Fragment>
          )
        })}
      </div>
    </div>
  )
}

function Row({ k, v, tone }: { k: string; v: ReactNode; tone?: string }) {
  const c = tone === 'critical' ? 'text-red-300' : tone === 'warning' ? 'text-amber-300' : 'text-slate-200'
  return (
    <div className="flex justify-between gap-3">
      <dt className="text-slate-500 whitespace-nowrap">{k}</dt>
      <dd className={`text-right ${c} break-words min-w-0`}>{v}</dd>
    </div>
  )
}
