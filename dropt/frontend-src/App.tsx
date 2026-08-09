import type { ReactNode } from "react";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { AdminSystemPage } from "@/pages/AdminSystemPage";
import { AsmPage } from "@/pages/AsmPage";
import { AuditPage } from "@/pages/AuditPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { FilesystemPage } from "@/pages/FilesystemPage";
import { HostnamePage } from "@/pages/HostnamePage";
import { PackagesPage } from "@/pages/PackagesPage";
import { JobDetailPage } from "@/pages/JobDetailPage";
import { JobsPage } from "@/pages/JobsPage";
import { LocalUsersPage } from "@/pages/LocalUsersPage";
import { LogCollectPage } from "@/pages/LogCollectPage";
import { LoginPage } from "@/pages/LoginPage";
import { MailConfigPage } from "@/pages/MailConfigPage";
import { PathPermsPage } from "@/pages/PathPermsPage";
import { PortalUsersPage } from "@/pages/PortalUsersPage";
import { RebootPage } from "@/pages/RebootPage";
import { ServicesPage } from "@/pages/ServicesPage";
import { ServerConsolePage } from "@/pages/ServerConsolePage";
import { ServersPage } from "@/pages/ServersPage";
import { SettingsPage } from "@/pages/SettingsPage";
import { SudoersPage } from "@/pages/SudoersPage";
import { SysctlPage } from "@/pages/SysctlPage";
import { LimitsPage } from "@/pages/LimitsPage";
import { TerminalPage } from "@/pages/TerminalPage";
import { NetworkPage, VlanRedirect } from "@/pages/NetworkPage";
import { getToken } from "@/session";

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
