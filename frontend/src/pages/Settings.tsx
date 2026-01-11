import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const API_BASE_URL = 'http://192.168.1.166:8000/api/v1'

interface Credential {
  id: number
  name: string
  username: string
  port: number
}

const Settings: React.FC = () => {
  const [activeTab, setActiveTab] = useState('credentials')
  const [showAddCredential, setShowAddCredential] = useState(false)
  const [credentialForm, setCredentialForm] = useState({
    name: '',
    username: '',
    password: '',
    port: 22
  })

  const queryClient = useQueryClient()

  const { data: credentials = [], isLoading } = useQuery<Credential[]>({
    queryKey: ['credentials'],
    queryFn: async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/settings/credentials/`)
        if (!response.ok) return []
        return response.json()
      } catch {
        return []
      }
    }
  })

  const createCredential = useMutation({
    mutationFn: async (data: typeof credentialForm) => {
      const response = await fetch(`${API_BASE_URL}/settings/credentials/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      if (!response.ok) throw new Error('Failed to create credential')
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      setShowAddCredential(false)
      setCredentialForm({ name: '', username: '', password: '', port: 22 })
    }
  })

  const tabs = [
    { id: 'credentials', name: 'Global Credentials', icon: '🔑' },
    { id: 'ai', name: 'AI Ayarları', icon: '🤖' },
    { id: 'monitoring', name: 'Monitoring', icon: '📊' },
    { id: 'about', name: 'Hakkında', icon: 'ℹ️' },
  ]

  return (
    <div className="flex gap-6 h-[calc(100vh-140px)]">
      {/* Sol Menu */}
      <div className="w-64 bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="p-4 border-b border-slate-700">
          <h2 className="text-lg font-semibold text-white">Ayarlar</h2>
        </div>
        <nav className="p-3">
          {tabs.map(tab => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`w-full flex items-center space-x-3 px-4 py-3 rounded-lg text-left transition-all ${
                activeTab === tab.id
                  ? 'bg-blue-600/20 text-blue-400 border border-blue-500/30'
                  : 'text-slate-400 hover:text-white hover:bg-slate-700/50'
              }`}
            >
              <span className="text-xl">{tab.icon}</span>
              <span className="font-medium">{tab.name}</span>
            </button>
          ))}
        </nav>
      </div>

      {/* İçerik */}
      <div className="flex-1 bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
        <div className="p-6 h-full overflow-y-auto">
          {/* Credentials Tab */}
          {activeTab === 'credentials' && (
            <div>
              <div className="flex items-center justify-between mb-6">
                <div>
                  <h2 className="text-xl font-semibold text-white">Global Credentials</h2>
                  <p className="text-slate-400 text-sm mt-1">Sunuculara bağlanmak için kullanılacak kimlik bilgileri</p>
                </div>
                <button
                  onClick={() => setShowAddCredential(!showAddCredential)}
                  className="inline-flex items-center px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all"
                >
                  {showAddCredential ? '✕ İptal' : '➕ Yeni Credential'}
                </button>
              </div>

              {showAddCredential && (
                <div className="bg-slate-900/50 rounded-xl border border-slate-700 p-6 mb-6">
                  <h3 className="text-lg font-medium text-white mb-4">Yeni Credential Ekle</h3>
                  <form onSubmit={(e) => { e.preventDefault(); createCredential.mutate(credentialForm) }} className="space-y-4">
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm font-medium text-slate-300 mb-2">İsim *</label>
                        <input
                          type="text"
                          required
                          value={credentialForm.name}
                          onChange={(e) => setCredentialForm({ ...credentialForm, name: e.target.value })}
                          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                          placeholder="örn: Production SSH"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-slate-300 mb-2">Port</label>
                        <input
                          type="number"
                          value={credentialForm.port}
                          onChange={(e) => setCredentialForm({ ...credentialForm, port: parseInt(e.target.value) || 22 })}
                          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-slate-300 mb-2">Kullanıcı Adı *</label>
                        <input
                          type="text"
                          required
                          value={credentialForm.username}
                          onChange={(e) => setCredentialForm({ ...credentialForm, username: e.target.value })}
                          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                          placeholder="root"
                        />
                      </div>
                      <div>
                        <label className="block text-sm font-medium text-slate-300 mb-2">Şifre *</label>
                        <input
                          type="password"
                          required
                          value={credentialForm.password}
                          onChange={(e) => setCredentialForm({ ...credentialForm, password: e.target.value })}
                          className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                          placeholder="••••••••"
                        />
                      </div>
                    </div>
                    <div className="flex justify-end">
                      <button
                        type="submit"
                        disabled={createCredential.isPending}
                        className="px-4 py-2 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-lg hover:from-green-500 hover:to-green-600 transition-all disabled:opacity-50"
                      >
                        {createCredential.isPending ? 'Kaydediliyor...' : 'Kaydet'}
                      </button>
                    </div>
                  </form>
                </div>
              )}

              {isLoading ? (
                <div className="text-center py-12">
                  <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto"></div>
                </div>
              ) : credentials.length === 0 ? (
                <div className="text-center py-12 bg-slate-900/30 rounded-xl border border-dashed border-slate-700">
                  <span className="text-4xl block mb-4">🔑</span>
                  <p className="text-slate-400">Henüz credential eklenmemiş</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {credentials.map(cred => (
                    <div key={cred.id} className="bg-slate-900/50 rounded-xl border border-slate-700 p-4 flex items-center justify-between">
                      <div className="flex items-center space-x-4">
                        <div className="w-10 h-10 bg-gradient-to-br from-yellow-500 to-orange-500 rounded-lg flex items-center justify-center">
                          <span className="text-white">🔑</span>
                        </div>
                        <div>
                          <p className="text-white font-medium">{cred.name}</p>
                          <p className="text-slate-400 text-sm font-mono">{cred.username}@:{cred.port}</p>
                        </div>
                      </div>
                      <button className="text-slate-400 hover:text-red-400 transition-colors">
                        🗑️
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {/* AI Tab */}
          {activeTab === 'ai' && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-6">AI Ayarları</h2>
              <div className="space-y-6">
                <div className="bg-slate-900/50 rounded-xl border border-slate-700 p-6">
                  <h3 className="text-lg font-medium text-white mb-4">Ollama Yapılandırması</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-slate-300 mb-2">Ollama URL</label>
                      <input
                        type="text"
                        value="http://192.168.1.166:11434"
                        disabled
                        className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-slate-400 cursor-not-allowed"
                      />
                      <p className="text-xs text-slate-500 mt-1">Ortam değişkeni ile ayarlanır (OLLAMA_URL)</p>
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-slate-300 mb-2">Varsayılan Model</label>
                      <input
                        type="text"
                        value="llama3.2:3b"
                        disabled
                        className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-slate-400 cursor-not-allowed"
                      />
                    </div>
                  </div>
                </div>
                <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4 flex items-center space-x-3">
                  <span className="text-2xl">✅</span>
                  <div>
                    <p className="text-green-400 font-medium">AI Servisi Aktif</p>
                    <p className="text-green-400/70 text-sm">Ollama bağlantısı başarılı</p>
                  </div>
                </div>
              </div>
            </div>
          )}

          {/* Monitoring Tab */}
          {activeTab === 'monitoring' && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-6">Monitoring Ayarları</h2>
              <div className="space-y-6">
                <div className="bg-slate-900/50 rounded-xl border border-slate-700 p-6">
                  <h3 className="text-lg font-medium text-white mb-4">Prometheus</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm font-medium text-slate-300 mb-2">Prometheus URL</label>
                      <input
                        type="text"
                        value="http://prometheus:9090"
                        disabled
                        className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-slate-400 cursor-not-allowed"
                      />
                    </div>
                    <div>
                      <label className="block text-sm font-medium text-slate-300 mb-2">Pushgateway URL</label>
                      <input
                        type="text"
                        value="http://pushgateway:9091"
                        disabled
                        className="w-full bg-slate-800 border border-slate-600 rounded-lg px-4 py-2 text-slate-400 cursor-not-allowed"
                      />
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <a
                    href="http://192.168.1.166:9090"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="bg-slate-900/50 rounded-xl border border-slate-700 p-4 hover:border-slate-600 transition-colors flex items-center space-x-3"
                  >
                    <span className="text-2xl">📈</span>
                    <div>
                      <p className="text-white font-medium">Prometheus</p>
                      <p className="text-slate-400 text-sm">Metrics & Queries</p>
                    </div>
                  </a>
                  <a
                    href="http://192.168.1.166:9091"
                    target="_blank"
                    rel="noopener noreferrer"
                    className="bg-slate-900/50 rounded-xl border border-slate-700 p-4 hover:border-slate-600 transition-colors flex items-center space-x-3"
                  >
                    <span className="text-2xl">📊</span>
                    <div>
                      <p className="text-white font-medium">Pushgateway</p>
                      <p className="text-slate-400 text-sm">Push Metrics</p>
                    </div>
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* About Tab */}
          {activeTab === 'about' && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-6">Hakkında</h2>
              <div className="bg-slate-900/50 rounded-xl border border-slate-700 p-6">
                <div className="flex items-center space-x-4 mb-6">
                  <div className="w-16 h-16 bg-gradient-to-br from-blue-500 to-purple-600 rounded-2xl flex items-center justify-center shadow-lg">
                    <span className="text-white font-bold text-2xl">SM</span>
                  </div>
                  <div>
                    <h3 className="text-2xl font-bold text-white">Server Manager</h3>
                    <p className="text-slate-400">v1.0.0</p>
                  </div>
                </div>
                <div className="space-y-4 text-slate-300">
                  <p>
                    Sunucu yönetim sistemi - VMware, Hyper-V, KVM ve fiziksel sunucuları tek bir arayüzden yönetin.
                  </p>
                  <div className="grid grid-cols-2 gap-4 pt-4">
                    <div className="bg-slate-800 rounded-lg p-4">
                      <p className="text-slate-400 text-sm">Backend</p>
                      <p className="text-white font-medium">FastAPI + Python</p>
                    </div>
                    <div className="bg-slate-800 rounded-lg p-4">
                      <p className="text-slate-400 text-sm">Frontend</p>
                      <p className="text-white font-medium">React + TypeScript</p>
                    </div>
                    <div className="bg-slate-800 rounded-lg p-4">
                      <p className="text-slate-400 text-sm">Database</p>
                      <p className="text-white font-medium">PostgreSQL + TimescaleDB</p>
                    </div>
                    <div className="bg-slate-800 rounded-lg p-4">
                      <p className="text-slate-400 text-sm">AI</p>
                      <p className="text-white font-medium">Ollama + LLaMA</p>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}

export default Settings
