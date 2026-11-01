import { describe, expect, it } from 'vitest'
import { resolveOsLogoKind } from '../components/OsIcon'
import { shortenOsLabel, fullOsLabel } from '../lib/osLabel'

describe('resolveOsLogoKind — vCenter / VMware', () => {
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
})

describe('resolveOsLogoKind — gerçek DB örnekleri', () => {
  it('almalinux', () => {
    expect(resolveOsLogoKind({ os_release_id: 'almalinux', os_type: 'AlmaLinux 9.3 (Shamrock Pampas Cat)' })).toBe('almalinux')
    expect(resolveOsLogoKind({ os_type: 'AlmaLinux 9.3 (Shamrock Pampas Cat)' })).toBe('almalinux')
  })

  it('rocky', () => {
    expect(resolveOsLogoKind({ os_release_id: 'rocky', os_type: 'Rocky Linux 8.9 (Green Obsidian)' })).toBe('rocky')
    expect(resolveOsLogoKind({ os_type: 'Rocky Linux 9.3 (Blue Onyx)' })).toBe('rocky')
  })

  it('centos', () => {
    expect(resolveOsLogoKind({ os_release_id: 'centos', os_type: 'CentOS Stream 9' })).toBe('centos')
    expect(resolveOsLogoKind({ os_type: 'CentOS Linux 7 (Core)' })).toBe('centos')
  })

  it('fedora', () => {
    expect(resolveOsLogoKind({ os_release_id: 'fedora', os_type: 'Fedora Linux 40 (Cloud Edition)' })).toBe('fedora')
  })

  it('rhel (release id, kısa ID ve uzun ad)', () => {
    expect(resolveOsLogoKind({ os_release_id: 'rhel' })).toBe('redhat')
    expect(resolveOsLogoKind({ os_type: 'rhel' })).toBe('redhat')
    expect(resolveOsLogoKind({ os_type: 'Red Hat Enterprise Linux 9.8 (Plow)' })).toBe('redhat')
    expect(resolveOsLogoKind({ os_release_id: 'rhel', os_type: 'LINUX' })).toBe('redhat')
  })

  it('oracle linux', () => {
    expect(resolveOsLogoKind({ os_release_id: 'ol', os_type: 'Oracle Linux Server 8.9' })).toBe('oracle')
    expect(resolveOsLogoKind({ vm_guest_os_full: 'ol_8x64' })).toBe('oracle')
  })

  it('sles', () => {
    expect(resolveOsLogoKind({ os_release_id: 'sles', os_type: 'SUSE Linux Enterprise Server 15 SP5' })).toBe('suse')
    expect(resolveOsLogoKind({ os_type: 'sles_11' })).toBe('suse')
    expect(resolveOsLogoKind({ os_version: 'SLES 15' })).toBe('suse')
  })

  it('ubuntu ve debian', () => {
    expect(resolveOsLogoKind({ os_release_id: 'ubuntu', os_version: 'Ubuntu 22.04.4 LTS' })).toBe('ubuntu')
    expect(resolveOsLogoKind({ os_type: 'Ubuntu 24.04 LTS' })).toBe('ubuntu')
    expect(resolveOsLogoKind({ os_release_id: 'debian', os_type: 'Debian GNU/Linux 12 (bookworm)' })).toBe('debian')
    expect(resolveOsLogoKind('debian 12')).toBe('debian')
  })

  it('windows', () => {
    expect(resolveOsLogoKind({ os_type: 'windows' })).toBe('windows')
    expect(resolveOsLogoKind({ os_type: 'Microsoft Windows Server 2022 Standard' })).toBe('windows')
    expect(resolveOsLogoKind({ os_type: 'windows_2019x64' })).toBe('windows')
    expect(resolveOsLogoKind({ vm_guest_os_full: 'windows2019srv_64Guest' })).toBe('windows')
    expect(resolveOsLogoKind('win10')).toBe('windows')
  })

  it("'win' kontrolü sıkı: darwin / twin / winner windows sayılmaz", () => {
    expect(resolveOsLogoKind('darwin')).toBeNull()
    expect(resolveOsLogoKind('twin-peaks')).toBeNull()
    expect(resolveOsLogoKind({ name: 'winner-db', os_type: 'other' })).toBeNull()
  })

  it('"Linux 9.6 CoreOS" → rhcos', () => {
    expect(resolveOsLogoKind({ os_type: 'Linux 9.6 CoreOS', os_version: 'Linux 9.6 CoreOS', vm_guest_os_full: 'Linux 9.6 CoreOS' })).toBe('rhcos')
    expect(resolveOsLogoKind('Red Hat Enterprise Linux CoreOS 417.94')).toBe('rhcos')
  })

  it("'other' / boş → null (Monitor ikonu)", () => {
    expect(resolveOsLogoKind({ os_type: 'other', os_version: 'other', vm_guest_os_full: 'other' })).toBeNull()
    expect(resolveOsLogoKind({})).toBeNull()
    expect(resolveOsLogoKind('')).toBeNull()
  })

  it('generic linux → Tux, ama spesifik başka kaynak varsa o kazanır', () => {
    expect(resolveOsLogoKind({ os_type: 'linuxGuest' })).toBe('linux')
    expect(resolveOsLogoKind({ os_type: 'linuxGuest', vm_guest_os_full: 'rhel9_64Guest' })).toBe('redhat')
  })
})

