/**
 * Exadata Altyapı Analizi — Exadata compute/cell sunucularına bağlı Linux hostlar üzerinden AI analiz.
 */
import { useT } from '../i18n/LocaleProvider'
import Chat from './Chat'

export default function ExadataChat() {
  const t = useT()
  return (
    <div className="space-y-2">
      <div className="mx-4 px-4 py-2 rounded-xl bg-orange-500/10 border border-orange-500/25 text-sm text-orange-200">
        <span className="font-semibold">{t('chat_exa_title')}</span>
        <span className="text-orange-200/70 ml-2">{t('chat_exa_sub')}</span>
      </div>
      <Chat />
    </div>
  )
}
