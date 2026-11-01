import { describe, it, expect, vi, afterEach } from 'vitest'
import { startChatStream, getChatStream, appendThinking, THINKING_MAX_CHARS } from '../lib/chatStreamStore'

const enc = new TextEncoder()
const sse = (o: unknown) => enc.encode('data: ' + JSON.stringify(o) + '\n\n')

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('chatStreamStore — Adım 14 düşünme akışı', () => {
  it('appendThinking son THINKING_MAX_CHARS karakteri tutar', () => {
    const big = 'x'.repeat(THINKING_MAX_CHARS + 500)
    expect(appendThinking('', big).length).toBe(THINKING_MAX_CHARS)
    expect(appendThinking('ab', 'cd')).toBe('abcd')
    expect(appendThinking(big, 'Z').endsWith('Z')).toBe(true)
  })

  it('thinking olayları cevap metnine karışmaz; yeni akış ve bitiş temizler', async () => {
    let ctrl!: ReadableStreamDefaultController<Uint8Array>
    const body = new ReadableStream<Uint8Array>({ start: (c) => { ctrl = c } })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, body }))
    const ch = 'test-thinking-1'
    const p = startChatStream({ channel: ch, url: '/x', body: {}, sessionId: null, message: 'q' })
    ctrl.enqueue(sse({ start: true, session_id: 3 }))
    ctrl.enqueue(sse({ type: 'thinking', text: 'Önce diskleri ' }))
    ctrl.enqueue(sse({ type: 'thinking', text: 'kontrol edeyim.' }))
    await vi.waitFor(() => expect(getChatStream(ch).thinkingText).toBe('Önce diskleri kontrol edeyim.'))
    expect(getChatStream(ch).streamingText).toBe('')

    ctrl.enqueue(sse({ token: 'Cevap' }))
    await vi.waitFor(() => expect(getChatStream(ch).streamingText).toBe('Cevap'))
    expect(getChatStream(ch).thinkingText).toBe('Önce diskleri kontrol edeyim.')   // cevap başlayınca da saklı

    ctrl.enqueue(sse({ type: 'thinking', text: '' }))                              // boş olay yok sayılır
    ctrl.enqueue(sse({ done: true, session_id: 3 }))
    ctrl.close()
    await p
    expect(getChatStream(ch).thinkingText).toBe('')
  })
})
