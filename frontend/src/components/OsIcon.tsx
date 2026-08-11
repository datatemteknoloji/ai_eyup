import { Monitor } from 'lucide-react'
import { fullOsLabel, type OsLabelInput } from '../lib/osLabel'

const SIZE = 20
const LOGO_BASE = '/assets/logos'

type LogoKind = 'windows' | 'suse' | 'oracle' | 'redhat'

/**
 * Atlas Infrastructure/VM ile aynı logo seti.
 * Hem PRETTY_NAME hem kısa kodlar (ol, rhel, rocky…) eşlenir.
 */
function resolveLogoKind(os: OsLabelInput | string): LogoKind | null {
  if (typeof os === 'string') {
    return kindFromText(os)
  }

  // Kısa ID + vCenter guest id önce
  const id = `${os.os_release_id || ''} ${os.os_type || ''} ${os.vm_guest_os_full || ''}`.toLowerCase().trim()
  const fromId = kindFromId(id)
  if (fromId) return fromId

  const blob = [
    fullOsLabel(os),
    os.os_pretty,
    os.os_version,
    os.vm_guest_os_full,
    os.os_type,
    os.os_release_id,
  ]
    .filter(Boolean)
    .join(' ')
  return kindFromText(blob)
}

function kindFromId(id: string): LogoKind | null {
  if (!id) return null
  // Generic LINUX / linuxGuest ikonu ezmesin
  const cleaned = id.replace(/linuxguest/g, ' ').replace(/\blinux\b/g, ' ')
  const tokens = cleaned.split(/[\s,/|_-]+/).filter(Boolean)
  for (const t of tokens) {
    if (t === 'ol' || t === 'oracle' || t === 'oraclelinux') return 'oracle'
    if (t === 'rhel' || t === 'redhat' || t === 'centos' || t === 'rocky' || t === 'alma' || t === 'almalinux' || t === 'fedora') {
      return 'redhat'
    }
    if (t === 'sles' || t === 'suse' || t === 'opensuse') return 'suse'
    if (t === 'windows' || t === 'win' || t.startsWith('win')) return 'windows'
  }
  if (/\bred\b/.test(id) && /\bhat\b/.test(id)) return 'redhat'
  // RHEL_9_64 tek string
  if (/rhel/i.test(id)) return 'redhat'
  if (/oracle/i.test(id)) return 'oracle'
  return null
}

function kindFromText(raw: string): LogoKind | null {
  const t = (raw || '').toLowerCase()
  if (!t.trim()) return null
  if (t.includes('windows') || /\bwin(dows)?\b/.test(t)) return 'windows'
  if (t.includes('suse') || t.includes('sles') || t.includes('opensuse')) return 'suse'
  if (t.includes('oracle') || /\bol\b/.test(t) || t.includes('oraclelinux')) return 'oracle'
  if (
    /red\s?hat/.test(t) ||
    t.includes('rhel') ||
    t.includes('rocky') ||
    t.includes('centos') ||
    t.includes('almalinux') ||
    /\balma\b/.test(t) ||
    t.includes('fedora')
  ) {
    return 'redhat'
  }
  return null
}

function logoSrc(kind: LogoKind): string {
  return `${LOGO_BASE}/${kind}-logo.png`
}

function resolveOsText(os: OsLabelInput | string): string {
  if (typeof os === 'string') return os
  return fullOsLabel(os) || os.os_version || os.os_type || os.os_release_id || ''
}

/** Atlas Wr bileşeni ile aynı davranış: logo PNG veya nötr fallback. */
export function OsIcon({
  os,
  className = '',
  size = SIZE,
  title,
}: {
  os: OsLabelInput | string
  className?: string
  size?: number
  title?: string
}) {
  const label = resolveOsText(os)
  const kind = resolveLogoKind(os)
  const src = kind ? logoSrc(kind) : null
  const tip = title ?? (label || 'Bilinmeyen OS')
  const box = { width: size, height: size }

  if (src) {
    return (
      <span
        className={`inline-flex items-center justify-center flex-shrink-0 ${className}`}
        style={box}
        title={tip}
      >
        <img src={src} alt={label || 'OS'} className="max-w-full max-h-full object-contain" draggable={false} />
      </span>
    )
  }

  return (
    <span
      className={`inline-flex items-center justify-center flex-shrink-0 text-slate-500 ${className}`}
      style={box}
      title={tip}
    >
      <Monitor style={{ width: size * 0.8, height: size * 0.8 }} strokeWidth={1.6} />
    </span>
  )
}
