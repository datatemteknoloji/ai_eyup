import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

interface Server {
  id: number
  name: string
  ip: string
  status?: string
}

interface RelatedEvent {
  id: number
  title: string
  severity: string
  event_type: string
  source: string | null
  resolved: boolean
  is_acknowledged: boolean
  created_at: string | null
}

interface Incident {
  id: number
  title: string
  description: string | null
  severity: string
  status: string
  source: string | null
  affected_servers: number[]
  affected_server_details: Server[]
  related_events: number[]
  related_event_details?: RelatedEvent[]
  root_cause: string | null
  resolution: string | null
  rca_result: any
  assigned_to: string | null
  created_at: string | null
  updated_at: string | null
  resolved_at: string | null
}

interface IncidentStats {
  total: number
  open: number
  investigating: number
  resolved: number
  critical: number
}

const SEV_BADGE: Record<string, string> = {
  critical: 'bg-red-500/20 text-red-400 border-red-500/30',
  high:     'bg-orange-500/20 text-orange-400 border-orange-500/30',
  medium:   'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  low:      'bg-blue-500/20 text-blue-400 border-blue-500/30',
}
const SEV_ICONS: Record<string, string> = {
  critical: '🔴', high: '🟠', medium: '🟡', low: '🔵'
}
const STATUS_BADGE: Record<string, string> = {
  open:          'bg-red-500/20 text-red-400',
  investigating: 'bg-yellow-500/20 text-yellow-400',
  resolved:      'bg-green-500/20 text-green-400',
  closed:        'bg-slate-500/20 text-slate-400',
}
const STATUS_LABELS: Record<string, string> = {
  open: '🔴 Açık', investigating: '🔍 İnceleniyor', resolved: '✅ Çözüldü', closed: '🔒 Kapalı'
}

const EVT_SEV_COLOR: Record<string, string> = {
  critical: 'text-red-400', emergency: 'text-pink-400', warning: 'text-yellow-400',
  error: 'text-orange-400', info: 'text-blue-400'
}

