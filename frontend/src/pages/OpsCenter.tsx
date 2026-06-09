/**
 * Ops Komuta Merkezi — Sunucu bazlı, verimli alarm yönetimi.
 *
 * Yapı:
 *   Sağlık Skoru (0-100)  +  Özet Banner (kritik/uyarı/kontrol)
 *   ⚡ Fırtınalar (ortak metrik)
 *   🔴 Kritik Sunucular  (kart başına 1 sunucu, tüm metrikleri)
 *   🟡 Uyarı Sunucuları
 *
 * Her kart:
 *   Sunucu adı + tier + IP  |  Max severity badge
 *   Metrik listesi (en kötüden iyiye, inline değer)
 *   Toplu seçim checkbox
 *   RCA / Onayla / Bastır / Ertele (30dk/2sa/8sa)
 */
import { useState, useCallback, useEffect, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { API_BASE_URL } from '../config/api'

// ── Types ─────────────────────────────────────────────────────────────────────
interface ServerInfo { id: number | null; name: string; hostname: string; ip: string; tier: string }

interface MetricItem {
  event_id: number; metric: string; severity: string
  value: number | null; occurrence_count: number
  last_seen: string | null; event_type: string
}

interface ServerCard {
  server: ServerInfo
  max_severity: string
  event_count: number
  event_ids: number[]
  metrics: MetricItem[]
  last_seen: string | null
  suggested_actions: string[]
}

interface StormCard {
  incident_id: number; metric: string; severity: string
  server_count: number; event_count: number; event_ids: number[]
  affected_servers: { id: number; name: string; ip: string; tier: string }[]
  last_seen: string | null
}

interface HealthScore {
  score: number; grade: string; label: string; color: string
  severity_breakdown: Record<string, number>
  event_count: number; server_count: number
}

interface CommandCenterData {
  health: HealthScore
  storms: StormCard[]
  critical_servers: ServerCard[]
  warning_servers: ServerCard[]
  critical_count: number; warning_count: number
  storm_count: number; green_count: number
  generated_at: string
}

interface RCAResult {
  root_cause?: string; likely_cause?: string; impact?: string
  actions?: string[]; affected_summary?: string
  severity_assessment?: string; confidence?: string
}
interface RCAResponse {
  server: string; metric: string; event_count: number; is_storm?: boolean
  analysis: RCAResult; model: string; analyzed_at: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const TIER_STYLE: Record<string, string> = {
  production:  'bg-red-500/20 text-red-300 border-red-500/30',
  staging:     'bg-amber-500/20 text-amber-300 border-amber-500/30',
  development: 'bg-green-500/20 text-green-300 border-green-500/30',
  unknown:     'bg-gray-500/20 text-gray-400 border-gray-500/30',
}
const TIER_SHORT: Record<string, string> = { production: 'PRD', staging: 'STG', development: 'DEV', unknown: '?' }

const SEV_BG: Record<string, string> = {
  emergency: 'border-purple-500/50 bg-purple-500/8',
  critical:  'border-red-500/40 bg-red-500/5',
  warning:   'border-amber-500/30 bg-amber-500/4',
}
const SEV_TEXT: Record<string, string> = {
  emergency: 'text-purple-300', critical: 'text-red-300', warning: 'text-amber-300', info: 'text-blue-300'
}
const SEV_DOT: Record<string, string> = {
  emergency: 'bg-purple-400 animate-ping', critical: 'bg-red-400 animate-pulse',
  warning: 'bg-amber-400', info: 'bg-blue-400'
}

function relTime(iso: string | null): string {
  if (!iso) return ''
  const d = Date.now() - new Date(iso).getTime()
  const m = Math.floor(d / 60000)
  if (m < 1) return 'şimdi'
  if (m < 60) return `${m}dk`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}s`
  return `${Math.floor(h / 24)}g`
}

// ── Sağlık Skoru ─────────────────────────────────────────────────────────────
function HealthBadge({ health }: { health: HealthScore }) {
  const ring = health.score >= 90 ? 'stroke-green-400' :
               health.score >= 75 ? 'stroke-blue-400' :
               health.score >= 55 ? 'stroke-yellow-400' :
               health.score >= 35 ? 'stroke-orange-400' : 'stroke-red-400'
  const textCol = ring.replace('stroke-', 'text-')
  const r = 20, circ = 2 * Math.PI * r
  const dash = circ * (health.score / 100)

  return (
    <div className="flex items-center gap-3 bg-gray-800/60 border border-gray-700/60 rounded-xl px-4 py-3">
      <div className="relative w-14 h-14 shrink-0">
        <svg className="w-14 h-14 -rotate-90" viewBox="0 0 48 48">
          <circle cx="24" cy="24" r={r} fill="none" strokeWidth="4" className="stroke-gray-700" />
          <circle cx="24" cy="24" r={r} fill="none" strokeWidth="4"
            className={ring} strokeDasharray={`${dash} ${circ}`} strokeLinecap="round" />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className={`text-sm font-bold ${textCol}`}>{health.score}</span>
        </div>
      </div>
      <div>
        <div className={`text-base font-semibold ${textCol}`}>{health.label}</div>
        <div className="text-xs text-gray-500 mt-0.5">
          {health.event_count} açık alarm · {health.server_count} sunucu
        </div>
        <div className="flex gap-2 mt-1">
          {Object.entries(health.severity_breakdown).map(([s, c]) => (
            <span key={s} className={`text-[10px] ${SEV_TEXT[s] || 'text-gray-400'}`}>
              {c} {s}
            </span>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── Inline RCA ────────────────────────────────────────────────────────────────
function RCAPanel({ eventIds, metric, isStorm, onClose }: {
  eventIds: number[]; metric: string; isStorm?: boolean; onClose: () => void
}) {
  const [result, setResult] = useState<RCAResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(async () => {
    setLoading(true); setError(null)
    try {
      const r = await fetch(`${API_BASE_URL}/rca/quick-analyze`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_ids: eventIds, metric, is_storm: isStorm ?? false }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setResult(await r.json())
    } catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }, [eventIds, metric, isStorm])

  useEffect(() => { run() }, [])

  const conf = result?.analysis?.confidence
  const confCol = conf === 'high' ? 'text-green-400' : conf === 'medium' ? 'text-amber-400' : 'text-gray-400'

  return (
    <div className="mt-2 rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-cyan-400">
          {isStorm ? '🔍 Fırtına Analizi (tüm sunucular)' : '🔍 AI Kök Neden'}
        </span>
        <button onClick={onClose} className="text-xs text-gray-500 hover:text-gray-300">✕</button>
      </div>
      {loading && (
        <div className="flex items-center gap-2 py-2">
          <div className="w-4 h-4 rounded-full border-2 border-t-cyan-400 border-r-transparent animate-spin" />
          <span className="text-xs text-gray-400">AI analiz ediyor...</span>
        </div>
      )}
      {error && (
        <div className="text-xs text-red-400 bg-red-500/10 rounded p-2">
          ⚠ {error} <button onClick={run} className="ml-2 underline">Tekrar dene</button>
        </div>
      )}
      {result && (
        <div className="space-y-2 text-sm">
          {result.analysis.root_cause && (
            <div><p className="text-[10px] text-gray-500 uppercase">Kök Neden</p>
              <p className="text-gray-200 mt-0.5">{result.analysis.root_cause}</p></div>
          )}
          {result.analysis.likely_cause && (
            <div><p className="text-[10px] text-gray-500 uppercase">Olası Sebep</p>
              <p className="text-gray-300 mt-0.5">{result.analysis.likely_cause}</p></div>
          )}
          {result.analysis.affected_summary && (
            <div><p className="text-[10px] text-gray-500 uppercase">Etkilenen</p>
              <p className="text-gray-300 mt-0.5">{result.analysis.affected_summary}</p></div>
          )}
          {result.analysis.impact && (
            <div><p className="text-[10px] text-gray-500 uppercase">Etki</p>
              <p className="text-gray-300 mt-0.5">{result.analysis.impact}</p></div>
          )}
          {result.analysis.actions && result.analysis.actions.length > 0 && (
            <div>
              <p className="text-[10px] text-gray-500 uppercase">Aksiyonlar</p>
              <ul className="mt-1 space-y-1">
                {result.analysis.actions.map((a, i) => (
                  <li key={i} className="text-xs text-gray-300 flex gap-1.5">
                    <span className="text-cyan-500 shrink-0">→</span><span>{a}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex items-center gap-3 pt-1 border-t border-gray-700/40 text-xs text-gray-500">
            <span className={confCol}>Güven: {conf}</span>
            <span>{result.event_count} event</span>
            <button onClick={run} className="ml-auto hover:text-gray-300">↻</button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Sunucu Kartı ─────────────────────────────────────────────────────────────
function ServerCard({
  card, selected, onSelect, onDone
}: {
  card: ServerCard
  selected: boolean
  onSelect: (ids: number[], checked: boolean) => void
  onDone: () => void
}) {
  const [expanded, setExpanded] = useState(false)
  const [showRCA, setShowRCA] = useState(false)
  const [showSnooze, setShowSnooze] = useState(false)
  const [loading, setLoading] = useState<string | null>(null)
  const tier = card.server.tier

  async function doAction(action: 'acknowledge' | 'known' | 'suppress') {
    setLoading(action)
    try {
      if (action === 'acknowledge') {
        await Promise.all(card.event_ids.map(id =>
          fetch(`${API_BASE_URL}/events/${id}/acknowledge`, { method: 'POST' })
        ))
      } else if (action === 'known') {
        await Promise.all(card.event_ids.map(id =>
          fetch(`${API_BASE_URL}/events/${id}/known`, { method: 'POST' })
        ))
      } else {
        await Promise.all(card.event_ids.map(id =>
          fetch(`${API_BASE_URL}/baseline/suppressions/from-event/${id}`, { method: 'POST' })
        ))
      }
      onDone()
    } finally { setLoading(null) }
  }

  async function doSnooze(minutes: number) {
    setLoading('snooze')
    setShowSnooze(false)
    try {
      await fetch(`${API_BASE_URL}/ops/snooze`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_ids: card.event_ids, minutes }),
      })
      onDone()
    } finally { setLoading(null) }
  }

  const sev = card.max_severity
  const severityBg = SEV_BG[sev] || SEV_BG.warning

  return (
    <div className={`rounded-xl border transition-all ${severityBg} ${selected ? 'ring-1 ring-cyan-500/50' : ''}`}>
      {/* ── Kart başlığı ── */}
      <div className="flex items-start gap-2 p-3">
        {/* Checkbox */}
        <input
          type="checkbox"
          checked={selected}
          onChange={e => onSelect(card.event_ids, e.target.checked)}
          className="mt-1 shrink-0 accent-cyan-500 cursor-pointer"
        />

        {/* Severity dot */}
        <div className="mt-1.5 shrink-0">
          <span className={`inline-block w-2 h-2 rounded-full ${SEV_DOT[sev] || 'bg-gray-400'}`} />
        </div>

        {/* İçerik */}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-bold ${TIER_STYLE[tier]}`}>
              {TIER_SHORT[tier] || tier}
            </span>
            <span className="font-semibold text-gray-100">{card.server.name}</span>
            <span className="text-xs text-gray-500">{card.server.ip}</span>
            <span className={`text-xs px-1.5 py-0.5 rounded-full border ml-auto ${
              sev === 'critical' || sev === 'emergency'
                ? 'bg-red-500/20 text-red-300 border-red-500/40'
                : 'bg-amber-500/20 text-amber-300 border-amber-500/40'
            }`}>
              {sev.toUpperCase()}
            </span>
          </div>

          {/* Metrik özeti — ilk 3, tıklanınca genişler */}
          <div className="mt-2 space-y-1">
            {(expanded ? card.metrics : card.metrics.slice(0, 3)).map(m => (
              <div key={m.event_id} className="flex items-center gap-2 text-xs">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                  m.severity === 'critical' ? 'bg-red-400' :
                  m.severity === 'warning' ? 'bg-amber-400' : 'bg-blue-400'
                }`} />
                <span className="text-gray-300 truncate max-w-[200px]">{m.metric}</span>
                {m.value !== null && (
                  <span className="text-gray-500">%{Math.round(m.value)}</span>
                )}
                {m.occurrence_count > 1 && (
                  <span className="text-gray-600">{m.occurrence_count}×</span>
                )}
                <span className="text-gray-600 ml-auto">{relTime(m.last_seen)}</span>
              </div>
            ))}
            {card.metrics.length > 3 && (
              <button
                onClick={() => setExpanded(v => !v)}
                className="text-xs text-gray-500 hover:text-gray-300 mt-1"
              >
                {expanded ? '▲ gizle' : `▼ +${card.metrics.length - 3} daha`}
              </button>
            )}
          </div>

          {/* Önerilen komutlar */}
          {expanded && card.suggested_actions.length > 0 && (
            <div className="mt-2 space-y-1">
              {card.suggested_actions.map((a, i) => (
                <div key={i} className="text-xs text-gray-500 flex gap-1.5">
                  <span className="text-gray-600 shrink-0">$</span>
                  <code className="text-gray-400">{a}</code>
                </div>
              ))}
            </div>
          )}

          {/* Aksiyon butonları */}
          <div className="flex flex-wrap gap-1.5 mt-2 relative">
            <button
              onClick={() => setShowRCA(v => !v)}
              className="text-xs px-2.5 py-1 rounded-lg border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10 transition-colors"
            >
              🔍 RCA
            </button>
            <button
              onClick={() => doAction('acknowledge')}
              disabled={loading !== null}
              className="text-xs px-2.5 py-1 rounded-lg border border-blue-500/40 text-blue-300 hover:bg-blue-500/10 transition-colors disabled:opacity-50"
            >
              {loading === 'acknowledge' ? '...' : '✓ Onayla'}
            </button>
            <button
              onClick={() => doAction('known')}
              disabled={loading !== null}
              className="text-xs px-2.5 py-1 rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-700 transition-colors disabled:opacity-50"
            >
              {loading === 'known' ? '...' : '👁 Bilinen'}
            </button>
            <button
              onClick={() => doAction('suppress')}
              disabled={loading !== null}
              className="text-xs px-2.5 py-1 rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-700 transition-colors disabled:opacity-50"
            >
              {loading === 'suppress' ? '...' : '🔇 Bastır'}
            </button>

            {/* Snooze dropdown */}
            <div className="relative">
              <button
                onClick={() => setShowSnooze(v => !v)}
                disabled={loading !== null}
                className="text-xs px-2.5 py-1 rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-700 transition-colors disabled:opacity-50"
              >
                {loading === 'snooze' ? '...' : '⏱ Ertele'}
              </button>
              {showSnooze && (
                <div className="absolute bottom-8 left-0 z-10 bg-gray-800 border border-gray-700 rounded-lg shadow-xl min-w-[120px] py-1">
                  {[
                    [30, '30 dk'], [60, '1 saat'], [120, '2 saat'], [480, '8 saat']
                  ].map(([m, label]) => (
                    <button
                      key={m}
                      onClick={() => doSnooze(m as number)}
                      className="w-full text-left text-xs px-3 py-1.5 text-gray-300 hover:bg-gray-700"
                    >
                      {label}
                    </button>
                  ))}
                </div>
              )}
            </div>

            <span className="text-xs text-gray-600 ml-auto self-center">
              {relTime(card.last_seen)}
            </span>
          </div>

          {/* RCA paneli */}
          {showRCA && (
            <RCAPanel
              eventIds={card.event_ids}
              metric={card.metrics[0]?.metric || ''}
              isStorm={false}
              onClose={() => setShowRCA(false)}
            />
          )}
        </div>
      </div>
    </div>
  )
}

// ── Fırtına Kartı ────────────────────────────────────────────────────────────
function StormCardView({
  storm, selected, onSelect, onDone
}: {
  storm: StormCard
  selected: boolean
  onSelect: (ids: number[], checked: boolean) => void
  onDone: () => void
}) {
  const [showServers, setShowServers] = useState(false)
  const [showRCA, setShowRCA] = useState(false)
  const [loading, setLoading] = useState<string | null>(null)

  async function doAction(action: 'acknowledge' | 'suppress') {
    setLoading(action)
    try {
      if (action === 'acknowledge') {
        await Promise.all(storm.event_ids.map(id =>
          fetch(`${API_BASE_URL}/events/${id}/acknowledge`, { method: 'POST' })
        ))
      } else {
        await Promise.all(storm.event_ids.map(id =>
          fetch(`${API_BASE_URL}/baseline/suppressions/from-event/${id}`, { method: 'POST' })
        ))
      }
      onDone()
    } finally { setLoading(null) }
  }

  return (
    <div className={`rounded-xl border border-amber-500/40 bg-amber-500/5 p-3 ${selected ? 'ring-1 ring-cyan-500/50' : ''}`}>
      <div className="flex items-start gap-2">
        <input
          type="checkbox"
          checked={selected}
          onChange={e => onSelect(storm.event_ids, e.target.checked)}
          className="mt-1 shrink-0 accent-cyan-500 cursor-pointer"
        />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-bold text-amber-400 bg-amber-500/10 border border-amber-500/30 px-1.5 py-0.5 rounded">
              ⚡ FIRTINA
            </span>
            <span className="font-semibold text-gray-100">{storm.metric}</span>
            <span className="text-xs bg-red-500/20 text-red-300 border border-red-500/40 px-1.5 py-0.5 rounded-full ml-auto">
              {storm.severity.toUpperCase()}
            </span>
          </div>

          <button
            onClick={() => setShowServers(v => !v)}
            className="mt-1 text-sm text-left hover:text-amber-200 transition-colors"
          >
            <span className="font-medium text-amber-300">{storm.server_count}</span>
            <span className="text-gray-400"> sunucu · {storm.event_count} event</span>
            <span className="text-xs text-gray-600 ml-1">{showServers ? '▲' : '▼ detay'}</span>
          </button>

          {showServers && (
            <div className="mt-2 rounded-lg border border-amber-500/20 divide-y divide-amber-500/10 bg-amber-500/3">
              {storm.affected_servers.map(s => (
                <div key={s.id} className="flex items-center justify-between px-3 py-1.5">
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-bold ${TIER_STYLE[s.tier] || TIER_STYLE.unknown}`}>
                      {TIER_SHORT[s.tier] || '?'}
                    </span>
                    <span className="text-sm text-gray-200">{s.name}</span>
                  </div>
                  <span className="text-xs text-gray-500">{s.ip}</span>
                </div>
              ))}
            </div>
          )}

          <div className="flex flex-wrap gap-1.5 mt-2">
            <Link to={`/incidents`} className="text-xs px-2.5 py-1 rounded-lg border border-purple-500/40 text-purple-300 hover:bg-purple-500/10 transition-colors">
              🔗 #{storm.incident_id}
            </Link>
            <button onClick={() => setShowRCA(v => !v)}
              className="text-xs px-2.5 py-1 rounded-lg border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10 transition-colors">
              🔍 RCA
            </button>
            <button onClick={() => doAction('acknowledge')} disabled={loading !== null}
              className="text-xs px-2.5 py-1 rounded-lg border border-blue-500/40 text-blue-300 hover:bg-blue-500/10 disabled:opacity-50 transition-colors">
              {loading === 'acknowledge' ? '...' : `✓ Tümünü Onayla (${storm.event_count})`}
            </button>
            <button onClick={() => doAction('suppress')} disabled={loading !== null}
              className="text-xs px-2.5 py-1 rounded-lg border border-gray-600 text-gray-400 hover:bg-gray-700 disabled:opacity-50 transition-colors">
              {loading === 'suppress' ? '...' : '🔇 Bastır'}
            </button>
          </div>

          {showRCA && (
            <RCAPanel eventIds={storm.event_ids} metric={storm.metric} isStorm onClose={() => setShowRCA(false)} />
          )}
        </div>
      </div>
    </div>
  )
}

