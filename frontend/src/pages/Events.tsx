import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

interface SystemEvent {
  id: number
  server_id: number | null
  event_type: string
  severity: string
  source: string | null
  title: string
  description: string | null
  is_acknowledged: boolean
  resolved: boolean
  created_at: string | null
}

interface EventStats {
  total: number
  unresolved: number
  critical: number
  warning: number
}

const Events: React.FC = () => {
  const [severityFilter, setSeverityFilter] = useState('')
  const [resolvedFilter, setResolvedFilter] = useState<string>('')
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [newEvent, setNewEvent] = useState({ title: '', event_type: 'custom', severity: 'info', description: '' })
  const queryClient = useQueryClient()

  const { data: eventsData, isLoading } = useQuery<{ total: number; events: SystemEvent[] }>({
    queryKey: ['events', severityFilter, resolvedFilter],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (severityFilter) params.set('severity', severityFilter)
      if (resolvedFilter !== '') params.set('resolved', resolvedFilter)
      const res = await fetch(`${API_BASE_URL}/events/?${params}`)
      if (!res.ok) return { total: 0, events: [] }
      return res.json()
    },
    refetchInterval: 15000
  })

  const { data: stats } = useQuery<EventStats>({
    queryKey: ['eventStats'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/events/stats`)
      if (!res.ok) return { total: 0, unresolved: 0, critical: 0, warning: 0 }
      return res.json()
    },
    refetchInterval: 15000
  })

  const createEvent = useMutation({
    mutationFn: async (data: typeof newEvent) => {
      const res = await fetch(`${API_BASE_URL}/events/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data)
      })
      if (!res.ok) throw new Error('Oluşturulamadı')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['events'] })
      queryClient.invalidateQueries({ queryKey: ['eventStats'] })
      setShowCreateForm(false)
      setNewEvent({ title: '', event_type: 'custom', severity: 'info', description: '' })
    }
  })

  const acknowledgeEvent = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${API_BASE_URL}/events/${id}/acknowledge`, { method: 'POST' })
      if (!res.ok) throw new Error('Hata')
      return res.json()
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['events'] })
  })

  const resolveEvent = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${API_BASE_URL}/events/${id}/resolve`, { method: 'POST' })
      if (!res.ok) throw new Error('Hata')
      return res.json()
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['events'] })
      queryClient.invalidateQueries({ queryKey: ['eventStats'] })
    }
  })

  const events = eventsData?.events || []

  const severityColor = (s: string) => {
    switch (s) {
      case 'critical': case 'emergency': return 'bg-red-500/20 text-red-400 border-red-500/30'
      case 'warning': return 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30'
      case 'info': return 'bg-blue-500/20 text-blue-400 border-blue-500/30'
      default: return 'bg-slate-500/20 text-slate-400 border-slate-500/30'
    }
  }

  const severityIcon = (s: string) => {
    switch (s) {
      case 'critical': case 'emergency': return '🔴'
      case 'warning': return '🟡'
      case 'info': return '🔵'
      default: return '⚪'
    }
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">AIOps Events</h1>
          <p className="text-slate-400 text-sm mt-1">Sistem olaylarını izleyin ve yönetin</p>
        </div>
        <button onClick={() => setShowCreateForm(!showCreateForm)}
          className="px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all text-sm">
          {showCreateForm ? '✕ İptal' : '➕ Yeni Event'}
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-4 gap-4">
        {[
          { label: 'Toplam', value: stats?.total || 0, color: 'from-blue-500 to-blue-600', icon: '📋' },
          { label: 'Çözülmemiş', value: stats?.unresolved || 0, color: 'from-orange-500 to-orange-600', icon: '⏳' },
          { label: 'Kritik', value: stats?.critical || 0, color: 'from-red-500 to-red-600', icon: '🔴' },
          { label: 'Uyarı', value: stats?.warning || 0, color: 'from-yellow-500 to-yellow-600', icon: '🟡' },
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
          <h3 className="text-lg font-medium text-white mb-4">Yeni Event Oluştur</h3>
          <form onSubmit={e => { e.preventDefault(); createEvent.mutate(newEvent) }} className="space-y-4">
            <div className="grid grid-cols-3 gap-4">
              <div>
                <label className="block text-sm text-slate-300 mb-1">Başlık *</label>
                <input type="text" required value={newEvent.title} onChange={e => setNewEvent({ ...newEvent, title: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none" />
              </div>
              <div>
                <label className="block text-sm text-slate-300 mb-1">Tip</label>
                <select value={newEvent.event_type} onChange={e => setNewEvent({ ...newEvent, event_type: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none">
                  <option value="custom">Custom</option>
                  <option value="cpu_high">CPU High</option>
                  <option value="memory_high">Memory High</option>
                  <option value="disk_full">Disk Full</option>
                  <option value="service_down">Service Down</option>
                  <option value="network_issue">Network Issue</option>
                </select>
              </div>
              <div>
                <label className="block text-sm text-slate-300 mb-1">Önem</label>
                <select value={newEvent.severity} onChange={e => setNewEvent({ ...newEvent, severity: e.target.value })}
                  className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none">
                  <option value="info">Info</option>
                  <option value="warning">Warning</option>
                  <option value="critical">Critical</option>
                  <option value="emergency">Emergency</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-sm text-slate-300 mb-1">Açıklama</label>
              <textarea value={newEvent.description} onChange={e => setNewEvent({ ...newEvent, description: e.target.value })}
                className="w-full bg-slate-900 border border-slate-600 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none" rows={2} />
            </div>
            <button type="submit" disabled={createEvent.isPending}
              className="px-4 py-2 bg-green-600 text-white rounded-lg hover:bg-green-500 text-sm disabled:opacity-50">
              {createEvent.isPending ? 'Oluşturuluyor...' : 'Oluştur'}
            </button>
          </form>
        </div>
      )}

      {/* Filters */}
      <div className="flex gap-3">
        <select value={severityFilter} onChange={e => setSeverityFilter(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none">
          <option value="">Tüm Seviyeler</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="critical">Critical</option>
          <option value="emergency">Emergency</option>
        </select>
        <select value={resolvedFilter} onChange={e => setResolvedFilter(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none">
          <option value="">Tüm Durumlar</option>
          <option value="false">Aktif</option>
          <option value="true">Çözülmüş</option>
        </select>
      </div>

      {/* Events Table */}
      {isLoading ? (
        <div className="text-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto"></div></div>
      ) : events.length === 0 ? (
        <div className="text-center py-12 bg-slate-800 rounded-xl border border-dashed border-slate-700">
          <span className="text-4xl block mb-3">📋</span>
          <p className="text-slate-400">Henüz event yok</p>
        </div>
      ) : (
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-slate-700 text-left">
                <th className="px-4 py-3 text-xs font-medium text-slate-400">Önem</th>
                <th className="px-4 py-3 text-xs font-medium text-slate-400">Başlık</th>
                <th className="px-4 py-3 text-xs font-medium text-slate-400">Tip</th>
                <th className="px-4 py-3 text-xs font-medium text-slate-400">Kaynak</th>
                <th className="px-4 py-3 text-xs font-medium text-slate-400">Durum</th>
                <th className="px-4 py-3 text-xs font-medium text-slate-400">Tarih</th>
                <th className="px-4 py-3 text-xs font-medium text-slate-400">İşlem</th>
              </tr>
            </thead>
            <tbody>
              {events.map(event => (
                <tr key={event.id} className="border-b border-slate-700/50 hover:bg-slate-700/30">
                  <td className="px-4 py-3">
                    <span className={`px-2 py-1 rounded-full text-[10px] font-medium border ${severityColor(event.severity)}`}>
                      {severityIcon(event.severity)} {event.severity}
                    </span>
                  </td>
                  <td className="px-4 py-3 text-sm text-white">{event.title}</td>
                  <td className="px-4 py-3 text-xs text-slate-400 font-mono">{event.event_type}</td>
                  <td className="px-4 py-3 text-xs text-slate-400">{event.source || '-'}</td>
                  <td className="px-4 py-3">
                    {event.resolved ? (
                      <span className="text-green-400 text-xs">✅ Çözüldü</span>
                    ) : event.is_acknowledged ? (
                      <span className="text-yellow-400 text-xs">👁 Onaylandı</span>
                    ) : (
                      <span className="text-red-400 text-xs">⏳ Bekliyor</span>
                    )}
                  </td>
                  <td className="px-4 py-3 text-xs text-slate-500">
                    {event.created_at ? new Date(event.created_at).toLocaleString('tr-TR') : '-'}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex gap-1">
                      {!event.is_acknowledged && !event.resolved && (
                        <button onClick={() => acknowledgeEvent.mutate(event.id)}
                          className="px-2 py-1 text-[10px] bg-yellow-500/10 text-yellow-400 border border-yellow-500/30 rounded hover:bg-yellow-500/20" title="Onayla">
                          👁
                        </button>
                      )}
                      {!event.resolved && (
                        <button onClick={() => resolveEvent.mutate(event.id)}
                          className="px-2 py-1 text-[10px] bg-green-500/10 text-green-400 border border-green-500/30 rounded hover:bg-green-500/20" title="Çözüldü">
                          ✅
                        </button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default Events
