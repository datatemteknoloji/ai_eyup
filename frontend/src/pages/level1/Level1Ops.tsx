import { Level1Shell } from './Level1Shell'
import { I18nProvider } from '@dropt/i18n/I18nProvider'
import { Navigate, Route, Routes } from 'react-router-dom'
import { LocalUsersPage } from '@dropt/pages/LocalUsersPage'
import { HostnamePage } from '@dropt/pages/HostnamePage'
import { RebootPage } from '@dropt/pages/RebootPage'
import { ServicesPage } from '@dropt/pages/ServicesPage'
import { SudoersPage } from '@dropt/pages/SudoersPage'
import { FilesystemPage } from '@dropt/pages/FilesystemPage'
import { PackagesPage } from '@dropt/pages/PackagesPage'
import { PathPermsPage } from '@dropt/pages/PathPermsPage'
import { LogCollectPage } from '@dropt/pages/LogCollectPage'
import { LimitsPage } from '@dropt/pages/LimitsPage'
import { SysctlPage } from '@dropt/pages/SysctlPage'
import { NetworkPage, VlanRedirect } from '@dropt/pages/NetworkPage'
import { AsmPage } from '@dropt/pages/AsmPage'
import { MailConfigPage } from '@dropt/pages/MailConfigPage'
import { TerminalPage } from '@dropt/pages/TerminalPage'

/** Standalone ops wizards (multi-select / sağ tık → /level1/ops/...). */
export default function Level1Ops() {
  return (
    <Level1Shell
      title="Operasyon"
      subtitle="Seçili sunucular için Level 1 sihirbazı — önizleme ve uygulama."
    >
      <I18nProvider>
        <div className="level1-ops-wizard overflow-hidden p-4 md:p-5">
          <Routes>
            <Route path="terminal" element={<TerminalPage />} />
            <Route path="local-users" element={<LocalUsersPage />} />
            <Route path="hostname" element={<HostnamePage />} />
            <Route path="reboot" element={<RebootPage />} />
            <Route path="services" element={<ServicesPage />} />
            <Route path="sudoers" element={<SudoersPage />} />
            <Route path="filesystem" element={<FilesystemPage />} />
            <Route path="packages" element={<PackagesPage />} />
            <Route path="path-perms" element={<PathPermsPage />} />
            <Route path="logs" element={<LogCollectPage />} />
            <Route path="limits" element={<LimitsPage />} />
            <Route path="sysctl" element={<SysctlPage />} />
            <Route path="network" element={<NetworkPage />} />
            <Route path="vlan" element={<VlanRedirect />} />
            <Route path="asm" element={<AsmPage />} />
            <Route path="mail-config" element={<MailConfigPage />} />
            <Route path="*" element={<Navigate to="/level1" replace />} />
          </Routes>
        </div>
      </I18nProvider>
    </Level1Shell>
  )
}