// ── Toplu Aksiyon Toolbar ─────────────────────────────────────────────────────
function BulkToolbar({
  selectedIds, onClear, onDone
}: {
  selectedIds: number[]; onClear: () => void; onDone: () => void
}) {
  const [loading, setLoading] = useState<string | null>(null)

  async function doAll(action: 'acknowledge' | 'known' | 'suppress' | 'snooze') {
    setLoading(action)
    try {
      if (action === 'snooze') {
        await fetch(`${API_BASE_URL}/ops/snooze`, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ event_ids: selectedIds, minutes: 60 }),
        })
      } else if (action === 'suppress') {
        await Promise.all(selectedIds.map(id =>
          fetch(`${API_BASE_URL}/baseline/suppressions/from-event/${id}`, { method: 'POST' })
        ))
      } else {
        await Promise.all(selectedIds.map(id =>
          fetch(`${API_BASE_URL}/events/${id}/${action}`, { method: 'POST' })
        ))
      }
      onClear()
      onDone()
    } finally { setLoading(null) }
  }

  return (
    <div className="sticky top-0 z-20 flex items-center gap-2 bg-gray-900/95 backdrop-blur border border-cyan-500/30 rounded-xl px-4 py-2 shadow-lg">
      <span className="text-sm font-semibold text-cyan-400">{selectedIds.length} seçili</span>
      <div className="flex gap-1.5 ml-2">
        {[
          ['acknowledge', '✓ Tümünü Onayla', 'border-blue-500/40 text-blue-300 hover:bg-blue-500/10'],
          ['known', '👁 Bilinen Yap', 'border-gray-600 text-gray-400 hover:bg-gray-700'],
          ['suppress', '🔇 Bastır', 'border-gray-600 text-gray-400 hover:bg-gray-700'],
          ['snooze', '⏱ 1sa Ertele', 'border-gray-600 text-gray-400 hover:bg-gray-700'],
        ].map(([act, label, style]) => (
          <button key={act} onClick={() => doAll(act as any)} disabled={loading !== null}
            className={`text-xs px-2.5 py-1 rounded-lg border disabled:opacity-50 transition-colors ${style}`}>
            {loading === act ? '...' : label}
          </button>
        ))}
      </div>
      <button onClick={onClear} className="ml-auto text-xs text-gray-500 hover:text-gray-300">✕ Seçimi Kaldır</button>
    </div>
  )
}

