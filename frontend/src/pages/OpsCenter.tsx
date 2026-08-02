/**
 * Komuta Merkezi — tam yeniden tasarım
 * Grid layout · Slide-over detay · Aktivite zaman çizelgesi · Metrik widget'ları
 * Arama/filtre · Otomatik yenileme sayacı · Toplu aksiyon toolbar
 */
import { useState, useCallback, useEffect, useMemo } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  RefreshCw, X, Search, ChevronDown, Cpu, MemoryStick, HardDrive, Network,
  Activity, Zap, CheckCircle2, Clock, Siren,
  ScanSearch, ArrowRight, Eye, BellOff, BarChart3, Terminal, FileDown,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import type { PlatformAiopsProps } from '../utils/platformApi'
import { PLATFORM_AIOPS_PREFIX } from '../config/platformAiops'
import {
  OpsRefreshCountdown,
  OpsShell,
} from '../components/ops/OpsShell'
import { exportRcaSectionsToPrintWindow } from '../utils/pdfExport'

// ── Types ─────────────────────────────────────────────────────────────────────
interface ServerInfo { id: number | null; name: string; hostname: string; ip: string; tier: string }
interface MetricItem {
  event_id: number; metric: string; severity: string
  value: number | null; occurrence_count: number
  last_seen: string | null; event_type: string
}
interface ServerCard {
  server: ServerInfo; max_severity: string; event_count: number
  event_ids: number[]; metrics: MetricItem[]; last_seen: string | null
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
  health: HealthScore; storms: StormCard[]
  critical_servers: ServerCard[]; warning_servers: ServerCard[]
  critical_count: number; warning_count: number
  storm_count: number; green_count: number; generated_at: string
  event_critical?: number
  event_warning?: number
  event_total?: number
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
interface EventItem {
  id: number; title: string; severity: string; event_type: string
  server_id: number | null; server_name?: string
  first_seen?: string | null; last_seen?: string | null; created_at?: string | null
  occurrence_count: number
  is_acknowledged: boolean; resolved: boolean
}

// ── Helpers ───────────────────────────────────────────────────────────────────
const TIER_STYLE: Record<string, string> = {
  production:  'bg-red-500/20 text-red-300 border-red-500/40',
  staging:     'bg-amber-500/20 text-amber-300 border-amber-500/40',
  development: 'bg-green-500/20 text-green-300 border-green-500/40',
  unknown:     'bg-slate-700/40 text-slate-400 border-slate-600/40',
}
const TIER_SHORT: Record<string, string> = { production: 'PRD', staging: 'STG', development: 'DEV', unknown: '?' }

// DESIGN.md: mor/violet kullanılmaz. "emergency" (critical'in üstü) aynı
// kırmızı ailesinde ama daha yoğun (red-600) bir tonla ayrıştırılır.
const SEV_RING: Record<string, string> = {
  emergency: 'border-red-600/70 bg-red-600/10',
  critical:  'border-red-500/50 bg-red-500/5',
  warning:   'border-amber-500/40 bg-amber-500/4',
}
const SEV_TEXT: Record<string, string> = {
  emergency: 'text-red-500 font-bold', critical: 'text-red-300',
  warning: 'text-amber-300', info: 'text-blue-300',
}
const SEV_DOT: Record<string, string> = {
  emergency: 'bg-red-600 animate-ping',
  critical:  'bg-red-400 animate-pulse',
  warning:   'bg-amber-400',
  info:      'bg-blue-400',
}
const SEV_BADGE: Record<string, string> = {
  emergency: 'bg-red-600/30 text-red-400 border-red-600/50',
  critical:  'bg-red-500/20 text-red-300 border-red-500/40',
  warning:   'bg-amber-500/20 text-amber-300 border-amber-500/40',
  info:      'bg-blue-500/20 text-blue-300 border-blue-500/40',
}

function relTime(iso: string | null | undefined): string {
  if (!iso) return ''
  const t = new Date(iso).getTime()
  if (!Number.isFinite(t)) return ''
  const d = Date.now() - t
  const m = Math.floor(d / 60000)
  if (m < 1) return 'şimdi'
  if (m < 60) return `${m}dk`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}s`
  return `${Math.floor(h / 24)}g`
}

function metricCategory(metric: string): 'cpu' | 'memory' | 'disk' | 'network' | 'other' {
  const m = (metric || '').toLowerCase()
  if (m.includes('cpu') || m.includes('load') || m.includes('steal')) return 'cpu'
  if (
    m.includes('mem') || m.includes('ram') || m.includes('swap')
    || m.includes('oom') || m.includes('out of memory') || m.includes('killer')
  ) return 'memory'
  if (
    m.includes('disk') || m.includes('fs') || m.includes('filesystem') || m.includes('inode')
    || m.includes('multipath') || m.includes('storage') || m.includes('volume')
    || m.includes('lvm') || m.includes('mdadm') || m.includes('smart')
  ) return 'disk'
  if (
    m.includes('net') || m.includes('bandwidth') || m.includes('eth')
    || m.includes('rx') || m.includes('tx') || m.includes('nic')
    || m.includes('bond') || m.includes('link down') || m.includes('carrier')
  ) return 'network'
  return 'other'
}

function eventWhen(ev: { last_seen?: string | null; first_seen?: string | null; created_at?: string | null }): string | null {
  return ev.last_seen || ev.first_seen || ev.created_at || null
}

// ── Metrik Kategori Widget ────────────────────────────────────────────────────
function MetricWidget({ icon, label, count, critCount, color, active, onClick }: {
  icon: React.ReactNode; label: string; count: number; critCount: number; color: string
  active?: boolean; onClick?: () => void
}) {
  const pct = count === 0 ? 0 : Math.min(100, count * 12)
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex-1 text-left bg-slate-800/60 border rounded-xl px-4 py-3 transition-all ${
        onClick ? 'cursor-pointer hover:border-cyan-500/40 hover:bg-slate-800' : ''
      } ${active ? 'border-cyan-500/60 ring-1 ring-cyan-500/30' : 'border-slate-700/60'}`}
    >
      <div className="flex items-center justify-between mb-2">
        <div className={`flex items-center gap-2 text-sm font-medium ${color}`}>
          {icon} {label}
        </div>
        <span className={`text-lg font-bold ${count > 0 ? color : 'text-slate-600'}`}>{count}</span>
      </div>
      <div className="h-1 bg-slate-700 rounded-full overflow-hidden">
        <div className="h-full rounded-full transition-all duration-500" style={{
          width: `${pct}%`,
          backgroundColor: count > 0 ? (critCount > 0 ? '#ef4444' : '#f59e0b') : '#334155'
        }} />
      </div>
      {critCount > 0 && <div className="text-[10px] text-red-400 mt-1">{critCount} kritik</div>}
    </button>
  )
}

