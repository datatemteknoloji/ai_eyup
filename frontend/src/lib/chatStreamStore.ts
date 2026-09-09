/**
 * Chat SSE stream — route unmount'tan bağımsız.
 * Sayfa değişince abort edilmez; geri dönünce aynı channel state'i okunur.
 */
import { useSyncExternalStore } from 'react'
import { API_BASE_URL } from '../config/api'
import { getToken } from '../auth/authStore'

/**
 * Sohbet uçlarına kimlik başlığı.
 *
 * Bu istekler token göndermiyordu; bu yüzden sunucu turu kime ait olduğunu
 * bilemiyor ve `/chat-turns/*` uçları (olay akışı, snapshot, iptal) yalnız
 * turn_id bilen herkese açık kalıyordu. Başlık gönderildiğinde sunucu turu
 * kullanıcıya bağlar ve sahiplik kontrolü devreye girer (bkz. chat_turns.py).
 */
function authHeaders(): Record<string, string> {
  const token = getToken()
  return token ? { Authorization: `Bearer ${token}` } : {}
}

export type ThinkingPhase = 'idle' | 'queued' | 'context' | 'tools' | 'streaming'

export type ToolCallProgress = { tool: string; label: string; done: boolean }

export type ClarifyOption = { id: string; label: string; prompt: string }

export type ChatSuggestion = { type?: string; label: string }

/** Sağlayıcının bildirdiği token tüketimi (yalnız admin göstergesi). */
export type ChatUsage = {
  prompt_tokens: number
  completion_tokens: number
  total_tokens: number
  calls?: number
}

export type ChatStreamSnapshot = {
  channel: string
  sessionId: number | null
  turnId: string | null
  pendingUserMessage: string | null
  streamingText: string
  thinkingPhase: ThinkingPhase
  isLoading: boolean
  toolCalls: ToolCallProgress[]
  clarifyOptions: ClarifyOption[] | null
  suggestions: ChatSuggestion[] | null
  queueMessage: string | null
  lastUsage: ChatUsage | null
  /** Son akış kullanıcı isteğiyle durduruldu mu? */
  cancelled: boolean
}

type Entry = {
  snap: ChatStreamSnapshot
  abort: AbortController | null
  listeners: Set<() => void>
}

const entries = new Map<string, Entry>()

const emptySnap = (channel: string): ChatStreamSnapshot => ({
  channel,
  sessionId: null,
  turnId: null,
  pendingUserMessage: null,
  streamingText: '',
  thinkingPhase: 'idle',
  isLoading: false,
  toolCalls: [],
  clarifyOptions: null,
  suggestions: null,
  queueMessage: null,
  lastUsage: null,
  cancelled: false,
})

function ensure(channel: string): Entry {
  let e = entries.get(channel)
  if (!e) {
    e = { snap: emptySnap(channel), abort: null, listeners: new Set() }
    entries.set(channel, e)
  }
  return e
}

function emit(channel: string) {
  const e = entries.get(channel)
  if (!e) return
  e.listeners.forEach((l) => {
    try {
      l()
    } catch {
      /* ignore */
    }
  })
}

function patch(channel: string, partial: Partial<ChatStreamSnapshot>) {
  const e = ensure(channel)
  e.snap = { ...e.snap, ...partial }
  emit(channel)
}

export function getChatStream(channel: string): ChatStreamSnapshot {
  return ensure(channel).snap
}

export function subscribeChatStream(channel: string, listener: () => void): () => void {
  const e = ensure(channel)
  e.listeners.add(listener)
  return () => {
    e.listeners.delete(listener)
  }
}

export function useChatStream(channel: string): ChatStreamSnapshot {
  return useSyncExternalStore(
    (onStoreChange) => subscribeChatStream(channel, onStoreChange),
    () => getChatStream(channel),
    () => getChatStream(channel),
  )
}

/**
 * Akışı durdur.
 *
 * `keepPartial` (varsayılan): o ana kadar üretilmiş metin ekranda KALIR.
 * Eskiden snapshot tamamen sıfırlanıyordu ve kullanıcı "durdur"a bastığında
 * yarım cevap da silindiği için 40 saniyelik üretim boşa gidiyordu. Kısmi
 * cevap sohbet geçmişine yazılmaz (tamamlanmamış bir yanıttır) ama yeni bir
 * mesaj gönderilene kadar görünür kalır.
 *
 * Oturum değiştirme gibi durumlarda çağıran `keepPartial: false` verir.
 */
