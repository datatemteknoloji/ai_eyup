/**
 * Ortak Komuta Merkezi kabuğu — tüm platformlarda aynı header / KPI / alt nav.
 * Orta alan (children) ve sağ rail platforma özel kalır.
 */
import React, { useEffect, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  Activity, BellOff, RefreshCw, ScanSearch, ShieldAlert, Siren, AlertTriangle, CheckCircle2,
} from 'lucide-react'
import {
  PLATFORM_AIOPS_LABEL,
  PLATFORM_AIOPS_PREFIX,
  type PlatformKey,
} from '../../config/platformAiops'

export function OpsPlatformBanner({
  platform,
  hint,
}: {
  platform: PlatformKey
  hint?: string
}) {
  return (
    <div className="mb-0 px-4 py-2 rounded-xl bg-slate-800/80 border border-slate-700/60 text-sm text-slate-300">
      <span className="text-slate-500">Platform:</span>{' '}
      <span className="font-medium text-white">{PLATFORM_AIOPS_LABEL[platform]}</span>
      <span className="text-slate-500 ml-2">
        — {hint || 'Komuta Merkezi · kendi kaynaklarından izleme'}
      </span>
    </div>
  )
}

export function OpsHealthRing({
  score,
  label,
  subtitle = 'Sistem Sağlığı',
}: {
  score: number
  label: string
  subtitle?: string
}) {
  const color =
    score >= 90 ? '#4ade80' : score >= 75 ? '#60a5fa' : score >= 55 ? '#facc15' : score >= 35 ? '#fb923c' : '#f87171'
  const r = 22
  const circ = 2 * Math.PI * r
  const dash = circ * (Math.min(100, Math.max(0, score)) / 100)
  return (
    <div className="flex items-center gap-3">
      <div className="relative w-14 h-14 shrink-0">
        <svg className="w-14 h-14 -rotate-90" viewBox="0 0 52 52">
          <circle cx="26" cy="26" r={r} fill="none" strokeWidth="4" stroke="#1e293b" />
          <circle
            cx="26"
            cy="26"
            r={r}
            fill="none"
            strokeWidth="4"
            stroke={color}
            strokeDasharray={`${dash} ${circ}`}
            strokeLinecap="round"
          />
        </svg>
        <div className="absolute inset-0 flex items-center justify-center">
          <span className="text-sm font-bold" style={{ color }}>
            {score}
          </span>
        </div>
      </div>
      <div>
        <div className="text-sm font-semibold text-white">{label}</div>
        <div className="text-xs text-slate-500 mt-0.5">{subtitle}</div>
      </div>
    </div>
  )
}

type KpiTone = 'critical' | 'warning' | 'ok' | 'neutral'

export function OpsKpiChip({
  value,
  label,
  tone,
  icon,
}: {
  value: number | string
  label: string
  tone: KpiTone
  icon?: React.ReactNode
}) {
  const active =
    typeof value === 'number' ? value > 0 : String(value) !== '0' && String(value) !== '—'
  const toneClass =
    tone === 'critical'
      ? active
        ? 'border-red-500/50 bg-red-500/10'
        : 'border-slate-700 bg-slate-800/40'
      : tone === 'warning'
        ? active
          ? 'border-amber-500/40 bg-amber-500/8'
          : 'border-slate-700 bg-slate-800/40'
        : tone === 'ok'
          ? 'border-green-500/20 bg-green-500/5'
          : 'border-slate-700 bg-slate-800/40'
  const valueClass =
    tone === 'critical'
      ? active
        ? 'text-red-400'
        : 'text-slate-600'
      : tone === 'warning'
        ? active
          ? 'text-amber-400'
          : 'text-slate-600'
        : tone === 'ok'
          ? 'text-green-400'
          : 'text-slate-300'
  return (
    <div className={`px-4 py-2.5 rounded-xl border text-center min-w-[72px] transition-colors ${toneClass}`}>
      <div className={`text-2xl font-bold ${valueClass}`}>{value}</div>
      <div className="text-[10px] text-slate-500 mt-0.5 flex items-center justify-center gap-1">
        {icon}
        {label}
      </div>
    </div>
  )
}

