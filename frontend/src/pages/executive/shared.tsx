import { useState, type CSSProperties } from 'react'
import { RESOURCE_ACCENT, LOAD_COLORS } from '../../components/dashboard/ResourceCharts'

export const MUTED = 'var(--theme-muted-foreground)'

export const cardStyle: CSSProperties = {
  background: 'var(--theme-card)',
  color: 'var(--theme-card-foreground)',
  border: '1px solid var(--theme-border)',
  borderRadius: 12,
  padding: 16,
}

export const linkButton: CSSProperties = { color: 'var(--theme-link)', background: 'transparent', border: 0, cursor: 'pointer' }

export function statusColor(status: string): string {
  if (status === 'Kritik') return 'var(--theme-destructive)'
  if (status === 'Dikkat') return 'var(--warning)'
  if (status === 'Normal') return 'var(--theme-success-fg)'
  return MUTED
}

/** Kullanım rengi: ResourceGauge ile aynı eşikler (%75 turuncu, %90 kırmızı), aksi halde kaynağın vurgu rengi. */
export function loadColor(pct: number | null | undefined, accent: string = RESOURCE_ACCENT.cpu): string {
  if (pct == null) return MUTED
  if (pct >= 90) return LOAD_COLORS.crit
  if (pct >= 75) return LOAD_COLORS.warn
  return accent
}

export function parseTr(value: string): number | null {
  if (!value || value === '—') return null
  const cleaned = value.replace(/\./g, '').replace(',', '.').replace(/[^\d.]/g, '')
  const num = Number.parseFloat(cleaned)
  return Number.isFinite(num) ? num : null
}

export function trCount(value: number): string {
  return value.toLocaleString('tr-TR')
}

export function ageText(iso: string | null | undefined, now: number = Date.now()): { text: string; stale: boolean } {
  if (!iso) return { text: 'kilitli rapor yok', stale: true }
  const minutes = Math.max(0, Math.round((now - new Date(iso).getTime()) / 60000))
  if (minutes < 2) return { text: 'az önce', stale: false }
  if (minutes < 60) return { text: `${minutes} dakika önce`, stale: false }
  const hours = Math.round(minutes / 60)
  if (hours < 48) return { text: `${hours} saat önce`, stale: hours > 30 }
  return { text: `${Math.round(hours / 24)} gün önce`, stale: true }
}

export function Info({ text }: { text: string }) {
  const [open, setOpen] = useState(false)
  return (
    <span style={{ position: 'relative', display: 'inline-flex', alignItems: 'center', gap: 4 }}>
      <span className="text-xs" style={{ color: MUTED }}>Yöntem</span>
      <button type="button" aria-label="Yöntem bilgisi" onClick={() => setOpen((v) => !v)} style={linkButton}>i</button>
      {open && (
        <span style={{ position: 'absolute', zIndex: 5, right: 0, top: '100%', width: 320, padding: 8, background: 'var(--theme-popover)', color: 'var(--theme-popover-foreground)', border: '1px solid var(--theme-border)', borderRadius: 8, fontSize: 12 }}>
          {text}
        </span>
      )}
    </span>
  )
}

/** Küçük yatay çubuk (host satırları). Renk eşikleri ResourceGauge ile aynı. */
export function MiniBar({ value, accent = RESOURCE_ACCENT.cpu }: { value: number | null | undefined; accent?: string }) {
  return (
    <span style={{ display: 'inline-block', width: 56, height: 6, borderRadius: 99, background: 'var(--theme-muted)', verticalAlign: 'middle' }}>
      <span style={{ display: 'block', height: '100%', width: `${Math.min(100, value ?? 0)}%`, borderRadius: 99, background: loadColor(value, accent) }} />
    </span>
  )
}

/** Recharts ortak görünümü (diğer sayfalarla aynı): eksen yazısı, tooltip, çubuk yuvarlaklığı. */
export const AXIS_TICK = { fill: '#94a3b8', fontSize: 10 }
export const TOOLTIP_STYLE = { background: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }
export const BAR_RADIUS: [number, number, number, number] = [4, 4, 0, 0]
