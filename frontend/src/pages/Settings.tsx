import React, { useState } from 'react'
import { AlertTriangle, CheckCircle2, XCircle, Star, Monitor, BarChart3, Search } from 'lucide-react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import { API_BASE_URL } from '../config/api'
import { useAuth } from '../auth/AuthContext'
import { useBranding } from '../branding/BrandingContext'
import { PlatformUpdateTab } from '../components/PlatformUpdateTab'
import { PlatformStatusTab } from '../components/PlatformStatusTab'
import SecuritySettings from './SecuritySettings'
import { useT, useLocale } from '../i18n/LocaleProvider'

interface Credential {
  id: number
  name: string
  username: string
  port: number
  has_password: boolean
  has_private_key: boolean
  is_default: boolean
}

interface Server {
  id: number
  name: string
  ip_address: string
  ai_ready: boolean
  os_type?: string
  connection_config: any
}

const isWindowsServer = (s: Server) => {
  const os = (s.os_type || '').toLowerCase()
  if (os.includes('windows')) return true
  const cfg = s.connection_config || {}
  if (cfg.winrm || cfg.protocol === 'winrm') return true
  return false
}

const ConfirmModal = ({ message, onConfirm, onCancel }: {
  message: string; onConfirm: () => void; onCancel: () => void
}) => {
  const t = useT()
  return (
  <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm">
    <div className="bg-cyber-card border border-slate-600 rounded-2xl shadow-2xl p-6 max-w-sm w-full mx-4">
      <div className="flex items-start gap-3 mb-5">
        <div className="w-9 h-9 rounded-full bg-yellow-500/15 border border-yellow-500/30 flex items-center justify-center flex-shrink-0 mt-0.5">
          <AlertTriangle size={16} strokeWidth={2} className="text-yellow-400" />
        </div>
        <div>
          <div className="text-sm font-semibold text-white mb-1">{t('confirm_title')}</div>
          <div className="text-sm text-slate-300 leading-relaxed">{message}</div>
        </div>
      </div>
      <div className="flex gap-3 justify-end">
        <button onClick={onCancel} className="px-4 py-2 rounded-lg text-sm text-slate-300 hover:text-white bg-white/[0.07] hover:bg-slate-600 border border-slate-600 transition-colors">{t('cancel')}</button>
        <button onClick={onConfirm} className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-red-600 hover:bg-red-500 border border-red-500/50 transition-colors">{t('confirm_ok')}</button>
      </div>
    </div>
  </div>
  )
}

interface RagStatus {
  runbook: number
  incidents: number
  metrics: number
  knowledge?: number
  sources?: {
    incidents_db?: number
    events_db?: number
    learned_facts_db?: number
    linux_inventory_db?: number
    default_metrics?: number
  }
  embedding?: {
    ok?: boolean
    base_url?: string
    model?: string
    model_present?: boolean
    dim?: number
    error?: string | null
    hint?: string
    remote_llm_fallback?: boolean
  }
}

interface RunbookDocument {
  title: string
  chunk_count: number
  chunk_ids?: string[]
}

interface RunbookSearchHit {
  id?: string
  title: string
  page?: number | null
  chunk_index?: number | null
  similarity: number
  snippet: string
}

interface RemoteLlmSettings {
  enabled: boolean
  url: string
  model: string
  api_key_set: boolean
  api_key_masked: string
  virtual_key_set?: boolean
  virtual_key_masked?: string
  verify_ssl: boolean
  ca_bundle: string
}

interface GeneralSettings {
  ollama_url: string
  ollama_model: string
  prometheus_url: string
  pushgateway_url?: string
  prometheus_linux_jobs?: string[]
  prometheus_windows_jobs?: string[]
  metric_retention_days?: number
  management_server_ip?: string
  detected_management_ip?: string
  remote_llm?: RemoteLlmSettings
}

