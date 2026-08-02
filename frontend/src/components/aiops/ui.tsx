import React, { useState, useRef, useEffect } from 'react'

// ── Palette ────────────────────────────────────────────────────────────────
export const NEON = {
  cyan: '#22d3ee', blue: '#3b82f6', sky: '#38bdf8',
  green: '#10b981', orange: '#f59e0b', red: '#ef4444', pink: '#ec4899', slate: '#64748b',
}
export function rgb(hex: string) {
  return `${parseInt(hex.slice(1, 3), 16)},${parseInt(hex.slice(3, 5), 16)},${parseInt(hex.slice(5, 7), 16)}`
}

// Severity → renk (sade, kurumsal)
export const SEV_COLOR: Record<string, string> = {
  emergency: NEON.pink, critical: NEON.red, high: NEON.orange,
  error: NEON.orange, warning: NEON.orange, medium: NEON.orange,
  low: NEON.blue, info: NEON.blue,
}
export function sevColor(s: string) { return SEV_COLOR[s?.toLowerCase()] || NEON.slate }

const SEV_LABEL: Record<string, string> = {
  emergency: 'ACİL', critical: 'KRİTİK', high: 'YÜKSEK', error: 'HATA',
  warning: 'UYARI', medium: 'ORTA', low: 'DÜŞÜK', info: 'BİLGİ',
}

