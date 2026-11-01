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
import { splitFirmware } from '../components/hardware/hwUi'

describe('splitFirmware', () => {
  it('Installed (ve durumu bilinmeyen) kurulu; Available önceki/yedek', () => {
    const r = splitFirmware([
      { name: 'BIOS', status: 'Installed', version: '1' }, { name: 'iDRAC', status: 'Available', version: '0' },
      { name: 'NIC', status: null, version: '2' },
    ])
    expect(r.installed.map(x => x.name)).toEqual(['BIOS', 'NIC'])
    expect(r.previous.map(x => x.name)).toEqual(['iDRAC'])
  })
})

function mount(detail: Record<string, unknown>) {
  vi.stubGlobal('fetch', vi.fn(async (u: string) => {
    const url = String(u)
    const body = url.includes('/methods') ? { methods: [], classes: [], aliases: {} }
      : url.includes('/hw/summary') ? { enabled: true, demo: false, total: 1, matched: 0, unmatched: 1, by_health: {}, by_class: { physical: 1 }, alerts_24h: 0, active_alerts: 0, providers: [] }
      : /\/hw\/servers\/\d+/.test(url) ? { server: { id: 1, name: 'srv-0', vendor: 'dell', health: 'ok', ...detail } }
      : url.includes('/hw/servers') ? { enabled: true, total: 1, servers: [{ id: 1, name: 'srv-0', vendor: 'dell', health: 'ok', host_class: 'physical' }] } : {}
    return { ok: true, json: async () => body }
  }))
  render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><HardwarePage /></QueryClientProvider></MemoryRouter>)
}

describe('Donanım sayfası — firmware listesi', () => {
  it('açılan satırda Installed satırlar, Available ayrı katlanır bölümde', async () => {
    mount({ bios_version: '1.2.3', firmware_collected_at: '2026-11-01T10:00:00Z', firmware: [
      { name: 'BIOS', type: 'BIOS', version: '1.2.3', status: 'Installed' },
      { name: 'iDRAC', type: 'FRMW', version: '7.00', status: 'Installed' },
      { name: 'iDRAC', type: 'FRMW', version: '6.10', status: 'Available' },
    ] })
    fireEvent.click(await screen.findByTestId('hw-row'))
    const fw = await screen.findByTestId('hw-fw')
    expect(fw.textContent).toContain('hw_fw_title:{"n":2}')
    expect(within(fw).getAllByTestId('hw-fw-row').length).toBe(3)            // 2 kurulu + 1 önceki (DOM'da, <details> kapalı olsa da)
    expect(fw.textContent).toContain('hw_fw_prev')
    expect(screen.queryByTestId('hw-fw-none')).toBeNull()
  })

  it('firmware yoksa nedenini söyler', async () => {
    mount({ firmware: [] })
    fireEvent.click(await screen.findByTestId('hw-row'))
    await waitFor(() => expect(screen.getByTestId('hw-fw-none').textContent).toBe('hw_fw_none'))
    expect(screen.queryByTestId('hw-fw')).toBeNull()
  })
})
