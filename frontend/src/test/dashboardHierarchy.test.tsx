import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../i18n/LocaleProvider', () => ({ useT: () => (k: string, v?: any) => (v ? `${k}:${JSON.stringify(v)}` : k) }))

import { HostsPanel, HwAlarmPanel, HypervisorTree, PAGE_SIZE } from '../components/dashboard/HostHierarchy'

const host = (i: number, hv = 1) => ({
  hvName: `vc${hv}`, hypervisor_id: hv,
  host: {
    host_name: `esx${i}.lab`, host_ref: `host-${hv}-${i}`, cpu_usage_pct: 40, cpu_usage_mhz: null, cpu_total_mhz: null, cpu_cores: 32,
    mem_used_mb: null, mem_total_mb: 262144, mem_usage_pct: 55, ds_used_gb: null, ds_total_gb: 2048, ds_usage_pct: 30,
    vms_running: 3, vms_total: 4, connection_state: 'connected', power_state: 'poweredOn', maintenance_mode: 0,
  },
})

const HOSTS = [...Array.from({ length: 11 }, (_, i) => host(i + 1, 1)), host(1, 2), host(2, 2)]

// Hiyerarşi (envanter tabanlı): hv1 → 1 cluster / 11 host, hv2 → 1 cluster / 2 host, hv3 → boş
const hierCluster = (hv: number, hosts: ReturnType<typeof host>[]) => ({
  name: `C${hv}`, standalone: false, ha_enabled: true, drs_enabled: false, host_count: hosts.length,
  vms_total: hosts.length * 4, vms_running: hosts.length * 3,
  hosts: hosts.map(r => ({ host_name: r.host.host_name, host_ref: r.host.host_ref, state: 'connected', cpu_pct: 40, mem_pct: 55, vms_total: 4, vms_running: 3 })),
})
const HIERARCHY = [
  { hypervisor_id: 1, name: 'vc1', type: 'vmware', host_count: 11, vms_total: 44, vms_running: 33, vms_unmapped: 0, clusters: [hierCluster(1, HOSTS.filter(h => h.hypervisor_id === 1))] },
  { hypervisor_id: 2, name: 'vc2', type: 'vmware', host_count: 2, vms_total: 8, vms_running: 6, vms_unmapped: 0, clusters: [hierCluster(2, HOSTS.filter(h => h.hypervisor_id === 2))] },
  { hypervisor_id: 3, name: 'px1', type: 'proxmox', host_count: 0, vms_total: 0, vms_running: 0, vms_unmapped: 0, clusters: [] },
]
const calls: string[] = []

function mockApi(extra: Record<string, any> = {}) {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    calls.push(String(url))
    const u = String(url)
    const json = (b: any) => ({ ok: true, json: async () => b })
    if (u.includes('/hypervisors/host-metrics')) return json({ hosts: HOSTS })
    if (u.includes('/hypervisors/hierarchy')) return json({ hypervisors: HIERARCHY })
    const m = u.match(/\/hypervisors\/(\d+)\/host-vms\?(.*)/)
    if (m) {
      const ref = new URLSearchParams(m[2]).get('host_ref')
      return json({ total: 2, running: 1, vms: [
        { id: 1, name: `vm-of-${ref}-a`, powered_on: true, power_state: 'poweredOn', ip: '10.0.0.5', os: 'RHEL 8', cpu: 4, memory_gb: 8, disk_gb: 100, services: ['ERP'] },
        { id: 2, name: `vm-of-${ref}-b`, powered_on: false, power_state: 'poweredOff', services: [] },
      ] })
    }
    for (const [k, v] of Object.entries(extra)) if (u.includes(k)) return json(v)
    return { ok: false, json: async () => ({}) }
  }))
}

const wrap = (ui: React.ReactElement) => render(
  <MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider></MemoryRouter>,
)

beforeEach(() => { calls.length = 0; vi.unstubAllGlobals() })

