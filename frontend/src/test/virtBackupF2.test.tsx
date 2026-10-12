import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const DATA: Record<string, any> = {}
vi.mock('../hooks/useCapabilities', () => ({
  useCapabilities: () => ({ capabilities: ['backup'], hasBackup: true, hasRealBackup: true, demoActive: false, isLoading: false }),
}))
vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, any>) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr' }),
}))
vi.mock('../components/insights/insightsKit', async (orig) => {
  const actual: any = await orig()
  return {
    ...actual,
    PageInfo: () => null,
    Panel: ({ children, title }: any) => <section>{title ? <h3>{title}</h3> : null}{children}</section>,
    useRole: () => ({ isAdmin: false, isOperator: false }),
    useInsights: (_b: string, path: string) => ({ data: DATA[path.split('?')[0]], refetch: () => {} }),
  }
})

import VirtBackup from '../pages/VirtBackup'

function mount() {
  const qc = new QueryClient()
  return render(<QueryClientProvider client={qc}><MemoryRouter><VirtBackup /></MemoryRouter></QueryClientProvider>)
}

describe('F.2 Yedek sekmeleri', () => {
  beforeEach(() => {
    DATA['/backup/rpo'] = { vms: [{ name: 'vm1', state: 'protected', rpo_state: 'ok', rto_state: 'unverified', powered_on: true }] }
    DATA['/backup/policies'] = { policies: [] }
    DATA['/backup/summary'] = { enabled: true, providers: [], jobs: 2, repositories: 1 }
    DATA['/backup/jobs'] = { jobs: [
      { id: 1, name: 'okunan', type: 'backup', config_state: 'ok', encryption: false, cbt: true, app_aware: null,
        retention_type: 'Days', retention_quantity: 7, gfs_enabled: false, schedule_summary: 'Günlük 10:00',
        retry_enabled: true, retry_count: 3, retry_wait_min: 10, window_enabled: false, backup_health: null },
      { id: 2, name: 'yetkisiz', type: 'backup', config_state: 'forbidden', encryption: null, cbt: null },
    ] }
    DATA['/backup/repositories'] = { repositories: [{ id: 1, name: 'R1', type: 'LinuxHardened', used_pct: 10, warn_pct: 85, free_gb: 5, online: true }] }
    DATA['/backup/proxies'] = { proxies: [
      { id: 1, name: 'P1', type: 'ViProxy', host: 'This server', online: true, disabled: false, out_of_date: true, transport_mode: 'auto', max_tasks: 2 },
    ] }
    DATA['/backup/security'] = {
      encryption: { counts: { enabled: 0, disabled: 1, not_measurable: 1 }, jobs: [
        { job: 'okunan', encryption: 'disabled', cbt: true }, { job: 'yetkisiz', encryption: 'not_measurable', cbt: null, reason: 'ölçülemedi (yetki)' }] },
      immutability: { status: 'not_measurable', repositories: [{ name: 'R1', type: 'LinuxHardened', status: 'not_measurable' }] },
      access: [{ key: 'server_info', path: '/api/v1/serverInfo', roles: 'Backup Administrator', viewer_ok: false, doc: 'https://x', states: { vbr: 'forbidden' } },
               { key: 'jobs', path: '/api/v1/jobs', roles: 'Admin/Viewer', viewer_ok: true, doc: 'https://y', states: { vbr: 'ok' } }],
      field_note: 'not verified',
    }
  })

  it('Jobs tab: eksik alan "—" (kapalı değil), yetkisiz iş "ölçülemedi (yetki)"', () => {
    mount()
    fireEvent.click(screen.getByText('bk_tab_jobs'))
    expect(screen.getByText('okunan')).toBeTruthy()
    expect(screen.getAllByText('bk_f2_nm_perm').length).toBeGreaterThan(0)    // yetkisiz iş
    expect(screen.getAllByTestId('bk-nm').length).toBeGreaterThan(0)           // app_aware=null → —
    expect(screen.getByText('Günlük 10:00')).toBeTruthy()
    expect(screen.getByTestId('bk-field-note').textContent).toBe('bk_f2_field_note')
  })

  it('Repos tab: değişmezlik daima "ölçülemedi"', () => {
    mount()
    fireEvent.click(screen.getByText('bk_tab_repos'))
    expect(screen.getByTestId('bk-immut-nm').textContent).toBe('bk_f2_nm')
  })

  it('Altyapı tab: proxy durumu ve "güncel değil"', () => {
    mount()
    fireEvent.click(screen.getByText('bk_f2_tab_infra'))
    expect(screen.getByText('P1')).toBeTruthy()
    expect(screen.getByText('This server')).toBeTruthy()
    expect(screen.getByText('bk_f2_proxy_online')).toBeTruthy()
    expect(screen.getByText(/bk_f2_proxy_outdated/)).toBeTruthy()
  })

  it('Güvenlik tab: şifreleme sayıları, değişmezlik ölçülemedi, Viewer-kapalı endpoint', () => {
    mount()
    fireEvent.click(screen.getByText('bk_f2_tab_security'))
    expect(screen.getByTestId('bk-sec-enc-counts').textContent).toContain('"nm":1')
    expect(screen.getByTestId('bk-sec-imm').textContent).toBe('bk_f2_sec_imm_nm')
    expect(screen.getByText('/api/v1/serverInfo')).toBeTruthy()
    expect(screen.getByText('bk_f2_nm_perm')).toBeTruthy()      // serverInfo forbidden
  })

  it('F.3: RTO "doğrulanmadı" rozeti ve not; tahmin değeri gösterilmez', () => {
    mount()
    const b = screen.getByTestId('bk-rto-badge')
    expect(b.textContent).toBe('bk_f3_rto_unverified')
    expect(b.getAttribute('title')).toBe('bk_f3_rto_note')
    fireEvent.click(screen.getByText('bk_tab_policies'))
    expect(screen.getByTestId('bk-rto-note').textContent).toBe('bk_f3_rto_note')
  })
})
