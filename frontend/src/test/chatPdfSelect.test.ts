import { describe, expect, it } from 'vitest'
import { pairChatMessages } from '../lib/chatPdfSelect'

describe('pairChatMessages', () => {
  it('groups user + following assistant', () => {
    const pairs = pairChatMessages([
      { id: 1, role: 'user', content: 'q1' },
      { id: 2, role: 'assistant', content: 'a1' },
      { id: 3, role: 'user', content: 'q2' },
      { id: 4, role: 'assistant', content: 'a2' },
    ])
    expect(pairs).toHaveLength(2)
    expect(pairs[0].messages.map(m => m.id)).toEqual([1, 2])
    expect(pairs[1].messages.map(m => m.id)).toEqual([3, 4])
  })

  it('keeps orphan user or assistant as its own pair', () => {
    const pairs = pairChatMessages([
      { id: 1, role: 'assistant', content: 'orphan' },
      { id: 2, role: 'user', content: 'no answer yet' },
    ])
    expect(pairs).toHaveLength(2)
    expect(pairs[0].messages).toHaveLength(1)
    expect(pairs[1].messages).toHaveLength(1)
  })
})
