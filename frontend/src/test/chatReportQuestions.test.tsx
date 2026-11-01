import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { NlEmptyState } from '../components/nlChatUi'
import { chatReportQuestions } from '../config/chatReportQuestions'
import { dictionaries } from '../i18n/messages'

describe('chat «Rapor soruları» chips', () => {
  it('TR ve EN listeleri aynı uzunlukta ve benzersiz', () => {
    for (const scope of ['openshift', 'executive'] as const) {
      const tr = chatReportQuestions(scope, 'tr')
      const en = chatReportQuestions(scope, 'en')
      expect(tr.length).toBe(en.length)
      expect(new Set(tr).size).toBe(tr.length)
      expect(new Set(en).size).toBe(en.length)
    }
    expect(chatReportQuestions('openshift', 'tr')).toHaveLength(12)
    expect(chatReportQuestions('executive', 'tr')).toHaveLength(11)
  })

  it('OpenShift listesi MTV, Yönetici listesi tüm ortam ifadeleri içerir', () => {
    expect(chatReportQuestions('openshift', 'tr').some((q) => q.includes('MTV'))).toBe(true)
    expect(chatReportQuestions('executive', 'tr').some((q) => q.startsWith('Tüm ortamlar'))).toBe(true)
  })

  it('NlEmptyState: rapor chip\'leri örnek sorulardan önce gösterilir ve tıklanınca gönderilir', () => {
    const onSelect = vi.fn()
    render(
      <NlEmptyState
        icon={<span />}
        description="d"
        reportSuggestions={['Kapasite raporu göster', 'Risk dashboard raporu ver']}
        suggestions={['Kaç node var?']}
        reportTitle="Rapor soruları"
        sampleTitle="Örnek sorular"
        onSelectSuggestion={onSelect}
      />,
    )
    const box = screen.getByTestId('nl-report-questions')
    expect(within(box).getByText('Rapor soruları')).toBeTruthy()
    fireEvent.click(within(box).getByText('Kapasite raporu göster'))
    expect(onSelect).toHaveBeenCalledWith('Kapasite raporu göster')
    expect(screen.getByText('Örnek sorular')).toBeTruthy()
    // sıralama: rapor bölümü örnek bölümünden önce
    const html = document.body.innerHTML
    expect(html.indexOf('Rapor soruları')).toBeLessThan(html.indexOf('Örnek sorular'))
  })

  it('NlEmptyState: rapor chip\'i yoksa bölüm çizilmez (diğer sohbetler değişmez)', () => {
    render(<NlEmptyState icon={<span />} description="d" suggestions={['x']} onSelectSuggestion={() => {}} />)
    expect(screen.queryByTestId('nl-report-questions')).toBeNull()
  })

  it('Doğal Dil Asistanı adı TR ve EN sözlükte', () => {
    expect(dictionaries.tr.nav_unified_chat).toBe('Doğal Dil Asistanı')
    expect(dictionaries.en.nav_unified_chat).toBe('Natural Language Assistant')
    expect(dictionaries.tr.mon_arch_uni).toContain('Doğal Dil Asistanı')
    expect(JSON.stringify(dictionaries.tr)).not.toContain('Tüm Altyapı Analizi')
  })
})
