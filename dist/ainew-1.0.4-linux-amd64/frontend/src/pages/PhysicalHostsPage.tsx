import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { Server, ArrowLeft, RefreshCw, Plus, X } from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { inventoryHeaders } from '../lib/inventoryApi'

interface AddHostForm {
  name: string
  hostname: string
  ip_address: string
  os_type: string
  ssh_username: string
  ssh_password: string
  ssh_port: string
  sudo_password: string
  private_key: string
}

const EMPTY_FORM: AddHostForm = {
  name: '',
  hostname: '',
  ip_address: '',
  os_type: 'linux',
  ssh_username: '',
  ssh_password: '',
  ssh_port: '22',
  sudo_password: '',
  private_key: '',
}

function AddPhysicalHostModal({ onClose, onCreate, isPending, error }: {
  onClose: () => void
  onCreate: (data: AddHostForm) => void
  isPending: boolean
  error: string | null
}) {
  const [form, setForm] = useState<AddHostForm>(EMPTY_FORM)

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!form.name.trim() || !form.ip_address.trim()) return
    onCreate(form)
  }

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-cyber-card rounded-xl border border-white/[0.06] p-6 w-full max-w-md shadow-2xl">
        <div className="flex items-center justify-between mb-6">
          <h2 className="text-xl font-semibold text-white">Yeni Fiziksel Host Ekle</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white transition-colors">
            <X size={18} />
          </button>
        </div>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">Host Adı *</label>
            <input
              type="text" required value={form.name}
              onChange={e => setForm({ ...form, name: e.target.value })}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="örn: db-host-01"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">Hostname</label>
            <input
              type="text" value={form.hostname}
              onChange={e => setForm({ ...form, hostname: e.target.value })}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
              placeholder="örn: db-host-01.local"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">
              IP Adresi <span className="text-red-400">*</span>
            </label>
            <input
              type="text" required value={form.ip_address}
              onChange={e => setForm({ ...form, ip_address: e.target.value })}
              className={`w-full bg-cyber-deep border rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 ${!form.ip_address ? 'border-red-500/50' : 'border-white/[0.06]'}`}
              placeholder="örn: 192.168.1.50"
            />
            {!form.ip_address && <p className="text-red-400 text-xs mt-1">IP adresi zorunludur</p>}
          </div>
          <div>
            <label className="block text-sm font-medium text-slate-300 mb-2">İşletim Sistemi</label>
            <select
              value={form.os_type}
              onChange={e => setForm({ ...form, os_type: e.target.value })}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
            >
              <option value="linux">Linux</option>
              <option value="windows">Windows</option>
              <option value="other">Diğer</option>
            </select>
          </div>
          <div className="border-t border-white/[0.06] pt-4">
            <h3 className="text-sm font-semibold text-slate-200 mb-3">SSH Bilgileri (opsiyonel — Node Exporter kurulumu için)</h3>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Kullanıcı Adı</label>
                <input
                  type="text" value={form.ssh_username}
                  onChange={e => setForm({ ...form, ssh_username: e.target.value })}
                  className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="örn: root"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">SSH Port</label>
                <input
                  type="number" value={form.ssh_port}
                  onChange={e => setForm({ ...form, ssh_port: e.target.value })}
                  className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="22"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4 mt-3">
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Şifre</label>
                <input
                  type="password" value={form.ssh_password}
                  onChange={e => setForm({ ...form, ssh_password: e.target.value })}
                  className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="SSH şifresi"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-slate-300 mb-2">Sudo Şifresi</label>
                <input
                  type="password" value={form.sudo_password}
                  onChange={e => setForm({ ...form, sudo_password: e.target.value })}
                  className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                  placeholder="Opsiyonel"
                />
              </div>
            </div>
            <div className="mt-3">
              <label className="block text-sm font-medium text-slate-300 mb-2">Private Key (opsiyonel)</label>
              <textarea
                value={form.private_key}
                onChange={e => setForm({ ...form, private_key: e.target.value })}
                className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-4 py-2 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                placeholder="-----BEGIN OPENSSH PRIVATE KEY-----"
                rows={3}
              />
            </div>
          </div>
          <div className="flex justify-end space-x-3 pt-2">
            <button type="button" onClick={onClose} className="px-4 py-2 bg-white/[0.07] text-white rounded-lg hover:bg-slate-600 transition-colors">
              İptal
            </button>
            <button
              type="submit" disabled={isPending}
              className="px-4 py-2 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-lg hover:from-green-500 hover:to-green-600 transition-all disabled:opacity-50"
            >
              {isPending ? 'Ekleniyor...' : 'Ekle'}
            </button>
          </div>
          {error && (
            <div className="bg-red-500/10 border border-red-500/30 rounded-lg p-3">
              <p className="text-red-400 text-sm">{error}</p>
            </div>
          )}
        </form>
      </div>
    </div>
  )
}

