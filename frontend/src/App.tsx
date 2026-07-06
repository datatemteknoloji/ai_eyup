import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider, useAuth } from './auth/AuthContext'
import ErrorBoundary from './components/ErrorBoundary'
import Login from './pages/Login'
import AuditLog from './pages/AuditLog'
import Servers from './pages/Servers'
import Hypervisors from './pages/Hypervisors'
import Agent from './pages/Agent'
import AiAutomationHub from './pages/AiAutomationHub'
import LiveMetrics from './pages/LiveMetrics'
import Settings from './pages/Settings'
import McpTools from './pages/McpTools'
import Ansible from './pages/Ansible'
import WindowsAnsible from './pages/WindowsAnsible'
import PackageManager from './pages/PackageManager'
import Repositories from './pages/Repositories'
import SystemUpdate from './pages/SystemUpdate'
import TerminalPage from './pages/TerminalPage'
import {
  LinuxInfraReportsPage, WindowsInfraReportsPage,
  VirtInfraReportsPage, ExadataInfraReportsPage,
} from './pages/PlatformInfraReportsPages'
import ExecutiveDashboard from './pages/ExecutiveDashboard'
import ExadataDashboard from './pages/ExadataDashboard'
import IntegrationsHub from './pages/IntegrationsHub'
import PhysicalHostsPage from './pages/PhysicalHostsPage'
import WindowsServers from './pages/WindowsServers'
import WindowsLiveMetrics from './pages/WindowsLiveMetrics'
import UCMDBImport from './pages/UCMDBImport'
import Level1Ops from './pages/Level1Ops'
import UserManager from './pages/UserManager'
import Layout from './components/Layout'
import {
  AdminDashboardPage, LinuxDashboardPage, WindowsDashboardPage,
} from './pages/PlatformDashboardPages'
import { RequirePlatformAiops } from './components/RequirePlatformAiops'
import {
  LinuxOpsPage, VirtOpsPage, WindowsOpsPage,
  LinuxEventsPage, VirtEventsPage, WindowsEventsPage,
  LinuxIncidentsPage, VirtIncidentsPage, WindowsIncidentsPage,
  LinuxAnalysisPage, VirtAnalysisPage, WindowsAnalysisPage,
  ExadataOpsPage, ExadataEventsPage, ExadataIncidentsPage, ExadataAnalysisPage,
} from './pages/PlatformAiopsPages'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,          // 30 sn önce fetch edilmişse yeniden istek atma
      gcTime: 5 * 60_000,         // 5 dk cache'de tut
      retry: 1,                   // başarısızlıkta sadece 1 kez dene
      refetchOnWindowFocus: false, // sekme odağında otomatik refetch yapma
    },
  },
})

// Layout wrapper — terminal dışında tüm sayfalara sidebar/header ekler
const WithLayout: React.FC<{ children: React.ReactNode }> = ({ children }) => (
  <Layout>{children}</Layout>
)

// Oturum koruması — giriş yoksa /login'e yönlendir
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

// Admin koruması — admin değilse ana sayfaya yönlendir (menüden gizli olsa da URL ile erişimi engeller)
const RequireAdmin: React.FC<{ children: React.ReactNode }> = ({ children }) => {
  const { user } = useAuth()
  if (user?.role !== 'admin') return <Navigate to="/" replace />
  return <>{children}</>
}

// Modül koruması — kullanıcının ilgili modüle erişimi yoksa ana sayfaya yönlendir (menüden gizli olsa da URL ile erişimi engeller)
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

