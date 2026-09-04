/**
 * Özel Raporlar (Custom Reports)
 * ================================
 * Hibrit "AI keşif + deterministik dondurma" akışı:
 *   1) Kullanıcı doğal dilde bir soru yazar (sohbet gibi) → backend agentic
 *      READ_ONLY tool-loop ile çözer, çağrılan tool aday(lar)ını + render
 *      önizlemesini döner (`POST /custom-reports/resolve`). HİÇBİR ŞEY KAYDEDİLMEZ.
 *   2) Kullanıcı bir adayı seçip başlık verir → `POST /custom-reports/` ile
 *      (tool_name + tool_args) birebir dondurulup kaydedilir.
 *   3) Kayıtlı her rapor `POST /custom-reports/{id}/run` ile İSTENİLDİĞİ KADAR
 *      tekrar çalıştırılabilir — LLM'e HİÇ gidilmez, tam deterministik.
 *
 * Erişim: 'custom_reports' modülü (varsayılan yalnız Admin; Kullanıcı Yönetimi
 * sayfasından diğer kullanıcılara da atanabilir).
 */
import { useState } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  FileBarChart2, Search, Save, RefreshCw, Trash2, Eye, X, Lock,
  AlertTriangle, CheckCircle2, XCircle, Clock, Sparkles,
} from 'lucide-react'
import { API_BASE_URL } from '../config/api'
import { useAuth } from '../auth/AuthContext'
import { useT } from '../i18n/LocaleProvider'
import { chatMarkdownComponents } from '../components/chatMarkdown'

// ── Types ─────────────────────────────────────────────────────────────────

type Platform = 'linux' | 'windows' | 'virt' | 'openshift' | 'exadata' | 'unified'
type Directive = 'table' | 'json' | 'brief'

interface Candidate {
  tool: string
  args: Record<string, unknown>
  label: string
  capturable: boolean
  ok: boolean
  preview: string
  domains: string[]
}

interface ResolveResult {
  ok: boolean
  question: string
  platform: string
  output_directive: string
  tools_used?: string[]
  candidates: Candidate[]
  note?: string
}

interface ReportDefinition {
  id: number
  title: string
  description: string | null
  platform: string
  tool_name: string
  tool_args: Record<string, unknown>
  output_directive: string | null
  source_question: string | null
  created_by: number | null
  created_at: string | null
  updated_at: string | null
  is_active: boolean
  last_run_at: string | null
  last_ok: boolean | null
  last_rendered: string | null
  last_error: string | null
}

const PLATFORMS: { id: Platform; labelKey: 'cr_platform_linux' | 'cr_platform_windows' | 'cr_platform_virt' | 'cr_platform_openshift' | 'cr_platform_exadata' | 'cr_platform_unified' }[] = [
  { id: 'unified', labelKey: 'cr_platform_unified' },
  { id: 'virt', labelKey: 'cr_platform_virt' },
  { id: 'linux', labelKey: 'cr_platform_linux' },
  { id: 'windows', labelKey: 'cr_platform_windows' },
  { id: 'openshift', labelKey: 'cr_platform_openshift' },
  { id: 'exadata', labelKey: 'cr_platform_exadata' },
]

const DIRECTIVES: { id: Directive; labelKey: 'cr_format_table' | 'cr_format_json' | 'cr_format_brief' }[] = [
  { id: 'table', labelKey: 'cr_format_table' },
  { id: 'json', labelKey: 'cr_format_json' },
  { id: 'brief', labelKey: 'cr_format_brief' },
]

async function api(method: string, path: string, body?: unknown) {
  const r = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: { 'Content-Type': 'application/json' },
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  if (!r.ok) {
    const e = await r.json().catch(() => ({ detail: r.statusText }))
    throw new Error(e.detail ?? r.statusText)
  }
  return r.json()
}

// ── Markdown önizleme ────────────────────────────────────────────────────────

function Preview({ text }: { text: string }) {
  return (
    <div className="chat-response-content prose prose-invert prose-sm max-w-none min-w-0 [&_table]:text-xs">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>{text}</ReactMarkdown>
    </div>
  )
}

