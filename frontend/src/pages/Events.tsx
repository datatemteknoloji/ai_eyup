import React, { useState, useRef } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  NEON, rgb, PageHeader, PrimaryButton, GhostButton, Kpi, SeverityBadge,
  SearchInput, Select, ActionMenu, Section, EmptyState, Modal, Pagination, MenuItem,
} from '../components/aiops/ui'
import { Eye, BarChart3 } from 'lucide-react'
import type { PlatformAiopsProps } from '../utils/platformApi'
import { appendPlatform } from '../utils/platformApi'

interface SystemEvent {
  id: number; server_id: number | null; server_name: string | null
  event_type: string; severity: string; source: string | null
  title: string; description: string | null; raw_data: any
  has_raw_data?: boolean
  is_acknowledged: boolean; is_known: boolean; resolved: boolean; created_at: string | null
}
interface EventStats {
  total: number; unresolved: number; critical: number; warning: number
  emergency: number; acknowledged: number; known: number
  actionable_total?: number; critical_only?: number
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

const Events: React.FC<PlatformAiopsProps & { hideHeader?: boolean }> = ({ platform = 'linux', hideHeader = false }) => {
  const [severityFilter, setSeverityFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')
  const [resolvedFilter, setResolvedFilter] = useState<string>('false')
  const [ackFilter, setAckFilter] = useState<string>('false') // actionable: onaylı olmayan
  const [knownFilter, setKnownFilter] = useState<string>('false') // actionable: bilinen olmayan
  const [search, setSearch] = useState('')
  const [page, setPage] = useState(0)
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set())
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [expandedRaw, setExpandedRaw] = useState<number | null>(null)
  const [rawCache, setRawCache] = useState<Record<number, any>>({})
  const [newEvent, setNewEvent] = useState({ title: '', event_type: 'custom', severity: 'info', description: '' })
  const [groupedView, setGroupedView] = useState(true)
  const [excludeKnown, setExcludeKnown] = useState(true)
  const [showRoutine, setShowRoutine] = useState(false)
  const [sortBy, setSortBy] = useState<keyof EventGroup>('latest_created_at')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')
  const [detailGroupIds, setDetailGroupIds] = useState<number[] | null>(null)
  const [scanning, setScanning] = useState(false)
  const [selectedGroups, setSelectedGroups] = useState<Set<number>>(new Set())
  const [analyzeGroup, setAnalyzeGroup] = useState<EventGroup | null>(null)
  const [analysisText, setAnalysisText] = useState('')
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [analyzeTab, setAnalyzeTab] = useState<'chat' | 'log'>('chat')
  const [logAnalysis, setLogAnalysis] = useState<{
    root_cause: string; impact: string; recommendations: string[];
    confidence: string; log_lines_used: number; model: string;
    requires_approval: boolean; analyzed_at: string;
  } | null>(null)
  const [isLogAnalyzing, setIsLogAnalyzing] = useState(false)
  const [logAnalysisError, setLogAnalysisError] = useState<string | null>(null)
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
    if (ackFilter !== '') p.set('acknowledged', ackFilter)
    if (knownFilter !== '') p.set('known', knownFilter)
    if (search) p.set('search', search)
    appendPlatform(p, platform)
    if (platform === 'virt') p.set('show_routine', String(showRoutine))
    return p
  }

  const { data: eventsData, isLoading } = useQuery<{ total: number; events: SystemEvent[] }>({
    queryKey: ['events', 'list', platform, severityFilter, typeFilter, resolvedFilter, ackFilter, knownFilter, search, page, showRoutine],
    queryFn: async () => {
      const params = paramsBase()
      params.set('limit', String(PAGE_SIZE)); params.set('offset', String(page * PAGE_SIZE))
      const res = await fetch(`${API_BASE_URL}/events/?${params}`)
      if (!res.ok) return { total: 0, events: [] }
      return res.json()
    },
    enabled: !groupedView, refetchInterval: 45_000,
  })

