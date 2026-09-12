import { Monitor } from 'lucide-react'
import { fullOsLabel, type OsLabelInput } from '../lib/osLabel'

const SIZE = 20
const LOGO_BASE = '/assets/logos'

export type LogoKind =
  | 'windows'
  | 'suse'
  | 'oracle'
  | 'redhat'
  | 'ubuntu'
  | 'debian'
  | 'vmware'
  | 'linux'

const LOGO_EXT: Record<LogoKind, 'png' | 'svg'> = {
  windows: 'png',
  suse: 'png',
  oracle: 'png',
  redhat: 'png',
  ubuntu: 'svg',
  debian: 'svg',
  vmware: 'svg',
  linux: 'svg',
}

function blobOf(os: OsLabelInput | string): string {
  if (typeof os === 'string') return os
  return [
    os.name,
    os.vm_name,
    fullOsLabel(os),
    os.os_pretty,
    os.os_version,
    os.vm_guest_os_full,
    os.os_type,
    os.os_release_id,
  ]
    .filter(Boolean)
    .join(' ')
}

/**
 * Atlas Infrastructure/VM ile aynı logo seti.
 * PRETTY_NAME, kısa kod, vCenter guest id ve VM adı (vCenter/Photon) eşlenir.
 */
export function resolveOsLogoKind(os: OsLabelInput | string): LogoKind | null {
  if (typeof os === 'string') {
    return kindFromText(os)
  }

  const id = `${os.os_release_id || ''} ${os.os_type || ''} ${os.vm_guest_os_full || ''} ${os.name || ''} ${os.vm_name || ''}`.toLowerCase().trim()
  const fromId = kindFromId(id)
  if (fromId) return fromId
  return kindFromText(blobOf(os))
}

function kindFromId(id: string): LogoKind | null {
  if (!id) return null
  const cleaned = id.replace(/linuxguest/g, ' ').replace(/\blinux\b/g, ' ')
  const tokens = cleaned.split(/[\s,/|_-]+/).filter(Boolean)
  for (const t of tokens) {
    if (t === 'vcenter' || t === 'vcsa' || t === 'vsphere' || t === 'vmware' || t === 'photon' || t === 'esxi' || t === 'esx') {
      return 'vmware'
    }
    if (t === 'ubuntu') return 'ubuntu'
    if (t === 'debian') return 'debian'
    if (t === 'ol' || t === 'oracle' || t === 'oraclelinux') return 'oracle'
    if (t === 'rhel' || t === 'redhat' || t === 'centos' || t === 'rocky' || t === 'alma' || t === 'almalinux' || t === 'fedora') {
      return 'redhat'
    }
    if (t === 'sles' || t === 'suse' || t === 'opensuse') return 'suse'
    if (t === 'windows' || t === 'win' || t.startsWith('win')) return 'windows'
  }
  if (/\bred\b/.test(id) && /\bhat\b/.test(id)) return 'redhat'
  if (/rhel/i.test(id)) return 'redhat'
  if (/oracle/i.test(id)) return 'oracle'
  if (/ubuntu/i.test(id)) return 'ubuntu'
  if (/debian/i.test(id)) return 'debian'
  if (/vcenter|vcsa|vsphere|vmware|photon|esxi/i.test(id)) return 'vmware'
  return null
}

function kindFromText(raw: string): LogoKind | null {
  const t = (raw || '').toLowerCase()
  if (!t.trim()) return null
  if (t.includes('windows') || /\bwin(dows)?\b/.test(t)) return 'windows'
  if (
    t.includes('vcenter') ||
    t.includes('vcsa') ||
    t.includes('vsphere') ||
    t.includes('photon') ||
    t.includes('vmware') ||
    /\besxi\b/.test(t)
  ) {
    return 'vmware'
  }
  if (t.includes('ubuntu')) return 'ubuntu'
  if (t.includes('debian')) return 'debian'
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
  if (t.includes('linux')) return 'linux'
  return null
}

function logoSrc(kind: LogoKind): string {
  return `${LOGO_BASE}/${kind}-logo.${LOGO_EXT[kind]}`
}

function resolveOsText(os: OsLabelInput | string): string {
  if (typeof os === 'string') return os
  return fullOsLabel(os) || os.os_version || os.os_type || os.os_release_id || os.name || ''
}

/** Atlas Wr bileşeni ile aynı davranış: logo PNG/SVG veya Tux fallback. */
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
  const kind = resolveOsLogoKind(os)
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
        <img src={src} alt={label || kind || 'OS'} className="max-w-full max-h-full object-contain" draggable={false} />
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
