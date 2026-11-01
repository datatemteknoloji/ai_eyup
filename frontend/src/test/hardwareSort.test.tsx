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

describe('Donanım sayfası — sütun sıralama', () => {
  it('9 sütun başlığı sıralanabilir; tıklama asc → desc → kapalı ve istek sort_by/sort_dir taşır', async () => {
    const urls: string[] = []
    vi.stubGlobal('fetch', vi.fn(async (u: string) => {
      urls.push(String(u))
      const body = String(u).includes('/methods') ? { methods: [], classes: [], aliases: {} } : String(u).includes('/hw/summary') ? { enabled: true, demo: false, total: 0, matched: 0, unmatched: 0, by_health: {}, alerts_24h: 0, active_alerts: 0, providers: [] }
        : String(u).includes('/hw/servers') ? { enabled: true, servers: [], total: 0 } : {}
      return { ok: true, json: async () => body }
    }))
    render(<MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}><HardwarePage /></QueryClientProvider></MemoryRouter>)
    const cols = ['name', 'vendor', 'model', 'serial', 'bmc_ip', 'bmc_version', 'bios_version', 'health', 'enclosure', 'warranty', 'match']
    for (const c of cols) await waitFor(() => expect(screen.getByTestId(`hw-sort-${c}`)).toBeInTheDocument())
    const last = () => urls.filter(u => u.includes('/hw/servers')).slice(-1)[0]
    expect(last()).not.toContain('sort_by')
    fireEvent.click(screen.getByTestId('hw-sort-bmc_ip'))
    await waitFor(() => expect(last()).toContain('sort_by=bmc_ip&sort_dir=asc'))
    expect(screen.getByTestId('hw-sort-bmc_ip').closest('th')).toHaveAttribute('aria-sort', 'ascending')
    fireEvent.click(screen.getByTestId('hw-sort-bmc_ip'))
    await waitFor(() => expect(last()).toContain('sort_by=bmc_ip&sort_dir=desc'))
    fireEvent.click(screen.getByTestId('hw-sort-warranty'))                              // başka sütun → asc'tan başlar
    await waitFor(() => expect(last()).toContain('sort_by=warranty&sort_dir=asc'))
    fireEvent.click(screen.getByTestId('hw-sort-warranty'))
    fireEvent.click(screen.getByTestId('hw-sort-warranty'))                              // desc → kapalı
    await waitFor(() => expect(last()).not.toContain('sort_by'))
  })
})