const RagTab: React.FC = () => {
  const t = useT()
  const { locale } = useLocale()
  const dateLoc = locale === 'en' ? 'en-GB' : 'tr-TR'
  const [pdfFile, setPdfFile] = useState<File | null>(null)
  const [pdfTitle, setPdfTitle] = useState('')
  const [rbQuery, setRbQuery] = useState('')
  const [rbHits, setRbHits] = useState<RunbookSearchHit[] | null>(null)
  const [rbSearchErr, setRbSearchErr] = useState<string | null>(null)
  const [statusError, setStatusError] = useState<string | null>(null)
  const [confirmState, setConfirmState] = React.useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))
  const { data: status, refetch: refetchStatus, isError: statusIsError, error: statusQueryError } = useQuery<RagStatus>({
    queryKey: ['rag-status'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/rag/status`)
      const body = await res.json().catch(() => ({}))
      if (!res.ok) {
        const detail = typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`
        setStatusError(detail)
        throw new Error(detail)
      }
      setStatusError(null)
      return body
    },
    retry: 1,
  })
  const uploadPdf = useMutation({
    mutationFn: async () => {
      if (!pdfFile) throw new Error(t('set_pdf_required'))
      const form = new FormData()
      form.append('file', pdfFile)
      if (pdfTitle.trim()) form.append('title', pdfTitle.trim())
      const res = await fetch(`${API_BASE_URL}/rag/runbook/ingest-pdf`, { method: 'POST', body: form })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || t('set_upload_err'))
      return r
    },
    onSuccess: (d) => { refetchStatus(); refetchRunbookDocs(); setPdfFile(null); setPdfTitle(''); alert(t('set_pdf_added', { n: d.chunks_added })) },
    onError: (e) => alert(e instanceof Error ? e.message : t('set_pdf_upload_err'))
  })
  const seedMetrics = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/rag/metrics/seed`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({}) })
      const r = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof r.detail === 'string' ? r.detail : t('set_metrics_err'))
      if (!r.chunks_added) throw new Error(t('set_zero_chunk'))
      return r
    },
    onSuccess: (d) => { refetchStatus(); alert(t('set_metrics_added', { n: d.chunks_added })) },
    onError: (e) => alert(e instanceof Error ? e.message : t('error_generic')),
  })
  const reindexIncidents = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/rag/incidents/reindex`, { method: 'POST' })
      const r = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof r.detail === 'string' ? r.detail : t('error_generic'))
      return r
    },
    onSuccess: (d) => { refetchStatus(); alert(t('set_inc_indexed', { n: d.chunks_added })) },
    onError: (e) => alert(e instanceof Error ? e.message : t('error_generic')),
  })
  const reindexEvents = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/rag/events/reindex`, { method: 'POST' })
      const r = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof r.detail === 'string' ? r.detail : t('error_generic'))
      return r
    },
    onSuccess: (d) => { refetchStatus(); alert(t('set_evt_added', { n: d.chunks_added })) },
    onError: (e) => alert(e instanceof Error ? e.message : t('error_generic')),
  })
  const reindexKnowledge = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/rag/knowledge/reindex`, { method: 'POST' })
      const r = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof r.detail === 'string' ? r.detail : t('error_generic'))
      return r
    },
    onSuccess: (d) => {
      refetchStatus()
      if (!d.chunks_added) {
        alert(t('set_kb_empty'))
      } else {
        alert(t('set_kb_indexed', { n: d.chunks_added }))
      }
    },
    onError: (e) => alert(e instanceof Error ? e.message : t('error_generic')),
  })
  const reindexAll = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/rag/reindex-all`, { method: 'POST' })
      const r = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof r.detail === 'string' ? r.detail : t('set_reindex_err'))
      return r
    },
    onSuccess: (d) => {
      refetchStatus()
      const c = d.chunks || {}
      alert(t('set_rag_refreshed', { metrics: c.metrics ?? 0, incidents: c.incidents ?? 0, events: c.events ?? 0, knowledge: c.knowledge ?? 0, total: d.total ?? 0 }))
    },
    onError: (e) => alert(e instanceof Error ? e.message : t('error_generic')),
  })
  const { data: runbookDocsData, refetch: refetchRunbookDocs } = useQuery<{ success: boolean; documents: RunbookDocument[] }>({
    queryKey: ['rag-runbook-documents'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/rag/runbook/documents`)
      if (!res.ok) {
        const r = await res.json().catch(() => ({}))
        throw new Error(r.detail || `HTTP ${res.status}`)
      }
      return res.json()
    }
  })
  const searchRunbook = useMutation({
    mutationFn: async (query: string) => {
      const q = query.trim()
      if (!q) throw new Error(t('set_rb_search_empty'))
      const res = await fetch(`${API_BASE_URL}/rag/runbook/search?q=${encodeURIComponent(q)}&limit=8`)
      const r = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof r.detail === 'string' ? r.detail : t('set_rb_search_err'))
      return r as { success: boolean; hits: RunbookSearchHit[]; mode?: string }
    },
    onSuccess: (d) => { setRbHits(d.hits || []); setRbSearchErr(null) },
    onError: (e) => {
      setRbHits(null)
      setRbSearchErr(e instanceof Error ? e.message : t('set_rb_search_err'))
    },
  })
  const deleteRunbookDoc = useMutation({
    mutationFn: async (title: string) => {
      const res = await fetch(`${API_BASE_URL}/rag/runbook/documents?title=${encodeURIComponent(title)}`, { method: 'DELETE' })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || t('delete_failed'))
      return r
    },
    onSuccess: (d) => { refetchStatus(); refetchRunbookDocs(); alert(t('set_doc_deleted', { title: d.title, n: d.deleted_chunks })) },
    onError: (e) => alert(e instanceof Error ? e.message : t('set_del_err'))
  })
  type RunbookCandidateRow = {
    id: number
    incident_id: number | null
    title: string
    content: string
    status: string
    created_at: string | null
  }
  const { data: candidatesData, refetch: refetchCandidates } = useQuery<{ success: boolean; candidates: RunbookCandidateRow[] }>({
    queryKey: ['rag-runbook-candidates'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/rag/runbook/candidates?status=pending`)
      if (!res.ok) return { success: false, candidates: [] }
      return res.json()
    },
    refetchInterval: 60000,
  })
  const approveCandidate = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${API_BASE_URL}/rag/runbook/candidates/${id}/approve`, { method: 'POST' })
      const r = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof r.detail === 'string' ? r.detail : t('set_approve_fail'))
      return r
    },
    onSuccess: (d) => {
      refetchCandidates()
      refetchRunbookDocs()
      refetchStatus()
      alert(t('set_rb_added', { n: d.chunks_added ?? 0 }))
    },
    onError: (e) => alert(e instanceof Error ? e.message : t('error_generic')),
  })
  const rejectCandidate = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${API_BASE_URL}/rag/runbook/candidates/${id}/reject`, { method: 'POST' })
      const r = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof r.detail === 'string' ? r.detail : t('set_reject_fail'))
      return r
    },
    onSuccess: () => refetchCandidates(),
    onError: (e) => alert(e instanceof Error ? e.message : t('error_generic')),
  })
  const candidates = candidatesData?.candidates ?? []
  const runbookDocs = runbookDocsData?.documents ?? []
  const src = status?.sources
  return (
    <div>
      <h2 className="text-xl font-semibold text-white mb-2">{t('set_rag_title')}</h2>
      <p className="text-slate-400 text-sm mb-6">{t('set_rag_intro')}</p>

      {(statusError || statusIsError) && (
        <div className="mb-4 p-3 rounded-lg border border-red-500/40 bg-red-500/10 text-red-300 text-sm">
          {t('set_rag_status_fail', { msg: statusError || (statusQueryError as Error)?.message || t('unknown_err_lc') })}
        </div>
      )}

      {/* PDF Ekle - en üstte, belirgin */}
      <div className="mb-6 p-5 bg-cyber-deep/70 rounded-xl border-2 border-emerald-500/40">
        <h3 className="text-base font-semibold text-white mb-1 flex items-center gap-2">
          {t('set_pdf_add')}
        </h3>
        <p className="text-slate-400 text-xs mb-4">{t('set_pdf_hint')}</p>
        <div className="flex flex-wrap items-end gap-4">
          <div className="min-w-[200px]">
            <label className="block text-xs font-medium text-slate-400 mb-1">{t('set_pdf_file')}</label>
            <input
              type="file"
              accept=".pdf"
              onChange={(e) => setPdfFile(e.target.files?.[0] || null)}
              className="block w-full text-sm text-slate-300 file:mr-3 file:py-2 file:px-4 file:rounded-lg file:border-0 file:bg-emerald-600 file:text-white file:font-medium"
            />
          </div>
          <div>
            <label className="block text-xs font-medium text-slate-400 mb-1">{t('set_title_opt')}</label>
            <input
              type="text"
              value={pdfTitle}
              onChange={(e) => setPdfTitle(e.target.value)}
              placeholder={t('set_filename_used')}
              className="w-52 bg-cyber-card border border-slate-600 rounded-lg px-3 py-2 text-white text-sm placeholder-slate-500"
            />
          </div>
          <button
            onClick={() => uploadPdf.mutate()}
            disabled={!pdfFile || uploadPdf.isPending}
            className="px-5 py-2.5 bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white rounded-lg text-sm font-semibold shadow-lg shadow-emerald-500/20"
          >
            {uploadPdf.isPending ? t('set_adding_pdf') : t('set_add_pdf_rag')}
          </button>
        </div>
        {pdfFile && <p className="text-emerald-400 text-xs mt-2">{t('set_selected_file', { name: pdfFile.name })}</p>}
        {uploadPdf.isPending && (
          <p className="text-amber-400/90 text-xs mt-2">{t('set_embed_wait')}</p>
        )}
      </div>

      {/* Eklenen runbook dokümanları */}
      <div className="mb-6 p-5 bg-cyber-deep/50 rounded-xl border border-white/[0.06]">
        <h3 className="text-base font-semibold text-white mb-3 flex items-center gap-2">
          {t('set_rb_docs')}
          {runbookDocs.length > 0 && (
            <span className="text-xs font-normal text-slate-500">{t('set_rb_doc_count', { n: runbookDocs.length })}</span>
          )}
        </h3>
        <div className="flex flex-wrap items-center gap-2 mb-4">
          <input
            type="search"
            value={rbQuery}
            onChange={(e) => setRbQuery(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') searchRunbook.mutate(rbQuery) }}
            placeholder={t('set_rb_search_ph')}
            className="flex-1 min-w-[200px] bg-cyber-card border border-slate-600 focus:border-blue-500 focus:ring-1 focus:ring-blue-500/40 rounded-lg px-3 py-2 text-white text-sm placeholder-slate-500 outline-none"
          />
          <button
            type="button"
            onClick={() => searchRunbook.mutate(rbQuery)}
            disabled={searchRunbook.isPending || !rbQuery.trim()}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium inline-flex items-center gap-2"
          >
            <Search size={16} strokeWidth={2} />
            {searchRunbook.isPending ? t('set_rb_searching') : t('set_rb_search')}
          </button>
        </div>
        {rbSearchErr && (
          <p className="text-red-400 text-xs mb-3">{rbSearchErr}</p>
        )}
        {rbHits !== null && (
          <div className="space-y-2 mb-4">
            {rbHits.length === 0 ? (
              <p className="text-slate-500 text-sm">{t('set_rb_no_hits')}</p>
            ) : (
              rbHits.map((h, i) => (
                <div key={h.id || `${h.title}-${i}`} className="rounded-lg border border-white/[0.08] bg-cyber-card/70 p-3">
                  <div className="text-emerald-400 text-xs font-medium mb-1.5 truncate">
                    {h.title}
                    {h.page != null && h.page > 0 ? ` s.${h.page}` : ''}
                    {' · '}
                    {t('set_rb_similarity', { score: Number(h.similarity || 0).toFixed(3) })}
                  </div>
                  <p className="text-slate-300 text-sm leading-relaxed whitespace-pre-wrap">{h.snippet}</p>
                </div>
              ))
            )}
          </div>
        )}
        {runbookDocs.length === 0 ? (
          <p className="text-slate-500 text-sm">{t('set_rb_none')}</p>
        ) : (
          <ul className="space-y-2 overflow-y-auto pr-1" style={{ maxHeight: '16.5rem' }}>
            {runbookDocs.map((doc) => (
              <li
                key={doc.title}
                className="flex items-center justify-between py-2 px-3 rounded-lg bg-cyber-card/50 border border-white/[0.06]"
              >
                <span className="text-white font-medium truncate flex-1 mr-3">{doc.title}</span>
                <span className="text-slate-400 text-sm whitespace-nowrap">{doc.chunk_count} chunk</span>
                <button
                  type="button"
                  onClick={async () => { if (await showConfirm(t('set_del_quoted', { name: doc.title }))) deleteRunbookDoc.mutate(doc.title) }}
                  disabled={deleteRunbookDoc.isPending}
                  className="ml-3 px-3 py-1.5 text-xs bg-red-600/20 text-red-400 border border-red-500/40 rounded-lg hover:bg-red-600/30 disabled:opacity-50"
                >
                  {t('delete')}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Runbook adayları (resolved incident → admin onayı) */}
      <div className="mb-6 p-5 bg-cyber-deep/50 rounded-xl border border-amber-500/25">
        <h3 className="text-base font-semibold text-white mb-1">{t('set_rb_cands')}</h3>
        <p className="text-slate-500 text-xs mb-3">{t('set_rb_cands_hint')}</p>
        {candidates.length === 0 ? (
          <p className="text-slate-500 text-sm">{t('set_no_cands')}</p>
        ) : (
          <ul className="space-y-3">
            {candidates.map((c) => (
              <li key={c.id} className="p-3 rounded-lg bg-cyber-card/50 border border-white/[0.06]">
                <div className="flex flex-wrap items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-white text-sm font-medium truncate">{c.title}</div>
                    <div className="text-[11px] text-slate-500 mt-0.5">
                      {t('set_incident_n', { id: c.incident_id ?? '—' })} · {c.created_at ? new Date(c.created_at).toLocaleString(dateLoc) : ''}
                    </div>
                    <pre className="mt-2 text-[11px] text-slate-400 whitespace-pre-wrap max-h-28 overflow-y-auto font-mono">
                      {(c.content || '').slice(0, 600)}
                      {(c.content || '').length > 600 ? '…' : ''}
                    </pre>
                  </div>
                  <div className="flex gap-2 shrink-0">
                    <button
                      type="button"
                      disabled={approveCandidate.isPending || rejectCandidate.isPending}
                      onClick={() => approveCandidate.mutate(c.id)}
                      className="px-3 py-1.5 text-xs bg-emerald-600/80 hover:bg-emerald-500 text-white rounded-lg disabled:opacity-50"
                    >
                      {t('confirm_ok')}
                    </button>
                    <button
                      type="button"
                      disabled={approveCandidate.isPending || rejectCandidate.isPending}
                      onClick={() => rejectCandidate.mutate(c.id)}
                      className="px-3 py-1.5 text-xs bg-white/[0.06] hover:bg-white/[0.1] text-slate-300 rounded-lg border border-white/[0.08] disabled:opacity-50"
                    >
                      {t('reject')}
                    </button>
                  </div>
                </div>
              </li>
            ))}
          </ul>
        )}
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-4">
        <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4">
          <p className="text-slate-400 text-sm">Runbook</p>
          <p className="text-2xl font-semibold text-white">{status?.runbook ?? '—'} <span className="text-sm font-normal text-slate-500">chunk</span></p>
        </div>
        <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4">
          <p className="text-slate-400 text-sm">Incidents / Events</p>
          <p className="text-2xl font-semibold text-white">{status?.incidents ?? '—'} <span className="text-sm font-normal text-slate-500">{t('records')}</span></p>
          {src && <p className="text-[10px] text-slate-500 mt-1">DB: {src.incidents_db ?? 0} inc · {src.events_db ?? 0} evt</p>}
        </div>
        <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4">
          <p className="text-slate-400 text-sm">{t('set_metrics_desc')}</p>
          <p className="text-2xl font-semibold text-white">{status?.metrics ?? '—'} <span className="text-sm font-normal text-slate-500">{t('set_metrics_unit')}</span></p>
          {src && <p className="text-[10px] text-slate-500 mt-1">{t('set_default_list', { n: src.default_metrics ?? 0 })}</p>}
        </div>
        <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4">
          <p className="text-slate-400 text-sm">{t('set_kb')}</p>
          <p className="text-2xl font-semibold text-white">{status?.knowledge ?? '—'} <span className="text-sm font-normal text-slate-500">chunk</span></p>
          {src && <p className="text-[10px] text-slate-500 mt-1">facts {src.learned_facts_db ?? 0} · inv {src.linux_inventory_db ?? 0}</p>}
        </div>
      </div>
      {status?.embedding && !status.embedding.ok && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-sm text-rose-100/90">
          <p className="font-medium text-rose-200">{t('set_embed_down')}</p>
          <p className="text-xs text-rose-100/80 mt-1 break-words">
            {status.embedding.error || t('set_embed_noresp')}
          </p>
          <p className="text-xs text-rose-100/60 mt-2">
            {t('set_target')} <code className="bg-cyber-card px-1 rounded">{status.embedding.base_url}</code>
            {' · '}model: <code className="bg-cyber-card px-1 rounded">{status.embedding.model}</code>
          </p>
          {status.embedding.hint && (
            <p className="text-[11px] text-rose-100/50 mt-2 whitespace-pre-wrap">{status.embedding.hint}</p>
          )}
        </div>
      )}
      {status?.embedding?.ok && (
        <div className="mb-4 px-4 py-3 rounded-xl bg-sky-500/10 border border-sky-500/25 text-sm text-sky-100/90">
          <p className="font-medium text-sky-200">{t('set_embed_ok')}</p>
          <p className="text-xs text-sky-200/70 mt-1">
            {status.embedding.base_url} · {status.embedding.model}
            {status.embedding.dim ? ` · ${status.embedding.dim} dim` : ''}
            {status.embedding.model_present === false ? t('set_model_missing') : ''}
          </p>
        </div>
      )}
      <div className="mb-4 px-4 py-3 rounded-xl bg-emerald-500/10 border border-emerald-500/25 text-sm text-emerald-100/90">
        <p className="font-medium text-emerald-200">{t('set_autosync')}</p>
        <p className="text-xs text-emerald-200/70 mt-1">{t('set_autosync_hint')}</p>
      </div>

      <div className="flex flex-wrap gap-2 mb-3">
        <button onClick={() => reindexAll.mutate()} disabled={reindexAll.isPending}
          className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white rounded-lg text-sm font-semibold">
          {reindexAll.isPending ? t('set_refreshing_long') : t('set_refresh_all')}
        </button>
        {(status?.metrics ?? 0) === 0 && (
          <button onClick={() => seedMetrics.mutate()} disabled={seedMetrics.isPending}
            className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium">
            {seedMetrics.isPending ? t('set_adding') : t('set_seed_first')}
          </button>
        )}
      </div>

      <details className="mb-6 group">
        <summary className="cursor-pointer text-xs text-slate-500 hover:text-slate-300 list-none flex items-center gap-2">
          <span className="underline-offset-2 group-open:underline">{t('set_adv_index')}</span>
          <span className="text-slate-600">{t('set_usually_unneeded')}</span>
        </summary>
        <div className="flex flex-wrap gap-2 mt-3">
          <button onClick={() => seedMetrics.mutate()} disabled={seedMetrics.isPending}
            className="px-3 py-1.5 bg-slate-700/80 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg text-xs">
            {seedMetrics.isPending ? t('set_adding') : t('set_metrics_desc')}
          </button>
          <button onClick={() => reindexIncidents.mutate()} disabled={reindexIncidents.isPending}
            className="px-3 py-1.5 bg-slate-700/80 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg text-xs">
            {reindexIncidents.isPending ? t('indexing') : t('set_incidents')}
          </button>
          <button onClick={() => reindexEvents.mutate()} disabled={reindexEvents.isPending}
            className="px-3 py-1.5 bg-slate-700/80 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg text-xs">
            {reindexEvents.isPending ? t('indexing') : t('set_events')}
          </button>
          <button onClick={() => reindexKnowledge.mutate()} disabled={reindexKnowledge.isPending}
            className="px-3 py-1.5 bg-slate-700/80 hover:bg-slate-600 disabled:opacity-50 text-slate-200 rounded-lg text-xs">
            {reindexKnowledge.isPending ? t('indexing') : t('set_kb')}
          </button>
        </div>
      </details>

      <div className="mt-2 bg-cyber-deep/30 rounded-[10px] border border-white/[0.06] p-4">
        <h4 className="text-sm font-medium text-slate-300 mb-2">{t('set_auto_manual')}</h4>
        <ul className="text-xs text-slate-500 space-y-1">
          <li>• <strong>{t('set_auto')}</strong> {t('set_auto_body')}</li>
          <li>• <strong>{t('set_manual_pdf')}</strong> {t('set_manual_pdf_body')}</li>
          <li>• <strong>{t('set_manual_rare')}</strong> {t('set_manual_rare_body')}</li>
          <li>• {t('set_embed_need')}</li>
        </ul>
      </div>
      {confirmState && <ConfirmModal message={confirmState.msg} onConfirm={() => { confirmState.resolve(true); setConfirmState(null) }} onCancel={() => { confirmState.resolve(false); setConfirmState(null) }} />}
    </div>
  )
}

interface WipeCategory {
  id: string
  label: string
  tables: Record<string, number>
  total_rows: number
}

interface WipePreview {
  categories: WipeCategory[]
  total_rows: number
  preserved: string[]
}

const WIPE_CONFIRM_PHRASE = 'TÜM VERİLERİ SİL'

/** Eski ortam → yeni ortam yapılandırma taşıma */
const ConfigBackupTab: React.FC = () => {
  const t = useT()
  const [busy, setBusy] = useState(false)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [includeSecrets, setIncludeSecrets] = useState(true)
  const [applySettings, setApplySettings] = useState(true)
  const [applyCredentials, setApplyCredentials] = useState(true)
  const [applyModules, setApplyModules] = useState(true)
  const [forceHostKeys, setForceHostKeys] = useState(false)
  const [envHints, setEnvHints] = useState<Record<string, string> | null>(null)
  const fileRef = React.useRef<HTMLInputElement>(null)

  const downloadBackup = async () => {
    setBusy(true); setErr(null); setMsg(null)
    try {
      const res = await fetch(`${API_BASE_URL}/settings/config/backup?include_secrets=${includeSecrets ? 'true' : 'false'}`)
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`)
      const blob = new Blob([JSON.stringify(body, null, 2)], { type: 'application/json' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      const stamp = new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')
      a.href = url
      a.download = `ainew-config-backup-${stamp}.json`
      a.click()
      URL.revokeObjectURL(url)
      setMsg(`Yedek indirildi (${Object.keys(body.app_settings || {}).length} ayar, ${(body.credentials || []).length} credential).`)
      if (body.env_hints) setEnvHints(body.env_hints)
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('set_backup_fail'))
    } finally {
      setBusy(false)
    }
  }

  const restoreFromFile = async (file: File) => {
    setBusy(true); setErr(null); setMsg(null)
    try {
      const text = await file.text()
      const payload = JSON.parse(text)
      const res = await fetch(`${API_BASE_URL}/settings/config/restore`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          ...payload,
          apply_settings: applySettings,
          apply_credentials: applyCredentials,
          apply_modules: applyModules,
          force_host_keys: forceHostKeys,
        }),
      })
      const body = await res.json().catch(() => ({}))
      if (!res.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${res.status}`)
      setMsg(body.message || t('set_restore_done'))
      if (body.env_hints && Object.keys(body.env_hints).length) setEnvHints(body.env_hints)
      else if (payload.env_hints) setEnvHints(payload.env_hints)
      if (body.stats?.warnings?.length) {
        setErr(t('set_warnings', { msg: (body.stats.warnings as string[]).slice(0, 8).join(' · ') }))
      }
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('set_restore_fail'))
    } finally {
      setBusy(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div>
      <h2 className="text-xl font-semibold text-white mb-2">{t('set_cfg_backup')}</h2>
      <p className="text-sm text-slate-400 mb-6 max-w-3xl">{t('set_cfg_intro')}</p>

      <div className="grid md:grid-cols-2 gap-4 mb-6">
        <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-5">
          <h3 className="text-sm font-semibold text-cyan-300 mb-3">{t('set_old_env')}</h3>
          <label className="flex items-center gap-2 text-xs text-slate-400 mb-4 cursor-pointer">
            <input type="checkbox" checked={includeSecrets} onChange={e => setIncludeSecrets(e.target.checked)}
              className="rounded border-slate-600" />
            {t('set_include_keys')}
          </label>
          <button type="button" disabled={busy} onClick={downloadBackup}
            className="px-4 py-2 bg-cyan-600 hover:bg-cyan-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium">
            {busy ? t('set_preparing') : t('set_dl_json')}
          </button>
        </div>

        <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-5">
          <h3 className="text-sm font-semibold text-amber-300 mb-3">{t('set_new_env')}</h3>
          <div className="space-y-2 text-xs text-slate-400 mb-4">
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={applySettings} onChange={e => setApplySettings(e.target.checked)} />
              {t('set_app_settings')}
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={applyCredentials} onChange={e => setApplyCredentials(e.target.checked)} />
              {t('set_ssh_creds')}
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={applyModules} onChange={e => setApplyModules(e.target.checked)} />
              {t('set_user_mods')}
            </label>
            <label className="flex items-center gap-2 cursor-pointer">
              <input type="checkbox" checked={forceHostKeys} onChange={e => setForceHostKeys(e.target.checked)} />
              {t('set_host_fields')}
            </label>
          </div>
          <input ref={fileRef} type="file" accept="application/json,.json" className="hidden"
            onChange={e => { const f = e.target.files?.[0]; if (f) restoreFromFile(f) }} />
          <button type="button" disabled={busy} onClick={() => fileRef.current?.click()}
            className="px-4 py-2 bg-amber-600 hover:bg-amber-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium">
            {busy ? t('loading') : t('set_pick_json')}
          </button>
        </div>
      </div>

      {msg && (
        <div className="mb-3 px-4 py-3 rounded-xl bg-emerald-500/10 border border-emerald-500/25 text-sm text-emerald-100">{msg}</div>
      )}
      {err && (
        <div className="mb-3 px-4 py-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-sm text-rose-100">{err}</div>
      )}

      {envHints && (
        <div className="bg-cyber-deep/40 rounded-[10px] border border-white/[0.06] p-4">
          <h4 className="text-sm font-medium text-slate-300 mb-2">{t('set_env_notes')}</h4>
          <p className="text-xs text-slate-500 mb-3">{t('set_env_hint')}</p>
          <pre className="text-[11px] text-slate-400 overflow-x-auto whitespace-pre-wrap font-mono bg-black/30 rounded-lg p-3">
{Object.entries(envHints)
  .filter(([k]) => !k.startsWith('_'))
  .map(([k, v]) => `${k}=${v}`)
  .join('\n')}
          </pre>
        </div>
      )}

      <ul className="mt-6 text-xs text-slate-500 space-y-1 list-disc list-inside">
        <li>{t('set_no_inv_json')}</li>
        <li>{t('set_mod_skip')}</li>
        <li>{t('set_use_plat_upd')}</li>
        <li>{t('set_db_secret')}</li>
      </ul>

      <div className="my-8 border-t border-white/[0.08]" />

      <DbBackupSection />
    </div>
  )
}

/** Tam PostgreSQL dump (ainew + Dropt) — Settings üzerinden taşıma */
const DbBackupSection: React.FC = () => {
  const t = useT()
  const [busy, setBusy] = useState(false)
  const [busyPhase, setBusyPhase] = useState<string | null>(null)
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [includeDropt, setIncludeDropt] = useState(true)
  const [includeSecretsInZip, setIncludeSecretsInZip] = useState(true)
  const [restoreAinew, setRestoreAinew] = useState(true)
  const [restoreDropt, setRestoreDropt] = useState(true)
  const [requireFp, setRequireFp] = useState(true)
  const [applySecrets, setApplySecrets] = useState(true)
  const [confirm, setConfirm] = useState('')
  const [preview, setPreview] = useState<any>(null)
  const [pendingFile, setPendingFile] = useState<File | null>(null)
  const [secretExportConfirm, setSecretExportConfirm] = useState('')
  const [includeDbPasswords, setIncludeDbPasswords] = useState(true)
  const fileRef = React.useRef<HTMLInputElement>(null)

  const { data: cap } = useQuery({
    queryKey: ['db-backup-capability'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/settings/db-backup/capability`)
      if (!r.ok) throw new Error(t('set_cap_fail'))
      return r.json()
    },
  })

  const { data: migSecrets, refetch: refetchMigSecrets } = useQuery({
    queryKey: ['db-backup-migration-secrets'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/settings/db-backup/migration-secrets`)
      if (!r.ok) throw new Error(t('set_secret_sum_fail'))
      return r.json()
    },
  })

  const downloadDb = async () => {
    setBusy(true); setBusyPhase(t('set_db_prep')); setErr(null); setMsg(null)
    try {
      const r = await fetch(`${API_BASE_URL}/settings/db-backup/export?include_dropt=${includeDropt ? 'true' : 'false'}&include_migration_secrets=${includeSecretsInZip ? 'true' : 'false'}`)
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${r.status}`)
      }
      setBusyPhase(t('set_downloading'))
      const blob = await r.blob()
      const cd = r.headers.get('Content-Disposition') || ''
      const m = /filename="?([^";]+)"?/i.exec(cd)
      const name = m?.[1] || `ainew-db-backup-${new Date().toISOString().slice(0, 19).replace(/[:T]/g, '-')}.zip`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = name
      a.click()
      URL.revokeObjectURL(url)
      setMsg(t('set_db_dl', { name }))
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('set_backup_fail'))
    } finally {
      setBusy(false); setBusyPhase(null)
    }
  }

  const downloadMigrationSecrets = async () => {
    setBusy(true); setBusyPhase(t('set_mig_prep')); setErr(null); setMsg(null)
    try {
      const phrase = migSecrets?.export_confirm_phrase || 'TASIMA SIRLARINI INDIR'
      const q = new URLSearchParams({
        confirm: secretExportConfirm,
        include_db_passwords: includeDbPasswords ? 'true' : 'false',
      })
      const r = await fetch(`${API_BASE_URL}/settings/db-backup/migration-secrets/export?${q}`)
      if (!r.ok) {
        const body = await r.json().catch(() => ({}))
        throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${r.status}`)
      }
      const blob = await r.blob()
      const cd = r.headers.get('Content-Disposition') || ''
      const m = /filename="?([^";]+)"?/i.exec(cd)
      const name = m?.[1] || `ainew-migrate-secrets.env`
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = name
      a.click()
      URL.revokeObjectURL(url)
      setMsg(t('set_mig_dl', { name }))
      setSecretExportConfirm('')
      refetchMigSecrets()
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('set_secret_export_fail'))
    } finally {
      setBusy(false); setBusyPhase(null)
    }
  }

  const validateFile = async (file: File) => {
    setBusy(true); setBusyPhase(t('set_validating')); setErr(null); setMsg(null); setPreview(null)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const r = await fetch(`${API_BASE_URL}/settings/db-backup/validate`, { method: 'POST', body: fd })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${r.status}`)
      setPreview(body)
      setPendingFile(file)
      setMsg(t('set_validated', { name: file.name }))
    } catch (e) {
      setPendingFile(null)
      setErr(e instanceof Error ? e.message : t('set_validate_fail'))
    } finally {
      setBusy(false); setBusyPhase(null)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const runRestore = async (file?: File | null) => {
    const f = file ?? pendingFile
    if (!f) {
      setErr(t('set_pick_first'))
      return
    }
    if (confirm !== phrase) {
      setErr(t('set_type_confirm', { phrase }))
      return
    }
    setBusy(true)
    setBusyPhase(
      applySecrets
        ? t('set_restore_secrets')
        : t('set_restore_db'),
    )
    setErr(null); setMsg(null)
    try {
      const fd = new FormData()
      fd.append('file', f)
      fd.append('confirm', confirm)
      fd.append('restore_ainew', restoreAinew ? 'true' : 'false')
      fd.append('restore_dropt', restoreDropt ? 'true' : 'false')
      fd.append('require_fingerprint_match', requireFp ? 'true' : 'false')
      fd.append('apply_migration_secrets', applySecrets ? 'true' : 'false')
      const r = await fetch(`${API_BASE_URL}/settings/db-backup/restore`, { method: 'POST', body: fd })
      const body = await r.json().catch(() => ({}))
      if (!r.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `HTTP ${r.status}`)
      setBusyPhase(t('set_done_phase'))
      setMsg(body.message || t('set_restore_done'))
      setPreview(null)
      setPendingFile(null)
      setConfirm('')
    } catch (e) {
      setErr(e instanceof Error ? e.message : t('set_restore_fail'))
    } finally {
      setBusy(false); setBusyPhase(null)
    }
  }

  const phrase = cap?.restore_confirm_phrase || 'VERITABANI GERI YUKLE'
  const secretPhrase = migSecrets?.export_confirm_phrase || 'TASIMA SIRLARINI INDIR'
  const installHint = migSecrets?.install_dir_hint || '/data'

  return (
    <div>
      <h2 className="text-xl font-semibold text-white mb-2">{t('set_db_title')}</h2>
      <p className="text-sm text-slate-400 mb-4 max-w-3xl">{t('set_db_intro')}</p>

      {cap && !cap.available && (
        <div className="mb-4 rounded-[10px] border border-amber-500/30 bg-amber-500/10 px-4 py-3 text-sm text-amber-100">
          {t('set_backup_unavail', { reasons: (cap.reasons || []).join(' · ') || t('unknown_reason') })}
        </div>
      )}

      <div className="mb-4 rounded-[10px] border border-violet-500/25 bg-violet-500/5 p-5">
        <div className="flex flex-wrap items-start justify-between gap-3 mb-3">
          <div>
            <h3 className="text-sm font-semibold text-violet-200">{t('set_mig_secrets')}</h3>
            <p className="text-xs text-slate-500 mt-1 max-w-2xl">{t('set_mig_hint')}</p>
          </div>
          <button
            type="button"
            onClick={() => refetchMigSecrets()}
            className="text-xs px-2.5 py-1.5 rounded-lg border border-white/[0.08] text-slate-300 hover:bg-white/[0.04]"
          >
            {t('refresh_action')}
          </button>
        </div>

        {migSecrets && (
          <>
            <div className="flex flex-wrap gap-2 mb-3 text-[11px]">
              <span className={`px-2 py-1 rounded border ${migSecrets.ready_for_full_migrate ? 'border-emerald-500/40 text-emerald-300 bg-emerald-500/10' : 'border-amber-500/40 text-amber-200 bg-amber-500/10'}`}>
                {migSecrets.ready_for_full_migrate ? t('set_ready_migrate') : t('set_missing_req')}
              </span>
              <span className={`px-2 py-1 rounded border ${migSecrets.bridge_match ? 'border-emerald-500/30 text-emerald-300/90' : 'border-amber-500/30 text-amber-200'}`}>
                {migSecrets.bridge_match ? t('set_bridge_ok') : t('set_bridge_bad')}
              </span>
            </div>
            <div className="overflow-x-auto mb-3">
              <table className="w-full text-[11px] text-left text-slate-300">
                <thead className="text-slate-500 border-b border-white/[0.06]">
                  <tr>
                    <th className="py-1.5 pr-3 font-medium">{t('set_col_key')}</th>
                    <th className="py-1.5 pr-3 font-medium">{t('set_col_target')}</th>
                    <th className="py-1.5 pr-3 font-medium">{t('set_col_st')}</th>
                    <th className="py-1.5 font-medium font-mono">Fingerprint</th>
                  </tr>
                </thead>
                <tbody>
                  {(migSecrets.keys || []).map((row: any, i: number) => (
                    <tr key={`${row.key}-${row.target_file}-${i}`} className="border-b border-white/[0.04]">
                      <td className="py-1.5 pr-3 font-mono text-slate-200">
                        {row.key}
                        {row.required && <span className="text-rose-300/80 ml-1">*</span>}
                      </td>
                      <td className="py-1.5 pr-3 text-slate-400 font-mono">{row.target_file}</td>
                      <td className="py-1.5 pr-3">
                        {row.present
                          ? <span className="text-emerald-400">{t('set_present')}</span>
                          : <span className="text-amber-300">{t('set_absent')}</span>}
                      </td>
                      <td className="py-1.5 font-mono text-slate-400">{row.fingerprint}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            {(migSecrets.missing_required || []).length > 0 && (
              <p className="text-[11px] text-amber-200/90 mb-3">
                {t('set_missing', { list: (migSecrets.missing_required || []).join(' · ') })}
              </p>
            )}
            <p className="text-[11px] text-slate-500 mb-3">{t('set_do_not_copy', { list: (migSecrets.do_not_copy || []).join(', ') })}</p>
          </>
        )}

        <label className="flex items-center gap-2 text-xs text-slate-400 mb-2 cursor-pointer">
          <input type="checkbox" checked={includeDbPasswords} onChange={e => setIncludeDbPasswords(e.target.checked)}
            className="rounded border-slate-600" />
          {t('set_incl_db_pw')}
        </label>
        <input
          value={secretExportConfirm}
          onChange={e => setSecretExportConfirm(e.target.value)}
          placeholder={secretPhrase}
          className="w-full mb-2 px-3 py-2 rounded-lg bg-black/30 border border-white/[0.08] text-sm text-white font-mono"
        />
        <button
          type="button"
          disabled={busy || secretExportConfirm !== secretPhrase}
          onClick={downloadMigrationSecrets}
          className="px-4 py-2 rounded-lg text-sm bg-violet-600/80 hover:bg-violet-600 text-white disabled:opacity-40"
        >
          {busy ? t('set_preparing') : t('set_dl_mig_env')}
        </button>
        <p className="text-[10px] text-slate-600 mt-2">{t('set_confirm_audit', { phrase: secretPhrase })}</p>
      </div>

      <div className="grid md:grid-cols-2 gap-4 mb-4">
        <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-5">
          <h3 className="text-sm font-semibold text-cyan-300 mb-3">{t('set_export')}</h3>
          <label className="flex items-center gap-2 text-xs text-slate-400 mb-2 cursor-pointer">
            <input type="checkbox" checked={includeDropt} onChange={e => setIncludeDropt(e.target.checked)}
              className="rounded border-slate-600" disabled={!cap?.dropt_db_present} />
            {t('set_incl_dropt')}
            {!cap?.dropt_db_present && <span className="text-slate-600">{t('set_no_container')}</span>}
          </label>
          <label className="flex items-center gap-2 text-xs text-slate-400 mb-4 cursor-pointer">
            <input type="checkbox" checked={includeSecretsInZip} onChange={e => setIncludeSecretsInZip(e.target.checked)}
              className="rounded border-slate-600" />
            {t('set_incl_secrets_zip')}
          </label>
          <button type="button" disabled={busy || !cap?.available} onClick={downloadDb}
            className="px-4 py-2 rounded-lg text-sm bg-gradient-to-r from-blue-600 to-blue-700 text-white disabled:opacity-50">
            {busy ? t('set_preparing') : t('set_dl_zip')}
          </button>
          <p className="text-[11px] text-slate-500 mt-3">
            {t('set_fingerprint')} <code className="text-slate-400 font-mono">{cap?.secret_key_fingerprint || migSecrets?.secret_key_fingerprint || '—'}</code>
            {' · '}{t('set_version', { v: cap?.app_version || '—' })}
          </p>
        </div>

        <div className="bg-cyber-deep/50 rounded-[10px] border border-rose-500/20 p-5">
          <h3 className="text-sm font-semibold text-rose-300 mb-2">{t('set_import')}</h3>
          <p className="text-xs text-slate-500 mb-3">{t('set_import_hint')}</p>
          <div className="flex flex-wrap gap-3 mb-3 text-xs text-slate-400">
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={restoreAinew} onChange={e => setRestoreAinew(e.target.checked)} /> ainew DB
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={restoreDropt} onChange={e => setRestoreDropt(e.target.checked)} /> Dropt DB
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={applySecrets} onChange={e => setApplySecrets(e.target.checked)} /> {t('set_write_secrets')}
            </label>
            <label className="flex items-center gap-1.5 cursor-pointer">
              <input type="checkbox" checked={requireFp} onChange={e => setRequireFp(e.target.checked)} /> {t('set_require_fp')}
            </label>
          </div>
          <input
            value={confirm}
            onChange={e => setConfirm(e.target.value)}
            placeholder={phrase}
            className="w-full mb-3 px-3 py-2 rounded-lg bg-black/30 border border-white/[0.08] text-sm text-white font-mono"
          />
          <div className="flex flex-wrap gap-2">
            <button type="button" disabled={busy}
              onClick={() => fileRef.current?.click()}
              className="px-3 py-2 rounded-lg text-sm bg-white/[0.06] border border-white/[0.08] text-slate-200 disabled:opacity-50">
              {t('set_pick_validate')}
            </button>
            <button
              type="button"
              disabled={busy || confirm !== phrase || !pendingFile}
              onClick={() => runRestore()}
              className={`px-3 py-2 rounded-lg text-sm border ${
                confirm === phrase && pendingFile && !busy
                  ? 'bg-rose-600/30 border-rose-500/40 text-rose-100 hover:bg-rose-600/40'
                  : 'opacity-40 border-white/[0.06] text-slate-500'
              }`}
              title={!pendingFile ? t('set_pick_file_first') : confirm !== phrase ? t('set_confirm_colon', { phrase }) : t('set_start_restore')}
            >
              {t('set_restore')}
            </button>
          </div>
          {pendingFile && (
            <p className="text-[11px] text-slate-500 mt-2">
              {t('set_selected_file_name', { name: pendingFile.name, size: (pendingFile.size / (1024 * 1024)).toFixed(1) })}
            </p>
          )}
          <input ref={fileRef} type="file" accept=".zip,application/zip" className="hidden"
            onChange={e => {
              const f = e.target.files?.[0]
              if (f) validateFile(f)
            }}
          />
        </div>
      </div>

      {busy && busyPhase && (
        <div className="mb-3 rounded-[10px] border border-sky-500/30 bg-sky-500/10 p-4">
          <div className="flex items-center gap-3 mb-2">
            <div className="w-4 h-4 border-2 border-sky-400 border-t-transparent rounded-full animate-spin flex-shrink-0" />
            <div className="text-sm text-sky-100">{busyPhase}</div>
          </div>
          <div className="h-1.5 rounded-full bg-black/30 overflow-hidden">
            <div className="h-full w-1/3 min-w-[30%] rounded-full bg-sky-400/80 animate-pulse"
              style={{ animation: 'ainewRestoreBar 1.6s ease-in-out infinite' }} />
          </div>
          <style>{`@keyframes ainewRestoreBar { 0% { transform: translateX(-100%); } 100% { transform: translateX(350%); } }`}</style>
          <p className="text-[11px] text-slate-500 mt-2">
            {t('set_large_dump')}
          </p>
        </div>
      )}

      {preview && (
        <div className="mb-3 rounded-[10px] border border-white/[0.08] bg-cyber-deep/40 p-4 text-xs text-slate-300 space-y-1">
          <div>{t('set_src_ver')} <span className="text-white">{preview.manifest?.app_version}</span> · {preview.manifest?.exported_at}</div>
          <div>SECRET_KEY: {preview.fingerprint_match
            ? <span className="text-emerald-400">{t('set_fp_match')}</span>
            : <span className="text-amber-300">{t('set_fp_diff')}</span>}
            {' '}({preview.zip_secret_key_fingerprint || preview.manifest?.secret_key_fingerprint} → {preview.current_fingerprint})
          </div>
          <div>
            Taşıma secret’ları:{' '}
            {preview.has_migration_secrets
              ? <span className="text-emerald-400">{t('set_mig_in_zip')}</span>
              : <span className="text-amber-300">{t('set_mig_missing')}</span>}
          </div>
          <div>{t('set_ainew_dropt_size', { a: (preview.ainew_size_bytes / 1024).toFixed(1), d: preview.has_dropt ? `${(preview.dropt_size_bytes / 1024).toFixed(1)} KB` : t('set_absent') })}</div>
        </div>
      )}

      {msg && <div className="mb-2 px-4 py-3 rounded-xl bg-emerald-500/10 border border-emerald-500/25 text-sm text-emerald-100">{msg}</div>}
      {err && <div className="mb-2 px-4 py-3 rounded-xl bg-rose-500/10 border border-rose-500/30 text-sm text-rose-100">{err}</div>}
    </div>
  )
}

const DangerZoneTab: React.FC = () => {
  const t = useT()
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [confirmText, setConfirmText] = useState('')
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null)
  const queryClient = useQueryClient()

  const { data: preview, isLoading, refetch } = useQuery<WipePreview>({
    queryKey: ['wipe-all-data-preview'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/settings/wipe-all-data/preview`)
      if (!r.ok) throw new Error(t('set_preview_fail'))
      return r.json()
    }
  })

  const categories = preview?.categories || []
  const nonEmptyCategories = categories.filter(c => c.total_rows > 0)

  const toggleCategory = (id: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const toggleAll = () => {
    if (selected.size === nonEmptyCategories.length) setSelected(new Set())
    else setSelected(new Set(nonEmptyCategories.map(c => c.id)))
  }

  const selectedTotal = categories
    .filter(c => selected.has(c.id))
    .reduce((sum, c) => sum + c.total_rows, 0)

  const wipeMutation = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${API_BASE_URL}/settings/wipe-all-data`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ confirm: confirmText, categories: Array.from(selected) }),
      })
      const d = await r.json()
      if (!r.ok) throw new Error(d.detail || t('set_wipe_fail'))
      return d
    },
    onSuccess: (d) => {
      setResult({ success: true, message: t('set_reloading', { msg: d.message }) })
      setConfirmText('')
      setSelected(new Set())
      refetch()
      queryClient.invalidateQueries()
      // Uygulama genelindeki tüm sayaçların (Dashboard, sidebar, vb.) anlık
      // olarak güncel görünmesini garanti etmek için tam sayfa yenileme yapılır —
      // invalidateQueries sadece o an mount olan sorguları tazeler.
      setTimeout(() => window.location.reload(), 1200)
    },
    onError: (e) => setResult({ success: false, message: e instanceof Error ? e.message : t('error_generic') }),
  })

  const canConfirm = confirmText.trim() === WIPE_CONFIRM_PHRASE && selected.size > 0

  return (
    <div>
      <h2 className="text-xl font-semibold text-white mb-2">{t('set_danger_title')}</h2>
      <p className="text-slate-400 text-sm mb-6">{t('set_danger_intro')}</p>

      <div className="bg-red-500/5 border-2 border-red-500/30 rounded-xl p-6">
        <div className="flex items-start gap-3 mb-4">
          <div className="w-10 h-10 rounded-full bg-red-500/15 border border-red-500/40 flex items-center justify-center flex-shrink-0">
            <AlertTriangle size={20} strokeWidth={2} className="text-red-400" />
          </div>
          <div>
            <h3 className="text-base font-semibold text-white">{t('set_wipe_data')}</h3>
            <p className="text-slate-400 text-sm mt-1">{t('set_wipe_hint')}</p>
          </div>
        </div>

        {isLoading ? (
          <p className="text-slate-500 text-sm py-4">{t('loading')}</p>
        ) : nonEmptyCategories.length === 0 ? (
          <p className="text-slate-500 text-sm py-4">{t('set_wipe_empty')}</p>
        ) : (
          <>
            <div className="mb-4 rounded-lg border border-white/[0.06] overflow-hidden">
              <div className="flex items-center justify-between px-4 py-2.5 bg-cyber-deep/70 border-b border-white/[0.06]">
                <label className="flex items-center gap-2.5 cursor-pointer text-sm text-slate-300">
                  <input
                    type="checkbox"
                    checked={selected.size === nonEmptyCategories.length && nonEmptyCategories.length > 0}
                    onChange={toggleAll}
                    className="w-4 h-4 text-red-600 bg-white/[0.07] border-slate-600 rounded"
                  />
                  {t('select_all')}
                </label>
                <span className="text-xs text-slate-500">{t('set_n_cats', { n: nonEmptyCategories.length })}</span>
              </div>
              <div className="divide-y divide-white/[0.04] max-h-80 overflow-y-auto">
                {nonEmptyCategories.map(cat => (
                  <label
                    key={cat.id}
                    className={`flex items-center justify-between px-4 py-3 cursor-pointer transition-colors ${selected.has(cat.id) ? 'bg-red-500/10' : 'hover:bg-white/[0.03]'}`}
                  >
                    <span className="flex items-center gap-2.5">
                      <input
                        type="checkbox"
                        checked={selected.has(cat.id)}
                        onChange={() => toggleCategory(cat.id)}
                        className="w-4 h-4 text-red-600 bg-white/[0.07] border-slate-600 rounded"
                      />
                      <span className="text-sm text-white">{cat.label}</span>
                    </span>
                    <span className="text-xs text-slate-400 font-mono">{cat.total_rows} {t('records')}</span>
                  </label>
                ))}
              </div>
            </div>

            <div className="mb-4 p-3 bg-blue-500/5 border border-blue-500/20 rounded-lg">
              <p className="text-xs text-blue-300">{t('set_preserved')}</p>
            </div>

            <div className="border-t border-red-500/20 pt-4">
              <div className="flex items-center justify-between mb-2">
                <label className="block text-sm text-slate-300">
                  {t('set_type_to_continue', { phrase: WIPE_CONFIRM_PHRASE })}
                </label>
                <span className="text-sm font-semibold text-red-400">{t('set_will_del', { n: selectedTotal })}</span>
              </div>
              <div className="flex items-center gap-3">
                <input
                  type="text"
                  value={confirmText}
                  onChange={e => setConfirmText(e.target.value)}
                  placeholder={WIPE_CONFIRM_PHRASE}
                  className="flex-1 bg-cyber-deep border border-red-500/30 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-red-500 font-mono text-sm"
                />
                <button
                  onClick={() => wipeMutation.mutate()}
                  disabled={!canConfirm || wipeMutation.isPending}
                  className="px-6 py-2.5 bg-gradient-to-r from-red-600 to-red-700 text-white rounded-lg hover:from-red-500 hover:to-red-600 disabled:opacity-40 disabled:cursor-not-allowed font-medium text-sm whitespace-nowrap"
                >
                  {wipeMutation.isPending ? t('deleting') : t('set_del_selected', { n: selected.size })}
                </button>
              </div>
              {selected.size === 0 && (
                <p className="text-xs text-slate-500 mt-2">{t('set_pick_cat')}</p>
              )}
            </div>

            {result && (
              <div className={`mt-4 p-3 rounded-lg text-sm ${result.success ? 'bg-green-500/10 border border-green-500/30 text-green-400' : 'bg-red-500/10 border border-red-500/30 text-red-400'}`}>
                {result.message}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}

interface AIModel { name: string; size: number; parameter_size: string; family: string }

interface AdvancedSettingItem {
  key: string
  value: number | boolean | string
  default: number | boolean | string
  type: string
  min?: number
  max?: number
  group: string
  group_label: string
  label: string
  help: string
  env?: string
  choices?: string[]
  requires_restart?: boolean
  restart_target?: string
}

interface AdvancedGroup {
  id: string
  label: string
  settings: AdvancedSettingItem[]
}

const AdvancedSettingsTab: React.FC = () => {
  const t = useT()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const queryClient = useQueryClient()
  const [draft, setDraft] = useState<Record<string, string>>({})
  const [saveMsg, setSaveMsg] = useState<string | null>(null)

  const { data, isLoading, error } = useQuery<{ groups: AdvancedGroup[]; settings: AdvancedSettingItem[] }>({
    queryKey: ['advanced-settings'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/settings/advanced`)
      if (!res.ok) {
        let detail = ''
        try {
          const j = await res.json()
          detail = typeof j?.detail === 'string' ? j.detail : ''
        } catch { /* ignore */ }
        throw new Error(detail || t('set_adv_load_fail', { status: res.status }))
      }
      return res.json()
    },
  })

  React.useEffect(() => {
    if (!data?.settings) return
    const next: Record<string, string> = {}
    for (const s of data.settings) {
      next[s.key] = String(s.value)
    }
    setDraft(next)
  }, [data])

  const saveMutation = useMutation({
    mutationFn: async (settings: Record<string, number | boolean | string>) => {
      const res = await fetch(`${API_BASE_URL}/settings/advanced`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ settings }),
      })
      if (!res.ok) {
        const bodyText = await res.text()
        throw new Error(bodyText || t('set_save_fail'))
      }
      return res.json()
    },
    onSuccess: (r) => {
      queryClient.invalidateQueries({ queryKey: ['advanced-settings'] })
      const restart = Array.isArray(r?.restart_needed) && r.restart_needed.length > 0
      setSaveMsg(r.message || (restart ? t('set_saved_recreate') : t('saved')))
      setTimeout(() => setSaveMsg(null), restart ? 12000 : 4000)
    },
  })

  const onSave = () => {
    if (!data?.settings) return
    const payload: Record<string, number | boolean | string> = {}
    for (const s of data.settings) {
      const raw = draft[s.key]
      if (raw === undefined || raw === '') continue
      if (s.type === 'bool') {
        payload[s.key] = ['1', 'true', 'yes', 'on'].includes(String(raw).toLowerCase())
      } else if (s.type === 'str') {
        payload[s.key] = String(raw)
      } else if (s.type === 'float') {
        payload[s.key] = Number(raw)
      } else {
        payload[s.key] = parseInt(String(raw), 10)
      }
    }
    saveMutation.mutate(payload)
  }

  const resetDefaults = () => {
    if (!data?.settings) return
    const next: Record<string, string> = {}
    for (const s of data.settings) {
      next[s.key] = String(s.default)
    }
    setDraft(next)
  }

  if (isLoading) {
    return <div className="text-slate-400 text-sm">{t('set_adv_loading')}</div>
  }
  if (error) {
    return <div className="text-red-400 text-sm">{t('set_load_err', { msg: (error as Error).message })}</div>
  }

  return (
    <div>
      <div className="flex flex-wrap items-start gap-3 mb-6">
        <div className="flex-1 min-w-0">
          <h2 className="text-xl font-semibold text-white">{t('set_tab_advanced')}</h2>
          <p className="text-slate-400 text-sm mt-1">{t('set_adv_intro')}</p>
        </div>
        <div className="flex flex-wrap gap-2">
          {isAdmin && (
            <>
              <button
                type="button"
                onClick={resetDefaults}
                className="px-3 py-2 rounded-lg text-sm text-slate-300 bg-white/[0.07] hover:bg-slate-600 border border-slate-600"
              >
                {t('set_reset_defaults')}
              </button>
              <button
                type="button"
                onClick={onSave}
                disabled={saveMutation.isPending}
                className="px-4 py-2 rounded-lg text-sm font-medium text-white bg-blue-600 hover:bg-blue-500 disabled:opacity-50"
              >
                {saveMutation.isPending ? t('saving') : t('save')}
              </button>
            </>
          )}
        </div>
      </div>

      {!isAdmin && (
        <div className="mb-4 p-3 rounded-lg text-sm bg-amber-500/10 border border-amber-500/30 text-amber-300">
          {t('set_adv_readonly')}
        </div>
      )}

      {saveMsg && (
        <div className="mb-4 p-3 rounded-lg text-sm bg-green-500/10 border border-green-500/30 text-green-400">
          {saveMsg}
        </div>
      )}
      {saveMutation.isError && (
        <div className="mb-4 p-3 rounded-lg text-sm bg-red-500/10 border border-red-500/30 text-red-400">
          {(saveMutation.error as Error).message}
        </div>
      )}

      <div className="space-y-6">
        {(data?.groups || []).map(group => (
          <div key={group.id} className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-5">
            <h3 className="text-sm font-semibold text-blue-400 mb-4 uppercase tracking-wide">{group.label}</h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
              {group.settings.map(s => (
                <div key={s.key} className="min-w-0">
                  <label className="block text-sm text-slate-300 mb-1 flex flex-wrap items-center gap-2">
                    <span>{s.label}</span>
                    {s.requires_restart ? (
                      <span className="text-[10px] uppercase tracking-wide px-1.5 py-0.5 rounded bg-amber-500/15 text-amber-300 border border-amber-500/30">
                        recreate{s.restart_target ? `: ${s.restart_target}` : ''}
                      </span>
                    ) : null}
                  </label>
                  {s.type === 'bool' ? (
                    <select
                      value={['1', 'true', 'yes', 'on'].includes(String(draft[s.key] ?? '').toLowerCase()) ? 'true' : 'false'}
                      disabled={!isAdmin}
                      onChange={e => setDraft(prev => ({ ...prev, [s.key]: e.target.value }))}
                      className="w-full bg-cyber-card border border-slate-600 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 disabled:opacity-60"
                    >
                      <option value="true">{t('enabled')}</option>
                      <option value="false">{t('disabled')}</option>
                    </select>
                  ) : s.type === 'str' && s.choices && s.choices.length > 0 ? (
                    <select
                      value={draft[s.key] ?? ''}
                      disabled={!isAdmin}
                      onChange={e => setDraft(prev => ({ ...prev, [s.key]: e.target.value }))}
                      className="w-full bg-cyber-card border border-slate-600 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 disabled:opacity-60"
                    >
                      {s.choices.map(c => (
                        <option key={c} value={c}>{c}</option>
                      ))}
                    </select>
                  ) : s.type === 'str' ? (
                    <input
                      type="text"
                      value={draft[s.key] ?? ''}
                      disabled={!isAdmin}
                      onChange={e => setDraft(prev => ({ ...prev, [s.key]: e.target.value }))}
                      className="w-full bg-cyber-card border border-slate-600 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 disabled:opacity-60"
                    />
                  ) : (
                    <input
                      type="number"
                      step={s.type === 'float' ? '0.1' : '1'}
                      min={s.min}
                      max={s.max}
                      value={draft[s.key] ?? ''}
                      disabled={!isAdmin}
                      onChange={e => setDraft(prev => ({ ...prev, [s.key]: e.target.value }))}
                      className="w-full bg-cyber-card border border-slate-600 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 disabled:opacity-60"
                    />
                  )}
                  <p className="text-xs text-slate-500 mt-1">
                    {s.help}
                    {s.type !== 'str' && s.type !== 'bool' && s.min != null && s.max != null ? ` (${s.min}–${s.max})` : ''}
                    {s.env ? ` · env: ${s.env}` : ''}
                  </p>
                </div>
              ))}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

const Settings: React.FC = () => {
  const t = useT()
  const { user } = useAuth()
  const isAdmin = user?.role === 'admin'
  const [activeTab, setActiveTab] = useState('credentials')
  const [showForm, setShowForm] = useState(false)
  const [editingCred, setEditingCred] = useState<Credential | null>(null)
  const [form, setForm] = useState({ name: '', username: '', password: '', private_key: '', sudo_password: '', port: 22 })
  const [applyModal, setApplyModal] = useState<{ open: boolean; credId: number; credName: string }>({ open: false, credId: 0, credName: '' })
  const [applyMode, setApplyMode] = useState<'all' | 'select'>('all')
  const [selectedServerIds, setSelectedServerIds] = useState<number[]>([])
  const [setAiReady, setSetAiReady] = useState(true)
  const [sshTest, setSshTest] = useState<{
    jobId: string | null
    status: 'idle' | 'running' | 'done' | 'error'
    done: number
    total: number
    percent: number
    successful: number
    failed: number
    skipped: number
    currentServer?: string | null
    message?: string
    error?: string | null
  }>({
    jobId: null,
    status: 'idle',
    done: 0,
    total: 0,
    percent: 0,
    successful: 0,
    failed: 0,
    skipped: 0,
  })
  const sshTestRunning = sshTest.status === 'running'
  const queryClient = useQueryClient()
  const [confirmState, setConfirmState] = React.useState<{ msg: string; resolve: (v: boolean) => void } | null>(null)
  const showConfirm = (msg: string): Promise<boolean> => new Promise(resolve => setConfirmState({ msg, resolve }))
  // WinRM credential state
  const [winrmForm, setWinrmForm] = useState({ username: '', password: '', port: 5985, use_https: false })
  const [winrmEditing, setWinrmEditing] = useState(false)
  const [winrmApplyResult, setWinrmApplyResult] = useState<{ applied_to: number; servers: string[]; skipped_linux?: number; message?: string } | null>(null)

  const [metricRetentionDays, setMetricRetentionDays] = useState<number>(30)
  const [selectedModel, setSelectedModel] = useState<string>(() => localStorage.getItem('chat_selected_model') || 'llama3.2:3b')
  const [modelSaved, setModelSaved] = useState(false)
  const [retentionSaved, setRetentionSaved] = useState(false)
  const { data: modelsData } = useQuery<{ success: boolean; models: AIModel[]; default: string }>({
    queryKey: ['ai-models'],
    queryFn: async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/chat/models`, { signal: AbortSignal.timeout(5000) })
        if (!res.ok) return { success: false, models: [], default: 'llama3.2:3b' }
        return res.json()
      } catch { return { success: false, models: [], default: 'llama3.2:3b' } }
    },
    staleTime: 60000,
  })
  const availableModels: AIModel[] = modelsData?.models?.length ? modelsData.models : []
  const { data: generalSettings } = useQuery<GeneralSettings>({
    queryKey: ['general-settings'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/settings/`)
      if (!res.ok) throw new Error(t('set_settings_fail'))
      return res.json()
    },
    staleTime: 60000,
  })
  // Backend'den gelen aktif model ile sync et (ilk yüklemede localStorage yoksa)
  React.useEffect(() => {
    if (modelsData?.default && !localStorage.getItem('chat_selected_model')) {
      setSelectedModel(modelsData.default)
    } else if (modelsData?.default && modelsData.default !== 'llama3.2:3b') {
      // Backend'de kayıtlı model varsa onu öne çıkar
      const stored = localStorage.getItem('chat_selected_model')
      if (!stored || stored === 'llama3.2:3b') {
        setSelectedModel(modelsData.default)
        localStorage.setItem('chat_selected_model', modelsData.default)
      }
    }
  }, [modelsData?.default])

  React.useEffect(() => {
    if (generalSettings?.metric_retention_days) {
      setMetricRetentionDays(generalSettings.metric_retention_days)
    }
  }, [generalSettings?.metric_retention_days])

  React.useEffect(() => {
    if (generalSettings) {
      setPromForm({
        prometheus_url: generalSettings.prometheus_url || '',
        pushgateway_url: generalSettings.pushgateway_url || '',
        linux_jobs: generalSettings.prometheus_linux_jobs?.length
          ? [...generalSettings.prometheus_linux_jobs]
          : ['node-exporter'],
        windows_jobs: generalSettings.prometheus_windows_jobs?.length
          ? [...generalSettings.prometheus_windows_jobs]
          : ['windows-exporter'],
        linux_job_input: '',
        windows_job_input: '',
      })
    }
  }, [generalSettings?.prometheus_url, generalSettings?.pushgateway_url,
      JSON.stringify(generalSettings?.prometheus_linux_jobs),
      JSON.stringify(generalSettings?.prometheus_windows_jobs)])

  const savePrometheus = async () => {
    setPromSaving(true)
    setPromSaved(false)
    setPromError('')
    try {
      const r = await fetch(`${API_BASE_URL}/settings/prometheus`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          prometheus_url: promForm.prometheus_url.trim(),
          pushgateway_url: promForm.pushgateway_url.trim(),
          prometheus_linux_jobs: promForm.linux_jobs,
          prometheus_windows_jobs: promForm.windows_jobs,
        }),
      })
      if (!r.ok) {
        const err = await r.json().catch(() => ({}))
        throw new Error(err.detail || t('set_save_fail'))
      }
      setPromSaved(true)
      queryClient.invalidateQueries({ queryKey: ['general-settings'] })
      setTimeout(() => setPromSaved(false), 3000)
    } catch (e: any) {
      setPromError(e?.message || t('set_save_fail'))
    } finally {
      setPromSaving(false)
    }
  }

  // Uzak AI (OpenAI-uyumlu gateway, örn. Bifrost) ayarları
  const [remoteLlmForm, setRemoteLlmForm] = useState({
    enabled: false,
    url: '',
    model: '',
    api_key: '',
    virtual_key: '',
    clear_virtual_key: false,
    verify_ssl: true,
    ca_bundle: '',
  })
  const [remoteLlmSaved, setRemoteLlmSaved] = useState(false)
  const [remoteLlmError, setRemoteLlmError] = useState('')
  const [remoteLlmSaving, setRemoteLlmSaving] = useState(false)
  const [remoteLlmTesting, setRemoteLlmTesting] = useState(false)
  const [remoteLlmTestMsg, setRemoteLlmTestMsg] = useState<{ ok: boolean; text: string } | null>(null)

  const [promForm, setPromForm] = useState({
    prometheus_url: '',
    pushgateway_url: '',
    linux_jobs: ['node-exporter'] as string[],
    windows_jobs: ['windows-exporter'] as string[],
    linux_job_input: '',
    windows_job_input: '',
  })
  const [promSaving, setPromSaving] = useState(false)
  const [promSaved, setPromSaved] = useState(false)
  const [promError, setPromError] = useState('')
  React.useEffect(() => {
    if (generalSettings?.remote_llm) {
      const r = generalSettings.remote_llm
      setRemoteLlmForm(f => ({
        ...f,
        enabled: r.enabled,
        url: r.url || '',
        model: r.model || '',
        verify_ssl: r.verify_ssl ?? true,
        ca_bundle: r.ca_bundle || '',
        clear_virtual_key: false,
      }))
    }
  }, [generalSettings?.remote_llm])
  const saveRemoteLlm = async () => {
    setRemoteLlmError('')
    setRemoteLlmTestMsg(null)
    setRemoteLlmSaving(true)
    try {
      const res = await fetch(`${API_BASE_URL}/settings/remote-llm`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          enabled: remoteLlmForm.enabled,
          url: remoteLlmForm.url.trim(),
          model: remoteLlmForm.model.trim(),
          api_key: remoteLlmForm.api_key.trim() || undefined,
          virtual_key: remoteLlmForm.virtual_key.trim() || undefined,
          clear_virtual_key: remoteLlmForm.clear_virtual_key || undefined,
          verify_ssl: remoteLlmForm.verify_ssl,
          ca_bundle: remoteLlmForm.ca_bundle.trim(),
        }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Kaydedilemedi')
      setRemoteLlmForm(f => ({ ...f, api_key: '', virtual_key: '', clear_virtual_key: false }))
      setRemoteLlmSaved(true)
      queryClient.invalidateQueries({ queryKey: ['general-settings'] })
      queryClient.invalidateQueries({ queryKey: ['ai-models'] })
      setTimeout(() => setRemoteLlmSaved(false), 3000)
    } catch (e: any) {
      setRemoteLlmError(e.message || 'Kaydedilemedi')
    } finally {
      setRemoteLlmSaving(false)
    }
  }

  const testRemoteLlm = async () => {
    setRemoteLlmError('')
    setRemoteLlmTestMsg(null)
    setRemoteLlmTesting(true)
    try {
      const res = await fetch(`${API_BASE_URL}/settings/remote-llm/test`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          url: remoteLlmForm.url.trim(),
          model: remoteLlmForm.model.trim(),
          api_key: remoteLlmForm.api_key.trim() || undefined,
          virtual_key: remoteLlmForm.virtual_key.trim() || undefined,
          verify_ssl: remoteLlmForm.verify_ssl,
          ca_bundle: remoteLlmForm.ca_bundle.trim(),
        }),
      })
      const data = await res.json().catch(() => ({}))
      if (!res.ok) {
        const detail = typeof data.detail === 'string' ? data.detail : t('set_test_fail')
        throw new Error(detail)
      }
      setRemoteLlmTestMsg({ ok: Boolean(data.ok), text: data.message || (data.ok ? 'OK' : t('audit_st_failed')) })
    } catch (e: any) {
      setRemoteLlmTestMsg({ ok: false, text: e.message || t('set_test_fail') })
    } finally {
      setRemoteLlmTesting(false)
    }
  }

  // Kurumsal Kimlik (marka adı + logo)
  const { appName, logoUrl, version, refreshBranding } = useBranding()
  const [brandingName, setBrandingName] = useState('')
  const [brandingNameSaving, setBrandingNameSaving] = useState(false)
  const [brandingNameSaved, setBrandingNameSaved] = useState(false)
  const [brandingError, setBrandingError] = useState('')
  const [logoFile, setLogoFile] = useState<File | null>(null)
  const [logoUploading, setLogoUploading] = useState(false)
  React.useEffect(() => { setBrandingName(appName) }, [appName])

  const saveBrandingName = async () => {
    setBrandingError('')
    setBrandingNameSaving(true)
    try {
      const res = await fetch(`${API_BASE_URL}/settings/branding`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ app_name: brandingName.trim() }),
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Kaydedilemedi')
      await refreshBranding()
      setBrandingNameSaved(true)
      setTimeout(() => setBrandingNameSaved(false), 3000)
    } catch (e: any) {
      setBrandingError(e.message || 'Kaydedilemedi')
    } finally {
      setBrandingNameSaving(false)
    }
  }

  const uploadLogo = async () => {
    if (!logoFile) return
    setBrandingError('')
    setLogoUploading(true)
    try {
      const form = new FormData()
      form.append('file', logoFile)
      const res = await fetch(`${API_BASE_URL}/settings/branding/logo`, { method: 'POST', body: form })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || t('set_logo_fail'))
      setLogoFile(null)
      await refreshBranding()
    } catch (e: any) {
      setBrandingError(e.message || t('set_logo_fail'))
    } finally {
      setLogoUploading(false)
    }
  }

  const removeLogo = async () => {
    setBrandingError('')
    try {
      const res = await fetch(`${API_BASE_URL}/settings/branding/logo`, { method: 'DELETE' })
      if (!res.ok) {
        const data = await res.json().catch(() => ({}))
        throw new Error(data.detail || t('set_logo_rm_fail'))
      }
      await refreshBranding()
    } catch (e: any) {
      setBrandingError(e.message || t('set_logo_rm_fail'))
    }
  }

  // Queries
  const { data: credentials = [], isLoading: credsLoading } = useQuery<Credential[]>({
    queryKey: ['credentials'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/`)
      if (!res.ok) return []
      return res.json()
    }
  })

  const { data: servers = [] } = useQuery<Server[]>({
    queryKey: ['servers', 'settings-picker'],
    queryFn: async () => {
      const { fetchServersForPicker } = await import('../api/servers')
      return fetchServersForPicker<Server>({ page_size: 200, maxPages: 3 })
    }
  })
  const linuxServers = React.useMemo(() => servers.filter(s => !isWindowsServer(s)), [servers])
  const windowsServers = React.useMemo(() => servers.filter(s => isWindowsServer(s)), [servers])

  // WinRM Queries & Mutations
  const { data: winrmCred } = useQuery<{ configured: boolean; username?: string; port?: number; use_https?: boolean; has_password?: boolean }>({
    queryKey: ['winrm-global-cred'],
    queryFn: async () => {
      const res = await fetch(`${API_BASE_URL}/windows/global-credential`)
      if (!res.ok) return { configured: false }
      return res.json()
    }
  })

  const saveWinrm = useMutation({
    mutationFn: async (data: typeof winrmForm) => {
      const res = await fetch(`${API_BASE_URL}/windows/global-credential`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
      })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || t('error_generic'))
      return r
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['winrm-global-cred'] })
      queryClient.invalidateQueries({ queryKey: ['windows-servers'] })
      setWinrmEditing(false)
    }
  })

  const deleteWinrm = useMutation({
    mutationFn: async () => {
      await fetch(`${API_BASE_URL}/windows/global-credential`, { method: 'DELETE' })
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['winrm-global-cred'] })
      queryClient.invalidateQueries({ queryKey: ['windows-servers'] })
    }
  })

  const applyWinrm = useMutation({
    mutationFn: async () => {
      const res = await fetch(`${API_BASE_URL}/windows/global-credential/apply`, { method: 'POST' })
      return res.json()
    },
    onSuccess: (data) => {
      setWinrmApplyResult(data)
      queryClient.invalidateQueries({ queryKey: ['windows-servers'] })
    }
  })

  // Mutations
  const createCred = useMutation({
    mutationFn: async (data: typeof form) => {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
      })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || t('error_generic'))
      return r
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['credentials'] }); resetForm() }
  })

  const updateCred = useMutation({
    mutationFn: async ({ id, data }: { id: number; data: typeof form }) => {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/${id}`, {
        method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(data)
      })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || t('error_generic'))
      return r
    },
    onSuccess: () => { queryClient.invalidateQueries({ queryKey: ['credentials'] }); resetForm() }
  })

  const deleteCred = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/${id}`, { method: 'DELETE' })
      if (!res.ok) throw new Error(t('delete_failed'))
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['credentials'] })
  })

  const setDefault = useMutation({
    mutationFn: async (id: number) => {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/${id}/set-default`, { method: 'POST' })
      if (!res.ok) throw new Error(t('error_generic'))
      return res.json()
    },
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['credentials'] })
  })

  const applyCred = useMutation({
    mutationFn: async ({ credId, serverIds, aiReady }: { credId: number; serverIds: number[] | null; aiReady: boolean }) => {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/${credId}/apply`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ server_ids: serverIds, set_ai_ready: aiReady })
      })
      const text = await res.text()
      let r: any = null
      try {
        r = text ? JSON.parse(text) : null
      } catch {
        throw new Error(
          res.status === 504 || res.status === 502
            ? t('set_proxy_timeout')
            : t('set_html_resp', { status: res.status })
        )
      }
      if (!res.ok) {
        const detail = r?.detail
        throw new Error(typeof detail === 'string' ? detail : (detail?.[0]?.msg || t('error_generic')))
      }
      return r
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['servers'] })
      setApplyModal({ open: false, credId: 0, credName: '' })
      alert(data.message)
    }
  })

  const startSshTest = async () => {
    if (sshTestRunning) return
    setSshTest({
      jobId: null,
      status: 'running',
      done: 0,
      total: 0,
      percent: 0,
      successful: 0,
      failed: 0,
      skipped: 0,
      message: t('set_ssh_starting'),
      currentServer: null,
      error: null,
    })
    try {
      const res = await fetch(`${API_BASE_URL}/settings/credentials/test-all-ssh`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      })
      const text = await res.text()
      let r: any = null
      try {
        r = text ? JSON.parse(text) : null
      } catch {
        throw new Error(
          res.status === 504 || res.status === 502
            ? t('set_ssh_timeout')
            : t('set_html_resp', { status: res.status })
        )
      }
      if (!res.ok) throw new Error(typeof r?.detail === 'string' ? r.detail : t('set_ssh_start_fail'))

      if (!r?.job_id) throw new Error(t('set_no_job'))
      setSshTest({
        jobId: r.job_id,
        status: r.status === 'done' ? 'done' : r.status === 'error' ? 'error' : 'running',
        done: r.done || 0,
        total: r.total || 0,
        percent: r.percent || 0,
        successful: r.successful || 0,
        failed: r.failed || 0,
        skipped: r.skipped || 0,
        currentServer: r.current_server,
        message: r.message || t('set_testing'),
        error: r.error || null,
      })
      if (r.status === 'done' && r.result) {
        queryClient.invalidateQueries({ queryKey: ['servers'] })
        alert(t('set_ssh_done', { ok: r.result.successful, fail: r.result.failed, msg: r.result.message }))
      } else if (r.status === 'error') {
        alert(r.error || r.message || t('set_ssh_err'))
      }
    } catch (e) {
      const msg = e instanceof Error ? e.message : t('set_ssh_err')
      setSshTest(prev => ({ ...prev, status: 'error', error: msg, message: msg }))
      alert(msg)
    }
  }

  React.useEffect(() => {
    if (!sshTest.jobId || sshTest.status !== 'running') return
    let cancelled = false
    let finished = false
    const poll = async () => {
      if (finished || cancelled) return
      try {
        const res = await fetch(`${API_BASE_URL}/settings/credentials/test-all-ssh/${sshTest.jobId}`)
        if (!res.ok) {
          if (res.status === 404 && !cancelled && !finished) {
            finished = true
            setSshTest(prev => ({
              ...prev,
              status: 'error',
              error: t('set_job_missing'),
              message: t('set_ssh_job_gone'),
            }))
          }
          return
        }
        const r = await res.json()
        if (cancelled || finished) return
        setSshTest(prev => ({
          ...prev,
          status: r.status === 'done' ? 'done' : r.status === 'error' ? 'error' : 'running',
          done: r.done || 0,
          total: r.total || prev.total,
          percent: r.percent || 0,
          successful: r.successful || 0,
          failed: r.failed || 0,
          skipped: r.skipped ?? prev.skipped,
          currentServer: r.current_server,
          message: r.message || prev.message,
          error: r.error || null,
        }))
        if (r.status === 'done' || r.status === 'error') {
          finished = true
          if (r.status === 'done') {
            queryClient.invalidateQueries({ queryKey: ['servers'] })
            const result = r.result
            const ok = result?.successful ?? r.successful ?? 0
            const fail = result?.failed ?? r.failed ?? 0
            const msg = result?.message || r.message || ''
            alert(t('set_ssh_done', { ok, fail, msg }))
          } else {
            alert(r.error || r.message || t('set_ssh_err'))
          }
        }
      } catch {
        // geçici ağ hatası — sonraki poll dener
      }
    }
    poll()
    const timer = window.setInterval(poll, 1000)
    return () => {
      cancelled = true
      window.clearInterval(timer)
    }
  }, [sshTest.jobId, sshTest.status, queryClient])

  const saveMetricRetention = useMutation({
    mutationFn: async (days: number) => {
      const res = await fetch(`${API_BASE_URL}/settings/metric-retention`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ days })
      })
      const r = await res.json()
      if (!res.ok) throw new Error(r.detail || t('set_ret_fail'))
      return r
    },
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ['general-settings'] })
      setRetentionSaved(true)
      setTimeout(() => setRetentionSaved(false), 3000)
      alert(t('set_ret_ok', { days: data.metric_retention_days, n: data.deleted_rows ?? 0 }))
    },
    onError: (e) => alert(e instanceof Error ? e.message : t('set_save_err'))
  })

  const resetForm = () => {
    setShowForm(false); setEditingCred(null)
    setForm({ name: '', username: '', password: '', private_key: '', sudo_password: '', port: 22 })
  }

  const openEdit = (c: Credential) => {
    setEditingCred(c); setShowForm(false)
    setForm({ name: c.name, username: c.username, password: '', private_key: '', sudo_password: '', port: c.port })
  }

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (editingCred) updateCred.mutate({ id: editingCred.id, data: form })
    else createCred.mutate(form)
  }

  const tabs = [
    { id: 'credentials', name: t('set_tab_linux_ssh') },
    { id: 'winrm', name: t('set_tab_winrm') },
    { id: 'ai', name: t('set_tab_ai') },
    { id: 'branding', name: t('set_tab_branding') },
    { id: 'rag', name: t('set_tab_rag') },
    { id: 'monitoring', name: t('set_tab_monitoring') },
    { id: 'security', name: t('set_tab_security') },
    { id: 'advanced', name: t('set_tab_advanced') },
    { id: 'about', name: t('set_tab_about') },
    ...(isAdmin ? [
      { id: 'platform-status', name: t('set_tab_platform') },
      { id: 'config-backup', name: t('set_tab_backup') },
      { id: 'platform-update', name: t('set_tab_update') },
      { id: 'danger', name: t('set_tab_danger') },
    ] : []),
  ]

  return (
    <div className="flex gap-6 h-[calc(100vh-140px)]">
      {/* Sol Menu */}
      <div className="w-64 bg-cyber-card rounded-[10px] border border-white/[0.06] overflow-hidden flex-shrink-0">
        <div className="p-4 border-b border-white/[0.06]">
          <h2 className="text-lg font-semibold text-[var(--text-primary)]">{t('set_title')}</h2>
        </div>
        <nav className="p-3">
          {tabs.map(tab => (
            <button key={tab.id} onClick={() => setActiveTab(tab.id)}
              className={`w-full flex items-center px-4 py-2.5 rounded-lg text-left transition-all text-sm ${
                activeTab === tab.id
                  ? (tab.id === 'danger' ? 'bg-red-600/20 text-red-400 border border-red-500/30' : 'bg-blue-600/20 text-blue-400 border border-blue-500/30')
                  : (tab.id === 'danger' ? 'text-red-400/70 hover:text-red-400 hover:bg-red-500/10' : 'text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]')
              }`}>
              <span className="font-medium">{tab.name}</span>
            </button>
          ))}
        </nav>
      </div>

      {/* Content */}
      <div className="flex-1 bg-cyber-card rounded-[10px] border border-white/[0.06] overflow-hidden min-w-0 min-h-0">
        <div className={`p-6 h-full min-h-0 ${
          activeTab === 'platform-status'
            ? 'overflow-hidden flex flex-col'
            : 'overflow-y-auto overflow-x-hidden'
        }`}>

          {/* ═══ Credentials ═══ */}
          {activeTab === 'credentials' && (
            <div>
              <div className="flex flex-wrap items-start gap-3 mb-6">
                <div className="flex-1 min-w-0">
                  <h2 className="text-xl font-semibold text-white">{t('set_linux_ssh_title')}</h2>
                  <p className="text-slate-400 text-sm mt-1">{t('set_linux_ssh_hint')}</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button onClick={startSshTest}
                    disabled={sshTestRunning}
                    className="px-3 py-2 bg-gradient-to-r from-emerald-600 to-emerald-700 text-white rounded-lg hover:from-emerald-500 hover:to-emerald-600 transition-all text-sm disabled:opacity-50 whitespace-nowrap">
                    {sshTestRunning ? t('set_testing_btn') : t('set_ssh_test_upd')}
                  </button>
                  <button onClick={() => { setShowForm(!showForm); setEditingCred(null); setForm({ name: '', username: '', password: '', private_key: '', sudo_password: '', port: 22 }) }}
                    className="px-3 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all text-sm whitespace-nowrap">
                    {showForm ? t('set_cancel_x') : t('set_new_cred')}
                  </button>
                </div>
              </div>

              {(sshTestRunning || sshTest.status === 'done' || sshTest.status === 'error') && (
                <div className="mb-6 rounded-[10px] border border-emerald-500/30 bg-emerald-500/5 p-4">
                  <div className="flex flex-wrap items-center justify-between gap-2 mb-2">
                    <div className="text-sm text-white font-medium">
                      {sshTestRunning ? t('set_ssh_running') : sshTest.status === 'error' ? t('set_ssh_err_short') : t('set_ssh_done_short')}
                    </div>
                    <div className="text-xs text-emerald-300/90 font-mono">
                      {sshTest.done}/{sshTest.total || '—'} · %{sshTest.percent}
                    </div>
                  </div>
                  <div className="h-2.5 rounded-full bg-slate-800 overflow-hidden border border-white/[0.06]">
                    <div
                      className={`h-full transition-all duration-500 ease-out ${
                        sshTest.status === 'error' ? 'bg-red-500' : 'bg-gradient-to-r from-emerald-500 to-emerald-400'
                      }`}
                      style={{ width: `${Math.max(sshTestRunning && sshTest.percent === 0 ? 2 : 0, Math.min(100, sshTest.percent))}%` }}
                    />
                  </div>
                  <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1 text-xs text-slate-400">
                    <span className="inline-flex items-center gap-1"><CheckCircle2 size={12} strokeWidth={2} className="text-green-400" /> {sshTest.successful}</span>
                    <span className="inline-flex items-center gap-1"><XCircle size={12} strokeWidth={2} className="text-red-400" /> {sshTest.failed}</span>
                    {sshTest.skipped > 0 && <span>{t('skipped_n', { n: sshTest.skipped })}</span>}
                    {sshTest.currentServer && sshTestRunning && (
                      <span className="text-slate-300 truncate">{t('set_last_srv', { name: sshTest.currentServer })}</span>
                    )}
                  </div>
                  {sshTest.message && (
                    <p className="mt-2 text-xs text-slate-500 whitespace-pre-line line-clamp-3">{sshTest.message}</p>
                  )}
                </div>
              )}

              {/* Form */}
              {(showForm || editingCred) && (
                <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-6 mb-6">
                  <h3 className="text-lg font-medium text-white mb-4">
                    {editingCred ? t('set_edit_named', { name: editingCred.name }) : t('set_add_cred')}
                  </h3>
                  <form onSubmit={handleSubmit} className="space-y-4">
                    <div className="grid grid-cols-3 gap-4">
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">{t('name_star')}</label>
                        <input type="text" required value={form.name} onChange={e => setForm({ ...form, name: e.target.value })}
                          className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder={t('set_name_ph')} />
                      </div>
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">{t('username_star')}</label>
                        <input type="text" required value={form.username} onChange={e => setForm({ ...form, username: e.target.value })}
                          className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="root" />
                      </div>
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">{t('set_ssh_port')}</label>
                        <input type="number" value={form.port} onChange={e => setForm({ ...form, port: parseInt(e.target.value) || 22 })}
                          className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" />
                      </div>
                    </div>
                    <div className="grid grid-cols-2 gap-4">
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">{editingCred ? `${t('password_label')} ${t('empty_keep')}` : t('password_star')}</label>
                        <input type="password" required={!editingCred} value={form.password} onChange={e => setForm({ ...form, password: e.target.value })}
                          className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder="••••••••" />
                      </div>
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">{t('set_sudo_opt')}</label>
                        <input type="password" value={form.sudo_password} onChange={e => setForm({ ...form, sudo_password: e.target.value })}
                          className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" placeholder={t('optional')} />
                      </div>
                    </div>
                    <div>
                      <label className="block text-sm text-slate-300 mb-1.5">{t('set_pk_opt')}</label>
                      <textarea value={form.private_key} onChange={e => setForm({ ...form, private_key: e.target.value })}
                        className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500 font-mono text-xs"
                        placeholder="-----BEGIN OPENSSH PRIVATE KEY-----" rows={3} />
                    </div>
                    <div className="flex justify-between items-center pt-2">
                      {(createCred.isError || updateCred.isError) && (
                        <p className="text-red-400 text-sm">{(createCred.error || updateCred.error)?.message}</p>
                      )}
                      <div className="flex gap-3 ml-auto">
                        <button type="button" onClick={resetForm} className="px-4 py-2 bg-white/[0.07] text-white rounded-lg hover:bg-slate-600 text-sm">{t('cancel')}</button>
                        <button type="submit" disabled={createCred.isPending || updateCred.isPending}
                          className="px-6 py-2 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-lg hover:from-green-500 hover:to-green-600 disabled:opacity-50 text-sm">
                          {(createCred.isPending || updateCred.isPending) ? t('saving') : t('save')}
                        </button>
                      </div>
                    </div>
                  </form>
                </div>
              )}

              {/* List */}
              {credsLoading ? (
                <div className="text-center py-12"><div className="animate-spin rounded-full h-8 w-8 border-b-2 border-blue-500 mx-auto"></div></div>
              ) : credentials.length === 0 ? (
                <div className="text-center py-12 bg-cyber-deep/30 rounded-xl border border-dashed border-white/[0.06]">
                  <span className="text-2xl font-bold text-blue-400 block mb-4">KEY</span>
                  <p className="text-slate-400 mb-2">{t('set_no_creds')}</p>
                  <p className="text-slate-500 text-sm">{t('set_no_creds_hint')}</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {credentials.map(cred => (
                    <div key={cred.id} className={`rounded-xl border p-4 ${cred.is_default ? 'bg-blue-500/5 border-blue-500/30' : 'bg-cyber-deep/50 border-white/[0.06]'}`}>
                      <div className="flex items-center justify-between">
                        <div className="flex items-center space-x-4">
                          <div className={`w-11 h-11 rounded-lg flex items-center justify-center ${cred.is_default ? 'bg-gradient-to-br from-blue-500 to-blue-600' : 'bg-gradient-to-br from-yellow-500 to-orange-500'}`}>
                            <span className="text-xs font-bold text-blue-400">KEY</span>
                          </div>
                          <div className="min-w-0">
                            <div className="flex items-center gap-2 flex-wrap">
                              <p className="text-white font-medium truncate max-w-[200px]">{cred.name}</p>
                              {cred.is_default && (
                                <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-400 border border-blue-500/30 font-medium whitespace-nowrap">{t('default_badge')}</span>
                              )}
                            </div>
                            <p className="text-slate-400 text-sm font-mono mt-0.5 truncate">
                              {cred.username}@:{cred.port}
                              {cred.has_password && <span className="text-green-400 ml-2">{t('set_pw_dot')}</span>}
                              {cred.has_private_key && <span className="text-blue-400 ml-2">{t('set_key_dot')}</span>}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-1.5">
                          <button onClick={() => { setApplyModal({ open: true, credId: cred.id, credName: cred.name }); setApplyMode('all'); setSelectedServerIds([]) }}
                            className="px-3 py-1.5 text-xs bg-green-500/10 text-green-400 border border-green-500/30 rounded-lg hover:bg-green-500/20 font-medium">
                            {t('apply')}
                          </button>
                          {!cred.is_default && (
                            <button onClick={() => setDefault.mutate(cred.id)}
                              className="px-3 py-1.5 text-xs bg-blue-500/10 text-blue-400 border border-blue-500/30 rounded-lg hover:bg-blue-500/20" title={t('set_make_default')}><Star size={12} strokeWidth={2} /></button>
                          )}
                          <button onClick={() => openEdit(cred)}
                            className="px-3 py-1.5 text-xs bg-white/[0.07] text-slate-300 rounded-lg hover:bg-slate-600" title={t('edit')}>✎</button>
                          <button onClick={async () => { if (await showConfirm(t('set_del_quoted', { name: cred.name }))) deleteCred.mutate(cred.id) }}
                            className="px-3 py-1.5 text-xs bg-red-500/10 text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/20" title={t('delete')}>✕</button>
                        </div>
                      </div>
                    </div>
                  ))}
                </div>
              )}

            </div>
          )}

          {/* ═══ AI ═══ */}
          {activeTab === 'ai' && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-6">{t('set_ai_title')}</h2>
              <div className="space-y-6">
                <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-6">
                  <h3 className="text-lg font-medium text-white mb-4">{t('set_ollama_pick')}</h3>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">{t('set_default_model')}</label>
                      <select
                        value={selectedModel}
                        onChange={e => setSelectedModel(e.target.value)}
                        className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-200 focus:outline-none focus:border-blue-500"
                      >
                        {availableModels.length === 0 && (
                          <option value={selectedModel}>{selectedModel}</option>
                        )}
                        {availableModels.map(m => (
                          <option key={m.name} value={m.name}>
                            {m.name}{m.parameter_size ? ` — ${m.parameter_size}` : ''}
                          </option>
                        ))}
                      </select>
                      <p className="text-xs text-slate-500 mt-1">{t('set_model_hint')}</p>
                    </div>
                    <div className="flex items-center gap-3 mt-4">
                      <button
                        onClick={async () => {
                          localStorage.setItem('chat_selected_model', selectedModel)
                          await fetch(`${API_BASE_URL}/settings/ollama-model`, {
                            method: 'PUT',
                            headers: { 'Content-Type': 'application/json' },
                            body: JSON.stringify({ model: selectedModel })
                          })
                          setModelSaved(true)
                          setTimeout(() => setModelSaved(false), 3000)
                        }}
                        className="px-4 py-2 bg-blue-600 hover:bg-blue-700 text-white text-sm font-medium rounded-lg transition-colors">
                        {t('save')}
                      </button>
                      {modelSaved && (
                        <span className="text-green-400 text-sm flex items-center gap-1">
                          {t('set_model_saved')}
                        </span>
                      )}
                    </div>
                  </div>


                </div>

                <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-6">
                  <div className="flex items-center justify-between mb-1">
                    <h3 className="text-lg font-medium text-white">{t('set_remote_ai')}</h3>
                    <label className="relative inline-flex items-center cursor-pointer">
                      <input
                        type="checkbox"
                        className="sr-only peer"
                        checked={remoteLlmForm.enabled}
                        onChange={e => setRemoteLlmForm(f => ({ ...f, enabled: e.target.checked }))}
                      />
                      <div className="w-11 h-6 bg-slate-600 peer-focus:outline-none rounded-full peer peer-checked:bg-blue-600 transition-colors after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:after:translate-x-full" />
                    </label>
                  </div>
                  <p className="text-xs text-slate-500 mb-4">{t('set_remote_hint')}</p>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">{t('set_gw_url')}</label>
                      <input
                        type="text"
                        value={remoteLlmForm.url}
                        onChange={e => setRemoteLlmForm(f => ({ ...f, url: e.target.value }))}
                        placeholder="https://llm-gateway.ornek-sirket.com"
                        className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-200 text-sm font-mono focus:outline-none focus:border-blue-500"
                      />
                      <p className="text-xs text-slate-500 mt-1">{t('set_root_url')}</p>
                    </div>
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">Model</label>
                      <input
                        type="text"
                        value={remoteLlmForm.model}
                        onChange={e => setRemoteLlmForm(f => ({ ...f, model: e.target.value }))}
                        placeholder="vllm-gpt-oss/openai/gpt-oss-120b"
                        className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-200 text-sm font-mono focus:outline-none focus:border-blue-500"
                      />
                    </div>
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">
                        Virtual Key <span className="text-slate-500 font-normal">{t('set_vk_rec')}</span>
                      </label>
                      <input
                        type="password"
                        value={remoteLlmForm.virtual_key}
                        onChange={e => setRemoteLlmForm(f => ({ ...f, virtual_key: e.target.value, clear_virtual_key: false }))}
                        placeholder={
                          generalSettings?.remote_llm?.virtual_key_set
                            ? t('set_stored_change', { masked: generalSettings.remote_llm.virtual_key_masked || '••••' })
                            : 'sk-bf-… → x-bf-vk'
                        }
                        className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-200 text-sm font-mono focus:outline-none focus:border-blue-500"
                      />
                      <p className="text-xs text-slate-500 mt-1">{t('set_vk_hint')}</p>
                      {generalSettings?.remote_llm?.virtual_key_set && (
                        <label className="mt-2 flex items-center gap-2 text-xs text-slate-400 cursor-pointer">
                          <input
                            type="checkbox"
                            checked={remoteLlmForm.clear_virtual_key}
                            onChange={e => setRemoteLlmForm(f => ({
                              ...f,
                              clear_virtual_key: e.target.checked,
                              virtual_key: e.target.checked ? '' : f.virtual_key,
                            }))}
                            className="rounded border-slate-600"
                          />
                          {t('set_clear_vk')}
                        </label>
                      )}
                    </div>
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">
                        API Key <span className="text-slate-500 font-normal">{t('set_api_old')}</span>
                      </label>
                      <input
                        type="password"
                        value={remoteLlmForm.api_key}
                        onChange={e => setRemoteLlmForm(f => ({ ...f, api_key: e.target.value }))}
                        placeholder={generalSettings?.remote_llm?.api_key_set ? t('set_stored_change', { masked: generalSettings.remote_llm.api_key_masked }) : t('set_auth_no_bearer')}
                        className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-200 text-sm font-mono focus:outline-none focus:border-blue-500"
                      />
                      <p className="text-xs text-slate-500 mt-1">{t('set_gw_key_hint')}</p>
                    </div>

                    <div className="border-t border-white/[0.06] pt-4">
                      <div className="flex items-center justify-between mb-1">
                        <label className="block text-sm text-slate-300">{t('set_ssl_verify')}</label>
                        <label className="relative inline-flex items-center cursor-pointer">
                          <input
                            type="checkbox"
                            className="sr-only peer"
                            checked={remoteLlmForm.verify_ssl}
                            onChange={e => setRemoteLlmForm(f => ({ ...f, verify_ssl: e.target.checked }))}
                          />
                          <div className="w-11 h-6 bg-slate-600 peer-focus:outline-none rounded-full peer peer-checked:bg-blue-600 transition-colors after:content-[''] after:absolute after:top-0.5 after:left-[2px] after:bg-white after:rounded-full after:h-5 after:w-5 after:transition-all peer-checked:after:translate-x-full" />
                        </label>
                      </div>
                      <p className="text-xs text-slate-500 mb-3">{t('set_ssl_hint')}</p>
                      <label className="block text-sm text-slate-300 mb-2">{t('set_ca_path')}</label>
                      <input
                        type="text"
                        value={remoteLlmForm.ca_bundle}
                        onChange={e => setRemoteLlmForm(f => ({ ...f, ca_bundle: e.target.value }))}
                        placeholder="/app/certs/remote-llm-ca.pem"
                        className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-200 text-sm font-mono focus:outline-none focus:border-blue-500"
                      />
                      <p className="text-xs text-slate-500 mt-1">{t('set_ca_hint')}</p>
                    </div>

                    <div className="flex flex-wrap items-center gap-3 mt-4">
                      <button
                        onClick={testRemoteLlm}
                        disabled={remoteLlmTesting || remoteLlmSaving || !remoteLlmForm.url.trim() || !remoteLlmForm.model.trim()}
                        className="px-4 py-2 bg-slate-700 hover:bg-slate-600 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors border border-slate-500/50">
                        {remoteLlmTesting ? t('set_testing') : t('set_test_conn')}
                      </button>
                      <button
                        onClick={saveRemoteLlm}
                        disabled={remoteLlmSaving || remoteLlmTesting}
                        className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors">
                        {remoteLlmSaving ? t('saving') : t('save')}
                      </button>
                      {remoteLlmSaved && <span className="text-green-400 text-sm">{t('saved')}</span>}
                      {remoteLlmError && <span className="text-red-400 text-sm">{remoteLlmError}</span>}
                      {remoteLlmTestMsg && (
                        <span className={`text-sm ${remoteLlmTestMsg.ok ? 'text-green-400' : 'text-red-400'}`}>
                          {remoteLlmTestMsg.text}
                        </span>
                      )}
                    </div>
                  </div>
                </div>

                {generalSettings?.remote_llm?.enabled ? (
                  <div className="bg-blue-500/10 border border-blue-500/30 rounded-xl p-4 flex items-center space-x-3">
                    <span className="text-sm font-semibold text-blue-400">OK</span>
                    <div><p className="text-blue-400 font-medium">{t('set_ai_remote')}</p><p className="text-blue-400/70 text-sm">{t('set_ai_remote_sub', { model: generalSettings.remote_llm.model })}</p></div>
                  </div>
                ) : (
                  <div className="bg-green-500/10 border border-green-500/30 rounded-xl p-4 flex items-center space-x-3">
                    <span className="text-sm font-semibold text-green-400">OK</span>
                    <div><p className="text-green-400 font-medium">{t('set_ai_local')}</p><p className="text-green-400/70 text-sm">{t('set_ai_local_sub')}</p></div>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* ═══ Kurumsal Kimlik ═══ */}
          {activeTab === 'branding' && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-1">{t('set_tab_branding')}</h2>
              <p className="text-slate-400 text-sm mb-6">{t('set_brand_intro')}</p>
              <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-6 max-w-2xl">
                <div className="space-y-5">
                  <div>
                    <label className="block text-sm text-slate-300 mb-2">{t('set_app_name')}</label>
                    <div className="flex items-center gap-3">
                      <input
                        type="text"
                        value={brandingName}
                        onChange={e => setBrandingName(e.target.value)}
                        maxLength={64}
                        placeholder="datatem AI"
                        className="flex-1 bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-200 text-sm focus:outline-none focus:border-blue-500"
                      />
                      <button
                        onClick={saveBrandingName}
                        disabled={brandingNameSaving || !brandingName.trim()}
                        className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors whitespace-nowrap">
                        {brandingNameSaving ? t('saving') : t('save')}
                      </button>
                    </div>
                    {brandingNameSaved && <p className="text-green-400 text-sm mt-2">{t('saved')}</p>}
                  </div>

                  <div>
                    <label className="block text-sm text-slate-300 mb-2">{t('set_logo')}</label>
                    <div className="flex items-center gap-4">
                      <div className="w-28 h-28 rounded-xl bg-cyber-card border border-slate-600 flex items-center justify-center overflow-hidden flex-shrink-0 p-2">
                        {logoUrl ? (
                          <img src={logoUrl} alt={appName} className="w-full h-full object-contain" />
                        ) : (
                          <span className="text-slate-500 text-xs">{t('set_no_logo')}</span>
                        )}
                      </div>
                      <div className="flex-1 min-w-0 space-y-2">
                        <input
                          type="file"
                          accept="image/png,image/jpeg,image/svg+xml,image/webp"
                          onChange={e => setLogoFile(e.target.files?.[0] || null)}
                          className="block w-full text-sm text-slate-400 file:mr-3 file:py-2 file:px-3 file:rounded-lg file:border-0 file:bg-slate-700 file:text-slate-200 file:text-sm hover:file:bg-slate-600"
                        />
                        <div className="flex items-center gap-3">
                          <button
                            onClick={uploadLogo}
                            disabled={!logoFile || logoUploading}
                            className="px-4 py-2 bg-blue-600 hover:bg-blue-700 disabled:opacity-50 text-white text-sm font-medium rounded-lg transition-colors">
                            {logoUploading ? t('uploading') : t('upload')}
                          </button>
                          {logoUrl && (
                            <button
                              onClick={removeLogo}
                              className="px-4 py-2 bg-white/[0.07] hover:bg-slate-600 border border-slate-600 text-slate-300 text-sm font-medium rounded-lg transition-colors">
                              {t('remove')}
                            </button>
                          )}
                        </div>
                        <p className="text-xs text-slate-500">{t('set_logo_types')}</p>
                      </div>
                    </div>
                  </div>
                  {brandingError && <p className="text-red-400 text-sm">{brandingError}</p>}
                </div>
              </div>
            </div>
          )}

          {/* ═══ WinRM Credentials ═══ */}
          {activeTab === 'winrm' && (
            <div>
              <div className="flex flex-wrap items-start gap-3 mb-6">
                <div className="flex-1 min-w-0">
                  <h2 className="text-xl font-semibold text-white">{t('set_winrm_title')}</h2>
                  <p className="text-slate-400 text-sm mt-1">{t('set_winrm_hint')}</p>
                </div>
                {!winrmEditing && (
                  <div className="flex gap-2">
                    {winrmCred?.configured && (
                      <button
                        onClick={() => applyWinrm.mutate()}
                        disabled={applyWinrm.isPending}
                        className="px-3 py-2 bg-gradient-to-r from-emerald-600 to-emerald-700 text-white rounded-lg hover:from-emerald-500 hover:to-emerald-600 transition-all text-sm disabled:opacity-50 whitespace-nowrap">
                        {applyWinrm.isPending ? t('applying') : <span className="inline-flex items-center gap-1.5"><Monitor size={14} strokeWidth={2} /> {t('set_apply_all')}</span>}
                      </button>
                    )}
                    <button
                      onClick={() => {
                        setWinrmForm({ username: winrmCred?.username || '', password: '', port: winrmCred?.port || 5985, use_https: winrmCred?.use_https || false })
                        setWinrmEditing(true)
                        setWinrmApplyResult(null)
                      }}
                      className="px-3 py-2 bg-gradient-to-r from-blue-600 to-blue-700 text-white rounded-lg hover:from-blue-500 hover:to-blue-600 transition-all text-sm whitespace-nowrap">
                      {winrmCred?.configured ? t('set_edit_pencil') : t('set_add_cred_plus')}
                    </button>
                  </div>
                )}
              </div>

              {/* Form */}
              {winrmEditing && (
                <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-6 mb-6">
                  <h3 className="text-lg font-medium text-white mb-4">
                    {winrmCred?.configured ? t('set_winrm_edit') : t('set_winrm_add')}
                  </h3>
                  <div className="space-y-4">
                    <div className="grid grid-cols-3 gap-4">
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">{t('username_star')}</label>
                        <input type="text" required value={winrmForm.username}
                          onChange={e => setWinrmForm({ ...winrmForm, username: e.target.value })}
                          className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                          placeholder={t('set_winrm_user_ph')} />
                      </div>
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">{winrmCred?.configured ? `${t('password_label')} ${t('empty_keep')}` : t('password_star')}</label>
                        <input type="password" value={winrmForm.password}
                          onChange={e => setWinrmForm({ ...winrmForm, password: e.target.value })}
                          className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500"
                          placeholder="••••••••" />
                      </div>
                      <div>
                        <label className="block text-sm text-slate-300 mb-1.5">{t('set_winrm_port')}</label>
                        <input type="number" value={winrmForm.port}
                          onChange={e => setWinrmForm({ ...winrmForm, port: parseInt(e.target.value) || 5985 })}
                          className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2.5 text-white focus:outline-none focus:ring-2 focus:ring-blue-500" />
                      </div>
                    </div>
                    <div className="flex items-center gap-3">
                      <input type="checkbox" id="winrm-https" checked={winrmForm.use_https}
                        onChange={e => setWinrmForm({ ...winrmForm, use_https: e.target.checked })}
                        className="w-4 h-4 text-blue-600 bg-white/[0.07] border-slate-600 rounded" />
                      <label htmlFor="winrm-https" className="text-sm text-slate-300 cursor-pointer">
                        {t('set_use_https')} <span className="text-slate-500">{t('set_https_need')}</span>
                      </label>
                    </div>
                    <div className="flex justify-between items-center pt-2">
                      {saveWinrm.isError && (
                        <p className="text-red-400 text-sm">{(saveWinrm.error as Error)?.message}</p>
                      )}
                      <div className="flex gap-3 ml-auto">
                        <button type="button" onClick={() => setWinrmEditing(false)}
                          className="px-4 py-2 bg-white/[0.07] text-white rounded-lg hover:bg-slate-600 text-sm">{t('cancel')}</button>
                        <button
                          onClick={() => saveWinrm.mutate(winrmForm)}
                          disabled={saveWinrm.isPending || !winrmForm.username || (!winrmForm.password && !winrmCred?.configured)}
                          className="px-6 py-2 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-lg hover:from-green-500 hover:to-green-600 disabled:opacity-50 text-sm">
                          {saveWinrm.isPending ? t('saving') : t('save')}
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              )}

              {/* Apply result */}
              {winrmApplyResult && (
                <div className="mb-6 p-4 bg-green-500/10 border border-green-500/30 rounded-xl text-sm text-green-300">
                  <p className="font-medium mb-1">
                    ✓ {winrmApplyResult.message || t('set_win_applied', { n: winrmApplyResult.applied_to })}
                  </p>
                  {winrmApplyResult.servers.length > 0 && (
                    <p className="text-green-400/70 text-xs">{winrmApplyResult.servers.join(', ')}</p>
                  )}
                </div>
              )}

              {/* Credential card (if configured) */}
              {!winrmCred?.configured && !winrmEditing ? (
                <div className="text-center py-12 bg-cyber-deep/30 rounded-xl border border-dashed border-white/[0.06]">
                  <span className="text-2xl font-bold text-blue-400 block mb-4">WIN</span>
                  <p className="text-slate-400 mb-2">{t('set_no_winrm')}</p>
                  <p className="text-slate-500 text-sm">{t('set_no_winrm_hint')}</p>
                </div>
              ) : winrmCred?.configured && !winrmEditing && (
                <div className="space-y-3">
                  <div className="rounded-xl border bg-blue-500/5 border-blue-500/30 p-4">
                    <div className="flex items-center justify-between">
                      <div className="flex items-center space-x-4">
                        <div className="w-11 h-11 rounded-lg flex items-center justify-center bg-gradient-to-br from-blue-500 to-blue-600">
                          <span className="text-xs font-bold text-white">WIN</span>
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2 flex-wrap">
                            <p className="text-white font-medium">{t('set_winrm_global')}</p>
                            <span className="text-[10px] px-2 py-0.5 rounded-full bg-blue-500/20 text-blue-400 border border-blue-500/30 font-medium">{t('default_badge')}</span>
                          </div>
                          <p className="text-slate-400 text-sm font-mono mt-0.5">
                            {winrmCred.username}@:{winrmCred.port}
                            {winrmCred.has_password && <span className="text-green-400 ml-2">{t('set_pw_dot')}</span>}
                            <span className={`ml-2 text-xs ${winrmCred.use_https ? 'text-green-400' : 'text-slate-500'}`}>
                              {winrmCred.use_https ? 'HTTPS' : 'HTTP'}
                            </span>
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-1.5">
                        <button
                          onClick={() => applyWinrm.mutate()}
                          disabled={applyWinrm.isPending}
                          className="px-3 py-1.5 text-xs bg-green-500/10 text-green-400 border border-green-500/30 rounded-lg hover:bg-green-500/20 font-medium disabled:opacity-50">
                          {applyWinrm.isPending ? t('applying') : t('set_apply_all')}
                        </button>
                        <button
                          onClick={() => {
                            setWinrmForm({ username: winrmCred.username || '', password: '', port: winrmCred.port || 5985, use_https: winrmCred.use_https || false })
                            setWinrmEditing(true)
                          }}
                          className="px-3 py-1.5 text-xs bg-blue-500/10 text-blue-400 border border-blue-500/30 rounded-lg hover:bg-blue-500/20">
                          Düzenle
                        </button>
                        <button
                          onClick={async () => {
                            const ok = await showConfirm(t('set_del_winrm'))
                            if (ok) deleteWinrm.mutate()
                          }}
                          className="px-3 py-1.5 text-xs bg-red-500/10 text-red-400 border border-red-500/30 rounded-lg hover:bg-red-500/20">
                          {t('delete')}
                        </button>
                      </div>
                    </div>
                  </div>
                  <p className="text-slate-500 text-xs px-1">{t('set_winrm_auto')}</p>
                </div>
              )}
            </div>
          )}

          {/* ═══ RAG ═══ */}
          {activeTab === 'rag' && (
            <RagTab />
          )}

          {/* ═══ Monitoring ═══ */}
          {activeTab === 'monitoring' && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-6">{t('set_mon_title')}</h2>
              <div className="space-y-6">
                <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-6">
                  <h3 className="text-lg font-medium text-white mb-1">Prometheus</h3>
                  <p className="text-xs text-slate-500 mb-4">{t('set_prom_hint')}</p>
                  <div className="space-y-4">
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">{t('set_prom_url')}</label>
                      <input
                        type="text"
                        value={promForm.prometheus_url}
                        onChange={e => setPromForm(f => ({ ...f, prometheus_url: e.target.value }))}
                        placeholder="http://prometheus:9090"
                        className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-200 text-sm font-mono focus:outline-none focus:border-blue-500"
                      />
                    </div>
                    <div>
                      <label className="block text-sm text-slate-300 mb-2">
                        Pushgateway URL
                        <span className="text-xs text-slate-500 ml-2">{t('set_optional_unused')}</span>
                      </label>
                      <input
                        type="text"
                        value={promForm.pushgateway_url}
                        onChange={e => setPromForm(f => ({ ...f, pushgateway_url: e.target.value }))}
                        placeholder="http://pushgateway:9091"
                        className="w-full bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-200 text-sm font-mono focus:outline-none focus:border-blue-500"
                      />
                      <p className="text-xs text-slate-500 mt-1">{t('set_pg_hint')}</p>
                    </div>

                    <div>
                      <label className="block text-sm text-slate-300 mb-2">
                        {t('set_linux_jobs')}
                        <span className="text-xs text-slate-500 ml-2">{t('set_jobs_multi')}</span>
                      </label>
                      <div className="flex flex-wrap gap-2 mb-2">
                        {promForm.linux_jobs.map((job) => (
                          <span
                            key={job}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-blue-500/15 border border-blue-500/30 text-blue-200 text-xs font-mono"
                          >
                            {job}
                            <button
                              type="button"
                              onClick={() => setPromForm(f => ({
                                ...f,
                                linux_jobs: f.linux_jobs.filter(j => j !== job),
                              }))}
                              className="text-blue-300/80 hover:text-white"
                              title={t('remove')}
                            >
                              ×
                            </button>
                          </span>
                        ))}
                      </div>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={promForm.linux_job_input}
                          onChange={e => setPromForm(f => ({ ...f, linux_job_input: e.target.value }))}
                          onKeyDown={e => {
                            if (e.key === 'Enter') {
                              e.preventDefault()
                              const v = promForm.linux_job_input.trim()
                              if (v && !promForm.linux_jobs.includes(v)) {
                                setPromForm(f => ({
                                  ...f,
                                  linux_jobs: [...f.linux_jobs, v],
                                  linux_job_input: '',
                                }))
                              }
                            }
                          }}
                          placeholder={t('set_job_ph')}
                          className="flex-1 bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-200 text-sm font-mono focus:outline-none focus:border-blue-500"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            const v = promForm.linux_job_input.trim()
                            if (v && !promForm.linux_jobs.includes(v)) {
                              setPromForm(f => ({
                                ...f,
                                linux_jobs: [...f.linux_jobs, v],
                                linux_job_input: '',
                              }))
                            }
                          }}
                          className="px-3 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded-lg"
                        >
                          {t('add')}
                        </button>
                      </div>
                    </div>

                    <div>
                      <label className="block text-sm text-slate-300 mb-2">
                        {t('set_win_jobs')}
                        <span className="text-xs text-slate-500 ml-2">{t('set_jobs_multi_short')}</span>
                      </label>
                      <div className="flex flex-wrap gap-2 mb-2">
                        {promForm.windows_jobs.map((job) => (
                          <span
                            key={job}
                            className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-md bg-emerald-500/15 border border-emerald-500/30 text-emerald-200 text-xs font-mono"
                          >
                            {job}
                            <button
                              type="button"
                              onClick={() => setPromForm(f => ({
                                ...f,
                                windows_jobs: f.windows_jobs.filter(j => j !== job),
                              }))}
                              className="text-emerald-300/80 hover:text-white"
                              title={t('remove')}
                            >
                              ×
                            </button>
                          </span>
                        ))}
                      </div>
                      <div className="flex gap-2">
                        <input
                          type="text"
                          value={promForm.windows_job_input}
                          onChange={e => setPromForm(f => ({ ...f, windows_job_input: e.target.value }))}
                          onKeyDown={e => {
                            if (e.key === 'Enter') {
                              e.preventDefault()
                              const v = promForm.windows_job_input.trim()
                              if (v && !promForm.windows_jobs.includes(v)) {
                                setPromForm(f => ({
                                  ...f,
                                  windows_jobs: [...f.windows_jobs, v],
                                  windows_job_input: '',
                                }))
                              }
                            }
                          }}
                          placeholder={t('set_job_ph')}
                          className="flex-1 bg-cyber-card border border-slate-600 rounded-lg px-4 py-2 text-slate-200 text-sm font-mono focus:outline-none focus:border-blue-500"
                        />
                        <button
                          type="button"
                          onClick={() => {
                            const v = promForm.windows_job_input.trim()
                            if (v && !promForm.windows_jobs.includes(v)) {
                              setPromForm(f => ({
                                ...f,
                                windows_jobs: [...f.windows_jobs, v],
                                windows_job_input: '',
                              }))
                            }
                          }}
                          className="px-3 py-2 bg-slate-700 hover:bg-slate-600 text-white text-sm rounded-lg"
                        >
                          {t('add')}
                        </button>
                      </div>
                    </div>

                    <div className="flex items-center gap-3">
                      <button
                        onClick={savePrometheus}
                        disabled={promSaving || !promForm.prometheus_url.trim() || promForm.linux_jobs.length === 0}
                        className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white text-sm font-medium rounded-lg"
                      >
                        {promSaving ? t('saving') : t('save')}
                      </button>
                      {promSaved && <span className="text-green-400 text-sm">{t('saved')}</span>}
                      {promError && <span className="text-red-400 text-sm">{promError}</span>}
                    </div>

                    {/* Yönetim Sunucu IP */}
                    <div className="border-t border-white/[0.06] pt-4">
                      <label className="block text-sm text-slate-300 mb-1">
                        {t('set_mgmt_ip')}
                        <span className="text-xs text-slate-500 ml-2">{t('set_mgmt_for')}</span>
                      </label>
                      <p className="text-xs text-slate-500 mb-2">
                        {t('set_mgmt_hint')}
                        {generalSettings?.detected_management_ip && (
                          <span className="text-blue-400 ml-1">{t('set_auto_detect', { ip: generalSettings.detected_management_ip })}</span>
                        )}
                      </p>
                      <div className="flex items-center gap-3">
                        <input
                          type="text"
                          defaultValue={generalSettings?.management_server_ip || ''}
                          id="mgmt-ip-input"
                          placeholder={generalSettings?.detected_management_ip || '192.168.1.x'}
                          className="bg-cyber-card border border-slate-600 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500 w-48 font-mono"
                        />
                        <button
                          onClick={async () => {
                            const val = (document.getElementById('mgmt-ip-input') as HTMLInputElement).value.trim()
                            const ip = val || generalSettings?.detected_management_ip || ''
                            if (!ip) { alert(t('set_enter_ip')); return }
                            const r = await fetch('/api/v1/settings/management-server-ip', {
                              method: 'PUT', headers: {'Content-Type':'application/json'},
                              body: JSON.stringify({ip})
                            })
                            if (r.ok) alert(t('set_mgmt_saved', { ip }))
                            else alert(t('error_generic'))
                          }}
                          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium"
                        >
                          {t('save')}
                        </button>
                      </div>
                    </div>

                    <div className="border-t border-white/[0.06] pt-4">
                      <label className="block text-sm text-slate-300 mb-2">{t('set_ret_days')}</label>
                      <div className="flex items-center gap-3">
                        <select
                          value={metricRetentionDays}
                          onChange={e => setMetricRetentionDays(Number(e.target.value))}
                          className="bg-cyber-card border border-slate-600 rounded-lg px-3 py-2 text-slate-200 focus:outline-none focus:border-blue-500"
                        >
                          <option value={7}>{t('days_n', { n: 7 })}</option>
                          <option value={15}>{t('days_n', { n: 15 })}</option>
                          <option value={30}>{t('days_n', { n: 30 })}</option>
                          <option value={60}>{t('days_n', { n: 60 })}</option>
                          <option value={90}>{t('days_n', { n: 90 })}</option>
                          <option value={180}>{t('days_n', { n: 180 })}</option>
                          <option value={365}>{t('days_n', { n: 365 })}</option>
                        </select>
                        <button
                          onClick={async () => {
                            const currentDays = generalSettings?.metric_retention_days ?? 30
                            const isDecrease = metricRetentionDays < currentDays
                            const message = isDecrease
                              ? t('set_ret_down', { from: currentDays, to: metricRetentionDays })
                              : t('set_ret_set', { n: metricRetentionDays })
                            if (!await showConfirm(message)) return
                            saveMetricRetention.mutate(metricRetentionDays)
                          }}
                          disabled={saveMetricRetention.isPending}
                          className="px-4 py-2 bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white rounded-lg text-sm font-medium"
                        >
                          {saveMetricRetention.isPending ? t('saving') : t('save')}
                        </button>
                        {retentionSaved && <span className="text-green-400 text-sm font-medium">{t('saved')}</span>}
                      </div>
                      <p className="text-xs text-slate-500 mt-2">{t('set_ret_drop_hint')}</p>
                    </div>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4">
                  <a href={`${window.location.protocol}//${window.location.hostname}:9090`} target="_blank" rel="noopener noreferrer" className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4 hover:border-slate-600 transition-colors flex items-center space-x-3">
                    <div className="w-8 h-8 rounded bg-orange-500/20 flex items-center justify-center flex-shrink-0"></div><div><p className="text-white font-medium">Prometheus</p><p className="text-slate-400 text-sm">{t('set_metrics_queries')}</p></div>
                  </a>
                  <a href={`${window.location.protocol}//${window.location.hostname}:9091`} target="_blank" rel="noopener noreferrer" className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-4 hover:border-slate-600 transition-colors flex items-center space-x-3">
                    <BarChart3 size={24} strokeWidth={1.8} className="text-slate-300" /><div><p className="text-white font-medium">Pushgateway</p><p className="text-slate-400 text-sm">{t('set_push_metrics')}</p></div>
                  </a>
                </div>
              </div>
            </div>
          )}

          {/* ═══ Uygulama geneli Güvenlik ═══ */}
          {activeTab === 'security' && (
            <SecuritySettings />
          )}

          {/* ═══ Gelişmiş Ayarlar ═══ */}
          {activeTab === 'advanced' && (
            <AdvancedSettingsTab />
          )}

          {/* ═══ Platform Durumu / Yedek / Update ═══ */}
          {activeTab === 'platform-status' && isAdmin && (
            <PlatformStatusTab />
          )}

          {activeTab === 'config-backup' && isAdmin && (
            <ConfigBackupTab />
          )}

          {activeTab === 'platform-update' && isAdmin && (
            <PlatformUpdateTab />
          )}

          {/* ═══ About ═══ */}
          {activeTab === 'about' && (
            <div>
              <h2 className="text-xl font-semibold text-white mb-6">{t('set_about')}</h2>
              <div className="bg-cyber-deep/50 rounded-[10px] border border-white/[0.06] p-6">
                <div className="flex items-center space-x-4 mb-6">
                  {logoUrl ? (
                    <img src={logoUrl} alt={appName} className="w-16 h-16 rounded-2xl object-contain shadow-lg bg-cyber-card border border-white/[0.06]" />
                  ) : (
                    <div className="w-16 h-16 bg-gradient-to-br from-blue-500 to-blue-600 rounded-2xl flex items-center justify-center shadow-lg">
                      <span className="text-white font-bold text-2xl">SM</span>
                    </div>
                  )}
                  <div>
                    <h3 className="text-2xl font-bold text-white">{appName}</h3>
                    <p className="text-slate-400">
                      {version ? `v${version}` : '—'} — {t('set_ai_infra')}
                    </p>
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-4 pt-4">
                  <div className="bg-cyber-card rounded-lg p-4"><p className="text-slate-400 text-sm">Backend</p><p className="text-white font-medium">FastAPI + Python</p></div>
                  <div className="bg-cyber-card rounded-lg p-4"><p className="text-slate-400 text-sm">Frontend</p><p className="text-white font-medium">React + TypeScript</p></div>
                  <div className="bg-cyber-card rounded-lg p-4"><p className="text-slate-400 text-sm">Database</p><p className="text-white font-medium">PostgreSQL</p></div>
                  <div className="bg-cyber-card rounded-lg p-4"><p className="text-slate-400 text-sm">AI</p><p className="text-white font-medium">Ollama + LLaMA</p></div>
                </div>
              </div>
            </div>
          )}

          {/* ═══ Tehlikeli Bölge ═══ */}
          {activeTab === 'danger' && isAdmin && (
            <DangerZoneTab />
          )}
        </div>
      </div>

      {/* ═══ Apply Modal (Linux SSH only) ═══ */}
      {applyModal.open && (
        <div className="fixed inset-0 bg-black/50 backdrop-blur-sm flex items-center justify-center z-50">
          <div className="bg-cyber-card rounded-[10px] border border-white/[0.06] p-6 w-full max-w-2xl shadow-2xl max-h-[80vh] overflow-hidden flex flex-col">
            <div className="flex items-center justify-between mb-4">
              <div>
                <h2 className="text-xl font-semibold text-white">{t('set_apply_cred')}</h2>
                <p className="text-sm text-slate-400 mt-1">
                  {t('set_apply_linux_only', { name: applyModal.credName })}
                </p>
                {windowsServers.length > 0 && (
                  <p className="text-xs text-slate-500 mt-1">
                    {t('set_win_skipped', { n: windowsServers.length })}
                  </p>
                )}
              </div>
              <button onClick={() => setApplyModal({ open: false, credId: 0, credName: '' })} className="text-slate-400 hover:text-white text-xl">✕</button>
            </div>

            <div className="flex gap-3 mb-4">
              <button onClick={() => setApplyMode('all')}
                className={`flex-1 py-3 rounded-lg text-sm font-medium transition-all ${applyMode === 'all' ? 'bg-blue-600/20 text-blue-400 border-2 border-blue-500/50' : 'bg-white/[0.07] text-slate-400 border-2 border-transparent hover:bg-slate-600'}`}>
                {t('set_all_linux', { n: linuxServers.length })}
              </button>
              <button onClick={() => setApplyMode('select')}
                className={`flex-1 py-3 rounded-lg text-sm font-medium transition-all ${applyMode === 'select' ? 'bg-blue-600/20 text-blue-400 border-2 border-blue-500/50' : 'bg-white/[0.07] text-slate-400 border-2 border-transparent hover:bg-slate-600'}`}>
                {t('set_sel_linux', { n: selectedServerIds.length })}
              </button>
            </div>

            {applyMode === 'select' && (
              <div className="flex-1 overflow-y-auto mb-4 border border-white/[0.06] rounded-lg max-h-60">
                {linuxServers.map(s => (
                  <label key={s.id} className={`flex items-center gap-3 px-4 py-2.5 cursor-pointer hover:bg-white/[0.06]/50 border-b border-white/[0.04] last:border-b-0 ${selectedServerIds.includes(s.id) ? 'bg-blue-500/10' : ''}`}>
                    <input type="checkbox" checked={selectedServerIds.includes(s.id)}
                      onChange={() => setSelectedServerIds(prev => prev.includes(s.id) ? prev.filter(x => x !== s.id) : [...prev, s.id])}
                      className="w-4 h-4 text-blue-600 bg-white/[0.07] border-slate-600 rounded" />
                    <span className="text-sm text-white">{s.name}</span>
                    <span className="text-xs text-slate-500 font-mono">{s.ip_address}</span>
                    {s.ai_ready && <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/20 text-blue-400 border border-blue-500/30 ml-auto">AI</span>}
                  </label>
                ))}
                {linuxServers.length === 0 && (
                  <p className="px-4 py-6 text-sm text-slate-500 text-center">{t('set_no_linux')}</p>
                )}
              </div>
            )}

            <div className="flex items-center gap-2 mb-2">
              <input type="checkbox" checked={setAiReady} onChange={e => setSetAiReady(e.target.checked)}
                className="w-4 h-4 text-blue-600 bg-white/[0.07] border-slate-600 rounded" />
              <span className="text-sm text-slate-300">{t('set_mark_ai')}</span>
            </div>
            {setAiReady && (
              <p className="text-xs text-amber-400/90 mb-4 leading-relaxed">
                {t('set_lockout_warn')}
              </p>
            )}
            {!setAiReady && <div className="mb-4" />}

            <div className="flex justify-end gap-3 pt-3 border-t border-white/[0.06]">
              <button onClick={() => setApplyModal({ open: false, credId: 0, credName: '' })}
                className="px-4 py-2.5 bg-white/[0.07] text-white rounded-lg hover:bg-slate-600 text-sm">{t('cancel')}</button>
              <button onClick={() => applyCred.mutate({
                credId: applyModal.credId,
                serverIds: applyMode === 'all' ? linuxServers.map(s => s.id) : selectedServerIds,
                aiReady: setAiReady,
              })}
                disabled={applyCred.isPending || linuxServers.length === 0 || (applyMode === 'select' && selectedServerIds.length === 0)}
                className="px-6 py-2.5 bg-gradient-to-r from-green-600 to-green-700 text-white rounded-lg hover:from-green-500 hover:to-green-600 disabled:opacity-50 font-medium text-sm">
                {applyCred.isPending ? t('applying') : t('set_apply_n_linux', { n: applyMode === 'all' ? linuxServers.length : selectedServerIds.length })}
              </button>
            </div>

            {applyCred.isError && (
              <div className="mt-3 p-3 bg-red-500/10 border border-red-500/30 rounded-lg text-sm text-red-400">
                {applyCred.error?.message || t('error_generic')}
              </div>
            )}
          </div>
        </div>
      )}
      {confirmState && <ConfirmModal message={confirmState.msg} onConfirm={() => { confirmState.resolve(true); setConfirmState(null) }} onCancel={() => { confirmState.resolve(false); setConfirmState(null) }} />}
    </div>
  )
}

export default Settings
