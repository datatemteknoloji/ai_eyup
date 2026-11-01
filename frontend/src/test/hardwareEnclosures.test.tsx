import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../hooks/useCapabilities', () => ({
  useCapabilities: () => ({ capabilities: [], hasBackup: false, hasRealBackup: false, demoActive: false, hasHw: true, hwDemoActive: false, isLoading: false }),
}))
vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, unknown>) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr', setLocale: () => {} }),
}))

import HardwarePage from '../pages/HardwarePage'
import { layoutBays } from '../components/hardware/hwUi'

const S = (id: number, bay: string | null, name = `s${id}`) => ({ id, name, bay, health: 'ok', model: 'BL460c' })

describe('layoutBays', () => {
  it('aynı yuvadaki sunucuları tek hücrede toplar, boş yuvaları araya doğal sırayla koyar, yuvasızı sona atar', () => {
    const cells = layoutBays([S(1, '1'), S(2, '3', 'a'), S(3, '3', 'b'), S(4, '10'), S(5, null)], [2, 4, 5, 6, 7, 8, 9])
    expect(cells.map(c => [c.bay, c.empty, c.servers.length])).toEqual([
      ['1', false, 1], ['2', true, 0], ['3', false, 2], ['4', true, 0], ['5', true, 0], ['6', true, 0], ['7', true, 0],
      ['8', true, 0], ['9', true, 0], ['10', false, 1], [null, false, 1],
    ])
  })

  it('Sled-2 < Sled-10 ve 1a < 1b < 2a', () => {
    expect(layoutBays([S(1, 'Sled-10'), S(2, 'Sled-2')]).map(c => c.bay)).toEqual(['Sled-2', 'Sled-10'])
    expect(layoutBays([S(1, '2a'), S(2, '1b'), S(3, '1a')]).map(c => c.bay)).toEqual(['1a', '1b', '2a'])
  })

  it('empty_bays yoksa / null ise yer tutucu üretmez', () => {
    expect(layoutBays([S(1, '1')], null).some(c => c.empty)).toBe(false)
    expect(layoutBays([S(1, '1')]).some(c => c.empty)).toBe(false)
  })
})

describe('Donanım sayfası — Kasalar sekmesi', () => {
  it('boş yuva yer tutucusu «sunucu kaydı yok» der (boş DEMEZ), ortak yuva ×N, atanmamış blade paneli', async () => {
    vi.stubGlobal('fetch', vi.fn(async (u: string) => {
      const body = String(u).includes('/methods') ? { methods: [], classes: [], aliases: {} }
        : String(u).includes('/hw/summary') ? { enabled: true, demo: false, total: 3, matched: 0, unmatched: 3, by_health: {}, by_class: { chassis: 3 }, alerts_24h: 0, active_alerts: 0, providers: [] }
        : String(u).includes('/hw/servers') ? { enabled: true, total: 0, servers: [] }
        : String(u).includes('/hw/enclosures') ? {
          enabled: true, demo: false,
          enclosures: [{ id: 1, name: 'Encl1', model: 'c7000', health: 'ok', bay_count: 4, empty_bays: [2, 4],
            servers: [S(1, '1'), S(2, '3', 'node-a'), S(3, '3', 'node-b')] }],
          unassigned: [{ ...S(9, '5', 'orphan'), enclosure: 'Dup' }],
        } : {}
      return { ok: true, json: async () => body }
    }))
    render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><HardwarePage /></QueryClientProvider></MemoryRouter>)
    fireEvent.click(await screen.findByText('hw_tab_enclosures'))
    await waitFor(() => expect(screen.getAllByTestId('hw-bay').length).toBe(2))
    expect(screen.getAllByTestId('hw-bay-empty').map(e => e.textContent)).toEqual(['#2hw_encl_no_server_record', '#4hw_encl_no_server_record'])
    expect(screen.getAllByTestId('hw-bay-empty')[0]).toHaveAttribute('title', 'hw_encl_no_server_record_hint')
    const shared = screen.getAllByTestId('hw-bay').find(b => b.getAttribute('data-shared') === 'true')!
    expect(within(shared).getByText('node-a')).toBeInTheDocument()
    expect(within(shared).getByText('node-b')).toBeInTheDocument()
    expect(shared.textContent).toContain('×2')
    expect(screen.getByTestId('hw-encl-bays').textContent).toContain('"bays":4')
    expect(within(screen.getByTestId('hw-encl-unassigned')).getByText('orphan')).toBeInTheDocument()
  })
})
