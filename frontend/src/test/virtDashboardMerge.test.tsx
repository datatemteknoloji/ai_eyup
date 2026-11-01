import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, string | number>) => (v ? `${k}:${Object.values(v).join(',')}` : k),
}))

class RO { observe() {} unobserve() {} disconnect() {} }
vi.stubGlobal('ResizeObserver', RO)

import {
  EnvStatusBreakdown, HostTypesTip, VirtCapacityCard, type CapacityOverview,
} from '../components/dashboard/CapacityBreakdown'
import { HostResourceChart, rankHostsByLoad } from '../components/dashboard/ResourceCharts'

const phys = (over: Record<string, unknown>) => ({
  hypervisor_id: 1, name: 'office', type: 'vmware', type_label: 'VMware vCenter', demo: false, hosts: 3,
  cpu_cores: 12, cpu_total_ghz: 40, cpu_used_ghz: 10, cpu_pct: 25,
  mem_total_gb: 100, mem_used_gb: 50, mem_pct: 50,
  storage_total_gb: 1000, storage_used_gb: 250, storage_pct: 25, datastores: 3, ...over,
})
const inv = (over: Record<string, unknown>) => ({
  key: 'hv:1', kind: 'hypervisor', label: 'office', type: 'vmware', type_label: 'VMware vCenter', demo: false,
  servers: 30, cpu_cores: 120, memory_gb: 400, online: 25, offline: 4, attention: 1, ...over,
})
const tot = { hypervisors: 2, hosts: 5, cpu_cores: 28, cpu_total_ghz: 60, cpu_used_ghz: 20, cpu_pct: 33.3, mem_total_gb: 180, mem_used_gb: 90, mem_pct: 50, storage_total_gb: 1000, storage_used_gb: 250, storage_pct: 25 }

const data = (): CapacityOverview => ({
  has_demo: false,
  inventory: {
    sources: [
      inv({}),
      inv({ key: 'hv:2', label: 'olvm', type: 'kvm', type_label: 'OLVM / oVirt (KVM)', servers: 10, cpu_cores: 40, memory_gb: 100, online: 6, offline: 4, attention: 0 }),
      inv({ key: 'hv:9', label: 'hyperv-lab', type: 'hyperv', type_label: 'Hyper-V', servers: 4, cpu_cores: 16, memory_gb: 32, online: 1, offline: 3, attention: 0 }),
      inv({ key: 'free:linux', kind: 'linux', label: 'Linux sunucular (hypervisor dışı)', type: '', type_label: '', servers: 7, cpu_cores: 70, memory_gb: 200, online: 7, offline: 0, attention: 0 }),
    ],
    total: { servers: 51, cpu_cores: 246, memory_gb: 732 }, total_real: { servers: 51, cpu_cores: 246, memory_gb: 732 },
  },
  physical: {
    sources: [
      phys({}),
      phys({ hypervisor_id: 2, name: 'olvm', type: 'kvm', type_label: 'OLVM / oVirt (KVM)', hosts: 2, cpu_cores: 16, mem_total_gb: 80, storage_total_gb: null, storage_used_gb: null, storage_pct: null, datastores: 0 }),
    ],
    total: tot, total_real: tot,
  },
}) as unknown as CapacityOverview

