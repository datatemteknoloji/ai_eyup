import { useState, useRef, useEffect, useCallback } from 'react'
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import { chatMarkdownComponents } from '../components/chatMarkdown'
import remarkGfm from 'remark-gfm'
import { API_BASE_URL } from '../config/api'
import {
  Cpu, Server, MemoryStick, HardDrive, Zap,
  MessageSquare, Lightbulb, Loader2, AlertCircle,
  ChevronDown, ChevronUp, FileDown, BarChart3,
} from 'lucide-react'
import { exportMarkdownToPrintWindow, exportChatMessagesToPrintWindow } from '../utils/pdfExport'
import ChatFeedbackButtons from '../components/ChatFeedbackButtons'
import {
  NlChatRoot, NlHistorySidebar, NlChatPanel, NlTopBar, NlModelSelect,
  NlModelUnavailableBanner, NlChatInput,
} from '../components/nlChatUi'
import { useChatStickToBottom } from '../lib/chatScroll'
import { useChatStream, startChatStream, abortChatStream, restoreChatTurn } from '../lib/chatStreamStore'
import { useT, useLocale } from '../i18n/LocaleProvider'
import type { TranslationKey } from '../i18n/messages'

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

interface AIModel {
  name: string
  size: number
  parameter_size: string
  family: string
}

interface HypervisorChatProps {
  embedded?: boolean
  initialQuestion?: string | null
  onInitialQuestionUsed?: () => void
}

// ── Intent badge ──────────────────────────────────────────────────────────────

const INTENT_KEYS: Record<string, { key: TranslationKey | null; fallback: string; color: string }> = {
  count_hosts:   { key: 'chat_intent_hosts', fallback: 'Host count', color: 'bg-blue-500/20 text-blue-300' },
  vm_per_host:   { key: 'chat_intent_vm_dist', fallback: 'VM distribution', color: 'bg-sky-500/20 text-sky-300' },
  capacity:      { key: 'chat_intent_capacity', fallback: 'Capacity', color: 'bg-amber-500/20 text-amber-300' },
  compare_vms:   { key: 'chat_intent_compare', fallback: 'Comparison', color: 'bg-green-500/20 text-green-300' },
  tools_status:  { key: null, fallback: 'VMware Tools', color: 'bg-sky-500/20 text-sky-300' },
  os_filter:     { key: 'chat_intent_os', fallback: 'OS filter', color: 'bg-rose-500/20 text-rose-300' },
  powered_off:   { key: 'chat_intent_off', fallback: 'Powered-off VM', color: 'bg-red-500/20 text-red-300' },
  assessment:    { key: 'chat_intent_assess', fallback: 'Assessment', color: 'bg-teal-500/20 text-teal-300' },
  network:       { key: null, fallback: 'Network', color: 'bg-indigo-500/20 text-indigo-300' },
  report:        { key: 'chat_intent_report', fallback: 'Report', color: 'bg-emerald-500/20 text-emerald-300' },
  general:       { key: 'chat_intent_general', fallback: 'General', color: 'bg-slate-500/20 text-slate-300' },
}

function IntentBadges({ intents, reportType }: { intents?: string[]; reportType?: string }) {
  const t = useT()
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
        const cfg = INTENT_KEYS[intent] || { key: null, fallback: intent, color: 'bg-slate-700 text-slate-300' }
        return (
          <span key={intent} className={`text-[10px] px-1.5 py-0.5 rounded-full font-medium ${cfg.color}`}>
            {cfg.key ? t(cfg.key) : cfg.fallback}
          </span>
        )
      })}
    </div>
  )
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
  const t = useT()
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
    { icon: <Zap size={14} />, label: t('chat_stat_running'), value: data.vms_powered_on },
    { icon: <Cpu size={14} />, label: t('chat_stat_avg_cpu'), value: `%${data.avg_cpu_pct?.toFixed(0)}` },
    { icon: <MemoryStick size={14} />, label: t('chat_stat_avg_mem'), value: `%${data.avg_mem_pct?.toFixed(0)}` },
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
  const t = useT()
  const [expanded, setExpanded] = useState(false)
  const all = [...(reportSuggestions || []).slice(0, 4), ...suggestions]
  const shown = expanded ? all : all.slice(0, 6)

  return (
    <div className="space-y-3">
      {reportSuggestions && reportSuggestions.length > 0 && (
        <div>
          <div className="flex items-center gap-2 text-xs text-emerald-500 mb-2">
            <BarChart3 size={12} />
            <span>{t('chat_report_qs')}</span>
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
          <span>{t('chat_sample_qs')}</span>
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
              {expanded ? t('chat_less') : t('chat_more_n', { n: all.length - 6 })}
            </button>
          )}
        </div>
      </div>
    </div>
  )
}

