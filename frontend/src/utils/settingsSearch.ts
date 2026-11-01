/** Ayarlar sayfası arama yardımcıları (Türkçe harf/aksan duyarsız, çok kelimeli VE araması). */

/** «Önbellek», «ONBELLEK», «onbellek» aynı olsun: küçük harf (tr) + aksan sil + ı→i. */
export function normSearch(s: string | undefined | null): string {
  return (s ?? '')
    .toLocaleLowerCase('tr')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/ı/g, 'i')
    .replace(/[_\-./:]+/g, ' ')
}

export function queryTokens(q: string): string[] {
  return normSearch(q).split(/\s+/).filter(Boolean)
}

/** Her kelime, birleşik metinde geçmeli (sıra önemsiz). Boş sorgu her şeyle eşleşir. */
export function matchesQuery(parts: Array<string | undefined | null>, q: string): boolean {
  const tokens = queryTokens(q)
  if (tokens.length === 0) return true
  const hay = normSearch(parts.filter(Boolean).join(' '))
  // Türkçe ünsüz yumuşaması: «önbellek» ↔ «önbelleği» — uzun kelimelerde son harf düşürülmüş kök de kabul
  return tokens.every(tk => hay.includes(tk) || (tk.length >= 5 && hay.includes(tk.slice(0, -1))))
}

export interface SearchableAdvSetting {
  key: string
  label: string
  help?: string
  group_label?: string
  env?: string
  notes?: string[]
  choices?: string[]
}

export function advSettingMatches(s: SearchableAdvSetting, q: string): boolean {
  return matchesQuery([s.label, s.key, s.help, s.group_label, s.env, ...(s.notes || []), ...(s.choices || [])], q)
}
