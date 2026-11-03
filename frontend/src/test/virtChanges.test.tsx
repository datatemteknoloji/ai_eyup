import { describe, it, expect, vi, beforeEach } from 'vitest'
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

let role = 'operator'
vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: any) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr', setLocale: () => {} }),
}))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { role, is_admin: role === 'admin' } }) }))
vi.mock('../components/insights/insightsKit', async importOriginal => {
  const m = await importOriginal<typeof import('../components/insights/insightsKit')>()
  return { ...m, PageInfo: () => <span />, RunBar: () => <span /> }
})

vi.mock('../components/insights/MethodBadge', () => ({ default: () => <span />, MethodBadge: () => <span /> }))

import { ChangesView } from '../pages/VirtChanges'

const change = (id: number, extra: Record<string, unknown> = {}) => ({
  id, platform: 'vmware', source_id: 1, entity_kind: 'host', entity_ref: `h${id}`, entity_name: `esx${id}`, cluster_name: 'C1',
  captured_at: '2026-11-01T10:00:00Z', previous_at: '2026-10-31T10:00:00Z',
  changes: [{ path: 'ntp', op: 'changed', old: 'a', new: 'b' }], change_count: 1,
  is_baseline: false, has_baseline: false, acked: false, ...extra,
})
let CHANGES: Record<string, unknown>
const BASELINE = {
  drifted: 1, count: 2,
  items: [
    { platform: 'vmware', source_id: 1, entity_kind: 'host', entity_ref: 'h1', entity_name: 'esx1', baseline_at: '2026-10-01T10:00:00Z',
      baseline_by: 'ayse', latest_at: '2026-11-01T10:00:00Z', drift_count: 1, status: 'drift', changes: [{ path: 'ntp', op: 'changed', old: 'a', new: 'b' }] },
    { platform: 'vmware', source_id: 1, entity_kind: 'cluster', entity_ref: 'c1', entity_name: 'C1', baseline_at: '2026-10-01T10:00:00Z',
      baseline_by: 'ayse', latest_at: '2026-10-01T10:00:00Z', drift_count: 0, status: 'same', changes: [] },
  ],
}
const calls: { url: string; method: string; body?: string }[] = []

function mockApi() {
  vi.stubGlobal('fetch', vi.fn(async (url: string, init?: RequestInit) => {
    const u = String(url)
    calls.push({ url: u, method: init?.method || 'GET', body: init?.body as string | undefined })
    const json = (b: unknown) => ({ ok: true, json: async () => b })
    if (u.includes('/changes/ack')) return json({ ok: true, count: 1 })
    if (u.includes('/changes')) return json(CHANGES)
    if (u.includes('/baseline')) return json(init?.method === 'POST' || init?.method === 'DELETE' ? { ok: true, count: 1 } : BASELINE)
    if (u.includes('/summary')) return json({ last_run: null })
    return json({})
  }))
}
const wrap = () => render(
  <MemoryRouter><QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
    <ChangesView base="virt-insights" />
  </QueryClientProvider></MemoryRouter>,
)

beforeEach(() => {
  vi.unstubAllGlobals(); calls.length = 0; role = 'operator'
  CHANGES = {
    changes: [change(1, { has_baseline: true, baseline_by: 'ayse', baseline_at: '2026-10-01T10:00:00Z' }), change(2)],
    count: 2, baseline_count: 2, baseline_by_kind: { host: 1, cluster: 1 }, baseline_marked_at: '2026-10-01T10:00:00Z',
    baseline_marked_by: 'ayse', drifted_count: 1, changed_unbaselined: 1, changed_unbaselined_kinds: { host: 1 }, acked_total: 3,
  }
  mockApi()
})

describe('Değişiklikler / baseline', () => {
  it('baseline kim/ne zaman işaretledi + sapma sayısı + baseline\'sız değişiklik uyarısı gösterilir', async () => {
    wrap()
    const banner = await screen.findByTestId('baseline-banner')
    expect(banner).toHaveTextContent('"u":"ayse"')
    expect(banner).toHaveTextContent('"d":1')
    expect(await screen.findByTestId('unbaselined-note')).toHaveTextContent('"n":1')
    expect(screen.getByTestId('acked-hidden')).toHaveTextContent('"n":3')
    expect(screen.getAllByTestId('change-row')[0]).toHaveTextContent('"u":"ayse"')   // satırda baseline sahibi
  })

  it('sapma 0 iken «neden 0» açıklaması gösterilir', async () => {
    CHANGES = { ...CHANGES, drifted_count: 0, changed_unbaselined: 0 }
    wrap()
    expect(await screen.findByTestId('zero-drift-note')).toBeInTheDocument()
  })

  it('«gözden geçirildi» seçili satırlar için ack endpoint\'ini çağırır; viewer seçemez', async () => {
    wrap()
    const boxes = await screen.findAllByTestId('change-select')
    fireEvent.click(boxes[1])
    fireEvent.click(await screen.findByText(/vi_ch_ack_selected/))
    await waitFor(() => expect(calls.some(c => c.url.includes('/changes/ack') && c.method === 'POST' && JSON.parse(c.body!).ids[0] === 2)).toBe(true))
  })

  it('viewer rolünde seçim kutusu ve işlem düğmeleri yok', async () => {
    role = 'viewer'
    wrap()
    await screen.findAllByTestId('change-row')
    expect(screen.queryByTestId('change-select')).toBeNull()
    expect(screen.queryByText('vi_ch_ack_btn')).toBeNull()
    expect(screen.queryByText('vi_bl_btn')).toBeNull()
  })

  it('Baseline\'lar sekmesi canlı sapmayı listeler, satır tıklayınca baseline↔güncel fark açılır', async () => {
    wrap()
    fireEvent.click(await screen.findByText('vi_ch_tab_baselines'))
    const view = await screen.findByTestId('baselines-view')
    const rows = await within(view).findAllByTestId('baseline-row')
    expect(rows).toHaveLength(2)
    expect(rows[0]).toHaveTextContent('vi_bl_status_drift')
    fireEvent.click(rows[0])
    expect(await screen.findByText('vi_bl_compare_title')).toBeInTheDocument()
    expect(screen.getByText('ntp')).toBeInTheDocument()
  })

  it('toplu baseline: mevcut baseline varsa onay kutusu işaretlenmeden uygulanamaz', async () => {
    wrap()
    fireEvent.click(await screen.findByText('vi_bl_btn'))
    expect(await screen.findByTestId('baseline-overwrite-warning')).toBeInTheDocument()
    const apply = screen.getByText('vi_bl_apply')
    expect(apply).toBeDisabled()
    fireEvent.click(screen.getByTestId('baseline-overwrite-confirm'))
    expect(apply).not.toBeDisabled()
  })

  it('baseline yoksa toplu baseline onay istemez', async () => {
    CHANGES = { ...CHANGES, baseline_count: 0, baseline_by_kind: {}, drifted_count: 0, changed_unbaselined: 0 }
    wrap()
    fireEvent.click(await screen.findByText('vi_bl_btn'))
    await screen.findByText('vi_bl_apply')
    expect(screen.queryByTestId('baseline-overwrite-warning')).toBeNull()
    expect(screen.getByText('vi_bl_apply')).not.toBeDisabled()
  })
})
