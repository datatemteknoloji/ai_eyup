import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import React, { useState } from 'react'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, unknown>) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr' }),
}))
vi.mock('../components/insights/MethodBadge', () => ({ MethodBadge: () => null }))

import { CollapsibleScope, EMPTY_SCOPE, ScopeSelect, scopeSummaryParts, type Scope } from '../pages/VirtCapacity'

const clusters = [
  { hypervisor_id: 1, hypervisor: 'vc01', datacenter: 'DC-IST', cluster: 'PROD', host_names: ['esx01', 'esx02'] },
  { hypervisor_id: 1, hypervisor: 'vc01', datacenter: 'DC-IST', cluster: 'DR', host_names: ['esx09'] },
  { hypervisor_id: 2, hypervisor: 'vc02', datacenter: 'DC-X', cluster: 'PROD', host_names: ['esx01'] },
]

function Harness({ onScope }: { onScope?: (s: Scope) => void }) {
  const [s, setS] = useState<Scope>(EMPTY_SCOPE)
  onScope?.(s)
  return <CollapsibleScope clusters={clusters} value={s} onChange={setS} />
}

function pick(testId: string, values: string[]) {
  const sel = screen.getByTestId(testId) as HTMLSelectElement
  Array.from(sel.options).forEach(o => { o.selected = values.includes(o.value) })
  fireEvent.change(sel)
}

describe('Kapsam seçici daraltma (What-if / Toplu yerleşim)', () => {
  it('varsayılan KAPALI: başlıkta "Kapsam: tüm ortamlar" özeti var, seçiciler çizilmez', () => {
    render(<Harness />)
    expect(screen.getByTestId('scope-summary').textContent).toBe('vi_scope_label: vi_scope_sum_all')
    expect(screen.getByTestId('scope-toggle').getAttribute('aria-expanded')).toBe('false')
    expect(screen.getByTestId('scope-toggle').textContent).toContain('vi_scope_expand')
    expect(screen.queryByTestId('scope-body')).toBeNull()
    expect(screen.queryByTestId('scope-instance')).toBeNull()
  })

  it('açılınca ScopeSelect çizilir ve host seçiminin yalnız aday host\'ları daralttığını söyleyen (i) bulunur', () => {
    render(<Harness />)
    fireEvent.click(screen.getByTestId('scope-toggle'))
    expect(screen.getByTestId('scope-toggle').getAttribute('aria-expanded')).toBe('true')
    expect(screen.getByTestId('scope-toggle').textContent).toContain('vi_scope_collapse')
    for (const id of ['scope-instance', 'scope-dc', 'scope-clusters', 'scope-hosts']) expect(screen.getByTestId(id)).toBeTruthy()
    const note = screen.getByTestId('scope-host-note')
    expect(note.textContent).toContain('vi_scope_host_note')
    expect(note.querySelector('button[aria-label="info_btn"]')).toBeTruthy()
  })

  it('seçim varken başlıkta özet ("2 cluster seçili"); daraltmak seçimi silmez', () => {
    let last: Scope = EMPTY_SCOPE
    render(<Harness onScope={s => { last = s }} />)
    fireEvent.click(screen.getByTestId('scope-toggle'))
    pick('scope-clusters', ['PROD', 'DR'])
    expect(last.clusters.sort()).toEqual(['DR', 'PROD'])
    fireEvent.click(screen.getByTestId('scope-toggle'))                       // daralt
    expect(screen.queryByTestId('scope-body')).toBeNull()
    expect(screen.getByTestId('scope-summary').textContent).toContain('vi_scope_n_clusters:{"n":2}')
    expect(last.clusters).toHaveLength(2)                                     // gönderilecek kapsam korunur
    fireEvent.click(screen.getByTestId('scope-toggle'))                       // yeniden aç: seçim duruyor
    const opts = Array.from((screen.getByTestId('scope-clusters') as HTMLSelectElement).selectedOptions).map(o => o.value).sort()
    expect(opts).toEqual(['DR', 'PROD'])
  })

  it('özet parçaları: instance adı, datacenter, cluster ve host sayıları', () => {
    const t = (k: string, v?: any) => (v ? `${k}:${v.n}` : k)
    expect(scopeSummaryParts(clusters, EMPTY_SCOPE, t)).toEqual([])
    expect(scopeSummaryParts(clusters, { instance: '1', datacenter: 'DC-IST', clusters: ['PROD'], hosts: ['esx01', 'esx02'] }, t))
      .toEqual(['vc01', 'DC-IST', 'vi_scope_n_clusters:1', 'vi_scope_n_hosts:2'])
  })

  it('ScopeSelect tek başına hâlâ eskisi gibi çalışır (geriye uyumlu)', () => {
    render(<ScopeSelect clusters={clusters} value={EMPTY_SCOPE} onChange={() => {}} />)
    expect(screen.getByTestId('scope-instance')).toBeTruthy()
  })
})
