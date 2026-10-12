import { useT } from '../i18n/LocaleProvider'
import { MethodBadge, useMethodCatalog } from './insights/MethodBadge'
import { useLocale } from '../i18n/LocaleProvider'

export type ChatEvidenceSource = { tool: string; class: string | null; at?: string }

export type ChatEvidence = {
  level: 'high' | 'medium' | 'low' | 'hidden'
  reason?: string
  /** Bu turda çağrılan araçlar ve yöntem sınıfı (Dilim T.3). */
  sources?: ChatEvidenceSource[]
  /** Yanıt ortam verisine dayanmıyor: "AI genel bilgisi — ortamınızdan alınmadı". */
  general?: boolean
}

const STYLES: Record<string, string> = {
  high: 'text-emerald-300/90 border-emerald-500/30 bg-emerald-500/10',
  medium: 'text-amber-200/90 border-amber-500/30 bg-amber-500/10',
  low: 'text-rose-200/90 border-rose-500/30 bg-rose-500/10',
}

export function ChatEvidenceBadge({ evidence }: { evidence?: ChatEvidence | null }) {
  const t = useT()
  const level = evidence?.level
  if (!level || level === 'hidden' || !STYLES[level]) return null
  return (
    <span
      title={evidence?.reason || t('chat_evidence_hint')}
      className={`inline-flex items-center text-[10px] px-1.5 py-0.5 rounded border ${STYLES[level]}`}
    >
      {t(`chat_evidence_${level}`)}
    </span>
  )
}

/**
 * Asistan yanıtı altındaki şeffaflık satırları (Dilim T.3):
 *  - "Kaynak: virt_capacity_simulate (Hesap), 23:31" — araçtan gelen sayılar için
 *  - "AI genel bilgisi — ortamınızdan alınmadı" — araç/veri kullanılmayan bilgi için
 *  - metnin AI tarafından yazıldığını gösteren rozet (+ (i))
 */
export function ChatSources({ evidence }: { evidence?: ChatEvidence | null }) {
  const t = useT()
  const { locale } = useLocale()
  const cat = useMethodCatalog().data
  const sources = evidence?.sources || []
  const label = (cls: string | null) => {
    const c = cat?.classes.find(x => x.id === cls)
    return c ? (locale === 'en' ? c.label_en : c.label_tr) : t('method_unclassified')
  }
  const time = (at?: string) => (at ? new Date(at).toLocaleTimeString(locale === 'en' ? 'en-GB' : 'tr-TR', { hour: '2-digit', minute: '2-digit' }) : '')
  if (!sources.length && !evidence?.general) return null
  return (
    <div className="mt-2 space-y-0.5 text-[11px] text-slate-500" data-testid="chat-sources">
      {sources.slice(0, 6).map(s => (
        <div key={s.tool} className="font-mono">
          {t('method_source_line', { tool: s.tool, cls: label(s.class), time: time(s.at) })}
        </div>
      ))}
      {sources.length > 6 && <div>+{sources.length - 6}</div>}
      {evidence?.general && <div className="text-violet-300/80">{t('method_general_ai')}</div>}
      <div><MethodBadge id="ai.chat" /></div>
    </div>
  )
}