// Ana sayfa — admin genel dashboard, diğerleri modül dashboard'una
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
  if (hasModule('linux')) return <Navigate to="/linux/dashboard" replace />
  if (hasModule('virtualization')) return <Navigate to="/hypervisors" replace />
  if (hasModule('windows')) return <Navigate to="/windows/dashboard" replace />
  if (hasModule('aiops')) return <Navigate to="/linux/ops" replace />
  if (hasModule('ai_automation')) return <Navigate to="/chat" replace />
  if (hasModule('level1')) return <Navigate to="/level1" replace />
  if (hasModule('integrations')) return <Navigate to="/integrations" replace />
  return <Navigate to="/audit" replace />
}

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            {/* Login — Layout YOK */}
            <Route path="/login" element={<Login />} />

            {/* Terminal — Layout YOK, tam ekran popup pencere */}
            <Route path="/terminal/:serverId" element={<TerminalPage />} />

            {/* Diğer tüm sayfalar — oturum + Layout var */}
            <Route path="/*" element={
              <RequireAuth>
                <WithLayout>
                  <ErrorBoundary>
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
                      <Route path="/infra-reports" element={<RequireModule moduleId="virtualization"><ErrorBoundary><VirtInfraReportsPage /></ErrorBoundary></RequireModule>} />
                      <Route path="/virt/reports" element={<Navigate to="/infra-reports" replace />} />

                      {/* Linux AIOps */}
                      <Route path="/linux/ops" element={<RequirePlatformAiops platform="linux"><ErrorBoundary><LinuxOpsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/linux/events" element={<RequirePlatformAiops platform="linux"><ErrorBoundary><LinuxEventsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/linux/incidents" element={<RequirePlatformAiops platform="linux"><ErrorBoundary><LinuxIncidentsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/linux/analysis" element={<RequirePlatformAiops platform="linux"><ErrorBoundary><LinuxAnalysisPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/linux/anomalies" element={<Navigate to="/linux/events?tab=heatmap" replace />} />
                      <Route path="/linux/rca" element={<Navigate to="/linux/analysis?tab=rca" replace />} />
                      <Route path="/linux/baseline" element={<Navigate to="/linux/analysis?tab=baseline" replace />} />

                      {/* Sanallaştırma AIOps */}
                      <Route path="/virt/ops" element={<RequirePlatformAiops platform="virt"><ErrorBoundary><VirtOpsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/virt/events" element={<RequirePlatformAiops platform="virt"><ErrorBoundary><VirtEventsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/virt/incidents" element={<RequirePlatformAiops platform="virt"><ErrorBoundary><VirtIncidentsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/virt/analysis" element={<RequirePlatformAiops platform="virt"><ErrorBoundary><VirtAnalysisPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/virt/anomalies" element={<Navigate to="/virt/events?tab=heatmap" replace />} />
                      <Route path="/virt/rca" element={<Navigate to="/virt/analysis?tab=rca" replace />} />
                      <Route path="/virt/baseline" element={<Navigate to="/virt/analysis?tab=baseline" replace />} />

                      {/* Windows AIOps */}
                      <Route path="/windows/aiops/ops" element={<RequirePlatformAiops platform="windows"><ErrorBoundary><WindowsOpsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/windows/aiops/events" element={<RequirePlatformAiops platform="windows"><ErrorBoundary><WindowsEventsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/windows/aiops/incidents" element={<RequirePlatformAiops platform="windows"><ErrorBoundary><WindowsIncidentsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/windows/aiops/analysis" element={<RequirePlatformAiops platform="windows"><ErrorBoundary><WindowsAnalysisPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/windows/aiops/anomalies" element={<Navigate to="/windows/aiops/events?tab=heatmap" replace />} />
                      <Route path="/windows/aiops/rca" element={<Navigate to="/windows/aiops/analysis?tab=rca" replace />} />
                      <Route path="/windows/aiops/baseline" element={<Navigate to="/windows/aiops/analysis?tab=baseline" replace />} />

                      {/* Exadata */}
                      <Route path="/exadata" element={<RequireModule moduleId="exadata"><ErrorBoundary><ExadataDashboard /></ErrorBoundary></RequireModule>} />
                      <Route path="/exadata/chat" element={<Navigate to="/chat?platform=exadata" replace />} />
                      <Route path="/exadata/reports" element={<RequireModule moduleId="exadata"><ErrorBoundary><ExadataInfraReportsPage /></ErrorBoundary></RequireModule>} />
                      <Route path="/exadata/ops" element={<RequirePlatformAiops platform="exadata"><ErrorBoundary><ExadataOpsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/exadata/events" element={<RequirePlatformAiops platform="exadata"><ErrorBoundary><ExadataEventsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/exadata/incidents" element={<RequirePlatformAiops platform="exadata"><ErrorBoundary><ExadataIncidentsPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/exadata/analysis" element={<RequirePlatformAiops platform="exadata"><ErrorBoundary><ExadataAnalysisPage /></ErrorBoundary></RequirePlatformAiops>} />
                      <Route path="/exadata/anomalies" element={<Navigate to="/exadata/events?tab=heatmap" replace />} />
                      <Route path="/exadata/rca" element={<Navigate to="/exadata/analysis?tab=rca" replace />} />
                      <Route path="/exadata/baseline" element={<Navigate to="/exadata/analysis?tab=baseline" replace />} />

                      {/* Eski AIOps yolları → Linux AIOps */}
                      <Route path="/ops" element={<Navigate to="/linux/ops" replace />} />
                      <Route path="/events" element={<Navigate to="/linux/events" replace />} />
                      <Route path="/incidents" element={<Navigate to="/linux/incidents" replace />} />
                      <Route path="/anomalies" element={<Navigate to="/linux/events?tab=heatmap" replace />} />
                      <Route path="/rca" element={<Navigate to="/linux/analysis?tab=rca" replace />} />
                      <Route path="/baseline" element={<Navigate to="/linux/analysis?tab=baseline" replace />} />

                      <Route path="/windows/reports" element={<RequireModule moduleId="windows"><ErrorBoundary><WindowsInfraReportsPage /></ErrorBoundary></RequireModule>} />
                      <Route path="/windows" element={<RequireModule moduleId="windows"><ErrorBoundary><WindowsServers /></ErrorBoundary></RequireModule>} />
                      <Route path="/windows/live-metrics" element={<RequireModule moduleId="windows"><ErrorBoundary><WindowsLiveMetrics /></ErrorBoundary></RequireModule>} />
                      <Route path="/windows/events" element={<RequireModule moduleId="windows"><ErrorBoundary><WindowsServers /></ErrorBoundary></RequireModule>} />
                      <Route path="/windows/updates" element={<RequireModule moduleId="windows"><ErrorBoundary><WindowsServers /></ErrorBoundary></RequireModule>} />
                      <Route path="/windows/ansible" element={<RequireModule moduleId="windows"><ErrorBoundary><WindowsAnsible /></ErrorBoundary></RequireModule>} />
                      <Route path="/windows/chat" element={<Navigate to="/chat?platform=windows" replace />} />
                      <Route path="/integrations" element={<RequireModule moduleId="integrations"><ErrorBoundary><IntegrationsHub /></ErrorBoundary></RequireModule>} />
                      <Route path="/integrations/ucmdb" element={<RequireModule moduleId="integrations"><ErrorBoundary><UCMDBImport /></ErrorBoundary></RequireModule>} />
                      <Route path="/integrations/hypervisors" element={<RequireAnyModule moduleIds={['integrations', 'virtualization']}><ErrorBoundary><Hypervisors allowInventoryEdit /></ErrorBoundary></RequireAnyModule>} />
                      <Route path="/integrations/physical-hosts" element={<RequireModule moduleId="integrations"><ErrorBoundary><PhysicalHostsPage /></ErrorBoundary></RequireModule>} />
                      <Route path="/integrations/exadata" element={<RequireAnyModule moduleIds={['integrations', 'exadata']}><ErrorBoundary><ExadataDashboard allowInventoryEdit /></ErrorBoundary></RequireAnyModule>} />
                      <Route path="/ucmdb/import" element={<Navigate to="/integrations/ucmdb" replace />} />
                      <Route path="/level1" element={<RequireModule moduleId="level1"><ErrorBoundary><Level1Ops /></ErrorBoundary></RequireModule>} />
                      <Route path="/level1/:category" element={<RequireModule moduleId="level1"><ErrorBoundary><Level1Ops /></ErrorBoundary></RequireModule>} />
                      <Route path="/modules" element={<Navigate to="/users" replace />} />
                      <Route path="/users" element={<RequireAdmin><ErrorBoundary><UserManager /></ErrorBoundary></RequireAdmin>} />
                      <Route path="/chat" element={<RequireModule moduleId="ai_automation"><ErrorBoundary><AiAutomationHub /></ErrorBoundary></RequireModule>} />
                      <Route path="/agent" element={<RequireModule moduleId="ai_automation"><ErrorBoundary><Agent /></ErrorBoundary></RequireModule>} />
                      <Route path="/metrics" element={<RequireModule moduleId="linux"><ErrorBoundary><LiveMetrics /></ErrorBoundary></RequireModule>} />
                      <Route path="/hypervisor-chat" element={<Navigate to="/infra-reports" replace />} />
                      <Route path="/ansible" element={<RequireModule moduleId="linux"><ErrorBoundary><Ansible /></ErrorBoundary></RequireModule>} />
                      <Route path="/mcp" element={<ErrorBoundary><McpTools /></ErrorBoundary>} />
                      <Route path="/packages" element={<RequireModule moduleId="linux"><ErrorBoundary><PackageManager /></ErrorBoundary></RequireModule>} />
                      <Route path="/repositories" element={<RequireModule moduleId="linux"><ErrorBoundary><Repositories /></ErrorBoundary></RequireModule>} />
                      <Route path="/system-update" element={<RequireModule moduleId="linux"><ErrorBoundary><SystemUpdate /></ErrorBoundary></RequireModule>} />
                      <Route path="/audit" element={<ErrorBoundary><AuditLog /></ErrorBoundary>} />
                      <Route path="/settings" element={<RequireAdmin><ErrorBoundary><Settings /></ErrorBoundary></RequireAdmin>} />
                    </Routes>
                  </ErrorBoundary>
                </WithLayout>
              </RequireAuth>
            } />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