export function OpsRefreshCountdown({
  onRefresh,
  interval = 30,
}: {
  onRefresh: () => void
  interval?: number
}) {
  const [remaining, setRemaining] = useState(interval)
  const startRef = useRef(Date.now())

  useEffect(() => {
    const id = setInterval(() => {
      const elapsed = Math.floor((Date.now() - startRef.current) / 1000)
      const rem = interval - (elapsed % interval)
      setRemaining(rem)
      if (rem === interval) onRefresh()
    }, 1000)
    return () => clearInterval(id)
  }, [onRefresh, interval])

  const pct = (remaining / interval) * 100
  return (
    <button
      type="button"
      onClick={() => {
        startRef.current = Date.now()
        setRemaining(interval)
        onRefresh()
      }}
      className="flex items-center gap-2 px-3 py-2 rounded-xl border border-slate-700 text-slate-400 hover:text-white hover:border-slate-500 transition-colors group"
    >
      <div className="relative w-5 h-5">
        <svg className="w-5 h-5 -rotate-90" viewBox="0 0 20 20">
          <circle cx="10" cy="10" r="8" fill="none" strokeWidth="2" stroke="#334155" />
          <circle
            cx="10"
            cy="10"
            r="8"
            fill="none"
            strokeWidth="2"
            stroke="#64748b"
            strokeDasharray={`${50.3 * (pct / 100)} 50.3`}
            strokeLinecap="round"
          />
        </svg>
        <RefreshCw size={10} className="absolute inset-0 m-auto group-hover:text-cyan-400 transition-colors" />
      </div>
      <span className="text-xs">{remaining}s</span>
    </button>
  )
}

export function OpsBottomNav({ platform }: { platform: PlatformKey }) {
  const base = PLATFORM_AIOPS_PREFIX[platform]
  const items = [
    { to: `${base}/events`, icon: <Activity size={13} />, label: 'Events' },
    { to: `${base}/incidents`, icon: <Siren size={13} />, label: 'Incidents' },
    { to: `${base}/analysis?tab=baseline`, icon: <BellOff size={13} />, label: 'Baseline' },
    { to: `${base}/analysis?tab=rca`, icon: <ScanSearch size={13} />, label: 'Kök Neden' },
  ]
  return (
    <div className="grid grid-cols-4 gap-2 pt-4 border-t border-slate-800/60">
      {items.map(({ to, icon, label }) => (
        <Link
          key={to}
          to={to}
          className="flex items-center justify-center gap-1.5 text-xs py-2.5 rounded-xl border border-slate-800 text-slate-500 hover:bg-slate-800 hover:text-slate-300 hover:border-slate-700 transition-colors"
        >
          {icon} {label}
        </Link>
      ))}
    </div>
  )
}

export type OpsShellKpi = {
  critical: number
  warning: number
  /** Üçüncü kart: Linux green / Virt VM aktif vb. */
  tertiaryValue: number | string
  tertiaryLabel: string
}

export function OpsShell({
  platform,
  health,
  healthSubtitle,
  kpi,
  headerActions,
  metaRow,
  filterBar,
  children,
  sideRail,
  loading,
  loadingLabel = 'Alarm durumu yükleniyor…',
}: {
  platform: PlatformKey
  health?: { score: number; label: string } | null
  healthSubtitle?: string
  kpi: OpsShellKpi
  headerActions?: React.ReactNode
  metaRow?: React.ReactNode
  filterBar?: React.ReactNode
  children: React.ReactNode
  sideRail?: React.ReactNode
  loading?: boolean
  loadingLabel?: string
}) {
  if (loading) {
    return (
      <div className="flex items-center justify-center h-full min-h-[280px]">
        <div className="text-center space-y-3">
          <div className="w-10 h-10 rounded-full border-2 border-t-cyan-400 border-r-transparent animate-spin mx-auto" />
          <p className="text-slate-400 text-sm">{loadingLabel}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full min-h-0 bg-slate-950">
      <div className="flex-none px-4 sm:px-6 pt-3 pb-2">
        <OpsPlatformBanner platform={platform} />
      </div>

      <div className="flex-none px-4 sm:px-6 py-3 border-b border-slate-800/60 bg-slate-900/60">
        <div className="flex items-center gap-4 flex-wrap">
          {health && (
            <OpsHealthRing
              score={health.score}
              label={health.label}
              subtitle={healthSubtitle}
            />
          )}
          <div className="flex gap-2 sm:gap-3">
            <OpsKpiChip
              value={kpi.critical}
              label="Kritik"
              tone="critical"
              icon={<ShieldAlert size={10} />}
            />
            <OpsKpiChip
              value={kpi.warning}
              label="Uyarı"
              tone="warning"
              icon={<AlertTriangle size={10} />}
            />
            <OpsKpiChip
              value={kpi.tertiaryValue}
              label={kpi.tertiaryLabel}
              tone="ok"
              icon={<CheckCircle2 size={10} />}
            />
          </div>
          {metaRow}
          <div className="ml-auto flex items-center gap-2 flex-wrap">{headerActions}</div>
        </div>
      </div>

      {filterBar && (
        <div className="flex-none px-4 sm:px-6 py-2.5 border-b border-slate-800/60 flex items-center gap-3 flex-wrap">
          {filterBar}
        </div>
      )}

      <div className="flex-1 min-h-0 flex overflow-hidden">
        <div className="flex-1 min-w-0 overflow-y-auto px-4 sm:px-6 py-4 space-y-5">
          {children}
          <OpsBottomNav platform={platform} />
        </div>
        {sideRail && (
          <div className="w-72 flex-none border-l border-slate-800/60 overflow-hidden hidden xl:block">
            {sideRail}
          </div>
        )}
      </div>
    </div>
  )
}
