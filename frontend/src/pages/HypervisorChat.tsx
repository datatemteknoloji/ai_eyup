import { useState, useRef, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { API_BASE_URL } from '../config/api'
import {
  Send, Cpu, Server, MemoryStick, HardDrive, Zap,
  MessageSquare, Lightbulb, Loader2, AlertCircle,
  ChevronDown, ChevronUp, RefreshCw, FileDown,
} from 'lucide-react'
import { exportMarkdownToPrintWindow } from '../utils/pdfExport'

// ── Types ────────────────────────────────────────────────────────────────────

interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  intents?: string[]
  latency_ms?: number
  error?: string | null
  timestamp: Date
}

interface Suggestions {
  suggestions: string[]
  sample_vms: string[]
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
  general:       { label: 'Genel',         color: 'bg-slate-500/20 text-slate-300' },
}

function IntentBadges({ intents }: { intents: string[] }) {
  return (
    <div className="flex flex-wrap gap-1 mt-1">
      {intents.map(intent => {
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
    <div className="flex items-center gap-3 px-4 py-2 bg-slate-800/50 border-b border-slate-700/50 text-xs text-slate-400 overflow-x-auto">
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
  onSelect,
}: {
  suggestions: string[]
  onSelect: (q: string) => void
}) {
  const [expanded, setExpanded] = useState(false)
  const shown = expanded ? suggestions : suggestions.slice(0, 4)

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 text-xs text-slate-500">
        <Lightbulb size={12} />
        <span>Örnek sorular</span>
      </div>
      <div className="flex flex-wrap gap-2">
        {shown.map(s => (
          <button
            key={s}
            onClick={() => onSelect(s)}
            className="text-xs px-3 py-1.5 rounded-full bg-slate-700/70 hover:bg-slate-700 text-slate-300 hover:text-white border border-slate-600/50 hover:border-blue-500/40 transition-all"
          >
            {s}
          </button>
        ))}
        {suggestions.length > 4 && (
          <button
            onClick={() => setExpanded(e => !e)}
            className="text-xs px-3 py-1.5 rounded-full bg-blue-900/30 text-blue-400 hover:text-blue-300 border border-blue-500/30 flex items-center gap-1 transition-all"
          >
            {expanded ? <ChevronUp size={12} /> : <ChevronDown size={12} />}
            {expanded ? 'Daha az' : `+${suggestions.length - 4} daha`}
          </button>
        )}
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
        {!isUser && msg.intents && msg.intents.length > 0 && (
          <IntentBadges intents={msg.intents} />
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
                title: 'Hypervisor Asistan Yanıtı',
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

// ── Typing indicator ──────────────────────────────────────────────────────────

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
          <div className="flex gap-0.5 ml-1">
            {[0, 1, 2].map(i => (
              <div
                key={i}
                className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-bounce"
                style={{ animationDelay: `${i * 0.15}s` }}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────────

export default function HypervisorChat({ embedded = false }: { embedded?: boolean }) {
  const [messages, setMessages] = useState<Message[]>([])
  const [input, setInput] = useState('')
  const [loading, setLoading] = useState(false)
  const bottomRef = useRef<HTMLDivElement>(null)
  const inputRef = useRef<HTMLTextAreaElement>(null)

  const { data: suggestions } = useQuery<Suggestions>({
    queryKey: ['hv-suggestions'],
    queryFn: async () => {
      const r = await fetch(`${API_BASE_URL}/hypervisors/ask/suggestions`)
      if (!r.ok) throw new Error('Suggestions error')
      return r.json()
    },
    staleTime: 60_000,
  })

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages, loading])

  const history = messages.map(m => ({ role: m.role, content: m.content }))

  async function sendQuestion(q: string) {
    if (!q.trim() || loading) return

    const userMsg: Message = {
      id: Date.now().toString(),
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
          history: history.slice(-6),
        }),
      })
      const data = await res.json()

      const assistantMsg: Message = {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: data.answer || data.detail || 'Yanıt alınamadı.',
        intents: data.intents,
        latency_ms: data.latency_ms,
        error: data.error,
        timestamp: new Date(),
      }
      setMessages(prev => [...prev, assistantMsg])
    } catch (err) {
      setMessages(prev => [...prev, {
        id: (Date.now() + 1).toString(),
        role: 'assistant',
        content: 'Bağlantı hatası. Lütfen tekrar deneyin.',
        error: 'connection_error',
        timestamp: new Date(),
      }])
    } finally {
      setLoading(false)
      setTimeout(() => inputRef.current?.focus(), 100)
    }
  }

  function handleKeyDown(e: React.KeyboardEvent<HTMLTextAreaElement>) {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      sendQuestion(input)
    }
  }

  function clearChat() {
    setMessages([])
    setInput('')
    inputRef.current?.focus()
  }

  const isEmpty = messages.length === 0

  return (
    <div className={`flex flex-col bg-slate-900 ${embedded ? 'h-[calc(100vh-220px)] min-h-[500px]' : 'h-screen'}`}>
      {/* Header — hidden when embedded inside another page */}
      {!embedded && (
      <div className="flex items-center justify-between px-6 py-4 border-b border-slate-700/50 bg-slate-900">
        <div className="flex items-center gap-3">
          <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center shadow-lg shadow-blue-500/20">
            <HardDrive size={18} className="text-white" />
          </div>
          <div>
            <h1 className="text-white font-semibold text-lg">Hypervisor Asistanı</h1>
            <p className="text-slate-400 text-xs">ESX, KVM ve VM'lerinize doğal dille sorun</p>
          </div>
        </div>
        {messages.length > 0 && (
          <button
            onClick={clearChat}
            className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white transition-colors px-3 py-1.5 rounded-lg hover:bg-slate-800"
          >
            <RefreshCw size={13} />
            Temizle
          </button>
        )}
      </div>
      )}
      {embedded && messages.length > 0 && (
        <div className="flex justify-end px-6 py-2 border-b border-slate-700/50">
          <button onClick={clearChat} className="flex items-center gap-1.5 text-xs text-slate-400 hover:text-white px-3 py-1.5 rounded-lg hover:bg-slate-800 transition-colors">
            <RefreshCw size={13} /> Temizle
          </button>
        </div>
      )}

      {/* Quick stats */}
      <QuickStatsBar />

      {/* Chat area */}
      <div className="flex-1 overflow-y-auto px-4 py-4">
        {isEmpty ? (
          /* Welcome screen */
          <div className="max-w-2xl mx-auto mt-8 space-y-6">
            <div className="text-center space-y-2">
              <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-blue-600 to-indigo-700 flex items-center justify-center mx-auto shadow-xl shadow-blue-500/20">
                <HardDrive size={28} className="text-white" />
              </div>
              <h2 className="text-xl font-semibold text-white">Hypervisor Ortamınızı Sorgulayın</h2>
              <p className="text-slate-400 text-sm max-w-md mx-auto">
                ESX hostlarınız, VM envanteriniz, kapasite durumunuz ve daha fazlası
                hakkında Türkçe sorular sorun.
              </p>
            </div>

            <div className="grid grid-cols-3 gap-3">
              {[
                { icon: <Server size={20} className="text-blue-400" />, label: 'Host Durumu', desc: 'CPU, RAM, datastore doluluk' },
                { icon: <Cpu size={20} className="text-purple-400" />, label: 'VM Envanteri', desc: 'OS, tools, güç durumu' },
                { icon: <MemoryStick size={20} className="text-green-400" />, label: 'Karşılaştırma', desc: 'İki VM yan yana analiz' },
              ].map(card => (
                <div key={card.label} className="bg-slate-800/60 border border-slate-700/50 rounded-xl p-4 text-center space-y-2">
                  <div className="flex justify-center">{card.icon}</div>
                  <div className="text-white text-sm font-medium">{card.label}</div>
                  <div className="text-slate-400 text-xs">{card.desc}</div>
                </div>
              ))}
            </div>

            {suggestions && (
              <SuggestionChips
                suggestions={suggestions.suggestions}
                onSelect={q => { setInput(q); setTimeout(() => sendQuestion(q), 50) }}
              />
            )}
          </div>
        ) : (
          /* Messages */
          <div className="max-w-3xl mx-auto">
            {messages.map(msg => (
              <MessageBubble key={msg.id} msg={msg} />
            ))}
            {loading && <TypingIndicator />}
            <div ref={bottomRef} />
          </div>
        )}
      </div>

      {/* Inline suggestions when chatting */}
      {!isEmpty && suggestions && (
        <div className="px-4 pb-2 max-w-3xl mx-auto w-full">
          <div className="flex gap-2 overflow-x-auto pb-1 scrollbar-hide">
            {suggestions.suggestions.slice(0, 5).map(s => (
              <button
                key={s}
                onClick={() => { setInput(s); setTimeout(() => sendQuestion(s), 50) }}
                className="text-xs px-3 py-1.5 rounded-full bg-slate-800 hover:bg-slate-700 text-slate-400 hover:text-white border border-slate-700/50 whitespace-nowrap transition-all flex-shrink-0"
              >
                {s}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Input bar */}
      <div className="px-4 pb-4 max-w-3xl mx-auto w-full">
        <div className="flex items-end gap-2 bg-slate-800 border border-slate-700/50 rounded-2xl px-4 py-3 focus-within:border-blue-500/50 transition-colors">
          <textarea
            ref={inputRef}
            value={input}
            onChange={e => setInput(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Sorunuzu yazın… (ör: Kaç ESX hostum var?)"
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
          Enter ile gönder · Shift+Enter yeni satır
        </p>
      </div>
    </div>
  )
}
