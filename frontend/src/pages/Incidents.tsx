import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

interface Incident {
  id: number
  title: string
  description: string | null
  severity: string
  status: string
  source: string | null
  affected_servers: number[]
  affected_server_details: { id: number; name: string; ip: string }[]
  related_events: number[]
  root_cause: string | null
  resolution: string | null
  rca_result: any
  assigned_to: string | null
  created_at: string | null
  resolved_at: string | null
}

interface IncidentStats {
  total: number
  open: number
  investigating: number
  resolved: number
  critical: number
}

const Incidents: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState('')
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null)
  const [newIncident, setNewIncident] = useState({ title: '', description: '', severity: 'medium' })
  const queryClient = useQueryClient()

  const { data: incidentsData, isLoading } = useQuery<{ total: number; incidents: Incident[] }>({
    queryKey: ['incidents', statusFilter],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (statusFilter) params.set('status', statusFilter)
      const res = await fetch(`${API_BASE_URL}/incidents/?${params}`)
      if (!res.ok) return { total: 0, incidents: [] }
      return res.json()
    },
    refetchInterval: 15000
  })

  const { data: stats } = useQuery<IncidentStats>({
    queryKey: ['incidentStats'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/incidents/stats`)
      if (!res.ok) return { total: 0, open: 0, investigating: 0, resolved: 0, critical: 0 }
      return res.json()
    },
    refetchInterval: 15000
  })

  const createIncident = useMutation({
    mutationFn: async (data: typeof newIncident) => {
      const res = await fetch(`${API_BASE_URL}/incidents/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      if (!res.ok) throw new Error('Oluşturulamadı')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['incidents'] })
      queryClient.invalidateQueries({ queryKey: ['incidentStats'] })
      setShowCreateForm(false)
      setNewIncident({ title: '', description: '', severity: 'medium' })
    }
  })

  const updateIncident = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: any }) => {
      const res = await fetch(`${API_BASE_URL}/incidents/${id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      if (!res.ok) throw new Error('Güncellenemedi')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['incidents'] })
      queryClient.invalidateQueries({ queryKey: ['incidentStats'] })
    }
  })

  const runRCA = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${API_BASE_URL}/incidents/${id}/rca`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail || 'RCA çalıştırılamadı')
      }
      return res.json()
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['incidents'] })
      if (selectedIncident) {
        setSelectedIncident({ ...selectedIncident, rca_result: data.rca })
      }
    }
  })

  const incidents = incidentsData?.incidents || []

  const severityBadge = (s: string) => {
    switch (s) {
      case 'critical': return 'bg-red-500/20 text-red-400 border-red-500/30'
      case 'high': return 'bg-orange-500/20 text-orange-400 border-orange-500/30'
      case 'medium': return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
      case 'low': return 'bg-blue-500/20 text-blue-400 border-blue-500/30'
      default: return 'bg-slate-500/20 text-slate-400 border-slate-500/30'
    }
  }

  const statusBadge = (s: string) => {
    switch (s) {
      case 'open': return 'bg-red-500/20 text-red-400'
      case 'investigating': return 'bg-yellow-500/20 text-yellow-400'
      case 'resolved': return 'bg-green-500/20 text-green-400'
      case 'closed': return 'bg-slate-500/20 text-slate-400'
      default: return 'bg-slate-500/20 text-slate-400'
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">AIOps Incidents</h1>
          <p className="text-slate-400 text-sm mt-1">Incident'ları yönetin, AI ile kök neden analizi yapın</p>
        </div>
        <button onClick={() => setShowCreateForm(!showCreateForm)}
          className="px-4 py-2 bg-gradient-to-r from-red-600 to-red-700 text-white rounded-lg hover:from-red-500 hover:to-red-600 transition-all text-sm">
          {showCreateForm ? '✕ İptal' : '🚨 Yeni Incident'}
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-5 gap-4">
        {[
          { label: 'Toplam', value: stats?.total || 0, color: 'from-slate-500 to-slate-600', icon: '📊' },
          { label: 'Açık', value: stats?.open || 0, color: 'from-red-500 to-red-600', icon: '🔴' },
          { label: 'İnceleniyor', value: stats?.investigating || 0, color: 'from-yellow-500 to-yellow-600', icon: '🔍' },
          { label: 'Çözülmüş', value: stats?.resolved || 0, color: 'from-green-500 to-green-600', icon: '✅' },
          { label: 'Kritik Açık', value: stats?.critical || 0, color: 'from-red-600 to-red-700', icon: '🚨' },
        ].map((s, i) => (
          <div key={i} className="bg-slate-800 rounded-xl border border-slate-700 p-4">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-slate-400 text-xs">{s.label}</p>
                <p className="text-2xl font-bold text-white mt-1">{s.value}</p>
              </div>
              <div className={`w-10 h-10 rounded-lg bg-gradient-to-br ${s.color} flex items-center justify-center`}>
                <span>{s.icon}</span>
              </div>
            </div>
          </div>
        ))}
      </div>

      {/* Create Form */}
      {showCreateForm && (
        <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
          <h3 className="text-lg font-medium text-white mb-4">Yeni Incident Oluştur</h3>
          <form onSubmit={e => { e.preventDefault(); createIncident.mutate(newIncident) }} className="space-y-4">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <label className="block text-sm text-slate-300 mb-1">Başlık *</label>
                <input type="text" required value={newIncident.title} onChange={e => setNewIncident({ ...newIncident, title: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-sm text-slate-300 mb-1">Önem</label>
                <select value={newIncident.severity} onChange={e => setNewIncident({ ...newIncident, severity: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none">
                  <option value="low">Low</option>
                  <option value="medium">Medium</option>
                  <option value="high">High</option>
                  <option value="critical">Critical</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-sm text-slate-300 mb-1">Açıklama</label>
              <textarea value={newIncident.description} onChange={e => setNewIncident({ ...newIncident, description: e.target.value })}
                className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none" rows={3} />
            </div>
            <button type="submit" disabled={createIncident.isPending}
              className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-500 text-sm disabled:opacity-50">
              {createIncident.isPending ? 'Oluşturuluyor...' : '🚨 Oluştur'}
            </button>
          </form>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3">
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm">
          <option value="">Tüm Durumlar</option>
          <option value="open">Açık</option>
          <option value="investigating">İnceleniyor</option>
          <option value="resolved">Çözülmüş</option>
          <option value="closed">Kapatılmış</option>
        </select>
      </div>

      {/* Incidents List */}
      {isLoading ? (
        <div className="text-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto"></div></div>
      ) : incidents.length === 0 ? (
        <div className="text-center py-12 bg-slate-800 rounded-xl border border-dashed border-slate-700">
          <span className="text-4xl block mb-3">🚨</span>
          <p className="text-slate-400">Henüz incident yok</p>
        </div>
      ) : (
        <div className="space-y-3">
          {incidents.map(inc => (
            <div key={inc.id} className="bg-slate-800 rounded-xl border border-slate-700 p-5 hover:border-slate-600 transition-all">
              <div className="flex items-start justify-between">
                <div className="flex-1">
                  <div className="flex items-center gap-3 mb-2">
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium border ${severityBadge(inc.severity)}`}>
                      {inc.severity.toUpperCase()}
                    </span>
                    <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${statusBadge(inc.status)}`}>
                      {inc.status}
                    </span>
                    <span className="text-xs text-slate-500">#{inc.id}</span>
                  </div>
                  <h3 className="text-white font-medium">{inc.title}</h3>
                  {inc.description && <p className="text-slate-400 text-sm mt-1">{inc.description}</p>}

                  {/* Affected Servers */}
                  {inc.affected_server_details && inc.affected_server_details.length > 0 && (
                    <div className="flex gap-2 mt-2">
                      {inc.affected_server_details.map(s => (
                        <span key={s.id} className="text-[10px] px-2 py-0.5 rounded bg-purple-500/20 text-purple-400 border border-purple-500/30">
                          {s.name} ({s.ip})
                        </span>
                      ))}
                    </div>
                  )}

                  {/* RCA Result */}
                  {inc.rca_result?.analysis && (
                    <div className="mt-3 p-3 bg-slate-900/50 rounded-lg border border-slate-700">
                      <p className="text-xs font-medium text-purple-400 mb-1">🤖 AI Kök Neden Analizi:</p>
                      <p className="text-xs text-slate-300 whitespace-pre-wrap">{inc.rca_result.analysis}</p>
                    </div>
                  )}

                  <p className="text-xs text-slate-500 mt-2">
                    {inc.created_at ? new Date(inc.created_at).toLocaleString('tr-TR') : ''}
                    {inc.assigned_to && ` • Atanan: ${inc.assigned_to}`}
                  </p>
                </div>

                {/* Actions */}
                <div className="flex flex-col gap-1.5 ml-4">
                  {inc.status === 'open' && (
                    <button onClick={() => updateIncident.mutate({ id: inc.id, data: { status: 'investigating' } })}
                      className="px-3 py-1.5 text-[10px] bg-yellow-500/10 text-yellow-400 border border-yellow-500/30 rounded-lg hover:bg-yellow-500/20">
                      🔍 İncele
                    </button>
                  )}
                  {(inc.status === 'open' || inc.status === 'investigating') && (
                    <>
                      <button onClick={() => runRCA.mutate(inc.id)} disabled={runRCA.isPending}
                        className="px-3 py-1.5 text-[10px] bg-purple-500/10 text-purple-400 border border-purple-500/30 rounded-lg hover:bg-purple-500/20 disabled:opacity-50">
                        {runRCA.isPending ? '⏳' : '🤖'} RCA
                      </button>
                      <button onClick={() => updateIncident.mutate({ id: inc.id, data: { status: 'resolved' } })}
                        className="px-3 py-1.5 text-[10px] bg-green-500/10 text-green-400 border border-green-500/30 rounded-lg hover:bg-green-500/20">
                        ✅ Çöz
                      </button>
                    </>
                  )}
                  {inc.status === 'resolved' && (
                    <button onClick={() => updateIncident.mutate({ id: inc.id, data: { status: 'closed' } })}
                      className="px-3 py-1.5 text-[10px] bg-slate-500/10 text-slate-400 border border-slate-500/30 rounded-lg hover:bg-slate-500/20">
                      🔒 Kapat
                    </button>
                  )}
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

export default Incidents
