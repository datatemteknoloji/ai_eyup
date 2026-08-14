/** OS pretty-name kısaltma + ikon anahtarı (offline UI). */

export type OsIconKey =
  | 'rhel'
  | 'oracle'
  | 'centos'
  | 'rocky'
  | 'alma'
  | 'ubuntu'
  | 'debian'
  | 'suse'
  | 'fedora'
  | 'windows'
  | 'linux'
  | 'unknown'

export type OsLabelInput = {
  os_type?: string | null
  os_version?: string | null
  os_release_id?: string | null
  os_version_id?: string | null
  os_pretty?: string | null
  /** vCenter / hypervisor guest id veya full name (örn. RHEL_9_64) */
  vm_guest_os_full?: string | null
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
  if (/^windows/i.test(compact) || /^win/i.test(compact)) {
    return compact.replace(/_/g, ' ')
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

function bestPretty(s: OsLabelInput): string {
  // SSH PRETTY_NAME (os_version) hypervisor guest id'den önce — minor sürüm burada.
  const candidates = [s.os_pretty, s.os_version, s.vm_guest_os_full]
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
    if (n) return n
  }
  return cleanPretty(s.os_pretty || s.os_version || '')
}

function versionOf(s: OsLabelInput, pretty: string): string {
  // VERSION_ID her zaman en doğru minor (9.7 / 9.8)
  const id = (s.os_version_id || '').trim()
  if (id && /^\d+(\.\d+)*/.test(id)) return id
  const m = pretty.match(/\b(\d+\.\d+(?:\.\d+)?|\d+)\b/)
  return m ? m[1] : ''
}

function idHint(s: OsLabelInput, prettyLower: string): string {
  const rawId = (s.os_release_id || s.os_type || '').toLowerCase().replace(/\s+/g, '')
  // Generic LINUX / linuxGuest → pretty / guest id'den çıkar
  if (rawId && !GENERIC_OS.has(rawId) && rawId !== 'linuxguest') {
    if (rawId.includes('rhel') || rawId === 'redhat') return 'rhel'
    if (rawId === 'ol' || rawId.includes('oracle')) return 'ol'
    if (rawId.includes('rocky')) return 'rocky'
    if (rawId.includes('alma')) return 'almalinux'
    if (rawId.includes('centos')) return 'centos'
    if (rawId.includes('ubuntu')) return 'ubuntu'
    if (rawId.includes('debian')) return 'debian'
    if (rawId.includes('suse') || rawId.includes('sles')) return 'sles'
    if (rawId.includes('fedora')) return 'fedora'
    if (rawId.includes('win')) return 'windows'
    return rawId
  }

  const guest = `${s.vm_guest_os_full || ''} ${prettyLower}`.toLowerCase()
  if (guest.includes('oracle') || /\bol[_\s-]?\d/.test(guest) || guest.startsWith('ol_')) return 'ol'
  if (guest.includes('red hat') || guest.includes('rhel') || /rhel[_\s-]?\d/i.test(guest)) return 'rhel'
  if (guest.includes('rocky')) return 'rocky'
  if (guest.includes('alma')) return 'almalinux'
  if (guest.includes('centos')) return 'centos'
  if (guest.includes('ubuntu')) return 'ubuntu'
  if (guest.includes('debian')) return 'debian'
  if (guest.includes('suse') || guest.includes('sles')) return 'sles'
  if (guest.includes('fedora')) return 'fedora'
  if (guest.includes('windows') || guest.includes('win')) return 'windows'
  if (prettyLower.includes('linux') || rawId.includes('linux')) return 'linux'
  return ''
}

/** Kısa etiket — tablo hücreleri için. */
export function shortenOsLabel(s: OsLabelInput): string {
  const pretty = bestPretty(s)
  const prettyLower = pretty.toLowerCase()
  const id = idHint(s, prettyLower)
  const ver = versionOf(s, pretty)

  if (id.includes('win') || prettyLower.includes('windows')) {
    if (/server\s*202[25]/i.test(pretty)) return ver ? `Win Server ${ver}` : 'Win Server'
    if (/server\s*2019/i.test(pretty)) return 'Win Server 2019'
    if (/server\s*2016/i.test(pretty)) return 'Win Server 2016'
    if (/windows\s*11/i.test(pretty)) return 'Windows 11'
    if (/windows\s*10/i.test(pretty)) return 'Windows 10'
    return ver ? `Windows ${ver}` : (pretty || 'Windows')
  }

  const withVer = (name: string) => (ver ? `${name} ${ver}` : name)

  if (id === 'rhel' || id === 'redhat' || prettyLower.includes('red hat enterprise') || /^rhel\b/i.test(pretty)) {
    return withVer('RHEL')
  }
  if (id === 'ol' || id === 'oracle' || prettyLower.includes('oracle linux')) {
    if (/server/i.test(pretty)) return withVer('Oracle Linux S')
    return withVer('Oracle Linux')
  }
  if (id === 'centos' || prettyLower.includes('centos')) return withVer('CentOS')
  if (id === 'rocky' || prettyLower.includes('rocky')) return withVer('Rocky')
  if (id === 'almalinux' || id === 'alma' || prettyLower.includes('alma')) return withVer('AlmaLinux')
  if (id === 'ubuntu' || prettyLower.includes('ubuntu')) return withVer('Ubuntu')
  if (id === 'debian' || prettyLower.includes('debian')) return withVer('Debian')
  if (id === 'sles' || id === 'opensuse' || prettyLower.includes('suse')) return withVer('SLES')
  if (id === 'fedora' || prettyLower.includes('fedora')) return withVer('Fedora')

  // Generic linux aile — guest id yoksa
  if (id === 'linux' || prettyLower === 'linux' || prettyLower === 'linuxguest') {
    return 'Linux'
  }

  if (pretty) {
    const parts = pretty.split(/\s+/).filter(Boolean)
    const head = parts.slice(0, 2).join(' ')
    return ver && !head.includes(ver) ? `${head} ${ver}` : head
  }
  const ot = (s.os_type || '').toString()
  if (GENERIC_OS.has(ot.toLowerCase().replace(/\s+/g, ''))) return '—'
  return ot || '—'
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
  const guest = (s.vm_guest_os_full || '').trim()
  if (guest) return guest
  const short = shortenOsLabel(s)
  return short === '—' ? '' : short
}

export function osIconKey(s: OsLabelInput): OsIconKey {
  const pretty = bestPretty(s).toLowerCase()
  const id = idHint(s, pretty)
  const guest = (s.vm_guest_os_full || '').toLowerCase()
  const blob = `${id} ${pretty} ${guest}`
  if (blob.includes('win')) return 'windows'
  if (id === 'rhel' || id === 'redhat' || blob.includes('rhel') || blob.includes('red hat')) return 'rhel'
  if (id === 'ol' || id === 'oracle' || blob.includes('oracle')) return 'oracle'
  if (id === 'centos' || blob.includes('centos')) return 'centos'
  if (id === 'rocky' || blob.includes('rocky')) return 'rocky'
  if (id === 'almalinux' || id === 'alma' || blob.includes('alma')) return 'alma'
  if (id === 'ubuntu' || blob.includes('ubuntu')) return 'ubuntu'
  if (id === 'debian' || blob.includes('debian')) return 'debian'
  if (id === 'sles' || id === 'opensuse' || blob.includes('suse')) return 'suse'
  if (id === 'fedora' || blob.includes('fedora')) return 'fedora'
  if (id === 'linux' || blob.includes('linux')) return 'linux'
  return 'unknown'
}

export function serverTypeLabel(serverType?: string | null): string {
  const t = (serverType || '').toUpperCase()
  if (t === 'PHYSICAL') return 'Physical'
  if (t === 'VIRTUAL') return 'Virtual'
  if (t === 'UNKNOWN' || !t) return '—'
  return serverType || '—'
}
