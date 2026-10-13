import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'

const catalog = {
  classes: [
    { id: 'hesap', label_tr: 'Hesap', label_en: 'Calculation', desc_tr: '', desc_en: '' },
    { id: 'ai', label_tr: 'AI', label_en: 'AI', desc_tr: '', desc_en: '' },
  ],
  ai_note_tr: 'AI notu', ai_note_en: 'AI note', general_knowledge_tr: '', general_knowledge_en: '',
  methods: [
    { id: 'tool:virt_capacity_simulate', cls: 'hesap', area: 'tool', method_tr: 'Simüle eder.', method_en: 'Simulates.', source_tr: 'Envanter.', source_en: 'Inventory.', limits_tr: 'Anlık.', limits_en: 'Moment.', uses_ai: false, formula_tr: '', formula_en: '' },
    { id: 'ai.chat', cls: 'ai', area: 'ai', method_tr: 'LLM yazar.', method_en: 'LLM writes.', source_tr: 'Araç sonuçları.', source_en: 'Tool results.', limits_tr: 'Sayı üretmez.', limits_en: 'No numbers.', uses_ai: true, formula_tr: '', formula_en: '' },
  ],
}

const exportMock = vi.fn()
vi.mock('../utils/pdfExport', () => ({ exportChatMessagesToPrintWindow: (...a: any[]) => exportMock(...a) }))
vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string) => k,
  useLocale: () => ({ locale: 'tr' }),
}))
vi.mock('./../components/insights/MethodBadge', async (orig) => {
  const actual: any = await orig()
  return { ...actual, useMethodCatalog: () => ({ data: catalog }) }
})

import { ChatPdfToolbar } from '../components/ChatPdfToolbar'
import { chatMethodIds } from '../lib/methodNotes'

const msgs: any[] = [
  { id: 1, role: 'user', content: 'sığar mı?' },
  { id: 2, role: 'assistant', content: 'Sığar.', evidence: { sources: [{ tool: 'virt_capacity_simulate' }, { tool: 'kayitsiz_arac' }] } },
]
const select: any = { selectMode: false, selectedCount: 0, enter: vi.fn(), exit: vi.fn(), selectAll: vi.fn(), exportSelected: vi.fn() }

describe('E9 — sohbet PDF yöntem notları', () => {
  beforeEach(() => exportMock.mockClear())

  it('yöntem kimlikleri: kullanılan araçlar + ai.chat; kullanıcı mesajı katkı vermez', () => {
    expect(chatMethodIds(msgs)).toEqual(['tool:virt_capacity_simulate', 'tool:kayitsiz_arac', 'ai.chat'])
    expect(chatMethodIds([msgs[0]])).toEqual([])
  })

  it('"Sohbeti PDF" yöntem notları geri çağrısını verir; notlar registry metninden, kayıtsız araç atlanır', () => {
    render(<ChatPdfToolbar pairs={[{ id: 'p', messages: msgs }]} select={select} fullExport={{ title: 'T' }} />)
    fireEvent.click(screen.getByText('chat_pdf_chat'))
    expect(exportMock).toHaveBeenCalledTimes(1)
    const opts = exportMock.mock.calls[0][1]
    const sec = opts.methodNotes(msgs)
    expect(sec.heading).toBe('method_notes_heading')
    expect(sec.items).toEqual([
      'Hesap — Simüle eder. Kaynak: Envanter. Sınırlar: Anlık.',
      'AI — LLM yazar. Kaynak: Araç sonuçları. Sınırlar: Sayı üretmez.',
      'AI notu',
    ])
    // yalnız kullanıcı mesajı varsa not yok
    expect(opts.methodNotes([msgs[0]])).toBeNull()
  })
})
