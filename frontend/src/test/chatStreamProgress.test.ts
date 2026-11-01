import { describe, it, expect, vi, afterEach } from 'vitest'
import { startChatStream, getChatStream } from '../lib/chatStreamStore'

const enc = new TextEncoder()
const sse = (o: unknown) => enc.encode('data: ' + JSON.stringify(o) + '\n\n')

afterEach(() => {
  vi.unstubAllGlobals()
})

describe('chatStreamStore — Adım 10 ilerleme olayları', () => {
  it('progress ilk token öncesi görünür, token gelince temizlenir, sonradan gelen yok sayılır', async () => {
    let ctrl!: ReadableStreamDefaultController<Uint8Array>
    const body = new ReadableStream<Uint8Array>({ start: (c) => { ctrl = c } })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, body }))
    const ch = 'test-progress-1'
    const p = startChatStream({ channel: ch, url: '/x', body: {}, sessionId: null, message: 'q' })

    ctrl.enqueue(sse({ start: true, session_id: 7 }))
    ctrl.enqueue(sse({ type: 'progress', step: 'querying', text: 'Veriler sorgulanıyor (Disk)', elapsed_s: 3 }))
    await vi.waitFor(() => expect(getChatStream(ch).progress?.text).toBe('Veriler sorgulanıyor (Disk)'))
    expect(getChatStream(ch).progress?.step).toBe('querying')
    expect(getChatStream(ch).progress?.elapsedS).toBe(3)

    ctrl.enqueue(sse({ type: 'progress', step: 'waiting', text: 'Sonuçlar değerlendiriliyor — 8 sn', elapsed_s: 8, heartbeat: true }))
    await vi.waitFor(() => expect(getChatStream(ch).progress?.step).toBe('waiting'))

    ctrl.enqueue(sse({ token: 'Merhaba' }))
    await vi.waitFor(() => expect(getChatStream(ch).streamingText).toBe('Merhaba'))
    expect(getChatStream(ch).progress).toBeNull()

    ctrl.enqueue(sse({ type: 'progress', step: 'waiting', text: 'gecikmiş', elapsed_s: 30 }))
    ctrl.enqueue(sse({ token: ' dünya' }))
    await vi.waitFor(() => expect(getChatStream(ch).streamingText).toBe('Merhaba dünya'))
    expect(getChatStream(ch).progress).toBeNull()

    ctrl.enqueue(sse({ done: true, session_id: 7 }))
    ctrl.close()
    await p
  })

  it('metinsiz progress olayı yok sayılır; yeni akış progress\'i sıfırlar', async () => {
    let ctrl!: ReadableStreamDefaultController<Uint8Array>
    const body = new ReadableStream<Uint8Array>({ start: (c) => { ctrl = c } })
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, status: 200, body }))
    const ch = 'test-progress-2'
    const p = startChatStream({ channel: ch, url: '/x', body: {}, sessionId: null, message: 'q' })
    expect(getChatStream(ch).progress).toBeNull()
    ctrl.enqueue(sse({ type: 'progress', step: 'x', text: '', elapsed_s: 1 }))
    ctrl.enqueue(sse({ start: true, session_id: 1 }))
    await vi.waitFor(() => expect(getChatStream(ch).sessionId).toBe(1))
    expect(getChatStream(ch).progress).toBeNull()
    ctrl.enqueue(sse({ done: true, session_id: 1 }))
    ctrl.close()
    await p
  })
})
