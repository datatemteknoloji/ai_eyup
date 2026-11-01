import React from 'react'
import { Server } from 'lucide-react'
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
    <span data-testid={`hw-health-${h}`} className={`inline-block text-[11px] px-1.5 py-0.5 rounded-sm border ${HEALTH_CLS[h]}`}>
      {t(`hw_health_${h}` as any)}
    </span>
  )
}

const VENDOR_LOGO: Record<string, { src: string; label: string }> = {
  dell: { src: '/assets/logos/dell-logo.svg', label: 'Dell' },
  hpe: { src: '/assets/logos/hp-logo.svg', label: 'HPE' },
}

/** Üretici logosu (Dell / HPE); bilinmeyen üretici için genel sunucu ikonu. */
export const VendorLogo: React.FC<{ vendor?: string | null; size?: number }> = ({ vendor, size = 18 }) => {
  const v = VENDOR_LOGO[String(vendor || '').toLowerCase()]
  const box = { width: size, height: size }
  if (!v) {
    return (
      <span data-testid="hw-vendor-logo" data-vendor="unknown" className="inline-flex items-center justify-center shrink-0 text-slate-500 align-middle" style={box} title={vendor ? String(vendor).toUpperCase() : undefined}>
        <Server style={{ width: size * 0.8, height: size * 0.8 }} strokeWidth={1.6} />
      </span>
    )
  }
  return (
    <span data-testid="hw-vendor-logo" data-vendor={String(vendor).toLowerCase()} className="inline-flex items-center justify-center shrink-0 align-middle" style={box} title={v.label}>
      <img src={v.src} alt={v.label} className="max-w-full max-h-full object-contain" draggable={false} />
    </span>
  )
}

export type BayServer = { id: number; name: string; bay?: string | null; health: string; model?: string | null }
export type BayCell = { bay: string | null; servers: BayServer[]; empty: boolean }

const bayCmp = (a: string, b: string) => a.localeCompare(b, undefined, { numeric: true, sensitivity: 'base' })

/** Kasa yuva yerleşimi: aynı yuvadaki sunucular TEK hücrede toplanır (çok düğümlü blade/sled); `emptyBays` (sunucu kaydı
 *  olmayan yuva numaraları) yer tutucu hücre olur; sıra doğal (1,2,10 · 1a,1b); yuvası olmayanlar sona. */
export function layoutBays(servers: BayServer[], emptyBays?: number[] | null): BayCell[] {
  const groups = new Map<string, BayServer[]>()
  const noBay: BayServer[] = []
  for (const s of servers) {
    const b = s.bay == null ? '' : String(s.bay).trim()
    if (!b) { noBay.push(s); continue }
    groups.set(b, [...(groups.get(b) || []), s])
  }
  const cells: BayCell[] = [
    ...Array.from(groups.entries()).map(([bay, list]) => ({ bay, servers: list, empty: false })),
    ...(emptyBays || []).map(n => ({ bay: String(n), servers: [], empty: true })),
  ].sort((a, b) => bayCmp(a.bay as string, b.bay as string))
  return [...cells, ...noBay.map(s => ({ bay: null, servers: [s], empty: false }))]
}

export type FwRow = { name: string; type?: string | null; version?: string | null; status?: string | null; component_id?: string | null; location?: string | null }

/** Firmware listesi: kurulu (`Installed`; durum bilinmiyorsa kurulu say) ve önceki/yedek (`Available`) olarak ayrılır. */
export function splitFirmware(rows: FwRow[]): { installed: FwRow[]; previous: FwRow[] } {
  const installed: FwRow[] = []
  const previous: FwRow[] = []
  for (const r of rows) (r.status && r.status !== 'Installed' ? previous : installed).push(r)
  return { installed, previous }
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
