import React, { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  NEON, rgb, PageHeader, PrimaryButton, GhostButton, Kpi, SeverityBadge,
  SearchInput, Select, ActionMenu, Section, EmptyState, Modal, Pagination, MenuItem,
} from '../components/aiops/ui'

interface SystemEvent {
  id: number; server_id: number | null; server_name: string | null
  event_type: string; severity: string; source: string | null
  title: string; description: string | null; raw_data: any
  is_acknowledged: boolean; is_known: boolean; resolved: boolean; created_at: string | null
}
interface EventStats {
  total: number; unresolved: number; critical: number; warning: number
  emergency: number; acknowledged: number; known: number
}
interface EventGroup {
  event_type: string; title: string; severity: string
  server_id: number | null; server_name: string | null
  event_ids: number[]; count: number; latest_created_at: string | null
  resolved?: boolean; is_acknowledged?: boolean; is_known?: boolean
}

const PAGE_SIZE = 50

function fmtDate(d: string | null, short = true) {
  if (!d) return '-'
  return new Date(d).toLocaleString('tr-TR', short
    ? { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }
    : undefined)
}

function StatusPill({ e }: { e: { resolved: boolean; is_known: boolean; is_acknowledged: boolean } }) {
  if (e.resolved) return <span className="text-[11px] font-medium" style={{ color: NEON.green }}>Çözüldü</span>
  if (e.is_known) return <span className="text-[11px] font-medium" style={{ color: NEON.cyan }}>Bilinen</span>
  if (e.is_acknowledged) return <span className="text-[11px] font-medium" style={{ color: NEON.orange }}>İncelemede</span>
  return <span className="text-[11px] font-medium" style={{ color: NEON.red }}>Yeni</span>
}

