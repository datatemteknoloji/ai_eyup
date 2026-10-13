import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, unknown>) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr' }),
}))
vi.mock('../components/insights/MethodBadge', () => ({ MethodBadge: () => null }))
const apiSend = vi.fn()
vi.mock('../components/insights/insightsKit', async () => ({
  apiSend: (...a: unknown[]) => apiSend(...a),
  fmt: (v: unknown) => (v == null ? '—' : String(v)),
}))

import HostFailure, { HostFailureResult } from '../components/insights/HostFailure'

const clusters = [{ hypervisor_id: 3, hypervisor: 'vc01', cluster: 'PROD', host_names: ['esx01', 'esx02', 'esx03'] },
                  { hypervisor_id: 3, hypervisor: 'vc01', cluster: 'DR', host_names: ['dr01'] }]
const fit = {
  verdict: 'fit', displaced: { count: 2, memory_gb: 70 }, remaining_hosts: ['esx02', 'esx03'], after: { memory_pct: 41.2 }, threshold_pct: 85,
  placed: [{ vm: 'a', memory_gb: 40, host: 'esx02', level: 'comfortable' }, { vm: 'b', memory_gb: 30, host: 'esx03', level: 'tight' }],
  unplaced: [], notes: ['not-1'],
}

describe('Host arızası', () => {
  beforeEach(() => { apiSend.mockReset() })

  it('sonuç: karar, hedef host tablosu, notlar', () => {
    render(<HostFailureResult res={fit} />)
    expect(screen.getByTestId('hf-verdict-fit')).toBeTruthy()
    const rows = screen.getByTestId('hf-hosts').querySelectorAll('tbody tr')
    expect(rows).toHaveLength(2)
    expect(rows[1].textContent).toContain('vi_hf_level_tight')
    expect(screen.getByText('not-1')).toBeTruthy()
    expect(screen.queryByTestId('hf-unplaced')).toBeNull()
  })

  it('yerleşemeyen VM nedeni gösterilir', () => {
    render(<HostFailureResult res={{ ...fit, verdict: 'fail', unplaced: [{ vm: 'big', memory_gb: 60, reason: 'memory' }] }} />)
    expect(screen.getByTestId('hf-verdict-fail')).toBeTruthy()
    expect(screen.getByTestId('hf-unplaced').textContent).toContain('big')
    expect(screen.getByTestId('hf-unplaced').textContent).toContain('vi_lim_memory')
  })

  const matrix = {
    ok: true, single_host: false, hosts_total: 3, rows: [
      { host: 'esx01', ok: true, vms: 5, memory_gb: 120, remaining_hosts: 2, no_remaining_host: false,
        defined: { verdict: 'fit', after_memory_pct: 61.2, unplaced: 0 }, p95: { verdict: 'fit', after_memory_pct: 40, unplaced: 0 },
        cpu: { verdict: 'fit', p95_pct: 30 }, overall: { verdict: 'fit', limiting: [], warnings: [] } },
      { host: 'esx02', ok: true, vms: 9, memory_gb: 300, remaining_hosts: 2, no_remaining_host: false,
        defined: { verdict: 'fail', after_memory_pct: 99, unplaced: 2 }, p95: { verdict: 'tight', after_memory_pct: 88, unplaced: 0 },
        cpu: { verdict: 'fit', p95_pct: 50 }, overall: { verdict: 'fail', limiting: ['memory'], warnings: [] } },
      { host: 'esx03', ok: true, vms: 0, memory_gb: 0, remaining_hosts: 2, no_remaining_host: false,
        defined: { verdict: 'no_vm', after_memory_pct: null, unplaced: 0 }, p95: { verdict: 'no_vm', after_memory_pct: null, unplaced: 0 },
        cpu: null, overall: { verdict: 'no_vm', limiting: [], warnings: [] } },
    ],
  }
  const route = (extra: Record<string, any> = {}) => apiSend.mockImplementation(async (_b: string, path: string) => {
    if (path === '/capacity/host-failure/matrix') return matrix
    if (path === '/capacity/host-failure') return fit
    return extra[path]
  })

  it('cluster seçilince matris otomatik gelir: host başına satır, tanımlı/p95/CPU/sınırlayan sütunları; en kötü önce', async () => {
    route()
    render(<HostFailure clusters={clusters} />)
    expect(screen.getByTestId('hf-intro').querySelector('button[aria-label="info_btn"]')).toBeTruthy()     // giriş metni + (i)
    expect(apiSend).not.toHaveBeenCalled()
    fireEvent.change(screen.getByTestId('hf-cluster'), { target: { value: '3:PROD' } })
    await waitFor(() => expect(screen.getByTestId('hf-matrix')).toBeTruthy())
    expect(apiSend).toHaveBeenCalledWith('virt-insights', '/capacity/host-failure/matrix', 'POST', { hypervisor_id: 3, cluster: 'PROD' })
    const heads = Array.from(screen.getByTestId('hf-matrix').querySelectorAll('thead th')).map(h => h.textContent)
    expect(heads).toEqual(expect.arrayContaining(['vi_hf_m_host', 'vi_hf_m_vms', 'Memory (GB)', 'vi_hf_m_lim', 'vi_hf_m_detail']))
    const rows = Array.from((screen.getByTestId('hf-matrix').querySelector('table') as HTMLTableElement).tBodies[0].rows)
    expect(rows.map(r => r.getAttribute('data-testid'))).toEqual(['hf-mrow-esx02', 'hf-mrow-esx01', 'hf-mrow-esx03'])
    expect(rows[0].textContent).toContain('300')
    expect(rows[0].querySelector('[data-testid="hf-mx-mem-fail"]')!.textContent).toContain('%99')
    expect(rows[0].querySelector('[data-testid="hf-mx-mem-tight"]')!.textContent).toContain('%88')
    expect(rows[0].querySelector('[data-testid="lim-memory"]')).toBeTruthy()
    expect(rows[1].querySelector('[data-testid="hf-mx-cpu-fit"]')!.textContent).toContain('%30')
    expect(rows[2].textContent).toContain('vi_hf_m_novm')                                                  // VM yok → '—' ve açıklama
  })

  it('satır tıklanınca mevcut ayrıntı (tek host) açılır; yeniden tıklayınca kapanır', async () => {
    route()
    render(<HostFailure clusters={clusters} />)
    fireEvent.change(screen.getByTestId('hf-cluster'), { target: { value: '3:PROD' } })
    await waitFor(() => expect(screen.getByTestId('hf-mrow-esx01')).toBeTruthy())
    fireEvent.click(screen.getByTestId('hf-mrow-esx01'))
    await waitFor(() => expect(screen.getByTestId('hf-result')).toBeTruthy())
    expect(apiSend).toHaveBeenCalledWith('virt-insights', '/capacity/host-failure', 'POST', { hypervisor_id: 3, cluster: 'PROD', hosts: ['esx01'] })
    expect(screen.getByTestId('hf-detail').textContent).toContain('vi_hf_detail_one')
    fireEvent.click(screen.getByTestId('hf-mrow-esx01'))
    expect(screen.queryByTestId('hf-detail')).toBeNull()
  })

  it('çoklu host: seçim yokken düğme DEVRE DIŞI ve görünür uyarı var (sessiz no-op yok); seçince doğru gövde gider', async () => {
    route()
    render(<HostFailure clusters={clusters} />)
    fireEvent.change(screen.getByTestId('hf-cluster'), { target: { value: '3:PROD' } })
    await waitFor(() => expect(screen.getByTestId('hf-multi')).toBeTruthy())
    const btn = screen.getByTestId('hf-run-selected') as HTMLButtonElement
    expect(btn.disabled).toBe(true)
    expect(screen.getByTestId('hf-select-warning').textContent).toContain('vi_hf_select_warn')
    const before = apiSend.mock.calls.length
    fireEvent.click(btn)
    expect(apiSend.mock.calls.length).toBe(before)                      // tıklama istek göndermez, ama uyarı ekranda
    fireEvent.click(screen.getByTestId('hf-host-esx01'))
    fireEvent.click(screen.getByTestId('hf-pick-esx02'))                // matris satırındaki onay kutusu da aynı seçimi kullanır
    expect(btn.disabled).toBe(false)
    expect(screen.queryByTestId('hf-select-warning')).toBeNull()
    fireEvent.click(btn)
    await waitFor(() => expect(screen.getByTestId('hf-result')).toBeTruthy())
    expect(apiSend).toHaveBeenLastCalledWith('virt-insights', '/capacity/host-failure', 'POST',
      { hypervisor_id: 3, cluster: 'PROD', hosts: ['esx01', 'esx02'] })
    expect(screen.getByTestId('hf-detail').textContent).toContain('vi_hf_detail_multi')
  })

  it('tek host\'lu cluster: "Kalan host yok: failover mümkün değil" gösterilir', async () => {
    apiSend.mockResolvedValue({ ok: true, single_host: true, hosts_total: 1, rows: [
      { host: 'sa1', ok: true, vms: 4, memory_gb: 50, remaining_hosts: 0, no_remaining_host: true,
        defined: { verdict: 'fail', after_memory_pct: null, unplaced: 4 }, p95: { verdict: 'fail', after_memory_pct: null, unplaced: 4 },
        cpu: { verdict: 'fail', p95_pct: null }, overall: { verdict: 'fail', limiting: ['no_host'], warnings: [] } }] })
    render(<HostFailure clusters={[{ hypervisor_id: 3, hypervisor: 'vc01', cluster: 'SOLO', host_names: ['sa1'] }]} />)
    await waitFor(() => expect(screen.getByTestId('hf-single-host')).toBeTruthy())               // tek cluster → otomatik seçilir
    expect(screen.getByTestId('hf-single-host').textContent).toContain('vi_hf_no_remaining')
    expect(screen.getByTestId('hf-mx-noremain').textContent).toContain('vi_hf_no_remaining')
  })

  it('matris hatası gösterilir', async () => {
    apiSend.mockImplementation(async () => { throw new Error('Cluster bulunamadı') })
    render(<HostFailure clusters={clusters} />)
    fireEvent.change(screen.getByTestId('hf-cluster'), { target: { value: '3:PROD' } })
    await waitFor(() => expect(screen.getByTestId('hf-matrix-err').textContent).toContain('Cluster bulunamadı'))
  })

  const v2 = {
    ...fit,
    overall: { verdict: 'fail', status: 'fail', limiting: ['cpu'], warnings: ['vcpu_ratio'] },
    memory: {
      defined: { verdict: 'fit', displaced_gb: 70, after_memory_pct: 70, unplaced: [], placed: fit.placed },
      p95: { verdict: 'fit', displaced_gb: 40, after_memory_pct: 55, unplaced: [], placed: [{ vm: 'a', memory_gb: 20, host: 'esx03' }] },
    },
    cpu: { verdict: 'fail', remaining_cores: 16, vcpu_ratio: 6.5, ratio_limit: 4, ratio_warn: true, p95_demand_cores: 20, p95_pct: 125, threshold_pct: 80 },
    p95: { window_days: 30, coverage: { vms_total: 5, mem_with_p95: 3, cpu_with_p95: 4 } },
  }

  it('yeni şekil: Memory tanımlı ve p95 yan yana, CPU bloğu, p95 kapsamı', () => {
    render(<HostFailureResult res={v2} />)
    const rows = screen.getByTestId('hf-memory')
    expect(rows.querySelector('thead')!.textContent).toContain('vi_hf_col_defined')
    expect(rows.querySelector('thead')!.textContent).toContain('vi_hf_col_p95')
    const moved = screen.getByTestId('hf-row-moved').querySelectorAll('td')
    expect(moved[1].textContent).toBe('70')
    expect(moved[2].textContent).toBe('40')
    expect(screen.getByTestId('hf-cpu').textContent).toContain('6.5:1')
    expect(screen.getByTestId('hf-ratio-warn')).toBeTruthy()
    expect(screen.getByTestId('hf-coverage').textContent).toContain('"a":3,"b":5')
  })

  it('yalnız CPU sınırlıyorsa CPU\'ya özel başlık; sınır/uyarı çipleri', () => {
    render(<HostFailureResult res={v2} />)
    expect(screen.getByTestId('hf-verdict-fail').textContent).toContain('vi_hf_verdict_fail_cpu')
    const chips = screen.getByTestId('hf-limiting')
    expect(chips.querySelector('[data-testid="lim-cpu"]')).toBeTruthy()
    expect(chips.querySelector('[data-testid="lim-vcpu_ratio"]')).toBeTruthy()
  })

  it('p95 verisi yoksa kapsam satırı çıkmaz; VM listesi iki yerleşimi birlikte gösterir', () => {
    const noCov = { ...v2, p95: { window_days: 30, coverage: { vms_total: 0, mem_with_p95: 0, cpu_with_p95: 0 } } }
    const { container } = render(<HostFailureResult res={noCov} />)
    expect(screen.queryByTestId('hf-coverage')).toBeNull()
    expect(container.textContent).toContain('a · 40 GB → esx02 · 20 GB → esx03')
  })

  it('(i) ipuçları: sonuç başlığında ve p95 sütununda', () => {
    render(<HostFailureResult res={v2} />)
    expect(screen.getAllByLabelText('info_btn').length).toBeGreaterThanOrEqual(4)
  })
})
