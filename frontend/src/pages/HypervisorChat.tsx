import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API_BASE_URL } from '../config/api'
import {
  Send, Cpu, Server, MemoryStick, HardDrive, Zap,
  MessageSquare, Lightbulb, Loader2, AlertCircle,
  ChevronDown, ChevronUp, FileDown,
  Search, Plus, Trash2, BarChart3, History,
} from 'lucide-react'
import { exportMarkdownToPrintWindow } from '../utils/pdfExport'

// ── Types ────────────────────────────────────────────────────────────────────

interface Message {
  id: string | number
  role: 'user' | 'assistant'
  content: string
  intents?: string[]
  report_type?: string
  report_title?: string
  latency_ms?: number
  error?: string | null
  timestamp: Date
}

interface ChatSession {
  id: number
  title: string
  created_at: string
  updated_at?: string | null
  message_count: number
}

interface Suggestions {
  suggestions: string[]
  report_suggestions?: string[]
  sample_vms: string[]
}

interface HypervisorChatProps {
  embedded?: boolean
  initialQuestion?: string | null
  onInitialQuestionUsed?: () => void
}

// ── Intent badge ──────────────────────────────────────────────────────────────

const INTENT_LABELS: Record<string, { label: string; color: string }> = {
  count_hosts:   { label: 'Host sayısı',   color: 'bg-blue-500/20 text-blue-300' },
  vm_per_host:   { label: 'VM dağılımı',   color: 'bg-purple-500/20 text-purple-300' },
  capacity:      { label: 'Kapasite',       color: 'bg-amber-500/20 text-amber-300' },
  compare_vms:   { label: 'Karşılaştırma', color: 'bg-green-500/20 text-green-300' },
  tools_status:  { label: 'VMware Tools',  color: 'bg-sky-500/20 text-sky-300' },
  os_filter:     { label: 'OS filtresi',   color: 'bg-rose-500/20 text-rose-300' },
  powered_off:   { label: 'Kapalı VM',     color: 'bg-red-500/20 text-red-300' },
  assessment:    { label: 'Değerlendirme', color: 'bg-teal-500/20 text-teal-300' },
  network:       { label: 'Network',       color: 'bg-indigo-500/20 text-indigo-300' },
  report:        { label: 'Rapor',         color: 'bg-emerald-500/20 text-emerald-300' },
  general:       { label: 'Genel',         color: 'bg-slate-500/20 text-slate-300' },
}

function IntentBadges({ intents, reportType }: { intents?: string[]; reportType?: string }) {
  const items = [...(intents || [])]
  if (reportType && !items.includes(reportType)) items.push('report')
  if (items.length === 0) return null
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {reportType && (
        <span className="text-[10px] px-1.5 py-0.5 rounded-full font-medium bg-emerald-500/20 text-emerald-300 flex items-center gap-1">
          <BarChart3 size={10} /> {reportType.replace(/_/g, ' ')}
        </span>
      )}
      {items.filter(i => i !== reportType).map(intent => {
        const cfg = INTENT_LABELS[intent] || { label: intent, color: 'bg-slate-700 text-slate-300' }
        return (
          <span key={intent} className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${cfg.color}`}>
            {cfg.label}
          </span>
        )
      })}
    </div>
  )
}

function formatSessionDate(iso: string) {
  if (!iso) return ''
  const d = new Date(iso)
  const now = new Date()
  const diff = now.getTime() - d.getTime()
  if (diff < 86400000) return d.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })
  if (diff < 604800000) return d.toLocaleDateString('tr-TR', { weekday: 'short' })
  return d.toLocaleDateString('tr-TR', { day: 'numeric', month: 'short' })
}

// ── Quick stats bar ───────────────────────────────────────────────────────────

interface QuickStats {
  host_count: number
  vm_count: number
  vms_powered_on: number
  avg_cpu_pct: number
  avg_mem_pct: number
}

function QuickStatsBar() {
  const { data } = useQuery<QuickStats>({
    queryKey: ['hv-quick-stats'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/ask/quick-stats`)
      if (!r.ok) throw new Error('Stats error')
      return r.json()
    },
    refetchInterval: 60_000,
    staleTime: 30_000,
  })

  if (!data) return null

  const stats = [
    { icon: <Server size={14} />, label: 'Host', value: data.host_count },
    { icon: <Cpu size={14} />, label: 'VM', value: data.vm_count },
    { icon: <Zap size={14} />, label: 'Çalışan', value: data.vms_powered_on },
    { icon: <Cpu size={14} />, label: 'Ort. CPU', value: `%${data.avg_cpu_pct?.toFixed(0)}` },
    { icon: <MemoryStick size={14} />, label: 'Ort. RAM', value: `%${data.avg_mem_pct?.toFixed(0)}` },
  ]

  return (
    <div className="flex items-center gap-3 px-4 py-2 bg-slate-800/50 border-b border-slate-700/50 text-xs text-slate-400 overflow-x-auto flex-shrink-0">
      {stats.map(s => (
        <div key={s.label} className="flex items-center gap-1.5 whitespace-nowrap">
          <span className="text-slate-500">{s.icon}</span>
          <span className="text-slate-500">{s.label}:</span>
          <span className="text-slate-200 font-medium">{s.value}</span>
        </div>
      ))}
    </div>
  )
}

