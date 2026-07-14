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
    { id: 'credentials', name: 'Global Credentials', icon: '🔑' },
    { id: 'ai', name: 'AI Ayarları', icon: '🤖' },
    { id: 'monitoring', name: 'Monitoring', icon: '📊' },
    { id: 'about', name: 'Hakkında', icon: 'ℹ️' },
  ]

  return (
    <div className="flex gap-6 h-[calc(100vh-140px)]">
      {/* Sol Menu */}
      <div className="w-64 bg-slate-800 rounded-xl border border-slate-700 overflow-hidden flex-shrink-0">
        <div className="p-4 border-b border-slate-700">
          <h2 className="text-lg font-semibold text-white">Ayarlar</h2>
        </div>
        <nav className="p-3">
          {tabs.map(tab => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id)}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-left transition-all ${
                activeTab === tab.id ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30' : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
              }`}>
              <span className="text-xl">{tab.icon}</span>
              <span className="font-medium">{tab.name}</span>
            </button>
          ))}
        </nav>
      </div>

      {/* Content */}
      <div className="flex-1 bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="p-6 h-full overflow-y-auto">

          {/* ═══ Credentials ═══ */}
          {activeTab === 'credentials' && (
            <div>
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-xl font-semibold text-white">Global Credentials</h2>
                  <p className="text-slate-400 text-sm mt-1">SSH kimlik bilgilerini tanımlayın ve sunuculara toplu uygulayın</p>
                </div>
                <button onClick={() => { setShowForm(!showForm); setEditingCred(null); setForm({ name: '', username: '', password: '', private_key: '', sudo_password: '', port: 22 }) }}
                  className="px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all text-sm">
                  {showForm ? '✕ İptal' : '➕ Yeni Credential'}
                </button>
              </div>

              {/* Form */}
              {(showForm || editingCred) && (
                <div className="bg-slate-900/50 rounded-xl border border-slate-700 p-6 mb-6">
                  <h3 className="text-lg font-medium text-white mb-4">
                    {editingCred ? `"${editingCred.name}" Düzenle` : 'Yeni Credential Ekle'}
                  </h3>
                  <form onSubmit={handleSubmit} className="space-y-4">
                    <div className="grid grid-cols-3 gap-4">
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">İsim *</label>
                        <input type="text" required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
                          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="örn: Production SSH" />
                      </div>
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">Kullanıcı Adı *</label>
                        <input type="text" required value={form.username} onChange={e => setForm({ ...form, username: e.target.value })}
                          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="root" />
                      </div>
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">SSH Port</label>
                        <input type="number" value={form.port} onChange={e => setForm({ ...form, port: parseInt(e.target.value) || 22 })}
                          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">Şifre {editingCred ? '(boş = değiştirme)' : '*'}</label>
                        <input type="password" required={!editingCred} value={form.password} onChange={e => setForm({ ...form, password: e.target.value })}
                          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="••••••••" />
                      </div>
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">Sudo Şifresi (opsiyonel)</label>
                        <input type="password" value={form.sudo_password} onChange={e => setForm({ ...form, sudo_password: e.target.value })}
                          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="opsiyonel" />
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm text-slate-300 mb-1.5">Private Key (opsiyonel)</label>
                      <textarea value={form.private_key} onChange={e => setForm({ ...form, private_key: e.target.value })}
                        className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-xs"
                        placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" rows={3} />
                    </div>
                    <div className="flex justify-between items-center pt-2">
                      {(createCred.isError || updateCred.isError) && (
                        <p className="text-red-400 text-sm">{(createCred.error || updateCred.error)?.message}</p>
                      )}
                      <div className="flex gap-3 ml-auto">
                        <button type="button" onClick={resetForm} className="px-4 py-2 bg-slate-700 text-white rounded-lg hover:bg-slate-600 text-sm">İptal</button>
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
                <div className="text-center py-12 bg-slate-900/30 rounded-xl border border-dashed border-slate-700">
                  <span className="text-4xl block mb-4">🔑</span>
                  <p className="text-slate-400 mb-2">Henüz credential eklenmemiş</p>
                  <p className="text-slate-500 text-sm">Yeni credential ekleyip tüm sunuculara toplu uygulayabilirsiniz</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {credentials.map(cred => (
                    <div key={cred.id} className={`rounded-xl border p-4 ${cred.is_default ? 'bg-blue-500/5 border-blue-500/30' : 'bg-slate-900/50 border-slate-700'}`}>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-4">
                          <div className={`w-11 h-11 rounded-lg flex items-center justify-center ${cred.is_default ? 'bg-gradient-to-br from-blue-500 to-blue-600' : 'bg-gradient-to-br from-yellow-500 to-orange-500'}`}>
                            <span className="text-white text-lg">🔑</span>
                          </div>
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="text-white font-medium">{cred.name}</p>
                              {cred.is_default && (
                                <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-400 border border-blue-500/30 font-medium">VARSAYILAN</span>
                              )}
                            </div>
                            <p className="text-slate-400 text-sm font-mono mt-0.5">
                              {cred.username}@:{cred.port}
                              {cred.has_password && <span className="text-green-400 ml-2">● şifre</span>}
                              {cred.has_private_key && <span className="text-purple-400 ml-2">● key</span>}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <button onClick={() => { setApplyModal({ open: true, credId: cred.id, credName: cred.name }); setApplyMode('all'); setSelectedServerIds([]) }}
                            className="px-3 py-1.5 text-xs bg-green-500/10 text-green-400 border border-green-500/30 rounded-lg hover:bg-green-500/20 font-medium">
                            🚀 Uygula
                          </button>
                          {!cred.is_default && (
                            <button onClick={() => setDefault.mutate(cred.id)}
                              className="px-3 py-1.5 text-xs bg-blue-500/10 text-blue-400 border border-blue-500/30 rounded-lg hover:bg-blue-500/20" title="Varsayılan Yap">⭐</button>
                          )}
                          <button onClick={() => openEdit(cred)}
                            className="px-3 py-1.5 text-xs bg-slate-700 text-slate-300 rounded-lg hover:bg-slate-600" title="Düzenle">✏️</button>
                          <button onClick={() => { if (confirm(`"${cred.name}" silinsin mi?`)) deleteCred.mutate(cred.id) }}
                            className="px-3 py-1.5 text-xs bg-red-500/10 text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/20" title="Sil">🗑️</button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

              <div className="mt-6 bg-slate-900/30 rounded-xl border border-slate-700 p-4">
                <h4 className="text-sm font-medium text-slate-300 mb-2">Nasıl Kullanılır?</h4>
                <ul className="text-xs text-slate-500 space-y-1">
                  <li>1. <strong>Yeni Credential</strong> ekleyin (SSH kullanıcı adı, şifre veya private key)</li>
                  <li>2. <strong>Uygula</strong> butonuyla tüm sunuculara veya seçili sunuculara toplu atayın</li>
                  <li>3. <strong>Varsayılan</strong> olarak işaretlerseniz yeni sunucularda otomatik kullanılır</li>
                  <li>4. Credential uygulandığında sunucular otomatik olarak <strong>AI Ready</strong> olur</li>
                </ul>
              </div>
            </div>
          )}

          {/* ═══ AI ═══ */}
          {activeTab === 'ai' && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-6">AI Ayarları</h2>
              <div className="space-y-6">
                <div className="bg-slate-900/50 rounded-xl border border-slate-700 p-6">
                  <h3 className="text-lg font-medium text-white mb-4">Ollama Yapılandırması</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">Ollama URL</label>
                      <input type="text" value="http://192.168.1.222:11434" disabled className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-slate-400 cursor-not-allowed" />
                      <p className="text-xs text-slate-500 mt-1">Ortam değişkeni ile ayarlanır (OLLAMA_URL)</p>
                    </div>
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">Varsayılan Model</label>
                      <input type="text" value="llama3:70b" disabled className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-slate-400 cursor-not-allowed" />
                    </div>
                  </div>
                </div>
                <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4 flex items-center space-x-3">
                  <span className="text-2xl">✅</span>
                  <div><p className="text-green-400 font-medium">AI Servisi Aktif</p><p className="text-green-400/70 text-sm">Ollama bağlantısı başarılı</p></div>
                </div>
              </div>
            </div>
          )}

          {/* ═══ Monitoring ═══ */}
          {activeTab === 'monitoring' && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-6">Monitoring Ayarları</h2>
              <div className="space-y-6">
                <div className="bg-slate-900/50 rounded-xl border border-slate-700 p-6">
                  <h3 className="text-lg font-medium text-white mb-4">Prometheus</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">Prometheus URL</label>
                      <input type="text" value="http://prometheus:9090" disabled className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-slate-400 cursor-not-allowed" />
                    </div>
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">Pushgateway URL</label>
                      <input type="text" value="http://pushgateway:9091" disabled className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-slate-400 cursor-not-allowed" />
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <a href="http://192.168.1.222:9090" target="_blank" rel="noopener noreferrer" className="bg-slate-900/50 rounded-xl border border-slate-700 p-4 hover:border-slate-600 transition-colors flex items-center space-x-3">
                    <span className="text-2xl">📈</span><div><p className="text-white font-medium">Prometheus</p><p className="text-slate-400 text-sm">Metrics & Queries</p></div>
                  </a>
                  <a href="http://192.168.1.222:9091" target="_blank" rel="noopener noreferrer" className="bg-slate-900/50 rounded-xl border border-slate-700 p-4 hover:border-slate-600 transition-colors flex items-center space-x-3">
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
              <div className="bg-slate-900/50 rounded-xl border border-slate-700 p-6">
                <div className="flex items-center space-x-4 mb-6">
                  <div className="w-16 h-16 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg">
                    <span className="text-white font-bold text-2xl">SM</span>
                  </div>
                  <div><h3 className="text-2xl font-bold text-white">Server Manager</h3><p className="text-slate-400">v1.0.0 - Enterprise AIOps Platform</p></div>
                </div>
                <div className="grid grid-cols-2 gap-4 pt-4">
                  <div className="bg-slate-800 rounded-lg p-4"><p className="text-slate-400 text-sm">Backend</p><p className="text-white font-medium">FastAPI + Python</p></div>
                  <div className="bg-slate-800 rounded-lg p-4"><p className="text-slate-400 text-sm">Frontend</p><p className="text-white font-medium">React + TypeScript</p></div>
                  <div className="bg-slate-800 rounded-lg p-4"><p className="text-slate-400 text-sm">Database</p><p className="text-white font-medium">PostgreSQL</p></div>
                  <div className="bg-slate-800 rounded-lg p-4"><p className="text-slate-400 text-sm">AI</p><p className="text-white font-medium">Ollama + LLaMA</p></div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ═══ Apply Modal ═══ */}
      {applyModal.open && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 w-full max-w-2xl shadow-2xl max-h-[80vh] overflow-hidden flex flex-col">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-xl font-semibold text-white">🚀 Credential Uygula</h2>
                <p className="text-sm text-slate-400 mt-1">
                  <span className="text-blue-400 font-medium">"{applyModal.credName}"</span> credential'ını sunuculara uygula
                </p>
              </div>
              <button onClick={() => setApplyModal({ open: false, credId: 0, credName: '' })} className="text-slate-400 hover:text-white text-xl">✕</button>
            </div>

            <div className="flex gap-3 mb-4">
              <button onClick={() => setApplyMode('all')}
                className={`flex-1 py-3 rounded-lg text-sm font-medium transition-all ${applyMode === 'all' ? 'bg-blue-600/20 text-blue-400 border-2 border-blue-500/50' : 'bg-slate-700 text-slate-400 border-2 border-transparent hover:bg-slate-600'}`}>
                🌐 Tüm Sunuculara ({servers.length})
              </button>
              <button onClick={() => setApplyMode('select')}
                className={`flex-1 py-3 rounded-lg text-sm font-medium transition-all ${applyMode === 'select' ? 'bg-blue-600/20 text-blue-400 border-2 border-blue-500/50' : 'bg-slate-700 text-slate-400 border-2 border-transparent hover:bg-slate-600'}`}>
                ✅ Seçili Sunuculara ({selectedServerIds.length})
              </button>
            </div>

            {applyMode === 'select' && (
              <div className="flex-1 overflow-y-auto mb-4 border border-slate-700 rounded-lg max-h-60">
                {servers.map(s => (
                  <label key={s.id} className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-slate-700/50 border-b border-slate-700/50 last:border-b-0 ${selectedServerIds.includes(s.id) ? 'bg-blue-500/10' : ''}`}>
                    <input type="checkbox" checked={selectedServerIds.includes(s.id)}
                      onChange={() => setSelectedServerIds(prev => prev.includes(s.id) ? prev.filter(x => x !== s.id) : [...prev, s.id])}
                      className="w-4 h-4 text-blue-600 bg-slate-700 border-slate-600 rounded" />
                    <span className="text-sm text-white">{s.name}</span>
                    <span className="text-xs text-slate-500 font-mono">{s.ip_address}</span>
                    {s.ai_ready && <span className="text-[10px] px-1.5 py-0.5 rounded bg-purple-500/20 text-purple-400 border border-purple-500/30 ml-auto">AI</span>}
                  </label>
                ))}
              </div>
            )}

            <div className="flex items-center gap-2 mb-4">
              <input type="checkbox" checked={setAiReady} onChange={e => setSetAiReady(e.target.checked)}
                className="w-4 h-4 text-blue-600 bg-slate-700 border-slate-600 rounded" />
              <span className="text-sm text-slate-300">Sunucuları <strong className="text-purple-400">AI Ready</strong> olarak işaretle</span>
            </div>

            <div className="flex justify-end gap-3 pt-3 border-t border-slate-700">
              <button onClick={() => setApplyModal({ open: false, credId: 0, credName: '' })}
                className="px-4 py-2.5 bg-slate-700 text-white rounded-lg hover:bg-slate-600 text-sm">İptal</button>
              <button onClick={() => applyCred.mutate({ credId: applyModal.credId, serverIds: applyMode === 'all' ? null : selectedServerIds, aiReady: setAiReady })}
                disabled={applyCred.isPending || (applyMode === 'select' && selectedServerIds.length === 0)}
                className="px-6 py-2.5 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-lg hover:from-green-500 hover:to-green-600 disabled:opacity-50 font-medium text-sm">
                {applyCred.isPending ? '⏳ Uygulanıyor...' : `🚀 ${applyMode === 'all' ? servers.length : selectedServerIds.length} Sunucuya Uygula`}
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
    </div>
  )
}

export default Settings
