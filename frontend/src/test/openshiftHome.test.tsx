import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../i18n/LocaleProvider', () => ({ useT: () => (k: string, v?: any) => (v ? `${k}:${JSON.stringify(v)}` : k) }))
vi.mock('../components/openshift/OcpClusterTree', () => ({ OcpClusterTree: () => <div /> }))
vi.mock('../components/insights/OcpInsightsStrip', () => ({ default: () => <div /> }))
vi.mock('../components/openshift/OcpResourceDetailDrawer', () => ({
  default: (p: { name: string; namespace?: string }) => <div data-testid="drawer">{p.namespace}/{p.name}</div>,
}))

import OpenShiftHome from '../pages/OpenShiftHome'

const node = (name: string, over: Record<string, unknown> = {}) => ({
  name, role: 'worker', status: 'Ready', cpu_cores: 8, memory_gb: 32, cpu_pct: 40, mem_pct: 50,
  pods_total: 10, pods_bad: 0, vms_total: 0, vms_running: 0, ...over,
})
const HIER = {
  clusters: [{
    cluster_id: 1, name: 'kfs-ocp', version: '4.15', status: 'ONLINE', node_count: 3, nodes_not_ready: 1,
    project_count: 5, pod_count: 30, pods_bad: 3, vm_count: 0,
    nodes: [node('w1', { cpu_pct: 95 }), node('w2', { cpu_pct: 20 }), node('w3', { status: 'NotReady', cpu_pct: 60 })],
    namespaces: [],
  }],
}
const risk = (id: number, sev: string, over: Record<string, unknown> = {}) => ({
  id, cluster_id: 1, project: `ns${id}`, name: `pod-${id}`, status: 'CrashLoopBackOff', reason: 'Error',
  node_name: 'w1', restart_count: id, ready: '0/1', owner_kind: 'ReplicaSet', owner_name: `rs-${id}`, risk_severity: sev, ...over,
})
const RISKS = { risks: [risk(1, 'warning'), risk(2, 'critical', { restart_count: 40 }), risk(3, 'high')], total: 61 }

function mockApi() {
  vi.stubGlobal('fetch', vi.fn(async (url: string) => {
    const u = String(url)
    const json = (b: unknown) => ({ ok: true, json: async () => b })
    if (u.includes('/openshift/hierarchy')) return json(HIER)
    if (u.includes('/openshift/risks')) return json(RISKS)
    if (u.includes('/hypervisors/host-metrics')) return json({ hosts: [] })
    return { ok: false, json: async () => ({}) }
  }))
}
const wrap = () => render(
  <MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><OpenShiftHome /></QueryClientProvider></MemoryRouter>,
)

beforeEach(() => { vi.unstubAllGlobals(); mockApi() })

describe('OpenShift Dashboard', () => {
  it('risk sayısı backend toplamını gösterir (satır sayısını değil) ve liste kaydırılır', async () => {
    wrap()
    const section = await screen.findByTestId('ocp-risk-section')
    await waitFor(() => expect(within(section).getAllByTestId('ocp-risk-row')).toHaveLength(3))
    expect(within(section).getByText(/ocp_dash_risk_title \(61\)/)).toBeInTheDocument()
    expect(within(section).getByTestId('ocp-risks-count').textContent).toContain('"total":61')
    expect(section.querySelector('.max-h-96')).not.toBeNull()
  })

  it('risk tablosu varsayılan önem sırasına göre (kritik üstte), başlıkla sıralanır, önem filtresi çalışır', async () => {
    wrap()
    const rows = async () => (await screen.findAllByTestId('ocp-risk-row')).map(r => r.textContent || '')
    expect((await rows())[0]).toContain('pod-2')
    fireEvent.click(screen.getByTestId('ocp-risks-sort-restarts')) // asc
    expect((await rows())[0]).toContain('pod-1')
    fireEvent.click(screen.getByTestId('ocp-risk-filter-critical'))
    await waitFor(async () => expect(await rows()).toHaveLength(1))
  })

  it('risk satırına tıklayınca pod detay çekmecesi açılır', async () => {
    wrap()
    fireEvent.click((await screen.findAllByTestId('ocp-risk-row'))[0])
    expect(await screen.findByTestId('drawer')).toHaveTextContent('ns2/pod-2')
  })

  it('node tablosu: sıralanabilir kolonlar, eşik renkli CPU çubuğu ve tooltip', async () => {
    wrap()
    const table = await screen.findByTestId('ocp-nodes-1')
    const bars = await within(table).findAllByTestId('usage-bar')
    expect(bars.length).toBeGreaterThanOrEqual(6)
    expect(bars[0].getAttribute('title')).toContain('/ 8 cores')
    fireEvent.click(within(table).getByTestId('ocp-nodes-1-sort-cpu'))
    fireEvent.click(within(table).getByTestId('ocp-nodes-1-sort-cpu')) // desc
    const first = within(table).getAllByRole('row')[1]
    expect(first.textContent).toContain('w1')
  })

  it('hazır olmayan node tek bir uyarı kutusunda; özet kartı «not ready» sayısını gösterir', async () => {
    wrap()
    const box = await screen.findByTestId('ocp-not-ready')
    expect(box).toHaveTextContent('w3')
    expect(screen.getByText('ocp_dash_nodes_nr:{"n":1}')).toBeInTheDocument()
  })
})
