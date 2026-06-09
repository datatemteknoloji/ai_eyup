import React, { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { API_BASE_URL } from '../config/api'
import {
  NEON, PageHeader, GhostButton, PrimaryButton, SeverityBadge,
  SearchInput, Select, Section, EmptyState,
} from '../components/aiops/ui'

interface EventItem {
  id: number
  server_id: number | null
  server_name: string | null
  event_type: string
  severity: string
  title: string
  description: string | null
  created_at: string | null
  resolved: boolean
  is_acknowledged: boolean
}

interface LogAnalysisResult {
  root_cause: string
  impact: string
  recommendations: string[]
  confidence: 'high' | 'medium' | 'low'
  log_lines_used: number
  model: string
  requires_approval: boolean
  analyzed_at: string
}

interface AnalysisState {
  [eventId: number]: { loading: boolean; result?: LogAnalysisResult; error?: string }
}

const CONFIDENCE_COLORS = {
  high: { bg: 'rgba(34,197,94,0.10)', border: 'rgba(34,197,94,0.25)', text: NEON.green, label: 'Yüksek Güven' },
  medium: { bg: 'rgba(251,191,36,0.08)', border: 'rgba(251,191,36,0.25)', text: NEON.orange, label: 'Orta Güven' },
  low: { bg: 'rgba(148,163,184,0.06)', border: 'rgba(148,163,184,0.15)', text: 'rgba(148,163,184,0.7)', label: 'Düşük Güven' },
}

const MUTATING_KW = ['systemctl', 'service', 'restart', 'reboot', 'rm ', 'kill', 'pkill']

function AnalysisCard({ result, eventTitle }: { result: LogAnalysisResult; eventTitle: string }) {
  const conf = CONFIDENCE_COLORS[result.confidence] || CONFIDENCE_COLORS.low
  const hasApproval = result.requires_approval || result.recommendations.some(r => MUTATING_KW.some(k => r.toLowerCase().includes(k)))

  return (
    <div className="space-y-3 mt-3">
      {/* Meta */}
      <div className="flex flex-wrap items-center gap-2 text-xs" style={{ color: 'rgba(148,163,184,0.55)' }}>
        <span className="px-2 py-0.5 rounded-full font-medium"
          style={{ background: conf.bg, color: conf.text, border: `1px solid ${conf.border}` }}>
          {conf.label}
        </span>
        <span>{result.log_lines_used} log satırı</span>
        <span>·</span>
        <span>{result.model}</span>
        <span>·</span>
        <span>{new Date(result.analyzed_at).toLocaleTimeString('tr-TR')}</span>
      </div>

      {/* Kök neden */}
      <div className="p-3 rounded-[8px]"
        style={{ background: 'rgba(6,182,212,0.06)', border: '1px solid rgba(6,182,212,0.14)' }}>
        <div className="text-[11px] font-semibold uppercase tracking-wide mb-1" style={{ color: NEON.cyan }}>Kök Neden</div>
        <p className="text-sm leading-relaxed" style={{ color: 'rgba(226,232,240,0.9)' }}>{result.root_cause}</p>
      </div>

      {/* Etki */}
      {result.impact && (
        <div className="p-3 rounded-[8px]"
          style={{ background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.12)' }}>
          <div className="text-[11px] font-semibold uppercase tracking-wide mb-1" style={{ color: NEON.orange }}>Etki Analizi</div>
          <p className="text-sm leading-relaxed" style={{ color: 'rgba(226,232,240,0.85)' }}>{result.impact}</p>
        </div>
      )}

      {/* Öneriler */}
      {result.recommendations.length > 0 && (
        <div className="p-3 rounded-[8px]"
          style={{ background: 'rgba(34,197,94,0.05)', border: '1px solid rgba(34,197,94,0.12)' }}>
          <div className="flex items-center gap-2 text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: NEON.green }}>
            Önerilen Aksiyonlar
            {hasApproval && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-medium normal-case"
                style={{ background: 'rgba(251,191,36,0.12)', color: NEON.orange, border: '1px solid rgba(251,191,36,0.25)' }}>
                Onay Gerekli
              </span>
            )}
          </div>
          <ol className="space-y-2">
            {result.recommendations.map((rec, i) => (
              <li key={i} className="flex gap-2.5 items-start">
                <span className="mt-0.5 flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[11px] font-bold"
                  style={{ background: 'rgba(34,197,94,0.14)', color: NEON.green }}>{i + 1}</span>
                <code className="text-[12px] leading-relaxed font-mono px-1.5 py-0.5 rounded"
                  style={{ background: 'rgba(0,0,0,0.25)', color: 'rgba(226,232,240,0.9)' }}>{rec}</code>
              </li>
            ))}
          </ol>
        </div>
      )}
    </div>
  )
}

const RootCauseAnalysis: React.FC = () => {
  const [search, setSearch] = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('log_entry')
  const [analyses, setAnalyses] = useState<AnalysisState>({})
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  const { data, isLoading } = useQuery({
    queryKey: ['rca-events', severityFilter, typeFilter, search],
    queryFn: async () => {
      const params = new URLSearchParams({
        limit: '50', resolved: 'false',
        ...(severityFilter && { severity: severityFilter }),
        ...(typeFilter && { event_type: typeFilter }),
        ...(search && { search }),
      })
      const res = await fetch(`${API_BASE_URL}/events/?${params}`)
      return res.json() as Promise<{ events: EventItem[]; total: number }>
    },
    refetchInterval: 30000,
  })

  const events = data?.events ?? []

  const analyze = async (event: EventItem) => {
    setAnalyses(prev => ({ ...prev, [event.id]: { loading: true } }))
    setExpanded(prev => { const n = new Set(prev); n.add(event.id); return n })
    try {
      const res = await fetch(`${API_BASE_URL}/events/${event.id}/log-analyze`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Bağlantı hatası' }))
        setAnalyses(prev => ({ ...prev, [event.id]: { loading: false, error: err.detail || `HTTP ${res.status}` } }))
        return
      }
      const result: LogAnalysisResult = await res.json()
      setAnalyses(prev => ({ ...prev, [event.id]: { loading: false, result } }))
    } catch {
      setAnalyses(prev => ({ ...prev, [event.id]: { loading: false, error: 'Analiz isteği başarısız.' } }))
    }
  }

  const analyzeAll = async () => {
    const pending = events.filter(e => !analyses[e.id]?.result && !analyses[e.id]?.loading).slice(0, 5)
    for (const ev of pending) { analyze(ev) }
  }

  const analyzedCount = Object.values(analyses).filter(a => a.result).length
  const highConfCount = Object.values(analyses).filter(a => a.result?.confidence === 'high').length

  return (
    <div className="space-y-6">
      <PageHeader
        title="Kök Neden Analizi"
        subtitle="Log satırları ve metrik anomalileri için AI destekli otomatik kök neden tespiti"
        actions={
          <div className="flex items-center gap-2">
            <GhostButton accent={NEON.cyan} onClick={analyzeAll} disabled={events.length === 0}>
              Toplu Analiz (ilk 5)
            </GhostButton>
          </div>
        }
      />

      {/* KPI bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Analize Hazır', value: events.length, accent: NEON.blue },
          { label: 'Analiz Yapıldı', value: analyzedCount, accent: NEON.cyan },
          { label: 'Yüksek Güven', value: highConfCount, accent: NEON.green },
          { label: 'Onay Gerekli', value: Object.values(analyses).filter(a => a.result?.requires_approval).length, accent: NEON.orange },
        ].map(k => (
          <div key={k.label} className="cyber-card p-3 flex flex-col gap-1">
            <span className="text-[11px] font-medium uppercase tracking-wide" style={{ color: 'rgba(148,163,184,0.55)' }}>{k.label}</span>
            <span className="text-2xl font-bold" style={{ color: k.accent }}>{k.value}</span>
          </div>
        ))}
      </div>

      {/* Filtreler */}
      <Section>
        <div className="flex flex-wrap gap-3 p-4">
          <SearchInput value={search} onChange={setSearch} placeholder="Başlık veya sunucu ara..." className="flex-1 min-w-[200px]" />
          <Select value={typeFilter} onChange={setTypeFilter} options={[
            { value: '', label: 'Tüm tipler' },
            { value: 'log_entry', label: 'Log Entry' },
            { value: 'metric_anomaly', label: 'Metrik Anomali' },
          ]} />
          <Select value={severityFilter} onChange={setSeverityFilter} options={[
            { value: '', label: 'Tüm önemler' },
            { value: 'critical', label: 'Kritik' },
            { value: 'warning', label: 'Uyarı' },
            { value: 'info', label: 'Bilgi' },
          ]} />
        </div>
      </Section>

      {/* Event listesi */}
      {isLoading ? (
        <div className="py-16 flex justify-center">
          <div className="animate-spin rounded-full h-8 w-8 border-2 border-t-cyan-400 border-white/[0.06]" />
        </div>
      ) : events.length === 0 ? (
        <EmptyState
          title="Analiz edilecek event yok"
          description="Seçili filtrelere göre çözümlenmemiş event bulunamadı."
        />
      ) : (
        <div className="space-y-2">
          {events.map(event => {
            const state = analyses[event.id]
            const isExpanded = expanded.has(event.id)

            return (
              <div key={event.id} className="cyber-card overflow-hidden transition-all">
                {/* Event satırı */}
                <div className="flex items-start gap-3 p-4">
                  {/* Severity indicator */}
                  <div className="mt-0.5 flex-shrink-0">
                    <div className="w-2 h-2 rounded-full mt-1.5"
                      style={{
                        background: event.severity === 'critical' ? NEON.red
                          : event.severity === 'warning' ? NEON.orange
                          : NEON.cyan,
                        boxShadow: `0 0 6px ${event.severity === 'critical' ? NEON.red : event.severity === 'warning' ? NEON.orange : NEON.cyan}`,
                      }} />
                  </div>

                  {/* Event bilgisi */}
                  <div className="flex-1 min-w-0">
                    <div className="flex flex-wrap items-center gap-2 mb-1">
                      <SeverityBadge severity={event.severity} />
                      <span className="text-[11px] px-1.5 py-0.5 rounded"
                        style={{ background: 'rgba(255,255,255,0.05)', color: 'rgba(148,163,184,0.6)' }}>
                        {event.event_type}
                      </span>
                      {event.server_name && (
                        <span className="text-[11px]" style={{ color: NEON.cyan }}>{event.server_name}</span>
                      )}
                    </div>
                    <p className="text-sm font-medium leading-snug" style={{ color: 'rgba(226,232,240,0.9)' }}>
                      {event.title}
                    </p>
                    {event.description && (
                      <p className="text-xs mt-0.5 line-clamp-2" style={{ color: 'rgba(148,163,184,0.55)' }}>
                        {event.description}
                      </p>
                    )}
                    <p className="text-[11px] mt-1" style={{ color: 'rgba(148,163,184,0.4)' }}>
                      {event.created_at ? new Date(event.created_at).toLocaleString('tr-TR') : '—'}
                    </p>
                  </div>

                  {/* Aksiyon butonları */}
                  <div className="flex items-center gap-2 flex-shrink-0">
                    {state?.result && (
                      <button
                        onClick={() => setExpanded(prev => {
                          const n = new Set(prev); n.has(event.id) ? n.delete(event.id) : n.add(event.id); return n
                        })}
                        className="text-[11px] px-2 py-1 rounded transition-colors"
                        style={{ color: NEON.cyan, border: `1px solid rgba(6,182,212,0.2)`, background: 'rgba(6,182,212,0.05)' }}
                      >
                        {isExpanded ? 'Gizle' : 'Sonucu Gör'}
                      </button>
                    )}
                    <PrimaryButton
                      accent={state?.result ? NEON.slate : NEON.cyan}
                      onClick={() => analyze(event)}
                      disabled={state?.loading}
                    >
                      {state?.loading
                        ? <span className="flex items-center gap-1.5">
                            <span className="w-3 h-3 border border-t-transparent rounded-full animate-spin" style={{ borderColor: `${NEON.cyan} transparent` }} />
                            Analiz...
                          </span>
                        : state?.result ? 'Yenile' : 'Analiz Et'
                      }
                    </PrimaryButton>
                  </div>
                </div>

                {/* Analiz sonucu */}
                {isExpanded && state?.error && (
                  <div className="px-4 pb-4">
                    <div className="text-sm p-3 rounded-[8px]"
                      style={{ background: 'rgba(239,68,68,0.07)', color: NEON.red, border: '1px solid rgba(239,68,68,0.18)' }}>
                      {state.error}
                    </div>
                  </div>
                )}
                {isExpanded && state?.result && (
                  <div className="px-4 pb-4 border-t" style={{ borderColor: 'rgba(255,255,255,0.04)' }}>
                    <AnalysisCard result={state.result} eventTitle={event.title} />
                  </div>
                )}
                {state?.loading && (
                  <div className="px-4 pb-3 flex items-center gap-2 text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>
                    <div className="w-3 h-3 border border-t-transparent rounded-full animate-spin"
                      style={{ borderColor: `${NEON.cyan} transparent ${NEON.cyan} ${NEON.cyan}` }} />
                    Log satırları okunuyor, AI analiz yapıyor...
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Events sayfasına link */}
      <div className="text-center pt-2">
        <Link to="/events" className="text-xs" style={{ color: 'rgba(148,163,184,0.4)' }}>
          Tüm eventleri görmek için Events sayfasına git
        </Link>
      </div>
    </div>
  )
}

export default RootCauseAnalysis