  const { data: groupedData, isLoading: groupedLoading } = useQuery<{ total: number; groups: EventGroup[] }>({
    queryKey: ['events', 'grouped', platform, severityFilter, typeFilter, resolvedFilter, ackFilter, knownFilter, search, page, sortBy, sortDir, excludeKnown, showRoutine],
    queryFn: async () => {
      const params = paramsBase()
      params.set('limit', String(PAGE_SIZE)); params.set('offset', String(page * PAGE_SIZE))
      params.set('sort_by', sortBy as string); params.set('sort_dir', sortDir)
      params.set('exclude_known', String(knownFilter === 'true' ? false : excludeKnown))
      const res = await fetch(`${API_BASE_URL}/events/grouped?${params}`)
      if (!res.ok) return { total: 0, groups: [] }
      return res.json()
    },
    enabled: groupedView, refetchInterval: 45_000,
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
    queryKey: ['eventStats', platform, showRoutine],
    queryFn: async () => {
      const params = appendPlatform(new URLSearchParams(), platform)
      if (platform === 'virt') params.set('show_routine', String(showRoutine))
      const res = await fetch(`${API_BASE_URL}/events/stats?${params}`)
      if (!res.ok) return { total: 0, unresolved: 0, critical: 0, warning: 0, emergency: 0, acknowledged: 0, known: 0 }
      return res.json()
    },
    refetchInterval: 45_000,
  })

  const { data: coverage } = useQuery<{
    with_events: { id: number; name: string; ip: string; event_count: number }[]
    without_events: { id: number; name: string; ip: string; event_count: number }[]
    with_count: number; without_count: number; hours: number
  }>({
    queryKey: ['events-coverage', platform],
    queryFn: async () => {
      const params = appendPlatform(new URLSearchParams({ hours: '24' }), platform)
      const res = await fetch(`${API_BASE_URL}/events/coverage?${params}`)
      if (!res.ok) return { with_events: [], without_events: [], with_count: 0, without_count: 0, hours: 24 }
      return res.json()
    },
    enabled: platform === 'linux' || platform === 'windows' || platform === 'exadata',
    refetchInterval: 60000,
  })

  const { data: eventTypes } = useQuery<string[]>({
    queryKey: ['eventTypes', platform],
    queryFn: async () => {
      const params = appendPlatform(new URLSearchParams(), platform)
      const res = await fetch(`${API_BASE_URL}/events/types?${params}`)
      if (!res.ok) return []
      return res.json()
    }
  })

  function invalidate() {
    queryClient.invalidateQueries({ queryKey: ['events'] })
    queryClient.invalidateQueries({ queryKey: ['eventStats'] })
    queryClient.invalidateQueries({ queryKey: ['ops-summary-nav'] })
    queryClient.invalidateQueries({ queryKey: ['windows-ops-summary'] })
    queryClient.invalidateQueries({ queryKey: ['virt-ops-summary'] })
    queryClient.invalidateQueries({ queryKey: ['exadata-ops-summary'] })
    queryClient.invalidateQueries({ queryKey: ['openshift-ops-summary'] })
    queryClient.invalidateQueries({ queryKey: ['ops-command-center'] })
    queryClient.invalidateQueries({ queryKey: ['openshift-command-center'] })
  }