// ── Suggestion chips ──────────────────────────────────────────────────────────

function SuggestionChips({
  suggestions,
  reportSuggestions,
  onSelect,
}: {
  suggestions: string[]
  reportSuggestions?: string[]
  onSelect: (q: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const all = [...(reportSuggestions || []).slice(0, 4), ...suggestions]
  const shown = expanded ? all : all.slice(0, 6)

  return (
    <div className="space-y-3">
      {reportSuggestions && reportSuggestions.length > 0 && (
        <div>
          <div className="flex items-center gap-2 text-xs text-emerald-500 mb-2">
            <BarChart3 size={12} />
            <span>Rapor soruları</span>
          </div>
          <div className="flex flex-wrap gap-2">
            {reportSuggestions.slice(0, expanded ? undefined : 4).map(s => (
              <button
                key={s}
                onClick={() => onSelect(s)}
                className="text-xs px-3 py-1.5 rounded-full bg-emerald-900/30 hover:bg-emerald-900/50 text-emerald-300 border border-emerald-500/30 transition-all"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}
      <div>
        <div className="flex items-center gap-2 text-xs text-slate-500 mb-2">
          <Lightbulb size={12} />
          <span>Örnek sorular</span>
        </div>
        <div className="flex flex-wrap gap-2">
          {shown.filter(s => !reportSuggestions?.includes(s)).map(s => (
            <button
              key={s}
              onClick={() => onSelect(s)}
              className="text-xs px-3 py-1.5 rounded-full bg-slate-700/70 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-600/50 hover:border-blue-500/40 transition-all"
            >
              {s}
            </button>
          ))}
          {all.length > 6 && (
            <button
              onClick={() => setExpanded(e => !e)}
              className="text-xs px-3 py-1.5 rounded-full bg-blue-900/30 text-blue-400 hover:text-blue-300 border border-blue-500/30 flex items-center gap-1 transition-all"
            >
              {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
              {expanded ? 'Daha az' : `+${all.length - 6} daha`}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ msg }: { msg: Message }) {
  const isUser = msg.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center mr-2 mt-1 flex-shrink-0">
          <Server size={14} className="text-white" />
        </div>
      )}
      <div className={`max-w-[85%] ${isUser ? 'order-first' : ''}`}>
        <div
          className={`rounded-2xl px-4 py-3 text-sm leading-relaxed ${
            isUser
              ? 'bg-blue-600 text-white rounded-tr-sm ml-auto'
              : msg.error
              ? 'bg-red-900/30 text-red-300 border border-red-700/40 rounded-tl-sm'
              : 'bg-slate-800 text-slate-100 border border-slate-700/50 rounded-tl-sm'
          }`}
        >
          {isUser ? (
            <p>{msg.content}</p>
          ) : (
            <div className="prose prose-invert prose-sm max-w-none
              prose-headings:text-blue-300 prose-headings:font-semibold
              prose-strong:text-white prose-code:text-amber-300
              prose-code:bg-slate-900 prose-code:px-1 prose-code:rounded
              prose-table:text-xs prose-th:bg-slate-900/50 prose-td:border-slate-700
              prose-a:text-blue-400">
              {msg.error ? (
                <div className="flex items-center gap-2">
                  <AlertCircle size={14} />
                  <span>{msg.content}</span>
                </div>
              ) : (
                <ReactMarkdown remarkPlugins={[remarkGfm]}>
                  {msg.content}
                </ReactMarkdown>
              )}
            </div>
          )}
        </div>
        {!isUser && (
          <IntentBadges intents={msg.intents} reportType={msg.report_type} />
        )}
        <div className="flex items-center gap-2 mt-1 px-1">
          <span className="text-[10px] text-slate-600">
            {msg.timestamp.toLocaleTimeString('tr-TR', { hour: '2-digit', minute: '2-digit' })}
          </span>
          {msg.latency_ms && (
            <span className="text-[10px] text-slate-600">{msg.latency_ms}ms</span>
          )}
          {!isUser && msg.content && msg.content.length > 50 && (
            <button
              onClick={() => exportMarkdownToPrintWindow(msg.content, {
                title: msg.report_title || 'Hypervisor Asistan Yanıtı',
                subtitle: msg.timestamp.toLocaleString('tr-TR'),
                filename: `hypervisor_analiz_${msg.timestamp.toISOString().split('T')[0]}`,
              })}
              className="ml-1 flex items-center gap-1 text-[10px] text-slate-500 hover:text-red-400 transition-colors"
              title="PDF olarak indir"
            >
              <FileDown size={11} /> PDF
            </button>
          )}
        </div>
      </div>
      {isUser && (
        <div className="w-7 h-7 rounded-full bg-slate-700 flex items-center justify-center ml-2 mt-1 flex-shrink-0">
          <MessageSquare size={14} className="text-slate-300" />
        </div>
      )}
    </div>
  )
}

function TypingIndicator() {
  return (
    <div className="flex justify-start mb-4">
      <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center mr-2 mt-1">
        <Server size={14} className="text-white" />
      </div>
      <div className="bg-slate-800 border border-slate-700/50 rounded-2xl rounded-tl-sm px-4 py-3">
        <div className="flex items-center gap-1.5">
          <Loader2 size={14} className="text-blue-400 animate-spin" />
          <span className="text-xs text-slate-400">Altyapı analiz ediliyor...</span>
        </div>
      </div>
    </div>
  )
}

// ── History sidebar ───────────────────────────────────────────────────────────

function HistorySidebar({
  sessions,
  selectedId,
  search,
  onSearchChange,
  onSelect,
  onNew,
  onDelete,
  onClearAll,
  loading,
}: {
  sessions: ChatSession[]
  selectedId: number | null
  search: string
  onSearchChange: (v: string) => void
  onSelect: (id: number | null) => void
  onNew: () => void
  onDelete: (id: number) => void
  onClearAll: () => void
  loading?: boolean
}) {
  return (
    <div className="w-64 flex-shrink-0 border-r border-slate-700/50 bg-slate-900/80 flex flex-col">
      <div className="p-3 border-b border-slate-700/50 space-y-2">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-1.5 text-xs font-medium text-slate-300">
            <History size={14} />
            Geçmiş
          </div>
          <div className="flex gap-1">
            <button
              onClick={onNew}
              className="p-1.5 rounded-lg bg-blue-600 hover:bg-blue-500 text-white transition-colors"
              title="Yeni sohbet"
            >
              <Plus size={14} />
            </button>
            {sessions.length > 0 && (
              <button
                onClick={onClearAll}
                className="p-1.5 rounded-lg bg-slate-800 hover:bg-red-900/40 text-slate-400 hover:text-red-400 transition-colors"
                title="Tümünü sil"
              >
                <Trash2 size={14} />
              </button>
            )}
          </div>
        </div>
        <div className="relative">
          <Search size={14} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-500" />
          <input
            value={search}
            onChange={e => onSearchChange(e.target.value)}
            placeholder="Sohbetlerde ara..."
            className="w-full bg-slate-800 border border-slate-700/50 rounded-lg pl-8 pr-3 py-1.5 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500/50"
          />
        </div>
      </div>
      <div className="flex-1 overflow-y-auto p-2">
        {loading ? (
          <div className="flex justify-center py-8">
            <Loader2 size={20} className="text-slate-500 animate-spin" />
          </div>
        ) : sessions.length === 0 ? (
          <div className="text-center py-8 px-2">
            <p className="text-xs text-slate-500">
              {search ? 'Arama sonucu yok' : 'Henüz sohbet yok'}
            </p>
            {!search && (
              <button onClick={onNew} className="mt-2 text-xs text-blue-400 hover:text-blue-300">
                + Yeni sohbet başlat
              </button>
            )}
          </div>
        ) : (
          sessions.map(session => (
            <div
              key={session.id}
              onClick={() => onSelect(session.id)}
              className={`group flex items-start gap-2 px-2.5 py-2 rounded-lg cursor-pointer mb-1 transition-colors ${
                selectedId === session.id
                  ? 'bg-blue-600/20 border border-blue-500/30'
                  : 'hover:bg-slate-800/80 border border-transparent'
              }`}
            >
              <div className="flex-1 min-w-0">
                <p className="text-xs font-medium text-slate-200 truncate">{session.title}</p>
                <p className="text-[10px] text-slate-500 mt-0.5">
                  {session.message_count} mesaj · {formatSessionDate(session.updated_at || session.created_at)}
                </p>
              </div>
              <button
                onClick={e => { e.stopPropagation(); onDelete(session.id) }}
                className="opacity-0 group-hover:opacity-100 p-1 text-slate-500 hover:text-red-400 transition-opacity flex-shrink-0"
              >
                <Trash2 size={12} />
              </button>
            </div>
          ))
        )}
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function HypervisorChat({
  embedded = false,
  initialQuestion = null,
  onInitialQuestionUsed,
}: HypervisorChatProps) {
  const queryClient = useQueryClient()
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const [historySearch, setHistorySearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)
  const initialHandled = useRef(false)

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(historySearch), 300)
    return () => clearTimeout(t)
  }, [historySearch])

  const { data: sessions = [], isLoading: sessionsLoading } = useQuery<ChatSession[]>({
    queryKey: ['hv-chat-sessions', debouncedSearch],
    queryFn: async () => {
      const q = debouncedSearch ? `?q=${encodeURIComponent(debouncedSearch)}` : ''
      const r = await fetch(`${API_BASE_URL}/hypervisors/ask/sessions${q}`)
      if (!r.ok) throw new Error('Sessions error')
      return r.json()
    },
    staleTime: 10_000,
  })

  const { data: suggestions } = useQuery<Suggestions>({
    queryKey: ['hv-suggestions'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/ask/suggestions`)
      if (!r.ok) throw new Error('Suggestions error')
      return r.json()
    },
    staleTime: 60_000,
  })

  const loadSessionMessages = useCallback(async (sessionId: number) => {
    const r = await fetch(`${API_BASE_URL}/hypervisors/ask/sessions/${sessionId}/messages`)
    if (!r.ok) return
    const data = await r.json()
    setMessages((data.messages || []).map((m: any) => ({
      id: m.id,
      role: m.role,
      content: m.content,
      intents: m.meta?.intents,
      report_type: m.meta?.report_type,
      report_title: m.meta?.report_title,
      latency_ms: m.meta?.latency_ms,
      error: m.meta?.error,
      timestamp: new Date(m.created_at),
    })))
  }, [])

  useEffect(() => {
    if (selectedSessionId) {
      loadSessionMessages(selectedSessionId)
    } else {
      setMessages([])
    }
  }, [selectedSessionId, loadSessionMessages])

  useEffect(() => {
    if (sessions.length > 0 && selectedSessionId === null && !debouncedSearch) {
      setSelectedSessionId(sessions[0].id)
    }
  }, [sessions, selectedSessionId, debouncedSearch])

  const createSessionMutation = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/ask/sessions`, { method: 'POST' })
      if (!r.ok) throw new Error('Create failed')
      return r.json() as Promise<ChatSession>
    },
    onSuccess: (session) => {
      queryClient.invalidateQueries({ queryKey: ['hv-chat-sessions'] })
      setSelectedSessionId(session.id)
      setMessages([])
      setInput('')
    },
  })

  const deleteSessionMutation = useMutation({
    mutationFn: async (id: number) => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/ask/sessions/${id}`, { method: 'DELETE' })
      if (!r.ok) throw new Error('Delete failed')
    },
    onSuccess: (_d, id) => {
      queryClient.invalidateQueries({ queryKey: ['hv-chat-sessions'] })
      if (selectedSessionId === id) {
        setSelectedSessionId(null)
        setMessages([])
      }
    },
  })

  const clearAllMutation = useMutation({
    mutationFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/ask/sessions`, { method: 'DELETE' })
      if (!r.ok) throw new Error('Clear failed')
    },
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['hv-chat-sessions'] })
      setSelectedSessionId(null)
      setMessages([])
    },
  })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const sendQuestion = useCallback(async (q: string, sessionId?: number | null) => {
    if (!q.trim() || loading) return

    let activeSessionId = sessionId ?? selectedSessionId

    const userMsg: Message = {
      id: `tmp-${Date.now()}`,
      role: 'user',
      content: q.trim(),
      timestamp: new Date(),
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')
    setLoading(true)

    try {
      const res = await fetch(`${API_BASE_URL}/hypervisors/ask`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          question: q.trim(),
          session_id: activeSessionId,
        }),
      })
      const data = await res.json().catch(() => ({}))

      if (!res.ok) {
        // Eski/silinmiş bir oturum kimliğiyle isteği tekrar denemeyelim ki
        // aynı hataya sonsuza dek çarpmasın; kullanıcı görünür bir hata alsın.
        if (activeSessionId) setSelectedSessionId(null)
        setMessages(prev => [...prev, {
          id: `tmp-${Date.now() + 1}`,
          role: 'assistant',
          content: data?.detail || `İstek başarısız oldu (HTTP ${res.status}).`,
          error: 'http_error',
          timestamp: new Date(),
        }])
        return
      }

      if (data.session_id) {
        setSelectedSessionId(data.session_id)
      }
      queryClient.invalidateQueries({ queryKey: ['hv-chat-sessions'] })
      if (data.session_id) {
        await loadSessionMessages(data.session_id)
      }
    } catch {
      setMessages(prev => [...prev, {
        id: `tmp-${Date.now() + 1}`,
        role: 'assistant',
        content: 'Bağlantı hatası. Lütfen tekrar deneyin.',
        error: 'connection_error',
        timestamp: new Date(),
      }])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }, [loading, selectedSessionId, queryClient, loadSessionMessages])

  useEffect(() => {
    if (initialQuestion && !initialHandled.current) {
      initialHandled.current = true
      sendQuestion(initialQuestion, null)
      onInitialQuestionUsed?.()
    }
  }, [initialQuestion, sendQuestion, onInitialQuestionUsed])

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendQuestion(input)
    }
  }

  function startNewChat() {
    createSessionMutation.mutate()
  }

  const isEmpty = messages.length === 0 && !loading

  const chatPanel = (
    <div className="flex-1 flex flex-col min-w-0 min-h-0">
      {!embedded && (
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50 bg-slate-900 flex-shrink-0">
          <div className="flex items-center gap-3">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center shadow-lg shadow-blue-500/20">
              <HardDrive size={18} className="text-white" />
            </div>
            <div>
              <h1 className="text-white font-semibold text-lg">Hypervisor Asistanı</h1>
              <p className="text-slate-400 text-xs">Altyapı sorguları ve rapor üretimi</p>
            </div>
          </div>
        </div>
      )}

      <QuickStatsBar />

      <div className="flex-1 overflow-y-auto px-4 py-4">
        {isEmpty ? (
          <div className="max-w-2xl mx-auto mt-6 space-y-6">
            <div className="text-center space-y-2">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center mx-auto shadow-xl shadow-blue-500/20">
                <HardDrive size={24} className="text-white" />
              </div>
              <h2 className="text-lg font-semibold text-white">Altyapınızı Sorgulayın</h2>
              <p className="text-slate-400 text-sm max-w-md mx-auto">
                ESX hostlar, VM envanteri, kapasite durumu ve raporlar hakkında Türkçe sorular sorun.
              </p>
            </div>
            {suggestions && (
              <SuggestionChips
                suggestions={suggestions.suggestions}
                reportSuggestions={suggestions.report_suggestions}
                onSelect={q => sendQuestion(q)}
              />
            )}
          </div>
        ) : (
          <div className="max-w-3xl mx-auto">
            {messages.map(msg => (
              <MessageBubble key={msg.id} msg={msg} />
            ))}
            {loading && <TypingIndicator />}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {!isEmpty && suggestions && (
        <div className="px-4 pb-2 max-w-3xl mx-auto w-full flex-shrink-0">
          <div className="flex gap-2 overflow-x-auto pb-1">
            {(suggestions.report_suggestions || []).slice(0, 2).concat(suggestions.suggestions.slice(0, 3)).map(s => (
              <button
                key={s}
                onClick={() => sendQuestion(s)}
                className="text-xs px-3 py-1.5 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white border border-slate-700/50 whitespace-nowrap transition-all flex-shrink-0"
              >
                {s.length > 40 ? s.slice(0, 40) + '…' : s}
              </button>
            ))}
          </div>
        </div>
      )}

      <div className="px-4 pb-4 max-w-3xl mx-auto w-full flex-shrink-0">
        <div className="flex items-end gap-2 bg-slate-800 border border-slate-700/50 rounded-2xl px-4 py-3 focus-within:border-blue-500/50 transition-colors">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Sorunuzu yazın… (ör: Kapasite raporu oluştur, Kaç ESX hostum var?)"
            rows={1}
            className="flex-1 bg-transparent text-white placeholder-slate-500 text-sm resize-none focus:outline-none leading-relaxed"
            style={{ maxHeight: '120px', overflowY: 'auto' }}
          />
          <button
            onClick={() => sendQuestion(input)}
            disabled={!input.trim() || loading}
            className="w-8 h-8 rounded-xl bg-blue-600 hover:bg-blue-500 disabled:bg-slate-700 disabled:opacity-50 flex items-center justify-center transition-all flex-shrink-0"
          >
            {loading ? (
              <Loader2 size={15} className="text-white animate-spin" />
            ) : (
              <Send size={15} className="text-white" />
            )}
          </button>
        </div>
        <p className="text-center text-[10px] text-slate-600 mt-1.5">
          Enter ile gönder · Shift+Enter yeni satır · Rapor soruları desteklenir
        </p>
      </div>
    </div>
  )

  return (
    <div className={`flex bg-slate-900 ${embedded ? 'h-[calc(100vh-220px)] min-h-[520px]' : 'h-screen'}`}>
      <HistorySidebar
        sessions={sessions}
        selectedId={selectedSessionId}
        search={historySearch}
        onSearchChange={setHistorySearch}
        onSelect={id => setSelectedSessionId(id)}
        onNew={startNewChat}
        onDelete={id => deleteSessionMutation.mutate(id)}
        onClearAll={() => {
          if (window.confirm('Tüm sohbet geçmişi silinecek. Emin misiniz?')) {
            clearAllMutation.mutate()
          }
        }}
        loading={sessionsLoading}
      />
      {chatPanel}
    </div>
  )
}
