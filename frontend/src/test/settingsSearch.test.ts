import { describe, expect, it } from 'vitest'
import { advSettingMatches, matchesQuery, normSearch } from '../utils/settingsSearch'

describe('normSearch', () => {
  it('Türkçe harf ve aksanları eşitler', () => {
    expect(normSearch('ÖNBELLEK')).toBe('onbellek')
    expect(normSearch('Sohbet Cevap Önbelleği')).toBe('sohbet cevap onbellegi')
    expect(normSearch('IŞIK')).toBe('isik')
    expect(normSearch('chat_cache_enabled')).toBe('chat cache enabled')
  })
})

describe('matchesQuery', () => {
  it('boş sorgu her şeyle eşleşir', () => {
    expect(matchesQuery(['x'], '')).toBe(true)
    expect(matchesQuery([], '   ')).toBe(true)
  })
  it('çok kelimeli arama: her kelime geçmeli, sıra önemsiz', () => {
    expect(matchesQuery(['Sohbet cevap önbelleği'], 'önbellek sohbet')).toBe(true)
    expect(matchesQuery(['Sohbet cevap önbelleği'], 'önbellek disk')).toBe(false)
  })
})

describe('advSettingMatches', () => {
  const cache = {
    key: 'chat_cache_enabled', label: 'Sohbet cevap önbelleği', help: 'Tekrarlanan soruları LLM çağırmadan yanıtlar',
    group_label: 'AI / Sohbet', env: 'CHAT_CACHE_ENABLED',
  }
  const other = { key: 'ssh_timeout', label: 'SSH zaman aşımı', help: 'Bağlantı süresi', group_label: 'Timeout' }

  it('etikete, anahtara, açıklamaya, gruba ve env adına göre bulur', () => {
    expect(advSettingMatches(cache, 'cache')).toBe(true)          // anahtar
    expect(advSettingMatches(cache, 'önbellek')).toBe(true)       // etiket
    expect(advSettingMatches(cache, 'chat cache')).toBe(true)     // anahtar (alt çizgi = boşluk)
    expect(advSettingMatches(cache, 'llm çağırmadan')).toBe(true) // açıklama
    expect(advSettingMatches(cache, 'CHAT_CACHE')).toBe(true)     // env
    expect(advSettingMatches(cache, 'AI sohbet')).toBe(true)      // grup + etiket
  })
  it('ilgisiz ayarı eşlemez', () => {
    expect(advSettingMatches(other, 'cache')).toBe(false)
    expect(advSettingMatches(other, 'ssh timeout')).toBe(true)
  })
})
