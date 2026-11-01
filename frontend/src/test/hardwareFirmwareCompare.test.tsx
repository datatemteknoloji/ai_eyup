import { describe, it, expect, vi, beforeEach } from 'vitest'
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
import { HwFirmwareTab } from '../components/hardware/HwFirmwareTab'

const GROUPS = {
  enabled: true, groups: [{
    vendor: 'hpe', model: 'ProLiant DL380 Gen10', total: 3, with_firmware: 3, outdated: 1, accepted: 0, unknown: 0,
    reference: { id: 9, server_id: 1, server_name: 'ref-srv', scope: 'model' },
    chassis_refs: [{ id: 10, server_id: 2, server_name: 'enc-ref', scope: 'chassis', enclosure_id: 5, enclosure_name: 'Encl-1' }],
    servers: [
      { id: 1, name: 'ref-srv', status: 'reference', components: [], outdated: 0, accepted: 0, unknown: 0, compared: 0, firmware_rows: 2 },
      { id: 3, name: 'low-srv', status: 'outdated', components: [
        { key: 'ilo 5|', name: 'iLO 5', location: null, version: '2.72', reference_version: '2.81', state: 'outdated', accepted: false },
      ], outdated: 1, accepted: 0, unknown: 0, compared: 2, firmware_rows: 2 },
      { id: 4, name: 'ok-srv', status: 'ok', components: [], outdated: 0, accepted: 0, unknown: 0, compared: 2, firmware_rows: 2 },
    ],
  }],
}

let calls: Array<{ url: string; method: string; body?: any }>

beforeEach(() => {
  calls = []
  vi.stubGlobal('fetch', vi.fn(async (u: string, init?: RequestInit) => {
    const url = String(u)
    calls.push({ url, method: init?.method || 'GET', body: init?.body ? JSON.parse(String(init.body)) : undefined })
    if (init?.method === 'POST' && url.includes('/firmware/references') && (JSON.parse(String(init.body)).scope === 'chassis'))
      return { ok: false, status: 400, json: async () => ({ detail: 'Sunucunun şasisi belirlenemedi' }) }
    return { ok: true, json: async () => (url.includes('/firmware/compare') ? GROUPS : { ok: true }) }
  }))
})

function wrap(ui: React.ReactElement) {
  return render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider></MemoryRouter>)
}

describe('Firmware sekmesi', () => {
  it('model grubunu, model ve şasi referansını ve düşük bileşeni gösterir', async () => {
    wrap(<HwFirmwareTab />)
    const g = await screen.findByTestId('hw-fwc-group')
    expect(g.textContent).toContain('ProLiant DL380 Gen10')
    expect(g.textContent).toContain('ref-srv')
    expect(g.textContent).toContain('enc-ref')
    expect(g.textContent).toContain('Encl-1')
    const comp = within(g).getByTestId('hw-fwc-comp')
    expect(comp.textContent).toContain('2.72')
    expect(comp.textContent).toContain('2.81')
    expect(within(comp).getByTestId('hw-fw-state').textContent).toBe('hw_fwc_state_outdated')
  })

  it('«Kabul et» yalnız o bileşeni gönderir', async () => {
    wrap(<HwFirmwareTab />)
    fireEvent.click(await screen.findByTestId('hw-fwc-accept'))
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/hw/firmware/accept') && c.method === 'POST')).toBe(true))
    const c = calls.find(x => x.url.endsWith('/hw/firmware/accept'))!
    expect(c.body).toMatchObject({ server_id: 3, component_keys: ['ilo 5|'] })
  })

  it('model referansı yap uç noktasını çağırır; şasi hatasını gösterir', async () => {
    wrap(<HwFirmwareTab />)
    const row = (await screen.findAllByTestId('hw-fwc-server')).find(r => r.textContent?.includes('low-srv'))!
    fireEvent.click(within(row).getByTestId('hw-fwc-set-model'))
    await waitFor(() => expect(calls.some(c => c.url.endsWith('/hw/firmware/references') && c.body?.scope === 'model' && c.body?.server_id === 3)).toBe(true))
    fireEvent.click(within(row).getByTestId('hw-fwc-set-chassis'))
    expect((await screen.findAllByRole('alert'))[0].textContent).toContain('şasisi belirlenemedi')
  })

  it('«Yalnız düşük olanlar» sağlam sunucuları gizler', async () => {
    wrap(<HwFirmwareTab />)
    await screen.findByTestId('hw-fwc-group')
    expect(screen.getAllByTestId('hw-fwc-server').length).toBe(3)
    fireEvent.click(screen.getByRole('checkbox'))
    await waitFor(() => expect(screen.getAllByTestId('hw-fwc-server').length).toBe(1))
  })

  it('veri yoksa boş durum', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ({ enabled: true, groups: [] }) })))
    wrap(<HwFirmwareTab />)
    await waitFor(() => expect(screen.getByTestId('hw-fwc-tab').textContent).toContain('hw_fwc_none'))
  })
})

describe('Sunucu satırı — referans paneli', () => {
  it('açılan satırda durum, referans ve karşılaştırma görünür', async () => {
    vi.stubGlobal('fetch', vi.fn(async (u: string) => {
      const url = String(u)
      const body = url.includes('/methods') ? { methods: [], classes: [], aliases: {} }
        : url.includes('/hw/summary') ? { enabled: true, total: 1, matched: 0, unmatched: 1, by_health: {}, by_class: { physical: 1 }, alerts_24h: 0, active_alerts: 0, providers: [] }
        : /\/hw\/servers\/\d+/.test(url) ? { server: { id: 3, name: 'low-srv', vendor: 'hpe', health: 'ok', firmware: [{ name: 'iLO 5', version: '2.72', status: 'Installed' }],
          firmware_status: { server_id: 3, status: 'outdated', compared: 2, outdated: 1, accepted: 0, unknown: 0,
            reference: { id: 9, server_id: 1, name: 'ref-srv', scope: 'model' },
            components: [{ key: 'ilo 5|', name: 'iLO 5', version: '2.72', reference_version: '2.81', state: 'outdated' }] } } }
        : url.includes('/hw/servers') ? { enabled: true, total: 1, servers: [{ id: 3, name: 'low-srv', vendor: 'hpe', health: 'ok', host_class: 'physical' }] } : {}
      return { ok: true, json: async () => body }
    }))
    wrap(<HardwarePage />)
    fireEvent.click(await screen.findByTestId('hw-row'))
    const p = await screen.findByTestId('hw-fwc-panel')
    expect(p.textContent).toContain('hw_fwc_ref_line')
    expect(p.textContent).toContain('ref-srv')
    expect(within(p).getByTestId('hw-fwc-comp').textContent).toContain('2.81')
    expect(within(p).getByTestId('hw-fwc-set-model')).toBeTruthy()
  })
})
