/**
 * Ortak monitoring kabuğu — API / Prometheus + başlık.
 * embedded: hub içinde yinelenen başlık yok; toolbar tek satır.
 */
import React from 'react'
import { Activity } from 'lucide-react'
import { useT } from '../../i18n/LocaleProvider'
import { MonitoringArchitectureHint } from './MonitoringArchitectureHint'

export type MonitoringDataMode = 'api' | 'prometheus'

export type MonitoringShellProps = {
  title: string
  subtitle?: string
  mode: MonitoringDataMode
  onModeChange: (m: MonitoringDataMode) => void
  prometheusConfigured: boolean
  children: React.ReactNode
  extraHeader?: React.ReactNode
  /** Hub: mimari (i) + modül/kaynak — embedded toolbar ile tek satır. */
  hubLeading?: React.ReactNode
  /** Hub içinde: dış padding/başlık yok, toggle kalır. */
  embedded?: boolean
  /** false → API/Prometheus seçici gizlenir (Virt: yalnız vCenter API). */
  showModeToggle?: boolean
}

export const MonitoringShell: React.FC<MonitoringShellProps> = ({
  title,
  subtitle,
  mode,
  onModeChange,
  prometheusConfigured,
  children,
  extraHeader,
  hubLeading,
  embedded = false,
  showModeToggle = true,
}) => {
  const t = useT()
  const modeToggle = showModeToggle ? (
    <div className="inline-flex rounded-md border border-white/[0.08] overflow-hidden text-[11px] flex-shrink-0">
      <button
        type="button"
        onClick={() => onModeChange('api')}
        className={`px-2.5 py-1 font-medium transition-colors ${
          mode === 'api'
            ? 'bg-blue-600 text-white'
            : 'bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:text-white'
        }`}
      >
        {t('mon_mode_api')}
      </button>
      <button
        type="button"
        disabled={!prometheusConfigured}
        title={!prometheusConfigured ? t('mon_prom_not_configured') : undefined}
        onClick={() => prometheusConfigured && onModeChange('prometheus')}
        className={`px-2.5 py-1 font-medium transition-colors ${
          mode === 'prometheus'
            ? 'bg-blue-600 text-white'
            : 'bg-[var(--bg-elevated)] text-[var(--text-secondary)] hover:text-white'
        } disabled:opacity-40 disabled:cursor-not-allowed`}
      >
        Prometheus
      </button>
    </div>
  ) : null

  if (embedded) {
    return (
      <div className="space-y-2">
        {(hubLeading || extraHeader || modeToggle) && (
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {hubLeading}
            {extraHeader}
            {modeToggle && <div className="ml-auto">{modeToggle}</div>}
          </div>
        )}
        {children}
      </div>
    )
  }

  return (
    <div className="p-4 md:p-6 space-y-3 max-w-[1600px] mx-auto">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <div className="flex items-center gap-2 min-w-0">
          <Activity className="text-blue-400 flex-shrink-0" size={20} />
          <h1 className="text-lg font-bold text-[var(--text-primary)] truncate">{title}</h1>
          <MonitoringArchitectureHint />
          {subtitle && (
            <span className="hidden lg:inline text-[11px] text-[var(--text-muted)] truncate max-w-md">
              · {subtitle}
            </span>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          {extraHeader}
          {modeToggle}
        </div>
      </div>
      {children}
    </div>
  )
}

export default MonitoringShell