export function abortChatStream(channel: string, opts?: { keepPartial?: boolean }) {
  const e = entries.get(channel)
  if (!e) return
  const keepPartial = opts?.keepPartial !== false
  const turnId = e.snap.turnId || loadPersistedTurnId(channel)
  if (turnId) {
    try {
      fetch(`${API_BASE_URL}/chat-turns/${turnId}/cancel`, {
        method: 'POST',
        headers: authHeaders(),
      }).catch(() => undefined)
    } catch {
      /* */
    }
    persistTurnId(channel, null)
  }
  e.abort?.abort()
  e.abort = null
  const partial = keepPartial ? (e.snap.streamingText || '') : ''
  e.snap = {
    ...emptySnap(channel),
    sessionId: e.snap.sessionId,
    pendingUserMessage: keepPartial ? e.snap.pendingUserMessage : null,
    streamingText: partial ? `${partial}\n\n_(Yanıt kullanıcı isteğiyle durduruldu.)_` : '',
    cancelled: Boolean(partial) || keepPartial,
  }
  emit(channel)
}

export function clearChatClarify(channel: string) {
  patch(channel, { clarifyOptions: null })
}

/** Stream bitti / hata — yükleme bayraklarını temizle (sessionId + clarify korunur). */
function finishIdle(channel: string, extra?: Partial<ChatStreamSnapshot>) {
  const prevClarify = getChatStream(channel).clarifyOptions
  patch(channel, {
    isLoading: false,
    thinkingPhase: 'idle',
    pendingUserMessage: null,
    streamingText: '',
    toolCalls: [],
    clarifyOptions: prevClarify,
    ...extra,
  })
  const e = entries.get(channel)
  if (e) e.abort = null
}

export type StartChatStreamOpts = {
  channel: string
  url: string
  body: Record<string, unknown>
  sessionId: number | null
  message: string
  initialPhase?: ThinkingPhase
  method?: 'POST' | 'GET'
  /** Yeni session_id SSE'den gelince */
  onSessionId?: (id: number) => void
  /** Stream başarıyla bittiğinde (mesajlar refetch için) */
  onDone?: (sessionId: number | null) => void | Promise<void>
}

/**
 * SSE chat stream başlat. Component unmount olsa da devam eder.
 * Aynı channel'da önceki stream iptal edilir.
 */
export async function startChatStream(opts: StartChatStreamOpts): Promise<void> {
  const {
    channel,
    url,
    body,
    sessionId,
    message,
    initialPhase = 'streaming',
    method = 'POST',
    onSessionId,
    onDone,
  } = opts

  const e = ensure(channel)
  e.abort?.abort()
  const ctrl = new AbortController()
  e.abort = ctrl

  patch(channel, {
    sessionId,
    pendingUserMessage: message,
    streamingText: '',
    thinkingPhase: initialPhase,
    isLoading: true,
    toolCalls: [],
    clarifyOptions: null,
    lastUsage: null,
    cancelled: false,
  })

  let activeSessionId = sessionId
  let accumulated = ''

  try {
    const res = await fetch(url, {
      method,
      headers:
        method === 'POST'
          ? { 'Content-Type': 'application/json', ...authHeaders() }
          : authHeaders(),
      body: method === 'POST' ? JSON.stringify(body) : undefined,
      signal: ctrl.signal,
    })

    if (!res.ok || !res.body) {
      throw new Error(`HTTP ${res.status}`)
    }

    const reader = res.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      if (ctrl.signal.aborted) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const jsonStr = line.slice(6).trim()
        if (!jsonStr) continue
        try {
          const chunk = JSON.parse(jsonStr)

          if (chunk.start) {
            if (chunk.turn_id) {
              persistTurnId(channel, String(chunk.turn_id))
              patch(channel, { turnId: String(chunk.turn_id) })
            }
            if (chunk.session_id) {
              activeSessionId = Number(chunk.session_id)
              patch(channel, { sessionId: activeSessionId, thinkingPhase: 'streaming' })
              onSessionId?.(activeSessionId)
            } else {
              patch(channel, { thinkingPhase: 'streaming' })
            }
          }
          if (chunk.queued) {
            const pos = chunk.position
            const msg =
              chunk.message ||
              (pos != null ? `Sıradasınız: ${pos}` : 'Kuyrukta…')
            patch(channel, { thinkingPhase: 'queued', queueMessage: String(msg) })
          }
          if (chunk.phase === 'collecting') patch(channel, { thinkingPhase: 'context' })
          if (chunk.phase === 'tools') patch(channel, { thinkingPhase: 'tools' })
          if (chunk.phase === 'answering') patch(channel, { thinkingPhase: 'streaming' })
          if (chunk.from_cache) patch(channel, { thinkingPhase: 'streaming' })

          if (chunk.token) {
            accumulated += chunk.token
            patch(channel, { streamingText: accumulated, thinkingPhase: 'streaming' })
          }

          if (chunk.type === 'tool_call') {
            const tool = chunk.tool || ''
            const label = chunk.label || tool
            const prev = getChatStream(channel).toolCalls
            patch(channel, { toolCalls: [...prev, { tool, label, done: false }] })
          }
          if (chunk.type === 'tool_result') {
            const tool = chunk.tool || ''
            const prev = getChatStream(channel).toolCalls
            const idx = [...prev].reverse().findIndex((t) => t.tool === tool && !t.done)
            if (idx !== -1) {
              const realIdx = prev.length - 1 - idx
              const next = [...prev]
              next[realIdx] = { ...next[realIdx], done: true }
              patch(channel, { toolCalls: next })
            }
          }

          if (chunk.type === 'clarify' && Array.isArray(chunk.options)) {
            patch(channel, { clarifyOptions: chunk.options as ClarifyOption[] })
          } else if (chunk.clarify_options && Array.isArray(chunk.clarify_options)) {
            patch(channel, { clarifyOptions: chunk.clarify_options as ClarifyOption[] })
          }

          if (chunk.usage && typeof chunk.usage === 'object') {
            patch(channel, { lastUsage: chunk.usage as ChatUsage })
          }

          if (Array.isArray(chunk.suggestions) && chunk.suggestions.length) {
            patch(channel, {
              suggestions: chunk.suggestions.map((s: any) =>
                typeof s === 'string' ? { label: s } : { type: s.type, label: s.label || String(s) },
              ),
            })
          }

          if (chunk.error) {
            patch(channel, {
              streamingText: `**Hata:** ${chunk.error}`,
              thinkingPhase: 'idle',
            })
          }

          if (chunk.done) {
            if (chunk.session_id) {
              activeSessionId = Number(chunk.session_id)
              patch(channel, { sessionId: activeSessionId })
            }
            try {
              await onDone?.(activeSessionId)
            } catch {
              /* refetch hatası stream'i bozmasın */
            }
            persistTurnId(channel, null)
            if (chunk.cancelled) {
              // Sunucu iptali onayladı (bkz. chat_orchestrator.cancel_turn):
              // o ana kadar üretilen metin korunur, sohbet geçmişine yazılmaz.
              const notice = String(chunk.notice || 'Yanıt üretimi durduruldu.')
              finishIdle(channel, {
                sessionId: activeSessionId,
                turnId: null,
                cancelled: true,
                streamingText: accumulated ? `${accumulated}\n\n_(${notice})_` : `_(${notice})_`,
              })
              return
            }
            finishIdle(channel, { sessionId: activeSessionId, turnId: null })
            return
          }
        } catch {
          /* json parse */
        }
      }
    }

    // Reader bitti ama done gelmedi (proxy kopması, uzak LLM erken kapanış)
    if (!ctrl.signal.aborted) {
      const prevText = getChatStream(channel).streamingText || ''
      const isErr =
        prevText.startsWith('**Hata:') || prevText.startsWith('**Bağlantı')
      try {
        await onDone?.(activeSessionId)
      } catch {
        /* */
      }
      finishIdle(channel, {
        sessionId: activeSessionId,
        streamingText: isErr
          ? prevText
          : accumulated
            ? ''
            : '**Bağlantı hatası.** Tekrar deneyin.',
      })
    }
  } catch (err: any) {
    if (err?.name === 'AbortError') {
      finishIdle(channel, { sessionId: activeSessionId })
      return
    }
    try {
      await onDone?.(activeSessionId)
    } catch {
      /* refetch */
    }
    finishIdle(channel, {
      sessionId: activeSessionId,
      streamingText: '**Bağlantı hatası.** Tekrar deneyin.',
    })
  }
}

