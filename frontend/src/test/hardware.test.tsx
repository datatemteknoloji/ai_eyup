import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const state = { hasHw: true }
vi.mock('../hooks/useCapabilities', () => ({
  useCapabilities: () => ({ capabilities: [], hasBackup: false, hasRealBackup: false, demoActive: false, hasHw: state.hasHw, hwDemoActive: false, isLoading: false }),
}))
vi.mock('../i18n/LocaleProvider', () => ({ useT: () => (k: string, v?: any) => (v ? `${k}:${JSON.stringify(v)}` : k) }))

import HwServerCard from '../components/hardware/HwServerCard'
import { canAccessPath } from '../config/routeAccess'

const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

const SERVER = {
  id: 1, health: 'critical', bmc_ip: '10.1.1.9', bmc_type: 'iDRAC', bmc_version: '5.10', model: 'PowerEdge R740', serial: 'ABC1234',
  form_factor: 'rack', enclosure_name: null, bay: null, warranty: { end_date: '2026-01-01', expired: true, days_remaining: -10 },
  web_url: 'https://ome.example', recent_alerts: [], manager: { name: 'OME', version: '4.7.0' }, collected_at: '2026-10-23T10:00:00Z',
}

function mockFetch(body: any, ok = true) {
  vi.stubGlobal('fetch', vi.fn(async () => ({ ok, json: async () => body })))
}

describe('Donanım kartı (çekmece / host paneli)', () => {
  beforeEach(() => { state.hasHw = true; vi.unstubAllGlobals() })

  it('entegrasyon yoksa (capability yok) hiç istek atmaz ve render etmez', async () => {
    state.hasHw = false
    const f = vi.fn()
    vi.stubGlobal('fetch', f)
    wrap(<HwServerCard kind="server" id={1} />)
    await new Promise(r => setTimeout(r, 20))
    expect(f).not.toHaveBeenCalled()
    expect(screen.queryByTestId('hw-server-card')).toBeNull()
  })

  it('eşleşme yoksa veya 403 ise render edilmez', async () => {
    mockFetch({ available: false, reason: 'no_match' })
    const { unmount } = wrap(<HwServerCard kind="server" id={1} />)
    await new Promise(r => setTimeout(r, 20))
    expect(screen.queryByTestId('hw-server-card')).toBeNull()
    unmount()
    mockFetch({ detail: 'forbidden' }, false)
    wrap(<HwServerCard kind="server" id={2} />)
    await new Promise(r => setTimeout(r, 20))
    expect(screen.queryByTestId('hw-server-card')).toBeNull()
  })

  it('eşleşme varsa alanları gösterir; konsol/güç düğmesi yoktur', async () => {
    mockFetch({ available: true, demo: false, server: SERVER })
    wrap(<HwServerCard kind="server" id={1} />)
    await waitFor(() => expect(screen.getByTestId('hw-server-card')).toBeInTheDocument())
    const txt = screen.getByTestId('hw-server-card').textContent || ''
    expect(txt).toContain('10.1.1.9')
    expect(txt).toContain('ABC1234')
    expect(txt).toContain('hw_warranty_expired')
    expect(screen.queryByRole('button')).toBeNull()               // uzaktan konsol / güç / LED düğmesi YOK
    expect(screen.getByTestId('hw-health-critical')).toBeInTheDocument()
  })

  it('DEMO verisi etiketlenir ve konsol bağlantısı vermez', async () => {
    mockFetch({ available: true, demo: true, server: SERVER })
    wrap(<HwServerCard kind="esxi" id={3} />)
    await waitFor(() => expect(screen.getByTestId('hw-demo-banner')).toBeInTheDocument())
    expect(screen.queryByText(/hw_open_console/)).toBeNull()
  })
})

describe('Donanım rota erişimi', () => {
  const has = (mods: string[]) => (id: string) => mods.includes(id)
  it('/hardware yalnız hardware modülü (veya admin) ile', () => {
    expect(canAccessPath('/hardware', has(['linux', 'integrations']), false)).toBe(false)
    expect(canAccessPath('/hardware', has(['hardware']), false)).toBe(true)
    expect(canAccessPath('/hardware', has([]), true)).toBe(true)
  })
  it('/integrations/hardware yalnız admin', () => {
    expect(canAccessPath('/integrations/hardware', has(['integrations', 'hardware']), false)).toBe(false)
    expect(canAccessPath('/integrations/hardware', has([]), true)).toBe(true)
  })
})
