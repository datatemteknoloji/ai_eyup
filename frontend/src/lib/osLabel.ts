/** OS sınıflandırma (logo türü) + pretty-name kısaltma (offline UI). Tek kaynak: resolveOsLogoKind. */

export type OsLabelInput = {
  os_type?: string | null
  os_version?: string | null
  os_release_id?: string | null
  os_version_id?: string | null
  os_pretty?: string | null
  /** vCenter / hypervisor guest id veya full name (örn. RHEL_9_64) */
  vm_guest_os_full?: string | null
  /** Envanter / VM adı — vCenter, VCSA, Photon tanımak için */
  name?: string | null
  vm_name?: string | null
}

const CODENAME = /\s*\((?:Plow|Ootpa|Galápagos|Blue Onyx|Ascott|Turquoise|Constantine|Santiago|Tikanga|Maipo|Ootpa|Plow)[^)]*\)\s*/gi

/** Aile-level generic etiketler — gerçek distro bilgisini ezmesin. */
const GENERIC_OS = new Set([
  'linux',
  'linuxguest',
  'other',
  'otherlinux',
  'otherlinux64guest',
  'unknown',
  'unix',
  '',
])

function cleanPretty(raw: string): string {
  return raw.replace(CODENAME, ' ').replace(/\s+/g, ' ').trim()
}

/** vSphere guest id → okunabilir metin (RHEL_9_64 → RHEL 9). */
export function normalizeGuestOs(raw: string): string {
  const s = (raw || '').trim()
  if (!s) return ''
  // Zaten pretty name
  if (/\s/.test(s) && !/^[A-Za-z0-9_]+$/.test(s)) return cleanPretty(s)

  const u = s.replace(/64Guest$/i, '').replace(/Guest$/i, '').replace(/_64$/i, '')
  const compact = u.replace(/_/g, ' ')

  const mRhel = compact.match(/^rhel\s*(\d+(?:\.\d+)*)?/i)
  if (mRhel) return mRhel[1] ? `RHEL ${mRhel[1]}` : 'RHEL'

  const mOl = compact.match(/^oracle\s*linux\s*(\d+(?:\.\d+)*)?/i)
  if (mOl) return mOl[1] ? `Oracle Linux ${mOl[1]}` : 'Oracle Linux'
  if (/^oraclelinux/i.test(u.replace(/[\s_]/g, ''))) {
    const v = u.match(/(\d+(?:\.\d+)*)/)
    return v ? `Oracle Linux ${v[1]}` : 'Oracle Linux'
  }

  if (/^centos/i.test(compact)) {
    const v = compact.match(/(\d+(?:\.\d+)*)/)
    return v ? `CentOS ${v[1]}` : 'CentOS'
  }
  if (/^rocky/i.test(compact)) {
    const v = compact.match(/(\d+(?:\.\d+)*)/)
    return v ? `Rocky ${v[1]}` : 'Rocky'
  }
  if (/^alma/i.test(compact)) {
    const v = compact.match(/(\d+(?:\.\d+)*)/)
    return v ? `AlmaLinux ${v[1]}` : 'AlmaLinux'
  }
  if (/^ubuntu/i.test(compact)) {
    const v = compact.match(/(\d+(?:\.\d+)*)/)
    return v ? `Ubuntu ${v[1]}` : 'Ubuntu'
  }
  if (/^debian/i.test(compact)) {
    const v = compact.match(/(\d+(?:\.\d+)*)/)
    return v ? `Debian ${v[1]}` : 'Debian'
  }
  if (/^sles|^suse|^opensuse/i.test(compact)) {
    const v = compact.match(/(\d+(?:\.\d+)*)/)
    return v ? `SLES ${v[1]}` : 'SLES'
  }
  if (/^fedora/i.test(compact)) {
    const v = compact.match(/(\d+(?:\.\d+)*)/)
    return v ? `Fedora ${v[1]}` : 'Fedora'
  }
  if (/^windows/i.test(compact) || /^win\d/i.test(compact)) {
    // windows_2019x64 / windows2019srv_64Guest → "Windows Server 2019"
    const y = compact.match(/^windows\s?(20\d{2})/i)
    if (y) return `Windows Server ${y[1]}`
    return compact.replace(/^windows/i, 'Windows')
  }

  // RHEL_9_64 tarzı tek token
  const token = s.replace(/64Guest$/i, '').replace(/Guest$/i, '')
  const mTok = token.match(/^(rhel|centos|rocky|alma|oraclelinux|ol|ubuntu|debian|sles|fedora)[_\s-]?(\d+(?:\.\d+)*)?/i)
  if (mTok) {
    const map: Record<string, string> = {
      rhel: 'RHEL',
      centos: 'CentOS',
      rocky: 'Rocky',
      alma: 'AlmaLinux',
      oraclelinux: 'Oracle Linux',
      ol: 'Oracle Linux',
      ubuntu: 'Ubuntu',
      debian: 'Debian',
      sles: 'SLES',
      fedora: 'Fedora',
    }
    const name = map[mTok[1].toLowerCase()] || mTok[1]
    return mTok[2] ? `${name} ${mTok[2]}` : name
  }

  return cleanPretty(compact)
}

