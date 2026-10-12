import { resolveMethod, type MethodCatalog } from '../components/insights/MethodBadge'

/**
 * İstemci tarafında üretilen PDF'ler (ör. AWR/RCA) için "Yöntem notları" bölümü.
 * Metin elle yazılmaz: `method_registry` kataloğundan (GET /api/v1/methods) okunur; sunucu tarafı raporlardaki
 * (`report_method_notes.py`) bölümle aynı kaynaktan gelir. Kayıtsız kimlik atlanır.
 */
export function methodNotesSection(
  cat: MethodCatalog | undefined, ids: string[], en: boolean, heading: string,
): { heading: string; items: string[] } | null {
  if (!cat) return null
  const items: string[] = []
  let anyAi = false
  for (const id of ids) {
    const m = resolveMethod(cat, id)
    if (!m) continue
    const cls = cat.classes.find(c => c.id === m.cls)
    const label = cls ? (en ? cls.label_en : cls.label_tr) : m.cls
    const [src, lim] = en ? ['Source', 'Limits'] : ['Kaynak', 'Sınırlar']
    items.push(`${label} — ${en ? m.method_en : m.method_tr} ${src}: ${en ? m.source_en : m.source_tr} ${lim}: ${en ? m.limits_en : m.limits_tr}`)
    anyAi = anyAi || m.uses_ai
  }
  if (anyAi) items.push(en ? cat.ai_note_en : cat.ai_note_tr)
  return items.length ? { heading, items } : null
}