// ── Message bubble ────────────────────────────────────────────────────────────

function MessageBubble({ msg, question }: { msg: Message; question?: string }) {
  const t = useT()
  const { locale } = useLocale()
  const isUser = msg.role === 'user'

  return (
    <div className={`flex ${isUser ? 'justify-end' : 'justify-start'} mb-4`}>
      {!isUser && (
        <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center mr-2 mt-1 flex-shrink-0">
          <Server size={14} className="text-white" />
        </div>
      )}
      <div className={`min-w-0 max-w-[min(85%,48rem)] ${isUser ? 'order-first' : ''}`}>
        <div
          className={`rounded-2xl px-4 py-3 text-sm leading-relaxed overflow-hidden ${
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
            <div className="chat-response-content prose prose-invert prose-sm max-w-none min-w-0
              prose-headings:text-blue-300 prose-headings:font-semibold
              prose-strong:text-white prose-code:text-amber-300
              prose-code:bg-slate-900 prose-code:px-1 prose-code:rounded
              prose-a:text-blue-400">
              {msg.error ? (
                <div className="flex items-center gap-2">
                  <AlertCircle size={14} />
                  <span>{msg.content}</span>
                </div>
              ) : (
                <ReactMarkdown remarkPlugins={[remarkGfm]} components={chatMarkdownComponents}>
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
                title: msg.report_title || t('chat_pdf_hv'),
                subtitle: msg.timestamp.toLocaleString(locale === 'en' ? 'en-GB' : 'tr-TR'),
                filename: `hypervisor_analiz_${msg.timestamp.toISOString().split('T')[0]}`,
              })}
              className="ml-1 flex items-center gap-1 text-[10px] text-slate-500 hover:text-red-400 transition-colors"
              title="PDF olarak indir"
            >
              <FileDown size={11} /> PDF
            </button>
          )}
        </div>
        {!isUser && !msg.error && question && (
          <div className="px-1">
            <ChatFeedbackButtons
              platform="virt"
              question={question}
              answer={msg.content}
              messageId={typeof msg.id === 'number' ? msg.id : undefined}
            />
          </div>
        )}
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
  const t = useT()
  return (
    <div className="flex justify-start mb-4">
      <div className="w-7 h-7 rounded-full bg-blue-600 flex items-center justify-center mr-2 mt-1">
        <Server size={14} className="text-white" />
      </div>
      <div className="bg-slate-800 border border-slate-700/50 rounded-2xl rounded-tl-sm px-4 py-3">
        <div className="flex items-center gap-1.5">
          <Loader2 size={14} className="text-blue-400 animate-spin" />
          <span className="text-xs text-slate-400">{t('chat_analyzing_infra')}</span>
        </div>
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
  const t = useT()
  const { locale } = useLocale()
  const queryClient = useQueryClient()
  const stream = useChatStream('hypervisor')
  const [selectedSessionId, setSelectedSessionId] = useState<number | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const loading = stream.isLoading
  const [selectedModel, setSelectedModel] = useState<string>(
    () => localStorage.getItem('virt_chat_selected_model') || localStorage.getItem('chat_selected_model') || 'llama3:70b',
  )
  const [historySearch, setHistorySearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const bottomRef = useRef<HTMLDivElement>(null)
  const messagesContainerRef = useRef<HTMLDivElement>(null)
  const initialHandled = useRef(false)

  useEffect(() => {
    const t = setTimeout(() => setDebouncedSearch(historySearch), 300)
    return () => clearTimeout(t)
  }, [historySearch])

  const { data: modelsData, isFetched: modelsFetched } = useQuery<{
    success: boolean
    reachable?: boolean
    models: AIModel[]
    default: string
    error?: string
    remote?: boolean
    provider?: string
  }>({
    queryKey: ['ai-models'],
    queryFn: async () => {
      try {
        const res = await fetch(`${API_BASE_URL}/chat/models`, { signal: AbortSignal.timeout(5000) })
        if (!res.ok) return { success: false, reachable: false, models: [], default: 'llama3.2:3b', error: `HTTP ${res.status}` }
        return res.json()
      } catch (e) {
        return {
          success: false,
          reachable: false,
          models: [],
          default: 'llama3.2:3b',
          error: e instanceof Error ? e.message : t('chat_conn_err'),
        }
      }
    },
    retry: false,
    staleTime: 60_000,
  })

  const availableModels: AIModel[] =
    modelsData?.models?.length
      ? modelsData.models
      : [
          { name: 'llama3.2:3b', size: 0, parameter_size: '3.2B', family: 'llama' },
          { name: 'llama3.1:8b', size: 0, parameter_size: '8.0B', family: 'llama' },
          { name: 'qwen2.5:7b', size: 0, parameter_size: '7.6B', family: 'qwen2' },
          { name: 'llama3:70b', size: 0, parameter_size: '70.6B', family: 'llama' },
        ]

  const { data: sessions = [], isLoading: sessionsLoading, isFetched: hvSessionsFetched } = useQuery<ChatSession[]>({
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
    if (!hvSessionsFetched || debouncedSearch) return
    if (selectedSessionId != null && sessions.some((s) => s.id === selectedSessionId)) return
    setSelectedSessionId(sessions.length > 0 ? sessions[0].id : null)
  }, [hvSessionsFetched, sessions, selectedSessionId, debouncedSearch])

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

  useChatStickToBottom(messagesContainerRef, {
    sessionId: selectedSessionId,
    messageCount: messages.length,
    followKey: `${loading}|${messages.map((m) => m.id).join(',')}`,
    sending: loading,
  })

  const sendQuestion = useCallback(async (q: string, sessionId?: number | null) => {
    if (!q.trim() || loading) return

    let activeSessionId = sessionId !== undefined ? sessionId : selectedSessionId
    if (
      activeSessionId != null &&
      !debouncedSearch &&
      sessions.length > 0 &&
      !sessions.some((s) => s.id === activeSessionId)
    ) {
      activeSessionId = null
    }

    const userMsg: Message = {
      id: `tmp-${Date.now()}`,
      role: 'user',
      content: q.trim(),
      timestamp: new Date(),
    }
    setMessages(prev => [...prev, userMsg])
    setInput('')

    try {
      await startChatStream({
        channel: 'hypervisor',
        url: `${API_BASE_URL}/hypervisors/ask/stream`,
        body: {
          question: q.trim(),
          session_id: activeSessionId,
          model: selectedModel,
        },
        sessionId: activeSessionId,
        message: q.trim(),
        initialPhase: 'context',
        onSessionId: (id) => setSelectedSessionId(id),
        onDone: async (sid) => {
          queryClient.invalidateQueries({ queryKey: ['hv-chat-sessions'] })
          if (sid) await loadSessionMessages(sid)
        },
      })
    } catch {
      setMessages(prev => [...prev, {
        id: `tmp-${Date.now() + 1}`,
        role: 'assistant',
        content: t('chat_retry_hint'),
        error: 'connection_error',
        timestamp: new Date(),
      }])
    }
  }, [loading, selectedSessionId, selectedModel, queryClient, loadSessionMessages, sessions, debouncedSearch])

  useEffect(() => {
    if (initialQuestion && !initialHandled.current) {
      initialHandled.current = true
      sendQuestion(initialQuestion, null)
      onInitialQuestionUsed?.()
    }
  }, [initialQuestion, sendQuestion, onInitialQuestionUsed])

  function startNewChat() {
    createSessionMutation.mutate()
  }

  const isEmpty = messages.length === 0 && !loading

  const chatPanel = (
    <NlChatPanel>
      <NlTopBar>
        {!embedded && (
          <div className="flex items-center gap-3 mr-2">
            <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center shadow-lg shadow-blue-500/20">
              <HardDrive size={18} className="text-white" />
            </div>
            <div>
              <h1 className="text-white font-semibold text-sm leading-tight">{t('chat_hv_title')}</h1>
              <p className="text-slate-400 text-[11px]">{t('chat_hv_sub')}</p>
            </div>
          </div>
        )}
        {messages.length > 0 && (
          <button
            type="button"
            onClick={() => exportChatMessagesToPrintWindow(
              messages.map(m => ({
                role: m.role,
                content: m.content,
                created_at: m.timestamp?.toISOString?.() || undefined,
              })),
              {
                title: t('chat_pdf_virt'),
                subtitle: new Date().toLocaleString(locale === 'en' ? 'en-GB' : 'tr-TR'),
                filename: `virt_ai_${new Date().toISOString().slice(0, 10)}`,
              },
            )}
            className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs font-medium bg-red-500/15 text-red-300 border border-red-500/30 hover:bg-red-500/25"
          >
            <FileDown size={13} /> {t('chat_pdf_chat')}
          </button>
        )}
        <NlModelSelect
          value={selectedModel}
          onChange={setSelectedModel}
          models={availableModels}
          storageKey="virt_chat_selected_model"
        />
      </NlTopBar>

      <NlModelUnavailableBanner modelsData={modelsData} isFetched={modelsFetched} />

      <QuickStatsBar />

      <div ref={messagesContainerRef} className="flex-1 min-h-0 overflow-y-auto overscroll-contain px-4 py-4">
        {isEmpty ? (
          <div className="max-w-2xl mx-auto mt-6 space-y-6">
            <div className="text-center space-y-2">
              <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center mx-auto shadow-xl shadow-blue-500/20">
                <HardDrive size={24} className="text-white" />
              </div>
              <h2 className="text-lg font-semibold text-white">{t('chat_hv_empty_title')}</h2>
              <p className="text-slate-400 text-sm max-w-md mx-auto">
                {t('chat_hv_empty')}
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
            {messages.map((msg, i) => {
              let question = ''
              if (msg.role === 'assistant') {
                for (let j = i - 1; j >= 0; j--) {
                  if (messages[j].role === 'user') {
                    question = messages[j].content
                    break
                  }
                }
              }
              return <MessageBubble key={msg.id} msg={msg} question={question} />
            })}
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

      <NlChatInput
        value={input}
        onChange={setInput}
        onSubmit={() => sendQuestion(input)}
        loading={loading}
        placeholder={t('chat_hv_ph')}
        hint={t('chat_hv_hint')}
      />
    </NlChatPanel>
  )

  return (
    <NlChatRoot embedded={embedded}>
      <NlHistorySidebar
        sessions={sessions}
        selectedId={selectedSessionId}
        search={historySearch}
        onSearchChange={setHistorySearch}
        onSelect={id => setSelectedSessionId(id)}
        onNew={startNewChat}
        onDelete={id => deleteSessionMutation.mutate(id)}
        onClearAll={() => {
          if (window.confirm(t('chat_hv_clear_confirm'))) {
            clearAllMutation.mutate()
          }
        }}
        loading={sessionsLoading}
      />
      {chatPanel}
    </NlChatRoot>
  )
}
