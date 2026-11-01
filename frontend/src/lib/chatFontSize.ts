/**
 * Adım 16 — sohbet yazı boyutu (Yönetici / Linux / Windows / Sanallaştırma / OpenShift).
 * Tek merkez: `<html data-chat-size="m">` → CSS `--chat-fs` (index.css). Diğer sayfalar etkilenmez.
 */
export type ChatFontSize = 's' | 'm' | 'l' | 'xl'

export const CHAT_FONT_SIZES: { id: ChatFontSize; px: number }[] = [
  { id: 's', px: 11 },
  { id: 'm', px: 12 },
  { id: 'l', px: 13 },
  { id: 'xl', px: 15 },
]

export const CHAT_FONT_SIZE_KEY = 'chat_font_size'
export const DEFAULT_CHAT_FONT_SIZE: ChatFontSize = 'm'

function isSize(v: unknown): v is ChatFontSize {
  return v === 's' || v === 'm' || v === 'l' || v === 'xl'
}

export function getChatFontSize(): ChatFontSize {
  try {
    const v = localStorage.getItem(CHAT_FONT_SIZE_KEY)
    if (isSize(v)) return v
  } catch { /* localStorage kapalı */ }
  return DEFAULT_CHAT_FONT_SIZE
}

export function applyChatFontSize(size: ChatFontSize): void {
  if (typeof document !== 'undefined') document.documentElement.dataset.chatSize = size
}

export function setChatFontSize(size: ChatFontSize): void {
  try { localStorage.setItem(CHAT_FONT_SIZE_KEY, size) } catch { /* yoksay */ }
  applyChatFontSize(size)
}

export function initChatFontSize(): void {
  applyChatFontSize(getChatFontSize())
}
