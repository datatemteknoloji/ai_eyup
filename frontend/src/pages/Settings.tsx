import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

interface Credential {
  id: number
  name: string
  username: string
  port: number
  has_password: boolean
  has_private_key: boolean
  is_default: boolean
}

interface Server {
  id: number
  name: string
  ip_address: string
  ai_ready: boolean
  connection_config: any
}

const ConfirmModal = ({ message, onConfirm, onCancel }: {
  message: string; onConfirm: () => void; onCancel: () => void
}) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
    <div className="bg-cyber-card border border-slate-600 rounded-2xl shadow-2xl p-6 max-w-sm w-full mx-4">
      <div className="flex items-start gap-3 mb-5">
        <div className="w-9 h-9 rounded-full bg-yellow-500/15 border border-yellow-500/30 flex items-center justify-center flex-shrink-0 mt-0.5">
          <span className="text-yellow-400 text-base">⚠</span>
        </div>
        <div>
          <div className="text-sm font-semibold text-white mb-1">Onay Gerekiyor</div>
          <div className="text-sm text-slate-300 leading-relaxed">{message}</div>
        </div>
      </div>
      <div className="flex gap-3 justify-end">
        <button onClick={onCancel} className="px-4 py-2 rounded-lg text-sm text-slate-300 hover:text-white bg-white/[0.07] hover:bg-slate-600 border border-slate-600 transition-colors">İptal</button>
        <button onClick={onConfirm} className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-600 hover:bg-red-500 border border-red-500/50 transition-colors">Onayla</button>
      </div>
    </div>
  </div>
)

interface RagStatus {
  runbook: number
  incidents: number
  metrics: number
}

interface RunbookDocument {
  title: string
  chunk_count: number
  chunk_ids?: string[]
}

interface GeneralSettings {
  ollama_url: string
  ollama_model: string
  prometheus_url: string
  metric_retention_days?: number
  management_server_ip?: string
  detected_management_ip?: string
}

