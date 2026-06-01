import React, { useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  PieChart, Pie, Cell, Tooltip, ResponsiveContainer,
} from 'recharts'
import { API_BASE_URL } from '../config/api'
import { ServerDetailDrawer } from './Servers'

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

// ── Design tokens ─────────────────────────────────────────────────────────
const NEON = {
  cyan:   '#22d3ee', blue:   '#3b82f6', purple: '#a855f7',
  green:  '#10b981', orange: '#f59e0b', red:    '#ef4444', pink: '#ec4899',
}

// ── Neon Stat Card ────────────────────────────────────────────────────────
function StatCard({
  label, value, sub, icon, accent, delay = 0
}: {
  label: string; value: string | number; sub?: string
  icon: React.ReactNode; accent: string; delay?: number
}) {
  return (
    <div
      className="stat-card animate-fade-in"
      style={{
        '--accent-color': accent,
        animationDelay: `${delay}ms`,
        background: 'var(--bg-card)',
        border: `1px solid rgba(${hexToRgb(accent)}, 0.2)`,
        borderRadius: 12,
        padding: '18px 20px',
        position: 'relative',
        overflow: 'hidden',
        transition: 'all 0.25s ease',
      } as React.CSSProperties}
      onMouseEnter={e => {
        const el = e.currentTarget
        el.style.borderColor = `rgba(${hexToRgb(accent)}, 0.5)`
        el.style.boxShadow = `0 0 24px rgba(${hexToRgb(accent)}, 0.2), 0 8px 32px rgba(0,0,0,0.4)`
        el.style.transform = 'translateY(-2px)'
      }}
      onMouseLeave={e => {
        const el = e.currentTarget
        el.style.borderColor = `rgba(${hexToRgb(accent)}, 0.2)`
        el.style.boxShadow = 'none'
        el.style.transform = 'translateY(0)'
      }}
    >
      {/* Top accent glow */}
      <div style={{
        position: 'absolute', top: 0, left: 0, right: 0, height: 1,
        background: `linear-gradient(90deg, transparent, ${accent}80, transparent)`,
      }} />
      {/* Bottom accent bar */}
      <div style={{
        position: 'absolute', bottom: 0, left: 0, right: 0, height: 2,
        background: accent, opacity: 0.5, borderRadius: '0 0 12px 12px',
      }} />
      {/* Bg glow blob */}
      <div style={{
        position: 'absolute', bottom: -20, right: -20,
        width: 80, height: 80, borderRadius: '50%',
        background: `radial-gradient(circle, rgba(${hexToRgb(accent)}, 0.12), transparent 70%)`,
        pointerEvents: 'none',
      }} />

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
          {icon}
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
          <DonutGauge pct={ramPct} color={NEON.purple} size={68} strokeWidth={6} />
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
      <div className="px-5 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid rgba(99,130,194,0.1)' }}>
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
            <div className="animate-spin rounded-full h-3 w-3 border border-b-cyan-400 border-slate-700" />
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
    rhel: NEON.red, centos: NEON.purple, ubuntu: NEON.orange,
    debian: NEON.pink, rocky: NEON.blue, oracle: NEON.cyan, windows: NEON.blue,
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
        <div className="w-1.5 h-4 rounded-full" style={{ background: NEON.purple }} />
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
      <div className="px-5 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid rgba(99,130,194,0.1)' }}>
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-4 rounded-full" style={{ background: NEON.green }} />
          <h2 className="text-sm font-semibold text-white">Çevrimiçi Sunucular</h2>
        </div>
        <Link
          to="/servers"
          className="text-xs font-medium transition-colors"
          style={{ color: 'rgba(34,211,238,0.7)' }}
          onMouseEnter={e => (e.currentTarget.style.color = NEON.cyan)}
          onMouseLeave={e => (e.currentTarget.style.color = 'rgba(34,211,238,0.7)')}
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
                  {server.ai_ready && (
                    <span className="px-1.5 py-0.5 rounded text-[9px] font-medium flex-shrink-0"
                      style={{ background: 'rgba(168,85,247,0.12)', color: NEON.purple, border: '1px solid rgba(168,85,247,0.25)' }}>
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

// ── Hypervisor Cards ───────────────────────────────────────────────────────
function HypervisorCards({ hypervisors }: { hypervisors: Hypervisor[] }) {
  if (hypervisors.length === 0) return null
  return (
    <div className="cyber-card animate-fade-in">
      <div className="px-5 py-4 flex items-center justify-between" style={{ borderBottom: '1px solid rgba(99,130,194,0.1)' }}>
        <div className="flex items-center gap-2">
          <div className="w-1.5 h-4 rounded-full" style={{ background: NEON.blue }} />
          <h2 className="text-sm font-semibold text-white">Hypervisor'lar</h2>
        </div>
        <Link
          to="/hypervisors"
          className="text-xs font-medium"
          style={{ color: 'rgba(34,211,238,0.7)' }}
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
                className="w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 text-lg"
                style={{ background: `rgba(${hexToRgb(accent)},0.1)` }}
              >
                {isVmware ? '🖧' : isOvirt ? '🐧' : '☁️'}
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
const Dashboard: React.FC = () => {
  const [selectedServer, setSelectedServer] = useState<DashboardServer | null>(null)

  const { data: servers = [], isLoading: serversLoading } = useQuery<DashboardServer[]>({
    queryKey: ['servers'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/servers/`)
      if (!r.ok) throw new Error('Failed to fetch servers')
      return r.json()
    },
    refetchInterval: 30_000,
  })

  const { data: hypervisors = [], isLoading: hypervisorsLoading } = useQuery<Hypervisor[]>({
    queryKey: ['hypervisors'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/`)
      if (!r.ok) throw new Error('Failed to fetch hypervisors')
      return r.json()
    },
  })

  if (serversLoading || hypervisorsLoading) {
    return (
      <div className="h-64 flex flex-col items-center justify-center gap-4">
        <div className="relative w-12 h-12">
          <div className="absolute inset-0 rounded-full border-2 border-cyan-500/20 animate-ping" />
          <div className="absolute inset-0 rounded-full border-2 border-t-cyan-400 animate-spin" />
        </div>
        <p className="text-xs text-slate-500 tracking-widest uppercase">Sistem Yükleniyor...</p>
      </div>
    )
  }

  const totalServers   = servers.length
  const onlineServers  = servers.filter(s => s.status === 'ONLINE').length
  const offlineServers = servers.filter(s => s.status === 'OFFLINE').length
  const warningServers = servers.filter(s => s.status === 'WARNING').length
  const criticalServers= servers.filter(s => s.status === 'CRITICAL').length
  const aiReadyServers = servers.filter(s => s.ai_ready).length
  const totalCpu       = servers.reduce((sum, s) => sum + (s.cpu_cores || 0), 0)
  const totalRam       = servers.reduce((sum, s) => sum + (s.memory_gb || 0), 0)
  const monitoredCount = servers.filter(s => s.node_exporter?.running).length

  const statCards = [
    {
      label: 'Toplam Sunucu',    value: totalServers,
      sub: `${onlineServers} çevrimiçi`,
      accent: NEON.cyan,
      icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-6 h-6"><rect x="2" y="3" width="20" height="5" rx="1"/><rect x="2" y="10" width="20" height="5" rx="1"/><rect x="2" y="17" width="20" height="5" rx="1"/></svg>,
    },
    {
      label: 'Çevrimiçi',        value: onlineServers,
      sub: `${totalServers > 0 ? ((onlineServers/totalServers)*100).toFixed(0) : 0}% aktif`,
      accent: NEON.green,
      icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-6 h-6"><polyline points="20 6 9 17 4 12"/></svg>,
    },
    {
      label: 'AI Ready',         value: aiReadyServers,
      sub: `${totalServers > 0 ? ((aiReadyServers/totalServers)*100).toFixed(0) : 0}% kapsama`,
      accent: NEON.purple,
      icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-6 h-6"><path d="M12 2a2 2 0 0 1 2 2c0 .74-.4 1.39-1 1.73V7h1a7 7 0 0 1 7 7h1a1 1 0 0 1 1 1v3a1 1 0 0 1-1 1h-1v1a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-1H2a1 1 0 0 1-1-1v-3a1 1 0 0 1 1-1h1a7 7 0 0 1 7-7h1V5.73c-.6-.34-1-.99-1-1.73a2 2 0 0 1 2-2M9 14a1 1 0 1 0 0 2 1 1 0 0 0 0-2m6 0a1 1 0 1 0 0 2 1 1 0 0 0 0-2z"/></svg>,
    },
    {
      label: 'Monitörlenen',     value: monitoredCount,
      sub: `${totalServers > 0 ? ((monitoredCount/totalServers)*100).toFixed(0) : 0}% exporter aktif`,
      accent: NEON.blue,
      icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-6 h-6"><polyline points="22 12 18 12 15 21 9 3 6 12 2 12"/></svg>,
    },
    {
      label: 'Hypervisor',       value: hypervisors.length,
      sub: `${hypervisors.filter(h=>h.type?.toLowerCase()==='vmware').length} VMware / ${hypervisors.filter(h=>h.type?.toLowerCase().includes('ovirt')||h.type?.toLowerCase().includes('olvm')).length} oVirt`,
      accent: NEON.blue,
      icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-6 h-6"><path d="M18 10h-1.26A8 8 0 1 0 9 20h9a5 5 0 0 0 0-10z"/></svg>,
    },
    {
      label: 'Toplam CPU',       value: totalCpu,
      sub: 'toplam çekirdek',
      accent: NEON.orange,
      icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-6 h-6"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><line x1="9" y1="2" x2="9" y2="4"/><line x1="15" y1="2" x2="15" y2="4"/><line x1="9" y1="20" x2="9" y2="22"/><line x1="15" y1="20" x2="15" y2="22"/><line x1="20" y1="9" x2="22" y2="9"/><line x1="20" y1="14" x2="22" y2="14"/><line x1="2" y1="9" x2="4" y2="9"/><line x1="2" y1="14" x2="4" y2="14"/></svg>,
    },
    {
      label: 'Toplam RAM',       value: `${totalRam} GB`,
      sub: 'envanter toplamı',
      accent: NEON.pink,
      icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-6 h-6"><path d="M6 19v-3M10 19v-3M14 19v-3M18 19v-3M8 11V9M12 11V9M16 11V9M20 13H4a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h16a2 2 0 0 1 2 2v4a2 2 0 0 1-2 2z"/></svg>,
    },
    {
      label: 'Uyarı / Kritik',   value: warningServers + criticalServers,
      sub: `${warningServers} uyarı, ${criticalServers} kritik`,
      accent: warningServers + criticalServers > 0 ? NEON.red : '#64748b',
      icon: <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={1.5} className="w-6 h-6"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>,
    },
  ]

  return (
    <>
      <div className="space-y-5 animate-fade-in">
        {/* ── Stat Cards ────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          {statCards.map((s, i) => (
            <StatCard key={i} {...s} delay={i * 50} />
          ))}
        </div>

        {/* ── ESX Resources ─────────────────────────────────────────── */}
        {hypervisors.some(hv => hv.type?.toLowerCase() === 'vmware') && (
          <EsxResourcePanel hypervisors={hypervisors} />
        )}

        {/* ── Middle row ────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <ServerStatusChart online={onlineServers} offline={offlineServers} warning={warningServers + criticalServers} />
          <OsDistChart servers={servers} />

          {/* Quick Actions */}
          <div className="cyber-card p-5 animate-fade-in">
            <div className="flex items-center gap-2 mb-4">
              <div className="w-1.5 h-4 rounded-full" style={{ background: NEON.orange }} />
              <h2 className="text-sm font-semibold text-white">Hızlı Erişim</h2>
            </div>
            <div className="grid grid-cols-2 gap-2">
              {[
                { label: 'AI Chat',    to: '/chat',         accent: NEON.purple, icon: '🤖' },
                { label: 'Güncelle',   to: '/system-update',accent: NEON.orange, icon: '🔄' },
                { label: 'Repo',       to: '/repositories', accent: NEON.cyan,   icon: '🗄️' },
                { label: 'Metrikler',  to: '/metrics',      accent: NEON.green,  icon: '📈' },
                { label: 'Ansible',    to: '/ansible',      accent: NEON.orange, icon: '⚡' },
                { label: 'Ayarlar',    to: '/settings',     accent: '#64748b',   icon: '⚙️' },
              ].map(btn => (
                <Link
                  key={btn.to}
                  to={btn.to}
                  className="flex items-center gap-2.5 px-3 py-2.5 rounded-lg transition-all"
                  style={{
                    background: `rgba(${hexToRgb(btn.accent)},0.07)`,
                    border: `1px solid rgba(${hexToRgb(btn.accent)},0.15)`,
                    color: btn.accent,
                  }}
                  onMouseEnter={e => {
                    e.currentTarget.style.background = `rgba(${hexToRgb(btn.accent)},0.15)`
                    e.currentTarget.style.borderColor = `rgba(${hexToRgb(btn.accent)},0.4)`
                  }}
                  onMouseLeave={e => {
                    e.currentTarget.style.background = `rgba(${hexToRgb(btn.accent)},0.07)`
                    e.currentTarget.style.borderColor = `rgba(${hexToRgb(btn.accent)},0.15)`
                  }}
                >
                  <span>{btn.icon}</span>
                  <span className="text-xs font-medium text-white">{btn.label}</span>
                </Link>
              ))}
            </div>
          </div>
        </div>

        {/* ── Bottom row ────────────────────────────────────────────── */}
        <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
          <RecentServers servers={servers.filter(s => s.status === 'ONLINE')} onSelect={setSelectedServer} />
          <HypervisorCards hypervisors={hypervisors} />
        </div>
      </div>

      {selectedServer && (
        <ServerDetailDrawer server={selectedServer as any} onClose={() => setSelectedServer(null)} />
      )}
    </>
  )
}

export default Dashboard
