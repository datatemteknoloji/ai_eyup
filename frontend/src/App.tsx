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

function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <Layout>
          <Routes>
            <Route path="/" element={<Dashboard />} />
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/servers" element={<Servers />} />
            <Route path="/hypervisors" element={<Hypervisors />} />
            <Route path="/chat" element={<Chat />} />
            <Route path="/metrics" element={<LiveMetrics />} />
            <Route path="/events" element={<Events />} />
            <Route path="/incidents" element={<Incidents />} />
            <Route path="/ansible" element={<Ansible />} />
            <Route path="/mcp" element={<McpTools />} />
            <Route path="/settings" element={<Settings />} />
          </Routes>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
