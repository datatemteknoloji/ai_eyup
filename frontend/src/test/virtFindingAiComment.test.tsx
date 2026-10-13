import { describe, it, expect, vi, beforeEach } from 'vitest'
import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import React from 'react'

vi.mock('../i18n/LocaleProvider', () => ({
  useT: () => (k: string, v?: Record<string, unknown>) => (v ? `${k}:${JSON.stringify(v)}` : k),
  useLocale: () => ({ locale: 'tr' }),
}))
vi.mock('../components/insights/MethodBadge', () => ({
  MethodBadge: () => null,
  AiBlock: ({ children, method, title }: any) => <div data-testid="ai-block" data-method={method}><span>{title}</span>{children}</div>,
}))
const apiSend = vi.fn()
let state: any = null
vi.mock('../components/insights/insightsKit', async () => ({
  apiSend: (...a: unknown[]) => apiSend(...a),
  useInsights: () => ({ data: state }),
}))

import FindingAiComment from '../components/insights/FindingAiComment'

const comment = (over: any = {}) => ({
  id: 7, version: 2, model: 'm1', generated_at: '2026-10-13T10:00:00Z', stale: false,
  confidence: { level: 'medium', reasons: ['no_sensor_type'] },
  content: { ozet: 'ÖZET', olay_gorunumu: 'OLAY', etki: 'ETKİ', oncelik: 'ÖNCELİK', gozlenen: ['g1', 'g2'], genel_bilgi: ['genel1'], bilinmeyenler: ['bilinmiyor1'] },
  feedback: { mine: null, helpful: 1, not_helpful: 0 },
  ...over,
})
const f = (o: any = {}) => ({ id: 68, category: 'hardware', result: 'fail', ...o })

