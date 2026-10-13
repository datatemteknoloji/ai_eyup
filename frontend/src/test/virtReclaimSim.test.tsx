import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, unknown>) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr' }),
}))
const apiSend = vi.fn()
const apiGet = vi.fn()
vi.mock('../components/insights/insightsKit', async () => ({
  apiSend: (...a: unknown[]) => apiSend(...a),
  apiGet: (...a: unknown[]) => apiGet(...a),
  fmt: (v: unknown) => (v == null ? '—' : String(v)),
  pctTone: () => '',
}))

import ReclaimSim, { ReclaimResult, changedThresholds } from '../components/insights/ReclaimSim'

const policy = { rs_window_days: 30, rs_target_pct: 70, rs_min_reduction_pct: 25, rs_min_vcpu: 4 }
const clusters = [{ hypervisor_id: 3, hypervisor: 'vc01', cluster: 'PROD' }]
const res = {
  clusters: [{
    hypervisor_id: 3, cluster: 'PROD', path: 'vc01 / DC / PROD', vms_affected: 2,
    vcpu: { freed: 10, vms: 2 }, memory: { freed_gb: 64, vms: 1 },
    before: { memory_effective_pct: 82, vcpu_ratio: 5, n1_memory_pct: 95, n1_status: 'fail' },
    after: { memory_effective_pct: 71, vcpu_ratio: 3.5, n1_memory_pct: 80, n1_status: 'ok' },
    top: [{ vm: 'big', kind: 'oversized', vcpu: 16, new_vcpu: 8, memory_gb: 128, new_memory_gb: 64, p95_cpu_pct: 10, p95_mem_pct: 12, data_days: 28 },
          { vm: 'idle1', kind: 'idle', vcpu: 4, new_vcpu: 2, memory_gb: 16, new_memory_gb: 8, p95_cpu_pct: null, p95_mem_pct: 5, data_days: 7 }],
  }],
  notes: ['not-1'],
}

describe('Geri kazanım simülasyonu', () => {
  beforeEach(() => { apiSend.mockReset(); apiGet.mockReset() })

  it('changedThresholds yalnız politikadan farklıları gönderir', () => {
    expect(changedThresholds({ rs_window_days: '30', rs_target_pct: '60', rs_min_reduction_pct: '', rs_min_vcpu: '2' }, policy))
      .toEqual({ rs_target_pct: 60, rs_min_vcpu: 2 })
  })

  it('sonuç: vCPU ve Memory kazanımı ayrı, önce→sonra değerleri, detay açılır', () => {
    render(<ReclaimResult res={res} />)
    expect(screen.getByTestId('rc-vcpu').textContent).toContain('10')
    expect(screen.getByTestId('rc-mem').textContent).toContain('64')
    const row = screen.getByTestId('rc-row')
    expect(row.textContent).toContain('82% → 71%')
    expect(row.textContent).toContain('vi_n1_ok')
    expect(screen.queryByTestId('rc-detail')).toBeNull()
    fireEvent.click(row)
    expect(screen.getByTestId('rc-detail').textContent).toContain('vi_rc_kind_oversized')
    expect(screen.getByText('• not-1')).toBeTruthy()
  })

  it('satır detayı gerçek TABLO: başlıklar, sınıf rozeti, önce→sonra sütunları, p95 ve gözlem günü', () => {
    render(<ReclaimResult res={res} />)
    fireEvent.click(screen.getByTestId('rc-row'))
    const table = screen.getByTestId('rc-vm-table')
    const heads = Array.from(table.querySelectorAll('thead th')).map(h => h.textContent)
    expect(heads).toEqual(['vi_rc_dcol_vm', 'vi_rc_dcol_class', 'vi_rc_dcol_vcpu', 'vi_rc_dcol_mem', 'vi_rc_dcol_p95cpu', 'vi_rc_dcol_p95mem', 'vi_rc_dcol_days'])
    const rows = Array.from((table as HTMLTableElement).tBodies[0].rows)
    expect(rows).toHaveLength(2)
    const c0 = Array.from(rows[0].querySelectorAll('td')).map(td => td.textContent)
    expect(c0).toEqual(['big', 'vi_rc_kind_oversized', '16 → 8', '128 → 64', '%10', '%12', '28'])
    expect(rows[0].querySelector('[data-testid="rc-kind-oversized"]')).toBeTruthy()
    expect(rows[1].querySelector('[data-testid="rc-kind-idle"]')).toBeTruthy()
    // veri yoksa '—'; sayısal sütunlar sağa hizalı
    expect(rows[1].querySelectorAll('td')[4].textContent).toBe('—')
    expect(rows[0].querySelector('[data-testid="rc-vm-vcpu"]')!.className).toContain('text-right')
    expect(rows[0].querySelector('[data-testid="rc-vm-mem"]')!.className).toContain('tabular-nums')
  })

  it('aday yoksa tablo yerine açıklama gösterilir', () => {
    render(<ReclaimResult res={{ clusters: [{ ...res.clusters[0], top: [] }], notes: [] }} />)
    fireEvent.click(screen.getByTestId('rc-row'))
    expect(screen.getByTestId('rc-detail').textContent).toContain('vi_rc_none')
    expect(screen.queryByTestId('rc-vm-table')).toBeNull()
  })

  it('eşikler politikadan dolar; değiştirilen eşik istekte gider, politika kaydedilmez', async () => {
    apiGet.mockResolvedValue({ values: policy, spec: { rs_target_pct: { label: 'Hedef' } } })
    apiSend.mockResolvedValue(res)
    render(<ReclaimSim clusters={clusters} />)
    await waitFor(() => expect(screen.getByText('Hedef')).toBeTruthy())
    const input = screen.getByTestId('rc-th-rs_target_pct').querySelector('input') as HTMLInputElement
    expect(input.value).toBe('70')
    fireEvent.change(input, { target: { value: '60' } })
    fireEvent.change(screen.getByTestId('rc-cluster'), { target: { value: '3:PROD' } })
    fireEvent.click(screen.getByText('vi_rc_run'))
    await waitFor(() => expect(apiSend).toHaveBeenCalled())
    expect(apiSend).toHaveBeenCalledWith('virt-insights', '/capacity/reclaim-sim', 'POST',
      { thresholds: { rs_target_pct: 60 }, hypervisor_id: 3, cluster: 'PROD' })
    expect(apiSend.mock.calls.every(c => c[2] !== 'PUT')).toBe(true)
    await waitFor(() => expect(screen.getByTestId('rc-result')).toBeTruthy())
  })

  it('her eşik alanında (i) simgesi var', async () => {
    apiGet.mockResolvedValue({ values: policy, spec: {} })
    render(<ReclaimSim clusters={clusters} />)
    await waitFor(() => expect(screen.getByTestId('rc-th-rs_min_vcpu')).toBeTruthy())
    for (const k of Object.keys(policy)) expect(screen.getByTestId(`rc-th-${k}`).querySelector('button[aria-label="info_btn"]')).toBeTruthy()
  })
})