describe('Sanallaştırma: birleşik kaynak kartları', () => {
  it('CPU: fiziksel ölçer + hypervisor başına kullanım ve dağıtılan vCPU + overcommit oranı', () => {
    render(<VirtCapacityCard data={data()} basis="cpu" />)
    const card = screen.getByTestId('vcc-cpu')
    expect(card.textContent).toContain('hv_cpu_usage')
    const list = screen.getByTestId('vcc-list-cpu')
    expect(list.textContent).toContain('office')
    expect(list.textContent).toContain('%25')
    expect(list.textContent).toContain('vcc_alloc:120 vCPU')
    // dağıtılan (120+40) / fiziksel çekirdek (12+16) = 5.7×
    expect(screen.getByTestId('vcc-ratio-cpu').textContent).toContain('5.7×')
  })

  it('fiziksel verisi olmayan hypervisor (ör. Hyper-V) satırı KAYBOLMAZ; yalnız envanter değeriyle görünür', () => {
    render(<VirtCapacityCard data={data()} basis="cpu" />)
    const list = screen.getByTestId('vcc-list-cpu')
    expect(list.textContent).toContain('hyperv-lab')
    expect(list.textContent).toContain('vcc_no_phys')
    expect(list.textContent).toContain('16 vCPU')
    // overcommit yalnız her iki verisi olanlarla hesaplanır (Hyper-V'nin 16 vCPU'su oranı şişirmez)
    expect(screen.getByTestId('vcc-ratio-cpu').textContent).toContain('5.7×')
  })

  it('bellek: GB cinsinden dağıtılan ve oran; hypervisor dışı Linux satırı yok', () => {
    render(<VirtCapacityCard data={data()} basis="memory" />)
    const list = screen.getByTestId('vcc-list-memory')
    expect(list.textContent).toContain('vcc_alloc:400 GB')
    expect(list.textContent).not.toContain('Linux sunucular')
    expect(screen.getByTestId('vcc-ratio-memory').textContent).toContain('2.8×')   // (400+100)/(100+80)
  })

  it('depolama: oran ve dağıtılan yok; datastore sayısı ve «veri yok» var', () => {
    render(<VirtCapacityCard data={data()} basis="storage" />)
    expect(screen.queryByTestId('vcc-ratio-storage')).toBeNull()
    const list = screen.getByTestId('vcc-list-storage')
    expect(list.textContent).toContain('vcc_ds_n:3')
    expect(list.textContent).toContain('cap_no_data')
    expect(list.textContent).not.toContain('vcc_alloc')
  })

  it('MHz vermeyen kaynakta ölçer yüzdeyle çalışır; hiç veri yoksa kart çizilmez', () => {
    const d = data()
    d.physical.total = { ...tot, cpu_total_ghz: null, cpu_used_ghz: null, cpu_pct: 42 } as never
    render(<VirtCapacityCard data={d} basis="cpu" />)
    expect(screen.getByTestId('vcc-cpu').textContent).toContain('42 %')
    const empty = { ...data(), physical: { sources: [], total: tot, total_real: tot }, inventory: { ...data().inventory, sources: [] } } as unknown as CapacityOverview
    const { container } = render(<VirtCapacityCard data={empty} basis="memory" />)
    expect(container.querySelector('[data-testid="vcc-memory"]')).toBeNull()
  })
})

describe('Host KPI balonu: türe göre', () => {
  it('host\'lar hypervisor türüne göre toplanır (VMware / OLVM …); yeni tür kendiliğinden görünür', () => {
    const d = data()
    d.physical.sources.push(phys({ hypervisor_id: 3, name: 'vc2', hosts: 7 }) as never,
      phys({ hypervisor_id: 4, name: 'ocp', type: 'openshift_virt', type_label: 'OpenShift Virtualization', hosts: 3 }) as never)
    render(<HostTypesTip data={d} />)
    const tip = document.body.textContent || ''
    expect(tip).toContain('VMware vCenter')
    expect(tip).toContain('cap_tip_hosts_n:10')          // 3 + 7
    expect(tip).toContain('cap_tip_hv_n:2')
    expect(tip).toContain('OpenShift Virtualization')
    expect(tip).toContain('OLVM / oVirt (KVM)')
    // toplam = tüm host'lar (3+2+7+3)
    expect(tip).toContain('15')
  })

  it('kaynak yoksa balon çizilmez', () => {
    const empty = { ...data(), physical: { sources: [], total: tot, total_real: tot } } as unknown as CapacityOverview
    const { container } = render(<HostTypesTip data={empty} />)
    expect(container.textContent).toBe('')
  })
})

