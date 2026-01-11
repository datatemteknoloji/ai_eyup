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
}

const Hypervisors: React.FC = () => {
  const [showAddForm, setShowAddForm] = useState(false)
  const [formData, setFormData] = useState({
    name: '',
    type: 'vmware',
    hostname: '',
    ip_address: '',
    port: 443
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
    mutationFn: async (data: any) => {
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
      setShowAddForm(false)
      setFormData({ name: '', type: 'vmware', hostname: '', ip_address: '', port: 443 })
    }
  })

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    createMutation.mutate(formData)
  }

  if (isLoading) {
    return <div className="text-center py-8">Yükleniyor...</div>
  }

  return (
    <div className="px-4 sm:px-6 lg:px-8">
      <div className="sm:flex sm:items-center mb-6">
        <div className="sm:flex-auto">
          <h1 className="text-2xl font-semibold text-gray-900">Hypervisor'lar</h1>
          <p className="mt-2 text-sm text-gray-700">Tüm hypervisor'ları görüntüleyin ve yönetin</p>
        </div>
        <div className="mt-4 sm:mt-0 sm:ml-16 sm:flex-none">
          <button
            onClick={() => setShowAddForm(!showAddForm)}
            className="block rounded-md bg-blue-600 px-3 py-2 text-center text-sm font-semibold text-white shadow-sm hover:bg-blue-500"
          >
            {showAddForm ? 'İptal' : 'Yeni Hypervisor Ekle'}
          </button>
        </div>
      </div>

      {showAddForm && (
        <div className="bg-white shadow rounded-lg p-6 mb-6">
          <h2 className="text-lg font-medium mb-4">Yeni Hypervisor Ekle</h2>
          <form onSubmit={handleSubmit}>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <div>
                <label className="block text-sm font-medium text-gray-700">İsim *</label>
                <input
                  type="text"
                  required
                  value={formData.name}
                  onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Tip *</label>
                <select
                  required
                  value={formData.type}
                  onChange={(e) => setFormData({ ...formData, type: e.target.value })}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                >
                  <option value="vmware">VMware</option>
                  <option value="hyperv">Hyper-V</option>
                  <option value="kvm">KVM</option>
                  <option value="xen">Xen</option>
                  <option value="proxmox">Proxmox</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Hostname</label>
                <input
                  type="text"
                  value={formData.hostname}
                  onChange={(e) => setFormData({ ...formData, hostname: e.target.value })}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">IP Adresi</label>
                <input
                  type="text"
                  value={formData.ip_address}
                  onChange={(e) => setFormData({ ...formData, ip_address: e.target.value })}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-gray-700">Port</label>
                <input
                  type="number"
                  value={formData.port}
                  onChange={(e) => setFormData({ ...formData, port: parseInt(e.target.value) || 443 })}
                  className="mt-1 block w-full rounded-md border-gray-300 shadow-sm focus:border-blue-500 focus:ring-blue-500 sm:text-sm"
                />
              </div>
            </div>
            <div className="mt-4">
              <button
                type="submit"
                disabled={createMutation.isPending}
                className="rounded-md bg-blue-600 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-blue-500 disabled:opacity-50"
              >
                {createMutation.isPending ? 'Ekleniyor...' : 'Ekle'}
              </button>
              {createMutation.isError && (
                <p className="mt-2 text-sm text-red-600">
                  Hata: {createMutation.error instanceof Error ? createMutation.error.message : 'Bilinmeyen hata'}
                </p>
              )}
            </div>
          </form>
        </div>
      )}

      {hypervisors.length === 0 && !showAddForm ? (
        <div className="bg-white shadow rounded-lg p-6 text-center">
          <p className="text-gray-500">Henüz hypervisor eklenmemiş. Yeni hypervisor eklemek için yukarıdaki butona tıklayın.</p>
        </div>
      ) : (
        <div className="bg-white shadow overflow-hidden sm:rounded-md">
          <ul className="divide-y divide-gray-200">
            {hypervisors.map((hypervisor) => (
              <li key={hypervisor.id} className="px-6 py-4">
                <div className="flex items-center justify-between">
                  <div className="flex-1">
                    <div className="flex items-center">
                      <h3 className="text-sm font-medium text-gray-900">{hypervisor.name}</h3>
                      <span className="ml-2 inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium bg-blue-100 text-blue-800">
                        {hypervisor.type.toUpperCase()}
                      </span>
                    </div>
                    <div className="mt-1 text-sm text-gray-500">
                      {hypervisor.hostname} {hypervisor.ip_address && `• ${hypervisor.ip_address}:${hypervisor.port}`}
                    </div>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

export default Hypervisors
