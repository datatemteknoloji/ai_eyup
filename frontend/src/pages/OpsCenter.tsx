/**
 * Ops Komuta Merkezi — "Şu an ne yapmalıyım?" tek ekranı.
 *
 * Trafik lambası mantığı:
 *   🔴 HEMEN BAK   → critical/emergency, fırtına, production warning
 *   🟡 İZLE        → warning (non-production)
 *   🟢 KONTROL     → bastırılan, bilinen, çözülen
 */
import { useState, useCallback, useEffect } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { API_BASE_URL } from '../config/api'

// ── Inline RCA paneli ────────────────────────────────────────────────────────
interface RCAResult {
  root_cause?: string
  likely_cause?: string
  impact?: string
  actions?: string[]
  severity_assessment?: string
  confidence?: string
}
interface RCAResponse {
  server: string; metric: string; event_count: number
  analysis: RCAResult; model: string; analyzed_at: string
}

function RCAPanel({
  eventId, serverId, metric, onClose
}: {
  eventId?: number; serverId?: number; metric: string; onClose: () => void
}) {
  const [result, setResult] = useState<RCAResponse | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const run = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const r = await fetch(`${API_BASE_URL}/rca/quick-analyze`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_id: eventId, server_id: serverId, metric }),
      })
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      setResult(await r.json())
    } catch (e: any) {
      setError(e.message || 'Bilinmeyen hata')
    } finally {
      setLoading(false)
    }
  }, [eventId, serverId, metric])

  // İlk açılışta otomatik başlat
  useEffect(() => { run() }, [])

  const conf = result?.analysis?.confidence
  const confColor = conf === 'high' ? 'text-green-400' : conf === 'medium' ? 'text-amber-400' : 'text-gray-400'

  return (
    <div className="mt-3 rounded-lg border border-cyan-500/30 bg-cyan-500/5 p-3 space-y-2">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-cyan-400">🔍 AI Kök Neden Analizi</span>
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
          ⚠ {error}
          <button onClick={run} className="ml-2 underline">Tekrar dene</button>
        </div>
      )}

      {result && (
        <div className="space-y-2 text-sm">
          <div>
            <span className="text-[10px] text-gray-500 uppercase">Kök Neden</span>
            <p className="text-gray-200 mt-0.5">{result.analysis.root_cause}</p>
          </div>
          {result.analysis.likely_cause && (
            <div>
              <span className="text-[10px] text-gray-500 uppercase">Olası Sebep</span>
              <p className="text-gray-300 mt-0.5">{result.analysis.likely_cause}</p>
            </div>
          )}
          {result.analysis.impact && (
            <div>
              <span className="text-[10px] text-gray-500 uppercase">Etki</span>
              <p className="text-gray-300 mt-0.5">{result.analysis.impact}</p>
            </div>
          )}
          {result.analysis.actions && result.analysis.actions.length > 0 && (
            <div>
              <span className="text-[10px] text-gray-500 uppercase">Aksiyonlar</span>
              <ul className="mt-1 space-y-1">
                {result.analysis.actions.map((a, i) => (
                  <li key={i} className="text-xs text-gray-300 flex gap-1.5">
                    <span className="text-cyan-500 shrink-0">→</span>
                    <span>{a}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex items-center gap-3 pt-1 border-t border-gray-700/60">
            <span className={`text-xs ${confColor}`}>Güven: {conf}</span>
            <span className="text-xs text-gray-500">{result.event_count} event analiz edildi</span>
            <button onClick={run} className="text-xs text-gray-500 hover:text-gray-300 ml-auto">↻ Yenile</button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Types ─────────────────────────────────────────────────────────────────────
interface ServerInfo {
  name: string; hostname: string; ip: string; tier: string
}

interface ActionItem {
  type: 'storm' | 'single' | 'group'
  metric: string
  severity: string
  event_count: number
  event_ids: number[]
  server_count: number
  server: ServerInfo | null
  storm_incident_id: number | null
  first_seen: string | null
  last_seen: string | null
  occurrence_count: number
  current_value: number | null
  actions: string[]
}

interface CommandCenterData {
  red: ActionItem[]
  yellow: ActionItem[]
  red_count: number
  yellow_count: number
  green_count: number
  storm_count: number
  generated_at: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const TIER_COLORS: Record<string, string> = {
  production: 'bg-red-500/20 text-red-300 border-red-500/30',
  staging:    'bg-amber-500/20 text-amber-300 border-amber-500/30',
  development:'bg-green-500/20 text-green-300 border-green-500/30',
  unknown:    'bg-gray-500/20 text-gray-400 border-gray-500/30',
}
const TIER_LABEL: Record<string, string> = {
  production: 'PRD', staging: 'STG', development: 'DEV', unknown: '?'
}
const SEV_BG: Record<string, string> = {
  emergency: 'border-purple-500/40 bg-purple-500/5',
  critical:  'border-red-500/40 bg-red-500/5',
  warning:   'border-amber-500/40 bg-amber-500/5',
  info:      'border-blue-500/20 bg-blue-500/5',
}
const SEV_DOT: Record<string, string> = {
  emergency: 'bg-purple-400 animate-ping',
  critical:  'bg-red-400 animate-pulse',
  warning:   'bg-amber-400',
  info:      'bg-blue-400',
}

function relTime(iso: string | null): string {
  if (!iso) return ''
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'şimdi'
  if (m < 60) return `${m}dk önce`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}s önce`
  return `${Math.floor(h / 24)}g önce`
}

function metricLabel(raw: string): string {
  const map: Record<string, string> = {
    cpu_usage: 'CPU Kullanımı', memory_usage: 'Bellek',
    disk_usage: 'Disk', network_rx: 'Ağ Giriş', network_tx: 'Ağ Çıkış',
    load_average: 'Sistem Yükü', swap_usage: 'Swap',
  }
  return map[raw] || raw.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())
}

// ── Aksiyon butonları ─────────────────────────────────────────────────────────
function ActionButtons({
  item, onDone, onRCA
}: {
  item: ActionItem
  onDone: () => void
  onRCA: () => void
}) {
  const [loading, setLoading] = useState<string | null>(null)

  async function markKnown() {
    setLoading('known')
    try {
      await Promise.all(
        item.event_ids.map(id =>
          fetch(`${API_BASE_URL}/events/${id}/known`, { method: 'POST' })
        )
      )
      onDone()
    } finally { setLoading(null) }
  }

  async function acknowledge() {
    setLoading('ack')
    try {
      await Promise.all(
        item.event_ids.map(id =>
          fetch(`${API_BASE_URL}/events/${id}/acknowledge`, { method: 'POST' })
        )
      )
      onDone()
    } finally { setLoading(null) }
  }

  async function suppressAll() {
    setLoading('suppress')
    try {
      await Promise.all(
        item.event_ids.map(id =>
          fetch(`${API_BASE_URL}/baseline/suppressions/from-event/${id}`, { method: 'POST' })
        )
      )
      onDone()
    } finally { setLoading(null) }
  }

  const btn = (label: string, onClick: () => void, key: string, color: string) => (
    <button
      key={key}
      onClick={onClick}
      disabled={loading !== null}
      className={`text-xs px-2.5 py-1 rounded-lg border transition-colors disabled:opacity-50 ${color}`}
    >
      {loading === key ? '...' : label}
    </button>
  )

  return (
    <div className="flex flex-wrap gap-1.5 mt-2">
      {item.storm_incident_id && (
        <Link
          to={`/incidents`}
          className="text-xs px-2.5 py-1 rounded-lg border border-purple-500/40 text-purple-300 hover:bg-purple-500/10 transition-colors"
        >
          🔗 Incident #{item.storm_incident_id}
        </Link>
      )}
      {item.actions.includes('rca') && (
        <button
          onClick={onRCA}
          className="text-xs px-2.5 py-1 rounded-lg border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10 transition-colors"
        >
          🔍 RCA
        </button>
      )}
      {item.actions.includes('acknowledge') &&
        btn('✓ Onayla', acknowledge, 'ack', 'border-blue-500/40 text-blue-300 hover:bg-blue-500/10')}
      {item.actions.includes('acknowledge_all') &&
        btn(`✓ Tümünü Onayla (${item.event_count})`, acknowledge, 'ack', 'border-blue-500/40 text-blue-300 hover:bg-blue-500/10')}
      {item.actions.includes('mark_known') &&
        btn('👁 Bilinen Yap', markKnown, 'known', 'border-gray-600 text-gray-400 hover:bg-gray-700')}
      {(item.actions.includes('suppress') || item.actions.includes('suppress_all')) &&
        btn('🔇 Bastır', suppressAll, 'suppress', 'border-gray-600 text-gray-400 hover:bg-gray-700')}
    </div>
  )
}

// ── Tekil kart ────────────────────────────────────────────────────────────────
function ActionCard({ item, onDone }: { item: ActionItem; onDone: () => void }) {
  const tier = item.server?.tier || 'unknown'
  const [showRCA, setShowRCA] = useState(false)

  return (
    <div className={`rounded-xl border p-3 transition-all hover:brightness-110 ${SEV_BG[item.severity] || SEV_BG.warning}`}>
      <div className="flex items-start gap-3">
        {/* Severity dot */}
        <div className="mt-1 shrink-0">
          <span className={`inline-block w-2 h-2 rounded-full ${SEV_DOT[item.severity] || 'bg-gray-400'}`} />
        </div>

        <div className="flex-1 min-w-0">
          {/* Başlık satırı */}
          <div className="flex items-center gap-2 flex-wrap">
            {item.type === 'storm' && (
              <span className="text-xs font-bold text-amber-400 bg-amber-500/10 border border-amber-500/30 px-1.5 py-0.5 rounded">
                ⚡ FIRTINA
              </span>
            )}
            <span className="font-semibold text-gray-100 truncate">
              {metricLabel(item.metric)}
            </span>
            {item.current_value !== null && (
              <span className="text-xs text-gray-400">
                %{Math.round(item.current_value)}
              </span>
            )}
            <span className={`text-xs px-1.5 py-0.5 rounded-full border ml-auto ${
              item.severity === 'critical' || item.severity === 'emergency'
                ? 'bg-red-500/20 text-red-300 border-red-500/40'
                : 'bg-amber-500/20 text-amber-300 border-amber-500/40'
            }`}>
              {item.severity.toUpperCase()}
            </span>
          </div>

          {/* Sunucu bilgisi */}
          <div className="flex items-center gap-2 mt-1 flex-wrap">
            {item.type === 'storm' ? (
              <span className="text-sm text-gray-300">
                <span className="font-medium text-amber-300">{item.server_count}</span> sunucu aynı anda
              </span>
            ) : item.server ? (
              <>
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-bold ${TIER_COLORS[tier]}`}>
                  {TIER_LABEL[tier]}
                </span>
                <span className="text-sm text-gray-300 font-medium">{item.server.name}</span>
                <span className="text-xs text-gray-500">{item.server.ip}</span>
              </>
            ) : (
              <span className="text-sm text-gray-500">Sunucu bilinmiyor</span>
            )}
            {item.occurrence_count > 1 && (
              <span className="text-xs text-gray-500 ml-auto">
                {item.occurrence_count}× tekrar
              </span>
            )}
            <span className="text-xs text-gray-500">{relTime(item.last_seen)}</span>
          </div>

          <ActionButtons item={item} onDone={onDone} onRCA={() => setShowRCA(v => !v)} />

          {showRCA && (
            <RCAPanel
              eventId={item.event_ids[0]}
              serverId={item.server ? undefined : undefined}
              metric={item.metric}
              onClose={() => setShowRCA(false)}
            />
          )}
        </div>
      </div>
    </div>
  )
}

// ── Ana sayfa ─────────────────────────────────────────────────────────────────
export default function OpsCenter() {
  const qc = useQueryClient()

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
    qc.invalidateQueries({ queryKey: ['ops-command-center'] })
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="text-center space-y-3">
          <div className="w-10 h-10 rounded-full border-2 border-t-cyan-400 border-r-transparent animate-spin mx-auto" />
          <p className="text-gray-400 text-sm">Alarm durumu analiz ediliyor...</p>
        </div>
      </div>
    )
  }

  const red = data?.red ?? []
  const yellow = data?.yellow ?? []
  const greenCount = data?.green_count ?? 0
  const stormCount = data?.storm_count ?? 0

  return (
    <div className="space-y-6 max-w-4xl mx-auto">
      {/* Başlık */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-gray-100">Ops Komuta Merkezi</h1>
          <p className="text-sm text-gray-500 mt-0.5">
            {data?.generated_at ? `Son güncelleme: ${relTime(data.generated_at)}` : ''}
          </p>
        </div>
        <button
          onClick={() => refetch()}
          className="text-xs px-3 py-1.5 rounded-lg border border-gray-700 text-gray-400 hover:bg-gray-700 transition-colors"
        >
          ↻ Yenile
        </button>
      </div>

      {/* Özet banner */}
      <div className="grid grid-cols-3 gap-3">
        <div className={`rounded-xl border p-4 text-center ${red.length > 0 ? 'border-red-500/50 bg-red-500/10' : 'border-gray-700 bg-gray-800/30'}`}>
          <div className={`text-3xl font-bold ${red.length > 0 ? 'text-red-400' : 'text-gray-500'}`}>
            {data?.red_count ?? 0}
          </div>
          <div className="text-xs text-gray-400 mt-1">🔴 Hemen Bak</div>
          {stormCount > 0 && (
            <div className="text-xs text-amber-400 mt-1">⚡ {stormCount} fırtına</div>
          )}
        </div>
        <div className={`rounded-xl border p-4 text-center ${yellow.length > 0 ? 'border-amber-500/30 bg-amber-500/5' : 'border-gray-700 bg-gray-800/30'}`}>
          <div className={`text-3xl font-bold ${yellow.length > 0 ? 'text-amber-400' : 'text-gray-500'}`}>
            {data?.yellow_count ?? 0}
          </div>
          <div className="text-xs text-gray-400 mt-1">🟡 İzle</div>
        </div>
        <div className="rounded-xl border border-green-500/20 bg-green-500/5 p-4 text-center">
          <div className="text-3xl font-bold text-green-400">{greenCount}</div>
          <div className="text-xs text-gray-400 mt-1">🟢 Kontrol Altında</div>
        </div>
      </div>

      {/* Hiç sorun yoksa */}
      {red.length === 0 && yellow.length === 0 && (
        <div className="rounded-xl border border-green-500/30 bg-green-500/5 p-8 text-center">
          <div className="text-4xl mb-3">✅</div>
          <h3 className="text-lg font-semibold text-green-400">Her şey yolunda</h3>
          <p className="text-sm text-gray-400 mt-1">
            Son 24 saatte müdahale gerektiren alarm yok.
          </p>
        </div>
      )}

      {/* 🔴 Kritik — Hemen Bak */}
      {red.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-3">
            <span className="w-3 h-3 rounded-full bg-red-500 animate-pulse" />
            <h2 className="text-sm font-semibold text-red-400 uppercase tracking-wide">
              Hemen Bak — {red.length} sorun
            </h2>
            {red.length > 10 && (
              <span className="text-xs text-gray-500 ml-auto">
                İlk 50 gösteriliyor, tümü için{' '}
                <Link to="/events" className="text-cyan-400 hover:underline">Events</Link>
              </span>
            )}
          </div>
          <div className="space-y-2">
            {red.map((item, i) => (
              <ActionCard key={`${item.metric}-${item.event_ids[0]}-${i}`} item={item} onDone={invalidate} />
            ))}
          </div>
        </section>
      )}

      {/* 🟡 Warning — İzle */}
      {yellow.length > 0 && (
        <section>
          <div className="flex items-center gap-2 mb-3">
            <span className="w-3 h-3 rounded-full bg-amber-400" />
            <h2 className="text-sm font-semibold text-amber-400 uppercase tracking-wide">
              İzle — {yellow.length} uyarı
            </h2>
          </div>
          <div className="space-y-2">
            {yellow.map((item, i) => (
              <ActionCard key={`y-${item.metric}-${item.event_ids[0]}-${i}`} item={item} onDone={invalidate} />
            ))}
          </div>
        </section>
      )}

      {/* Hızlı navigasyon */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 pt-2 border-t border-gray-700/60">
        {[
          { to: '/events', label: '📋 Tüm Events' },
          { to: '/incidents', label: '🚨 Incidents' },
          { to: '/baseline', label: '⚙ Baseline' },
          { to: '/rca', label: '🔍 Kök Neden' },
        ].map(({ to, label }) => (
          <Link
            key={to}
            to={to}
            className="text-center text-xs px-3 py-2 rounded-lg border border-gray-700/60 text-gray-400 hover:bg-gray-700/40 hover:text-gray-200 transition-colors"
          >
            {label}
          </Link>
        ))}
      </div>
    </div>
  )
}