describe('resolveOsLogoKind — öncelik', () => {
  it("adında 'ubuntu' geçen ama OS'u RHEL olan sunucu → redhat", () => {
    expect(resolveOsLogoKind({
      name: 'ubuntu-build-01',
      vm_name: 'ubuntu-build-01',
      os_release_id: 'rhel',
      os_type: 'Red Hat Enterprise Linux 9.4 (Plow)',
    })).toBe('redhat')
    // release id boş: os_type yine ada üstün
    expect(resolveOsLogoKind({
      name: 'ubuntu-build-01',
      os_type: 'Red Hat Enterprise Linux 9.4 (Plow)',
    })).toBe('redhat')
    // yalnızca vm_guest_os_full varsa da ada üstün
    expect(resolveOsLogoKind({ name: 'ubuntu-build-01', vm_guest_os_full: 'RHEL_9_64' })).toBe('redhat')
  })

  it('os_release_id, os_type / vm_guest_os_full değerini ezer', () => {
    expect(resolveOsLogoKind({ os_release_id: 'rocky', os_type: 'CentOS Stream 9', vm_guest_os_full: 'rhel9_64Guest' })).toBe('rocky')
    expect(resolveOsLogoKind({ os_type: 'Ubuntu 24.04 LTS', vm_guest_os_full: 'debian11_64Guest' })).toBe('ubuntu')
  })

  it('name / vm_name yalnızca diğer alanlar boş ya da generic iken kullanılır', () => {
    expect(resolveOsLogoKind({ name: 'ubuntu-web-02' })).toBe('ubuntu')
    expect(resolveOsLogoKind({ name: 'ubuntu-web-02', os_type: 'linuxGuest' })).toBe('ubuntu')
    expect(resolveOsLogoKind({ name: 'ubuntu-web-02', os_type: 'Rocky Linux 9.3 (Blue Onyx)' })).toBe('rocky')
  })
})

describe('shortenOsLabel / fullOsLabel', () => {
  it('RHEL — PRETTY_NAME ve os_type üzerinden kısalır', () => {
    expect(shortenOsLabel({ os_version: 'Red Hat Enterprise Linux 9.8 (Plow)' })).toBe('RHEL 9.8')
    expect(shortenOsLabel({ os_type: 'Red Hat Enterprise Linux 9.8 (Plow)' })).toBe('RHEL 9.8')
    expect(shortenOsLabel({ os_release_id: 'rhel', os_type: 'Red Hat Enterprise Linux Server 7.9 (Maipo)' })).toBe('RHEL 7.9')
    expect(shortenOsLabel({ os_release_id: 'rhel', os_type: 'LINUX', os_version_id: '9.4' })).toBe('RHEL 9.4')
    expect(shortenOsLabel({ os_type: 'rhel' })).toBe('RHEL')
  })

  it('Oracle Linux Server artık "Oracle Linux S" diye kesilmez', () => {
    expect(shortenOsLabel({ os_release_id: 'ol', os_type: 'Oracle Linux Server 8.9' })).toBe('Oracle Linux 8.9')
    expect(shortenOsLabel({ os_type: 'Oracle Linux Server 9.2' })).toBe('Oracle Linux 9.2')
    expect(shortenOsLabel({ os_type: 'ol_8x64' })).toBe('Oracle Linux 8')
  })

  it('CoreOS → RHCOS', () => {
    expect(shortenOsLabel({ os_type: 'Linux 9.6 CoreOS' })).toBe('RHCOS 9.6')
  })

  it('Windows', () => {
    expect(shortenOsLabel({ os_type: 'windows_2019x64' })).toBe('Windows Server 2019')
    expect(shortenOsLabel({ os_type: 'Microsoft Windows Server 2022 Standard' })).toBe('Windows Server 2022')
    expect(shortenOsLabel({ os_type: 'Microsoft Windows 11 Pro' })).toBe('Windows 11')
    expect(shortenOsLabel({ os_type: 'windows' })).toBe('Windows')
  })

  it("'other' / boş → —", () => {
    expect(shortenOsLabel({ os_type: 'other', os_version: 'other', vm_guest_os_full: 'other' })).toBe('—')
    expect(shortenOsLabel({})).toBe('—')
    expect(fullOsLabel({ os_type: 'other' })).toBe('')
  })

  it('diğer dağıtımlar', () => {
    expect(shortenOsLabel({ os_release_id: 'almalinux', os_type: 'AlmaLinux 9.3 (Shamrock Pampas Cat)' })).toBe('AlmaLinux 9.3')
    expect(shortenOsLabel({ os_release_id: 'rocky', os_type: 'Rocky Linux 8.9 (Green Obsidian)' })).toBe('Rocky 8.9')
    expect(shortenOsLabel({ os_release_id: 'centos', os_type: 'CentOS Stream 9' })).toBe('CentOS Stream 9')
    expect(shortenOsLabel({ os_release_id: 'fedora', os_type: 'Fedora Linux 40 (Cloud Edition)' })).toBe('Fedora 40')
    expect(shortenOsLabel({ os_release_id: 'sles', os_type: 'SUSE Linux Enterprise Server 15 SP5' })).toBe('SLES 15 SP5')
    expect(shortenOsLabel({ os_release_id: 'ubuntu', os_version: 'Ubuntu 24.04 LTS' })).toMatch(/^Ubuntu 24\.04/)
    expect(shortenOsLabel({ os_release_id: 'debian', os_type: 'Debian GNU/Linux 12 (bookworm)' })).toBe('Debian 12')
    expect(shortenOsLabel({ os_type: 'linuxGuest' })).toBe('Linux')
  })

  it('vCenter envanteri', () => {
    expect(shortenOsLabel({ name: 'VMware vCenter Server', os_type: 'linuxGuest' })).toBe('vCenter')
  })
})
