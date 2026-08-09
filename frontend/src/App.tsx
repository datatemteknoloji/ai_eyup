import React, { Suspense, lazy } from 'react'
import { BrowserRouter, Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider, useAuth } from './auth/AuthContext'
import { BrandingProvider } from './branding/BrandingContext'
import { ThemeProvider } from './theme/ThemeProvider'
import ErrorBoundary from './components/ErrorBoundary'
import Layout from './components/Layout'
import { RequirePlatformAiops } from './components/RequirePlatformAiops'

// Eager: login + auth shell (ilk boya)
import Login from './pages/Login'

// Route-level code splitting — ağır sayfalar ayrı chunk
const AuditLog = lazy(() => import('./pages/AuditLog'))
const KnowledgeBase = lazy(() => import('./pages/KnowledgeBase'))
const Applications = lazy(() => import('./pages/Applications'))
const Servers = lazy(() => import('./pages/Servers'))
const Hypervisors = lazy(() => import('./pages/Hypervisors'))
const Agent = lazy(() => import('./pages/Agent'))
const AiAutomationHub = lazy(() => import('./pages/AiAutomationHub'))
const LiveMetrics = lazy(() => import('./pages/LiveMetrics'))
const Settings = lazy(() => import('./pages/Settings'))
const McpTools = lazy(() => import('./pages/McpTools'))
const Ansible = lazy(() => import('./pages/Ansible'))
const WindowsAnsible = lazy(() => import('./pages/WindowsAnsible'))
const PackageManager = lazy(() => import('./pages/PackageManager'))
const Repositories = lazy(() => import('./pages/Repositories'))
const SystemUpdate = lazy(() => import('./pages/SystemUpdate'))
const TerminalPage = lazy(() => import('./pages/TerminalPage'))
const ExecutiveDashboard = lazy(() => import('./pages/ExecutiveDashboard'))
const ExadataDashboard = lazy(() => import('./pages/ExadataDashboard'))
const OpenShiftDashboard = lazy(() => import('./pages/OpenShiftDashboard'))
const OpenShiftExplorer = lazy(() => import('./pages/OpenShiftExplorer'))
const OpenShiftVmConsolePage = lazy(() => import('./pages/OpenShiftVmConsolePage'))
const IntegrationsHub = lazy(() => import('./pages/IntegrationsHub'))
const PhysicalHostsPage = lazy(() => import('./pages/PhysicalHostsPage'))
const WindowsServers = lazy(() => import('./pages/WindowsServers'))
const WindowsLiveMetrics = lazy(() => import('./pages/WindowsLiveMetrics'))
const UCMDBImport = lazy(() => import('./pages/UCMDBImport'))
const Level1OpsCenter = lazy(() => import('./pages/level1/Level1OpsCenter'))
const Level1Ops = lazy(() => import('./pages/level1/Level1Ops'))
const Level1Console = lazy(() => import('./pages/level1/Level1Console'))
const Level1Jobs = lazy(() => import('./pages/level1/Level1Jobs'))
const Level1Audit = lazy(() => import('./pages/level1/Level1Audit'))
const Level1Settings = lazy(() => import('./pages/level1/Level1Settings'))
const UserManager = lazy(() => import('./pages/UserManager'))

const LinuxInfraReportsPage = lazy(() =>
  import('./pages/PlatformInfraReportsPages').then((m) => ({ default: m.LinuxInfraReportsPage }))
)
const WindowsInfraReportsPage = lazy(() =>
  import('./pages/PlatformInfraReportsPages').then((m) => ({ default: m.WindowsInfraReportsPage }))
)
const VirtInfraReportsPage = lazy(() =>
  import('./pages/PlatformInfraReportsPages').then((m) => ({ default: m.VirtInfraReportsPage }))
)
const ExadataInfraReportsPage = lazy(() =>
  import('./pages/PlatformInfraReportsPages').then((m) => ({ default: m.ExadataInfraReportsPage }))
)

