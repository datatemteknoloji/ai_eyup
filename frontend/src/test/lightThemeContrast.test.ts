import { describe, expect, it } from 'vitest'
// @ts-expect-error node:fs tipi yok (@types/node kurulu değil); vitest Node'da çalışır
import { readFileSync } from 'node:fs'

/**
 * Beyaz tema regresyonu: şeffaf/tinted mavi kartların (bg-blue-500/5, from-blue-600/20 …) içindeki
 * `.text-white` sayıları beyaza zorlanmamalı; yalnız DOLU mavi zeminde beyaz kalmalı.
 */
const rawCss: string = readFileSync('src/index.css', 'utf8')
const css = rawCss.replace(/\/\*[\s\S]*?\*\//g, '')

describe('light theme — text-white on blue backgrounds', () => {
  it('does not force white on any descendant of a blue/gradient substring match', () => {
    expect(css).not.toMatch(/\[class\*="bg-blue-"\]\s+\.text-white/)
    expect(css).not.toMatch(/\[class\*="from-blue"\]\s+\.text-white/)
    expect(css).not.toMatch(/\[class\*="bg-gradient"\]\s+\.text-white/)
    expect(css).not.toMatch(/\[class\*="bg-blue-"\]\.text-white/)
  })

  it('keeps white text on solid blue fills', () => {
    expect(css).toMatch(/\.bg-blue-600 \.text-white/)
    expect(css).toMatch(/\.bg-blue-600\.text-white/)
  })
})
