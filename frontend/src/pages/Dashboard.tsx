import React, { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
  BarChart, Bar, XAxis, YAxis, CartesianGrid, RadialBarChart, RadialBar,
  AreaChart, Area,
} from 'recharts'
import { ShieldOff } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { ServerDetailDrawer } from './Servers'
import { useAuth } from '../auth/AuthContext'

// ── Types ────────────────────────────────────────────────────────────────────
interface DashboardServer {
  id: number; name: string; hostname: string; ip_address: string
  status: string; ai_ready: boolean; cpu_cores: number; memory_gb: number
  os_type: string; os_version?: string; server_type?: string
  connection_config?: any; node_exporter?: { installed: boolean; running: boolean }
  created_at?: string
}
interface Hypervisor { id: number; name: string; type: string; ip_address: string }
interface EsxHost {
  host_name: string; host_ref?: string; last_updated?: string
  cpu_usage_pct: number | null; cpu_usage_mhz: number | null; cpu_total_mhz: number | null
  cpu_cores: number | null; mem_used_mb: number | null; mem_total_mb: number | null
  mem_usage_pct: number | null; ds_used_gb: number | null; ds_total_gb: number | null
  ds_usage_pct: number | null; vms_running: number | null; vms_total: number | null
  connection_state: string | null; power_state: string | null; maintenance_mode: number | null
}
interface EsxHostMetricsResponse {
  hypervisor_id: number; hypervisor_name: string; host_count: number; hosts: EsxHost[]
}
interface EventStats {
  total: number; unresolved: number; critical: number; warning: number
  emergency: number; acknowledged: number; known: number
}
interface IncidentStats {
  total: number; open: number; investigating: number; resolved: number; critical: number
}
interface MetricServerRow {
  server_id: number; hostname: string; ip_address: string
  cpu_usage: number | null; memory_usage: number | null; disk_usage: number | null
  last_update: string | null
}
interface MetricDashboard { total_servers: number; servers: MetricServerRow[] }
interface FeedEvent {
  id: number; title: string; severity: string; server_name?: string
  created_at?: string; resolved: boolean
}

export type DashboardScope = 'admin' | 'linux' | 'windows'

function isWindowsOs(s: DashboardServer) {
  return (s.os_type || '').toLowerCase().includes('windows')
}

// ── Design tokens (aligned with DESIGN.md) ────────────────────────────────
const NEON = {
  cyan:   '#38bdf8', blue:   '#3b82f6', purple: '#3b82f6',
  green:  '#22c55e', orange: '#f59e0b', red:    '#ef4444', pink: '#f59e0b',
}

// ── Neon Stat Card ────────────────────────────────────────────────────────
function StatCard({
  label, value, sub, icon, accent, delay = 0
}: {
  label: string; value: string | number; sub?: string
  icon?: React.ReactNode; accent: string; delay?: number
}) {
  return (
    <div
      className="stat-card animate-fade-in"
      style={{
        '--accent-color': accent,
        animationDelay: `${delay}ms`,
        background: 'var(--bg-surface)',
        border: `1px solid rgba(${hexToRgb(accent)}, 0.18)`,
        borderRadius: 12,
        padding: '18px 20px',
        position: 'relative',
        overflow: 'hidden',
        transition: 'border-color 0.15s',
      } as React.CSSProperties}
      onMouseEnter={e => {
        e.currentTarget.style.borderColor = `rgba(${hexToRgb(accent)}, 0.4)`
      }}
      onMouseLeave={e => {
        e.currentTarget.style.borderColor = `rgba(${hexToRgb(accent)}, 0.18)`
      }}
    >

      <div className="flex items-start justify-between relative z-10">
        <div>
          <p className="text-xs font-medium tracking-wider uppercase mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>
            {label}
          </p>
          <p className="text-3xl font-bold text-white count-up leading-none">{value}</p>
          {sub && <p className="text-xs mt-1.5" style={{ color: `${accent}99` }}>{sub}</p>}
        </div>
        <div
          className="w-11 h-11 rounded-xl flex items-center justify-center flex-shrink-0"
          style={{ background: `rgba(${hexToRgb(accent)}, 0.12)`, color: accent }}
        >
          {icon ?? <DonutGauge pct={Math.min(100, typeof value === 'number' ? value : 50)} color={accent} size={36} strokeWidth={4} />}
        </div>
      </div>
    </div>
  )
}

function hexToRgb(hex: string): string {
  const r = parseInt(hex.slice(1,3), 16)
  const g = parseInt(hex.slice(3,5), 16)
  const b = parseInt(hex.slice(5,7), 16)
  return `${r},${g},${b}`
}

// ── Animated Donut ─────────────────────────────────────────────────────────
function DonutGauge({
  pct, color, size = 80, strokeWidth = 8, label
}: {
  pct: number; color: string; size?: number; strokeWidth?: number; label?: string
}) {
  const r = (size - strokeWidth) / 2
  const circ = 2 * Math.PI * r
  const dash = (pct / 100) * circ

  const getColor = (p: number) => p >= 90 ? NEON.red : p >= 75 ? NEON.orange : color

  return (
    <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} style={{ transform: 'rotate(-90deg)' }}>
        {/* Track */}
        <circle
          cx={size/2} cy={size/2} r={r}
          fill="none" stroke="rgba(255,255,255,0.05)" strokeWidth={strokeWidth}
        />
        {/* Glow layer */}
        <circle
          cx={size/2} cy={size/2} r={r}
          fill="none" stroke={getColor(pct)}
          strokeWidth={strokeWidth + 4}
          strokeDasharray={`${dash} ${circ}`}
          strokeLinecap="round"
          opacity={0.15}
        />
        {/* Main arc */}
        <circle
          cx={size/2} cy={size/2} r={r}
          fill="none" stroke={getColor(pct)}
          strokeWidth={strokeWidth}
          strokeDasharray={`${dash} ${circ}`}
          strokeLinecap="round"
          style={{ transition: 'stroke-dasharray 0.8s cubic-bezier(0.4,0,0.2,1)' }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-sm font-bold text-white leading-none">{pct.toFixed(0)}%</span>
        {label && <span className="text-[9px] mt-0.5" style={{ color: 'rgba(148,163,184,0.6)' }}>{label}</span>}
      </div>
    </div>
  )
}

// ── ESX Host Card ──────────────────────────────────────────────────────────
function EsxHostCard({ hvName, host }: { hvName: string; host: EsxHost }) {
  const inMaint = host.maintenance_mode === 1
  const disconnected = host.connection_state === 'disconnected' || host.connection_state === 'notResponding'
  const shortName = host.host_name.split('.')[0]
  const cpuPct = host.cpu_usage_pct ?? (host.cpu_usage_mhz && host.cpu_total_mhz ? (host.cpu_usage_mhz / host.cpu_total_mhz) * 100 : 0)
  const ramPct = host.mem_usage_pct ?? (host.mem_used_mb && host.mem_total_mb ? (host.mem_used_mb / host.mem_total_mb) * 100 : 0)
  const dskPct = host.ds_usage_pct ?? (host.ds_used_gb && host.ds_total_gb ? (host.ds_used_gb / host.ds_total_gb) * 100 : 0)

  return (
    <div
      className="cyber-card p-4 animate-fade-in"
      style={{ opacity: disconnected ? 0.6 : 1 }}
    >
      {/* Header */}
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <div
            className="w-2 h-2 rounded-full"
            style={{
              background: disconnected ? NEON.red : inMaint ? NEON.orange : NEON.green,
              boxShadow: `0 0 6px ${disconnected ? NEON.red : inMaint ? NEON.orange : NEON.green}`,
            }}
          />
          <span className="font-semibold text-white text-sm">{shortName}</span>
          <span className="text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>{hvName}</span>
          {inMaint && (
            <span className="px-1.5 py-0.5 rounded text-[10px] font-medium"
              style={{ background: 'rgba(245,158,11,0.15)', color: NEON.orange, border: '1px solid rgba(245,158,11,0.3)' }}>
              Bakım
            </span>
          )}
        </div>
        {host.vms_running != null && (
          <span className="text-xs font-medium px-2 py-0.5 rounded"
            style={{ background: 'rgba(34,211,238,0.08)', color: NEON.cyan, border: '1px solid rgba(34,211,238,0.2)' }}>
            {host.vms_running}/{host.vms_total ?? '?'} VM
          </span>
        )}
      </div>

      {/* Gauges row */}
      <div className="flex items-center justify-around">
        <div className="flex flex-col items-center gap-1.5">
          <DonutGauge pct={cpuPct} color={NEON.blue} size={68} strokeWidth={6} />
          <span className="text-[10px] text-slate-500 font-medium">CPU</span>
          {host.cpu_total_mhz != null && (
            <span className="text-[9px] text-slate-600">
              {host.cpu_total_mhz >= 1000 ? `${(host.cpu_total_mhz/1000).toFixed(1)}G` : `${host.cpu_total_mhz}M`}
            </span>
          )}
        </div>
        <div className="flex flex-col items-center gap-1.5">
          <DonutGauge pct={ramPct} color={NEON.blue} size={68} strokeWidth={6} />
          <span className="text-[10px] text-slate-500 font-medium">RAM</span>
          {host.mem_total_mb != null && (
            <span className="text-[9px] text-slate-600">{(host.mem_total_mb/1024).toFixed(0)}GB</span>
          )}
        </div>
        <div className="flex flex-col items-center gap-1.5">
          <DonutGauge pct={dskPct} color={NEON.green} size={68} strokeWidth={6} />
          <span className="text-[10px] text-slate-500 font-medium">Disk</span>
          {host.ds_total_gb != null && (
            <span className="text-[9px] text-slate-600">
              {host.ds_total_gb >= 1024 ? `${(host.ds_total_gb/1024).toFixed(1)}T` : `${host.ds_total_gb.toFixed(0)}G`}
            </span>
          )}
        </div>
      </div>

      {/* Last updated */}
      {host.last_updated && (
        <p className="text-[10px] text-slate-600 text-center mt-3">
          {new Date(host.last_updated).toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })} güncellendi
        </p>
      )}
    </div>
  )
}