describe('Ana dashboard «Sunucu Durumu»: ortam bazında açık/kapalı', () => {
  it('her ortam için açık/kapalı sayısı; uyarı yalnız varsa; en kalabalık ortam üstte', () => {
    render(<EnvStatusBreakdown data={data()} />)
    const rows = screen.getAllByTestId('env-status-row')
    expect(rows).toHaveLength(4)
    expect(rows[0].textContent).toContain('office')                   // 30 sunucu
    expect(rows[0].textContent).toContain('25')
    expect(rows[0].textContent).toContain('dash_env_attn')            // 1 uyarı var
    expect(rows[1].textContent).toContain('olvm')                     // 10
    expect(within(rows[2]).getByText('Linux sunucular (hypervisor dışı)')).toBeTruthy()   // 7
    expect(rows[2].textContent).not.toContain('dash_env_attn')
  })

  it('6\'dan fazla ortam «daha fazla» ile açılır', () => {
    const d = data()
    for (let i = 0; i < 5; i++) d.inventory.sources.push(inv({ key: `hv:${100 + i}`, label: `extra-${i}`, servers: 1 }) as never)
    render(<EnvStatusBreakdown data={d} />)
    expect(screen.getAllByTestId('env-status-row')).toHaveLength(6)
    fireEvent.click(screen.getByTestId('env-status-more'))
    expect(screen.getAllByTestId('env-status-row')).toHaveLength(9)
  })

  it('eski yanıtta (durum alanları yok) hiçbir şey çizilmez', () => {
    const d = data()
    d.inventory.sources = d.inventory.sources.map(s => ({ ...s, online: undefined, offline: undefined, attention: undefined }))
    const { container } = render(<EnvStatusBreakdown data={d} />)
    expect(container.textContent).toBe('')
  })
})

describe('Host Kaynak Kullanımı: ilk 10 + daha fazla', () => {
  const host = (i: number, cpu: number, mem = 0, ds = 0) => ({ host_name: `h${i}`, cpu_usage_pct: cpu, mem_usage_pct: mem, ds_usage_pct: ds })

  it('en yüksek kullanımdan sıralar; eşitlikte toplam kullanıma bakar; girdiyi değiştirmez', () => {
    const hosts = [host(1, 10), host(2, 90), host(3, 50, 40), host(4, 50, 10), host(5, 5, 99)]
    const before = hosts.map(h => h.host_name).join()
    expect(rankHostsByLoad(hosts as never).map(h => h.host_name)).toEqual(['h5', 'h2', 'h3', 'h4', 'h1'])
    expect(hosts.map(h => h.host_name).join()).toBe(before)
  })

  it('10\'dan fazla host: not + «daha fazla (N)»; tıklayınca hepsi, tekrar tıklayınca ilk 10', () => {
    const hosts = Array.from({ length: 13 }, (_, i) => host(i, i * 5))
    render(<HostResourceChart hosts={hosts as never} topN={10} />)
    expect(document.body.textContent).toContain('hv_host_top_note:10,13')
    const btn = screen.getByTestId('hv-host-more')
    expect(btn.textContent).toBe('hv_host_more:3')
    fireEvent.click(btn)
    expect(document.body.textContent).toContain('hv_host_top_note:13,13')
    expect(screen.getByTestId('hv-host-more').textContent).toBe('hv_host_less')
    fireEvent.click(screen.getByTestId('hv-host-more'))
    expect(document.body.textContent).toContain('hv_host_top_note:10,13')
  })

  it('10 veya daha az host: «daha fazla» düğmesi yok', () => {
    render(<HostResourceChart hosts={Array.from({ length: 10 }, (_, i) => host(i, i)) as never} topN={10} />)
    expect(screen.queryByTestId('hv-host-more')).toBeNull()
  })

  it('topN verilmeyen kullanım (OpenShift) eski davranışta kalır: not ve düğme yok', () => {
    render(<HostResourceChart hosts={Array.from({ length: 12 }, (_, i) => host(i, i)) as never} limit={12} />)
    expect(screen.queryByTestId('hv-host-more')).toBeNull()
    expect(document.body.textContent).not.toContain('hv_host_top_note')
  })
})
