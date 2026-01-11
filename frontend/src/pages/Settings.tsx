import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const API_BASE_URL = 'http://192.168.1.166:8000/api/v1'

interface GlobalCredential {
  id: number
  name: string
  username: string
  port: number
  created_at: string
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

  const { data: credentials = [], isLoading } = useQuery<GlobalCredential[]>({
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
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to create credential')
      }
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['credentials'] })
      setShowAddCredential(false)
      setCredentialForm({ name: '', username: '', password: '', port: 22 })
    }
  })

  const handleSubmitCredential = (e: React.FormEvent) => {
    e.preventDefault()
    createCredential.mutate(credentialForm)
  }

  return (
    <div className="px-4 sm:px-6 lg:px-8">
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-gray-900">Ayarlar</h1>
        <p className="mt-2 text-sm text-gray-700">Sistem ayarlarını yönetin</p>
      </div>

      {/* Tab Menü */}
      <div className="border-b border-gray-200 mb-6">
        <nav className="-mb-px flex space-x-8">
          <button
            onClick={() => setActiveTab('credentials')}
            className={`py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'credentials'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            Global Credentials
          </button>
          <button
            onClick={() => setActiveTab('ai')}
            className={`py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'ai'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            AI Ayarları
          </button>
          <button
            onClick={() => setActiveTab('monitoring')}
            className={`py-4 px-1 border-b-2 font-medium text-sm ${
              activeTab === 'monitoring'
                ? 'border-blue-500 text-blue-600'
                : 'border-transparent text-gray-500 hover:text-gray-700 hover:border-gray-300'
            }`}
          >
            Monitoring
          </button>
        </nav>
      </div>

      {/* Global Credentials Tab */}
      {activeTab === 'credentials' && (
        <div>
          <div className="flex justify-between items-center mb-4">
            <h2 className="text-lg font-medium text-gray-900">Global Credentials</h2>
            <button
              onClick={() => setShowAddCredential(!showAddCredential)}
              className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 text-sm"
            >
              {showAddCredential ? 'İptal' : 'Yeni Credential Ekle'}
            </button>
          </div>

          {showAddCredential && (
            <div className="bg-white shadow rounded-lg p-6 mb-6">
              <form onSubmit={handleSubmitCredential}>
                <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                  <div>
                    <label className="block text-sm font-medium text-gray-700">İsim *</label>
                    <input
                      type="text"
                      required
                      value={credentialForm.name}
                      onChange={(e) => setCredentialForm({ ...credentialForm, name: e.target.value })}
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Kullanıcı Adı *</label>
                    <input
                      type="text"
                      required
                      value={credentialForm.username}
                      onChange={(e) => setCredentialForm({ ...credentialForm, username: e.target.value })}
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Şifre *</label>
                    <input
                      type="password"
                      required
                      value={credentialForm.password}
                      onChange={(e) => setCredentialForm({ ...credentialForm, password: e.target.value })}
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                    />
                  </div>
                  <div>
                    <label className="block text-sm font-medium text-gray-700">Port</label>
                    <input
                      type="number"
                      value={credentialForm.port}
                      onChange={(e) => setCredentialForm({ ...credentialForm, port: parseInt(e.target.value) || 22 })}
                      className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                    />
                  </div>
                </div>
                <div className="mt-4">
                  <button
                    type="submit"
                    disabled={createCredential.isPending}
                    className="px-4 py-2 bg-blue-600 text-white rounded-md hover:bg-blue-700 text-sm disabled:opacity-50"
                  >
                    {createCredential.isPending ? 'Ekleniyor...' : 'Ekle'}
                  </button>
                  {createCredential.isError && (
                    <p className="mt-2 text-sm text-red-600">
                      Hata: {createCredential.error instanceof Error ? createCredential.error.message : 'Bilinmeyen hata'}
                    </p>
                  )}
                </div>
              </form>
            </div>
          )}

          {isLoading ? (
            <div className="text-center py-8">Yükleniyor...</div>
          ) : credentials.length === 0 ? (
            <div className="bg-white shadow rounded-lg p-6 text-center">
              <p className="text-gray-500">Henüz credential eklenmemiş.</p>
            </div>
          ) : (
            <div className="bg-white shadow overflow-hidden sm:rounded-md">
              <ul className="divide-y divide-gray-200">
                {credentials.map((cred) => (
                  <li key={cred.id} className="px-6 py-4">
                    <div className="flex items-center justify-between">
                      <div>
                        <h3 className="text-sm font-medium text-gray-900">{cred.name}</h3>
                        <p className="text-sm text-gray-500">
                          {cred.username}@:{cred.port}
                        </p>
                      </div>
                    </div>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </div>
      )}

      {/* AI Ayarları Tab */}
      {activeTab === 'ai' && (
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">AI Ayarları</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Ollama URL</label>
              <input
                type="text"
                defaultValue="http://ollama:11434"
                disabled
                className="mt-1 block w-full rounded-md border-gray-300 bg-gray-50 shadow-sm sm:text-sm"
              />
              <p className="mt-1 text-xs text-gray-500">Ortam değişkeni ile ayarlanır</p>
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Varsayılan Model</label>
              <input
                type="text"
                defaultValue="llama3.2:3b"
                disabled
                className="mt-1 block w-full rounded-md border-gray-300 bg-gray-50 shadow-sm sm:text-sm"
              />
            </div>
          </div>
        </div>
      )}

      {/* Monitoring Tab */}
      {activeTab === 'monitoring' && (
        <div className="bg-white shadow rounded-lg p-6">
          <h2 className="text-lg font-medium text-gray-900 mb-4">Monitoring Ayarları</h2>
          <div className="space-y-4">
            <div>
              <label className="block text-sm font-medium text-gray-700">Prometheus URL</label>
              <input
                type="text"
                defaultValue="http://prometheus:9090"
                disabled
                className="mt-1 block w-full rounded-md border-gray-300 bg-gray-50 shadow-sm sm:text-sm"
              />
            </div>
            <div>
              <label className="block text-sm font-medium text-gray-700">Pushgateway URL</label>
              <input
                type="text"
                defaultValue="http://pushgateway:9091"
                disabled
                className="mt-1 block w-full rounded-md border-gray-300 bg-gray-50 shadow-sm sm:text-sm"
              />
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export default Settings