describe('Dashboard host kartları', () => {
  it('ilk görünümde en fazla 8 kart (4×2); «Daha fazla» kalanları kaydırılabilir alanda açar', async () => {
    mockApi()
    wrap(<HostsPanel enabled />)
    await waitFor(() => expect(screen.getAllByTestId('host-card').length).toBe(PAGE_SIZE))
    expect(PAGE_SIZE).toBe(8)
    expect(screen.getByTestId('hosts-grid').className).toContain('lg:grid-cols-4')
    expect(screen.queryByTestId('hosts-scroll')).toBeNull()
    fireEvent.click(screen.getByTestId('hosts-more'))
    expect(screen.getAllByTestId('host-card').length).toBe(13)
    expect(screen.getByTestId('hosts-scroll').className).toContain('overflow-y-auto')
    fireEvent.click(screen.getByTestId('hosts-more'))                                  // «Daha az»
    expect(screen.getAllByTestId('host-card').length).toBe(8)
  })

  it('8 veya daha az host varsa «Daha fazla» düğmesi görünmez', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ hosts: HOSTS.slice(0, 8) }) })))
    wrap(<HostsPanel enabled />)
    await waitFor(() => expect(screen.getAllByTestId('host-card').length).toBe(8))
    expect(screen.queryByTestId('hosts-more')).toBeNull()
  })

  it('host kartına tıklayınca yalnız O host için VM listesi istenir ve gösterilir; tekrar tıklayınca kapanır', async () => {
    mockApi()
    wrap(<HostsPanel enabled />)
    await waitFor(() => expect(screen.getAllByTestId('host-card').length).toBe(8))
    fireEvent.click(screen.getAllByTestId('host-card')[2])
    await waitFor(() => expect(screen.getByTestId('host-vms-table')).toBeInTheDocument())
    const vmCalls = calls.filter(c => c.includes('/host-vms'))
    expect(vmCalls).toHaveLength(1)
    expect(vmCalls[0]).toContain('/hypervisors/1/host-vms')
    expect(vmCalls[0]).toContain('host_ref=host-1-3')
    expect(vmCalls[0]).toContain('host_name=esx3.lab')
    const rows = screen.getAllByTestId('host-vm-row')
    expect(rows).toHaveLength(2)
    expect(within(rows[0]).getByText('vm-of-host-1-3-a')).toBeInTheDocument()
    expect(screen.getAllByTestId('host-card')[2]).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getAllByTestId('host-card')[2])
    expect(screen.queryByTestId('host-vms-panel')).toBeNull()
  })

  it('host başka bir karta geçince VM paneli o hosta ait olur (karışmaz)', async () => {
    mockApi()
    wrap(<HostsPanel enabled />)
    await waitFor(() => expect(screen.getAllByTestId('host-card').length).toBe(8))
    fireEvent.click(screen.getAllByTestId('host-card')[0])
    await waitFor(() => expect(screen.getByText('vm-of-host-1-1-a')).toBeInTheDocument())
    fireEvent.click(screen.getAllByTestId('host-card')[1])
    await waitFor(() => expect(screen.getByText('vm-of-host-1-2-a')).toBeInTheDocument())
    expect(screen.queryByText('vm-of-host-1-1-a')).toBeNull()
  })
})

describe('Hypervisor → cluster → host → VM hiyerarşisi', () => {
  const HVS = [
    { id: 1, name: 'vc1', type: 'vmware', ip_address: '10.0.0.1' },
    { id: 2, name: 'vc2', type: 'vmware', ip_address: '10.0.0.2' },
    { id: 3, name: 'px1', type: 'proxmox', ip_address: '10.0.0.3' },
  ]

  it('hypervisor → cluster → host → VM zinciri; VM sayısı envanterden gelir (host metriği toplanmaz)', async () => {
    mockApi()
    wrap(<HypervisorTree hypervisors={HVS} hostsEnabled />)
    await waitFor(() => expect(screen.getAllByTestId('hypervisor-card')[1].textContent).toContain('dash_vm_count:{"n":8}'))
    fireEvent.click(screen.getAllByTestId('hypervisor-card')[1])
    await waitFor(() => expect(screen.getByTestId('hypervisor-clusters-panel')).toBeInTheDocument())
    expect(screen.getAllByTestId('cluster-card')).toHaveLength(1)
    fireEvent.click(screen.getByTestId('cluster-card'))
    await waitFor(() => expect(screen.getAllByTestId('cluster-host-card')).toHaveLength(2))
    fireEvent.click(screen.getAllByTestId('cluster-host-card')[0])
    await waitFor(() => expect(screen.getByTestId('host-vms-table')).toBeInTheDocument())
    expect(calls.filter(c => c.includes('/host-vms'))[0]).toContain('/hypervisors/2/host-vms')
  })

  it('host verisi olmayan hypervisor için açıklayıcı boş durum gösterir', async () => {
    mockApi()
    wrap(<HypervisorTree hypervisors={HVS} hostsEnabled />)
    await waitFor(() => expect(screen.getAllByTestId('hypervisor-card').length).toBe(3))
    fireEvent.click(screen.getAllByTestId('hypervisor-card')[2])
    await waitFor(() => expect(screen.getByTestId('hypervisor-clusters-empty')).toBeInTheDocument())
    fireEvent.click(screen.getByTestId('hypervisor-clusters-close'))
    expect(screen.queryByTestId('hypervisor-clusters-panel')).toBeNull()
  })

  it('9+ hypervisor için aynı 8 kart + «Daha fazla» mantığı', async () => {
    mockApi()
    const many = Array.from({ length: 10 }, (_, i) => ({ id: 100 + i, name: `hv${i}`, type: 'vmware', ip_address: '1.1.1.1' }))
    wrap(<HypervisorTree hypervisors={many} hostsEnabled />)
    await waitFor(() => expect(screen.getAllByTestId('hypervisor-card').length).toBe(8))
    fireEvent.click(screen.getByTestId('hypervisors-more'))
    expect(screen.getAllByTestId('hypervisor-card').length).toBe(10)
  })
})