const Incidents: React.FC = () => {
  const [statusFilter, setStatusFilter]   = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [search, setSearch]               = useState('')
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [newIncident, setNewIncident]     = useState({ title: '', description: '', severity: 'medium', assigned_to: '' })
  const [resolutionText, setResolutionText] = useState('')
  const queryClient = useQueryClient()

  const { data: incidentsData, isLoading } = useQuery<{ total: number; incidents: Incident[] }>({
    queryKey: ['incidents', statusFilter, severityFilter, search],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (statusFilter) params.set('status', statusFilter)
      if (severityFilter) params.set('severity', severityFilter)
      if (search) params.set('search', search)
      const res = await fetch(`${API_BASE_URL}/incidents/?${params}`)
      if (!res.ok) return { total: 0, incidents: [] }
      return res.json()
    },
    refetchInterval: 20000
  })

  const { data: stats } = useQuery<IncidentStats>({
    queryKey: ['incidentStats'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/incidents/stats`)
      if (!res.ok) return { total: 0, open: 0, investigating: 0, resolved: 0, critical: 0 }
      return res.json()
    },
    refetchInterval: 20000
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['incidents'] })
    queryClient.invalidateQueries({ queryKey: ['incidentStats'] })
  }

  const openDetail = async (inc: Incident) => {
    setSelectedIncident(inc)
    setDetailLoading(true)
    setResolutionText(inc.resolution || '')
    try {
      const res = await fetch(`${API_BASE_URL}/incidents/${inc.id}`)
      if (res.ok) setSelectedIncident(await res.json())
    } finally {
      setDetailLoading(false)
    }
  }

  const createIncident = useMutation({
    mutationFn: async (data: typeof newIncident) => {
      const res = await fetch(`${API_BASE_URL}/incidents/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...data, assigned_to: data.assigned_to || null })
      })
      if (!res.ok) throw new Error('Oluşturulamadı')
      return res.json()
    },
    onSuccess: () => {
      invalidate()
      setShowCreateForm(false)
      setNewIncident({ title: '', description: '', severity: 'medium', assigned_to: '' })
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
    onSuccess: () => { invalidate(); if (selectedIncident) openDetail(selectedIncident) }
  })

  const deleteIncident = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${API_BASE_URL}/incidents/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Silinemedi')
    },
    onSuccess: () => { invalidate(); setSelectedIncident(null) }
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
      invalidate()
      if (selectedIncident) setSelectedIncident({ ...selectedIncident, rca_result: data.rca })
    }
  })

  const incidents = incidentsData?.incidents || []

  return (
    <div className="flex gap-5 h-full">
      {/* Left: List */}
      <div className={`flex-1 min-w-0 flex flex-col gap-5 overflow-hidden ${selectedIncident ? 'max-w-2xl' : ''}`}>
        {/* Header */}
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-2xl font-bold text-white">AIOps Incidents</h1>
            <p className="text-slate-400 text-sm mt-1">Incident yönetimi ve AI kök neden analizi</p>
          </div>
          <button onClick={() => setShowCreateForm(!showCreateForm)}
            className="px-4 py-2 bg-gradient-to-r from-red-600 to-red-700 text-white rounded-lg hover:from-red-500 hover:to-red-600 transition-all text-sm font-medium">
            {showCreateForm ? '✕ İptal' : '🚨 Yeni Incident'}
          </button>
        </div>

        {/* Stats */}
        <div className="grid grid-cols-5 gap-3">
          {[
            { label: 'Toplam',      value: stats?.total || 0,        color: 'from-slate-500 to-slate-600',  icon: '📊' },
            { label: 'Açık',        value: stats?.open || 0,         color: 'from-red-500 to-red-600',      icon: '🔴' },
            { label: 'İnceleniyor', value: stats?.investigating || 0, color: 'from-yellow-500 to-yellow-600', icon: '🔍' },
            { label: 'Çözülmüş',   value: stats?.resolved || 0,     color: 'from-green-500 to-green-600',  icon: '✅' },
            { label: 'Kritik Açık', value: stats?.critical || 0,    color: 'from-red-600 to-red-700',      icon: '🚨' },
          ].map((s, i) => (
            <div key={i} className="bg-slate-800 rounded-xl border border-slate-700 p-3">
              <div className="flex items-center justify-between">
                <div>
                  <p className="text-slate-400 text-[10px]">{s.label}</p>
                  <p className="text-xl font-bold text-white mt-0.5">{s.value}</p>
                </div>
                <div className={`w-8 h-8 rounded-lg bg-gradient-to-br ${s.color} flex items-center justify-center text-sm`}>{s.icon}</div>
              </div>
            </div>
          ))}
        </div>

        {/* Create Form */}
        {showCreateForm && (
          <div className="bg-slate-800 rounded-xl border border-slate-700 p-6">
            <h3 className="text-lg font-medium text-white mb-4">Yeni Incident Oluştur</h3>
            <form onSubmit={e => { e.preventDefault(); createIncident.mutate(newIncident) }} className="space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <div className="col-span-2">
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
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-sm text-slate-300 mb-1">Açıklama</label>
                  <textarea value={newIncident.description} onChange={e => setNewIncident({ ...newIncident, description: e.target.value })}
                    className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none" rows={2} />
                </div>
                <div>
                  <label className="block text-sm text-slate-300 mb-1">Atanan Kişi</label>
                  <input type="text" value={newIncident.assigned_to} placeholder="ops-team / admin..."
                    onChange={e => setNewIncident({ ...newIncident, assigned_to: e.target.value })}
                    className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none" />
                </div>
              </div>
              <button type="submit" disabled={createIncident.isPending}
                className="px-4 py-2 bg-red-600 text-white rounded-lg hover:bg-red-500 text-sm disabled:opacity-50">
                {createIncident.isPending ? 'Oluşturuluyor...' : '🚨 Oluştur'}
              </button>
            </form>
          </div>
        )}

        {/* Filters */}
        <div className="flex flex-wrap gap-2">
          <input type="text" value={search} onChange={e => setSearch(e.target.value)}
            placeholder="🔍 Başlıkta ara..."
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none w-48" />
          <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none">
            <option value="">Tüm Durumlar</option>
            <option value="open">Açık</option>
            <option value="investigating">İnceleniyor</option>
            <option value="resolved">Çözülmüş</option>
            <option value="closed">Kapatılmış</option>
          </select>
          <select value={severityFilter} onChange={e => setSeverityFilter(e.target.value)}
            className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none">
            <option value="">Tüm Önem</option>
            <option value="critical">Critical</option>
            <option value="high">High</option>
            <option value="medium">Medium</option>
            <option value="low">Low</option>
          </select>
          <span className="ml-auto text-xs text-slate-500 self-center">{incidentsData?.total || 0} sonuç</span>
        </div>

        {/* List */}
        {isLoading ? (
          <div className="text-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto"></div></div>
        ) : incidents.length === 0 ? (
          <div className="text-center py-12 bg-slate-800 rounded-xl border border-dashed border-slate-700">
            <span className="text-4xl block mb-3">🚨</span>
            <p className="text-slate-400">Henüz incident yok</p>
          </div>
        ) : (
          <div className="mt-3 space-y-3">
            {incidents.map(inc => (
              <div key={inc.id}
                onClick={() => openDetail(inc)}
                className={`bg-slate-800 rounded-xl border transition-all cursor-pointer hover:border-blue-500/50 hover:bg-slate-800/80 p-4 ${selectedIncident?.id === inc.id ? 'border-blue-500/60 bg-blue-500/5' : 'border-slate-700'}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${SEV_BADGE[inc.severity] || SEV_BADGE.medium}`}>
                        {SEV_ICONS[inc.severity] || '⚪'} {inc.severity.toUpperCase()}
                      </span>
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-medium ${STATUS_BADGE[inc.status] || STATUS_BADGE.open}`}>
                        {STATUS_LABELS[inc.status] || inc.status}
                      </span>
                      <span className="text-[10px] text-slate-600">#{inc.id}</span>
                      {inc.assigned_to && (
                        <span className="text-[10px] text-slate-500">👤 {inc.assigned_to}</span>
                      )}
                    </div>
                    <h3 className="text-white font-medium text-sm truncate">{inc.title}</h3>
                    {inc.description && <p className="text-slate-400 text-xs mt-0.5 truncate">{inc.description}</p>}
                    <div className="flex items-center gap-3 mt-1.5 text-[10px] text-slate-500">
                      {inc.affected_server_details?.length > 0 && (
                        <span>🖥️ {inc.affected_server_details.map(s => s.name).join(', ')}</span>
                      )}
                      {inc.related_events?.length > 0 && (
                        <span>📋 {inc.related_events.length} event</span>
                      )}
                      {inc.rca_result?.analysis && (
                        <span className="text-purple-400">🤖 RCA var</span>
                      )}
                      <span>{inc.created_at ? new Date(inc.created_at).toLocaleString('tr-TR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' }) : ''}</span>
                    </div>
                  </div>
                  <div className="flex flex-col gap-1 shrink-0" onClick={e => e.stopPropagation()}>
                    {inc.status === 'open' && (
                      <button onClick={() => updateIncident.mutate({ id: inc.id, data: { status: 'investigating' } })}
                        className="px-2.5 py-1 text-[10px] bg-yellow-500/10 text-yellow-400 border border-yellow-500/30 rounded-lg hover:bg-yellow-500/20 whitespace-nowrap">
                        🔍 İncele
                      </button>
                    )}
                    {(inc.status === 'open' || inc.status === 'investigating') && (
                      <button onClick={() => updateIncident.mutate({ id: inc.id, data: { status: 'resolved' } })}
                        className="px-2.5 py-1 text-[10px] bg-green-500/10 text-green-400 border border-green-500/30 rounded-lg hover:bg-green-500/20 whitespace-nowrap">
                        ✅ Çöz
                      </button>
                    )}
                    {inc.status === 'resolved' && (
                      <button onClick={() => updateIncident.mutate({ id: inc.id, data: { status: 'closed' } })}
                        className="px-2.5 py-1 text-[10px] bg-slate-500/10 text-slate-400 border border-slate-500/30 rounded-lg hover:bg-slate-500/20 whitespace-nowrap">
                        🔒 Kapat
                      </button>
                    )}
                    <button onClick={() => { if (confirm('Bu incident silinecek. Emin misiniz?')) deleteIncident.mutate(inc.id) }}
                      className="px-2.5 py-1 text-[10px] bg-red-500/10 text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/20">
                      🗑️ Sil
                    </button>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Right: Detail Panel */}
      {selectedIncident && (
        <div className="flex-1 max-w-[520px] bg-slate-800 border border-slate-700 rounded-xl overflow-y-auto max-h-[calc(100vh-120px)] sticky top-0">
          <div className="p-4 border-b border-slate-700 flex items-start justify-between">
            <div>
              <div className="flex items-center gap-2 mb-1">
                <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${SEV_BADGE[selectedIncident.severity] || SEV_BADGE.medium}`}>
                  {SEV_ICONS[selectedIncident.severity]} {selectedIncident.severity.toUpperCase()}
                </span>
                <span className={`px-2 py-0.5 rounded-full text-[10px] ${STATUS_BADGE[selectedIncident.status]}`}>
                  {STATUS_LABELS[selectedIncident.status]}
                </span>
                <span className="text-[10px] text-slate-500">#{selectedIncident.id}</span>
              </div>
              <h2 className="text-white font-semibold text-sm leading-tight">{selectedIncident.title}</h2>
            </div>
            <button onClick={() => setSelectedIncident(null)} className="text-slate-500 hover:text-white ml-2 shrink-0">✕</button>
          </div>

          {detailLoading ? (
            <div className="p-8 text-center"><div className="animate-spin rounded-full h-6 w-6 border-b-2 border-blue-500 mx-auto"></div></div>
          ) : (
            <div className="p-4 space-y-4 text-sm">

              {/* Description */}
              {selectedIncident.description && (
                <div>
                  <p className="text-xs text-slate-400 font-medium mb-1">Açıklama</p>
                  <p className="text-slate-300 text-xs">{selectedIncident.description}</p>
                </div>
              )}

              {/* Meta */}
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div className="bg-slate-900/60 rounded-lg p-2.5">
                  <p className="text-slate-500 mb-0.5">Atanan</p>
                  <p className="text-white">{selectedIncident.assigned_to || '—'}</p>
                </div>
                <div className="bg-slate-900/60 rounded-lg p-2.5">
                  <p className="text-slate-500 mb-0.5">Kaynak</p>
                  <p className="text-white">{selectedIncident.source || '—'}</p>
                </div>
                <div className="bg-slate-900/60 rounded-lg p-2.5">
                  <p className="text-slate-500 mb-0.5">Oluşturulma</p>
                  <p className="text-white">{selectedIncident.created_at ? new Date(selectedIncident.created_at).toLocaleString('tr-TR') : '—'}</p>
                </div>
                <div className="bg-slate-900/60 rounded-lg p-2.5">
                  <p className="text-slate-500 mb-0.5">Çözülme</p>
                  <p className="text-white">{selectedIncident.resolved_at ? new Date(selectedIncident.resolved_at).toLocaleString('tr-TR') : '—'}</p>
                </div>
              </div>

              {/* Affected Servers */}
              {selectedIncident.affected_server_details?.length > 0 && (
                <div>
                  <p className="text-xs text-slate-400 font-medium mb-2">🖥️ Etkilenen Sunucular</p>
                  <div className="flex flex-wrap gap-1.5">
                    {selectedIncident.affected_server_details.map(s => (
                      <span key={s.id} className="text-[10px] px-2 py-0.5 rounded bg-purple-500/20 text-purple-300 border border-purple-500/30">
                        {s.name} {s.ip ? `(${s.ip})` : ''}
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {/* Status Actions */}
              <div>
                <p className="text-xs text-slate-400 font-medium mb-2">Durum İşlemleri</p>
                <div className="flex gap-2 flex-wrap">
                  {selectedIncident.status === 'open' && (
                    <button onClick={() => updateIncident.mutate({ id: selectedIncident.id, data: { status: 'investigating' } })}
                      className="px-3 py-1.5 text-xs bg-yellow-500/10 text-yellow-400 border border-yellow-500/30 rounded-lg hover:bg-yellow-500/20">
                      🔍 İncelemeye Al
                    </button>
                  )}
                  {(selectedIncident.status === 'open' || selectedIncident.status === 'investigating') && (
                    <>
                      <button onClick={() => runRCA.mutate(selectedIncident.id)} disabled={runRCA.isPending}
                        className="px-3 py-1.5 text-xs bg-purple-500/10 text-purple-400 border border-purple-500/30 rounded-lg hover:bg-purple-500/20 disabled:opacity-50">
                        {runRCA.isPending ? '⏳ Analiz...' : '🤖 AI RCA Çalıştır'}
                      </button>
                      <button onClick={() => updateIncident.mutate({ id: selectedIncident.id, data: { status: 'resolved' } })}
                        className="px-3 py-1.5 text-xs bg-green-500/10 text-green-400 border border-green-500/30 rounded-lg hover:bg-green-500/20">
                        ✅ Çözüldü
                      </button>
                    </>
                  )}
                  {selectedIncident.status === 'resolved' && (
                    <button onClick={() => updateIncident.mutate({ id: selectedIncident.id, data: { status: 'closed' } })}
                      className="px-3 py-1.5 text-xs bg-slate-500/10 text-slate-400 border border-slate-500/30 rounded-lg hover:bg-slate-500/20">
                      🔒 Kapat
                    </button>
                  )}
                </div>
              </div>

              {/* Assign */}
              <div>
                <p className="text-xs text-slate-400 font-medium mb-1.5">👤 Atama Güncelle</p>
                <div className="flex gap-2">
                  <input type="text" placeholder="ops-team / admin..."
                    defaultValue={selectedIncident.assigned_to || ''}
                    id={`assign-${selectedIncident.id}`}
                    className="flex-1 bg-slate-900 border border-slate-600 rounded-lg px-2.5 py-1.5 text-white text-xs focus:ring-2 focus:ring-blue-500 focus:outline-none" />
                  <button onClick={() => {
                    const val = (document.getElementById(`assign-${selectedIncident.id}`) as HTMLInputElement)?.value
                    updateIncident.mutate({ id: selectedIncident.id, data: { assigned_to: val || null } })
                  }} className="px-3 py-1.5 text-xs bg-blue-500/10 text-blue-400 border border-blue-500/30 rounded-lg hover:bg-blue-500/20">
                    Kaydet
                  </button>
                </div>
              </div>

              {/* Resolution Notes */}
              <div>
                <p className="text-xs text-slate-400 font-medium mb-1.5">📝 Çözüm Notları</p>
                <textarea value={resolutionText} onChange={e => setResolutionText(e.target.value)}
                  placeholder="Çözüm adımları, neyin yapıldığı..."
                  className="w-full bg-slate-900 border border-slate-600 rounded-lg px-2.5 py-2 text-white text-xs focus:ring-2 focus:ring-blue-500 focus:outline-none" rows={3} />
                <button onClick={() => updateIncident.mutate({ id: selectedIncident.id, data: { resolution: resolutionText } })}
                  disabled={updateIncident.isPending}
                  className="mt-1.5 px-3 py-1.5 text-xs bg-blue-500/10 text-blue-400 border border-blue-500/30 rounded-lg hover:bg-blue-500/20 disabled:opacity-50">
                  {updateIncident.isPending ? 'Kaydediliyor...' : '💾 Notları Kaydet'}
                </button>
                {selectedIncident.resolution && (
                  <div className="mt-2 p-2.5 bg-slate-900/50 rounded-lg border border-slate-700">
                    <p className="text-[10px] text-slate-500 mb-1">Mevcut not:</p>
                    <p className="text-xs text-slate-300 whitespace-pre-wrap">{selectedIncident.resolution}</p>
                  </div>
                )}
              </div>

              {/* RCA Result */}
              {selectedIncident.rca_result?.analysis && (
                <div>
                  <p className="text-xs text-purple-400 font-medium mb-1.5">🤖 AI Kök Neden Analizi</p>
                  <div className="bg-slate-900/50 rounded-lg border border-purple-500/20 p-3">
                    <p className="text-[10px] text-slate-500 mb-1.5">
                      Model: {selectedIncident.rca_result.model} •{' '}
                      {selectedIncident.rca_result.analyzed_at ? new Date(selectedIncident.rca_result.analyzed_at).toLocaleString('tr-TR') : ''}
                    </p>
                    <p className="text-xs text-slate-200 whitespace-pre-wrap leading-relaxed">{selectedIncident.rca_result.analysis}</p>
                  </div>
                </div>
              )}

              {/* Related Events Timeline */}
              {(selectedIncident.related_event_details?.length ?? 0) > 0 && (
                <div>
                  <p className="text-xs text-slate-400 font-medium mb-2">📋 İlgili Eventler ({selectedIncident.related_event_details!.length})</p>
                  <div className="space-y-1.5">
                    {selectedIncident.related_event_details!.map(evt => (
                      <div key={evt.id} className="flex items-start gap-2 bg-slate-900/60 rounded-lg p-2.5 border border-slate-700/50">
                        <span className={`text-xs shrink-0 mt-0.5 ${EVT_SEV_COLOR[evt.severity] || 'text-slate-400'}`}>●</span>
                        <div className="min-w-0 flex-1">
                          <p className="text-xs text-white truncate" title={evt.title}>{evt.title}</p>
                          <div className="flex gap-2 mt-0.5 text-[10px] text-slate-500">
                            <span className="font-mono">{evt.event_type}</span>
                            {evt.resolved && <span className="text-green-500">✅ Çözüldü</span>}
                            <span>{evt.created_at ? new Date(evt.created_at).toLocaleString('tr-TR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' }) : ''}</span>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

export default Incidents
