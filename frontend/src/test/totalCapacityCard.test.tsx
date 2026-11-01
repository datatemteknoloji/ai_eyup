import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, string | number>) => (v ? `${k}:${Object.values(v).join(',')}` : k),
}))

import { TotalCapacityCard, buildCapacityRows, type CapacityOverview } from '../components/dashboard/CapacityBreakdown'

const phys = (over: Record<string, unknown>) => ({
  hypervisor_id: 1, name: 'office', type: 'vmware', type_label: 'VMware vCenter', demo: false, hosts: 3,
  cpu_cores: 12, cpu_total_ghz: 40, cpu_used_ghz: 10, cpu_pct: 25,
  mem_total_gb: 100, mem_used_gb: 50, mem_pct: 50,
  storage_total_gb: 1000, storage_used_gb: 250, storage_pct: 25, datastores: 3, ...over,
})
const inv = (over: Record<string, unknown>) => ({
  key: 'hv:1', kind: 'hypervisor', label: 'office', type: 'vmware', type_label: 'VMware vCenter', demo: false,
  servers: 30, cpu_cores: 120, memory_gb: 400, ...over,
})
const tot = { hypervisors: 1, hosts: 3, cpu_cores: 12, cpu_total_ghz: 40, cpu_used_ghz: 10, cpu_pct: 25, mem_total_gb: 100, mem_used_gb: 50, mem_pct: 50, storage_total_gb: 1000, storage_used_gb: 250, storage_pct: 25 }

const data = (over: Record<string, unknown> = {}): CapacityOverview => ({
  has_demo: false,
  inventory: {
    sources: [
      inv({}),
      inv({ key: 'hv:9', label: 'hyperv-lab', type: 'hyperv', type_label: 'Hyper-V', servers: 4, cpu_cores: 16, memory_gb: 32 }),
      inv({ key: 'free:linux', kind: 'linux', label: 'Linux sunucular (hypervisor dışı)', type: '', type_label: '', servers: 7, cpu_cores: 70, memory_gb: 200 }),
    ],
    total: { servers: 41, cpu_cores: 206, memory_gb: 632 }, total_real: { servers: 41, cpu_cores: 206, memory_gb: 632 },
  },
  physical: { sources: [phys({})], total: tot, total_real: tot },
  ...over,
}) as unknown as CapacityOverview