const Events: React.FC = () => {
  const [severityFilter, setSeverityFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [resolvedFilter, setResolvedFilter] = useState<string>('false')
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [expandedRaw, setExpandedRaw] = useState<number | null>(null)
  const [newEvent, setNewEvent] = useState({ title: '', event_type: 'custom', severity: 'info', description: '' })
  const [groupedView, setGroupedView] = useState(true)
  const [sortBy, setSortBy] = useState<keyof EventGroup>('latest_created_at')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [detailGroupIds, setDetailGroupIds] = useState<number[] | null>(null)
  const [scanning, setScanning] = useState(false)
  const [selectedGroups, setSelectedGroups] = useState<Set<number>>(new Set())
  const [analyzeGroup, setAnalyzeGroup] = useState<EventGroup | null>(null)
  const [analysisText, setAnalysisText] = useState('')
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [incidentModal, setIncidentModal] = useState<{ event_ids: number[]; group_title?: string } | null>(null)
  const [incidentForm, setIncidentForm] = useState({ title: '', description: '', severity: 'medium', assigned_to: '' })
  const analyzeModel = localStorage.getItem('chat_selected_model') || 'gpt-oss:20b'
  const analyzeAbortRef = useRef<AbortController | null>(null)
  const [scanResult, setScanResult] = useState<{ total_servers: number; servers_with_logs: number; total_saved: number; details: any[] } | null>(null)
  const queryClient = useQueryClient()

  const createIncident = useMutation({
    mutationFn: async (payload: { title: string; description: string; severity: string; assigned_to: string; related_events: number[] }) => {
      const res = await fetch(`${API_BASE_URL}/incidents/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...payload, source: 'manual' })
      })
      if (!res.ok) throw new Error('Incident oluşturulamadı')
      return res.json()
    },
    onSuccess: () => { setIncidentModal(null); invalidate() },
  })

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
      params.set('limit', String(PAGE_SIZE)); params.set('offset', String(page * PAGE_SIZE))
      const res = await fetch(`${API_BASE_URL}/events/?${params}`)
      if (!res.ok) return { total: 0, events: [] }
      return res.json()
    },
    enabled: !groupedView, refetchInterval: 20000
  })

  const { data: groupedData, isLoading: groupedLoading } = useQuery<{ total: number; groups: EventGroup[] }>({
    queryKey: ['events', 'grouped', severityFilter, typeFilter, resolvedFilter, search, page, sortBy, sortDir],
    queryFn: async () => {
      const params = paramsBase()
      params.set('limit', String(PAGE_SIZE)); params.set('offset', String(page * PAGE_SIZE))
      params.set('sort_by', sortBy as string); params.set('sort_dir', sortDir)
      const res = await fetch(`${API_BASE_URL}/events/grouped?${params}`)
      if (!res.ok) return { total: 0, groups: [] }
      return res.json()
    },
    enabled: groupedView, refetchInterval: 20000
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
      if (!res.ok) return { total: 0, unresolved: 0, critical: 0, warning: 0, emergency: 0, acknowledged: 0, known: 0 }
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

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['events'] })
    queryClient.invalidateQueries({ queryKey: ['eventStats'] })
  }

  const handleScan = async () => {
    setScanning(true); setScanResult(null)
    try {
      const res = await fetch(`${API_BASE_URL}/events/scan?only_ai_ready=false`, { method: 'POST' })
      setScanResult(await res.json()); invalidate()
    } catch { setScanResult(null) } finally { setScanning(false) }
  }

  const createEvent = useMutation({
    mutationFn: async (data: typeof newEvent) => {
      const res = await fetch(`${API_BASE_URL}/events/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
      })
      if (!res.ok) throw new Error('Oluşturulamadı')
      return res.json()
    },
    onSuccess: () => { invalidate(); setShowCreateForm(false); setNewEvent({ title: '', event_type: 'custom', severity: 'info', description: '' }) }
  })

  const ackEvent = useMutation({ mutationFn: async (id: number) => { await fetch(`${API_BASE_URL}/events/${id}/acknowledge`, { method: 'POST' }) }, onSuccess: invalidate })
  const knownEvent = useMutation({ mutationFn: async (id: number) => { await fetch(`${API_BASE_URL}/events/${id}/known`, { method: 'POST' }) }, onSuccess: invalidate })
  const resolveEvent = useMutation({ mutationFn: async (id: number) => { await fetch(`${API_BASE_URL}/events/${id}/resolve`, { method: 'POST' }) }, onSuccess: invalidate })
  const unresolveEvent = useMutation({ mutationFn: async (id: number) => { await fetch(`${API_BASE_URL}/events/${id}/unresolve`, { method: 'POST' }) }, onSuccess: invalidate })
  const deleteEvent = useMutation({ mutationFn: async (id: number) => { const r = await fetch(`${API_BASE_URL}/events/${id}`, { method: 'DELETE' }); if (!r.ok) throw new Error() }, onSuccess: invalidate })

  const bulkAction = useMutation({
    mutationFn: async ({ action, ids }: { action: string; ids: number[] }) => {
      const res = await fetch(`${API_BASE_URL}/events/bulk-action`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event_ids: ids, action })
      })
      if (!res.ok) throw new Error()
      return res.json()
    },
    onSuccess: () => { invalidate(); setSelectedIds(new Set()) }
  })

  const bulkDelete = useMutation({
    mutationFn: async (ids: number[]) => {
      const res = await fetch(`${API_BASE_URL}/events/bulk-delete`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event_ids: ids, action: 'delete' })
      })
      if (!res.ok) throw new Error()
    },
    onSuccess: () => { invalidate(); setSelectedIds(new Set()) }
  })

  const events = eventsData?.events || []
  const groups = groupedData?.groups || []
  const total = groupedView ? (groupedData?.total ?? 0) : (eventsData?.total ?? 0)
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))
  const isLoadingList = groupedView ? groupedLoading : isLoading

  const handleSort = (col: keyof EventGroup) => {
    setPage(0)
    if (sortBy === col) setSortDir(d => d === 'asc' ? 'desc' : 'asc')
    else { setSortBy(col); setSortDir('desc') }
  }
  const SortIcon = ({ col }: { col: keyof EventGroup }) =>
    sortBy !== col ? <span className="text-slate-600 ml-1">⇅</span>
      : <span style={{ color: NEON.cyan }} className="ml-1">{sortDir === 'asc' ? '↑' : '↓'}</span>

  const toggleSelect = (id: number) => setSelectedIds(prev => { const n = new Set(prev); n.has(id) ? n.delete(id) : n.add(id); return n })
  const toggleSelectAll = () => setSelectedIds(selectedIds.size === events.length ? new Set() : new Set(events.map(e => e.id)))
  const toggleGroupSelect = (idx: number) => setSelectedGroups(prev => { const n = new Set(prev); n.has(idx) ? n.delete(idx) : n.add(idx); return n })
  const toggleSelectAllGroups = () => setSelectedGroups(selectedGroups.size === groups.length ? new Set() : new Set(groups.map((_, i) => i)))
  const selectedGroupEventIds = (): number[] => [...selectedGroups].flatMap(i => groups[i]?.event_ids ?? [])

  const groupBulkAction = async (action: string) => {
    const ids = selectedGroupEventIds()
    if (!ids.length) return
    const url = action === 'delete' ? '/events/bulk-delete' : '/events/bulk-action'
    await fetch(`${API_BASE_URL}${url}`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ event_ids: ids, action })
    })
    invalidate(); setSelectedGroups(new Set())
  }

  const startAnalyze = async (grp: EventGroup) => {
    analyzeAbortRef.current?.abort()
    setAnalyzeGroup(grp); setAnalysisText(''); setIsAnalyzing(true)
    const prompt = `Aşağıdaki sistem eventi/grubu hakkında detaylı analiz yap ve çözüm önerisi sun:\n\n` +
      `Başlık: ${grp.title}\nÖnem: ${grp.severity}\nTip: ${grp.event_type}\n` +
      (grp.server_name ? `Sunucu: ${grp.server_name}\n` : '') + `Adet: ${grp.count}×\n\n` +
      `Lütfen şunları içeren bir analiz yap:\n1. Bu hatanın/uyarının ne anlama geldiği\n2. Olası nedenleri\n3. Adım adım çözüm önerileri\n4. Tekrar önleme yöntemleri`
    const ctrl = new AbortController(); analyzeAbortRef.current = ctrl
    try {
      const res = await fetch(`${API_BASE_URL}/chat/stream`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ message: prompt, use_rag: true, model: analyzeModel, skip_server_context: true }), signal: ctrl.signal
      })
      if (!res.ok || !res.body) throw new Error('HTTP ' + res.status)
      const reader = res.body.getReader(); const decoder = new TextDecoder()
      let buf = '', acc = ''
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        buf += decoder.decode(value, { stream: true })
        const lines = buf.split('\n'); buf = lines.pop() ?? ''
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
      if (e?.name !== 'AbortError') setAnalysisText('Analiz başarısız.')
    } finally { setIsAnalyzing(false) }
  }

  const openIncidentForGroup = (grp: EventGroup) => {
    setIncidentForm({ title: grp.title, description: `${grp.count} event içeren grup`, severity: grp.severity === 'emergency' ? 'critical' : grp.severity, assigned_to: '' })
    setIncidentModal({ event_ids: grp.event_ids, group_title: grp.title })
  }

  // group row action menu
  const groupMenu = (grp: EventGroup): MenuItem[] => [
    { label: 'Tümünü gör', icon: '', onClick: () => setDetailGroupIds(grp.event_ids) },
    { label: 'İncelemeye al', icon: '👁', onClick: () => bulkAction.mutate({ action: 'acknowledge', ids: grp.event_ids }) },
    { label: 'Bilinen olay', icon: '', onClick: () => bulkAction.mutate({ action: 'known', ids: grp.event_ids }) },
    { label: 'Kapat (çöz)', icon: '', accent: NEON.green, onClick: () => bulkAction.mutate({ action: 'resolve', ids: grp.event_ids }) },
    { label: 'Yeniden aç', icon: '↩', hidden: !grp.resolved, onClick: () => bulkAction.mutate({ action: 'unresolve', ids: grp.event_ids }) },
    { label: 'Incident oluştur', icon: '', accent: NEON.blue, onClick: () => openIncidentForGroup(grp) },
  ]
  const flatMenu = (e: SystemEvent): MenuItem[] => [
    { label: 'Raw data', icon: '', hidden: !(e.raw_data && Object.keys(e.raw_data).length), onClick: () => setExpandedRaw(expandedRaw === e.id ? null : e.id) },
    { label: 'İncelemeye al', icon: '👁', hidden: e.is_acknowledged || e.resolved, onClick: () => ackEvent.mutate(e.id) },
    { label: 'Bilinen olay', icon: '', hidden: e.is_known || e.resolved, onClick: () => knownEvent.mutate(e.id) },
    { label: 'Kapat (çöz)', icon: '', accent: NEON.green, hidden: e.resolved, onClick: () => resolveEvent.mutate(e.id) },
    { label: 'Yeniden aç', icon: '↩', hidden: !e.resolved, onClick: () => unresolveEvent.mutate(e.id) },
    { label: 'Sil', icon: '✕', accent: NEON.red, onClick: () => { if (confirm('Bu event silinecek. Emin misiniz?')) deleteEvent.mutate(e.id) } },
  ]

  const inputCls = 'w-full rounded-lg px-3 py-2 text-white text-sm focus:outline-none'
  const inputStyle = { background: 'var(--bg-deep)', border: '1px solid rgba(99,130,194,0.2)' } as React.CSSProperties

  return (
    <div className="space-y-4 animate-fade-in">
      <PageHeader
        title="Events"
        subtitle="Sistem olaylarını izleyin, gruplayın ve yönetin"
        actions={<>
          <GhostButton accent={NEON.green} onClick={handleScan} disabled={scanning}>
            {scanning ? 'Taranıyor...' : 'Şimdi Tara'}
          </GhostButton>
          <PrimaryButton accent={NEON.blue} onClick={() => setShowCreateForm(v => !v)}>
            {showCreateForm ? 'İptal' : '+ Yeni Event'}
          </PrimaryButton>
        </>}
      />

      {/* KPI row — tıklayınca filtreler */}
      <div className="grid grid-cols-3 md:grid-cols-6 gap-3">
        <Kpi label="Toplam" value={stats?.total ?? 0} accent={NEON.cyan}
          active={!severityFilter && resolvedFilter === ''} onClick={() => { setSeverityFilter(''); setResolvedFilter(''); setPage(0) }} />
        <Kpi label="Çözülmemiş" value={stats?.unresolved ?? 0} accent={NEON.orange}
          active={resolvedFilter === 'false' && !severityFilter} onClick={() => { setSeverityFilter(''); setResolvedFilter('false'); setPage(0) }} />
        <Kpi label="Kritik" value={stats?.critical ?? 0} accent={NEON.red}
          active={severityFilter === 'critical'} onClick={() => { setSeverityFilter('critical'); setResolvedFilter('false'); setPage(0) }} />
        <Kpi label="Acil" value={stats?.emergency ?? 0} accent={NEON.pink}
          active={severityFilter === 'emergency'} onClick={() => { setSeverityFilter('emergency'); setResolvedFilter('false'); setPage(0) }} />
        <Kpi label="Uyarı" value={stats?.warning ?? 0} accent={NEON.orange}
          active={severityFilter === 'warning'} onClick={() => { setSeverityFilter('warning'); setResolvedFilter('false'); setPage(0) }} />
        <Kpi label="Bilinen" value={stats?.known ?? 0} accent={NEON.blue} />
      </div>

      {scanResult && (
        <div className="px-4 py-3 rounded-xl text-sm flex items-start justify-between gap-4 cyber-card"
          style={{ borderColor: scanResult.total_saved > 0 ? `rgba(${rgb(NEON.green)},0.3)` : undefined }}>
          <div>
            <p className="font-medium text-white mb-1">
              {scanResult.total_saved > 0 ? `Tarama tamamlandı — ${scanResult.total_saved} yeni event` : 'Tarama tamamlandı — yeni event yok'}
            </p>
            <p className="text-xs" style={{ color: 'rgba(148,163,184,0.6)' }}>
              {scanResult.total_servers} sunucu tarandı · {scanResult.servers_with_logs} sunucuda log
            </p>
          </div>
          <button onClick={() => setScanResult(null)} className="text-slate-500 hover:text-white text-lg leading-none">&times;</button>
        </div>
      )}

      {showCreateForm && (
        <Section title="Yeni Event Oluştur" accent={NEON.blue}>
          <form onSubmit={e => { e.preventDefault(); createEvent.mutate(newEvent) }} className="p-5 space-y-4">
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              <div>
                <label className="block text-xs mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>Başlık *</label>
                <input type="text" required value={newEvent.title} onChange={e => setNewEvent({ ...newEvent, title: e.target.value })} className={inputCls} style={inputStyle} />
              </div>
              <div>
                <label className="block text-xs mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>Tip</label>
                <select value={newEvent.event_type} onChange={e => setNewEvent({ ...newEvent, event_type: e.target.value })} className={inputCls} style={inputStyle}>
                  <option value="custom">Custom</option><option value="cpu_high">CPU High</option><option value="memory_high">Memory High</option>
                  <option value="disk_full">Disk Full</option><option value="service_down">Service Down</option><option value="network_issue">Network Issue</option>
                </select>
              </div>
              <div>
                <label className="block text-xs mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>Önem</label>
                <select value={newEvent.severity} onChange={e => setNewEvent({ ...newEvent, severity: e.target.value })} className={inputCls} style={inputStyle}>
                  <option value="info">Info</option><option value="warning">Warning</option><option value="error">Error</option>
                  <option value="critical">Critical</option><option value="emergency">Emergency</option>
                </select>
              </div>
            </div>
            <div>
              <label className="block text-xs mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>Açıklama</label>
              <textarea value={newEvent.description} onChange={e => setNewEvent({ ...newEvent, description: e.target.value })} className={inputCls} style={inputStyle} rows={2} />
            </div>
            <PrimaryButton accent={NEON.green} disabled={createEvent.isPending}>{createEvent.isPending ? 'Oluşturuluyor...' : 'Oluştur'}</PrimaryButton>
          </form>
        </Section>
      )}

      {/* Toolbar */}
      <div className="flex flex-wrap items-center gap-2">
        <SearchInput value={search} onChange={v => { setSearch(v); setPage(0) }} placeholder="Başlıkta ara..." />
        <Select value={severityFilter} onChange={v => { setSeverityFilter(v); setPage(0) }}>
          <option value="">Tüm Seviyeler</option><option value="info">Info</option><option value="warning">Warning</option>
          <option value="error">Error</option><option value="critical">Critical</option><option value="emergency">Emergency</option>
        </Select>
        <Select value={typeFilter} onChange={v => { setTypeFilter(v); setPage(0) }}>
          <option value="">Tüm Tipler</option>
          {(eventTypes || []).map(t => <option key={t} value={t}>{t}</option>)}
        </Select>
        <Select value={resolvedFilter} onChange={v => { setResolvedFilter(v); setPage(0) }}>
          <option value="">Tüm Durumlar</option><option value="false">Aktif</option><option value="true">Çözülmüş</option>
        </Select>
        <label className="flex items-center gap-2 cursor-pointer select-none ml-1">
          <div onClick={() => { setGroupedView(v => !v); setPage(0) }}
            className="relative w-9 h-5 rounded-full transition-colors cursor-pointer"
            style={{ background: groupedView ? NEON.cyan : 'rgba(100,116,139,0.5)' }}>
            <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${groupedView ? 'translate-x-4' : ''}`} />
          </div>
          <span className="text-xs" style={{ color: 'rgba(148,163,184,0.7)' }}>Benzerleri grupla</span>
        </label>
        <span className="ml-auto text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>{total} {groupedView ? 'grup' : 'sonuç'}</span>
      </div>

      {/* Flat bulk toolbar */}
      {!groupedView && selectedIds.size > 0 && (
        <div className="flex items-center gap-2 flex-wrap cyber-card px-4 py-2.5" style={{ borderColor: `rgba(${rgb(NEON.cyan)},0.3)` }}>
          <span className="text-sm font-medium" style={{ color: NEON.cyan }}>{selectedIds.size} event seçili</span>
          <GhostButton accent={NEON.orange} onClick={() => bulkAction.mutate({ action: 'acknowledge', ids: [...selectedIds] })}>İncelemeye al</GhostButton>
          <GhostButton accent={NEON.cyan} onClick={() => bulkAction.mutate({ action: 'known', ids: [...selectedIds] })}>Bilinen</GhostButton>
          <GhostButton accent={NEON.green} onClick={() => bulkAction.mutate({ action: 'resolve', ids: [...selectedIds] })}>Kapat</GhostButton>
          <GhostButton accent={NEON.blue} onClick={() => {
            const f = events.find(e => selectedIds.has(e.id))
            setIncidentForm({ title: f ? f.title : 'Yeni Incident', description: '', severity: 'medium', assigned_to: '' })
            setIncidentModal({ event_ids: [...selectedIds] })
          }}>Incident</GhostButton>
          <GhostButton accent={NEON.red} onClick={() => { if (confirm(`${selectedIds.size} event silinecek?`)) bulkDelete.mutate([...selectedIds]) }}>Sil</GhostButton>
          <button onClick={() => setSelectedIds(new Set())} className="ml-auto text-xs" style={{ color: 'rgba(148,163,184,0.6)' }}>Seçimi kaldır</button>
        </div>
      )}

      {/* Group bulk toolbar */}
      {groupedView && selectedGroups.size > 0 && (
        <div className="flex items-center gap-2 flex-wrap cyber-card px-4 py-2.5" style={{ borderColor: `rgba(${rgb(NEON.cyan)},0.3)` }}>
          <span className="text-sm font-medium" style={{ color: NEON.cyan }}>{selectedGroups.size} grup ({selectedGroupEventIds().length} event)</span>
          <GhostButton accent={NEON.orange} onClick={() => groupBulkAction('acknowledge')}>İncelemeye al</GhostButton>
          <GhostButton accent={NEON.cyan} onClick={() => groupBulkAction('known')}>Bilinen</GhostButton>
          <GhostButton accent={NEON.green} onClick={() => groupBulkAction('resolve')}>Kapat</GhostButton>
          <GhostButton accent={NEON.blue} onClick={() => {
            const ids = selectedGroupEventIds()
            const title = [...selectedGroups].map(i => groups[i]?.title).filter(Boolean).join(', ')
            setIncidentForm({ title: title || 'Çoklu Grup Incident', description: '', severity: 'medium', assigned_to: '' })
            setIncidentModal({ event_ids: ids })
          }}>Incident</GhostButton>
          <GhostButton accent={NEON.red} onClick={() => groupBulkAction('delete')}>Sil</GhostButton>
          <button onClick={() => setSelectedGroups(new Set())} className="ml-auto text-xs" style={{ color: 'rgba(148,163,184,0.6)' }}>İptal</button>
        </div>
      )}

      {/* List */}
      {isLoadingList ? (
        <div className="py-16 flex justify-center"><div className="animate-spin rounded-full h-8 w-8 border-2 border-t-cyan-400 border-white/[0.06]" /></div>
      ) : groupedView ? (
        groups.length === 0 ? <Section><EmptyState icon="" text="Henüz event yok" /></Section> : (
          <Section className="overflow-visible">
            <div className="overflow-x-auto overflow-y-visible">
              <table className="cyber-table w-full text-sm">
                <thead>
                  <tr>
                    <th className="w-8"><input type="checkbox" checked={selectedGroups.size === groups.length && groups.length > 0} onChange={toggleSelectAllGroups} /></th>
                    <th className="text-left cursor-pointer" onClick={() => handleSort('severity')}>Önem<SortIcon col="severity" /></th>
                    <th className="text-left cursor-pointer" onClick={() => handleSort('title')}>Başlık<SortIcon col="title" /></th>
                    <th className="text-left cursor-pointer" onClick={() => handleSort('server_name')}>Sunucu<SortIcon col="server_name" /></th>
                    <th className="text-left cursor-pointer" onClick={() => handleSort('count')}>Adet<SortIcon col="count" /></th>
                    <th className="text-left cursor-pointer" onClick={() => handleSort('latest_created_at')}>Son Oluşum<SortIcon col="latest_created_at" /></th>
                    <th className="text-right">İşlem</th>
                  </tr>
                </thead>
                <tbody>
                  {groups.map((grp, idx) => (
                    <tr key={idx} style={selectedGroups.has(idx) ? { background: `rgba(${rgb(NEON.cyan)},0.06)` } : undefined}>
                      <td><input type="checkbox" checked={selectedGroups.has(idx)} onChange={() => toggleGroupSelect(idx)} /></td>
                      <td><SeverityBadge severity={grp.severity} /></td>
                      <td className="max-w-md"><p className="text-white truncate" title={grp.title}>{grp.title}</p></td>
                      <td><span className="font-mono text-xs" style={{ color: grp.server_name ? NEON.blue : 'rgba(148,163,184,0.4)' }}>{grp.server_name || '-'}</span></td>
                      <td>
                        <span className="px-2 py-0.5 rounded text-xs font-bold"
                          style={grp.count > 1 ? { background: `rgba(${rgb(NEON.orange)},0.15)`, color: NEON.orange } : { background: 'rgba(255,255,255,0.05)', color: 'rgba(148,163,184,0.6)' }}>
                          {grp.count}×
                        </span>
                      </td>
                      <td className="text-xs whitespace-nowrap" style={{ color: 'rgba(148,163,184,0.6)' }}>{fmtDate(grp.latest_created_at)}</td>
                      <td>
                        <div className="flex items-center justify-end gap-1.5">
                          <button onClick={() => startAnalyze(grp)}
                            className="px-2.5 py-1.5 rounded-lg text-xs font-medium transition-all"
                            style={{ background: `rgba(${rgb(NEON.blue)},0.12)`, color: NEON.blue, border: `1px solid rgba(${rgb(NEON.blue)},0.3)` }}>
                            Analiz
                          </button>
                          <ActionMenu items={groupMenu(grp)} />
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Section>
        )
      ) : (
        events.length === 0 ? <Section><EmptyState icon="" text="Henüz event yok" /></Section> : (
          <Section className="overflow-visible">
            <div className="overflow-x-auto overflow-y-visible">
              <table className="cyber-table w-full text-sm">
                <thead>
                  <tr>
                    <th className="w-8"><input type="checkbox" checked={selectedIds.size === events.length && events.length > 0} onChange={toggleSelectAll} /></th>
                    <th className="text-left">Önem</th><th className="text-left">Başlık</th><th className="text-left">Sunucu</th>
                    <th className="text-left">Tip</th><th className="text-left">Durum</th><th className="text-left">Tarih</th><th className="text-right">İşlem</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map(event => (
                    <React.Fragment key={event.id}>
                      <tr style={selectedIds.has(event.id) ? { background: `rgba(${rgb(NEON.cyan)},0.06)` } : undefined}>
                        <td><input type="checkbox" checked={selectedIds.has(event.id)} onChange={() => toggleSelect(event.id)} /></td>
                        <td><SeverityBadge severity={event.severity} /></td>
                        <td className="max-w-xs">
                          <p className="text-white truncate" title={event.title}>{event.title}</p>
                          {event.description && event.description !== event.title && (
                            <p className="text-xs truncate mt-0.5" style={{ color: 'rgba(148,163,184,0.5)' }} title={event.description}>{event.description}</p>
                          )}
                        </td>
                        <td><span className="font-mono text-xs" style={{ color: event.server_name ? NEON.blue : 'rgba(148,163,184,0.4)' }}>{event.server_name || '-'}</span></td>
                        <td><span className="font-mono text-[11px] px-1.5 py-0.5 rounded" style={{ background: 'rgba(255,255,255,0.04)', color: 'rgba(148,163,184,0.7)' }}>{event.event_type}</span></td>
                        <td><StatusPill e={event} /></td>
                        <td className="text-xs whitespace-nowrap" style={{ color: 'rgba(148,163,184,0.6)' }}>{fmtDate(event.created_at)}</td>
                        <td><div className="flex justify-end"><ActionMenu items={flatMenu(event)} /></div></td>
                      </tr>
                      {expandedRaw === event.id && (
                        <tr>
                          <td colSpan={8} className="px-5 py-3" style={{ background: 'var(--bg-deep)' }}>
                            <p className="text-xs mb-1 font-medium" style={{ color: 'rgba(148,163,184,0.7)' }}>Raw Data:</p>
                            <pre className="text-[11px] font-mono rounded p-3 overflow-auto max-h-40" style={{ background: '#05080f', color: NEON.green }}>
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
          </Section>
        )
      )}

      <Pagination page={page} totalPages={totalPages} total={total} pageSize={PAGE_SIZE} unit={groupedView ? 'grup' : 'event'} onPage={setPage} />

      {/* Occurrences modal */}
      {detailGroupIds && (
        <Modal title={`Tüm oluşumlar (${occurrenceData?.events?.length ?? '...'})`} onClose={() => setDetailGroupIds(null)}>
          <div className="p-4 space-y-2">
            {(occurrenceData?.events ?? []).length === 0 ? (
              <div className="text-center py-8" style={{ color: 'rgba(148,163,184,0.5)' }}>Yükleniyor...</div>
            ) : (occurrenceData?.events ?? []).map(ev => (
              <div key={ev.id} className="rounded-lg p-3" style={{ background: 'var(--bg-deep)', border: '1px solid rgba(99,130,194,0.12)' }}>
                <div className="flex items-center gap-2 flex-wrap">
                  <SeverityBadge severity={ev.severity} />
                  {ev.server_name && <span className="text-[11px] font-mono" style={{ color: NEON.blue }}>{ev.server_name}</span>}
                  <span className="text-[11px] font-mono px-1.5 py-0.5 rounded" style={{ background: 'rgba(255,255,255,0.04)', color: 'rgba(148,163,184,0.7)' }}>{ev.event_type}</span>
                  <StatusPill e={ev} />
                  <span className="ml-auto text-[11px]" style={{ color: 'rgba(148,163,184,0.5)' }}>{fmtDate(ev.created_at, false)}</span>
                </div>
                <p className="text-white text-xs mt-2 break-words">{ev.title}</p>
                {ev.description && ev.description !== ev.title && <p className="text-[11px] mt-1" style={{ color: 'rgba(148,163,184,0.6)' }}>{ev.description}</p>}
              </div>
            ))}
          </div>
        </Modal>
      )}

      {/* AI Analyze modal */}
      {analyzeGroup && (
        <Modal
          title={<span className="flex items-center gap-2">{analyzeGroup.title}</span>}
          subtitle={`${analyzeGroup.event_type}${analyzeGroup.server_name ? ' · ' + analyzeGroup.server_name : ''} · ${analyzeGroup.count}×`}
          onClose={() => { analyzeAbortRef.current?.abort(); setAnalyzeGroup(null); setAnalysisText('') }}
          footer={
            <div className="flex justify-between items-center gap-2">
              <GhostButton accent={NEON.blue} onClick={() => startAnalyze(analyzeGroup)} disabled={isAnalyzing}>Yeniden</GhostButton>
              <div className="flex gap-2">
                <GhostButton accent={NEON.green} onClick={() => { bulkAction.mutate({ action: 'resolve', ids: analyzeGroup.event_ids }); setAnalyzeGroup(null) }}>Kapat</GhostButton>
                <GhostButton accent={NEON.blue} onClick={() => {
                  setIncidentForm({ title: analyzeGroup.title, description: analysisText.slice(0, 300) || `${analyzeGroup.count} event`, severity: analyzeGroup.severity === 'emergency' ? 'critical' : analyzeGroup.severity, assigned_to: '' })
                  setIncidentModal({ event_ids: analyzeGroup.event_ids, group_title: analyzeGroup.title })
                }}>Incident</GhostButton>
              </div>
            </div>
          }>
          <div className="p-5">
            {isAnalyzing && !analysisText && (
              <div className="flex items-center gap-2 text-sm" style={{ color: 'rgba(148,163,184,0.7)' }}>
                <div className="w-4 h-4 border-2 border-t-transparent rounded-full animate-spin" style={{ borderColor: `${NEON.blue} transparent ${NEON.blue} ${NEON.blue}` }} />
                AI analiz yapıyor...
              </div>
            )}
            {analysisText && (
              <div className="prose prose-invert prose-sm max-w-none" style={{ color: 'rgba(226,232,240,0.9)' }}>
                <ReactMarkdown remarkPlugins={[remarkGfm]}>{analysisText}</ReactMarkdown>
                {isAnalyzing && <span className="inline-block w-2 h-4 animate-pulse ml-1 rounded-sm" style={{ background: NEON.blue }} />}
              </div>
            )}
          </div>
        </Modal>
      )}

      {/* Incident create modal */}
      {incidentModal && (
        <Modal title="Incident Oluştur" subtitle={`${incidentModal.event_ids.length} event bağlanacak`} onClose={() => setIncidentModal(null)} maxWidth="max-w-lg"
          footer={
            <div className="flex gap-2 justify-end">
              <GhostButton onClick={() => setIncidentModal(null)}>İptal</GhostButton>
              <PrimaryButton accent={NEON.blue} disabled={!incidentForm.title.trim() || createIncident.isPending}
                onClick={() => createIncident.mutate({ title: incidentForm.title, description: incidentForm.description, severity: incidentForm.severity, assigned_to: incidentForm.assigned_to, related_events: incidentModal.event_ids })}>
                {createIncident.isPending ? 'Oluşturuluyor...' : 'Oluştur'}
              </PrimaryButton>
            </div>
          }>
          <div className="p-5 space-y-4">
            <div>
              <label className="block text-xs mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>Başlık *</label>
              <input value={incidentForm.title} onChange={e => setIncidentForm(f => ({ ...f, title: e.target.value }))} className={inputCls} style={inputStyle} />
            </div>
            <div>
              <label className="block text-xs mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>Açıklama</label>
              <textarea value={incidentForm.description} onChange={e => setIncidentForm(f => ({ ...f, description: e.target.value }))} rows={3} className={inputCls} style={inputStyle} />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>Önem</label>
                <select value={incidentForm.severity} onChange={e => setIncidentForm(f => ({ ...f, severity: e.target.value }))} className={inputCls} style={inputStyle}>
                  <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option>
                </select>
              </div>
              <div>
                <label className="block text-xs mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>Atanan</label>
                <input value={incidentForm.assigned_to} onChange={e => setIncidentForm(f => ({ ...f, assigned_to: e.target.value }))} placeholder="İsim..." className={inputCls} style={inputStyle} />
              </div>
            </div>
          </div>
        </Modal>
      )}
    </div>
  )
}

export default Events
