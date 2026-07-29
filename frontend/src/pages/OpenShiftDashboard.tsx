/**
 * OpenShift Container Platform Dashboard — cluster bağlantısı, node/proje/workload envanteri.
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import {
  Boxes, Server, Layers, Plus, RefreshCw, X, Check, Trash2, Cpu, MemoryStick,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { inventoryHeaders } from '../lib/inventoryApi'

interface Cluster {
  id: number; name: string; api_url: string; status: string | null; version: string | null
  last_sync: string | null; sync_job?: { status?: string; phase?: string; percent?: number; message?: string } | null
}

interface OcpNode {
  id: number; cluster_id: number; name: string; role: string; status: string
  cpu_cores?: number; memory_gb?: number; kubelet_version?: string
}

interface OcpProject {
  id: number; cluster_id: number; name: string; status: string
  pod_count: number; deployment_count: number; route_count: number
}

interface OcpWorkload {
  id: number; cluster_id: number; project: string; kind: string; name: string
  status: string; node_name?: string; restart_count: number; ready?: string; host?: string
}

function relTime(iso: string | null): string {
  if (!iso) return '—'
  const t = new Date(iso).getTime()
  if (Number.isNaN(t)) return '—'
  const m = Math.floor((Date.now() - t) / 60000)
  if (m < 1) return 'şimdi'
  if (m < 60) return `${m}dk önce`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h}s önce`
  return `${Math.floor(h / 24)}g önce`
}

function statusColor(status?: string) {
  const s = (status || '').toLowerCase()
  if (['ready', 'running', 'active', 'admitted', 'available'].includes(s)) return 'text-green-400'
  if (['pending', 'progressing'].includes(s)) return 'text-amber-400'
  if (['notready', 'failed', 'error', 'crashloopbackoff'].includes(s)) return 'text-red-400'
  return 'text-slate-400'
}

function AddClusterModal({ onClose, onCreate }: { onClose: () => void; onCreate: (data: any) => void }) {
  const [form, setForm] = useState({ name: '', api_url: '', token: '', username: '', password: '', verify_ssl: false })
  const [authMethod, setAuthMethod] = useState<'token' | 'credentials'>('token')
  const [testing, setTesting] = useState(false)
  const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

  const buildPayload = () => ({
    name: form.name,
    api_url: form.api_url,
    verify_ssl: form.verify_ssl,
    ...(authMethod === 'token'
      ? { token: form.token }
      : { username: form.username, password: form.password }),
  })

  const canTest = Boolean(form.api_url) && (authMethod === 'token' ? Boolean(form.token) : Boolean(form.username) && Boolean(form.password))

  const testConnection = async () => {
    setTesting(true)
    setTestResult(null)
    try {
      const r = await fetch(`${API_BASE_URL}/openshift/test-connection`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(buildPayload()),
      })
      const data = await r.json()
      setTestResult({ success: data.success, message: data.message })
    } catch {
      setTestResult({ success: false, message: 'Bağlantı hatası' })
    } finally {
      setTesting(false)
    }
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (!testResult?.success) return
    onCreate(buildPayload())
    onClose()
  }

  return (
    <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
      <div className="bg-cyber-card rounded-2xl border border-white/[0.06] w-full max-w-md shadow-2xl">
        <div className="px-6 py-4 border-b border-white/[0.06] flex items-center justify-between">
          <h2 className="text-lg font-semibold text-white">OpenShift Cluster Ekle</h2>
          <button onClick={onClose} className="text-slate-400 hover:text-white"><X className="w-5 h-5" /></button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Adı *</label>
            <input type="text" required value={form.name} onChange={e => { setForm({ ...form, name: e.target.value }); setTestResult(null) }}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-500/50" placeholder="Production OCP" />
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">Kimlik Doğrulama Yöntemi</label>
            <div className="grid grid-cols-2 gap-2 p-1 bg-cyber-deep border border-white/[0.06] rounded-lg">
              <button type="button" onClick={() => { setAuthMethod('token'); setTestResult(null) }}
                className={`py-1.5 rounded-md text-sm font-medium transition-colors ${authMethod === 'token' ? 'bg-rose-600 text-white' : 'text-slate-400 hover:text-white'}`}>
                Bearer Token
              </button>
              <button type="button" onClick={() => { setAuthMethod('credentials'); setTestResult(null) }}
                className={`py-1.5 rounded-md text-sm font-medium transition-colors ${authMethod === 'credentials' ? 'bg-rose-600 text-white' : 'text-slate-400 hover:text-white'}`}>
                Kullanıcı Adı / Şifre
              </button>
            </div>
          </div>
          <div>
            <label className="block text-xs text-slate-400 mb-1.5">API Server URL *</label>
            <input type="text" required value={form.api_url} onChange={e => { setForm({ ...form, api_url: e.target.value }); setTestResult(null) }}
              className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-500/50" placeholder="https://api.cluster.example.com:6443" />
          </div>
          {authMethod === 'token' ? (
            <div>
              <label className="block text-xs text-slate-400 mb-1.5">Bearer Token *</label>
              <textarea required rows={3} value={form.token} onChange={e => { setForm({ ...form, token: e.target.value }); setTestResult(null) }}
                className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-500/50 font-mono" placeholder="oc whoami -t ile alınan token" />
            </div>
          ) : (
            <>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">Kullanıcı Adı *</label>
                <input type="text" required value={form.username} onChange={e => { setForm({ ...form, username: e.target.value }); setTestResult(null) }}
                  className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-500/50" placeholder="kubeadmin" />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1.5">Şifre *</label>
                <input type="password" required value={form.password} onChange={e => { setForm({ ...form, password: e.target.value }); setTestResult(null) }}
                  className="w-full bg-cyber-deep border border-white/[0.06] rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-rose-500/50" />
              </div>
              <p className="text-[11px] text-slate-500 leading-relaxed">
                Kullanıcı adı/şifre, cluster'ın OAuth sunucusu üzerinden ("oc login" ile aynı akış) bir erişim token'ına çevrilir.
              </p>
            </>
          )}

          <button type="button" onClick={testConnection} disabled={testing || !canTest}
            className="w-full py-2.5 bg-rose-600/20 text-rose-400 border border-rose-500/30 rounded-lg hover:bg-rose-600/30 disabled:opacity-50 text-sm font-medium flex items-center justify-center gap-2">
            {testing ? <><RefreshCw className="w-4 h-4 animate-spin" /> Test Ediliyor...</> : 'Bağlantıyı Test Et'}
          </button>

          {testResult && (
            <div className={`p-3 rounded-lg border ${testResult.success ? 'bg-green-500/10 border-green-500/30' : 'bg-red-500/10 border-red-500/30'}`}>
              <div className="flex items-center gap-2">
                {testResult.success ? <Check className="w-4 h-4 text-green-400" /> : <X className="w-4 h-4 text-red-400" />}
                <span className={`text-sm ${testResult.success ? 'text-green-400' : 'text-red-400'}`}>{testResult.message}</span>
              </div>
            </div>
          )}

          <div className="flex gap-3 pt-2">
            <button type="button" onClick={onClose} className="flex-1 px-4 py-2.5 bg-white/[0.07] text-white rounded-lg hover:bg-slate-600 text-sm">İptal</button>
            <button type="submit" disabled={!testResult?.success}
              className="flex-1 px-4 py-2.5 bg-gradient-to-r from-rose-600 to-red-700 text-white rounded-lg hover:from-rose-500 hover:to-red-600 disabled:opacity-50 text-sm font-medium">
              Ekle
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

export default function OpenShiftDashboard({ allowInventoryEdit = false }: { allowInventoryEdit?: boolean }) {
  const [tab, setTab] = useState<'clusters' | 'nodes' | 'projects' | 'workloads'>('clusters')
  const [showAddModal, setShowAddModal] = useState(false)
  const qc = useQueryClient()

  const { data: clusters = [], isLoading: clustersLoading } = useQuery<Cluster[]>({
    queryKey: ['openshift-clusters'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters`)
      if (!r.ok) return []
      return (await r.json()).clusters
    },
    refetchInterval: (q) => {
      const list = (q.state.data as Cluster[] | undefined) || []
      return list.some(c => c.sync_job?.status === 'running') ? 4000 : 60_000
    },
  })

  const { data: nodes = [] } = useQuery<OcpNode[]>({
    queryKey: ['openshift-nodes'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/nodes`)
      if (!r.ok) return []
      return (await r.json()).nodes
    },
    refetchInterval: 60_000,
  })

  const { data: projects = [] } = useQuery<OcpProject[]>({
    queryKey: ['openshift-projects'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/projects`)
      if (!r.ok) return []
      return (await r.json()).projects
    },
    refetchInterval: 60_000,
  })

  const { data: workloads = [] } = useQuery<OcpWorkload[]>({
    queryKey: ['openshift-workloads'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/openshift/workloads`)
      if (!r.ok) return []
      return (await r.json()).workloads
    },
    refetchInterval: 60_000,
  })

  const createMutation = useMutation({
    mutationFn: async (data: any) => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters`, {
        method: 'POST',
        headers: inventoryHeaders({ 'Content-Type': 'application/json' }),
        body: JSON.stringify(data),
      })
      if (!r.ok) throw new Error((await r.json()).detail || 'Ekleme hatası')
      return r.json()
    },
    onSuccess: async (created) => {
      qc.invalidateQueries({ queryKey: ['openshift-clusters'] })
      await fetch(`${API_BASE_URL}/openshift/clusters/${created.id}/sync?background=true`, { method: 'POST', headers: inventoryHeaders() })
      qc.invalidateQueries({ queryKey: ['openshift-clusters'] })
    },
    onError: (e) => alert(e instanceof Error ? e.message : 'Ekleme hatası'),
  })

  const deleteMutation = useMutation({
    mutationFn: async (id: number) => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${id}`, { method: 'DELETE', headers: inventoryHeaders() })
      if (!r.ok) throw new Error('Silme hatası')
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['openshift-clusters'] })
      qc.invalidateQueries({ queryKey: ['openshift-nodes'] })
      qc.invalidateQueries({ queryKey: ['openshift-projects'] })
      qc.invalidateQueries({ queryKey: ['openshift-workloads'] })
    },
  })

  const syncMutation = useMutation({
    mutationFn: async (id: number) => {
      const r = await fetch(`${API_BASE_URL}/openshift/clusters/${id}/sync?background=true`, { method: 'POST', headers: inventoryHeaders() })
      if (!r.ok) throw new Error('Sync hatası')
      return r.json()
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ['openshift-clusters'] })
      setTimeout(() => {
        qc.invalidateQueries({ queryKey: ['openshift-nodes'] })
        qc.invalidateQueries({ queryKey: ['openshift-projects'] })
        qc.invalidateQueries({ queryKey: ['openshift-workloads'] })
      }, 8000)
    },
    onError: (e) => alert(e instanceof Error ? e.message : 'Sync hatası'),
  })

  const nonSystemProjects = projects.filter(p => !(p as any).is_system)

  if (clustersLoading) {
    return (
      <div className="min-h-[50vh] flex items-center justify-center">
        <div className="w-12 h-12 border-4 border-rose-500/30 border-t-rose-500 rounded-full animate-spin" />
      </div>
    )
  }

  return (
    <div className="space-y-5">
      {showAddModal && <AddClusterModal onClose={() => setShowAddModal(false)} onCreate={data => createMutation.mutate(data)} />}

      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold text-white flex items-center gap-2">
            <Boxes className="text-rose-400" size={22} /> OpenShift Container Platform
          </h1>
          <p className="text-sm text-slate-500 mt-1">Cluster, node, proje ve workload envanteri</p>
        </div>
        {allowInventoryEdit && (
          <button onClick={() => setShowAddModal(true)}
            className="flex items-center gap-2 px-4 py-2 bg-gradient-to-r from-rose-600 to-red-700 text-white rounded-lg text-sm font-medium hover:from-rose-500 hover:to-red-600">
            <Plus size={16} /> Cluster Ekle
          </button>
        )}
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
          <div className="text-xs text-slate-500 mb-1">Cluster</div>
          <div className="text-2xl font-bold text-white">{clusters.length}</div>
        </div>
        <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
          <div className="text-xs text-slate-500 mb-1">Node</div>
          <div className="text-2xl font-bold text-white">{nodes.length}</div>
        </div>
        <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
          <div className="text-xs text-slate-500 mb-1">Proje</div>
          <div className="text-2xl font-bold text-white">{nonSystemProjects.length}</div>
        </div>
        <div className="rounded-xl border border-white/[0.06] bg-cyber-card p-4">
          <div className="text-xs text-slate-500 mb-1">Pod</div>
          <div className="text-2xl font-bold text-white">{workloads.filter(w => w.kind === 'pod').length}</div>
        </div>
      </div>

      <div className="flex items-center gap-2 border-b border-white/[0.06]">
        {([
          ['clusters', 'Cluster\'lar'],
          ['nodes', 'Node\'lar'],
          ['projects', 'Projeler'],
          ['workloads', 'Workload\'lar'],
        ] as const).map(([id, label]) => (
          <button key={id} onClick={() => setTab(id)}
            className={`px-4 py-2 text-sm font-medium border-b-2 transition-colors ${
              tab === id ? 'border-rose-500 text-white' : 'border-transparent text-slate-500 hover:text-slate-300'
            }`}>
            {label}
          </button>
        ))}
      </div>

      {tab === 'clusters' && (
        <div className="space-y-3">
          {clusters.length === 0 && (
            <div className="text-center py-12 text-slate-500">
              <Boxes size={32} className="mx-auto mb-3 opacity-40" />
              <p className="text-sm">Henüz bir OpenShift cluster'ı eklenmemiş.</p>
            </div>
          )}
          {clusters.map(c => {
            const syncing = c.sync_job?.status === 'running'
            return (
              <div key={c.id} className="rounded-xl border border-white/[0.06] bg-cyber-card p-4 flex items-center justify-between gap-4 flex-wrap">
                <div className="flex items-center gap-3 min-w-0">
                  <div className="w-10 h-10 rounded-lg bg-gradient-to-br from-rose-600 to-red-700 flex items-center justify-center flex-shrink-0">
                    <Boxes size={18} className="text-white" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-white font-medium truncate">{c.name}</div>
                    <div className="text-xs text-slate-500 truncate">{c.api_url} · {c.version || 'sürüm bilinmiyor'}</div>
                    <div className="text-xs text-slate-500">
                      {syncing ? (
                        <span className="text-cyan-400">{c.sync_job?.message || 'Senkronize ediliyor...'}</span>
                      ) : (
                        <>Son sync: {relTime(c.last_sync)}</>
                      )}
                    </div>
                  </div>
                </div>
                {allowInventoryEdit && (
                  <div className="flex items-center gap-2 flex-shrink-0">
                    <button onClick={() => syncMutation.mutate(c.id)} disabled={syncing}
                      className="p-2 rounded-lg bg-white/[0.05] text-slate-300 hover:bg-white/[0.1] disabled:opacity-50">
                      <RefreshCw size={15} className={syncing ? 'animate-spin' : ''} />
                    </button>
                    <button onClick={() => { if (confirm(`'${c.name}' silinsin mi?`)) deleteMutation.mutate(c.id) }}
                      className="p-2 rounded-lg bg-red-500/10 text-red-400 hover:bg-red-500/20">
                      <Trash2 size={15} />
                    </button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {tab === 'nodes' && (
        <div className="rounded-xl border border-white/[0.06] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-white/[0.03] text-slate-500 text-xs">
              <tr>
                <th className="text-left px-4 py-2.5">Node</th>
                <th className="text-left px-4 py-2.5">Rol</th>
                <th className="text-left px-4 py-2.5">Durum</th>
                <th className="text-left px-4 py-2.5">CPU</th>
                <th className="text-left px-4 py-2.5">RAM</th>
                <th className="text-left px-4 py-2.5">Kubelet</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {nodes.map(n => (
                <tr key={n.id} className="hover:bg-white/[0.02]">
                  <td className="px-4 py-2.5 text-white flex items-center gap-2"><Server size={13} className="text-slate-500" /> {n.name}</td>
                  <td className="px-4 py-2.5 text-slate-400 capitalize">{n.role}</td>
                  <td className={`px-4 py-2.5 font-medium ${statusColor(n.status)}`}>{n.status}</td>
                  <td className="px-4 py-2.5 text-slate-400 flex items-center gap-1"><Cpu size={12} /> {n.cpu_cores ?? '—'}</td>
                  <td className="px-4 py-2.5 text-slate-400 flex items-center gap-1"><MemoryStick size={12} /> {n.memory_gb ?? '—'} GB</td>
                  <td className="px-4 py-2.5 text-slate-500 text-xs">{n.kubelet_version || '—'}</td>
                </tr>
              ))}
              {nodes.length === 0 && (
                <tr><td colSpan={6} className="text-center py-8 text-slate-500">Node bulunamadı — cluster senkronize edildi mi?</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'projects' && (
        <div className="rounded-xl border border-white/[0.06] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-white/[0.03] text-slate-500 text-xs">
              <tr>
                <th className="text-left px-4 py-2.5">Proje</th>
                <th className="text-left px-4 py-2.5">Durum</th>
                <th className="text-left px-4 py-2.5">Pod</th>
                <th className="text-left px-4 py-2.5">Deployment</th>
                <th className="text-left px-4 py-2.5">Route</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {nonSystemProjects.map(p => (
                <tr key={p.id} className="hover:bg-white/[0.02]">
                  <td className="px-4 py-2.5 text-white flex items-center gap-2"><Layers size={13} className="text-slate-500" /> {p.name}</td>
                  <td className={`px-4 py-2.5 font-medium ${statusColor(p.status)}`}>{p.status}</td>
                  <td className="px-4 py-2.5 text-slate-400">{p.pod_count}</td>
                  <td className="px-4 py-2.5 text-slate-400">{p.deployment_count}</td>
                  <td className="px-4 py-2.5 text-slate-400">{p.route_count}</td>
                </tr>
              ))}
              {nonSystemProjects.length === 0 && (
                <tr><td colSpan={5} className="text-center py-8 text-slate-500">Proje bulunamadı — cluster senkronize edildi mi?</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {tab === 'workloads' && (
        <div className="rounded-xl border border-white/[0.06] overflow-hidden">
          <table className="w-full text-sm">
            <thead className="bg-white/[0.03] text-slate-500 text-xs">
              <tr>
                <th className="text-left px-4 py-2.5">Tür</th>
                <th className="text-left px-4 py-2.5">Ad</th>
                <th className="text-left px-4 py-2.5">Proje</th>
                <th className="text-left px-4 py-2.5">Durum</th>
                <th className="text-left px-4 py-2.5">Ready</th>
                <th className="text-left px-4 py-2.5">Restart</th>
                <th className="text-left px-4 py-2.5">Node / Host</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-white/[0.04]">
              {workloads.slice(0, 500).map(w => (
                <tr key={w.id} className="hover:bg-white/[0.02]">
                  <td className="px-4 py-2.5 text-slate-400 uppercase text-xs">{w.kind}</td>
                  <td className="px-4 py-2.5 text-white">{w.name}</td>
                  <td className="px-4 py-2.5 text-slate-400">{w.project}</td>
                  <td className={`px-4 py-2.5 font-medium ${statusColor(w.status)}`}>{w.status}</td>
                  <td className="px-4 py-2.5 text-slate-400">{w.ready || '—'}</td>
                  <td className={`px-4 py-2.5 ${w.restart_count >= 5 ? 'text-amber-400' : 'text-slate-400'}`}>{w.restart_count}</td>
                  <td className="px-4 py-2.5 text-slate-500 text-xs">{w.node_name || w.host || '—'}</td>
                </tr>
              ))}
              {workloads.length === 0 && (
                <tr><td colSpan={7} className="text-center py-8 text-slate-500">Workload bulunamadı — cluster senkronize edildi mi?</td></tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
