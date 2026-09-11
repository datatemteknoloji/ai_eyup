import { useT } from '../i18n/LocaleProvider'

export type ChatEvidence = {
  level: 'high' | 'medium' | 'low' | 'hidden'
  reason?: string
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