const AdminDashboardPage = lazy(() =>
  import('./pages/PlatformDashboardPages').then((m) => ({ default: m.AdminDashboardPage }))
)
const LinuxDashboardPage = lazy(() =>
  import('./pages/PlatformDashboardPages').then((m) => ({ default: m.LinuxDashboardPage }))
)
const WindowsDashboardPage = lazy(() =>
  import('./pages/PlatformDashboardPages').then((m) => ({ default: m.WindowsDashboardPage }))
)

const LinuxOpsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.LinuxOpsPage }))
)
const VirtOpsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.VirtOpsPage }))
)
const WindowsOpsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.WindowsOpsPage }))
)
const LinuxEventsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.LinuxEventsPage }))
)
const VirtEventsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.VirtEventsPage }))
)
const WindowsEventsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.WindowsEventsPage }))
)
const LinuxIncidentsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.LinuxIncidentsPage }))
)
const VirtIncidentsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.VirtIncidentsPage }))
)
const WindowsIncidentsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.WindowsIncidentsPage }))
)
const LinuxAnalysisPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.LinuxAnalysisPage }))
)
const VirtAnalysisPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.VirtAnalysisPage }))
)
const WindowsAnalysisPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.WindowsAnalysisPage }))
)
const ExadataOpsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.ExadataOpsPage }))
)
const ExadataEventsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.ExadataEventsPage }))
)
const ExadataIncidentsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.ExadataIncidentsPage }))
)
const ExadataAnalysisPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.ExadataAnalysisPage }))
)
const LinuxChatPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.LinuxChatPage }))
)
const WindowsChatPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.WindowsChatPage }))
)
const VirtChatPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.VirtChatPage }))
)
const ExadataChatPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.ExadataChatPage }))
)
const OpenShiftOpsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.OpenShiftOpsPage }))
)
const OpenShiftEventsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.OpenShiftEventsPage }))
)
const OpenShiftIncidentsPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.OpenShiftIncidentsPage }))
)
const OpenShiftChatPage = lazy(() =>
  import('./pages/PlatformAiopsPages').then((m) => ({ default: m.OpenShiftChatPage }))
)

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      gcTime: 5 * 60_000,
      retry: 1,
      refetchOnWindowFocus: false,
      refetchIntervalInBackground: false,
    },
  },
})

const PageFallback: React.FC = () => (
  <div className="min-h-[40vh] flex items-center justify-center">
    <span className="w-8 h-8 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
  </div>
)

const WithLayout: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Layout>{children}</Layout>
)

const RouteErrorBoundary: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const location = useLocation()
  return (
    <ErrorBoundary resetKey={`${location.pathname}${location.search}`}>
      {children}
    </ErrorBoundary>
  )
}

const RequireAuth: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user, loading } = useAuth()
  if (loading) {
    return (
      <div className="min-h-screen bg-slate-900 flex items-center justify-center">
        <span className="w-8 h-8 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return <>{children}</>
}

const RequireAdmin: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user } = useAuth()
  if (user?.role !== 'admin' && !user?.is_admin) return <Navigate to="/" replace />
  return <>{children}</>
}

const RequireModule: React.FC<{ moduleId: string; children: React.ReactNode }> = ({ moduleId, children }) => {
  const { hasModule } = useAuth()
  if (!hasModule(moduleId)) return <Navigate to="/" replace />
  return <>{children}</>
}

const RequireAnyModule: React.FC<{ moduleIds: string[]; children: React.ReactNode }> = ({ moduleIds, children }) => {
  const { hasModule } = useAuth()
  if (!moduleIds.some(id => hasModule(id))) return <Navigate to="/" replace />
  return <>{children}</>
}

