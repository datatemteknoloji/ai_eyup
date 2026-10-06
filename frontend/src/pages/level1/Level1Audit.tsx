import { Level1Shell } from './Level1Shell'
import { AuditPage } from '@dropt/pages/AuditPage'
import { I18nProvider } from '@dropt/i18n/I18nProvider'

export function Level1AuditContent() {
  return (
    <I18nProvider>
      <AuditPage />
    </I18nProvider>
  )
}

/** L1 Denetim — Dropt audit (tek store; nested MemoryRouter yok). Admin only. */
export default function Level1Audit() {
  return (
    <Level1Shell>
      <div className="flex min-h-0 flex-1 flex-col rounded-xl border border-white/[0.06] bg-cyber-card overflow-hidden">
        <div className="flex-1 min-h-0 overflow-auto px-4 py-2">
          <Level1AuditContent />
        </div>
      </div>
    </Level1Shell>
  )
}
