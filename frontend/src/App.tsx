import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider, useAuth } from './auth/AuthContext'
import ErrorBoundary from './components/ErrorBoundary'
import Login from './pages/Login'
import AuditLog from './pages/AuditLog'
import Dashboard from './pages/Dashboard'
import Servers from './pages/Servers'
import Hypervisors from './pages/Hypervisors'
import Chat from './pages/Chat'
import Agent from './pages/Agent'
import LiveMetrics from './pages/LiveMetrics'
import Settings from './pages/Settings'
import Events from './pages/Events'
import Incidents from './pages/Incidents'
import McpTools from './pages/McpTools'
import Ansible from './pages/Ansible'
import AnomalyDetection from './pages/AnomalyDetection'
import PackageManager from './pages/PackageManager'
import Repositories from './pages/Repositories'
import SystemUpdate from './pages/SystemUpdate'
import TerminalPage from './pages/TerminalPage'
import RootCauseAnalysis from './pages/RootCauseAnalysis'
import BaselineManager from './pages/BaselineManager'
import Layout from './components/Layout'

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
                      <Route path="/" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
                      <Route path="/dashboard" element={<ErrorBoundary><Dashboard /></ErrorBoundary>} />
                      <Route path="/servers" element={<ErrorBoundary><Servers /></ErrorBoundary>} />
                      <Route path="/hypervisors" element={<ErrorBoundary><Hypervisors /></ErrorBoundary>} />
                      <Route path="/chat" element={<ErrorBoundary><Chat /></ErrorBoundary>} />
                      <Route path="/agent" element={<ErrorBoundary><Agent /></ErrorBoundary>} />
                      <Route path="/metrics" element={<ErrorBoundary><LiveMetrics /></ErrorBoundary>} />
                      <Route path="/events" element={<ErrorBoundary><Events /></ErrorBoundary>} />
                      <Route path="/incidents" element={<ErrorBoundary><Incidents /></ErrorBoundary>} />
                      <Route path="/anomalies" element={<ErrorBoundary><AnomalyDetection /></ErrorBoundary>} />
                      <Route path="/rca" element={<ErrorBoundary><RootCauseAnalysis /></ErrorBoundary>} />
                      <Route path="/baseline" element={<ErrorBoundary><BaselineManager /></ErrorBoundary>} />
                      <Route path="/ansible" element={<ErrorBoundary><Ansible /></ErrorBoundary>} />
                      <Route path="/mcp" element={<ErrorBoundary><McpTools /></ErrorBoundary>} />
                      <Route path="/packages" element={<ErrorBoundary><PackageManager /></ErrorBoundary>} />
                      <Route path="/repositories" element={<ErrorBoundary><Repositories /></ErrorBoundary>} />
                      <Route path="/system-update" element={<ErrorBoundary><SystemUpdate /></ErrorBoundary>} />
                      <Route path="/audit" element={<ErrorBoundary><AuditLog /></ErrorBoundary>} />
                      <Route path="/settings" element={<ErrorBoundary><Settings /></ErrorBoundary>} />
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