// ── RCA Panel ─────────────────────────────────────────────────────────────────
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
  const confCol = conf === 'high' ? 'text-green-400' : conf === 'medium' ? 'text-amber-400' : 'text-slate-500'

  return (
    <div className="mt-3 rounded-xl border border-cyan-500/30 bg-cyan-500/5 p-4 space-y-3">
      <div className="flex items-center justify-between">
        <span className="text-xs font-semibold text-cyan-400 flex items-center gap-1.5">
          <ScanSearch size={13} /> {isStorm ? 'Fırtına Analizi' : 'AI Kök Neden Analizi'}
        </span>
        <button onClick={onClose} className="text-slate-500 hover:text-slate-300 transition-colors">
          <X size={14} />
        </button>
      </div>
      {loading && (
        <div className="flex items-center gap-2 py-2">
          <div className="w-4 h-4 rounded-full border-2 border-t-cyan-400 border-r-transparent animate-spin" />
          <span className="text-xs text-slate-400">Analiz ediliyor…</span>
        </div>
      )}
      {error && (
        <div className="text-xs text-red-400 bg-red-500/10 rounded-lg p-3 flex items-center justify-between">
          <span>{error}</span>
          <button onClick={run} className="text-cyan-400 hover:underline">Tekrar dene</button>
        </div>
      )}
      {result && (
        <div className="space-y-2.5 text-sm">
          {result.analysis.root_cause && (
            <div>
              <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium mb-1">Kök Neden</p>
              <p className="text-slate-200">{result.analysis.root_cause}</p>
            </div>
          )}
          {result.analysis.likely_cause && (
            <div>
              <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium mb-1">Olası Sebep</p>
              <p className="text-slate-300">{result.analysis.likely_cause}</p>
            </div>
          )}
          {result.analysis.impact && (
            <div>
              <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium mb-1">Etki</p>
              <p className="text-slate-300">{result.analysis.impact}</p>
            </div>
          )}
          {(result.analysis.actions ?? []).length > 0 && (
            <div>
              <p className="text-[10px] text-slate-500 uppercase tracking-wider font-medium mb-1">Önerilen Aksiyonlar</p>
              <ul className="space-y-1">
                {result.analysis.actions!.map((a, i) => (
                  <li key={i} className="text-xs text-slate-300 flex gap-2">
                    <ArrowRight size={12} className="text-cyan-500 shrink-0 mt-0.5" />
                    <span>{a}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
          <div className="flex items-center gap-3 pt-2 border-t border-slate-700/50 text-xs text-slate-500">
            <span className={confCol}>Güven: {conf}</span>
            <span>{result.event_count} event</span>
            <button
              type="button"
              onClick={() => {
                const a = result.analysis
                const sections: Array<{ heading?: string; body?: string; items?: string[] }> = []
                if (a.root_cause) sections.push({ heading: 'Kök Neden', body: a.root_cause })
                if (a.likely_cause) sections.push({ heading: 'Olası Sebep', body: a.likely_cause })
                if (a.impact) sections.push({ heading: 'Etki', body: a.impact })
                if ((a.actions || []).length) sections.push({ heading: 'Önerilen Aksiyonlar', items: a.actions })
                if (a.affected_summary) sections.push({ heading: 'Etkilenen Özet', body: a.affected_summary })
                if (a.severity_assessment) sections.push({ heading: 'Önem', body: a.severity_assessment })
                if (a.confidence) sections.push({ heading: 'Güven', body: String(a.confidence) })
                exportRcaSectionsToPrintWindow(sections, {
                  title: isStorm ? `Fırtına RCA — ${metric}` : `OpsCenter RCA — ${metric}`,
                  subtitle: `${result.model || ''} · ${result.event_count} event · ${result.analyzed_at || ''}`,
                  filename: `rca_ops_${(metric || 'analiz').replace(/\s+/g, '_')}_${new Date().toISOString().slice(0, 10)}`,
                })
              }}
              className="inline-flex items-center gap-1 hover:text-cyan-300 transition-colors"
              title="PDF olarak kaydet"
            >
              <FileDown size={12} /> PDF
            </button>
            <button onClick={run} className="ml-auto hover:text-slate-300 transition-colors">
              <RefreshCw size={11} />
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

// ── Slide-over Server Detail ──────────────────────────────────────────────────
function ServerDetailPanel({
  card, onClose, onDone
}: { card: ServerCard; onClose: () => void; onDone: () => void }) {
  const [showRCA, setShowRCA] = useState(false)
  const [loading, setLoading] = useState<string | null>(null)
  const [showSnooze, setShowSnooze] = useState(false)

  async function doAction(action: 'acknowledge' | 'known' | 'suppress') {
    setLoading(action)
    try {
      if (action === 'suppress') {
        await Promise.all(card.event_ids.map(id =>
          fetch(`${API_BASE_URL}/baseline/suppressions/from-event/${id}`, { method: 'POST' })
        ))
      } else {
        await Promise.all(card.event_ids.map(id =>
          fetch(`${API_BASE_URL}/events/${id}/${action}`, { method: 'POST' })
        ))
      }
      onDone(); onClose()
    } finally { setLoading(null) }
  }

  async function doSnooze(minutes: number) {
    setLoading('snooze'); setShowSnooze(false)
    try {
      await fetch(`${API_BASE_URL}/ops/snooze`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_ids: card.event_ids, minutes }),
      })
      onDone(); onClose()
    } finally { setLoading(null) }
  }

  const sev = card.max_severity
  return (
    <>
      {/* Backdrop */}
      <div className="fixed inset-0 bg-black/40 z-40" onClick={onClose} />
      {/* Panel */}
      <div className="fixed right-0 top-0 h-full w-[420px] bg-slate-900 border-l border-slate-700 z-50 flex flex-col shadow-2xl">
        {/* Header */}
        <div className={`flex-none p-5 border-b border-slate-700/60 ${
          sev === 'critical' || sev === 'emergency' ? 'bg-red-500/5' : 'bg-amber-500/5'
        }`}>
          <div className="flex items-start justify-between">
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 flex-wrap">
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-bold ${TIER_STYLE[card.server.tier]}`}>
                  {TIER_SHORT[card.server.tier] || card.server.tier}
                </span>
                <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-semibold ${SEV_BADGE[sev]}`}>
                  {sev.toUpperCase()}
                </span>
              </div>
              <h3 className="text-lg font-bold text-white mt-2 truncate">{card.server.name}</h3>
              <p className="text-sm text-slate-400">{card.server.ip} · {card.server.hostname}</p>
            </div>
            <button onClick={onClose}
              className="flex-none p-1.5 rounded-lg text-slate-500 hover:text-white hover:bg-slate-800 transition-colors ml-3">
              <X size={18} />
            </button>
          </div>
        </div>

        {/* Body — scrollable */}
        <div className="flex-1 overflow-y-auto p-5 space-y-5">
          {/* Action buttons */}
          <div className="flex flex-wrap gap-2">
            <button onClick={() => doAction('acknowledge')} disabled={loading !== null}
              className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-blue-500/50 text-blue-300 hover:bg-blue-500/10 disabled:opacity-50 transition-colors">
              <CheckCircle2 size={14} /> {loading === 'acknowledge' ? '…' : 'Onayla'}
            </button>
            <button onClick={() => doAction('known')} disabled={loading !== null}
              className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-slate-600 text-slate-400 hover:bg-slate-700 disabled:opacity-50 transition-colors">
              <Eye size={14} /> {loading === 'known' ? '…' : 'Bilinen'}
            </button>
            <button onClick={() => doAction('suppress')} disabled={loading !== null}
              className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-slate-600 text-slate-400 hover:bg-slate-700 disabled:opacity-50 transition-colors">
              <BellOff size={14} /> {loading === 'suppress' ? '…' : 'Bastır'}
            </button>
            <div className="relative">
              <button onClick={() => setShowSnooze(v => !v)} disabled={loading !== null}
                className="flex items-center gap-1.5 text-sm px-3 py-1.5 rounded-lg border border-slate-600 text-slate-400 hover:bg-slate-700 disabled:opacity-50 transition-colors">
                <Clock size={14} /> Ertele <ChevronDown size={12} />
              </button>
              {showSnooze && (
                <div className="absolute top-full left-0 mt-1 z-10 bg-slate-800 border border-slate-700 rounded-xl shadow-xl min-w-[130px] py-1 overflow-hidden">
                  {[[30,'30 dk'],[60,'1 saat'],[120,'2 saat'],[480,'8 saat']].map(([m,l]) => (
                    <button key={m} onClick={() => doSnooze(m as number)}
                      className="w-full text-left text-sm px-4 py-2 text-slate-300 hover:bg-slate-700 transition-colors">
                      {l}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          {/* Metrics */}
          <div>
            <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
              Aktif Alarmlar ({card.metrics.length})
            </h4>
            <div className="space-y-2">
              {card.metrics.map(m => (
                <div key={m.event_id}
                  className={`flex items-center gap-3 p-3 rounded-xl border text-sm ${SEV_RING[m.severity] || 'border-slate-700 bg-slate-800/40'}`}>
                  <span className={`w-2 h-2 rounded-full shrink-0 ${SEV_DOT[m.severity] || 'bg-slate-500'}`} />
                  <span className="flex-1 text-slate-200 truncate">{m.metric}</span>
                  {m.value !== null && (
                    <span className={`font-mono font-semibold ${SEV_TEXT[m.severity]}`}>
                      %{Math.round(m.value)}
                    </span>
                  )}
                  {m.occurrence_count > 1 && (
                    <span className="text-xs text-slate-600">{m.occurrence_count}×</span>
                  )}
                  <span className="text-xs text-slate-600 ml-auto">{relTime(m.last_seen)}</span>
                </div>
              ))}
            </div>
          </div>

          {/* Suggested commands */}
          {card.suggested_actions.length > 0 && (
            <div>
              <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">
                Önerilen Komutlar
              </h4>
              <div className="space-y-2">
                {card.suggested_actions.map((a, i) => (
                  <div key={i} className="flex items-center gap-2 bg-slate-950 border border-slate-800 rounded-lg px-3 py-2 font-mono text-xs text-slate-400">
                    <span className="text-slate-600">$</span>
                    <code className="flex-1 truncate">{a}</code>
                  </div>
                ))}
              </div>
            </div>
          )}

          {/* RCA */}
          <div>
            <button onClick={() => setShowRCA(v => !v)}
              className={`w-full flex items-center justify-between px-4 py-2.5 rounded-xl border text-sm font-medium transition-colors ${
                showRCA
                  ? 'border-cyan-500/50 bg-cyan-500/10 text-cyan-300'
                  : 'border-slate-700 text-slate-400 hover:border-slate-600 hover:text-white'
              }`}>
              <span className="flex items-center gap-2"><ScanSearch size={14} /> AI Kök Neden Analizi</span>
              <ChevronDown size={14} className={`transition-transform ${showRCA ? 'rotate-180' : ''}`} />
            </button>
            {showRCA && (
              <RCAPanel eventIds={card.event_ids} metric={card.metrics[0]?.metric || ''} onClose={() => setShowRCA(false)} />
            )}
          </div>

          {/* Quick links */}
          {card.server.id && (
            <div>
              <h4 className="text-xs font-semibold text-slate-500 uppercase tracking-wider mb-3">Hızlı Erişim</h4>
              <div className="grid grid-cols-2 gap-2">
                <Link to={`/metrics?server=${card.server.id}`}
                  className="flex items-center gap-2 px-3 py-2 rounded-xl border border-slate-700 text-slate-400 hover:text-white hover:border-slate-500 text-sm transition-colors">
                  <BarChart3 size={14} /> Canlı Metrikler
                </Link>
                <Link to={`/servers?id=${card.server.id}`}
                  className="flex items-center gap-2 px-3 py-2 rounded-xl border border-slate-700 text-slate-400 hover:text-white hover:border-slate-500 text-sm transition-colors">
                  <Terminal size={14} /> Terminal
                </Link>
              </div>
            </div>
          )}
        </div>
      </div>
    </>
  )
}

// ── Server Card (compact) ─────────────────────────────────────────────────────
function ServerAlarmCard({
  card, selected, onSelect, onDone, onClick
}: {
  card: ServerCard; selected: boolean
  onSelect: (ids: number[], checked: boolean) => void
  onDone: () => void; onClick: () => void
}) {
  const [loading, setLoading] = useState<string | null>(null)
  const sev = card.max_severity

  async function quickAck(e: React.MouseEvent) {
    e.stopPropagation()
    setLoading('ack')
    try {
      await Promise.all(card.event_ids.map(id =>
        fetch(`${API_BASE_URL}/events/${id}/acknowledge`, { method: 'POST' })
      ))
      onDone()
    } finally { setLoading(null) }
  }

  return (
    <div
      onClick={onClick}
      className={`rounded-2xl border cursor-pointer group transition-all hover:shadow-lg
        ${SEV_RING[sev] || 'border-slate-700 bg-slate-800/30'}
        ${selected ? 'ring-2 ring-cyan-500/50' : ''}
      `}
    >
      <div className="flex items-start gap-3 p-4">
        {/* Checkbox */}
        <input type="checkbox" checked={selected}
          onChange={e => { e.stopPropagation(); onSelect(card.event_ids, e.target.checked) }}
          onClick={e => e.stopPropagation()}
          className="mt-1 shrink-0 accent-cyan-500 cursor-pointer rounded"
        />

        {/* Severity dot */}
        <div className="mt-1.5 shrink-0">
          <span className={`inline-block w-2.5 h-2.5 rounded-full ${SEV_DOT[sev] || 'bg-slate-500'}`} />
        </div>

        <div className="flex-1 min-w-0">
          {/* Header row */}
          <div className="flex items-center gap-2 flex-wrap">
            <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-bold ${TIER_STYLE[card.server.tier]}`}>
              {TIER_SHORT[card.server.tier] || '?'}
            </span>
            <span className="font-semibold text-white text-sm truncate">{card.server.name}</span>
            <span className="text-xs text-slate-500">{card.server.ip}</span>
            <span className={`ml-auto text-[10px] px-1.5 py-0.5 rounded-full border font-semibold ${SEV_BADGE[sev]}`}>
              {sev.toUpperCase()}
            </span>
          </div>

          {/* Metrics list (top 3) */}
          <div className="mt-2.5 space-y-1.5">
            {card.metrics.slice(0, 3).map(m => (
              <div key={m.event_id} className="flex items-center gap-2 text-xs">
                <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                  m.severity === 'critical' ? 'bg-red-400' :
                  m.severity === 'warning' ? 'bg-amber-400' : 'bg-blue-400'
                }`} />
                <span className="text-slate-300 truncate flex-1">{m.metric}</span>
                {m.value !== null && (
                  <span className={`font-mono ${SEV_TEXT[m.severity]}`}>
                    %{Math.round(m.value)}
                  </span>
                )}
                {m.occurrence_count > 1 && <span className="text-slate-600">{m.occurrence_count}×</span>}
                <span className="text-slate-600">{relTime(m.last_seen)}</span>
              </div>
            ))}
            {card.metrics.length > 3 && (
              <span className="text-xs text-slate-600">+{card.metrics.length - 3} daha…</span>
            )}
          </div>

          {/* Quick actions */}
          <div className="flex items-center gap-2 mt-3 opacity-0 group-hover:opacity-100 transition-opacity">
            <button onClick={quickAck}
              disabled={loading !== null}
              className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-blue-500/40 text-blue-300 hover:bg-blue-500/10 disabled:opacity-50 transition-colors">
              {loading === 'ack' ? '…' : <><CheckCircle2 size={11} /> Onayla</>}
            </button>
            <button onClick={e => { e.stopPropagation(); onClick() }}
              className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-slate-600 text-slate-400 hover:bg-slate-700 transition-colors">
              <ArrowRight size={11} /> Detay
            </button>
            <span className="ml-auto text-xs text-slate-600">{relTime(card.last_seen)}</span>
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Storm Card ────────────────────────────────────────────────────────────────
function StormAlarmCard({ storm, selected, onSelect, onDone, platform }: {
  storm: StormCard; selected: boolean
  onSelect: (ids: number[], checked: boolean) => void; onDone: () => void
  platform: string
}) {
  const [showServers, setShowServers] = useState(false)
  const [showRCA, setShowRCA] = useState(false)
  const [loading, setLoading] = useState<string | null>(null)

  async function doAck() {
    setLoading('ack')
    try {
      await Promise.all(storm.event_ids.map(id =>
        fetch(`${API_BASE_URL}/events/${id}/acknowledge`, { method: 'POST' })
      ))
      onDone()
    } finally { setLoading(null) }
  }

  return (
    <div className={`rounded-2xl border border-amber-500/50 bg-amber-500/5 p-4 ${selected ? 'ring-2 ring-cyan-500/50' : ''}`}>
      <div className="flex items-start gap-3">
        <input type="checkbox" checked={selected}
          onChange={e => onSelect(storm.event_ids, e.target.checked)}
          className="mt-1 shrink-0 accent-cyan-500 cursor-pointer" />
        <Zap size={16} className="text-amber-400 shrink-0 mt-0.5" />
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-xs font-bold text-amber-400 bg-amber-500/10 border border-amber-500/30 px-2 py-0.5 rounded-full">
              FIRTINA
            </span>
            <span className="font-semibold text-white truncate">{storm.metric}</span>
            <span className={`ml-auto text-[10px] px-1.5 py-0.5 rounded-full border font-semibold ${SEV_BADGE[storm.severity]}`}>
              {storm.severity.toUpperCase()}
            </span>
          </div>

          <button onClick={() => setShowServers(v => !v)}
            className="mt-2 flex items-center gap-1.5 text-sm text-slate-400 hover:text-amber-300 transition-colors">
            <span className="font-semibold text-amber-300">{storm.server_count}</span> sunucu ·
            <span>{storm.event_count} event</span>
            <ChevronDown size={13} className={`transition-transform ${showServers ? 'rotate-180' : ''}`} />
          </button>

          {showServers && (
            <div className="mt-2 rounded-xl border border-amber-500/20 divide-y divide-amber-500/10 overflow-hidden">
              {storm.affected_servers.map(s => (
                <div key={s.id} className="flex items-center justify-between px-3 py-2">
                  <div className="flex items-center gap-2">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-bold ${TIER_STYLE[s.tier] || TIER_STYLE.unknown}`}>
                      {TIER_SHORT[s.tier] || '?'}
                    </span>
                    <span className="text-sm text-slate-200">{s.name}</span>
                  </div>
                  <span className="text-xs text-slate-500">{s.ip}</span>
                </div>
              ))}
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 mt-3">
            <Link to={`${PLATFORM_AIOPS_PREFIX[platform as keyof typeof PLATFORM_AIOPS_PREFIX] || '/linux'}/incidents`} onClick={e => e.stopPropagation()}
              className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-sky-500/40 text-sky-300 hover:bg-sky-500/10 transition-colors">
              <Siren size={11} /> #{storm.incident_id}
            </Link>
            <button onClick={() => setShowRCA(v => !v)}
              className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10 transition-colors">
              <ScanSearch size={11} /> RCA
            </button>
            <button onClick={doAck} disabled={loading !== null}
              className="flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg border border-blue-500/40 text-blue-300 hover:bg-blue-500/10 disabled:opacity-50 transition-colors">
              <CheckCircle2 size={11} /> {loading === 'ack' ? '…' : `Tümünü Onayla (${storm.event_count})`}
            </button>
            <span className="ml-auto text-xs text-slate-600">{relTime(storm.last_seen)}</span>
          </div>

          {showRCA && (
            <RCAPanel eventIds={storm.event_ids} metric={storm.metric} isStorm onClose={() => setShowRCA(false)} />
          )}
        </div>
      </div>
    </div>
  )
}

// ── Bulk Toolbar ──────────────────────────────────────────────────────────────
function BulkToolbar({ selectedIds, onClear, onDone }: {
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
      onClear(); onDone()
    } finally { setLoading(null) }
  }

  return (
    <div className="sticky top-0 z-20 flex items-center gap-2 bg-slate-900/95 backdrop-blur-sm border border-cyan-500/40 rounded-2xl px-5 py-2.5 shadow-xl">
      <span className="text-sm font-semibold text-cyan-400">{selectedIds.length} alarm seçili</span>
      <div className="flex gap-1.5 ml-3">
        {([
          ['acknowledge', <CheckCircle2 size={13} />, 'Onayla', 'border-blue-500/40 text-blue-300 hover:bg-blue-500/10'],
          ['known', <Eye size={13} />, 'Bilinen', 'border-slate-600 text-slate-400 hover:bg-slate-700'],
          ['suppress', <BellOff size={13} />, 'Bastır', 'border-slate-600 text-slate-400 hover:bg-slate-700'],
          ['snooze', <Clock size={13} />, '1sa Ertele', 'border-slate-600 text-slate-400 hover:bg-slate-700'],
        ] as const).map(([act, icon, label, style]) => (
          <button key={act} onClick={() => doAll(act)} disabled={loading !== null}
            className={`flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-xl border disabled:opacity-50 transition-colors ${style}`}>
            {loading === act ? <div className="w-3 h-3 border border-t-transparent rounded-full animate-spin" /> : icon}
            {label}
          </button>
        ))}
      </div>
      <button onClick={onClear} className="ml-auto flex items-center gap-1 text-xs text-slate-500 hover:text-slate-300 transition-colors">
        <X size={13} /> Seçimi kaldır
      </button>
    </div>
  )
}

// ── Activity Timeline ─────────────────────────────────────────────────────────
function ActivityTimeline({ platform }: { platform: string }) {
  const { data } = useQuery<{ events: EventItem[]; total: number }>({
    queryKey: ['ops-timeline', platform],
    queryFn: async () => {
      // Komuta Merkezi ile aynı actionable set: çözülmemiş + onaylı değil + bilinen değil
      const p = new URLSearchParams({
        resolved: 'false',
        acknowledged: 'false',
        known: 'false',
        limit: '40',
        offset: '0',
        platform,
      })
      const r = await fetch(`${API_BASE_URL}/events/?${p}`)
      if (!r.ok) throw new Error('events fetch failed')
      return r.json()
    },
    refetchInterval: 30_000,
    staleTime: 20_000,
  })

  const events = data?.events ?? []

  const timeLabel = (iso: string | null | undefined) => {
    if (!iso) return '—'
    const t = new Date(iso).getTime()
    if (!Number.isFinite(t)) return '—'
    const rel = relTime(iso)
    if (rel === 'şimdi' || (rel && rel.endsWith('dk'))) return rel
    return new Date(iso).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
  }

  return (
    <div className="flex flex-col h-full">
      <div className="flex-none px-4 py-3 border-b border-slate-800/60">
        <div className="flex items-center gap-2 text-sm font-semibold text-slate-300">
          <Activity size={14} className="text-cyan-400" /> Son Aktivite
        </div>
        <div className="text-xs text-slate-600 mt-0.5">{events.length} açık alarm</div>
      </div>
      <div className="flex-1 overflow-y-auto">
        {events.length === 0 ? (
          <div className="text-center py-12 text-slate-600 text-sm">Aktif alarm yok</div>
        ) : (
          <div className="relative px-4 py-3">
            {/* Vertical line */}
            <div className="absolute left-[27px] top-3 bottom-3 w-px bg-slate-800" />
            <div className="space-y-2">
              {events.map(ev => (
                <div key={ev.id} className="flex items-start gap-3 relative">
                  {/* Dot */}
                  <div className={`flex-none w-3 h-3 rounded-full mt-1.5 z-10 border-2 border-slate-900 ${
                    ev.severity === 'critical' || ev.severity === 'emergency' ? 'bg-red-400' :
                    ev.severity === 'warning' ? 'bg-amber-400' : 'bg-blue-400'
                  }`} />
                  <div className="flex-1 min-w-0 pb-2">
                    <div className="flex items-start justify-between gap-2">
                      <span className="text-xs text-slate-300 leading-tight line-clamp-2">{ev.title}</span>
                      <span className="text-[10px] text-slate-600 shrink-0 mt-0.5">{timeLabel(eventWhen(ev))}</span>
                    </div>
                    {ev.server_name && (
                      <span className="text-[10px] text-slate-600">{ev.server_name}</span>
                    )}
                    {ev.occurrence_count > 1 && (
                      <span className="text-[10px] text-slate-700 ml-2">{ev.occurrence_count}×</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

// ── İşlenen (onaylı / bilinen / çözülen) alarm listesi ────────────────────────
interface HandledEvent {
  id: number; title: string; severity: string; event_type: string
  handle_status: 'acknowledged' | 'known' | 'resolved'
  server_name: string; server_ip: string
  occurrence_count: number; last_seen: string | null
}

const HANDLE_LABEL: Record<string, { text: string; cls: string }> = {
  acknowledged: { text: 'Onaylandı', cls: 'bg-blue-500/20 text-blue-300 border-blue-500/40' },
  known: { text: 'Bilinen', cls: 'bg-slate-500/20 text-slate-300 border-slate-500/40' },
  resolved: { text: 'Kapatıldı', cls: 'bg-green-500/20 text-green-300 border-green-500/40' },
}

function HandledEventsPanel({
  platform, statusFilter, search, onDone,
}: {
  platform: string
  statusFilter: '' | 'acknowledged' | 'known' | 'resolved'
  search: string
  onDone: () => void
}) {
  const [busyId, setBusyId] = useState<number | null>(null)

  const { data, isLoading, refetch } = useQuery<{
    counts: { acknowledged: number; known: number; resolved: number; total: number }
    events: HandledEvent[]
    total: number
  }>({
    queryKey: ['ops-handled', platform, statusFilter, search],
    queryFn: async () => {
      const p = new URLSearchParams({ platform, limit: '150' })
      if (statusFilter) p.set('status', statusFilter)
      if (search) p.set('search', search)
      const r = await fetch(`${API_BASE_URL}/ops/handled-events?${p}`)
      if (!r.ok) throw new Error('handled-events error')
      return r.json()
    },
    refetchInterval: 30_000,
  })

  async function reopen(ev: HandledEvent) {
    setBusyId(ev.id)
    try {
      if (ev.handle_status === 'acknowledged') {
        await fetch(`${API_BASE_URL}/events/${ev.id}/unacknowledge`, { method: 'POST' })
      } else if (ev.handle_status === 'known') {
        await fetch(`${API_BASE_URL}/events/${ev.id}/unknown`, { method: 'POST' })
      } else if (ev.handle_status === 'resolved') {
        await fetch(`${API_BASE_URL}/events/${ev.id}/unresolve`, { method: 'POST' })
      }
      await refetch()
      onDone()
    } finally { setBusyId(null) }
  }

  if (isLoading) {
    return (
      <div className="flex justify-center py-16">
        <div className="w-8 h-8 rounded-full border-2 border-t-cyan-400 border-r-transparent animate-spin" />
      </div>
    )
  }

  const events = data?.events ?? []
  const counts = data?.counts

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 flex-wrap text-xs text-slate-400">
        <span>Son 24 saatte işlenen alarmlar</span>
        {counts && (
          <span className="text-slate-600">
            · Onay {counts.acknowledged} · Bilinen {counts.known} · Kapatılan {counts.resolved}
          </span>
        )}
      </div>
      {events.length === 0 ? (
        <div className="flex flex-col items-center py-16 text-center text-slate-500">
          <CheckCircle2 size={40} className="text-slate-600 mb-3" />
          <p className="text-sm">Bu filtrede işlenen alarm yok.</p>
        </div>
      ) : (
        <div className="space-y-2">
          {events.map(ev => {
            const badge = HANDLE_LABEL[ev.handle_status] || HANDLE_LABEL.acknowledged
            return (
              <div key={ev.id}
                className="rounded-xl border border-slate-700/60 bg-slate-900/50 px-4 py-3 flex items-start gap-3">
                <span className={`mt-0.5 w-2 h-2 rounded-full shrink-0 ${
                  ev.severity === 'critical' || ev.severity === 'emergency' ? 'bg-red-400'
                    : ev.severity === 'warning' ? 'bg-amber-400' : 'bg-slate-500'
                }`} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 flex-wrap mb-0.5">
                    <span className={`text-[10px] px-1.5 py-0.5 rounded-full border font-medium ${badge.cls}`}>
                      {badge.text}
                    </span>
                    <span className="text-[10px] text-slate-500 font-mono">{ev.event_type}</span>
                    {ev.occurrence_count > 1 && (
                      <span className="text-[10px] text-slate-500">×{ev.occurrence_count}</span>
                    )}
                  </div>
                  <p className="text-sm text-slate-200 truncate" title={ev.title}>{ev.title}</p>
                  <p className="text-xs text-slate-500 mt-0.5">
                    {ev.server_name}{ev.server_ip ? ` · ${ev.server_ip}` : ''}
                    {ev.last_seen ? ` · ${relTime(ev.last_seen)} önce` : ''}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={busyId === ev.id}
                  onClick={() => reopen(ev)}
                  className="shrink-0 text-xs px-2.5 py-1.5 rounded-lg border border-cyan-500/40 text-cyan-300 hover:bg-cyan-500/10 disabled:opacity-50"
                  title="Aktif alarmlara geri al"
                >
                  {busyId === ev.id ? '…' : 'Yeniden aç'}
                </button>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}

// ── Ana Sayfa ─────────────────────────────────────────────────────────────────
export default function OpsCenter({ platform = 'linux' }: PlatformAiopsProps) {
  const qc = useQueryClient()
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [tierFilter, setTierFilter] = useState<'all' | 'production' | 'staging' | 'development'>('all')
  const [sevFilter, setSevFilter] = useState<'all' | 'critical' | 'warning'>('all')
  const [search, setSearch] = useState('')
  const [detailCard, setDetailCard] = useState<ServerCard | null>(null)
  const [viewMode, setViewMode] = useState<'active' | 'handled'>('active')
  const [handledStatus, setHandledStatus] = useState<'' | 'acknowledged' | 'known' | 'resolved'>('')
  const [metricFilter, setMetricFilter] = useState<'all' | 'cpu' | 'memory' | 'disk' | 'network'>('all')

  const { data, isLoading, refetch } = useQuery<CommandCenterData>({
    queryKey: ['ops-command-center', platform],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/ops/command-center?platform=${platform}`)
      if (!r.ok) throw new Error('ops/command-center error')
      return r.json()
    },
    refetchInterval: 30_000,
    staleTime: 25_000,
  })

  function invalidate() {
    setSelectedIds(new Set())
    qc.invalidateQueries({ queryKey: ['ops-command-center'] })
    qc.invalidateQueries({ queryKey: ['ops-timeline', platform] })
    qc.invalidateQueries({ queryKey: ['ops-handled'] })
    // Navbar rozetleri (Linux/Windows/…) anında güncellensin
    qc.invalidateQueries({ queryKey: ['ops-summary-nav'] })
    qc.invalidateQueries({ queryKey: ['windows-ops-summary'] })
    qc.invalidateQueries({ queryKey: ['virt-ops-summary'] })
    qc.invalidateQueries({ queryKey: ['exadata-ops-summary'] })
    qc.invalidateQueries({ queryKey: ['eventStats'] })
  }

  function toggleSelect(ids: number[], checked: boolean) {
    setSelectedIds(prev => {
      const next = new Set(prev)
      ids.forEach(id => checked ? next.add(id) : next.delete(id))
      return next
    })
  }

  const metricBreakdown = useMemo(() => {
    const all = [
      ...(data?.critical_servers ?? []).flatMap(s => s.metrics),
      ...(data?.warning_servers ?? []).flatMap(s => s.metrics),
    ]
    const counts = { cpu: 0, memory: 0, disk: 0, network: 0, other: 0 }
    const critCounts = { cpu: 0, memory: 0, disk: 0, network: 0, other: 0 }
    const seen = new Set<number>()
    all.forEach(m => {
      // Aynı event birden fazla satırda gelmesin
      if (m.event_id && seen.has(m.event_id)) return
      if (m.event_id) seen.add(m.event_id)
      const cat = metricCategory(m.metric)
      counts[cat]++
      if (m.severity === 'critical' || m.severity === 'emergency') critCounts[cat]++
    })
    return { counts, critCounts }
  }, [data])

  const filterCards = useCallback((cards: ServerCard[], opts?: { ignoreSev?: boolean }) =>
    cards.filter(c => {
      if (tierFilter !== 'all' && c.server.tier !== tierFilter) return false
      // Kritik/uyarı kovaları zaten ayrılmış; sevFilter kovayı seçer, max_severity ile tekrar eleme
      // (emergency / production-warning kartlarını gizlemesin).
      if (!opts?.ignoreSev && sevFilter !== 'all' && c.max_severity !== sevFilter
        && !(sevFilter === 'critical' && c.max_severity === 'emergency')) return false
      if (metricFilter !== 'all' && !c.metrics.some(m => metricCategory(m.metric) === metricFilter)) return false
      if (search && !c.server.name.toLowerCase().includes(search.toLowerCase())
        && !c.server.ip.includes(search)
        && !c.metrics.some(m => m.metric.toLowerCase().includes(search.toLowerCase()))) return false
      return true
    }),
    [tierFilter, sevFilter, search, metricFilter]
  )

  const critFiltered = useMemo(() => {
    if (sevFilter === 'warning') return []
    return filterCards(data?.critical_servers ?? [], { ignoreSev: true })
  }, [data, filterCards, sevFilter])
  const warnFiltered = useMemo(() => {
    if (sevFilter === 'critical') return []
    return filterCards(data?.warning_servers ?? [], { ignoreSev: true })
  }, [data, filterCards, sevFilter])

  const kpiCritical = data?.event_critical ?? ((data?.critical_count ?? 0) + (data?.storm_count ?? 0))
  const kpiWarning = data?.event_warning ?? (data?.warning_count ?? 0)
  const allOk = !kpiCritical && !kpiWarning

  return (
    <>
      <OpsShell
        platform={platform}
        loading={isLoading}
        health={data?.health ? { score: data.health.score, label: data.health.label } : null}
        kpi={{
          critical: kpiCritical,
          warning: kpiWarning,
          tertiaryValue: data?.green_count ?? 0,
          tertiaryLabel: 'İşlenen',
          onCriticalClick: () => { setViewMode('active'); setSevFilter('critical') },
          onWarningClick: () => { setViewMode('active'); setSevFilter('warning') },
          onTertiaryClick: () => { setViewMode(v => v === 'handled' ? 'active' : 'handled'); setHandledStatus('') },
          criticalActive: viewMode === 'active' && sevFilter === 'critical',
          warningActive: viewMode === 'active' && sevFilter === 'warning',
          tertiaryActive: viewMode === 'handled',
        }}
        headerActions={(
          <>
            <span className="text-xs text-slate-600 hidden sm:block">
              {relTime(data?.generated_at ?? null)} önce güncellendi
            </span>
            <OpsRefreshCountdown onRefresh={() => { refetch(); invalidate() }} interval={30} />
          </>
        )}
        metaRow={(
          <div className="flex gap-3 w-full basis-full order-last">
            {[
              { key: 'cpu', icon: <Cpu size={14} />, label: 'CPU', color: 'text-orange-400' },
              { key: 'memory', icon: <MemoryStick size={14} />, label: 'RAM', color: 'text-sky-400' },
              { key: 'disk', icon: <HardDrive size={14} />, label: 'Disk', color: 'text-blue-400' },
              { key: 'network', icon: <Network size={14} />, label: 'Ağ', color: 'text-teal-400' },
            ].map(({ key, icon, label, color }) => (
              <MetricWidget
                key={key}
                icon={icon}
                label={label}
                color={color}
                count={(metricBreakdown.counts as any)[key]}
                critCount={(metricBreakdown.critCounts as any)[key]}
                active={metricFilter === key}
                onClick={() => {
                  setViewMode('active')
                  setMetricFilter(prev => prev === key ? 'all' : key as typeof metricFilter)
                }}
              />
            ))}
          </div>
        )}
        filterBar={(
          <>
            <div className="flex gap-1 mr-1">
              {([
                ['active', 'Aktif'],
                ['handled', 'İşlenen'],
              ] as const).map(([mode, label]) => (
                <button
                  key={mode}
                  type="button"
                  onClick={() => setViewMode(mode)}
                  className={`text-xs px-3 py-1.5 rounded-xl border transition-colors ${
                    viewMode === mode
                      ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-300'
                      : 'border-slate-700 text-slate-500 hover:text-slate-300 hover:border-slate-600'
                  }`}
                >
                  {label}
                </button>
              ))}
            </div>
            <div className="relative flex-1 min-w-[12rem] max-w-md">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-slate-500" />
              <input
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder={viewMode === 'handled' ? 'İşlenen alarm veya sunucu ara…' : 'Sunucu, IP veya metrik ara…'}
                className="w-full bg-slate-800 border border-slate-700 text-white text-sm rounded-xl pl-9 pr-8 py-2 focus:outline-none focus:ring-2 focus:ring-cyan-500/50 placeholder-slate-600"
              />
              {search && (
                <button type="button" onClick={() => setSearch('')} className="absolute right-2 top-1/2 -translate-y-1/2 text-slate-500 hover:text-white">
                  <X size={13} />
                </button>
              )}
            </div>
            {viewMode === 'handled' ? (
              <div className="flex gap-1">
                {([
                  ['', 'Tümü'],
                  ['acknowledged', 'Onaylanan'],
                  ['known', 'Bilinen'],
                  ['resolved', 'Kapatılan'],
                ] as const).map(([st, label]) => (
                  <button
                    key={st || 'all'}
                    type="button"
                    onClick={() => setHandledStatus(st)}
                    className={`text-xs px-3 py-1.5 rounded-xl border transition-colors ${
                      handledStatus === st
                        ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-300'
                        : 'border-slate-700 text-slate-500 hover:text-slate-300 hover:border-slate-600'
                    }`}
                  >
                    {label}
                  </button>
                ))}
              </div>
            ) : (
              <>
                <div className="flex gap-1">
                  {(['all', 'production', 'staging', 'development'] as const).map(t => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setTierFilter(t)}
                      className={`text-xs px-3 py-1.5 rounded-xl border transition-colors ${
                        tierFilter === t
                          ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-300'
                          : 'border-slate-700 text-slate-500 hover:text-slate-300 hover:border-slate-600'
                      }`}
                    >
                      {t === 'all' ? 'Tümü' : TIER_SHORT[t]}
                    </button>
                  ))}
                </div>
                <div className="flex gap-1">
                  {(['all', 'critical', 'warning'] as const).map(s => (
                    <button
                      key={s}
                      type="button"
                      onClick={() => setSevFilter(s)}
                      className={`text-xs px-3 py-1.5 rounded-xl border transition-colors ${
                        sevFilter === s
                          ? 'border-cyan-500/60 bg-cyan-500/10 text-cyan-300'
                          : 'border-slate-700 text-slate-500 hover:text-slate-300 hover:border-slate-600'
                      }`}
                    >
                      {s === 'all' ? 'Tüm Seviye' : s === 'critical' ? 'Kritik' : 'Uyarı'}
                    </button>
                  ))}
                </div>
              </>
            )}
          </>
        )}
        sideRail={<ActivityTimeline platform={platform} />}
      >
        {viewMode === 'handled' ? (
          <HandledEventsPanel
            platform={platform}
            statusFilter={handledStatus}
            search={search}
            onDone={invalidate}
          />
        ) : (
          <>
        {selectedIds.size > 0 && (
          <BulkToolbar selectedIds={[...selectedIds]} onClear={() => setSelectedIds(new Set())} onDone={invalidate} />
        )}

        {allOk && !search && sevFilter === 'all' && tierFilter === 'all' && (
          <div className="flex flex-col items-center justify-center py-20 text-center">
            <CheckCircle2 size={48} className="text-green-400 mb-4" />
            <h3 className="text-xl font-semibold text-green-400">Her şey yolunda</h3>
            <p className="text-sm text-slate-400 mt-2">Son 24 saatte müdahale gerektiren alarm yok.</p>
            {(data?.green_count ?? 0) > 0 && (
              <button
                type="button"
                onClick={() => setViewMode('handled')}
                className="mt-4 text-sm text-cyan-400 hover:underline"
              >
                {data!.green_count} işlenen alarmı gör →
              </button>
            )}
          </div>
        )}

        {(data?.storms?.length ?? 0) > 0 && (
          <section>
            <div className="flex items-center gap-2 mb-3">
              <Zap size={14} className="text-amber-400" />
              <h2 className="text-xs font-semibold text-amber-400 uppercase tracking-wider">
                Alarm Fırtınaları — {data!.storms.length}
              </h2>
            </div>
            <div className="space-y-3">
              {data!.storms.map(s => (
                <StormAlarmCard
                  key={s.incident_id}
                  storm={s}
                  platform={platform}
                  selected={s.event_ids.every(id => selectedIds.has(id))}
                  onSelect={toggleSelect}
                  onDone={invalidate}
                />
              ))}
            </div>
          </section>
        )}

        {critFiltered.length > 0 && (
          <section>
            <div className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-red-400 animate-pulse" />
              <h2 className="text-xs font-semibold text-red-400 uppercase tracking-wider">
                Hemen Bak — {critFiltered.length} sunucu
              </h2>
            </div>
            <div className="space-y-2">
              {critFiltered.map(c => (
                <ServerAlarmCard
                  key={`${c.server.id}-${c.last_seen}`}
                  card={c}
                  selected={c.event_ids.every(id => selectedIds.has(id))}
                  onSelect={toggleSelect}
                  onDone={invalidate}
                  onClick={() => setDetailCard(c)}
                />
              ))}
            </div>
          </section>
        )}

        {warnFiltered.length > 0 && (
          <section>
            <div className="flex items-center gap-2 mb-3">
              <span className="w-2 h-2 rounded-full bg-amber-400" />
              <h2 className="text-xs font-semibold text-amber-400 uppercase tracking-wider">
                İzle — {warnFiltered.length} sunucu
              </h2>
            </div>
            <div className="space-y-2">
              {warnFiltered.map(c => (
                <ServerAlarmCard
                  key={`${c.server.id}-${c.last_seen}`}
                  card={c}
                  selected={c.event_ids.every(id => selectedIds.has(id))}
                  onSelect={toggleSelect}
                  onDone={invalidate}
                  onClick={() => setDetailCard(c)}
                />
              ))}
            </div>
          </section>
        )}

        {(critFiltered.length === 0 && warnFiltered.length === 0 && (search || sevFilter !== 'all' || tierFilter !== 'all')) && (
          <div className="text-center py-16 text-slate-600">
            <Search size={32} className="mx-auto mb-3 opacity-30" />
            <p className="text-sm">Filtre kriterlerine uyan alarm yok.</p>
          </div>
        )}
          </>
        )}
      </OpsShell>

      {detailCard && (
        <ServerDetailPanel
          card={detailCard}
          onClose={() => setDetailCard(null)}
          onDone={invalidate}
        />
      )}
    </>
  )
}
