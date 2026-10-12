import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

const DATA: Record<string, any> = {}
vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, any>) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr' }),
}))
vi.mock('../auth/AuthContext', () => ({ useAuth: () => ({ user: { role: 'admin', is_admin: true } }) }))
vi.mock('../components/insights/MethodBadge', async (orig) => {
  const actual: any = await orig()
  return { ...actual, MethodBadge: ({ id }: any) => <span data-testid="mb">{id}</span> }
})
vi.mock('../components/insights/insightsKit', async (orig) => {
  const actual: any = await orig()
  return {
    ...actual,
    useRole: () => ({ isAdmin: true, isOperator: true }),
    useInsights: (_b: string, path: string) => ({ data: DATA[path.split('?')[0]] }),
  }
})

import { ReferencePacksCard } from '../components/insights/ReferencePacksCard'
import { FindingsTable, type Finding } from '../components/insights/insightsKit'

const wrap = (el: React.ReactNode) => render(<QueryClientProvider client={new QueryClient()}><MemoryRouter>{el}</MemoryRouter></QueryClientProvider>)

describe('G referans paketi arayüzü', () => {
  it('kart: yok / güncel / güncel değil durumlarını ve paket başına (i) kimliğini gösterir', () => {
    DATA['/reference'] = { packages: [
      { kind: 'cve_feed', state: 'ok', age_days: 3.2, stale_threshold_days: 30, generated_at: '2026-10-10T00:00:00+00:00' },
      { kind: 'kb_feed', state: 'stale', age_days: 45, stale_threshold_days: 30, generated_at: '2026-08-29T00:00:00+00:00' },
      { kind: 'upgrade_matrix', state: 'missing' },
    ] }
    wrap(<ReferencePacksCard />)
    expect(screen.getByText(/g_ref_st_ok/)).toBeTruthy()
    expect(screen.getByText(/g_ref_st_stale/)).toBeTruthy()
    expect(screen.getByText('g_ref_st_missing')).toBeTruthy()
    expect(screen.getAllByTestId('mb').map(e => e.textContent)).toEqual(['ref.pack.cve_feed', 'ref.pack.kb_feed', 'ref.pack.upgrade_matrix'])
    // yokluk ≠ temiz uyarısı
    expect(screen.getByText('g_ref_absent_note')).toBeTruthy()
  })

  it('kart: tüm paketler güncelse uyarı notu yok', () => {
    DATA['/reference'] = { packages: ['cve_feed', 'kb_feed', 'upgrade_matrix'].map(k => ({ kind: k, state: 'ok', age_days: 1, stale_threshold_days: 30 })) }
    wrap(<ReferencePacksCard />)
    expect(screen.queryByText('g_ref_absent_note')).toBeNull()
  })

  it('bulgu satırı: korunan bulgu "doğrulanamayan" rozeti + son bilinen durum notu; kaynak bağlantısı', () => {
    const f: Finding = {
      id: 1, platform: 'vmware', source_id: 1, source_name: 'vc', category: 'vuln', check_id: 'vuln:VMSA-T-1',
      entity_kind: 'host', entity_ref: 'host:h1', entity_name: 'esx1', cluster_name: null, result: 'fail', severity: 'high',
      title: 'VMSA-T-1: t', detail: 'd', evidence: { source_url: 'https://www.broadcom.com/support/vmware-security-advisories' },
      stale: true, stale_note: 'Son bilinen durum: paket v1 (2026-10-01) ile tespit edildi, şu an doğrulanamıyor',
      recommendation: null, refs: [], first_seen: null, last_seen: null, active: true, resolved_at: null,
      resolved_reason: null, has_draft: false, exception: null,
    } as any
    wrap(<FindingsTable base="virt-insights" rows={[f]} />)
    const badge = document.querySelector('[data-unverifiable]') as HTMLElement
    expect(badge.textContent).toBe('g_ref_unverifiable')
    expect(badge.getAttribute('title')).toContain('Son bilinen durum')
    fireEvent.click(screen.getByText('VMSA-T-1: t'))
    expect(screen.getByText(/Son bilinen durum/)).toBeTruthy()
    const a = screen.getByRole('link', { name: /broadcom\.com/ }) as HTMLAnchorElement
    expect(a.rel).toContain('noopener')
  })
})
