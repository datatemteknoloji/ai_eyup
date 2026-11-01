import { describe, it, expect, vi } from 'vitest'
import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../hooks/useCapabilities', () => ({
  useCapabilities: () => ({ capabilities: [], hasBackup: false, hasRealBackup: false, demoActive: false, hasHw: true, hwDemoActive: false, isLoading: false }),
}))
vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string) => k,
  useLocale: () => ({ locale: 'tr', setLocale: () => {} }),
}))

import HardwarePage from '../pages/HardwarePage'

describe('Donanım sayfası — host sınıfı chip\'leri', () => {
  it('yalnız sayısı > 0 olan sınıflar görünür; tıklama host_class isteğini değiştirir; satırda sınıf etiketi', async () => {
    const urls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (u: string) => {
      urls.push(String(u))
      const body = String(u).includes('/methods') ? { methods: [], classes: [], aliases: {} }
        : String(u).includes('/hw/summary') ? { enabled: true, demo: false, total: 56, matched: 14, unmatched: 42, by_health: {}, by_class: { esxi: 8, chassis: 24, physical: 24 }, alerts_24h: 0, active_alerts: 0, providers: [] }
        : String(u).includes('/hw/servers') ? { enabled: true, total: 1, servers: [{ id: 1, name: 'esx-01', vendor: 'hpe', health: 'ok', host_class: 'esxi' }] } : {}
      return { ok: true, json: async () => body }
    }))
    render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><HardwarePage /></QueryClientProvider></MemoryRouter>)
    await waitFor(() => expect(screen.getByTestId('hw-class-chips')).toBeInTheDocument())
    expect(screen.getByTestId('hw-class-all').textContent).toContain('56')
    expect(screen.getByTestId('hw-class-esxi').textContent).toContain('8')
    expect(screen.queryByTestId('hw-class-ocp')).toBeNull()             // 0 olan sınıf gizli
    expect(screen.queryByTestId('hw-class-olvm')).toBeNull()
    await waitFor(() => expect(screen.getByTestId('hw-class-tag').textContent).toBe('hw_class_esxi'))
    fireEvent.click(screen.getByTestId('hw-class-chassis'))
    await waitFor(() => expect(urls.filter(u => u.includes('/hw/servers')).slice(-1)[0]).toContain('host_class=chassis'))
    expect(screen.getByTestId('hw-class-chassis')).toHaveAttribute('aria-pressed', 'true')
    fireEvent.click(screen.getByTestId('hw-class-all'))
    await waitFor(() => expect(urls.filter(u => u.includes('/hw/servers')).slice(-1)[0]).not.toContain('host_class=chassis'))
  })
})
