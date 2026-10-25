import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../components/insights/MethodBadge', () => ({
  AiBlock: ({ children, title }: { children: React.ReactNode; title?: string }) => <div data-ai-block><span>{title}</span>{children}</div>,
  MethodBadge: () => null,
}))

import { ExecutiveReportView } from '../pages/ExecutiveReports'

const bundle = {
  status: 'ready' as const,
  generated_at: '2026-10-25T13:00:00+00:00',
  refreshing: false,
  period: { start: '2026-10-01', end: '2026-11-01' },
  summary: 'Kapalı durumdaki 29 VM toplam 126 vCPU ayırıyor.',
  summary_source: 'template',
  demo_cards: [
    { title: 'Yedek kapsamı', demo: false, status: 'Ölçülemedi', lines: [] },
  ],
  view: {
    summary: { text: 'Kapalı durumdaki 29 VM toplam 126 vCPU ayırıyor.', source: 'template' },
    kpis: [
      { label: 'Kritik durumdaki alan', value: '1 / 3 alan', hint: '' },
      { label: 'En yakın kapasite eşiği', value: '—', hint: 'geçmiş veri yetersiz' },
      { label: 'Geri kazanılabilir kaynak', value: '126 vCPU', hint: '' },
      { label: '30 günden uzun açık kritik sorun', value: '0', hint: '' },
    ],
    areas: [
      {
        name: 'OpenShift', status: 'Dikkat', score: 70, reason: 'Bu not küme olaylarından hesaplanıyor.',
        metrics: [{ label: 'Küme', value: '1' }, { label: 'Node', value: '3' }, { label: 'Açık kritik uyarı', value: '—' }],
        series: [], formula: 'Alanda en az bir varlıkta açık kritik varsa alan en az Dikkat olur.', change: 'ilk ay',
      },
    ],
    capacity: [],
    investment: { value: '0', sentence: 'Önümüzdeki 12 ay için ek sunucu ihtiyacı görünmüyor.' },
    risks: [],
    risk_rule: 'Sıra şiddet, yaş ve etkidir.',
    events: [],
    coverage: { measured: 2, total: 12, rows: [] },
    openshift_note: 'Bu not küme olaylarından hesaplanıyor.',
    formula: 'Alan notu ortalamadır.',
  },
}

describe('yönetici raporu', () => {
  it('başka modül sayfasına gitmez ve anahtar adı basmaz', () => {
    const { container } = render(<ExecutiveReportView bundle={bundle} />)
    const html = container.innerHTML
    expect(html).not.toMatch(/href="\/(infra-reports|linux\/reports|windows\/reports|exadata\/reports|custom-reports)/)
    expect(container.textContent || '').not.toMatch(/\b[a-z]+_[a-z0-9_]+\b/)
    expect(screen.getByText('Yönetici Raporu')).toBeTruthy()
    expect(screen.getByText('Dikkat')).toBeTruthy()
    expect(screen.getByText('Ölçülemedi')).toBeTruthy()
  })
})
