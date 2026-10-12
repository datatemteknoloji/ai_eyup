import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent, within } from '@testing-library/react'

const mk = (id: string, cls: string, method: string, ai = false) => ({
  id, cls, area: 'capacity', method_tr: method, method_en: method, source_tr: 's-' + method, source_en: 's-' + method,
  limits_tr: '', limits_en: '', uses_ai: ai, formula_tr: '', formula_en: '',
})
const catalog = {
  classes: [
    { id: 'veri', label_tr: 'Veri', label_en: 'Data', desc_tr: '', desc_en: '' },
    { id: 'hesap', label_tr: 'Hesap', label_en: 'Calc', desc_tr: '', desc_en: '' },
  ],
  ai_note_tr: '', ai_note_en: '',
  methods: [mk('b.two', 'hesap', 'Charlie'), mk('a.one', 'veri', 'Alpha'), mk('c.three', 'hesap', 'Bravo', true)],
}
vi.mock('../components/insights/MethodBadge', () => ({
  CLASS_STYLE: { veri: '', hesap: '' },
  useMethodCatalog: () => ({ data: catalog, isLoading: false, error: null }),
}))
vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string) => k,
  useLocale: () => ({ locale: 'tr' }),
}))

import MethodsPage from '../pages/MethodsPage'

const order = () => Array.from(document.querySelectorAll('[data-method-row]')).map(e => e.getAttribute('data-method-row'))

describe('MethodsPage column sorting', () => {
  it('sorts asc → desc → default per column', () => {
    render(<MethodsPage />)
    expect(order()).toEqual(['b.two', 'a.one', 'c.three'])
    const btn = document.querySelector('[data-sort-col="id"]') as HTMLElement
    fireEvent.click(btn)
    expect(order()).toEqual(['a.one', 'b.two', 'c.three'])
    fireEvent.click(btn)
    expect(order()).toEqual(['c.three', 'b.two', 'a.one'])
    fireEvent.click(btn)
    expect(order()).toEqual(['b.two', 'a.one', 'c.three'])
  })

  it('sorts by method text and class', () => {
    render(<MethodsPage />)
    fireEvent.click(document.querySelector('[data-sort-col="method"]') as HTMLElement)
    expect(order()).toEqual(['a.one', 'c.three', 'b.two'])
    fireEvent.click(document.querySelector('[data-sort-col="cls"]') as HTMLElement)
    expect(order()[0]).toBe('b.two')   // Hesap < Veri
    expect(within(document.body).getAllByRole('columnheader').some(h => h.getAttribute('aria-sort') === 'ascending')).toBe(true)
  })
})
