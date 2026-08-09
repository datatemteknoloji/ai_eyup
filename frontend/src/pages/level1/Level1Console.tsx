import { Level1Shell } from './Level1Shell'
import { ServerConsolePage } from '@dropt/pages/ServerConsolePage'
import { I18nProvider } from '@dropt/i18n/I18nProvider'

/** Console — useParams().id from /level1/console/:id (no nested MemoryRouter). */
export default function Level1Console() {
  return (
    <Level1Shell>
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-white/[0.06] bg-cyber-card">
        <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
          <I18nProvider>
            <ServerConsolePage />
          </I18nProvider>
        </div>
      </div>
    </Level1Shell>
  )
}