export default function PhysicalHostsPage() {
  const [showAddModal, setShowAddModal] = useState(false)
  const queryClient = useQueryClient()

  const { data: hosts = [], isLoading, refetch } = useQuery({
    queryKey: ['integrations-physical-hosts'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/integrations/physical-hosts`)
      if (!r.ok) throw new Error('fetch failed')
      return r.json()
    },
  })

  const createMutation = useMutation({
    mutationFn: async (form: AddHostForm) => {
      const connection_config = form.ssh_username
        ? {
            username: form.ssh_username,
            password: form.ssh_password || undefined,
            port: Number(form.ssh_port || 22),
            sudo_password: form.sudo_password || undefined,
            private_key: form.private_key || undefined,
          }
        : {}
      const r = await fetch(`${API_BASE_URL}/servers/`, {
        method: 'POST',
        headers: inventoryHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify({
          name: form.name,
          hostname: form.hostname || undefined,
          ip_address: form.ip_address,
          status: 'OFFLINE',
          server_type: 'PHYSICAL',
          os_type: form.os_type,
          connection_config,
        }),
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        throw new Error(err.detail || 'Host eklenemedi')
      }
      return r.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['integrations-physical-hosts'] })
      queryClient.invalidateQueries({ queryKey: ['integrations-overview'] })
      setShowAddModal(false)
    },
  })

  return (
    <div className="p-6 space-y-4">
      {showAddModal && (
        <AddPhysicalHostModal
          onClose={() => setShowAddModal(false)}
          onCreate={data => createMutation.mutate(data)}
          isPending={createMutation.isPending}
          error={createMutation.isError ? (createMutation.error instanceof Error ? createMutation.error.message : String(createMutation.error)) : null}
        />
      )}

      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <Link to="/integrations" className="inline-flex items-center gap-1 text-xs text-slate-500 hover:text-white mb-2">
            <ArrowLeft size={14} /> Envanter Merkezi
          </Link>
          <h1 className="text-xl font-bold text-white flex items-center gap-2">
            <Server size={22} className="text-green-400" /> Fiziksel Hostlar
          </h1>
          <p className="text-sm text-slate-500 mt-1">
            UCMDB veya manuel tanımlı fiziksel sunucular — VM ve Exadata node&apos;ları hariç
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => refetch()} className="text-xs px-3 py-2 rounded-lg border border-slate-700 text-slate-400 hover:text-white flex items-center gap-1">
            <RefreshCw size={14} /> Yenile
          </button>
          <button
            onClick={() => setShowAddModal(true)}
            className="text-xs px-3 py-2 rounded-lg bg-gradient-to-r from-green-600 to-green-700 text-white flex items-center gap-1.5 font-medium hover:from-green-500 hover:to-green-600 transition-all"
          >
            <Plus size={14} /> Yeni Fiziksel Host
          </button>
        </div>
      </div>

      <div className="bg-slate-800/40 border border-slate-700/50 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-slate-700/50 text-xs text-slate-500">
              <th className="text-left px-4 py-2">Ad</th>
              <th className="text-left px-4 py-2">Hostname</th>
              <th className="text-left px-4 py-2">IP</th>
              <th className="text-left px-4 py-2">OS</th>
              <th className="text-left px-4 py-2">Durum</th>
              <th className="text-left px-4 py-2">Kaynak</th>
            </tr>
          </thead>
          <tbody>
            {isLoading ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-500">Yükleniyor...</td></tr>
            ) : hosts.length === 0 ? (
              <tr><td colSpan={6} className="px-4 py-8 text-center text-slate-500">Fiziksel host bulunamadı — UCMDB import veya "Yeni Fiziksel Host" ile ekleyin</td></tr>
            ) : hosts.map((h: any) => (
              <tr key={h.id} className="border-b border-slate-700/30 hover:bg-slate-700/20">
                <td className="px-4 py-2.5 text-white">{h.name}</td>
                <td className="px-4 py-2.5 text-slate-400 font-mono text-xs">{h.hostname || '—'}</td>
                <td className="px-4 py-2.5 text-slate-400 font-mono text-xs">{h.ip_address || '—'}</td>
                <td className="px-4 py-2.5 text-slate-400">{h.os_type || '—'}</td>
                <td className="px-4 py-2.5">
                  <span className={`text-xs px-2 py-0.5 rounded-full ${h.status === 'ONLINE' ? 'bg-green-500/20 text-green-400' : 'bg-slate-600/30 text-slate-400'}`}>
                    {h.status || 'unknown'}
                  </span>
                </td>
                <td className="px-4 py-2.5 text-xs text-slate-500">
                  {(h.sources?.length ? h.sources.map((s: any) => s.source).join(', ') : 'manuel') || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <p className="text-xs text-slate-600">
        Linux modülünde yönetim için{' '}
        <Link to="/servers" className="text-blue-400 hover:underline">Linux Sunucular</Link>
        {' '}sayfasını kullanın.
      </p>
    </div>
  )
}
