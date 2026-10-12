import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import React, { useState } from 'react'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string) => k,
  useLocale: () => ({ locale: 'tr' }),
}))
vi.mock('../components/insights/MethodBadge', () => ({ MethodBadge: () => null }))

import { EMPTY_SCOPE, ScopeSelect, type Scope } from '../pages/VirtCapacity'

const clusters = [
  { hypervisor_id: 1, hypervisor: 'vc01', datacenter: 'DC-IST', cluster: 'PROD', host_names: ['esx01', 'esx02'] },
  { hypervisor_id: 1, hypervisor: 'vc01', datacenter: 'DC-ANK', cluster: 'DR', host_names: ['esx09'] },
  { hypervisor_id: 2, hypervisor: 'vc02', datacenter: 'DC-X', cluster: 'PROD', host_names: ['esx01'] },  // aynı ad, başka instance
]

function Harness({ onScope }: { onScope: (s: Scope) => void }) {
  const [s, setS] = useState<Scope>(EMPTY_SCOPE)
  onScope(s)
  return <ScopeSelect clusters={clusters} value={s} onChange={setS} />
}

describe('H.0 kapsam seçici', () => {
  it('instance seçimi datacenter/cluster/host seçeneklerini daraltır; aynı adlı cluster karışmaz', () => {
    let last: Scope = EMPTY_SCOPE
    render(<Harness onScope={s => { last = s }} />)
    const opts = (id: string) => Array.from((screen.getByTestId(id) as HTMLSelectElement).options).map(o => o.value)
    expect(opts('scope-dc')).toEqual(['', 'DC-IST', 'DC-ANK', 'DC-X'])
    fireEvent.change(screen.getByTestId('scope-instance'), { target: { value: '2' } })
    expect(last.instance).toBe('2')
    expect(opts('scope-dc')).toEqual(['', 'DC-X'])
    expect(opts('scope-clusters')).toEqual(['PROD'])
    expect(opts('scope-hosts')).toEqual(['esx01'])            // yalnız vc02'nin host'u
  })

  it('datacenter seçimi cluster ve host listesini sınırlar; üst seviye değişince alt seçimler sıfırlanır', () => {
    let last: Scope = EMPTY_SCOPE
    render(<Harness onScope={s => { last = s }} />)
    fireEvent.change(screen.getByTestId('scope-instance'), { target: { value: '1' } })
    fireEvent.change(screen.getByTestId('scope-dc'), { target: { value: 'DC-ANK' } })
    const opts = (id: string) => Array.from((screen.getByTestId(id) as HTMLSelectElement).options).map(o => o.value)
    expect(opts('scope-clusters')).toEqual(['DR'])
    expect(opts('scope-hosts')).toEqual(['esx09'])
    fireEvent.change(screen.getByTestId('scope-instance'), { target: { value: '' } })
    expect(last).toEqual(EMPTY_SCOPE)
  })
})
