import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React, { useState } from 'react'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, unknown>) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr' }),
}))
vi.mock('../components/insights/MethodBadge', () => ({ MethodBadge: () => null }))
vi.mock('../components/aiops/ui', () => ({ SeverityBadge: ({ severity }: { severity: string }) => <b>{severity}</b> }))
const apiSend = vi.fn()
vi.mock('../components/insights/insightsKit', async () => ({
  apiSend: (...a: unknown[]) => apiSend(...a),
  fmt: (v: unknown) => (v == null ? '—' : String(v)),
}))

import HostFailure from '../components/insights/HostFailure'
import FindingContext from '../components/insights/FindingContext'
import { CollapsibleScope, EMPTY_SCOPE, type Scope } from '../pages/VirtCapacity'

const clusters = [
  { hypervisor_id: 1, hypervisor: 'vc01', datacenter: 'DC-IST', cluster: 'PROD', host_names: ['esx01', 'esx02'] },
  { hypervisor_id: 1, hypervisor: 'vc01', datacenter: 'DC-IST', cluster: 'DR', host_names: ['esx09'] },
]
const row = (host: string, verdict: string) => ({ host, ok: true, vms: 1, memory_gb: 10, remaining_hosts: 1, no_remaining_host: false,
  defined: { verdict, after_memory_pct: 50, unplaced: 0 }, p95: { verdict, after_memory_pct: 40, unplaced: 0 }, cpu: null,
  overall: { verdict, limiting: [], warnings: [] } })

describe('F3 — Host devre dışı kalırsa (N+1)', () => {
  beforeEach(() => { apiSend.mockReset() })

  it('simülasyon açıklaması ve Bulgular bağlantısı görünür', () => {
    apiSend.mockResolvedValue({ ok: true, single_host: false, hosts_total: 0, rows: [] })
    render(<HostFailure clusters={[clusters[0]]} />)
    expect(screen.getByTestId('hf-sim-note').textContent).toContain('vi_hf_sim_note')
    expect((screen.getByTestId('hf-findings-link') as HTMLAnchorElement).getAttribute('href')).toBe('/virt/health')
  })

  it('derin bağlantı (initialKey/initialHost): matris gelince ilgili host satırı otomatik açılır', async () => {
    apiSend.mockImplementation(async (_b: string, path: string) => path.endsWith('/matrix')
      ? { ok: true, single_host: false, hosts_total: 2, rows: [row('esx01', 'fit'), row('esx02', 'fail')] }
      : { verdict: 'fail', displaced: { count: 1, memory_gb: 10 }, remaining_hosts: ['esx01'], after: { memory_pct: 99 }, threshold_pct: 85, placed: [], unplaced: [], notes: [],
          memory: { defined: { verdict: 'fail', displaced_gb: 10, after_memory_pct: 99, unplaced: [] }, p95: { verdict: 'fail', displaced_gb: 10, after_memory_pct: 99, unplaced: [] } },
          overall: { verdict: 'fail', limiting: ['memory'], warnings: [] } })
    render(<HostFailure clusters={clusters} initialKey="1:PROD" initialHost="esx02" />)
    await waitFor(() => expect(screen.getByTestId('hf-detail')).toBeTruthy())
    expect(apiSend).toHaveBeenCalledWith('virt-insights', '/capacity/host-failure', 'POST', { hypervisor_id: 1, cluster: 'PROD', hosts: ['esx02'] })
  })

  it('Bulgular Etki bloğu: N+1 satırına derin bağlantı', () => {
    render(<FindingContext ctx={{ impact: { available: true, verdict: 'fail', vms: 3, memory_gb: 90, remaining_hosts: 1, after_memory_pct: 99, threshold_pct: 85,
      hypervisor_id: 1, cluster: 'PROD', host: 'esx 02' } }} />)
    const a = screen.getByTestId('fc-impact-link') as HTMLAnchorElement
    expect(a.getAttribute('href')).toBe('/virt/capacity?tab=hostfail&hv=1&cluster=PROD&host=esx%2002')
  })

  it('bağlantı bilgisi yoksa (eski backend) bağlantı çizilmez', () => {
    render(<FindingContext ctx={{ impact: { available: true, verdict: 'fit', vms: 0, memory_gb: 0, remaining_hosts: 1, after_memory_pct: 10, threshold_pct: 85 } }} />)
    expect(screen.queryByTestId('fc-impact-link')).toBeNull()
  })
})

describe('F2 — kapsam çipleri ve host seçici', () => {
  function Harness({ showHosts = true, init = EMPTY_SCOPE, onScope }: { showHosts?: boolean; init?: Scope; onScope?: (s: Scope) => void }) {
    const [s, setS] = useState<Scope>(init)
    onScope?.(s)
    return <CollapsibleScope clusters={clusters} value={s} onChange={setS} showHosts={showHosts} />
  }

  it('seçimler çip olarak görünür ve × ile tek tek kaldırılır', () => {
    let last: Scope = EMPTY_SCOPE
    render(<Harness init={{ instance: '1', datacenter: 'DC-IST', clusters: ['PROD', 'DR'], hosts: ['esx01'] }} onScope={s => { last = s }} />)
    expect(screen.getByTestId('scope-chips').textContent).toContain('PROD')
    fireEvent.click(screen.getByTestId('scope-chip-x-cl-PROD'))
    expect(last.clusters).toEqual(['DR'])
    expect(last.hosts).toEqual([])                       // cluster değişince host seçimi sıfırlanır
    fireEvent.click(screen.getByTestId('scope-chip-x-dc-DC-IST'))
    expect(last.datacenter).toBe('')
    expect(last.clusters).toEqual([])
    fireEvent.click(screen.getByTestId('scope-chip-x-inst-1'))
    expect(last).toEqual(EMPTY_SCOPE)
    expect(screen.queryByTestId('scope-chips')).toBeNull()
  })

  it('"Nereye sığar" (showHosts=false): host seçici ve host notu yok, host çipi yok', () => {
    render(<Harness showHosts={false} init={{ ...EMPTY_SCOPE, hosts: ['esx01'] }} />)
    fireEvent.click(screen.getByTestId('scope-toggle'))
    expect(screen.queryByTestId('scope-hosts')).toBeNull()
    expect(screen.queryByTestId('scope-host-note')).toBeNull()
    expect(screen.queryByTestId('scope-chip-x-h-esx01')).toBeNull()
    expect(screen.getByTestId('scope-clusters')).toBeTruthy()
  })
})
