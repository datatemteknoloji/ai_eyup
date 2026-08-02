/**
 * Yönetici Ekranı — Üst düzey yöneticiler için tüm ortamların (Linux, Windows,
 * Sanallaştırma) tek ekranda özeti. Salt görüntüleme; detay için ilgili
 * platformun Komuta Merkezi / Dashboard sayfalarına yönlendirir.
 */
import { useEffect, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
  PieChart, Pie, Cell, Legend,
} from 'recharts'
import {
  Crown, Server, Shield, Cloud, AlertTriangle, CheckCircle2,
  RefreshCw, Clock, ArrowRight, HeartPulse, Siren, BellRing,
  BrainCircuit, HardDrive, Trophy, Sparkles, Radar,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'

// ── Types ─────────────────────────────────────────────────────────────────────

interface PlatformStat {
  critical: number
  warning: number
  health_score: number
  grade: string
  label: string
  server_count?: number
  ai_ready_count?: number
  node_exporter_running?: number
  windows_exporter_running?: number
  hypervisor_count?: number
  vm_count?: number
  vm_running_count?: number
}

interface TopAlert {
  event_id: number
  platform: 'linux' | 'windows' | 'virtualization'
  server_name: string
  severity: string
  title: string
  last_seen: string | null
}

interface ExecSummary {
  generated_at: string
  overall: {
    health_score: number; grade: string; label: string
    critical_total: number; warning_total: number
    open_incidents: number; total_servers: number
  }
  platforms: { linux: PlatformStat; windows: PlatformStat; virtualization: PlatformStat }
  top_alerts: TopAlert[]
}

// ── Style helpers ────────────────────────────────────────────────────────────

const GRADE_COLOR: Record<string, string> = {
  A: 'text-green-400 border-green-500/40 bg-green-500/10',
  B: 'text-blue-400 border-blue-500/40 bg-blue-500/10',
  C: 'text-yellow-400 border-yellow-500/40 bg-yellow-500/10',
  D: 'text-orange-400 border-orange-500/40 bg-orange-500/10',
  F: 'text-red-400 border-red-500/40 bg-red-500/10',
}

const GRADE_HEX: Record<string, string> = {
  A: '#4ade80', B: '#60a5fa', C: '#facc15', D: '#fb923c', F: '#f87171',
}

// DESIGN.md: mor/violet kullanılmaz. "emergency" (critical'in üstü) aynı
// kırmızı ailesinde ama daha yoğun (red-600) bir tonla ayrıştırılır.
const SEV_BADGE: Record<string, string> = {
  emergency: 'bg-red-600/30 text-red-400 border-red-600/50',
  critical:  'bg-red-500/20 text-red-300 border-red-500/40',
  warning:   'bg-amber-500/20 text-amber-300 border-amber-500/40',
  info:      'bg-blue-500/20 text-blue-300 border-blue-500/40',
}

const SEV_STRIPE: Record<string, string> = {
  emergency: 'border-l-red-600', critical: 'border-l-red-500',
  warning: 'border-l-amber-500', info: 'border-l-blue-500',
}

const PLATFORM_META: Record<string, { label: string; icon: React.ReactNode; badge: string; hex: string; glow: string }> = {
  linux:          { label: 'Linux',         icon: <Server size={12} />, badge: 'bg-green-500/15 text-green-300 border-green-500/30',   hex: '#4ade80', glow: 'from-green-500/10' },
  windows:        { label: 'Windows',       icon: <Shield size={12} />, badge: 'bg-blue-500/15 text-blue-300 border-blue-500/30',      hex: '#60a5fa', glow: 'from-blue-500/10' },
  virtualization: { label: 'Sanallaştırma', icon: <Cloud size={12} />,  badge: 'bg-indigo-500/15 text-indigo-300 border-indigo-500/30', hex: '#818cf8', glow: 'from-indigo-500/10' },
}

const MEDAL_COLOR: Record<number, string> = { 0: '#facc15', 1: '#cbd5e1', 2: '#d97706' }

// ── Küçük yardımcı hook'lar ──────────────────────────────────────────────────

function useCountUp(target: number, duration = 900) {
  const [value, setValue] = useState(0)
  const prevTarget = useRef(0)
  useEffect(() => {
    const from = prevTarget.current
    prevTarget.current = target
    let raf: number
    const start = performance.now()
    function tick(now: number) {
      const progress = Math.min(1, (now - start) / duration)
      const eased = 1 - Math.pow(1 - progress, 3)
      setValue(Math.round(from + (target - from) * eased))
      if (progress < 1) raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [target])
  return value
}

// ── Görsel bileşenler ────────────────────────────────────────────────────────

function ScoreRing({ score, size = 150, strokeWidth = 12 }: { score: number; size?: number; strokeWidth?: number }) {
  const animated = useCountUp(score, 1100)
  const r = 42; const cx = 50; const cy = 50
  const circumference = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(100, animated)) / 100
  const offset = circumference * (1 - pct)
  const grade = score >= 90 ? 'A' : score >= 75 ? 'B' : score >= 55 ? 'C' : score >= 35 ? 'D' : 'F'
  const color = GRADE_HEX[grade]
  const gradId = `ring-grad-${size}`
  return (
    <div className="relative" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox="0 0 100 100" className="drop-shadow-[0_0_16px_rgba(96,165,250,0.15)]">
        <defs>
          <linearGradient id={gradId} x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" stopColor={color} stopOpacity={0.55} />
            <stop offset="100%" stopColor={color} stopOpacity={1} />
          </linearGradient>
        </defs>
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#1e293b" strokeWidth={strokeWidth} />
        <circle
          cx={cx} cy={cy} r={r} fill="none" stroke={`url(#${gradId})`} strokeWidth={strokeWidth}
          strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round"
          transform={`rotate(-90 ${cx} ${cy})`} style={{ transition: 'stroke-dashoffset 1s cubic-bezier(.22,1,.36,1)', filter: `drop-shadow(0 0 6px ${color}88)` }}
        />
      </svg>
      <div className="absolute inset-0 flex flex-col items-center justify-center">
        <span className="text-4xl font-extrabold text-white tabular-nums">{animated}</span>
        <span className="text-[10px] text-slate-500 -mt-1">/ 100</span>
      </div>
    </div>
  )
}

function MiniRing({ score, size = 46 }: { score: number; size?: number }) {
  const r = 40; const cx = 50; const cy = 50
  const circumference = 2 * Math.PI * r
  const pct = Math.max(0, Math.min(100, score)) / 100
  const offset = circumference * (1 - pct)
  const grade = score >= 90 ? 'A' : score >= 75 ? 'B' : score >= 55 ? 'C' : score >= 35 ? 'D' : 'F'
  const color = GRADE_HEX[grade]
  return (
    <div className="relative flex-shrink-0" style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox="0 0 100 100">
        <circle cx={cx} cy={cy} r={r} fill="none" stroke="#1e293b" strokeWidth="12" />
        <circle
          cx={cx} cy={cy} r={r} fill="none" stroke={color} strokeWidth="12"
          strokeDasharray={circumference} strokeDashoffset={offset} strokeLinecap="round"
          transform={`rotate(-90 ${cx} ${cy})`} style={{ transition: 'stroke-dashoffset 0.8s ease' }}
        />
      </svg>
      <div className="absolute inset-0 flex items-center justify-center">
        <span className="text-[13px] font-bold text-white">{score}</span>
      </div>
    </div>
  )
}

function KpiCard({ icon, label, value, tone, pulse }: {
  icon: React.ReactNode; label: string; value: number; tone: string; pulse?: boolean
}) {
  const animated = useCountUp(value)
  return (
    <div className="relative bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 flex items-center gap-3 overflow-hidden group hover:border-slate-600 transition-colors">
      <div className={`absolute -right-4 -top-4 w-16 h-16 rounded-full blur-2xl opacity-40 ${tone}`} />
      <div className={`relative w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${tone}`}>
        {pulse && value > 0 && <span className="absolute inline-flex h-full w-full rounded-lg bg-red-400 opacity-20 animate-ping" />}
        {icon}
      </div>
      <div className="min-w-0 relative">
        <div className="text-2xl font-bold text-white leading-tight tabular-nums">{animated}</div>
        <div className="text-xs text-slate-400">{label}</div>
      </div>
    </div>
  )
}

function PlatformPanel({ platformKey, stat, link, linkLabel }: {
  platformKey: 'linux' | 'windows' | 'virtualization'
  stat: PlatformStat
  link: string
  linkLabel: string
}) {
  const meta = PLATFORM_META[platformKey]
  return (
    <div className="relative bg-slate-800/60 border border-slate-700/50 rounded-xl p-5 flex flex-col gap-4 overflow-hidden hover:border-slate-600/80 transition-all group">
      <div className={`absolute inset-x-0 top-0 h-24 bg-gradient-to-b ${meta.glow} to-transparent pointer-events-none opacity-0 group-hover:opacity-100 transition-opacity`} />
      <div className="flex items-start justify-between relative">
        <div className="flex items-center gap-2">
          <div className={`w-9 h-9 rounded-lg border flex items-center justify-center ${meta.badge}`}>{meta.icon}</div>
          <div>
            <h3 className="text-white font-semibold text-sm">{meta.label}</h3>
            <p className="text-slate-500 text-[11px]">
              {platformKey === 'virtualization'
                ? `${stat.hypervisor_count ?? 0} hypervisor · ${stat.vm_running_count ?? 0}/${stat.vm_count ?? 0} VM çalışıyor`
                : `${stat.server_count ?? 0} sunucu`}
            </p>
          </div>
        </div>
        <MiniRing score={stat.health_score} />
      </div>

      <div className="grid grid-cols-2 gap-2 relative">
        <div className="bg-red-500/10 border border-red-500/20 rounded-lg px-3 py-2">
          <div className="text-lg font-bold text-red-300 tabular-nums">{stat.critical}</div>
          <div className="text-[10px] text-red-400/80">Kritik Alarm</div>
        </div>
        <div className="bg-amber-500/10 border border-amber-500/20 rounded-lg px-3 py-2">
          <div className="text-lg font-bold text-amber-300 tabular-nums">{stat.warning}</div>
          <div className="text-[10px] text-amber-400/80">Uyarı</div>
        </div>
      </div>

      {platformKey !== 'virtualization' && (
        <div className="flex items-center gap-3 text-[11px] text-slate-400 relative">
          <span className="flex items-center gap-1"><BrainCircuit size={11} /> AI Ready: {stat.ai_ready_count ?? 0}</span>
          <span className="flex items-center gap-1">
            <HeartPulse size={11} />
            {platformKey === 'linux' ? `node_exporter: ${stat.node_exporter_running ?? 0}` : `windows_exporter: ${stat.windows_exporter_running ?? 0}`}
          </span>
        </div>
      )}

      <Link to={link} className="relative mt-auto flex items-center justify-center gap-1.5 text-xs font-medium text-blue-400 hover:text-blue-300 border border-blue-500/20 hover:border-blue-500/40 bg-blue-600/10 hover:bg-blue-600/20 rounded-lg px-3 py-2 transition-all">
        {linkLabel} <ArrowRight size={12} className="group-hover:translate-x-0.5 transition-transform" />
      </Link>
    </div>
  )
}

function CustomBarTooltip({ active, payload, label }: any) {
  if (!active || !payload?.length) return null
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
      <div className="text-slate-300 font-medium mb-1">{label}</div>
      {payload.map((p: any) => (
        <div key={p.dataKey} className="flex items-center gap-2" style={{ color: p.fill }}>
          <span className="w-2 h-2 rounded-full" style={{ background: p.fill }} />
          {p.dataKey}: <span className="font-semibold">{p.value}</span>
        </div>
      ))}
    </div>
  )
}

function CustomPieTooltip({ active, payload }: any) {
  if (!active || !payload?.length) return null
  const p = payload[0]
  return (
    <div className="bg-slate-900 border border-slate-700 rounded-lg px-3 py-2 text-xs shadow-xl">
      <span className="font-semibold" style={{ color: p.payload.fill }}>{p.name}</span>: {p.value}
    </div>
  )
}

// ── Main Page ─────────────────────────────────────────────────────────────────

export default function ExecutiveDashboard() {
  const { data, isLoading, isFetching, refetch, dataUpdatedAt } = useQuery<ExecSummary>({
    queryKey: ['executive-summary'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/ops/executive-summary`)
      if (!r.ok) throw new Error(`HTTP ${r.status}`)
      return r.json()
    },
    refetchInterval: 30_000,
  })

  if (isLoading) {
    return (
      <div className="p-6 flex items-center justify-center h-64 text-slate-400 text-sm gap-2">
        <RefreshCw size={16} className="animate-spin" /> Yönetici özeti yükleniyor...
      </div>
    )
  }

  if (!data) {
    return (
      <div className="p-6 text-center text-slate-500 text-sm">Veri alınamadı. Lütfen tekrar deneyin.</div>
    )
  }

  const { overall, platforms, top_alerts } = data

  const comparisonData = [
    { name: 'Linux', Kritik: platforms.linux.critical, Uyarı: platforms.linux.warning },
    { name: 'Windows', Kritik: platforms.windows.critical, Uyarı: platforms.windows.warning },
    { name: 'Sanallaştırma', Kritik: platforms.virtualization.critical, Uyarı: platforms.virtualization.warning },
  ]

  const assetData = [
    { name: 'Linux Sunucu', value: platforms.linux.server_count ?? 0, fill: PLATFORM_META.linux.hex },
    { name: 'Windows Sunucu', value: platforms.windows.server_count ?? 0, fill: PLATFORM_META.windows.hex },
    { name: 'Sanallaştırma VM', value: platforms.virtualization.vm_count ?? 0, fill: PLATFORM_META.virtualization.hex },
  ].filter(d => d.value > 0)

  // Riskli varlıklar için tekilleştirilmiş liderlik tablosu (ilk 5 farklı sunucu)
  const seen = new Set<string>()
  const leaderboard: TopAlert[] = []
  for (const a of top_alerts) {
    const key = `${a.platform}:${a.server_name}`
    if (seen.has(key)) continue
    seen.add(key)
    leaderboard.push(a)
    if (leaderboard.length >= 5) break
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="relative overflow-hidden rounded-2xl border border-amber-500/20 bg-gradient-to-br from-amber-500/10 via-slate-800/60 to-slate-800/60 p-5">
        <div className="absolute -right-10 -top-16 w-56 h-56 rounded-full bg-amber-500/10 blur-3xl pointer-events-none" />
        <div className="flex items-center justify-between relative">
          <div className="flex items-center gap-3">
            <div className="w-11 h-11 rounded-xl bg-amber-500/15 border border-amber-500/30 flex items-center justify-center shadow-[0_0_20px_rgba(245,158,11,0.15)]">
              <Crown size={20} className="text-amber-400" />
            </div>
            <div>
              <h1 className="text-2xl font-bold text-white flex items-center gap-2">
                Yönetici Ekranı
                <span className="flex items-center gap-1 text-[10px] font-semibold text-emerald-300 bg-emerald-500/10 border border-emerald-500/30 rounded-full px-2 py-0.5">
                  <span className="relative flex h-1.5 w-1.5">
                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75" />
                    <span className="relative inline-flex rounded-full h-1.5 w-1.5 bg-emerald-400" />
                  </span>
                  CANLI
                </span>
              </h1>
              <p className="text-slate-400 text-sm mt-0.5">Linux, Windows ve Sanallaştırma ortamlarının tek ekranda özeti</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-xs text-slate-500 flex items-center gap-1.5">
              <Clock size={12} />
              Son güncelleme: {dataUpdatedAt ? new Date(dataUpdatedAt).toLocaleTimeString('tr-TR') : '-'}
            </span>
            <button
              onClick={() => refetch()}
              disabled={isFetching}
              className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-lg bg-slate-700 hover:bg-slate-600 text-slate-200 transition-all disabled:opacity-50"
            >
              <RefreshCw size={12} className={isFetching ? 'animate-spin' : ''} /> Yenile
            </button>
          </div>
        </div>
      </div>

      {/* Genel Sağlık + KPI'lar */}
      <div className="grid grid-cols-1 lg:grid-cols-[auto_1fr] gap-4">
        <div className="relative bg-slate-800/60 border border-slate-700/50 rounded-xl p-6 flex flex-col items-center justify-center gap-2 min-w-[240px] overflow-hidden">
          <div className="absolute inset-0 bg-gradient-to-b from-white/[0.02] to-transparent pointer-events-none" />
          <ScoreRing score={overall.health_score} />
          <span className={`text-xs font-semibold px-2.5 py-1 rounded-lg border ${GRADE_COLOR[overall.grade] || GRADE_COLOR.C}`}>
            {overall.grade} · {overall.label}
          </span>
          <span className="text-[11px] text-slate-500">Genel Altyapı Sağlık Skoru</span>
        </div>

        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <KpiCard icon={<Siren size={18} className="text-red-300" />} label="Toplam Kritik Alarm" value={overall.critical_total} tone="bg-red-500/15" pulse />
          <KpiCard icon={<AlertTriangle size={18} className="text-amber-300" />} label="Toplam Uyarı" value={overall.warning_total} tone="bg-amber-500/15" />
          <KpiCard icon={<BellRing size={18} className="text-orange-300" />} label="Açık Olay (Incident)" value={overall.open_incidents} tone="bg-orange-500/15" />
          <KpiCard icon={<HardDrive size={18} className="text-cyan-300" />} label="Toplam Sunucu" value={overall.total_servers} tone="bg-cyan-500/15" />
        </div>
      </div>

      {/* Grafikler: Kritik/Uyarı Karşılaştırma + Envanter Dağılımı */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <div className="lg:col-span-3 bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
          <h2 className="text-slate-300 text-sm font-medium mb-4 flex items-center gap-2">
            <Radar size={14} className="text-blue-400" /> Ortamlar Arası Alarm Karşılaştırması
          </h2>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={comparisonData} barGap={6}>
              <CartesianGrid strokeDasharray="3 3" stroke="#334155" vertical={false} />
              <XAxis dataKey="name" tick={{ fill: '#94a3b8', fontSize: 12 }} axisLine={{ stroke: '#334155' }} tickLine={false} />
              <YAxis tick={{ fill: '#94a3b8', fontSize: 11 }} axisLine={false} tickLine={false} allowDecimals={false} />
              <Tooltip content={<CustomBarTooltip />} cursor={{ fill: 'rgba(255,255,255,0.03)' }} />
              <Legend wrapperStyle={{ fontSize: 12, color: '#94a3b8' }} />
              <Bar dataKey="Kritik" fill="#f87171" radius={[6, 6, 0, 0]} maxBarSize={42} />
              <Bar dataKey="Uyarı" fill="#fbbf24" radius={[6, 6, 0, 0]} maxBarSize={42} />
            </BarChart>
          </ResponsiveContainer>
        </div>

        <div className="lg:col-span-2 bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
          <h2 className="text-slate-300 text-sm font-medium mb-2 flex items-center gap-2">
            <Sparkles size={14} className="text-indigo-400" /> Envanter Dağılımı
          </h2>
          {assetData.length === 0 ? (
            <div className="h-[190px] flex items-center justify-center text-slate-600 text-xs">Envanter verisi yok</div>
          ) : (
            <ResponsiveContainer width="100%" height={190}>
              <PieChart>
                <Pie data={assetData} dataKey="value" nameKey="name" innerRadius={48} outerRadius={72} paddingAngle={3} strokeWidth={0}>
                  {assetData.map((d, i) => <Cell key={i} fill={d.fill} />)}
                </Pie>
                <Tooltip content={<CustomPieTooltip />} />
                <Legend wrapperStyle={{ fontSize: 11, color: '#94a3b8' }} layout="vertical" verticalAlign="middle" align="right" />
              </PieChart>
            </ResponsiveContainer>
          )}
          <p className="text-[10px] text-slate-600 mt-1 leading-relaxed">
            Not: VM sayısı, guest OS'e göre Linux/Windows sunucu sayımlarıyla örtüşebilir.
          </p>
        </div>
      </div>

      {/* Platform panelleri */}
      <div>
        <h2 className="text-slate-300 text-sm font-medium mb-3">Ortamlar</h2>
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
          <PlatformPanel platformKey="linux" stat={platforms.linux} link="/linux/ops" linkLabel="Linux Komuta Merkezi" />
          <PlatformPanel platformKey="windows" stat={platforms.windows} link="/windows/aiops/ops" linkLabel="Windows Komuta Merkezi" />
          <PlatformPanel platformKey="virtualization" stat={platforms.virtualization} link="/virt/ops" linkLabel="Sanallaştırma Komuta Merkezi" />
        </div>
      </div>

      {/* Risk liderlik tablosu + Detaylı olay listesi */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-4">
        <div className="lg:col-span-2 bg-slate-800/60 border border-slate-700/50 rounded-xl p-5">
          <h2 className="text-slate-300 text-sm font-medium mb-4 flex items-center gap-2">
            <Trophy size={14} className="text-amber-400" /> Risk Liderlik Tablosu
          </h2>
          {leaderboard.length === 0 ? (
            <div className="flex items-center justify-center gap-2 text-slate-500 text-sm py-8">
              <CheckCircle2 size={16} className="text-green-400" /> Aktif risk yok
            </div>
          ) : (
            <div className="space-y-2">
              {leaderboard.map((a, i) => {
                const meta = PLATFORM_META[a.platform]
                return (
                  <div key={a.event_id} className={`flex items-center gap-3 bg-slate-900/40 border-l-4 ${SEV_STRIPE[a.severity] || SEV_STRIPE.info} border-y border-r border-slate-700/40 rounded-r-lg px-3 py-2.5`}>
                    <span className="w-6 flex items-center justify-center flex-shrink-0">
                      {MEDAL_COLOR[i]
                        ? <Trophy size={15} strokeWidth={2} style={{ color: MEDAL_COLOR[i] }} />
                        : <span className="text-slate-500 text-xs">#{i + 1}</span>}
                    </span>
                    <div className="min-w-0 flex-1">
                      <div className="flex items-center gap-1.5">
                        <span className="text-white text-sm font-medium truncate">{a.server_name}</span>
                        <span className={`inline-flex items-center gap-1 text-[9px] px-1.5 py-0.5 rounded-full border flex-shrink-0 ${meta?.badge || ''}`}>
                          {meta?.icon} {meta?.label}
                        </span>
                      </div>
                      <p className="text-[11px] text-slate-500 truncate" title={a.title}>{a.title}</p>
                    </div>
                    <span className={`text-[10px] px-2 py-0.5 rounded-full border flex-shrink-0 ${SEV_BADGE[a.severity] || SEV_BADGE.info}`}>
                      {a.severity}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>

        <div className="lg:col-span-3">
          <h2 className="text-slate-300 text-sm font-medium mb-3">En Kritik Olaylar (Tüm Ortamlar)</h2>
          <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl overflow-hidden">
            {top_alerts.length === 0 ? (
              <div className="flex items-center justify-center gap-2 text-slate-500 text-sm py-10">
                <CheckCircle2 size={16} className="text-green-400" /> Aktif kritik/uyarı olayı yok
              </div>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-slate-700/50 text-xs text-slate-500">
                    <th className="text-left px-4 py-2">Ortam</th>
                    <th className="text-left px-4 py-2">Sunucu / Kaynak</th>
                    <th className="text-left px-4 py-2">Olay</th>
                    <th className="text-left px-4 py-2">Önem</th>
                    <th className="text-left px-4 py-2">Son Görülme</th>
                  </tr>
                </thead>
                <tbody>
                  {top_alerts.map(a => {
                    const meta = PLATFORM_META[a.platform]
                    return (
                      <tr key={a.event_id} className="border-b border-slate-700/30 hover:bg-slate-700/20 transition-colors">
                        <td className="px-4 py-2.5">
                          <span className={`inline-flex items-center gap-1 text-[10px] px-2 py-0.5 rounded-full border ${meta?.badge || ''}`}>
                            {meta?.icon} {meta?.label || a.platform}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-white">{a.server_name}</td>
                        <td className="px-4 py-2.5 text-slate-300 max-w-xs truncate" title={a.title}>{a.title}</td>
                        <td className="px-4 py-2.5">
                          <span className={`text-[10px] px-2 py-0.5 rounded-full border ${SEV_BADGE[a.severity] || SEV_BADGE.info}`}>
                            {a.severity}
                          </span>
                        </td>
                        <td className="px-4 py-2.5 text-slate-500 text-xs">
                          {a.last_seen ? new Date(a.last_seen).toLocaleString('tr-TR') : '-'}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </div>
        </div>
      </div>
    </div>
  )
}
