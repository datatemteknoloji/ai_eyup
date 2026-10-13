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
  pctTone: () => '',
}))

import BulkPlacement, { BulkResults, planToCsv, csvCell, buildProfiles } from '../components/insights/BulkPlacement'

const cl = {
  hypervisor_id: 1, hypervisor: 'vc01', cluster: 'PROD', path: 'vc01 / DC / PROD', requested: 3, placed: 2, unplaced_count: 1,
  fits: false, status: 'fail', limiting: ['anti_affinity'], warn_codes: [],
  plan: [
    { vm: 'web-1', profile: 'web', group: 'g1', vcpu: 4, memory_gb: 16, disk_gb: 100, host: 'esx01', datastore: 'ds1' },
    { vm: 'web-2', profile: 'web', group: 'g1', vcpu: 4, memory_gb: 16, disk_gb: 100, host: 'esx02', datastore: null },
  ],
  unplaced: [{ vm: 'web-3', profile: 'web', group: 'g1', memory_gb: 16, reason: 'anti_affinity' }],
  by_host: [{ host: 'esx01', vms: 1, memory_gb: 16, free_after_gb: 40 }],
  before: { memory_effective_pct: 50, vcpu_ratio: 2 }, after: { memory_effective_pct: 60, vcpu_ratio: 2.5 }, notes: ['n-1'],
}

describe('Toplu yerleşim', () => {
  beforeEach(() => apiSend.mockReset())

  it('CSV: başlık + yerleşen + yerleşemeyen (neden ile)', () => {
    const lines = planToCsv([cl]).split('\r\n')
    expect(lines[0]).toBe('cluster,hypervisor,vm,profile,group,vcpu,memory_gb,disk_gb,host,datastore,status,reason')
    expect(lines).toHaveLength(4)
    expect(lines[1]).toBe('PROD,vc01,web-1,web,g1,4,16,100,esx01,ds1,placed,')
    expect(lines[3]).toBe('PROD,vc01,web-3,web,g1,,16,,,,unplaced,anti_affinity')
  })

  it('CSV kaçışı: virgül, tırnak ve formül enjeksiyonu', () => {
    expect(csvCell('a,b')).toBe('"a,b"')
    expect(csvCell('say "hi"')).toBe('"say ""hi"""')
    expect(csvCell('=SUM(A1)')).toBe("'=SUM(A1)")
    expect(csvCell(-5)).toBe('-5')
    expect(csvCell(null)).toBe('')
  })

  it('sonuç: yerleşen plan, yerleşemeyen neden (anti-affinity), çip', () => {
    render(<BulkResults res={{ results: [cl], assumptions: ['as-1'] }} />)
    expect(screen.getAllByTestId('bp-plan-row')).toHaveLength(2)
    expect(screen.getByTestId('bp-unplaced').textContent).toContain('vi_lim_anti_affinity')
    expect(screen.getByTestId('bp-status-fail')).toBeTruthy()
    expect(screen.getByTestId('lim-anti_affinity')).toBeTruthy()
    expect(screen.queryByText('vi_bp_csv_all')).toBeNull()   // tek cluster: "tümü" düğmesi yok
  })

  it('profil doğrulama: boş ad, tekrar, sayı hatası', () => {
    const p = (o: object) => ({ id: 1, name: 'a', vcpu: '4', memory_gb: '8', disk_gb: '0', count: '1', group: '', ...o })
    expect(buildProfiles([p({ name: ' ' })]).error).toBe('vi_bp_err_name')
    expect(buildProfiles([p({}), p({ id: 2 })]).error).toBe('vi_bp_err_dup')
    expect(buildProfiles([p({ vcpu: '0' })]).error).toBe('vi_bp_err_num')
    expect(buildProfiles([p({ group: ' g ' })]).profiles).toEqual([{ name: 'a', vcpu: 4, memory_gb: 8, disk_gb: 0, count: 1, group: 'g' }])
  })

  it('form: gövde profiller + kapsam ile gönderilir; (i) simgeleri var', async () => {
    apiSend.mockResolvedValue({ results: [cl], assumptions: [] })
    render(<BulkPlacement scopeBody={() => ({ hypervisor_id: 1 })} />)
    expect(screen.getAllByLabelText('info_btn').length).toBeGreaterThanOrEqual(5)
    fireEvent.change(screen.getByTestId('bp-group'), { target: { value: 'g1' } })
    fireEvent.click(screen.getByText('vi_bp_run'))
    await waitFor(() => expect(apiSend).toHaveBeenCalled())
    const body = apiSend.mock.calls[0][3]
    expect(apiSend.mock.calls[0][1]).toBe('/capacity/bulk-placement')
    expect(body.hypervisor_id).toBe(1)
    expect(body.profiles[0]).toMatchObject({ name: 'web', count: 2, group: 'g1' })
    await waitFor(() => expect(screen.getByTestId('bp-result')).toBeTruthy())
  })

  it('geçersiz profilde istek atılmaz, Türkçe hata gösterilir', () => {
    render(<BulkPlacement />)
    fireEvent.change(screen.getByTestId('bp-name'), { target: { value: '' } })
    fireEvent.click(screen.getByText('vi_bp_run'))
    expect(apiSend).not.toHaveBeenCalled()
    expect(screen.getByTestId('bp-error').textContent).toBe('vi_bp_err_name')
  })
})
