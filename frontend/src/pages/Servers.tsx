import React, { useState, useEffect, lazy, Suspense } from 'react'
const SshTerminalModal = lazy(() => import('../components/SshTerminal'))
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

interface Server {
  id: number
  name: string
  hostname: string
  ip_address: string
  status: string
  os_type: string
  os_version: string
  os_release_id: string
  os_version_id: string
  kernel_version: string
  server_type: string
  cpu_cores: number
  memory_gb: number
  ai_ready: boolean
  hypervisor_id: number | null
  hypervisor_name: string | null
  connection_config: any
  node_exporter?: {
    installed: boolean
    running: boolean
  }
}

// ─── Toplu Node Exporter Kur ──────────────────────────────────────────────────
const BulkNodeExporterButton: React.FC<{ servers: Server[]; onDone: () => void }> = ({ servers, onDone }) => {
  const [loading, setLoading] = React.useState(false)
  const [result, setResult]   = React.useState<{success: number; failed: number} | null>(null)

  const notRunning = servers.filter(s => s.status === 'ONLINE' && s.ai_ready && !s.node_exporter?.running)

  const handleClick = async () => {
    if (notRunning.length === 0) { alert('Node Exporter çalışmayan aktif AI-Ready sunucu yok'); return }
    if (!confirm(`${notRunning.length} sunucuya Node Exporter kurulacak/başlatılacak. Devam?`)) return

    setLoading(true); setResult(null)
    try {
      const r = await fetch(`${API_BASE_URL}/monitoring/node-exporter/bulk-install`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(notRunning.map(s => s.id)),
      })
      if (r.ok) {
        const d = await r.json()
        setResult({ success: d.success, failed: d.failed })
        onDone()
        setTimeout(() => setResult(null), 8000)
      }
    } finally { setLoading(false) }
  }

  return (
    <button
      onClick={handleClick}
      disabled={loading || notRunning.length === 0}
      className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-cyan-600 to-cyan-700 text-white rounded-lg hover:from-cyan-500 hover:to-cyan-600 transition-all disabled:opacity-50"
      title={`Node Exporter çalışmayan ${notRunning.length} AI-Ready sunucuya toplu kur`}
    >
      {loading ? (
        <>
          <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
          <span>Kuruluyor... ({notRunning.length})</span>
        </>
      ) : result ? (
        <span>✓ {result.success} başarılı{result.failed > 0 ? ` · ${result.failed} hata` : ''}</span>
      ) : (
        <>
          <span>📊</span>
          <span>Toplu Metrik Kur {notRunning.length > 0 ? `(${notRunning.length})` : ''}</span>
        </>
      )}
    </button>
  )
}

// ─── AI Ready Güncelle Butonu ─────────────────────────────────────────────────
const AiReadyUpdateButton: React.FC<{ onDone: () => void }> = ({ onDone }) => {
  const [loading, setLoading] = React.useState(false)
  const [result, setResult]   = React.useState<{ai_ready: number; not_ready: number; tested: number} | null>(null)

  const handleClick = async () => {
    if (!confirm(
      'Tüm sunucularda SSH bağlantısı test edilecek.\n' +
      'Global Credential ile bağlanabilen sunucular → AI Ready = ✅\n' +
      'Bağlanamayanlar → AI Ready = ❌\n\nDevam?'
    )) return

    setLoading(true); setResult(null)
    try {
      const r = await fetch(`${API_BASE_URL}/servers/update-ai-ready`, { method: 'POST' })
      if (r.ok) {
        const d = await r.json()
        setResult(d)
        onDone()
        setTimeout(() => setResult(null), 8000)
      }
    } finally { setLoading(false) }
  }

  return (
    <button
      onClick={handleClick}
      disabled={loading}
      className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-indigo-600 to-indigo-700 text-white rounded-lg hover:from-indigo-500 hover:to-indigo-600 transition-all disabled:opacity-50"
      title="Global Credential ile SSH testi yaparak AI Ready durumunu güncelle"
    >
      {loading ? (
        <>
          <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
          <span>Test ediliyor...</span>
        </>
      ) : result ? (
        <span>🤖 {result.ai_ready} AI Ready · {result.not_ready} bağlanamadı</span>
      ) : (
        <>
          <span>🤖</span>
          <span>AI Ready Güncelle</span>
        </>
      )}
    </button>
  )
}

// ─── OS Bilgisi Yenile Butonu ──────────────────────────────────────────────────
const OsRefreshButton: React.FC<{ servers: Server[]; onDone: () => void }> = ({ servers, onDone }) => {
  const [loading, setLoading] = React.useState(false)
  const [result, setResult]   = React.useState<{updated: number; failed: number} | null>(null)

  const handleClick = async () => {
    // AI ready veya tümü?
    const aiReadyIds = servers.filter(s => s.ai_ready).map(s => s.id)
    const ids = aiReadyIds.length > 0 ? aiReadyIds : servers.map(s => s.id)

    const confirmed = window.confirm(
      aiReadyIds.length > 0
        ? `${aiReadyIds.length} AI-Ready sunucuya SSH bağlanıp OS/Kernel bilgisi güncellenecek. Devam?`
        : `Tüm ${ids.length} sunucuya SSH bağlanıp OS bilgisi güncellenecek. Devam?`
    )
    if (!confirmed) return

    setLoading(true); setResult(null)
    try {
      const r = await fetch('/api/v1/servers/refresh-os-info', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server_ids: ids }),
      })
      if (r.ok) {
        const d = await r.json()
        setResult(d)
        onDone()
        setTimeout(() => setResult(null), 5000)
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <button
      onClick={handleClick}
      disabled={loading}
      className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-purple-600 to-purple-700 text-white rounded-lg hover:from-purple-500 hover:to-purple-600 transition-all disabled:opacity-50"
      title="AI-Ready sunucuların OS/Kernel bilgisini SSH ile güncelle"
    >
      {loading ? (
        <>
          <div className="w-4 h-4 border-2 border-white/40 border-t-white rounded-full animate-spin" />
          <span>OS Güncelleniyor...</span>
        </>
      ) : result ? (
        <span>✓ {result.updated} güncellendi {result.failed > 0 ? `· ${result.failed} hata` : ''}</span>
      ) : (
        <>
          <span>💻</span>
          <span>OS Bilgisini Yenile</span>
        </>
      )}
    </button>
  )
}

const NODE_EXPORTER_STEP_LABELS = [
  { id: 'connection', label: 'SSH bağlantı testi' },
  { id: 'status_check', label: 'Node Exporter durum kontrolü' },
  { id: 'download', label: 'Binary indirme / dağıtım' },
  { id: 'install', label: 'Sunucuya kurulum' },
  { id: 'systemd_service', label: 'Systemd servisi oluşturma' },
  { id: 'start_service', label: 'Servisi başlatma' },
  { id: 'final_check', label: 'Son durum kontrolü' },
  { id: 'prometheus', label: 'Prometheus hedefi ekleme' }
]

interface MetricsSummary {
  has_node_exporter: boolean
  source?: string | null
  power_state?: string | null
  cpu_percent: number | null
  mem_percent: number | null
  disk_percent: number | null
  load1: number | null
  load5: number | null
  uptime_seconds: number | null
  mem_total_gb: number | null
  mem_used_gb: number | null
  disk_total_gb: number | null
  disk_avail_gb: number | null
  cpu_num?: number | null
}

interface EventGroup {
  event_type: string
  title: string
  severity: string
  server_id: number | null
  server_name: string | null
  event_ids: number[]
  count: number
  latest_created_at: string | null
  resolved?: boolean
  is_acknowledged?: boolean
}

function fmtUptime(seconds: number | null): string {
  if (!seconds) return '-'
  const d = Math.floor(seconds / 86400)
  const h = Math.floor((seconds % 86400) / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  if (d > 0) return `${d}g ${h}s`
  if (h > 0) return `${h}s ${m}dk`
  return `${m}dk`
}

function MetricBar({ label, value, colorClass }: { label: string; value: number | null; colorClass: string }) {
  const v = value ?? 0
  return (
    <div>
      <div className="flex justify-between text-xs text-slate-400 mb-1">
        <span>{label}</span>
        <span className={value !== null ? 'text-white font-medium' : 'text-slate-600'}>{value !== null ? `${value}%` : 'N/A'}</span>
      </div>
      <div className="w-full bg-slate-700 rounded-full h-2">
        <div className={`h-2 rounded-full transition-all ${colorClass}`} style={{ width: `${Math.min(v, 100)}%` }} />
      </div>
    </div>
  )
}

const SCOLOR: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  emergency: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  warning: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  info: 'bg-blue-500/20 text-blue-400 border-blue-500/30',
  error: 'bg-orange-500/20 text-orange-400 border-orange-500/30',
}

