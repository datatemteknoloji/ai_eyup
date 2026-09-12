import { describe, expect, it } from 'vitest'
import { resolveOsLogoKind } from '../components/OsIcon'
import { osIconKey, shortenOsLabel } from '../lib/osLabel'

describe('resolveOsLogoKind', () => {
  it('maps VMware vCenter Server name even when guest is generic linux', () => {
    expect(resolveOsLogoKind({
      name: 'VMware vCenter Server',
      os_type: 'linuxGuest',
      os_version: 'Other 5.x or later Linux (64-bit)',
    })).toBe('vmware')
  })

  it('maps Photon OS and VCSA', () => {
    expect(resolveOsLogoKind({ os_version: 'VMware Photon OS 5.0' })).toBe('vmware')
    expect(resolveOsLogoKind({ vm_name: 'VCSA-80' })).toBe('vmware')
  })

  it('maps Ubuntu and Debian', () => {
    expect(resolveOsLogoKind({ os_release_id: 'ubuntu', os_version: 'Ubuntu 22.04.4 LTS' })).toBe('ubuntu')
    expect(resolveOsLogoKind('debian 12')).toBe('debian')
  })

  it('keeps existing vendor logos', () => {
    expect(resolveOsLogoKind({ os_release_id: 'rhel' })).toBe('redhat')
    expect(resolveOsLogoKind({ os_release_id: 'ol' })).toBe('oracle')
    expect(resolveOsLogoKind({ os_type: 'windows' })).toBe('windows')
    expect(resolveOsLogoKind({ os_version: 'SLES 15' })).toBe('suse')
  })

  it('uses Tux for generic linux, not Monitor-only unknown', () => {
    expect(resolveOsLogoKind({ os_type: 'linuxGuest' })).toBe('linux')
  })
})

describe('osIconKey / shortenOsLabel', () => {
  it('classifies vCenter inventory as vmware', () => {
    const s = { name: 'VMware vCenter Server', os_type: 'linuxGuest' }
    expect(osIconKey(s)).toBe('vmware')
    expect(shortenOsLabel(s)).toBe('vCenter')
  })

  it('keeps Ubuntu short label', () => {
    expect(osIconKey({ os_release_id: 'ubuntu', os_version: 'Ubuntu 24.04' })).toBe('ubuntu')
    expect(shortenOsLabel({ os_release_id: 'ubuntu', os_version: 'Ubuntu 24.04' })).toMatch(/Ubuntu/)
  })
})
