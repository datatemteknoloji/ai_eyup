import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'

interface SystemEvent {
  id: number
  server_id: number | null
  server_name: string | null
  event_type: string
  severity: string
  source: string | null
  title: string
  description: string | null
  raw_data: any
  is_acknowledged: boolean
  resolved: boolean
  created_at: string | null
}

interface EventStats {
  total: number
  unresolved: number
  critical: number
  warning: number
  emergency: number
  acknowledged: number
}

const SEVERITY_STYLES: Record<string, string> = {
  critical:  'bg-red-500/20 text-red-400 border-red-500/30',
  emergency: 'bg-pink-500/20 text-pink-400 border-pink-500/30',
  warning:   'bg-yellow-500/20 text-yellow-400 border-yellow-500/30',
  info:      'bg-blue-500/20 text-blue-400 border-blue-500/30',
  error:     'bg-orange-500/20 text-orange-400 border-orange-500/30',
}
const SEVERITY_ICONS: Record<string, string> = {
  critical: '🔴', emergency: '🚨', warning: '🟡', info: '🔵', error: '🟠'
}

const PAGE_SIZE = 50

const Events: React.FC = () => {
  const [severityFilter, setSeverityFilter] = useState('')
  const [typeFilter, setTypeFilter]         = useState('')
  const [resolvedFilter, setResolvedFilter] = useState<string>('false')
  const [search, setSearch]                 = useState('')
  const [page, setPage]                     = useState(0)
  const [selectedIds, setSelectedIds]       = useState<Set<number>>(new Set())
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [expandedRaw, setExpandedRaw]       = useState<number | null>(null)
  const [newEvent, setNewEvent]             = useState({ title: '', event_type: 'custom', severity: 'info', description: '' })
  const queryClient = useQueryClient()

  const { data: eventsData, isLoading } = useQuery<{ total: number; events: SystemEvent[] }>({
    queryKey: ['events', severityFilter, typeFilter, resolvedFilter, search, page],
    queryFn: async () => {
      const params = new URLSearchParams()
      if (severityFilter) params.set('severity', severityFilter)
      if (typeFilter) params.set('event_type', typeFilter)
      if (resolvedFilter !== '') params.set('resolved', resolvedFilter)
      if (search) params.set('search', search)
      params.set('limit', String(PAGE_SIZE))
      params.set('offset', String(page * PAGE_SIZE))
      const res = await fetch(`${API_BASE_URL}/events/?${params}`)
      if (!res.ok) return { total: 0, events: [] }
      return res.json()
    },
    refetchInterval: 20000
  })

  const { data: stats } = useQuery<EventStats>({
    queryKey: ['eventStats'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/events/stats`)
      if (!res.ok) return { total: 0, unresolved: 0, critical: 0, warning: 0, emergency: 0, acknowledged: 0 }
      return res.json()
    },
    refetchInterval: 20000
  })

  const { data: eventTypes } = useQuery<string[]>({
    queryKey: ['eventTypes'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/events/types`)
      if (!res.ok) return []
      return res.json()
    }
  })

  const invalidate = () => {
    queryClient.invalidateQueries({ queryKey: ['events'] })
    queryClient.invalidateQueries({ queryKey: ['eventStats'] })
  }

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
      invalidate()
      setShowCreateForm(false)
      setNewEvent({ title: '', event_type: 'custom', severity: 'info', description: '' })
    }
  })

  const ackEvent = useMutation({
    mutationFn: async (id: number) => {
      await fetch(`${API_BASE_URL}/events/${id}/acknowledge`, { method: 'POST' })
    },
    onSuccess: invalidate
  })

  const resolveEvent = useMutation({
    mutationFn: async (id: number) => {
      await fetch(`${API_BASE_URL}/events/${id}/resolve`, { method: 'POST' })
    },
    onSuccess: invalidate
  })

  const deleteEvent = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${API_BASE_URL}/events/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error('Silinemedi')
    },
    onSuccess: invalidate
  })

  const bulkAction = useMutation({
    mutationFn: async ({ action, ids }: { action: string; ids: number[] }) => {
      const res = await fetch(`${API_BASE_URL}/events/bulk-action`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_ids: ids, action })
      })
      if (!res.ok) throw new Error('İşlem başarısız')
      return res.json()
    },
    onSuccess: () => { invalidate(); setSelectedIds(new Set()) }
  })

  const bulkDelete = useMutation({
    mutationFn: async (ids: number[]) => {
      const res = await fetch(`${API_BASE_URL}/events/bulk-delete`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_ids: ids, action: 'delete' })
      })
      if (!res.ok) throw new Error('Silinemedi')
    },
    onSuccess: () => { invalidate(); setSelectedIds(new Set()) }
  })

  const events = eventsData?.events || []
  const total  = eventsData?.total || 0
  const totalPages = Math.ceil(total / PAGE_SIZE)

  const toggleSelect = (id: number) => {
    setSelectedIds(prev => {
      const next = new Set(prev)
      next.has(id) ? next.delete(id) : next.add(id)
      return next
    })
  }

  const toggleSelectAll = () => {
    if (selectedIds.size === events.length) {
      setSelectedIds(new Set())
    } else {
      setSelectedIds(new Set(events.map(e => e.id)))
    }
  }

  const sColor = (s: string) => SEVERITY_STYLES[s] || SEVERITY_STYLES.info
  const sIcon  = (s: string) => SEVERITY_ICONS[s]  || '⚪'

  return (
    <div className="space-y-5">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">AIOps Events</h1>
          <p className="text-slate-400 text-sm mt-1">Sistem olaylarını izleyin ve yönetin</p>
        </div>
        <button onClick={() => setShowCreateForm(!showCreateForm)}
          className="px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all text-sm font-medium">
          {showCreateForm ? '✕ İptal' : '➕ Yeni Event'}
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
        {[
          { label: 'Toplam',       value: stats?.total || 0,        color: 'from-blue-500 to-blue-600',     icon: '📋' },
          { label: 'Çözülmemiş',   value: stats?.unresolved || 0,   color: 'from-orange-500 to-orange-600', icon: '⏳' },
          { label: 'Kritik',       value: stats?.critical || 0,     color: 'from-red-500 to-red-600',       icon: '🔴' },
          { label: 'Emergency',    value: stats?.emergency || 0,    color: 'from-pink-500 to-pink-600',     icon: '🚨' },
          { label: 'Uyarı',        value: stats?.warning || 0,      color: 'from-yellow-500 to-yellow-600', icon: '🟡' },
          { label: 'Onaylandı',    value: stats?.acknowledged || 0, color: 'from-green-500 to-green-600',   icon: '👁' },
        ].map((s, i) => (
          <div key={i} className="bg-slate-800 rounded-xl border border-slate-700 p-3">
            <div className="flex items-center justify-between">
              <div>
                <p className="text-slate-400 text-[10px]">{s.label}</p>
                <p className="text-xl font-bold text-white mt-0.5">{s.value}</p>
              </div>
              <div className={`w-8 h-8 rounded-lg bg-gradient-to-br ${s.color} flex items-center justify-center text-sm`}>
                {s.icon}
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
                  <option value="error">Error</option>
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
      <div className="flex flex-wrap gap-2">
        <input type="text" value={search} onChange={e => { setSearch(e.target.value); setPage(0) }}
          placeholder="🔍 Başlıkta ara..."
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none w-52" />
        <select value={severityFilter} onChange={e => { setSeverityFilter(e.target.value); setPage(0) }}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none">
          <option value="">Tüm Seviyeler</option>
          <option value="info">Info</option>
          <option value="warning">Warning</option>
          <option value="error">Error</option>
          <option value="critical">Critical</option>
          <option value="emergency">Emergency</option>
        </select>
        <select value={typeFilter} onChange={e => { setTypeFilter(e.target.value); setPage(0) }}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none">
          <option value="">Tüm Tipler</option>
          {(eventTypes || []).map(t => <option key={t} value={t}>{t}</option>)}
        </select>
        <select value={resolvedFilter} onChange={e => { setResolvedFilter(e.target.value); setPage(0) }}
          className="bg-slate-800 border border-slate-700 rounded-lg px-3 py-2 text-white text-sm focus:ring-2 focus:ring-blue-500 focus:outline-none">
          <option value="">Tüm Durumlar</option>
          <option value="false">Aktif</option>
          <option value="true">Çözülmüş</option>
        </select>
        <span className="ml-auto text-xs text-slate-500 self-center">{total} sonuç</span>
      </div>

      {/* Bulk Action Bar */}
      {selectedIds.size > 0 && (
        <div className="flex items-center gap-3 bg-blue-500/10 border border-blue-500/30 rounded-xl px-4 py-3">
          <span className="text-blue-400 text-sm font-medium">{selectedIds.size} event seçili</span>
          <button onClick={() => bulkAction.mutate({ action: 'acknowledge', ids: [...selectedIds] })}
            disabled={bulkAction.isPending}
            className="px-3 py-1.5 text-xs bg-yellow-500/10 text-yellow-400 border border-yellow-500/30 rounded-lg hover:bg-yellow-500/20 disabled:opacity-50">
            👁 Toplu Onayla
          </button>
          <button onClick={() => bulkAction.mutate({ action: 'resolve', ids: [...selectedIds] })}
            disabled={bulkAction.isPending}
            className="px-3 py-1.5 text-xs bg-green-500/10 text-green-400 border border-green-500/30 rounded-lg hover:bg-green-500/20 disabled:opacity-50">
            ✅ Toplu Çöz
          </button>
          <button onClick={() => { if (confirm(`${selectedIds.size} event silinecek. Emin misiniz?`)) bulkDelete.mutate([...selectedIds]) }}
            disabled={bulkDelete.isPending}
            className="px-3 py-1.5 text-xs bg-red-500/10 text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/20 disabled:opacity-50">
            🗑️ Toplu Sil
          </button>
          <button onClick={() => setSelectedIds(new Set())} className="ml-auto text-xs text-slate-400 hover:text-white">Seçimi Kaldır</button>
        </div>
      )}

      {/* Table */}
      {isLoading ? (
        <div className="text-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto"></div></div>
      ) : events.length === 0 ? (
        <div className="text-center py-12 bg-slate-800 rounded-xl border border-dashed border-slate-700">
          <span className="text-4xl block mb-3">📋</span>
          <p className="text-slate-400">Henüz event yok</p>
        </div>
      ) : (
        <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-700 text-left bg-slate-800/80">
                <th className="px-3 py-3 w-8">
                  <input type="checkbox" checked={selectedIds.size === events.length && events.length > 0}
                    onChange={toggleSelectAll}
                    className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500" />
                </th>
                <th className="px-3 py-3 text-xs font-medium text-slate-400">Önem</th>
                <th className="px-3 py-3 text-xs font-medium text-slate-400">Başlık</th>
                <th className="px-3 py-3 text-xs font-medium text-slate-400">Sunucu</th>
                <th className="px-3 py-3 text-xs font-medium text-slate-400">Tip</th>
                <th className="px-3 py-3 text-xs font-medium text-slate-400">Kaynak</th>
                <th className="px-3 py-3 text-xs font-medium text-slate-400">Durum</th>
                <th className="px-3 py-3 text-xs font-medium text-slate-400">Tarih</th>
                <th className="px-3 py-3 text-xs font-medium text-slate-400">İşlem</th>
              </tr>
            </thead>
            <tbody>
              {events.map(event => (
                <React.Fragment key={event.id}>
                  <tr className={`border-b border-slate-700/50 hover:bg-slate-700/20 transition-colors ${selectedIds.has(event.id) ? 'bg-blue-500/5' : ''}`}>
                    <td className="px-3 py-3">
                      <input type="checkbox" checked={selectedIds.has(event.id)} onChange={() => toggleSelect(event.id)}
                        className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500" />
                    </td>
                    <td className="px-3 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${sColor(event.severity)}`}>
                        {sIcon(event.severity)} {event.severity}
                      </span>
                    </td>
                    <td className="px-3 py-3 max-w-xs">
                      <p className="text-white text-xs truncate" title={event.title}>{event.title}</p>
                      {event.description && event.description !== event.title && (
                        <p className="text-slate-500 text-[10px] truncate mt-0.5" title={event.description}>{event.description}</p>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      {event.server_name ? (
                        <span className="text-xs text-purple-400 font-mono">{event.server_name}</span>
                      ) : (
                        <span className="text-xs text-slate-600">-</span>
                      )}
                    </td>
                    <td className="px-3 py-3">
                      <span className="text-[10px] text-slate-400 font-mono bg-slate-900/50 px-1.5 py-0.5 rounded">{event.event_type}</span>
                    </td>
                    <td className="px-3 py-3 text-xs text-slate-500">{event.source || '-'}</td>
                    <td className="px-3 py-3">
                      {event.resolved ? (
                        <span className="text-green-400 text-[10px] font-medium">✅ Çözüldü</span>
                      ) : event.is_acknowledged ? (
                        <span className="text-yellow-400 text-[10px] font-medium">👁 Onaylandı</span>
                      ) : (
                        <span className="text-red-400 text-[10px] font-medium">⏳ Bekliyor</span>
                      )}
                    </td>
                    <td className="px-3 py-3 text-[10px] text-slate-500 whitespace-nowrap">
                      {event.created_at ? new Date(event.created_at).toLocaleString('tr-TR', { day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit' }) : '-'}
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex gap-1">
                        {event.raw_data && Object.keys(event.raw_data).length > 0 && (
                          <button onClick={() => setExpandedRaw(expandedRaw === event.id ? null : event.id)}
                            className="px-2 py-1 text-[10px] bg-slate-500/10 text-slate-400 border border-slate-500/30 rounded hover:bg-slate-500/20" title="Raw Data">
                            📦
                          </button>
                        )}
                        {!event.is_acknowledged && !event.resolved && (
                          <button onClick={() => ackEvent.mutate(event.id)}
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
                        <button onClick={() => { if (confirm('Bu event silinecek. Emin misiniz?')) deleteEvent.mutate(event.id) }}
                          className="px-2 py-1 text-[10px] bg-red-500/10 text-red-400 border border-red-500/30 rounded hover:bg-red-500/20" title="Sil">
                          🗑️
                        </button>
                      </div>
                    </td>
                  </tr>
                  {expandedRaw === event.id && (
                    <tr className="bg-slate-900/60">
                      <td colSpan={9} className="px-6 py-3">
                        <p className="text-xs text-slate-400 mb-1 font-medium">Raw Data:</p>
                        <pre className="text-[11px] text-green-400 font-mono bg-slate-950 rounded p-3 overflow-auto max-h-40">
                          {JSON.stringify(event.raw_data, null, 2)}
                        </pre>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">
            {page * PAGE_SIZE + 1} – {Math.min((page + 1) * PAGE_SIZE, total)} / {total} event
          </span>
          <div className="flex gap-2">
            <button disabled={page === 0} onClick={() => setPage(p => p - 1)}
              className="px-3 py-1.5 text-xs bg-slate-800 border border-slate-700 text-slate-300 rounded-lg hover:bg-slate-700 disabled:opacity-40">
              ← Önceki
            </button>
            {Array.from({ length: Math.min(totalPages, 7) }).map((_, i) => {
              const p = page < 4 ? i : page - 3 + i
              if (p >= totalPages) return null
              return (
                <button key={p} onClick={() => setPage(p)}
                  className={`px-3 py-1.5 text-xs border rounded-lg ${p === page ? 'bg-blue-600 border-blue-500 text-white' : 'bg-slate-800 border-slate-700 text-slate-300 hover:bg-slate-700'}`}>
                  {p + 1}
                </button>
              )
            })}
            <button disabled={page >= totalPages - 1} onClick={() => setPage(p => p + 1)}
              className="px-3 py-1.5 text-xs bg-slate-800 border border-slate-700 text-slate-300 rounded-lg hover:bg-slate-700 disabled:opacity-40">
              Sonraki →
            </button>
          </div>
        </div>
      )}
    </div>
  )
}

export default Events
