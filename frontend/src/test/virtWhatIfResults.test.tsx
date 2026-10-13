import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import React, { useState } from 'react'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, unknown>) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr' }),
}))
vi.mock('../components/insights/MethodBadge', () => ({ MethodBadge: () => null }))

import WhatIfResults, { placedHosts } from '../components/insights/WhatIfResults'
import { PlatformChips } from '../pages/VirtCapacity'

const base = { hypervisor_id: 1, hypervisor: 'vc01' }
const results = [
  { ...base, cluster: 'PROD', path: 'vc01 / DC / PROD', fits: true, status: 'ok', max_fit: 7, limiting: [], warn_codes: [],
    placement: { placed: [{ host: 'esx01' }, { host: 'esx01' }, { host: 'esx02' }], host_free: [{ host: 'esx01', free_gb: 40 }], notes: ['n1'] },
    before: { memory_effective_pct: 50 }, after: { memory_effective_pct: 60 }, reasons: [] },
  { ...base, cluster: 'DR', path: 'vc01 / DC / DR', fits: true, status: 'warn', max_fit: 3, limiting: [], warn_codes: ['cpu'], placement: { placed: [{ host: 'esx09' }] }, reasons: [] },
  { ...base, cluster: 'TEST', path: 'vc01 / DC / TEST', fits: false, status: 'fail', max_fit: 0, limiting: ['memory', 'ha'], warn_codes: ['ha'], placement: { placed: [] }, reasons: ['Effective Memory %91 > %85'] },
  { hypervisor_id: 1, hypervisor: 'vc01', cluster: '(cluster yok) · sa1', standalone: true, path: 'vc01 / ? / (cluster yok) · sa1', fits: false, status: 'fail', max_fit: null, limiting: ['fragmentation'], warn_codes: [] },
]

describe('What-if sonuç tablosu', () => {
  it('sonuç hücresi: ✅ N adet / ⚠️ / ❌ + sığmazsa "en fazla"', () => {
    render(<WhatIfResults results={results} count={2} />)
    const rows = screen.getAllByTestId('wi-row')
    expect(rows).toHaveLength(4)
    expect(rows[0].textContent).toContain('✅')
    expect(rows[0].textContent).toContain('vi_wi_n:{"n":7}')
    expect(rows[1].textContent).toContain('⚠️')
    expect(rows[2].textContent).toContain('❌')
    expect(rows[2].textContent).toContain('vi_wi_max:{"n":0}')
  })

  it('sınırlayan: tek kelimelik kod çipleri; engelleyici olan uyarı olarak tekrarlanmaz', () => {
    render(<WhatIfResults results={results} count={2} />)
    const rows = screen.getAllByTestId('wi-row')
    expect(rows[2].querySelectorAll('[data-testid="lim-memory"]')).toHaveLength(1)
    expect(rows[2].querySelectorAll('[data-testid="lim-ha"]')).toHaveLength(1)   // hem limiting hem warn_codes'ta
    expect(rows[1].querySelector('[data-testid="lim-cpu"]')?.className).toContain('amber')
    expect(rows[3].querySelector('[data-testid="lim-fragmentation"]')).not.toBeNull()
  })

  it('uygun host listesi benzersiz ve adetli', () => {
    expect(placedHosts(results[0])).toEqual([{ host: 'esx01', n: 2 }, { host: 'esx02', n: 1 }])
    render(<WhatIfResults results={results} count={2} />)
    expect(screen.getAllByTestId('wi-row')[0].textContent).toContain('esx01 ×2, esx02')
  })

  it('bağımsız host etiketi ve max_fit=null durumunda "en fazla" yazılmaz', () => {
    render(<WhatIfResults results={results} count={2} />)
    const r = screen.getAllByTestId('wi-row')[3]
    expect(r.textContent).toContain('vi_wi_standalone')
    expect(r.textContent).not.toContain('vi_wi_max')
  })

  it('filtre çipleri sayıları gösterir ve satırları süzer', () => {
    render(<WhatIfResults results={results} count={2} />)
    expect(screen.getByTestId('wi-filter-fit').textContent).toContain('2')
    fireEvent.click(screen.getByTestId('wi-filter-nofit'))
    expect(screen.getAllByTestId('wi-row')).toHaveLength(2)
    fireEvent.click(screen.getByTestId('wi-filter-fit'))
    expect(screen.getAllByTestId('wi-row')).toHaveLength(2)
  })

  it('satıra tıklayınca ayrıntı açılır (host başına boş Memory, gerekçe, not)', () => {
    render(<WhatIfResults results={results} count={2} />)
    fireEvent.click(screen.getAllByTestId('wi-row')[0])
    expect(screen.getByText('esx01: 40 GB')).toBeTruthy()
    expect(screen.getByText('• n1')).toBeTruthy()
  })
})

describe('Platform çipleri', () => {
  const clusters = [{ platform: 'vmware' }, { platform: 'olvm' }, { platform: 'vmware' }]
  function H({ onV }: { onV: (v: string[]) => void }) {
    const [v, setV] = useState<string[]>([])
    onV(v)
    return <PlatformChips clusters={clusters} value={v} onChange={setV} />
  }
  it('yalnız mevcut platformlar listelenir ve çoklu seçilir', () => {
    let last: string[] = []
    render(<H onV={v => { last = v }} />)
    expect(screen.queryByTestId('platform-ocp_virt')).toBeNull()
    fireEvent.click(screen.getByTestId('platform-olvm'))
    expect(last).toEqual(['olvm'])
    fireEvent.click(screen.getByTestId('platform-vmware'))
    expect(last).toEqual(['olvm', 'vmware'])
    fireEvent.click(screen.getByTestId('platform-olvm'))
    expect(last).toEqual(['vmware'])
  })
  it('tek platform varsa hiç gösterilmez', () => {
    const { container } = render(<PlatformChips clusters={[{ platform: 'vmware' }]} value={[]} onChange={() => {}} />)
    expect(container.firstChild).toBeNull()
  })
})
