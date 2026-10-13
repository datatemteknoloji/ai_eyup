import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import React from 'react'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, unknown>) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr' }),
}))
vi.mock('../components/aiops/ui', () => ({ SeverityBadge: ({ severity }: { severity: string }) => <b>{severity}</b> }))

import FindingContext from '../components/insights/FindingContext'

const guide = { guides: [{ key: 'power', title: 'Güç', cause: 'c', impact: 'i', steps: ['s1', 's2'] }], vendor: 'HP', official_links: [] }
const rel = [{ id: 5, check_id: 'hw.host.overall_status', category: 'hardware', severity: 'critical', title: 'Genel durum', detail: 'red' },
             { id: 9, check_id: 'vmw.host.ntp', category: 'health', severity: 'low', title: 'NTP', detail: null }]

describe('Bulgu bağlamı', () => {
  it('etki, ilişkili bulgular ve rehber gösterilir; doğrulanmış bağlantı yoksa neden yazılır', () => {
    render(<FindingContext ctx={{ guide, related: rel, impact: { available: true, verdict: 'fail', vms: 3, memory_gb: 90, remaining_hosts: 0, after_memory_pct: null, threshold_pct: 85 } }} />)
    expect(screen.getByTestId('fc-impact').textContent).toContain('vi_hf_verdict_fail')
    expect(screen.getByTestId('fc-related').textContent).toContain('Genel durum')
    expect(screen.getByTestId('fc-guide-power').querySelectorAll('li')).toHaveLength(2)
    expect(screen.getByTestId('fc-no-links').textContent).toContain('HP')
    expect(screen.getByTestId('fc-guide').querySelectorAll('a')).toHaveLength(0)
  })

  it('ilişkili bulgu yalnız listede varsa tıklanabilir', () => {
    const open = vi.fn()
    render(<FindingContext ctx={{ related: rel }} onOpenFinding={open} openable={new Set([5])} />)
    const rows = screen.getByTestId('fc-related')
    expect(rows.querySelectorAll('button')).toHaveLength(1)
    fireEvent.click(rows.querySelector('button')!)
    expect(open).toHaveBeenCalledWith(5)
  })

  it('içerik yoksa hiçbir şey çizilmez; hesaplanamayan etki nedenini gösterir', () => {
    const { container, rerender } = render(<FindingContext ctx={{ impact: null, related: [], guide: null }} />)
    expect(container.firstChild).toBeNull()
    rerender(<FindingContext ctx={{ impact: { available: false, reason: 'Cluster bulunamadı' } }} />)
    expect(screen.getByTestId('fc-impact-na').textContent).toContain('Cluster bulunamadı')
  })

  it('(a) aynı olay ve (b) diğer bulgular AYRI gruplanır; (b) "bu olayla doğrudan ilişkili değil" başlığıyla', () => {
    render(<FindingContext ctx={{ related: rel, related_event: [rel[0]], related_other: [rel[1]] }} />)
    expect(screen.getByTestId('fc-related-event').textContent).toContain('Genel durum')
    expect(screen.getByTestId('fc-related-event').textContent).not.toContain('NTP')
    expect(screen.getByTestId('fc-related-other').textContent).toContain('NTP')
    expect(screen.getByTestId('fc-related-other').textContent).toContain('vi_fc_related_other')
    expect(screen.queryByTestId('fc-related')).toBeNull()
    expect(screen.getByTestId('fc-related-other').querySelector('button[aria-label="info_btn"]')).toBeTruthy()
  })

  it('yalnız (b) varsa olay grubu çizilmez', () => {
    render(<FindingContext ctx={{ related_event: [], related_other: [rel[1]] }} />)
    expect(screen.queryByTestId('fc-related-event')).toBeNull()
    expect(screen.getByTestId('fc-related-other')).toBeTruthy()
  })
})