describe('Bulgu AI yorumu', () => {
  beforeEach(() => { apiSend.mockReset(); state = null })

  it('Yapılandırma/Donanım dışındaki kategoride ve geçen bulguda hiçbir şey çizmez', () => {
    state = { supported: true, available: true, comment: null }
    const { container, rerender } = render(<FindingAiComment f={f({ category: 'vuln' })} />)
    expect(container.innerHTML).toBe('')
    rerender(<FindingAiComment f={f({ result: 'pass' })} />)
    expect(container.innerHTML).toBe('')
  })

  it('yorum yoksa düğme görünür; üretim YALNIZ tıklayınca başlar (yerel dil başlığıyla)', async () => {
    state = { supported: true, available: true, comment: null }
    apiSend.mockResolvedValue({ supported: true, available: true, comment: comment() })
    render(<FindingAiComment f={f({ category: 'health' })} />)
    expect(apiSend).not.toHaveBeenCalled()
    fireEvent.click(screen.getByText('vi_ai_btn'))
    await waitFor(() => expect(apiSend).toHaveBeenCalled())
    expect(apiSend).toHaveBeenCalledWith('virt-insights', '/findings/68/ai-comment', 'POST', undefined, 'tr')
    await waitFor(() => expect(screen.getByTestId('ai-comment')).toBeTruthy())
  })

  it('yorum: AI etiketi, güven + nedenler, üretim tarihi/model, bölümler; genel bilgi ayrı kutuda', () => {
    state = { supported: true, available: true, comment: comment() }
    render(<FindingAiComment f={f()} />)
    expect(screen.getByTestId('ai-block').getAttribute('data-method')).toBe('ai.finding.comment')
    expect(screen.getByText('vi_ai_label')).toBeTruthy()
    expect(screen.getByTestId('ai-conf-medium').textContent).toContain('vi_ai_conf_medium')
    expect(screen.getByTestId('ai-conf-reasons').textContent).toContain('vi_ai_cr_no_sensor_type')
    expect(screen.getByTestId('ai-generated').textContent).toContain('"model":"m1"')
    expect(screen.getByTestId('ai-sec-summary').textContent).toContain('ÖZET')
    expect(screen.getByTestId('ai-sec-observed').textContent).toContain('g2')
    expect(screen.getByTestId('ai-sec-general').textContent).toContain('genel1')
    expect(screen.getByTestId('ai-sec-observed').textContent).not.toContain('genel1')   // veri ile genel bilgi karışmaz
    expect(screen.getByTestId('ai-sec-unknown').textContent).toContain('bilinmiyor1')
    expect(screen.queryByTestId('ai-stale')).toBeNull()
  })

  it('bulgu değiştiyse uyarı + Yeniden üret', async () => {
    state = { supported: true, available: true, comment: comment({ stale: true }) }
    apiSend.mockResolvedValue({ supported: true, available: true, comment: comment({ version: 3 }) })
    render(<FindingAiComment f={f()} />)
    const stale = screen.getByTestId('ai-stale')
    expect(stale.textContent).toContain('vi_ai_stale')
    fireEvent.click(stale.querySelector('button:not([aria-label])') as HTMLElement)
    await waitFor(() => expect(apiSend).toHaveBeenCalled())
    await waitFor(() => expect(screen.queryByTestId('ai-stale')).toBeNull())
    expect(screen.getByTestId('ai-generated').textContent).toContain('"v":3')
  })

  it('geri bildirim: doğru gövde gider, sayaçlar ve seçili durum güncellenir', async () => {
    state = { supported: true, available: true, comment: comment() }
    apiSend.mockResolvedValue({ ok: true, mine: false, helpful: 1, not_helpful: 1 })
    render(<FindingAiComment f={f()} />)
    fireEvent.click(screen.getByTestId('ai-fb-no'))
    await waitFor(() => expect(apiSend).toHaveBeenCalledWith('virt-insights', '/findings/68/ai-comment/feedback', 'POST', { comment_id: 7, helpful: false }))
    await waitFor(() => expect(screen.getByTestId('ai-fb-no').getAttribute('aria-pressed')).toBe('true'))
    expect(screen.getByTestId('ai-fb-counts').textContent).toContain('"down":1')
  })

  it('tablolar yoksa üretim düğmesi yok, açıklama var', () => {
    state = { supported: true, available: false, reason: 'tables_missing', comment: null }
    render(<FindingAiComment f={f()} />)
    expect(screen.getByTestId('ai-unavailable').textContent).toBe('vi_ai_tables_missing')
    expect(screen.queryByText('vi_ai_btn')).toBeNull()
  })

  it('doğrulama/servis hatası (Türkçe mesaj) gösterilir, yorum çizilmez', async () => {
    state = { supported: true, available: true, comment: null }
    apiSend.mockRejectedValue(new Error('AI yorumu kalite kurallarını geçemedi; gösterilmedi.'))
    render(<FindingAiComment f={f()} />)
    fireEvent.click(screen.getByText('vi_ai_btn'))
    await waitFor(() => expect(screen.getByTestId('ai-error').textContent).toContain('geçemedi'))
    expect(screen.queryByTestId('ai-comment')).toBeNull()
  })

  it('(i) ipuçları: güven ve genel bilgi', () => {
    state = { supported: true, available: true, comment: comment() }
    render(<FindingAiComment f={f()} />)
    expect(screen.getAllByLabelText('info_btn').length).toBeGreaterThanOrEqual(2)
  })

  it('diğer iyileştirmeler ayrı kutuda ve (i) ile; olay üye sayısı notu birden çok üyede görünür', () => {
    state = { supported: true, available: true, comment: comment({
      content: { ozet: 'Ö', olay_gorunumu: 'O', etki: 'E', oncelik: 'P', gozlenen: ['g'], genel_bilgi: [], diger_iyilestirmeler: ['NTP — bu olayla doğrudan ilişkili değil'], bilinmeyenler: [] },
      event: { key: 'k', family: 'hardware', member_count: 3, member_ids: [68, 70, 190], representative_id: 68 },
    }) }
    render(<FindingAiComment f={f()} />)
    const other = screen.getByTestId('ai-sec-other')
    expect(other.textContent).toContain('vi_ai_sec_other')
    expect(other.textContent).toContain('bu olayla doğrudan ilişkili değil')
    expect(other.querySelector('button[aria-label="info_btn"]')).toBeTruthy()
    expect(screen.getByTestId('ai-event-note').textContent).toContain('"n":3')
  })

  it('diğer iyileştirme yoksa kutu yok; tek üyeli olayda not yok (eski kayıtlarla uyumlu)', () => {
    state = { supported: true, available: true, comment: comment({ event: { key: 'k', family: 'x', member_count: 1, member_ids: [68], representative_id: 68 } }) }
    render(<FindingAiComment f={f()} />)
    expect(screen.queryByTestId('ai-sec-other')).toBeNull()
    expect(screen.queryByTestId('ai-event-note')).toBeNull()
  })
})