describe('Ana dashboard: tek «Toplam kapasite» kartı', () => {
  it('fiziksel + dağıtılan aynı satırda; fiziksel verisi olmayan ve hypervisor dışı satırlar kaybolmaz', () => {
    render(<TotalCapacityCard data={data()} />)
    const rows = screen.getAllByTestId('cap-total-row')
    expect(rows).toHaveLength(3)
    expect(rows[0].textContent).toContain('office')
    expect(rows[0].textContent).toContain('cap_cores_ghz:12,40')
    expect(rows[0].textContent).toContain('cap_l_alloc 120 vCPU')
    expect(rows[0].textContent).toContain('cap_l_alloc 400 GB')
    expect(rows[1].textContent).toContain('hyperv-lab')            // host verisi yok, envanter var
    expect(rows[1].textContent).toContain('cap_l_alloc 16 vCPU')
    expect(rows[2].textContent).toContain('Linux sunucular')       // hypervisor dışı
    expect(rows[2].textContent).toContain('cap_l_alloc 70 vCPU')
  })

  it('birimler tutarlı ve etiketli: fiziksel (çekirdek·GHz) / «Kullanım» / «Dağıtılan» ayrı satır; ayrıntı hover\'da', () => {
    render(<TotalCapacityCard data={data()} />)
    const row = screen.getAllByTestId('cap-total-row')[0]
    const cpu = row.querySelectorAll('td')[2]
    expect(cpu.querySelector('[data-line="used"]')!.textContent).toBe('cap_l_used %25 (10 GHz)')   // kullanım %, GHz cinsinden kullanılan
    expect(cpu.querySelector('[data-alloc="cpu"]')!.textContent).toBe('cap_l_alloc 120 vCPU · cap_per_core:10')
    expect(cpu.getAttribute('title')).toContain('cap_tt_phys_cpu:12,40')
    expect(cpu.getAttribute('title')).toContain('cap_tt_used:10 GHz,40 GHz,25')
    expect(cpu.getAttribute('title')).toContain('cap_tt_ratio_cpu:10')
    const mem = row.querySelectorAll('td')[3]
    expect(mem.querySelector('[data-line="used"]')!.textContent).toBe('cap_l_used %50 (50 GB)')
    expect(mem.getAttribute('title')).toContain('cap_tt_alloc_mem:400 GB')
    const st = row.querySelectorAll('td')[4]
    expect(st.querySelector('[data-line="used"]')!.textContent).toBe('cap_l_used %25 (250 GB)')
  })

  it('eski ayrı kartlar yok; başlık «cap_title»', () => {
    render(<TotalCapacityCard data={data()} />)
    expect(screen.queryByTestId('cap-inv-cpu')).toBeNull()
    expect(screen.queryByTestId('cap-inv-memory')).toBeNull()
    expect(screen.getByTestId('cap-total').textContent).toContain('cap_title')
  })

  it('toplam satırı tüm dağıtılanı toplar; overcommit yalnız fiziksel verisi olan ortamla (Hyper-V/Linux şişirmez)', () => {
    render(<TotalCapacityCard data={data()} />)
    const foot = screen.getByTestId('cap-total').querySelector('tfoot')!
    expect(foot.textContent).toContain('cap_l_alloc 206 vCPU')       // 120 + 16 + 70
    expect(foot.textContent).toContain('cap_per_core:10')           // 120 vCPU / 12 çekirdek
    expect(foot.textContent).not.toContain('cap_per_core:17')       // 206 / 12 olurdu
    expect(foot.textContent).toContain('cap_servers_n:41')
  })

  it('free=false: hypervisor dışı satırlar gizli; physical=false: yalnız envanter (Linux kapsamı)', () => {
    const { unmount } = render(<TotalCapacityCard data={data()} free={false} />)
    expect(screen.queryByText(/Linux sunucular/)).toBeNull()
    unmount()
    render(<TotalCapacityCard data={data()} physical={false} />)
    const rows = screen.getAllByTestId('cap-total-row')
    expect(rows.map(r => r.textContent).join('|')).not.toContain('cap_cores_n')
    expect(within(screen.getByTestId('cap-total')).queryByText(/cap_total_real/)).toBeNull()
  })

  it('demo satırı «Tümü» toplamına girer, «gerçek» toplamına girmez', () => {
    const d = data()
    d.has_demo = true
    d.inventory.sources.push(inv({ key: 'hv:5', label: 'ZZ-FAKE', demo: true, servers: 100, cpu_cores: 1000, memory_gb: 4000 }) as never)
    render(<TotalCapacityCard data={d} />)
    const foot = screen.getByTestId('cap-total').querySelector('tfoot')!
    expect(foot.textContent).toContain('cap_total_real')
    expect(foot.textContent).toContain('cap_total_all')
    expect(foot.textContent).toContain('cap_l_alloc 206 vCPU')        // gerçek
    expect(foot.textContent).toContain('cap_l_alloc 1.206 vCPU')      // tümü (tr-TR binlik ayracı)
  })

  it('yeni ortam eklenince (veri değişince) satır kendiliğinden çıkar', () => {
    const d = data()
    expect(buildCapacityRows(d, { physical: true, free: true })).toHaveLength(3)
    d.physical.sources.push(phys({ hypervisor_id: 2, name: 'olvm', type: 'kvm', type_label: 'OLVM' }) as never)
    expect(buildCapacityRows(d, { physical: true, free: true }).map(r => r.label)).toContain('olvm')
  })
})
