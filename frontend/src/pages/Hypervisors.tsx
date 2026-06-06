import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

const ConfirmModal = ({ message, onConfirm, onCancel }: {
  message: string; onConfirm: () => void; onCancel: () => void
}) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
    <div className="bg-slate-800 border border-slate-600 rounded-2xl shadow-2xl p-6 max-w-sm w-full mx-4">
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
        <button onClick={onCancel} className="px-4 py-2 rounded-lg text-sm text-slate-300 hover:text-white bg-slate-700 hover:bg-slate-600 border border-slate-600 transition-colors">İptal</button>
        <button onClick={onConfirm} className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-600 hover:bg-red-500 border border-red-500/50 transition-colors">Onayla</button>
      </div>
    </div>
  </div>
)

interface Hypervisor {
  id: number
  name: string
  type: string
  hostname: string
  ip_address: string
  port: number
  username: string
  connection_config: any
}

const Hypervisors: React.FC = () => {
  const [showAddModal, setShowAddModal] = useState(false)
  const [confirmState, setConfirmState] = useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))
  const [formData, setFormData] = useState({
    name: '',
    type: 'vmware',
    hostname: '',
    ip_address: '',
    port: 443,
    username: '',
    password: ''
  })
  const [connectionTest, setConnectionTest] = useState<{
    tested: boolean
    success: boolean
    message: string
    details: string
  } | null>(null)
  const [testing, setTesting] = useState(false)

  const queryClient = useQueryClient()

  const { data: hypervisors = [], isLoading, isError, error, refetch } = useQuery<Hypervisor[]>({
    queryKey: ['hypervisors'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/hypervisors/`)
      const data = await response.json().catch(() => ({}))
      if (!response.ok) {
        const detail = typeof data?.detail === 'string' ? data.detail : data?.detail?.msg || JSON.stringify(data) || 'Hypervisor listesi alınamadı'
        throw new Error(detail)
      }
      if (!Array.isArray(data)) {
        throw new Error(data?.message || data?.error || 'Beklenmeyen yanıt')
      }
      return data
    }
  })

  const createMutation = useMutation({
    mutationFn: async (data: typeof formData) => {
      const response = await fetch(`${API_BASE_URL}/hypervisors/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Failed to create hypervisor')
      }
      return response.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hypervisors'] })
      setShowAddModal(false)
      setFormData({ name: '', type: 'vmware', hostname: '', ip_address: '', port: 443, username: '', password: '' })
    }
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      const response = await fetch(`${API_BASE_URL}/hypervisors/${id}`, { method: 'DELETE' })
      if (!response.ok) throw new Error('Failed to delete hypervisor')
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hypervisors'] })
    }
  })

  const syncVMsMutation = useMutation({
    mutationFn: async (hypervisorId: number) => {
      const response = await fetch(`${API_BASE_URL}/hypervisors/${hypervisorId}/sync-vms`, {
        method: 'POST'
      })
      if (!response.ok) {
        const error = await response.json()
        throw new Error(error.detail || 'Sync failed')
      }
      return response.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['servers'] })
      alert(`✅ ${data.synced_count} VM senkronize edildi!\n\nToplam: ${data.total_vms} VM bulundu\n${data.errors.length > 0 ? `\n⚠️ Hatalar:\n${data.errors.join('\n')}` : ''}`)
    },
    onError: (error: Error) => {
      alert(`❌ Sync hatası: ${error.message}`)
    }
  })

  const testConnection = async () => {
    setTesting(true)
    setConnectionTest(null)
    
    try {
      const response = await fetch(`${API_BASE_URL}/hypervisors/test-connection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          type: formData.type,
          hostname: formData.hostname || formData.ip_address,
          ip_address: formData.ip_address,
          port: formData.port,
          username: formData.username,
          password: formData.password
        })
      })
      
      const result = await response.json()
      setConnectionTest({
        tested: true,
        success: result.success,
        message: result.message,
        details: result.details || ''
      })
    } catch (error: any) {
      setConnectionTest({
        tested: true,
        success: false,
        message: '❌ Test başarısız',
        details: error.message || 'Bağlantı hatası'
      })
    } finally {
      setTesting(false)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    
    // Bağlantı testi yapılmadıysa veya başarısız olduysa uyar
    if (!connectionTest?.tested) {
      alert('⚠️ Lütfen önce "Bağlantıyı Test Et" butonuna basarak credential\'ları doğrulayın!')
      return
    }
    
    if (!connectionTest.success) {
      alert('❌ Bağlantı testi başarısız! Kullanıcı adı ve şifreyi kontrol edin.')
      return
    }
    
    createMutation.mutate(formData)
  }
  
  // Form değiştiğinde test sonucunu sıfırla
  const handleFormChange = (field: string, value: any) => {
    setFormData({ ...formData, [field]: value })
    setConnectionTest(null) // Form değişince test sonucunu sıfırla
  }

  const getTypeLabel = (type: string) => {
    const labels: Record<string, string> = {
      vmware: 'VM', hyperv: 'HV', kvm: 'KVM', xen: 'XEN', proxmox: 'PX'
    }
    return labels[type.toLowerCase()] || type.slice(0, 3).toUpperCase()
  }

  const getTypeColor = (type: string) => {
    const colors: Record<string, string> = {
      vmware: 'from-green-500 to-green-600',
      hyperv: 'from-blue-500 to-blue-600',
      kvm: 'from-orange-500 to-orange-600',
      xen: 'from-purple-500 to-purple-600',
      proxmox: 'from-red-500 to-red-600'
    }
    return colors[type.toLowerCase()] || 'from-slate-500 to-slate-600'
  }

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-500"></div>
      </div>
    )
  }

  if (isError) {
    return (
      <div className="flex flex-col items-center justify-center h-64 gap-4 p-6">
        <p className="text-red-400 font-medium">Hypervisor listesi yüklenemedi</p>
        <p className="text-slate-400 text-sm text-center max-w-md">
          {error instanceof Error ? error.message : 'Backend bağlantısını kontrol edin. API: ' + API_BASE_URL}
        </p>
        <button onClick={() => refetch()} className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg">
          Tekrar dene
        </button>
      </div>
    )
  }

  return (
    <>
      {confirmState && <ConfirmModal message={confirmState.msg} onConfirm={() => { confirmState.resolve(true); setConfirmState(null) }} onCancel={() => { confirmState.resolve(false); setConfirmState(null) }} />}
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-slate-400">Toplam {hypervisors.length} hypervisor</p>
        <button
          onClick={() => setShowAddModal(true)}
          className="inline-flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all shadow-lg shadow-blue-500/25"
        >
          + Yeni Hypervisor
        </button>
      </div>

      {/* Grid */}
      {hypervisors.length > 0 ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {hypervisors.map((hv) => (
            <div
              key={hv.id}
              className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden hover:border-slate-600 transition-all hover:shadow-lg hover:shadow-slate-900/50"
            >
              <div className="p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center space-x-3">
                    <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${getTypeColor(hv.type)} flex items-center justify-center shadow-lg`}>
                      <span className="text-sm font-bold text-white">{getTypeLabel(hv.type)}</span>
                    </div>
                    <div>
                      <h3 className="text-lg font-semibold text-white">{hv.name}</h3>
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-700 text-slate-300">
                        {hv.type.toUpperCase()}
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={async () => {
                      if (await showConfirm('Bu hypervisor\'ı silmek istediğinize emin misiniz?')) {
                        deleteMutation.mutate(hv.id)
                      }
                    }}
                    className="text-slate-500 hover:text-red-400 transition-colors p-1"
                    title="Sil"
                  >
                    🗑️
                  </button>
                </div>
                <div className="space-y-2 text-sm">
                  <div className="flex items-center text-slate-400 min-w-0">
                    <span className="w-20 flex-shrink-0">Host:</span>
                    <span className="text-white font-mono truncate" title={hv.hostname || '-'}>{hv.hostname || '-'}</span>
                  </div>
                  <div className="flex items-center text-slate-400 min-w-0">
                    <span className="w-20 flex-shrink-0">IP:</span>
                    <span className="text-white font-mono truncate">{hv.ip_address}:{hv.port}</span>
                  </div>
                  {hv.username && (
                    <div className="flex items-center text-slate-400 min-w-0">
                      <span className="w-20 flex-shrink-0">User:</span>
                      <span className="text-white truncate" title={hv.username}>{hv.username}</span>
                    </div>
                  )}
                </div>
                <div className="mt-4 pt-4 border-t border-slate-700 flex justify-between">
                  <button 
                    onClick={() => syncVMsMutation.mutate(hv.id)}
                    disabled={syncVMsMutation.isPending}
                    className="text-blue-400 hover:text-blue-300 text-sm transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
                  >
                    {syncVMsMutation.isPending ? (
                      <>
                        <div className="animate-spin rounded-full h-3 w-3 border-b-2 border-blue-400"></div>
                        <span>Syncing...</span>
                      </>
                    ) : (
                      <>
                        <span>🔄</span>
                        <span>Sync VMs</span>
                      </>
                    )}
                  </button>
                  <span className="text-slate-500 text-xs">
                    {hv.type.toUpperCase()}
                  </span>
                </div>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-12 text-center">
          <div className="w-16 h-16 bg-slate-700 rounded-full flex items-center justify-center mx-auto mb-4">
            <span className="text-3xl">☁️</span>
          </div>
          <h3 className="text-lg font-medium text-white mb-2">Henüz hypervisor eklenmemiş</h3>
          <p className="text-slate-400 mb-4">Sanal makinelerinizi yönetmek için bir hypervisor ekleyin</p>
          <button
            onClick={() => setShowAddModal(true)}
            className="inline-flex items-center px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all"
          >
            <span className="mr-2">➕</span>
            Hypervisor Ekle
          </button>
        </div>
      )}

      {/* Add Modal */}
      {showAddModal && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-6 w-full max-w-md shadow-2xl">
            <div className="flex items-center justify-between mb-6">
              <h2 className="text-xl font-semibold text-white">Yeni Hypervisor Ekle</h2>
              <button
                onClick={() => setShowAddModal(false)}
                className="text-slate-400 hover:text-white transition-colors"
              >
                ✕
              </button>
            </div>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Hypervisor Adı *</label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => handleFormChange('name', e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="örn: vCenter Production"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Tip *</label>
                <select
                  value={formData.type}
                  onChange={(e) => handleFormChange('type', e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="vmware">VMware vCenter / ESXi</option>
                  <option value="hyperv">Microsoft Hyper-V</option>
                  <option value="kvm">KVM / oVirt</option>
                  <option value="xen">Xen</option>
                  <option value="proxmox">Proxmox VE</option>
                </select>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-2">IP Adresi *</label>
                  <input
                    type="text"
                    required
                    value={formData.ip_address}
                    onChange={(e) => handleFormChange('ip_address', e.target.value)}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="192.168.1.100"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-2">Port</label>
                  <input
                    type="number"
                    value={formData.port}
                    onChange={(e) => handleFormChange('port', parseInt(e.target.value) || 443)}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Kullanıcı Adı *</label>
                <input
                  type="text"
                  required
                  value={formData.username}
                  onChange={(e) => handleFormChange('username', e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder={formData.type === 'kvm' ? 'örn. admin (@internal otomatik eklenir)' : 'administrator@vsphere.local'}
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Şifre *</label>
                <input
                  type="password"
                  required
                  value={formData.password}
                  onChange={(e) => handleFormChange('password', e.target.value)}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="••••••••"
                />
              </div>
              
              {/* Test Connection Button */}
              <div className="pt-2">
                <button
                  type="button"
                  onClick={testConnection}
                  disabled={testing || !formData.username || !formData.password}
                  className="w-full py-2.5 bg-purple-600/20 text-purple-400 border border-purple-500/30 rounded-lg hover:bg-purple-600/30 transition-all disabled:opacity-50 disabled:cursor-not-allowed font-medium flex items-center justify-center gap-2"
                >
                  {testing ? (
                    <>
                      <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-purple-400"></div>
                      <span>Test Ediliyor...</span>
                    </>
                  ) : (
                    <>
                      <span>🔌</span>
                      <span>Bağlantıyı Test Et</span>
                    </>
                  )}
                </button>
              </div>

              {/* Test Result */}
              {connectionTest && (
                <div className={`p-4 rounded-lg border ${
                  connectionTest.success 
                    ? 'bg-green-500/10 border-green-500/30' 
                    : 'bg-red-500/10 border-red-500/30'
                }`}>
                  <div className="flex items-start gap-3">
                    <span className="text-2xl">{connectionTest.success ? '✅' : '❌'}</span>
                    <div className="flex-1">
                      <p className={`font-medium ${
                        connectionTest.success ? 'text-green-400' : 'text-red-400'
                      }`}>
                        {connectionTest.message}
                      </p>
                      {connectionTest.details && (
                        <p className="text-sm text-slate-400 mt-1">{connectionTest.details}</p>
                      )}
                    </div>
                  </div>
                </div>
              )}

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
                  disabled={createMutation.isPending || !connectionTest?.success}
                  className="px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                  title={!connectionTest?.success ? 'Önce bağlantıyı test edin' : ''}
                >
                  {createMutation.isPending ? 'Ekleniyor...' : '➕ Hypervisor Ekle'}
                </button>
              </div>
              {createMutation.isError && (
                <p className="text-red-400 text-sm">
                  Hata: {createMutation.error instanceof Error ? createMutation.error.message : 'Bilinmeyen hata'}
                </p>
              )}
            </form>
          </div>
        </div>
      )}
    </div>
    </>
  )
}

export default Hypervisors