// ── ESX Panel ──────────────────────────────────────────────────────────────
function EsxResourcePanel({ hypervisors }: { hypervisors: Hypervisor[] }) {
  const vmwareHvs = hypervisors.filter(hv => hv.type?.toLowerCase() === 'vmware')
  const [allHosts, setAllHosts] = useState<{ hvName: string; host: EsxHost }[]>([])
  const [isLoading, setIsLoading] = useState(true)

  const load = () => {
    if (vmwareHvs.length === 0) { setIsLoading(false); return }
    Promise.all(
      vmwareHvs.map(hv =>
        fetch(`${API_BASE_URL}/hypervisors/${hv.id}/host-metrics`)
          .then(r => r.ok ? r.json() : null)
          .then((data: EsxHostMetricsResponse | null) =>
            (data?.hosts || []).map(h => ({ hvName: hv.name, host: h })))
          .catch(() => [] as { hvName: string; host: EsxHost }[])
      )
    ).then(results => { setAllHosts(results.flat()); setIsLoading(false) })
  }

  useEffect(() => {
    load()
    const t = setInterval(load, 15 * 60 * 1000)
    return () => clearInterval(t)
  }, [hypervisors.map(h => h.id).join(',')])

  if (vmwareHvs.length === 0) return null

  return (
    <div className="cyber-card">
      <div className="px-5 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center gap-3">
          <div
            className="w-8 h-8 rounded-lg flex items-center justify-center"
            style={{ background: 'rgba(59,130,246,0.15)', color: NEON.blue }}
          >
            <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-4 h-4">
              <rect x="2" y="3" width="20" height="5" rx="1"/><rect x="2" y="10" width="20" height="5" rx="1"/>
              <rect x="2" y="17" width="20" height="5" rx="1"/>
            </svg>
          </div>
          <div>
            <h2 className="text-sm font-semibold text-white">ESX Host Kaynak Durumu</h2>
            <p className="text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>15 dakikada bir güncellenir</p>
          </div>
        </div>
        {isLoading && (
          <div className="flex items-center gap-2 text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>
            <div className="animate-spin rounded-full h-3 w-3 border border-b-cyan-400 border-white/[0.06]" />
            Yükleniyor...
          </div>
        )}
      </div>

      {!allHosts.length && !isLoading ? (
        <div className="px-5 py-10 text-center" style={{ color: 'rgba(148,163,184,0.4)' }}>
          <p className="text-sm">Henüz ESX host metrik verisi yok.</p>
          <p className="text-xs mt-1" style={{ color: 'rgba(148,163,184,0.25)' }}>İlk veri 15 dakika içinde toplanacak.</p>
        </div>
      ) : (
        <div className="p-4 grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
          {allHosts.map(({ hvName, host }) => (
            <EsxHostCard key={`${hvName}-${host.host_name}`} hvName={hvName} host={host} />
          ))}
        </div>
      )}
    </div>
  )
}