  const handleScan = async () => {
    setScanning(true); setScanResult(null)
    try {
      const res = await fetch(`${API_BASE_URL}/events/scan?platform=${platform}&only_ai_ready=true`, { method: 'POST' })
      const data = await res.json()
      // Arka plan job: EventsHub BulkJobOverlay gösterir; burada kısa bilgi
      if (data.job_id) {
        setScanResult({
          total_servers: 0,
          servers_with_logs: 0,
          total_saved: 0,
          details: [],
          job_id: data.job_id,
          message: data.message || 'Tarama arka planda başladı',
        } as any)
      } else {
        setScanResult(data)
      }
      invalidate()
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
  const unackEvent = useMutation({ mutationFn: async (id: number) => { await fetch(`${API_BASE_URL}/events/${id}/unacknowledge`, { method: 'POST' }) }, onSuccess: invalidate })
  const knownEvent = useMutation({ mutationFn: async (id: number) => { await fetch(`${API_BASE_URL}/events/${id}/known`, { method: 'POST' }) }, onSuccess: invalidate })
  const unknownEvent = useMutation({ mutationFn: async (id: number) => { await fetch(`${API_BASE_URL}/events/${id}/unknown`, { method: 'POST' }) }, onSuccess: invalidate })
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
    setAnalyzeTab('chat'); setLogAnalysis(null); setLogAnalysisError(null)
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

  const startLogAnalyze = async (grp: EventGroup) => {
    if (!grp.event_ids.length) return
    setIsLogAnalyzing(true)
    setLogAnalysis(null)
    setLogAnalysisError(null)
    const eventId = grp.event_ids[0]
    try {
      const res = await fetch(`${API_BASE_URL}/events/${eventId}/log-analyze`, { method: 'POST' })
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: 'Bağlantı hatası' }))
        setLogAnalysisError(err.detail || `HTTP ${res.status}`)
        return
      }
      const data = await res.json()
      setLogAnalysis(data)
    } catch {
      setLogAnalysisError('Analiz isteği başarısız.')
    } finally {
      setIsLogAnalyzing(false)
    }
  }

  const openIncidentForGroup = (grp: EventGroup) => {
    setIncidentForm({ title: grp.title, description: `${grp.count} event içeren grup`, severity: grp.severity === 'emergency' ? 'critical' : grp.severity, assigned_to: '' })
    setIncidentModal({ event_ids: grp.event_ids, group_title: grp.title })
  }

  // group row action menu
  const groupMenu = (grp: EventGroup): MenuItem[] => [
    { label: 'Tümünü gör', icon: '', onClick: () => setDetailGroupIds(grp.event_ids) },
    { label: 'İncelemeye al', icon: <Eye size={13} strokeWidth={2} />, onClick: () => bulkAction.mutate({ action: 'acknowledge', ids: grp.event_ids }) },
    { label: 'Onayı kaldır', icon: '↩', hidden: !grp.is_acknowledged, onClick: () => bulkAction.mutate({ action: 'unacknowledge', ids: grp.event_ids }) },
    { label: 'Bilinen olay', icon: '', onClick: () => bulkAction.mutate({ action: 'known', ids: grp.event_ids }) },
    { label: 'Bilineni kaldır', icon: '↩', hidden: !grp.is_known, onClick: () => bulkAction.mutate({ action: 'unknown', ids: grp.event_ids }) },
    { label: 'Kapat (çöz)', icon: '', accent: NEON.green, onClick: () => bulkAction.mutate({ action: 'resolve', ids: grp.event_ids }) },
    { label: 'Yeniden aç', icon: '↩', hidden: !grp.resolved, onClick: () => bulkAction.mutate({ action: 'unresolve', ids: grp.event_ids }) },
    { label: 'Incident oluştur', icon: '', accent: NEON.blue, onClick: () => openIncidentForGroup(grp) },
  ]
  const markAsNormal = async (eventId: number) => {
    try {
      await fetch(`${API_BASE_URL}/baseline/suppressions/from-event/${eventId}?baseline_severity=warning`, { method: 'POST' })
    } catch { /* sessiz başarısız */ }
  }

  const toggleRaw = async (e: SystemEvent) => {
    if (expandedRaw === e.id) {
      setExpandedRaw(null)
      return
    }
    setExpandedRaw(e.id)
    if (e.raw_data && Object.keys(e.raw_data).length) {
      setRawCache(c => ({ ...c, [e.id]: e.raw_data }))
      return
    }
    if (rawCache[e.id] !== undefined) return
    try {
      const res = await fetch(`${API_BASE_URL}/events/${e.id}`)
      if (res.ok) {
        const full = await res.json()
        setRawCache(c => ({ ...c, [e.id]: full.raw_data ?? null }))
      } else {
        setRawCache(c => ({ ...c, [e.id]: null }))
      }
    } catch {
      setRawCache(c => ({ ...c, [e.id]: null }))
    }
  }

  const flatMenu = (e: SystemEvent): MenuItem[] => [
    { label: 'Raw data', icon: '', hidden: !(e.has_raw_data || (e.raw_data && Object.keys(e.raw_data).length)), onClick: () => { void toggleRaw(e) } },
    { label: 'İncelemeye al', icon: <Eye size={13} strokeWidth={2} />, hidden: e.is_acknowledged || e.resolved, onClick: () => ackEvent.mutate(e.id) },
    { label: 'Onayı kaldır', icon: '↩', hidden: !e.is_acknowledged || e.resolved, onClick: () => unackEvent.mutate(e.id) },
    { label: 'Bilinen olay', icon: '', hidden: e.is_known || e.resolved, onClick: () => knownEvent.mutate(e.id) },
    { label: 'Bilineni kaldır', icon: '↩', hidden: !e.is_known, onClick: () => unknownEvent.mutate(e.id) },
    { label: 'Bu sunucu için normal', icon: <BarChart3 size={13} strokeWidth={2} />, hidden: e.event_type !== 'metric_anomaly', accent: NEON.orange, onClick: () => markAsNormal(e.id) },
    { label: 'Kapat (çöz)', icon: '', accent: NEON.green, hidden: e.resolved, onClick: () => resolveEvent.mutate(e.id) },
    { label: 'Yeniden aç', icon: '↩', hidden: !e.resolved, onClick: () => unresolveEvent.mutate(e.id) },
    { label: 'Sil', icon: '✕', accent: NEON.red, onClick: () => { if (confirm('Bu event silinecek. Emin misiniz?')) deleteEvent.mutate(e.id) } },
  ]

  const inputCls = 'w-full rounded-lg px-3 py-2 text-white text-sm focus:outline-none'
  const inputStyle = { background: 'var(--bg-deep)', border: '1px solid rgba(99,130,194,0.2)' } as React.CSSProperties

  return (
    <div className="space-y-4 animate-fade-in">
      {!hideHeader && (
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
      )}

      {platform === 'virt' && (
        <label className="flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
          <input type="checkbox" checked={showRoutine} onChange={e => { setShowRoutine(e.target.checked); setPage(0) }} className="rounded border-slate-600" />
          Rutin olayları göster (vCenter task, login/logout)
        </label>
      )}

      {/* KPI row — tıklayınca filtreler */}
      <div className="grid grid-cols-3 md:grid-cols-7 gap-3">
        <Kpi label="Toplam" value={stats?.total ?? 0} accent={NEON.cyan}
          active={!severityFilter && resolvedFilter === '' && ackFilter === '' && knownFilter === ''}
          onClick={() => { setSeverityFilter(''); setResolvedFilter(''); setAckFilter(''); setKnownFilter(''); setExcludeKnown(false); setPage(0) }} />
        <Kpi label="Aktif" value={stats?.actionable_total ?? ((stats?.critical ?? 0) + (stats?.warning ?? 0))} accent={NEON.orange}
          active={resolvedFilter === 'false' && ackFilter === 'false' && knownFilter === 'false' && !severityFilter}
          onClick={() => { setSeverityFilter(''); setResolvedFilter('false'); setAckFilter('false'); setKnownFilter('false'); setExcludeKnown(true); setPage(0) }} />
        <Kpi label="Kritik" value={stats?.critical ?? 0} accent={NEON.red}
          active={severityFilter === 'critical,emergency' || severityFilter === 'critical'}
          onClick={() => { setSeverityFilter('critical,emergency'); setResolvedFilter('false'); setAckFilter('false'); setKnownFilter('false'); setPage(0) }} />
        <Kpi label="Acil" value={stats?.emergency ?? 0} accent={NEON.pink}
          active={severityFilter === 'emergency'} onClick={() => { setSeverityFilter('emergency'); setResolvedFilter('false'); setAckFilter('false'); setKnownFilter('false'); setPage(0) }} />
        <Kpi label="Uyarı" value={stats?.warning ?? 0} accent={NEON.orange}
          active={severityFilter === 'warning' && ackFilter === 'false'}
          onClick={() => { setSeverityFilter('warning'); setResolvedFilter('false'); setAckFilter('false'); setKnownFilter('false'); setPage(0) }} />
        <Kpi label="Onaylanan" value={stats?.acknowledged ?? 0} accent={NEON.blue}
          active={ackFilter === 'true'}
          onClick={() => { setSeverityFilter(''); setResolvedFilter(''); setAckFilter('true'); setKnownFilter(''); setExcludeKnown(false); setPage(0) }} />
        <Kpi label="Bilinen" value={stats?.known ?? 0} accent={NEON.cyan}
          active={knownFilter === 'true'}
          onClick={() => { setSeverityFilter(''); setResolvedFilter(''); setAckFilter(''); setKnownFilter('true'); setExcludeKnown(false); setPage(0) }} />
      </div>

      {coverage && (platform === 'linux' || platform === 'windows' || platform === 'exadata') && (
        <div className="cyber-card px-4 py-3 flex flex-wrap items-start gap-4 text-xs">
          <div>
            <p className="font-medium text-slate-300 mb-1">AI Ready kapsama (24s)</p>
            <p style={{ color: 'rgba(148,163,184,0.65)' }}>
              <span style={{ color: NEON.green }}>{coverage.with_count} event gelen</span>
              {' · '}
              <span style={{ color: NEON.orange }}>{coverage.without_count} event gelmeyen</span>
            </p>
          </div>
          {coverage.without_events.length > 0 && (
            <div className="flex-1 min-w-[12rem]">
              <p className="mb-1" style={{ color: 'rgba(148,163,184,0.5)' }}>Event gelmeyen (AI Ready):</p>
              <div className="flex flex-wrap gap-1.5 max-h-16 overflow-y-auto">
                {coverage.without_events.slice(0, 40).map(s => (
                  <span key={s.id} className="px-2 py-0.5 rounded border text-[11px]"
                    style={{ borderColor: 'rgba(251,191,36,0.25)', color: 'rgba(251,191,36,0.9)', background: 'rgba(251,191,36,0.06)' }}
                    title={s.ip || ''}>{s.name}</span>
                ))}
                {coverage.without_events.length > 40 && (
                  <span style={{ color: 'rgba(148,163,184,0.5)' }}>+{coverage.without_events.length - 40}</span>
                )}
              </div>
            </div>
          )}
        </div>
      )}

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
          <option value="">Tüm Durumlar</option><option value="false">Aktif (çözülmemiş)</option><option value="true">Çözülmüş / Kapatılan</option>
        </Select>
        <Select value={ackFilter} onChange={v => { setAckFilter(v); if (v === 'true') { setResolvedFilter(''); setExcludeKnown(false) }; setPage(0) }}>
          <option value="">Onay: hepsi</option><option value="true">Onaylanan</option><option value="false">Onaysız</option>
        </Select>
        <label className="flex items-center gap-2 cursor-pointer select-none ml-1">
          <div onClick={() => { setGroupedView(v => !v); setPage(0) }}
            className="relative w-9 h-5 rounded-full transition-colors cursor-pointer"
            style={{ background: groupedView ? NEON.cyan : 'rgba(100,116,139,0.5)' }}>
            <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${groupedView ? 'translate-x-4' : ''}`} />
          </div>
          <span className="text-xs" style={{ color: 'rgba(148,163,184,0.7)' }}>Benzerleri grupla</span>
        </label>
        <label className="flex items-center gap-2 cursor-pointer select-none">
          <div onClick={() => { setExcludeKnown(v => !v); setPage(0) }}
            className="relative w-9 h-5 rounded-full transition-colors cursor-pointer"
            style={{ background: excludeKnown ? NEON.orange : 'rgba(100,116,139,0.5)' }}>
            <span className={`absolute top-0.5 left-0.5 w-4 h-4 bg-white rounded-full shadow transition-transform ${excludeKnown ? 'translate-x-4' : ''}`} />
          </div>
          <span className="text-xs" style={{ color: excludeKnown ? NEON.orange : 'rgba(148,163,184,0.5)' }}>
            Bilinenleri gizle
          </span>
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
                              {rawCache[event.id] === undefined
                                ? 'Yükleniyor…'
                                : JSON.stringify(rawCache[event.id] ?? event.raw_data, null, 2)}
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
          onClose={() => { analyzeAbortRef.current?.abort(); setAnalyzeGroup(null); setAnalysisText(''); setLogAnalysis(null); setLogAnalysisError(null) }}
          footer={
            <div className="flex justify-between items-center gap-2">
              {analyzeTab === 'chat'
                ? <GhostButton accent={NEON.blue} onClick={() => startAnalyze(analyzeGroup)} disabled={isAnalyzing}>Yeniden</GhostButton>
                : <GhostButton accent={NEON.cyan} onClick={() => startLogAnalyze(analyzeGroup)} disabled={isLogAnalyzing}>Yeniden Analiz Et</GhostButton>
              }
              <div className="flex gap-2">
                <GhostButton accent={NEON.green} onClick={() => { bulkAction.mutate({ action: 'resolve', ids: analyzeGroup.event_ids }); setAnalyzeGroup(null) }}>Kapat</GhostButton>
                <GhostButton accent={NEON.blue} onClick={() => {
                  setIncidentForm({ title: analyzeGroup.title, description: analysisText.slice(0, 300) || `${analyzeGroup.count} event`, severity: analyzeGroup.severity === 'emergency' ? 'critical' : analyzeGroup.severity, assigned_to: '' })
                  setIncidentModal({ event_ids: analyzeGroup.event_ids, group_title: analyzeGroup.title })
                }}>Incident</GhostButton>
              </div>
            </div>
          }>
          {/* Sekme bar */}
          <div className="flex border-b px-5 pt-1" style={{ borderColor: 'rgba(255,255,255,0.06)' }}>
            <button
              onClick={() => setAnalyzeTab('chat')}
              className="text-xs font-medium pb-2 mr-4 border-b-2 transition-colors"
              style={{ borderColor: analyzeTab === 'chat' ? NEON.blue : 'transparent', color: analyzeTab === 'chat' ? NEON.blue : 'rgba(148,163,184,0.6)' }}
            >AI Sohbet</button>
            <button
              onClick={() => { setAnalyzeTab('log'); if (!logAnalysis && !isLogAnalyzing) startLogAnalyze(analyzeGroup) }}
              className="text-xs font-medium pb-2 border-b-2 transition-colors flex items-center gap-1"
              style={{ borderColor: analyzeTab === 'log' ? NEON.cyan : 'transparent', color: analyzeTab === 'log' ? NEON.cyan : 'rgba(148,163,184,0.6)' }}
            >Log Kök Neden Analizi</button>
          </div>

          {/* AI Sohbet sekmesi */}
          {analyzeTab === 'chat' && (
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
          )}

          {/* Log Kök Neden Analizi sekmesi */}
          {analyzeTab === 'log' && (
            <div className="p-5 space-y-4">
              {isLogAnalyzing && (
                <div className="flex items-center gap-2 text-sm" style={{ color: 'rgba(148,163,184,0.7)' }}>
                  <div className="w-4 h-4 border-2 border-t-transparent rounded-full animate-spin" style={{ borderColor: `${NEON.cyan} transparent ${NEON.cyan} ${NEON.cyan}` }} />
                  Log satırları okunuyor, AI analiz yapıyor...
                </div>
              )}
              {logAnalysisError && (
                <div className="text-sm p-3 rounded-[8px]" style={{ background: 'rgba(239,68,68,0.08)', color: NEON.red, border: '1px solid rgba(239,68,68,0.2)' }}>
                  {logAnalysisError}
                </div>
              )}
              {logAnalysis && !isLogAnalyzing && (
                <div className="space-y-4">
                  {/* Güven + meta */}
                  <div className="flex items-center gap-3 text-xs" style={{ color: 'rgba(148,163,184,0.6)' }}>
                    <span className="px-2 py-0.5 rounded-full text-xs font-medium"
                      style={{
                        background: logAnalysis.confidence === 'high' ? 'rgba(34,197,94,0.12)' : logAnalysis.confidence === 'medium' ? 'rgba(251,191,36,0.12)' : 'rgba(148,163,184,0.1)',
                        color: logAnalysis.confidence === 'high' ? NEON.green : logAnalysis.confidence === 'medium' ? NEON.orange : 'rgba(148,163,184,0.6)',
                        border: `1px solid ${logAnalysis.confidence === 'high' ? 'rgba(34,197,94,0.3)' : logAnalysis.confidence === 'medium' ? 'rgba(251,191,36,0.3)' : 'rgba(148,163,184,0.2)'}`,
                      }}>
                      {logAnalysis.confidence === 'high' ? 'Yüksek Güven' : logAnalysis.confidence === 'medium' ? 'Orta Güven' : 'Düşük Güven'}
                    </span>
                    <span>{logAnalysis.log_lines_used} log satırı kullanıldı</span>
                    <span>Model: {logAnalysis.model}</span>
                  </div>

                  {/* Kök neden */}
                  <div className="p-3 rounded-[8px]" style={{ background: 'rgba(6,182,212,0.06)', border: '1px solid rgba(6,182,212,0.15)' }}>
                    <div className="text-xs font-semibold mb-1" style={{ color: NEON.cyan }}>Kök Neden</div>
                    <div className="text-sm" style={{ color: 'rgba(226,232,240,0.9)' }}>{logAnalysis.root_cause}</div>
                  </div>

                  {/* Etki */}
                  {logAnalysis.impact && (
                    <div className="p-3 rounded-[8px]" style={{ background: 'rgba(251,191,36,0.06)', border: '1px solid rgba(251,191,36,0.12)' }}>
                      <div className="text-xs font-semibold mb-1" style={{ color: NEON.orange }}>Etki</div>
                      <div className="text-sm" style={{ color: 'rgba(226,232,240,0.9)' }}>{logAnalysis.impact}</div>
                    </div>
                  )}

                  {/* Öneriler */}
                  {logAnalysis.recommendations.length > 0 && (
                    <div className="p-3 rounded-[8px]" style={{ background: 'rgba(34,197,94,0.06)', border: '1px solid rgba(34,197,94,0.12)' }}>
                      <div className="text-xs font-semibold mb-2 flex items-center gap-2" style={{ color: NEON.green }}>
                        Önerilen Aksiyonlar
                        {logAnalysis.requires_approval && (
                          <span className="text-xs px-1.5 py-0.5 rounded" style={{ background: 'rgba(251,191,36,0.15)', color: NEON.orange, border: '1px solid rgba(251,191,36,0.3)' }}>Onay Gerekli</span>
                        )}
                      </div>
                      <ol className="space-y-1.5">
                        {logAnalysis.recommendations.map((rec, i) => (
                          <li key={i} className="flex gap-2 text-sm" style={{ color: 'rgba(226,232,240,0.85)' }}>
                            <span className="flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-xs font-bold" style={{ background: 'rgba(34,197,94,0.15)', color: NEON.green }}>{i + 1}</span>
                            <code className="text-xs bg-black/20 px-1.5 py-0.5 rounded font-mono" style={{ color: 'rgba(226,232,240,0.9)' }}>{rec}</code>
                          </li>
                        ))}
                      </ol>
                    </div>
                  )}
                </div>
              )}
            </div>
          )}
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
