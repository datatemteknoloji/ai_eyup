import React, { useMemo, useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { API_BASE_URL } from '../config/api'
import {
  NEON, rgb, PageHeader, PrimaryButton, GhostButton, Kpi, SeverityBadge,
  SearchInput, Select, Section, EmptyState, Tabs,
} from '../components/aiops/ui'
import type { PlatformAiopsProps } from '../utils/platformApi'

type LogListResponse = {
  anomalies: Array<{
    id: number; source: string; server_id?: number; server_name?: string
    ip_address?: string; severity: string; score: number
    title?: string; message?: string; created_at?: string; date?: string
  }>
  total: number; critical_count: number; warning_count: number; days: number; generated_at?: string
}
type HeatmapCell = { date: string; count: number; score: number }
type HeatmapRow = { server_id: number; server_name: string; ip_address?: string; total_count: number; total_score: number; cells: HeatmapCell[] }
type LogHeatmapResponse = { dates: string[]; rows: HeatmapRow[]; max_cell_score: number; generated_at: string }
type MetricAnomaly = {
  server_id: number; server_name: string; ip_address?: string
  metric_name: string; current_value: number; mean_value?: number | null
  z_score?: number | null; severity: string; message: string
}
type AiopsStatus = {
  monitored_servers: number; active_metric_anomalies: number; active_metric_critical: number
  auto_open_incidents: number; open_incidents: number; incidents_with_rca: number
  pipeline: Array<{ stage: string; ok: boolean }>; generated_at: string
}

function heatColor(score: number, maxScore: number) {
  if (!score || maxScore <= 0) return 'rgba(255,255,255,0.04)'
  const r = score / maxScore
  if (r >= 0.75) return 'rgba(239,68,68,0.85)'
  if (r >= 0.5) return 'rgba(245,158,11,0.8)'
  if (r >= 0.25) return 'rgba(245,200,11,0.6)'
  return 'rgba(234,179,8,0.4)'
}
function formatDayLabel(isoDate: string) {
  const [y, m, d] = isoDate.split('-')
  return y && m && d ? `${d}.${m}` : isoDate
}

function PipelineFlow({ status }: { status?: AiopsStatus }) {
  const stages = [
    { key: 'metric', label: 'Metrikler', icon: '', color: NEON.cyan, value: status?.monitored_servers ?? 0, unit: 'sunucu' },
    { key: 'anomaly', label: 'Anomali', icon: '', color: NEON.blue, value: status?.active_metric_anomalies ?? 0, unit: 'aktif' },
    { key: 'event', label: 'Event', icon: '', color: NEON.blue, value: status?.active_metric_critical ?? 0, unit: 'kritik' },
    { key: 'incident', label: 'Incident', icon: '', color: NEON.orange, value: status?.auto_open_incidents ?? 0, unit: 'otomatik' },
    { key: 'rca', label: 'AI RCA', icon: '', color: NEON.green, value: status?.incidents_with_rca ?? 0, unit: 'analiz' },
  ]
  return (
    <Section title="Otonom Döngü" accent={NEON.cyan}
      right={<span className="text-xs hidden sm:block" style={{ color: 'rgba(148,163,184,0.45)' }}>metrik → anomali → event → incident → AI RCA</span>}>
      <div className="p-5 flex items-stretch justify-between gap-1 sm:gap-2">
        {stages.map((s, i) => (
          <React.Fragment key={s.key}>
            <div className="flex-1 flex flex-col items-center">
              <div className="w-full rounded-xl p-3 flex flex-col items-center gap-1"
                style={{ background: `rgba(${rgb(s.color)},0.08)`, border: `1px solid rgba(${rgb(s.color)},0.25)` }}>
                <span className="text-xl">{s.icon}</span>
                <span className="text-2xl font-bold text-white leading-none">{s.value}</span>
                <span className="text-[10px]" style={{ color: s.color }}>{s.unit}</span>
              </div>
              <span className="text-xs font-medium text-white mt-2">{s.label}</span>
            </div>
            {i < stages.length - 1 && (
              <div className="flex items-center pt-6">
                <svg width="24" height="20" viewBox="0 0 24 20" className="flex-shrink-0">
                  <defs>
                    <linearGradient id={`flow-${i}`} x1="0" y1="0" x2="1" y2="0">
                      <stop offset="0%" stopColor={stages[i].color} stopOpacity="0.6" />
                      <stop offset="100%" stopColor={stages[i + 1].color} stopOpacity="0.6" />
                    </linearGradient>
                  </defs>
                  <line x1="0" y1="10" x2="18" y2="10" stroke={`url(#flow-${i})`} strokeWidth="2" strokeDasharray="3 3" className="animate-pulse" />
                  <polygon points="18,5 24,10 18,15" fill={stages[i + 1].color} opacity="0.7" />
                </svg>
              </div>
            )}
          </React.Fragment>
        ))}
      </div>
    </Section>
  )
}

interface CorrelationMetric {
  metric: string
  recurrence_days: number
  total_count: number
  max_severity: string
  last_seen: string | null
  last_event_id: number | null
  last_server_id: number | null
  server_count: number
  is_chronic: boolean
  is_very_chronic: boolean
  suppression: { id: number; baseline_severity: string | null; reason: string | null; scope: string } | null
  effective_severity: string
  is_suppressed: boolean
  is_downgraded: boolean
}

interface CorrelationResponse {
  total_metrics: number
  chronic_count: number
  suppressed_count: number
  downgraded_count: number
  metrics: CorrelationMetric[]
}

const SEV_COLOR: Record<string, string> = { critical: '#ef4444', warning: '#fb923c', info: '#22d3ee', emergency: '#a855f7' }

export function CorrelationTab() {
  const [search, setSearch] = useState('')
  const [markLoading, setMarkLoading] = useState<number | null>(null)
  const queryClient = useQueryClient()

  const { data, isLoading } = useQuery<CorrelationResponse>({
    queryKey: ['baseline-correlation'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/baseline/correlation`)
      return r.json()
    },
    refetchInterval: 60000,
  })

  const suppress = async (_metric: string, _serverId: number | null, eventId: number | null) => {
    if (!eventId) return
    setMarkLoading(eventId)
    try {
      await fetch(`${API_BASE_URL}/baseline/suppressions/from-event/${eventId}?baseline_severity=warning`, { method: 'POST' })
      queryClient.invalidateQueries({ queryKey: ['baseline-correlation'] })
    } finally { setMarkLoading(null) }
  }

  const metrics = data?.metrics ?? []
  const filtered = search
    ? metrics.filter(m => m.metric.toLowerCase().includes(search.toLowerCase()))
    : metrics

  return (
    <div className="space-y-4">
      {/* KPI'lar */}
      {data && (
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {[
            { label: 'Toplam Metrik', value: data.total_metrics, accent: NEON.cyan },
            { label: 'Kronik (3+ gün)', value: data.chronic_count, accent: NEON.orange },
            { label: 'Bastırılıyor', value: data.suppressed_count, accent: NEON.green },
            { label: 'Düşürüldü', value: data.downgraded_count, accent: NEON.blue },
          ].map(k => (
            <div key={k.label} className="cyber-card p-3 flex flex-col gap-1">
              <span className="text-[10px] font-medium uppercase tracking-wide" style={{ color: 'rgba(148,163,184,0.5)' }}>{k.label}</span>
              <span className="text-2xl font-bold" style={{ color: k.accent }}>{k.value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Arama */}
      <SearchInput value={search} onChange={setSearch} placeholder="Metrik adı ara..." width="w-64" />

      {isLoading ? (
        <div className="py-16 flex justify-center"><div className="animate-spin rounded-full h-8 w-8 border-2 border-t-cyan-400 border-white/[0.06]" /></div>
      ) : filtered.length === 0 ? (
        <EmptyState icon="📊" text="Korelasyon verisi yok — AIOps döngüsünü çalıştırın." />
      ) : (
        <div className="space-y-2">
          {filtered.map(m => {
            const origColor = SEV_COLOR[m.max_severity] ?? NEON.cyan
            const effColor = SEV_COLOR[m.effective_severity] ?? NEON.cyan
            const degraded = m.effective_severity !== m.max_severity

            return (
              <div key={m.metric} className="cyber-card p-4">
                <div className="flex items-start gap-3 flex-wrap">
                  {/* Sol: Kronik göstergesi */}
                  <div className="flex-shrink-0 mt-1">
                    <div className="w-2.5 h-2.5 rounded-full"
                      style={{
                        background: m.is_very_chronic ? NEON.red : m.is_chronic ? NEON.orange : 'rgba(148,163,184,0.25)',
                        boxShadow: m.is_chronic ? `0 0 8px ${m.is_very_chronic ? NEON.red : NEON.orange}` : 'none',
                      }} />
                  </div>

                  {/* Orta: Metrik bilgisi */}
                  <div className="flex-1 min-w-0 space-y-1.5">
                    <p className="text-sm font-medium truncate" style={{ color: 'rgba(226,232,240,0.9)' }}>{m.metric}</p>

                    {/* Severity akışı */}
                    <div className="flex items-center gap-2 flex-wrap">
                      {/* Orijinal severity */}
                      <span className="text-[11px] px-1.5 py-0.5 rounded font-semibold uppercase"
                        style={{ background: `color-mix(in srgb, ${origColor} 12%, transparent)`, color: origColor, border: `1px solid color-mix(in srgb, ${origColor} 20%, transparent)` }}>
                        {m.max_severity}
                      </span>

                      {/* Ok (değiştiyse) */}
                      {degraded && (
                        <>
                          <span style={{ color: 'rgba(148,163,184,0.3)' }}>→</span>
                          <span className="text-[11px] px-1.5 py-0.5 rounded font-semibold uppercase"
                            style={{ background: `color-mix(in srgb, ${effColor} 12%, transparent)`, color: effColor, border: `1px solid color-mix(in srgb, ${effColor} 20%, transparent)` }}>
                            {m.is_suppressed ? 'bastırıldı' : m.effective_severity}
                          </span>
                        </>
                      )}

                      {/* Kronik rozeti */}
                      {m.is_very_chronic && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(239,68,68,0.1)', color: NEON.red, border: '1px solid rgba(239,68,68,0.2)' }}>
                          {m.recurrence_days}g kronik
                        </span>
                      )}
                      {m.is_chronic && !m.is_very_chronic && (
                        <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(251,191,36,0.1)', color: NEON.orange, border: '1px solid rgba(251,191,36,0.2)' }}>
                          {m.recurrence_days}g tekrar
                        </span>
                      )}
                    </div>

                    {/* Kural bilgisi */}
                    {m.suppression && (
                      <div className="text-[11px] flex items-center gap-1.5" style={{ color: 'rgba(148,163,184,0.55)' }}>
                        <span>📋</span>
                        <span>Kural #{m.suppression.id}:</span>
                        <span style={{ color: NEON.green }}>{m.suppression.reason || 'Suppression aktif'}</span>
                        {m.suppression.scope === 'global' && <span className="px-1 rounded text-[10px]" style={{ background: 'rgba(6,182,212,0.1)', color: NEON.cyan }}>global</span>}
                      </div>
                    )}

                    {/* İstatistik */}
                    <div className="flex gap-3 text-[10px]" style={{ color: 'rgba(148,163,184,0.4)' }}>
                      <span>{m.total_count} olay</span>
                      {m.server_count > 1 && <span>· {m.server_count} sunucu</span>}
                      {m.last_seen && <span>· Son: {new Date(m.last_seen).toLocaleString('tr-TR')}</span>}
                    </div>
                  </div>

                  {/* Sağ: Aksiyonlar */}
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {m.last_event_id && (
                      <a href={`/events?highlight=${m.last_event_id}`}
                        className="text-xs px-2 py-1 rounded transition-colors"
                        style={{ color: NEON.cyan, border: '1px solid rgba(6,182,212,0.2)', background: 'rgba(6,182,212,0.05)' }}>
                        Event →
                      </a>
                    )}
                    {!m.suppression && m.is_chronic && m.last_event_id && (
                      <button
                        onClick={() => suppress(m.metric, m.last_server_id, m.last_event_id)}
                        disabled={markLoading === m.last_event_id}
                        className="text-xs px-2 py-1 rounded transition-colors"
                        style={{ color: NEON.orange, border: '1px solid rgba(251,191,36,0.2)', background: 'rgba(251,191,36,0.06)' }}>
                        {markLoading === m.last_event_id ? '...' : 'Bu Normal'}
                      </button>
                    )}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

export function LogHeatmapPanel({ platform = 'linux' }: PlatformAiopsProps) {
  const [serverSearch, setServerSearch] = useState('')
  const [backfillDays, setBackfillDays] = useState(7)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const queryClient = useQueryClient()

  const { data: heatmapData, isLoading: heatmapLoading, error: heatmapError } = useQuery<LogHeatmapResponse>({
    queryKey: ['anomaly-log-heatmap-30d', platform],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/anomalies/logs/heatmap?days=30&platform=${platform}&actionable_only=true`)
      if (!r.ok) throw new Error()
      return r.json()
    },
    refetchInterval: 60000,
  })

  const backfillMutation = useMutation({
    mutationFn: async (days: number) => {
      const r = await fetch(`${API_BASE_URL}/anomalies/logs/backfill?days=${days}&platform=${platform}`, { method: 'POST' })
      if (!r.ok) throw new Error()
      return r.json()
    },
    onSuccess: () => {
      setMsg({ ok: true, text: 'Geçmiş veri yüklendi.' })
      queryClient.invalidateQueries({ queryKey: ['anomaly-log-heatmap-30d', platform] })
    },
    onError: () => setMsg({ ok: false, text: 'Backfill sırasında hata oluştu.' }),
  })

  const filteredHeatmapRows = useMemo(() => {
    const rows = heatmapData?.rows || []
    const q = serverSearch.trim().toLowerCase()
    const f = !q ? rows : rows.filter(r => r.server_name.toLowerCase().includes(q) || (r.ip_address || '').toLowerCase().includes(q))
    return [...f].sort((a, b) => b.total_score - a.total_score)
  }, [heatmapData, serverSearch])

  if (platform === 'virt') {
    return (
      <EmptyState icon="☁" text="Sanallaştırma modülünde log ısı haritası vCenter olayları üzerinden Events sekmesinde görüntülenir." />
    )
  }

  return (
    <div className="space-y-3">
      {msg && (
        <div className="px-4 py-2 rounded-xl text-sm" style={{ color: msg.ok ? NEON.green : NEON.red }}>{msg.text}</div>
      )}
      <div className="flex items-center gap-2 flex-wrap">
        <SearchInput value={serverSearch} onChange={setServerSearch} placeholder="Sunucu ara..." width="w-52" />
      </div>
      <Section title="30 Günlük Log Anomali Isı Haritası" accent={NEON.orange}
        right={
          <div className="flex items-center gap-2">
            <Select value={String(backfillDays)} onChange={v => setBackfillDays(Number(v))}>
              {[1, 3, 7, 14, 30].map(d => <option key={d} value={d}>{d} gün</option>)}
            </Select>
            <GhostButton accent={NEON.orange} onClick={() => backfillMutation.mutate(backfillDays)} disabled={backfillMutation.isPending}>
              {backfillMutation.isPending ? 'Yükleniyor...' : 'Geçmiş Veri'}
            </GhostButton>
          </div>
        }>
        <div className="px-5 py-2.5 flex flex-wrap items-center gap-3 text-xs" style={{ borderBottom: '1px solid rgba(99,130,194,0.08)' }}>
          <span style={{ color: 'rgba(148,163,184,0.5)' }}>Skala:</span>
          {[{ c: 'rgba(255,255,255,0.04)', l: 'Normal' }, { c: 'rgba(234,179,8,0.4)', l: 'Düşük' }, { c: 'rgba(245,200,11,0.6)', l: 'Orta' }, { c: 'rgba(245,158,11,0.8)', l: 'Yüksek' }, { c: 'rgba(239,68,68,0.85)', l: 'Kritik' }].map(s => (
            <span key={s.l} className="inline-flex items-center gap-1" style={{ color: 'rgba(148,163,184,0.7)' }}>
              <span className="w-3 h-3 rounded" style={{ background: s.c, border: '1px solid rgba(99,130,194,0.2)' }} />{s.l}
            </span>
          ))}
        </div>
        {heatmapLoading ? (
          <div className="p-6 text-sm" style={{ color: 'rgba(148,163,184,0.5)' }}>Harita yükleniyor...</div>
        ) : heatmapError ? (
          <div className="p-6 text-sm" style={{ color: NEON.red }}>Harita verisi alınamadı.</div>
        ) : (
          <div className="overflow-x-auto max-h-[560px]">
            <table className="min-w-full text-xs">
              <thead className="sticky top-0 z-20" style={{ background: 'var(--bg-deep)' }}>
                <tr>
                  <th className="sticky left-0 z-30 text-left px-3 py-2 min-w-[200px]" style={{ background: 'var(--bg-deep)', color: 'rgba(148,163,184,0.7)' }}>Sunucu</th>
                  {(heatmapData?.dates || []).map(d => <th key={d} className="px-1 py-2 whitespace-nowrap" style={{ color: 'rgba(148,163,184,0.5)' }}>{formatDayLabel(d)}</th>)}
                </tr>
              </thead>
              <tbody>
                {filteredHeatmapRows.length === 0 && <tr><td colSpan={(heatmapData?.dates?.length || 0) + 1} className="px-4 py-6 text-center" style={{ color: 'rgba(148,163,184,0.5)' }}>Veri bulunamadı.</td></tr>}
                {filteredHeatmapRows.map(row => (
                  <tr key={row.server_id} style={{ borderTop: '1px solid rgba(30,41,59,0.6)' }}>
                    <td className="sticky left-0 z-10 px-3 py-2 whitespace-nowrap" style={{ background: 'var(--bg-card)' }}>
                      <div className="font-medium text-white">{row.server_name}</div>
                      <div className="text-[10px]" style={{ color: 'rgba(148,163,184,0.5)' }}>{row.ip_address || '-'}</div>
                    </td>
                    {row.cells.map(cell => (
                      <td key={`${row.server_id}-${cell.date}`} className="px-1 py-1">
                        <div title={cell.score > 0 ? `${row.server_name} | ${cell.date} | skor: ${cell.score}` : `${row.server_name} | ${cell.date} | normal`}
                          className="w-6 h-6 rounded-md mx-auto transition-transform hover:scale-125 flex items-center justify-center"
                          style={{ background: heatColor(cell.score, heatmapData?.max_cell_score || 0), border: '1px solid rgba(99,130,194,0.12)' }}>
                          {cell.score === 0 && <span className="text-[10px]" style={{ color: 'rgba(148,163,184,0.3)' }}>·</span>}
                        </div>
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Section>
    </div>
  )
}

const AnomalyDetection: React.FC<PlatformAiopsProps> = ({ platform = 'linux' }) => {
  const [tab, setTab] = useState('metric')
  const [serverSearch, setServerSearch] = useState('')
  const [backfillDays, setBackfillDays] = useState(7)
  const [msg, setMsg] = useState<{ text: string; ok: boolean } | null>(null)
  const queryClient = useQueryClient()

  const { data: aiops } = useQuery<AiopsStatus>({
    queryKey: ['aiops-status'],
    queryFn: async () => { const r = await fetch(`${API_BASE_URL}/anomalies/aiops-status`); if (!r.ok) throw new Error(); return r.json() },
    refetchInterval: 30000,
  })
  const { data: metricData, isLoading: metricLoading } = useQuery<{ anomalies: MetricAnomaly[] }>({
    queryKey: ['metric-anomalies-live', platform],
    queryFn: async () => { const r = await fetch(`${API_BASE_URL}/anomalies/?platform=${platform}`); if (!r.ok) throw new Error(); return r.json() },
    refetchInterval: 60000,
  })
  const { data, isLoading, isFetching, error, refetch } = useQuery<LogListResponse>({
    queryKey: ['anomaly-log-list-30d', platform],
    queryFn: async () => { const r = await fetch(`${API_BASE_URL}/anomalies/logs/list?days=30&platform=${platform}&actionable_only=true`); if (!r.ok) throw new Error(); return r.json() },
    refetchInterval: 60000,
  })
  const { data: heatmapData, isLoading: heatmapLoading, error: heatmapError } = useQuery<LogHeatmapResponse>({
    queryKey: ['anomaly-log-heatmap-30d', platform],
    queryFn: async () => { const r = await fetch(`${API_BASE_URL}/anomalies/logs/heatmap?days=30&platform=${platform}&actionable_only=true`); if (!r.ok) throw new Error(); return r.json() },
    refetchInterval: 60000,
  })

  const cycleMutation = useMutation({
    mutationFn: async () => { const r = await fetch(`${API_BASE_URL}/anomalies/run-cycle`, { method: 'POST' }); if (!r.ok) throw new Error(); return r.json() },
    onSuccess: (res) => {
      setMsg({ ok: true, text: `Döngü çalıştı: ${res.scanned_anomalies} anomali, ${res.created} yeni event, ${res.incidents} incident, ${res.resolved} çözüldü. AI RCA arka planda.` })
      queryClient.invalidateQueries({ queryKey: ['aiops-status'] })
      queryClient.invalidateQueries({ queryKey: ['metric-anomalies-live'] })
    },
    onError: () => setMsg({ ok: false, text: 'Döngü çalıştırılamadı.' }),
  })
  const escalateMutation = useMutation({
    mutationFn: async (a: MetricAnomaly) => {
      const r = await fetch(`${API_BASE_URL}/incidents/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          title: a.message,
          description: `Manuel yükseltildi.\nMetrik: ${a.metric_name}\nDeğer: ${a.current_value}\nSunucu: ${a.server_name} (${a.ip_address || '-'})`,
          severity: a.severity === 'critical' ? 'critical' : 'high', source: 'manual_escalation', affected_servers: [a.server_id],
        }),
      })
      if (!r.ok) throw new Error(); return r.json()
    },
    onSuccess: (res) => setMsg({ ok: true, text: `Incident #${res.id} oluşturuldu. Incidents sayfasından RCA çalıştırabilirsiniz.` }),
    onError: () => setMsg({ ok: false, text: 'Incident oluşturulamadı.' }),
  })
  const backfillMutation = useMutation({
    mutationFn: async (days: number) => { const r = await fetch(`${API_BASE_URL}/anomalies/logs/backfill?days=${days}&platform=${platform}`, { method: 'POST' }); if (!r.ok) throw new Error(); return r.json() },
    onSuccess: (result) => {
      setMsg({ ok: true, text: `${result.backfill_days} gün backfill: ${result.total_saved ?? 0} yeni log (${result.servers_with_logs ?? 0} sunucu)` })
      queryClient.invalidateQueries({ queryKey: ['anomaly-log-heatmap-30d'] })
      queryClient.invalidateQueries({ queryKey: ['anomaly-log-list-30d'] })
    },
    onError: () => setMsg({ ok: false, text: 'Backfill sırasında hata oluştu.' }),
  })

  const metricAnomalies = metricData?.anomalies || []
  const filteredMetric = useMemo(() => {
    const q = serverSearch.trim().toLowerCase()
    return q ? metricAnomalies.filter(a => (a.server_name || '').toLowerCase().includes(q)) : metricAnomalies
  }, [metricAnomalies, serverSearch])
  const anomalies = data?.anomalies || []
  const filteredAnomalies = useMemo(() => {
    const q = serverSearch.trim().toLowerCase()
    return q ? anomalies.filter(a => (a.server_name || '').toLowerCase().includes(q)) : anomalies
  }, [anomalies, serverSearch])
  const filteredHeatmapRows = useMemo(() => {
    const rows = heatmapData?.rows || []
    const q = serverSearch.trim().toLowerCase()
    const f = !q ? rows : rows.filter(r => r.server_name.toLowerCase().includes(q) || (r.ip_address || '').toLowerCase().includes(q))
    return [...f].sort((a, b) => b.total_score - a.total_score)
  }, [heatmapData, serverSearch])

  return (
    <div className="space-y-4 animate-fade-in">
      <PageHeader title="Anomaly Detection" subtitle="Otonom tespit · otomatik incident · yapay zeka kök neden analizi"
        actions={<>
          <PrimaryButton accent={NEON.cyan} onClick={() => cycleMutation.mutate()} disabled={cycleMutation.isPending}>
            {cycleMutation.isPending ? 'Çalışıyor...' : 'Döngüyü Çalıştır'}
          </PrimaryButton>
          <Link to="/events"><GhostButton accent={NEON.blue}>Events →</GhostButton></Link>
          <Link to="/incidents"><GhostButton accent={NEON.orange}>Incidents →</GhostButton></Link>
        </>} />

      {msg && (
        <div className="px-4 py-3 rounded-xl text-sm font-medium flex items-center justify-between"
          style={{ background: msg.ok ? `rgba(${rgb(NEON.green)},0.1)` : `rgba(${rgb(NEON.red)},0.1)`, border: `1px solid rgba(${rgb(msg.ok ? NEON.green : NEON.red)},0.3)`, color: msg.ok ? NEON.green : NEON.red }}>
          <span>{msg.text}</span>
          <button onClick={() => setMsg(null)} className="ml-3 opacity-60 hover:opacity-100">✕</button>
        </div>
      )}

      <PipelineFlow status={aiops} />

      <div className="grid grid-cols-2 lg:grid-cols-5 gap-3">
        <Kpi label="İzlenen Sunucu" value={aiops?.monitored_servers ?? 0} accent={NEON.cyan} />
        <Kpi label="Aktif Anomali" value={aiops?.active_metric_anomalies ?? 0} accent={NEON.blue} />
        <Kpi label="Kritik" value={aiops?.active_metric_critical ?? 0} accent={NEON.red} />
        <Kpi label="Açık Incident" value={aiops?.open_incidents ?? 0} accent={NEON.orange} />
        <Kpi label="RCA Tamamlanan" value={aiops?.incidents_with_rca ?? 0} accent={NEON.green} />
      </div>

      {/* Tabs + search */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <Tabs active={tab} onChange={setTab} tabs={[
          { id: 'metric', label: 'Metrik Anomalileri', count: filteredMetric.length },
          { id: 'heatmap', label: 'Log Isı Haritası' },
          { id: 'list', label: 'Log Listesi', count: data?.total },
          { id: 'correlation', label: 'Korelasyon' },
        ]} />
        <div className="flex items-center gap-2">
          <SearchInput value={serverSearch} onChange={setServerSearch} placeholder="Sunucu ara..." width="w-52" />
          <GhostButton onClick={() => refetch()}>{isFetching ? '...' : 'Yenile'}</GhostButton>
        </div>
      </div>

      {/* TAB: Metric */}
      {tab === 'metric' && (
        <Section title="Canlı Metrik Anomalileri" accent={NEON.blue}
          right={<span className="text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>Prometheus · Z-score + eşik</span>}>
          {metricLoading ? (
            <div className="p-6 text-sm" style={{ color: 'rgba(148,163,184,0.5)' }}>Taranıyor...</div>
          ) : filteredMetric.length === 0 ? (
            <EmptyState icon="✓" text="Şu an metrik anomalisi yok — tüm sistemler normal aralıkta" />
          ) : (
            <div className="overflow-x-auto overflow-y-visible">
              <table className="cyber-table min-w-full text-sm">
                <thead><tr>
                  <th className="text-left">Severity</th><th className="text-left">Sunucu</th><th className="text-left">Metrik</th>
                  <th className="text-left">Değer</th><th className="text-left">Z-score</th><th className="text-right">İşlem</th>
                </tr></thead>
                <tbody>
                  {filteredMetric.map((a, idx) => (
                    <tr key={`${a.server_id}-${a.metric_name}-${idx}`}>
                      <td><SeverityBadge severity={a.severity} /></td>
                      <td><div className="text-white font-medium">{a.server_name}</div><div className="text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>{a.ip_address}</div></td>
                      <td className="font-mono text-xs" style={{ color: NEON.cyan }}>{a.metric_name}</td>
                      <td className="text-white font-semibold">{a.current_value}{a.mean_value != null && <span className="text-xs ml-1" style={{ color: 'rgba(148,163,184,0.5)' }}>(norm: {a.mean_value})</span>}</td>
                      <td>{a.z_score != null ? <span className="font-mono text-xs" style={{ color: Math.abs(a.z_score) >= 3 ? NEON.red : NEON.orange }}>{a.z_score > 0 ? '+' : ''}{a.z_score}σ</span> : <span className="text-slate-600">—</span>}</td>
                      <td><div className="flex justify-end"><GhostButton accent={NEON.orange} onClick={() => escalateMutation.mutate(a)} disabled={escalateMutation.isPending}>Incident'a Yükselt</GhostButton></div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {/* TAB: Heatmap */}
      {tab === 'heatmap' && (
        <Section title="30 Günlük Log Anomali Isı Haritası" accent={NEON.orange}
          right={
            <div className="flex items-center gap-2">
              <Select value={String(backfillDays)} onChange={v => setBackfillDays(Number(v))}>
                {[1, 3, 7, 14, 30].map(d => <option key={d} value={d}>{d} gün</option>)}
              </Select>
              <GhostButton accent={NEON.orange} onClick={() => backfillMutation.mutate(backfillDays)} disabled={backfillMutation.isPending}>
                {backfillMutation.isPending ? 'Yükleniyor...' : '📥 Geçmiş Veri'}
              </GhostButton>
            </div>
          }>
          <div className="px-5 py-2.5 flex flex-wrap items-center gap-3 text-xs" style={{ borderBottom: '1px solid rgba(99,130,194,0.08)' }}>
            <span style={{ color: 'rgba(148,163,184,0.5)' }}>Skala:</span>
            {[{ c: 'rgba(255,255,255,0.04)', l: 'Normal' }, { c: 'rgba(234,179,8,0.4)', l: 'Düşük' }, { c: 'rgba(245,200,11,0.6)', l: 'Orta' }, { c: 'rgba(245,158,11,0.8)', l: 'Yüksek' }, { c: 'rgba(239,68,68,0.85)', l: 'Kritik' }].map(s => (
              <span key={s.l} className="inline-flex items-center gap-1" style={{ color: 'rgba(148,163,184,0.7)' }}>
                <span className="w-3 h-3 rounded" style={{ background: s.c, border: '1px solid rgba(99,130,194,0.2)' }} />{s.l}
              </span>
            ))}
          </div>
          {heatmapLoading ? (
            <div className="p-6 text-sm" style={{ color: 'rgba(148,163,184,0.5)' }}>Harita yükleniyor...</div>
          ) : heatmapError ? (
            <div className="p-6 text-sm" style={{ color: NEON.red }}>Harita verisi alınamadı.</div>
          ) : (
            <div className="overflow-x-auto max-h-[560px]">
              <table className="min-w-full text-xs">
                <thead className="sticky top-0 z-20" style={{ background: 'var(--bg-deep)' }}>
                  <tr>
                    <th className="sticky left-0 z-30 text-left px-3 py-2 min-w-[200px]" style={{ background: 'var(--bg-deep)', color: 'rgba(148,163,184,0.7)' }}>Sunucu</th>
                    {(heatmapData?.dates || []).map(d => <th key={d} className="px-1 py-2 whitespace-nowrap" style={{ color: 'rgba(148,163,184,0.5)' }}>{formatDayLabel(d)}</th>)}
                  </tr>
                </thead>
                <tbody>
                  {filteredHeatmapRows.length === 0 && <tr><td colSpan={(heatmapData?.dates?.length || 0) + 1} className="px-4 py-6 text-center" style={{ color: 'rgba(148,163,184,0.5)' }}>Veri bulunamadı.</td></tr>}
                  {filteredHeatmapRows.map(row => (
                    <tr key={row.server_id} style={{ borderTop: '1px solid rgba(30,41,59,0.6)' }}>
                      <td className="sticky left-0 z-10 px-3 py-2 whitespace-nowrap" style={{ background: 'var(--bg-card)' }}>
                        <div className="font-medium text-white">{row.server_name}</div>
                        <div className="text-[10px]" style={{ color: 'rgba(148,163,184,0.5)' }}>{row.ip_address || '-'}</div>
                        <div className="text-[10px]" style={{ color: 'rgba(148,163,184,0.5)' }}>Skor: {row.total_score} · Kayıt: {row.total_count}</div>
                      </td>
                      {row.cells.map(cell => (
                        <td key={`${row.server_id}-${cell.date}`} className="px-1 py-1">
                          <div title={cell.score > 0 ? `${row.server_name} | ${cell.date} | kayıt: ${cell.count}, skor: ${cell.score}` : `${row.server_name} | ${cell.date} | normal`}
                            className="w-6 h-6 rounded-md mx-auto transition-transform hover:scale-125 flex items-center justify-center"
                            style={{ background: heatColor(cell.score, heatmapData?.max_cell_score || 0), border: '1px solid rgba(99,130,194,0.12)' }}>
                            {cell.score === 0 && <span className="text-[10px]" style={{ color: 'rgba(148,163,184,0.3)' }}>·</span>}
                          </div>
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {/* TAB: List */}
      {tab === 'list' && (
        <Section title="Log Anomali Listesi" accent={NEON.blue}
          right={<span className="text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>{data?.generated_at ? new Date(data.generated_at).toLocaleString('tr-TR') : '-'}</span>}>
          {isLoading ? (
            <div className="p-6 text-sm" style={{ color: 'rgba(148,163,184,0.5)' }}>Yükleniyor...</div>
          ) : error ? (
            <div className="p-6 text-sm" style={{ color: NEON.red }}>Veri alınamadı.</div>
          ) : filteredAnomalies.length === 0 ? (
            <EmptyState icon="" text="Filtreye uyan anomali yok" />
          ) : (
            <div className="overflow-x-auto max-h-[560px]">
              <table className="cyber-table min-w-full text-sm">
                <thead><tr><th className="text-left">Tarih</th><th className="text-left">Severity</th><th className="text-left">Sunucu</th><th className="text-left">Detay</th></tr></thead>
                <tbody>
                  {filteredAnomalies.map((a, idx) => (
                    <tr key={`${a.id}-${idx}`}>
                      <td style={{ color: 'rgba(148,163,184,0.7)' }}>{a.created_at ? new Date(a.created_at).toLocaleString('tr-TR') : '-'}</td>
                      <td><SeverityBadge severity={a.severity} /></td>
                      <td className="text-white">{a.server_name || '-'}</td>
                      <td style={{ color: 'rgba(226,232,240,0.8)' }}>{a.title || a.message || 'Detay yok'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Section>
      )}

      {tab === 'correlation' && <CorrelationTab />}
    </div>
  )
}

export default AnomalyDetection
