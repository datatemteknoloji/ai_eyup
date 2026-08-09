import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@dropt/components/AppShell";
import { AdminSystemPage } from "@dropt/pages/AdminSystemPage";
import { AsmPage } from "@dropt/pages/AsmPage";
import { AuditPage } from "@dropt/pages/AuditPage";
import { DashboardPage } from "@dropt/pages/DashboardPage";
import { FilesystemPage } from "@dropt/pages/FilesystemPage";
import { HostnamePage } from "@dropt/pages/HostnamePage";
import { PackagesPage } from "@dropt/pages/PackagesPage";
import { JobDetailPage } from "@dropt/pages/JobDetailPage";
import { JobsPage } from "@dropt/pages/JobsPage";
import { LocalUsersPage } from "@dropt/pages/LocalUsersPage";
import { LogCollectPage } from "@dropt/pages/LogCollectPage";
import { LoginPage } from "@dropt/pages/LoginPage";
import { MailConfigPage } from "@dropt/pages/MailConfigPage";
import { PathPermsPage } from "@dropt/pages/PathPermsPage";
import { PortalUsersPage } from "@dropt/pages/PortalUsersPage";
import { RebootPage } from "@dropt/pages/RebootPage";
import { ServicesPage } from "@dropt/pages/ServicesPage";
import { ServerConsolePage } from "@dropt/pages/ServerConsolePage";
import { ServersPage } from "@dropt/pages/ServersPage";
import { SettingsPage } from "@dropt/pages/SettingsPage";
import { SudoersPage } from "@dropt/pages/SudoersPage";
import { SysctlPage } from "@dropt/pages/SysctlPage";
import { LimitsPage } from "@dropt/pages/LimitsPage";
import { TerminalPage } from "@dropt/pages/TerminalPage";
import { NetworkPage, VlanRedirect } from "@dropt/pages/NetworkPage";
import { getToken } from "@dropt/session";

function RequireAuth({ children }: { children: ReactNode }) {
  if (!getToken()) return <Navigate to="/" replace />;
  return children;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LoginPage />} />
        <Route
          path="/app"
          element={
            <RequireAuth>
              <AppShell />
            </RequireAuth>
          }
        >
          <Route index element={<DashboardPage />} />
          <Route path="servers" element={<ServersPage />} />
          <Route path="servers/:id" element={<ServerConsolePage />} />
          <Route path="local-users" element={<LocalUsersPage />} />
          <Route path="hostname" element={<HostnamePage />} />
          <Route path="reboot" element={<RebootPage />} />
          <Route path="services" element={<ServicesPage />} />
          <Route path="sudoers" element={<SudoersPage />} />
          <Route path="filesystem" element={<FilesystemPage />} />
          <Route path="filesystem-create" element={<Navigate to="/app/filesystem" replace />} />
          <Route path="packages" element={<PackagesPage />} />
          <Route path="docker" element={<Navigate to="/app/packages" replace />} />
          <Route path="path-perms" element={<PathPermsPage />} />
          <Route path="logs" element={<LogCollectPage />} />
          <Route path="limits" element={<LimitsPage />} />
          <Route path="sysctl" element={<SysctlPage />} />
          <Route path="network" element={<NetworkPage />} />
          <Route path="vlan" element={<VlanRedirect />} />
          <Route path="asm" element={<AsmPage />} />
          <Route path="mail-config" element={<MailConfigPage />} />
          <Route path="terminal" element={<TerminalPage />} />
          <Route path="jobs" element={<JobsPage />} />
          <Route path="jobs/:id" element={<JobDetailPage />} />
          <Route path="audit" element={<AuditPage />} />
          <Route path="settings" element={<SettingsPage />} />
          <Route path="users" element={<PortalUsersPage />} />
          <Route path="system" element={<AdminSystemPage />} />
        </Route>
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
