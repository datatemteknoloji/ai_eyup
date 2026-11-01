import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('../components/insights/MethodBadge', () => ({
  AiBlock: ({ children, title }: { children: React.ReactNode; title?: string }) => <div data-ai-block><span>{title}</span>{children}</div>,
  MethodBadge: () => null,
}))

vi.mock('../i18n/LocaleProvider', () => ({ useT: () => (k: string) => k }))

import { ExecutiveReportView } from '../pages/ExecutiveReports'

class ResizeObserverStub {
  observe() {}
  unobserve() {}
  disconnect() {}
}
;(globalThis as unknown as { ResizeObserver: unknown }).ResizeObserver = ResizeObserverStub

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
        issues: [{ problem: 'Küme olayı açık', action: 'Node üzerindeki olayı giderin.' }],
      },
    ],
    landscape: {
      physical: '2',
      virtual: '10',
      platforms: [{ name: 'VMware', environments: 1, clusters: 1, hosts: 2, vms: 10 }],
      environments: [{
        name: 'office', kind: 'VMware', clusters: 1, hosts: 2, vms: 10, cpu: 40, memory: 55, storage: 91, storage_name: 'NVME',
        problem: '', action: '', status: 'Normal',
        tree: [{ name: 'Kümesiz', environment: 'office', kind: 'VMware', hosts: 2, vms: 10, cpu: 40, memory: 55, host_list: [
          { name: 'ESXi host (192.168.1.101)', cpu: 40, memory: 88, problem: true },
          { name: 'esx02', cpu: 20, memory: 30, problem: false },
        ] }],
      }],
      clusters: [{ name: 'office', environment: 'office', kind: 'VMware', hosts: 2, vms: 10, cpu: 40, memory: 55 }],
      datastores: [{ name: 'NVME', environment: 'office', usage: 91, usageLabel: '%91', free: '1 TB' }],
      hosts: [{ host: 'esx01', problem: 'Sensör uyarıda', action: 'Sensörü kontrol edin.', cluster: 'office', environment: 'office', kind: 'VMware', hardware: true }],
      reclaim: [],
    },
    attention: [
      { title: 'ESXi host (192.168.1.101)', problem: 'Sensör uyarıda', action: 'Sensörü kontrol edin.', environment: 'office', kind: 'VMware', cluster: 'Kümesiz', hardware: true, extra: 2, age_days: 9, area: '' },
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
    expect(screen.getByText('Yönetici Özeti')).toBeTruthy()
    expect(screen.getByText('Dikkat')).toBeTruthy()
    expect(screen.getAllByText('office').length).toBeGreaterThan(0)
    expect(screen.getByText('Olası çözüm: Node üzerindeki olayı giderin.')).toBeTruthy()
    expect(screen.queryByText('Yedek kapsamı')).toBeNull()
    expect(screen.queryByText('Donanım ve garanti')).toBeNull()
  })

  it('ortam ağacı kapalı gelir, açılınca IP host «ESXi host (IP)» olarak görünür', () => {
    render(<ExecutiveReportView bundle={bundle} />)
    expect(screen.queryByTestId('env-tree')).toBeNull()
    fireEvent.click(screen.getByText('Küme ve hostları göster'))
    expect(screen.getByTestId('env-tree').textContent).toContain('ESXi host (192.168.1.101)')
    expect(screen.getByTestId('env-tree').textContent).toContain('Kümesiz')
  })

  it('dikkat listesi varlık başına tek satır; ayrı risk/host tablosu yok', () => {
    render(<ExecutiveReportView bundle={bundle} />)
    expect(screen.getByText('Dikkat gerektirenler')).toBeTruthy()
    expect(screen.getByText(/\+2 bulgu daha/)).toBeTruthy()
    expect(screen.queryByText('Öncelikli riskler')).toBeNull()
    expect(screen.queryByText('Host sorunları')).toBeNull()
  })

  it('veri yaşı gösterilir; şablon özet «AI» etiketi taşımaz', () => {
    render(<ExecutiveReportView bundle={bundle} />)
    expect(screen.getByTestId('veri-yasi').textContent).toContain('Veri yaşı')
    expect(screen.getByText('Bu özet kurallarla otomatik yazıldı.')).toBeTruthy()
  })

  it('dikkat satırı çekmeceyi açar; boşluğa tıklayınca ve Esc ile kapanır', () => {
    render(<ExecutiveReportView bundle={bundle} />)
    fireEvent.click(screen.getByText('Sensör uyarıda'))
    expect(screen.getByRole('dialog')).toBeTruthy()
    fireEvent.click(screen.getByTestId('drawer-backdrop'))
    expect(screen.queryByRole('dialog')).toBeNull()
    fireEvent.click(screen.getByText('Sensör uyarıda'))
    fireEvent.keyDown(window, { key: 'Escape' })
    expect(screen.queryByRole('dialog')).toBeNull()
  })
})
