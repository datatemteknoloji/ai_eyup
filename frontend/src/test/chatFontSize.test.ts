import { describe, it, expect, beforeEach } from 'vitest'
import {
  CHAT_FONT_SIZES, CHAT_FONT_SIZE_KEY, DEFAULT_CHAT_FONT_SIZE,
  applyChatFontSize, getChatFontSize, initChatFontSize, setChatFontSize,
} from '../lib/chatFontSize'

describe('chatFontSize (Adım 16)', () => {
  beforeEach(() => {
    localStorage.clear()
    delete document.documentElement.dataset.chatSize
  })

  it('varsayılan 12 px (m)', () => {
    expect(DEFAULT_CHAT_FONT_SIZE).toBe('m')
    expect(CHAT_FONT_SIZES.find(s => s.id === 'm')?.px).toBe(12)
    expect(getChatFontSize()).toBe('m')
  })

  it('seçenekler 11/12/13/15', () => {
    expect(CHAT_FONT_SIZES.map(s => s.px)).toEqual([11, 12, 13, 15])
  })

  it('setChatFontSize kalıcı + html özniteliği', () => {
    setChatFontSize('xl')
    expect(localStorage.getItem(CHAT_FONT_SIZE_KEY)).toBe('xl')
    expect(document.documentElement.dataset.chatSize).toBe('xl')
    expect(getChatFontSize()).toBe('xl')
  })

  it('geçersiz kayıt varsayılana düşer; init uygular', () => {
    localStorage.setItem(CHAT_FONT_SIZE_KEY, 'dev')
    expect(getChatFontSize()).toBe('m')
    localStorage.setItem(CHAT_FONT_SIZE_KEY, 's')
    initChatFontSize()
    expect(document.documentElement.dataset.chatSize).toBe('s')
    applyChatFontSize('l')
    expect(document.documentElement.dataset.chatSize).toBe('l')
  })
})