// ── Yeni Özel Rapor sekmesi ──────────────────────────────────────────────────

function NewReportTab({ onSaved }: { onSaved: () => void }) {
  const t = useT()
  const [question, setQuestion] = useState('')
  const [platform, setPlatform] = useState<Platform>('unified')
  const [directive, setDirective] = useState<Directive>('table')
  const [result, setResult] = useState<ResolveResult | null>(null)
  const [selected, setSelected] = useState<Candidate | null>(null)
  const [title, setTitle] = useState('')
  const [description, setDescription] = useState('')
  const [saveOk, setSaveOk] = useState(false)

  const resolveMut = useMutation({
    mutationFn: () => api('POST', '/custom-reports/resolve', {
      question, platform, output_directive: directive,
    }) as Promise<ResolveResult>,
    onSuccess: (r) => {
      setResult(r)
      setSelected(null)
      setSaveOk(false)
    },
  })

  const saveMut = useMutation({
    mutationFn: () => api('POST', '/custom-reports/', {
      title: title.trim(),
      description: description.trim() || undefined,
      platform,
      tool_name: selected!.tool,
      tool_args: selected!.args,
      output_directive: directive,
      source_question: question,
    }),
    onSuccess: () => {
      setSaveOk(true)
      setSelected(null)
      setTitle('')
      setDescription('')
      onSaved()
    },
  })

  function handleResolve() {
    if (!question.trim() || resolveMut.isPending) return
    resolveMut.mutate()
  }

  function handleSelect(c: Candidate) {
    if (!c.capturable) return
    setSelected(c)
    setTitle(question.trim().slice(0, 80))
    setSaveOk(false)
  }

  return (
    <div className="space-y-5">
      <div className="bg-slate-800/60 border border-slate-700 rounded-xl p-4 space-y-3">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="text-xs text-slate-400 mb-1 block">{t('cr_platform')}</label>
            <select
              value={platform}
              onChange={e => setPlatform(e.target.value as Platform)}
              className="w-full bg-slate-900/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
            >
              {PLATFORMS.map(p => <option key={p.id} value={p.id}>{t(p.labelKey)}</option>)}
            </select>
          </div>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">{t('cr_format')}</label>
            <div className="flex gap-1 bg-slate-900/60 border border-slate-700 rounded-lg p-1 w-fit">
              {DIRECTIVES.map(d => (
                <button
                  key={d.id}
                  onClick={() => setDirective(d.id)}
                  className={`px-3 py-1.5 rounded-md text-xs font-medium transition-all ${
                    directive === d.id ? 'bg-blue-600 text-white' : 'text-slate-400 hover:text-white'
                  }`}
                >
                  {t(d.labelKey)}
                </button>
              ))}
            </div>
          </div>
        </div>

        <div>
          <label className="text-xs text-slate-400 mb-1 block">{t('cr_question_label')}</label>
          <div className="flex gap-2">
            <textarea
              value={question}
              onChange={e => setQuestion(e.target.value)}
              onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); handleResolve() } }}
              placeholder={t('cr_question_ph')}
              rows={2}
              className="flex-1 bg-slate-900/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500 resize-none"
            />
            <button
              onClick={handleResolve}
              disabled={!question.trim() || resolveMut.isPending}
              className="px-4 py-2 bg-blue-600 hover:bg-blue-500 text-white rounded-lg text-sm font-medium disabled:opacity-50 flex items-center gap-2 transition-all self-start"
            >
              {resolveMut.isPending
                ? <><RefreshCw size={14} className="animate-spin" /> {t('cr_resolving')}</>
                : <><Search size={14} /> {t('cr_resolve_btn')}</>}
            </button>
          </div>
        </div>

        {resolveMut.isError && (
          <div className="flex items-center gap-2 text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2">
            <AlertTriangle size={14} />
            {t('cr_resolve_err', { msg: String((resolveMut.error as Error)?.message || '') })}
          </div>
        )}
      </div>

      {result && (
        <div className="space-y-3">
          {result.candidates.length === 0 ? (
            <div className="bg-amber-500/10 border border-amber-500/30 rounded-xl p-4 text-sm text-amber-300">
              {result.note || t('cr_no_candidates')}
            </div>
          ) : (
            <>
              <h3 className="text-sm font-medium text-slate-300 flex items-center gap-2">
                <Sparkles size={14} className="text-blue-400" /> {t('cr_candidates_title')}
              </h3>
              {result.candidates.map((c, i) => (
                <div
                  key={i}
                  className={`border rounded-xl p-4 transition-all ${
                    selected === c ? 'border-blue-500 bg-blue-500/5' : 'border-slate-700 bg-slate-800/40'
                  }`}
                >
                  <div className="flex items-center justify-between gap-3 mb-2">
                    <div className="flex items-center gap-2">
                      <code className="text-xs px-2 py-1 rounded bg-slate-900/60 text-cyan-300">{c.tool}</code>
                      <span className="text-xs text-slate-500">{c.label}</span>
                      {!c.ok && <XCircle size={13} className="text-red-400" />}
                    </div>
                    {c.capturable ? (
                      <button
                        onClick={() => handleSelect(c)}
                        className={`px-3 py-1.5 rounded-lg text-xs font-medium flex items-center gap-1.5 transition-all ${
                          selected === c
                            ? 'bg-blue-600 text-white'
                            : 'bg-slate-700 hover:bg-slate-600 text-slate-200'
                        }`}
                      >
                        <Save size={12} />
                        {selected === c ? t('cr_selected_candidate') : t('cr_select_candidate')}
                      </button>
                    ) : (
                      <span className="text-xs text-slate-500 flex items-center gap-1">
                        <Lock size={11} /> {t('cr_candidate_not_capturable')}
                      </span>
                    )}
                  </div>
                  <div className="max-h-72 overflow-y-auto bg-slate-900/40 rounded-lg p-3">
                    <Preview text={c.preview} />
                  </div>
                </div>
              ))}
            </>
          )}
        </div>
      )}

      {selected && (
        <div className="bg-slate-800/60 border border-blue-700/40 rounded-xl p-4 space-y-3">
          <h3 className="text-sm font-medium text-slate-300">{t('cr_save_form_title')}</h3>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">{t('cr_report_title_label')}</label>
            <input
              value={title}
              onChange={e => setTitle(e.target.value)}
              placeholder={t('cr_report_title_ph')}
              className="w-full bg-slate-900/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div>
            <label className="text-xs text-slate-400 mb-1 block">{t('cr_report_desc_label')}</label>
            <input
              value={description}
              onChange={e => setDescription(e.target.value)}
              className="w-full bg-slate-900/60 border border-slate-700 rounded-lg px-3 py-2 text-sm text-white focus:outline-none focus:border-blue-500"
            />
          </div>
          <p className="text-xs text-slate-500">{t('cr_deterministic_note')}</p>
          {saveMut.isError && (
            <div className="text-sm text-red-400">{t('cr_save_err', { msg: String((saveMut.error as Error)?.message || '') })}</div>
          )}
          <div className="flex items-center gap-3">
            <button
              onClick={() => saveMut.mutate()}
              disabled={!title.trim() || saveMut.isPending}
              className="px-4 py-2 bg-green-600 hover:bg-green-500 text-white rounded-lg text-sm font-medium disabled:opacity-50 flex items-center gap-2 transition-all"
            >
              {saveMut.isPending
                ? <><RefreshCw size={14} className="animate-spin" /> {t('cr_saving')}</>
                : <><Save size={14} /> {t('cr_save_btn')}</>}
            </button>
            {saveOk && (
              <span className="text-sm text-green-400 flex items-center gap-1.5">
                <CheckCircle2 size={14} /> {t('cr_save_ok')}
              </span>
            )}
          </div>
        </div>
      )}
    </div>
  )
}