// ── Sınıflandırma (logo türü) ────────────────────────────────────────────────

export type LogoKind =
  | 'windows'
  | 'suse'
  | 'oracle'
  | 'redhat'
  | 'rhcos'
  | 'centos'
  | 'rocky'
  | 'almalinux'
  | 'fedora'
  | 'ubuntu'
  | 'debian'
  | 'vmware'
  | 'linux'

/**
 * Tek metin → logo türü. Kural sırası önemlidir (ör. "CoreOS" RHEL'den, "Oracle Linux" generic linux'tan önce).
 * Kısa ID'ler (ol, alma) yalnızca bağımsız token olarak eşlenir: "protocol", "tall" yanlış eşleşmez.
 * 'linux' genel (generic) sonuçtur — daha spesifik bir kaynak varsa o kazanır (bkz. resolveOsLogoKind).
 */
function kindFromText(raw: string): LogoKind | null {
  const t = (raw || '').toLowerCase()
  if (!t.trim()) return null
  // windows | win10 | win2019 — "darwin", "twin" eşleşmez
  if (/(?:^|[^a-z])win(?:dows|\d)/.test(t)) return 'windows'
  if (/vcenter|vcsa|vsphere|vmware|photon|(?:^|[^a-z])esxi?(?:[^a-z]|$)/.test(t)) return 'vmware'
  if (/coreos|rhcos/.test(t)) return 'rhcos'
  if (t.includes('ubuntu')) return 'ubuntu'
  if (t.includes('debian')) return 'debian'
  if (/suse|sles|(?:^|[^a-z])sled(?:[^a-z]|$)/.test(t)) return 'suse'
  if (/oracle|(?:^|[^a-z])ol(?:[^a-z]|$)/.test(t)) return 'oracle'
  if (/almalinux|(?:^|[^a-z])alma(?:[^a-z]|$)/.test(t)) return 'almalinux'
  if (t.includes('rocky')) return 'rocky'
  if (t.includes('centos')) return 'centos'
  if (t.includes('fedora')) return 'fedora'
  if (/red\s?hat|rhel/.test(t)) return 'redhat'
  if (t.includes('linux')) return 'linux'
  return null
}

function field(v: string | null | undefined): string {
  return (v || '').trim()
}

/**
 * Logo türü — tek sınıflandırma (ikon + etiket buradan beslenir).
 *
 * Öncelik: os_release_id > os_type / os_pretty / os_version > vm_guest_os_full > (en son) name / vm_name.
 * Her katman kendi içinde değerlendirilir; ilk SPESİFİK sonuç kazanır. 'linux' (linuxGuest, "Linux 9.7")
 * generic sayılır ve daha düşük katmanlarda spesifik sonuç aranır; hiçbiri yoksa 'linux' döner.
 * Böylece adında "ubuntu" geçen ama OS'u RHEL olan sunucu RHEL ikonu alır.
 */
export function resolveOsLogoKind(os: OsLabelInput | string): LogoKind | null {
  if (typeof os === 'string') return kindFromText(os)

  const tiers = [
    field(os.os_release_id),
    [os.os_type, os.os_pretty, os.os_version].map(field).filter(Boolean).join(' '),
    field(os.vm_guest_os_full),
    [os.name, os.vm_name].map(field).filter(Boolean).join(' '),
  ]
  let generic: LogoKind | null = null
  for (const text of tiers) {
    const k = kindFromText(text)
    if (!k) continue
    if (k === 'linux') {
      generic = 'linux'
      continue
    }
    return k
  }
  return generic
}

// ── Etiket ───────────────────────────────────────────────────────────────────

