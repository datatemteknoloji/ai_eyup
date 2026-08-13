import { type RefObject, useEffect, useRef } from 'react'

const NEAR_PX = 140

function isNearBottom(el: HTMLElement): boolean {
  return el.scrollHeight - el.scrollTop - el.clientHeight < NEAR_PX
}

function jumpToBottom(el: HTMLElement) {
  el.scrollTop = el.scrollHeight
  requestAnimationFrame(() => {
    el.scrollTop = el.scrollHeight
    requestAnimationFrame(() => {
      el.scrollTop = el.scrollHeight
    })
  })
}

/**
 * Sohbet listesi kaydırması:
 * - Oturum açılınca / mesajlar yüklenince en alta in
 * - Kullanıcı mesaj gönderince tekrar alta pinle
 * - AI stream / yeni satır: alta yakınken takip et
 * - Kullanıcı geçmişi okumak için yukarı kaydırdıysa bırak
 */
export function useChatStickToBottom(
  containerRef: RefObject<HTMLElement | null>,
  opts: {
    sessionId: number | string | null
    messageCount: number
    followKey: unknown
    sending?: boolean
  },
) {
  const { sessionId, messageCount, followKey, sending = false } = opts
  const pinnedRef = useRef(true)
  const prevSession = useRef(sessionId)
  const prevSending = useRef(false)

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const onScroll = () => {
      pinnedRef.current = isNearBottom(el)
    }
    el.addEventListener('scroll', onScroll, { passive: true })
    return () => el.removeEventListener('scroll', onScroll)
  }, [containerRef])

  useEffect(() => {
    const el = containerRef.current
    if (!el) return
    const sessionChanged = prevSession.current !== sessionId
    prevSession.current = sessionId
    const startedSending = sending && !prevSending.current
    prevSending.current = sending
    if (sessionChanged || startedSending) pinnedRef.current = true
    if (pinnedRef.current) jumpToBottom(el)
  }, [containerRef, sessionId, messageCount, followKey, sending])
}
