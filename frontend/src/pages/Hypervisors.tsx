import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'

const API_BASE_URL = 'http://192.168.1.166:8000/api/v1'

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
  const [formData, setFormData] = useState({
    name: '',
    type: 'vmware',
    hostname: '',
    ip_address: '',
    port: 443,
    username: '',
    password: ''
  })

  const queryClient = useQueryClient()

  const { data: hypervisors = [], isLoading } = useQuery<Hypervisor[]>({
    queryKey: ['hypervisors'],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/hypervisors/`)
      if (!response.ok) throw new Error('Failed to fetch hypervisors')
      return response.json()
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

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate(formData)
  }

  const getTypeIcon = (type: string) => {
    const icons: Record<string, string> = {
      vmware: '🟢',
      hyperv: '🔵',
      kvm: '🟠',
      xen: '🟣',
      proxmox: '🔴'
    }
    return icons[type.toLowerCase()] || '☁️'
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-slate-400">Toplam {hypervisors.length} hypervisor</p>
        <button
          onClick={() => setShowAddModal(true)}
          className="inline-flex items-center px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all shadow-lg shadow-blue-500/25"
        >
          <span className="mr-2">➕</span>
          Yeni Hypervisor
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
              <div className={`h-2 bg-gradient-to-r ${getTypeColor(hv.type)}`} />
              <div className="p-6">
                <div className="flex items-start justify-between mb-4">
                  <div className="flex items-center space-x-3">
                    <div className={`w-12 h-12 rounded-xl bg-gradient-to-br ${getTypeColor(hv.type)} flex items-center justify-center shadow-lg`}>
                      <span className="text-2xl">{getTypeIcon(hv.type)}</span>
                    </div>
                    <div>
                      <h3 className="text-lg font-semibold text-white">{hv.name}</h3>
                      <span className="inline-flex items-center px-2 py-0.5 rounded text-xs font-medium bg-slate-700 text-slate-300">
                        {hv.type.toUpperCase()}
                      </span>
                    </div>
                  </div>
                  <button
                    onClick={() => {
                      if (confirm('Bu hypervisor\'ı silmek istediğinize emin misiniz?')) {
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
                  <div className="flex items-center text-slate-400">
                    <span className="w-20">Host:</span>
                    <span className="text-white font-mono">{hv.hostname || '-'}</span>
                  </div>
                  <div className="flex items-center text-slate-400">
                    <span className="w-20">IP:</span>
                    <span className="text-white font-mono">{hv.ip_address}:{hv.port}</span>
                  </div>
                  {hv.username && (
                    <div className="flex items-center text-slate-400">
                      <span className="w-20">User:</span>
                      <span className="text-white">{hv.username}</span>
                    </div>
                  )}
                </div>
                <div className="mt-4 pt-4 border-t border-slate-700 flex justify-between">
                  <button className="text-blue-400 hover:text-blue-300 text-sm transition-colors">
                    🔄 Sync
                  </button>
                  <button className="text-slate-400 hover:text-white text-sm transition-colors">
                    ⚙️ Ayarlar
                  </button>
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
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="örn: vCenter Production"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Tip *</label>
                <select
                  value={formData.type}
                  onChange={(e) => setFormData({ ...formData, type: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                >
                  <option value="vmware">VMware vCenter / ESXi</option>
                  <option value="hyperv">Microsoft Hyper-V</option>
                  <option value="kvm">KVM / OLVM</option>
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
                    onChange={(e) => setFormData({ ...formData, ip_address: e.target.value })}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                    placeholder="192.168.1.100"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-slate-300 mb-2">Port</label>
                  <input
                    type="number"
                    value={formData.port}
                    onChange={(e) => setFormData({ ...formData, port: parseInt(e.target.value) || 443 })}
                    className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Kullanıcı Adı</label>
                <input
                  type="text"
                  value={formData.username}
                  onChange={(e) => setFormData({ ...formData, username: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="administrator@vsphere.local"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Şifre</label>
                <input
                  type="password"
                  value={formData.password}
                  onChange={(e) => setFormData({ ...formData, password: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-700 rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="••••••••"
                />
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
                <p className="text-red-400 text-sm">
                  Hata: {createMutation.error instanceof Error ? createMutation.error.message : 'Bilinmeyen hata'}
                </p>
              )}
            </form>
          </div>
        </div>
      )}
    </div>
  )
}

export default Hypervisors