function bestPretty(s: OsLabelInput): string {
  // SSH PRETTY_NAME (os_version) hypervisor guest id'den önce — minor sürüm burada.
  const candidates = [s.os_pretty, s.os_version, s.os_type, s.vm_guest_os_full]
  let best = ''
  for (const c of candidates) {
    const n = normalizeGuestOs(c || '')
    if (!n || GENERIC_OS.has(n.toLowerCase().replace(/\s+/g, ''))) continue
    // Minor içereni tercih et (RHEL 9.8 > RHEL 9)
    if (!best) {
      best = n
      continue
    }
    const bestMinor = /\d+\.\d+/.test(best)
    const nMinor = /\d+\.\d+/.test(n)
    if (nMinor && !bestMinor) best = n
  }
  if (best) return best
  if (s.vm_guest_os_full) {
    const n = normalizeGuestOs(s.vm_guest_os_full)
    if (n && !GENERIC_OS.has(n.toLowerCase().replace(/\s+/g, ''))) return n
  }
  return ''
}

function versionOf(s: OsLabelInput, pretty: string): string {
  // VERSION_ID her zaman en doğru minor (9.7 / 9.8)
  const id = (s.os_version_id || '').trim()
  if (id && /^\d+(\.\d+)*/.test(id)) return id
  const m = pretty.match(/\b(\d+\.\d+(?:\.\d+)?|\d+)\b/)
  return m ? m[1] : ''
}

function windowsLabel(pretty: string): string {
  const p = pretty || ''
  if (/windows\s*11/i.test(p)) return 'Windows 11'
  if (/windows\s*10/i.test(p)) return 'Windows 10'
  const server = p.match(/server\s*(20\d{2})/i) || p.match(/windows\s*(20\d{2})/i)
  if (server) return `Windows Server ${server[1]}`
  if (/server/i.test(p)) return 'Windows Server'
  return 'Windows'
}

/** Kısa etiket — tablo hücreleri için. Anlamlı OS yoksa "—". */
export function shortenOsLabel(s: OsLabelInput): string {
  const pretty = bestPretty(s)
  const kind = resolveOsLogoKind(s)
  const ver = versionOf(s, pretty)
  const withVer = (name: string) => (ver ? `${name} ${ver}` : name)
  const lower = pretty.toLowerCase()

  switch (kind) {
    case 'windows':
      return windowsLabel(pretty)
    case 'vmware':
      if (/vcenter|vcsa/i.test(`${pretty} ${s.name || ''} ${s.vm_name || ''}`)) return 'vCenter'
      if (/photon/i.test(`${pretty} ${s.os_release_id || ''}`)) return withVer('Photon OS')
      return 'VMware'
    case 'redhat':
      return withVer('RHEL')
    case 'rhcos':
      return withVer(lower.includes('fedora') ? 'Fedora CoreOS' : 'RHCOS')
    case 'oracle':
      // "Oracle Linux Server 8.9" → "Oracle Linux 8.9" (Server kelimesi atılır, kesilmez)
      return withVer('Oracle Linux')
    case 'centos':
      return withVer(/stream/i.test(pretty) ? 'CentOS Stream' : 'CentOS')
    case 'rocky':
      return withVer('Rocky')
    case 'almalinux':
      return withVer('AlmaLinux')
    case 'fedora':
      return withVer('Fedora')
    case 'ubuntu':
      return withVer('Ubuntu')
    case 'debian':
      return withVer('Debian')
    case 'suse': {
      const sp = pretty.match(/\bSP\s?(\d+)\b/i)
      const base = /opensuse/i.test(`${pretty} ${s.os_release_id || ''} ${s.os_type || ''}`) ? 'openSUSE' : 'SLES'
      const v = withVer(base)
      return sp ? `${v} SP${sp[1]}` : v
    }
    case 'linux':
      return pretty ? withVer('Linux') : 'Linux'
    default:
      break
  }

  if (pretty) {
    const parts = pretty.split(/\s+/).filter(Boolean)
    const head = parts.slice(0, 2).join(' ')
    return ver && !head.includes(ver) ? `${head} ${ver}` : head
  }
  return '—'
}

/** Hover / title için tam metin. */
export function fullOsLabel(s: OsLabelInput): string {
  const pretty = bestPretty(s)
  if (pretty) {
    // VERSION_ID minor varsa pretty'de yoksa ekle (nadiren)
    const vid = (s.os_version_id || '').trim()
    if (vid && /^\d+\.\d+/.test(vid) && !pretty.includes(vid)) {
      return `${pretty} (${vid})`
    }
    return pretty
  }
  const short = shortenOsLabel(s)
  return short === '—' ? '' : short
}

export function serverTypeLabel(serverType?: string | null): string {
  const t = (serverType || '').toUpperCase()
  if (t === 'PHYSICAL') return 'Physical'
  if (t === 'VIRTUAL') return 'Virtual'
  if (t === 'UNKNOWN' || !t) return '—'
  return serverType || '—'
}