// ── Page header ────────────────────────────────────────────────────────────
export function PageHeader({ title, subtitle, actions }: {
  title: string; subtitle?: string; actions?: React.ReactNode
}) {
  return (
    <div className="flex items-end justify-between flex-wrap gap-3">
      <div>
        <h1 className="text-lg font-bold text-white">{title}</h1>
        {subtitle && <p className="text-sm mt-0.5" style={{ color: 'rgba(148,163,184,0.6)' }}>{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 flex-wrap">{actions}</div>}
    </div>
  )
}

// ── Buttons ────────────────────────────────────────────────────────────────
export function PrimaryButton({ children, onClick, disabled, accent = NEON.cyan }: {
  children: React.ReactNode; onClick?: () => void; disabled?: boolean; accent?: string
}) {
  return (
    <button onClick={onClick} disabled={disabled}
      className="px-3.5 py-2 rounded-lg text-sm font-medium text-white transition-all disabled:opacity-60"
      style={{ background: `linear-gradient(135deg, ${accent}, ${accent}cc)`, boxShadow: `0 0 14px rgba(${rgb(accent)},0.25)` }}>
      {children}
    </button>
  )
}
export function GhostButton({ children, onClick, disabled, accent = NEON.slate }: {
  children: React.ReactNode; onClick?: () => void; disabled?: boolean; accent?: string
}) {
  return (
    <button onClick={onClick} disabled={disabled}
      className="px-3 py-2 rounded-lg text-sm font-medium transition-all disabled:opacity-60"
      style={{ background: `rgba(${rgb(accent)},0.1)`, color: accent, border: `1px solid rgba(${rgb(accent)},0.25)` }}>
      {children}
    </button>
  )
}

// ── KPI row (clickable filter chips) ────────────────────────────────────────
export function Kpi({ label, value, accent = NEON.cyan, active, onClick }: {
  label: string; value: number | string; accent?: string; active?: boolean; onClick?: () => void
}) {
  return (
    <button
      onClick={onClick}
      className="cyber-card px-4 py-3 text-left transition-all"
      style={{
        borderColor: active ? `rgba(${rgb(accent)},0.6)` : 'rgba(99,130,194,0.15)',
        background: active ? `rgba(${rgb(accent)},0.08)` : 'var(--bg-card)',
        cursor: onClick ? 'pointer' : 'default',
      }}>
      <div className="text-[11px] uppercase tracking-wider" style={{ color: 'rgba(148,163,184,0.6)' }}>{label}</div>
      <div className="text-2xl font-bold mt-0.5" style={{ color: accent }}>{value}</div>
    </button>
  )
}

// ── Badges ─────────────────────────────────────────────────────────────────
export function SeverityBadge({ severity }: { severity: string }) {
  const c = sevColor(severity)
  return (
    <span className="px-2 py-0.5 rounded text-[11px] font-semibold whitespace-nowrap"
      style={{ background: `rgba(${rgb(c)},0.14)`, color: c, border: `1px solid rgba(${rgb(c)},0.3)` }}>
      {SEV_LABEL[severity?.toLowerCase()] || severity}
    </span>
  )
}

const STATUS_CFG: Record<string, { c: string; l: string }> = {
  open: { c: NEON.red, l: 'Açık' },
  investigating: { c: NEON.orange, l: 'İnceleniyor' },
  resolved: { c: NEON.green, l: 'Çözüldü' },
  closed: { c: NEON.slate, l: 'Kapalı' },
}
export function StatusBadge({ status }: { status: string }) {
  const cfg = STATUS_CFG[status] || { c: NEON.slate, l: status }
  return (
    <span className="px-2 py-0.5 rounded-full text-[11px] font-medium whitespace-nowrap inline-flex items-center gap-1"
      style={{ background: `rgba(${rgb(cfg.c)},0.12)`, color: cfg.c, border: `1px solid rgba(${rgb(cfg.c)},0.25)` }}>
      <span className="w-1.5 h-1.5 rounded-full" style={{ background: cfg.c }} />{cfg.l}
    </span>
  )
}

// ── Toolbar inputs ──────────────────────────────────────────────────────────
export function SearchInput({ value, onChange, placeholder, width = 'w-56' }: {
  value: string; onChange: (v: string) => void; placeholder?: string; width?: string
}) {
  return (
    <div className={`relative ${width}`}>
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth={2}
        className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2" style={{ color: 'rgba(148,163,184,0.5)' }}>
        <circle cx="11" cy="11" r="8" /><path d="m21 21-4.35-4.35" />
      </svg>
      <input value={value} onChange={e => onChange(e.target.value)} placeholder={placeholder}
        className="w-full rounded-lg pl-9 pr-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none transition-colors"
        style={{ background: 'var(--bg-deep)', border: '1px solid rgba(99,130,194,0.2)' }} />
    </div>
  )
}
export function Select({ value, onChange, children }: {
  value: string; onChange: (v: string) => void; children: React.ReactNode
}) {
  return (
    <select value={value} onChange={e => onChange(e.target.value)}
      className="rounded-lg px-3 py-2 text-sm text-white focus:outline-none transition-colors"
      style={{ background: 'var(--bg-deep)', border: '1px solid rgba(99,130,194,0.2)' }}>
      {children}
    </select>
  )
}

// ── Action menu (kebab) — fixed positioned to avoid clipping ────────────────
export type MenuItem = { label: string; icon?: React.ReactNode; onClick: () => void; accent?: string; hidden?: boolean }
export function ActionMenu({ items, label }: { items: MenuItem[]; label?: string }) {
  const [open, setOpen] = useState(false)
  const [pos, setPos] = useState<{ top: number; left: number }>({ top: 0, left: 0 })
  const btnRef = useRef<HTMLButtonElement>(null)
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    const handler = (e: MouseEvent) => {
      if (menuRef.current?.contains(e.target as Node) || btnRef.current?.contains(e.target as Node)) return
      setOpen(false)
    }
    const scrollHandler = () => setOpen(false)
    document.addEventListener('mousedown', handler)
    window.addEventListener('scroll', scrollHandler, true)
    return () => { document.removeEventListener('mousedown', handler); window.removeEventListener('scroll', scrollHandler, true) }
  }, [open])

  const toggle = () => {
    if (!open && btnRef.current) {
      const r = btnRef.current.getBoundingClientRect()
      setPos({ top: r.bottom + 4, left: Math.max(8, r.right - 180) })
    }
    setOpen(o => !o)
  }

  const visible = items.filter(i => !i.hidden)

  return (
    <>
      <button ref={btnRef} onClick={toggle}
        className="px-2 py-1.5 rounded-lg transition-colors inline-flex items-center gap-1 text-xs"
        style={{ background: open ? 'rgba(34,211,238,0.1)' : 'rgba(255,255,255,0.04)', color: open ? NEON.cyan : 'rgba(148,163,184,0.8)', border: '1px solid rgba(99,130,194,0.2)' }}>
        {label && <span>{label}</span>}
        <svg viewBox="0 0 24 24" fill="currentColor" className="w-4 h-4"><circle cx="5" cy="12" r="1.6" /><circle cx="12" cy="12" r="1.6" /><circle cx="19" cy="12" r="1.6" /></svg>
      </button>
      {open && (
        <div ref={menuRef} className="fixed z-[100] py-1 rounded-lg shadow-2xl animate-fade-in"
          style={{ top: pos.top, left: pos.left, width: 180, background: 'var(--bg-card2)', border: '1px solid rgba(99,130,194,0.25)' }}>
          {visible.map((it, i) => (
            <button key={i} onClick={() => { it.onClick(); setOpen(false) }}
              className="w-full text-left px-3 py-2 text-xs flex items-center gap-2 transition-colors hover:bg-white/[0.05]"
              style={{ color: it.accent || 'rgba(226,232,240,0.9)' }}>
              {it.icon && <span className="w-4 text-center">{it.icon}</span>}
              {it.label}
            </button>
          ))}
        </div>
      )}
    </>
  )
}

