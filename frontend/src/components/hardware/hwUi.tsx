import React from 'react'
import { useT } from '../../i18n/LocaleProvider'

/** Donanım sağlık/güç/form faktörü rozetleri + ortak biçimleyiciler (Donanım sayfası, çekmece kartı, host paneli). */
export type HwWarranty = { end_date: string | null; expired: boolean | null; days_remaining: number | null; service_level?: string | null } | null

const HEALTH_CLS: Record<string, string> = {
  ok: 'bg-emerald-500/15 text-emerald-300 border-emerald-500/30',
  warning: 'bg-amber-500/15 text-amber-300 border-amber-500/30',
  critical: 'bg-red-500/15 text-red-300 border-red-500/30',
  unknown: 'bg-slate-500/15 text-slate-300 border-slate-500/30',
}

export const HealthBadge: React.FC<{ health: string }> = ({ health }) => {
  const t = useT()
  const h = HEALTH_CLS[health] ? health : 'unknown'
  return (
    <span data-testid={`hw-health-${h}`} className={`inline-block text-[11px] px-1.5 py-0.5 rounded border ${HEALTH_CLS[h]}`}>
      {t(`hw_health_${h}` as any)}
    </span>
  )
}

export function formFactorLabel(t: (k: any, v?: any) => string, ff?: string | null) {
  if (ff === 'blade') return t('hw_ff_blade')
  if (ff === 'rack') return t('hw_ff_rack')
  if (ff === 'standalone') return t('hw_ff_standalone')
  return t('hw_ff_unknown')
}

export const WarrantyText: React.FC<{ w: HwWarranty }> = ({ w }) => {
  const t = useT()
  if (!w || !w.end_date) return <span className="text-slate-500">{t('hw_not_measured')}</span>
  if (w.expired) return <span className="text-red-300">{w.end_date} · {t('hw_warranty_expired')}</span>
  return <span>{w.end_date}{w.days_remaining != null ? ` · ${t('hw_warranty_days', { n: w.days_remaining })}` : ''}</span>
}

export const DemoStrip: React.FC = () => {
  const t = useT()
  return (
    <div role="alert" data-testid="hw-demo-banner" className="rounded-lg border border-fuchsia-500/40 bg-fuchsia-500/10 px-4 py-2 text-xs font-semibold text-fuchsia-200">
      {t('hw_demo_banner')}
    </div>
  )
}

export const val = (v: unknown, t: (k: any) => string) => (v === null || v === undefined || v === '' ? t('hw_not_measured') : String(v))
