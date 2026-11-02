import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

// Faz 3c: portal (OME/OneView) yokken log odaklı Donanım sayfası.
const caps = { hasHw: false, hasHwLogs: true }
vi.mock('../hooks/useCapabilities', () => ({
  useCapabilities: () => ({ capabilities: [], hasBackup: false, hasRealBackup: false, demoActive: false, hasHw: caps.hasHw, hasHwLogs: caps.hasHwLogs, hwDemoActive: false, isLoading: false }),
}))
vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string) => k,
  useLocale: () => ({ locale: 'tr', setLocale: () => {} }),
}))

import HardwarePage from '../pages/HardwarePage'

function mount(urls: string[]) {
  vi.stubGlobal('fetch', vi.fn(async (u: string) => {
    urls.push(String(u))
    const s = String(u)
    const body = s.includes('/hw/summary') ? { enabled: false }
      : s.includes('/hw/log-overview') ? { ok: true, enabled: true, available: true, total: 0, items: [], counts: {}, sources: [] }
      : s.includes('/hw/bmc/overview') ? { ok: true, endpoints: [], profiles: [], flags: {} }
      : {}
    return { ok: true, json: async () => body }
  }))
  return render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><HardwarePage /></QueryClientProvider></MemoryRouter>)
}

describe('Donanım sayfası — portalsız log modu', () => {
  beforeEach(() => { vi.unstubAllGlobals(); caps.hasHw = false; caps.hasHwLogs = true })

  it('yalnız Loglar + BMC sekmeleri; portal sekmeleri/KPI yok; /summary çağrılmaz; not görünür', async () => {
    const urls: string[] = []
    mount(urls)
    await waitFor(() => expect(screen.getByTestId('hw-logs-only')).toBeInTheDocument())
    expect(screen.getByTestId('hw-logs-only-note')).toHaveTextContent('hw_logs_only_note')
    expect(screen.getByText('hw_tab_logs')).toBeInTheDocument()
    expect(screen.getByText('hw_tab_bmc')).toBeInTheDocument()
    for (const k of ['hw_tab_servers', 'hw_tab_enclosures', 'hw_tab_alerts', 'hw_tab_warranty', 'hw_tab_unmatched', 'hw_tab_firmware', 'hw_tab_findings', 'hw_kpi_total'])
      expect(screen.queryByText(k)).toBeNull()
    await waitFor(() => expect(urls.some(u => u.includes('/hw/log-overview'))).toBe(true))
    expect(urls.some(u => u.includes('/hw/summary'))).toBe(false)
    expect(urls.some(u => /\/hw\/(servers|enclosures|alerts|warranty-report|unmatched|findings|firmware)/.test(u))).toBe(false)
  })

  it('BMC sekmesine geçilir; portal uçlarına yine istek atılmaz', async () => {
    const urls: string[] = []
    mount(urls)
    fireEvent.click(await screen.findByText('hw_tab_bmc'))
    await waitFor(() => expect(urls.some(u => u.includes('/hw/bmc/overview'))).toBe(true))
    expect(urls.some(u => u.includes('/hw/summary'))).toBe(false)
  })

  it('portal VARSA tam sayfa (logsOnly değil): /summary çağrılır, portal sekmeleri görünür', async () => {
    caps.hasHw = true
    const urls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (u: string) => {
      urls.push(String(u))
      const body = String(u).includes('/hw/summary') ? { enabled: true, demo: false, total: 0, matched: 0, unmatched: 0, by_health: {}, alerts_24h: 0, active_alerts: 0, providers: [] } : { enabled: true, servers: [], total: 0 }
      return { ok: true, json: async () => body }
    }))
    render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><HardwarePage /></QueryClientProvider></MemoryRouter>)
    await waitFor(() => expect(screen.getByText('hw_tab_servers')).toBeInTheDocument())
    expect(screen.queryByTestId('hw-logs-only')).toBeNull()
    expect(urls.some(u => u.includes('/hw/summary'))).toBe(true)
  })

  it('portal de log de yoksa mevcut boş durum (hw_none)', async () => {
    caps.hasHw = false
    caps.hasHwLogs = false
    mount([])
    await waitFor(() => expect(screen.getByText('hw_none')).toBeInTheDocument())
    expect(screen.queryByTestId('hw-logs-only')).toBeNull()
  })
})
