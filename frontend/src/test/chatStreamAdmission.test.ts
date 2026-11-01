import { describe, it, expect, vi, afterEach } from 'vitest'
import { startChatStream, getChatStream, readFriendlyDetail } from '../lib/chatStreamStore'

afterEach(() => {
  vi.unstubAllGlobals()
})

const MSG = 'Önceki sorularınız hâlâ işleniyor. Lütfen birinin bitmesini bekleyin.'

describe('chatStreamStore — Adım 13 kabul reddi (429)', () => {
  it('429 gövdesindeki Türkçe açıklama «Bağlantı hatası» yerine gösterilir', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 429, body: null, json: async () => ({ detail: MSG }),
    }))
    await startChatStream({ channel: 'adm-1', url: '/x', body: {}, sessionId: null, message: 'q' })
    const st = getChatStream('adm-1')
    expect(st.isLoading).toBe(false)
    expect(st.streamingText).toContain(MSG)
    expect(st.streamingText).not.toContain('Bağlantı hatası')
  })

  it('JSON olmayan 429 / diğer hatalar eski davranışı korur', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 429, body: null, json: async () => { throw new Error('no json') },
    }))
    await startChatStream({ channel: 'adm-2', url: '/x', body: {}, sessionId: null, message: 'q' })
    expect(getChatStream('adm-2').streamingText).toContain('Bağlantı hatası')

    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: false, status: 500, body: null, json: async () => ({ detail: 'boom' }),
    }))
    await startChatStream({ channel: 'adm-3', url: '/x', body: {}, sessionId: null, message: 'q' })
    expect(getChatStream('adm-3').streamingText).toContain('Bağlantı hatası')   // 500 detay göstermez
  })

  it('readFriendlyDetail: yalnız dolu string detail', async () => {
    expect(await readFriendlyDetail({ json: async () => ({ detail: ' x ' }) })).toBe('x')
    expect(await readFriendlyDetail({ json: async () => ({ detail: [1] }) })).toBeNull()
    expect(await readFriendlyDetail({ json: async () => ({ detail: '' }) })).toBeNull()
  })
})
