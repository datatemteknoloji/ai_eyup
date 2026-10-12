import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'

const catalog = {
  classes: [
    { id: 'veri', label_tr: 'Veri', label_en: 'Data', desc_tr: '', desc_en: '' },
    { id: 'ai', label_tr: 'AI', label_en: 'AI', desc_tr: '', desc_en: '' },
  ],
  ai_note_tr: 'AI notu', ai_note_en: 'AI note', general_knowledge_tr: '', general_knowledge_en: '',
  methods: [
    { id: 'tool:collect_ssh', cls: 'veri', area: 'tool', method_tr: 'SSH okur.', method_en: 'Reads SSH.', source_tr: 'SSH çıktısı.', source_en: 'SSH output.', limits_tr: 'Anlık.', limits_en: 'Moment.', uses_ai: false, formula_tr: '', formula_en: '' },
    { id: 'awr.parse', cls: 'veri', area: 'platform', method_tr: 'AWR ayrıştırır.', method_en: 'Parses AWR.', source_tr: 'Yüklenen rapor.', source_en: 'Uploaded report.', limits_tr: 'Canlı değil.', limits_en: 'Not live.', uses_ai: false, formula_tr: '', formula_en: '' },
    { id: 'ai.awr', cls: 'ai', area: 'ai', method_tr: 'LLM yorumlar.', method_en: 'LLM interprets.', source_tr: 'AWR değerleri.', source_en: 'AWR values.', limits_tr: 'Yorum AI.', limits_en: 'AI advice.', uses_ai: true, formula_tr: '', formula_en: '' },
    { id: 'tool:win_*', cls: 'veri', area: 'tool', method_tr: 'WinRM.', method_en: 'WinRM.', source_tr: 'WinRM.', source_en: 'WinRM.', limits_tr: '-', limits_en: '-', uses_ai: false, formula_tr: '', formula_en: '' },
  ],
}

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, any>) => (v ? `${k}:${v.tool}|${v.cls}` : k),
  useLocale: () => ({ locale: 'tr' }),
}))
vi.mock('../components/insights/MethodBadge', async (orig) => {
  const actual: any = await orig()
  return { ...actual, useMethodCatalog: () => ({ data: catalog }), MethodBadge: ({ id }: any) => <span data-testid="mb">{id}</span> }
})

import { ChatSources } from '../components/ChatEvidenceBadge'
import { methodNotesSection } from '../lib/methodNotes'

describe('T2 kaynak satırı ve yöntem notları', () => {
  it('eski sohbet akışı kaynağı (collect_ssh) yöntem sınıfıyla satır olarak görünür', () => {
    render(<MemoryRouter><ChatSources evidence={{ level: 'high', sources: [{ tool: 'collect_ssh', class: 'veri', at: '2026-10-13T10:00:00Z' }] }} /></MemoryRouter>)
    expect(screen.getByText('method_source_line:collect_ssh|Veri')).toBeTruthy()
    expect(screen.queryByText('method_general_ai')).toBeNull()
  })

  it('kaynak yoksa satır çizilmez (iddia yok)', () => {
    const { container } = render(<MemoryRouter><ChatSources evidence={{ level: 'high' }} /></MemoryRouter>)
    expect(container.querySelector('[data-testid="chat-sources"]')).toBeNull()
  })

  it('PDF yöntem notları katalogdan üretilir; AI notu yalnız AI yöntemi varsa eklenir', () => {
    const cat: any = catalog
    const sec = methodNotesSection(cat, ['awr.parse', 'ai.awr', 'yok.boyle.bir.id'], false, 'Yöntem notları')!
    expect(sec.heading).toBe('Yöntem notları')
    expect(sec.items).toHaveLength(3)                      // 2 yöntem + AI notu; kayıtsız id atlandı
    expect(sec.items[0]).toBe('Veri — AWR ayrıştırır. Kaynak: Yüklenen rapor. Sınırlar: Canlı değil.')
    expect(sec.items[2]).toBe('AI notu')
    const en = methodNotesSection(cat, ['awr.parse'], true, 'Method notes')!
    expect(en.items).toEqual(['Data — Parses AWR. Source: Uploaded report. Limits: Not live.'])
    expect(methodNotesSection(cat, ['yok'], false, 'x')).toBeNull()
    expect(methodNotesSection(undefined, ['awr.parse'], false, 'x')).toBeNull()
  })
})