// ── Ana Sayfa ─────────────────────────────────────────────────────────────────
export default function OpsCenter() {
  const qc = useQueryClient()
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [filter, setFilter] = useState<'all' | 'production' | 'staging' | 'development'>('all')

  const { data, isLoading, refetch } = useQuery<CommandCenterData>({
    queryKey: ['ops-command-center'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/ops/command-center`)
      if (!r.ok) throw new Error('ops/command-center hata')
      return r.json()
    },
    refetchInterval: 30_000,
  })

  function invalidate() {
    setSelectedIds(new Set())
    qc.invalidateQueries({ queryKey: ['ops-command-center'] })
  }

  function toggleSelect(ids: number[], checked: boolean) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      ids.forEach(id => checked ? next.add(id) : next.delete(id))
      return next
    })
  }

  // Tier filtresi
  const criticalFiltered = useMemo(() =>
    filter === 'all' ? (data?.critical_servers ?? []) :
    (data?.critical_servers ?? []).filter(c => c.server.tier === filter),
    [data, filter]
  )
  const warningFiltered = useMemo(() =>
    filter === 'all' ? (data?.warning_servers ?? []) :
    (data?.warning_servers ?? []).filter(c => c.server.tier === filter),
    [data, filter]
  )

  if (isLoading) return (
    <div className="flex items-center justify-center min-h-[60vh]">
      <div className="text-center space-y-3">
        <div className="w-10 h-10 rounded-full border-2 border-t-cyan-400 border-r-transparent animate-spin mx-auto" />
        <p className="text-gray-400 text-sm">Alarm durumu analiz ediliyor...</p>
      </div>
    </div>
  )

  const allOk = !data?.critical_count && !data?.storm_count && !data?.warning_count

  return (
    <div className="space-y-4 max-w-3xl mx-auto">
      {/* Başlık + Yenile */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-gray-100">Komuta Merkezi</h1>
        <div className="flex items-center gap-2">
          <span className="text-xs text-gray-600">{relTime(data?.generated_at ?? null)} önce</span>
          <button onClick={() => refetch()}
            className="text-xs px-3 py-1.5 rounded-lg border border-gray-700 text-gray-400 hover:bg-gray-700 transition-colors">
            ↻
          </button>
        </div>
      </div>

      {/* Sağlık skoru + özet */}
      {data?.health && (
        <div className="grid grid-cols-1 sm:grid-cols-[1fr_auto_auto_auto] gap-3 items-center">
          <HealthBadge health={data.health} />
          <div className={`rounded-xl border p-3 text-center min-w-[80px] ${data.critical_count ? 'border-red-500/40 bg-red-500/8' : 'border-gray-700 bg-gray-800/30'}`}>
            <div className={`text-2xl font-bold ${data.critical_count ? 'text-red-400' : 'text-gray-500'}`}>{data.critical_count + data.storm_count}</div>
            <div className="text-[10px] text-gray-500 mt-0.5">🔴 Kritik</div>
          </div>
          <div className={`rounded-xl border p-3 text-center min-w-[80px] ${data.warning_count ? 'border-amber-500/30 bg-amber-500/5' : 'border-gray-700 bg-gray-800/30'}`}>
            <div className={`text-2xl font-bold ${data.warning_count ? 'text-amber-400' : 'text-gray-500'}`}>{data.warning_count}</div>
            <div className="text-[10px] text-gray-500 mt-0.5">🟡 Uyarı</div>
          </div>
          <div className="rounded-xl border border-green-500/20 bg-green-500/5 p-3 text-center min-w-[80px]">
            <div className="text-2xl font-bold text-green-400">{data.green_count}</div>
            <div className="text-[10px] text-gray-500 mt-0.5">🟢 Kontrol</div>
          </div>
        </div>
      )}

      {/* Tier filtre */}
      <div className="flex gap-1.5">
        {(['all', 'production', 'staging', 'development'] as const).map(t => (
          <button key={t} onClick={() => setFilter(t)}
            className={`text-xs px-3 py-1 rounded-full border transition-colors ${
              filter === t
                ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-300'
                : 'border-gray-700 text-gray-500 hover:text-gray-300'
            }`}>
            {t === 'all' ? 'Tümü' : TIER_SHORT[t]}
          </button>
        ))}
      </div>

      {/* Toplu aksiyon toolbar */}
      {selectedIds.size > 0 && (
        <BulkToolbar selectedIds={[...selectedIds]} onClear={() => setSelectedIds(new Set())} onDone={invalidate} />
      )}

      {/* Her şey yolunda */}
      {allOk && (
        <div className="rounded-xl border border-green-500/30 bg-green-500/5 p-8 text-center">
          <div className="text-4xl mb-3">✅</div>
          <h3 className="text-lg font-semibold text-green-400">Her şey yolunda</h3>
          <p className="text-sm text-gray-400 mt-1">Son 24 saatte müdahale gerektiren alarm yok.</p>
        </div>
      )}

      {/* ⚡ Fırtınalar */}
      {(data?.storms?.length ?? 0) > 0 && (
        <section>
          <h2 className="text-xs font-semibold text-amber-400 uppercase tracking-wide mb-2 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-400 animate-pulse" />
            Alarm Fırtınaları — {data!.storms.length}
          </h2>
          <div className="space-y-2">
            {data!.storms.map(s => (
              <StormCardView key={s.incident_id} storm={s}
                selected={s.event_ids.every(id => selectedIds.has(id))}
                onSelect={toggleSelect} onDone={invalidate} />
            ))}
          </div>
        </section>
      )}

      {/* 🔴 Kritik Sunucular */}
      {criticalFiltered.length > 0 && (
        <section>
          <h2 className="text-xs font-semibold text-red-400 uppercase tracking-wide mb-2 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
            Hemen Bak — {criticalFiltered.length} sunucu
          </h2>
          <div className="space-y-2">
            {criticalFiltered.map(c => (
              <ServerCard key={`${c.server.id}-${c.last_seen}`} card={c}
                selected={c.event_ids.every(id => selectedIds.has(id))}
                onSelect={toggleSelect} onDone={invalidate} />
            ))}
          </div>
        </section>
      )}

      {/* 🟡 Uyarı Sunucuları */}
      {warningFiltered.length > 0 && (
        <section>
          <h2 className="text-xs font-semibold text-amber-400 uppercase tracking-wide mb-2 flex items-center gap-2">
            <span className="w-2 h-2 rounded-full bg-amber-400" />
            İzle — {warningFiltered.length} sunucu
          </h2>
          <div className="space-y-2">
            {warningFiltered.map(c => (
              <ServerCard key={`${c.server.id}-${c.last_seen}`} card={c}
                selected={c.event_ids.every(id => selectedIds.has(id))}
                onSelect={toggleSelect} onDone={invalidate} />
            ))}
          </div>
        </section>
      )}

      {/* Alt nav */}
      <div className="grid grid-cols-4 gap-2 pt-2 border-t border-gray-700/60">
        {[
          { to: '/events',    label: '📋 Events' },
          { to: '/incidents', label: '🚨 Incidents' },
          { to: '/baseline',  label: '⚙ Baseline' },
          { to: '/rca',       label: '🔍 Kök Neden' },
        ].map(({ to, label }) => (
          <Link key={to} to={to}
            className="text-center text-xs px-2 py-2 rounded-lg border border-gray-700/60 text-gray-400 hover:bg-gray-700/40 hover:text-gray-200 transition-colors">
            {label}
          </Link>
        ))}
      </div>
    </div>
  )
}