// ── Tabs ────────────────────────────────────────────────────────────────────
export function Tabs({ tabs, active, onChange }: {
  tabs: { id: string; label: string; count?: number }[]; active: string; onChange: (id: string) => void
}) {
  return (
    <div className="flex items-center gap-1 p-1 rounded-xl" style={{ background: 'var(--bg-card)', border: '1px solid rgba(99,130,194,0.12)', width: 'fit-content' }}>
      {tabs.map(t => {
        const on = active === t.id
        return (
          <button key={t.id} onClick={() => onChange(t.id)}
            className="px-4 py-2 rounded-lg text-sm font-medium transition-all flex items-center gap-2"
            style={{ background: on ? 'rgba(34,211,238,0.12)' : 'transparent', color: on ? NEON.cyan : 'rgba(148,163,184,0.7)' }}>
            {t.label}
            {t.count != null && (
              <span className="px-1.5 py-0.5 rounded text-[10px] font-bold"
                style={{ background: on ? 'rgba(34,211,238,0.2)' : 'rgba(255,255,255,0.06)', color: on ? NEON.cyan : 'rgba(148,163,184,0.6)' }}>
                {t.count}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )
}

// ── Card / Section ──────────────────────────────────────────────────────────
export function Section({ title, accent = NEON.cyan, right, children, className = '' }: {
  title?: string; accent?: string; right?: React.ReactNode; children: React.ReactNode; className?: string
}) {
  return (
    <div className={`cyber-card overflow-hidden ${className}`}>
      {title && (
        <div className="px-5 py-3.5 flex items-center justify-between" style={{ borderBottom: '1px solid rgba(99,130,194,0.1)' }}>
          <div className="flex items-center gap-2">
            <div className="w-1.5 h-4 rounded-full" style={{ background: accent }} />
            <h2 className="text-sm font-semibold text-white">{title}</h2>
          </div>
          {right}
        </div>
      )}
      {children}
    </div>
  )
}

// ── Empty state ─────────────────────────────────────────────────────────────
export function EmptyState({ icon, text }: { icon?: React.ReactNode; text: string }) {
  return (
    <div className="py-14 text-center">
      {icon && <div className="mb-2 opacity-40 flex justify-center">{icon}</div>}
      <p className="text-sm" style={{ color: 'rgba(148,163,184,0.5)' }}>{text}</p>
    </div>
  )
}

// ── Modal ───────────────────────────────────────────────────────────────────
export function Modal({ title, subtitle, onClose, children, footer, maxWidth = 'max-w-2xl' }: {
  title: React.ReactNode; subtitle?: string; onClose: () => void
  children: React.ReactNode; footer?: React.ReactNode; maxWidth?: string
}) {
  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4" style={{ background: 'rgba(0,0,0,0.7)', backdropFilter: 'blur(4px)' }} onClick={onClose}>
      <div className={`cyber-card w-full ${maxWidth} max-h-[88vh] flex flex-col shadow-2xl animate-fade-in`} onClick={e => e.stopPropagation()}>
        <div className="px-5 py-4 flex items-start justify-between flex-shrink-0" style={{ borderBottom: '1px solid rgba(99,130,194,0.12)' }}>
          <div className="min-w-0">
            <h3 className="text-white font-semibold text-sm">{title}</h3>
            {subtitle && <p className="text-xs mt-0.5" style={{ color: 'rgba(148,163,184,0.6)' }}>{subtitle}</p>}
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none flex-shrink-0 ml-3">&times;</button>
        </div>
        <div className="flex-1 overflow-y-auto">{children}</div>
        {footer && <div className="px-5 py-3 flex-shrink-0" style={{ borderTop: '1px solid rgba(99,130,194,0.12)' }}>{footer}</div>}
      </div>
    </div>
  )
}

// ── Pagination ──────────────────────────────────────────────────────────────
export function Pagination({ page, totalPages, total, pageSize, unit, onPage }: {
  page: number; totalPages: number; total: number; pageSize: number; unit: string; onPage: (p: number) => void
}) {
  if (totalPages <= 1) return null
  return (
    <div className="flex items-center justify-between">
      <span className="text-xs" style={{ color: 'rgba(148,163,184,0.6)' }}>
        {page * pageSize + 1} – {Math.min((page + 1) * pageSize, total)} / {total} {unit}
      </span>
      <div className="flex gap-1.5">
        <GhostButton onClick={() => page > 0 && onPage(page - 1)} disabled={page === 0}>← Önceki</GhostButton>
        {Array.from({ length: Math.min(totalPages, 7) }).map((_, i) => {
          const p = page < 4 ? i : page - 3 + i
          if (p >= totalPages) return null
          const on = p === page
          return (
            <button key={p} onClick={() => onPage(p)}
              className="px-3 py-2 text-xs rounded-lg font-medium transition-all"
              style={on
                ? { background: `linear-gradient(135deg, ${NEON.cyan}, ${NEON.blue})`, color: '#fff' }
                : { background: 'rgba(255,255,255,0.05)', color: 'rgba(148,163,184,0.8)', border: '1px solid rgba(99,130,194,0.2)' }}>
              {p + 1}
            </button>
          )
        })}
        <GhostButton onClick={() => page < totalPages - 1 && onPage(page + 1)} disabled={page >= totalPages - 1}>Sonraki →</GhostButton>
      </div>
    </div>
  )
}
