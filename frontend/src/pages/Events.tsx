import React, { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'

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

interface EventGroup {
  event_type: string
  title: string
  severity: string
  server_id: number | null
  server_name: string | null
  event_ids: number[]
  count: number
  latest_created_at: string | null
  resolved?: boolean
  is_acknowledged?: boolean
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
  const [groupedView, setGroupedView]       = useState(true)
  const [sortBy, setSortBy]                 = useState<keyof EventGroup>('latest_created_at')
  const [sortDir, setSortDir]               = useState<'asc'|'desc'>('desc')
  const [detailGroupIds, setDetailGroupIds] = useState<number[] | null>(null)
  const [scanning, setScanning]             = useState(false)
  const [selectedGroups, setSelectedGroups] = useState<Set<number>>(new Set())
  const [analyzeGroup, setAnalyzeGroup]     = useState<EventGroup | null>(null)
  const [analysisText, setAnalysisText]     = useState('')
  const [isAnalyzing, setIsAnalyzing]       = useState(false)
  const analyzeModel = localStorage.getItem('chat_selected_model') || 'llama3.2:3b'
  const analyzeAbortRef                     = useRef<AbortController | null>(null)
  const [scanResult, setScanResult]         = useState<{total_servers:number; servers_with_logs:number; total_saved:number; details:any[]} | null>(null)
  const queryClient = useQueryClient()


  const paramsBase = () => {
    const p = new URLSearchParams()
    if (severityFilter) p.set('severity', severityFilter)
    if (typeFilter) p.set('event_type', typeFilter)
    if (resolvedFilter !== '') p.set('resolved', resolvedFilter)
    if (search) p.set('search', search)
    return p
  }

  const { data: eventsData, isLoading } = useQuery<{ total: number; events: SystemEvent[] }>({
    queryKey: ['events', 'list', severityFilter, typeFilter, resolvedFilter, search, page],
    queryFn: async () => {
      const params = paramsBase()
      params.set('limit', String(PAGE_SIZE))
      params.set('offset', String(page * PAGE_SIZE))
      const res = await fetch(`${API_BASE_URL}/events/?${params}`)
      if (!res.ok) return { total: 0, events: [] }
      return res.json()
    },
    enabled: !groupedView,
    refetchInterval: 20000
  })

  const { data: groupedData, isLoading: groupedLoading } = useQuery<{ total: number; groups: EventGroup[] }>({
    queryKey: ['events', 'grouped', severityFilter, typeFilter, resolvedFilter, search, page, sortBy, sortDir],
    queryFn: async () => {
      const params = paramsBase()
      params.set('limit', String(PAGE_SIZE))
      params.set('offset', String(page * PAGE_SIZE))
      params.set('sort_by', sortBy as string)
      params.set('sort_dir', sortDir)
      const res = await fetch(`${API_BASE_URL}/events/grouped?${params}`)
      if (!res.ok) return { total: 0, groups: [] }
      return res.json()
    },
    enabled: groupedView,
    refetchInterval: 20000
  })

  const { data: occurrenceData } = useQuery<{ events: SystemEvent[] }>({
    queryKey: ['events', 'occurrences', detailGroupIds?.join(',')],
    queryFn: async () => {
      if (!detailGroupIds?.length) return { events: [] }
      const res = await fetch(`${API_BASE_URL}/events/occurrences?ids=${detailGroupIds.join(',')}`)
      if (!res.ok) return { events: [] }
      return res.json()
    },
    enabled: !!detailGroupIds?.length
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

  const handleScan = async (onlyAiReady = false) => {
    setScanning(true)
    setScanResult(null)
    try {
      const res = await fetch(`${API_BASE_URL}/events/scan?only_ai_ready=${onlyAiReady}`, { method: 'POST' })
      const data = await res.json()
      setScanResult(data)
      invalidate()
    } catch {
      setScanResult(null)
    } finally {
      setScanning(false)
    }
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

  const events     = eventsData?.events  || []
  const groups     = groupedData?.groups || []

  const sortedGroups = groups  // sorting done server-side

  const handleSort = (col: keyof EventGroup) => {
    setPage(0)
    if (sortBy === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortBy(col); setSortDir('desc') }
  }
  const SortIcon = ({ col }: { col: keyof EventGroup }) => {
    if (sortBy !== col) return <span className="text-slate-600 ml-1">⇅</span>
    return <span className="text-blue-400 ml-1">{sortDir === 'asc' ? '↑' : '↓'}</span>
  }
  const total      = groupedView ? (groupedData?.total ?? 0) : (eventsData?.total ?? 0)
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const isLoadingList = groupedView ? groupedLoading : isLoading

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

  // Grup toplu seçim
  const toggleGroupSelect = (idx: number) => {
    setSelectedGroups(prev => {
      const next = new Set(prev)
      next.has(idx) ? next.delete(idx) : next.add(idx)
      return next
    })
  }
  const toggleSelectAllGroups = () => {
    if (selectedGroups.size === sortedGroups.length) setSelectedGroups(new Set())
    else setSelectedGroups(new Set(sortedGroups.map((_, i) => i)))
  }
  const selectedGroupEventIds = (): number[] =>
    [...selectedGroups].flatMap(i => sortedGroups[i]?.event_ids ?? [])

  // Grup toplu işlem
  const groupBulkAction = async (action: 'acknowledge' | 'resolve' | 'delete') => {
    const ids = selectedGroupEventIds()
    if (!ids.length) return
    if (action === 'delete') {
      await fetch(`${API_BASE_URL}/events/bulk-delete`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_ids: ids, action: 'delete' })
      })
    } else {
      await fetch(`${API_BASE_URL}/events/bulk-action`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ event_ids: ids, action })
      })
    }
    invalidate()
    setSelectedGroups(new Set())
  }

  // Analiz: grup event'larını AI'ye gönder
  const startAnalyze = async (grp: EventGroup) => {
    analyzeAbortRef.current?.abort()
    setAnalyzeGroup(grp)
    setAnalysisText('')
    setIsAnalyzing(true)
    const prompt = `Aşağıdaki sistem eventi/grubu hakkında detaylı analiz yap ve çözüm önerisi sun:\n\n` +
      `Başlık: ${grp.title}\n` +
      `Önem: ${grp.severity}\n` +
      `Tip: ${grp.event_type}\n` +
      (grp.server_name ? `Sunucu: ${grp.server_name}\n` : '') +
      `Adet: ${grp.count}×\n\n` +
      `Lütfen şunları içeren bir analiz yap:\n` +
      `1. Bu hatanın/uyarının ne anlama geldiği\n` +
      `2. Olası nedenleri\n` +
      `3. Adım adım çözüm önerileri\n` +
      `4. Tekrar önleme yöntemleri`
    const ctrl = new AbortController()
    analyzeAbortRef.current = ctrl
    try {
      const res = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: prompt, use_rag: true, model: analyzeModel }),
        signal: ctrl.signal
      })
      if (!res.ok || !res.body) throw new Error('HTTP ' + res.status)
      const reader = res.body.getReader()
      const decoder = new TextDecoder()
      let buf = '', acc = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n')
        buf = lines.pop() ?? ''
        for (const line of lines) {
          if (!line.startsWith('data: ')) continue
          try {
            const chunk = JSON.parse(line.slice(6))
            if (chunk.token) { acc += chunk.token; setAnalysisText(acc) }
            if (chunk.done) setIsAnalyzing(false)
          } catch {}
        }
      }
    } catch (e: any) {
      if (e?.name !== 'AbortError') setAnalysisText('❌ Analiz başarısız.')
    } finally {
      setIsAnalyzing(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-white">AIOps Events</h1>
          <p className="text-slate-400 text-sm mt-1">Sistem olaylarını izleyin ve yönetin</p>
        </div>
        <div className="flex items-center gap-2">
          <button onClick={() => handleScan(false)} disabled={scanning}
            className="px-4 py-2 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-lg hover:from-green-500 hover:to-green-600 transition-all text-sm font-medium disabled:opacity-60 flex items-center gap-2">
            {scanning ? (
              <><span className="animate-spin inline-block">⏳</span><span> Taranıyor...</span></>
            ) : (
              <><span>🔍</span><span> Şimdi Tara</span></>
            )}
          </button>
          <button onClick={() => setShowCreateForm(!showCreateForm)}
            className="px-4 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all text-sm font-medium">
            {showCreateForm ? '✕ İptal' : '➕ Yeni Event'}
          </button>
        </div>
      </div>

      <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
        {[
          { label: 'Toplam',     value: stats?.total || 0,        color: 'from-blue-500 to-blue-600',     icon: '📋' },
          { label: 'Çözülmemiş', value: stats?.unresolved || 0,   color: 'from-orange-500 to-orange-600', icon: '⏳' },
          { label: 'Kritik',     value: stats?.critical || 0,     color: 'from-red-500 to-red-600',       icon: '🔴' },
          { label: 'Emergency',  value: stats?.emergency || 0,    color: 'from-pink-500 to-pink-600',     icon: '🚨' },
          { label: 'Uyarı',      value: stats?.warning || 0,      color: 'from-yellow-500 to-yellow-600', icon: '🟡' },
          { label: 'Onaylandı',  value: stats?.acknowledged || 0, color: 'from-green-500 to-green-600',   icon: '👁' },
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

      {/* Scan Result */}
      {scanResult && (
        <div className={`rounded-xl border px-5 py-4 text-sm flex items-start justify-between gap-4 ${
          scanResult.total_saved > 0
            ? 'bg-green-500/10 border-green-500/30'
            : 'bg-slate-800 border-slate-700'
        }`}>
          <div>
            <p className="font-medium text-white mb-1">
              {scanResult.total_saved > 0
                ? `✅ Tarama tamamlandı — ${scanResult.total_saved} yeni event kaydedildi`
                : '✅ Tarama tamamlandı — yeni event bulunamadı'}
            </p>
            <p className="text-slate-400 text-xs">
              {scanResult.total_servers} sunucu tarandı · {scanResult.servers_with_logs} sunucuda log bulundu
            </p>
            {scanResult.details.length > 0 && (
              <div className="mt-2 space-y-0.5">
                {scanResult.details.map((d: any, i: number) => (
                  <p key={i} className="text-xs text-slate-400">
                    <span className="text-white font-mono">{d.server}</span>
                    {' — '}{d.saved} event
                    {d.critical > 0 && <span className="text-red-400 ml-1">({d.critical} kritik)</span>}
                    {d.error > 0 && <span className="text-orange-400 ml-1">({d.error} hata)</span>}
                  </p>
                ))}
              </div>
            )}
          </div>
          <button onClick={() => setScanResult(null)} className="text-slate-500 hover:text-white text-lg leading-none flex-shrink-0">&times;</button>
        </div>
      )}

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
        <label className="flex items-center gap-2 self-center cursor-pointer select-none ml-1">
          <div onClick={() => { setGroupedView(v => !v); setPage(0) }}
            className={`relative w-9 h-5 rounded-full transition-colors cursor-pointer ${groupedView ? 'bg-blue-600' : 'bg-slate-600'}`}>
            <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${groupedView ? 'translate-x-4' : ''}`} />
          </div>
          <span className="text-xs text-slate-400">Tekil göster (duplikaları grupla)</span>
        </label>
        <span className="ml-auto text-xs text-slate-500 self-center">{total} {groupedView ? 'grup' : 'sonuç'}</span>
      </div>

      {!groupedView && selectedIds.size > 0 && (
        <div className="flex items-center gap-3 bg-blue-500/10 border border-blue-500/30 rounded-xl px-4 py-3">
          <span className="text-blue-400 text-sm font-medium">{selectedIds.size} event seçili</span>
          <button onClick={() => bulkAction.mutate({ action: 'acknowledge', ids: [...selectedIds] })} disabled={bulkAction.isPending}
            className="px-3 py-1.5 text-xs bg-yellow-500/10 text-yellow-400 border border-yellow-500/30 rounded-lg hover:bg-yellow-500/20 disabled:opacity-50">
            👁 Toplu Onayla
          </button>
          <button onClick={() => bulkAction.mutate({ action: 'resolve', ids: [...selectedIds] })} disabled={bulkAction.isPending}
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

      {detailGroupIds && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4" onClick={() => setDetailGroupIds(null)}>
          <div className="bg-slate-800 rounded-xl border border-slate-700 max-w-4xl w-full max-h-[85vh] flex flex-col shadow-2xl" onClick={e => e.stopPropagation()}>
            <div className="px-6 py-4 border-b border-slate-700 flex items-center justify-between flex-shrink-0">
              <h3 className="text-lg font-semibold text-white">
                Tüm oluşumlar
                <span className="ml-2 px-2 py-0.5 rounded bg-amber-500/20 text-amber-400 text-sm font-medium">
                  {occurrenceData?.events?.length ?? '...'} kayıt
                </span>
              </h3>
              <button onClick={() => setDetailGroupIds(null)} className="text-slate-400 hover:text-white text-2xl leading-none">&times;</button>
            </div>
            <div className="overflow-auto flex-1 p-4 space-y-2">
              {(occurrenceData?.events ?? []).length === 0 ? (
                <div className="text-center py-8 text-slate-500">Yükleniyor...</div>
              ) : (occurrenceData?.events ?? []).map(ev => (
                <div key={ev.id} className="bg-slate-900/70 rounded-lg p-3 border border-slate-700">
                  <div className="flex items-center gap-3 flex-wrap">
                    <span className={`px-2 py-0.5 rounded text-[10px] font-semibold border ${sColor(ev.severity)}`}>
                      {sIcon(ev.severity)} {ev.severity}
                    </span>
                    {ev.server_name && <span className="text-[10px] text-purple-400 font-mono">{ev.server_name}</span>}
                    <span className="text-[10px] text-slate-400 font-mono bg-slate-800 px-1.5 py-0.5 rounded">{ev.event_type}</span>
                    {ev.resolved && <span className="text-[10px] text-green-400">✅ Çözüldü</span>}
                    {ev.is_acknowledged && !ev.resolved && <span className="text-[10px] text-yellow-400">👁 Onaylandı</span>}
                    <span className="ml-auto text-[10px] text-slate-500">
                      {ev.created_at ? new Date(ev.created_at).toLocaleString('tr-TR') : '-'}
                    </span>
                  </div>
                  <p className="text-white text-xs mt-2 break-words">{ev.title}</p>
                  {ev.description && ev.description !== ev.title && (
                    <p className="text-slate-400 text-[11px] mt-1">{ev.description}</p>
                  )}
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {isLoadingList ? (
        <div className="text-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto"></div></div>
      ) : groupedView ? (
        groups.length === 0 ? (
          <div className="text-center py-12 bg-slate-800 rounded-xl border border-dashed border-slate-700">
            <span className="text-4xl block mb-3">📋</span>
            <p className="text-slate-400">Henüz event yok</p>
          </div>
        ) : (
          <div className="bg-slate-800 rounded-xl border border-slate-700 overflow-hidden">
            <table className="w-full text-sm">
              {/* Toplu işlem toolbar */}
              {selectedGroups.size > 0 && (
                <div className="flex items-center gap-2 px-4 py-2 bg-blue-600/10 border-b border-blue-500/30">
                  <span className="text-xs text-blue-300 font-medium">{selectedGroups.size} grup seçili ({selectedGroupEventIds().length} event)</span>
                  <div className="ml-auto flex gap-2">
                    <button onClick={() => groupBulkAction('acknowledge')}
                      className="px-3 py-1 text-xs bg-yellow-500/20 text-yellow-300 border border-yellow-500/30 rounded hover:bg-yellow-500/30">
                      👁 Tümünü Onayla
                    </button>
                    <button onClick={() => groupBulkAction('resolve')}
                      className="px-3 py-1 text-xs bg-green-500/20 text-green-300 border border-green-500/30 rounded hover:bg-green-500/30">
                      ✅ Tümünü Çöz
                    </button>
                    <button onClick={() => groupBulkAction('delete')}
                      className="px-3 py-1 text-xs bg-red-500/20 text-red-300 border border-red-500/30 rounded hover:bg-red-500/30">
                      🗑 Tümünü Sil
                    </button>
                    <button onClick={() => setSelectedGroups(new Set())}
                      className="px-3 py-1 text-xs bg-slate-600 text-slate-300 border border-slate-500 rounded hover:bg-slate-500">
                      ✕ İptal
                    </button>
                  </div>
                </div>
              )}
              <thead>
                <tr className="border-b border-slate-700 text-left bg-slate-800/80">
                  <th className="px-3 py-3 w-8">
                    <input type="checkbox"
                      checked={selectedGroups.size === sortedGroups.length && sortedGroups.length > 0}
                      onChange={toggleSelectAllGroups}
                      className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500" />
                  </th>
                  <th className="px-3 py-3 text-xs font-medium text-slate-400 cursor-pointer select-none hover:text-white" onClick={() => handleSort('severity')}>
                    Önem <SortIcon col="severity" />
                  </th>
                  <th className="px-3 py-3 text-xs font-medium text-slate-400 cursor-pointer select-none hover:text-white" onClick={() => handleSort('title')}>
                    Başlık <SortIcon col="title" />
                  </th>
                  <th className="px-3 py-3 text-xs font-medium text-slate-400 cursor-pointer select-none hover:text-white" onClick={() => handleSort('server_name')}>
                    Sunucu <SortIcon col="server_name" />
                  </th>
                  <th className="px-3 py-3 text-xs font-medium text-slate-400 cursor-pointer select-none hover:text-white" onClick={() => handleSort('event_type')}>
                    Tip <SortIcon col="event_type" />
                  </th>
                  <th className="px-3 py-3 text-xs font-medium text-slate-400 cursor-pointer select-none hover:text-white" onClick={() => handleSort('count')}>
                    Adet <SortIcon col="count" />
                  </th>
                  <th className="px-3 py-3 text-xs font-medium text-slate-400 cursor-pointer select-none hover:text-white" onClick={() => handleSort('latest_created_at')}>
                    Son Oluşum <SortIcon col="latest_created_at" />
                  </th>
                  <th className="px-3 py-3 text-xs font-medium text-slate-400">İşlem</th>
                </tr>
              </thead>
              <tbody>
                {sortedGroups.map((grp, idx) => (
                  <tr key={idx} className={`border-b border-slate-700/50 hover:bg-slate-700/20 transition-colors ${selectedGroups.has(idx) ? 'bg-blue-600/10' : ''}`}>
                    <td className="px-3 py-3 w-8">
                      <input type="checkbox" checked={selectedGroups.has(idx)} onChange={() => toggleGroupSelect(idx)}
                        className="rounded border-slate-600 bg-slate-700 text-blue-500 focus:ring-blue-500" />
                    </td>
                    <td className="px-3 py-3">
                      <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${sColor(grp.severity)}`}>
                        {sIcon(grp.severity)} {grp.severity}
                      </span>
                    </td>
                    <td className="px-3 py-3 max-w-md">
                      <p className="text-white text-xs truncate" title={grp.title}>{grp.title}</p>
                    </td>
                    <td className="px-3 py-3 text-xs text-purple-400 font-mono">{grp.server_name || <span className="text-slate-600">-</span>}</td>
                    <td className="px-3 py-3">
                      <span className="text-[10px] text-slate-400 font-mono bg-slate-900/50 px-1.5 py-0.5 rounded">{grp.event_type}</span>
                    </td>
                    <td className="px-3 py-3">
                      <span className={`px-2 py-0.5 rounded text-xs font-bold ${grp.count > 1 ? 'bg-amber-500/20 text-amber-400' : 'bg-slate-700 text-slate-400'}`}>
                        {grp.count}×
                      </span>
                    </td>
                    <td className="px-3 py-3 text-[10px] text-slate-500 whitespace-nowrap">
                      {grp.latest_created_at
                        ? new Date(grp.latest_created_at).toLocaleString('tr-TR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' })
                        : '-'}
                    </td>
                    <td className="px-3 py-3">
                      <div className="flex flex-wrap gap-1.5">
                        <button onClick={() => setDetailGroupIds(grp.event_ids)}
                          className="px-2 py-1 text-[10px] bg-blue-500/20 text-blue-400 border border-blue-500/30 rounded hover:bg-blue-500/30 transition-colors whitespace-nowrap">
                          📋 Tümünü gör ({grp.count})
                        </button>
                        <button onClick={() => startAnalyze(grp)}
                          className="px-2 py-1 text-[10px] bg-purple-500/20 text-purple-300 border border-purple-500/30 rounded hover:bg-purple-500/30 transition-colors whitespace-nowrap">
                          🔍 Analiz Et
                        </button>
                        <button onClick={() => bulkAction.mutate({ action: 'acknowledge', ids: grp.event_ids })}
                          className="px-2 py-1 text-[10px] bg-yellow-500/10 text-yellow-400 border border-yellow-600/20 rounded hover:bg-yellow-500/20 transition-colors whitespace-nowrap">
                          👁 Onayla
                        </button>
                        <button onClick={() => bulkAction.mutate({ action: 'resolve', ids: grp.event_ids })}
                          className="px-2 py-1 text-[10px] bg-green-500/10 text-green-400 border border-green-600/20 rounded hover:bg-green-500/20 transition-colors whitespace-nowrap">
                          ✅ Çöz
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )
      ) : (
        events.length === 0 ? (
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
                        {event.server_name ? <span className="text-xs text-purple-400 font-mono">{event.server_name}</span>
                          : <span className="text-xs text-slate-600">-</span>}
                      </td>
                      <td className="px-3 py-3">
                        <span className="text-[10px] text-slate-400 font-mono bg-slate-900/50 px-1.5 py-0.5 rounded">{event.event_type}</span>
                      </td>
                      <td className="px-3 py-3 text-xs text-slate-500">{event.source || '-'}</td>
                      <td className="px-3 py-3">
                        {event.resolved ? <span className="text-green-400 text-[10px] font-medium">✅ Çözüldü</span>
                          : event.is_acknowledged ? <span className="text-yellow-400 text-[10px] font-medium">👁 Onaylandı</span>
                          : <span className="text-red-400 text-[10px] font-medium">⏳ Bekliyor</span>}
                      </td>
                      <td className="px-3 py-3 text-[10px] text-slate-500 whitespace-nowrap">
                        {event.created_at ? new Date(event.created_at).toLocaleString('tr-TR', { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }) : '-'}
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
                              className="px-2 py-1 text-[10px] bg-yellow-500/10 text-yellow-400 border border-yellow-500/30 rounded hover:bg-yellow-500/20">
                              👁
                            </button>
                          )}
                          {!event.resolved && (
                            <button onClick={() => resolveEvent.mutate(event.id)}
                              className="px-2 py-1 text-[10px] bg-green-500/10 text-green-400 border border-green-500/30 rounded hover:bg-green-500/20">
                              ✅
                            </button>
                          )}
                          <button onClick={() => { if (confirm('Bu event silinecek. Emin misiniz?')) deleteEvent.mutate(event.id) }}
                            className="px-2 py-1 text-[10px] bg-red-500/10 text-red-400 border border-red-500/30 rounded hover:bg-red-500/20">
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
        )
      )}

      {totalPages > 1 && (
        <div className="flex items-center justify-between">
          <span className="text-xs text-slate-400">
            {page * PAGE_SIZE + 1} – {Math.min((page + 1) * PAGE_SIZE, total)} / {total} {groupedView ? 'grup' : 'event'}
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
      {/* AI Analiz Modalı */}
      {analyzeGroup && (
        <div className="fixed inset-0 bg-black/60 backdrop-blur-sm flex items-center justify-center z-50 p-4">
          <div className="bg-slate-800 border border-slate-600 rounded-2xl w-full max-w-2xl max-h-[85vh] flex flex-col shadow-2xl">
            <div className="flex items-center gap-3 px-5 py-4 border-b border-slate-700">
              <span className="text-xl">🔍</span>
              <div className="flex-1 min-w-0">
                <h3 className="text-white font-semibold text-sm truncate">{analyzeGroup.title}</h3>
                <div className="flex gap-2 mt-1">
                  <span className={`px-2 py-0.5 rounded-full text-[10px] font-semibold border ${sColor(analyzeGroup.severity)}`}>
                    {sIcon(analyzeGroup.severity)} {analyzeGroup.severity}
                  </span>
                  {analyzeGroup.server_name && (
                    <span className="text-[10px] text-purple-400 font-mono">{analyzeGroup.server_name}</span>
                  )}
                  <span className="text-[10px] text-slate-400 font-mono bg-slate-900/50 px-1.5 py-0.5 rounded">{analyzeGroup.event_type}</span>
                </div>
              </div>
              <button onClick={() => { analyzeAbortRef.current?.abort(); setAnalyzeGroup(null); setAnalysisText('') }}
                className="text-slate-400 hover:text-white text-xl leading-none flex-shrink-0">&times;</button>
            </div>
            <div className="flex-1 overflow-y-auto p-5">
              {isAnalyzing && !analysisText && (
                <div className="flex items-center gap-2 text-slate-400 text-sm">
                  <div className="w-4 h-4 border-2 border-purple-400 border-t-transparent rounded-full animate-spin" />
                  <span>AI analiz yapıyor...</span>
                </div>
              )}
              {analysisText ? (
                <div className="prose prose-invert prose-sm max-w-none text-slate-200">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>{analysisText}</ReactMarkdown>
                  {isAnalyzing && (
                    <span className="inline-block w-2 h-4 bg-purple-400 animate-pulse ml-1 rounded-sm" />
                  )}
                </div>
              ) : !isAnalyzing ? (
                <p className="text-slate-500 text-sm">Analiz başlatılıyor...</p>
              ) : null}
            </div>
            <div className="px-5 py-3 border-t border-slate-700 flex justify-between items-center">
              <button onClick={() => startAnalyze(analyzeGroup)}
                disabled={isAnalyzing}
                className="px-3 py-1.5 text-xs bg-purple-600/30 text-purple-300 border border-purple-500/30 rounded hover:bg-purple-600/40 disabled:opacity-50">
                🔄 Yeniden Analiz Et
              </button>
              <div className="flex gap-2">
                <button onClick={() => { bulkAction.mutate({ action: 'acknowledge', ids: analyzeGroup.event_ids }); setAnalyzeGroup(null) }}
                  className="px-3 py-1.5 text-xs bg-yellow-500/20 text-yellow-300 border border-yellow-500/30 rounded hover:bg-yellow-500/30">
                  👁 Onayla
                </button>
                <button onClick={() => { bulkAction.mutate({ action: 'resolve', ids: analyzeGroup.event_ids }); setAnalyzeGroup(null) }}
                  className="px-3 py-1.5 text-xs bg-green-500/20 text-green-300 border border-green-500/30 rounded hover:bg-green-500/30">
                  ✅ Çözüldü İşaretle
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

    </div>
  )
}

export default Events
