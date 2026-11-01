import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor, renderHook, act } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import React from 'react'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, p?: Record<string, string | number>) => (p ? `${k}:${Object.values(p).join(',')}` : k),
}))

const facetsMock = vi.fn()
vi.mock('../api/servers', async (orig) => {
  const mod = await orig<typeof import('../api/servers')>()
  return { ...mod, fetchHypervisorFacets: (...a: unknown[]) => facetsMock(...a) }
})

import { HypervisorFilter } from '../components/HypervisorFilter'
import { useHypervisorSelection, loadHypervisorSelection } from '../hooks/useHypervisorSelection'

const env = (id: number, name: string, count = 1, status = 'ONLINE') => ({ id, name, status, count })
const FACETS = {
  groups: [
    { type: 'vmware', label: 'VMware vCenter', environments: [env(2, 'office', 26), env(8, 'ZZ-FAKE-vCenter', 639, 'fake')] },
    { type: 'openshift_virt', label: 'OpenShift Virtualization', environments: [env(6, 'oVirt', 5), env(10, 'ZZ-FAKE-OpenShift', 381, 'fake')] },
    { type: 'kvm', label: 'OLVM / KVM', environments: [env(7, 'Datatem OLVM', 17)] },
  ],
  unassigned_count: 0,
}

function setup(sel: number[] = [], unassigned = false, onChange = vi.fn()) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  const ui = (s: number[], u: boolean) => (
    <QueryClientProvider client={qc}>
      <HypervisorFilter platform="linux" selectedIds={s} includeUnassigned={u} onChange={onChange} />
    </QueryClientProvider>
  )
  const r = render(ui(sel, unassigned))
  return { onChange, rerender: (s: number[], u: boolean) => r.rerender(ui(s, u)) }
}

describe('HypervisorFilter', () => {
  beforeEach(() => { facetsMock.mockReset(); facetsMock.mockResolvedValue(FACETS) })

  it('selection yokken "Tüm ortamlar" etiketi', async () => {
    setup()
    expect(screen.getByTestId('hv-filter-button').textContent).toContain('hv_env_all')
  })

  it('tek ortam seçilince adı, birden çoksa N ortam; tam ad title içinde', async () => {
    const { rerender } = setup([7])
    await waitFor(() => expect(screen.getByTestId('hv-filter-button').textContent).toContain('Datatem OLVM'))
    rerender([7, 2], false)
    expect(screen.getByTestId('hv-filter-button').textContent).toContain('hv_env_n:2')
    expect(screen.getByTestId('hv-filter-button').getAttribute('title')).toBe('Datatem OLVM, office')
    rerender([], true)
    expect(screen.getByTestId('hv-filter-button').textContent).toContain('hv_env_unassigned_short')
  })

  it('DEMO rozeti yalnızca status=fake ortamlarda; sayılar görünür', async () => {
    setup()
    fireEvent.click(screen.getByTestId('hv-filter-button'))
    await screen.findByText('ZZ-FAKE-vCenter')
    expect(screen.getAllByText('hv_env_demo')).toHaveLength(2)
    expect(screen.getByText('639')).toBeTruthy()
  })

  it('başlık checkbox\'ı türün tüm ortamlarını seçer / bırakır', async () => {
    const { onChange, rerender } = setup()
    fireEvent.click(screen.getByTestId('hv-filter-button'))
    await screen.findByText('office')
    fireEvent.click(screen.getByLabelText('VMware vCenter: hv_env_group_toggle'))
    expect(onChange).toHaveBeenLastCalledWith([2, 8], false)
    rerender([2, 8], false)
    fireEvent.click(screen.getByLabelText('VMware vCenter: hv_env_group_toggle'))
    expect(onChange).toHaveBeenLastCalledWith([], false)
  })

  it('"Fiziksel / bağımsız" satırı unassigned\'ı değiştirir', async () => {
    const { onChange } = setup([2])
    fireEvent.click(screen.getByTestId('hv-filter-button'))
    const row = await screen.findByTitle('hv_env_unassigned')
    fireEvent.click(row.closest('label')!.querySelector('input')!)
    expect(onChange).toHaveBeenLastCalledWith([2], true)
  })

  it('arama kutusu yalnızca ortam sayısı > 8 ise görünür', async () => {
    setup()
    fireEvent.click(screen.getByTestId('hv-filter-button'))
    await screen.findByText('office')
    expect(screen.queryByLabelText('hv_env_search')).toBeNull()
  })

  it('9 ortamda arama kutusu çıkar ve filtreler', async () => {
    facetsMock.mockResolvedValue({
      groups: [{ type: 'vmware', label: 'VMware vCenter', environments: Array.from({ length: 9 }, (_, i) => env(i + 1, `vc-${i + 1}`)) }],
      unassigned_count: 0,
    })
    setup()
    fireEvent.click(screen.getByTestId('hv-filter-button'))
    const box = await screen.findByLabelText('hv_env_search')
    fireEvent.change(box, { target: { value: 'vc-3' } })
    expect(screen.getByText('vc-3')).toBeTruthy()
    expect(screen.queryByText('vc-4')).toBeNull()
  })

  it('silinmiş (facet\'te olmayan) ortam seçiliyse temizlenir', async () => {
    const { onChange } = setup([7, 999], true)
    await waitFor(() => expect(onChange).toHaveBeenCalledWith([7], true))
  })

  it('facet isteği hata verirse seçim silinmez', async () => {
    facetsMock.mockRejectedValue(new Error('boom'))
    const { onChange } = setup([999])
    await new Promise((r) => setTimeout(r, 50))
    expect(onChange).not.toHaveBeenCalled()
  })
})

describe('useHypervisorSelection', () => {
  beforeEach(() => window.localStorage.clear())

  it('seçimi platform başına localStorage\'a yazar ve params üretir', () => {
    const { result } = renderHook(() => useHypervisorSelection('linux'))
    expect(result.current.params).toEqual({ hypervisor_ids: undefined, unassigned_hypervisor: undefined })
    act(() => result.current.setSelection([8, 2, 2], true))
    expect(result.current.ids).toEqual([2, 8])
    expect(result.current.params).toEqual({ hypervisor_ids: '2,8', unassigned_hypervisor: true })
    expect(loadHypervisorSelection('linux')).toEqual({ ids: [2, 8], unassigned: true })
    expect(loadHypervisorSelection('windows')).toEqual({ ids: [], unassigned: false })
  })

  it('kaydedilmiş seçimi yükler, bozuk değerleri yok sayar; temizlenince anahtar silinir', () => {
    window.localStorage.setItem('ainew.hv-filter.windows', JSON.stringify({ ids: [3, 'x', -1, 3, 4.5], unassigned: true }))
    const { result } = renderHook(() => useHypervisorSelection('windows'))
    expect(result.current.ids).toEqual([3])
    act(() => result.current.setSelection([], false))
    expect(window.localStorage.getItem('ainew.hv-filter.windows')).toBeNull()
    window.localStorage.setItem('ainew.hv-filter.linux', '{bozuk')
    expect(loadHypervisorSelection('linux')).toEqual({ ids: [], unassigned: false })
  })
})
