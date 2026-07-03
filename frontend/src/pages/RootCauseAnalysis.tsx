import React, { useState, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { API_BASE_URL } from '../config/api'
import type { PlatformAiopsProps } from '../utils/platformApi'
import { appendPlatform } from '../utils/platformApi'
import {
  NEON, PageHeader, GhostButton, PrimaryButton, SeverityBadge,
  SearchInput, Select, Section, EmptyState,
} from '../components/aiops/ui'

// ── Tipler ────────────────────────────────────────────────────────────────────

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

interface WindowStats {
  since: string; until: string; total_events: number
  severity_counts: Record<string, number>
  type_counts: Record<string, number>
  top_titles: { title: string; count: number }[]
  critical_samples: { ts: string; severity: string; type: string; title: string; description: string }[]
  error_rate: number
}

interface CompareResult {
  window_a: WindowStats; window_b: WindowStats
  delta: {
    total_events_change: number; total_events_pct: number | null
    error_events_change: number; error_events_pct: number | null
    error_rate_change: number
    new_event_types: string[]; disappeared_event_types: string[]
  }
  llm_analysis: {
    summary?: string; key_differences?: string[]
    regression_indicators?: string[]; recommendations?: string[]
    confidence?: string
  }
  model: string; analyzed_at: string
}

interface AWRReport {
  db_name: string; db_id: string; instance_name: string; host_name: string
  db_version: string; snap_begin: string; snap_end: string
  elapsed_minutes: number; db_time_minutes: number
  load_profile: { db_cpu_per_sec: number; db_time_per_sec: number; logical_reads_per_sec: number; physical_reads_per_sec: number }
  buffer_cache_hit_pct: number; library_cache_hit_pct: number
  top_wait_events: { event: string; time_s: number; avg_wait_ms: number; pct_db_time: number; wait_class: string }[]
  top_sql_cpu: { sql_id: string; cpu_s: number; elapsed_s: number; executions: number; pct_total: number; sql_text: string }[]
  top_sql_elapsed: { sql_id: string; cpu_s: number; elapsed_s: number; executions: number; pct_total: number; sql_text: string }[]
  parse_errors: string[]
}

interface AWRAnalyzeResult {
  report: AWRReport
  llm_analysis: {
    summary?: string; bottlenecks?: string[]; top_sql_findings?: string[]
    wait_event_analysis?: string[]; recommendations?: string[]
    baseline_comparison?: string; severity?: string; confidence?: string
  }
  baseline_report?: AWRReport
  model: string; analyzed_at: string
}

// ── Sabit renkler ─────────────────────────────────────────────────────────────

const CONFIDENCE_COLORS = {
  high: { bg: 'rgba(34,197,94,0.10)', border: 'rgba(34,197,94,0.25)', text: NEON.green, label: 'Yüksek Güven' },
  medium: { bg: 'rgba(251,191,36,0.08)', border: 'rgba(251,191,36,0.25)', text: NEON.orange, label: 'Orta Güven' },
  low: { bg: 'rgba(148,163,184,0.06)', border: 'rgba(148,163,184,0.15)', text: 'rgba(148,163,184,0.7)', label: 'Düşük Güven' },
} as const

const MUTATING_KW = ['systemctl', 'service', 'restart', 'reboot', 'rm ', 'kill', 'pkill']

// ── Ortak bileşenler ─────────────────────────────────────────────────────────

function ConfidenceBadge({ confidence }: { confidence?: string }) {
  const c = CONFIDENCE_COLORS[(confidence as keyof typeof CONFIDENCE_COLORS) ?? 'low'] ?? CONFIDENCE_COLORS.low
  return (
    <span className="px-2 py-0.5 rounded-full text-xs font-medium"
      style={{ background: c.bg, color: c.text, border: `1px solid ${c.border}` }}>
      {c.label}
    </span>
  )
}

function LLMSection({ title, items, accent }: { title: string; items?: string[]; accent: string }) {
  if (!items?.length) return null
  return (
    <div className="p-3 rounded-[8px]" style={{ background: `color-mix(in srgb, ${accent} 5%, transparent)`, border: `1px solid color-mix(in srgb, ${accent} 15%, transparent)` }}>
      <div className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: accent }}>{title}</div>
      <ul className="space-y-1.5">
        {items.map((item, i) => (
          <li key={i} className="flex gap-2 text-sm leading-relaxed" style={{ color: 'rgba(226,232,240,0.88)' }}>
            <span className="flex-shrink-0 mt-0.5" style={{ color: accent }}>▸</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  )
}

function DeltaBadge({ value, pct, invert = false }: { value: number; pct?: number | null; invert?: boolean }) {
  const bad = invert ? value < 0 : value > 0
  const color = value === 0 ? 'rgba(148,163,184,0.5)' : bad ? NEON.red : NEON.green
  return (
    <span className="font-mono text-xs font-bold" style={{ color }}>
      {value > 0 ? '+' : ''}{value}
      {pct !== null && pct !== undefined ? ` (${pct > 0 ? '+' : ''}${pct.toFixed(1)}%)` : ''}
    </span>
  )
}

// ── Log Analiz Kartı ──────────────────────────────────────────────────────────

function AnalysisCard({ result }: { result: LogAnalysisResult }) {
  const hasApproval = result.requires_approval || result.recommendations.some(r => MUTATING_KW.some(k => r.toLowerCase().includes(k)))

  return (
    <div className="space-y-3 mt-3">
      <div className="flex flex-wrap items-center gap-2 text-xs" style={{ color: 'rgba(148,163,184,0.55)' }}>
        <ConfidenceBadge confidence={result.confidence} />
        <span>{result.log_lines_used} log satırı</span>
        <span>·</span><span>{result.model}</span>
        <span>·</span><span>{new Date(result.analyzed_at).toLocaleTimeString('tr-TR')}</span>
      </div>
      <div className="p-3 rounded-[8px]" style={{ background: 'rgba(6,182,212,0.06)', border: '1px solid rgba(6,182,212,0.14)' }}>
        <div className="text-[11px] font-semibold uppercase tracking-wide mb-1" style={{ color: NEON.cyan }}>Kök Neden</div>
        <p className="text-sm leading-relaxed" style={{ color: 'rgba(226,232,240,0.9)' }}>{result.root_cause}</p>
      </div>
      {result.impact && (
        <div className="p-3 rounded-[8px]" style={{ background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.12)' }}>
          <div className="text-[11px] font-semibold uppercase tracking-wide mb-1" style={{ color: NEON.orange }}>Etki Analizi</div>
          <p className="text-sm leading-relaxed" style={{ color: 'rgba(226,232,240,0.85)' }}>{result.impact}</p>
        </div>
      )}
      {result.recommendations.length > 0 && (
        <div className="p-3 rounded-[8px]" style={{ background: 'rgba(34,197,94,0.05)', border: '1px solid rgba(34,197,94,0.12)' }}>
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

// ── Compare Windows paneli ────────────────────────────────────────────────────

function ComparePanel() {
  const now = new Date()
  const fmt = (d: Date) => d.toISOString().slice(0, 16)
  const h = (n: number) => { const d = new Date(now); d.setHours(d.getHours() - n); return fmt(d) }

  const [sinceA, setSinceA] = useState(h(2))
  const [untilA, setUntilA] = useState(h(1))
  const [sinceB, setSinceB] = useState(h(1))
  const [untilB, setUntilB] = useState(fmt(now))
  const [labelA, setLabelA] = useState('Sorun Öncesi')
  const [labelB, setLabelB] = useState('Sorun Sonrası')
  const [serverIdA, setServerIdA] = useState('')
  const [serverIdB, setServerIdB] = useState('')
  const [context, setContext] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<CompareResult | null>(null)
  const [error, setError] = useState('')

  const [searchA, setSearchA] = useState('')
  const [searchB, setSearchB] = useState('')

  const { data: serversData } = useQuery({
    queryKey: ['servers-list-compare'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/servers/?limit=300`)
      return r.json()
    },
  })
  // Sadece online sunucular
  const allServers: { id: number; name: string; status: string }[] =
    serversData?.servers ?? serversData ?? []
  const onlineServers = allServers.filter(s => s.status !== 'OFFLINE')

  const run = async () => {
    setLoading(true); setError(''); setResult(null)
    try {
      const res = await fetch(`${API_BASE_URL}/rca/compare-window`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          server_id_a: serverIdA ? parseInt(serverIdA) : null,
          since_a: new Date(sinceA).toISOString(),
          until_a: new Date(untilA).toISOString(),
          server_id_b: serverIdB ? parseInt(serverIdB) : null,
          since_b: new Date(sinceB).toISOString(),
          until_b: new Date(untilB).toISOString(),
          label_a: labelA, label_b: labelB,
          context: context || undefined,
        }),
      })
      if (!res.ok) {
        const e = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        setError(e.detail || `HTTP ${res.status}`); return
      }
      setResult(await res.json())
    } catch (e: any) {
      setError(e.message ?? 'Bağlantı hatası')
    } finally { setLoading(false) }
  }

  const filteredServersA = onlineServers.filter(s =>
    s.name.toLowerCase().includes(searchA.toLowerCase())
  )
  const filteredServersB = onlineServers.filter(s =>
    s.name.toLowerCase().includes(searchB.toLowerCase())
  )

  const inputStyle = {
    background: 'rgba(255,255,255,0.04)',
    border: '1px solid rgba(255,255,255,0.08)',
    color: 'rgba(226,232,240,0.9)',
  }
  const inputCls = "w-full text-sm px-3 py-2 rounded-[6px] outline-none focus:border-cyan-500/40"

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Sunucu A */}
        <div className="cyber-card p-4 space-y-3">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full" style={{ background: NEON.cyan }} />
            <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: NEON.cyan }}>Sunucu A</span>
          </div>
          <input value={labelA} onChange={e => setLabelA(e.target.value)}
            className={inputCls} style={inputStyle}
            placeholder="Etiket (ör: Sorun öncesi)" />

          {/* Arama kutusu + select */}
          <div className="space-y-1">
            <input
              value={searchA}
              onChange={e => setSearchA(e.target.value)}
              className={inputCls + " text-xs"}
              style={{ ...inputStyle, fontSize: 12 }}
              placeholder="🔍  Sunucu ara..." />
            <select
              value={serverIdA}
              onChange={e => { setServerIdA(e.target.value); setSearchA('') }}
              className="w-full text-sm px-3 py-2 rounded-[6px] outline-none"
              style={{ ...inputStyle, colorScheme: 'dark' }}
            >
              <option value="">— Sunucu seç —</option>
              {filteredServersA.map(s => (
                <option key={s.id} value={String(s.id)}>{s.name}</option>
              ))}
            </select>
            {serverIdA && (
              <div className="text-[11px] px-1" style={{ color: NEON.cyan }}>
                ✓ {onlineServers.find(s => String(s.id) === serverIdA)?.name}
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="text-[10px] mb-1" style={{ color: 'rgba(148,163,184,0.5)' }}>Başlangıç</div>
              <input type="datetime-local" value={sinceA} onChange={e => setSinceA(e.target.value)}
                className="w-full text-xs px-2 py-1.5 rounded-[6px] outline-none"
                style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: 'rgba(226,232,240,0.8)', colorScheme: 'dark' }} />
            </div>
            <div>
              <div className="text-[10px] mb-1" style={{ color: 'rgba(148,163,184,0.5)' }}>Bitiş</div>
              <input type="datetime-local" value={untilA} onChange={e => setUntilA(e.target.value)}
                className="w-full text-xs px-2 py-1.5 rounded-[6px] outline-none"
                style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: 'rgba(226,232,240,0.8)', colorScheme: 'dark' }} />
            </div>
          </div>
        </div>

        {/* Sunucu B */}
        <div className="cyber-card p-4 space-y-3">
          <div className="flex items-center gap-2">
            <div className="w-2 h-2 rounded-full" style={{ background: NEON.orange }} />
            <span className="text-xs font-semibold uppercase tracking-wide" style={{ color: NEON.orange }}>Sunucu B</span>
          </div>
          <input value={labelB} onChange={e => setLabelB(e.target.value)}
            className={inputCls} style={inputStyle}
            placeholder="Etiket (ör: Sorun sonrası)" />

          {/* Arama kutusu + select */}
          <div className="space-y-1">
            <input
              value={searchB}
              onChange={e => setSearchB(e.target.value)}
              className={inputCls + " text-xs"}
              style={{ ...inputStyle, fontSize: 12 }}
              placeholder="🔍  Sunucu ara..." />
            <select
              value={serverIdB}
              onChange={e => { setServerIdB(e.target.value); setSearchB('') }}
              className="w-full text-sm px-3 py-2 rounded-[6px] outline-none"
              style={{ ...inputStyle, colorScheme: 'dark' }}
            >
              <option value="">— Sunucu seç —</option>
              {filteredServersB.map(s => (
                <option key={s.id} value={String(s.id)}>{s.name}</option>
              ))}
            </select>
            {serverIdB && (
              <div className="text-[11px] px-1" style={{ color: NEON.orange }}>
                ✓ {onlineServers.find(s => String(s.id) === serverIdB)?.name}
              </div>
            )}
          </div>

          <div className="grid grid-cols-2 gap-2">
            <div>
              <div className="text-[10px] mb-1" style={{ color: 'rgba(148,163,184,0.5)' }}>Başlangıç</div>
              <input type="datetime-local" value={sinceB} onChange={e => setSinceB(e.target.value)}
                className="w-full text-xs px-2 py-1.5 rounded-[6px] outline-none"
                style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: 'rgba(226,232,240,0.8)', colorScheme: 'dark' }} />
            </div>
            <div>
              <div className="text-[10px] mb-1" style={{ color: 'rgba(148,163,184,0.5)' }}>Bitiş</div>
              <input type="datetime-local" value={untilB} onChange={e => setUntilB(e.target.value)}
                className="w-full text-xs px-2 py-1.5 rounded-[6px] outline-none"
                style={{ background: 'rgba(255,255,255,0.04)', border: '1px solid rgba(255,255,255,0.08)', color: 'rgba(226,232,240,0.8)', colorScheme: 'dark' }} />
            </div>
          </div>
        </div>
      </div>

      {/* Opsiyonel bağlam */}
      <div className="cyber-card p-4">
        <div className="text-[11px] font-semibold uppercase tracking-wide mb-2" style={{ color: 'rgba(148,163,184,0.55)' }}>
          Ek Bağlam (opsiyonel — AWR özeti veya incident notu)
        </div>
        <textarea value={context} onChange={e => setContext(e.target.value)} rows={3}
          className="w-full text-sm px-3 py-2 rounded-[6px] outline-none resize-none"
          style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', color: 'rgba(226,232,240,0.8)' }}
          placeholder="Örn: CPU yükselmesi 14:30'da başladı. Deployment 14:25'te yapıldı..." />
      </div>

      <div className="flex justify-end">
        <PrimaryButton accent={NEON.cyan} onClick={run} disabled={loading}>
          {loading
            ? <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 border border-t-transparent rounded-full animate-spin" style={{ borderColor: `${NEON.cyan} transparent` }} />
                Karşılaştırılıyor...
              </span>
            : 'Karşılaştır ve Analiz Et'}
        </PrimaryButton>
      </div>

      {error && (
        <div className="p-3 rounded-[8px] text-sm" style={{ background: 'rgba(239,68,68,0.07)', color: NEON.red, border: '1px solid rgba(239,68,68,0.18)' }}>
          {error}
        </div>
      )}

      {result && <CompareResultCard result={result} />}
    </div>
  )
}

function CompareResultCard({ result }: { result: CompareResult }) {
  const { window_a, window_b, delta, llm_analysis } = result
  return (
    <div className="space-y-4">
      {/* Delta özet */}
      <div className="cyber-card p-4">
        <div className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: NEON.cyan }}>Delta Özeti</div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
          {[
            { label: 'Event Değişimi', value: delta.total_events_change, pct: delta.total_events_pct, invert: false },
            { label: 'Hata Değişimi', value: delta.error_events_change, pct: delta.error_events_pct, invert: false },
            { label: 'Pencere A Toplam', value: window_a.total_events, pct: null, invert: false },
            { label: 'Pencere B Toplam', value: window_b.total_events, pct: null, invert: false },
          ].map(item => (
            <div key={item.label}>
              <div className="text-[10px] mb-0.5" style={{ color: 'rgba(148,163,184,0.5)' }}>{item.label}</div>
              <DeltaBadge value={item.value} pct={item.pct} invert={item.invert} />
            </div>
          ))}
        </div>
        {(delta.new_event_types.length > 0 || delta.disappeared_event_types.length > 0) && (
          <div className="mt-3 pt-3 border-t flex flex-wrap gap-4 text-xs" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
            {delta.new_event_types.length > 0 && (
              <span>Yeni tipler: <span style={{ color: NEON.red }}>{delta.new_event_types.join(', ')}</span></span>
            )}
            {delta.disappeared_event_types.length > 0 && (
              <span>Kaybolan tipler: <span style={{ color: NEON.green }}>{delta.disappeared_event_types.join(', ')}</span></span>
            )}
          </div>
        )}
      </div>

      {/* LLM analizi */}
      <div className="cyber-card p-4 space-y-3">
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: NEON.cyan }}>AI Karşılaştırma Analizi</div>
          <div className="flex items-center gap-2">
            <ConfidenceBadge confidence={llm_analysis.confidence} />
            <span className="text-[10px]" style={{ color: 'rgba(148,163,184,0.4)' }}>{result.model}</span>
          </div>
        </div>
        {llm_analysis.summary && (
          <p className="text-sm leading-relaxed" style={{ color: 'rgba(226,232,240,0.88)' }}>{llm_analysis.summary}</p>
        )}
        <LLMSection title="Temel Farklar" items={llm_analysis.key_differences} accent={NEON.cyan} />
        <LLMSection title="Regresyon Göstergeleri" items={llm_analysis.regression_indicators} accent={NEON.red} />
        <LLMSection title="Öneriler" items={llm_analysis.recommendations} accent={NEON.green} />
      </div>

      {/* Pencere detayları */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {[
          { w: window_a, accent: NEON.cyan, label: 'Pencere A' },
          { w: window_b, accent: NEON.orange, label: 'Pencere B' },
        ].map(({ w, accent, label }) => (
          <div key={label} className="cyber-card p-4">
            <div className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: accent }}>{label}</div>
            <div className="space-y-1.5 text-xs" style={{ color: 'rgba(148,163,184,0.7)' }}>
              <div><span className="opacity-60">Aralık:</span> {w.since.slice(0, 16)} → {w.until.slice(0, 16)}</div>
              <div><span className="opacity-60">Toplam:</span> <span style={{ color: accent }}>{w.total_events}</span> event</div>
              <div><span className="opacity-60">Hata oranı:</span> <span style={{ color: w.error_rate > 0.2 ? NEON.red : 'inherit' }}>{(w.error_rate * 100).toFixed(1)}%</span></div>
              {w.top_titles.slice(0, 3).map(t => (
                <div key={t.title} className="truncate">▸ {t.title} <span className="opacity-50">({t.count}x)</span></div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

// ── AWR Analiz paneli ─────────────────────────────────────────────────────────

function AWRPanel() {
  const fileRef = useRef<HTMLInputElement>(null)
  const baselineRef = useRef<HTMLInputElement>(null)
  const [content, setContent] = useState('')
  const [filename, setFilename] = useState('')
  const [baselineContent, setBaselineContent] = useState('')
  const [baselineFilename, setBaselineFilename] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AWRAnalyzeResult | null>(null)
  const [error, setError] = useState('')

  const loadFile = (file: File, setC: (s: string) => void, setN: (s: string) => void) => {
    setN(file.name)
    const reader = new FileReader()
    reader.onload = e => setC((e.target?.result as string) ?? '')
    reader.readAsText(file, 'utf-8')
  }

  const run = async () => {
    if (!content) { setError('AWR dosyası seçin veya yapıştırın'); return }
    setLoading(true); setError(''); setResult(null)
    try {
      const res = await fetch(`${API_BASE_URL}/rca/awr-analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          content, filename: filename || 'report.txt',
          compare_with_awr: baselineContent || undefined,
          compare_filename: baselineFilename || 'baseline.txt',
        }),
      })
      if (!res.ok) {
        const e = await res.json().catch(() => ({ detail: `HTTP ${res.status}` }))
        setError(e.detail || `HTTP ${res.status}`); return
      }
      setResult(await res.json())
    } catch (e: any) {
      setError(e.message ?? 'Bağlantı hatası')
    } finally { setLoading(false) }
  }

  return (
    <div className="space-y-5">
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
        {/* Ana AWR */}
        <div className="cyber-card p-4 space-y-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: NEON.cyan }}>AWR Raporu</div>
          <button onClick={() => fileRef.current?.click()}
            className="w-full py-8 rounded-[8px] border-2 border-dashed flex flex-col items-center gap-2 transition-colors cursor-pointer hover:border-cyan-500/40"
            style={{ borderColor: content ? 'rgba(6,182,212,0.3)' : 'rgba(255,255,255,0.08)', background: content ? 'rgba(6,182,212,0.04)' : 'transparent' }}>
            {content
              ? <><span className="text-lg">✓</span><span className="text-xs" style={{ color: NEON.cyan }}>{filename}</span><span className="text-[10px] opacity-40">{content.length.toLocaleString()} karakter yüklendi</span></>
              : <><span className="text-2xl opacity-30">📄</span><span className="text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>HTML veya Text AWR yükle</span></>
            }
          </button>
          <input ref={fileRef} type="file" accept=".html,.htm,.txt,.log" className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) loadFile(f, setContent, setFilename) }} />
          <div className="text-[10px]" style={{ color: 'rgba(148,163,184,0.4)' }}>— veya içeriği yapıştır —</div>
          <textarea value={content} onChange={e => { setContent(e.target.value); setFilename(prev => prev || 'paste.txt') }} rows={4}
            className="w-full text-xs px-3 py-2 rounded-[6px] outline-none resize-none font-mono"
            style={{ background: 'rgba(0,0,0,0.2)', border: '1px solid rgba(255,255,255,0.07)', color: 'rgba(226,232,240,0.7)' }}
            placeholder="AWR içeriğini buraya yapıştır..." />
        </div>

        {/* Baseline AWR (opsiyonel) */}
        <div className="cyber-card p-4 space-y-3">
          <div className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: 'rgba(148,163,184,0.5)' }}>
            Baseline AWR <span className="font-normal normal-case opacity-60">(opsiyonel karşılaştırma)</span>
          </div>
          <button onClick={() => baselineRef.current?.click()}
            className="w-full py-8 rounded-[8px] border-2 border-dashed flex flex-col items-center gap-2 transition-colors cursor-pointer"
            style={{ borderColor: baselineContent ? 'rgba(251,191,36,0.3)' : 'rgba(255,255,255,0.06)', background: baselineContent ? 'rgba(251,191,36,0.03)' : 'transparent' }}>
            {baselineContent
              ? <><span className="text-lg">✓</span><span className="text-xs" style={{ color: NEON.orange }}>{baselineFilename}</span></>
              : <><span className="text-2xl opacity-20">📄</span><span className="text-xs" style={{ color: 'rgba(148,163,184,0.35)' }}>Baseline AWR (sağlıklı dönem)</span></>
            }
          </button>
          <input ref={baselineRef} type="file" accept=".html,.htm,.txt,.log" className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) loadFile(f, setBaselineContent, setBaselineFilename) }} />
        </div>
      </div>

      <div className="flex justify-end">
        <PrimaryButton accent={NEON.cyan} onClick={run} disabled={loading || !content}>
          {loading
            ? <span className="flex items-center gap-1.5">
                <span className="w-3 h-3 border border-t-transparent rounded-full animate-spin" style={{ borderColor: `${NEON.cyan} transparent` }} />
                AWR parse + AI analiz...
              </span>
            : 'Parse Et ve Analiz Yap'}
        </PrimaryButton>
      </div>

      {error && (
        <div className="p-3 rounded-[8px] text-sm" style={{ background: 'rgba(239,68,68,0.07)', color: NEON.red, border: '1px solid rgba(239,68,68,0.18)' }}>
          {error}
        </div>
      )}

      {result && <AWRResultCard result={result} />}
    </div>
  )
}