const RagTab: React.FC = () => {
  const [pdfFile, setPdfFile] = useState<File | null>(null)
  const [pdfTitle, setPdfTitle] = useState('')
  const [confirmState, setConfirmState] = React.useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))
  const { data: status, refetch: refetchStatus } = useQuery<RagStatus>({
    queryKey: ['rag-status'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/rag/status`)
      if (!res.ok) return { runbook: 0, incidents: 0, metrics: 0 }
      return res.json()
    }
  })
  const uploadPdf = useMutation({
    mutationFn: async () => {
      if (!pdfFile) throw new Error('PDF seçin')
      const form = new FormData()
      form.append('file', pdfFile)
      if (pdfTitle.trim()) form.append('title', pdfTitle.trim())
      const res = await fetch(`${API_BASE_URL}/rag/runbook/ingest-pdf`, { method: 'POST', body: form })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || 'Yükleme hatası')
      return r
    },
    onSuccess: (d) => { refetchStatus(); refetchRunbookDocs(); setPdfFile(null); setPdfTitle(''); alert(`PDF eklendi: ${d.chunks_added} chunk.`) },
    onError: (e) => alert(e instanceof Error ? e.message : 'PDF yükleme hatası')
  })
  const seedMetrics = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/rag/metrics/seed`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || 'Hata')
      return r
    },
    onSuccess: () => { refetchStatus(); alert('Metrik açıklamaları eklendi.') }
  })
  const reindexIncidents = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/rag/incidents/reindex`, { method: 'POST' })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || 'Hata')
      return r
    },
    onSuccess: (d) => { refetchStatus(); alert(`Incident'lar indexlendi: ${d.chunks_added} kayıt.`) }
  })
  const reindexEvents = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/rag/events/reindex`, { method: 'POST' })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || 'Hata')
      return r
    },
    onSuccess: (d) => { refetchStatus(); alert(`Event'ler eklendi: ${d.chunks_added} kayıt.`) }
  })
  const { data: runbookDocsData, refetch: refetchRunbookDocs } = useQuery<{ success: boolean; documents: RunbookDocument[] }>({
    queryKey: ['rag-runbook-documents'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/rag/runbook/documents`)
      if (!res.ok) return { success: false, documents: [] }
      return res.json()
    }
  })
  const deleteRunbookDoc = useMutation({
    mutationFn: async (title: string) => {
      const res = await fetch(`${API_BASE_URL}/rag/runbook/documents?title=${encodeURIComponent(title)}`, { method: 'DELETE' })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || 'Silinemedi')
      return r
    },
    onSuccess: (d) => { refetchStatus(); refetchRunbookDocs(); alert(`"${d.title}" silindi (${d.deleted_chunks} chunk).`) },
    onError: (e) => alert(e instanceof Error ? e.message : 'Silme hatası')
  })
  const runbookDocs = runbookDocsData?.documents ?? []
  return (
    <div>
      <h2 className="text-xl font-semibold text-white mb-2">RAG (Bilgi Tabanı)</h2>
      <p className="text-slate-400 text-sm mb-6">AI Chat sorularına yanıt verirken runbook, geçmiş olaylar ve metrik açıklamaları kullanılır.</p>

      {/* PDF Ekle - en üstte, belirgin */}
      <div className="mb-6 p-5 bg-cyber-deep/70 rounded-xl border-2 border-emerald-500/40">
        <h3 className="text-base font-semibold text-white mb-1 flex items-center gap-2">
          Runbook'a PDF Ekle
        </h3>
        <p className="text-slate-400 text-xs mb-4">PDF yükleyin; metin çıkarılıp RAG'e eklenir. Chat'te sorularınıza yanıt verirken kullanılır.</p>
        <div className="flex flex-wrap items-end gap-4">
          <div className="min-w-[200px]">
            <label className="block text-xs font-medium text-slate-400 mb-1">PDF dosyası</label>
            <input
              type="file"
              accept=".pdf"
              onChange={(e) => setPdfFile(e.target.files?.[0] || null)}
              className="block w-full text-sm text-slate-300 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-emerald-600 file:text-white file:font-medium"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">Başlık (opsiyonel)</label>
            <input
              type="text"
              value={pdfTitle}
              onChange={(e) => setPdfTitle(e.target.value)}
              placeholder="Dosya adı kullanılır"
              className="w-52 bg-cyber-card border border-slate-600 rounded-lg px-3 py-2 text-white text-sm placeholder-slate-500"
            />
          </div>
          <button
            onClick={() => uploadPdf.mutate()}
            disabled={!pdfFile || uploadPdf.isPending}
            className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-sm font-semibold shadow-lg shadow-emerald-500/20"
          >
            {uploadPdf.isPending ? 'Ekleniyor...' : 'PDF\'i RAG\'e Ekle'}
          </button>
        </div>
        {pdfFile && <p className="text-emerald-400 text-xs mt-2">Seçili: {pdfFile.name}</p>}
      </div>

      {/* Eklenen runbook dokümanları */}
      <div className="mb-6 p-5 bg-cyber-deep/50 rounded-xl border border-white/[0.06]">
        <h3 className="text-base font-semibold text-white mb-3 flex items-center gap-2">
          Eklenen Runbook Dokümanları
        </h3>
        {runbookDocs.length === 0 ? (
          <p className="text-slate-500 text-sm">Henüz runbook dokümanı yok. Yukarıdan PDF ekleyebilirsiniz.</p>
        ) : (
          <ul className="space-y-2">
            {runbookDocs.map((doc) => (
              <li
                key={doc.title}
                className="flex items-center justify-between py-2 px-3 rounded-lg bg-cyber-card/50 border border-white/[0.06]"
              >
                <span className="text-white font-medium truncate flex-1 mr-3">{doc.title}</span>
                <span className="text-slate-400 text-sm whitespace-nowrap">{doc.chunk_count} chunk</span>
                <button
                  type="button"
                  onClick={async () => { if (await showConfirm(`"${doc.title}" silinsin mi?`)) deleteRunbookDoc.mutate(doc.title) }}
                  disabled={deleteRunbookDoc.isPending}
                  className="ml-3 px-3 py-1.5 text-xs bg-red-600/20 text-red-400 border border-red-500/40 rounded-lg hover:bg-red-600/30 disabled:opacity-50"
                >
                  Sil
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="grid grid-cols-3 gap-4 mb-6">
        <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4">
          <p className="text-slate-400 text-sm">Runbook</p>
          <p className="text-2xl font-semibold text-white">{status?.runbook ?? 0} <span className="text-sm font-normal text-slate-500">chunk</span></p>
        </div>
        <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4">
          <p className="text-slate-400 text-sm">Incidents / Events</p>
          <p className="text-2xl font-semibold text-white">{status?.incidents ?? 0} <span className="text-sm font-normal text-slate-500">kayıt</span></p>
        </div>
        <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4">
          <p className="text-slate-400 text-sm">Metrik Açıklamaları</p>
          <p className="text-2xl font-semibold text-white">{status?.metrics ?? 0} <span className="text-sm font-normal text-slate-500">metrik</span></p>
        </div>
      </div>
      <div className="space-y-3">
        <button onClick={() => seedMetrics.mutate()} disabled={seedMetrics.isPending}
          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium">
          {seedMetrics.isPending ? 'Ekleniyor...' : 'Metrik Açıklamalarını Yükle (varsayılan)'}
        </button>
        <button onClick={() => reindexIncidents.mutate()} disabled={reindexIncidents.isPending}
          className="ml-3 px-4 py-2 bg-slate-600 hover:bg-slate-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium">
          {reindexIncidents.isPending ? 'Indexleniyor...' : "Incident'ları RAG'e Ekle"}
        </button>
        <button onClick={() => reindexEvents.mutate()} disabled={reindexEvents.isPending}
          className="ml-3 px-4 py-2 bg-slate-600 hover:bg-slate-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium">
          {reindexEvents.isPending ? 'Indexleniyor...' : "Event'leri RAG'e Ekle"}
        </button>
      </div>
      <div className="mt-6 bg-cyber-deep/30 rounded-[10px] border border-white/[0.06] p-4">
        <h4 className="text-sm font-medium text-slate-300 mb-2">Nasıl kullanılır?</h4>
        <ul className="text-xs text-slate-500 space-y-1">
          <li>• <strong>Metrik açıklamaları:</strong> Chat’te “bu metrik ne?” sorularında kullanılır. Yukarıdan yükleyin.</li>
          <li>• <strong>Incident’lar:</strong> Veritabanındaki incident’lar RAG’e eklenir; benzer geçmiş olaylar yanıtta kullanılır.</li>
          <li>• <strong>Runbook:</strong> Yukarıdan <strong>PDF yükleyebilir</strong> veya API’den <code className="bg-cyber-card px-1 rounded">POST /api/v1/rag/runbook/ingest</code> / <code className="bg-cyber-card px-1 rounded">/rag/runbook/ingest-pdf</code> ile metin/PDF ekleyebilirsiniz.</li>
        </ul>
      </div>
      {confirmState && <ConfirmModal message={confirmState.msg} onConfirm={() => { confirmState.resolve(true); setConfirmState(null) }} onCancel={() => { confirmState.resolve(false); setConfirmState(null) }} />}
    </div>
  )
}

interface AIModel { name: string; size: number; parameter_size: string; family: string }

const Settings: React.FC = () => {
  const [activeTab, setActiveTab] = useState('credentials')
  const [showForm, setShowForm] = useState(false)
  const [editingCred, setEditingCred] = useState<Credential | null>(null)
  const [form, setForm] = useState({ name: '', username: '', password: '', private_key: '', sudo_password: '', port: 22 })
  const [applyModal, setApplyModal] = useState<{ open: boolean; credId: number; credName: string }>({ open: false, credId: 0, credName: '' })
  const [applyMode, setApplyMode] = useState<'all' | 'select'>('all')
  const [selectedServerIds, setSelectedServerIds] = useState<number[]>([])
  const [setAiReady, setSetAiReady] = useState(true)
  const queryClient = useQueryClient()
  const [confirmState, setConfirmState] = React.useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))
  const [metricRetentionDays, setMetricRetentionDays] = useState<number>(30)
  const [selectedModel, setSelectedModel] = useState<string>(() => localStorage.getItem('chat_selected_model') || 'llama3.2:3b')
  const [modelSaved, setModelSaved] = useState(false)
  const [retentionSaved, setRetentionSaved] = useState(false)
  const { data: modelsData } = useQuery<{ success: boolean; models: AIModel[]; default: string }>({
    queryKey: ['ai-models'],
    queryFn: async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/chat/models`, { signal: AbortSignal.timeout(5000) })
        if (!res.ok) return { success: false, models: [], default: 'llama3.2:3b' }
        return res.json()
      } catch { return { success: false, models: [], default: 'llama3.2:3b' } }
    },
    staleTime: 60000,
  })
  const availableModels: AIModel[] = modelsData?.models?.length ? modelsData.models : []
  const { data: generalSettings } = useQuery<GeneralSettings>({
    queryKey: ['general-settings'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/settings/`)
      if (!res.ok) throw new Error('Ayarlar alınamadı')
      return res.json()
    },
    staleTime: 60000,
  })
  // Backend'den gelen aktif model ile sync et (ilk yüklemede localStorage yoksa)
  React.useEffect(() => {
    if (modelsData?.default && !localStorage.getItem('chat_selected_model')) {
      setSelectedModel(modelsData.default)
    } else if (modelsData?.default && modelsData.default !== 'llama3.2:3b') {
      // Backend'de kayıtlı model varsa onu öne çıkar
      const stored = localStorage.getItem('chat_selected_model')
      if (!stored || stored === 'llama3.2:3b') {
        setSelectedModel(modelsData.default)
        localStorage.setItem('chat_selected_model', modelsData.default)
      }
    }
  }, [modelsData?.default])

  React.useEffect(() => {
    if (generalSettings?.metric_retention_days) {
      setMetricRetentionDays(generalSettings.metric_retention_days)
    }
  }, [generalSettings?.metric_retention_days])

  // Queries
  const { data: credentials = [], isLoading: credsLoading } = useQuery<Credential[]>({
    queryKey: ['credentials'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/`)
      if (!res.ok) return []
      return res.json()
    }
  })

  const { data: servers = [] } = useQuery<Server[]>({
    queryKey: ['servers'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/servers/`)
      if (!res.ok) return []
      return res.json()
    }
  })

  // Mutations
  const createCred = useMutation({
    mutationFn: async (data: typeof form) => {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
      })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || 'Hata')
      return r
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['credentials'] }); resetForm() }
  })

  const updateCred = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: typeof form }) => {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/${id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
      })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || 'Hata')
      return r
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['credentials'] }); resetForm() }
  })

  const deleteCred = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Silinemedi')
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['credentials'] })
  })

  const setDefault = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/${id}/set-default`, { method: 'POST' })
      if (!res.ok) throw new Error('Hata')
      return res.json()
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['credentials'] })
  })

  const applyCred = useMutation({
    mutationFn: async ({ credId, serverIds, aiReady }: { credId: number; serverIds: number[] | null; aiReady: boolean }) => {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/${credId}/apply`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server_ids: serverIds, set_ai_ready: aiReady })
      })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || 'Hata')
      return r
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['servers'] })
      setApplyModal({ open: false, credId: 0, credName: '' })
      alert(data.message)
    }
  })

  const checkAllServersSSH = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/test-all-ssh`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }
      })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || 'Hata')
      return r
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['servers'] })
      alert(`SSH Test tamamlandı!\n\n✅ Başarılı: ${data.successful}\n❌ Başarısız: ${data.failed}\n\n${data.message}`)
    },
    onError: (e) => alert(e instanceof Error ? e.message : 'SSH test hatası')
  })

  const saveMetricRetention = useMutation({
    mutationFn: async (days: number) => {
      const res = await fetch(`${API_BASE_URL}/settings/metric-retention`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days })
      })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || 'Metrik saklama süresi güncellenemedi')
      return r
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['general-settings'] })
      setRetentionSaved(true)
      setTimeout(() => setRetentionSaved(false), 3000)
      alert(`Metrik saklama süresi ${data.metric_retention_days} gün olarak güncellendi. ${data.deleted_rows ?? 0} eski kayıt silindi.`)
    },
    onError: (e) => alert(e instanceof Error ? e.message : 'Kaydetme hatası')
  })

  const resetForm = () => {
    setShowForm(false); setEditingCred(null)
    setForm({ name: '', username: '', password: '', private_key: '', sudo_password: '', port: 22 })
  }

  const openEdit = (c: Credential) => {
    setEditingCred(c); setShowForm(false)
    setForm({ name: c.name, username: c.username, password: '', private_key: '', sudo_password: '', port: c.port })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (editingCred) updateCred.mutate({ id: editingCred.id, data: form })
    else createCred.mutate(form)
  }

  const tabs = [
    { id: 'credentials', name: 'Global Credentials' },
    { id: 'ai', name: 'AI Ayarları' },
    { id: 'rag', name: 'RAG (Bilgi Tabanı)' },
    { id: 'monitoring', name: 'Monitoring' },
    { id: 'about', name: 'Hakkında' },
  ]

  return (
    <div className="flex gap-6 h-[calc(100vh-140px)]">
      {/* Sol Menu */}
      <div className="w-64 bg-cyber-card rounded-[10px] border border-white/[0.06] overflow-hidden flex-shrink-0">
        <div className="p-4 border-b border-white/[0.06]">
          <h2 className="text-lg font-semibold text-white">Ayarlar</h2>
        </div>
        <nav className="p-3">
          {tabs.map(tab => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id)}
              className={`w-full flex items-center px-4 py-2.5 rounded-lg text-left transition-all text-sm ${
                activeTab === tab.id ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30' : 'text-slate-400 hover:text-white hover:bg-white/[0.06]/50'
              }`}>
              <span className="font-medium">{tab.name}</span>
            </button>
          ))}
        </nav>
      </div>

      {/* Content */}
      <div className="flex-1 bg-cyber-card rounded-[10px] border border-white/[0.06] overflow-hidden min-w-0">
        <div className="p-6 h-full overflow-y-auto overflow-x-hidden">

          {/* ═══ Credentials ═══ */}
          {activeTab === 'credentials' && (
            <div>
              <div className="flex flex-wrap items-start gap-3 mb-6">
                <div className="flex-1 min-w-0">
                  <h2 className="text-xl font-semibold text-white">Global Credentials</h2>
                  <p className="text-slate-400 text-sm mt-1">SSH kimlik bilgilerini tanımlayın ve sunuculara toplu uygulayın</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button onClick={() => checkAllServersSSH.mutate()}
                    disabled={checkAllServersSSH.isPending}
                    className="px-3 py-2 bg-gradient-to-r from-emerald-600 to-emerald-700 text-white rounded-lg hover:from-emerald-500 hover:to-emerald-600 transition-all text-sm disabled:opacity-50 whitespace-nowrap">
                    {checkAllServersSSH.isPending ? 'Test Ediliyor...' : 'SSH Test & Update'}
                  </button>
                  <button onClick={() => { setShowForm(!showForm); setEditingCred(null); setForm({ name: '', username: '', password: '', private_key: '', sudo_password: '', port: 22 }) }}
                    className="px-3 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all text-sm whitespace-nowrap">
                    {showForm ? '✕ İptal' : '+ Yeni Credential'}
                  </button>
                </div>
              </div>

              {/* Form */}
              {(showForm || editingCred) && (
                <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-6 mb-6">
                  <h3 className="text-lg font-medium text-white mb-4">
                    {editingCred ? `"${editingCred.name}" Düzenle` : 'Yeni Credential Ekle'}
                  </h3>
                  <form onSubmit={handleSubmit} className="space-y-4">
                    <div className="grid grid-cols-3 gap-4">
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">İsim *</label>
                        <input type="text" required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
                          className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="örn: Production SSH" />
                      </div>
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">Kullanıcı Adı *</label>
                        <input type="text" required value={form.username} onChange={e => setForm({ ...form, username: e.target.value })}
                          className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="root" />
                      </div>
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">SSH Port</label>
                        <input type="number" value={form.port} onChange={e => setForm({ ...form, port: parseInt(e.target.value) || 22 })}
                          className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">Şifre {editingCred ? '(boş = değiştirme)' : '*'}</label>
                        <input type="password" required={!editingCred} value={form.password} onChange={e => setForm({ ...form, password: e.target.value })}
                          className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="••••••••" />
                      </div>
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">Sudo Şifresi (opsiyonel)</label>
                        <input type="password" value={form.sudo_password} onChange={e => setForm({ ...form, sudo_password: e.target.value })}
                          className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="opsiyonel" />
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm text-slate-300 mb-1.5">Private Key (opsiyonel)</label>
                      <textarea value={form.private_key} onChange={e => setForm({ ...form, private_key: e.target.value })}
                        className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-xs"
                        placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" rows={3} />
                    </div>
                    <div className="flex justify-between items-center pt-2">
                      {(createCred.isError || updateCred.isError) && (
                        <p className="text-red-400 text-sm">{(createCred.error || updateCred.error)?.message}</p>
                      )}
                      <div className="flex gap-3 ml-auto">
                        <button type="button" onClick={resetForm} className="px-4 py-2 bg-white/[0.07] text-white rounded-lg hover:bg-slate-600 text-sm">İptal</button>
                        <button type="submit" disabled={createCred.isPending || updateCred.isPending}
                          className="px-6 py-2 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-lg hover:from-green-500 hover:to-green-600 disabled:opacity-50 text-sm">
                          {(createCred.isPending || updateCred.isPending) ? 'Kaydediliyor...' : 'Kaydet'}
                        </button>
                      </div>
                    </div>
                  </form>
                </div>
              )}

              {/* List */}
              {credsLoading ? (
                <div className="text-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto"></div></div>
              ) : credentials.length === 0 ? (
                <div className="text-center py-12 bg-cyber-deep/30 rounded-xl border border-dashed border-white/[0.06]">
                  <span className="text-2xl font-bold text-blue-400 block mb-4">KEY</span>
                  <p className="text-slate-400 mb-2">Henüz credential eklenmemiş</p>
                  <p className="text-slate-500 text-sm">Yeni credential ekleyip tüm sunuculara toplu uygulayabilirsiniz</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {credentials.map(cred => (
                    <div key={cred.id} className={`rounded-xl border p-4 ${cred.is_default ? 'bg-blue-500/5 border-blue-500/30' : 'bg-cyber-deep/50 border-white/[0.06]'}`}>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-4">
                          <div className={`w-11 h-11 rounded-lg flex items-center justify-center ${cred.is_default ? 'bg-gradient-to-br from-blue-500 to-blue-600' : 'bg-gradient-to-br from-yellow-500 to-orange-500'}`}>
                            <span className="text-xs font-bold text-blue-400">KEY</span>
                          </div>
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <p className="text-white font-medium truncate max-w-[200px]">{cred.name}</p>
                              {cred.is_default && (
                                <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-400 border border-blue-500/30 font-medium whitespace-nowrap">VARSAYILAN</span>
                              )}
                            </div>
                            <p className="text-slate-400 text-sm font-mono mt-0.5 truncate">
                              {cred.username}@:{cred.port}
                              {cred.has_password && <span className="text-green-400 ml-2">● şifre</span>}
                              {cred.has_private_key && <span className="text-blue-400 ml-2">● key</span>}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <button onClick={() => { setApplyModal({ open: true, credId: cred.id, credName: cred.name }); setApplyMode('all'); setSelectedServerIds([]) }}
                            className="px-3 py-1.5 text-xs bg-green-500/10 text-green-400 border border-green-500/30 rounded-lg hover:bg-green-500/20 font-medium">
                            Uygula
                          </button>
                          {!cred.is_default && (
                            <button onClick={() => setDefault.mutate(cred.id)}
                              className="px-3 py-1.5 text-xs bg-blue-500/10 text-blue-400 border border-blue-500/30 rounded-lg hover:bg-blue-500/20" title="Varsayılan Yap">★</button>
                          )}
                          <button onClick={() => openEdit(cred)}
                            className="px-3 py-1.5 text-xs bg-white/[0.07] text-slate-300 rounded-lg hover:bg-slate-600" title="Düzenle">✎</button>
                          <button onClick={async () => { if (await showConfirm(`"${cred.name}" silinsin mi?`)) deleteCred.mutate(cred.id) }}
                            className="px-3 py-1.5 text-xs bg-red-500/10 text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/20" title="Sil">✕</button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

            </div>
          )}

          {/* ═══ AI ═══ */}
          {activeTab === 'ai' && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-6">AI Ayarları</h2>
              <div className="space-y-6">
                <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-6">
                  <h3 className="text-lg font-medium text-white mb-4">Ollama Model Seçimi</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">Varsayılan Model</label>
                      <select
                        value={selectedModel}
                        onChange={e => setSelectedModel(e.target.value)}
                        className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-200 focus:outline-none focus:border-blue-500"
                      >
                        {availableModels.length === 0 && (
                          <option value={selectedModel}>{selectedModel}</option>
                        )}
                        {availableModels.map(m => (
                          <option key={m.name} value={m.name}>
                            {m.name}{m.parameter_size ? ` — ${m.parameter_size}` : ''}
                          </option>
                        ))}
                      </select>
                      <p className="text-xs text-slate-500 mt-1">Chat ve Event analizi için varsayılan model (Ollama üzerinden)</p>
                    </div>
                    <div className="flex items-center gap-3 mt-4">
                      <button
                        onClick={async () => {
                          localStorage.setItem('chat_selected_model', selectedModel)
                          await fetch(`${API_BASE_URL}/settings/ollama-model`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ model: selectedModel })
                          })
                          setModelSaved(true)
                          setTimeout(() => setModelSaved(false), 3000)
                        }}
                        className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors">
                        Kaydet
                      </button>
                      {modelSaved && (
                        <span className="text-green-400 text-sm flex items-center gap-1">
                          Model kaydedildi
                        </span>
                      )}
                    </div>
                  </div>


                </div>
                <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4 flex items-center space-x-3">
                  <span className="text-sm font-semibold text-green-400">OK</span>
                  <div><p className="text-green-400 font-medium">AI Servisi Aktif — Tam Lokal</p><p className="text-green-400/70 text-sm">Tüm veriler sunucuda kalır, dışarı çıkmaz</p></div>
                </div>
              </div>
            </div>
          )}

          {/* ═══ RAG ═══ */}
          {activeTab === 'rag' && (
            <RagTab />
          )}

          {/* ═══ Monitoring ═══ */}
          {activeTab === 'monitoring' && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-6">Monitoring Ayarları</h2>
              <div className="space-y-6">
                <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-6">
                  <h3 className="text-lg font-medium text-white mb-4">Prometheus</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">Prometheus URL</label>
                      <input type="text" value="http://prometheus:9090" disabled className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-400 cursor-not-allowed" />
                    </div>
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">Pushgateway URL</label>
                      <input type="text" value="http://pushgateway:9091" disabled className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-400 cursor-not-allowed" />
                    </div>
                    {/* Yönetim Sunucu IP */}
                    <div className="border-t border-white/[0.06] pt-4">
                      <label className="block text-sm text-slate-300 mb-1">
                        Yönetim Sunucusu IP
                        <span className="text-xs text-slate-500 ml-2">— Local repo & SSH için</span>
                      </label>
                      <p className="text-xs text-slate-500 mb-2">
                        Sunucuların bu uygulamaya erişmek için kullandığı IP. Local repo .repo dosyasında kullanılır.
                        {generalSettings?.detected_management_ip && (
                          <span className="text-blue-400 ml-1">(Otomatik tespit: {generalSettings.detected_management_ip})</span>
                        )}
                      </p>
                      <div className="flex items-center gap-3">
                        <input
                          type="text"
                          defaultValue={generalSettings?.management_server_ip || ''}
                          id="mgmt-ip-input"
                          placeholder={generalSettings?.detected_management_ip || '192.168.1.x'}
                          className="bg-cyber-card border border-slate-600 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 w-48 font-mono"
                        />
                        <button
                          onClick={async () => {
                            const val = (document.getElementById('mgmt-ip-input') as HTMLInputElement).value.trim()
                            const ip = val || generalSettings?.detected_management_ip || ''
                            if (!ip) { alert('IP girin'); return }
                            const r = await fetch('/api/v1/settings/management-server-ip', {
                              method: 'PUT', headers: {'Content-Type':'application/json'},
                              body: JSON.stringify({ip})
                            })
                            if (r.ok) alert(`✓ Yönetim IP kaydedildi: ${ip}`)
                            else alert('Hata')
                          }}
                          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium"
                        >
                          Kaydet
                        </button>
                      </div>
                    </div>

                    <div className="border-t border-white/[0.06] pt-4">
                      <label className="block text-sm text-slate-300 mb-2">Metrik Saklama Süresi (gün)</label>
                      <div className="flex items-center gap-3">
                        <select
                          value={metricRetentionDays}
                          onChange={e => setMetricRetentionDays(Number(e.target.value))}
                          className="bg-cyber-card border border-slate-600 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500"
                        >
                          <option value={7}>7 gün</option>
                          <option value={15}>15 gün</option>
                          <option value={30}>30 gün</option>
                          <option value={60}>60 gün</option>
                          <option value={90}>90 gün</option>
                          <option value={180}>180 gün</option>
                          <option value={365}>365 gün</option>
                        </select>
                        <button
                          onClick={async () => {
                            const currentDays = generalSettings?.metric_retention_days ?? 30
                            const isDecrease = metricRetentionDays < currentDays
                            const message = isDecrease
                              ? `Saklama süresi ${currentDays} günden ${metricRetentionDays} güne düşürülecek.\n${metricRetentionDays} günden eski metrik kayıtları silinecek.\n\nDevam etmek istiyor musunuz?`
                              : `Metrik saklama süresi ${metricRetentionDays} gün olarak güncellensin mi?`
                            if (!await showConfirm(message)) return
                            saveMetricRetention.mutate(metricRetentionDays)
                          }}
                          disabled={saveMetricRetention.isPending}
                          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium"
                        >
                          {saveMetricRetention.isPending ? 'Kaydediliyor...' : 'Kaydet'}
                        </button>
                        {retentionSaved && <span className="text-green-400 text-sm font-medium">Kaydedildi</span>}
                      </div>
                      <p className="text-xs text-slate-500 mt-2">
                        Süre düşürülürse (ör. 30 → 15), 15 günden eski metrik kayıtları hemen silinir.
                      </p>
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <a href="http://192.168.1.222:9090" target="_blank" rel="noopener noreferrer" className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4 hover:border-slate-600 transition-colors flex items-center space-x-3">
                    <div className="w-8 h-8 rounded bg-orange-500/20 flex items-center justify-center flex-shrink-0"></div><div><p className="text-white font-medium">Prometheus</p><p className="text-slate-400 text-sm">Metrics & Queries</p></div>
                  </a>
                  <a href="http://192.168.1.222:9091" target="_blank" rel="noopener noreferrer" className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4 hover:border-slate-600 transition-colors flex items-center space-x-3">
                    <span className="text-2xl">📊</span><div><p className="text-white font-medium">Pushgateway</p><p className="text-slate-400 text-sm">Push Metrics</p></div>
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* ═══ About ═══ */}
          {activeTab === 'about' && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-6">Hakkında</h2>
              <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-6">
                <div className="flex items-center space-x-4 mb-6">
                  <div className="w-16 h-16 bg-gradient-to-br from-blue-500 to-blue-600 rounded-2xl flex items-center justify-center shadow-lg">
                    <span className="text-white font-bold text-2xl">SM</span>
                  </div>
                  <div><h3 className="text-2xl font-bold text-white">datatem AI</h3><p className="text-slate-400">v1.0.0 - AI Infrastructure Management</p></div>
                </div>
                <div className="grid grid-cols-2 gap-4 pt-4">
                  <div className="bg-cyber-card rounded-lg p-4"><p className="text-slate-400 text-sm">Backend</p><p className="text-white font-medium">FastAPI + Python</p></div>
                  <div className="bg-cyber-card rounded-lg p-4"><p className="text-slate-400 text-sm">Frontend</p><p className="text-white font-medium">React + TypeScript</p></div>
                  <div className="bg-cyber-card rounded-lg p-4"><p className="text-slate-400 text-sm">Database</p><p className="text-white font-medium">PostgreSQL</p></div>
                  <div className="bg-cyber-card rounded-lg p-4"><p className="text-slate-400 text-sm">AI</p><p className="text-white font-medium">Ollama + LLaMA</p></div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ═══ Apply Modal ═══ */}
      {applyModal.open && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-cyber-card rounded-[10px] border border-white/[0.06] p-6 w-full max-w-2xl shadow-2xl max-h-[80vh] overflow-hidden flex flex-col">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-xl font-semibold text-white">Credential Uygula</h2>
                <p className="text-sm text-slate-400 mt-1">
                  <span className="text-blue-400 font-medium">"{applyModal.credName}"</span> credential'ını sunuculara uygula
                </p>
              </div>
              <button onClick={() => setApplyModal({ open: false, credId: 0, credName: '' })} className="text-slate-400 hover:text-white text-xl">✕</button>
            </div>

            <div className="flex gap-3 mb-4">
              <button onClick={() => setApplyMode('all')}
                className={`flex-1 py-3 rounded-lg text-sm font-medium transition-all ${applyMode === 'all' ? 'bg-blue-600/20 text-blue-400 border-2 border-blue-500/50' : 'bg-white/[0.07] text-slate-400 border-2 border-transparent hover:bg-slate-600'}`}>
                🌐 Tüm Sunuculara ({servers.length})
              </button>
              <button onClick={() => setApplyMode('select')}
                className={`flex-1 py-3 rounded-lg text-sm font-medium transition-all ${applyMode === 'select' ? 'bg-blue-600/20 text-blue-400 border-2 border-blue-500/50' : 'bg-white/[0.07] text-slate-400 border-2 border-transparent hover:bg-slate-600'}`}>
                Seçili Sunuculara ({selectedServerIds.length})
              </button>
            </div>

            {applyMode === 'select' && (
              <div className="flex-1 overflow-y-auto mb-4 border border-white/[0.06] rounded-lg max-h-60">
                {servers.map(s => (
                  <label key={s.id} className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-white/[0.06]/50 border-b border-white/[0.04] last:border-b-0 ${selectedServerIds.includes(s.id) ? 'bg-blue-500/10' : ''}`}>
                    <input type="checkbox" checked={selectedServerIds.includes(s.id)}
                      onChange={() => setSelectedServerIds(prev => prev.includes(s.id) ? prev.filter(x => x !== s.id) : [...prev, s.id])}
                      className="w-4 h-4 text-blue-600 bg-white/[0.07] border-slate-600 rounded" />
                    <span className="text-sm text-white">{s.name}</span>
                    <span className="text-xs text-slate-500 font-mono">{s.ip_address}</span>
                    {s.ai_ready && <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30 ml-auto">AI</span>}
                  </label>
                ))}
              </div>
            )}

            <div className="flex items-center gap-2 mb-4">
              <input type="checkbox" checked={setAiReady} onChange={e => setSetAiReady(e.target.checked)}
                className="w-4 h-4 text-blue-600 bg-white/[0.07] border-slate-600 rounded" />
              <span className="text-sm text-slate-300">Sunucuları <strong className="text-blue-400">AI Ready</strong> olarak işaretle</span>
            </div>

            <div className="flex justify-end gap-3 pt-3 border-t border-white/[0.06]">
              <button onClick={() => setApplyModal({ open: false, credId: 0, credName: '' })}
                className="px-4 py-2.5 bg-white/[0.07] text-white rounded-lg hover:bg-slate-600 text-sm">İptal</button>
              <button onClick={() => applyCred.mutate({ credId: applyModal.credId, serverIds: applyMode === 'all' ? null : selectedServerIds, aiReady: setAiReady })}
                disabled={applyCred.isPending || (applyMode === 'select' && selectedServerIds.length === 0)}
                className="px-6 py-2.5 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-lg hover:from-green-500 hover:to-green-600 disabled:opacity-50 font-medium text-sm">
                {applyCred.isPending ? 'Uygulanıyor...' : `${applyMode === 'all' ? servers.length : selectedServerIds.length} Sunucuya Uygula`}
              </button>
            </div>

            {applyCred.isError && (
              <div className="mt-3 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">
                {applyCred.error?.message || 'Hata'}
              </div>
            )}
          </div>
        </div>
      )}
      {confirmState && <ConfirmModal message={confirmState.msg} onConfirm={() => { confirmState.resolve(true); setConfirmState(null) }} onCancel={() => { confirmState.resolve(false); setConfirmState(null) }} />}
    </div>
  )
}

export default Settings
