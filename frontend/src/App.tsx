import { BrowserRouter, Routes, Route } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import Dashboard from './pages/Dashboard'
import Servers from './pages/Servers'
import Hypervisors from './pages/Hypervisors'
import Chat from './pages/Chat'
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

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Routes>
          {/* Terminal — Layout YOK, tam ekran popup pencere */}
          <Route path="/terminal/:serverId" element={<TerminalPage />} />

          {/* Diğer tüm sayfalar — Layout var */}
          <Route path="/*" element={
            <WithLayout>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/dashboard" element={<Dashboard />} />
                <Route path="/servers" element={<Servers />} />
                <Route path="/hypervisors" element={<Hypervisors />} />
                <Route path="/chat" element={<Chat />} />
                <Route path="/metrics" element={<LiveMetrics />} />
                <Route path="/events" element={<Events />} />
                <Route path="/incidents" element={<Incidents />} />
                <Route path="/anomalies" element={<AnomalyDetection />} />
                <Route path="/ansible" element={<Ansible />} />
                <Route path="/mcp" element={<McpTools />} />
                <Route path="/packages" element={<PackageManager />} />
                <Route path="/repositories" element={<Repositories />} />
                <Route path="/system-update" element={<SystemUpdate />} />
                <Route path="/settings" element={<Settings />} />
              </Routes>
            </WithLayout>
          } />
        </Routes>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