const HomeRedirect: React.FC = () => {
  const { hasModule, loading, user } = useAuth()
  if (loading) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center">
        <span className="w-8 h-8 border-2 border-slate-600 border-t-blue-500 rounded-full animate-spin" />
      </div>
    )
  }
  if (user?.role === 'admin') return <Navigate to="/dashboard" replace />
  if (hasModule('executive')) return <Navigate to="/executive" replace />
  if (hasModule('linux')) return <Navigate to="/linux/dashboard" replace />
  if (hasModule('virtualization')) return <Navigate to="/hypervisors" replace />
  if (hasModule('windows')) return <Navigate to="/windows/dashboard" replace />
  if (hasModule('exadata')) return <Navigate to="/exadata" replace />
  if (hasModule('openshift')) return <Navigate to="/openshift" replace />
  if (hasModule('ai_automation')) return <Navigate to="/chat" replace />
  if (hasModule('level1')) return <Navigate to="/level1" replace />
  if (hasModule('integrations')) return <Navigate to="/integrations" replace />
  return (
    <div className="min-h-[50vh] flex items-center justify-center text-center px-6">
      <div className="max-w-sm">
        <p className="text-slate-300 font-medium mb-1">Henüz bir modül atanmamış</p>
        <p className="text-sm text-slate-500">Erişim için lütfen sistem yöneticinizle iletişime geçin.</p>
      </div>
    </div>
  )
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrandingProvider>
      <BrowserRouter>
        <AuthProvider>
          <ThemeProvider>
          <Suspense fallback={<PageFallback />}>
          <Routes>
            <Route path="/login" element={<Login />} />

            <Route path="/terminal/:serverId" element={<TerminalPage />} />
            <Route
              path="/openshift/vms/:clusterId/:namespace/:name/console"
              element={<OpenShiftVmConsolePage />}
            />

            <Route path="/*" element={
              <RequireAuth>
                <WithLayout>
                  <RouteErrorBoundary>
                    <Suspense fallback={<PageFallback />}>
                    <Routes>
                      <Route path="/" element={<ErrorBoundary><HomeRedirect /></ErrorBoundary>} />
                      <Route path="/dashboard" element={<ErrorBoundary><AdminDashboardPage /></ErrorBoundary>} />
                      <Route path="/executive" element={<RequireModule moduleId="executive"><ErrorBoundary><ExecutiveDashboard /></ErrorBoundary></RequireModule>} />
                      <Route path="/linux/dashboard" element={<RequireModule moduleId="linux"><ErrorBoundary><LinuxDashboardPage /></ErrorBoundary></RequireModule>} />
                      <Route path="/windows/dashboard" element={<RequireModule moduleId="windows"><ErrorBoundary><WindowsDashboardPage /></ErrorBoundary></RequireModule>} />
                      <Route path="/servers" element={<RequireModule moduleId="linux"><ErrorBoundary><Servers /></ErrorBoundary></RequireModule>} />
                      <Route path="/hypervisors" element={<RequireModule moduleId="virtualization"><ErrorBoundary><Hypervisors /></ErrorBoundary></RequireModule>} />
                      <Route path="/virt/dashboard" element={<Navigate to="/hypervisors" replace />} />
                      <Route path="/virt-ops" element={<Navigate to="/virt/ops" replace />} />
                      <Route path="/linux/reports" element={<RequireModule moduleId="linux"><ErrorBoundary><LinuxInfraReportsPage /></ErrorBoundary></RequireModule>} />
                      <Route path="/linux/compare" element={<Navigate to="/linux/reports?tab=compare" replace />} />
                      <Route path="/infra-reports" element={<RequireModule moduleId="virtualization"><ErrorBoundary><VirtInfraReportsPage /></ErrorBoundary></RequireModule>} />
                      <Route path="/virt/compare" element={<Navigate to="/infra-reports?tab=compare" replace />} />
                      <Route path="/virt/reports" element={<Navigate to="/infra-reports" replace />} />

                      <Route path="/linux/ops" element={<RequirePlatformAiops platform="linux"><ErrorBoundary><LinuxOpsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/linux/chat" element={<RequirePlatformAiops platform="linux"><ErrorBoundary><LinuxChatPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/linux/events" element={<RequirePlatformAiops platform="linux"><ErrorBoundary><LinuxEventsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/linux/incidents" element={<RequirePlatformAiops platform="linux"><ErrorBoundary><LinuxIncidentsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/linux/analysis" element={<RequirePlatformAiops platform="linux"><ErrorBoundary><LinuxAnalysisPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/linux/anomalies" element={<Navigate to="/linux/events?tab=heatmap" replace />} />
                      <Route path="/linux/rca" element={<Navigate to="/linux/analysis?tab=rca" replace />} />
                      <Route path="/linux/baseline" element={<Navigate to="/linux/analysis?tab=baseline" replace />} />

                      <Route path="/virt/ops" element={<RequirePlatformAiops platform="virt"><ErrorBoundary><VirtOpsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/virt/chat" element={<RequirePlatformAiops platform="virt"><ErrorBoundary><VirtChatPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/virt/events" element={<RequirePlatformAiops platform="virt"><ErrorBoundary><VirtEventsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/virt/incidents" element={<RequirePlatformAiops platform="virt"><ErrorBoundary><VirtIncidentsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/virt/analysis" element={<RequirePlatformAiops platform="virt"><ErrorBoundary><VirtAnalysisPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/virt/anomalies" element={<Navigate to="/virt/events?tab=heatmap" replace />} />
                      <Route path="/virt/rca" element={<Navigate to="/virt/analysis?tab=rca" replace />} />
                      <Route path="/virt/baseline" element={<Navigate to="/virt/analysis?tab=baseline" replace />} />

                      <Route path="/windows/aiops/ops" element={<RequirePlatformAiops platform="windows"><ErrorBoundary><WindowsOpsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/windows/aiops/chat" element={<RequirePlatformAiops platform="windows"><ErrorBoundary><WindowsChatPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/windows/aiops/events" element={<RequirePlatformAiops platform="windows"><ErrorBoundary><WindowsEventsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/windows/aiops/incidents" element={<RequirePlatformAiops platform="windows"><ErrorBoundary><WindowsIncidentsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/windows/aiops/analysis" element={<RequirePlatformAiops platform="windows"><ErrorBoundary><WindowsAnalysisPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/windows/aiops/anomalies" element={<Navigate to="/windows/aiops/events?tab=heatmap" replace />} />
                      <Route path="/windows/aiops/rca" element={<Navigate to="/windows/aiops/analysis?tab=rca" replace />} />
                      <Route path="/windows/aiops/baseline" element={<Navigate to="/windows/aiops/analysis?tab=baseline" replace />} />

                      <Route path="/exadata" element={<RequireModule moduleId="exadata"><ErrorBoundary><ExadataDashboard /></ErrorBoundary></RequireModule>} />
                      <Route path="/exadata/chat" element={<RequirePlatformAiops platform="exadata"><ErrorBoundary><ExadataChatPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/exadata/reports" element={<RequireModule moduleId="exadata"><ErrorBoundary><ExadataInfraReportsPage /></ErrorBoundary></RequireModule>} />
                      <Route path="/exadata/ops" element={<RequirePlatformAiops platform="exadata"><ErrorBoundary><ExadataOpsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/exadata/events" element={<RequirePlatformAiops platform="exadata"><ErrorBoundary><ExadataEventsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/exadata/incidents" element={<RequirePlatformAiops platform="exadata"><ErrorBoundary><ExadataIncidentsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/exadata/analysis" element={<RequirePlatformAiops platform="exadata"><ErrorBoundary><ExadataAnalysisPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/exadata/anomalies" element={<Navigate to="/exadata/events?tab=heatmap" replace />} />
                      <Route path="/exadata/rca" element={<Navigate to="/exadata/analysis?tab=rca" replace />} />
                      <Route path="/exadata/baseline" element={<Navigate to="/exadata/analysis?tab=baseline" replace />} />

                      <Route path="/openshift" element={<RequireModule moduleId="openshift"><ErrorBoundary><OpenShiftExplorer /></ErrorBoundary></RequireModule>} />
                      <Route path="/openshift/vms" element={<RequireModule moduleId="openshift"><ErrorBoundary><OpenShiftExplorer initialSection="vms" /></ErrorBoundary></RequireModule>} />
                      <Route path="/openshift/chat" element={<RequirePlatformAiops platform="openshift"><ErrorBoundary><OpenShiftChatPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/openshift/ops" element={<RequirePlatformAiops platform="openshift"><ErrorBoundary><OpenShiftOpsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/openshift/events" element={<RequirePlatformAiops platform="openshift"><ErrorBoundary><OpenShiftEventsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/openshift/incidents" element={<RequirePlatformAiops platform="openshift"><ErrorBoundary><OpenShiftIncidentsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/openshift/analysis" element={<Navigate to="/openshift" replace />} />
                      <Route path="/openshift/rca" element={<Navigate to="/openshift" replace />} />
                      <Route path="/openshift/baseline" element={<Navigate to="/openshift?section=riskler" replace />} />

                      <Route path="/ops" element={<Navigate to="/linux/ops" replace />} />
                      <Route path="/events" element={<Navigate to="/linux/events" replace />} />
                      <Route path="/incidents" element={<Navigate to="/linux/incidents" replace />} />
                      <Route path="/anomalies" element={<Navigate to="/linux/events?tab=heatmap" replace />} />
                      <Route path="/rca" element={<Navigate to="/linux/analysis?tab=rca" replace />} />
                      <Route path="/baseline" element={<Navigate to="/linux/analysis?tab=baseline" replace />} />

                      <Route path="/windows/reports" element={<RequireModule moduleId="windows"><ErrorBoundary><WindowsInfraReportsPage /></ErrorBoundary></RequireModule>} />
                      <Route path="/windows/compare" element={<Navigate to="/windows/reports?tab=compare" replace />} />
                      <Route path="/windows" element={<RequireModule moduleId="windows"><ErrorBoundary><WindowsServers /></ErrorBoundary></RequireModule>} />
                      <Route path="/windows/live-metrics" element={<RequireModule moduleId="windows"><ErrorBoundary><WindowsLiveMetrics /></ErrorBoundary></RequireModule>} />
                      <Route path="/windows/events" element={<RequireModule moduleId="windows"><ErrorBoundary><WindowsServers /></ErrorBoundary></RequireModule>} />
                      <Route path="/windows/updates" element={<RequireModule moduleId="windows"><ErrorBoundary><WindowsServers /></ErrorBoundary></RequireModule>} />
                      <Route path="/windows/ansible" element={<RequireModule moduleId="windows"><ErrorBoundary><WindowsAnsible /></ErrorBoundary></RequireModule>} />
                      <Route path="/windows/chat" element={<Navigate to="/windows/aiops/chat" replace />} />
                      <Route path="/integrations" element={<RequireModule moduleId="integrations"><ErrorBoundary><IntegrationsHub /></ErrorBoundary></RequireModule>} />
                      <Route path="/integrations/ucmdb" element={<RequireModule moduleId="integrations"><ErrorBoundary><UCMDBImport /></ErrorBoundary></RequireModule>} />
                      <Route path="/integrations/hypervisors" element={<RequireAnyModule moduleIds={['integrations', 'virtualization']}><ErrorBoundary><Hypervisors allowInventoryEdit /></ErrorBoundary></RequireAnyModule>} />
                      <Route path="/integrations/physical-hosts" element={<RequireModule moduleId="integrations"><ErrorBoundary><PhysicalHostsPage /></ErrorBoundary></RequireModule>} />
                      <Route path="/integrations/exadata" element={<RequireAnyModule moduleIds={['integrations', 'exadata']}><ErrorBoundary><ExadataDashboard allowInventoryEdit /></ErrorBoundary></RequireAnyModule>} />
                      <Route path="/integrations/openshift" element={<RequireAnyModule moduleIds={['integrations', 'openshift']}><ErrorBoundary><OpenShiftDashboard allowInventoryEdit /></ErrorBoundary></RequireAnyModule>} />
                      <Route path="/ucmdb/import" element={<Navigate to="/integrations/ucmdb" replace />} />
                      <Route path="/level1" element={<RequireModule moduleId="level1"><ErrorBoundary><Level1OpsCenter /></ErrorBoundary></RequireModule>} />
                      <Route path="/level1/ops/*" element={<RequireModule moduleId="level1"><ErrorBoundary><Level1Ops /></ErrorBoundary></RequireModule>} />
                      <Route path="/level1/console/:id" element={<RequireModule moduleId="level1"><ErrorBoundary><Level1Console /></ErrorBoundary></RequireModule>} />
                      <Route path="/level1/jobs/*" element={<RequireModule moduleId="level1"><ErrorBoundary><Level1Jobs /></ErrorBoundary></RequireModule>} />
                      <Route path="/level1/audit" element={<RequireModule moduleId="level1"><RequireAdmin><ErrorBoundary><Level1Audit /></ErrorBoundary></RequireAdmin></RequireModule>} />
                      <Route path="/level1/settings" element={<RequireModule moduleId="level1"><RequireAdmin><ErrorBoundary><Level1Settings /></ErrorBoundary></RequireAdmin></RequireModule>} />
                      <Route path="/level1/:category" element={<Navigate to="/level1" replace />} />
                      <Route path="/modules" element={<Navigate to="/users" replace />} />
                      <Route path="/users" element={<RequireAdmin><ErrorBoundary><UserManager /></ErrorBoundary></RequireAdmin>} />
                      <Route path="/chat" element={<RequireAnyModule moduleIds={['ai_automation', 'executive']}><ErrorBoundary><AiAutomationHub /></ErrorBoundary></RequireAnyModule>} />
                      <Route path="/agent" element={<RequireModule moduleId="ai_automation"><ErrorBoundary><Agent /></ErrorBoundary></RequireModule>} />
                      <Route path="/metrics" element={<RequireModule moduleId="linux"><ErrorBoundary><LiveMetrics /></ErrorBoundary></RequireModule>} />
                      <Route path="/hypervisor-chat" element={<Navigate to="/virt/chat" replace />} />
                      <Route path="/ansible" element={<RequireModule moduleId="linux"><ErrorBoundary><Ansible /></ErrorBoundary></RequireModule>} />
                      <Route path="/mcp" element={<ErrorBoundary><McpTools /></ErrorBoundary>} />
                      <Route path="/packages" element={<RequireModule moduleId="linux"><ErrorBoundary><PackageManager /></ErrorBoundary></RequireModule>} />
                      <Route path="/repositories" element={<RequireModule moduleId="linux"><ErrorBoundary><Repositories /></ErrorBoundary></RequireModule>} />
                      <Route path="/system-update" element={<RequireModule moduleId="linux"><ErrorBoundary><SystemUpdate /></ErrorBoundary></RequireModule>} />
                      <Route path="/knowledge-base" element={<RequireModule moduleId="knowledge"><ErrorBoundary><KnowledgeBase /></ErrorBoundary></RequireModule>} />
                      <Route path="/applications" element={<RequireModule moduleId="applications"><ErrorBoundary><Applications /></ErrorBoundary></RequireModule>} />
                      <Route path="/audit" element={<RequireAdmin><ErrorBoundary><AuditLog /></ErrorBoundary></RequireAdmin>} />
                      <Route path="/settings" element={<RequireAdmin><ErrorBoundary><Settings /></ErrorBoundary></RequireAdmin>} />
                    </Routes>
                    </Suspense>
                  </RouteErrorBoundary>
                </WithLayout>
              </RequireAuth>
            } />
          </Routes>
          </Suspense>
          </ThemeProvider>
        </AuthProvider>
      </BrowserRouter>
      </BrandingProvider>
    </QueryClientProvider>
  )
}

export default App
