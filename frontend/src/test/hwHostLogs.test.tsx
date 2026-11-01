import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, waitFor, fireEvent } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

vi.mock('../i18n/LocaleProvider', () => ({ useT: () => (k: string, v?: any) => (v ? `${k}:${JSON.stringify(v)}` : k) }))

import HwHostLogsCard from '../components/hardware/HwHostLogsCard'

const wrap = (ui: React.ReactElement) => render(<QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>{ui}</QueryClientProvider>)

const ROW = (i: number, over: any = {}) => ({
  id: i, severity: 'critical', category: 'power', source: 'esxi_sel', message: `PSU ${i} failed`, occurrences: 2,
  first_seen_at: '2026-10-27T08:00:00Z', last_seen_at: '2026-10-27T09:00:00Z', target: { kind: 'esxi', id: 3, name: 'esx01' }, ...over,
})

function mockFetch(body: any, ok = true) {
  const f = vi.fn(async () => ({ ok, json: async () => body }))
  vi.stubGlobal('fetch', f)
  return f
}

describe('Donanım günlükleri kartı (Faz 3a)', () => {
  beforeEach(() => { vi.unstubAllGlobals() })

  it('özellik kapalı / kayıt yoksa render edilmez', async () => {
    mockFetch({ ok: true, enabled: false, available: false, items: [] })
    const { unmount } = wrap(<HwHostLogsCard kind="esxi" id={3} />)
    await new Promise(r => setTimeout(r, 20))
    expect(screen.queryByTestId('hw-host-logs-card')).toBeNull()
    unmount()
    mockFetch({ ok: true, enabled: true, available: true, items: [] })
    wrap(<HwHostLogsCard kind="esxi" id={3} />)
    await new Promise(r => setTimeout(r, 20))
    expect(screen.queryByTestId('hw-host-logs-card')).toBeNull()
  })

  it('403 / hata yanıtında render edilmez', async () => {
    mockFetch({ detail: 'forbidden' }, false)
    wrap(<HwHostLogsCard kind="server" id={1} />)
    await new Promise(r => setTimeout(r, 20))
    expect(screen.queryByTestId('hw-host-logs-card')).toBeNull()
  })

  it('kayıt varsa listeler; ilk 5 satır görünür, "tümünü göster" ile açılır', async () => {
    const items = Array.from({ length: 8 }, (_, i) => ROW(i + 1, i === 0 ? {} : { severity: 'warning', category: 'memory' }))
    const f = mockFetch({ ok: true, enabled: true, available: true, days: 7, counts: { critical: 1, warning: 7 }, items })
    wrap(<HwHostLogsCard kind="esxi" id={3} />)
    await waitFor(() => expect(screen.getByTestId('hw-host-logs-card')).toBeInTheDocument())
    expect(String((f.mock.calls[0] as any)[0])).toContain('/hw/host-logs?kind=esxi&id=3')
    expect(screen.getAllByTestId('hw-host-log-row')).toHaveLength(5)
    fireEvent.click(screen.getByText(/hwlog_more/))
    expect(screen.getAllByTestId('hw-host-log-row')).toHaveLength(8)
  })

  it('salt-okunur: yalnız aç/kapat düğmesi vardır (konsol/güç/temizle yok)', async () => {
    mockFetch({ ok: true, enabled: true, available: true, counts: { critical: 1 }, items: [ROW(1)] })
    wrap(<HwHostLogsCard kind="server" id={9} />)
    await waitFor(() => expect(screen.getByTestId('hw-host-logs-card')).toBeInTheDocument())
    expect(screen.queryAllByRole('button')).toHaveLength(0)                   // 1 satır < eşik → düğme bile yok
    expect(screen.getByTestId('hw-host-logs-card').textContent).toContain('PSU 1 failed')
  })

  it('showEmpty: özellik açık + kayıt yok → «kayıt yok · son toplama» satırı; kapalıysa hiçbir şey', async () => {
    mockFetch({ ok: true, enabled: true, available: false, days: 7, items: [], last_run_at: '2026-10-27T11:52:00Z', last_run_errors: 0 })
    const { unmount } = wrap(<HwHostLogsCard kind="esxi" id={3} showEmpty />)
    await waitFor(() => expect(screen.getByTestId('hw-host-logs-empty')).toBeInTheDocument())
    const txt = screen.getByTestId('hw-host-logs-empty').textContent || ''
    expect(txt).toContain('hwlog_none')
    expect(txt).toContain('hwlog_last_run')
    expect(txt).not.toContain('hwlog_run_errors')
    unmount()
    mockFetch({ ok: true, enabled: false, available: false, items: [] })
    wrap(<HwHostLogsCard kind="esxi" id={3} showEmpty />)
    await new Promise(r => setTimeout(r, 20))
    expect(screen.queryByTestId('hw-host-logs-empty')).toBeNull()
  })

  it('showEmpty: hiç toplanmadıysa «henüz toplanmadı»; hata varsa uyarı; showEmpty yoksa gizli', async () => {
    mockFetch({ ok: true, enabled: true, available: false, days: 7, items: [], last_run_at: null, last_run_errors: 2 })
    const { unmount } = wrap(<HwHostLogsCard kind="esxi" id={3} showEmpty />)
    await waitFor(() => expect(screen.getByTestId('hw-host-logs-empty')).toBeInTheDocument())
    const txt = screen.getByTestId('hw-host-logs-empty').textContent || ''
    expect(txt).toContain('hwlog_never_run')
    expect(txt).toContain('hwlog_run_errors')
    unmount()
    mockFetch({ ok: true, enabled: true, available: false, days: 7, items: [] })
    wrap(<HwHostLogsCard kind="server" id={3} />)
    await new Promise(r => setTimeout(r, 20))
    expect(screen.queryByTestId('hw-host-logs-empty')).toBeNull()
  })

  it('kayıtlı kartın altında da son toplama zamanı yazar', async () => {
    mockFetch({ ok: true, enabled: true, available: true, counts: { critical: 1 }, items: [ROW(1)], last_run_at: '2026-10-27T11:52:00Z' })
    wrap(<HwHostLogsCard kind="esxi" id={3} />)
    await waitFor(() => expect(screen.getByTestId('hw-host-logs-card')).toBeInTheDocument())
    expect(screen.getByTestId('hw-host-logs-card').textContent).toContain('hwlog_last_run')
  })
})
