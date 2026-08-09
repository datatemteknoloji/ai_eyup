import { Level1Shell } from './Level1Shell'
import { JobsPage } from '@dropt/pages/JobsPage'
import { JobDetailPage } from '@dropt/pages/JobDetailPage'
import { I18nProvider } from '@dropt/i18n/I18nProvider'
import { Route, Routes } from 'react-router-dom'

/** Nested Routes (same BrowserRouter) — MemoryRouter yasak (RR6 invariant). */
export default function Level1Jobs() {
  return (
    <Level1Shell
      title="İşler"
      subtitle="Level 1 operasyon işleri — durum, ilerleme ve sunucu sonuçları."
    >
      <I18nProvider>
        <div className="level1-has-shell-title flex min-h-0 flex-1 flex-col rounded-xl border border-white/[0.06] bg-cyber-card overflow-hidden">
          <div className="flex-1 min-h-0 overflow-auto p-5">
            <Routes>
              <Route index element={<JobsPage />} />
              <Route path=":id" element={<JobDetailPage />} />
            </Routes>
          </div>
        </div>
      </I18nProvider>
    </Level1Shell>
  )
}
