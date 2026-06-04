import { BrowserRouter, Routes, Route, Navigate } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { AuthProvider, useAuth } from './auth/AuthContext'
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
                  <Routes>
                    <Route path="/" element={<Dashboard />} />
                    <Route path="/dashboard" element={<Dashboard />} />
                    <Route path="/servers" element={<Servers />} />
                    <Route path="/hypervisors" element={<Hypervisors />} />
                    <Route path="/chat" element={<Chat />} />
                    <Route path="/agent" element={<Agent />} />
                    <Route path="/metrics" element={<LiveMetrics />} />
                    <Route path="/events" element={<Events />} />
                    <Route path="/incidents" element={<Incidents />} />
                    <Route path="/anomalies" element={<AnomalyDetection />} />
                    <Route path="/ansible" element={<Ansible />} />
                    <Route path="/mcp" element={<McpTools />} />
                    <Route path="/packages" element={<PackageManager />} />
                    <Route path="/repositories" element={<Repositories />} />
                    <Route path="/system-update" element={<SystemUpdate />} />
                    <Route path="/audit" element={<AuditLog />} />
                    <Route path="/settings" element={<Settings />} />
                  </Routes>
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