// ── Server Status Donut ────────────────────────────────────────────────────
function ServerStatusChart({
  online, offline, warning
}: { online: number; offline: number; warning: number }) {
  const total = online + offline + warning
  if (total === 0) return null

  const data = [
    { name: 'Online', value: online, color: NEON.green },
    { name: 'Offline', value: offline, color: '#334155' },
    { name: 'Uyarı', value: warning, color: NEON.orange },
  ].filter(d => d.value > 0)

  const CustomTooltip = ({ active, payload }: any) => {
    if (!active || !payload?.length) return null
    const d = payload[0].payload
    return (
      <div className="cyber-card px-3 py-2 text-xs">
        <span style={{ color: d.color }}>{d.name}: </span>
        <span className="text-white font-bold">{d.value}</span>
      </div>
    )
  }

  return (
    <div className="cyber-card p-5 animate-fade-in">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-1.5 h-4 rounded-full" style={{ background: NEON.cyan }} />
        <h2 className="text-sm font-semibold text-white">Sunucu Durumu</h2>
      </div>

      <div className="flex items-center gap-6">
        <div className="relative">
          <ResponsiveContainer width={120} height={120}>
            <PieChart>
              <Pie
                data={data} cx="50%" cy="50%"
                innerRadius={35} outerRadius={55}
                paddingAngle={3} dataKey="value" startAngle={90} endAngle={-270}
              >
                {data.map((entry, i) => (
                  <Cell key={i} fill={entry.color}
                    style={{ filter: `drop-shadow(0 0 4px ${entry.color}80)` }} />
                ))}
              </Pie>
              <Tooltip content={<CustomTooltip />} />
            </PieChart>
          </ResponsiveContainer>
          <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
            <span className="text-2xl font-bold text-white">{total}</span>
            <span className="text-[10px] text-slate-500">toplam</span>
          </div>
        </div>

        <div className="space-y-3 flex-1">
          {[
            { label: 'Çevrimiçi',  value: online,  color: NEON.green, pct: (online/total)*100 },
            { label: 'Çevrimdışı', value: offline, color: '#64748b',  pct: (offline/total)*100 },
            { label: 'Uyarı',      value: warning, color: NEON.orange,pct: (warning/total)*100 },
          ].map(row => (
            <div key={row.label}>
              <div className="flex justify-between items-center mb-1">
                <div className="flex items-center gap-1.5">
                  <div className="w-2 h-2 rounded-full" style={{ background: row.color }} />
                  <span className="text-xs text-slate-400">{row.label}</span>
                </div>
                <span className="text-xs font-medium text-white">{row.value}</span>
              </div>
              <div className="h-1 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.05)' }}>
                <div
                  className="h-full rounded-full transition-all duration-700"
                  style={{
                    width: `${row.pct}%`,
                    background: row.color,
                    boxShadow: `0 0 6px ${row.color}80`,
                  }}
                />
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

// ── OS Distribution ────────────────────────────────────────────────────────
function OsDistChart({ servers }: { servers: DashboardServer[] }) {
  const osCounts: Record<string, { count: number; color: string }> = {}
  const osColors: Record<string, string> = {
    rhel: NEON.red, centos: NEON.blue, ubuntu: NEON.orange,
    debian: NEON.orange, rocky: NEON.blue, oracle: NEON.cyan, windows: NEON.blue,
  }

  servers.forEach(s => {
    const key = (s.os_type || 'unknown').toLowerCase().replace(/\s+/g, '')
    const shortKey = Object.keys(osColors).find(k => key.includes(k)) || 'linux'
    const col = osColors[shortKey] || NEON.cyan
    if (!osCounts[shortKey]) osCounts[shortKey] = { count: 0, color: col }
    osCounts[shortKey].count++
  })

  const data = Object.entries(osCounts).map(([name, { count, color }]) => ({ name, count, color }))
  if (data.length === 0) return null

  return (
    <div className="cyber-card p-5 animate-fade-in">
      <div className="flex items-center gap-2 mb-4">
        <div className="w-1.5 h-4 rounded-full" style={{ background: NEON.blue }} />
        <h2 className="text-sm font-semibold text-white">OS Dağılımı</h2>
      </div>
      <div className="space-y-2.5">
        {data.sort((a,b) => b.count - a.count).map(d => {
          const maxCount = Math.max(...data.map(x => x.count))
          return (
            <div key={d.name} className="flex items-center gap-3">
              <span className="text-xs text-slate-400 w-16 truncate capitalize">{d.name}</span>
              <div className="flex-1 h-5 rounded" style={{ background: 'rgba(255,255,255,0.04)' }}>
                <div
                  className="h-full rounded flex items-center pl-2 transition-all duration-700"
                  style={{
                    width: `${(d.count / maxCount) * 100}%`,
                    background: `linear-gradient(90deg, rgba(${hexToRgb(d.color)},0.3), rgba(${hexToRgb(d.color)},0.15))`,
                    borderRight: `2px solid ${d.color}`,
                  }}
                >
                  <span className="text-[10px] font-medium" style={{ color: d.color }}>{d.count}</span>
                </div>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function formatRelativeTime(iso?: string): string {
  if (!iso) return '—'
  const diff = Date.now() - new Date(iso).getTime()
  const m = Math.floor(diff / 60000)
  if (m < 1) return 'az önce'
  if (m < 60) return `${m} dk önce`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} sa önce`
  return `${Math.floor(h / 24)} gün önce`
}

function calcHealthScore(
  onlinePct: number, monitorPct: number, aiReadyPct: number,
  problemServers: number, eventStats?: EventStats, incidentStats?: IncidentStats,
): number {
  const base = onlinePct * 0.45 + monitorPct * 0.25 + aiReadyPct * 0.15
  const stability = Math.max(0, 15 - problemServers * 3)
  const aiops = Math.max(0, 15
    - (eventStats?.critical ?? 0) * 4
    - (eventStats?.emergency ?? 0) * 5
    - (eventStats?.warning ?? 0)
    - (incidentStats?.open ?? 0) * 3
    - (incidentStats?.critical ?? 0) * 5)
  return Math.round(Math.min(100, Math.max(0, base + stability + aiops)))
}

function healthColor(score: number): string {
  if (score >= 85) return NEON.green
  if (score >= 65) return NEON.cyan
  if (score >= 45) return NEON.orange
  return NEON.red
}

// ── Hero Banner ────────────────────────────────────────────────────────────
function DashboardHero({
  healthScore, onlineServers, totalServers, unresolvedEvents, openIncidents, lastRefresh,
  showFleet = true, showOps = true, title = 'Altyapı Komuta Merkezi',
}: {
  healthScore: number; onlineServers: number; totalServers: number
  unresolvedEvents: number; openIncidents: number; lastRefresh: string
  showFleet?: boolean; showOps?: boolean; title?: string
}) {
  const systemStatus = healthScore >= 80 ? 'Sistem Normal' : healthScore >= 50 ? 'Dikkat Gerekiyor' : 'Kritik Durum'
  const accent = healthColor(healthScore)

  const chips = [
    { label: 'Sağlık', value: `${healthScore}%`, color: accent },
    ...(showFleet ? [{ label: 'Fleet', value: `${onlineServers}/${totalServers}`, color: NEON.blue }] : []),
    ...(showOps ? [
      { label: 'Events', value: String(unresolvedEvents), color: unresolvedEvents ? NEON.orange : NEON.green },
      { label: 'Incidents', value: String(openIncidents), color: openIncidents ? NEON.red : NEON.green },
    ] : []),
  ]

  return (
    <div
      className="relative overflow-hidden rounded-2xl p-6 md:p-8 animate-fade-in"
      style={{
        background: 'linear-gradient(135deg, var(--bg-elevated) 0%, rgba(26,37,64,0.9) 100%)',
        border: '1px solid var(--border-strong)',
        boxShadow: '0 8px 32px rgba(0,0,0,0.3)',
      }}
    >
      <div className="absolute -top-24 -right-24 w-72 h-72 rounded-full opacity-20 blur-3xl pointer-events-none"
        style={{ background: `radial-gradient(circle, ${accent}30, transparent 70%)` }} />

      <div className="relative flex flex-col lg:flex-row lg:items-center gap-8">
        <div className="flex-1">
          <p className="text-xs uppercase tracking-[0.2em] mb-2" style={{ color: 'rgba(148,163,184,0.7)' }}>
            {title}
          </p>
          <h1 className="text-2xl md:text-3xl font-bold mb-2" style={{ color: accent }}>{systemStatus}</h1>
          <p className="text-sm max-w-xl" style={{ color: 'rgba(148,163,184,0.8)' }}>
            {showFleet && `${totalServers} sunucunun ${onlineServers} tanesi çevrimiçi.`}
            {showOps && unresolvedEvents > 0 && ` ${unresolvedEvents} açık event`}
            {showOps && openIncidents > 0 && `, ${openIncidents} aktif incident`}
            {showOps && (unresolvedEvents > 0 || openIncidents > 0) && ' takip ediliyor.'}
          </p>
          <div className="flex flex-wrap gap-3 mt-5">
            {chips.map(chip => (
              <div key={chip.label} className="px-3 py-1.5 rounded-lg text-xs font-medium"
                style={{ background: `rgba(${hexToRgb(chip.color)},0.1)`, border: `1px solid rgba(${hexToRgb(chip.color)},0.25)`, color: chip.color }}>
                <span className="opacity-70 mr-1.5">{chip.label}</span>
                <span className="text-white font-bold">{chip.value}</span>
              </div>
            ))}
          </div>
        </div>

        <div className="flex-shrink-0 flex flex-col items-center">
          <div className="relative" style={{ width: 140, height: 140 }}>
            <ResponsiveContainer width="100%" height="100%">
              <RadialBarChart cx="50%" cy="50%" innerRadius="72%" outerRadius="100%" barSize={10}
                data={[{ name: 'Sağlık', value: healthScore, fill: accent }]}
                startAngle={90} endAngle={-270}>
                <RadialBar dataKey="value" cornerRadius={8} background={{ fill: 'rgba(255,255,255,0.06)' }} />
              </RadialBarChart>
            </ResponsiveContainer>
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <span className="text-3xl font-bold text-white">{healthScore}</span>
              <span className="text-[10px] uppercase tracking-wider text-slate-500">Health</span>
            </div>
          </div>
          <p className="text-[10px] text-slate-600 mt-2">Güncelleme: {lastRefresh}</p>
        </div>
      </div>
    </div>
  )
}

// ── Hero KPI ───────────────────────────────────────────────────────────────
function HeroKpi({
  label, value, sub, accent, pct, delay = 0,
}: { label: string; value: string | number; sub: string; accent: string; pct: number; delay?: number }) {
  return (
    <div className="stat-card animate-fade-in group" style={{ '--accent-color': accent, animationDelay: `${delay}ms` } as React.CSSProperties}>
      <div className="flex items-start justify-between mb-3">
        <div>
          <p className="text-[10px] font-semibold tracking-widest uppercase text-slate-500">{label}</p>
          <p className="text-2xl md:text-3xl font-bold text-white mt-1 count-up">{value}</p>
          <p className="text-xs mt-1" style={{ color: `${accent}99` }}>{sub}</p>
        </div>
        <div className="w-10 h-10 rounded-xl flex items-center justify-center transition-transform group-hover:scale-110"
          style={{ background: `rgba(${hexToRgb(accent)},0.15)`, color: accent, boxShadow: `0 0 20px rgba(${hexToRgb(accent)},0.2)` }}>
          <DonutGauge pct={pct} color={accent} size={40} strokeWidth={4} />
        </div>
      </div>
      <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'rgba(255,255,255,0.06)' }}>
        <div className="h-full rounded-full transition-all duration-1000" style={{ width: `${pct}%`, background: `linear-gradient(90deg, ${accent}, ${accent}88)`, boxShadow: `0 0 8px ${accent}60` }} />
      </div>
    </div>
  )
}

// ── Kaynak Kullanımı ───────────────────────────────────────────────────────
function ResourceUsageChart({ metrics }: { metrics: MetricDashboard | undefined }) {
  const rows = (metrics?.servers || [])
    .filter(s => s.cpu_usage != null || s.memory_usage != null)
    .slice(0, 8)
    .map(s => ({
      name: (s.hostname || s.ip_address || `#${s.server_id}`).split('.')[0].slice(0, 10),
      cpu: Math.round(s.cpu_usage ?? 0),
      ram: Math.round(s.memory_usage ?? 0),
      disk: Math.round(s.disk_usage ?? 0),
    }))

  if (!rows.length) {
    return (
      <div className="cyber-card p-5 h-full flex flex-col">
        <SectionTitle title="Kaynak Kullanımı" accent={NEON.blue} sub="AI-ready sunucular — canlı metrik" />
        <div className="flex-1 flex items-center justify-center text-sm text-slate-500 text-center px-4">
          Henüz metrik verisi yok. Node Exporter kurulumu sonrası grafikler dolacak.
        </div>
      </div>
    )
  }

  const CustomTooltip = ({ active, payload, label }: any) => {
    if (!active || !payload?.length) return null
    return (
      <div className="cyber-card px-3 py-2 text-xs border border-white/[0.06]">
        <p className="text-white font-medium mb-1">{label}</p>
        {payload.map((p: any) => (
          <p key={p.dataKey} style={{ color: p.color }}>{p.name}: {p.value}%</p>
        ))}
      </div>
    )
  }

  return (
    <div className="cyber-card p-5 h-full animate-fade-in">
      <SectionTitle title="Kaynak Kullanımı" accent={NEON.blue} sub={`${metrics?.total_servers ?? 0} izlenen sunucu`} />
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={rows} margin={{ top: 8, right: 8, left: -20, bottom: 0 }} barGap={2}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.08)" vertical={false} />
          <XAxis dataKey="name" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis domain={[0, 100]} tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} unit="%" />
          <Tooltip content={<CustomTooltip />} cursor={{ fill: 'rgba(34,211,238,0.06)' }} />
          <Bar dataKey="cpu" name="CPU" fill={NEON.blue} radius={[4, 4, 0, 0]} maxBarSize={18} />
          <Bar dataKey="ram" name="RAM" fill={NEON.blue} radius={[4, 4, 0, 0]} maxBarSize={18} />
          <Bar dataKey="disk" name="Disk" fill={NEON.green} radius={[4, 4, 0, 0]} maxBarSize={18} />
        </BarChart>
      </ResponsiveContainer>
      <div className="flex justify-center gap-4 mt-2">
        {[{ c: NEON.blue, l: 'CPU' }, { c: NEON.blue, l: 'RAM' }, { c: NEON.green, l: 'Disk' }].map(x => (
          <div key={x.l} className="flex items-center gap-1.5 text-[10px] text-slate-500">
            <div className="w-2 h-2 rounded-sm" style={{ background: x.c }} />{x.l}
          </div>
        ))}
      </div>
    </div>
  )
}

// ── Fleet trend (dekoratif area — online oranı) ──────────────────────────
function FleetTrendChart({ online, offline, warning }: { online: number; offline: number; warning: number }) {
  const total = online + offline + warning || 1
  const data = [
    { t: 'Pzt', up: Math.max(0, online - 2), dn: offline },
    { t: 'Sal', up: Math.max(0, online - 1), dn: offline },
    { t: 'Çar', up: online, dn: offline },
    { t: 'Per', up: online, dn: Math.max(0, offline - 1) },
    { t: 'Cum', up: online, dn: offline },
    { t: 'Cmt', up: Math.max(0, online - 1), dn: offline + 1 },
    { t: 'Bugün', up: online, dn: offline + warning },
  ]

  return (
    <div className="cyber-card p-5 animate-fade-in h-full">
      <SectionTitle title="Fleet Trend" accent={NEON.cyan} sub={`${((online/total)*100).toFixed(0)}% uptime hedefi`} />
      <ResponsiveContainer width="100%" height={160}>
        <AreaChart data={data} margin={{ top: 8, right: 8, left: -20, bottom: 0 }}>
          <defs>
            <linearGradient id="gOnline" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={NEON.green} stopOpacity={0.4} />
              <stop offset="100%" stopColor={NEON.green} stopOpacity={0} />
            </linearGradient>
            <linearGradient id="gOffline" x1="0" y1="0" x2="0" y2="1">
              <stop offset="0%" stopColor={NEON.red} stopOpacity={0.25} />
              <stop offset="100%" stopColor={NEON.red} stopOpacity={0} />
            </linearGradient>
          </defs>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(148,163,184,0.06)" vertical={false} />
          <XAxis dataKey="t" tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} />
          <YAxis tick={{ fill: '#64748b', fontSize: 10 }} axisLine={false} tickLine={false} allowDecimals={false} />
          <Tooltip contentStyle={{ background: 'var(--bg-elevated)', border: '1px solid var(--border-strong)', borderRadius: 8, fontSize: 12 }} />
          <Area type="monotone" dataKey="up" name="Online" stroke={NEON.green} fill="url(#gOnline)" strokeWidth={2} />
          <Area type="monotone" dataKey="dn" name="Sorunlu" stroke={NEON.red} fill="url(#gOffline)" strokeWidth={2} />
        </AreaChart>
      </ResponsiveContainer>
    </div>
  )
}

function SectionTitle({ title, accent, sub }: { title: string; accent: string; sub?: string }) {
  return (
    <div className="flex items-center justify-between mb-4">
      <div className="flex items-center gap-2">
        <div className="w-1.5 h-4 rounded-full" style={{ background: accent }} />
        <div>
          <h2 className="text-sm font-semibold text-white">{title}</h2>
          {sub && <p className="text-[10px] text-slate-500">{sub}</p>}
        </div>
      </div>
    </div>
  )
}

// ── AIOps Özet ─────────────────────────────────────────────────────────────
function AiOpsOverview({
  eventStats, incidentStats,
  eventsPath = '/linux/events', incidentsPath = '/linux/incidents', anomaliesPath = '/linux/anomalies',
}: {
  eventStats?: EventStats; incidentStats?: IncidentStats
  eventsPath?: string; incidentsPath?: string; anomaliesPath?: string
}) {
  const items = [
    { label: 'Açık Event', value: eventStats?.unresolved ?? 0, color: NEON.orange, to: eventsPath },
    { label: 'Kritik Event', value: (eventStats?.critical ?? 0) + (eventStats?.emergency ?? 0), color: NEON.red, to: eventsPath },
    { label: 'Açık Incident', value: incidentStats?.open ?? 0, color: NEON.blue, to: incidentsPath },
    { label: 'RCA Bekleyen', value: incidentStats?.investigating ?? 0, color: NEON.cyan, to: incidentsPath },
  ]

  return (
    <div className="cyber-card p-5 animate-fade-in h-full">
      <SectionTitle title="AIOps Özeti" accent={NEON.blue} sub="Events & Incidents" />
      <div className="grid grid-cols-2 gap-3 mb-4">
        {items.map(item => (
          <Link key={item.label} to={item.to}
            className="p-3 rounded-xl transition-all hover:scale-[1.02]"
            style={{ background: `rgba(${hexToRgb(item.color)},0.08)`, border: `1px solid rgba(${hexToRgb(item.color)},0.2)` }}>
            <p className="text-2xl font-bold text-white">{item.value}</p>
            <p className="text-[10px] uppercase tracking-wider mt-1" style={{ color: item.color }}>{item.label}</p>
          </Link>
        ))}
      </div>
      <div className="flex gap-2">
        <Link to={anomaliesPath} className="flex-1 text-center py-2 rounded-lg text-xs font-medium text-white transition-colors"
          style={{ background: 'rgba(59,130,246,0.12)', border: '1px solid rgba(59,130,246,0.25)' }}>
          Anomaly Detection →
        </Link>
        <Link to={incidentsPath} className="flex-1 text-center py-2 rounded-lg text-xs font-medium text-white transition-colors"
          style={{ background: 'rgba(56,189,248,0.08)', border: '1px solid rgba(56,189,248,0.2)' }}>
          Incidents →
        </Link>
      </div>
    </div>
  )
}

// ── Aktivite Akışı ─────────────────────────────────────────────────────────
function ActivityFeed({ events, eventsPath = '/linux/events' }: { events: FeedEvent[]; eventsPath?: string }) {
  const sevStyle: Record<string, { color: string; bg: string }> = {
    critical: { color: NEON.red, bg: 'rgba(239,68,68,0.10)' },
    emergency: { color: NEON.red, bg: 'rgba(239,68,68,0.10)' },
    warning: { color: NEON.orange, bg: 'rgba(245,158,11,0.10)' },
    info: { color: NEON.cyan, bg: 'rgba(56,189,248,0.08)' },
  }

  return (
    <div className="cyber-card animate-fade-in h-full flex flex-col">
      <div className="px-5 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
        <SectionTitle title="Canlı Aktivite" accent={NEON.orange} sub="Son açık eventler" />
        <Link to={eventsPath} className="text-xs" style={{ color: 'var(--accent)' }}>Tümü →</Link>
      </div>
      <div className="flex-1 overflow-y-auto max-h-80">
        {events.length === 0 ? (
          <p className="p-6 text-sm text-center text-slate-500">Açık event yok — sistem sakin görünüyor.</p>
        ) : events.map((ev, i) => {
          const st = sevStyle[ev.severity] || sevStyle.info
          return (
            <div key={ev.id} className="px-5 py-3 flex gap-3" style={{ borderBottom: i < events.length - 1 ? '1px solid rgba(30,41,59,0.5)' : undefined }}>
              <div className="w-1 rounded-full flex-shrink-0 self-stretch" style={{ background: st.color, boxShadow: `0 0 6px ${st.color}` }} />
              <div className="min-w-0 flex-1">
                <p className="text-sm text-white truncate">{ev.title}</p>
                <p className="text-[11px] text-slate-500 mt-0.5">
                  {ev.server_name || 'Sistem'} · {formatRelativeTime(ev.created_at)}
                </p>
              </div>
              <span className="text-[9px] px-1.5 py-0.5 rounded uppercase font-bold flex-shrink-0 h-fit"
                style={{ color: st.color, background: st.bg }}>{ev.severity}</span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

// ── Günlük Özet Kartı ──────────────────────────────────────────────────────
function DigestCard({ digest }: {
  digest: {
    date: string; total_events: number; severity_breakdown: Record<string, number>
    affected_servers: number; new_incidents: number; storm_incidents: number
    resolved_count: number; unresolved_critical_count: number
    top_metrics: { metric: string; count: number }[]
    action_required: boolean; noise_ratio: number
  }
}) {
  const sevColor: Record<string, string> = {
    critical: 'text-red-400', warning: 'text-amber-400', info: 'text-blue-400', emergency: 'text-purple-400'
  }
  return (
    <div className={`rounded-xl border p-4 ${digest.action_required
      ? 'border-amber-500/40 bg-amber-500/5'
      : 'border-gray-700/60 bg-gray-800/30'}`}>
      <div className="flex items-center justify-between mb-4">
        <div className="flex items-center gap-2">
          <span className="text-lg">📊</span>
          <h3 className="font-semibold text-gray-100">Günlük Alarm Özeti</h3>
          <span className="text-xs text-gray-500">{digest.date}</span>
        </div>
        {digest.action_required && (
          <span className="text-xs bg-amber-500/20 text-amber-400 px-2 py-1 rounded-full border border-amber-500/30">
            ⚠ Müdahale Gerekli
          </span>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3 mb-4">
        <div className="text-center">
          <div className="text-2xl font-bold text-gray-100">{digest.total_events}</div>
          <div className="text-xs text-gray-500">Toplam Event</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold text-red-400">{digest.unresolved_critical_count}</div>
          <div className="text-xs text-gray-500">Kritik Açık</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold text-amber-400">{digest.affected_servers}</div>
          <div className="text-xs text-gray-500">Etkilenen Sunucu</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold text-cyan-400">{digest.noise_ratio}%</div>
          <div className="text-xs text-gray-500">Gürültü Oranı</div>
        </div>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div>
          <div className="text-xs text-gray-500 mb-2">Severity Dağılımı</div>
          <div className="space-y-1">
            {Object.entries(digest.severity_breakdown).map(([sev, cnt]) => (
              <div key={sev} className="flex items-center gap-2">
                <span className={`text-xs w-16 ${sevColor[sev] || 'text-gray-400'}`}>{sev}</span>
                <div className="flex-1 h-1.5 bg-gray-700 rounded-full overflow-hidden">
                  <div
                    className={`h-full rounded-full ${sev === 'critical' ? 'bg-red-500' : sev === 'warning' ? 'bg-amber-500' : 'bg-blue-500'}`}
                    style={{ width: `${Math.min((cnt / digest.total_events) * 100, 100)}%` }}
                  />
                </div>
                <span className="text-xs text-gray-400 w-8 text-right">{cnt}</span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <div className="text-xs text-gray-500 mb-2">En Sık Tetiklenen Metrikler</div>
          <div className="space-y-1">
            {digest.top_metrics.slice(0, 5).map((m, i) => (
              <div key={i} className="flex items-center justify-between">
                <span className="text-xs text-gray-300 truncate max-w-[160px]">{m.metric}</span>
                <span className="text-xs text-gray-500 bg-gray-700/50 px-1.5 py-0.5 rounded">{m.count}</span>
              </div>
            ))}
          </div>
          {digest.storm_incidents > 0 && (
            <div className="mt-2 text-xs text-amber-400 flex items-center gap-1">
              <span>⚡</span>
              <span>{digest.storm_incidents} alarm fırtınası tespit edildi</span>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Hızlı Erişim (gelişmiş) ────────────────────────────────────────────────
function QuickActionsPanel({ scope = 'admin' }: { scope?: DashboardScope }) {
  const { hasModule, user } = useAuth()
  const allActions: { label: string; desc: string; to: string; accent: string; moduleId?: string; adminOnly?: boolean; scopes?: DashboardScope[] }[] = [
    { label: 'AI Chat', desc: 'Soru sor', to: '/chat', accent: NEON.blue, moduleId: 'ai_automation' },
    { label: 'AI Agent', desc: 'Otomasyon', to: '/agent', accent: NEON.cyan, moduleId: 'ai_automation' },
    { label: 'Güncelle', desc: 'Patch & repo', to: '/system-update', accent: NEON.orange, moduleId: 'linux', scopes: ['admin', 'linux'] },
    { label: 'Metrikler', desc: 'Canlı izleme', to: '/metrics', accent: NEON.green, moduleId: 'linux', scopes: ['admin', 'linux'] },
    { label: 'Ansible', desc: 'Playbook', to: '/ansible', accent: NEON.blue, moduleId: 'linux', scopes: ['admin', 'linux'] },
    { label: 'WinRM', desc: 'Windows sunucular', to: '/windows', accent: NEON.blue, moduleId: 'windows', scopes: ['admin', 'windows'] },
    { label: 'Hypervisor', desc: 'Sanallaştırma', to: '/hypervisors', accent: NEON.purple, moduleId: 'virtualization', scopes: ['admin'] },
    { label: 'Ayarlar', desc: 'Yapılandırma', to: '/settings', accent: '#94a3b8', adminOnly: true },
  ]
  const actions = allActions.filter(a => {
    if (a.scopes && !a.scopes.includes(scope)) return false
    return a.adminOnly ? user?.role === 'admin' : hasModule(a.moduleId!)
  })

  if (actions.length === 0) return null

  return (
    <div className="cyber-card p-5 animate-fade-in h-full">
      <SectionTitle title="Hızlı Erişim" accent={NEON.orange} sub="Tek tıkla modüller" />
      <div className="grid grid-cols-2 gap-2">
        {actions.map(btn => (
          <Link key={btn.to} to={btn.to}
            className="group p-3 rounded-xl transition-all hover:-translate-y-0.5"
            style={{ background: `rgba(${hexToRgb(btn.accent)},0.06)`, border: `1px solid rgba(${hexToRgb(btn.accent)},0.15)` }}>
            <p className="text-sm font-semibold text-white group-hover:text-white">{btn.label}</p>
            <p className="text-[10px] mt-0.5" style={{ color: `${btn.accent}99` }}>{btn.desc}</p>
          </Link>
        ))}
      </div>
    </div>
  )
}

// ── Recent Servers ─────────────────────────────────────────────────────────
function RecentServers({
  servers, onSelect
}: { servers: DashboardServer[]; onSelect: (s: DashboardServer) => void }) {
  const statusConfig: Record<string, { color: string; label: string }> = {
    ONLINE:   { color: NEON.green,  label: 'ONLINE' },
    OFFLINE:  { color: '#64748b',   label: 'OFFLINE' },
    WARNING:  { color: NEON.orange, label: 'UYARI' },
    CRITICAL: { color: NEON.red,    label: 'KRİTİK' },
  }

  return (
    <div className="cyber-card animate-fade-in">
      <div className="px-5 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-4 rounded-full" style={{ background: NEON.green }} />
          <h2 className="text-sm font-semibold text-white">Çevrimiçi Sunucular</h2>
        </div>
        <Link
          to="/servers"
          className="text-xs font-medium transition-colors"
          style={{ color: 'var(--accent)' }}
          onMouseEnter={e => (e.currentTarget.style.color = NEON.blue)}
          onMouseLeave={e => (e.currentTarget.style.color = 'var(--accent)')}
        >
          Tümünü Gör →
        </Link>
      </div>
      <div>
        {servers.length > 0 ? servers.slice(0, 6).map((server, i) => {
          const sc = statusConfig[server.status] || statusConfig.OFFLINE
          return (
            <div
              key={server.id}
              className="flex items-center gap-3 px-5 py-3 cursor-pointer transition-all"
              style={{ borderBottom: i < Math.min(servers.length, 6) - 1 ? '1px solid rgba(30,41,59,0.6)' : 'none' }}
              onClick={() => onSelect(server)}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(34,211,238,0.03)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              {/* Status dot */}
              <div className="relative flex-shrink-0">
                <div className="w-2 h-2 rounded-full" style={{ background: sc.color, boxShadow: `0 0 6px ${sc.color}` }} />
                {server.status === 'ONLINE' && (
                  <div className="absolute inset-0 w-2 h-2 rounded-full animate-ping" style={{ background: sc.color, opacity: 0.4 }} />
                )}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-white truncate">{server.name}</p>
                  {server.ai_ready && server.status === 'ONLINE' && (
                    <span className="px-1.5 py-0.5 rounded text-[9px] font-medium flex-shrink-0"
                      style={{ background: 'rgba(56,189,248,0.10)', color: NEON.cyan, border: '1px solid rgba(56,189,248,0.22)' }}>
                      AI
                    </span>
                  )}
                </div>
                <p className="text-xs truncate" style={{ color: 'rgba(148,163,184,0.5)' }}>{server.ip_address || server.hostname}</p>
              </div>

              <div className="flex items-center gap-3 flex-shrink-0">
                {server.cpu_cores > 0 && (
                  <span className="text-xs" style={{ color: 'rgba(148,163,184,0.4)' }}>
                    {server.cpu_cores}C
                  </span>
                )}
                {server.memory_gb > 0 && (
                  <span className="text-xs" style={{ color: 'rgba(148,163,184,0.4)' }}>
                    {server.memory_gb}G
                  </span>
                )}
                <span
                  className="px-2 py-0.5 rounded text-[10px] font-medium"
                  style={{
                    background: `rgba(${hexToRgb(sc.color)}, 0.12)`,
                    color: sc.color,
                    border: `1px solid rgba(${hexToRgb(sc.color)}, 0.25)`,
                  }}
                >
                  {sc.label}
                </span>
              </div>
            </div>
          )
        }) : (
          <div className="px-5 py-8 text-center text-sm" style={{ color: 'rgba(148,163,184,0.35)' }}>
            Çevrimiçi sunucu bulunamadı
          </div>
        )}
      </div>
    </div>
  )
}

// ── Recent Windows Servers ─────────────────────────────────────────────────
// RecentServers ile aynı görsel dili kullanır — dashboard'lar arası tutarlılık için.
function RecentWindowsServers({
  servers
}: { servers: { id: number; name: string; hostname: string; ip_address: string; status: string; ai_ready?: boolean; cpu_cores?: number; memory_gb?: number }[] }) {
  const statusConfig: Record<string, { color: string; label: string }> = {
    ONLINE:   { color: NEON.green,  label: 'ONLINE' },
    OFFLINE:  { color: '#64748b',   label: 'OFFLINE' },
    WARNING:  { color: NEON.orange, label: 'UYARI' },
    CRITICAL: { color: NEON.red,    label: 'KRİTİK' },
  }

  return (
    <div className="cyber-card animate-fade-in">
      <div className="px-5 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-4 rounded-full" style={{ background: NEON.green }} />
          <h2 className="text-sm font-semibold text-white">Çevrimiçi Sunucular</h2>
        </div>
        <Link to="/windows" className="text-xs font-medium" style={{ color: 'var(--accent)' }}>Tümünü Gör →</Link>
      </div>
      <div>
        {servers.length > 0 ? servers.slice(0, 6).map((server, i) => {
          const sc = statusConfig[server.status] || statusConfig.OFFLINE
          return (
            <Link
              key={server.id}
              to="/windows"
              className="flex items-center gap-3 px-5 py-3 transition-all"
              style={{ borderBottom: i < Math.min(servers.length, 6) - 1 ? '1px solid rgba(30,41,59,0.6)' : 'none' }}
              onMouseEnter={e => (e.currentTarget.style.background = 'rgba(34,211,238,0.03)')}
              onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
            >
              <div className="relative flex-shrink-0">
                <div className="w-2 h-2 rounded-full" style={{ background: sc.color, boxShadow: `0 0 6px ${sc.color}` }} />
                {server.status === 'ONLINE' && (
                  <div className="absolute inset-0 w-2 h-2 rounded-full animate-ping" style={{ background: sc.color, opacity: 0.4 }} />
                )}
              </div>

              <div className="flex-1 min-w-0">
                <div className="flex items-center gap-2">
                  <p className="text-sm font-medium text-white truncate">{server.name}</p>
                  {server.ai_ready && server.status === 'ONLINE' && (
                    <span className="px-1.5 py-0.5 rounded text-[9px] font-medium flex-shrink-0"
                      style={{ background: 'rgba(56,189,248,0.10)', color: NEON.cyan, border: '1px solid rgba(56,189,248,0.22)' }}>
                      WinRM
                    </span>
                  )}
                </div>
                <p className="text-xs truncate" style={{ color: 'rgba(148,163,184,0.5)' }}>{server.ip_address || server.hostname}</p>
              </div>

              <div className="flex items-center gap-3 flex-shrink-0">
                {(server.cpu_cores ?? 0) > 0 && (
                  <span className="text-xs" style={{ color: 'rgba(148,163,184,0.4)' }}>{server.cpu_cores}C</span>
                )}
                {(server.memory_gb ?? 0) > 0 && (
                  <span className="text-xs" style={{ color: 'rgba(148,163,184,0.4)' }}>{server.memory_gb}G</span>
                )}
                <span
                  className="px-2 py-0.5 rounded text-[10px] font-medium"
                  style={{
                    background: `rgba(${hexToRgb(sc.color)}, 0.12)`,
                    color: sc.color,
                    border: `1px solid rgba(${hexToRgb(sc.color)}, 0.25)`,
                  }}
                >
                  {sc.label}
                </span>
              </div>
            </Link>
          )
        }) : (
          <div className="px-5 py-8 text-center text-sm" style={{ color: 'rgba(148,163,184,0.35)' }}>
            Çevrimiçi sunucu bulunamadı
          </div>
        )}
      </div>
    </div>
  )
}

// ── Hypervisor Cards ───────────────────────────────────────────────────────
function HypervisorCards({ hypervisors }: { hypervisors: Hypervisor[] }) {
  if (hypervisors.length === 0) return null
  return (
    <div className="cyber-card animate-fade-in">
      <div className="px-5 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid var(--border)' }}>
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-4 rounded-full" style={{ background: NEON.blue }} />
          <h2 className="text-sm font-semibold text-white">Hypervisor'lar</h2>
        </div>
        <Link
          to="/hypervisors"
          className="text-xs font-medium"
          style={{ color: 'var(--accent)' }}
        >
          Tümünü Gör →
        </Link>
      </div>
      <div className="p-4 grid grid-cols-1 sm:grid-cols-2 gap-3">
        {hypervisors.map(hv => {
          const isVmware = hv.type?.toLowerCase() === 'vmware'
          const isOvirt  = hv.type?.toLowerCase().includes('ovirt') || hv.type?.toLowerCase().includes('olvm')
          const accent   = isVmware ? NEON.blue : isOvirt ? NEON.orange : NEON.cyan
          return (
            <div
              key={hv.id}
              className="flex items-center gap-3 p-3 rounded-lg transition-all"
              style={{
                background: 'rgba(255,255,255,0.03)',
                border: `1px solid rgba(${hexToRgb(accent)},0.15)`,
              }}
              onMouseEnter={e => {
                e.currentTarget.style.borderColor = `rgba(${hexToRgb(accent)},0.4)`
                e.currentTarget.style.background = `rgba(${hexToRgb(accent)},0.05)`
              }}
              onMouseLeave={e => {
                e.currentTarget.style.borderColor = `rgba(${hexToRgb(accent)},0.15)`
                e.currentTarget.style.background = 'rgba(255,255,255,0.03)'
              }}
            >
              <div
                className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 text-xs font-bold"
                style={{ background: `rgba(${hexToRgb(accent)},0.12)`, color: accent, letterSpacing: '0.05em' }}
              >
                {isVmware ? 'VM' : isOvirt ? 'OV' : 'HV'}
              </div>
              <div className="min-w-0">
                <p className="text-sm font-medium text-white truncate">{hv.name}</p>
                <p className="text-xs truncate" style={{ color: accent + '80' }}>
                  {hv.type.toUpperCase()} • {hv.ip_address}
                </p>
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}


// ── Main Dashboard ─────────────────────────────────────────────────────────
const Dashboard: React.FC<{ scope?: DashboardScope }> = ({ scope = 'admin' }) => {
  const { hasModule } = useAuth()
  const isAdminScope = scope === 'admin'
  const isLinuxScope = scope === 'linux'
  const isWindowsScope = scope === 'windows'

  const showLinux = isLinuxScope || (isAdminScope && hasModule('linux'))
  const showVirt = isAdminScope && hasModule('virtualization')
  const showWindowsPanel = isWindowsScope || (isAdminScope && hasModule('windows'))
  const showAiops = isLinuxScope
    ? hasModule('linux')
    : isWindowsScope
      ? hasModule('windows')
      : (isAdminScope && hasModule('linux'))
  const showAiAutomation = isAdminScope && hasModule('ai_automation')

  const aiopsPlatform = isLinuxScope ? 'linux' : isWindowsScope ? 'windows' : undefined
  const eventsPath = isLinuxScope ? '/linux/events' : isWindowsScope ? '/windows/aiops/events' : '/linux/events'
  const incidentsPath = isLinuxScope ? '/linux/incidents' : isWindowsScope ? '/windows/aiops/incidents' : '/linux/incidents'
  const anomaliesPath = isLinuxScope ? '/linux/events?tab=heatmap' : isWindowsScope ? '/windows/aiops/events?tab=heatmap' : '/virt/events?tab=heatmap'
  const heroTitle = isLinuxScope ? 'Linux Yönetimi' : isWindowsScope ? 'Windows Yönetimi' : 'Altyapı Komuta Merkezi'

  const hasAnyModule = showLinux || showVirt || showAiops || showAiAutomation || showWindowsPanel
    || hasModule('integrations') || hasModule('level1')

  const [selectedServer, setSelectedServer] = useState<DashboardServer | null>(null)
  const [now, setNow] = useState(() => new Date())

  useEffect(() => {
    const t = setInterval(() => setNow(new Date()), 60_000)
    return () => clearInterval(t)
  }, [])

  const { data: serversRaw = [], isLoading: serversLoading } = useQuery<DashboardServer[]>({
    queryKey: ['servers'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/servers/?platform=linux`)
      if (!r.ok) throw new Error('Failed to fetch servers')
      return r.json()
    },
    enabled: showLinux && !isWindowsScope,
    refetchInterval: 30_000,
  })
  const servers = serversRaw.filter(s => !isWindowsOs(s))

  // Admin (genel) dashboard TÜM envanteri (Linux + Windows + VM) baz alır —
  // böylece "Toplam Sunucu" ve fleet grafikleri Linux dashboard'dan gerçekten
  // farklı, altyapının tamamını yansıtan sayılar gösterir.
  const { data: allServersRaw = [], isLoading: allServersLoading } = useQuery<DashboardServer[]>({
    queryKey: ['servers-all'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/servers/`)
      if (!r.ok) throw new Error('Failed to fetch servers')
      return r.json()
    },
    enabled: isAdminScope,
    refetchInterval: 30_000,
  })

  interface WindowsDashboardServer {
    id: number; name: string; hostname: string; ip_address: string; status: string
    winrm_configured?: boolean; cpu_cores?: number; memory_gb?: number
    os_type?: string; ai_ready?: boolean
    windows_exporter_installed?: boolean; windows_exporter_running?: boolean
  }
  const { data: windowsServers = [], isLoading: windowsLoading } = useQuery<WindowsDashboardServer[]>({
    queryKey: ['windows-dashboard-servers'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/windows/servers`)
      if (!r.ok) return []
      return r.json()
    },
    enabled: isWindowsScope || (isAdminScope && hasModule('windows')),
    refetchInterval: 30_000,
  })

  const { data: hypervisors = [], isLoading: hypervisorsLoading } = useQuery<Hypervisor[]>({
    queryKey: ['hypervisors'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/`)
      if (!r.ok) throw new Error('Failed to fetch hypervisors')
      return r.json()
    },
    enabled: showVirt,
    refetchInterval: 60_000,
  })

  const { data: eventStats } = useQuery<EventStats>({
    queryKey: ['event-stats', aiopsPlatform ?? 'all'],
    queryFn: async () => {
      const q = aiopsPlatform ? `?platform=${aiopsPlatform}` : ''
      const r = await fetch(`${API_BASE_URL}/events/stats${q}`)
      if (!r.ok) return { total: 0, unresolved: 0, critical: 0, warning: 0, emergency: 0, acknowledged: 0, known: 0 }
      return r.json()
    },
    enabled: showAiops,
    refetchInterval: 60_000,
  })

  const { data: incidentStats } = useQuery<IncidentStats>({
    queryKey: ['incident-stats', aiopsPlatform ?? 'all'],
    queryFn: async () => {
      const q = aiopsPlatform ? `?platform=${aiopsPlatform}` : ''
      const r = await fetch(`${API_BASE_URL}/incidents/stats${q}`)
      if (!r.ok) return { total: 0, open: 0, investigating: 0, resolved: 0, critical: 0 }
      return r.json()
    },
    enabled: showAiops,
    refetchInterval: 60_000,
  })

  const { data: metricDashboard } = useQuery<MetricDashboard>({
    queryKey: ['metrics-dashboard', isWindowsScope ? 'windows' : 'linux'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/metrics/dashboard?platform=${isWindowsScope ? 'windows' : 'linux'}`)
      if (!r.ok) return { total_servers: 0, servers: [] }
      return r.json()
    },
    enabled: showLinux || isWindowsScope,
    refetchInterval: 60_000,
  })

  const { data: metricsOverview } = useQuery<{
    total_online_installed: number
    total_live: number
    scrape_errors: number
  }>({
    queryKey: ['metrics-servers-overview'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/monitoring/metrics/servers`)
      if (!r.ok) return { total_online_installed: 0, total_live: 0, scrape_errors: 0 }
      return r.json()
    },
    enabled: showLinux,
    refetchInterval: 60_000,
  })

  const { data: recentEventsData } = useQuery<{ events: FeedEvent[] }>({
    queryKey: ['dashboard-events', aiopsPlatform ?? 'all'],
    queryFn: async () => {
      const q = aiopsPlatform ? `&platform=${aiopsPlatform}` : ''
      const r = await fetch(`${API_BASE_URL}/events/?resolved=false&limit=8${q}`)
      if (!r.ok) return { events: [] }
      return r.json()
    },
    enabled: showAiops,
    refetchInterval: 45_000,
  })

  const { data: digest } = useQuery<{
    date: string; total_events: number; severity_breakdown: Record<string, number>
    affected_servers: number; new_incidents: number; storm_incidents: number
    resolved_count: number; unresolved_critical_count: number
    top_metrics: { metric: string; count: number }[]
    action_required: boolean; noise_ratio: number
  }>({
    queryKey: ['daily-digest', aiopsPlatform ?? 'all'],
    queryFn: async () => {
      const q = aiopsPlatform ? `?platform=${aiopsPlatform}` : ''
      const r = await fetch(`${API_BASE_URL}/baseline/digest${q}`)
      if (!r.ok) return null
      return r.json()
    },
    enabled: showAiops,
    refetchInterval: 300_000,  // 5 dk
  })

  if ((showLinux && serversLoading) || (showVirt && hypervisorsLoading) || (isWindowsScope && windowsLoading)
      || (isAdminScope && allServersLoading)) {
    return (
      <div className="min-h-[50vh] flex flex-col items-center justify-center gap-4">
        <div className="relative w-16 h-16">
          <div className="absolute inset-0 rounded-full border-2 border-cyan-500/20 animate-ping" />
          <div className="absolute inset-0 rounded-full border-2 border-t-cyan-400 border-r-transparent border-b-transparent border-l-transparent animate-spin" />
        </div>
        <p className="text-xs text-slate-500 tracking-[0.25em] uppercase">Dashboard yükleniyor</p>
      </div>
    )
  }

  // Admin scope: TÜM envanter (Linux+Windows+VM). Linux scope: sadece Linux. Windows scope: sadece Windows.
  const fleetServers = isWindowsScope ? windowsServers : isAdminScope ? allServersRaw : servers
  const totalServers    = fleetServers.length
  const onlineServers   = fleetServers.filter(s => s.status === 'ONLINE').length
  const offlineServers  = fleetServers.filter(s => s.status === 'OFFLINE').length
  const warningServers  = fleetServers.filter(s => s.status === 'WARNING').length
  const criticalServers = fleetServers.filter(s => s.status === 'CRITICAL').length
  const aiReadyServers  = isWindowsScope
    ? fleetServers.filter(s => s.status === 'ONLINE').length
    : (fleetServers as DashboardServer[]).filter(s => s.ai_ready && s.status === 'ONLINE').length
  const totalCpu        = fleetServers.reduce((sum, s) => sum + (s.cpu_cores || 0), 0)
  const totalRam        = fleetServers.reduce((sum, s) => sum + (s.memory_gb || 0), 0)
  // metricsOverview backend'de her zaman Linux node-exporter kurulumlarını sayar —
  // admin (tüm envanter) kapsamında Windows sunucuları da içerecek şekilde
  // doğrudan fleetServers üzerinden hesaplanır.
  const monitoredInstalled = isWindowsScope
    ? onlineServers
    : isAdminScope
      ? (fleetServers as DashboardServer[]).filter(s => s.node_exporter?.installed && s.status === 'ONLINE').length
      : (metricsOverview?.total_online_installed
        ?? servers.filter(s => s.node_exporter?.installed && s.status === 'ONLINE').length)
  const monitoredLive = isWindowsScope
    ? onlineServers
    : isAdminScope
      ? (fleetServers as DashboardServer[]).filter(s => s.node_exporter?.running && s.status === 'ONLINE').length
      : (metricsOverview?.total_live
      ?? servers.filter(s => s.node_exporter?.running && s.status === 'ONLINE').length)

  const onlinePct   = totalServers > 0 ? (onlineServers / totalServers) * 100 : 100
  const monitorPct  = totalServers > 0 ? (monitoredLive / totalServers) * 100 : 0
  const aiReadyPct  = totalServers > 0 ? (aiReadyServers / totalServers) * 100 : 0
  const problemSrv  = warningServers + criticalServers + offlineServers

  const healthScore = calcHealthScore(onlinePct, monitorPct, aiReadyPct, problemSrv, eventStats, incidentStats)
  const lastRefresh = now.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })

  const secondaryStats = [
    ...(showVirt ? [{ label: 'Hypervisor', value: hypervisors.length, sub: `${hypervisors.filter(h => h.type?.toLowerCase() === 'vmware').length} VMware`, accent: NEON.blue, pct: hypervisors.length > 0 ? 100 : 0 }] : []),
    ...(showLinux || isWindowsScope ? [
      { label: 'Toplam CPU', value: totalCpu, sub: 'çekirdek', accent: NEON.orange, pct: Math.min(100, totalCpu * 2) },
      { label: 'Toplam RAM', value: `${totalRam} GB`, sub: 'envanter', accent: NEON.green, pct: Math.min(100, totalRam / 2) },
    ] : []),
    ...(isWindowsScope ? [
      { label: 'WinRM Hazır', value: windowsServers.filter(s => s.winrm_configured).length, sub: `${totalServers} sunucu`, accent: NEON.cyan, pct: totalServers > 0 ? (windowsServers.filter(s => s.winrm_configured).length / totalServers) * 100 : 0 },
    ] : []),
    ...(showLinux || isWindowsScope ? [
      { label: 'Uyarı/Kritik', value: warningServers + criticalServers, sub: `${offlineServers} offline`, accent: problemSrv > 0 ? NEON.red : '#64748b', pct: totalServers > 0 ? ((warningServers + criticalServers) / totalServers) * 100 : 0 },
    ] : []),
  ]

  if (!hasAnyModule) {
    return (
      <div className="min-h-[50vh] flex flex-col items-center justify-center gap-3 text-center">
        <div className="w-14 h-14 rounded-2xl flex items-center justify-center" style={{ background: 'rgba(148,163,184,0.1)', border: '1px solid rgba(148,163,184,0.2)' }}>
          <ShieldOff size={24} className="text-slate-500" />
        </div>
        <p className="text-slate-300 text-sm font-medium">Henüz bir modüle erişiminiz yok</p>
        <p className="text-slate-500 text-xs max-w-sm">Görüntüleyebileceğiniz içerik için lütfen yöneticinize başvurun.</p>
      </div>
    )
  }

  return (
    <>
      <div className="space-y-5 animate-fade-in pb-4">
        {(showLinux || showAiops || isWindowsScope) && (
          <DashboardHero
            healthScore={healthScore}
            onlineServers={onlineServers}
            totalServers={totalServers}
            unresolvedEvents={eventStats?.unresolved ?? 0}
            openIncidents={(incidentStats?.open ?? 0) + (incidentStats?.investigating ?? 0)}
            lastRefresh={lastRefresh}
            showFleet={showLinux || isWindowsScope}
            showOps={showAiops}
            title={heroTitle}
          />
        )}

        {(showLinux || isWindowsScope) && (
          <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-3">
            <HeroKpi label={isWindowsScope ? 'Windows Sunucu' : 'Toplam Sunucu'} value={totalServers} sub={`${onlineServers} çevrimiçi`} accent={NEON.blue} pct={onlinePct} delay={0} />
            {!isWindowsScope && (
              <HeroKpi label="AI Ready" value={aiReadyServers} sub={`${aiReadyPct.toFixed(0)}% kapsama`} accent={NEON.blue} pct={aiReadyPct} delay={50} />
            )}
            {isWindowsScope && (
              <HeroKpi label="WinRM" value={windowsServers.filter(s => s.winrm_configured).length} sub="yapılandırılmış" accent={NEON.cyan} pct={totalServers > 0 ? (windowsServers.filter(s => s.winrm_configured).length / totalServers) * 100 : 0} delay={50} />
            )}
            <HeroKpi label={isWindowsScope ? 'Erişilebilir' : 'Monitörlenen'} value={monitoredLive} sub={isWindowsScope ? `${offlineServers} offline` : `${monitoredInstalled} kurulu · ${monitoredLive} canlı`} accent={NEON.green} pct={monitorPct} delay={100} />
            <HeroKpi label="Çevrimiçi Oran" value={`${onlinePct.toFixed(0)}%`} sub={`${offlineServers} offline`} accent={NEON.green} pct={onlinePct} delay={150} />
          </div>
        )}

        {secondaryStats.length > 0 && (
          <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
            {secondaryStats.map((s, i) => (
              <StatCard key={s.label} label={s.label} value={s.value} sub={s.sub} accent={s.accent} delay={200 + i * 40} />
            ))}
          </div>
        )}

        {(showLinux || isWindowsScope || showAiops) && (
          <div className={`grid grid-cols-1 gap-4 ${(showLinux || isWindowsScope) && showAiops ? 'xl:grid-cols-3' : ''}`}>
            {(showLinux || isWindowsScope) && (
              <div className={showAiops ? 'xl:col-span-2' : ''}>
                <ResourceUsageChart metrics={metricDashboard} />
              </div>
            )}
            {showAiops && !isWindowsScope && (
              <AiOpsOverview
                eventStats={eventStats}
                incidentStats={incidentStats}
                eventsPath={eventsPath}
                incidentsPath={incidentsPath}
                anomaliesPath={anomaliesPath}
              />
            )}
          </div>
        )}

        {isWindowsScope && showAiops && (
          <AiOpsOverview
            eventStats={eventStats}
            incidentStats={incidentStats}
            eventsPath={eventsPath}
            incidentsPath={incidentsPath}
            anomaliesPath={anomaliesPath}
          />
        )}

        {(showLinux || isWindowsScope) && (
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <ServerStatusChart online={onlineServers} offline={offlineServers} warning={warningServers + criticalServers} />
            <FleetTrendChart online={onlineServers} offline={offlineServers} warning={warningServers + criticalServers} />
            <OsDistChart servers={isWindowsScope ? (windowsServers as unknown as DashboardServer[]) : (isAdminScope ? allServersRaw : servers)} />
          </div>
        )}

        {showVirt && hypervisors.some(hv => hv.type?.toLowerCase() === 'vmware') && (
          <EsxResourcePanel hypervisors={hypervisors} />
        )}

        {showAiops && digest && (
          <DigestCard digest={digest} />
        )}

        <div className={`grid grid-cols-1 gap-4 ${showAiops ? 'lg:grid-cols-3' : ''}`}>
          {showAiops && (
            <div className="lg:col-span-2">
              <ActivityFeed events={recentEventsData?.events ?? []} eventsPath={eventsPath} />
            </div>
          )}
          <QuickActionsPanel scope={scope} />
        </div>

        {(showLinux || showVirt || isWindowsScope) && (
          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            {showLinux && <RecentServers servers={(isAdminScope ? allServersRaw : servers).filter(s => s.status === 'ONLINE')} onSelect={setSelectedServer} />}
            {isWindowsScope && (
              <RecentWindowsServers servers={windowsServers.filter(s => s.status === 'ONLINE')} />
            )}
            {showVirt && <HypervisorCards hypervisors={hypervisors} />}
          </div>
        )}
      </div>

      {selectedServer && (
        <ServerDetailDrawer server={selectedServer as any} onClose={() => setSelectedServer(null)} />
      )}
    </>
  )
}

export default Dashboard
