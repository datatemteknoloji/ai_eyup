import { Monitor } from 'lucide-react'
import { fullOsLabel, resolveOsLogoKind, type LogoKind, type OsLabelInput } from '../lib/osLabel'

const SIZE = 20
const LOGO_BASE = '/assets/logos'

const LOGO_EXT: Record<LogoKind, 'png' | 'svg'> = {
  windows: 'png',
  suse: 'png',
  oracle: 'png',
  redhat: 'png',
  rhcos: 'svg',
  centos: 'svg',
  rocky: 'svg',
  almalinux: 'svg',
  fedora: 'svg',
  ubuntu: 'svg',
  debian: 'svg',
  vmware: 'svg',
  linux: 'svg',
}

// Sınıflandırma lib/osLabel.ts'te tek yerde (ikon + etiket aynı kaynaktan).
export { resolveOsLogoKind }
export type { LogoKind }

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
        className={`inline-flex items-center justify-center shrink-0 ${className}`}
        style={box}
        title={tip}
      >
        <img src={src} alt={label || kind || 'OS'} className="max-w-full max-h-full object-contain" draggable={false} />
      </span>
    )
  }

  return (
    <span
      className={`inline-flex items-center justify-center shrink-0 text-slate-500 ${className}`}
      style={box}
      title={tip}
    >
      <Monitor style={{ width: size * 0.8, height: size * 0.8 }} strokeWidth={1.6} />
    </span>
  )
}
