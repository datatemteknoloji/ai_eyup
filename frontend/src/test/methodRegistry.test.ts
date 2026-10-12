import { describe, expect, it } from 'vitest'
import { resolveMethod, type MethodCatalog, type MethodEntry } from '../components/insights/MethodBadge'
import IDS from './method_ids.json'

/**
 * Dilim T: yöntem kaydında olmayan bir id kullanan bileşen CI'ı kırar.
 * `method_ids.json` backend `method_registry.ids()` çıktısının kopyasıdır; backend testi
 * (`test_method_registry.py::test_snapshot_file_matches_registry`) iki kopyanın da güncel olduğunu doğrular.
 */
const catalog: MethodCatalog = {
  classes: [],
  ai_note_tr: '', ai_note_en: '', general_knowledge_tr: '', general_knowledge_en: '',
  methods: (IDS as string[]).map(id => ({ id } as MethodEntry)),
}

const SOURCES = import.meta.glob('../**/*.tsx', { query: '?raw', import: 'default', eager: true }) as Record<string, string>

function usedIds(src: string): string[] {
  const ids: string[] = []
  // method="x" | method='x' | <MethodBadge id="x"
  for (const m of src.matchAll(/\bmethod=(?:"([^"]+)"|'([^']+)')/g)) ids.push(m[1] || m[2])
  for (const m of src.matchAll(/<MethodBadge\s+id=(?:"([^"]+)"|'([^']+)')/g)) ids.push(m[1] || m[2])
  // `{ ..., method: 'ops.x' }` nesne alanları (HTTP `method: 'GET'` ile karışmaması için yalnız `alan.ad` / `ön:ek` biçimli id'ler)
  for (const m of src.matchAll(/\bmethod:\s*'([a-z_]+[.:][^']*)'/g)) ids.push(m[1])
  // method={cond ? 'a' : 'b'} — yalnız `?`/`:` sonrası literaller (koşuldaki karşılaştırma literalleri değil)
  for (const m of src.matchAll(/\bmethod=\{([^}]*)\}/g)) {
    for (const l of m[1].matchAll(/[?:]\s*'([^']+)'/g)) ids.push(l[1])
  }
  // `const FOO_METHOD: Record<string, string> = { a: 'x.y', ... }` eşlemeleri
  for (const m of src.matchAll(/const\s+\w*METHOD\w*\s*(?::[^=]+)?=\s*\{([^}]*)\}/g)) {
    for (const l of m[1].matchAll(/:\s*'([^']+)'/g)) ids.push(l[1])
  }
  // AiBlock varsayılanı: `method = 'ai.chat'` (yalnız MethodBadge.tsx içinde; başka dosyalardaki `method` HTTP vb. anlamındadır)
  if (/export function AiBlock/.test(src)) {
    for (const m of src.matchAll(/\bmethod\s*=\s*'([^']+)'/g)) ids.push(m[1])
  }
  return ids
}

describe('method registry coverage (frontend)', () => {
  const found: { file: string; id: string }[] = []
  for (const [f, src] of Object.entries(SOURCES)) {
    // yalnız yöntem rozeti/Panel/Stat kullanan dosyalar (başka `method=` kullanımları HTTP vb. olabilir)
    if (!/insights\/(MethodBadge|insightsKit)|export function AiBlock/.test(src)) continue
    for (const id of usedIds(src)) found.push({ file: f, id })
  }

  it('finds method usages (guard against a vacuous pass)', () => {
    expect(found.length).toBeGreaterThan(30)
  })

  it('every method id used in components is registered', () => {
    const missing = found.filter(x => !resolveMethod(catalog, x.id))
    expect(missing, `Kayıtsız yöntem id'leri: ${JSON.stringify(missing)}`).toEqual([])
  })

  it('resolves prefix patterns the same way as the backend', () => {
    expect(resolveMethod(catalog, 'vuln:VMSA-2024-0001')?.id).toBe('vuln:*')
    expect(resolveMethod(catalog, 'tool:vcenter_ask')?.id).toBe('tool:vcenter_ask')
    expect(resolveMethod(catalog, 'tool:vcenter_live_alarms')?.id).toBe('tool:vcenter_*')
    expect(resolveMethod(catalog, 'no.such.component')).toBeUndefined()
  })
})