describe('Dashboard donanım alarmları', () => {
  const ITEMS = Array.from({ length: 9 }, (_, i) => ({
    id: i + 1, name: `hw-${i + 1}`, vendor: 'dell', model: 'R740', health: i === 0 ? 'critical' : 'warning',
    critical_alerts: i === 0 ? 2 : 0, warning_alerts: 1, top_alert: `alarm ${i + 1}`, target: null,
  }))

  it('entegrasyon/yetki yoksa hiçbir şey çizmez ve istek atmaz', async () => {
    mockApi()
    wrap(<HwAlarmPanel enabled={false} />)
    await new Promise(r => setTimeout(r, 20))
    expect(calls).toHaveLength(0)
    expect(screen.queryByTestId('hw-alarm-panel')).toBeNull()
  })

  it('enabled=false yanıtı (entegrasyon yok) panel göstermez', async () => {
    mockApi({ '/hw/problem-servers': { enabled: false, total: 0, items: [] } })
    wrap(<HwAlarmPanel enabled />)
    await waitFor(() => expect(calls.some(c => c.includes('problem-servers'))).toBe(true))
    await new Promise(r => setTimeout(r, 20))
    expect(screen.queryByTestId('hw-alarm-panel')).toBeNull()
  })

  it('sorun yoksa «tümü sağlıklı» mesajı', async () => {
    mockApi({ '/hw/problem-servers': { enabled: true, total: 0, items: [] } })
    wrap(<HwAlarmPanel enabled />)
    await waitFor(() => expect(screen.getByTestId('hw-alarm-empty')).toBeInTheDocument())
  })

  it('8 kart + «Daha fazla»; karta tıklayınca o donanımın aktif alarmları açılır', async () => {
    mockApi({
      '/hw/problem-servers': { enabled: true, total: 9, items: ITEMS },
      '/hw/servers/1': { server: { id: 1, warranty: null, link: { name: 'esx-01' }, alerts: [
        { severity: 'critical', state: 'active', message: 'PSU failed', occurred_at: '2026-10-23T10:00:00Z' },
        { severity: 'warning', state: 'cleared', message: 'old fan alarm' },
      ] } },
    })
    wrap(<HwAlarmPanel enabled />)
    await waitFor(() => expect(screen.getAllByTestId('hw-alarm-card').length).toBe(8))
    fireEvent.click(screen.getByTestId('hw-alarms-more'))
    expect(screen.getAllByTestId('hw-alarm-card').length).toBe(9)
    fireEvent.click(screen.getAllByTestId('hw-alarm-card')[0])
    await waitFor(() => expect(screen.getByTestId('hw-alarm-list')).toBeInTheDocument())
    const txt = screen.getByTestId('hw-alarm-detail').textContent || ''
    expect(txt).toContain('PSU failed')
    expect(txt).not.toContain('old fan alarm')                                         // çözülmüş alarm listelenmez
  })
})

describe('VM→host eşleşmesi olmayan hypervisor', () => {
  it('host kartı VM gösterdiği halde eşleşme yoksa açıklayıcı mesaj verir (yanıltıcı «VM yok» değil)', async () => {
    vi.stubGlobal('fetch', vi.fn(async (u: string) => {
      const json = (b: any) => ({ ok: true, json: async () => b })
      if (String(u).includes('/hypervisors/host-metrics')) return json({ hosts: [host(1, 6)] })
      return json({ total: 0, running: 0, unmapped: 5, vms: [] })
    }))
    wrap(<HostsPanel enabled />)
    await waitFor(() => expect(screen.getAllByTestId('host-card').length).toBe(1))
    fireEvent.click(screen.getByTestId('host-card'))
    await waitFor(() => expect(screen.getByTestId('host-vms-empty').textContent).toContain('dash_vm_unmapped'))
  })
})
