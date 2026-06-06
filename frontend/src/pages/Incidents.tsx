import React, { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API_BASE_URL } from '../config/api'
import {
  NEON, rgb, PageHeader, PrimaryButton, GhostButton, Kpi, SeverityBadge, StatusBadge,
  SearchInput, Select, ActionMenu, Section, EmptyState, sevColor,
} from '../components/aiops/ui'

interface Server { id: number; name: string; ip: string; status?: string }
interface RelatedEvent {
  id: number; title: string; severity: string; event_type: string
  source: string | null; resolved: boolean; is_acknowledged: boolean; created_at: string | null
}
interface Incident {
  id: number; title: string; description: string | null; severity: string; status: string
  source: string | null; affected_servers: number[]; affected_server_details: Server[]
  related_events: number[]; related_event_details?: RelatedEvent[]
  root_cause: string | null; resolution: string | null; rca_result: any
  assigned_to: string | null; created_at: string | null; updated_at: string | null; resolved_at: string | null
}
interface IncidentStats { total: number; open: number; investigating: number; resolved: number; critical: number }

function fmt(d: string | null, short = true) {
  if (!d) return '—'
  return new Date(d).toLocaleString('tr-TR', short ? { day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' } : undefined)
}

const Incidents: React.FC = () => {
  const [statusFilter, setStatusFilter] = useState('')
  const [severityFilter, setSeverityFilter] = useState('')
  const [search, setSearch] = useState('')
  const [showCreateForm, setShowCreateForm] = useState(false)
  const [selectedIncident, setSelectedIncident] = useState<Incident | null>(null)
  const [detailLoading, setDetailLoading] = useState(false)
  const [newIncident, setNewIncident] = useState({ title: '', description: '', severity: 'medium', assigned_to: '' })
  const [resolutionText, setResolutionText] = useState('')
  const [assignText, setAssignText] = useState('')
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
    setSelectedIncident(inc); setDetailLoading(true)
    setResolutionText(inc.resolution || ''); setAssignText(inc.assigned_to || '')
    try {
      const res = await fetch(`${API_BASE_URL}/incidents/${inc.id}`)
      if (res.ok) { const full = await res.json(); setSelectedIncident(full); setResolutionText(full.resolution || ''); setAssignText(full.assigned_to || '') }
    } finally { setDetailLoading(false) }
  }

  const createIncident = useMutation({
    mutationFn: async (data: typeof newIncident) => {
      const res = await fetch(`${API_BASE_URL}/incidents/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...data, assigned_to: data.assigned_to || null })
      })
      if (!res.ok) throw new Error()
      return res.json()
    },
    onSuccess: () => { invalidate(); setShowCreateForm(false); setNewIncident({ title: '', description: '', severity: 'medium', assigned_to: '' }) }
  })

  const updateIncident = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: any }) => {
      const res = await fetch(`${API_BASE_URL}/incidents/${id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
      })
      if (!res.ok) throw new Error()
      return res.json()
    },
    onSuccess: (_d, vars) => { invalidate(); if (selectedIncident?.id === vars.id) openDetail(selectedIncident) }
  })

  const deleteIncident = useMutation({
    mutationFn: async (id: number) => { const r = await fetch(`${API_BASE_URL}/incidents/${id}`, { method: 'DELETE' }); if (!r.ok) throw new Error() },
    onSuccess: () => { invalidate(); setSelectedIncident(null) }
  })

  const runRCA = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${API_BASE_URL}/incidents/${id}/rca`, { method: 'POST' })
      if (!res.ok) { const e = await res.json(); throw new Error(e.detail || 'RCA çalıştırılamadı') }
      return res.json()
    },
    onSuccess: (data) => { invalidate(); if (selectedIncident) setSelectedIncident({ ...selectedIncident, rca_result: data.rca, root_cause: data.rca?.analysis?.slice(0, 500) }) }
  })

  const incidents = incidentsData?.incidents || []
  const inputCls = 'w-full rounded-lg px-3 py-2 text-white text-sm focus:outline-none'
  const inputStyle = { background: 'var(--bg-deep)', border: '1px solid rgba(99,130,194,0.2)' } as React.CSSProperties

  const rowMenu = (inc: Incident) => {
    const items = []
    if (inc.status === 'open') items.push({ label: "İncelemeye al", icon: "", accent: NEON.orange, onClick: () => updateIncident.mutate({ id: inc.id, data: { status: 'investigating' } }) })
    if (inc.status === 'open' || inc.status === 'investigating') items.push({ label: 'Çözüldü işaretle', icon: '', accent: NEON.green, onClick: () => updateIncident.mutate({ id: inc.id, data: { status: 'resolved' } }) })
    if (inc.status === 'resolved') items.push({ label: 'Kapat', icon: '🔒', accent: NEON.slate, onClick: () => updateIncident.mutate({ id: inc.id, data: { status: 'closed' } }) })
    items.push({ label: 'Sil', icon: '✕', accent: NEON.red, onClick: () => { if (confirm('Bu incident silinecek?')) deleteIncident.mutate(inc.id) } })
    return items
  }

  return (
    <div className="flex gap-4 animate-fade-in">
      {/* Left: list */}
      <div className={`flex-1 min-w-0 space-y-4 ${selectedIncident ? 'max-w-2xl' : ''}`}>
        <PageHeader title="Incidents" subtitle="Incident yönetimi ve AI kök neden analizi"
          actions={<PrimaryButton accent={NEON.red} onClick={() => setShowCreateForm(v => !v)}>{showCreateForm ? 'İptal' : '+ Yeni Incident'}</PrimaryButton>} />

        {/* KPI */}
        <div className="grid grid-cols-3 md:grid-cols-5 gap-3">
          <Kpi label="Toplam" value={stats?.total ?? 0} accent={NEON.cyan} active={!statusFilter && !severityFilter} onClick={() => { setStatusFilter(''); setSeverityFilter('') }} />
          <Kpi label="Açık" value={stats?.open ?? 0} accent={NEON.red} active={statusFilter === 'open'} onClick={() => { setStatusFilter('open'); setSeverityFilter('') }} />
          <Kpi label="İnceleniyor" value={stats?.investigating ?? 0} accent={NEON.orange} active={statusFilter === 'investigating'} onClick={() => { setStatusFilter('investigating'); setSeverityFilter('') }} />
          <Kpi label="Çözülmüş" value={stats?.resolved ?? 0} accent={NEON.green} active={statusFilter === 'resolved'} onClick={() => { setStatusFilter('resolved'); setSeverityFilter('') }} />
          <Kpi label="Kritik Açık" value={stats?.critical ?? 0} accent={NEON.red} active={severityFilter === 'critical'} onClick={() => { setSeverityFilter('critical'); setStatusFilter('') }} />
        </div>

        {showCreateForm && (
          <Section title="Yeni Incident" accent={NEON.red}>
            <form onSubmit={e => { e.preventDefault(); createIncident.mutate(newIncident) }} className="p-5 space-y-4">
              <div className="grid grid-cols-3 gap-4">
                <div className="col-span-2">
                  <label className="block text-xs mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>Başlık *</label>
                  <input required value={newIncident.title} onChange={e => setNewIncident({ ...newIncident, title: e.target.value })} className={inputCls} style={inputStyle} />
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>Önem</label>
                  <select value={newIncident.severity} onChange={e => setNewIncident({ ...newIncident, severity: e.target.value })} className={inputCls} style={inputStyle}>
                    <option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option><option value="critical">Critical</option>
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>Açıklama</label>
                  <textarea value={newIncident.description} onChange={e => setNewIncident({ ...newIncident, description: e.target.value })} rows={2} className={inputCls} style={inputStyle} />
                </div>
                <div>
                  <label className="block text-xs mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>Atanan</label>
                  <input value={newIncident.assigned_to} placeholder="ops-team / admin..." onChange={e => setNewIncident({ ...newIncident, assigned_to: e.target.value })} className={inputCls} style={inputStyle} />
                </div>
              </div>
              <PrimaryButton accent={NEON.red} disabled={createIncident.isPending}>{createIncident.isPending ? 'Oluşturuluyor...' : 'Oluştur'}</PrimaryButton>
            </form>
          </Section>
        )}

        {/* Toolbar */}
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput value={search} onChange={setSearch} placeholder="Başlıkta ara..." width="w-48" />
          <Select value={statusFilter} onChange={setStatusFilter}>
            <option value="">Tüm Durumlar</option><option value="open">Açık</option><option value="investigating">İnceleniyor</option><option value="resolved">Çözülmüş</option><option value="closed">Kapatılmış</option>
          </Select>
          <Select value={severityFilter} onChange={setSeverityFilter}>
            <option value="">Tüm Önem</option><option value="critical">Critical</option><option value="high">High</option><option value="medium">Medium</option><option value="low">Low</option>
          </Select>
          <span className="ml-auto text-xs" style={{ color: 'rgba(148,163,184,0.5)' }}>{incidentsData?.total ?? 0} sonuç</span>
        </div>

        {/* List */}
        {isLoading ? (
          <div className="py-16 flex justify-center"><div className="animate-spin rounded-full h-8 w-8 border-2 border-t-cyan-400 border-white/[0.06]" /></div>
        ) : incidents.length === 0 ? (
          <Section><EmptyState icon="" text="Henüz incident yok" /></Section>
        ) : (
          <div className="space-y-2.5">
            {incidents.map(inc => {
              const c = sevColor(inc.severity)
              const sel = selectedIncident?.id === inc.id
              return (
                <div key={inc.id} onClick={() => openDetail(inc)}
                  className="cyber-card p-4 cursor-pointer transition-all"
                  style={{ borderColor: sel ? `rgba(${rgb(NEON.cyan)},0.5)` : undefined, borderLeft: `3px solid ${c}` }}>
                  <div className="flex items-start justify-between gap-3">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1.5 flex-wrap">
                        <SeverityBadge severity={inc.severity} />
                        <StatusBadge status={inc.status} />
                        <span className="text-[11px]" style={{ color: 'rgba(148,163,184,0.4)' }}>#{inc.id}</span>
                        {inc.assigned_to && <span className="text-[11px]" style={{ color: 'rgba(148,163,184,0.6)' }}>{inc.assigned_to}</span>}
                      </div>
                      <h3 className="text-white font-medium text-sm truncate">{inc.title}</h3>
                      {inc.description && <p className="text-xs mt-0.5 truncate" style={{ color: 'rgba(148,163,184,0.6)' }}>{inc.description}</p>}
                      <div className="flex items-center gap-3 mt-2 text-[11px]" style={{ color: 'rgba(148,163,184,0.5)' }}>
                        {inc.affected_server_details?.length > 0 && <span>{inc.affected_server_details.map(s => s.name).join(', ')}</span>}
                        {inc.related_events?.length > 0 && <span>{inc.related_events.length} event</span>}
                        {inc.rca_result?.analysis && <span className="text-[10px] font-bold text-blue-400">AI RCA</span>}
                        <span className="ml-auto">{fmt(inc.created_at)}</span>
                      </div>
                    </div>
                    <div onClick={e => e.stopPropagation()}><ActionMenu items={rowMenu(inc)} /></div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Right: detail */}
      {selectedIncident && (
        <div className="flex-1 max-w-[540px]">
          <div className="cyber-card overflow-y-auto max-h-[calc(100vh-110px)] sticky top-0">
            <div className="px-5 py-4 flex items-start justify-between" style={{ borderBottom: '1px solid rgba(99,130,194,0.12)' }}>
              <div className="min-w-0">
                <div className="flex items-center gap-2 mb-1.5">
                  <SeverityBadge severity={selectedIncident.severity} />
                  <StatusBadge status={selectedIncident.status} />
                  <span className="text-[11px]" style={{ color: 'rgba(148,163,184,0.4)' }}>#{selectedIncident.id}</span>
                </div>
                <h2 className="text-white font-semibold text-sm leading-snug">{selectedIncident.title}</h2>
              </div>
              <button onClick={() => setSelectedIncident(null)} className="text-slate-400 hover:text-white ml-2 text-xl leading-none flex-shrink-0">&times;</button>
            </div>

            {detailLoading ? (
              <div className="p-10 flex justify-center"><div className="animate-spin rounded-full h-6 w-6 border-2 border-t-cyan-400 border-white/[0.06]" /></div>
            ) : (
              <div className="p-5 space-y-5 text-sm">
                {selectedIncident.description && (
                  <div>
                    <p className="text-xs font-medium mb-1" style={{ color: 'rgba(148,163,184,0.7)' }}>Açıklama</p>
                    <p className="text-xs whitespace-pre-wrap" style={{ color: 'rgba(226,232,240,0.85)' }}>{selectedIncident.description}</p>
                  </div>
                )}

                <div className="grid grid-cols-2 gap-2.5 text-xs">
                  {[
                    { l: 'Atanan', v: selectedIncident.assigned_to || '—' },
                    { l: 'Kaynak', v: selectedIncident.source || '—' },
                    { l: 'Oluşturulma', v: fmt(selectedIncident.created_at, false) },
                    { l: 'Çözülme', v: fmt(selectedIncident.resolved_at, false) },
                  ].map(m => (
                    <div key={m.l} className="rounded-lg p-2.5" style={{ background: 'var(--bg-deep)', border: '1px solid rgba(99,130,194,0.1)' }}>
                      <p className="mb-0.5" style={{ color: 'rgba(148,163,184,0.5)' }}>{m.l}</p>
                      <p className="text-white truncate">{m.v}</p>
                    </div>
                  ))}
                </div>

                {selectedIncident.affected_server_details?.length > 0 && (
                  <div>
                    <p className="text-xs font-medium mb-2" style={{ color: 'rgba(148,163,184,0.7)' }}>Etkilenen Sunucular</p>
                    <div className="flex flex-wrap gap-1.5">
                      {selectedIncident.affected_server_details.map(s => (
                        <span key={s.id} className="text-[11px] px-2 py-0.5 rounded" style={{ background: `rgba(${rgb(NEON.blue)},0.12)`, color: NEON.blue, border: `1px solid rgba(${rgb(NEON.blue)},0.25)` }}>
                          {s.name}{s.ip ? ` (${s.ip})` : ''}
                        </span>
                      ))}
                    </div>
                  </div>
                )}

                {/* Status actions */}
                <div className="flex gap-2 flex-wrap">
                  {selectedIncident.status === 'open' && (
                    <GhostButton accent={NEON.orange} onClick={() => updateIncident.mutate({ id: selectedIncident.id, data: { status: 'investigating' } })}>İncelemeye Al</GhostButton>
                  )}
                  {(selectedIncident.status === 'open' || selectedIncident.status === 'investigating') && (
                    <>
                      <GhostButton accent={NEON.blue} onClick={() => runRCA.mutate(selectedIncident.id)} disabled={runRCA.isPending}>
                        {runRCA.isPending ? 'Analiz...' : 'AI RCA Çalıştır'}
                      </GhostButton>
                      <GhostButton accent={NEON.green} onClick={() => updateIncident.mutate({ id: selectedIncident.id, data: { status: 'resolved' } })}>Çözüldü</GhostButton>
                    </>
                  )}
                  {selectedIncident.status === 'resolved' && (
                    <GhostButton accent={NEON.slate} onClick={() => updateIncident.mutate({ id: selectedIncident.id, data: { status: 'closed' } })}>Kapat</GhostButton>
                  )}
                </div>

                {/* Assign */}
                <div>
                  <p className="text-xs font-medium mb-1.5" style={{ color: 'rgba(148,163,184,0.7)' }}>Atama</p>
                  <div className="flex gap-2">
                    <input value={assignText} onChange={e => setAssignText(e.target.value)} placeholder="ops-team / admin..." className={inputCls} style={inputStyle} />
                    <GhostButton accent={NEON.blue} onClick={() => updateIncident.mutate({ id: selectedIncident.id, data: { assigned_to: assignText || null } })}>Kaydet</GhostButton>
                  </div>
                </div>

                {/* Resolution */}
                <div>
                  <p className="text-xs font-medium mb-1.5" style={{ color: 'rgba(148,163,184,0.7)' }}>Çözüm Notları</p>
                  <textarea value={resolutionText} onChange={e => setResolutionText(e.target.value)} placeholder="Çözüm adımları..." rows={3} className={inputCls} style={inputStyle} />
                  <div className="mt-1.5">
                    <GhostButton accent={NEON.blue} onClick={() => updateIncident.mutate({ id: selectedIncident.id, data: { resolution: resolutionText } })} disabled={updateIncident.isPending}>
                      {updateIncident.isPending ? 'Kaydediliyor...' : 'Kaydet'}
                    </GhostButton>
                  </div>
                </div>

                {/* RCA */}
                {selectedIncident.rca_result?.analysis && (
                  <div>
                    <p className="text-xs font-medium mb-1.5 flex items-center gap-1.5" style={{ color: NEON.blue }}>
                      AI Kök Neden Analizi
                      {selectedIncident.rca_result.auto && <span className="px-1.5 py-0.5 rounded text-[9px]" style={{ background: `rgba(${rgb(NEON.blue)},0.15)` }}>OTOMATİK</span>}
                    </p>
                    <div className="rounded-lg p-3" style={{ background: 'var(--bg-deep)', border: `1px solid rgba(${rgb(NEON.blue)},0.2)` }}>
                      <p className="text-[10px] mb-2" style={{ color: 'rgba(148,163,184,0.5)' }}>
                        {selectedIncident.rca_result.model} · {fmt(selectedIncident.rca_result.analyzed_at, false)}
                      </p>
                      <div className="prose prose-invert prose-sm max-w-none text-xs leading-relaxed break-words" style={{ color: 'rgba(226,232,240,0.9)' }}>
                        <ReactMarkdown remarkPlugins={[remarkGfm]}>{selectedIncident.rca_result.analysis}</ReactMarkdown>
                      </div>
                    </div>
                  </div>
                )}

                {/* Related events */}
                {(selectedIncident.related_event_details?.length ?? 0) > 0 && (
                  <div>
                    <p className="text-xs font-medium mb-2" style={{ color: 'rgba(148,163,184,0.7)' }}>İlgili Eventler ({selectedIncident.related_event_details!.length})</p>
                    <div className="space-y-1.5">
                      {selectedIncident.related_event_details!.map(evt => (
                        <div key={evt.id} className="flex items-start gap-2 rounded-lg p-2.5" style={{ background: 'var(--bg-deep)', border: '1px solid rgba(99,130,194,0.1)' }}>
                          <span className="text-xs shrink-0 mt-0.5" style={{ color: sevColor(evt.severity) }}>●</span>
                          <div className="min-w-0 flex-1">
                            <p className="text-xs text-white truncate" title={evt.title}>{evt.title}</p>
                            <div className="flex gap-2 mt-0.5 text-[10px]" style={{ color: 'rgba(148,163,184,0.5)' }}>
                              <span className="font-mono">{evt.event_type}</span>
                              {evt.resolved && <span style={{ color: NEON.green }}>çözüldü</span>}
                              <span>{fmt(evt.created_at)}</span>
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
        </div>
      )}
    </div>
  )
}

export default Incidents
