import { render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, string | number>) => (v ? `${k}:${Object.values(v).join(',')}` : k),
}))

import { HypervisorUsageList, InventoryBreakdownCard, PhysicalCapacityCard, type CapacityOverview } from '../components/dashboard/CapacityBreakdown'

const phys = (over: Record<string, unknown>) => ({
  hypervisor_id: 1, name: 'office', type: 'vmware', type_label: 'VMware vCenter', demo: false, hosts: 1,
  cpu_cores: 12, cpu_total_ghz: 41.6, cpu_used_ghz: 5.8, cpu_pct: 14.1,
  mem_total_gb: 104, mem_used_gb: 91.5, mem_pct: 88,
  storage_total_gb: 6577.9, storage_used_gb: 4212.8, storage_pct: 64, datastores: 3, ...over,
})
const total = { hypervisors: 1, hosts: 1, cpu_cores: 12, cpu_total_ghz: 41.6, cpu_used_ghz: 5.8, cpu_pct: 14.1, mem_total_gb: 104, mem_used_gb: 91.5, mem_pct: 88, storage_total_gb: 6577.9, storage_used_gb: 4212.8, storage_pct: 64 }

const data: CapacityOverview = {
  has_demo: true,
  inventory: {
    sources: [
      { key: 'hv:2', kind: 'hypervisor', label: 'office', type: 'vmware', type_label: 'VMware vCenter', demo: false, servers: 33, cpu_cores: 110, memory_gb: 297 },
      { key: 'free:linux', kind: 'linux', label: 'Linux sunucular (hypervisor dışı)', type: '', type_label: '', demo: false, servers: 5, cpu_cores: 160, memory_gb: 1280 },
      { key: 'hv:8', kind: 'hypervisor', label: 'ZZ-FAKE-vCenter', type: 'vmware', type_label: 'VMware vCenter', demo: true, servers: 1000, cpu_cores: 5253, memory_gb: 20034 },
    ],
    total: { servers: 1038, cpu_cores: 5523, memory_gb: 21611 },
    total_real: { servers: 38, cpu_cores: 270, memory_gb: 1577 },
  },
  physical: {
    sources: [phys({}), phys({ hypervisor_id: 6, name: 'oVirt', cpu_total_ghz: null, cpu_used_ghz: null, storage_total_gb: null, storage_used_gb: null, storage_pct: null })],
    total, total_real: total,
  },
}

describe('kapasite dökümü', () => {
  it('toplam CPU kaynağa göre; demo etiketli ve gerçek toplam ayrı', () => {
    render(<InventoryBreakdownCard data={data} metric="cpu" />)
    const card = screen.getByTestId('cap-inv-cpu')
    expect(within(card).getByText('Linux sunucular (hypervisor dışı)')).toBeTruthy()
    expect(within(card).getByText('cap_demo')).toBeTruthy()
    expect(card.textContent).toContain('5.523 vCPU')
    expect(card.textContent).toContain('270 vCPU')
  })

  it('sanallaştırma sayfasında hypervisor dışı satırlar gizlenir', () => {
    render(<InventoryBreakdownCard data={data} metric="memory" onlyHypervisors />)
    expect(screen.queryByText('Linux sunucular (hypervisor dışı)')).toBeNull()
    expect(screen.getByText('office')).toBeTruthy()
  })

  it('ölçer altlığı her hypervisor için kullanım ve «veri yok» gösterir', () => {
    render(<HypervisorUsageList data={data} basis="storage" />)
    const list = screen.getByTestId('hv-usage-storage')
    expect(list.textContent).toContain('%64')
    expect(list.textContent).toContain('cap_no_data')
  })

  it('toplam kapasite kartı depolamayı TB olarak gösterir', () => {
    render(<PhysicalCapacityCard data={data} />)
    expect(screen.getByTestId('cap-physical').textContent).toContain('6.4 TB')
  })
})

describe('KPI kartı üzerine gelince kaynak dökümü', () => {
  it('toplam sunucu balonu kaynak başına sunucu sayısını ve toplamı gösterir', async () => {
    const { HoverTip, inventoryTip } = await import('../components/dashboard/CapacityBreakdown')
    render(<HoverTip testId="k" tip={inventoryTip(data, 'servers')}><div>KART</div></HoverTip>)
    const tip = screen.getByTestId('k-tip')
    expect(tip.textContent).toContain('office')
    expect(tip.textContent).toContain('ZZ-FAKE-vCenter')
    expect(tip.textContent).toContain('1.000')          // hypervisor başına sunucu sayısı
    expect(tip.textContent).toContain('1.038')          // toplam (kartın değeri)
    expect(tip.textContent).toContain('cap_demo')        // demo etiketli
    expect(tip.textContent).toContain('cap_total_real')  // demo hariç gerçek toplam ayrı
  })

  it('CPU ve bellek balonu kaynağa göre dağılımı verir; sanallaştırmada hypervisor dışı satırlar yok', async () => {
    const { HoverTip, inventoryTip } = await import('../components/dashboard/CapacityBreakdown')
    const { unmount } = render(<HoverTip testId="c" tip={inventoryTip(data, 'cpu')}><div>KART</div></HoverTip>)
    expect(screen.getByTestId('c-tip').textContent).toContain('Linux sunucular (hypervisor dışı)')
    expect(screen.getByTestId('c-tip').textContent).toContain('5.253 vCPU')
    unmount()
    render(<HoverTip testId="m" tip={inventoryTip(data, 'memory', true)}><div>KART</div></HoverTip>)
    expect(screen.getByTestId('m-tip').textContent).not.toContain('Linux sunucular')
    expect(screen.getByTestId('m-tip').textContent).toContain('office')
  })

  it('hypervisor balonu adları, türü ve varsa host sayısını listeler', async () => {
    const { HoverTip, HypervisorNamesTip } = await import('../components/dashboard/CapacityBreakdown')
    const hvs = [{ id: 2, name: 'office', type: 'vmware' }, { id: 6, name: 'oVirt', type: 'kvm' }]
    render(<HoverTip testId="h" tip={<HypervisorNamesTip hypervisors={hvs} data={data} />}><div>KART</div></HoverTip>)
    const tip = screen.getByTestId('h-tip')
    expect(tip.textContent).toContain('office')
    expect(tip.textContent).toContain('oVirt')
    expect(tip.textContent).toContain('VMware vCenter')
    expect(tip.textContent).toContain('cap_tip_hosts_n')
  })

  it('veri yoksa balon açılmaz (boş kutu yok)', async () => {
    const { HoverTip, inventoryTip } = await import('../components/dashboard/CapacityBreakdown')
    expect(inventoryTip(undefined, 'cpu')).toBeNull()
    render(<HoverTip testId="n" tip={inventoryTip(undefined, 'cpu')}><div>KART</div></HoverTip>)
    expect(screen.queryByTestId('n-tip')).toBeNull()
    expect(screen.getByText('KART')).toBeTruthy()
  })
})