function AWRResultCard({ result }: { result: AWRAnalyzeResult }) {
  const r = result.report
  const llm = result.llm_analysis
  return (
    <div className="space-y-4">
      {/* DB bilgisi */}
      <div className="cyber-card p-4">
        <div className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: NEON.cyan }}>Rapor Bilgisi</div>
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 text-xs" style={{ color: 'rgba(148,163,184,0.7)' }}>
          {[
            { label: 'DB', value: `${r.db_name} (${r.db_id})` },
            { label: 'Instance', value: r.instance_name || '—' },
            { label: 'Host', value: r.host_name || '—' },
            { label: 'Versiyon', value: r.db_version || '—' },
            { label: 'Başlangıç', value: r.snap_begin || '—' },
            { label: 'Bitiş', value: r.snap_end || '—' },
            { label: 'Süre', value: `${r.elapsed_minutes.toFixed(1)} dk` },
            { label: 'DB Time', value: `${r.db_time_minutes.toFixed(1)} dk` },
          ].map(item => (
            <div key={item.label}>
              <div className="opacity-50 text-[10px]">{item.label}</div>
              <div style={{ color: 'rgba(226,232,240,0.85)' }}>{item.value}</div>
            </div>
          ))}
        </div>
      </div>

      {/* Performans metrikleri */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {[
          { label: 'Buffer Cache Hit', value: `${r.buffer_cache_hit_pct.toFixed(1)}%`, accent: r.buffer_cache_hit_pct < 90 ? NEON.red : NEON.green },
          { label: 'Library Cache Hit', value: `${r.library_cache_hit_pct.toFixed(1)}%`, accent: r.library_cache_hit_pct < 95 ? NEON.orange : NEON.green },
          { label: 'DB CPU/sn', value: `${r.load_profile.db_cpu_per_sec.toFixed(2)}s`, accent: NEON.cyan },
          { label: 'Phys Reads/sn', value: r.load_profile.physical_reads_per_sec.toFixed(0), accent: NEON.blue },
        ].map(k => (
          <div key={k.label} className="cyber-card p-3">
            <div className="text-[10px] opacity-50 mb-0.5" style={{ color: 'rgba(148,163,184,0.7)' }}>{k.label}</div>
            <div className="text-lg font-bold" style={{ color: k.accent }}>{k.value}</div>
          </div>
        ))}
      </div>

      {/* Top wait events */}
      {r.top_wait_events.length > 0 && (
        <div className="cyber-card p-4">
          <div className="text-[11px] font-semibold uppercase tracking-wide mb-3" style={{ color: NEON.orange }}>Top Wait Events</div>
          <div className="space-y-2">
            {r.top_wait_events.slice(0, 8).map((e, i) => (
              <div key={i} className="flex items-center gap-3 text-xs">
                <div className="flex-1 min-w-0">
                  <span style={{ color: 'rgba(226,232,240,0.85)' }}>{e.event}</span>
                  <span className="ml-2 opacity-40">[{e.wait_class}]</span>
                </div>
                <span className="font-mono" style={{ color: e.pct_db_time > 20 ? NEON.red : NEON.orange }}>{e.pct_db_time.toFixed(1)}%</span>
                <span className="font-mono opacity-50">{e.time_s.toFixed(1)}s</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* LLM analizi */}
      {(llm.summary || llm.bottlenecks?.length || llm.recommendations?.length) && (
        <div className="cyber-card p-4 space-y-3">
          <div className="flex items-center justify-between flex-wrap gap-2">
            <div className="text-[11px] font-semibold uppercase tracking-wide" style={{ color: NEON.cyan }}>AI Performans Analizi</div>
            <div className="flex items-center gap-2">
              {llm.severity && (
                <span className="text-xs px-2 py-0.5 rounded-full"
                  style={{
                    background: llm.severity === 'critical' ? 'rgba(239,68,68,0.1)' : llm.severity === 'high' ? 'rgba(251,191,36,0.1)' : 'rgba(34,197,94,0.1)',
                    color: llm.severity === 'critical' ? NEON.red : llm.severity === 'high' ? NEON.orange : NEON.green,
                    border: `1px solid ${llm.severity === 'critical' ? 'rgba(239,68,68,0.2)' : llm.severity === 'high' ? 'rgba(251,191,36,0.2)' : 'rgba(34,197,94,0.2)'}`,
                  }}>
                  {llm.severity?.toUpperCase()}
                </span>
              )}
              <ConfidenceBadge confidence={llm.confidence} />
              <span className="text-[10px]" style={{ color: 'rgba(148,163,184,0.4)' }}>{result.model}</span>
            </div>
          </div>
          {llm.summary && <p className="text-sm leading-relaxed" style={{ color: 'rgba(226,232,240,0.88)' }}>{llm.summary}</p>}
          <LLMSection title="Darboğazlar" items={llm.bottlenecks} accent={NEON.red} />
          <LLMSection title="Problematik SQL" items={llm.top_sql_findings} accent={NEON.orange} />
          <LLMSection title="Wait Event Analizi" items={llm.wait_event_analysis} accent={NEON.cyan} />
          <LLMSection title="Öneriler" items={llm.recommendations} accent={NEON.green} />
          {llm.baseline_comparison && (
            <div className="p-3 rounded-[8px] text-sm" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.07)', color: 'rgba(226,232,240,0.7)' }}>
              <div className="text-[10px] font-semibold uppercase tracking-wide mb-1" style={{ color: 'rgba(148,163,184,0.5)' }}>Baseline Karşılaştırması</div>
              {llm.baseline_comparison}
            </div>
          )}
        </div>
      )}

      {r.parse_errors.length > 0 && (
        <div className="p-3 rounded-[8px] text-xs space-y-1" style={{ background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.15)', color: NEON.orange }}>
          <div className="font-semibold">Parse uyarıları:</div>
          {r.parse_errors.map((e, i) => <div key={i}>! {e}</div>)}
        </div>
      )}
    </div>
  )
}

// ── Ana sayfa ─────────────────────────────────────────────────────────────────

type Tab = 'log' | 'compare' | 'awr'

const RootCauseAnalysis: React.FC<PlatformAiopsProps> = ({ platform = 'linux' }) => {
  const [activeTab, setActiveTab] = useState<Tab>('log')
  const [search, setSearch] = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('log_entry')
  const [serverFilter, setServerFilter] = useState('')
  const [hideOffline, setHideOffline] = useState(true)
  const [analyses, setAnalyses] = useState<AnalysisState>({})
  const [expanded, setExpanded] = useState<Set<number>>(new Set())

  // Online sunucu listesi (dropdown için)
  const { data: serversListData } = useQuery({
    queryKey: ['rca-servers-online'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/servers/?limit=300`)
      if (!r.ok) return { servers: [] }
      return r.json()
    },
    staleTime: 60_000,
  })
  const allServers: { id: number; name: string; status: string }[] =
    serversListData?.servers ?? serversListData ?? []
  const onlineServers = allServers.filter(s => s.status !== 'OFFLINE')

  const { data, isLoading } = useQuery({
    queryKey: ['rca-events', platform, severityFilter, typeFilter, search, serverFilter, hideOffline],
    queryFn: async () => {
      const params = appendPlatform(new URLSearchParams({
        limit: '50', resolved: 'false',
        ...(severityFilter && { severity: severityFilter }),
        ...(typeFilter && { event_type: typeFilter }),
        ...(search && { search }),
        ...(serverFilter && { server_id: serverFilter }),
        ...(hideOffline && { online_only: 'true' }),
      }), platform)
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

  const tabs: { id: Tab; label: string }[] = [
    { id: 'log', label: 'Log Kök Neden' },
    { id: 'compare', label: 'Karşılaştırmalı Analiz' },
    { id: 'awr', label: 'AWR Analiz' },
  ]

  return (
    <div className="space-y-6">
      <PageHeader
        title="Kök Neden Analizi"
        subtitle="Log analizi, zaman penceresi karşılaştırması ve AWR performans analizi"
        actions={
          activeTab === 'log' ? (
            <GhostButton accent={NEON.cyan} onClick={analyzeAll} disabled={events.length === 0}>
              Toplu Analiz (ilk 5)
            </GhostButton>
          ) : undefined
        }
      />

      {/* Tab bar */}
      <div className="flex gap-1 p-1 rounded-[10px]" style={{ background: 'rgba(255,255,255,0.03)', border: '1px solid rgba(255,255,255,0.06)' }}>
        {tabs.map(tab => (
          <button key={tab.id} onClick={() => setActiveTab(tab.id)}
            className="flex-1 py-2 px-3 rounded-[8px] text-sm font-medium transition-all"
            style={activeTab === tab.id
              ? { background: 'rgba(6,182,212,0.12)', color: NEON.cyan, border: '1px solid rgba(6,182,212,0.2)' }
              : { color: 'rgba(148,163,184,0.55)', border: '1px solid transparent' }}>
            {tab.label}
          </button>
        ))}
      </div>

      {/* Log RCA tab */}
      {activeTab === 'log' && (
        <>
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

          <Section>
            <div className="flex flex-wrap gap-3 p-4 items-center">
              <SearchInput value={search} onChange={setSearch} placeholder="Başlık veya sunucu adı ara..." width="w-56" />
              {/* Sunucu dropdown */}
              <Select value={serverFilter} onChange={setServerFilter}>
                <option value="">Tüm sunucular</option>
                {onlineServers.map(s => (
                  <option key={s.id} value={String(s.id)}>{s.name}</option>
                ))}
              </Select>
              <Select value={typeFilter} onChange={setTypeFilter}>
                <option value="">Tüm tipler</option>
                <option value="log_entry">Log Entry</option>
                <option value="metric_anomaly">Metrik Anomali</option>
              </Select>
              <Select value={severityFilter} onChange={setSeverityFilter}>
                <option value="">Tüm önemler</option>
                <option value="critical">Kritik</option>
                <option value="warning">Uyarı</option>
                <option value="info">Bilgi</option>
              </Select>
              {/* Kapalı sunucu toggle */}
              <label className="flex items-center gap-2 cursor-pointer select-none ml-auto"
                style={{ color: 'rgba(148,163,184,0.75)', fontSize: 13 }}>
                <div
                  onClick={() => setHideOffline(h => !h)}
                  className="relative w-9 h-5 rounded-full transition-colors cursor-pointer flex-shrink-0"
                  style={{ background: hideOffline ? 'rgba(6,182,212,0.5)' : 'rgba(255,255,255,0.1)', border: '1px solid rgba(255,255,255,0.1)' }}
                >
                  <div className="absolute top-0.5 transition-all w-4 h-4 rounded-full bg-white shadow"
                    style={{ left: hideOffline ? '18px' : '2px' }} />
                </div>
                <span>Kapalı sunucuları gizle</span>
              </label>
            </div>
          </Section>

          {isLoading ? (
            <div className="py-16 flex justify-center">
              <div className="animate-spin rounded-full h-8 w-8 border-2 border-t-cyan-400 border-white/[0.06]" />
            </div>
          ) : events.length === 0 ? (
            <EmptyState text="Seçili filtrelere göre çözümlenmemiş event bulunamadı." />
          ) : (
            <div className="space-y-2">
              {events.map(event => {
                const state = analyses[event.id]
                const isExpanded = expanded.has(event.id)
                return (
                  <div key={event.id} className="cyber-card overflow-hidden transition-all">
                    <div className="flex items-start gap-3 p-4">
                      <div className="mt-0.5 flex-shrink-0">
                        <div className="w-2 h-2 rounded-full mt-1.5"
                          style={{ background: event.severity === 'critical' ? NEON.red : event.severity === 'warning' ? NEON.orange : NEON.cyan, boxShadow: `0 0 6px ${event.severity === 'critical' ? NEON.red : event.severity === 'warning' ? NEON.orange : NEON.cyan}` }} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex flex-wrap items-center gap-2 mb-1">
                          <SeverityBadge severity={event.severity} />
                          <span className="text-[11px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(255,255,255,0.05)', color: 'rgba(148,163,184,0.6)' }}>{event.event_type}</span>
                          {event.server_name && <span className="text-[11px]" style={{ color: NEON.cyan }}>{event.server_name}</span>}
                        </div>
                        <p className="text-sm font-medium leading-snug" style={{ color: 'rgba(226,232,240,0.9)' }}>{event.title}</p>
                        {event.description && <p className="text-xs mt-0.5 line-clamp-2" style={{ color: 'rgba(148,163,184,0.55)' }}>{event.description}</p>}
                        <p className="text-[11px] mt-1" style={{ color: 'rgba(148,163,184,0.4)' }}>{event.created_at ? new Date(event.created_at).toLocaleString('tr-TR') : '—'}</p>
                      </div>
                      <div className="flex items-center gap-2 flex-shrink-0">
                        {state?.result && (
                          <button onClick={() => setExpanded(prev => { const n = new Set(prev); n.has(event.id) ? n.delete(event.id) : n.add(event.id); return n })}
                            className="text-[11px] px-2 py-1 rounded transition-colors"
                            style={{ color: NEON.cyan, border: `1px solid rgba(6,182,212,0.2)`, background: 'rgba(6,182,212,0.05)' }}>
                            {isExpanded ? 'Gizle' : 'Sonucu Gör'}
                          </button>
                        )}
                        <PrimaryButton accent={state?.result ? NEON.slate : NEON.cyan} onClick={() => analyze(event)} disabled={state?.loading}>
                          {state?.loading
                            ? <span className="flex items-center gap-1.5"><span className="w-3 h-3 border border-t-transparent rounded-full animate-spin" style={{ borderColor: `${NEON.cyan} transparent` }} />Analiz...</span>
                            : state?.result ? 'Yenile' : 'Analiz Et'}
                        </PrimaryButton>
                      </div>
                    </div>
                    {isExpanded && state?.error && (
                      <div className="px-4 pb-4"><div className="text-sm p-3 rounded-[8px]" style={{ background: 'rgba(239,68,68,0.07)', color: NEON.red, border: '1px solid rgba(239,68,68,0.18)' }}>{state.error}</div></div>
                    )}
                    {isExpanded && state?.result && (
                      <div className="px-4 pb-4 border-t" style={{ borderColor: 'rgba(255,255,255,0.04)' }}>
                        <AnalysisCard result={state.result} />
                      </div>
                    )}
                    {state?.loading && (
                      <div className="px-4 pb-3 flex items-center gap-2 text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>
                        <div className="w-3 h-3 border border-t-transparent rounded-full animate-spin" style={{ borderColor: `${NEON.cyan} transparent ${NEON.cyan} ${NEON.cyan}` }} />
                        Log satırları okunuyor, AI analiz yapıyor...
                      </div>
                    )}
                  </div>
                )
              })}
            </div>
          )}

          <div className="text-center pt-2">
            <Link to="/events" className="text-xs" style={{ color: 'rgba(148,163,184,0.4)' }}>
              Tüm eventleri görmek için Events sayfasına git
            </Link>
          </div>
        </>
      )}

      {/* Karşılaştırma tab */}
      {activeTab === 'compare' && <ComparePanel />}

      {/* AWR tab */}
      {activeTab === 'awr' && <AWRPanel />}
    </div>
  )
}

export default RootCauseAnalysis