// ── Kayıtlı Raporlar sekmesi ─────────────────────────────────────────────────

function relTime(iso: string | null): string {
  if (!iso) return '—'
  const m = Math.floor((Date.now() - new Date(iso).getTime()) / 60000)
  if (m < 1) return 'şimdi'
  if (m < 60) return `${m} dk önce`
  const h = Math.floor(m / 60)
  if (h < 24) return `${h} sa önce`
  return `${Math.floor(h / 24)} gün önce`
}

function SavedReportsTab() {
  const t = useT()
  const qc = useQueryClient()
  const [viewing, setViewing] = useState<ReportDefinition | null>(null)

  const { data, isLoading } = useQuery({
    queryKey: ['custom-reports'],
    queryFn: () => api('GET', '/custom-reports/') as Promise<{ reports: ReportDefinition[] }>,
    staleTime: 10_000,
  })

  const runMut = useMutation({
    mutationFn: (id: number) => api('POST', `/custom-reports/${id}/run`),
    onSuccess: (res: { report: ReportDefinition }) => {
      qc.invalidateQueries({ queryKey: ['custom-reports'] })
      if (viewing && viewing.id === res.report.id) setViewing(res.report)
    },
  })

  const deleteMut = useMutation({
    mutationFn: (id: number) => api('DELETE', `/custom-reports/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: ['custom-reports'] }),
  })

  const reports = data?.reports || []

  if (isLoading) {
    return <div className="text-sm text-slate-500 py-8 text-center">{t('loading')}</div>
  }

  if (reports.length === 0) {
    return (
      <div className="bg-slate-800/40 border border-slate-700 rounded-xl p-8 text-center text-sm text-slate-400">
        {t('cr_saved_empty')}
      </div>
    )
  }

  return (
    <>
      <div className="bg-slate-800/40 border border-slate-700 rounded-xl overflow-hidden">
        <table className="w-full text-sm">
          <thead className="bg-slate-900/40 text-slate-400 text-xs uppercase">
            <tr>
              <th className="text-left px-4 py-2.5">{t('cr_col_title')}</th>
              <th className="text-left px-4 py-2.5">{t('cr_col_platform')}</th>
              <th className="text-left px-4 py-2.5">{t('cr_col_tool')}</th>
              <th className="text-left px-4 py-2.5">{t('cr_col_last_run')}</th>
              <th className="text-left px-4 py-2.5">{t('cr_col_status')}</th>
              <th className="text-right px-4 py-2.5">{t('cr_col_actions')}</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-700/50">
            {reports.map(r => (
              <tr key={r.id} className="hover:bg-slate-700/20">
                <td className="px-4 py-2.5">
                  <div className="text-white font-medium">{r.title}</div>
                  {r.source_question && <div className="text-xs text-slate-500 truncate max-w-md">{r.source_question}</div>}
                </td>
                <td className="px-4 py-2.5 text-slate-300">{r.platform}</td>
                <td className="px-4 py-2.5"><code className="text-xs text-cyan-300">{r.tool_name}</code></td>
                <td className="px-4 py-2.5 text-slate-400 text-xs flex items-center gap-1">
                  <Clock size={11} /> {relTime(r.last_run_at)}
                </td>
                <td className="px-4 py-2.5">
                  {r.last_ok === true && <span className="text-green-400 text-xs flex items-center gap-1"><CheckCircle2 size={12} /> {t('cr_status_ok')}</span>}
                  {r.last_ok === false && <span className="text-red-400 text-xs flex items-center gap-1"><XCircle size={12} /> {t('cr_status_err')}</span>}
                  {r.last_ok === null && <span className="text-slate-500 text-xs">{t('cr_status_never')}</span>}
                </td>
                <td className="px-4 py-2.5">
                  <div className="flex items-center justify-end gap-1.5">
                    <button
                      onClick={() => setViewing(r)}
                      title={t('cr_action_view')}
                      className="p-1.5 rounded-md hover:bg-slate-700 text-slate-400 hover:text-white transition-all"
                    ><Eye size={14} /></button>
                    <button
                      onClick={() => runMut.mutate(r.id)}
                      disabled={runMut.isPending && runMut.variables === r.id}
                      title={t('cr_action_run')}
                      className="p-1.5 rounded-md hover:bg-slate-700 text-slate-400 hover:text-blue-400 transition-all disabled:opacity-50"
                    >
                      <RefreshCw size={14} className={runMut.isPending && runMut.variables === r.id ? 'animate-spin' : ''} />
                    </button>
                    <button
                      onClick={() => { if (window.confirm(t('cr_delete_confirm', { title: r.title }))) deleteMut.mutate(r.id) }}
                      title={t('cr_action_delete')}
                      className="p-1.5 rounded-md hover:bg-red-500/20 text-slate-400 hover:text-red-400 transition-all"
                    ><Trash2 size={14} /></button>
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {viewing && (
        <div className="fixed inset-0 bg-black/60 z-50 flex items-center justify-center p-6" onClick={() => setViewing(null)}>
          <div
            className="bg-slate-800 border border-slate-700 rounded-xl max-w-3xl w-full max-h-[85vh] flex flex-col"
            onClick={e => e.stopPropagation()}
          >
            <div className="flex items-center justify-between px-5 py-4 border-b border-slate-700">
              <div>
                <h3 className="text-white font-medium">{viewing.title}</h3>
                <p className="text-xs text-slate-500 mt-0.5">
                  {t('cr_view_modal_run_at')}: {relTime(viewing.last_run_at)}
                </p>
              </div>
              <button onClick={() => setViewing(null)} className="text-slate-400 hover:text-white">
                <X size={18} />
              </button>
            </div>
            <div className="flex-1 overflow-y-auto px-5 py-4">
              {viewing.last_error && (
                <div className="text-sm text-red-400 bg-red-500/10 border border-red-500/30 rounded-lg px-3 py-2 mb-3">
                  {viewing.last_error}
                </div>
              )}
              {viewing.last_rendered && <Preview text={viewing.last_rendered} />}
            </div>
          </div>
        </div>
      )}
    </>
  )
}

// ── Ana sayfa ─────────────────────────────────────────────────────────────────

export default function CustomReports() {
  const t = useT()
  const { hasModule } = useAuth()
  const [tab, setTab] = useState<'new' | 'saved'>('new')

  if (!hasModule('custom_reports')) {
    return (
      <div className="p-6">
        <div className="flex flex-col items-center justify-center py-16 text-center max-w-md mx-auto">
          <Lock size={40} className="text-slate-600 mb-3" />
          <p className="text-slate-300 font-medium mb-1">{t('cr_no_access_title')}</p>
          <p className="text-sm text-slate-500">{t('cr_no_access_hint')}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="p-6 space-y-6">
      <div>
        <h1 className="text-2xl font-bold text-white flex items-center gap-2">
          <FileBarChart2 size={22} className="text-blue-400" /> {t('cr_title')}
        </h1>
        <p className="text-slate-400 text-sm mt-1">{t('cr_subtitle')}</p>
      </div>

      <div className="flex gap-1 bg-slate-800/60 border border-slate-700 rounded-xl p-1 w-fit">
        <button
          onClick={() => setTab('new')}
          className={`flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-medium transition-all ${
            tab === 'new' ? 'bg-blue-600 text-white shadow' : 'text-slate-400 hover:text-white'
          }`}
        >
          <Sparkles size={15} /> {t('cr_tab_new')}
        </button>
        <button
          onClick={() => setTab('saved')}
          className={`flex items-center gap-2 px-5 py-2 rounded-lg text-sm font-medium transition-all ${
            tab === 'saved' ? 'bg-blue-600 text-white shadow' : 'text-slate-400 hover:text-white'
          }`}
        >
          <FileBarChart2 size={15} /> {t('cr_tab_saved')}
        </button>
      </div>

      {tab === 'new' ? <NewReportTab onSaved={() => setTab('saved')} /> : <SavedReportsTab />}
    </div>
  )
}