export function ServerDetailDrawer({ server, onClose }: { server: Server; onClose: () => void }) {
  const [tab, setTab] = useState<'info' | 'events' | 'perf'>('info')
  const [analyzeText, setAnalyzeText] = useState('')
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const analyzeAbort = React.useRef<AbortController | null>(null)

  const { data: metrics, isLoading: metricsLoading } = useQuery<MetricsSummary>({
    queryKey: ['server-metrics-summary', server.id],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/servers/${server.id}/metrics-summary`)
      if (!res.ok) throw new Error('metrics error')
      return res.json()
    },
    refetchInterval: 15000,
    enabled: tab === 'perf',
  })

  const { data: eventsData, isLoading: eventsLoading } = useQuery<{ total: number; groups: EventGroup[] }>({
    queryKey: ['server-events', server.id],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/events/grouped?server_id=${server.id}&resolved=false&limit=30&sort_by=latest_created_at&sort_dir=desc`)
      if (!res.ok) return { total: 0, groups: [] }
      return res.json()
    },
    refetchInterval: 30000,
    enabled: tab === 'events',
  })

  const startAnalyze = async () => {
    analyzeAbort.current?.abort()
    const ctrl = new AbortController()
    analyzeAbort.current = ctrl
    setAnalyzeText('')
    setIsAnalyzing(true)
    const model = localStorage.getItem('chat_selected_model') || 'llama3.2:3b'
    const metricsCtx = metrics ? `CPU: ${metrics.cpu_percent ?? 'N/A'}%, RAM: ${metrics.mem_percent ?? 'N/A'}%, Disk: ${metrics.disk_percent ?? 'N/A'}%, Load: ${metrics.load1 ?? 'N/A'}` : ''
    const prompt = `${server.name} (${server.ip_address}) sunucusunun genel durumunu analiz et. ${metricsCtx ? `Anlık metrikler: ${metricsCtx}.` : ''} Bu sunucuyla ilgili dikkat edilmesi gereken noktaları, önerileri ve varsa performans iyileştirmelerini belirt.`
    try {
      const res = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: prompt, use_rag: true, model }),
        signal: ctrl.signal,
      })
      if (!res.ok || !res.body) throw new Error()
      const reader = res.body.getReader()
      const dec = new TextDecoder()
      let buf = '', acc = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += dec.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const chunk = JSON.parse(line.slice(6))
            if (chunk.token) { acc += chunk.token; setAnalyzeText(acc) }
            if (chunk.done) setIsAnalyzing(false)
          } catch {}
        }
      }
    } catch (e: any) {
      if (e?.name !== 'AbortError') setAnalyzeText('❌ Analiz başarısız.')
    } finally { setIsAnalyzing(false) }
  }

  const sshUser = server.connection_config?.username
  const cpuColor = (v: number | null) => v === null ? 'bg-slate-600' : v > 85 ? 'bg-red-500' : v > 60 ? 'bg-yellow-500' : 'bg-green-500'
  const memColor = (v: number | null) => v === null ? 'bg-slate-600' : v > 85 ? 'bg-red-500' : v > 70 ? 'bg-yellow-500' : 'bg-blue-500'
  const diskColor = (v: number | null) => v === null ? 'bg-slate-600' : v > 85 ? 'bg-red-500' : v > 70 ? 'bg-yellow-500' : 'bg-purple-500'

  return (
    <div className="fixed inset-0 z-50 flex">
      <div className="flex-1 bg-black/50 backdrop-blur-sm" onClick={onClose} />
      <div className="w-full max-w-xl bg-slate-900 border-l border-slate-700 flex flex-col shadow-2xl overflow-hidden">
        {/* Header */}
        <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-700 bg-slate-800/50">
          <div className={`w-10 h-10 rounded-lg flex items-center justify-center flex-shrink-0 ${server.status === 'ONLINE' ? 'bg-gradient-to-br from-green-500 to-green-600' : 'bg-gradient-to-br from-slate-600 to-slate-700'}`}>
            <span className="text-white text-lg">🖥️</span>
          </div>
          <div className="flex-1 min-w-0">
            <h2 className="text-white font-semibold text-base truncate">{server.name}</h2>
            <div className="flex items-center gap-2 mt-0.5 flex-wrap">
              <p className="text-slate-400 text-xs font-mono">{server.ip_address}</p>
              {server.hypervisor_name && (
                <span className="text-xs text-slate-500 bg-slate-700/50 px-1.5 py-0.5 rounded">
                  ☁ {server.hypervisor_name}
                </span>
              )}
            </div>
          </div>
          <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${server.status === 'ONLINE' ? 'bg-green-500/20 text-green-400 border-green-500/30' : 'bg-red-500/20 text-red-400 border-red-500/30'}`}>
            ● {server.status}
          </span>
          {/* SSH butonu detay headerında */}
          {server.status === 'ONLINE' && server.ip_address && (
            <button
              onClick={() => {
                const w = window.open(
                  `/terminal/${server.id}?name=${encodeURIComponent(server.name)}&ip=${encodeURIComponent(server.ip_address)}`,
                  `ssh-${server.id}`,
                  'width=1200,height=700,resizable=yes,scrollbars=no,menubar=no,toolbar=no,location=no,status=no'
                )
                if (!w) alert('Popup engellendi — tarayıcı ayarlarınızdan popup iznini açın.')
              }}
              className="flex items-center gap-1 px-2.5 py-1 text-xs bg-green-700/40 hover:bg-green-700 text-green-300 rounded-lg transition-colors font-mono flex-shrink-0"
              title="SSH Terminal"
            >
              <span>⌨</span> SSH
            </button>
          )}
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl leading-none flex-shrink-0">&times;</button>
        </div>

        {/* Tabs */}
        <div className="flex border-b border-slate-700 bg-slate-800/30">
          {([['info', '📋 Bilgi'], ['perf', '📈 Performans'], ['events', '🔔 Eventler']] as const).map(([id, label]) => (
            <button key={id} onClick={() => setTab(id)}
              className={`px-4 py-2.5 text-xs font-medium transition-colors border-b-2 ${tab === id ? 'border-blue-500 text-blue-400' : 'border-transparent text-slate-400 hover:text-white'}`}>
              {label}
            </button>
          ))}
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-5 space-y-4">

          {/* ── INFO TAB ── */}
          {tab === 'info' && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                {[
                  ['Sunucu Adı', server.name],
                  ['IP Adresi', server.ip_address || '-'],
                  ['Hostname', server.hostname || '-'],
                  ...(server.hypervisor_name ? [['Hypervisor', `☁ ${server.hypervisor_name}`]] : []),
                  ['Tip', server.server_type || '-'],
                  ['OS Dağıtım', server.os_release_id ? server.os_release_id.toUpperCase() : (server.os_type || '-')],
                  ['OS Sürüm', server.os_version_id ? `${server.os_version_id} — ${server.os_version || ''}` : (server.os_version || '-')],
                  ['Kernel', server.kernel_version || '-'],
                  ['CPU', server.cpu_cores ? `${server.cpu_cores} çekirdek` : '-'],
                  ['RAM', server.memory_gb ? `${server.memory_gb} GB` : '-'],
                  ['SSH Kullanıcı', sshUser || '-'],
                  ['AI Ready', '__AI_READY_TOGGLE__'],
                  ['Node Exporter', server.node_exporter?.running ? '✅ Çalışıyor' : server.node_exporter?.installed ? '⚠️ Kurulu/Durdurulmuş' : '❌ Kurulu Değil'],
                ].map(([label, value]) => (
                  <div key={label} className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50">
                    <p className="text-[10px] text-slate-500 uppercase tracking-wide mb-0.5">{label}</p>
                    {value === '__AI_READY_TOGGLE__' ? (
                      <div className="flex items-center justify-between mt-0.5">
                        <span className={`text-sm font-medium ${server.ai_ready ? 'text-green-400' : 'text-slate-400'}`}>
                          {server.ai_ready ? '✅ AI Ready' : '❌ AI Ready Değil'}
                        </span>
                        <button
                          onClick={async () => {
                            const newVal = !server.ai_ready
                            await fetch(`${API_BASE_URL}/servers/${server.id}`, {
                              method: 'PUT',
                              headers: { 'Content-Type': 'application/json' },
                              body: JSON.stringify({ ai_ready: newVal }),
                            })
                            onClose()
                          }}
                          className={`text-xs px-2 py-0.5 rounded-lg border transition-colors ${
                            server.ai_ready
                              ? 'text-red-400 border-red-500/40 hover:bg-red-500/10'
                              : 'text-green-400 border-green-500/40 hover:bg-green-500/10'
                          }`}
                        >
                          {server.ai_ready ? 'Kaldır' : 'Ekle'}
                        </button>
                      </div>
                    ) : (
                      <p className="text-sm text-white font-medium break-all">{value}</p>
                    )}
                  </div>
                ))}
              </div>

              {/* AI Analiz */}
              <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4">
                <div className="flex items-center justify-between mb-3">
                  <h3 className="text-sm font-medium text-white">🤖 AI Analiz</h3>
                  <button onClick={startAnalyze} disabled={isAnalyzing}
                    className="px-3 py-1 text-xs bg-purple-600/30 text-purple-300 border border-purple-500/30 rounded hover:bg-purple-600/40 disabled:opacity-50">
                    {isAnalyzing ? '⏳ Analiz ediliyor...' : analyzeText ? '🔄 Yeniden' : '▶ Analiz Et'}
                  </button>
                </div>
                {analyzeText ? (
                  <div className="prose prose-invert prose-sm max-w-none text-slate-200 text-xs">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>{analyzeText}</ReactMarkdown>
                    {isAnalyzing && <span className="inline-block w-1.5 h-3 bg-purple-400 animate-pulse ml-0.5 rounded-sm" />}
                  </div>
                ) : isAnalyzing ? (
                  <div className="flex items-center gap-2 text-slate-400 text-xs">
                    <div className="w-3 h-3 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
                    <span>AI analiz yapıyor...</span>
                  </div>
                ) : (
                  <p className="text-slate-500 text-xs">Sunucu hakkında AI analizi başlatmak için yukarıdaki butona tıklayın.</p>
                )}
              </div>
            </div>
          )}

          {/* ── PERF TAB ── */}
          {tab === 'perf' && (
            <div className="space-y-4">
              {metricsLoading ? (
                <div className="flex items-center gap-2 text-slate-400 text-sm py-8 justify-center">
                  <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                  <span>Metrikler yükleniyor...</span>
                </div>
              ) : (!metrics?.has_node_exporter && !metrics?.source) ? (
                <div className="text-center py-10 text-slate-500">
                  <p className="text-3xl mb-3">📡</p>
                  <p className="text-sm">Node Exporter kurulu değil ve vCenter'dan veri alınamadı.</p>
                  {server.server_type === 'VIRTUAL' && (
                    <p className="text-xs text-slate-600 mt-1">Ayarlar → Hypervisors'dan vCenter bağlantısını kontrol edin.</p>
                  )}
                </div>
              ) : (
                <>
                  {/* Data source badge */}
                  <div className="flex items-center gap-2 text-xs">
                    {metrics.source === 'vcenter' ? (
                      <span className="px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-400 border border-blue-500/30">📊 vCenter</span>
                    ) : metrics.source === 'prometheus' ? (
                      <span className="px-2 py-0.5 rounded-full bg-green-500/20 text-green-400 border border-green-500/30">📈 Prometheus / Node Exporter</span>
                    ) : null}
                    {metrics.power_state && (
                      <span className={`px-2 py-0.5 rounded-full border text-[10px] font-semibold ${metrics.power_state === 'POWERED_ON' ? 'bg-green-500/20 text-green-400 border-green-500/30' : 'bg-red-500/20 text-red-400 border-red-500/30'}`}>
                        {metrics.power_state === 'POWERED_ON' ? '⚡ Açık' : '⏹ Kapalı'}
                      </span>
                    )}
                  </div>

                  {/* Gauge cards */}
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      { label: 'CPU', value: metrics.cpu_percent, icon: '⚡', color: 'text-yellow-400' },
                      { label: 'RAM', value: metrics.mem_percent, icon: '🧠', color: 'text-blue-400' },
                      { label: 'Disk', value: metrics.disk_percent, icon: '💾', color: 'text-purple-400' },
                    ].map(({ label, value, icon, color }) => (
                      <div key={label} className="bg-slate-800/50 rounded-xl border border-slate-700 p-3 text-center">
                        <p className={`text-2xl font-bold ${value !== null ? (value > 85 ? 'text-red-400' : value > 60 ? 'text-yellow-400' : 'text-green-400') : 'text-slate-600'}`}>
                          {value !== null ? `${value}%` : 'N/A'}
                        </p>
                        <p className={`text-xs mt-1 ${color}`}>{icon} {label}</p>
                      </div>
                    ))}
                  </div>

                  {/* Progress bars */}
                  <div className="bg-slate-800/50 rounded-xl border border-slate-700 p-4 space-y-3">
                    <MetricBar label="CPU Kullanımı" value={metrics.cpu_percent} colorClass={cpuColor(metrics.cpu_percent)} />
                    <MetricBar label={`RAM  ${metrics.mem_used_gb != null ? `(${metrics.mem_used_gb}/${metrics.mem_total_gb} GB)` : ''}`} value={metrics.mem_percent} colorClass={memColor(metrics.mem_percent)} />
                    <MetricBar label={`Disk  ${metrics.disk_avail_gb != null ? `(${metrics.disk_avail_gb} GB boş / ${metrics.disk_total_gb} GB)` : ''}`} value={metrics.disk_percent} colorClass={diskColor(metrics.disk_percent)} />
                  </div>

                  {/* Extra info */}
                  <div className="grid grid-cols-3 gap-3">
                    {[
                      metrics.source === 'vcenter'
                        ? ['vCPU Sayısı', metrics.cpu_num !== null ? String(metrics.cpu_num) : '-']
                        : ['Load 1m', metrics.load1 !== null ? String(metrics.load1) : '-'],
                      metrics.source === 'vcenter'
                        ? ['RAM (Toplam)', metrics.mem_total_gb !== null ? `${metrics.mem_total_gb} GB` : '-']
                        : ['Load 5m', metrics.load5 !== null ? String(metrics.load5) : '-'],
                      ['Uptime', fmtUptime(metrics.uptime_seconds)],
                    ].map(([label, value]) => (
                      <div key={label} className="bg-slate-800/50 rounded-lg p-3 border border-slate-700/50 text-center">
                        <p className="text-xs text-slate-500 mb-0.5">{label}</p>
                        <p className="text-sm font-medium text-white">{value}</p>
                      </div>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {/* ── EVENTS TAB ── */}
          {tab === 'events' && (
            <div className="space-y-2">
              {eventsLoading ? (
                <div className="flex items-center gap-2 text-slate-400 text-sm py-8 justify-center">
                  <div className="w-4 h-4 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
                  <span>Eventler yükleniyor...</span>
                </div>
              ) : !eventsData?.groups?.length ? (
                <div className="text-center py-10 text-slate-500">
                  <p className="text-3xl mb-3">✅</p>
                  <p className="text-sm">Bu sunucuya ait aktif event bulunmuyor.</p>
                </div>
              ) : (
                eventsData.groups.map((grp, i) => (
                  <div key={i} className="bg-slate-800/50 rounded-lg border border-slate-700/50 p-3">
                    <div className="flex items-start gap-2">
                      <span className={`mt-0.5 px-1.5 py-0.5 rounded text-[10px] font-semibold border flex-shrink-0 ${SCOLOR[grp.severity] || SCOLOR.info}`}>
                        {grp.severity}
                      </span>
                      <div className="flex-1 min-w-0">
                        <p className="text-xs text-slate-200 break-words leading-snug">{grp.title}</p>
                        <div className="flex gap-3 mt-1">
                          <span className="text-[10px] text-slate-500">{grp.event_type}</span>
                          <span className="text-[10px] text-slate-500">{grp.count}×</span>
                          {grp.latest_created_at && (
                            <span className="text-[10px] text-slate-500">
                              {new Date(grp.latest_created_at).toLocaleString('tr-TR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>
                  </div>
                ))
              )}
            </div>
          )}

        </div>
      </div>
    </div>
  )
}


const Servers: React.FC = () => {
  const [selectedServer, setSelectedServer] = useState<Server | null>(null)
  const [showAddModal, setShowAddModal] = useState(false)
  const [searchTerm, setSearchTerm] = useState('')
  const [ipFilter, setIpFilter] = useState('')
  const [statusFilter, setStatusFilter] = useState<string>('all') // Varsayılan olarak tüm durumlar
  const [showOffline, setShowOffline] = useState(false) // Varsayılan: tüm sunucular (çevrimiçi + çevrimdışı) gösterilsin
  const [aiReadyFilter, setAiReadyFilter] = useState<string>('true') // all, true, false — varsayılan: AI Ready
  const [typeFilter, setTypeFilter] = useState<string>('all') // all, VIRTUAL, PHYSICAL
  const [nodeExporterFilter, setNodeExporterFilter] = useState<string>('all') // all, installed, running, not_installed

  const [sortKey, setSortKey] = useState<string>('name')
  const [sortDirection, setSortDirection] = useState<'asc' | 'desc'>('asc')
  const [sshTarget, setSshTarget] = useState<{id: number; name: string; ip: string} | null>(null)

  // Kolon genişlikleri (px)
  const [colWidths, setColWidths] = useState<number[]>([260, 120, 240, 140, 180, 120])

  // Resize handler
  const resizingCol = React.useRef<{col: number; startX: number; startW: number} | null>(null)
  const onResizeMouseDown = (col: number, e: React.MouseEvent) => {
    e.preventDefault()
    e.stopPropagation()
    resizingCol.current = { col, startX: e.clientX, startW: colWidths[col] }
    const onMove = (ev: MouseEvent) => {
      if (!resizingCol.current) return
      const delta = ev.clientX - resizingCol.current.startX
      const newW = Math.max(60, resizingCol.current.startW + delta)
      setColWidths(prev => { const next = [...prev]; next[resizingCol.current!.col] = newW; return next })
    }
    const onUp = () => { resizingCol.current = null; document.removeEventListener('mousemove', onMove); document.removeEventListener('mouseup', onUp) }
    document.addEventListener('mousemove', onMove)
    document.addEventListener('mouseup', onUp)
  }
  const [installingNodeExporter, setInstallingNodeExporter] = useState<number | null>(null)
  const [startingNodeExporter, setStartingNodeExporter] = useState<number | null>(null)
  const [installResultByServerId, setInstallResultByServerId] = useState<Record<number, {
    success: boolean
    message?: string
    error?: string
    steps?: Array<{ id: string; label: string; status: string; message?: string }>
  }>>({})
  const [installSimulatedStep, setInstallSimulatedStep] = useState<Record<number, number>>({})
  const installAbortRef = React.useRef<AbortController | null>(null)
  const [formData, setFormData] = useState({
    name: '',
    hostname: '',
    ip_address: '',
    status: 'OFFLINE',
    server_type: 'VIRTUAL',
    os_type: 'linux',
    ssh_username: '',
    ssh_password: '',
    ssh_port: '22',
    sudo_password: '',
    private_key: ''
  })

  const queryClient = useQueryClient()

  // Kurulum sırasında adımların görsel olarak ilerlemesi (simüle)
  useEffect(() => {
    if (installingNodeExporter == null) return
    setInstallSimulatedStep(prev => ({ ...prev, [installingNodeExporter]: 0 }))
    const totalSteps = 8
    const t = setInterval(() => {
      setInstallSimulatedStep(prev => {
        const current = prev[installingNodeExporter] ?? 0
        if (current >= totalSteps - 1) return prev
        return { ...prev, [installingNodeExporter]: current + 1 }
      })
    }, 2200)
    return () => clearInterval(t)
  }, [installingNodeExporter])

  // Önce sunucu listesini al (Node Exporter durumu olmadan)
  const { data: servers = [], isLoading, isFetching, isError, error, refetch } = useQuery<Server[]>({
    queryKey: ['servers'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/servers/`)
      if (!response.ok) {
        let detail = `HTTP ${response.status}`
        try {
          const err = await response.json()
          detail = typeof err?.detail === 'string' ? err.detail : JSON.stringify(err)
        } catch { /* JSON parse hatası yoksay */ }
        throw new Error(detail)
      }
      const data = await response.json()
      if (!Array.isArray(data)) throw new Error('API dizi döndürmedi')
      return data
    },
    refetchInterval: 60_000,   // 60 sn'de bir arka planda yenile
    placeholderData: (prev) => prev, // önceki veriyi göster, yüklenirken blank bırakma
  })

  // Tüm ONLINE sunucular için Node Exporter durumu iste (SSH yoksa backend Prometheus'tan bakar)
  const checkableServerIds = servers
    .filter(s => s.status === 'ONLINE')
    .map(s => s.id)
    .sort((a, b) => a - b)
    .join(',')

  // Node Exporter kurulu sunucuları listele
  // Node Exporter durumlarını ayrı bir query ile al (ONLINE sunucular; backend SSH + Prometheus fallback kullanır)
  const { data: nodeExporterStatuses = {} } = useQuery<Record<number, { installed: boolean; running: boolean }>>({
    queryKey: ['nodeExporterStatuses', checkableServerIds],
    queryFn: async () => {
      const onlineServers = servers.filter(s => s.status === 'ONLINE')
      if (onlineServers.length === 0) return {}

      const statusPromises = onlineServers.map(async (server) => {
        let installed = false
        let running = false
        try {
          const response = await fetch(`${API_BASE_URL}/monitoring/node-exporter/status/${server.id}`)
          const data = await response.json().catch(() => ({}))
          if (response.ok) {
            installed = Boolean(data.installed)
            running = Boolean(data.running)
          }
        } catch {
          // ağ/parse hatası
        }
        return {
          serverId: server.id,
          status: { installed, running }
        }
      })

      const results = await Promise.all(statusPromises)
      const statusMap: Record<number, { installed: boolean; running: boolean }> = {}
      results.forEach(r => { statusMap[r.serverId] = r.status })
      return statusMap
    },
    enabled: servers.length > 0 && checkableServerIds.length > 0,
    refetchInterval: 60000
  })

  const createMutation = useMutation({
    mutationFn: async (data: {
      name: string
      hostname: string
      ip_address: string
      status: string
      server_type: string
      os_type: string
      connection_config: Record<string, any>
    }) => {
      const response = await fetch(`${API_BASE_URL}/servers/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to create server')
      }
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] })
      queryClient.invalidateQueries({ queryKey: ['nodeExporterStatuses'] })
      setShowAddModal(false)
      setFormData({
        name: '',
        hostname: '',
        ip_address: '',
        status: 'OFFLINE',
        server_type: 'VIRTUAL',
        os_type: 'linux',
        ssh_username: '',
        ssh_password: '',
        ssh_port: '22',
        sudo_password: '',
        private_key: ''
      })
    },
    onError: () => {
      // DEV: console.error(...)
    }
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await fetch(`${API_BASE_URL}/servers/${id}`, { method: 'DELETE' })
      if (!response.ok) throw new Error('Failed to delete server')
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['servers'] })
    }
  })

  const INSTALL_REQUEST_TIMEOUT_MS = 120000

  const installNodeExporterMutation = useMutation({
    mutationFn: async (serverId: number) => {
      const controller = new AbortController()
      installAbortRef.current = controller
      const timeoutId = setTimeout(() => controller.abort(), INSTALL_REQUEST_TIMEOUT_MS)
      try {
        const response = await fetch(`${API_BASE_URL}/monitoring/node-exporter/install/${serverId}`, {
          method: 'POST',
          signal: controller.signal
        })
        const data = await response.json().catch(() => ({}))
        if (!response.ok) {
          setInstallingNodeExporter(null)
          setInstallResultByServerId(prev => ({
            ...prev,
            [serverId]: { success: false, error: data.detail || data.error || 'Kurulum başarısız', steps: Array.isArray(data.steps) ? data.steps : [] }
          }))
          throw new Error(data.detail || data.error || 'Failed to install Node Exporter')
        }
        return data
      } finally {
        clearTimeout(timeoutId)
        installAbortRef.current = null
      }
    },
    onSuccess: (data, serverId) => {
      queryClient.invalidateQueries({ queryKey: ['servers'] })
      queryClient.invalidateQueries({ queryKey: ['nodeExporterStatuses'] })
      setInstallingNodeExporter(null)
      setInstallSimulatedStep(prev => { const next = { ...prev }; delete next[serverId]; return next })
      const steps = Array.isArray(data.steps) ? data.steps : []
      setInstallResultByServerId(prev => ({ ...prev, [serverId]: { success: true, message: data.message, steps } }))
    },
    onError: (err: Error, serverId) => {
      setInstallingNodeExporter(null)
      setInstallSimulatedStep(prev => { const next = { ...prev }; delete next[serverId]; return next })
      const message = err.name === 'AbortError'
        ? 'Kurulum zaman aşımına uğradı (2 dk) veya iptal edildi. SSH/bağlantıyı kontrol edin.'
        : err.message
      setInstallResultByServerId(prev => ({ ...prev, [serverId]: { success: false, error: message, steps: [] } }))
    }
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    // DEV: console.log(...)
    if (!formData.name || formData.name.trim() === '') {
      alert('Sunucu adı gereklidir!')
      return
    }
    if (!formData.ip_address || formData.ip_address.trim() === '') {
      alert('IP adresi zorunludur! Lütfen sunucunun IP adresini girin.')
      return
    }
    const connection_config = formData.ssh_username
      ? {
          username: formData.ssh_username,
          password: formData.ssh_password || undefined,
          port: Number(formData.ssh_port || 22),
          sudo_password: formData.sudo_password || undefined,
          private_key: formData.private_key || undefined
        }
      : {}

    createMutation.mutate({
      name: formData.name,
      hostname: formData.hostname,
      ip_address: formData.ip_address,
      status: formData.status,
      server_type: formData.server_type,
      os_type: formData.os_type,
      connection_config
    })
  }

  const toggleSort = (key: string) => {
    if (sortKey === key) {
      setSortDirection(prev => (prev === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDirection('asc')
    }
  }

  const getStatusOrder = (status: string) => {
    const order: Record<string, number> = {
      ONLINE: 1,
      WARNING: 2,
      CRITICAL: 3,
      OFFLINE: 4
    }
    return order[status] ?? 5
  }

  const getNodeExporterOrder = (server: Server) => {
    const status = server.node_exporter
    if (status?.running) return 2
    if (status?.installed) return 1
    return 0
  }

  const parseIp = (ip: string) => ip.split('.').map(part => Number(part) || 0)

  // Sunuculara Node Exporter durumunu ekle
  const serversWithNodeExporter = servers.map(server => ({
    ...server,
    node_exporter: nodeExporterStatuses[server.id] || {
      installed: false,
      running: false
    }
  }))

  // Filtreleme
  const filteredServers = serversWithNodeExporter.filter(server => {
    const matchesSearch = server.name.toLowerCase().includes(searchTerm.toLowerCase()) ||
      server.ip_address?.toLowerCase().includes(searchTerm.toLowerCase()) ||
      server.hostname?.toLowerCase().includes(searchTerm.toLowerCase())
    const matchesIp = !ipFilter || server.ip_address?.toLowerCase().includes(ipFilter.toLowerCase())
    
    // Status filtresi:
    // showOffline=false → OFFLINE gizle (ONLINE + WARNING + diğerleri görünür)
    // showOffline=true  → hepsi görünür (OFFLINE dahil)
    const matchesStatus = showOffline
      ? (statusFilter === 'all' || server.status === statusFilter)
      : (server.status !== 'OFFLINE' && (statusFilter === 'all' || server.status === statusFilter))
    
    const matchesAiReady = aiReadyFilter === 'all' || 
      (aiReadyFilter === 'true' && server.ai_ready) ||
      (aiReadyFilter === 'false' && !server.ai_ready)
    
    const matchesType = typeFilter === 'all' || server.server_type === typeFilter

    const matchesNodeExporter = nodeExporterFilter === 'all' ||
      (nodeExporterFilter === 'installed' && server.node_exporter?.installed) ||
      (nodeExporterFilter === 'running' && server.node_exporter?.running) ||
      (nodeExporterFilter === 'not_installed' && !server.node_exporter?.installed)

    return matchesSearch && matchesIp && matchesStatus && matchesAiReady && matchesType && matchesNodeExporter
  })

  const sortedServers = [...filteredServers].sort((a, b) => {
    let aValue: number | string = ''
    let bValue: number | string = ''

    switch (sortKey) {
      case 'ip': {
        const aParts = parseIp(a.ip_address || '0.0.0.0')
        const bParts = parseIp(b.ip_address || '0.0.0.0')
        for (let i = 0; i < 4; i += 1) {
          if (aParts[i] !== bParts[i]) return sortDirection === 'asc' ? aParts[i] - bParts[i] : bParts[i] - aParts[i]
        }
        return 0
      }
      case 'status':
        aValue = getStatusOrder(a.status)
        bValue = getStatusOrder(b.status)
        break
      case 'type':
        aValue = a.server_type || ''
        bValue = b.server_type || ''
        break
      case 'cpu':
        aValue = a.cpu_cores || 0
        bValue = b.cpu_cores || 0
        break
      case 'memory':
        aValue = a.memory_gb || 0
        bValue = b.memory_gb || 0
        break
      case 'ai':
        aValue = a.ai_ready ? 1 : 0
        bValue = b.ai_ready ? 1 : 0
        break
      case 'node_exporter':
        aValue = getNodeExporterOrder(a)
        bValue = getNodeExporterOrder(b)
        break
      case 'name':
      default:
        aValue = a.name || ''
        bValue = b.name || ''
        break
    }

    if (typeof aValue === 'number' && typeof bValue === 'number') {
      return sortDirection === 'asc' ? aValue - bValue : bValue - aValue
    }
    return sortDirection === 'asc'
      ? String(aValue).localeCompare(String(bValue))
      : String(bValue).localeCompare(String(aValue))
  })

  const getStatusBadge = (status: string) => {
    const styles: Record<string, string> = {
      ONLINE: 'bg-green-500/20 text-green-400 border-green-500/30',
      OFFLINE: 'bg-slate-500/20 text-slate-400 border-slate-500/30',
      WARNING: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
      CRITICAL: 'bg-red-500/20 text-red-400 border-red-500/30',
    }
    return styles[status] || styles.OFFLINE
  }

  if (isLoading) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
        <p className="text-slate-400">Sunucular yükleniyor...</p>
      </div>
    )
  }

  if (isError && servers.length === 0) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4 p-6">
        <p className="text-red-400 font-medium">Sunucular yüklenemedi</p>
        <p className="text-slate-400 text-sm text-center max-w-md">
          {error instanceof Error ? error.message : 'Backend bağlantısını kontrol edin. API adresi: ' + API_BASE_URL}
        </p>
        <button
          onClick={() => refetch()}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg"
        >
          Tekrar dene
        </button>
      </div>
    )
  }

  return (
    <>
    <div className="space-y-6">
      {/* Hata banner (eski veri varken hata alındıysa göster) */}
      {isError && servers.length > 0 && (
        <div className="flex items-center gap-3 bg-red-500/10 border border-red-500/30 rounded-lg px-4 py-2.5 text-sm">
          <span className="text-red-400">⚠️ Yenileme hatası:</span>
          <span className="text-red-300">{error instanceof Error ? error.message : 'Bilinmeyen hata'}</span>
          <button onClick={() => refetch()} className="ml-auto text-xs text-red-400 underline">Tekrar dene</button>
        </div>
      )}
      {/* Arka plan yenileme göstergesi */}
      {isFetching && !isLoading && (
        <div className="flex items-center gap-2 text-xs text-slate-500">
          <div className="animate-spin rounded-full h-3 w-3 border-b border-slate-400"></div>
          Yenileniyor...
        </div>
      )}
      {/* Header */}
      <div className="flex flex-col gap-4">
        <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-4">
          <div className="flex flex-wrap items-center gap-3">
            {/* Search */}
            <div className="relative">
              <input
                type="text"
                placeholder="Sunucu ara..."
                value={searchTerm}
                onChange={(e) => setSearchTerm(e.target.value)}
                className="w-64 bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 pl-10 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
              <span className="absolute left-3 top-2.5 text-slate-500">🔍</span>
            </div>
            {/* IP Filter */}
            <div className="relative">
              <input
                type="text"
                placeholder="IP filtre..."
                value={ipFilter}
                onChange={(e) => setIpFilter(e.target.value)}
                className="w-48 bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white placeholder-slate-500 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent"
              />
            </div>
            {/* Show Offline Toggle */}
            <label className="flex items-center space-x-2 cursor-pointer">
              <input
                type="checkbox"
                checked={showOffline}
                onChange={(e) => setShowOffline(e.target.checked)}
                className="w-4 h-4 text-blue-600 bg-slate-700 border-slate-600 rounded focus:ring-blue-500"
              />
              <span className="text-sm text-slate-300">Çevrimdışıları Göster</span>
            </label>
            {/* Status Filter */}
            {showOffline && (
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              >
                <option value="all">Tüm Durumlar</option>
                <option value="ONLINE">Çevrimiçi</option>
                <option value="OFFLINE">Çevrimdışı</option>
                <option value="WARNING">Uyarı</option>
                <option value="CRITICAL">Kritik</option>
              </select>
            )}
            {/* AI Ready Filter */}
            <select
              value={aiReadyFilter}
              onChange={(e) => setAiReadyFilter(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">Tümü</option>
              <option value="true">🤖 AI Ready</option>
              <option value="false">AI Ready Değil</option>
            </select>
            {/* Type Filter */}
            <select
              value={typeFilter}
              onChange={(e) => setTypeFilter(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">Tüm Tipler</option>
              <option value="VIRTUAL">Virtual</option>
              <option value="PHYSICAL">Physical</option>
            </select>
            {/* Node Exporter Filter */}
            <select
              value={nodeExporterFilter}
              onChange={(e) => setNodeExporterFilter(e.target.value)}
              className="bg-slate-800 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="all">Node Exporter: Tümü</option>
              <option value="running">Çalışıyor</option>
              <option value="installed">Kurulu</option>
              <option value="not_installed">Kurulu Değil</option>
            </select>

          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={async () => {
                try {
                  const response = await fetch(`${API_BASE_URL}/servers/check-health`, { method: 'POST' })
                  const data = await response.json()
                  if (response.ok) {
                    alert(`Durum kontrolü tamamlandı:\n${data.stats?.checked || 0} sunucu kontrol edildi\n${data.stats?.updated || 0} güncellendi`)
                    queryClient.invalidateQueries({ queryKey: ['servers'] })
                    queryClient.invalidateQueries({ queryKey: ['nodeExporterStatuses'] })
                  } else {
                    alert('Durum kontrolü başarısız: ' + (data.detail || 'Bilinmeyen hata'))
                  }
                } catch (err) {
                  alert('Durum kontrolü hatası: ' + (err instanceof Error ? err.message : 'Ağ hatası'))
                }
              }}
              className="inline-flex items-center px-4 py-2 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-lg hover:from-green-500 hover:to-green-600 transition-all"
            >
              <span className="mr-2">🔄</span>
              Durumları Kontrol Et
            </button>
            <AiReadyUpdateButton onDone={() => refetch()} />
            <BulkNodeExporterButton servers={servers} onDone={() => refetch()} />
            <OsRefreshButton servers={servers} onDone={() => refetch()} />
            <button
              onClick={() => setShowAddModal(true)}
              className="inline-flex items-center px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all shadow-lg shadow-blue-500/25"
            >
              <span className="mr-2">➕</span>
              Yeni Sunucu
            </button>
          </div>
        </div>
      </div>

      {/* Table */}
      <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full" style={{ tableLayout: 'fixed', minWidth: colWidths.reduce((a,b) => a+b, 0) }}>
            {/* Kolon genişlikleri */}
            <colgroup>
              {colWidths.map((w, i) => <col key={i} style={{ width: w }} />)}
            </colgroup>
            <thead>
              <tr className="bg-slate-800/80 border-b border-slate-700 select-none">
                {([
                  { key: 'name',   label: 'Sunucu',      sortable: true,  sortKey: 'name'   },
                  { key: 'status', label: 'Durum',       sortable: true,  sortKey: 'status' },
                  { key: 'os',     label: 'OS / Kernel', sortable: false, sortKey: ''       },
                  { key: 'cpu',    label: 'CPU / RAM',   sortable: true,  sortKey: 'cpu'    },
                  { key: 'izleme', label: 'İzleme',      sortable: true,  sortKey: 'ai'     },
                  { key: 'action', label: '',           sortable: false, sortKey: '' },
                ] as Array<{key: string; label: string; sortable: boolean; sortKey?: string}>).map((col, ci) => (
                  <th key={col.key}
                    className="relative px-4 py-3 text-left text-xs font-semibold text-slate-400 uppercase tracking-wide overflow-hidden">
                    {/* Başlık + sort ikonu */}
                    <div className="flex items-center gap-1 pr-3">
                      {col.sortable ? (
                        <button
                          onClick={() => toggleSort(col.sortKey || col.key)}
                          className="flex items-center gap-1 hover:text-white transition-colors group/sort"
                        >
                          {col.label}
                          <span className={`text-[11px] ml-0.5 ${sortKey === (col.sortKey || col.key) ? 'text-blue-400' : 'text-slate-600 group-hover/sort:text-slate-400'}`}>
                            {sortKey === (col.sortKey || col.key) ? (sortDirection === 'asc' ? '↑' : '↓') : '↕'}
                          </span>
                        </button>
                      ) : (
                        <span>{col.label}</span>
                      )}
                    </div>
                    {/* Resize handle */}
                    {ci < colWidths.length - 1 && (
                      <div
                        className="absolute right-0 top-0 bottom-0 w-3 flex items-center justify-center cursor-col-resize group/rz hover:bg-blue-500/10"
                        onMouseDown={e => onResizeMouseDown(ci, e)}
                      >
                        <div className="w-0.5 h-4 bg-slate-600 group-hover/rz:bg-blue-400 transition-colors rounded-full" />
                      </div>
                    )}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-700">
              {sortedServers.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-6 py-12 text-center text-slate-400">
                    <p className="font-medium">Henüz sunucu yok</p>
                    <p className="text-sm mt-1">Yeni sunucu eklemek için &quot;Yeni Sunucu&quot; butonunu kullanın veya backend/veritabanı bağlantısını kontrol edin.</p>
                    <p className="text-xs mt-2 text-slate-500">API: {API_BASE_URL}</p>
                  </td>
                </tr>
              ) : sortedServers.map((server) => (
                <React.Fragment key={server.id}>
                <tr className="hover:bg-slate-700/20 transition-colors cursor-pointer border-b border-slate-700/50 group" onClick={() => setSelectedServer(server)}>

                  {/* ── Sunucu Adı + IP + Hostname ── */}
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-3">
                      <div className={`w-9 h-9 rounded-lg flex items-center justify-center flex-shrink-0 text-lg ${
                        server.status === 'ONLINE'
                          ? 'bg-green-500/20 ring-1 ring-green-500/40'
                          : server.status === 'OFFLINE'
                          ? 'bg-slate-700/50 ring-1 ring-slate-600/40'
                          : 'bg-yellow-500/20 ring-1 ring-yellow-500/40'
                      }`}>
                        {server.server_type === 'PHYSICAL' ? '🖥️' : '💻'}
                      </div>
                      <div className="min-w-0">
                        <div className="text-sm font-semibold text-white group-hover:text-blue-300 transition-colors truncate max-w-[180px]">
                          {server.name}
                        </div>
                        <div className="flex items-center gap-2 mt-0.5 flex-wrap">
                          <span className="text-xs font-mono text-slate-400">{server.ip_address || '-'}</span>
                          {server.hypervisor_name ? (
                            <span className="inline-flex items-center gap-0.5 text-[11px] text-slate-500 bg-slate-700/50 px-1.5 py-0.5 rounded">
                              ☁ {server.hypervisor_name}
                            </span>
                          ) : server.hostname && server.hostname !== server.name && server.hostname !== server.ip_address ? (
                            <span className="text-xs text-slate-600 truncate max-w-[100px]">{server.hostname}</span>
                          ) : null}
                        </div>
                      </div>
                    </div>
                  </td>

                  {/* ── Durum ── */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    {server.status === 'ONLINE' ? (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-green-500/15 text-green-400 border border-green-500/30">
                        <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
                        Aktif
                      </span>
                    ) : server.status === 'OFFLINE' ? (
                      <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-slate-700/50 text-slate-400 border border-slate-600/50">
                        <span className="w-1.5 h-1.5 bg-slate-500 rounded-full" />
                        Çevrimdışı
                      </span>
                    ) : (
                      <span className={`inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border ${getStatusBadge(server.status)}`}>
                        <span className="w-1.5 h-1.5 rounded-full bg-current" />
                        {server.status}
                      </span>
                    )}
                  </td>

                  {/* ── OS / Kernel ── */}
                  <td className="px-4 py-3">
                    {(() => {
                      const icon = server.os_release_id === 'rhel'   ? '🔴' :
                                   server.os_release_id === 'ol'     ? '🟠' :
                                   server.os_release_id === 'rocky'  ? '🟢' :
                                   server.os_release_id === 'ubuntu' ? '🟡' :
                                   server.os_release_id === 'debian' ? '🌀' :
                                   server.os_version?.toLowerCase().includes('red hat') ? '🔴' :
                                   server.os_version?.toLowerCase().includes('oracle')  ? '🟠' :
                                   server.os_version?.toLowerCase().includes('rocky')   ? '🟢' :
                                   server.os_version?.toLowerCase().includes('ubuntu')  ? '🟡' : '🐧'
                      const osName = server.os_release_id
                        ? `${server.os_release_id.toUpperCase()} ${server.os_version_id || ''}`
                        : server.os_version?.replace('(Plow)','').replace('(Ootpa)','').replace('(Ootpa)','').trim() || null
                      return (
                        <div className="flex items-start gap-2">
                          <span className="text-base mt-0.5 flex-shrink-0">{icon}</span>
                          <div className="min-w-0">
                            {osName ? (
                              <div className="text-sm font-medium text-white truncate max-w-[180px]" title={osName}>
                                {osName}
                              </div>
                            ) : (
                              <div className="text-xs text-slate-600 italic">Bilinmiyor</div>
                            )}
                            {server.kernel_version && (
                              <div className="text-[11px] text-slate-500 font-mono truncate max-w-[200px] mt-0.5"
                                   title={server.kernel_version}>
                                {server.kernel_version}
                              </div>
                            )}
                          </div>
                        </div>
                      )
                    })()}
                  </td>

                  {/* ── CPU / RAM ── */}
                  <td className="px-4 py-3 whitespace-nowrap">
                    <div className="space-y-1">
                      {server.cpu_cores > 0 ? (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-400 w-7">CPU</span>
                          <span className="text-sm font-medium text-white">{server.cpu_cores}</span>
                          <span className="text-xs text-slate-500">çekirdek</span>
                        </div>
                      ) : (
                        <div className="text-xs text-slate-600">—</div>
                      )}
                      {server.memory_gb > 0 && (
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-slate-400 w-7">RAM</span>
                          <span className="text-sm font-medium text-white">{server.memory_gb}</span>
                          <span className="text-xs text-slate-500">GB</span>
                        </div>
                      )}
                    </div>
                  </td>

                  {/* ── İzleme (AI + Node Exporter) ── */}
                  <td className="px-4 py-3" onClick={e => e.stopPropagation()}>
                    <div className="flex flex-wrap gap-1.5">
                      {/* AI Ready */}
                      {server.ai_ready && (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-purple-500/15 text-purple-300 border border-purple-500/25">
                          🤖 AI
                        </span>
                      )}
                      {/* Node Exporter */}
                      {server.node_exporter?.running ? (
                        <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-md text-xs font-medium bg-green-500/15 text-green-400 border border-green-500/25">
                          <span className="w-1.5 h-1.5 bg-green-400 rounded-full animate-pulse" />
                          Metrik
                        </span>
                      ) : server.node_exporter?.installed ? (
                      <button
                        onClick={async () => {
                          setStartingNodeExporter(server.id)
                          try {
                            const response = await fetch(`${API_BASE_URL}/monitoring/node-exporter/start/${server.id}`, { method: 'POST' })
                            const data = await response.json().catch(() => ({}))
                            if (response.ok) {
                              queryClient.invalidateQueries({ queryKey: ['nodeExporterStatuses'] })
                              queryClient.invalidateQueries({ queryKey: ['servers'] })
                            } else {
                              alert('Başlatma hatası: ' + (data.detail || 'Bilinmeyen hata'))
                            }
                          } catch (e) {
                            alert('Hata: ' + (e instanceof Error ? e.message : String(e)))
                          } finally {
                            setStartingNodeExporter(null)
                          }
                        }}
                        disabled={startingNodeExporter === server.id}
                        className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full text-xs font-medium bg-yellow-500/20 text-yellow-400 border border-yellow-500/30 hover:bg-yellow-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Node Exporter Başlat"
                      >
                        {startingNodeExporter === server.id ? '⏳' : '▶️'} {startingNodeExporter === server.id ? 'Başlatılıyor...' : 'Başlat'}
                      </button>
                    ) : server.status === 'ONLINE' ? (
                      <button
                        onClick={() => {
                          setInstallResultByServerId(prev => { const next = { ...prev }; delete next[server.id]; return next })
                          setInstallingNodeExporter(server.id)
                          installNodeExporterMutation.mutate(server.id)
                        }}
                        disabled={installingNodeExporter === server.id}
                        className="inline-flex items-center px-2.5 py-1 rounded-full text-xs font-medium bg-blue-500/20 text-blue-400 border border-blue-500/30 hover:bg-blue-500/30 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        title="Node Exporter Kur"
                      >
                        {installingNodeExporter === server.id ? '⏳ Kuruluyor...' : '📦 Kur'}
                      </button>
                    ) : (
                      <span className="text-xs text-slate-600 italic">Çevrimdışı</span>
                    )}
                    </div>
                  </td>

                  {/* ── İşlemler ── */}
                  <td className="px-4 py-3 text-right" onClick={e => e.stopPropagation()}>
                    <div className="flex items-center justify-end gap-1">
                      {installNodeExporterMutation.isError && installingNodeExporter === server.id && (
                        <span className="text-red-400 text-xs" title={installNodeExporterMutation.error?.message}>❌</span>
                      )}
                      {server.status === 'ONLINE' && server.ip_address && (
                        <button
                          onClick={() => {
                            // Yeni popup pencerede aç
                            const w = window.open(
                              `/terminal/${server.id}?name=${encodeURIComponent(server.name)}&ip=${encodeURIComponent(server.ip_address)}`,
                              `ssh-${server.id}`,
                              'width=1200,height=700,resizable=yes,scrollbars=no,menubar=no,toolbar=no,location=no,status=no'
                            )
                            if (!w) {
                              // Popup engellenirse modal aç
                              setSshTarget({id: server.id, name: server.name, ip: server.ip_address})
                            }
                          }}
                          className="px-2.5 py-1.5 text-xs bg-green-700/40 hover:bg-green-700 text-green-300 rounded-lg transition-colors font-mono"
                          title="SSH Terminal Aç (Yeni Pencere)"
                        >
                          SSH
                        </button>
                      )}
                      <button
                        onClick={() => setSelectedServer(server)}
                        className="px-2.5 py-1.5 text-xs bg-slate-700 hover:bg-slate-600 text-slate-200 rounded-lg transition-colors"
                        title="Detay"
                      >
                        Detay
                      </button>
                      <button
                        onClick={() => {
                          if (confirm('Bu sunucuyu silmek istediğinize emin misiniz?')) {
                            deleteMutation.mutate(server.id)
                          }
                        }}
                        className="px-2.5 py-1.5 text-xs text-red-400 hover:text-white hover:bg-red-700 rounded-lg transition-colors"
                        title="Sil"
                      >
                        Sil
                      </button>
                    </div>
                  </td>
                </tr>
                {/* Kurulum adımları: Kur basılan satırda açılır */}
                {(installingNodeExporter === server.id || installResultByServerId[server.id]) && (
                  <tr key={`${server.id}-install`} className="bg-slate-800/80">
                    <td colSpan={6} className="px-6 py-4">
                      <div className="rounded-lg border border-slate-700 bg-slate-900/60 p-4">
                        <div className="flex items-center justify-between mb-3">
                          <span className="text-sm font-medium text-slate-300">Node Exporter kurulumu — {server.name}</span>
                          <div className="flex items-center gap-2">
                            {installingNodeExporter === server.id && (
                              <button
                                type="button"
                                onClick={() => { installAbortRef.current?.abort(); setInstallingNodeExporter(null) }}
                                className="text-xs px-2 py-1 rounded bg-amber-500/20 text-amber-400 border border-amber-500/30 hover:bg-amber-500/30"
                              >
                                İptal
                              </button>
                            )}
                            <button
                              onClick={() => { installAbortRef.current?.abort(); setInstallingNodeExporter(null); setInstallResultByServerId(prev => { const next = { ...prev }; delete next[server.id]; return next }) }}
                              className="text-slate-400 hover:text-white text-xs"
                              aria-label="Kapat"
                            >
                              ✕ Kapat
                            </button>
                          </div>
                        </div>
                        <div className="mb-3">
                          <div className="h-2 bg-slate-700 rounded-full overflow-hidden">
                            {!installResultByServerId[server.id] ? (
                              <div
                                className="h-full bg-blue-500 rounded-full transition-all duration-500"
                                style={{
                                  width: `${Math.min(100, ((installSimulatedStep[server.id] ?? -1) + 1) * (100 / 8))}%`
                                }}
                              />
                            ) : (
                              <div
                                className="h-full bg-green-500 rounded-full transition-all duration-500"
                                style={{
                                  width: `${installResultByServerId[server.id].steps?.length
                                    ? (installResultByServerId[server.id].steps!.filter(s => s.status === 'success' || s.status === 'skipped').length / Math.max(installResultByServerId[server.id].steps!.length, 1)) * 100
                                    : installResultByServerId[server.id].success ? 100 : 50}%`
                                }}
                              />
                            )}
                          </div>
                          <p className="text-slate-500 text-xs mt-1">
                            {!installResultByServerId[server.id]
                              ? 'Kurulum devam ediyor... (en fazla 2 dk; takılırsa İptal ile iptal edebilirsiniz)'
                              : installResultByServerId[server.id].success
                                ? 'Kurulum tamamlandı'
                                : 'Kurulum hata ile sonuçlandı'}
                          </p>
                        </div>
                        <div className="space-y-1.5 max-h-48 overflow-y-auto">
                          {(installResultByServerId[server.id]?.steps && installResultByServerId[server.id].steps!.length > 0
                            ? installResultByServerId[server.id].steps!
                            : NODE_EXPORTER_STEP_LABELS.map((s, i) => ({
                                ...s,
                                status: (i <= (installSimulatedStep[server.id] ?? -1) ? 'success' : 'pending') as string,
                                message: undefined as string | undefined
                              }))
                          ).map((step: { id: string; label: string; status: string; message?: string }) => (
                            <div key={step.id} className="flex items-center gap-2 py-1.5 px-2 rounded bg-slate-800/60 border border-slate-700/50">
                              <span className="flex-shrink-0 w-5 h-5 flex items-center justify-center text-xs">
                                {step.status === 'success' ? (
                                  <span className="text-green-400">✓</span>
                                ) : step.status === 'failed' ? (
                                  <span className="text-red-400">✕</span>
                                ) : step.status === 'skipped' ? (
                                  <span className="text-slate-500">−</span>
                                ) : (
                                  <span className="text-blue-400 animate-spin">⟳</span>
                                )}
                              </span>
                              <div className="flex-1 min-w-0">
                                <p className="text-slate-200 text-xs font-medium truncate">{step.label}</p>
                                {step.message && <p className="text-slate-500 text-[10px] truncate" title={step.message}>{step.message}</p>}
                              </div>
                            </div>
                          ))}
                        </div>
                        {installResultByServerId[server.id] && (
                          <div className={`mt-3 p-2 rounded border text-xs ${installResultByServerId[server.id].success ? 'bg-green-500/10 border-green-500/30 text-green-400' : 'bg-red-500/10 border-red-500/30 text-red-400'}`}>
                            {installResultByServerId[server.id].success
                              ? (installResultByServerId[server.id].message || 'Kurulum başarıyla tamamlandı.')
                              : (installResultByServerId[server.id].error || 'Kurulum sırasında bir hata oluştu.')}
                          </div>
                        )}
                      </div>
                    </td>
                  </tr>
                )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
        {sortedServers.length === 0 && (
          <div className="text-center py-12 text-slate-500">
            {searchTerm || ipFilter || statusFilter !== 'all' || aiReadyFilter !== 'all' || typeFilter !== 'all' || nodeExporterFilter !== 'all'
              ? 'Filtreye uygun sunucu bulunamadı' 
              : 'Henüz sunucu eklenmemiş'}
          </div>
        )}
      </div>

      {/* Add Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-white">Yeni Sunucu Ekle</h2>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-slate-400 hover:text-white transition-colors"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Sunucu Adı *</label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="örn: web-server-01"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Hostname</label>
                <input
                  type="text"
                  value={formData.hostname}
                  onChange={(e) => setFormData({ ...formData, hostname: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="örn: web-server-01.local"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">
                  IP Adresi <span className="text-red-400">*</span>
                </label>
                <input
                  type="text"
                  required
                  value={formData.ip_address}
                  onChange={(e) => setFormData({ ...formData, ip_address: e.target.value })}
                  className={`w-full bg-slate-900 border rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 focus:border-transparent ${!formData.ip_address ? 'border-red-500/50' : 'border-slate-700'}`}
                  placeholder="örn: 192.168.1.100"
                />
                {!formData.ip_address && (
                  <p className="text-red-400 text-xs mt-1">IP adresi zorunludur</p>
                )}
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-2">Tip</label>
                  <select
                    value={formData.server_type}
                    onChange={(e) => setFormData({ ...formData, server_type: e.target.value })}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="VIRTUAL">Virtual</option>
                    <option value="PHYSICAL">Physical</option>
                  </select>
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-2">İşletim Sistemi</label>
                  <select
                    value={formData.os_type}
                    onChange={(e) => setFormData({ ...formData, os_type: e.target.value })}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  >
                    <option value="linux">Linux</option>
                    <option value="windows">Windows</option>
                  </select>
                </div>
              </div>
              <div className="border-t border-slate-700 pt-4">
                <h3 className="text-sm font-semibold text-slate-200 mb-3">SSH Bilgileri (Node Exporter kurulumu için)</h3>
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">Kullanıcı Adı</label>
                    <input
                      type="text"
                      value={formData.ssh_username}
                      onChange={(e) => setFormData({ ...formData, ssh_username: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="örn: root"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">SSH Port</label>
                    <input
                      type="number"
                      value={formData.ssh_port}
                      onChange={(e) => setFormData({ ...formData, ssh_port: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="22"
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 mt-3">
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">Şifre</label>
                    <input
                      type="password"
                      value={formData.ssh_password}
                      onChange={(e) => setFormData({ ...formData, ssh_password: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="SSH şifresi"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-slate-300 mb-2">Sudo Şifresi</label>
                    <input
                      type="password"
                      value={formData.sudo_password}
                      onChange={(e) => setFormData({ ...formData, sudo_password: e.target.value })}
                      className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                      placeholder="Opsiyonel"
                    />
                  </div>
                </div>
                <div className="mt-3">
                  <label className="block text-sm font-medium text-slate-300 mb-2">Private Key (opsiyonel)</label>
                  <textarea
                    value={formData.private_key}
                    onChange={(e) => setFormData({ ...formData, private_key: e.target.value })}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                    rows={3}
                  />
                </div>
              </div>
              <div className="flex justify-end space-x-3 pt-4">
                <button
                  type="button"
                  onClick={() => setShowAddModal(false)}
                  className="px-4 py-2 bg-slate-700 text-white rounded-lg hover:bg-slate-600 transition-colors"
                >
                  İptal
                </button>
                <button
                  type="submit"
                  disabled={createMutation.isPending}
                  className="px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all disabled:opacity-50"
                >
                  {createMutation.isPending ? 'Ekleniyor...' : 'Ekle'}
                </button>
              </div>
              {createMutation.isError && (
                <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
                  <p className="text-red-400 text-sm font-medium">Hata:</p>
                  <p className="text-red-300 text-sm mt-1">
                    {createMutation.error != null
                      ? (createMutation.error instanceof Error ? createMutation.error.message : String(createMutation.error))
                      : 'Bilinmeyen hata'}
                  </p>
                </div>
              )}
              {createMutation.isSuccess && (
                <div className="bg-green-500/10 border border-green-500/30 rounded-lg p-3">
                  <p className="text-green-400 text-sm">✓ Sunucu başarıyla eklendi!</p>
                </div>
              )}
            </form>
          </div>
        </div>
      )}

    </div>

      {selectedServer && (
        <ServerDetailDrawer server={selectedServer} onClose={() => setSelectedServer(null)} />
      )}

      {/* SSH Terminal Modal */}
      {sshTarget && (
        <Suspense fallback={
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/80">
            <div className="w-10 h-10 border-2 border-green-500 border-t-transparent rounded-full animate-spin" />
          </div>
        }>
          <SshTerminalModal
            serverId={sshTarget.id}
            serverName={sshTarget.name}
            serverIp={sshTarget.ip}
            onClose={() => setSshTarget(null)}
          />
        </Suspense>
      )}
    </>
  )
}

export default Servers