/** sessionStorage: son seçili chat session (platform başına) */
export function loadPersistedSessionId(channel: string): number | null {
  try {
    const v = sessionStorage.getItem(`ainew.chat.session.${channel}`)
    if (!v) return null
    const n = Number(v)
    return Number.isFinite(n) ? n : null
  } catch {
    return null
  }
}

export function persistTurnId(channel: string, id: string | null) {
  try {
    if (!id) sessionStorage.removeItem(`ainew.chat.turn.${channel}`)
    else sessionStorage.setItem(`ainew.chat.turn.${channel}`, id)
  } catch {
    /* */
  }
}

export function loadPersistedTurnId(channel: string): string | null {
  try {
    return sessionStorage.getItem(`ainew.chat.turn.${channel}`)
  } catch {
    return null
  }
}

export function persistSessionId(channel: string, id: number | null) {
  try {
    if (id == null) sessionStorage.removeItem(`ainew.chat.session.${channel}`)
    else sessionStorage.setItem(`ainew.chat.session.${channel}`, String(id))
  } catch {
    /* */
  }
}

/** Sayfa yenilemede devam eden turn'e yeniden bağlan. */
export async function restoreChatTurn(opts: {
  channel: string
  onSessionId?: (id: number) => void
  onDone?: (sessionId: number | null) => void | Promise<void>
}): Promise<boolean> {
  const turnId = loadPersistedTurnId(opts.channel)
  if (!turnId) return false
  await startChatStream({
    channel: opts.channel,
    url: `${API_BASE_URL}/chat-turns/${turnId}/events`,
    body: {},
    sessionId: loadPersistedSessionId(opts.channel),
    message: getChatStream(opts.channel).pendingUserMessage || '',
    initialPhase: 'streaming',
    method: 'GET',
    onSessionId: opts.onSessionId,
    onDone: opts.onDone,
  })
  return true
}
